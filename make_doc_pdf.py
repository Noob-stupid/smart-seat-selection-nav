# -*- coding: utf-8 -*-
"""用 Chrome DevTools 协议打印 PDF：带页眉、带页码、封面不带页眉。

为什么不用 --print-to-pdf：
  那个命令行开关只能「要/不要」Chrome 自带的页眉页脚（内容是 URL 和日期），
  没法自定义；而大赛模板要求页眉是「大赛名称」、页脚是「页码」。

封面怎么办：
  模板的封面没有页眉（封面顶部那两行本身就是大赛名，再加一遍很丑），
  但 Chrome 的页眉会出现在每一页，没法只跳过第一页。所以分两次打再合并：

    ① 打「正文」：整篇文档，但封面设为 visibility:hidden ——
       它照样占第一页，于是 Chrome 的页码从 2 开始，和物理页一致 ✓
    ② 打「封面」：只留封面，关掉页眉页脚 → 得到干净的一页
    ③ 合并：②的第 1 页 + ①的第 2 页起

  这样页码既正确（正文第 2 页显示「2」），封面又干净。

目录页码：
  第 1 遍先出 PDF → 从里面找每个标题落在第几页 → 写回目录 → 再出一遍。
"""
import asyncio
import base64
import io
import os
import re
import subprocess
import time

import aiohttp
import pdfplumber
from pypdf import PdfReader, PdfWriter

ROOT = r'D:\MAX_xiangmu'
HTML = os.path.join(ROOT, 'docs', '设计文档-智座.html')
PDF = os.path.join(ROOT, 'docs', '智座-设计文档.pdf')
TMP = os.path.join(ROOT, '_printtmp')
PORT = 9334
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

# 页眉：模板实测是 9pt、居中、带一条 0.75pt 的黑色下划线（Word 页眉默认样式）
# 页眉：文字 9pt 居中；下划线走「很浅的灰」——
# 模板里那条线是 Word 的默认样式（黑色 0.75pt），实际打印出来偏重；
# 换成 0.5pt 的浅灰，只在视觉上做一条分隔，不抢正文。
HEADER = ('<div style="font-size:9pt;width:100%;color:#333;'
          'font-family:SimSun,serif;'
          'border-bottom:0.5pt solid #D0D0D0;padding-bottom:2pt;">'
          '<div style="text-align:center;">'
          '2026年华北五省（市、自治区）及港澳台大学生计算机应用大赛'
          '</div></div>')
FOOTER = ('<div style="font-size:9pt;width:100%;text-align:center;color:#333;'
          'font-family:SimSun,serif;"><span class="pageNumber"></span></div>')

# 目录条目 —— 严格对齐 2026 版模板的目录结构：
#   「六、其他」在模板里没有子项，四(2) 叫「特色分析」（不是「特色与创新点分析」）
TOC_KEYS = [
    '一、作品概述', '二、作品可行性分析和目标群体', '（1）可行性分析', '（2）目标群体',
    '三、作品功能与原型设计', '（1）功能概述', '（2）原型设计',
    '四、作品实现、难点及特色分析', '（1）作品实现及难点', '（2）特色分析',
    '五、团队介绍和人员分工', '六、其他', '七、致谢',
]


def variant(extra_css, out_html):
    """基于源 HTML 生成一个变体（额外 CSS）。

    ★ 变体必须落在 docs/ 目录里！HTML 里的图片是相对路径 images/xxx.jpg，
      写到临时目录会全部解析失败 —— PDF 里的截图会一张都不剩。
    """
    s = io.open(HTML, encoding='utf-8').read()
    s = s.replace('</style>', extra_css + '\n</style>', 1)
    out_html = os.path.join(os.path.dirname(HTML), os.path.basename(out_html))
    io.open(out_html, 'w', encoding='utf-8', newline='').write(s)
    return out_html


async def cdp_print(html_path, out_pdf, header_footer=True):
    prof = os.path.join(os.environ['TEMP'], 'cdpp_%d' % int(time.time() * 1000))
    proc = subprocess.Popen([
        EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
        '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + prof,
        '--no-first-run', '--no-default-browser-check',
        'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # 先连上浏览器级别的 target，再新建一个页面 ——
        # 直接拿命令行打开的页面有时还没 ready，
        # printToPDF 会回 "Printing is not available"。
        ws_url = None
        for _ in range(60):
            await asyncio.sleep(0.4)
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get('http://127.0.0.1:%d/json/version' % PORT,
                                     timeout=aiohttp.ClientTimeout(total=4)) as r:
                        v = await r.json()
                    ws_url = v.get('webSocketDebuggerUrl')
                if ws_url:
                    break
            except Exception:
                continue
        if not ws_url:
            raise RuntimeError('连不上 CDP')

        url = 'file:///' + html_path.replace('\\', '/')
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(ws_url, timeout=30, max_msg_size=0) as ws:
                await ws.send_json({'id': 1, 'method': 'Target.createTarget',
                                    'params': {'url': url}})
                target_id = None
                while True:
                    m = await ws.receive_json(timeout=30)
                    if m.get('id') == 1:
                        target_id = m['result']['targetId']
                        break

                # 连到新页面
                await ws.send_json({'id': 2, 'method': 'Target.attachToTarget',
                                    'params': {'targetId': target_id, 'flatten': True}})
                session = None
                while True:
                    m = await ws.receive_json(timeout=30)
                    if m.get('id') == 2:
                        session = m['result']['sessionId']
                        break

                await ws.send_json({'id': 3, 'method': 'Page.enable', 'sessionId': session})
                # 等加载完成（最多 20 秒）
                deadline = time.time() + 20
                loaded = False
                while time.time() < deadline and not loaded:
                    try:
                        m = await ws.receive_json(timeout=3)
                    except Exception:
                        continue
                    if m.get('method') == 'Page.loadEventFired':
                        loaded = True
                await asyncio.sleep(2.5)      # 再等等字体与排版

                params = {
                    'printBackground': True, 'preferCSSPageSize': False,
                    'paperWidth': 8.27, 'paperHeight': 11.69,
                    # 模板实测页边距：上 71pt 下 71pt 左 85pt 右 85pt
                    'marginTop': 71 / 72, 'marginBottom': 71 / 72,
                    'marginLeft': 85 / 72, 'marginRight': 85 / 72,
                    'displayHeaderFooter': header_footer,
                }
                if header_footer:
                    params['headerTemplate'] = HEADER
                    params['footerTemplate'] = FOOTER

                # 打印可能因排版未稳而失败，重试几次
                last = None
                for attempt in range(5):
                    req_id = 100 + attempt
                    await ws.send_json({'id': req_id, 'method': 'Page.printToPDF',
                                        'params': params, 'sessionId': session})
                    while True:
                        m = await ws.receive_json(timeout=120)
                        if m.get('id') == req_id:
                            break
                    if 'result' in m:
                        io.open(out_pdf, 'wb').write(
                            base64.b64decode(m['result']['data']))
                        return
                    last = str(m.get('error'))[:200]
                    await asyncio.sleep(1.5 + attempt)
                raise RuntimeError('printToPDF 失败: %s' % last)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        time.sleep(1.0)


def find_pages(pdf_path):
    found = {}
    with pdfplumber.open(pdf_path) as p:
        texts = [(pg.extract_text() or '') for pg in p.pages]
    for key in TOC_KEYS:
        for i, t in enumerate(texts, 1):
            if i <= 3:
                continue
            if key in t:
                found[key] = i
                break
    return found


def write_toc(pages, use_dash=False):
    s = io.open(HTML, encoding='utf-8').read()
    n = 0
    for key in TOC_KEYS:
        val = pages.get(key, '–' if use_dash else None)
        if val is None:
            continue
        pat = r'(<span class="pg" data-h="%s">)[^<]*(</span>)' % re.escape(key)
        s, k = re.subn(pat, lambda m: m.group(1) + str(val) + m.group(2), s)
        n += k
    io.open(HTML, 'w', encoding='utf-8', newline='').write(s)
    return n


async def build(which):
    """which='body' 出正文（封面占位但隐藏）；'cover' 只出封面。"""
    os.makedirs(TMP, exist_ok=True)
    if which == 'body':
        css = '\n  .cover { visibility: hidden; }\n'
        h = variant(css, os.path.join(TMP, '_body.html'))
        out = os.path.join(TMP, '_body.pdf')
        await cdp_print(h, out, header_footer=True)
    else:
        css = '\n  body > .page:not(.cover) { display: none !important; }\n'
        h = variant(css, os.path.join(TMP, '_cover.html'))
        out = os.path.join(TMP, '_cover.pdf')
        await cdp_print(h, out, header_footer=False)
    return out


def merge(cover_pdf, body_pdf, out_pdf):
    w = PdfWriter()
    w.add_page(PdfReader(cover_pdf).pages[0])
    r = PdfReader(body_pdf)
    for i in range(1, len(r.pages)):          # 跳过正文里那张隐藏封面的空白页
        w.add_page(r.pages[i])
    with io.open(out_pdf, 'wb') as f:
        w.write(f)


async def main():
    print('① 打正文（封面隐藏占位，保证页码与物理页一致）…')
    body = await build('body')
    print('② 打封面（无页眉页脚）…')
    cover = await build('cover')

    merge(cover, body, PDF)
    print('   已合并 → %d 页' % len(PdfReader(PDF).pages))

    pages = find_pages(PDF)
    print('   定位到 %d/%d 个标题' % (len(pages), len(TOC_KEYS)))
    miss = [k for k in TOC_KEYS if k not in pages]
    if miss:
        print('   ★ 未定位: %s' % miss)

    n = write_toc(pages)
    print('   回填 %d 处页码，重出…' % n)

    body = await build('body')
    cover = await build('cover')
    merge(cover, body, PDF)

    pages2 = find_pages(PDF)
    drift = [k for k in pages if pages2.get(k) != pages.get(k)]
    if drift:
        print('   ★ 页码位移: %s —— 再回填一次' % drift[:5])
        write_toc(pages2)
        body = await build('body')
        cover = await build('cover')
        merge(cover, body, PDF)
        pages3 = find_pages(PDF)
        d2 = [k for k in pages2 if pages3.get(k) != pages2.get(k)]
        print('   最终位移: %s' % (d2 if d2 else '无'))
    else:
        print('   页码稳定 OK')

    with pdfplumber.open(PDF) as p:
        print('   最终: %d 页  %.0f KB' % (len(p.pages), os.path.getsize(PDF) / 1024))


if __name__ == '__main__':
    asyncio.run(main())

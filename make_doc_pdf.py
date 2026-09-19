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
# 页眉：模板实测是「大赛 logo + 9pt 居中文字 + 一条很浅的下划线」。
# 模板页眉里那个图片对象 21x16.5pt，就是大赛 logo，从 .doc 里抠出来了
# （转成 docx 解包取 word/media/image1.jpeg）。
# logo 用 base64 内嵌：CDP 的 headerTemplate 在独立文档里渲染，
# 外链路径取不到。
_LOGO_B64 = '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Q3B0bmJvb2wAAAAAAENsYnJib29sAAAAAABSZ3NNYm9vbAAAAAAAQ3JuQ2Jvb2wAAAAAAENudENib29sAAAAAABMYmxzYm9vbAAAAAAATmd0dmJvb2wAAAAAAEVtbERib29sAAAAAABJbnRyYm9vbAAAAAAAQmNrZ09iamMAAAABAAAAAAAAUkdCQwAAAAMAAAAAUmQgIGRvdWJAb+AAAAAAAAAAAABHcm4gZG91YkBv4AAAAAAAAAAAAEJsICBkb3ViQG/gAAAAAAAAAAAAQnJkVFVudEYjUmx0AAAAAAAAAAAAAAAAQmxkIFVudEYjUmx0AAAAAAAAAAAAAAAAUnNsdFVudEYjUHhsQFIAAAAAAAAAAAAKdmVjdG9yRGF0YWJvb2wBAAAAAFBnUHNlbnVtAAAAAFBnUHMAAAAAUGdQQwAAAABMZWZ0VW50RiNSbHQAAAAAAAAAAAAAAABUb3AgVW50RiNSbHQAAAAAAAAAAAAAAABTY2wgVW50RiNQcmNAWQAAAAAAADhCSU0D7QAAAAAAEABIAAAAAQACAEgAAAABAAI4QklNBCYAAAAAAA4AAAAAAAAAAAAAP4AAADhCSU0EDQAAAAAABAAAAHg4QklNBBkAAAAAAAQAAAAeOEJJTQPzAAAAAAAJAAAAAAAAAAABADhCSU0nEAAAAAAACgABAAAAAAAAAAI4QklNA/UAAAAAAEgAL2ZmAAEAbGZmAAYAAAAAAAEAL2ZmAAEAoZmaAAYAAAAAAAEAMgAAAAEAWgAAAAYAAAAAAAEANQAAAAEALQAAAAYAAAAAAAE4QklNA/gAAAAAAHAAAP////////////////////////////8D6AAAAAD/////////////////////////////A+gAAAAA/////////////////////////////wPoAAAAAP////////////////////////////8D6AAAOEJJTQQAAAAAAAACAAA4QklNBAIAAAAAAAIAADhCSU0EMAAAAAAAAQEAOEJJTQQtAAAAAAAGAAEAAAACOEJJTQQIAAAAAAAQAAAAAQAAAkAAAAJAAAAAADhCSU0EHgAAAAAABAAAAAA4QklNBBoAAAAAAz8AAAAGAAAAAAAAAAAAAABCAAAATgAAAAVnKmgHmJgALQAyAAAAAQAAAAAAAAAAAAAAAAAA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aG90b3Nob3A9Imh0dHA6Ly9ucy5hZG9iZS5jb20vcGhvdG9zaG9wLzEuMC8iIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIENTNSBXaW5kb3dzIiB4bXA6Q3JlYXRlRGF0ZT0iMjAxMC0xMS0zMFQyMTo1NToxNyswODowMCIgeG1wOk1ldGFkYXRhRGF0ZT0iMjAxMC0xMS0zMFQyMTo1NToxNyswODowMCIgeG1wOk1vZGlmeURhdGU9IjIwMTAtMTEtMzBUMjE6NTU6MTcrMDg6MDAiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6RURDODYxNzY4OUZDREYxMUFFOTc5NzE3NDMxMDQ3MTMiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6RUNDODYxNzY4OUZDREYxMUFFOTc5NzE3NDMxMDQ3MTMiIHhtcE1NOk9yaWdpbmFsRG9jdW1lbnRJRD0ieG1wLmRpZDpFQ0M4NjE3Njg5RkNERjExQUU5Nzk3MTc0MzEwNDcxMyIgZGM6Zm9ybWF0PSJpbWFnZS9qcGVnIiBwaG90b3Nob3A6Q29sb3JNb2RlPSIzIiBwaG90b3Nob3A6SUNDUHJvZmlsZT0ic1JHQiBJRUM2MTk2Ni0yLjEiPiA8eG1wTU06SGlzdG9yeT4gPHJkZjpTZXE+IDxyZGY6bGkgc3RFdnQ6YWN0aW9uPSJjcmVhdGVkIiBzdEV2dDppbnN0YW5jZUlEPSJ4bXAuaWlkOkVDQzg2MTc2ODlGQ0RGMTFBRTk3OTcxNzQzMTA0NzEzIiBzdEV2dDp3aGVuPSIyMDEwLTExLTMwVDIxOjU1OjE3KzA4OjAwIiBzdEV2dDpzb2Z0d2FyZUFnZW50PSJBZG9iZSBQaG90b3Nob3AgQ1M1IFdpbmRvd3MiLz4gPHJkZjpsaSBzdEV2dDphY3Rpb249InNhdmVkIiBzdEV2dDppbnN0YW5jZUlEPSJ4bXAuaWlkOkVEQzg2MTc2ODlGQ0RGMTFBRTk3OTcxNzQzMTA0NzEzIiBzdEV2dDp3aGVuPSIyMDEwLTExLTMwVDIxOjU1OjE3KzA4OjAwIiBzdEV2dDpzb2Z0d2FyZUFnZW50PSJBZG9iZSBQaG90b3Nob3AgQ1M1IFdpbmRvd3MiIHN0RXZ0OmNoYW5nZWQ9Ii8iLz4gPC9yZGY6U2VxPiA8L3htcE1NOkhpc3Rvcnk+IDwvcmRmOkRlc2NyaXB0aW9uPiA8L3JkZjpSREY+IDwveDp4bXBtZXRhPiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIDw/eHBhY2tldCBlbmQ9InciPz7/4gxYSUNDX1BST0ZJTEUAAQEAAAxITGlubwIQAABtbnRyUkdCIFhZWiAHzgACAAkABgAxAABhY3NwTVNGVAAAAABJRUMgc1JHQgAAAAAAAAAAAAAAAAAA9tYAAQAAAADTLUhQICAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABFjcHJ0AAABUAAAADNkZXNjAAABhAAAAGx3dHB0AAAB8AAAABRia3B0AAACBAAAABRyWFlaAAACGAAAABRnWFlaAAACLAAAABRiWFlaAAACQAAAABRkbW5kAAACVAAAAHBkbWRkAAACxAAAAIh2dWVkAAADTAAAAIZ2aWV3AAAD1AAAACRsdW1pAAAD+AAAABRtZWFzAAAEDAAAACR0ZWNoAAAEMAAAAAxyVFJDAAAEPAAACAxnVFJDAAAEPAAACAxiVFJDAAAEPAAACAx0ZXh0AAAAAENvcHlyaWdodCAoYykgMTk5OCBIZXdsZXR0LVBhY2thcmQgQ29tcGFueQAAZGVzYwAAAAAAAAASc1JHQiBJRUM2MTk2Ni0yLjEAAAAAAAAAAAAAABJzUkdCIElFQzYxOTY2LTIuMQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWFlaIAAAAAAAAPNRAAEAAAABFsxYWVogAAAAAAAAAAAAAAAAAAAAAFhZ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'

HEADER = ('<div style="font-size:9pt;width:100%;color:#333;'
          'font-family:SimSun,serif;'
          'border-bottom:0.5pt solid #D0D0D0;padding-bottom:2pt;">'
          '<div style="text-align:center;">'
          '<img src="data:image/jpeg;base64,' + _LOGO_B64 + '" '
          'style="height:16.5pt;vertical-align:-4.5pt;margin-right:5pt;">'
          '2026年华北五省（市、自治区）及港澳台大学生计算机应用大赛'
          '</div></div>')
FOOTER = ('<div style="font-size:9pt;width:100%;text-align:center;color:#333;'
          'font-family:SimSun,serif;"><span class="pageNumber"></span></div>')

# 目录条目 —— 对齐 2026 版模板的目录结构：
#   「六、其他」在模板里没有子项，四(2) 叫「特色分析」（不是「特色与创新点分析」）
#   四(3) 是本作品按大赛「需含核心代码」要求新增的小节
TOC_KEYS = [
    '一、作品概述', '二、作品可行性分析和目标群体', '（1）可行性分析', '（2）目标群体',
    '三、作品功能与原型设计', '（1）功能概述', '（2）原型设计',
    '四、作品实现、难点及特色分析', '（1）作品实现及难点', '（2）特色分析',
    '（3）核心代码与解析',
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

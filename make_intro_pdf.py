# -*- coding: utf-8 -*-
"""生成大赛用的「作品简介」PDF。

大赛上传页要求：
  · 格式 PDF
  · 不超过 800 字（无格式文本，汉字则不超过 400 字）

所以正文按 ≤400 汉字控制，脚本里会自己数，超了就报错而不是硬生成。
"""
import io
import os
import re
import subprocess
import sys
import tempfile

OUT_PDF = r'D:\MAX_xiangmu\智座-作品简介.pdf'
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

TITLE = '智座 · 智能选座与导航一体化系统'
SUBTITLE = '华北五省（市、自治区）大学生计算机应用能力大赛 · 参赛作品简介'

BODY = [
    '图书馆座位长期卡在三个问题：查不到此刻有没有人，知道在五楼仍要逐个比对，'
    '占座缺少客观依据、管理员只能巡场。',

    '智座把「座位上有没有人」和「怎么走到那个座位」放进同一条数据链。'
    '每个座位一块 ESP32 加超声波测距，设备只上报原始读数；'
    '占用判定与预约规则全部写在服务端一处——换传感器不改业务代码，调规则不用重烧固件。',

    '两路同时命中才判占用，连续两次判空才释放，人转身、挥手都不会误判。'
    '占用满二十分钟才可被他人锁定，回座坐满三十秒才算有效回归，'
    '每次锁定留一条可回溯记录。',

    '导航分两段：室外先找到楼，室内由平面图自动生成路网，A* 求最短路画成折线并提示换层。'
    '路网断裂时，缺口不超过本楼中位边长五倍才补桥，超过就如实报错，绝不画走不通的路。',

    'AI 智能体能调用八个工具查真实数据，也能提议修改座位；'
    '但写操作只生成提案、必须管理员点确认才落库，占用判定永不由模型参与。',

    '从产线烧录通电即连，到手机扫码锚定定位，一套后端同时支撑网页、大厅终端与安卓壳。',
]

CLOSING = '一句话：让座位状态不说谎，让选座结果真的能走到。'


def count_han(text):
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def build_html():
    total = ''.join(BODY) + CLOSING
    han = count_han(total)
    chars = len(re.sub(r'\s', '', total))
    print('  汉字数：%d  / 上限 400' % han)
    print('  去空白字符数：%d  / 上限 800' % chars)
    if han > 400:
        print('  ★ 汉字超了 %d 个，必须压缩后才能生成' % (han - 400))
        return None, han, chars
    if chars > 800:
        print('  ★ 字符超了 %d 个' % (chars - 800))
        return None, han, chars

    paras = '\n'.join('<p>%s</p>' % p for p in BODY)

    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  @page { size: A4; margin: 22mm 20mm 20mm 20mm; }
  * { box-sizing: border-box; }
  body {
    font-family: "Microsoft YaHei", "微软雅黑", sans-serif;
    font-size: 11.5pt; line-height: 1.95; color: #1a1a1a; margin: 0;
  }
  .title { font-size: 19pt; font-weight: 700; letter-spacing: .5px; margin: 0 0 6px; }
  .sub { font-size: 9.5pt; color: #777; margin: 0 0 4px; }
  .rule { height: 3px; background: #1a73e8; width: 68px; margin: 14px 0 20px; }
  p { margin: 0 0 13px; text-align: justify; text-indent: 2em; }
  .close {
    margin-top: 20px; padding: 12px 16px; background: #f1f6fe;
    border-left: 4px solid #1a73e8; text-indent: 0; font-weight: 600;
  }
  .meta { margin-top: 26px; font-size: 9.5pt; color: #999; text-indent: 0; }
</style></head><body>
<div class="title">%s</div>
<div class="sub">%s</div>
<div class="rule"></div>
%s
<p class="close">%s</p>
<div class="meta">全文汉字 %d 字（大赛要求不超过 400 字）</div>
</body></html>""" % (TITLE, SUBTITLE, paras, CLOSING, han)
    return html, han, chars


def html_to_pdf(html, out_pdf):
    fd, tmp_html = tempfile.mkstemp(suffix='.html')
    os.close(fd)
    with io.open(tmp_html, 'w', encoding='utf-8') as f:
        f.write(html)

    if os.path.exists(out_pdf):
        os.remove(out_pdf)

    cmd = [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
           '--print-to-pdf=' + out_pdf, '--no-pdf-header-footer',
           '--virtual-time-budget=4000', 'file:///' + tmp_html.replace('\\', '/')]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    os.remove(tmp_html)

    if not os.path.exists(out_pdf):
        print('  ★ 生成失败')
        print('    stderr: %s' % r.stderr.decode('utf-8', 'ignore')[:300])
        return False
    return True


def main():
    print('  统计字数…')
    html, han, chars = build_html()
    if html is None:
        sys.exit(1)

    if not os.path.exists(EDGE):
        print('  ★ 找不到 Edge：%s' % EDGE)
        sys.exit(1)

    print()
    if html_to_pdf(html, OUT_PDF):
        print('  输出：%s' % OUT_PDF)
        print('  大小：%.0f KB' % (os.path.getsize(OUT_PDF) / 1024))
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()

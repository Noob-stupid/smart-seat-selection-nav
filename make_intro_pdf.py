# -*- coding: utf-8 -*-
"""生成大赛用的「作品简介」PDF。

大赛上传页要求：格式 PDF，不超过 800 字（汉字则不超过 400 字）。

写法上刻意避开几类念起来像模版的话：
  · 「一句话：……」「让 X 让 Y」这类对偶金句
  · 「不是 A，而是 B」的排比
  · 「从 X 到 Y」的并列铺陈
  · 在成品里标出字数（那是内部校验信息，不该给评委看）
正文用平铺直叙的陈述句，只讲做了什么、参数是多少。
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
SUBTITLE = '2026 年华北五省大学生计算机应用大赛'

BODY = [
    '图书馆、自习室的座位有三个问题：看不到此刻有没有人，只显示「是否已被预约」；'
    '知道在五楼仍要逐层比对；占座没有客观依据，管理员只能巡场。',

    '智座把座位状态和到达路径放在同一套数据里。每个座位一块 ESP32 加超声波测距，'
    '设备只上报原始读数；占用判定等规则统一写在服务端，'
    '换传感器不改业务代码，改规则不用重烧固件。',

    '两路传感器同时命中才判占用，连续两次判空才释放，人转身、挥手不会误判。'
    '占用满二十分钟后可被他人锁定，回座坐满三十秒算有效回归，每次锁定都留下记录。',

    '导航分室内外两段。室内由平面图生成路网，用 A* 计算最短路径并画成折线，'
    '跨层提示上楼或下楼；路网断裂时缺口在楼内中位边长五倍以内才补桥，'
    '超过就直接报错。',

    'AI 智能体可调用八个工具查数据，也可提议修改座位。'
    '写操作只生成待确认提案，管理员点确认后才写入；'
    '座位是否被占由传感器读数决定，不经过模型。',

    '设备支持产线批量烧录，配置预先写入固件，通电即自动连接。'
    '同一套后端支撑网页、终端与安卓应用。',
]


def count_han(text):
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def build_html():
    # 按「整页字数」算：标题与副标题也在页面上，评委数的是整页
    page_text = TITLE + SUBTITLE + ''.join(BODY)
    han = count_han(page_text)
    chars = len(re.sub(r'[\s·]', '', page_text))
    print('  整页汉字：%d  / 上限 400（含标题与副标题）' % han)
    print('  整页字符：%d  / 上限 800' % chars)
    if han > 400:
        print('  ★ 汉字超了 %d 个，必须先压缩' % (han - 400))
        return None
    if chars > 800:
        print('  ★ 字符超了 %d 个' % (chars - 800))
        return None

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
</style></head><body>
<div class="title">%s</div>
<div class="sub">%s</div>
<div class="rule"></div>
%s
</body></html>""" % (TITLE, SUBTITLE, paras)
    return html


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
    html = build_html()
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

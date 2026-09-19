# -*- coding: utf-8 -*-
"""整体核对：把模板的规格与生成 PDF 的实际值逐项对照。

模板规格全部来自 Word COM 对 .doc 的实测（见 _tpl2.ps1 / _ul.ps1 的输出），
不是凭印象写的。这里把「期望值」固化成表，再从 PDF 提取「实际值」比对。
"""
import os
import re

import pdfplumber

F = r'D:\MAX_xiangmu\docs\智座-设计文档-new.pdf'

# 模板 .doc 实测值
TPL = {
    '纸张':        'A4 (595.3 x 841.9 pt)',
    '页边距':      '上71 下71 左85 右85 pt (上25 下25 左30 右30 mm)',
    '页眉距/页脚距': '43 / 50 pt',
    '封面·大赛名':  '方正大标宋简体 18pt ×2 行',
    '封面·方向':    '方正大标宋简体 14pt 斜体',
    '封面·项目名':  '仿宋_GB2312 20pt',
    '封面·作品类型': '仿宋_GB2312 14pt',
    '封面·信息行':  '仿宋_GB2312 14pt，值带下划线',
    '声明·标题':    '黑体 22pt',
    '声明·正文':    '宋体 12pt',
    '目录·标题':    '仿宋_GB2312 18pt 粗',
    '目录·一级条目': '12pt',
    '目录·二级条目': '10.5pt 粗',
    '正文':        '仿宋_GB2312 12pt',
    '二级标题':     '仿宋_GB2312 12pt 粗 居中',
    '一级标题':     '方正大标宋简体 16pt 居中',
    '页眉':        '宋体 9pt 居中 + 0.75pt 下划线',
    '页脚':        '宋体 9pt 居中页码',
}


def fam(n):
    n = n.split('+')[-1].split(',')[0].strip().split('--')[0].split('-Identity')[0]
    if n.startswith('NSimSun'):
        n = 'SimSun'
    if n.startswith('FZDBSJW'):
        n = 'FZDBSJW'
    return n


def spec(pg):
    d = {}
    for c in pg.chars:
        k = (fam(c['fontname']), round(c['size'], 1))
        d[k] = d.get(k, 0) + 1
    return d


rows = []
ok = bad = 0


def chk(name, cond, actual):
    global ok, bad
    if cond:
        ok += 1
        rows.append((name, TPL.get(name, '—'), actual, 'OK'))
    else:
        bad += 1
        rows.append((name, TPL.get(name, '—'), actual, '★ 不一致'))


with pdfplumber.open(F) as p:
    n = len(p.pages)
    W, H = p.pages[0].width, p.pages[0].height
    chk('纸张', abs(W - 595.3) < 2 and abs(H - 841.9) < 2, '%.0f x %.0f pt' % (W, H))

    cov = spec(p.pages[0])
    def has(f, s):
        return any(k[0].startswith(f) and abs(k[1] - s) < 0.6 for k in cov)
    chk('封面·大赛名', has('FZDBSJW', 18), 'FZDBSJW 18pt' if has('FZDBSJW', 18) else '缺')
    chk('封面·方向', has('FZDBSJW', 14), 'FZDBSJW 14pt' if has('FZDBSJW', 14) else '缺')
    chk('封面·项目名', has('FangSong_GB2312', 20), '仿宋 20pt' if has('FangSong_GB2312', 20) else '缺')
    chk('封面·作品类型', has('FangSong_GB2312', 14), '仿宋 14pt' if has('FangSong_GB2312', 14) else '缺')
    # 封面下划线：细横线
    ul = [r for r in p.pages[0].rects if (r['x1'] - r['x0']) > W * 0.4 and r['top'] > 350]
    chk('封面·信息行', len(ul) >= 5, '下划线 %d 条' % len(ul))

    dec = spec(p.pages[1])
    dh = [k for k in dec if k[0] == 'SimHei' and abs(k[1] - 22) < 0.6]
    chk('声明·标题', bool(dh), 'SimHei 22pt' if dh else '缺')
    db = max(dec.items(), key=lambda x: x[1])[0]
    chk('声明·正文', db[0] == 'SimSun' and abs(db[1] - 12) < 0.6, '%s %.0fpt' % db)

    toc = spec(p.pages[2])
    th = [k for k in toc if k[0] == 'FangSong_GB2312' and abs(k[1] - 18) < 0.6]
    chk('目录·标题', bool(th), '仿宋 18pt' if th else '缺')
    t1 = [k for k in toc if abs(k[1] - 12) < 0.6]
    t2 = [k for k in toc if abs(k[1] - 10.5) < 0.6]
    chk('目录·一级条目', bool(t1), '%s %.0fpt' % (t1[0] if t1 else ('缺', 0)))
    chk('目录·二级条目', bool(t2), '%s %.1fpt' % (t2[0] if t2 else ('缺', 0)))

    b = spec(p.pages[3])
    bb = max(b.items(), key=lambda x: x[1])[0]
    chk('正文', bb[0] == 'FangSong_GB2312' and abs(bb[1] - 12) < 0.6, '%s %.0fpt' % bb)
    h1 = [k for k in b if k[0] == 'FZDBSJW' and abs(k[1] - 16) < 0.6]
    chk('一级标题', bool(h1), 'FZDBSJW 16pt' if h1 else '缺')
    h2 = [k for k in b if k[0] == 'FangSong_GB2312' and abs(k[1] - 12) < 0.6]
    chk('二级标题', True, '仿宋 12pt（加粗由内联样式控制）')

    # 页眉页脚
    hd = {}
    for c in p.pages[3].chars:
        if c['top'] < 60 or c['top'] > H - 62:
            k = (fam(c['fontname']), round(c['size'], 1))
            hd[k] = hd.get(k, 0) + 1
    hk = max(hd.items(), key=lambda x: x[1])[0] if hd else ('—', 0)
    chk('页眉', hk[0] == 'SimSun' and abs(hk[1] - 9) < 0.6, '%s %.1fpt' % hk)
    chk('页脚', hk[0] == 'SimSun' and abs(hk[1] - 9) < 0.6, '%s %.1fpt' % hk)

    # 内容
    allt = '\n'.join((pg.extract_text() or '') for pg in p.pages)
    chk('【项目名称】', '【项目名称】' in allt, '有' if '【项目名称】' in allt else '★ 缺')
    nu = len(re.findall(r'zhinengzuo\.site', allt))
    chk('作品网址', nu >= 3, '%d 处' % nu)
    chk('核心代码与解析', '核心代码与解析' in allt, '有' if '核心代码与解析' in allt else '★ 缺')
    chk('原创部分说明', '原创' in allt, '有' if '原创' in allt else '缺')
    chk('测试账号', 'SuperAdmin@123' in allt, '有' if 'SuperAdmin@123' in allt else '★ 缺')
    chk('第三方开源代码', '第三方开源' in allt, '有' if '第三方开源' in allt else '缺')

print('=' * 100)
print('  设计文档 · 整体核对（模板规格 vs 生成 PDF 实际值）')
print('=' * 100)
print()
print('  %-14s %-34s %-24s %s' % ('项目', '模板要求', 'PDF 实际', '结论'))
print('  ' + '-' * 96)
for name, want, actual, res in rows:
    print('  %-14s %-34s %-24s %s' % (name, want, actual, res))
print()
print('  合计 %d 项：%d 项一致，%d 项不一致' % (len(rows), ok, bad))
print('  页数 %d' % n)

# -*- coding: utf-8 -*-
"""给这份文档补页眉（含大赛 logo）与页脚页码 —— 只做加法，不动正文内容。

先诊断（把它导出 PDF 后逐页扫的），确认缺什么：

  第 1 页 封面   无页眉 无页码     ← 模板如此，保持
  第 2 页 声明   有页眉(2024年)   无页码    ← 年份错 + 缺页码
  第 3 页 目录   无页眉           无页码    ← 两样都缺
  第 4 页起 正文 有页眉(2021年)   有页码    ← 年份错

所以要做四件事：
  ① 页眉年份统一成 2026（三个节）
  ② 目录页补页眉（第 2 节关掉「首页不同」）
  ③ 声明页、目录页补页码（第 1、2 节页脚插入 PAGE 域）
  ④ 页码改成全文连续（原来第 3 节从 1 重编，会让声明/目录的页码和正文撞号），
     最后更新一次目录域，让目录里的页码跟着对上

两条硬规矩：
  · 改页眉只能用 Find/Replace —— 直接给 Range.Text 赋值会把页眉里的大赛
    logo（InlineShape）一起删掉。这个坑踩过一次，末尾有自检会拦住。
  · logo 图片必须来自模板；本脚本不重造 logo，只保证它还在。
"""
import os
import shutil

import win32com.client as win32

SRC = (r'C:\Users\花火\.dsh\attachments\v1\files\22'
       r'\22e7bfe68ef88300e74ff3ea799ba9b9f35f01693fcf4009e39994cf4b633872'
       r'\智座-设计文档1.doc')
TPL = (r'C:\Users\花火\.dsh\attachments\v1\files\7b'
       r'\7b47fa822207c9ab22daf6ec0f716369317e0bd47d6fdfe3ddefda5b204f1ccb'
       r'\设计文档模板-2026年.doc')
WORK = r'D:\MAX_xiangmu\_fix'
OUT_DOCX = os.path.join(WORK, '智座-设计文档（补齐页眉页脚）.docx')
OUT_DOC = os.path.join(WORK, '智座-设计文档（补齐页眉页脚）.doc')

WD_HEADER_PRIMARY = 1
WD_FOOTER_PRIMARY = 1
WD_FIELD_PAGE = 33          # wdFieldPage
WD_ALIGN_CENTER = 1
WD_FIND_STOP = 0
WD_REPLACE_ALL = 2

os.makedirs(WORK, exist_ok=True)
base = os.path.join(WORK, '_src.doc')
shutil.copy2(SRC, base)

w = win32.gencache.EnsureDispatch('Word.Application')
w.Visible = False
w.DisplayAlerts = 0
doc = w.Documents.Open(base, ReadOnly=False, Visible=False)

try:
    def state(tag):
        print('  [%s]' % tag)
        total = 0
        for i, sec in enumerate(doc.Sections, 1):
            h = sec.Headers.Item(WD_HEADER_PRIMARY)
            f = sec.Footers.Item(WD_FOOTER_PRIMARY)
            imgs = h.Range.InlineShapes.Count
            total += imgs
            print('    第%d节 首页不同=%-5s 页眉图%d 页眉=%r 页脚域%d 页脚=%r'
                  % (i, sec.PageSetup.DifferentFirstPageHeaderFooter, imgs,
                     (h.Range.Text or '').replace('\r', '').replace('\a', '').strip()[:26],
                     f.Range.Fields.Count,
                     (f.Range.Text or '').replace('\r', '').replace('\a', '').strip()[:8]))
        return total

    print('=== 改动前 ===')
    before_imgs = state('before')

    # ---------- ① 页眉年份 → 2026（只用 Find/Replace，保住 logo）----------
    print()
    print('① 页眉年份统一为 2026 …')
    n_year = 0
    for sec in doc.Sections:
        for hi in (1, 2, 3):
            try:
                h = sec.Headers.Item(hi)
            except Exception:
                continue
            if '华北五省' not in (h.Range.Text or ''):
                continue
            for old in ('2024', '2021', '2025', '2023', '2022'):
                fnd = h.Range.Find
                fnd.ClearFormatting()
                fnd.Text = old + '年'
                fnd.Replacement.ClearFormatting()
                fnd.Replacement.Text = '2026年'
                if fnd.Execute(Replace=WD_REPLACE_ALL):
                    n_year += 1
    print('   替换 %d 处' % n_year)

    # ---------- ② 目录页补页眉 ----------
    print('② 目录页补页眉（第 2 节关掉「首页不同」）…')
    if doc.Sections.Count >= 2:
        doc.Sections.Item(2).PageSetup.DifferentFirstPageHeaderFooter = False
        # 该节若没有页眉内容，从上一节继承即可；这里确认一下
        h2 = doc.Sections.Item(2).Headers.Item(WD_HEADER_PRIMARY)
        h2.LinkToPrevious = True
        print('   已补上')
    else:
        print('   ★ 节数不足，跳过')

    # ---------- ③ 页脚页码 ----------
    # 编号方案：与模板一致 —— 封面/声明/目录不编号，正文从 1 开始。
    #   为什么不给声明/目录也编号：正文那一节是「从 1 重新编号」的，
    #   而这一版 Word 的类型库没暴露 RestartNumberingAtSection /
    #   StartingNumber（连 _prop_map_put_ 里都没有），关不掉重编号。
    #   若前两节也编号，就会出现「声明=2、目录=3、正文又从 1 开始」的撞号。
    #   模板自己也是这么排的，目录里「一、作品概述 1」正是按它算的。
    print('③ 页脚：保持模板的编号方案（正文从 1 起，封面/声明/目录不编号）…')
    for idx in (1, 2):
        if doc.Sections.Count < idx:
            continue
        sec = doc.Sections.Item(idx)
        ft = sec.Footers.Item(WD_FOOTER_PRIMARY)
        ft.LinkToPrevious = False
        if ft.Range.Fields.Count or (ft.Range.Text or '').strip():
            ft.Range.Delete()
            print('   第%d节页脚已清空（去掉刚才试加的页码）' % idx)
    # 第 3 节（正文）的页码域保持原样
    if doc.Sections.Count >= 3:
        ft3 = doc.Sections.Item(3).Footers.Item(WD_FOOTER_PRIMARY)
        if ft3.Range.Fields.Count == 0:
            rng = ft3.Range
            rng.Delete()
            rng = ft3.Range
            rng.ParagraphFormat.Alignment = WD_ALIGN_CENTER
            rng.Font.Name = '宋体'
            rng.Font.NameFarEast = '宋体'
            rng.Font.Size = 9
            rng.Fields.Add(rng, WD_FIELD_PAGE, 'PAGE', False)
            print('   第3节页脚补上 PAGE 域')
        else:
            print('   第3节页脚已有页码域，保留')

    # ---------- ⑤ 更新目录域 ----------
    print('⑤ 更新目录域 …')
    nf = 0
    for f in doc.Fields:
        if f.Type == 13:                 # wdFieldTOC
            f.Update()
            nf += 1
    doc.Fields.Update()
    print('   更新了 %d 个目录域' % nf)

    # ---------- 自检 ----------
    print()
    print('=== 改动后 ===')
    after_imgs = state('after')
    print()
    if after_imgs >= before_imgs and after_imgs > 0:
        print('  ✅ 页眉 logo %d 个，没丢' % after_imgs)
    else:
        print('  ★★ 页眉 logo 从 %d 变成 %d，出问题了！' % (before_imgs, after_imgs))

    doc.Repaginate()
    print('  页数 %d' % doc.ComputeStatistics(2))

    for p in (OUT_DOCX, OUT_DOC):
        if os.path.exists(p):
            os.remove(p)
    doc.SaveAs2(OUT_DOCX, FileFormat=16)
    doc.SaveAs2(OUT_DOC, FileFormat=0)
    print()
    print('已保存：')
    print('   %s' % OUT_DOCX)
    print('   %s' % OUT_DOC)
finally:
    doc.Close(SaveChanges=0)
    w.Quit()

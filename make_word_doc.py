# -*- coding: utf-8 -*-
"""把设计文档生成为 Word（.docx）—— 直接在模板基础上改。

模板规格（用 Word COM 从模板里读出来的，不是猜的）：
  · 一级标题：样式=正文，大纲级别=1，16pt 方正大标宋简体，居中
  · 二级标题：样式=正文，大纲级别=2，12pt 加粗，居中
  · 目录：真正的 TOC 域  TOC \\o "1-3" \\h \\z \\u   → Word 自己算页码
  · 页眉 9pt 居中 + 0.75pt 下划线；首页不同（封面不带页眉）
  · 页脚页码居中；页面 A4，页边距 上25 下25 左30 右30 mm

两个关键取舍：
  ① 只取「一、作品概述」之后的块 —— 封面/声明/目录用模板自带的，
     我们只填字段，不重造（重造必然跑偏）。
  ② 表格用「制表符文本 → ConvertToTable」而不是逐格写 COM 单元格：
     逐格写时 Range 会落进表格内部，后续内容会钻到单元格里去；
     而且单元格索引一旦和实际结构不符就报「集合成员不存在」。
"""
import io
import os
import re
from html.parser import HTMLParser

import win32com.client as win32

ROOT = r'D:\MAX_xiangmu'
HTML = os.path.join(ROOT, 'docs', '设计文档-智座.html')
TEMPLATE = (r'C:\Users\花火\.dsh\attachments\v1\files\98'
            r'\985a9a60c6a1e40b43f4bc7da650f2e86cce81c8ee3e6109920e4cc455d1deae'
            r'\设计文档模板-2026年.doc')
OUT = os.path.join(ROOT, 'docs', '智座-设计文档.docx')

WD_ALIGN_CENTER = 1
WD_ALIGN_LEFT = 0
WD_OUTLINE_BODY = 10
WD_FORMAT_DOCX = 16
WD_SEP_TAB = 1
WD_COLLAPSE_END = 0


# ============================================================ HTML 解析
class Doc(HTMLParser):
    """把正文解析成块序列 [(kind, payload)]。

    kind: h1(一级标题) / h2(二级) / h3(小标题) / p / li / note / table / img
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.buf = []
        self.cur = None
        self.in_body = False
        self.skip_to = None       # 跳过到第几层 div 结束
        self.div_depth = 0
        self.table = None
        self.row = None
        self.started = False      # 见到「一、作品概述」才开始收

    def _flush(self):
        # ★ 必须检查 started：封面/声明/目录用的是模板自带的，
        #   我们只负责「一、作品概述」之后的正文。
        #   之前这里漏了判断，声明页的标题和段落被当成正文又写了一遍。
        if self.started and self.cur and self.buf:
            txt = re.sub(r'\s+', ' ', ''.join(self.buf)).strip()
            if txt:
                self.blocks.append((self.cur, txt))
        self.buf = []
        self.cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get('class', '')
        style = a.get('style', '')

        if tag == 'div':
            self.div_depth += 1
            if self.skip_to is not None:
                return
            if 'cover' in cls or 'tocpage' in cls:
                self.skip_to = self.div_depth
                return

        if not self.in_body:
            if tag == 'body':
                self.in_body = True
            return
        if self.skip_to is not None:
            return

        if tag in ('h1', 'h2'):
            self._flush(); self.cur = 'h1'
            self.buf = []
        elif tag == 'h3':
            self._flush(); self.cur = 'h2'; self.buf = []
        elif tag == 'h4':
            self._flush(); self.cur = 'h3'; self.buf = []
        elif tag == 'p':
            self._flush()
            self.cur = 'note' if 'padding-left' in style else 'p'
            self.buf = []
        elif tag == 'li':
            self._flush(); self.cur = 'li'; self.buf = []
        elif tag == 'table':
            self._flush(); self.table = []
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.buf = []
        elif tag == 'img':
            src = a.get('src', '')
            if src.startswith('images/') and self.started:
                self._flush()
                self.blocks.append(('img', src))

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.skip_to is not None and self.div_depth == self.skip_to:
                self.skip_to = None
            self.div_depth = max(0, self.div_depth - 1)
            return
        if self.skip_to is not None or not self.in_body:
            return

        if tag in ('h1', 'h2', 'h3', 'h4', 'p', 'li'):
            if tag in ('h1', 'h2') and self.cur == 'h1':
                txt = re.sub(r'\s+', ' ', ''.join(self.buf)).strip()
                if txt.startswith('一、作品概述'):
                    self.started = True        # ★ 从这里开始才收
            self._flush()
        elif tag in ('td', 'th'):
            if self.table is not None and self.row is not None:
                self.row.append(re.sub(r'\s+', ' ', ''.join(self.buf)).strip())
            self.buf = []
        elif tag == 'tr':
            if self.table is not None and self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table':
            if self.table and self.started:
                self.blocks.append(('table', self.table))
            self.table = None

    def handle_data(self, d):
        if self.in_body and self.skip_to is None:
            self.buf.append(d)


# ============================================================ 主流程
def main():
    print('① 解析 HTML …')
    s = io.open(HTML, encoding='utf-8').read()
    s = re.sub(r'<script[\s\S]*?</script>', '', s)
    d = Doc()
    d.feed(s)
    kinds = {}
    for k, _ in d.blocks:
        kinds[k] = kinds.get(k, 0) + 1
    print('   %s' % kinds)

    print('② 打开模板 …')
    w = win32.gencache.EnsureDispatch('Word.Application')
    w.Visible = False
    w.DisplayAlerts = 0
    doc = w.Documents.Open(TEMPLATE, ReadOnly=False, Visible=False)

    try:
        # ---------- 封面：只填字段 ----------
        print('③ 填封面与声明 …')
        fill = {'所在赛区：': '河北赛区', '所在学校：': '沧州交通学院',
                '团队名称：': '苗苗', '团队成员：': '吴嘉森、李冠桦',
                '提交日期：': '2026 年 10 月'}
        for p in doc.Paragraphs:
            t = (p.Range.Text or '').replace('\r', '').replace('\a', '').strip()
            if t.startswith('【项目名称】'):
                p.Range.Text = '智座'
                p.Range.Font.Size = 26
                p.Range.Font.Bold = 1
                p.Range.ParagraphFormat.Alignment = WD_ALIGN_CENTER
                continue
            for k, v in fill.items():
                if t == k:
                    p.Range.InsertAfter(v)

        # 页眉年份：模板作者的页眉还写着 2024，改成 2026
        for sec in doc.Sections:
            for hi in (1, 2, 3):          # 奇数页 / 偶数页 / 首页
                try:
                    h = sec.Headers.Item(hi)
                except Exception:
                    continue
                t = (h.Range.Text or '').replace('\r', '').replace('\a', '')
                if '华北五省' in t:
                    new_t = re.sub(r'20\d\d\s*年', '2026年', t).strip()
                    h.Range.Text = new_t

        # 声明标题的大纲级别降为正文 —— 模板的目录里没有这一条
        for p in doc.Paragraphs:
            t = (p.Range.Text or '').replace('\r', '').replace('\a', '').strip()
            if t == '参赛作品知识产权声明':
                p.Range.ParagraphFormat.OutlineLevel = WD_OUTLINE_BODY
                break

        # 声明页的作品名
        for p in doc.Paragraphs:
            t = (p.Range.Text or '').replace('\r', '').replace('\a', '').strip()
            if t.startswith('参赛作品名称：') and '下称该作品' in t:
                p.Range.Text = '参赛作品名称：智座（智能选座与导航一体化系统）（下称该作品）'
                break

        # ---------- 正文：从「一、作品概述」起整体替换 ----------
        print('④ 定位正文起点 …')
        start = None
        for p in doc.Paragraphs:
            t = (p.Range.Text or '').replace('\r', '').replace('\a', '').strip()
            if t == '一、作品概述':
                start = p.Range.Start
                break
        if start is None:
            raise RuntimeError('模板里没找到「一、作品概述」')

        tail = doc.Content
        tail.Collapse(WD_COLLAPSE_END)
        doc.Range(start, tail.End).Delete()
        rng = doc.Range(start, start)

        def new_para(text, size=12, bold=False, align=WD_ALIGN_LEFT,
                     indent=True, outline=WD_OUTLINE_BODY, font='宋体'):
            rng.InsertAfter(text + '\r')
            rng.Style = doc.Styles('正文')
            rng.Font.Size = size
            rng.Font.Name = font
            rng.Font.Bold = -1 if bold else 0
            rng.ParagraphFormat.Alignment = align
            rng.ParagraphFormat.OutlineLevel = outline
            rng.ParagraphFormat.FirstLineIndent = 24 if indent else 0
            rng.Collapse(WD_COLLAPSE_END)

        # ★ 只有模板目录里列出的二级标题才设大纲级别 2。
        #   「六、其他」下面的（1）(2)… 模板目录里没有，
        #   若也设成大纲 2 就会混进目录，与模板不一致。
        TOC_SUB = {
            '（1）可行性分析', '（2）目标群体',
            '（1）功能概述', '（2）原型设计',
            '（1）作品实现及难点', '（2）特色分析',
        }

        print('⑤ 写入正文 …')
        n_img = 0
        for kind, payload in d.blocks:
            if kind == 'h1':
                new_para(payload, size=16, align=WD_ALIGN_CENTER, indent=False,
                         outline=1, font='方正大标宋简体')
            elif kind == 'h2':
                new_para(payload, size=12, bold=True, align=WD_ALIGN_CENTER,
                         indent=False,
                         outline=(2 if payload.strip() in TOC_SUB else WD_OUTLINE_BODY))
            elif kind == 'h3':
                new_para(payload, size=12, bold=True, indent=False)
            elif kind in ('p', 'li'):
                new_para(payload, indent=True)
            elif kind == 'note':
                new_para(payload, indent=False)

            elif kind == 'img':
                path = os.path.join(ROOT, 'docs', payload.replace('/', os.sep))
                if not os.path.exists(path):
                    continue
                # 图片宽度按内容区（150mm）的 46% 走，两张并排
                rng.ParagraphFormat.Alignment = WD_ALIGN_CENTER
                rng.ParagraphFormat.OutlineLevel = WD_OUTLINE_BODY
                rng.ParagraphFormat.FirstLineIndent = 0
                shp = rng.InlineShapes.AddPicture(path, False, True, rng)
                try:
                    shp.LockAspectRatio = -1
                    shp.Width = 150 / 2.54 * 72 * 0.46      # 150mm 的 46%
                except Exception:
                    pass
                rng.Collapse(WD_COLLAPSE_END)
                rng.InsertAfter('\r')
                rng.Collapse(WD_COLLAPSE_END)
                n_img += 1

            elif kind == 'table':
                rows = payload
                # 用制表符文本 + ConvertToTable，比逐格写 COM 稳得多
                txt = '\r'.join('\t'.join(c.replace('\t', ' ') for c in r) for r in rows)
                rng.InsertAfter(txt + '\r')
                rng.Style = doc.Styles('正文')
                rng.Font.Size = 10.5
                rng.Font.Name = '宋体'
                rng.Font.Bold = 0
                rng.ParagraphFormat.OutlineLevel = WD_OUTLINE_BODY
                rng.ParagraphFormat.FirstLineIndent = 0
                tbl = rng.ConvertToTable(Separator=WD_SEP_TAB)
                tbl.Borders.Enable = True
                tbl.Rows(1).Range.Font.Bold = -1
                tbl.Rows(1).HeadingFormat = -1        # 跨页重复表头
                rng = tbl.Range
                rng.Collapse(WD_COLLAPSE_END)
                rng.InsertAfter('\r')
                rng.Collapse(WD_COLLAPSE_END)

        print('   写入图片 %d 张' % n_img)

        print('⑥ 更新目录域 …')
        for f in doc.Fields:
            if f.Type == 13:
                f.Update()
        doc.Fields.Update()

        if os.path.exists(OUT):
            os.remove(OUT)
        doc.SaveAs2(OUT, FileFormat=WD_FORMAT_DOCX)
        print('⑦ 已保存 %s  (%.1f MB)' % (OUT, os.path.getsize(OUT) / 1024 / 1024))
    finally:
        doc.Close(SaveChanges=0)
        w.Quit()


if __name__ == '__main__':
    main()

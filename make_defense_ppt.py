# -*- coding: utf-8 -*-
"""把 v5 原理版改成答辩用 16 页版。

改动只做三件事，其余版式与内容一字不动：
  ① 封面更新：commit / 提交数 / 测试数（原文件已过时）
  ② 新增一页「局限与未解」—— 答辩必问，原版没有
  ③ 全部页码重新编号（/15 → /16）

新增页用「复制 P5 的 XML」的方式做，不新建形状，保证版式、字体、
配色与其它页完全一致。
"""
import copy
import os
import shutil
import sys

from pptx import Presentation

SRC = r'C:\Users\花火\xwechat_files\wxid_28290tke86ib22_8980\msg\file\2026-11\智能选座汇报_原理翻版_v5_15页.pptx'
OUT_DIR = r'D:\MAX_xiangmu\docs'
OUT = os.path.join(OUT_DIR, '★智座-答辩PPT-16页.pptx')

# 真实数据（本次会话核实）
COMMIT = 'AD88A85'
COMMIT_COUNT = 79
TEST_COUNT = 476


def set_text(shape, new_text):
    """替换文本，保留第一个 run 的字体格式。

    不能直接赋 shape.text_frame.text —— 那会把整段合并成一个 run，
    v5 里项题是加粗、项述是灰色小字，直接赋值会把这些格式冲掉。
    """
    tf = shape.text_frame
    para = tf.paragraphs[0]
    if not para.runs:
        para.add_run()
    para.runs[0].text = new_text
    for r in para.runs[1:]:
        r._r.getparent().remove(r._r)
    # 清掉多余段落（这些框都只有一段）
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)


def duplicate_slide(prs, src_index, dst_index):
    """复制一页（深拷贝 XML），并移动到 dst_index 位置。"""
    src = prs.slides[src_index]
    blank = prs.slide_layouts[0]
    new = prs.slides.add_slide(blank)
    # 去掉版式自带的形状
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    # 深拷贝源页所有形状
    for sh in src.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    # 移动到目标位置
    sldIdLst = prs.slides._sldIdLst
    ids = list(sldIdLst)
    moved = ids[-1]
    sldIdLst.remove(moved)
    sldIdLst.insert(dst_index, moved)
    return new


def shape_by_name(slide, name):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
    return None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # 用 copyfile 而不是 copy2：copy2 会把源文件的只读属性一起带过来，
    # 微信目录里拿到的 pptx 常常是只读的，导致后面 save 直接 PermissionError。
    shutil.copyfile(SRC, OUT)
    # 万一目标已存在且被设成只读，这里再兜一次
    try:
        os.chmod(OUT, 0o666)
    except OSError:
        pass
    prs = Presentation(OUT)

    # ---------- ① 封面 ----------
    cover = prs.slides[0]
    for sh in cover.shapes:
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text
        if 'GITHUB' in t and 'COMMIT' not in t.upper().replace('COMMITS', 'COMMIT'):
            pass
        if 'GITHUB' in t:
            set_text(sh, 'GITHUB · MAIN @ %s · %d COMMITS · %d 项测试全过'
                     % (COMMIT, COMMIT_COUNT, TEST_COUNT))
            print('  封面：commit 行已更新')

    # ---------- ② 新增「局限与未解」页 ----------
    # 19 页位置：v5 共 15 页，插在「演示」页（原 P14，索引 13）之前
    new_slide = duplicate_slide(prs, src_index=4, dst_index=13)

    pairs = [
        # (形状名, 新文字)
        ('大标题', '边界与未解：能验证的写进指标，不能的写成边界'),
        ('栏目', '14 · LIMITS'),
        ('结论', '这四条都不藏在代码里：做到的写进指标，做不到的明确写成边界——答辩被追问也不会含糊。'),
        ('页脚', '智能选座与导航一体化系统 · 8 分钟精简版'),
        # 左栏：已经做到
        ('标题 900', '已经做到'),
        ('项题 901', '判占有依据'),
        ('项述 901', '判占规则只写服务端一处；现场用超声波测距（距离小于阈值即占用），换传感器不改业务代码'),
        ('项题 903', '状态不卡死'),
        ('项述 903', '四类状态配四套兜底：抗抖动、预约例外、离线异常、有效回归'),
        ('项题 905', '走得过去'),
        ('项述 905', '平面图生路网、A* 求最短路、跨层分段绘制；断点超过 5 倍中位边长就如实报错'),
        ('项题 907', '批量可部署'),
        ('项述 907', 'secrets.h 预置 WiFi 与服务器地址，烧完通电即连，不必逐台开热点配网（已实测）'),
        # 右栏：边界与未解
        ('标题 909', '边界与未解'),
        ('项题 910', '监控页不是安防'),
        ('项述 910', '没有接入真实视频流，页面是可计算的可视化层，画面按座位状态生成，不能当作视觉识别证据'),
        ('项题 912', '相邻超声波串扰'),
        ('项述 912', '多台同时测距会收到彼此的回波；现在只靠上报间隔错开，没做严格的时分复用'),
        ('项题 914', 'PDR 会累积误差'),
        ('项述 914', '必须靠扫座位码重新锚定，不能长期只靠惯性推算'),
        ('项题 916', '规模还没压测'),
        ('项述 916', '离线 mock 引擎与传感器模拟器只用于演示，不能当作真实并发容量的依据'),
    ]
    missing = []
    for name, text in pairs:
        sh = shape_by_name(new_slide, name)
        if sh is None:
            missing.append(name)
            continue
        set_text(sh, text)
    if missing:
        print('  ★ 这些形状没找到：%s' % missing)
    else:
        print('  「局限与未解」页已填入 %d 个文本框' % len(pairs))

    # ---------- ③ 全部页码重新编号 ----------
    # 不能按形状名找：v5 里页码框有的叫「页码」，有的是「文本框 55」「TextBox 17」，
    # 按名字只会改到一部分，剩下的还留着 ／15。改成按内容特征匹配。
    import re as _re
    pg_re = _re.compile(r'^\s*\d{1,2}\s*/\s*\d{1,2}\s*$')
    total = len(prs.slides)
    fixed = 0
    for i, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            if not sh.has_text_frame:
                continue
            if pg_re.match(sh.text_frame.text.strip()):
                set_text(sh, '%02d / %d' % (i, total))
                fixed += 1
    print('  页码已重编：改了 %d 个（共 %d 页）' % (fixed, total))
    if fixed != total:
        print('  ⚠ 有 %d 页没有页码框（封面通常没有，属正常）' % (total - fixed))

    prs.save(OUT)
    print()
    print('  输出：%s' % OUT)
    print('  大小：%.1f MB' % (os.path.getsize(OUT) / 1024 / 1024))


if __name__ == '__main__':
    main()

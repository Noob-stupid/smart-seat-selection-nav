# -*- coding: utf-8 -*-
"""决赛版加「创新点」页 —— 页数仍 16（封顶）。

腾位置的办法：把「室外导航」与「室内导航」合成一页（两页版式完全相同，
都是 4 卡片 + 横条 + 结论），合成后正好多出一页给创新点。

最终 16 页：
  1 封面 / 2 为什么做 / 3 架构 / 4 判占原理 / 5 状态机 / 6 动态锁定 /
  7 推荐排序 / 8 硬件 / 9 导航(合并) / 10 路网生成 / 11 A* /
  12 AI 智能体 / 13 演示 / 14 难点与攻克 / 15 创新点 / 16 致谢
"""
import copy
import os
import shutil

from pptx import Presentation

SRC = r'D:\MAX_xiangmu\docs\★智座-答辩PPT-决赛版.pptx'
OUT = r'D:\MAX_xiangmu\docs\★智座-答辩PPT-决赛版2.pptx'


def set_text(shape, new_text):
    tf = shape.text_frame
    para = tf.paragraphs[0]
    if not para.runs:
        para.add_run()
    para.runs[0].text = new_text
    for r in para.runs[1:]:
        r._r.getparent().remove(r._r)
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)


def fill(slide, pairs):
    by = {sh.name: sh for sh in slide.shapes}
    missing = []
    for name, text in pairs:
        sh = by.get(name)
        if sh is None:
            missing.append(name)
            continue
        set_text(sh, text)
    return missing


def clone_slide(prs, src_index):
    """深拷贝一页，追加到末尾（返回新页）。"""
    src = prs.slides[src_index]
    new = prs.slides.add_slide(prs.slide_layouts[0])
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in src.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    return new


def move_slide(prs, from_idx, to_idx):
    lst = prs.slides._sldIdLst
    items = list(lst)
    el = items[from_idx]
    lst.remove(el)
    lst.insert(to_idx, el)


def delete_slide(prs, idx):
    lst = prs.slides._sldIdLst
    el = list(lst)[idx]
    lst.remove(el)


# ---------------------------------------------------------------------------
# ① 合并导航页（用原来的室内导航页 P10 当载体）
# ---------------------------------------------------------------------------

NAV_PAGE = [
    ('大标题', '导航：先到楼，再进楼，走完路网'),
    ('栏目', '09 · NAVIGATION'),

    ('卡题 0', '先到楼'),
    ('卡述 0', '只返回已配置经纬度的建筑；高德 / 百度二选一，尊重用户已装地图'),

    ('卡题 1', '再进楼'),
    ('卡述 1', '平面图点选、扫节点码或建筑入口作起点；座位坐标作终点'),

    ('卡题 2', '走路网'),
    ('卡述 2', '点击吸附最近路点，A* 求最短路叠加折线；附近没路点就明确提示，不硬画'),

    ('卡题 3', '跨楼层'),
    ('卡述 3', '按楼层分段绘制，按高差提示上楼或下楼至第几层'),

    ('带字 901', '兜底　无地图 Key 或断网改指南针方位；Key 只发给已登录用户，匿名不返回'),
    ('结论', '先到楼、再进楼、走完路网 —— 三段接上，选座结果才真正落到一个座位上。'),
]

# ---------------------------------------------------------------------------
# ② 创新点页（用同一套 4 卡片版式）
# ---------------------------------------------------------------------------

INNO_PAGE = [
    ('大标题', '创新点：四个「不省事」的选择'),
    ('栏目', '15 · INNOVATION'),

    ('卡题 0', '规则只写一处'),
    ('卡述 0', '硬件可换：双路 PIR、红外、单路超声波。换传感器不改一行业务代码，也不重烧固件'),

    ('卡题 1', '断点宁可不连'),
    ('卡述 1', '缺口超过本路网中位边长的 5 倍就如实报错，不给一条走不通的假路径'),

    ('卡题 2', 'AI 只解释不改写'),
    ('卡述 2', '8 个工具读写分开：读的直接跑，写的只出提案必须人确认，判占永不由模型决定'),

    ('卡题 3', '一条数据链'),
    ('卡述 3', '选座 → 导航 → 签到，前端看到的和后台存的是同一份，不存在两套状态'),

    ('带字 901', '四个选择指向同一件事：别人图省事的地方，我们选了更麻烦但对的那条路'),
    ('结论', '创新不在用了什么技术，而在每个岔路口都选了不自欺的那一边。'),
]


def main():
    shutil.copyfile(SRC, OUT)
    try:
        os.chmod(OUT, 0o666)
    except OSError:
        pass

    prs = Presentation(OUT)
    print('  起始页数：%d' % len(prs.slides))

    # ① 先把 P10（室内导航）改造成合并导航页
    m = fill(prs.slides[9], NAV_PAGE)
    print('  ① P10 → 合并导航页（填 %d 项%s）'
          % (len(NAV_PAGE) - len(m), '' if not m else '，缺 %s' % m))

    # ② 深拷贝这一页做创新点页，追加到末尾
    inno = clone_slide(prs, 9)
    m2 = fill(inno, INNO_PAGE)
    print('  ② 新建创新点页（填 %d 项%s）'
          % (len(INNO_PAGE) - len(m2), '' if not m2 else '，缺 %s' % m2))

    # ③ 删掉 P9（原室外导航，内容已并入合并页）
    delete_slide(prs, 8)
    print('  ③ 删除原 P9 室外导航（已并入）')

    # ④ 创新点页现在在末尾（索引 15，致谢之后），移到致谢之前
    n = len(prs.slides)
    move_slide(prs, n - 1, n - 2)
    print('  ④ 创新点页移到致谢之前')

    # ⑤ 重编页码
    import re
    pg_re = re.compile(r'^\s*\d{1,2}\s*/\s*\d{1,2}\s*$')
    total = len(prs.slides)
    fixed = 0
    for i, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            if sh.has_text_frame and pg_re.match(sh.text_frame.text.strip()):
                set_text(sh, '%02d / %d' % (i, total))
                fixed += 1
    print('  ⑤ 页码重编 %d 个（共 %d 页）' % (fixed, total))

    prs.save(OUT)
    print()
    print('  输出：%s' % OUT)
    print('  页数：%d' % len(prs.slides))
    print('  大小：%.1f MB' % (os.path.getsize(OUT) / 1024 / 1024))

    print()
    print('  === 最终页序 ===')
    for i, s in enumerate(prs.slides, 1):
        title = ''
        for sh in s.shapes:
            if sh.name == '大标题' and sh.has_text_frame:
                title = sh.text_frame.text.strip()
        if not title:
            t = [sh.text_frame.text.strip() for sh in s.shapes
                 if sh.has_text_frame and sh.text_frame.text.strip()]
            title = t[0].splitlines()[0][:36] if t else ''
        print('    %2d. %s' % (i, title[:52]))


if __name__ == '__main__':
    main()

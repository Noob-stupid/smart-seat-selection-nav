# -*- coding: utf-8 -*-
"""决赛答辩 PPT —— 从原始 16 页一条命令生成，不再层层叠加中间文件。

之前是 make_defense_ppt → final → inno → img 串了四层，每层都在上一层的
输出上改，最后出现了「孤儿 slide 部件被写两次」的坏包。
这里合并成一个脚本，只从原始文件读一次，全部改动一次保存。

相比原始 16 页的改动：
  · P10 室内导航 + 原 P9 室外导航 → 合并为一页「导航：先到楼，再进楼，走完路网」
  · 原 P13 断点与跨层 → 「AI 智能体」并配真实对话截图
  · 原 P15 边界与未解 → 「难点与攻克：八个真踩过的坑」
  · 新增「创新点」页（用合并后腾出的位置，总数仍 16）
  · 右侧加真实项目截图，文字相应精简

页数 16 不变。
"""
import copy
import os
import re
import shutil

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches

SRC = (r'C:\Users\花火\.dsh\attachments\v1\files\09'
       r'\09844ac105943f6845cffa3f68914bcb481ee3100076f35946f1821fa04b2564'
       r'\★智座-答辩PPT-16页(1)(2).pptx')
OUT = r'D:\MAX_xiangmu\docs\★智座-答辩PPT-决赛版.pptx'
IMG = r'D:\MAX_xiangmu\docs\images'

COMMIT = 'AD88A85'
COMMIT_COUNT = 79
TEST_COUNT = 476

# 手机截图统一规格（1260x2700，比例 0.4667）
IMG_W, IMG_H = 2.15, 4.60
IMG_TOP = 1.52
IMG_LEFT = 10.55          # +2.15 = 12.70，右边界 12.71


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

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


def by_name(slide):
    return {sh.name: sh for sh in slide.shapes}


def fill(slide, pairs):
    by = by_name(slide)
    missing = []
    for name, text in pairs:
        sh = by.get(name)
        if sh is None:
            missing.append(name)
            continue
        set_text(sh, text)
    return missing


def move(sh, left=None, width=None, top=None, height=None):
    if left is not None:
        sh.left = Inches(left)
    if top is not None:
        sh.top = Inches(top)
    if width is not None:
        sh.width = Inches(width)
    if height is not None:
        sh.height = Inches(height)


def clone_slide(prs, src_index):
    src = prs.slides[src_index]
    new = prs.slides.add_slide(prs.slide_layouts[0])
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in src.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    return new


def clone_shapes(src_slide, dst_slide, names):
    by = by_name(src_slide)
    for n in names:
        sh = by.get(n)
        if sh is None:
            print('    ⚠ 源页没有 %s' % n)
            continue
        dst_slide.shapes._spTree.append(copy.deepcopy(sh._element))


def delete_slide(prs, idx):
    """删页必须同时断开部件关系。

    只从 sldIdLst 里 remove 是不够的 —— 幻灯片部件还挂在 presentation.part
    的关系里，保存时会被再写一遍，产出「slideN.xml 重复」的坏包。
    """
    lst = prs.slides._sldIdLst
    el = list(lst)[idx]
    rId = el.get(qn('r:id'))
    prs.part.drop_rel(rId)
    lst.remove(el)


def move_slide(prs, from_idx, to_idx):
    lst = prs.slides._sldIdLst
    items = list(lst)
    el = items[from_idx]
    lst.remove(el)
    lst.insert(to_idx, el)


def add_shot(slide, filename):
    pic = slide.shapes.add_picture(os.path.join(IMG, filename),
                                   Inches(IMG_LEFT), Inches(IMG_TOP),
                                   Inches(IMG_W), Inches(IMG_H))
    pic.name = '截图 %s' % filename
    pic.line.color.rgb = RGBColor(0xD0, 0xD0, 0xD0)
    pic.line.width = Emu(9525)
    return pic


# ---------------------------------------------------------------------------
# 各页内容
# ---------------------------------------------------------------------------

AI_CODE = """# utils/ai_tools.py
READ_TOOLS = [
  list_buildings, floor_stats, query_seats,
  find_free_seat, device_status,
]
WRITE_TOOLS = [
  set_seat_active, set_seat_ir, close_floor_ir,
]

run_read_tool(...)    # 立即执行
run_write_tool(...)   # 先出提案，等人点确认"""

AI_PAGE = [
    ('大标题', 'AI 智能体：模型自己查数据，写操作要人确认'),
    ('栏目', '13 · AI AGENT'),
    ('标题 900', '工具调用 · 读与写分开'),
    ('代码 902', AI_CODE),
    ('注 903', '模型只决定「调哪个工具」，能不能真正改动数据由代码控制，不由模型决定。'),
    ('标题 904', '它能做什么'),
    ('项题 905', '自然语言选座'),
    ('项述 905', '「有靠窗空位吗」→ 调 find_free_seat 查真实座位'),
    ('项题 907', '写操作二次确认'),
    ('项述 907', '只出提案，管理员点确认才落库'),
    ('项题 909', '故障排查'),
    ('项述 909', '「哪个设备掉线」→ 调 device_status 查心跳'),
    ('结论', 'AI 只解释事实、不生产事实：判占永远由传感器读数决定，模型不参与。'),
]

HARD_PAGE = [
    ('大标题', '难点与攻克：八个真踩过的坑'),
    ('栏目', '15 · HARD PROBLEMS'),

    ('标题 900', '硬件与网络'),
    ('项题 901', '设备连不上云端'),
    ('项述 901', '云端 HTTPS 后全站 301 跳转，设备无 TLS 不跟随，请求全被挡。改 WiFiClientSecure 按前缀选协议'),
    ('项题 903', 'WiFi 密码混进 BOM'),
    ('项述 903', '写文件时带上的 BOM 成了密码首字符，握手只报 reason=15，查了很久。在配置生成处统一转义并剔除 BOM'),
    ('项题 905', '重连风暴打满热点'),
    ('项述 905', '底层自动重连 40 秒触发 313 次断开事件，把热点连接表占满反而更容易被拒。关掉自动重连'),
    ('项题 907', '产线批量配置'),
    ('项述 907', '逐台开热点配网不可能。把 WiFi 与服务器地址预置进固件，烧完通电即连，已在真机实测'),

    ('标题 909', '算法与工程'),
    ('项题 910', '断点桥接给出假路径'),
    ('项述 910', '原来无条件连最近两节点，相距 9999 像素也桥接。改以本路网中位边长的 5 倍为上限'),
    ('项题 912', 'PDR 转身位置跳变'),
    ('项述 912', '原按「当前朝向 × 累计距离」推算，一转身位移被重投影，实测跳了 260 像素。改为逐步累加'),
    ('项题 914', '迁移在生产从不执行'),
    ('项述 914', '迁移写在 __main__ 里，gunicorn 用 import app:app 永远不进，加字段后接口 500'),
    ('项题 916', '在线判定看错字段'),
    ('项述 916', '设备不上报也一直显示在线。拆成「心跳」与「上报」两个时间戳，并加「无数据」中间态'),

    ('结论', '这八个坑都是跑出来的，不是想出来的 —— 每个都固化成回归测试，现在 476 项全过。'),
]

NAV_PAGE = [
    ('大标题', '导航：先到楼，再进楼，走完路网'),
    ('栏目', '09 · NAVIGATION'),
    ('卡题 0', '先到楼'),
    ('卡述 0', '只返回已配置经纬度的建筑；高德 / 百度二选一，尊重用户已装地图'),
    ('卡题 1', '再进楼'),
    ('卡述 1', '平面图点选、扫节点码或建筑入口作起点；座位坐标作终点'),
    ('卡题 2', '走路网'),
    ('卡述 2', '点击吸附最近路点，A* 求最短路径；附近没路点就明确提示，不硬画'),
    ('卡题 3', '跨楼层'),
    ('卡述 3', '按楼层分段绘制，按高差提示上楼或下楼至第几层'),
    ('带字 901', '兜底　无地图 Key 或断网改指南针方位；Key 只发给已登录用户，匿名不返回'),
    ('结论', '先到楼、再进楼、走完路网 —— 三段接上，选座结果才真正落到一个座位上。'),
]

INNO_PAGE = [
    ('大标题', '创新点：四个「不省事」的选择'),
    ('栏目', '15 · INNOVATION'),
    ('卡题 0', '规则只写一处'),
    ('卡述 0', '硬件可换：双路 PIR、红外、单路超声波。换传感器不改业务代码，也不重烧固件'),
    ('卡题 1', '断点宁可不连'),
    ('卡述 1', '缺口超过本路网中位边长的 5 倍就如实报错，不给走不通的假路径'),
    ('卡题 2', 'AI 只解释不改写'),
    ('卡述 2', '8 个工具读写分开：读的直接跑，写的只出提案必须人确认'),
    ('卡题 3', '一条数据链'),
    ('卡述 3', '选座 → 导航 → 签到，前端看到的和后台存的是同一份状态'),
    ('带字 901', '四个选择指向同一件事：别人图省事的地方，我们选了更麻烦但对的那条路'),
    ('结论', '创新不在用了什么技术，而在每个岔路口都选了不自欺的那一边。'),
]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    shutil.copyfile(SRC, OUT)
    try:
        os.chmod(OUT, 0o666)
    except OSError:
        pass

    prs = Presentation(OUT)
    print('  原始页数：%d' % len(prs.slides))

    # ① 封面数字
    for sh in prs.slides[0].shapes:
        if sh.has_text_frame and 'GITHUB' in sh.text_frame.text:
            set_text(sh, 'GITHUB · MAIN @ %s · %d COMMITS · %d 项测试全过'
                     % (COMMIT, COMMIT_COUNT, TEST_COUNT))
    print('  ① 封面：commit / 提交数 / 测试数已更新')

    # ② 原 P13 断点与跨层 → AI 智能体（并压窄右栏放截图）
    ai = prs.slides[12]
    fill(ai, AI_PAGE)
    by = by_name(ai)
    for n in ('标题 904', '项题 905', '项题 907', '项题 909',
              '项述 905', '项述 907', '项述 909'):
        move(by[n], width=3.30)
    add_shot(ai, 'AI助手对话.jpg')
    print('  ② P13 → AI 智能体（含对话截图）')

    # ③ 原 P15 边界与未解 → 难点与攻克
    hard = prs.slides[14]
    if not any(sh.name == '结论' for sh in hard.shapes):
        clone_shapes(prs.slides[12], hard, ['结论底', '结论竖条', '结论'])
    fill(hard, HARD_PAGE)
    print('  ③ P15 → 难点与攻克')

    # ④ 原 P10 室内导航 → 合并导航页
    fill(prs.slides[9], NAV_PAGE)
    print('  ④ P10 → 导航（室内外合并）')

    # ④b P9 导航：4 张卡压窄到 4.0 英寸，右侧腾出位置放室内导航截图
    nav = prs.slides[9]
    nby = by_name(nav)
    for i, left in [(0, 0.62), (1, 4.77), (2, 0.62), (3, 4.77)]:
        move(nby['卡 %d' % i], left=left, width=4.00)
        move(nby['卡题 %d' % i], left=left + 0.30, width=3.40)
        move(nby['卡述 %d' % i], left=left + 0.30, width=3.40)
    # 剩余横向空间 8.92 ~ 12.71，把 2.15 宽的图居中放
    pic = nav.shapes.add_picture(os.path.join(IMG, '室内导航-裁.jpg'),
                                 Inches(9.74), Inches(IMG_TOP),
                                 Inches(IMG_W), Inches(IMG_H))
    pic.name = '截图 室内导航-裁.jpg'
    pic.line.color.rgb = RGBColor(0xD0, 0xD0, 0xD0)
    pic.line.width = Emu(9525)
    print('  ④b P9 导航：卡片压窄，加室内导航截图')

    # ⑤ 复制合并导航页做「创新点」。
    #    必须在删页之前复制 —— 删页会让部件名出现空档，add_slide 接着编号时
    #    会和仍然存在的 slideN.xml 撞名，存出来就是「slideN 重复」的坏包。
    inno = clone_slide(prs, 9)
    fill(inno, INNO_PAGE)
    # 这一页是从「导航」页深拷贝来的，会把导航页那张截图一起带过来 —— 删掉。
    # （导航页的截图是这一页之后才加的，但顺序万一变了这里也兜得住）
    for sh in list(inno.shapes):
        if sh.name.startswith('截图'):
            sh._element.getparent().remove(sh._element)
    print('  ⑤ 新增创新点页（此时不移动，先留在末尾）')

    # ⑥ 删原 P9 室外导航（内容已并入合并页）
    delete_slide(prs, 8)
    print('  ⑥ 删原 P9 室外导航')

    # ⑦ 创新点页移到致谢之前
    n = len(prs.slides)
    move_slide(prs, n - 1, n - 2)
    print('  ⑦ 创新点页置于致谢前')

    # ⑧ 重编页码
    pg_re = re.compile(r'^\s*\d{1,2}\s*/\s*\d{1,2}\s*$')
    total = len(prs.slides)
    fixed = 0
    for i, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            if sh.has_text_frame and pg_re.match(sh.text_frame.text.strip()):
                set_text(sh, '%02d / %d' % (i, total))
                fixed += 1
    print('  ⑧ 页码重编 %d 个' % fixed)

    prs.save(OUT)
    print()
    print('  输出：%s' % OUT)
    print('  页数：%d' % len(prs.slides))
    print('  大小：%.1f MB' % (os.path.getsize(OUT) / 1024 / 1024))
    print()
    for i, s in enumerate(prs.slides, 1):
        title = ''
        for sh in s.shapes:
            if sh.name == '大标题' and sh.has_text_frame:
                title = sh.text_frame.text.strip()
        if not title:
            t = [sh.text_frame.text.strip() for sh in s.shapes
                 if sh.has_text_frame and sh.text_frame.text.strip()]
            title = t[0].splitlines()[0][:34] if t else ''
        pics = sum(1 for sh in s.shapes if sh.name.startswith('截图'))
        med = sum(1 for sh in s.shapes if 'MEDIA' in str(sh.shape_type))
        extra = (' 图%d' % pics if pics else '') + (' 视频%d' % med if med else '')
        print('    %2d. %-44s%s' % (i, title[:44], extra))


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""把 16 页答辩版改成决赛版：页数不变（封顶 16），用「替换」腾位置。

改动：
  P13「断点与跨层」 → 「AI 智能体」（断点搭桥的内容移到 P15 当难点）
  P15「边界与未解」 → 「难点与攻克」（8 个真踩过的坑 + 怎么克的）

只替换这两个页的文字，形状位置一律不动，保证版式与其余页一致。
"""
import os
import shutil

from pptx import Presentation

SRC = (r'C:\Users\花火\.dsh\attachments\v1\files\09'
       r'\09844ac105943f6845cffa3f68914bcb481ee3100076f35946f1821fa04b2564'
       r'\★智座-答辩PPT-16页(1)(2).pptx')
OUT = r'D:\MAX_xiangmu\docs\★智座-答辩PPT-决赛版.pptx'


def set_text(shape, new_text):
    """替换文本并保留第一个 run 的格式（项题加粗、项述灰色小字都靠这个）。"""
    tf = shape.text_frame
    para = tf.paragraphs[0]
    if not para.runs:
        para.add_run()
    para.runs[0].text = new_text
    for r in para.runs[1:]:
        r._r.getparent().remove(r._r)
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)


def clone_shapes(src_slide, dst_slide, names):
    """把 src 页上指定名字的形状深拷贝到 dst 页（版式、配色、字体全部照抄）。"""
    import copy
    by_name = {sh.name: sh for sh in src_slide.shapes}
    for n in names:
        sh = by_name.get(n)
        if sh is None:
            print('    ⚠ 源页没有形状 %s' % n)
            continue
        dst_slide.shapes._spTree.append(copy.deepcopy(sh._element))


def fill(slide, pairs):
    """pairs: [(形状名, 新文字)]，逐个替换并汇报缺哪个。"""
    by_name = {sh.name: sh for sh in slide.shapes}
    missing = []
    for name, text in pairs:
        sh = by_name.get(name)
        if sh is None:
            missing.append(name)
            continue
        set_text(sh, text)
    return missing


# ---------------------------------------------------------------------------
# P13 → AI 智能体
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
    ('项述 905', '「找个安静靠窗的空位」→ 模型调 find_free_seat 查真实座位再回答，不是凭空生成'),
    ('项题 907', '写操作二次确认'),
    ('项述 907', '模型能提议改座位状态，但只生成提案，必须管理员点确认才落库'),
    ('项题 909', '故障排查'),
    ('项述 909', '「三楼有几个传感器掉线」→ 调 device_status 用真实心跳数据回答'),
    ('结论', 'AI 只解释事实、不生产事实：判占永远由传感器读数决定，模型不参与。'),
]

# ---------------------------------------------------------------------------
# P15 → 难点与攻克
# ---------------------------------------------------------------------------

HARD_PAGE = [
    ('大标题', '难点与攻克：八个真踩过的坑'),
    ('栏目', '15 · HARD PROBLEMS'),

    ('标题 900', '硬件与网络'),
    ('项题 901', '设备连不上云端'),
    ('项述 901', '云端 HTTPS 后全站 301 跳转，设备无 TLS 不跟随，请求全被挡。改 WiFiClientSecure 按前缀选协议'),
    ('项题 903', 'WiFi 密码混进 BOM'),
    ('项述 903', '写文件时带上的 BOM 成了密码首字符，握手只报 reason=15，查了很久。'
                 '在配置生成处统一转义并剔除 BOM'),
    ('项题 905', '重连风暴打满热点'),
    ('项述 905', '底层自动重连 40 秒触发 313 次断开事件，把热点连接表占满反而更容易被拒。'
                 '关掉自动重连，改由主循环控制重试节奏'),
    ('项题 907', '产线批量配置'),
    ('项述 907', '逐台开热点配网不可能。把 WiFi 与服务器地址预置进固件，'
                 '烧完通电即连，已在真机实测通过'),

    ('标题 909', '算法与工程'),
    ('项题 910', '断点桥接给出假路径'),
    ('项述 910', '原来无条件连最近两节点，相距 9999 像素也桥接。'
                 '改以本路网中位边长的 5 倍为上限，超了就如实报错'),
    ('项题 912', 'PDR 转身位置跳变'),
    ('项述 912', '原按「当前朝向 × 累计距离」推算，一转身走过的位移被整体重投影，实测跳了 260 像素。'
                 '改为逐步累加位移向量'),
    ('项题 914', '迁移在生产从不执行'),
    ('项述 914', '迁移写在 __main__ 里，gunicorn 用 import app:app 永远不进，'
                 '加字段后接口 500。移到模块级'),
    ('项题 916', '在线判定看错字段'),
    ('项述 916', '设备不上报也一直显示在线。拆成「心跳」与「上报」两个时间戳，'
                 '并加「无数据」中间态区分'),

    ('结论', '这八个坑都是跑出来的，不是想出来的 —— 每个都固化成回归测试，现在 476 项全过。'),
]


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    shutil.copyfile(SRC, OUT)
    try:
        os.chmod(OUT, 0o666)
    except OSError:
        pass

    prs = Presentation(OUT)
    print('  原始页数：%d' % len(prs.slides))

    m1 = fill(prs.slides[12], AI_PAGE)      # P13
    print('  P13 → AI 智能体：填 %d 项%s'
          % (len(AI_PAGE) - len(m1), '' if not m1 else '，缺 %s' % m1))

    hard = prs.slides[14]
    # 这页在你改过的版本里没有底部结论条，页脚上方留了一块空。
    # 从 P13 原样复制那三个形状（结论底 / 结论竖条 / 结论），版式与其它页对齐。
    if not any(sh.name == '结论' for sh in hard.shapes):
        clone_shapes(prs.slides[12], hard, ['结论底', '结论竖条', '结论'])
        print('  P15 → 从 P13 补回底部结论条')
    m2 = fill(hard, HARD_PAGE)
    print('  P15 → 难点与攻克：填 %d 项%s'
          % (len(HARD_PAGE) - len(m2), '' if not m2 else '，缺 %s' % m2))

    prs.save(OUT)
    print()
    print('  输出：%s' % OUT)
    print('  页数：%d（未变）' % len(prs.slides))
    print('  大小：%.1f MB' % (os.path.getsize(OUT) / 1024 / 1024))


if __name__ == '__main__':
    main()

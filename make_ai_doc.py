# -*- coding: utf-8 -*-
"""生成《AI 路网诊断》答辩材料 docx。

素材来源：utils/ai_diagnose.py（12 条规则、system prompt、三级降级）、
utils/dxf_reader.py / mapget.py（确认生成段不调模型）。
"""
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

OUT = r'D:\MAX_xiangmu\docs\★智座-答辩-AI路网诊断.docx'

FONT = '微软雅黑'
CODE_FONT = 'Consolas'


def set_font(run, name=FONT, size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn('w:rFonts'))
    if rf is None:
        rf = rpr.makeelement(qn('w:rFonts'), {})
        rpr.append(rf)
    rf.set(qn('w:eastAsia'), FONT)


def h(doc, text, level=1):
    p = doc.add_paragraph()
    sizes = {1: 15, 2: 12.5, 3: 11}
    p.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text)
    set_font(r, size=sizes.get(level, 11), bold=True,
             color=RGBColor(0x1a, 0x1a, 0x1a) if level == 1
             else RGBColor(0x33, 0x33, 0x33))
    return p


def body(doc, text, size=10.5, bold=False, indent=0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.45
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    r = p.add_run(text)
    set_font(r, size=size, bold=bold)
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.4
    r = p.add_run(text)
    set_font(r, size=size)
    return p


def code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.15
    r = p.add_run(text)
    set_font(r, name=CODE_FONT, size=9)
    r.font.color.rgb = RGBColor(0x2b, 0x2b, 0x2b)
    return p


def quote(doc, text):
    """引用块：浅底 + 左缩进"""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.8)
    p.paragraph_format.right_indent = Cm(0.4)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(7)
    p.paragraph_format.line_spacing = 1.45
    r = p.add_run(text)
    set_font(r, size=10)
    r.font.color.rgb = RGBColor(0x44, 0x44, 0x44)
    return p


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = 'Light Grid Accent 1'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, htxt in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ''
        r = cell.paragraphs[0].add_run(htxt)
        set_font(r, size=9.5, bold=True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ''
            r = cells[i].paragraphs[0].add_run(str(v))
            set_font(r, size=9)
    if widths:
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def main():
    doc = Document()

    # 页面设置
    sec = doc.sections[0]
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)

    style = doc.styles['Normal']
    style.font.name = FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)

    # ===== 封面 =====
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(70)
    r = p.add_run('智座 · 智能选座与导航一体化系统')
    set_font(r, size=13, color=RGBColor(0x66, 0x66, 0x66))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(18)
    r = p.add_run('AI 在路网环节用在哪里')
    set_font(r, size=26, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    r = p.add_run('答辩材料 · 口径 · 话术 · 预判问题')
    set_font(r, size=12, color=RGBColor(0x77, 0x77, 0x77))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(120)
    r = p.add_run('2026 年华北五省计算机应用大赛 · 决赛')
    set_font(r, size=10, color=RGBColor(0x99, 0x99, 0x99))

    doc.add_page_break()

    # ===== 零、一页速览 =====
    h(doc, '零、一页速览', 1)

    body(doc, '路网这一块，AI 用在哪里、不用在哪里，先把边界划清楚。'
              '这张表是整份材料的骨架：', size=10.5)

    table(doc,
          ['环节', '用什么做的', '有没有 AI'],
          [['DXF 一键生成路网', 'ezdxf 解析图层 + 形态学细化 + 遍历采样 + 连通性连边', '没有'],
           ['图片生成路网', '二值化 → 骨架 → 采样 → 连边', '没有'],
           ['路网体检', '12 条确定性规则', '没有'],
           ['体检结论写成话', 'DeepSeek-flash 看数字 + 看原图', '有'],
           ['A* 寻路', '图搜索', '没有']],
          widths=[3.6, 9.2, 2.4])

    body(doc, '一句话口径：生成靠确定性算法，AI 只做生成之后的质量诊断。',
         bold=True)

    quote(doc, '如果答辩时说「我们用 AI 生成路网」，评委追问「用了什么模型、'
               'prompt 怎么写」就答不上来 —— 因为那段代码里根本没有模型调用。'
               '反过来，把 AI 的位置讲准，反而是加分项：我们清楚什么该交给模型、'
               '什么不该。')

    # ===== 一、为什么不用 AI 生成 =====
    h(doc, '一、为什么不让 AI 直接生成路网', 1)

    body(doc, '这是答辩很可能被问的第一个问题，答案是我们主动做的取舍，不是能力不够。',
         size=10.5)

    h(doc, '1.1 路网要的是空间拓扑，不是文本', 2)
    body(doc, '路网的本质是一张图：节点带精确坐标（像素级），边表示真实可通行。'
              '模型输出的是文本，要转成这种结构，中间每一步都得猜 —— '
              '坐标猜错一个像素，导航就会把人导到墙里。')

    h(doc, '1.2 生成必须可复现', 2)
    body(doc, '管理员调一个参数重跑，就要能对比出「到底哪里变了」。'
              '确定性算法跑两次结果完全一致；模型有温度参数，同样的输入两次可能不一样，'
              '没法做这种对比。')

    h(doc, '1.3 所以把 AI 放在「评估」而不是「生成」', 2)
    body(doc, '生成之后我们缺的不是另一张图，而是「这张图到底行不行、问题在哪」。'
              '这个判断需要综合多个指标，正是模型擅长的地方。', indent=0)

    # ===== 二、真实链路 =====
    h(doc, '二、AI 在路网链路上的真实位置', 1)

    code(doc,
         '① 上传平面图（图片 / DXF）\n'
         '        ↓\n'
         '② 生成路网（纯算法，约 2.7 秒）        ← 没有 AI\n'
         '        ↓\n'
         '③ 收集事实                             ← 纯计算\n'
         '   节点数 / 孤立比例 / 平均度 / 骨架覆盖率 / 白色占比 /\n'
         '   灰块被判成通道的面积比 / 端点密度 / 未连座位数\n'
         '        ↓\n'
         '④ 规则检测（12 条）                     ← 没有 AI，但这是体检的骨架\n'
         '        ↓\n'
         '⑤ 大模型写文案（DeepSeek-flash）        ← AI 在这里，看数字 + 看原图\n'
         '        ↓\n'
         '⑥ 输出诊断 + 建议')

    body(doc, '整个设计可以压缩成六个字：规则查，模型说。', bold=True, indent=0)

    h(doc, '2.1 为什么这么分工', 2)
    bullet(doc, '阈值判断是确定性的，交给规则 —— 节点数 4000 就是超标，'
                '模型说什么都改不了，从根上避免了幻觉')
    bullet(doc, '但「这六个指标合起来说明什么、该先修哪个」需要综合判断，交给模型')
    bullet(doc, '模型只能读到规则给出的结论，prompt 里明确禁止编造没给的数字')

    # ===== 三、12 条规则 =====
    h(doc, '三、12 条体检规则', 1)

    body(doc, '这部分是纯规则，没有 AI，但它是整个诊断的依据。'
              '阈值集中放在 ai_diagnose.py 开头，随时可调。', size=10.5)

    table(doc,
          ['规则', '级别', '判什么', '阈值'],
          [['image_unreadable', 'error', '图完全读不出来', '—'],
           ['too_few_nodes', 'error', '节点太少，可能什么都没提取到', '< 30'],
           ['too_many_nodes', 'warn', '节点太多，骨架被噪声撑爆', '> 1500'],
           ['high_isolation', 'error', '孤立节点比例高，连边失败', '> 25%（> 50% 升级 error）'],
           ['low_degree', 'warn', '平均度低，节点之间没连上', '< 1.5'],
           ['low_skeleton', 'warn', '骨架覆盖率太低', '< 0.5%'],
           ['high_skeleton', 'warn', '骨架覆盖率太高', '> 25%'],
           ['binary_ratio_extreme', 'warn', '二值化白色占比极端', '< 20% 或 > 80%'],
           ['gray_fill_walkable', 'warn', '灰色填充块被当成通道', '灰阶 195–250、面积 > 1%、> 50% 可走'],
           ['spur_skeleton', 'warn', '文字标注被细化成短线', '端点 > 10 个 / 千像素'],
           ['unlinked_seats', 'warn', '座位没连上路网', '—'],
           ['imread_fallback', 'warn', '普通读图接口读不到', '—']],
          widths=[4.2, 1.5, 5.6, 4.0])

    h(doc, '3.1 两条值得单独讲的规则', 2)

    body(doc, 'gray_fill_walkable —— 家具填充块被当成可通行区域', bold=True, indent=0)
    body(doc, '平面图里的灰色填充块（家具、设备、装饰）在二值化之后会变成实心区域，'
              '骨架提取会把它们的中心也连进路网，等于给了系统一条「穿过桌子」的路。'
              '这条规则的判据是：灰阶落在 195–250、面积占全图 1% 以上、'
              '并且其中一半以上被判成了可行走区域。', indent=0.5)

    body(doc, 'spur_skeleton —— 文字标注被细化成骨架短线', bold=True, indent=0)
    body(doc, '房间名、座位编号这类文字在细化之后会变成一堆短线段，'
              '每个字都可能贡献几个端点。判据是每千像素的骨架端点数超过 10 个 —— '
              '正常路网不会有这么多断头。', indent=0.5)

    quote(doc, '这两条不是凭空设的阈值，是从真实生成结果里看出来的失败模式：'
               '我们把生成的路网叠回原图，发现灰块中央被连了线、房间名变成了短线，'
               '才反过去写成了规则。')

    # ===== 四、AI 段实现 =====
    h(doc, '四、AI 那一段的完整实现', 1)

    h(doc, '4.1 模型', 2)
    body(doc, 'DeepSeek-flash。选它有两个理由：支持图片输入（诊断需要模型亲眼看图），'
              '成本与延迟可接受（诊断端到端约 2.5 秒）。模型在后台可切换。')

    h(doc, '4.2 看图是怎么处理的', 2)
    body(doc, '平面图先缩到长边 1024 像素，再转 JPEG（质量 85），base64 后作为 data URI 发送。')
    bullet(doc, '缩到 1024 而不是更小 —— 再小的话房间名和座位编号就认不出来了')
    bullet(doc, '转 JPEG 是为了体积 —— 一张 6600×4474 的 PNG 直接 base64 有十几 MB，'
                '缩放转码后通常一两百 KB')
    bullet(doc, '这一步耗时约 0.25 秒')

    h(doc, '4.3 System Prompt 的五条硬约束', 2)
    body(doc, '这段可以直接背给评委听：', size=10.5)
    code(doc,
         '1. 只能依据给定的事实数据与异常列表，不要编造没给的数字或结论。\n'
         '2. 用 2~4 句中文说清：生成得怎么样、主要问题、建议怎么改。\n'
         '   不要分点、不要罗列 JSON。\n'
         '3. 异常 code 的含义全部在 prompt 里解释清楚（避免模型猜）。\n'
         '4. 若异常为空，就说明指标正常，并指出纯骨架法的固有局限\n'
         '   （房间中央的星形/三角形枝杈）。\n'
         '5. 不要承诺「重新生成就会好」，给具体动作：裁剪图框、去文字标注、\n'
         '   换二值线稿、手工修正、或改用 DXF 走矢量路网。')

    body(doc, '第 1 条防幻觉。第 5 条明确禁止模型说「重试一下就好了」—— '
              '那是最没用、也最容易出现的建议。', indent=0)

    # ===== 五、降级链 =====
    h(doc, '五、三级降级链', 1)

    body(doc, '这一部分是稳定性设计，建议主动讲 —— 它回答了「如果模型不可用怎么办」。',
         size=10.5)

    code(doc,
         '① 图 + 数字一起发给模型    模型能看图时，诊断里会提到图上看到的东西\n'
         '        ↓ 失败（模型不支持图片输入）\n'
         '② 只发数字                 仍是完整诊断，只是模型没亲眼看图\n'
         '        ↓ 失败（模型不可用 / 超时 / 报错）\n'
         '③ 规则兜底文案             纯模板拼装，保证一定有输出')

    body(doc, '任何一级失败都不会让管理员拿到空白页。', bold=True)

    # ===== 六、话术 =====
    doc.add_page_break()
    h(doc, '六、答辩话术', 1)

    h(doc, '6.1 三十秒版（时间紧就用这个）', 2)
    quote(doc, '路网生成用的是形态学骨架提取，确定性算法，一张图大约 2.7 秒。'
               '但生成完我们不知道它好不好 —— 所以我们做了一套 12 条规则的体检，'
               '检查节点数、孤立比例、平均度、骨架覆盖率这些指标，能自动认出'
               '「灰色填充块被当成通道」「房间名被细化成短线」这类失败模式。'
               '然后让大模型看着原图和这些指标写一份诊断，告诉管理员问题在哪、该先修什么。'
               '规则负责查出来，模型负责说清楚 —— 不让模型去判断数字，它就编不出来。')

    h(doc, '6.2 九十秒版（加三个亮点）', 2)
    body(doc, '接上面那段，补三点：', size=10.5)
    quote(doc, '第一，AI 不参与画线。生成是确定性的，同样的图跑两次结果一样 —— '
               '这在这个场景里很重要，管理员改完重跑，能对比出到底哪里变了。')
    quote(doc, '第二，我们的规则是从真实失败里长出来的。比如 gray_fill_walkable 这一条：'
               '灰阶 195 到 250、面积超过 1%、有一半以上被判成可行走 —— '
               '这是我们发现家具填充块被当成通道之后，专门加的判断。')
    quote(doc, '第三，有三级降级。模型能看图就图文一起发；不支持图片就只发数字；'
               '模型挂了就用规则模板拼。任何一级失败，管理员拿到的都是一份完整诊断。')

    # ===== 七、预判问题 =====
    h(doc, '七、预判问题与回答', 1)

    qa = [
        ('路网是 AI 生成的吗？',
         '不是。生成是形态学骨架提取，确定性算法。AI 用在生成之后的诊断环节。'),
        ('用了什么模型？为什么选它？',
         'DeepSeek-flash。两个原因：支持图片输入，诊断需要模型亲眼看图；'
         '成本低、延迟可接受，诊断端到端约 2.5 秒。模型在后台可切换。'),
        ('AI 会不会胡说？',
         '三道防线。第一，12 条规则先算出结论，模型只能读这些数字；'
         '第二，prompt 第一条明确「只能依据给定事实，不要编造没给的数字」；'
         '第三，模型失败时降级到规则模板，输出一定在事实范围内。'),
        ('为什么不直接让 AI 生成路网？',
         '路网是空间拓扑，需要精确坐标和连通性，模型输出文本转成图结构误差不可控；'
         '而且生成要可复现 —— 管理员改一个参数得能对比出变化。'
         '所以把 AI 放在评估而不是生成，是刻意选择。'),
        ('诊断准不准？',
         '规则部分是确定性的，阈值有依据。模型部分受限于它看到的事实。'
         '如果指标都正常但路网确实有毛病，模型会指出来 —— '
         '我们在 prompt 里专门写了「若异常为空，指出纯骨架法的固有局限」。'),
        ('怎么验证 AI 诊断是对的？',
         '拿生成失败的图去跑，看它能不能说出我们肉眼看得出的问题。'
         '比如一张有大量灰色填充块的图，规则会报 gray_fill_walkable，'
         '模型会说明家具块被当成了可通行区域。'
         '我们用这套诊断发现过几个真实问题，然后反过去补了规则。'),
        ('这块 AI 和选座推荐那边的 AI 什么关系？',
         '同一套模型接入层，不同用途。选座推荐是让模型根据用户偏好从候选里挑并说明理由；'
         '路网诊断是让模型读指标写诊断。共用 LLM 客户端，但 prompt 和作用完全不同。'),
        ('12 条规则的阈值怎么定的？',
         '一部分来自实测。比如孤立比例 25% 这个数，是因为实测图片路线生成了 4243 个节点、'
         '31% 孤立，那个结果明显不可用，所以把 25% 设成警戒线、50% 设成错误线。'
         '另一部分是工程经验值，比如骨架覆盖率 0.5% 到 25% 这个区间。'
         '阈值集中放在文件开头，随时可调。'),
    ]
    for i, (q, a) in enumerate(qa, 1):
        body(doc, 'Q%d：%s' % (i, q), bold=True, indent=0)
        body(doc, 'A：%s' % a, indent=0.5)

    # ===== 八、局限 =====
    h(doc, '八、必须自己知道的局限', 1)

    body(doc, '这些不建议主动说，但被问到要能答。', size=10.5)

    table(doc,
          ['局限', '如果是真的，怎么答'],
          [['规则阈值以经验值为主',
            '只有孤立比例那条是从实测数据反推的，其余是工程经验值，集中可调'],
           ['诊断依赖模型服务',
            '断网或 API 挂了只剩规则兜底，但不会是空白页 —— 这就是降级链的意义'],
           ['纯骨架法的固有缺陷',
            '房间中央会走出星形/三角形枝杈，算法层没解决，只在诊断里如实说明'],
           ['诊断不自动修复',
            '只给建议，要管理员手动改参数重跑或换 DXF。自动化修复风险太大，没做']],
          widths=[4.6, 10.6])

    # ===== 九、演示 =====
    h(doc, '九、现场怎么演示', 1)

    body(doc, '别只讲，要能点出来。', bold=True)

    steps = [
        '管理端 →「平面图与路网」',
        '选一个楼层 → 点「自动生成」（图片路线）',
        '生成完 → 点「AI 诊断」→ 等 2~3 秒',
        '指着诊断文字说：「这里说灰色填充块被判断为可通行区域，'
        '左边指标里 gray_fill_walkable 这条规则确实报了」',
        '再演示 DXF 路线（如果有 DXF 文件）→ 画面对比：'
        '「DXF 直接读矢量，不需要猜，所以这版路网干净得多」',
    ]
    for i, s in enumerate(steps, 1):
        body(doc, '%d. %s' % (i, s), indent=0.4)

    body(doc, '第四步是关键 —— 把「规则报了什么」和「模型说了什么」对上，'
              '评委就能看出这不是套壳。', indent=0)

    doc.save(OUT)
    print('  输出：%s' % OUT)
    print('  大小：%.0f KB' % (os.path.getsize(OUT) / 1024))


if __name__ == '__main__':
    main()

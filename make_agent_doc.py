# -*- coding: utf-8 -*-
"""生成「AI 智能体源码解析 + 答辩问答」备赛文档。

内容包括：
  ① 整体设计（一次问答到底发生了什么）
  ② 源码逐段解析（真实代码，可直接对照 utils/ai_agent.py、utils/ai_tools.py）
  ③ 为什么这么设计（每个关键决策的取舍）
  ④ 答辩问答（AI 相关 12 题，含陷阱题）
  ⑤ 演示话术（现场怎么演给人看）
"""
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Cm, Pt, RGBColor

OUT = r'D:\MAX_xiangmu\docs\★智座-AI智能体源码与答辩准备.docx'


def setup(doc):
    st = doc.styles['Normal']
    st.font.name = '微软雅黑'
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(__import__('docx').oxml.ns.qn('w:eastAsia'), '微软雅黑')
    for s in doc.sections:
        s.top_margin = Cm(2.0)
        s.bottom_margin = Cm(2.0)
        s.left_margin = Cm(2.2)
        s.right_margin = Cm(2.2)


def h(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for r in p.runs:
        r.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
        r.font.name = '微软雅黑'
    return p


def para(doc, text, bold=False, size=10.5, color=None, after=4, indent=0):
    p = doc.add_paragraph()
    for i, seg in enumerate(text.split('**')):
        if not seg:
            continue
        r = p.add_run(seg)
        r.bold = bold or (i % 2 == 1)
        r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(after)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    return p


def code(doc, text, size=8.5):
    """代码块：等宽字体 + 浅灰底 + 左侧竖线。"""
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.rows[0].cells[0]
    cell.text = ''
    shade(cell, 'F4F5F7')
    first = True
    for line in text.splitlines():
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        r = p.add_run(line if line else ' ')
        r.font.name = 'Consolas'
        r.font.size = Pt(size)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def shade(cell, hex_color):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def table(doc, header, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = 'Light Grid Accent 1'
    for i, x in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ''
        r = c.paragraphs[0].add_run(x)
        r.bold = True
        r.font.size = Pt(9.5)
    for row in rows:
        cells = t.add_row().cells
        for i, x in enumerate(row):
            cells[i].text = ''
            for j, seg in enumerate(str(x).split('**')):
                if not seg:
                    continue
                r = cells[i].paragraphs[0].add_run(seg)
                r.bold = (j % 2 == 1)
                r.font.size = Pt(9)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


# ---------------------------------------------------------------------------

def build():
    doc = Document()
    setup(doc)

    title = doc.add_heading('智座 · AI 智能体源码解析与答辩准备', level=0)
    for r in title.runs:
        r.font.name = '微软雅黑'
    para(doc, '对应代码：utils/ai_agent.py（主循环）、utils/ai_tools.py（工具定义与实现）、'
              'app.py 的 /api/ai/agent 与 /api/ai/agent/confirm',
         size=9.5, color=RGBColor(0x66, 0x66, 0x66))

    # ===================== 一、整体设计 =====================
    h(doc, '一、一次问答到底发生了什么', 1)
    para(doc, '先把流程背下来，答辩时这一张图能讲两分钟。')
    code(doc, """用户提问
  ↓
模型判断要不要调工具 —— 不用 ——→ 直接回答
  ↓ 要
┌─ 只读工具 → 立刻执行 → 结果喂回模型 → 回到判断（最多 4 轮）
└─ 写工具   → 不执行，记成「待确认操作」→ 连同回答一起返回前端
  ↓
前端展示回答；有待确认操作就弹确认框，用户点了才真正执行
            （POST /api/ai/agent/confirm）""")

    para(doc, '**一句话概括**：模型只负责「决定调哪个工具、怎么组织语言」，'
              '**能不能真正改动数据，由代码控制，不由模型决定**。')

    para(doc, '')
    para(doc, '读工具 5 个（立刻执行）：', bold=True)
    table(doc, ['工具名', '干什么', '典型问法'], [
        ['list_buildings', '列出所有场所与楼层（含每层座位数）', '系统里有哪些地方？'],
        ['floor_stats', '某楼层的座位统计（空闲/占用/异常/关闭）', '哪个楼层座位最多？'],
        ['query_seats', '按楼层、状态、座位号关键字查明细', '三楼有哪些空座？'],
        ['find_free_seat', '找一个空闲座位，返回座位号与坐标', '帮我找个靠窗的座'],
        ['device_status', '传感器在线情况：谁掉了、掉多久、绑在哪', '有哪些设备掉线了？'],
    ])

    para(doc, '写工具 3 个（**只出提案，必须人确认**）：', bold=True)
    table(doc, ['工具名', '干什么', '风险点'], [
        ['set_seat_active', '开放 / 关闭一个座位', '关闭后对外不可见'],
        ['set_seat_ir', '开关某座位的红外检测', '影响占用判定'],
        ['close_floor_ir', '关闭整层红外（闭馆用）', '**一次影响几十个座位**'],
    ])

    doc.add_page_break()

    # ===================== 二、源码解析 =====================
    h(doc, '二、源码逐段解析', 1)

    h(doc, '2.1 系统提示词 —— 把行为约束写死在提示里', 2)
    para(doc, '位置：utils/ai_agent.py 的 _SYSTEM 常量。它不是「你是一个助手」这种空话，'
              '而是五条可执行的行为约束：')
    code(doc, """原则：
1. 先查再说。涉及具体座位、数量、设备状态的问题，必须先调用工具拿真实数据，
   不要凭印象回答，更不要编造座位号。
2. 回答短。用户问什么答什么，一般 1~3 句。
3. 如实说明数据边界。如果某楼层没有接入传感器，就说"未接入传感器"，
   不要把它说成"设备故障"或"异常"。
4. 修改类操作只提议。……不要在文字里假装已经做完了。
5. 如果用户的意图不明确（比如"收拾一下 A 区"），先问清楚要做什么，
   不要自己猜一个操作就提议。""")
    para(doc, '**为什么第 1 条要写成「不要编造座位号」**：模型没见过真实数据时，'
              '最自然的反应就是编一个看起来合理的座位号（比如「A-12」）。'
              '这种错误最难被发现 —— 用户会照着去找，找不到才知道是假的。')
    para(doc, '**为什么第 3 条要强调「未接入传感器」**：这是真实踩过的坑。'
              '某楼层没装设备时，座位状态一直不动，模型容易解释成「设备故障」——'
              '但事实上是根本没装。两者给管理员的行动完全不同。')

    h(doc, '2.2 主循环 —— 最多 4 轮，防止模型兜圈子', 2)
    para(doc, '位置：utils/ai_agent.py 的 run_agent()。核心就是这段：')
    code(doc, """MAX_ROUNDS = 4          # 工具调用最多几轮，防止模型来回兜圈子

for rnd in range(1, MAX_ROUNDS + 1):
    res = llm.chat_with_tools(messages, ai_tools.ALL_TOOL_DEFS,
                              max_tokens=500, temperature=0.2)
    if res is None:
        return {... 'text': 'AI 服务暂时不可用，请稍后再试。' ...}

    calls = res.get('tool_calls') or []
    if not calls:
        return {                      # 没有工具调用 = 模型认为可以回答了
            'text': res.get('content') or '（没有生成内容）',
            'actions': proposals,     # 待确认的写操作
            'used_tools': used_tools,
            'rounds': rnd,
            'ai_generated': True,
        }
    ...""")

    para(doc, '**三个关键数字，答辩会被问**：', bold=True)
    table(doc, ['参数', '值', '为什么是这个值'], [
        ['MAX_ROUNDS', '**4 轮**', '一般问法 1~2 轮就够（查楼层 → 查座位）。'
                                   '留 4 轮兜住「先查有什么楼，再查楼层，再查座位」这种多跳问题，'
                                   '再多就是模型在兜圈子了'],
        ['temperature', '**0.2**', '查数据要稳，不要发挥。事实性问题温度调高只会让模型更爱编'],
        ['max_tokens', '**500**', '提示词要求「回答短，1~3 句」。给多了模型反而会啰嗦'],
    ])

    h(doc, '2.3 写操作的处理 —— 整个设计里最重要的一段', 2)
    code(doc, """if name in ai_tools.WRITE_TOOL_NAMES:
    # ★ 写操作：只记成提议，绝不在这里执行
    if not ctx.get('is_admin'):
        messages.append({... 'content': _fmt_result({'error': '只有管理员可以执行这个操作'})})
        continue
    proposals.append({
        'tool': name,
        'args': args,
        'desc': ai_tools.describe_action(name, args),
    })
    messages.append({
        'role': 'tool', 'tool_call_id': call.get('id'),
        'content': _fmt_result({
            'status': 'pending_user_confirmation',
            'note': '操作已记录，等待用户在界面上确认后才会真正执行。'
                    '请在回答里说明你准备做什么，不要声称已经完成。',
        }),
    })
    used_tools.append(name)
    continue""")

    para(doc, '**这段做了四件事，每一件都有明确目的**：', bold=True)
    table(doc, ['动作', '防的是什么'], [
        ['`if not is_admin` 直接拒绝', '普通用户让 AI 把关座位，模型不懂权限，得靠代码拦'],
        ['不执行，只 append 到 proposals', '模型对自然语言理解有偏差，而写操作不可撤销。'
                                          '一句含糊的「把 A 区收拾一下」可能改掉几十条数据'],
        ['告诉模型「等待确认」', '否则模型会在回答里写成「已经帮您关闭了」——'
                              '用户以为生效了，实际没有，这是最坏的情况'],
        ['`describe_action()` 生成中文说明', '确认框里必须让人看懂将要发生什么，'
                                          '不能只显示 JSON 参数'],
    ])

    para(doc, '源码里的注释把这件事说得很直白：', size=10)
    code(doc, """为什么写操作要单独走一趟：
  模型对自然语言的理解有偏差，而写操作不可撤销。让它直接执行，
  一句含糊的话（"把 A 区收拾一下"）就可能改掉几十条数据。
  多一次点击，换来的是「模型理解错了也不会出事」。""")

    h(doc, '2.4 轮次用尽怎么办 —— 别让用户干等', 2)
    code(doc, """# 轮次用尽：把最后能拿到的话说出来，别让用户干等
return {
    'text': '这个问题我需要多查几步，先把已知的信息告诉你：请再具体一点，'
            '例如指明楼层或座位号。',
    'actions': proposals,
    'used_tools': used_tools,
    'rounds': MAX_ROUNDS,
    'ai_generated': True,
}""")
    para(doc, '**注意这里没有返回空字符串或报错**，而是给了一句引导用户细化问题的话，'
              '并且把已经收集到的 proposals 一起带回去 —— 前面几轮查到的东西不浪费。')

    h(doc, '2.5 工具出错不拖垮对话', 2)
    code(doc, """def run_read_tool(name, args, ctx):
    fn = READ_EXECUTORS.get(name)
    if not fn:
        return {'error': '未知的只读工具：%s' % name}
    try:
        return fn(args or {}, ctx)
    except Exception as e:      # noqa: BLE001 —— 工具出错不该拖垮对话
        logger.warning('AI 工具 %s 执行失败: %s', name, e, exc_info=True)
        return {'error': '工具执行失败：%s' % e}""")
    para(doc, '**设计要点**：工具抛异常不向上抛，而是包成 {"error": ...} 这样的结果返回给模型。'
              '模型收到错误后会自己换个问法或如实告诉用户，'
              '而不是整个对话崩掉。写工具额外多做一步 db.session.rollback()，'
              '保证失败的操作不会留半截脏数据。')

    h(doc, '2.6 权限与多校隔离', 2)
    code(doc, """def _check_floor_scope(floor_id, ctx):
    \"\"\"学校管理员只能动本校的楼层。超级管理员不受限。\"\"\"
    if ctx.get('is_super'):
        return None
    school_id = ctx.get('school_id')
    ...
    if b and b.school_id and b.school_id != school_id:
        return {'error': '无权操作其他学校的场所'}""")
    para(doc, '**这一层的意义**：AI 智能体是新的入口，权限校验不能只做在传统页面上。'
              '工具实现里复用了同一套学校归属判断，'
              '否则会出现「页面上看不到别的学校，但让 AI 关一下就能关」的漏洞。')

    doc.add_page_break()

    # ===================== 三、答辩问答 =====================
    h(doc, '三、答辩问答（AI 部分）', 1)
    para(doc, '这 12 题覆盖了评委最可能追问的角度。每题给「答法」和「为什么这么答」。',
         size=9.5, color=RGBColor(0x66, 0x66, 0x66))

    qa = [
        ('Q1', '你们的 AI 智能体和普通的问答机器人有什么区别？',
         '区别在于**它真的能查数据、也能操作系统，但系统不信任它**。'
         '普通问答机器人只生成文字。我们的助手有 8 个工具：5 个只读、3 个可写。'
         '只读的它自己调，写完的数据直接用来回答；可写的它只能「提议」，'
         '系统不会执行，要用户在确认框点一下才真正落库。'
         '所以它既不是纯聊天，也不是让模型直接操作数据库。',
         '**关键词是「系统不信任它」** —— 这句话最能体现工程思维，比说"我们很智能"强'),

        ('Q2', 'AI 会不会把座位状态改错？',
         '会有这个风险，所以我们从架构上把它挡掉了。'
         '第一，**判占永远不由模型决定** —— 座位有没有人，只由传感器读数经一条确定的规则算出，'
         '模型碰不到这条链路。'
         '第二，**写操作必须人工确认** —— 模型可以提议「关闭 A-3 座位」，'
         '但只生成一条待确认记录，前端弹框写明「关闭座位「A-3」」，用户点了才执行。'
         '第三，**权限在代码里校验** —— 模型不知道谁是管理员，'
         '是 `run_write_tool` 里先查 `is_admin`，不够就直接拒绝。',
         '这题的答案是整个 AI 设计的核心，**要能一口气说完**'),

        ('Q3', '为什么要多一次确认？不能自动执行吗？',
         '因为**写操作不可撤销，而模型对自然语言的理解有偏差**。'
         '举例：管理员随口说「把 A 区收拾一下」，模型可能理解成'
         '「关闭 A 区所有座位的红外检测」—— 一句话改掉几十条数据。'
         '多一次点击，换来的是「模型理解错了也不会出事」。'
         '这个取舍写在源码注释里，是我们想清楚之后做的决定，不是做不出来自动执行。',
         '**主动说出「不是做不出来」**，避免评委以为你们技术不够'),

        ('Q4', '模型怎么知道该调哪个工具？',
         '用 OpenAI 风格的工具调用（function calling）：我们把 8 个工具的'
         '名称、说明、参数结构（JSON Schema）一起发给模型，'
         '由模型自己决定要不要调、调哪个、参数填什么。'
         '比如用户说「三楼还有空座吗」，模型会先调 `list_buildings` 拿到楼层 ID，'
         '再调 `floor_stats` 或 `query_seats`。'
         '我们做的就是定义好工具、把结果喂回去，最多 4 轮。',
         '会追问「4 轮够吗」→ 见 Q5'),

        ('Q5', '最多 4 轮够吗？问题复杂怎么办？',
         '一般问法 1~2 轮就够（查楼层 → 查座位）。4 轮是留给多跳问题的余量，'
         '比如「哪个楼层的空座最多」要先列楼、再逐层统计。'
         '如果 4 轮还没结论，我们会返回一句「请再具体一点，例如指明楼层或座位号」，'
         '并把已经查到的内容一起带回去 —— 不让用户干等，也不假装答出来了。',
         '**「不假装答出来了」**这句很重要，比硬编一个答案强'),

        ('Q6', 'AI 会不会编造座位号？',
         '这是最容易出现的错误，所以我们有三道防线：'
         '① 系统提示词第一条就是「必须先调用工具拿真实数据，不要凭印象回答，更不要编造座位号」；'
         '② 温度设成 0.2，事实性问题不给模型发挥空间；'
         '③ 回答里出现的座位号，都是工具真实返回的字段，模型做的是组织和转述。'
         '即便这样也不能保证 100%，所以我们不把 AI 输出当作数据源 —— 它只是解释层。',
         '**承认「不能保证 100%」**，比说"绝对不会"可信'),

        ('Q7', '你们用了什么模型？能不能换？',
         '默认用 DeepSeek 的对话模型，走 OpenAI 兼容接口。'
         '实际上可以换 deepseek / openai / qwen / zhipu 四家，'
         '后台改配置就生效，不用重启 —— 因为客户端封装在 utils/llm.py 里，统一了调用方式。'
         '没配 Key 或调用失败时会自动降级成规则文案，页面不留空白。',
         '会追问「降级是什么样」→ 答：AI 不可用时页面照常可用，只是少了自然语言解释'),

        ('Q8', '这个智能体和你们的判占逻辑是什么关系？',
         '**完全解耦，这是设计上的硬边界**。座位占用由传感器读数经一条确定的与运算得出，'
         '可复现、可审计、能回溯每一次状态变化。'
         'AI 只读取状态、解释状态，不参与产生状态。'
         '如果让模型参与判占，一次幻觉就会把空座标成占用，用户白跑一趟，'
         '而且出了问题无法复盘「模型为什么这么判」。',
         '**这条是加分项**，主动讲能体现你们想清楚了 AI 的能力边界'),

        ('Q9', 'AI 功能有多少代码量？是不是就调个 API？',
         '不是。核心文件三个：`ai_agent.py`（主循环 153 行）、'
         '`ai_tools.py`（8 个工具的定义与实现，约 350 行）、`llm.py`（客户端封装）。'
         '真正的工作量不在调 API，而在：'
         '① 把系统能力拆成模型能理解的工具（参数怎么设计、说明怎么写才不让模型误解）；'
         '② 写操作的确认机制；'
         '③ 权限与多校隔离；'
         '④ 工具出错时不让对话崩掉。',
         '这题是给「是不是套壳」的质疑准备的，**用行数和具体工作项回答**'),

        ('Q10', '如果模型调用失败或者超时怎么办？',
         '三层兜底：① 调用返回 None 时直接给「AI 服务暂时不可用，请稍后再试」，'
         '不抛异常给用户看；② 工具执行抛异常时包成错误结果喂回模型，'
         '让模型自己换个问法，对话继续；③ 整块 AI 不可用时，'
         '页面的座位图、预约、导航全部照常工作 —— AI 是增强，不是依赖。',
         '**「AI 是增强，不是依赖」**这句话能显著提高印象分'),

        ('Q11', '多校场景下 AI 会不会越权？',
         '工具实现里复用了和页面同一套学校归属判断：'
         '学校管理员调 `close_floor_ir` 只能动本校楼层，'
         '`_check_floor_scope()` 会比对建筑所属学校，不是本校就直接返回「无权操作其他学校的场所」。'
         '超级管理员不受限。'
         '**关键点是：AI 是新的入口，权限不能只在老页面上做。**',
         '这题能证明你们想到了「新入口要重新过权限」，很多人会漏'),

        ('Q12', '（陷阱）你们这个智能体是不是很危险，能改数据？',
         '恰恰相反 —— **它能提议，但改不了**。模型没有任何直接写库的路径：'
         '所有写操作都先进 proposals 列表，前端弹确认框，用户点了才调确认接口执行，'
         '而且执行前还要过 `is_admin` 校验。'
         '换句话说，模型能做的最大恶是「提一个错误的建议」，'
         '而这个建议会被展示成人能看懂的中文（「关闭座位「A-3」」），用户不点就不会发生。',
         '**陷阱题，答案是「危险被架构挡住了」而不是「不危险」**'),
    ]

    for no, q, a, tip in qa:
        para(doc, '%s  %s' % (no, q), bold=True, size=11.5, after=3)
        para(doc, '答：' + a, size=10.5, after=3)
        para(doc, '💡 ' + tip, size=9.5, color=RGBColor(0xB0, 0x50, 0x00), after=9)

    doc.add_page_break()

    # ===================== 四、演示话术 =====================
    h(doc, '四、现场怎么演给人看（60 秒）', 1)
    para(doc, '不念代码，演三个动作就够 —— 每个动作都对应一个设计要点。')

    table(doc, ['步骤', '你做什么', '说什么'], [
        ['①', '点开 AI 助手，问「三楼还有空座吗」',
         '「它现在会去调 floor_stats，拿真实数据 —— 不是凭印象答」'],
        ['②', '再问「有哪些传感设备掉线了」',
         '「这一句对应 device_status，查的是真实心跳，不是模拟数据」'],
        ['③', '说「把 A-3 座位关掉」',
         '「注意它**没有直接执行**，而是弹了一个确认框，写着『关闭座位「A-3」』——'
         '**模型只能提议，改不改由人决定**」'],
    ])

    para(doc, '')
    para(doc, '**如果评委问「能自动吗」**：', bold=True)
    para(doc, '「技术上能，但我们不做。写操作不可撤销，而模型对自然语言有偏差 ——'
              '一句『把 A 区收拾一下』可能改掉几十条数据。多一次点击，'
              '换的是『模型理解错了也不会出事』。」')

    para(doc, '')
    para(doc, '**如果现场网络不行 / AI 不可用**：', bold=True)
    para(doc, '「正好演示降级 —— 你们看，AI 不可用时座位图、预约、导航全都照常工作，'
              '只是少了自然语言解释。**AI 是增强，不是依赖**。」')

    # 五、速记
    h(doc, '五、数字速记（被问到时能立刻报出来）', 1)
    table(doc, ['项', '值'], [
        ['工具总数', '**8 个**（5 个只读 + 3 个可写）'],
        ['最多工具调用轮次', '**4 轮**'],
        ['temperature / max_tokens', '**0.2 / 500**'],
        ['主循环代码量', 'utils/ai_agent.py **153 行**'],
        ['可切换模型供应商', '**4 家**（deepseek / openai / qwen / zhipu）'],
        ['后端自动化测试', '**476 项全过**'],
    ])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc.save(OUT)
    print('  已生成：%s' % OUT)
    print('  大小：%.1f KB' % (os.path.getsize(OUT) / 1024))
    print('  问答：%d 题' % len(qa))


if __name__ == '__main__':
    build()

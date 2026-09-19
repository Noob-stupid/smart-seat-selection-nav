# -*- coding: utf-8 -*-
"""AI 智能体：让助手真的能查数据、能操作系统。

一次问答的流程：

    用户提问
      ↓
    模型判断要不要调工具 ── 不用 ──→ 直接回答
      ↓ 要
    ┌─ 只读工具 → 立刻执行 → 结果喂回模型 → 回到判断（最多 4 轮）
    └─ 写工具   → **不执行**，记成「待确认操作」→ 连同回答一起返回前端
      ↓
    前端展示回答；如有待确认操作，弹出确认框，用户点了才调 /api/ai/agent/confirm

为什么写操作要单独走一趟：
  模型对自然语言的理解有偏差，而写操作不可撤销。让它直接执行，
  一句含糊的话（"把 A 区收拾一下"）就可能改掉几十条数据。
  多一次点击，换来的是「模型理解错了也不会出事」。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from utils import ai_tools
from utils.llm import get_llm

logger = logging.getLogger(__name__)

MAX_ROUNDS = 4          # 工具调用最多几轮，防止模型来回兜圈子

_SYSTEM = """你是「智座」——一个公共空间智能选座与导航系统的助手。

你可以调用工具去查真实数据，也可以提议修改系统（但修改必须经用户确认才会执行）。

原则：
1. **先查再说**。涉及具体座位、数量、设备状态的问题，必须先调用工具拿真实数据，
   不要凭印象回答，更不要编造座位号。
2. **回答短**。用户问什么答什么，一般 1~3 句。需要列座位时用逗号分隔的座位号。
3. **如实说明数据边界**。如果某楼层没有接入传感器，就说"未接入传感器"，
   不要把它说成"设备故障"或"异常"。
4. **修改类操作只提议**。用户让你关座位、开红外之类，你调用对应的写工具即可 ——
   系统不会直接执行，而是弹出确认框让用户点。不要在文字里假装已经做完了，
   可以说明"我准备执行以下操作，请确认"。
5. 如果用户的意图不明确（比如"收拾一下 A 区"），**先问清楚**要做什么，
   不要自己猜一个操作就提议。
"""


def _fmt_result(r: Any) -> str:
    try:
        return json.dumps(r, ensure_ascii=False, default=str)
    except Exception:                            # noqa: BLE001
        return str(r)


def run_agent(question: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """跑一轮智能体。返回 {text, actions, used_tools, rounds, ai_generated}。"""
    question = (question or '').strip()
    if not question:
        return {'text': '请说说你想做什么，例如「三楼还有空座吗」',
                'actions': [], 'used_tools': [], 'rounds': 0, 'ai_generated': False}

    llm = get_llm()
    if not llm.configured:
        return {'text': 'AI 服务当前不可用，请稍后再试。',
                'actions': [], 'used_tools': [], 'rounds': 0, 'ai_generated': False}

    messages: List[Dict[str, Any]] = [
        {'role': 'system', 'content': _SYSTEM},
        {'role': 'user', 'content': question},
    ]

    used_tools: List[str] = []
    proposals: List[Dict[str, Any]] = []

    for rnd in range(1, MAX_ROUNDS + 1):
        res = llm.chat_with_tools(
            messages, ai_tools.ALL_TOOL_DEFS, max_tokens=500, temperature=0.2)
        if res is None:
            return {'text': 'AI 服务暂时不可用，请稍后再试。',
                    'actions': [], 'used_tools': used_tools,
                    'rounds': rnd, 'ai_generated': False}

        calls = res.get('tool_calls') or []
        if not calls:
            return {
                'text': res.get('content') or '（没有生成内容）',
                'actions': proposals,
                'used_tools': used_tools,
                'rounds': rnd,
                'ai_generated': True,
            }

        # 把模型的这一次输出（含工具调用）记进上下文
        messages.append({
            'role': 'assistant',
            'content': res.get('content') or '',
            'tool_calls': calls,
        })

        for call in calls:
            fn = (call.get('function') or {})
            name = fn.get('name') or ''
            try:
                args = json.loads(fn.get('arguments') or '{}')
                if not isinstance(args, dict):
                    args = {}
            except (ValueError, TypeError):
                args = {}

            if name in ai_tools.WRITE_TOOL_NAMES:
                # ★ 写操作：只记成提议，绝不在这里执行
                if not ctx.get('is_admin'):
                    messages.append({
                        'role': 'tool', 'tool_call_id': call.get('id'),
                        'content': _fmt_result({'error': '只有管理员可以执行这个操作'}),
                    })
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
                continue

            # 只读工具：直接执行
            outcome = ai_tools.run_read_tool(name, args, ctx)
            used_tools.append(name)
            messages.append({
                'role': 'tool', 'tool_call_id': call.get('id'),
                'content': _fmt_result(outcome),
            })

    # 轮次用尽：把最后能拿到的话说出来，别让用户干等
    return {
        'text': '这个问题我需要多查几步，先把已知的信息告诉你：请再具体一点，'
                '例如指明楼层或座位号。',
        'actions': proposals,
        'used_tools': used_tools,
        'rounds': MAX_ROUNDS,
        'ai_generated': True,
    }

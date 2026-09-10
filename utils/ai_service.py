"""
AI 业务服务层（用户端 + 管理端）
================================

对外提供所有 AI 能力，内部统一走 `LLMClient`，并在**任何失败时降级为规则文案**。

铁律
----
* 座位是否被占用 → 由传感器 + 规则决定（本层只读取 `Seat.status`）。
* 大模型只负责「翻译成人话」与「从历史里发现模式」。
* 每个函数都保证返回**可直接展示的字符串**，绝不返回 None / 抛异常。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from models import db
from models.building import Floor, Seat
from models.reservation import Reservation
from models.user import User
from utils.ai_context import (
    build_messages,
    build_seat_snapshot,
    build_user_context,
    dumps_compact,
    snapshot_fingerprint,
)
from utils.llm import LLMClient, get_llm

logger = logging.getLogger(__name__)


# ==================================================================== 降级文案
def _fallback_brief(snap: Dict[str, Any]) -> str:
    """无 AI 时的「一句话结论」（纯规则生成）。"""
    total = snap.get('total', 0)
    free = snap.get('free', 0)
    occupied = snap.get('occupied', 0)
    if not total:
        return '当前没有可用的座位数据。'
    # 数据过期：不要给出误导性的"很空"结论
    if snap.get('data_stale'):
        ago = snap.get('last_report_minutes_ago')
        when = f'（最近一次上报在 {ago} 分钟前）' if ago is not None else ''
        return f'传感器数据已过期{when}，暂无法确认实时座位情况，请稍后重试或联系管理员。'
    if free == 0:
        return f'当前 {total} 个座位已全部占用，暂无空闲座位，建议稍后再来或前往其他楼层。'
    labels = snap.get('free_seat_labels') or []
    hint = f'例如 {labels[0]}' if labels else ''
    return (f'当前共 {total} 个座位，空闲 {free} 个、占用 {occupied} 个，'
            f'整体比较宽松，可直接前往{hint}。')


def _fallback_reason(seat_label: str, details: Optional[Dict[str, Any]]) -> str:
    """无 AI 时的「推荐理由」。"""
    if not details:
        return f'推荐 {seat_label}：当前空闲，可立即使用。'
    parts = []
    if details.get('distance_score') is not None:
        parts.append('距离较近')
    if details.get('preference_score') is not None:
        parts.append('匹配你的偏好')
    if details.get('heat_score') is not None:
        parts.append('热度适中')
    if details.get('crowd_score') is not None:
        parts.append('周边不拥挤')
    if not parts:
        parts.append('综合评分最高')
    return f'推荐 {seat_label}：{("、".join(parts))}。'


def _fallback_habit(ctx: Dict[str, Any]) -> str:
    """无 AI 时的「历史习惯」。"""
    if not ctx or not ctx.get('reservation_count_30d'):
        return '你近 30 天还没有预约记录，多使用几次后我就能总结你的习惯了。'
    bits = []
    favs = ctx.get('favorite_seats') or []
    if favs:
        bits.append(f'常坐 {favs[0]["seat"]}（{favs[0]["times"]} 次）')
    floors = ctx.get('favorite_floors') or []
    if floors:
        bits.append(f'偏好 {floors[0]["floor"]}')
    hours = ctx.get('usual_hours') or []
    if hours:
        bits.append(f'通常在 {hours[0]} 前后到馆')
    prefs = ctx.get('preferences') or {}
    if prefs.get('window'):
        bits.append('喜欢靠窗')
    if prefs.get('quiet'):
        bits.append('偏好安静区')
    if not bits:
        return f'你近 30 天预约了 {ctx["reservation_count_30d"]} 次。'
    return '你的习惯：' + '，'.join(bits) + '。'


def _fallback_admin_report(snap: Dict[str, Any]) -> str:
    """无 AI 时的「管理端简报」。"""
    total = snap.get('total', 0)
    free = snap.get('free', 0)
    occupied = snap.get('occupied', 0)
    rate = snap.get('occupancy_rate', 0)
    lines = [
        f'【现状】共 {total} 个座位，占用 {occupied} 个、空闲 {free} 个，'
        f'上座率约 {round(rate * 100)}%。'
    ]
    if snap.get('data_stale'):
        ago = snap.get('last_report_minutes_ago')
        when = f'{ago} 分钟前' if ago is not None else '未知时间'
        lines.append(f'【数据质量】⚠ 全部 {total} 个座位均无最新上报（最近一次在 {when}），'
                     f'疑似设备或网络整体掉线，当前状态可能不准确。')
    by_floor = snap.get('by_floor') or {}
    if by_floor:
        desc = '；'.join(f'{k} 空 {v.get("free", 0)}/{v.get("total", 0)}'
                        for k, v in by_floor.items())
        lines.append(f'【分楼层】{desc}。')
    abnormal = snap.get('abnormal_seats') or []
    if abnormal:
        names = '、'.join(a.get('seat', '?') for a in abnormal[:5])
        lines.append(f'【异常】{len(abnormal)} 个座位存在异常或仍停在占用但无上报：{names}，建议检查设备。')
    elif snap.get('data_stale'):
        lines.append('【异常】因数据整体过期，暂不做逐座位异常判定。')
    else:
        lines.append('【异常】未发现异常座位。')
    return '\n'.join(lines)


# ==================================================================== 用户端
class UserAIService:
    """用户端 AI：一句话结论、推荐理由、历史习惯、追问。"""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or get_llm()

    # ---------------------------------------------------------- 一句话结论
    def brief(self, building_id: Optional[int] = None,
              floor_id: Optional[int] = None,
              user_id: Optional[int] = None) -> Dict[str, Any]:
        """给用户的「一句话结论」——AI 生成，失败自动降级。"""
        snap = build_seat_snapshot(building_id=building_id, floor_id=floor_id)
        fallback = _fallback_brief(snap)

        facts: Dict[str, Any] = {'当前座位状态': snap}
        if user_id:
            try:
                facts['用户习惯'] = build_user_context(user_id)
            except Exception:
                logger.debug('构建用户画像失败，忽略', exc_info=True)

        text = self.llm.chat(build_messages(
            system_extra='你的任务是用一句话（不超过 60 字）告诉用户当前座位情况，并给出一个明确建议。',
            facts=facts,
            question='请用一句话总结当前座位情况并给出建议。',
        ), max_tokens=160)

        return {
            'text': text or fallback,
            'ai_generated': text is not None,
            'snapshot': snap,
        }

    # ---------------------------------------------------------- 推荐理由
    def explain_recommendation(self, seat_label: str,
                               details: Optional[Dict[str, Any]] = None,
                               user_id: Optional[int] = None,
                               snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """解释"为什么推荐这个座位"。"""
        snap = snapshot or build_seat_snapshot()
        fallback = _fallback_reason(seat_label, details)

        facts = {
            '推荐座位': seat_label,
            '评分明细': details or {},
            '当前座位状态': snap,
        }
        if user_id:
            try:
                facts['用户习惯'] = build_user_context(user_id)
            except Exception:
                logger.debug('构建用户画像失败，忽略', exc_info=True)

        text = self.llm.chat(build_messages(
            system_extra='你的任务是解释为什么推荐这个座位，一到两句话，突出与用户习惯的契合点。',
            facts=facts,
            question=f'为什么推荐座位 {seat_label}？',
        ), max_tokens=200)

        return {'text': text or fallback, 'ai_generated': text is not None}

    # ---------------------------------------------------------- 历史习惯
    def habit_insight(self, user_id: int) -> Dict[str, Any]:
        """总结用户的历史使用习惯。"""
        try:
            ctx = build_user_context(user_id)
        except Exception:
            logger.exception('构建用户画像失败')
            return {'text': '暂时无法读取你的历史记录。', 'ai_generated': False}

        fallback = _fallback_habit(ctx)
        text = self.llm.chat(build_messages(
            system_extra='你的任务是根据用户的历史记录，用两三句话总结其使用习惯并给一条贴心建议。',
            facts={'用户历史': ctx},
            question='请总结这位用户的使用习惯，并给一条建议。',
        ), max_tokens=240)

        return {'text': text or fallback, 'ai_generated': text is not None, 'context': ctx}

    # ---------------------------------------------------------- 追问
    def ask(self, question: str, user_id: Optional[int] = None,
            building_id: Optional[int] = None,
            floor_id: Optional[int] = None) -> Dict[str, Any]:
        """自然语言追问（用户端）。"""
        question = (question or '').strip()
        if not question:
            return {'text': '请描述你的问题，例如"有没有安静的座位？"', 'ai_generated': False}

        snap = build_seat_snapshot(building_id=building_id, floor_id=floor_id)
        facts: Dict[str, Any] = {'当前座位状态': snap}
        if user_id:
            try:
                facts['用户习惯'] = build_user_context(user_id)
            except Exception:
                logger.debug('构建用户画像失败，忽略', exc_info=True)

        text = self.llm.chat(build_messages(
            system_extra='你的任务是回答用户关于座位的提问，回答要简短、直接给出座位号。',
            facts=facts,
            question=question,
        ), max_tokens=300)

        if text is None:
            # 降级：至少把当前空闲情况说清楚
            return {'text': _fallback_brief(snap), 'ai_generated': False}
        return {'text': text, 'ai_generated': True}


# ==================================================================== 管理端
class AdminAIService:
    """管理端 AI：运营简报、异常发现、趋势解读、问答。"""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or get_llm()

    # ---------------------------------------------------------- 运营简报
    def daily_report(self, building_id: Optional[int] = None) -> Dict[str, Any]:
        """生成当前运营简报（自然语言）。"""
        snap = build_seat_snapshot(building_id=building_id)
        fallback = _fallback_admin_report(snap)

        text = self.llm.chat(build_messages(
            system_extra=(
                '你是场馆运营分析助手。请生成一份简短运营简报，'
                '分「现状」「分楼层」「异常」三点，每点一两句话，总长不超过 150 字。'
            ),
            facts={'当前座位状态': snap},
            question='请生成当前运营简报。',
        ), max_tokens=400)

        return {'text': text or fallback, 'ai_generated': text is not None, 'snapshot': snap}

    # ---------------------------------------------------------- 异常发现
    def anomaly_report(self, building_id: Optional[int] = None) -> Dict[str, Any]:
        """传感器/座位异常发现（把"设备掉线"变成产品功能）。"""
        snap = build_seat_snapshot(building_id=building_id)
        abnormal = snap.get('abnormal_seats') or []
        stale = snap.get('data_stale')
        ago = snap.get('last_report_minutes_ago')

        # 全局离线：所有座位都无最新上报 -> 这是整体掉线，优先提示
        if stale:
            when = f'{ago} 分钟前' if ago is not None else '未知时间'
            fallback = (f'⚠ 全部 {snap.get("total", 0)} 个座位均无最新上报（最近一次在 {when}），'
                        f'疑似传感器网关/网络整体掉线。建议检查：ESP32 供电与指示灯、'
                        f'所连 WiFi 是否可上网、服务器隧道是否正常。')
            text = self.llm.chat(build_messages(
                system_extra=(
                    '你是设备运维助手。当前所有座位都没有最新上报，属于整体掉线。'
                    '请判断最可能的原因并给出按优先级排序的排查步骤，不超过 150 字。'
                ),
                facts={'数据状态': snap},
                question='为什么所有座位都没有数据？应该如何排查？',
            ), max_tokens=350)
            return {'text': text or fallback, 'ai_generated': text is not None,
                    'abnormal': [], 'global_offline': True, 'snapshot': snap}

        if not abnormal:
            return {'text': '未发现异常座位，所有传感器工作正常。',
                    'ai_generated': False, 'abnormal': [], 'global_offline': False,
                    'snapshot': snap}

        fallback = (f'发现 {len(abnormal)} 个异常座位：'
                    + '、'.join(a.get('seat', '?') for a in abnormal[:6])
                    + '。建议检查对应传感器接线或供电。')

        text = self.llm.chat(build_messages(
            system_extra=(
                '你是设备运维助手。请根据异常座位列表，判断可能的故障原因'
                '（如设备掉线、传感器故障、接线问题），并给出排查建议，不超过 150 字。'
            ),
            facts={'异常座位': abnormal, '当前座位状态': snap},
            question='这些座位为什么异常？应该如何排查？',
        ), max_tokens=350)

        return {'text': text or fallback, 'ai_generated': text is not None,
                'abnormal': abnormal, 'global_offline': False, 'snapshot': snap}

    # ---------------------------------------------------------- 趋势解读
    def trend_analysis(self, days: int = 7, building_id: Optional[int] = None) -> Dict[str, Any]:
        """从历史上报数据里总结趋势。"""
        days = max(1, min(int(days or 7), 90))
        now = datetime.utcnow()
        since = now - timedelta(days=days)

        try:
            from models.sensor_data import SensorData
            rows = (
                db.session.query(SensorData.timestamp, SensorData.ir_front, SensorData.ir_back)
                .filter(SensorData.timestamp >= since)
                .all()
            )
        except Exception:
            logger.exception('读取历史传感器数据失败')
            rows = []

        if not rows:
            return {'text': f'近 {days} 天暂无足够传感器数据可供分析。',
                    'ai_generated': False, 'stats': {}}

        daily: Dict[str, Dict[str, int]] = {}
        for ts, front, back in rows:
            if not ts:
                continue
            key = ts.strftime('%Y-%m-%d')
            bucket = daily.setdefault(key, {'samples': 0, 'occupied': 0})
            bucket['samples'] += 1
            if front == 1 and back == 1:
                bucket['occupied'] += 1

        series = [
            {'date': k,
             'samples': v['samples'],
             'occupied': v['occupied'],
             'rate': round(v['occupied'] / v['samples'], 3) if v['samples'] else 0.0}
            for k, v in sorted(daily.items())
        ]
        peak = max(series, key=lambda x: x['rate']) if series else None
        stats = {
            'days': days,
            'total_samples': len(rows),
            'daily': series,
            'peak_day': peak,
        }
        fallback = (f'近 {days} 天共采集 {len(rows)} 条传感器数据。'
                    + (f'占用率最高的是 {peak["date"]}（约 {round(peak["rate"] * 100)}%）。'
                       if peak else ''))

        text = self.llm.chat(build_messages(
            system_extra=(
                '你是数据分析助手。请根据每日占用率数据，用两三句话总结趋势，'
                '指出高峰时段或高峰日，并给一条运营建议。不要编造数据里没有的日期。'
            ),
            facts={'趋势数据': stats},
            question=f'请总结近 {days} 天的座位使用趋势。',
        ), max_tokens=400)

        return {'text': text or fallback, 'ai_generated': text is not None, 'stats': stats}

    # ---------------------------------------------------------- 管理端问答
    def ask(self, question: str, building_id: Optional[int] = None) -> Dict[str, Any]:
        """管理端自然语言问答。"""
        question = (question or '').strip()
        if not question:
            return {'text': '请输入问题，例如"现在哪个楼层最紧张？"', 'ai_generated': False}

        snap = build_seat_snapshot(building_id=building_id)
        text = self.llm.chat(build_messages(
            system_extra='你是场馆运营助手，回答管理员的问题，简洁准确，可以给运营建议。',
            facts={'当前座位状态': snap},
            question=question,
        ), max_tokens=400)

        return {'text': text or _fallback_admin_report(snap), 'ai_generated': text is not None}


# ==================================================================== 终端
def terminal_brief(building_id: Optional[int] = None,
                   floor_id: Optional[int] = None,
                   user_id: Optional[int] = None,
                   max_len: int = 48) -> Dict[str, Any]:
    """智能终端用极简结论（超长自动截断，适配 OLED 小屏）。

    返回精简字段：text / ai_generated / free / total，便于 ESP32 等
    资源受限设备直接解析，不必传输完整快照。
    """
    service = UserAIService()
    result = service.brief(building_id=building_id, floor_id=floor_id, user_id=user_id)
    text = (result.get('text') or '').replace('\n', ' ').strip()
    if max_len and len(text) > max_len:
        text = text[:max_len - 1] + '…'
    snap = result.get('snapshot') or {}
    return {
        'text': text,
        'ai_generated': result.get('ai_generated', False),
        'total': snap.get('total', 0),
        'free': snap.get('free', 0),
        'occupied': snap.get('occupied', 0),
        'data_stale': snap.get('data_stale', False),
    }


# ==================================================================== 单例
_user_ai: Optional[UserAIService] = None
_admin_ai: Optional[AdminAIService] = None


def get_user_ai() -> UserAIService:
    global _user_ai
    if _user_ai is None:
        _user_ai = UserAIService()
    return _user_ai


def get_admin_ai() -> AdminAIService:
    global _admin_ai
    if _admin_ai is None:
        _admin_ai = AdminAIService()
    return _admin_ai


def reset_ai_services() -> None:
    """配置变更后重建（配合 reload_llm 使用）。"""
    global _user_ai, _admin_ai
    _user_ai = None
    _admin_ai = None

"""
AI 上下文构建层（状态快照 + 用户画像）
=====================================

**这是控制 token 成本与调用延迟的关键模块。**

不把 50 个座位的原始记录丢给大模型（那样每次几千~几万 token），
而是压成一份"结构化摘要"（几百 token）：总数、空闲数、楼层分布、
异常设备、以及少量值得注意的座位明细。

同时从预约/锁定历史里提炼「用户习惯画像」，供模型生成个性化建议。

注意：本模块只做**事实汇总**，不做任何判断结论——
判断由规则引擎负责，大模型只负责把事实翻译成人话。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from models import db
from models.building import Building, Floor, Seat
from models.reservation import Reservation
from models.user import User
from models.sensor_device import SensorDevice


# ---------------------------------------------------------------- 工具
def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _minutes_since(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if not dt:
        return None
    return int((now - dt).total_seconds() // 60)


# ---------------------------------------------------------------- 座位快照
def build_seat_snapshot(
    building_id: Optional[int] = None,
    floor_id: Optional[int] = None,
    now: Optional[datetime] = None,
    detail_limit: int = 8,
) -> Dict[str, Any]:
    """构建座位状态快照（紧凑摘要，供大模型消费）。

    Args:
        building_id: 限定建筑；None 表示全库。
        floor_id: 限定楼层；None 表示不限。
        now: 当前时间（便于测试注入）。
        detail_limit: 最多附带多少个"值得注意"的座位明细。

    Returns:
        紧凑字典，可直接 json.dumps 后喂给模型。
    """
    now = now or datetime.utcnow()

    query = Seat.query.join(Floor).filter(Seat.is_active == True)  # noqa: E712
    if building_id:
        query = query.filter(Floor.building_id == building_id)
    if floor_id:
        query = query.filter(Seat.floor_id == floor_id)
    seats: List[Seat] = query.all()

    total = len(seats)
    counts = {'free': 0, 'occupied': 0, 'locked': 0, 'error': 0}
    by_floor: Dict[str, Dict[str, int]] = {}
    free_seats: List[Seat] = []
    candidates: List[Dict[str, Any]] = []
    silent_count = 0
    no_sensor_count = 0
    newest_scan: Optional[datetime] = None

    # 已接入传感器设备的座位集合。未接入的座位（尚未安装硬件）不参与
    # "静默/异常"判定，否则会被误报成"传感器故障"。
    try:
        instrumented_ids = {
            row[0] for row in
            db.session.query(SensorDevice.seat_id)
            .filter(SensorDevice.seat_id.isnot(None)).all()
        }
    except Exception:
        instrumented_ids = set()

    for s in seats:
        st = s.status or 'free'
        is_instrumented = (not instrumented_ids) or (s.id in instrumented_ids)
        if not is_instrumented:
            no_sensor_count += 1
        counts[st] = counts.get(st, 0) + 1

        floor_name = s.floor.name if s.floor and s.floor.name else (
            f'{s.floor.floor_number}F' if s.floor else '未知'
        )
        bucket = by_floor.setdefault(floor_name, {'total': 0, 'free': 0, 'occupied': 0})
        bucket['total'] += 1
        if st == 'free':
            bucket['free'] += 1
            free_seats.append(s)
        elif st == 'occupied':
            bucket['occupied'] += 1

        silent_min = _minutes_since(s.last_scan_time, now)
        if s.last_scan_time and (newest_scan is None or s.last_scan_time > newest_scan):
            newest_scan = s.last_scan_time
        # 静默判定：从未上报，或超过 10 分钟没有新数据（仅针对已接入传感器的座位）
        is_silent = (silent_min is None) or (silent_min >= 10)
        if is_silent and is_instrumented:
            silent_count += 1
            candidates.append({
                'seat': s.seat_label,
                'status': st,
                'silent_minutes': silent_min,
            })

    occupancy_rate = round(counts['occupied'] / total, 3) if total else 0.0
    instrumented_total = total - no_sensor_count
    # 只把"已接入传感器但全体静默"视为整体掉线
    all_silent = instrumented_total > 0 and silent_count == instrumented_total

    # 异常座位筛选：
    #  * 全局离线（所有座位都静默）-> 这是"设备/网络整体掉线"，不是单个座位异常，
    #    只在 data_stale 里提示，不再逐条列出（否则 50 个座位全被报异常，报告无意义）。
    #  * 局部异常 -> 只挑"状态不对劲"的：error 状态，或仍停在 occupied 却已长时间无上报
    #    （即"僵尸占用"，正是设备掉线后没人释放的典型表现）。
    abnormal: List[Dict[str, Any]] = []
    if not all_silent:
        for c in candidates:
            if c['status'] == 'error':
                abnormal.append(c)
            elif c['status'] in ('occupied', 'locked'):
                abnormal.append(c)
        # error 状态即使不静默也算异常（仍只针对已接入传感器的座位）
        for s in seats:
            if not ((not instrumented_ids) or (s.id in instrumented_ids)):
                continue
            if (s.status == 'error') and all(a['seat'] != s.seat_label for a in abnormal):
                abnormal.append({
                    'seat': s.seat_label,
                    'status': 'error',
                    'silent_minutes': _minutes_since(s.last_scan_time, now),
                })

    snapshot: Dict[str, Any] = {
        'time': now.strftime('%Y-%m-%d %H:%M'),
        'scope': {'building_id': building_id, 'floor_id': floor_id},
        'total': total,
        'free': counts.get('free', 0),
        'occupied': counts.get('occupied', 0),
        'locked': counts.get('locked', 0),
        'error': counts.get('error', 0),
        'occupancy_rate': occupancy_rate,
        'by_floor': by_floor,
        # 空闲座位号（最多列 20 个，避免 prompt 膨胀）
        'free_seat_labels': [s.seat_label for s in free_seats[:20]],
        'abnormal_seats': abnormal[:detail_limit],
        'abnormal_total': len(abnormal),
        # 数据新鲜度：让模型知道"数据是否可信"
        'data_stale': all_silent,
        'silent_seat_count': silent_count,
        'last_report_minutes_ago': _minutes_since(newest_scan, now),
        # 已接入传感器 / 未接入传感器的座位数（未接入的不算故障）
        'instrumented_total': instrumented_total,
        'no_sensor_count': no_sensor_count,
    }
    return snapshot


def snapshot_fingerprint(snapshot: Dict[str, Any]) -> str:
    """给快照算指纹，用于缓存键与"状态是否变化"判断。"""
    core = {
        'total': snapshot.get('total'),
        'free': snapshot.get('free'),
        'occupied': snapshot.get('occupied'),
        'locked': snapshot.get('locked'),
        'error': snapshot.get('error'),
        'by_floor': snapshot.get('by_floor'),
        'free_labels': snapshot.get('free_seat_labels'),
        'abnormal': [a.get('seat') for a in snapshot.get('abnormal_seats', [])],
        'stale': snapshot.get('data_stale'),
    }
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------- 用户画像
def build_user_context(user_id: int, days: int = 30,
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """构建用户习惯画像（偏好 + 预约历史 + 锁定行为）。"""
    now = now or datetime.utcnow()
    ctx: Dict[str, Any] = {'user_id': user_id}

    user = db.session.get(User, user_id)
    if not user:
        return ctx

    prefs = user.preferences or {}
    ctx['name'] = user.name
    ctx['preferences'] = {
        'window': bool(prefs.get('window')),
        'quiet': bool(prefs.get('quiet')),
        'tags': prefs.get('tags') or [],
    }

    since = now - timedelta(days=days)
    reservations = (
        Reservation.query
        .filter(Reservation.user_id == user_id, Reservation.created_at >= since)
        .order_by(Reservation.created_at.desc())
        .limit(50)
        .all()
    )

    seat_counter: Dict[str, int] = {}
    floor_counter: Dict[str, int] = {}
    hour_counter: Dict[int, int] = {}
    for r in reservations:
        seat = db.session.get(Seat, r.seat_id) if r.seat_id else None
        if seat:
            seat_counter[seat.seat_label] = seat_counter.get(seat.seat_label, 0) + 1
            fname = seat.floor.name if seat.floor and seat.floor.name else (
                f'{seat.floor.floor_number}F' if seat.floor else '未知'
            )
            floor_counter[fname] = floor_counter.get(fname, 0) + 1
        if r.start_time:
            hour_counter[r.start_time.hour] = hour_counter.get(r.start_time.hour, 0) + 1

    ctx['reservation_count_30d'] = len(reservations)

    if seat_counter:
        top = sorted(seat_counter.items(), key=lambda kv: -kv[1])[:3]
        ctx['favorite_seats'] = [{'seat': k, 'times': v} for k, v in top]
    if floor_counter:
        top_floor = sorted(floor_counter.items(), key=lambda kv: -kv[1])[:2]
        ctx['favorite_floors'] = [{'floor': k, 'times': v} for k, v in top_floor]
    if hour_counter:
        top_hours = sorted(hour_counter.items(), key=lambda kv: -kv[1])[:3]
        ctx['usual_hours'] = [f'{h:02d}:00' for h, _ in top_hours]

    return ctx


# ---------------------------------------------------------------- 提示词组装
def dumps_compact(data: Dict[str, Any]) -> str:
    """紧凑 JSON（无多余空白），进一步压 token。"""
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


SYSTEM_GUARD = (
    '你是一个图书馆座位管理系统的智能助手。\n'
    '严格要求：\n'
    '1. 只能依据给定的事实数据回答，绝不编造座位号、人数或时间。\n'
    '2. 座位是否有人的判断已由传感器确定，你不需要也不允许重新判断。\n'
    '3. 回答简洁、口语化，直接给出结论和建议，不要罗列数据表格。\n'
    '4. 涉及推荐时必须给出具体座位号。\n'
    '5. 用中文回答。\n'
    '6. 注意区分「未接入传感器」（no_sensor_count，尚未安装硬件，属正常情况，'
    '不要描述为故障）与「传感器异常」（abnormal_seats，已接入但失联，才是故障）。'
    '描述整体情况时，应以「已接入传感器的座位」为准。'
)


def build_messages(system_extra: str, facts: Dict[str, Any], question: str) -> List[Dict[str, str]]:
    """组装消息列表：系统约束 + 事实数据 + 用户问题。"""
    system = SYSTEM_GUARD + ('\n' + system_extra if system_extra else '')
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': f'【事实数据】{dumps_compact(facts)}\n\n【任务】{question}'},
    ]

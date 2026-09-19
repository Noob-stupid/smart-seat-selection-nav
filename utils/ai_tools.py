# -*- coding: utf-8 -*-
"""AI 助手的工具调用层。

让大模型不只是"聊天"，而是真的能查数据、能操作系统。

设计上分两类，这个区分是刻意的：

  · **只读工具（READ_TOOLS）** —— 查座位、查设备、找空位、看统计。
    模型可以直接调用，结果喂回模型继续推理，用户看到的就是一个答得上来的助手。

  · **写工具（WRITE_TOOLS）** —— 关闭/开放座位、开关红外。
    **模型不允许直接执行**，只能"提议"。提议会随回答一起返回前端，
    由用户点确认后才真正落库。

为什么写操作一定要卡一道：
  大模型对自然语言的理解是有偏差的。用户说「把 A 区收拾一下」，
  模型完全可能理解成「把 A 区所有座位关掉」。如果让它直接执行，
  一句含糊的话就能改掉几十条数据，而且没有撤销。
  加一道确认，代价是一次点击，换来的是「模型理解错了也不会出事」。

权限：写工具只有管理员能用（学校管理员限本校），在 agent 层校验。
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Dict, List, Optional

from models import db
from models.building import Building, Floor, Seat
from models.sensor_device import SensorDevice

logger = logging.getLogger(__name__)

# 座位状态的中文名，给模型和用户看
STATUS_TEXT = {
    'free': '空闲',
    'occupied': '已占用',
    'locked': '已预约',
    'error': '异常',
}


# ---------------------------------------------------------------------------
# 工具定义（OpenAI function calling 格式）
# ---------------------------------------------------------------------------

def _fn(name: str, desc: str, params: Dict[str, Any], required: Optional[List[str]] = None):
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': desc,
            'parameters': {
                'type': 'object',
                'properties': params,
                'required': required or [],
                # 部分模型要求显式声明；DeepSeek 兼容 OpenAI 格式
                'additionalProperties': False,
            },
        },
    }


_P_FLOOR = {'type': 'integer', 'description': '楼层ID。不确定就先调 list_buildings 查。'}
_P_LIMIT = {'type': 'integer', 'description': '最多返回多少条，默认 20，上限 100。'}

READ_TOOL_DEFS = [
    _fn('list_buildings', '列出所有场所（建筑）及其楼层，含每层的座位数。想知道系统里有哪些地方、楼层ID是多少，先调这个。', {}),
    _fn('floor_stats', '查某个楼层的座位统计：总数、空闲、占用、已预约、异常、已关闭各多少。',
        {'floor_id': _P_FLOOR}, ['floor_id']),
    _fn('query_seats', '按条件查座位明细。可按楼层、状态（free/occupied/locked/error）、座位号关键字筛选。',
        {'floor_id': _P_FLOOR,
         'status': {'type': 'string', 'enum': ['free', 'occupied', 'locked', 'error'],
                    'description': '只查该状态的座位'},
         'keyword': {'type': 'string', 'description': '座位号关键字，如 "A-" 或 "A-1"'},
         'limit': _P_LIMIT}),
    _fn('find_free_seat', '找一个当前空闲的座位，返回座位号、坐标和所在楼层。用户说"帮我找个座"时用这个。',
        {'floor_id': _P_FLOOR,
         'seat_type': {'type': 'string', 'enum': ['normal', 'window', 'quiet', 'power'],
                       'description': '偏好类型：window 靠窗 / quiet 安静 / power 有电源'}}),
    _fn('device_status', '查传感设备的在线情况：哪些设备在线、哪些掉线多久了、分别绑在哪个座位。',
        {'limit': _P_LIMIT}),
]

WRITE_TOOL_DEFS = [
    _fn('set_seat_active', '【需要用户确认】开放或关闭一个座位。关闭后该座位不再对外显示、不可预约，但历史记录保留。',
        {'seat_id': {'type': 'integer', 'description': '座位ID'},
         'active': {'type': 'boolean', 'description': 'true=开放，false=关闭'}},
        ['seat_id', 'active']),
    _fn('set_seat_ir', '【需要用户确认】开关某个座位的红外传感器检测。',
        {'seat_id': {'type': 'integer', 'description': '座位ID'},
         'enabled': {'type': 'boolean', 'description': 'true=开启检测，false=关闭'}},
        ['seat_id', 'enabled']),
    _fn('close_floor_ir', '【需要用户确认】关闭某个楼层全部座位的红外检测（闭馆时用）。',
        {'floor_id': _P_FLOOR}, ['floor_id']),
]

ALL_TOOL_DEFS = READ_TOOL_DEFS + WRITE_TOOL_DEFS

READ_TOOL_NAMES = {t['function']['name'] for t in READ_TOOL_DEFS}
WRITE_TOOL_NAMES = {t['function']['name'] for t in WRITE_TOOL_DEFS}


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def _seat_brief(s: Seat) -> Dict[str, Any]:
    return {
        'seat_id': s.id,
        'seat_label': s.seat_label,
        'floor_id': s.floor_id,
        'status': s.status,
        'status_text': STATUS_TEXT.get(s.status, s.status),
        'x': round(s.x or 0, 1),
        'y': round(s.y or 0, 1),
    }


def _t_list_buildings(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    out = []
    for b in Building.query.filter_by(is_active=True).order_by(Building.id).all():
        floors = []
        for f in Floor.query.filter_by(building_id=b.id, is_active=True).order_by(Floor.floor_number).all():
            floors.append({
                'floor_id': f.id,
                'name': f.name or ('%s楼' % f.floor_number),
                'floor_number': f.floor_number,
                'seat_count': Seat.query.filter_by(floor_id=f.id, is_active=True).count(),
            })
        out.append({'building_id': b.id, 'name': b.name, 'floors': floors})
    return {'buildings': out}


def _t_floor_stats(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    fid = int(args['floor_id'])
    floor = db.session.get(Floor, fid)
    if not floor:
        return {'error': '楼层 %s 不存在' % fid}
    q = Seat.query.filter_by(floor_id=fid)
    active = q.filter_by(is_active=True)
    stat = {
        'floor_id': fid,
        'floor_name': floor.name or ('%s楼' % floor.floor_number),
        'total_active': active.count(),
        'closed': q.filter_by(is_active=False).count(),
    }
    for k, text in STATUS_TEXT.items():
        stat[k] = active.filter_by(status=k).count()
        stat[k + '_text'] = text
    return stat


def _t_query_seats(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    limit = min(int(args.get('limit') or 20), 100)
    q = Seat.query.filter_by(is_active=True)
    if args.get('floor_id'):
        q = q.filter_by(floor_id=int(args['floor_id']))
    if args.get('status'):
        q = q.filter_by(status=args['status'])
    if args.get('keyword'):
        q = q.filter(Seat.seat_label.like('%%%s%%' % args['keyword']))
    rows = q.order_by(Seat.floor_id, Seat.seat_label).limit(limit).all()
    total = q.count()
    return {'total_matched': total, 'returned': len(rows),
            'seats': [_seat_brief(s) for s in rows]}


def _t_find_free_seat(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    q = Seat.query.filter_by(is_active=True, status='free')
    if args.get('floor_id'):
        q = q.filter_by(floor_id=int(args['floor_id']))
    if args.get('seat_type'):
        q = q.filter_by(seat_type=args['seat_type'])
    seat = q.order_by(Seat.floor_id, Seat.seat_label).first()
    if not seat:
        # 放宽类型再找一个，别直接说没有
        seat = Seat.query.filter_by(is_active=True, status='free').first()
        if seat:
            return {'found': True, 'matched_preference': False,
                    'seat': _seat_brief(seat),
                    'note': '没有符合偏好的空位，这是任意一个空闲座位'}
        return {'found': False, 'note': '当前没有任何空闲座位'}
    return {'found': True, 'matched_preference': True, 'seat': _seat_brief(seat)}


def _t_device_status(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    limit = min(int(args.get('limit') or 20), 100)
    from config import Config
    timeout_min = int(getattr(Config, 'SEAT_ONLINE_TIMEOUT_MINUTES', 3))
    now = _dt.datetime.utcnow()
    devs = SensorDevice.query.order_by(SensorDevice.last_seen.desc().nullslast()).limit(limit).all()
    online, offline = [], []
    for d in devs:
        age = None
        if d.last_seen:
            age = round((now - d.last_seen).total_seconds())
        row = {
            'device_id': d.device_id,
            'seat_id': d.seat_id,
            'seat_label': None,
            'sensor_type': d.sensor_type,
            'last_seen_sec_ago': age,
        }
        if d.seat_id:
            s = db.session.get(Seat, d.seat_id)
            if s:
                row['seat_label'] = s.seat_label
        if age is not None and age <= timeout_min * 60:
            online.append(row)
        else:
            offline.append(row)
    return {'online_count': len(online), 'offline_count': len(offline),
            'online_timeout_minutes': timeout_min,
            'online': online, 'offline': offline}


def _t_set_seat_active(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    seat = db.session.get(Seat, int(args['seat_id']))
    if not seat:
        return {'error': '座位 %s 不存在' % args['seat_id']}
    bad = _check_floor_scope(seat.floor_id, ctx)
    if bad:
        return bad
    seat.is_active = bool(args['active'])
    db.session.commit()
    return {'ok': True, 'seat_id': seat.id, 'seat_label': seat.seat_label,
            'is_active': seat.is_active,
            'message': '已%s座位 %s' % ('开放' if seat.is_active else '关闭', seat.seat_label)}


def _t_set_seat_ir(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    seat = db.session.get(Seat, int(args['seat_id']))
    if not seat:
        return {'error': '座位 %s 不存在' % args['seat_id']}
    bad = _check_floor_scope(seat.floor_id, ctx)
    if bad:
        return bad
    if not hasattr(seat, 'ir_enabled'):
        return {'error': '当前数据模型没有红外开关字段'}
    seat.ir_enabled = bool(args['enabled'])
    db.session.commit()
    return {'ok': True, 'seat_id': seat.id, 'seat_label': seat.seat_label,
            'ir_enabled': seat.ir_enabled,
            'message': '已%s座位 %s 的红外检测' % ('开启' if seat.ir_enabled else '关闭', seat.seat_label)}


def _t_close_floor_ir(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    fid = int(args['floor_id'])
    bad = _check_floor_scope(fid, ctx)
    if bad:
        return bad
    if not hasattr(Seat, 'ir_enabled'):
        return {'error': '当前数据模型没有红外开关字段'}
    seats = Seat.query.filter_by(floor_id=fid, is_active=True).all()
    n = 0
    for s in seats:
        if s.ir_enabled is not False:
            s.ir_enabled = False
            n += 1
    db.session.commit()
    return {'ok': True, 'floor_id': fid, 'changed': n,
            'message': '已关闭该楼层 %d 个座位的红外检测' % n}


def _check_floor_scope(floor_id: int, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """学校管理员只能动本校的楼层。超级管理员不受限。"""
    if ctx.get('is_super'):
        return None
    school_id = ctx.get('school_id')
    if not school_id:
        return None
    floor = db.session.get(Floor, floor_id)
    if not floor:
        return {'error': '楼层不存在'}
    b = db.session.get(Building, floor.building_id)
    if b and b.school_id and b.school_id != school_id:
        return {'error': '无权操作其他学校的场所'}
    return None


READ_EXECUTORS = {
    'list_buildings': _t_list_buildings,
    'floor_stats': _t_floor_stats,
    'query_seats': _t_query_seats,
    'find_free_seat': _t_find_free_seat,
    'device_status': _t_device_status,
}

WRITE_EXECUTORS = {
    'set_seat_active': _t_set_seat_active,
    'set_seat_ir': _t_set_seat_ir,
    'close_floor_ir': _t_close_floor_ir,
}


def run_read_tool(name: str, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    fn = READ_EXECUTORS.get(name)
    if not fn:
        return {'error': '未知的只读工具：%s' % name}
    try:
        return fn(args or {}, ctx)
    except Exception as e:                       # noqa: BLE001 —— 工具出错不该拖垮对话
        logger.warning('AI 工具 %s 执行失败: %s', name, e, exc_info=True)
        return {'error': '工具执行失败：%s' % e}


def run_write_tool(name: str, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    fn = WRITE_EXECUTORS.get(name)
    if not fn:
        return {'error': '未知的写工具：%s' % name}
    if not ctx.get('is_admin'):
        return {'error': '只有管理员可以执行这个操作'}
    try:
        return fn(args or {}, ctx)
    except Exception as e:                       # noqa: BLE001
        logger.warning('AI 写工具 %s 执行失败: %s', name, e, exc_info=True)
        db.session.rollback()
        return {'error': '操作失败：%s' % e}


# ---------------------------------------------------------------------------
# 把「提议」翻译成人话，供前端确认框显示
# ---------------------------------------------------------------------------

def describe_action(name: str, args: Dict[str, Any]) -> str:
    """给写操作生成一句中文说明 —— 这句会显示在确认框里，必须准确。"""
    a = args or {}
    try:
        if name == 'set_seat_active':
            seat = db.session.get(Seat, int(a.get('seat_id')))
            who = ('「%s」' % seat.seat_label) if seat else ('座位#%s' % a.get('seat_id'))
            return '%s座位 %s' % ('开放' if a.get('active') else '关闭', who)
        if name == 'set_seat_ir':
            seat = db.session.get(Seat, int(a.get('seat_id')))
            who = ('「%s」' % seat.seat_label) if seat else ('座位#%s' % a.get('seat_id'))
            return '%s %s 的红外检测' % ('开启' if a.get('enabled') else '关闭', who)
        if name == 'close_floor_ir':
            fid = int(a.get('floor_id'))
            floor = db.session.get(Floor, fid)
            fname = (floor.name or ('%s楼' % floor.floor_number)) if floor else ('楼层#%s' % fid)
            n = Seat.query.filter_by(floor_id=fid, is_active=True).count()
            return '关闭「%s」全部 %d 个座位的红外检测' % (fname, n)
    except Exception:                            # noqa: BLE001
        logger.debug('生成操作说明失败', exc_info=True)
    return '执行 %s' % name

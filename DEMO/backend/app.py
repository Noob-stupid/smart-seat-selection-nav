# -*- coding: utf-8 -*-
"""
功能一：物联网感知 —— Flask 后端

本后端承担三件事：
1. 接收 ESP32 上传的扫描数据，维护“座椅状态表”供前端查询；
2. 采用“连续两次无人”的确认逻辑，降低单次扫描误判；
3. 实现核心创新“动态锁定防抢座”：
   - 座位连续占用满 m 分钟后，客户端可发起锁定；
   - 锁定后每 n 分钟自动检测一次；
   - n 分钟后无人则自动解锁，有人则保持锁定并重新计时；
   - 记录用户历史锁定频次与平均离座时长，对高频锁定且长期不归的用户
     动态提高 m 门槛或缩短 n，防止恶意锁座。
"""

import os
import sqlite3
import time

from flask import Flask, g, jsonify, request


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "seat_state.db")

# ==================== 动态锁定参数 ====================
M_BASE = 10          # 基础 m：连续占用满 10 分钟才允许锁定
N_BASE = 5           # 基础 n：锁定后每 5 分钟自动检测一次
M_STEP = 5           # 每次惩罚后 m 提高 5 分钟
N_STEP = 2           # 每次惩罚后 n 缩短 2 分钟
N_MIN = 2            # n 最短不低于 2 分钟
MAX_PUNISHMENT = 3   # 最多累计 3 次惩罚，防止参数无限恶化

# 行为感知判定阈值
LOCK_HISTORY_MIN = 3        # 历史锁定次数达到 3 次才算“高频”
LONG_AWAY_MINUTES = 10.0    # 单次/平均离座达到 10 分钟才算“长期不归”

# 连续多少次扫描无人后才把座位更新为空闲（与设备端保持一致）
VACANT_CONFIRM_SCANS = 2


app = Flask(__name__)


def get_db():
    """每个请求独立使用一个 sqlite 连接。"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    """请求结束后关闭数据库连接。"""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据表，重复启动不会覆盖已有数据。"""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS seats (
            id TEXT PRIMARY KEY,
            occupied INTEGER NOT NULL DEFAULT 0,
            occupied_since REAL,
            updated_at REAL,
            consecutive_empty INTEGER NOT NULL DEFAULT 0,
            locked INTEGER NOT NULL DEFAULT 0,
            lock_user TEXT,
            lock_since REAL,
            lock_check_at REAL
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            lock_count INTEGER NOT NULL DEFAULT 0,
            total_lock_minutes REAL NOT NULL DEFAULT 0,
            last_unlock_at REAL,
            punishment INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS lock_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seat_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            lock_since REAL,
            unlocked_at REAL,
            away_minutes REAL
        );

        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seat_id TEXT NOT NULL,
            occupied INTEGER NOT NULL,
            sensor_a INTEGER,
            sensor_b INTEGER,
            scan_type TEXT,
            created_at REAL
        );
        """
    )
    conn.commit()
    conn.close()


def to_bool(value):
    """把 JSON 里的各种 true/false 写法统一转成 bool。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("true", "1", "yes")


def ensure_seat(seat_id):
    """确保座椅记录存在，不存在则插入一条空闲记录。"""
    db = get_db()
    row = db.execute("SELECT * FROM seats WHERE id = ?", (seat_id,)).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO seats (id, occupied, consecutive_empty, locked) "
            "VALUES (?, 0, 0, 0)",
            (seat_id,),
        )
        db.commit()
        row = db.execute("SELECT * FROM seats WHERE id = ?", (seat_id,)).fetchone()
    return row


def effective_params(user_id):
    """
    根据用户历史行为计算当前用户的 m 和 n。

    规则：被判定为恶意锁座的用户，punishment 每 +1，
    m 提高 M_STEP 分钟，n 缩短 N_STEP 分钟，且 n 不低于 N_MIN。
    """
    punishment = 0
    if user_id:
        db = get_db()
        row = db.execute(
            "SELECT punishment FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            punishment = row["punishment"] or 0

    m = M_BASE + punishment * M_STEP
    n = max(N_MIN, N_BASE - punishment * N_STEP)
    return m, n


def insert_lock_event(seat_id, user_id, action, lock_since=None,
                      unlocked_at=None, away_minutes=None):
    """写入锁定事件日志。"""
    db = get_db()
    db.execute(
        "INSERT INTO lock_events "
        "(seat_id, user_id, action, lock_since, unlocked_at, away_minutes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (seat_id, user_id, action, lock_since, unlocked_at, away_minutes),
    )


def punish_if_abusing(user_id, away_minutes):
    """
    行为感知：
    如果用户历史锁定次数 >= LOCK_HISTORY_MIN，
    且平均离座时长和本次离座时长都 >= LONG_AWAY_MINUTES，
    判定为“高频锁定且长期不归”，punishment +1。
    """
    db = get_db()
    row = db.execute(
        "SELECT lock_count, total_lock_minutes, punishment "
        "FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return False

    lock_count = row["lock_count"] or 0
    if lock_count < LOCK_HISTORY_MIN:
        return False

    avg_away = (row["total_lock_minutes"] or 0.0) / lock_count
    if avg_away < LONG_AWAY_MINUTES or away_minutes < LONG_AWAY_MINUTES:
        return False

    new_punishment = min(
        (row["punishment"] or 0) + 1,
        MAX_PUNISHMENT,
    )
    db.execute(
        "UPDATE users SET punishment = ? WHERE user_id = ?",
        (new_punishment, user_id),
    )
    return True


def check_locked_seat(seat_id):
    """
    锁定后的 n 分钟自动检测：
    - 若当前仍有人：保持锁定，重置 lock_check_at，重新计时 n 分钟；
    - 若当前无人：自动解锁，记录离座时长并更新用户行为档案。
    """
    db = get_db()
    seat = db.execute(
        "SELECT * FROM seats WHERE id = ?", (seat_id,)
    ).fetchone()
    if not seat or not seat["locked"]:
        return None

    now = time.time()
    n = effective_params(seat["lock_user"])[1]
    last_check = seat["lock_check_at"] or now

    # n 分钟还没到，暂不检测
    if now - last_check < n * 60:
        return None

    if seat["occupied"]:
        # 有人：保持锁定并重新计时
        db.execute(
            "UPDATE seats SET lock_check_at = ? WHERE id = ?",
            (now, seat_id),
        )
        insert_lock_event(
            seat_id, seat["lock_user"], "LOCK_RENEW",
            lock_since=seat["lock_since"],
        )
        db.commit()
        return {"action": "LOCK_RENEW", "message": "仍有人占用，锁定已续期"}

    # 无人：自动解锁
    lock_since = seat["lock_since"] or now
    away_minutes = max(0.0, (now - lock_since) / 60.0)

    db.execute(
        "UPDATE seats SET locked = 0, lock_user = NULL, "
        "lock_since = NULL, lock_check_at = NULL WHERE id = ?",
        (seat_id,),
    )

    user_id = seat["lock_user"]
    db.execute(
        "INSERT INTO users (user_id, lock_count, total_lock_minutes, last_unlock_at) "
        "VALUES (?, 1, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "lock_count = lock_count + 1, "
        "total_lock_minutes = total_lock_minutes + excluded.total_lock_minutes, "
        "last_unlock_at = excluded.last_unlock_at",
        (user_id, away_minutes, now),
    )
    insert_lock_event(
        seat_id, user_id, "UNLOCK_AUTO",
        lock_since=lock_since,
        unlocked_at=now,
        away_minutes=away_minutes,
    )
    punished = punish_if_abusing(user_id, away_minutes)
    db.commit()

    return {
        "action": "UNLOCK_AUTO",
        "message": "n 分钟后无人，自动解锁",
        "away_minutes": round(away_minutes, 1),
        "punished": punished,
    }


@app.after_request
def add_cors_headers(response):
    """允许浏览器前端跨域调用，方便后续接入 Web 页面。"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/api/health", methods=["GET"])
def health():
    """健康检查接口。"""
    return jsonify({"status": "ok", "time": time.time()})


@app.route("/api/scan", methods=["POST"])
def receive_scan():
    """
    接收 ESP32 的扫描数据。
    后端同样只允许“连续两次无人”后才把座位改为空闲。
    """
    data = request.get_json(silent=True) or {}
    seat_id = str(data.get("seat_id", "")).strip()
    if not seat_id:
        return jsonify({"success": False, "message": "seat_id 不能为空"}), 400

    occupied = to_bool(data.get("occupied", False))
    sensor_a = int(bool(data.get("sensor_a", False)))
    sensor_b = int(bool(data.get("sensor_b", False)))
    scan_type = str(data.get("scan_type", "scan"))
    now = time.time()

    db = get_db()
    seat = ensure_seat(seat_id)

    # 记录原始扫描日志
    db.execute(
        "INSERT INTO scans "
        "(seat_id, occupied, sensor_a, sensor_b, scan_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (seat_id, int(occupied), sensor_a, sensor_b, scan_type, now),
    )

    if occupied:
        # 有人：如果是空闲转有人，记录占用起始时间
        if not seat["occupied"]:
            db.execute(
                "UPDATE seats SET occupied = 1, occupied_since = ?, "
                "consecutive_empty = 0, updated_at = ? WHERE id = ?",
                (now, now, seat_id),
            )
        else:
            db.execute(
                "UPDATE seats SET occupied = 1, consecutive_empty = 0, "
                "updated_at = ? WHERE id = ?",
                (now, seat_id),
            )
    else:
        # 无人：先累计连续无人次数，达到阈值才真正清空
        consecutive = (seat["consecutive_empty"] or 0) + 1
        if seat["occupied"] and consecutive >= VACANT_CONFIRM_SCANS:
            db.execute(
                "UPDATE seats SET occupied = 0, occupied_since = NULL, "
                "consecutive_empty = ?, updated_at = ? WHERE id = ?",
                (consecutive, now, seat_id),
            )
        else:
            db.execute(
                "UPDATE seats SET consecutive_empty = ?, updated_at = ? "
                "WHERE id = ?",
                (consecutive, now, seat_id),
            )

    db.commit()

    # 若该座位处于锁定状态，顺便执行 n 分钟自动检测
    lock_result = check_locked_seat(seat_id)
    seat = db.execute(
        "SELECT * FROM seats WHERE id = ?", (seat_id,)
    ).fetchone()

    return jsonify({
        "success": True,
        "seat": {
            "seat_id": seat_id,
            "occupied": bool(seat["occupied"]),
            "locked": bool(seat["locked"]),
        },
        "lock_check": lock_result,
    })


@app.route("/api/seat/<seat_id>/lock", methods=["POST"])
def lock_seat(seat_id):
    """
    客户端锁定接口。
    要求座位当前有人，且已连续占用满当前用户的动态 m 分钟。
    """
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    if not user_id:
        return jsonify({"success": False, "message": "user_id 不能为空"}), 400

    db = get_db()
    seat = ensure_seat(seat_id)
    now = time.time()

    if not seat["occupied"]:
        return jsonify({
            "success": False,
            "message": "座位当前无人，无法锁定",
        }), 409

    if seat["locked"]:
        return jsonify({
            "success": False,
            "message": "座位已被锁定",
            "lock_user": seat["lock_user"],
        }), 409

    m, n = effective_params(user_id)
    occupied_minutes = (now - (seat["occupied_since"] or now)) / 60.0
    if occupied_minutes < m:
        return jsonify({
            "success": False,
            "code": "TOO_EARLY",
            "message": f"连续占用未满 {m} 分钟，暂不能锁定",
            "required_minutes": m,
            "occupied_minutes": round(occupied_minutes, 1),
        }), 409

    db.execute(
        "UPDATE seats SET locked = 1, lock_user = ?, "
        "lock_since = ?, lock_check_at = ? WHERE id = ?",
        (user_id, now, now, seat_id),
    )
    insert_lock_event(seat_id, user_id, "LOCK_START", lock_since=now)
    db.commit()

    return jsonify({
        "success": True,
        "message": f"锁定成功，每 {n} 分钟自动检测一次",
        "seat_id": seat_id,
        "locked": True,
        "lock_since": now,
    })


@app.route("/api/seat/status", methods=["GET"])
def seat_status():
    """
    前端查询接口：返回所有座椅当前占用、锁定状态和动态参数。
    """
    db = get_db()
    now = time.time()
    rows = db.execute("SELECT * FROM seats ORDER BY id").fetchall()

    result = []
    for row in rows:
        user_id = row["lock_user"]
        m, n = effective_params(user_id if row["locked"] else None)
        occupied_minutes = 0.0
        if row["occupied_since"]:
            occupied_minutes = max(0.0, (now - row["occupied_since"]) / 60.0)

        locked_minutes = 0.0
        next_check_seconds = None
        if row["locked"] and row["lock_check_at"]:
            locked_minutes = max(0.0, (now - (row["lock_since"] or now)) / 60.0)
            remaining = n * 60 - (now - row["lock_check_at"])
            next_check_seconds = max(0.0, remaining)

        result.append({
            "seat_id": row["id"],
            "occupied": bool(row["occupied"]),
            "occupied_minutes": round(occupied_minutes, 1),
            "consecutive_empty": row["consecutive_empty"],
            "locked": bool(row["locked"]),
            "lock_user": row["lock_user"],
            "locked_minutes": round(locked_minutes, 1),
            "next_check_seconds": next_check_seconds,
            "effective_m_minutes": m,
            "effective_n_minutes": n,
            "updated_at": row["updated_at"],
        })

    return jsonify({"success": True, "seats": result})


@app.route("/api/users/<user_id>", methods=["GET"])
def user_behavior(user_id):
    """查看某个用户的历史锁定行为与当前动态惩罚等级。"""
    db = get_db()
    row = db.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        return jsonify({
            "success": True,
            "user": {
                "user_id": user_id,
                "lock_count": 0,
                "total_lock_minutes": 0.0,
                "avg_away_minutes": 0.0,
                "punishment": 0,
                "effective_m_minutes": M_BASE,
                "effective_n_minutes": N_BASE,
            },
        })

    m, n = effective_params(user_id)
    avg_away = (
        (row["total_lock_minutes"] or 0.0) / row["lock_count"]
        if row["lock_count"]
        else 0.0
    )
    return jsonify({
        "success": True,
        "user": {
            "user_id": user_id,
            "lock_count": row["lock_count"],
            "total_lock_minutes": round(row["total_lock_minutes"], 1),
            "avg_away_minutes": round(avg_away, 1),
            "last_unlock_at": row["last_unlock_at"],
            "punishment": row["punishment"],
            "effective_m_minutes": m,
            "effective_n_minutes": n,
        },
    })


@app.route("/", methods=["GET"])
def index():
    """接口说明页。"""
    return jsonify({
        "service": "ESP32 红外座椅感知后端",
        "endpoints": [
            "POST /api/scan",
            "POST /api/seat/<seat_id>/lock",
            "GET  /api/seat/status",
            "GET  /api/users/<user_id>",
            "GET  /api/health",
        ],
    })


init_db()


if __name__ == "__main__":
    # 0.0.0.0 表示局域网内 ESP32 和其他设备都能访问
    app.run(host="0.0.0.0", port=5000, debug=True)

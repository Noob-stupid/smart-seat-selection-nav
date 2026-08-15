"""
预约模型 - 支持模式2：选座式预约
"""
from datetime import datetime
from . import db


class Reservation(db.Model):
    """座位预约记录"""
    __tablename__ = 'reservations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    seat_id = db.Column(db.Integer, db.ForeignKey('seats.id'), nullable=False)
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=False)

    # 预约时间
    start_time = db.Column(db.DateTime, nullable=False, comment='预约开始时间')
    end_time = db.Column(db.DateTime, nullable=False, comment='预约结束时间')
    checkin_time = db.Column(db.DateTime, nullable=True, comment='实际签到时间')
    checkout_time = db.Column(db.DateTime, nullable=True, comment='实际签退时间')

    # 预约凭证
    qr_code_path = db.Column(db.String(255), nullable=True, comment='二维码凭证路径')
    qr_token = db.Column(db.String(64), unique=True, nullable=False, comment='二维码Token')

    # 状态
    status = db.Column(db.Enum('pending', 'checked_in', 'completed', 'cancelled', 'no_show'),
                       default='pending', comment='预约状态')
    timeout_minutes = db.Column(db.Integer, default=15, comment='超时未签到自动释放(分钟)')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    seat = db.relationship('Seat', backref='reservations')

    def to_dict(self):
        # 数据库存的是 naive UTC，序列化时补 'Z' 声明 UTC，
        # 前端 new Date(...) 才能正确换算成本地时间
        def _utc_iso(v):
            return v.isoformat() + 'Z' if v else None

        return {
            'id': self.id,
            'user_id': self.user_id,
            'seat_id': self.seat_id,
            'seat_label': self.seat.seat_label if self.seat else None,
            'building_id': self.building_id,
            'start_time': _utc_iso(self.start_time),
            'end_time': _utc_iso(self.end_time),
            'checkin_time': _utc_iso(self.checkin_time),
            'checkout_time': _utc_iso(self.checkout_time),
            'status': self.status,
            'qr_token': self.qr_token,
            'created_at': _utc_iso(self.created_at),
        }

    def __repr__(self):
        return f'<Reservation {self.id} user={self.user_id} seat={self.seat_id}>'


class LockRecord(db.Model):
    """锁定记录 - 行为分析数据源"""
    __tablename__ = 'lock_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    seat_id = db.Column(db.Integer, db.ForeignKey('seats.id'), nullable=False)
    floor_id = db.Column(db.Integer, db.ForeignKey('floors.id'), nullable=False)

    lock_start = db.Column(db.DateTime, nullable=False, comment='锁定开始时间')
    lock_end = db.Column(db.DateTime, nullable=True, comment='锁定结束时间')
    duration_sec = db.Column(db.Float, nullable=True, comment='锁定持续秒数')

    detection_count = db.Column(db.Integer, default=0, comment='锁定期间检测次数')
    valid_return_count = db.Column(db.Integer, default=0, comment='有效回归次数')
    unoccupied_sec = db.Column(db.Float, default=0.0, comment='锁定期间无人累计秒数')

    is_abnormal = db.Column(db.Boolean, default=False, comment='是否异常锁定')
    auto_unlocked = db.Column(db.Boolean, default=False, comment="是否自动解锁（无人超时）")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'seat_id': self.seat_id,
            'floor_id': self.floor_id,
            'lock_start': self.lock_start.isoformat() if self.lock_start else None,
            'lock_end': self.lock_end.isoformat() if self.lock_end else None,
            'duration_sec': self.duration_sec,
            'detection_count': self.detection_count,
            'valid_return_count': self.valid_return_count,
            'unoccupied_sec': self.unoccupied_sec,
            'return_rate': round(self.valid_return_count / self.detection_count, 4) if self.detection_count > 0 else 0,
            'absence_rate': round(self.unoccupied_sec / self.duration_sec, 4) if self.duration_sec and self.duration_sec > 0 else 0,
            'is_abnormal': self.is_abnormal,
            'auto_unlocked': self.auto_unlocked,
        }

    def __repr__(self):
        return f'<LockRecord {self.id} user={self.user_id} seat={self.seat_id}>'

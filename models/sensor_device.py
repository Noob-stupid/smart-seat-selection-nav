"""
传感器设备模型 - 记录每台 ESP32 硬件设备及其配置/在线状态。

设备以 WiFi MAC 作为唯一 device_id（无需人工编号），首次联网时自动注册；
管理员在「硬件 / 传感器调试」面板里为其绑定座位、选择传感器类型、设定上报间隔，
设备启动时会向服务器拉取配置（device_config），从而做到“改配置不用重烧固件”。
"""
from datetime import datetime

from . import db


class SensorDevice(db.Model):
    __tablename__ = 'sensor_devices'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # 设备唯一标识（默认取 ESP32 的 WiFi MAC）
    device_id = db.Column(db.String(64), unique=True, nullable=False, index=True, comment='设备唯一ID(WiFi MAC)')
    # 绑定的座位（可空，未绑定则不生效）
    seat_id = db.Column(db.Integer, db.ForeignKey('seats.id'), nullable=True, comment='绑定座位ID')
    # 传感器类型：True=检测到人输出HIGH(HC-SR501/PIR)；False=检测到物体输出LOW(红外避障)
    ir_active_high = db.Column(db.Boolean, default=True, comment='传感器电平 true=PIR(HIGH) false=红外(LOW)')
    # 传感器类型：pir=HC-SR501(PIR) / ir=红外避障 / ultrasonic=HC-SR04P(超声波测距)
    sensor_type = db.Column(db.String(20), default='pir', comment='传感器类型 pir/ir/ultrasonic')
    # 超声波(HCSR04P)判定“有人”的距离阈值（厘米）：距离小于该值视为占用
    distance_threshold_cm = db.Column(db.Integer, default=50, comment='超声波距离阈值(cm)')
    # 上报间隔（毫秒）
    report_interval_ms = db.Column(db.Integer, default=5000, comment='上报间隔(毫秒)')
    # 最近一次上报/心跳时间，用于在线判断与“新设备上线”提示
    last_seen = db.Column(db.DateTime, nullable=True, comment='最近上线时间')
    # 是否已被管理员“查看/认领”过（新设备上线提示用）
    is_new = db.Column(db.Boolean, default=True, comment='是否全新未处理设备')
    registered_at = db.Column(db.DateTime, default=datetime.utcnow, comment='注册时间')

    seat = db.relationship('Seat', foreign_keys=[seat_id], backref=db.backref('sensor_devices', lazy='dynamic'))

    def to_dict(self, include_seat=True):
        data = {
            'id': self.id,
            'device_id': self.device_id,
            'ir_active_high': self.ir_active_high,
            'sensor_type': self.sensor_type,
            'distance_threshold_cm': self.distance_threshold_cm,
            'report_interval_ms': self.report_interval_ms,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'is_new': self.is_new,
            'registered_at': self.registered_at.isoformat() if self.registered_at else None,
        }
        if include_seat:
            data['seat_id'] = self.seat_id
            if self.seat:
                data['seat_label'] = self.seat.seat_label
                data['floor_name'] = self.seat.floor.name if self.seat.floor else ''
            else:
                data['seat_label'] = None
                data['floor_name'] = ''
        return data

    def __repr__(self):
        return f'<SensorDevice {self.device_id} seat={self.seat_id}>'

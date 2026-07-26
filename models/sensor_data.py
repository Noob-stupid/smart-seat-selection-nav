"""
传感器数据模型 - 记录红外传感器上报数据
"""
from datetime import datetime
from . import db


class SensorData(db.Model):
    """传感器原始数据记录"""
    __tablename__ = 'sensor_data'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    seat_id = db.Column(db.Integer, db.ForeignKey('seats.id'), nullable=False)
    ir_front = db.Column(db.Integer, default=0, comment='前方红外 0/1')
    ir_back = db.Column(db.Integer, default=0, comment='后方红外 0/1')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, comment='扫描时间戳')

    def __repr__(self):
        return f'<SensorData seat={self.seat_id} ir=({self.ir_front},{self.ir_back})>'

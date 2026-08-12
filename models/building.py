"""
建筑物/楼层/座位模型 - 支持多场所、多层空间
"""
import os
from datetime import datetime
from . import db


class Building(db.Model):
    """建筑物（图书馆、写字楼、礼堂等）"""
    __tablename__ = 'buildings'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, comment='建筑物名称')
    alias = db.Column(db.String(100), nullable=True, comment='别名/简称')
    region = db.Column(db.String(100), nullable=True, comment='所属区域/城市，如"广州市"、"深圳大学"')
    address = db.Column(db.String(255), nullable=True, comment='地址')
    lat = db.Column(db.Float, nullable=True, comment='纬度')
    lng = db.Column(db.Float, nullable=True, comment='经度')
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    floors = db.relationship('Floor', backref='building', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'alias': self.alias,
            'region': self.region,
            'address': self.address,
            'lat': self.lat,
            'lng': self.lng,
            'description': self.description,
            'is_active': self.is_active,
            'floor_count': self.floors.filter(Floor.is_active == True).count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Building {self.name}>'


class Floor(db.Model):
    """楼层"""
    __tablename__ = 'floors'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=False)
    floor_number = db.Column(db.Integer, nullable=False, comment='楼层号（1,2,3... -1表示地下1层）')
    name = db.Column(db.String(100), nullable=True, comment='楼层名称（如"3楼自习区"）')
    floor_plan_path = db.Column(db.String(255), nullable=True, comment='平面图文件路径')
    floor_plan_width = db.Column(db.Integer, nullable=True, comment='平面图宽度(px)')
    floor_plan_height = db.Column(db.Integer, nullable=True, comment='平面图高度(px)')
    road_network_path = db.Column(db.String(255), nullable=True, comment='路网数据文件路径(JSON)')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    seats = db.relationship('Seat', backref='floor', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'building_id': self.building_id,
            'building_name': self.building.name if self.building else None,
            'floor_number': self.floor_number,
            'name': self.name or f'{self.floor_number}F',
            'floor_plan_path': self.floor_plan_path,
            'floor_plan_url': f'/uploads/{os.path.basename(self.floor_plan_path)}' if self.floor_plan_path else None,
            'floor_plan_width': self.floor_plan_width,
            'floor_plan_height': self.floor_plan_height,
            'road_network_path': self.road_network_path,
            'is_active': self.is_active,
            'seat_count': self.seats.count(),
        }

    def __repr__(self):
        return f'<Floor {self.building_id}-{self.floor_number}F>'


class Seat(db.Model):
    """座位 - 核心模型"""
    __tablename__ = 'seats'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    floor_id = db.Column(db.Integer, db.ForeignKey('floors.id'), nullable=False)
    seat_label = db.Column(db.String(50), nullable=False, comment='座位编号（如"A区-12"）')
    seat_type = db.Column(db.Enum('normal', 'window', 'quiet', 'power', 'disabled'),
                          default='normal', comment='座位类型')
    status = db.Column(db.Enum('free', 'occupied', 'locked', 'error'),
                       default='free', comment='当前状态')

    # 平面图坐标（像素）
    x = db.Column(db.Float, nullable=False, comment='平面图X坐标')
    y = db.Column(db.Float, nullable=False, comment='平面图Y坐标')
    width = db.Column(db.Float, default=30, comment='座位图标宽度')
    height = db.Column(db.Float, default=30, comment='座位图标高度')
    rotation = db.Column(db.Float, default=0, comment='旋转角度')

    # 路网关联
    nearest_node_id = db.Column(db.String(50), nullable=True, comment='最近路网节点ID')

    # 传感器相关
    ir_front = db.Column(db.Integer, default=0, comment='前方红外状态 0/1')
    ir_back = db.Column(db.Integer, default=0, comment='后方红外状态 0/1')
    ir_enabled = db.Column(db.Boolean, default=True, comment='红外传感器是否启用（管理员可关闭）')
    last_scan_time = db.Column(db.DateTime, nullable=True, comment='最后扫描时间')
    consecutive_empty = db.Column(db.Integer, default=0, comment='连续无人扫描次数')
    error_since = db.Column(db.DateTime, nullable=True, comment='设备异常开始时间')

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 当前占用人（可选关联）
    current_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    occupied_since = db.Column(db.DateTime, nullable=True, comment='开始占用时间')
    lock_available_since = db.Column(db.DateTime, nullable=True, comment='锁定按钮可用时间')

    def to_dict(self):
        return {
            'id': self.id,
            'floor_id': self.floor_id,
            'seat_label': self.seat_label,
            'seat_type': self.seat_type,
            'status': self.status,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'rotation': self.rotation,
            'nearest_node_id': self.nearest_node_id,
            'ir_front': self.ir_front,
            'ir_back': self.ir_back,
            'ir_enabled': self.ir_enabled,
            'is_active': self.is_active,
            'current_user_id': self.current_user_id,
        }

    def __repr__(self):
        return f'<Seat {self.seat_label} ({self.status})>'

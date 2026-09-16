"""
学校模型 —— 「学校模式」的顶层归属单位
=====================================

引入学校后：
  * `Building.school_id`  建筑归属某学校
  * `User.school_id`      用户归属某学校
  * 搜索/建筑列表按「当前用户所属学校」过滤，学生只看到本校场所
  * 超级管理员可不带学校（跨校查看）

设计说明
--------
* `student_id` 仍保持全局唯一（按需求：只加学校标签，不改唯一性约束）。
  因此不同学校的相同学号会冲突 —— 批量导入时会把这类行标为「冲突」并
  跳过、写入导入报告，而不是报错或覆盖。
* 学校自身也可带经纬度，便于将来做「跨校/校区」级别的室外导航。
"""
from datetime import datetime

from . import db


class School(db.Model):
    """学校（或校区）"""
    __tablename__ = 'schools'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True, comment='学校名称')
    code = db.Column(db.String(50), nullable=True, unique=True, comment='学校编码/简称（如 SZU）')
    region = db.Column(db.String(100), nullable=True, comment='所属区域/城市')
    address = db.Column(db.String(255), nullable=True, comment='地址')
    lat = db.Column(db.Float, nullable=True, comment='纬度（学校中心点，可选）')
    lng = db.Column(db.Float, nullable=True, comment='经度（学校中心点，可选）')
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    buildings = db.relationship('Building', backref='school', lazy='dynamic')
    users = db.relationship('User', backref='school', lazy='dynamic')

    def to_dict(self, with_stats=False):
        d = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'region': self.region,
            'address': self.address,
            'lat': self.lat,
            'lng': self.lng,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if with_stats:
            d['building_count'] = self.buildings.filter_by(is_active=True).count()
            d['user_count'] = self.users.count()
        return d

    def __repr__(self):
        return f'<School {self.name}>'

"""
用户模型 - 支持学生/管理员角色
"""
from datetime import datetime
from . import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False, comment='学号')
    name = db.Column(db.String(50), nullable=False, comment='姓名')
    role = db.Column(db.Enum('student', 'admin', 'super_admin'), default='student', comment='角色')
    is_approved = db.Column(db.Boolean, default=False, comment='管理员是否已审批通过（仅 admin 角色需要）')
    password_hash = db.Column(db.String(255), nullable=False, default='', comment='密码哈希')
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    avatar_url = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # 偏好设置（JSON存储，含标签等）
    preferences = db.Column(db.JSON, nullable=True, comment='{"window":true,"quiet":true,"tags":["安静","靠窗"]}')

    # 关系
    reservations = db.relationship('Reservation', backref='user', lazy='dynamic')
    lock_records = db.relationship('LockRecord', backref='user', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'name': self.name,
            'role': self.role,
            'phone': self.phone,
            'email': self.email,
            'avatar_url': self.avatar_url,
            'is_active': self.is_active,
            'preferences': self.preferences or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
        }

    def __repr__(self):
        return f'<User {self.student_id} {self.name}>'

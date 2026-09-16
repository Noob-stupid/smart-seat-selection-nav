"""
用户模型 - 支持学生/管理员角色
"""
from datetime import datetime
from . import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False, comment='学号')
    # 学校模式：用户归属某学校；超级管理员可留空以跨校查看
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True,
                          comment='所属学校；NULL=不限（超级管理员）')
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

    # 注册身份的展示文案（与 /login 注册页的四个选项一致）
    USER_TYPE_LABELS = {
        'student': '学生',
        'user': '普通用户',
        'school_admin': '学校管理员',
        'admin': '管理员',
    }

    @property
    def user_type(self):
        """注册时登记的身份；老账号为 None。"""
        try:
            return (self.preferences or {}).get('user_type')
        except Exception:
            return None

    @property
    def role_label(self):
        """角色徽章文案 —— **全站唯一数据源**。

        优先用注册时登记的身份（preferences.user_type）；
        老账号没有登记过，则按 role 回退：
          super_admin -> 超级管理员
          admin       -> 管理员
          student     -> 普通用户（与 profile.html 的历史显示保持一致）
        注意：**不按 school_id 猜身份** —— 学校归属是数据属性，
        不应影响"我注册时选的是什么身份"。
        """
        ut = self.user_type
        if ut in self.USER_TYPE_LABELS:
            return self.USER_TYPE_LABELS[ut]
        if self.role == 'super_admin':
            return '超级管理员'
        if self.role == 'admin':
            return '管理员'
        return '普通用户'

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'school_id': self.school_id,
            'school_name': self.school.name if self.school else None,
            'name': self.name,
            'role': self.role,
            'role_label': self.role_label,
            'user_type': self.user_type,
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

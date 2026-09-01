# -*- coding: utf-8 -*-
"""前后端合并（方案B）集成验证：
同事新增的拍照上传页保留并接入真实 api-client，
其余页面回退为 Flask 原版模板；本测试防止未来回归。
"""
import pytest

from app import db
from models.user import User
from werkzeug.security import generate_password_hash


@pytest.fixture
def admin_client(app, client):
    """管理员登录的测试客户端"""
    with app.app_context():
        user = User(
            student_id='feadmin',
            name='前端集成测试管理员',
            password_hash=generate_password_hash('123456'),
            email='feadmin@test.com',
            role='admin',
            is_approved=True,
        )
        db.session.add(user)
        db.session.commit()
        uid = user.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'admin'
    return client


def test_uploading_page_uses_real_api(admin_client):
    """上传页（同事新版）：必须引用 api-client.js、不得引用 mock-api.js"""
    resp = admin_client.get('/uploading')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'api-client.js' in text, '上传页应引用真实 api-client.js'
    assert 'mock-api.js' not in text, '上传页不得引用 mock-api.js'
    # 应用跳转应指向 Flask 路由
    assert '/admin/floor-plan?floor_id=' in text
    # 不得残留静态站跳转
    assert 'admin-floor-plan.html' not in text


def test_index_page_is_flask_original(admin_client):
    """首页应恢复为 Flask 原版模板（含 base 布局与真实用户信息）"""
    resp = admin_client.get('/')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'api-client.js' in text, '原版 base.html 应引 api-client.js'
    assert 'mock-api.js' not in text
    assert '前端集成测试管理员' in text, '应显示真实登录用户名而非「演示用户」'


def test_login_page_is_flask_original(client):
    """登录页应恢复 Flask 原版"""
    resp = client.get('/login')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'mock-api.js' not in text


def test_admin_floor_plan_page_renders(admin_client):
    """管理端平面图页仍走 Flask 原版模板"""
    resp = admin_client.get('/admin/floor-plan')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'mock-api.js' not in text
    assert 'api-client.js' in text

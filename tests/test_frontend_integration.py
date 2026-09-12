# -*- coding: utf-8 -*-
"""前端集成验证（混合模式契约）

背景
----
仓库里曾出现两种前端方向并行：
  * 一方希望页面走「Flask 原版模板 + 真实 api-client.js」；
  * 另一方把页面改为「纯静态演示 + 浏览器内 mock-api.js」。
两者直接冲突，导致本文件早期版本（断言「不得引用 mock-api.js」）持续失败。

最终采用**混合模式**：
  * 页面一律 **先引 `api-client.js`**（真实后端优先）；
  * `mock-api.js` **允许存在，但必须排在其后**，且仅在
    「请求发生网络层失败」时被 `api-client.js` 当作兜底调用；
  * 后端返回的 4xx/5xx 属真实业务错误，不会被 mock 掩盖。

效果：挂着 Flask 时用真实数据；把页面当纯静态打开（file:// 或静态服务器）
时自动回退到演示数据，离线演示仍然可用。

本测试守护上述契约，防止任一方再次单方面改回单一模式。
"""
import pytest

from app import db
from models.user import User
from werkzeug.security import generate_password_hash


def _assert_real_api_first(text, page_name):
    """断言：必须引真实 api-client.js；若引了 mock，则必须排在其后（兜底而非覆盖）"""
    assert 'api-client.js' in text, f'{page_name}应优先引用真实 api-client.js'
    if 'mock-api.js' in text:
        assert text.index('api-client.js') < text.index('mock-api.js'), (
            f'{page_name}中 mock-api.js 必须排在 api-client.js 之后，'
            '否则会覆盖真实后端，退化成纯静态演示'
        )


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
    """上传页：真实 api-client 优先，mock 仅兜底；跳转指向 Flask 路由"""
    resp = admin_client.get('/uploading')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    _assert_real_api_first(text, '上传页')
    # 应用跳转应指向 Flask 路由
    assert '/admin/floor-plan?floor_id=' in text
    # 不得残留静态站跳转
    assert 'admin-floor-plan.html' not in text


def test_index_page_uses_real_api_first(admin_client):
    """首页：真实 api-client 优先（mock 只能兜底）"""
    resp = admin_client.get('/')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    _assert_real_api_first(text, '首页')


def test_login_page_uses_real_api_first(client):
    """登录页：真实 api-client 优先"""
    resp = client.get('/login')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    _assert_real_api_first(text, '登录页')


def test_admin_floor_plan_page_renders(admin_client):
    """管理端平面图页：由 Flask 正常渲染，且真实 api-client 优先"""
    resp = admin_client.get('/admin/floor-plan')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    _assert_real_api_first(text, '平面图页')


def test_ai_pages_present_and_use_real_backend(admin_client):
    """AI 相关页面必须随合并保留，且走真实后端（AI 依赖 Flask 接口）"""
    resp = admin_client.get('/admin/ai')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'api-client.js' in text, 'AI 运营中心需走真实后端接口'
    assert 'admin/ai.js' in text
    assert 'mock-api.js' not in text, 'AI 接口没有 mock 实现，引用 mock 会导致功能失效'

    t = admin_client.get('/terminal').get_data(as_text=True)
    assert 'api/terminal/data' in t, '智能终端应轮询真实终端接口'


def test_ai_assistant_loaded_on_user_pages(admin_client):
    """全站 AI 助手浮窗应挂在主要用户页面上"""
    for path in ('/', '/seat-map'):
        text = admin_client.get(path).get_data(as_text=True)
        assert 'ai-assistant.js' in text, f'{path} 缺少 AI 助手浮窗'


def test_mock_api_is_fallback_not_override():
    """静态契约：mock-api.js 不得无条件覆盖 window.axios。

    它必须先挂到 window.__mockAxios，只有在 api-client.js 未声明
    __REAL_API_AVAILABLE 时才接管 window.axios。
    """
    import io
    import os
    root = os.path.join(os.path.dirname(__file__), '..')
    mock = io.open(os.path.join(root, 'static', 'js', 'mock-api.js'),
                   encoding='utf-8').read()
    assert 'window.__mockAxios' in mock
    assert '__REAL_API_AVAILABLE' in mock, '应根据真实后端是否可用决定是否接管'

    client = io.open(os.path.join(root, 'static', 'js', 'api-client.js'),
                     encoding='utf-8').read()
    assert '__REAL_API_AVAILABLE' in client, 'api-client.js 应声明真实 API 可用'
    assert '__mockAxios' in client, 'api-client.js 应在网络失败时回退到 mock'

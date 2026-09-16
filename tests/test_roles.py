# -*- coding: utf-8 -*-
"""角色区分与权限收口测试。

覆盖用户反馈的三个问题：
  1. 普通用户/学生/管理员/超管要区分开（前端按服务端身份渲染）
  2. 非管理员不得看到「管理」入口；非学校管理员不得看到「导入学生」入口
  3. 个人中心必须显示真实登录用户（而不是静态演示的「演示用户」）
"""
import io
import os

import pytest

from app import db
from models.school import School
from models.user import User
from werkzeug.security import generate_password_hash


def _school(app, name):
    with app.app_context():
        sc = School(name=name)
        db.session.add(sc)
        db.session.commit()
        return sc.id


def _user(app, sid, role='student', school_id=None, name=None):
    with app.app_context():
        u = User(student_id=sid, name=name or sid, role=role,
                 school_id=school_id, is_approved=True,
                 password_hash=generate_password_hash(sid))
        db.session.add(u)
        db.session.commit()
        return u.id


def _login(client, app, sid, role, school_id=None):
    uid = _user(app, sid, role, school_id)
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = role
        sess['name'] = sid
    return client


# ================================================================ 导入学生权限
class TestImportPermission:
    """「导入学生」只属于学校管理员（用户明确要求）。"""

    ENDPOINTS = [
        ('get', '/api/admin/students'),
        ('get', '/api/admin/students/import/template'),
    ]

    def test_plain_admin_without_school_forbidden(self, client, app):
        """非学校管理员不应有导入学生功能"""
        _login(client, app, 'plainadm', 'admin', school_id=None)
        for method, url in self.ENDPOINTS:
            r = getattr(client, method)(url)
            assert r.status_code == 403, '%s 应对非学校管理员返回 403' % url
            assert '学校' in r.get_json()['message']

    def test_plain_admin_import_upload_forbidden(self, client, app):
        _login(client, app, 'plainadm2', 'admin', school_id=None)
        r = client.post('/api/admin/students/import',
                        data={'file': (io.BytesIO(b'x'), 'a.csv')},
                        content_type='multipart/form-data')
        assert r.status_code == 403

    def test_school_admin_allowed(self, client, app):
        sid = _school(app, '权限大学')
        _login(client, app, 'schadm', 'admin', school_id=sid)
        assert client.get('/api/admin/students').status_code == 200
        assert client.get('/api/admin/students/import/template').status_code == 200

    def test_student_forbidden(self, client, app):
        sid = _school(app, '权限大学')
        _login(client, app, 'stu1', 'student', school_id=sid)
        assert client.get('/api/admin/students').status_code == 403
        assert client.get('/api/admin/students/import/template').status_code == 403

    def test_anonymous_forbidden(self, client, app):
        assert client.get('/api/admin/students').status_code in (401, 403)

    def test_super_admin_allowed(self, client, app):
        """超管放行（需在导入时显式指定学校）"""
        _login(client, app, 'root', 'super_admin', school_id=None)
        assert client.get('/api/admin/students').status_code == 200


# ================================================================ 前端角色契约
class TestShellNavContract:
    """shell-nav.js 必须以服务端身份为准，并且默认保守。"""

    def _src(self):
        root = os.path.join(os.path.dirname(__file__), '..')
        return io.open(os.path.join(root, 'static', 'js', 'shell-nav.js'),
                       encoding='utf-8').read()

    def test_reads_identity_from_server(self):
        src = self._src()
        assert '/api/auth/me' in src, '应从服务端取真实身份，而不是只读 localStorage'

    def test_defaults_to_non_admin(self):
        """读不到身份时必须默认非管理员（fail-safe），不能默认 admin"""
        src = self._src()
        assert "role = null" in src, '未知身份时应把 role 置空'
        # 不允许再出现「读不到就当管理员」的旧写法
        assert "(u && u.role) || 'admin'" not in src

    def test_hides_admin_nav_for_non_admin(self):
        src = self._src()
        assert 'data-nav="admin"' in src
        assert 'setDisplay' in src

    def test_supports_school_scoped_entries(self):
        """需要学校身份的入口（导入学生）要能被隐藏"""
        src = self._src()
        assert 'data-requires-school' in src
        assert 'hasSchool' in src

    def test_role_labels_match_app_wording(self):
        """角色文案必须与 profile.html / login.html 一致（普通用户，而非"学生"）"""
        import re
        src = self._src()
        m = re.search(r'ROLE_LABEL\s*=\s*\{([^}]*)\}', src)
        assert m, '应存在 ROLE_LABEL 映射'
        block = m.group(1)
        assert "student: '普通用户'" in block, 'student 的文案应与 profile.html 一致'
        assert "admin: '管理员'" in block
        assert "super_admin: '超级管理员'" in block
        # 不允许把 student 擅自改叫「学生」
        assert "student: '学生'" not in block

    def test_avatar_restored(self):
        """旧版 base.html 会渲染 <img class="avatar">，静态版丢了 —— 必须补回"""
        src = self._src()
        assert 'avatar_url' in src, '应从 /api/auth/me 取头像地址'
        assert 'applyAvatar' in src, '应存在头像应用逻辑'
        assert "createElement('img')" in src, '应补出 <img> 节点'

    def test_anonymous_shows_login_button(self):
        """旧版未登录时显示「登录」按钮，而不是把用户区留空"""
        src = self._src()
        assert 'applyAnonymous' in src
        assert '登录' in src
        assert "'/login'" in src

    def test_is_additive_not_destructive(self):
        """只叠加不修改：不得删除模板原有节点"""
        src = self._src()
        # 允许 remove 自己注入的节点，但不能删模板里的 .user-info-link 等
        assert "removeChild" not in src or 'injected' in src
        assert ".user-info-link'" not in src.replace("setDisplay('.user-info-link'", '')

    def test_static_demo_still_works(self):
        """纯静态演示（无后端）仍要保留原行为，不能白屏"""
        src = self._src()
        assert '__REAL_API_AVAILABLE' in src
        assert '演示用户' in src

    def test_logout_clears_server_session(self):
        """真实模式下退出必须清服务端 session"""
        src = self._src()
        assert "'/logout'" in src


class TestPageRoleMarkers:
    def test_dashboard_student_entry_requires_school(self, client, app):
        sid = _school(app, '标记大学')
        _login(client, app, 'mkadm', 'admin', school_id=sid)
        html = client.get('/admin/dashboard.html').get_data(as_text=True)
        assert 'data-requires-school' in html, '导入学生入口需可被隐藏'

    def test_pages_have_role_slots(self, client, app):
        sid = _school(app, '标记大学')
        _login(client, app, 'mkstu', 'student', school_id=sid)
        for path in ('/', '/profile', '/seat-map'):
            html = client.get(path).get_data(as_text=True)
            assert 'data-user-name' in html, '%s 缺少用户名占位' % path
            assert 'data-user-role' in html, '%s 缺少角色占位' % path

    def test_profile_link_kept_relative_for_static_mode(self, client, app):
        """个人中心链接保持相对写法（协作者静态演示依赖它，不得改成绝对路径）"""
        sid = _school(app, '标记大学')
        _login(client, app, 'mkstu2', 'student', school_id=sid)
        html = client.get('/profile').get_data(as_text=True)
        assert 'href="profile.html"' in html, '模板应保留相对链接以兼容静态演示'
        assert 'href="/profile"' not in html, '不应改成绝对路径（会破坏 file:// 模式）'

    def test_static_style_links_resolve_under_flask(self, client, app):
        """相对链接在 Flask 下必须能用 —— 由路由别名兜住，而不是改模板"""
        sid = _school(app, '标记大学')
        _login(client, app, 'mkstu3', 'student', school_id=sid)
        for path in ('/profile.html', '/index.html', '/seat_map.html',
                     '/admin/dashboard.html', '/admin/students.html'):
            assert client.get(path).status_code == 200, '%s 应可由别名路由打开' % path

    def test_alias_route_rejects_traversal(self, client, app):
        """别名路由不能变成任意模板读取（防目录穿越）"""
        sid = _school(app, '标记大学')
        _login(client, app, 'mkstu4', 'student', school_id=sid)
        for bad in ('/..%2f..%2fconfig.html', '/nope.html', '/admin/nope.html'):
            assert client.get(bad).status_code == 404


class TestProfileShowsRealUser:
    def test_auth_me_returns_real_identity(self, client, app):
        sid = _school(app, '主页大学')
        _login(client, app, 'realuser', 'student', school_id=sid)
        with app.app_context():
            u = User.query.filter_by(student_id='realuser').first()
            u.name = '真实姓名'
            db.session.commit()
        d = client.get('/api/auth/me').get_json()['data']
        assert d['name'] == '真实姓名'
        assert d['role'] == 'student'
        assert d['school_id'] == sid

    def test_auth_me_401_when_anonymous(self, client):
        assert client.get('/api/auth/me').status_code == 401

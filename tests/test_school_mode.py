# -*- coding: utf-8 -*-
"""学校模式（P1）测试：学校 CRUD、注册选校、跨校隔离。"""
import pytest

from app import db
from models.building import Building, Floor, Seat
from models.school import School
from models.user import User
from werkzeug.security import generate_password_hash


def _school(app, name, code=None):
    with app.app_context():
        sc = School(name=name, code=code)
        db.session.add(sc)
        db.session.commit()
        return sc.id


def _building(app, name, school_id=None):
    with app.app_context():
        b = Building(name=name, school_id=school_id)
        db.session.add(b)
        db.session.commit()
        return b.id


def _login(client, app, sid, school_id, role='student', name='用户'):
    with app.app_context():
        u = User(student_id=sid, name=name, role=role, school_id=school_id,
                 is_approved=True,
                 password_hash=generate_password_hash('123456'))
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = role
        sess['name'] = name
    return client


# ================================================================ 学校 CRUD
class TestSchoolCRUD:
    def test_public_list_for_register_page(self, client, app):
        """注册页需要学校下拉：未登录也应能读列表"""
        _school(app, '甲大学')
        r = client.get('/api/schools')
        assert r.status_code == 200
        names = [x['name'] for x in r.get_json()['data']]
        assert '甲大学' in names

    def test_create_requires_admin(self, client, app):
        assert client.post('/api/schools', json={'name': '乙大学'}).status_code in (401, 403)

    def test_admin_can_create_and_update(self, client, app):
        _login(client, app, 'sa1', None, role='admin', name='管理员')
        r = client.post('/api/schools', json={'name': '乙大学', 'code': 'BJU',
                                              'region': '北京'})
        assert r.status_code == 200, r.get_json()
        sid = r.get_json()['data']['id']

        r2 = client.put(f'/api/schools/{sid}', json={'region': '北京市海淀区'})
        assert r2.status_code == 200
        assert r2.get_json()['data']['region'] == '北京市海淀区'

    def test_duplicate_name_rejected(self, client, app):
        _school(app, '丙大学')
        _login(client, app, 'sa2', None, role='admin')
        r = client.post('/api/schools', json={'name': '丙大学'})
        assert r.status_code == 400

    def test_delete_is_soft(self, client, app):
        sid = _school(app, '丁大学')
        _login(client, app, 'sa3', None, role='admin')
        assert client.delete(f'/api/schools/{sid}').status_code == 200
        with app.app_context():
            assert db.session.get(School, sid).is_active is False
            assert db.session.get(School, sid) is not None   # 数据保留


# ================================================================ 注册选校
class TestRegisterWithSchool:
    def test_register_saves_school(self, client, app):
        sid = _school(app, '戊大学')
        r = client.post('/api/auth/register', json={
            'student_id': 'stu001', 'name': '小明', 'password': 'pass123',
            'confirm_password': 'pass123', 'school_id': sid,
        })
        assert r.status_code == 201
        assert r.get_json()['data']['school_name'] == '戊大学'
        with app.app_context():
            assert User.query.filter_by(student_id='stu001').first().school_id == sid

    def test_register_without_school_rejected(self, client, app):
        r = client.post('/api/auth/register', json={
            'student_id': 'stu002', 'name': '无校', 'password': 'pass123',
            'confirm_password': 'pass123',
        })
        assert r.status_code == 400

    def test_register_with_inactive_school_rejected(self, client, app):
        sid = _school(app, '已停用大学')
        with app.app_context():
            db.session.get(School, sid).is_active = False
            db.session.commit()
        r = client.post('/api/auth/register', json={
            'student_id': 'stu003', 'name': '停用', 'password': 'pass123',
            'confirm_password': 'pass123', 'school_id': sid,
        })
        assert r.status_code == 400


# ================================================================ 跨校隔离
class TestSchoolIsolation:
    def test_student_only_sees_own_school_buildings(self, client, app):
        a = _school(app, 'A大学')
        b = _school(app, 'B大学')
        _building(app, 'A图书馆', a)
        _building(app, 'B图书馆', b)

        _login(client, app, 'a001', a)
        names = [x['name'] for x in client.get('/api/buildings').get_json()['data']]
        assert 'A图书馆' in names
        assert 'B图书馆' not in names, '学生不应看到其他学校的建筑'

    def test_student_search_scoped_to_school(self, client, app):
        a = _school(app, 'A大学')
        b = _school(app, 'B大学')
        _building(app, '中心图书馆A', a)
        _building(app, '中心图书馆B', b)

        _login(client, app, 'a002', a)
        res = client.get('/api/search/venues?q=图书馆').get_json()['data']
        names = [x['name'] for x in res]
        assert '中心图书馆A' in names
        assert '中心图书馆B' not in names, '搜索不应跨校'

    def test_super_admin_sees_all_schools(self, client, app):
        """需求 5B：超级管理员可跨校查看"""
        a = _school(app, 'A大学')
        b = _school(app, 'B大学')
        _building(app, 'A图书馆', a)
        _building(app, 'B图书馆', b)

        _login(client, app, 'root1', None, role='super_admin', name='超管')
        names = [x['name'] for x in client.get('/api/buildings').get_json()['data']]
        assert 'A图书馆' in names and 'B图书馆' in names

    def test_anonymous_sees_all(self, client, app):
        """未登录（如首页公开浏览）不受学校过滤"""
        a = _school(app, 'A大学')
        _building(app, '未登录可看', a)
        names = [x['name'] for x in client.get('/api/buildings').get_json()['data']]
        assert '未登录可看' in names

    def test_building_dict_exposes_school(self, client, app):
        sid = _school(app, '己大学')
        _building(app, '己图书馆', sid)
        _login(client, app, 'a003', sid)
        data = client.get('/api/buildings').get_json()['data']
        b = [x for x in data if x['name'] == '己图书馆'][0]
        assert b['school_id'] == sid
        assert b['school_name'] == '己大学'

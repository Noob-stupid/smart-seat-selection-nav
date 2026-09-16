# -*- coding: utf-8 -*-
"""P4 室外导航测试：地图配置下发 + 目的地列表 + 页面。"""
import pytest

from app import db
from models.building import Building
from models.school import School
from models.user import User
from werkzeug.security import generate_password_hash


def _school(app, name):
    with app.app_context():
        sc = School(name=name)
        db.session.add(sc)
        db.session.commit()
        return sc.id


def _building(app, name, school_id, lat=None, lng=None):
    with app.app_context():
        b = Building(name=name, school_id=school_id, lat=lat, lng=lng)
        db.session.add(b)
        db.session.commit()
        return b.id


def _login(client, app, sid, school_id, role='student'):
    with app.app_context():
        u = User(student_id=sid, name='导航用户', role=role, school_id=school_id,
                 is_approved=True, password_hash=generate_password_hash('123456'))
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = role
        sess['name'] = '导航用户'
    return client


class TestNavConfig:
    def test_default_provider_is_amap(self, client, app):
        d = client.get('/api/nav/config').get_json()['data']
        assert d['provider'] == 'amap'

    def test_key_not_exposed_to_anonymous(self, client, app):
        """匿名请求不应下发地图 key（避免配额被抓取滥用）"""
        from config import Config
        old = Config.NAV_MAP_KEY
        Config.NAV_MAP_KEY = 'secretkey123456'
        try:
            d = client.get('/api/nav/config').get_json()['data']
            assert d['logged_in'] is False
            assert d['key'] == '', '未登录不应下发 key'
            assert d['has_key'] is False
        finally:
            Config.NAV_MAP_KEY = old

    def test_key_delivered_after_login(self, client, app):
        from config import Config
        a = _school(app, '导航大学')
        _login(client, app, 'navu1', a)
        old = Config.NAV_MAP_KEY
        Config.NAV_MAP_KEY = 'k' * 32
        try:
            d = client.get('/api/nav/config').get_json()['data']
            assert d['logged_in'] is True
            assert d['has_key'] is True
            assert d['key'] == 'k' * 32
        finally:
            Config.NAV_MAP_KEY = old

    def test_fallback_flag_exposed(self, client, app):
        d = client.get('/api/nav/config').get_json()['data']
        assert 'fallback_enabled' in d


class TestNavDestinations:
    def test_only_buildings_with_coords(self, client, app):
        a = _school(app, '导航大学')
        _building(app, '有坐标楼', a, 22.5431, 114.0579)
        _building(app, '无坐标楼', a)
        _login(client, app, 'navu2', a)
        d = client.get('/api/nav/destinations').get_json()['data']
        names = [x['name'] for x in d['destinations']]
        assert '有坐标楼' in names
        assert '无坐标楼' not in names, '没坐标的建筑无法室外导航，不应返回'
        assert d['missing_coords'] == 1
        assert d['total_buildings'] == 2

    def test_scoped_by_school(self, client, app):
        a = _school(app, 'A导航大学')
        b = _school(app, 'B导航大学')
        _building(app, 'A楼', a, 22.5, 114.0)
        _building(app, 'B楼', b, 23.5, 115.0)
        _login(client, app, 'navu3', a)
        d = client.get('/api/nav/destinations').get_json()['data']
        names = [x['name'] for x in d['destinations']]
        assert 'A楼' in names
        assert 'B楼' not in names, '目的地列表不应跨校'

    def test_super_admin_sees_all(self, client, app):
        a = _school(app, 'A导航大学')
        b = _school(app, 'B导航大学')
        _building(app, 'A楼', a, 22.5, 114.0)
        _building(app, 'B楼', b, 23.5, 115.0)
        _login(client, app, 'navroot', None, role='super_admin')
        names = [x['name'] for x in client.get('/api/nav/destinations').get_json()['data']['destinations']]
        assert 'A楼' in names and 'B楼' in names

    def test_payload_has_coords(self, client, app):
        a = _school(app, '导航大学')
        _building(app, '坐标楼', a, 22.543100, 114.057900)
        _login(client, app, 'navu4', a)
        x = client.get('/api/nav/destinations').get_json()['data']['destinations'][0]
        assert abs(x['lat'] - 22.5431) < 1e-6
        assert abs(x['lng'] - 114.0579) < 1e-6
        assert 'school_name' in x


class TestOutdoorPage:
    def test_page_renders(self, client):
        r = client.get('/outdoor')
        assert r.status_code == 200
        html = r.data.decode('utf-8', 'ignore')
        assert 'id="navMap"' in html, '应包含地图容器'
        assert 'id="compass"' in html, '应包含方位导航兜底视图'
        assert 'outdoor.js' in html

    def test_page_references_both_nav_views(self, client):
        """页面必须同时具备地图与兜底两套视图（降级不白屏）"""
        html = client.get('/outdoor').get_data(as_text=True)
        assert "navMode === 'map'" in html
        assert "navMode === 'fallback'" in html

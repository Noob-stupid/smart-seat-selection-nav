# -*- coding: utf-8 -*-
"""删除平面图功能测试（DELETE /api/floors/<id>/plan）。"""
import io
import os

import pytest

from app import app as flask_app, db
from config import Config
from models.building import Building, Floor, Seat
from models.school import School
from models.user import User
from werkzeug.security import generate_password_hash


def _school(app, name):
    with app.app_context():
        sc = School(name=name)
        db.session.add(sc)
        db.session.commit()
        return sc.id


def _floor(app, school_id, label='P-1', with_plan=True):
    """建楼/层，可选地造一个真实的平面图文件。"""
    with app.app_context():
        b = Building(name='删除测试楼%s' % (school_id or 0), school_id=school_id)
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, name='1F')
        db.session.add(f)
        db.session.flush()
        db.session.add(Seat(floor_id=f.id, seat_label=label, x=1, y=1))
        disk = None
        if with_plan:
            sub = 'school_%d' % school_id if school_id else 'shared'
            d = os.path.join(Config.UPLOAD_FOLDER, sub)
            os.makedirs(d, exist_ok=True)
            disk = os.path.join(d, 'unittest_plan_%d.png' % f.id)
            with open(disk, 'wb') as fh:
                fh.write(b'\x89PNG\r\n\x1a\n' + b'0' * 40)
            f.floor_plan_path = disk
            f.floor_plan_width = 400
            f.floor_plan_height = 300
        db.session.commit()
        return b.id, f.id, disk


def _login(client, app, sid, school_id, role='admin'):
    with app.app_context():
        u = User(student_id=sid, name=sid, role=role, school_id=school_id,
                 is_approved=True, password_hash=generate_password_hash('123456'))
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = role
        sess['name'] = sid
    return client


class TestDeleteFloorPlan:
    def test_requires_admin(self, client, app):
        a = _school(app, '删图大学')
        _, fid, _ = _floor(app, a)
        assert client.delete('/api/floors/%d/plan' % fid).status_code in (401, 403)

    def test_deletes_file_and_clears_fields(self, client, app):
        a = _school(app, '删图大学')
        _, fid, disk = _floor(app, a)
        assert disk and os.path.exists(disk)
        _login(client, app, 'd1', a)

        r = client.delete('/api/floors/%d/plan' % fid)
        assert r.status_code == 200, r.get_json()
        d = r.get_json()['data']
        assert d['removed_files'], '应报告删掉的文件'

        with app.app_context():
            f = db.session.get(Floor, fid)
            assert f.floor_plan_path is None
            assert f.floor_plan_width is None
            assert f.floor_plan_height is None
            assert f.road_network_path is None
        assert not os.path.exists(disk), '磁盘文件应被删除'

    def test_keeps_floor_and_seats(self, client, app):
        """只删平面图，楼层与座位要保留"""
        a = _school(app, '删图大学')
        _, fid, _ = _floor(app, a)
        _login(client, app, 'd2', a)
        client.delete('/api/floors/%d/plan' % fid)
        with app.app_context():
            f = db.session.get(Floor, fid)
            assert f is not None, '楼层应保留'
            assert f.seats.count() == 1, '座位应保留'

    def test_url_becomes_null_after_delete(self, client, app):
        a = _school(app, '删图大学')
        _, fid, _ = _floor(app, a)
        _login(client, app, 'd3', a)
        before = client.get('/api/floors/%d' % fid).get_json()['data']
        assert before['floor_plan_url'] is not None
        client.delete('/api/floors/%d/plan' % fid)
        after = client.get('/api/floors/%d' % fid).get_json()['data']
        assert after['floor_plan_url'] is None

    def test_idempotent_when_no_plan(self, client, app):
        a = _school(app, '删图大学')
        _, fid, _ = _floor(app, a, with_plan=False)
        _login(client, app, 'd4', a)
        r = client.delete('/api/floors/%d/plan' % fid)
        assert r.status_code == 200
        assert '本来就没有' in r.get_json()['message']

    def test_cannot_delete_other_school_plan(self, client, app):
        """A 校管理员不能删 B 校的平面图"""
        a = _school(app, '删图A大学')
        b = _school(app, '删图B大学')
        _, fid, disk = _floor(app, b)
        _login(client, app, 'd5', a)
        r = client.delete('/api/floors/%d/plan' % fid)
        assert r.status_code == 403
        assert os.path.exists(disk), 'B 校文件不应被删'
        with app.app_context():
            assert db.session.get(Floor, fid).floor_plan_path is not None

    def test_super_admin_can_delete_any(self, client, app):
        b = _school(app, '删图B大学')
        _, fid, _ = _floor(app, b)
        _login(client, app, 'root', None, role='super_admin')
        assert client.delete('/api/floors/%d/plan' % fid).status_code == 200

    def test_missing_floor_404(self, client, app):
        a = _school(app, '删图大学')
        _login(client, app, 'd6', a)
        assert client.delete('/api/floors/999999/plan').status_code == 404

    def test_traversal_path_not_deleted(self, client, app):
        """数据库里若是越界路径（../），绝不能删到 uploads 之外的文件"""
        a = _school(app, '删图大学')
        _, fid, _ = _floor(app, a, with_plan=False)
        # 造一个 uploads 外的"诱饵"文件
        bait = os.path.join(Config.UPLOAD_FOLDER, '..', 'unittest_bait.txt')
        with open(bait, 'wb') as fh:
            fh.write(b'bait')
        with app.app_context():
            f = db.session.get(Floor, fid)
            f.floor_plan_path = bait
            db.session.commit()
        try:
            _login(client, app, 'd7', a)
            r = client.delete('/api/floors/%d/plan' % fid)
            assert r.status_code == 200
            assert os.path.exists(bait), 'uploads 之外的文件不应被删除'
        finally:
            if os.path.exists(bait):
                os.remove(bait)

    def test_removes_road_network_too(self, client, app):
        """平面图删了，由它生成的路网也要清（坐标会错位）"""
        a = _school(app, '删图大学')
        _, fid, _ = _floor(app, a)
        net = os.path.join('data', 'networks', 'unittest_net_%d.json' % fid)
        with open(net, 'w', encoding='utf-8') as fh:
            fh.write('{"nodes":[],"edges":[]}')
        with app.app_context():
            f = db.session.get(Floor, fid)
            f.road_network_path = net
            db.session.commit()
        try:
            _login(client, app, 'd8', a)
            r = client.delete('/api/floors/%d/plan' % fid)
            assert r.status_code == 200
            with app.app_context():
                assert db.session.get(Floor, fid).road_network_path is None
            assert not os.path.exists(net), '路网文件也应被删除'
        finally:
            if os.path.exists(net):
                os.remove(net)

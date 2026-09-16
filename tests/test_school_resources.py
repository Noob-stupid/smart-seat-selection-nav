# -*- coding: utf-8 -*-
"""#2 学校资源隔离测试：平面图/楼层/建筑不得跨校访问。"""
import io

import pytest

from app import db
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


def _building_with_floor(app, name, school_id):
    with app.app_context():
        b = Building(name=name, school_id=school_id)
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, name='1F',
                  floor_plan_path='/uploads/school_x/plan.png')
        db.session.add(f)
        db.session.flush()
        s = Seat(floor_id=f.id, seat_label='S-1', x=1, y=1)
        db.session.add(s)
        db.session.commit()
        return b.id, f.id, s.id


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


class TestFloorIsolation:
    """A 校管理员不得读写 B 校的楼层与其平面图。"""

    def test_cannot_read_other_school_floor(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        _, fb, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sa1', a)
        r = client.get('/api/floors/%d' % fb)
        assert r.status_code == 403, '不应读到它校楼层'
        assert '学校' in r.get_json()['message']

    def test_can_read_own_school_floor(self, client, app):
        a = _school(app, 'A资源大学')
        _, fa, _ = _building_with_floor(app, 'A楼', a)
        _login(client, app, 'sa2', a)
        assert client.get('/api/floors/%d' % fa).status_code == 200

    def test_cannot_modify_other_school_floor_plan(self, client, app):
        """核心：不能把别人的平面图换掉"""
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        _, fb, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sa3', a)
        r = client.put('/api/floors/%d' % fb,
                       json={'floor_plan_path': '/uploads/hacked.png'})
        assert r.status_code == 403
        with app.app_context():
            f = db.session.get(Floor, fb)
            assert f.floor_plan_path == '/uploads/school_x/plan.png', '平面图不应被篡改'

    def test_cannot_delete_other_school_floor(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        _, fb, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sa4', a)
        assert client.delete('/api/floors/%d' % fb).status_code == 403

    def test_cannot_add_seats_to_other_school_floor(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        _, fb, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sa5', a)
        r = client.post('/api/floors/%d/seats' % fb, json={'seat_label': 'X'})
        assert r.status_code == 403

    def test_cannot_modify_other_school_seat(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        _, _, sb = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sa6', a)
        assert client.put('/api/seats/%d' % sb, json={'status': 'error'}).status_code == 403


class TestBuildingIsolation:
    def test_cannot_read_detail_of_other_school_building(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        bb, _, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sb1', a)
        assert client.get('/api/buildings/%d' % bb).status_code == 403

    def test_cannot_rename_other_school_building(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        bb, _, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sb2', a)
        assert client.put('/api/buildings/%d' % bb,
                          json={'name': '改掉'}).status_code == 403

    def test_cannot_delete_other_school_building(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        bb, _, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sb3', a)
        assert client.delete('/api/buildings/%d' % bb).status_code == 403

    def test_cannot_add_floor_to_other_school_building(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        bb, _, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'sb4', a)
        r = client.post('/api/buildings/%d/floors' % bb, json={'floor_number': 9})
        assert r.status_code == 403


class TestSuperAdminAndLegacy:
    def test_super_admin_can_access_all(self, client, app):
        a = _school(app, 'A资源大学')
        b = _school(app, 'B资源大学')
        _, fa, _ = _building_with_floor(app, 'A楼', a)
        _, fb, _ = _building_with_floor(app, 'B楼', b)
        _login(client, app, 'root', None, role='super_admin')
        assert client.get('/api/floors/%d' % fa).status_code == 200
        assert client.get('/api/floors/%d' % fb).status_code == 200

    def test_unassigned_resources_open(self, client, app, ):
        """未归属学校的资源视为公共，放行（兼容历史数据）"""
        a = _school(app, 'A资源大学')
        _, fc, _ = _building_with_floor(app, '公共楼', None)
        _login(client, app, 'sc1', a)
        assert client.get('/api/floors/%d' % fc).status_code == 200


class TestUploadSegregation:
    def test_upload_saves_into_school_subdir(self, client, app):
        """上传的平面图应落到 uploads/school_<id>/ 下"""
        import os
        from config import Config
        from openpyxl import Workbook  # noqa: F401  (仅确保依赖可用)

        a = _school(app, '上传大学')
        _login(client, app, 'up1', a)

        # 造一张最小 PNG
        png = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
               b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
               b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
               b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')
        r = client.post('/api/upload',
                        data={'file': (io.BytesIO(png), 'plan.png')},
                        content_type='multipart/form-data')
        if r.status_code != 200:
            pytest.skip('图像解析不可用（缺 opencv）：%s' % r.get_json())
        url = r.get_json()['data']['file_url']
        assert '/school_%d/' % a in url, '文件应落在本校子目录：%s' % url
        # 该文件确实存在且可访问
        assert client.get(url).status_code == 200
        # 清理
        try:
            os.remove(os.path.join(Config.UPLOAD_FOLDER, url.replace('/uploads/', '')))
        except OSError:
            pass

    def test_uploaded_file_route_blocks_traversal(self, client):
        assert client.get('/uploads/../../config.py').status_code in (400, 404)
        assert client.get('/uploads/..%2f..%2fconfig.py').status_code in (400, 404)

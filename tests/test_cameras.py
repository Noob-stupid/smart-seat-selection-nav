# -*- coding: utf-8 -*-
"""摄像头点位接口测试（原先这些接口根本不存在，页面永远空白）。"""
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


def _floor_with_seats(app, school_id, labels, status='free'):
    """按给定座位编号建楼/层/座位，坐标排成一行便于断言。"""
    with app.app_context():
        b = Building(name='监控楼%s' % school_id, school_id=school_id)
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, name='1F')
        db.session.add(f)
        db.session.flush()
        for i, lb in enumerate(labels):
            db.session.add(Seat(floor_id=f.id, seat_label=lb, x=100 + i * 100,
                                y=300, status=status))
        db.session.commit()
        return b.id, f.id


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


class TestCameraZones:
    def test_requires_admin(self, client, app):
        a = _school(app, '监控大学')
        _floor_with_seats(app, a, ['A-1'])
        _login(client, app, 'stu', a, role='student')
        assert client.get('/api/admin/cameras/zones').status_code in (401, 403)

    def test_derives_zones_from_seat_labels(self, client, app):
        """座位 A-1..A-3 -> 一个 A 区点位；B-1 -> 一个 B 区点位"""
        a = _school(app, '监控大学')
        _floor_with_seats(app, a, ['A-1', 'A-2', 'A-3', 'B-1'])
        _login(client, app, 'ad1', a)
        d = client.get('/api/admin/cameras/zones').get_json()['data']
        zones = {c['zone'] for c in d['cameras']}
        assert 'A 区' in zones and 'B 区' in zones

    def test_zone_name_strips_separator(self, client, app):
        """A-1 的区名应为 A 区，而不是 A- 区"""
        a = _school(app, '监控大学')
        _floor_with_seats(app, a, ['A-1', 'A-2'])
        _login(client, app, 'ad2', a)
        d = client.get('/api/admin/cameras/zones').get_json()['data']
        assert d['cameras'][0]['zone'] == 'A 区'

    def test_camera_covers_zone_seats(self, client, app):
        a = _school(app, '监控大学')
        _floor_with_seats(app, a, ['A-1', 'A-2', 'A-3'])
        _login(client, app, 'ad3', a)
        cam = client.get('/api/admin/cameras/zones').get_json()['data']['cameras'][0]
        assert cam['seat_count'] == 3
        assert len(cam['seats']) == 3
        assert cam['seat_range'] == 'A-1 ~ A-3'
        # 必备字段（前端渲染依赖）
        for k in ('id', 'name', 'status', 'status_text', 'building_name',
                  'floor_name', 'occupied', 'x', 'y', 'fov_points',
                  'resolution', 'protocol', 'ptz', 'ir'):
            assert k in cam, '缺少字段 %s' % k
        assert cam['fov_points'], '视野扇形不能为空'

    def test_occupied_count_from_seat_status(self, client, app):
        a = _school(app, '监控大学')
        bid, fid = _floor_with_seats(app, a, ['A-1', 'A-2'], status='free')
        with app.app_context():
            s = Seat.query.filter_by(floor_id=fid, seat_label='A-1').first()
            s.status = 'occupied'
            db.session.commit()
        _login(client, app, 'ad4', a)
        cam = client.get('/api/admin/cameras/zones').get_json()['data']['cameras'][0]
        assert cam['occupied'] == 1

    def test_summary_counts(self, client, app):
        a = _school(app, '监控大学')
        _floor_with_seats(app, a, ['A-1', 'A-2'])
        _login(client, app, 'ad5', a)
        s = client.get('/api/admin/cameras/zones').get_json()['data']['summary']
        assert s['camera_count'] == 1
        assert s['seats_total'] == 2
        assert s['online_count'] + s['offline_count'] + s['maintenance_count'] == 1

    def test_scoped_by_school(self, client, app):
        """学校隔离：A 校管理员看不到 B 校的摄像头点位"""
        a = _school(app, '监控A大学')
        b = _school(app, '监控B大学')
        _floor_with_seats(app, a, ['A-1'])
        _floor_with_seats(app, b, ['Z-1'])
        _login(client, app, 'ad6', a)
        names = [c['building_name'] for c in
                 client.get('/api/admin/cameras/zones').get_json()['data']['cameras']]
        assert all('监控楼%s' % a == n for n in names), '不应出现它校点位'

    def test_super_admin_sees_all(self, client, app):
        a = _school(app, '监控A大学')
        b = _school(app, '监控B大学')
        _floor_with_seats(app, a, ['A-1'])
        _floor_with_seats(app, b, ['Z-1'])
        _login(client, app, 'root', None, role='super_admin')
        cams = client.get('/api/admin/cameras/zones').get_json()['data']['cameras']
        assert len(cams) >= 2

    def test_floor_filter(self, client, app):
        a = _school(app, '监控大学')
        bid, fid = _floor_with_seats(app, a, ['A-1'])
        _login(client, app, 'ad7', a)
        d = client.get('/api/admin/cameras/zones?floor_id=%d' % fid).get_json()['data']
        assert len(d['cameras']) == 1
        d2 = client.get('/api/admin/cameras/zones?floor_id=999999').get_json()['data']
        assert d2['cameras'] == []


class TestCameraSnapshot:
    def _first_cam(self, client, app, sid='snap1'):
        a = _school(app, '快照大学')
        _floor_with_seats(app, a, ['A-1', 'A-2'])
        _login(client, app, sid, a)
        cams = client.get('/api/admin/cameras/zones').get_json()['data']['cameras']
        return cams[0]

    def test_returns_svg_frame(self, client, app):
        cam = self._first_cam(client, app)
        r = client.get('/api/admin/cameras/%s/snapshot' % cam['id'])
        assert r.status_code == 200, r.get_json()
        d = r.get_json()['data']
        assert d['frame']['url'].startswith('data:image/svg+xml;base64,')
        assert d['taken_at']
        assert isinstance(d['occupied'], int)
        assert d['seat_count'] == 2

    def test_frame_contains_seat_labels(self, client, app):
        """帧内容应真实反映座位（可解码验证）"""
        import base64
        cam = self._first_cam(client, app, 'snap2')
        d = client.get('/api/admin/cameras/%s/snapshot' % cam['id']).get_json()['data']
        raw = base64.b64decode(d['frame']['url'].split(',', 1)[1]).decode('utf-8')
        assert '<svg' in raw
        assert 'A-1' in raw and 'A-2' in raw

    def test_bad_camera_id_404(self, client, app):
        a = _school(app, '快照大学')
        _login(client, app, 'snap3', a)
        assert client.get('/api/admin/cameras/nonsense/snapshot').status_code == 404
        assert client.get('/api/admin/cameras/cam-999999-A/snapshot').status_code == 404

    def test_snapshot_scoped_by_school(self, client, app):
        """不能通过构造 id 偷看它校点位的画面"""
        a = _school(app, '快照A大学')
        b = _school(app, '快照B大学')
        _, fid_b = _floor_with_seats(app, b, ['Z-1'])
        _login(client, app, 'snap4', a)
        r = client.get('/api/admin/cameras/cam-%d-Z/snapshot' % fid_b)
        assert r.status_code == 403

# -*- coding: utf-8 -*-
"""新建「硬件 / 传感器调试」面板的接口与页面验证（临时验证用）。"""
from app import db
from models.building import Building, Floor, Seat
from models.user import User
from werkzeug.security import generate_password_hash


def _admin_client(app, client):
    with app.app_context():
        user = User(
            student_id='hwadmin', name='硬件管理员',
            password_hash=generate_password_hash('123456'),
            email='hwadmin@test.com', role='admin', is_approved=True,
        )
        db.session.add(user)
        db.session.commit()
        uid = user.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'admin'
    return client


def _make_seat(app, label='A区-12'):
    with app.app_context():
        b = Building(name='测试馆')
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, name='1F')
        db.session.add(f)
        db.session.flush()
        s = Seat(floor_id=f.id, seat_label=label, x=10, y=10)
        db.session.add(s)
        db.session.commit()
        return s.id


def test_hardware_page_renders(app, client):
    c = _admin_client(app, client)
    r = c.get('/admin/hardware')
    assert r.status_code == 200
    assert b'/api/admin/sensor/overview' not in r.data  # 前端用 api-client 动态取，不内联
    assert 'admin/hardware.js' in r.get_data(as_text=True)


def test_sensor_overview_endpoint(app, client):
    c = _admin_client(app, client)
    sid = _make_seat(app, 'A区-12')
    r = c.get('/api/admin/sensor/overview')
    assert r.status_code == 200
    body = r.get_json()['data']
    assert 'seats' in body and 'simulator_running' in body and 'config' in body
    seat = next(x for x in body['seats'] if x['id'] == sid)
    assert seat['seat_label'] == 'A区-12'
    assert seat['online'] is False  # 无上报应为离线
    assert 'ir_front' in seat and 'ir_back' in seat and 'ir_enabled' in seat


def test_manual_report_via_real_endpoint(app, client):
    """面板的“手动模拟上报”走的就是 /api/sensor/report，验证能置为占用。"""
    c = _admin_client(app, client)
    sid = _make_seat(app, 'B3')
    r = c.post('/api/sensor/report', json={'seat_id': sid, 'ir_front': 1, 'ir_back': 1})
    assert r.status_code == 200
    with app.app_context():
        s = db.session.get(Seat, sid)
        assert s.status == 'occupied'
    # overview 里应显示在线 + ir=(1,1)
    body = c.get('/api/admin/sensor/overview').get_json()['data']
    seat = next(x for x in body['seats'] if x['id'] == sid)
    assert seat['ir_front'] == 1 and seat['ir_back'] == 1
    assert seat['online'] is True

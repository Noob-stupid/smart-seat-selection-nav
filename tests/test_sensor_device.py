# -*- coding: utf-8 -*-
"""ESP32 设备注册 / 配置下发 接口测试。"""
from app import db
from models.building import Building, Floor, Seat
from models.sensor_device import SensorDevice
from models.user import User
from werkzeug.security import generate_password_hash


def _admin(client, app):
    with app.app_context():
        u = User(student_id='devadmin', name='设备管理员',
                 password_hash=generate_password_hash('123456'),
                 email='devadmin@test.com', role='admin', is_approved=True)
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'admin'
    return client


def _seat(app, label='A区-12'):
    with app.app_context():
        b = Building(name='馆')
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, name='1F')
        db.session.add(f)
        db.session.flush()
        s = Seat(floor_id=f.id, seat_label=label, x=1, y=1)
        db.session.add(s)
        db.session.commit()
        return s.id


def test_register_new_device_defaults(client):
    r = client.post('/api/sensor/device/register', json={'device_id': 'AA:BB:CC:11:22:33'})
    assert r.status_code == 200
    data = r.get_json()['data']
    assert data['registered'] is True
    assert data['is_new'] is True
    assert data['config']['seat_label'] is None
    assert data['config']['ir_active_high'] is True   # 默认 PIR


def test_register_existing_not_new(client):
    client.post('/api/sensor/device/register', json={'device_id': 'AA:BB:CC:11:22:33'})
    r = client.post('/api/sensor/device/register', json={'device_id': 'AA:BB:CC:11:22:33'})
    assert r.get_json()['data']['is_new'] is False


def _dev_pk(app, device_id):
    with app.app_context():
        return SensorDevice.query.filter_by(device_id=device_id).first().id


def test_device_config_returns_binding(app, client):
    sid = _seat(app, 'B区-7')
    # 注册并绑定
    r = client.post('/api/sensor/device/register', json={'device_id': 'AA:BB:CC:44:55:66'})
    dev_pk = _dev_pk(app, 'AA:BB:CC:44:55:66')
    _admin(client, app).put(f'/api/admin/sensor/devices/{dev_pk}', json={
        'seat_id': sid, 'ir_active_high': True, 'report_interval_ms': 3000,
    })
    cfg = client.get('/api/sensor/device_config?device_id=AA:BB:CC:44:55:66').get_json()['data']
    assert cfg['registered'] is True
    assert cfg['config']['seat_label'] == 'B区-7'
    assert cfg['config']['report_interval_ms'] == 3000
    assert cfg['config']['ir_active_high'] is True


def test_admin_device_list_and_update_clears_new(client, app):
    ac = _admin(client, app)  # 管理员客户端（复用，勿重复创建）
    ac.post('/api/sensor/device/register', json={'device_id': 'AA:BB:CC:99:00:11'})
    with app.app_context():
        dev = SensorDevice.query.filter_by(device_id='AA:BB:CC:99:00:11').first()
        assert dev.is_new is True
        dev_pk = dev.id
    lst = ac.get('/api/admin/sensor/devices').get_json()['data']['devices']
    assert any(d['device_id'] == 'AA:BB:CC:99:00:11' for d in lst)
    # 更新后清除 is_new
    ac.put(f'/api/admin/sensor/devices/{dev_pk}', json={'report_interval_ms': 4000})
    with app.app_context():
        assert db.session.get(SensorDevice, dev_pk).is_new is False


def test_report_updates_device_last_seen(client, app):
    sid = _seat(app, 'C区-1')
    client.post('/api/sensor/device/register', json={'device_id': 'AA:BB:CC:12:34:56'})
    # 上报带 device_id -> 刷新在线时间
    r = client.post('/api/sensor/report', json={
        'seat_id': sid, 'ir_front': 1, 'ir_back': 1, 'device_id': 'AA:BB:CC:12:34:56',
    })
    assert r.status_code == 200
    with app.app_context():
        dev = SensorDevice.query.filter_by(device_id='AA:BB:CC:12:34:56').first()
        assert dev.last_seen is not None


def test_ultrasonic_sensor_type_config(app, client):
    """HC-SR04P 超声波：配置 sensor_type=ultrasonic + 距离阈值，并下发到设备。"""
    sid = _seat(app, 'US-1')
    ac = _admin(client, app)
    client.post('/api/sensor/device/register', json={'device_id': 'AA:BB:CC:AA:AA:11'})
    with app.app_context():
        dev_pk = SensorDevice.query.filter_by(device_id='AA:BB:CC:AA:AA:11').first().id
    ac.put(f'/api/admin/sensor/devices/{dev_pk}', json={
        'seat_id': sid, 'sensor_type': 'ultrasonic', 'distance_threshold_cm': 40,
    })
    cfg = client.get('/api/sensor/device_config?device_id=AA:BB:CC:AA:AA:11').get_json()['data']
    assert cfg['config']['sensor_type'] == 'ultrasonic'
    assert cfg['config']['distance_threshold_cm'] == 40
    bad = ac.put(f'/api/admin/sensor/devices/{dev_pk}', json={'sensor_type': 'badname'})
    assert bad.status_code == 400

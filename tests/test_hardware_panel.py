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


# ================================================================ 在线判定超时（回归）
class TestOnlineTimeout:
    """回归：设备断电后必须「很快」显示离线。

    旧实现把「在线/离线」与「座位标记异常」混用同一个阈值
    （SEAT_OFFLINE_HOURS，现场被设为 1 小时），导致断电后
    面板仍显示「在线」长达一小时。现在在线判定改用独立的
    SEAT_ONLINE_TIMEOUT_MINUTES（默认 3 分钟）。
    """

    def _seat_with_age(self, app, minutes_ago):
        from models.building import Building, Floor, Seat as S
        from datetime import datetime, timedelta
        with app.app_context():
            b = Building(name='超时馆')
            db.session.add(b)
            db.session.flush()
            f = Floor(building_id=b.id, floor_number=1, name='1F')
            db.session.add(f)
            db.session.flush()
            s = S(floor_id=f.id, seat_label='T-1', x=1, y=1, status='free',
                  last_scan_time=datetime.utcnow() - timedelta(minutes=minutes_ago))
            db.session.add(s)
            db.session.commit()
            return s.id

    def test_recent_report_is_online(self, app, client):
        _admin_client(app, client)
        self._seat_with_age(app, 0.5)          # 30 秒前
        d = client.get('/api/admin/sensor/overview').get_json()['data']
        assert d['seats'][0]['online'] is True

    def test_report_10min_ago_is_offline(self, app, client):
        """核心回归：10 分钟无上报必须判离线（旧逻辑因 1 小时阈值会误判在线）"""
        _admin_client(app, client)
        self._seat_with_age(app, 10)
        d = client.get('/api/admin/sensor/overview').get_json()['data']
        assert d['seats'][0]['online'] is False, '断电 10 分钟后不应仍显示在线'

    def test_timeout_is_configurable(self, app, client):
        """后台可调在线超时：调大后同样的座位重新变为在线"""
        from config import Config
        _admin_client(app, client)
        self._seat_with_age(app, 10)
        old = Config.SEAT_ONLINE_TIMEOUT_MINUTES
        try:
            Config.SEAT_ONLINE_TIMEOUT_MINUTES = 30
            d = client.get('/api/admin/sensor/overview').get_json()['data']
            assert d['seats'][0]['online'] is True
        finally:
            Config.SEAT_ONLINE_TIMEOUT_MINUTES = old

    def test_devices_endpoint_uses_short_timeout(self, app, client):
        """设备列表的 online 也必须用短超时"""
        from models.sensor_device import SensorDevice as SD
        from datetime import datetime, timedelta
        _admin_client(app, client)
        with app.app_context():
            db.session.add(SD(device_id='FF:EE:DD:CC:BB:AA',
                              last_seen=datetime.utcnow() - timedelta(minutes=10)))
            db.session.commit()
        d = client.get('/api/admin/sensor/devices').get_json()['data']
        dev = [x for x in d['devices'] if x['device_id'] == 'FF:EE:DD:CC:BB:AA'][0]
        assert dev['online'] is False
        assert 'online_timeout_minutes' in d

    def test_settings_page_roundtrip(self, app, client):
        """设置页往返：GET 配置含该字段 -> PUT 修改 -> 生效并持久化。"""
        import json
        import app as app_module
        _admin_client(app, client)
        d = client.get('/api/admin/config').get_json()['data']
        assert 'seat_online_timeout_minutes' in d, '设置页需要读到该字段'

        r = client.put('/api/admin/config', json={'seat_online_timeout_minutes': 7})
        assert r.status_code == 200, r.get_json()
        from config import Config
        try:
            assert Config.SEAT_ONLINE_TIMEOUT_MINUTES == 7
            with open(app_module._RUNTIME_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            assert saved.get('seat_online_timeout_minutes') == 7
        finally:
            Config.SEAT_ONLINE_TIMEOUT_MINUTES = 3

    def test_settings_page_rejects_bad_timeout(self, app, client):
        _admin_client(app, client)
        assert client.put('/api/admin/config',
                          json={'seat_online_timeout_minutes': 0}).status_code == 400
        assert client.put('/api/admin/config',
                          json={'seat_online_timeout_minutes': 999}).status_code == 400

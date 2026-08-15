"""预约签到功能测试：按钮签到 / 扫码签到 / 二维码开关"""
from datetime import datetime, timedelta

from app import db, Config
from models.building import Seat
from models.reservation import Reservation
from tests.test_api import make_seat


def _create_reservation(client, seat_id):
    # 使用未来时间（5 分钟后），与真实前端只允许预约未来时段的行为一致
    start = datetime.utcnow() + timedelta(minutes=5)
    payload = {
        'seat_id': seat_id,
        'start_time': start.isoformat(),
        'end_time': (start + timedelta(hours=1)).isoformat(),
    }
    r = client.post('/api/reservations', json=payload)
    assert r.status_code == 201, r.get_json()
    return r.get_json()['data']['id']


def _set_seat_ir(app, seat_id, ir_front=1, ir_back=1):
    with app.app_context():
        seat = db.session.get(Seat, seat_id)
        seat.ir_front = ir_front
        seat.ir_back = ir_back
        db.session.commit()


def _set_seat_node(app, seat_id, node_id):
    with app.app_context():
        seat = db.session.get(Seat, seat_id)
        seat.nearest_node_id = node_id
        db.session.commit()


def _reservation_token(app, rid):
    with app.app_context():
        return db.session.get(Reservation, rid).qr_token


def _enable_qr():
    Config.CHECKIN_QR_ENABLED = True


def _disable_qr():
    Config.CHECKIN_QR_ENABLED = False


class TestButtonCheckin:
    def test_sensor_not_occupied_rejected(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        # 传感器默认无人（ir 均为 0）
        r = client.post(f'/api/reservations/{rid}/checkin', json={})
        assert r.status_code == 400
        assert '未检测到有人' in r.get_json()['message']

    def test_success_without_road_network(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        _set_seat_ir(app, ids['seat_id'], 1, 1)
        # 座位无路网节点时跳过定位校验，仅需传感器检测有人
        r = client.post(f'/api/reservations/{rid}/checkin', json={})
        assert r.status_code == 200
        assert r.get_json()['data']['status'] == 'checked_in'

    def test_location_mismatch_rejected(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        _set_seat_ir(app, ids['seat_id'], 1, 1)
        _set_seat_node(app, ids['seat_id'], 'N1')
        # 未提供定位
        r = client.post(f'/api/reservations/{rid}/checkin', json={})
        assert r.status_code == 400
        assert '扫码定位' in r.get_json()['message']
        # 定位节点不匹配
        r = client.post(f'/api/reservations/{rid}/checkin', json={'loc_node_id': 'N2'})
        assert r.status_code == 400
        assert '不在该座位附近' in r.get_json()['message']

    def test_location_match_success(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        _set_seat_ir(app, ids['seat_id'], 1, 1)
        _set_seat_node(app, ids['seat_id'], 'N1')
        r = client.post(f'/api/reservations/{rid}/checkin', json={'loc_node_id': 'N1'})
        assert r.status_code == 200


class TestScanCheckin:
    def test_disabled_by_default(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        token = _reservation_token(app, rid)
        r = client.post('/api/checkin/scan', json={'token': token})
        assert r.status_code == 400
        assert '未开启' in r.get_json()['message']

    def test_scan_with_reservation_token(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        token = _reservation_token(app, rid)
        _enable_qr()
        try:
            r = client.post('/api/checkin/scan', json={'token': token})
            assert r.status_code == 200
            assert r.get_json()['data']['status'] == 'checked_in'
        finally:
            _disable_qr()

    def test_scan_with_seat_code(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        _enable_qr()
        try:
            r = client.post('/api/checkin/scan', json={'token': f'SEAT:{ids["seat_id"]}'})
            assert r.status_code == 200
        finally:
            _disable_qr()

    def test_scan_other_user_reservation_rejected(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        token = _reservation_token(app, rid)
        _enable_qr()
        try:
            # 用另一用户登录后扫该预约码应被拒绝
            from models.user import User
            from werkzeug.security import generate_password_hash
            with app.app_context():
                other = User(student_id='other2', name='其他', password_hash=generate_password_hash('123'))
                db.session.add(other)
                db.session.commit()
                other_id = other.id
            with client.session_transaction() as sess:
                sess['user_id'] = other_id
                sess['role'] = 'student'
            r = client.post('/api/checkin/scan', json={'token': token})
            assert r.status_code == 403
        finally:
            _disable_qr()


class TestQrCodeEndpoints:
    def test_reservation_qrcode_disabled(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        r = client.get(f'/api/reservations/{rid}/qrcode')
        assert r.status_code == 403

    def test_seat_qrcode_requires_admin(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        r = client.get(f'/api/seats/{ids["seat_id"]}/qrcode')
        assert r.status_code == 403

    def test_reservation_qrcode_enabled(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        rid = _create_reservation(client, ids['seat_id'])
        _enable_qr()
        try:
            r = client.get(f'/api/reservations/{rid}/qrcode')
            assert r.status_code == 200
            assert r.content_type.startswith('image/png')
        finally:
            _disable_qr()

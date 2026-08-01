"""API 端点测试"""
import json
from datetime import datetime, timedelta

from app import db
from models.building import Building, Floor, Seat
from models.user import User


def make_seat(app, user_id=None, status='free', last_scan_time=None):
    """在测试数据库中创建一个可用的建筑/楼层/座位。"""
    with app.app_context():
        building = Building(name='测试馆', region='测试区')
        db.session.add(building)
        db.session.flush()
        floor = Floor(building_id=building.id, floor_number=1, name='1F')
        db.session.add(floor)
        db.session.flush()
        seat = Seat(
            floor_id=floor.id, seat_label='A1', x=10, y=10,
            status=status, current_user_id=user_id,
            last_scan_time=last_scan_time,
        )
        db.session.add(seat)
        db.session.commit()
        return {
            'building_id': building.id,
            'floor_id': floor.id,
            'seat_id': seat.id,
        }


class TestAuthAPI:
    def test_login_page(self, client):
        r = client.get('/login')
        assert r.status_code == 200
        html = r.data.decode('utf-8')

    def test_register_page(self, client):
        r = client.get('/register')
        assert r.status_code == 200
        html = r.data.decode('utf-8')

    def test_api_login_invalid(self, client):
        r = client.post('/api/auth/login', json={
            'student_id': '', 'password': ''
        })
        data = r.get_json()
        assert r.status_code == 400
        assert '请填写' in data['message']

    def test_api_login_wrong(self, client, app):
        r = client.post('/api/auth/login', json={
            'student_id': 'nobody', 'password': 'wrong'
        })
        assert r.status_code == 401

    def test_api_register(self, client, app):
        r = client.post('/api/auth/register', json={
            'student_id': 'newuser123',
            'name': 'newuser',
            'password': 'pass123',
            'confirm_password': 'pass123',
        })
        assert r.status_code == 201


class TestProfileAPI:
    def test_profile_page_requires_login(self, client):
        r = client.get('/profile', follow_redirects=True)
        html = r.data.decode('utf-8')

    def test_profile_page_logged_in(self, logged_in):
        client, user = logged_in
        r = client.get('/profile')
        assert r.status_code == 200
        html = r.data.decode('utf-8')

    def test_update_profile(self, logged_in):
        client, user = logged_in
        r = client.put('/api/profile', json={
            'name': 'new_name',
            'tags': ['quiet', 'window'],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['data']['name'] == 'new_name'

    def test_change_password_wrong_old(self, logged_in):
        client, user = logged_in
        r = client.put('/api/profile/password', json={
            'old_password': 'wrong',
            'new_password': 'new123456',
        })
        assert r.status_code == 400


class TestReservationPage:
    def test_page_logged_in(self, logged_in):
        client, user = logged_in
        r = client.get('/reservation')
        assert r.status_code == 200

    def test_page_empty_state(self, logged_in):
        client, user = logged_in
        r = client.get('/reservation')
        html = r.data.decode('utf-8')
        assert '预约座位' in html


class TestBuildingsAPI:
    def test_list_buildings(self, client, app):
        r = client.get('/api/buildings')
        assert r.status_code == 200
        data = r.get_json()
        assert data['code'] == 200

    def test_nonexistent_building(self, client, app):
        r = client.get('/api/buildings/99999')
        assert r.status_code == 404


class TestSeatsAPI:
    def test_list_seats(self, client, app):
        r = client.get('/api/seats')
        assert r.status_code == 200


class TestSecurityAndConcurrency:
    def test_upload_requires_admin(self, client):
        r = client.post('/api/upload')
        assert r.status_code == 401

    def test_network_get_requires_admin(self, client):
        r = client.get('/api/admin/network/1')
        assert r.status_code == 401

    def test_reservation_requires_login(self, client):
        r = client.post('/api/reservations', json={})
        assert r.status_code == 401

    def test_behavior_report_requires_login(self, client):
        r = client.get('/api/behavior/report/1')
        assert r.status_code == 401

    def test_lock_start_requires_login(self, client):
        r = client.post('/api/lock/start', json={})
        assert r.status_code == 401

    def test_reservation_uses_session_user_not_body(self, logged_in, app):
        client, user = logged_in
        with app.app_context():
            other = User(student_id='other', name='其他用户', password_hash='x')
            db.session.add(other)
            db.session.commit()
            other_id = other.id
        ids = make_seat(app)

        payload = {
            'user_id': other_id,
            'seat_id': ids['seat_id'],
            'start_time': datetime.utcnow().isoformat(),
            'end_time': (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        }
        r = client.post('/api/reservations', json=payload)
        assert r.status_code == 201

        reservations = client.get('/api/reservations').get_json()['data']
        assert reservations
        assert all(item['user_id'] == user.id for item in reservations)

    def test_duplicate_reservation_rejected(self, logged_in, app):
        client, _ = logged_in
        ids = make_seat(app)
        payload = {
            'seat_id': ids['seat_id'],
            'start_time': datetime.utcnow().isoformat(),
            'end_time': (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        }
        assert client.post('/api/reservations', json=payload).status_code == 201
        assert client.post('/api/reservations', json=payload).status_code == 400

    def test_lock_start_rejects_non_owner(self, logged_in, app):
        client, _ = logged_in
        with app.app_context():
            other = User(student_id='owner', name='占座用户', password_hash='x')
            db.session.add(other)
            db.session.commit()
            other_id = other.id
        ids = make_seat(app, user_id=other_id, status='occupied')
        with app.app_context():
            seat = db.session.get(Seat, ids['seat_id'])
            seat.occupied_since = datetime.utcnow() - timedelta(minutes=30)
            db.session.commit()

        r = client.post('/api/lock/start', json={'seat_id': ids['seat_id']})
        assert r.status_code == 403

    def test_sensor_stale_scan_marks_error(self, client, app):
        old_time = datetime.utcnow() - timedelta(hours=25)
        ids = make_seat(app, status='occupied', last_scan_time=old_time)
        r = client.post('/api/sensor/report', json={
            'seat_id': ids['seat_id'], 'ir_front': 0, 'ir_back': 0,
        })
        assert r.status_code == 200
        with app.app_context():
            seat = db.session.get(Seat, ids['seat_id'])
            assert seat.status == 'error'

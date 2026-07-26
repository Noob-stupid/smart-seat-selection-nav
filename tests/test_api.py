"""API 端点测试"""
import json


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

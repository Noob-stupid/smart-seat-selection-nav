# -*- coding: utf-8 -*-
"""ESP32 硬件接入测试：/api/sensor/report 支持 seat_id / seat_label 两种座位定位。

覆盖场景（与 DEMO/src/main.cpp 的两种上报方式对应）：
- 按数据库数字 id 上报（原逻辑，向后兼容）
- 按座位标签 seat_label 上报（真机推荐方式）
- 连续两次"无人"上报后座位释放
- 同名标签跨楼层时的歧义报错与 floor_id 消歧
"""
from datetime import datetime

from app import db
from models.building import Building, Floor, Seat


def _make_floor_and_seat(app, seat_label='A1', floor_number=1):
    """在测试数据库中创建 建筑/楼层/座位，返回 seat_id 与 floor_id。"""
    with app.app_context():
        building = Building(name='测试馆', region='测试区')
        db.session.add(building)
        db.session.flush()
        floor = Floor(building_id=building.id, floor_number=floor_number,
                      name=f'{floor_number}F')
        db.session.add(floor)
        db.session.flush()
        seat = Seat(floor_id=floor.id, seat_label=seat_label, x=10, y=10)
        db.session.add(seat)
        db.session.commit()
        return {'seat_id': seat.id, 'floor_id': floor.id}


class TestSensorReportSeatLabel:
    """座位标识双通道：数字 id 与 标签"""

    def test_report_by_numeric_id_occupies(self, client, app):
        ids = _make_floor_and_seat(app)
        r = client.post('/api/sensor/report', json={
            'seat_id': ids['seat_id'], 'ir_front': 1, 'ir_back': 1,
        })
        assert r.status_code == 200
        with app.app_context():
            seat = db.session.get(Seat, ids['seat_id'])
            assert seat.status == 'occupied'
            assert seat.consecutive_empty == 0

    def test_report_by_label_occupies(self, client, app):
        _make_floor_and_seat(app, seat_label='A区-12')
        r = client.post('/api/sensor/report', json={
            'seat_label': 'A区-12', 'ir_front': 1, 'ir_back': 1,
        })
        assert r.status_code == 200
        data = r.get_json()['data']
        assert data['status'] == 'occupied'

    def test_report_by_label_frees_after_two_empty(self, client, app):
        ids = _make_floor_and_seat(app, seat_label='B3')
        with app.app_context():
            seat = db.session.get(Seat, ids['seat_id'])
            seat.status = 'occupied'
            seat.occupied_since = datetime.utcnow()
            db.session.commit()

        r1 = client.post('/api/sensor/report', json={
            'seat_label': 'B3', 'ir_front': 0, 'ir_back': 0,
        })
        assert r1.status_code == 200
        with app.app_context():
            seat = db.session.get(Seat, ids['seat_id'])
            assert seat.consecutive_empty == 1
            assert seat.status == 'occupied'

        r2 = client.post('/api/sensor/report', json={
            'seat_label': 'B3', 'ir_front': 0, 'ir_back': 0,
        })
        assert r2.status_code == 200
        with app.app_context():
            seat = db.session.get(Seat, ids['seat_id'])
            assert seat.consecutive_empty == 2
            assert seat.status == 'free'

    def test_report_by_label_rejects_ambiguous(self, client, app):
        _make_floor_and_seat(app, seat_label='A1', floor_number=1)
        _make_floor_and_seat(app, seat_label='A1', floor_number=2)
        r = client.post('/api/sensor/report', json={
            'seat_label': 'A1', 'ir_front': 1, 'ir_back': 1,
        })
        assert r.status_code == 400
        assert '多个座位' in r.get_json()['message']

    def test_report_by_label_with_floor_id_disambiguates(self, client, app):
        _make_floor_and_seat(app, seat_label='A1', floor_number=1)
        ids2 = _make_floor_and_seat(app, seat_label='A1', floor_number=2)
        r = client.post('/api/sensor/report', json={
            'seat_label': 'A1', 'floor_id': ids2['floor_id'],
            'ir_front': 1, 'ir_back': 1,
        })
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(Seat, ids2['seat_id']).status == 'occupied'

    def test_report_missing_identity_returns_400(self, client, app):
        _make_floor_and_seat(app)
        r = client.post('/api/sensor/report', json={'ir_front': 1, 'ir_back': 1})
        assert r.status_code == 400
        assert 'seat_id 或 seat_label' in r.get_json()['message']


# ================================================================ 离线判定回归
class TestReportOfflineContradiction:
    """回归：传感器上报路径不得把刚算出的状态又改回 error。

    旧实现里 sensor_report 在按红外更新状态之后，又用
    "距上次上报 > 24h" 判定设备离线并覆盖 status='error'。
    但本次上报本身就是设备在线的证据 —— 结果是设备断电超过 24h
    后首次上报时，座位先变 occupied 又被改回 error，要等第二次才恢复。
    实机场景：隔夜后重新上电，第一次上报被吞掉。
    """

    def _setup_seat(self, app, status='error', days_ago=2):
        import datetime as dt
        from models.building import Building, Floor, Seat as S
        with app.app_context():
            b = Building(name='离线馆')
            db.session.add(b); db.session.flush()
            f = Floor(building_id=b.id, floor_number=1, name='1F')
            db.session.add(f); db.session.flush()
            s = S(floor_id=f.id, seat_label='O-1', x=1, y=1, status=status,
                  last_scan_time=dt.datetime.utcnow() - dt.timedelta(days=days_ago),
                  error_since=dt.datetime.utcnow() - dt.timedelta(days=3),
                  consecutive_empty=0, ir_enabled=True)
            db.session.add(s); db.session.commit()
            return s.id

    def test_first_report_after_long_gap_sets_occupied(self, client, app):
        sid = self._setup_seat(app, 'error', days_ago=2)
        r = client.post('/api/sensor/report', json={
            'seat_id': sid, 'ir_front': 1, 'ir_back': 1, 'distance_cm': 30})
        assert r.status_code == 200
        assert r.get_json()['data']['status'] == 'occupied', (
            '长间隔后的首次上报就应生效，不能被离线判定覆盖回 error')
        with app.app_context():
            from models.building import Seat as S
            assert db.session.get(S, sid).status == 'occupied'
            assert db.session.get(S, sid).error_since is None, '异常标记应被清除'

    def test_long_gap_empty_report_marks_error(self, client, app):
        """长期离线后报来「空闲」不足以判定座位真的空闲 -> 仍标异常。

        这是 tests/test_api.py::test_sensor_stale_scan_marks_error 的同一语义，
        本次修复只额外保证「有人」读数不被覆盖。
        """
        sid = self._setup_seat(app, 'occupied', days_ago=2)
        r = client.post('/api/sensor/report', json={
            'seat_id': sid, 'ir_front': 0, 'ir_back': 0, 'distance_cm': 300})
        assert r.status_code == 200
        assert r.get_json()['data']['consecutive_empty'] == 1
        with app.app_context():
            from models.building import Seat as S
            st = db.session.get(S, sid)
            assert st.status == 'error'
            assert st.error_since is not None

    def test_second_empty_report_frees_seat(self, client, app):
        """第二次空闲上报（间隔已正常）-> 自愈为 free"""
        sid = self._setup_seat(app, 'error', days_ago=2)
        for _ in range(2):
            client.post('/api/sensor/report', json={
                'seat_id': sid, 'ir_front': 0, 'ir_back': 0, 'distance_cm': 300})
        with app.app_context():
            from models.building import Seat as S
            assert db.session.get(S, sid).status == 'free'

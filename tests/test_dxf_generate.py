# -*- coding: utf-8 -*-
"""DXF 路线（直接读 CAD 图纸建路网 + 座位）的回归测试。

与图片路线相比，DXF 是结构化数据：图层里已经写明哪是墙、哪是家具、
这间房叫什么，不用二值化猜也不用骨架细化猜可行走区。

实测基准（library_cad/图书馆一层平面图.dxf）：
    节点 810 / 边 956 / 座位 187 / 房间 23
"""
import io as _io
import os

import pytest

REAL_DXF = os.path.join(os.path.dirname(__file__), '..', 'library_cad',
                        '图书馆一层平面图.dxf')


@pytest.fixture
def admin_client(client, app):
    """已登录的管理员客户端（conftest 的 logged_in 是 student，进不了 admin 接口）。"""
    from models.user import User
    from werkzeug.security import generate_password_hash
    from app import db

    with app.app_context():
        u = User(student_id='advisor', name='测试管理员',
                 password_hash=generate_password_hash('123456'),
                 email='admin@test.com', role='admin', is_approved=True)
        db.session.add(u)
        db.session.commit()
        with client.session_transaction() as sess:
            sess['user_id'] = u.id
            sess['role'] = 'admin'
            sess['name'] = '测试管理员'
    return client


def _mk_floor(app):
    from models.building import Building, Floor
    from app import db
    with app.app_context():
        b = Building(name='测试楼')
        db.session.add(b)
        db.session.commit()
        f = Floor(name='测试层', floor_number=1, building_id=b.id)
        db.session.add(f)
        db.session.commit()
        return f.id


@pytest.mark.skipif(not os.path.exists(REAL_DXF), reason='缺测试用 DXF')
def test_generate_from_dxf_produces_seats_and_rooms(app, admin_client):
    """DXF 路线应一次拿到路网 + 座位 + 房间名，这是图片路线做不到的。"""
    fid = _mk_floor(app)
    r = admin_client.post('/api/admin/network/generate-from-dxf',
                          json={'floor_id': fid, 'dxf_path': REAL_DXF})
    assert r.status_code == 200, (r.get_json() or {}).get('message')
    d = r.get_json()['data']

    stats = d['stats']
    assert stats['node_count'] > 300, '节点太少：%s' % stats
    assert stats['edge_count'] > 300, '边太少：%s' % stats
    assert stats['seat_count'] > 100, '应识别出上百个座位：%s' % stats
    assert stats['room_count'] > 10, '应识别出十个以上房间：%s' % stats

    rooms = d['rooms']
    assert any(x.get('name') for x in rooms), '房间应有名称'
    assert any(x.get('code') for x in rooms), '房间应有编号'

    seats = d['seats']
    labels = [x['seat_label'] for x in seats]
    assert all(labels), '每个座位都要有编号'
    assert len(set(labels)) == len(labels), '座位编号不能重复'
    w = d['network']['floor_info']['width']
    h = d['network']['floor_info']['height']
    assert all(0 <= x['x'] < w and 0 <= x['y'] < h for x in seats), '座位坐标越界'


@pytest.mark.skipif(not os.path.exists(REAL_DXF), reason='缺测试用 DXF')
def test_generate_from_dxf_apply_seats_writes_db(app, admin_client):
    """apply_seats=true 时座位要真的入库，且与手动添加的座位结构一致。"""
    from models.building import Seat
    fid = _mk_floor(app)
    r = admin_client.post('/api/admin/network/generate-from-dxf',
                          json={'floor_id': fid, 'dxf_path': REAL_DXF,
                                'apply_seats': True})
    assert r.status_code == 200
    created = r.get_json()['data']['seat_created']
    assert created > 100, '应写入上百个座位，实际 %d' % created

    with app.app_context():
        rows = Seat.query.filter_by(floor_id=fid).all()
        assert len(rows) == created
        s = rows[0]
        assert s.seat_label and s.x is not None and s.y is not None
        assert s.status == 'free', '新座位默认状态应为 free，与手动添加一致'


def test_generate_from_dxf_missing_file_is_400(app, admin_client):
    """DXF 路径不存在要回 400 JSON，不能 500。"""
    fid = _mk_floor(app)
    r = admin_client.post('/api/admin/network/generate-from-dxf',
                          json={'floor_id': fid, 'dxf_path': r'C:\no\such.dxf'})
    assert r.status_code == 400
    assert r.is_json


def test_generate_from_dxf_missing_params_is_400(app, admin_client):
    """缺参数要回 400 JSON。"""
    r = admin_client.post('/api/admin/network/generate-from-dxf', json={})
    assert r.status_code == 400
    assert r.is_json


@pytest.mark.skipif(not os.path.exists(REAL_DXF), reason='缺测试用 DXF')
def test_dxf_upload_accepts_and_validates(app, admin_client):
    """上传 DXF：能解析的收下，解析不了的要拒绝。"""
    with open(REAL_DXF, 'rb') as f:
        r = admin_client.post('/api/upload',
                              data={'file': (_io.BytesIO(f.read()), 'plan.dxf')},
                              content_type='multipart/form-data')
    assert r.status_code == 200, (r.get_json() or {}).get('message')
    d = r.get_json()['data']
    assert d['kind'] == 'dxf'
    assert d['entity_count'] > 100
    assert os.path.exists(d['file_path'])
    os.remove(d['file_path'])

    r2 = admin_client.post('/api/upload',
                           data={'file': (_io.BytesIO(b'not a dxf at all'), 'bad.dxf')},
                           content_type='multipart/form-data')
    assert r2.status_code == 400
    assert r2.is_json


def test_upload_rejects_unknown_extension(app, admin_client):
    """不认识的扩展名要拒绝。"""
    r = admin_client.post('/api/upload',
                          data={'file': (_io.BytesIO(b'x'), 'evil.exe')},
                          content_type='multipart/form-data')
    assert r.status_code == 400
    assert r.is_json

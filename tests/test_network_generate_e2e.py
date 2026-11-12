# -*- coding: utf-8 -*-
"""路网生成接口的端到端回归测试。

背景：用户点「自动生成」时前端只收到一个 HTML 500 页，看不出真因。
查下来是四件事叠在一起（全局异常没兜底、保存段裸在 try 外、
WebP 伪装的 png 读不了、连边零容差）。这里把每一件都钉住，
以后再坏会立刻红。

不触碰真实数据库：全部走 conftest 的内存 SQLite。
"""
import os

import pytest

REAL_PLAN = os.path.join(os.path.dirname(__file__), '..', 'uploads',
                         'plane_room_0276db07.jpg')


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


def _mk_floor(app, plan_path=None, seats=None):
    """建一栋楼 + 一层楼 + 若干座位，返回 floor_id。"""
    from models.building import Building, Floor, Seat
    from app import db

    with app.app_context():
        b = Building(name='测试楼')
        db.session.add(b)
        db.session.commit()
        f = Floor(name='测试层', floor_number=1, building_id=b.id)
        db.session.add(f)
        db.session.commit()
        fid = f.id
        if plan_path:
            f.floor_plan_path = plan_path
            f.floor_plan_width = 1931
            f.floor_plan_height = 791
            db.session.commit()
        for label, x, y in (seats or []):
            db.session.add(Seat(seat_label=label, x=x, y=y,
                                floor_id=fid, seat_type='normal'))
        db.session.commit()
        return fid


# ---------------------------------------------------------------- 接口行为

def test_generate_returns_json_not_html_when_floor_has_no_seats(app, admin_client):
    """楼层没座位时应回 400 JSON，而不是 HTML 500。"""
    fid = _mk_floor(app)
    r = admin_client.post('/api/admin/network/generate', json={'floor_id': fid})
    assert r.status_code == 400, '没座位应该 400，实际 %d' % r.status_code
    assert r.is_json, '必须是 JSON —— 前端要读出中文原因'
    body = r.get_json()
    assert body['code'] == 400
    assert '座位' in body['message']


def test_generate_without_plan_uses_seats_only(app, admin_client):
    """没有平面图时走「按座位坐标」分支，不应 500。"""
    fid = _mk_floor(app, seats=[('A-1', 100, 100), ('A-2', 200, 100)])
    r = admin_client.post('/api/admin/network/generate', json={'floor_id': fid})
    assert r.status_code == 200, '无平面图也应成功，实际 %d：%s' % (
        r.status_code, (r.get_json() or {}).get('message'))
    data = r.get_json()['data']
    assert data['network']['nodes'], '至少要有节点'
    assert data['network']['edges'], '两个座位之间应该有边'


def test_floor_not_found_is_404_json(app, admin_client):
    """不存在的楼层应回 404 JSON。"""
    r = admin_client.post('/api/admin/network/generate', json={'floor_id': 999999})
    assert r.status_code == 404
    assert r.is_json


@pytest.mark.skipif(not os.path.exists(REAL_PLAN), reason='缺测试用平面图')
def test_generate_with_real_plan_has_low_isolation(app, admin_client):
    """有真实平面图时，路网不应大量孤立节点（连边零容差曾导致 49.7% 孤立）。"""
    fid = _mk_floor(app, plan_path=REAL_PLAN, seats=[('A-1', 300, 300)])
    r = admin_client.post('/api/admin/network/generate', json={'floor_id': fid})
    assert r.status_code == 200, (r.get_json() or {}).get('message')

    net = r.get_json()['data']['network']
    nodes, edges = net['nodes'], net['edges']
    assert len(nodes) > 100, '真实平面图应生成上百个节点，实际 %d' % len(nodes)

    deg = {}
    for e in edges:
        deg[e['from']] = deg.get(e['from'], 0) + 1
        deg[e['to']] = deg.get(e['to'], 0) + 1
    iso_ratio = (len(nodes) - len(deg)) / len(nodes)
    # 修好膨胀容差后实测 3.8%；留足余量，超过 15% 就是回归
    assert iso_ratio < 0.15, '孤立节点占比 %.1f%% 过高（曾修复到 3.8%%）' % (iso_ratio * 100)

    avg_deg = 2 * len(edges) / len(nodes)
    assert avg_deg > 1.5, '平均度数 %.2f 过低，路网碎片化' % avg_deg


@pytest.mark.skipif(not os.path.exists(REAL_PLAN), reason='缺测试用平面图')
def test_all_nodes_inside_image(app, admin_client):
    """节点坐标必须在图像内（曾经出现 y=-10 这种越界坐标）。"""
    fid = _mk_floor(app, plan_path=REAL_PLAN, seats=[('A-1', 300, 300)])
    r = admin_client.post('/api/admin/network/generate', json={'floor_id': fid})
    assert r.status_code == 200

    net = r.get_json()['data']['network']
    xs = [n['x'] for n in net['nodes'].values()]
    ys = [n['y'] for n in net['nodes'].values()]
    w = net['floor_info']['width']
    h = net['floor_info']['height']

    assert min(xs) >= 0 and min(ys) >= 0, '出现负坐标：x_min=%d y_min=%d' % (min(xs), min(ys))
    assert max(xs) < w and max(ys) < h, '坐标超出图像：x_max=%d y_max=%d (图 %dx%d)' % (
        max(xs), max(ys), w, h)


def test_webp_disguised_as_png_can_be_read(app, admin_client):
    """WebP 内容、.png 扩展名的图也要能读（浏览器截图、微信转存都这样）。

    原来用 cv2.imread，它只看扩展名选解码器，直接返回 None，整条流程失败。
    """
    import numpy as np
    import cv2
    import tempfile

    if not os.path.exists(REAL_PLAN):
        pytest.skip('缺测试用平面图')

    img = cv2.imread(REAL_PLAN)
    if img is None:
        pytest.skip('基准图读不到')
    fd, fake_png = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    # 用 WebP 编码，但文件名是 .png
    cv2.imencode('.webp', img)[1].tofile(fake_png)
    try:
        from utils.mapget import RoadNetworkGenerator
        net = RoadNetworkGenerator().generate_from_floorplan(
            fake_png, [{'x': 300, 'y': 300, 'label': 'A-1'}])
        assert net['nodes'], 'WebP 伪装的 png 应该能正常生成路网'
    finally:
        os.remove(fake_png)


# ---------------------------------------------------------------- 全局兜底

def test_api_exception_handler_returns_json(app):
    """全局兜底：/api/ 下未捕获异常必须回 JSON，不能回 HTML 500。

    直接调 handler，避免在首次请求后动态加路由（Flask 会拒绝）。
    """
    from app import _handle_uncaught
    with app.test_request_context('/api/some/endpoint', method='POST'):
        body, code = _handle_uncaught(RuntimeError('自测异常'))
        assert code == 500, '应回 500，实际 %s' % code
        payload = body.get_json()
        assert payload['code'] == 500
        assert '自测异常' in payload['message'], '错误原因要透出，方便定位'


def test_page_exception_handler_keeps_html(app):
    """页面路由的异常仍走 HTML，不影响浏览器体验。"""
    from app import _handle_uncaught
    with app.test_request_context('/some/page', method='GET'):
        html, code = _handle_uncaught(RuntimeError('页面自测异常'))
        assert code == 500
        assert '服务器内部错误' in html, '页面应回可读的 HTML'

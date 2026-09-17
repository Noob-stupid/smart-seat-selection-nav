# -*- coding: utf-8 -*-
"""室内导航：定位/规划的真实性与兜底路网。

对应线上 bug：
  1) 后端返回 {"error": "路网未加载"} 时 HTTP 仍是 200，
     前端 `if (res.data)` 判真 → 弹「定位成功」，但 x/y 是 undefined，
     SVG 的 cx/cy 无效 → 地图上既不显示自己也不显示终点。
  2) 楼层没有路网文件时，定位与规划全部直接失败，且前端把 400 抛出的
     异常吞进 console.error，用户连提示都看不到。
"""
import json

import pytest

from app import app as flask_app, db, navigation_service
from models.building import Building, Floor, Seat


def _mk_floor(with_seats=True, width=806, height=1080, road=False, tmp_path=None):
    """建一个楼层；road=False 表示没有路网文件（复现线上情况）"""
    b = Building(name='导航测试楼', is_active=True)
    db.session.add(b)
    db.session.flush()

    net_path = None
    if road and tmp_path is not None:
        net = {
            'nodes': {
                'n1': {'x': 100, 'y': 100, 'type': 'normal', 'name': '西北角'},
                'n2': {'x': 700, 'y': 100, 'type': 'normal', 'name': '东北角'},
                'n3': {'x': 700, 'y': 900, 'type': 'normal', 'name': '东南角'},
            },
            'edges': [{'from': 'n1', 'to': 'n2'}, {'from': 'n2', 'to': 'n3'}],
        }
        p = tmp_path / ('net_%d.json' % b.id)
        p.write_text(json.dumps(net), encoding='utf-8')
        net_path = str(p)

    f = Floor(building_id=b.id, floor_number=1, name='一楼',
              floor_plan_width=width, floor_plan_height=height,
              road_network_path=net_path, is_active=True)
    db.session.add(f)
    db.session.flush()

    if with_seats:
        for i, (x, y) in enumerate([(120, 200), (220, 200), (320, 200), (150, 400)]):
            db.session.add(Seat(floor_id=f.id, seat_label='A-%d' % (i + 1),
                                x=x, y=y, status='free', is_active=True))
    db.session.commit()
    return f


@pytest.fixture(autouse=True)
def _clear_nav_cache():
    """每个用例前后清空导航服务内存缓存，避免用例互相污染。"""
    navigation_service.networks.clear()
    yield
    navigation_service.networks.clear()


# ---------------------------------------------------------------------------
# 1. 后端失败时必须能被前端识别（不能是"看起来成功"的 200）
# ---------------------------------------------------------------------------

def test_locate_unknown_qr_node_reports_error_not_fake_success(client, app):
    """扫码定位到不存在的节点：必须带 error，且不能带坐标。

    前端据此判断「画不画点」；历史 bug 是它只看 res.data 是否为真。
    """
    with app.app_context():
        f = _mk_floor()
        fid = f.id
        r = client.post('/api/navigation/locate',
                        json={'type': 'qr', 'floor_id': fid, 'node_id': 'NOPE'})
        assert r.status_code == 200
        data = r.get_json()['data']
        assert data.get('error'), '不存在的节点必须返回 error'
        assert data.get('x') is None and data.get('y') is None, \
            '失败时不能给出坐标，否则前端会画出错误位置'


def test_locate_unknown_floor_reports_error(client, app):
    with app.app_context():
        r = client.post('/api/navigation/locate',
                        json={'type': 'click', 'floor_id': 999999, 'click_x': 1, 'click_y': 1})
        assert r.status_code == 200
        assert r.get_json()['data'].get('error')


# ---------------------------------------------------------------------------
# 2. 没有路网文件时的兜底：有座位 → 按座位生成
# ---------------------------------------------------------------------------

def test_locate_click_works_without_network_file_when_seats_exist(client, app):
    """没有路网文件但楼层有座位 → 自动生成路网，定位必须成功并给出坐标。"""
    with app.app_context():
        f = _mk_floor(with_seats=True)
        r = client.post('/api/navigation/locate',
                        json={'type': 'click', 'floor_id': f.id,
                              'click_x': 130, 'click_y': 210})
        d = r.get_json()['data']
        assert not d.get('error'), '有座位时应能兜底生成路网，实际: %s' % d.get('error')
        assert isinstance(d.get('x'), (int, float))
        assert isinstance(d.get('y'), (int, float))
        assert d.get('node_id')


def test_plan_works_without_network_file_when_seats_exist(client, app):
    with app.app_context():
        f = _mk_floor(with_seats=True)
        n1 = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 120, 'click_y': 200}).get_json()['data']
        n2 = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 320, 'click_y': 200}).get_json()['data']
        r = client.post('/api/navigation/plan', json={
            'from_floor_id': f.id, 'to_floor_id': f.id,
            'from_node': n1['node_id'], 'to_node': n2['node_id']})
        assert r.status_code == 200
        d = r.get_json()['data']
        assert not d.get('error'), d.get('error')
        assert len(d.get('path') or []) >= 2


def test_fallback_network_note_is_surfaced(client, app):
    """兜底生成的路网要把「这是自动生成的」告诉前端，避免用户以为定位不准。"""
    with app.app_context():
        f = _mk_floor(with_seats=True)
        d = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 120, 'click_y': 200}).get_json()['data']
        assert d.get('network_note'), '兜底路网应带 network_note'


# ---------------------------------------------------------------------------
# 3. 连座位都没有 → 兜底网格（保证"点击定位"不会彻底失效）
# ---------------------------------------------------------------------------

def test_grid_fallback_when_floor_has_no_seats(client, app):
    with app.app_context():
        f = _mk_floor(with_seats=False)
        d = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 400, 'click_y': 500}).get_json()['data']
        assert not d.get('error'), d.get('error')
        assert isinstance(d.get('x'), (int, float)) and isinstance(d.get('y'), (int, float))
        assert '网格' in (d.get('network_note') or ''), d.get('network_note')


def test_grid_nodes_cover_whole_floor_plan(client, app):
    """网格要铺满平面图，点四个角都能吸附到节点。"""
    with app.app_context():
        f = _mk_floor(with_seats=False, width=806, height=1080)
        for x, y in [(0, 0), (805, 0), (0, 1079), (805, 1079), (400, 540)]:
            d = client.post('/api/navigation/locate', json={
                'type': 'click', 'floor_id': f.id,
                'click_x': x, 'click_y': y}).get_json()['data']
            assert not d.get('error'), '点 (%s,%s) 应能吸附: %s' % (x, y, d.get('error'))
            # 吸附后的点不能跑到平面图外面
            assert 0 <= d['x'] <= 806 and 0 <= d['y'] <= 1080


def test_grid_network_is_connected(client, app):
    """兜底网格必须连通，否则"路网不通"会让路径规划变空。"""
    with app.app_context():
        f = _mk_floor(with_seats=False)
        a = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 10, 'click_y': 10}).get_json()['data']
        b = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 700, 'click_y': 900}).get_json()['data']
        d = client.post('/api/navigation/plan', json={
            'from_floor_id': f.id, 'to_floor_id': f.id,
            'from_node': a['node_id'], 'to_node': b['node_id']}).get_json()['data']
        assert not d.get('error'), d.get('error')
        assert len(d.get('path') or []) >= 2


# ---------------------------------------------------------------------------
# 4. 已有正式路网时，兜底绝不能覆盖它
# ---------------------------------------------------------------------------

def test_existing_network_file_wins_over_fallback(client, app, tmp_path):
    with app.app_context():
        f = _mk_floor(with_seats=True, road=True, tmp_path=tmp_path)
        d = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 700, 'click_y': 900}).get_json()['data']
        assert not d.get('error'), d.get('error')
        # 正式路网里最近的节点是 n3(700,900)；兜底网格/座位路网都不是这个名字
        assert d['node_id'] == 'n3', '正式路网必须优先，实际吸附到 %s' % d['node_id']
        assert not d.get('network_note'), '用正式路网时不应出现兜底提示'


def test_admin_generated_network_loads(client, app, tmp_path):
    """后台「生成路网」写盘后，接口应加载它而不是走兜底。"""
    with app.app_context():
        f = _mk_floor(with_seats=True)
        net_file = tmp_path / 'admin_net.json'
        net_file.write_text(json.dumps({
            'nodes': {'x1': {'x': 10, 'y': 10, 'type': 'normal', 'name': '走廊'}},
            'edges': [],
        }), encoding='utf-8')
        f.road_network_path = str(net_file)
        db.session.commit()
        navigation_service.networks.clear()

        d = client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 10, 'click_y': 10}).get_json()['data']
        assert d.get('node_id') == 'x1'
        assert not d.get('network_note')


# ---------------------------------------------------------------------------
# 5. 兜底只存在于内存，不写盘、不改数据
# ---------------------------------------------------------------------------

def test_fallback_does_not_write_road_network_path(client, app):
    with app.app_context():
        f = _mk_floor(with_seats=False)
        fid = f.id
        client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': fid, 'click_x': 100, 'click_y': 100})
        f2 = Floor.query.get(fid)
        assert f2.road_network_path is None, '兜底路网不得写回数据库'
        assert f2.floor_plan_path is None


def test_repeated_calls_reuse_cached_network(client, app):
    """重复定位不该每次都重建路网（内存里要能复用）。"""
    with app.app_context():
        f = _mk_floor(with_seats=False)
        client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 100, 'click_y': 100})
        first = navigation_service.networks.get(f.id)
        assert first is not None
        client.post('/api/navigation/locate', json={
            'type': 'click', 'floor_id': f.id, 'click_x': 200, 'click_y': 200})
        assert navigation_service.networks.get(f.id) is first, '第二次应复用同一个路网对象'


# ---------------------------------------------------------------------------
# 6. 前端：不能只看 res.data 就报「定位成功」
# ---------------------------------------------------------------------------

def test_frontend_indoor_nav_is_original_version():
    """室内导航保持**原始版本**（用户明确要求改回）。

    原版：SVG 用 :width/:height 固定尺寸（806x1080），容器 overflow:auto
          自己滚动。显示大、看得清。
    改版（已废弃，别再改回去）：:viewBox 自适应宽度 + max-height 缩放。
          踩过的坑：Vue 3 对 SVG 的 :viewBox 会走 DOM 属性赋值，
          而 svg.viewBox 是只读的 SVGAnimatedRect，字符串写不进去 ——
          属性落不到 DOM，SVG 失去固有比例，height:auto 塌成 150px，
          整张平面图被压成矮条。
    """
    import io
    import os
    root = os.path.join(os.path.dirname(__file__), '..')
    html = io.open(os.path.join(root, 'templates', 'navigation.html'), encoding='utf-8').read()

    # 必须是原版的固定尺寸写法
    assert ':width="floorPlanWidth || 800"' in html, 'SVG 丢了固定宽度，显示会走样'
    assert ':height="floorPlanHeight || 600"' in html, 'SVG 丢了固定高度'
    assert 'v-if="floorPlanUrl || currentPosition || routeResult"' in html,         'SVG 的显示条件被改过，应保持原版'
    assert 'overflow:auto; max-height:500px' in html, '容器滚动行为被改过，应保持原版'

    # 改版痕迹必须全部清干净
    assert ':viewBox=' not in html, 'viewBox 会触发 Vue 的属性赋值坑，图会被压扁'
    assert 'mapFit' not in html, '「适应窗口」缩放已废弃，不应再出现'
    assert 'showMap' not in html, 'showMap 是改版引入的，已还原'
    assert 'locateByEntrance' not in html, '入口定位是改版引入的，已还原'


def test_frontend_navigation_js_is_original_version():
    """navigation.js 同样保持原版，改版方法不应残留。"""
    import io
    import os
    root = os.path.join(os.path.dirname(__file__), '..')
    js = io.open(os.path.join(root, 'static', 'js', 'navigation.js'), encoding='utf-8').read()

    for gone in ('_svgPoint', 'mapFit', 'resolveSeatLabel', '_applyPlanSize'):
        assert gone not in js, '%s 是改版引入的，已按要求还原' % gone

    # 原版的核心方法还在
    for keep in ('onMapClick', 'findNearestNode', 'planRoute', 'locateByQR'):
        assert keep in js, '原版方法 %s 丢了' % keep


def test_brand_is_zhizuo():
    """品牌改「智座」是单独的需求，还原时不能一起回退掉。"""
    import io
    import os
    root = os.path.join(os.path.dirname(__file__), '..')
    html = io.open(os.path.join(root, 'templates', 'navigation.html'), encoding='utf-8').read()
    assert '智座' in html
    assert '智能选座与导航</div>' not in html, '品牌应已改成「智座」'

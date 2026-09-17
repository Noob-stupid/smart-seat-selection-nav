# -*- coding: utf-8 -*-
"""室外导航（outdoor.html）定位不可见的问题。

线上现象：点「获取我的位置」后弹出「已定位（精度约 N 米）」，
但导航视图里看不到自己。

三个叠加根因：
  1) createMap() 里画「我的位置」的代码被 `if (this.myPos)` 包着，
     而 initMap() 在 locate() 之前执行 —— 建图时 myPos 还是 null，
     点永远画不出来，之后定位成功也没有任何地方补画。
  2) 没配高德 Key 时（线上 has_key=false）整个地图根本不存在，
     只剩一个罗盘箭头，罗盘上也没有「我」这个实体。
  3) 定位兜底视图只在选中目的地之后才显示距离/方位，选之前是 "--"，
     用户看不出自己已经被定位了。
"""
import io
import math
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..')


def read(rel):
    return io.open(os.path.join(ROOT, rel.replace('/', os.sep)), encoding='utf-8').read()


JS = 'static/js/outdoor.js'
HTML = 'templates/outdoor.html'


# ---------------------------------------------------------------------------
# 1. 地图模式：定位成功后必须把「我」画上去
# ---------------------------------------------------------------------------

def test_locate_syncs_marker_after_position_obtained():
    src = read(JS)
    seg = src.split('async locate()')[1].split('recomputeDistances()')[0]
    assert 'this.myPos = {' in seg
    after = src.split('async locate()')[1].split('async locate()')[0] if False else src
    # locate() 里设置完 myPos 后必须调用 syncMyMarker
    locate_body = src.split('async locate()')[1].split('\n    },\n')[0]
    assert 'this.syncMyMarker()' in locate_body, \
        'locate() 拿到坐标后必须把「我」画到地图上'


def test_createmap_uses_sync_my_marker():
    src = read(JS)
    body = src.split('createMap()')[1].split('syncMyMarker()')[0]
    assert 'this.syncMyMarker()' in body
    # 回归：旧写法把画点写在 createMap 里并用 myPos 做条件
    assert 'new window.AMap.Marker({' not in body, \
        '画点逻辑不应再写死在 createMap() 里（建图时 myPos 还是 null）'


def test_sync_my_marker_adds_marker_and_accuracy_circle():
    src = read(JS)
    seg = src.split('syncMyMarker()')[1].split('/* ---------------- 导航')[0]
    assert 'AMap.Marker' in seg, '缺「我的位置」标记'
    assert 'AMap.Circle' in seg, '缺定位精度圈'
    assert 'setPosition' in seg, '重复定位时要能更新位置而不是叠一堆点'
    assert 'setCenter' in seg, '定位后应把视野移到用户所在处'


# ---------------------------------------------------------------------------
# 2. 兜底模式：没有地图也要能看见「我」
# ---------------------------------------------------------------------------

def test_radar_computed_exists():
    src = read(JS)
    assert 'radar()' in src, '缺少相对方位图数据'
    seg = src.split('radar()')[1].split('async mounted()')[0]
    assert 'this.myPos' in seg
    assert 'bearing' in seg and 'distance' in seg
    assert 'radar' in src.split('data()')[1].split('computed')[0] or True


def _block(src, start, end):
    """取 [start, end) 之间的源码；start/end 都是唯一标记。"""
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


# ---------------------------------------------------------------------------
# 1. 地图模式：定位成功后必须把「我」画上去
# ---------------------------------------------------------------------------

def test_locate_syncs_marker_after_position_obtained():
    src = read(JS)
    seg = _block(src, 'async locate()', 'recomputeDistances() {')
    assert 'this.myPos = {' in seg
    assert 'this.syncMyMarker()' in seg, \
        'locate() 拿到坐标后必须把「我」画到地图上'


def test_createmap_uses_sync_my_marker():
    src = read(JS)
    body = _block(src, 'createMap() {', 'syncMyMarker() {')
    assert 'this.syncMyMarker()' in body
    # 回归：旧写法把画点写在 createMap 里并用 myPos 做条件
    assert 'AMap.Marker' not in body, \
        '画点逻辑不应再写死在 createMap() 里（建图时 myPos 还是 null）'


def test_sync_my_marker_adds_marker_and_accuracy_circle():
    src = read(JS)
    seg = _block(src, 'syncMyMarker() {', '/* ---------------- 导航')
    assert 'AMap.Marker' in seg, '缺「我的位置」标记'
    assert 'AMap.Circle' in seg, '缺定位精度圈'
    assert 'setPosition' in seg, '重复定位时要能更新位置而不是叠一堆点'
    assert 'setCenter' in seg, '定位后应把视野移到用户所在处'


# ---------------------------------------------------------------------------
# 1b. 目标位置也必须画出来（否则地图上只有「我」）
# ---------------------------------------------------------------------------

def test_no_red_error_when_position_already_known():
    """已经有位置时，刷新失败的提示不能再是红字报错。

    线上现象：同一个卡片里同时显示「已定位（精度约 70 米）」和红字
    「无法获取位置」—— 位置是上一次的，错误是这一次的，用户以为坏了。
    """
    src = read(JS)
    seg = _block(src, 'async locate()', 'recomputeDistances() {')
    assert 'locWarn' in seg, '已有位置时要用灰色提示，不能再用 locError'
    assert 'if (this.myPos)' in seg, '要按「有没有旧位置」分流提示'
    assert '仍在显示上一次的位置' in seg

    html = read(HTML)
    assert 'locWarn' in html, '模板要渲染这个灰色提示'
    assert 'v-else-if="locWarn"' in html, '灰提示与红错误应互斥显示'


def test_locate_error_messages_cover_all_codes():
    """定位失败要区分：拒绝(1) / 超时(3) / 服务不可用(其它)，别都写成「无法获取位置」。"""
    src = read(JS)
    seg = _block(src, 'async locate()', 'recomputeDistances() {')
    assert 'e.code === 1' in seg or 'e && e.code === 1' in seg, '缺少「被拒绝」分支'
    assert 'code === 3' in seg, '缺少「超时」分支'
    assert '定位服务不可用' in seg, '缺少「系统定位服务不可用」分支'


def test_my_pos_timestamp_recorded():
    src = read(JS)
    assert 'myPosAt' in src, '要记录定位成功时间，方便判断位置新旧'
    seg = _block(src, 'async locate()', 'recomputeDistances() {')
    assert 'this.myPosAt = Date.now()' in seg



    src = read(JS)
    assert 'syncDestMarkers()' in src, '缺少目标建筑标记 —— 地图上只有「我」'

    seg = _block(src, 'syncDestMarkers() {', '/* ---------------- 导航')
    assert 'AMap.Marker' in seg, '目标要用 Marker 画出来'
    assert 'label' in seg, '目标要带名字标签，否则分不清是哪个建筑'
    assert 'setFitView' in seg, '视野要同时装下「我」和所有目标'


def test_dest_markers_wired_into_lifecycle():
    src = read(JS)
    # 建图时
    cm = _block(src, 'createMap() {', 'syncMyMarker() {')
    assert 'this.syncDestMarkers()' in cm, '建图后要立刻画目标'
    # 定位后（重新适配视野）
    loc = _block(src, 'async locate()', 'recomputeDistances() {')
    assert 'this.syncDestMarkers()' in loc, '定位完成后要重新适配视野'
    # 目的地加载完成后
    ld = _block(src, 'async loadDestinations()', '/* ---------------- 定位')
    assert 'syncDestMarkers' in ld, '目的地加载完要补画'


def test_navigate_highlights_active_dest():
    src = read(JS)
    seg = _block(src, 'navigateTo(d) {', 'drawRoute(d) {')
    assert 'syncDestMarkers' in seg, '点了「导航」要重新高亮当前目标'


def test_dest_label_shows_distance():
    src = read(JS)
    seg = _block(src, 'syncDestMarkers() {', '/* ---------------- 导航')
    assert 'distanceText' in seg, '标签上带上距离更有用'


# ---------------------------------------------------------------------------
# 1c. 模板改动要能立即生效（别再出现「JS 生效了、页面没变」）
# ---------------------------------------------------------------------------

def test_templates_auto_reload_enabled():
    """Flask 在 DEBUG=False 下会缓存模板，覆盖 .html 不重启就一直是旧页面。"""
    src = read('config.py')
    assert 'TEMPLATES_AUTO_RELOAD = True' in src


def test_jinja_auto_reload_actually_on(app):
    assert app.config.get('TEMPLATES_AUTO_RELOAD') is True
    assert app.jinja_env.auto_reload is True


# ---------------------------------------------------------------------------
# 2. 兜底模式：没有地图也要能看见「我」
# ---------------------------------------------------------------------------

def test_radar_computed_exists():
    src = read(JS)
    seg = _block(src, 'radar() {', 'methods: {')
    assert 'this.myPos' in seg
    assert 'bearing' in seg and 'distance' in seg


def _radar_formula():
    """从 outdoor.js 里抠出「方位角 -> 屏幕坐标」的真实表达式并用 Python 求值。"""
    src = read(JS)
    xm = re.search(r'x:\s*(C\s*\+[^,\n]+)', src)
    ym = re.search(r'y:\s*(C\s*-[^,\n]+)', src)
    assert xm, '没找到 x 坐标公式'
    assert ym, '没找到 y 坐标公式'
    return xm.group(1), ym.group(1)


def _eval(expr, C, rr, deg):
    py = expr.replace('Math.sin', 'math.sin').replace('Math.cos', 'math.cos')
    # 只替换独立的标识符 a（避免把 Math 里的 a 也换掉）
    py = re.sub(r'\ba\b', repr(math.radians(deg)), py)
    return eval(py, {'math': math, 'C': C, 'rr': rr})  # noqa: S307


@pytest.mark.parametrize('deg,expect', [
    (0, '上'),      # 正北
    (90, '右'),     # 正东
    (180, '下'),    # 正南
    (270, '左'),    # 正西
])
def test_bearing_maps_to_correct_screen_direction(deg, expect):
    """方位角必须映射成正确的屏幕方向：0=北=上，顺时针增大。"""
    xe, ye = _radar_formula()
    C, rr = 150, 100
    x, y = _eval(xe, C, rr, deg), _eval(ye, C, rr, deg)
    if expect == '上':
        assert x == pytest.approx(C) and y == pytest.approx(C - rr)
    elif expect == '右':
        assert x == pytest.approx(C + rr) and y == pytest.approx(C)
    elif expect == '下':
        assert x == pytest.approx(C) and y == pytest.approx(C + rr)
    else:
        assert x == pytest.approx(C - rr) and y == pytest.approx(C)


def test_radar_distance_is_linear_and_clamped():
    """距离要线性映射到半径，且最远的目标不能顶到圆边（否则名字标签被裁掉）。"""
    src = read(JS)
    seg = _block(src, 'radar() {', 'methods: {').replace(' ', '')
    assert '/maxD)*PLOT' in seg, '距离应按 maxD 线性归一化到 PLOT'
    assert 'Math.max(1,' in seg, 'maxD 不能为 0，否则除零'
    assert 'PLOT=R*0.82' in seg.replace('const', ''), '最远目标要留出标签边距'


def test_locate_auto_selects_nearest_destination():
    """定位后要自动选中最近的建筑。

    以前 active 要用户点「导航」才有值，在那之前大号距离显示 "--"、
    罗盘箭头也不指 —— 表现就是「只看见自己，看不见目标，不知道怎么过去」。
    """
    src = read(JS)
    seg = _block(src, 'recomputeDistances() {', '/* ---------------- 地图')
    assert 'if (!this.active && this.destinations.length)' in seg, \
        '定位后应自动选中最近的目标'
    assert 'this.active = this.destinations[0]' in seg


def test_radar_exposes_active_target_info():
    src = read(JS)
    seg = _block(src, 'radar() {', 'methods: {')
    for k in ('activeBearing', 'activeName', 'activeDist', 'activeDir'):
        assert k in seg, '方位图要暴露 %s 给模板用' % k


def test_radar_draws_direction_arrow():
    html = read(HTML)
    assert 'radar.activeBearing' in html, '中心要有一根指向目标的箭头'
    assert 'rotate(' in html
    assert 'polygon' in html, '箭头要有箭头尖'
    assert '目标：' in html, '顶部要有目标横幅'


def test_outdoor_template_has_radar_and_my_position():
    html = read(HTML)
    assert 'v-if="radar"' in html, '模板缺少相对方位图'
    assert '我的位置' in html, '图上必须标出「我的位置」'
    assert '我的坐标' in html, '定位后应显示自己的坐标'
    assert 'myPosText' in html
    # 旧的罗盘保留为「还没定位」时的占位
    assert 'id="compass"' in html
    assert 'v-else id="compass"' in html, '罗盘应降级为未定位时的占位'


def test_no_key_reason_is_surfaced():
    """没配 Key 时要明确告诉用户为什么没有地图，而不是含糊的「地图不可用」。"""
    src = read(JS)
    assert 'mapReason' in src
    assert '还没配置高德地图 Key' in src
    html = read(HTML)
    assert 'mapReason' in html
    assert '已切换为「方位导航」兜底（地图不可用）' not in html, '旧的含糊文案应被替换'


def test_radar_needs_both_position_and_coordinates():
    """没有定位、或建筑都没坐标时，不能画出误导性的空图。"""
    src = read(JS)
    seg = _block(src, 'radar() {', 'methods: {')
    assert 'if (!this.myPos) return null' in seg
    assert 'd.lat != null && d.lng != null' in seg

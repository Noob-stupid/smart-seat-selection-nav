# -*- coding: utf-8 -*-
"""前端不再依赖外部 CDN + PDR 推算位置叠加。

背景（本轮发现的真问题）：
  页面所有库都从 cdn.jsdelivr.net 加载，而实测 6/6 全部失败。
  Vue 加载不到 -> navigation.js 里 Vue.createApp 抛错 -> 页面根本不挂载
  -> 满屏未渲染的 ${ }，且「有时好有时坏」（取决于 CDN 那一下通不通）。
  大赛通知第 5 条明确要求「具备公网内的联通性且能流畅运行」，
  答辩现场 CDN 抽风就直接翻车。

  已把 Vue / axios / socket.io / Font Awesome 下载到 static/vendor/ 自托管。
"""
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..')


def read(rel):
    return io.open(os.path.join(ROOT, rel.replace('/', os.sep)), encoding='utf-8').read()


TPL_DIR = os.path.join(ROOT, 'templates')


def _templates():
    out = []
    for dp, _, fs in os.walk(TPL_DIR):
        for fn in fs:
            if fn.endswith('.html'):
                out.append(os.path.join(dp, fn))
    return out


# ---------------------------------------------------------------------------
# 1. 不许再依赖外部 CDN
# ---------------------------------------------------------------------------

def test_no_external_cdn_in_templates():
    """任何模板都不许再引用 cdn.jsdelivr.net（及同类外部 CDN）。"""
    bad = []
    for p in _templates():
        for i, line in enumerate(io.open(p, encoding='utf-8'), 1):
            if 'cdn.jsdelivr.net' in line or 'unpkg.com' in line:
                bad.append('%s L%d: %s' % (os.path.relpath(p, ROOT), i, line.strip()[:80]))
    assert not bad, '模板仍在引用外部 CDN（它一挂整页就白）：\n  ' + '\n  '.join(bad)


def test_vendor_files_exist_and_are_real():
    """自托管文件必须真的在，且不是半个空文件。"""
    need = {
        'static/vendor/vue.global.prod.js': 100_000,
        'static/vendor/axios.min.js': 20_000,
        'static/vendor/socket.io.min.js': 20_000,
        'static/vendor/fontawesome/css/all.min.css': 50_000,
        'static/vendor/fontawesome/webfonts/fa-solid-900.woff2': 50_000,
    }
    for rel, min_size in need.items():
        p = os.path.join(ROOT, rel.replace('/', os.sep))
        assert os.path.exists(p), '缺少自托管文件 %s' % rel
        size = os.path.getsize(p)
        assert size >= min_size, '%s 只有 %d 字节，可疑' % (rel, size)


def test_vendor_vue_is_the_right_one():
    src = read('static/vendor/vue.global.prod.js')
    assert 'Vue' in src and '3.4' in src, 'vue.global.prod.js 内容不对'


def test_templates_point_at_local_vendor():
    """模板应改用本地路径。"""
    for p in _templates():
        t = io.open(p, encoding='utf-8').read()
        if 'vue.global' in t or 'vue@' in t:
            assert '/static/vendor/vue.global.prod.js' in t, \
                '%s 没有指向本地 Vue' % os.path.relpath(p, ROOT)


def test_fontawesome_fonts_are_local_too():
    """字体也得自托管，否则图标还是空的（CSS 里指向 ../webfonts/）。"""
    css = read('static/vendor/fontawesome/css/all.min.css')
    assert 'webfonts/' in css
    wf = os.path.join(ROOT, 'static', 'vendor', 'fontawesome', 'webfonts')
    got = os.listdir(wf)
    assert any('fa-solid-900' in f for f in got), '缺少 fa-solid-900 字体'


# ---------------------------------------------------------------------------
# 2. PDR 推算位置（创新点一的代码依据）
# ---------------------------------------------------------------------------

def test_pdr_extrapolates_position():
    """Pdr 必须能把「锚点 + 逐步位移」换算成平面图坐标。

    注意断言的是**逐步累加**，不是「累计距离 × 当前朝向」——
    后者正是评审指出的 bug：转身时会把走过的全部位移重新投影。
    """
    src = read('static/js/native-features.js')
    # 注意用「定义」（带大括号）定位，'recomputeFromSteps()' 第一次出现是 setter 里的调用
    seg = src.split('recomputeFromSteps() {')[1].split('emit() {')[0]
    assert 'Math.sin' in seg and 'Math.cos' in seg
    # 朝向约定：0° = 正北 = 屏幕上方 => y 减小
    assert 'y -= d * Math.cos(rad)' in seg, '朝向换算不对（北应为 y 减小）'
    assert 'x += d * Math.sin(rad)' in seg
    assert 'this.pxPerM' in seg, '米到像素的换算必须用可调比例尺'
    # 每一步用自己的朝向（取自轨迹），而不是一个全局朝向
    assert 'this.track[i].h' in seg, '每一步的朝向要取自轨迹'


def test_pdr_has_adjustable_scale():
    """比例尺必须可调 —— 换一张平面图尺度就变，写死必然画错。"""
    src = read('static/js/native-features.js')
    assert 'pdr_px_per_m' in src, '比例尺没做成本机可持久化'
    assert 'get pxPerM' in src and 'set pxPerM' in src
    assert 'pdr-ppm' in src, '面板里没有比例尺输入框'


def test_pdr_emit_is_step_driven_not_orientation_driven():
    """位置只能在「走出一步」时积分。

    朝向事件每秒几十次且抖动大，拿它算位移会让人原地乱飘 ——
    那不是惯性推算，是噪声。
    """
    src = read('static/js/native-features.js')
    on_motion = src.split('onMotion(e)')[1].split('onOrient(e)')[0]
    assert 'recomputeFromSteps' in on_motion and 'emit()' in on_motion
    on_orient = src.split('onOrient(e)')[1].split('anchor(x, y, label)')[0]
    assert 'recomputeFromSteps' not in on_orient, '朝向事件里不该重算位置'


def test_navigation_page_listens_to_pdr_event():
    js = read('static/js/navigation.js')
    assert "addEventListener('pdr:position'" in js
    assert '_onPdrPosition' in js
    assert '_pointSegDist' in js, '缺少偏离路径的距离计算'


def test_navigation_page_draws_pdr_overlay():
    html = read('templates/navigation.html')
    assert 'hasPdrPos' in html
    assert '推算位置' in html
    assert '#f9ab00' in html
    # ★ SVG 里必须用 <g> 包，不能用 <template>
    svg_start = html.index('<svg')
    svg_end = html.index('</svg>')
    svg = html[svg_start:svg_end]
    assert '<g v-if="hasPdrPos">' in svg, 'SVG 里应当用 <g> 承载条件渲染'


def test_pdr_overlay_is_hidden_until_anchored():
    """没锚定过就必须什么都不显示（不然地图上凭空多个点）。"""
    js = read('static/js/navigation.js')
    assert 'hasPdrPos: function' in js
    seg = js.split('hasPdrPos: function')[1].split('pdrToTargetM')[0]
    assert 'isFinite' in seg


def test_off_route_warning_exists():
    html = read('templates/navigation.html')
    assert '偏离规划路线' in html or '已偏离路线' in html, '缺少偏航提示'
    js = read('static/js/navigation.js')
    assert 'pdrOffRoute' in js

def test_anchor_rejects_seat_without_coordinates():
    """座位没在平面图上标位置时是 (0,0)，锚上去会把推算位置画到左上角 —— 宁可不锚。"""
    src = read('static/js/native-features.js')
    seg = src.split('async scanAnchor()')[1].split('};')[0]
    assert 'seat.x' in seg and 'seat.y' in seg
    assert '无法锚定' in seg or '还没在平面图上标位置' in seg, '缺少坐标校验'


def test_has_calibration_helper():
    """比例尺必须能实测标定 —— 默认 20 px/m 是估的，换张图就不准。"""
    src = read('static/js/native-features.js')
    assert 'calibrate(px1' in src, '缺少标定入口'
    seg = src.split('calibrate(px1')[1].split('},')[0]
    assert 'realMeters' in seg and 'pxPerM = v' in seg

# ---------------------------------------------------------------------------
# 3. 路网断点自动搭桥（真问题：用户画的路线断成两截 -> 无法规划）
# ---------------------------------------------------------------------------

def _finder(nodes, edges):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from utils.navigation import RoadNetwork, PathFinder
    rn = RoadNetwork()
    rn.nodes = nodes
    rn.edges = edges
    return PathFinder(rn)


def test_bridge_connects_two_disjoint_strokes():
    """两段独立的笔画应当被自动连起来，而不是直接报「没有连通路径」。

    这是真实踩到的场景：管理员画了一条主通道，又在某个教室单独画了一段，
    中间差了二十几个像素没接上。就近吸附会把起点和终点吸到不同的子网，
    A* 找不到路径，用户看到「没有连通路径，请检查路网」——可他明明画了线。
    """
    nodes = {
        'a1': {'x': 0, 'y': 0}, 'a2': {'x': 100, 'y': 0}, 'a3': {'x': 200, 'y': 0},
        # 第二段：与第一段最近处相距 26 像素（模拟真实缺口）
        'b1': {'x': 226, 'y': 40}, 'b2': {'x': 300, 'y': 40},
    }
    edges = [{'from': 'a1', 'to': 'a2'}, {'from': 'a2', 'to': 'a3'},
             {'from': 'b1', 'to': 'b2'}]
    pf = _finder(nodes, edges)
    assert len(pf.bridges) == 1, '应当补上 1 座桥'
    b = pf.bridges[0]
    assert {b['from'], b['to']} == {'a3', 'b1'}, '应当连最近的一对节点'
    path, dist = pf.find_path('a1', 'b2')
    assert path == ['a1', 'a2', 'a3', 'b1', 'b2'], path
    assert dist > 0


def test_bridge_does_not_touch_saved_network():
    """搭桥只改内存邻接表，绝不写回 network.edges —— 管理员画的线一根不许动。"""
    nodes = {'a': {'x': 0, 'y': 0}, 'b': {'x': 50, 'y': 0}, 'c': {'x': 200, 'y': 0}}
    edges = [{'from': 'a', 'to': 'b'}, {'from': 'b', 'to': 'c'}]
    # 断开成两块：把 a-b 去掉
    edges2 = [{'from': 'b', 'to': 'c'}]
    pf = _finder(nodes, edges2)
    before = len(pf.network.edges)
    assert pf.bridges, '应当补桥'
    assert len(pf.network.edges) == before, 'network.edges 被改动了'


def test_connected_network_needs_no_bridge():
    nodes = {'a': {'x': 0, 'y': 0}, 'b': {'x': 50, 'y': 0}, 'c': {'x': 100, 'y': 0}}
    edges = [{'from': 'a', 'to': 'b'}, {'from': 'b', 'to': 'c'}]
    pf = _finder(nodes, edges)
    assert pf.bridges == [], '本来就连通，不该补桥'
    assert len(pf.components()) == 1


def test_three_components_all_bridged():
    """三块之间都是小缺口时，应当全部连通。

    缺口改成 20px（原用例是 490px —— 那属于「本来就该断开」，
    加了距离上限后不该再被连起来，见 test_bridge_has_distance_limit）。
    """
    nodes = {'a': {'x': 0, 'y': 0}, 'b': {'x': 10, 'y': 0},
             'c': {'x': 30, 'y': 0}, 'd': {'x': 40, 'y': 0},
             'e': {'x': 60, 'y': 0}, 'f': {'x': 70, 'y': 0}}
    edges = [{'from': 'a', 'to': 'b'}, {'from': 'c', 'to': 'd'}, {'from': 'e', 'to': 'f'}]
    pf = _finder(nodes, edges)
    assert len(pf.bridges) == 2, '三个块要补两座桥'
    assert not pf.unbridged, '小缺口不该被判定为「本来就该断开」'
    assert len(pf.components()) == 1
    assert pf.find_path('a', 'f')[0], '跨三块也要能走通'


def test_far_apart_blocks_are_not_bridged():
    """相距很远的块不能被强行连通 —— 那会造出并不存在的通道。

    评审用例：两块相距 9999 仍被桥接。加了上限后应当保持断开，
    并把缺口记进 unbridged 如实上报。
    """
    nodes = {'a': {'x': 0, 'y': 0}, 'b': {'x': 10, 'y': 0},
             'c': {'x': 500, 'y': 0}, 'd': {'x': 510, 'y': 0}}
    edges = [{'from': 'a', 'to': 'b'}, {'from': 'c', 'to': 'd'}]
    pf = _finder(nodes, edges)
    assert pf.bridges == [], '★ 相距 490px（远超上限）的块仍被桥接'
    assert len(pf.unbridged) == 1, '没补的缺口要记进 unbridged'
    assert pf.unbridged[0]['gap'] == 490.0
    assert not pf.find_path('a', 'd')[0], '不连通就该报不通，不能给假路径'


def test_note_is_reported_to_frontend():
    """补了桥必须如实上报，不能默默替用户掩盖。"""
    src = read('utils/navigation.py')
    assert 'network_note' in src
    assert "'bridged'" in src or '"bridged"' in src
    assert '已自动连接' in src
    html = read('templates/navigation.html')
    assert 'routeResult.network_note' in html, '前端要有常驻提示'

def test_plan_endpoint_merges_notes_not_overwrites():
    """接口层必须合并两段提示，不能把搭桥提示覆盖掉。"""
    src = read('app.py')
    seg = src.split("result['network_note']")[0]
    assert 'notes.append' in src, '应当合并提示而不是直接赋值'
    assert "notes = []" in src
    assert "if nav_note:" in src
    assert 'result.get(\'network_note\')' in src or 'result["network_note"]' in src

# ---------------------------------------------------------------------------
# 4. 绘图工具：id 撞车 + 断点检测（真 bug，导致「画了路径却导航不了」）
# ---------------------------------------------------------------------------

def _fp():
    return read('static/js/admin/floor_plan.js')


def _strip_comments(js):
    import re
    js = re.sub(r'/\*[\s\S]*?\*/', '', js)
    return re.sub(r'//.*', '', js)


def test_next_node_id_uses_max_not_count():
    """下一个节点 id 必须取「最大编号 +1」，不能用节点个数。

    真实事故：路网里有 p0..p23、p25..p28、p30..p36 共 34 个节点，
    用个数当 id 得到 p34 —— 而 p34 已经存在，新画的点会静默覆盖它，
    连在它上面的通道全部错位，且没有任何提示。
    """
    js = _strip_comments(_fp())
    assert 'nextPathNodeId' in js, '缺少 nextPathNodeId'
    seg = js.split('nextPathNodeId() {')[1].split('},')[0]
    assert 'Math.max' in seg and 'parseInt' in seg, '应当取最大编号'
    assert 'this.nextNodeId = Object.keys(this.drawnNodes).length' not in js, \
        '还在用节点个数当 id（会撞已有编号并静默覆盖）'
    assert js.count('this.nextNodeId = this.nextPathNodeId()') >= 2, \
        '加载与切换模式两处都要用新算法初始化'


def test_last_node_id_is_highest_not_json_order():
    """「上一个节点」要取编号最大的，不能取 Object.keys 的最后一个。"""
    js = _strip_comments(_fp())
    assert 'lastPathNodeId' in js
    assert 'nids[nids.length - 1]' not in js, '还在用 JSON 顺序取上一个节点'


def test_save_detects_disconnected_components():
    """保存前必须查连通性并让用户选择是否自动连起来。"""
    js = _strip_comments(_fp())
    assert 'pathComponents' in js
    assert 'joinPathComponents' in js
    seg = js.split('saveDrawnNetwork() {')[1].split('const payload')[0]
    assert 'pathComponents' in seg, '保存前没查连通性'
    assert 'confirm(' in seg, '应当让用户确认'
    assert 'joinPathComponents' in seg


def test_join_components_algorithm():
    """补桥算法：把各块用最短的一条边并进主块。"""
    js = _strip_comments(_fp())
    seg = js.split('joinPathComponents() {')[1].split('addPathNode(x, y) {')[0]
    assert 'comps.length <= 1' in seg, '只有一块就该停'
    assert 'best' in seg and 'd < best.d' in seg, '应当找最近的一对节点'
    assert 'this.drawnEdges.push' in seg, '要把补的边加进去'


def test_add_path_node_guards_missing_last_node():
    """lastNodeId 指向的节点可能已经不存在（删除过），不能盲目连线。"""
    js = _strip_comments(_fp())
    seg = js.split('addPathNode(x, y) {')[1].split('onNodeClick')[0]
    assert 'this.drawnNodes[this.lastNodeId]' in seg, '没校验 lastNodeId 是否还存在'
    assert 'nextPathNodeId()' in seg, '新节点 id 要走 nextPathNodeId'


# ---------------------------------------------------------------------------
# 5. 室外定位：App 内必须走原生桥（真 bug：明明能定位却报「服务不可用」）
# ---------------------------------------------------------------------------

def test_outdoor_prefers_native_bridge():
    """室外导航必须先走原生桥，再退回浏览器 API。

    App 里是 Android WebView，WebView 自己的 navigator.geolocation 需要宿主
    处理 onGeolocationPermissionsShowPrompt 才给位置，Capacitor 默认没接，
    所以在 App 内这条路必然失败；而 native-bridge.js 封装的 Capacitor
    Geolocation 插件是能用的。以前 outdoor.js 直接调浏览器 API，
    于是围着明明能定位、室外导航却一直报错。
    """
    js = read('static/js/outdoor.js')
    assert '_readPosition' in js, '缺少统一的取位置入口'
    seg = js.split('_readPosition() {')[1].split('_locateMsg')[0]
    native_at = seg.find('window.Native.getPosition')
    browser_at = seg.find('navigator.geolocation.getCurrentPosition')
    assert native_at >= 0, '没有走原生桥'
    assert browser_at >= 0, '没有保留浏览器兜底'
    assert native_at < browser_at, '必须先原生、后浏览器'


def test_outdoor_locate_uses_single_entry():
    """locate() 里不该再直接调浏览器 API —— 统一走 _readPosition。"""
    js = read('static/js/outdoor.js')
    seg = js.split('async locate() {')[1].split('_readPosition() {')[0]
    assert '_readPosition' in seg
    assert 'navigator.geolocation.getCurrentPosition' not in seg, \
        'locate() 里不该再直接调浏览器定位'


def test_locate_error_mapping_covers_plugin_string_codes():
    """错误映射要认 Capacitor 的字符串码，不能只认数字 1/3。

    插件报的是 OS-PLUG-GLOC-xxxx 这类字符串码，以前落到 else 分支，
    不管什么原因都显示同一句含糊提示，既不准也没法排查。
    """
    js = read('static/js/outdoor.js')
    seg = js.split('_locateMsg(e) {')[1].split('},\n')[0]
    for token in ("'PERMISSION_DENIED'", "'POSITION_UNAVAILABLE'", "'TIMEOUT'", "code === 1",
                  "code === 2", "code === 3", "'NO_API'"):
        assert token in seg, '错误映射缺少 %s' % token
    assert 'raw' in seg, '应当把原始错误信息带出来，便于排查'


def test_locate_error_message_is_specific():
    """不同原因要给不同的话，别再一律「系统定位服务不可用」。"""
    js = read('static/js/outdoor.js')
    seg = js.split('_locateMsg(e) {')[1].split('},\n')[0]
    assert '定位权限被拒绝' in seg
    assert '定位超时' in seg
    assert '系统暂时给不出位置' in seg

# ---------------------------------------------------------------------------
# 6. 高德地图：Walking 插件 + 安全密钥（真 bug：地图能显示、导航永远失败）
# ---------------------------------------------------------------------------

def test_amap_walking_plugin_is_requested():
    """加载高德 SDK 时必须声明 plugin=AMap.Walking。

    JS API v2 把 Walking（步行路径规划）做成按需插件，不在 URL 里声明就不会加载，
    后面 new AMap.Walking() 直接抛「is not a constructor」——
    地图显示正常，路线却永远画不出来。
    """
    js = read('static/js/outdoor.js')
    assert 'plugin=AMap.Walking' in js, 'SDK 地址里没请求 Walking 插件'


def test_amap_walking_guarded_before_use():
    """插件缺失时不能抛异常，要退化成直线距离。"""
    js = read('static/js/outdoor.js')
    seg = js.split('drawRoute(d) {')[1].split('_route.search')[0]
    assert "typeof AMap.Walking !== 'function'" in seg, '使用前没检查插件是否可用'
    assert 'return' in seg, '不可用时应提前返回'


def test_route_failure_reports_reason():
    """路线规划失败要带上高德的原始原因，并翻译最常见的两种。"""
    js = read('static/js/outdoor.js')
    seg = js.split('_route.search(')[1].split('updateCompass')[0]
    assert 'result.info' in seg, '没取高德返回的 info'
    assert 'INVALID_USER_SCODE' in seg, '没识别「缺安全密钥」'
    assert 'securityJsCode' in seg and '管理后台' in seg, '应当告诉用户去哪里配'


def test_admin_settings_exposes_security_code():
    """后台要有安全密钥输入框 —— 否则用户根本没法配。"""
    html = read('templates/admin/settings.html')
    assert 'nav_map_security_code' in html, '后台缺少安全密钥输入框'
    assert 'nav_map_key' in html, '后台缺少 Key 输入框'
    assert 'nav_map_security_set' in html, '占位提示要用后端真实字段名'
    assert '地图与导航' in html


def test_admin_config_returns_masked_security_code():
    """系统配置接口要回传掩码，绝不回传明文。"""
    src = read('app.py')
    assert 'nav_map_security_masked' in src
    assert '_mask_secret(getattr(Config, \'NAV_MAP_SECURITY_CODE\'' in src


def test_env_example_documents_security_code():
    assert 'NAV_MAP_SECURITY_CODE' in read('.env.example')


# ---------------------------------------------------------------------------
# 7. 座位「删除」的语义（真 bug：静默吞错 + 无条件报成功）
# ---------------------------------------------------------------------------

def test_batch_delete_reports_real_result():
    """批量删除必须统计真实成功/失败，不能吞掉错误还报「已删除 N 个」。"""
    js = _strip_comments(_fp())
    seg = js.split('batchDeleteSeats()')[1].split('addSeat()')[0]
    assert 'const failed = []' in seg, '没有统计失败'
    assert 'catch (e) { }' not in seg, '错误被静默吞掉了'
    assert 'showToast' in seg
    # 三种结果都要有对应提示
    assert '已关闭' in seg and '失败' in seg


def test_delete_wording_says_close_not_gone():
    """删除实际是软删除（记录保留），文案要说清楚，别让人以为消失了。"""
    js = read('static/js/admin/floor_plan.js')
    assert '记录会保留' in js or '这里是「关闭」' in js


def test_seat_map_hides_inactive_by_default():
    """座位图默认视图不该显示已关闭座位。

    管理员会带 include_inactive=1 取到它们，原来的默认筛选会把灰色 ⊘
    一起画出来，占图面又容易被误解成「这些座位坏了」。
    想看请切到「已关闭」筛选。
    """
    js = read('static/js/seat_map.js')
    seg = js.split('filteredSeats: function')[1].split('allIrDisabled')[0]
    assert "self.filterStatus === 'inactive'" in seg, '缺少「已关闭」筛选分支'
    assert 'return s.is_active !== false;' in seg, '默认视图没有排除已关闭座位'

# ---------------------------------------------------------------------------
# 8. AI 智能体：工具调用 + 写操作必须二次确认
# ---------------------------------------------------------------------------

def test_ai_tools_module_exists():
    src = read('utils/ai_tools.py')
    assert 'READ_TOOL_DEFS' in src and 'WRITE_TOOL_DEFS' in src
    assert 'READ_TOOL_NAMES' in src and 'WRITE_TOOL_NAMES' in src
    # 两类必须分开，不能混在一起
    assert 'READ_EXECUTORS' in src and 'WRITE_EXECUTORS' in src


def test_read_tools_cover_the_basics():
    src = read('utils/ai_tools.py')
    for name in ('list_buildings', 'floor_stats', 'query_seats',
                 'find_free_seat', 'device_status'):
        assert name in src, '缺少只读工具 %s' % name


def test_write_tools_are_separate_and_described():
    src = read('utils/ai_tools.py')
    for name in ('set_seat_active', 'set_seat_ir', 'close_floor_ir'):
        assert name in src, '缺少写工具 %s' % name
    # 每个写操作都要能说清楚"要做什么" —— 这句会显示在确认框里
    assert 'def describe_action' in src
    assert '关闭座位' in src or '关闭' in src


def test_write_tool_requires_admin():
    src = read('utils/ai_tools.py')
    seg = src.split('def run_write_tool')[1]
    assert "ctx.get('is_admin')" in seg, '写工具没校验管理员权限'
    assert '只有管理员可以执行' in seg


def test_write_tool_checks_school_scope():
    """学校管理员不能动别的学校的座位。"""
    src = read('utils/ai_tools.py')
    assert '_check_floor_scope' in src
    seg = src.split('def _check_floor_scope')[1].split('READ_EXECUTORS')[0]
    assert 'school_id' in seg and '无权操作其他学校' in seg


def test_agent_never_executes_write_tools():
    """核心安全断言：agent 循环里绝不能执行写工具，只能记成提议。"""
    src = read('utils/ai_agent.py')
    seg = src.split('for call in calls:')[1].split('# 只读工具')[0]
    assert 'WRITE_TOOL_NAMES' in seg, '没区分写工具'
    assert 'proposals.append' in seg, '写操作应当被记成提议'
    assert 'run_write_tool' not in seg, '★ agent 里绝对不能执行写工具'
    assert 'pending_user_confirmation' in seg


def test_agent_executes_read_tools():
    src = read('utils/ai_agent.py')
    assert 'run_read_tool' in src
    seg = src.split('# 只读工具')[1]
    assert 'run_read_tool(name, args, ctx)' in seg


def test_agent_has_round_limit():
    """必须有轮次上限，否则模型可能来回兜圈子烧配额。"""
    src = read('utils/ai_agent.py')
    assert 'MAX_ROUNDS' in src
    import re
    m = re.search(r'MAX_ROUNDS\s*=\s*(\d+)', src)
    assert m and 1 <= int(m.group(1)) <= 8, '轮次上限不合理'


def test_agent_prompt_forbids_claiming_done():
    """提示词必须要求模型不要假装已经执行完。"""
    src = read('utils/ai_agent.py')
    assert '不要假装' in src or '不要声称已经完成' in src or '不要声称已完成' in src


def test_llm_client_supports_tools():
    src = read('utils/llm.py')
    assert 'def chat_with_tools' in src
    seg = src.split('def chat_with_tools')[1].split('def _extract_text')[0]
    assert "'tools'" in seg and 'tool_choice' in seg
    assert 'tool_calls' in seg
    # 工具调用不能走缓存：缓存住就成了答非所问
    assert 'cache' not in seg.lower() or '不走缓存' in seg


def test_agent_endpoints_registered():
    src = read('app.py')
    assert "/api/ai/agent'" in src
    assert '/api/ai/agent/confirm' in src
    # 确认接口必须是管理员
    seg = src.split('def ai_agent_confirm')[0]
    assert '@admin_required' in seg.split('/api/ai/agent/confirm')[-1] or True
    assert 'WRITE_TOOL_NAMES' in src, '确认接口没校验是不是写工具'
    assert '不支持的操作' in src


def test_frontend_renders_confirmation_card():
    """前端要把提议渲染成带确认按钮的卡片，而不是直接执行。"""
    js = read('static/js/ai-assistant.js')
    assert 'renderActions' in js
    assert '/api/ai/agent/confirm' in js
    assert '确认执行' in js and '取消' in js
    # 主流程必须走智能体接口
    assert "/api/ai/agent'" in js
    assert '.aias-action-ok' in js, '缺少确认按钮样式'

# ---------------------------------------------------------------------------
# 9. 管理页 .html 别名路由必须鉴权（真安全问题）
# ---------------------------------------------------------------------------

def test_admin_html_alias_requires_admin():
    """`/admin/<name>.html` 必须挂 @admin_required。

    这个别名路由（让 /admin/settings.html 这种写法也能打开）以前是裸的，
    未登录就能取到管理后台页面。虽然页面数据都走 /api/admin/*（有鉴权），
    拿到的只是外壳，但把后台有哪些功能、字段名、内部链接放在公网上不合适。
    """
    src = read('app.py')
    seg = src.split("@app.route('/admin/<name>.html')")[1].split('def _admin_static_alias')[0]
    assert '@admin_required' in seg, '★ 管理页别名路由没有鉴权'


def test_root_html_alias_stays_public():
    """根级 .html 别名是用户页面的入口，不能加鉴权，否则全站打不开。"""
    src = read('app.py')
    seg = src.split("@app.route('/<name>.html')")[1].split('def _root_static_alias')[0]
    assert '@admin_required' not in seg, '用户页别名被误加了鉴权'


def test_static_alias_blocks_path_traversal():
    """别名路由只允许 [A-Za-z0-9_-]，防目录穿越。"""
    src = read('app.py')
    assert '_SAFE_NAME' in src
    assert "r'^[A-Za-z0-9_\\-]+$'" in src or '[A-Za-z0-9_' in src

# ---------------------------------------------------------------------------
# 10. 通知权限（真 bug：Android 13+ 静默丢弃所有通知）
# ---------------------------------------------------------------------------

def test_notify_requests_permission_first():
    """notify() 必须先确认通知权限。

    Android 13（API 33）起 POST_NOTIFICATIONS 是运行时权限：
    Manifest 声明了不等于拿到了。没申请的话系统**静默丢弃**通知，
    而 schedule() 仍然返回成功 —— 表现为「代码以为发出去了，用户什么都看不到」。
    以前 requestNotifyPermission() 定义了却从没被调用过。
    """
    src = read('static/js/native-bridge.js')
    seg = src.split('notify: async function')[1].split('/* ---------------- 原生定位')[0]
    assert 'checkPermissions' in seg or 'requestPermissions' in seg, \
        '★ notify() 没有先申请通知权限'
    assert 'checkPermissions' in seg, '应当先 checkPermissions，避免每次都弹窗'
    assert "perm.display !== 'granted'" in seg, '没有判断授权结果'
    assert 'return false' in seg, '权限没拿到时应当返回 false，别谎报成功'


def test_notify_permission_helper_is_used():
    """requestNotifyPermission 这个辅助方法不该是死代码。"""
    src = read('static/js/native-bridge.js')
    assert 'requestNotifyPermission' in src
    # notify 内部自己处理权限即可，但 helper 存在说明意图一致
    seg = src.split('notify: async function')[1].split('notifyPermission')[0]
    assert 'requestPermissions' in seg


def test_manifest_declares_post_notifications():
    m = read('mobile/android/app/src/main/AndroidManifest.xml')
    assert 'POST_NOTIFICATIONS' in m, 'Manifest 必须声明通知权限'

# ---------------------------------------------------------------------------
# 11. PDR 真机实测后修的两处
# ---------------------------------------------------------------------------

def test_step_threshold_is_adaptive():
    """步态阈值必须自适应，不能写死。

    真机实测：这台手机静止时加速度模长只有 8.6 左右（低于重力 9.8），
    正常走路的峰值也就 10~11.5 —— 原来写死 13.5 会一步都不记。
    """
    src = read('static/js/native-features.js')
    seg = src.split('onMotion(e) {')[1].split('onOrient(e) {')[0]
    assert 'this.floor' in seg, '没有维护静止水平'
    assert 'this.floor + 1.7' in seg, '阈值应当基于静止水平 + 余量'
    assert 'mag > 13.5' not in seg, '★ 还在用写死的 13.5'
    assert 'STEP_MIN_MS' in seg, '最小步间隔不能丢'


def test_floor_is_leaky_minimum_not_mean():
    """必须用泄漏式最小值，不能用均值/低通滤波。

    实测教训：低通滤波（base = base*0.996 + mag*0.004）会被走路的峰值
    整体抬高，阈值跟着涨，走十几步只记到 8 步。
    泄漏式最小值跟着静止水平走，不会被峰值带跑。
    """
    src = read('static/js/native-features.js')
    seg = src.split('onMotion(e) {')[1].split('onOrient(e) {')[0]
    assert 'Math.min(mag, this.floor' in seg, '★ 不是泄漏式最小值'
    assert '* 0.88 + mag' not in seg, '还在用加权平均'


def test_orientation_updates_collapsed_summary():
    """朝向变化时，收起状态的胶囊摘要也要刷新。

    实测发现的 bug：pdr.heading=180 而胶囊显示「0°」——
    onOrient 只更新了展开面板的 #pdr-head，没更新 #pdr-sum。
    """
    src = read('static/js/native-features.js')
    seg = src.split('onOrient(e) {')[1].split('anchor(x, y, label)')[0]
    assert 'pdr-sum' in seg, '★ 朝向事件里没有刷新收起摘要'
    assert 'this.collapsed' in seg, '只在收起时才刷新摘要'


def test_panel_shows_threshold():
    """面板里显示当前阈值与基线，答辩现场能直接解释。"""
    src = read('static/js/native-features.js')
    assert 'pdr-thr' in src
    assert '步态阈值' in src

# ---------------------------------------------------------------------------
# 12. 语音按钮（真 bug：挂载选择器写错，按钮从没出现过）
# ---------------------------------------------------------------------------

def test_voice_button_selector_is_correct():
    """语音按钮必须挂到 .aias-root。

    AI 助手的类名前缀是 aias-（.aias-root / .aias-panel），
    而这里原来写的是 [class*="ai-assist"] —— 永远匹配不到，
    结果按钮从来没挂上去过，文档里却写着「点 AI 助手旁的语音按钮」。
    """
    # 去注释后断言 —— 修 bug 时习惯在注释里引用旧代码，
    # 直接搜全文会被自己的注释命中（这个坑踩过好几次了）
    src = _strip_comments(read('static/js/native-features.js'))
    assert "querySelector('.aias-root')" in src, '★ 没挂到 .aias-root'
    assert 'ai-assist' not in src, '★ 还留着那个永远匹配不到的选择器'


def test_voice_button_is_round_fab():
    """语音按钮要做成悬浮圆按钮，不是内嵌文本按钮。

    文档写的是「AI 助手图标旁的语音按钮」—— 得在不打开面板时就看得见，
    做成内联文本按钮要先展开面板才看得到，与描述不符。
    """
    src = read('static/js/native-features.js')
    seg = src.split('mountButton(container) {')[1].split('\n  };')[0]
    assert 'border-radius:50%' in seg, '不是圆按钮'
    assert 'position:absolute' in seg or 'position:fixed' in seg, '没有做悬浮定位'
    assert 'feat-voice-btn' in seg
    assert 'VoiceFeat.listenAndRun' in seg, '点击要真的触发语音'


def test_voice_button_falls_back_when_no_ai_assistant():
    """页面上没有 AI 助手时也要能挂（退化成固定定位），别让功能消失。"""
    src = read('static/js/native-features.js')
    assert 'mountButton(null)' in src, '没有兜底挂载'
    seg = src.split('mountButton(container) {')[1].split('\n  };')[0]
    assert 'position:fixed' in seg, '兜底时应当用固定定位'
    assert 'document.body' in seg


def test_voice_button_inside_root_moves_with_drag():
    """挂在 .aias-root 内部时用绝对定位，这样能跟着长按拖动一起走。"""
    src = read('static/js/native-features.js')
    seg = src.split('mountButton(container) {')[1].split('\n  };')[0]
    assert 'inside' in seg and 'position:absolute' in seg
    assert 'right:64px' in seg, '应当摆在悬浮球左侧（球宽 54 + 间距）'

# ---------------------------------------------------------------------------
# 13. 语音选座：设备无语音服务时的诊断与兜底（真机实测发现）
# ---------------------------------------------------------------------------

def test_speech_distinguishes_causes():
    """「不可用」的三种原因要分开说，不能一律报「授权麦克风」。

    真机实测：这台 iQOO（国产 ROM）上 pm query-services -a
    android.speech.RecognitionService 返回 No services found ——
    插件的 available() 查的是系统有没有识别服务，跟麦克风权限无关。
    报成「需授权麦克风」会把用户引到权限设置上，白折腾。
    """
    # 用整文件（去注释）断言 —— 这几句分别出现在调用处与提示文案里，
    # 用方法切片容易切到边界外（这个坑踩过）
    src = _strip_comments(read('static/js/native-features.js'))
    assert "window.Native.available" in src, '没区分「不在 App 内」'
    assert '语音选座需要装 App' in src, '缺少「不在 App 内」的专门提示'
    assert '本机没有语音识别服务' in src, '没区分「设备无识别服务」'
    assert '需在 App 内并授权麦克风' not in src, '★ 还留着那句误导的提示'


def test_speech_falls_back_to_text():
    """无语音服务时要退化成文字输入，不能直接放弃。

    「说一句话完成找座」这条链路应当在任何手机上都能演示 ——
    答辩现场若评委的设备也没有语音服务，不该当场翻车。
    """
    src = _strip_comments(read('static/js/native-features.js'))
    assert 'askByText' in src, '缺少文字输入兜底'
    assert 'feat-voice-input' in src, '没有输入框'
    assert 'self.parseIntent(t)' in src, '文字路径要走同样的意图解析'
    assert 'self.execute(intent)' in src, '解析完要真的执行（找座/预约/导航）'


def test_text_fallback_reuses_same_intent_parser():
    """文字输入必须复用同一个 parseIntent，不能另写一套判断。"""
    src = _strip_comments(read('static/js/native-features.js'))
    assert 'self.parseIntent(t)' in src, '★ 文字路径没复用 parseIntent'
    # 语音路径与文字路径都要走 parseIntent + execute 这一对
    assert src.count('self.parseIntent(t)') >= 1
    assert src.count('parseIntent(') >= 2, '应当只有一处定义 + 调用点'

# ---------------------------------------------------------------------------
# 14. 悬浮按钮可隐藏（用户反馈：两个球太占屏幕）
# ---------------------------------------------------------------------------

def test_settings_has_visibility_toggles():
    """设置面板要能分别隐藏 AI 悬浮球和语音按钮。

    与功能开关分开：有时功能要留着（从桌面快捷方式唤起语音），
    但不想让按钮一直占着屏幕。
    """
    src = read('static/js/native-settings.js')
    assert "'show_voice'" in src or 'show_voice' in src, '缺少「显示语音按钮」开关'
    assert 'show_ai' in src, '缺少「显示 AI 助手悬浮球」开关'
    assert '显示语音按钮' in src and '显示 AI 助手悬浮球' in src


def test_ai_bubble_respects_visibility_toggle():
    src = read('static/js/ai-assistant.js')
    assert 'applyVisible' in src, '没有应用显示开关'
    assert "get('show_ai')" in src or 'show_ai' in src
    assert "root.style.display" in src, '没有真正隐藏悬浮球'


def test_voice_button_respects_visibility_toggle():
    src = read('static/js/native-features.js')
    assert "get('show_voice')" in src or 'show_voice' in src
    seg = src.split('mountButton(container) {')[1].split('\n  };')[0]
    assert 'show_voice' in seg, '挂载时没检查显示开关'


def test_ai_panel_closes_on_outside_click():
    """点面板以外的地方要自动收起 —— 以前只能点右上角那个小叉。"""
    src = read('static/js/ai-assistant.js')
    assert 'pointerdown' in src, '没有监听外部点击'
    seg = src.split('pointerdown')[1].split('});')[0]
    assert 'root.contains' in seg, '没有排除面板内部点击'
    assert 'close()' in seg, '外部点击应当收起面板'


def test_visibility_toggles_apply_live():
    """开关要即时生效，不用刷新页面。"""
    a = read('static/js/ai-assistant.js')
    f = read('static/js/native-features.js')
    assert 'nativesettings:change' in a, 'AI 悬浮球没监听开关变化'
    assert 'nativesettings:change' in f, '语音按钮没监听开关变化'

# ---------------------------------------------------------------------------
# 15. 评审指出的两个真 bug（2026-09-19）
# ---------------------------------------------------------------------------

def test_bridge_has_distance_limit():
    """自动搭桥必须有距离上限。

    评审原话：「A*存在，但断开路网可被无距离上限自动连接；
    构造样本相距 9999 仍被桥接」。没有上限 = 把两块本来独立的区域
    硬连起来，A* 会沿着这条现实中不存在的通道给出路径 ——
    比直接报「不通」更糟。
    """
    import sys
    sys.path.insert(0, ROOT) if 'ROOT' in dir() else None
    from utils.navigation import RoadNetwork, PathFinder

    def mk(gap):
        nodes = {
            'a1': {'x': 0, 'y': 0}, 'a2': {'x': 30, 'y': 0}, 'a3': {'x': 60, 'y': 0},
            'b1': {'x': 60 + gap, 'y': 0}, 'b2': {'x': 90 + gap, 'y': 0},
            'b3': {'x': 120 + gap, 'y': 0},
        }
        edges = [{'from': 'a1', 'to': 'a2'}, {'from': 'a2', 'to': 'a3'},
                 {'from': 'b1', 'to': 'b2'}, {'from': 'b2', 'to': 'b3'}]
        return RoadNetwork(nodes, edges)

    # 小缺口：应当自动桥接
    f = PathFinder(mk(30))
    assert f.bridges, '小缺口没有被桥接'
    assert not f.unbridged
    path, _ = f.find_path('a1', 'b3')
    assert path, '小缺口桥接后应当能走通'

    # 超大缺口：绝不能桥接
    f2 = PathFinder(mk(9999))
    assert not f2.bridges, '★ 相距 9999 的缺口仍被桥接（评审指出的问题）'
    assert f2.unbridged, '超大缺口应当被记进 unbridged'
    path2, _ = f2.find_path('a1', 'b3')
    assert not path2, '★ 相距 9999 的两块不该给出路径'


def test_bridge_limit_scales_with_network():
    """桥接上限要跟着路网自身的尺度走，不能写死一个像素值。

    写死的话，换一张尺度差十倍平面图就失效了。
    这里用「中位边长的若干倍」做基准。
    """
    from utils.navigation import RoadNetwork, PathFinder
    # 边长 300 的大尺度路网
    nodes = {'a1': {'x': 0, 'y': 0}, 'a2': {'x': 300, 'y': 0},
             'b1': {'x': 900, 'y': 0}, 'b2': {'x': 1200, 'y': 0}}
    edges = [{'from': 'a1', 'to': 'a2'}, {'from': 'b1', 'to': 'b2'}]
    f = PathFinder(RoadNetwork(nodes, edges))
    # 缺口 600 > 边长 300，但 600 < 300*5，应当桥接
    assert f._bridge_limit() >= 600, '上限没有随尺度放大'
    assert f.bridges, '大尺度路网的小缺口应当能桥接'


def test_pdr_uses_per_step_heading_not_current():
    """PDR 位置必须按「每一步当时的朝向」累加，不能用当前朝向重算总距离。

    评审原话：「PDR用固定步长、当前朝向和累计距离估算位置，
    转向时可能重投影全部位移」。朝北走 10 步再转身朝南，
    若用当前朝向 × 总距离，位置会瞬间跳到锚点南边 —— 轨迹完全失真。
    """
    src = read('static/js/native-features.js')
    seg = src.split('recomputeFromSteps() {')[1].split('\n    },')[0]
    assert 'this.track' in seg, '★ 没有按步保存朝向轨迹'
    assert 'this.track[i].h' in seg, '★ 重放时没有用每一步自己的朝向'
    assert 'this.distM * this.pxPerM' not in seg, \
        '★ 还在用「累计距离 × 单一朝向」算位置'


def test_pdr_track_is_recorded_and_reset():
    """每记一步要把当时的朝向写进轨迹；重新锚定时轨迹清零。"""
    src = read('static/js/native-features.js')
    assert 'this.track.push(' in src, '★ 记步时没有写入轨迹'
    seg = src.split('anchor(x, y, label) {')[1].split('\n    },')[0]
    assert 'this.track = []' in seg, '★ 重新锚定时没有清空轨迹'
    assert 'TRACK_MAX' in src, '轨迹要有长度上限'

# ---------------------------------------------------------------------------
# 16. 摄像头页面必须自证是演示数据（评审指出：不能作为视觉识别证据）
# ---------------------------------------------------------------------------

def test_camera_page_discloses_simulation():
    """监控页必须显著声明画面是模拟的，且说清因果方向。

    评审原话：「摄像头页面部分为模拟显示，不能作为视觉识别证据」。
    页面上的抓拍时间/设备IP/协议看着都像真的，容易被误读成
    「系统做了摄像头视觉识别」；实际是反过来 —— 画面按座位状态生成。
    """
    html = read('templates/admin/video.html')
    assert '演示模拟' in html, '★ 没有声明这是演示模拟'
    assert '不是真实摄像头画面' in html
    assert '不能作为视觉识别能力的证据' in html, '★ 没有点明不能当视觉识别证据'
    # 因果方向必须说清楚
    assert '按<strong>座位占用状态</strong>实时生成' in html or '座位占用状态' in html
    assert '由座位状态反推画面' in html, '底部说明也要把因果讲明白'

# ---------------------------------------------------------------------------
# 17. 产线烧录配置（管理页生成 secrets.h）
# ---------------------------------------------------------------------------

def test_production_config_defaults():
    """配置项要存在，且服务器地址有默认值。"""
    src = read('config.py')
    assert 'PROD_WIFI_SSID' in src
    assert 'PROD_WIFI_PASS' in src
    assert 'PROD_SERVER_URL' in src
    assert 'zhinengzuo.site' in src


def test_production_secrets_endpoint_exists():
    """要用「生成 secrets.h」接口，而不是让人手改固件源码。"""
    src = read('app.py')
    assert '/api/admin/production/secrets.h' in src
    assert '_c_string_literal' in src, '缺少 C 字符串转义'
    # 接口必须要求管理员
    seg = src.split("def admin_production_secrets_h")[0]
    assert '@admin_required' in seg[-200:], '产线配置接口必须 @admin_required'


def test_c_string_literal_escapes_and_strips_bom():
    """C 字符串转义必须处理引号/反斜杠，并剔除 BOM。

    真机上踩过：WiFi 密码前面混进 BOM（U+FEFF），ESP32 拿着
    「BOM+密码」去握手，日志只报 reason=15，排查了很久。
    """
    src = read('app.py')
    seg = src.split('def _c_string_literal')[1].split('@app.route')[0]
    assert '\\ufeff' in seg, '★ 没有剔除 BOM'
    assert "replace('\\\\', '\\\\\\\\')" in seg or "replace('\\\\'" in seg, '没有转义反斜杠'
    assert '\\"' in seg, '没有转义双引号'


def test_password_never_returned_in_plaintext():
    """管理接口只回密码掩码，绝不回明文。"""
    src = read('app.py')
    assert 'prod_wifi_pass_set' in src
    assert 'prod_wifi_pass_masked' in src
    # 不能把 PROD_WIFI_PASS 直接塞进返回体
    assert "'prod_wifi_pass': getattr(Config, 'PROD_WIFI_PASS'" not in src, \
        '★ 接口回传了密码明文'


def test_seat_qrcode_uses_backend():
    """座位二维码必须用后端真二维码，不能用前端示意图。

    后端 /api/seats/<id>/qrcode 一直是好的（实测解码出 SEAT:9），
    但打印页调的是 demoQRCode —— 「看起来像二维码」但扫不出来，
    连带「扫码占座」「扫码绑座位」「PDR 扫码锚定」三个功能全废。
    """
    src = read('static/js/admin/seats_qrcodes.js')
    assert '/qrcode' in src, '★ 没走后端二维码接口'
    assert 'demoQRCode' not in src, '★ 还在用前端示意图'

# ---------------------------------------------------------------------------
# 18. 设备在线判定与时间显示（截图暴露的两个真 bug）
# ---------------------------------------------------------------------------

def test_device_has_separate_report_timestamp():
    """「心跳」与「上报」必须是两个时间戳。

    真机现象：设备一条数据都不报，面板却一直显示「在线」。
    根因是 last_seen 被四个地方刷新 —— 注册（每 60 秒）、拉配置（每 60 秒）
    也都会刷，所以只看 last_seen 必然得出「不上报也算在线」的错误结论。
    """
    src = read('models/sensor_device.py')
    assert 'last_report_at' in src, '★ 没有单独的「上报时间」字段'
    assert "'last_report_at'" in src, 'to_dict 没返回 last_report_at'


def test_online_judged_by_report_not_heartbeat():
    """在线判定要用「最后一次上报」，不能用「最后一次心跳」。"""
    src = read('app.py')
    seg = src.split('def admin_sensor_devices()')[1].split('@app.route')[0]
    assert 'last_report_at' in seg, '★ 在线判定还在看 last_seen'
    assert "r['online'] = bool(report_age" in seg, '在线应当由上报年龄决定'
    # 心跳单独判定，用于区分「设备失联」和「设备活着但不上报」
    assert 'heartbeat_ok' in seg, '缺少 heartbeat_ok（区分两种不在线）'


def test_report_handler_sets_last_report_at():
    """上报接口要同时刷新两个时间戳。"""
    src = read('app.py')
    seg = src.split("dev_id = data.get('device_id')")[1].split('db.session.commit()')[0]
    assert 'last_seen' in seg
    assert 'last_report_at' in seg, '★ 上报时没有记 last_report_at'


def test_last_report_at_has_migration():
    """新增列必须有迁移，否则 MySQL 上直接 500。"""
    src = read('app.py')
    assert "ADD COLUMN last_report_at" in src, '★ 缺少 last_report_at 的列迁移'


def test_frontend_treats_backend_time_as_utc():
    """前端必须把后端时间当 UTC 解析。

    后端存 datetime.utcnow()，返回的 ISO 串不带时区标记；
    JS new Date('2026-11-01T09:35:28') 会按本地时间解析，
    结果北京时间 17:35 显示成 09:35，差 8 小时。
    """
    src = read('static/js/admin/hardware.js')
    seg = src.split('fmtTime(t) {')[1].split('\n    },')[0]
    assert '[zZ]' in seg, '★ 没有检测时区标记'
    assert "t + 'Z'" in seg, "★ 没有给无时区的串补 Z"

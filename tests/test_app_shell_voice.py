# -*- coding: utf-8 -*-
"""移动端外壳（智座）与语音选座链路。

对应两个真问题：
  1) App 顶部 nav 在窄屏被挤爆：品牌压成 4 行、角色徽章压成 3 行、
     6 个导航链接一个都看不见 —— 改为 App 内专用外壳
     （顶部 54px 细条 + 底部 5 个 Tab + 侧边抽屉）。
  2) 语音选座说了座位号却什么都没发生：
       · 意图正则 /([A-Za-z]?\\d+[-\\d]*)/ 对「预约A-4」只截出 "4"，丢了区号字母
       · 跳转带的 seat_label 参数，navigation.html / reservation.js 根本不读
       · 相对跳转 navigation.html 在 /admin/ 页面下会跳到 /admin/navigation.html
"""
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..')


def read(rel):
    return io.open(os.path.join(ROOT, rel.replace('/', os.sep)), encoding='utf-8').read()


# ---------------------------------------------------------------------------
# 1. App 外壳：只在 App 内生效
# ---------------------------------------------------------------------------

def test_app_shell_only_runs_inside_app():
    """浏览器里必须一个像素都不动 —— 第一道闸就是 Native.available。"""
    src = read('static/js/app-shell.js')
    assert 'window.Native.available' in src
    assert re.search(r'if \(!window\.Native \|\| !window\.Native\.available\) return;', src), \
        'app-shell.js 必须在非 App 环境直接返回'


def test_app_shell_css_is_scoped_to_app_mode():
    """所有会改动既有界面的规则都必须挂在 body.app-mode 下。

    否则网页版也会被改掉（用户要求：只叠加，不动网页端）。
    """
    css = read('static/css/mobile-app.css')
    # 去掉注释后逐条检查选择器
    body = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    selectors = []
    for block in re.finditer(r'([^{}]+)\{', body):
        sel = block.group(1).strip()
        if sel.startswith('@') or not sel:
            continue
        selectors.append(sel)

    assert selectors, '没解析到任何选择器，检查正则'
    # @keyframes 里的 from/to/百分比 不是选择器，跳过
    keyframe_sel = re.compile(r'^(from|to|\d+(\.\d+)?%)$')
    for sel in selectors:
        for one in sel.split(','):
            one = one.strip()
            if not one or keyframe_sel.match(one):
                continue
            ok = one.startswith('body.app-mode') or one.startswith('.app-')
            assert ok, '选择器未限定在 App 模式内，会污染网页版: %s' % one


def test_app_shell_hides_original_nav_only_in_app():
    css = read('static/css/mobile-app.css')
    assert 'body.app-mode .nav' in css
    assert 'display: none !important' in css


def test_app_shell_builds_topbar_tabbar_drawer():
    src = read('static/js/app-shell.js')
    for token in ('app-topbar', 'app-tabbar', 'app-drawer',
                  'app-drawer-mask', 'app-drawer-logout'):
        assert token in src, '缺少 %s' % token


def test_app_shell_has_five_tabs():
    src = read('static/js/app-shell.js')
    seg = src.split('var TABS = [')[1].split('];')[0]
    keys = re.findall(r"key: '([a-z_]+)'", seg)
    assert keys == ['index', 'seat_map', 'reservation', 'navigation', 'profile'], keys


def test_drawer_rebuilds_links_after_identity_known():
    """抽屉链接必须在身份确定后重建。

    首次克隆发生在 shell-nav.js 拿到 /api/auth/me 之前，那时「管理」入口
    还没被隐藏，会让匿名用户也看到管理后台。
    """
    src = read('static/js/app-shell.js')
    assert 'function buildDrawerNav' in src
    assert 'function fillUser' in src
    fill = src.split('function fillUser')[1].split('function whenUserReady')[0]
    assert 'buildDrawerNav()' in fill, 'fillUser 里必须重建抽屉链接'
    # 重建时仍要跳过被隐藏的链接
    nav = src.split('function buildDrawerNav')[1].split('function buildDrawer')[0]
    assert "display === 'none'" in nav, '重建时必须跳过 shell-nav 隐藏掉的入口'


def test_bundle_contains_app_shell_and_inlined_css():
    """外壳靠 native-bundle.js 单文件下发，不能再要求多传 css。"""
    js = read('static/js/native-bundle.js')
    assert 'window.__APP_SHELL_CSS__' in js, 'CSS 未内联，云端会缺样式'
    assert '智座移动端外壳已启用' in js, 'bundle 里没有 app-shell.js'
    assert 'body.app-mode' in js, '内联的 CSS 不是外壳样式'
    # app.js 仍负责自动加载
    app = read('static/js/app.js')
    assert '/static/js/native-bundle.js?v=1' in app


def test_appmode_preview_switch():
    """本地预览开关：?appmode=1 让电脑上也能看 App 布局（答辩演示用）。"""
    src = read('static/js/native-bridge.js')
    assert 'appmode' in src
    assert 'localStorage' in src.split('appmode')[0][-400:] or '__appmode__' in src


# ---------------------------------------------------------------------------
# 2. 语音选座：意图解析
# ---------------------------------------------------------------------------

def _intent_regexes():
    """从 native-features.js 里抠出座位编号正则（主 + 退化），用 Python 跑一遍。"""
    src = read('static/js/native-features.js')
    seg = src.split('parseIntent(text)')[1].split('if (/导航')[0]
    pats = re.findall(r'/(\((?:\[A-Za-z\]|\\d).*?\))/\.exec', seg)
    assert len(pats) >= 2, '应同时有「字母+数字」和「纯数字」两条，实际 %r' % pats
    return [re.compile(p) for p in pats]


def _extract_seat(sentence):
    for rx in _intent_regexes():
        m = rx.search(sentence)
        if m:
            # 与 JS 一致：去空格、把全角下划线归一成连字符
            return m.group(1).replace(' ', '').replace('_', '-').replace('－', '-')
    return None


@pytest.mark.parametrize('sentence,expect', [
    ('预约A-4', 'A-4'),
    ('导航到A-4', 'A-4'),
    ('导航到 A-4', 'A-4'),
    ('帮我订 B12', 'B12'),
    ('A4有人吗', 'A4'),
    ('预约4号', '4'),
    ('去12号座位', '12'),
])
def test_seat_label_extraction(sentence, expect):
    """旧正则对「预约A-4」只会截出 "4"，区号字母被丢掉。"""
    got = _extract_seat(sentence)
    assert got == expect, '%s -> %r，期望 %r' % (sentence, got, expect)


def test_intent_regex_keeps_letter_prefix():
    """明确回归：修复前 A-4 会被解析成 4。"""
    src = read('static/js/native-features.js')
    # 去掉 // 注释，只在真正的代码里检查旧正则是否还活着
    code = '\n'.join(l.split('//')[0] for l in src.splitlines())
    assert r'/([A-Za-z]?\d+[-\d]*)/' not in code, '旧的丢字母正则还在代码里'
    assert r'([A-Za-z]{1,3}\s*[-_－]?\s*\d{1,4})' in code, '新正则没生效'


def test_voice_navigation_uses_absolute_url():
    src = read('static/js/native-features.js')
    assert "'/navigation.html?seat_label='" in src, '相对路径在 /admin/ 下会跳错'
    assert "'/reservation.html?seat_label='" in src


# ---------------------------------------------------------------------------
# 3. 语音选座：页面必须真的接收 seat_label
# ---------------------------------------------------------------------------

def test_reservation_page_only_does_my_reservations():
    """预约页只负责「我的预约」列表 —— 选座入口在「座位图」页，不在这里。

    用户 2026-09-17 明确：选座不用在预约页实现。
    做法：不实现 building/floors/freeSeats/targetSeat/doReserve，
    于是模板里 <div class="card" v-if="building"> 那块永不渲染。
    但「我的预约」卡引用的 timeRange/qrOf/openQr/statusText/statusClass/
    checkin/qrModal 必须实现 —— 原版缺这些，列表里只要有记录 Vue 渲染就抛错，
    整页空白（只剩导航栏）。
    """
    import re as _re
    js = read('static/js/reservation.js')
    code = _re.sub(r'/\*.*?\*/', '', js, flags=_re.S)
    code = '\n'.join(l.split('//')[0] for l in code.splitlines())

    for gone in ('building', 'floors', 'freeSeats', 'targetSeat',
                 'doReserve', 'loadFromUrl', 'seatId', 'booking'):
        assert not _re.search(r'\b%s\b' % gone, code), \
            '%s 不该在预约页实现（选座在座位图页）' % gone

    for keep in ('timeRange', 'statusText', 'statusClass', 'qrOf',
                 'openQr', 'checkin', 'qrModal', 'loadReservations', 'cancel'):
        assert keep in code, '「我的预约」列表需要的 %s 缺失，页面会白屏' % keep

def test_navigation_page_is_reverted_to_original():
    """室内导航页按用户要求**完全还原成原版**。

    原版不读 seat_label —— 所以语音「导航到 A-4」不会在导航页自动选中终点，
    只会跳到导航页。预约页（reservation.js）仍保留该能力。
    另外原版有「定位成功」谎报的问题（后端返回 {{"error":...}} 时
    只判断 res.data 真假），这是还原后重新存在的已知行为。
    """
    html = read('templates/navigation.html')
    js = read('static/js/navigation.js')
    assert 'seatLabel' not in html, '导航页已还原，不该再有 seatLabel'
    assert 'resolveSeatLabel' not in js, '导航页已还原，不该再有 resolveSeatLabel'
    # 原版该有的东西还在
    assert 'onMapClick' in js and 'planRoute' in js


def test_seats_api_exposes_labels_for_voice_lookup(client, app):
    """语音解析后要按 seat_label 找座位，「全库找」这一步依赖 /api/seats。"""
    from app import db
    from models.building import Building, Floor, Seat

    with app.app_context():
        b = Building(name='语音测试楼', is_active=True)
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, name='一楼', is_active=True)
        db.session.add(f)
        db.session.flush()
        db.session.add(Seat(floor_id=f.id, seat_label='A-4', x=10, y=20,
                            status='free', is_active=True))
        db.session.commit()

        r = client.get('/api/seats')
        assert r.status_code == 200
        labels = [s.get('seat_label') for s in (r.get_json().get('data') or [])]
        assert 'A-4' in labels


def test_navigation_locate_rejects_missing_node(client, app):
    """qr 定位不给 node_id 也不能 500。"""
    from app import db
    from models.building import Building, Floor

    with app.app_context():
        b = Building(name='空楼', is_active=True)
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, floor_plan_width=400,
                  floor_plan_height=300, is_active=True)
        db.session.add(f)
        db.session.commit()

        r = client.post('/api/navigation/locate',
                        json={'type': 'qr', 'floor_id': f.id})
        assert r.status_code == 200
        assert r.get_json()['data'].get('error')

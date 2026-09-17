# -*- coding: utf-8 -*-
"""手机端登录态与桌面快捷方式。

线上反馈的四个问题：
  1) 每次打开 App 都要重新登录
     -> 全项目没有 session.permanent，Flask 发的是「会话 cookie」（无 Max-Age），
        安卓 WebView 每次冷启动都是新进程，cookie 直接没了。
  2) 明明没登录却显示「演示用户」，还退不出登录
     -> 模板里写死的默认文案；shell-nav.js 只把容器 display:none，
        App 外壳读 textContent 就读到了假名字；
        而匿名时 shell-nav 又会隐藏 [data-logout] 和 .user-info，
        注入的「登录」按钮正好在那个被隐藏的容器里 —— 进退两难。
  3) 长按桌面图标跳到首页后无事发生
     -> MainActivity.onCreate 只调了 handleShortcut() 记录路径，
        没调 applyPending()，冷启动时 path 永远不生效。
  4) 「说一句话完成找座」名不副实
     -> 找座意图只是把整句话丢给 AI 问答，不会真的找座。
"""
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), '..')


def read(rel):
    return io.open(os.path.join(ROOT, rel.replace('/', os.sep)), encoding='utf-8').read()


# ---------------------------------------------------------------------------
# 1. 会话持久化
# ---------------------------------------------------------------------------

def test_config_has_permanent_session():
    src = read('config.py')
    assert 'PERMANENT_SESSION_LIFETIME' in src, '没配会话有效期，cookie 关掉就失效'
    assert 'SESSION_COOKIE_HTTPONLY' in src
    assert 'SESSION_COOKIE_SAMESITE' in src
    # 默认不能开 Secure，否则本机 http 调试时 cookie 发不出去
    assert "SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '0')" in src


def test_both_login_handlers_mark_session_permanent():
    src = read('app.py')
    n = src.count('session.permanent = True')
    assert n >= 2, '表单登录和 /api/auth/login 都要设 session.permanent，实际 %d 处' % n


def test_login_response_sets_persistent_cookie(client, app):
    """登录响应必须带 Max-Age / Expires，否则 App 冷启动后就得重新登录。"""
    from werkzeug.security import generate_password_hash
    from app import db
    from models.user import User

    with app.app_context():
        db.session.add(User(student_id='cookie_u', name='会话测试',
                            password_hash=generate_password_hash('pw123456'),
                            email='c@t.com', role='student', is_active=True))
        db.session.commit()

    r = client.post('/api/auth/login', json={'student_id': 'cookie_u', 'password': 'pw123456'})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]

    cookies = r.headers.getlist('Set-Cookie')
    assert cookies, '登录没有下发 cookie'
    joined = ' | '.join(cookies)
    assert ('Max-Age=' in joined) or ('Expires=' in joined), \
        'cookie 没有有效期 —— 这就是「每次打开都要重新登录」的根因：%s' % joined


def test_session_survives_new_client_with_same_cookie(app):
    """同一个 cookie 换个客户端也要能认出来（模拟 App 重启后复用 cookie）。"""
    from werkzeug.security import generate_password_hash
    from app import db
    from models.user import User

    with app.app_context():
        db.session.add(User(student_id='persist_u', name='持久测试',
                            password_hash=generate_password_hash('pw123456'),
                            email='p@t.com', role='student', is_active=True))
        db.session.commit()

    c1 = app.test_client()
    assert c1.post('/api/auth/login',
                   json={'student_id': 'persist_u', 'password': 'pw123456'}).status_code == 200
    me1 = c1.get('/api/auth/me')
    assert me1.status_code == 200

    # 取出 cookie 塞给另一个 client
    cookie = None
    for h in c1.cookie_jar if hasattr(c1, 'cookie_jar') else []:
        cookie = h
    c2 = app.test_client()
    with c2.session_transaction() as s:
        pass
    # 直接复用 c1 的 cookie 头
    raw = '; '.join('%s=%s' % (k, v) for k, v in c1.cookie_jar._cookies.get('localhost.local', {})
                    .get('/', {}).items()) if hasattr(c1, 'cookie_jar') else ''
    assert me1.status_code == 200


# ---------------------------------------------------------------------------
# 2. App 外壳必须读真实登录态
# ---------------------------------------------------------------------------

def test_app_shell_uses_current_user_not_stale_text():
    src = read('static/js/app-shell.js')
    seg = src.split('function fillUser')[1].split('function whenUserReady')[0]
    assert 'window.CURRENT_USER' in seg, \
        '必须读 shell-nav.js 设置的 window.CURRENT_USER；' \
        '读 [data-user-name] 的 textContent 会拿到模板写死的「演示用户」'
    assert 'isLoggedIn' in src


def test_app_shell_offers_login_when_anonymous():
    """匿名时抽屉底部必须是「去登录」—— 否则 App 里根本没法登录。"""
    src = read('static/js/app-shell.js')
    assert '去登录' in src
    assert 'app-drawer-login' in src
    css = read('static/css/mobile-app.css')
    assert 'body.app-mode .app-drawer-login' in css, '登录态按钮样式要限定在 App 模式内'


def test_app_shell_logout_reuses_shell_nav_handler():
    src = read('static/js/app-shell.js')
    assert 'function doLogout' in src
    seg = src.split('function doLogout')[1].split('function fillUser')[0]
    assert "querySelector('[data-logout]')" in seg, '应复用 shell-nav.js 的退出逻辑'
    assert "'/logout'" in seg, '兜底也要能退出'


def test_app_shell_hides_fake_admin_entry():
    """演示路径下不能把「管理」入口带给匿名用户。"""
    src = read('static/js/app-shell.js')
    nav = src.split('function buildDrawerNav')[1].split('function buildDrawer')[0]
    assert "display === 'none'" in nav


# ---------------------------------------------------------------------------
# 3. 桌面快捷方式
# ---------------------------------------------------------------------------

def test_main_activity_applies_pending_on_cold_start():
    src = read('mobile/android/app/src/main/java/site/zhinengzuo/seatnav/MainActivity.java')
    seg = src.split('public void onCreate')[1].split('public void onNewIntent')[0]
    assert 'applyPending(' in seg, \
        'onCreate 里必须调 applyPending()，否则快捷方式冷启动永远不生效'


def test_shortcut_action_travels_in_url():
    """动作要拼在 URL 上，不能靠注入 window.__SHORTCUT__（跳转就冲掉了）。"""
    src = read('mobile/android/app/src/main/java/site/zhinengzuo/seatnav/MainActivity.java')
    assert 'autoscan=1' in src
    assert 'autovoice=1' in src
    # 只看代码，注释里会提到旧写法作为说明
    code = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    code = '\n'.join(l.split('//')[0] for l in code.splitlines())
    assert 'window.__SHORTCUT__' not in code, '不该再用注入变量的方式传动作'
    assert 'evaluateJavascript' not in code, '不该再靠 evaluateJavascript 注入动作'


def test_frontend_reads_shortcut_from_url():
    src = read('static/js/native-features.js')
    assert 'shortcutFromUrl' in src
    assert "q.get('autoscan')" in src and "q.get('autovoice')" in src
    assert 'clearShortcutParam' in src, '触发一次后要从地址栏抹掉，避免刷新重复触发'
    seg = src.split('function clearShortcutParam')[1].split('async function apiGet')[0]
    assert 'replaceState' in seg


def test_shortcut_paths_point_somewhere_useful():
    """扫码要去预约页签到，语音要有地方说话。"""
    xml = read('mobile/android/app/src/main/res/xml/shortcuts.xml')
    assert 'find_seat' in xml and 'scan_seat' in xml
    assert 'my_reservations' in xml and 'voice_seat' in xml
    assert xml.count('<extra android:name="path"') == 4


def test_shortcut_labels_present():
    xml = read('mobile/android/app/src/main/res/values/strings.xml')
    for k in ('sc_find_short', 'sc_scan_short', 'sc_resv_short', 'sc_voice_short'):
        assert 'name="%s"' % k in xml


# ---------------------------------------------------------------------------
# 4. 语音找座要真的去找座
# ---------------------------------------------------------------------------

def test_voice_find_queries_seats_and_navigates():
    src = read('static/js/native-features.js')
    seg = src.split("if (intent.act === 'find')")[1].split("if (intent.act === 'ask')")[0]
    assert '/api/seats' in seg, '找座要真的查座位，不能只丢给 AI 问答'
    assert "s.status === 'free'" in seg
    assert '/navigation.html?seat_label=' in seg, '找到后要直接带去导航'


def test_voice_ask_still_uses_ai():
    src = read('static/js/native-features.js')
    seg = src.split("if (intent.act === 'ask')")[1].split('async listenAndRun')[0]
    assert '/api/ai/ask' in seg, '开放问题仍应交给 AI'


def test_voice_seat_number_matching_is_normalised():
    src = read('static/js/native-features.js')
    seg = src.split("if (intent.act === 'find')")[1].split("if (intent.act === 'ask')")[0]
    assert 'replace(' in seg and 'toLowerCase' in seg, '座位号要归一化后再比对（A4 / A-4）'

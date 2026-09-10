# -*- coding: utf-8 -*-
"""AI（大模型）功能测试。

覆盖三层：
1. LLMClient 单元行为（未配置 / 缓存 / 失败降级 / 状态不泄密）
2. 快照与用户画像（token 控制层的正确性）
3. HTTP 接口（用户端 / 管理端 / 智能终端），包括降级路径

**所有测试都不发起真实网络请求**（必要时 monkeypatch requests.post）。
"""
import json

import pytest

from app import db
from models.building import Building, Floor, Seat
from models.user import User
from werkzeug.security import generate_password_hash

from utils.ai_context import (
    build_seat_snapshot,
    build_user_context,
    snapshot_fingerprint,
)
from utils.llm import LLMClient
from utils import ai_service
from utils.ai_service import (
    AdminAIService,
    UserAIService,
    _fallback_admin_report,
    _fallback_brief,
    terminal_brief,
)


# ---------------------------------------------------------------- 辅助
def _admin(client, app):
    with app.app_context():
        u = User(student_id='aiadmin', name='AI 管理员',
                 password_hash=generate_password_hash('123456'),
                 email='aiadmin@test.com', role='admin', is_approved=True)
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'admin'
    return client


def _login(client, app, student_id='aistudent'):
    with app.app_context():
        u = User(student_id=student_id, name='AI 用户',
                 password_hash=generate_password_hash('123456'),
                 email='aistudent@test.com')
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'student'
    return uid


def _seats(app, n=4, occupy=0):
    """建 n 个座位，前 occupy 个设为占用。"""
    with app.app_context():
        b = Building(name='AI馆')
        db.session.add(b)
        db.session.flush()
        f = Floor(building_id=b.id, floor_number=1, name='1F')
        db.session.add(f)
        db.session.flush()
        ids = []
        for i in range(n):
            s = Seat(floor_id=f.id, seat_label='A-%d' % (i + 1), x=i, y=1,
                     status='occupied' if i < occupy else 'free')
            db.session.add(s)
            db.session.flush()
            ids.append(s.id)
        db.session.commit()
        return f.id, ids


# ================================================================ LLMClient
class TestLLMClient:
    def test_not_configured_returns_none(self):
        """未配置密钥时应安静返回 None（而不是抛异常）。"""
        c = LLMClient(base_url='', api_key='', model='')
        assert c.configured is False
        assert c.chat([{'role': 'user', 'content': 'hi'}]) is None

    def test_disabled_returns_none(self):
        c = LLMClient(base_url='https://x/v1', api_key='k', model='m', enabled=False)
        assert c.configured is False
        assert c.chat([{'role': 'user', 'content': 'hi'}]) is None

    def test_status_never_leaks_key(self):
        """状态接口只能暴露"是否设置"，绝不能回传密钥明文。"""
        secret = 'sk-super-secret-value-123456'
        c = LLMClient(base_url='https://x/v1', api_key=secret, model='m')
        st = c.status()
        assert st['api_key_set'] is True
        assert secret not in json.dumps(st)

    def test_success_and_cache(self, monkeypatch):
        """成功调用并命中缓存：第二次不应再发请求。"""
        calls = {'n': 0}

        class Resp:
            status_code = 200

            @staticmethod
            def json():
                return {'choices': [{'message': {'content': '正常'}}]}

        def fake_post(url, headers=None, json=None, timeout=None):
            calls['n'] += 1
            return Resp()

        monkeypatch.setattr('utils.llm.requests.post', fake_post)
        c = LLMClient(base_url='https://x/v1', api_key='k', model='m', cache_ttl=60)
        msgs = [{'role': 'user', 'content': '你好'}]
        assert c.chat(msgs) == '正常'
        assert c.chat(msgs) == '正常'
        assert calls['n'] == 1, '第二次应命中缓存'
        assert c.status()['stats']['hits'] == 1

    def test_cache_can_be_bypassed(self, monkeypatch):
        calls = {'n': 0}

        class Resp:
            status_code = 200

            @staticmethod
            def json():
                return {'choices': [{'message': {'content': 'x'}}]}

        def fake_post(url, headers=None, json=None, timeout=None):
            calls['n'] += 1
            return Resp()

        monkeypatch.setattr('utils.llm.requests.post', fake_post)
        c = LLMClient(base_url='https://x/v1', api_key='k', model='m', cache_ttl=60)
        msgs = [{'role': 'user', 'content': 'q'}]
        c.chat(msgs)
        c.chat(msgs, use_cache=False)
        assert calls['n'] == 2

    def test_network_error_degrades(self, monkeypatch):
        """网络异常 -> 返回 None（调用方降级），且统计 fallbacks。"""
        import requests

        def boom(*a, **k):
            raise requests.RequestException('connection reset')

        monkeypatch.setattr('utils.llm.requests.post', boom)
        c = LLMClient(base_url='https://x/v1', api_key='k', model='m', max_retries=0)
        assert c.chat([{'role': 'user', 'content': 'hi'}]) is None
        assert c.status()['stats']['fallbacks'] == 1

    def test_auth_error_no_retry(self, monkeypatch):
        """401 鉴权失败不应重试。"""
        calls = {'n': 0}

        class Resp:
            status_code = 401
            text = 'unauthorized'

            @staticmethod
            def json():
                return {}

        def fake_post(url, headers=None, json=None, timeout=None):
            calls['n'] += 1
            return Resp()

        monkeypatch.setattr('utils.llm.requests.post', fake_post)
        c = LLMClient(base_url='https://x/v1', api_key='bad', model='m', max_retries=3)
        assert c.chat([{'role': 'user', 'content': 'hi'}], use_cache=False) is None
        assert calls['n'] == 1, '401 应立即放弃，不重试'

    def test_extract_text_variants(self):
        assert LLMClient._extract_text({'choices': [{'message': {'content': 'abc'}}]}) == 'abc'
        assert LLMClient._extract_text(
            {'choices': [{'message': {'content': [{'text': 'a'}, {'text': 'b'}]}}]}
        ) == 'ab'
        assert LLMClient._extract_text({}) == ''
        assert LLMClient._extract_text({'choices': []}) == ''

    def test_clear_cache(self, monkeypatch):
        class Resp:
            status_code = 200

            @staticmethod
            def json():
                return {'choices': [{'message': {'content': 'v'}}]}

        monkeypatch.setattr('utils.llm.requests.post',
                            lambda *a, **k: Resp())
        c = LLMClient(base_url='https://x/v1', api_key='k', model='m', cache_ttl=60)
        c.chat([{'role': 'user', 'content': 'q'}])
        assert c.clear_cache() == 1
        assert c.clear_cache() == 0


# ================================================================ 快照
class TestSnapshot:
    def test_counts_and_rate(self, app):
        with app.app_context():
            _seats(app, n=4, occupy=1)
            snap = build_seat_snapshot()
            assert snap['total'] == 4
            assert snap['occupied'] == 1
            assert snap['free'] == 3
            assert snap['occupancy_rate'] == pytest.approx(0.25)
            assert 'A-1' in snap['free_seat_labels'] or 'A-2' in snap['free_seat_labels']

    def test_stale_detection(self, app):
        """所有座位都没有 last_scan_time -> 判定为数据过期，且不逐条报异常。"""
        with app.app_context():
            _seats(app, n=3)
            snap = build_seat_snapshot()
            assert snap['data_stale'] is True
            assert snap['abnormal_seats'] == []

    def test_fingerprint_changes_with_state(self, app):
        with app.app_context():
            _seats(app, n=3)
            a = snapshot_fingerprint(build_seat_snapshot())
            Seat.query.filter_by(seat_label='A-1').first().status = 'occupied'
            db.session.commit()
            b = snapshot_fingerprint(build_seat_snapshot())
            assert a != b

    def test_user_context_empty(self, app):
        with app.app_context():
            u = User(student_id='u1', name='某人',
                     password_hash=generate_password_hash('1'),
                     email='u1@t.com', preferences={'window': True})
            db.session.add(u)
            db.session.commit()
            ctx = build_user_context(u.id)
            assert ctx['preferences']['window'] is True
            assert ctx['reservation_count_30d'] == 0


# ================================================================ 降级文案
class TestFallbacks:
    def test_brief_stale_is_honest(self):
        """数据过期时必须诚实说明，不能误导用户"很空"。"""
        snap = {'total': 10, 'free': 10, 'occupied': 0, 'data_stale': True,
                'last_report_minutes_ago': 90, 'free_seat_labels': ['A-1']}
        text = _fallback_brief(snap)
        assert '过期' in text
        assert '90' in text

    def test_brief_no_free(self):
        snap = {'total': 5, 'free': 0, 'occupied': 5, 'data_stale': False,
                'free_seat_labels': []}
        assert '全部占用' in _fallback_brief(snap)

    def test_brief_normal(self):
        snap = {'total': 10, 'free': 4, 'occupied': 6, 'data_stale': False,
                'free_seat_labels': ['B-2']}
        text = _fallback_brief(snap)
        assert 'B-2' in text and '4' in text

    def test_admin_report_mentions_stale(self):
        snap = {'total': 3, 'free': 3, 'occupied': 0, 'occupancy_rate': 0.0,
                'by_floor': {}, 'abnormal_seats': [], 'data_stale': True,
                'last_report_minutes_ago': 30}
        assert '掉线' in _fallback_admin_report(snap)

    def test_admin_report_lists_abnormal(self):
        snap = {'total': 3, 'free': 2, 'occupied': 1, 'occupancy_rate': 0.33,
                'by_floor': {'1F': {'total': 3, 'free': 2, 'occupied': 1}},
                'abnormal_seats': [{'seat': 'A-9', 'status': 'occupied',
                                    'silent_minutes': 42}],
                'data_stale': False}
        text = _fallback_admin_report(snap)
        assert 'A-9' in text


# ================================================================ 服务层（无 AI）
class TestServicesWithoutAI:
    def test_brief_falls_back(self, app):
        with app.app_context():
            _seats(app, n=3)
            r = UserAIService().brief()
            assert r['ai_generated'] is False
            assert r['text']

    def test_admin_report_falls_back(self, app):
        with app.app_context():
            _seats(app, n=3)
            r = AdminAIService().daily_report()
            assert r['ai_generated'] is False
            assert r['text']

    def test_anomaly_global_offline(self, app):
        """所有座位静默 -> 应报告"整体掉线"而不是逐个座位。"""
        with app.app_context():
            _seats(app, n=3)
            r = AdminAIService().anomaly_report()
            assert r['global_offline'] is True
            assert '掉线' in r['text']

    def test_trend_no_data(self, app):
        with app.app_context():
            r = AdminAIService().trend_analysis(days=7)
            assert r['text']

    def test_habit_no_history(self, app):
        with app.app_context():
            u = User(student_id='h1', name='无记录',
                     password_hash=generate_password_hash('1'), email='h1@t.com')
            db.session.add(u)
            db.session.commit()
            r = UserAIService().habit_insight(u.id)
            assert '还没有预约记录' in r['text']

    def test_ask_empty_question(self, app):
        with app.app_context():
            r = UserAIService().ask('')
            assert r['ai_generated'] is False

    def test_terminal_brief_truncates(self, app):
        with app.app_context():
            _seats(app, n=3)
            r = terminal_brief(max_len=10)
            assert len(r['text']) <= 10
            assert set(['text', 'free', 'total', 'ai_generated']).issubset(r.keys())


# ================================================================ 服务层（模拟 AI 可用）
class TestServicesWithMockedAI:
    def test_brief_uses_llm(self, app, monkeypatch):
        with app.app_context():
            _seats(app, n=3)
            monkeypatch.setattr(ai_service.LLMClient, 'chat',
                                lambda self, *a, **k: 'AI 生成的一句话')
            r = UserAIService().brief()
            assert r['ai_generated'] is True
            assert r['text'] == 'AI 生成的一句话'

    def test_llm_failure_still_returns_text(self, app, monkeypatch):
        """模型返回 None（失败）时必须降级，绝不返回空。"""
        with app.app_context():
            _seats(app, n=3)
            monkeypatch.setattr(ai_service.LLMClient, 'chat',
                                lambda self, *a, **k: None)
            r = UserAIService().brief()
            assert r['ai_generated'] is False
            assert r['text']


# ================================================================ HTTP 接口
class TestAIEndpoints:
    def test_status_ok_and_no_key(self, client, app):
        """状态接口可以报"是否已设置"，但绝不能返回密钥明文。"""
        from config import Config
        secret = 'sk-leak-canary-0123456789'
        old = Config.AI_API_KEY
        Config.AI_API_KEY = secret
        try:
            from utils import reload_llm
            reload_llm()
            r = client.get('/api/ai/status')
            assert r.status_code == 200
            body = r.data.decode('utf-8')
            assert secret not in body, '响应中不得包含密钥明文'
            d = r.get_json()['data']
            assert d['api_key_set'] is True
            assert d['configured'] is True
        finally:
            Config.AI_API_KEY = old
            from utils import reload_llm as _rl
            _rl()

    def test_brief_public(self, client, app):
        with app.app_context():
            _seats(app, n=3)
        r = client.get('/api/ai/brief')
        assert r.status_code == 200
        d = r.get_json()['data']
        assert d['text']
        assert d['snapshot']['total'] == 3

    def test_brief_max_len(self, client, app):
        with app.app_context():
            _seats(app, n=3)
        r = client.get('/api/ai/brief?max_len=12')
        assert r.status_code == 200
        d = r.get_json()['data']
        assert len(d['text']) <= 12
        assert 'snapshot' not in d, '终端模式应返回精简结构'

    def test_terminal_page_renders(self, client):
        r = client.get('/terminal')
        assert r.status_code == 200
        html = r.data.decode('utf-8', 'ignore')
        # 稳定标识：终端页容器与楼层切换控件
        assert 'id="notice"' in html
        assert 'id="floors"' in html
        # 零外部依赖：不应引用任何 CDN
        assert 'cdn.jsdelivr.net' not in html
        assert 'unpkg.com' not in html

    def test_terminal_data(self, client, app):
        with app.app_context():
            _seats(app, n=4, occupy=1)
        r = client.get('/api/terminal/data')
        assert r.status_code == 200
        d = r.get_json()['data']
        assert d['total'] == 4
        assert d['occupied'] == 1
        assert len(d['seats']) == 4
        assert d['ai_text']
        assert d['ai_mode'] in ('ai', 'fallback')

    def test_habit_requires_login(self, client):
        assert client.get('/api/ai/habit').status_code == 401

    def test_habit_with_login(self, client, app):
        uid = _login(client, app)
        r = client.get('/api/ai/habit')
        assert r.status_code == 200
        assert r.get_json()['data']['text']

    def test_explain_requires_seat(self, client, app):
        _login(client, app, 'aistudent2')
        r = client.post('/api/ai/explain', json={})
        assert r.status_code == 400
        r2 = client.post('/api/ai/explain', json={'seat_label': 'A-1'})
        assert r2.status_code == 200
        assert 'A-1' in r2.get_json()['data']['text']

    def test_ask_endpoint(self, client, app):
        _login(client, app, 'aistudent3')
        r = client.post('/api/ai/ask', json={'question': '有没有安静的座位？'})
        assert r.status_code == 200
        assert r.get_json()['data']['text']

    def test_admin_report_requires_admin(self, client):
        assert client.get('/api/admin/ai/report').status_code in (401, 403)

    def test_admin_ai_page_renders(self, client, app):
        _admin(client, app)
        r = client.get('/admin/ai')
        assert r.status_code == 200
        assert 'AI 运营中心' in r.data.decode('utf-8', 'ignore')

    def test_admin_report_and_anomaly(self, client, app):
        _admin(client, app)
        with app.app_context():
            _seats(app, n=3)
        assert client.get('/api/admin/ai/report').status_code == 200
        assert client.get('/api/admin/ai/anomaly').status_code == 200

    def test_admin_trend_and_ask(self, client, app):
        _admin(client, app)
        assert client.get('/api/admin/ai/trend?days=7').status_code == 200
        r = client.post('/api/admin/ai/ask', json={'question': '现在忙吗？'})
        assert r.status_code == 200
        assert r.get_json()['data']['text']

    def test_admin_ai_test_reports_not_configured(self, client, app):
        _admin(client, app)
        r = client.post('/api/admin/ai/test', json={})
        assert r.status_code == 400
        assert r.get_json()['data']['ok'] is False


# ================================================================ 配置切换
class TestAIConfig:
    def test_get_config_hides_key(self, client, app):
        _admin(client, app)
        from config import Config
        Config.AI_API_KEY = 'sk-abcdefghijklmnop'
        try:
            r = client.get('/api/admin/config')
            assert r.status_code == 200
            body = json.dumps(r.get_json())
            assert 'sk-abcdefghijklmnop' not in body
            d = r.get_json()['data']
            assert d['ai_api_key_set'] is True
            assert d['ai_api_key_masked'].startswith('sk-abc')
        finally:
            Config.AI_API_KEY = ''

    def test_switch_provider_applies_preset(self, client, app):
        """切换供应商应自动套用该供应商的 base_url 与模型。"""
        _admin(client, app)
        from config import Config
        old = (Config.AI_PROVIDER, Config.AI_BASE_URL, Config.AI_MODEL)
        try:
            r = client.put('/api/admin/config', json={'ai_provider': 'qwen'})
            assert r.status_code == 200, r.get_json()
            assert Config.AI_BASE_URL == Config.AI_PROVIDER_PRESETS['qwen']['base_url']
            assert Config.AI_MODEL == Config.AI_PROVIDER_PRESETS['qwen']['model']
        finally:
            Config.AI_PROVIDER, Config.AI_BASE_URL, Config.AI_MODEL = old

    def test_custom_provider_can_set_own_url(self, client, app):
        """custom 供应商允许指向本地模型（如 Ollama）。"""
        _admin(client, app)
        from config import Config
        old = (Config.AI_PROVIDER, Config.AI_BASE_URL, Config.AI_MODEL)
        try:
            r = client.put('/api/admin/config', json={
                'ai_provider': 'custom',
                'ai_base_url': 'http://127.0.0.1:11434/v1',
                'ai_model': 'qwen2.5:7b',
            })
            assert r.status_code == 200, r.get_json()
            assert Config.AI_BASE_URL == 'http://127.0.0.1:11434/v1'
            assert Config.AI_MODEL == 'qwen2.5:7b'
        finally:
            Config.AI_PROVIDER, Config.AI_BASE_URL, Config.AI_MODEL = old

    def test_invalid_provider_rejected(self, client, app):
        _admin(client, app)
        r = client.put('/api/admin/config', json={'ai_provider': 'not-a-provider'})
        assert r.status_code == 400

    def test_invalid_base_url_rejected(self, client, app):
        _admin(client, app)
        r = client.put('/api/admin/config', json={'ai_base_url': 'ftp://x'})
        assert r.status_code == 400

    def test_timeout_range_validated(self, client, app):
        _admin(client, app)
        assert client.put('/api/admin/config', json={'ai_timeout': 1}).status_code == 400
        assert client.put('/api/admin/config', json={'ai_timeout': 999}).status_code == 400

    def test_config_merge_keeps_other_keys(self, client, app):
        """保存 AI 配置不应清掉其它已保存配置（回归测试：原来会整体覆盖）。"""
        import app as app_module
        _admin(client, app)
        assert client.put('/api/admin/config',
                          json={'lock_m_default': 25}).status_code == 200
        assert client.put('/api/admin/config',
                          json={'ai_max_tokens': 800}).status_code == 200
        with open(app_module._RUNTIME_CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        assert saved.get('lock_m_default') == 25, '保存 AI 配置时不应丢失其它配置'
        assert saved.get('ai_max_tokens') == 800


# ================================================================ 智能终端
class TestTerminal:
    def test_data_lists_buildings_and_floors(self, client, app):
        """终端需要拿到可切换的场所/楼层列表。"""
        with app.app_context():
            _seats(app, n=3)
        r = client.get('/api/terminal/data')
        assert r.status_code == 200
        d = r.get_json()['data']
        assert len(d['buildings']) >= 1
        assert len(d['floors']) >= 1
        assert 'title' in d

    def test_floor_filter_narrows_seats(self, client, app):
        """按楼层过滤后座位数应减少。"""
        with app.app_context():
            fid, _ = _seats(app, n=3)
            b = Building(name='第二馆')
            db.session.add(b)
            db.session.flush()
            f2 = Floor(building_id=b.id, floor_number=1, name='2馆1F')
            db.session.add(f2)
            db.session.flush()
            for i in range(2):
                db.session.add(Seat(floor_id=f2.id, seat_label='B-%d' % (i + 1), x=i, y=1))
            db.session.commit()
            f2_id = f2.id
        all_d = client.get('/api/terminal/data').get_json()['data']
        one_d = client.get('/api/terminal/data?floor_id=%d' % f2_id).get_json()['data']
        assert all_d['total'] == 5
        assert one_d['total'] == 2
        assert one_d['floor_id'] == f2_id

    def test_configured_default_location_used(self, client, app):
        """未传参数时应采用管理员配置的终端默认位置。"""
        from config import Config
        with app.app_context():
            fid, _ = _seats(app, n=3)
            b = Building(name='别馆')
            db.session.add(b)
            db.session.flush()
            f2 = Floor(building_id=b.id, floor_number=1, name='别馆1F')
            db.session.add(f2)
            db.session.flush()
            other_id = f2.id
            db.session.commit()
        old_b, old_f = Config.TERMINAL_BUILDING_ID, Config.TERMINAL_FLOOR_ID
        try:
            Config.TERMINAL_BUILDING_ID = 0
            Config.TERMINAL_FLOOR_ID = other_id
            d = client.get('/api/terminal/data').get_json()['data']
            assert d['floor_id'] == other_id
            assert d['total'] == 0, '该楼层没有座位，应只统计本层'
        finally:
            Config.TERMINAL_BUILDING_ID, Config.TERMINAL_FLOOR_ID = old_b, old_f

    def test_explicit_zero_means_all(self, client, app):
        """显式传 floor_id=0 表示"全部楼层"，可覆盖配置的默认位置。"""
        from config import Config
        with app.app_context():
            _seats(app, n=3)
        old_f = Config.TERMINAL_FLOOR_ID
        try:
            Config.TERMINAL_FLOOR_ID = 999999
            d = client.get('/api/terminal/data?floor_id=0').get_json()['data']
            assert d['floor_id'] is None
            assert d['total'] == 3
        finally:
            Config.TERMINAL_FLOOR_ID = old_f

    def test_save_terminal_location(self, client, app):
        """管理员保存终端位置与标题。"""
        from config import Config
        _admin(client, app)
        old = (Config.TERMINAL_TITLE, Config.TERMINAL_BUILDING_ID)
        try:
            r = client.put('/api/admin/config', json={
                'terminal_title': '图书馆三楼导引',
                'terminal_building_id': 1,
                'terminal_floor_id': 0,
            })
            assert r.status_code == 200, r.get_json()
            assert Config.TERMINAL_TITLE == '图书馆三楼导引'
            assert Config.TERMINAL_BUILDING_ID == 1
        finally:
            Config.TERMINAL_TITLE, Config.TERMINAL_BUILDING_ID = old

    def test_terminal_location_visible_in_config_get(self, client, app):
        _admin(client, app)
        d = client.get('/api/admin/config').get_json()['data']
        assert 'terminal_title' in d
        assert 'buildings' in d and 'floors' in d

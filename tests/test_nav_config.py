# -*- coding: utf-8 -*-
"""室外导航地图配置测试（key 安全 + 可切换）。"""
import json

from app import db
from models.user import User
from werkzeug.security import generate_password_hash


def _admin(client, app, sid='navadmin'):
    with app.app_context():
        u = User(student_id=sid, name='导航管理员',
                 password_hash=generate_password_hash('123456'),
                 role='admin', is_approved=True)
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'admin'
    return client


SECRET = 'abcdef0123456789abcdef0123456789'


class TestNavMapConfig:
    def test_default_provider_is_amap(self, app):
        """需求：默认高德"""
        from config import Config
        old = Config.NAV_MAP_PROVIDER
        try:
            Config.NAV_MAP_PROVIDER = 'amap'
            assert Config.NAV_MAP_PROVIDER == 'amap'
        finally:
            Config.NAV_MAP_PROVIDER = old

    def test_masking_helper(self):
        from app import _mask_secret
        assert _mask_secret('') == ''
        assert _mask_secret('abc') == '***'
        m = _mask_secret(SECRET)
        assert SECRET not in m
        assert m.startswith('abcd') and m.endswith('6789')

    def test_key_never_returned_in_plaintext(self, client, app):
        """核心安全断言：后台配置接口只能回传掩码，绝不回传明文 key"""
        from config import Config
        old = Config.NAV_MAP_KEY
        Config.NAV_MAP_KEY = SECRET
        try:
            _admin(client, app)
            r = client.get('/api/admin/config')
            assert r.status_code == 200
            body = r.data.decode('utf-8')
            assert SECRET not in body, '接口绝不能回传明文 key'
            d = r.get_json()['data']
            assert d['nav_map_key_set'] is True
            assert 'nav_map_key_masked' in d
            assert SECRET not in json.dumps(d)
        finally:
            Config.NAV_MAP_KEY = old

    def test_admin_can_switch_provider(self, client, app):
        """管理员可切换服务商（需求：可配置换）"""
        from config import Config
        old = Config.NAV_MAP_PROVIDER
        try:
            _admin(client, app)
            assert client.put('/api/admin/config',
                              json={'nav_map_provider': 'baidu'}).status_code == 200
            assert Config.NAV_MAP_PROVIDER == 'baidu'
        finally:
            Config.NAV_MAP_PROVIDER = old

    def test_invalid_provider_rejected(self, client, app):
        _admin(client, app)
        r = client.put('/api/admin/config', json={'nav_map_provider': 'google'})
        assert r.status_code == 400

    def test_key_can_be_updated_and_cleared(self, client, app):
        from config import Config
        import app as app_module
        old = Config.NAV_MAP_KEY
        try:
            _admin(client, app)
            client.put('/api/admin/config', json={'nav_map_key': 'newkey123456'})
            assert Config.NAV_MAP_KEY == 'newkey123456'

            client.put('/api/admin/config', json={'nav_map_key': '__CLEAR__'})
            assert Config.NAV_MAP_KEY == ''

            # 留空表示不修改（避免误清空）
            Config.NAV_MAP_KEY = 'keepme'
            client.put('/api/admin/config', json={'nav_map_key': ''})
            assert Config.NAV_MAP_KEY == 'keepme'
        finally:
            Config.NAV_MAP_KEY = old

    def test_runtime_config_persists_key(self, client, app):
        """写入的 key 应持久化到运行期配置文件（该文件已被 .gitignore 忽略）"""
        import app as app_module
        _admin(client, app)
        client.put('/api/admin/config', json={'nav_map_key': 'persist_me_123'})
        with open(app_module._RUNTIME_CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        assert saved.get('nav_map_key') == 'persist_me_123'

    def test_fallback_toggle(self, client, app):
        """兜底开关可配置（地图不可用时的自建方位导航）"""
        from config import Config
        old = Config.NAV_FALLBACK_ENABLED
        try:
            _admin(client, app)
            client.put('/api/admin/config', json={'nav_fallback_enabled': False})
            assert Config.NAV_FALLBACK_ENABLED is False
        finally:
            Config.NAV_FALLBACK_ENABLED = old

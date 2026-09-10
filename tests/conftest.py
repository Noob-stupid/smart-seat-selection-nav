import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy.pool import StaticPool
from app import app as flask_app, db
from config import Config


def _use_inmemory_db():
    """强制测试使用内存 SQLite，避免误操作真实 MySQL。

    关键：Flask-SQLAlchemy 3.x 在 `db.init_app(app)` 时（app.py 导入瞬间）
    就已按 MySQL 配置创建了引擎；之后直接改 `SQLALCHEMY_DATABASE_URI`
    完全不生效。必须显式按新配置重建引擎，否则测试的 create_all/drop_all
    会直接作用在真实 MySQL 的 seat_navigation 库上（历史上因此清空过数据）。
    """
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    sa = flask_app.extensions.get('sqlalchemy')
    if sa is not None:
        with flask_app.app_context():
            engines = sa._app_engines.setdefault(flask_app, {})
            for eng in list(engines.values()):
                eng.dispose()
            engines.clear()
            basic_opts = dict(sa._engine_options)
            basic_opts.update(flask_app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {}))
            basic_opts['url'] = flask_app.config['SQLALCHEMY_DATABASE_URI']
            engines[None] = sa._make_engine(None, basic_opts, flask_app)


@pytest.fixture
def app():
    """创建测试用 Flask 应用（隔离到内存 SQLite，绝不触碰 MySQL）"""
    _use_inmemory_db()
    flask_app.config['WTF_CSRF_ENABLED'] = False
    # 测试环境隔离：重置动态配置，避免受 data/system_config.json 持久化配置影响
    Config.CHECKIN_QR_ENABLED = False
    with flask_app.app_context():
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def _isolate_runtime_config(tmp_path, monkeypatch):
    """测试隔离：把运行期配置文件重定向到临时目录。

    否则调用 /api/admin/config 的测试会把配置写进真实的
    `data/system_config.json`，污染本机运行配置（历史上已发生过）。
    """
    import app as app_module
    monkeypatch.setattr(app_module, '_RUNTIME_CONFIG_FILE',
                        str(tmp_path / 'system_config.json'))
    yield


_AI_KEYS = ('AI_ENABLED', 'AI_API_KEY', 'AI_PROVIDER', 'AI_BASE_URL', 'AI_MODEL',
            'AI_TIMEOUT', 'AI_MAX_RETRIES', 'AI_MAX_TOKENS', 'AI_TEMPERATURE',
            'AI_CACHE_TTL')


@pytest.fixture(autouse=True)
def _reset_ai_config():
    """测试隔离：把 AI 配置重置为"未配置"。

    本机 `data/system_config.json` 里可能存着真实 API Key，若不重置，
    依赖"降级路径"的测试会真的去调外网，结果取决于本机配置而不确定。
    """
    from config import Config
    from utils import reload_llm, reset_ai_services

    saved = {k: getattr(Config, k, None) for k in _AI_KEYS}
    Config.AI_ENABLED = True
    Config.AI_API_KEY = ''
    Config.AI_PROVIDER = 'deepseek'
    Config.AI_BASE_URL = Config.AI_PROVIDER_PRESETS['deepseek']['base_url']
    Config.AI_MODEL = Config.AI_PROVIDER_PRESETS['deepseek']['model']
    reload_llm()
    reset_ai_services()
    yield
    for k, v in saved.items():
        if v is not None:
            setattr(Config, k, v)
    reload_llm()
    reset_ai_services()


@pytest.fixture
def client(app):
    """Flask 测试客户端"""
    return app.test_client()


@pytest.fixture
def logged_in(client, app):
    """已登录的测试客户端"""
    from models.user import User
    from werkzeug.security import generate_password_hash
    with app.app_context():
        user = User(
            student_id='testuser',
            name='测试用户',
            password_hash=generate_password_hash('123456'),
            email='test@test.com',
        )
        db.session.add(user)
        db.session.commit()
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['role'] = 'student'
            sess['name'] = '测试用户'
    return client, user

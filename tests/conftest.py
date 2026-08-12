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

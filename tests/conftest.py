import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import app as flask_app, db


@pytest.fixture
def app():
    """创建测试用 Flask 应用"""
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    flask_app.config['WTF_CSRF_ENABLED'] = False
    with flask_app.app_context():
        db.create_all()
        yield flask_app
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

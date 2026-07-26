from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO

db = SQLAlchemy()
# CORS 由 app.py 中 socketio.init_app 动态配置
socketio = SocketIO()

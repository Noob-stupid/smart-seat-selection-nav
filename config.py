"""
智能选座与导航一体化系统 - 配置文件
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'seat-nav-system-secret-key-2026')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

    # 文件上传
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB

    # MySQL 数据库
    DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT = int(os.getenv('DB_PORT', 3306))
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'seat_navigation')
    # 密码中的 @ 需转义为 %40，避免被 URI 解析器误认为 user:password@host 分隔符
    _encoded_pw = DB_PASSWORD.replace('@', '%40')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        f'mysql+pymysql://{DB_USER}:{_encoded_pw}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Redis 缓存
    REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

    # 锁定参数默认值
    LOCK_M_DEFAULT = 20       # 锁定门槛 m（分钟）
    LOCK_N_DEFAULT = 5        # 检测周期 n（分钟）
    LOCK_T_DEFAULT = 30       # 最短有效回归时长 t（秒）
    LOCK_M_RANGE = (10, 60)   # m 可配置范围
    LOCK_N_RANGE = (2, 15)    # n 可配置范围
    LOCK_T_RANGE = (10, 120)  # t 可配置范围

    # AI 推荐权重
    AI_WEIGHTS = [0.35, 0.25, 0.25, 0.15]  # [dist, heat, pref, crowd]

    # 传感器配置
    SENSOR_SCAN_INTERVAL = 30  # 传感器扫描周期（秒）

    # SQLite fallback（无 MySQL 时使用）
    SQLALCHEMY_DATABASE_URI_FALLBACK = 'sqlite:///seat_navigation.db'


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}

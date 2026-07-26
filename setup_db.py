"""
============================================================
数据库初始化脚本
创建 MySQL 数据库和所有表结构
============================================================
用法:
  python setup_db.py           # 创建数据库+表+示例数据
  python setup_db.py --drop    # 删除现有表后重建
============================================================
"""
import sys
import pymysql
from app import app, db
from config import Config

DB_NAME = Config.DB_NAME


def create_database_if_not_exists():
    """连接 MySQL server 并创建数据库（如果不存在）"""
    try:
        conn = pymysql.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            charset='utf8mb4',
        )
        cursor = conn.cursor()
        cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        cursor.close()
        conn.close()
        print(f'[✓] 数据库 "{DB_NAME}" 已就绪')
        return True
    except pymysql.err.OperationalError as e:
        print(f'[✗] MySQL 连接失败: {e}')
        print(f'    请确认 MySQL 服务已启动，账号密码正确')
        return False


def create_tables(drop_first=False):
    """创建所有表结构"""
    with app.app_context():
        if drop_first:
            print('  正在删除旧表...')
            db.drop_all()
            print('  [✓] 旧表已删除')
        db.create_all()
        # 列出所有表
        tables = db.metadata.tables.keys()
        print(f'  [✓] 已创建 {len(list(tables))} 张表:')
        for t in tables:
            print(f'       - {t}')


def seed_data():
    """插入示例数据"""
    from app import init_database
    with app.app_context():
        from models.building import Building
        if Building.query.count() > 0:
            print('  [i] 示例数据已存在，跳过')
            return
        init_database()
        print('  [✓] 示例数据已插入')


if __name__ == '__main__':
    drop_first = '--drop' in sys.argv

    print('=' * 50)
    print('  智能选座与导航 - 数据库初始化')
    print('=' * 50)

    # 1. 创建数据库
    print(f'\n[1/3] 连接 MySQL ({Config.DB_HOST}:{Config.DB_PORT})...')
    if not create_database_if_not_exists():
        sys.exit(1)

    # 2. 强制使用 MySQL 连接
    print(f'\n[2/3] 创建数据表...')
    app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
    create_tables(drop_first=drop_first)

    # 3. 插入示例数据
    print(f'\n[3/3] 插入示例数据...')
    seed_data()

    print('\n' + '=' * 50)
    print('  初始化完成！运行: python app.py')
    print('=' * 50)

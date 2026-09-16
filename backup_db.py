"""
============================================================
数据库备份 / 恢复工具
============================================================
背景：本项目曾发生一次真实事故 —— 一个临时排查脚本里调用了
`db.drop_all()`，而它直接作用在 MySQL 真实库上（Flask-SQLAlchemy
在 `db.init_app(app)` 时已按 MySQL 建好引擎，之后改配置不生效），
导致 buildings / seats / users / sensor_devices 等表被清空。
最终靠 MySQL binlog（ROW 格式 + FULL 行镜像）恢复了座位与用户数据。

结论：**任何会写库的临时脚本，先在真库上做备份。**

用法：
  python backup_db.py                # 备份到 backups/ 目录
  python backup_db.py --list         # 列出已有备份
  python backup_db.py --restore <文件>   # 从备份恢复（会覆盖现有数据！）

注意：备份文件包含用户密码哈希等敏感信息，已加入 .gitignore，请勿提交。
"""
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import Config

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')

# 常见 MySQL 安装位置（可用 MYSQL_BIN 环境变量覆盖）
MYSQL_BIN_CANDIDATES = [
    os.getenv('MYSQL_BIN', ''),
    r'D:\MySQL\MySQL Server 8.0\bin',
    r'C:\Program Files\MySQL\MySQL Server 8.0\bin',
    r'C:\Program Files\MySQL\MySQL Server 8.4\bin',
    r'C:\xampp\mysql\bin',
]


def find_tool(name):
    """定位 mysqldump / mysql 可执行文件。"""
    for d in MYSQL_BIN_CANDIDATES:
        if not d:
            continue
        exe = os.path.join(d, name + ('.exe' if os.name == 'nt' else ''))
        if os.path.exists(exe):
            return exe
    # 回退：PATH 中查找
    from shutil import which
    return which(name)


def do_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dump = find_tool('mysqldump')
    if not dump:
        print('[x] 找不到 mysqldump，请设置环境变量 MYSQL_BIN 指向 MySQL 的 bin 目录')
        return 1

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = os.path.join(BACKUP_DIR, 'seat_navigation_%s.sql' % ts)
    cmd = [dump,
           '-h', Config.DB_HOST, '-P', str(Config.DB_PORT),
           '-u', Config.DB_USER, '-p' + Config.DB_PASSWORD,
           '--single-transaction', '--routines', '--events',
           '--default-character-set=utf8mb4',
           Config.DB_NAME]
    with open(out, 'wb') as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
    if p.returncode != 0:
        err = p.stderr.decode('utf-8', 'ignore')
        # 密码错误等敏感信息不打印
        print('[x] 备份失败（退出码 %s）' % p.returncode)
        print('    ' + err.strip().splitlines()[-1][:160] if err.strip() else '')
        if os.path.exists(out):
            os.remove(out)
        return 1

    size = os.path.getsize(out)
    print('[√] 备份完成：%s（%.1f KB）' % (out, size / 1024))
    return 0


def do_list():
    if not os.path.isdir(BACKUP_DIR):
        print('（还没有备份）')
        return 0
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith('.sql'))
    if not files:
        print('（还没有备份）')
        return 0
    for f in files:
        p = os.path.join(BACKUP_DIR, f)
        print('  %-40s %8.1f KB  %s' % (
            f, os.path.getsize(p) / 1024,
            datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')))
    return 0


def do_restore(path):
    if not os.path.exists(path):
        print('[x] 备份文件不存在：%s' % path)
        return 1
    mysql = find_tool('mysql')
    if not mysql:
        print('[x] 找不到 mysql 客户端')
        return 1
    print('!! 即将用 %s 覆盖当前数据库 %s' % (os.path.basename(path), Config.DB_NAME))
    if input('   确认请输入 yes：').strip().lower() != 'yes':
        print('    已取消')
        return 1
    cmd = [mysql, '-h', Config.DB_HOST, '-P', str(Config.DB_PORT),
           '-u', Config.DB_USER, '-p' + Config.DB_PASSWORD,
           '--default-character-set=utf8mb4', Config.DB_NAME]
    with open(path, 'rb') as f:
        p = subprocess.run(cmd, stdin=f, stderr=subprocess.PIPE)
    if p.returncode != 0:
        print('[x] 恢复失败：', p.stderr.decode('utf-8', 'ignore')[:200])
        return 1
    print('[√] 恢复完成')
    return 0


if __name__ == '__main__':
    if '--list' in sys.argv:
        sys.exit(do_list())
    if '--restore' in sys.argv:
        i = sys.argv.index('--restore')
        if i + 1 >= len(sys.argv):
            print('用法: python backup_db.py --restore <备份文件>')
            sys.exit(1)
        sys.exit(do_restore(sys.argv[i + 1]))
    sys.exit(do_backup())

# -*- coding: utf-8 -*-
"""清理测试账号 + 列出真实账号状态（不输出密码）"""
import pymysql

env = {}
for line in open(r'D:\MAX_xiangmu\.env', encoding='utf-8'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()

conn = pymysql.connect(
    host=env.get('DB_HOST', '127.0.0.1'),
    port=int(env.get('DB_PORT', 3306)),
    user=env.get('DB_USER', 'root'),
    password=env.get('DB_PASSWORD', ''),
    database=env.get('DB_NAME', 'seat_navigation'),
    charset='utf8mb4',
)
with conn.cursor() as cur:
    cur.execute("DELETE FROM users WHERE student_id LIKE 'dsh_test_%'")
    print('deleted test users:', cur.rowcount)
    cur.execute(
        "SELECT id, student_id, name, role, is_approved, is_active, "
        "DATE_FORMAT(last_login_at, '%%Y-%%m-%%d %%H:%%i') FROM users ORDER BY id")
    print('现有账号:')
    for r in cur.fetchall():
        print('  id=%s  %s  %s  角色=%s  已审核=%s  启用=%s  上次登录=%s' % r)
conn.commit()
conn.close()

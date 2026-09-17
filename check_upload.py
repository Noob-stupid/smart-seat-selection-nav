# -*- coding: utf-8 -*-
"""云端上传路径诊断 —— 在服务器上运行，一次把真相全打出来。

用法（在服务器项目目录下）：
    ./.venv/bin/python check_upload.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db                       # noqa: E402
from models.building import Floor, Building, uploads_url   # noqa: E402
from config import Config                     # noqa: E402

print('=' * 66)
print(' 1. 楼层表里存的路径 vs 算出来的 URL')
print('=' * 66)
with app.app_context():
    floors = Floor.query.order_by(Floor.id).all()
    if not floors:
        print('  （floors 表是空的）')
    for f in floors:
        b = db.session.get(Building, f.building_id)
        print('  floor id=%-3s  %s-%s' % (f.id, b.name if b else '?', f.floor_number))
        print('      floor_plan_path = %r' % f.floor_plan_path)
        print('      -> floor_plan_url = %r' % uploads_url(f.floor_plan_path))
        if f.road_network_path:
            print('      road_network_path = %r' % f.road_network_path)

print()
print('=' * 66)
print(' 2. uploads 目录里实际有什么文件')
print('=' * 66)
root = Config.UPLOAD_FOLDER
print('  UPLOAD_FOLDER =', root)
print('  存在 =', os.path.isdir(root))
if os.path.isdir(root):
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        print('  [%s]  权限=%s' % (rel, oct(os.stat(dirpath).st_mode)[-3:]))
        for fn in filenames[:8]:
            fp = os.path.join(dirpath, fn)
            print('      %-52s %8d bytes  权限=%s'
                  % (fn, os.path.getsize(fp), oct(os.stat(fp).st_mode)[-3:]))
            n += 1
        if len(filenames) > 8:
            print('      ... 还有 %d 个' % (len(filenames) - 8))
        n += max(0, len(filenames) - 8)
    print('  文件总数 =', n)

print()
print('=' * 66)
print(' 3. 数据库里的路径是否在磁盘上真实存在')
print('=' * 66)
with app.app_context():
    for f in Floor.query.all():
        p = f.floor_plan_path
        if not p:
            continue
        cands = []
        if os.path.isabs(p):
            cands.append(p)
        # 相对项目根 / uploads 目录的可能写法
        cands.append(os.path.join(app.root_path, p.lstrip('/')))
        cands.append(os.path.join(root, os.path.basename(p)))
        # 补上 shared / school_N
        for sub in ('shared', 'school_1', 'school_2', 'school_3'):
            cands.append(os.path.join(root, sub, os.path.basename(p)))
        hit = [c for c in cands if os.path.exists(c)]
        print('  floor %s: %r' % (f.id, p))
        if hit:
            for h in hit:
                print('      ✓ 实际存在: %s' % h)
        else:
            print('      ✗ 这些候选路径都不存在:')
            for c in cands[:4]:
                print('         %s' % c)

print()
print('=' * 66)
print(' 4. Flask 自己解析 /uploads/<path> 是否正常')
print('=' * 66)
app.config['TESTING'] = True
with app.test_client() as c:
    with app.app_context():
        first = None
        for f in Floor.query.all():
            u = uploads_url(f.floor_plan_path)
            if u:
                first = u
                break
    if first:
        r = c.get(first)
        print('  GET %s -> %s (%d bytes)' % (first, r.status_code, len(r.data)))
    else:
        print('  （没有可测的平面图 URL）')
print()
print('诊断结束。把以上全部输出发回给我即可。')

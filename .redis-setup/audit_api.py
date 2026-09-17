# -*- coding: utf-8 -*-
"""合并后前后端接口自动化核对：前端所有 /api/ 调用 vs 后端路由"""
import re, glob, sys

frontend_paths = set()
for f in glob.glob(r'D:\MAX_xiangmu\static\js\**\*.js', recursive=True) + \
        glob.glob(r'D:\MAX_xiangmu\templates\**\*.html', recursive=True):
    if 'checkin.js' in f:
        continue
    with open(f, encoding='utf-8', errors='ignore') as fh:
        txt = fh.read()
    for m in re.finditer(r"['\"`](/api/[A-Za-z0-9_/${}.\-]+)['\"`]", txt):
        p = re.sub(r'\$\{[^}]*\}', '{P}', m.group(1))
        frontend_paths.add(p)

routes = set()
with open(r'D:\MAX_xiangmu\app.py', encoding='utf-8') as fh:
    txt = fh.read()
for m in re.finditer(r"@app\.route\('(/api/[^']+)'", txt):
    r = re.sub(r'<int:[^>]+>', '{P}', m.group(1))
    r = re.sub(r'<[^>]+>', '{P}', r)
    routes.add(r)


def match(fp):
    segs = fp.split('/')
    for r in routes:
        rsegs = r.split('/')
        if len(segs) != len(rsegs):
            continue
        ok = True
        for a, b in zip(segs, rsegs):
            if b == '{P}':
                continue
            if a != b:
                ok = False
                break
        if ok:
            return r
    return None


missing = []
for fp in sorted(frontend_paths):
    if not match(fp):
        missing.append(fp)

print('前端调用端点:', len(frontend_paths))
print('后端路由:', len(routes))
if missing:
    print('=== 未匹配的端点 ===')
    for m in missing:
        print(' ', m)
    sys.exit(1)
else:
    print('全部端点均有对应后端路由 OK')

# -*- coding: utf-8 -*-
"""重新生成参赛用的完整源代码包。

大赛通知第（三）条第 3 款：
  「作品源代码：参赛团队需要在大赛网站提交完整源代码，
    源代码中必须说明原创部分，第三方开源代码部分请在
    《软件创意设计文档》中标明。」

排除项（重要）：
  · .env / data/system_config.json —— 含 API 密钥、数据库口令
  · mobile/android/*.jks —— 安卓签名密钥
  · mobile/node_modules / android/build / .gradle —— 构建产物，几百 MB
  · backups / _binlog_dump / instance / uploads —— 运行时数据与用户上传
  · __pycache__ / .pytest_cache / .git / 打出来的 zip
"""
import io
import os
import re
import shutil
import zipfile

ROOT = r'D:\MAX_xiangmu'
STAGE = os.path.join(ROOT, '_srcpack')
OUT = os.path.join(ROOT, '★智座-源代码.zip')

INCLUDE = [
    'app.py', 'config.py', 'requirements.txt', 'pytest.ini',
    'setup_db.py', 'backup_db.py', 'make_cloud_pkg.py', 'build_native_bundle.py',
    'models', 'utils', 'templates', 'static', 'tests', 'view',
    'DEMO', 'mobile', 'docs',
    '.env.example', 'Dockerfile', 'docker-compose.yml', 'nginx.conf',
    '.dockerignore', '.gitignore',
]

SKIP_DIRS = {
    '__pycache__', '.pytest_cache', '.git', '.github', 'node_modules',
    'build', '.gradle', '.idea', 'instance', 'backups', '_binlog_dump',
    'uploads', '.pio', '_srcpack', '.superpowers', '.vscode', '.redis-setup',
    '作品简介-3张截图',
}
SKIP_FILES = {'.env', 'system_config.json', 'local.properties', 'package-lock.json'}
SKIP_EXT = {'.jks', '.keystore', '.apk', '.aab', '.zip', '.log', '.pyc', '.db', '.sqlite3'}

copied = []


def should_skip(path, name):
    if name in SKIP_FILES:
        return True
    if os.path.splitext(name)[1].lower() in SKIP_EXT:
        return True
    return any(p in SKIP_DIRS for p in path.split(os.sep))


# 临时目录删不掉时（图片被看图软件/浏览器锁住是常态），
# 换一个唯一名字继续，别让整个打包卡在清理上。
if os.path.exists(STAGE):
    try:
        shutil.rmtree(STAGE)
    except PermissionError:
        import time as _t
        STAGE = STAGE + '_%d' % int(_t.time())
        print('  · 旧临时目录被占用，改用 %s' % os.path.basename(STAGE))
os.makedirs(STAGE, exist_ok=True)

for item in INCLUDE:
    src = os.path.join(ROOT, item)
    if not os.path.exists(src):
        print('  · 跳过（不存在）%s' % item)
        continue
    if os.path.isfile(src):
        if not should_skip(item, os.path.basename(item)):
            shutil.copy2(src, os.path.join(STAGE, item))
            copied.append(item)
        continue
    for dp, dns, fns in os.walk(src):
        rel = os.path.relpath(dp, ROOT)
        dns[:] = [d for d in dns if not should_skip(rel, d)]
        for fn in fns:
            if should_skip(rel, fn):
                continue
            sp = os.path.join(dp, fn)
            rp = os.path.relpath(sp, ROOT)
            dst = os.path.join(STAGE, rp)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.copy2(sp, dst)
                copied.append(rp)
            except Exception as e:
                print('  · 复制失败 %s: %s' % (rp, e))

total = sum(os.path.getsize(os.path.join(STAGE, r.replace('/', os.sep)))
            for r in copied if os.path.exists(os.path.join(STAGE, r.replace('/', os.sep))))
print('已收集 %d 个文件，%.1f MB' % (len(copied), total / 1024 / 1024))

print()
print('=' * 68)
print('安全检查')
print('=' * 68)
danger = [r for r in copied
          if r.lower().endswith('.env') or 'system_config.json' in r.lower()
          or r.lower().endswith(('.jks', '.keystore')) or 'node_modules' in r.lower()]
if danger:
    print('  ★★ 剔除敏感文件：')
    for d in danger:
        print('     %s' % d)
        p = os.path.join(STAGE, d)
        if os.path.exists(p):
            os.remove(p)
    copied = [c for c in copied if c not in danger]
else:
    print('  ✓ 没有 .env / system_config.json / 签名密钥 / node_modules')

# 真实密钥零容忍
real_keys = []
for f in ('.env', os.path.join('data', 'system_config.json')):
    fp = os.path.join(ROOT, f)
    if os.path.exists(fp):
        try:
            t = io.open(fp, encoding='utf-8', errors='ignore').read()
            import json
            if fp.endswith('.json'):
                d = json.loads(t)
                for k in ('ai_api_key', 'nav_map_key', 'nav_map_security_code'):
                    v = d.get(k)
                    if v and len(str(v)) > 12:
                        real_keys.append(str(v))
        except Exception:
            pass
leak = 0
for dp, _d, fns in os.walk(STAGE):
    for fn in fns:
        fp = os.path.join(dp, fn)
        if os.path.getsize(fp) > 3 * 1024 * 1024:
            continue
        try:
            t = io.open(fp, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        for k in real_keys:
            if k in t:
                print('  ★★ %s 含真实密钥！' % os.path.relpath(fp, STAGE))
                leak += 1
print('  ✓ 真实密钥未入库' if leak == 0 else '  ★★ 有 %d 处泄露' % leak)

# 把《原创说明》放到包的根 —— 大赛要求「源码中必须说明原创部分」，
# 这份文件就是那份说明。源文件常驻 docs/原创说明.md（不再放临时目录，
# 免得下次打包时又忘了带上）。
_README_SRC = os.path.join(ROOT, 'docs', '原创说明.md')
if os.path.exists(_README_SRC):
    shutil.copy2(_README_SRC, os.path.join(STAGE, 'README-原创说明.md'))
    copied.append('README-原创说明.md')
else:
    print('  ★★ 警告：docs/原创说明.md 不存在，包里会缺《原创说明》！')

# 把设计文档与作品简介也放进去，方便评委对照
os.makedirs(os.path.join(STAGE, 'docs'), exist_ok=True)
for f, dst in [(r'docs\智座-设计文档.pdf', 'docs/智座-设计文档.pdf'),
               (r'docs\作品简介.txt', 'docs/作品简介.txt'),
               (r'docs\设计文档-智座.html', 'docs/设计文档-智座（源文件）.html'),
               (r'docs\原创说明.md', 'docs/原创说明.md')]:
    p = os.path.join(ROOT, f)
    if os.path.exists(p):
        shutil.copy2(p, os.path.join(STAGE, dst.replace('/', os.sep)))

if os.path.exists(OUT):
    os.remove(OUT)
n = 0
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
    for dp, _d, fns in os.walk(STAGE):
        for fn in fns:
            fp = os.path.join(dp, fn)
            z.write(fp, os.path.join('智座-源代码', os.path.relpath(fp, STAGE)))
            n += 1
shutil.rmtree(STAGE, ignore_errors=True)
print()
print('★智座-源代码.zip  %d 个文件  %.1f MB' % (n, os.path.getsize(OUT) / 1024 / 1024))

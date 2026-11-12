# -*- coding: utf-8 -*-
"""全量打「云更新.zip」。

不再用增量比对（make_cloud_pkg.py 那套按特征串判断"云端是否已是最新"
反复漏文件，改一处漏一处，已经踩过三次）。这次直接把所有服务端与前端
文件整份打进去，覆盖即可，不看云端状态。

输出：D:\\MAX_xiangmu\\云更新.zip
"""
import os
import zipfile

ROOT = r'D:\MAX_xiangmu'
OUT = os.path.join(ROOT, '云更新.zip')

# 服务端：整份带
ROOT_FILES = ['app.py', 'config.py', 'requirements.txt']
DIRS = ['models', 'utils']

# 前端：只带会被改动的页面与脚本（vendor 是第三方库，没动过）
STATIC = [
    'static/js/admin/floor_plan.js',
    'static/js/uploading.js',
    'static/js/app.js',
    'static/js/api-client.js',
    'static/js/seat_map.js',
    'static/js/navigation.js',
    'static/js/ai-assistant.js',
    'static/js/native-bundle.js',
    'static/css/base.css',
    'static/css/pages/uploading.css',
    'static/css/pages/floor_plan.css',
]
TEMPLATES = [
    'templates/uploading.html',
    'templates/admin/floor_plan.html',
    'templates/seat_map.html',
    'templates/navigation.html',
    'templates/index.html',
    'templates/login.html',
    'templates/base.html',
]

SKIP_NAMES = {'__pycache__', '.pyc', '.git', 'node_modules'}


def add_file(z, rel, added):
    src = os.path.join(ROOT, rel.replace('/', os.sep))
    if not os.path.exists(src):
        return False
    z.write(src, rel)
    added.append(rel)
    return True


def main():
    if os.path.exists(OUT):
        os.remove(OUT)

    added = []
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in ROOT_FILES:
            add_file(z, f, added)

        for d in DIRS:
            base = os.path.join(ROOT, d)
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [x for x in dirnames if x not in SKIP_NAMES]
                for fn in filenames:
                    if not fn.endswith('.py'):
                        continue
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, ROOT).replace('\\', '/')
                    z.write(full, rel)
                    added.append(rel)

        for f in STATIC + TEMPLATES:
            add_file(z, f, added)

        # 说明
        note = [
            '云更新包（全量）',
            '',
            '用法：解压后把里面的文件按相同路径覆盖到 /www/wwwroot/seatnav/',
            '      app.py / config.py / utils/ 改了要重启 gunicorn；',
            '      static/ 与 templates/ 是 nginx 直接读磁盘，不用重启，浏览器 Ctrl+F5 强刷即可。',
            '',
            '重启命令（--timeout 300 不能省）：',
            '  pkill -f "venv/bin/gunicorn"',
            '  sleep 2',
            '  cd /www/wwwroot/seatnav',
            '  ./venv/bin/gunicorn -k eventlet -w 1 -b 0.0.0.0:5800 app:app --daemon --timeout 300',
            '',
            '若还没装依赖（首次更新时要做）：',
            '  ./venv/bin/pip uninstall -y opencv-python opencv-contrib-python',
            '  ./venv/bin/pip install -r requirements.txt',
            '',
            '验证：',
            '  ./venv/bin/python -c "import ezdxf; print(ezdxf.__version__)"   # 期望 1.4.5',
            '',
            '本包含 %d 个文件：' % len(added),
        ] + ['  ' + a for a in added]
        z.writestr('说明.txt', '\n'.join(note))

    print('  输出：%s' % OUT)
    print('  大小：%.0f KB' % (os.path.getsize(OUT) / 1024))
    print('  文件 %d 个：' % len(added))
    for a in added:
        print('    ' + a)


if __name__ == '__main__':
    main()

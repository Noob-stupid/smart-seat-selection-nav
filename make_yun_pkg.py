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

# 前端：扫目录而不是写死清单。
#
# 以前这里是三张硬编码列表，结果反复漏文件 —— 加了 static/js/admin/hardware.js、
# static/js/reservation.js、templates/admin/hardware.html、templates/reservation.html
# 都没跟上，用户传上去发现功能没变，白折腾一轮。
# 改成扫目录，新增的页面/脚本自动进包，不用每次记得改这里。
#
# 唯一要排除的是 static/vendor/：第三方库（Vue、fontawesome）没动过，
# 体积大且没必要每次重传。
SCAN_DIRS = ['static/js', 'static/css', 'templates']
SCAN_SKIP_PREFIX = ('static/vendor/',)
SCAN_EXTS = ('.js', '.css', '.html')

SKIP_NAMES = {'__pycache__', '.pyc', '.git', 'node_modules'}


def collect_frontend():
    """把 static/js、static/css、templates 下的前端文件全收进来。

    返回按路径排序的列表，保证每次打包顺序一致（便于比对包内容）。
    """
    out = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d.replace('/', os.sep))
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_NAMES]
            for fn in filenames:
                if not fn.endswith(SCAN_EXTS):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace('\\', '/')
                if any(rel.startswith(p) for p in SCAN_SKIP_PREFIX):
                    continue
                out.append(rel)
    return sorted(out)


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

        for f in collect_frontend():
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

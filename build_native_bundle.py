# -*- coding: utf-8 -*-
"""把移动端原生脚本合并成 native-bundle.js（供 app.js 自动加载）。

合并顺序（有依赖关系，不要随意调整）：
  1. native-bridge.js     原生能力桥（window.Native）
  2. native-settings.js   设置面板 + 7 个开关（window.NativeSettings）
  3. native-features.js   功能实现（window.Feat）—— 依赖上面两个
  4. app-shell.js         移动端外壳（顶栏/底部Tab/抽屉）—— 依赖 window.Native

另外把 static/css/mobile-app.css 内联成 window.__APP_SHELL_CSS__，
这样 App 外壳不需要额外的 CSS 文件，云端只传 native-bundle.js 一个文件即可。
"""
import io
import json
import os
import shutil

ROOT = r'D:\MAX_xiangmu'

SRC = [
    'static/js/native-bridge.js',
    'static/js/native-settings.js',
    'static/js/native-features.js',
    'static/js/app-shell.js',
    'static/js/drag-fab.js',
]
CSS_SRC = 'static/css/mobile-app.css'
OUT = os.path.join(ROOT, 'static', 'js', 'native-bundle.js')

HEAD = '''/* ============================================================
   智座 · 移动端原生能力包（自动合并生成，请勿直接改本文件）
   ------------------------------------------------------------
   由以下源文件按顺序合并而成：
     static/js/native-bridge.js    原生能力桥（扫码/语音/通知/定位/缓存）
     static/js/native-settings.js  设置面板 + 7 个功能开关（默认全开）
     static/js/native-features.js  功能实现（扫码占座/语音/提醒/围栏/传感器导航）
     static/js/app-shell.js        移动端外壳（顶部细条 + 底部 Tab + 侧边抽屉）
     static/css/mobile-app.css     外壳样式（已内联为 __APP_SHELL_CSS__）
   改功能请改上面这些源文件，再跑 _buildbundle.py 重新合并。
   本文件由 app.js 自动加载，因此所有页面都能用，无需改模板；
   浏览器里自动降级，界面与原来完全一致。
   ============================================================ */

'''

parts = [HEAD]

# 外壳样式内联（避免多传一个 css 文件，也少一次请求）
css_path = os.path.join(ROOT, CSS_SRC.replace('/', os.sep))
css = io.open(css_path, encoding='utf-8').read()
parts.append('/* ================= %s (内联) ================= */\n' % os.path.basename(CSS_SRC))
parts.append('window.__APP_SHELL_CSS__ = %s;\n\n' % json.dumps(css, ensure_ascii=False))

for rel in SRC:
    p = os.path.join(ROOT, rel.replace('/', os.sep))
    body = io.open(p, encoding='utf-8').read()
    parts.append('/* ================= %s ================= */\n' % os.path.basename(rel))
    parts.append(body.rstrip() + '\n\n')

data = ''.join(parts)
io.open(OUT, 'w', encoding='utf-8', newline='\n').write(data)

# 同步给 App（Capacitor 内置一份，离线也能用）
for d in ('mobile/www', 'mobile/android/app/src/main/assets/public'):
    dst = os.path.join(ROOT, d.replace('/', os.sep), 'native-bundle.js')
    if os.path.isdir(os.path.dirname(dst)):
        shutil.copy2(OUT, dst)
        print('同步 -> %s' % dst)

print('生成 %s  (%.1f KB, CSS %.1f KB)' % (
    OUT, os.path.getsize(OUT) / 1024, len(css.encode('utf-8')) / 1024))

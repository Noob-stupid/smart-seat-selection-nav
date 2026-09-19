# -*- coding: utf-8 -*-
"""算一遍云端还缺什么，只把缺的打包。

判定方式分两类：
  · static/ 下的 js/css —— nginx 直接发磁盘文件，逐字节比对即可
  · templates/*.html    —— Flask 渲染，比字节没意义，改用特征串探测
  · app.py / config.py  —— 服务端代码，只能整体替换 + 重启
"""
import hashlib
import io
import json
import os
import random
import shutil
import urllib.request
import zipfile

ROOT = r'D:\MAX_xiangmu'
BASE = 'https://zhinengzuo.site'
DEST = os.path.join(ROOT, '_pkg')
ZIP = os.path.join(ROOT, '★云端更新.zip')

# 静态文件：按哈希比对
# 注意：只列「服务器上本来就单独存在」的文件。
# native-bridge/settings/features/app-shell/drag-fab/mobile-app.css 这些
# 只存在于 native-bundle.js 内部（css 也内联了），云端本来就没有这些单独文件，
# 传了也没用，所以不列。
STATIC = [
    'static/js/native-bundle.js',
    'static/js/login.js',
    'static/js/navigation.js',
    'static/js/outdoor.js',
    'static/js/reservation.js',
    'static/js/app.js',
    'static/js/admin/floor_plan.js',
    'static/js/seat_map.js',
    'static/js/ai-assistant.js',
    'static/css/base.css',
    'static/css/pages/login.css',
    # ★ 自托管的前端依赖：以前指向 cdn.jsdelivr.net（实测 6/6 失败），
    #   一挂整页就变成未渲染的 ${ }。这些必须一起传，少一个页面就白。
    'static/vendor/vue.global.prod.js',
    'static/vendor/axios.min.js',
    'static/vendor/socket.io.min.js',
    'static/vendor/fontawesome/css/all.min.css',
    'static/vendor/fontawesome/webfonts/fa-solid-900.woff2',
    'static/vendor/fontawesome/webfonts/fa-regular-400.woff2',
    'static/vendor/fontawesome/webfonts/fa-brands-400.woff2',
]

# 模板：特征串探测（值 = 必须出现的关键串）
TEMPLATES = {
    'templates/index.html': ['智座'],
    'templates/login.html': ['<h2>智座</h2>', 'interactive-widget', 'scrollIntoView',
                             'name="username"', 'autocomplete="current-password"'],
    'templates/seat_map.html': ['智座'],
    'templates/navigation.html': ['智座', ':width="floorPlanWidth || 800"',
                                  '推算位置', 'routeResult.network_note'],
    'templates/outdoor.html': ['智座', 'v-if="radar"', '我的坐标'],
    'templates/reservation.html': ['智座'],
    'templates/profile.html': ['智座'],
    'templates/register.html': ['智座'],
    # terminal.html 是终端大屏页，本来就没有导航栏（自带标题「智能座位导引」），
    # 所以不检查品牌
    'templates/uploading.html': ['智座'],
    'templates/admin/ai.html': ['智座'],
    'templates/admin/approvals.html': ['智座'],
    'templates/admin/behavior.html': ['智座'],
    'templates/admin/buildings.html': ['智座'],
    'templates/admin/dashboard.html': ['智座'],
    'templates/admin/floor_plan.html': ['智座'],
    'templates/admin/hardware.html': ['智座'],
    'templates/admin/seats_qrcodes.html': ['智座'],
    'templates/admin/settings.html': ['智座', '地图与导航', 'nav_map_security_code'],
    'templates/admin/students.html': ['智座'],
    'templates/admin/video.html': ['智座'],
}

# 服务端代码：只有 app.py 这次改过（config.py 上次已生效，未再改动）
# 服务端代码：外网看不出内容，只能整包带上，配合重启生效。
# utils/ 下的模块也要带 —— 寻路、推荐、AI 服务都在这里，
# 以前漏了 utils/navigation.py，改了半天云端还是老逻辑。
SERVER = ['app.py', 'config.py',
          'utils/navigation.py', 'utils/ai_context.py', 'utils/recommendation.py',
          'utils/ai_service.py',
          # AI 智能体：工具定义 + 循环 + 带工具调用的 LLM 客户端
          'utils/ai_tools.py', 'utils/ai_agent.py', 'utils/llm.py']


# 登录后的会话 cookie。
# ★ 必须登录才能查管理页：/admin/<name>.html 这类别名路由已经挂了鉴权，
#   未登录会 302 跳登录页 —— 那样每个管理模板都会被误判成「要传」。
COOKIE = {'value': ''}


def _login():
    """用超管账号登录，拿一份 cookie 供后续查管理页用。

    账号口令不写死在代码里 —— 从环境变量读，读不到再退回 .env：
        PKG_ADMIN_USER / PKG_ADMIN_PASS
    （这套口令在《设计文档》里本来就按大赛要求公开，但脚本里硬编码一份
      仍然不专业，而且改口令时要满仓库找。）
    """
    try:
        user = os.getenv('PKG_ADMIN_USER', '').strip()
        pwd = os.getenv('PKG_ADMIN_PASS', '').strip()
        if not user or not pwd:
            # 退回读 .env（本地开发时通常已经填好了）
            try:
                for line in io.open(os.path.join(ROOT, '.env'), encoding='utf-8'):
                    if line.startswith('PKG_ADMIN_USER='):
                        user = line.split('=', 1)[1].strip().strip('"\'')
                    elif line.startswith('PKG_ADMIN_PASS='):
                        pwd = line.split('=', 1)[1].strip().strip('"\'')
            except Exception:
                pass
        if not user or not pwd:
            print('  · 未配置 PKG_ADMIN_USER / PKG_ADMIN_PASS，跳过管理页比对')
            return False
        body = json.dumps({'student_id': user, 'password': pwd}).encode()
        req = urllib.request.Request(
            BASE + '/api/auth/login', data=body,
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            ck = '; '.join(c.split(';')[0] for c in (r.headers.get_all('Set-Cookie') or []))
        COOKIE['value'] = ck
        return bool(ck)
    except Exception as e:
        print('  ★ 登录失败（管理页将无法比对，可能误报「要传」）：%s' % e)
        return False


def fetch(url):
    u = BASE + url + ('&' if '?' in url else '?') + 'n=' + str(random.randint(10 ** 8, 10 ** 9))
    h = {'Cache-Control': 'no-store'}
    if COOKIE['value']:
        h['Cookie'] = COOKIE['value']
    req = urllib.request.Request(u, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception as e:
        return b'ERR:' + str(e).encode()


def local(rel):
    p = os.path.join(ROOT, rel.replace('/', os.sep))
    return io.open(p, 'rb').read() if os.path.exists(p) else None


need = []

# 先登录：管理页别名路由已挂鉴权，未登录会 302 跳登录页，
# 那样每个管理模板都会被误判成「要传」。
if not _login():
    print('  （未登录也能继续，但管理页模板的比对结果不可信）')

print('=' * 76)
print('1. 静态文件（nginx 直接发，逐字节比对）')
print('=' * 76)
for rel in STATIC:
    lb = local(rel)
    if lb is None:
        print('  %-34s 本地没有，跳过' % rel)
        continue
    cb = fetch('/' + rel)
    if cb.startswith(b'ERR:'):
        print('  %-34s 云端取不到 -> 要传' % rel)
        need.append(rel)
        continue
    if hashlib.sha256(lb).hexdigest() == hashlib.sha256(cb).hexdigest():
        print('  %-34s 一致 ✓' % rel)
    else:
        print('  %-34s ★ 不同（本地 %d / 云端 %d）-> 要传' % (rel, len(lb), len(cb)))
        need.append(rel)

print()
print('=' * 76)
print('2. 页面模板（Flask 渲染，按特征串判断）')
print('=' * 76)
tpl_need = []
for rel, feats in sorted(TEMPLATES.items()):
    name = os.path.basename(rel)
    url = ('/admin/' + name) if '/admin/' in rel else ('/' + name)
    body = fetch(url).decode('utf-8', 'replace')
    # 所有页面都必须已经改成引用自托管依赖 —— 只要还有页面指向 jsdelivr，
    # 它一挂那个页面就是满屏未渲染的 ${ }（Vue 加载不到，createApp 抛错）
    miss = [f for f in feats if f not in body]
    if 'cdn.jsdelivr.net' in body:
        miss.append('仍引用外部 CDN')
    elif '/static/vendor/vue' not in body:
        miss.append('未指向自托管 Vue')
    if miss:
        tpl_need.append(rel)
        print('  %-34s ★ 缺: %s' % (rel, ', '.join(miss)))
    else:
        print('  %-34s 已是最新 ✓' % rel)
need += tpl_need

print()
print('=' * 76)
print('3. 服务端代码（必须配合重启服务）')
print('=' * 76)
for rel in SERVER:
    print('  %-34s 随包一起传（内容无法从外网比对）' % rel)
need = SERVER + need

print()
print('=' * 76)
print('合计需要上传 %d 个文件' % len(need))
print('=' * 76)

# ---------------- --changed-only：只打「跟上一包比确实变了」的文件 ----------------
#
# 服务端代码（app.py / utils/*.py）的内容从外网读不到，没法跟云端比对，
# 所以默认整份带上。但那样包里会混进一堆没改过的旧文件，翻包时很迷惑。
#
# 这里改用「与上一包的哈希清单比对」：
#   · 每次打包把本次带了哪些文件、各自 sha256 记进 _pkg_history.json
#   · 下次某文件的哈希和上次一样 → 说明上一包已经带过了 → --changed-only 时跳过
# 不依赖时间，也不依赖外网可读性。
#
# ★ 这一段必须在下面「复制文件」之前 —— 先把要带的文件定下来，再拷。
import json as _json
import sys as _sys

HIST = os.path.join(ROOT, '_pkg_history.json')
CHANGED_ONLY = '--changed-only' in _sys.argv


def _sha(path):
    import hashlib as _h
    with io.open(path, 'rb') as f:
        return _h.sha256(f.read()).hexdigest()


prev = {}
if os.path.exists(HIST):
    try:
        prev = (_json.loads(io.open(HIST, encoding='utf-8').read()) or {}).get('files', {})
    except Exception:
        prev = {}

if CHANGED_ONLY:
    _kept, _skipped = [], []
    for r in need:
        lp = os.path.join(ROOT, r.replace('/', os.sep))
        if r in SERVER and prev.get(r) and os.path.exists(lp) and _sha(lp) == prev[r]:
            _skipped.append(r)
        else:
            _kept.append(r)
    need = _kept
    print('  [--changed-only] 与上一包比对：跳过 %d 个内容未变的文件' % len(_skipped))
    for r in _skipped:
        print('      - %s' % r)

# ---------------- 复制文件（过滤之后）----------------
if os.path.exists(DEST):
    shutil.rmtree(DEST)
missing = []
for rel in need:
    src = os.path.join(ROOT, rel.replace('/', os.sep))
    if not os.path.exists(src):
        missing.append(rel)
        print('  ★ 警告：本地找不到 %s，已跳过' % rel)
        continue
    dst = os.path.join(DEST, rel.replace('/', os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
if missing:
    need = [r for r in need if r not in missing]
    print('  （缺 %d 个文件，其余照常打包）' % len(missing))



def _mtime(rel):
    import datetime
    p = os.path.join(ROOT, rel.replace('/', os.sep))
    return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%m-%d %H:%M')


# 把包内文件分成两类，别混在一起 ——
#   changed: 与云端比对后发现真的不同（static/templates 能比对出来）
#   vendor : 服务端代码，外网读不到内容，无法比对，只能整份带上。
#            但要说清楚它「是不是本轮改的」，否则用户翻包会以为塞了旧文件。
changed_rows, carried_rows = [], []
for rel in sorted(need):
    p = os.path.join(DEST, rel.replace('/', os.sep))
    if not os.path.exists(p):
        continue
    size = os.path.getsize(p)
    rel_posix = rel.replace(os.sep, '/')
    row = '  %-38s %8d B   本地改于 %s' % (rel_posix, size, _mtime(rel))
    if rel in SERVER:
        carried_rows.append(row)
    else:
        changed_rows.append(row)

# 服务端文件里，哪些确实是这一两天动过的？单独标出来。
recent_cut = None
try:
    import time as _t
    recent_cut = _t.time() - 2 * 86400
except Exception:
    pass


def _is_recent(rel):
    if recent_cut is None:
        return True
    return os.path.getmtime(os.path.join(ROOT, rel.replace('/', os.sep))) >= recent_cut


recent_server = [r for r in SERVER if r in need and _is_recent(r)]
old_server = [r for r in SERVER if r in need and not _is_recent(r)]

NOTE = '''════════════════════════════════════════════════════════════════════
  智座 · 云端更新包（共 %(n)d 个文件）
════════════════════════════════════════════════════════════════════

  目录结构和服务器一致。解压后把 app.py / config.py / utils / static /
  templates 拖到 /www/wwwroot/seatnav 覆盖即可。

────────────────────────────────────────────────────────────────────
 ① 与云端比对后确认不同（static / templates，内容能直接从外网读到）
────────────────────────────────────────────────────────────────────
%(changed)s

────────────────────────────────────────────────────────────────────
 ② 服务端代码（app.py / utils/*.py）
    ★ 这些文件的内容外网读不到，没法比对，所以整份带上以确保一致。
      它们**全部是本地当前最新版**，不是旧文件。
────────────────────────────────────────────────────────────────────

  ▌本轮确实改动过的（%(nrecent)d 个，必须传）：
%(recent)s

  ▌本轮没动过、但一并带上以保证一致的（%(nold)d 个）：
%(old)s

  （如果你确定之前已经传过这些没动过的文件，跳过它们也不影响；
    但一起覆盖最省心，它们就是本地最新版。）

────────────────────────────────────────────────────────────────────
 ⚠️ 传完必须重启 gunicorn（app.py 改了）
────────────────────────────────────────────────────────────────────

    pkill -f "venv/bin/gunicorn"
    sleep 2
    cd /www/wwwroot/seatnav
    ./venv/bin/gunicorn -k eventlet -w 1 -b 0.0.0.0:5800 app:app --daemon
    sleep 3
    ps -eo pid,ppid,etime,args | grep "[g]unicorn"
    curl -s -o /dev/null -w "%%{http_code}\\n" http://127.0.0.1:5800/api/status

  （static/ 是 nginx 直接发磁盘文件，不重启也生效；
    app.py 与 utils/ 改了，必须重启，否则后端还是老逻辑。）

════════════════════════════════════════════════════════════════════
''' % {
    'n': len(changed_rows) + len(carried_rows),
    'changed': '\n'.join(changed_rows) if changed_rows else '  （本轮没有需要覆盖的静态文件或模板）',
    'nrecent': len(recent_server),
    'recent': '\n'.join('  ' + r for r in recent_server) if recent_server else '  （无）',
    'nold': len(old_server),
    'old': '\n'.join('  ' + r for r in old_server) if old_server else '  （无）',
}

# ---------------------------------------------------------------------------
# 本轮修复清单 —— 每轮打包前更新这一段，它会被写进包里的 ★说明.txt
# ---------------------------------------------------------------------------
FIXES = '''────────────────────────────────────────────────────────────────────
 本轮改了什么
────────────────────────────────────────────────────────────────────

【1】AI 助手升级为「智能体」：能查数据，也能提议改系统（新）
   · 只读工具 5 个：列场所楼层 / 楼层统计 / 查座位 / 找空位 / 查设备在线。
     模型会真的去调这些工具拿实时数据，不再凭印象编座位号。
   · 写工具 3 个：开放·关闭座位 / 开关红外 / 关整层红外。
     ★ 模型**不允许直接执行** —— 只能提议。前端弹出确认卡片，
       用户点「确认执行」才落库，点「取消」就什么都不做。
       模型理解偏了（比如把"收拾一下 A 区"理解成关掉整区）也只是
       弹出一个错误的提议，不会真的改数据。
   · 管理后台的 AI 面板里可以直接用。

【2】修了一个安全洞：管理页 .html 别名路由没有鉴权（重要）
   · /admin/<name>.html 这个别名路由（让 /admin/settings.html 这种写法
     也能打开）以前是裸的，未登录就能取到后台页面。
   · 影响要说准：泄露的是页面外壳，真正的数据都走 /api/admin/*（有鉴权），
     不是数据泄露；但用户页面里确实有指向后台的链接（靠 JS 按角色隐藏），
     学生手敲地址就能进后台。
   · 已挂 @admin_required：未登录 → 302 跳登录；管理员正常打开。

【3】室外导航「步行路线规划失败」根治
   · 直接原因：加载高德 SDK 时没声明 plugin=AMap.Walking。
     高德 v2 把步行规划做成按需插件，不声明就永远加载不到，
     new AMap.Walking() 直接抛「is not a constructor」。
   · 另一个必要条件是安全密钥：路径规划属于 Web 服务，从 2021 年起
     必须配 securityJsCode，否则返回 INVALID_USER_SCODE。
     ★ 后台「系统设置 → 🗺️ 地图与导航」新增了 Key 与安全密钥输入框
       （以前后端支持但前台没有入口，根本填不了）。
   · 失败提示现在会带上高德原始错误码，并翻译成「缺安全密钥 / 配额用完 /
     Key 无效」，不再是一句笼统的失败。

【4】室外定位改用原生桥
   · 以前直接调 navigator.geolocation —— App 里是 Android WebView，
     这条路需要宿主处理权限回调，Capacitor 默认没接，必然失败；
     而 native-bridge.js 早就封装好了 Capacitor 插件（地理围栏一直在用）。
   · 现在先走原生桥，再退回浏览器 API。错误映射也补齐了插件返回的
     字符串码（OS-PLUG-GLOC-xxxx），不再一律显示「系统定位服务不可用」。

【5】路网断点自动搭桥
   · 手绘路网断成两截时，A* 找不到路径，只报「没有连通路径，请检查路网」，
     管理员对着图很难看出断在哪（实测那次只差 26 像素）。
   · 现在规划时自动把最近的缺口连上（只改内存邻接表，绝不写回磁盘，
     管理员画的线一根不动），并如实告知补了哪一处。
   · 绘图工具另修两个真 bug：
       · 新节点 id 用「节点个数」，节点数 34 时下一个也叫 p34 ——
         而路网里正好已有 p34，新画的点会**静默覆盖**它。
         现已改为「最大编号 +1」。
       · 「上一个节点」取的是 JSON 里最后一个键（跟绘制先后无关），
         自动连线会莫名接到随机节点上。现改为取编号最大的那个。
   · 保存路网时若检测到断点，会弹窗问「是否自动连起来」。

【6】座位「删除」的语义说清楚
   · 删除是**软删除**：记录保留（历史预约还在），只是不再对外显示。
     以前批量删除会静默吞掉错误、还无条件弹「已删除 N 个座位」，
     现在逐个统计真实成功/失败并分开提示。
   · 座位图默认不再显示已关闭座位（管理员之前会看到一堆灰色 ⊘，
     占图面又容易被误解成「这些座位坏了」）；要看请把筛选切到「已关闭」。

【7】前端依赖全部自托管，不再依赖外部 CDN
   · 页面所有库原来都从 cdn.jsdelivr.net 加载，实测连续 6 次全部失败。
     它一挂，Vue 加载不到 → createApp 抛错 → 整页渲染中断，
     浏览器只显示一堆未渲染的 ${ }。
   · 已把 Vue / axios / Socket.IO / Font Awesome 下到 static/vendor/ 自托管。
'''

NOTE = NOTE + FIXES


io.open(os.path.join(DEST, '★说明.txt'), 'w', encoding='utf-8').write(NOTE)

if os.path.exists(ZIP):
    os.remove(ZIP)
with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
    for r, _d, fs in os.walk(DEST):
        for fn in fs:
            fp = os.path.join(r, fn)
            z.write(fp, os.path.relpath(fp, DEST))
shutil.rmtree(DEST, ignore_errors=True)

print()
print('打包完成: %s  (%.0f KB)' % (ZIP, os.path.getsize(ZIP) / 1024))

# 记下清单，供下次 --changed-only 比对。
# ★ 必须「合并」而不是覆盖：
#   --changed-only 跑的时候 need 里只有变了的那几个，直接覆盖的话，
#   被跳过的文件就从清单里消失了 —— 下次它们又会被当成"新的"重新带上。
#   它们的内容没变、也确实已经发过，应当留在清单里。
try:
    _files = dict(prev)                     # 保留已知的
    for r in need:
        lp = os.path.join(ROOT, r.replace('/', os.sep))
        if os.path.exists(lp):
            _files[r] = _sha(lp)
    io.open(HIST, 'w', encoding='utf-8').write(_json.dumps(
        {'files': _files}, ensure_ascii=False, indent=1))
    print('已记录包内清单到 _pkg_history.json（本次 %d 个，累计 %d 个）'
          % (len(need), len(_files)))
except Exception as _e:
    print('记录清单失败（不影响包本身）: %s' % _e)

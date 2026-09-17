/* ============================================================
   移动端原生功能 · 全部实现
   ------------------------------------------------------------
   每个功能都受 NativeSettings 开关控制（默认全开），
   并监听 nativesettings:change 实时启停。

   功能清单
     1 扫码占座   scan     —— 原生相机 + 二维码 → 选座/签到
     2 语音选座   voice    —— 原生麦克风 → 意图识别 → 找座/预约/导航
     3 实时提醒   notify   —— 本地通知（预约到期 / 座位释放）
     4 地理围栏   geofence —— 基于建筑经纬度，进入/离开推送
     5 传感器导航 pdr      —— 加速度计步态推算 + 扫码锚定
     6 离线缓存   offline  —— 接口响应缓存，断网可看
     7 桌面快捷方式 shortcut —— 提示入口
   ============================================================ */
(function () {
  'use strict';

  if (!window.Native) { console.warn('[Feat] 缺少 native-bridge.js'); return; }
  var isApp = window.Native.available;

  /* ---------------- 通用工具 ---------------- */
  function toast(msg, type) {
    if (typeof window.showToast === 'function') { window.showToast(msg, type || 'success'); }
    console.log('[Feat]', msg);
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function el(tag, css, html) {
    var e = document.createElement(tag);
    if (css) e.setAttribute('style', css);
    if (html) e.innerHTML = html;
    return e;
  }
  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  async function on(key) {
    if (!window.NativeSettings) return true;
    return await window.NativeSettings.get(key);
  }
  function onChange(key, fn) {
    window.addEventListener('nativesettings:change', function (e) {
      if (e.detail && e.detail.key === key) fn(e.detail.value);
    });
  }

  /* 桌面快捷方式动作：MainActivity 把它拼在 URL 上
     （?autoscan=1 / ?autovoice=1），比注入 window.__SHORTCUT__ 可靠 ——
     注入的变量在页面跳转后会被新文档冲掉。 */
  function shortcutFromUrl() {
    try {
      var q = new URLSearchParams(location.search);
      if (q.get('autoscan') === '1') return 'scan';
      if (q.get('autovoice') === '1') return 'voice';
    } catch (e) { }
    return null;
  }

  /* 用掉一次就从地址栏抹掉，避免用户刷新时又触发一遍 */
  function clearShortcutParam() {
    try {
      var u = new URL(location.href);
      u.searchParams.delete('autoscan');
      u.searchParams.delete('autovoice');
      history.replaceState(null, '', u.pathname + (u.search || '') + (u.hash || ''));
    } catch (e) { }
  }
  async function apiGet(url, params) {
    if (window.api && window.api.get) return await window.api.get(url, params);
    var qs = params ? '?' + new URLSearchParams(params).toString() : '';
    var r = await fetch(url + qs, { credentials: 'same-origin' });
    return await r.json();
  }

  /* ============================================================
     1. 扫码占座
     ============================================================ */
  var ScanFeat = {
    async doScan(purpose) {
      if (!isApp) { toast('扫码需在 App 内使用', 'error'); return null; }
      if (!await on('scan')) { toast('扫码功能已在设置中关闭', 'error'); return null; }
      toast('正在打开相机…');
      var text = await window.Native.scanQrCode();
      if (!text) { toast('未识别到二维码', 'error'); return null; }
      window.Native.vibrate(60);
      console.log('[扫码]', purpose, '->', text);
      return text;
    },

    async scanForSeat() {
      var text = await this.doScan('seat');
      if (!text) return;
      // 二维码形如 RESV:<token> / SEAT:<id> / 纯座位号
      var m = /(\d+)/.exec(text);
      if (!m) { toast('二维码内容无法识别为座位号', 'error'); return; }
      location.href = 'reservation.html?seat_id=' + m[1];
    },

    async scanForCheckin() {
      var input = document.getElementById('checkin-token');
      var text = await this.doScan('checkin');
      if (!text || !input) return;
      input.value = text;
      toast('已扫码，正在签到…');
      if (typeof window.scanCheckin === 'function') window.scanCheckin();
    },

    /* --- PDR 锚点：扫到的码作为已知坐标 --- */
    async scanAnchor() {
      var text = await this.doScan('anchor');
      if (!text) return null;
      var m = /(\d+)/.exec(text);
      if (!m) return null;
      var sid = parseInt(m[1], 10);
      try {
        var res = await apiGet('/api/seats');
        var list = (res && res.data) || [];
        if (list.seats) list = list.seats;
        var seat = list.filter(function (s) { return s.id === sid; })[0];
        if (seat) {
          Pdr.anchor(seat.x, seat.y, seat.seat_label);
          toast('已锚定位置：' + seat.seat_label + '，开始步态推算');
          return seat;
        }
      } catch (e) { }
      toast('未找到该座位，锚定失败', 'error');
      return null;
    },
  };

  /* ============================================================
     2. 语音选座（语音 → 意图识别 → 直接执行）
     ============================================================ */
  var VoiceFeat = {
    /** 意图识别：从一句话里判断用户想干什么 */
    parseIntent(text) {
      var t = String(text || '');
      // 座位编号：优先「字母+数字」整体匹配（A-4 / A4 / B12），
      // 失败才退化成纯数字。旧写法 /([A-Za-z]?\d+[-\d]*)/ 对「预约A-4」
      // 只会截出 "4"，把区号字母丢掉，后面永远找不到座位。
      var seatM = /([A-Za-z]{1,3}\s*[-_－]?\s*\d{1,4})/.exec(t) || /(\d{1,4})/.exec(t);
      var seat = seatM ? seatM[1].replace(/\s+/g, '').replace(/[_－]/g, '-') : null;
      if (/导航|怎么走|带我去|路线|在哪/.test(t)) return { act: 'navigate', seat: seat, raw: t };
      if (/预约|订|占|要这个|就这个/.test(t))   return { act: 'reserve',  seat: seat, raw: t };
      if (/取消/.test(t))                      return { act: 'cancel',   seat: seat, raw: t };
      if (/空|有空|哪里有|推荐|找座|哪个好/.test(t)) return { act: 'find', seat: seat, raw: t };
      return { act: 'ask', seat: seat, raw: t };   // 兜底：交给 AI 问答
    },

    async execute(intent) {
      /* 找座：真的去挑一个空闲座位，然后直接打开导航 ——
         以前这一步只是把整句话丢给 AI 问答，答完就没了，
         所以「说一句话完成找座」名不副实。 */
      if (intent.act === 'find') {
        try {
          var r = await fetch('/api/seats', { credentials: 'same-origin' });
          var d = await r.json();
          var list = (d && d.data) || [];
          var free = list.filter(function (s) {
            return s.status === 'free' && s.is_active !== false;
          });
          if (!free.length) { toast('当前没有空闲座位', 'error'); return; }

          // 说了具体座位号就优先它
          var want = intent.seat ? String(intent.seat).toLowerCase().replace(/[\s\-_－—]/g, '') : null;
          var pick = free[0];
          if (want) {
            for (var i = 0; i < free.length; i++) {
              var lb = String(free[i].seat_label || '').toLowerCase().replace(/[\s\-_－—]/g, '');
              if (lb === want) { pick = free[i]; break; }
            }
          }

          toast('找到 ' + free.length + ' 个空座，带你去 ' + pick.seat_label + '…');
          setTimeout(function () {
            location.href = '/navigation.html?seat_label=' + encodeURIComponent(pick.seat_label);
          }, 1000);
        } catch (e) { toast('查询空座位失败', 'error'); }
        return;
      }

      // 其余开放问题：交给 AI
      if (intent.act === 'ask') {
        try {
          var r2 = await fetch('/api/ai/ask', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: intent.raw }),
          });
          var d2 = await r2.json();
          var ans = (d2 && d2.data && d2.data.answer) || (d2 && d2.message) || '暂时没有答案';
          window.FeatShowAnswer && window.FeatShowAnswer(intent.raw, ans);
          toast('AI：' + String(ans).slice(0, 40) + (String(ans).length > 40 ? '…' : ''));
        } catch (e) { toast('AI 请求失败', 'error'); }
        return;
      }

      // 预约 / 导航：需要座位号
      if (!intent.seat) { toast('请说清楚座位号，例如「预约 A-4」', 'error'); return; }

      if (intent.act === 'navigate') {
        // 用绝对路径：从 /admin/xxx.html 页面说话时相对路径会跳到 /admin/ 下
        location.href = '/navigation.html?seat_label=' + encodeURIComponent(intent.seat);
        return;
      }
      if (intent.act === 'reserve') {
        location.href = '/reservation.html?seat_label=' + encodeURIComponent(intent.seat);
        return;
      }
      if (intent.act === 'cancel') {
        toast('请到「我的预约」里取消', 'error');
      }
    },

    async listenAndRun() {
      if (!await on('voice')) { toast('语音选座已在设置中关闭', 'error'); return; }
      var ok = await window.Native.speechAvailable();
      if (!ok) { toast('语音识别不可用（需在 App 内并授权麦克风）', 'error'); return; }
      toast('请说话…（例如「预约 A-4」）');
      var text = await window.Native.listenOnce('zh-CN');
      if (!text) { toast('没听清，请再试一次', 'error'); return; }
      toast('识别到：' + text);
      var intent = this.parseIntent(text);
      console.log('[语音意图]', intent);
      await this.execute(intent);
    },

    mountButton(container) {
      if (!container || document.getElementById('feat-voice-btn')) return;
      var b = el('button', 'padding:6px 12px;border:none;border-radius:16px;'
        + 'background:#7c5cff;color:#fff;font-size:13px;cursor:pointer;margin:6px;', '🎤 语音选座');
      b.id = 'feat-voice-btn';
      b.onclick = function () { VoiceFeat.listenAndRun(); };
      container.appendChild(b);
    },
  };

  /* ============================================================
     3. 实时提醒（本地通知）
     ============================================================ */
  var NotifyFeat = {
    async notify(title, body) {
      if (!await on('notify')) return false;
      return await window.Native.notify(title, body);
    },

    /** 预约到期前提醒（默认提前 5 分钟） */
    async scheduleReservationReminders() {
      if (!await on('notify')) return;
      try {
        var res = await apiGet('/api/reservations');
        var list = (res && res.data) || [];
        if (!Array.isArray(list)) return;
        var now = Date.now(), n = 0;
        list.forEach(function (r) {
          if (r.status !== 'pending' || !r.end_time) return;
          var end = new Date(r.end_time).getTime();
          var remindAt = end - 5 * 60000;
          if (remindAt > now && remindAt < now + 3600000) {
            window.Native.notify('预约即将结束',
              (r.seat_label || '座位') + ' 的预约还有 5 分钟到期', undefined);
            n++;
          }
        });
        if (n) console.log('[Feat] 已安排', n, '条到期提醒');
      } catch (e) { }
    },

    /** 检测到有人占座/释放时的提醒（配合座位轮询） */
    async checkSeatChange() {
      if (!await on('notify')) return;
      try {
        var res = await apiGet('/api/seats');
        var list = (res && res.data) || [];
        if (list.seats) list = list.seats;
        var free = list.filter(function (s) { return s.status === 'free'; });
        var last = parseInt(localStorage.getItem('feat_free_count') || '-1', 10);
        if (last >= 0 && free.length > last) {
          window.Native.notify('有座位释放了',
            '当前空闲 ' + free.length + ' 个座位，例如 ' + (free[0] && free[0].seat_label));
        }
        localStorage.setItem('feat_free_count', String(free.length));
      } catch (e) { }
    },
  };

  /* ============================================================
     4. 地理围栏（基于建筑经纬度）
     ============================================================ */
  var GeofenceFeat = {
    timer: null,
    lastInside: null,
    buildings: [],

    async loadBuildings() {
      try {
        var res = await apiGet('/api/nav/destinations');
        var d = (res && res.data) || {};
        this.buildings = (d.destinations || []).filter(function (b) { return b.lat && b.lng; });
        console.log('[Feat] 地理围栏目标建筑:', this.buildings.length, '个');
      } catch (e) { this.buildings = []; }
    },

    distance(lat1, lng1, lat2, lng2) {
      var R = 6371000, rad = function (x) { return x * Math.PI / 180; };
      var dLat = rad(lat2 - lat1), dLng = rad(lng2 - lng1);
      var a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
            + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
      return 2 * R * Math.asin(Math.sqrt(a));
    },

    async tick() {
      if (!await on('geofence')) return;
      if (!this.buildings.length) return;
      var pos = await window.Native.getPosition();
      if (!pos) return;

      var nearest = null, minD = 1e9;
      this.buildings.forEach(function (b) {
        var d = GeofenceFeat.distance(pos.lat, pos.lng, b.lat, b.lng);
        if (d < minD) { minD = d; nearest = b; }
      });
      if (!nearest) return;

      var INSIDE_R = 120;    // 进入半径（米）
      var inside = minD < INSIDE_R;
      var prev = this.lastInside;

      if (inside && prev !== nearest.id) {
        this.lastInside = nearest.id;
        console.log('[Feat] 进入围栏:', nearest.name, Math.round(minD), 'm');
        try {
          var res = await apiGet('/api/seats');
          var list = (res && res.data) || [];
          if (list.seats) list = list.seats;
          var free = list.filter(function (s) { return s.status === 'free'; }).length;
          NotifyFeat.notify('你已到达 ' + nearest.name,
            free ? ('当前有 ' + free + ' 个空位，点击查看') : '当前没有空位');
        } catch (e) {
          NotifyFeat.notify('你已到达 ' + nearest.name, '点击查看座位');
        }
      } else if (!inside && typeof prev === 'number' && this.lastInside === prev) {
        this.lastInside = null;
        console.log('[Feat] 离开围栏:', nearest.name);
        NotifyFeat.notify('你已离开 ' + nearest.name, '如不需要请及时释放座位');
      }
    },

    start() {
      this.stop();
      this.loadBuildings().then(function () {
        GeofenceFeat.tick();
        GeofenceFeat.timer = setInterval(function () { GeofenceFeat.tick(); }, 60000);
      });
    },
    stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } },
  };

  /* ============================================================
     5. 传感器导航 PDR（步态推算 + 扫码锚定）
     ------------------------------------------------------------
     诚实说明：纯惯性推算会累积漂移。这里采用「扫码锚定 + 短距推算」，
     每扫一次码就把位置拉回已知点，把误差控制在可演示范围内。
     ============================================================ */
  var Pdr = {
    running: false,
    steps: 0,
    distM: 0,
    lastMag: 0,
    lastStepAt: 0,
    heading: 0,
    anchorX: null, anchorY: null, anchorLabel: null,
    STEP_LEN: 0.65,          // 平均步长（米）
    STEP_MIN_MS: 280,        // 最小步间隔，防抖

    onMotion(e) {
      var a = e.accelerationIncludingGravity || e.acceleration;
      if (!a) return;
      var mag = Math.sqrt((a.x || 0) * (a.x || 0) + (a.y || 0) * (a.y || 0) + (a.z || 0) * (a.z || 0));
      var now = Date.now();
      // 简易峰值检测：超过阈值且距上一步足够久 => 记一步
      if (mag > 13.5 && this.lastMag <= 13.5 && (now - this.lastStepAt) > this.STEP_MIN_MS) {
        this.steps++;
        this.distM += this.STEP_LEN;
        this.lastStepAt = now;
        this.render();
      }
      this.lastMag = mag;
    },

    onOrient(e) {
      if (typeof e.webkitCompassHeading === 'number') this.heading = e.webkitCompassHeading;
      else if (typeof e.alpha === 'number') this.heading = (360 - e.alpha) % 360;
    },

    anchor(x, y, label) {
      this.anchorX = x; this.anchorY = y; this.anchorLabel = label || null;
      this.steps = 0; this.distM = 0;
      this.render();
    },

    render() {
      var box = document.getElementById('pdr-box');
      if (!box) return;
      $('#pdr-steps', box).textContent = this.steps + ' 步';
      $('#pdr-dist', box).textContent = this.distM.toFixed(1) + ' m';
      $('#pdr-head', box).textContent = Math.round(this.heading) + '°';
      $('#pdr-anchor', box).textContent = this.anchorLabel ? ('锚点 ' + this.anchorLabel) : '未锚定';
      var arrow = $('#pdr-arrow', box);
      if (arrow) arrow.style.transform = 'rotate(' + Math.round(this.heading) + 'deg)';
      // 收起时在标题栏右侧显示摘要，不展开也能看到关键数据
      var sum = $('#pdr-sum', box);
      if (sum) {
        sum.textContent = this.collapsed
          ? (this.steps + ' 步 · ' + Math.round(this.heading) + '°')
          : '';
      }
    },

    /* ---------------- 收起 / 展开 ----------------
       面板长期悬浮会挡住导航主界面，所以默认收起成一个小胶囊，
       点标题栏可展开；状态记在本机，下次进页面沿用。 */
    collapsed: true,
    COLLAPSE_KEY: 'pdr_collapsed',

    applyCollapsed() {
      var body = document.getElementById('pdr-body');
      var caret = document.getElementById('pdr-caret');
      var box = document.getElementById('pdr-box');
      if (body) body.style.display = this.collapsed ? 'none' : 'block';
      if (caret) caret.className = 'fas ' + (this.collapsed ? 'fa-chevron-down' : 'fa-chevron-up');
      if (box) box.style.opacity = this.collapsed ? '0.94' : '1';
    },

    setCollapsed(v) {
      this.collapsed = !!v;
      this.applyCollapsed();
      this.render();
      try { window.Native.cacheSet(this.COLLAPSE_KEY, this.collapsed); } catch (e) { }
    },

    async loadCollapsed() {
      try {
        var v = await window.Native.cacheGet(this.COLLAPSE_KEY);
        if (v === true || v === false) { this.collapsed = v; this.applyCollapsed(); this.render(); }
      } catch (e) { }
    },

    mountBox() {
      var old = document.getElementById('pdr-box');
      if (old) old.remove();
      var box = el('div', 'position:fixed;right:14px;bottom:150px;z-index:9997;'
        + 'background:rgba(255,255,255,.97);border-radius:12px;'
        + 'box-shadow:0 4px 18px rgba(0,0,0,.18);font-size:13px;color:#1f2937;'
        + 'max-width:calc(100vw - 28px);overflow:hidden;');
      box.id = 'pdr-box';
      box.innerHTML =
        // 标题栏：始终可见，点它展开 / 收起
        '<button id="pdr-toggle" type="button" style="display:flex;align-items:center;gap:6px;'
        + 'width:100%;border:none;background:none;padding:9px 12px;cursor:pointer;'
        + 'font:inherit;color:#1a73e8;font-weight:700;text-align:left;">'
        + '<i class="fas fa-shoe-prints"></i><span>传感器导航</span>'
        + '<span id="pdr-sum" style="font-weight:400;color:#8a94a6;font-size:11.5px;"></span>'
        + '<i id="pdr-caret" class="fas fa-chevron-down" '
        + 'style="margin-left:auto;color:#8a94a6;font-size:11px;"></i></button>'
        // 面板主体：默认收起
        + '<div id="pdr-body" style="padding:0 14px 12px;min-width:158px;">'
        + '<div style="display:flex;justify-content:space-between;"><span>步数</span>'
        + '<b id="pdr-steps">0 步</b></div>'
        + '<div style="display:flex;justify-content:space-between;margin-top:4px;"><span>推算距离</span>'
        + '<b id="pdr-dist">0.0 m</b></div>'
        + '<div style="display:flex;justify-content:space-between;margin-top:4px;"><span>朝向</span>'
        + '<b id="pdr-head">0°</b></div>'
        + '<div style="margin-top:8px;font-size:11.5px;color:#8a94a6;">'
        + '锚点：<span id="pdr-anchor">未锚定</span></div>'
        + '<button id="pdr-anchor-btn" style="margin-top:10px;width:100%;padding:7px;border:none;'
        + 'border-radius:8px;background:#1a73e8;color:#fff;font-size:12.5px;cursor:pointer;">'
        + '📷 扫桌上的码锚定</button>'
        + '<div style="margin-top:6px;font-size:11px;color:#b0b8c4;line-height:1.5;">'
        + '惯性推算会有累积误差，每走一段扫一次码校准</div>'
        + '</div>';
      document.body.appendChild(box);

      var self = this;
      $('#pdr-anchor-btn', box).onclick = function () { ScanFeat.scanAnchor(); };
      $('#pdr-toggle', box).onclick = function () { self.setCollapsed(!self.collapsed); };
      this.applyCollapsed();
      this.render();
      this.loadCollapsed();
    },

    async start() {
      if (this.running) return;
      if (!await on('pdr')) return;
      if (!window.DeviceMotionEvent) { console.log('[Feat] 设备不支持 devicemotion'); return; }
      window.addEventListener('devicemotion', this._h = this.onMotion.bind(this));
      window.addEventListener('deviceorientation', this._o = this.onOrient.bind(this));
      this.running = true;
      this.mountBox();
      console.log('[Feat] 传感器导航已启动');
    },

    stop() {
      if (!this.running) return;
      if (this._h) window.removeEventListener('devicemotion', this._h);
      if (this._o) window.removeEventListener('deviceorientation', this._o);
      this.running = false;
      var b = document.getElementById('pdr-box');
      if (b) b.remove();
      console.log('[Feat] 传感器导航已停止');
    },
  };

  /* ============================================================
     6. 离线缓存
     ============================================================ */
  var OfflineFeat = {
    KEY: 'seat_cache_v1',

    hook() {
      var ax = window.axios;
      if (!ax || ax.__featHooked) return;
      var origGet = ax.get;
      ax.get = async function (url, cfg) {
        var res = await origGet.call(this, url, cfg);
        try {
          if (typeof url === 'string' && /\/api\/(seats|buildings|floors|nav)/.test(url)
              && await on('offline')) {
            var store = (await window.Native.cacheGet(OfflineFeat.KEY)) || {};
            store[url] = { at: Date.now(), data: res && res.data };
            var keys = Object.keys(store);
            if (keys.length > 40) delete store[keys[0]];    // 简单限容
            await window.Native.cacheSet(OfflineFeat.KEY, store);
          }
        } catch (e) { }
        return res;
      };
      ax.__featHooked = true;
      console.log('[Feat] 离线缓存已挂钩');
    },

    async showIfOffline() {
      if (navigator.onLine) return;
      if (!await on('offline')) return;
      var store = await window.Native.cacheGet(this.KEY);
      if (!store) return;
      var keys = Object.keys(store);
      if (!keys.length) return;
      toast('当前无网络，已加载上次缓存数据', 'error');
      window.__OFFLINE_CACHE__ = store;
    },

    watch() {
      window.addEventListener('online', function () { toast('网络已恢复，正在同步…'); });
      window.addEventListener('offline', function () { toast('网络已断开', 'error'); });
    },
  };

  /* ============================================================
     7. 桌面快捷方式（编译期配置，这里只做提示与验证）
     ============================================================ */
  var ShortcutFeat = {
    async hint() {
      if (!isApp) return;
      if (!await on('shortcut')) return;
      console.log('[Feat] 桌面快捷方式：长按 App 图标可用「找空座 / 扫码占座 / 我的预约」');
    },
  };

  /* ============================================================
     挂载：按页面注入入口
     ============================================================ */
  ready(async function () {
    console.log('[Feat] 启动 isApp=', isApp, 'path=', location.pathname);

    OfflineFeat.watch();
    OfflineFeat.hook();
    OfflineFeat.showIfOffline();

    /* 齿轮按钮：App 内显示；浏览器里也显示，
       便于直接验证 / 投影演示（各功能项会按平台自动降级） */
    if (window.NativeSettings) {
      window.NativeSettings.mountButton();
    }

    var p = location.pathname;

    /* 预约页：扫码签到 */
    if (/reservation/.test(p) && isApp) {
      var input = document.getElementById('checkin-token');
      if (input && !document.getElementById('feat-scan-btn')) {
        var b = el('button', 'background:#e8f0fe;color:#1a73e8;margin-left:6px;', '<i class="fas fa-camera"></i> 扫码');
        b.id = 'feat-scan-btn';
        b.className = 'btn btn-sm';
        b.onclick = function () { ScanFeat.scanForCheckin(); };
        input.parentNode.insertBefore(b, input.nextSibling);
      }
    }

    /* 座位图：扫码占座浮动按钮 */
    if (/seat_map|seat-map/.test(p) && isApp) {
      if (await on('scan') && !document.getElementById('feat-scan-fab')) {
        var fab = el('button', 'position:fixed;right:18px;bottom:86px;z-index:9998;'
          + 'padding:12px 18px;border:none;border-radius:26px;background:#1a73e8;color:#fff;'
          + 'font-size:15px;box-shadow:0 4px 14px rgba(26,115,232,.4);cursor:pointer;',
          '<i class="fas fa-qrcode"></i><span style="margin-left:8px">扫码占座</span>');
        fab.id = 'feat-scan-fab';
        fab.onclick = function () { ScanFeat.scanForSeat(); };
        document.body.appendChild(fab);
      }
    }

    /* 导航页：启动 PDR */
    if (/navigation/.test(p) && isApp) Pdr.start();

    /* AI 助手：挂语音按钮 */
    if (isApp) {
      var tries = 0;
      var t = setInterval(async function () {
        tries++;
        var box = document.querySelector('#ai-assistant, .ai-assistant, [class*="ai-assist"]');
        if (box && await on('voice')) { VoiceFeat.mountButton(box); clearInterval(t); }
        if (tries > 40) clearInterval(t);
      }, 500);
    }

    /* 实时提醒：定期检查 */
    if (isApp) {
      setTimeout(function () { NotifyFeat.scheduleReservationReminders(); }, 3000);
      setInterval(function () { NotifyFeat.checkSeatChange(); }, 120000);
      ShortcutFeat.hint();
    }

    /* App 模式标识 */
    if (isApp && !document.getElementById('feat-badge')) {
      var bd = el('div', 'position:fixed;left:12px;bottom:12px;z-index:9996;padding:4px 10px;'
        + 'border-radius:12px;font-size:12px;background:rgba(15,157,88,.92);color:#fff;',
        '<i class="fas fa-mobile-alt"></i> App 模式');
      bd.id = 'feat-badge';
      document.body.appendChild(bd);
    }

    /* 地理围栏 */
    if (isApp) GeofenceFeat.start();

    /* 开关实时生效 */
    onChange('pdr', function (v) { v ? Pdr.start() : Pdr.stop(); });
    onChange('geofence', function (v) { v ? GeofenceFeat.start() : GeofenceFeat.stop(); });

    /* 桌面快捷方式动作（URL 参数版，主路径） */
    if (isApp) {
      var autoAct = shortcutFromUrl();
      if (autoAct) {
        clearShortcutParam();
        console.log('[Feat] 快捷方式动作（URL）:', autoAct);
        if (autoAct === 'scan' && await on('scan')) {
          setTimeout(function () { ScanFeat.scanForCheckin(); }, 700);
        }
        if (autoAct === 'voice' && await on('voice')) {
          setTimeout(function () { VoiceFeat.listenAndRun(); }, 700);
        }
      }
    }

    /* 桌面快捷方式带过来的一次性动作（旧版注入方式，保留兼容） */
    if (isApp) {
      var tries2 = 0;
      var t2 = setInterval(async function () {
        tries2++;
        var act = window.__SHORTCUT__;
        if (act) {
          window.__SHORTCUT__ = null;
          clearInterval(t2);
          console.log('[Feat] 快捷方式动作:', act);
          if (act === 'scan' && await on('scan')) {
            setTimeout(function () { ScanFeat.scanForCheckin(); }, 600);
          }
          if (act === 'voice' && await on('voice')) {
            setTimeout(function () { VoiceFeat.listenAndRun(); }, 600);
          }
        }
        if (tries2 > 30) clearInterval(t2);
      }, 500);
    }
  });

  /* 暴露给页面 */
  window.Feat = {
    scan: ScanFeat, voice: VoiceFeat, notify: NotifyFeat,
    geofence: GeofenceFeat, pdr: Pdr, offline: OfflineFeat,
  };
})();

/* ============================================================
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

/* ================= mobile-app.css (内联) ================= */
window.__APP_SHELL_CSS__ = "/* ============================================================\n   智座 · 移动端 App 外壳样式\n   ------------------------------------------------------------\n   ★ 只有在 App 内（Capacitor WebView）才生效 ★\n   app-shell.js 会先确认 window.Native.available 为真，\n   再给 <body> 打上 .app-mode 类；网页版不会命中这里任何一条规则，\n   桌面端界面一个像素都不变。\n\n   解决的原问题：手机上顶部 .nav 里「品牌 + 6 个链接 + 头像 + 角色徽章\n   + 退出」全挤在 60px 里，窄屏下品牌被压成 4 行、徽章压成 3 行，\n   导航链接一个都看不见。\n   ============================================================ */\n\nbody.app-mode {\n  --app-top-h: 54px;\n  /* 顶栏整体再往下让一点，别贴着状态栏/刘海 */\n  --app-top-extra: 8px;\n  /* 顶部安全区：优先用原生注入的真实状态栏高度（Android WebView 里\n     env(safe-area-inset-top) 不可靠），没有就用 env() 兜底 */\n  --app-safe-t: max(var(--app-status-h, 0px), env(safe-area-inset-top, 0px));\n  --app-tab-h: 58px;\n  --app-safe-b: env(safe-area-inset-bottom, 0px);\n\n  padding-top: calc(var(--app-top-h) + var(--app-top-extra) + var(--app-safe-t));\n  padding-bottom: calc(var(--app-tab-h) + var(--app-safe-b));\n  -webkit-tap-highlight-color: transparent;\n  overscroll-behavior-y: none;\n}\n\n/* 原顶部导航整体让位给 .app-topbar（不改原样式，只是不显示） */\nbody.app-mode .nav {\n  display: none !important;\n}\n\n/* 内容区补足底部 Tab 的高度，避免最后一行被盖住 */\nbody.app-mode .container {\n  padding-bottom: calc(16px + var(--app-tab-h) + var(--app-safe-b));\n}\n\n/* 浮动按钮上移，别被底部 Tab 压住 */\nbody.app-mode #ns-btn {\n  bottom: calc(var(--app-tab-h) + 16px + var(--app-safe-b)) !important;\n  z-index: 880 !important;\n}\nbody.app-mode #feat-scan-fab {\n  bottom: calc(var(--app-tab-h) + 58px + var(--app-safe-b)) !important;\n}\nbody.app-mode #feat-badge {\n  bottom: calc(var(--app-tab-h) + 16px + var(--app-safe-b)) !important;\n}\n/* AI 助手气泡：ai-assistant.js 内联样式是 fixed/right:22px/bottom:22px/z-index:9000，\n   不改它，只在 App 内抬高并压到 Tab 栏下面 */\nbody.app-mode .aias-root {\n  bottom: calc(var(--app-tab-h) + 22px + var(--app-safe-b)) !important;\n  z-index: 890 !important;\n}\n/* 传感器导航面板：默认收起成小胶囊，抬高到 Tab 栏之上 */\nbody.app-mode #pdr-box {\n  bottom: calc(var(--app-tab-h) + 92px + var(--app-safe-b)) !important;\n  max-width: calc(100vw - 28px);\n}\nbody.app-mode #pdr-body {\n  transition: opacity .18s ease;\n}\nbody.app-mode #pdr-toggle:active {\n  background: rgba(26, 115, 232, .08);\n}\n\n/* ---------- 顶部细条 ---------- */\n.app-topbar {\n  display: none;\n}\n\nbody.app-mode .app-topbar {\n  display: flex;\n  align-items: center;\n  gap: 8px;\n  position: fixed;\n  top: 0;\n  left: 0;\n  right: 0;\n  height: calc(var(--app-top-h) + var(--app-top-extra) + var(--app-safe-t));\n  padding: calc(var(--app-safe-t) + var(--app-top-extra)) 10px 0;\n  background: linear-gradient(135deg, var(--accent), var(--accent-dark));\n  color: #fff;\n  z-index: 900;\n  box-shadow: 0 1px 10px rgba(0, 0, 0, .18);\n}\n\n.app-topbar-btn {\n  flex: 0 0 38px;\n  height: 38px;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  background: rgba(255, 255, 255, .14);\n  border: none;\n  border-radius: 10px;\n  color: #fff;\n  font-size: 16px;\n  cursor: pointer;\n}\n\n.app-topbar-btn:active {\n  background: rgba(255, 255, 255, .3);\n}\n\n.app-topbar-title {\n  flex: 1 1 auto;\n  min-width: 0;\n  font-size: 16px;\n  font-weight: 600;\n  white-space: nowrap;\n  overflow: hidden;\n  text-overflow: ellipsis;\n}\n\n.app-topbar-avatar {\n  flex: 0 0 34px;\n  height: 34px;\n  border-radius: 50%;\n  background: rgba(255, 255, 255, .2);\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  color: #fff;\n  font-size: 15px;\n  text-decoration: none;\n  overflow: hidden;\n}\n\n.app-topbar-avatar img {\n  width: 100%;\n  height: 100%;\n  object-fit: cover;\n}\n\n/* ---------- 底部 Tab ---------- */\n.app-tabbar {\n  display: none;\n}\n\nbody.app-mode .app-tabbar {\n  display: flex;\n  position: fixed;\n  left: 0;\n  right: 0;\n  bottom: 0;\n  height: calc(var(--app-tab-h) + var(--app-safe-b));\n  padding-bottom: var(--app-safe-b);\n  background: #fff;\n  border-top: 1px solid var(--border-light);\n  z-index: 900;\n  box-shadow: 0 -1px 10px rgba(0, 0, 0, .06);\n}\n\n.app-tab {\n  flex: 1 1 0;\n  min-width: 0;\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  justify-content: center;\n  gap: 2px;\n  color: var(--text-dim);\n  text-decoration: none;\n  font-size: 11px;\n  position: relative;\n}\n\n.app-tab i {\n  font-size: 18px;\n}\n\n.app-tab:active {\n  background: #f6f8fb;\n}\n\n.app-tab.active {\n  color: var(--accent);\n  font-weight: 600;\n}\n\n.app-tab.active::before {\n  content: '';\n  position: absolute;\n  top: 0;\n  left: 50%;\n  transform: translateX(-50%);\n  width: 26px;\n  height: 3px;\n  border-radius: 0 0 3px 3px;\n  background: var(--accent);\n}\n\n/* ---------- 侧边抽屉 ---------- */\n.app-drawer-mask,\n.app-drawer {\n  display: none;\n}\n\nbody.app-mode .app-drawer-mask.open {\n  display: block;\n  position: fixed;\n  inset: 0;\n  background: rgba(0, 0, 0, .42);\n  z-index: 1000;\n}\n\nbody.app-mode .app-drawer.open {\n  display: flex;\n  flex-direction: column;\n  position: fixed;\n  top: 0;\n  bottom: 0;\n  left: 0;\n  width: 268px;\n  max-width: 82vw;\n  background: #fff;\n  z-index: 1001;\n  box-shadow: 4px 0 24px rgba(0, 0, 0, .2);\n  animation: appDrawerIn .22s ease-out;\n}\n\n@keyframes appDrawerIn {\n  from { transform: translateX(-100%); }\n  to { transform: translateX(0); }\n}\n\n.app-drawer-head {\n  padding: calc(18px + var(--app-safe-t)) 16px 14px;\n  background: linear-gradient(135deg, var(--accent), var(--accent-dark));\n  color: #fff;\n}\n\n.app-drawer-brand {\n  display: flex;\n  align-items: center;\n  gap: 9px;\n  font-size: 19px;\n  font-weight: 700;\n}\n\n.app-drawer-sub {\n  font-size: 11.5px;\n  opacity: .85;\n  margin-top: 4px;\n}\n\n.app-drawer-user {\n  margin-top: 12px;\n  display: flex;\n  align-items: center;\n  gap: 8px;\n  font-size: 13px;\n}\n\n.app-drawer-role {\n  padding: 2px 9px;\n  border-radius: 10px;\n  background: rgba(255, 255, 255, .22);\n  font-size: 11px;\n}\n\n.app-drawer-nav {\n  flex: 1 1 auto;\n  overflow-y: auto;\n  padding: 8px;\n}\n\n.app-drawer-nav a {\n  display: flex;\n  align-items: center;\n  gap: 12px;\n  padding: 13px 12px;\n  border-radius: 10px;\n  color: var(--text);\n  text-decoration: none;\n  font-size: 15px;\n}\n\n.app-drawer-nav a i {\n  width: 20px;\n  text-align: center;\n  color: var(--text-dim);\n  font-size: 16px;\n}\n\n.app-drawer-nav a:active {\n  background: var(--accent-subtle);\n}\n\n.app-drawer-nav a.active {\n  background: var(--accent-subtle);\n  color: var(--accent);\n  font-weight: 600;\n}\n\n.app-drawer-nav a.active i {\n  color: var(--accent);\n}\n\n.app-drawer-foot {\n  padding: 10px 12px calc(14px + var(--app-safe-b));\n  border-top: 1px solid var(--border-light);\n}\n\n.app-drawer-logout {\n  width: 100%;\n  padding: 12px;\n  border: none;\n  border-radius: 10px;\n  background: #fdecea;\n  color: var(--danger);\n  font-size: 15px;\n  font-weight: 600;\n  cursor: pointer;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  gap: 8px;\n  font-family: inherit;\n}\n\n.app-drawer-logout:active {\n  background: #fbd9d6;\n}\n\n/* 未登录时底部按钮变成「去登录」（蓝色而不是红色） */\nbody.app-mode .app-drawer-login {\n  background: var(--accent-subtle);\n  color: var(--accent);\n}\n\nbody.app-mode .app-drawer-login:active {\n  background: #d7e6fb;\n}\n\n/* ---------- 悬浮按钮长按拖动（drag-fab.js）---------- */\nbody.app-mode .fab-dragging {\n  opacity: .88 !important;\n  box-shadow: 0 10px 30px rgba(0, 0, 0, .38) !important;\n  cursor: grabbing !important;\n  z-index: 9500 !important;\n}\n\n/* 拖动中的按钮不要被选中/弹出系统菜单 */\nbody.app-mode .aias-root,\nbody.app-mode #feat-scan-fab {\n  -webkit-user-select: none;\n  user-select: none;\n  -webkit-touch-callout: none;\n}\n";

/* ================= native-bridge.js ================= */
/* ============================================================
   原生能力桥 native-bridge.js
   ------------------------------------------------------------
   作用：把 Capacitor 的原生插件能力，包装成网页可以直接调用的
        window.Native 对象。网页里一行代码就能用：

            // 扫码
            const text = await Native.scanQrCode();

            // 语音识别（说一句话转文字）
            const text = await Native.listenOnce();

            // 本地通知
            await Native.notify('座位已释放', 'A-4 现在空出来了');

            // 地理定位（原生，不受 http 安全上下文限制）
            const pos = await Native.getPosition();

            // 离线缓存
            await Native.cacheSet('seats', data);
            const data = await Native.cacheGet('seats');

   设计原则：
     · 在**浏览器**里打开时，Native.available === false，
       所有方法都会安全降级（返回 null 或走浏览器原生 API），
       所以同一套页面在网页和 App 里都能跑，不会报错。
     · 不依赖任何打包工具 —— 直接 <script src="..."></script> 引入即可。
   ============================================================ */
(function () {
  'use strict';

  var Cap = window.Capacitor;
  var isNative = !!(Cap && typeof Cap.isNativePlatform === 'function' && Cap.isNativePlatform());

  /* 本地预览开关（真实 App 内不受影响）
     ------------------------------------------------------------
     在电脑浏览器里加 ?appmode=1 就能强制打开「App 模式」，
     用于预览 / 答辩演示移动端界面，不需要装 APK；?appmode=0 关掉。
     选择会记在 localStorage，后续页面自动沿用。 */
  try {
    var _m = /[?&]appmode=([01])/.exec(location.search);
    if (_m) {
      isNative = _m[1] === '1';
      try { localStorage.setItem('__appmode__', _m[1]); } catch (e) { }
    } else {
      var _v = localStorage.getItem('__appmode__');
      if (_v === '0' || _v === '1') isNative = (_v === '1');
    }
  } catch (e) { }

  /** 取插件（Capacitor 7 用 Capacitor.Plugins，旧版用 registerPlugin） */
  function plugin(name) {
    if (!Cap) return null;
    if (Cap.Plugins && Cap.Plugins[name]) return Cap.Plugins[name];
    try {
      if (typeof Cap.registerPlugin === 'function') return Cap.registerPlugin(name);
    } catch (e) { }
    return null;
  }

  var Native = {
    available: isNative,
    platform: (Cap && Cap.getPlatform && Cap.getPlatform()) || 'web',

    /* ---------------- 扫码（原生相机） ---------------- */
    /**
     * 调原生相机扫码，返回扫到的文本；取消或失败返回 null。
     * 网页环境降级：返回 null（调用方可以自己提示"请在 App 内使用"）
     */
    scanQrCode: async function () {
      if (!isNative) return null;
      var P = plugin('BarcodeScanner');
      if (!P) return null;
      try {
        var perm = await P.requestPermissions();
        if (perm && perm.camera !== 'granted' && perm.camera !== 'limited') return null;
        var res = await P.scan();
        var codes = (res && res.barcodes) || [];
        return codes.length ? (codes[0].rawValue || codes[0].displayValue || null) : null;
      } catch (e) {
        console.warn('[Native] 扫码失败', e);
        return null;
      }
    },

    /* ---------------- 语音识别（原生麦克风） ---------------- */
    /** 检查语音识别是否可用 */
    speechAvailable: async function () {
      if (!isNative) return false;
      var P = plugin('SpeechRecognition');
      if (!P || !P.available) return false;
      try { var r = await P.available(); return !!(r && r.available); } catch (e) { return false; }
    },

    /**
     * 听一句话并返回识别文本；失败返回 null。
     * @param {string} lang 语言，默认 zh-CN
     */
    listenOnce: async function (lang) {
      if (!isNative) return null;
      var P = plugin('SpeechRecognition');
      if (!P) return null;
      try {
        var perm = await P.requestPermissions();
        if (perm && perm.speechRecognition !== 'granted') return null;
        var res = await P.start({
          language: lang || 'zh-CN',
          maxResults: 1,
          partialResults: false,
          popup: false,
        });
        var m = (res && res.matches) || [];
        return m.length ? m[0] : null;
      } catch (e) {
        console.warn('[Native] 语音识别失败', e);
        return null;
      }
    },

    /* ---------------- 本地通知 ---------------- */
    /** 申请通知权限 */
    requestNotifyPermission: async function () {
      if (!isNative) return false;
      var P = plugin('LocalNotifications');
      if (!P) return false;
      try { var r = await P.requestPermissions(); return !!(r && r.display === 'granted'); }
      catch (e) { return false; }
    },

    /**
     * 立即弹一条本地通知
     * @param {string} title
     * @param {string} body
     */
    notify: async function (title, body, id) {
      if (!isNative) {
        // 网页降级：用浏览器通知（需 https + 用户授权）
        try {
          if (window.Notification && Notification.permission === 'granted') {
            new Notification(title, { body: body });
            return true;
          }
        } catch (e) { }
        return false;
      }
      var P = plugin('LocalNotifications');
      if (!P) return false;
      try {
        /* ★ 先确认通知权限。

           Android 13（API 33）起 POST_NOTIFICATIONS 是**运行时权限**：
           Manifest 里声明了不等于拿到了，运行时没申请的话，
           系统会**静默丢弃**所有通知 —— 而 schedule() 依然返回成功。
           表现为「代码以为发出去了，用户什么都看不到」，
           而且不报任何错，极难排查。

           以前这里直接 schedule，从来没有申请过权限，
           所以地理围栏、预约提醒这些通知在 Android 13+ 上其实一条都没弹出来。 */
        var perm = null;
        try {
          if (P.checkPermissions) perm = await P.checkPermissions();
        } catch (e) { /* 老版本插件没有 checkPermissions，直接走申请 */ }
        if (!perm || perm.display !== 'granted') {
          try { perm = await P.requestPermissions(); } catch (e) { perm = null; }
        }
        if (!perm || perm.display !== 'granted') {
          console.warn('[Native] 通知权限未授予，通知不会显示（' +
            ((perm && perm.display) || 'unknown') + '）');
          return false;
        }

        await P.schedule({
          notifications: [{
            id: id || Math.floor(Math.random() * 100000),
            title: title || '智能选座',
            body: body || '',
            schedule: { at: new Date(Date.now() + 300) },
          }],
        });
        return true;
      } catch (e) { console.warn('[Native] 通知失败', e); return false; }
    },

    /* ---------------- 原生定位 ---------------- */
    /**
     * 取当前位置。原生环境走 Capacitor 插件（不受 http 安全上下文限制）；
     * 网页环境退回浏览器 navigator.geolocation。
     * @returns {Promise<{lat:number,lng:number,accuracy:number}|null>}
     */
    getPosition: async function () {
      if (isNative) {
        var P = plugin('Geolocation');
        if (P) {
          try {
            var perm = await P.requestPermissions();
            if (perm && perm.location !== 'granted') return null;
            var pos = await P.getCurrentPosition({ enableHighAccuracy: true, timeout: 15000 });
            return { lat: pos.coords.latitude, lng: pos.coords.longitude,
                     accuracy: pos.coords.accuracy };
          } catch (e) { console.warn('[Native] 定位失败', e); return null; }
        }
      }
      // 网页降级
      return new Promise(function (resolve) {
        if (!navigator.geolocation) { resolve(null); return; }
        navigator.geolocation.getCurrentPosition(
          function (p) { resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }); },
          function () { resolve(null); },
          { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
      });
    },

    /* ---------------- 离线缓存 ---------------- */
    cacheSet: async function (key, value) {
      var s = JSON.stringify(value);
      if (isNative) {
        var P = plugin('Preferences');
        if (P) { try { await P.set({ key: key, value: s }); return true; } catch (e) { } }
      }
      try { localStorage.setItem('native_cache_' + key, s); return true; } catch (e) { return false; }
    },

    cacheGet: async function (key) {
      if (isNative) {
        var P = plugin('Preferences');
        if (P) {
          try {
            var r = await P.get({ key: key });
            if (r && r.value) return JSON.parse(r.value);
          } catch (e) { }
        }
      }
      try {
        var v = localStorage.getItem('native_cache_' + key);
        return v ? JSON.parse(v) : null;
      } catch (e) { return null; }
    },

    /* ---------------- 震动反馈 ---------------- */
    vibrate: function (ms) {
      if (isNative && Cap && Cap.Plugins && Cap.Plugins.Haptics) {
        try { Cap.Plugins.Haptics.vibrate({ duration: ms || 50 }); return; } catch (e) { }
      }
      if (navigator.vibrate) { try { navigator.vibrate(ms || 50); } catch (e) { } }
    },
  };

  window.Native = Native;
  console.log('[Native] 桥接就绪, 平台 =', Native.platform, ', 原生能力 =', Native.available);
})();

/* ================= native-settings.js ================= */
/* ============================================================
   移动端功能开关 · 设置存储 + 设置面板
   ------------------------------------------------------------
   所有原生功能都可以在这里手动开关，**默认全部开启**。
   开关持久化在原生 Preferences（App）或 localStorage（网页）。

   对外接口：
       window.NativeSettings.get('voice')        -> Promise<bool>
       window.NativeSettings.all()               -> Promise<{...}>
       window.NativeSettings.set('voice', false) -> Promise<void>
       window.NativeSettings.openPanel()         -> 打开设置面板
   ============================================================ */
(function () {
  'use strict';

  var STORE_KEY = 'native_feature_settings_v1';

  /* 功能开关定义（顺序即面板显示顺序） */
  var FEATURES = [
    { key: 'scan',     name: '扫码占座',   icon: 'fa-qrcode',
      desc: '调用原生相机扫座位二维码，直接选座/签到' },
    { key: 'voice',    name: '语音选座',   icon: 'fa-microphone',
      desc: '用手机麦克风说一句话完成找座、预约、导航' },
    { key: 'notify',   name: '实时提醒',   icon: 'fa-bell',
      desc: '座位释放 / 预约到期 主动推送通知' },
    { key: 'geofence', name: '地理围栏',   icon: 'fa-location-dot',
      desc: '走近场馆自动推荐空位，离开时提示释放' },
    { key: 'pdr',      name: '传感器导航', icon: 'fa-shoe-prints',
      desc: '加速度计步态推算 + 扫码锚定，室内短距定位' },
    { key: 'offline',  name: '离线缓存',   icon: 'fa-cloud-arrow-down',
      desc: '缓存座位数据，弱网/断网时仍可查看' },
    { key: 'shortcut', name: '桌面快捷方式', icon: 'fa-mobile-screen',
      desc: '长按 App 图标直接进入找空座 / 扫码 / 我的预约' },
    /* 悬浮按钮显示开关：与功能开关分开 ——
       有时功能要留着（比如从桌面快捷方式唤起语音），但不想让按钮一直占着屏幕。 */
    { key: 'show_voice', name: '显示语音按钮', icon: 'fa-microphone-lines',
      desc: '关闭后 AI 圆球旁的麦克风按钮会隐藏（语音功能本身不受影响）' },
    { key: 'show_ai',    name: '显示 AI 助手悬浮球', icon: 'fa-comment-dots',
      desc: '关闭后右下角的 AI 圆球会隐藏，界面更清爽（AI 接口仍可正常调用）' },
  ];

  var DEFAULTS = {};
  FEATURES.forEach(function (f) { DEFAULTS[f.key] = true; });   // 默认全开

  function cache() { return window.Native || null; }

  async function readAll() {
    var c = cache();
    if (c) {
      try {
        var v = await c.cacheGet(STORE_KEY);
        if (v && typeof v === 'object') return Object.assign({}, DEFAULTS, v);
      } catch (e) { }
    }
    try {
      var s = localStorage.getItem(STORE_KEY);
      if (s) return Object.assign({}, DEFAULTS, JSON.parse(s));
    } catch (e) { }
    return Object.assign({}, DEFAULTS);
  }

  async function writeAll(obj) {
    var c = cache();
    if (c) { try { await c.cacheSet(STORE_KEY, obj); } catch (e) { } }
    try { localStorage.setItem(STORE_KEY, JSON.stringify(obj)); } catch (e) { }
  }

  var _cacheObj = null;

  var NativeSettings = {
    FEATURES: FEATURES,
    DEFAULTS: DEFAULTS,

    async all() {
      if (!_cacheObj) _cacheObj = await readAll();
      return _cacheObj;
    },

    async get(key) {
      var a = await this.all();
      return a[key] !== false;      // 未设置视为 true
    },

    async set(key, val) {
      var a = await this.all();
      a[key] = !!val;
      _cacheObj = a;
      await writeAll(a);
      // 通知各功能模块实时启停
      try { window.dispatchEvent(new CustomEvent('nativesettings:change', { detail: { key: key, value: !!val } })); } catch (e) { }
    },

    async toggle(key) {
      var cur = await this.get(key);
      await this.set(key, !cur);
      return !cur;
    },

    /* ---------------- 设置面板 UI ---------------- */
    async openPanel() {
      if (document.getElementById('ns-panel')) return;
      var st = await this.all();

      var overlay = document.createElement('div');
      overlay.id = 'ns-panel';
      overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.45);'
        + 'display:flex;align-items:flex-end;justify-content:center;';

      var card = document.createElement('div');
      card.style.cssText = 'width:100%;max-width:520px;max-height:82vh;overflow:auto;'
        + 'background:#fff;border-radius:18px 18px 0 0;padding:18px 18px 26px;'
        + 'box-shadow:0 -6px 30px rgba(0,0,0,.28);';

      var head = document.createElement('div');
      head.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;';
      head.innerHTML = '<div style="font-size:18px;font-weight:700;color:#1f2937;">'
        + '<i class="fas fa-sliders" style="color:#1a73e8;margin-right:8px;"></i>移动端功能</div>'
        + '<button id="ns-close" style="border:none;background:#f1f3f4;border-radius:50%;'
        + 'width:32px;height:32px;font-size:16px;cursor:pointer;">✕</button>';
      card.appendChild(head);

      var sub = document.createElement('p');
      sub.style.cssText = 'color:#6b7280;font-size:12.5px;margin:0 0 14px;';
      sub.textContent = '以下功能默认全部开启，可按需关闭。设置会保存在本机。';
      card.appendChild(sub);

      /* 浏览器中打开时的说明（原生能力自动降级，避免误以为坏了） */
      if (!(window.Native && window.Native.available)) {
        var warn = document.createElement('p');
        warn.style.cssText = 'background:#fff7e6;border:1px solid #ffe0a3;color:#8a6d3b;'
          + 'font-size:12px;line-height:1.6;border-radius:10px;padding:9px 11px;margin:0 0 12px;';
        warn.innerHTML = '<i class="fas fa-info-circle"></i> 当前是浏览器模式：'
          + '扫码占座 / 语音选座 / 传感器导航 / 地理围栏需要装 App 才能调用；'
          + '离线缓存和这里的开关在网页上同样生效。';
        card.appendChild(warn);
      }

      FEATURES.forEach(function (f) {
        var on = st[f.key] !== false;
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:12px;padding:12px 4px;'
          + 'border-bottom:1px solid #f0f2f5;';

        var sw = document.createElement('label');
        sw.style.cssText = 'position:relative;display:inline-block;width:46px;height:26px;flex:0 0 46px;';
        sw.innerHTML = '<input type="checkbox" data-key="' + f.key + '" ' + (on ? 'checked' : '')
          + ' style="opacity:0;width:0;height:0;">'
          + '<span style="position:absolute;cursor:pointer;inset:0;border-radius:26px;'
          + 'transition:.25s;background:' + (on ? '#1a73e8' : '#cbd5e1') + ';"></span>'
          + '<span class="ns-knob" style="position:absolute;height:20px;width:20px;left:'
          + (on ? '23px' : '3px') + ';bottom:3px;background:#fff;border-radius:50%;'
          + 'transition:.25s;box-shadow:0 1px 3px rgba(0,0,0,.3);"></span>';

        var txt = document.createElement('div');
        txt.style.cssText = 'flex:1;min-width:0;';
        txt.innerHTML = '<div style="font-size:14.5px;font-weight:600;color:#1f2937;">'
          + '<i class="fas ' + f.icon + '" style="color:#1a73e8;width:18px;"></i> ' + f.name + '</div>'
          + '<div style="font-size:12px;color:#8a94a6;margin-top:2px;line-height:1.45;">' + f.desc + '</div>';

        row.appendChild(sw);
        row.appendChild(txt);
        card.appendChild(row);

        var cb = sw.querySelector('input');
        cb.addEventListener('change', async function () {
          var val = cb.checked;
          var track = sw.querySelector('span');
          var knob = sw.querySelector('.ns-knob');
          track.style.background = val ? '#1a73e8' : '#cbd5e1';
          knob.style.left = val ? '23px' : '3px';
          await NativeSettings.set(f.key, val);
        });
      });

      var tip = document.createElement('p');
      tip.style.cssText = 'margin-top:14px;font-size:11.5px;color:#9aa4b2;line-height:1.6;';
      tip.innerHTML = '提示：传感器导航为「扫码锚定 + 短距惯性推算」，'
        + '不走蓝牙信标方案；长时间使用会有累积误差，建议每走一段扫一次码校准。';
      card.appendChild(tip);

      overlay.appendChild(card);
      document.body.appendChild(overlay);

      function close() { overlay.remove(); }
      overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
      card.querySelector('#ns-close').onclick = close;
    },

    /* 左下角齿轮按钮（仅 App 内显示） */
    mountButton() {
      if (document.getElementById('ns-btn')) return;
      var b = document.createElement('button');
      b.id = 'ns-btn';
      b.innerHTML = '<i class="fas fa-sliders"></i>';
      b.title = '移动端功能设置';
      b.style.cssText = 'position:fixed;left:12px;bottom:44px;z-index:9997;'
        + 'width:38px;height:38px;border:none;border-radius:50%;background:rgba(26,115,232,.92);'
        + 'color:#fff;font-size:16px;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.25);';
      b.onclick = function () { NativeSettings.openPanel(); };
      document.body.appendChild(b);
    },
  };

  window.NativeSettings = NativeSettings;
  console.log('[NativeSettings] 就绪，功能项 =', FEATURES.map(function (f) { return f.key; }).join(','));
})();

/* ================= native-features.js ================= */
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
        if (!seat) { toast('未找到该座位，锚定失败', 'error'); return null; }
        // 座位没配坐标时是 (0,0)，锚上去会把推算位置画到平面图左上角，
        // 比不锚定更糟 —— 宁可不锚，也不能给一个错的位置。
        if (!seat.x && !seat.y) {
          toast('座位「' + (seat.seat_label || sid) + '」还没在平面图上标位置，无法锚定。'
            + '请管理员在「平面图与路网配置」里给它设置坐标。', 'error');
          return null;
        }
        Pdr.anchor(seat.x, seat.y, seat.seat_label);
        Pdr.anchorSeatId = seat.id;
        toast('已锚定位置：' + seat.seat_label + '，开始步态推算');
        return seat;
      } catch (e) { }
      toast('锚定失败：读取座位信息出错', 'error');
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

      if (!(window.Native && window.Native.available)) {
        toast('语音选座需要装 App 才能用（网页版没有麦克风权限）', 'error');
        return;
      }

      var ok = await window.Native.speechAvailable();
      if (!ok) {
        /* 设备没有语音识别服务。

           注意这跟麦克风权限无关 —— 插件的 available() 查的是
           SpeechRecognizer.isRecognitionAvailable()，即系统里有没有
           android.speech.RecognitionService。国产 ROM 很常见：
           Google 语音服务未装/未启用，厂商自己的语音助手又不对外
           暴露 RecognitionService，于是第三方应用一个都调不到。

           以前这里直接报「需在 App 内并授权麦克风」，把用户引到权限上去，
           查半天也查不出所以然。现在改成如实说明，并退化为文字输入 ——
           功能不该因为一个系统服务缺失就整个消失。 */
        this.askByText('本机没有语音识别服务（国产系统常见），可以直接打字');
        return;
      }

      toast('请说话…（例如「找个空座」）');
      var text = await window.Native.listenOnce('zh-CN');
      if (!text) { toast('没听清，请再试一次', 'error'); return; }
      toast('识别到：' + text);
      var intent = this.parseIntent(text);
      console.log('[语音意图]', intent);
      await this.execute(intent);
    },

    /* 无语音服务时的文字兜底：输入一句话，走完全一样的意图解析。

       这样「说一句话完成找座」这条链路在任何手机上都能演示，
       答辩现场也不怕评委的设备没有语音服务。 */
    askByText(hint) {
      if (document.getElementById('feat-voice-text')) return;
      var self = this;

      var mask = el('div',
        'position:fixed;left:0;right:0;top:0;bottom:0;z-index:99999;'
        + 'background:rgba(0,0,0,.45);display:flex;align-items:center;'
        + 'justify-content:center;padding:20px;');
      mask.id = 'feat-voice-text';

      var card = el('div',
        'background:#fff;border-radius:14px;padding:18px;width:100%;max-width:340px;'
        + 'box-shadow:0 12px 40px rgba(0,0,0,.3);');

      card.innerHTML =
        '<div style="font-size:15px;font-weight:600;color:#1f2d4d;margin-bottom:6px;">'
        + '🎤 语音选座</div>'
        + '<div style="font-size:12.5px;color:#8a94a6;line-height:1.6;margin-bottom:12px;">'
        + (hint || '输入一句话') + '</div>'
        + '<input id="feat-voice-input" type="text" placeholder="例如：找个空座 / 预约 A-4" '
        + 'style="width:100%;box-sizing:border-box;padding:10px 12px;font-size:14px;'
        + 'border:1px solid #d7e0ec;border-radius:9px;outline:none;font-family:inherit;">'
        + '<div style="display:flex;gap:8px;margin-top:12px;">'
        + '  <button id="feat-voice-go" style="flex:1;padding:10px;border:none;border-radius:9px;'
        + 'background:#7c5cff;color:#fff;font-size:14px;cursor:pointer;font-family:inherit;">'
        + '确定</button>'
        + '  <button id="feat-voice-cancel" style="padding:10px 16px;border:none;border-radius:9px;'
        + 'background:#eef2f7;color:#5a6b80;font-size:14px;cursor:pointer;font-family:inherit;">'
        + '取消</button>'
        + '</div>';

      mask.appendChild(card);
      document.body.appendChild(mask);

      var input = card.querySelector('#feat-voice-input');
      input.focus();
      setTimeout(function () { try { input.focus(); } catch (e) { } }, 200);

      function close() { if (mask.parentNode) mask.parentNode.removeChild(mask); }
      function go() {
        var t = (input.value || '').trim();
        close();
        if (!t) return;
        var intent = self.parseIntent(t);
        console.log('[文字意图]', intent);
        self.execute(intent);
      }
      card.querySelector('#feat-voice-go').onclick = go;
      card.querySelector('#feat-voice-cancel').onclick = close;
      mask.onclick = function (e) { if (e.target === mask) close(); };
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); go(); }
      });
    },

    /* 语音按钮：做成 AI 悬浮球左边的第二个圆按钮。

       这里以前有两个问题：
         ① 挂载选择器写的是 "#ai-assistant, .ai-assistant, [class*=\"ai-assist\"]"，
            而 AI 助手的实际类名前缀是 aias-（.aias-root / .aias-panel …），
            选择器永远匹配不到 —— 按钮从来没挂上去过。
            文档里却写着「点 AI 助手图标旁的语音按钮」，用户当然找不到。
         ② 挂上去的还是一个内嵌文本按钮（"🎤 语音选座"），得先打开面板才看得见。

       现在：挂进 .aias-root，做成和悬浮球同风格的圆按钮，摆在它左边。
       放在 .aias-root 内部的好处是能跟着长按拖动一起走。 */
    mountButton(container) {
      if (document.getElementById('feat-voice-btn')) return;

      /* 「显示语音按钮」开关：关掉就把已有的按钮摘掉。
         和「语音选座」功能开关分开 —— 功能留着（桌面快捷方式还能唤起），
         只是不让按钮一直占着屏幕。 */
      var self = this;
      if (window.NativeSettings && window.NativeSettings.get) {
        window.NativeSettings.get('show_voice').then(function (on) {
          if (on === false) {
            var old = document.getElementById('feat-voice-btn');
            if (old && old.parentNode) old.parentNode.removeChild(old);
          }
        }).catch(function () { });
      }

      var host = container || document.querySelector('.aias-root');
      var inside = !!host;
      if (!host) host = document.body;

      // 挂在悬浮球里 -> 相对它定位（跟着拖动走）；
      // 页面没有 AI 助手时才退回固定定位，坐标对齐悬浮球左侧。
      var pos = inside
        ? 'position:absolute;right:64px;bottom:0;'
        : 'position:fixed;right:86px;bottom:22px;z-index:9000;';

      var b = el('button',
        pos + 'width:46px;height:46px;border-radius:50%;border:none;cursor:pointer;'
        + 'background:linear-gradient(135deg,#7c5cff,#b06bff);color:#fff;'
        + 'font-size:19px;line-height:1;padding:0;'
        + 'box-shadow:0 6px 18px rgba(124,92,255,.42);transition:transform .18s;',
        '🎤');
      b.id = 'feat-voice-btn';
      b.type = 'button';
      b.title = '语音选座：说「找个空座」';
      b.onclick = function () { VoiceFeat.listenAndRun(); };
      b.onmouseenter = function () { b.style.transform = 'scale(1.06)'; };
      b.onmouseleave = function () { b.style.transform = ''; };
      host.appendChild(b);
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
    // 推算位置（平面图像素坐标）。锚定后从锚点出发，按朝向与步长逐步外推。
    posX: null, posY: null,
    STEP_LEN: 0.65,          // 平均步长（米）
    STEP_MIN_MS: 280,        // 最小步间隔，防抖
    floor: 9.8,             // 加速度模长的泄漏式最小值（跟随静止水平，不被走路峰值带走）
    threshold: 12.0,         // 当前生效的步态阈值（自适应，仅用于显示）

    /* 平面图比例尺：1 米 = 多少像素。
       不同平面图尺度不同（同一栋楼换张图就不一样），所以做成可调，
       默认按「806x1080 的图约合 40m x 54m」取 20 px/m。
       改比例尺后立刻按当前步数重算位置，不用重新走一遍。 */
    get pxPerM() {
      var v = parseFloat(localStorage.getItem('pdr_px_per_m'));
      return (isFinite(v) && v > 1) ? v : 20;
    },
    set pxPerM(v) {
      var n = parseFloat(v);
      if (!isFinite(n) || n <= 1) return;
      try { localStorage.setItem('pdr_px_per_m', String(n)); } catch (e) { }
      this.recomputeFromSteps();
      this.render();
      this.emit();
    },

    /* 从「锚点 + 累计距离 + 当前朝向」重算推算位置。
       朝向约定与室外方位图一致：0° = 正北 = 屏幕正上方，顺时针增大。
       平面图像素坐标 x 向右、y 向下，所以：
         dx = d * sin(θ)，dy = -d * cos(θ)  */
    recomputeFromSteps() {
      if (this.anchorX == null) { this.posX = null; this.posY = null; return; }
      var d = this.distM * this.pxPerM;              // 米 -> 像素
      var rad = this.heading * Math.PI / 180;
      this.posX = this.anchorX + d * Math.sin(rad);
      this.posY = this.anchorY - d * Math.cos(rad);
    },

    /* 把推算位置广播给页面（导航页据此画到平面图上）。
       用事件而不是直接调导航页的函数：这个模块不知道当前在哪个页面。 */
    emit() {
      try {
        window.dispatchEvent(new CustomEvent('pdr:position', {
          detail: {
            x: this.posX, y: this.posY,
            anchorX: this.anchorX, anchorY: this.anchorY,
            anchorLabel: this.anchorLabel,
            steps: this.steps, distM: this.distM,
            heading: this.heading,
            anchored: this.anchorX != null,
            pxPerM: this.pxPerM,
          }
        }));
      } catch (e) { }
    },

    onMotion(e) {
      var a = e.accelerationIncludingGravity || e.acceleration;
      if (!a) return;
      var mag = Math.sqrt((a.x || 0) * (a.x || 0) + (a.y || 0) * (a.y || 0) + (a.z || 0) * (a.z || 0));
      var now = Date.now();

      /* 步态阈值：跟着「静止水平」走，而不是跟着均值走。

         原来写死 13.5 —— 真机实测这台手机静止时模长只有 8.6 左右
         （低于重力 9.8），正常走路的峰值也就 10~11.5，写死 13.5 一步都不记。

         第一版改成低通滤波（base = base*0.996 + mag*0.004）也不行：
         走路的峰值会把基线整体抬高，阈值跟着涨，越走越不记步
         （实测走十几步只记到 8 步）。

         现在用「泄漏式最小值包络」：
           · 被更小的值拉低（捕捉静止水平）
           · 自身缓慢回升（每秒约 1.2）
         走路时每次落脚都会把它压回静止水平，所以它始终贴着地面走，
         不会像均值那样被峰值带跑。换手机、换握法都能自适应。 */
      this.floor = Math.min(mag, this.floor + 0.02);
      var thr = Math.min(14.0, Math.max(9.5, this.floor + 1.7));
      this.threshold = thr;

      // 简易峰值检测：超过阈值且距上一步足够久 => 记一步
      if (mag > thr && this.lastMag <= thr && (now - this.lastStepAt) > this.STEP_MIN_MS) {
        this.steps++;
        this.distM += this.STEP_LEN;
        this.lastStepAt = now;
        // 只在「走出一步」时积分位置 —— 朝向事件每秒几十次且抖动大，
        // 拿它算位移会让人原地乱飘，那不是惯性推算，是噪声。
        this.recomputeFromSteps();
        this.render();
        this.emit();
      }
      this.lastMag = mag;
    },

    onOrient(e) {
      if (typeof e.webkitCompassHeading === 'number') this.heading = e.webkitCompassHeading;
      else if (typeof e.alpha === 'number') this.heading = (360 - e.alpha) % 360;
      var arrow = document.getElementById('pdr-arrow');
      if (arrow) arrow.style.transform = 'rotate(' + Math.round(this.heading) + 'deg)';
      var h = document.getElementById('pdr-head');
      if (h) h.textContent = Math.round(this.heading) + '°';
      // ★ 收起时的摘要也要跟着刷新。
      //   朝向事件每秒二十来次，不能整个 render()（会重排面板），
      //   但摘要那一行只是改文本，顺手更新掉 —— 否则胶囊永远显示「0°」。
      var sum = document.getElementById('pdr-sum');
      if (sum && this.collapsed) {
        sum.textContent = this.steps + ' 步 · ' + Math.round(this.heading) + '°';
      }
    },

    anchor(x, y, label) {
      this.anchorX = x; this.anchorY = y; this.anchorLabel = label || null;
      this.steps = 0; this.distM = 0;
      this.recomputeFromSteps();     // 位置立刻回到锚点
      this.render();
      this.emit();
    },

    /* 把比例尺按「这两点在图上的像素距离 ÷ 你能量出来的实际米数」标定一次。
       默认值 20 px/m 只是按典型图书馆平面图估的 —— 换一张图、换一栋楼都不准，
       所以提供一个能自己量的入口，比猜一个数可靠。 */
    calibrate(px1, py1, px2, py2, realMeters) {
      var px = Math.sqrt((px2 - px1) * (px2 - px1) + (py2 - py1) * (py2 - py1));
      if (!(px > 0) || !(realMeters > 0)) return null;
      var v = px / realMeters;
      if (v < 2 || v > 200) return null;
      this.pxPerM = v;
      return v;
    },

    render() {
      var box = document.getElementById('pdr-box');
      if (!box) return;
      $('#pdr-steps', box).textContent = this.steps + ' 步';
      $('#pdr-dist', box).textContent = this.distM.toFixed(1) + ' m';
      $('#pdr-head', box).textContent = Math.round(this.heading) + '°';
      var thr = $('#pdr-thr', box);
      if (thr) thr.textContent = this.threshold.toFixed(1) + ' / 基线 ' + this.floor.toFixed(1);
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
      var ppm = $('#pdr-ppm', box);
      if (ppm && document.activeElement !== ppm) ppm.value = this.pxPerM;
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
        + '<div style="display:flex;justify-content:space-between;margin-top:4px;font-size:11.5px;color:#8a94a6;">'
        + '<span>步态阈值（自适应）</span><b id="pdr-thr">—</b></div>'
        + '<div style="margin-top:8px;font-size:11.5px;color:#8a94a6;">'
        + '锚点：<span id="pdr-anchor">未锚定</span></div>'
        // 比例尺：把「米」换算成平面图像素的唯一依据，换一张图就要调
        + '<div style="display:flex;align-items:center;gap:6px;margin-top:8px;font-size:11.5px;color:#8a94a6;">'
        + '<span>比例尺</span>'
        + '<input id="pdr-ppm" type="number" min="2" max="200" step="1" inputmode="decimal" '
        + 'style="width:56px;padding:3px 5px;border:1px solid #dbe4f0;border-radius:6px;'
        + 'font-size:11.5px;font-family:inherit;text-align:right;">'
        + '<span>像素/米</span></div>'
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
      var ppmInput = $('#pdr-ppm', box);
      ppmInput.value = this.pxPerM;
      ppmInput.onchange = function () { self.pxPerM = ppmInput.value; };
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

    /* AI 助手：挂语音按钮。
       ★ 选择器必须是 .aias-root —— AI 助手的类名前缀是 aias-，
         以前写成 [class*="ai-assist"] 永远匹配不到，按钮从没挂上去过。 */
    if (isApp) {
      var tries = 0;
      var t = setInterval(async function () {
        tries++;
        var box = document.querySelector('.aias-root');
        if (box && await on('voice')) { VoiceFeat.mountButton(box); clearInterval(t); }
        if (tries > 40) {
          clearInterval(t);
          // 找不到 AI 助手时也别让功能消失，用固定定位兜底挂一个
          if (await on('voice')) VoiceFeat.mountButton(null);
        }
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

    /* 悬浮按钮显示开关：实时响应，不用刷新页面 */
    if (isApp) {
      window.addEventListener('nativesettings:change', function (ev) {
        var d = ev.detail || {};
        if (d.key !== 'show_voice') return;
        if (d.value === false) {
          var b = document.getElementById('feat-voice-btn');
          if (b && b.parentNode) b.parentNode.removeChild(b);
        } else {
          VoiceFeat.mountButton(null);
        }
      });
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

/* ================= app-shell.js ================= */
/* ============================================================
   智座 · 移动端 App 外壳
   ------------------------------------------------------------
   ★ 只在 App 内生效 ★
   window.Native.available 为假（即普通浏览器）时，本文件直接返回，
   网页版界面一个像素都不动。

   做了什么：
     1. 顶部压成 54px 细条：☰ 抽屉按钮 + 当前页标题 + 头像
     2. 底部 5 个 Tab：首页 / 座位图 / 预约 / 导航 / 我的
     3. 侧边抽屉：品牌、用户名 + 角色徽章、全部导航链接、退出登录
        （链接直接从页面原有的 .nav-links 克隆，因此
          「管理」入口对非管理员隐藏等既有逻辑自动继承）
     4. 「App 模式」角标 3 秒后淡出，不再长期占位
   ============================================================ */
(function () {
  'use strict';

  if (!window.Native || !window.Native.available) return;
  if (window.__APP_SHELL_ON__) return;
  window.__APP_SHELL_ON__ = true;

  /* ---------------- 页面标题 / 底部 Tab 定义 ---------------- */

  var TITLES = {
    index: '智座',
    seat_map: '实时座位图',
    reservation: '我的预约',
    navigation: '室内导航',
    outdoor: '室外导航',
    profile: '个人中心',
    admin: '管理后台',
    login: '登录',
    terminal: '智能终端',
  };

  var TABS = [
    { key: 'index', href: '/index.html', icon: 'fa-home', label: '首页' },
    { key: 'seat_map', href: '/seat_map.html', icon: 'fa-chair', label: '座位图' },
    { key: 'reservation', href: '/reservation.html', icon: 'fa-calendar-check', label: '预约' },
    { key: 'navigation', href: '/navigation.html', icon: 'fa-directions', label: '导航' },
    { key: 'profile', href: '/profile.html', icon: 'fa-user', label: '我的' },
  ];

  function currentKey() {
    var p = location.pathname.replace(/\/+$/, '');
    if (p === '' || p === '/index.html') return 'index';
    if (/seat_map/.test(p)) return 'seat_map';
    if (/reservation/.test(p)) return 'reservation';
    if (/navigation/.test(p)) return 'navigation';
    if (/outdoor/.test(p)) return 'outdoor';
    if (/profile/.test(p)) return 'profile';
    if (/terminal/.test(p)) return 'terminal';
    if (/login/.test(p)) return 'login';
    if (/admin/.test(p)) return 'admin';
    return 'index';
  }

  /* 把模板里的相对链接（admin/dashboard.html、../seat_map.html）规范成站内绝对路径，
     这样从 /admin/xxx.html 打开时抽屉里的链接也不会点错。 */
  function absHref(h) {
    if (!h) return '#';
    if (/^(https?:)?\/\//.test(h) || h.charAt(0) === '/' || h.charAt(0) === '#') return h;
    return '/' + h.replace(/^(\.\.\/)+/, '').replace(/^\.\//, '');
  }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  /* ---------------- 样式注入 ---------------- */

  function injectCss() {
    var css = window.__APP_SHELL_CSS__;
    if (css) {
      var st = document.createElement('style');
      st.id = 'app-shell-style';
      st.textContent = css;
      document.head.appendChild(st);
      return;
    }
    // 兜底：没被内联进 bundle 时，按普通静态文件引入
    if (document.getElementById('app-shell-style')) return;
    var link = document.createElement('link');
    link.id = 'app-shell-style';
    link.rel = 'stylesheet';
    link.href = '/static/css/mobile-app.css';
    document.head.appendChild(link);
  }

  /* ---------------- 顶部细条 ---------------- */

  function buildTopbar(key) {
    var bar = el('div', 'app-topbar');

    var menu = el('button', 'app-topbar-btn', '<i class="fas fa-bars"></i>');
    menu.type = 'button';
    menu.setAttribute('aria-label', '菜单');
    menu.onclick = function () { toggleDrawer(true); };

    var title = el('span', 'app-topbar-title', TITLES[key] || '智座');

    var avatar = el('a', 'app-topbar-avatar', '<i class="fas fa-user"></i>');
    avatar.href = '/profile.html';
    avatar.setAttribute('data-app-avatar', '1');

    bar.appendChild(menu);
    bar.appendChild(title);
    bar.appendChild(avatar);
    return bar;
  }

  /* ---------------- 底部 Tab ---------------- */

  function buildTabbar(key) {
    var bar = el('nav', 'app-tabbar');
    TABS.forEach(function (t) {
      var a = el('a', 'app-tab' + (t.key === key ? ' active' : ''),
        '<i class="fas ' + t.icon + '"></i><span>' + t.label + '</span>');
      a.href = t.href;
      bar.appendChild(a);
    });
    return bar;
  }

  /* ---------------- 侧边抽屉 ---------------- */

  var maskEl = null, drawerEl = null, pageKey = 'index';

  function toggleDrawer(open) {
    if (!maskEl || !drawerEl) return;
    var want = (open === undefined) ? !drawerEl.classList.contains('open') : !!open;
    drawerEl.classList.toggle('open', want);
    maskEl.classList.toggle('open', want);
    document.documentElement.style.overflow = want ? 'hidden' : '';
  }
  window.AppShell = { open: function () { toggleDrawer(true); }, close: function () { toggleDrawer(false); } };

  /* 导航链接直接从页面原有的 .nav-links 克隆，因此「管理入口仅管理员可见」
     这类既有逻辑自动继承。
     ★ 必须在身份确定（CURRENT_USER_READY）之后重建一次 ——
       刚进页面时 shell-nav.js 还没拿到 /api/auth/me 的结果，
       这时克隆会把「管理」入口也带给匿名用户。 */
  function buildDrawerNav() {
    if (!drawerEl) return;
    var nav = drawerEl.querySelector('.app-drawer-nav');
    if (!nav) return;
    nav.innerHTML = '';

    var src = document.querySelectorAll('.nav-links a[data-nav]');
    var n = 0;
    for (var i = 0; i < src.length; i++) {
      var s = src[i];
      if (s.style.display === 'none') continue;      // 例如非管理员的「管理」入口
      if (s.getAttribute('data-injected-login')) continue;
      var k = s.getAttribute('data-nav');
      var a = el('a', k === pageKey ? 'active' : '', s.innerHTML);
      a.href = absHref(s.getAttribute('href'));
      nav.appendChild(a);
      n++;
    }
    // 一条链接都没有（未登录）时，至少给个回首页的入口
    if (!n) {
      var home = el('a', pageKey === 'index' ? 'active' : '', '<i class="fas fa-home"></i> 首页');
      home.href = '/index.html';
      nav.appendChild(home);
    }
  }

  function buildDrawer(key) {
    maskEl = el('div', 'app-drawer-mask');
    maskEl.onclick = function () { toggleDrawer(false); };

    drawerEl = el('aside', 'app-drawer');

    /* 头部：品牌 + 用户 + 角色 */
    var head = el('div', 'app-drawer-head');
    head.appendChild(el('div', 'app-drawer-brand',
      '<i class="fas fa-map-location-dot"></i> 智座'));
    head.appendChild(el('div', 'app-drawer-sub', '智能选座与导航一体化系统'));

    var userRow = el('div', 'app-drawer-user');
    userRow.appendChild(el('span', '', '<i class="fas fa-user-circle"></i>'));
    var nameSpan = el('span', '', '');
    nameSpan.setAttribute('data-app-user-name', '1');
    userRow.appendChild(nameSpan);
    var roleSpan = el('span', 'app-drawer-role', '');
    roleSpan.setAttribute('data-app-user-role', '1');
    userRow.appendChild(roleSpan);
    head.appendChild(userRow);
    drawerEl.appendChild(head);

    drawerEl.appendChild(el('div', 'app-drawer-nav'));
    buildDrawerNav();

    /* 底部：退出登录（复用页面原有按钮的逻辑与登录态判断） */
    var foot = el('div', 'app-drawer-foot');
    var out = el('button', 'app-drawer-logout', '<i class="fas fa-right-from-bracket"></i> 退出登录');
    out.type = 'button';
    out.onclick = function () {
      var b = document.querySelector('[data-logout]');
      if (b && b.style.display !== 'none') { b.click(); return; }
      location.href = '/logout';
    };
    foot.appendChild(out);
    drawerEl.appendChild(foot);

    return { mask: maskEl, drawer: drawerEl };
  }

  /* ---------------- 用户信息回填 ----------------
     ★ 不能用 [data-user-name] 的 textContent —— 模板里写死的是「演示用户」，
       shell-nav.js 只把容器 display:none 掉，文字还在，读出来就是假的。
       唯一可信来源是 shell-nav.js 设置的 window.CURRENT_USER。 */
  function isLoggedIn() {
    var u = window.CURRENT_USER;
    return !!(u && (u.id || u.user_id || u.student_id || u.name));
  }

  function doLogout() {
    try { localStorage.removeItem('seat_app_current_user'); } catch (e) { }
    var b = document.querySelector('[data-logout]');
    if (b) { b.click(); return; }          // 复用 shell-nav.js 的退出逻辑
    location.href = '/logout';
  }

  function fillUser() {
    var u = window.CURRENT_USER || null;
    var loggedIn = isLoggedIn();

    var name = loggedIn ? (u.name || u.student_id || '用户') : '未登录';
    var role = loggedIn ? (u.role_label || '') : '';

    var target = drawerEl && drawerEl.querySelector('[data-app-user-name]');
    if (target) target.textContent = name;

    var rt = drawerEl && drawerEl.querySelector('[data-app-user-role]');
    if (rt) {
      if (role) { rt.textContent = role; rt.style.display = ''; }
      else { rt.style.display = 'none'; }
    }

    // 顶栏头像：登录了去个人中心，没登录去登录页
    var av = document.querySelector('[data-app-avatar]');
    if (av) {
      av.href = loggedIn ? '/profile.html' : '/login';
      var srcImg = loggedIn ? document.querySelector('.user-info .avatar img') : null;
      if (srcImg && srcImg.src) av.innerHTML = '<img src="' + srcImg.src + '" alt="">';
      else av.innerHTML = '<i class="fas fa-user"></i>';
    }

    // 底部按钮：登录态决定是「退出登录」还是「去登录」
    var outBtn = drawerEl && drawerEl.querySelector('.app-drawer-logout');
    if (outBtn) {
      if (loggedIn) {
        outBtn.className = 'app-drawer-logout';
        outBtn.innerHTML = '<i class="fas fa-right-from-bracket"></i> 退出登录';
        outBtn.onclick = doLogout;
      } else {
        outBtn.className = 'app-drawer-logout app-drawer-login';
        outBtn.innerHTML = '<i class="fas fa-right-to-bracket"></i> 去登录';
        outBtn.onclick = function () { location.href = '/login'; };
      }
    }

    // 身份确定后重建抽屉链接（管理入口的可见性此时才是准的）
    buildDrawerNav();
  }

  function whenUserReady(fn) {
    if (window.CURRENT_USER_READY) { fn(); return; }
    var tries = 0;
    var t = setInterval(function () {
      if (window.CURRENT_USER_READY || ++tries > 40) { clearInterval(t); fn(); }
    }, 200);
  }

  /* ---------------- 启动 ---------------- */

  function boot() {
    if (!document.body) return;
    injectCss();
    document.body.classList.add('app-mode');

    var key = currentKey();
    pageKey = key;

    document.body.appendChild(buildTopbar(key));
    document.body.appendChild(buildTabbar(key));
    var d = buildDrawer(key);
    document.body.appendChild(d.mask);
    document.body.appendChild(d.drawer);

    whenUserReady(fillUser);

    // 抽屉链接里的当前页高亮，在身份确定后重新算一次（管理入口可能刚出现）
    whenUserReady(function () {
      setTimeout(function () {
        if (drawerEl) fillUser();
      }, 400);
    });

    // 「App 模式」角标：亮 3 秒后淡出，不再长期占地方
    setTimeout(function () {
      var b = document.getElementById('feat-badge');
      if (!b) return;
      b.style.transition = 'opacity .6s';
      b.style.opacity = '0';
      setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 700);
    }, 3000);

    console.log('[AppShell] 智座移动端外壳已启用, 当前页 =', key);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

/* ================= drag-fab.js ================= */
/* ============================================================
   悬浮按钮长按拖动（只有 App 内生效）
   ------------------------------------------------------------
   目标：AI 助手气泡、扫码占座按钮
   交互：
     · 长按 ~0.45 秒进入拖动模式（震动一下 + 视觉反馈）
     · 拖动跟随手指，自动夹在屏幕内
     · 松手把位置写进本机，下次打开沿用
     · 短按/单击行为完全不变（该开 AI 还是开 AI，该扫码还是扫码）
     · 拖动结束后的那一次 click 会被吞掉，避免误触

   为什么单独一个文件：这两个按钮分别由 ai-assistant.js 和
   native-features.js 动态创建，时机不定，所以这里用
   MutationObserver + 定时扫描兜住。

   ★ 只在 window.Native.available 为真（App 内）时运行，
     浏览器里直接 return，网页版不受影响。
   ============================================================ */
(function () {
  'use strict';

  if (!window.Native || !window.Native.available) return;
  if (window.__FAB_DRAG_ON__) return;
  window.__FAB_DRAG_ON__ = true;

  var HOLD_MS = 450;          // 长按判定
  var MOVE_TOL = 8;           // 长按期间允许的抖动
  var EDGE = 6;               // 离屏幕边缘留白
  var KEY = 'fab_pos_v1';

  var TARGETS = [
    { sel: '.aias-root', id: 'ai', name: 'AI 助手' },
    { sel: '#feat-scan-fab', id: 'scan', name: '扫码占座' }
  ];

  /* ---------------- 位置存取 ---------------- */
  function readAll() {
    try {
      var v = JSON.parse(localStorage.getItem(KEY) || '{}');
      return (v && typeof v === 'object') ? v : {};
    } catch (e) { return {}; }
  }

  function writeAll(o) {
    try { localStorage.setItem(KEY, JSON.stringify(o)); } catch (e) { }
  }

  function resetAll() {
    try { localStorage.removeItem(KEY); } catch (e) { }
    TARGETS.forEach(function (t) {
      var el = document.querySelector(t.sel);
      if (!el) return;
      ['left', 'top', 'right', 'bottom'].forEach(function (p) {
        el.style.removeProperty(p);
      });
      delete el.dataset.fabLeft;
      delete el.dataset.fabTop;
    });
  }

  /* ---------------- 移动 + 夹在屏幕内 ---------------- */
  function moveTo(el, left, top) {
    var r = el.getBoundingClientRect();
    var w = r.width || 44, h = r.height || 44;
    var maxX = Math.max(EDGE, window.innerWidth - w - EDGE);
    var maxY = Math.max(EDGE, window.innerHeight - h - EDGE);
    left = Math.max(EDGE, Math.min(maxX, left));
    top = Math.max(EDGE, Math.min(maxY, top));

    // 样式表里有 bottom:...!important，所以这里也必须 important 才盖得住
    el.style.setProperty('left', left + 'px', 'important');
    el.style.setProperty('top', top + 'px', 'important');
    el.style.setProperty('right', 'auto', 'important');
    el.style.setProperty('bottom', 'auto', 'important');
    el.dataset.fabLeft = String(Math.round(left));
    el.dataset.fabTop = String(Math.round(top));
  }

  function applySaved(id, el) {
    var p = readAll()[id];
    if (!p || !isFinite(p.left) || !isFinite(p.top)) return false;
    // 等一帧，让按钮尺寸定下来再按边界夹一次
    requestAnimationFrame(function () { moveTo(el, p.left, p.top); });
    return true;
  }

  function save(id, el) {
    var l = parseFloat(el.dataset.fabLeft), t = parseFloat(el.dataset.fabTop);
    if (!isFinite(l) || !isFinite(t)) return;
    var all = readAll();
    all[id] = { left: l, top: t };
    writeAll(all);
  }

  /* ---------------- 绑定一个按钮 ---------------- */
  function attach(el, id) {
    if (!el || el.__fabDrag) return;
    el.__fabDrag = true;

    // 小圆钮不需要靠"在它上面滑动"来滚页面，直接吃掉手势
    el.style.touchAction = 'none';
    el.style.webkitUserSelect = 'none';
    el.style.userSelect = 'none';
    el.style.webkitTouchCallout = 'none';

    var st = { down: false, dragging: false, timer: null, sx: 0, sy: 0, ox: 0, oy: 0, swallow: false };

    el.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button !== 0 && e.pointerType === 'mouse') return;
      st.down = true;
      st.dragging = false;
      st.sx = e.clientX;
      st.sy = e.clientY;
      var r = el.getBoundingClientRect();
      st.ox = r.left;
      st.oy = r.top;
      clearTimeout(st.timer);
      st.timer = setTimeout(function () {
        if (!st.down) return;
        st.dragging = true;
        el.classList.add('fab-dragging');
        try { el.setPointerCapture(e.pointerId); } catch (err) { }
        try { window.Native.vibrate && window.Native.vibrate(18); } catch (err) { }
      }, HOLD_MS);
    });

    el.addEventListener('pointermove', function (e) {
      if (!st.down) return;
      if (!st.dragging) {
        // 还没到长按时间就滑走了 -> 当成普通滑动，取消长按
        if (Math.abs(e.clientX - st.sx) > MOVE_TOL ||
            Math.abs(e.clientY - st.sy) > MOVE_TOL) {
          clearTimeout(st.timer);
          st.down = false;
        }
        return;
      }
      e.preventDefault();
      moveTo(el, st.ox + (e.clientX - st.sx), st.oy + (e.clientY - st.sy));
    });

    function end() {
      clearTimeout(st.timer);
      if (st.dragging) {
        st.dragging = false;
        el.classList.remove('fab-dragging');
        save(id, el);
        // 吞掉紧跟其后的那次 click
        st.swallow = true;
        setTimeout(function () { st.swallow = false; }, 400);
      }
      st.down = false;
    }

    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
    el.addEventListener('pointerleave', function () { if (!st.dragging) end(); });

    // 捕获阶段拦掉拖动后的误触
    el.addEventListener('click', function (e) {
      if (st.swallow) {
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);

    el.title = (el.title ? el.title + ' · ' : '') + '长按可拖动';
  }

  /* ---------------- 扫描 + 应用 ---------------- */
  function scan() {
    TARGETS.forEach(function (t) {
      var el = document.querySelector(t.sel);
      if (!el || el.__fabDrag) return;
      attach(el, t.id);
      applySaved(t.id, el);
    });
  }

  var pending = null;
  function scheduleScan() {
    if (pending) return;
    pending = setTimeout(function () { pending = null; scan(); }, 200);
  }

  /* ---------------- 设置面板里加「复位」 ---------------- */
  function hookPanel() {
    var mo = new MutationObserver(function () {
      var panel = document.getElementById('ns-panel');
      if (!panel || panel.querySelector('[data-fab-reset]')) return;
      var card = panel.firstElementChild;
      if (!card) return;

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('data-fab-reset', '1');
      btn.innerHTML = '<i class="fas fa-arrows-up-down-left-right"></i> 复位悬浮按钮位置';
      btn.style.cssText = 'margin-top:12px;width:100%;padding:10px;border:1px solid #dbe4f0;'
        + 'border-radius:10px;background:#f7fafd;color:#1a73e8;font-size:13.5px;'
        + 'font-family:inherit;cursor:pointer;';
      btn.onclick = function () {
        resetAll();
        btn.innerHTML = '<i class="fas fa-check"></i> 已复位';
        setTimeout(function () {
          btn.innerHTML = '<i class="fas fa-arrows-up-down-left-right"></i> 复位悬浮按钮位置';
        }, 1500);
      };
      card.appendChild(btn);
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  /* ---------------- 启动 ---------------- */
  function boot() {
    scan();
    hookPanel();
    // 按钮是异步创建的，用观察者 + 兜底轮询双重保险
    try {
      new MutationObserver(scheduleScan).observe(document.body, {
        childList: true, subtree: true
      });
    } catch (e) { }
    var n = 0;
    var t = setInterval(function () {
      scan();
      if (++n > 40) clearInterval(t);   // 最多盯 20 秒
    }, 500);
    // 转屏/改窗口大小后重新夹一次
    window.addEventListener('resize', function () {
      TARGETS.forEach(function (tg) {
        var el = document.querySelector(tg.sel);
        if (el && el.dataset.fabLeft) {
          moveTo(el, parseFloat(el.dataset.fabLeft), parseFloat(el.dataset.fabTop));
        }
      });
    });
    console.log('[FabDrag] 长按拖动已启用（AI 助手 / 扫码占座）');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();


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

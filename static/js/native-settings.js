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

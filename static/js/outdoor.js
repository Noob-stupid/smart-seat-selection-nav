/* ============================================================
   室外导航（从当前位置导航到建筑）
   ------------------------------------------------------------
   设计：地图为主 + 方位导航兜底（与本项目 AI 的降级思路一致）

   主方案 B：加载高德 JS API，画真实步行路线
   兜底 A ：自建方位导航（罗盘箭头 + 直线距离），完全离线可用
   附加  C：一键用手机地图 App 打开（URI scheme）

   自动降级条件：未配置 key / SDK 加载失败 / 超时 / 无网络
   ============================================================ */
const { createApp } = Vue;

/* ---------------- 通用数学 ---------------- */
const R_EARTH = 6371000;                    // 地球半径（米）

function haversine(lat1, lng1, lat2, lng2) {
  const rad = d => d * Math.PI / 180;
  const dLat = rad(lat2 - lat1), dLng = rad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R_EARTH * Math.asin(Math.sqrt(a));
}

function bearing(lat1, lng1, lat2, lng2) {
  const rad = d => d * Math.PI / 180, deg = r => r * 180 / Math.PI;
  const y = Math.sin(rad(lng2 - lng1)) * Math.cos(rad(lat2));
  const x = Math.cos(rad(lat1)) * Math.sin(rad(lat2)) -
    Math.sin(rad(lat1)) * Math.cos(rad(lat2)) * Math.cos(rad(lng2 - lng1));
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

function compassText(b) {
  const dirs = ['正北', '东北', '正东', '东南', '正南', '西南', '正西', '西北'];
  return dirs[Math.round(b / 45) % 8];
}

function distanceText(m) {
  if (m == null) return '';
  return m < 1000 ? Math.round(m) + ' 米' : (m / 1000).toFixed(2) + ' 公里';
}

createApp({
  delimiters: ['${', '}'],

  data() {
    return {
      cfg: { provider: 'amap', key: '', security_code: '', has_key: false,
             fallback_enabled: true, logged_in: false },
      destinations: [],
      missingCoords: 0,
      myPos: null,                 // {lat, lng, accuracy}
      myPosAt: 0,                  // 上一次定位成功的时间戳
      locating: false,
      locError: '',                // 没有任何位置时的硬错误（红）
      locWarn: '',                 // 已有位置、只是这次刷新失败的提示（灰）
      navMode: 'map',              // map | fallback
      mapReason: '',               // 为什么走了方位导航兜底
      active: null,
      routeInfo: null,             // {distance, duration}
      map: null,
      mapReady: false,
    };
  },

  computed: {
    myPosText() {
      if (!this.myPos) return '';
      return this.myPos.lat.toFixed(5) + ', ' + this.myPos.lng.toFixed(5);
    },

    /* 相对方位图：自己在正中心，各建筑按「真实方位 + 真实距离」摆开。
       没配高德 Key 时（has_key=false）整个地图不存在，
       用户定位成功后依然「看不到自己」—— 这张图不依赖任何外部服务。 */
    radar() {
      if (!this.myPos) return null;
      const list = this.destinations.filter(d => d.lat != null && d.lng != null);
      if (!list.length) return null;

      const C = 150, R = 118;
      const maxD = Math.max(1, ...list.map(d => d.distance || 0));
      // 最远的目标放在 0.82R，留出边距给名字标签，别顶到圆边上被裁掉
      const PLOT = R * 0.82;

      const pts = list.map(d => {
        const rr = maxD > 0 ? ((d.distance || 0) / maxD) * PLOT : 0;
        const a = (d.bearing || 0) * Math.PI / 180;   // 0° = 正北 = 屏幕正上方
        const name = String(d.name || '');
        return {
          id: d.id,
          name: name.length > 7 ? name.slice(0, 7) + '…' : name,
          x: C + rr * Math.sin(a),
          y: C - rr * Math.cos(a),
          distText: d.distanceText,
          bearingText: d.bearingText,
          isActive: !!(this.active && this.active.id === d.id),
        };
      });

      // 每个刻度圈对应的真实距离：最远目标在 PLOT 处 = maxD
      const rings = [0.25, 0.5, 0.75, 1].map(f => ({
        r: R * f,
        label: distanceText(maxD * (R * f) / PLOT),
      }));

      return {
        C, R, pts, maxD, rings,
        // 当前目标的方位角，用来在圆心画一根粗箭头
        activeBearing: (this.active && this.active.bearing != null) ? this.active.bearing : null,
        activeName: this.active ? (this.active.name || '') : '',
        activeDist: this.active ? (this.active.distanceText || '') : '',
        activeDir: this.active ? (this.active.bearingText || '') : '',
      };
    },
  },

  async mounted() {
    await this.loadConfig();
    await this.loadDestinations();
    await this.initMap();
    this.locate();               // 自动尝试定位（被拒则提示）
  },

  methods: {
    /* ---------------- 数据加载 ---------------- */
    async loadConfig() {
      try {
        const res = await axios.get('/api/nav/config');
        this.cfg = Object.assign(this.cfg, (res.data && res.data.data) || {});
      } catch (e) { /* 用默认值 */ }
    },

    async loadDestinations() {
      try {
        const res = await axios.get('/api/nav/destinations');
        const d = (res.data && res.data.data) || {};
        this.destinations = (d.destinations || []).map(x => Object.assign({
          distance: null, distanceText: '', bearing: null, bearingText: '',
        }, x));
        this.missingCoords = d.missing_coords || 0;
        if (this.mapReady) this.syncDestMarkers();   // 地图已就绪时补画目标
      } catch (e) {
        this.destinations = [];
      }
    },

    /* ---------------- 定位 ---------------- */
    async locate() {
      this.locError = '';
      this.locWarn = '';
      this.locating = true;
      try {
        const p = await this._readPosition();
        this.myPos = { lat: p.lat, lng: p.lng, accuracy: p.accuracy };
        this.myPosAt = Date.now();
        this.recomputeDistances();
        // 把「我」画到地图上。
        // 旧代码只在 createMap() 里画点，而 initMap() 跑在 locate() 之前，
        // 那时 myPos 还是 null —— 于是定位成功却永远看不到自己。
        this.syncMyMarker();
        this.syncDestMarkers();       // 目标也要跟着重新适配视野
      } catch (e) {
        var msg = this._locateMsg(e);
        // 已经有位置时不要再弹红字：上一次的位置仍在使用中，
        // 只是这一次刷新失败 —— 说清楚就行，别让用户以为定位彻底坏了。
        if (this.myPos) {
          this.locWarn = '本次刷新失败（' + msg + '），仍在显示上一次的位置';
        } else {
          this.locError = msg;
        }
      } finally {
        this.locating = false;
      }
    },

    /* 取一次位置：**先走原生桥，再退回浏览器 API**。

       为什么必须这样：
          App 里跑的是 Android WebView，WebView 自己的 navigator.geolocation
          需要宿主 App 处理 onGeolocationPermissionsShowPrompt 才会给位置，
          Capacitor 默认没接这个回调 —— 所以 WebView 这条路在 App 内必然失败。
          而 native-bridge.js 早就封装好了 Capacitor 的 Geolocation 插件
          （Native.getPosition），App 里是能正常拿到坐标的。
          以前这里直接调浏览器 API，等于放着能用的不用，还回一句
          「系统定位服务不可用」，让人以为手机定位坏了。 */
    async _readPosition() {
      // ① 原生桥（App 内）
      if (window.Native && window.Native.available && window.Native.getPosition) {
        try {
          var p = await window.Native.getPosition();
          if (p && isFinite(p.lat) && isFinite(p.lng)) return p;
        } catch (e) { /* 原生失败就继续试浏览器 API */ }
      }
      // ② 浏览器 API（网页版，或原生不可用时）
      if (!navigator.geolocation) throw { code: 'NO_API' };
      return await new Promise(function (resolve, reject) {
        navigator.geolocation.getCurrentPosition(
          function (c) {
            resolve({ lat: c.coords.latitude, lng: c.coords.longitude, accuracy: c.coords.accuracy });
          },
          function (err) { reject(err || { code: 'UNKNOWN' }); },
          { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
      });
    },

    /* 把各种形状的定位错误翻译成一句人话。

       三种形状都要认：
         · 浏览器标准错误：code 是数字 1 权限 / 2 不可用 / 3 超时
         · Capacitor 插件错误：code 是字符串，如 OS-PLUG-GLOC-0003
         · 完全没给 code 的意外错误
       以前只判了数字 1 和 3，插件那种字符串码会落到 else，
       于是不管什么原因都显示同一句「系统定位服务不可用」，
       既不准也没法排查。现在把原始信息一并带出来。 */
    _locateMsg(e) {
      var code = e && e.code;
      var raw = e && (e.message || e.code) ? String(e.message || e.code) : '';
      var msg;
      if (code === 1 || code === 'PERMISSION_DENIED') {
        msg = '定位权限被拒绝，请在系统设置里允许「智座」使用位置信息';
      } else if (code === 2 || code === 'POSITION_UNAVAILABLE') {
        msg = '系统暂时给不出位置：可能室内信号弱，或系统定位开关被关掉了';
      } else if (code === 3 || code === 'TIMEOUT') {
        msg = '定位超时，请到窗边或空旷处再试';
      } else if (code === 'NO_API') {
        msg = '当前环境不支持定位';
      } else {
        msg = '定位失败';
      }
      return raw ? (msg + '（' + raw + '）') : msg;
    },

    recomputeDistances() {
      if (!this.myPos) return;
      const me = this.myPos;
      this.destinations.forEach(d => {
        const dist = haversine(me.lat, me.lng, d.lat, d.lng);
        const brg = bearing(me.lat, me.lng, d.lat, d.lng);
        d.distance = dist;
        d.distanceText = distanceText(dist);
        d.bearing = brg;
        d.bearingText = compassText(brg);
      });
      this.destinations.sort((a, b) => (a.distance ?? 1e12) - (b.distance ?? 1e12));
      // ★ 定位后自动选中最近的建筑。
      //   以前 active 要用户点「导航」才有值，在那之前大号距离显示 "--"、
      //   罗盘箭头也不指 —— 表现就是「只看见自己，看不见目标，不知道怎么过去」。
      if (!this.active && this.destinations.length) {
        this.active = this.destinations[0];
      }
      if (this.active) {
        const cur = this.destinations.find(x => x.id === this.active.id);
        if (cur) this.active = cur;
        this.updateCompass();
      }
    },

    /* ---------------- 地图（高德 JS API v2） ---------------- */
    initMap() {
      const needMap = this.cfg.fallback_enabled === false || this.cfg.has_key;
      if (!this.cfg.has_key) {
        // 没配 key：直接用兜底，不白屏
        this.navMode = 'fallback';
        this.mapReason = '还没配置高德地图 Key';
        return Promise.resolve();
      }
      return this.loadAmapSdk()
        .then(() => this.createMap())
        .catch(err => {
          console.info('[outdoor] 地图不可用，切换方位导航兜底：', err && err.message);
          this.mapReason = (err && err.message) || '地图加载失败';
          this.navMode = this.cfg.fallback_enabled ? 'fallback' : 'map';
        });
    },

    loadAmapSdk() {
      if (window.AMap) return Promise.resolve();
      // 高德 JS API v2 需要在加载 SDK 之前设置安全密钥
      if (this.cfg.security_code) {
        window._AMapSecurityConfig = { securityJsCode: this.cfg.security_code };
      }
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('地图 SDK 加载超时')), 9000);
        const s = document.createElement('script');
        // ★ 必须显式声明 plugin=AMap.Walking：
        //   高德 JS API v2 把 Walking（步行路径规划）做成按需插件，
        //   不在 URL 里声明就不会加载，后面 new AMap.Walking() 会直接抛
        //   「AMap.Walking is not a constructor」——地图能显示，路线却永远画不出来。
        s.src = 'https://webapi.amap.com/maps?v=2.0&key=' + encodeURIComponent(this.cfg.key)
              + '&plugin=AMap.Walking';
        s.onload = () => { clearTimeout(timer); window.AMap ? resolve() : reject(new Error('SDK 加载异常')); };
        s.onerror = () => { clearTimeout(timer); reject(new Error('地图 SDK 加载失败（检查 Key 与域名白名单）')); };
        document.head.appendChild(s);
      });
    },

    createMap() {
      if (this.map) return;
      this.map = new window.AMap.Map('navMap', { zoom: 16, resizeEnable: true });
      this.mapReady = true;
      this.syncMyMarker();
      this.syncDestMarkers();
    },

    /** 把「我的位置」画到高德地图上（定位晚于建图时也能补画）
        旧代码把画点写死在 createMap() 里，而 initMap() 在 locate() 之前执行，
        myPos 还是 null —— 所以定位成功却永远看不到自己。 */
    syncMyMarker() {
      if (!this.mapReady || !this.map || !this.myPos) return;
      const AMap = window.AMap;
      if (!AMap) return;
      const pos = [this.myPos.lng, this.myPos.lat];
      const acc = Math.max(10, Math.round(this.myPos.accuracy || 30));

      if (!this._meMarker) {
        this._meMarker = new AMap.Marker({
          position: pos, title: '我的位置', zIndex: 200,
          label: { content: '我的位置', direction: 'top' },
        });
        this._meMarker.setMap(this.map);
      } else {
        this._meMarker.setPosition(pos);
      }

      // 精度圈：让用户知道这次定位有多准
      if (!this._meCircle) {
        this._meCircle = new AMap.Circle({
          center: pos, radius: acc, strokeColor: '#34a853', strokeOpacity: .6,
          strokeWeight: 1, fillColor: '#34a853', fillOpacity: .12,
        });
        this._meCircle.setMap(this.map);
      } else {
        this._meCircle.setCenter(pos);
        this._meCircle.setRadius(acc);
      }

      this.map.setCenter(pos);
      if (this.active) this.drawRoute(this.active);
    },

    /** 把所有目标建筑画到地图上。
        以前地图上只有「我」——目标要点「导航」才会出现，
        用户在地图上看不到自己要去的地方。 */
    syncDestMarkers() {
      if (!this.mapReady || !this.map || !window.AMap) return;
      const AMap = window.AMap;
      const list = this.destinations.filter(d => d.lat != null && d.lng != null);
      if (!list.length) return;

      if (!this._destMarkers) this._destMarkers = {};

      list.forEach(d => {
        const pos = [d.lng, d.lat];
        const active = !!(this.active && this.active.id === d.id);
        const label = (active ? '★ ' : '') + (d.name || '') +
                      (d.distanceText ? ' · ' + d.distanceText : '');
        let m = this._destMarkers[d.id];
        if (!m) {
          m = new AMap.Marker({
            position: pos, title: d.name || '目标', zIndex: active ? 180 : 150,
            label: { content: label, direction: 'top' },
          });
          m.setMap(this.map);
          this._destMarkers[d.id] = m;
        } else {
          m.setPosition(pos);
          m.setzIndex(active ? 180 : 150);
          m.setLabel({ content: label, direction: 'top' });
        }
      });

      // 视野同时装下「我」和所有目标，别只顾着自己
      try { this.map.setFitView(null, false, [70, 70, 70, 70]); }
      catch (e) { try { this.map.setFitView(); } catch (e2) { /* 忽略 */ } }
    },

    /* ---------------- 导航 ---------------- */
    navigateTo(d) {
      this.active = d;
      this.updateCompass();
      if (this.navMode === 'map' && this.mapReady) {
        this.syncDestMarkers();       // 高亮当前目标
        this.drawRoute(d);
      }
      // 视图容器可能刚从 v-show 显示出来，触发一次尺寸刷新
      if (this.map) setTimeout(() => this.map.resize(), 60);
    },

    drawRoute(d) {
      if (!this.myPos) {
        showToast('请先获取你的位置', 'error');
        return;
      }
      const AMap = window.AMap;
      const from = [this.myPos.lng, this.myPos.lat];
      const to = [d.lng, d.lat];

      // 插件没加载成功时不抛异常，直接退化成「直线 + 提示」：
      // 真机上宁可少一条路线，也不能因为一个构造函数把整页定位搞崩。
      if (typeof AMap.Walking !== 'function') {
        this.routeInfo = {
          distance: distanceText(d.distance) + '（直线）',
          duration: '—',
        };
        this.mapReason = '步行路线插件未加载，已退化为直线距离';
        return;
      }

      if (!this._route) {
        this._route = new AMap.Walking({ map: this.map, hideMarkers: false });
      }
      this._route.clear();
      this.routeInfo = null;
      this._route.search(from, to, (status, result) => {
        if (status === 'complete' && result.routes && result.routes.length) {
          const r = result.routes[0];
          this.routeInfo = {
            distance: distanceText(r.distance),
            duration: Math.max(1, Math.round(r.time / 60)) + ' 分钟',
          };
        } else {
          // 路线规划失败（配额/网络/跨城等）-> 退化为直线 + 提示，不白屏。
          // 把高德给的原始原因带出来：最常见的两种是没配安全密钥和配额用完，
          // 只报「规划失败」的话，用户根本不知道该去改什么。
          var why = (result && (result.info || result.infocode))
            ? String(result.info || result.infocode) : '';
          if (/INVALID_USER_SCODE/i.test(why)) {
            why = '缺少高德「安全密钥」(securityJsCode)，请管理员到管理后台「系统设置 → 地图与导航」填写';
          } else if (/OVER_LIMIT|QUOTA|DAILY_QUERY/i.test(why)) {
            why = '今日路径规划配额已用完';
          } else if (/USER_KEY|INVALID_USER_KEY/i.test(why)) {
            why = '高德 Key 无效或未开通 Web 服务';
          }
          this.routeInfo = { distance: distanceText(d.distance) + '（直线）',
                             duration: '—' };
          showToast('步行路线规划失败' + (why ? '：' + why : '') + '，已显示直线距离', 'error');
        }
      });
    },

    updateCompass() {
      if (this.navMode !== 'fallback' || !this.active) return;
      const el = document.getElementById('arrow');
      if (el && this.active.bearing != null) {
        el.style.transform = 'translateY(-100%) rotate(' + Math.round(this.active.bearing) + 'deg)';
      }
    },

    /* ---------------- 一键跳手机地图 ---------------- */
    externalUrl(d) {
      // 各平台通用：高德 URI API 优先，失败可长按复制坐标
      const name = encodeURIComponent(d.name || '目的地');
      return 'https://uri.amap.com/marker?position=' + d.lng + ',' + d.lat +
             '&name=' + name + '&src=smartseat&coordinate=gaode&callnative=1';
    },
  },
}).mount('#app');

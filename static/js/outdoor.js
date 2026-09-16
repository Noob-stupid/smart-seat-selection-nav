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
      locating: false,
      locError: '',
      navMode: 'map',              // map | fallback
      active: null,
      routeInfo: null,             // {distance, duration}
      map: null,
      mapReady: false,
    };
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
      } catch (e) {
        this.destinations = [];
      }
    },

    /* ---------------- 定位 ---------------- */
    async locate() {
      this.locError = '';
      if (!navigator.geolocation) {
        this.locError = '该浏览器不支持定位功能';
        return;
      }
      this.locating = true;
      try {
        const c = await new Promise((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject,
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
        });
        this.myPos = { lat: c.coords.latitude, lng: c.coords.longitude,
                       accuracy: c.coords.accuracy };
        this.recomputeDistances();
      } catch (e) {
        this.locError = e.code === 1
          ? '定位被拒绝：请在浏览器里允许本站获取位置（https 或 localhost 下才可用）'
          : e.code === 3 ? '定位超时，请到空旷处重试' : '无法获取位置';
      } finally {
        this.locating = false;
      }
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
        return Promise.resolve();
      }
      return this.loadAmapSdk()
        .then(() => this.createMap())
        .catch(err => {
          console.info('[outdoor] 地图不可用，切换方位导航兜底：', err && err.message);
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
        s.src = 'https://webapi.amap.com/maps?v=2.0&key=' + encodeURIComponent(this.cfg.key);
        s.onload = () => { clearTimeout(timer); window.AMap ? resolve() : reject(new Error('SDK 加载异常')); };
        s.onerror = () => { clearTimeout(timer); reject(new Error('地图 SDK 加载失败（检查 Key 与域名白名单）')); };
        document.head.appendChild(s);
      });
    },

    createMap() {
      if (this.map) return;
      this.map = new window.AMap.Map('navMap', { zoom: 16, resizeEnable: true });
      this.mapReady = true;
      if (this.myPos) {
        this.map.setCenter([this.myPos.lng, this.myPos.lat]);
        new window.AMap.Marker({
          position: [this.myPos.lng, this.myPos.lat],
          title: '我的位置',
        }).setMap(this.map);
      }
    },

    /* ---------------- 导航 ---------------- */
    navigateTo(d) {
      this.active = d;
      this.updateCompass();
      if (this.navMode === 'map' && this.mapReady) {
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
          // 路线规划失败（配额/网络/跨城等）-> 退化为直线 + 提示，不白屏
          this.routeInfo = { distance: distanceText(d.distance) + '（直线）',
                             duration: '—' };
          showToast('步行路线规划失败，已显示直线距离', 'error');
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

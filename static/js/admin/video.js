/* 视频监控页面（管理员）
   ------------------------------------------------------------------
   数据来源：mock 接口 /api/admin/cameras/zones —— 摄像头点位按「选座座位区」派生
   （每个楼层按座位编号前缀分为 A/B/C/D 区，每区 1 路监控，位置在该区正前方）。
   页面结构：概览统计 → 筛选（建筑物/楼层/状态）→ 位置区块网格 → 点击区块弹窗看画面。
   区块内只画「位置」：座位小方块 + 摄像头点位 + 朝向视野扇形，不放视频；
   画面通过 /api/admin/cameras/<id>/snapshot 获取（模拟帧按座位状态实时生成）。
*/
(function () {
  'use strict';

  function uncloak() {
    var a = document.querySelectorAll('[v-cloak]');
    for (var i = 0; i < a.length; i++) a[i].removeAttribute('v-cloak');
  }
  if (typeof Vue === 'undefined') { uncloak(); return; }

  /* 座位状态配色（复用 app.js 的 seatColors，缺失时兜底） */
  var FALLBACK_SEAT_COLORS = {
    free: { bg: '#e6f4ea', color: '#1e7e34' },
    occupied: { bg: '#fce8e6', color: '#d93025' },
    locked: { bg: '#fff3e0', color: '#e37400' },
    error: { bg: '#f1f3f4', color: '#5f6368' },
  };

  try {
    Vue.createApp({
      delimiters: ['${', '}'],
      data: function () {
        return {
          buildings: [],
          floors: [],
          buildingId: '',
          floorId: '',
          statusFilter: '',
          cameras: [],
          summary: {},
          loading: true,
          viewer: null,
          frameLoading: false,
          autoRefresh: true,
          refreshTimer: null,
        };
      },
      computed: {
        filtered: function () {
          var self = this;
          return this.cameras.filter(function (c) {
            return !self.statusFilter || c.status === self.statusFilter;
          });
        },
        abnormal: function () {
          return (this.summary.offline_count || 0) + (this.summary.maintenance_count || 0);
        },
      },
      created: function () {
        this.loadBuildings();
        this.load();
      },
      methods: {
        /* ---------------- 数据 ---------------- */
        loadBuildings: async function () {
          try {
            var res = await api.get('/api/buildings');
            this.buildings = res.data || [];
          } catch (e) { /* 已由 api 层提示 */ }
        },
        onBuildingChange: async function () {
          this.floorId = '';
          this.floors = [];
          if (!this.buildingId) { this.load(); return; }
          try {
            var res = await api.get('/api/buildings/' + this.buildingId);
            this.floors = (res.data && res.data.floors) || [];
          } catch (e) { }
          this.load();
        },
        load: async function (showTip) {
          this.loading = true;
          try {
            var params = {};
            if (this.buildingId) params.building_id = this.buildingId;
            if (this.floorId) params.floor_id = this.floorId;
            var res = await api.get('/api/admin/cameras/zones', params);
            var data = res.data || {};
            this.cameras = data.cameras || [];
            this.summary = data.summary || {};
            if (showTip) showToast('已刷新 ' + this.cameras.length + ' 个摄像头点位');
          } catch (e) {
            this.cameras = [];
          } finally {
            this.loading = false;
          }
        },

        /* ---------------- 区块缩略图 ---------------- */
        blockViewBox: function (c) {
          var xs = c.seats.map(function (s) { return s.x; }).concat([c.x]);
          var ys = c.seats.map(function (s) { return s.y; }).concat([c.y, c.y + Math.min(c.range || 200, 220)]);
          var minX = Math.min.apply(null, xs) - 60;
          var minY = Math.min.apply(null, ys) - 60;
          var maxX = Math.max.apply(null, xs) + 60;
          var maxY = Math.max.apply(null, ys) + 60;
          return Math.round(minX) + ' ' + Math.round(minY) + ' ' + Math.round(maxX - minX) + ' ' + Math.round(maxY - minY);
        },
        seatFill: function (status) {
          var c = (typeof seatColors !== 'undefined' && seatColors[status]) || FALLBACK_SEAT_COLORS[status];
          return c ? c.bg : '#f1f3f4';
        },
        seatStroke: function (status) {
          var c = (typeof seatColors !== 'undefined' && seatColors[status]) || FALLBACK_SEAT_COLORS[status];
          return c ? c.color : '#9aa0a6';
        },

        /* ---------------- 画面查看器 ---------------- */
        openViewer: async function (c) {
          this.viewer = { camera: c, frame: '', taken_at: '', occupied: c.occupied };
          await this.loadFrame();
          this.startAutoRefresh();
        },
        closeViewer: function () {
          this.viewer = null;
          this.clearAutoRefresh();
        },
        loadFrame: async function () {
          if (!this.viewer) return;
          this.frameLoading = true;
          var camId = this.viewer.camera.id;
          try {
            var res = await api.get('/api/admin/cameras/' + camId + '/snapshot');
            var data = res.data || {};
            /* 弹窗可能已被关闭或切换了其它点位 */
            if (!this.viewer || this.viewer.camera.id !== camId) return;
            if (data.frame && data.frame.url) this.viewer.frame = data.frame.url;
            this.viewer.taken_at = this.fmt(data.taken_at);
            this.viewer.occupied = data.occupied;
            var src = this.cameras.filter(function (x) { return x.id === camId; })[0];
            if (src && typeof data.occupied === 'number') src.occupied = data.occupied;
          } catch (e) { /* api 层已提示（如点位离线） */ }
          finally { this.frameLoading = false; }
        },
        startAutoRefresh: function () {
          var self = this;
          this.clearAutoRefresh();
          this.refreshTimer = setInterval(function () {
            if (!self.viewer || !self.autoRefresh || document.hidden) return;
            self.loadFrame();
          }, 5000);
        },
        clearAutoRefresh: function () {
          if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
        },
        //时间
        fmt: function (t) {
          if (!t) return '-';
          var d = new Date(String(t).replace(' ', 'T'));
          if (isNaN(d.getTime())) return String(t);
          var p = function (n) { return n < 10 ? '0' + n : '' + n; };
          return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' +
            p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
        },
      },
      beforeUnmount: function () { this.clearAutoRefresh(); },
    }).mount('#app');
  } catch (e) {
    console.error('[视频监控]', e);
    uncloak();
  }
})();

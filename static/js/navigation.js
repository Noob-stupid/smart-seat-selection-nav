/* 导航页 */
Vue.createApp({
  delimiters: ['${', '}'],
  data() {
    var initScript = document.getElementById('init-data');
    var initData = {};
    if (initScript) { try { initData = JSON.parse(initScript.textContent.trim()); } catch (e) { } }
    return {
      buildings: [], floors: [], allSeats: [],
      buildingId: initData.buildingId || null,
      fromFloorId: initData.floorId || null,
      toFloorId: null,
      locateMode: 'click', destMode: 'seat',
      fromX: 0, fromY: 0, toX: 0, toY: 0,
      qrNodeId: '',
      toSeatId: initData.targetSeatId || null,
      currentPosition: null, routeResult: null, navigating: false,
      // 平面图
      floorPlanUrl: null, floorPlanWidth: 800, floorPlanHeight: 600,
      nearestStartNode: null,
      /* 传感器导航（PDR）推算出来的实时位置，由 native-features.js 广播过来。
         这一层只是「把已经有坐标画到图上」，不动原有定位与寻路逻辑。 */
      pdrPos: null,
    };
  },
  computed: {
    freeSeats: function () {
      if (!this.toFloorId) return [];
      var self = this;
      return this.allSeats.filter(function (s) { return s.floor_id === self.toFloorId; });
    },

    /* ---- 传感器导航叠加层：位置有效才画，没锚定过就什么都不显示 ---- */
    hasPdrPos: function () {
      return !!(this.pdrPos && isFinite(this.pdrPos.x) && isFinite(this.pdrPos.y));
    },
    /* 推算位置到终点的直线距离（米）。比例尺由 PDR 面板给出（默认 20 px/m）。 */
    pdrToTargetM: function () {
      if (!this.hasPdrPos) return null;
      var tx = Number(this.toX), ty = Number(this.toY);
      if (!isFinite(tx) || !isFinite(ty) || (tx === 0 && ty === 0)) return null;
      var ppm = this.pdrPos.pxPerM || 20;
      return Math.sqrt((tx - this.pdrPos.x) * (tx - this.pdrPos.x) +
                       (ty - this.pdrPos.y) * (ty - this.pdrPos.y)) / ppm;
    },
    /* 推算位置偏离规划路径的距离（米）。惯性推算会累积误差，
       超过阈值就说明该重新扫码锚定了 —— 与其硬画一个漂移的点，不如直说。 */
    pdrOffRouteM: function () {
      if (!this.hasPdrPos) return null;
      var path = this.routeResult && this.routeResult.path;
      if (!path || path.length < 2) return null;
      var ppm = this.pdrPos.pxPerM || 20;
      var best = Infinity;
      for (var i = 0; i < path.length - 1; i++) {
        var d = this._pointSegDist(this.pdrPos.x, this.pdrPos.y,
          path[i].x, path[i].y, path[i + 1].x, path[i + 1].y);
        if (d < best) best = d;
      }
      return isFinite(best) ? best / ppm : null;
    },
    pdrOffRoute: function () {
      return this.pdrOffRouteM !== null && this.pdrOffRouteM > 5;
    },
  },
  created: function () { this.loadBuildings(); },
  methods: {
    loadBuildings: async function () {
      try {
        var res = await api.get('/api/buildings');
        this.buildings = res.data || [];
        if (this.buildingId) this.loadFloors();
      } catch (e) { }
    },
    loadFloors: async function () {
      if (!this.buildingId) return;
      try {
        var res = await api.get('/api/buildings/' + this.buildingId);
        this.floors = res.data && res.data.floors ? res.data.floors : [];
        if (this.floors.length) {
          if (!this.fromFloorId) this.fromFloorId = this.floors[0].id;
          if (!this.toFloorId) this.toFloorId = this.floors[0].id;
        }
        await this.loadSeats();
        // 如果从座位图跳转过来，自动匹配目标座位楼层
        if (this.toSeatId) {
          var targetSeat = this.allSeats.find(function (s) { return s.id === this.toSeatId; }.bind(this));
          if (targetSeat) {
            this.toFloorId = targetSeat.floor_id;
            this.toX = targetSeat.x;
            this.toY = targetSeat.y;
          }
        }
        // 加载当前楼层的平面图
        this.loadFloorPlan();
      } catch (e) { }
    },
    loadSeats: async function () {
      if (!this.buildingId) return;
      try { var r = await api.get('/api/seats', { building_id: this.buildingId }); this.allSeats = r.data || []; } catch (e) { }
    },
    loadFloorPlan: function () {
      var floor = this.floors.find(function (f) { return f.id === this.fromFloorId; }.bind(this));
      if (floor && floor.floor_plan_url) {
        this.floorPlanUrl = floor.floor_plan_url;
        this.floorPlanWidth = floor.floor_plan_width || 800;
        this.floorPlanHeight = floor.floor_plan_height || 600;
      } else {
        this.floorPlanUrl = null;
      }
    },
    onSeatSelect: function () {
      var self = this;
      var seat = this.allSeats.find(function (s) { return s.id === self.toSeatId; });
      if (seat) { this.toX = seat.x; this.toY = seat.y; }
    },
    onMapClick: function (e) {
      if (this.locateMode === 'click') {
        var svg = e.currentTarget;
        var rect = svg.getBoundingClientRect();
        var x = Math.round(e.clientX - rect.left);
        var y = Math.round(e.clientY - rect.top);
        this.fromX = x; this.fromY = y;
        this.currentPosition = { x: x, y: y };
        // 查询该位置最近的节点
        this.findNearestNode(x, y);
      }
    },
    findNearestNode: async function (x, y) {
      try {
        var res = await api.post('/api/navigation/locate', {
          type: 'click', floor_id: this.fromFloorId, click_x: x, click_y: y
        });
        if (res.data && res.data.node_id) {
          showToast('已定位到节点 ' + res.data.node_id + ' (' + res.data.x + ',' + res.data.y + ')');
          this.nearestStartNode = res.data;
          // 保存定位节点，供预约页"签到按钮"校验是否在座位附近
          localStorage.setItem('checkin_loc_node', res.data.node_id);
        } else {
          showToast('该位置附近无路网节点，请靠近通道点击', 'warning');
        }
      } catch (e) { }
    },
    planRoute: async function () {
      if (!this.fromFloorId) { showToast('请选择楼层', 'error'); return; }
      if (!this.currentPosition && this.fromX === 0 && this.fromY === 0) {
        showToast('请先在地图上点击设置起点位置', 'error'); return;
      }
      if ((this.toX === 0 && this.toY === 0) && !this.toSeatId) {
        showToast('请设置终点座位或坐标', 'error'); return;
      }
      this.navigating = true;
      try {
        // 先定位起点最近节点
        var locRes = await api.post('/api/navigation/locate', {
          floor_id: this.fromFloorId, click_x: this.fromX, click_y: this.fromY,
        });
        if (!locRes.data || !locRes.data.node_id) {
          showToast('起点附近无路网节点，请靠近通道点击', 'error'); return;
        }
        var fromNode = locRes.data.node_id;

        // 定位终点最近节点
        var toLocRes = await api.post('/api/navigation/locate', {
          floor_id: this.toFloorId || this.fromFloorId,
          click_x: this.toX || 0, click_y: this.toY || 0,
        });
        if (!toLocRes.data || !toLocRes.data.node_id) {
          showToast('终点附近无路网节点', 'error'); return;
        }
        var toNode = toLocRes.data.node_id;

        var res = await api.post('/api/navigation/plan', {
          from_floor_id: this.fromFloorId, to_floor_id: this.toFloorId || this.fromFloorId,
          from_node: fromNode, to_node: toNode,
        });
        if (res.data) {
          if (res.data.error) {
            showToast(res.data.error, 'error');
            this.routeResult = null;
          } else if (res.data.path && res.data.path.length > 0) {
            this.routeResult = res.data;
            // 路网有断点、后端自动补桥时如实说明，别默默替用户掩盖
            if (res.data.bridged && res.data.network_note) {
              showToast('路径规划成功（' + res.data.network_note + '）', 'warning');
            } else {
              showToast('路径规划成功！经过 ' + res.data.path.length + ' 个节点');
            }
          } else {
            this.routeResult = res.data;
            showToast('路网不连通，请检查节点间是否有连线', 'warning');
          }
        }
      } catch (e) {
        console.error('路径规划失败:', e);
      } finally { this.navigating = false; }
    },
    locateByQR: async function () {
      if (!this.qrNodeId) return;
      try {
        var res = await api.post('/api/navigation/locate', { type: 'qr', floor_id: this.fromFloorId, node_id: this.qrNodeId });
        if (res.data) {
          this.currentPosition = res.data; this.fromX = res.data.x; this.fromY = res.data.y; showToast('定位成功');
          // 保存定位节点，供预约页"签到按钮"校验是否在座位附近
          localStorage.setItem('checkin_loc_node', res.data.node_id);
        }
      } catch (e) { }
    },

    /* ---------------- 传感器导航（PDR）叠加 ----------------
       只负责「把 native-features.js 推算出的位置画到平面图上」，
       不参与原有的选点/寻路逻辑。没锚定过就是 null，界面自然什么都不显示。 */
    _onPdrPosition: function (e) {
      this.pdrPos = (e && e.detail) ? e.detail : null;
    },
    /* 点到线段的距离：用来判断推算位置偏离规划路径有多远 */
    _pointSegDist: function (px, py, x1, y1, x2, y2) {
      var dx = x2 - x1, dy = y2 - y1;
      var len2 = dx * dx + dy * dy;
      if (len2 === 0) return Math.sqrt((px - x1) * (px - x1) + (py - y1) * (py - y1));
      var t = ((px - x1) * dx + (py - y1) * dy) / len2;
      t = Math.max(0, Math.min(1, t));
      var cx = x1 + t * dx, cy = y1 + t * dy;
      return Math.sqrt((px - cx) * (px - cx) + (py - cy) * (py - cy));
    },
  },
  mounted: function () {
    // 传感器导航模块（native-features.js）通过事件广播推算位置
    this._pdrHandler = this._onPdrPosition.bind(this);
    window.addEventListener('pdr:position', this._pdrHandler);
  },
  unmounted: function () {
    if (this._pdrHandler) window.removeEventListener('pdr:position', this._pdrHandler);
  },
  watch: {
    buildingId: function () { this.loadFloors(); },
    fromFloorId: function () { this.loadFloorPlan(); },
    toFloorId: function (newVal) {
      this.loadFloorPlan();
      // 如果当前选中的座位不在新楼层，清空
      if (this.toSeatId) {
        var seat = this.allSeats.find(function (s) { return s.id === this.toSeatId; }.bind(this));
        if (seat && seat.floor_id !== newVal) { this.toSeatId = null; this.toX = 0; this.toY = 0; }
      }
    },
  },
}).mount('#app');

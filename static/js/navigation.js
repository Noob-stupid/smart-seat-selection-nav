/* 导航页 */
function floorPlanPlaceholderUrl() {
  var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">' +
    '<defs>' +
    '<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">' +
    '<path d="M40 0H0V40" fill="none" stroke="#f0f1f3" stroke-width="1"/>' +
    '</pattern>' +
    '</defs>' +
    '<rect width="800" height="600" fill="#f8f9fa"/>' +
    '<rect x="30" y="30" width="740" height="540" fill="url(#grid)" stroke="#dadce0" stroke-width="1.5"/>' +
    '</svg>';
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

Vue.createApp({
  delimiters: ['${', '}'],
  data() {
    var initScript = document.getElementById('init-data');
    var initData = {};
    if (initScript) { try { initData = JSON.parse(initScript.textContent.trim()); } catch (e) { } }
    try {
      var queryParams = new URLSearchParams(location.search);
      if (queryParams.has('building_id')) initData.buildingId = Number(queryParams.get('building_id'));
      if (queryParams.has('floor_id')) initData.floorId = Number(queryParams.get('floor_id'));
      if (queryParams.has('seat_id')) initData.targetSeatId = Number(queryParams.get('seat_id'));
    } catch (e) {}
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
      mapFloorId: null,
    };
  },
  computed: {
    freeSeats: function () {
      if (!this.toFloorId) return [];
      var self = this;
      return this.allSeats.filter(function (s) { return s.floor_id === self.toFloorId; });
    },
    mapSeats: function () {
      if (!this.mapFloorId) return [];
      var self = this;
      return this.allSeats.filter(function (s) { return s.floor_id === self.mapFloorId; });
    },
  },
  created: function () { this.loadBuildings(); },
  methods: {
    loadBuildings: async function () {
      try {
        var res = await api.get('/api/buildings');
        this.buildings = res.data || [];
        if (this.buildingId) {
          this.loadFloors();
        } else if (this.buildings.length) {
          // 无指定建筑时自动选中第一栋，便于直接显示地图
          this.buildingId = this.buildings[0].id;
          this.loadFloors();
        }
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
          if (!this.mapFloorId || !this.floors.some(function (f) { return f.id === this.mapFloorId; }.bind(this))) {
            this.mapFloorId = this.fromFloorId;
          }
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
      try {
        var r = await api.get('/api/seats');
        var self = this;
        this.allSeats = (r.data || []).filter(function (s) { return s.building_id === self.buildingId; });
      } catch (e) { }
    },
    loadFloorPlan: function () {
      var fid = this.mapFloorId || this.fromFloorId;
      var floor = this.floors.find(function (f) { return f.id === fid; }.bind(this));
      if (floor && floor.floor_plan_url) {
        this.floorPlanUrl = floor.floor_plan_url;
        this.floorPlanWidth = floor.floor_plan_width || 800;
        this.floorPlanHeight = floor.floor_plan_height || 600;
      } else {
        // 未上传平面图时显示演示用地图，保证地图区始终可见
        this.floorPlanUrl = floorPlanPlaceholderUrl();
        this.floorPlanWidth = 800;
        this.floorPlanHeight = 600;
      }
    },
    onSeatSelect: function () {
      var self = this;
      var seat = this.allSeats.find(function (s) { return s.id === self.toSeatId; });
      if (seat) { this.toX = seat.x; this.toY = seat.y; }
    },
    onMapSeatClick: function (seat) {
      this.toSeatId = seat.id;
      this.toX = seat.x;
      this.toY = seat.y;
      this.destMode = 'seat';
      if (seat.floor_id !== this.toFloorId) this.toFloorId = seat.floor_id;
      if (seat.floor_id !== this.mapFloorId) this.mapFloorId = seat.floor_id;
      showToast('已选择座位 ' + seat.seat_label + ' 作为终点');
    },
    planRoute: async function () {
      if (!this.fromFloorId) { showToast('请选择楼层', 'error'); return; }
      if (!this.currentPosition && this.fromX === 0 && this.fromY === 0) {
        showToast('请先设置起点坐标', 'error'); return;
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
          showToast('起点附近无路网节点，请调整起点坐标', 'error'); return;
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
          var route = res.data;
          // 后端跨层返回 segments，单层返回 distance；统一成前端可绘制的 path 与 total_distance
          if (!route.path && route.segments) {
            route.path = [];
            route.segments.forEach(function (seg) {
              (seg.path || []).forEach(function (n) { route.path.push(n); });
            });
          }
          if (route.total_distance === undefined && route.distance !== undefined) {
            route.total_distance = route.distance;
          }
          if (route.error) {
            showToast(route.error, 'error');
            this.routeResult = null;
          } else if (route.path && route.path.length > 0) {
            this.routeResult = route;
            showToast('路径规划成功！经过 ' + route.path.length + ' 个节点');
          } else {
            this.routeResult = route;
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
        if (res.data) { this.currentPosition = res.data; this.fromX = res.data.x; this.fromY = res.data.y; showToast('定位成功'); }
      } catch (e) { }
    },
  },
  watch: {
    buildingId: function () { this.loadFloors(); },
    fromFloorId: function () {
      this.mapFloorId = this.fromFloorId;
      this.loadFloorPlan();
    },
    toFloorId: function (newVal) {
      this.mapFloorId = newVal;
      this.loadFloorPlan();
      // 如果当前选中的座位不在新楼层，清空
      if (this.toSeatId) {
        var seat = this.allSeats.find(function (s) { return s.id === this.toSeatId; }.bind(this));
        if (seat && seat.floor_id !== newVal) { this.toSeatId = null; this.toX = 0; this.toY = 0; }
      }
    },
  },
}).mount('#app');

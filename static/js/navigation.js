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
    };
  },
  computed: {
    freeSeats: function () {
      if (!this.toFloorId) return [];
      var self = this;
      return this.allSeats.filter(function (s) { return s.floor_id === self.toFloorId; });
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
            showToast('路径规划成功！经过 ' + res.data.path.length + ' 个节点');
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
        if (res.data) { this.currentPosition = res.data; this.fromX = res.data.x; this.fromY = res.data.y; showToast('定位成功'); }
      } catch (e) { }
    },
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

/* 导航页 */
Vue.createApp({
  delimiters: ['${', '}'],
  data() {
    var initScript = document.getElementById('init-data');
    var initData = {};
    if (initScript) { try { initData = JSON.parse(initScript.textContent.trim()); } catch (e) { } }
    return {
      buildings: [], floors: [],
      buildingId: initData.buildingId || null,
      fromFloorId: initData.floorId || null,
      toFloorId: null,
      locateMode: 'click', destMode: 'seat',
      fromX: 0, fromY: 0, toX: 0, toY: 0,
      qrNodeId: '',
      toSeatId: initData.targetSeatId || null,
      currentPosition: null, routeResult: null, navigating: false,
    };
  },
  created: function () { this.loadBuildings(); },
  methods: {
    loadBuildings: async function () {
      try { var res = await api.get('/api/buildings'); this.buildings = res.data || []; if (this.buildingId) this.loadFloors(); } catch (e) { }
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
      } catch (e) { }
    },
    onMapClick: function (e) {
      if (this.locateMode !== 'click') return;
      var rect = e.currentTarget.getBoundingClientRect();
      this.fromX = Math.round(e.clientX - rect.left);
      this.fromY = Math.round(e.clientY - rect.top);
      this.currentPosition = { x: this.fromX, y: this.fromY };
      showToast('起点 (' + this.fromX + ', ' + this.fromY + ')');
    },
    planRoute: async function () {
      if (!this.fromFloorId) { showToast('请选择楼层', 'error'); return; }
      this.navigating = true;
      try {
        var res = await api.post('/api/navigation/plan', {
          from_floor_id: this.fromFloorId, to_floor_id: this.toFloorId || this.fromFloorId,
          from_x: this.fromX, from_y: this.fromY, to_x: this.toX, to_y: this.toY,
        });
        if (res.data) { this.routeResult = res.data; showToast('路径规划成功'); }
      } catch (e) { } finally { this.navigating = false; }
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
  },
}).mount('#app');

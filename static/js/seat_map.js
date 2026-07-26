/* 座位图 - 直接 mount（无 IIFE），确保可靠 */
var initScript = document.getElementById('init-data');
var initData = {};
if (initScript) {
  try { initData = JSON.parse(initScript.textContent.trim()); } catch (e) { }
}

Vue.createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      phase: 'loading',
      errorMsg: '',
      buildings: [], floors: [], seats: [],
      buildingId: initData.buildingId || null,
      floorId: initData.floorId || null,
      filterStatus: '',
      stats: { free: 0, occupied: 0, locked: 0, error: 0 },
      lastUpdate: '',
      selectedSeat: null,
      showDetail: false,
      seatColors: seatColors,
    };
  },
  computed: {
    filteredSeats: function () {
      if (!this.filterStatus) return this.seats;
      var self = this;
      return this.seats.filter(function (s) { return s.status === self.filterStatus; });
    },
  },
  created: function () {
    this.loadBuildings();
  },
  methods: {
    seatTypeLabel: function (type) { return seatTypeLabel(type); },
    loadBuildings: async function () {
      this.phase = 'loading';
      try {
        var res = await api.get('/api/buildings');
        this.buildings = res.data || [];
        if (!this.buildings.length) { this.phase = 'empty'; this.errorMsg = '暂未配置场所，请联系管理员添加'; return; }
        if (this.buildingId) { this.floors = []; this.floorId = null; this.onBuildingChange(); return; }
        this.phase = 'select-bld';
      } catch (e) { this.phase = 'error'; this.errorMsg = '加载失败，请检查网络'; }
    },
    onBuildingChange: async function () {
      this.floors = []; this.seats = []; this.phase = 'loading';
      if (!this.buildingId) { this.phase = 'select-bld'; return; }
      try {
        var res = await api.get('/api/buildings/' + this.buildingId);
        this.floors = res.data && res.data.floors ? res.data.floors : [];
        if (!this.floors.length) { this.phase = 'empty'; this.errorMsg = '该场所暂未配置楼层'; return; }
        if (!this.floorId) this.floorId = this.floors[0].id;
        this.loadSeats();
      } catch (e) { this.phase = 'error'; this.errorMsg = '加载楼层失败'; }
    },
    loadSeats: async function () {
      if (!this.floorId) { this.phase = 'select-floor'; return; }
      this.phase = 'loading';
      try {
        var params = { floor_id: this.floorId };
        if (this.filterStatus) params.status = this.filterStatus;
        var res = await api.get('/api/seats', params);
        this.seats = res.data || [];
        this.phase = this.seats.length ? 'ready' : 'empty';
        if (!this.seats.length) this.errorMsg = '该楼层暂未配置座位，请管理员上传平面图标注座位';
        this.updateStats();
        this.lastUpdate = new Date().toLocaleTimeString();
      } catch (e) { this.phase = 'error'; this.errorMsg = '加载座位失败'; }
    },
    updateStats: function () {
      var s = { free: 0, occupied: 0, locked: 0, error: 0 };
      var self = this;
      this.seats.forEach(function (seat) { if (s[seat.status] !== undefined) s[seat.status]++; });
      this.stats = s;
    },
    onSeatClick: function (seat) { this.selectedSeat = seat; this.showDetail = true; },
    reserveSeat: async function (seat) {
      try {
        await api.post('/api/reservations', {
          user_id: 1, seat_id: seat.id,
          start_time: new Date().toISOString(),
          end_time: new Date(Date.now() + 7200000).toISOString()
        });
        showToast('预约成功');
        this.showDetail = false;
        this.loadSeats();
      } catch (e) { }
    },
    goHome: function () { location.href = '/'; },
  },
}).mount('#app');

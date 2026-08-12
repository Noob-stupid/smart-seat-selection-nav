/* 座位图 - 直接 mount（无 IIFE），确保可靠 */
var initScript = document.getElementById('init-data');
var initData = {};
if (initScript) {
  try { initData = JSON.parse(initScript.textContent.trim()); } catch (e) { }
}

try {
  var queryParams = new URLSearchParams(location.search);
  if (queryParams.has('building_id')) initData.buildingId = Number(queryParams.get('building_id'));
  if (queryParams.has('floor_id')) initData.floorId = Number(queryParams.get('floor_id'));
} catch (e) {}

Vue.createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      phase: 'loading',
      errorMsg: '',
      buildings: [], floors: [], seats: [],
      buildingId: initData.buildingId || null,
      floorId: initData.floorId || null,
      lastUpdate: '',
      reservations: [],
      selectedSeat: null,
      showDetail: false,
      timeSlots: [],
      selectedSlot: null,
      seatColors: seatColors,
    };
  },
  computed: {
    timeStatus: function () {
      return this.seatStatusAt(this.selectedSeat, this.selectedSlot);
    },
    timeStatusText: function () {
      var map = { free: '该时段空闲，可预约', occupied: '该时段占用', locked: '该时段已被预约', error: '座位异常' };
      return map[this.timeStatus] || '';
    },
  },
  created: function () {
    this.loadBuildings();
    this.loadReservations();
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
        var res = await api.get('/api/seats', { floor_id: this.floorId });
        this.seats = res.data || [];
        this.phase = this.seats.length ? 'ready' : 'empty';
        if (!this.seats.length) this.errorMsg = '该楼层暂未配置座位，请管理员上传平面图标注座位';
        this.lastUpdate = new Date().toLocaleTimeString();
      } catch (e) { this.phase = 'error'; this.errorMsg = '加载座位失败'; }
    },
    loadReservations: function () {
      var self = this;
      api.get('/api/reservations').then(function (res) { self.reservations = res.data || []; }).catch(function () { });
    },
    seatStatusAt: function (seat, slot) {
      if (!seat || !slot) return '';
      if (seat.status === 'error') return 'error';
      var start = slot.start.getTime();
      var end = slot.end.getTime();
      var conflict = this.reservations.find(function (r) {
        if (r.seat_id !== seat.id || r.status === 'cancelled') return false;
        var rs = new Date(r.start_time).getTime();
        var re = new Date(r.end_time).getTime();
        return start < re && end > rs;
      });
      return conflict ? (conflict.status === 'pending' ? 'locked' : 'occupied') : 'free';
    },
    slotStatusAt: function (slot) {
      return this.seatStatusAt(this.selectedSeat, slot);
    },
    onSeatClick: function (seat) {
      this.selectedSeat = seat;
      this.buildTimeSlots();
      this.showDetail = true;
    },
    buildTimeSlots: function () {
      var slots = [];
      var now = new Date();
      var base = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      var d;
      for (d = 0; d < 2; d++) {
        var dayStart = new Date(base.getTime() + d * 86400000);
        var dayName = d === 0 ? '今天' : '明天';
        var h;
        for (h = 8; h <= 21; h++) {
          var start = new Date(dayStart.getTime() + h * 3600000);
          var end = new Date(start.getTime() + 3600000);
          slots.push({
            label: dayName + ' ' + pad(h) + ':00 - ' + pad(h + 1) + ':00',
            start: start,
            end: end,
            available: end.getTime() > now.getTime()
          });
        }
      }
      this.timeSlots = slots;
      this.selectedSlot = null;
      function pad(n) { return n < 10 ? '0' + n : '' + n; }
    },
    reserveSeat: async function (seat) {
      if (!this.selectedSlot) { showToast('请先选择时间段', 'error'); return; }
      try {
        await api.post('/api/reservations', {
          seat_id: seat.id,
          start_time: this.selectedSlot.start.toISOString(),
          end_time: this.selectedSlot.end.toISOString()
        });
        showToast('预约成功');
        this.showDetail = false;
        this.loadSeats();
        this.loadReservations();
      } catch (e) { }
    },
    goHome: function () { location.href = '/'; },
  },
}).mount('#app');

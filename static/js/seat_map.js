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
      filterStatus: '',
      searchQuery: '',
      isAdmin: initData.isAdmin || false,
      stats: { free: 0, occupied: 0, locked: 0, error: 0, inactive: 0 },
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
    filteredSeats: function () {
      var self = this;
      var q = (this.searchQuery || '').trim().toLowerCase();
      return this.seats.filter(function (s) {
        // 普通用户看不到已关闭座位
        if (!self.isAdmin && s.is_active === false) return false;
        // 搜索座位编号
        if (q && String(s.seat_label || '').toLowerCase().indexOf(q) < 0) return false;
        // 状态筛选
        if (self.filterStatus === 'inactive') return s.is_active === false;
        if (self.filterStatus) return s.is_active !== false && s.status === self.filterStatus;
        return true;
      });
    },
    // 是否所有开放座位的红外都已关闭（用于总开关按钮文案）
    allIrDisabled: function () {
      var open = this.seats.filter(function (s) { return s.is_active !== false; });
      return open.length > 0 && open.every(function (s) { return s.ir_enabled === false; });
    },
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
        var params = { floor_id: this.floorId };
        // 管理员可查看全部座位（含已关闭）
        if (this.isAdmin) params.include_inactive = 1;
        if (this.filterStatus) params.status = this.filterStatus;
        var res = await api.get('/api/seats', params);
        this.seats = res.data || [];
        this.updateStats();
        this.phase = this.seats.length ? 'ready' : 'empty';
        if (!this.seats.length) this.errorMsg = '该楼层暂未配置座位，请管理员上传平面图标注座位';
        this.lastUpdate = new Date().toLocaleTimeString();
      } catch (e) { this.phase = 'error'; this.errorMsg = '加载座位失败'; }
    },
    updateStats: function () {
      var s = { free: 0, occupied: 0, locked: 0, error: 0, inactive: 0 };
      var self = this;
      this.seats.forEach(function (seat) {
        if (seat.is_active === false) { s.inactive++; return; }
        if (s[seat.status] !== undefined) s[seat.status]++;
      });
      this.stats = s;
    },
    // 管理员：关闭 / 开放座位
    toggleSeatActive: async function (seat) {
      if (!seat) return;
      var isClosing = seat.is_active !== false;
      var msg = isClosing
        ? `确定关闭座位 ${seat.seat_label}？关闭后用户将无法查看和预约该座位。`
        : `确定开放座位 ${seat.seat_label}？`;
      if (!confirm(msg)) return;
      try {
        await api.put('/api/seats/' + seat.id, { is_active: !isClosing });
        showToast(isClosing ? '座位已关闭' : '座位已开放');
        this.showDetail = false;
        this.loadSeats();
      } catch (e) { }
    },
    // 管理员：标记异常 / 恢复正常
    toggleSeatError: async function (seat) {
      if (!seat) return;
      var isError = seat.status === 'error';
      var msg = isError
        ? `确定恢复座位 ${seat.seat_label} 为正常？`
        : `确定将座位 ${seat.seat_label} 标记为异常？（异常座位不可预约）`;
      if (!confirm(msg)) return;
      try {
        await api.put('/api/seats/' + seat.id, { status: isError ? 'free' : 'error' });
        showToast(isError ? '座位已恢复正常' : '座位已标记异常');
        this.showDetail = false;
        this.loadSeats();
      } catch (e) { }
    },
    // 管理员：关闭 / 开启红外传感器
    toggleSeatIr: async function (seat) {
      if (!seat) return;
      var isOn = seat.ir_enabled !== false;
      var msg = isOn
        ? `确定关闭座位 ${seat.seat_label} 的红外传感器？关闭后该座位不再接收传感器检测。`
        : `确定开启座位 ${seat.seat_label} 的红外传感器？`;
      if (!confirm(msg)) return;
      try {
        await api.put('/api/seats/' + seat.id, { ir_enabled: !isOn });
        showToast(isOn ? '红外已关闭' : '红外已开启');
        this.showDetail = false;
        this.loadSeats();
      } catch (e) { }
    },
    // 管理员：红外总开关（一键关闭/开启所有开放座位的红外）
    toggleAllIr: async function () {
      var disable = !this.allIrDisabled;
      var msg = disable
        ? '确定关闭所有开放座位的红外传感器？关闭后所有座位不再接收传感器检测。'
        : '确定开启所有座位的红外传感器？';
      if (!confirm(msg)) return;
      try {
        await api.put('/api/admin/seats/ir', { ir_enabled: !disable });
        showToast(disable ? '已关闭全部红外' : '已开启全部红外');
        this.loadSeats();
      } catch (e) { }
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
            // 已开始（开始时间已过）的时段不可预约，自动置灰
            available: start.getTime() > now.getTime()
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

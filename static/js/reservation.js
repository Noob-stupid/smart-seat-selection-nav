/* 预约页 Vue 应用 */
(function () {
  if (typeof Vue === 'undefined') { var a = document.querySelectorAll('[v-cloak]'); for (var i = 0; i < a.length; i++)a[i].removeAttribute('v-cloak'); return }
  try {
    Vue.createApp({
      delimiters: ['${', '}'], data: function () {
        return { phase: 'loading', errorMsg: '', buildings: [], floors: [], seats: [], recommendations: [], buildingId: null, floorId: null, duration: 2, pick: null, submitting: false, reservations: [], now: new Date }
      }, computed: { end: function () { return new Date(this.now.getTime() + this.duration * 3600000) } },
      created: function () { this.init() },
      methods: {
        fmt: function (t) { if (!t) return ''; var d = new Date(t); if (isNaN(d.getTime())) return ''; return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); function p(n) { return n < 10 ? '0' + n : '' + n } },
        init: function () { this.now = new Date(); this.loadBuildings(); this.loadReservations() },
        loadBuildings: function () {
          var self = this; self.phase = 'loading';
          api.get('/api/buildings').then(function (res) {
            self.buildings = res.data || [];
            if (!self.buildings.length) { self.phase = 'empty'; self.errorMsg = '暂未配置场所，请联系管理员添加' }
            else self.phase = 'select'
          }).catch(function () { self.phase = 'error'; self.errorMsg = '加载失败，请检查网络' })
        },
        pickBuilding: function (b) { this.buildingId = b.id; this.loadFloors() },
        loadFloors: function () {
          if (!this.buildingId) { this.phase = 'select'; return }
          var self = this; self.phase = 'loading';
          api.get('/api/buildings/' + this.buildingId).then(function (res) {
            self.floors = res.data && res.data.floors ? res.data.floors : [];
            if (!self.floors.length) { self.phase = 'empty'; self.errorMsg = '该场所暂未配置楼层，请联系管理员'; return }
            if (!self.floorId) self.floorId = self.floors[0].id;
            self.loadSeats()
          }).catch(function () { self.phase = 'error'; self.errorMsg = '加载失败，请检查网络' })
        },
        loadSeats: function () {
          if (!this.floorId) { this.phase = 'select'; return }
          var self = this; self.phase = 'loading';
          api.get('/api/seats', { floor_id: this.floorId }).then(function (res) {
            var all = res.data || [];
            self.seats = all.filter(function (s) { return s.status === 'free' });
            if (!self.seats.length) { self.phase = 'nofree'; return }
            self.phase = 'ready';
            api.get('/api/recommend', { building_id: self.buildingId, floor_id: self.floorId, top_k: 5 }).then(function (r) { self.recommendations = r.data || [] }).catch(function () { })
          }).catch(function () { self.phase = 'error'; self.errorMsg = '加载失败，请检查网络' })
        },
        preview: function (s) { this.pick = s },
        submit: function () {
          if (!this.pick) return; this.submitting = true; var self = this;
          api.post('/api/reservations', { seat_id: this.pick.id, start_time: this.now.toISOString(), end_time: this.end.toISOString() }).then(function () {
            showToast('预约成功'); self.pick = null; self.loadSeats(); self.loadReservations()
          }).catch(function () { }).finally(function () { self.submitting = false })
        },
        loadReservations: function () {
          var self = this;
          api.get('/api/reservations').then(function (res) { self.reservations = res.data || [] }).catch(function () { })
        },
        cancel: function (id) {
          if (!confirm('确定取消？')) return; var self = this;
          api.post('/api/reservations/' + id + '/cancel').then(function () { showToast('已取消'); self.loadReservations(); self.loadSeats() }).catch(function () { })
        }
      }
    }).mount('#app')
  } catch (e) { console.error('[预约]', e); var a = document.querySelectorAll('[v-cloak]'); for (var i = 0; i < a.length; i++)a[i].removeAttribute('v-cloak') }
})()

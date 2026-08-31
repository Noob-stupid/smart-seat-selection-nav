/* 我的预约 Vue 应用 */
(function () {
  if (typeof Vue === 'undefined') { var a = document.querySelectorAll('[v-cloak]'); for (var i = 0; i < a.length; i++)a[i].removeAttribute('v-cloak'); return }
  try {
    Vue.createApp({
      delimiters: ['${', '}'],
      data: function () { return { reservations: [] } },
      created: function () { this.loadReservations() },
      methods: {
        fmt: function (t) {
          if (!t) return '';
          var d = new Date(t);
          if (isNaN(d.getTime())) return '';
          return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
          function p(n) { return n < 10 ? '0' + n : '' + n }
        },
        loadReservations: function () {
          var self = this;
          api.get('/api/reservations').then(function (res) { self.reservations = res.data || [] }).catch(function () { })
        },
        cancel: function (id) {
          if (!confirm('确定取消？')) return;
          var self = this;
          api.post('/api/reservations/' + id + '/cancel').then(function () { showToast('已取消'); self.loadReservations() }).catch(function () { })
        }
      }
    }).mount('#app')
  } catch (e) { console.error('[我的预约]', e); var a = document.querySelectorAll('[v-cloak]'); for (var i = 0; i < a.length; i++)a[i].removeAttribute('v-cloak') }
})()

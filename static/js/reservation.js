/* 我的预约 Vue 应用
   ==================================================================
   ★ 本文件只负责「我的预约」列表。
     选座入口在「座位图」页，不在这里 —— 所以不实现 building / floors /
     freeSeats / targetSeat / doReserve。模板里那块「选座预约」是
     <div class="card" v-if="building"> 包着的，building 未设置 => 永不渲染。

   为什么需要下面这几个小方法：
     模板 reservation.html 的「我的预约」卡引用了
       qrOf / openQr / timeRange / statusText / statusClass / checkin / qrModal
     它们原本缺失，Vue 渲染到 <template v-if="reservations.length"> 里的
     timeRange(r) 时就抛错，整页空白（只剩导航栏）。
     只要列表里有任意一条预约，原版就会白屏 —— 这里补齐，页面才正常。
   ================================================================== */
(function () {
  if (typeof Vue === 'undefined') { var a = document.querySelectorAll('[v-cloak]'); for (var i = 0; i < a.length; i++)a[i].removeAttribute('v-cloak'); return }

  var STATUS_TEXT = {
    pending: '待签到', checked_in: '已签到', completed: '已完成',
    cancelled: '已取消', no_show: '未签到'
  };
  var STATUS_CLASS = {
    pending: 'tag-locked', checked_in: 'tag-free', completed: 'tag-free',
    cancelled: 'tag-error', no_show: 'tag-occupied'
  };

  try {
    Vue.createApp({
      delimiters: ['${', '}'],
      data: function () { return { reservations: [], qrModal: null } },
      created: function () { this.loadReservations() },
      methods: {
        fmt: function (t) {
          if (!t) return '';
          var d = new Date(t);
          if (isNaN(d.getTime())) return '';
          return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
          function p(n) { return n < 10 ? '0' + n : '' + n }
        },

        /** 时间段文案：2026-09-17 11:00 ~ 12:00 */
        timeRange: function (r) {
          if (!r) return '';
          var a = this.fmt(r.start_time), b = this.fmt(r.end_time);
          if (a && b) return a + ' ~ ' + b.slice(-5);
          return a || b || '';
        },

        statusText: function (s) { return STATUS_TEXT[s] || s || '' },
        statusClass: function (s) { return STATUS_CLASS[s] || 'tag-error' },

        /** 预约二维码（纯前端生成的演示图形，不走网络） */
        qrOf: function (r) {
          if (!r) return '';
          var text = r.qr_token || ('RESV:' + r.id);
          return typeof window.demoQRCode === 'function' ? window.demoQRCode(text, 240) : '';
        },
        openQr: function (r) { this.qrModal = this.qrOf(r) },

        /** 列表里的「签到」按钮：复用 checkin.js 的全局实现 */
        checkin: function (r) {
          if (r && typeof window.doCheckin === 'function') window.doCheckin(r.id);
        },

        loadReservations: function () {
          var self = this;
          api.get('/api/reservations').then(function (res) {
            self.reservations = (res.data || []).map(function (r) {
              return Object.assign({}, r, { status_text: STATUS_TEXT[r.status] || r.status });
            });
          }).catch(function () { })
        },

        cancel: function (id) {
          if (!confirm('确定取消？')) return;
          var self = this;
          api.post('/api/reservations/' + id + '/cancel').then(function () { showToast('已取消'); self.loadReservations() }).catch(function () { })
        }
      }
    }).mount('#app')
  } catch (e) {
    console.error('[我的预约]', e);
    var a = document.querySelectorAll('[v-cloak]'); for (var i = 0; i < a.length; i++)a[i].removeAttribute('v-cloak');
  }
})()

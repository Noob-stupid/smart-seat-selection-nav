/* 座位二维码打印（纯静态版）
   ------------------------------------------------------------------
   原页面由 Flask 服务端渲染 groups（建筑物 → 楼层 → 座位），二维码图片来自
   后端接口 /api/seats/<id>/qrcode。静态化后改为：拉取建筑物 → 楼层 → 座位，
   在前端按 建筑物·楼层 分组渲染，二维码用 qr-placeholder.js 生成示意图形。
*/
(function () {
  'use strict';

  function uncloak() {
    var a = document.querySelectorAll('[v-cloak]');
    for (var i = 0; i < a.length; i++) a[i].removeAttribute('v-cloak');
  }
  if (typeof Vue === 'undefined') { uncloak(); return; }

  try {
    Vue.createApp({
      delimiters: ['${', '}'],
      data: function () {
        return { groups: [], loading: true };
      },
      created: function () { this.load(); },
      methods: {
        load: async function () {
          this.loading = true;
          try {
            var res = await api.get('/api/buildings');
            var buildings = res.data || [];
            var groups = [];
            for (var i = 0; i < buildings.length; i++) {
              var b = buildings[i];
              var detail = await api.get('/api/buildings/' + b.id);
              var floors = (detail.data && detail.data.floors) || [];
              for (var j = 0; j < floors.length; j++) {
                var f = floors[j];
                var seatRes = await api.get('/api/seats', { floor_id: f.id });
                var seats = seatRes.data || [];
                if (!seats.length) continue;
                groups.push({
                  key: b.id + '-' + f.id,
                  building: b.name,
                  floor: f.name || ('F' + f.floor_number),
                  seats: seats,
                });
              }
            }
            this.groups = groups;
          } catch (e) {
            console.error('[座位二维码] 加载失败', e);
          } finally {
            this.loading = false;
          }
        },
        qr: function (seat) {
          // ★ 用后端生成的真二维码（内容 SEAT:<id>，符合 ISO/IEC 18004，扫得出来）。
          //   以前这里调前端占位图生成器，画出来「看起来像二维码」但实际读不出来，
          //   是静态化改造时留下的 —— 连带「扫码占座」「扫码绑座位」「PDR 扫码锚定」
          //   三个功能全废。后端接口 /api/seats/<id>/qrcode 一直是好的，只是没人调。
          return '/api/seats/' + seat.id + '/qrcode';
        },
      },
    }).mount('#app');
  } catch (e) {
    console.error('[座位二维码]', e);
    uncloak();
  }
})();

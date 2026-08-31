/* ============================================================
   智能选座与导航系统 - 全局工具库 (v2 - 可靠版)
   ============================================================ */

// Toast 通知
function showToast(message, type) {
  type = type || 'success';
  var el = document.getElementById('toast-container');
  if (!el) return;
  var t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.textContent = message;
  el.appendChild(t);
  setTimeout(function () { t.remove(); }, 3000);
}

// API 请求工具
var api = {
  baseURL: '',
  get: async function (url, params) {
    try {
      var res = await axios.get(url, { params: params });
      return res.data;
    } catch (err) {
      var msg = (err.response && err.response.data && err.response.data.message) || err.message;
      showToast(msg, 'error');
      throw err;
    }
  },
  post: async function (url, data) {
    try {
      var res = await axios.post(url, data);
      return res.data;
    } catch (err) {
      var msg = (err.response && err.response.data && err.response.data.message) || err.message;
      showToast(msg, 'error');
      throw err;
    }
  },
  put: async function (url, data) {
    try {
      var res = await axios.put(url, data);
      return res.data;
    } catch (err) {
      var msg = (err.response && err.response.data && err.response.data.message) || err.message;
      showToast(msg, 'error');
      throw err;
    }
  },
  del: async function (url) {
    try {
      var res = await axios.delete(url);
      return res.data;
    } catch (err) {
      var msg = (err.response && err.response.data && err.response.data.message) || err.message;
      showToast(msg, 'error');
      throw err;
    }
  },
  delete: async function (url) {
    return this.del(url);
  }
};

// 座位颜色
var seatColors = {
  free: { bg: '#e6f4ea', color: '#1e7e34', text: '空闲', icon: 'fa-check-circle' },
  occupied: { bg: '#fce8e6', color: '#d93025', text: '占用', icon: 'fa-user' },
  locked: { bg: '#fff3e0', color: '#e37400', text: '锁定', icon: 'fa-lock' },
  error: { bg: '#f1f3f4', color: '#5f6368', text: '异常', icon: 'fa-exclamation-triangle' }
};

// 格式化时间
function formatTime(t) {
  if (!t) return '-';
  var d = new Date(t);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// 座位类型
function seatTypeLabel(type) {
  var map = { normal: '普通', window: '靠窗', quiet: '安静区', power: '电源位', disabled: '无障碍' };
  return map[type] || type || '普通';
}

// 预约状态
function reservationStatusText(status) {
  var map = { pending: '待签到', checked_in: '已签到', completed: '已完成', cancelled: '已取消', no_show: '未签到' };
  return map[status] || status;
}

/* 雾水背景 / 鼠标柔光 / 点击涟漪 */
(function () {
  'use strict';
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function mountEffects() {
    if (document.getElementById('shuimo-fog')) return;
    var fog = document.createElement('div');
    fog.className = 'fog';
    fog.id = 'shuimo-fog';
    ['a', 'b', 'c'].forEach(function (name) {
      var span = document.createElement('span');
      span.className = name;
      fog.appendChild(span);
    });
    document.body.appendChild(fog);

    var glow = document.createElement('div');
    glow.className = 'cursor-glow';
    document.body.appendChild(glow);
  }

  if (document.body) {
    mountEffects();
  } else {
    document.addEventListener('DOMContentLoaded', mountEffects);
  }

  document.addEventListener('pointerdown', function (e) {
    if (reduced) return;
    var el = e.target.closest('button, .choose-card, .venue-card, .region-tag, .time-slot, .tag-chip, .path-segment');
    if (!el) return;
    var cs = getComputedStyle(el);
    if (cs.position === 'static') el.style.position = 'relative';
    if (cs.overflow !== 'hidden' && cs.overflow !== 'auto' && cs.overflow !== 'scroll') el.style.overflow = 'hidden';
    var r = el.getBoundingClientRect();
    var s = Math.max(r.width, r.height);
    var sp = document.createElement('span');
    sp.className = 'ripple';
    sp.style.width = sp.style.height = s + 'px';
    sp.style.left = (e.clientX - r.left - s / 2) + 'px';
    sp.style.top = (e.clientY - r.top - s / 2) + 'px';
    el.appendChild(sp);
    sp.addEventListener('animationend', function () {
      sp.remove();
    });
  });

  var glow = document.querySelector('.cursor-glow');
  if (glow && !reduced && window.matchMedia && window.matchMedia('(pointer: fine)').matches) {
    var tx = window.innerWidth / 2;
    var ty = window.innerHeight / 2;
    var cx = tx;
    var cy = ty;
    window.addEventListener('pointermove', function (e) {
      tx = e.clientX;
      ty = e.clientY;
    }, { passive: true });
    (function loop() {
      cx += (tx - cx) * 0.12;
      cy += (ty - cy) * 0.12;
      glow.style.transform = 'translate(' + (cx - 110) + 'px,' + (cy - 110) + 'px)';
      window.requestAnimationFrame(loop);
    })();
  } else if (glow) {
    glow.style.display = 'none';
  }
})();

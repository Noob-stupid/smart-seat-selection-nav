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

/* 预约签到 - 两种模式：
   1. 二维码扫描签到（受后端开关控制，管理员开启并粘贴座位二维码后可用）
   2. 按钮签到（需传感器检测到座位上有人 + 用户定位在座位附近）
*/
(function () {
  // 保存当前定位节点（导航页定位成功后也会自动保存）
  window.saveCheckinLocNode = function (nodeId) {
    if (!nodeId) return;
    localStorage.setItem('checkin_loc_node', String(nodeId).trim());
    showToast('已保存定位节点 ' + nodeId);
  };

  // 扫码签到：读取扫码枪/手动输入的二维码内容
  window.scanCheckin = function () {
    var input = document.getElementById('checkin-token');
    var token = input ? input.value.trim() : '';
    if (!token) { showToast('请先扫描或输入二维码内容', 'error'); return; }
    api.post('/api/checkin/scan', { token: token }).then(function () {
      showToast('签到成功');
      setTimeout(function () { location.reload(); }, 800);
    }).catch(function () { });
  };

  // 按钮签到：带上本地定位节点，由后端校验"传感器有人 + 在座位附近"
  window.doCheckin = function (reservationId) {
    var locNodeId = localStorage.getItem('checkin_loc_node') || '';
    api.post('/api/reservations/' + reservationId + '/checkin', { loc_node_id: locNodeId }).then(function () {
      showToast('签到成功');
      setTimeout(function () { location.reload(); }, 800);
    }).catch(function (err) {
      var msg = (err.response && err.response.data && err.response.data.message) || '';
      // 定位缺失/不在附近时，引导用户补充当前节点
      if (msg.indexOf('扫码定位') >= 0 || msg.indexOf('不在该座位附近') >= 0) {
        var node = prompt('请输入您当前所在位置的节点ID（可在导航页"扫码定位"获得，如 N12）：');
        if (node && node.trim()) {
          saveCheckinLocNode(node.trim());
          api.post('/api/reservations/' + reservationId + '/checkin', { loc_node_id: node.trim() }).then(function () {
            showToast('签到成功');
            setTimeout(function () { location.reload(); }, 800);
          }).catch(function () { });
        }
      }
    });
  };
})();

/* ============================================================================
   浏览器内 mock 数据层（纯静态环境的后端替身）
   ----------------------------------------------------------------------------
   原工程用 static/js/api-client.js 通过 fetch 访问真实 Flask 后端（app.py）。
   去掉 Flask 后，本文件在浏览器内实现同一套接口，使所有页面可离线交互。

   与真实后端保持一致的契约（改写自 app.py + api-client.js）：
     · window.axios.get/post/put/delete(url[, data][, config])
       - 成功 resolve { status, data: body }
       - 失败 reject  { response: { status, data: body } }
     · body 恒为信封 { code, message, data }，且 code == HTTP 状态码
     · 列表放在 data 内（没有裸数组接口）
     · GET 参数从 config.params 读取（app.js 的 api.get 会包成 { params }）
     · 错误 message 为中文，前端 toast 直接展示

   数据保存在内存 + localStorage（刷新后保留建图任务、预约、配置、登录态）。
   接入真实后端时，把页面里的 mock-api.js 换回 api-client.js 即可。
   ========================================================================== */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- 响应工具 */
  function ok(data, message, code) {
    var status = code || 200;
    return {
      status: status,
      data: { code: status, message: message === undefined ? 'success' : message, data: data === undefined ? null : data },
    };
  }
  function fail(message, code) {
    var status = code || 400;
    var body = { code: status, message: message || '请求失败', data: null };
    return Promise.reject({ response: { status: status, data: body } });
  }

  /* ---------------------------------------------------------------- 通用工具 */
  var _idSeq = 10000;
  function nextId() { return ++_idSeq; }

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  /* 后端约定：预约时间带 Z，其余对象时间不带 Z */
  function isoNoZ(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' +
      pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  function isoZ(d) { return new Date(d).toISOString().split('.')[0] + 'Z'; }

  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  function findById(list, id) {
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  function paginateNone(list) { return list; }

  /* ---------------------------------------------------------------- 种子数据 */
  var SEED_BUILDINGS = [
    { name: '文化中心', alias: 'WZ', region: '广州市', address: '大学城中心', description: '综合活动场所', lat: 23.0489, lng: 113.3957 },
    { name: '图书馆', alias: 'LIB', region: '广州市', address: '东门旁', description: '安静学习空间', lat: 23.0501, lng: 113.3982 },
    { name: '教学楼 A', alias: 'A', region: '广州市', address: '南门', description: '公共教室与自习区', lat: 23.0462, lng: 113.3941 },
  ];
  var FLOOR_COUNTS = [3, 2, 4];
  var SEAT_TYPES = ['normal', 'window', 'quiet', 'power'];

  var state = {
    users: [],
    buildings: [],
    floors: [],
    seats: [],
    reservations: [],
    networks: {},
    mappingTasks: {},
    config: {
      ai_weights: [0.35, 0.25, 0.25, 0.15],
      lock_m_default: 20,
      lock_n_default: 5,
      lock_t_default: 30,
      lock_m_range: [10, 60],
      lock_n_range: [2, 15],
      lock_t_range: [10, 120],
      sensor_scan_interval: 30,
      seat_offline_hours: 24,
      seat_sweep_interval_minutes: 30,
      checkin_qr_enabled: true,   /* 演示环境默认开启，便于测试签到与二维码页 */
    },
    simulatorRunning: false,
    simulatorTimer: null,
    pendingUsers: [],
    abnormalUsers: [],
    sensorDevices: [],
    currentUserId: null,
  };

  /* ---------------------------------------------------------------- 持久化 */
  var KEYS = {
    user: 'seat_app_current_user',
    reservations: 'seat_app_reservations',
    mapping: 'seat_app_mapping_tasks',
    config: 'seat_app_config',
  };
  function store(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { }
  }
  function load(key) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  /* ---------------------------------------------------------------- 建种子 */
  (function seed() {
    var now = new Date();

    /* 用户：1 演示管理员 + 1 普通用户 + 2 待审核 */
    state.users = [
      { id: 1, student_id: 'admin', name: '演示管理员', role: 'admin', email: 'admin@example.com', phone: '13800000001', avatar_url: '', preferences: { tags: ['安静学习', '靠窗座位'] }, is_active: true, created_at: isoNoZ(now) },
      { id: 2, student_id: '2024002', name: '张三', role: 'student', email: 'zhangsan@example.com', phone: '', avatar_url: '', preferences: { tags: ['靠窗座位'] }, is_active: true, created_at: isoNoZ(now) },
      { id: 3, student_id: '2026001', name: '新管理员', role: 'admin', email: 'new-admin@example.com', phone: '', avatar_url: '', preferences: { tags: [] }, is_active: false, created_at: isoNoZ(now) },
    ];
    state.pendingUsers = [
      { id: 3, name: '新管理员', student_id: '2026001', email: 'new-admin@example.com' },
      { id: 4, name: '林同学', student_id: '2026002', email: 'lin@example.com' },
    ];

    state.abnormalUsers = [
      {
        user_id: 2, user_name: '张三', student_id: '2024002',
        total_lock_count: 8, return_rate: 0.21, absence_rate: 0.74, dynamic_m: 60, dynamic_n: 2,
        lock_history: [
          { start: '2026-08-02 09:20', duration_sec: 780, detections: 13, valid_returns: 2 },
          { start: '2026-08-02 14:05', duration_sec: 640, detections: 11, valid_returns: 3 },
          { start: '2026-08-03 08:40', duration_sec: 720, detections: 12, valid_returns: 2 },
        ],
      },
    ];

    /* 建筑物 / 楼层 / 座位 */
    var seatId = 0;
    var floorId = 0;
    SEED_BUILDINGS.forEach(function (b, bi) {
      var building = {
        id: bi + 1, name: b.name, alias: b.alias, region: b.region, address: b.address,
        lat: b.lat, lng: b.lng, description: b.description, is_active: true,
        floor_count: FLOOR_COUNTS[bi] || 2, created_at: isoNoZ(now),
      };
      state.buildings.push(building);

      for (var f = 1; f <= building.floor_count; f++) {
        floorId++;
        var floor = {
          id: floorId, building_id: building.id, building_name: building.name,
          floor_number: f, name: f + '楼',
          floor_plan_path: '', floor_plan_url: null,
          floor_plan_width: 800, floor_plan_height: 600,
          road_network_path: null, is_active: true, seat_count: 0,
        };
        state.floors.push(floor);

        var rows = 4;
        var cols = 6 + ((bi + f) % 4);
        var n = 0;
        for (var r = 0; r < rows; r++) {
          for (var c = 0; c < cols; c++) {
            n++;
            seatId++;
            var mod = n + f + bi;
            var status = 'free';
            if (mod % 7 === 0) status = 'occupied';
            else if (mod % 11 === 0) status = 'locked';
            else if (mod % 13 === 0) status = 'error';
            var occupied = status === 'occupied';
            state.seats.push({
              id: seatId,
              floor_id: floor.id,
              seat_label: String.fromCharCode(65 + r) + '-' + pad(c + 1),
              seat_type: SEAT_TYPES[(c + r) % SEAT_TYPES.length],
              status: status,
              x: 90 + c * 74,
              y: 90 + r * 74,
              width: 40, height: 40, rotation: 0,
              nearest_node_id: (n % 5 === 0) ? 'n' + floor.id + '_' + (n % 8) : null,
              ir_front: occupied ? 1 : 0,
              ir_back: occupied ? 1 : 0,
              ir_enabled: !(mod % 17 === 0),
              is_active: !(mod % 29 === 0),
              current_user_id: occupied ? 2 : null,
              last_scan_time: occupied ? isoNoZ(new Date(now.getTime() - n * 60000)) : null,
              created_at: isoNoZ(now),
            });
          }
        }
        floor.seat_count = state.seats.filter(function (s) { return s.floor_id === floor.id; }).length;
      }
    });

    /* 传感器设备（ESP32） */
    state.sensorDevices = [
      { id: 1, device_id: 'AA:BB:CC:DD:EE:01', is_new: false, online: true, seat_id: state.seats[0].id, sensor_type: 'pir', ir_active_high: true, distance_threshold_cm: 50, report_interval_ms: 5000, last_seen: isoNoZ(now) },
      { id: 2, device_id: 'AA:BB:CC:DD:EE:02', is_new: false, online: false, seat_id: state.seats[1].id, sensor_type: 'ir', ir_active_high: false, distance_threshold_cm: 50, report_interval_ms: 5000, last_seen: isoNoZ(new Date(now.getTime() - 3600000)) },
      { id: 3, device_id: 'AA:BB:CC:DD:EE:03', is_new: true, online: true, seat_id: null, sensor_type: 'ultrasonic', ir_active_high: true, distance_threshold_cm: 80, report_interval_ms: 3000, last_seen: isoNoZ(now) },
    ];

    /* 演示预约：一条待签到（座位传感器已就绪，可直接签到）、一条已签到 */
    var demoSeat = state.seats.find(function (s) { return s.status === 'free'; }) || state.seats[0];
    demoSeat.ir_front = 1; demoSeat.ir_back = 1; demoSeat.nearest_node_id = null;
    var secondSeat = state.seats.filter(function (s) { return s.status === 'free' && s.id !== demoSeat.id; })[0] || demoSeat;
    secondSeat.ir_front = 1; secondSeat.ir_back = 1; secondSeat.nearest_node_id = null;

    state.reservations = [
      {
        id: 1, user_id: 1, seat_id: demoSeat.id, seat_label: demoSeat.seat_label, building_id: demoSeat.floor_id ? floorBuildingId(demoSeat.floor_id) : 1,
        start_time: isoZ(new Date(now.getTime() - 1800000)), end_time: isoZ(new Date(now.getTime() + 5400000)),
        checkin_time: null, checkout_time: null, status: 'pending',
        qr_token: 'demo-token-' + demoSeat.id, created_at: isoZ(new Date(now.getTime() - 3600000)),
      },
      {
        id: 2, user_id: 1, seat_id: secondSeat.id, seat_label: secondSeat.seat_label, building_id: secondSeat.floor_id ? floorBuildingId(secondSeat.floor_id) : 1,
        start_time: isoZ(new Date(now.getTime() - 7200000)), end_time: isoZ(new Date(now.getTime() - 3600000)),
        checkin_time: isoZ(new Date(now.getTime() - 7000000)), checkout_time: null, status: 'checked_in',
        qr_token: 'demo-token-' + secondSeat.id, created_at: isoZ(new Date(now.getTime() - 9000000)),
      },
    ];

    /* 恢复本地持久化内容 */
    var savedRes = load(KEYS.reservations);
    if (Array.isArray(savedRes) && savedRes.length) state.reservations = savedRes;
    var savedCfg = load(KEYS.config);
    if (savedCfg && typeof savedCfg === 'object') state.config = Object.assign(state.config, savedCfg);
    var savedMap = load(KEYS.mapping);
    if (savedMap && typeof savedMap === 'object') state.mappingTasks = savedMap;
    var savedUser = load(KEYS.user);
    if (savedUser && savedUser.student_id) {
      var matched = state.users.filter(function (u) { return u.student_id === savedUser.student_id; })[0];
      if (matched) state.currentUserId = matched.id;
    }
  })();

  function floorBuildingId(fid) {
    var f = findById(state.floors, fid);
    return f ? f.building_id : null;
  }

  /* ---------------------------------------------------------------- 对象序列化 */
  function userDict(u, withToken) {
    if (!u) return null;
    var d = {
      id: u.id, student_id: u.student_id, name: u.name, role: u.role,
      email: u.email || '', phone: u.phone || '', avatar_url: u.avatar_url || '',
      preferences: u.preferences || { tags: [] }, is_active: u.is_active !== false,
      created_at: u.created_at || isoNoZ(new Date()),
    };
    if (withToken) d.password = u.password;
    return d;
  }

  function buildingDict(b, withStats) {
    var d = {
      id: b.id, name: b.name, alias: b.alias || '', region: b.region || '', address: b.address || '',
      lat: b.lat === undefined ? null : b.lat, lng: b.lng === undefined ? null : b.lng,
      description: b.description || '', is_active: b.is_active !== false,
      floor_count: state.floors.filter(function (f) { return f.building_id === b.id && f.is_active !== false; }).length,
      created_at: b.created_at || isoNoZ(new Date()),
    };
    if (withStats) {
      var floorIds = state.floors.filter(function (f) { return f.building_id === b.id; }).map(function (f) { return f.id; });
      var seats = state.seats.filter(function (s) { return floorIds.indexOf(s.floor_id) >= 0 && s.is_active !== false; });
      d.total_seats = seats.length;
      d.free_seats = seats.filter(function (s) { return s.status === 'free'; }).length;
    }
    return d;
  }

  function floorDict(f) {
    return {
      id: f.id, building_id: f.building_id, building_name: f.building_name,
      floor_number: f.floor_number, name: f.name || (f.floor_number + 'F'),
      floor_plan_path: f.floor_plan_path || '',
      floor_plan_url: f.floor_plan_url || (f.floor_plan_path ? f.floor_plan_path : null),
      floor_plan_width: f.floor_plan_width || 800,
      floor_plan_height: f.floor_plan_height || 600,
      road_network_path: f.road_network_path || null,
      is_active: f.is_active !== false,
      seat_count: state.seats.filter(function (s) { return s.floor_id === f.id; }).length,
    };
  }

  function seatDict(s, withContext) {
    var d = {
      id: s.id, floor_id: s.floor_id, seat_label: s.seat_label, seat_type: s.seat_type,
      status: s.status, x: s.x, y: s.y, width: s.width, height: s.height, rotation: s.rotation || 0,
      nearest_node_id: s.nearest_node_id || null,
      ir_front: s.ir_front || 0, ir_back: s.ir_back || 0,
      ir_enabled: s.ir_enabled !== false,
      is_active: s.is_active !== false,
      current_user_id: s.current_user_id || null,
      last_scan_time: s.last_scan_time || null,
    };
    if (withContext) {
      var f = findById(state.floors, s.floor_id);
      if (f) {
        d.floor_number = f.floor_number;
        d.floor_name = f.name || (f.floor_number + 'F');
        d.building_id = f.building_id;
        var b = findById(state.buildings, f.building_id);
        d.building_name = b ? b.name : '';
      }
      if (s.status === 'occupied' && s.current_user_id) {
        var u = findById(state.users, s.current_user_id);
        d.occupant_name = u ? u.name : '';
        d.occupant_avatar = u ? (u.avatar_url || '') : '';
      }
    }
    return d;
  }

  function reservationDict(r) {
    return {
      id: r.id, user_id: r.user_id, seat_id: r.seat_id,
      seat_label: r.seat_label !== undefined ? r.seat_label : (function () {
        var s = findById(state.seats, r.seat_id);
        return s ? s.seat_label : null;
      })(),
      building_id: r.building_id === undefined ? floorBuildingId((findById(state.seats, r.seat_id) || {}).floor_id) : r.building_id,
      start_time: r.start_time, end_time: r.end_time,
      checkin_time: r.checkin_time || null, checkout_time: r.checkout_time || null,
      status: r.status, status_text: STATUS_TEXT[r.status] || r.status,
      qr_token: r.qr_token || null, created_at: r.created_at,
    };
  }

  var STATUS_TEXT = { pending: '待签到', checked_in: '已签到', completed: '已完成', cancelled: '已取消', no_show: '未签到' };

  function persistReservations() { store(KEYS.reservations, state.reservations); }

  /* ---------------------------------------------------------------- 路网 */
  function buildNetwork(floorId) {
    var nodes = {};
    var edges = [];
    var f = findById(state.floors, floorId);
    var cols = 5, rows = 3;
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var id = 'n' + floorId + '_' + (r * cols + c);
        nodes[id] = { x: 90 + c * 155, y: 110 + r * 180, type: 'normal', name: (r === 0 && c === 0) ? '入口' : null };
      }
    }
    for (var rr = 0; rr < rows; rr++) {
      for (var cc = 0; cc < cols; cc++) {
        var cur = 'n' + floorId + '_' + (rr * cols + cc);
        if (cc < cols - 1) edges.push({ from: cur, to: 'n' + floorId + '_' + (rr * cols + cc + 1) });
        if (rr < rows - 1) edges.push({ from: cur, to: 'n' + floorId + '_' + ((rr + 1) * cols + cc) });
      }
    }
    /* 座位作为可导航终点接入最近节点 */
    state.seats.filter(function (s) { return s.floor_id === floorId && s.is_active !== false; }).forEach(function (s) {
      var nodeId = 'seat_' + s.id;
      nodes[nodeId] = { x: s.x, y: s.y, type: 'seat', name: s.seat_label };
      var best = null, bestD = Infinity;
      Object.keys(nodes).forEach(function (k) {
        if (nodes[k].type === 'seat') return;
        var d = Math.pow(nodes[k].x - s.x, 2) + Math.pow(nodes[k].y - s.y, 2);
        if (d < bestD) { bestD = d; best = k; }
      });
      if (best) edges.push({ from: best, to: nodeId });
      if (!s.nearest_node_id) s.nearest_node_id = best;
    });
    return {
      nodes: nodes, edges: edges,
      floor_info: { width: (f ? f.floor_plan_width : 800) || 800, height: (f ? f.floor_plan_height : 600) || 600 },
    };
  }

  function getNetwork(floorId) {
    if (!state.networks[floorId]) state.networks[floorId] = buildNetwork(floorId);
    return state.networks[floorId];
  }

  function nearestNode(net, x, y) {
    var best = null, bestD = Infinity;
    Object.keys(net.nodes).forEach(function (k) {
      if (net.nodes[k].type === 'seat') return;
      var d = Math.pow(net.nodes[k].x - x, 2) + Math.pow(net.nodes[k].y - y, 2);
      if (d < bestD) { bestD = d; best = k; }
    });
    return best;
  }

  /* 同层最短路（BFS，与后端 networkx 行为一致：不连通返回 error） */
  function shortestPath(net, from, to) {
    if (!net.nodes[from] || !net.nodes[to]) return null;
    var adj = {};
    net.edges.forEach(function (e) {
      if (!net.nodes[e.from] || !net.nodes[e.to]) return;
      (adj[e.from] = adj[e.from] || []).push(e.to);
      (adj[e.to] = adj[e.to] || []).push(e.from);
    });
    var prev = {}, seen = {}; seen[from] = true;
    var queue = [from];
    while (queue.length) {
      var cur = queue.shift();
      if (cur === to) break;
      (adj[cur] || []).forEach(function (nx) {
        if (seen[nx]) return;
        seen[nx] = true; prev[nx] = cur; queue.push(nx);
      });
    }
    if (!seen[to]) return null;
    var path = [to];
    while (path[0] !== from) path.unshift(prev[path[0]]);
    return path;
  }

  function pathDistance(net, path) {
    var d = 0;
    for (var i = 1; i < path.length; i++) {
      var a = net.nodes[path[i - 1]], b = net.nodes[path[i]];
      d += Math.sqrt(Math.pow(a.x - b.x, 2) + Math.pow(a.y - b.y, 2));
    }
    return Math.round(d * 10) / 10;
  }

  function pathPoints(net, path) {
    return path.map(function (id) {
      var n = net.nodes[id];
      return { node_id: id, x: n.x, y: n.y, type: n.type || 'normal' };
    });
  }

  /* ---------------------------------------------------------------- 建图（模拟后端 auto_mapping） */
  function buildMockMappingImage(taskId, w, h) {
    var m = Math.round(Math.min(w, h) * 0.06);
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '">' +
      '<rect width="' + w + '" height="' + h + '" fill="#f7f4ee"/>' +
      '<rect x="' + m + '" y="' + m + '" width="' + (w - 2 * m) + '" height="' + (h - 2 * m) + '" fill="none" stroke="#e2dccd" stroke-width="6" stroke-dasharray="26 18"/>' +
      '<circle cx="' + Math.round(w * 0.82) + '" cy="' + Math.round(h * 0.16) + '" r="' + Math.round(Math.min(w, h) * 0.045) + '" fill="#ece6d8"/>' +
      '<rect x="' + Math.round(w * 0.14) + '" y="' + Math.round(h * 0.62) + '" width="' + Math.round(w * 0.2) + '" height="' + Math.round(h * 0.14) + '" rx="8" fill="#e7e0d1"/>' +
      '<rect x="' + Math.round(w * 0.55) + '" y="' + Math.round(h * 0.55) + '" width="' + Math.round(w * 0.26) + '" height="' + Math.round(h * 0.16) + '" rx="8" fill="#e7e0d1"/>' +
      '</svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  function seedFromString(str) {
    var seed = 0;
    for (var i = 0; i < str.length; i++) seed = (seed * 31 + str.charCodeAt(i)) % 1000000007;
    return seed;
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function round2(n) { return Math.round(n * 100) / 100; }

  function buildMockMappingLines(taskId, w, h) {
    var rnd = mulberry32(seedFromString(taskId));
    var m = Math.round(Math.min(w, h) * 0.06);
    var doorW = Math.round(w * 0.1);
    var lines = [];
    function wall(x1, y1, x2, y2) {
      var dx = x2 - x1, dy = y2 - y1;
      lines.push({
        x1: x1, y1: y1, x2: x2, y2: y2,
        angle: round2(Math.atan2(dy, dx) * 180 / Math.PI),
        length: round2(Math.sqrt(dx * dx + dy * dy)), type: 'wall',
      });
    }
    wall(m, m, w - m, m);
    wall(w - m, m, w - m, h - m);
    wall(m, h - m, w / 2 - doorW / 2, h - m);
    wall(w / 2 + doorW / 2, h - m, w - m, h - m);
    wall(m, m, m, h - m);
    var gy = Math.round(h * 0.42);
    wall(m + Math.round(w * 0.18), gy, w / 2 - doorW / 2, gy);
    wall(w / 2 + doorW / 2, gy, w - m, gy);
    var gx = Math.round(w * 0.66);
    wall(gx, gy, gx, h - m - Math.round(h * 0.12));
    for (var i = 0; i < 4; i++) {
      var bx = m + Math.round(w * (0.08 + rnd() * 0.6));
      var by = m + Math.round(h * (0.1 + rnd() * 0.5));
      var bw = Math.round(Math.min(w, h) * (0.05 + rnd() * 0.08));
      wall(bx, by, bx + bw, by);
      wall(bx + bw, by, bx + bw, by + Math.round(bw * 0.6));
    }
    return lines;
  }

  function persistMapping() { store(KEYS.mapping, state.mappingTasks); }

  /* ---------------------------------------------------------------- 传感器模拟器 */
  function startSimulator() {
    if (state.simulatorRunning) return;
    state.simulatorRunning = true;
    state.simulatorTimer = setInterval(function () {
      var pool = state.seats.filter(function (s) { return s.is_active !== false; });
      for (var i = 0; i < 6; i++) {
        var s = pool[Math.floor(Math.random() * pool.length)];
        if (!s || s.status === 'locked' || s.status === 'error') continue;
        var nowOccupied = Math.random() > 0.5;
        s.status = nowOccupied ? 'occupied' : 'free';
        s.current_user_id = nowOccupied ? 2 : null;
        s.ir_front = nowOccupied ? 1 : 0;
        s.ir_back = nowOccupied ? 1 : 0;
        s.last_scan_time = isoNoZ(new Date());
      }
    }, 4000);
  }
  function stopSimulator() {
    state.simulatorRunning = false;
    if (state.simulatorTimer) { clearInterval(state.simulatorTimer); state.simulatorTimer = null; }
  }

  /* ---------------------------------------------------------------- 请求分发 */
  function currentUser() { return findById(state.users, state.currentUserId); }

  function requireLogin() {
    if (!state.currentUserId) return fail('请先登录', 401);
    return null;
  }

  function handle(method, url, body, config) {
    var raw = String(url || '');
    var path = raw.split('?')[0];
    var params = (config && config.params) || {};
    var m;

    /* ============================ 认证 / 用户 ============================ */
    if (path === '/api/auth/login' && method === 'POST') {
      var sid = String((body && body.student_id) || '').trim();
      var pwd = String((body && body.password) || '');
      if (!sid || !pwd) return fail('请填写账号和密码');
      var u = state.users.filter(function (x) { return x.student_id === sid; })[0];
      if (!u) return fail('账号或密码错误', 401);
      if (u.is_active === false) return fail('你的管理员账号正在审核中，请等待通知', 403);
      state.currentUserId = u.id;
      store(KEYS.user, { student_id: u.student_id, name: u.name, role: u.role, user_id: u.id });
      return ok({ user_id: u.id, name: u.name, role: u.role, student_id: u.student_id }, '登录成功');
    }

    if (path === '/api/auth/register' && method === 'POST') {
      var rsid = String((body && body.student_id) || '').trim();
      if (!rsid) return fail('请填写账号');
      if (String((body && body.password) || '').length < 6) return fail('密码至少6位');
      if (String(body.password) !== String(body.confirm_password)) return fail('两次输入的密码不一致');
      if (state.users.some(function (x) { return x.student_id === rsid; })) return fail('账号已存在');
      var role = body.role === 'admin' ? 'admin' : 'student';
      var nu = {
        id: nextId(), student_id: rsid, name: body.name || rsid, role: role,
        email: body.email || '', phone: '', avatar_url: '', preferences: { tags: [] },
        is_active: role !== 'admin', created_at: isoNoZ(new Date()), password: body.password,
      };
      state.users.push(nu);
      if (role === 'admin') {
        state.pendingUsers.push({ id: nu.id, name: nu.name, student_id: nu.student_id, email: nu.email });
        return ok({ user_id: nu.id, name: nu.name, role: nu.role }, '注册成功，管理员账号需审核后登录', 201);
      }
      return ok({ user_id: nu.id, name: nu.name, role: nu.role }, '注册成功，请登录', 201);
    }

    if (path === '/api/auth/me' && method === 'GET') {
      var me = currentUser();
      if (!me) return fail('未登录', 401);
      return ok(userDict(me));
    }

    if (path === '/api/profile' && method === 'PUT') {
      var pu = currentUser();
      if (!pu) return fail('未登录', 401);
      if (body && body.name) pu.name = body.name;
      if (body && body.email !== undefined && body.email !== null) pu.email = body.email;
      if (body && body.phone !== undefined && body.phone !== null) pu.phone = body.phone;
      if (body && body.tags !== undefined && body.tags !== null) pu.preferences = { tags: body.tags };
      store(KEYS.user, { student_id: pu.student_id, name: pu.name, role: pu.role, user_id: pu.id });
      return ok(userDict(pu), '资料已更新');
    }

    if (path === '/api/profile/avatar' && method === 'POST') {
      var au = currentUser();
      if (!au) return fail('未登录', 401);
      var avatarFile = body && body.get ? body.get('avatar') : null;
      if (!avatarFile) return fail('请选择头像文件');
      if (typeof FileReader !== 'undefined') {
        return new Promise(function (resolve) {
          var reader = new FileReader();
          reader.onload = function () {
            au.avatar_url = reader.result;
            resolve(ok({ avatar_url: au.avatar_url }, '头像已更新'));
          };
          reader.onerror = function () { resolve(ok({ avatar_url: au.avatar_url || '' }, '头像已更新')); };
          reader.readAsDataURL(avatarFile);
        });
      }
      au.avatar_url = '';
      return ok({ avatar_url: '' }, '头像已更新');
    }

    if (path === '/api/profile/password' && method === 'PUT') {
      if (!currentUser()) return fail('未登录', 401);
      if (!body || !body.old_password || !body.new_password) return fail('请填写新旧密码');
      if (String(body.new_password).length < 6) return fail('新密码至少6位');
      return ok(null, '密码已修改');
    }

    /* ============================ 场所 / 楼层 / 座位 ============================ */
    if (path === '/api/regions' && method === 'GET') {
      var regions = {};
      state.buildings.forEach(function (b) {
        var r = b.region || '其他';
        regions[r] = (regions[r] || 0) + 1;
      });
      return ok(Object.keys(regions).map(function (name) { return { name: name, count: regions[name] }; }));
    }

    if (path === '/api/search/venues' && method === 'GET') {
      var q = String(params.q || '').toLowerCase();
      var matched = state.buildings.filter(function (b) {
        if (!q) return true;
        return [b.name, b.alias || '', b.region || '', b.address || ''].join(' ').toLowerCase().indexOf(q) >= 0;
      });
      return ok(matched.map(function (b) { return buildingDict(b, true); }));
    }

    if (path === '/api/buildings' && method === 'GET') {
      var list = state.buildings
        .filter(function (b) { return b.is_active !== false; })
        .filter(function (b) { return !params.region || b.region === params.region; })
        .map(function (b) { return buildingDict(b, true); });
      return ok(list);
    }

    if (path === '/api/buildings' && method === 'POST') {
      if (!body || !body.name) return fail('请填写场所名称');
      var nb = {
        id: nextId(), name: body.name, alias: body.alias || '', region: body.region || '',
        address: body.address || '', lat: body.lat || null, lng: body.lng || null,
        description: body.description || '', is_active: true, floor_count: 0,
        created_at: isoNoZ(new Date()),
      };
      state.buildings.push(nb);
      return ok(buildingDict(nb), '添加成功', 201);
    }

    m = path.match(/^\/api\/buildings\/(\d+)$/);
    if (m) {
      var bid = Number(m[1]);
      var b2 = findById(state.buildings, bid);
      if (!b2) return fail('场所不存在', 404);
      if (method === 'GET') {
        var detail = buildingDict(b2, true);
        detail.floors = state.floors
          .filter(function (f) { return f.building_id === bid && f.is_active !== false; })
          .sort(function (x, y) { return x.floor_number - y.floor_number; })
          .map(floorDict);
        return ok(detail);
      }
      if (method === 'PUT') {
        Object.assign(b2, body || {});
        return ok(buildingDict(b2), '修改成功');
      }
      if (method === 'DELETE') {
        state.buildings = state.buildings.filter(function (x) { return x.id !== bid; });
        var removedFloors = state.floors.filter(function (f) { return f.building_id === bid; }).map(function (f) { return f.id; });
        state.floors = state.floors.filter(function (f) { return f.building_id !== bid; });
        state.seats = state.seats.filter(function (s) { return removedFloors.indexOf(s.floor_id) < 0; });
        return ok({ id: bid }, '已删除');
      }
    }

    m = path.match(/^\/api\/buildings\/(\d+)\/floors$/);
    if (m && method === 'POST') {
      var fb = findById(state.buildings, Number(m[1]));
      if (!fb) return fail('场所不存在', 404);
      var fnum = Number((body && body.floor_number) || 1);
      var exist = state.floors.filter(function (f) { return f.building_id === fb.id && f.floor_number === fnum; })[0];
      if (exist) return fail('该楼层已存在');
      var nf = {
        id: nextId(), building_id: fb.id, building_name: fb.name, floor_number: fnum,
        name: (body && body.name) || (fnum + '楼'), floor_plan_path: '', floor_plan_url: null,
        floor_plan_width: 800, floor_plan_height: 600, road_network_path: null,
        is_active: true, seat_count: 0,
      };
      state.floors.push(nf);
      fb.floor_count = state.floors.filter(function (f) { return f.building_id === fb.id; }).length;
      return ok({ id: nf.id }, '楼层创建成功', 201);
    }

    m = path.match(/^\/api\/floors\/(\d+)$/);
    if (m) {
      var fid = Number(m[1]);
      var fl = findById(state.floors, fid);
      if (!fl) return fail('楼层不存在', 404);
      if (method === 'GET') {
        var fd = floorDict(fl);
        fd.seats = state.seats
          .filter(function (s) { return s.floor_id === fid && s.is_active !== false; })
          .map(function (s) { return seatDict(s, true); });
        return ok(fd);
      }
      if (method === 'PUT') {
        Object.assign(fl, body || {});
        return ok(floorDict(fl), '修改成功');
      }
      if (method === 'DELETE') {
        state.floors = state.floors.filter(function (x) { return x.id !== fid; });
        state.seats = state.seats.filter(function (s) { return s.floor_id !== fid; });
        delete state.networks[fid];
        return ok({ id: fid }, '已删除');
      }
    }

    m = path.match(/^\/api\/floors\/(\d+)\/seats$/);
    if (m && method === 'POST') {
      var sfid = Number(m[1]);
      var sfl = findById(state.floors, sfid);
      if (!sfl) return fail('楼层不存在', 404);
      var items = Array.isArray(body) ? body : [body || {}];
      var ids = [];
      items.forEach(function (item, idx) {
        var ns = {
          id: nextId(), floor_id: sfid,
          seat_label: item.seat_label || ('新座位' + (idx + 1)),
          seat_type: item.seat_type || 'normal', status: 'free',
          x: Number(item.x) || 100, y: Number(item.y) || 100,
          width: 40, height: 40, rotation: 0, nearest_node_id: null,
          ir_front: 0, ir_back: 0, ir_enabled: true, is_active: true,
          current_user_id: null, last_scan_time: null, created_at: isoNoZ(new Date()),
        };
        state.seats.push(ns);
        ids.push(ns.id);
      });
      sfl.seat_count = state.seats.filter(function (s) { return s.floor_id === sfid; }).length;
      delete state.networks[sfid];
      return ok({ ids: ids }, '座位添加成功', 201);
    }

    if (path === '/api/seats' && method === 'GET') {
      var sl = state.seats.slice();
      if (params.floor_id) sl = sl.filter(function (s) { return s.floor_id === Number(params.floor_id); });
      if (params.status === 'inactive') sl = sl.filter(function (s) { return s.is_active === false; });
      else sl = sl.filter(function (s) { return s.is_active !== false; });
      if (params.status && params.status !== 'inactive') sl = sl.filter(function (s) { return s.status === params.status; });
      return ok(sl.map(function (s) { return seatDict(s, true); }));
    }

    m = path.match(/^\/api\/seats\/(\d+)$/);
    if (m) {
      var seatId2 = Number(m[1]);
      var st = findById(state.seats, seatId2);
      if (!st) return fail('座位不存在', 404);
      if (method === 'PUT') {
        Object.assign(st, body || {});
        return ok(seatDict(st, true), '已更新');
      }
      if (method === 'DELETE') {
        state.seats = state.seats.filter(function (x) { return x.id !== seatId2; });
        return ok({ id: seatId2 }, '已删除');
      }
    }

    if (path === '/api/admin/seats/ir' && method === 'PUT') {
      var enable = !(body && body.ir_enabled === false);
      state.seats.forEach(function (s) { s.ir_enabled = enable; });
      return ok(null, enable ? '已开启全部红外传感器' : '已关闭全部红外传感器');
    }

    if (path === '/api/status' && method === 'GET') {
      var act = state.seats.filter(function (s) { return s.is_active !== false; });
      return ok({
        total: act.length,
        free: act.filter(function (s) { return s.status === 'free'; }).length,
        occupied: act.filter(function (s) { return s.status === 'occupied'; }).length,
        locked: act.filter(function (s) { return s.status === 'locked'; }).length,
        error: act.filter(function (s) { return s.status === 'error'; }).length,
      });
    }

    if (path === '/api/recommend' && method === 'GET') {
      var rlist = state.seats.filter(function (s) {
        return s.is_active !== false && s.status === 'free' && (!params.floor_id || s.floor_id === Number(params.floor_id));
      }).slice(0, 5);
      return ok(rlist.map(function (s) { return seatDict(s, true); }));
    }

    /* ============================ 预约 / 签到 ============================ */
    if (path === '/api/reservations' && method === 'GET') {
      if (!state.currentUserId) return fail('请先登录', 401);
      var mine = state.reservations
        .filter(function (r) { return r.user_id === state.currentUserId; })
        .filter(function (r) { return !params.status || r.status === params.status; })
        .sort(function (a, b) { return String(b.created_at).localeCompare(String(a.created_at)); });
      return ok(mine.map(reservationDict));
    }

    if (path === '/api/reservations' && method === 'POST') {
      var ru = currentUser();
      if (!ru) return fail('请先登录', 401);
      var targetSeat = findById(state.seats, Number(body && body.seat_id));
      if (!targetSeat) return fail('座位不存在', 404);
      var start = body && body.start_time ? new Date(body.start_time) : new Date();
      var end;
      if (body && body.end_time) end = new Date(body.end_time);
      else if (body && body.duration) end = new Date(start.getTime() + Number(body.duration) * 3600000);
      else end = new Date(start.getTime() + 7200000);
      if (isNaN(start.getTime())) start = new Date();
      if (isNaN(end.getTime())) end = new Date(start.getTime() + 7200000);
      if (end <= start) return fail('结束时间必须晚于开始时间');
      var activeCount = state.reservations.filter(function (r) {
        return r.user_id === ru.id && (r.status === 'pending' || r.status === 'checked_in');
      }).length;
      if (activeCount >= 2) return fail('每人最多同时预约 2 个时间段，请先使用或取消已有预约');
      var clash = state.reservations.some(function (r) {
        return r.seat_id === targetSeat.id && (r.status === 'pending' || r.status === 'checked_in') &&
          new Date(r.start_time) < end && new Date(r.end_time) > start;
      });
      if (clash) return fail('该时段已被预约');
      var nr = {
        id: nextId(), user_id: ru.id, seat_id: targetSeat.id, seat_label: targetSeat.seat_label,
        building_id: floorBuildingId(targetSeat.floor_id),
        start_time: isoZ(start), end_time: isoZ(end), checkin_time: null, checkout_time: null,
        status: 'pending', qr_token: 'qt' + Date.now().toString(16), created_at: isoZ(new Date()),
      };
      state.reservations.push(nr);
      targetSeat.status = 'locked';
      persistReservations();
      return ok(reservationDict(nr), '预约成功', 201);
    }

    m = path.match(/^\/api\/reservations\/(\d+)\/cancel$/);
    if (m && method === 'POST') {
      if (!state.currentUserId) return fail('请先登录', 401);
      var cr = findById(state.reservations, Number(m[1]));
      if (!cr) return fail('预约不存在', 404);
      if (cr.status === 'completed' || cr.status === 'cancelled') return fail('预约已结束');
      cr.status = 'cancelled';
      var cs = findById(state.seats, cr.seat_id);
      if (cs) cs.status = 'free';
      persistReservations();
      return ok(null, '已取消');
    }

    m = path.match(/^\/api\/reservations\/(\d+)\/checkin$/);
    if (m && method === 'POST') {
      var r = findById(state.reservations, Number(m[1]));
      if (!r) return fail('预约不存在', 404);
      if (r.status !== 'pending') return fail('预约状态无效');
      var cseat = findById(state.seats, r.seat_id);
      if (!cseat) return fail('座位不存在', 404);
      if (!(cseat.ir_front === 1 && cseat.ir_back === 1)) {
        return fail('无法签到：座位传感器未检测到有人，请入座后重试');
      }
      if (cseat.nearest_node_id) {
        var locNode = body && body.loc_node_id;
        if (!locNode) return fail('无法签到：请先在导航页扫码定位到座位附近');
        if (String(locNode) !== String(cseat.nearest_node_id)) return fail('无法签到：您不在该座位附近');
      }
      r.status = 'checked_in';
      r.checkin_time = isoZ(new Date());
      cseat.status = 'occupied';
      cseat.current_user_id = r.user_id;
      cseat.last_scan_time = isoNoZ(new Date());
      persistReservations();
      return ok(reservationDict(r), '签到成功');
    }

    if (path === '/api/checkin/scan' && method === 'POST') {
      if (!state.config.checkin_qr_enabled) return fail('二维码签到功能未开启，请联系管理员');
      var token = String((body && body.token) || '').trim();
      if (!token) return fail('请提供二维码内容');
      var target = null;
      var seatMatch = token.match(/^SEAT:(\d+)/);
      if (seatMatch) {
        target = state.reservations.filter(function (x) {
          return x.seat_id === Number(seatMatch[1]) && x.status === 'pending' && x.user_id === state.currentUserId;
        })[0];
      } else {
        target = state.reservations.filter(function (x) { return x.qr_token === token && x.status === 'pending'; })[0];
      }
      if (!target) return fail('二维码无效或已失效', 404);
      target.status = 'checked_in';
      target.checkin_time = isoZ(new Date());
      var ts = findById(state.seats, target.seat_id);
      if (ts) { ts.status = 'occupied'; ts.current_user_id = target.user_id; }
      persistReservations();
      return ok(reservationDict(target), '签到成功');
    }

    /* ============================ 导航 ============================ */
    if (path === '/api/navigation/locate' && method === 'POST') {
      var lfid = Number((body && body.floor_id) || 0);
      if (!lfid) return fail('缺少 floor_id');
      var net = getNetwork(lfid);
      if (!net || !Object.keys(net.nodes).length) return ok({ error: '路网未加载' });
      if ((body && body.type) === 'qr') {
        var qn = net.nodes[String(body.node_id)];
        if (!qn) return ok({ error: '无效的定位节点' });
        return ok({ floor_id: lfid, node_id: String(body.node_id), x: qn.x, y: qn.y, position_name: qn.name || '未知位置' });
      }
      var cx = Number((body && body.click_x) || 0);
      var cy = Number((body && body.click_y) || 0);
      var nn = nearestNode(net, cx, cy);
      if (!nn) return ok({ error: '未找到附近路网节点' });
      return ok({
        floor_id: lfid, node_id: nn, x: net.nodes[nn].x, y: net.nodes[nn].y,
        position_name: net.nodes[nn].name || '已吸附到路网',
        original_click: { x: cx, y: cy },
      });
    }

    if (path === '/api/navigation/plan' && method === 'POST') {
      var fromF = Number((body && body.from_floor_id) || 0);
      var toF = Number((body && body.to_floor_id) || fromF);
      if (!fromF) return fail('缺少起点楼层');
      var netFrom = getNetwork(fromF);
      if (!netFrom || !Object.keys(netFrom.nodes).length) {
        return ok({ error: '路网未加载', path: [], distance: 0 });
      }
      var resolveNode = function (net2, nodeId, x, y) {
        if (nodeId && net2.nodes[String(nodeId)]) return String(nodeId);
        if (x !== undefined && y !== undefined && x !== null && y !== null) return nearestNode(net2, Number(x), Number(y));
        return nearestNode(net2, 0, 0);
      };
      var startId = resolveNode(netFrom, body && body.from_node, body && body.from_x, body && body.from_y);
      var netTo = toF === fromF ? netFrom : getNetwork(toF);
      var endId = resolveNode(netTo, body && body.to_node, body && body.to_x, body && body.to_y);
      if (!startId || !endId) return fail('路径规划失败：无法确定起点或终点');

      if (fromF === toF) {
        var p = shortestPath(netFrom, startId, endId);
        var sNode = { id: startId, x: netFrom.nodes[startId].x, y: netFrom.nodes[startId].y };
        var eNode = { id: endId, x: netFrom.nodes[endId].x, y: netFrom.nodes[endId].y };
        if (!p) {
          return ok({
            error: '起点 ' + startId + ' 和终点 ' + endId + ' 之间没有连通路径，请检查路网是否连续',
            path: [], distance: 0, node_count: 0, start_node: sNode, end_node: eNode,
          });
        }
        return ok({
          floor_id: fromF, path: pathPoints(netFrom, p), distance: pathDistance(netFrom, p),
          node_count: p.length, start_node: sNode, end_node: eNode,
        });
      }

      /* 跨层：拆成 起点→楼梯口 / 楼梯口→终点 两段 */
      var p1 = shortestPath(netFrom, startId, endIdIn(netFrom)) || [startId];
      function endIdIn(net3) {
        var keys = Object.keys(net3.nodes);
        for (var i = 0; i < keys.length; i++) if (keys[i].indexOf('stair') >= 0) return keys[i];
        return keys[keys.length - 1];
      }
      var stairFrom = endIdIn(netFrom);
      var stairTo = endIdIn(netTo);
      var p1b = shortestPath(netFrom, startId, stairFrom) || [startId, stairFrom];
      var p2 = shortestPath(netTo, stairTo, endId) || [stairTo, endId];
      var d1 = pathDistance(netFrom, p1b);
      var d2 = pathDistance(netTo, p2);
      var diff = Math.abs((findById(state.floors, toF) || {}).floor_number - (findById(state.floors, fromF) || {}).floor_number) || 1;
      return ok({
        segments: [
          { floor_id: fromF, path: pathPoints(netFrom, p1b), distance: d1, label: '从起点到楼梯口' },
          { floor_id: toF, path: pathPoints(netTo, p2), distance: d2, label: '从楼梯口到目标座位' },
        ],
        total_distance: Math.round((d1 + d2) * 10) / 10,
        cross_floor_hint: '请上楼至' + diff + '层（走楼梯/电梯至' + toF + 'F）',
      });
    }

    /* ============================ 管理：配置 / 权重 / 审核 / 行为 ============================ */
    if (path === '/api/admin/config') {
      if (method === 'GET') return ok(clone(state.config));
      if (method === 'PUT') {
        Object.assign(state.config, body || {});
        store(KEYS.config, state.config);
        return ok(null, '配置已保存');
      }
    }

    if (path === '/api/admin/weights' && method === 'PUT') {
      if (body && Array.isArray(body.weights)) state.config.ai_weights = body.weights;
      store(KEYS.config, state.config);
      return ok(null, '权重已保存');
    }

    if (path === '/api/admin/pending-users' && method === 'GET') {
      return ok(state.pendingUsers.slice());
    }

    m = path.match(/^\/api\/admin\/(approve|reject)\/(\d+)$/);
    if (m && method === 'POST') {
      var puid = Number(m[2]);
      state.pendingUsers = state.pendingUsers.filter(function (u) { return u.id !== puid; });
      var target = findById(state.users, puid);
      if (target) target.is_active = m[1] === 'approve';
      return ok(null, m[1] === 'approve' ? '已通过审核' : '已驳回');
    }

    if (path === '/api/admin/abnormal-users' && method === 'GET') {
      return ok(clone(state.abnormalUsers));
    }

    if (path === '/api/admin/simulator/start' && method === 'POST') {
      startSimulator();
      return ok(null, '模拟器已启动');
    }

    if (path === '/api/admin/simulator/stop' && method === 'POST') {
      stopSimulator();
      return ok(null, '模拟器已停止');
    }

    /* ============================ 管理：传感器 ============================ */
    if (path === '/api/admin/sensor/overview' && method === 'GET') {
      return ok({
        config: {
          sensor_scan_interval: state.config.sensor_scan_interval,
          seat_offline_hours: state.config.seat_offline_hours,
          seat_sweep_interval_minutes: state.config.seat_sweep_interval_minutes,
        },
        simulator_running: state.simulatorRunning,
        seats: state.seats.filter(function (s) { return s.is_active !== false; }).slice(0, 40).map(function (s) {
          var f = findById(state.floors, s.floor_id) || {};
          var b = findById(state.buildings, f.building_id) || {};
          return {
            id: s.id, seat_label: s.seat_label,
            floor_name: f.name || ((f.floor_number || 1) + 'F'),
            building_name: b.name || '',
            status: s.status,
            ir_front: s.ir_front || 0, ir_back: s.ir_back || 0,
            online: s.ir_enabled !== false,
            last_scan_time: s.last_scan_time,
            ir_enabled: s.ir_enabled !== false,
          };
        }),
      });
    }

    if (path === '/api/admin/sensor/devices' && method === 'GET') {
      return ok({ devices: clone(state.sensorDevices) });
    }

    m = path.match(/^\/api\/admin\/sensor\/devices\/(\d+)$/);
    if (m && method === 'PUT') {
      var dev = findById(state.sensorDevices, Number(m[1]));
      if (!dev) return fail('设备不存在', 404);
      ['seat_id', 'sensor_type', 'ir_active_high', 'distance_threshold_cm', 'report_interval_ms'].forEach(function (k) {
        if (body && body[k] !== undefined) dev[k] = body[k];
      });
      dev.is_new = false;
      return ok(clone(dev), '设备配置已保存');
    }

    if (path === '/api/sensor/report' && method === 'POST') {
      var rs = findById(state.seats, Number(body && body.seat_id));
      if (!rs) return fail('座位不存在', 404);
      if (body && body.ir_front !== undefined) rs.ir_front = Number(body.ir_front) ? 1 : 0;
      if (body && body.ir_back !== undefined) rs.ir_back = Number(body.ir_back) ? 1 : 0;
      rs.last_scan_time = isoNoZ(new Date());
      if (rs.ir_front === 1 && rs.ir_back === 1 && rs.status === 'free') {
        rs.status = 'occupied';
        rs.current_user_id = 2;
      } else if (rs.ir_front === 0 && rs.ir_back === 0 && rs.status === 'occupied') {
        rs.status = 'free';
        rs.current_user_id = null;
      }
      return ok({ seat_id: rs.id, ir_front: rs.ir_front, ir_back: rs.ir_back }, '上报成功');
    }

    /* ============================ 管理：路网 ============================ */
    m = path.match(/^\/api\/admin\/network\/(\d+)$/);
    if (m) {
      var nfid = Number(m[1]);
      if (method === 'GET') return ok(getNetwork(nfid));
      if (method === 'DELETE') {
        delete state.networks[nfid];
        return ok(null, '路网已清除');
      }
    }

    if (path === '/api/admin/network/save-manual' && method === 'POST') {
      var saveFid = Number(body && body.floor_id);
      var netPayload = (body && body.network) || { nodes: {}, edges: [] };
      state.networks[saveFid] = {
        nodes: netPayload.nodes || {},
        edges: netPayload.edges || [],
        floor_info: netPayload.floor_info || { width: 800, height: 600 },
      };
      return ok(null, '路线已保存');
    }

    if (path === '/api/admin/network/generate' && method === 'POST') {
      var genFid = Number(body && body.floor_id);
      if (!genFid) return fail('缺少 floor_id');
      var genFloor = findById(state.floors, genFid);
      if (!genFloor) return fail('楼层不存在', 404);
      delete state.networks[genFid];
      var generated = getNetwork(genFid);
      return ok({
        network: {
          nodes: generated.nodes, edges: generated.edges,
          floor_info: {
            width: genFloor.floor_plan_width || 800,
            height: genFloor.floor_plan_height || 600,
            image_path: genFloor.floor_plan_path || undefined,
          },
        },
      }, '路网生成成功');
    }

    /* ============================ 上传 / 自动建图 ============================ */
    if (path === '/api/upload' && method === 'POST') {
      var file = body && body.get ? body.get('file') : null;
      if (!file) return fail('请选择文件');
      var fname = String(file.name || '');
      if (!/\.(png|jpe?g|webp|bmp)$/i.test(fname)) return fail('仅支持 PNG/JPG/WEBP/BMP 图片');
      return ok({
        session_id: 'sess-' + Date.now().toString(16),
        file_path: 'demo-uploads/' + fname,
        file_url: 'demo-uploads/' + fname,
        image_info: { width: 800, height: 600, channels: 3 },
      });
    }

    if (path === '/api/admin/mapping/tasks' && method === 'POST') {
      var isForm = !!(body && typeof body.get === 'function');
      var files = isForm ? (body.getAll('file') || []).filter(Boolean) : [];
      var firstName = files.length ? String(files[0].name || '') : '';
      if (!files.length) return fail('素材不足：未收到视频或图片', 400);
      if (/^fail/i.test(firstName)) return fail('素材不足（有效帧过少）或全景拼接失败，请更换拍摄素材后重试', 400);
      if (/^dep/i.test(firstName)) return fail('建图模块不可用：服务器缺少 OpenCV / NumPy 依赖', 500);
      var taskId = 'room_' + Date.now().toString(16) + Math.random().toString(16).slice(2, 6);
      var imgW = 1600, imgH = 1000;
      var lines = buildMockMappingLines(taskId, imgW, imgH);
      var task = {
        task_id: taskId,
        room: { id: taskId, name: (isForm && body.get('name')) || '自动建模房间', mode: 'phone_capture' },
        image: { width: imgW, height: imgH, url: buildMockMappingImage(taskId, imgW, imgH) },
        lines: lines, unit: 'pixel', line_count: lines.length,
        status: 'done', created_at: isoZ(new Date()),
      };
      state.mappingTasks[taskId] = task;
      persistMapping();
      return new Promise(function (resolve) {
        setTimeout(function () { resolve(ok(task, '建图完成')); }, 1600);
      });
    }

    m = path.match(/^\/api\/admin\/mapping\/tasks\/([\w-]+)$/);
    if (m && method === 'GET') {
      var saved = state.mappingTasks[m[1]];
      if (!saved) return fail('建图任务不存在或已被清理', 404);
      var copy = Object.assign({}, saved, { status: 'done' });
      delete copy.line_count;
      return ok(copy);
    }

    m = path.match(/^\/api\/admin\/mapping\/tasks\/([\w-]+)\/apply$/);
    if (m && method === 'POST') {
      var applyTask = state.mappingTasks[m[1]];
      if (!applyTask) return fail('建图结果不存在', 404);
      var afid = Number(body && body.floor_id);
      if (!afid) return fail('缺少 floor_id');
      var afloor = findById(state.floors, afid);
      if (!afloor) return fail('楼层不存在', 404);
      afloor.floor_plan_path = applyTask.image.url;
      afloor.floor_plan_url = applyTask.image.url;
      afloor.floor_plan_width = applyTask.image.width;
      afloor.floor_plan_height = applyTask.image.height;
      delete state.networks[afid];
      return ok({
        floor_id: afid, floor_plan_url: afloor.floor_plan_url,
        width: afloor.floor_plan_width, height: afloor.floor_plan_height,
      }, '建图结果已应用到楼层');
    }

    return fail('演示环境未实现该接口：' + method + ' ' + path, 404);
  }

  /* ---------------------------------------------------------------- axios 替身 */
  function request(method, url, data, config) {
    return new Promise(function (resolve, reject) {
      var result;
      try {
        result = handle(method, url, data, config);
      } catch (e) {
        reject({ response: { status: 500, data: { code: 500, message: (e && e.message) || '演示环境内部错误', data: null } } });
        return;
      }
      Promise.resolve(result).then(resolve, reject);
    });
  }

  /* ------------------------------------------------------------------
     导出策略（混合模式）
     ------------------------------------------------------------------
     本文件有两种使用方式，二者兼容：

     1) 纯静态演示：页面只引本文件 -> 直接接管 window.axios（原有行为不变）
     2) 真实后端优先：页面先引 api-client.js（它会置 window.__REAL_API_AVAILABLE），
        再引本文件 -> 本文件只把 mock 挂到 window.__mockAxios 作为「兜底」，
        不覆盖真实 axios；当 api-client.js 的请求遇到网络失败时，会自动
        回退到这里，从而在没有 Flask 后端的场合（file:// 或纯静态服务器）
        仍然可以演示。
  */
  var mockAxios = {
    get: function (url, config) { return request('GET', url, null, config); },
    post: function (url, data, config) { return request('POST', url, data, config); },
    put: function (url, data, config) { return request('PUT', url, data, config); },
    delete: function (url, config) { return request('DELETE', url, null, config); },
  };

  window.__mockAxios = mockAxios;
  if (!window.__REAL_API_AVAILABLE) {
    // 纯静态环境：本文件就是唯一数据源
    window.axios = mockAxios;
  }
})();

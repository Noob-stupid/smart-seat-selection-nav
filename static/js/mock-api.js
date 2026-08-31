/* Pure-frontend mock API for the static build.
   Replaces the Flask backend and keeps every page interactive offline. */
(function () {
  'use strict';

  function normalizePath(path) {
    if (!path || path === '/' || path === '/index') return 'index.html';
    var bare = String(path).split(/[?#]/)[0];
    var map = {
      '/seat-map': 'seat-map.html',
      '/reservation': 'reservation.html',
      '/navigation': 'navigation.html',
      '/profile': 'profile.html',
      '/uploading': 'uploading.html',
      '/admin': 'admin-dashboard.html',
      '/admin/buildings': 'admin-buildings.html',
      '/admin/floor-plan': 'admin-floor-plan.html',
      '/admin/behavior': 'admin-behavior.html',
      '/admin/settings': 'admin-settings.html',
      '/admin/approvals': 'admin-approvals.html',
      '/login': 'login.html',
      '/register': 'register.html'
    };
    if (map[bare]) return map[bare] + String(path).slice(bare.length);
    return String(path);
  }
  window.normalizePath = normalizePath;

  var SEED_BUILDINGS = [
    { id: 1, name: '文化中心', alias: 'WZ', region: '广州市', address: '大学城中心', description: '综合活动场所' },
    { id: 2, name: '图书馆', alias: 'LIB', region: '广州市', address: '东门旁', description: '安静学习空间' },
    { id: 3, name: '教学楼 A', alias: 'A', region: '广州市', address: '南门', description: '公共教室与自习区' }
  ];

  var state = {
    buildings: SEED_BUILDINGS.map(function (b) { return Object.assign({}, b); }),
    floors: [],
    seats: [],
    networks: {},
    reservations: [],
    pendingUsers: [
      { id: 1, name: '新管理员', student_id: '2026001', email: 'new-admin@example.com' },
      { id: 2, name: '林同学', student_id: '2026002', email: 'lin@example.com' }
    ],
    abnormalUsers: [
      {
        user_id: 1,
        user_name: '陈同学',
        student_id: '20240101',
        total_lock_count: 8,
        return_rate: 0.21,
        absence_rate: 0.74,
        dynamic_m: 60,
        dynamic_n: 2,
        lock_history: [
          { start: '2026-08-02 09:20', duration_sec: 780, detections: 13, valid_returns: 2 },
          { start: '2026-08-02 14:05', duration_sec: 640, detections: 11, valid_returns: 3 },
          { start: '2026-08-03 08:40', duration_sec: 720, detections: 12, valid_returns: 2 }
        ]
      }
    ],
    config: {
      lock_m_default: 30,
      lock_n_default: 5,
      lock_t_default: 30,
      lock_m_range: [10, 60],
      lock_n_range: [2, 15],
      lock_t_range: [10, 120],
      ai_weights: [0.35, 0.25, 0.25, 0.15],
      sensor_scan_interval: 15
    },
    currentUser: null,
    mappingTasks: {}
  };

  var STORAGE_KEY = 'seat_app_current_user';
  function persistUser() {
    if (!state.currentUser) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.currentUser)); } catch (e) { }
  }
  function restoreUser() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (raw) state.currentUser = JSON.parse(raw);
    } catch (e) { }
  }
  restoreUser();

  var RESERVATIONS_KEY = 'seat_app_reservations';
  function persistReservations() {
    try { localStorage.setItem(RESERVATIONS_KEY, JSON.stringify(state.reservations || [])); } catch (e) { }
  }
  function restoreReservations() {
    try {
      var raw = localStorage.getItem(RESERVATIONS_KEY);
      if (raw) state.reservations = JSON.parse(raw);
    } catch (e) { }
  }

  var SEATS_KEY = 'seat_app_seats';
  function persistSeats() {
    try { localStorage.setItem(SEATS_KEY, JSON.stringify(state.seats || [])); } catch (e) { }
  }
  function restoreSeats() {
    try {
      var raw = localStorage.getItem(SEATS_KEY);
      if (!raw) return;
      var saved = JSON.parse(raw);
      if (!Array.isArray(saved) || !saved.length) return;
      var savedFloorIds = {};
      saved.forEach(function (s) { savedFloorIds[s.floor_id] = true; });
      state.seats = state.seats.filter(function (s) { return !savedFloorIds[s.floor_id]; });
      saved.forEach(function (s) { state.seats.push(s); });
    } catch (e) { }
  }

  var MAPPING_TASKS_KEY = 'seat_app_mapping_tasks';
  function persistMappingTasks() {
    try { localStorage.setItem(MAPPING_TASKS_KEY, JSON.stringify(state.mappingTasks || {})); } catch (e) { }
  }
  function restoreMappingTasks() {
    try {
      var raw = localStorage.getItem(MAPPING_TASKS_KEY);
      if (raw) state.mappingTasks = JSON.parse(raw);
    } catch (e) { }
  }
  restoreMappingTasks();

  SEED_BUILDINGS.forEach(function (building, bi) {
    var floorCount = [3, 2, 4][bi] || 2;
    for (var f = 1; f <= floorCount; f++) {
      var floorId = building.id * 100 + f;
      state.floors.push({
        id: floorId,
        building_id: building.id,
        floor_number: f,
        name: f + '楼',
        floor_plan_width: 800,
        floor_plan_height: 600,
        floor_plan_path: ''
      });
      var rows = 4;
      var cols = 6 + ((bi + f) % 4);
      var planW = 800;
      var planH = 600;
      var marginX = Math.max(50, Math.round(planW * 0.08));
      var marginY = Math.max(50, Math.round(planH * 0.10));
      var cellW = (planW - marginX * 2) / cols;
      var cellH = (planH - marginY * 2) / rows;
      var n = 0;
      for (var r = 0; r < rows; r++) {
        for (var c = 0; c < cols; c++) {
          n++;
          var mod = n + f + bi;
          var status = 'free';
          if (mod % 7 === 0) status = 'occupied';
          else if (mod % 11 === 0) status = 'locked';
          else if (mod % 13 === 0) status = 'error';
          state.seats.push({
            id: floorId * 100 + n,
            building_id: building.id,
            floor_id: floorId,
            floor_name: f + '楼',
            floor_number: f,
            seat_label: String.fromCharCode(65 + r) + '-' + (c + 1),
            seat_type: c % 4 === 0 ? 'window' : c % 5 === 0 ? 'quiet' : c % 6 === 0 ? 'power' : 'normal',
            status: status,
            x: Math.round(marginX + cellW * (c + 0.5)),
            y: Math.round(marginY + cellH * (r + 0.5)),
            width: 36,
            height: 36,
            ir_front: 1,
            ir_back: 0,
            occupant_name: status === 'occupied' ? '同学' + (n % 9 + 1) : '',
            occupant_avatar: ''
          });
        }
      }
    }
  });

  var APPLIED_PLANS_KEY = 'seat_app_applied_floor_plans';
  try {
    var appliedPlans = JSON.parse(localStorage.getItem(APPLIED_PLANS_KEY) || '{}');
    state.floors.forEach(function (f) {
      var plan = appliedPlans[f.id];
      if (plan && plan.path) {
        f.floor_plan_path = plan.path;
        f.floor_plan_width = plan.width;
        f.floor_plan_height = plan.height;
      }
    });
  } catch (e) { }

  function persistAppliedFloorPlan(floor) {
    try {
      var plans = JSON.parse(localStorage.getItem(APPLIED_PLANS_KEY) || '{}');
      plans[floor.id] = {
        path: floor.floor_plan_path,
        width: floor.floor_plan_width,
        height: floor.floor_plan_height
      };
      localStorage.setItem(APPLIED_PLANS_KEY, JSON.stringify(plans));
    } catch (e) { }
  }

  restoreSeats();

  var firstSeat = state.seats[0];
  state.reservations.push({
    id: 1,
    seat_id: firstSeat.id,
    seat_label: firstSeat.seat_label,
    status: 'pending',
    start_time: '2026-08-03T09:00:00',
    end_time: '2026-08-03T11:00:00'
  });
  restoreReservations();

  function summarizeBuilding(b) {
    var floorIds = state.floors.filter(function (f) { return f.building_id === b.id; }).map(function (f) { return f.id; });
    var buildingSeats = state.seats.filter(function (s) { return floorIds.indexOf(s.floor_id) >= 0; });
    return Object.assign({}, b, {
      total_seats: buildingSeats.length,
      free_seats: buildingSeats.filter(function (s) { return s.status === 'free'; }).length,
      floor_count: floorIds.length
    });
  }

  function buildingDetail(id) {
    var b = state.buildings.find(function (x) { return x.id === id; });
    if (!b) return null;
    var floors = state.floors.filter(function (f) { return f.building_id === id; }).map(function (f) {
      return Object.assign({}, f, {
        seat_count: typeof f.seat_count === 'number' ? f.seat_count : state.seats.filter(function (s) { return s.floor_id === f.id; }).length,
        floor_plan_url: f.floor_plan_path || null
      });
    });
    return Object.assign({}, b, { floors: floors });
  }

  function getNetwork(floorId) {
    if (state.networks[floorId]) return state.networks[floorId];
    var nodes = {};
    var edges = [];
    for (var i = 0; i < 8; i++) {
      nodes['n' + i] = { x: 70 + i * 100, y: 100 + (i % 3) * 90, type: 'normal', name: null };
    }
    for (var e = 0; e < 7; e++) {
      edges.push({ from: 'n' + e, to: 'n' + (e + 1) });
    }
    state.networks[floorId] = { nodes: nodes, edges: edges, floor_info: { width: 800, height: 600 } };
    return state.networks[floorId];
  }

  function nearestNode(floorId, x, y) {
    var net = getNetwork(floorId);
    var ids = Object.keys(net.nodes);
    var best = null;
    var bestDistance = Infinity;
    ids.forEach(function (id) {
      var node = net.nodes[id];
      var d = Math.pow(node.x - x, 2) + Math.pow(node.y - y, 2);
      if (d < bestDistance) {
        bestDistance = d;
        best = id;
      }
    });
    if (!best) return null;
    return { node_id: best, x: net.nodes[best].x, y: net.nodes[best].y };
  }

  function planRoute(data) {
    var fromFloorId = Number(data.from_floor_id || 0);
    var toFloorId = Number(data.to_floor_id || fromFloorId);
    var fromNet = getNetwork(fromFloorId);
    var toNet = getNetwork(toFloorId);
    var fromKeys = Object.keys(fromNet.nodes);
    var toKeys = Object.keys(toNet.nodes);
    if (!fromKeys.length || !toKeys.length) {
      return { error: '当前楼层暂无路网节点，请先在管理后台配置路网' };
    }
    var fromId = String(data.from_node || fromKeys[0]);
    var toId = String(data.to_node || toKeys[0]);
    var fromNode = fromNet.nodes[fromId] || fromNet.nodes[fromKeys[0]];
    var toNode = toNet.nodes[toId] || toNet.nodes[toKeys[0]];
    var path = [{ node_id: fromId, x: fromNode.x, y: fromNode.y }];
    var segments = [];
    var totalDistance = 0;

    if (fromFloorId !== toFloorId) {
      path.push({ node_id: 'stair', x: 400, y: 300 });
      path.push({ node_id: toId, x: toNode.x, y: toNode.y });
      segments.push({ label: fromFloorId + ' 层路径', distance: 96, path: [path[0]] });
      segments.push({ label: '跨层衔接（楼梯/电梯）', distance: 12, path: [path[1]] });
      segments.push({ label: toFloorId + ' 层路径', distance: 72, path: [path[2]] });
      totalDistance = 180;
    } else {
      path.push({ node_id: toId, x: toNode.x, y: toNode.y });
      segments.push({ label: fromFloorId + ' 层路径', distance: 108, path: path });
      totalDistance = 108;
    }
    return {
      path: path,
      segments: segments,
      total_distance: totalDistance,
      cross_floor_hint: fromFloorId !== toFloorId ? '需要从 ' + fromFloorId + ' 层前往 ' + toFloorId + ' 层' : ''
    };
  }

  function response(data, code, message) {
    return { data: { code: code || 200, message: message || 'ok', data: data } };
  }

  function failure(message, status) {
    return Promise.reject({ response: { status: status || 0, data: { message: message || '请求失败' } } });
  }

  function makeMappingLine(x1, y1, x2, y2) {
    return {
      x1: x1, y1: y1, x2: x2, y2: y2,
      angle: Math.round(Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI * 100) / 100,
      length: Math.round(Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2)) * 100) / 100,
      type: 'wall'
    };
  }

  function svgDataUri(svg) {
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  function makeMockMappingTask(taskId, name, mode) {
    var w = 1200, h = 800;
    var safeName = String(name || '').replace(/[<>&]/g, function (c) {
      return { '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c];
    });
    var lines = [
      makeMappingLine(100, 100, 1100, 100),
      makeMappingLine(1100, 100, 1100, 700),
      makeMappingLine(1100, 700, 100, 700),
      makeMappingLine(100, 700, 100, 100),
      makeMappingLine(700, 100, 700, 280),
      makeMappingLine(700, 360, 700, 400),
      makeMappingLine(700, 400, 1100, 400)
    ];
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">';
    svg += '<defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">' +
      '<path d="M40 0H0V40" fill="none" stroke="#e3ddd0" stroke-width="1"/></pattern></defs>';
    svg += '<rect width="' + w + '" height="' + h + '" fill="#f8f5ed"/>';
    svg += '<rect width="' + w + '" height="' + h + '" fill="url(#grid)"/>';
    lines.forEach(function (l) {
      svg += '<line x1="' + l.x1 + '" y1="' + l.y1 + '" x2="' + l.x2 + '" y2="' + l.y2 +
        '" stroke="#4f4a42" stroke-width="12" stroke-linecap="round"/>';
    });
    svg += '<path d="M 700 280 Q 760 320 700 360" fill="none" stroke="#7a7264" stroke-width="3" stroke-dasharray="6 5"/>';
    svg += '<text x="180" y="180" font-family="Microsoft YaHei, sans-serif" font-size="26" fill="#57503f">' +
      safeName + '</text>';
    svg += '<text x="180" y="220" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#8b8472">' +
      '自动建图演示 · ' + mode + '</text>';
    svg += '<text x="760" y="180" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#8b8472">识别墙线 ' +
      lines.length + ' 条</text>';
    svg += '</svg>';
    return {
      task_id: taskId,
      room: { id: taskId, name: name, mode: 'phone_capture' },
      image: { width: w, height: h, url: svgDataUri(svg) },
      lines: lines,
      unit: 'pixel',
      line_count: lines.length
    };
  }

  function makeMockUploadImage(fileName) {
    var w = 800, h = 600;
    var label = String(fileName || '手动上传平面图').replace(/[<>&]/g, function (c) {
      return { '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c];
    });
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">';
    svg += '<defs><pattern id="grid2" width="40" height="40" patternUnits="userSpaceOnUse">' +
      '<path d="M40 0H0V40" fill="none" stroke="#e3ddd0" stroke-width="1"/></pattern></defs>';
    svg += '<rect width="' + w + '" height="' + h + '" fill="#f8f5ed"/>';
    svg += '<rect width="' + w + '" height="' + h + '" fill="url(#grid2)"/>';
    svg += '<rect x="60" y="60" width="680" height="480" fill="none" stroke="#4f4a42" stroke-width="10"/>';
    svg += '<line x1="320" y1="60" x2="320" y2="380" stroke="#4f4a42" stroke-width="8"/>';
    svg += '<line x1="320" y1="380" x2="740" y2="380" stroke="#4f4a42" stroke-width="8"/>';
    svg += '<path d="M 320 210 Q 370 240 320 270" fill="none" stroke="#7a7264" stroke-width="3" stroke-dasharray="6 5"/>';
    svg += '<text x="110" y="130" font-family="Microsoft YaHei, sans-serif" font-size="22" fill="#57503f">' + label + '</text>';
    svg += '<text x="110" y="165" font-family="Microsoft YaHei, sans-serif" font-size="16" fill="#8b8472">手动上传演示平面图</text>';
    svg += '</svg>';
    return { file_path: svgDataUri(svg), image_info: { width: w, height: h } };
  }

  function makeSeatGrid(floor) {
    var rows = Math.max(3, Math.round(floor.floor_plan_height / 130));
    var cols = Math.max(4, Math.round(floor.floor_plan_width / 130));
    var marginX = Math.max(40, Math.round(floor.floor_plan_width * 0.08));
    var marginY = Math.max(40, Math.round(floor.floor_plan_height * 0.10));
    var cellW = (floor.floor_plan_width - marginX * 2) / cols;
    var cellH = (floor.floor_plan_height - marginY * 2) / rows;
    var seats = [];
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        seats.push({
          seat_label: String.fromCharCode(65 + r) + '-' + (c + 1),
          seat_type: c % 4 === 0 ? 'window' : c % 5 === 0 ? 'quiet' : c % 6 === 0 ? 'power' : 'normal',
          status: 'free',
          x: Math.round(marginX + cellW * (c + 0.5)),
          y: Math.round(marginY + cellH * (r + 0.5)),
          width: 36,
          height: 36,
          ir_front: 1,
          ir_back: 0,
          occupant_name: '',
          occupant_avatar: ''
        });
      }
    }
    return seats;
  }

  function replaceFloorSeats(floor, items) {
    state.seats = state.seats.filter(function (s) { return s.floor_id !== floor.id; });
    items.forEach(function (item, i) {
      state.seats.push(Object.assign({
        id: floor.id * 1000 + i + 1,
        building_id: floor.building_id,
        floor_id: floor.id,
        floor_name: floor.name,
        floor_number: floor.floor_number
      }, item));
    });
    persistSeats();
    return items.length;
  }

  function rescaleFloorSeats(floor, oldW, oldH) {
    var nw = floor.floor_plan_width, nh = floor.floor_plan_height;
    if (!oldW || !oldH || !nw || !nh) return;
    state.seats.forEach(function (s) {
      if (s.floor_id !== floor.id) return;
      s.x = Math.round(s.x * nw / oldW);
      s.y = Math.round(s.y * nh / oldH);
    });
    persistSeats();
  }

  function syncFloorSeatsWithImage(floor, oldW, oldH) {
    var existing = state.seats.filter(function (s) { return s.floor_id === floor.id; });
    if (existing.length) {
      rescaleFloorSeats(floor, oldW, oldH);
      return existing.length;
    }
    return replaceFloorSeats(floor, makeSeatGrid(floor));
  }

  function countSeats(list) {
    var counts = { total: list.length, free: 0, occupied: 0, locked: 0, error: 0 };
    list.forEach(function (s) {
      if (counts[s.status] !== undefined) counts[s.status]++;
    });
    return counts;
  }

  function statusText(status) {
    var map = { pending: '待签到', checked_in: '已签到', completed: '已完成', cancelled: '已取消', no_show: '未签到' };
    return map[status] || status;
  }

  function handle(method, url, data, params) {
    var path = String(url).split('?')[0];

    if (method === 'GET' && path === '/api/regions') {
      var regions = {};
      state.buildings.forEach(function (b) {
        var region = b.region || '其他';
        regions[region] = (regions[region] || 0) + 1;
      });
      return response(Object.keys(regions).map(function (name) { return { name: name, count: regions[name] }; }));
    }

    if (method === 'GET' && path === '/api/search/venues') {
      var q = String((params && params.q) || '').toLowerCase();
      var matched = state.buildings.filter(function (b) {
        return [b.name, b.alias || '', b.region || '', b.address || ''].join(' ').toLowerCase().indexOf(q) >= 0;
      });
      return response(matched.map(summarizeBuilding));
    }

    if (method === 'GET' && path === '/api/buildings') {
      var list = state.buildings.map(summarizeBuilding);
      if (params && params.region) list = list.filter(function (b) { return b.region === params.region; });
      return response(list);
    }

    if (method === 'GET' && path === '/api/status') {
      return response(countSeats(state.seats));
    }

    if (method === 'GET' && path === '/api/seats') {
      var seatList = state.seats.slice();
      if (params && params.floor_id) seatList = seatList.filter(function (s) { return s.floor_id === Number(params.floor_id); });
      if (params && params.building_id) seatList = seatList.filter(function (s) { return s.building_id === Number(params.building_id); });
      if (params && params.status) seatList = seatList.filter(function (s) { return s.status === params.status; });
      return response(seatList);
    }

    if (method === 'GET' && path === '/api/recommend') {
      var recs = state.seats.filter(function (s) {
        return s.floor_id === Number(params.floor_id) && s.status === 'free';
      }).slice(0, 5);
      return response(recs);
    }

    var buildingMatch = path.match(/^\/api\/buildings\/(\d+)$/);
    if (buildingMatch) {
      var bid = Number(buildingMatch[1]);
      if (method === 'GET') {
        var detail = buildingDetail(bid);
        return detail ? response(detail) : failure('场所不存在');
      }
      if (method === 'PUT') {
        var target = state.buildings.find(function (b) { return b.id === bid; });
        if (!target) return failure('场所不存在');
        Object.assign(target, data);
        return response(target);
      }
      if (method === 'DELETE') {
        state.buildings = state.buildings.filter(function (b) { return b.id !== bid; });
        state.floors = state.floors.filter(function (f) { return f.building_id !== bid; });
        state.seats = state.seats.filter(function (s) { return s.building_id !== bid; });
        return response({ id: bid });
      }
    }

    var createFloorMatch = path.match(/^\/api\/buildings\/(\d+)\/floors$/);
    if (createFloorMatch && method === 'POST') {
      var building = state.buildings.find(function (b) { return b.id === Number(createFloorMatch[1]); });
      if (!building) return failure('场所不存在');
      var floorNumber = Number(data.floor_number || 1);
      var existingFloor = state.floors.find(function (f) { return f.building_id === building.id && f.floor_number === floorNumber; });
      if (existingFloor) return failure('该楼层已存在');
      var floorId = building.id * 100 + floorNumber;
      var manualSeatCount = (data.seat_count === undefined || data.seat_count === null || data.seat_count === '') ? null : Math.max(0, Math.floor(Number(data.seat_count) || 0));
      state.floors.push({
        id: floorId,
        building_id: building.id,
        floor_number: floorNumber,
        name: data.name || floorNumber + '楼',
        seat_count: manualSeatCount,
        floor_plan_width: 800,
        floor_plan_height: 600,
        floor_plan_path: ''
      });
      return response({ id: floorId }, 201, '楼层创建成功');
    }

    var floorMatch = path.match(/^\/api\/floors\/(\d+)$/);
    if (floorMatch) {
      var fid = Number(floorMatch[1]);
      var floor = state.floors.find(function (f) { return f.id === fid; });
      if (method === 'GET') {
        if (!floor) return failure('楼层不存在');
        return response(Object.assign({}, floor, {
          seats: state.seats.filter(function (s) { return s.floor_id === fid; }),
          floor_plan_url: floor.floor_plan_path || null
        }));
      }
      if (method === 'PUT' && floor) {
        var oldPlanW = floor.floor_plan_width;
        var oldPlanH = floor.floor_plan_height;
        Object.assign(floor, data);
        if (data.floor_plan_path && data.floor_plan_width && data.floor_plan_height) {
          persistAppliedFloorPlan(floor);
          syncFloorSeatsWithImage(floor, oldPlanW, oldPlanH);
        }
        return response(floor);
      }
      if (method === 'DELETE' && floor) {
        state.floors = state.floors.filter(function (f) { return f.id !== fid; });
        state.seats = state.seats.filter(function (s) { return s.floor_id !== fid; });
        return response({ id: fid });
      }
    }

    var createSeatsMatch = path.match(/^\/api\/floors\/(\d+)\/seats$/);
    if (createSeatsMatch && method === 'POST') {
      var targetFloorId = Number(createSeatsMatch[1]);
      var items = Array.isArray(data) ? data : [data];
      var newIds = [];
      items.forEach(function (item, index) {
        var nextId = targetFloorId * 1000 + state.seats.length + index + 1;
        newIds.push(nextId);
        state.seats.push(Object.assign({
          id: nextId,
          building_id: 0,
          floor_id: targetFloorId,
          floor_name: '',
          floor_number: 0,
          seat_label: item.seat_label || '新座位',
          seat_type: item.seat_type || 'normal',
          status: 'free',
          x: item.x || 100,
          y: item.y || 100,
          width: 36,
          height: 36,
          ir_front: 1,
          ir_back: 0,
          occupant_name: '',
          occupant_avatar: ''
        }, item));
      });
      persistSeats();
      return response({ ids: newIds }, 201, '座位添加成功');
    }

    var seatMatch = path.match(/^\/api\/seats\/(\d+)$/);
    if (seatMatch) {
      var seatId = Number(seatMatch[1]);
      var seat = state.seats.find(function (s) { return s.id === seatId; });
      if (method === 'PUT' && seat) {
        Object.assign(seat, data);
        persistSeats();
        return response(seat);
      }
      if (method === 'DELETE' && seat) {
        state.seats = state.seats.filter(function (s) { return s.id !== seatId; });
        persistSeats();
        return response({ id: seatId });
      }
    }

    if (path === '/api/auth/login' && method === 'POST') {
      var account = String(data.student_id || '').trim();
      var password = String(data.password || '');
      if (!account || !password) return failure('账号或密码不能为空');
      var isAdmin = account === 'admin' || account === '管理员';
      state.currentUser = {
        id: Date.now(),
        student_id: account,
        name: isAdmin ? '演示管理员' : account,
        role: isAdmin ? 'admin' : 'student',
        email: account.indexOf('@') >= 0 ? account : 'demo@example.com',
        phone: '',
        avatar_url: '',
        preferences: { tags: ['安静学习', '靠窗座位'] }
      };
      persistUser();
      return response(state.currentUser, 200, '登录成功');
    }

    if (path === '/api/auth/register' && method === 'POST') {
      if (String(data.password || '') !== String(data.confirm_password || '')) {
        return failure('两次输入的密码不一致');
      }
      state.currentUser = {
        id: Date.now(),
        student_id: data.student_id,
        name: data.name,
        role: data.role === 'admin' ? 'admin' : 'student',
        email: '',
        phone: '',
        avatar_url: '',
        preferences: { tags: [] }
      };
      persistUser();
      return response(state.currentUser, 201, '注册成功');
    }

    if (path === '/api/auth/me' && method === 'GET') {
      if (!state.currentUser) {
        state.currentUser = {
          id: 0,
          student_id: 'demo',
          name: '演示用户',
          role: 'admin',
          email: 'demo@example.com',
          phone: '',
          avatar_url: '',
          preferences: { tags: ['安静学习'] }
        };
      }
      return response(state.currentUser);
    }

    if (path === '/api/profile' && method === 'PUT') {
      state.currentUser = Object.assign({}, state.currentUser || {}, data);
      persistUser();
      return response(state.currentUser);
    }

    if (path === '/api/profile/password' && method === 'PUT') {
      return response({ message: '密码已修改' });
    }

    if (path === '/api/profile/avatar' && method === 'POST') {
      var avatarFile = data && data.get ? data.get('avatar') : null;
      if (avatarFile && typeof FileReader !== 'undefined') {
        return new Promise(function (resolve) {
          var reader = new FileReader();
          reader.onload = function () {
            var avatarUrl = reader.result;
            if (state.currentUser) state.currentUser.avatar_url = avatarUrl;
            persistUser();
            resolve(response({ avatar_url: avatarUrl }));
          };
          reader.onerror = function () {
            resolve(failure('头像文件读取失败'));
          };
          reader.readAsDataURL(avatarFile);
        });
      }
      var avatarSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160">' +
  '<rect width="160" height="160" rx="80" fill="#2f7068"/>' +
        '<text x="80" y="104" font-size="58" text-anchor="middle" fill="#fff">用户</text></svg>';
      var fallbackUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(avatarSvg);
      if (state.currentUser) state.currentUser.avatar_url = fallbackUrl;
      persistUser();
      return response({ avatar_url: fallbackUrl });
    }

    if (path === '/api/upload' && method === 'POST') {
      var fileName = data && data.get ? (data.get('file') && data.get('file').name) || 'floor.png' : 'floor.png';
      var uploadImage = makeMockUploadImage(fileName);
      return response(uploadImage, 201, '上传成功');
    }

    if (path === '/api/reservations') {
      if (method === 'GET') {
        return response(state.reservations.map(function (r) {
          return Object.assign({}, r, { status_text: statusText(r.status) });
        }));
      }
      if (method === 'POST') {
        var target = state.seats.find(function (s) { return s.id === Number(data.seat_id); });
        if (!target) return failure('座位不存在');
        target.status = 'locked';
        var rid = Date.now();
        state.reservations.unshift({
          id: rid,
          seat_id: target.id,
          seat_label: target.seat_label,
          status: 'pending',
          start_time: data.start_time || new Date().toISOString(),
          end_time: data.end_time || new Date(Date.now() + 7200000).toISOString()
        });
        persistReservations();
        return response({ id: rid }, 201, '预约成功');
      }
    }

    var cancelMatch = path.match(/^\/api\/reservations\/(\d+)\/cancel$/);
    if (cancelMatch && method === 'POST') {
      var reservation = state.reservations.find(function (r) { return r.id === Number(cancelMatch[1]); });
      if (reservation) {
        reservation.status = 'cancelled';
        var seatToFree = state.seats.find(function (s) { return s.id === reservation.seat_id; });
        if (seatToFree) seatToFree.status = 'free';
      }
      persistReservations();
      return response({ id: Number(cancelMatch[1]) });
    }

    if (path === '/api/admin/pending-users' && method === 'GET') {
      return response(state.pendingUsers);
    }

    var approveMatch = path.match(/^\/api\/admin\/approve\/(\d+)$/);
    if (approveMatch && method === 'POST') {
      state.pendingUsers = state.pendingUsers.filter(function (u) { return u.id !== Number(approveMatch[1]); });
      return response({ id: Number(approveMatch[1]) });
    }

    var rejectMatch = path.match(/^\/api\/admin\/reject\/(\d+)$/);
    if (rejectMatch && method === 'POST') {
      state.pendingUsers = state.pendingUsers.filter(function (u) { return u.id !== Number(rejectMatch[1]); });
      return response({ id: Number(rejectMatch[1]) });
    }

    if (path === '/api/admin/abnormal-users' && method === 'GET') {
      return response(state.abnormalUsers);
    }

    if (path === '/api/admin/simulator/start' && method === 'POST') {
      return response({ message: '模拟器已启动' });
    }

    if (path === '/api/admin/simulator/stop' && method === 'POST') {
      return response({ message: '模拟器已停止' });
    }

    if (path === '/api/admin/config') {
      if (method === 'GET') return response(state.config);
      if (method === 'PUT') {
        Object.assign(state.config, data);
        return response(state.config);
      }
    }

    if (path === '/api/admin/weights' && method === 'PUT') {
      state.config.ai_weights = data.weights;
      return response(state.config);
    }

    var networkGetMatch = path.match(/^\/api\/admin\/network\/(\d+)$/);
    if (networkGetMatch && method === 'GET') {
      return response(getNetwork(Number(networkGetMatch[1])));
    }

    if (path === '/api/admin/network/save-manual' && method === 'POST') {
      state.networks[Number(data.floor_id)] = data.network;
      return response({ saved: true });
    }

    if (path === '/api/admin/network/generate' && method === 'POST') {
      var generated = getNetwork(Number(data.floor_id));
      return response({ network: generated });
    }

    if (path === '/api/navigation/locate' && method === 'POST') {
      var locateFloorId = Number(data.floor_id || 0);
      if (data.type === 'qr' || data.node_id) {
        var locateNet = getNetwork(locateFloorId);
        var targetNode = locateNet.nodes[String(data.node_id)];
        if (!targetNode) return failure('节点不存在');
        return response({ node_id: String(data.node_id), x: targetNode.x, y: targetNode.y });
      }
      var located = nearestNode(locateFloorId, Number(data.click_x || 0), Number(data.click_y || 0));
      if (!located) return failure('该楼层暂无路网节点');
      return response(located);
    }

    if (path === '/api/navigation/plan' && method === 'POST') {
      return response(planRoute(data));
    }

    if (path === '/api/admin/mapping/tasks' && method === 'POST') {
      var mapFiles = data && data.getAll ? (data.getAll('file') || []) : [];
      if (!mapFiles.length) {
        var singleFile = data && data.get ? data.get('file') : null;
        if (singleFile) mapFiles = [singleFile];
      }
      if (!mapFiles.length) return failure('未收到视频或图片素材', 400);
      var roomName = String((data && data.get && data.get('name')) || '自动建模房间');
      var mode = String((data && data.get && data.get('mode')) || 'images');
      var taskId = 'room_' + Math.random().toString(16).slice(2, 10);
      var task = makeMockMappingTask(taskId, roomName, mode === 'video' ? '视频' : '图片组');
      return new Promise(function (resolve) {
        setTimeout(function () {
          state.mappingTasks[taskId] = task;
          persistMappingTasks();
          resolve(response(task, 201, '建图成功'));
        }, 2800);
      });
    }

    var mappingGetMatch = path.match(/^\/api\/admin\/mapping\/tasks\/([\w-]+)$/);
    if (mappingGetMatch && method === 'GET') {
      var task = state.mappingTasks[mappingGetMatch[1]];
      if (!task) return failure('任务不存在或已清理', 404);
      return response(task);
    }

    var mappingApplyMatch = path.match(/^\/api\/admin\/mapping\/tasks\/([\w-]+)\/apply$/);
    if (mappingApplyMatch && method === 'POST') {
      var taskToApply = state.mappingTasks[mappingApplyMatch[1]];
      if (!taskToApply) return failure('任务不存在或已清理', 404);
      var floorId = Number(data && data.floor_id);
      var floor = state.floors.find(function (f) { return f.id === floorId; });
      if (!floor) return failure('楼层不存在', 404);
      var oldPlanW = floor.floor_plan_width;
      var oldPlanH = floor.floor_plan_height;
      floor.floor_plan_path = taskToApply.image.url;
      floor.floor_plan_width = taskToApply.image.width;
      floor.floor_plan_height = taskToApply.image.height;
      persistAppliedFloorPlan(floor);
      syncFloorSeatsWithImage(floor, oldPlanW, oldPlanH);
      return response({ floor_id: floorId, task_id: taskToApply.task_id }, 200, '已应用到楼层');
    }

    var relayoutMatch = path.match(/^\/api\/admin\/floors\/(\d+)\/relayout-seats$/);
    if (relayoutMatch && method === 'POST') {
      var relayoutFloor = state.floors.find(function (f) { return f.id === Number(relayoutMatch[1]); });
      if (!relayoutFloor) return failure('楼层不存在', 404);
      var count = replaceFloorSeats(relayoutFloor, makeSeatGrid(relayoutFloor));
      return response({ floor_id: relayoutFloor.id, count: count }, 200, '座位已按图片重排');
    }

    if (path === '/api/buildings' && method === 'POST') {
      var nextId = state.buildings.reduce(function (max, b) { return Math.max(max, b.id); }, 0) + 1;
      var created = Object.assign({ id: nextId }, data);
      state.buildings.push(created);
      return response(created, 201, '添加成功');
    }

    return failure('演示环境不支持该接口: ' + method + ' ' + path);
  }

  window.axios = {
    get: function (url, config) { return Promise.resolve(handle('GET', url, null, config && config.params)); },
    post: function (url, data) { return Promise.resolve(handle('POST', url, data)); },
    put: function (url, data) { return Promise.resolve(handle('PUT', url, data)); },
    delete: function (url) { return Promise.resolve(handle('DELETE', url)); }
  };
})();

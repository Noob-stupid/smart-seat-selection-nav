/* 硬件 / 传感器调试面板 Vue 应用 */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      sim: { config: {}, simulator_running: false, seats: [] },
      cfg: { sensor_scan_interval: 30, seat_offline_hours: 24, seat_sweep_interval_minutes: 30 },
      devices: [],          // 设备管理列表
      seats: [],            // 座位（用于绑定下拉）
      knownIds: {},         // 已见设备 id（用于“新设备注册”提示）
      _loadedOnce: false,
      timer: null,
      // 「建筑 → 楼层」折叠状态。key 用 'b<id>' / 'b<id>-f<id>'，
      // 空对象 = 全部收起（一进页面就摊开几十上百个座位是没法看的）。
      openGroups: {},
      // 产线烧录配置（生成 secrets.h 用）
      prod: { wifi_ssid: '', wifi_pass: '', wifi_pass_set: false,
              wifi_pass_masked: '', server_url: 'https://zhinengzuo.site' },
    };
  },
  computed: {
    /* 座位传感器状态按「建筑 → 楼层」两级分组。
     *
     * 原来是一张平铺表，一层楼 192 个座位全列出来，翻到某个座位得滚半天，
     * 而且分不清哪几个是同一个楼层的。这里按 building_id / floor_id 切组
     * （有 id 就不用名字，同名楼层不会串），组标题带在线/离线统计。
     * 注意：分组只包壳，不能 clone 座位对象 —— 行里的「接收上报」开关和
     * 「手动模拟上报」下拉都是 v-model 绑在座位对象上的，一 clone 就点不动了。
     */
    seatGroups() {
      const seats = (this.sim && this.sim.seats) || [];
      const buildings = {};
      seats.forEach((s) => {
        const bKey = 'b' + (s.building_id != null ? s.building_id
          : (s.building_name || 'none'));
        if (!buildings[bKey]) {
          buildings[bKey] = {
            key: bKey,
            name: s.building_name || '未分配场所',
            total: 0, online: 0, offline: 0, simulated: 0, floorMap: {},
          };
        }
        const b = buildings[bKey];
        const fKey = bKey + '-f' + (s.floor_id != null ? s.floor_id
          : (s.floor_name || 'x'));
        if (!b.floorMap[fKey]) {
          b.floorMap[fKey] = {
            key: fKey,
            name: s.floor_name || '未命名楼层',
            number: s.floor_number == null ? 0 : s.floor_number,
            total: 0, online: 0, offline: 0, simulated: 0, seats: [],
          };
        }
        const f = b.floorMap[fKey];
        f.seats.push(s);
        [b, f].forEach((g) => {
          g.total += 1;
          if (s.online) { g.online += 1; } else { g.offline += 1; }
          if (s.simulated) g.simulated += 1;
        });
      });
      return Object.keys(buildings).map((k) => {
        const b = buildings[k];
        b.floors = Object.keys(b.floorMap)
          .map((fk) => b.floorMap[fk])
          .sort((x, y) => (x.number - y.number) || x.name.localeCompare(y.name));
        b.floors.forEach((f) => {
          f.seats.sort((x, y) => String(x.seat_label).localeCompare(String(y.seat_label)));
        });
        delete b.floorMap;
        return b;
      }).sort((x, y) => x.name.localeCompare(y.name));
    },
  },
  mounted() {
    this.load();
    this.loadProd();
    this.timer = setInterval(() => this.load(), 3000);
  },
  beforeUnmount() {
    if (this.timer) clearInterval(this.timer);
  },
  methods: {
    /* ---------- 产线烧录配置 ---------- */
    async loadProd() {
      try {
        const res = await api.get('/api/admin/config');
        const d = res.data || {};
        this.prod.wifi_ssid = d.prod_wifi_ssid || '';
        this.prod.wifi_pass_set = !!d.prod_wifi_pass_set;
        this.prod.wifi_pass_masked = d.prod_wifi_pass_masked || '';
        this.prod.server_url = d.prod_server_url || 'https://zhinengzuo.site';
        this.prod.wifi_pass = '';        // 密码永不回显明文，留空 = 不修改
      } catch (e) {
        console.warn('[产线配置] 读取失败', e);
      }
    },

    async saveProd() {
      const body = {
        prod_wifi_ssid: this.prod.wifi_ssid || '',
        prod_server_url: this.prod.server_url || '',
      };
      // 密码留空 = 不修改（后端约定）
      if (this.prod.wifi_pass) body.prod_wifi_pass = this.prod.wifi_pass;
      try {
        await api.put('/api/admin/config', body);
        this.prod.wifi_pass = '';
        await this.loadProd();
        alert('产线配置已保存');
      } catch (e) {
        alert('保存失败：' + ((e.response && e.response.data && e.response.data.message) || e.message));
      }
    },

    downloadSecrets() {
      // 用 a[download] 触发下载；接口带 admin 鉴权，浏览器会带上 cookie
      const a = document.createElement('a');
      a.href = '/api/admin/production/secrets.h';
      a.download = 'secrets.h';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    },

    async load() {
      try {
        // 1) 面板总览（全局参数 + 座位传感器状态）
        const res = await api.get('/api/admin/sensor/overview');
        this.sim = res.data || {};
        this.seats = this.sim.seats || [];
        this.cfg = Object.assign({}, this.cfg, res.data.config || {});
        (this.sim.seats || []).forEach((s) => {
          if (s._combo === undefined) s._combo = 3;   // 默认“有人 (1,1)”
        });
        // 2) 设备管理列表 + 新设备注册提示
        const dRes = await api.get('/api/admin/sensor/devices');
        this.devices = (dRes.data && dRes.data.devices) || [];
        this.devices.forEach((d) => {
          if (d._highStr === undefined) d._highStr = String(d.ir_active_high);
          if (d._sensorType === undefined) d._sensorType = d.sensor_type || 'pir';
          if (d.distance_threshold_cm === undefined) d.distance_threshold_cm = d.distance_threshold_cm || 50;
          if (!(d.id in this.knownIds)) {
            this.knownIds[d.id] = true;
            if (this._loadedOnce && d.is_new) {
              showToast('🆕 新 ESP32（' + d.device_id + '）已注册成功', 'success');
            }
          }
        });
        this._loadedOnce = true;
      } catch (e) { console.error(e); }
    },
    async startSim() {
      try {
        await api.post('/api/admin/simulator/start', { seat_count: 50 });
        showToast('模拟器已启动');
        this.load();
      } catch (e) { this.load(); }
    },
    async stopSim() {
      try {
        await api.post('/api/admin/simulator/stop');
        showToast('模拟器已停止');
        this.load();
      } catch (e) { this.load(); }
    },
    async saveConfig() {
      try {
        await api.put('/api/admin/config', {
          sensor_scan_interval: this.cfg.sensor_scan_interval,
          seat_offline_hours: this.cfg.seat_offline_hours,
          seat_sweep_interval_minutes: this.cfg.seat_sweep_interval_minutes,
        });
        showToast('全局参数已保存');
        this.load();
      } catch (e) { this.load(); }
    },
    async saveDevice(d) {
      try {
        await api.put('/api/admin/sensor/devices/' + d.id, {
          seat_id: d.seat_id || null,
          sensor_type: d._sensorType,
          ir_active_high: d._highStr === 'true',
          distance_threshold_cm: d.distance_threshold_cm,
          report_interval_ms: d.report_interval_ms,
        });
        showToast('设备 ' + d.device_id + ' 配置已保存（设备拉取后生效）');
        this.load();
      } catch (e) { this.load(); }
    },
    /* ---------- 分组折叠 ---------- */
    toggleGroup(key) {
      // 整体换一个新对象再赋值：直接改 this.openGroups[key] 在 Vue 3 里
      // 也是响应式的，但新增键这条路径历史上踩过「点了没反应」，换引用最稳。
      const next = Object.assign({}, this.openGroups);
      next[key] = !next[key];
      this.openGroups = next;
    },
    /* 组标题上的统计：「192 个座位，在线 0 / 离线 192」。
       模拟上报的座位不算在线，单独点出来 —— 否则运维会以为
       「明明显示有数据，怎么全离线」，反而更困惑。 */
    groupSummary(g) {
      let s = g.total + ' 个座位，在线 ' + g.online + ' / 离线 ' + g.offline;
      if (g.simulated) {
        s += '，其中 ' + g.simulated + ' 个是模拟上报（不算在线）';
      }
      return s;
    },
    async toggleEnabled(s) {
      const next = !s.ir_enabled;
      try {
        await api.put('/api/seats/' + s.id, { ir_enabled: next });
        showToast(s.seat_label + (next ? ' 已开启接收上报' : ' 已关闭接收上报'));
        this.load();
      } catch (e) { this.load(); }
    },
    async testReport(s) {
      const c = s._combo;
      const ir_front = (c === 1 || c === 3) ? 1 : 0;
      const ir_back = (c === 2 || c === 3) ? 1 : 0;
      try {
        await api.post('/api/sensor/report', { seat_id: s.id, ir_front, ir_back });
        showToast(s.seat_label + ' 已上报 ir=(' + ir_front + ',' + ir_back + ')');
        this.load();
      } catch (e) { this.load(); }
    },
    statusText(st) {
      return { free: '空闲', occupied: '占用', locked: '锁定', error: '异常' }[st] || st;
    },
    statusStyle(st) {
      return {
        free: 'color:#1e7e34;font-weight:600;',
        occupied: 'color:#d93025;font-weight:600;',
        locked: 'color:#e37400;font-weight:600;',
        error: 'color:#5f6368;font-weight:600;',
      }[st] || '';
    },
    irStyle(v) {
      return v === 1 ? 'background:#fce8e6;color:#d93025;padding:2px 6px;border-radius:4px;'
                     : 'background:#f1f3f4;color:#9aa0a6;padding:2px 6px;border-radius:4px;';
    },
    fmtTime(t) {
      if (!t) return '-';
      // ⚠️ 后端存的是 UTC（datetime.utcnow()），返回的 ISO 串不带时区标记。
      //    直接 new Date('2026-11-01T09:35:28') 会被 JS 当成「本地时间」解析，
      //    于是北京时间 17:35 的数据显示成 09:35 —— 整整差 8 小时。
      //    这里给无时区的串补一个 Z，明确它是 UTC，再由浏览器转成本地时区。
      const s = /([zZ]|[+-]\d{2}:?\d{2})$/.test(t) ? t : t + 'Z';
      const d = new Date(s);
      if (isNaN(d.getTime())) return t;
      return d.toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
    },
  },
}).mount('#app');

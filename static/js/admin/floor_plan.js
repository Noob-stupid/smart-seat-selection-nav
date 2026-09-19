/* 平面图与路网配置页面 Vue 应用 - 手动绘制路线模式 */
const { createApp } = Vue;

const initScript = document.getElementById('init-data');
const initData = initScript ? JSON.parse(initScript.textContent) : {};

try {
  var queryParams = new URLSearchParams(location.search);
  if (queryParams.has('building_id')) initData.buildingId = Number(queryParams.get('building_id'));
  if (queryParams.has('floor_id')) initData.floorId = Number(queryParams.get('floor_id'));
} catch (e) {}

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      buildings: [], floors: [], seats: [],
      buildingId: initData.buildingId || null,
      floorId: initData.floorId || null,
      networkData: null,
      generating: false,
      newSeatLabel: '', newSeatX: 0, newSeatY: 0, newSeatType: 'normal',
      editingSeatId: null,
      floorPlanUrl: null,
    deletingPlan: false,
      floorPlanWidth: 800,
      floorPlanHeight: 600,
      draggingSeat: null,
      draggingNode: null,
      dragOffsetX: 0,
      dragOffsetY: 0,
      selectedSeatIds: [],
      // 模式: 'seat'=添加座位  'path'=绘制路线  'edit'=编辑路网
      drawMode: 'seat',
      // 手动绘制的路线数据
      drawnNodes: {},
      drawnEdges: [],
      nextNodeId: 0,
      selectedNode: null,
      connectingFrom: null,
      lastNodeId: null,
    };
  },
  computed: {
    displayNodes() {
      if (this.drawMode === 'path') return this.drawnNodes;
      return this.networkData?.nodes || {};
    },
    displayEdges() {
      if (this.drawMode === 'path') return this.drawnEdges;
      return this.networkData?.edges || [];
    },
  },
  created() { this.loadBuildings(); },
  methods: {
    /* 删除本楼层的平面图（连同由它生成的路网；楼层与座位保留） */
    deleteFloorPlan: async function () {
      if (!confirm('确定删除该楼层的平面图吗？\n\n'
                 + '· 平面图文件会被删除\n'
                 + '· 由它自动生成的路网也会一并清除（坐标会错位）\n'
                 + '· 楼层与座位数据保留\n\n'
                 + '删完可以重新上传。')) return;
      this.deletingPlan = true;
      try {
        const res = await api.delete('/api/floors/' + this.floorId + '/plan');
        showToast((res && res.message) || '平面图已删除');
        this.floorPlanUrl = null;
        this.networkData = null;
        this.drawnNodes = {};
        this.drawnEdges = [];
        await this.onFloorChange();
      } catch (e) { /* api 层已提示 */ }
      finally { this.deletingPlan = false; }
    },

    async loadBuildings() {
      const res = await api.get('/api/buildings');
      this.buildings = res.data || [];
      if (this.buildingId) this.onBuildingChange();
    },
    async onBuildingChange() {
      this.floors = []; this.floorId = null; this.seats = []; this.networkData = null;
      this.floorPlanUrl = null; this.resetDraw();
      if (!this.buildingId) return;
      const res = await api.get(`/api/buildings/${this.buildingId}`);
      this.floors = res.data?.floors || [];
      if (this.floors.length && !this.floorId) this.floorId = this.floors[0].id;
      if (this.floorId) await this.onFloorChange();
    },
    async onFloorChange() {
      if (!this.floorId) return;
      // 保留当前绘制数据（如果是绘制模式）
      const keepDraw = this.drawMode === 'path' && Object.keys(this.drawnNodes).length > 0;
      const oldDrawn = keepDraw ? { nodes: JSON.parse(JSON.stringify(this.drawnNodes)), edges: JSON.parse(JSON.stringify(this.drawnEdges)), nextId: this.nextNodeId } : null;

      this.seats = []; this.networkData = null; this.floorPlanUrl = null;
      if (!keepDraw) this.resetDraw();

      const res = await api.get(`/api/floors/${this.floorId}`);
      this.seats = res.data?.seats || [];
      this.floorPlanUrl = res.data?.floor_plan_url || null;
      this.floorPlanWidth = res.data?.floor_plan_width || 800;
      this.floorPlanHeight = res.data?.floor_plan_height || 600;
      // 加载座位后自动生成下一个默认编号（往下排，无需手写）
      this.updateDefaultSeatLabel();
      try {
        const netRes = await api.get(`/api/admin/network/${this.floorId}`);
        this.networkData = netRes.data;
      } catch (e) { }

      // 恢复绘制数据（优先使用当前绘制的，因为是最新的）
      if (keepDraw && oldDrawn) {
        this.drawnNodes = oldDrawn.nodes;
        this.drawnEdges = oldDrawn.edges;
        this.nextNodeId = oldDrawn.nextId;
      } else if (this.drawMode === 'path') {
        // 从已保存路网加载（只取通道节点）
        const src = this.networkData || { nodes: {}, edges: [] };
        this.drawnNodes = {};
        for (const [k, v] of Object.entries(src.nodes)) {
          if (v.type !== 'seat') this.drawnNodes[k] = JSON.parse(JSON.stringify(v));
        }
        this.drawnEdges = (src.edges || []).filter(e => this.drawnNodes[e.from] && this.drawnNodes[e.to]);
        this.drawnEdges = JSON.parse(JSON.stringify(this.drawnEdges));
        this.nextNodeId = this.nextPathNodeId();
        // 「上一个节点」取编号最大的那个（即最后画的那个）。
        // 以前取的是 Object.keys 的最后一个 —— 那是 JSON 里的顺序，
        // 跟绘制先后无关，自动连线会莫名其妙接到一个随机节点上。
        this.lastNodeId = this.lastPathNodeId();
      }
    },
    resetDraw() {
      this.drawnNodes = {}; this.drawnEdges = []; this.nextNodeId = 0;
      this.selectedNode = null; this.connectingFrom = null; this.lastNodeId = null;
    },
    setMode(mode) {
      // 离开绘制模式时，将绘制数据同步回 networkData（内存中）
      if (this.drawMode === 'path' && mode !== 'path' && Object.keys(this.drawnNodes).length > 0) {
        if (!this.networkData) this.networkData = { nodes: {}, edges: [], floor_info: {} };
        this.networkData.nodes = Object.assign({}, this.drawnNodes);
        this.networkData.edges = [...this.drawnEdges];
      }
      this.drawMode = mode;
      this.selectedNode = null;
      this.connectingFrom = null;
      if (mode === 'path') {
        // 进入绘制模式：从 networkData 加载最新数据（排除座位节点，座位由独立标记显示）
        const src = this.networkData || { nodes: {}, edges: [] };
        this.drawnNodes = {};
        for (const [k, v] of Object.entries(src.nodes)) {
          if (v.type !== 'seat') this.drawnNodes[k] = JSON.parse(JSON.stringify(v));
        }
        this.drawnEdges = (src.edges || []).filter(e => this.drawnNodes[e.from] && this.drawnNodes[e.to]);
        this.drawnEdges = JSON.parse(JSON.stringify(this.drawnEdges));
        this.nextNodeId = this.nextPathNodeId();
        // 记录最后画的那个节点（编号最大的），用于自动连线
        this.lastNodeId = this.lastPathNodeId();
      }
    },

    // ========== SVG 点击 ==========
    onSvgClick(e) {
      if (this.draggingSeat || this.draggingNode) return;
      const svg = e.currentTarget;
      const rect = svg.getBoundingClientRect();
      const x = Math.round(e.clientX - rect.left);
      const y = Math.round(e.clientY - rect.top);
      if (this.drawMode === 'path') {
        // 绘制模式：点击空白处添加路径节点
        this.addPathNode(x, y);
      } else if (this.drawMode === 'seat' && !this.editingSeatId) {
        this.newSeatX = x; this.newSeatY = y;
      }
    },

    // ========== 手动绘制路线 ==========

    /* 下一个可用节点 id：现有 id 里最大数字 + 1。

       以前这里用的是「节点个数」：
           this.nextNodeId = Object.keys(this.drawnNodes).length;
       节点数 34 时下一个 id 也是 p34 —— 可路网里很可能已经有 p34，
       于是新画的点会**静默覆盖**那个同名节点（坐标被改掉，
       原本连在它上面的通道全部错位），而且完全没有提示。
       改成取最大编号 +1，从根上避免撞名。 */
    nextPathNodeId() {
      let max = -1;
      for (const k of Object.keys(this.drawnNodes || {})) {
        const m = /^p(\d+)$/.exec(k);
        if (m) max = Math.max(max, parseInt(m[1], 10));
      }
      return max + 1;
    },

    /* 最后画的那个节点 = 编号最大的那个。
       不能拿 Object.keys 的最后一个：那是 JSON 里的顺序，
       跟绘制先后无关，自动连线会莫名接到一个随机节点上。 */
    lastPathNodeId() {
      const n = this.nextPathNodeId() - 1;
      if (n < 0) return null;
      const id = 'p' + n;
      return this.drawnNodes[id] ? id : null;
    },

    /* 按连通性把节点分块，顺带返回邻接表 */
    pathComponents() {
      const adj = {};
      for (const k of Object.keys(this.drawnNodes || {})) adj[k] = [];
      for (const e of this.drawnEdges || []) {
        if (adj[e.from] && adj[e.to]) { adj[e.from].push(e.to); adj[e.to].push(e.from); }
      }
      const seen = new Set();
      const comps = [];
      for (const k of Object.keys(this.drawnNodes || {})) {
        if (seen.has(k)) continue;
        const stack = [k]; seen.add(k); const comp = [];
        while (stack.length) {
          const x = stack.pop(); comp.push(x);
          for (const y of adj[x]) if (!seen.has(y)) { seen.add(y); stack.push(y); }
        }
        comps.push(comp);
      }
      return { comps, adj };
    },

    /* 把断成几块的路线用最短的一条边连起来，返回补了几条。

       绘图工具是「点一下新建一个节点、自动接上一个」的链式画法，
       所以很容易画出几段互不相连的笔画（主通道一段、某个教室一段），
       中间差几十像素没接上。存下去之后导航就会报「没有连通路径」，
       而管理员对着图看半天也看不出哪里断了。
       与其让他自己排查，不如保存时直接补上，并告诉补了哪里。 */
    joinPathComponents() {
      let added = 0;
      for (;;) {
        const { comps } = this.pathComponents();
        if (comps.length <= 1) break;
        comps.sort((a, b) => b.length - a.length);
        const main = comps[0];
        let best = null;
        for (const comp of comps.slice(1)) {
          for (const a of main) {
            const pa = this.drawnNodes[a];
            for (const b of comp) {
              const pb = this.drawnNodes[b];
              const d = (pa.x - pb.x) * (pa.x - pb.x) + (pa.y - pb.y) * (pa.y - pb.y);
              if (best === null || d < best.d) best = { d, a, b };
            }
          }
        }
        if (!best) break;
        this.drawnEdges.push({ from: best.a, to: best.b });
        added++;
      }
      return added;
    },

    addPathNode(x, y) {
      const id = `p${this.nextPathNodeId()}`;
      this.drawnNodes[id] = { x, y, type: 'normal', name: null };
      // 自动连到上一个节点（沿通道点击形成自然链条）
      if (this.connectingFrom !== null) {
        this.drawnEdges.push({ from: this.connectingFrom, to: id });
        this.connectingFrom = null;
      } else if (this.lastNodeId !== null && this.drawnNodes[this.lastNodeId]) {
        this.drawnEdges.push({ from: this.lastNodeId, to: id });
      }
      this.lastNodeId = id;
      this.selectedNode = id;
    },
    onNodeClick(nid, node, e) {
      if (this.drawMode !== 'path') return;
      e.stopPropagation();
      if (this.connectingFrom === nid) {
        this.connectingFrom = null; this.selectedNode = null; return;
      }
      if (this.connectingFrom !== null) {
        this.drawnEdges.push({ from: this.connectingFrom, to: nid });
        this.connectingFrom = null; this.selectedNode = nid;
      } else {
        this.connectingFrom = nid; this.selectedNode = nid;
      }
    },
    // 绘制模式下的节点拖拽
    startNodeDragInDraw(nid, node, e) {
      if (this.drawMode !== 'path') return;
      e.stopPropagation();
      this.draggingNode = nid;
      const svg = e.currentTarget.closest('svg');
      const rect = svg.getBoundingClientRect();
      this.dragOffsetX = e.clientX - rect.left - node.x;
      this.dragOffsetY = e.clientY - rect.top - node.y;
      document.addEventListener('mousemove', this.onNodeDragInDraw);
      document.addEventListener('mouseup', this.endNodeDragInDraw);
    },
    onNodeDragInDraw(e) {
      if (!this.draggingNode || !this.drawnNodes[this.draggingNode]) return;
      const svg = document.querySelector('#app svg');
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const x = Math.round(e.clientX - rect.left - this.dragOffsetX);
      const y = Math.round(e.clientY - rect.top - this.dragOffsetY);
      const node = this.drawnNodes[this.draggingNode];
      if (node) { node.x = Math.max(0, x); node.y = Math.max(0, y); }
    },
    endNodeDragInDraw(e) {
      document.removeEventListener('mousemove', this.onNodeDragInDraw);
      document.removeEventListener('mouseup', this.endNodeDragInDraw);
      this.draggingNode = null;
    },
    deleteSelectedNode() {
      if (this.selectedNode === null || !this.drawnNodes[this.selectedNode]) return;
      const id = this.selectedNode;
      this.drawnEdges = this.drawnEdges.filter(e => e.from !== id && e.to !== id);
      delete this.drawnNodes[id];
      this.selectedNode = null; this.connectingFrom = null;
    },
    clearDrawnNetwork() {
      if (!Object.keys(this.drawnNodes).length) return;
      if (!confirm('确定清除所有已绘制的路径节点？')) return;
      this.drawnNodes = {}; this.drawnEdges = [];
      this.nextNodeId = 0; this.selectedNode = null; this.connectingFrom = null;
    },

    // ========== 保存手动绘制的路网 ==========
    async saveDrawnNetwork() {
      const n = Object.keys(this.drawnNodes).length;
      if (!n) { showToast('请先在平面图上点击绘制路线', 'error'); return; }

      // 保存前先查连通性：断成几块的路线存下去，导航时必然报
      // 「没有连通路径」，而管理员对着图很难看出断在哪。
      const before = this.pathComponents().comps;
      if (before.length > 1) {
        const sizes = before.map(c => c.length).sort((a, b) => b - a).join(' / ');
        const ok = confirm(
          '检测到路线断成了 ' + before.length + ' 段（各段节点数：' + sizes + '），'
          + '中间没有连通，导航时会提示「没有连通路径」。\n\n'
          + '是否自动把这几段用最短的一条线连起来？\n'
          + '（点「取消」则按现在的样子原样保存）'
        );
        if (ok) {
          const added = this.joinPathComponents();
          showToast('已自动连接 ' + added + ' 处断点');
        }
      }

      const payload = {
        nodes: this.drawnNodes,
        edges: this.drawnEdges,
        floor_info: { width: this.floorPlanWidth, height: this.floorPlanHeight },
      };
      try {
        await api.post('/api/admin/network/save-manual', {
          floor_id: this.floorId,
          network: payload,
        });
        // 立即同步到 networkData，确保其他模式能看到
        this.networkData = JSON.parse(JSON.stringify(payload));
        showToast(`路线已保存：${n} 个节点，${this.drawnEdges.length} 条通道`);
      } catch (e) { console.error('保存路线失败:', e); }
    },

    // ========== 保存路网（通用） ==========
    async saveNetwork() {
      if (this.drawMode === 'path') { await this.saveDrawnNetwork(); return; }
      if (!this.networkData) { showToast('没有路网数据可保存', 'info'); return; }
      showToast('路网已保存');
    },

    // ========== 自动生成路网（CAD 图用） ==========
    async generateNetwork() {
      if (!this.floorId) { showToast('请选择楼层', 'error'); return; }
      this.generating = true;
      try {
        const res = await api.post('/api/admin/network/generate', { floor_id: this.floorId });
        const net = res.data?.network;
        this.networkData = net;
        if (!net || !Object.keys(net.nodes || {}).length) {
          showToast('自动提取未生成有效节点，可切换到「绘制路线」模式手动画', 'warning');
        } else {
          showToast(`路网生成成功！${Object.keys(net.nodes).length} 个节点`);
        }
      } catch (e) { console.error('路网生成失败:', e); }
      finally { this.generating = false; }
    },

    // ========== 删除路网 ==========
    async deleteNetwork() {
      if (!this.floorId) { showToast('请选择楼层', 'error'); return; }
      if (!this.networkData) { showToast('当前没有路网数据', 'info'); return; }
      if (!confirm('确定删除该楼层已生成/保存的路网？此操作不可恢复！')) return;
      try {
        await api.delete(`/api/admin/network/${this.floorId}`);
        this.networkData = null;
        this.resetDraw();
        showToast('路网已删除');
      } catch (e) { console.error('删除路网失败:', e); }
    },

    // ========== 座位默认编号（自动往下排） ==========
    updateDefaultSeatLabel() {
      let best = { prefix: 'A', num: 0, found: false };
      for (const s of this.seats || []) {
        const m = /^([A-Za-z]+)[-\s]?(\d+)$/.exec(String(s.seat_label || '').trim());
        if (m) {
          const num = parseInt(m[2], 10);
          if (!best.found || num > best.num) { best = { prefix: m[1].toUpperCase(), num, found: true }; }
        }
      }
      this.newSeatLabel = best.found ? `${best.prefix}-${best.num + 1}` : 'A-1';
    },

    // ========== 路网节点拖拽（编辑模式） ==========
    startNodeDrag(nid, node, e) {
      if (this.drawMode !== 'edit' || node.type === 'seat') return;
      e.stopPropagation();
      this.draggingNode = nid;
      const svg = e.currentTarget.closest('svg');
      const rect = svg.getBoundingClientRect();
      this.dragOffsetX = e.clientX - rect.left - node.x;
      this.dragOffsetY = e.clientY - rect.top - node.y;
      document.addEventListener('mousemove', this.onNodeDrag);
      document.addEventListener('mouseup', this.endNodeDrag);
    },
    onNodeDrag(e) {
      if (!this.draggingNode) return;
      const svg = document.querySelector('#app svg');
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const x = Math.round(e.clientX - rect.left - this.dragOffsetX);
      const y = Math.round(e.clientY - rect.top - this.dragOffsetY);
      const node = this.networkData?.nodes?.[this.draggingNode];
      if (node) { node.x = Math.max(0, x); node.y = Math.max(0, y); }
    },
    async endNodeDrag(e) {
      document.removeEventListener('mousemove', this.onNodeDrag);
      document.removeEventListener('mouseup', this.endNodeDrag);
      if (!this.draggingNode) return;
      const nid = this.draggingNode; this.draggingNode = null;
      // 编辑模式下拖拽节点后自动保存到后端
      if (this.networkData && this.floorId) {
        try {
          await api.post('/api/admin/network/save-manual', {
            floor_id: this.floorId,
            network: {
              nodes: this.networkData.nodes,
              edges: this.networkData.edges,
              floor_info: this.networkData.floor_info || { width: this.floorPlanWidth, height: this.floorPlanHeight },
            },
          });
        } catch (e) { console.error('保存路网调整失败:', e); }
      }
    },

    // ========== 座位拖拽 ==========
    startDrag(seat, e) {
      e.stopPropagation();
      this.draggingSeat = seat.id;
      const svg = e.currentTarget.closest('svg');
      const rect = svg.getBoundingClientRect();
      this.dragOffsetX = e.clientX - rect.left - seat.x;
      this.dragOffsetY = e.clientY - rect.top - seat.y;
      document.addEventListener('mousemove', this.onDrag);
      document.addEventListener('mouseup', this.endDrag);
    },
    onDrag(e) {
      if (!this.draggingSeat) return;
      const svg = document.querySelector('#app svg');
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const x = Math.round(e.clientX - rect.left - this.dragOffsetX);
      const y = Math.round(e.clientY - rect.top - this.dragOffsetY);
      const seat = this.seats.find(s => s.id === this.draggingSeat);
      if (seat) { seat.x = Math.max(0, x); seat.y = Math.max(0, y); }
    },
    async endDrag(e) {
      document.removeEventListener('mousemove', this.onDrag);
      document.removeEventListener('mouseup', this.endDrag);
      if (!this.draggingSeat) return;
      const seat = this.seats.find(s => s.id === this.draggingSeat);
      const seatId = this.draggingSeat; this.draggingSeat = null;
      if (seat) {
        await api.put(`/api/seats/${seatId}`, { x: seat.x, y: seat.y });
        // 只保存座位坐标，不重新生成路网（避免覆盖手动绘制的路线）
      }
    },

    // ========== 座位选择/批量删除 ==========
    toggleSelectSeat(id) {
      const idx = this.selectedSeatIds.indexOf(id);
      if (idx >= 0) this.selectedSeatIds.splice(idx, 1);
      else this.selectedSeatIds.push(id);
    },
    toggleSelectAll() {
      if (this.selectedSeatIds.length === this.seats.length) this.selectedSeatIds = [];
      else this.selectedSeatIds = this.seats.map(s => s.id);
    },
    async batchDeleteSeats() {
      if (!this.selectedSeatIds.length) { showToast('请先选择要删除的座位', 'error'); return; }
      const ids = this.selectedSeatIds.slice();
      if (!confirm('确定删除选中的 ' + ids.length + ' 个座位？\n\n'
        + '说明：这里是「关闭」座位 —— 记录会保留（历史预约还在），'
        + '只是不再对外显示和接受预约。')) return;

      // ★ 逐个删并统计真实结果。
      //   旧代码是 try{...}catch(e){} —— 错误被静默吞掉，
      //   然后不管成没成都弹「已删除 N 个座位」，用户以为删干净了其实没有。
      let ok = 0; const failed = [];
      for (const id of ids) {
        try { await api.delete(`/api/seats/${id}`); ok++; }
        catch (e) {
          const lab = (this.seats.find(s => s.id === id) || {}).seat_label || ('#' + id);
          failed.push(lab);
        }
      }
      this.selectedSeatIds = [];
      await this.onFloorChange();

      if (failed.length === 0) {
        showToast(`已关闭 ${ok} 个座位`, 'success');
      } else if (ok === 0) {
        showToast(`删除失败：${failed.length} 个座位都没删掉（${failed.slice(0, 3).join('、')}${failed.length > 3 ? ' 等' : ''}）`, 'error');
      } else {
        showToast(`已关闭 ${ok} 个，另有 ${failed.length} 个失败（${failed.slice(0, 3).join('、')}${failed.length > 3 ? ' 等' : ''}）`, 'warning');
      }
    },
    async addSeat() {
      if (!this.newSeatLabel || !this.floorId) { showToast('请填写完整信息', 'error'); return; }
      if (this.editingSeatId) {
        await api.put(`/api/seats/${this.editingSeatId}`, { seat_label: this.newSeatLabel, seat_type: this.newSeatType, x: this.newSeatX, y: this.newSeatY });
      } else {
        await api.post(`/api/floors/${this.floorId}/seats`, { seat_label: this.newSeatLabel, seat_type: this.newSeatType, x: this.newSeatX, y: this.newSeatY });
      }
      this.editingSeatId = null; this.newSeatX = 0; this.newSeatY = 0; this.newSeatType = 'normal';
      await this.onFloorChange();
      this.updateDefaultSeatLabel();
    },
    async batchAddSeats() {
      const seats = [];
      for (let r = 0; r < 6; r++) for (let c = 0; c < 8; c++) seats.push({ seat_label: `${String.fromCharCode(65 + r)}-${c + 1}`, x: 100 + c * 80, y: 100 + r * 80 });
      await api.post(`/api/floors/${this.floorId}/seats`, seats);
      showToast(`批量添加 ${seats.length} 个座位`);
      await this.onFloorChange();
      this.updateDefaultSeatLabel();
    },
    async deleteSeat(id) {
      if (!confirm('确定删除该座位？\n\n（这里是「关闭」：记录保留，只是不再对外显示和接受预约）')) return;
      try {
        await api.delete(`/api/seats/${id}`);
      } catch (e) {
        showToast('删除失败：' + ((e && e.message) || '请稍后重试'), 'error');
        return;
      }
      await this.onFloorChange();
      showToast('已关闭该座位');
    },
    editSeat(seat) {
      this.editingSeatId = seat.id; this.newSeatLabel = seat.seat_label;
      this.newSeatX = seat.x; this.newSeatY = seat.y; this.newSeatType = seat.seat_type;
    },
    cancelEdit() {
      this.editingSeatId = null; this.newSeatX = 0; this.newSeatY = 0; this.newSeatType = 'normal';
      this.updateDefaultSeatLabel();
    },
  },
}).mount('#app');

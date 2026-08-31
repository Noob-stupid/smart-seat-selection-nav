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
    async loadBuildings() {
      const res = await api.get('/api/buildings');
      this.buildings = res.data || [];
      if (this.floorId && !this.buildingId) {
        for (const b of this.buildings) {
          const detail = await api.get(`/api/buildings/${b.id}`);
          if ((detail.data?.floors || []).some(f => f.id === this.floorId)) {
            this.buildingId = b.id;
            break;
          }
        }
      }
      if (this.buildingId) this.onBuildingChange();
    },
    async onBuildingChange() {
      const requestedFloorId = this.floorId;
      this.floors = []; this.floorId = null; this.seats = []; this.networkData = null;
      this.floorPlanUrl = null; this.resetDraw();
      if (!this.buildingId) return;
      const res = await api.get(`/api/buildings/${this.buildingId}`);
      this.floors = res.data?.floors || [];
      const requested = this.floors.find(f => f.id === requestedFloorId);
      this.floorId = requested ? requested.id : (this.floors.length ? this.floors[0].id : null);
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
        this.nextNodeId = Object.keys(this.drawnNodes).length;
        const nids = Object.keys(this.drawnNodes);
        this.lastNodeId = nids.length > 0 ? nids[nids.length - 1] : null;
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
        this.nextNodeId = Object.keys(this.drawnNodes).length;
        // 记录最后一个节点（用于自动连线）
        const nids = Object.keys(this.drawnNodes);
        this.lastNodeId = nids.length > 0 ? nids[nids.length - 1] : null;
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
    addPathNode(x, y) {
      const id = `p${this.nextNodeId++}`;
      this.drawnNodes[id] = { x, y, type: 'normal', name: null };
      // 自动连到上一个节点（沿通道点击形成自然链条）
      if (this.connectingFrom !== null) {
        this.drawnEdges.push({ from: this.connectingFrom, to: id });
        this.connectingFrom = null;
      } else if (this.lastNodeId !== null) {
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
      if (!confirm(`确定删除选中的 ${this.selectedSeatIds.length} 个座位？`)) return;
      for (const id of this.selectedSeatIds) {
        try { await api.delete(`/api/seats/${id}`); } catch (e) { }
      }
      const n = this.selectedSeatIds.length; this.selectedSeatIds = [];
      await this.onFloorChange();
      setTimeout(() => showToast(`已删除 ${n} 个座位`), 100);
    },
    async addSeat() {
      if (!this.newSeatLabel || !this.floorId) { showToast('请填写完整信息', 'error'); return; }
      if (this.editingSeatId) {
        await api.put(`/api/seats/${this.editingSeatId}`, { seat_label: this.newSeatLabel, seat_type: this.newSeatType, x: this.newSeatX, y: this.newSeatY });
      } else {
        await api.post(`/api/floors/${this.floorId}/seats`, { seat_label: this.newSeatLabel, seat_type: this.newSeatType, x: this.newSeatX, y: this.newSeatY });
      }
      this.editingSeatId = null; this.newSeatLabel = ''; this.newSeatX = 0; this.newSeatY = 0; this.newSeatType = 'normal';
      this.onFloorChange();
    },
    async batchAddSeats() {
      const seats = [];
      for (let r = 0; r < 6; r++) for (let c = 0; c < 8; c++) seats.push({ seat_label: `${String.fromCharCode(65 + r)}-${c + 1}`, x: 100 + c * 80, y: 100 + r * 80 });
      await api.post(`/api/floors/${this.floorId}/seats`, seats);
      showToast(`批量添加 ${seats.length} 个座位`); this.onFloorChange();
    },
    async relayoutSeats() {
      if (!this.floorId || !this.floorPlanUrl) { showToast('请先上传平面图', 'error'); return; }
      if (!confirm('将按当前图片尺寸重新生成座位网格，已有座位会被替换，确定？')) return;
      try {
        const res = await api.post(`/api/admin/floors/${this.floorId}/relayout-seats`, {});
        const count = res.data?.data?.count || 0;
        showToast(`已按图片生成 ${count} 个座位`);
        await this.onFloorChange();
      } catch (e) { console.error('按图片重排座位失败:', e); }
    },
    async deleteSeat(id) {
      if (!confirm('确定删除？')) return;
      await api.delete(`/api/seats/${id}`);
      await this.onFloorChange();
      showToast('已删除');
    },
    editSeat(seat) {
      this.editingSeatId = seat.id; this.newSeatLabel = seat.seat_label;
      this.newSeatX = seat.x; this.newSeatY = seat.y; this.newSeatType = seat.seat_type;
    },
    cancelEdit() {
      this.editingSeatId = null; this.newSeatLabel = ''; this.newSeatX = 0; this.newSeatY = 0; this.newSeatType = 'normal';
    },
  },
}).mount('#app');

/* 平面图与路网配置页面 Vue 应用 - 手动绘制路线模式 */
const { createApp } = Vue;

/* 缩放范围：0.3x 能把整层看全，5x 能把一个座位放到能点准。
   再往外缩，图上的点位只剩一两个像素，点谁都不准；再往里放就全是马赛克。 */
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 5;
/* 滚轮一格缩放的比例（太小按十几次才动，太大一下就到顶） */
const ZOOM_STEP = 1.15;

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
      // ===== 缩放 / 平移 =====
      zoom: 1,      // 缩放倍数
      panX: 0,      // 平移量，单位是平面图像素（也就是 SVG 自己的用户坐标）
      panY: 0,
      panning: false,   // 正在拖画布（只用来换鼠标手势，顺便挡住误触的点击）
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
    /* 画布整体的变换。顺序是「先平移再缩放」，等价于
           屏幕点 = 平面图点 * zoom + pan
       _screenToPlan 里的逆变换必须和这个式子严格对应，两边一起改才不会错位。 */
    viewTransform() {
      return `translate(${this.panX}, ${this.panY}) scale(${this.zoom})`;
    },
    zoomPercent() {
      return Math.round(this.zoom * 100) + '%';
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
      // 这个函数有两个来源：① 换楼层/换建筑；② 增删座位后刷新同层。
      // 只有「同层刷新」才应该保留未保存的绘制节点 —— 换了楼层还保留的话，
      // 上层的节点会画在新楼层的平面图上，看起来就像「一楼的座位透到二楼」。
      const sameFloor = this._lastFloorId === this.floorId;
      const keepDraw = sameFloor && this.drawMode === 'path'
                       && Object.keys(this.drawnNodes).length > 0;
      const oldDrawn = keepDraw
        ? { nodes: JSON.parse(JSON.stringify(this.drawnNodes)),
            edges: JSON.parse(JSON.stringify(this.drawnEdges)),
            nextId: this.nextNodeId }
        : null;
      this._lastFloorId = this.floorId;
      // 换楼层就把视角复位：上一层的缩放平移套到新图上，大概率停在一片空白上，
      // 看起来就像「这一层没图」。同层刷新（加完座位回来）不能复位，否则每加一个就跳一次。
      if (!sameFloor) this.resetView();

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

    // ========== 缩放与平移 ==========

    /* 鼠标事件 → SVG 用户坐标（还没去掉缩放平移的那一层）。
       为什么要按 rect 尺寸再乘一次比例：SVG 的 width/height 属性是平面图尺寸，
       但 CSS 完全可能把它拉伸（窄屏、flex 里的元素等）。原版直接用
       clientX - rect.left 当平面图坐标，一旦被拉伸就整体偏移；
       这里按「属性尺寸 / 实际渲染尺寸」还原，拉伸时也能对得上。 */
    _svgPoint(e) {
      const svg = document.querySelector('#app svg');
      if (!svg) return { x: 0, y: 0 };
      const rect = svg.getBoundingClientRect();
      const kx = rect.width ? (this.floorPlanWidth || 800) / rect.width : 1;
      const ky = rect.height ? (this.floorPlanHeight || 600) / rect.height : 1;
      return { x: (e.clientX - rect.left) * kx, y: (e.clientY - rect.top) * ky };
    },

    /* ★ 屏幕坐标 → 平面图坐标：全页唯一的换算入口。
       加缩放之前，点击与三条拖拽各自写了一遍「clientX - rect.left」，
       那等于假设「1 屏幕像素 == 1 平面图像素、画布也没位移」。
       画布一旦能缩放平移，这个假设就不成立了：同一个鼠标位置，
       2x 时对应的平面图坐标是 1x 时的一半再减掉平移量。
       所以把这一串收敛在这个函数里，谁会用到就来调 —— 少一处重复换算，
       就少一个「缩放后点到了旁边那个座位 / 节点不跟手」的坑。 */
    _screenToPlan(e) {
      const p = this._svgPoint(e);
      // 逆掉 <g> 上的 translate(panX,panY) scale(zoom)
      return { x: (p.x - this.panX) / this.zoom, y: (p.y - this.panY) / this.zoom };
    },

    /* 以屏幕点 (cx,cy) 为锚点缩放到 next：
       先记住锚点下面压着的平面图坐标，缩放后再把它送回锚点位置，
       这样滚轮缩放时鼠标指着的那个座位/墙角不会跑。 */
    _applyZoom(next, cx, cy) {
      next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next));
      next = Math.round(next * 1000) / 1000;   // 免得连按后出现 1.0000000000000002
      if (!isFinite(next) || next === this.zoom) return;
      const planX = (cx - this.panX) / this.zoom;
      const planY = (cy - this.panY) / this.zoom;
      this.zoom = next;
      this.panX = cx - planX * next;
      this.panY = cy - planY * next;
    },

    /* 滚轮缩放：三种模式都能用。
       滚轮不参与「点击」语义（点击才负责加座位/连线），所以没有冲突。 */
    onWheelZoom(e) {
      const raw = this.zoom * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
      // 先夹到范围内再比：夹完等于当前倍数说明已经到顶了，
      // 这时不拦滚轮，把它让给外层容器去滚动，别让页面在画布上滚死。
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, raw));
      if (next === this.zoom) return;
      e.preventDefault();
      const p = this._svgPoint(e);   // 缩放中心 = 鼠标当前所在位置
      this._applyZoom(next, p.x, p.y);
    },

    /* 按钮缩放：以画布中心为锚点，这样画面不会往一边跑 */
    zoomBy(k) {
      const cx = (this.floorPlanWidth || 800) / 2;
      const cy = (this.floorPlanHeight || 600) / 2;
      this._applyZoom(this.zoom * k, cx, cy);
    },

    /* 点缩放比 → 回到 100%，但保持画面中心不动（只改倍数不跳位置） */
    resetZoom() {
      const cx = (this.floorPlanWidth || 800) / 2;
      const cy = (this.floorPlanHeight || 600) / 2;
      this._applyZoom(1, cx, cy);
    },

    /* 适应窗口：1:1 且回到原点 —— 和没加缩放功能时的样子完全一致 */
    resetView() {
      this.zoom = 1;
      this.panX = 0;
      this.panY = 0;
    },

    /* 平移手势。为什么不是「空白处左键拖」：
       绘制路线 / 添加座位模式下，空白处左键要负责「加节点 / 加座位」，
       两者抢同一个 mousedown 就必然有一边失灵。所以平移只认三种手势：
       中键拖、Shift+左键拖、编辑路网模式下的空白左键拖（那个模式左键本来就没活干）。
       空格拖没做：空格在页面里还会触发滚动/按钮激活，抢这键得不偿失。 */
    onSvgMouseDown(e) {
      // 上一次平移可能松手在画布外，浏览器不会补发 click，这里兜底清掉残留标记
      this._suppressClick = false;
      const panInEdit = e.button === 0 && this.drawMode === 'edit' && !e.shiftKey;
      const isPan = e.button === 1 || (e.button === 0 && e.shiftKey) || panInEdit;
      if (!isPan) return;
      e.preventDefault();   // 中键的默认行为是滚动/自动滚动，先掐掉
      // 这次 mousedown 之后浏览器还会补一个 click；不挡住的话，
      // 「拖了一下画布」会被当成「在空白处新增座位 / 节点」。
      this._suppressClick = true;
      this.panning = true;
      const p = this._svgPoint(e);
      this._panFrom = { x: p.x, y: p.y, panX: this.panX, panY: this.panY };
      document.addEventListener('mousemove', this.onPan);
      document.addEventListener('mouseup', this.endPan);
    },
    onPan(e) {
      if (!this.panning || !this._panFrom) return;
      const p = this._svgPoint(e);
      this.panX = this._panFrom.panX + (p.x - this._panFrom.x);
      this.panY = this._panFrom.panY + (p.y - this._panFrom.y);
    },
    endPan(e) {
      document.removeEventListener('mousemove', this.onPan);
      document.removeEventListener('mouseup', this.endPan);
      this.panning = false;
      this._panFrom = null;
    },

    // ========== SVG 点击 ==========
    onSvgClick(e) {
      if (this.draggingSeat || this.draggingNode) return;
      // 刚拖完画布弹出的那个 click 不算点击
      if (this._suppressClick) { this._suppressClick = false; return; }
      const p = this._screenToPlan(e);
      // 缩小 / 平移之后，画布空白处有一部分已经不在平面图上了，
      // 那儿点一下不该凭空冒出一个坐标是负数的座位
      const w = this.floorPlanWidth || 800;
      const h = this.floorPlanHeight || 600;
      if (p.x < 0 || p.y < 0 || p.x > w || p.y > h) return;
      const x = Math.round(p.x);
      const y = Math.round(p.y);
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
      // 偏移量也在平面图坐标里算（不是 clientX - rect.left 那种屏幕差值）：
      // 否则 2x 时鼠标动 10px、节点会想跑 10 个平面图像素（实际显示成 20px）。
      const p = this._screenToPlan(e);
      this.dragOffsetX = p.x - node.x;
      this.dragOffsetY = p.y - node.y;
      document.addEventListener('mousemove', this.onNodeDragInDraw);
      document.addEventListener('mouseup', this.endNodeDragInDraw);
    },
    onNodeDragInDraw(e) {
      if (!this.draggingNode || !this.drawnNodes[this.draggingNode]) return;
      const p = this._screenToPlan(e);
      const x = Math.round(p.x - this.dragOffsetX);
      const y = Math.round(p.y - this.dragOffsetY);
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
      const p = this._screenToPlan(e);
      this.dragOffsetX = p.x - node.x;
      this.dragOffsetY = p.y - node.y;
      document.addEventListener('mousemove', this.onNodeDrag);
      document.addEventListener('mouseup', this.endNodeDrag);
    },
    onNodeDrag(e) {
      if (!this.draggingNode) return;
      const p = this._screenToPlan(e);
      const x = Math.round(p.x - this.dragOffsetX);
      const y = Math.round(p.y - this.dragOffsetY);
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
      const p = this._screenToPlan(e);
      this.dragOffsetX = p.x - seat.x;
      this.dragOffsetY = p.y - seat.y;
      document.addEventListener('mousemove', this.onDrag);
      document.addEventListener('mouseup', this.endDrag);
    },
    onDrag(e) {
      if (!this.draggingSeat) return;
      const p = this._screenToPlan(e);
      const x = Math.round(p.x - this.dragOffsetX);
      const y = Math.round(p.y - this.dragOffsetY);
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

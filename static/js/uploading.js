/* 平面图上传页面 Vue 应用（自动建图 + 手动上传） */
const { createApp } = Vue;
const AUTO_TASK_KEY = 'auto_mapping_task_id';

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      mode: 'auto',
      buildings: [], buildingId: '', floorNumber: 1, floorName: '',
      existingFloors: [], selectedFloorId: null,
      // 自动建图
      roomName: '', lineMethod: 'lsd', sourceType: 'video',
      videoFiles: [], imageFiles: [],
      mappingBusy: false, mappingError: '', mappingResult: null,
      _mappingAbort: false,   // 用户点了「关闭」：请求还在跑，但不再占着界面
      applying: false,
      processingSteps: ['提取关键帧', '全景拼接', '墙体识别'],
      processingStep: 0, stepTimer: null,
      // 手动上传
      file: null, previewUrl: '', uploading: false, result: null, newFloorId: null,\n      dxfFile: null,          // 可选的 DXF，与图片一起传
      // CAD 图纸（DXF）直接建路网 —— 结构化数据，比从视频/图片猜准得多
      dxfFiles: [], dxfBusy: false, dxfResult: null, dxfError: '',
      dxfApplySeats: true,
    };
  },
  created() {
    this.loadBuildings();
    this.restoreMappingTask();
  },
  updated() {
    // 预览 SVG 必须使用大写的 viewBox 才能按原图比例完整显示：
    // 模板绑定会被渲染成小写 viewbox（无效），这里用原生 API 设置以保留大小写
    this.syncMappingViewBox();
  },
  beforeUnmount() {
    if (this.stepTimer) clearInterval(this.stepTimer);
  },
  computed: {
    // 图片与 DXF 是互补的，不是二选一：
    //   图片能当底图显示（DXF 前端 <img> 用不了），
    //   DXF 的图层里写着哪是墙、哪是家具、这间房叫什么，直接读就能精确生成。
    // 所以这里两个文件各自独立，不互相排斥。
  },
  methods: {
    async loadBuildings() {
      const res = await api.get('/api/buildings');
      this.buildings = res.data || [];
    },
    async onBuildingChange() {
      this.existingFloors = [];
      this.selectedFloorId = null;
      if (!this.buildingId) return;
      const res = await api.get(`/api/buildings/${this.buildingId}`);
      this.existingFloors = res.data?.floors || [];
    },
    setMode(mode) { this.mode = mode; },

    /* ---------- 自动建图 ---------- */
    pickSource(type) {
      this.sourceType = type;
      if (type === 'video') this.imageFiles = [];
      else this.videoFiles = [];
    },
    onVideoChange(e) {
      this.videoFiles = Array.from(e.target.files || []);
      this.imageFiles = [];
      this.sourceType = 'video';
      if (e.target) e.target.value = '';
    },
    onImagesChange(e) {
      this.imageFiles = Array.from(e.target.files || []);
      this.videoFiles = [];
      this.sourceType = 'images';
      if (e.target) e.target.value = '';
    },
    startStepTimer() {
      if (this.stepTimer) clearInterval(this.stepTimer);
      this.stepTimer = setInterval(() => {
        this.processingStep = (this.processingStep + 1) % this.processingSteps.length;
      }, 1400);
    },
    // 关闭遮罩：把 mappingBusy 放掉，让用户能继续操作页面。
    // 建图请求本身是后台任务，关掉这层不影响它继续跑；
    // 它返回时 startMapping 的 finally 会再放一次（幂等）。
    cancelMapping() {
      this._mappingAbort = true;
      this.mappingBusy = false;
      if (this.stepTimer) { clearInterval(this.stepTimer); this.stepTimer = null; }
      showToast('已关闭进度窗。建图仍在后台进行，稍后刷新页面可看结果。', 'info');
    },

    async startMapping() {
      if (!this.buildingId) { showToast('请先选择建筑物', 'error'); return; }
      if (!this.selectedFloorId) { showToast('请选择结果要应用的楼层', 'error'); return; }
      const files = this.videoFiles.length ? this.videoFiles : this.imageFiles;
      if (!files.length) { showToast('请选择视频或图片组素材', 'error'); return; }
      for (const f of files) {
        if (f.size > 100 * 1024 * 1024) {
          showToast(`文件 ${f.name} 超过 100MB 限制`, 'error');
          return;
        }
      }

      this._mappingAbort = false;
      this.mappingBusy = true;
      this.mappingError = '';
      this.mappingResult = null;
      this.processingStep = 0;
      this.startStepTimer();

      const formData = new FormData();
      files.forEach(f => formData.append('file', f));
      formData.append('mode', this.sourceType);
      formData.append('name', this.roomName || '自动建模房间');
      formData.append('line_method', this.lineMethod);

      try {
        const res = await window.axios.post('/api/admin/mapping/tasks', formData);
        const data = res.data?.data || res;
        this.mappingResult = data;
        try { localStorage.setItem(AUTO_TASK_KEY, data.task_id); } catch (e) { }
        showToast('建图完成，可预览并应用');
      } catch (e) {
        const status = e.response?.status;
        const msg = e.response?.data?.message || e.message || '建图失败';
        if (status === 400) this.mappingError = `素材不足或拼接失败（400）：${msg}`;
        else if (status === 500) this.mappingError = `服务依赖缺失（500）：${msg}`;
        else this.mappingError = msg;
      } finally {
        // 用户中途点了关闭的话，这里只清定时器，不再把界面翻回去
        if (!this._mappingAbort) this.mappingBusy = false;
        this._mappingAbort = false;
        if (this.stepTimer) clearInterval(this.stepTimer);
      }
    },
    async applyMapping() {
      if (!this.mappingResult?.task_id || !this.selectedFloorId) {
        showToast('请先选择目标楼层', 'error');
        return;
      }
      this.applying = true;
      try {
        await window.axios.post(`/api/admin/mapping/tasks/${this.mappingResult.task_id}/apply`, {
          floor_id: Number(this.selectedFloorId),
        });
        try { localStorage.removeItem(AUTO_TASK_KEY); } catch (e) { }
        showToast('已应用到楼层，正在跳转...');
        setTimeout(() => {
          location.href = `admin/floor_plan.html?floor_id=${this.selectedFloorId}`;
        }, 600);
      } catch (e) {
        showToast(e.response?.data?.message || '应用失败', 'error');
      } finally {
        this.applying = false;
      }
    },
    syncMappingViewBox() {
      const el = this.$refs && this.$refs.mappingSvg;
      if (!el || !this.mappingResult) return;
      const w = this.mappingResult.image?.width;
      const h = this.mappingResult.image?.height;
      if (w && h) el.setAttribute('viewBox', `0 0 ${w} ${h}`);
    },
    resetMapping() {
      this.mappingResult = null;
      this.mappingError = '';
      this.videoFiles = [];
      this.imageFiles = [];
      try { localStorage.removeItem(AUTO_TASK_KEY); } catch (e) { }
    },

    // -------------------- CAD 图纸（DXF）直接建路网 --------------------
    //
    // 与上面的视频/图片建图是两条完全不同的路：
    // 视频/图片要先拼图再识别墙体，本质是「猜」；DXF 里画图的人已经把
    // 墙、家具、房间名分好图层了，直接读就是「知道」。
    // 实测同一栋楼：图片路线 4243 节点、孤立 31%、认不出座位；
    // DXF 路线一次拿到 810 节点、187 个座位（自动按房间编号命名）、23 个房间。
    onDxfChange(e) {
      const f = e.target.files && e.target.files[0];
      this.dxfFiles = f ? [f] : [];
      this.dxfResult = null;
      this.dxfError = '';
    },
    async startDxfBuild() {
      if (!this.selectedFloorId) { showToast('请先选择结果要应用的楼层', 'error'); return; }
      const f = this.dxfFiles[0];
      if (!f) { showToast('请选择 DXF 图纸', 'error'); return; }
      if (!/\.dxf$/i.test(f.name)) { showToast('只支持 .dxf 文件', 'error'); return; }
      if (f.size > 50 * 1024 * 1024) { showToast('DXF 超过 50MB，请先在 CAD 里精简', 'error'); return; }

      this.dxfBusy = true;
      this.dxfError = '';
      this.dxfResult = null;
      try {
        // ① 先上传（后端会当场用 ezdxf 验一遍能不能解析，坏文件直接拒）
        const fd = new FormData();
        fd.append('file', f);
        const up = await window.axios.post('/api/upload', fd);
        const uploaded = up.data?.data || up.data;
        if (uploaded?.kind !== 'dxf') {
          throw new Error('上传结果不是 DXF，请确认文件类型');
        }

        // ② 再从 DXF 建路网（可选择是否把识别出的座位直接写库）
        const res = await window.axios.post('/api/admin/network/generate-from-dxf', {
          floor_id: Number(this.selectedFloorId),
          dxf_path: uploaded.file_path,
          apply_seats: this.dxfApplySeats,
        });
        const d = res.data?.data || res.data;
        this.dxfResult = d;
        const st = d.stats || {};
        const created = d.seat_created || 0;
        showToast(`已生成：${st.node_count} 个路网节点、${st.seat_count} 个座位`
                  + (created ? `（已入库 ${created} 个）` : '') + `、${st.room_count} 个房间`);
      } catch (e) {
        const msg = e.response?.data?.message || e.message || 'DXF 生成失败';
        this.dxfError = msg;
        showToast(msg, 'error');
      } finally {
        this.dxfBusy = false;
      }
    },
    async restoreMappingTask() {
      const params = new URLSearchParams(location.search);
      let taskId = params.get('task_id');
      if (!taskId) {
        try { taskId = localStorage.getItem(AUTO_TASK_KEY); } catch (e) { }
      }
      if (!taskId) return;
      try {
        const res = await window.axios.get(`/api/admin/mapping/tasks/${taskId}`);
        const data = res.data?.data || res;
        if (data && data.task_id) {
          this.mappingResult = data;
          this.mode = 'auto';
          try { localStorage.setItem(AUTO_TASK_KEY, data.task_id); } catch (e) { }
        }
      } catch (e) {
        if (e.response?.status === 404) {
          try { localStorage.removeItem(AUTO_TASK_KEY); } catch (err) { }
          showToast('上次建图任务已清理，请重新上传', 'error');
        }
      }
    },

    /* ---------- 手动上传 ---------- */
    onFileSelect(e) {
      this.file = e.target.files[0] || null;
      this.previewUrl = this.file ? URL.createObjectURL(this.file) : '';
    },
    onDxfSelect(e) {
      const f = e.target.files[0] || null;
      if (f && !/\.dxf$/i.test(f.name)) {
        showToast('请选择 .dxf 文件', 'error');
        return;
      }
      this.dxfFile = f;
    },
    async upload() {
      if (!this.buildingId) { showToast('请先选择建筑物', 'error'); return; }
      if (!this.file) { showToast('请选择平面图图片（它要当底图显示）', 'error'); return; }

      this.uploading = true;
      try {
        // ① 先传图片 —— 它是底图，平面图页 / 座位图 / 导航都靠它显示
        const imgFd = new FormData();
        imgFd.append('file', this.file);
        const imgRes = await axios.post('/api/upload', imgFd);
        const imgInfo = imgRes.data.data;

        // ② 找楼层：优先用户选的，其次同楼层号且还没有平面图的那层，最后新建
        let floorId = this.selectedFloorId || null;
        if (!floorId) {
          const existing = this.existingFloors.find(
            f => f.floor_number === this.floorNumber && !f.floor_plan_path
          );
          if (existing) floorId = existing.id;
        }
        if (!floorId) {
          const floorRes = await api.post(`/api/buildings/${this.buildingId}/floors`, {
            floor_number: this.floorNumber,
            name: this.floorName || `${this.floorNumber}楼`,
          });
          floorId = floorRes.data.id;
        }
        this.newFloorId = floorId;

        // ③ 把底图挂到楼层上
        await api.put(`/api/floors/${floorId}`, {
          floor_plan_path: imgInfo.file_path,
          floor_plan_width: imgInfo.image_info.width,
          floor_plan_height: imgInfo.image_info.height,
        });

        // ④ 有 DXF 就再走一遍精确提取（路网 + 座位）
        if (this.dxfFile) {
          const dxfFd = new FormData();
          dxfFd.append('file', this.dxfFile);
          const dxfRes = await axios.post('/api/upload', dxfFd);
          const dxfInfo = dxfRes.data.data;

          const gen = await api.post('/api/admin/network/generate-from-dxf', {
            floor_id: Number(floorId),
            dxf_path: dxfInfo.file_path,
            apply_seats: true,
          });
          const d = (gen.data && gen.data) || {};
          const st = d.stats || {};
          showToast(`底图已上传；DXF 解析出 ${st.node_count || 0} 个路网节点、`
                    + `${st.seat_count || 0} 个座位（已写入 ${d.seat_created || 0} 个）、`
                    + `${st.room_count || 0} 个房间`);
        } else {
          showToast('底图已上传。没传 DXF，路网要另点「自动生成」或手画。');
        }

        setTimeout(() => {
          location.href = `admin/floor_plan.html?floor_id=${floorId}`;
        }, 900);
      } catch (e) {
        // 原来只有 console.error，页面上什么都不发生，用户不知道失败了。
        const msg = (e.response && e.response.data && e.response.data.message)
                    || e.message || '上传失败';
        showToast(msg, 'error');
      } finally {
        this.uploading = false;
      }
    },
  },
}).mount('#app');

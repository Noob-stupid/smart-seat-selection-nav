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
      applying: false,
      processingSteps: ['提取关键帧', '全景拼接', '墙体识别'],
      processingStep: 0, stepTimer: null,
      // 手动上传
      file: null, previewUrl: '', uploading: false, result: null, newFloorId: null,
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
        this.mappingBusy = false;
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
          location.href = `/admin/floor-plan?floor_id=${this.selectedFloorId}`;
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
      this.file = e.target.files[0];
      if (this.file) this.previewUrl = URL.createObjectURL(this.file);
    },
    async upload() {
      if (!this.buildingId || !this.file) { showToast('请填写完整信息', 'error'); return; }
      this.uploading = true;
      try {
        // 1. 上传文件
        const formData = new FormData();
        formData.append('file', this.file);
        const uploadRes = await axios.post('/api/upload', formData);
        this.result = uploadRes.data.data;

        // 2. 查找是否已存在同楼层号，若存在则复用
        //    仅匹配“无平面图”的楼层：已有平面图的楼层不可被覆盖
        let floorId = this.selectedFloorId;
        if (!floorId) {
          const existing = this.existingFloors.find(
            f => f.floor_number === this.floorNumber && !f.floor_plan_path
          );
          if (existing) {
            floorId = existing.id;
          }
        }

        if (floorId) {
          // 更新已有楼层的平面图
          await api.put(`/api/floors/${floorId}`, {
            floor_plan_path: this.result.file_path,
            floor_plan_width: this.result.image_info.width,
            floor_plan_height: this.result.image_info.height,
          });
          this.newFloorId = floorId;
          showToast('平面图已更新到现有楼层！');
        } else {
          // 新建楼层
          const floorRes = await api.post(`/api/buildings/${this.buildingId}/floors`, {
            floor_number: this.floorNumber,
            name: this.floorName || `${this.floorNumber}楼`,
          });
          this.newFloorId = floorRes.data.id;

          await api.put(`/api/floors/${this.newFloorId}`, {
            floor_plan_path: this.result.file_path,
            floor_plan_width: this.result.image_info.width,
            floor_plan_height: this.result.image_info.height,
          });
          showToast('上传成功！');
        }
      } catch (e) { console.error(e); }
      finally { this.uploading = false; }
    },
  },
}).mount('#app');

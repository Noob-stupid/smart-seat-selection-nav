/* 平面图上传页面 Vue 应用 */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      buildings: [], buildingId: '', floorNumber: 1, floorName: '',
      existingFloors: [], selectedFloorId: null,
      file: null, previewUrl: '', uploading: false, result: null, newFloorId: null,
    };
  },
  created() { this.loadBuildings(); },
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
        let floorId = this.selectedFloorId;
        if (!floorId) {
          const existing = this.existingFloors.find(
            f => f.floor_number === this.floorNumber
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

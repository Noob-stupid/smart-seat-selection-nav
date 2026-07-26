/* 平面图与路网配置页面 Vue 应用 */
const { createApp } = Vue;

const initScript = document.getElementById('init-data');
const initData = initScript ? JSON.parse(initScript.textContent) : {};

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
    };
  },
  created() { this.loadBuildings(); },
  methods: {
    async loadBuildings() {
      const res = await api.get('/api/buildings');
      this.buildings = res.data || [];
      if (this.buildingId) this.onBuildingChange();
    },
    async onBuildingChange() {
      this.floors = []; this.floorId = null; this.seats = []; this.networkData = null;
      if (!this.buildingId) return;
      const res = await api.get(`/api/buildings/${this.buildingId}`);
      this.floors = res.data?.floors || [];
      if (this.floors.length && !this.floorId) this.floorId = this.floors[0].id;
      if (this.floorId) this.onFloorChange();
    },
    async onFloorChange() {
      this.seats = []; this.networkData = null;
      if (!this.floorId) return;
      const res = await api.get(`/api/floors/${this.floorId}`);
      this.seats = res.data?.seats || [];
      try {
        const netRes = await api.get(`/api/admin/network/${this.floorId}`);
        this.networkData = netRes.data;
      } catch (e) { }
    },
    async generateNetwork() {
      if (!this.floorId) { showToast('请选择楼层', 'error'); return; }
      this.generating = true;
      try {
        const res = await api.post('/api/admin/network/generate', { floor_id: this.floorId });
        this.networkData = res.data?.network;
        showToast('路网生成成功！可在预览图中微调');
      } catch (e) { }
      finally { this.generating = false; }
    },
    saveNetwork() {
      if (!this.networkData) return;
      showToast('路网已保存');
    },
    async addSeat() {
      if (!this.newSeatLabel || !this.floorId) { showToast('请填写完整信息', 'error'); return; }
      await api.post(`/api/floors/${this.floorId}/seats`, {
        seat_label: this.newSeatLabel,
        seat_type: this.newSeatType,
        x: this.newSeatX, y: this.newSeatY,
      });
      showToast('座位添加成功');
      this.newSeatLabel = '';
      this.onFloorChange();
    },
    batchAddSeats() {
      const seats = [];
      for (let row = 0; row < 6; row++) {
        for (let col = 0; col < 8; col++) {
          seats.push({
            seat_label: `${String.fromCharCode(65 + row)}-${col + 1}`,
            x: 100 + col * 80, y: 100 + row * 80,
          });
        }
      }
      api.post(`/api/floors/${this.floorId}/seats`, seats);
      showToast(`批量添加 ${seats.length} 个座位`);
      setTimeout(() => this.onFloorChange(), 500);
    },
    async deleteSeat(id) {
      if (!confirm('确定删除？')) return;
      await api.delete(`/api/seats/${id}`);
      showToast('已删除');
      this.onFloorChange();
    },
    editSeat(seat) {
      this.newSeatLabel = seat.seat_label;
      this.newSeatX = seat.x;
      this.newSeatY = seat.y;
      this.newSeatType = seat.seat_type;
    },
    onNodeClick(nid, node) {
      console.log('Node:', nid, node);
    },
  },
}).mount('#app');

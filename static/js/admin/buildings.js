/* 场所管理页面 Vue 应用 */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      buildings: [], expandedId: null,
      showAddBuilding: false,
      newBuilding: { name: '', alias: '', region: '', address: '', description: '' },
      editingBuilding: null,
      newFloorNumber: 1, newFloorName: '',
    };
  },
  created() { this.loadBuildings(); },
  methods: {
    async loadBuildings() {
      const res = await api.get('/api/buildings');
      this.buildings = res.data || [];
      for (const b of this.buildings) {
        const detail = await api.get(`/api/buildings/${b.id}`);
        b.floors = detail.data?.floors || [];
      }
    },
    async addBuilding() {
      if (!this.newBuilding.name) { showToast('请输入名称', 'error'); return; }
      await api.post('/api/buildings', this.newBuilding);
      showToast('添加成功');
      this.showAddBuilding = false;
      this.newBuilding = { name: '', alias: '', region: '', address: '', description: '' };
      this.loadBuildings();
    },
    async deleteBuilding(id) {
      if (!confirm('确定删除该建筑物？')) return;
      await api.delete(`/api/buildings/${id}`);
      showToast('已删除');
      this.loadBuildings();
    },
    viewBuilding(id) {
      this.expandedId = this.expandedId === id ? null : id;
    },
    editBuilding(b) {
      this.newBuilding = { name: b.name, alias: b.alias || '', region: b.region || '', address: b.address || '', description: b.description || '' };
      this.showAddBuilding = true;
    },
    async addFloor(buildingId) {
      if (!this.newFloorNumber) { showToast('请输入楼层号', 'error'); return; }
      await api.post(`/api/buildings/${buildingId}/floors`, {
        floor_number: this.newFloorNumber,
        name: this.newFloorName || `${this.newFloorNumber}楼`,
      });
      showToast('楼层添加成功');
      this.newFloorNumber = 1;
      this.newFloorName = '';
      this.loadBuildings();
    },
    async deleteFloor(id) {
      if (!confirm('确定删除该楼层？')) return;
      await api.delete(`/api/floors/${id}`);
      showToast('已删除');
      this.loadBuildings();
    },
  },
}).mount('#app');

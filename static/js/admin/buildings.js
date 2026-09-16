/* 场所管理页面 Vue 应用 */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      locId: null,
      loc: { lat: '', lng: '', address: '' },
      locating: false,
      savingLoc: false,
      buildings: [], expandedId: null,
      showAddBuilding: false,
      newBuilding: { name: '', alias: '', region: '', address: '', description: '' },
      editingBuilding: null,
      newFloorNumber: 1, newFloorName: '', newFloorSeatCount: 0,
    };
  },
  created() { this.loadBuildings(); },
  methods: {
    /* ---------- 目标地点（室外导航坐标） ---------- */
    toggleLocation(b) {
      if (this.locId === b.id) { this.locId = null; return; }
      this.locId = b.id;
      this.loc = {
        lat: b.lat != null ? String(b.lat) : '',
        lng: b.lng != null ? String(b.lng) : '',
        address: b.address || '',
      };
    },

    _readMyPosition() {
      return new Promise((resolve, reject) => {
        if (!navigator.geolocation) { reject(new Error('该浏览器不支持定位')); return; }
        navigator.geolocation.getCurrentPosition(
          pos => resolve(pos.coords),
          err => reject(new Error(
            err.code === 1 ? '定位被拒绝，请允许浏览器获取位置'
              : err.code === 3 ? '定位超时，请到空旷处重试' : '无法获取位置')),
          { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
      });
    },

    async useMyLocation() {
      this.locating = true;
      try {
        const c = await this._readMyPosition();
        this.loc.lat = c.latitude.toFixed(6);
        this.loc.lng = c.longitude.toFixed(6);
        showToast('已获取当前位置（精度约 ' + Math.round(c.accuracy || 0) + ' 米）', 'success');
      } catch (e) {
        showToast(e.message, 'error');
      } finally { this.locating = false; }
    },

    async fillNewFromMyLocation() {
      try {
        const c = await this._readMyPosition();
        this.newBuilding.lat = c.latitude.toFixed(6);
        this.newBuilding.lng = c.longitude.toFixed(6);
        showToast('已填入当前位置', 'success');
      } catch (e) { showToast(e.message, 'error'); }
    },

    async saveLocation(b) {
      this.savingLoc = true;
      try {
        const res = await api.put('/api/buildings/' + b.id, {
          lat: this.loc.lat === '' ? null : this.loc.lat,
          lng: this.loc.lng === '' ? null : this.loc.lng,
          address: this.loc.address,
        });
        showToast(res.message || '地点已保存', 'success');
        this.locId = null;
        await this.loadBuildings();
      } catch (e) { /* toast 已提示 */ }
      finally { this.savingLoc = false; }
    },

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
      if (this.editingBuilding) {
        await api.put(`/api/buildings/${this.editingBuilding.id}`, this.newBuilding);
        showToast('修改成功');
      } else {
        await api.post('/api/buildings', this.newBuilding);
        showToast('添加成功');
      }
      this.showAddBuilding = false;
      this.editingBuilding = null;
      this.newBuilding = { name: '', alias: '', region: '', address: '', description: '' };
      this.loadBuildings();
    },
    openAddBuilding() {
      this.editingBuilding = null;
      this.newBuilding = { name: '', alias: '', region: '', address: '', description: '' };
      this.showAddBuilding = true;
    },
    closeAddBuilding() {
      this.showAddBuilding = false;
      this.editingBuilding = null;
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
      this.editingBuilding = b;
      this.newBuilding = { name: b.name, alias: b.alias || '', region: b.region || '', address: b.address || '', description: b.description || '' };
      this.showAddBuilding = true;
    },
    async addFloor(buildingId) {
      if (!this.newFloorNumber) { showToast('请输入楼层号', 'error'); return; }
      await api.post(`/api/buildings/${buildingId}/floors`, {
        floor_number: this.newFloorNumber,
        name: this.newFloorName || `${this.newFloorNumber}楼`,
        seat_count: Math.max(0, Math.floor(Number(this.newFloorSeatCount) || 0)),
      });
      showToast('楼层添加成功');
      this.newFloorNumber = 1;
      this.newFloorName = '';
      this.newFloorSeatCount = 0;
      this.loadBuildings();
    },
    async updateFloorSeatCount(floor) {
      const count = Math.max(0, Math.floor(Number(floor.seat_count) || 0));
      floor.seat_count = count;
      try {
        await api.put(`/api/floors/${floor.id}`, { seat_count: count });
        showToast('座位数已更新');
      } catch (e) {
        this.loadBuildings();
      }
    },
    async deleteFloor(id) {
      if (!confirm('确定删除该楼层？')) return;
      await api.delete(`/api/floors/${id}`);
      showToast('已删除');
      this.loadBuildings();
    },
  },
}).mount('#app');

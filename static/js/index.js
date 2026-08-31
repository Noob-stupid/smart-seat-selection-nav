/* ============================================================
   首页 Vue 应用 — 位置优先设计
   流程: 搜索位置 → 选择场所 → 查看座位
   ============================================================ */
(function () {
  // 如果 Vue 未加载，移除 v-cloak 并退出
  if (typeof Vue === 'undefined') {
    document.querySelectorAll('[v-cloak]').forEach(function (el) { el.removeAttribute('v-cloak') });
    console.warn('[首页] Vue 未加载，跳过');
    return;
  }
  try {
    var app = Vue.createApp({
      delimiters: ['${', '}'],
      data() {
        return {
          query: '',
          searchResults: [],
          searching: false,
          showSearchResults: false,
          regions: [],
          selectedRegion: '',
          buildings: [],
          loading: false,
          selectedBuilding: null,
          stats: null,
          statsLoading: false,
        };
      },
      computed: {
        groupedBuildings() {
          const groups = {};
          this.buildings.forEach(b => {
            const region = b.region || '其他';
            if (!groups[region]) groups[region] = [];
            groups[region].push(b);
          });
          return groups;
        },
      },
      created() {
        this.loadRegions();
        this.loadHotBuildings();
        // 连接 Socket.IO（如果可用）
        try {
          if (typeof connectSocket === 'function') {
            connectSocket();
            if (typeof socket !== 'undefined' && socket) {
              socket.on('seat_update', () => {
                if (this.selectedBuilding) this.loadBuildingStats(this.selectedBuilding.id);
              });
            }
          }
        } catch (e) { console.warn('Socket 不可用', e); }
      },
      methods: {
        async loadRegions() {
          try {
            const res = await api.get('/api/regions');
            this.regions = res.data || [];
          } catch (e) { console.error(e); }
        },

        async doSearch() {
          if (!this.query.trim()) return;
          this.searching = true;
          this.showSearchResults = true;
          this.selectedRegion = '';
          this.buildings = [];
          this.selectedBuilding = null;
          this.stats = null;
          try {
            const res = await api.get('/api/search/venues', { q: this.query.trim() });
            this.searchResults = res.data || [];
          } catch (e) { console.error(e); }
          finally { this.searching = false; }
        },

        async selectRegion(region) {
          this.selectedRegion = region;
          this.query = '';
          this.searchResults = [];
          this.showSearchResults = false;
          this.selectedBuilding = null;
          this.stats = null;
          await this.loadBuildings(region);
        },

        async loadBuildings(region) {
          this.loading = true;
          try {
            const res = await api.get('/api/buildings', { region });
            this.buildings = res.data || [];
          } catch (e) { console.error(e); }
          finally { this.loading = false; }
        },

        async loadHotBuildings() {
          try {
            const res = await api.get('/api/buildings');
            this.buildings = res.data || [];
          } catch (e) { console.error(e); }
        },

        async selectBuilding(building) {
          this.selectedBuilding = building;
          await this.loadBuildingStats(building.id);
        },

        async loadBuildingStats(buildingId) {
          this.statsLoading = true;
          try {
            const seatRes = await api.get('/api/seats');
            const bSeats = (seatRes.data || []).filter(s => s.building_id === buildingId);
            const stats = { total: bSeats.length, free: 0, occupied: 0, locked: 0, error: 0 };
            bSeats.forEach(s => { if (stats[s.status] !== undefined) stats[s.status]++; });
            this.stats = stats;
          } catch (e) { console.error(e); }
          finally { this.statsLoading = false; }
        },

        backToList() {
          this.selectedBuilding = null;
          this.stats = null;
        },

        enterBuilding(id) { window.location.href = `seat-map.html?building_id=${id}`; },
        navigateTo(buildingId) { window.location.href = `navigation.html?building_id=${buildingId}`; },
        reserveAt(buildingId) { window.location.href = `reservation.html?building_id=${buildingId}`; },
      },
    }).mount('#app');
    console.log('[首页] Vue 已挂载');
  } catch (e) {
    console.error('[首页] Vue 初始化失败:', e);
    document.querySelectorAll('[v-cloak]').forEach(function (el) { el.removeAttribute('v-cloak') });
  }
})();

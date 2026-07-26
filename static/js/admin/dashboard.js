/* 管理后台首页 Vue 应用 */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      simStatus: '',
      setupItems: [],
    };
  },
  created() { this.loadSetupStatus(); },
  methods: {
    async loadSetupStatus() {
      try {
        const [bRes, sRes, netRes] = await Promise.all([
          api.get('/api/buildings'),
          api.get('/api/status'),
          api.get('/api/seats'),
        ]);
        const buildings = bRes.data || [];
        const seats = sRes.data || { total: 0 };
        const totalSeats = seats.total || (netRes.data || []).length;
        this.setupItems = [
          { label: '添加场所', done: buildings.length > 0, link: '/admin/buildings' },
          { label: '添加楼层与座位', done: totalSeats > 0, link: '/admin/floor-plan' },
          { label: '上传平面图（可选）', done: false, link: '/uploading' },
          { label: '配置锁定参数', done: true, link: '/admin/settings' },
        ];
      } catch (e) { console.error(e); }
    },
    async startSimulator() {
      try {
        const res = await api.post('/api/admin/simulator/start', { seat_count: 50 });
        this.simStatus = res.message || '模拟器已启动';
        showToast('模拟器已启动');
      } catch (e) { }
    },
    async stopSimulator() {
      try {
        await api.post('/api/admin/simulator/stop');
        this.simStatus = '模拟器已停止';
        showToast('模拟器已停止');
      } catch (e) { }
    },
  },
}).mount('#app');

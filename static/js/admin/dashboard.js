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
        // 统计各楼层平面图上传情况（按建筑）
        let totalFloors = 0;
        let planFloors = 0;
        const bldPlanInfo = [];
        for (const b of buildings) {
          try {
            const detail = await api.get('/api/buildings/' + b.id);
            const floors = detail.data?.floors || [];
            const withPlan = floors.filter(f => f.floor_plan_path);
            totalFloors += floors.length;
            planFloors += withPlan.length;
            if (withPlan.length) bldPlanInfo.push(`${b.name}: ${withPlan.length}/${floors.length}`);
          } catch (e) { }
        }
        this.setupItems = [
          { label: '添加场所', done: buildings.length > 0, link: '/admin/buildings', optional: false },
          { label: '添加楼层与座位', done: totalSeats > 0, link: '/admin/floor-plan', optional: false },
          { label: `平面图 (${planFloors}/${totalFloors} 楼层)`, done: planFloors > 0, link: '/uploading', optional: true, detail: bldPlanInfo.length ? bldPlanInfo.join(' | ') : '暂无' },
          { label: '配置锁定参数', done: true, link: '/admin/settings', optional: false },
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

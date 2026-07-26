/* 行为分析页面 Vue 应用 */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],
  data() {
    return { abnormalUsers: [], loading: false };
  },
  methods: {
    async loadAbnormal() {
      this.loading = true;
      try {
        const res = await api.get('/api/admin/abnormal-users');
        this.abnormalUsers = res.data || [];
        if (!this.abnormalUsers.length) showToast('当前无异常用户');
      } catch (e) { }
      finally { this.loading = false; }
    },
    async loadAllReports() {
      this.loading = true;
      try {
        showToast('功能开发中，请先查看异常用户');
      } catch (e) { }
      finally { this.loading = false; }
    },
  },
}).mount('#app');

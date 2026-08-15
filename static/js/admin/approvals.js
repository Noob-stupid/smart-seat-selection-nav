/* 管理员审核页 - 待审核管理员列表（通过/驳回）
   对应后端接口：
     GET  /api/admin/pending-users
     POST /api/admin/approve/<user_id>
     POST /api/admin/reject/<user_id>
   （本文件为 feature/update-frontend 分支缺失文件，逻辑移植自旧版
    templates/admin/approvals.html 内联脚本，与新版纯模板结构配套） */
(function () {
  if (typeof Vue === 'undefined') return;
  Vue.createApp({
    delimiters: ['${', '}'],
    data: function () {
      return { users: [], loading: true, error: '' };
    },
    created: function () { this.load(); },
    methods: {
      load: async function () {
        this.loading = true;
        try {
          var r = await api.get('/api/admin/pending-users');
          this.users = r.data || [];
        } catch (e) { this.error = '加载失败'; }
        finally { this.loading = false; }
      },
      approve: async function (id) {
        try {
          await api.post('/api/admin/approve/' + id);
          this.load();
          showToast('审核通过');
        } catch (e) { showToast('操作失败', 'error'); }
      },
      reject: async function (id) {
        if (!confirm('驳回后将降为普通用户，确定？')) return;
        try {
          await api.post('/api/admin/reject/' + id);
          this.load();
          showToast('已驳回');
        } catch (e) { showToast('操作失败', 'error'); }
      }
    }
  }).mount('#app');
})();

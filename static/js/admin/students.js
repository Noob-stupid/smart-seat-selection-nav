/* ============================================================
   管理端 · 学生管理（批量导入 + 名单）
   ============================================================ */
const { createApp } = Vue;

createApp({
  delimiters: ['${', '}'],

  data() {
    return {
      dragging: false,
      uploading: false,
      error: '',
      report: null,
      students: [],
      total: 0,
      q: '',
      loading: false,
    };
  },

  mounted() {
    this.loadStudents();
  },

  methods: {
    /** 角色文案以服务端 role_label 为准，缺失时按 role 兜底 */
    roleText(s) {
      if (s && s.role_label) return s.role_label;
      var r = (s && s.role) || s;
      return { student: '普通用户', admin: '管理员',
               super_admin: '超级管理员' }[r] || r;
    },

    downloadTemplate() {
      // 走真实后端下载模板；失败则提示
      window.location.href = '/api/admin/students/import/template';
    },

    onPick(e) {
      const f = e.target.files && e.target.files[0];
      if (f) this.upload(f);
      e.target.value = '';           // 允许重复选同一文件
    },

    onDrop(e) {
      this.dragging = false;
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) this.upload(f);
    },

    async upload(file) {
      this.error = '';
      this.report = null;
      const name = (file.name || '').toLowerCase();
      if (!/\.(xlsx|xlsm|csv)$/.test(name)) {
        this.error = '仅支持 .xlsx / .csv 文件';
        return;
      }
      if (file.size > 8 * 1024 * 1024) {
        this.error = '文件超过 8MB';
        return;
      }

      this.uploading = true;
      try {
        const fd = new FormData();
        fd.append('file', file);
        const res = await axios.post('/api/admin/students/import', fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        const body = res.data || {};
        if (body.code === 200) {
          this.report = body.data;
          showToast(body.message || '导入完成', 'success');
          this.loadStudents();
        } else {
          this.error = body.message || '导入失败';
        }
      } catch (err) {
        const d = (err.response && err.response.data) || {};
        this.error = d.message || '导入失败，请检查文件格式';
      } finally {
        this.uploading = false;
      }
    },

    async loadStudents() {
      this.loading = true;
      try {
        const res = await axios.get('/api/admin/students', {
          params: { q: this.q, role: 'student', size: 200 },
        });
        const d = (res.data && res.data.data) || {};
        this.students = d.students || [];
        this.total = d.total || 0;
      } catch (e) {
        this.students = [];
        this.total = 0;
      } finally {
        this.loading = false;
      }
    },
  },
}).mount('#app');

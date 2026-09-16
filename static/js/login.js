/* 登录页 */
try { localStorage.removeItem('seat_app_current_user'); } catch (e) { }
Vue.createApp({
  delimiters: ['${', '}'],
  
  data() {
    return {
      tab: 'login',
      studentId: '', name: '', password: '', confirmPassword: '', role: 'student',
      schoolId: '', schools: [],
      loading: false, error: '',
    };
  },
  mounted: function () {
    this.loadSchools();
  },
  methods: {
    /** 加载学校列表（/api/schools 公开可读，供注册下拉使用） */
    loadSchools: async function () {
      try {
        var res = await axios.get('/api/schools');
        this.schools = (res.data && res.data.data) || [];
      } catch (e) {
        this.schools = [];
      }
    },

    doLogin: async function () {
      if (!this.studentId || !this.password) { this.error = '请填写账号和密码'; return; }
      this.loading = true; this.error = '';
      try {
        var res = await axios.post('/api/auth/login', { student_id: this.studentId, password: this.password });
        if (res.data.code === 200) {
          location.href = new URLSearchParams(location.search).get('next') || 'index.html';
        } else { this.error = res.data.message || '登录失败'; }
      } catch (e) {
        this.error = (e.response && e.response.data && e.response.data.message) || '登录失败，请检查账号和密码';
      } finally { this.loading = false; }
    },
    doRegister: async function () {
      if (!this.schoolId) { this.error = '请选择所属学校'; return; }
      if (!this.studentId || !this.name || !this.password) { this.error = '请填写完整信息'; return; }
      if (this.password.length < 6) { this.error = '密码至少6位'; return; }
      if (this.password !== this.confirmPassword) { this.error = '两次输入的密码不一致'; return; }
      this.loading = true; this.error = '';
      try {
        var res = await axios.post('/api/auth/register', {
          student_id: this.studentId, name: this.name,
          password: this.password, confirm_password: this.confirmPassword,
          role: this.role === 'admin' ? 'admin' : 'student',
          school_id: this.schoolId,
        });
        if (res.data.code === 201) {
          this.error = ''; this.tab = 'login';
          alert(res.data.message || '注册成功');
        } else { this.error = res.data.message || '注册失败'; }
      } catch (e) {
        this.error = (e.response && e.response.data && e.response.data.message) || '注册失败';
      } finally { this.loading = false; }
    },
  },
}).mount('#app');

/* 登录页 */
Vue.createApp({
  delimiters: ['${', '}'],
  data() {
    return {
      tab: 'login',
      studentId: '', name: '', password: '', confirmPassword: '', role: 'student',
      loading: false, error: '',
    };
  },
  methods: {
    doLogin: async function () {
      if (!this.studentId || !this.password) { this.error = '请填写账号和密码'; return; }
      this.loading = true; this.error = '';
      try {
        var res = await axios.post('/api/auth/login', { student_id: this.studentId, password: this.password });
        if (res.data.code === 200) {
          location.href = new URLSearchParams(location.search).get('next') || '/';
        } else { this.error = res.data.message || '登录失败'; }
      } catch (e) {
        this.error = (e.response && e.response.data && e.response.data.message) || '登录失败，请检查账号和密码';
      } finally { this.loading = false; }
    },
    doRegister: async function () {
      if (!this.studentId || !this.name || !this.password) { this.error = '请填写完整信息'; return; }
      if (this.password.length < 6) { this.error = '密码至少6位'; return; }
      if (this.password !== this.confirmPassword) { this.error = '两次输入的密码不一致'; return; }
      this.loading = true; this.error = '';
      try {
        var res = await axios.post('/api/auth/register', {
          student_id: this.studentId, name: this.name,
          password: this.password, confirm_password: this.confirmPassword,
          role: this.role === 'admin' ? 'admin' : 'student',
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

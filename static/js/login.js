/* 登录页 */
try { localStorage.removeItem('seat_app_current_user'); } catch (e) { }
Vue.createApp({
  delimiters: ['${', '}'],
  
  data() {
    return {
      tab: 'login',
      studentId: '', name: '', password: '', confirmPassword: '', role: 'student',
      schoolName: '', schools: [],
      // 需要填写学校的身份：学生 / 学校管理员
      schoolRoles: ['student', 'school_admin'],
      loading: false, error: '',
    };
  },
  computed: {
    /** 只有「学生 / 学校管理员」才需要填所属学校 */
    needSchool: function () {
      return this.schoolRoles.indexOf(this.role) >= 0;
    },
  },
  watch: {
    role: function () {
      // 切到不需要学校的身份时，顺手清掉校验错误
      if (!this.needSchool) this.error = '';
    },
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
      // 手机上自动填充/输入法常带首尾空格，先去掉
      this.studentId = String(this.studentId || '').trim();
      this.password = String(this.password || '');
      if (!this.studentId || !this.password) { this.error = '请填写账号和密码'; return; }
      this.password = this.password.trim();

      // 中文输入法下 @ 很容易打成全角 ＠，服务器比的是半角 —— 直接说清楚
      var full = this.password.match(/[\uFF01-\uFF5E\u3000]/);
      if (full) {
        this.error = '密码里有全角字符「' + full[0] + '」（中文输入法打出来的）。'
          + '请把输入法切到英文半角再输一遍。';
        return;
      }

      this.loading = true; this.error = '';
      try {
        var res = await axios.post('/api/auth/login', { student_id: this.studentId, password: this.password });
        if (res.data.code !== 200) { this.error = res.data.message || '登录失败'; return; }

        // 接口成功了，还要确认「浏览器真的把登录状态存住了」。
        // 无痕模式 / 禁用 Cookie / 用了 www 或 IP 打开时，接口照样返回成功，
        // 但下一次请求就不认识你了 —— 表现成「登完又跳回登录页」，
        // 用户完全不知道发生了什么。这里先验证一次，失败就直说原因。
        if (!await this.verifySession()) { this.error = this.sessionHint(); return; }

        location.href = new URLSearchParams(location.search).get('next') || 'index.html';
      } catch (e) {
        this.error = (e.response && e.response.data && e.response.data.message)
          || ('登录失败：' + (e.message || '网络异常'));
      } finally { this.loading = false; }
    },

    /** 登录后立刻问服务端一句「你认得我吗」 */
    verifySession: async function () {
      try {
        var r = await axios.get('/api/auth/me');
        var d = r.data && r.data.data;
        return !!(d && (d.user_id || d.id || d.student_id));
      } catch (e) { return false; }
    },

    /** 登录状态存不住时，把可能原因直接列出来，别让用户猜 */
    sessionHint: function () {
      var tips = [];
      if (!navigator.cookieEnabled) tips.push('浏览器禁用了 Cookie');

      if (location.hostname !== 'zhinengzuo.site') {
        tips.push('当前地址是 ' + location.origin + '，请改用 https://zhinengzuo.site 打开'
          + '（登录状态按域名保存，带 www 或用 IP 都存不住）');
      }
      if (/MicroMessenger|QQ\/|DingTalk|AlipayClient|Weibo|UCBrowser/i.test(navigator.userAgent)) {
        tips.push('当前是 App 内置浏览器（微信/QQ 等），请点右上角「在浏览器打开」');
      }
      try {
        if (window.self !== window.top) tips.push('页面被嵌在别的页面里（iframe），Cookie 可能被拦截');
      } catch (e) {
        tips.push('页面被嵌在别的页面里（iframe），Cookie 可能被拦截');
      }
      if (!tips.length) {
        tips.push('可能处于无痕 / 隐私模式，关掉无痕再登录');
        tips.push('或浏览器设成了「退出时清除 Cookie」');
      }
      return '登录成功，但浏览器没保存登录状态。原因可能是：' + tips.join('；') + '。';
    },
    doRegister: async function () {
      if (this.needSchool && !this.schoolName) {
        this.error = '请填写所属学校（可手动输入校名）';
        return;
      }
      if (!this.studentId || !this.name || !this.password) { this.error = '请填写完整信息'; return; }
      if (this.password.length < 6) { this.error = '密码至少6位'; return; }
      if (this.password !== this.confirmPassword) { this.error = '两次输入的密码不一致'; return; }
      this.loading = true; this.error = '';
      try {
        var res = await axios.post('/api/auth/register', {
          student_id: this.studentId, name: this.name,
          password: this.password, confirm_password: this.confirmPassword,
          role: this.role,
          // 仅需要学校的身份才提交；后端按校名查找或新建
          school_name: this.needSchool ? this.schoolName : '',
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

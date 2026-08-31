/* 登录页 */
try { localStorage.removeItem('seat_app_current_user'); } catch (e) { }
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
          location.href = normalizePath(new URLSearchParams(location.search).get('next') || '/');
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

/* 雾水背景 / 鼠标柔光 / 点击涟漪 */
(function () {
  'use strict';
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function mountEffects() {
    if (document.getElementById('shuimo-fog')) return;
    var fog = document.createElement('div');
    fog.className = 'fog';
    fog.id = 'shuimo-fog';
    ['a', 'b', 'c'].forEach(function (name) {
      var span = document.createElement('span');
      span.className = name;
      fog.appendChild(span);
    });
    document.body.appendChild(fog);

    var glow = document.createElement('div');
    glow.className = 'cursor-glow';
    document.body.appendChild(glow);
  }

  mountEffects();

  document.addEventListener('pointerdown', function (e) {
    if (reduced) return;
    var el = e.target.closest('button, .choose-card, .venue-card, .region-tag, .time-slot, .tag-chip, .path-segment');
    if (!el) return;
    var cs = getComputedStyle(el);
    if (cs.position === 'static') el.style.position = 'relative';
    if (cs.overflow !== 'hidden' && cs.overflow !== 'auto' && cs.overflow !== 'scroll') el.style.overflow = 'hidden';
    var r = el.getBoundingClientRect();
    var s = Math.max(r.width, r.height);
    var sp = document.createElement('span');
    sp.className = 'ripple';
    sp.style.width = sp.style.height = s + 'px';
    sp.style.left = (e.clientX - r.left - s / 2) + 'px';
    sp.style.top = (e.clientY - r.top - s / 2) + 'px';
    el.appendChild(sp);
    sp.addEventListener('animationend', function () {
      sp.remove();
    });
  });

  var glow = document.querySelector('.cursor-glow');
  if (glow && !reduced && window.matchMedia && window.matchMedia('(pointer: fine)').matches) {
    var tx = window.innerWidth / 2;
    var ty = window.innerHeight / 2;
    var cx = tx;
    var cy = ty;
    window.addEventListener('pointermove', function (e) {
      tx = e.clientX;
      ty = e.clientY;
    }, { passive: true });
    (function loop() {
      cx += (tx - cx) * 0.12;
      cy += (ty - cy) * 0.12;
      glow.style.transform = 'translate(' + (cx - 110) + 'px,' + (cy - 110) + 'px)';
      window.requestAnimationFrame(loop);
    })();
  } else if (glow) {
    glow.style.display = 'none';
  }
})();

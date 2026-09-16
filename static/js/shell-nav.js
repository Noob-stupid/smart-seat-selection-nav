/* 静态外壳脚本：导航高亮 + 登录态 + 角色区分
   ------------------------------------------------------------------
   原 templates/base.html 依赖 Flask 渲染时的两个判断：
     {% if request.path == '/seat-map' %}active{% endif %}   → 当前页导航高亮
     {% if session.get('user_id') %} … {% endif %}           → 登录态与退出按钮
     {% if session.get('role') in ('admin','super_admin') %} → 仅管理员显示「管理」

   本文件按**混合模式**处理身份，规则如下：

   1) 真实后端在（页面引了 api-client.js，window.__REAL_API_AVAILABLE 为真）
      -> 调 GET /api/auth/me 取**服务端 session 的真实身份**：
         姓名、角色（学生/管理员/超级管理员）、所属学校。
         非管理员隐藏「管理」入口；非学校管理员隐藏「导入学生」入口。
      -> 取不到（未登录 / 后端不可达）时**默认按非管理员处理**（fail-safe），
         绝不因为读不到身份就放开管理入口。

   2) 纯静态演示（没有 api-client.js，双击 html 打开）
      -> 退回读 localStorage 的演示身份；读不到则沿用原有「演示用户 / 管理员」，
         保证静态演示仍可完整浏览。

   3) 退出登录
      -> 真实模式下调 /logout 清服务端 session，再回登录页；
         静态演示只清本地。
*/
(function () {
  'use strict';

  var USER_KEY = 'seat_app_current_user';
  var ROLE_LABEL = {
    student: '学生',
    admin: '管理员',
    super_admin: '超级管理员',
  };
  var FILE_GROUPS = {
    index: 'index',
    seat_map: 'seat_map',
    reservation: 'reservation',
    navigation: 'navigation',
    outdoor: 'outdoor',
  };

  /** 是否纯静态演示环境（没有加载 api-client.js） */
  function isStaticDemo() {
    return !window.__REAL_API_AVAILABLE;
  }

  function currentGroup() {
    if (/\/admin\//.test(location.pathname)) return 'admin';
    var name = location.pathname.split('/').pop().replace(/\.html$/, '');
    if (name === '' || name === 'index') return 'index';
    return FILE_GROUPS[name] || null;
  }

  function applyActive() {
    var group = currentGroup();
    var links = document.querySelectorAll('.nav-links a[data-nav]');
    for (var i = 0; i < links.length; i++) {
      if (links[i].getAttribute('data-nav') === group) links[i].classList.add('active');
      else links[i].classList.remove('active');
    }
  }

  function readDemoUser() {
    try {
      var raw = localStorage.getItem(USER_KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) { }
    return null;
  }

  /** 请求服务端当前用户；返回 user / null(未登录) / undefined(后端不可达) */
  function fetchMe() {
    if (typeof fetch !== 'function') return Promise.resolve(undefined);
    return fetch('/api/auth/me', {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) return null;   // 未登录
      if (!res.ok) return undefined;
      return res.json().then(function (body) {
        return (body && body.data) || null;
      });
    }).catch(function () { return undefined; });                    // 网络失败
  }

  function setDisplay(selector, visible) {
    var els = document.querySelectorAll(selector);
    for (var i = 0; i < els.length; i++) {
      els[i].style.display = visible ? '' : 'none';
    }
  }

  /**
   * 应用身份到页面。
   * @param {object|null|undefined} user 服务端用户；null=未登录；undefined=后端不可达
   */
  function applyIdentity(user) {
    var name, role, isAdmin, hasSchool, loggedIn;

    if (user) {
      name = user.name || user.student_id || '用户';
      role = user.role || 'student';
      hasSchool = !!user.school_id;
      loggedIn = true;
    } else if (isStaticDemo() && user !== null) {
      // 纯静态演示：保留原行为
      var demo = readDemoUser();
      name = (demo && (demo.name || demo.student_id)) || '演示用户';
      role = (demo && demo.role) || 'admin';
      hasSchool = true;
      loggedIn = true;
    } else {
      name = '未登录';
      role = null;
      hasSchool = false;
      loggedIn = false;
    }
    isAdmin = role === 'admin' || role === 'super_admin';

    // 姓名
    var nameEls = document.querySelectorAll('[data-user-name]');
    for (var i = 0; i < nameEls.length; i++) nameEls[i].textContent = name;

    // 角色徽章（三种角色区分显示）
    var roleEls = document.querySelectorAll('[data-user-role]');
    for (var j = 0; j < roleEls.length; j++) {
      roleEls[j].textContent = loggedIn ? (ROLE_LABEL[role] || role) : '未登录';
      roleEls[j].className = 'role-badge ' + (isAdmin ? 'admin' : 'user');
      roleEls[j].style.display = loggedIn ? '' : 'none';
    }

    // 管理入口：仅管理员可见（与后端 admin_required 一致）
    setDisplay('.nav-links a[data-nav="admin"]', isAdmin);

    // 需要学校身份的入口（如批量导入学生）：仅「有学校的管理员」可见
    setDisplay('[data-requires-school]', isAdmin && hasSchool);

    // 未登录时隐藏退出按钮
    setDisplay('[data-logout]', loggedIn);

    // 供页面脚本复用（避免各自重复请求 /api/auth/me）
    window.CURRENT_USER = user || null;
    window.CURRENT_USER_READY = true;
  }

  function applyLogout() {
    var btns = document.querySelectorAll('[data-logout]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function (e) {
        e.preventDefault();
        try { localStorage.removeItem(USER_KEY); } catch (err) { }
        if (isStaticDemo() || typeof fetch !== 'function') {
          location.href = 'login.html';
          return;
        }
        // 真实模式：必须清服务端 session，否则刷新后仍是登录态
        fetch('/logout', { credentials: 'same-origin', redirect: 'manual' })
          .catch(function () { })
          .then(function () { location.href = '/login'; });
      });
    }
  }

  function init() {
    applyActive();
    applyLogout();

    if (isStaticDemo()) {
      applyIdentity(undefined);            // 直接用演示身份
      return;
    }
    // 先按「未登录」渲染，避免读到身份前短暂显示管理员入口
    applyIdentity(null);
    fetchMe().then(function (user) {
      applyIdentity(user === undefined ? null : user);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

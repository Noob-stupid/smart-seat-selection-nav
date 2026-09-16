/* 静态外壳脚本：导航高亮 + 登录态 + 角色区分
   ------------------------------------------------------------------
   原 templates/base.html 由 Flask 服务端渲染四件事：
     {% if request.path == '/seat-map' %}active{% endif %}          → 导航高亮
     {% if session.get('role') in ('admin','super_admin') %}        → 仅管理员显示「管理」
     {% if user_avatar %}<img class="avatar">{% else %}占位图标{% endif %} → 头像
     {% if session.get('user_id') %} 用户区 {% else %} 登录按钮 {% endif %}
   纯静态环境没有 session，本文件在浏览器端把这四件事补齐。

   ★ 本文件遵循「只叠加、不修改」：
     模板里的原有结构与文案一律保留，只在其上补充真实身份；
     任何一项拿不到数据时，都退回模板原本的静态表现，不做删除。

   身份来源（混合模式，与项目其它降级设计一致）：
     1) 真实后端在（页面引了 api-client.js，window.__REAL_API_AVAILABLE 为真）
        -> GET /api/auth/me 取服务端 session 的真实身份：
           姓名 / 角色 / 头像 / 所属学校
     2) 纯静态演示（双击 html）-> 保留 localStorage 演示身份，
        沿用原有「演示用户 / 管理员」，静态演示仍可完整浏览
     3) 读不到身份时**默认按非管理员处理**（fail-safe）

   角色文案与 profile.html、login.html 保持一致：
     普通用户(student) / 管理员(admin) / 超级管理员(super_admin)
*/
(function () {
  'use strict';

  var USER_KEY = 'seat_app_current_user';
  var ROLE_LABEL = {
    student: '普通用户',
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

  /** 纯静态演示环境（没有加载 api-client.js） */
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

  /** 服务端当前用户：user / null(未登录) / undefined(后端不可达) */
  function fetchMe() {
    if (typeof fetch !== 'function') return Promise.resolve(undefined);
    return fetch('/api/auth/me', {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    }).then(function (res) {
      if (res.status === 401 || res.status === 403) return null;
      if (!res.ok) return undefined;
      return res.json().then(function (body) {
        return (body && body.data) || null;
      });
    }).catch(function () { return undefined; });
  }

  function setDisplay(selector, visible) {
    var els = document.querySelectorAll(selector);
    for (var i = 0; i < els.length; i++) els[i].style.display = visible ? '' : 'none';
  }

  /**
   * 头像：旧版是 <img src="{{ user_avatar }}" class="avatar" style="object-fit:cover">，
   * 无头像时才用占位图标。模板里现在是占位图标，这里**在其之上补一层图片**：
   * 有 avatar_url 就把图片填进 .avatar 容器（保持 28×28 圆形，视觉与旧版一致），
   * 没有则原样保留占位图标 —— 不删除、不替换模板结构。
   */
  function applyAvatar(url) {
    var boxes = document.querySelectorAll('.user-info .avatar');
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      var img = box.querySelector('img');
      if (url) {
        if (!img) {
          img = document.createElement('img');
          img.alt = '头像';
          img.style.width = '100%';
          img.style.height = '100%';
          img.style.objectFit = 'cover';
          img.style.borderRadius = '50%';
          img.style.display = 'block';
          box.appendChild(img);
        }
        img.src = url;
        box.style.overflow = 'hidden';
        box.style.padding = '0';
        var icon = box.querySelector('i');
        if (icon) icon.style.visibility = 'hidden';   // 保留节点，仅遮住
      } else if (img) {
        img.remove();
        var ic = box.querySelector('i');
        if (ic) ic.style.visibility = '';
      }
    }
  }

  /**
   * 未登录时：旧版显示「登录」按钮。
   * 这里**新增**一个按钮，并把原有的用户区/退出按钮隐藏 —— 不删除模板节点。
   */
  function applyAnonymous() {
    setDisplay('.user-info-link', false);
    setDisplay('[data-user-role]', false);
    setDisplay('[data-logout]', false);
    var slot = document.querySelector('.user-info');
    if (!slot || slot.querySelector('[data-injected-login]')) return;
    var a = document.createElement('button');
    a.className = 'logout-btn login-btn-header';
    a.setAttribute('data-injected-login', '1');
    a.textContent = '登录';
    a.onclick = function () { location.href = '/login'; };
    slot.appendChild(a);
  }

  /**
   * @param {object|null|undefined} user 服务端用户；null=未登录；undefined=后端不可达
   */
  function applyIdentity(user) {
    var name, role, isAdmin, hasSchool, loggedIn, avatar;

    if (user) {
      name = user.name || user.student_id || '用户';
      role = user.role || 'student';
      hasSchool = !!user.school_id;
      avatar = user.avatar_url || '';
      loggedIn = true;
    } else if (isStaticDemo() && user !== null) {
      // 纯静态演示：保留原有表现
      var demo = readDemoUser();
      name = (demo && (demo.name || demo.student_id)) || '演示用户';
      role = (demo && demo.role) || 'admin';
      avatar = (demo && demo.avatar_url) || '';
      hasSchool = true;
      loggedIn = true;
    } else {
      name = '';
      role = null;
      avatar = '';
      hasSchool = false;
      loggedIn = false;
    }
    isAdmin = role === 'admin' || role === 'super_admin';

    if (!loggedIn) {
      applyAnonymous();
      setDisplay('.nav-links a[data-nav="admin"]', false);
      setDisplay('[data-requires-school]', false);
      applyAvatar('');
      window.CURRENT_USER = null;
      window.CURRENT_USER_READY = true;
      return;
    }

    // 姓名（原有模板文案作为兜底，取到真实姓名时覆盖）
    var nameEls = document.querySelectorAll('[data-user-name]');
    for (var i = 0; i < nameEls.length; i++) nameEls[i].textContent = name;

    // 角色徽章：沿用 profile.html / login.html 的用词（普通用户 / 管理员），
    // 并额外区分出超级管理员
    var roleEls = document.querySelectorAll('[data-user-role]');
    for (var j = 0; j < roleEls.length; j++) {
      roleEls[j].textContent = ROLE_LABEL[role] || role;
      roleEls[j].className = 'role-badge ' + (isAdmin ? 'admin' : 'user');
      roleEls[j].style.display = '';
    }

    // 头像（补回旧版行为）
    applyAvatar(avatar);

    // 登录态下的按钮回归正常
    setDisplay('.user-info-link', true);
    setDisplay('[data-logout]', true);
    var injected = document.querySelector('[data-injected-login]');
    if (injected && injected.parentNode) injected.parentNode.removeChild(injected);

    // 管理入口：仅管理员可见（与后端 admin_required 一致）
    setDisplay('.nav-links a[data-nav="admin"]', isAdmin);

    // 需要学校身份的入口（如批量导入学生）：仅「有学校的管理员」可见
    setDisplay('[data-requires-school]', isAdmin && hasSchool);

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
        // 真实模式：清服务端 session（旧版就是直接跳 /logout）
        fetch('/logout', { credentials: 'same-origin', redirect: 'manual' })
          .catch(function () { })
          .then(function () { location.href = '/login'; });
      });
    }
  }

  function init() {
    applyActive();
    applyLogout();

    if (isStaticDemo()) { applyIdentity(undefined); return; }
    fetchMe().then(function (user) {
      applyIdentity(user === undefined ? null : user);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

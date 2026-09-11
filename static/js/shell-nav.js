/* 静态外壳脚本：导航高亮 + 演示登录态
   ------------------------------------------------------------------
   原 templates/base.html 依赖 Flask 渲染时的两个判断：
     {% if request.path == '/seat-map' %}active{% endif %}   → 当前页导航高亮
     {% if session.get('user_id') %} … {% endif %}           → 登录态与退出按钮
   纯静态环境没有 request/session，这里改用浏览器端判断：
     · 导航高亮：按当前文件名匹配 <a data-nav="…">（admin 目录下统一高亮「管理」）
     · 登录态：读取 localStorage 的演示用户；默认展示「演示用户 / 管理员」
     · 退出：清除本地登录态并回到 login.html（原 /logout 路由）
*/
(function () {
  'use strict';

  var USER_KEY = 'seat_app_current_user';
  var FILE_GROUPS = {
    index: 'index',
    seat_map: 'seat_map',
    reservation: 'reservation',
    navigation: 'navigation',
  };

  function currentGroup() {
    if (/\/admin\//.test(location.pathname)) return 'admin';
    var name = location.pathname.split('/').pop().replace(/\.html$/, '');
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

  function readUser() {
    try {
      var raw = localStorage.getItem(USER_KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) { }
    return null;
  }

  function applyUser() {
    var u = readUser();
    var name = (u && (u.name || u.student_id)) || '演示用户';
    var role = (u && u.role) || 'admin';
    var isAdmin = role === 'admin' || role === 'super_admin';

    var nameEls = document.querySelectorAll('[data-user-name]');
    for (var i = 0; i < nameEls.length; i++) nameEls[i].textContent = name;

    var roleEls = document.querySelectorAll('[data-user-role]');
    for (var j = 0; j < roleEls.length; j++) {
      roleEls[j].textContent = isAdmin ? '管理员' : '用户';
      roleEls[j].className = 'role-badge ' + (isAdmin ? 'admin' : 'user');
    }

    /* 与后端 session 判断保持一致：非管理员隐藏「管理」入口 */
    var adminLinks = document.querySelectorAll('.nav-links a[data-nav="admin"]');
    for (var k = 0; k < adminLinks.length; k++) {
      adminLinks[k].style.display = isAdmin ? '' : 'none';
    }
  }

  function applyLogout() {
    var btns = document.querySelectorAll('[data-logout]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function (e) {
        e.preventDefault();
        try { localStorage.removeItem(USER_KEY); } catch (err) { }
        var prefix = /\/admin\//.test(location.pathname) ? '../' : '';
        location.href = prefix + 'login.html';
      });
    }
  }

  function init() { applyActive(); applyUser(); applyLogout(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

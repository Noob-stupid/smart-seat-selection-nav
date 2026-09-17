/* ============================================================
   智座 · 移动端 App 外壳
   ------------------------------------------------------------
   ★ 只在 App 内生效 ★
   window.Native.available 为假（即普通浏览器）时，本文件直接返回，
   网页版界面一个像素都不动。

   做了什么：
     1. 顶部压成 54px 细条：☰ 抽屉按钮 + 当前页标题 + 头像
     2. 底部 5 个 Tab：首页 / 座位图 / 预约 / 导航 / 我的
     3. 侧边抽屉：品牌、用户名 + 角色徽章、全部导航链接、退出登录
        （链接直接从页面原有的 .nav-links 克隆，因此
          「管理」入口对非管理员隐藏等既有逻辑自动继承）
     4. 「App 模式」角标 3 秒后淡出，不再长期占位
   ============================================================ */
(function () {
  'use strict';

  if (!window.Native || !window.Native.available) return;
  if (window.__APP_SHELL_ON__) return;
  window.__APP_SHELL_ON__ = true;

  /* ---------------- 页面标题 / 底部 Tab 定义 ---------------- */

  var TITLES = {
    index: '智座',
    seat_map: '实时座位图',
    reservation: '我的预约',
    navigation: '室内导航',
    outdoor: '室外导航',
    profile: '个人中心',
    admin: '管理后台',
    login: '登录',
    terminal: '智能终端',
  };

  var TABS = [
    { key: 'index', href: '/index.html', icon: 'fa-home', label: '首页' },
    { key: 'seat_map', href: '/seat_map.html', icon: 'fa-chair', label: '座位图' },
    { key: 'reservation', href: '/reservation.html', icon: 'fa-calendar-check', label: '预约' },
    { key: 'navigation', href: '/navigation.html', icon: 'fa-directions', label: '导航' },
    { key: 'profile', href: '/profile.html', icon: 'fa-user', label: '我的' },
  ];

  function currentKey() {
    var p = location.pathname.replace(/\/+$/, '');
    if (p === '' || p === '/index.html') return 'index';
    if (/seat_map/.test(p)) return 'seat_map';
    if (/reservation/.test(p)) return 'reservation';
    if (/navigation/.test(p)) return 'navigation';
    if (/outdoor/.test(p)) return 'outdoor';
    if (/profile/.test(p)) return 'profile';
    if (/terminal/.test(p)) return 'terminal';
    if (/login/.test(p)) return 'login';
    if (/admin/.test(p)) return 'admin';
    return 'index';
  }

  /* 把模板里的相对链接（admin/dashboard.html、../seat_map.html）规范成站内绝对路径，
     这样从 /admin/xxx.html 打开时抽屉里的链接也不会点错。 */
  function absHref(h) {
    if (!h) return '#';
    if (/^(https?:)?\/\//.test(h) || h.charAt(0) === '/' || h.charAt(0) === '#') return h;
    return '/' + h.replace(/^(\.\.\/)+/, '').replace(/^\.\//, '');
  }

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  /* ---------------- 样式注入 ---------------- */

  function injectCss() {
    var css = window.__APP_SHELL_CSS__;
    if (css) {
      var st = document.createElement('style');
      st.id = 'app-shell-style';
      st.textContent = css;
      document.head.appendChild(st);
      return;
    }
    // 兜底：没被内联进 bundle 时，按普通静态文件引入
    if (document.getElementById('app-shell-style')) return;
    var link = document.createElement('link');
    link.id = 'app-shell-style';
    link.rel = 'stylesheet';
    link.href = '/static/css/mobile-app.css';
    document.head.appendChild(link);
  }

  /* ---------------- 顶部细条 ---------------- */

  function buildTopbar(key) {
    var bar = el('div', 'app-topbar');

    var menu = el('button', 'app-topbar-btn', '<i class="fas fa-bars"></i>');
    menu.type = 'button';
    menu.setAttribute('aria-label', '菜单');
    menu.onclick = function () { toggleDrawer(true); };

    var title = el('span', 'app-topbar-title', TITLES[key] || '智座');

    var avatar = el('a', 'app-topbar-avatar', '<i class="fas fa-user"></i>');
    avatar.href = '/profile.html';
    avatar.setAttribute('data-app-avatar', '1');

    bar.appendChild(menu);
    bar.appendChild(title);
    bar.appendChild(avatar);
    return bar;
  }

  /* ---------------- 底部 Tab ---------------- */

  function buildTabbar(key) {
    var bar = el('nav', 'app-tabbar');
    TABS.forEach(function (t) {
      var a = el('a', 'app-tab' + (t.key === key ? ' active' : ''),
        '<i class="fas ' + t.icon + '"></i><span>' + t.label + '</span>');
      a.href = t.href;
      bar.appendChild(a);
    });
    return bar;
  }

  /* ---------------- 侧边抽屉 ---------------- */

  var maskEl = null, drawerEl = null, pageKey = 'index';

  function toggleDrawer(open) {
    if (!maskEl || !drawerEl) return;
    var want = (open === undefined) ? !drawerEl.classList.contains('open') : !!open;
    drawerEl.classList.toggle('open', want);
    maskEl.classList.toggle('open', want);
    document.documentElement.style.overflow = want ? 'hidden' : '';
  }
  window.AppShell = { open: function () { toggleDrawer(true); }, close: function () { toggleDrawer(false); } };

  /* 导航链接直接从页面原有的 .nav-links 克隆，因此「管理入口仅管理员可见」
     这类既有逻辑自动继承。
     ★ 必须在身份确定（CURRENT_USER_READY）之后重建一次 ——
       刚进页面时 shell-nav.js 还没拿到 /api/auth/me 的结果，
       这时克隆会把「管理」入口也带给匿名用户。 */
  function buildDrawerNav() {
    if (!drawerEl) return;
    var nav = drawerEl.querySelector('.app-drawer-nav');
    if (!nav) return;
    nav.innerHTML = '';

    var src = document.querySelectorAll('.nav-links a[data-nav]');
    var n = 0;
    for (var i = 0; i < src.length; i++) {
      var s = src[i];
      if (s.style.display === 'none') continue;      // 例如非管理员的「管理」入口
      if (s.getAttribute('data-injected-login')) continue;
      var k = s.getAttribute('data-nav');
      var a = el('a', k === pageKey ? 'active' : '', s.innerHTML);
      a.href = absHref(s.getAttribute('href'));
      nav.appendChild(a);
      n++;
    }
    // 一条链接都没有（未登录）时，至少给个回首页的入口
    if (!n) {
      var home = el('a', pageKey === 'index' ? 'active' : '', '<i class="fas fa-home"></i> 首页');
      home.href = '/index.html';
      nav.appendChild(home);
    }
  }

  function buildDrawer(key) {
    maskEl = el('div', 'app-drawer-mask');
    maskEl.onclick = function () { toggleDrawer(false); };

    drawerEl = el('aside', 'app-drawer');

    /* 头部：品牌 + 用户 + 角色 */
    var head = el('div', 'app-drawer-head');
    head.appendChild(el('div', 'app-drawer-brand',
      '<i class="fas fa-map-location-dot"></i> 智座'));
    head.appendChild(el('div', 'app-drawer-sub', '智能选座与导航一体化系统'));

    var userRow = el('div', 'app-drawer-user');
    userRow.appendChild(el('span', '', '<i class="fas fa-user-circle"></i>'));
    var nameSpan = el('span', '', '');
    nameSpan.setAttribute('data-app-user-name', '1');
    userRow.appendChild(nameSpan);
    var roleSpan = el('span', 'app-drawer-role', '');
    roleSpan.setAttribute('data-app-user-role', '1');
    userRow.appendChild(roleSpan);
    head.appendChild(userRow);
    drawerEl.appendChild(head);

    drawerEl.appendChild(el('div', 'app-drawer-nav'));
    buildDrawerNav();

    /* 底部：退出登录（复用页面原有按钮的逻辑与登录态判断） */
    var foot = el('div', 'app-drawer-foot');
    var out = el('button', 'app-drawer-logout', '<i class="fas fa-right-from-bracket"></i> 退出登录');
    out.type = 'button';
    out.onclick = function () {
      var b = document.querySelector('[data-logout]');
      if (b && b.style.display !== 'none') { b.click(); return; }
      location.href = '/logout';
    };
    foot.appendChild(out);
    drawerEl.appendChild(foot);

    return { mask: maskEl, drawer: drawerEl };
  }

  /* ---------------- 用户信息回填 ----------------
     ★ 不能用 [data-user-name] 的 textContent —— 模板里写死的是「演示用户」，
       shell-nav.js 只把容器 display:none 掉，文字还在，读出来就是假的。
       唯一可信来源是 shell-nav.js 设置的 window.CURRENT_USER。 */
  function isLoggedIn() {
    var u = window.CURRENT_USER;
    return !!(u && (u.id || u.user_id || u.student_id || u.name));
  }

  function doLogout() {
    try { localStorage.removeItem('seat_app_current_user'); } catch (e) { }
    var b = document.querySelector('[data-logout]');
    if (b) { b.click(); return; }          // 复用 shell-nav.js 的退出逻辑
    location.href = '/logout';
  }

  function fillUser() {
    var u = window.CURRENT_USER || null;
    var loggedIn = isLoggedIn();

    var name = loggedIn ? (u.name || u.student_id || '用户') : '未登录';
    var role = loggedIn ? (u.role_label || '') : '';

    var target = drawerEl && drawerEl.querySelector('[data-app-user-name]');
    if (target) target.textContent = name;

    var rt = drawerEl && drawerEl.querySelector('[data-app-user-role]');
    if (rt) {
      if (role) { rt.textContent = role; rt.style.display = ''; }
      else { rt.style.display = 'none'; }
    }

    // 顶栏头像：登录了去个人中心，没登录去登录页
    var av = document.querySelector('[data-app-avatar]');
    if (av) {
      av.href = loggedIn ? '/profile.html' : '/login';
      var srcImg = loggedIn ? document.querySelector('.user-info .avatar img') : null;
      if (srcImg && srcImg.src) av.innerHTML = '<img src="' + srcImg.src + '" alt="">';
      else av.innerHTML = '<i class="fas fa-user"></i>';
    }

    // 底部按钮：登录态决定是「退出登录」还是「去登录」
    var outBtn = drawerEl && drawerEl.querySelector('.app-drawer-logout');
    if (outBtn) {
      if (loggedIn) {
        outBtn.className = 'app-drawer-logout';
        outBtn.innerHTML = '<i class="fas fa-right-from-bracket"></i> 退出登录';
        outBtn.onclick = doLogout;
      } else {
        outBtn.className = 'app-drawer-logout app-drawer-login';
        outBtn.innerHTML = '<i class="fas fa-right-to-bracket"></i> 去登录';
        outBtn.onclick = function () { location.href = '/login'; };
      }
    }

    // 身份确定后重建抽屉链接（管理入口的可见性此时才是准的）
    buildDrawerNav();
  }

  function whenUserReady(fn) {
    if (window.CURRENT_USER_READY) { fn(); return; }
    var tries = 0;
    var t = setInterval(function () {
      if (window.CURRENT_USER_READY || ++tries > 40) { clearInterval(t); fn(); }
    }, 200);
  }

  /* ---------------- 启动 ---------------- */

  function boot() {
    if (!document.body) return;
    injectCss();
    document.body.classList.add('app-mode');

    var key = currentKey();
    pageKey = key;

    document.body.appendChild(buildTopbar(key));
    document.body.appendChild(buildTabbar(key));
    var d = buildDrawer(key);
    document.body.appendChild(d.mask);
    document.body.appendChild(d.drawer);

    whenUserReady(fillUser);

    // 抽屉链接里的当前页高亮，在身份确定后重新算一次（管理入口可能刚出现）
    whenUserReady(function () {
      setTimeout(function () {
        if (drawerEl) fillUser();
      }, 400);
    });

    // 「App 模式」角标：亮 3 秒后淡出，不再长期占地方
    setTimeout(function () {
      var b = document.getElementById('feat-badge');
      if (!b) return;
      b.style.transition = 'opacity .6s';
      b.style.opacity = '0';
      setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 700);
    }, 3000);

    console.log('[AppShell] 智座移动端外壳已启用, 当前页 =', key);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

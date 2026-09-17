/* ============================================================
   悬浮按钮长按拖动（只有 App 内生效）
   ------------------------------------------------------------
   目标：AI 助手气泡、扫码占座按钮
   交互：
     · 长按 ~0.45 秒进入拖动模式（震动一下 + 视觉反馈）
     · 拖动跟随手指，自动夹在屏幕内
     · 松手把位置写进本机，下次打开沿用
     · 短按/单击行为完全不变（该开 AI 还是开 AI，该扫码还是扫码）
     · 拖动结束后的那一次 click 会被吞掉，避免误触

   为什么单独一个文件：这两个按钮分别由 ai-assistant.js 和
   native-features.js 动态创建，时机不定，所以这里用
   MutationObserver + 定时扫描兜住。

   ★ 只在 window.Native.available 为真（App 内）时运行，
     浏览器里直接 return，网页版不受影响。
   ============================================================ */
(function () {
  'use strict';

  if (!window.Native || !window.Native.available) return;
  if (window.__FAB_DRAG_ON__) return;
  window.__FAB_DRAG_ON__ = true;

  var HOLD_MS = 450;          // 长按判定
  var MOVE_TOL = 8;           // 长按期间允许的抖动
  var EDGE = 6;               // 离屏幕边缘留白
  var KEY = 'fab_pos_v1';

  var TARGETS = [
    { sel: '.aias-root', id: 'ai', name: 'AI 助手' },
    { sel: '#feat-scan-fab', id: 'scan', name: '扫码占座' }
  ];

  /* ---------------- 位置存取 ---------------- */
  function readAll() {
    try {
      var v = JSON.parse(localStorage.getItem(KEY) || '{}');
      return (v && typeof v === 'object') ? v : {};
    } catch (e) { return {}; }
  }

  function writeAll(o) {
    try { localStorage.setItem(KEY, JSON.stringify(o)); } catch (e) { }
  }

  function resetAll() {
    try { localStorage.removeItem(KEY); } catch (e) { }
    TARGETS.forEach(function (t) {
      var el = document.querySelector(t.sel);
      if (!el) return;
      ['left', 'top', 'right', 'bottom'].forEach(function (p) {
        el.style.removeProperty(p);
      });
      delete el.dataset.fabLeft;
      delete el.dataset.fabTop;
    });
  }

  /* ---------------- 移动 + 夹在屏幕内 ---------------- */
  function moveTo(el, left, top) {
    var r = el.getBoundingClientRect();
    var w = r.width || 44, h = r.height || 44;
    var maxX = Math.max(EDGE, window.innerWidth - w - EDGE);
    var maxY = Math.max(EDGE, window.innerHeight - h - EDGE);
    left = Math.max(EDGE, Math.min(maxX, left));
    top = Math.max(EDGE, Math.min(maxY, top));

    // 样式表里有 bottom:...!important，所以这里也必须 important 才盖得住
    el.style.setProperty('left', left + 'px', 'important');
    el.style.setProperty('top', top + 'px', 'important');
    el.style.setProperty('right', 'auto', 'important');
    el.style.setProperty('bottom', 'auto', 'important');
    el.dataset.fabLeft = String(Math.round(left));
    el.dataset.fabTop = String(Math.round(top));
  }

  function applySaved(id, el) {
    var p = readAll()[id];
    if (!p || !isFinite(p.left) || !isFinite(p.top)) return false;
    // 等一帧，让按钮尺寸定下来再按边界夹一次
    requestAnimationFrame(function () { moveTo(el, p.left, p.top); });
    return true;
  }

  function save(id, el) {
    var l = parseFloat(el.dataset.fabLeft), t = parseFloat(el.dataset.fabTop);
    if (!isFinite(l) || !isFinite(t)) return;
    var all = readAll();
    all[id] = { left: l, top: t };
    writeAll(all);
  }

  /* ---------------- 绑定一个按钮 ---------------- */
  function attach(el, id) {
    if (!el || el.__fabDrag) return;
    el.__fabDrag = true;

    // 小圆钮不需要靠"在它上面滑动"来滚页面，直接吃掉手势
    el.style.touchAction = 'none';
    el.style.webkitUserSelect = 'none';
    el.style.userSelect = 'none';
    el.style.webkitTouchCallout = 'none';

    var st = { down: false, dragging: false, timer: null, sx: 0, sy: 0, ox: 0, oy: 0, swallow: false };

    el.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button !== 0 && e.pointerType === 'mouse') return;
      st.down = true;
      st.dragging = false;
      st.sx = e.clientX;
      st.sy = e.clientY;
      var r = el.getBoundingClientRect();
      st.ox = r.left;
      st.oy = r.top;
      clearTimeout(st.timer);
      st.timer = setTimeout(function () {
        if (!st.down) return;
        st.dragging = true;
        el.classList.add('fab-dragging');
        try { el.setPointerCapture(e.pointerId); } catch (err) { }
        try { window.Native.vibrate && window.Native.vibrate(18); } catch (err) { }
      }, HOLD_MS);
    });

    el.addEventListener('pointermove', function (e) {
      if (!st.down) return;
      if (!st.dragging) {
        // 还没到长按时间就滑走了 -> 当成普通滑动，取消长按
        if (Math.abs(e.clientX - st.sx) > MOVE_TOL ||
            Math.abs(e.clientY - st.sy) > MOVE_TOL) {
          clearTimeout(st.timer);
          st.down = false;
        }
        return;
      }
      e.preventDefault();
      moveTo(el, st.ox + (e.clientX - st.sx), st.oy + (e.clientY - st.sy));
    });

    function end() {
      clearTimeout(st.timer);
      if (st.dragging) {
        st.dragging = false;
        el.classList.remove('fab-dragging');
        save(id, el);
        // 吞掉紧跟其后的那次 click
        st.swallow = true;
        setTimeout(function () { st.swallow = false; }, 400);
      }
      st.down = false;
    }

    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
    el.addEventListener('pointerleave', function () { if (!st.dragging) end(); });

    // 捕获阶段拦掉拖动后的误触
    el.addEventListener('click', function (e) {
      if (st.swallow) {
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);

    el.title = (el.title ? el.title + ' · ' : '') + '长按可拖动';
  }

  /* ---------------- 扫描 + 应用 ---------------- */
  function scan() {
    TARGETS.forEach(function (t) {
      var el = document.querySelector(t.sel);
      if (!el || el.__fabDrag) return;
      attach(el, t.id);
      applySaved(t.id, el);
    });
  }

  var pending = null;
  function scheduleScan() {
    if (pending) return;
    pending = setTimeout(function () { pending = null; scan(); }, 200);
  }

  /* ---------------- 设置面板里加「复位」 ---------------- */
  function hookPanel() {
    var mo = new MutationObserver(function () {
      var panel = document.getElementById('ns-panel');
      if (!panel || panel.querySelector('[data-fab-reset]')) return;
      var card = panel.firstElementChild;
      if (!card) return;

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('data-fab-reset', '1');
      btn.innerHTML = '<i class="fas fa-arrows-up-down-left-right"></i> 复位悬浮按钮位置';
      btn.style.cssText = 'margin-top:12px;width:100%;padding:10px;border:1px solid #dbe4f0;'
        + 'border-radius:10px;background:#f7fafd;color:#1a73e8;font-size:13.5px;'
        + 'font-family:inherit;cursor:pointer;';
      btn.onclick = function () {
        resetAll();
        btn.innerHTML = '<i class="fas fa-check"></i> 已复位';
        setTimeout(function () {
          btn.innerHTML = '<i class="fas fa-arrows-up-down-left-right"></i> 复位悬浮按钮位置';
        }, 1500);
      };
      card.appendChild(btn);
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  /* ---------------- 启动 ---------------- */
  function boot() {
    scan();
    hookPanel();
    // 按钮是异步创建的，用观察者 + 兜底轮询双重保险
    try {
      new MutationObserver(scheduleScan).observe(document.body, {
        childList: true, subtree: true
      });
    } catch (e) { }
    var n = 0;
    var t = setInterval(function () {
      scan();
      if (++n > 40) clearInterval(t);   // 最多盯 20 秒
    }, 500);
    // 转屏/改窗口大小后重新夹一次
    window.addEventListener('resize', function () {
      TARGETS.forEach(function (tg) {
        var el = document.querySelector(tg.sel);
        if (el && el.dataset.fabLeft) {
          moveTo(el, parseFloat(el.dataset.fabLeft), parseFloat(el.dataset.fabTop));
        }
      });
    });
    console.log('[FabDrag] 长按拖动已启用（AI 助手 / 扫码占座）');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

/* ============================================================
   AI 助手浮窗（全局）
   ------------------------------------------------------------
   * 纯原生 JS，不依赖 Vue，可在任何页面复用；
   * 后端不可用/未登录时给出明确提示，不会静默失败；
   * 通过 /api/ai/ask 提问（需登录），回答由大模型生成，
     失败自动降级为规则文案（后端已保证）。
   ============================================================ */
(function () {
  'use strict';

  if (window.__aiAssistantLoaded) return;
  window.__aiAssistantLoaded = true;

  var QUICK = [
    '现在有空的座位吗？',
    '哪个楼层的座位最多？',
    '有哪些传感设备掉线了？',
    '帮我在一楼找个空座'
  ];

  var state = { open: false, busy: false, history: [] };

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var root, panel, listEl, inputEl;

  function build() {
    root = el('div', 'aias-root');

    var fab = el('button', 'aias-fab');
    fab.type = 'button';
    fab.title = 'AI 助手';
    fab.innerHTML = '<i class="fas fa-comment-dots"></i>';
    fab.addEventListener('click', toggle);

    panel = el('div', 'aias-panel');
    panel.innerHTML =
      '<div class="aias-head">' +
      '  <span class="aias-head-t"><i class="fas fa-robot"></i> AI 助手</span>' +
      '  <button type="button" class="aias-close" title="收起">&times;</button>' +
      '</div>' +
      '<div class="aias-list"></div>' +
      '<div class="aias-quick"></div>' +
      '<div class="aias-input">' +
      '  <input type="text" placeholder="问点什么，例如：有靠窗的空位吗？">' +
      '  <button type="button" class="aias-send"><i class="fas fa-paper-plane"></i></button>' +
      '</div>';

    listEl = panel.querySelector('.aias-list');
    inputEl = panel.querySelector('.aias-input input');

    panel.querySelector('.aias-close').addEventListener('click', toggle);
    panel.querySelector('.aias-send').addEventListener('click', send);
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') send();
    });

    var quickBox = panel.querySelector('.aias-quick');
    QUICK.forEach(function (q) {
      var b = el('button', 'aias-chip', esc(q));
      b.type = 'button';
      b.addEventListener('click', function () {
        inputEl.value = q;
        send();
      });
      quickBox.appendChild(b);
    });

    root.appendChild(panel);
    root.appendChild(fab);
    document.body.appendChild(root);

    push('ai', '你好，我可以帮你找座位。试试问我「现在有空的座位吗？」');
  }

  function toggle() {
    state.open = !state.open;
    root.classList.toggle('aias-open', state.open);
    if (state.open) setTimeout(function () { inputEl.focus(); }, 120);
  }

  function close() {
    if (!state.open) return;
    state.open = false;
    root.classList.remove('aias-open');
  }

  /* 点面板以外的地方自动收起。
     以前只能点右上角的 ×，面板铺在屏幕下半部分挡着内容，
     用户想关还得精确点那个小叉。 */
  document.addEventListener('pointerdown', function (e) {
    if (!state.open) return;
    if (root.contains(e.target)) return;
    close();
  }, true);

  /* 「显示 AI 助手悬浮球」开关：关掉后整个悬浮球隐藏。
     与 AI 功能本身分开 —— 接口照常可用，只是不占屏幕。 */
  function applyVisible() {
    var v = true;
    if (window.NativeSettings && window.NativeSettings.get) {
      window.NativeSettings.get('show_ai').then(function (on) {
        v = on !== false;
        root.style.display = v ? '' : 'none';
        if (!v) close();
      }).catch(function () { });
    }
  }
  window.addEventListener('nativesettings:change', function (e) {
    if (e.detail && e.detail.key === 'show_ai') {
      var on = e.detail.value !== false;
      root.style.display = on ? '' : 'none';
      if (!on) close();
    }
  });

  function push(role, text) {
    state.history.push({ role: role, text: text });
    var item = el('div', 'aias-msg aias-' + role);
    item.innerHTML = '<div class="aias-bubble">' + esc(text) + '</div>';
    listEl.appendChild(item);
    listEl.scrollTop = listEl.scrollHeight;
    return item;
  }

  /* 让 AI 提议的写操作带一个确认按钮。

     后端不会执行写操作，只把「准备做什么」随回答一起返回；
     这里把它渲染成一张卡片，用户点了才调 /api/ai/agent/confirm。
     模型理解错了也只是弹出来一个错误的提议，不会真的改数据。 */
  function renderActions(host, actions) {
    if (!actions || !actions.length) return;
    actions.forEach(function (a) {
      var card = document.createElement('div');
      card.className = 'aias-action';

      var desc = document.createElement('div');
      desc.className = 'aias-action-desc';
      desc.textContent = '⚙️ 准备执行：' + (a.desc || a.tool);
      card.appendChild(desc);

      var row = document.createElement('div');
      row.className = 'aias-action-row';

      var ok = document.createElement('button');
      ok.className = 'aias-action-ok';
      ok.textContent = '确认执行';
      var no = document.createElement('button');
      no.className = 'aias-action-no';
      no.textContent = '取消';

      var done = false;
      var finish = function (msg, cls) {
        if (done) return;
        done = true;
        desc.textContent = msg;
        row.remove();
        if (cls) card.classList.add(cls);
      };

      ok.onclick = function () {
        ok.disabled = true; no.disabled = true;
        ok.textContent = '执行中…';
        fetch('/api/ai/agent/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tool: a.tool, args: a.args })
        }).then(function (r) {
          return r.json().then(function (b) { return { status: r.status, body: b }; });
        }).then(function (res) {
          var msg = (res.body && (res.body.message || (res.body.data && res.body.data.message)))
            || (res.body && res.body.data && res.body.data.error);
          if (res.status === 200) {
            finish('✅ ' + (msg || '已执行'), 'aias-action-done');
          } else {
            finish('✗ ' + (msg || '执行失败'), 'aias-action-fail');
          }
        }).catch(function () {
          finish('✗ 网络异常，未执行', 'aias-action-fail');
        });
      };
      no.onclick = function () { finish('已取消，未做任何修改', 'aias-action-cancel'); };

      row.appendChild(ok);
      row.appendChild(no);
      card.appendChild(row);
      host.appendChild(card);
    });
  }

  function send() {
    var q = (inputEl.value || '').trim();
    if (!q || state.busy) return;
    inputEl.value = '';
    push('me', q);

    state.busy = true;
    var pending = push('ai', '正在思考…');
    pending.classList.add('aias-pending');

    // 走智能体接口：它能调工具查真实数据，也能提议修改（但不会直接执行）
    fetch('/api/ai/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q })
    })
      .then(function (r) {
        return r.json().then(function (body) { return { status: r.status, body: body }; });
      })
      .then(function (res) {
        pending.classList.remove('aias-pending');
        var d = (res.body && res.body.data) || {};
        var text;
        if (res.status === 401) {
          text = '请先登录后再使用 AI 助手。';
        } else if (d.text) {
          text = d.text;
          if (!d.ai_generated) {
            text += '\n（当前为大模型降级模式，内容由规则生成）';
          }
          if (d.used_tools && d.used_tools.length) {
            text += '\n· 已查询：' + d.used_tools.join('、');
          }
        } else {
          text = (res.body && res.body.message) || '暂时无法回答，请稍后再试。';
        }
        pending.querySelector('.aias-bubble').textContent = text;
        renderActions(pending, d.actions);
        listEl.scrollTop = listEl.scrollHeight;
      })
      .catch(function () {
        pending.classList.remove('aias-pending');
        pending.querySelector('.aias-bubble').textContent = '网络异常，暂时无法连接 AI 助手。';
      })
      .then(function () { state.busy = false; });
  }

  function injectStyle() {
    var css = [
      '.aias-root{position:fixed;right:22px;bottom:22px;z-index:9000;font-family:inherit}',
      '.aias-fab{width:54px;height:54px;border-radius:50%;border:none;cursor:pointer;',
      'background:linear-gradient(135deg,#4f8cff,#7c5cff);color:#fff;font-size:21px;',
      'box-shadow:0 6px 20px rgba(79,140,255,.4);transition:transform .18s}',
      '.aias-fab:hover{transform:scale(1.06)}',
      '.aias-panel{position:absolute;right:0;bottom:68px;width:352px;max-width:calc(100vw - 40px);',
      'height:472px;max-height:calc(100vh - 120px);background:#fff;border-radius:14px;',
      'box-shadow:0 12px 40px rgba(0,0,0,.18);display:none;flex-direction:column;overflow:hidden}',
      '.aias-open .aias-panel{display:flex}',
      '.aias-head{display:flex;align-items:center;justify-content:space-between;padding:13px 16px;',
      'background:linear-gradient(135deg,#4f8cff,#7c5cff);color:#fff;font-weight:600;font-size:15px}',
      '.aias-close{background:none;border:none;color:#fff;font-size:22px;line-height:1;cursor:pointer;opacity:.85}',
      '.aias-close:hover{opacity:1}',
      '.aias-list{flex:1;overflow-y:auto;padding:14px;background:#f7f9fc}',
      '.aias-msg{display:flex;margin-bottom:10px}',
      '.aias-me{justify-content:flex-end}',
      '.aias-bubble{max-width:82%;padding:9px 13px;border-radius:11px;font-size:14px;',
      'line-height:1.65;white-space:pre-wrap;word-break:break-word}',
      '.aias-ai .aias-bubble{background:#fff;color:#1f2d4d;border:1px solid #e3e9f2;border-bottom-left-radius:3px}',
      '.aias-me .aias-bubble{background:#4f8cff;color:#fff;border-bottom-right-radius:3px}',
      '.aias-pending .aias-bubble{color:#8b98a8;font-style:italic}',
      // AI 提议的写操作：必须由用户点确认，模型不能自己执行
      '.aias-action{max-width:82%;margin:6px 0 2px;background:#fff8e6;border:1px solid #ffe0a3;',
      'border-radius:10px;padding:9px 11px;font-size:13px}',
      '.aias-action-desc{color:#8a5a00;line-height:1.6;word-break:break-word}',
      '.aias-action-row{display:flex;gap:8px;margin-top:8px}',
      '.aias-action-ok,.aias-action-no{border:none;border-radius:7px;padding:6px 14px;',
      'font-size:13px;font-family:inherit;cursor:pointer}',
      '.aias-action-ok{background:#f9ab00;color:#fff}',
      '.aias-action-ok:hover{background:#e09b00}',
      '.aias-action-ok:disabled{opacity:.6;cursor:default}',
      '.aias-action-no{background:#eef2f7;color:#5a6b80}',
      '.aias-action-no:hover{background:#e2705f;color:#fff}',
      '.aias-action-no:disabled{opacity:.6;cursor:default}',
      '.aias-action-done{background:#e8f6ec;border-color:#b7e0c4}',
      '.aias-action-done .aias-action-desc{color:#1e7e34}',
      '.aias-action-fail{background:#fdecea;border-color:#f5c6c0}',
      '.aias-action-fail .aias-action-desc{color:#c5221f}',
      '.aias-action-cancel{background:#f2f4f7;border-color:#dfe4ea}',
      '.aias-action-cancel .aias-action-desc{color:#6b7785}',
      '.aias-quick{display:flex;gap:6px;flex-wrap:wrap;padding:0 14px 8px;background:#f7f9fc}',
      '.aias-chip{font-size:12px;padding:5px 10px;border-radius:999px;border:1px solid #d7e0ec;',
      'background:#fff;color:#4a5a70;cursor:pointer;font-family:inherit}',
      '.aias-chip:hover{border-color:#4f8cff;color:#4f8cff}',
      '.aias-input{display:flex;gap:8px;padding:11px 14px;border-top:1px solid #e8edf5;background:#fff}',
      '.aias-input input{flex:1;border:1px solid #d7e0ec;border-radius:8px;padding:9px 12px;',
      'font-size:14px;font-family:inherit;outline:none}',
      '.aias-input input:focus{border-color:#4f8cff}',
      '.aias-send{border:none;background:#4f8cff;color:#fff;width:40px;border-radius:8px;cursor:pointer}',
      '.aias-send:hover{background:#3d7ae8}',
      '@media(max-width:480px){.aias-panel{width:calc(100vw - 32px)}}'
    ].join('');
    var s = document.createElement('style');
    s.textContent = css;
    document.head.appendChild(s);
  }

  function init() {
    injectStyle();
    build();
    applyVisible();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

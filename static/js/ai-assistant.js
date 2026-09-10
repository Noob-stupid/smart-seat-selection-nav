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
    '有没有安静的座位？',
    '哪个楼层最空？'
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

  function push(role, text) {
    state.history.push({ role: role, text: text });
    var item = el('div', 'aias-msg aias-' + role);
    item.innerHTML = '<div class="aias-bubble">' + esc(text) + '</div>';
    listEl.appendChild(item);
    listEl.scrollTop = listEl.scrollHeight;
    return item;
  }

  function send() {
    var q = (inputEl.value || '').trim();
    if (!q || state.busy) return;
    inputEl.value = '';
    push('me', q);

    state.busy = true;
    var pending = push('ai', '正在思考…');
    pending.classList.add('aias-pending');

    fetch('/api/ai/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q })
    })
      .then(function (r) {
        return r.json().then(function (body) { return { status: r.status, body: body }; });
      })
      .then(function (res) {
        pending.classList.remove('aias-pending');
        var text;
        if (res.status === 401) {
          text = '请先登录后再使用 AI 助手。';
        } else if (res.body && res.body.data && res.body.data.text) {
          text = res.body.data.text;
          if (!res.body.data.ai_generated) {
            text += '\n（当前为大模型降级模式，内容由规则生成）';
          }
        } else {
          text = (res.body && res.body.message) || '暂时无法回答，请稍后再试。';
        }
        pending.querySelector('.aias-bubble').textContent = text;
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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

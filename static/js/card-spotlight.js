/* ============================================================
   全局卡片鼠标聚光（配合 css/pages/card-spotlight.css）
   仅跟踪鼠标位置设置 --mx/--my，无 3D 倾斜；
   作用于页面内所有 .card 与 .login-card 元素
   ============================================================ */
(function () {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  function closestCard(target) {
    if (!target || !target.closest) return null;
    return target.closest('.card, .login-card');
  }

  document.addEventListener('mousemove', function (e) {
    var card = closestCard(e.target);
    if (!card) return;
    var rect = card.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var x = e.clientX - rect.left;
    var y = e.clientY - rect.top;
    card.style.setProperty('--mx', ((x / rect.width) * 100).toFixed(2) + '%');
    card.style.setProperty('--my', ((y / rect.height) * 100).toFixed(2) + '%');
  });
})();

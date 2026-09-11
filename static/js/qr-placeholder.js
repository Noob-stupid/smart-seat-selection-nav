/* 演示用二维码占位图生成器
   ------------------------------------------------------------------
   纯静态环境没有后端 /api/seats/<id>/qrcode 这类图片接口，本文件在浏览器内
   用确定性算法生成「看起来像二维码」的 SVG 图形（含定位角、定时图案、
   数据区），同一段文本永远生成同一张图，便于演示与打印排版。

   注意：这是示意图形，不是符合 ISO/IEC 18004 的真二维码，无法被扫码枪识别。
   接入真实后端后，把 img 的 src 换回后端二维码接口即可。

   用法：
     window.demoQRCode('SEAT:12:A-01')            → data URI（可直接给 <img src>）
     window.demoQRCode('SEAT:12:A-01', 220)       → 指定像素尺寸
*/
(function () {
  'use strict';

  var MODULES = 25;   // 模块数（25×25，接近二维码版本 2 的观感）
  var QUIET = 3;      // 静默区（模块）

  function hashString(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function mulberry32(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* 生成模块矩阵：true = 深色 */
  function buildMatrix(text) {
    var n = MODULES;
    var grid = [];
    var fixed = [];   // true = 已被功能图形占用
    var i, j;
    for (i = 0; i < n; i++) {
      grid.push(new Array(n).fill(false));
      fixed.push(new Array(n).fill(false));
    }

    function setModule(r, c, dark) {
      if (r < 0 || c < 0 || r >= n || c >= n) return;
      grid[r][c] = !!dark;
      fixed[r][c] = true;
    }

    /* 定位角（7×7）+ 分隔带（1 模块白边） */
    function finder(r0, c0) {
      for (var r = -1; r <= 7; r++) {
        for (var c = -1; c <= 7; c++) {
          var rr = r0 + r, cc = c0 + c;
          if (rr < 0 || cc < 0 || rr >= n || cc >= n) continue;
          var ring = (r === 0 || r === 6 || c === 0 || c === 6);
          var core = (r >= 2 && r <= 4 && c >= 2 && c <= 4);
          var edge = (r === -1 || r === 7 || c === -1 || c === 7);
          setModule(rr, cc, edge ? false : (ring || core));
        }
      }
    }
    finder(0, 0);
    finder(0, n - 7);
    finder(n - 7, 0);

    /* 定时图案：第 6 行 / 第 6 列交替黑白 */
    for (i = 8; i < n - 8; i++) {
      setModule(6, i, i % 2 === 0);
      setModule(i, 6, i % 2 === 0);
    }

    /* 校正图案（5×5） */
    var a0 = n - 9;
    for (var r2 = -1; r2 <= 5; r2++) {
      for (var c2 = -1; c2 <= 5; c2++) {
        var rr2 = a0 + r2, cc2 = a0 + c2;
        if (rr2 < 0 || cc2 < 0 || rr2 >= n || cc2 >= n) continue;
        var outer = (r2 === 0 || r2 === 4 || c2 === 0 || c2 === 4);
        var inner = (r2 === 2 && c2 === 2);
        setModule(rr2, cc2, outer || inner);
      }
    }

    /* 数据区：由文本哈希驱动的伪随机填充（确定性） */
    var rnd = mulberry32(hashString(String(text)));
    for (i = 0; i < n; i++) {
      for (j = 0; j < n; j++) {
        if (fixed[i][j]) continue;
        grid[i][j] = rnd() > 0.48;
      }
    }
    return grid;
  }

  function toSvg(text, size) {
    var grid = buildMatrix(text);
    var n = MODULES;
    var total = n + QUIET * 2;
    var unit = size / total;
    var parts = [];
    // 用单条 path 绘制深色模块，体积更小
    for (var r = 0; r < n; r++) {
      for (var c = 0; c < n; c++) {
        if (!grid[r][c]) continue;
        var x = ((c + QUIET) * unit).toFixed(2);
        var y = ((r + QUIET) * unit).toFixed(2);
        parts.push('M' + x + ' ' + y + 'h' + unit.toFixed(2) + 'v' + unit.toFixed(2) + 'h-' + unit.toFixed(2) + 'z');
      }
    }
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '">' +
      '<rect width="' + size + '" height="' + size + '" fill="#ffffff"/>' +
      '<path d="' + parts.join('') + '" fill="#20252a"/>' +
      '</svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  window.demoQRCode = function (text, size) {
    return toSvg(text === undefined || text === null ? '' : String(text), Number(size) > 0 ? Number(size) : 160);
  };
})();

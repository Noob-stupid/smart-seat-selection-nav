// 行为验证：PDR 位置推算在「转弯」时的表现。
// 从 native-features.js 里把 recomputeFromSteps 抠出来实跑，
// 对比「逐步累加（修好后）」与「当前朝向 × 总距离（修之前）」两种模型。

const fs = require('fs');
const src = fs.readFileSync('static/js/native-features.js', 'utf8');

const start = src.indexOf('recomputeFromSteps() {');
if (start < 0) { console.error('找不到 recomputeFromSteps'); process.exit(1); }
const open = src.indexOf('{', start);
let depth = 0, close = -1;
for (let i = open; i < src.length; i++) {
  if (src[i] === '{') depth++;
  else if (src[i] === '}') { depth--; if (depth === 0) { close = i; break; } }
}
const body = src.slice(open + 1, close);
console.log('--- 抠出的函数体 ---');
console.log(body.trim());
console.log('--------------------\n');

const recompute = new Function('return function () {' + body + '};')();

const PPM = 20;
const STEP = 0.65;
const n = (v) => (typeof v === 'number' && isFinite(v) ? v.toFixed(1) : String(v));

function makePdr(track, heading) {
  return {
    anchorX: 100, anchorY: 100,
    track: track,
    heading: heading,
    pxPerM: PPM,
    posX: null, posY: null,
    recomputeFromSteps: recompute,
  };
}

const track = [];
for (let i = 0; i < 10; i++) track.push({ h: 0, m: STEP });

console.log('=== 朝北走 10 步（6.5 米），然后原地转身朝南 ===');
const a = makePdr(track, 0);
a.recomputeFromSteps();
const x0 = a.posX, y0 = a.posY;
console.log('  转身前 (0°)   : x=' + n(x0) + '  y=' + n(y0));

a.heading = 180;
a.recomputeFromSteps();
console.log('  转身后 (180°) : x=' + n(a.posX) + '  y=' + n(a.posY));
const moved = Math.hypot(a.posX - x0, a.posY - y0);
console.log('  位置变化: ' + n(moved) + ' px  ' +
  (moved < 0.01 ? '✓ 没动（正确）' : '✗ 跳了（旧模型的 bug）'));

for (let i = 0; i < 4; i++) a.track.push({ h: 180, m: STEP });
a.recomputeFromSteps();
const expY = 100 - 10 * STEP * PPM + 4 * STEP * PPM;
console.log('\n  再朝南走 4 步 : x=' + n(a.posX) + '  y=' + n(a.posY));
console.log('  期望 y        : ' + n(expY) + '  ' +
  (Math.abs(a.posY - expY) < 0.01 ? '✓ 对上' : '✗ 不对'));

console.log('\n=== 对照：修之前的模型（当前朝向 × 累计距离）===');
const distM = 10 * STEP;
const oldModel = (heading) => {
  const rad = heading * Math.PI / 180;
  const d = distM * PPM;
  return { x: 100 + d * Math.sin(rad), y: 100 - d * Math.cos(rad) };
};
const o1 = oldModel(0), o2 = oldModel(180);
console.log('  转身前: x=' + n(o1.x) + ' y=' + n(o1.y));
console.log('  转身后: x=' + n(o2.x) + ' y=' + n(o2.y));
console.log('  → 位置被整体翻到锚点另一侧，跳了 ' +
  n(Math.hypot(o2.x - o1.x, o2.y - o1.y)) + ' px' +
  '（这正是评审说的「转向时重投影全部位移」）');

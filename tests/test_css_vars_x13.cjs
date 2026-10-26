// 批次 D 地基（X13）：共享颜色变量两份同值——插件 styles.css 顶部（插件加载时全局生效）和 lb-page-lib.js 的 LB_SHARED_CSS
// （手机上插件不加载，页面自己注入 head 的 #lb-shared）。改一处必须改两处，这里逐个比。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path');
const { ROOT } = require('./_fakedom.cjs');

const NAMES = ['--lb-warn', '--lb-warn-bg', '--lb-warn-border', '--lb-danger', '--lb-danger-bg', '--lb-ok', '--lb-star'];
// 解析 --lb-* 定义：分「基础」（@supports 外）和「@supports 里」两组，值去掉多余空白
function lbVars(css) {
  const out = { base: {}, supports: {} };
  const supports = [];
  const rest = css.replace(/@supports\s*\(([^)]*\([^)]*\)[^)]*)\)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}/g, (_, cond, body) => { supports.push({ cond: cond.replace(/\s+/g, ' ').trim(), body }); return ''; });
  const grab = (text, into) => { for (const m of text.matchAll(/(--lb-[\w-]+)\s*:\s*([^;}]+)[;}]/g)) into[m[1]] = m[2].replace(/\s+/g, ' ').replace(/\s*,\s*/g, ',').trim(); };
  grab(rest, out.base);
  for (const s of supports) grab(s.body, out.supports);
  out.conds = supports.filter(s => /--lb-/.test(s.body)).map(s => s.cond);
  return out;
}

const styles = fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/styles.css'), 'utf8');
const lib = fs.readFileSync(path.join(ROOT, 'link_brain/assets/lb-page-lib.js'), 'utf8');
const shared = (lib.match(/const LB_SHARED_CSS = `([\s\S]*?)`;/) || [])[1];
assert.ok(shared, 'lb-page-lib.js 里有 LB_SHARED_CSS');
const a = lbVars(styles), b = lbVars(shared);
for (const n of NAMES) assert.ok(n in a.base, 'styles.css 定义了 ' + n);
assert.deepEqual(Object.keys(a.base).sort(), Object.keys(b.base).sort(), '两份定义的变量名一样');
for (const n of Object.keys(a.base)) assert.equal(a.base[n], b.base[n], n + ' 两份同值');
assert.deepEqual(a.supports, b.supports, '@supports 里的 color-mix 覆盖两份同值');
assert.deepEqual(a.conds, b.conds, '@supports 条件一样');
assert.ok(Object.keys(a.supports).length >= 3, 'warn-bg / warn-border / danger-bg 在支持 color-mix 时混色');
// 语义：提醒色跟主题（先 --text-warning，退回 --color-orange），危险色跟 --text-error；不用 --lb-warn-line 这个名字
assert.equal(a.base['--lb-warn'], 'var(--text-warning,var(--color-orange))');
assert.equal(a.base['--lb-danger'], 'var(--text-error)');
assert.ok(!/--lb-warn-line/.test(styles + shared), '统一叫 --lb-warn-border');
// 两份都挂在 body 上（主题的变量也在 body 的类上，跟着主题走）
assert.ok(/(^|\n)body\{--lb-warn:/.test(styles) && /(^|\n)body\{--lb-warn:/.test(shared), '定义在 body 上');
console.log(`PASS css vars X13: ${Object.keys(a.base).length} shared --lb-* vars + ${Object.keys(a.supports).length} color-mix overrides identical in styles.css and LB_SHARED_CSS`);

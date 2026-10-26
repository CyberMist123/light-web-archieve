// 1027 样式集：LB.applyTheme（页面）和 plugin.applyTheme / lb-theme.js（插件）同一套换算；lb-shared 带上全部样式集变量和共用类。
// 逐字副本那一层在 tests/test_tokens_1027.py；这里管行为。
'use strict';
const assert = require('node:assert/strict');
const path = require('path');
const { ROOT, asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const LIB = asset('lb-page-lib.js');
const DATA = '_archive/catalog-data.json';
const plug = require(path.join(ROOT, 'obsidian-plugins/link-brain-actions/lb-theme.js'));

const CASES = [
  undefined, null, {}, 'x',
  { titleFont: 'LXGW WenKai', bodyFont: 'Inter, sans-serif', numberFont: '', scale: 1.15, gap: 30 },
  { titleFont: '"Evil"; } body{color:red', scale: '9', gap: 's' },
  { scale: 0.1, gap: -5, numberFont: 'Georgia' },
  { scale: 'abc', gap: '18px', bodyFont: '  ' },
  { gap: 'l', scale: '1.2' },
];

function pureMapping() {
  const v = plug.lbThemeVars({ titleFont: 'LXGW WenKai', bodyFont: 'Inter, sans-serif', scale: 1.15, gap: 30 });
  assert.equal(v['--lb-font-title'], '"LXGW WenKai",var(--lb-font-title-base)', '她的字体在前，默认栈兜底');
  assert.equal(v['--lb-font-body'], '"Inter",sans-serif,var(--lb-font-body-base)', '通用族名不加引号');
  assert.equal(v['--lb-font-num'], null, '没给 = 用默认');
  assert.equal(v['--lb-scale'], '1.15');
  assert.equal(v['--lb-gap'], '30px');
  const bad = plug.lbThemeVars({ titleFont: '"Evil"; } body{color:red', scale: '9', gap: 's' });
  assert.ok(!/[;{}]/.test(bad['--lb-font-title']), '字体名里的 ; { } 去掉，写不出别的规则：' + bad['--lb-font-title']);
  assert.equal(bad['--lb-scale'], '2', '倍数封顶 2');
  assert.equal(bad['--lb-gap'], '17px', "'s' = 24 × 0.7");
  const lo = plug.lbThemeVars({ scale: 0.1, gap: -5 });
  assert.equal(lo['--lb-scale'], '0.5'); assert.equal(lo['--lb-gap'], '0px');
  const none = plug.lbThemeVars(undefined);
  assert.deepEqual(Object.values(none), [null, null, null, null, null], '没有主题 = 五个都回默认');
  assert.deepEqual(Object.keys(none), ['--lb-font-title', '--lb-font-body', '--lb-font-num', '--lb-scale', '--lb-gap']);
  console.log('PASS lb-theme mapping: user fonts first + default stack fallback, generic families unquoted, injection chars stripped, scale 0.5–2, gap px / s|m|l, empty = defaults');
}

async function pageAndPluginAgree() {
  const dom = makeDom();
  const plugin = { settings: { catalogLayout: { theme: { titleFont: 'Playfair Display', scale: 1.1, gap: 'l' } } } };
  const { app } = makeApp({ files: { [DATA]: JSON.stringify({ built_at: 'x', items: [] }) }, plugin });
  const A = dataviewBlock({ dom, app, code: LIB + `
const LB = lbPageLib(dv, app, 'catalog');
globalThis.__LB = LB;
globalThis.__host = LB.mountHost('t-host');
globalThis.__pageVars = typeof lbThemeVars === 'function' ? CASES.map(c => lbThemeVars(c)) : null;
`.replace('CASES', JSON.stringify(CASES.map(c => (c === undefined ? null : c)))) });
  await A.run();
  const LB = globalThis.__LB, host = globalThis.__host;
  // 页面和插件两份换算对同一组输入给出同样结果（两份代码逐字相同由 py 测试锁，这里防「同文本不同环境」）
  assert.deepEqual(globalThis.__pageVars, CASES.map(c => plug.lbThemeVars(c === undefined ? null : c)));
  // 不传参：读插件设置 catalogLayout.theme，写到本页 host 上，host 加 lb-scope
  const vars = LB.applyTheme();
  assert.equal(host.style.getPropertyValue('--lb-font-title'), '"Playfair Display",var(--lb-font-title-base)');
  assert.equal(host.style.getPropertyValue('--lb-scale'), '1.1');
  assert.equal(host.style.getPropertyValue('--lb-gap'), '32px');
  assert.ok(host.classList.contains('lb-scope'), 'host 带 lb-scope（字号在这一层按新倍数重算）');
  assert.equal(vars['--lb-scale'], '1.1', '返回写上去的变量');
  // 改回默认：传 null → 五个行内变量都摘掉
  LB.applyTheme(null);
  assert.equal(host.style.getPropertyValue('--lb-scale') || '', '');
  assert.equal(host.style.getPropertyValue('--lb-font-title') || '', '');
  // 指定元素
  const box = host.createEl('div');
  LB.applyTheme({ bodyFont: 'Inter' }, box);
  assert.equal(box.style.getPropertyValue('--lb-font-body'), '"Inter",var(--lb-font-body-base)');
  assert.ok(box.classList.contains('lb-scope'));
  // 插件侧：body 上不加 lb-scope（body 本来就在样式集选择器里）
  const body = dom.document.body;
  plug.lbApplyTheme(body, { scale: 1.2 });
  assert.equal(body.style.getPropertyValue('--lb-scale'), '1.2');
  assert.ok(!body.classList.contains('lb-scope'));
  plug.lbApplyTheme(body, null);
  // lb-shared 带全套样式集
  const shared = dom.document.getElementById('lb-shared').textContent;
  for (const v of ['--lb-font-title:', '--lb-font-body:', '--lb-fs-body:', '--lb-ink:', '--lb-space-6:', '--lb-ctl-h:', '.lb-btn{', '.lb-btn-pill{', '.lb-input{', '.lb-label{', '.lb-num', '.lb-kicker{', 'body,.lb-page-host,.lb-scope{'])
    assert.ok(shared.includes(v), 'lb-shared 有 ' + v);
  console.log('PASS LB.applyTheme: page and plugin mapping identical on 9 inputs; no-arg reads plugin catalogLayout.theme onto the page host (+ .lb-scope), null clears, explicit element works; lb-shared carries the whole token set + shared classes');
}

async function pluginMethod() {
  // main.js 的 applyTheme：默认读 settings.catalogLayout.theme、写到 document.body
  const src = require('fs').readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/main.js'), 'utf8');
  assert.match(src, /applyTheme\(theme = this\.settings\?\.catalogLayout\?\.theme, el\b/, 'plugin.applyTheme(theme?, el?) 默认取设置里的主题');
  assert.match(src, /lbTheme\(\)\s*\{[^\n]*lb-theme\.js/, 'plugin.lbTheme() 载入 lb-theme.js');
  console.log('PASS plugin.applyTheme / plugin.lbTheme exist with the agreed signature');
}

(async () => {
  pureMapping();
  await pageAndPluginAgree();
  await pluginMethod();
})().catch(e => { console.error(e); process.exit(1); });

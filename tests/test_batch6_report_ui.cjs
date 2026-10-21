// 第 6 批：目录页标题区小改。真跑页面脚本，假 DOM / 假 vault，不起真进程（CONVENTIONS §7.5）。断言：
//   目录页：标题下的同步概况行（.lbc-syncinfo）没了；「N 篇 · 更新 …」那行可点（10-03 起悬停提示「看同步记录」，点了调插件 openSyncLog()）
//   「本周同步情况」窗口 10-03 换成「同步记录」，用例在 test_batch9_synclog_ui.cjs。
'use strict';
const assert = require('node:assert/strict');
const { ROOT, asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const LIB = asset('lb-page-lib.js');
const SEARCH = asset('catalog-search.js');
const DATA = '_archive/catalog-data.json';
const SUMMARY = '_archive/problems-summary.json';

function catalogData() {
  const mk = (id, title) => ({ id, title, tags: [], cats: [], topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: '', attachment: 'none', starred: false, problems: [] });
  return { built_at: '2026-10-03T10:00:00+10:00', pinyin_chars: {}, aliases: [], cats_order: [], cats: [], topics: [], state_registry: {},
    items: [mk('a', '悉尼咖啡地图'), mk('b', '电饭煲鸡肉饭')] };
}

async function catalogTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const V = makeVault({
    [DATA]: JSON.stringify(catalogData()),
    [SUMMARY]: JSON.stringify({ updated_at: '2026-10-03T04:05:00+10:00', needs_human: 0, auto: 0, gave_up: 0, skipped: 0,
      sync: { state: 'ready', last_success: '2026-10-03T04:00:00+10:00', new: 12, deferred: 85 } }),
  });
  let opened = 0;
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {}, openProblems() {}, openSyncLog() { opened++; } };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const A = dataviewBlock({ dom, app, code: LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js') });
  await A.run();
  const q = s => A.section.querySelector(s);
  assert.equal(q('.lbc-syncinfo'), null, '「上次同步 · 本次新收 · 还剩」那行删了');
  assert.ok(!/上次同步/.test(q('.lbc-top').textContent), '标题区不再出现「上次同步」');   // 1021 第 3 段：「上次同步」只在左侧边栏 SYNC 里（设计稿）
  // 批次 D · F4：标题下那行拆成三块——计数只是字；「更新 …」是按钮（悬停说目录数据生成时刻），点了开同步记录
  assert.equal(q('.lbc-count').textContent, '2 篇');
  assert.equal(q('.lbc-count').onclick, undefined); assert.equal(q('.lbc-count').getAttribute('role'), null);
  const sub = q('.lbc-updated');
  assert.ok(sub, '「更新 …」那块可点');
  assert.match(sub.textContent, /^更新 \d\d\/\d\d \d\d:\d\d$/);
  assert.match(sub.title, /^目录数据生成于 \d{4}-\d\d-\d\d \d\d:\d\d（同步或刷新目录后更新）· 点开看同步记录$/);
  assert.equal(sub.tagName, 'BUTTON', '键盘可达（回车 / 空格按原生按钮行为），样式是灰字');
  assert.ok(sub.classList.contains('lbc-sub-link'));
  await sub.onclick();
  assert.equal(opened, 1, '点了 = 插件 openSyncLog()');
  // 插件里还没有 openSyncLog（刚部署、旧实例在内存）：LB.ensure 重载一次插件再调
  {
    delete globalThis.__lbState;
    const old = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {} };
    let reloaded = 0, got = 0;
    const app2 = { vault: makeVault({ [DATA]: JSON.stringify(catalogData()) }).vault, workspace: makeWorkspace(), metadataCache: { getCache: () => null },
      plugins: { plugins: { 'link-brain-actions': old }, disablePlugin: async () => {},
        enablePlugin: async () => { reloaded++; app2.plugins.plugins['link-brain-actions'] = { ...old, openSyncLog() { got++; } }; } } };
    const B = dataviewBlock({ dom, app: app2, code: LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js') });
    await B.run();
    await B.section.querySelector('.lbc-updated').onclick();
    assert.equal(reloaded, 1); assert.equal(got, 1, '重载后调到新方法');
  }
  console.log('PASS catalog title: sync overview line removed; 「更新 …」is its own button (title = data built time) → LB.ensure(openSyncLog)');
}

(async () => {
  await catalogTests();
})().catch(e => { console.error(e); process.exitCode = 1; });

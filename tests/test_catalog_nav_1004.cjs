// 10-04 目录页（车 C）：⑧ 滚下去之后右下角出一个小的回顶按钮；⑨ Ctrl+F 在目录页（当前视图是它或鼠标在页上）= 聚焦目录搜索框、拦掉 Obsidian 的查找，别的页不拦
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';

(async () => {
  const items = Array.from({ length: 6 }, (_, i) => ({ id: 'n' + i, title: '笔记' + i, tags: [], cats: ['城市'], topics: [], summary: '', search_fields: { body: '正文' + i },
    note: `Web/n${i}.md`, notes_path: `_archive/xiaohongshu/n${i}/notes.json`, cover: '', attachment: 'none', starred: false, ts: '2026-10-01T00:00:00Z', date: '2026-10-01' }));
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: '2026-10-04T00:00:00Z', pinyin_chars: {}, aliases: [], cats_order: ['城市'], cats: [], topics: [], items }), '_archive/sync-status.json': '{}' });
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {} };
  const workspace = makeWorkspace();
  const app = { vault: V.vault, workspace, plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js') });
  await A.run(); await tick(5);
  const $ = s => A.container.querySelector(s);
  const wrap = $('.lbc-wrap'), scroller = A.host, search = $('.lbc-search');

  // ⑧ 回顶按钮：在 wrap 最后（sticky 贴视口底），没滚时藏着；滚过一屏出现；点了回到顶；滚回去又藏
  const dock = $('.lbc-totop-dock'), btn = $('.lbc-totop');
  assert.ok(dock && btn, '有回顶按钮');
  assert.equal(wrap.children.at(-1), dock, '在页面最后');
  assert.ok(!dock.classList.contains('is-on'));
  assert.ok(A.container.querySelector('style').textContent.includes('.lbc-totop-dock{position:sticky;bottom:22px'), '钉在视口底部');
  const scrollTo = async top => { scroller.scrollTop = top; for (const fn of scroller.listeners.scroll || []) fn({}); await tick(30); };
  await scrollTo(1500);
  assert.ok(dock.classList.contains('is-on'), '滚下去出现');
  btn.onclick();
  assert.equal(scroller.scrollTop, 0, '点了回到顶部');
  await scrollTo(0);
  assert.ok(!dock.classList.contains('is-on'), '回到顶上就藏起来');

  // ⑨ Ctrl+F
  const press = (o = {}) => { let prevented = false, stopped = false; const e = { key: 'f', code: 'KeyF', ctrlKey: true, metaKey: false, altKey: false, shiftKey: false, ...o,
    preventDefault() { prevented = true; }, stopPropagation() { stopped = true; }, stopImmediatePropagation() { stopped = true; } };
    for (const fn of [...(dom.document.listeners.keydown || [])]) fn(e); return { prevented, stopped }; };
  dom.document.activeElement = null;
  // 不在目录页（别的标签是当前视图、鼠标也不在页上）：不拦
  workspace.activeLeaf = { view: { containerEl: dom.document.body.createEl('div') } };
  let r = press();
  assert.equal(r.prevented, false); assert.notEqual(dom.document.activeElement, search);
  // 鼠标在页上：拦掉、聚焦搜索框
  for (const fn of wrap.listeners.mouseenter || []) fn({});
  r = press();
  assert.ok(r.prevented && r.stopped, '拦掉 Obsidian 自带的查找');
  assert.equal(dom.document.activeElement, search, '聚焦目录搜索框');
  // Ctrl+Shift+F（全库搜索）、单按 F 不拦
  dom.document.activeElement = null;
  assert.equal(press({ shiftKey: true }).prevented, false);
  assert.equal(press({ ctrlKey: false }).prevented, false);
  // 鼠标离开、但当前视图就是目录页：照样拦
  for (const fn of wrap.listeners.mouseleave || []) fn({});
  workspace.activeLeaf = { view: { containerEl: A.host } };
  r = press({ key: 'F' });
  assert.ok(r.prevented); assert.equal(dom.document.activeElement, search);
  // 监听器只有一份（重开页面不叠加）
  const before = (dom.document.listeners.keydown || []).length;
  delete globalThis.__lbState;
  const B = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js') });
  await B.run(); await tick(5);
  assert.equal((dom.document.listeners.keydown || []).length, before, '重开目录页：Ctrl+F 监听替换、不叠加');

  console.log('PASS catalog nav 1004: back-to-top dock appears after scrolling, scrolls to top, hides at top; Ctrl+F on the catalog (active view or hovered) focuses the search box and blocks Obsidian find, other pages / Ctrl+Shift+F untouched, listener not duplicated');
})().catch(e => { console.error(e); process.exit(1); });

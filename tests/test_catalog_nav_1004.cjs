// 10-04 目录页（车 C）：⑧ 滚下去之后右下角出一个小的回顶按钮；⑨ Ctrl+F 在目录页 = 聚焦目录搜索框、拦掉 Obsidian 的查找，别的页不拦
// 批次 D · CM1：快捷键只认「当前活动标签页里有这一页」（activeLeafHas），不再看鼠标停在哪；C10：Ctrl + 滚轮的非 passive 监听只在按住 Ctrl 且鼠标在页上时挂
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
  const $ = s => A.section.querySelector(s);
  const wrap = $('.lbc-wrap'), scroller = A.host, search = $('.lbc-search');

  // ⑧ 回顶按钮：在 wrap 最后（sticky 贴视口底），没滚时藏着；滚过一屏出现；点了回到顶；滚回去又藏
  const dock = $('.lbc-totop-dock'), btn = $('.lbc-totop');
  assert.ok(dock && btn, '有回顶按钮');
  assert.equal(wrap.children.at(-1), dock, '在页面最后');
  assert.ok(!dock.classList.contains('is-on'));
  assert.ok(dom.document.getElementById('lbc-style').textContent.includes('.lbc-totop-dock{position:sticky;bottom:22px'), '钉在视口底部');
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
  // CM1：鼠标在页上、但当前活动标签页是别的视图（她在左栏写笔记）：Ctrl+F / Ctrl+= 都不拦，回到 Obsidian 自带的查找 / 整窗缩放
  for (const fn of wrap.listeners.mouseenter || []) fn({});
  r = press();
  assert.equal(r.prevented, false, 'hover 不再算');
  assert.equal(press({ key: '=', code: 'Equal' }).prevented, false, 'Ctrl+= 也不拦');
  // 当前活动标签页就是目录页：拦掉、聚焦搜索框
  workspace.activeLeaf = { view: { containerEl: A.host } };
  r = press();
  assert.ok(r.prevented && r.stopped, '拦掉 Obsidian 自带的查找');
  assert.equal(dom.document.activeElement, search, '聚焦目录搜索框');
  // Ctrl+Shift+F（全库搜索）、单按 F 不拦
  dom.document.activeElement = null;
  assert.equal(press({ shiftKey: true }).prevented, false);
  assert.equal(press({ ctrlKey: false }).prevented, false);
  // 鼠标离开、但当前视图就是目录页：照样拦；Ctrl+= 改列数
  for (const fn of wrap.listeners.mouseleave || []) fn({});
  r = press({ key: 'F' });
  assert.ok(r.prevented); assert.equal(dom.document.activeElement, search);
  const grid = $('.lbc-grid');
  r = press({ key: '-', code: 'Minus' });
  assert.ok(r.prevented, 'Ctrl+- 拦下改列数');
  assert.equal(grid.style.getPropertyValue('--lbc-cols'), '2', '没调过：从实际排的列数（这里 1 列）往多一列，最少 2 列');
  press({ key: '-', code: 'Minus' });
  assert.equal(grid.style.getPropertyValue('--lbc-cols'), '3');
  assert.ok(A.notices.some(m => m === '瀑布流 3 列'), 'C7：列数提示走 Notice');

  // C10：没按 Ctrl 时 wrap 上没有滚轮监听（不挡 Obsidian 的滚动优化）；鼠标在页上 + 按下 Ctrl 才挂，松开就摘
  const keyev = (type, key) => { const e = { type, key, ctrlKey: key === 'Control', preventDefault() {}, stopPropagation() {} }; for (const fn of [...(dom.document.listeners[type] || [])]) fn(e); };
  assert.equal((wrap.listeners.wheel || []).length, 0, '平时没有 wheel 监听');
  keyev('keydown', 'Control');
  assert.equal((wrap.listeners.wheel || []).length, 0, '鼠标不在页上：按 Ctrl 也不挂');
  for (const fn of wrap.listeners.mouseenter || []) fn({});
  keyev('keydown', 'Control');
  assert.equal((wrap.listeners.wheel || []).length, 1, '鼠标在页上 + Ctrl：挂上');
  let wp = false;
  for (const fn of wrap.listeners.wheel) fn({ ctrlKey: true, deltaY: -100, preventDefault() { wp = true; } });
  assert.ok(wp, 'Ctrl + 滚轮拦下');
  assert.equal(grid.style.getPropertyValue('--lbc-cols'), '2', '往上滚 = 卡片变大、列变少');
  keyev('keyup', 'Control');
  assert.equal((wrap.listeners.wheel || []).length, 0, '松开 Ctrl：摘掉');
  for (const fn of wrap.listeners.mouseenter || []) fn({ ctrlKey: true });
  assert.equal((wrap.listeners.wheel || []).length, 1, '按着 Ctrl 移进页面：mouseenter 时也看 ctrlKey');
  for (const fn of wrap.listeners.mouseleave || []) fn({});
  assert.equal((wrap.listeners.wheel || []).length, 0, '移出页面：摘掉');
  // 监听器只有一份（重开页面不叠加）
  const before = (dom.document.listeners.keydown || []).length;
  delete globalThis.__lbState;
  const B = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js') });
  await B.run(); await tick(5);
  assert.equal((dom.document.listeners.keydown || []).length, before, '重开目录页：Ctrl+F 监听替换、不叠加');

  console.log('PASS catalog nav 1004: back-to-top dock appears after scrolling, scrolls to top, hides at top; Ctrl+F / Ctrl+± only when the catalog is in the active leaf (CM1), Ctrl+wheel listener only while Ctrl held over the page (C10), focuses the search box and blocks Obsidian find, other pages / Ctrl+Shift+F untouched, listener not duplicated');
})().catch(e => { console.error(e); process.exit(1); });

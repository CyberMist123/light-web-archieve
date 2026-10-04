// 10-04 ⑩ 笔记正文回目录页：作者行最左一个「← 目录」，点了在笔记自己那一格打开页头 lb-page: catalog 的那一页（不写死文件名）；
// 旧插件开着（图片导航不接管）也照样加；后渲染出来的笔记也补上；插件卸载时摘掉。两栏布局（.lb-cols / .lb-side / .lb-detail）不碰。
'use strict';
const assert = require('node:assert/strict');
const path = require('path');
const { ROOT, makeDom } = require('./_fakedom.cjs');

(async () => {
  const dom = makeDom();
  const observers = [];
  globalThis.document = dom.document;
  globalThis.MutationObserver = class { constructor(fn) { this.fn = fn; observers.push(this); } observe() {} disconnect() { this.off = true; } };
  globalThis.queueMicrotask = globalThis.queueMicrotask || (f => Promise.resolve().then(f));
  const note = () => {
    const pane = dom.document.body.createEl('div', { cls: 'markdown-preview-view xhs-note' });
    const lb = pane.createEl('div', { cls: 'lb-note' });
    const side = lb.createEl('div', { cls: 'lb-side' });
    const main = lb.createEl('div', { cls: 'lb-main' });
    const row = main.createEl('div', { cls: 'lb-author-row' });
    row.createEl('div', { cls: 'lb-author-dot' }); row.createEl('div', { cls: 'lb-author-copy', text: '作者' });
    return { pane, row, side };
  };
  const first = note();
  const opened = [];
  const leaf = { view: { containerEl: first.pane }, openFile(f) { opened.push(['leaf', f]); } };
  const cleanups = [];
  const plugin = {
    app: { plugins: { enabledPlugins: new Set(['link-brain-native-media-nav']) }, workspace: { iterateAllLeaves(fn) { fn({ view: { containerEl: dom.document.body.createEl('div') } }); fn(leaf); } } },
    register(fn) { cleanups.push(fn); }, registerDomEvent() {},
    async openLibraryPage(role, l) { opened.push([role, l]); },
  };
  const factory = require(path.join(ROOT, 'obsidian-plugins/link-brain-actions/media-nav.js'));
  const nav = factory({}, plugin);
  assert.equal(nav.attach(), false, '旧插件开着：图片导航不接管');
  const back = r => r.children.find(c => c.classList.contains('lb-back-catalog'));
  const btn = back(first.row);
  assert.ok(btn, '旧插件开着也加了「← 目录」');
  assert.equal(first.row.children[0], btn, '在作者行最左边');
  assert.equal(btn.textContent, '← 目录');
  assert.equal(first.side.children.length, 0, '左栏不动');
  // 点：在笔记自己那一格打开目录页（按 lb-page 找，交给 openLibraryPage）
  let stopped = 0; const ev = { preventDefault() {}, stopPropagation() { stopped++; } };
  for (const fn of btn.listeners.mousedown) fn(ev);
  for (const fn of btn.listeners.click) fn(ev);
  await Promise.resolve();
  assert.deepEqual(opened, [['catalog', leaf]]);
  assert.ok(stopped >= 2, '实时预览里点它不把光标放进 HTML 块');
  // 后来渲染出来的笔记：MutationObserver 触发后补上，且不重复加
  const second = note();
  observers[0].fn([{ addedNodes: [second.pane] }]);
  await new Promise(r => setTimeout(r, 0));
  assert.ok(back(second.row));
  observers[0].fn([{ addedNodes: [second.pane] }]); await new Promise(r => setTimeout(r, 0));
  assert.equal(first.row.children.filter(c => c.classList.contains('lb-back-catalog')).length, 1, '不重复加');
  // 卸载：摘掉
  for (const fn of cleanups) fn();
  assert.equal(back(first.row), undefined); assert.equal(back(second.row), undefined);

  // main.js：openLibraryPage(role, leaf) 给了窗格就在那一格打开
  const src = require('fs').readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/main.js'), 'utf8');
  assert.ok(/async openLibraryPage\(role, leaf = null\)/.test(src) && src.includes("if(leaf&&typeof leaf.openFile==='function'){await leaf.openFile(file);return;}"));
  const css = require('fs').readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/styles.css'), 'utf8');
  assert.ok(css.includes('.lb-note .lb-author-row > button.lb-back-catalog') && css.includes('color: var(--text-faint)'));

  console.log('PASS note back 1004: 「← 目录」 leftmost in the author row (even with the old media plugin on), opens the lb-page catalog in the note\'s own leaf, added to later notes once, removed on unload; two-column layout untouched');
})().catch(e => { console.error(e); process.exit(1); });

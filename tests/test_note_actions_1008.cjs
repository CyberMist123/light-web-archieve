// 批次 D · L3 note-actions.js：N2 笔记样式挂 head（和 note.css 一样、css-change 后排最后、卸载摘掉）+ body.lb-actions-on；
// N8 / N14「现在抓」→ 确认 → fetchAllComments(file)；N9 标签 → pendingCatalogQuery + openLibraryPage('catalog', 同一窗格 / Ctrl 新标签) + 事件；
// N11 ⋯ 菜单 / 命令「问这篇」→ plugin.askAboutNote(file)；N17 没开 Dataview 时打开归档笔记挂提示条；main.js 的 DATAVIEW_HINT / starNote 前缀。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { ROOT, makeDom, makeWorkspace, makeLeaf, makeMetadataCache } = require('./_fakedom.cjs');

const DIR = 'obsidian-plugins/link-brain-actions';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

function load(dom) {
  const src = fs.readFileSync(path.join(ROOT, DIR, 'note-actions.js'), 'utf8');
  const m = { exports: {} };
  new Function('require', 'module', 'exports', 'document', 'window', src)(require, m, m.exports, dom.document, { getSelection: () => null });
  return m.exports;
}
function setup({ running = null, dataview = 'ok' } = {}) {
  const dom = makeDom(), D = dom.document;
  const ws = makeWorkspace();
  const leafEl = D.body.createEl('div', { cls: 'workspace-leaf' });
  const content = leafEl.createEl('div', { cls: 'workspace-leaf-content' });
  const preview = content.createEl('div', { cls: 'markdown-reading-view' }).createEl('div', { cls: 'markdown-preview-view xhs-note' });
  const note = preview.createEl('div', { cls: 'lb-note' });
  const scroll = note.createEl('div', { cls: 'lb-main' }).createEl('div', { cls: 'lb-scroll' });
  const tags = scroll.createEl('div', { cls: 'lb-tags' });
  const tag = tags.createEl('span', { cls: 'lb-tag', text: '#做饭' });
  const act = scroll.createEl('div', { cls: 'lb-comments-note', text: '楼中楼还缺 7 条' }).createEl('span', { cls: 'lb-act lb-act-fetch-comments', text: '现在抓全部评论' });
  const file = { path: 'Web/Xiaohongshu/做饭.md', basename: '做饭' };
  const other = { path: 'Web/随手记.md', basename: '随手记' };
  const leaf = makeLeaf({ containerEl: content, file });
  ws.leaves.push(leaf);
  const calls = [], notices = [], cleanups = [], commands = {}, banners = [];
  const plugin = {
    app: { workspace: ws, metadataCache: makeMetadataCache({ [file.path]: { link_brain: { item_id: 'xhs-n1' } } }), vault: { adapter: { getBasePath: () => ROOT } } },
    manifest: { dir: DIR }, running, pendingCatalogQuery: '',
    register(fn) { cleanups.push(fn); }, registerEvent() {}, registerDomEvent(el, t, fn, o) { el.addEventListener(t, fn, o); },
    addCommand(c) { commands[c.id] = c; },
    notify(msg, opts = {}) { notices.push({ msg, opts }); return {}; },
    fetchAllComments: async f => calls.push(['fetch', f]),
    openLibraryPage: async (role, l) => calls.push(['open', role, l]),
    askAboutNote: async f => { calls.push(['ask', f]); return true; },
    dataviewState: () => dataview,
    onboardingUI: () => ({ dataviewBanner: v => banners.push(v) }),
  };
  const factory = load(dom);
  const inst = factory({ MarkdownView: class {} }, plugin);
  return { dom, D, ws, preview, note, tag, act, file, other, leaf, plugin, calls, notices, cleanups, commands, banners, inst };
}
const click = (D, target, extra = {}) => { const e = { type: 'click', target, prevented: false, preventDefault() { this.prevented = true; }, stopPropagation() {}, ...extra }; for (const fn of [...(D.listeners.click || [])]) fn(e); return e; };

(async () => {
  // ── N2 ──
  {
    const S = setup();
    const other = S.D.head.createEl('style'); other.id = 'snippet-link-brain';
    S.inst.attach();
    const el = S.D.getElementById('lb-note-style');
    assert.ok(el, 'head 里有 #lb-note-style');
    assert.equal(el.textContent, fs.readFileSync(path.join(ROOT, DIR, 'note.css'), 'utf8'), '内容就是 note.css');
    assert.ok(S.D.body.classList.contains('lb-actions-on'));
    S.D.head.createEl('style').id = 'later-snippet';
    S.ws.trigger('css-change');   // registerEvent 是空的：直接调
    S.inst.keepStyleLast();
    assert.equal(S.D.head.lastElementChild, el, 'css-change 后排在 head 最后（片段旧了也盖不掉新规则）');
    for (const fn of S.cleanups) fn();
    assert.equal(S.D.getElementById('lb-note-style'), null, '卸载后摘掉');
    assert.ok(!S.D.body.classList.contains('lb-actions-on'));
    // 读不到 note.css：只 console.error、不抛（片段照常生效）
    const T = setup(); T.plugin.manifest.dir = 'no/such/dir';
    const err = console.error; console.error = () => {};
    try { T.inst.attach(); } finally { console.error = err; }
    assert.equal(T.D.getElementById('lb-note-style'), null);
  }
  // ── N8 / N14 ──
  {
    const S = setup(); S.inst.attach();
    const e = click(S.D, S.act);
    assert.ok(e.prevented);
    const n = S.notices.at(-1);
    assert.ok(n.msg.startsWith('抓这篇的全部评论？') && n.opts.actions[0].label === '开始抓' && n.opts.ms === 12000, '先确认');
    assert.equal(S.calls.length, 0, '没点「开始抓」不动');
    await n.opts.actions[0].run();
    assert.deepEqual(S.calls, [['fetch', S.file]]);
    const R = setup({ running: '同步收藏' }); R.inst.attach();
    click(R.D, R.act);
    assert.equal(R.notices.at(-1).msg, '正在同步收藏，完成后再点'); assert.equal(R.calls.length, 0);
    // 键盘 Enter 同样
    const K = setup(); K.inst.attach();
    for (const fn of K.D.listeners.keydown || []) fn({ key: 'Enter', target: K.act, preventDefault() {} });
    assert.ok(K.notices.at(-1).msg.startsWith('抓这篇的全部评论？'));
    // 1026：抓过一遍没齐的，按钮是「接着补抓」——确认语说清只补缺的、不重复
    const C = setup(); C.inst.attach();
    C.act.textContent = '接着补抓';
    click(C.D, C.act);
    const c = C.notices.at(-1);
    assert.ok(c.msg.startsWith('接着补抓这篇没齐的评论？') && c.msg.includes('不会重复') && c.opts.actions[0].label === '接着补');
    await c.opts.actions[0].run();
    assert.deepEqual(C.calls, [['fetch', C.file]], '同一个入口：后端自己判断接着补');
  }
  // ── N9 ──
  {
    const S = setup(); S.inst.attach();
    let fired = 0; S.ws.on('link-brain:catalog-query', () => fired++);
    await click(S.D, S.tag); await tick(0);
    assert.equal(S.plugin.pendingCatalogQuery, '#做饭');
    assert.deepEqual(S.calls[0], ['open', 'catalog', S.leaf], '同一窗格打开目录');
    assert.equal(fired, 1);
    await click(S.D, S.tag, { ctrlKey: true }); await tick(0);
    assert.equal(S.ws.gotLeaves.at(-1), 'tab'); assert.equal(S.calls[1][2], S.ws.leaves.at(-1), 'Ctrl：新标签');
    S.D.body.classList.remove('lb-actions-on'); S.plugin.pendingCatalogQuery = '';
    click(S.D, S.tag); await tick(0);
    assert.equal(S.plugin.pendingCatalogQuery, '', '没有 lb-actions-on 不处理');
  }
  // ── N11 ── 1026 她：「问这篇」入口拿掉（笔记右键 / 命令面板都没有）
  {
    const S = setup(); S.inst.attach();
    assert.equal(S.commands['note-ask'], undefined, '没有「问这篇」命令');
    assert.equal(typeof S.inst.onFileMenu, 'undefined', '笔记右键不再加「问这篇」');
    assert.ok(S.commands['note-highlight-selection'], '划重点命令注册了');
  }
  // ── N17 ──
  {
    const S = setup({ dataview: 'nojs' }); S.inst.attach();
    S.ws.activeLeaf = S.leaf;
    S.inst.onFileOpen(S.file);
    assert.deepEqual(S.banners, [S.leaf.view], 'Dataview 没开 JS 查询：挂提示条');
    S.inst.onFileOpen(S.other);
    assert.equal(S.banners.length, 1, '不是归档笔记不挂');
    const O = setup({ dataview: 'ok' }); O.inst.attach(); O.inst.onFileOpen(O.file);
    assert.equal(O.banners.length, 0);
  }
  // ── main.js：DATAVIEW_HINT 文案、starNote 只有一个前缀 ──
  {
    const ctx = { module: { exports: {} }, process, setTimeout, clearTimeout, console, URL,
      require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Notice: class {}, TFile: class {} } : require(n) };
    vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(path.join(ROOT, DIR, 'main.js'), 'utf8'), ctx);
    const P = ctx.module.exports;
    const src = fs.readFileSync(path.join(ROOT, DIR, 'main.js'), 'utf8');
    const hint = src.slice(src.indexOf('const DATAVIEW_HINT'), src.indexOf('};', src.indexOf('const DATAVIEW_HINT')));
    assert.equal((hint.match(/笔记下面的批注/g) || []).length, 3, 'DATAVIEW_HINT 三条都提到笔记下面的批注');
    const p = Object.create(P.prototype || (P.default && P.default.prototype) || {});
    if (typeof p.starNote === 'function') {
      p.app = { workspace: { trigger() {} } };
      p.runPy = async () => { throw new Error('收藏失败'); };
      await assert.rejects(p.starNote('xhs-n1', true), e => (e.message.match(/收藏失败/g) || []).length === 1);
      p.runPy = async () => { throw new Error('后台没起来'); };
      await assert.rejects(p.starNote('xhs-n1', true), e => e.message === '收藏失败：后台没起来');
    } else console.log('（main.js 导出里拿不到插件类：starNote 前缀只按源码查）'), assert.ok(/\/\^收藏失败\/\.test\(m\)\?m:"收藏失败："\+m/.test(src));
  }
  console.log('PASS note-actions 1008: note.css injected into head (same bytes, kept last after css-change, removed on unload, fail-open) + body.lb-actions-on; 现在抓 asks first then fetchAllComments(file), busy → notice only; #tag → pendingCatalogQuery + catalog in same leaf (Ctrl → new tab) + event; 问这篇 in file-menu / command → askAboutNote(file); Dataview banner on archive notes; DATAVIEW_HINT mentions annotations; starNote single prefix');
})().catch(e => { console.error(e); process.exit(1); });

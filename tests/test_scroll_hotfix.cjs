// 1003 热修：目录页 / 问收藏页「有时滚轮滚不动」+「点来源，问收藏自动回首行」。假 DOM 复现 + 回归。
//   1. 图片导航（新 media-nav.js 与旧插件 link-brain-native-media-nav 同一段代码）：同一个标签页里看过「钉住媒体」的笔记，
//      再换到目录页 / 问收藏页（Obsidian 复用同一个 .markdown-preview-view），旧笔记挂在预览容器上的滚轮监听不能再吃掉滚轮；
//      每个预览容器只留一个滚轮监听（新旧两份插件同开也是一个）；钉住时笔记里的滚轮照旧转给 .lb-scroll、图片上照旧翻页。
//   2. 问收藏：点「查看」开右侧来源窗格（Obsidian 拆分时把本页 DOM 挪了个位置 → 对话区 scrollTop 被浏览器归零）、
//      Dataview 重跑挂回旧 DOM、layout-change 之后，对话区回到原处；在底部跟随的回到底部；用户自己滚到顶的不拉回。
//      页头 / 输入框上滚滚轮 = 滚对话区。
//   3. lb-page-lib restoreScroll：键盘（焦点不在滚动容器里）也算用户动了；新一次恢复取消上一次，不两个循环互相抢。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path');
const { ROOT, asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const wheelEv = (target, extra = {}) => { const e = { target, deltaY: 100, deltaX: 0, deltaMode: 0, ctrlKey: false, prevented: false, ...extra }; e.preventDefault = () => { e.prevented = true; }; e.stopPropagation = () => {}; return e; };
const fireWheel = (el, target, extra) => { const e = wheelEv(target, extra); for (const fn of [...(el.listeners.wheel || [])]) fn(e); return e; };

// ── 1. 图片导航 ──
function mediaEnv() {
  const dom = makeDom();
  const El = dom.El;
  El.prototype.scrollTo = function (o) { this.scrolledTo = (this.scrolledTo || 0) + 1; if (o && typeof o.left === 'number') this.scrollLeft = o.left; };
  // 钉子按钮的 innerHTML 里有 <span>，假 DOM 的 innerHTML 会把标签抹掉：这里补一个 span
  Object.defineProperty(El.prototype, 'innerHTML', { configurable: true, get() { return this.textContent; }, set(v) { this.textContent = ''; if (/<span/.test(String(v))) this.createEl('span'); } });
  const window = { innerHeight: 800, innerWidth: 1200, getSelection: () => null };
  class Obs { observe() {} disconnect() {} }
  return { dom, El, window, Obs };
}
function loadNew(env) {
  const src = fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/media-nav.js'), 'utf8');
  const m = { exports: {} };
  new Function('require', 'module', 'exports', 'document', 'window', 'Element', 'MutationObserver', 'ResizeObserver', src)(() => ({}), m, m.exports, env.dom.document, env.window, env.El, env.Obs, env.Obs);
  const cleanups = [];
  const host = { app: { plugins: { enabledPlugins: new Set() } }, register(fn) { cleanups.push(fn); }, registerDomEvent(el, t, fn) { el.addEventListener(t, fn); } };
  const nav = m.exports({}, host); nav.cleanups = cleanups; return nav;
}
function loadOld(env) {
  const src = fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-native-media-nav/main.js'), 'utf8');
  const m = { exports: {} };
  class Plugin { constructor() { this.cleanups = []; } register(fn) { this.cleanups.push(fn); } registerDomEvent(el, t, fn) { el.addEventListener(t, fn); } }
  new Function('require', 'module', 'exports', 'document', 'window', 'Element', 'MutationObserver', 'ResizeObserver', src)(() => ({ Plugin }), m, m.exports, env.dom.document, env.window, env.El, env.Obs, env.Obs);
  return new m.exports();
}
function buildNote(preview, slides = 2) {
  const note = preview.createEl('div', { cls: 'lb-note' });
  note.style.setProperty = () => {};
  const media = note.createEl('div', { cls: 'lb-side' }).createEl('section', { cls: 'lb-media' });
  const car = media.createEl('div', { cls: 'lb-carousel' });
  for (let i = 0; i < slides; i++) car.createEl('figure', { cls: 'lb-slide' }).createEl('img');
  const main = note.createEl('div', { cls: 'lb-main' });
  const sc = main.createEl('div', { cls: 'lb-scroll' }); sc.scrollHeight = 2000; sc.clientHeight = 500;
  const para = sc.createEl('p', { text: '正文' });
  return { note, media, car, sc, para, side: media.parentNode };
}

async function mediaTests() {
  const env = mediaEnv();
  const leaf = env.dom.document.body.createEl('div', { cls: 'workspace-leaf-content' });
  const preview = leaf.createEl('div', { cls: 'markdown-preview-view xhs-note' });
  const A = buildNote(preview);
  const nav = loadNew(env);
  assert.equal(nav.attach(), true);
  const pin = A.media.querySelector('.lb-media-pin');
  assert.ok(pin, '笔记接上了图片导航');
  pin.onclick();
  assert.ok(A.note.classList.contains('lb-media-locked') && preview.classList.contains('lb-pane-locked'), '钉住');
  // 钉住时原行为：笔记里 .lb-scroll 外面滚滚轮 → 转给 .lb-scroll
  let e = fireWheel(preview, A.side);
  assert.ok(e.prevented && A.sc.scrollTop === 100, '钉住时滚轮转给正文栏（原行为不变）');
  e = fireWheel(preview, A.para);
  assert.ok(!e.prevented, '正文栏里面的滚轮交给浏览器');
  // 图片上滚轮 = 翻页
  e = fireWheel(preview, A.car.children[0]);
  assert.ok(e.prevented && A.car.scrolledTo === 1, '图片上滚轮翻页（原行为不变）');

  // 同一个标签页换到目录页：Obsidian 复用这个预览容器，旧笔记被摘掉
  A.note.remove(); preview.classList.remove('xhs-note');
  const card = preview.createEl('div', { cls: 'lbc-wrap' }).createEl('div', { cls: 'lbc-card' });
  e = fireWheel(preview, card);
  assert.ok(!e.prevented, '目录页上滚轮不能被旧笔记的监听吃掉');
  assert.equal(A.sc.scrollTop, 100, '也不再去滚已经不在页面上的旧正文栏');
  assert.ok(!preview.classList.contains('lb-pane-locked'), '旧笔记留下的「整页锁住」类名清掉（不然整页 overflow:hidden 滚不动）');
  console.log('PASS media-nav: pinned note left the pane → wheel on catalog/chat page no longer swallowed, stale lb-pane-locked cleared');

  // 再在同一个标签页打开另一篇：预览容器上始终只有一个滚轮监听
  card.parentNode.remove(); preview.classList.add('xhs-note');
  const B = buildNote(preview);
  nav.enhance(B.car);
  assert.equal((preview.listeners.wheel || []).length, 1, '每个预览容器只留一个滚轮监听（不再一篇笔记挂一个）');
  B.media.querySelector('.lb-media-pin').onclick();
  e = fireWheel(preview, B.side);
  assert.ok(e.prevented && B.sc.scrollTop === 100, '新笔记钉住时照常转给它自己的正文栏');

  // 旧插件和新 media-nav 同时开着：同一个预览容器上仍只有一个监听，图片上一格只翻一页
  const old = loadOld(env);
  await old.onload();
  B.note.remove();
  const C = buildNote(preview, 3);
  old.enhance(C.car);
  nav.enhance(C.car);
  assert.equal((preview.listeners.wheel || []).length, 1, '新旧两份插件同开：预览容器上仍只有一个滚轮监听');
  e = fireWheel(preview, C.car.children[1]);
  assert.ok(e.prevented && C.car.scrolledTo === 1, '图片上一格滚轮只翻一页');
  B.note.remove();
  e = fireWheel(preview, C.para);
  assert.ok(!e.prevented, '没钉住的笔记：正文上的滚轮交给浏览器');
  // 卸载：监听摘掉
  for (const fn of old.cleanups) fn();
  for (const fn of nav.cleanups) fn();
  assert.equal((preview.listeners.wheel || []).length, 0, '插件卸载后监听摘干净');
  console.log('PASS media-nav: one wheel listener per pane even with the old plugin also enabled; pinned scroll + image paging unchanged');
}

// ── 2. 问收藏：对话区停在原处 ──
const DATA = '_archive/catalog-data.json';
function chatSetup() {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const turns = [{ role: 'user', content: '悉尼有什么' }, { role: 'assistant', content: '有咖啡 [来源1]', sources: [{ citation: 1, title: '悉尼咖啡地图', note: 'Web/a.md' }] }];
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: '2026-10-02T10:00:00+10:00', items: [] }), '_archive/chat-session.json': JSON.stringify({ turns }), '_archive/chat-archive.json': '{"entries":[]}' });
  let reader = false, body = null;
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { el.createEl('p', { text: md }); },
    archiveSourceState: () => ({ reader, compare: false }),
    // Obsidian 拆出右侧来源窗格时把本页 DOM 挪进新的分栏容器：浏览器把里面滚动容器的 scrollTop 归零（可能还发一个 scroll 事件）
    async openArchiveSource() { reader = true; body.scrollTop = 0; (body.listeners.scroll || []).forEach(fn => fn({})); },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js') });
  return { dom, app, A, setBody(b) { body = b; } };
}
const userScroll = (body, top) => { fireWheel(body, body); body.scrollTop = top; (body.listeners.scroll || []).forEach(fn => fn({})); };

async function chatTests() {
  const S = chatSetup();
  await S.A.run();
  const q = s => S.A.container.querySelector(s);
  const body = q('.lbchat-body'); S.setBody(body);
  body.scrollHeight = 2000; body.clientHeight = 400;
  userScroll(body, 300);
  // 点「查看」：开右侧来源窗格
  const view = S.A.container.querySelectorAll('.lbchat-src button').find(b => b.textContent === '查看');
  assert.ok(view, '回答下面有「查看」');
  view.onclick(); await tick(5);
  assert.equal(body.scrollTop, 300, '点来源开右侧窗格后，对话区停在原处（不回首行）');
  // 引用编号 [来源1] 也一样
  const cite = q('.lbchat-cite'); assert.ok(cite);
  cite.onclick({ stopPropagation() {} }); await tick(5);
  assert.equal(body.scrollTop, 300, '点引用编号后也停在原处');
  // 拆分 / 关窗格引起的 layout-change：被挪过 DOM、scrollTop 归零（没发 scroll 事件）→ 回到原处
  body.scrollTop = 0; S.app.workspace.trigger('layout-change'); await tick(0);
  assert.equal(body.scrollTop, 300, 'layout-change 后回到原处');
  // Dataview 重跑把整页摘下再挂回：浏览器把挂回来的滚动容器归零 → 回到原处
  body.scrollTop = 0; await S.A.rerun(); await tick(5);
  assert.equal(S.A.container.querySelector('.lbchat-body'), body, '重跑挂回的是同一份 DOM');
  assert.equal(body.scrollTop, 300, 'Dataview 重跑挂回后对话区回到原处');
  // 记下来的位置没被「归零」那一下冲掉（换页再回来也对）
  assert.equal(JSON.parse(globalThis.sessionStorage?.getItem?.('lb:chat') || globalThis.__lbState['lb:chat']).scrollTop, 300, '页面状态里记的仍是 300');
  // 用户自己滚到顶：不拉回
  userScroll(body, 0); S.app.workspace.trigger('layout-change'); await tick(0);
  assert.equal(body.scrollTop, 0, '用户自己滚到顶的不拉回');
  // 停在底部跟随的：被归零后回到底部
  userScroll(body, 1600);
  body.scrollTop = 0; S.app.workspace.trigger('layout-change'); await tick(0);
  assert.equal(body.scrollTop, 2000, '停在底部的回到底部');
  console.log('PASS chat: opening a source / layout-change / Dataview rerun keep the conversation where it was (no jump to the first line)');

  // 页头 / 输入框上滚滚轮 = 滚对话区；对话区里面的滚轮交给浏览器
  userScroll(body, 300);
  const wrap = q('.lbchat');
  let e = fireWheel(wrap, q('.lbchat-head'), { deltaY: 120 });
  assert.ok(e.prevented && body.scrollTop === 420, '页头上滚滚轮 → 对话区往下滚');
  e = fireWheel(wrap, q('.lbchat-search'), { deltaY: -20 });
  assert.ok(e.prevented && body.scrollTop === 400, '输入框（没有可滚内容）上滚滚轮 → 对话区滚');
  const ta = q('.lbchat-search'); ta.scrollHeight = 300; ta.clientHeight = 40; ta.scrollTop = 0;
  e = fireWheel(wrap, ta, { deltaY: 50 });
  assert.ok(!e.prevented && body.scrollTop === 400, '输入框里字多到能滚：先滚输入框');
  e = fireWheel(wrap, q('.lbchat-answer'), { deltaY: 50 });
  assert.ok(!e.prevented && body.scrollTop === 400, '对话区里面的滚轮交给浏览器');
  e = fireWheel(wrap, q('.lbchat-head'), { deltaY: 50, ctrlKey: true });
  assert.ok(!e.prevented, 'Ctrl+滚轮（缩放）不接管');
  console.log('PASS chat: wheel over the header / composer scrolls the conversation');
}

// ── 3. restoreScroll ──
async function restoreTests() {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const V = makeVault({});
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: {} } };
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\nglobalThis.__LB = lbPageLib(dv, app, "catalog");' });
  await A.run();
  const LB = globalThis.__LB, el = A.host;
  el.scrollHeight = 5000; el.clientHeight = 500;
  // 键盘：焦点在页面正文（不在滚动容器里）按 PageDown 也算用户动了
  let p = LB.restoreScroll(800, { maxMs: 400, holdMs: 300 });
  await tick(20);
  assert.equal(el.scrollTop, 800);
  for (const fn of [...(dom.document.listeners.keydown || [])]) fn({ key: 'PageDown', target: dom.document.body });
  el.scrollTop = 1200; await tick(40);
  assert.equal(el.scrollTop, 1200, '按了键就不再抢滚动');
  await p;
  // 新一次恢复取消上一次：不两个循环轮流设
  const p1 = LB.restoreScroll(500, { maxMs: 300, holdMs: 200 });
  const p2 = LB.restoreScroll(900, { maxMs: 300, holdMs: 200 });
  const seen = new Set();
  for (let i = 0; i < 8; i++) { await tick(8); seen.add(el.scrollTop); }
  assert.deepEqual([...seen], [900], '只有最新一次恢复在守');
  await Promise.all([p1, p2]);
  assert.equal((el.listeners.wheel || []).length, 0, '恢复结束后监听摘干净');
  console.log('PASS restoreScroll: keyboard anywhere counts as user input; a newer restore cancels the older one; listeners removed');
}

(async () => {
  await mediaTests();
  await chatTests();
  await restoreTests();
})().catch(e => { console.error(e); process.exit(1); });

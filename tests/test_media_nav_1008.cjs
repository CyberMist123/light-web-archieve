// 批次 D · L3 图片导航（media-nav.js）：N1 滚轮翻到头放行；N12 只盯新出现的轮播、尺寸监听用完就放；
// N15 默认钉住（阅读视图）、例外不钉、每篇记住钉没钉 / 第几张 / 正文滚到哪、钉住时左栏能用滚轮滚、钉住时 note 顶不被滚出去、钉住后促一次 scroll；
// N-M2 ←/→ 不翻后台 / 别的分栏；F6 视频工具行「循环」「连播…」；openLightbox(images, index, {caption, onCaption, onClose}) 给问收藏用、菜单开着时键盘归菜单。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path');
const { ROOT, makeDom } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const frames = () => tick(60);   // 没有 requestAnimationFrame 时 media-nav 用 16ms 的 setTimeout
const wheelEv = (target, extra = {}) => { const e = { target, deltaY: 100, deltaX: 0, deltaMode: 0, ctrlKey: false, prevented: false, ...extra }; e.preventDefault = () => { e.prevented = true; }; e.stopPropagation = () => {}; return e; };
const fireWheel = (el, target, extra) => { const e = wheelEv(target, extra); for (const fn of [...(el.listeners.wheel || [])]) fn(e); return e; };

function makeEnv() {
  const dom = makeDom();
  const El = dom.El;
  El.prototype.scrollTo = function (o) { this.scrolledTo = (this.scrolledTo || 0) + 1; if (o && typeof o.left === 'number') this.scrollLeft = o.left; };
  Object.defineProperty(El.prototype, 'innerHTML', { configurable: true, get() { return this.textContent; }, set(v) { this.textContent = ''; if (/<span/.test(String(v))) this.createEl('span'); } });
  const wl = {};
  const window = { innerHeight: 800, innerWidth: 1200, getSelection: () => null,
    addEventListener(t, fn) { (wl[t] = wl[t] || []).push(fn); }, removeEventListener(t, fn) { wl[t] = (wl[t] || []).filter(f => f !== fn); }, wl };
  const mos = [];
  class MO { constructor(cb) { this.cb = cb; mos.push(this); } observe() {} disconnect() {} }
  class RO { constructor(cb) { this.cb = cb; this.live = true; } observe() {} disconnect() { this.live = false; } }
  return { dom, El, D: dom.document, window, mos, MO, RO };
}
function load(E, { settings = {}, leaves = [], activeLeaf = null, playerUI = null } = {}) {
  const src = fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/media-nav.js'), 'utf8');
  const m = { exports: {} };
  new Function('require', 'module', 'exports', 'document', 'window', 'Element', 'MutationObserver', 'ResizeObserver', 'innerWidth', 'innerHeight', 'Event', src)(() => ({}), m, m.exports, E.D, E.window, E.El, E.MO, E.RO, 1200, 800, E.dom.Event);
  const notices = [], saved = [];
  const host = { app: { plugins: { enabledPlugins: new Set(), manifests: {} }, workspace: { activeLeaf, getLeavesOfType: () => leaves }, metadataCache: { getFileCache: () => null } },
    settings, saveSettings: async () => { saved.push(JSON.parse(JSON.stringify(host.settings))); }, notify: m => notices.push(m), playerUI,
    cleanups: [], register(fn) { this.cleanups.push(fn); }, registerDomEvent(el, t, fn) { el.addEventListener(t, fn); }, registerEvent() {} };
  const nav = m.exports({ Notice: class {} }, host);
  nav.host = host; nav.notices = notices; nav.saved = saved;
  return nav;
}
// 阅读视图里的一篇：.workspace-leaf > .workspace-leaf-content > .markdown-reading-view > .markdown-preview-view.xhs-note > .lb-note
function makePane(E, { reading = true, leafCls = '' } = {}) {
  const leaf = E.D.body.createEl('div', { cls: 'workspace-leaf' });
  const lc = leaf.createEl('div', { cls: 'workspace-leaf-content ' + leafCls });
  const preview = reading ? lc.createEl('div', { cls: 'markdown-reading-view' }).createEl('div', { cls: 'markdown-preview-view xhs-note' })
    : lc.createEl('div', { cls: 'markdown-source-view xhs-note' });
  return { leaf, lc, preview };
}
function buildNote(preview, { slides = 3, item = 'xhs-n1', video = false } = {}) {
  const note = preview.createEl('div', { cls: 'lb-note' });
  if (item) note.dataset.lbItem = item;
  const side = note.createEl('div', { cls: 'lb-side' });
  const media = side.createEl('section', { cls: 'lb-media' });
  const car = media.createEl('div', { cls: 'lb-carousel' });
  if (video) car.createEl('figure', { cls: 'lb-slide' }).createEl('video');
  else for (let i = 0; i < slides; i++) { const f = car.createEl('figure', { cls: 'lb-slide' }); f.offsetLeft = i * 500; f.createEl('img'); }
  const annot = side.createEl('div', { cls: 'lba-annot lba-in-side' });
  const main = note.createEl('div', { cls: 'lb-main' });
  const sc = main.createEl('div', { cls: 'lb-scroll' }); sc.scrollHeight = 2000; sc.clientHeight = 500;
  const para = sc.createEl('p', { text: '正文' });
  return { note, side, media, car, annot, sc, para, img: i => car.children[i] && car.children[i].querySelector('img') };
}
const locked = n => n.note.classList.contains('lb-media-locked');

(async () => {
  // ── N15 ①：阅读视图默认钉住 ──
  {
    const E = makeEnv(); const P = makePane(E); const N = buildNote(P.preview);
    let scrolls = 0; P.preview.addEventListener('scroll', () => scrolls++);
    const nav = load(E); assert.equal(nav.attach(), true);
    assert.ok(locked(N), '阅读视图默认钉住');
    assert.ok(P.preview.classList.contains('lb-pane-locked'));
    assert.equal(N.media.querySelector('.lb-media-pin').getAttribute('aria-pressed'), 'true');
    await frames();
    assert.ok(scrolls >= 1, '⑧ 钉住后派发过一次 scroll（促阅读视图渲染底部的批注段）');
  }
  // ── N15 ②：例外不钉 ──
  for (const [how, mk] of [
    ['来源窗格 .lb-source-reader', E => makePane(E, { leafCls: 'lb-source-reader' })],
    ['实时预览（.markdown-source-view）', E => makePane(E, { reading: false })],
    ['悬停预览 .hover-popover', E => { const pop = E.D.body.createEl('div', { cls: 'popover hover-popover' }); const rv = pop.createEl('div', { cls: 'markdown-reading-view' }); return { preview: rv.createEl('div', { cls: 'markdown-preview-view xhs-note' }) }; }],
  ]) {
    const E = makeEnv(); const P = mk(E); const N = buildNote(P.preview);
    load(E).attach();
    assert.ok(!locked(N), how + '：默认不钉');
  }
  { // 问收藏的来源窗格：leaf 登记成 lbArchiveReader（类是 openFile 之后才加的）
    const E = makeEnv(); const P = makePane(E); const N = buildNote(P.preview);
    const owner = { lbArchiveReader: { view: { containerEl: P.lc } } };
    load(E, { leaves: [owner] }).attach();
    assert.ok(!locked(N), '登记成来源窗格的 leaf：默认不钉');
  }

  // ── N1：滚轮翻到头放行 ──
  {
    const E = makeEnv(); const P = makePane(E); const N = buildNote(P.preview);
    const nav = load(E); nav.attach();
    N.media.querySelector('.lb-media-pin').onclick();   // 取消钉住
    assert.ok(!locked(N));
    N.car.scrollLeft = 1000; let before = N.car.scrolledTo || 0;
    let e = fireWheel(P.preview, N.img(2));
    assert.ok(!e.prevented && (N.car.scrolledTo || 0) === before, '① 不钉：最后一张往下滚 → 放行给页面');
    N.car.scrollLeft = 0; N.car.lbFlipAt = 0;
    e = fireWheel(P.preview, N.img(0), { deltaY: -100 });
    assert.ok(!e.prevented, '② 第一张往上滚 → 放行');
    N.car.scrollLeft = 500; before = N.car.scrolledTo || 0;
    e = fireWheel(P.preview, N.img(1));
    assert.ok(e.prevented && N.car.scrolledTo === before + 1 && N.car.scrollLeft === 1000, '④ 中间张照常翻');
    e = fireWheel(P.preview, N.img(1));
    assert.ok(e.prevented && N.car.scrolledTo === before + 1, '⑤ 刚翻到最后一张、350ms 内再滚：拦住、不翻、不滚页面');
    N.media.querySelector('.lb-media-pin').onclick();   // 钉住
    N.car.lbFlipAt = 0; N.sc.scrollTop = 0;
    e = fireWheel(P.preview, N.img(2));
    assert.ok(e.prevented && N.sc.scrollTop === 100, '③ 钉住：最后一张往下滚 → 转给正文栏');
  }

  // ── N15 ⑥：钉住时左栏能用滚轮滚，到头才转给正文栏 ──
  {
    const E = makeEnv(); const P = makePane(E); const N = buildNote(P.preview);
    load(E).attach();
    assert.ok(locked(N));
    N.side.style.overflowY = 'auto'; N.side.scrollHeight = 1200; N.side.clientHeight = 600; N.side.scrollTop = 0;
    let e = fireWheel(P.preview, N.annot);
    assert.ok(!e.prevented && (N.sc.scrollTop || 0) === 0, '左栏还能往下滚：交给浏览器滚左栏，正文栏不动');
    N.side.scrollTop = 600;
    e = fireWheel(P.preview, N.annot);
    assert.ok(e.prevented && N.sc.scrollTop === 100, '左栏到底：转给正文栏');
  }

  // ── N15 ③④⑤：后台重写后照原样；换一篇默认钉住 ──
  {
    const E = makeEnv(); const P = makePane(E); let N = buildNote(P.preview);
    const nav = load(E); nav.attach();
    N.media.querySelector('.lb-media-pin').onclick();   // 取消钉住
    N.car.scrollLeft = 1000; N.car.dispatchEvent({ type: 'scroll' }); await tick(200);
    N.note.remove();
    N = buildNote(P.preview); nav.enhance(N.car); await frames();
    assert.ok(!locked(N), '③ 同一篇重写：保持不钉');
    assert.equal(N.car.scrollLeft, 1000, '③ 轮播回到第 3 张');
    N.media.querySelector('.lb-media-pin').onclick();   // 钉住
    N.sc.scrollTop = 400; N.sc.dispatchEvent({ type: 'scroll' }); await frames();
    N.note.remove();
    N = buildNote(P.preview); nav.enhance(N.car); await frames();
    assert.ok(locked(N), '④ 保持钉住');
    assert.equal(N.sc.scrollTop, 400, '④ 正文栏回到原来的位置');
    N.note.remove();
    const M = buildNote(P.preview, { item: 'xhs-n2' }); nav.enhance(M.car);
    assert.ok(locked(M), '⑤ 换一篇：走默认钉住（不跨篇）');
    assert.equal(M.car.scrollLeft || 0, 0);
  }

  // ── N15 ⑦：preview 已经往下滚了再钉：note 顶不在 preview 上沿之上 ──
  {
    const E = makeEnv(); const P = makePane(E); const N = buildNote(P.preview);
    P.preview._rect = { top: 100, height: 700 };
    N.note.getBoundingClientRect = () => ({ top: 200 - (P.preview.scrollTop || 0), bottom: 900, left: 0, right: 1000, height: 700, width: 1000 });
    P.preview.scrollTop = 300;
    load(E).attach();
    assert.ok(locked(N));
    assert.ok(N.note.getBoundingClientRect().top >= P.preview.getBoundingClientRect().top, '钉住后 note 顶部回到 preview 里');
    assert.equal(P.preview.scrollTop, 100);
  }

  // ── N12：无关插入不扫描；新轮播才扫；换页清锁；尺寸监听用完就放 ──
  {
    const E = makeEnv(); const P = makePane(E); const N = buildNote(P.preview);
    const nav = load(E); nav.attach();
    const mo = E.mos[0];
    const other = E.D.body.createEl('div', { cls: 'lbchat' });
    const nodes = Array.from({ length: 50 }, () => other.createEl('p', { text: '流式' }));
    mo.cb([{ addedNodes: nodes }]); await tick(0);
    assert.equal(nav.stats.scan, 0, '别处 50 次普通插入：一次都不扫');
    const fitBefore = nav.stats.fit;
    const N2pane = makePane(E); const N2 = buildNote(N2pane.preview, { item: 'xhs-n3' });
    mo.cb([{ addedNodes: [N2.note] }]); await tick(0);
    assert.equal(nav.stats.scan, 1, '新出现的轮播：扫一次'); assert.equal(N2.car.dataset.lbEnhanced, '1');
    assert.ok(nav.stats.fit > fitBefore);
    // 同一窗格从钉住的笔记换到目录页（不发滚轮）：整页锁就地清掉
    assert.ok(P.preview.classList.contains('lb-pane-locked'));
    const size = nav.ros.size;
    N.note.remove();
    const card = P.preview.createEl('div', { cls: 'lbc-wrap' }).createEl('div', { cls: 'lbc-card' });
    mo.cb([{ addedNodes: [card.parentNode] }]); await tick(0);
    assert.ok(!P.preview.classList.contains('lb-pane-locked'), '换到目录页：残留的整页锁清掉');
    N.car.lbFit();
    assert.equal(nav.ros.size, size - 1, '轮播不在了：它的尺寸监听断开并移出集合');
    for (const fn of nav.host.cleanups) fn();
    assert.equal(nav.ros.size, 0);
  }

  // ── N-M2：←/→ 只翻看得见、当前那一栏 ──
  {
    const E = makeEnv(); const P = makePane(E); const N = buildNote(P.preview);
    const Q = makePane(E); const other = Q.preview.createEl('p', { text: '另一栏' });
    const activeLeaf = { containerEl: P.leaf };
    const nav = load(E, { activeLeaf }); nav.attach();
    const key = (target) => { const e = { key: 'ArrowRight', target, defaultPrevented: false, prevented: false, preventDefault() { this.prevented = true; }, stopPropagation() {} }; for (const fn of [...(E.D.listeners.keydown || [])]) fn(e); return e; };
    nav.activeCarousel = N.car; N.car.scrollLeft = 0;
    N.car.offsetParent = null;
    let e = key(E.D.body);
    assert.ok(!e.prevented && !N.car.scrolledTo, '后台标签页（display:none）里的那篇不翻');
    N.car.offsetParent = undefined; delete N.car._op;
    e = key(other);
    assert.ok(!e.prevented && !N.car.scrolledTo, '按键在另一个分栏里：不翻');
    activeLeaf.containerEl = Q.leaf;
    e = key(E.D.body);
    assert.ok(!e.prevented, '焦点在 body、当前活动 leaf 不含它：不翻');
    activeLeaf.containerEl = P.leaf;
    e = key(E.D.body);
    assert.ok(e.prevented && N.car.scrolledTo === 1, '当前活动 leaf 里的那篇：照常翻');
  }

  // ── F6：视频工具行「循环」「连播…」 ──
  {
    const E = makeEnv(); const P = makePane(E); const V = buildNote(P.preview, { video: true });
    const picks = [];
    const nav = load(E, { settings: { media: { loop: false, playlistOrder: 'newest' } }, playerUI: { openTagPicker: o => { picks.push(o); } } });
    nav.attach();
    const loop = V.media.querySelector('.lb-video-loop'), pl = V.media.querySelector('.lb-video-playlist');
    assert.ok(V.media.querySelector('.lb-video-speed') && loop && pl, '倍速、循环、连播在同一行');
    assert.equal(pl.textContent, '连播…');
    const video = V.car.querySelector('video');
    assert.equal(video.loop, false); assert.equal(loop.getAttribute('aria-pressed'), 'false');
    await loop.onclick();
    assert.equal(video.loop, true); assert.equal(loop.getAttribute('aria-pressed'), 'true');
    assert.deepEqual(nav.host.settings.media, { loop: true, playlistOrder: 'newest' }, '记进 settings.media.loop，别的键不动');
    assert.equal(nav.saved.length, 1, 'saveSettings 调了');
    const V2 = buildNote(makePane(E).preview, { video: true, item: 'xhs-v2' }); nav.enhance(V2.car);
    assert.equal(V2.car.querySelector('video').loop, true, '之后新打开的视频初始就是循环');
    pl.onclick();
    assert.deepEqual(picks, [{ itemId: 'xhs-n1' }], '连播 → playerUI.openTagPicker({itemId})');
    nav.host.playerUI = null; pl.onclick();
    assert.ok(nav.notices.some(m => m.includes('连播还没装好')), '播放器没装上：说一句，不报错');
  }

  // ── openLightbox（L2 用）──
  {
    const E = makeEnv(); const nav = load(E); nav.attach();
    assert.equal(nav.openLightbox([], 0), null, '没有图：null');
    let picked = null, closedAt = null;
    const h = nav.openLightbox([{ src: 'a.png' }, { src: 'b.png', alt: 'B' }], 1, { caption: i => '来源1 · 图' + (i + 1), onCaption: i => { picked = i; }, onClose: i => { closedAt = i; } });
    assert.ok(h && typeof h.close === 'function', '打开成功返回 {close()}（不是 null）');
    const lb = E.D.body.querySelector('.lb-lightbox');
    assert.ok(lb); assert.equal(lb.querySelector('img').src, 'b.png');
    assert.equal(lb.querySelector('.lb-lb-count').textContent, '2 / 2');
    assert.equal(lb.querySelector('.lb-lb-caption').textContent, '来源1 · 图2');
    // 右键菜单开着：Esc 归菜单，不关大图
    nav.host.menuOpen = true;
    for (const fn of E.window.wl.keydown || []) fn({ key: 'Escape', preventDefault() {}, stopPropagation() {} });
    assert.ok(lb.isConnected, '菜单开着时 Esc 不关大图');
    nav.host.menuOpen = false;
    for (const fn of E.window.wl.keydown || []) fn({ key: 'ArrowLeft', preventDefault() {}, stopPropagation() {} });
    assert.equal(lb.querySelector('.lb-lb-caption').textContent, '来源1 · 图1', '←/→ 切图，说明跟着变');
    lb.querySelector('.lb-lb-caption').dispatchEvent({ type: 'click', stopPropagation() {} });
    assert.equal(picked, 0, '点说明 → onCaption(当前那张)');
    assert.ok(!lb.isConnected, '点说明先关大图'); assert.equal(closedAt, 0);
    assert.equal((E.window.wl.keydown || []).length, 0, '关掉后键盘监听摘掉');
  }
  console.log('PASS media-nav 1008: default pin in reading view (not in source pane / live preview / hover popover / archive reader leaf), per-note state survives rewrite, locked note kept in view + scroll nudge, left column wheel-scrolls before forwarding, wheel passes through at first/last image, scans only on new carousels + stale lock cleared + RO released, arrows only in the visible active pane, video loop (settings.media.loop) + 连播… → playerUI.openTagPicker, openLightbox API (caption / onCaption / onClose, menu guard)');
})().catch(e => { console.error(e); process.exit(1); });

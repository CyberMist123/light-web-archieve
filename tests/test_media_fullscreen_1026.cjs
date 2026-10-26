// 1026 她（录屏 13:22）：「你看它不是全屏。」——点图 / 视频能真正铺满屏幕，倍速 / 循环 / 下一条照样在，退出不丢阅读进度。
// media-nav.js：笔记页视频工具行「全屏」（全屏的是整块 .lb-media，不是 <video>；原生全屏键换掉、双击画面也是它）、
// 大图查看器 ⛶ / F / Esc（Esc 先退全屏、再按才关）；不支持 requestFullscreen 时退回铺满窗口（.lb-fs-fallback，Esc 退）；
// 退出时右栏 .lb-scroll 和各级滚动容器放回进全屏前的位置。player-ui.js：连播「⛶ 全屏」全屏整块画面，切下一条不掉出全屏，F 切换，关页先退出。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path');
const { ROOT, makeDom, makeWorkspace, makeMetadataCache } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const frames = () => tick(60);

function makeEnv({ native = true } = {}) {
  const dom = makeDom();
  const El = dom.El, D = dom.document;
  El.prototype.scrollTo = function (o) { if (o && typeof o.left === 'number') this.scrollLeft = o.left; };
  Object.defineProperty(El.prototype, 'innerHTML', { configurable: true, get() { return this.textContent; }, set(v) { this.textContent = ''; if (/<span/.test(String(v))) this.createEl('span'); } });
  const change = () => { for (const fn of [...((D.listeners && D.listeners.fullscreenchange) || [])]) fn({ type: 'fullscreenchange' }); };
  D.fullscreenElement = null;
  if (native) {
    El.prototype.requestFullscreen = async function () { D.fullscreenElement = this; change(); };
    D.exitFullscreen = async () => { D.fullscreenElement = null; change(); };
  } else {
    delete El.prototype.requestFullscreen;
  }
  const wl = {};
  const window = { innerHeight: 800, innerWidth: 1200, getSelection: () => null,
    addEventListener(t, fn) { (wl[t] = wl[t] || []).push(fn); }, removeEventListener(t, fn) { wl[t] = (wl[t] || []).filter(f => f !== fn); }, wl };
  class MO { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} }
  class RO { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} }
  // 浏览器自己按 Esc 退出全屏（不经我们的按钮）
  const browserEsc = () => { D.fullscreenElement = null; change(); };
  return { dom, El, D, window, MO, RO, browserEsc };
}
function load(E, { settings = {} } = {}) {
  const src = fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/media-nav.js'), 'utf8');
  const m = { exports: {} };
  new Function('require', 'module', 'exports', 'document', 'window', 'Element', 'MutationObserver', 'ResizeObserver', 'innerWidth', 'innerHeight', 'Event', src)(() => ({}), m, m.exports, E.D, E.window, E.El, E.MO, E.RO, 1200, 800, E.dom.Event);
  const host = { app: { plugins: { enabledPlugins: new Set(), manifests: {} }, workspace: { activeLeaf: null, getLeavesOfType: () => [] }, metadataCache: { getFileCache: () => null } },
    settings, saveSettings: async () => {}, notify: () => {}, cleanups: [], register(fn) { this.cleanups.push(fn); }, registerDomEvent(el, t, fn) { el.addEventListener(t, fn); }, registerEvent() {} };
  const nav = m.exports({ Notice: class {} }, host);
  return nav;
}
function videoNote(E) {
  const leaf = E.D.body.createEl('div', { cls: 'workspace-leaf' });
  const preview = leaf.createEl('div', { cls: 'workspace-leaf-content' }).createEl('div', { cls: 'markdown-reading-view' }).createEl('div', { cls: 'markdown-preview-view xhs-note' });
  const note = preview.createEl('div', { cls: 'lb-note' }); note.dataset.lbItem = 'xhs-v1';
  const media = note.createEl('div', { cls: 'lb-side' }).createEl('section', { cls: 'lb-media' });
  const car = media.createEl('div', { cls: 'lb-carousel' });
  const video = car.createEl('figure', { cls: 'lb-slide' }).createEl('video');
  const sc = note.createEl('div', { cls: 'lb-main' }).createEl('div', { cls: 'lb-scroll' }); sc.scrollHeight = 3000; sc.clientHeight = 500;
  return { preview, note, media, car, video, sc };
}
const keydown = (E, key) => { const e = { key, prevented: false, preventDefault() { this.prevented = true; }, stopPropagation() {} }; for (const fn of [...(E.window.wl.keydown || [])]) fn(e); return e; };

(async () => {
  // ── 笔记页视频：「全屏」全屏整块媒体（倍速 / 循环 / 连播都在里面），退出把阅读位置放回 ──
  {
    const E = makeEnv(); const V = videoNote(E); const nav = load(E, { settings: { media: { loop: false } } }); nav.attach();
    const btn = V.media.querySelector('.lb-video-full');
    assert.ok(btn, '工具行有「全屏」'); assert.equal(btn.textContent, '全屏');
    assert.equal(V.video.getAttribute('controlslist'), 'nofullscreen', '原生全屏键（只全屏 <video>、控件全丢）换掉');
    V.sc.scrollTop = 700; V.preview.scrollTop = 120;
    btn.onclick({}); await tick();
    assert.equal(E.D.fullscreenElement, V.media, '全屏的是整块 .lb-media，不是 <video>');
    assert.ok(V.media.classList.contains('is-lb-fullscreen'));
    assert.ok(V.media.querySelector('.lb-video-speed') && V.media.querySelector('.lb-video-loop') && V.media.querySelector('.lb-video-playlist'), '倍速 / 循环 / 连播都在全屏的那块里');
    assert.equal(btn.getAttribute('aria-pressed'), 'true'); assert.equal(btn.textContent, '退出全屏');
    // 全屏期间页面重排把滚动冲掉了；浏览器自己按 Esc 退出
    V.sc.scrollTop = 0; V.preview.scrollTop = 0;
    E.browserEsc(); await frames();
    assert.ok(!V.media.classList.contains('is-lb-fullscreen'));
    assert.equal(V.sc.scrollTop, 700, '右栏正文滚到哪还在哪'); assert.equal(V.preview.scrollTop, 120, '整页滚动也放回');
    assert.equal(btn.textContent, '全屏'); assert.equal(btn.getAttribute('aria-pressed'), 'false');
    // 双击画面 = 全屏；再点按钮退出
    let prevented = false;
    for (const fn of V.video.listeners.dblclick || []) fn({ button: 0, preventDefault() { prevented = true; }, stopPropagation() {} });
    await tick();
    assert.ok(prevented, '双击不走原生（原生只全屏 <video>）'); assert.equal(E.D.fullscreenElement, V.media);
    btn.onclick({}); await tick(); await frames();
    assert.equal(E.D.fullscreenElement, null); assert.ok(!V.media.classList.contains('is-lb-fullscreen'));
  }
  // ── 不支持 requestFullscreen：铺满窗口（.lb-fs-fallback），Esc 退出 ──
  {
    const E = makeEnv({ native: false }); const V = videoNote(E); const nav = load(E); nav.attach();
    V.sc.scrollTop = 333;
    V.media.querySelector('.lb-video-full').onclick({}); await tick();
    assert.ok(V.media.classList.contains('lb-fs-fallback') && V.media.classList.contains('is-lb-fullscreen'));
    V.sc.scrollTop = 0;
    const e = keydown(E, 'Escape'); await frames();
    assert.ok(e.prevented && !V.media.classList.contains('lb-fs-fallback'), 'Esc 退出铺满');
    assert.equal(V.sc.scrollTop, 333);
    assert.equal((E.window.wl.keydown || []).length, 0, 'Esc 监听摘掉');
  }
  // ── 大图：⛶ / F 全屏；Esc 先退全屏，再按才关；全屏里关大图先退出 ──
  {
    const E = makeEnv(); const nav = load(E); nav.attach();
    const h = nav.openLightbox([{ src: 'a.png' }, { src: 'b.png' }], 0);
    const lb = E.D.body.querySelector('.lb-lightbox');
    const full = lb.querySelector('.lb-lb-full');
    assert.ok(full && full.getAttribute('aria-label') === '全屏');
    full.dispatchEvent({ type: 'click', stopPropagation() {} }); await tick();
    assert.equal(E.D.fullscreenElement, lb); assert.equal(full.getAttribute('aria-pressed'), 'true');
    keydown(E, 'ArrowRight');
    assert.equal(lb.querySelector('.lb-lb-count').textContent, '2 / 2', '全屏里照样翻页');
    keydown(E, 'Escape'); await tick();
    assert.equal(E.D.fullscreenElement, null); assert.ok(lb.isConnected, 'Esc 先退全屏，大图还开着');
    keydown(E, 'f'); await tick();
    assert.equal(E.D.fullscreenElement, lb, 'F 进全屏');
    h.close(); await tick();
    assert.equal(E.D.fullscreenElement, null, '全屏里关大图：先退出来'); assert.ok(!lb.isConnected);
  }
  // ── 连播：⛶ 全屏全屏整块画面，切下一条不掉出全屏，F 切换，关页先退出 ──
  {
    const dom = makeDom(), D = dom.document;
    D.fullscreenElement = null;
    const change = () => { for (const fn of [...((D.listeners && D.listeners.fullscreenchange) || [])]) fn({}); };
    dom.El.prototype.requestFullscreen = async function () { D.fullscreenElement = this; change(); };
    D.exitFullscreen = async () => { D.fullscreenElement = null; change(); };
    const obs = makeObsidian(D, {}); const ws = makeWorkspace(); const views = {};
    const plugin = { lbPath: p => 'LB/' + p, settings: { media: {} }, saveSettings() {}, notify() {},
      app: { workspace: ws, metadataCache: makeMetadataCache({}), vault: { adapter: { getResourcePath: p => 'app://res/' + p }, getMarkdownFiles: () => [], getAbstractFileByPath: () => null } },
      registerView(t, f) { views[t] = f; }, addCommand() {}, runPy: async () => ({ json: null }) };
    const ui = require(path.join(ROOT, 'obsidian-plugins/link-brain-actions/player-ui.js'))(obs, plugin, { setTimeout: () => {} });
    ui.attach();
    ws.getLeaf = () => { const leaf = { async setViewState(s) { if (!leaf.view) { leaf.view = views[s.type](leaf); await leaf.view.onOpen(); } await leaf.view.setState(s.state, {}); } }; ws.leaves.push(leaf); return leaf; };
    const items = [1, 2].map(i => ({ item_id: `xhs-${i}`, title: `T${i}`, note: `n${i}.md`, video: `v${i}.mp4`, duration_sec: 60 }));
    const view = await ui.startPlaylist({ ok: true, tag: '做饭', order: 'newest', items, start_index: 0 }, {});
    assert.ok(view.fullBtn && view.stage.contains(view.fullBtn), '「全屏」在画面上的工具行里');
    assert.equal(view.video.getAttribute('controlslist'), 'nofullscreen');
    await view.toggleFull();
    assert.equal(D.fullscreenElement, view.stage, '全屏的是整块画面（上一条 / 倍速 / 循环 / 下一条都在）');
    assert.ok(view.stage.querySelector('.lb-player-next') && view.stage.querySelector('.lb-player-speed') && view.stage.querySelector('.lb-player-loop'));
    assert.equal(view.fsTitle.textContent, '第 1 / 2 · T1');
    view.next();
    assert.equal(D.fullscreenElement, view.stage, '切下一条不掉出全屏'); assert.equal(view.fsTitle.textContent, '第 2 / 2 · T2');
    view.onKey({ key: 'f', preventDefault() {} }); await tick();
    assert.equal(D.fullscreenElement, null, 'F 退出'); assert.equal(view.fullBtn.textContent, '⛶ 全屏');
    view.onKey({ key: 'F', preventDefault() {} }); await tick();
    assert.equal(D.fullscreenElement, view.stage);
    await view.onClose();
    assert.equal(D.fullscreenElement, null, '关连播页先退出全屏');
  }
  console.log('PASS media fullscreen 1026: note video 全屏 = whole .lb-media (speed / loop / 连播 inside), native fullscreen key replaced, dblclick, scroll restored on exit (incl. browser Esc), fallback fills window + Esc; lightbox ⛶ / F, Esc exits fullscreen first, close exits; player ⛶ fullscreen stage, next keeps fullscreen, F toggles, onClose exits');
})().catch(e => { console.error(e); process.exit(1); });

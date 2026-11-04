// 1031 作者（第二轮）：真 Edge 里把 media-nav + danmaku + 批注框（annotate-view.js）一起跑在一篇合成的 B 站视频笔记上：
// ①批注框下面「记在当前时间」：写一条 → notes.json 带 video_t，列表里有「▶ 0:00」时间标，画面上立刻飘出带细框的那条；
// ②全屏：工具行不显示，画面右下角「弹」字开关在原生控制条上方（不压住控制条那 48px），鼠标动出现、静止 2 秒淡出，点了关 / 开；
// ③高级弹幕（mode 7）按坐标静态显示。截图进 LWA_QA_DIR（danmaku-*.png）。不连网、不碰真库（vault 是内存里的假 adapter）。
'use strict';
const { chromium } = require('playwright');
const fs = require('fs'), os = require('os'), path = require('path');
const assert = require('assert/strict');
const ROOT = path.resolve(__dirname, '..', '..');
const QA = process.env.LWA_QA_DIR || path.join(os.tmpdir(), 'lwa-qa');
fs.mkdirSync(QA, { recursive: true });
const rd = p => fs.readFileSync(path.join(ROOT, p), 'utf8');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' }).catch(() => chromium.launch({ headless: true }));
  const page = await browser.newPage({ viewport: { width: 1200, height: 760 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const mp4 = 'data:video/mp4;base64,' + fs.readFileSync(path.join(ROOT, 'tests/fixtures/tiny-1s.mp4')).toString('base64');
  const SID = 'BV1ui000001', base = `_archive/bilibili/${SID}`;
  const xml = '<?xml version="1.0" encoding="UTF-8"?><i>'
    + [[0.05, 1, 25, 16777215, '原弹幕：开头'], [0.15, 1, 25, 16776960, '黄色滚动弹幕'], [0.25, 5, 25, 16711680, '顶部红字'], [0.35, 4, 25, 65280, '底部绿字'], [0.4, 1, 25, 16777215, '哈哈哈哈哈哈']]
      .map(([t, m, s, c, x]) => `<d p="${t},${m},${s},${c},0,0,a,1,5">${x}</d>`).join('')
    + '<d p="0.1,7,40,16777215,0,0,a,1,5">["400","260","1-0","9","高级弹幕/n静态两行","0","0","400","260",500,0,1,"SimHei",1]</d></i>';
  const files = {
    [`${base}/meta.json`]: JSON.stringify({ item_id: 'bili-' + SID, source: 'bilibili', source_id: SID, current_version: 1 }),
    [`${base}/raw/v0001/manifest.json`]: JSON.stringify({ media: [{ role: 'danmaku', file: 'raw/v0001/assets/danmaku.xml', download_status: 'ok', sha256: 'x' }] }),
    [`${base}/raw/v0001/assets/danmaku.xml`]: xml,
    [`${base}/notes.json`]: JSON.stringify({ starred: false, annotations: [
      { id: 'a1', ts: '2026-10-30T01:00:00Z', text: '普通批注：不带时间，不当弹幕' },
      { id: 'a2', ts: '2026-10-30T02:00:00Z', text: '之前记的一条（带时间）', video_t: 0.3 },
    ] }),
  };
  await page.setContent(`<!doctype html><html><head><style>body{margin:0;font-family:"Microsoft YaHei",sans-serif}${rd('link_brain/assets/link-brain.css')}${rd('obsidian-plugins/link-brain-actions/note.css')}</style></head><body class="theme-light">
    <div class="markdown-reading-view"><main class="markdown-preview-view xhs-note" style="height:760px;overflow:auto;padding:16px">
      <div class="lb-note" data-lb-item="bili-${SID}"><div class="lb-side"><section class="lb-media"><div class="lb-carousel"><figure class="lb-slide"><video muted loop src="${mp4}" style="width:560px;height:315px;background:#234"></video></figure></div></section></div>
      <div class="lb-main"><div class="lb-scroll"><p>合成的 B 站视频笔记正文。</p></div></div></div>
      <div class="block-language-dataviewjs" id="dvc"></div>
    </main></div></body></html>`);
  await page.evaluate(async ({ nav, dm, annot, files }) => {
    Element.prototype.createEl = function (tag, o = {}) { const e = document.createElement(tag); if (o.cls) e.className = o.cls; if (o.text != null) e.textContent = o.text; if (o.attr) for (const [k, v] of Object.entries(o.attr)) e.setAttribute(k, v); this.append(e); return e; };
    Element.prototype.setText = function (s) { this.textContent = s; };
    Element.prototype.empty = function () { this.textContent = ''; };
    Element.prototype.addClass = function (c) { this.classList.add(c); };
    Element.prototype.removeClass = function (c) { this.classList.remove(c); };
    Element.prototype.createDiv = function (o = {}) { return this.createEl('div', o); };
    window.Notice = class { constructor(m) { console.log('[notice]', m); } };
    const disk = new Map(Object.entries(files)); window.disk = disk;
    const adapter = { async exists(p) { return disk.has(p); }, async read(p) { if (!disk.has(p)) throw new Error('ENOENT ' + p); return disk.get(p); }, async write(p, s) { disk.set(p, s); }, getResourcePath: p => p };
    const bus = new Map();
    const workspace = { on(n, f) { const r = { n, f }; (bus.get(n) || bus.set(n, new Set()).get(n)).add(r); return r; }, offref(r) { bus.get(r.n)?.delete(r); }, trigger(n, ...a) { for (const r of [...(bus.get(n) || [])]) r.f(...a); }, getLeavesOfType: () => [] };
    const app = { vault: { adapter }, workspace, plugins: { plugins: {} } };
    const dmMod = { exports: {} }; new Function('module', 'exports', 'require', dm)(dmMod, dmMod.exports, () => ({}));
    window.DM = dmMod.exports;
    const host = { app, settings: { media: { loop: true } }, async saveSettings() {}, markSettingDirty() {}, register() {}, registerDomEvent(el, n, f, o) { el.addEventListener(n, f, o); }, registerEvent() {}, lbPath: p => p };
    const m = { exports: {} }; new Function('require', 'module', nav)(p => (p === './danmaku.js' ? dmMod.exports : {}), m);
    window.plugin = m.exports({}, host); plugin.attach();
    const dv = { container: document.getElementById('dvc'), component: { registerEvent() {} }, current: () => ({ file: { folder: '' } }) };
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    await new AsyncFunction('dv', 'app', 'itemId', 'notePath', annot)(dv, app, 'bili-' + 'BV1ui000001', '_archive/bilibili/BV1ui000001/notes.json');
  }, { nav: rd('obsidian-plugins/link-brain-actions/media-nav.js'), dm: rd('obsidian-plugins/link-brain-actions/danmaku.js'), annot: rd('link_brain/assets/annotate-view.js'), files });
  await page.waitForFunction(() => document.querySelector('.lb-media').__lbDanmaku && document.querySelector('video').readyState >= 2);
  await page.waitForTimeout(200);
  assert.ok(await page.evaluate(() => !!document.querySelector('.lb-side .lba-annot')), '批注框挪进左栏（10-31 起一律带当前时间，不再有「记在当前时间」的勾）');
  assert.equal(await page.locator('.lb-dm-send').count(), 0, '没有另一个发弹幕框');
  assert.deepEqual(await page.locator('.lba-vt').allTextContents(), ['▶ 0:00'], '原有带时间的批注前面有时间标');

  // ① 视频播到 0.5 秒暂停 → 在批注框里写一条（勾着）→ 落定（Ctrl+Enter）
  await page.evaluate(async () => { const v = document.querySelector('video'); v.currentTime = 0.5; await v.play(); await new Promise(r => setTimeout(r, 30)); v.pause(); v.currentTime = 0.5; });
  await page.waitForTimeout(150);
  await page.locator('.lba-annot-input').first().click();
  await page.keyboard.type('这里的转场好看');
  await page.keyboard.press('Control+Enter');
  await page.waitForTimeout(200);
  const saved = await page.evaluate(() => JSON.parse(disk.get('_archive/bilibili/BV1ui000001/notes.json')).annotations.find(a => a.text === '这里的转场好看'));
  assert.ok(saved && typeof saved.video_t === 'number' && saved.video_t >= 0.45 && saved.video_t <= 0.55, '存成带 video_t 的批注：' + JSON.stringify(saved));
  assert.equal(await page.locator('.lba-vt').count(), 2, '列表里两条带时间标');
  const mine = await page.evaluate(() => [...document.querySelectorAll('.lb-dm-item.is-mine')].map(e => e.textContent));
  assert.ok(mine.includes('这里的转场好看'), '画面上立刻飘出来（带细框）：' + JSON.stringify(mine));
  assert.ok(await page.evaluate(() => [...document.querySelectorAll('.lb-dm-item.is-adv')].some(e => e.textContent.includes('高级弹幕'))), '高级弹幕静态显示');
  await page.locator('.lb-note').screenshot({ path: path.join(QA, 'danmaku-annot-normal.png') });

  // 点时间标跳过去
  await page.evaluate(() => document.querySelector('video').pause());
  await page.locator('.lba-vt').first().click();
  assert.ok(await page.evaluate(() => Math.abs(document.querySelector('video').currentTime - 0.3) < 0.15 || !document.querySelector('video').paused), '点时间标跳过去播');

  // ② 1104 作者（参考 B 站播放器）：「弹幕」「弹幕设置」是工具行里两个电视形「弹」图标；画面上不再浮一个圆「弹」
  assert.equal(await page.locator('.lb-dm-ovbtn').count(), 0, '画面上不再浮「弹」');
  await page.locator('.lb-media').hover();
  await page.waitForTimeout(150);
  await page.locator('.lb-media').screenshot({ path: path.join(QA, 'danmaku-icons-normal.png') });
  // 全屏：暂停时工具行在，两个图标都看得见；点开关 = 关弹幕、图标带 ⊘，不暂停
  await page.evaluate(() => document.querySelector('.lb-media').lbToggleFullscreen());
  await page.waitForFunction(() => document.fullscreenElement && document.fullscreenElement.classList.contains('lb-media'));
  await page.evaluate(async () => { const v = document.querySelector('video'); v.pause(); v.currentTime = 0.5; });
  await page.mouse.move(600, 300); await page.mouse.move(620, 320);
  await page.waitForTimeout(350);
  const g = await page.evaluate(() => [...document.querySelectorAll('.lb-dm-icobtn')].map(b => { const r = b.getBoundingClientRect(), i = b.querySelector('.lb-dm-ico').getBoundingClientRect();
    return { w: Math.round(r.width), icoW: Math.round(i.width), icoH: Math.round(i.height), vis: getComputedStyle(b).visibility, op: getComputedStyle(b.closest('.lb-media-tools')).opacity }; }));
  assert.equal(g.length, 2, '两个图标：' + JSON.stringify(g));
  assert.ok(g.every(x => x.icoW >= 16 && x.icoH >= 12 && x.vis === 'visible'), '全屏里两个图标都画出来了：' + JSON.stringify(g));
  await page.screenshot({ path: path.join(QA, 'danmaku-fullscreen-on.png') });
  await page.locator('.lb-dm-toggle').click();
  await page.waitForTimeout(250);
  const off = await page.evaluate(() => ({ hidden: document.querySelector('.lb-dm-layer').hidden, pressed: document.querySelector('.lb-dm-toggle').getAttribute('aria-pressed'), paused: document.querySelector('video').paused }));
  assert.deepEqual(off, { hidden: true, pressed: 'false', paused: true }, '点图标关弹幕、不把这一下当成点画面');
  await page.screenshot({ path: path.join(QA, 'danmaku-fullscreen-off.png') });
  await page.locator('.lb-dm-toggle').click();
  await page.evaluate(() => document.exitFullscreen());
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('PASS danmaku+annot (Edge): 批注框写的批注带 video_t（一律带当前时间）、列表有时间标、画面立刻飘（细框）；高级弹幕静态显示；「弹幕」「弹幕设置」是工具行里的电视形「弹」图标（全屏也在），点开关不暂停。截图：' + QA);
})().catch(e => { console.error(e); process.exit(1); });

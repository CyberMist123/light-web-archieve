// 1031 她：B 站视频弹幕（obsidian-plugins/link-brain-actions/danmaku.js，media-nav 给正文视频装工具行时挂上）。
// ①解析 B 站 XML（模式 / 颜色 / 字号 / 实体、7 高级弹幕不画、按时间排好）；②引擎：一千多条只建屏幕上的节点（回收复用）、同一行不撞车、
// 拖进度条按新时间重排、屏蔽 / 显示区域 / 速度；③控制器：只认 B 站来源（小红书视频不出控件）、工具行「弹幕」「弹幕设置」、D 键开关
// （焦点在视频上；全屏里焦点在哪都算；输入框里不算）、设置存 settings.media.danmaku（markSettingDirty('media') + saveSettings，没存上拨回 + 说原因）、
// 所有视频共用；④本地发弹幕：立刻上画面、带 is-mine、存 _archive/bilibili/<BV>/danmaku-mine.json（原子写、追加、不留 .tmp / .bak），
// 写失败撤回并把字放回输入框，下次打开和原弹幕一起播；⑤插件卸载拆干净。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path');
const { ROOT, makeDom, makeVault } = require('./_fakedom.cjs');

const DM_PATH = path.join(ROOT, 'obsidian-plugins/link-brain-actions/danmaku.js');
const DM = require(DM_PATH);
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

// ── 合成数据 ──
function xmlOf(rows) {
  return '<?xml version="1.0" encoding="UTF-8"?><i><chatserver>chat.bilibili.com</chatserver><maxlimit>3000</maxlimit>'
    + rows.map(([t, mode, size, color, text]) => `<d p="${t},${mode},${size},${color},1729911729,0,abc,1701,10">${text}</d>`).join('') + '</i>';
}
function bigXml(n, dur = 120) {
  const rows = [];
  let seed = 7; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  for (let i = 0; i < n; i++) { const m = rnd() < 0.8 ? 1 : rnd() < 0.5 ? 4 : 5; rows.push([(rnd() * dur).toFixed(3), m, 25, 16777215, '弹幕' + i + (i % 3 ? '哈哈哈哈' : '')]); }
  return xmlOf(rows);
}
function archiveFiles(sid, { xml = null, danmakuStatus = 'ok', mine = null } = {}) {
  const base = `_archive/bilibili/${sid}`;
  const files = {
    [`${base}/meta.json`]: JSON.stringify({ item_id: 'bili-' + sid, source: 'bilibili', source_id: sid, current_version: 2 }),
    [`${base}/raw/v0002/manifest.json`]: JSON.stringify({ media: [
      { role: 'video', file: 'raw/v0002/assets/video.mp4', download_status: 'ok' },
      { role: 'danmaku', file: 'raw/v0002/assets/danmaku.xml', download_status: danmakuStatus, sha256: 'abc' + sid, count: 3 },
    ] }),
  };
  if (xml != null) files[`${base}/raw/v0002/assets/danmaku.xml`] = xml;
  if (mine) files[`${base}/danmaku-mine.json`] = JSON.stringify(mine);
  return files;
}

function makeEnv(files = {}) {
  const dom = makeDom(); const D = dom.document;
  D.fullscreenElement = null;
  const V = makeVault(files);
  const wl = {};
  const window = { innerHeight: 800, innerWidth: 1200, getSelection: () => null, addEventListener(t, fn) { (wl[t] = wl[t] || []).push(fn); }, removeEventListener(t, fn) { wl[t] = (wl[t] || []).filter(f => f !== fn); } };
  class MO { observe() {} disconnect() {} }
  class RO { observe() {} disconnect() {} }
  return { dom, D, V, window, MO, RO };
}
function loadNav(E, { settings = { media: { loop: true, playlistOrder: 'newest' } }, saveFail = null } = {}) {
  const src = fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/media-nav.js'), 'utf8');
  const m = { exports: {} };
  const req = p => (p === './danmaku.js' ? DM : {});
  new Function('require', 'module', 'exports', 'document', 'window', 'Element', 'MutationObserver', 'ResizeObserver', 'innerWidth', 'innerHeight', 'Event', src)(req, m, m.exports, E.D, E.window, E.dom.El, E.MO, E.RO, 1200, 800, E.dom.Event);
  const host = {
    app: { plugins: { enabledPlugins: new Set(), manifests: {} }, workspace: { activeLeaf: null, getLeavesOfType: () => [] }, metadataCache: { getFileCache: () => null }, vault: E.V.vault },
    settings, saves: 0, dirty: [], notes: [],
    async saveSettings() { this.saves++; if (saveFail && saveFail()) throw new Error('磁盘满了'); },
    markSettingDirty(...k) { this.dirty.push(...k); },
    notify(msg, o) { this.notes.push([msg, o && o.kind]); },
    lbPath: p => p,
    cleanups: [], register(fn) { this.cleanups.push(fn); }, registerDomEvent(el, t, fn) { el.addEventListener(t, fn); }, registerEvent() {},
  };
  const nav = m.exports({ Notice: class {} }, host);
  return { nav, host };
}
function videoNote(E, item, src = '') {
  const preview = E.D.body.createEl('div', { cls: 'markdown-reading-view' }).createEl('div', { cls: 'markdown-preview-view xhs-note' });
  const note = preview.createEl('div', { cls: 'lb-note' }); if (item) note.dataset.lbItem = item;
  const side = note.createEl('div', { cls: 'lb-side' });
  const media = side.createEl('section', { cls: 'lb-media' });
  const car = media.createEl('div', { cls: 'lb-carousel' });
  const slide = car.createEl('figure', { cls: 'lb-slide' });
  const video = slide.createEl('video');
  if (src) video.setAttribute('src', src);
  video.paused = true; video.currentTime = 0; video.playbackRate = 1;
  slide._rect = { width: 640, height: 360 };
  note.createEl('div', { cls: 'lb-main' }).createEl('div', { cls: 'lb-scroll' });
  return { note, side, media, car, slide, video };
}
const settle = async () => { for (let i = 0; i < 6; i++) await tick(1); };
const key = (E, target, k, extra = {}) => { const e = E.dom.event('keydown', { key: k, bubbles: true, ...extra }); target.dispatchEvent(e); return e; };

(async () => {
  // ── ① 解析 ──
  {
    const items = DM.parseXml(xmlOf([
      [9.5, 1, 25, 16777215, '滚动'], [2.25, 5, 36, 15138834, '顶部 &amp; &lt;b&gt;'], [3, 4, 18, 41194, '底部&#x1F600;'],
      [4, 7, 25, 1, '["高级弹幕"]'], [5, 8, 25, 1, 'code'], [6, 1, 25, 1, '   '], ['x', 1, 25, 1, '坏时间'], [7, 6, 25, 255, '逆向当滚动'],
    ]));
    assert.deepEqual(items.map(d => d.text), ['顶部 & <b>', '底部😀', '逆向当滚动', '滚动'], '按时间排好；7 / 8 / 空文字 / 坏时间不要');
    assert.deepEqual(items.map(d => d.mode), ['top', 'bottom', 'scroll', 'scroll']);
    assert.equal(items[0].size, 36); assert.equal(items[0].color, 15138834); assert.equal(items[1].size, 18);
    const real = path.join(ROOT, 'tests/fixtures/bilibili_danmaku_sample.xml');
    if (fs.existsSync(real)) assert.ok(DM.parseXml(fs.readFileSync(real, 'utf8')).length > 0);
  }
  // ── 设置：缺的补默认、越界夹住、不认识的就近取档 ──
  {
    assert.deepEqual(DM.normalizeSettings(undefined), { on: true, opacity: 0.9, scale: 1, area: 0.5, speed: 1, block: { scroll: false, top: false, bottom: false } });
    const s = DM.normalizeSettings({ on: false, opacity: 5, scale: 0.1, area: 0.3, speed: 9, block: { top: 1 } });
    assert.deepEqual(s, { on: false, opacity: 1, scale: 0.5, area: 0.25, speed: 1.7, block: { scroll: false, top: true, bottom: false } });
    assert.equal(DM.sourceIdOf('bili-BV19e4y1r7q6', ''), 'BV19e4y1r7q6');
    assert.equal(DM.sourceIdOf('bili-BV1x_p2', ''), 'BV1x_p2');
    assert.equal(DM.sourceIdOf('xhs-abc', 'app://x/_archive/bilibili/BV1/raw/v0001/assets/video.mp4'), '', '有 item_id 而且不是 bili-：不认');
    assert.equal(DM.sourceIdOf('', 'app://local/D%3A/v/_archive/bilibili/BV1abc/raw/v0001/assets/video.mp4?1'), 'BV1abc', '没有 item_id：看视频地址');
    assert.equal(DM.sourceIdOf('bili-../../etc', ''), '', '不许路径穿越');
  }

  // ── ② 引擎：1500 条、播 2 分钟，节点只建屏幕上的、同行不撞车 ──
  {
    const { document: D } = makeDom();
    const layer = D.body.createEl('div', { cls: 'lb-dm-layer' });
    const eng = new DM.Engine(layer);
    eng.resize(800, 450);
    eng.setItems(DM.parseXml(bigXml(1500, 120)));
    assert.equal(eng.items.length, 1500);
    let maxLive = 0, overlaps = 0;
    for (let f = 0; f <= 120 * 30; f++) {
      const t = f / 30;
      eng.frame(t);
      maxLive = Math.max(maxLive, eng.live.length);
      assert.equal(layer.children.length, eng.live.length, '层里只有屏幕上的那些节点');
      if (f % 15) continue;
      const byLane = new Map();
      for (const r of eng.live) if (r.mode === 'scroll') { const x = eng.W - (t - r.start) * r.v; (byLane.get(r.lane) || byLane.set(r.lane, []).get(r.lane)).push([x, x + r.w]); }
      for (const segs of byLane.values()) { segs.sort((a, b) => a[0] - b[0]); for (let i = 1; i < segs.length; i++) if (segs[i][0] < segs[i - 1][1] - 0.5) overlaps++; }
    }
    assert.ok(maxLive > 10 && maxLive <= DM.MAX_LIVE, `同屏条数有上限：${maxLive}`);
    assert.equal(overlaps, 0, '同一行的滚动弹幕不互相压');
    assert.ok(eng.stats.created <= maxLive + 5, `节点回收复用：建了 ${eng.stats.created} 个，同屏最多 ${maxLive}`);
    // 拖进度条：一下跳到 30 秒 → 按新时间重排，屏幕上的都是此刻本该在的
    eng.frame(5); eng.frame(30);
    assert.ok(eng.live.length > 0);
    for (const r of eng.live) assert.ok(r.d.time <= 30 && 30 - r.d.time < (r.mode === 'scroll' ? eng.dur : DM.FIX_SEC), '重排后只剩此刻该在画面里的');
    assert.equal(eng.next, DM.upperBound(eng.items, 30), '指针停在 30 秒之后的第一条');
    const xs = eng.live.filter(r => r.mode === 'scroll').map(r => r.el.style.transform);
    eng.frame(30.5);
    const moved = eng.live.filter(r => r.mode === 'scroll').map(r => r.el.style.transform);
    assert.notDeepEqual(xs, moved, '时间往前走，滚动的往左挪（只改 transform）');
    assert.ok(/^translate3d\(/.test(moved[0]));
    // 屏蔽滚动 → 只剩顶部 / 底部；显示区域 1/4 屏 → 行数少一半
    const lanesHalf = eng.nLanes;
    eng.setSettings({ block: { scroll: true } });
    assert.ok(eng.live.length > 0 && eng.live.every(r => r.mode !== 'scroll'), '屏蔽滚动');
    eng.setSettings({ area: 0.25 });
    assert.ok(eng.nLanes < lanesHalf, '1/4 屏行数更少');
    for (const r of eng.live) assert.ok(r.mode === 'bottom' ? r.y >= eng.H - eng.nLanes * eng.laneH - 0.5 : r.y < eng.nLanes * eng.laneH, '都在显示区域里');
    eng.setSettings({ area: 1, block: {}, speed: 1.7 });
    assert.ok(Math.abs(eng.dur - DM.SCROLL_SEC / 1.7) < 1e-9, '速度快 = 一条走完用时短');
    // 她发的：挤也要挤上去，一出来整条就在画面里（暂停时也看得见）
    const mine = { time: 30.5, mode: 'scroll', size: 25, color: 0xffffff, text: '我的', mine: true };
    const rec = eng.insertNow(mine, 30.5);
    assert.ok(rec && rec.el.classList.contains('is-mine'));
    const x = eng.W - (30.5 - rec.start) * rec.v;
    assert.ok(x + rec.w <= eng.W && x > eng.W - rec.w - 30, `整条在右边缘里：x=${x}`);
    const n = eng.next; eng.frame(30.6); assert.equal(eng.live.filter(r => r.d === mine).length, 1, '指针不会再放一次');
    assert.ok(eng.next >= n);
    eng.removeItem(mine); assert.ok(!eng.items.includes(mine) && !eng.live.some(r => r.d === mine), '撤回');
  }

  // ── ③ 控制器：B 站视频挂上、小红书视频不挂 ──
  const SID = 'BV1test0001';
  {
    const E = makeEnv(archiveFiles(SID, { xml: xmlOf([[0.5, 1, 25, 16777215, '第一条'], [1, 5, 25, 255, '顶'], [40, 1, 25, 16777215, '后面']]) }));
    const A = videoNote(E, 'bili-' + SID), B = videoNote(E, 'xhs-v1');
    const { nav, host } = loadNav(E);
    nav.attach();
    await settle();
    const c = A.media.__lbDanmaku;
    assert.ok(c, 'B 站视频挂上弹幕');
    assert.ok(!B.media.__lbDanmaku && !B.media.querySelector('.lb-dm-toggle') && !E.D.body.querySelectorAll('.lb-dm-send').some(r => B.side.contains(r)), '小红书视频不出弹幕控件');
    const bar = A.media.querySelector('.lb-media-tools');
    assert.deepEqual(bar.children.map(b => b.textContent).slice(-2), ['弹幕', '弹幕设置'], '工具行末尾「弹幕」「弹幕设置」');
    assert.ok(A.slide.querySelector('.lb-dm-layer'), '弹幕层叠在视频那一格里（.lb-media 里：全屏照样在）');
    assert.equal(A.media.nextElementSibling && A.media.nextElementSibling.className, 'lb-dm-send', '发弹幕那一条在视频下面（不挡画面）');
    assert.equal(c.origState, 'ok'); assert.equal(c.engine.items.length, 3);
    assert.equal(c.toggleBtn.getAttribute('aria-pressed'), 'true', '默认开');
    // 暂停在 0.6 秒拖到这里：画面上是这一刻该有的
    A.video.currentTime = 0.6; A.video.dispatchEvent({ type: 'seeked' });
    assert.deepEqual(c.engine.live.map(r => r.d.text), ['第一条']);
    A.video.currentTime = 41; A.video.dispatchEvent({ type: 'seeked' });
    assert.deepEqual(c.engine.live.map(r => r.d.text), ['后面'], '拖进度条按新时间重排');
    // 倍速：currentTime 两次更新之间按倍速往前推
    A.video.playbackRate = 2; A.video.paused = false;
    c.engine.t = 41;
    A.video.dispatchEvent({ type: 'play' });
    await tick(60);
    assert.ok(c.engine.t > 41.05 && c.engine.t <= 41.25 + 1e-9, `倍速 2 时画面时间按 2 倍推（最多推 0.25 秒）：${c.engine.t}`);
    A.video.paused = true; A.video.dispatchEvent({ type: 'pause' });
    const frozen = c.engine.t; await tick(50);
    assert.equal(c.engine.t, frozen, '暂停就停');

    // 「弹幕」按钮：关 → 存 settings.media.danmaku、登记 media、层和发送栏收起；循环设置还在
    c.toggleBtn.click(); await settle();
    assert.equal(host.settings.media.danmaku.on, false); assert.equal(host.settings.media.loop, true, '同组的循环设置不丢');
    assert.ok(host.saves >= 1 && host.dirty.includes('media'));
    assert.ok(c.layer.hidden && c.sendRow.hidden, '关了：弹幕层藏起来、发送栏收起');
    assert.equal(c.engine.live.length, 0);
    // D：焦点在视频上按 → 开；输入框里按不算；别处按不算；全屏时焦点在哪都算
    key(E, A.video, 'd'); await settle();
    assert.equal(host.settings.media.danmaku.on, true, '焦点在视频上按 D 开');
    assert.ok(!c.layer.hidden && A.slide.querySelector('.lb-dm-flash.is-on'), '画面上冒一句「弹幕：开」');
    assert.match(A.slide.querySelector('.lb-dm-flash').textContent, /弹幕：开/);
    key(E, c.input, 'd'); await settle();
    assert.equal(host.settings.media.danmaku.on, true, '输入框里打 d 不切');
    key(E, E.D.body, 'd'); await settle();
    assert.equal(host.settings.media.danmaku.on, true, '焦点不在视频上不切');
    E.D.fullscreenElement = A.media;
    key(E, E.D.body, 'D'); await settle();
    assert.equal(host.settings.media.danmaku.on, false, '全屏时焦点在哪都算');
    E.D.fullscreenElement = null;
    key(E, A.video, 'd'); await settle();
    assert.equal(host.settings.media.danmaku.on, true);

    // 设置弹层：显示区域 / 速度 / 屏蔽 / 透明度
    c.menuBtn.click();
    assert.equal(c.panel.hidden, false, '「弹幕设置」打开弹层');
    assert.match(c.panel.textContent, /按 D 开关弹幕/, '可见文字里说明了 D 键');
    assert.match(c.panel.textContent, /不会发到 B 站/);
    assert.match(c.panel.textContent, /原弹幕 3 条 · 我发的 0 条/);
    const opt = text => c.panel.querySelectorAll('button').find(b => b.textContent === text);
    for (const t of ['1/4 屏', '半屏', '全屏', '慢', '标准', '快', '很快', '滚动', '顶部', '底部', '收起']) assert.ok(opt(t), '弹层里有「' + t + '」');
    opt('全屏').click(); await settle();
    assert.equal(host.settings.media.danmaku.area, 1); assert.equal(opt('全屏').getAttribute('aria-pressed'), 'true');
    opt('快').click(); await settle(); assert.equal(host.settings.media.danmaku.speed, 1.35);
    opt('顶部').click(); await settle(); assert.deepEqual(host.settings.media.danmaku.block, { scroll: false, top: true, bottom: false });
    const ranges = c.panel.querySelectorAll('input');
    ranges[0].value = '40'; ranges[0].dispatchEvent({ type: 'input' });
    assert.equal(c.layer.style.opacity, '0.4', '拖透明度立刻生效');
    const savesBefore = host.saves;
    ranges[0].dispatchEvent({ type: 'change' }); await settle();
    assert.equal(host.saves, savesBefore + 1, '松手才存');
    ranges[1].value = '150'; ranges[1].dispatchEvent({ type: 'change' }); await settle();
    assert.equal(host.settings.media.danmaku.scale, 1.5);
    opt('收起').click(); assert.equal(c.panel.hidden, true);

    // ④ 发弹幕：立刻上画面（带细框）、存 danmaku-mine.json
    A.video.currentTime = 12.3456;
    c.input.value = '  第一次\n发弹幕 ';
    c.media.nextElementSibling.querySelector('.lb-dm-send-btn').click(); await settle();
    const mineRec = c.engine.live.find(r => r.d.mine);
    assert.ok(mineRec && mineRec.el.classList.contains('is-mine'), '立刻飘出来、带 is-mine 细框');
    assert.equal(mineRec.d.text, '第一次 发弹幕');
    assert.equal(c.input.value, '', '发完清空');
    const file = `_archive/bilibili/${SID}/danmaku-mine.json`;
    const doc1 = JSON.parse(E.V.get(file));
    assert.equal(doc1.schema_version, 1); assert.equal(doc1.item_id, 'bili-' + SID); assert.equal(doc1.source_id, SID);
    assert.equal(doc1.items.length, 1);
    const it = doc1.items[0];
    assert.deepEqual(Object.keys(it).sort(), ['color', 'created_at', 'id', 'mode', 'size', 'text', 'time']);
    assert.equal(it.time, 12.346); assert.equal(it.mode, 1); assert.equal(it.color, 16777215); assert.equal(it.size, 25);
    assert.match(it.created_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/, '本地时区带偏移');
    assert.ok(E.V.get(file).endsWith('\n') && E.V.get(file).includes('\n  "items"'), '缩进 2、末尾换行');
    // Enter 发第二条：追加，不留临时文件
    A.video.currentTime = 20;
    c.input.value = '第二条'; key(E, c.input, 'Enter'); await settle();
    assert.equal(JSON.parse(E.V.get(file)).items.length, 2, '追加');
    assert.ok(![...E.V.disk.keys()].some(k => /danmaku-mine\.json\.(tmp|bak)$/.test(k)), '不留 .tmp / .bak');
    assert.match(c.panel.textContent, /我发的 2 条/);
    // 写盘失败：撤回、字放回输入框、说原因
    const w0 = E.V.vault.adapter.write;
    E.V.vault.adapter.write = async () => { throw new Error('只读'); };
    c.input.value = '写不进去'; key(E, c.input, 'Enter'); await settle();
    E.V.vault.adapter.write = w0;
    assert.equal(c.input.value, '写不进去', '内容还在');
    assert.ok(!c.engine.items.some(d => d.text === '写不进去'), '撤回');
    assert.ok(host.notes.some(([m, k]) => /^没保存上，内容还在，可重试：只读/.test(m) && k === 'error'));
    assert.equal(JSON.parse(E.V.get(file)).items.length, 2);
    // 空的不发
    c.input.value = '   '; key(E, c.input, 'Enter'); await settle();
    assert.equal(JSON.parse(E.V.get(file)).items.length, 2);

    // 设置存不上：拨回原来的样子并说原因
    const E2 = makeEnv(archiveFiles(SID, { xml: xmlOf([]) }));
    const N2 = videoNote(E2, 'bili-' + SID);
    const L2 = loadNav(E2, { saveFail: () => true }); L2.nav.attach(); await settle();
    const c2 = N2.media.__lbDanmaku;
    c2.toggleBtn.click(); await settle();
    assert.equal(DM.normalizeSettings(L2.host.settings.media.danmaku).on, true, '没存上：拨回开');
    assert.ok(!c2.layer.hidden && c2.toggleBtn.getAttribute('aria-pressed') === 'true');
    assert.ok(L2.host.notes.some(([m]) => m === '没保存上，开关已拨回原来的位置：磁盘满了'));
    L2.host.cleanups.forEach(f => f());

    // 重新打开：原弹幕 + 我发的一起播
    A.note.remove();
    const A2 = videoNote(E, 'bili-' + SID);
    nav.enhance(A2.car); await settle();
    const c3 = A2.media.__lbDanmaku;
    assert.ok(c3 && c3 !== c);
    assert.equal(c3.engine.items.length, 5, '3 条原弹幕 + 2 条我发的');
    assert.deepEqual(c3.engine.items.filter(d => d.mine).map(d => d.text), ['第一次 发弹幕', '第二条']);
    // 所有视频共用一份设置：一条视频上关掉，另一条也关
    const Bv = videoNote(E, 'bili-BV1other02');
    for (const [k, v] of Object.entries(archiveFiles('BV1other02', { danmakuStatus: 'unavailable' }))) E.V.disk.set(k, v);
    nav.enhance(Bv.car); await settle();
    const c4 = Bv.media.__lbDanmaku;
    assert.ok(c4, '原弹幕没有（unavailable）照样能发自己的');
    c4.menuBtn.click(); assert.match(c4.panel.textContent, /这条视频没存下原弹幕/);
    c4.toggleBtn.click(); await settle();
    assert.ok(c3.layer.hidden && c3.toggleBtn.getAttribute('aria-pressed') === 'false', '另一条视频跟着关');
    // 被摘掉的视频：设置一变就拆掉自己
    Bv.note.remove(); c3.toggleBtn.click(); await settle();
    assert.ok(!DM.controllers.has(c4), '不在文档里的拆掉');
    // ⑤ 插件卸载：拆干净
    host.cleanups.forEach(f => f());
    assert.equal(DM.controllers.size, 0);
    assert.equal(E.D.body.querySelectorAll('.lb-dm-layer').length + E.D.body.querySelectorAll('.lb-dm-send').length + E.D.body.querySelectorAll('.lb-dm-panel').length, 0);
    assert.equal((E.D.listeners.keydown || []).length, 1, 'D 键监听摘掉（剩下那个是 media-nav 自己的 ←/→，由插件 registerDomEvent 管）');
  }
  // 弹幕模块加载不上（旧测试那样 require 返回 {}）：视频工具行照常
  {
    const E = makeEnv(archiveFiles(SID, { xml: xmlOf([]) }));
    const A = videoNote(E, 'bili-' + SID);
    const src = fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/media-nav.js'), 'utf8');
    const m = { exports: {} };
    new Function('require', 'module', 'exports', 'document', 'window', 'Element', 'MutationObserver', 'ResizeObserver', 'innerWidth', 'innerHeight', 'Event', src)(() => ({}), m, m.exports, E.D, E.window, E.dom.El, E.MO, E.RO, 1200, 800, E.dom.Event);
    const nav = m.exports({}, { app: { plugins: { enabledPlugins: new Set(), manifests: {} }, workspace: { getLeavesOfType: () => [] }, vault: E.V.vault }, settings: {}, register() {}, registerDomEvent(el, t, fn) { el.addEventListener(t, fn); }, registerEvent() {} });
    nav.attach(); await settle();
    assert.ok(A.media.querySelector('.lb-video-full') && !A.media.querySelector('.lb-dm-toggle'));
  }
  console.log('PASS danmaku 1031: XML 解析、引擎只建屏幕上的节点且同行不撞车、拖进度条重排、倍速 / 暂停、屏蔽 / 区域 / 速度；只认 B 站视频；弹幕 / 弹幕设置 / D 键；设置共用且存不上拨回；本地发弹幕原子写 danmaku-mine.json、失败撤回、重开一起播；卸载拆干净');
})().catch(e => { console.error(e); process.exit(1); });

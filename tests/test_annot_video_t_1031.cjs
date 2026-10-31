// 1031 作者「弹幕直接复用批注」：B 站视频笔记里，批注框下面一个「记在当前时间」的勾——勾着写的批注带 video_t（秒），
// 就是用户的弹幕（插件 danmaku.js 读它飘）。这里直接跑生产那份 assets/annotate-view.js（和 bootstrap 一样用 AsyncFunction 起），查：
// ①时间取「开始写这一条那一刻」的播放位置（写的工夫里视频接着走也不变）、3 位小数；视频还没开始播不带；勾掉不带；勾的状态不让输入框失焦；
// ②写盘走原来那套（persist：读盘合并、墓碑），改字保留 video_t；③列表里带时间的前面一个「▶ 0:12」，点了跳到那一秒并播放；
// ④每次存完发 link-brain:annotations（itemId, {annotations, deleted}），danmaku.annotationItems 认得出（删掉的不算）；⑤小红书笔记什么都不加。
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

const code = fs.readFileSync(path.join(__dirname, '..', 'link_brain', 'assets', 'annotate-view.js'), 'utf8');
const DM = require(path.join(__dirname, '..', 'obsidian-plugins', 'link-brain-actions', 'danmaku.js'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

// 这篇的视频：被 findVideo() 从视图里找到
const video = { currentTime: 0, paused: true, plays: 0, play() { this.plays++; this.paused = false; return Promise.resolve(); }, scrollIntoView() {} };
// 视图：isConnected=false 让「挪进左栏」那段直接收手（那段另有 test_annot_side 守着）
const view = { dataset: {}, isConnected: false, querySelector(sel) { return /video/.test(sel) ? video : null; } };
globalThis.MutationObserver = class { observe() {} disconnect() {} };

function el(tag, cls = '', text = '') {
  const e = {
    tag, cls, text, children: [], style: {}, value: '', placeholder: '', disabled: false, parent: null, checked: false,
    classList: { add(c) { e.cls += ' ' + c; }, toggle() {} },
    createEl(t, o = {}) { const c = el(t, o.cls || '', o.text || ''); c.attr = o.attr || {}; c.parent = e; e.children.push(c); return c; },
    setText(t) { e.text = t; }, empty() { e.children = []; }, closest() { return view; },
    all(sel) {
      const want = sel.replace(/^\./, ''); const out = [];
      (function walk(n) { for (const c of n.children) { if (c.cls.split(/\s+/).includes(want)) out.push(c); walk(c); } })(e);
      return out;
    },
    querySelector(sel) { return e.all(sel)[0] || null; }, querySelectorAll(sel) { return e.all(sel); },
    appendChild(c) { e.children.push(c); }, remove() {}, focus() {}, setSelectionRange() {},
  };
  return e;
}

const disk = new Map();
const adapter = {
  async exists(p) { return disk.has(p); },
  async read(p) { if (!disk.has(p)) throw new Error('ENOENT ' + p); return disk.get(p); },
  async write(p, s) { disk.set(p, s); },
};
globalThis.Notice = class { constructor() {} };
const events = [];
const app = { vault: { adapter }, plugins: { plugins: {} }, workspace: { on() { return {}; }, trigger(name, ...a) { events.push([name, ...a]); } } };

async function openView(itemId, notePath) {
  const dv = { container: el('div'), component: { registerEvent() {} } };
  await new AsyncFunction('dv', 'app', 'itemId', 'notePath', code)(dv, app, itemId, notePath);
  const ta = dv.container.querySelector('.lba-annot-input');
  return {
    dv, ta,
    async write(text) { ta.value = text; await ta.onblur(); },
    items() { return dv.container.all('.lba-annot-item'); },
  };
}

(async () => {
  const NOTE = '_archive/bilibili/BV1vt0001/notes.json';
  const onDisk = () => JSON.parse(disk.get(NOTE));
  const A = await openView('bili-BV1vt0001', NOTE);
  const row = A.dv.container.querySelector('.lba-vt-row');
  assert.ok(row, 'B 站视频笔记：批注框下面有「记在当前时间」');
  const box = row.children.find(c => c.tag === 'input');
  assert.equal(box.attr.type, 'checkbox'); assert.equal(box.checked, true, '默认勾着');
  const pd = { prevented: 0, target: row, preventDefault() { this.prevented++; } };
  row.onmousedown(pd); assert.equal(pd.prevented, 1, '按下这一行不让输入框失焦（失焦即定稿）');
  assert.ok(events.some(e => e[0] === 'link-brain:annotations' && e[1] === 'bili-BV1vt0001'), '打开时也发一次（弹幕层对齐）');

  // ① 视频还没开始播：不带时间
  await A.write('还没播时写的');
  assert.equal(onDisk().annotations[0].video_t, undefined, '没开始播不带 video_t');

  // 开始写的那一刻 12.3456 秒，写完时视频已经到 20 秒：记 12.346
  video.currentTime = 12.3456; video.paused = false;
  A.ta.value = '看'; A.ta.oninput();
  video.currentTime = 20;
  A.ta.value = '看到这里了'; A.ta.oninput();
  await A.ta.onblur();
  const timed = onDisk().annotations.find(a => a.text === '看到这里了');
  assert.equal(timed.video_t, 12.346, '取开始写那一刻、3 位小数');
  assert.ok(timed.id && timed.ts, '其余字段照旧');
  // 下一条重新取（上一条落定后清掉记下的时间）
  video.currentTime = 65.2;
  await A.write('第二条');
  assert.equal(onDisk().annotations.find(a => a.text === '第二条').video_t, 65.2);

  // ④ 存完发事件；danmaku 认得出
  const last = events.filter(e => e[0] === 'link-brain:annotations').pop();
  assert.equal(last[1], 'bili-BV1vt0001');
  assert.deepEqual(DM.annotationItems(last[2]).map(d => [d.time, d.text]), [[12.346, '看到这里了'], [65.2, '第二条']], '不带时间的不算弹幕');

  // ③ 列表：带时间的前面一个时间标，点了跳过去播
  const tags = A.dv.container.all('.lba-vt');
  assert.deepEqual(tags.map(t => t.text), ['▶ 0:12', '▶ 1:05']);
  video.paused = true; video.currentTime = 3;
  tags[1].onclick({ stopPropagation() {} });
  assert.equal(video.currentTime, 65.2); assert.equal(video.plays, 1, '跳过去接着播');

  // 勾掉：不带时间（勾的状态记住；node 里没有 localStorage 也不出错）
  box.checked = false; box.onchange();
  video.currentTime = 80; video.paused = false;
  await A.write('勾掉后写的');
  assert.equal(onDisk().annotations.find(a => a.text === '勾掉后写的').video_t, undefined);
  box.checked = true; box.onchange();

  // ② 改字保留 video_t
  const item = A.items().find(i => i.querySelector('.lba-annot-text').text === '第二条');
  await item.querySelector('.lba-edit').onclick({ stopPropagation() {} });
  const editor = A.items().find(i => i.querySelector('.lba-annot-text').text === '第二条').querySelector('.lba-edit-input');
  editor.value = '第二条（改）'; await editor.onblur();
  const edited = onDisk().annotations.find(a => a.text === '第二条（改）');
  assert.equal(edited.video_t, 65.2, '改字不丢时间'); assert.equal(edited.edited, true);
  // 删掉：墓碑 → 弹幕里也没了
  const delItem = A.items().find(i => i.querySelector('.lba-annot-text').text === '看到这里了');
  await delItem.querySelector('.lba-del').onclick({ stopPropagation() {} });
  const after = events.filter(e => e[0] === 'link-brain:annotations').pop()[2];
  assert.deepEqual(DM.annotationItems(after).map(d => d.text), ['第二条（改）'], '删掉的不再飘');
  // 别的端同时写了一条（合并照旧）：不吞
  const other = onDisk(); other.annotations.push({ id: 'aphone', ts: '2099-01-01T00:00:00Z', text: '手机写的', video_t: 3 }); disk.set(NOTE, JSON.stringify(other));
  video.currentTime = 90;
  await A.write('合并测试');
  assert.deepEqual(onDisk().annotations.map(a => a.text).slice(-2), ['合并测试', '手机写的'], '读盘合并照旧（按 ts 排）');
  assert.equal(onDisk().annotations.find(a => a.id === 'aphone').video_t, 3, '别端写的时间原样留着');

  // ⑤ 小红书笔记：没有勾、不带时间、不发事件
  const n0 = events.length;
  const X = await openView('xhs-n1', '_archive/xiaohongshu/n1/notes.json');
  assert.equal(X.dv.container.querySelector('.lba-vt-row'), null, '小红书笔记不出「记在当前时间」');
  await X.write('普通批注');
  assert.equal(JSON.parse(disk.get('_archive/xiaohongshu/n1/notes.json')).annotations[0].video_t, undefined);
  assert.equal(events.length, n0, '小红书笔记不发弹幕事件');
  console.log('PASS annot video_t 1031: B 站视频笔记「记在当前时间」（开始写那一刻、没开始播 / 勾掉不带、按下不失焦）；走原来的 persist（合并 / 墓碑 / 改字保留 video_t）；时间标点了跳过去播；存完发 link-brain:annotations、danmaku 认得出；小红书不变');
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });

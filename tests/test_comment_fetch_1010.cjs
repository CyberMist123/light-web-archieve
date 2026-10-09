// 1010 她报：笔记页「抓全部评论」提示说「底部状态栏能看进度」，其实没有进度。
//   main.js fetchAllComments：调 `comments <id> --progress --wait-lock-min 10`，把后端一行一个的进度事件记进 plugin.commentFetch、
//   发 'link-brain:comment-fetch'，底部状态栏「⟳ 抓全部评论 · 读评论区 0:05 / 下图 1/2」；做完留结果、过一会儿清掉。
//   note-actions.js paintFetch：画在这篇（data-lb-item）评论区最上面一行 + 细条；别的笔记不画；读评论区时来回扫、下图按真计数；
//   结果 ✓ / ⚠；commentFetch 清掉后收起；Obsidian 重画摘掉了就每秒补回来。全部假 child_process / 假 DOM，不起真进程。
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert/strict'), { EventEmitter } = require('events');
const { ROOT, makeDom, makeWorkspace } = require('./_fakedom.cjs');

const DIR = 'obsidian-plugins/link-brain-actions';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

// —— main.js（假 spawn：按脚本往 stdout 一行一行吐进度事件）——
const spawned = [];
let plan = null;
function fakeSpawn(exe, args, opts) {
  const c = new EventEmitter();
  c.pid = 4000 + spawned.length;
  c.stdout = new EventEmitter(); c.stderr = new EventEmitter();
  c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
  c.kill = () => {};
  spawned.push({ exe, args, child: c });
  c.feed = line => c.stdout.emit('data', Buffer.from(line + '\n'));
  c.finish = code => c.emit('close', code);
  if (plan) setTimeout(() => plan(c), 0);
  return c;
}
const notices = [];
const ctx = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, Buffer, console, URL,
  require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, TFile: class {},
    Notice: class { constructor(m) { notices.push(m); } setMessage() {} hide() {} } }
    : n === 'child_process' ? { spawn: fakeSpawn } : require(n) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(ROOT, DIR, 'main.js'), 'utf8'), ctx);
const Plugin = ctx.module.exports;

function loadNoteActions(dom) {
  const src = fs.readFileSync(path.join(ROOT, DIR, 'note-actions.js'), 'utf8');
  const m = { exports: {} };
  new Function('require', 'module', 'exports', 'document', 'window', src)(require, m, m.exports, dom.document, { getSelection: () => null });
  return m.exports;
}

(async () => {
  // ── 状态栏那一截（纯函数）──
  {
    const f = Plugin.commentFetchShort;
    const t0 = 1_000_000;
    assert.equal(f({ stage: 'start', stageAt: t0 }, t0), '准备');
    assert.equal(f({ stage: 'lock', stageAt: t0 }, t0 + 65000), '等号 1:05');
    assert.equal(f({ stage: 'read', stageAt: t0 }, t0 + 5000), '读评论区 0:05');
    assert.equal(f({ stage: 'media', done: 1, total: 2, stageAt: t0 }, t0), '下图 1/2');
    assert.equal(f({ stage: 'render', stageAt: t0 }, t0), '写进笔记');
    assert.equal(f({ stage: 'read', result: { ok: true } }, t0), '', '做完了：不再显示进度');
  }

  // ── fetchAllComments：参数、进度事件 → commentFetch / 状态栏 / 事件；结果；过一会儿清掉 ──
  {
    const p = new Plugin(); p.repoRoot = 'D:/repo';
    const events = [];
    const file = { path: 'Web/Xiaohongshu/做饭.md', basename: '做饭' };
    p.app = { vault: { adapter: { stat: async () => null, append: async () => {}, exists: async () => false, rename: async () => {}, remove: async () => {} } },
      workspace: { trigger: (name, st) => { if (name === 'link-brain:comment-fetch') events.push(st ? { stage: st.stage, result: st.result && { ...st.result } } : null); }, getActiveFile: () => file },
      metadataCache: { getFileCache: () => ({ frontmatter: { link_brain: { item_id: 'xhs-n1' }, title: '做饭' } }) } };
    p.lbPath = x => x;
    p.notify = (m, o) => { notices.push(m); return {}; };
    const status = { text: '', hidden: true, setText(t) { this.text = t; } };
    p.taskStatusEl = status;
    const seenStatus = [];
    const origChanged = p.taskChanged.bind(p);
    p.taskChanged = () => { origChanged(); seenStatus.push(status.text); };
    let clock = 5_000_000; p.now = () => clock;
    plan = async c => {
      c.feed(JSON.stringify({ type: 'progress', stage: 'start', text: '准备抓这篇的全部评论' }));
      c.feed(JSON.stringify({ type: 'progress', stage: 'read', text: '打开这篇，把评论一楼一楼展开读下来（热门笔记要几分钟到十几分钟，最多 25 分钟）' }));
      clock += 3000;
      c.feed(JSON.stringify({ type: 'progress', stage: 'merge', text: '评论读回来了：和存下的合并' }));
      c.feed(JSON.stringify({ type: 'progress', stage: 'media', text: '下载图片 / 语音 1/2', done: 1, total: 2, unit: '个' }));
      await tick(5);
      assert.equal(p.commentFetch.stage, 'media'); assert.equal(p.commentFetch.done, 1); assert.equal(p.commentFetch.total, 2);
      assert.equal(status.text, '⟳ 抓全部评论 · 下图 1/2', '状态栏：真计数，单位不是「篇」');
      c.feed(JSON.stringify({ type: 'progress', stage: 'render', text: '写进笔记、刷新这一页' }));
      c.feed(JSON.stringify({ ok: true, code: '', message: '评论已更新：12 条一级、40 条回复', comments: 12 }));
      c.finish(0);
    };
    const realSet = ctx.setTimeout;
    const later = [];
    ctx.setTimeout = (fn, ms) => { if (ms >= 8000) { later.push([fn, ms]); return 0; } return realSet(fn, ms); };   // 「过一会儿清掉」手动触发
    const res = await p.fetchAllComments(file);
    ctx.setTimeout = realSet;
    const args = spawned.at(-1).args;
    assert.deepEqual([...args.slice(-5)], ['comments', 'xhs-n1', '--progress', '--wait-lock-min', '10'], '带 --progress、等号最多 10 分钟');
    assert.deepEqual(events.map(e => e && e.stage), ['start', 'start', 'read', 'merge', 'media', 'render', 'render'], '每一步发一次事件，最后一次带结果');
    assert.deepEqual(events.at(-1).result, { ok: true, message: '评论已更新：12 条一级、40 条回复', code: 0 });
    assert.ok(seenStatus.includes('⟳ 抓全部评论 · 读评论区 0:00'), '读评论区时状态栏有已用时间：' + JSON.stringify(seenStatus));
    assert.ok(notices.some(m => String(m).startsWith('开始抓《做饭》的全部评论：进度在这篇的评论区顶上')), '开头那句说清进度在哪');
    assert.ok(notices.includes('评论已更新：12 条一级、40 条回复'), '结束提示用后端那句');
    assert.deepEqual(JSON.parse(JSON.stringify(res)), { ok: true, message: '评论已更新：12 条一级、40 条回复', code: 0 });
    assert.equal(p.running, null); assert.equal(p.runningProgress, '');
    assert.equal(later.length, 1); assert.equal(later[0][1], 8000);
    later[0][0]();
    assert.equal(p.commentFetch, null, '过 8 秒清掉'); assert.equal(events.at(-1), null);
    // 等号等满：后端最后一行是一句人话（不是进度事件），照它说
    plan = c => { c.feed(JSON.stringify({ type: 'progress', stage: 'lock', text: '等号：后台补评论正在用小红书号，它这一篇补完就轮到这里（最多等 10 分钟）' }));
      c.feed(JSON.stringify({ ok: false, code: 'BUSY', message: '号一直被「后台补评论」占着，等了 10 分钟没轮到：过一会儿再点', results: [] })); c.finish(6); };
    ctx.setTimeout = (fn, ms) => (ms >= 8000 ? 0 : realSet(fn, ms));
    const busy = await p.fetchAllComments(file);
    ctx.setTimeout = realSet;
    assert.deepEqual(JSON.parse(JSON.stringify(busy)), { ok: false, message: '号一直被「后台补评论」占着，等了 10 分钟没轮到：过一会儿再点', code: 6 });
    assert.ok(notices.includes('号一直被「后台补评论」占着，等了 10 分钟没轮到：过一会儿再点'), '不再说「正在执行其他任务」');
    plan = null;
  }

  // ── note-actions paintFetch：画在这篇评论区最上面；别的笔记不画；进度 / 结果 / 收起；被摘掉补回 ──
  {
    const dom = makeDom(), D = dom.document;
    const ws = makeWorkspace();
    const mk = id => {
      const pv = D.body.createEl('div', { cls: 'markdown-reading-view' }).createEl('div', { cls: 'markdown-preview-view xhs-note' });
      const note = pv.createEl('div', { cls: 'lb-note', attr: { 'data-lb-item': id } });
      const comments = note.createEl('div', { cls: 'lb-main' }).createEl('div', { cls: 'lb-scroll' }).createEl('section', { cls: 'lb-detail' }).createEl('div', { cls: 'lb-comments' });
      comments.createEl('div', { cls: 'lb-comments-note', text: '楼中楼还缺 7 条' });
      return { note, comments };
    };
    const A = mk('xhs-n1'), B = mk('xhs-other');
    const plugin = { app: { workspace: ws, metadataCache: { getFileCache: () => null }, vault: { adapter: { getBasePath: () => ROOT } } }, manifest: { dir: DIR },
      register() {}, registerEvent() {}, registerDomEvent() {}, addCommand() {}, notify() {}, commentFetch: null };
    const inst = loadNoteActions(dom)({}, plugin);
    const now = Date.now();
    plugin.commentFetch = { itemId: 'xhs-n1', stage: 'read', text: '打开这篇，把评论一楼一楼展开读下来（最多 25 分钟）', startedAt: now - 70000, stageAt: now - 65000, done: null, total: null, result: null };
    inst.paintFetch();
    const box = A.comments.children[0];
    assert.ok(box.classList.contains('lb-fetch-progress'), '在评论区最上面');
    assert.equal(box.getAttribute('role'), 'status');
    assert.match(box.querySelector('.lb-fetch-text').textContent, /^⟳ 抓全部评论 · 打开这篇，把评论一楼一楼展开读下来（最多 25 分钟） · 已用 1:0[56]$/);
    assert.ok(box.classList.contains('is-indeterminate'), '读评论区：不知道多久 → 来回扫');
    assert.equal(B.comments.querySelectorAll('.lb-fetch-progress').length, 0, '别的笔记不画');
    plugin.commentFetch.stage = 'media'; plugin.commentFetch.text = '下载图片 / 语音 3/12'; plugin.commentFetch.done = 3; plugin.commentFetch.total = 12;
    inst.paintFetch();
    assert.equal(A.comments.querySelectorAll('.lb-fetch-progress').length, 1, '不重复插');
    assert.ok(!box.classList.contains('is-indeterminate'));
    assert.equal(box.querySelector('.lb-fetch-fill').style.width, '25%', '下图：按真计数走');
    // Obsidian 重画这一段（摘掉了）：下一拍补回来
    box.remove();
    await tick(1100);
    assert.equal(A.comments.children[0].classList.contains('lb-fetch-progress'), true, '被摘掉了每秒补回');
    plugin.commentFetch.result = { ok: true, message: '评论已更新：12 条一级、40 条回复' };
    inst.paintFetch();
    const done = A.comments.children[0];
    assert.equal(done.querySelector('.lb-fetch-text').textContent, '✓ 评论已更新：12 条一级、40 条回复');
    assert.ok(done.classList.contains('is-done'));
    assert.equal(inst.fetchTick, null, '做完不再每秒刷');
    plugin.commentFetch.result = { ok: false, message: '评论没抓：读取服务未连接' };
    inst.paintFetch();
    assert.equal(A.comments.children[0].querySelector('.lb-fetch-text').textContent, '⚠ 没抓完：读取服务未连接');
    plugin.commentFetch = null;
    inst.paintFetch();
    assert.equal(D.body.querySelectorAll('.lb-fetch-progress').length, 0, '清掉后收起');
    inst.detach();
  }
  console.log('PASS comment fetch progress (1010): --progress events → plugin.commentFetch + status bar (真计数 / 已用时间), readable BUSY result, inline line on that note only (indeterminate while reading, determinate media, ✓ / ⚠, re-added after re-render, removed when cleared)');
})().catch(e => { console.error(e); process.exit(1); });

// 1011：这篇在小红书网页版要验证才能看——前端三处入口都开「这一篇」的验证窗口（plugin.openNoteVerify → note-verify <id> --wait）：
//   ① 问题面板：已放弃组里 NOTE_RESTRICTED 那一行有「打开验证」（不是 needs_you 也给）、能隐藏、能查看；别的已放弃行不给；
//   ② 笔记页：评论区顶上那一行的「打开验证」（.lb-act-note-verify），条目 id 取这篇笔记块的 data-lb-item；同一时刻只开一个；Enter 也能点；
//   ③ main.js openNoteVerify：跑 note-verify <id> --wait（等窗口关，14 分钟上限），结束如实提示 message。
// 假 DOM / 假 runPy / 假 spawnPy，不起真进程（§7.5）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { ROOT, makeDom, makeWorkspace, makeLeaf, makeMetadataCache } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const DIR = 'obsidian-plugins/link-brain-actions';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

async function panel() {
  const dom = makeDom(), notices = [];
  class Modal {
    constructor(app) { this.app = app; this.modalEl = dom.document.body.createEl('div', { cls: 'modal' }); this.contentEl = this.modalEl.createEl('div', { cls: 'modal-content' }); }
    open() { this.opened = Promise.resolve(this.onOpen && this.onOpen()); }
    close() { this.closed = true; this.onClose && this.onClose(); this.modalEl.remove(); }
  }
  const row = o => ({ ts: '2026-10-11T04:01:00+11:00', resolved_at: null, count: 1, ...o });
  const rows = [
    row({ key: 'note.restricted|xhs-r|NOTE_RESTRICTED', step: 'note.restricted', item_id: 'xhs-r', title: '合成笔记 R',
          code: 'PERMANENT.NOTE_RESTRICTED', action: 'gave_up', label: '网页版要验证', hover: '这篇在小红书网页版要验证才能看：…点「打开验证」',
          group: 'gave_up', repairable: false, dismissable: true, status_text: '要你看一眼：点「打开验证」…' }),
    row({ key: 'vision.refine|xhs-a|MODEL_OUTPUT_INVALID', step: 'vision.refine', item_id: 'xhs-a', code: 'PERMANENT.MODEL_OUTPUT_INVALID',
          action: 'gave_up', label: 'AI 结果不可用', hover: '复读', group: 'gave_up', repairable: true, dismissable: true }),
  ];
  const verified = [];
  const plugin = {
    app: { workspace: makeWorkspace(), vault: { adapter: { read: async () => '{"items":[]}' } }, setting: { open() {}, openTabById() {} } },
    manifest: { id: 'link-brain-actions', version: '0.4.2', dir: DIR }, lbPath: p => p,
    async runPy(args) { return { code: 0, json: { ok: true, summary: {}, problems: rows }, out: '', err: '', timedOut: false }; },
    async openNoteVerify(id) { verified.push(id); return { ok: true }; },
    async fixFromCatalog() {}, openAccountStatus() {},
  };
  const ui = require(path.join(ROOT, DIR, 'problems-ui.js'))({ Modal, Notice: class { constructor(m) { notices.push(m); } } }, plugin);
  const m = ui.open(); await m.opened;
  const rowOf = key => m.contentEl.querySelectorAll('.lb-problem').find(r => r.getAttribute('data-key') === key);
  const btns = r => r.querySelectorAll('button').map(b => b.textContent);
  const r = rowOf('note.restricted|xhs-r|NOTE_RESTRICTED');
  assert.deepEqual(btns(r), ['隐藏', '查看', '打开验证'], '已放弃组照样有「打开验证」，还能隐藏 / 查看');
  assert.ok(r.textContent.includes('要你看一眼'), '状态句照 Python 写的');
  assert.deepEqual(btns(rowOf('vision.refine|xhs-a|MODEL_OUTPUT_INVALID')), ['再试一次', '隐藏', '查看'], '别的已放弃行不多出按钮');
  await r.querySelectorAll('button').find(b => b.textContent === '打开验证').onclick();
  assert.deepEqual(verified, ['xhs-r'], '开的是这一篇');
  // 没有 item_id / 插件太旧：不给
  assert.deepEqual(ui._internals.fixesFor({ code: 'PERMANENT.NOTE_RESTRICTED', group: 'gave_up' }), []);
  console.log('PASS problems panel: NOTE_RESTRICTED row (gave_up) gets 打开验证 → openNoteVerify(item_id), still hideable; other gave_up rows unchanged');
}

async function noteActions() {
  const dom = makeDom(), D = dom.document;
  const ws = makeWorkspace();
  const content = D.body.createEl('div', { cls: 'workspace-leaf' }).createEl('div', { cls: 'workspace-leaf-content' });
  const preview = content.createEl('div', { cls: 'markdown-reading-view' }).createEl('div', { cls: 'markdown-preview-view xhs-note' });
  const note = preview.createEl('div', { cls: 'lb-note' });
  note.setAttribute('data-lb-item', 'xhs-n1');
  const line = note.createEl('div', { cls: 'lb-comments' }).createEl('div', { cls: 'lb-comments-note lb-restricted-note', text: '这篇在小红书网页版要验证才能看' });
  const act = line.createEl('span', { cls: 'lb-act lb-act-note-verify', text: '打开验证' });
  const file = { path: 'Web/Xiaohongshu/r.md', basename: 'r' };
  ws.leaves.push(makeLeaf({ containerEl: content, file }));
  const calls = [], notices = [];
  let release;
  const plugin = {
    app: { workspace: ws, metadataCache: makeMetadataCache({ [file.path]: { link_brain: { item_id: 'xhs-n1' } } }), vault: { adapter: { getBasePath: () => ROOT } } },
    manifest: { dir: DIR }, register() {}, registerEvent() {}, registerDomEvent(el, t, fn, o) { el.addEventListener(t, fn, o); }, addCommand() {},
    notify(msg) { notices.push(msg); return {}; },
    openNoteVerify: id => { calls.push(id); return new Promise(r => { release = r; }); },
    dataviewState: () => 'ok',
  };
  const src = fs.readFileSync(path.join(ROOT, DIR, 'note-actions.js'), 'utf8');
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', 'document', 'window', src)(require, mod, mod.exports, D, { getSelection: () => null });
  const inst = mod.exports({ MarkdownView: class {} }, plugin).attach();
  const click = target => { const e = { type: 'click', target, prevented: false, preventDefault() { this.prevented = true; } }; for (const fn of [...(D.listeners.click || [])]) fn(e); return e; };
  const ev = click(act);
  assert.ok(ev.prevented);
  assert.deepEqual(calls, ['xhs-n1'], '条目 id 取这篇笔记块的 data-lb-item');
  click(act);
  assert.deepEqual(calls, ['xhs-n1'], '窗口开着时再点不再开第二个');
  assert.ok(notices.at(-1).includes('已经开着'));
  release({ ok: true }); await tick(5);
  for (const fn of [...(D.listeners.keydown || [])]) fn({ type: 'keydown', key: 'Enter', target: act, preventDefault() {} });
  assert.deepEqual(calls, ['xhs-n1', 'xhs-n1'], 'Enter 也能点（窗口关了之后）');
  release({ ok: true }); await tick(5);
  // 插件太旧（没有 openNoteVerify）：说一句，不抛
  delete plugin.openNoteVerify;
  click(act); await tick(5);
  assert.ok(notices.at(-1).includes('更新 Link Brain Actions'));
  inst.detach();
  console.log('PASS note page: 打开验证 → openNoteVerify(data-lb-item), single window at a time, Enter works, old plugin says update');
}

async function mainJs() {
  const dom = makeDom();
  const notices = [];
  const obs = makeObsidian(dom.document, { notices });
  const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, console, window: { confirm: () => false },
    require: n => n === 'obsidian' ? { ...obs, Notice: class { constructor(m) { notices.push(m); } } }
      : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, DIR, 'main.js'), 'utf8'), context);
  const p = new context.module.exports();
  p.app = { vault: { adapter: { getBasePath: () => ROOT, read: async () => { throw new Error('ENOENT'); } } }, workspace: makeWorkspace() };
  p.manifest = { id: 'link-brain-actions', version: '0.4.2', dir: DIR };
  p.lbPath = x => x;
  p.settings = { sync: {} };
  const calls = [];
  p.spawnPy = async (args, opts) => {
    calls.push({ args: args.slice(2), timeoutMs: opts && opts.timeoutMs });
    return { code: 0, json: { ok: true, code: '', message: '过了，这篇能打开了：评论在后台补（同一篇隔 45 分钟再开），附件今晚 4 点补' }, out: '', err: '', all: '', timedOut: false };
  };
  const r = await p.openNoteVerify('xhs-n1');
  assert.equal(JSON.stringify(calls[0].args), JSON.stringify(['note-verify', 'xhs-n1', '--wait']));
  assert.equal(calls[0].timeoutMs, 14 * 60000, '等窗口关（读取组件验证窗口最长 12 分钟）');
  assert.ok(r.ok && notices.some(n => String(n).includes('看到笔记内容后关掉窗口')) && notices.at(-1).includes('评论在后台补'));
  p.running = '同步收藏';
  assert.equal(await p.openNoteVerify('xhs-n1'), null, '别的长任务在跑：不开');
  assert.equal(calls.length, 1);
  console.log('PASS main.js openNoteVerify: note-verify <id> --wait (14 min), says the real result, refuses while another task runs');
}

(async () => {
  await panel();
  await noteActions();
  await mainJs();
})().catch(e => { console.error(e); process.exit(1); });

// 1011 她的同步记录截图：①「夜跑在同步（计划任务），这里停不了」其实是命令行跑的；②「14:57 命令行 · 没有新内容」那趟其实收了 43 篇
// 才被停掉；③ 04:02 那条「重写目录页 / 补转写视频 PermissionError … 点复制报错发给作者」后来早好了，还红着挂在那。
// 这里：report-ui.js 照后端给的 interrupted / errors[].resolved 画（被中断 · 已收 N 篇；后来好了的灰字一行、不红、不默认展开、
// 不给「看问题」）；main.js externalSyncText 按 sync-status.json 的 trigger 说是谁在跑。假 DOM / 假 runPy，不起进程。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { ROOT, makeDom, makeVault, makeWorkspace } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';

function fakeObsidian(dom, notices) {
  class Modal {
    constructor(app) { this.app = app; this.modalEl = dom.document.body.createEl('div', { cls: 'modal' }); this.contentEl = this.modalEl.createEl('div', { cls: 'modal-content' }); }
    open() { this.opened = Promise.resolve(this.onOpen && this.onOpen()); }
    close() { this.closed = true; this.onClose && this.onClose(); this.modalEl.remove(); }
  }
  return { Modal, Notice: class { constructor(m) { notices.push(m); } } };
}

const RUNS = [
  { run_id: 'r1705', trigger: 'cli', started_at: '2026-10-11T17:05:08+11:00', finished_at: null, running: true, new: 4, error: false,
    counts: { note: { ok: 4, failed: 0 } }, items: [], errors: [] },
  { run_id: 'r1457', trigger: 'cli', started_at: '2026-10-11T14:57:30+11:00', finished_at: '2026-10-11T16:58:00+11:00', interrupted: true, recovered: true,
    new: 43, error: false, counts: { note: { ok: 43, failed: 0 } },
    items: [{ kind: 'note', id: 'xhs-w0', title: '合成 A', note: 'Web/a.md', ok: true }], errors: [] },
  { run_id: 'r0402', trigger: 'nightly', started_at: '2026-10-11T04:02:16+11:00', finished_at: '2026-10-11T05:46:36+11:00', new: 0, error: false,
    counts: { video: { ok: 4, failed: 0 } }, items: [],
    errors: [{ step: 'repair.nightly.catalog', reason: "已试：重写目录页（05:46）；没好：PermissionError: [WinError 5] 拒绝访问。；下一步：点「复制报错」发给作者", resolved: true, label: '重写目录页' },
             { step: 'repair.nightly.videos-transcribe', reason: '已试：补转写视频（05:46）；没好：PermissionError', resolved: true, label: '补转写视频' }] },
  { run_id: 'rkilled0', trigger: 'cli', started_at: '2026-10-09T10:00:00+11:00', finished_at: '2026-10-09T10:05:00+11:00', interrupted: true,
    new: 0, error: false, counts: {}, items: [], errors: [] },
];

(async () => {
  const dom = makeDom(), notices = [];
  const obs = fakeObsidian(dom, notices);
  const problems = [];
  const plugin = { app: { workspace: makeWorkspace(), vault: makeVault({}).vault }, lbPath: p => p,
    async runPy() { return { code: 0, json: { ok: true, runs: RUNS, backlog: { favorites_total: 1246, archived: 610, deferred: 636, days_left: 5,
      message: '收藏 1246 篇，已入库 610 篇，还差 636 篇，预计还要 5 天同步完' } }, out: '', err: '' }; },
    openProblems() { problems.push(1); }, taskLabel: '同步收藏', running: null, externalTaskText: () => '命令行在同步（终端里开的），这里停不了：要停就在那个终端按 Ctrl+C' };
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'report-ui.js'));
  const I = factory(obs, plugin)._internals;
  assert.equal(I.lineText(RUNS[1]), '10/11 14:57 命令行 · 被中断 · 已收 43 篇 · 正文 43 ✅');
  assert.equal(I.lineText(RUNS[3]), '10/09 10:00 命令行 · 被中断 · 已收 0 篇', '被中断、一篇没收：不说「没有新内容」也不说「没做完」');
  assert.equal(I.lineText(RUNS[2]), '10/11 04:02 夜跑 · 视频 4 ✅', '后来好了的报错不让这一行变成「没做完」');
  assert.equal(I.failedCount(RUNS[2]), 0);
  assert.equal(I.lineText(RUNS[0]), '10/11 17:05 命令行 · 新收 4 · 正文 4 ✅ · 进行中…', '还在跑的照旧');
  assert.equal(I.backlogText({ favorites_total: 1246, archived: 610, deferred: 636, days_left: 5, message: '收藏 1246 篇，已入库 610 篇，还差 636 篇，预计还要 5 天同步完' }),
    '收藏 1246 篇，已入库 610 篇，还差 636 篇，预计还要 5 天同步完', '句子用后端那句（和进度条同一份数）');
  assert.equal(I.backlogText({ favorites_total: 10, archived: 5, deferred: 5, days_left: 3 }), '收藏 10 篇，已入库 5 篇，还差 5 篇，预计还要 3 天同步完', '旧后端没 message：同样的说法');

  const m = factory(obs, plugin).open(); await m.opened;
  for (let i = 0; i < 3; i++) await new Promise(r => setTimeout(r, 0));
  const c = m.contentEl;
  assert.equal(c.querySelector('.lb-synclog-now').textContent, '命令行在同步（终端里开的），这里停不了：要停就在那个终端按 Ctrl+C', '照真来源说，不再一律「夜跑」');
  assert.equal(c.querySelector('.lb-synclog-backlog').textContent, '收藏 1246 篇，已入库 610 篇，还差 636 篇，预计还要 5 天同步完');
  const box = id => c.querySelectorAll('.lb-synclog-run').find(b => b.getAttribute('data-run') === id);
  const healed = box('r0402');
  assert.ok(!healed.className.includes('is-error'), '后来好了的那趟不红');
  assert.equal(healed.querySelector('.lb-synclog-detail').hidden, true, '不默认展开');
  healed.querySelector('.lb-synclog-toggle').onclick();
  assert.equal(healed.querySelectorAll('.lb-synclog-err').length, 0, '展开也没有红字');
  assert.equal(healed.querySelector('.lb-synclog-healed').textContent, '✓ 后来好了：重写目录页、补转写视频');
  assert.equal(healed.querySelector('.lb-synclog-retry'), null, '没有「重试」/「看问题」');
  const killed = box('r1457');
  assert.ok(!killed.className.includes('is-error'));
  killed.querySelector('.lb-synclog-toggle').onclick();
  assert.ok(killed.textContent.includes('从库里找回来的') && killed.textContent.includes('合成 A'), '找回来的篇目看得到');

  // main.js：externalSyncText 按 trigger 说
  const fdom = makeDom();
  const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, Buffer, document: fdom.document,
    require: n => (n === 'obsidian' ? makeObsidian(fdom.document, {}) : n === 'child_process' ? { spawn() { throw new Error('不许起进程'); } } : require(n)) };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8') + '\nmodule.exports.__ext = externalSyncText;', context);
  const ext = context.module.exports.__ext;
  assert.match(ext({ trigger: 'cli' }), /^命令行在同步/);
  assert.match(ext({ trigger: 'nightly' }), /^夜跑在同步（计划任务）/);
  assert.match(ext({ trigger: 'schedule' }), /^定时同步在跑/);
  assert.match(ext({}), /^后台在同步（不是这个窗口开的）/, '旧后端没记来源：不瞎说是夜跑');
  const src = fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8') + fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'report-ui.js'), 'utf8');
  assert.ok(!src.includes("'夜跑在同步（计划任务），这里停不了')") && !src.includes("'命令行 / 计划任务在跑，这里停不了'") && !src.includes("'计划任务在跑，这里停不了'"),
    '「这里停不了」只剩按来源说的那一处');
  console.log('PASS sync log truth (1011): killed runs read 被中断 · 已收 N 篇 (recovered titles listed), self-healed step errors grey ✓ 后来好了 (not red, collapsed, no retry), backlog sentence from backend, external sync labelled by real trigger (命令行 / 夜跑 / 定时)');
})().catch(e => { console.error(e); process.exit(1); });

// 第 6 批：目录页标题区小改 + 「本周同步情况」窗口（report-ui.js）。真跑页面脚本、report-ui.js 和插件 main.js，
// 假 DOM / 假 vault / 假 runPy，不起真进程（CONVENTIONS §7.5）。断言：
//   目录页：标题下的同步概况行（.lbc-syncinfo）没了；「N 篇 · 更新 …」那行可点（悬停提示「看本周同步情况」），点了调插件 openWeekReport()
//   窗口：report week --days 7；按天一块（新收 / 正文·机读版 / 附件 / 识图·概要 / 夜跑一句话）；还没完成的列标题、点了同一窗格打开笔记；
//         夜跑有问题带「看问题」→ openProblems()；底部合计 + 还剩 N 篇逐晚处理；空数据 / runPy 失败 / ok:false 如实提示
//   插件：openWeekReport 按需加载 report-ui.js
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { ROOT, asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const LIB = asset('lb-page-lib.js');
const SEARCH = asset('catalog-search.js');
const DATA = '_archive/catalog-data.json';
const SUMMARY = '_archive/problems-summary.json';
const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';

function catalogData() {
  const mk = (id, title) => ({ id, title, tags: [], cats: [], topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: '', attachment: 'none', starred: false, problems: [] });
  return { built_at: '2026-10-03T10:00:00+10:00', pinyin_chars: {}, aliases: [], cats_order: [], cats: [], topics: [], state_registry: {},
    items: [mk('a', '悉尼咖啡地图'), mk('b', '电饭煲鸡肉饭')] };
}

async function catalogTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const V = makeVault({
    [DATA]: JSON.stringify(catalogData()),
    [SUMMARY]: JSON.stringify({ updated_at: '2026-10-03T04:05:00+10:00', needs_human: 0, auto: 0, gave_up: 0, skipped: 0,
      sync: { state: 'ready', last_success: '2026-10-03T04:00:00+10:00', new: 12, deferred: 85 } }),
  });
  let opened = 0;
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {}, openProblems() {}, openWeekReport() { opened++; } };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const A = dataviewBlock({ dom, app, code: LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js') });
  await A.run();
  const q = s => A.container.querySelector(s);
  assert.equal(q('.lbc-syncinfo'), null, '「上次同步 · 本次新收 · 还剩」那行删了');
  assert.ok(!/上次同步/.test(A.container.textContent), '页面上不再出现「上次同步」');
  const sub = q('.lbc-sub-link');
  assert.ok(sub, '「N 篇 · 更新 …」那行可点');
  assert.match(sub.textContent, /^2 篇 · 更新 /);
  assert.equal(sub.title, '看本周同步情况');
  assert.equal(sub.tagName, 'SPAN', '保持灰字，不做成按钮块');
  await sub.onclick();
  assert.equal(opened, 1, '点了 = 插件 openWeekReport()');
  await sub.onkeydown({ key: 'Enter', preventDefault() {} });
  assert.equal(opened, 2, '键盘回车也能开');
  // 插件里还没有 openWeekReport（刚部署、旧实例在内存）：LB.ensure 重载一次插件再调
  {
    delete globalThis.__lbState;
    const old = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {} };
    let reloaded = 0, got = 0;
    const app2 = { vault: makeVault({ [DATA]: JSON.stringify(catalogData()) }).vault, workspace: makeWorkspace(), metadataCache: { getCache: () => null },
      plugins: { plugins: { 'link-brain-actions': old }, disablePlugin: async () => {},
        enablePlugin: async () => { reloaded++; app2.plugins.plugins['link-brain-actions'] = { ...old, openWeekReport() { got++; } }; } } };
    const B = dataviewBlock({ dom, app: app2, code: LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js') });
    await B.run();
    await B.container.querySelector('.lbc-sub-link').onclick();
    assert.equal(reloaded, 1); assert.equal(got, 1, '重载后调到新方法');
  }
  console.log('PASS catalog title: sync overview line removed; "N 篇 · 更新" line clickable (title 看本周同步情况) → LB.ensure(openWeekReport)');
}

function fakeObsidian(dom, notices) {
  class Modal {
    constructor(app) { this.app = app; this.modalEl = dom.document.body.createEl('div', { cls: 'modal' }); this.contentEl = this.modalEl.createEl('div', { cls: 'modal-content' }); }
    open() { this.opened = Promise.resolve(this.onOpen && this.onOpen()); }
    close() { this.closed = true; this.onClose && this.onClose(); this.modalEl.remove(); }
  }
  return { Modal, Notice: class { constructor(m) { notices.push(m); } } };
}
const zero = () => ({ new: 0, note: { done: 0, missing: 0 }, agent: { done: 0, missing: 0 },
  attachments: { expected: 0, downloaded: 0, missing: 0, convertible: 0, converted: 0, unconverted: 0 }, vision_missing: 0, summary_missing: 0 });
const WEEK = {
  ok: true, code: '', message: '最近 7 天新收 5 篇', days: 7, nightly_source: 'log', time_field_note: '按 meta.json 的 first_archived_at（首次入库时间）分天',
  deferred: 40,
  total: { new: 5, note: { done: 4, missing: 1 }, agent: { done: 3, missing: 2 }, attachments: { expected: 3, downloaded: 2, missing: 1, convertible: 2, converted: 1, unconverted: 1 }, vision_missing: 1, summary_missing: 2 },
  rows: [
    { date: '2026-10-03', weekday: '周六', new: 3, note: { done: 2, missing: 1 }, agent: { done: 1, missing: 2 },
      attachments: { expected: 3, downloaded: 2, missing: 1, convertible: 2, converted: 1, unconverted: 1 }, vision_missing: 1, summary_missing: 2,
      incomplete: [
        { id: 'xhs-a', title: '悉尼咖啡地图', note: 'Web/a.md', missing: ['机读版', '附件缺 1 个', '识图'] },
        { id: 'xhs-c', title: '还没渲染的一篇', note: null, missing: ['正文', '机读版', '概要'] }],
      nightly: { source: 'log', finished: false, text: '夜跑没走完（04:00 开始，日志里没有结束）；有问题：夜跑：sync-favorites · 稍后自动重试（1 个还没解决）', open_problems: 1,
        problems: [{ code: 'TRANSIENT.STEP_TIMEOUT', label: '稍后自动重试', step: 'nightly.sync-favorites', open: true }] } },
    { date: '2026-10-02', weekday: '周五', new: 2, note: { done: 2, missing: 0 }, agent: { done: 2, missing: 0 },
      attachments: { expected: 0, downloaded: 0, missing: 0, convertible: 0, converted: 0, unconverted: 0 }, vision_missing: 0, summary_missing: 0,
      incomplete: [], nightly: { source: 'log', finished: true, text: '夜跑走完了', problems: [], open_problems: 0 } },
    { date: '2026-10-01', weekday: '周四', ...zero(), incomplete: [], nightly: { source: 'log', finished: null, text: '那天没跑夜跑', problems: [], open_problems: 0 } },
  ],
};
function makePlugin(reply) {
  const calls = [], problemsOpened = [];
  const workspace = makeWorkspace();
  const plugin = {
    app: { workspace },
    manifest: { id: 'link-brain-actions', version: '0.4.2', dir: PLUGIN_DIR },
    lbPath: p => p,
    async runPy(args, opts) { calls.push(args.slice(2)); return typeof reply === 'function' ? reply(args, opts) : { code: 0, json: reply, out: '', err: '' }; },
    openProblems() { problemsOpened.push(1); },
  };
  return { plugin, calls, workspace, problemsOpened };
}

async function modalTests() {
  const dom = makeDom(), notices = [];
  const obsidian = fakeObsidian(dom, notices);
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'report-ui.js'));
  const { plugin, calls, workspace, problemsOpened } = makePlugin(WEEK);
  const m = factory(obsidian, plugin).open(); await m.opened;
  const c = m.contentEl;
  assert.deepEqual(calls[0], ['report', 'week', '--days', '7']);
  assert.equal(c.querySelector('h2').textContent, '本周同步情况');
  const days = c.querySelectorAll('.lb-report-day');
  assert.equal(days.length, 3, '按天一块，新的在上');
  const d0 = days[0];
  assert.equal(d0.querySelector('.lb-report-dayhead').textContent, '10/03 周六新收 3 篇');
  assert.equal(d0.querySelector('.lb-report-facts').textContent,
    '正文 2/3 · 机读版 1/3 · 附件下好 2/3，还缺 1 个 · 转文字 1/2 · 识图还差 1 篇 · 概要还差 2 篇');
  const night = d0.querySelector('.lb-report-nightly');
  assert.ok(night.classList.contains('is-warn'), '没走完 / 有问题 醒目色');
  assert.ok(night.textContent.startsWith('夜跑没走完（04:00 开始'), night.textContent);
  await night.querySelector('.lb-report-problems').onclick();
  assert.equal(problemsOpened.length, 1, '「看问题」= openProblems()');
  assert.ok(m.closed, '打开问题列表后关掉本窗口');
  // 还没完成的：有正文的可点（同一窗格打开），没正文的只是文字
  const m2 = factory(obsidian, plugin).open(); await m2.opened;
  const d = m2.contentEl.querySelectorAll('.lb-report-day');
  assert.equal(d[0].querySelector('.lb-report-todo-head').textContent, '还没完成的 2 篇');
  const items = d[0].querySelectorAll('.lb-report-item');
  assert.equal(items[0].querySelector('.lb-report-title').tagName, 'A');
  assert.equal(items[0].querySelector('.lb-report-missing').textContent, '差：机读版、附件缺 1 个、识图');
  assert.equal(items[1].querySelector('.lb-report-title').tagName, 'SPAN', '没生成正文的不给链接');
  await items[0].querySelector('.lb-report-title').onclick({ preventDefault() {} });
  assert.deepEqual(workspace.opened.at(-1), ['Web/a.md', '', false], '同一窗格打开那篇');
  assert.ok(m2.closed);
  const m3 = factory(obsidian, plugin).open(); await m3.opened;
  const d3 = m3.contentEl.querySelectorAll('.lb-report-day');
  assert.equal(d3[1].querySelector('.lb-report-facts').textContent, '正文、机读版都生成了 · 识图、概要都齐了', '附件没有就不提');
  assert.equal(d3[1].querySelector('.lb-report-nightly').textContent, '夜跑走完了');
  assert.equal(d3[1].querySelector('.lb-report-problems'), null, '没问题不带按钮');
  assert.ok(d3[2].classList.contains('is-empty'));
  assert.equal(d3[2].querySelector('.lb-report-new').textContent, '没有新收藏');
  assert.equal(d3[2].querySelector('.lb-report-facts'), null);
  const foot = m3.contentEl.querySelector('.lb-report-total');
  assert.ok(foot.querySelector('.lb-report-total-line').textContent.startsWith('合计新收 5 篇 · 正文 4/5'), foot.textContent);
  assert.equal(foot.querySelector('.lb-report-deferred').textContent, '还剩 40 篇收藏逐晚处理');
  assert.equal(m3.contentEl.querySelector('.lb-report-empty'), null);
  console.log('PASS week report modal: report week --days 7, one block per day, counts, incomplete titles open note in same pane, 看问题 → openProblems, total + deferred');

  // ── 空数据 / 没有逐晚处理 / 没夜跑日志 ──
  const empty = { ok: true, days: 7, nightly_source: 'problems', deferred: null, total: zero(),
    rows: [{ date: '2026-10-03', weekday: '周六', ...zero(), incomplete: [], nightly: { source: 'problems', finished: null, text: '没有问题记录', problems: [], open_problems: 0 } }] };
  const e = makePlugin(empty);
  const me = factory(obsidian, e.plugin).open(); await me.opened;
  assert.equal(me.contentEl.querySelector('.lb-report-empty').textContent, '最近 7 天没有新收藏');
  assert.equal(me.contentEl.querySelector('.lb-report-deferred'), null, '没有逐晚处理的不显示');
  assert.ok(me.contentEl.querySelector('.lb-report-total').textContent.includes('这台电脑没有夜跑日志'));
  // runPy 失败 / ok:false
  const broken = makePlugin(() => { throw new Error('找不到 Python。'); });
  const mb = factory(obsidian, broken.plugin).open(); await mb.opened;
  assert.equal(mb.contentEl.querySelector('.lb-report-status').textContent, '读不到同步情况：找不到 Python。');
  const bad = makePlugin({ ok: false, message: 'index.db 读不了', rows: [] });
  const mbad = factory(obsidian, bad.plugin).open(); await mbad.opened;
  assert.equal(mbad.contentEl.querySelector('.lb-report-status').textContent, '读不到同步情况：index.db 读不了');
  console.log('PASS week report modal: empty → 最近 7 天没有新收藏; no deferred line when none; no-log note; runPy / ok:false failures shown');
}

async function pluginTests() {
  const dom = makeDom(), notices = [];
  const fakeObs = fakeObsidian(dom, notices);
  const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, window: { confirm: () => false },
    require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: fakeObs.Modal, Notice: fakeObs.Notice }
      : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8'), context);
  const Plugin = context.module.exports;
  const p = new Plugin();
  p.app = { vault: { adapter: { getBasePath: () => ROOT } }, workspace: makeWorkspace() };
  p.manifest = { id: 'link-brain-actions', version: '0.4.2', dir: PLUGIN_DIR };
  p.lbPath = x => x;
  const ran = [];
  p.runPy = async args => { ran.push(args.slice(2)); return { code: 0, json: WEEK }; };
  const m = p.openWeekReport(); await m.opened;
  assert.deepEqual(ran[0], ['report', 'week', '--days', '7']);
  assert.equal(m.contentEl.querySelectorAll('.lb-report-day').length, 3);
  const doctor = fs.readFileSync(path.join(ROOT, 'link_brain', 'doctor.py'), 'utf8');
  assert.ok(/PLUGIN_FILES = \([^)]*'report-ui\.js'/.test(doctor), 'doctor 必需文件里有 report-ui.js');
  console.log('PASS plugin: openWeekReport loads report-ui.js and runs report week; doctor lists report-ui.js');
}

(async () => {
  await catalogTests();
  await modalTests();
  await pluginTests();
})().catch(e => { console.error(e); process.exitCode = 1; });

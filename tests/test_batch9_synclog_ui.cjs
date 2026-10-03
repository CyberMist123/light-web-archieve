// 10-03（第 9 批）：同步记录窗口（report-ui.js）+ 灵活定时组件（schedule-ui.js）+ 目录页瀑布流列数（catalog-view.js）。
// 真跑 report-ui.js / schedule-ui.js / main.js / 页面脚本，假 DOM / 假 vault / 假 runPy / 假 spawnPy，不起真进程（CONVENTIONS §7.5）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { ROOT, asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';
const flush = async (n = 3) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };

function fakeObsidian(dom, notices) {
  class Modal {
    constructor(app) { this.app = app; this.modalEl = dom.document.body.createEl('div', { cls: 'modal' }); this.contentEl = this.modalEl.createEl('div', { cls: 'modal-content' }); }
    open() { this.opened = Promise.resolve(this.onOpen && this.onOpen()); }
    close() { this.closed = true; this.onClose && this.onClose(); this.modalEl.remove(); }
  }
  return { Modal, Notice: class { constructor(m) { notices.push(m); } } };
}

const RUNS = [
  { run_id: 'r3', trigger: 'nightly', started_at: '2026-10-03T04:00:00+10:00', finished_at: '2026-10-03T05:10:00+10:00', new: 3, error: true,
    counts: { note: { ok: 3, failed: 0 }, attachment: { ok: 2, failed: 1 }, video: { ok: 1, failed: 0 } },
    items: [
      { kind: 'note', id: 'xhs-a', title: '悉尼咖啡地图', note: 'Web/a.md', ok: true },
      { kind: 'attachment', id: 'xhs-b', title: '电饭煲鸡肉饭', note: 'Web/b.md', ok: false, reason: '菜谱.pdf：下载超时' },
      { kind: 'video', id: 'xhs-c', title: '还没渲染的一篇', note: null, ok: true }],
    errors: [] },
  { run_id: 'r2', trigger: 'manual', started_at: '2026-10-02T16:20:00+10:00', finished_at: '2026-10-02T16:40:00+10:00', new: 2, error: false,
    counts: { note: { ok: 2, failed: 0 } }, items: [{ kind: 'note', id: 'xhs-d', title: '旧书店', note: 'Web/d.md', ok: true }], errors: [] },
  { run_id: 'r1', trigger: 'schedule', started_at: '2026-10-01T16:00:00+10:00', finished_at: '2026-10-01T16:01:00+10:00', new: 0, error: true,
    counts: {}, items: [], errors: [{ step: 'sync-favorites', reason: '小红书掉登录：扫码后再同步', code: 'NOT_LOGGED_IN' }] },
];
const LIST = { ok: true, runs: RUNS, backlog: { favorites_total: 1159, archived: 361, deferred: 798, days_left: 16 } };

function makePlugin(reply, { spawn = null, files = {} } = {}) {
  const calls = [], spawned = [], problems = [];
  const workspace = makeWorkspace();
  const V = makeVault(files);
  const plugin = {
    app: { workspace, vault: V.vault },
    lbPath: p => p,
    async runPy(args, opts) { calls.push(args.slice(2)); return typeof reply === 'function' ? reply(args, opts) : { code: 0, json: reply, out: '', err: '' }; },
    async spawnPy(args, opts) { spawned.push({ args: args.slice(2), opts }); return spawn ? spawn(args, opts) : { code: 0, json: { ok: true, message: '重跑了 1 项，成了 1 项' } }; },
    openProblems() { problems.push(1); },
  };
  return { plugin, calls, spawned, workspace, problems, V };
}

async function modalTests() {
  const dom = makeDom(), notices = [];
  const obs = fakeObsidian(dom, notices);
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'report-ui.js'));
  const { _internals: I } = factory(obs, makePlugin(LIST).plugin);
  assert.equal(I.countsText(RUNS[0]), '正文 3 ✅ 附件 2 ✅ 1 ❌ 视频 1 ✅');

  let env = makePlugin(LIST);
  let m = factory(obs, env.plugin).open(); await m.opened;
  const c = m.contentEl;
  assert.deepEqual(env.calls[0], ['synclog', 'list', '--limit', '30']);
  assert.equal(c.querySelector('h2').textContent, '同步记录');
  assert.equal(c.querySelector('.lb-synclog-backlog').textContent, '一共 1159 篇收藏，已入库 361 篇，预计还要 16 天同步完', '第一排：积压');
  const runs = c.querySelectorAll('.lb-synclog-run');
  assert.equal(runs.length, 3, '每次同步一行，新的在前');
  const line = r => r.querySelector('.lb-synclog-line').textContent;
  assert.match(line(runs[0]), /^10\/03 0?4:00 夜跑 · 新收 3 · 正文 3 ✅ 附件 2 ✅ 1 ❌ 视频 1 ✅$/);
  assert.match(line(runs[1]), /^10\/02 16:20 手动 · 新收 2 · 正文 2 ✅$/);
  assert.match(line(runs[2]), /^10\/01 16:00 定时 · 没做完$/);
  // 有报错的默认展开（原因 + 重试）；没报错的收起只一行
  assert.ok(runs[0].classList.contains('is-error'));
  assert.equal(runs[0].querySelector('.lb-synclog-detail').hidden, false, '有失败的默认展开');
  assert.equal(runs[1].querySelector('.lb-synclog-detail').hidden, true, '没报错的默认收起');
  assert.equal(runs[1].querySelector('.lb-synclog-toggle').textContent, '⬇️');
  const failed = runs[0].querySelector('.lb-synclog-item.is-failed');
  assert.equal(failed.textContent, '❌附件电饭煲鸡肉饭菜谱.pdf：下载超时', '失败的排前面，带原因');
  assert.ok(runs[0].querySelector('.lb-synclog-retry'), '有失败 → 重试');
  assert.equal(runs[1].querySelector('.lb-synclog-retry'), null);
  assert.equal(runs[2].querySelector('.lb-synclog-err').textContent, '❌ 小红书掉登录：扫码后再同步');
  await runs[2].querySelector('.lb-report-problems').onclick();
  assert.equal(env.problems.length, 1, '步骤级报错带「看问题」');
  // 展开没报错的那条：看到标题，点了同一窗格打开
  m = factory(obs, env.plugin).open(); await m.opened;
  let r1 = m.contentEl.querySelectorAll('.lb-synclog-run')[1];
  r1.querySelector('.lb-synclog-toggle').onclick();
  assert.equal(r1.querySelector('.lb-synclog-detail').hidden, false);
  assert.equal(r1.querySelector('.lb-synclog-toggle').textContent, '⬆️');
  const a = r1.querySelector('a.lb-synclog-title');
  assert.equal(a.textContent, '旧书店');
  await a.onclick({ preventDefault() {} });
  assert.deepEqual(env.workspace.opened.at(-1), ['Web/d.md', '', false], '同一窗格打开那篇');
  // 没正文的只是文字
  m = factory(obs, env.plugin).open(); await m.opened;
  const r0 = m.contentEl.querySelectorAll('.lb-synclog-run')[0];
  const plain = r0.querySelectorAll('.lb-synclog-title').find(x => x.textContent === '还没渲染的一篇');
  assert.equal(plain.tagName, 'SPAN');
  // 重试：synclog retry --run（独占），结果如实提示，重新读一遍
  const before = env.calls.length;
  await r0.querySelector('.lb-synclog-retry').onclick(); await flush();
  assert.deepEqual(env.spawned.at(-1).args, ['synclog', 'retry', '--run', 'r3']);
  assert.equal(env.spawned.at(-1).opts.exclusive, true);
  assert.equal(notices.at(-1), '重跑了 1 项，成了 1 项');
  assert.equal(env.calls.length, before + 1, '重试完重新读同步记录');
  const box = m.contentEl.querySelectorAll('.lb-synclog-run').find(x => x.getAttribute('data-run') === 'r3');
  assert.match(box.querySelector('.lb-synclog-retrymsg').textContent, /✅ 重跑了 1 项/);
  // 别的任务在跑：不重试，说清楚
  env = makePlugin(LIST, { spawn: () => ({ busy: true, code: 1, json: null, err: '还在跑「同步收藏」' }) });
  m = factory(obs, env.plugin).open(); await m.opened;
  const rr = m.contentEl.querySelector('.lb-synclog-run');
  await rr.querySelector('.lb-synclog-retry').onclick();
  assert.equal(rr.querySelector('.lb-synclog-retrymsg').textContent, '还在跑「同步收藏」');
  console.log('PASS sync log modal: synclog list, backlog first row, one line per run (正文 3 ✅ 附件 1 ❌), errors expanded + retry via synclog retry --run, ok rows collapsed, titles open note in same pane');

  // 积压清零：第一排不显示；没记录；后端起不来 → 直接读库里的 jsonl
  env = makePlugin({ ok: true, runs: [], backlog: null });
  m = factory(obs, env.plugin).open(); await m.opened;
  assert.equal(m.contentEl.querySelector('.lb-synclog-backlog'), null, '积压清零不显示');
  assert.equal(m.contentEl.querySelector('.lb-report-empty').textContent, '还没有同步记录（下次同步完会记在这里）');
  const jsonl = JSON.stringify(RUNS[2]) + '\n坏行\n' + JSON.stringify(RUNS[1]) + '\n';
  env = makePlugin(() => { throw new Error('没找到后端程序'); }, { files: { '_archive/sync-log.jsonl': jsonl } });
  m = factory(obs, env.plugin).open(); await m.opened;
  const fr = m.contentEl.querySelectorAll('.lb-synclog-run');
  assert.equal(fr.length, 2, '没有后端也看得到记录（手机）');
  assert.match(fr[0].querySelector('.lb-synclog-line').textContent, /手动/, '文件里后写的在前');
  env = makePlugin(() => { throw new Error('找不到 Python。'); });
  m = factory(obs, env.plugin).open(); await m.opened;
  assert.equal(m.contentEl.querySelector('.lb-report-status').textContent, '读不到同步记录：找不到 Python。');
  console.log('PASS sync log modal: backlog hidden when cleared, empty state, falls back to reading _archive/sync-log.jsonl, failure shown honestly');
}

async function scheduleTests() {
  const dom = makeDom(), notices = [];
  const obs = fakeObsidian(dom, notices);
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'schedule-ui.js'));
  const I = factory(obs, {})._internals;
  assert.deepEqual(I.rulesFromRows([{ kind: 'daily', timesText: '16:00，4:00 16:00' }]).rules, [{ kind: 'daily', times: ['04:00', '16:00'] }]);
  assert.match(I.rulesFromRows([{ kind: 'weekly', days: [], times: ['08:00'] }]).error, /至少选一天/);
  assert.deepEqual(I.rulesFromRows([{ kind: 'once', at: '2026-10-3T17:00' }]).rules, [{ kind: 'once', at: '2026-10-03 17:00' }]);
  assert.match(I.rulesFromRows([{ kind: 'hourly', hours: 8 }]).error, /1–6/);
  assert.match(I.rulesFromRows([]).error, /至少要有一条/);
  assert.deepEqual(I.rowsFromState({ freq: 'weekly', time: '08:00', day: 'Monday,Thursday' }), [{ kind: 'weekly', days: ['Monday', 'Thursday'], times: ['08:00'] }], '老格式也认');

  const saved = [];
  let state = { task: 'LinkBrainNightly', freq: 'custom', enabled: true, summary: '每周一 08:00 · 每 4 小时一次 · 下次 10/06 08:00',
    rules: [{ kind: 'weekly', days: ['Monday'], times: ['08:00'] }, { kind: 'hourly', hours: 4, from: '00:00' }], others: ['登录时'] };
  const plugin = {
    async getSyncSchedule() { return state; },
    async setSyncRules(rules) { saved.push(rules); return { ok: true, detail: '已保存：每周一、四 08:00 · 每天 04:00、16:00 · 10/09 17:00 一次' }; },
    async setSyncSchedule(f) { saved.push(f); state = { ...state, enabled: false, summary: '已关闭' }; return { ok: true }; },
  };
  const host = dom.document.body.createDiv();
  const ed = factory(obs, plugin).render(host); await ed.ready;
  const box = host.querySelector('.lb-sched');
  assert.equal(box.querySelector('.lb-sched-status').textContent, '当前：每周一 08:00 · 每 4 小时一次 · 下次 10/06 08:00　·　另有：登录时（不改动）', '一行人话');
  let rows = box.querySelectorAll('.lb-sched-row');
  assert.deepEqual(rows.map(r => r.getAttribute('data-kind')), ['weekly', 'hourly']);
  assert.equal(box.querySelector('.lb-sched-warn').hidden, false, '有每几小时 → 提醒风控（不拦）');
  assert.match(box.querySelector('.lb-sched-warn').textContent, /风控/);
  assert.equal(rows[1].querySelector('.lb-sched-hours').value, '4');
  // 周四也勾上；加一条每天两次；加一条一次性；删掉每 4 小时
  rows[0].querySelectorAll('.lb-sched-day').find(b => b.getAttribute('data-day') === 'Thursday').onclick();
  rows = box.querySelectorAll('.lb-sched-row');
  assert.ok(rows[0].querySelectorAll('.lb-sched-day').find(b => b.getAttribute('data-day') === 'Thursday').classList.contains('is-on'));
  rows[1].querySelector('.lb-sched-del').onclick();
  assert.equal(box.querySelector('.lb-sched-warn').hidden, true, '没有每几小时就不提醒');
  box.querySelector('.lb-sched-add').onclick();
  rows = box.querySelectorAll('.lb-sched-row');
  const t = rows[1].querySelector('.lb-sched-times'); t.value = '04:00, 16:00'; t.oninput();
  box.querySelector('.lb-sched-add').onclick();
  rows = box.querySelectorAll('.lb-sched-row');
  const kind = rows[2].querySelector('.lb-sched-kind'); kind.value = 'once'; kind.onchange();
  rows = box.querySelectorAll('.lb-sched-row');
  await box.querySelector('.lb-sched-save').onclick();
  assert.match(box.querySelector('.lb-sched-msg').textContent, /一次性的要填日期和时间/, '没填日期不保存');
  assert.equal(saved.length, 0);
  const at = rows[2].querySelector('.lb-sched-at'); at.value = '2026-10-09T17:00'; at.oninput();
  await box.querySelector('.lb-sched-save').onclick(); await flush();
  assert.deepEqual(saved[0], [{ kind: 'weekly', days: ['Monday', 'Thursday'], times: ['08:00'] }, { kind: 'daily', times: ['04:00', '16:00'] }, { kind: 'once', at: '2026-10-09 17:00' }]);
  assert.match(box.querySelector('.lb-sched-msg').textContent, /^已保存：/);
  await box.querySelector('.lb-sched-off').onclick(); await flush();
  assert.equal(saved[1], 'off');
  assert.equal(box.querySelector('.lb-sched-status').textContent, '当前：已关闭');
  // 每几小时：1–6 下拉
  const k2 = box.querySelectorAll('.lb-sched-row')[0].querySelector('.lb-sched-kind'); k2.value = 'hourly'; k2.onchange();
  assert.equal(box.querySelectorAll('.lb-sched-row')[0].querySelectorAll('option').length, 4 + 6);
  console.log('PASS schedule editor: rules ↔ rows, status one-liner, weekly multi-day, daily several times, once, hourly 1–6 + risk note, save via setSyncRules, off via setSyncSchedule');
}

function loadPlugin(dom, notices) {
  const fakeObs = fakeObsidian(dom, notices);
  class Setting {
    constructor(el) { this.settingEl = el.createDiv({ cls: 'setting-item' }); }
    setName() { return this; } setDesc() { return this; } addButton(f) { const b = { setButtonText: () => b, setCta: () => b, onClick: () => b }; f(b); return this; }
    addText(f) { const t = { setPlaceholder: () => t, setValue: () => t, onChange: () => t }; f(t); return this; }
  }
  class Menu {
    constructor() { this.items = []; loadPlugin.lastMenu = this; }
    addItem(cb) { const it = { title: '', click: null, setTitle(t) { this.title = t; return this; }, setIcon() { return this; }, onClick(f) { this.click = f; return this; } }; cb(it); this.items.push(it); return this; }
    addSeparator() { this.items.push({ title: '---' }); return this; }
    showAtMouseEvent() {} showAtPosition() {}
  }
  const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, window: { confirm: () => false },
    require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: fakeObs.Modal, Notice: fakeObs.Notice, Setting, Menu }
      : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8'), context);
  return context.module.exports;
}

async function pluginTests() {
  const dom = makeDom(), notices = [];
  const Plugin = loadPlugin(dom, notices);
  const p = new Plugin();
  p.app = { vault: { adapter: { getBasePath: () => ROOT } }, workspace: makeWorkspace() };
  p.manifest = { id: 'link-brain-actions', version: '0.4.2', dir: PLUGIN_DIR };
  p.lbPath = x => x;
  const ran = [];
  p.runPy = async (args, opts = {}) => {
    ran.push({ args: args.slice(2), env: opts.env || null });
    if (args[3] === 'list') return { code: 0, json: LIST };
    if (args.includes('--install')) return { code: 0, json: { ok: true, task: 'LinkBrainNightly', message: '已注册' } };
    if (args.includes('--rules')) return { code: 0, json: { ok: true, detail: '已保存：每 4 小时一次' } };
    return { code: 0, json: { task: opts.env?.LINK_BRAIN_SYNC_TASK, freq: 'none', enabled: false } };
  };
  const m = p.openSyncLog(); await m.opened;
  assert.deepEqual(ran[0].args, ['synclog', 'list', '--limit', '30']);
  assert.equal(m.contentEl.querySelectorAll('.lb-synclog-run').length, 3);
  const m2 = p.openWeekReport(); await m2.opened;
  assert.equal(m2.contentEl.querySelector('h2').textContent, '同步记录', '旧名 openWeekReport 也开同步记录');
  // 立即同步标成「手动」（同步记录收尾一行）
  const spawned = [];
  p.spawnPy = (args, opts) => { spawned.push({ args, opts }); return Promise.resolve({ code: 0, all: 'ok', out: '' }); };
  p.log = async () => {};
  await p.syncNow();
  assert.equal(JSON.stringify(spawned[0].opts.env), JSON.stringify({ LINK_BRAIN_SYNC_TRIGGER: 'manual' }));
  // 灵活定时：没有计划任务 → 先注册包内夜跑，再 --rules 写规则（任务名经 env 传）
  ran.length = 0;
  const r = await p.setSyncRules([{ kind: 'hourly', hours: 4, from: '06:00' }]);
  assert.equal(r.ok, true);
  const install = ran.find(x => x.args.includes('--install'));
  assert.ok(install && install.args.includes('06:00'), '没有任务：先注册（时刻取第一条规则的）');
  const rules = ran.find(x => x.args.includes('--rules'));
  assert.deepEqual(JSON.parse(rules.args[rules.args.indexOf('--rules') + 1]), [{ kind: 'hourly', hours: 4, from: '06:00' }]);
  assert.equal(rules.env.LINK_BRAIN_SYNC_TASK, 'LinkBrainNightly');
  // 状态一行：Python 给了 summary 就用它
  assert.equal(Plugin.scheduleStatusText({ freq: 'custom', summary: '每周一 08:00 · 每 4 小时一次 · 下次 10/06 08:00', rules: [{}], others: [] }),
    '当前：每周一 08:00 · 每 4 小时一次 · 下次 10/06 08:00');
  const doctor = fs.readFileSync(path.join(ROOT, 'link_brain', 'doctor.py'), 'utf8');
  assert.ok(/PLUGIN_FILES = \([^)]*'schedule-ui\.js'/.test(doctor), 'doctor 必需文件里有 schedule-ui.js');
  assert.ok(/PLUGIN_FILES = \([^)]*'report-ui\.js'/.test(doctor));
  console.log('PASS plugin: openSyncLog (and old openWeekReport) → synclog list; syncNow env trigger=manual; setSyncRules installs then --rules with task env; summary status line; doctor lists schedule-ui.js');

  // 同步记录窗口顶部：立即同步 / 改定时
  let synced = 0, planned = 0;
  p.syncNow = () => { synced++; };
  p.openSyncSettings = () => { planned++; };
  let w = p.openSyncLog(); await w.opened;
  w.contentEl.querySelector('.lb-synclog-sync').onclick();
  assert.equal(synced, 1); assert.ok(w.closed);
  w = p.openSyncLog(); await w.opened;
  w.contentEl.querySelector('.lb-synclog-plan').onclick();
  assert.equal(planned, 1, '「改定时」= 同步收藏夹弹窗（定时组件）');
  console.log('PASS sync log modal top: 立即同步 → syncNow, 改定时 → openSyncSettings');

  // 「+」：导入网址 / 立即同步收藏 / 账号登录 / 换号
  let imported = 0, acct = 0;
  p.openImportModal = () => { imported++; }; p.openAccountStatus = () => { acct++; };
  p.openPlusMenu({ pageX: 1 });
  const plus = loadPlugin.lastMenu.items.map(i => i.title);
  assert.deepEqual(plus, ['导入网址', '立即同步收藏', '---', '账号登录 / 换号']);
  loadPlugin.lastMenu.items[1].click(); loadPlugin.lastMenu.items[3].click(); loadPlugin.lastMenu.items[0].click();
  assert.deepEqual([synced, acct, imported], [2, 1, 1], '立即同步 / 账号面板（扫码 / 更换账号）/ 导入');
  // 「…」：改标题 / 每行几列 / 管理分类 / 回收站 / 导出资料 / 设置 / 刷新目录（小字：重新整理分类）
  const opened = [];
  p.openLibraryPage = x => opened.push(x); p.openExportFolder = () => opened.push('export');
  p.openPluginSettings = id => opened.push('settings:' + id); p.run = (args, label) => opened.push(label);
  let cats = 0;
  p.openManageMenu({ currentTarget: { getBoundingClientRect: () => ({ left: 0, bottom: 0 }) } }, { categories: () => cats++ });
  const manage = loadPlugin.lastMenu.items;
  assert.deepEqual(manage.map(i => i.title), ['改标题…', '每行几列…', '管理分类', '回收站', '导出资料', '设置', '刷新目录（重新整理分类）']);
  for (const i of manage.slice(2)) i.click();
  assert.equal(cats, 1, '管理分类保留');
  assert.deepEqual(opened, ['trash', 'export', 'settings:link-brain-actions', '刷新目录']);
  p.openAISettingsMenu({});
  assert.deepEqual(loadPlugin.lastMenu.items.map(i => i.title), ['设置', '导出资料'], '「模型与提示词」并进「设置」');
  // 改标题 / 每行几列：存设置 + 通知开着的目录页
  const events = [];
  p.settings = { catalogColumns: 0, catalogTitle: '' };
  let saves = 0; p.saveSettings = async () => { saves++; };
  p.app.workspace.trigger = (name, payload) => events.push([name, payload]);
  p.openCatalogTitle();
  const tm = dom.document.body.querySelectorAll('.modal').at(-1);
  assert.equal(tm.querySelector('h2').textContent, '改标题');
  await p.setCatalogPrefs({ title: '  我的书架  ' });
  assert.equal(p.settings.catalogTitle, '我的书架');
  p.openColumnsPicker();
  const cm = dom.document.body.querySelectorAll('.modal').at(-1);
  const btns = cm.querySelectorAll('.lb-cols-btn');
  assert.deepEqual(btns.map(b => b.textContent), ['自动', '2 列', '3 列', '4 列', '5 列', '6 列']);
  await btns[3].onclick();
  assert.equal(p.settings.catalogColumns, 4);
  await p.setCatalogPrefs({ columns: 9 });
  assert.equal(p.settings.catalogColumns, 0, '超出 2–6 = 自动');
  assert.equal(saves, 3);
  assert.equal(events.at(-1)[0], 'link-brain:catalog-prefs');
  console.log('PASS menus: + (导入网址 / 立即同步收藏 / 账号登录 / 换号), … (改标题 / 每行几列 / 管理分类 / 回收站 / 导出资料 / 设置 / 刷新目录+小字), AI menu 设置; title / columns saved + event');
}

function catalogData() {
  const mk = (id, title) => ({ id, title, tags: [], cats: [], topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: '', attachment: 'none', starred: false, problems: [] });
  return { built_at: '2026-10-03T10:00:00+10:00', pinyin_chars: {}, aliases: [], cats_order: [], cats: [], topics: [], state_registry: {},
    items: [mk('a', '悉尼咖啡地图'), mk('b', '电饭煲鸡肉饭'), mk('c', '旧书店')] };
}

async function columnsTests() {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const V = makeVault({ '_archive/catalog-data.json': JSON.stringify(catalogData()) });
  let saves = 0;
  const plugin = { settings: { hiddenCats: [], catalogColumns: 0 }, saveSettings() { saves++; }, openAttachments() {}, openCategories() {}, openLibraryPage() {}, openProblems() {}, openSyncLog() {} };
  const workspace = makeWorkspace();
  const app = { vault: V.vault, workspace, plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const code = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js');
  const A = dataviewBlock({ dom, app, code });
  await A.run();
  const grid = A.container.querySelector('.lbc-grid');
  const wrap = A.container.querySelector('.lbc-wrap');
  assert.ok(!grid.classList.contains('lbc-has-cols'), '没调过 = 按宽度自动');
  const cardsBefore = A.container.querySelectorAll('.lbc-card');
  const key = (k, extra = {}) => {
    let prevented = false;
    const ev = { key: k, code: '', ctrlKey: true, metaKey: false, altKey: false, preventDefault() { prevented = true; }, stopPropagation() {}, stopImmediatePropagation() {}, ...extra };
    for (const fn of dom.document.listeners.keydown || []) fn(ev);
    return prevented;
  };
  // 不是当前视图、鼠标也不在页上：Ctrl + 加号不拦（Obsidian 照常整窗缩放）
  workspace.activeLeaf = { view: { containerEl: dom.document.body.createDiv() } };
  assert.equal(key('='), false);
  assert.ok(!grid.classList.contains('lbc-has-cols'));
  // 当前视图是目录页：Ctrl + 加号 = 卡片变大（4 → 3 列），Ctrl + 减号 = 变小；最少 2、最多 6
  workspace.activeLeaf = { view: { containerEl: A.host } };
  assert.equal(key('='), true, '在目录页上拦下 Ctrl + 加号');
  assert.ok(grid.classList.contains('lbc-has-cols'));
  assert.equal(grid.style['--lbc-cols'], '3');
  key('+'); key('=', { key: '=', code: 'Equal' }); key('=');
  assert.equal(grid.style['--lbc-cols'], '2', '最少 2 列');
  for (let i = 0; i < 6; i++) key('-');
  assert.equal(grid.style['--lbc-cols'], '6', '最多 6 列');
  key('', { code: 'NumpadAdd' });
  assert.equal(grid.style['--lbc-cols'], '5', '小键盘加号也认');
  assert.equal(key('=', { ctrlKey: false }), false, '不按 Ctrl 不管');
  assert.equal(plugin.settings.catalogColumns, 5, '列数记在插件设置');
  await new Promise(r => setTimeout(r, 700));
  assert.ok(saves >= 1, '设置存盘（合并成一次）');
  // Ctrl + 滚轮：鼠标在页上才有（监听挂在本页上）；往上滚一格 = 卡片变大
  workspace.activeLeaf = null;
  let prevented = false;
  wrap.fire('wheel', { ctrlKey: true, deltaY: -100, preventDefault() { prevented = true; } });
  assert.equal(prevented, true); assert.equal(grid.style['--lbc-cols'], '4');
  wrap.fire('wheel', { ctrlKey: true, deltaY: 40 }); wrap.fire('wheel', { ctrlKey: true, deltaY: 40 });
  assert.equal(grid.style['--lbc-cols'], '4', '触控板小步：攒够一格才动');
  wrap.fire('wheel', { ctrlKey: true, deltaY: 40 });
  assert.equal(grid.style['--lbc-cols'], '5');
  prevented = false;
  wrap.fire('wheel', { ctrlKey: false, deltaY: 100, preventDefault() { prevented = true; } });
  assert.equal(prevented, false, '不按 Ctrl 的滚轮照常滚动');
  // 鼠标在页上（不是当前视图也算）：键盘也生效
  wrap.fire('mouseenter');
  assert.equal(key('-'), true); assert.equal(grid.style['--lbc-cols'], '6');
  wrap.fire('mouseleave');
  assert.equal(key('-'), false, '鼠标离开、又不是当前视图：不拦');
  const cardsAfter = A.container.querySelectorAll('.lbc-card');
  assert.ok(cardsAfter.length === cardsBefore.length && cardsAfter.every((c, i) => c === cardsBefore[i]), '只改布局，卡片一张没重建');
  // 重开页面：按插件设置里记的列数排
  delete globalThis.__lbState;
  const nKeys = (dom.document.listeners.keydown || []).length;
  const B = dataviewBlock({ dom, app, code });
  await B.run();
  const g2 = B.container.querySelector('.lbc-grid');
  assert.ok(g2.classList.contains('lbc-has-cols')); assert.equal(g2.style['--lbc-cols'], '6');
  assert.equal((dom.document.listeners.keydown || []).length, nKeys, '重开页面摘掉上一份键盘监听，不叠加');
  // 「…→改标题 / 每行几列」：事件来了就地换标题和列数，卡片不重建
  assert.equal(B.container.querySelector('.lbc-title-text').textContent, 'Collections', '没改过 = Collections');
  plugin.settings.catalogTitle = '我的书架'; plugin.settings.catalogColumns = 3;
  const cardsB = B.container.querySelectorAll('.lbc-card');
  for (const fn of workspace.handlers['link-brain:catalog-prefs'] || []) fn({});
  assert.equal(B.container.querySelector('.lbc-title-text').textContent, '我的书架');
  assert.equal(g2.style['--lbc-cols'], '3');
  plugin.settings.catalogColumns = 0;
  for (const fn of workspace.handlers['link-brain:catalog-prefs'] || []) fn({});
  assert.ok(!g2.classList.contains('lbc-has-cols'), '改回自动');
  assert.ok(B.container.querySelectorAll('.lbc-card').every((c, i) => c === cardsB[i]));
  const css = asset('catalog-view.js');
  assert.ok(css.includes('.lbc-grid.lbc-has-cols .lbc-grid-inner{columns:auto;column-count:var(--lbc-cols);'), 'CSS 按变量定列数');
  console.log('PASS catalog columns: Ctrl +/- and Ctrl+wheel change waterfall columns 2–6 only when the page is active/hovered, no card rebuild, remembered in plugin settings');
}

async function lowHitTests() {
  // 单测：命中明细 → 浅色片段
  const ctx = {}; vm.createContext(ctx);
  vm.runInContext(asset('catalog-search.js') + '\nthis.lowConfidenceSnippet = lowConfidenceSnippet;', ctx);
  const low = ctx.lowConfidenceSnippet;
  const it = { title: '悉尼咖啡地图', search_fields: { body: '周末去了悉尼的一家咖啡店，拿铁很好喝' } };
  assert.equal(low(it, { fuzzy: false, hits: [{ term: '悉尼', kind: 'exact', field: 'title', variant: '悉尼' }] }), '', '原词命中只显示标题');
  assert.equal(low(it, { fuzzy: true, hits: [{ term: '西尼', kind: 'pinyin', field: 'pinyin' }] }), '拼音相近：西尼');
  assert.match(low(it, { fuzzy: false, hits: [{ term: 'coffee', kind: 'alias', field: 'body', variant: '咖啡' }] }), /^正文：.*咖啡店/);
  assert.equal(low(it, { fuzzy: false, hits: [{ term: 'coffee', kind: 'alias', field: 'title', variant: '咖啡' }] }).startsWith('正文：'), true, '标题里命中也从正文找一段');
  assert.equal(low({ title: 'x' }, { hits: [{ term: 'coffee', kind: 'alias', field: 'title', variant: '咖啡' }] }), '同义词：coffee → 咖啡');
  assert.equal(low(it, { hits: [{ term: '提神', kind: 'semantic', snippet: '  拿铁\n很好喝 ' }] }), '拿铁 很好喝', '结果自带片段（以后的语义命中）就用它');
  assert.equal(low(it, null), '');

  // 真跑目录页：搜 coffee —— 原词命中的那篇只有标题；同义词命中的那篇标题下多一行浅色片段
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const data = catalogData();
  data.aliases = [['咖啡', 'coffee']];
  data.items[2].search_fields = { body: 'best coffee shop list' };
  data.items[0].search_fields = { body: '周末去了悉尼的一家咖啡店' };
  const V = makeVault({ '_archive/catalog-data.json': JSON.stringify(data) });
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {}, openProblems() {}, openSyncLog() {} };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js') });
  await A.run();
  assert.equal(A.container.querySelectorAll('.lbc-lowhit').length, 0, '没搜索不显示');
  const search = A.container.querySelector('.lbc-search');
  search.value = 'coffee';
  search.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} });
  const cards = A.container.querySelectorAll('.lbc-card');
  const byTitle = t => cards.find(c => c.querySelector('.lbc-ctitle').textContent === t);
  assert.ok(byTitle('旧书店') && !byTitle('旧书店').querySelector('.lbc-lowhit'), '原词命中：只有标题');
  const lowEl = byTitle('悉尼咖啡地图').querySelector('.lbc-lowhit');
  assert.ok(lowEl, '同义词命中：标题下浅色片段');
  assert.match(lowEl.textContent, /^正文：周末去了悉尼的一家咖啡店/);
  search.value = ''; search.oninput();
  assert.equal(A.container.querySelectorAll('.lbc-lowhit').length, 0, '清空搜索片段就没了');
  console.log('PASS low-confidence hits: alias / pinyin / typo / gap / semantic show a faint snippet under the title; exact hits stay title-only');
}

(async () => {
  await lowHitTests();
  await modalTests();
  await scheduleTests();
  await pluginTests();
  await columnsTests();
})().catch(e => { console.error(e); process.exitCode = 1; });

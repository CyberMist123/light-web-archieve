// 第 4 批：故障分类 + 问题入口的前端部分（CONVENTIONS §3、§5.7；RELEASE-BAR P12）。真跑页面脚本、problems-ui.js 和插件 main.js，
// 假 DOM / 假 vault / 假 runPy，不起真进程（§7.5）。断言：
//   目录页顶部问题入口：要你处理=橙色数字、其余（自动处理中+已放弃）=灰色数字、未开启不计数、都为 0 不显示；同步中显示「· 同步中…」；
//     副行同步概况第 6 批已删；problems-summary.json / sync-status.json 变了只重画入口，不重建整页、不重读 catalog-data
//   卡片：按 it.problems 出灰标（要你处理的醒目色），悬停 = hover；同标签只出一个；「未开启」不上卡片；和附件标同名不重复
//   问题列表 Modal：分组「等你处理 / 正在自动处理 / 已放弃 / 未开启」，每行时间 · 标题 · 标签 · 系统动作 · 次数 · 查看；登录 / 验证类带按钮走 fixFromCatalog
//   复制报错：problems export --plugin-version <manifest.version> → 剪贴板，成功 / 失败如实提示；空列表「没有问题」；runPy 失败如实提示
//   插件：同步状态以 problems-summary 的 sync 段为准、不再 process.kill 查 pid；状态文案从 state_registry 取
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { ROOT, asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const LIB = asset('lb-page-lib.js');
const SEARCH = asset('catalog-search.js');
const DATA = '_archive/catalog-data.json';
const SUMMARY = '_archive/problems-summary.json';
const SYNC = '_archive/sync-status.json';
const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

const REGISTRY = {
  'NEEDS_HUMAN.NOT_LOGGED_IN': { where: 'top+card', label: '需要登录', hover: '小红书掉登录', group: 'needs_you' },
  'NEEDS_HUMAN.CAPTCHA_REQUIRED': { where: 'top+card', label: '需要验证', hover: '要安全验证', group: 'needs_you' },
  'TRANSIENT.INTERRUPTED': { where: 'list', label: '被打断', hover: '上次中途被打断', group: 'auto' },
  'TRANSIENT.*': { where: 'list', label: '稍后自动重试', hover: '{reason}', group: 'auto' },
};
function catalogData() {
  const mk = (id, title, more = {}) => ({ id, title, tags: [], cats: ['城市'], topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: '', attachment: 'none', starred: false, ...more });
  return { built_at: '2026-10-02T10:00:00+10:00', pinyin_chars: {}, aliases: [], cats_order: ['城市'], cats: [], topics: [], state_registry: REGISTRY,
    items: [
      mk('a', '悉尼咖啡地图', { problems: [
        { code: 'PERMANENT.PDF_ENCRYPTED', label: '全文没转出来', hover: 'PDF 有打开密码，字节已保存', group: 'gave_up', action: 'gave_up' },
        { code: 'PERMANENT.PDF_DAMAGED', label: '全文没转出来', hover: 'PDF 文件损坏，字节已保存', group: 'gave_up', action: 'gave_up' }] }),
      mk('b', '悉尼海边徒步', { problems: [{ code: 'NEEDS_HUMAN.AUTH_FAILED', label: 'AI key 失效', hover: '接口拒绝了 key（401/403）：到设置里换一个', group: 'needs_you', action: 'needs_human' }] }),
      mk('c', '电饭煲鸡肉饭', { problems: [{ code: 'SKIPPED.NOT_CONFIGURED', label: '未配置', hover: '没配 AI', group: 'off', action: 'skipped' }] }),
      mk('d', '附件线索', { attachment: '线索', attachment_reason: '正文提到附件', problems: [{ code: 'PERMANENT.X', label: '疑似附件', hover: '重复', group: 'gave_up' }] }),
    ] };
}
function makeApp(V, plugin) {
  return { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
}
// 假 vault 的文件事件：catalog-view 用 app.vault.on('modify' / 'create') 监听
function watchable(V) {
  const handlers = {};
  V.vault.on = (name, fn) => { (handlers[name] = handlers[name] || []).push(fn); return { name, fn }; };
  return (name, p) => { for (const fn of handlers[name] || []) fn({ path: p }); };
}

async function catalogEntryTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const V = makeVault({
    [DATA]: JSON.stringify(catalogData()),
    [SYNC]: JSON.stringify({ state: 'blocked', code: 'NOT_LOGGED_IN', account: 'xhs', detail: '读取号掉登录', updated_at: '2026-10-02T04:00:00+10:00' }),
    [SUMMARY]: JSON.stringify({ updated_at: '2026-10-02T04:05:00+10:00', needs_human: 2, auto: 3, gave_up: 1, skipped: 7,
      sync: { state: 'blocked', code: 'NOT_LOGGED_IN', label: '需要登录', updated_at: '2026-10-02T04:05:00+10:00', last_success: '2026-10-02T04:00:00+10:00', new: 12, deferred: 85 } }),
  });
  const fire = watchable(V);
  let opened = 0, aliveChecks = 0;
  let syncLogs = 0;
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {}, openProblems() { opened++; }, openSyncLog() { syncLogs++; },
    refreshProblemSummary: async () => { aliveChecks++; return null; } };
  const app = makeApp(V, plugin);
  const A = dataviewBlock({ dom, app, code: LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js') });
  await A.run();
  const q = s => A.section.querySelector(s);
  const entry = q('.lbc-problems');
  assert.equal(entry.hidden, false);
  assert.equal(entry.querySelector('.lbc-prob-need').textContent, '2', '要你处理 = 橙色数字');
  assert.equal(entry.querySelector('.lbc-prob-other'), null, '1027b 她：不影响实际体验的不显示——已放弃 / 自动处理中都不计数，只数要你处理的');
  assert.ok(entry.title.startsWith('需要登录：读取号掉登录'), '悬停第一行 = 登记表标签 + 原因：' + entry.title);
  assert.ok(entry.title.includes('要你处理 2') && !/自动处理|已放弃/.test(entry.title), entry.title);
  assert.equal(q('.lbc-syncing').hidden, true);
  assert.equal(q('.lbc-syncinfo'), null, '第 6 批：标题下的同步概况行删了（挪进「本周同步情况」窗口）');
  assert.equal(q('.lbc-account-status'), null, '旧「!」没了');
  await entry.onclick();
  assert.equal(opened, 1, '点开 = 插件 openProblems()');
  console.log('PASS catalog entry: orange needs-you count + gray others, skipped not counted, hover from registry, no sync overview line, click → openProblems');

  // ── 卡片问题标 ──
  const card = id => A.section.querySelectorAll('.lbc-card').find(c => c._lbItem.id === id);
  const probs = id => card(id).querySelectorAll('.lbc-prob');
  assert.equal(probs('a').length, 1, '同一个标签只出一个');
  assert.equal(probs('a')[0].textContent, '全文没转出来');
  assert.equal(probs('a')[0].title, 'PDF 有打开密码，字节已保存\nPDF 文件损坏，字节已保存', '悬停把原因并起来');
  assert.ok(!probs('a')[0].classList.contains('is-need'), '已放弃是灰标');
  assert.ok(probs('b')[0].classList.contains('is-need'), '要你处理用醒目色');
  assert.equal(probs('b')[0].title, '接口拒绝了 key（401/403）：到设置里换一个');
  assert.equal(probs('c').length, 0, '未开启不上卡片');
  assert.equal(card('d').querySelectorAll('.lbc-attach').filter(b => b.textContent === '疑似附件').length, 1, '和附件标同名不重复');
  console.log('PASS cards: problem badges from it.problems (gray / needs-you highlighted), hover = Python hover, same label once, off group hidden, no duplicate of attachment badge');

  // ── 文件变了：只重画入口，不重建整页、不重读 catalog-data ──
  const wrap = q('.lbc-wrap'), firstCard = card('a');
  V.resetCounts();
  V.set(SUMMARY, JSON.stringify({ updated_at: '2026-10-02T05:00:00+10:00', needs_human: 0, auto: 1, gave_up: 1, skipped: 0,
    sync: { state: 'ready', updated_at: '2026-10-02T05:00:00+10:00', last_success: '2026-10-02T05:00:00+10:00' } }));
  fire('modify', SUMMARY); await tick(10);
  assert.equal(q('.lbc-wrap'), wrap, '整页没重建');
  assert.equal(card('a'), firstCard, '卡片没重建');
  assert.equal(V.reads[DATA] || 0, 0, '没重读 catalog-data');
  assert.equal(entry.querySelector('.lbc-prob-need'), null, '要你处理清零后橙色数字消失');
  assert.equal(entry.hidden, true, '1027b：只剩已放弃 / 自动处理的，入口不亮');
  // 新一次同步开始：sync-status.json 比 summary 新 → 「· 同步中…」
  V.set(SYNC, JSON.stringify({ state: 'running', pid: 999999, updated_at: '2026-10-02T06:00:00+10:00' }));
  fire('modify', SYNC); await tick(10);
  assert.equal(q('.lbc-syncing').hidden, false, '同步进行中仍显示「· 同步中…」');
  assert.equal(aliveChecks, 1, '插件没在跑任务时请 Python 核一次进程（problems summary）');
  fire('modify', SYNC); await tick(10);
  assert.equal(aliveChecks, 1, '每次打开页面最多核一次');
  // 批次 D · C14：「· 同步中」带上阶段，悬停看全句，点开同步记录
  const syncingAt = (progress, at) => { V.set(SYNC, JSON.stringify({ state: 'running', progress, updated_at: at })); fire('modify', SYNC); return tick(10); };
  await syncingAt('第 3/40 条收藏是新的…抓取中', '2026-10-02T06:01:00+10:00');
  assert.equal(q('.lbc-syncing').textContent, '· 同步中 3/40');
  assert.equal(q('.lbc-syncing').title, '第 3/40 条收藏是新的…抓取中\n点开看同步记录');
  await syncingAt('《咖啡》查附件 / 下附件中', '2026-10-02T06:02:00+10:00');
  assert.ok(q('.lbc-syncing').textContent.startsWith('· 同步中 · 《咖啡》查附件'), q('.lbc-syncing').textContent);
  assert.ok(q('.lbc-syncing').textContent.endsWith('…'), '超长加 …');
  await syncingAt('', '2026-10-02T06:03:00+10:00');
  assert.equal(q('.lbc-syncing').textContent, '· 同步中…');
  assert.equal(q('.lbc-syncing').tagName, 'BUTTON');
  await q('.lbc-syncing').onclick({}); await tick(5);
  assert.equal(syncLogs, 1, '点「同步中」= 打开同步记录（和「更新」同一个入口）');  // Python 改判进程已死（summary 更新得更晚）→ 不再显示同步中；页面自己不查 pid
  V.set(SUMMARY, JSON.stringify({ updated_at: '2026-10-02T06:30:00+10:00', needs_human: 0, auto: 0, gave_up: 0, skipped: 2,
    sync: { state: 'failed', code: 'INTERRUPTED', updated_at: '2026-10-02T06:30:00+10:00' } }));
  fire('modify', SUMMARY); await tick(10);
  assert.equal(q('.lbc-syncing').hidden, true, '以 summary.sync 的改判为准');
  assert.equal(entry.hidden, true, '都为 0（未开启不算）不显示');
  assert.equal(V.reads[DATA] || 0, 0);
  // Dataview 重跑：同一份 DOM 挂回，入口还在
  await A.rerun();
  assert.equal(q('.lbc-wrap'), wrap);
  assert.ok(!/process\.kill/.test(asset('catalog-view.js')), '页面不再自己查 pid');
  assert.ok(!/NOT_LOGGED_IN\s*:\s*'需要登录'/.test(asset('catalog-view.js')), '页面里没有自己的状态文案表');
  // 另开一页：插件在跑同步时不去核；没在跑时核一次，Python 改判后入口跟着变
  {
    delete globalThis.__lbState;
    const V2 = makeVault({ [DATA]: JSON.stringify(catalogData()), [SYNC]: JSON.stringify({ state: 'running', pid: 1, updated_at: '2026-10-02T06:00:00+10:00' }) });
    const fire2 = watchable(V2);
    let checks = 0;
    const p2 = { settings: { hiddenCats: [] }, running: '同步收藏', openLibraryPage() {},
      refreshProblemSummary: async () => { checks++; V2.set(SUMMARY, JSON.stringify({ updated_at: '2026-10-02T07:00:00+10:00', needs_human: 0, auto: 1, gave_up: 0, skipped: 0, sync: { state: 'failed', code: 'INTERRUPTED', updated_at: '2026-10-02T07:00:00+10:00' } })); return { ok: true }; } };
    const B = dataviewBlock({ dom, app: makeApp(V2, p2), code: LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js') });
    await B.run(); await tick(10);
    assert.equal(checks, 0, '插件正在跑同步时不核');
    assert.equal(B.section.querySelector('.lbc-syncing').hidden, false);
    p2.running = null; await B.rerun(); fire2('modify', SYNC); await tick(10);
    assert.equal(checks, 1);
    assert.equal(B.section.querySelector('.lbc-syncing').hidden, true, '核完重读 summary：不再显示同步中');
    assert.equal(B.section.querySelector('.lbc-prob-other'), null, '1019：被打断属自动处理中，不亮数字');
  }
  console.log('PASS file watch: summary / sync-status change repaints entry only (no rebuild, no catalog reread); running shown; INTERRUPTED from summary wins; hidden at 0');
}

// ── problems-ui.js：问题列表 Modal ──
function fakeObsidian(dom, notices) {
  class Modal {
    constructor(app) { this.app = app; this.modalEl = dom.document.body.createEl('div', { cls: 'modal' }); this.contentEl = this.modalEl.createEl('div', { cls: 'modal-content' }); }
    open() { this.opened = Promise.resolve(this.onOpen && this.onOpen()); }
    close() { this.closed = true; this.onClose && this.onClose(); this.modalEl.remove(); }
  }
  return { Modal, Notice: class { constructor(m) { notices.push(m); } } };
}
const LIST = {
  ok: true, code: '', message: '', summary: { needs_human: 2, auto: 1, gave_up: 1, skipped: 1 },
  problems: [
    { ts: '2026-10-02T04:01:00+10:00', key: 'login||NOT_LOGGED_IN', category: 'account', step: 'login', item_id: null, title: null, code: 'NEEDS_HUMAN.NOT_LOGGED_IN', reason: '读取号掉登录', action: 'needs_human', count: 1, resolved_at: null, label: '需要登录', hover: '小红书掉登录', group: 'needs_you' },
    { ts: '2026-10-02T04:02:00+10:00', key: 'sync.favorites||CAPTCHA_REQUIRED', category: 'account', step: 'sync.favorites', item_id: null, title: null, code: 'NEEDS_HUMAN.CAPTCHA_REQUIRED', reason: '', action: 'needs_human', count: 1, resolved_at: null, label: '需要验证', hover: '要安全验证', group: 'needs_you' },
    { ts: '2026-10-02T04:03:00+10:00', key: 'attachments.convert|a|NETWORK', category: 'api', step: 'attachments.convert', item_id: 'a', title: '悉尼咖啡地图', code: 'TRANSIENT.NETWORK', reason: 'OCR 服务连不上', action: 'retry_later', next_at: '2026-10-03T04:00:00+10:00', count: 3, resolved_at: null, label: '网络不通', hover: 'OCR 服务连不上（10-03 04:00 再试）', group: 'auto' },
    { ts: '2026-10-02T04:04:00+10:00', key: 'attachments.convert|a|PDF_ENCRYPTED', category: 'other', step: 'attachments.convert', item_id: 'a', title: '悉尼咖啡地图', code: 'PERMANENT.PDF_ENCRYPTED', reason: 'PDF 有打开密码', action: 'gave_up', count: 1, resolved_at: null, label: '全文没转出来', hover: 'PDF 有打开密码，字节已保存', group: 'gave_up' },
    { ts: '2026-10-02T04:05:00+10:00', key: 'enrich.summary||NOT_CONFIGURED', category: 'off', step: 'enrich.summary', item_id: null, title: null, code: 'SKIPPED.NOT_CONFIGURED', reason: '没配摘要模型', action: 'skipped', count: 4, resolved_at: null, label: '未配置', hover: '没配摘要模型', group: 'off' },
    { ts: '2026-10-01T04:05:00+10:00', key: 'x', step: 'embed', code: 'TRANSIENT.NETWORK', action: 'retry_later', count: 1, resolved_at: '2026-10-02T01:00:00+10:00', label: '网络不通', group: 'auto' },
  ],
};
function makeProblemsPlugin(dom, replies) {
  const calls = [], fixes = [];
  const workspace = makeWorkspace();
  const plugin = {
    app: { workspace, vault: { adapter: { read: async () => JSON.stringify(catalogData()) } }, setting: { open() { fixes.push('settings'); }, openTabById() {} } },
    manifest: { id: 'link-brain-actions', version: '0.4.2', dir: PLUGIN_DIR },
    catalogCache: null,
    lbPath: p => p,
    async runPy(args, opts) {
      calls.push(args.slice(2));
      const r = replies[args[3]];
      if (typeof r === 'function') return r(args, opts);
      return { code: 0, json: r, out: '', err: '', timedOut: false };
    },
    async fixFromCatalog(kind) { fixes.push(kind); },
    openAccountStatus() { fixes.push('panel'); },
  };
  return { plugin, calls, fixes, workspace };
}
const clip = { text: null, fail: null };
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { clipboard: { writeText: async t => { if (clip.fail) throw new Error(clip.fail); clip.text = t; } } } });

async function modalTests() {
  const dom = makeDom(), notices = [];
  const obsidian = fakeObsidian(dom, notices);
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'problems-ui.js'));
  const { plugin, calls, fixes, workspace } = makeProblemsPlugin(dom, { list: LIST, export: { ok: true, text: '# Link Brain 诊断信息（已脱敏）\n- 插件版本：0.4.2' } });
  const ui = factory(obsidian, plugin);
  const m = ui.open(); await m.opened;
  const c = m.contentEl;
  assert.deepEqual(calls[0], ['problems', 'list']);
  const groups = c.querySelectorAll('.lb-problems-group');
  assert.deepEqual(groups.map(g => g.querySelector('h3').textContent), ['登录验证 · 2', 'AI 接口 · 1', '其他 · 1', '未开启 · 1'], '1017 按是什么事分区、顺序固定；已解决的不列');
  const rows = c.querySelectorAll('.lb-problem');
  const text = r => r.querySelector('.lb-problem-line').textContent;
  assert.match(text(rows[0]), /^10-02 \d\d:\d\dlogin需要登录等你处理$/, '没有标题时用 step：' + text(rows[0]));
  assert.ok(text(rows[2]).includes('悉尼咖啡地图') && text(rows[2]).includes('网络不通') && /待修复（10-0[23] \d\d:\d\d）/.test(text(rows[2])) && !text(rows[2]).includes('下晚再试') && text(rows[2]).includes('3 次'), text(rows[2]));
  assert.ok(text(rows[3]).includes('全文没转出来') && text(rows[3]).includes('放弃'), text(rows[3]));
  assert.ok(text(rows[4]).includes('未开启') && text(rows[4]).includes('4 次'));
  assert.equal(rows[2].querySelector('.lb-problem-why').textContent, 'OCR 服务连不上（10-03 04:00 再试）', '原因一句话来自 Python hover');
  // 按钮：登录类「扫码登录」、验证类「打开验证」；有 item_id 的「查看」；其余没有按钮
  const btns = r => r.querySelectorAll('button').map(b => b.textContent);
  assert.deepEqual(btns(rows[0]), ['扫码登录']);
  assert.deepEqual(btns(rows[1]), ['打开验证']);
  assert.deepEqual(btns(rows[2]), ['查看']);
  assert.deepEqual(btns(rows[4]), []);
  await rows[0].querySelector('.lb-problem-fix').onclick();
  assert.deepEqual(fixes, ['login'], '「扫码登录」= fixFromCatalog(login)');
  assert.deepEqual(calls.at(-1), ['problems', 'list'], '修完重读列表');
  await c.querySelectorAll('.lb-problem')[1].querySelector('.lb-problem-fix').onclick();
  assert.deepEqual(fixes, ['login', 'verify']);
  // 查看 → 同一窗格打开那篇
  await c.querySelectorAll('.lb-problem')[2].querySelector('.lb-problem-open').onclick();
  assert.deepEqual(workspace.opened.at(-1), ['Web/a.md', '', false]);
  assert.ok(m.closed, '打开那篇后关掉窗口');
  console.log('PASS problems modal: 4 groups in order, row = time · title/step · label · action · count, why from hover, 扫码登录 / 打开验证 → fixFromCatalog, 查看 opens note');

  // ── 复制报错 ──
  const m2 = ui.open(); await m2.opened;
  await m2.contentEl.querySelector('.lb-problems-copy').onclick();
  assert.deepEqual(calls.at(-1), ['problems', 'export', '--plugin-version', '0.4.2'], '带上 manifest.version');
  assert.ok(clip.text.startsWith('# Link Brain 诊断信息'));
  assert.equal(notices.at(-1), '已复制诊断信息（已去掉密钥和本机路径）');
  clip.fail = 'Document is not focused';
  await m2.contentEl.querySelector('.lb-problems-copy').onclick();
  assert.equal(notices.at(-1), '复制报错没成功：剪贴板写不进去（Document is not focused）');
  clip.fail = null;
  const bad = makeProblemsPlugin(dom, { list: { ok: true, problems: [] }, export: () => { throw new Error('找不到 Python。'); } });
  const ui2 = factory(obsidian, bad.plugin);
  assert.equal(await ui2.copyReport(), false);
  assert.equal(notices.at(-1), '复制报错没成功：找不到 Python。');
  const bad2 = makeProblemsPlugin(dom, { export: { ok: false, message: '问题记录读不了' } });
  assert.equal(await factory(obsidian, bad2.plugin).copyReport(), false);
  assert.equal(notices.at(-1), '复制报错没成功：问题记录读不了');
  console.log('PASS copy report: export --plugin-version → clipboard + 已复制诊断信息（已去掉密钥和本机路径）; runPy / ok:false / clipboard failures say why');

  // ── 空列表 / 读不到 ──
  const m3 = ui2.open(); await m3.opened;
  assert.equal(m3.contentEl.querySelector('.lb-problems-empty').textContent, '没有问题');
  const broken = makeProblemsPlugin(dom, { list: () => { throw new Error('后台命令超过 1 分钟没有结果，已停止。'); } });
  const m4 = factory(obsidian, broken.plugin).open(); await m4.opened;
  assert.equal(m4.contentEl.querySelector('.lb-problems-status').textContent, '读不到问题列表：后台命令超过 1 分钟没有结果，已停止。');
  console.log('PASS problems modal: empty → 没有问题; runPy failure shown as-is');
}

// ── 插件 main.js：readSyncStatus / fixFromCatalog / openProblems / 文案来源 ──
async function pluginTests() {
  const dom = makeDom(), notices = [];
  const fakeObs = fakeObsidian(dom, notices);
  let pidChecks = 0;
  const proc = Object.create(process); proc.kill = () => { pidChecks++; };
  const context = { module: { exports: {} }, process: proc, setTimeout, clearTimeout, console, window: { confirm: () => false },
    require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: fakeObs.Modal, Notice: fakeObs.Notice }
      : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8'), context);
  const Plugin = context.module.exports;
  const files = {
    [SYNC]: JSON.stringify({ state: 'running', pid: 4242, message: '正在同步收藏：第 3 篇', updated_at: '2026-10-02T04:00:00+10:00', last_success: '2026-10-01T04:30:00+10:00' }),
    [SUMMARY]: JSON.stringify({ updated_at: '2026-10-02T05:00:00+10:00', needs_human: 0, auto: 1, gave_up: 0, skipped: 0,
      sync: { state: 'failed', code: 'INTERRUPTED', message: '上次同步中途被打断', updated_at: '2026-10-02T05:00:00+10:00' } }),
  };
  const p = new Plugin();
  p.app = { vault: { adapter: { getBasePath: () => ROOT, read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; } } }, workspace: makeWorkspace() };
  p.manifest = { id: 'link-brain-actions', version: '0.4.2', dir: PLUGIN_DIR };
  p.lbPath = x => x;
  let st = await p.readSyncStatus();
  assert.equal(st.state, 'failed'); assert.equal(st.code, 'INTERRUPTED'); assert.equal(st.last_success, '2026-10-01T04:30:00+10:00', '旧键保留');
  assert.equal(pidChecks, 0, '插件不再自己 process.kill 查 pid');
  delete files[SUMMARY];
  st = await p.readSyncStatus();
  assert.equal(st.state, 'running', '没有 summary 时原样用 sync-status.json');
  assert.equal(Plugin.mergeSyncStatus({ state: 'running', updated_at: '2026-10-02T06:00:00Z' }, { sync: { state: 'failed', updated_at: '2026-10-02T05:00:00Z' } }).state, 'running', 'sync-status 更新时用它');
  // 文案：裸码 / 全码 / 类兜底都从登记表取
  assert.equal(Plugin.registryEntry(REGISTRY, 'NOT_LOGGED_IN').label, '需要登录');
  assert.equal(Plugin.registryEntry(REGISTRY, 'TRANSIENT.HTTP_5XX').label, '稍后自动重试');
  assert.equal(Plugin.registryEntry(REGISTRY, ''), null);
  files[DATA] = JSON.stringify({ state_registry: REGISTRY });
  assert.equal((await p.stateRegistry())['NEEDS_HUMAN.CAPTCHA_REQUIRED'].label, '需要验证');
  const src = fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8');
  assert.ok(!/process\.kill\(s\.pid/.test(src), 'main.js 里没有 pid 自判');
  assert.ok(!src.includes("captcha: ['需要验证'"), '账号卡片的状态字不再自己写');
  // fixFromCatalog(kind)：问题列表按钮直接指定；不指定仍按同步状态判
  const routes = [];
  p.loginAccount = async () => { routes.push('login'); return { state: 'ready' }; };
  p.openVerify = async () => { routes.push('verify'); return {}; };
  p.openAccountStatus = () => routes.push('panel');
  p.syncNow = () => routes.push('sync');
  await p.fixFromCatalog('verify');
  await p.fixFromCatalog('login');
  files[SYNC] = JSON.stringify({ state: 'blocked', code: 'CAPTCHA_REQUIRED', account: 'xhs' });
  await p.fixFromCatalog();
  assert.deepEqual(routes, ['verify', 'login', 'sync', 'verify']);
  // openProblems：按需加载 problems-ui.js，走 runPy problems list
  const ran = [];
  p.runPy = async args => { ran.push(args.slice(2)); return { code: 0, json: { ok: true, problems: [] } }; };
  const m = p.openProblems(); await m.opened;
  assert.deepEqual(ran[0], ['problems', 'list']);
  await Promise.all([p.refreshProblemSummary(), p.refreshProblemSummary()]);
  assert.equal(JSON.stringify(ran.slice(1)), JSON.stringify([['problems', 'summary']]),'核对同步进程走 problems summary，并发合并成一次');
  assert.equal(m.contentEl.querySelector('.lb-problems-empty').textContent, '没有问题');
  console.log('PASS plugin: sync status from problems-summary (no pid check), registry lookup for labels, fixFromCatalog(kind), openProblems loads problems-ui.js');
}

// ── 10-04 当场自愈：「现在修」/「全部修一遍」/ Python 填好的状态一句话 ──
async function repairTests() {
  const dom = makeDom(), notices = [];
  const obsidian = fakeObsidian(dom, notices);
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'problems-ui.js'));
  const rows = [
    { ts: '2026-10-04T04:01:00+10:00', key: 'login||CAPTCHA_REQUIRED', step: 'login', code: 'NEEDS_HUMAN.CAPTCHA_REQUIRED', action: 'needs_human', count: 1, resolved_at: null, label: '需要验证', hover: '要安全验证', group: 'needs_you', repairable: false, repair_kind: 'human', status_text: '' },
    { ts: '2026-10-04T04:02:00+10:00', key: 'enrich.summary||STUCK', step: 'enrich.summary', code: 'NEEDS_HUMAN.STUCK', action: 'needs_human', count: 1, resolved_at: null, label: '连续几天没修好', hover: '连续 3 天', group: 'needs_you', repairable: true, repair_minutes: 10, status_text: '待修复：点「现在修」当场修（约 10 分钟）' },
    { ts: '2026-10-04T04:03:00+10:00', key: 'embed||NETWORK', step: 'embed', step_label: '语义索引', code: 'TRANSIENT.NETWORK', action: 'retry_later', count: 1, resolved_at: null, label: '网络不通', hover: '连不上', group: 'auto', repairable: true, repair_minutes: 4, status_text: '当场修过没好（10-04 04:30）：可以再点「现在修」', repair_state: 'failed', repair_note: '已试：重建语义索引（04:30）；没好：连不上；下一步：到设置里确认 key' },
    { ts: '2026-10-04T04:04:00+10:00', key: 'sync.favorites||FAVORITES_SUSPICIOUS', step: 'sync.favorites', step_label: '收藏同步', code: 'TRANSIENT.FAVORITES_SUSPICIOUS', action: 'retry_later', count: 1, resolved_at: null, label: '收藏只读到一截', hover: '收藏只读到一截：读回 540 条', group: 'auto', repairable: false, repair_kind: 'wait', status_text: '等到 10-05 04:00：今晚已经读到一截收藏列表，同一晚再读容易撞安全验证' },
    { ts: '2026-10-04T04:05:00+10:00', key: 'vision.refine|xhs-a|MODEL_OUTPUT_INVALID', step: 'vision.refine', item_id: 'a', title: '悉尼咖啡地图', code: 'PERMANENT.MODEL_OUTPUT_INVALID', action: 'gave_up', count: 1, resolved_at: null, label: 'AI 结果不可用', hover: '复读', group: 'gave_up', repairable: true, repair_minutes: 4, repairing: true, status_text: '正在修 / 预计 4 分钟' },
  ];
  let release;
  const gate = new Promise(r => { release = r; });
  const replies = {
    list: { ok: true, problems: rows },
    repair: async (args) => { await gate; return { code: 0, json: { ok: args.includes('--key'), message: args.includes('--key') ? '自愈：修好 1 条' : '自愈：修好 2 条，还剩 1 条（每条都写了试过什么、为什么没好、下一步）', results: [{ key: 'x', status: 'resolved' }] }, out: '', err: '', timedOut: false }; },
  };
  const { plugin, calls } = makeProblemsPlugin(dom, replies);
  const runs = [];
  const orig = plugin.runPy;
  plugin.runPy = (args, opts) => { runs.push(opts); return orig.call(plugin, args, opts); };
  const ui = factory(obsidian, plugin);
  const m = ui.open(); await m.opened;
  const c = m.contentEl;
  const all = c.querySelector('.lb-problems-repair-all');
  assert.ok(all && all.textContent === '全部修一遍', '顶部有「全部修一遍」');
  const list = c.querySelectorAll('.lb-problem');
  const btnTexts = r => r.querySelectorAll('button').map(b => b.textContent);
  assert.deepEqual(btnTexts(list[0]), ['打开验证'], '风控 / 验证类：只有人工按钮，没有「现在修」');
  assert.deepEqual(btnTexts(list[1]), ['现在修'], '「连续几天没修好」不是风控：给「现在修」');
  assert.deepEqual(btnTexts(list[2]), ['现在修']);
  assert.deepEqual(btnTexts(list[3]), [], '必须等的（今晚已读到一截）：不给「现在修」');
  const line = r => r.querySelector('.lb-problem-line').textContent;
  assert.ok(line(list[3]).includes('等到 10-05 04:00'), '要等的写清等到几点：' + line(list[3]));
  assert.ok(!c.textContent.includes('下晚再试'), '面板上不再出现「下晚再试」');
  assert.equal(list[2].querySelector('.lb-problem-repair-note').textContent, rows[2].repair_note, '修不好：试过什么、为什么没好、下一步');
  const busy = list[4].querySelector('.lb-problem-repair');
  assert.ok(busy.disabled && busy.textContent === '正在修 / 预计 4 分钟', '后台正在修的：按钮显示进行中');
  // 点「现在修」：进行中显示「正在修 / 预计 N 分钟」，跑完提示结果、重读列表
  const b = list[2].querySelector('.lb-problem-repair');
  const pending = b.onclick();
  assert.ok(b.disabled && b.textContent === '正在修 / 预计 4 分钟', b.textContent);
  release();
  await pending;
  const repairCall = calls.find(a => a[1] === 'repair');
  assert.deepEqual(repairCall, ['problems', 'repair', '--key', 'embed||NETWORK']);
  assert.ok(runs.some(o => o && o.timeoutMs >= 20 * 60000), '单条修复的超时长于后端 20 分钟预算');
  assert.ok(notices.some(n => String(n).startsWith('自愈：修好 1 条')), notices.join(' | '));
  assert.deepEqual(calls.at(-1), ['problems', 'list'], '修完重读列表');
  // 全部修一遍
  const m2 = ui.open(); await m2.opened;
  await m2.contentEl.querySelector('.lb-problems-repair-all').onclick();
  assert.deepEqual(calls.filter(a => a[1] === 'repair').at(-1), ['problems', 'repair']);
  assert.ok(notices.some(n => String(n).includes('还剩 1 条')));
  // 后端报错：如实提示
  const bad = makeProblemsPlugin(dom, { list: { ok: true, problems: rows }, repair: () => { throw new Error('找不到 Python。'); } });
  const m3 = factory(obsidian, bad.plugin).open(); await m3.opened;
  await m3.contentEl.querySelector('.lb-problems-repair-all').onclick();
  assert.equal(notices.at(-1), '修复没跑完：找不到 Python。');
  console.log('PASS problems repair: 现在修 per non-risk row (STUCK too, not captcha/login), waits show 等到几点, running shows 正在修 / 预计 N 分钟, repair_note shown, 全部修一遍, failures honest, no 下晚再试');
}

(async () => {
  await catalogEntryTests();
  await modalTests();
  await repairTests();
  await pluginTests();
})().catch(e => { console.error(e); process.exitCode = 1; });

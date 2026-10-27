// 1008（L6）：问题面板 + 账号行的前端部分。真跑 problems-ui.js 和插件 main.js，假 DOM / 假 runPy，不起真进程（§7.5）。断言：
//   B2 隐藏：已放弃的行有「隐藏」、组标题旁「全部隐藏（N）」（dismiss --group gave_up，不弹确认框、提示可恢复）；等你处理 / 正在自动处理没有；
//      「已隐藏 · N」默认收起，展开后「恢复显示」调 undismiss 再重读；已放弃的按钮叫「再试一次」
//   C20：第二次打开时第一帧就按缓存画好（runPy 还挂着、没有「正在读取」）；「现在修」结束只换那一行（修好的标「✓ 已修好」、
//      别的行还是同一个元素、行数不变）；后台重读没变化一行不动
//   B1：关窗后熔断还在（verify_result）才给「没看到验证，恢复」；有证据的给「查看截图」；restoreHold 先确认再发 --clear-hold --by-owner
//   1011：已解决的 / 轻微的（minor：楼中楼只缺 ≤2 条）不进列表、不进组计数；「✓ 已修好」停一会儿后整行拿掉
//   X8：AUTH_FAILED 行「打开设置」→ openSetupPage('ai')
//   S4：账号行默认浅查（--shallow），同一时刻只跑一个，10 分钟内再画 0 次进程、显示「N 分钟前确认」；「重新检查」深查；
//      openVerify 带 --wait；设置页同步行如实写「上次 HH:MM 在读收藏时判到验证」
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { ROOT, makeDom, makeWorkspace } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

function fakeObsidian(dom, notices) {
  class Modal {
    constructor(app) { this.app = app; this.modalEl = dom.document.body.createEl('div', { cls: 'modal' }); this.contentEl = this.modalEl.createEl('div', { cls: 'modal-content' }); }
    open() { this.opened = Promise.resolve(this.onOpen && this.onOpen()); }
    close() { this.closed = true; this.onClose && this.onClose(); this.modalEl.remove(); }
  }
  return { Modal, Notice: class { constructor(m) { notices.push(m); } } };
}

const row = (o) => ({ ts: '2026-10-08T04:01:00+11:00', resolved_at: null, count: 1, ...o });
const ROWS = () => [
  row({ key: 'login||CAPTCHA_REQUIRED', category: 'account', step: 'login', code: 'NEEDS_HUMAN.CAPTCHA_REQUIRED', action: 'needs_human', label: '需要验证', hover: '要验证', group: 'needs_you',
        verify_result: 'no_captcha_seen', evidence_id: '20261008-051957' }),
  row({ key: 'ai.summary||AUTH_FAILED', category: 'api', step: 'ai.summary', code: 'NEEDS_HUMAN.AUTH_FAILED', action: 'needs_human', label: 'AI key 失效', hover: 'key 坏了', group: 'needs_you', repairable: true, repair_minutes: 10 }),
  row({ key: 'attachments.recheck|xhs-p|PROBE_FAILED', category: 'fetch', step: 'attachments.recheck', item_id: 'xhs-p', code: 'TRANSIENT.PROBE_FAILED', action: 'retry_later', label: '附件没查清', hover: '没查清', group: 'auto', repairable: false, status_text: '排在游客补查第 3 篇（不用你的号），预计 10-09 轮到' }),
  row({ key: 'embed||NETWORK', category: 'api', step: 'embed', code: 'TRANSIENT.NETWORK', action: 'retry_later', label: '网络不通', hover: '连不上', group: 'auto', repairable: true, repair_minutes: 4, status_text: '待修复' }),
  row({ key: 'vision.refine|xhs-a|MODEL_OUTPUT_INVALID', category: 'api', step: 'vision.refine', item_id: 'xhs-a', title: '合成笔记 A', code: 'PERMANENT.MODEL_OUTPUT_INVALID', action: 'gave_up', label: 'AI 结果不可用', hover: '复读', group: 'gave_up', repairable: true, repair_minutes: 4, dismissable: true, count: 2, status_text: '同样的原因已失败 2 次' }),
  row({ key: 'vision.refine|xhs-b|MODEL_OUTPUT_INVALID', category: 'api', step: 'vision.refine', item_id: 'xhs-b', title: '合成笔记 B', code: 'PERMANENT.MODEL_OUTPUT_INVALID', action: 'gave_up', label: 'AI 结果不可用', hover: '复读', group: 'gave_up', repairable: true, repair_minutes: 4, dismissable: true }),
  row({ key: 'vision.refine|xhs-c|MODEL_OUTPUT_INVALID', category: 'api', step: 'vision.refine', item_id: 'xhs-c', title: '合成笔记 C', code: 'PERMANENT.MODEL_OUTPUT_INVALID', action: 'gave_up', label: 'AI 结果不可用', hover: '复读', group: 'gave_up', dismissable: true, hidden: true, hidden_repeats: 2 }),
  // 1011：这两条不该出现在面板上（老后端 / --all 也可能带回来）
  row({ key: 'comments.fill|xhs-m|COMMENTS_INCOMPLETE', category: 'fetch', step: 'comments.fill', item_id: 'xhs-m', title: '合成笔记 M', code: 'PERMANENT.COMMENTS_INCOMPLETE', action: 'gave_up', label: '评论没补全', hover: '楼中楼还缺 1 条', group: 'gave_up', dismissable: true, minor: true }),
  row({ key: 'videos.transcribe|xhs-r|NO_SPEECH', category: 'other', step: 'videos.transcribe', item_id: 'xhs-r', title: '合成笔记 R', code: 'PERMANENT.NO_SPEECH', action: 'gave_up', label: '没人声', hover: '', group: 'gave_up', resolved_at: '2026-10-08T05:00:00+11:00' }),
];

function makePlugin(state) {
  const calls = [], fixes = [];
  const plugin = {
    app: { workspace: makeWorkspace(), vault: { adapter: { read: async () => '{"items":[]}' } }, setting: { open() {}, openTabById() {} } },
    manifest: { id: 'link-brain-actions', version: '0.4.2', dir: PLUGIN_DIR },
    lbPath: p => p,
    async runPy(args, opts) {
      const sub = args.slice(2);
      calls.push(sub);
      if (state.gate && sub[1] === 'list') await state.gate;
      const r = state.replies[sub[1]];
      const json = typeof r === 'function' ? await r(sub) : r;
      return { code: 0, json, out: '', err: '', timedOut: false };
    },
    async fixFromCatalog(kind) { fixes.push(kind); },
    openAccountStatus() { fixes.push('panel'); },
    openSetupPage(tab) { fixes.push('setup:' + tab); },
    async restoreHold() { fixes.push('restore'); },
    async openRiskEvidence(id) { fixes.push('evidence:' + id); },
  };
  return { plugin, calls, fixes };
}

async function panelTests() {
  const dom = makeDom(), notices = [];
  const obsidian = fakeObsidian(dom, notices);
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'problems-ui.js'));
  let rows = ROWS();
  const state = { replies: {
    list: () => ({ ok: true, summary: {}, problems: rows }),
    dismiss: sub => ({ ok: true, code: '', message: sub.includes('--group') ? '已隐藏 2 条，可在列表最下面「已隐藏」里恢复' : '已隐藏 1 条，可在列表最下面「已隐藏」里恢复' }),
    undismiss: () => ({ ok: true, code: '', message: '已恢复显示' }),
    repair: () => { rows = rows.filter(r => r.key !== 'embed||NETWORK'); return { ok: true, message: '自愈：修好 1 条', results: [{ key: 'embed||NETWORK', status: 'resolved' }] }; },
  } };
  const { plugin, calls, fixes } = makePlugin(state);
  const ui = factory(obsidian, plugin);
  const m = ui.open(); await m.opened;
  const c = m.contentEl;
  const btns = r => r.querySelectorAll('button').map(b => b.textContent);
  const rowOf = key => c.querySelectorAll('.lb-problem').find(r => r.getAttribute('data-key') === key);
  // 分组 + 按钮
  const heads = c.querySelectorAll('.lb-problems-group h3').map(h => h.textContent);
  assert.deepEqual(heads, ['登录验证 · 1', 'AI 接口 · 4', '拉取没拿全 · 1'], '1017 按是什么事分区；隐藏的不计入分区；已解决 / 轻微的不计也不列');
  assert.ok(!heads.some(h => h.startsWith('已放弃')), '1017：不再有「已放弃」分区');
  assert.equal(rowOf('comments.fill|xhs-m|COMMENTS_INCOMPLETE'), undefined, '轻微的（楼中楼只缺 1 条）不列');
  assert.equal(rowOf('videos.transcribe|xhs-r|NO_SPEECH'), undefined, '已解决的不列');
  assert.deepEqual(btns(rowOf('login||CAPTCHA_REQUIRED')), ['打开验证', '没看到验证，恢复', '查看截图'], '关窗后熔断还在：多一个恢复；有证据：查看截图');
  assert.deepEqual(btns(rowOf('attachments.recheck|xhs-p|PROBE_FAILED')), ['查看'], '正在自动处理的不能隐藏');
  assert.deepEqual(btns(rowOf('vision.refine|xhs-a|MODEL_OUTPUT_INVALID')), ['再试一次', '隐藏', '查看'], '已放弃：「再试一次」+「隐藏」');
  assert.ok(rowOf('attachments.recheck|xhs-p|PROBE_FAILED').textContent.includes('预计 10-09'), '状态句照 Python 写的');
  // X8：打开设置直达 AI 分页
  await rowOf('ai.summary||AUTH_FAILED').querySelectorAll('button').find(b => b.textContent === '打开设置').onclick();
  assert.ok(fixes.includes('setup:ai'));
  await rowOf('login||CAPTCHA_REQUIRED').querySelector('.lb-problem-restore').onclick();
  await rowOf('login||CAPTCHA_REQUIRED').querySelector('.lb-problem-evidence').onclick();
  assert.ok(fixes.includes('restore') && fixes.includes('evidence:20261008-051957'));
  // 已隐藏区：默认收起；恢复显示 → undismiss 再重读
  const toggle = c.querySelector('.lb-problems-hidden-toggle');
  assert.equal(toggle.textContent, '已隐藏 · 1');
  assert.equal(c.querySelector('.lb-problems-hidden-list').hidden, true, '默认收起');
  toggle.onclick();
  assert.equal(c.querySelector('.lb-problems-hidden-list').hidden, false);
  const hiddenRow = rowOf('vision.refine|xhs-c|MODEL_OUTPUT_INVALID');
  assert.ok(hiddenRow.textContent.includes('隐藏后又出现 2 次'));
  assert.deepEqual(btns(hiddenRow), ['恢复显示', '查看']);
  await hiddenRow.querySelector('.lb-problem-undismiss').onclick();
  assert.deepEqual(calls.filter(a => a[1] === 'undismiss').at(-1), ['problems', 'undismiss', '--key', 'vision.refine|xhs-c|MODEL_OUTPUT_INVALID']);
  assert.deepEqual(calls.at(-1), ['problems', 'list'], '恢复后重读');
  // 全部隐藏：不弹确认，提示可恢复
  const all = c.querySelector('.lb-problems-hide-all');
  assert.equal(all.textContent, '全部隐藏（2）');
  await all.onclick();
  assert.deepEqual(calls.filter(a => a[1] === 'dismiss').at(-1), ['problems', 'dismiss', '--category', 'api'], '1017：只隐藏这一区能隐藏的');
  assert.ok(notices.at(-1).includes('可在列表最下面「已隐藏」里恢复'));
  await rowOf('vision.refine|xhs-b|MODEL_OUTPUT_INVALID').querySelector('.lb-problem-dismiss').onclick();
  assert.deepEqual(calls.filter(a => a[1] === 'dismiss').at(-1), ['problems', 'dismiss', '--key', 'vision.refine|xhs-b|MODEL_OUTPUT_INVALID']);
  console.log('PASS problems hide: gave_up rows 再试一次 + 隐藏, 全部隐藏（N）→ dismiss --group gave_up (no confirm, says recoverable), 已隐藏 · N collapsed → 恢复显示 → undismiss + reload; needs_you / auto rows not hideable; restore / evidence / X8 setup:ai');

  // C20：修完只换那一行
  const before = c.querySelectorAll('.lb-problem');
  const keep = rowOf('ai.summary||AUTH_FAILED');
  const target = rowOf('embed||NETWORK');
  ui._internals.timing.resolvedLingerMs = 30;
  await target.querySelector('.lb-problem-repair').onclick();
  const after = c.querySelectorAll('.lb-problem');
  assert.equal(after.length, before.length, '行数不变（修好的不删，免得跳动）');
  assert.ok(target.hasClass('is-resolved') && target.textContent.includes('✓ 已修好') && !target.querySelector('.lb-problem-btns'));
  assert.equal(rowOf('ai.summary||AUTH_FAILED'), keep, '别的行还是同一个元素');
  assert.equal(c.querySelectorAll('.lb-problems-group h3')[1].textContent, 'AI 接口 · 3', '组标题计数跟着改');
  // 1011：「✓ 已修好」停一会儿后整行拿掉（已解决的不留在列表里），别的行照旧是同一个元素
  await tick(80);
  assert.equal(rowOf('embed||NETWORK'), undefined, '修好的那一行停一会儿后拿掉');
  assert.equal(c.querySelectorAll('.lb-problem').length, before.length - 1);
  assert.equal(rowOf('ai.summary||AUTH_FAILED'), keep);
  assert.equal(c.querySelectorAll('.lb-problems-group h3')[1].textContent, 'AI 接口 · 3');
  // 第二次打开：第一帧就按缓存画好，标「正在刷新…」，没有「正在读取」
  let release; state.gate = new Promise(r => { release = r; });
  const m2 = ui.open();
  assert.ok(m2.contentEl.querySelectorAll('.lb-problem').length > 0, '缓存先画');
  assert.ok(!m2.contentEl.textContent.includes('正在读取'));
  assert.equal(m2.contentEl.querySelector('.lb-problems-refresh').textContent, '正在刷新…');
  const firstRow = m2.contentEl.querySelector('.lb-problem');
  release(); await m2.opened;
  assert.equal(m2.contentEl.querySelector('.lb-problems-refresh').textContent, '');
  assert.equal(m2.contentEl.querySelector('.lb-problem'), firstRow, '后台重读没变化：一行不动');
  state.gate = null;
  console.log('PASS problems C20: repair replaces only that row (✓ 已修好, others same element, count updated; 1011: resolved row dropped after a beat, resolved / minor rows never listed), reopen paints cache first with 正在刷新…, unchanged refresh touches nothing');
}

async function pluginTests() {
  const dom = makeDom();
  const El = dom.document.createElement('div').constructor;
  El.prototype.hide = El.prototype.hide || function () { this.hidden = true; };
  El.prototype.show = El.prototype.show || function () { this.hidden = false; };
  const notices = [], confirms = [];
  const obs = makeObsidian(dom.document, { notices });
  const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, window: { confirm: () => false },
    require: n => n === 'obsidian' ? { ...obs, Notice: class { constructor(m) { notices.push(m); } } }
      : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } }
      : n === 'electron' ? { shell: { openPath: async f => { opened.push(f); return ''; } } } : require(n) };
  const opened = [];
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8'), context);
  const Plugin = context.module.exports;
  const p = new Plugin();
  const files = {};
  p.app = { vault: { adapter: { getBasePath: () => ROOT, read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; } } }, workspace: makeWorkspace() };
  p.manifest = { id: 'link-brain-actions', version: '0.4.2', dir: PLUGIN_DIR };
  p.lbPath = x => x;
  p.settings = { sync: {} };
  p.confirm = async o => { confirms.push(o); return confirms.length > 1; };
  const calls = [];
  let release;
  p.spawnPy = async (args, opts) => {
    calls.push({ args: args.slice(2), timeoutMs: opts && opts.timeoutMs });
    if (release === undefined) await new Promise(r => { release = r; });
    return { code: 0, json: { state: 'ready', message: '已登录：合成号', account: '合成号' }, out: '', err: '', all: '', timedOut: false };
  };
  // 账号行：两处同时画，共用一次浅查
  const box = dom.document.body.createDiv();
  p.renderAccountRow(box, { id: 'xhs', name: '小红书', status: (pl, deep) => pl.accountStatus({ deep }) });
  p.renderAccountRow(box, { id: 'xhs', name: '小红书', status: (pl, deep) => pl.accountStatus({ deep }) });
  await tick(5);
  assert.equal(calls.length, 1, '并发两个账号行共用一个检查');
  assert.ok(calls[0].args.includes('--shallow') && calls[0].timeoutMs === 20000, '默认浅查：不拉起服务、不开页');
  release(); await tick(5);
  assert.ok(box.textContent.includes('已登录') && box.textContent.includes('刚刚确认'), box.textContent);
  // 10 分钟内再画：0 次进程
  p.accountCache.at = Date.now() - 3 * 60000;
  const box2 = dom.document.body.createDiv();
  p.renderAccountRow(box2, { id: 'xhs', name: '小红书', status: (pl, deep) => pl.accountStatus({ deep }) });
  await tick(5);
  assert.equal(calls.length, 1, '缓存里的不起进程');
  assert.ok(box2.textContent.includes('3 分钟前确认'), box2.textContent);
  // 1027b：浅查带回读取服务真查的时刻（checked_at）——按它写，不写「刚刚确认」
  p.accountCache.row = { ...p.accountCache.row, checked_at: new Date(Date.now() - 2 * 3600000 - 60000).toISOString() };
  const boxAgo = dom.document.body.createDiv();
  p.renderAccountRow(boxAgo, { id: 'xhs', name: '小红书', status: (pl, deep) => pl.accountStatus({ deep }) });
  await tick(5);
  assert.ok(boxAgo.textContent.includes('2 小时前确认') && !boxAgo.textContent.includes('刚刚确认'), boxAgo.textContent);
  // 同步状态里出现了比缓存新的账号类故障：缓存作废，浅查一次
  files['_archive/sync-status.json'] = JSON.stringify({ state: 'blocked', code: 'CAPTCHA_REQUIRED', updated_at: new Date().toISOString() });
  const box3 = dom.document.body.createDiv();
  p.renderAccountRow(box3, { id: 'xhs', name: '小红书', status: (pl, deep) => pl.accountStatus({ deep }) });
  await tick(5);
  assert.equal(calls.length, 2, '掉登录 / 要验证的事件让缓存作废');
  delete files['_archive/sync-status.json'];
  // 「重新检查」= 深查
  await p.accountStatus({ deep: true });
  assert.ok(!calls.at(-1).args.includes('--shallow') && calls.at(-1).timeoutMs === 180000);
  // openVerify 带 --wait；restoreHold 先确认，第一次不确认不发
  await p.openVerify();
  assert.equal(JSON.stringify(calls.at(-1).args), JSON.stringify(['login', '--verify', '--wait', '--json']));
  assert.ok(notices.some(n => String(n).includes('「收藏」页签')));
  const n0 = calls.length;
  assert.equal(await p.restoreHold(), null);
  assert.equal(calls.length, n0, '没确认不发');
  await p.restoreHold();
  assert.equal(JSON.stringify(calls.at(-1).args), JSON.stringify(['login', '--clear-hold', '--by-owner', '--json']));
  assert.ok(confirms[0].body.includes('「收藏」页签'));
  // 10-26 她截图：账号面板写着「点『没看到验证，恢复』」却没有这个按钮——关窗后熔断还在时账号行也要给，已登录时不给
  const restoreBtn = bx => [...bx.querySelectorAll('button')].find(b => b.textContent === '没看到验证，恢复');
  const shown = b => !!b && b.isShown();
  p.accountCache = { row: { state: 'captcha', verify_result: 'no_captcha_seen', message: '窗口里没出现验证，暂停还在', next_step: '如果你确实没看到滑块：点「没看到验证，恢复」' }, at: Date.now(), deep: false };
  const box4 = dom.document.body.createDiv();
  p.renderAccountRow(box4, { id: 'xhs', name: '小红书', status: (pl, deep) => pl.accountStatus({ deep }) });
  await tick(5);
  assert.ok(shown(restoreBtn(box4)), '熔断还在：账号行有「没看到验证，恢复」');
  const n1 = calls.length;
  restoreBtn(box4).click(); await tick(30);
  assert.equal(JSON.stringify(calls.at(-1).args), JSON.stringify(['login', '--clear-hold', '--by-owner', '--json']), '点了走 restoreHold（先确认）');
  assert.equal(calls.length, n1 + 1);
  assert.ok(!shown(restoreBtn(box4)), '恢复后（已登录）按钮收起');
  p.accountCache = { row: { state: 'captcha', verify_result: 'cleared' }, at: Date.now(), deep: false };
  const box5 = dom.document.body.createDiv();
  p.renderAccountRow(box5, { id: 'xhs', name: '小红书', status: (pl, deep) => pl.accountStatus({ deep }) });
  await tick(5);
  assert.ok(!shown(restoreBtn(box5)), '没有「关窗后熔断还在」的结论就不给');
  // 查看截图：只认目录名，拼本机路径打开
  await assert.rejects(p.openRiskEvidence('../x'), /目录名不对/);
  const evRoot = path.join(require('os').tmpdir(), 'lb-l6-ev-' + process.pid);
  process.env.LINK_BRAIN_EVIDENCE_DIR = evRoot;
  fs.mkdirSync(path.join(evRoot, '20261008-051957'), { recursive: true });
  fs.writeFileSync(path.join(evRoot, '20261008-051957', 'shot.png'), 'x');
  try {
    assert.equal(await p.openRiskEvidence('20261008-051957'), path.join(evRoot, '20261008-051957', 'shot.png'));
    assert.equal(opened.length, 1);
  } finally { fs.rmSync(evRoot, { recursive: true, force: true }); delete process.env.LINK_BRAIN_EVIDENCE_DIR; }
  // 设置页「立即同步」旁：如实写上次几点判到验证（不拦）
  const d0 = new Date(); d0.setSeconds(0, 0); d0.setMinutes(Math.max(0, d0.getMinutes() - 1)); const at = d0.toISOString();   // 今天之内（以前取一小时前，半夜跑会落到昨天）
  assert.match(Plugin.lastRiskNote({ last_risk: { at, code: 'NEEDS_HUMAN.CAPTCHA_REQUIRED', open: true } }), /^⚠ 上次 今天 \d\d:\d\d 在读收藏时判到验证（暂停中/);
  assert.equal(Plugin.lastRiskNote({ last_risk: { at: '2026-01-01T00:00:00Z', open: false } }), '');
  assert.equal(Plugin.lastRiskNote({}), '');
  const src = fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8');
  assert.ok(!/syncNow\(\)\s*\{[^}]*cooldown/.test(src), '不加冷却闸（她 1008 答）');
  console.log('PASS account row S4: shallow by default (20s, single-flight), 10-min cache paints N 分钟前确认 with 0 spawns, account event invalidates, 重新检查 deep; openVerify --wait; restoreHold confirms first; evidence by name only; sync row says 上次 HH:MM 判到验证');
}

// 1015（她截图：「等你处理 · 0」下面还挂着两张卡）：修一条的同时别的行也没了（同一次熔断解除，ACCOUNT_RISK / RISK_HOLD
// 一起解决）——不能只换 key 那一行、留下不存在的卡片；整体重画，空组不出现。
async function staleRowsTest() {
  const dom = makeDom(), notices = [];
  const obsidian = fakeObsidian(dom, notices);
  delete require.cache[require.resolve(path.join(ROOT, PLUGIN_DIR, 'problems-ui.js'))];
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'problems-ui.js'));
  let rows = [
    row({ key: 'login||ACCOUNT_RISK', step: 'login', code: 'NEEDS_HUMAN.ACCOUNT_RISK', action: 'needs_human', label: '账号风控', hover: '跳到安全页', group: 'needs_you' }),
    row({ key: 'embed||NETWORK', step: 'embed', code: 'TRANSIENT.NETWORK', action: 'retry_later', label: '网络不通', hover: '连不上', group: 'auto', repairable: true, repair_minutes: 4 }),
    row({ key: 'ingest||NETWORK', step: 'ingest', code: 'TRANSIENT.NETWORK', action: 'retry_later', label: '网络不通', hover: '连不上', group: 'auto', repairable: true, repair_minutes: 4 }),
  ];
  const state = { replies: {
    list: () => ({ ok: true, summary: {}, problems: rows }),
    repair: () => { rows = rows.filter(r => r.key === 'ingest||NETWORK'); return { ok: true, message: '自愈：修好 1 条', results: [] }; },
  } };
  const { plugin } = makePlugin(state);
  const ui = factory(obsidian, plugin);
  const m = ui.open(); await m.opened;
  const c = m.contentEl;
  const rowOf = key => c.querySelectorAll('.lb-problem').find(r => r.getAttribute('data-key') === key);
  assert.deepEqual(c.querySelectorAll('.lb-problems-group h3').map(h => h.textContent), ['登录验证 · 1', '其他 · 2'], '老后端没有 category：号的事算登录验证，其余归其他');
  await rowOf('embed||NETWORK').querySelector('.lb-problem-repair').onclick();
  assert.equal(rowOf('login||ACCOUNT_RISK'), undefined, '已经解决的别的行不留卡片');
  assert.deepEqual(c.querySelectorAll('.lb-problems-group h3').map(h => h.textContent), ['其他 · 1'], '空组不出现（不会有「登录验证 · 0」）');
  console.log('PASS problems 1015: repair while other rows vanished repaints (no stale card under 等你处理 · 0)');
}

// 1017（她：多条合并一条）：Python 并好的一行（items）在面板里列每一篇：标题 +「查看」，网页版打不开的多「打开验证」
async function foldedRowTest() {
  const dom = makeDom(), notices = [];
  const obsidian = fakeObsidian(dom, notices);
  delete require.cache[require.resolve(path.join(ROOT, PLUGIN_DIR, 'problems-ui.js'))];
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'problems-ui.js'));
  const items = [{ key: 'note.restricted|xhs-a|NOTE_RESTRICTED', item_id: 'xhs-a', title: '合成 A' }, { key: 'note.restricted|xhs-b|NOTE_RESTRICTED', item_id: 'xhs-b', title: '合成 B' }];
  let rows = [row({ key: 'fold|PERMANENT.NOTE_RESTRICTED', step: 'note.restricted', category: 'fetch', code: 'PERMANENT.NOTE_RESTRICTED', action: 'gave_up', label: '网页版要验证', title: '2 篇网页版打不开', hover: '点那篇的打开验证', group: 'gave_up', folded: true, items, dismissable: true })];
  const state = { replies: { list: () => ({ ok: true, summary: {}, problems: rows }) } };
  const { plugin } = makePlugin(state);
  const verified = [];
  plugin.openNoteVerify = async id => { verified.push(id); rows = []; };
  const ui = factory(obsidian, plugin);
  const m = ui.open(); await m.opened;
  const c = m.contentEl;
  assert.deepEqual(c.querySelectorAll('.lb-problems-group h3').map(h => h.textContent), ['拉取没拿全 · 1'], '并成一条，计一条');
  const lines = c.querySelectorAll('.lb-problem-item');
  assert.equal(lines.length, 2);
  assert.deepEqual(lines[0].querySelectorAll('button').map(b => b.textContent), ['查看', '打开验证']);
  await lines[1].querySelectorAll('button').find(b => b.textContent === '打开验证').onclick();
  assert.deepEqual(verified, ['xhs-b']);
  assert.equal(c.querySelectorAll('.lb-problem').length, 0, '修好了：重读后整条消失');
  console.log('PASS problems 1017: folded row lists each note with 查看 / 打开验证; fixed → gone');
}

(async () => {
  await panelTests();
  await staleRowsTest();
  await foldedRowTest();
  await pluginTests();
})().catch(e => { console.error(e); process.exitCode = 1; });

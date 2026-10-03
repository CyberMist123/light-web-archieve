// 第 7 批：设置页「开始」分页（setup-ui.js）。后端还没写好也能测：runPy 全是按 docs/SETUP-CONTRACT.md 形状回话的替身，不起真进程（CONVENTIONS §7.5）。
// 断言：
//   1. 分页：顶部五个分页，点了就换，重开设置页停在上次的；
//   2. 左：`setup plan` 的功能清单——默认按「推荐」勾；必选灰勾取消不了；「以后」有标；预设（轻量版 / 推荐 / 全部）；
//      依赖联动（取消语音识别 → CapsLock 跟着取消；勾 CapsLock → 语音识别自动勾上）；底部合计磁盘 / 内存；齿轮跳到对应分页；选择存 settings.setup.selected；
//   3. 右：①–⑤ 上一步 / 下一步 / 点步骤条跳；
//   4. ② 一键检查并安装：check → fix:auto 的逐项 install；stdout 进度事件画成进度条（百分比 + 阶段 + MB）；失败给原因 + 重试；
//      manual 给怎么做；Dataview 缺时「打开第三方插件」；停止 = killTree 那个安装进程；全部 ready 才算这步完成；
//   5. ③ 账号卡片；④ 定时 / 每天上限 / 图片·视频·评论 + `setup backfill` 一行（改上限天数跟着变）+ 进度条；
//   6. ⑤「不填 key 也能用」+ `setup estimate` 价格（带日期）+ 文本 AI 三格 +「试问一句」走 answerArchive，回答显示在这一步；
//   7. 收起为总览：每步 ✓ / 未完成 +「修改」；
//   8. spawnPy 的 onLine：stdout 被切成碎块也按整行回调（install 进度事件靠它）。
'use strict';
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert/strict');
const { EventEmitter } = require('events');
const { makeDom } = require('./_fakedom.cjs');

const dom = makeDom();
const El = dom.document.createElement('div').constructor;
El.prototype.removeClass = function (...c) { this.classList.remove(...c); };
El.prototype.toggleClass = function (c, on) { this.classList.toggle(c, on); };
El.prototype.hide = function () { this.hidden = true; };
El.prototype.show = function () { this.hidden = false; };

class FakeSetting {
  constructor(container) {
    this.settingEl = container.createDiv({ cls: 'setting-item' });
    const info = this.settingEl.createDiv({ cls: 'setting-item-info' });
    this.nameEl = info.createDiv({ cls: 'setting-item-name' });
    this.descEl = info.createDiv({ cls: 'setting-item-description' });
    this.controlEl = this.settingEl.createDiv({ cls: 'setting-item-control' });
  }
  setName(n) { this.nameEl.setText(n); return this; }
  setDesc(d) { this.descEl.setText(d); return this; }
  setClass(c) { this.settingEl.addClass(c); return this; }
  addButton(cb) {
    const el = this.controlEl.createEl('button');
    const b = { buttonEl: el, setButtonText(t) { el.setText(t); return b; }, setCta() { return b; }, setWarning() { return b; },
      setDisabled(v) { el.disabled = !!v; return b; }, setTooltip() { return b; }, setIcon() { return b; }, onClick(f) { el.onclick = f; return b; } };
    cb(b); return this;
  }
  addExtraButton(cb) {
    const el = this.controlEl.createEl('div', { cls: 'extra-setting-button' });
    const b = { extraSettingsEl: el, setIcon() { return b; }, setTooltip() { return b; }, setDisabled() { return b; }, onClick(f) { el.onclick = f; return b; } };
    cb(b); return this;
  }
  addText(cb, tag = 'input') {
    const el = this.controlEl.createEl(tag);
    const t = { inputEl: el, setPlaceholder(p) { el.setAttribute('placeholder', p); return t; }, setValue(v) { el.value = v; return t; },
      getValue() { return el.value; }, setDisabled() { return t; }, onChange(f) { el.oninput = () => f(el.value); return t; } };
    cb(t); return this;
  }
  addTextArea(cb) { return this.addText(cb, 'textarea'); }
  addToggle(cb) {
    const el = this.controlEl.createEl('div', { cls: 'checkbox-container' });
    const t = { toggleEl: el, setValue(v) { el.checked = !!v; return t; }, setDisabled() { return t; }, onChange(f) { el.onchange = () => f(el.checked); return t; } };
    cb(t); return this;
  }
  addDropdown(cb) {
    const el = this.controlEl.createEl('select');
    const d = { selectEl: el, addOption(v, l) { el.createEl('option', { text: l }); return d; },
      setValue(v) { el.value = v; return d; }, getValue() { return el.value; }, onChange(f) { el.onchange = () => f(el.value); return d; } };
    cb(d); return this;
  }
  then(cb) { cb(this); return this; }
}

const notices = [];
let spawnImpl = () => { throw new Error('测试里不许 spawn 真进程'); };
const OBS = { Plugin: class {}, PluginSettingTab: class { constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = dom.document.createElement('div'); } },
  Modal: class {}, Setting: FakeSetting, Notice: class { constructor(m) { notices.push(String(m)); } }, Menu: class {} };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, Buffer, navigator: { clipboard: { writeText: async t => { context.clipboard = t; } } },
  require: n => n === 'obsidian' ? OBS : n === 'child_process' ? { spawn: (...a) => spawnImpl(...a) } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8')
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;
const PLUGIN_DIR = '../obsidian-plugins/link-brain-actions/';
const setupFactory = require(PLUGIN_DIR + 'setup-ui.js');
const flush = async (n = 3) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };

// —— 契约形状的假后端 ——
const PLAN = {
  ok: true, code: '', message: '',
  components: [
    { id: 'core', name: '归档·同步·浏览·关键词搜索', required: true, default: true, needs_key: false, disk_mb: 120, ram_mb: 300, status: 'ready', depends: [], settings_tab: 'sync' },
    { id: 'reader', name: '读取组件', required: true, default: true, disk_mb: 180, ram_mb: 400, status: 'missing', depends: ['core'], settings_tab: 'sync' },
    { id: 'dataview', name: 'Dataview', required: true, check_only: true, default: true, disk_mb: 3, ram_mb: 20, status: 'missing', depends: [], settings_tab: 'advanced' },
    { id: 'ocr', name: '本地 OCR', default: true, disk_mb: 60, ram_mb: 250, status: 'missing', depends: ['core'], settings_tab: 'ai' },
    { id: 'asr', name: '本地语音识别', default: true, disk_mb: 900, ram_mb: 1200, status: 'missing', depends: ['core'], settings_tab: 'ai' },
    { id: 'capslock', name: 'CapsLock 语音输入', default: true, disk_mb: 5, ram_mb: 30, status: 'missing', depends: ['asr'], settings_tab: 'ai' },
    { id: 'ai_text', name: 'AI 问答 · 概要 · 打标', needs_key: true, default: false, disk_mb: 0, ram_mb: 0, status: 'unknown', depends: ['core'], settings_tab: 'ai' },
    { id: 'ai_vision', name: '识图', needs_key: true, default: false, disk_mb: 0, ram_mb: 0, status: 'unknown', depends: ['core'], settings_tab: 'ai' },
    { id: 'remote', name: '远程阅读', default: false, later: true, disk_mb: 1, ram_mb: 60, status: 'unknown', depends: ['core'], settings_tab: 'remote' },
  ],
  presets: { light: ['core', 'reader', 'dataview', 'ocr'], recommended: ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock', 'ai_text'],
    full: ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock', 'ai_text', 'ai_vision', 'remote'] },
  totals_basis: '磁盘 / 内存是估计值：已装的量实际占用，没装的按官方包大小',
};
const BACKFILL = { ok: true, favorites_total: 1159, archived: 361, deferred: 798, daily_limit: 50, days_left: 16, as_of: '2026-10-03T08:00:00' };
const ESTIMATE = { ok: true, posts: 100, basis: { from_library: true, sample: 361, avg_chars: 820, avg_images: 4.2, avg_video_min: 0.6 },
  items: [{ id: 'summary', name: '概要 + 打标', provider: 'DeepSeek', model: 'deepseek-chat', yuan: 0.8, per: '100 篇', how: '每篇约 1200 输入 token' },
    { id: 'vision', name: '识图', provider: '通义千问', model: 'qwen-vl', yuan: 2.1, per: '100 篇' },
    { id: 'ask', name: '问答（每问一次）', provider: 'DeepSeek', model: 'deepseek-chat', yuan: 0.012, per: '次' }],
  prices: { as_of: '2026-10-03', sources: ['https://example.com/pricing'] }, local_free: ['ocr', 'asr'] };

function makePlugin(saved = {}) {
  const p = new Plugin();
  const saves = [], calls = [], killed = [], asks = [], schedules = [];
  p.manifest = { id: 'link-brain-actions', dir: 'x' };
  p.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async () => false, read: async f => { throw new Error('ENOENT ' + f); } } },
    setting: { opened: [], open() {}, openTabById(id) { this.opened.push(id); } } };
  p.lbRoot = ''; p.vaultDir = 'D:/vault';
  p.settings = Plugin.__merge(saved);
  p.saveSettings = async () => { saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.accountRenders = 0;
  p.renderAccounts = c => { p.accountRenders++; c.createDiv({ cls: 'lb-accounts' }).createDiv({ cls: 'setting-item lb-acct-row' }); };
  p.renderSyncRow = () => () => {};
  p.capsWriterDir = () => null;
  p.remoteUI = { render(box) { box.createEl('h4', { text: '远程阅读（MCP）' }); } };
  p.onboardingUI = () => p._onb || (p._onb = require(PLUGIN_DIR + 'onboarding-ui.js')(OBS, p));
  p.setupUI = () => p._setup || (p._setup = setupFactory(OBS, p));
  p.killTree = async pid => { killed.push(pid); p.backend.finishPending?.(); return [pid]; };
  p.getSyncSchedule = async () => ({ freq: 'daily', enabled: true, time: '04:30', others: [] });
  p.setSyncSchedule = async (...a) => { schedules.push(a); return { ok: true, detail: '已保存' }; };
  p.answerArchive = async req => { asks.push(req); return p.backend.answer(req); };
  p.stopArchiveAnswer = () => 0;
  // 后端替身：按子命令回话；install 由场景表决定（可以挂起，等测试放行）
  p.backend = {
    check: () => ({ ok: false, results: [] }),
    install: {},
    answer: async req => { req.onPhase?.('检索收藏：共 361 条'); req.onDelta?.('先看'); req.onDelta?.('这三篇。'); return { status: 'ok', markdown: '先看这三篇。[来源1]', sources: [{}, {}, {}] }; },
  };
  p.runPy = async (args, opts = {}) => {
    calls.push(args.join(' '));
    const sub = args.slice(2);
    if (sub[0] !== 'setup') throw new Error('意外的调用 ' + args.join(' '));
    if (sub[1] === 'plan') return { code: 0, json: JSON.parse(JSON.stringify(PLAN)), out: '', err: '' };
    if (sub[1] === 'backfill') return { code: 0, json: BACKFILL, out: '', err: '' };
    if (sub[1] === 'estimate') return { code: 0, json: ESTIMATE, out: '', err: '' };
    if (sub[1] === 'check') return { code: 0, json: p.backend.check(sub[3].split(',')), out: '', err: '' };
    if (sub[1] === 'install') {
      const id = sub[3];
      const script = p.backend.install[id];
      if (!script) throw new Error('没准备这个安装：' + id);
      opts.onChild?.({ pid: 4000 + calls.length });
      return script(opts);
    }
    throw new Error('意外的调用 ' + args.join(' '));
  };
  return { p, saves, calls, killed, asks, schedules };
}
function openTab(p, id) { if (id) p.settingsView = { ...(p.settingsView || { otherAI: false }), tab: id }; const t = new Plugin.__SettingTab({}, p); t.display(); return t; }
const q = (root, sel) => root.querySelector(sel);
const qa = (root, sel) => root.querySelectorAll(sel);
const btn = (root, text) => qa(root, 'button').find(b => b.textContent === text);
const comp = (root, id) => qa(root, '.lb-comp').find(r => r.getAttribute('data-id') === id);
const checked = root => qa(root, '.lb-comp').filter(r => r.querySelector('input').checked).map(r => r.getAttribute('data-id'));
const activeTab = root => q(root, '.lb-tab.is-active')?.textContent;
const stepHeading = root => q(root, '.lb-step-heading')?.textContent;
const installRow = (root, id) => qa(root, '.lb-install-row').find(r => r.getAttribute('data-id') === id);
const line = l => JSON.stringify(l);

(async () => {
  // —— 0. 纯函数 ——
  const I = setupFactory._internals;
  const cs = PLAN.components;
  assert.deepEqual(I.toggleSelection(PLAN.presets.recommended, 'asr', false, cs), ['core', 'reader', 'dataview', 'ocr', 'ai_text'], '取消 asr → capslock 跟着走');
  assert.deepEqual(I.toggleSelection(PLAN.presets.light, 'capslock', true, cs), ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock'], '勾 capslock → asr 自动勾');
  assert.deepEqual(I.toggleSelection(PLAN.presets.light, 'core', false, cs), PLAN.presets.light, '必选项取消不了');
  assert.deepEqual(I.initialSelection(null, PLAN), PLAN.presets.recommended, '没选过 = 推荐');
  assert.deepEqual(I.initialSelection(['ocr', 'nonexistent'], PLAN), ['core', 'reader', 'dataview', 'ocr'], '存着的选择：认得的 + 必选补齐');
  assert.deepEqual(I.totals(PLAN.presets.light, cs), { disk: 363, ram: 970, unknown: 0 });
  assert.equal(I.fmtMB(2560), '2.5 GB'); assert.equal(I.fmtMB(null), '?');
  assert.deepEqual(I.installTargets(PLAN.presets.full, cs).includes('remote'), false, '「以后」的不装');
  assert.deepEqual(I.progressView({ phase: '下载', done: 52428800, total: 104857600, text: 'CapsWriter' }), { pct: 50, text: '下载 · 50% · 50.0 / 100.0 MB · CapsWriter' });
  assert.deepEqual(I.progressView({ phase: '解压' }), { pct: null, text: '解压' }, '没给数就不编百分比');
  assert.equal(I.backfillLine(BACKFILL, 50), '收藏 1159 篇，已入库 361 篇，按每天 50 篇约还要 16 天');
  assert.equal(I.backfillLine(BACKFILL, 0), '收藏 1159 篇，已入库 361 篇，每天不限量（一次抓完，容易触发风控）');
  assert.equal(I.backfillLine({ favorites_total: null, archived: 12, deferred: null, days_left: null }, 50), '已入库 12 篇', '缺的数不显示那段');
  assert.equal(I.backfillLine({ favorites_total: 10, archived: 10 }, 50), '收藏 10 篇，已入库 10 篇，已全部入库');
  assert.equal(I.yuan(0.012), '¥0.012'); assert.equal(I.yuan(0.8), '¥0.80'); assert.equal(I.yuan(null), '—');

  // —— 1. 分页 ——
  let env = makePlugin();
  let tab = openTab(env.p);
  let root = tab.containerEl;
  assert.equal(activeTab(root), '开始', '默认「开始」');
  btn(root, 'AI').click(); root = tab.containerEl;
  assert.equal(activeTab(root), 'AI');
  tab.hide();
  tab = openTab(env.p); root = tab.containerEl;
  assert.equal(activeTab(root), 'AI', '重开设置页停在上次的分页');
  btn(root, '开始').click(); root = tab.containerEl;
  await flush();

  // —— 2. 左：功能清单 ——
  assert.equal(env.calls.filter(c => c.endsWith('setup plan')).length, 1, '读一次 setup plan');
  assert.deepEqual(checked(root), PLAN.presets.recommended, '默认按「推荐」勾');
  assert.equal(q(root, '.lb-preset.is-active')?.textContent, '推荐');
  const coreBox = comp(root, 'core').querySelector('input');
  assert.ok(coreBox.disabled && coreBox.checked, '必选灰勾');
  assert.match(comp(root, 'remote').textContent, /以后/, '「以后」有标');
  assert.match(comp(root, 'ai_text').textContent, /要 key/);
  assert.match(comp(root, 'asr').querySelector('.lb-comp-meta').textContent, /^磁盘 900 MB · 内存 1.2 GB/);
  assert.equal(q(root, '.lb-setup-total-line').textContent, '合计：磁盘 1.2 GB · 内存 2.1 GB', '推荐的合计');
  assert.match(q(root, '.lb-setup-total').textContent, /估计值/, '写清怎么算的');
  // 预设
  btn(root, '轻量版（不要任何 key）').click(); await flush();
  assert.deepEqual(checked(root), PLAN.presets.light);
  assert.deepEqual(env.p.settings.setup.selected, PLAN.presets.light, '选择存 settings.setup.selected');
  assert.equal(q(root, '.lb-setup-total-line').textContent, '合计：磁盘 363 MB · 内存 970 MB');
  btn(root, '全部').click(); await flush();
  assert.deepEqual(checked(root), PLAN.presets.full);
  btn(root, '推荐').click(); await flush();
  // 依赖联动
  let box = comp(root, 'asr').querySelector('input'); box.checked = false; await box.onchange(); await flush();
  assert.deepEqual(checked(root), ['core', 'reader', 'dataview', 'ocr', 'ai_text'], '取消语音识别 → CapsLock 跟着取消');
  assert.equal(q(root, '.lb-preset.is-active'), null, '不是哪个预设了');
  box = comp(root, 'capslock').querySelector('input'); box.checked = true; await box.onchange(); await flush();
  assert.ok(checked(root).includes('asr') && checked(root).includes('capslock'), '勾 CapsLock → 语音识别自动勾上');
  box = comp(root, 'core').querySelector('input'); box.checked = false; await box.onchange(); await flush();
  assert.ok(checked(root).includes('core'), '必选取消不了');
  assert.deepEqual(env.p.settings.setup.selected, PLAN.presets.recommended);
  // 齿轮 → 对应分页
  comp(root, 'ai_text').querySelector('.lb-comp-gear').click(); root = tab.containerEl;
  assert.equal(activeTab(root), 'AI', '齿轮跳到 AI 分页');
  btn(root, '开始').click(); root = tab.containerEl; await flush();
  comp(root, 'core').querySelector('.lb-comp-gear').click(); root = tab.containerEl;
  assert.equal(activeTab(root), '同步与内容');
  btn(root, '开始').click(); root = tab.containerEl; await flush();
  assert.equal(env.calls.filter(c => c.endsWith('setup plan')).length, 1, '换分页回来不重读清单');

  // —— 3. 步骤前后翻 ——
  assert.equal(stepHeading(root), '① 选功能');
  assert.deepEqual(qa(root, '.lb-step').map(s => s.textContent), ['①选功能', '②检查并安装', '③扫码登录', '④同步设置', '⑤AI（选填）'], '竖排步骤条');
  assert.ok(btn(root, '上一步').disabled, '第一步不能上一步');
  assert.match(q(root, '.lb-step-summary').textContent, /你勾了 7 项：.*本地语音识别/);
  assert.match(q(root, '.lb-step-summary').textContent, /要 API key 的：AI 问答/);
  assert.ok(qa(root, '.setting-item-name').some(n => n.textContent === '收藏存放位置'), '① 里有收藏存放位置');
  btn(root, '下一步').click(); await flush();
  assert.equal(stepHeading(root), '② 检查并安装');
  assert.ok(env.p.settings.setup.passed.includes(1));
  btn(root, '上一步').click(); await flush();
  assert.equal(stepHeading(root), '① 选功能');
  qa(root, '.lb-step').find(s => s.getAttribute('data-step') === '2').click(); await flush();
  assert.equal(stepHeading(root), '② 检查并安装', '点步骤条直接跳');
  assert.equal(env.p.settings.setup.step, 2, '停在哪一步存 setup.step');

  // —— 4. ② 一键检查并安装 ——
  let checkRound = 0;
  const installed = new Set();   // 装成功的，下次 check 就是 ready（后端「装完自己再 check」）
  env.p.backend.check = ids => {
    checkRound++;
    const st = { core: 'ready', reader: 'missing', dataview: checkRound >= 2 ? 'ready' : 'missing', ocr: 'missing', asr: 'missing', capslock: 'missing', ai_text: 'ready' };
    return { ok: false, results: ids.map(id => ({ item_id: id, status: installed.has(id) ? 'ready' : st[id] || 'missing', code: '', error: '', detail: id === 'reader' ? '没找到 link-brain-reader' : '',
      fix: id === 'dataview' ? 'manual' : 'auto', fix_hint: id === 'dataview' ? '在「第三方插件」里搜 Dataview，安装并启用' : '' })) };
  };
  let release = null;
  const ok = id => async () => (installed.add(id), { code: 0, json: { type: 'result', ok: true, code: '', message: '装好了', status: 'ready', component: id }, out: '', err: '' });
  env.p.backend.install = {
    reader: ok('reader'),
    ocr: async opts => { opts.onLine(line({ type: 'progress', component: 'ocr', phase: '下载模型', done: 10, total: 20, text: 'PP-OCRv6' })); return ok('ocr')(); },
    asr: opts => new Promise(res => {
      opts.onLine(line({ type: 'progress', component: 'asr', phase: '下载', done: 157286400, total: 629145600, text: 'CapsWriter-Offline' }));
      release = () => res({ code: 1, json: { type: 'result', ok: false, code: 'TRANSIENT.NETWORK', message: '下载中断：连接被重置', status: 'failed' }, out: '', err: '' });
    }),
    capslock: async () => (installed.add('capslock'), { code: 0, json: { type: 'result', ok: true, code: '', message: '装好了', status: 'ready', component: 'capslock',
      settings_patch: { voice: { capsWriterDir: 'C:/CapsWriter-test' } } }, out: '', err: '' }),
  };
  assert.ok(!btn(root, '一键检查并安装').disabled);
  const run = btn(root, '一键检查并安装').click();
  await flush(5);
  assert.equal(env.calls.find(c => c.includes('setup check')), '-m link_brain setup check --components core,reader,dataview,ocr,asr,capslock', '按勾的检查（「以后」的、要 key 的不算）');
  assert.ok(env.calls.includes('-m link_brain setup install --component reader') && env.calls.includes('-m link_brain setup install --component ocr'), '逐项装 fix:auto 的');
  assert.ok(!env.calls.some(c => c.endsWith('--component dataview') || c.endsWith('--component core')), 'ready 的和 manual 的不装');
  // asr 正在装：进度条按事件画
  let r = installRow(root, "asr");
  assert.equal(r.querySelector('.lb-install-status').textContent, '安装中');
  assert.equal(r.querySelector('.lb-bar-fill').style.width, '25%', '进度条 = done / total');
  assert.equal(r.querySelector('.lb-install-progress').textContent, '下载 · 25% · 150.0 / 600.0 MB · CapsWriter-Offline');
  assert.equal(installRow(root, 'capslock').querySelector('.lb-install-status').textContent, '等着装', '后面的排队');
  assert.equal(installRow(root, 'ocr').querySelector('.lb-install-status').textContent, '✓ 就绪');
  assert.ok(btn(root, '停止') && !btn(root, '一键检查并安装'), '装着的时候只有「停止」');
  assert.match(q(root, '.lb-install-summary').textContent, /正在装：本地语音识别/);
  // 进度事件再来一条：只更新这一行
  release(); await run; await flush(5);
  r = installRow(root, 'asr');
  assert.equal(r.querySelector('.lb-install-status').textContent, '没装上');
  assert.equal(r.querySelector('.lb-install-error').textContent, '原因：下载中断：连接被重置', '失败如实给原因');
  assert.match(r.querySelector('.lb-install-progress').textContent, /^停在：下载 · 25%/);
  assert.equal(installRow(root, 'capslock').querySelector('.lb-install-status').textContent, '✓ 就绪', '一项失败不挡后面的');
  // 后端装完改了插件设置（settings_patch）：合进内存设置（不丢同一段里的其他键）并保存，免得插件下次保存把它盖掉
  assert.equal(env.p.settings.voice.capsWriterDir, 'C:/CapsWriter-test');
  assert.ok(Object.keys(env.p.settings.voice).length > 1, '深合并：voice 里原有的其他设置还在');
  assert.equal(env.saves.at(-1).voice.capsWriterDir, 'C:/CapsWriter-test', '合完存盘');
  const dv = installRow(root, 'dataview');
  assert.equal(dv.querySelector('.lb-install-status').textContent, '要你手动');
  assert.match(dv.querySelector('.lb-install-hint').textContent, /^怎么做：在「第三方插件」里搜 Dataview/);
  dv.querySelectorAll('button').find(b => b.textContent === '打开第三方插件').click();
  assert.deepEqual(env.p.app.setting.opened.slice(-1), ['community-plugins'], 'Dataview 缺：打开第三方插件');
  assert.match(q(root, '.lb-install-summary').textContent, /^还没全部就绪：2 项没就绪：Dataview、本地语音识别$/);
  assert.ok(!qa(root, '.lb-step').find(s => s.getAttribute('data-step') === '2').classList.contains('is-done'), '没全 ready 不算完成');
  assert.ok(env.calls.filter(c => c.endsWith('setup plan')).length >= 2, '装完重读清单（「已装」跟着变）');
  // 重试：这次停止
  let stopRelease = null;
  env.p.backend.install.asr = opts => new Promise(res => {
    opts.onLine(line({ type: 'progress', component: 'asr', phase: '校验', text: 'sha256' }));
    stopRelease = () => res({ code: 1, json: { type: 'progress', component: 'asr', phase: '校验' }, out: '', err: '' });
  });
  env.p.backend.finishPending = () => stopRelease?.();
  const retry1 = installRow(root, 'asr').querySelectorAll('button').find(b => b.textContent === '重试').click();
  await flush();
  r = installRow(root, 'asr');
  assert.ok(r.querySelector('.lb-bar').classList.contains('is-indeterminate'), '没给 total：不定进度条');
  assert.equal(r.querySelector('.lb-install-progress').textContent, '校验 · sha256');
  btn(root, '停止').click(); await retry1; await flush(5);
  assert.equal(env.killed.length, 1, '停止 = killTree 那个安装进程');
  r = installRow(root, 'asr');
  assert.equal(r.querySelector('.lb-install-status').textContent, '已停止');
  assert.match(r.querySelector('.lb-install-error').textContent, /再点「重试」会接着装或从头干净重来/);
  // 再重试：成功
  env.p.backend.install.asr = ok('asr');
  await installRow(root, 'asr').querySelectorAll('button').find(b => b.textContent === '重试').click(); await flush(5);
  assert.equal(installRow(root, 'asr').querySelector('.lb-install-status').textContent, '✓ 就绪', '重试成功');
  assert.match(q(root, '.lb-install-summary').textContent, /1 项没就绪：Dataview/);
  // Dataview 装好后「只重新检查」→ 全部 ready → 这步完成
  await btn(root, '只重新检查').click(); await flush(5);
  assert.equal(q(root, '.lb-install-summary').textContent, '✓ 全部就绪');
  assert.ok(qa(root, '.lb-step').find(s => s.getAttribute('data-step') === '2').classList.contains('is-done'), '全部 ready → ② ✓');
  assert.equal(env.calls.filter(c => c.includes('install --component')).length, 6, '只检查不装');
  // 检查本身失败：如实说
  env.p.backend.check = () => null;
  await btn(root, '只重新检查').click(); await flush(5);
  assert.match(q(root, '.lb-install-summary').textContent, /^没检查成：后台没返回检查结果/);

  // —— 5. ③ 账号卡片 / ④ 同步设置 ——
  btn(root, '下一步').click(); await flush();
  assert.equal(stepHeading(root), '③ 扫码登录');
  assert.ok(q(root, '.lb-step-body').querySelector('.lb-accounts'), '③ 就是账号卡片');
  env.p.accountState = { xhs: 'ready' }; env.p.setupNotify(); await flush();
  assert.ok(qa(root, '.lb-step').find(s => s.getAttribute('data-step') === '3').classList.contains('is-done'), '登上了 → ③ ✓');
  btn(root, '下一步').click(); await flush(5);
  assert.equal(stepHeading(root), '④ 同步设置');
  const body = () => q(root, '.lb-step-body');
  const rowNamed = n => qa(body(), '.setting-item').find(x => x.querySelector('.setting-item-name').textContent.trim() === n);
  for (const n of ['每天几点同步', '每天最多新抓', '下载图片', '下载视频', '评论 · 自动拉取']) assert.ok(rowNamed(n), '④ 有「' + n + '」');
  assert.match(body().textContent, /附件（PDF \/ Word 等）/);
  assert.equal(rowNamed('每天几点同步').querySelector('input').value, '04:30', '读到现在的定时');
  assert.match(rowNamed('每天几点同步').querySelector('.setting-item-description').textContent, /当前：每天 04:30/);
  assert.equal(q(root, '.lb-backfill-line').textContent, '收藏 1159 篇，已入库 361 篇，按每天 50 篇约还要 16 天');
  assert.equal(q(root, '.lb-backfill').querySelector('.lb-bar-fill').style.width, '31%');
  const lim = rowNamed('每天最多新抓').querySelector('input'); lim.value = '100'; await lim.oninput(); await flush();
  assert.equal(env.p.settings.sync.dailyNewLimit, 100, '复用原设置项（同一个键）');
  assert.equal(q(root, '.lb-backfill-line').textContent, '收藏 1159 篇，已入库 361 篇，按每天 100 篇约还要 8 天', '改上限天数跟着变');
  const tIn = rowNamed('每天几点同步').querySelector('input');
  tIn.value = '25:00'; tIn.oninput();
  await btn(rowNamed('每天几点同步'), '保存定时').onclick(); await flush();
  assert.equal(env.schedules.length, 0); assert.match(notices.at(-1), /时间格式不对/);
  tIn.value = '23:15'; tIn.oninput();
  await btn(rowNamed('每天几点同步'), '保存定时').onclick(); await flush();
  assert.deepEqual(env.schedules.at(-1), ['daily', '23:15', null], '定时走原来的 setSyncSchedule');

  // —— 6. ⑤ AI ——
  btn(root, '下一步').click(); await flush(5);
  assert.equal(stepHeading(root), '⑤ AI（选填）');
  assert.equal(q(root, '.lb-free-line').textContent, '不填 key 也能用：归档、浏览、关键词搜索、本地 OCR、本地语音。', '先说不填也能用');
  const est = qa(root, '.lb-estimate-row').map(x => x.textContent);
  assert.deepEqual(est, ['概要 + 打标DeepSeek · deepseek-chat¥0.80 / 100 篇', '识图通义千问 · qwen-vl¥2.10 / 100 篇', '问答（每问一次）DeepSeek · deepseek-chat¥0.012 / 次']);
  assert.match(q(root, '.lb-estimate').textContent, /按你库里 361 篇的平均量估.*价格核对于 2026-10-03/);
  assert.ok(rowNamed('文本 AI') && rowNamed('API Key'), '文本 AI 三格就在这一步');
  assert.ok(!qa(root, '.lb-step').find(s => s.getAttribute('data-step') === '5').classList.contains('is-done'), '没填 key：⑤ 未完成');
  const keyIn = rowNamed('API Key').querySelector('input');
  rowNamed('接口地址').querySelector('input').value = 'https://api.example.com/v1/chat/completions'; await rowNamed('接口地址').querySelector('input').oninput();
  keyIn.value = 'sk-test'; await keyIn.oninput();
  assert.equal(env.p.settings.textAI.apiKey, 'sk-test', '存的还是 textAI.apiKey');
  const askRow = rowNamed('试问一句');
  askRow.querySelector('input').value = '有什么菜谱？'; askRow.querySelector('input').oninput();
  await btn(askRow, '问').onclick(); await flush(5);
  assert.equal(env.asks.at(-1).question, '有什么菜谱？', '「试问一句」走 answerArchive');
  assert.equal(q(root, '.lb-ask-answer').textContent, '先看这三篇。[来源1]', '回答显示在这一步');
  assert.match(q(root, '.lb-ask-out').textContent, /用了 3 条收藏做依据/);
  env.p.backend.answer = async () => { throw new Error('接口拒绝了 key（HTTP 401）'); };
  await btn(askRow, '问').onclick(); await flush(5);
  assert.equal(q(root, '.lb-ask-error').textContent, '没答上：接口拒绝了 key（HTTP 401）', '答不上如实说');
  // 正在答：显示后端阶段 + 停止
  let finishAsk = null;
  env.p.backend.answer = req => new Promise(res => { req.onPhase('生成回答：用 5 条材料'); finishAsk = () => res({ status: 'cancelled', markdown: '半截' }); });
  btn(askRow, '问').onclick(); await flush(3);
  assert.match(q(root, '.lb-ask-phase').textContent, /^生成回答：用 5 条材料/);
  assert.ok(btn(q(root, '.lb-ask-out'), '停止'));
  finishAsk(); await flush(5);
  assert.match(q(root, '.lb-ask-out').textContent, /已停止生成/);

  // —— 7. 完成 → 总览 ——
  btn(root, '完成').click(); await flush();
  assert.equal(env.p.settings.setup.collapsed, true);
  assert.equal(q(root, '.lb-setup-head').querySelector('h3').textContent, '设置总览');
  let ov = qa(root, '.lb-overview-row');
  assert.equal(ov.length, 5);
  assert.deepEqual(ov.map(x => x.querySelector('.lb-overview-mark').textContent), ['✓', '✓', '✓', '✓', '✓'], '五步都 ✓（最后一次检查没跑成不抹掉上次的结果）');
  assert.match(ov[1].textContent, /全部就绪/);
  assert.match(ov[4].textContent, /已配置文本 AI/);
  // 账号掉了：总览跟着变（账号卡片一变就刷新），写「未完成」+ 原因
  env.p.accountState = { xhs: 'expired' }; env.p.setupNotify(); await flush();
  ov = qa(root, '.lb-overview-row');
  assert.equal(ov[2].querySelector('.lb-overview-mark').textContent, '○');
  assert.match(ov[2].textContent, /未完成 · 还没登录/);
  assert.ok(!btn(root, '下一步'), '总览没有上一步 / 下一步');
  btn(ov[3], '修改').click(); await flush(5);
  assert.equal(env.p.settings.setup.collapsed, false);
  assert.equal(stepHeading(root), '④ 同步设置', '「修改」回到那一步');
  btn(root, '收起为总览').click(); await flush();
  assert.ok(q(root, '.lb-overview'), '任何时候都能收起为总览');
  btn(root, '展开向导').click(); await flush();
  assert.equal(stepHeading(root), '④ 同步设置');
  // 重开设置页：停在「开始」、向导状态接得上（存在 setup.* 里）
  tab.hide();
  tab = openTab(env.p); root = tab.containerEl; await flush(5);
  assert.equal(activeTab(root), '开始');
  assert.equal(stepHeading(root), '④ 同步设置');
  assert.ok(Object.keys(env.saves.at(-1).setup).every(k => ['selected', 'step', 'collapsed', 'passed'].includes(k)), '只新增 setup.* 这几个键');
  tab.hide();
  assert.equal(env.p.setupNotify, null, '关设置页注销刷新钩子');

  // —— 清单读不到：如实说 + 重试 ——
  env = makePlugin();
  let fail = true;
  const realRun = env.p.runPy;
  env.p.runPy = async (args, opts) => { if (fail && args.includes('plan')) throw new Error('后台命令失败（退出码 1）'); return realRun(args, opts); };
  tab = openTab(env.p, 'start'); root = tab.containerEl; await flush(5);
  assert.match(q(root, '.lb-setup-error').textContent, /^读不到功能清单：后台命令失败/);
  fail = false;
  btn(q(root, '.lb-setup-error'), '重试').click(); await flush(5);
  assert.deepEqual(checked(root), PLAN.presets.recommended, '重试后读到了');
  tab.hide();

  // —— 8. spawnPy 的 onLine：碎块拼成整行；onChild 拿到子进程 ——
  {
    const p = new Plugin();
    p.app = { vault: { adapter: { getBasePath: () => 'D:/vault' } } };
    spawnImpl = () => {
      const c = new EventEmitter(); c.pid = 99; c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
      setTimeout(() => {
        c.stdout.emit('data', Buffer.from('{"type":"progress","done":1,'));
        c.stdout.emit('data', Buffer.from('"total":4}\n{"type":"progress","done":2,"total":4}\n{"type":"res'));
        c.stdout.emit('data', Buffer.from('ult","ok":true,"status":"ready"}'));
        c.emit('close', 0);
      }, 0);
      return c;
    };
    const lines = []; let child = null;
    const res = await p.runPy(['-m', 'link_brain', 'setup', 'install', '--component', 'ocr'], { onLine: l => lines.push(JSON.parse(l)), onChild: ch => { child = ch; } });
    assert.deepEqual(lines.map(l => l.type + (l.done || '')), ['progress1', 'progress2', 'result'], '整行回调，最后一行没换行也给');
    assert.equal(child.pid, 99);
    assert.equal(res.json.status, 'ready', '结果照旧是最后一行 JSON');
    spawnImpl = () => { throw new Error('测试里不许 spawn 真进程'); };
  }

  console.log('PASS setup wizard: tabs remembered, plan list (recommended default, required locked, later tag, presets, asr↔capslock deps, totals, gear → tab), steps ①–⑤ prev/next/jump, check → install with progress bars / failure reason / retry / stop via killTree / manual hint / Dataview button / all-ready gate, accounts, schedule + daily limit + backfill days, estimate prices + text AI + 试问一句 via answerArchive, overview with 修改; spawnPy onLine');
})().catch(e => { console.error(e); process.exitCode = 1; });

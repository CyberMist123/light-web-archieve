// 1027 设置页六组（design-1027/prototype.html「设置」第三版 + design.md §3；settings-v6.js）：一页滚完，左边锚点，
//   ① 账号登录 ② 收藏与同步 ③ 目录与批注 ④ 高级功能 ⑤ CLI 与外接 MCP ⑥ 修复；每组常用的平铺，其余在组底「＋ 更多」（点开才画）；说明在 ⓘ 里；改了就存。
// 守住以前的几条规矩（1009 / 1010 / 1015 / 1018 / 1026）：每个设置只出现在一处（比第 7 批的清单一项不少）；同步时间只有一个编辑器（设置页 · 首次设置 ·
//   plugin.openSyncTime() 都落到它）；落点名照认；开关 / 下拉存失败拨回原值；从不删她的密钥引用、不改已经填好的地址（10-10 事故）。
// 1027 新加：同步时间改了自动存（没有「保存定时」）· 同步开关 · ④ 每项一个下拉对上双重门禁 · 「粘一把 key」换掉用不了的那家（以前只填空格子，换不掉）·
//   首次设置和设置页是同一份值 · 没人读的键不再进默认值 · 「输入框提示字」那一行没了 · 精细识图模型改的是真正起作用的那一个。
// 不起真进程（CONVENTIONS §7.5）：child_process 换成一碰就炸的桩，runPy / 账号卡片是替身，home-ui / remote-ui / onboarding-ui / schedule-ui / usage-ui 是真的。
'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const { makeDom } = require('./_fakedom.cjs');

const dom = makeDom();
const El = dom.document.createElement('div').constructor;
// Obsidian 给 HTMLElement 加的几个小帮手（_fakedom 没有的）
El.prototype.removeClass = function (...c) { this.classList.remove(...c); };
El.prototype.toggleClass = function (c, on) { this.classList.toggle(c, on); };
El.prototype.hide = function () { this.hidden = true; };
El.prototype.show = function () { this.hidden = false; };

class FakeSetting {
  constructor(container) {
    this.settingEl = container.createDiv({ cls: 'setting-item' });
    this.settingEl.setting = this;
    const info = this.settingEl.createDiv({ cls: 'setting-item-info' });
    this.nameEl = info.createDiv({ cls: 'setting-item-name' });
    this.descEl = info.createDiv({ cls: 'setting-item-description' });
    this.controlEl = this.settingEl.createDiv({ cls: 'setting-item-control' });
  }
  setName(n) { this.nameEl.setText(n); return this; }
  setDesc(d) { this.descEl.setText(d); return this; }
  setClass(c) { this.settingEl.addClass(c); return this; }
  setHeading() { this.settingEl.addClass('setting-item-heading'); return this; }
  addButton(cb) {
    const el = this.controlEl.createEl('button');
    const b = { buttonEl: el, setButtonText(t) { el.setText(t); return b; }, setCta() { el.addClass('mod-cta'); return b; }, setWarning() { return b; },
      setDisabled(v) { el.disabled = !!v; return b; }, setTooltip() { return b; }, setIcon() { return b; }, onClick(f) { el.onclick = f; return b; } };
    cb(b); return this;
  }
  addExtraButton(cb) {
    const el = this.controlEl.createEl('div', { cls: 'extra-setting-button' });
    const b = { extraSettingsEl: el, setIcon() { return b; }, setTooltip(t) { el.setAttribute('aria-label', t); return b; }, setDisabled() { return b; }, onClick(f) { el.onclick = f; return b; } };
    cb(b); return this;
  }
  addText(cb, tag = 'input') {
    const el = this.controlEl.createEl(tag);
    const t = { inputEl: el, setPlaceholder(p) { el.setAttribute('placeholder', p); return t; }, setValue(v) { el.value = v; return t; },
      getValue() { return el.value; }, setDisabled() { return t; }, onChange(f) { el.oninput = () => f(el.value); return t; } };
    cb(t); return this;
  }
  addTextArea(cb) { return this.addText(cb, 'textarea'); }
  // 照 Obsidian 1.14.4：setValue 值变了会再触发 onChange（ToggleComponent.setValue 调 changeCallback）
  addToggle(cb) {
    const el = this.controlEl.createEl('div', { cls: 'checkbox-container' });
    let change = null;
    const t = { toggleEl: el, getValue() { return !!el.checked; }, setValue(v) { const was = !!el.checked; el.checked = !!v; if (change && was !== !!v) change(!!v); return t; }, setDisabled() { return t; }, onChange(f) { change = f; el.onchange = () => f(el.checked); return t; } };
    cb(t); return this;
  }
  addDropdown(cb) {
    const el = this.controlEl.createEl('select');
    const d = { selectEl: el, options: [], addOption(v, l) { d.options.push([v, l]); el.createEl('option', { text: l }); return d; },
      setValue(v) { el.value = v; return d; }, getValue() { return el.value; }, onChange(f) { el.onchange = () => f(el.value); return d; } };
    el.dropdown = d; cb(d); return this;
  }
  then(cb) { cb(this); return this; }
}

const notices = [];
const OBS = { Plugin: class {}, PluginSettingTab: class { constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = dom.document.createElement('div'); } },
  Modal: class {}, Setting: FakeSetting, Notice: class { constructor(m) { notices.push(m); } }, Menu: class {} };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, document: dom.document, URL, console, navigator: { clipboard: { writeText: async () => {} } },
  require: n => n === 'obsidian' ? OBS
    : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8')
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings; module.exports.__DEFAULTS = DEFAULT_SETTINGS;', context);
const Plugin = context.module.exports;
const PLUGIN_DIR = '../obsidian-plugins/link-brain-actions/';

// —— 后端替身：按子命令回 SETUP-CONTRACT / connect / remote / usage 的形状 ——
const PLAN = { ok: true, components: [
  { id: 'core', name: '归档·同步·浏览·关键词搜索', required: true, status: 'ready', disk_mb: 120, ram_mb: 300, depends: [] },
  { id: 'reader', name: '读取组件（读小红书收藏 / 评论 / 附件）', required: true, status: 'ready', disk_mb: 80, ram_mb: 400, depends: ['core'] },
  { id: 'dataview', name: 'Dataview（目录页显示用，Obsidian 插件）', required: true, check_only: true, status: 'ready', depends: [] },
  { id: 'ocr', name: '本地 OCR（图片里的字）', status: 'ready', disk_mb: 60, ram_mb: 200, depends: ['core'] },
  { id: 'asr', name: '本地语音识别（CapsWriter，视频转写 / 语音提问）', status: 'missing', disk_mb: 900, ram_mb: 600, depends: ['core'] },
  { id: 'capslock', name: 'CapsLock 语音输入', status: 'missing', disk_mb: 5, ram_mb: 30, depends: ['asr'] },
  { id: 'ai_text', name: 'AI 问答 · 概要 · 打标（要 API key）', needs_key: true, status: 'needs_key', depends: ['core'] },
  { id: 'ai_vision', name: '识图（要 API key）', needs_key: true, status: 'needs_key', depends: ['ocr'] },
  { id: 'remote', name: '远程阅读（MCP，高级，要自备域名）', later: true, status: 'ready', depends: ['core'] }],
  presets: { light: ['core', 'reader', 'dataview', 'ocr'], recommended: ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock', 'ai_text'] }, totals_basis: '估计值' };
const W = o => ({ calls: 1, failed: 0, items: 0, in: 0, out: 0, sec: 0, cost: 0, free: 0, unpriced: 0, ...o });
const DATES = Array.from({ length: 30 }, (_, i) => `2026-10-${String(i - 2).padStart(2, '0')}`.replace('-10--', '-09-2').replace('-10-00', '-09-30'));
const USAGE = { ok: true, budget: { daily_yuan: 3, spent_today: 0.83, over: false },
  summary: { as_of: '2026-10-03', features: { ask: '问收藏', vision: '识图', summary: '概要' }, month: { deepseek: W({ cost: 12.5, calls: 300 }), aliyun: W({ cost: 8.06, calls: 90, unpriced: 2 }) },
    windows: { '7d': { total: W({ calls: 9, cost: 1.5, free: 4, unpriced: 1 }), providers: { deepseek: W({ calls: 4, cost: 1.5 }), google: W({ calls: 4, free: 4 }), aliyun: W({ calls: 1, unpriced: 1 }) }, models: {}, features: { ask: W({ calls: 4, cost: 1.5 }) },
      unpriced_models: [{ provider: 'aliyun', model: 'qwen-x', calls: 1 }] }, '30d': { total: W({ calls: 0 }), providers: {}, models: {}, features: {} } },
    series: { dates: DATES, providers: { deepseek: DATES.map((_, i) => (i === 29 ? 1.2 : i === 27 ? null : i === 25 ? 0.3 : 0)) }, models: {}, features: { ask: DATES.map((_, i) => (i === 29 ? 1.2 : 0)) } },
    recent: [], recent_limit: 200 },
  keys: { aliyun: { code: 'NEEDS_HUMAN.QUOTA_EXCEEDED', caps: ['visionAI'] } }, links: { aliyun: { recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge' } },
  features: [
    { id: 'ask', name: '问收藏', cap: 'textAI', on: true, state: 'ok', chain: [{ label: 'DeepSeek', provider: 'deepseek', price: '约 ¥0.004 / 次' }] },
    { id: 'summary', name: '概要 · 打标签', cap: 'summaryAI', on: true, state: 'ok', chain: [{ label: 'DeepSeek', provider: 'deepseek' }] },
    { id: 'vision', name: '识图', cap: 'visionAI', on: true, state: 'backup', state_text: '已换用 通义千问', chain: [{ label: 'Gemini', provider: 'google' }, { label: '通义千问', provider: 'aliyun' }] },
    { id: 'embed', name: '按意思搜', cap: 'embedAI', on: true, state: 'ok', chain: [{ label: '通义千问', provider: 'aliyun' }] }] };
const REPLIES = {
  'setup plan': PLAN,
  'setup estimate': { ok: true, items: [], prices: { as_of: '2026-10-03' } },
  'comments --fill-status': { ok: true, pending: 12, ready: 12, cooling: 0, stuck: 0, missing: 340, running: false, message: '12 篇的评论还没补齐' },
  'connect status': { ok: true, clients: {}, json: '{"mcpServers":{}}',
    apps: [{ id: 'claude-code', name: 'Claude Code', installed: true, oneclick: true, version: '2.1.3', connected: false },
      { id: 'claude-desktop', name: 'Claude 桌面版', installed: true, oneclick: true, version: '', connected: true },
      { id: 'codex', name: 'Codex', installed: true, oneclick: true, version: '0.146.0', connected: false },
      { id: 'opencode', name: 'OpenCode', installed: true, oneclick: false, version: '1.19.3', connected: false }],
    not_installed: ['Pi', 'Grok Build'] },
  'usage --table': { ok: true, ai_table: { cli: [{ id: 'codex', name: 'Codex', preset: 'codex' }, { id: 'claude', name: 'Claude Code', preset: 'claude' }, { id: 'opencode', name: 'OpenCode', preset: 'opencode' }] } },
  'usage --balance': { ok: true, balances: {} },
  'usage': USAGE,
  'keys detect': { ok: true, provider: 'aliyun', name: '通义千问', message: '认出是 通义千问', fills: {
    textAI: { endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen3.7-flash' },
    visionAI: { endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen3.8-flash' } } },
  'remote status': { ok: true, state: 'running', message: '运行中（127.0.0.1:18071）', auth: { passphrase_set: true, passphrase_copyable: true, clients: [], personal: [] }, recent: [] },
  'sync-schedule': { task: null, freq: 'none', enabled: false, installable: true },
  'doctor': { checks: [{ label: 'Python 程序', state: 'ready', message: '能用' }, { label: 'Dataview', state: 'missing', message: '没装', next_step: '到第三方插件里装' }] },
  'problems summary': { ok: true },
  'problems repair': { ok: true, message: '修好 2 件' },
};
function reply(args) {
  const sub = args.slice(2).join(' ');
  const key = Object.keys(REPLIES).sort((a, b) => b.length - a.length).find(k => sub.startsWith(k));
  return key ? REPLIES[key] : { ok: true };
}

// —— 搭一个插件对象：真的 renderSyncRow / readSyncStatus / onboarding-ui / home-ui / remote-ui / schedule-ui / usage-ui，假的 vault / 账号卡片 ——
function makePlugin(saved, files = {}) {
  const p = new Plugin();
  const saves = [], calls = [];
  p.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async f => f in files, read: async f => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f]; } },
    getAllLoadedFiles: () => [] }, workspace: { getActiveFile: () => null, trigger() {} } };
  p.manifest = { dir: '.obsidian/plugins/link-brain-actions' };
  p.lbRoot = '';
  const fresh = saved && saved.__fresh;
  if (saved) delete saved.__fresh;
  p.settings = Plugin.__merge(saved);
  if (!fresh && !(saved && saved.onboarding)) p.settings.onboarding = { ...(p.settings.onboarding || {}), guideDone: true };
  if (saved && saved.remote) p.settings.remote = saved.remote;
  p.loadData = async () => JSON.parse(JSON.stringify(p.settings));
  p.saveFails = 0;
  p.saveSettings = async () => { if (p.saveFails > 0) { p.saveFails--; throw new Error('磁盘满了（合成）'); } saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.notify = (m) => notices.push(m);
  p.renderAccounts = (c, opts) => { p.accountOpts = opts; c.createDiv({ cls: 'lb-accounts' }).createDiv({ cls: 'setting-item lb-acct-row' }); };
  p.capsWriterDir = () => null;
  p.setCapsVoice = async () => true;
  p.runPy = async (args, opts = {}) => { calls.push(args); return { code: 0, json: reply(args), err: '' }; };
  p.onboardingUI = () => p._onb || (p._onb = require(PLUGIN_DIR + 'onboarding-ui.js')(OBS, p));
  p.homeUI = () => p._home || (p._home = require(PLUGIN_DIR + 'home-ui.js')(OBS, p));
  p.scheduleUI = () => require(PLUGIN_DIR + 'schedule-ui.js')(OBS, p);
  p.remoteUI = require(PLUGIN_DIR + 'remote-ui.js')(OBS, p);
  p.skillsUI = () => require(PLUGIN_DIR + 'skills-ui.js')(OBS, p);
  p.usageUI = () => require(PLUGIN_DIR + 'usage-ui.js')(OBS, p);
  p.settingsPages = () => p._pages || (p._pages = require(PLUGIN_DIR + 'settings-pages.js')(OBS, p));
  p.settingsV6 = () => p._v6 || (p._v6 = require(PLUGIN_DIR + 'settings-v6.js')(OBS, p));
  p.providerIcons = () => require(PLUGIN_DIR + 'provider-icons.js');
  p.problemsUI = () => ({ copyReport: async () => { p.copied = (p.copied || 0) + 1; return true; } });
  p.openProblems = () => { p.problemsOpened = (p.problemsOpened || 0) + 1; };
  p.syncNow = async () => {};
  p.copyText = async () => {};
  p.busyButton = () => () => {};
  return { p, saves, files, calls };
}
function openPage(p, tabId = null) {
  if (tabId) p.settingsView = { ...(p.settingsView || {}), tab: tabId };
  const tab = new Plugin.__SettingTab({}, p); p.settingTab = tab; tab.display(); return tab;
}
const flush = () => new Promise(r => setTimeout(r, 0));
const settle = async (n = 10) => { for (let i = 0; i < n; i++) await flush(); };
// 假 DOM 设 open 不会自己发 toggle（浏览器会）：这里补发；「更多」里画过一次就不再画
const openMore = async (root, section) => { const d = root.querySelector(`details[data-section="${section}"]`); assert.ok(d, '没有「更多」：' + section); d.open = true; d.fire('toggle'); await settle(); return d; };
const openAll = async root => { for (let k = 0; k < 4; k++) { const shut = root.querySelectorAll('details').filter(d => !d.open); if (!shut.length) break; for (const d of shut) { d.open = true; d.fire('toggle'); } await settle(); } };
// 一个元素此刻用户看不看得见：祖先里有收起的 details（不在 summary 里）或 hidden / is-hidden
function visible(el, root) {
  for (let n = el; n && n !== root; n = n.parentNode) {
    if (n.hidden || n.classList?.contains('is-hidden')) return false;
    const up = n.parentNode;
    if (up && up.tagName === 'DETAILS' && !up.open && n.tagName !== 'SUMMARY') return false;
  }
  return true;
}
const rowsOf = root => root.querySelectorAll('.setting-item');
const nameOf = row => { const n = row.querySelector('.setting-item-name'); if (!n) return ''; return [...n.childNodes].filter(c => !(c.classList && (c.classList.contains('lb-help') || c.classList.contains('lb-feat-icon') || c.classList.contains('lb-app-ver')))).map(c => c.textContent).join('').trim(); };
const idOf = row => nameOf(row) || row.querySelectorAll('button').map(b => b.textContent.trim()).join('+') || (row.classList.contains('lb-acct-row') ? '〔账号卡片〕' : '');
const pane = root => root.querySelector('.lb-tab-pane');
const group = (root, id) => root.querySelector(`.lb-group[data-section="${id}"]`);
const visibleRows = el => rowsOf(el).filter(r => visible(r, el)).map(idOf).filter(Boolean);
const rowNamed = (root, n) => rowsOf(root).find(r => nameOf(r) === n);
const helpOf = row => row.querySelector('.lb-help')?.getAttribute('aria-label') || '';
const descText = row => { const d = row.querySelector('.setting-item-description'); if (!d) return ''; return [...d.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent).join('').trim(); };
const pick = async (row, value) => { const sel = row.querySelector('select'); sel.value = value; await sel.onchange(); await settle(); };

// 第 7 批（五个分页全部展开）的设置项清单——每种配置一份；只许挪地方 / 改名 / 合并重复，不许丢
const CONFIGS = {
  defaults: {},
  alt: { textAI: { mode: 'cli', command: 'x' }, summaryAI: { mode: 'http' }, visionAI: { mode: 'off' }, asrAI: { mode: 'http' }, voice: { capsLock: false } },
  legacy: { textAI: { mode: 'http', endpoint: 'https://api.example.com/v1/chat/completions', keyFile: 'k.csv' }, visionAI: { mode: 'media' }, asrAI: { mode: 'media' }, ocr: { mode: 'media' } },
};
const BASELINE = {
  defaults: ["〔账号卡片〕","收藏同步","登录后自动同步","下载图片","下载视频","评论 · 自动拉取","评论 · 手动拉取","每天最多新抓","文本 AI","接口地址","API Key","模型","测试文本 AI","归档摘要模型（默认同文本 AI）","模型","测试归档摘要","识图接口","接口地址","API Key","模型","精细识别模型","测试识图","视频画面文字","语音识别","端口","测试语音识别","CapsLock 语音输入","CapsWriter 目录","输入框提示文字","DeepSeek","Codex","Sonnet","添加模型","Claude Code","Codex","其他客户端（JSON 配置）","测试 MCP","搜索收藏","批注昵称","下载文件夹","检查本机环境","文字识别（OCR）","识别精度","模型目录（可选）","测试 OCR","摘要提示词（归档时抽取）","问答提示词（/问AI）","回答输出上限（max_tokens）","发给模型的总字符上限","每篇片段字符上限","送模型的片段篇数（topK）","先用小模型扩检索词","载入当前分类+清空（用内置）+重建目录","等待手动下载（分钟）","待补附件","电脑需求 必需：Windows","电脑需求 内存：建议 8 GB","电脑需求 收藏问答：文本模型（","电脑需求 图片文字：本地 OC","电脑需求 附件：PDF / W","电脑需求 视频：语音转写走上面","电脑需求 语音输入：CapsW","〔远程阅读〕"],
  alt: ["〔账号卡片〕","收藏同步","登录后自动同步","下载图片","下载视频","评论 · 自动拉取","评论 · 手动拉取","每天最多新抓","文本 AI","命令","测试文本 AI","归档摘要模型（默认同文本 AI）","接口地址","API Key","模型","测试归档摘要","识图接口","测试识图","视频画面文字","语音识别","接口地址","API Key","模型","测试语音识别","CapsLock 语音输入","CapsWriter 目录","输入框提示文字","DeepSeek","Codex","Sonnet","添加模型","Claude Code","Codex","其他客户端（JSON 配置）","测试 MCP","搜索收藏","批注昵称","下载文件夹","检查本机环境","文字识别（OCR）","识别精度","模型目录（可选）","测试 OCR","摘要提示词（归档时抽取）","问答提示词（/问AI）","回答输出上限（max_tokens）","发给模型的总字符上限","每篇片段字符上限","送模型的片段篇数（topK）","先用小模型扩检索词","载入当前分类+清空（用内置）+重建目录","等待手动下载（分钟）","待补附件","电脑需求 必需：Windows","电脑需求 内存：建议 8 GB","电脑需求 收藏问答：文本模型（","电脑需求 图片文字：本地 OC","电脑需求 附件：PDF / W","电脑需求 视频：语音转写走上面","电脑需求 语音输入：CapsW","〔远程阅读〕"],
  legacy: ["〔账号卡片〕","收藏同步","登录后自动同步","下载图片","下载视频","评论 · 自动拉取","评论 · 手动拉取","每天最多新抓","文本 AI","接口地址","API Key","模型","测试文本 AI","归档摘要模型（默认同文本 AI）","模型","测试归档摘要","识图接口","测试识图","视频画面文字","语音识别","测试语音识别","CapsLock 语音输入","CapsWriter 目录","输入框提示文字","DeepSeek","Codex","Sonnet","添加模型","Claude Code","Codex","其他客户端（JSON 配置）","测试 MCP","搜索收藏","批注昵称","下载文件夹","检查本机环境","文字识别（OCR）","测试 OCR","摘要提示词（归档时抽取）","问答提示词（/问AI）","回答输出上限（max_tokens）","发给模型的总字符上限","每篇片段字符上限","送模型的片段篇数（topK）","先用小模型扩检索词","载入当前分类+清空（用内置）+重建目录","等待手动下载（分钟）","待补附件","电脑需求 必需：Windows","电脑需求 内存：建议 8 GB","电脑需求 收藏问答：文本模型（","电脑需求 图片文字：本地 OC","电脑需求 附件：PDF / W","电脑需求 视频：语音转写走上面","电脑需求 语音输入：CapsW","〔远程阅读〕"],
};
const REMOVED = ['搜索收藏', '输入框提示文字'];   // 目录页本来就有入口；1027：「输入框提示字」那一行删了（问收藏页没填就用默认那句）
// 旧身份 → 1027 的名字（照设计稿 prototype.html 的用词）
const RENAMED = {
  '评论 · 自动拉取': '评论', '评论 · 手动拉取': '评论', '每天最多新抓': '每天新收', '文本 AI': '命令行程序', 'API Key': '密钥（API Key）', '模型': '模型名',
  '测试文本 AI': '测试（发一句话，几乎不花钱）', '归档摘要模型（默认同文本 AI）': '概要与标签', '测试归档摘要': '测试概要模型（发一段短文，几乎不花钱）',
  '识图接口': '识图', '精细识别模型': '精细识图模型', '测试识图': '测试识图（发一张小图，几乎不花钱）', '视频画面文字': '认视频画面里的字',
  '语音识别': '语音转文字', '端口': '本机语音识别的端口', 'CapsLock 语音输入': '按 CapsLock 说话', 'CapsWriter 目录': 'CapsWriter 装在哪',
  DeepSeek: '文本 AI', '添加模型': '加一个模型', '其他客户端（JSON 配置）': '其他应用', '测试 MCP': '测一下本机的连接程序（MCP）',
  '批注昵称': '批注署名', '下载文件夹': '手动下载的文件夹', '检查本机环境': '当前状态', '文字识别（OCR）': '识图', '识别精度': '本机认字精度', '模型目录（可选）': '认字模型放在哪',
  '测试 OCR': '测试认字（本机跑，不花钱）', '摘要提示词（归档时抽取）': '写概要的提示词', '问答提示词（/问AI）': '问收藏的提示词',
  '回答输出上限（max_tokens）': '回答长度上限', '发给模型的总字符上限': '给模型看的字数', '每篇片段字符上限': '每篇摘录字数',
  '送模型的片段篇数（topK）': '参考篇数', '先用小模型扩检索词': '扩展同义词', '载入当前分类+清空（用内置）+重建目录': '编辑索引',
  '等待手动下载（分钟）': '等下载最多', '待补附件': '还没下到的附件', '命令': '自己写命令',
  '电脑需求 收藏问答：文本模型（': '电脑需求 问收藏：文本模型（现', '电脑需求 图片文字：本地 OC': '电脑需求 图片里的字：本地 O',
  '电脑需求 视频：语音转写走上面': '电脑需求 视频：语音转文字默认', '电脑需求 语音输入：CapsW': '电脑需求 说话打字：CapsW', '〔远程阅读〕': '〔连接其他 AI〕',
  '测试语音识别': '测试语音转文字（本机跑，不花钱）', '登录后自动同步': '登录后马上同步', '下载图片': '图片', '下载视频': '视频',
};
// 合并的：本机 AI 的复制命令只留一处；「评论 · 手动拉取」合进「评论」；OCR 和识图接口合成一个「识图」下拉
const MERGED = { Codex: 1, '评论': 1, '识图': 1 };
// 这些设置只许出现一次（别处有重复的一律删掉只留一处）
const ONCE = ['〔账号卡片〕', '收藏同步', '同步', '同步时间', '每天新收', '图片', '视频', '评论', '收藏放在哪', '登录后马上同步', '每次新收上限', '补评论间隔',
  '目录的样子', '批注署名', '留言对象', '索引文件', '转 Markdown', '语音转文字', '识图', '问答模型', '概要与标签', '按意思搜', '粘一把 key', '配置哪一项',
  '按 CapsLock 说话', '精细识图模型', '扩展同义词', '命令行程序', '开放收藏库', 'Claude Code', '测一下本机的连接程序（MCP）', '当前状态', '问题记录', '后端命令', '诊断信息', '重新走一遍首次设置'];
// 动态状态行（说明是现读的状态，不算「每项说明一行」的说明文字）
const DYNAMIC = new Set(['〔账号卡片〕', '收藏同步', '评论补齐', '当前状态', '这台电脑', '文本 AI', 'Codex', 'Sonnet', '远程访问', '口令', '连接地址', 'Claude Code', 'Claude 桌面版', '你的网址',
  '远程访问的运行情况', '后端命令', 'Python 路径', 'OpenCode', '服务商', '阿里云百炼', 'DeepSeek', 'Gemini', '收藏放在哪']);

// 一页全部打开（「更多」都展开、接口与密钥把每一项都选一遍）的清单
async function inventory(p) {
  const t = openPage(p); const root = t.containerEl;
  await settle(); await openAll(root); await settle();
  const items = rowsOf(root).map(idOf).filter(Boolean);
  const req = root.querySelectorAll('div').filter(d => /^· /.test(d.textContent) && !d.children.length).map(d => '电脑需求' + d.textContent.slice(1, 12));
  const conn = root.querySelector('.lb-connect') ? ['〔连接其他 AI〕'] : [];
  const api = root.querySelector('[data-section="ai-keys"]');
  const caps = rowNamed(api, '配置哪一项').querySelector('select').dropdown.options.map(o => o[0]);
  const extra = [];
  for (const cap of caps.slice(1)) { api.lbPick(cap); await settle(); extra.push(...rowsOf(api.querySelector('.lb-api-fields')).map(idOf).filter(Boolean)); }
  api.lbPick('ask'); await settle();
  t.hide();
  return [...items, ...req, ...conn, ...extra];
}

(async () => {
  // —— 1. 一页六组：左边锚点、组名照设计稿；库里已有收藏就不出首次设置；立即同步只有一个；最多一个主按钮 ——
  const sum = { updated_at: '2026-10-02T04:20:00', needs_human: 1, auto: 2, gave_up: 0, sync: { state: 'ready', message: '收藏同步完成', last_success: '2026-10-02T04:12:00', new: 3, deferred: 0, updated_at: '2026-10-02T04:20:00' } };
  let env = makePlugin({ onboarding: { guideDone: true } }, { '_archive/problems-summary.json': JSON.stringify(sum), '_archive/catalog-data.json': '{"items":[]}' });
  let tab = openPage(env.p); let root = tab.containerEl;
  await settle();
  assert.ok(!root.querySelector('.lb-tabs'), '没有页签');
  assert.ok(!pane(root).querySelector('.lb-guide'), '库里已经有收藏：不出首次设置');
  assert.deepEqual(root.querySelectorAll('.lb-group').map(g => g.getAttribute('data-section')), ['g-account', 'g-sync', 'g-catalog', 'g-advanced', 'g-connect', 'g-repair']);
  assert.deepEqual(root.querySelectorAll('.lb-group-head h2').map(h => h.textContent), ['账号登录', '收藏与同步', '目录与批注', '高级功能', 'CLI 与外接 MCP', '修复']);
  assert.deepEqual(root.querySelectorAll('.lb-anchor').map(a => a.textContent), ['01账号登录', '02收藏与同步', '03目录与批注', '04高级功能', '05CLI 与外接 MCP', '06修复']);
  assert.ok(root.querySelector('.lb-anchor.is-current[data-target="g-account"]'), '一开始高亮第一组');
  root.querySelectorAll('.lb-anchor')[3].onclick({ preventDefault() {} });
  assert.ok(group(root, 'g-advanced')._scrolledIntoView, '点锚点滚到那一组');
  assert.ok(root.querySelector('.lb-anchor.is-current[data-target="g-advanced"]'));
  assert.equal(root.querySelectorAll('.lb-card[data-section="s-status"]').length, 0, '大状态卡没了');
  assert.equal(root.querySelectorAll('button').filter(b => b.textContent === '立即同步').length, 1, '「立即同步」只有一个');
  assert.ok(root.querySelectorAll('button').filter(b => b.classList.contains('mod-cta') && visible(b, root)).length <= 1, '最多一个主按钮');
  assert.match(pane(root).querySelector('.lb-v7-lead').textContent, /改动自动保存/);
  assert.ok(root.querySelectorAll('details.lb-more').every(d => !d.open && d.querySelector('summary').textContent === '＋ 更多'), '组底「＋ 更多」默认收着');
  // ① 账号：小红书一张卡（账号卡片放在卡里、平台名在卡片标题上、登好了给「换个账号」）+ B 站灰着
  const acc = group(root, 'g-account');
  assert.deepEqual(acc.querySelectorAll('.lb-twin-card').map(c => c.getAttribute('data-platform') + ':' + c.querySelector('strong').textContent), ['xhs:小红书', 'bilibili:B 站']);
  assert.ok(acc.querySelector('.lb-twin-card[data-platform="xhs"] .lb-acct-row'), '账号卡片在小红书那张卡里');
  assert.deepEqual(env.p.accountOpts, { inCard: true });
  assert.ok(acc.querySelector('.lb-twin-card.is-soon button').disabled, 'B 站：以后支持');
  assert.ok(!/登错号|指定账号|目标账号/.test(acc.textContent), '没有「登错号」这回事');
  // ② 收藏与同步
  const sy = group(root, 'g-sync');
  assert.deepEqual(visibleRows(sy), ['收藏同步', '同步', '每天新收', '图片', '视频', '评论'], '同步关着：「同步时间」那一行收起来');
  assert.ok(sy.querySelector('[data-section="sync-time"] .lb-sched'), '唯一的同步时间编辑器在②，落点 sync-time');
  assert.deepEqual(sy.querySelectorAll('.lb-subhead').map(x => x.textContent), ['同步', '存哪些']);
  assert.deepEqual(rowNamed(sy, '收藏同步').querySelectorAll('button').map(b => b.textContent), ['立即同步']);
  assert.ok(!sy.querySelector('.lb-sched-save') && !sy.querySelector('.lb-sched-off'), '没有「保存定时」「关闭定时」按钮');
  // ③ 目录与批注：没有全局样式控件（在目录的「编排 → Aa 样式」）
  const cat = group(root, 'g-catalog');
  assert.deepEqual(visibleRows(cat), ['目录的样子', '批注署名']);
  assert.ok(!/字号|字体|列数|布局/.test(visibleRows(cat).join()), '样式不在这里');
  let arranged = 0; env.p.openCatalogArrange = async () => { arranged++; };
  rowNamed(cat, '目录的样子').querySelector('button').onclick(); assert.equal(arranged, 1, '去目录编排');
  // ④ 高级功能：一项一行带图标
  const adv = group(root, 'g-advanced');
  assert.deepEqual(adv.querySelectorAll('.lb-feat').map(r => nameOf(r) + ':' + r.querySelector('.lb-feat-icon')?.getAttribute('data-icon')),
    ['转 Markdown:doc', '语音转文字:audio', '识图:image', '问答模型:chat', '概要与标签:summary', '按意思搜:search']);
  assert.ok(adv.querySelectorAll('.lb-feat-icon svg').length === 6, '线条图标');
  assert.equal(rowNamed(adv, '转 Markdown').querySelector('.lb-feat-tag').textContent, 'PDF / Word · 本机免费 · 自动');
  assert.ok(!rowNamed(adv, '转 Markdown').querySelector('select, .checkbox-container'), '转 Markdown 只是说明，不虚构开关');
  assert.deepEqual(rowNamed(adv, '问答模型').querySelector('select').dropdown.options.map(o => o[1]), ['文本 AI', 'Codex', 'Sonnet', '关闭'], '问答模型 = 问收藏页下拉里那几个');
  assert.equal(rowNamed(adv, '问答模型').querySelector('select').value, '文本 AI');
  // key 出了问题：一句 + 去充值 + 换 key
  const fix = adv.querySelector('.lb-key-trouble .lb-fix-line');
  assert.ok(fix && /通义千问 额度用完或余额不足（识图）/.test(fix.textContent), '欠费那一句点名哪家、影响哪项');
  assert.deepEqual(fix.querySelectorAll('button').map(b => b.textContent), ['去充值 ↗', '换 key']);
  // AI 控制台：一行今天 · 本月 · 每天最多花（唯一的上限输入框）
  const con = adv.querySelector('.lb-console');
  assert.deepEqual(con.querySelectorAll('.lb-console-k').map(k => k.childNodes[0].textContent), ['今天', '本月', '每天最多花']);
  assert.equal(con.querySelectorAll('.lb-console-v')[0].textContent, '¥0.83');
  assert.match(con.querySelectorAll('.lb-console-cell')[1].textContent, /¥20\.56.*另有 2 次未计价/);
  assert.equal(root.querySelectorAll('input.lb-spend-input').length, 1, '每天上限只有一个输入框');
  assert.equal(con.querySelector('input.lb-spend-input').value, '3', '没存过：显示后端默认');
  assert.match(helpOf({ querySelector: () => con.querySelector('.lb-console-cap .lb-help') ? { getAttribute: a => con.querySelector('.lb-console-cap .lb-help').getAttribute(a) } : null }), /手动问收藏.*不受限/, '上限只管后台付费处理');
  // ⑤ CLI 与外接 MCP
  const cn = group(root, 'g-connect');
  assert.deepEqual(cn.querySelectorAll('.lb-subhead').map(x => x.textContent), ['本机命令行', '让其他 AI 读收藏']);
  assert.deepEqual(cn.querySelectorAll('.lb-twin-card strong').map(x => x.textContent), ['电脑端', '网页端']);
  assert.deepEqual(cn.querySelectorAll('.lb-app').map(r => r.getAttribute('data-app')), ['claude-code', 'claude-desktop', 'codex', 'opencode', 'other']);
  assert.equal(cn.querySelector('.lb-mcp-state').textContent, '● 已接入 1 个');
  assert.ok(cn.querySelector('[data-section="remote"] .lb-twin-head .checkbox-container'), '网页端的开关在卡片标题上');
  assert.ok(!rowNamed(cn, '你的网址'), '网页端关着：网址、口令不出');
  assert.deepEqual(rowNamed(cn, '命令行程序').querySelector('select').querySelectorAll('option').map(o => o.textContent), ['不用（用接口）', 'Codex', 'Claude Code', 'OpenCode']);
  assert.ok(rowNamed(cn, '开放收藏库').querySelector('.checkbox-container').checked, '收藏库默认开放');
  assert.ok(!/访问令牌|端口/.test(visibleRows(cn).join()), '访问令牌、端口在「更多」里（10-10 她定）');
  // ⑥ 修复：当前状态 + 检查 / 全部修一遍；问题记录只有一个入口
  const rp = group(root, 'g-repair');
  assert.deepEqual(visibleRows(rp), ['当前状态', '问题记录']);
  assert.deepEqual(rowNamed(rp, '当前状态').querySelectorAll('button').map(b => b.textContent), ['检查', '全部修一遍']);
  assert.match(descText(rowNamed(rp, '当前状态')), /⚠ 1 件要你处理 · 另有 2 条在自动处理/);
  await openAll(root);
  assert.equal(root.querySelectorAll('button').filter(b => /打开问题列表/.test(b.textContent) || (b.textContent === '打开' && b.closest('.setting-item') && nameOf(b.closest('.setting-item')) === '问题记录')).length, 1, '问题记录只有一个入口（更多里不再有「问题」那一行）');
  await rowNamed(rp, '当前状态').querySelectorAll('button')[0].onclick(); await settle();
  assert.deepEqual(rp.querySelectorAll('.lb-check-line').map(x => x.textContent), ['✓ Python 程序：能用', '⚠ Dataview：没装 — 到第三方插件里装']);
  assert.ok(env.calls.some(a => a.join(' ').includes('problems summary')), '检查 = 先请后端重算问题记录');
  await rowNamed(rp, '当前状态').querySelectorAll('button')[1].onclick(); await settle();
  assert.ok(env.calls.some(a => a.join(' ') === '-m link_brain problems repair') && notices.includes('修好 2 件'), '全部修一遍 = problems repair，结果如实说');
  await rowNamed(rp, '诊断信息').querySelector('button').onclick(); assert.equal(env.p.copied, 1, '诊断信息：复制（已脱敏）');
  tab.hide();

  // —— 2. ④ 每项一个下拉：对上 setup.selected 和各能力的 mode（双重门禁）；存失败拨回 ——
  env = makePlugin({ onboarding: { guideDone: true }, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text', 'ai_vision'], aiSynced: true },
    visionAI: { mode: 'http', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen3.8-flash', keyFile: 'k.csv' } });
  tab = openPage(env.p, 'ai'); root = tab.containerEl; await settle();
  const A = n => rowNamed(group(root, 'g-advanced'), n);
  const val = n => A(n).querySelector('select').value;
  assert.deepEqual([val('语音转文字'), val('识图'), val('问答模型'), val('概要与标签')], ['local', 'ai', '文本 AI', 'inherit']);
  await pick(A('语音转文字'), 'off');
  assert.equal(env.p.settings.asrAI.mode, 'off'); assert.ok(!env.p.settings.setup.selected.includes('asr'));
  await pick(A('语音转文字'), 'local');
  assert.equal(env.p.settings.asrAI.mode, 'capswriter'); assert.ok(env.p.settings.setup.selected.includes('asr'), '本机 = 勾上 asr + 本机 CapsWriter');
  await pick(A('语音转文字'), 'http');
  assert.equal(env.p.settings.asrAI.mode, 'http');
  assert.match(A('语音转文字').querySelector('.lb-feat-need').textContent, /还没填在线接口/, '选了在线接口但没填：那一行下面一句 + 去填');
  await pick(A('识图'), 'local');
  assert.ok(!env.p.settings.setup.selected.includes('ai_vision') && env.p.settings.setup.selected.includes('ocr'));
  await pick(A('识图'), 'off');
  assert.equal(env.p.settings.ocr.mode, 'off', '关识图 = 本机认字也关');
  await pick(A('识图'), 'ai');
  assert.ok(env.p.settings.setup.selected.includes('ai_vision') && env.p.settings.ocr.mode !== 'off', 'AI 识图带上本机认字');
  await pick(A('问答模型'), 'off');
  assert.ok(!env.p.settings.setup.selected.includes('ai_text'), '问答「关闭」= ai_text 关');
  assert.deepEqual([val('概要与标签'), A('按意思搜').querySelector('.checkbox-container').checked], ['off', false], '同一个开关：概要、按意思搜如实显示关');
  await pick(A('概要与标签'), 'inherit');
  assert.ok(env.p.settings.setup.selected.includes('ai_text'), '打开概要 = 顺手打开 ai_text');
  assert.equal(val('问答模型'), '文本 AI', '问答跟着回来');
  await pick(A('概要与标签'), 'custom');
  assert.equal(env.p.settings.summaryAI.mode, 'http');
  await pick(A('概要与标签'), 'off');
  assert.deepEqual([env.p.settings.summaryAI.mode, env.p.settings.summaryAI.prevMode], ['off', 'http'], '关了记住原来的');
  await pick(A('概要与标签'), 'custom');
  assert.equal(env.p.settings.summaryAI.mode, 'http'); assert.ok(!('prevMode' in env.p.settings.summaryAI));
  await pick(A('问答模型'), 'Codex');
  assert.equal(env.p.settings.activeModel, 'Codex', '问答模型 = activeModel（问收藏页同一个值）');
  // 按意思搜：没配过的关了再开 = 回到后端默认（存盘时不留一个 embedAI）
  assert.equal(env.p.settings.embedAI, undefined);
  const emb = A('按意思搜').querySelector('.checkbox-container');
  emb.checked = false; await emb.onchange(); await settle();
  assert.deepEqual(env.p.settings.embedAI, { mode: 'off', wasDefault: true });
  emb.checked = true; await emb.onchange(); await settle();
  assert.equal(env.p.settings.embedAI, undefined, '回到「没配过」');
  assert.ok(!('embedAI' in env.saves.at(-1)), '写进 data.json 的也没有 embedAI');
  // 存失败：下拉拨回 + 一句（CONVENTIONS §8）
  notices.length = 0; env.p.saveFails = 1;
  const before = JSON.stringify(env.p.settings.setup.selected);
  await pick(A('识图'), 'off');
  assert.equal(val('识图'), 'ai', '下拉拨回'); assert.equal(JSON.stringify(env.p.settings.setup.selected), before, '选择还原');
  assert.ok(notices.some(n => String(n).startsWith('没保存上，已改回原来的')), notices.join('|'));
  // 识别细项：按 CapsLock 说话只在「本机」时能用；精细识图模型改的是真正起作用的那一个
  tab.hide();
  env = makePlugin({ visionAI: { mode: 'http', model: 'gemini-3.5-flash', refineModel: 'old-unused', refine: { endpoint: 'https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen3.8-max' } } });
  tab = openPage(env.p); root = tab.containerEl; await settle();
  await openMore(root, 'ai-more');
  const refine = rowNamed(root, '精细识图模型').querySelector('input');
  assert.equal(refine.value, 'qwen3.8-max', '显示的是 visionAI.refine.model（盖过 refineModel 的那个）');
  refine.value = 'qwen3.9-max'; await refine.oninput(); await settle();
  assert.equal(env.p.settings.visionAI.refine.model, 'qwen3.9-max'); assert.equal(env.p.settings.visionAI.refineModel, 'old-unused', '不去改不起作用的那个');
  assert.ok(rowNamed(root, '按 CapsLock 说话').classList.contains('is-disabled') === false, '语音转文字是本机：CapsLock 能用');
  assert.ok(root.querySelector('.lb-pair'), '识别细项 / 问答细项两列');
  tab.hide();

  // —— 3. 粘一把 key：认出是哪家 → 这家正用不了就换掉那几格（1027 修：以前只往空格子里填，换不掉）；否则只填空着的 ——
  {
    const BL = 'https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions', G = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions';
    const e = makePlugin({ summaryAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', fallback: { endpoint: BL, model: 'qwen3.7-flash', keyFile: 'C:/keys/llm.csv', keyField: 'qwen' } },
      visionAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', refine: { endpoint: BL, model: 'qwen3.8-max', apiKeyEnv: 'DASHSCOPE_API_KEY' } },
      textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-v4-flash', keyFile: 'C:/keys/llm.csv', keyField: 'ds' } });
    const v6 = e.p.settingsV6();
    // 坏的是阿里云（识图第二层 + 概要的备用都在用它）
    REPLIES.usage = { ...USAGE, keys: { aliyun: { code: 'NEEDS_HUMAN.AUTH_FAILED', caps: ['visionAI', 'summaryAI'] } } };
    e.p.v6Cache = {};
    // 修之前的路（只填空格子）：一格都换不掉——这就是她点「换一个 key」没反应的原因
    const was = JSON.stringify([e.p.settings.summaryAI, e.p.settings.visionAI]);
    await v6.addKey('sk-new-aliyun');
    assert.equal(JSON.stringify([e.p.settings.summaryAI, e.p.settings.visionAI]), was, '只填空格子：坏 key 那几格不动（旧 bug 的样子）');
    assert.ok(notices.some(n => /都已经配好了，没改/.test(String(n))));
    // 现在的路：pasteKey → 认出是阿里云 + 阿里云正用不了 → 换掉在用它的那几格
    const t = openPage(e.p); const r = t.containerEl; await settle();
    await openMore(r, 'ai-more');
    const box = r.querySelector('[data-section="ai-key-paste"]');
    box.querySelector('input').value = 'sk-new-aliyun';
    await box.querySelectorAll('button').find(b => b.textContent === '认出并用上').onclick(); await settle();
    const sent = e.calls.filter(a => a.join(' ').includes('keys detect'));
    assert.ok(sent.length && sent.every(a => !a.join(' ').includes('sk-new-aliyun')), 'key 不进命令行参数（走标准输入）');
    const s = e.p.settings;
    assert.equal(s.summaryAI.fallback.apiKey, 'sk-new-aliyun', '概要的备用（阿里云）换上新 key');
    assert.equal(s.visionAI.refine.apiKey, 'sk-new-aliyun', '识图第二层（阿里云）换上新 key');
    assert.ok(!s.summaryAI.apiKey && !s.visionAI.apiKey, 'Gemini 那几格（轮流用的免费 key）不动');
    assert.equal(s.summaryAI.fallback.keyFile, 'C:/keys/llm.csv', '原来的密钥文件引用没删（apiKey 排在前面，照样换得掉）');
    assert.equal(s.visionAI.refine.apiKeyEnv, 'DASHSCOPE_API_KEY');
    assert.ok(!s.textAI.apiKey, 'DeepSeek 那一格不动');
    assert.equal(e.saves.at(-1).visionAI.refine.apiKey, 'sk-new-aliyun', '写进 data.json');
    assert.ok(notices.some(n => /已换上新的 通义千问 key：用在 识图、概要/.test(String(n))), notices.slice(-3).join('|'));
    assert.equal(box.querySelector('input').value, '', '换完清空输入框');
    // 「换 key」按钮落到同一个输入框（唯一的 key 入口）
    t.hide();
    const t2 = openPage(e.p); const r2 = t2.containerEl; await settle();
    dom.document.body.appendChild(r2);
    r2.querySelector('.lb-key-trouble .lb-fix-line').querySelectorAll('button').find(b => b.textContent === '换 key').onclick();
    assert.ok(r2.querySelector('details[data-section="ai-more"]').open, '「换 key」→ 打开④「更多」');
    assert.equal(dom.document.activeElement, r2.querySelector('[data-section="ai-key-paste"] input'), '焦点落进粘 key 的那一格');
    t2.hide(); r2.remove();
    // 存失败：一格都不改
    const e2 = makePlugin({ visionAI: { mode: 'http', endpoint: BL, model: 'qwen3.8-flash', keyFile: 'k.csv' } });
    e2.p.saveFails = 1;
    await e2.p.settingsV6().replaceKey('aliyun', 'sk-x', ['visionAI']);
    assert.ok(!e2.p.settings.visionAI.apiKey, '没保存上：原来的 key 没动');
    REPLIES.usage = USAGE;
    // 只填空格子（没出问题的那家）：已经填好的地址和密钥引用一个不动
    const e3 = makePlugin({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-v4-flash', keyFile: 'k.csv' }, visionAI: { mode: 'http', endpoint: '', model: '' },
      setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text'], aiSynced: true } });
    e3.p.v6Cache = {};
    REPLIES.usage = { ...USAGE, keys: {} };
    await e3.p.settingsV6().pasteKey('sk-aliyun-fake');
    assert.equal(e3.p.settings.textAI.endpoint, 'https://api.deepseek.com/chat/completions'); assert.ok(!e3.p.settings.textAI.apiKey);
    assert.equal(e3.p.settings.visionAI.endpoint, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', '空着的识图填上');
    assert.equal(e3.p.settings.visionAI.apiKey, 'sk-aliyun-fake');
    assert.ok(e3.p.settings.setup.selected.includes('ai_vision'), '填上识图 → 识图打开');
    REPLIES.usage = USAGE;
  }

  // —— 4. 旧落点名照认；落点在收着的「更多」里：先打开、画出来，再滚，焦点落进能改的那一格 ——
  env.p.app.setting = { activeTab: null, open() {}, openTabById() {} };
  env.p.openPluginSettings = () => {};
  for (const [from, to, focus] of [['ai', 'ai', null], ['status', 'overview', 'status'], ['remote', 'connect', 'remote'], ['schedule', 'sync', 'schedule'],
    ['advanced', 'more', 'developer'], ['skills', 'more', 'skills'], ['usage', 'ai', 'ai-usage'], ['nope', 'overview', null]]) {
    env.p.openSetupPage(from); assert.equal(env.p.settingsView.tab, to, from + ' → ' + to); assert.equal(env.p.settingsView.focus, focus, from + ' 的落点');
  }
  {
    const e = makePlugin({}, { '_archive/catalog-data.json': '{"items":[]}' });
    const t = openPage(e.p); const r = t.containerEl;
    dom.document.body.appendChild(r);
    await settle();
    const v6 = e.p.settingsV6();
    for (const [sec, more, ctl] of [['skills', 'ai-more', null], ['ai-prompts', 'ai-more', null], ['attach', 'sync-more', 'input'], ['developer', 'repair-more', null], ['tokens', 'connect-more', null], ['index', 'catalog-more', null]]) {
      const el = v6.focusSection(t, sec);
      assert.ok(el, sec + '：画出来了');
      assert.ok(r.querySelector(`details[data-section="${more}"]`).open, sec + '：在「更多」里——先打开');
      assert.ok(el._scrolledIntoView && el.classList.contains('lb-flash'), sec + '：滚过去、闪一下');
      if (ctl) assert.equal(dom.document.activeElement, el.querySelector(ctl), sec + '：焦点落进能改的那一格');
    }
    const ai = v6.focusSection(t, 'ai-spend');
    assert.equal(dom.document.activeElement, ai.querySelector('input.lb-spend-input'), '每天上限：焦点落进输入框');
    notices.length = 0;
    assert.equal(v6.focusSection(t, 'no-such-thing'), null);
    assert.ok(notices.some(n => /还没画出来/.test(String(n))), '找不到：说一句，不是没反应');
    t.hide(); r.remove();
    // openSetupPage('remote') → 网页端那张卡；('skills') → ④「更多」里那一段
    e.p.app.setting = { activeTab: null, open() {}, openTabById() {} }; e.p.openPluginSettings = () => {};
    e.p.openSetupPage('skills');
    const t2 = openPage(e.p); await settle(); await new Promise(res => setTimeout(res, 80)); await settle();
    assert.ok(t2.containerEl.querySelector('details[data-section="ai-more"]').open, '「技能」落点：④「更多」打开');
    t2.hide();
  }

  // —— 5. 同步时间只有一个编辑器，改了自动存：首页 / 同步记录「改定时」/ plugin.openSyncTime() 都落到它；首次设置「同步」一步也是它 ——
  {
    let cur = { freq: 'none', enabled: false, installable: true };
    const saved = [];
    const e = makePlugin({ __fresh: true });
    e.p.getSyncSchedule = async () => JSON.parse(JSON.stringify(cur));
    e.p.setSyncRules = async rules => { saved.push(rules); cur = { freq: 'daily', enabled: true, rules, summary: '每天 ' + rules[0].times.join('、') }; return { ok: true, detail: '已保存：每天 ' + rules[0].times.join('、') }; };
    e.p.setSyncSchedule = async f => { saved.push(f); cur = { ...cur, enabled: false, summary: '已关闭' }; return { ok: true }; };
    e.p.app.setting = { activeTab: null, open() {}, openTabById() {} };
    e.p.openPluginSettings = () => {};
    for (const how of [() => e.p.openSyncTime(), () => e.p.openSetupPage('schedule'), () => e.p.openSyncSettings(), () => e.p.openSetupPage('sync-time')]) {
      how(); assert.ok(['sync-time', 'schedule'].includes(e.p.settingsView.focus), '落点是同步时间');
    }
    // 还在首次设置：直接停在「同步」那一步（里面就是那个编辑器）
    e.p.openSyncTime();
    let t = openPage(e.p); let r = t.containerEl; await settle(); await new Promise(res => setTimeout(res, 80)); await settle();
    assert.equal(r.querySelector('.lb-card-title').textContent, '同步', '首次设置里点「改定时」：停在同步那一步');
    assert.ok(r.querySelector('.lb-guide [data-section="sync-time"] .lb-sched'), '首次设置里是同一个时间编辑器');
    const times = () => r.querySelector('[data-section="sync-time"] input.lb-sched-times');
    assert.equal(times().value, '04:00', '还没开定时：推荐值');
    times().value = '06:30'; times().oninput();
    await r.querySelectorAll('.lb-guide-nav button').find(b => b.textContent === '下一步').onclick(); await settle();
    assert.deepEqual(saved.at(-1), [{ kind: 'daily', times: ['06:30'] }], '在这一步动过时间：「下一步」替她按这个时间打开');
    assert.equal(r.querySelector('.lb-card-title').textContent, '识别与问答');
    // 首次设置第 3 步和设置页④是同一批行（同一个值）：这里选的问答模型，设置页里就是它
    await pick(rowNamed(r, '问答模型'), 'Sonnet');
    assert.equal(e.p.settings.activeModel, 'Sonnet');
    assert.ok(r.querySelector('[data-section="ai-key-paste"]'), '第 3 步的 key 入口也是那一个');
    e.p.homeUI().runAll = async () => ({ ok: true });
    for (let k = 0; k < 2; k++) { const b = r.querySelectorAll('.lb-guide-nav button').find(x => x.textContent === '下一步' || x.textContent === '完成'); await b.onclick(); await settle(); }
    assert.equal(e.p.settings.onboarding.guideDone, true);
    t.hide();
    t = openPage(e.p); r = t.containerEl; await settle(); await new Promise(res => setTimeout(res, 80)); await settle();
    assert.ok(group(r, 'g-sync').querySelector('[data-section="sync-time"]'), '设置页里同一个编辑器');
    assert.equal(times().value, '06:30', '重进设置页：和首次设置里存的是同一份');
    assert.match(r.querySelector('.lb-sched-status').textContent, /每天 06:30/);
    assert.equal(rowNamed(group(r, 'g-sync'), '同步').querySelector('.checkbox-container').checked, true, '同步开关 = 计划任务开着');
    assert.equal(rowNamed(group(r, 'g-advanced'), '问答模型').querySelector('select').value, 'Sonnet', '首次设置选的问答模型，设置页里同一个值');
    // 改时间 → 不点按钮也存（打字停一会儿合并成一次）
    const n0 = saved.length;
    times().value = '07:0'; times().oninput(); times().value = '07:00'; times().oninput();
    assert.equal(saved.length, n0, '还在打字：不马上写计划任务');
    await new Promise(res => setTimeout(res, 1350)); await settle();
    assert.deepEqual(saved.slice(n0), [[{ kind: 'daily', times: ['07:00'] }]], '停手后自动存了一次（合并）');
    assert.match(r.querySelector('.lb-sched-msg').textContent, /^已保存/);
    // 格式不对：不存，说一句；离开那一格（change）立刻存
    times().value = '25:99'; times().oninput(); times().onchange(); await settle();
    assert.equal(saved.length, n0 + 1, '格式不对不存'); assert.match(r.querySelector('.lb-sched-msg').textContent, /时间格式不对/);
    times().value = '08:15'; times().oninput(); times().onchange(); await settle();
    assert.deepEqual(saved.at(-1), [{ kind: 'daily', times: ['08:15'] }], '离开那一格立刻存');
    // 关同步 → setSyncSchedule('off')，时间那一行收起来；再开 → 按编辑器里的时间注册
    const sw = rowNamed(group(r, 'g-sync'), '同步').querySelector('.checkbox-container');
    sw.checked = false; await sw.onchange(); await settle();
    assert.equal(saved.at(-1), 'off');
    assert.ok(rowNamed(group(r, 'g-sync'), '同步时间').classList.contains('is-hidden'), '关着：时间那一行收起来');
    sw.checked = true; await sw.onchange(); await settle();
    assert.deepEqual(saved.at(-1), [{ kind: 'daily', times: ['08:15'] }], '再开：按编辑器里的时间');
    t.hide();
    assert.equal(e.p.scheduleDraft, null, '存过了：不留草稿');
  }

  // —— 6. 首次设置：欢迎页两个大按钮；一键 = 扫码 → 完成（换成推荐那一组、开始跑）；自定义 = 四步 ——
  {
    const e3 = makePlugin({ __fresh: true });
    let ran = 0; e3.p.homeUI().runAll = async () => { ran++; return { ok: true }; };
    const t3 = openPage(e3.p); const r3 = t3.containerEl; await settle();
    assert.ok(pane(r3).querySelector('.lb-guide'), '库里还没有收藏：首次设置');
    assert.deepEqual(r3.querySelectorAll('.lb-big-name').map(x => x.textContent), ['推荐设置，一键开始', '自定义']);
    r3.querySelectorAll('button.lb-big')[0].onclick(); await settle();
    assert.equal(r3.querySelector('.lb-card-title').textContent, '登录小红书');
    assert.ok(r3.querySelector('.lb-acct-row'), '登录那一步就是账号卡片（扫码）');
    const done = r3.querySelectorAll('.lb-guide-nav button').find(b => b.textContent === '完成');
    await done.onclick(); await settle();
    assert.equal(e3.p.settings.onboarding.guideDone, true);
    assert.deepEqual(Array.from(e3.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock'], '推荐那一组（没 key 的 AI 先不勾）');
    assert.equal(ran, 1, '完成后开始一口气跑');
    assert.ok(!pane(r3).querySelector('.lb-guide') && group(r3, 'g-account'), '走完变成六组设置页');
    t3.hide();
    const e4 = makePlugin({ __fresh: true });
    const t4 = openPage(e4.p); const r4 = t4.containerEl; await settle();
    r4.querySelectorAll('button.lb-big')[1].onclick(); await settle();
    const titles = [];
    for (let i = 0; i < 4; i++) {
      titles.push(r4.querySelector('.lb-card-title').textContent);
      const next = r4.querySelectorAll('.lb-guide-nav button').find(b => b.textContent === '下一步');
      if (next) { await next.onclick(); await settle(); }
    }
    assert.deepEqual(titles, ['登录小红书', '同步', '识别与问答', '接入其他 AI（MCP）']);
    assert.deepEqual(r4.querySelectorAll('.lb-guide-step').map(s => s.textContent.replace(/[\d✓]/g, '')), ['登录小红书', '同步', '识别与问答', '接入其他 AI']);
    t4.hide();
    // 「重新走一遍首次设置」在⑥「更多」里
    const e5 = makePlugin({});
    const t5 = openPage(e5.p); await settle(); await openMore(t5.containerEl, 'repair-more');
    await rowNamed(t5.containerEl, '重新走一遍首次设置').querySelector('button').onclick(); await settle();
    assert.ok(pane(t5.containerEl).querySelector('.lb-guide'), '回到首次设置');
    t5.hide();
  }

  // —— 7. 全部打开后一项不少、单例只剩一处 ——
  for (const [k, cfg] of Object.entries(CONFIGS)) {
    const { p } = makePlugin({ ...cfg, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock', 'ai_text', 'ai_vision'], aiSynced: true } });
    const all = await inventory(p);
    const count = a => a.reduce((m, x) => m.set(x, (m.get(x) || 0) + 1), new Map());
    const per = k === 'alt' ? { '测试语音识别': '测试语音转文字（发 1 秒录音，几乎不花钱）' } : {};
    const base = BASELINE[k].map((x, i, a) => (x === '模型' && a[i - 1] === '归档摘要模型（默认同文本 AI）' ? (k === 'alt' ? '模型名' : '只换模型名') : per[x] || RENAMED[x] || x));
    const had = count(base), has = count(all);
    for (const [x, n] of Object.entries(MERGED)) if (had.has(x)) had.set(x, had.get(x) - n);
    const missing = [...had].filter(([x, n]) => !REMOVED.includes(x) && (has.get(x) || 0) < n).map(([x, n]) => `${x} ×${n - (has.get(x) || 0)}`);
    assert.deepEqual(missing, [], `配置 ${k}：少了这些设置项`);
    for (const x of [...REMOVED, '输入框里的提示字']) assert.ok(!all.includes(x), '不该再有：' + x);
    // 单例：页面上（不算「接口与密钥」逐项切过去的那几格）只出现一次
    const t = openPage(p); await settle(); await openAll(t.containerEl); await settle();
    const page = count(rowsOf(t.containerEl).map(idOf).filter(Boolean));
    const dup = ONCE.filter(x => (page.get(x) || 0) > 1).map(x => `${x} ×${page.get(x)}`);
    assert.deepEqual(dup, [], `配置 ${k}：重复的设置项要删到只剩一处`);
    const lost = ONCE.filter(x => !page.get(x));
    assert.deepEqual(lost, [], `配置 ${k}：这些应该在页上`);
    // 每项说明一行：静态说明 ≤ 60 字（多的在 ⓘ 悬停里）
    if (k === 'defaults') {
      const long = rowsOf(t.containerEl).map(r => [idOf(r), descText(r)]).filter(([n, d]) => !DYNAMIC.has(n) && d.length > 60).map(([n, d]) => `${n}：${d.length} 字`);
      assert.deepEqual(long, [], '说明太长（> 60 字）的项');
      assert.ok(!/OAuth|Bearer/.test(t.containerEl.querySelector('[data-section="g-connect"]').textContent.replace(/访问令牌[\s\S]*$/, '')), '主界面上没有 OAuth');
    }
    t.hide();
  }

  // —— 8. 没人读的键不再进默认值（她 data.json 里已有的照原样带着）——
  {
    const D = Plugin.__DEFAULTS;
    assert.equal(Object.keys(D.setup).join(), 'selected', 'setup.step / collapsed / passed 删了');
    assert.ok(!('connect' in D), 'connect.clients 删了');
    assert.ok(!('expandTerms' in D.retrieval));
    assert.ok(!['model', 'endpoint', 'apiKey'].some(k => k in D.ocr));
    const kept = Plugin.__merge({ connect: { clients: ['chatgpt'] }, setup: { selected: ['core'], step: 3, passed: [1] } });
    assert.equal(JSON.stringify(kept.connect), '{"clients":["chatgpt"]}', '她已有的不动');
    assert.equal(kept.setup.step, 3);
  }

  // —— 9. 收藏同步那一行（②）的说明 + 同步 / 问题状态文件监听，重画 / 关设置页注销 ——
  const syncDesc = async (files) => { const e = makePlugin({}, files); const t = openPage(e.p); await settle();
    const d = rowNamed(t.containerEl, '收藏同步').querySelector('.setting-item-description').textContent; t.hide(); return d; };
  assert.match(await syncDesc({ '_archive/problems-summary.json': JSON.stringify({ sync: { state: 'ready', last_success: new Date().toISOString(), new: 3, deferred: 1 } }) }),
    /^上次：今天 \d\d:\d\d · 新增 3 篇 · 还剩 1 篇 · 自动同步：没开$/);
  {
    const e = makePlugin({}, { '_archive/sync-status.json': JSON.stringify({ state: 'ready', message: '收藏同步完成', updated_at: '2026-10-02T04:20:00' }) });
    const handlers = []; let offs = 0;
    e.p.app.vault.on = (ev, cb2) => { const ref = { ev, cb: cb2, live: true }; handlers.push(ref); return ref; };
    e.p.app.vault.offref = ref => { ref.live = false; offs++; };
    const t = openPage(e.p); await settle();
    const desc = () => rowNamed(t.containerEl, '收藏同步').querySelector('.setting-item-description').textContent;
    assert.match(desc(), /^收藏同步完成/);
    const live = () => handlers.filter(h => h.live).length;
    assert.equal(live(), 4, '收藏同步那一行 2 个 + ⑥当前状态 2 个');
    e.files['_archive/sync-status.json'] = JSON.stringify({ state: 'running', message: '正在同步收藏：《a》查附件 / 下附件中', updated_at: new Date().toISOString(), done: 3, total: 10 });
    handlers.filter(h => h.live && h.ev === 'modify').forEach(h => h.cb({ path: '_archive/sync-status.json' }));
    await new Promise(r => setTimeout(r, 350)); await settle();
    assert.equal(desc(), '正在同步收藏：《a》查附件 / 下附件中 · 已完成 3/10 篇 · 剩 7 篇 · 自动同步：没开');
    t.display(); await settle();
    assert.equal(offs, 4); assert.equal(live(), 4, '重画整页：旧监听注销，新的接上');
    t.hide();
    assert.equal(live(), 0, '关设置页：全部注销');
  }

  // —— 10. 每天新收（默认 50，清空回 50，0 = 不限）· 评论（说明在 ⓘ 里）· 更多：每次新收上限 · 补评论间隔 ——
  {
    const f = Plugin.dailyNewLimitOf;
    assert.deepEqual([f(''), f('  '), f(null), f('abc'), f('-3'), f('2.5'), f('0'), f(30)], [50, 50, 50, 50, 50, 50, 0, 30]);
    const e = makePlugin({}); const t = openPage(e.p); await settle();
    const input = rowNamed(t.containerEl, '每天新收').querySelector('input');
    assert.equal(input.value, '50');
    input.value = ''; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 50, '清空回落 50');
    input.value = '0'; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 0, '0 = 不限，照存');
    const floors = rowNamed(t.containerEl, '评论');
    assert.match(helpOf(floors), /每一楼的回复都会抓全.*楼数只往上补.*抓全部评论/, 'ⓘ 里讲规则');
    assert.equal(floors.querySelector('.lb-help').textContent, 'ⓘ');
    e.p.saveFails = 1; notices.length = 0;
    const sel = floors.querySelector('select'); sel.value = '50'; await sel.onchange();
    assert.equal(e.p.settings.sync.commentFloors, 10); assert.equal(sel.value, '10');
    assert.ok(notices.some(n => String(n).includes('没保存上，已改回原来的楼数')));
    await openMore(t.containerEl, 'sync-more');
    const per = rowNamed(t.containerEl, '每次新收上限').querySelector('input');
    per.value = '20'; await per.oninput(); assert.equal(e.p.settings.sync.perRunLimit, 20);
    const pace = rowNamed(t.containerEl, '补评论间隔').querySelector('select');
    assert.deepEqual(pace.dropdown.options.map(o => o[0]), ['45', '90', '180']);
    pace.value = '180'; await pace.onchange(); assert.equal(e.p.settings.sync.commentFillGap, 180);
    t.hide();
  }

  // —— 11. 10-10 她的 data.json 事故：没有她明确操作，永不删密钥引用字段、不改已经填好的地址 ——
  {
    const DEDICATED = 'https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions';
    const HERS = {
      textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-v4-flash', apiKey: '', keyFile: 'C:/keys/llm.json', keyField: 'deepseek', maxTokens: 1200 },
      summaryAI: { mode: 'http', endpoint: DEDICATED, model: 'qwen3.7-flash', apiKey: '', apiKeyEnv: 'DASHSCOPE_API_KEY', keyFile: 'C:/keys/llm.json', keyField: 'qwen', requireKey: true },
      visionAI: { mode: 'http', endpoint: DEDICATED, model: 'qwen3.8-flash', refineModel: 'qwen3.8-max', apiKey: '', apiKeyEnv: 'DASHSCOPE_API_KEY', keyFile: 'C:/keys/llm.json', keyField: 'qwen', requireKey: true, videoScreenText: true },
      setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text', 'ai_vision'], aiSynced: true },
    };
    const AI = ['textAI', 'summaryAI', 'visionAI'];
    const e3 = makePlugin(JSON.parse(JSON.stringify(HERS)), { '_archive/catalog-data.json': '{"items":[]}' });
    const orig = JSON.stringify(AI.map(k => e3.p.settings[k]));
    e3.p.confirm = async () => true;
    assert.equal(await e3.p.homeUI().firstRun(), 'existing-library', '老库首次加载只记一笔');
    let t3 = openPage(e3.p); await settle(); await openAll(t3.containerEl); await settle();
    const api = t3.containerEl.querySelector('[data-section="ai-keys"]');
    for (const cap of ['summary', 'vision', 'refine', 'asr', 'embed', 'ask']) { api.lbPick(cap); await settle(); }
    await pick(rowNamed(group(t3.containerEl, 'g-advanced'), '语音转文字'), 'off');
    await pick(rowNamed(group(t3.containerEl, 'g-advanced'), '识图'), 'local');
    await pick(rowNamed(group(t3.containerEl, 'g-advanced'), '识图'), 'ai');
    t3.hide();
    assert.equal(JSON.stringify(AI.map(k => e3.p.settings[k])), orig, '问答 / 概要 / 识图的设置被改了（密钥引用字段被删、或地址被换）');
    for (const sv of e3.saves) assert.equal(JSON.stringify(AI.map(k => sv[k])), orig, '写进 data.json 的 AI 设置被改了');
    assert.ok(e3.saves.length > 0, '这一路确实存过');
  }

  // —— 12. ③「更多」：留言对象 · 编辑索引（四个次要链接，调 index-ui.js 挂的方法）· 索引文件 ——
  {
    const e5 = makePlugin({});
    const hits = [];
    Object.assign(e5.p, { openIndexFile: () => hits.push('open'), indexDraft: async () => { hits.push('draft'); }, openIndexSuggestions: () => hits.push('suggest'),
      indexRebuild: () => hits.push('rebuild'), indexUI: { indexRel: () => e5.p.settings.indexFile || '索引.md' }, run: async args => hits.push('run ' + args.slice(2).join(' ')) });
    const t5 = openPage(e5.p); await settle(); await openMore(t5.containerEl, 'catalog-more');
    const row = rowNamed(t5.containerEl, '编辑索引');
    const btns = row.querySelectorAll('button');
    assert.deepEqual(btns.map(b => b.textContent), ['打开 索引.md', 'AI 起草', '未归类建议', '重新整理目录']);
    assert.ok(btns.every(b => b.classList.contains('lb-link') && !b.classList.contains('mod-cta')), '都是次要链接');
    for (const b of btns) await b.onclick();
    await settle();
    assert.deepEqual(hits, ['open', 'draft', 'suggest', 'run catalog']);
    const input = rowNamed(t5.containerEl, '索引文件').querySelector('input');
    input.value = ' 我的/分类.md '; await input.oninput(); await settle();
    assert.equal(e5.p.settings.indexFile, '我的/分类.md'); assert.equal(hits.at(-1), 'rebuild', '换了索引文件：重算一次');
    const ment = rowNamed(t5.containerEl, '留言对象').querySelector('input');
    ment.value = ' fable '; await ment.oninput(); assert.equal(e5.p.settings.annotateMention, 'fable');
    t5.hide();
  }

  // —— 13. 问收藏页能换的模型（④「更多 → 接口与密钥 → 问答模型」）：勾选（至少留一个）· 就地改（不弹窗，改了就存，名字重了不存）· 删（能撤销）· 加 ——
  {
    const e = makePlugin({}); const t = openPage(e.p); await settle(); await openMore(t.containerEl, 'ai-more');
    const rows = () => t.containerEl.querySelectorAll('.lb-model-row');
    assert.deepEqual(rows().map(nameOf), ['文本 AI', 'Codex', 'Sonnet']);
    let trig = 0; e.p.app.workspace.trigger = ev => { if (ev === 'link-brain:models-changed') trig++; };
    const box = name => rows().find(r => nameOf(r) === name).querySelector('.lb-model-check');
    box('文本 AI').checked = false; await box('文本 AI').onchange(); await settle();
    assert.equal(e.p.settings.models[0].hidden, true);
    assert.equal(e.p.settings.activeModel, 'Codex', '当前选中的被取消：换成下一个勾着的');
    assert.ok(trig >= 1, '通知问收藏页重画下拉');
    box('Codex').checked = false; await box('Codex').onchange(); await settle();
    box('Sonnet').checked = false; await box('Sonnet').onchange(); await settle();
    assert.equal(box('Sonnet').checked, true, '最后一个不让取消');
    // 就地改
    rows().find(r => nameOf(r) === 'Sonnet').querySelectorAll('button').find(b => b.textContent === '改').onclick(); await settle();
    const ed = t.containerEl.querySelector('.lb-model-edit');
    assert.ok(ed, '就地展开（没有弹窗）');
    const nameIn = rowNamed(ed, '名字').querySelector('input');
    nameIn.value = 'Codex'; nameIn.fire('change'); await settle();
    assert.equal(e.p.settings.models[2].name, 'Sonnet', '名字重了不存');
    nameIn.value = 'Claude'; nameIn.fire('change'); await settle();
    assert.equal(e.p.settings.models[2].name, 'Claude'); assert.equal(e.p.settings.activeModel, 'Claude', '当前选中的改名：activeModel 跟着改');
    // 加
    await rowsOf(t.containerEl).find(r => r.querySelector('button')?.textContent === '加一个模型').querySelector('button').onclick(); await settle();
    assert.equal(e.p.settings.models.at(-1).name, '新模型');
    assert.ok(t.containerEl.querySelector('.lb-model-edit'), '加完就地展开，接着填');
    const chat = fs.readFileSync('link_brain/assets/chat-view.js', 'utf8');
    assert.match(chat, /filter\(m => m && m\.name && !m\.hidden\)/, '问收藏页的下拉只列勾着的');
    assert.match(chat, /p\.settings\.activeModel = modelPick\.value/, '问收藏页改的也是 activeModel（同一个值）');
    t.hide();
  }

  // —— 14. 技能（④「更多 → 问收藏的写法」）：说明行 + 刷新 / ＋ · 读收藏库 _skills · 隐藏列表 ——
  {
    const files = {};
    const e = makePlugin({}, files);
    e.p.app.vault.adapter.list = async dir => ({ folders: Object.keys(files).filter(f => f.startsWith(dir + '/') && f.endsWith('/SKILL.md')).map(f => f.slice(0, -'/SKILL.md'.length)), files: [] });
    files['_skills'] = '';
    files['_skills/recipe/SKILL.md'] = '---\nname: recipe\ndescription: 菜谱：列菜名、主料\n---\n正文';
    const t = openPage(e.p); await settle(); await openMore(t.containerEl, 'ai-more'); await new Promise(r => setTimeout(r, 60)); await settle();
    const lead = rowNamed(t.containerEl, '问收藏时按问题自动选用');
    assert.ok(lead, '说明行');
    assert.deepEqual(t.containerEl.querySelectorAll('.lb-skill-row').map(nameOf), ['recipe']);
    const hid = rowNamed(t.containerEl, '不自动选用这些技能').querySelector('input');
    hid.value = 'recipe， travel recipe'; await hid.oninput();
    assert.deepEqual(Array.from(e.p.settings.skills.hidden), ['recipe', 'travel']);
    t.hide();
  }

  // —— 15. ⑤：本机命令行 = textAI 走哪个命令行（选「不用」回到接口）；网页端打开后出网址 / 口令 / 几步做法（只有一份，照 docs/remote-access.md）——
  {
    const e = makePlugin({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'x', keyFile: 'k' } });
    e.p.settings.remote = { enabled: true, domain: 'https://lwa.example.com', port: 18071, folders: ['@xhs', 'D:/笔记'] };
    const t = openPage(e.p); const r = t.containerEl; await settle(); await settle();
    const cli = rowNamed(r, '命令行程序').querySelector('select');
    cli.value = 'claude'; await cli.onchange(); await settle();
    assert.deepEqual([e.p.settings.textAI.mode, e.p.settings.textAI.preset, e.p.settings.textAI.prevMode], ['cli', 'claude', 'http']);
    assert.equal(e.p.settings.textAI.keyFile, 'k', '换命令行不删 key 引用');
    cli.value = ''; await cli.onchange(); await settle();
    assert.equal(e.p.settings.textAI.mode, 'http', '「不用」= 回到接口');
    const web = r.querySelector('[data-section="remote"]');
    for (const n of ['你的网址', '连接地址', '口令']) assert.ok(rowNamed(web, n), '网页端开着：' + n);
    assert.equal(r.querySelectorAll('.setting-item').filter(x => nameOf(x) === '连接地址').length, 1, '「连接地址」只有一处');
    const how = web.querySelector('details[data-section="web-howto"]');
    assert.match(how.textContent, /claude\.ai（网页 \/ 手机 App）：设置 → Connectors → Add custom connector/);
    assert.match(how.textContent, /ChatGPT：设置 → Apps & Connectors → Advanced settings，打开 Developer mode/);
    assert.equal(r.querySelectorAll('[data-section="web-howto"]').length, 1, '接入步骤只有一份');
    assert.ok(!/OAuth/.test(web.textContent), '网页端卡片上没有 OAuth 这个词');
    await openMore(r, 'connect-more');
    assert.ok(rowNamed(r, 'D:/笔记'), '其他开放的文件夹在「更多」');
    assert.ok(!rowsOf(r.querySelector('[data-section="connect-more"]')).some(x => nameOf(x) === '小红书收藏库'), '收藏库那个开关只在外面一处');
    for (const n of ['端口', '访问令牌（给不支持口令的软件）', '全部断开']) assert.ok(rowNamed(r, n), '更多里：' + n);
    t.hide();
  }

  console.log('PASS settings page 1027 (six groups): anchors + 账号登录 / 收藏与同步 / 目录与批注 / 高级功能 / CLI 与外接 MCP / 修复, 「＋ 更多」 lazy, one 立即同步, one sync-time editor that autosaves (debounced, invalid not saved, change flushes) with a 同步 switch, wizard and settings share the same rows and values, feature selects drive setup.selected + modes (dual gate) with revert on failed save, paste-a-key replaces the failing provider\'s slots (old fill-blanks-only bug reproduced) and otherwise fills blanks, refine model edits the effective key, landing names open the right 「更多」, nothing lost vs pre-1009 inventory and no duplicates, unread default keys dropped, data.json key refs never touched, models edited inline');
})().catch(e => { console.error(e); process.exitCode = 1; });

// 1026（录屏场景 08）：按要做的事排六组；状态行落到能改的控件；同步时间只有一个编辑器（设置页 · 首次设置 · plugin.openSyncTime()）。
// 1018 她批 v6：不分页签、一页五张卡 + 首次设置（settings-v6.js）；下面 1010 / 1015 的规矩照守，页签那几条改成「落点」。
// 设置页（1010 她：「原本的设置分栏还是需要的」——恢复分栏，按「什么都不懂的新用户」重写；1015 她：照 claudian 改成 通用 / 模型与提供商 / 技能 三个页签 + 圆角卡片）。
// 守住 1009 的两条：每个设置只出现在一处；装上自动跑轻量版、一键装好 / 跑完（docs/SETUP-CONTRACT.md 10-10 修订）。
// 断言：
//   1. 三栏（通用 / 模型与提供商（子页签）/ 技能），默认通用；一次只画一栏；每栏最多一个主按钮；每组一张卡片（标题 + 内容）；
//      概览 = 账号 · 收藏同步（只有次要的「立即同步」「改时间」）· 评论补齐 · 问题 · 这台电脑 +「一键装好 / 跑完」；
//   2. AI 那一栏的开关改 setup.selected（依赖联动）并对上实际起作用的设置（OCR 方式 / 本机语音 / CapsLock / AI 方式）；
//      子选项（按住 CapsLock 说话）只在父开关打开后出现；AI 打开原地出接口那几格 + 价钱；
//   3. 停在哪一栏记在插件对象上，不写 data.json；「打开设置」的旧落点名照认；
//   4. 五栏全打开（AI 全开、五个软件都勾、折叠都展开）后，第 7 批以来的设置项一项不少（改名 / 合并按表对上），列出的单例只出现一次；
//   5. 收藏同步说明行；6. 同步 / 补评论 / 问题状态文件监听，重画 / 切栏 / 关设置页注销；7. 每天最多新收几篇、每篇评论抓几楼；8. 同步计划说明；
//   9. 每项说明一行（≤ 60 字，多的在「?」悬停里）；10. 开关存失败拨回原值。
//  11. 10-10 目录分类 = 索引.md：编辑索引 / AI 起草 / 未归类建议 / 重新整理目录（次要链接，调 index-ui.js 挂的方法；没加载上只说一句）+ 索引文件路径。
// 不起真进程（CONVENTIONS §7.5）：child_process 换成一碰就炸的桩，runPy / 账号卡片是替身，home-ui / remote-ui / onboarding-ui / schedule-ui 是真的。
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
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings; module.exports.__TABS = SETTING_TABS; module.exports.__SUBTABS = SETTING_SUBTABS;', context);
const Plugin = context.module.exports;
const PLUGIN_DIR = '../obsidian-plugins/link-brain-actions/';

// —— 后端替身：按子命令回 SETUP-CONTRACT / connect / remote 的形状 ——
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
const REPLIES = {
  'setup plan': PLAN,
  'setup estimate': { ok: true, items: [{ id: 'summary', name: '概要 + 打标', provider: 'DeepSeek', model: 'x', yuan: 0.8, per: '100 篇', endpoint: 'https://api.deepseek.com/chat/completions', key_url: 'https://platform.deepseek.com/api_keys' },
    { id: 'ask', name: '问答（每问一次）', provider: 'DeepSeek', model: 'x', yuan: 0.004, per: '次' }], prices: { as_of: '2026-10-03' } },
  'comments --fill-status': { ok: true, pending: 12, ready: 12, cooling: 0, stuck: 0, missing: 340, running: false, message: '12 篇的评论还没补齐' },
  'connect status': { ok: true, clients: { 'claude-code': { installed: true, connected: false, command: 'claude mcp add lwa -s user -- python -m link_brain mcp' },
    'claude-desktop': { installed: true, connected: true } }, json: '{"mcpServers":{}}',
    apps: [{ id: 'claude-code', name: 'Claude Code', installed: true, oneclick: true, version: '2.1.3', connected: false },
      { id: 'claude-desktop', name: 'Claude 桌面版', installed: true, oneclick: true, version: '', connected: true },
      { id: 'codex', name: 'Codex', installed: true, oneclick: true, version: '0.146.0', connected: false },
      { id: 'opencode', name: 'OpenCode', installed: true, oneclick: false, version: '1.19.3', connected: false }],
    not_installed: ['Pi', 'Grok Build', 'DeepSeek Harness'] },
  'usage': { ok: true, budget: { daily_yuan: 3, spent_today: 0.83, over: false }, summary: { month: { deepseek: { cost: 12.5, calls: 300 }, aliyun: { cost: 8.06, calls: 90 } } },
    keys: { aliyun: { code: 'NEEDS_HUMAN.QUOTA_EXCEEDED' } }, links: { aliyun: { recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge' } },
    features: [
      { id: 'ask', name: '问收藏', cap: 'textAI', on: true, state: 'ok', chain: [{ label: 'DeepSeek', provider: 'deepseek', price: '约 ¥0.004 / 次' }] },
      { id: 'summary', name: '概要 · 打标签', cap: 'summaryAI', on: true, state: 'ok', chain: [{ label: 'DeepSeek', provider: 'deepseek' }] },
      { id: 'vision', name: '识图', cap: 'visionAI', on: true, state: 'backup', state_text: '已换用 通义千问', chain: [{ label: '通义千问', provider: 'aliyun' }] },
      { id: 'refine', name: '精细识图', cap: 'visionAI.refine', on: true, state: 'ok', chain: [{ label: '通义千问', provider: 'aliyun' }] },
      { id: 'embed', name: '按意思搜', cap: 'embedAI', on: true, state: 'ok', chain: [{ label: '通义千问', provider: 'aliyun' }] }] },
  'keys detect': { ok: true, provider: 'aliyun', name: '通义千问', message: '认出是 通义千问', fills: {
    textAI: { endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen3.7-flash' },
    visionAI: { endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen3.8-flash' } } },
  'remote status': { ok: true, state: 'running', message: '运行中（127.0.0.1:18071）', auth: { passphrase_set: true, passphrase_copyable: true, clients: [], personal: [] }, recent: [] },
  'sync-schedule': { task: null, freq: 'none', enabled: false, installable: true },
};
function reply(args) {
  const sub = args.slice(2).join(' ');
  const key = Object.keys(REPLIES).find(k => sub.startsWith(k));
  return key ? REPLIES[key] : { ok: true };
}

// —— 搭一个插件对象：真的 renderSyncRow / readSyncStatus / onboarding-ui / home-ui / remote-ui / schedule-ui，假的 vault / 账号卡片 ——
function makePlugin(saved, files = {}) {
  const p = new Plugin();
  const saves = [], calls = [];
  p.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async f => f in files, read: async f => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f]; } },
    getAllLoadedFiles: () => [] }, workspace: { getActiveFile: () => null } };
  p.manifest = { dir: '.obsidian/plugins/link-brain-actions' };
  p.lbRoot = '';
  const fresh = saved && saved.__fresh;
  if (saved) delete saved.__fresh;
  p.settings = Plugin.__merge(saved);
  if (!fresh && !(saved && saved.onboarding)) p.settings.onboarding = { ...(p.settings.onboarding || {}), guideDone: true };   // 1018 v6：老用例都当已经走完首次设置
  if (saved && saved.remote) p.settings.remote = saved.remote;
  p.loadData = async () => JSON.parse(JSON.stringify(p.settings));
  p.saveFails = 0;
  p.saveSettings = async () => { if (p.saveFails > 0) { p.saveFails--; throw new Error('磁盘满了（合成）'); } saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.notify = (m) => notices.push(m);
  p.renderAccounts = c => { c.createDiv({ cls: 'lb-accounts' }).createDiv({ cls: 'setting-item lb-acct-row' }); };
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
  p.syncNow = async () => {};
  p.copyText = async () => {};
  return { p, saves, files, calls };
}
function openPage(p, tabId = null, sub = null) {
  if (tabId) p.settingsView = { ...(p.settingsView || {}), tab: tabId };
  if (sub) p.settingsView.sub = { ...(p.settingsView.sub || {}), [tabId]: sub };
  const tab = new Plugin.__SettingTab({}, p); p.settingTab = tab; tab.display(); return tab;
}
// 每个页签 × 子页签（1015：模型与提供商下面有子页签）
// 1018 v6：一页（旧的页签名只是落点）
const PAGES = () => [[null, null]];
const cardOf = (root, section) => root.querySelector(`.lb-card[data-section="${section}"]`);
const flush = () => new Promise(r => setTimeout(r, 0));
const settle = async (n = 8) => { for (let i = 0; i < n; i++) await flush(); };
// 1018 v6：「更多」里每一项是一行折叠，点开才画
// 假 DOM 设 open 不会自己发 toggle（浏览器会）：这里补发；里面画过一次就不再画
const openRow = async (root, section) => { const d = root.querySelector(`details[data-section="${section}"]`); if (d) { d.open = true; d.fire('toggle'); } await settle(); };

// 一个元素此刻用户看不看得见：祖先里有收起的 details（不在 summary 里）或 is-collapsed / hidden
function visible(el, root) {
  for (let n = el; n && n !== root; n = n.parentNode) {
    if (n.hidden || n.classList?.contains('is-collapsed')) return false;
    const up = n.parentNode;
    if (up && up.tagName === 'DETAILS' && !up.open && n.tagName !== 'SUMMARY') return false;
  }
  return true;
}
const rowsOf = root => root.querySelectorAll('.setting-item');
const nameOf = row => { const n = row.querySelector('.setting-item-name'); if (!n) return ''; return [...n.childNodes].filter(c => !(c.classList && (c.classList.contains('lb-help') || c.classList.contains('lb-price') || c.classList.contains('lb-logo') || c.classList.contains('lb-app-ver')))).map(c => c.textContent).join('').trim(); };
const idOf = row => nameOf(row) || row.querySelectorAll('button').map(b => b.textContent.trim()).join('+') || (row.classList.contains('lb-acct-row') ? '〔账号卡片〕' : '');
const pane = root => root.querySelector('.lb-tab-pane');
const visibleRows = (root) => rowsOf(pane(root)).filter(r => visible(r, root)).map(idOf);
const ctas = root => pane(root).querySelectorAll('button').filter(b => b.classList.contains('mod-cta')).map(b => b.textContent);
const descText = row => { const d = row.querySelector('.setting-item-description'); if (!d) return ''; return [...d.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent).join('').trim(); };
// 展开里面再有折叠的（更多 → 每项功能用哪个模型 → 每一项）：一层层展开到没有收着的
const openFolds = root => { for (let k = 0; k < 4; k++) { const shut = root.querySelectorAll('details').filter(d => !d.open); if (!shut.length) break; for (const d of shut) { d.open = true; d.fire('toggle'); } } };
// 一栏的清单（行 + 电脑需求那几行 + 连接其他 AI 一整块）
function inventoryOf(root) {
  const items = rowsOf(root).map(idOf).filter(Boolean);
  const req = root.querySelectorAll('div').filter(d => /^· /.test(d.textContent) && !d.children.length).map(d => '电脑需求' + d.textContent.slice(1, 12));
  const conn = root.querySelector('.lb-connect') ? ['〔连接其他 AI〕'] : [];
  return [...items, ...req, ...conn];
}

// 改动前（第 7 批五个分页全部展开）的设置项清单——每种配置一份。1009 一页、1010 分栏：只许挪地方 / 改名 / 合并重复，不许丢。
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
const REMOVED = ['搜索收藏'];   // 目录页本来就有入口
// 1009 / 1010 挪了地方、换成新手说法、合并了重复的行（内容没少）：旧身份 → 新身份
const RENAMED = {
  '评论 · 自动拉取': '每篇评论抓几楼', '评论 · 手动拉取': '每篇评论抓几楼',     // 1010：合成一项，手动的差别是一行小字
  '每天最多新抓': '每天最多新收几篇', '文本 AI': '问收藏 / 概要改用本机命令行', 'API Key': '密钥（API Key）', '模型': '模型名',
  '测试文本 AI': '测试（发一句话，几乎不花钱）', '归档摘要模型（默认同文本 AI）': '写概要用的模型', '测试归档摘要': '测试概要模型（发一段短文，几乎不花钱）',
  '识图接口': 'AI 识图', '精细识别模型': '精细识图模型', '测试识图': '测试识图（发一张小图，几乎不花钱）', '视频画面文字': '认视频画面里的字',
  '语音识别': '视频转文字改用在线接口', '端口': '本机语音识别的端口', 'CapsLock 语音输入': '按 CapsLock 转文字', 'CapsWriter 目录': 'CapsWriter 装在哪',
  '输入框提示文字': '输入框里的提示字', DeepSeek: '文本 AI', '添加模型': '加一个模型', '其他客户端（JSON 配置）': '其他应用', '测试 MCP': '测一下本机的连接程序（MCP）',
  '批注昵称': '批注署名', '检查本机环境': '检查这台电脑', '文字识别（OCR）': '识图', '识别精度': '认字精度', '模型目录（可选）': '认字模型放在哪（可选）',
  '测试 OCR': '测试认字（本机跑，不花钱）', '摘要提示词（归档时抽取）': '写概要的提示词', '问答提示词（/问AI）': '问收藏的提示词',
  '回答输出上限（max_tokens）': '回答最长多少（max_tokens）', '发给模型的总字符上限': '最多给模型看多少字', '每篇片段字符上限': '每篇最多摘多少字',
  '送模型的片段篇数（topK）': '最多参考几篇（topK）', '先用小模型扩检索词': '提问时先想几个同义词一起搜', '载入当前分类+清空（用内置）+重建目录': '编辑索引',   // 10-10 索引树：分类文本框换成「编辑索引 / AI 起草 / 未归类建议 / 重新整理目录」
  '等待手动下载（分钟）': '等下载最多几分钟', '待补附件': '还没下到的附件',
  '电脑需求 收藏问答：文本模型（': '电脑需求 问收藏：文本模型（现', '电脑需求 图片文字：本地 OC': '电脑需求 图片里的字：本地 O',
  '电脑需求 视频：语音转写走上面': '电脑需求 视频：语音转文字默认', '电脑需求 语音输入：CapsW': '电脑需求 说话打字：CapsW', '〔远程阅读〕': '〔连接其他 AI〕',
  '测试语音识别': '测试语音转文字（本机跑，不花钱）',
  '登录后自动同步': '登录后马上同步', '下载图片': '存图片', '下载视频': '保存视频',   // 1016 改说法；1018 v6 叫「保存视频」
};
// 合并的：本机 AI 的复制命令只留一处（第二个 Codex 合进「其他 AI 软件」的设置片段）；「评论 · 手动拉取」合进「每篇评论抓几楼」
const MERGED = { Codex: 1, '每篇评论抓几楼': 1 };
// 这些设置只许出现一次（别处有重复的一律删掉只留一处）
const ONCE = ['〔账号卡片〕', '收藏同步', '每天最多新收几篇', '存图片', '保存视频', '每篇评论抓几楼', 'AI 识图', '按 CapsLock 转文字', 'Claude Code', '测一下本机的连接程序（MCP）',
  '视频转文字改用在线接口', '写概要用的模型', '评论补齐', '收藏放在哪', '后端命令', '自动同步时间', '识图', '语音', '概要', '按意思搜', '每天最多花', '问收藏用的模型'];
// 动态状态行（说明是现读的状态，不算「每项说明一行」的说明文字）
const DYNAMIC = new Set(['〔账号卡片〕', '收藏同步', '评论补齐', '问题', '这台电脑', '文本 AI', 'Codex', 'Sonnet', '远程访问', '口令', '连接地址', 'Claude Code', 'Claude Desktop', '你的网址', '远程访问的运行情况']);

(async () => {
  // —— 1. 1018 v6：不分页签，一页五张卡（状态 · 小红书 · 识别与问答 · 知识库接入 AI · 更多）；库里已有收藏就不出首次设置；最多一个主按钮 ——
  const sum = { updated_at: '2026-10-02T04:20:00', needs_human: 1, auto: 2, gave_up: 0, sync: { state: 'ready', message: '收藏同步完成', last_success: '2026-10-02T04:12:00', new: 3, deferred: 0, updated_at: '2026-10-02T04:20:00' } };
  let env = makePlugin({ onboarding: { guideDone: true } }, { '_archive/problems-summary.json': JSON.stringify(sum), '_archive/catalog-data.json': '{"items":[]}' });
  let tab = openPage(env.p); let root = tab.containerEl;
  await settle();
  assert.ok(!root.querySelector('.lb-tabs'), '没有页签了');
  assert.equal(root.querySelectorAll('.lb-tab-pane').length, 1);
  // 1026（录屏场景 08）：按要做的事排——状态 + ① 收藏与同步 ② 内容、目录及管理 ③ 识别与问答 ④ 模型与费用 ⑤ 外部 AI 接入 ⑥ 高级 / 修复
  assert.deepEqual(pane(root).querySelectorAll('.lb-card').map(c => c.getAttribute('data-section')), ['s-status', 's-xhs', 's-content', 's-ai', 's-cost', 's-mcp', 's-more']);
  assert.deepEqual(pane(root).querySelectorAll('.lb-card-title').map(c => c.textContent), ['状态', '收藏与同步', '内容、目录及管理', '识别与问答', '模型与费用', '外部 AI 接入', '高级 / 修复']);
  assert.ok(!pane(root).querySelector('.lb-guide'), '库里已经有收藏：不出首次设置');
  const st = cardOf(root, 's-status');
  assert.ok(st.querySelector('.lb-lamp'), '状态卡有信号灯');
  assert.deepEqual(rowsOf(st).map(idOf), ['〔账号卡片〕', '收藏同步', 'API 费用', '识别', '读取']);
  const statusRow = n => rowsOf(root).find(r => nameOf(r) === n);
  assert.deepEqual(statusRow('收藏同步').querySelectorAll('button').map(b => b.textContent), ['立即同步', '改时间']);
  assert.match(descText(statusRow('API 费用')), /今天 ¥0\.83 · 本月 ¥20\.6 · 每天上限 ¥3/);
  assert.match(descText(statusRow('读取')), /已接入 Claude 桌面版/);
  assert.ok(ctas(root).length <= 1, '最多一个主按钮：' + ctas(root));
  // 黄灯只有两种在这里修：key 欠费 / 失效 → 一句 + 去充值 + 换一个 key
  const fix = st.querySelector('.lb-fix-line');
  assert.ok(fix && /通义千问 额度用完或余额不足/.test(fix.textContent), '欠费那一句');
  assert.deepEqual(fix.querySelectorAll('button').map(b => b.textContent), ['去充值 ↗', '换一个 key']);
  assert.ok(st.querySelector('.lb-lamp.is-warn'), 'key 出问题：黄灯');
  // 收藏与同步：常用的平铺（自动同步时间 · 每天最多新收 · 评论 · 保存视频 · 存图片 · 同步记录），技术细项在本组「高级」折叠里（点开才画）
  const xhs = cardOf(root, 's-xhs');
  assert.deepEqual(rowsOf(xhs).map(idOf).filter(n => n !== ''), ['自动同步时间', '每天最多新收几篇', '每篇评论抓几楼', '保存视频', '存图片', '同步记录']);
  assert.ok(xhs.querySelector('[data-section="sync-time"] .lb-sched'), '唯一的自动同步时间编辑器在「收藏与同步」里，带落点 sync-time');
  assert.deepEqual(xhs.querySelectorAll('details').map(d => d.getAttribute('data-section')), ['sync-more']);
  // 内容、目录及管理：批注署名 · 留言对象平铺；目录与写法 · 附件 是折叠
  const content = cardOf(root, 's-content');
  assert.deepEqual(rowsOf(content).map(idOf).filter(n => n !== ''), ['批注署名', '留言对象', '回收站']);
  assert.deepEqual(content.querySelectorAll('details').map(d => d.getAttribute('data-section')), ['skills', 'attach']);
  // 识别与问答：本机两项（语音转文字没开 → CapsLock 子项不出）+ 用 key 的三项 + 问收藏模型；提示词在本组「高级」（每天上限只在「模型与费用」一处）
  const ai = cardOf(root, 's-ai');
  assert.deepEqual(rowsOf(ai).map(idOf), ['识图', '语音', '按意思搜', '概要', 'AI 识图', '问收藏用的模型']);
  assert.deepEqual(ai.querySelectorAll('details').map(d => d.getAttribute('data-section')), ['ai-prompts']);
  // 模型与费用：今天 / 本月 / 每天上限 → 每个功能用谁 → 钥匙串 → 花了多少（平铺，三种看法切换）
  const cost = cardOf(root, 's-cost');
  assert.ok(cost.querySelector('[data-section="ai-spend"] input.lb-spend-input'), '每天上限的输入框在「模型与费用」');
  assert.equal(root.querySelectorAll('input.lb-spend-input').length, 1, '每天上限只有一个输入框');
  assert.deepEqual(cost.querySelectorAll('.lb-sec-h').map(h => h.getAttribute('data-section')), ['ai-routes', 'ai-api', 'ai-usage']);
  assert.deepEqual(cost.querySelectorAll('.lb-usage-dim').map(b => b.textContent), ['按服务商', '按 API 或模型', '按功能']);
  assert.deepEqual(ai.querySelectorAll('.lb-pv').map(x => x.getAttribute('data-provider') || x.textContent), ['deepseek', 'aliyun', '＋ 添加 key']);
  assert.ok(ai.querySelector('.lb-pv[data-provider="aliyun"]').classList.contains('is-warn'), '欠费那家标黄');
  // 外部 AI 接入：接入电脑端（照 Claudian 认）· 接入网页端（说明 + 域名 / 口令 / 令牌紧挨着）· 可读取哪些库；开没开在标题右边
  const mcp = cardOf(root, 's-mcp');
  assert.deepEqual(mcp.querySelectorAll('.lb-grp').map(g => g.textContent.split(' · ')[0]), ['接入电脑端', '接入网页端', '可读取哪些库']);
  assert.match(mcp.querySelector('.lb-mcp-state').textContent, /^只读 · 电脑端已接入 1 个 · 网页端没开$/);
  assert.deepEqual(mcp.querySelectorAll('.lb-app').map(r => r.getAttribute('data-app')), ['claude-code', 'claude-desktop', 'codex', 'opencode', 'other']);
  assert.match(mcp.querySelector('.lb-app[data-app="opencode"]').textContent, /复制设置/, '写法不确定的只给复制设置');
  assert.match(mcp.querySelector('.lb-note').textContent, /Pi、Grok Build、DeepSeek Harness 没装/);
  assert.deepEqual(mcp.querySelectorAll('details.lb-row-fold').map(d => d.getAttribute('data-section')), ['web-howto', 'remote', 'mcp-folders']);
  assert.match(mcp.querySelector('details[data-section="mcp-folders"] summary').textContent, /小红书收藏库/, '开放的库直接写在那一行上');
  // 网页端：点开就是步骤（照 ChatGPT 现在的界面：插件 → 浏览目录 → 添加 → 添加自定义 MCP 服务器），也能一键复制
  const how = mcp.querySelector('details[data-section="web-howto"]');
  how.open = true; how.fire('toggle');
  assert.match(how.textContent, /添加自定义 MCP 服务器/); assert.match(how.textContent, /创建为插件/);
  assert.ok(how.querySelector('summary button').textContent === '复制接入说明');
  tab.hide();

  // —— 2. 识别与问答的开关：本机项改 setup.selected（依赖联动）+ 实际起作用的设置；子项；存失败拨回；按意思搜 / 概要是各自的 mode ——
  env = makePlugin({ onboarding: { guideDone: true } });
  tab = openPage(env.p, 'ai'); root = tab.containerEl; await settle();
  const feat = id => root.querySelector(`.lb-feat[data-id="${id}"]`);
  const flip = async (id, on) => { const cb = feat(id).querySelector('.checkbox-container'); cb.checked = on; await cb.onchange(); await settle(); };
  assert.ok(!feat('capslock'), '语音转文字没开：「按住 CapsLock 说话」这个子选项不出');
  assert.equal(feat('ocr').querySelector('.lb-meta').textContent, '免费 · 本机');
  await flip('asr', true);
  assert.ok(feat('capslock'), '父开关打开后，子选项出现');
  await flip('capslock', true);
  assert.deepEqual(Array.from(env.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock'], '勾 CapsLock → 语音识别也在');
  assert.equal(env.p.settings.voice.capsLock, true, 'CapsLock 客户端跟着开');
  await flip('asr', false);
  assert.deepEqual(Array.from(env.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr'], '取消语音识别 → CapsLock 跟着取消');
  assert.equal(env.p.settings.asrAI.mode, 'off');
  assert.ok(!feat('capslock'));
  await flip('ocr', false);
  assert.equal(env.p.settings.ocr.mode, 'off', 'OCR 开关就是 OCR 的唯一开关');
  notices.length = 0; env.p.saveFails = 1;
  const before = JSON.stringify(env.p.settings.setup.selected);
  await flip('ocr', true);
  assert.equal(JSON.stringify(env.p.settings.setup.selected), before, '存失败：选择还原');
  assert.equal(env.p.settings.ocr.mode, 'off', '存失败：OCR 方式还原');
  assert.equal(feat('ocr').querySelector('.checkbox-container').checked, false, '开关拨回关');
  assert.ok(notices.some(n => String(n).includes('没保存上，开关已拨回原来的位置')), notices.join('|'));
  // 概要：关 = summaryAI.mode off（记住原来的），开 = 还原 + 勾上「问收藏 · 概要 · 打标」
  const capCb = cap => root.querySelector(`.lb-feat[data-cap="${cap}"] .checkbox-container`);
  env.p.settings.summaryAI = { mode: 'http', endpoint: 'https://x/v1/chat/completions', apiKey: 'k' };
  capCb('summaryAI').checked = false; await capCb('summaryAI').onchange(); await settle();
  assert.equal(env.p.settings.summaryAI.mode, 'off'); assert.equal(env.p.settings.summaryAI.prevMode, 'http');
  assert.equal(env.p.settings.summaryAI.apiKey, 'k', '关掉不动 key');
  capCb('summaryAI').checked = true; await capCb('summaryAI').onchange(); await settle();
  assert.equal(env.p.settings.summaryAI.mode, 'http'); assert.ok(!('prevMode' in env.p.settings.summaryAI));
  assert.ok(env.p.settings.setup.selected.includes('ai_text'), '打开概要 → 勾上问收藏那一组（后台门禁看它）');
  capCb('embedAI').checked = false; await capCb('embedAI').onchange(); await settle();
  assert.equal(env.p.settings.embedAI.mode, 'off');
  tab.hide();

  // —— 1018 她「识图还没配」：关掉识图转文字顺带关掉识图，再打开认字要把识图一起开回来 ——
  {
    const e5 = makePlugin({ onboarding: { guideDone: true }, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text', 'ai_vision'], aiSynced: true } });
    const t5 = openPage(e5.p, 'ai'); await settle();
    const cb = () => t5.containerEl.querySelector('.lb-feat[data-id="ocr"] .checkbox-container');
    cb().checked = false; await cb().onchange(); await settle();
    assert.ok(!e5.p.settings.setup.selected.includes('ai_vision'), '关认字：依赖它的识图跟着关');
    cb().checked = true; await cb().onchange(); await settle();
    assert.ok(e5.p.settings.setup.selected.includes('ai_vision'), '再开认字：识图一起开回来');
    t5.hide();
  }

  // —— 粘一把 key：认出是哪家，只往空着的格子里填；已经填好的地址和密钥引用一个不动 ——
  {
    const e2 = makePlugin({ onboarding: { guideDone: true }, textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-v4-flash', keyFile: 'k.csv' },
      visionAI: { mode: 'http', endpoint: '', model: '' } });
    const v6 = e2.p.settingsV6();
    const got = await v6.addKey('sk-aliyun-fake');
    assert.equal(got.provider, 'aliyun');
    const sent = e2.calls.find(a => a.join(' ').includes('keys detect'));
    assert.ok(sent && !sent.join(' ').includes('sk-aliyun-fake'), 'key 不进命令行参数（走标准输入）');
    assert.equal(e2.p.settings.textAI.endpoint, 'https://api.deepseek.com/chat/completions', '已经填好的地址不动');
    assert.equal(e2.p.settings.textAI.keyFile, 'k.csv'); assert.ok(!e2.p.settings.textAI.apiKey, '已有密钥引用：不塞新 key');
    assert.equal(e2.p.settings.visionAI.endpoint, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', '空着的识图填上');
    assert.equal(e2.p.settings.visionAI.model, 'qwen3.8-flash'); assert.equal(e2.p.settings.visionAI.apiKey, 'sk-aliyun-fake');
    assert.ok(e2.p.settings.setup.selected.includes('ai_vision'), '填上识图 → 识图打开');
  }

  // —— 3. 旧落点名照认（问题面板「打开设置」带 'ai'、「去扫码 / 验证」带 'status'、远程带 'remote'）：滚到对应那张卡 / 展开那一行 ——
  env.p.app.setting = { activeTab: null, open() {}, openTabById() {} };
  env.p.openPluginSettings = () => {};
  for (const [from, to, focus] of [['ai', 'ai', null], ['status', 'overview', 'status'], ['remote', 'connect', 'remote'], ['schedule', 'sync', 'schedule'],
    ['advanced', 'more', 'developer'], ['skills', 'more', 'skills'], ['usage', 'ai', 'ai-usage'], ['nope', 'overview', null]]) {
    env.p.openSetupPage(from); assert.equal(env.p.settingsView.tab, to, from + ' → ' + to); assert.equal(env.p.settingsView.focus, focus, from + ' 的落点');
  }
  env.p.openSetupPage('remote');
  tab = openPage(env.p); root = tab.containerEl; await settle(); await new Promise(r => setTimeout(r, 80)); await settle();
  assert.ok(root.querySelector('details[data-section="remote"]').open, '「远程」落点：网页端那一行展开');
  assert.ok(root.querySelector('details[data-section="remote"] .lb-remote-svc'), '展开后是远程访问那几格');
  tab.hide();
  env.p.openSetupPage('skills');
  tab = openPage(env.p); root = tab.containerEl; await settle(); await new Promise(r => setTimeout(r, 80)); await settle();
  assert.ok(root.querySelector('details[data-section="skills"]').open, '「技能」落点：更多里那一行展开');
  tab.hide();

  // —— 1026（录屏 23:23「很奇怪的跳转」、23:34「点了没有反应」）：状态行整行能点、落在能改的那个控件上、闪一下；找不到就说一句 ——
  {
    const e = makePlugin({ onboarding: { guideDone: true } }, { '_archive/catalog-data.json': '{"items":[]}' });
    const t = openPage(e.p); const r = t.containerEl;
    dom.document.body.appendChild(r);   // 连上文档：焦点才真的能落进去
    await settle(); await new Promise(res => setTimeout(res, 80)); await settle();
    const row = n => rowsOf(r).find(x => nameOf(x) === n);
    for (const [name, sec, ctl] of [['API 费用', 'ai-spend', 'input.lb-spend-input'], ['识别', 'ai-feats', null], ['读取', 'mcp-apps', null]]) {
      const el = row(name);
      assert.equal(el.getAttribute('data-jump'), sec, name + ' 跳到哪');
      assert.equal(el.getAttribute('role'), 'button', name + '：整行是可点的');
      const target = r.querySelector(`[data-section="${sec}"]`);
      assert.ok(target, name + ' 的落点画出来了');
      const before = target._scrolledIntoView || 0;
      el.onclick({ target: el.querySelector('.setting-item-name') });   // 点字（以前只有右边小箭头能点）
      assert.ok((target._scrolledIntoView || 0) > before, name + '：点字也滚过去');
      assert.ok(target.classList.contains('lb-flash'), name + '：落地那一块闪一下');
      if (ctl) assert.equal(dom.document.activeElement, target.querySelector(ctl), name + '：焦点落进能改的那一格');
      const n2 = target._scrolledIntoView;
      el.querySelector('.extra-setting-button').onclick();
      assert.ok(target._scrolledIntoView > n2, name + '：右边箭头照样能点');
    }
    // 「改时间」：落在唯一的自动同步时间编辑器上，不是卡片顶
    const sched = r.querySelector('[data-section="sync-time"]');
    const n0 = sched._scrolledIntoView || 0;
    row('收藏同步').querySelectorAll('button').find(b => b.textContent === '改时间').onclick();
    assert.ok(sched._scrolledIntoView > n0 && sched.classList.contains('lb-flash'), '改时间 → 自动同步时间编辑器');
    assert.ok(!cardOf(r, 's-xhs')._scrolledIntoView, '不再落在卡片顶');
    // 落点在收着的折叠里：一层层打开再滚
    const v6 = e.p.settingsV6();
    assert.ok(v6.focusSection(t, 'ai-prompts') && r.querySelector('details[data-section="ai-prompts"]').open, '折叠里的落点：打开它');
    notices.length = 0;
    assert.equal(v6.focusSection(t, 'no-such-thing'), null);
    assert.ok(notices.some(n => /还没画出来/.test(String(n))), '找不到：说一句，不是没反应');
    t.hide(); r.remove();
  }

  // —— 1026：同步时间只有一个编辑器。首页齿轮（openSetupPage('schedule')）、plugin.openSyncTime()、同步记录「改定时」（openSyncSettings）都落到它；
  //    首次设置「同步」一步也是它：改了没点保存就「下一步」→ 替她存上；之后设置页里看到的是同一份值；没保存的草稿看得出来 ——
  {
    let cur = { freq: 'none', enabled: false, installable: true };
    const saved = [];
    const e = makePlugin({ __fresh: true });
    e.p.getSyncSchedule = async () => JSON.parse(JSON.stringify(cur));
    e.p.setSyncRules = async rules => { saved.push(rules); cur = { freq: 'daily', enabled: true, rules, summary: '每天 ' + rules[0].times.join('、') }; return { ok: true, detail: '已保存' }; };
    e.p.app.setting = { activeTab: null, open() {}, openTabById() {} };
    e.p.openPluginSettings = () => {};
    for (const how of [() => e.p.openSyncTime(), () => e.p.openSetupPage('schedule'), () => e.p.openSyncSettings(), () => e.p.openSetupPage('sync-time')]) {
      how(); assert.equal(e.p.settingsView.focus === 'sync-time' || e.p.settingsView.focus === 'schedule', true, '落点是同步时间');
    }
    // 还在首次设置：直接停在「同步」那一步（里面就是那个编辑器）
    e.p.openSyncTime();
    let t = openPage(e.p); let r = t.containerEl; await settle(); await new Promise(res => setTimeout(res, 80)); await settle();
    assert.equal(r.querySelector('.lb-card-title').textContent, '同步', '首次设置里点「改定时」：停在同步那一步');
    assert.ok(r.querySelector('.lb-guide [data-section="sync-time"] .lb-sched'), '首次设置里是同一个时间编辑器');
    const times = () => r.querySelector('[data-section="sync-time"] input.lb-sched-times');
    assert.equal(times().value, '04:00', '还没开定时：推荐值');
    times().value = '06:30'; times().oninput(); r.querySelector('.lb-sched').fire('input');
    assert.match(r.querySelector('.lb-sched-msg').textContent, /改了还没保存/, '没保存的草稿看得出来');
    await r.querySelectorAll('.lb-guide-nav button').find(b => b.textContent === '下一步').onclick(); await settle();
    assert.deepEqual(saved.at(-1), [{ kind: 'daily', times: ['06:30'] }], '「下一步」替她存上了');
    assert.equal(r.querySelector('.lb-card-title').textContent, '识别与问答');
    // 走完首次设置 → 设置页「收藏与同步」里是同一份值
    e.p.homeUI().runAll = async () => ({ ok: true });
    for (let k = 0; k < 2; k++) { const b = r.querySelectorAll('.lb-guide-nav button').find(x => x.textContent === '下一步' || x.textContent === '完成'); await b.onclick(); await settle(); }
    assert.equal(e.p.settings.onboarding.guideDone, true);
    t.hide();
    t = openPage(e.p); r = t.containerEl; await settle(); await new Promise(res => setTimeout(res, 80)); await settle();
    assert.ok(cardOf(r, 's-xhs').querySelector('[data-section="sync-time"]'), '设置页里同一个编辑器');
    assert.equal(times().value, '06:30', '重进设置页：和首次设置里存的是同一份');
    assert.match(r.querySelector('.lb-sched-status').textContent, /每天 06:30/);
    // 设置页里改了没保存 → 关掉再开：草稿还在、并且标着没保存（不冒充已生效）；保存后草稿清掉
    times().value = '07:00'; times().oninput(); r.querySelector('.lb-sched').fire('input');
    t.hide(); t = openPage(e.p); r = t.containerEl; await settle(); await new Promise(res => setTimeout(res, 80)); await settle();
    assert.equal(times().value, '07:00'); assert.match(r.querySelector('.lb-sched-msg').textContent, /改了还没保存/);
    await r.querySelector('.lb-sched-save').onclick(); await settle();
    assert.deepEqual(saved.at(-1), [{ kind: 'daily', times: ['07:00'] }]);
    assert.ok(!/改了还没保存/.test(r.querySelector('.lb-sched-msg').textContent));
    t.hide();
    assert.equal(e.p.scheduleDraft, null, '存过了：不留草稿');
  }

  // —— 首次设置：欢迎页两个大按钮；一键 = 扫码 → 完成（换成推荐那一组、开始跑）；自定义 = 四步 ——
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
    assert.ok(done, '一键：扫完码就是「完成」');
    await done.onclick(); await settle();
    assert.equal(e3.p.settings.onboarding.guideDone, true);
    assert.deepEqual(Array.from(e3.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock'], '推荐那一组（没 key 的 AI 先不勾）');
    assert.equal(ran, 1, '完成后开始一口气跑');
    assert.ok(!pane(r3).querySelector('.lb-guide') && cardOf(r3, 's-status'), '走完变成状态页');
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
  }

  // —— 4. 五栏全打开（AI 全开、五个软件都勾、折叠都展开）后一项不少、单例只剩一处 ——
  for (const [k, cfg] of Object.entries(CONFIGS)) {
    const { p } = makePlugin({ ...cfg, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock', 'ai_text', 'ai_vision'], aiSynced: true },
      connect: { clients: ['claude-code', 'claude-desktop', 'claude-ai', 'chatgpt', 'other'] } });
    const all = [];
    for (const [id, sub] of PAGES()) {
      const t = openPage(p, id, sub); await settle(); for (let k = 0; k < 4; k++) { openFolds(t.containerEl); await settle(); }
      all.push(...inventoryOf(t.containerEl));
      t.hide();
    }
    const count = a => a.reduce((m, x) => m.set(x, (m.get(x) || 0) + 1), new Map());
    // 「归档摘要模型」下面那一格「模型」（只换模型名）按位置改名，别的「模型」都叫「模型名」
    // 在线转写的那一份（alt）：测试按钮字写的是在线接口那句
    const per = k === 'alt' ? { '测试语音识别': '测试语音转文字（发 1 秒录音，几乎不花钱）' } : {};
    const base = BASELINE[k].map((x, i, a) => (x === '模型' && a[i - 1] === '归档摘要模型（默认同文本 AI）' ? '只换模型名' : per[x] || RENAMED[x] || x));
    const had = count(base), has = count(all);
    for (const [x, n] of Object.entries(MERGED)) if (had.has(x)) had.set(x, had.get(x) - n);
    const missing = [...had].filter(([x, n]) => !REMOVED.includes(x) && (has.get(x) || 0) < n).map(([x, n]) => `${x} ×${n - (has.get(x) || 0)}`);
    assert.deepEqual(missing, [], `配置 ${k}：少了这些设置项`);
    for (const x of REMOVED) assert.ok(!all.includes(x));
    const dup = ONCE.filter(x => (has.get(x) || 0) > 1).map(x => `${x} ×${has.get(x)}`);
    assert.deepEqual(dup, [], `配置 ${k}：重复的设置项要删到只剩一处`);
    // 9. 每项说明一行：静态说明 ≤ 60 字（多的在「?」悬停里）
    if (k === 'defaults') {
      const long = [];
      for (const [id, sub] of PAGES()) {
        const t = openPage(p, id, sub); await settle(); for (let k = 0; k < 4; k++) { openFolds(t.containerEl); await settle(); }
        for (const r of rowsOf(t.containerEl)) { const n = idOf(r), d = descText(r); if (!DYNAMIC.has(n) && d.length > 60) long.push(`${n}：${d.length} 字`); }
        t.hide();
      }
      assert.deepEqual(long, [], '说明太长（> 60 字）的项');
    }
  }

  // —— 5. 同步说明行（概览「收藏同步」）——
  const syncDesc = async (files) => { const e = makePlugin({}, files); const t = openPage(e.p); await settle();
    const d = rowsOf(t.containerEl).find(x => nameOf(x) === '收藏同步').querySelector('.setting-item-description').textContent; t.hide(); return d; };
  const line = Plugin.syncSummaryLine;
  const now = new Date(2026, 9, 2, 9, 0).getTime();
  assert.equal(line({ sync: { last_success: new Date(2026, 9, 2, 4, 12).toISOString(), new: 3, deferred: 0 } }, now), '上次：今天 04:12 · 新增 3 篇 · 还剩 0 篇');
  assert.equal(line({ sync: { last_success: new Date(2026, 9, 1, 4, 5).toISOString(), deferred: 4 } }, now), '上次：昨天 04:05 · 还剩 4 篇', '缺 new 不显示那段');
  assert.equal(line({ sync: { new: 2 } }, now), '新增 2 篇', '缺上次时间不显示那段');
  assert.equal(line({ sync: { last_success: '', new: null, deferred: '' } }, now), '');
  assert.equal(line(null, now), '');
  assert.match(await syncDesc({ '_archive/problems-summary.json': JSON.stringify({ sync: { state: 'ready', last_success: new Date().toISOString(), new: 3, deferred: 1 } }) }),
    /^上次：今天 \d\d:\d\d · 新增 3 篇 · 还剩 1 篇 · 自动同步：没开$/);
  assert.equal(await syncDesc({}), '还没有同步过：登录后点「立即同步」，或在「定时同步」里开自动同步。 · 自动同步：没开');

  // —— 6. 概览开着时监听同步 / 问题 / 补评论状态文件，变了重画；重画整页 / 切栏 / 关设置页时注销 ——
  {
    const e = makePlugin({}, { '_archive/sync-status.json': JSON.stringify({ state: 'ready', message: '收藏同步完成', updated_at: '2026-10-02T04:20:00' }) });
    const handlers = []; let offs = 0;
    e.p.app.vault.on = (ev, cb2) => { const ref = { ev, cb: cb2, live: true }; handlers.push(ref); return ref; };
    e.p.app.vault.offref = ref => { ref.live = false; offs++; };
    const t = openPage(e.p, 'overview'); await settle();
    const desc = () => rowsOf(t.containerEl).find(x => nameOf(x) === '收藏同步').querySelector('.setting-item-description').textContent;
    assert.match(desc(), /^收藏同步完成/);
    const live = () => handlers.filter(h => h.live).length;
    assert.equal(live(), 2, '同步那一行 2 个（1016：补评论自己跑，不再占概览一行）');
    e.files['_archive/sync-status.json'] = JSON.stringify({ state: 'running', message: '正在同步收藏：《a》查附件 / 下附件中', updated_at: new Date().toISOString(), done: 3, total: 10 });
    handlers.filter(h => h.live && h.ev === 'modify').forEach(h => h.cb({ path: '_archive/sync-status.json' }));
    await new Promise(r => setTimeout(r, 350)); await settle();
    assert.equal(desc(), '正在同步收藏：《a》查附件 / 下附件中 · 已完成 3/10 篇 · 剩 7 篇 · 自动同步：没开');
    t.display(); await settle();
    assert.equal(offs, 2); assert.equal(live(), 2, '重画整页：旧监听注销，新的接上');
    t.showTab('more'); await settle();
    assert.equal(offs, 4, '跳到别的落点（1018 v6 一页）：整页重画，旧监听注销'); assert.equal(live(), 2);
    t.hide();
    assert.equal(live(), 0, '关设置页：全部注销');
  }

  // —— 7. 每天最多新收几篇（收藏与同步）——默认 50，清空回 50，0 = 不限；每篇评论抓几楼的说明 + 手动那一行小字 ——
  {
    const f = Plugin.dailyNewLimitOf;
    assert.deepEqual([f(''), f('  '), f(null), f(undefined), f('abc'), f('-3'), f('2.5')], [50, 50, 50, 50, 50, 50, 50]);
    assert.deepEqual([f('0'), f(0), f('30'), f(200)], [0, 0, 30, 200]);
    const e = makePlugin({}); const t = openPage(e.p, 'sync'); await settle();
    const input = rowsOf(t.containerEl).find(x => nameOf(x) === '每天最多新收几篇').querySelector('input');
    assert.equal(input.value, '50');
    input.value = ''; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 50, '清空回落 50');
    input.value = '0'; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 0, '0 = 不限，照存');
    const floors = rowsOf(t.containerEl).find(x => nameOf(x) === '每篇评论抓几楼');
    assert.match(floors.querySelector('.setting-item-description').textContent, /每一楼的回复都会抓全/);
    assert.match(floors.querySelector('.lb-sub-line').textContent, /打开那篇，在右上角 ⋮ 菜单里点「抓全部评论」/);
    assert.match(floors.querySelector('.lb-help').getAttribute('aria-label'), /^楼数只往上补：已经存下的评论不会删/, '「?」里讲规则');
    // 下拉存失败：改回原来的楼数 + 一句
    e.p.saveFails = 1; notices.length = 0;
    const sel = floors.querySelector('select'); sel.value = '50'; await sel.onchange();
    assert.equal(e.p.settings.sync.commentFloors, 10); assert.equal(sel.value, '10');
    assert.ok(notices.some(n => String(n).includes('没保存上，已改回原来的楼数')));
    // 自动同步：编辑器就在这一栏（目录页「同步记录」里的弹窗是同一个组件）
    assert.ok(t.containerEl.querySelector('.lb-sched-host .lb-sched'), '定时编辑器在「同步 → 什么时候同步」');
    t.hide();
  }

  // —— 8. 同步计划「当前：…」——认不出的不冒充每天，别的触发器列出来 ——
  {
    const st = Plugin.scheduleStatusText;
    assert.equal(st({ freq: 'daily', enabled: true, time: '04:00', others: ['一次性 2026-10-02 00:00'], next_run: '2026-10-03T04:00:00' }),
      '当前：每天 04:00　·　另有：一次性 2026-10-02 00:00（不改动）　·　下次 2026-10-03 04:00:00');
    assert.equal(st({ freq: 'none' }), '当前：没有计划任务');
  }

  // —— 9. 10-10 她的 data.json 事故（凌晨问答 / 识图的密钥引用被删、地址被换成价格表里的通用地址）——
  // 规矩：没有她明确操作，永不删密钥引用字段（apiKey / keyFile / keyField / apiKeyEnv）、不改已经填好的地址。
  // 照她的配置（问答 DeepSeek + 密钥文件；概要 / 识图 走阿里云专属地址 + 环境变量 / 密钥文件）走一遍首次加载 → 概览 → AI → 拨无关开关 → 高级 → 回 AI；
  // 页面上要是出现「填上它的地址和模型」就照她那样点下去（确认也点「换」），最后三段 AI 设置和每一次写进 data.json 的都得一字不差。
  {
    const DEDICATED = 'https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions';
    const HERS = {
      textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-v4-flash', apiKey: '', keyFile: 'C:/keys/llm.json', keyField: 'deepseek', maxTokens: 1200 },
      summaryAI: { mode: 'http', endpoint: DEDICATED, model: 'qwen3.7-flash', apiKey: '', apiKeyEnv: 'DASHSCOPE_API_KEY', keyFile: 'C:/keys/llm.json', keyField: 'qwen', requireKey: true },
      visionAI: { mode: 'http', endpoint: DEDICATED, model: 'qwen3.8-flash', refineModel: 'qwen3.8-max', apiKey: '', apiKeyEnv: 'DASHSCOPE_API_KEY', keyFile: 'C:/keys/llm.json', keyField: 'qwen', requireKey: true, videoScreenText: true },
      setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text', 'ai_vision'], aiSynced: true },
    };
    // setup estimate 按她配的模型算价（configured），地址给的是价格表里这家的通用地址
    const EST = { ok: true, items: [
      { id: 'summary', name: '概要 + 打标', provider: '通义千问', model: 'qwen3.7-flash', api_model: 'qwen3.7-flash', configured: true, yuan: 0.3, per: '100 篇', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', key_url: 'https://bailian.console.aliyun.com/' },
      { id: 'vision', name: '识图', provider: '通义千问', model: 'qwen3.8-flash', api_model: 'qwen3.8-flash', configured: true, yuan: 1.2, per: '100 篇', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions' },
      { id: 'ask', name: '问答（每问一次）', provider: 'DeepSeek', model: 'deepseek-flash', api_model: 'deepseek-v4-flash', configured: true, yuan: 0.004, per: '次', endpoint: 'https://api.deepseek.com/chat/completions' }],
      prices: { as_of: '2026-10-03' } };
    const AI = ['textAI', 'summaryAI', 'visionAI'];
    const e3 = makePlugin(JSON.parse(JSON.stringify(HERS)), { '_archive/catalog-data.json': '{"items":[]}' });
    const orig = JSON.stringify(AI.map(k => e3.p.settings[k]));
    const realRun = e3.p.runPy;
    e3.p.runPy = async (args, o) => (args.join(' ').includes('setup estimate') ? { code: 0, json: EST, err: '' } : realRun(args, o));
    e3.p.confirm = async () => true;                                   // 她要是点了，确认也点「换」
    assert.equal(await e3.p.homeUI().firstRun(), 'existing-library', '老库首次加载只记一笔');
    let t3 = openPage(e3.p, 'overview'); await settle(); t3.hide();
    t3 = openPage(e3.p, 'ai'); await settle();
    const clickFills = async () => { let n = 0; for (const b of t3.containerEl.querySelectorAll('button').filter(x => /^填上它的地址和模型/.test(x.textContent))) { n++; await b.onclick(); await settle(); } return n; };
    let offered = await clickFills();
    const featOf = id => t3.containerEl.querySelector(`.lb-feat[data-id="${id}"]`);
    const flip3 = async (id, on) => { const cb = featOf(id).querySelector('.checkbox-container'); cb.checked = on; await cb.onchange(); await settle(); };
    await flip3('ocr', false); await flip3('ocr', true); await flip3('ai_vision', true);
    t3.hide(); t3 = openPage(e3.p, 'advanced'); await settle(); t3.hide();
    t3 = openPage(e3.p, 'ai'); await settle();
    offered += await clickFills();
    t3.hide();
    assert.equal(JSON.stringify(AI.map(k => e3.p.settings[k])), orig, '问答 / 概要 / 识图的设置被改了（密钥引用字段被删、或地址被换）');
    for (const sv of e3.saves) assert.equal(JSON.stringify(AI.map(k => sv[k])), orig, '写进 data.json 的 AI 设置被改了');
    assert.ok(e3.saves.length > 0, '这一路确实存过（首次加载 / 拨开关）');
    assert.equal(offered, 0, '已经填好地址的，不该再给「填上它的地址和模型」');
    // 1018 v6：「填上它的地址和模型」换成「添加 key」（粘贴 → 认出是哪家 → 只往空着的格子里填）。同一条规矩：原来的密钥引用（环境变量名）一个不删、不另塞 key
    const e4 = makePlugin({ textAI: { mode: 'http', endpoint: '', model: '', apiKeyEnv: 'MY_LLM_KEY' }, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text'], aiSynced: true } });
    await e4.p.settingsV6().addKey('sk-whatever');
    assert.equal(e4.p.settings.textAI.endpoint, 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions');
    assert.equal(e4.p.settings.textAI.model, 'qwen3.7-flash');
    assert.equal(e4.p.settings.textAI.apiKeyEnv, 'MY_LLM_KEY', '填推荐值把原来的密钥引用删了');
    assert.ok(!e4.p.settings.textAI.apiKey, '已经有密钥引用：不另塞 key');
  }

  // —— 11. 10-10 索引树：「分类」文本框换成 编辑索引 / AI 起草 / 未归类建议 / 重新整理目录（都是次要链接），索引文件路径存进 indexFile ——
  {
    const e5 = makePlugin({});
    const hits = [];
    Object.assign(e5.p, { openIndexFile: () => hits.push('open'), indexDraft: async () => { hits.push('draft'); }, openIndexSuggestions: () => hits.push('suggest'),
      indexRebuild: () => hits.push('rebuild'), indexUI: { indexRel: () => e5.p.settings.indexFile || '索引.md' }, run: async args => hits.push('run ' + args.slice(2).join(' ')),
      busyButton: () => () => {} });
    const t5 = openPage(e5.p, 'more'); await settle(); await openRow(t5.containerEl, 'skills');
    const fold = t5.containerEl.querySelector('.lb-cats-fold');
    assert.ok(fold && !fold.open, '目录分类默认收起');
    assert.equal(fold.querySelector('summary').textContent, '目录分类（索引）');
    assert.ok(!fold.querySelector('textarea'), '「名称: 关键词」文本框退场');
    const row = rowsOf(fold).find(r => nameOf(r) === '编辑索引');
    const btns = row.querySelectorAll('button');
    assert.deepEqual(btns.map(b => b.textContent), ['打开 索引.md', 'AI 起草', '未归类建议', '重新整理目录']);
    assert.ok(btns.every(b => b.classList.contains('lb-link') && !b.classList.contains('mod-cta')), '都是次要链接');
    for (const b of btns) await b.onclick();
    await settle();
    assert.deepEqual(hits, ['open', 'draft', 'suggest', 'run catalog']);
    const input = rowsOf(fold).find(r => nameOf(r) === '索引文件').querySelector('input');
    assert.equal(input.getAttribute('placeholder'), '索引.md');
    input.value = ' 我的/分类.md '; await input.oninput(); await settle();
    assert.equal(e5.p.settings.indexFile, '我的/分类.md');
    assert.equal(e5.saves.at(-1).indexFile, '我的/分类.md', '存进设置');
    assert.equal(hits.at(-1), 'rebuild', '换了索引文件：重算一次');
    t5.hide();
    // index-ui.js 没加载上：点了只说一句，不炸
    const e6 = makePlugin({});
    const t6 = openPage(e6.p, 'more'); await settle(); await openRow(t6.containerEl, 'skills');
    const before = notices.length;
    await rowsOf(t6.containerEl.querySelector('.lb-cats-fold')).find(r => nameOf(r) === '编辑索引').querySelectorAll('button')[0].onclick();
    assert.match(String(notices.slice(before).at(-1)), /索引功能没加载上/);
    t6.hide();
  }

  // —— 12. 1015 定时同步卡片：每次同步最多收几篇（0 = 不限，存 sync.perRunLimit）· 补评论节奏（45 / 90 / 180，存失败改回）——
  {
    assert.deepEqual([Plugin.perRunLimitOf(''), Plugin.perRunLimitOf(null), Plugin.perRunLimitOf('-1'), Plugin.perRunLimitOf('x'), Plugin.perRunLimitOf('7')], [0, 0, 0, 0, 7]);
    assert.deepEqual([Plugin.fillGapOf(90), Plugin.fillGapOf('180'), Plugin.fillGapOf(10), Plugin.fillGapOf(undefined)], [90, 180, 45, 45], '补评论只能比 45 分钟慢');
    const e = makePlugin({}); const t = openPage(e.p, 'sync'); await settle(); await openRow(t.containerEl, 'sync-more');
    const card = t.containerEl;   // 1018 v6：这两项在「更多 → 同步细项」里
    const per = rowsOf(card).find(r => nameOf(r) === '每次同步最多收几篇').querySelector('input');
    assert.equal(per.value, '0');
    per.value = '20'; await per.oninput(); assert.equal(e.p.settings.sync.perRunLimit, 20);
    assert.equal(e.saves.at(-1).sync.perRunLimit, 20, '存进 data.json（后端 sync_options 读同一个键）');
    per.value = ''; await per.oninput(); assert.equal(e.p.settings.sync.perRunLimit, 0, '清空 = 不限');
    const pace = rowsOf(card).find(r => nameOf(r) === '补评论节奏').querySelector('select');
    assert.deepEqual(pace.dropdown.options.map(o => o[0]), ['45', '90', '180']);
    assert.equal(pace.value, '45');
    pace.value = '180'; await pace.onchange(); assert.equal(e.p.settings.sync.commentFillGap, 180);
    e.p.saveFails = 1; notices.length = 0;
    pace.value = '90'; await pace.onchange();
    assert.equal(e.p.settings.sync.commentFillGap, 180, '存失败：节奏改回原来的'); assert.equal(pace.value, '180');
    assert.ok(notices.some(n => String(n).includes('没保存上，已改回原来的节奏')));
    t.hide();
  }

  // —— 13. 1015 模型与提供商 → 问收藏模型：勾选列表（不勾 = 不进问收藏页下拉，至少留一个；当前选中的被取消就换一个）——
  {
    const e = makePlugin({}); const t = openPage(e.p, 'ai'); await settle();
    { const d = t.containerEl.querySelector('details.lb-route[data-feature="ask"]'); d.open = true; d.fire('toggle'); await settle(); }   // 1026：模型与费用 → 每个功能用谁 → 问收藏
    const rows = () => rowsOf(cardOf(t.containerEl, 'models')).filter(r => r.classList.contains('lb-model-row'));
    assert.deepEqual(rows().map(nameOf), ['文本 AI', 'Codex', 'Sonnet']);
    assert.ok(rows().every(r => r.querySelector('.lb-model-check').checked), '默认都勾着');
    let trig = 0; e.p.app.workspace.trigger = ev => { if (ev === 'link-brain:models-changed') trig++; };
    const box = name => rows().find(r => nameOf(r) === name).querySelector('.lb-model-check');
    box('文本 AI').checked = false; await box('文本 AI').onchange(); await settle();
    assert.equal(e.p.settings.models[0].hidden, true);
    assert.equal(e.p.settings.activeModel, 'Codex', '当前选中的被取消：换成下一个勾着的');
    assert.ok(trig >= 1, '通知问收藏页重画下拉');
    box('Codex').checked = false; await box('Codex').onchange(); await settle();
    box('Sonnet').checked = false; await box('Sonnet').onchange(); await settle();
    assert.equal(box('Sonnet').checked, true, '最后一个不让取消'); assert.ok(!e.p.settings.models[2].hidden);
    box('文本 AI').checked = true; await box('文本 AI').onchange(); await settle();
    assert.ok(!('hidden' in e.p.settings.models[0]), '重新勾上：hidden 去掉');
    // 问收藏页的下拉只列勾着的（chat-view.js fillModels）
    const chat = fs.readFileSync('link_brain/assets/chat-view.js', 'utf8');
    assert.match(chat, /filter\(m => m && m\.name && !m\.hidden\)/);
    t.hide();
  }

  // —— 14. 1015 技能页：说明行 + 刷新 / ＋ · 读收藏库 _skills · 空状态一句 · 隐藏列表输入框 ——
  {
    const files = {};
    const e = makePlugin({}, files);
    const ad = e.p.app.vault.adapter;
    ad.list = async dir => ({ folders: Object.keys(files).filter(f => f.startsWith(dir + '/') && f.endsWith('/SKILL.md')).map(f => f.slice(0, -'/SKILL.md'.length)), files: [] });
    let t = openPage(e.p, 'skills'); await settle(); await new Promise(r => setTimeout(r, 80)); await openRow(t.containerEl, 'skills');   // 1018 v6：落点「技能」→ 更多里那一行展开
    const skillCard = () => cardOf(t.containerEl, 'skills');
    const lead = rowsOf(skillCard()).find(r => nameOf(r) === '问收藏时按问题自动选用');
    assert.ok(lead, '说明行');
    assert.deepEqual(lead.querySelectorAll('.extra-setting-button').map(b => b.getAttribute('aria-label')), ['刷新', '从本地文件夹导入（只拷文字文件，不执行）']);
    assert.match(skillCard().querySelector('.lb-skill-empty').textContent, /还没有技能。点右上角 ＋ 从本地文件夹导入/);
    // 放进两个技能（一个坏的）再点刷新
    files['_skills'] = '';
    files['_skills/recipe/SKILL.md'] = '---\nname: recipe\ndescription: 菜谱：列菜名、主料\n---\n正文';
    files['_skills/broken/SKILL.md'] = '没有 frontmatter';
    await lead.querySelectorAll('.extra-setting-button')[0].onclick(); await settle();
    const skillRows = () => skillCard().querySelectorAll('.lb-skill-row');
    assert.deepEqual(skillRows().map(nameOf), ['broken', 'recipe']);
    assert.equal(skillRows()[1].querySelector('.setting-item-description').textContent, '菜谱：列菜名、主料');
    assert.ok(skillRows()[0].classList.contains('is-broken'), '读不懂的也列出来、标出来');
    // 隐藏列表：逗号分隔存 settings.skills.hidden；列表里标「已隐藏」
    const hid = rowsOf(cardOf(t.containerEl, 'skills-hidden')).find(r => nameOf(r) === '不自动选用这些技能').querySelector('input');
    assert.ok(hid.classList.contains('lb-skill-hidden-input'));
    hid.value = 'recipe， travel recipe'; await hid.oninput();
    assert.deepEqual(Array.from(e.p.settings.skills.hidden), ['recipe', 'travel']);
    assert.deepEqual(Array.from(e.saves.at(-1).skills.hidden), ['recipe', 'travel']);
    t.hide(); t = openPage(e.p, 'skills'); await settle(); await openRow(t.containerEl, 'skills');
    assert.ok(skillRows().find(r => r.getAttribute('data-skill') === 'recipe').classList.contains('is-hidden-skill'));
    // ＋导入：只拷文字文件（脚本 / 程序 / 隐藏文件不拷），已有同名的先问
    const writes = [];
    ad.write = async (f, text) => { writes.push(f); files[f] = text; };
    ad.mkdir = async f => { files[f] = ''; };
    const fileObj = (rel, text) => ({ webkitRelativePath: rel, name: rel.split('/').pop(), size: Buffer.byteLength(text), text: async () => text });
    const ui = e.p.skillsUI();
    const n = await ui.importFiles([
      fileObj('trip-planner/SKILL.md', '---\nname: Trip Planner\ndescription: >\n  旅游攻略：路线、时段\n  预算和坑\n---\n正文'),
      fileObj('trip-planner/references/checklist.md', '核验清单'),
      fileObj('trip-planner/scripts/fetch.py', 'import os; os.system("rm -rf /")'),
      fileObj('trip-planner/run.sh', 'curl x | sh'),
      fileObj('trip-planner/.env', 'KEY=1'),
    ]);
    assert.equal(n, 1);
    assert.deepEqual(writes.sort(), ['_skills/trip-planner/SKILL.md', '_skills/trip-planner/references/checklist.md'], '只拷文字文件');
    e.p.confirm = async () => false;
    writes.length = 0;
    assert.equal(await ui.importFiles([fileObj('trip-planner/SKILL.md', '---\nname: trip-planner\n---\n')]), 0, '同名不覆盖（没点「覆盖」）');
    assert.equal(writes.length, 0);
    notices.length = 0;
    assert.equal(await ui.importFiles([fileObj('x/readme.md', 'hi')]), 0);
    assert.match(String(notices.at(-1)), /没有 SKILL\.md/);
    t.hide();
  }

  console.log('PASS settings page v6 (1018, 1026 regrouped): 状态 + six task groups (收藏与同步 · 内容、目录及管理 · 识别与问答 · 模型与费用 · 外部 AI 接入 · 高级 / 修复), status rows clickable and landing on the editable control with a flash, one sync-time editor shared by settings / first-run / openSyncTime (unsaved edits auto-saved on 下一步, same value after reopening, drafts flagged), first-run guide (一键 / 自定义四步) turning into the status page, key trouble = one line + recharge / change key, local toggles drive setup.selected with deps + sub-options, summary / embed toggles keep their mode, paste-a-key fills blanks only, installed AI apps listed, old open-page names land on the right card / row, nothing lost vs pre-1009 inventory and no duplicates, one-line descriptions, failed saves revert, sync rows live-watched + unhooked');
})().catch(e => { console.error(e); process.exitCode = 1; });

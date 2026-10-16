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
    const t = { toggleEl: el, setValue(v) { const was = !!el.checked; el.checked = !!v; if (change && was !== !!v) change(!!v); return t; }, setDisabled() { return t; }, onChange(f) { change = f; el.onchange = () => f(el.checked); return t; } };
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
  presets: { light: ['core', 'reader', 'dataview', 'ocr'] }, totals_basis: '估计值' };
const REPLIES = {
  'setup plan': PLAN,
  'setup estimate': { ok: true, items: [{ id: 'summary', name: '概要 + 打标', provider: 'DeepSeek', model: 'x', yuan: 0.8, per: '100 篇', endpoint: 'https://api.deepseek.com/chat/completions', key_url: 'https://platform.deepseek.com/api_keys' },
    { id: 'ask', name: '问答（每问一次）', provider: 'DeepSeek', model: 'x', yuan: 0.004, per: '次' }], prices: { as_of: '2026-10-03' } },
  'comments --fill-status': { ok: true, pending: 12, ready: 12, cooling: 0, stuck: 0, missing: 340, running: false, message: '12 篇的评论还没补齐' },
  'connect status': { ok: true, clients: { 'claude-code': { installed: true, connected: false, command: 'claude mcp add lwa -s user -- python -m link_brain mcp' },
    'claude-desktop': { installed: true, connected: true } }, json: '{"mcpServers":{}}' },
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
  p.settings = Plugin.__merge(saved);
  if (saved && saved.remote) p.settings.remote = saved.remote;
  p.loadData = async () => JSON.parse(JSON.stringify(p.settings));
  p.saveFails = 0;
  p.saveSettings = async () => { if (p.saveFails > 0) { p.saveFails--; throw new Error('磁盘满了（合成）'); } saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.notify = (m) => notices.push(m);
  p.renderAccounts = c => { c.createDiv({ cls: 'lb-accounts' }).createDiv({ cls: 'setting-item lb-acct-row' }); };
  p.capsWriterDir = () => null;
  p.setCapsVoice = async () => true;
  p.runPy = async args => { calls.push(args); return { code: 0, json: reply(args), err: '' }; };
  p.onboardingUI = () => p._onb || (p._onb = require(PLUGIN_DIR + 'onboarding-ui.js')(OBS, p));
  p.homeUI = () => p._home || (p._home = require(PLUGIN_DIR + 'home-ui.js')(OBS, p));
  p.scheduleUI = () => require(PLUGIN_DIR + 'schedule-ui.js')(OBS, p);
  p.remoteUI = require(PLUGIN_DIR + 'remote-ui.js')(OBS, p);
  p.skillsUI = () => require(PLUGIN_DIR + 'skills-ui.js')(OBS, p);
  p.usageUI = () => require(PLUGIN_DIR + 'usage-ui.js')(OBS, p);
  return { p, saves, files, calls };
}
function openPage(p, tabId = null, sub = null) {
  if (tabId) p.settingsView = { ...(p.settingsView || {}), tab: tabId };
  if (sub) p.settingsView.sub = { ...(p.settingsView.sub || {}), [tabId]: sub };
  const tab = new Plugin.__SettingTab({}, p); p.settingTab = tab; tab.display(); return tab;
}
// 每个页签 × 子页签（1015：模型与提供商下面有子页签）
const PAGES = () => Plugin.__TABS.flatMap(([id]) => (Plugin.__SUBTABS[id] || [[null]]).map(([sub]) => [id, sub]));
const cardOf = (root, section) => root.querySelector(`.lb-card[data-section="${section}"]`);
const flush = () => new Promise(r => setTimeout(r, 0));
const settle = async (n = 8) => { for (let i = 0; i < n; i++) await flush(); };

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
const nameOf = row => { const n = row.querySelector('.setting-item-name'); if (!n) return ''; return [...n.childNodes].filter(c => !(c.classList && (c.classList.contains('lb-help') || c.classList.contains('lb-price')))).map(c => c.textContent).join('').trim(); };
const idOf = row => nameOf(row) || row.querySelectorAll('button').map(b => b.textContent.trim()).join('+') || (row.classList.contains('lb-acct-row') ? '〔账号卡片〕' : '');
const pane = root => root.querySelector('.lb-tab-pane');
const visibleRows = (root) => rowsOf(pane(root)).filter(r => visible(r, root)).map(idOf);
const ctas = root => pane(root).querySelectorAll('button').filter(b => b.classList.contains('mod-cta')).map(b => b.textContent);
const descText = row => { const d = row.querySelector('.setting-item-description'); if (!d) return ''; return [...d.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent).join('').trim(); };
const openFolds = root => { for (const d of root.querySelectorAll('details')) if (!d.open) { d.open = true; d.fire('toggle'); } };
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
  '识图接口': '识图', '精细识别模型': '精细识图模型', '测试识图': '测试识图（发一张小图，几乎不花钱）', '视频画面文字': '认视频画面里的字',
  '语音识别': '视频转文字改用在线接口', '端口': '本机语音识别的端口', 'CapsLock 语音输入': '按住 CapsLock 说话打字', 'CapsWriter 目录': 'CapsWriter 装在哪',
  '输入框提示文字': '输入框里的提示字', DeepSeek: '文本 AI', '添加模型': '加一个模型', '其他客户端（JSON 配置）': '其他 AI 软件', '测试 MCP': '测一下本机的连接程序（MCP）',
  '批注昵称': '批注署名', '检查本机环境': '检查这台电脑', '文字识别（OCR）': '认图片里的字', '识别精度': '认字精度', '模型目录（可选）': '认字模型放在哪（可选）',
  '测试 OCR': '测试认字（本机跑，不花钱）', '摘要提示词（归档时抽取）': '写概要的提示词', '问答提示词（/问AI）': '问收藏的提示词',
  '回答输出上限（max_tokens）': '回答最长多少（max_tokens）', '发给模型的总字符上限': '最多给模型看多少字', '每篇片段字符上限': '每篇最多摘多少字',
  '送模型的片段篇数（topK）': '最多参考几篇（topK）', '先用小模型扩检索词': '提问时先想几个同义词一起搜', '载入当前分类+清空（用内置）+重建目录': '编辑索引',   // 10-10 索引树：分类文本框换成「编辑索引 / AI 起草 / 未归类建议 / 重新整理目录」
  '等待手动下载（分钟）': '等下载最多几分钟', '待补附件': '还没下到的附件',
  '电脑需求 收藏问答：文本模型（': '电脑需求 问收藏：文本模型（现', '电脑需求 图片文字：本地 OC': '电脑需求 图片里的字：本地 O',
  '电脑需求 视频：语音转写走上面': '电脑需求 视频：语音转文字默认', '电脑需求 语音输入：CapsW': '电脑需求 说话打字：CapsW', '〔远程阅读〕': '〔连接其他 AI〕',
  '测试语音识别': '测试语音转文字（本机跑，不花钱）',
};
// 合并的：本机 AI 的复制命令只留一处（第二个 Codex 合进「其他 AI 软件」的设置片段）；「评论 · 手动拉取」合进「每篇评论抓几楼」
const MERGED = { Codex: 1, '每篇评论抓几楼': 1 };
// 这些设置只许出现一次（别处有重复的一律删掉只留一处）
const ONCE = ['〔账号卡片〕', '收藏同步', '每天最多新收几篇', '下载图片', '下载视频', '每篇评论抓几楼', '识图', '按住 CapsLock 说话打字', 'Claude Code', '测一下本机的连接程序（MCP）',
  '视频转文字改用在线接口', '写概要用的模型', '评论补齐', '收藏放在哪', '后端命令', '自动同步', '认图片里的字', '问收藏 · 自动概要 · 打标签'];
// 动态状态行（说明是现读的状态，不算「每项说明一行」的说明文字）
const DYNAMIC = new Set(['〔账号卡片〕', '收藏同步', '评论补齐', '问题', '这台电脑', '文本 AI', 'Codex', 'Sonnet', '远程访问', '口令', '连接地址', 'Claude Code', 'Claude Desktop', '你的网址', '远程访问的运行情况']);

(async () => {
  // —— 1. 五栏，默认概览；一次只画一栏；每栏最多一个主按钮 ——
  const sum = { updated_at: '2026-10-02T04:20:00', needs_human: 1, auto: 2, gave_up: 0, sync: { state: 'ready', message: '收藏同步完成', last_success: '2026-10-02T04:12:00', new: 3, deferred: 0, updated_at: '2026-10-02T04:20:00' } };
  let env = makePlugin({}, { '_archive/problems-summary.json': JSON.stringify(sum) });
  let tab = openPage(env.p); let root = tab.containerEl;
  await settle();
  assert.deepEqual(root.querySelectorAll('.lb-tabs .lb-tab').map(b => b.textContent), ['通用', '模型与提供商', '技能']);
  assert.deepEqual(root.querySelectorAll('.lb-tab.is-active').map(b => b.textContent), ['通用']);
  assert.equal(root.querySelectorAll('.lb-tab-pane').length, 1, '一次只画一栏');
  assert.ok(!root.querySelector('.lb-setup') && !root.querySelector('.lb-steps'), '没有分步向导');
  // 1015：每组一张卡片，标题加粗 + 分隔线（卡片头）
  assert.deepEqual(pane(root).querySelectorAll('.lb-card > .lb-card-head > .lb-card-title').map(t => t.textContent),
    ['状态', '收藏', '定时同步', '目录与批注', '附件手动下载', '连接其他 AI', '开发者']);
  assert.ok(pane(root).querySelectorAll('.setting-item').every(r => r.closest ? r.closest('.lb-card') : true), '设置行都在卡片里');
  assert.deepEqual(rowsOf(cardOf(root, 'status')).filter(r => visible(r, root)).map(idOf), ['〔账号卡片〕', '收藏同步', '评论补齐', '问题', '这台电脑']);
  assert.deepEqual(rowsOf(cardOf(root, 'schedule')).map(idOf), ['自动同步', '每次同步最多收几篇', '每天最多新收几篇', '每篇评论抓几楼', '补评论节奏'],
    '定时同步：同步篇数、补评论都在这一张卡片里（她 1015）');
  const statusRow = n => rowsOf(root).find(r => nameOf(r) === n);
  assert.match(statusRow('评论补齐').querySelector('.setting-item-description').textContent, /12 篇的评论还没补齐（共缺 340 条回复）/);
  assert.match(statusRow('问题').querySelector('.setting-item-description').textContent, /⚠ 1 件要你处理/);
  assert.deepEqual(statusRow('收藏同步').querySelectorAll('button').map(b => b.textContent), ['立即同步', '改时间'], '概览：收藏同步只有两个次要链接（定时在「收藏与同步」）');
  assert.ok(statusRow('收藏同步').querySelectorAll('button').every(b => b.classList.contains('lb-link') && !b.classList.contains('mod-cta')), '都是次要的链接样子');
  assert.match(statusRow('这台电脑').querySelector('.setting-item-description').textContent, /^✓ 程序 · ✓ 读取组件 · ✓ Dataview · ✓ 认字/);
  assert.deepEqual(ctas(root), ['一键装好 / 跑完'], '概览唯一的主按钮');
  // 切到别的栏：概览那一栏的监听注销、只画新的那一栏
  for (const [id, label] of Plugin.__TABS) {
    root.querySelectorAll('.lb-tabs .lb-tab').find(b => b.textContent === label).onclick();
    await settle();
    assert.equal(pane(root).getAttribute('data-tab'), id);
    assert.ok(ctas(root).length <= 1, `「${label}」最多一个主按钮：${ctas(root)}`);
    for (const [sub, subLabel] of Plugin.__SUBTABS[id] || []) {
      pane(root).querySelectorAll('.lb-subtabs .lb-subtab').find(b => b.textContent === subLabel).onclick();
      await settle();
      assert.equal(pane(root).querySelector('.lb-subpane').getAttribute('data-sub'), sub);
      assert.deepEqual(pane(root).querySelectorAll('.lb-subtab.is-active').map(b => b.textContent), [subLabel]);
      assert.ok(ctas(root).length <= 1, `「${label} → ${subLabel}」最多一个主按钮：${ctas(root)}`);
    }
  }
  assert.deepEqual(Array.from(Plugin.__SUBTABS.providers, x => x[1]), ['AI 功能', '问收藏模型', '识图 · 认字 · 语音', '提示词', '用量与余额']);
  tab.hide();

  // —— 2. AI 那一栏：开关改 setup.selected（依赖联动）+ 对上实际起作用的设置；子选项；AI 打开原地出接口那几格 + 价钱 ——
  env = makePlugin({});
  tab = openPage(env.p, 'ai'); root = tab.containerEl; await settle();
  const feat = id => root.querySelector(`.lb-feat[data-id="${id}"]`);
  const flip = async (id, on) => { const cb = feat(id).querySelector('.checkbox-container'); cb.checked = on; await cb.onchange(); await settle(); };
  assert.ok(!feat('capslock'), '视频说话转文字没开：「按住 CapsLock 说话」这个子选项不出');
  assert.equal(feat('ocr').querySelector('.lb-price').textContent, '免费（本机跑）');
  assert.match(root.querySelector('.lb-ai-lead').textContent, /要不要 AI：不填也能用；填了多出 问收藏、自动概要、识图。/);
  await flip('asr', true);
  assert.ok(feat('capslock'), '父开关打开后，子选项出现');
  await flip('capslock', true);
  assert.deepEqual(Array.from(env.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock'], '勾 CapsLock → 语音识别也在');
  assert.equal(env.p.settings.voice.capsLock, true, 'CapsLock 客户端跟着开');
  await flip('asr', false);
  assert.deepEqual(Array.from(env.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr'], '取消语音识别 → CapsLock 跟着取消');
  assert.equal(env.p.settings.asrAI.mode, 'off');
  assert.ok(!feat('capslock'));
  await flip('ai_text', true);
  const capBox = root.querySelector('.lb-feat-cap[data-cap="textAI"]');
  assert.ok(capBox, '问收藏打开 → 原地出接口那几格');
  for (const n of ['接口地址', '密钥（API Key）', '模型名', '测试（发一句话，几乎不花钱）']) assert.ok(rowsOf(capBox).some(r => idOf(r) === n), '缺「' + n + '」');
  assert.equal(feat('ai_text').querySelector('.lb-price').textContent, '概要和打标签 约 ¥0.80 / 100 篇 · 问收藏 约 ¥0.004 / 次');
  assert.ok(rowsOf(root).some(r => nameOf(r) === 'DeepSeek（概要和打标签、问收藏）'), '去哪弄密钥、大概多少钱');
  // 别处触发的重画（一键装好 / 跑完每来一个进度事件就重画一次）不重建接口那几格：正在打的字和焦点不丢
  const typing = capBox.querySelector('input');
  typing.value = 'https://api.example.com/打到一半';
  env.p.homeUI()._internals.repaint(); await settle();
  assert.ok(root.querySelector('.lb-feat-cap[data-cap="textAI"]') === capBox && capBox.querySelector('input') === typing, '进度重画把接口那几格重建了（正在打的字会丢）');
  assert.equal(typing.value, 'https://api.example.com/打到一半');
  await flip('ocr', false);
  assert.equal(env.p.settings.ocr.mode, 'off', 'OCR 开关就是 OCR 的唯一开关');
  assert.ok(!env.p.settings.setup.selected.includes('ai_vision'), '取消 OCR → 依赖它的识图跟着取消');
  // 10. 开关存失败：拨回原值 + 一句（假开关照 1.14.4：setValue 会再触发 onChange——不来回弹）
  notices.length = 0; env.p.saveFails = 1;
  const before = JSON.stringify(env.p.settings.setup.selected);
  await flip('ocr', true);
  assert.equal(JSON.stringify(env.p.settings.setup.selected), before, '存失败：选择还原');
  assert.equal(env.p.settings.ocr.mode, 'off', '存失败：OCR 方式还原');
  assert.equal(feat('ocr').querySelector('.checkbox-container').checked, false, '开关拨回关');
  assert.ok(notices.some(n => String(n).includes('没保存上，开关已拨回原来的位置')), notices.join('|'));
  assert.equal(env.p.saveFails, 0, '只存了一次（没来回弹）');
  tab.hide();

  // 「填上它的地址和模型」：现在用本机命令行（不花钱）→ 先确认（换成接口要按用量付费），不点「换」就不动（1010 审查）
  {
    const e2 = makePlugin({ textAI: { mode: 'cli', command: 'codex exec' }, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text'], aiSynced: true } });
    const asked = []; e2.p.confirm = async o => { asked.push(o); return false; };
    const t2 = openPage(e2.p, 'ai'); await settle();
    const fillBtn = t2.containerEl.querySelectorAll('button').find(b => /^填上它的地址和模型/.test(b.textContent));
    assert.ok(fillBtn, '有「填上它的地址和模型」');
    await fillBtn.onclick(); await settle();
    assert.equal(asked.length, 1, '本机命令行换成接口要先确认');
    assert.match(asked[0].body, /本机命令行（不花钱）.*按用量付费/);
    assert.equal(e2.p.settings.textAI.mode, 'cli', '没点「换」：还是本机命令行');
    t2.hide();
  }

  // —— 3. 停在哪一栏记在插件对象上（本次会话），不写 data.json；「打开设置」旧落点名照认 ——
  const savesBefore = env.saves.length;
  tab = openPage(env.p); root = tab.containerEl; await settle();
  assert.equal(pane(root).getAttribute('data-tab'), 'providers', '重开设置页停在上次那一栏');
  assert.equal(pane(root).querySelector('.lb-subpane').getAttribute('data-sub'), 'features', '旧名 ai → 模型与提供商 → AI 功能');
  assert.equal(env.saves.length, savesBefore, '切栏不写 data.json');
  assert.ok(!JSON.stringify(env.p.settings).includes('"tab"'), '状态不进 settings');
  env.p.app.setting = { activeTab: null, open() {}, openTabById() {} };
  env.p.openPluginSettings = () => {};
  for (const [from, to, focus] of [['ai', 'providers', null], ['features', 'general', null], ['overview', 'general', 'status'], ['status', 'general', 'status'],
    ['remote', 'general', 'connect'], ['sync', 'general', 'schedule'], ['advanced', 'general', 'developer'], ['skills', 'skills', null], ['nope', 'general', null]]) {
    env.p.openSetupPage(from); assert.equal(env.p.settingsView.tab, to, from + ' → ' + to); assert.equal(env.p.settingsView.focus, focus, from + ' 的落点');
  }
  env.p.openSetupPage('ai'); assert.equal(env.p.settingsView.sub.providers, 'features', '问题面板「打开设置」→ AI 功能');
  env.p.openSetupPage('status'); assert.equal(env.p.settingsView.focus, 'status', '「去扫码 / 验证」→ 通用的状态卡片');
  tab.hide();

  // —— 4. 五栏全打开（AI 全开、五个软件都勾、折叠都展开）后一项不少、单例只剩一处 ——
  for (const [k, cfg] of Object.entries(CONFIGS)) {
    const { p } = makePlugin({ ...cfg, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock', 'ai_text', 'ai_vision'], aiSynced: true },
      connect: { clients: ['claude-code', 'claude-desktop', 'claude-ai', 'chatgpt', 'other'] } });
    const all = [];
    for (const [id, sub] of PAGES()) {
      const t = openPage(p, id, sub); await settle(); openFolds(t.containerEl); await settle();
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
        const t = openPage(p, id, sub); await settle(); openFolds(t.containerEl); await settle();
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
    const t = openPage(e.p, 'general'); await settle();
    const desc = () => rowsOf(t.containerEl).find(x => nameOf(x) === '收藏同步').querySelector('.setting-item-description').textContent;
    assert.match(desc(), /^收藏同步完成/);
    const live = () => handlers.filter(h => h.live).length;
    assert.equal(live(), 4, '同步那一行 2 个 + 补评论 / 问题那两行 2 个');
    e.files['_archive/sync-status.json'] = JSON.stringify({ state: 'running', message: '正在同步收藏：《a》查附件 / 下附件中', updated_at: new Date().toISOString(), done: 3, total: 10 });
    handlers.filter(h => h.live && h.ev === 'modify').forEach(h => h.cb({ path: '_archive/sync-status.json' }));
    await new Promise(r => setTimeout(r, 350)); await settle();
    assert.equal(desc(), '正在同步收藏：《a》查附件 / 下附件中 · 已完成 3/10 篇 · 剩 7 篇 · 自动同步：没开');
    e.files['_archive/comments-fill-status.json'] = JSON.stringify({ state: 'running', message: '正在补评论 · 已补齐 5/12 篇', updated_at: new Date().toISOString() });
    handlers.filter(h => h.live && h.ev === 'modify').forEach(h => h.cb({ path: '_archive/comments-fill-status.json' }));
    await new Promise(r => setTimeout(r, 350)); await settle();
    assert.equal(rowsOf(t.containerEl).find(x => nameOf(x) === '评论补齐').querySelector('.setting-item-description').textContent, '正在补评论 · 已补齐 5/12 篇');
    t.display(); await settle();
    assert.equal(offs, 4); assert.equal(live(), 4, '重画整页：旧监听注销，新的接上');
    t.showTab('providers'); await settle();
    assert.equal(offs, 8, '切到别的栏：通用（状态卡片）的监听注销'); assert.equal(live(), 0);
    t.hide();
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
    assert.ok(cardOf(t.containerEl, 'schedule').querySelector('.lb-sched'), '定时编辑器在「通用 → 定时同步」卡片里');
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
    // 只有空着的才给填：填地址和模型，原来的密钥引用（环境变量名）一个不删
    const e4 = makePlugin({ textAI: { mode: 'http', endpoint: '', model: '', apiKeyEnv: 'MY_LLM_KEY' }, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text'], aiSynced: true } });
    const t4 = openPage(e4.p, 'ai'); await settle();
    const fill = t4.containerEl.querySelectorAll('button').find(b => /^填上它的地址和模型/.test(b.textContent));
    assert.ok(fill, '地址空着：给「填上它的地址和模型」');
    await fill.onclick(); await settle();
    assert.equal(e4.p.settings.textAI.endpoint, 'https://api.deepseek.com/chat/completions');
    assert.equal(e4.p.settings.textAI.model, 'x');
    assert.equal(e4.p.settings.textAI.apiKeyEnv, 'MY_LLM_KEY', '填推荐值把原来的密钥引用删了');
    t4.hide();
  }

  // —— 11. 10-10 索引树：「分类」文本框换成 编辑索引 / AI 起草 / 未归类建议 / 重新整理目录（都是次要链接），索引文件路径存进 indexFile ——
  {
    const e5 = makePlugin({});
    const hits = [];
    Object.assign(e5.p, { openIndexFile: () => hits.push('open'), indexDraft: async () => { hits.push('draft'); }, openIndexSuggestions: () => hits.push('suggest'),
      indexRebuild: () => hits.push('rebuild'), indexUI: { indexRel: () => e5.p.settings.indexFile || '索引.md' }, run: async args => hits.push('run ' + args.slice(2).join(' ')),
      busyButton: () => () => {} });
    const t5 = openPage(e5.p, 'sync'); await settle();
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
    const t6 = openPage(e6.p, 'sync'); await settle();
    const before = notices.length;
    await rowsOf(t6.containerEl.querySelector('.lb-cats-fold')).find(r => nameOf(r) === '编辑索引').querySelectorAll('button')[0].onclick();
    assert.match(String(notices.slice(before).at(-1)), /索引功能没加载上/);
    t6.hide();
  }

  // —— 12. 1015 定时同步卡片：每次同步最多收几篇（0 = 不限，存 sync.perRunLimit）· 补评论节奏（45 / 90 / 180，存失败改回）——
  {
    assert.deepEqual([Plugin.perRunLimitOf(''), Plugin.perRunLimitOf(null), Plugin.perRunLimitOf('-1'), Plugin.perRunLimitOf('x'), Plugin.perRunLimitOf('7')], [0, 0, 0, 0, 7]);
    assert.deepEqual([Plugin.fillGapOf(90), Plugin.fillGapOf('180'), Plugin.fillGapOf(10), Plugin.fillGapOf(undefined)], [90, 180, 45, 45], '补评论只能比 45 分钟慢');
    const e = makePlugin({}); const t = openPage(e.p, 'sync'); await settle();
    const card = cardOf(t.containerEl, 'schedule');
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
    const e = makePlugin({}); const t = openPage(e.p, 'providers', 'chat'); await settle();
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
    let t = openPage(e.p, 'skills'); await settle();
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
    t.hide(); t = openPage(e.p, 'skills'); await settle();
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

  console.log('PASS settings page (1015 claudian): tabs 通用 · 模型与提供商(5 sub-tabs) · 技能 in cards (one drawn at a time, remembered per session, old open-page names mapped), ≤1 primary per tab, AI toggles drive setup.selected + runtime with deps and sub-options only under an enabled parent, prices + key guide, nothing lost vs pre-1009 inventory (renamed / merged) and no duplicates, one-line descriptions, failed saves revert, sync / fill / problem rows live-watched + unhooked on redraw / tab switch / hide');
})().catch(e => { console.error(e); process.exitCode = 1; });

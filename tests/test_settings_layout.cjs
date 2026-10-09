// 设置页（1009 她的裁决：一页——顶部「状态 · 功能 · 连接 AI」，其余收进一个「高级」；不再有分页、不再有分步向导；
// 重复的设置项删掉只留一处）。
// 断言：
//   1. 一页四块（状态 / 功能 / 连接 AI / 高级），高级默认收起；状态四行；功能每项一行、必需项没有开关、默认轻量版；
//      连接 AI 五个客户端可勾、开放文件夹两个入口并排；
//   2. 开关改 setup.selected（依赖联动）并对上实际起作用的设置（OCR 方式 / 本机语音 / CapsLock / AI 方式）；AI 打开原地出接口那几格 + 参考价；
//   3. 「高级」开没开记在插件对象上，不写 data.json；「打开设置」的落点；
//   4. 一页全部打开后，第 7 批五个分页里的设置项一项不少（挪了地方 / 合并重复的按表对上），重复的只剩一处；
//   5. 收藏同步说明行；6. 同步 / 补评论 / 问题状态文件监听，重画整页 / 关设置页注销；7. 每天最多新抓、评论楼层说明；8. 同步计划说明。
// 不起真进程（CONVENTIONS §7.5）：child_process 换成一碰就炸的桩，runPy / 账号卡片是替身，home-ui / remote-ui / onboarding-ui 是真的。
'use strict';
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
    const b = { buttonEl: el, setButtonText(t) { el.setText(t); return b; }, setCta() { return b; }, setWarning() { return b; },
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
  addToggle(cb) {
    const el = this.controlEl.createEl('div', { cls: 'checkbox-container' });
    const t = { toggleEl: el, setValue(v) { el.checked = !!v; return t; }, setDisabled() { return t; }, onChange(f) { el.onchange = () => f(el.checked); return t; } };
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
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;
const PLUGIN_DIR = '../obsidian-plugins/link-brain-actions/';
const path = require('path');

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
  'setup estimate': { ok: true, items: [{ id: 'summary', name: '概要 + 打标', provider: 'DeepSeek', model: 'x', yuan: 0.8 }], prices: { as_of: '2026-10-03' } },
  'comments --fill-status': { ok: true, pending: 12, ready: 12, cooling: 0, stuck: 0, missing: 340, running: false, message: '12 篇的评论还没补齐' },
  'connect status': { ok: true, clients: { 'claude-code': { installed: true, connected: false, command: 'claude mcp add lwa -s user -- python -m link_brain mcp' },
    'claude-desktop': { installed: true, connected: true } }, json: '{"mcpServers":{}}' },
  'remote status': { ok: true, state: 'running', message: '运行中（127.0.0.1:18071）', auth: { passphrase_set: true, passphrase_copyable: true, clients: [] }, recent: [] },
};
function reply(args) {
  const sub = args.slice(2).join(' ');
  const key = Object.keys(REPLIES).find(k => sub.startsWith(k));
  return key ? REPLIES[key] : { ok: true };
}

// —— 搭一个插件对象：真的 renderSyncRow / readSyncStatus / onboarding-ui / home-ui / remote-ui，假的 vault / 账号卡片 ——
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
  p.saveSettings = async () => { saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.renderAccounts = c => { c.createDiv({ cls: 'lb-accounts' }).createDiv({ cls: 'setting-item lb-acct-row' }); };
  p.capsWriterDir = () => null;
  p.setCapsVoice = async () => true;
  p.runPy = async args => { calls.push(args); return { code: 0, json: reply(args), err: '' }; };
  p.onboardingUI = () => p._onb || (p._onb = require(PLUGIN_DIR + 'onboarding-ui.js')(OBS, p));
  p.homeUI = () => p._home || (p._home = require(PLUGIN_DIR + 'home-ui.js')(OBS, p));
  p.remoteUI = require(PLUGIN_DIR + 'remote-ui.js')(OBS, p);
  return { p, saves, files, calls };
}
function openPage(p) { const tab = new Plugin.__SettingTab({}, p); tab.display(); return tab; }
const flush = () => new Promise(r => setTimeout(r, 0));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

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
const nameOf = row => (row.querySelector('.setting-item-name')?.textContent || '').trim();
const idOf = row => nameOf(row) || row.querySelectorAll('button').map(b => b.textContent.trim()).join('+') || (row.classList.contains('lb-acct-row') ? '〔账号卡片〕' : '');
const section = (root, id) => root.querySelector(`[data-section="${id}"]`);
const visibleRows = (root, el) => rowsOf(el).filter(r => visible(r, root)).map(idOf);
function inventory(root) {
  const items = rowsOf(root).map(idOf).filter(Boolean);
  const req = root.querySelectorAll('div').filter(d => /^· /.test(d.textContent) && !d.children.length).map(d => '电脑需求' + d.textContent.slice(1, 12));
  const conn = root.querySelectorAll('h3').filter(h => h.textContent === '连接 AI').map(() => '〔连接 AI〕');
  return [...items, ...req, ...conn];
}
function openAdvanced(tab) {
  const d = section(tab.containerEl, 'advanced');
  if (!d.open) { d.open = true; d.fire('toggle'); }
}

// 改动前（第 7 批五个分页全部展开）的设置项清单——每种配置一份。1009 改成一页后：只许挪地方 / 合并重复，不许丢。
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
// 1009 挪了地方 / 合并了重复的行（内容没少）：旧身份 → 新身份
const RENAMED = { '电脑需求 视频：语音转写走上面': '电脑需求 视频：语音转写走「A', DeepSeek: '文本 AI',
  '文字识别（OCR）': '本地 OCR（图片里的字）',            // 开关在「功能」，精度 / 模型目录在「高级」
  '其他客户端（JSON 配置）': '其他 MCP 客户端', '〔远程阅读〕': '〔连接 AI〕' };
// 本机 AI 的复制命令只留一处（「连接 AI」）：第二个 Codex（复制 codex mcp add 那行）合进「其他 MCP 客户端」的 JSON
const MERGED = { Codex: 1 };
// 这些设置在一页里只许出现一次（别处有重复的一律删掉只留一处）
const ONCE = ['〔账号卡片〕', '收藏同步', '每天最多新抓', '下载图片', '下载视频', '评论 · 自动拉取', '识图接口', 'CapsLock 语音输入', 'Claude Code', '测试 MCP', '语音识别', '归档摘要模型（默认同文本 AI）', '评论补齐'];

(async () => {
  // —— 1. 一页：状态 · 功能 · 连接 AI · 高级（默认收起），没有分页条、没有分步向导 ——
  const sum = { updated_at: '2026-10-02T04:20:00', needs_human: 1, auto: 2, gave_up: 0, sync: { state: 'ready', message: '收藏同步完成', last_success: '2026-10-02T04:12:00', new: 3, deferred: 0, updated_at: '2026-10-02T04:20:00' } };
  let env = makePlugin({}, { '_archive/problems-summary.json': JSON.stringify(sum) });
  let tab = openPage(env.p); let root = tab.containerEl;
  await settle();
  assert.ok(!root.querySelector('.lb-tabs'), '没有分页条');
  assert.ok(!root.querySelector('.lb-setup') && !root.querySelector('.lb-steps'), '没有分步向导');
  assert.deepEqual(root.querySelectorAll('[data-section]').map(s => s.getAttribute('data-section')), ['status', 'features', 'connect', 'advanced']);
  assert.equal(section(root, 'advanced').tagName, 'DETAILS'); assert.equal(section(root, 'advanced').open, false, '「高级」默认收起');
  assert.deepEqual(visibleRows(root, section(root, 'status')), ['〔账号卡片〕', '收藏同步', '评论补齐', '问题']);
  const statusRow = n => rowsOf(section(root, 'status')).find(r => nameOf(r) === n);
  assert.match(statusRow('评论补齐').querySelector('.setting-item-description').textContent, /12 篇的评论还没补齐（共缺 340 条回复）/);
  assert.match(statusRow('问题').querySelector('.setting-item-description').textContent, /⚠ 1 件要你处理/);
  assert.deepEqual(statusRow('收藏同步').querySelectorAll('button').map(b => b.textContent), ['定时…', '立即同步'], '定时… / 立即同步 在顶部');
  // 功能：每项一行（远程阅读不在这里，在「连接 AI」）；必需的没有开关；默认 = 轻量版
  const feats = section(root, 'features');
  assert.deepEqual(rowsOf(feats.querySelector('.lb-feat-list')).map(nameOf), PLAN.components.filter(c => !c.later).map(c => c.name));
  const featRow = id => feats.querySelector(`.lb-feat[data-id="${id}"]`);
  assert.ok(!featRow('core').querySelector('.checkbox-container'), '必需项没有开关');
  assert.equal(featRow('ocr').querySelector('.checkbox-container').checked, true, '没选过 = 轻量版：OCR 开');
  assert.equal(featRow('asr').querySelector('.checkbox-container').checked, false);
  assert.match(feats.querySelector('.lb-free-line').textContent, /不填 key 也能用/, '没开 AI：说明不填也能用，不出接口那几格');
  assert.ok(feats.querySelector('.lb-run-go'), '有「一键装好 / 跑完」');
  assert.match(feats.querySelector('.lb-run-go').textContent, /一键装好 \/ 跑完/);
  // 连接 AI：五个客户端可勾；没勾时给一句；开放文件夹两个入口并排
  const conn = section(root, 'connect');
  assert.deepEqual(conn.querySelectorAll('.lb-connect-chip').map(c => c.textContent.trim()), ['Claude Code', 'Claude Desktop', 'claude.ai', 'ChatGPT', '其他 MCP 客户端']);
  assert.match(conn.textContent, /上面勾一个/);
  const pickRow = rowsOf(conn).find(r => nameOf(r) === '再开放一个文件夹');
  assert.deepEqual(pickRow.querySelectorAll('button').map(b => b.textContent), ['从库内选…', '选本机文件夹…', '添加'], '两个入口并排 + 手输兜底');
  tab.hide();

  // —— 2. 开关：改的是 setup.selected（依赖联动），顺手对上实际起作用的设置；AI 打开就在原地出接口那几格 ——
  env = makePlugin({});
  tab = openPage(env.p); root = tab.containerEl; await settle();
  let cb = section(root, 'features').querySelector('.lb-feat[data-id="capslock"] .checkbox-container');
  cb.checked = true; await cb.onchange(); await settle();
  assert.deepEqual(Array.from(env.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock'], '勾 CapsLock → 语音识别自动勾上');
  assert.equal(env.p.settings.voice.capsLock, true, 'CapsLock 客户端跟着开');
  cb = section(root, 'features').querySelector('.lb-feat[data-id="asr"] .checkbox-container');
  cb.checked = false; await cb.onchange(); await settle();
  assert.deepEqual(Array.from(env.p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr'], '取消语音识别 → CapsLock 跟着取消');
  assert.equal(env.p.settings.asrAI.mode, 'off');
  cb = section(root, 'features').querySelector('.lb-feat[data-id="ai_text"] .checkbox-container');
  cb.checked = true; await cb.onchange(); await settle();
  const capBox = section(root, 'features').querySelector('.lb-feat-cap[data-cap="textAI"]');
  assert.ok(capBox, 'AI 问答打开 → 原地出接口那几格');
  for (const n of ['文本 AI', '接口地址', 'API Key', '模型', '测试文本 AI']) assert.ok(rowsOf(capBox).some(r => idOf(r) === n), '缺「' + n + '」');
  assert.match(section(root, 'features').querySelector('.lb-estimate-line').textContent, /参考价（每 100 篇）：概要 \+ 打标 ¥0\.80/);
  cb = section(root, 'features').querySelector('.lb-feat[data-id="ocr"] .checkbox-container');
  cb.checked = false; await cb.onchange(); await settle();
  assert.equal(env.p.settings.ocr.mode, 'off', 'OCR 开关就是 OCR 的唯一开关');
  assert.ok(!env.p.settings.setup.selected.includes('ai_vision'), '取消 OCR → 依赖它的识图跟着取消');

  // —— 3. 「高级」开没开记在插件对象上（本次会话），不写 data.json ——
  const savesBefore = env.saves.length;
  openAdvanced(tab);
  assert.ok(rowsOf(section(root, 'advanced')).some(r => nameOf(r) === '每天最多新抓'));
  tab.hide();
  tab = openPage(env.p); root = tab.containerEl; await settle();
  assert.equal(section(root, 'advanced').open, true, '重开设置页「高级」保持展开');
  assert.equal(env.saves.length, savesBefore, '展开收起不写 data.json');
  assert.ok(!JSON.stringify(env.p.settings).includes('"adv"'), '状态不进 settings');
  // 「打开设置」带落点（问题面板 → AI）：滚到「功能」
  env.p.settingsView.focus = 'features';
  tab.display(); assert.equal(env.p.settingsView.focus, null, '落点用过就清');
  tab.hide();

  // —— 4. 一页全部打开（高级展开、两项 AI 打开、五个客户端都勾上）后一项不少、重复的只剩一处 ——
  for (const [k, cfg] of Object.entries(CONFIGS)) {
    const { p } = makePlugin({ ...cfg, setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'asr', 'capslock', 'ai_text', 'ai_vision'] },
      connect: { clients: ['claude-code', 'claude-desktop', 'claude-ai', 'chatgpt', 'other'] } });
    const t = openPage(p); openAdvanced(t); await settle();
    const all = inventory(t.containerEl);
    const count = a => a.reduce((m, x) => m.set(x, (m.get(x) || 0) + 1), new Map());
    const had = count(BASELINE[k].map(x => RENAMED[x] || x)), has = count(all);
    for (const [x, n] of Object.entries(MERGED)) if (had.has(x)) had.set(x, had.get(x) - n);
    const missing = [...had].filter(([x, n]) => !REMOVED.includes(x) && (has.get(x) || 0) < n).map(([x, n]) => `${x} ×${n - (has.get(x) || 0)}`);
    assert.deepEqual(missing, [], `配置 ${k}：少了这些设置项`);
    for (const x of REMOVED) assert.ok(!all.includes(x));
    const dup = ONCE.filter(x => (has.get(x) || 0) > 1).map(x => `${x} ×${has.get(x)}`);
    assert.deepEqual(dup, [], `配置 ${k}：重复的设置项要删到只剩一处`);
    t.hide();
  }

  // —— 5. 同步说明行（顶部「收藏同步」）——
  const syncDesc = async (files) => { const e = makePlugin({}, files); const t = openPage(e.p); await settle();
    return rowsOf(t.containerEl).find(x => nameOf(x) === '收藏同步').querySelector('.setting-item-description').textContent; };
  const line = Plugin.syncSummaryLine;
  const now = new Date(2026, 9, 2, 9, 0).getTime();
  assert.equal(line({ sync: { last_success: new Date(2026, 9, 2, 4, 12).toISOString(), new: 3, deferred: 0 } }, now), '上次：今天 04:12 · 新增 3 篇 · 还剩 0 篇');
  assert.equal(line({ sync: { last_success: new Date(2026, 9, 1, 4, 5).toISOString(), deferred: 4 } }, now), '上次：昨天 04:05 · 还剩 4 篇', '缺 new 不显示那段');
  assert.equal(line({ sync: { new: 2 } }, now), '新增 2 篇', '缺上次时间不显示那段');
  assert.equal(line({ sync: { last_success: '', new: null, deferred: '' } }, now), '');
  assert.equal(line(null, now), '');
  assert.match(await syncDesc({ '_archive/problems-summary.json': JSON.stringify({ sync: { state: 'ready', last_success: new Date().toISOString(), new: 3, deferred: 1 } }) }),
    /^上次：今天 \d\d:\d\d · 新增 3 篇 · 还剩 1 篇 · 定时：没开$/);
  assert.equal(await syncDesc({}), '还没有同步过。登录后点「立即同步」，或点「定时…」开启自动同步。 · 定时：没开');

  // —— 6. 设置页开着时监听同步 / 问题 / 补评论状态文件，变了重画；重画整页 / 关设置页时注销 ——
  {
    const e = makePlugin({}, { '_archive/sync-status.json': JSON.stringify({ state: 'ready', message: '收藏同步完成', updated_at: '2026-10-02T04:20:00' }) });
    const handlers = []; let offs = 0;
    e.p.app.vault.on = (ev, cb2) => { const ref = { ev, cb: cb2, live: true }; handlers.push(ref); return ref; };
    e.p.app.vault.offref = ref => { ref.live = false; offs++; };
    const t = openPage(e.p); await settle();
    const desc = () => rowsOf(t.containerEl).find(x => nameOf(x) === '收藏同步').querySelector('.setting-item-description').textContent;
    assert.match(desc(), /^收藏同步完成/);
    const live = () => handlers.filter(h => h.live).length;
    assert.equal(live(), 4, '同步那一行 2 个 + 补评论 / 问题那两行 2 个');
    e.files['_archive/sync-status.json'] = JSON.stringify({ state: 'running', message: '正在同步收藏：《a》查附件 / 下附件中', updated_at: new Date().toISOString(), done: 3, total: 10 });
    handlers.filter(h => h.live && h.ev === 'modify').forEach(h => h.cb({ path: '_archive/sync-status.json' }));
    await new Promise(r => setTimeout(r, 350)); await settle();
    assert.equal(desc(), '正在同步收藏：《a》查附件 / 下附件中 · 已完成 3/10 篇 · 剩 7 篇 · 定时：没开');
    e.files['_archive/comments-fill-status.json'] = JSON.stringify({ state: 'running', message: '正在补评论 · 已补齐 5/12 篇', updated_at: new Date().toISOString() });
    handlers.filter(h => h.live && h.ev === 'modify').forEach(h => h.cb({ path: '_archive/comments-fill-status.json' }));
    await new Promise(r => setTimeout(r, 350)); await settle();
    assert.equal(rowsOf(t.containerEl).find(x => nameOf(x) === '评论补齐').querySelector('.setting-item-description').textContent, '正在补评论 · 已补齐 5/12 篇');
    t.display(); await settle();
    assert.equal(offs, 4); assert.equal(live(), 4, '重画整页：旧监听注销，新的接上');
    t.hide();
    assert.equal(offs, 8, '关设置页注销'); assert.equal(live(), 0);
  }

  // —— 7. 每天最多新抓（在「高级 → 同步」）——默认 50，清空回 50，0 = 不限；评论楼层说明 ——
  {
    const f = Plugin.dailyNewLimitOf;
    assert.deepEqual([f(''), f('  '), f(null), f(undefined), f('abc'), f('-3'), f('2.5')], [50, 50, 50, 50, 50, 50, 50]);
    assert.deepEqual([f('0'), f(0), f('30'), f(200)], [0, 0, 30, 200]);
    const e = makePlugin({}); const t = openPage(e.p); openAdvanced(t); await settle();
    const input = rowsOf(t.containerEl).find(x => nameOf(x) === '每天最多新抓').querySelector('input');
    assert.equal(input.value, '50');
    input.value = ''; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 50, '清空回落 50');
    input.value = '0'; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 0, '0 = 不限，照存');
    const floors = rowsOf(t.containerEl).find(x => nameOf(x) === '评论 · 自动拉取');
    assert.match(floors.querySelector('.setting-item-description').textContent, /默认前 10 楼/);
    assert.match(floors.querySelector('.setting-item-description').textContent, /调小不删已经存下的；调大会在后台给旧笔记补到新楼数/);
  }

  // —— 8. 同步计划「当前：…」——认不出的不冒充每天，别的触发器列出来 ——
  {
    const st = Plugin.scheduleStatusText;
    assert.equal(st({ freq: 'daily', enabled: true, time: '04:00', others: ['一次性 2026-10-02 00:00'], next_run: '2026-10-03T04:00:00' }),
      '当前：每天 04:00　·　另有：一次性 2026-10-02 00:00（不改动）　·　下次 2026-10-03 04:00:00');
    assert.equal(st({ freq: 'none' }), '当前：没有计划任务');
  }

  console.log('PASS settings page (1009): one page 状态 · 功能 · 连接 AI · 高级 (collapsed, remembered per session), no wizard / tabs, toggles drive setup.selected + runtime settings with deps, AI fields inline, run-all button, 5 connect clients + 2 folder pickers, nothing lost vs pre-1009 inventory and no duplicates, sync / fill / problem rows live-watched + unhooked');
})().catch(e => { console.error(e); process.exitCode = 1; });

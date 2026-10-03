// 设置页布局。第 4 批末收纳（第一层 + 「更多」）→ 第 7 批改成顶部分页：开始 / 同步与内容 / AI / 远程阅读 / 高级。
// 断言：
//   1. 顶部一排 5 个分页，默认「开始」；每个设置分页里放的是哪些行（「其他 AI 能力」默认收起）；
//   2. 上次打开的分页、「其他 AI 能力」展开没有：记在插件对象上（重开设置页保持），不写 data.json；
//   3. 五个分页全部打开、全部展开后，改动前的每一项设置都还在（BASELINE 是第 4 批改动前从旧 display() 抽出来的清单，
//      唯一删掉的是「搜索收藏 · 打开目录」；只许增不许减）；
//   4. 「其他 AI 能力」的摘要随设置变化；
//   5. 收藏同步说明行从 problems-summary.json 的 sync 段取「上次 / 新增 / 还剩」，缺值不显示那段，都没有就用原来的状态文字。
// 不起真进程（CONVENTIONS §7.5）：child_process 换成一碰就炸的桩，runPy / 账号卡片 / 远程阅读都是替身。
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
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, navigator: { clipboard: { writeText: async () => {} } },
  require: n => n === 'obsidian' ? OBS
    : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8')
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;
const PLUGIN_DIR = '../obsidian-plugins/link-brain-actions/';

// —— 搭一个插件对象：真的 renderSyncRow / readSyncStatus / onboarding-ui / setup-ui，假的 vault / 账号卡片 / 远程阅读 ——
function makePlugin(saved, files = {}) {
  const p = new Plugin();
  const saves = [];
  p.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async f => f in files, read: async f => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f]; } } } };
  p.lbRoot = '';
  p.settings = Plugin.__merge(saved);
  p.saveSettings = async () => { saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.renderAccounts = c => { c.createDiv({ cls: 'lb-accounts' }).createDiv({ cls: 'setting-item lb-acct-row' }); };
  p.capsWriterDir = () => null;
  p.remoteUI = { render(box) { box.createEl('h4', { text: '远程阅读（MCP）' }); } };
  p.runPy = async () => ({ json: { ok: true }, err: '' });
  p.onboardingUI = () => p._onb || (p._onb = require(PLUGIN_DIR + 'onboarding-ui.js')(OBS, p));
  p.setupUI = () => p._setup || (p._setup = require(PLUGIN_DIR + 'setup-ui.js')(OBS, p));
  return { p, saves, files };
}
const TAB_IDS = ['start', 'sync', 'ai', 'remote', 'advanced'];
// 打开设置页（可指定停在哪个分页；不指定 = 上次那个）
function openTab(p, id) { if (id) p.settingsView = { ...(p.settingsView || { otherAI: false }), tab: id }; const tab = new Plugin.__SettingTab({}, p); tab.display(); return tab; }
const flush = () => new Promise(r => setTimeout(r, 0));

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
// 一行设置的身份：有名字用名字；没名字（只有按钮那种）用按钮文字
const idOf = row => nameOf(row) || row.querySelectorAll('button').map(b => b.textContent.trim()).join('+') || (row.classList.contains('lb-acct-row') ? '〔账号卡片〕' : '');
function inventory(root) {
  const items = rowsOf(root).map(idOf).filter(Boolean);
  const req = root.querySelectorAll('div').filter(d => /^· /.test(d.textContent) && !d.children.length).map(d => '电脑需求' + d.textContent.slice(1, 12));
  const remote = root.querySelectorAll('h4').filter(h => h.textContent === '远程阅读（MCP）').map(() => '〔远程阅读〕');
  return [...items, ...req, ...remote];
}
// 当前分页里能展开的都展开（「其他 AI 能力」、任何 details）
function expandAll(tab) {
  const root = tab.containerEl;
  for (const d of root.querySelectorAll('details')) if (!d.open) { d.open = true; d.fire('toggle'); }
  const btn = root.querySelector('.lb-other-ai')?.querySelector('button');
  if (btn && root.querySelector('.lb-other-ai-body')?.classList.contains('is-collapsed')) btn.click();
}
// 五个分页挨个打开、全部展开，清单拼起来；顺带收集展开后还藏着的行
async function inventoryAll(p) {
  const all = [], hidden = [];
  for (const id of TAB_IDS) {
    const t = openTab(p, id); expandAll(t); await flush();
    all.push(...inventory(t.containerEl));
    hidden.push(...rowsOf(t.containerEl).filter(r => !visible(r, t.containerEl)).map(r => id + ':' + idOf(r)));
    t.hide();
  }
  return { all, hidden };
}
const tabButtons = root => root.querySelector('.lb-tabs').querySelectorAll('button');
const paneOf = root => root.querySelector('.lb-tab-pane');
const visibleRows = root => rowsOf(paneOf(root)).filter(r => visible(r, root)).map(idOf);
const headsOf = root => paneOf(root).querySelectorAll('h3,h4').map(h => h.textContent);

// 改动前（c133b3d 的 display()）从旧代码抽出来的设置项清单——每种配置一份。
// 生成：在旧代码上跑本文件 `LB_DUMP=1 node tests/test_settings_layout.cjs`（见末尾）；之后只许增不许减。
const CONFIGS = {
  defaults: {},
  alt: { textAI: { mode: 'cli', command: 'x' }, summaryAI: { mode: 'http' }, visionAI: { mode: 'off' }, asrAI: { mode: 'http' }, voice: { capsLock: false } },
  legacy: { textAI: { mode: 'http', endpoint: 'https://api.example.com/v1/chat/completions', keyFile: 'k.csv' }, visionAI: { mode: 'media' }, asrAI: { mode: 'media' }, ocr: { mode: 'media' } },
};
const BASELINE = {
  defaults: ["〔账号卡片〕","收藏同步","登录后自动同步","下载图片","下载视频","评论 · 自动拉取","评论 · 手动拉取","每天最多新抓","文本 AI","接口地址","API Key","模型","测试文本 AI","归档摘要模型（默认同文本 AI）","模型","测试归档摘要","识图接口","接口地址","API Key","模型","精细识别模型","测试识图","视频画面文字","语音识别","端口","测试语音识别","CapsLock 语音输入","CapsWriter 目录","输入框提示文字","DeepSeek","Codex","Sonnet","添加模型","Claude Code","Codex","其他客户端（JSON 配置）","测试 MCP","搜索收藏","批注昵称","下载文件夹","检查本机环境","文字识别（OCR）","识别精度","模型目录（可选）","测试 OCR","摘要提示词（归档时抽取）","问答提示词（/问AI）","回答输出上限（max_tokens）","发给模型的总字符上限","每篇片段字符上限","送模型的片段篇数（topK）","先用小模型扩检索词","载入当前大类+清空（用内置）+重建目录","等待手动下载（分钟）","待补附件","电脑需求 必需：Windows","电脑需求 内存：建议 8 GB","电脑需求 收藏问答：文本模型（","电脑需求 图片文字：本地 OC","电脑需求 附件：PDF / W","电脑需求 视频：语音转写走上面","电脑需求 语音输入：CapsW","〔远程阅读〕"],
  alt: ["〔账号卡片〕","收藏同步","登录后自动同步","下载图片","下载视频","评论 · 自动拉取","评论 · 手动拉取","每天最多新抓","文本 AI","命令","测试文本 AI","归档摘要模型（默认同文本 AI）","接口地址","API Key","模型","测试归档摘要","识图接口","测试识图","视频画面文字","语音识别","接口地址","API Key","模型","测试语音识别","CapsLock 语音输入","CapsWriter 目录","输入框提示文字","DeepSeek","Codex","Sonnet","添加模型","Claude Code","Codex","其他客户端（JSON 配置）","测试 MCP","搜索收藏","批注昵称","下载文件夹","检查本机环境","文字识别（OCR）","识别精度","模型目录（可选）","测试 OCR","摘要提示词（归档时抽取）","问答提示词（/问AI）","回答输出上限（max_tokens）","发给模型的总字符上限","每篇片段字符上限","送模型的片段篇数（topK）","先用小模型扩检索词","载入当前大类+清空（用内置）+重建目录","等待手动下载（分钟）","待补附件","电脑需求 必需：Windows","电脑需求 内存：建议 8 GB","电脑需求 收藏问答：文本模型（","电脑需求 图片文字：本地 OC","电脑需求 附件：PDF / W","电脑需求 视频：语音转写走上面","电脑需求 语音输入：CapsW","〔远程阅读〕"],
  legacy: ["〔账号卡片〕","收藏同步","登录后自动同步","下载图片","下载视频","评论 · 自动拉取","评论 · 手动拉取","每天最多新抓","文本 AI","接口地址","API Key","模型","测试文本 AI","归档摘要模型（默认同文本 AI）","模型","测试归档摘要","识图接口","测试识图","视频画面文字","语音识别","测试语音识别","CapsLock 语音输入","CapsWriter 目录","输入框提示文字","DeepSeek","Codex","Sonnet","添加模型","Claude Code","Codex","其他客户端（JSON 配置）","测试 MCP","搜索收藏","批注昵称","下载文件夹","检查本机环境","文字识别（OCR）","测试 OCR","摘要提示词（归档时抽取）","问答提示词（/问AI）","回答输出上限（max_tokens）","发给模型的总字符上限","每篇片段字符上限","送模型的片段篇数（topK）","先用小模型扩检索词","载入当前大类+清空（用内置）+重建目录","等待手动下载（分钟）","待补附件","电脑需求 必需：Windows","电脑需求 内存：建议 8 GB","电脑需求 收藏问答：文本模型（","电脑需求 图片文字：本地 OC","电脑需求 附件：PDF / W","电脑需求 视频：语音转写走上面","电脑需求 语音输入：CapsW","〔远程阅读〕"],
};
const REMOVED = ['搜索收藏'];   // 唯一删掉的一行：目录页本来就有入口

// 第 7 批改了文字的行（内容没少，只是说法跟着分页变了）：旧身份 → 新身份
const RENAMED = { '电脑需求 视频：语音转写走上面': '电脑需求 视频：语音转写走「A' };

(async () => {
  if (process.env.LB_DUMP) {
    const out = {};
    for (const [k, cfg] of Object.entries(CONFIGS)) { const { p } = makePlugin(cfg); out[k] = (await inventoryAll(p)).all; }
    console.log(JSON.stringify(out, null, 2)); return;
  }

  // —— 1. 顶部分页 + 各分页放了什么 ——
  const sum = { updated_at: '2026-10-02T04:20:00', sync: { state: 'ready', message: '收藏同步完成', last_success: '2026-10-02T04:12:00', new: 3, deferred: 0, updated_at: '2026-10-02T04:20:00' } };
  let env = makePlugin({}, { '_archive/problems-summary.json': JSON.stringify(sum) });
  let tab = openTab(env.p);
  let root = tab.containerEl;
  assert.deepEqual(tabButtons(root).map(b => b.textContent), ['开始', '同步与内容', 'AI', '远程阅读', '高级'], '顶部五个分页');
  assert.deepEqual(tabButtons(root).filter(b => b.classList.contains('is-active')).map(b => b.textContent), ['开始'], '默认「开始」');
  assert.ok(paneOf(root).querySelector('.lb-setup'), '「开始」分页是向导');
  assert.ok(!root.querySelector('details.lb-more'), '「更多」折叠拆进了各分页');
  tab.hide();

  tab = openTab(env.p, 'sync'); root = tab.containerEl;
  assert.deepEqual(visibleRows(root), ['〔账号卡片〕', '收藏同步', '每天最多新抓', '登录后自动同步', '下载图片', '下载视频', '评论 · 自动拉取', '评论 · 手动拉取',
    '下载文件夹', '等待手动下载（分钟）', '待补附件', '批注昵称', '批注留言对象'], '同步与内容');
  assert.deepEqual(headsOf(root), ['账号', '收藏同步', '收藏同步细项', '下载', '附件', '批注']);
  const row = n => rowsOf(root).find(r => nameOf(r) === n);
  assert.equal(row('每天最多新抓').querySelector('.setting-item-description').textContent, '防风控；第一次补历史收藏会分几天完成。默认 50，清空就回到 50；填 0 = 不限（一次抓太多容易触发风控）。');
  assert.deepEqual(row('收藏同步').querySelectorAll('button').map(b => b.textContent), ['定时…', '立即同步'], '定时… / 立即同步 照旧');
  tab.hide();

  tab = openTab(env.p, 'ai'); root = tab.containerEl;
  assert.deepEqual(visibleRows(root), ['文本 AI', '接口地址', 'API Key', '模型', '测试文本 AI', '其他 AI 能力', '输入框提示文字', 'DeepSeek', 'Codex', 'Sonnet', '添加模型',
    '文字识别（OCR）', '识别精度', '模型目录（可选）', '测试 OCR'], 'AI（其他 AI 能力收起）');
  assert.deepEqual(headsOf(root), ['AI（问收藏用）', '问答模型', '文字识别（OCR）']);
  assert.match(rowsOf(root).find(r => nameOf(r) === '文本 AI').querySelector('.setting-item-description').textContent, /^问收藏页的回答用它。没配时问答用不了；归档、浏览、关键词搜索不受影响。/);
  assert.ok(root.querySelector('.lb-other-ai-body').classList.contains('is-collapsed'), '「其他 AI 能力」默认收起');
  const otherNames = rowsOf(root.querySelector('.lb-other-ai-body')).map(idOf);
  for (const n of ['归档摘要模型（默认同文本 AI）', '测试归档摘要', '识图接口', '精细识别模型', '测试识图', '视频画面文字', '语音识别', '端口', '测试语音识别', 'CapsLock 语音输入', 'CapsWriter 目录'])
    assert.ok(otherNames.includes(n), `其他 AI 能力里缺「${n}」`);

  tab = openTab(env.p, 'remote'); root = tab.containerEl;
  assert.match(paneOf(root).querySelector('.lb-remote-intro').textContent, /需要自备域名和隧道（高级）/, '远程阅读顶部先说要什么');
  assert.match(paneOf(root).querySelector('.lb-remote-intro').textContent, /Notion.*以后支持/);
  assert.deepEqual(visibleRows(root), ['Claude Code', 'Codex', '其他客户端（JSON 配置）', '测试 MCP'], '外接 MCP 的复制按钮');
  assert.equal(paneOf(root).querySelector('ol.lb-install-steps').querySelectorAll('li').length, 3, '外接的安装 / 复制三步');
  assert.deepEqual(headsOf(root), ['外接 MCP', '远程阅读（MCP）']);

  tab = openTab(env.p, 'advanced'); root = tab.containerEl;
  assert.deepEqual(visibleRows(root), ['检查本机环境', '后端命令', '收藏存放位置', '摘要提示词（归档时抽取）', '问答提示词（/问AI）', '回答输出上限（max_tokens）', '发给模型的总字符上限',
    '每篇片段字符上限', '送模型的片段篇数（topK）', '先用小模型扩检索词', '', '载入当前大类+清空（用内置）+重建目录'], '高级（空名那行是目录大类的输入框）');
  assert.deepEqual(headsOf(root), ['运行环境', '电脑需求', '提示词', '问答用量', '目录大类']);
  assert.ok(!rowsOf(root).some(r => nameOf(r) === '搜索收藏'), '「搜索收藏 · 打开目录」删掉了');

  // —— 2. 分页 / 展开记在插件对象上（本次会话），不写 data.json ——
  env = makePlugin({});
  tab = openTab(env.p); root = tab.containerEl;
  const savesBefore = env.saves.length;
  tabButtons(root).find(b => b.textContent === '同步与内容').click();
  root = tab.containerEl;
  assert.deepEqual(tabButtons(root).filter(b => b.classList.contains('is-active')).map(b => b.textContent), ['同步与内容'], '点分页就换');
  assert.ok(rowsOf(paneOf(root)).some(r => nameOf(r) === '每天最多新抓'));
  tab.hide();
  tab = openTab(env.p); root = tab.containerEl;   // 重开设置页
  assert.equal(root.querySelector('.lb-tab.is-active').textContent, '同步与内容', '重开设置页停在上次的分页');
  tabButtons(root).find(b => b.textContent === 'AI').click(); root = tab.containerEl;
  expandAll(tab);
  assert.equal(rowsOf(root).find(r => nameOf(r) === '其他 AI 能力').querySelector('button').textContent, '收起');
  tab = openTab(env.p); root = tab.containerEl;
  assert.equal(root.querySelector('.lb-tab.is-active').textContent, 'AI');
  assert.ok(!root.querySelector('.lb-other-ai-body').classList.contains('is-collapsed'), '重开设置页「其他 AI 能力」保持展开');
  root.querySelector('.lb-other-ai').querySelector('button').click();
  tab = openTab(env.p); root = tab.containerEl;
  assert.ok(root.querySelector('.lb-other-ai-body').classList.contains('is-collapsed'), '收起也记住');
  assert.equal(env.saves.length, savesBefore, '换分页 / 展开收起不写 data.json');
  assert.ok(!('settingsView' in env.p.settings) && !JSON.stringify(env.p.settings).includes('otherAI'), '状态不进 settings');

  // —— 3. 五个分页全部打开、全部展开后一项不少 ——
  for (const [k, cfg] of Object.entries(CONFIGS)) {
    const { p } = makePlugin(cfg);
    const { all, hidden } = await inventoryAll(p);
    const count = a => a.reduce((m, x) => m.set(x, (m.get(x) || 0) + 1), new Map());
    const had = count(BASELINE[k].map(x => RENAMED[x] || x)), has = count(all);
    const missing = [...had].filter(([x, n]) => !REMOVED.includes(x) && (has.get(x) || 0) < n).map(([x, n]) => `${x} ×${n - (has.get(x) || 0)}`);
    assert.deepEqual(missing, [], `配置 ${k}：展开后少了这些设置项`);
    for (const x of REMOVED) assert.ok(!all.includes(x));
    assert.deepEqual(hidden, [], `配置 ${k}：全部展开后不该还有藏着的行`);
  }

  // —— 4. 摘要随设置变化 ——
  const summaryOf = r => rowsOf(r).find(x => nameOf(x) === '其他 AI 能力').querySelector('.setting-item-description').textContent;
  env = makePlugin({ visionAI: { mode: 'off' } }); tab = openTab(env.p, 'ai');
  assert.equal(summaryOf(tab.containerEl), '归档摘要：和文本 AI 相同 · 识图：未开启 · 语音识别：本机 CapsWriter');
  env = makePlugin({ summaryAI: { mode: 'off' }, visionAI: { mode: 'http', endpoint: 'https://v.example.com/v1/chat/completions', model: 'vl-model' }, asrAI: { mode: 'http', model: 'whisper-1' } });
  tab = openTab(env.p, 'ai');
  assert.equal(summaryOf(tab.containerEl), '归档摘要：关闭 · 识图：vl-model · 语音识别：接口 whisper-1');
  // 在展开块里改模式（下拉 onChange → 存 + 重画）摘要跟着变
  expandAll(tab);
  const sumDd = rowsOf(tab.containerEl).find(x => nameOf(x) === '归档摘要模型（默认同文本 AI）').querySelector('select');
  sumDd.value = 'inherit'; await sumDd.onchange();
  await flush();
  assert.match(summaryOf(tab.containerEl), /^归档摘要：和文本 AI 相同 · /);
  // 只改文字（不重画）摘要也跟着变
  const modelInput = rowsOf(tab.containerEl).find(x => nameOf(x) === '模型' && x.parentNode.closest('.lb-other-ai-body'))?.querySelector('input');
  assert.ok(modelInput, '归档摘要的「模型」在展开块里');
  modelInput.value = 'cheap-model'; await modelInput.oninput(); await flush();
  assert.match(summaryOf(tab.containerEl), /^归档摘要：文本 AI 接口 · cheap-model · /);
  assert.equal(env.p.settings.summaryAI.model, 'cheap-model', '存储键不变');

  // —— 5. 同步说明行 ——
  const syncDesc = async (files) => { const e = makePlugin({}, files); const t = openTab(e.p, 'sync'); await flush(); await flush();
    return rowsOf(t.containerEl).find(x => nameOf(x) === '收藏同步').querySelector('.setting-item-description').textContent; };
  const line = Plugin.syncSummaryLine;
  const now = new Date(2026, 9, 2, 9, 0).getTime();
  assert.equal(line({ sync: { last_success: new Date(2026, 9, 2, 4, 12).toISOString(), new: 3, deferred: 0 } }, now), '上次：今天 04:12 · 新增 3 篇 · 还剩 0 篇');
  assert.equal(line({ sync: { last_success: new Date(2026, 9, 1, 4, 5).toISOString(), deferred: 4 } }, now), '上次：昨天 04:05 · 还剩 4 篇', '缺 new 不显示那段');
  assert.equal(line({ sync: { new: 2 } }, now), '新增 2 篇', '缺上次时间不显示那段');
  assert.equal(line({ sync: { last_success: '', new: null, deferred: '' } }, now), '');
  assert.equal(line(null, now), '');
  assert.match(line({ sync: { last_success: new Date(2026, 8, 20, 22, 30).toISOString() } }, now), /^上次：9\/20 22:30$/);
  // 接到设置页：有 summary 用它；没有 summary 用原来的状态文字
  assert.match(await syncDesc({ '_archive/problems-summary.json': JSON.stringify({ sync: { state: 'ready', last_success: new Date().toISOString(), new: 3, deferred: 1 } }) }),
    /^上次：今天 \d\d:\d\d · 新增 3 篇 · 还剩 1 篇$/);
  assert.equal(await syncDesc({}), '还没有同步过。登录后点「立即同步」，或点「定时…」开启自动同步。');
  assert.match(await syncDesc({ '_archive/sync-status.json': JSON.stringify({ state: 'ready', message: '收藏同步完成', updated_at: '2026-10-02T04:20:00', synced: 5 }) }),
    /^收藏同步完成 · .* · 本次 5 条$/, 'summary 里没有这几项：照旧显示状态文字');
  assert.match(await syncDesc({ '_archive/problems-summary.json': JSON.stringify({ sync: { state: 'running', message: '正在同步收藏', last_success: new Date().toISOString(), new: 1 } }) }),
    /^正在同步收藏 · 上次：今天 \d\d:\d\d · 新增 1 篇$/, '同步中 / 失败时状态放在前面');

  // —— 6. 第 5 批 4.5：设置页开着时监听两份同步文件，变了重画那一行；hide() / 重画整页 / 换分页时注销 ——
  {
    const e = makePlugin({}, { '_archive/sync-status.json': JSON.stringify({ state: 'ready', message: '收藏同步完成', updated_at: '2026-10-02T04:20:00' }) });
    const handlers = []; let offs = 0;
    e.p.app.vault.on = (ev, cb) => { const ref = { ev, cb, live: true }; handlers.push(ref); return ref; };
    e.p.app.vault.offref = ref => { ref.live = false; offs++; };
    const t = openTab(e.p, 'sync'); await flush(); await flush();
    const desc = () => rowsOf(t.containerEl).find(x => nameOf(x) === '收藏同步').querySelector('.setting-item-description').textContent;
    assert.match(desc(), /^收藏同步完成/);
    assert.deepEqual(handlers.map(h => h.ev), ['modify', 'create'], '监听 modify + create');
    // 同步开始：sync-status.json 改成 running，带后端阶段和（若有）完成数 / 剩余
    e.files['_archive/sync-status.json'] = JSON.stringify({ state: 'running', message: '正在同步收藏：《a》查附件 / 下附件中', updated_at: new Date().toISOString(), done: 3, total: 10 });
    handlers.filter(h => h.live).forEach(h => h.cb({ path: 'other.md' }));
    await new Promise(r => setTimeout(r, 350)); await flush();
    assert.match(desc(), /^收藏同步完成/, '别的文件变了不重画');
    handlers.filter(h => h.live && h.ev === 'modify').forEach(h => h.cb({ path: '_archive/sync-status.json' }));
    await new Promise(r => setTimeout(r, 350)); await flush(); await flush();
    assert.equal(desc(), '正在同步收藏：《a》查附件 / 下附件中 · 已完成 3/10 篇 · 剩 7 篇');
    // 重画整页：旧监听注销，新的接上（不会越开越多）
    t.display(); await flush();
    assert.equal(offs, 2); assert.equal(handlers.filter(h => h.live).length, 2);
    // 换到别的分页：监听注销，不再盯着
    t.showTab('advanced'); await flush();
    assert.equal(offs, 4, '换分页注销'); assert.equal(handlers.filter(h => h.live).length, 0);
    t.showTab('sync'); await flush();
    assert.equal(handlers.filter(h => h.live).length, 2);
    t.hide();
    assert.equal(offs, 6, '关设置页注销'); assert.equal(handlers.filter(h => h.live).length, 0);
    // 没完成数就只显示阶段，不编数字
    assert.equal(Plugin.syncStateHead({ state: 'running', message: '正在同步收藏：抓取中' }), '正在同步收藏：抓取中');
    assert.equal(Plugin.syncStateHead({ state: 'running', message: 'x', remaining: 4 }), 'x · 剩 4 篇');
    assert.equal(Plugin.syncStateHead({ state: 'ready', message: '收藏同步完成' }), '');
  }

  // —— 7. 第 5 批 4.1：每天最多新抓——默认 50，清空回 50，0 = 不限 ——
  {
    const f = Plugin.dailyNewLimitOf;
    assert.deepEqual([f(''), f('  '), f(null), f(undefined), f('abc'), f('-3'), f('2.5')], [50, 50, 50, 50, 50, 50, 50]);
    assert.deepEqual([f('0'), f(0), f('30'), f(200)], [0, 0, 30, 200]);
    assert.equal(Plugin.__merge({}).sync.dailyNewLimit, 50, '新装默认 50（和 ai_config.py 一致）');
    const e = makePlugin({}); const t = openTab(e.p, 'sync');
    const input = rowsOf(t.containerEl).find(x => nameOf(x) === '每天最多新抓').querySelector('input');
    assert.equal(input.value, '50');
    input.value = ''; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 50, '清空回落 50');
    input.value = '0'; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 0, '0 = 不限，照存');
    input.value = '120'; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 120);
    const floors = rowsOf(t.containerEl).find(x => nameOf(x) === '评论 · 自动拉取');
    assert.match(floors.querySelector('.setting-item-description').textContent, /默认前 10 楼/);
    assert.ok(!/默认全部/.test(floors.querySelector('.setting-item-description').textContent), '说明和下拉的默认一致');
    // 第 7 批新增的 setup.* 键：默认值，不碰别的键
    assert.deepEqual(JSON.parse(JSON.stringify(Plugin.__merge({}).setup)), { selected: null, step: 1, collapsed: false, passed: [] });
  }

  // —— 8. 第 5 批 4.4：同步计划「当前：…」——认不出的不冒充每天，别的触发器列出来 ——
  {
    const st = Plugin.scheduleStatusText;
    assert.equal(st({ freq: 'daily', enabled: true, time: '04:00', others: ['一次性 2026-10-02 00:00'], next_run: '2026-10-03T04:00:00' }),
      '当前：每天 04:00　·　另有：一次性 2026-10-02 00:00（不改动）　·　下次 2026-10-03 04:00:00');
    assert.equal(st({ freq: 'unknown', enabled: true, time: '', others: ['一次性 2026-10-02 00:00', '登录时'] }),
      '当前：自定义触发器（一次性 2026-10-02 00:00、登录时），未改动');
    assert.equal(st({ freq: 'weekly', enabled: true, time: '22:30', day: 'Monday,Thursday', others: [] }), '当前：每周周一、周四 22:30');
    assert.equal(st({ freq: 'daily', enabled: false, time: '04:00', others: [], next_run: '2026-10-03T04:00:00' }), '当前：已关闭（整个计划任务停用，原来是每天 04:00）');
    assert.equal(st({ freq: 'none' }), '当前：没有计划任务');
    assert.match(st({ error: '拒绝访问' }), /读不到计划任务（拒绝访问）/);
  }

  console.log('PASS settings layout: 5 top tabs (default 开始) remembered per session, each tab holds its rows, nothing lost vs pre-change inventory across all tabs, AI summary live, sync line from summary; batch5: sync row live-watched + unhooked on hide / tab switch, daily limit 50/0=unlimited, schedule status honest');
})().catch(e => { console.error(e); process.exitCode = 1; });

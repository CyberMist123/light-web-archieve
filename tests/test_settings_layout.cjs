// 设置页收纳（第 4 批末，她拍板的方案）：第一层只留开箱要碰的几行，其余整块收进「更多」。
// 断言：
//   1. 第一层（「更多」收起、「其他 AI 能力」收起）只有：账号卡片 · 收藏同步 · 每天最多新抓 · 文本 AI（+ 三格 + 测试）· 其他 AI 能力 · 批注昵称；
//   2. 「更多」默认收起；「其他 AI 能力」默认收起；两者的展开状态在同一个插件对象里记住（重开设置页保持），不写 data.json；
//   3. 全部展开后，改动前的每一项设置都还在（BASELINE 是改动前从旧 display() 抽出来的清单，唯一删掉的是「搜索收藏 · 打开目录」）；
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
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, navigator: { clipboard: { writeText: async () => {} } },
  require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class { constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = dom.document.createElement('div'); } },
    Modal: class {}, Setting: FakeSetting, Notice: class { constructor(m) { notices.push(m); } }, Menu: class {} }
    : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8')
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;

// —— 搭一个插件对象：真的 renderSyncRow / readSyncStatus，假的 vault / 账号卡片 / 远程阅读 ——
function makePlugin(saved, files = {}) {
  const p = new Plugin();
  const saves = [];
  p.app = { vault: { adapter: { getBasePath: () => 'D:/vault', read: async f => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f]; } } } };
  p.lbRoot = '';
  p.settings = Plugin.__merge(saved);
  p.saveSettings = async () => { saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.renderAccounts = c => { c.createDiv({ cls: 'lb-accounts' }).createDiv({ cls: 'setting-item lb-acct-row' }); };
  p.capsWriterDir = () => null;
  p.remoteUI = { render(box) { box.createEl('h4', { text: '远程阅读（MCP）' }); } };
  p.runPy = async () => ({ json: { ok: true }, err: '' });
  return { p, saves, files };
}
function openTab(p) { const tab = new Plugin.__SettingTab({}, p); tab.display(); return tab; }
const flush = () => new Promise(r => setTimeout(r, 0));

// 一个元素此刻用户看不看得见：祖先里有收起的「更多」（details 未 open，且不在 summary 里）或 is-collapsed / hidden
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
function expandAll(tab) {
  const root = tab.containerEl;
  for (const d of root.querySelectorAll('details')) if (!d.open) { d.open = true; d.fire('toggle'); }
  const btn = root.querySelector('.lb-other-ai')?.querySelector('button');
  if (btn && root.querySelector('.lb-other-ai-body')?.classList.contains('is-collapsed')) btn.click();
}

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

(async () => {
  if (process.env.LB_DUMP) {
    const out = {};
    for (const [k, cfg] of Object.entries(CONFIGS)) { const { p } = makePlugin(cfg); const tab = openTab(p); expandAll(tab); await flush(); out[k] = inventory(tab.containerEl); }
    console.log(JSON.stringify(out, null, 2)); return;
  }

  // —— 1. 第一层 ——
  const sum = { updated_at: '2026-10-02T04:20:00', sync: { state: 'ready', message: '收藏同步完成', last_success: '2026-10-02T04:12:00', new: 3, deferred: 0, updated_at: '2026-10-02T04:20:00' } };
  let env = makePlugin({}, { '_archive/problems-summary.json': JSON.stringify(sum) });
  let tab = openTab(env.p);
  let root = tab.containerEl;
  const top = rowsOf(root).filter(r => visible(r, root)).map(idOf);
  assert.deepEqual(top, ['〔账号卡片〕', '收藏同步', '每天最多新抓', '文本 AI', '接口地址', 'API Key', '模型', '测试文本 AI', '其他 AI 能力', '批注昵称', '批注留言对象'], '第一层只有这几行');
  const heads = root.children.filter(e => /^H[234]$/.test(e.tagName)).map(e => e.textContent);
  assert.deepEqual(heads, ['账号', '收藏同步', 'AI（问收藏用）', '批注'], '第一层标题');
  assert.equal(root.children.at(-1).tagName, 'DETAILS', '「更多」在最后');
  assert.equal(root.querySelector('details.lb-more')?.children[0]?.textContent, '更多');
  assert.equal(!!root.querySelector('details.lb-more').open, false, '「更多」默认收起');
  assert.ok(root.querySelector('.lb-other-ai-body').classList.contains('is-collapsed'), '「其他 AI 能力」默认收起');
  const row = n => rowsOf(root).find(r => nameOf(r) === n);
  assert.match(row('文本 AI').querySelector('.setting-item-description').textContent, /^问收藏页的回答用它。没配时问答用不了；归档、浏览、关键词搜索不受影响。/);
  assert.equal(row('每天最多新抓').querySelector('.setting-item-description').textContent, '防风控；第一次补历史收藏会分几天完成。默认 50，清空就回到 50；填 0 = 不限（一次抓太多容易触发风控）。');
  assert.deepEqual(row('收藏同步').querySelectorAll('button').map(b => b.textContent), ['定时…', '立即同步'], '定时… / 立即同步 照旧');
  assert.ok(!rowsOf(root).some(r => nameOf(r) === '搜索收藏'), '「搜索收藏 · 打开目录」删掉了');

  // —— 2. 展开 / 收起记在插件对象上（本次会话），不写 data.json ——
  const savesBefore = env.saves.length;
  expandAll(tab);
  assert.ok(!root.querySelector('.lb-other-ai-body').classList.contains('is-collapsed'));
  assert.equal(row('其他 AI 能力').querySelector('button').textContent, '收起');
  tab.display(); root = tab.containerEl;   // 重开设置页
  assert.equal(root.querySelector('details.lb-more').open, true, '重开设置页「更多」保持展开');
  assert.ok(!root.querySelector('.lb-other-ai-body').classList.contains('is-collapsed'), '重开设置页「其他 AI 能力」保持展开');
  const more = root.querySelector('details.lb-more'); more.open = false; more.fire('toggle');
  root.querySelector('.lb-other-ai').querySelector('button').click();
  tab.display(); root = tab.containerEl;
  assert.equal(!!root.querySelector('details.lb-more').open, false, '收起也记住');
  assert.ok(root.querySelector('.lb-other-ai-body').classList.contains('is-collapsed'));
  assert.equal(env.saves.length, savesBefore, '展开 / 收起不写 data.json');
  assert.ok(!('settingsView' in env.p.settings) && !JSON.stringify(env.p.settings).includes('otherAI'), '状态不进 settings');

  // —— 3. 全部展开后一项不少 ——
  for (const [k, cfg] of Object.entries(CONFIGS)) {
    const { p } = makePlugin(cfg); const t = openTab(p); expandAll(t); await flush();
    const now = inventory(t.containerEl);
    const count = a => a.reduce((m, x) => m.set(x, (m.get(x) || 0) + 1), new Map());
    const had = count(BASELINE[k]), has = count(now);
    const missing = [...had].filter(([x, n]) => !REMOVED.includes(x) && (has.get(x) || 0) < n).map(([x, n]) => `${x} ×${n - (has.get(x) || 0)}`);
    assert.deepEqual(missing, [], `配置 ${k}：展开后少了这些设置项`);
    for (const x of REMOVED) assert.ok(!now.includes(x));
    // 展开后都看得见
    const hiddenRows = rowsOf(t.containerEl).filter(r => !visible(r, t.containerEl)).map(idOf);
    assert.deepEqual(hiddenRows, [], `配置 ${k}：全部展开后不该还有藏着的行`);
  }
  // 「更多」里的块顺序
  ({ p: env.p } = makePlugin({})); tab = openTab(env.p); root = tab.containerEl;
  const moreHeads = root.querySelector('details.lb-more').querySelectorAll('h4').map(h => h.textContent);
  assert.deepEqual(moreHeads, ['收藏同步细项', '问答模型', '外接 MCP', '电脑需求', '下载', '运行环境', '文字识别（OCR）', '提示词', '问答用量', '目录大类', '附件', '远程阅读（MCP）']);
  // 「其他 AI 能力」展开块里是这些能力的完整设置
  const otherNames = rowsOf(root.querySelector('.lb-other-ai-body')).map(idOf);
  for (const n of ['归档摘要模型（默认同文本 AI）', '测试归档摘要', '识图接口', '精细识别模型', '测试识图', '视频画面文字', '语音识别', '端口', '测试语音识别', 'CapsLock 语音输入', 'CapsWriter 目录'])
    assert.ok(otherNames.includes(n), `其他 AI 能力里缺「${n}」`);

  // —— 4. 摘要随设置变化 ——
  const summaryOf = r => rowsOf(r).find(x => nameOf(x) === '其他 AI 能力').querySelector('.setting-item-description').textContent;
  env = makePlugin({ visionAI: { mode: 'off' } }); tab = openTab(env.p);
  assert.equal(summaryOf(tab.containerEl), '归档摘要：和文本 AI 相同 · 识图：未开启 · 语音识别：本机 CapsWriter');
  env = makePlugin({ summaryAI: { mode: 'off' }, visionAI: { mode: 'http', endpoint: 'https://v.example.com/v1/chat/completions', model: 'vl-model' }, asrAI: { mode: 'http', model: 'whisper-1' } });
  tab = openTab(env.p);
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
  const syncDesc = async (files) => { const e = makePlugin({}, files); const t = openTab(e.p); await flush(); await flush();
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

  // —— 6. 第 5 批 4.5：设置页开着时监听两份同步文件，变了重画那一行；hide() / 重画整页时注销 ——
  {
    const e = makePlugin({}, { '_archive/sync-status.json': JSON.stringify({ state: 'ready', message: '收藏同步完成', updated_at: '2026-10-02T04:20:00' }) });
    const handlers = []; let offs = 0;
    e.p.app.vault.on = (ev, cb) => { const ref = { ev, cb, live: true }; handlers.push(ref); return ref; };
    e.p.app.vault.offref = ref => { ref.live = false; offs++; };
    const t = openTab(e.p); await flush(); await flush();
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
    t.hide();
    assert.equal(offs, 4, '关设置页注销'); assert.equal(handlers.filter(h => h.live).length, 0);
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
    const e = makePlugin({}); const t = openTab(e.p);
    const input = rowsOf(t.containerEl).find(x => nameOf(x) === '每天最多新抓').querySelector('input');
    assert.equal(input.value, '50');
    input.value = ''; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 50, '清空回落 50');
    input.value = '0'; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 0, '0 = 不限，照存');
    input.value = '120'; await input.oninput(); assert.equal(e.p.settings.sync.dailyNewLimit, 120);
    expandAll(t);
    const floors = rowsOf(t.containerEl).find(x => nameOf(x) === '评论 · 自动拉取');
    assert.match(floors.querySelector('.setting-item-description').textContent, /默认前 10 楼/);
    assert.ok(!/默认全部/.test(floors.querySelector('.setting-item-description').textContent), '说明和下拉的默认一致');
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

  console.log('PASS settings layout: first layer 10 rows, 更多 + 其他 AI 能力 collapsed by default and remembered per session, nothing lost vs pre-change inventory, AI summary live, sync line from summary; batch5: sync row live-watched + unhooked on hide, daily limit 50/0=unlimited, schedule status honest');
})().catch(e => { console.error(e); process.exitCode = 1; });

// 第 1B 批：设置页 AI——每个能力块下只有一个「测试」按钮，调的是 selftest <能力>；方式下拉里没有 media；
// 旧的 media 配置只如实说一句（不在界面里偷偷改写，改了那一格才存成新格式）。
// 1010 她：设置页分栏、按新手重写——「AI」那一栏：问收藏 / 识图的接口 · 密钥 · 模型 + 测试；「高级」：写概要用的模型、认字、语音转文字的细项 + 测试；
// 测试按钮把后果写在按钮字上（要花钱的写「几乎不花钱」，本机的写「本机跑，不花钱」）；子选项只在父开关打开后出现。
// 不起真进程：runPy 是替身（CONVENTIONS §7.5）。
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');

const notices = [];
const settings = [];   // 每个 new Setting(...) 的记录
class FakeEl {
  constructor(tag = 'div', opts = {}) { this.tag = tag; this.text = opts.text || ''; this.children = []; this.style = {}; this.classList = { toggle() {}, add() {} }; this.attrs = {}; }
  createEl(tag, opts = {}) { const el = new FakeEl(tag, opts); this.children.push(el); return el; }
  createDiv(opts = {}) { return this.createEl('div', opts); }
  createSpan(opts = {}) { return this.createEl('span', opts); }
  empty() { this.children = []; }
  addClass() {}
  toggleClass() {}
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
  querySelector() { return this.children.find(child => child.tag === 'input') || null; }
  setText(t) { this.text = t; }
  remove() {}
  allText() { return [this.text, ...this.children.map(c => c.allText())].join('\n'); }
}
class FakeSetting {
  constructor(container) { this.container = container; this.rec = { name: '', desc: '', dropdown: null, buttons: [], texts: [], toggle: null };
    settings.push(this.rec); this.settingEl = container.createDiv(); this.nameEl = new FakeEl(); this.controlEl = new FakeEl(); this.descEl = new FakeEl(); }
  setName(n) { this.rec.name = n; return this; }
  setDesc(d) { this.rec.desc = d; return this; }
  addDropdown(cb) {
    const dd = { options: [], value: null, onChangeCb: null,
      addOption(v, l) { this.options.push([v, l]); return this; }, setValue(v) { this.value = v; return this; },
      onChange(f) { this.onChangeCb = f; return this; } };
    this.rec.dropdown = dd; cb(dd); return this;
  }
  addText(cb) { const t = { inputEl: this.controlEl.createEl('input'), value: '', setPlaceholder(p) { this.placeholder = p; return this; },
    setValue(v) { this.value = v; this.inputEl.value = v; return this; }, onChange(f) { this.cb = f; return this; } }; this.rec.texts.push(t); cb(t); return this; }
  addTextArea(cb) { return this.addText(cb); }
  addToggle(cb) { const t = { value: null, setValue(v) { this.value = v; return this; }, onChange(f) { this.cb = f; return this; } }; this.rec.toggle = t; cb(t); return this; }
  addButton(cb) { const b = { label: '', onClickCb: null, setButtonText(l) { this.label = this.label || l; return this; },
    setDisabled() { return this; }, setCta() { return this; }, setWarning() { return this; }, onClick(f) { this.onClickCb = f; return this; } };
    this.rec.buttons.push(b); cb(b); return this; }
  addExtraButton(cb) { const b = { setIcon() { return this; }, setTooltip() { return this; }, onClick() { return this; } }; cb(b); return this; }
  then(cb) { cb(this); return this; }
}

const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, URL, console,
  require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class { constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = new FakeEl(); } },
    Modal: class {}, Setting: FakeSetting, Notice: class { constructor(m) { notices.push(m); } } }
    : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8')
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;

// 1027：设置页④「更多」——「接口与密钥」（先选一项：问答 → AI 识图 → 概要，一项一项画）+「识别细项」；画的就是设置页上那几个函数
function render(saved, caps = ['ask', 'vision', 'summary']) {
  settings.length = 0;
  const calls = [];
  const OBS = context.require('obsidian');
  const plugin = { app: { workspace: { getActiveFile: () => null, trigger() {} } }, mcpArgv: () => ['python', '-m', 'link_brain', 'mcp'], testMcp: async () => { calls.push(['mcp']); return { json: plugin.reply }; }, settings: Plugin.__merge(saved), saveSettings: async () => {}, renderAccounts() {}, renderSyncRow() {},
    capsWriterDir: () => null, onboardingUI: () => ({ renderFolder: () => null }), runPy: async (args) => { calls.push(args); return { json: plugin.reply, err: '' }; }, notify: m => notices.push(m),
    failBox: (c, what, e) => c.createEl('p', { text: (what || '') + '这一块暂时读不到：' + e.message }) };
  plugin.homeUI = () => ({ featureToggle: row => row.addToggle(t => t.setValue(false)), state: () => ({ plan: {} }), isOn: () => false, setFeature: async () => {} });
  plugin.settingsPages = () => require(require('path').resolve('obsidian-plugins/link-brain-actions/settings-pages.js'))(OBS, plugin);
  const v6 = require(require('path').resolve('obsidian-plugins/link-brain-actions/settings-v6.js'))(OBS, plugin);
  const tab = new Plugin.__SettingTab({}, plugin);
  plugin.settingsView = { tab: 'ai' }; tab.stops = [];
  const box = tab.containerEl;
  const api = v6._parts.apiConfig(box, tab, Promise.resolve(null));
  let text = box.allText() + '\n';
  for (const cap of caps.slice(1)) { api.lbPick(cap); text += box.allText() + '\n'; }
  if (caps[0] !== 'ask') api.lbPick(caps[0]);
  v6._parts.recogRows(box, tab);
  text += box.allText() + '\n';
  return { tab, plugin, calls, text, api };
}
const ALL_ON = { setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'asr', 'ai_text', 'ai_vision'], aiSynced: true } };

(async () => {
  // —— 新装（没有 data.json，功能都打开）——
  let { plugin, calls, text } = render(ALL_ON);
  const byName = n => settings.find(r => r.name === n);
  // 接口 · 密钥 · 模型名；「配置哪一项」先选一项（问答 / 概要 / AI 识图 / 精细识图 / 语音转文字（在线）/ 按意思搜）
  for (const n of ['接口地址', '密钥（API Key）', '模型名']) assert.ok(byName(n), `缺「${n}」`);
  assert.deepEqual(byName('配置哪一项').dropdown.options.map(o => o[0]), ['ask', 'summary', 'vision', 'refine', 'asr', 'embed']);
  assert.ok(!byName('识图接口') && !byName('语音识别') && !byName('视频转文字改用在线接口') && !byName('写概要用的模型'), '旧的方式下拉 / 开关没了（④ 主界面每项一个下拉）');
  assert.ok(byName('只换模型名'), '概要跟随问答：只换模型名');
  assert.ok(!byName('用哪个命令行'), '没选命令行时不出命令行下拉');
  assert.ok(!/旧版「本机千问配置」/.test(text), '新装不显示旧配置说明');
  // 概要「单独配置」：接口 / 本机命令行两样（没有 media、没有「不写」——关在④主界面的下拉里）
  render({ ...ALL_ON, summaryAI: { mode: 'http' } }, ['summary']);
  const sum = settings.find(r => r.name === '单独配置用什么');
  assert.deepEqual(sum.dropdown.options.map(o => o[0]), ['http', 'cli']);
  ({ plugin, calls, text } = render(ALL_ON));

  // 每个能力块下一个测试按钮，调 selftest <能力>；后果写在按钮字上
  const tests = settings.flatMap(r => r.buttons).filter(b => /^测试/.test(b.label));
  assert.deepEqual(tests.map(b => b.label), ['测试（发一句话，几乎不花钱）', '测试识图（发一张小图，几乎不花钱）', '测试概要模型（发一段短文，几乎不花钱）',
    '测试认字（本机跑，不花钱）', '测试语音转文字（本机跑，不花钱）'], '「接口与密钥」逐项的在前，「识别细项」两个在后');
  for (const b of tests) await b.onClickCb();
  assert.deepEqual(calls.map(a => a.at(-1)), ['text', 'vision', 'summary', 'ocr', 'asr']);
  assert.ok(calls.every(a => a[2] === 'selftest'));

  // 没配 = 「还没打开：原因」，不是「没通过」
  notices.length = 0;
  plugin.reply = { kind: 'summary', ok: false, skipped: true, detail: '问收藏那一格没填接口地址' };
  await tests[2].onClickCb();
  assert.match(plugin.settingsView.tests.summary.text, /^还没打开/);
  plugin.reply = { kind: 'vision', ok: false, skipped: false, code: 'NEEDS_HUMAN.AUTH_FAILED', detail: '接口拒绝了 key（HTTP 401）' };
  await tests[1].onClickCb();
  assert.match(plugin.settingsView.tests.vision.text, /^✗ 没通过.*401/);

  // CapsWriter 装在哪：提示里不带任何本机盘位
  const capsDir = byName('CapsWriter 装在哪');
  assert.ok(capsDir && !/\\AI\\/.test(capsDir.texts[0].placeholder));


  // —— 1023：概要选「本机命令行」→ 下拉列后端 AI 配置表里的命令行（含 OpenCode），选中只存 preset ——
  let tab;
  let api;
  ({ plugin, calls, tab, api } = render({ ...ALL_ON, summaryAI: { mode: 'cli', preset: 'claude' } }, ['summary']));
  plugin.reply = { ok: true, ai_table: { caps: {}, cli: [{ id: 'codex', name: 'Codex', preset: 'codex', command: 'codex exec -' },
    { id: 'claude', name: 'Claude Code', preset: 'claude', command: 'claude -p' }, { id: 'opencode', name: 'OpenCode', preset: 'opencode', command: 'opencode run --pure' }] } };
  plugin.aiTableCache = null;
  api.lbPick('summary');   // 表到了再画一遍（render 时还没给替身回包）
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  const pickRow = [...settings].reverse().find(r => r.name === '用哪个命令行' && r.dropdown);
  assert.ok(pickRow, '概要选了命令行：出命令行下拉');
  assert.ok(calls.some(a => a.join(' ').includes('usage --table')), '命令行列表从后端表读');
  assert.deepEqual(pickRow.dropdown.options.map(o => o[0]), ['', 'codex', 'claude', 'opencode']);
  assert.equal(pickRow.dropdown.value, 'claude');
  await pickRow.dropdown.onChangeCb('opencode');
  assert.deepEqual([plugin.settings.summaryAI.preset, plugin.settings.summaryAI.command], ['opencode', undefined], '选中只存 preset，命令在后端');

  // —— 旧配置（作者以前那种 mode=media）：如实说一句；改了那一格才存成新格式 ——
  ({ text, plugin } = render({ ...ALL_ON, textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: '', keyFile: 'x.csv', keyField: 'ds' },
    visionAI: { mode: 'media', model: 'qwen3.8-flash' }, asrAI: { mode: 'media' }, ocr: { mode: 'media', via: 'local' } }));
  assert.match(text, /旧版「本机千问配置」/);
  assert.equal(plugin.settings.visionAI.mode, 'media', '画页面不改写');
  const visionModel = settings.filter(r => r.name === '模型名')[1];
  await visionModel.texts[0].cb('qwen3.8-flash');
  assert.equal(plugin.settings.visionAI.mode, 'http', '改了识图那一格 → 存成新格式');
  console.log('PASS AI settings (1027 ④ 更多 → 接口与密钥 / 识别细项): one test button per capability → selftest <cap> (consequence in the label); one capability at a time; summary custom = 接口 / 命令行 (no media); skipped shows 还没打开; legacy media told once, converted on edit');
})().catch(e => { console.error(e); process.exitCode = 1; });

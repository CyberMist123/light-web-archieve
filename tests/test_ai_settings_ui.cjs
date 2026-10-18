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

// 画「AI」和「高级」两栏（各画一遍，记录叠在一起）
function render(saved) {
  settings.length = 0;
  const calls = [];
  const plugin = { app: { workspace: { getActiveFile: () => null } }, mcpArgv: () => ['python', '-m', 'link_brain', 'mcp'], testMcp: async () => { calls.push(['mcp']); return { json: plugin.reply }; }, settings: Plugin.__merge(saved), saveSettings: async () => {}, renderAccounts() {}, renderSyncRow() {},
    capsWriterDir: () => null, onboardingUI: () => ({ renderFolder: () => null }), runPy: async (args) => { calls.push(args); return { json: plugin.reply, err: '' }; },
    failBox: (c, what, e) => c.createEl('p', { text: (what || '') + '这一块暂时读不到：' + e.message }) };
  // 「AI」那一栏：home-ui 打开了的两项会原地画接口那几格（这里替身直接画两块）
  plugin.homeUI = () => ({ renderStatus: () => () => {}, renderRun: () => () => {}, renderAI: (c, tab) => { tab.sectionTextAI(c, { heading: false }); tab.sectionVisionAI(c); return () => {}; } });
  plugin.remoteUI = { renderConnect: () => () => {} };
  plugin.settingsPages = () => require(require('path').resolve('obsidian-plugins/link-brain-actions/settings-pages.js'))(context.require('obsidian'), plugin);   // 1016 四个页签
  const tab = new Plugin.__SettingTab({}, plugin);
  // 1015：「AI」→「模型与提供商 → AI 功能」；原「高级」里的 AI 细项 →「识图 · 认字 · 语音」「问收藏模型」「提示词」三个子页签
  // 1018 v6：这几块在「更多 → 每项功能用哪个模型」每一项展开里（问收藏 / 识图 / 概要 / 认字 / 语音）；展开时画的就是这几个方法，这里直接画
  plugin.settingsView = { tab: 'ai' }; tab.stops = [];
  tab.renderAIFeatures(tab.containerEl); tab.renderSummaryAI(tab.containerEl); tab.renderOcrAI(tab.containerEl); tab.renderVoiceAI(tab.containerEl);
  let text = tab.containerEl.allText() + '\n';
  // 1016：AI 一页画全（接口那几块在页底「详细设置」折叠里），不再分子页签
  return { tab, plugin, calls, text };
}
const ALL_ON = { setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'asr', 'ai_text', 'ai_vision'], aiSynced: true } };

(async () => {
  // —— 新装（没有 data.json，功能都打开）——
  let { plugin, calls, text } = render(ALL_ON);
  const byName = n => settings.find(r => r.name === n);
  // 「AI」那一栏没有方式下拉了（开关在功能清单上，命令行在「高级 → 开发者」）；接口 · 密钥 · 模型名
  for (const n of ['接口地址', '密钥（API Key）', '模型名']) assert.ok(byName(n), `缺「${n}」`);
  assert.ok(!settings.some(r => r.name === '文本 AI' && r.dropdown) && !byName('识图接口') && !byName('语音识别'), '没有方式下拉了');   // 1015：「文本 AI」只剩问收藏模型勾选列表里那一行
  // 「高级」：写概要用的模型（和问收藏一样 / 另配一个接口 / 不写概要）
  const sum = byName('写概要用的模型');
  assert.ok(sum && sum.dropdown);
  assert.deepEqual(sum.dropdown.options.map(o => o[0]), ['inherit', 'http', 'off']);
  assert.equal(sum.dropdown.value, 'inherit');
  assert.ok(!sum.dropdown.options.some(o => o[0] === 'media'), '不该再有 media');
  assert.ok(byName('视频转文字改用在线接口').toggle, '在线转写是一个开关');
  assert.equal(byName('视频转文字改用在线接口').toggle.value, false, '默认本机');
  assert.ok(!/旧版「本机千问配置」/.test(text), '新装不显示旧配置说明');

  // 每个能力块下一个测试按钮，调 selftest <能力>；后果写在按钮字上
  const tests = settings.flatMap(r => r.buttons).filter(b => /^测试/.test(b.label));
  assert.deepEqual(tests.map(b => b.label), ['测试（发一句话，几乎不花钱）', '测试识图（发一张小图，几乎不花钱）', '测试概要模型（发一段短文，几乎不花钱）',
    '测试认字（本机跑，不花钱）', '测试语音转文字（本机跑，不花钱）'], '「AI 功能」里的两块在前，其余在「识图 · 认字 · 语音」');
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

  // （1018 起这些细项只在用户点开「更多 → 每项功能用哪个模型」里那一项时才画，不再按父开关藏；开关本身在「识别与问答」卡上，见 test_settings_layout）

  // —— 旧配置（作者以前那种 mode=media）：如实说一句；改了那一格才存成新格式 ——
  ({ text, plugin } = render({ ...ALL_ON, textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: '', keyFile: 'x.csv', keyField: 'ds' },
    visionAI: { mode: 'media', model: 'qwen3.8-flash' }, asrAI: { mode: 'media' }, ocr: { mode: 'media', via: 'local' } }));
  assert.match(text, /旧版「本机千问配置」/);
  assert.equal(plugin.settings.visionAI.mode, 'media', '画页面不改写');
  const visionModel = settings.filter(r => r.name === '模型名')[1];
  await visionModel.texts[0].cb('qwen3.8-flash');
  assert.equal(plugin.settings.visionAI.mode, 'http', '改了识图那一格 → 存成新格式');
  console.log('PASS AI settings (capability blocks under 更多 → 每项功能用哪个模型): one test button per capability → selftest <cap> (consequence in the label); no mode dropdowns for the newbie, summary model select without media; skipped shows 还没打开; legacy media told once, converted on edit');
})().catch(e => { console.error(e); process.exitCode = 1; });

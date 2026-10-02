// 第 1B 批：设置页 AI 区——每个能力块下只有一个「测试」按钮，调的是 selftest <能力>；mode 下拉里没有 media；
// 旧的 media 配置只读显示（加一个「旧版本机配置（已自动换算）」选项 + 一句说明），不在界面里偷偷改写。
// 不起真进程：runPy 是替身（CONVENTIONS §7.5）。
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');

const notices = [];
const settings = [];   // 每个 new Setting(...) 的记录
class FakeEl {
  constructor(tag = 'div', opts = {}) { this.tag = tag; this.text = opts.text || ''; this.children = []; this.style = {}; }
  createEl(tag, opts = {}) { const el = new FakeEl(tag, opts); this.children.push(el); return el; }
  createDiv(opts = {}) { return this.createEl('div', opts); }
  createSpan(opts = {}) { return this.createEl('span', opts); }
  empty() { this.children = []; }
  addClass() {}
  toggleClass() {}
  addEventListener() {}
  setText(t) { this.text = t; }
  remove() {}
  allText() { return [this.text, ...this.children.map(c => c.allText())].join('\n'); }
}
class FakeSetting {
  constructor(container) { this.container = container; this.rec = { name: '', desc: '', dropdown: null, buttons: [], texts: [] };
    settings.push(this.rec); this.controlEl = new FakeEl(); }
  setName(n) { this.rec.name = n; return this; }
  setDesc(d) { this.rec.desc = d; return this; }
  addDropdown(cb) {
    const dd = { options: [], value: null, onChangeCb: null,
      addOption(v, l) { this.options.push([v, l]); return this; }, setValue(v) { this.value = v; return this; },
      onChange(f) { this.onChangeCb = f; return this; } };
    this.rec.dropdown = dd; cb(dd); return this;
  }
  addText(cb) { const t = { inputEl: { style: {} }, value: '', setPlaceholder(p) { this.placeholder = p; return this; },
    setValue(v) { this.value = v; return this; }, onChange(f) { this.cb = f; return this; } }; this.rec.texts.push(t); cb(t); return this; }
  addTextArea(cb) { return this.addText(cb); }
  addToggle(cb) { const t = { setValue() { return this; }, onChange() { return this; } }; cb(t); return this; }
  addButton(cb) { const b = { label: '', onClickCb: null, setButtonText(l) { this.label = this.label || l; return this; },
    setDisabled() { return this; }, setCta() { return this; }, onClick(f) { this.onClickCb = f; return this; } };
    this.rec.buttons.push(b); cb(b); return this; }
  addExtraButton(cb) { const b = { setIcon() { return this; }, setTooltip() { return this; }, onClick() { return this; } }; cb(b); return this; }
  then(cb) { cb(this); return this; }
}

const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console,
  require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class { constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = new FakeEl(); } },
    Modal: class {}, Setting: FakeSetting, Notice: class { constructor(m) { notices.push(m); } } }
    : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8')
  + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;

function render(saved) {
  settings.length = 0;
  const calls = [];
  const plugin = { settings: Plugin.__merge(saved), saveSettings: async () => {}, renderAccounts() {}, renderSyncRow() {},
    capsWriterDir: () => null, runPy: async (args) => { calls.push(args); return { json: plugin.reply, err: '' }; } };
  const tab = new Plugin.__SettingTab({}, plugin);
  tab.display();
  return { tab, plugin, calls, text: tab.containerEl.allText() };
}

(async () => {
  // —— 新装（没有 data.json）——
  let { plugin, calls, text } = render({});
  const byName = n => settings.find(r => r.name === n);
  for (const [name, modes] of [['文本 AI', ['http', 'cli', 'off']], ['归档摘要模型（默认同文本 AI）', ['inherit', 'http', 'off']],
    ['识图接口', ['http', 'off']], ['语音识别', ['capswriter', 'http', 'off']], ['文字识别（OCR）', ['local', 'off']]]) {
    const rec = byName(name);
    assert.ok(rec && rec.dropdown, `缺「${name}」`);
    assert.deepEqual(rec.dropdown.options.map(o => o[0]), modes, `${name} 的方式`);
    assert.ok(!rec.dropdown.options.some(o => o[0] === 'media'), `${name} 不该再有 media`);
  }
  assert.equal(byName('语音识别').dropdown.value, 'capswriter', '语音识别默认本机 CapsWriter');
  assert.equal(byName('归档摘要模型（默认同文本 AI）').dropdown.value, 'inherit');
  assert.ok(!/收藏问答与归档摘要/.test(settings.map(r => r.desc).join('\n')), '不再写「问答与归档摘要」这种不实说法');
  assert.ok(!/旧版「本机千问配置」/.test(text), '新装不显示旧配置说明');

  // 每个能力块下一个测试按钮，调 selftest <能力>
  const tests = settings.flatMap(r => r.buttons).filter(b => /^测试/.test(b.label));
  assert.deepEqual(tests.map(b => b.label), ['测试文本 AI', '测试归档摘要', '测试识图', '测试语音识别', '测试 MCP', '测试 OCR']);
  for (const b of tests) await b.onClickCb();
  assert.deepEqual(calls.map(a => a.at(-1)), ['text', 'summary', 'vision', 'asr', 'mcp', 'ocr']);
  assert.ok(calls.every(a => a[2] === 'selftest'));

  // 没配 = 「未开启：原因」，不是「失败」
  notices.length = 0;
  plugin.reply = { kind: 'summary', ok: false, skipped: true, detail: '文本 AI没填接口地址' };
  await tests[1].onClickCb();
  assert.match(notices.at(-1), /^未开启：/);
  plugin.reply = { kind: 'vision', ok: false, skipped: false, code: 'NEEDS_HUMAN.AUTH_FAILED', detail: '接口拒绝了 key（HTTP 401）' };
  await tests[2].onClickCb();
  assert.match(notices.at(-1), /^失败：.*401/);

  // CapsWriter 目录的提示里不带任何本机盘位
  const capsDir = byName('　CapsWriter 目录');
  assert.ok(capsDir && !/\\AI\\/.test(capsDir.texts[0].placeholder));

  // —— 旧配置（作者本机那种 mode=media）：只读显示，加一个说明 ——
  ({ text } = render({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: '', keyFile: 'x.csv', keyField: 'ds' },
    visionAI: { mode: 'media', model: 'qwen3.8-flash' }, asrAI: { mode: 'media' }, ocr: { mode: 'media', via: 'local' } }));
  assert.match(text, /旧版「本机千问配置」/);
  for (const name of ['识图接口', '语音识别', '文字识别（OCR）']) {
    const rec = byName(name);
    assert.equal(rec.dropdown.value, 'media');
    assert.deepEqual(rec.dropdown.options.at(-1), ['media', '旧版本机配置（已自动换算）']);
  }
  console.log('PASS AI settings: one test button per capability → selftest <cap>; no media mode; skipped shows 未开启; legacy media shown read-only');
})().catch(e => { console.error(e); process.exitCode = 1; });

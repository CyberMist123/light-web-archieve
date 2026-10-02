// 第 6 批：设置页「远程阅读（MCP）」一节（obsidian-plugins/link-brain-actions/remote-ui.js）。
// 不起真进程（CONVENTIONS §7.5）：runPy 是替身，按子命令回预设 JSON；Obsidian 的 Setting / Modal / Notice 是假的。
// 断言：attach 把 data.json 的 remote 段挂回 settings；各控件都在；状态 / 出错原因 / 最近访问如实显示；
// 启用失败把开关退回去；加文件夹有提示；口令只走 stdin、令牌只在弹窗里出现，都不进 settings（= data.json）。
const assert = require('assert/strict');
const path = require('path');

const notices = [];
const settings = [];
const modals = [];
class FakeEl {
  constructor(tag = 'div', opts = {}) { this.tag = tag; this.text = opts.text || ''; this.attr = opts.attr || {}; this.type = opts.type; this.children = []; this.style = {}; this.classes = new Set(opts.cls ? [opts.cls] : []); this.value = ''; this.listeners = {}; }
  createEl(tag, opts = {}) { const el = new FakeEl(tag, opts); this.children.push(el); return el; }
  createDiv(opts = {}) { return this.createEl('div', opts); }
  empty() { this.children = []; }
  addClass(c) { this.classes.add(c); }
  setText(t) { this.text = t; }
  remove() { this.removed = true; }
  addEventListener(ev, f) { this.listeners[ev] = f; }
  allText() { return [this.removed ? '' : this.text, ...this.children.map(c => c.allText())].join('\n'); }
  find(pred) { if (pred(this)) return this; for (const c of this.children) { const f = c.find(pred); if (f) return f; } return null; }
}
class FakeSetting {
  constructor(container) {
    this.rec = { name: '', desc: '', buttons: [], texts: [], toggle: null, dropdown: null, extra: [] };
    settings.push(this.rec);
    this.settingEl = container.createDiv(); this.descEl = new FakeEl(); this.controlEl = new FakeEl();
    this.rec.setting = this;
  }
  setName(n) { this.rec.name = n; return this; }
  setDesc(d) { this.rec.desc = d; return this; }
  addToggle(cb) { const t = { value: null, setValue(v) { this.value = v; return this; }, onChange(f) { this.cb = f; return this; }, setDisabled() { return this; } }; this.rec.toggle = t; cb(t); return this; }
  addText(cb) { const inputEl = new FakeEl('input'); const t = { inputEl, setPlaceholder() { return this; }, setValue(v) { inputEl.value = v; return this; }, onChange(f) { this.cb = f; return this; } }; this.rec.texts.push(t); cb(t); return this; }
  addDropdown(cb) { const d = { options: [], value: null, addOption(v, l) { this.options.push([v, l]); return this; }, setValue(v) { this.value = v; return this; }, onChange(f) { this.cb = f; return this; } }; this.rec.dropdown = d; cb(d); return this; }
  addButton(cb) { const b = { label: '', disabled: false, setButtonText(l) { this.label = l; return this; }, setCta() { return this; }, setWarning() { return this; }, setDisabled(v) { this.disabled = v; return this; }, onClick(f) { this.cb = f; return this; } }; this.rec.buttons.push(b); cb(b); return this; }
  addExtraButton(cb) { const b = { setIcon() { return this; }, setTooltip(t) { this.tip = t; return this; }, onClick(f) { this.cb = f; return this; } }; this.rec.extra.push(b); cb(b); return this; }
}
class FakeModal {
  constructor(app) { this.app = app; this.contentEl = new FakeEl(); }
  open() { modals.push(this); this.opened = this.onOpen(); }
  close() { this.closed = true; this.onClose && this.onClose(); }
}
const obsidian = { Setting: FakeSetting, Modal: FakeModal, Notice: class { constructor(m) { notices.push(m); } } };
Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async (t) => { global.__clip = t; } } }, configurable: true });

const factory = require(path.resolve(__dirname, '../obsidian-plugins/link-brain-actions/remote-ui.js'));
const tick = () => new Promise(r => setTimeout(r, 0));
const byName = (n) => settings.find(r => r.name === n);

function makePlugin(saved, replies) {
  const calls = [];
  const saves = [];
  const plugin = {
    app: { vault: { adapter: { getBasePath: () => 'D:/vault' } } }, manifest: { dir: '.obsidian/plugins/link-brain-actions' }, settings: { other: 1 },
    loadData: async () => saved,
    saveSettings: async () => { saves.push(JSON.parse(JSON.stringify(plugin.settings))); },
    runPy: async (args, opts = {}) => {
      calls.push({ args, input: opts.input });
      const sub = args.slice(3).join(' ');
      const key = Object.keys(replies).find(k => sub.startsWith(k));
      const json = key ? (typeof replies[key] === 'function' ? replies[key](args, opts) : replies[key]) : null;
      return { code: json && json.ok ? 0 : 1, json, out: '', err: '' };
    },
  };
  return { plugin, calls, saves };
}

const STATUS_RUNNING = { ok: true, state: 'running', message: '运行中（127.0.0.1:18080）', warnings: ['没填域名：现在只有本机能连'],
  auth: { passphrase_set: true, passphrase_set_at: '2026-10-02T10:00:00', personal: [{ id: 'pt_1', label: 'Claude 桌面', created: '2026-10-02T10:05:00', last_used: null }],
          clients: [{ id: 'lbc_1', name: 'ChatGPT', last_used: '2026-10-02T11:00:00' }] },
  recent: [{ ts: '2026-10-02T11:00:00', client: 'ChatGPT', tool: 'read', path: 'Web/Xiaohongshu/a.md', status: 'ok' },
           { ts: '2026-10-02T11:01:00', tool: 'mcp', status: 'denied', code: 'BAD_TOKEN' }] };

(async () => {
  // —— attach：mergeSettings 会丢 remote 段，attach 把它挂回来 ——
  let { plugin } = makePlugin({ remote: { enabled: true, domain: 'https://a.example.com', port: 18080, folders: ['@xhs', '其他资料', '@xhs'] } }, {});
  const ui = factory(obsidian, plugin);
  await ui.attach();
  assert.deepEqual(plugin.settings.remote, { enabled: true, domain: 'https://a.example.com', port: 18080, folders: ['@xhs', '其他资料'] });
  ({ plugin } = makePlugin(null, {}));
  await factory(obsidian, plugin).attach();
  assert.deepEqual(plugin.settings.remote, ui.REMOTE_DEFAULTS);

  // —— 纯函数 ——
  assert.equal(ui.cleanDomain(' https://A.Example.com/ '), 'https://a.example.com');
  assert.equal(ui.cleanDomain(''), '');
  for (const bad of ['http://a.example.com', 'https://a.example.com/mcp', 'https://a.example.com:8443', 'a.example.com']) assert.equal(ui.cleanDomain(bad), null, bad);
  assert.equal(ui.accessLine(STATUS_RUNNING.recent[1]), '10-02 11:01 · 未授权 · 连接 · 拒绝（令牌无效或已撤销）');

  // —— 渲染：控件齐、状态 / 最近访问如实显示 ——
  let env = makePlugin({ remote: { enabled: true, domain: 'https://a.example.com', port: 18080, folders: ['@xhs'] } }, { status: STATUS_RUNNING });
  let r = factory(obsidian, env.plugin); await r.attach();
  settings.length = 0;
  const root = new FakeEl();
  r.render(root, () => {});
  await tick(); await tick();
  for (const n of ['状态', '启用', '域名', '端口', '口令', '连接地址', '给其他客户端的访问令牌', '撤销全部访问']) assert.ok(byName(n), '缺「' + n + '」');
  assert.equal(byName('状态').desc, '运行中（127.0.0.1:18080）');
  assert.equal(byName('连接地址').desc, 'https://a.example.com/mcp');
  assert.ok(settings.some(s => /小红书收藏库/.test(s.name)), '默认开放项要显示');
  const text = root.allText();
  assert.match(text, /⚠ 没填域名/);
  assert.match(text, /ChatGPT · 读 · Web\/Xiaohongshu\/a\.md · 成功/);
  assert.match(text, /已授权的客户端：ChatGPT/);
  assert.ok(settings.some(s => /Claude 桌面/.test(s.name)), '访问令牌列表');
  assert.equal(byName('口令').buttons[0].label, '修改口令');
  await byName('连接地址').buttons[0].cb();
  assert.equal(global.__clip, 'https://a.example.com/mcp');
  assert.ok(env.calls.every(c => c.args.slice(0, 3).join(' ') === '-m link_brain remote'));

  // —— 出错原因如实显示 ——
  env = makePlugin({ remote: { enabled: true, port: 18080 } }, { status: { ok: true, state: 'error', message: '端口 18080 被别的程序占着：到设置里换一个端口', auth: {}, recent: [] } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0;
  r.render(new FakeEl(), () => {}); await tick(); await tick();
  assert.equal(byName('状态').desc, '出错：端口 18080 被别的程序占着：到设置里换一个端口');
  assert.match(byName('连接地址').desc, /先填域名/);
  assert.ok(byName('连接地址').buttons[0].disabled);

  // —— 启用：先存开关再调 enable；注册失败 → 开关退回、提示原因 ——
  env = makePlugin({ remote: { enabled: false } }, { status: { ok: true, state: 'stopped', message: '已停', auth: {}, recent: [] },
    enable: { ok: false, code: 'PERMANENT.REMOTE_TASK_FAILED', message: '没注册上计划任务：Access is denied.', command: 'python -m link_brain remote serve' } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; notices.length = 0;
  r.render(new FakeEl(), () => {}); await tick();
  await byName('启用').toggle.cb(true);
  assert.equal(env.saves[0].remote.enabled, true, '先把开关写进 data.json，服务才读得到');
  assert.deepEqual(env.calls.find(c => c.args[3] === 'enable').args,
    ['-m', 'link_brain', 'remote', 'enable', '--settings', path.join('D:/vault', '.obsidian/plugins/link-brain-actions', 'data.json')]);
  assert.equal(env.plugin.settings.remote.enabled, false);
  assert.ok(notices.some(n => n === '没启用上：没注册上计划任务：Access is denied.'), notices.join('|'));
  // 成功
  env = makePlugin({ remote: { enabled: false } }, { status: { ok: true, state: 'stopped', message: '已停', auth: {}, recent: [] },
    enable: { ok: true, message: '已注册并启动计划任务 LinkBrainRemote' }, disable: { ok: true, message: '已停止并删除计划任务' } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; notices.length = 0;
  r.render(new FakeEl(), () => {}); await tick();
  await byName('启用').toggle.cb(true);
  assert.equal(env.plugin.settings.remote.enabled, true);
  assert.ok(notices.includes('已注册并启动计划任务 LinkBrainRemote'));
  await byName('启用').toggle.cb(false);
  assert.equal(env.plugin.settings.remote.enabled, false);
  assert.ok(notices.includes('已停止并删除计划任务'));

  // —— 域名：格式不对不保存；对的保存 ——
  const dom = byName('域名').texts[0];
  dom.inputEl.value = 'http://bad.example.com'; await dom.inputEl.listeners.change();
  assert.equal(env.plugin.settings.remote.domain, '');
  dom.inputEl.value = 'https://Read.Example.com/'; await dom.inputEl.listeners.change();
  assert.equal(env.plugin.settings.remote.domain, 'https://read.example.com');

  // —— 加文件夹：候选来自 `remote folders`，有「都能读」提示，确认后才写进设置 ——
  env = makePlugin({ remote: { enabled: true, folders: [] } }, { status: { ok: true, state: 'running', message: '运行中', auth: {}, recent: [] },
    folders: { ok: true, folders: ['Web', 'Web/Xiaohongshu', '其他资料'] } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; modals.length = 0;
  r.render(new FakeEl(), () => {}); await tick();
  await settings.find(s => s.buttons.some(b => b.label === '添加文件夹')).buttons[0].cb();
  const fm = modals.at(-1); await fm.opened;
  assert.match(fm.contentEl.allText(), /拿到授权的客户端都能读这个文件夹/);
  const dd = settings.find(s => s.dropdown && s.name === '文件夹').dropdown;
  assert.deepEqual(dd.options.map(o => o[0]), ['@xhs', 'Web', 'Web/Xiaohongshu', '其他资料']);
  dd.cb('其他资料');
  assert.deepEqual(env.plugin.settings.remote.folders, [], '没点「开放」前不改');
  await settings.find(s => s.buttons.some(b => b.label === '开放')).buttons.find(b => b.label === '开放').cb();
  assert.deepEqual(env.plugin.settings.remote.folders, ['其他资料']);

  // —— 口令：只走 stdin；settings 里永远没有口令 ——
  env = makePlugin({ remote: { enabled: true } }, { status: { ok: true, state: 'running', message: '运行中', auth: {}, recent: [] },
    passphrase: { ok: true, message: '口令已保存' } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; modals.length = 0;
  r.render(new FakeEl(), () => {}); await tick();
  await byName('口令').buttons[0].cb();
  const pm = modals.at(-1);
  const inputs = []; pm.contentEl.find(el => { if (el.tag === 'input') inputs.push(el); return false; });
  inputs[0].value = 'abc'; inputs[1].value = 'abc';
  const saveBtn = settings.at(-1).buttons.find(b => b.label === '保存口令');
  await saveBtn.cb();
  assert.ok(!env.calls.some(c => c.args.includes('passphrase')), '太短不调');
  inputs[0].value = '一个够长的口令123'; inputs[1].value = '一个够长的口令123';
  await saveBtn.cb();
  const pc = env.calls.find(c => c.args.includes('passphrase'));
  assert.deepEqual(pc.args, ['-m', 'link_brain', 'remote', 'passphrase']);
  assert.equal(JSON.parse(pc.input).passphrase, '一个够长的口令123');
  assert.ok(!JSON.stringify(env.plugin.settings).includes('一个够长的口令'));
  assert.ok(!env.saves.some(sv => JSON.stringify(sv).includes('一个够长的口令')));

  // —— 令牌：生成后只在弹窗里出现；撤销全部要确认 ——
  env = makePlugin({ remote: { enabled: true } }, { status: { ok: true, state: 'running', message: '运行中', auth: {}, recent: [] },
    'token new': { ok: true, id: 'pt_9', label: '桌面', token: 'lbr_p_SECRET', message: '已生成' }, 'revoke-all': { ok: true, message: '已撤销全部访问：1 个 OAuth 客户端、0 个访问令牌' } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; modals.length = 0; notices.length = 0;
  r.render(new FakeEl(), () => {}); await tick();
  const tok = byName('给其他客户端的访问令牌');
  tok.texts[0].cb('桌面');
  await tok.buttons[0].cb();
  assert.deepEqual(env.calls.find(c => c.args[3] === 'token').args.slice(3), ['token', 'new', '--label', '桌面']);
  assert.match(modals.at(-1).contentEl.allText(), /lbr_p_SECRET/);
  assert.ok(!JSON.stringify(env.plugin.settings).includes('lbr_p_SECRET'));
  await byName('撤销全部访问').buttons[0].cb();
  assert.ok(!env.calls.some(c => c.args[3] === 'revoke-all'), '要先确认');
  await settings.at(-1).buttons.find(b => b.label === '撤销全部').cb();
  assert.ok(env.calls.some(c => c.args[3] === 'revoke-all'));
  assert.ok(notices.includes('已撤销全部访问：1 个 OAuth 客户端、0 个访问令牌'));

  console.log('ok remote-ui');
})().catch(e => { console.error(e); process.exit(1); });

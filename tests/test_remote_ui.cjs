// 1009 设置页「连接 AI」+「高级 → 远程服务」；1010 她：设置页分栏后是「连接其他 AI」一整栏，远程访问的东西都在这一栏（高级在最下面一个折叠里）。
// 不起真进程（CONVENTIONS §7.5）：runPy 是替身，按子命令回预设 JSON；Obsidian 的 Setting / Modal / Notice / FuzzySuggestModal 是假的。
// 断言：attach 把 data.json 的 remote 段挂回 settings；勾了哪个客户端就出哪一步（本机一键写配置 / 撤销；网页一屏给全）；
// 远程服务开关先存再 enable、注册失败退回；域名格式不对不存；口令只走 stdin、令牌只在弹窗里出现，都不进 settings（= data.json）；
// 开放文件夹两个入口并排（从库内选 = FuzzySuggestModal；选本机 = pick-folder），库外的先问后端能不能开放。
const assert = require('assert/strict');
const path = require('path');

const notices = [];
const settings = [];
const modals = [];
class FakeEl {
  constructor(tag = 'div', opts = {}) { this.tag = tag; this.text = opts.text || ''; this.attr = opts.attr || {}; this.type = opts.type; this.children = []; this.style = {}; this.classes = new Set(opts.cls ? [opts.cls] : []); this.value = ''; this.listeners = {}; }
  createEl(tag, opts = {}) { const el = new FakeEl(tag, opts); this.children.push(el); return el; }
  createDiv(opts = {}) { return this.createEl('div', opts); }
  createSpan(opts = {}) { return this.createEl('span', opts); }
  empty() { this.children = []; }
  addClass(c) { this.classes.add(c); }
  setText(t) { this.text = t; }
  setAttribute(k, v) { this.attr[k] = v; }
  remove() { this.removed = true; }
  focus() { this.focused = true; }
  addEventListener(ev, f) { this.listeners[ev] = f; }
  allText() { return [this.removed ? '' : this.text, ...this.children.map(c => c.allText())].join('\n'); }
  find(pred) { if (pred(this)) return this; for (const c of this.children) { const f = c.find(pred); if (f) return f; } return null; }
  findAll(pred, out = []) { if (pred(this)) out.push(this); for (const c of this.children) c.findAll(pred, out); return out; }
}
class FakeSetting {
  constructor(container) {
    this.rec = { name: '', desc: '', buttons: [], texts: [], toggle: null, dropdown: null, extra: [] };
    settings.push(this.rec);
    this.settingEl = container.createDiv(); this.descEl = this.settingEl.createDiv(); this.controlEl = new FakeEl();
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
  open() { modals.push(this); this.opened = this.onOpen && this.onOpen(); }
  close() { this.closed = true; this.onClose && this.onClose(); }
}
let fuzzyPick = null;   // 「从库内选…」弹窗里她选哪一个
class FakeFuzzy extends FakeModal {
  setPlaceholder(p) { this.placeholder = p; }
  open() { modals.push(this); this.items = this.getItems(); const hit = this.items.find(i => this.getItemText(i) === fuzzyPick); if (hit) this.onChooseItem(hit); this.onClose(); }
}
class FakeFolder { constructor(p) { this.path = p; this.children = []; } }
const obsidian = { Setting: FakeSetting, Modal: FakeModal, FuzzySuggestModal: FakeFuzzy, TFolder: FakeFolder, Notice: class { constructor(m) { notices.push(m); } } };
Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async (t) => { global.__clip = t; } } }, configurable: true });

const factory = require(path.resolve(__dirname, '../obsidian-plugins/link-brain-actions/remote-ui.js'));
const tick = async (n = 4) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };
const byName = (n) => settings.findLast ? settings.findLast(r => r.name === n) : [...settings].reverse().find(r => r.name === n);

function makePlugin(saved, replies, extra = {}) {
  const calls = [];
  const saves = [];
  const plugin = {
    confirm: async options => { plugin.confirmOptions = options; return plugin.confirmed === true; },
    notify: (m) => notices.push(m),
    app: { vault: { adapter: { getBasePath: () => 'D:/vault' }, getAllLoadedFiles: () => [new FakeFolder('Web'), new FakeFolder('Web/Xiaohongshu'), new FakeFolder('其他资料'), new FakeFolder('.obsidian'), new FakeFolder('_archive')] } },
    manifest: { dir: '.obsidian/plugins/link-brain-actions' }, settings: { other: 1, connect: { clients: null }, ...extra },
    lbRoot: '',
    loadData: async () => (saves.length ? JSON.parse(JSON.stringify(saves[saves.length - 1])) : saved),   // 磁盘 = 最后一次保存的
    saveSettings: async () => { saves.push(JSON.parse(JSON.stringify(plugin.settings))); },
    runPy: async (args, opts = {}) => {
      calls.push({ args, input: opts.input });
      const sub = args.slice(2).join(' ');
      const key = Object.keys(replies).find(k => sub.startsWith(k));
      const json = key ? (typeof replies[key] === 'function' ? replies[key](args, opts) : replies[key]) : null;
      return { code: json && json.ok ? 0 : 1, json, out: '', err: '' };
    },
  };
  return { plugin, calls, saves };
}

const STATUS_RUNNING = { ok: true, state: 'running', message: '运行中（127.0.0.1:18080）', warnings: ['还没填网址：现在只有这台电脑自己能连'],
  auth: { passphrase_set: true, passphrase_copyable: true, passphrase_set_at: '2026-10-02T10:00:00', personal: [{ id: 'pt_1', label: 'Claude 桌面', created: '2026-10-02T10:05:00', last_used: null }],
          clients: [{ id: 'lbc_1', name: 'ChatGPT', connected_at: '2026-10-02T10:30:00', last_used: '2026-10-02T11:00:00' }] },
  recent: [{ ts: '2026-10-02T11:00:00', client: 'ChatGPT', tool: 'read', path: 'Web/Xiaohongshu/a.md', status: 'ok' },
           { ts: '2026-10-02T11:01:00', tool: 'mcp', status: 'denied', code: 'BAD_TOKEN' }] };
const LOCAL = { ok: true, clients: { 'claude-code': { installed: true, connected: false, command: 'claude mcp add lwa -s user -- python -m link_brain mcp' },
  'claude-desktop': { installed: true, connected: true } }, json: '{"mcpServers":{"lwa":{}}}' };

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
  for (const bad of ['http://a.example.com', 'https://a.example.com/mcp', 'https://a.example.com:8443', 'a.example.com']) assert.equal(ui.cleanDomain(bad), null, bad);
  assert.equal(ui.accessLine(STATUS_RUNNING.recent[1]), '10-02 11:01 · 未授权 · 连接 · 拒绝（令牌无效或已撤销）');
  assert.deepEqual(ui.chosenClients({ remote: { enabled: true } }), ['claude-ai', 'chatgpt'], '没勾过 + 远程开着 → 先勾网页那两个');
  assert.deepEqual(ui.chosenClients({ remote: { enabled: false } }), []);
  assert.deepEqual(ui.chosenClients({ connect: { clients: ['claude-code', 'nope'] } }), ['claude-code']);
  assert.equal(ui.vaultRelative('Web/Xiaohongshu', ''), 'Web/Xiaohongshu');
  assert.equal(ui.vaultRelative('收藏/读书', '收藏'), '读书');
  assert.equal(ui.vaultRelative('别处/读书', '收藏'), null);

  // —— 连接 AI：勾了什么就出什么；本机一键接上 / 撤销；网页一屏给全 ——
  let env = makePlugin({ remote: { enabled: true, domain: 'https://a.example.com', port: 18080, folders: ['@xhs'] } },
    { 'remote status': STATUS_RUNNING, 'connect status': LOCAL, 'connect add': { ok: true, changed: true, message: '已接到 Claude Code（用户级，所有项目都能用）' },
      'connect remove': { ok: true, changed: true, message: '已从 Claude Desktop 撤掉 lwa' } },
    { connect: { clients: ['claude-code', 'claude-desktop', 'claude-ai'] } });
  let r = factory(obsidian, env.plugin); await r.attach();
  settings.length = 0; notices.length = 0;
  let root = new FakeEl();
  r.renderConnect(root, () => {});
  await tick(8);
  for (const n of ['Claude Code', 'Claude Desktop', '远程访问', '你的网址', '连接地址', '口令', '再开放一个文件夹']) assert.ok(byName(n), '缺「' + n + '」');
  assert.ok(!byName('其他 AI 软件'), '没勾的不出');
  assert.match(root.allText(), /claude\.ai（网页 \/ 手机 App）：设置 → Connectors/);
  assert.ok(!/ChatGPT：设置/.test(root.allText()), '没勾 ChatGPT 不出它的步骤');
  assert.equal(byName('远程访问').desc, '● 开着：运行中（127.0.0.1:18080）');
  assert.ok(!/OAuth/.test(root.allText()), '界面上没有 OAuth 这个词');
  assert.match(root.allText(), /还没有网址？/); assert.match(root.allText(), /Cloudflare/); assert.match(root.allText(), /Tailscale/);
  assert.equal(byName('连接地址').desc, 'https://a.example.com/mcp');
  await byName('连接地址').buttons[0].cb();
  assert.equal(global.__clip, 'https://a.example.com/mcp');
  assert.match(root.allText(), /已经连上的网页版/);
  // Claude Code：一键接上 = connect add claude-code（结果带「撤销」）
  const cc = byName('Claude Code');
  assert.equal(cc.buttons[0].label, '一键接上');
  await cc.buttons[0].cb(); await tick(4);
  assert.deepEqual(env.calls.find(c => c.args[2] === 'connect' && c.args[3] === 'add').args, ['-m', 'link_brain', 'connect', 'add', 'claude-code']);
  assert.ok(notices.includes('已接到 Claude Code（用户级，所有项目都能用）'));
  // Claude Desktop 已接上：按钮是「撤销」= connect remove claude-desktop
  const cd = byName('Claude Desktop');
  assert.equal(cd.buttons[0].label, '撤销');
  await cd.buttons[0].cb(); await tick(4);
  assert.deepEqual(env.calls.find(c => c.args[3] === 'remove').args, ['-m', 'link_brain', 'connect', 'remove', 'claude-desktop']);
  assert.ok(notices.includes('已从 Claude Desktop 撤掉 lwa'));
  // 勾 / 取消客户端存在 settings.connect（插件设置），不进 remote 段
  const chip = root.find(el => el.tag === 'label' && el.attr['data-client'] === 'other');
  const box = chip.children.find(c => c.tag === 'input');
  box.checked = true; await box.onchange(); await tick(6);
  assert.deepEqual(env.plugin.settings.connect.clients, ['claude-code', 'claude-desktop', 'claude-ai', 'other']);
  assert.ok(byName('其他 AI 软件'), '勾上「其他」就出复制设置（JSON）');

  // —— 远程服务开关：先存开关再调 enable；注册失败 → 开关退回、提示原因 ——
  env = makePlugin({ remote: { enabled: false } }, { 'remote status': { ok: true, state: 'stopped', message: '已停', auth: {}, recent: [] }, 'connect status': LOCAL,
    'remote enable': { ok: false, code: 'PERMANENT.REMOTE_TASK_FAILED', message: '没注册上计划任务：Access is denied.' } }, { connect: { clients: ['chatgpt'] } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; notices.length = 0;
  r.renderConnect(new FakeEl(), () => {}); await tick(8);
  assert.match(byName('远程访问').desc, /没开/);
  await byName('远程访问').toggle.cb(true); await tick(4);
  assert.equal(env.saves[env.saves.length - 2].remote.enabled, true, '先把开关写进 data.json，服务才读得到');
  assert.deepEqual(env.calls.find(c => c.args[3] === 'enable').args,
    ['-m', 'link_brain', 'remote', 'enable', '--settings', path.join('D:/vault', '.obsidian/plugins/link-brain-actions', 'data.json')]);
  assert.equal(env.plugin.settings.remote.enabled, false, '没注册上 → 退回去');
  assert.ok(notices.some(n => n === '没启用上：没注册上计划任务：Access is denied.'), notices.join('|'));

  // —— 域名：格式不对不保存；对的保存 ——
  env = makePlugin({ remote: { enabled: true, domain: '' } }, { 'remote status': STATUS_RUNNING, 'connect status': LOCAL }, { connect: { clients: ['claude-ai'] } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0;
  r.renderConnect(new FakeEl(), () => {}); await tick(8);
  assert.match(byName('连接地址').desc, /先填上面的网址/);
  assert.ok(byName('连接地址').buttons[0].disabled);
  const dom = byName('你的网址').texts[0];
  dom.inputEl.value = 'http://bad.example.com'; await dom.inputEl.listeners.change();
  assert.equal(env.plugin.settings.remote.domain, '');
  dom.inputEl.value = 'https://Read.Example.com/'; await dom.inputEl.listeners.change();
  assert.equal(env.plugin.settings.remote.domain, 'https://read.example.com');

  // —— 口令：只走 stdin；settings 里永远没有口令；复制 = --reveal；随机生成 = --generate ——
  env = makePlugin({ remote: { enabled: true, domain: 'https://a.example.com' } }, { 'remote status': STATUS_RUNNING, 'connect status': LOCAL,
    'remote passphrase --reveal': { ok: true, passphrase: '旧口令-ABC12345' }, 'remote passphrase': { ok: true, message: '口令已保存' } }, { connect: { clients: ['claude-ai'] } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; modals.length = 0;
  r.renderConnect(new FakeEl(), () => {}); await tick(8);
  const pass = byName('口令');
  assert.deepEqual(pass.buttons.map(b => b.label), ['复制口令', '换一个新口令（旧的作废）', '自己改一个']);
  await pass.buttons[0].cb();
  assert.equal(global.__clip, '旧口令-ABC12345');
  await pass.buttons[2].cb();
  const pm = modals.at(-1);
  const inputs = []; pm.contentEl.find(el => { if (el.tag === 'input') inputs.push(el); return false; });
  inputs[0].value = 'abc'; inputs[1].value = 'abc';
  const saveBtn = settings.at(-1).buttons.find(b => b.label === '保存口令');
  await saveBtn.cb();
  assert.ok(!env.calls.some(c => c.args[3] === 'passphrase' && c.args.length === 4), '太短不调');
  inputs[0].value = '一个够长的口令123'; inputs[1].value = '一个够长的口令123';
  await saveBtn.cb();
  const pc = env.calls.find(c => c.args[3] === 'passphrase' && c.args.length === 4);
  assert.deepEqual(pc.args, ['-m', 'link_brain', 'remote', 'passphrase']);
  assert.equal(JSON.parse(pc.input).passphrase, '一个够长的口令123');
  assert.ok(!JSON.stringify(env.plugin.settings).includes('一个够长的口令'));
  assert.ok(!env.saves.some(sv => JSON.stringify(sv).includes('一个够长的口令')));

  // —— 开放文件夹：从库内选（FuzzySuggestModal，只列收藏库里的、不列隐藏 / _archive）；选本机（pick-folder → 先问能不能开放）——
  env = makePlugin({ remote: { enabled: true, folders: ['@xhs'] } }, { 'remote status': STATUS_RUNNING, 'connect status': LOCAL,
    'pick-folder': { ok: true, path: 'E:\\资料\\读书', canceled: false }, 'remote folders --check': { ok: true } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; modals.length = 0; notices.length = 0;
  r.renderConnect(new FakeEl(), () => {}); await tick(8);
  const pick = byName('再开放一个文件夹');
  assert.deepEqual(pick.buttons.map(b => b.label), ['从库内选…', '选本机文件夹…', '添加']);
  fuzzyPick = 'Web/Xiaohongshu';
  await pick.buttons[0].cb(); await tick(4);
  assert.deepEqual(modals.at(-1).items.map(i => i.rel), ['Web', 'Web/Xiaohongshu', '其他资料'], '不列 .obsidian / _archive');
  assert.deepEqual(env.plugin.settings.remote.folders, ['@xhs', 'Web/Xiaohongshu']);
  await byName('再开放一个文件夹').buttons[1].cb(); await tick(4);
  assert.ok(env.calls.some(c => c.args.join(' ').startsWith('-m link_brain pick-folder')), '弹系统选文件夹对话框（Python 端）');
  assert.deepEqual(env.calls.find(c => c.args[3] === 'folders').args.slice(3), ['folders', '--check', 'E:\\资料\\读书']);
  assert.deepEqual(env.plugin.settings.remote.folders, ['@xhs', 'Web/Xiaohongshu', 'E:\\资料\\读书']);
  // 对话框弹不出来：如实说，焦点给手输框
  env.plugin.runPy = async (args) => ({ code: 1, json: args.includes('pick-folder') ? { ok: false, message: '选文件夹的对话框弹不出来（tkinter：x）：请直接粘贴路径' } : null });
  notices.length = 0;
  await byName('再开放一个文件夹').buttons[1].cb(); await tick(4);
  assert.ok(notices.some(n => /请直接粘贴路径/.test(n)));

  // —— 高级 → 远程服务：端口 / 令牌（只在弹窗里出现）/ 撤销全部要确认 / 最近访问 ——
  env = makePlugin({ remote: { enabled: true, port: 18080 } }, { 'remote status': STATUS_RUNNING,
    'remote token new': { ok: true, id: 'pt_9', label: '桌面', token: 'lbr_p_SECRET', message: '已生成' }, 'remote revoke-all': { ok: true, message: '已全部断开：1 个网页版、0 个访问令牌' } });
  r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0; modals.length = 0; notices.length = 0;
  root = new FakeEl();
  r.renderAdvanced(root); await tick(8);
  for (const n of ['远程访问的运行情况', '端口', '访问令牌（给不支持口令的软件）', '全部断开']) assert.ok(byName(n), '缺「' + n + '」');
  assert.match(root.allText(), /ChatGPT · 读 · Web\/Xiaohongshu\/a\.md · 成功/);
  assert.ok(settings.some(s => /Claude 桌面/.test(s.name)), '访问令牌列表');
  const tok = byName('访问令牌（给不支持口令的软件）');
  tok.texts[0].cb('桌面');
  await tok.buttons[0].cb();
  assert.deepEqual(env.calls.find(c => c.args[3] === 'token').args.slice(3), ['token', 'new', '--label', '桌面']);
  assert.match(modals.at(-1).contentEl.allText(), /lbr_p_SECRET/);
  assert.ok(!JSON.stringify(env.plugin.settings).includes('lbr_p_SECRET'));
  await byName('全部断开').buttons[0].cb();
  assert.ok(!env.calls.some(c => c.args[3] === 'revoke-all'), '要先确认');
  assert.equal(env.plugin.confirmOptions.ok, '全部断开');
  env.plugin.confirmed = true;
  await byName('全部断开').buttons[0].cb();
  assert.ok(env.calls.some(c => c.args[3] === 'revoke-all'));
  assert.ok(notices.includes('已全部断开：1 个网页版、0 个访问令牌'));

  // —— 读到状态后的重画（1010 审查）：正在打的网址 / 粘贴路径不丢；最下面「高级」折叠不跟着重建、不再多起一遍 remote status ——
  {
    let release; const gate = new Promise(res => { release = res; });
    env = makePlugin({ remote: { enabled: true, domain: '', folders: ['@xhs'] } }, { 'remote status': STATUS_RUNNING, 'connect status': LOCAL }, { connect: { clients: ['claude-ai'] } });
    const real = env.plugin.runPy; let statusRuns = 0;
    env.plugin.runPy = async (args, opts) => {
      if (args[3] === 'status') { if (args[2] === 'remote') statusRuns++; await gate; }   // 状态读得慢：她已经开始打字了
      return real(args, opts);
    };
    r = factory(obsidian, env.plugin); await r.attach(); settings.length = 0;
    root = new FakeEl();
    r.renderConnect(root, () => {}); await tick(8);
    assert.equal(byName('远程访问').desc, '读取中…');
    const domIn = byName('你的网址').texts[0].inputEl;
    domIn.value = 'https://half.exam'; domIn.listeners.input?.();
    const man = byName('再开放一个文件夹').texts[0].inputEl;
    man.value = 'E:/资料/读书'; man.listeners.input?.();
    const adv = root.find(el => el.tag === 'details' && [...el.classes].some(c => c.includes('lb-connect-adv')));
    adv.open = true; adv.listeners.toggle(); await tick(4);
    const runsBefore = statusRuns;
    release(); await tick(16);
    assert.equal(byName('远程访问').desc, '● 开着：运行中（127.0.0.1:18080）', '状态读回来了');
    assert.equal(byName('你的网址').texts[0].inputEl.value, 'https://half.exam', '读到状态后的重画把正在打的网址冲掉了');
    assert.equal(byName('再开放一个文件夹').texts[0].inputEl.value, 'E:/资料/读书', '粘贴到一半的路径被冲掉了');
    assert.ok(root.find(el => el === adv), '「高级」折叠被重建了（里面正在填的端口 / 令牌备注会丢）');
    assert.equal(statusRuns, runsBefore, '重画又起了一遍 remote status');
    // 存好了才清：网址保存成功后，重画显示的是存下的值
    const domIn2 = byName('你的网址').texts[0].inputEl;
    domIn2.value = 'https://read.example.com'; domIn2.listeners.input?.(); await domIn2.listeners.change(); await tick(8);
    assert.equal(byName('你的网址').texts[0].inputEl.value, 'https://read.example.com');
    assert.equal(env.plugin.settings.remote.domain, 'https://read.example.com');
  }

  console.log('ok remote-ui (1009 连接 AI → 1010「连接其他 AI」一整栏：口令为主、「还没有网址？」紧挨网址、令牌只在高级折叠、界面没有 OAuth)');
})().catch(e => { console.error(e); process.exit(1); });

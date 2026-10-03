// 第 5 批 B2：单插件交付的插件侧接线。不起真进程（CONVENTIONS §7.5）：child_process 是记账的假 spawn，runPy 按场景替身。
// 断言：
//   1. 后端选择：收藏库上一级 / 插件目录上两级是 LWA 仓库 → python -m link_brain（cwd 仓根，作者本机现状）；否则后端命令（默认 link-brain，
//      PATH 找不到时看 uv 的 ~/.local/bin）；都找不到 → missing。每次起进程都带 LINK_BRAIN_VAULT=<收藏库绝对路径>；
//   2. 找不到后端：runPy / run() 如实说「没找到后端程序：先运行 `uv tool install link-brain`」，设置页顶部有「复制安装命令」；
//   3. 首次引导：什么时候弹（走过 / 没后端 / 已有 _archive 都不弹）；四步各自的状态与跳过；读取组件发布地址没配时按钮写「发布地址还没配置（测试版）」
//      并给手动放置说明，不调 install；配了才调 `reader install`；收藏位置写进插件设置 + 后端命令模式写 ~/.link-brain/config.json；关窗 = 走过；
//   4. 定时同步任务名：LinkBrainNightly 优先 → 旧任务 → 都没有时「开启」= sync-schedule --install --at --vault，「关闭」不起进程；
//   5. Dataview 缺失 / 没开 JS：设置页顶部提示 + 目录页顶部提示，按钮打开第三方插件页（或 Dataview 设置）；
//   6. 媒体导航并进主插件：onload 载入 media-nav.js 并接管；旧插件还开着就不接管（不重复弹大图），设置页提示停用旧插件。
'use strict';
const fs = require('fs'), os = require('os'), path = require('path'), vm = require('vm'), assert = require('assert/strict');
const { EventEmitter } = require('events');
const { makeDom } = require('./_fakedom.cjs');

const ROOT = path.resolve(__dirname, '..');
const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';
const dom = makeDom();
const El = dom.document.createElement('div').constructor;
El.prototype.removeClass = function (...c) { this.classList.remove(...c); };
El.prototype.toggleClass = function (c, on) { this.classList.toggle(c, on); };
El.prototype.hide = function () { this.hidden = true; };
El.prototype.show = function () { this.hidden = false; };

class FakeSetting {
  constructor(container) {
    this.settingEl = container.createDiv({ cls: 'setting-item' });
    const info = this.settingEl.createDiv({ cls: 'setting-item-info' });
    this.nameEl = info.createDiv({ cls: 'setting-item-name' });
    this.descEl = info.createDiv({ cls: 'setting-item-description' });
    this.controlEl = this.settingEl.createDiv({ cls: 'setting-item-control' });
  }
  setName(n) { this.nameEl.setText(n); return this; }
  setDesc(d) { this.descEl.setText(d); return this; }
  setClass(c) { this.settingEl.addClass(c); return this; }
  addButton(cb) {
    const el = this.controlEl.createEl('button');
    const b = { buttonEl: el, setButtonText(t) { el.setText(t); return b; }, setCta() { return b; }, setWarning() { return b; },
      setDisabled(v) { el.disabled = !!v; return b; }, setTooltip() { return b; }, setIcon() { return b; }, onClick(f) { el.onclick = f; return b; } };
    cb(b); return this;
  }
  addExtraButton(cb) { const el = this.controlEl.createEl('div'); const b = { extraSettingsEl: el, setIcon() { return b; }, setTooltip() { return b; }, onClick(f) { el.onclick = f; return b; } }; cb(b); return this; }
  addText(cb, tag = 'input') {
    const el = this.controlEl.createEl(tag);
    const t = { inputEl: el, setPlaceholder() { return t; }, setValue(v) { el.value = v; return t; }, getValue() { return el.value; }, onChange(f) { el.oninput = () => f(el.value); return t; } };
    cb(t); return this;
  }
  addTextArea(cb) { return this.addText(cb, 'textarea'); }
  addToggle(cb) { const el = this.controlEl.createEl('div'); const t = { setValue() { return t; }, onChange() { return t; } }; cb(t); return this; }
  addDropdown(cb) { const el = this.controlEl.createEl('select'); const d = { addOption() { return d; }, setValue() { return d; }, onChange() { return d; } }; cb(d); return this; }
  then(cb) { cb(this); return this; }
}
const notices = [];
class FakeModal {
  constructor(app) { this.app = app; this.contentEl = dom.document.createElement('div'); this.modalEl = dom.document.createElement('div'); this.opened = false; }
  open() { this.opened = true; this.onOpen?.(); }
  close() { this.opened = false; this.onClose?.(); }
}
const obsidianStub = { Plugin: class {}, PluginSettingTab: class { constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = dom.document.createElement('div'); } },
  Modal: FakeModal, Setting: FakeSetting, Notice: class { constructor(m) { notices.push(m); } }, Menu: class {}, TFile: class {}, MarkdownView: class {} };

const spawned = [];
function fakeSpawn(exe, args, opts) {
  const c = new EventEmitter();
  c.pid = 5000 + spawned.length;
  c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.stdout.setEncoding = () => {};
  c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
  spawned.push({ exe, args, opts });
  setTimeout(() => { c.stdout.emit('data', Buffer.from('{"ok":true}\n')); c.emit('close', 0); }, 0);
  return c;
}
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, Buffer, navigator: { clipboard: { writeText: async t => { context.clipboard = t; } } },
  window: { confirm: () => true },
  // 插件按「库根 + manifest.dir」require 自己的几个文件；临时库里没拷插件，指回仓库里的源文件
  require: n => n === 'obsidian' ? obsidianStub : n === 'child_process' ? { spawn: fakeSpawn }
    : /[\\/](onboarding-ui|media-nav|remote-ui)\.js$/.test(n) ? require(path.join(ROOT, PLUGIN_DIR, path.basename(n))) : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8') + '\nmodule.exports.__SettingTab = LinkBrainSettingTab; module.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;
const flush = () => new Promise(r => setTimeout(r, 0));
const texts = root => root.querySelectorAll('button').map(b => b.textContent);

// 临时目录：一个「仓库」（有 link_brain/__init__.py，里面 vault/）和一个和程序无关的库
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-b2-'));
const repo = path.join(tmp, 'repo'), repoVault = path.join(repo, 'vault'), plainVault = path.join(tmp, 'my-notes');
fs.mkdirSync(path.join(repo, 'link_brain'), { recursive: true }); fs.writeFileSync(path.join(repo, 'link_brain', '__init__.py'), '');
fs.mkdirSync(path.join(repoVault, '_archive'), { recursive: true }); fs.writeFileSync(path.join(repoVault, '_archive', 'catalog-data.json'), '{}');
fs.mkdirSync(plainVault, { recursive: true });

function makePlugin(base, { saved = {}, files = new Set(), manifestDir = '.obsidian/plugins/link-brain-actions' } = {}) {
  const p = new Plugin();
  const saves = [];
  p.manifest = { id: 'link-brain-actions', version: '0.2.0', dir: manifestDir };
  p.app = { vault: { adapter: { getBasePath: () => base, exists: async f => files.has(f), list: async () => ({ folders: [] }), mkdir: async f => files.add(f), read: async () => { throw new Error('ENOENT'); } }, configDir: '.obsidian' },
    workspace: {}, setting: { opened: [], open() {}, openTabById(id) { this.opened.push(id); } } };
  p.settings = Plugin.__merge(saved);
  p.saveSettings = async () => { saves.push(JSON.parse(JSON.stringify(p.settings))); };
  return { p, saves, files };
}

(async () => {
  // ── 1. 纯函数：拆命令 / 找命令 / 选后端 / 参数 ──
  assert.deepEqual([...Plugin.splitCommand('link-brain')], ['link-brain']);
  assert.deepEqual([...Plugin.splitCommand('"C:/Program Files/lb/link-brain.exe"  --x')], ['C:/Program Files/lb/link-brain.exe', '--x']);
  assert.deepEqual([...Plugin.splitCommand('uvx  link-brain')], ['uvx', 'link-brain']);
  const have = new Set([path.join('/bin1', 'link-brain.exe'), path.join('/home/u', '.local', 'bin', 'other.exe'), '/opt/lb']);
  const exists = f => have.has(f);
  assert.equal(Plugin.whichCommand('link-brain', { env: { PATH: '/bin0;/bin1' }, platform: 'win32', exists, home: '/home/u' }), path.join('/bin1', 'link-brain.exe'), 'Windows 补 .exe');
  assert.equal(Plugin.whichCommand('other', { env: { PATH: '/bin0' }, platform: 'win32', exists, home: '/home/u' }), path.join('/home/u', '.local', 'bin', 'other.exe'), 'PATH 里没有就看 uv 的 ~/.local/bin');
  assert.equal(Plugin.whichCommand('nothing', { env: { PATH: '/bin0' }, platform: 'win32', exists, home: '/home/u' }), null);
  assert.equal(Plugin.whichCommand('/opt/lb', { env: {}, platform: 'linux', exists }), '/opt/lb', '给了路径就只看那个路径');
  const isRepo = r => r === '/repo';
  let b = Plugin.pickBackend({ candidates: ['/x', '/repo'], isRepo, which: () => '/never' });
  assert.equal(b.mode, 'repo'); assert.equal(b.exe, 'python'); assert.equal(b.cwd, '/repo');
  b = Plugin.pickBackend({ candidates: ['/x', null], command: 'uvx link-brain', isRepo, which: c => (c === 'uvx' ? '/u/uvx.exe' : null) });
  assert.equal(b.mode, 'command'); assert.equal(b.exe, '/u/uvx.exe'); assert.deepEqual([...b.prefix], ['link-brain']);
  assert.deepEqual([...Plugin.backendArgv(b, ['-m', 'link_brain', 'login', '--json'])], ['link-brain', 'login', '--json'], '后端命令模式去掉 -m link_brain');
  assert.deepEqual([...Plugin.backendArgv({ mode: 'repo' }, ['-m', 'link_brain', 'catalog'])], ['-m', 'link_brain', 'catalog'], '仓库模式原样');
  b = Plugin.pickBackend({ candidates: [], command: '', isRepo, which: () => null });
  assert.equal(b.mode, 'missing'); assert.equal(b.command, 'link-brain', '空 = 默认 link-brain');
  assert.match(Plugin.backendMissingText(b), /没找到后端程序.*uv tool install link-brain/);

  // ── 1b. 真走 locateCollection：仓库里的库 → 仓库模式（作者本机现状），带 LINK_BRAIN_VAULT ──
  let env = makePlugin(repoVault, { files: new Set(['_archive/catalog-data.json']) });
  await env.p.locateCollection();
  assert.equal(env.p.backend.mode, 'repo'); assert.equal(env.p.repoRoot, fs.realpathSync.native(repo), '仓根 = 收藏库上一级（和改前一样）');
  assert.equal(env.p.vaultDir, fs.realpathSync.native(repoVault));
  spawned.length = 0;
  let r = await env.p.runPy(['-m', 'link_brain', 'catalog']);
  assert.equal(r.code, 0);
  assert.equal(spawned[0].exe, 'python'); assert.deepEqual([...spawned[0].args], ['-m', 'link_brain', 'catalog']);
  assert.equal(spawned[0].opts.cwd, fs.realpathSync.native(repo)); assert.equal(spawned[0].opts.env.LINK_BRAIN_VAULT, fs.realpathSync.native(repoVault));
  assert.equal(spawned[0].opts.env.PYTHONIOENCODING, 'utf-8');
  // 插件目录上两级是仓库（插件目录链接到仓库里的 obsidian-plugins/link-brain-actions）→ 也算仓库模式
  env = makePlugin(plainVault, { manifestDir: path.relative(plainVault, path.join(repo, 'obsidian-plugins', 'link-brain-actions')) });
  fs.mkdirSync(path.join(repo, 'obsidian-plugins', 'link-brain-actions'), { recursive: true });
  await env.p.locateCollection();
  assert.equal(env.p.backend.mode, 'repo', '插件目录上两级是仓库');
  assert.equal(env.p.vaultDir, fs.realpathSync.native(plainVault), '收藏库仍是当前库，不要求在仓库里');

  // ── 1c. 普通库 + 后端命令：exe + 子命令，cwd 不在仓库，带 LINK_BRAIN_VAULT ──
  const fakeExe = path.join(tmp, 'bin', process.platform === 'win32' ? 'lb-test.exe' : 'lb-test');
  fs.mkdirSync(path.dirname(fakeExe), { recursive: true }); fs.writeFileSync(fakeExe, '');
  env = makePlugin(plainVault, { saved: { backend: { command: `"${fakeExe}" --quiet` } } });
  await env.p.locateCollection();
  assert.equal(env.p.backend.mode, 'command'); assert.equal(env.p.repoRoot, null);
  spawned.length = 0;
  await env.p.runPy(['-m', 'link_brain', 'reader', 'status']);
  assert.equal(spawned[0].exe, fakeExe); assert.deepEqual([...spawned[0].args], ['--quiet', 'reader', 'status']);
  assert.equal(spawned[0].opts.env.LINK_BRAIN_VAULT, fs.realpathSync.native(plainVault));
  assert.equal(spawned[0].opts.cwd, fs.realpathSync.native(plainVault));
  // 问答 worker 也走同一个入口
  spawned.length = 0; env.p.ensureAnswerWorker();
  assert.equal(spawned[0].exe, fakeExe); assert.deepEqual([...spawned[0].args], ['--quiet', 'serve', '--stdio']);
  assert.ok(spawned[0].opts.env.LINK_BRAIN_VAULT);
  env.p.answerWorker = null;
  // 收藏放进子文件夹：LINK_BRAIN_VAULT 跟着换，lbRoot 也是它
  fs.mkdirSync(path.join(plainVault, '收藏'), { recursive: true });
  env.p.settings.collectionFolder = '收藏'; await env.p.locateCollection();
  assert.equal(env.p.lbRoot, '收藏'); assert.equal(env.p.vaultDir, fs.realpathSync.native(path.join(plainVault, '收藏')));

  // ── 2. 找不到后端：如实提示 + 复制按钮，不起进程 ──
  env = makePlugin(plainVault, { saved: { backend: { command: 'lb-definitely-not-installed-xyz' } } });
  await env.p.locateCollection();
  assert.equal(env.p.backend.mode, 'missing');
  spawned.length = 0;
  await assert.rejects(env.p.runPy(['-m', 'link_brain', 'login', '--status', '--json']), e => /没找到后端程序/.test(e.message) && e.message.includes('uv tool install link-brain') && e.backendMissing);
  await assert.rejects(env.p.loginAccount(), /没找到后端程序/);
  assert.equal(spawned.length, 0, '找不到就不 spawn');
  notices.length = 0; env.p.log = async () => {};
  const rr = await env.p.run(['-m', 'link_brain', 'catalog'], '重建目录');
  assert.equal(rr.code, -1); assert.ok(notices.some(n => /重建目录 起不来：没找到后端程序/.test(n)));
  assert.throws(() => env.p.ensureAnswerWorker(), /没找到后端程序/);
  // 设置页顶部：提示 + 「复制安装命令」
  env.p.renderAccounts = c => c.createDiv({ cls: 'lb-accounts' });
  env.p.renderSyncRow = () => () => {};
  env.p.capsWriterDir = () => null;
  let tab = new Plugin.__SettingTab({}, env.p); tab.display();
  let hint = tab.containerEl.querySelector('.lb-setup-hint');
  assert.ok(hint && /没找到后端程序/.test(hint.textContent), '设置页顶部有缺后端提示');
  hint.querySelector('button').click(); await flush();
  assert.equal(context.clipboard, 'uv tool install link-brain');
  // 「更多 → 运行环境」里有后端命令一行
  const rowNames = tab.containerEl.querySelectorAll('.setting-item-name').map(e => e.textContent);
  assert.ok(rowNames.includes('后端命令') && rowNames.includes('收藏存放位置'));
  // 启动检查：缺后端只提示，不弹引导
  notices.length = 0;
  assert.equal(await env.p.startupChecks(), 'backend-missing');
  assert.ok(notices.some(n => /没找到后端程序/.test(String(n?.textContent ?? n))));

  // ── 3. 首次引导 ──
  // 作者本机：仓库模式 + 已有 _archive → 不弹
  env = makePlugin(repoVault, { files: new Set(['_archive', '_archive/catalog-data.json']) });
  await env.p.locateCollection();
  assert.equal(await env.p.onboardingUI().needsOnboarding(), false, '已准备好的库不弹');
  assert.equal(await env.p.startupChecks(), 'ready');
  // 走过引导 → 不弹
  env = makePlugin(plainVault, { saved: { backend: { command: `"${fakeExe}"` }, onboarding: { done: true } } });
  await env.p.locateCollection();
  assert.equal(await env.p.onboardingUI().needsOnboarding(), false);
  // 新库 + 后端在 + 没走过 → 弹
  const home = path.join(tmp, 'lbhome'); process.env.LINK_BRAIN_HOME = home;
  env = makePlugin(plainVault, { saved: { backend: { command: `"${fakeExe}"` } } });
  await env.p.locateCollection();
  assert.equal(await env.p.onboardingUI().needsOnboarding(), true);
  const calls = [];
  let readerStatus = { ok: true, reader: null, release_configured: false, bin_dir: '~/.link-brain/bin' };
  env.p.runPy = async (args, opts = {}) => {
    calls.push({ args: [...args], env: opts.env || null });
    if (args.includes('reader') && args.includes('status')) return { code: 0, json: readerStatus, out: '', err: '' };
    if (args.includes('reader') && args.includes('install')) return { code: 0, json: { ok: true, message: '读取组件已装好（2 个文件）' }, out: '', err: '' };
    throw new Error('意外的调用 ' + args.join(' '));
  };
  let accountsRendered = 0;
  env.p.renderAccounts = c => { accountsRendered++; c.createDiv({ cls: 'lb-accounts' }).createDiv({ text: '小红书 · 未登录' }); return async () => { accountsRendered++; }; };
  assert.equal(await env.p.startupChecks(), 'onboarding');
  const UI = env.p.onboardingUI();
  let m = new UI.OnboardingModal(); m.open(); await flush(); await flush();
  const steps = () => m.contentEl.querySelectorAll('div').filter(d => d.classList.contains('lb-onb-step'));
  assert.equal(steps().length, 4, '四步');
  assert.deepEqual(steps().map(s => s.querySelector('h3').textContent), ['① 收藏存放位置', '② 读取组件', '③ 扫码登录', '④ AI（可选）']);
  const stateOf = i => steps()[i].querySelectorAll('div').find(d => d.classList.contains('lb-onb-state')).textContent;
  const btn = (i, t) => steps()[i].querySelectorAll('button').find(b => b.textContent === t);
  // ② 发布地址没配：按钮禁用且写明测试版，给手动放置说明，不调 install
  assert.ok(btn(1, '发布地址还没配置（测试版）')?.disabled, '发布地址没配时按钮写明且不能点');
  assert.match(steps()[1].textContent, /手动放置.*~\/\.link-brain\/bin/);
  assert.ok(!calls.some(c => c.args.includes('install')));
  assert.equal(stateOf(1), '还没装');
  btn(1, '跳过').click(); assert.match(stateOf(1), /^已跳过/);
  // ① 收藏位置：乱填如实拒绝；填子文件夹 → 建文件夹、存设置、LINK_BRAIN_VAULT 跟着换、写 ~/.link-brain/config.json
  const folderInput = steps()[0].querySelector('input');
  folderInput.value = '../外面'; folderInput.oninput();
  await btn(0, '保存').onclick(); assert.match(stateOf(0), /^没做成：/);
  folderInput.value = '收藏'; folderInput.oninput();
  await btn(0, '保存').onclick();
  assert.match(stateOf(0), /^✓ 收藏放在 .*收藏（命令行也用这个位置）/);
  assert.equal(env.p.settings.collectionFolder, '收藏'); assert.equal(env.p.lbRoot, '收藏');
  assert.equal(env.p.vaultDir, fs.realpathSync.native(path.join(plainVault, '收藏')));
  assert.equal(JSON.parse(fs.readFileSync(path.join(home, 'config.json'), 'utf8')).vault, env.p.vaultDir);
  // ③ 扫码：就是账号卡片（同一个扫码流程），可跳过
  assert.ok(steps()[2].querySelector('.lb-accounts'), '引导里放的是账号卡片');
  btn(2, '跳过').click(); assert.match(stateOf(2), /^已跳过/);
  // ④ AI：没配不打勾；「去填 AI 设置」关窗并打开本插件设置页
  assert.equal(stateOf(3), '');
  btn(3, '去填 AI 设置').click();
  assert.deepEqual(env.p.app.setting.opened.slice(-1), ['link-brain-actions']);
  assert.equal(m.opened, false);
  assert.equal(env.p.settings.onboarding.done, true, '关窗 = 走过引导');
  assert.equal(await UI.needsOnboarding(), false);
  // 发布地址配了：按钮可点 → reader install → 状态如实、账号卡片刷新
  readerStatus = { ok: true, reader: null, release_configured: true, bin_dir: '~/.link-brain/bin' };
  m = new UI.OnboardingModal(); m.open(); await flush(); await flush();
  const before = accountsRendered;
  await btn(1, '下载读取组件').onclick();
  assert.ok(calls.some(c => c.args.join(' ') === '-m link_brain reader install'));
  assert.equal(stateOf(1), '✓ 读取组件已装好（2 个文件）');
  assert.ok(accountsRendered > before, '装好后账号卡片重新检查');
  // 已就位：直接打勾
  readerStatus = { ok: true, reader: 'C:/x/link-brain-reader.exe', release_configured: false };
  m = new UI.OnboardingModal(); m.open(); await flush(); await flush();
  assert.match(stateOf(1), /^✓ 已就位/);
  m.close();
  assert.equal(UI._internals.normalizeFolder('C:/x').ok, false);
  assert.equal(UI._internals.normalizeFolder('a\\b/').folder, 'a/b');
  delete process.env.LINK_BRAIN_HOME;

  // ── 4. 定时同步任务名 ──
  const sched = (tasks) => {
    const log = [];
    const p = new Plugin(); p.vaultDir = 'D:/v';
    p.runPy = async (args, opts = {}) => {
      log.push({ args: [...args], task: opts.env?.LINK_BRAIN_SYNC_TASK || null });
      if (args.includes('--install')) return { code: 0, json: { ok: true, task: 'LinkBrainNightly', message: '已注册计划任务 LinkBrainNightly：每天 05:30 夜跑' } };
      if (args.includes('--set')) return { code: 0, json: { ok: true, freq: args[args.indexOf('--set') + 1] } };
      const t = opts.env?.LINK_BRAIN_SYNC_TASK;
      return { code: 0, json: tasks[t] || { task: t, freq: 'none', enabled: false } };
    };
    return { p, log };
  };
  assert.equal(Plugin.pickSyncTask({ freq: 'daily' }, { freq: 'daily' }), 'LinkBrainNightly');
  assert.equal(Plugin.pickSyncTask({ freq: 'none' }, { freq: 'unknown' }), 'XhsFavSync');
  assert.equal(Plugin.pickSyncTask({ freq: 'none' }, { freq: 'none' }), null);
  // 作者本机：只有旧任务 → 读和改都指向旧任务（行为不变）
  let s = sched({ XhsFavSync: { task: 'XhsFavSync', freq: 'daily', time: '04:00', enabled: true } });
  let cur = await s.p.getSyncSchedule();
  assert.equal(cur.task, 'XhsFavSync'); assert.equal(cur.freq, 'daily');
  assert.deepEqual(s.log.map(x => x.task), ['LinkBrainNightly', 'XhsFavSync']);
  await s.p.setSyncSchedule('daily', '05:00');
  assert.deepEqual(s.log.at(-1), { args: ['-m', 'link_brain', 'sync-schedule', '--set', 'daily', '--at', '05:00'], task: 'XhsFavSync' });
  // 两个都有：LinkBrainNightly 优先，旧任务不用再读
  s = sched({ LinkBrainNightly: { freq: 'weekly', day: 'Monday', time: '03:00', enabled: true }, XhsFavSync: { freq: 'daily' } });
  cur = await s.p.getSyncSchedule(); assert.equal(cur.task, 'LinkBrainNightly'); assert.equal(s.log.length, 1);
  await s.p.setSyncSchedule('off'); assert.deepEqual(s.log.at(-1), { args: ['-m', 'link_brain', 'sync-schedule', '--set', 'off'], task: 'LinkBrainNightly' });
  // 都没有：状态写「还没开启」；关闭不起进程；每天 = --install --at --vault；每周 = 注册后再改成每周
  s = sched({});
  cur = await s.p.getSyncSchedule();
  assert.equal(cur.task, null); assert.equal(cur.installable, true);
  assert.match(Plugin.scheduleStatusText(cur), /还没开启定时同步.*LinkBrainNightly/);
  assert.equal(Plugin.scheduleStatusText({ freq: 'none' }), '当前：没有计划任务', '旧文案不变');
  let n0 = s.log.length;
  assert.equal((await s.p.setSyncSchedule('off')).ok, true); assert.equal(s.log.length, n0, '没任务时关闭不起进程');
  let res = await s.p.setSyncSchedule('daily', '05:30');
  assert.equal(res.ok, true); assert.match(res.detail, /已注册计划任务 LinkBrainNightly/);
  assert.deepEqual(s.log.at(-1).args, ['-m', 'link_brain', 'sync-schedule', '--install', '--at', '05:30', '--vault', 'D:/v']);
  s = sched({}); await s.p.getSyncSchedule();
  res = await s.p.setSyncSchedule('weekly', '05:30', 'Friday');
  assert.equal(res.ok, true);
  assert.ok(s.log.at(-2).args.includes('--install'));
  assert.deepEqual(s.log.at(-1), { args: ['-m', 'link_brain', 'sync-schedule', '--set', 'weekly', '--at', '05:30', '--day', 'Friday'], task: 'LinkBrainNightly' });
  // 注册失败如实带原因
  s = sched({}); s.p.runPy = async (args) => args.includes('--install') ? { code: 1, json: { ok: false, message: '没注册上计划任务：被系统策略限制' } } : { code: 0, json: { freq: 'none' } };
  await s.p.getSyncSchedule();
  res = await s.p.setSyncSchedule('daily', '04:00'); assert.equal(res.ok, false); assert.match(res.error, /被系统策略限制/);

  // ── 5. Dataview ──
  const plugins = (o) => ({ plugins: o });
  assert.equal(Plugin.dataviewState({}), null, '拿不到插件表不提示');
  assert.equal(Plugin.dataviewState(plugins({ manifests: {}, enabledPlugins: new Set(), plugins: {} })), 'missing');
  assert.equal(Plugin.dataviewState(plugins({ manifests: { dataview: {} }, enabledPlugins: new Set(), plugins: {} })), 'disabled');
  assert.equal(Plugin.dataviewState(plugins({ manifests: { dataview: {} }, enabledPlugins: new Set(['dataview']), plugins: { dataview: { settings: { enableDataviewJs: false } } } })), 'nojs');
  assert.equal(Plugin.dataviewState(plugins({ manifests: { dataview: {} }, enabledPlugins: new Set(['dataview']), plugins: { dataview: { settings: { enableDataviewJs: true } } } })), 'ok');
  env = makePlugin(repoVault, { files: new Set(['_archive']) }); await env.p.locateCollection();
  env.p.app.plugins = { manifests: {}, enabledPlugins: new Set(), plugins: {} };
  env.p.renderAccounts = c => c.createDiv({ cls: 'lb-accounts' }); env.p.renderSyncRow = () => () => {}; env.p.capsWriterDir = () => null;
  tab = new Plugin.__SettingTab({}, env.p); tab.display();
  hint = tab.containerEl.querySelectorAll('div').find(d => d.classList.contains('is-dataview'));
  assert.ok(hint && /Dataview/.test(hint.textContent) && /还没装/.test(hint.textContent), '设置页有 Dataview 缺失提示');
  hint.querySelector('button').click();
  assert.deepEqual(env.p.app.setting.opened.slice(-1), ['community-plugins']);
  // 目录页顶部
  const view = { contentEl: dom.document.createElement('div') };
  view.contentEl.createDiv({ text: '```dataviewjs …' });
  const banner = env.p.onboardingUI().dataviewBanner(view);
  assert.ok(banner && view.contentEl.querySelector('.lb-dataview-hint'), '目录页顶部有提示');
  env.p.app.plugins = { manifests: { dataview: {} }, enabledPlugins: new Set(['dataview']), plugins: { dataview: { settings: { enableDataviewJs: false } } } };
  env.p.onboardingUI().dataviewBanner(view);
  assert.equal(view.contentEl.querySelectorAll('.lb-dataview-hint').length, 1, '重开只留一条');
  view.contentEl.querySelector('.lb-dataview-hint').querySelector('button').click();
  assert.deepEqual(env.p.app.setting.opened.slice(-1), ['dataview'], '没开 JS → 打开 Dataview 设置');
  env.p.app.plugins.plugins.dataview.settings.enableDataviewJs = true;
  assert.equal(env.p.onboardingUI().dataviewBanner(view), null); assert.equal(view.contentEl.querySelector('.lb-dataview-hint'), null, '好了就撤掉');
  // 都正常时设置页什么也不加（第一层不多一行）
  tab = new Plugin.__SettingTab({}, env.p); tab.display();
  assert.equal(tab.containerEl.querySelector('.lb-setup-hint'), null);

  // ── 6. 媒体导航并进主插件 ──
  const events = [];
  const docStub = { querySelectorAll: () => [], head: { appendChild() {} }, body: {}, createElement: () => ({ remove() {} }) };
  global.document = docStub; global.MutationObserver = class { observe() {} disconnect() {} };
  const host = { app: { plugins: { enabledPlugins: new Set() } }, registered: 0, register() { this.registered++; }, registerDomEvent(el, type) { events.push(type); } };
  const factory = require(path.join(ROOT, PLUGIN_DIR, 'media-nav.js'));
  const nav = factory({}, host);
  assert.equal(nav.attach(), true);
  for (const t of ['pointerdown', 'focusin', 'keydown', 'click']) assert.ok(events.includes(t), '接管了 ' + t);
  assert.equal(nav.attach(), true, '重复 attach 不重复挂'); assert.equal(events.filter(t => t === 'keydown').length, 1);
  events.length = 0;
  const old = factory({}, { ...host, app: { plugins: { enabledPlugins: new Set(['link-brain-native-media-nav']) } } });
  assert.equal(old.attach(), false); assert.equal(old.skipped, true); assert.equal(events.length, 0, '旧插件开着就不接管（不重复弹大图）');
  // main.js onload 真的接上 media-nav.js；旧插件开着时设置页提示停用它
  const p = new Plugin();
  p.manifest = { id: 'link-brain-actions', dir: PLUGIN_DIR };
  p.app = { vault: { adapter: { getBasePath: () => ROOT, exists: async () => false, list: async () => ({ folders: [] }) } }, workspace: { onLayoutReady() {} },
    plugins: { manifests: { dataview: {} }, enabledPlugins: new Set(['dataview', 'link-brain-native-media-nav']), plugins: { dataview: { settings: { enableDataviewJs: true } } } } };
  p.loadData = async () => null; p.addSettingTab = () => {}; p.addCommand = () => {}; p.addRibbonIcon = () => {}; p.register = () => {}; p.registerDomEvent = () => {};
  await p.onload();
  assert.ok(p.mediaNav && p.mediaNav.skipped === true, 'onload 载入了 media-nav.js（旧插件开着 → 先不接管）');
  p.renderAccounts = c => c.createDiv({ cls: 'lb-accounts' }); p.renderSyncRow = () => () => {}; p.capsWriterDir = () => null; p.saveSettings = async () => {};
  tab = new Plugin.__SettingTab({}, p); tab.display();
  hint = tab.containerEl.querySelectorAll('div').find(d => d.classList.contains('is-medianav'));
  assert.ok(hint && /停用/.test(hint.textContent), '设置页提示停用旧图片导航插件');
  p.app.plugins.enabledPlugins.delete('link-brain-native-media-nav'); p.mediaNav = null;
  await p.onload();
  assert.equal(p.mediaNav.attached, true, '旧插件停用后由本插件接管');
  delete global.document; delete global.MutationObserver;
  // doctor 必需文件清单和插件目录一致（Python 侧另有 pytest）
  const doctorSrc = fs.readFileSync(path.join(ROOT, 'link_brain', 'doctor.py'), 'utf8');
  for (const f of ['media-nav.js', 'onboarding-ui.js']) assert.ok(doctorSrc.includes(`'${f}'`) && fs.existsSync(path.join(ROOT, PLUGIN_DIR, f)), f);

  fs.rmSync(tmp, { recursive: true, force: true });
  console.log('PASS batch5 delivery UI: backend choice (repo / command / missing) + LINK_BRAIN_VAULT on every spawn, missing-backend hint with copy, onboarding 4 steps with skip + honest state, sync task LinkBrainNightly → legacy → install, Dataview hints, media-nav merged');
})().catch(e => { console.error(e); process.exitCode = 1; });

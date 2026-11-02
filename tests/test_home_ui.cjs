// 1009 作者的裁决：功能开关 +「一键装好 / 跑完」+ 零配置首次自动跑；1010：设置页分栏后这一块在「概览」（renderRun）和「AI」（renderAI）。
// 断言：
//   1. 纯函数：没选过 = 轻量版；依赖联动；进度事件 → 各步状态；评论补齐那一行；每个功能旁的价钱（本地免费 / 约 ¥x / 100 篇 / 约 ¥x / 次 / 按用量）；
//   2. 「一键装好 / 跑完」：经 spawnPy（exclusive）跑 `setup run`，stdout 一行一个事件画成各步 ✓ / ⟳ / ✗ + 当前在装的进度条，
//      结果一句话；要人处理（掉登录 / 验证）给「去扫码 / 验证」按钮；
//   3. 首次：老库（已有目录数据）只记一笔、选择不动、不跑；新库 → 选轻量版、自动跑一次；跑过不再跑；
//   4. spawnPy 的 onLine：stdout 被切成碎块也按整行回调，最后一行没换行也给（setup run / install 的进度靠它）；
//   2b（1102）. 没有后端时主按钮是「一键装好」：装后端的五步 + 下载进度条画在同一块，完了只留一句；失败不抛、按钮能再点；runAll 先装后端。
// 不起真进程：child_process 是替身。
'use strict';
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert/strict');
const { EventEmitter } = require('events');
const { makeDom } = require('./_fakedom.cjs');

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
  addButton(cb) { const el = this.controlEl.createEl('button'); const b = { buttonEl: el, setButtonText(t) { el.setText(t); return b; }, setCta() { return b; }, setDisabled(v) { el.disabled = !!v; return b; }, onClick(f) { el.onclick = f; return b; } }; cb(b); return this; }
  addToggle(cb) { const el = this.controlEl.createEl('div', { cls: 'checkbox-container' }); const t = { setValue(v) { el.checked = !!v; return t; }, onChange(f) { el.onchange = () => f(el.checked); return t; } }; cb(t); return this; }
}
const notices = [];
const OBS = { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Setting: FakeSetting, Notice: class { constructor(m) { notices.push(m); } }, Menu: class {} };
let spawnImpl = () => { throw new Error('测试里不许 spawn 真进程'); };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, document: dom.document, URL, console, Buffer,
  require: n => n === 'obsidian' ? OBS : n === 'child_process' ? { spawn: (...a) => spawnImpl(...a) } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
const Plugin = context.module.exports;
const homeFactory = require('../obsidian-plugins/link-brain-actions/home-ui.js');
const H = homeFactory._internals;
const flush = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };

const PLAN = { ok: true, components: [
  { id: 'core', name: '归档·同步·浏览·关键词搜索', required: true, status: 'ready', depends: [] },
  { id: 'reader', name: '读取组件', required: true, status: 'ready', depends: ['core'] },
  { id: 'dataview', name: 'Dataview', required: true, status: 'ready', depends: [] },
  { id: 'ocr', name: '本地 OCR（图片里的字）', status: 'ready', depends: ['core'] },
  { id: 'asr', name: '本地语音识别', status: 'missing', depends: ['core'] },
  { id: 'capslock', name: 'CapsLock 语音输入', status: 'missing', depends: ['asr'] },
  { id: 'ai_text', name: 'AI 问答 · 概要 · 打标（要 API key）', needs_key: true, depends: ['core'] },
  { id: 'ai_vision', name: '识图（要 API key）', needs_key: true, depends: ['ocr'] }],
  presets: { light: ['core', 'reader', 'dataview', 'ocr'] } };

(async () => {
  // —— 1. 纯函数 ——
  assert.deepEqual(H.initialSelection(null, PLAN), ['core', 'reader', 'dataview', 'ocr'], '没选过 = 轻量版');
  assert.deepEqual(H.initialSelection(['capslock'], PLAN), ['core', 'reader', 'dataview', 'asr', 'capslock'], '勾 CapsLock 连语音识别一起；必选永远在');
  assert.deepEqual(H.toggleSelection(['core', 'reader', 'dataview', 'ocr', 'ai_vision'], 'ocr', false, PLAN.components), ['core', 'reader', 'dataview'], '取消 OCR → 识图跟着取消');
  const run = { stages: {} };
  H.applyRunEvent(run, { type: 'progress', stage: 'install', label: '装好要用的组件', index: 1, count: 7, state: 'running', text: '检查中…' });
  H.applyRunEvent(run, { type: 'progress', stage: 'install', component: 'asr', phase: '下载', done: 1, total: 4 });
  assert.equal(run.install.component, 'asr', '组件安装进度单独记');
  H.applyRunEvent(run, { type: 'progress', stage: 'install', label: '装好要用的组件', index: 1, count: 7, state: 'ok', text: '全部就绪' });
  H.applyRunEvent(run, { type: 'progress', stage: 'sync', label: '同步收藏', index: 3, count: 7, state: 'running', text: '' });
  H.applyRunEvent(run, { type: 'progress', stage: 'sync', state: 'running', text: '第 3/40 条收藏是新的' });
  assert.deepEqual(run.stages.sync, { label: '同步收藏', index: 3, count: 7, state: 'running', text: '第 3/40 条收藏是新的' });
  H.applyRunEvent(run, { type: 'result', ok: true, message: '都跑完了' });
  assert.equal(run.state, 'done'); assert.equal(run.result.message, '都跑完了');
  const now = Date.parse('2026-10-10T01:00:00+11:00');
  assert.equal(H.fillLine({ state: 'running', message: '正在补评论 · 已补齐 3/197 篇', updated_at: new Date(now - 60000).toISOString() }, null, now), '正在补评论 · 已补齐 3/197 篇');
  assert.equal(H.fillLine({ state: 'done', message: '评论都补齐了' }, { ok: true, pending: 0, stuck: 2 }, now), '评论都补齐了（2 篇连着补不上，见问题列表）');
  assert.equal(H.fillLine(null, { ok: true, pending: 5, missing: 70, stuck: 0 }, now), '5 篇的评论还没补齐（共缺 70 条回复）');
  // 1010 作者：每个功能旁标清价钱
  const EST = { data: { items: [{ id: 'summary', yuan: 0.8, per: '100 篇' }, { id: 'ask', yuan: 0.004, per: '次' }, { id: 'vision', yuan: null, per: '100 篇' }] } };
  assert.equal(H.priceText('ocr', EST), '免费（本机跑）');
  assert.equal(H.priceText('capslock', null), '免费（本机跑）');
  assert.equal(H.priceText('ai_text', EST), '概要和打标签 约 ¥0.80 / 100 篇 · 问收藏 约 ¥0.004 / 次');
  assert.equal(H.priceText('ai_vision', EST), '按用量', '估不出价 → 按用量');
  assert.equal(H.priceText('ai_vision', { error: 'x' }), '按用量');
  assert.equal(H.priceText('core', EST), '', '必需的不标价');

  // —— 2. 一键装好 / 跑完 ——
  const files = {};
  const p = new Plugin();
  p.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async f => f in files, read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; } } }, workspace: { trigger() {} } };
  p.lbPath = x => x; p.repoRoot = 'D:/repo';
  p.settings = Plugin.__merge ? Plugin.__merge({}) : { setup: {} };
  p.settings.setup = { selected: null };
  p.settings.voice = { capsLock: false }; p.settings.ocr = { mode: 'local' }; p.settings.asrAI = { mode: 'capswriter' }; p.settings.textAI = { mode: 'http' }; p.settings.visionAI = { mode: 'off' };
  const saves = []; p.saveSettings = async () => { saves.push(JSON.parse(JSON.stringify(p.settings))); };
  p.notify = (m, o = {}) => notices.push({ m, o });
  p.log = async () => {};
  p.openSetupPage = s => { p.opened = s; };
  const runs = [];
  spawnImpl = (exe, args) => {
    runs.push(args);
    const c = new EventEmitter(); c.pid = 4242; c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
    const ev = o => Buffer.from(JSON.stringify(o) + '\n');
    if (args.includes('plan')) { setTimeout(() => { c.stdout.emit('data', ev(PLAN)); c.emit('close', 0); }, 0); return c; }
    setTimeout(() => {
      c.stdout.emit('data', ev({ type: 'progress', stage: 'install', label: '装好要用的组件', index: 1, count: 7, state: 'ok', text: '全部就绪' }));
      c.stdout.emit('data', ev({ type: 'progress', stage: 'login', label: '确认小红书登录', index: 2, count: 7, state: 'failed', text: '小红书掉登录了：扫码登录' }));
      c.stdout.emit('data', ev({ type: 'progress', stage: 'sync', label: '同步收藏（含 OCR / 识图 / 概要）', index: 3, count: 7, state: 'skipped', text: '先处理小红书登录（见上一步）' }));
      c.stdout.emit('data', ev({ type: 'progress', stage: 'catalog', label: '整理目录', index: 5, count: 7, state: 'ok', text: '完成' }));
      c.stdout.emit('data', ev({ type: 'result', ok: false, code: 'NEEDS_HUMAN', message: '先处理小红书：小红书掉登录了：扫码登录；处理好再点一次「一键装好 / 跑完」', stages: [] }));
      c.emit('close', 5);
    }, 0);
    return c;
  };
  const home = homeFactory(OBS, p);
  const pane = dom.document.createElement('div');
  const tab = { sectionTextAI: () => {}, sectionVisionAI: () => {} };
  const stop = home.renderRun(pane, tab);
  // 按钮不能点时，旁边一句为什么（功能清单还在读）
  const go0 = pane.querySelector('.lb-run-go');
  assert.ok(go0 && go0.disabled, '还没读到功能清单：先不能点');
  assert.match(pane.querySelector('.lb-why').textContent, /正在看这台电脑装了什么/);
  await flush(10);
  const go = pane.querySelector('.lb-run-go');
  assert.ok(go && !go.disabled, '功能清单读到后按钮可点');
  go.onclick(); await flush(12);
  const runArgs = runs.find(a => a.includes('run'));
  assert.deepEqual(Array.from(runArgs), ['-m', 'link_brain', 'setup', 'run']);
  assert.deepEqual(Array.from(p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr'], '跑之前把「没选过」落成轻量版');
  // 1027b 作者：「不影响实际体验的就别显示了」——跑完只留一句结果（里面说清要你做什么），不再摆每一步的 ✓ / ✗
  assert.equal(pane.querySelectorAll('.lb-run-step').length, 0, '跑完不列每一步');
  assert.match(pane.querySelector('.lb-run-result').textContent, /先处理小红书/);
  const last = notices.at(-1);
  assert.equal(last.o.actions[0].label, '去扫码 / 验证');
  last.o.actions[0].run(); assert.equal(p.opened, 'status', '去扫码 → 打开设置页顶部账号那一行');
  assert.equal(p.running, null, '跑完放开互斥位');
  stop();

  // —— 2b. 1102 托管模式：没有后端时这个主按钮先管「一键装好」——装后端的五步画在同一块，完了只留一句；装好后变回「一键装好 / 跑完」——
  {
    const q = new Plugin();
    q.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async () => false } } };
    q.lbPath = x => x; q.settings = { setup: {} }; q.saveSettings = async () => {}; q.log = async () => {};
    const told = []; q.notify = (m, o = {}) => told.push({ m, o });
    let mode = 'missing';
    q.currentBackend = () => ({ mode, exe: mode === 'missing' ? null : 'D:/h/py/Scripts/link-brain.exe', command: 'link-brain' });
    q.runPy = async args => { if (args.includes('plan')) return { code: 0, json: PLAN }; throw new Error('意外的调用 ' + args.join(' ')); };
    let resolveInstall; const events = [];
    q.backendInstall = () => ({ ensureBackend: (pl, { onProgress }) => new Promise(r => { resolveInstall = res => r(res); events.push(onProgress); }) });
    const h = homeFactory(OBS, q);
    const pane = dom.document.createElement('div');
    const stop = h.renderRun(pane, { sectionTextAI: () => {}, sectionVisionAI: () => {} });
    const go = pane.querySelector('.lb-run-go');
    assert.equal(go.textContent, '一键装好', '没有后端：主按钮是「一键装好」');
    assert.ok(!go.disabled, '能点（不等功能清单——没后端读不到）');
    assert.match(pane.textContent, /还没有后端程序.*没有 Python 也行/);
    go.onclick(); await flush();
    const emit = events[0];
    emit({ stage: 'uv', label: '准备安装工具 uv', done: 1048576, total: 4194304, text: '1.0 / 4.0 MB', state: 'running' });
    await new Promise(r => setTimeout(r, 170));   // repaint 节流 120ms
    assert.equal(pane.querySelector('.lb-run-go').textContent, '正在装后端…');
    assert.ok(pane.querySelector('.lb-run-go').disabled);
    assert.equal(pane.querySelectorAll('.lb-backend-steps .lb-run-step').length, 1, '装的时候逐步画');
    assert.match(pane.querySelector('.lb-run-step').textContent, /准备安装工具 uv.*1\.0 \/ 4\.0 MB/);
    assert.equal(pane.querySelector('.lb-bar-fill').style.width, '25%', '下载进度条');
    emit({ stage: 'uv', label: '准备安装工具 uv', done: null, total: null, text: '就绪', state: 'ok' });
    emit({ stage: 'python', label: '准备 Python 3.12', done: null, total: null, text: 'Installed Python 3.12.x', state: 'running' });
    await new Promise(r => setTimeout(r, 170));   // repaint 节流 120ms
    assert.equal(pane.querySelectorAll('.lb-run-step').length, 2);
    assert.equal(pane.querySelector('.lb-run-step.is-ok .lb-run-mark').textContent, '✓');
    assert.ok(!pane.querySelector('.lb-bar'), '没有 done / total 的步不画进度条');
    mode = 'managed';
    resolveInstall({ ok: true, code: '', message: '后端装好了：link-brain 0.2.0' });
    await flush(20);
    assert.match(pane.querySelector('.lb-run-result').textContent, /后端装好了：link-brain 0\.2\.0/, '完了只留一句结果');
    assert.equal(pane.querySelectorAll('.lb-run-step').length, 0, '跑完不列每一步');
    assert.equal(pane.querySelector('.lb-run-go').textContent, '一键装好 / 跑完', '装好后变回「一键装好 / 跑完」');
    assert.equal(told.at(-1).m, '后端装好了：link-brain 0.2.0'); assert.equal(told.at(-1).o.kind, 'ok');
    // 失败：码和原因留在这一块（{ok:false, code, message}，不抛），按钮回到「一键装好」能再点
    mode = 'missing'; told.length = 0;
    pane.querySelector('.lb-run-go').onclick(); await flush();
    resolveInstall({ ok: false, code: 'TRANSIENT.NETWORK', message: '下载 uv没连上：ECONNREFUSED' });
    await flush(20);
    assert.match(pane.querySelector('.lb-run-result.is-failed').textContent, /下载 uv没连上/);
    assert.equal(pane.querySelector('.lb-run-go').textContent, '一键装好');
    assert.equal(told.at(-1).o.kind, 'error'); assert.equal(told.at(-1).o.actions[0].label, '打开设置');
    // runAll 在没后端时先装：装不上就不往下跑 setup run
    q.backendInstall = () => ({ ensureBackend: async () => ({ ok: false, code: 'SKIPPED.NOT_CONFIGURED', message: '后端发布包还没发布' }) });
    const r = await h.runAll({ quiet: true });
    assert.equal(r.ok, false); assert.equal(r.code, 'SKIPPED.NOT_CONFIGURED');
    stop();
  }

  // —— 3. 首次（零配置）——
  {
    const q = new Plugin();
    q.app = { vault: { adapter: { exists: async f => f === '_archive/catalog-data.json' } } };
    q.lbPath = x => x; q.settings = { setup: { selected: ['core', 'reader', 'ai_text'] } };
    q.saveSettings = async () => {}; q.notify = () => {};
    const h = homeFactory(OBS, q);
    assert.equal(await h.firstRun(), 'existing-library', '老库：只记一笔');
    assert.deepEqual(q.settings.setup.selected, ['core', 'reader', 'ai_text'], '老库的选择不动');
    assert.ok(q.settings.setup.firstRunAt);
    assert.equal(await h.firstRun(), 'done-before', '记过就不再跑');
    const r = new Plugin();
    r.app = { vault: { adapter: { exists: async () => false } } };
    r.lbPath = x => x; r.settings = { setup: {} }; r.saveSettings = async () => {};
    const told = []; r.notify = m => told.push(m);
    r.running = '别的'; r.busyText = () => '正在别的';   // runAll 遇上占用只提示、不起进程
    const h2 = homeFactory(OBS, r);
    assert.equal(await h2.firstRun(), 'started');
    assert.deepEqual(r.settings.setup.selected, ['core', 'reader', 'dataview', 'ocr'], '新库：轻量版');
    assert.match(told[0], /按轻量版（不要任何 key）自动装好并同步/);
  }

  // —— 4. spawnPy 的 onLine：碎块拼成整行；最后一行没换行也给；onChild 拿到子进程 ——
  {
    const q = new Plugin();
    q.app = { vault: { adapter: { getBasePath: () => 'D:/vault' } } };
    spawnImpl = () => {
      const c = new EventEmitter(); c.pid = 99; c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
      setTimeout(() => {
        c.stdout.emit('data', Buffer.from('{"type":"progress","stage":"sync","done":1,'));
        c.stdout.emit('data', Buffer.from('"total":4}\n{"type":"progress","stage":"sync","done":2,"total":4}\n{"type":"res'));
        c.stdout.emit('data', Buffer.from('ult","ok":true}'));
        c.emit('close', 0);
      }, 0);
      return c;
    };
    const lines = []; let child = null;
    const res = await q.runPy(['-m', 'link_brain', 'setup', 'run'], { onLine: l => lines.push(JSON.parse(l)), onChild: ch => { child = ch; } });
    assert.deepEqual(lines.map(l => l.type + (l.done || '')), ['progress1', 'progress2', 'result'], '整行回调，最后一行没换行也给');
    assert.equal(child.pid, 99);
    assert.equal(res.json.ok, true, '结果照旧是最后一行 JSON');
  }
  // —— 5. 1102：结果 code 分按钮——号的事才「去扫码 / 验证」，读取组件没起来 / 没装给「重试」 ——
  {
    assert.equal(H.resultKind('NEEDS_HUMAN'), 'account');
    assert.equal(H.resultKind('NEEDS_HUMAN.CAPTCHA_REQUIRED'), 'account');
    assert.equal(H.resultKind('TRANSIENT.DISCONNECTED'), 'reader');
    assert.equal(H.resultKind('NEEDS_HUMAN.NOT_INSTALLED'), 'reader');
    assert.equal(H.resultKind(''), ''); assert.equal(H.resultKind('TRANSIENT.STEP_CRASHED'), '');
    const q = new Plugin();
    q.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async () => false, read: async () => { throw new Error('ENOENT'); } } }, workspace: { trigger() {} } };
    q.lbPath = x => x; q.repoRoot = 'D:/repo'; q.settings = { setup: { selected: ['core', 'reader', 'dataview', 'ocr'] } };
    q.saveSettings = async () => {}; q.notify = (m, o = {}) => notices.push({ m, o }); q.log = async () => {};
    q.openSetupPage = s => { q.opened = s; };
    q.homeState = { plan: PLAN };
    let runs = 0;
    spawnImpl = (exe, args) => {
      const c = new EventEmitter(); c.pid = 7; c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
      const ev = o => Buffer.from(JSON.stringify(o) + '\n');
      if (args.includes('plan')) { setTimeout(() => { c.stdout.emit('data', ev(PLAN)); c.emit('close', 0); }, 0); return c; }
      runs++;
      setTimeout(() => {
        c.stdout.emit('data', ev({ type: 'progress', stage: 'login', label: '确认小红书登录', index: 2, count: 7, state: 'failed', text: '读取服务没连上（DISCONNECTED）' }));
        c.stdout.emit('data', ev({ type: 'result', ok: false, code: 'TRANSIENT.DISCONNECTED', message: '读取组件没起来，点重试或看 reader.log：读取服务没连上（DISCONNECTED）', stages: [] }));
        c.emit('close', 1);
      }, 0);
      return c;
    };
    const h = homeFactory(OBS, q);
    const res = await h.runAll();
    assert.equal(res.code, 'TRANSIENT.DISCONNECTED');
    const last = notices.at(-1);
    assert.equal(last.o.actions[0].label, '重试', '读取组件类不引导扫码');
    assert.equal(last.o.kind, 'warn');
    assert.equal(q.opened, undefined);
    q.homeState.run = null;
    last.o.actions[0].run(); await flush(12);
    assert.equal(runs, 2, '「重试」= 再跑一次 setup run');
  }

  // —— 6. 1102：没有 result JSON（崩了 / 被杀）：不把 stderr 弹出去——一句话 + 「打开日志」，traceback 折进「详情」 ——
  {
    const q = new Plugin();
    q.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async () => false, read: async () => { throw new Error('ENOENT'); } } }, workspace: { trigger() {} } };
    q.lbPath = x => x; q.repoRoot = 'D:/repo'; q.settings = { setup: { selected: ['core', 'reader', 'dataview', 'ocr'] } };
    q.saveSettings = async () => {}; q.notify = (m, o = {}) => notices.push({ m, o });
    const logged = []; q.log = async t => logged.push(t);
    let opened = 0; q.openActionLog = () => { opened++; return true; };
    q.homeState = { plan: PLAN };
    spawnImpl = () => {
      const c = new EventEmitter(); c.pid = 8; c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
      setTimeout(() => {
        c.stdout.emit('data', Buffer.from(JSON.stringify({ type: 'progress', stage: 'install', label: '装好要用的组件', index: 1, count: 7, state: 'running', text: '检查中…' }) + '\n'));
        c.stderr.emit('data', Buffer.from('Traceback (most recent call last):\n  File "x.py", line 1\nKeyError: \'boom\'\n'));
        c.emit('close', 1);
      }, 0);
      return c;
    };
    const h = homeFactory(OBS, q);
    const pane = dom.document.createElement('div');
    h.renderRun(pane, {});
    const res = await h.runAll();
    assert.equal(res.message, '安装程序没有返回结果，详情见日志');
    assert.ok(res.noResult && /KeyError/.test(res.detail), 'stderr 尾巴留在 detail 里');
    const last = notices.at(-1);
    assert.equal(last.m, '安装程序没有返回结果，详情见日志', '弹的不是 traceback');
    assert.equal(last.o.actions[0].label, '打开日志');
    last.o.actions[0].run(); assert.equal(opened, 1);
    assert.ok(logged.some(t => /没有返回结果/.test(t) && /KeyError/.test(t)), 'stderr 写进 ob-actions.log');
    await flush(4);
    const fail = pane.querySelector('.lb-fail');
    assert.ok(fail, '结果区用 failBox');
    assert.match(fail.querySelector('.lb-fail-detail pre').textContent, /KeyError: 'boom'/);
    assert.ok(!/Traceback/.test(fail.querySelector('.lb-fail-line').textContent), '一行字里没有 traceback');
    assert.ok([...fail.querySelectorAll('button')].some(b => b.textContent === '打开日志'));
  }

  // —— 7. 1102：Obsidian 关掉后安装没停——重开按 _archive/setup-run.json 续画；pid 死了 = 「上次没跑完，停在 X 步」+「再跑一次」 ——
  {
    const stateFile = { running: true, pid: 4321, started_at: '2026-11-02T10:00:00+1100', updated_at: '2026-11-02T10:01:00+1100', current: 'sync',
      stages: [{ id: 'install', label: '装好要用的组件', state: 'ok', text: '全部就绪' }, { id: 'login', label: '确认小红书登录', state: 'ok', text: '已登录' }], result: null };
    const r1 = H.runFromState(stateFile, true);
    assert.equal(r1.state, 'running'); assert.equal(r1.resumed, true); assert.equal(r1.current, 'sync');
    assert.equal(r1.stages.sync.state, 'running'); assert.equal(r1.stages.install.state, 'ok');
    const r2 = H.runFromState(stateFile, false);
    assert.equal(r2.state, 'done'); assert.equal(r2.result.interrupted, true);
    assert.equal(r2.result.message, '上次没跑完，停在「同步收藏（含 OCR / 识图 / 概要）」');
    const r3 = H.runFromState({ ...stateFile, running: false, current: null, result: { ok: true, message: '都跑完了' } }, false);
    assert.equal(r3.state, 'done'); assert.equal(r3.result.message, '都跑完了');
    assert.equal(H.runFromState(null, true), null);

    // 设置页：文件说 running、pid 活着 → 续画步骤、没有「停止」按钮；文件变成 result → 结束提示
    const files = { '_archive/setup-run.json': JSON.stringify(stateFile) };
    const q = new Plugin();
    const handlers = [];
    q.app = { vault: { adapter: { getBasePath: () => 'D:/vault', exists: async f => f in files, read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; } },
      on: (ev, cb) => { const ref = { ev, cb }; handlers.push(ref); return ref; }, offref: ref => { const i = handlers.indexOf(ref); if (i >= 0) handlers.splice(i, 1); } }, workspace: { trigger() {} } };
    q.lbPath = x => x; q.repoRoot = 'D:/repo'; q.settings = { setup: { selected: ['core', 'reader', 'dataview', 'ocr'] } };
    q.saveSettings = async () => {}; q.notify = (m, o = {}) => notices.push({ m, o }); q.log = async () => {};
    let alive = true; q.pidAlive = pid => { assert.equal(pid, 4321); return alive; };
    q.homeState = { plan: PLAN };
    spawnImpl = () => { throw new Error('续画不起进程'); };
    const h = homeFactory(OBS, q);
    const pane = dom.document.createElement('div');
    const stop = h.renderRun(pane, {});
    await flush(6);
    assert.equal(pane.querySelectorAll('.lb-run-stop').length, 0, '不是本会话起的，停不了');
    assert.match(pane.textContent, /还在后台跑/);
    assert.equal(pane.querySelectorAll('.lb-run-step').length, 3, '两步做完 + 当前一步');
    assert.ok(handlers.length >= 1, '盯着 setup-run.json');
    files['_archive/setup-run.json'] = JSON.stringify({ ...stateFile, running: false, current: null, result: { ok: true, code: '', message: '都跑完了（轻量版）' },
      stages: [...stateFile.stages, { id: 'sync', label: '同步收藏（含 OCR / 识图 / 概要）', state: 'ok', text: '完成' }] });
    for (const hd of [...handlers]) if (hd.ev === 'modify') hd.cb({ path: '_archive/setup-run.json' });
    await flush(8);
    assert.equal(q.homeState.run.state, 'done');
    assert.equal(notices.at(-1).m, '都跑完了（轻量版）');
    assert.equal(handlers.length, 0, '跑完不再盯文件');
    assert.equal(q.homeState.resumeTimer, null);
    assert.match(pane.querySelector('.lb-run-result').textContent, /都跑完了/);
    stop();

    // pid 死了：说停在哪一步，按钮变「再跑一次」
    alive = false;
    files['_archive/setup-run.json'] = JSON.stringify(stateFile);
    q.homeState = { plan: PLAN };
    const pane2 = dom.document.createElement('div');
    const stop2 = h.renderRun(pane2, {});
    await flush(6);
    assert.match(pane2.querySelector('.lb-run-result').textContent, /上次没跑完，停在「同步收藏/);
    assert.equal(pane2.querySelector('.lb-run-go').textContent, '再跑一次');
    assert.equal(handlers.length, 0, '死了就不用盯');
    stop2;
    // 本会话自己在跑时不碰
    q.homeState = { plan: PLAN, run: { state: 'running', stages: {}, result: null } };
    assert.equal((await h.resumeRun()).state, 'running');
    // 跑完了的旧结果不重放
    files['_archive/setup-run.json'] = JSON.stringify({ ...stateFile, running: false, result: { ok: true, message: '旧' } });
    q.homeState = { plan: PLAN };
    assert.equal(await h.resumeRun(), null);
    // 启动（firstRun）也接：记过 firstRunAt 的老用户照样续画
    files['_archive/setup-run.json'] = JSON.stringify(stateFile); alive = true;
    q.homeState = { plan: PLAN }; q.settings.setup.firstRunAt = '2026-10-01T00:00:00Z';
    assert.equal(await h.firstRun(), 'done-before');
    await flush(4);
    assert.equal(q.homeState.run?.state, 'running');
    clearInterval(q.homeState.resumeTimer); q.homeState.resumeTimer = null;
  }

  // —— 8. 1102 main.js：Windows 编码两个环境变量都给；卸载插件不杀正在跑的安装、只说一句 ——
  {
    const q = new Plugin();
    q.app = { vault: { adapter: { getBasePath: () => 'D:/vault' } } };
    const env = q.pyEnv();
    assert.equal(env.PYTHONIOENCODING, 'utf-8'); assert.equal(env.PYTHONUTF8, '1');
    let killed = 0;
    q.runningChild = { pid: 99, kill() { killed++; } }; q.running = '装好并跑完';
    q.killTree = async () => { killed++; };
    const before = notices.length;
    q.onunload();
    assert.equal(killed, 0, 'onunload 不杀 runningChild');
    assert.match(String(notices[before]), /安装在后台继续/);
    assert.equal(q.pidAlive(process.pid), true); assert.equal(q.pidAlive(0), false); assert.equal(q.pidAlive(2147483646), false);
  }
  console.log('PASS home-ui (1009 / 1010 / 1102): light by default, deps, prices next to features, run button (disabled reason while loading) → step marks + result + 去扫码 action, first run (old library untouched / new library light + auto run once), spawnPy onLine whole lines; 1102 reader codes → 重试, no-result → 打开日志 + failBox detail, resume from setup-run.json (alive → continue / dead → 再跑一次), PYTHONUTF8 + onunload keeps the child');
})().catch(e => { console.error(e); process.exitCode = 1; });

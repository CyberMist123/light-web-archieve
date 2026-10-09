// 1009 她的裁决：设置页顶部（home-ui.js）——功能开关 +「一键装好 / 跑完」+ 零配置首次自动跑。
// 断言：
//   1. 纯函数：没选过 = 轻量版；依赖联动；进度事件 → 各步状态；评论补齐那一行；
//   2. 「一键装好 / 跑完」：经 spawnPy（exclusive）跑 `setup run`，stdout 一行一个事件画成各步 ✓ / ⟳ / ✗ + 当前在装的进度条，
//      结果一句话；要人处理（掉登录 / 验证）给「去扫码 / 验证」按钮；
//   3. 首次：老库（已有目录数据）只记一笔、选择不动、不跑；新库 → 选轻量版、自动跑一次；跑过不再跑；
//   4. spawnPy 的 onLine：stdout 被切成碎块也按整行回调，最后一行没换行也给（setup run / install 的进度靠它）。
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
  assert.equal(H.fillLine({ state: 'done', message: '评论都补齐了' }, { ok: true, pending: 0, stuck: 2 }, now), '评论都补齐了（2 篇连着补不上，见问题面板）');
  assert.equal(H.fillLine(null, { ok: true, pending: 5, missing: 70, stuck: 0 }, now), '5 篇的评论还没补齐（共缺 70 条回复）');

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
  const stop = home.renderFeatures(pane, tab);
  await flush(10);
  const go = pane.querySelector('.lb-run-go');
  assert.ok(go && !go.disabled, '功能清单读到后按钮可点');
  go.onclick(); await flush(12);
  const runArgs = runs.find(a => a.includes('run'));
  assert.deepEqual(Array.from(runArgs), ['-m', 'link_brain', 'setup', 'run']);
  assert.deepEqual(Array.from(p.settings.setup.selected), ['core', 'reader', 'dataview', 'ocr'], '跑之前把「没选过」落成轻量版');
  const steps = pane.querySelectorAll('.lb-run-step').map(r => r.textContent);
  assert.deepEqual(steps.map(s => s.slice(0, 1)), ['✓', '✗', '–', '✓'], '各步 ✓ / ✗ / 跳过');
  assert.match(steps[1], /确认小红书登录.*扫码登录/);
  assert.match(pane.querySelector('.lb-run-result').textContent, /先处理小红书/);
  const last = notices.at(-1);
  assert.equal(last.o.actions[0].label, '去扫码 / 验证');
  last.o.actions[0].run(); assert.equal(p.opened, 'status', '去扫码 → 打开设置页顶部账号那一行');
  assert.equal(p.running, null, '跑完放开互斥位');
  stop();

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
  console.log('PASS home-ui (1009): light by default, deps, run events → step marks + result + 去扫码 action, first run (old library untouched / new library light + auto run once), spawnPy onLine whole lines');
})().catch(e => { console.error(e); process.exitCode = 1; });

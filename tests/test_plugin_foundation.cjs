// 批次 D 地基：插件 main.js 的 foundation 段（notify / confirm / showMenu / busyButton / busyText / refreshCatalog / openLightbox 转发）
// + saveSettings 广播 + 问答 tag / onStart 管道 + pyEnv 的 LINK_BRAIN_OBSIDIAN_DIR + DEFAULT_SETTINGS.media + onload 四个挂载点。
// 'obsidian' 换成 tests/_fakeobsidian.cjs（Menu / Modal / Notice 都渲染真结构的假 DOM），child_process 换成假 spawn（不起真进程）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { EventEmitter } = require('events');
const { makeDom, makeWorkspace, ROOT } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
// vm 里造的对象原型不同，深比较用 JSON
const same = (a, b, msg) => assert.equal(JSON.stringify(a), JSON.stringify(b), msg);
const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';
const dom = makeDom();
const notices = [];
const obs = makeObsidian(dom.document, { notices });
const spawned = [];
function fakeSpawn(exe, args, opts) {
  const c = new EventEmitter(); c.pid = 7000 + spawned.length;
  c.stdout = new EventEmitter(); c.stdout.setEncoding = () => {}; c.stderr = new EventEmitter();
  c.stdin = new EventEmitter(); c.stdin.lines = []; c.stdin.write = s => { c.stdin.lines.push(JSON.parse(s)); }; c.stdin.end = () => {};
  c.kill = () => c.emit('close'); spawned.push({ exe, args, opts, child: c }); return c;
}
const attached = [], detached = [];
const stubFactory = name => (obsidian, plugin) => ({ attach() { attached.push([name, obsidian === obs, !!plugin]); }, detach() { detached.push(name); } });
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, Buffer, document: dom.document,
  require: n => n === 'obsidian' ? obs : n === 'child_process' ? { spawn: fakeSpawn }
    : /[\\/](note-actions|note-tools|image-actions|player-ui|index-ui)\.js$/.test(n) ? stubFactory(path.basename(n))
    : /[\\/](remote-ui|media-nav|onboarding-ui)\.js$/.test(n) ? (() => ({ attach() { return true; } }))
    : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8') + '\nmodule.exports.__merge = mergeSettings; module.exports.__ConfirmModal = ConfirmModal;', context);
const Plugin = context.module.exports;

function makePlugin() {
  const workspace = makeWorkspace();
  const triggered = [];
  const trig = workspace.trigger.bind(workspace);
  workspace.trigger = (name, ...a) => { triggered.push(name); trig(name, ...a); };
  const app = { workspace, vault: { configDir: '.obsidian-x', adapter: { getBasePath: () => path.join(path.sep, 'fake-vault'), exists: async () => false, list: async () => ({ folders: [] }) } },
    plugins: { manifests: { dataview: {} }, enabledPlugins: new Set(['dataview']), plugins: { dataview: { settings: { enableDataviewJs: true } } } } };
  const p = new Plugin(app, { id: 'link-brain-actions', dir: PLUGIN_DIR, version: 'test' });
  p.settings = Plugin.__merge({});
  return { p, app, triggered };
}

(async () => {
  // ── notify：默认时长、按钮、常驻 ──
  const { p, app, triggered } = makePlugin();
  let n = p.notify('已保存', { kind: 'ok' });
  assert.equal(n.message, '已保存'); assert.equal(n.timeout, 3000, '成功 3 秒');
  assert.equal(p.notify('没删掉：EPERM', { kind: 'error' }).timeout, 8000, '失败 8 秒');
  assert.equal(p.notify('提醒', { kind: 'warn' }).timeout, 8000);
  assert.equal(p.notify('正在同步…', { ms: 0 }).timeout, 0, 'ms=0 常驻');
  let ran = 0;
  n = p.notify('同步只做了一部分', { kind: 'warn', actions: [{ label: '查看同步记录', run: () => { ran++; } }, { label: '重试', run: () => { ran += 10; } }] });
  assert.equal(n.timeout, 8000, '带按钮的 8 秒');
  assert.deepEqual(n.buttons.map(b => b.label), ['查看同步记录', '重试']);
  assert.ok(n.containerEl.querySelector('.notice-button-container .notice-cta'), 'Notice 自带按钮区（Obsidian 1.14 结构）');
  n.buttons[0].click(); await tick();
  assert.equal(ran, 1, '点按钮调到 run'); assert.equal(n.hidden, true, '点了先收起');
  assert.ok(n.containerEl.classList.contains('lb-notice') && n.containerEl.classList.contains('is-warn'), '提示条带种类 class');
  // run 抛错：再弹一句错误
  n = p.notify('x', { actions: [{ label: '试试', run: () => { throw new Error('没成'); } }] });
  n.buttons[0].click(); await tick(5);
  assert.equal(notices.at(-1).message, '没成'); assert.equal(notices.at(-1).timeout, 8000);

  // ── confirm：Enter = true，Esc / 关窗 = false，danger = 1.14.4 的 setWarning 样子 ──
  let pending = p.confirm({ title: '删除这 3 篇？', body: '会移到回收站。\n\n可以在回收站恢复。', ok: '删除', danger: true });
  let modal = dom.document.body.querySelector('.modal-container .modal.lb-confirm-modal');
  assert.ok(modal, '确认框打开了');
  assert.equal(modal.querySelector('.modal-title').textContent, '删除这 3 篇？');
  assert.deepEqual(modal.querySelectorAll('.lb-confirm-body').map(x => x.textContent), ['会移到回收站。', '可以在回收站恢复。']);
  const yes = modal.querySelectorAll('button').find(b => b.textContent === '删除');
  assert.ok(yes.classList.contains('mod-destructive') && yes.classList.contains('mod-cta'), 'danger → ButtonComponent.setWarning（1.14.4 = mod-destructive + mod-cta）');
  modal.dispatchEvent({ type: 'keydown', key: 'Enter', target: modal, isComposing: true });
  assert.ok(modal.isConnected, '输入法组字中的回车不算');
  modal.dispatchEvent({ type: 'keydown', key: 'Enter', target: modal });
  assert.equal(await pending, true, '回车 = 确定'); assert.equal(modal.isConnected, false);
  pending = p.confirm({ title: '退出登录？' });
  modal = dom.document.body.querySelector('.modal-container .modal.lb-confirm-modal');
  assert.ok(modal.querySelectorAll('button').find(b => b.textContent === '确定').classList.contains('mod-cta'));
  dom.document.dispatchEvent({ type: 'keydown', key: 'Escape' });
  assert.equal(await pending, false, 'Esc = 取消');
  pending = p.confirm({ title: '清空？', cancel: '算了' });
  modal = dom.document.body.querySelector('.modal-container .modal.lb-confirm-modal');
  modal.querySelectorAll('button').find(b => b.textContent === '算了').click();
  assert.equal(await pending, false);
  pending = p.confirm({ title: '关窗？' });
  dom.document.body.querySelector('.modal-container .modal-close-button').click();
  assert.equal(await pending, false, '点右上角关掉 = false');

  // ── showMenu：菜单项映射、定位、menuOpen 延一拍 ──
  let clicked = '';
  const menu = p.showMenu([
    { title: '收藏', icon: 'star', checked: true, onClick: () => { clicked = '收藏'; } },
    { title: '刷新目录', sub: '重新整理分类', icon: 'refresh-cw', onClick() {} },
    { separator: true },
    { title: '删除（移到回收站）', danger: true, onClick: () => { clicked = '删除'; } },
    { title: '导出', disabled: true, onClick: () => { clicked = '导出'; } },
  ], { pageX: 30, pageY: 40, clientX: 30, clientY: 40 });
  assert.equal(obs.Menu.open, menu); assert.ok(menu.dom.isConnected, '渲染成 body > .menu');
  const its = menu.items.filter(i => !i.separator);
  assert.deepEqual(its.map(i => i.title), ['收藏', '刷新目录（重新整理分类）', '删除（移到回收站）', '导出']);
  assert.ok(its[0].dom.classList.contains('mod-checked')); assert.equal(its[0].icon, 'star');
  assert.ok(its[2].dom.classList.contains('is-warning')); assert.ok(its[3].dom.classList.contains('is-disabled'));
  assert.equal(menu.items.filter(i => i.separator).length, 1);
  assert.deepEqual(menu.pos, { x: 30, y: 40 }, '有 pageX：showAtMouseEvent');
  assert.equal(p.menuOpen, true);
  its[3].click(); assert.equal(clicked, '', '禁用项点了没反应');
  its[2].click(); assert.equal(clicked, '删除');
  assert.equal(p.menuOpen, true, '关掉的那一拍里还是 true（同一次按键别当成菜单外的 Esc）');
  await tick(); assert.equal(p.menuOpen, false, '下一拍变回 false');
  const btn = dom.document.body.createEl('button'); btn._rect = { left: 100, top: 20, width: 40, height: 30 };
  const m2 = p.showMenu([{ title: 'a', onClick() {} }], { currentTarget: btn });
  assert.deepEqual({ ...m2.pos }, { x: 100, y: 50 }, '没有坐标：按发起元素的左下角 showAtPosition');
  dom.document.dispatchEvent({ type: 'keydown', key: 'Escape' });
  assert.equal(m2.shown, false, 'Esc 关菜单'); await tick(); assert.equal(p.menuOpen, false);
  // 键盘（Enter / 空格）触发的 click：Chromium 给的是 PointerEvent，detail=0、坐标 0,0 → 按发起元素左下角，不落到窗口左上角
  const mk = p.showMenu([{ title: 'a', onClick() {} }], { type: 'click', detail: 0, pageX: 0, pageY: 0, clientX: 0, clientY: 0, currentTarget: btn });
  assert.deepEqual({ ...mk.pos }, { x: 100, y: 50 }, '键盘打开：菜单在按钮下面');
  mk.hide(); await tick();
  // Shift+F10 / 菜单键的 contextmenu 带元素坐标：照指针
  const mc = p.showMenu([{ title: 'a', onClick() {} }], { type: 'contextmenu', detail: 0, pageX: 222, pageY: 218, clientX: 222, clientY: 218, currentTarget: btn });
  assert.deepEqual({ ...mc.pos }, { x: 222, y: 218 }); mc.hide(); await tick();
  // 调用方对返回的菜单再设 onHide：两个都跑，menuOpen 照样复位（1.14.4 的 onHide 只有一个槽位）
  const mh = p.showMenu([{ title: 'a', onClick() {} }], { currentTarget: btn });
  let userHid = 0; mh.onHide(() => { userHid++; });
  assert.equal(p.menuOpen, true);
  mh.hide(); await tick();
  assert.equal(userHid, 1, '调用方的 onHide 照样调到'); assert.equal(p.menuOpen, false, 'menuOpen 没被卡在 true');
  // 没有菜单项（只有分隔线）：Obsidian 不显示，menuOpen 不设
  const me = p.showMenu([{ separator: true }, null], { currentTarget: btn });
  assert.equal(me.shown, false); assert.equal(p.menuOpen, false, '空菜单不把 menuOpen 卡住');
  // show 抛错：不设 menuOpen
  const origShow = obs.Menu.prototype.showAtPosition;
  obs.Menu.prototype.showAtPosition = function () { throw new Error('坏了'); };
  const ce0 = console.error; console.error = () => {};
  p.showMenu([{ title: 'a', onClick() {} }], { currentTarget: btn });
  console.error = ce0; obs.Menu.prototype.showAtPosition = origShow;
  assert.equal(p.menuOpen, false, 'show 抛错不把 menuOpen 卡住');

  // ── busyButton / busyText ──
  const b = dom.document.body.createEl('button', { text: '导入' }); b.createEl('span', { cls: 'svg-icon' });
  const done = p.busyButton(b, '导入中…');
  assert.equal(b.disabled, true); assert.equal(b.textContent, '导入中…'); assert.ok(b.classList.contains('is-busy'));
  done(); assert.equal(b.disabled, false); assert.equal(b.textContent, '导入'); assert.ok(b.querySelector('.svg-icon'));
  p.running = '同步收藏'; p.runningProgress = '3/40';
  assert.equal(p.busyText(), '正在同步收藏（3/40），完成后再点，或在底部状态栏停止');
  p.running = null; p.runningProgress = null;
  assert.equal(p.busyText('导出'), '正在导出，完成后再点，或在底部状态栏停止');

  // ── refreshCatalog / openLightbox 转发 / saveSettings 广播 ──
  const runs = []; p.run = async (...a) => { runs.push(a); return { code: 0 }; };
  await p.refreshCatalog();
  same(runs[0], [['-m', 'link_brain', 'catalog'], '刷新目录', true]);
  assert.equal(p.openLightbox([{ src: 'a' }], 0), null, '没有 media-nav：返回 null');
  p.mediaNav = { skipped: true, openLightbox: () => 'x' }; assert.equal(p.openLightbox([], 0), null, 'media-nav 被跳过：null');
  const seen = []; p.mediaNav = { openLightbox: (...a) => { seen.push(a); return { close() {} }; } };
  const opts = { caption: i => '来源1 · 图' + (i + 1) };
  assert.ok(p.openLightbox([{ src: 'a' }, { src: 'b' }], 1, opts)); assert.deepEqual(seen[0], [[{ src: 'a' }, { src: 'b' }], 1, opts]);
  p.saveData = async () => {};
  await p.saveSettings(); assert.ok(triggered.includes('link-brain:settings'), 'saveSettings 广播 link-brain:settings');

  // ── 问答管道：onStart 拿到 id；stop(tag) 只停这个 tag ──
  p.repoRoot = ROOT; p.killTree = async () => [];
  const ids = [];
  // onStart 回调时请求已经写给 worker 了（复审：先回调后写，onStart 里马上取消会让 cancel 排在请求前面，worker 不认、8 秒后整个被 killTree）
  const written = id => spawned.at(-1).child.stdin.lines.some(l => l.id === id && !l.type);
  const a1 = p.answerArchive({ question: '设置页试问', tag: 'setup', onStart: id => ids.push(['setup', id, written(id)]) });
  const a2 = p.answerArchive({ question: '问收藏', tag: 'chat', onStart: id => ids.push(['chat', id, written(id)]) });
  const a3 = p.answerArchive({ question: '老调用不带 tag' });
  const worker = spawned.at(-1).child;
  assert.deepEqual(ids.map(x => x[0]), ['setup', 'chat']); assert.ok(ids.every(x => typeof x[1] === 'string' && x[1]));
  assert.ok(ids.every(x => x[2] === true), 'onStart 在请求写出之后才回调');
  assert.deepEqual(worker.stdin.lines.map(l => l.question), ['设置页试问', '问收藏', '老调用不带 tag']);
  assert.ok(worker.stdin.lines.every(l => !('tag' in l) && !('onStart' in l)), '请求体不变（tag 只在插件这头）');
  assert.equal(p.stopArchiveAnswer('setup'), 1, '只停 setup 那一问');
  assert.deepEqual(worker.stdin.lines.filter(l => l.type === 'cancel').map(l => l.id), [ids[0][1]]);
  assert.equal(p.stopArchiveAnswer('nope'), 0);
  for (const id of [ids[0][1]]) worker.stdout.emit('data', JSON.stringify({ id, type: 'result', result: { status: 'cancelled', markdown: '' } }) + '\n');
  assert.equal((await a1).status, 'cancelled');
  assert.equal(p.stopArchiveAnswer(), 2, '不带 tag：全停（兼容）');
  for (const l of worker.stdin.lines.filter(l => l.type === 'cancel').slice(1)) worker.stdout.emit('data', JSON.stringify({ id: l.id, type: 'result', result: { status: 'cancelled', markdown: '' } }) + '\n');
  assert.equal((await a2).status, 'cancelled'); assert.equal((await a3).status, 'cancelled');
  p.unloading = true; worker.emit('close');

  // ── pyEnv / DEFAULT_SETTINGS.media ──
  const env = p.pyEnv({ X: '1' });
  assert.equal(env.LINK_BRAIN_OBSIDIAN_DIR, path.join(path.sep, 'fake-vault', '.obsidian-x'), 'pyEnv 带 Obsidian 真正的配置目录');
  assert.equal(env.X, '1');
  assert.deepEqual({ ...Plugin.__merge({}).media }, { loop: false, playlistOrder: 'newest' });
  assert.deepEqual({ ...Plugin.__merge({ media: { loop: true } }).media }, { loop: true, playlistOrder: 'newest' }, '存过的设置合并，缺的键用默认');

  // ── onload：五个挂载点（批次 D 四个 + 10-10 索引树 index-ui.js）都 attach，没起任何进程 ──
  const before = spawned.length;
  const q = makePlugin();
  q.p.loadData = async () => null; q.p.saveData = async () => {};
  // require 缓存：四个文件加载前先删缓存（只重载插件也拿到新部署的文件）；别的模块的缓存不动
  const base = path.join(path.sep, 'fake-vault', PLUGIN_DIR);
  const mountFiles = ['note-actions.js', 'note-tools.js', 'image-actions.js', 'player-ui.js', 'index-ui.js'].map(f => path.join(base, f));
  context.require.cache = Object.fromEntries([...mountFiles.map(f => [f, 'old']), ['other.js', 'keep']]);
  context.require.resolve = x => x;
  await q.p.onload();
  assert.deepEqual(Object.keys(context.require.cache), ['other.js'], '四个挂载点的 require 缓存先删掉再加载');
  delete context.require.cache; delete context.require.resolve;
  assert.deepEqual(attached.map(a => a[0]), ['note-actions.js', 'note-tools.js', 'image-actions.js', 'player-ui.js', 'index-ui.js'], '依次 require + attach');
  assert.ok(attached.every(a => a[1] && a[2]), '工厂拿到 (obsidian, plugin)');
  for (const k of ['noteActions', 'noteTools', 'imageActions', 'playerUI', 'indexUI']) assert.equal(typeof q.p[k]?.attach, 'function', 'this.' + k + ' 挂上了');
  assert.equal(spawned.length, before, 'onload 不起进程');
  // onunload：有 detach 的挂载点各调一次
  q.p.onunload();
  assert.deepEqual(detached, ['note-actions.js', 'note-tools.js', 'image-actions.js', 'player-ui.js', 'index-ui.js'], 'onunload 调各挂载点的 detach');
  // 某个文件挂不上：别的照常
  attached.length = 0;
  const badRequire = context.require;
  context.require = n => (/note-tools\.js$/.test(n) ? (() => { throw new Error('坏了'); })() : badRequire(n));
  const errs = []; const ce = console.error; console.error = (...a) => errs.push(a.join(' '));
  const r = makePlugin(); r.p.loadData = async () => null; r.p.saveData = async () => {};
  await r.p.onload();
  console.error = ce; context.require = badRequire;
  assert.deepEqual(attached.map(a => a[0]), ['note-actions.js', 'image-actions.js', 'player-ui.js', 'index-ui.js'], '一个坏了不拦别的');
  assert.ok(errs.some(e => e.includes('note-tools.js 没加载上')));
  // 四个桩文件本身：工厂形状对
  for (const f of ['note-actions.js', 'note-tools.js', 'image-actions.js', 'player-ui.js']) {
    const inst = require(path.join(ROOT, PLUGIN_DIR, f))(obs, {});
    assert.equal(typeof inst.attach, 'function', f);
  }
  console.log('PASS plugin foundation: notify (3s/8s/0, Notice.addButton actions run + hide, error re-notify), ConfirmModal (Enter / Esc / close / danger), showMenu (item mapping, pointer vs anchor incl. keyboard click detail=0 → under the button, caller onHide chained so menuOpen resets, empty / throwing menus leave menuOpen false, menuOpen false one tick after hide), busyButton / busyText, refreshCatalog args, openLightbox forward, saveSettings → link-brain:settings, answerArchive onStart (after the request is written) + stopArchiveAnswer(tag), pyEnv LINK_BRAIN_OBSIDIAN_DIR, settings.media defaults, onload attaches 4 mount points without spawning (require cache dropped first; onunload calls detach)');
})().catch(e => { console.error(e); process.exit(1); });

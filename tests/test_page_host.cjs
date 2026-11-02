// 1102：插件自己执行 ```lb-page 块（obsidian-plugins/link-brain-actions/page-host.js），不再要 Dataview。
// 假 Obsidian 的 registerMarkdownCodeBlockProcessor + MarkdownRenderChild，验证：
//   找仓根（仓挂在别的库的子目录里）、读 _archive/<脚本>、同一版本只编译一次；容器和全局约定（dv.container / component /
//   current() / page() / el()、app、__lbCodeVer、块参数 + 以 Path 结尾的补仓根前缀）；真 lb-page-lib 的 mountHost / keep 照用；
//   重跑（component.render、库里 .md 变了 2.5 秒防抖）；脚本抛错 / 没脚本 / 块写错时 failBox 不炸；块卸载 / 插件卸载时清理；
//   lb-page-core 和 link_brain/assets/page-bootstrap.js 逐字一致（唯一源）；旧 dataviewjs 引导用同一段核心照样能跑。
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { makeDom, makeApp, asset, ROOT } = require('./_fakedom.cjs');

const HOST_FILE = path.join(ROOT, 'obsidian-plugins', 'link-brain-actions', 'page-host.js');
const pageHost = require(HOST_FILE);

// 假 Obsidian：Component（后进先出清理）+ MarkdownRenderChild + MarkdownRenderer.render
function fakeObsidian() {
  class Component {
    constructor() { this._loaded = false; this._cbs = []; this._children = []; }
    load() { if (this._loaded) return; this._loaded = true; for (const c of this._children) c.load(); }
    unload() { if (!this._loaded) return; this._loaded = false; for (const c of this._children.splice(0)) c.unload(); while (this._cbs.length) { try { this._cbs.pop()(); } catch {} } }
    addChild(c) { this._children.push(c); if (this._loaded) c.load(); return c; }
    removeChild(c) { this._children = this._children.filter(x => x !== c); c.unload(); return c; }
    register(fn) { this._cbs.push(fn); }
    registerEvent(ref) { this.register(() => ref && ref.e && ref.e.offref && ref.e.offref(ref)); }
    registerDomEvent(t, type, fn) { t.addEventListener(type, fn); this.register(() => t.removeEventListener(type, fn)); }
  }
  class MarkdownRenderChild extends Component { constructor(el) { super(); this.containerEl = el; } }
  const rendered = [];
  const MarkdownRenderer = { render(app, md, el) { rendered.push(md); el.textContent = md; return Promise.resolve(); } };
  return { Component, MarkdownRenderChild, MarkdownRenderer, rendered };
}

// 一个阅读视图的段落：section > 容器（Obsidian 给处理器的 el，class block-language-lb-page）
function setup(files, { pagePath = '目录.md', frontmatter = {} } = {}) {
  const dom = makeDom();
  const { app, V } = makeApp({ files, frontmatter });
  const obs = fakeObsidian();
  const processors = {};
  const plugin = { app, registerMarkdownCodeBlockProcessor(lang, fn) { processors[lang] = fn; }, neutralizeMarkdown: t => t };
  const host = pageHost(obs, plugin);
  const section = dom.document.body.createEl('div', { cls: 'el-pre' });
  const mkEl = () => section.createEl('div', { cls: 'block-language-lb-page' });
  const owner = new obs.Component(); owner.load();   // 这一段 Markdown 的渲染组件（ctx.addChild 挂在它下面）
  const ctx = { sourcePath: pagePath, addChild: c => owner.addChild(c) };
  const run = async (source, el = mkEl()) => ({ el, entry: await host.process(source, el, ctx) });
  return { dom, app, V, obs, plugin, host, processors, section, mkEl, owner, ctx, run };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const realTimeout = setTimeout;
const flush = () => new Promise(r => realTimeout(r, 0));   // 用真的：有一条用例把 setTimeout 换成手动计时器

test('lb-page-core 和 page-bootstrap.js 逐字一致（唯一源；python tools/sync_tokens.py 拷）', () => {
  const rx = /\/\/ lb-page-core:begin[\s\S]*?\/\/ lb-page-core:end/;
  const src = asset('page-bootstrap.js').match(rx);
  const copy = fs.readFileSync(HOST_FILE, 'utf8').match(rx);
  assert.ok(src && copy, '两边都要有 lb-page-core 标记');
  assert.strictEqual(copy[0], src[0], 'page-host.js 里的 lb-page-core 和 page-bootstrap.js 不一致：跑 python tools/sync_tokens.py');
});

test('attach 注册 lb-page 处理器；插件没有 registerMarkdownCodeBlockProcessor 时不炸', () => {
  const S = setup({});
  assert.strictEqual(S.host.attach(), true);
  assert.strictEqual(typeof S.processors['lb-page'], 'function');
  assert.strictEqual(S.host.attach(), false, '重复 attach 不再注册一次');
  const bare = pageHost(fakeObsidian(), { app: S.app });
  assert.strictEqual(bare.attach(), false);
});

test('parseBlock：脚本名 / script: / 参数 JSON / 注释 / 写错', () => {
  const p = pageHost.parseBlock;
  assert.deepStrictEqual(p('catalog-page.js\n'), { script: 'catalog-page.js', params: {}, error: '' });
  assert.deepStrictEqual(p('# 注释\nscript: wiki-page.js'), { script: 'wiki-page.js', params: {}, error: '' });
  const a = p('annotate-view.js\nitemId: "xhs-1"\nnotePath: "_archive/x/1/notes.json"\nn: 3\nraw: 不是 json');
  assert.deepStrictEqual(a.params, { itemId: 'xhs-1', notePath: '_archive/x/1/notes.json', n: 3, raw: '不是 json' });
  assert.ok(p('').error);
  assert.ok(p('../evil.js').error, '不许带路径');
  assert.ok(p('a/b.js').error);
  assert.ok(p('catalog-page.js\napp: 1').error, '保留名');
  assert.ok(p('catalog-page.js\n第二个脚本.js').error);
});

test('找仓根（挂在子目录里）→ 读脚本 → 容器和全局约定都给到；同一版本只读一次', async () => {
  const script = `globalThis.__seen = { dv: !!dv, container: dv.container, comp: typeof dv.component.register, current: dv.current(), app: app === globalThis.__app,
    page: dv.page('Lib/Inner/a.md'), ver: dv.__lbCodeVer, itemId: typeof itemId === 'undefined' ? null : itemId, notePath: typeof notePath === 'undefined' ? null : notePath };
    dv.container.createEl('p', { text: '画了' });`;
  const S = setup({ 'Lib/Inner/_archive/test-page.js': script, 'Lib/Inner/a.md': '' }, { pagePath: 'Lib/Inner/Pages/目录.md' });
  S.app.metadataCache.frontmatter['Lib/Inner/a.md'] = { tags: ['x'] };
  globalThis.__app = S.app;
  const { el, entry } = await S.run('test-page.js\nitemId: "xhs-1"\nnotePath: "_archive/xhs/1/notes.json"');
  const seen = globalThis.__seen;
  assert.ok(entry && !entry.lastError, String(entry && entry.lastError));
  assert.strictEqual(seen.container, el, 'dv.container 就是 Obsidian 给的那一块');
  assert.strictEqual(seen.comp, 'function');
  assert.deepStrictEqual(seen.current, { file: { path: 'Lib/Inner/Pages/目录.md', folder: 'Lib/Inner/Pages', name: '目录.md' } });
  assert.strictEqual(seen.app, true, 'app 是插件的 app');
  assert.deepStrictEqual(seen.page, { tags: ['x'], file: { path: 'Lib/Inner/a.md' } });
  assert.match(seen.ver, /^\d+:\d+$/, '__lbCodeVer = mtime:size');
  assert.strictEqual(seen.itemId, 'xhs-1');
  assert.strictEqual(seen.notePath, 'Lib/Inner/_archive/xhs/1/notes.json', '以 Path 结尾的参数补仓根前缀');
  assert.strictEqual(el.querySelector('p').textContent, '画了');
  assert.strictEqual(S.V.reads['Lib/Inner/_archive/test-page.js'], 1);
  await S.run('test-page.js\nitemId: "xhs-1"\nnotePath: "_archive/xhs/1/notes.json"');
  assert.strictEqual(S.V.reads['Lib/Inner/_archive/test-page.js'], 1, '同一版本复用编译好的函数，不再读');
  S.V.set('Lib/Inner/_archive/test-page.js', script + '\n// v2');
  await S.run('test-page.js\nitemId: "xhs-1"\nnotePath: "_archive/xhs/1/notes.json"');
  assert.strictEqual(S.V.reads['Lib/Inner/_archive/test-page.js'], 2, '脚本换了版本就重读');
});

test('真 lb-page-lib：mountHost / keep 照用，块卸载时 host 摘掉', async () => {
  const code = asset('lb-page-lib.js') + `
const LB = lbPageLib(dv, app, 'catalog');
if (await LB.reuseDom()) return;
const host = LB.mountHost('lb-test-host');
host.createEl('div', { cls: 'lb-test-body', text: '页面' });
LB.keep(host, { version: 'v1', update: async () => {} });
globalThis.__runs = (globalThis.__runs || 0) + 1;`;
  globalThis.__runs = 0;
  const S = setup({ '_archive/catalog-page.js': code });
  const { el, entry } = await S.run('catalog-page.js');
  assert.ok(!entry.lastError, String(entry.lastError));
  const host = el.nextElementSibling;
  assert.ok(host && host.classList.contains('lb-page-host'), '页面挂在容器后面的 host 上（§5.9）');
  assert.strictEqual(host.dataset.lbRole, 'catalog');
  assert.strictEqual(globalThis.__runs, 1);
  // 重跑（和 Dataview 的 render 一样：清空容器再跑）→ reuseDom 原样挂回，不重建
  await entry.child.render();
  assert.strictEqual(globalThis.__runs, 1, '版本没变：旧 DOM 挂回，不重建');
  assert.strictEqual(el.nextElementSibling, host);
  // 块被 Obsidian 摘掉（这一段重画 / 关页）→ component 卸载 → 页面 onUnload 摘 host；插件的 live 表里也没了
  S.owner.removeChild(entry.child);
  assert.ok(!host.parentNode, '卸载时 host 摘掉');
  assert.strictEqual(S.host.live.size, 0);
});

test('脚本抛错 / 没有脚本 / 块写错：只在这一块里说一句，不往外抛', async () => {
  const S = setup({ '_archive/boom.js': 'throw new Error("炸了");' });
  const r1 = await S.run('boom.js');
  assert.match(r1.el.querySelector('.lb-page-fail').textContent, /页面出错了（炸了）/);
  assert.match(String(r1.entry.lastError), /炸了/);
  const r2 = await S.run('missing-page.js');
  assert.match(r2.el.querySelector('.lb-page-fail').textContent, /页面脚本没读到/);
  assert.ok(r2.entry.lastError);
  const r3 = await S.run('../../etc/passwd');
  assert.strictEqual(r3.entry, null);
  assert.match(r3.el.querySelector('.lb-page-fail').textContent, /页面块写错了/);
  const r4 = await S.run('_archive/x.js'.replace('_archive/', '') + '\n???');
  assert.match(r4.el.querySelector('.lb-page-fail').textContent, /看不懂这一行/);
  // 编译不过（语法错）也一样
  S.V.set('_archive/syntax.js', 'const = ;');
  const r5 = await S.run('syntax.js');
  assert.match(r5.el.querySelector('.lb-page-fail').textContent, /页面脚本没读到/);
  // 经注册的处理器走（插件真正的入口）也不抛
  S.host.attach();
  const el = S.mkEl();
  await S.processors['lb-page']('boom.js', el, S.ctx);
  assert.ok(el.querySelector('.lb-page-fail'));
});

test('库里 .md 变了 → 2.5 秒后重跑看得见的块；json 变了、块卸载后不跑', async () => {
  const realSet = global.setTimeout, realClear = global.clearTimeout;
  const timers = [];
  global.setTimeout = (fn, ms) => { const t = { fn, ms, done: false }; timers.push(t); return t; };
  global.clearTimeout = t => { if (t) t.done = true; };
  const fire = async () => { for (const t of timers.splice(0)) if (!t.done) { t.done = true; await t.fn(); } await flush(); };
  try {
    globalThis.__count = 0;
    const S = setup({ '_archive/count.js': 'globalThis.__count++; dv.container.createEl("i");' });
    const { el, entry } = await S.run('count.js');
    assert.strictEqual(globalThis.__count, 1);
    S.V.set('_archive/catalog-data.json', '{}');
    assert.strictEqual(timers.filter(t => !t.done).length, 0, '非 .md 不触发重跑');
    S.V.set('笔记.md', 'a');
    S.V.set('笔记.md', 'b');
    const live = timers.filter(t => !t.done);
    assert.strictEqual(live.length, 1, '防抖：连着两次只留一个计时器');
    assert.strictEqual(live[0].ms, pageHost.RERUN_MS);
    await fire();
    assert.strictEqual(globalThis.__count, 2, '重跑了一次');
    assert.strictEqual(el.querySelectorAll('i').length, 1, '重跑前清空容器（和 Dataview 一样）');
    // 别处要求立刻重跑（刷新目录之后）
    S.app.workspace.trigger('link-brain:refresh-pages');
    await flush(); await flush();
    assert.strictEqual(globalThis.__count, 3);
    // 卸载后：监听摘掉，计时器清掉
    S.V.set('笔记.md', 'c');
    S.owner.removeChild(entry.child);
    await fire();
    S.V.set('笔记.md', 'd');
    await fire();
    assert.strictEqual(globalThis.__count, 3, '卸载后不再重跑');
    assert.strictEqual((S.V.handlers.modify || []).length, 0, 'vault 监听都摘了');
  } finally { global.setTimeout = realSet; global.clearTimeout = realClear; }
});

test('插件卸载（detach）：已画出的块逐个卸掉', async () => {
  const code = asset('lb-page-lib.js') + `
const LB = lbPageLib(dv, app, 'chat');
const host = LB.mountHost('x'); LB.keep(host, { version: 'v' });`;
  const S = setup({ '_archive/chat-page.js': code });
  const a = await S.run('chat-page.js');
  const hostA = a.el.nextElementSibling;
  assert.ok(hostA && hostA.classList.contains('lb-page-host'));
  assert.strictEqual(S.host.live.size, 1);
  S.host.detach();
  assert.strictEqual(S.host.live.size, 0);
  assert.ok(!hostA.parentNode, '插件卸载时页面 host 摘掉');
});

test('dv.el / paragraph：字符串按 Markdown 渲染进容器（兜底提示用）', async () => {
  const S = setup({ '_archive/p.js': 'dv.paragraph("**粗**"); dv.el("div", "x", { cls: "k" });' });
  const { el } = await S.run('p.js');
  assert.strictEqual(el.querySelector('p').textContent, '**粗**');
  assert.ok(el.querySelector('div.k'));
  assert.deepStrictEqual(S.obs.rendered, ['**粗**', 'x']);
});

test('旧 dataviewjs 引导（page-bootstrap.js）用同一段核心照样能跑', async () => {
  const dom = makeDom();
  const { app } = makeApp({ files: { 'Lib/_archive/old.js': 'globalThis.__old = { ver: dv.__lbCodeVer, app: !!app };' } });
  const container = dom.document.body.createEl('div');
  const dv = { container, current: () => ({ file: { folder: 'Lib/Pages' } }), paragraph: t => container.createEl('p', { text: t }) };
  const code = asset('page-bootstrap.js').replace(/__LB_SCRIPT__/g, 'old.js');
  await new (Object.getPrototypeOf(async function () {}).constructor)('dv', 'app', code)(dv, app);
  assert.ok(globalThis.__old && /^\d+:\d+$/.test(globalThis.__old.ver) && globalThis.__old.app);
  const code2 = asset('page-bootstrap.js').replace(/__LB_SCRIPT__/g, 'nope.js');
  await new (Object.getPrototypeOf(async function () {}).constructor)('dv', 'app', code2)(dv, app);
  assert.match(container.querySelector('p').textContent, /页面脚本没读到/);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log('ok  ' + name); }
    catch (e) { failed++; console.log('FAIL ' + name + '\n' + (e && e.stack || e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} 过`);
  process.exit(failed ? 1 : 0);
})();

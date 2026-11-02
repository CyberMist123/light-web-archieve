// 1102：同一个插件手机上也装（manifest isDesktopOnly:false）。手机上没有 child_process / fs / path / os / electron，
// 也不能按路径 require 同目录的其他文件——所以：
//   ① main.js（构建产物）在「Node 模块一 require 就抛错」的假环境里能加载完，顶层不碰 Node 模块；
//   ② 手机上 onload 不抛错、注册了 lb-page 代码块处理器、把 note.css（经 vault.adapter 读）注入 head；
//      不加命令、不加设置页、不加状态栏 / 功能区图标、不起进程；onunload 拆掉处理器画的块和样式；
//   ③ 处理器是打进 main.js 的那份（LBPageHost），真能把 _archive 下的页面脚本跑起来；
//   ④ 页面在手机上看不到插件（LB.provider() 是 null）→ 走原来那条手机只读路；桌面上照旧拿得到插件；
//   ⑤ main.js 是 main.src.js 的最新构建（tools/build_plugin.cjs --check；没装 esbuild 就只核「main.src.js 原样在里面」）。
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { makeDom, makeApp, asset, ROOT } = require('./_fakedom.cjs');

const DIR = path.join(ROOT, 'obsidian-plugins', 'link-brain-actions');
const MAIN = fs.readFileSync(path.join(DIR, 'main.js'), 'utf8');
const NODE_ONLY = new Set(['child_process', 'fs', 'path', 'os', 'electron', 'crypto', 'http', 'https', 'net']);

// 假 Obsidian（只给手机上用得到的）
function fakeObsidian() {
  class Component {
    constructor() { this._loaded = false; this._cbs = []; this._children = []; }
    load() { if (this._loaded) return; this._loaded = true; for (const c of this._children) c.load(); }
    unload() { if (!this._loaded) return; this._loaded = false; for (const c of this._children.splice(0)) c.unload(); while (this._cbs.length) { try { this._cbs.pop()(); } catch {} } }
    addChild(c) { this._children.push(c); if (this._loaded) c.load(); return c; }
    register(fn) { this._cbs.push(fn); }
    registerEvent(ref) { this.register(() => ref && ref.e && ref.e.offref && ref.e.offref(ref)); }
  }
  class MarkdownRenderChild extends Component { constructor(el) { super(); this.containerEl = el; } }
  const calls = [];
  class Plugin extends Component {
    constructor() { super(); this.processors = {}; }
    registerMarkdownCodeBlockProcessor(lang, fn) { calls.push(['processor', lang]); this.processors[lang] = fn; }
    addCommand(c) { calls.push(['command', c.id]); }
    addRibbonIcon() { calls.push(['ribbon']); return {}; }
    addSettingTab() { calls.push(['settingTab']); }
    addStatusBarItem() { calls.push(['statusBar']); return { addClass() {}, setText() {} }; }
    registerDomEvent() { calls.push(['domEvent']); }
    loadData() { calls.push(['loadData']); return Promise.resolve(null); }
    saveData() { calls.push(['saveData']); return Promise.resolve(); }
  }
  class Stub {}
  return { Plugin, Component, MarkdownRenderChild, Notice: Stub, TFile: Stub, Modal: Stub, PluginSettingTab: Stub, Setting: Stub, MarkdownView: Stub,
    Platform: { isMobile: true, isMobileApp: true }, requestUrl: async () => { throw new Error('不联网'); }, calls };
}

// ① 在没有 Node 模块的 vm 里加载 main.js
function loadMain(obs, { mobile = true, D = null } = {}) {
  const required = [];
  const ctx = {
    module: { exports: {} }, console, setTimeout, clearTimeout, setInterval, clearInterval, URL, Promise, document: D,
    window: {},
    require: name => {
      required.push(name);
      if (name === 'obsidian') return obs;
      if (mobile && (NODE_ONLY.has(name) || name.startsWith('.') || name.startsWith('/'))) throw new Error(`手机上没有模块：${name}`);
      return require(name);
    },
  };
  if (!mobile) ctx.process = process;
  vm.createContext(ctx);
  vm.runInContext(MAIN, ctx, { filename: 'main.js' });
  return { Plugin: ctx.module.exports, required, ctx };
}

(async () => {
  // ⑤ 构建产物是最新的
  let esbuild = null; try { esbuild = require('esbuild'); } catch {}
  const src = fs.readFileSync(path.join(DIR, 'main.src.js'), 'utf8').replace(/\r\n/g, '\n').trimEnd();
  assert.ok(MAIN.includes(src), 'main.js 里原样带着 main.src.js（改了源要 npm run build）');
  assert.ok(/var LBPageHost = \(\(\) => \{/.test(MAIN), 'page-host.js 由 esbuild 打进 main.js（全局名 LBPageHost）');
  assert.ok(!/^"use strict";/.test(MAIN), '打包段的 use strict 不提到文件头（不改变 main.src.js 的模式）');
  if (esbuild) assert.strictEqual(MAIN.replace(/\r\n/g, '\n'), require(path.join(ROOT, 'tools', 'build_plugin.cjs')).build(), 'main.js 不是最新构建：npm run build');
  else console.log('（没装 esbuild：只核了 main.src.js 原样在 main.js 里；CI 上 npm run build:check 全核）');
  const manifest = JSON.parse(fs.readFileSync(path.join(DIR, 'manifest.json'), 'utf8'));
  assert.strictEqual(manifest.isDesktopOnly, false, '手机上也能装');

  // ①② 手机上加载 + onload
  const dom = makeDom();
  const D = dom.document;
  const noteCss = fs.readFileSync(path.join(DIR, 'note.css'), 'utf8');
  const pageScript = asset('lb-page-lib.js') + `
const LB = lbPageLib(dv, app, 'catalog');
globalThis.__mobileSeen = { mobile: LB.mobile, provider: LB.provider(), need: LB.need('syncNow') };
dv.container.createEl('p', { text: '目录页（手机只读）' });`;
  const pluginDir = '.obsidian/plugins/link-brain-actions';
  const { app, V } = makeApp({ isMobile: true, files: { '_archive/catalog-page.js': pageScript, [pluginDir + '/note.css']: noteCss } });
  const obs = fakeObsidian();
  const { Plugin, required, ctx } = loadMain(obs, { mobile: true, D });
  assert.deepStrictEqual(required.filter(n => n !== 'obsidian'), [], '加载 main.js 时没 require 任何 Node 模块 / 同目录文件');
  const p = new Plugin();
  p.app = app;
  p.manifest = { id: 'link-brain-actions', dir: pluginDir, version: manifest.version };
  app.plugins.plugins['link-brain-actions'] = p;
  await p.onload();   // 抛错这一行就红
  assert.strictEqual(typeof p.processors['lb-page'], 'function', '手机上注册了 lb-page 处理器');
  const kinds = obs.calls.map(c => c[0]);
  assert.deepStrictEqual(kinds, ['processor'], '手机上只注册处理器：没有命令、设置页、状态栏、功能区图标、也不读写 data.json');
  assert.deepStrictEqual(required.filter(n => n !== 'obsidian'), [], 'onload 也没碰 Node 模块');
  assert.strictEqual(p.mobileMode, true);
  const style = D.getElementById('lb-note-style');
  assert.ok(style && style.textContent === noteCss, '笔记样式经 vault.adapter 读 note.css 注入 head');
  assert.strictEqual(V.reads[pluginDir + '/note.css'], 1);

  // ③④ 打进去的处理器真能跑页面；页面在手机上看不到插件
  const said = [];
  app.plugins.plugins['link-brain-actions'].notify = (m) => said.push(m);
  const section = D.body.createEl('div', { cls: 'el-pre' });
  const el = section.createEl('div', { cls: 'block-language-lb-page' });
  const owner = new obs.Component(); owner.load();
  await p.processors['lb-page']('catalog-page.js', el, { sourcePath: '目录.md', addChild: c => owner.addChild(c) });
  await new Promise(r => setTimeout(r, 0));
  assert.ok(!el.querySelector('.lb-page-fail'), '页面没报错：' + (el.querySelector('.lb-page-fail') || {}).textContent);
  assert.strictEqual(el.querySelector('p').textContent, '目录页（手机只读）');
  const seen = ctx.__mobileSeen;   // 页面脚本在 vm 那边的全局里跑（处理器是打进 main.js 的那份）
  assert.strictEqual(seen.mobile, true);
  assert.strictEqual(seen.provider, null, '手机上 LB.provider() 是 null：页面走原来的手机只读路');
  assert.strictEqual(seen.need, null, 'LB.need 在手机上不给插件（只说一句手机只读）');

  // ② onunload：块卸掉、样式拿掉，不碰 Node
  p.onunload();
  assert.ok(!D.getElementById('lb-note-style'), '卸载时样式拿掉');
  assert.strictEqual(p.pageHost.live.size, 0, '处理器画的块都卸了');
  assert.deepStrictEqual(required.filter(n => n !== 'obsidian'), [], 'onunload 也没碰 Node 模块');

  // ④ 桌面上页面照旧拿得到插件（provider 不是 null）
  {
    const dom2 = makeDom();
    const { app: app2 } = makeApp({ isMobile: false, plugin: { id: 'stub' } });
    const container = dom2.document.body.createEl('div');
    const dv = { container, current: () => ({ file: { folder: '' } }), component: { register() {} } };
    const LB = new Function('dv', 'app', asset('lb-page-lib.js') + '\nreturn lbPageLib(dv, app, "catalog");')(dv, app2);
    assert.ok(LB.provider() && LB.provider().id === 'stub', '桌面上 LB.provider() 照旧是插件');
  }

  // ① 桌面上 Node 模块是用到时才加载：模块加载完还没 require 过任何 Node 模块
  {
    const { required: req2 } = loadMain(fakeObsidian(), { mobile: false });
    // 桌面上加载时只为「下载文件夹」默认值碰 path / os；child_process / fs / electron 都是用到时才 require
    assert.deepStrictEqual(req2.filter(n => !['obsidian', 'path', 'os'].includes(n)), [], '桌面上 child_process / fs / electron 懒加载');
  }
  console.log('PASS plugin mobile 1102: main.js 是 main.src.js + esbuild 打包的 page-host 的最新构建；没有 Node 模块的假环境里加载 / onload / onunload 都不抛、不 require；手机上只注册 lb-page 处理器 + 注入 note.css（不加命令 / 设置页 / 状态栏）；打进去的处理器能跑页面；手机上 LB.provider() 为 null（只读路），桌面照旧');
})().catch(e => { console.error(e); process.exit(1); });

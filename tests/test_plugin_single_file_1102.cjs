// 1102 单文件：BRAT 只下载 main.js / manifest.json / styles.css。把这三个文件单独拷进临时插件目录，
// 在「require 任何同目录文件（相对路径 / 绝对路径）都报错」的假环境里，桌面端 onload 照样把全部功能加载起来：
// 命令、设置页、onload 挂的各个界面模块（远程阅读、图片导航、去提示气泡、五个挂载点），以及 13 个按需取的界面模块；
// 整个过程不按路径 require 任何文件、不起进程，也没有「没加载上」的报错。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), os = require('os'), path = require('path'), vm = require('vm');
const { makeDom, makeWorkspace, ROOT } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const SRC_DIR = path.join(ROOT, 'obsidian-plugins', 'link-brain-actions');
const SHIPPED = ['main.js', 'manifest.json', 'styles.css'];

(async () => {
  // BRAT 装出来的样子：库里插件目录只有三个文件
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-brat-'));
  const pluginDir = '.obsidian/plugins/link-brain-actions';
  fs.mkdirSync(path.join(vault, pluginDir), { recursive: true });
  for (const f of SHIPPED) fs.copyFileSync(path.join(SRC_DIR, f), path.join(vault, pluginDir, f));
  assert.deepEqual(fs.readdirSync(path.join(vault, pluginDir)).sort(), [...SHIPPED].sort());

  const dom = makeDom();
  const obs = makeObsidian(dom.document, { notices: [] });
  const required = [], badRequires = [], spawned = [];
  const ctx = {
    module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, console, Buffer, URL,
    document: dom.document, window: { confirm: () => false },
    MutationObserver: class { observe() {} disconnect() {} takeRecords() { return []; } },   // 浏览器自带（图片导航用）
    require: n => {
      required.push(n);
      if (n === 'obsidian') return obs;
      if (n === 'electron' || n === '@electron/remote') return { shell: { openPath: async () => '', openExternal: async () => {}, showItemInFolder() {} }, webUtils: {} };   // 桌面 Obsidian 才有
      if (n === 'child_process') return { spawn(...a) { spawned.push(a); throw new Error('测试里不许起进程'); } };
      if (n.startsWith('.') || path.isAbsolute(n)) { badRequires.push(n); throw new Error(`插件目录里没有这个文件：${n}`); }
      return require(n);
    },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(vault, pluginDir, 'main.js'), 'utf8'), ctx, { filename: 'main.js' });
  const Plugin = ctx.module.exports;
  assert.equal(typeof Plugin, 'function', 'main.js 导出插件类');

  const app = { workspace: makeWorkspace(), vault: { configDir: '.obsidian', adapter: { getBasePath: () => vault, exists: async () => false, list: async () => ({ folders: [] }), read: async () => { throw new Error('ENOENT'); } } },
    plugins: { manifests: {}, enabledPlugins: new Set(), plugins: {} } };
  const manifest = JSON.parse(fs.readFileSync(path.join(vault, pluginDir, 'manifest.json'), 'utf8'));
  const p = new Plugin(app, { ...manifest, dir: pluginDir });
  p.loadData = async () => null; p.saveData = async () => {};
  const errs = []; const ce = console.error;
  console.error = (...a) => errs.push(a.map(x => (x && x.message) || String(x)).join(' '));
  try {
    await p.onload();
    // onload 挂的模块
    for (const k of ['remoteUI', 'mediaNav', 'noTooltip', 'noteActions', 'noteTools', 'imageActions', 'playerUI', 'indexUI']) assert.ok(p[k], `onload 挂上了 this.${k}`);
    // 按需取的模块：都能从打包里拿到
    const lazy = { scheduleUI: 'object', libraryUI: 'object', onboardingUI: 'object', settingsV6: 'object', lbTheme: 'object', providerIcons: 'object', settingsPages: 'object',
      usageUI: 'object', skillsUI: 'object', homeUI: 'object', backendInstall: 'object', problemsUI: 'object', reportUI: 'object' };
    for (const [k, t] of Object.entries(lazy)) {
      const m = p[k]();
      assert.ok(m && (typeof m === t || typeof m === 'function'), `plugin.${k}() 从 main.js 里拿到模块`);
    }
    assert.ok(Plugin.noteCssText().includes('.lb-note'), 'note.css 文本打进了 main.js');
  } finally { console.error = ce; }
  assert.ok(p.commands.length >= 10, `注册了命令（${p.commands.length} 条）`);
  assert.equal(p.settingTabs.length, 1, '加了设置页');
  assert.deepEqual(badRequires, [], '没按路径 require 任何同目录文件');
  assert.ok(!required.some(n => n.startsWith('.') || path.isAbsolute(n)));
  assert.equal(spawned.length, 0, 'onload 不起进程');
  const notLoaded = errs.filter(e => /没加载上|没挂上/.test(e));
  assert.deepEqual(notLoaded, [], '没有模块加载失败');
  p.unloading = true; try { p.onunload(); } catch {}
  fs.rmSync(vault, { recursive: true, force: true });
  console.log(`PASS plugin single file 1102: only ${SHIPPED.join(' / ')} in the plugin dir, path requires throw → desktop onload still loads ${p.commands.length} commands, settings tab, 8 onload modules and 13 lazy UI modules from main.js; no path require, no spawn`);
})().catch(e => { console.error(e); process.exit(1); });

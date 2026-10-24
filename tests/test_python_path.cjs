// P0（BUGS-1024 根因）：插件拉起 Python 只认一个解释器——设置「Python 路径」（data.json 的 pythonPath）。
// 断言：
//   1. pickPython：用户配了用配的；没配时程序目录下有 .venv（Windows .venv/Scripts/python.exe，其他 .venv/bin/python）用它；都没有退回 python；
//   2. 仓库模式下所有起进程（runPy / spawnPy）和写给外部客户端的 MCP 命令（mcpArgv）都用这个解释器；
//   3. 旧设置没有 pythonPath：合并后为空串 = 按默认找，不报错。
// 不起真进程（CONVENTIONS §7.5）：child_process 是记账的假 spawn。
'use strict';
const fs = require('fs'), os = require('os'), path = require('path'), vm = require('vm'), assert = require('assert/strict');
const { EventEmitter } = require('events');

const ROOT = path.resolve(__dirname, '..');
const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';
const obsidianStub = { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Setting: class {}, Notice: class {}, Menu: class {}, TFile: class {}, MarkdownView: class {} };

const spawned = [];
function fakeSpawn(exe, args, opts) {
  const c = new EventEmitter();
  c.pid = 7000 + spawned.length;
  c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.stdout.setEncoding = () => {};
  c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
  spawned.push({ exe, args, opts });
  setTimeout(() => { c.stdout.emit('data', Buffer.from('{"ok":true}\n')); c.emit('close', 0); }, 0);
  return c;
}
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, Buffer, navigator: {}, window: {},
  require: n => n === 'obsidian' ? obsidianStub : n === 'child_process' ? { spawn: fakeSpawn } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8') + '\nmodule.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-py-'));
const repo = path.join(tmp, 'repo'), repoVault = path.join(repo, 'vault');
fs.mkdirSync(path.join(repo, 'link_brain'), { recursive: true }); fs.writeFileSync(path.join(repo, 'link_brain', '__init__.py'), '');
fs.mkdirSync(path.join(repoVault, '_archive'), { recursive: true });

function makePlugin(base, saved = {}) {
  const p = new Plugin();
  p.manifest = { id: 'link-brain-actions', version: '0.2.0', dir: '.obsidian/plugins/link-brain-actions' };
  p.app = { vault: { adapter: { getBasePath: () => base, exists: async () => false, list: async () => ({ folders: [] }) }, configDir: '.obsidian' }, workspace: {} };
  p.settings = Plugin.__merge(saved);
  return p;
}

(async () => {
  // ── 1. 纯函数 ──
  assert.equal(typeof Plugin.pickPython, 'function', '要导出 pickPython 给单测');
  const winVenv = path.join('/repo', '.venv', 'Scripts', 'python.exe'), nixVenv = path.join('/repo', '.venv', 'bin', 'python');
  const has = set => f => set.has(f);
  assert.equal(Plugin.pickPython({ root: '/repo', configured: '', platform: 'win32', exists: has(new Set([winVenv])) }), winVenv, '有 .venv 用它');
  assert.equal(Plugin.pickPython({ root: '/repo', configured: '', platform: 'linux', exists: has(new Set([nixVenv])) }), nixVenv, '非 Windows 看 .venv/bin/python');
  assert.equal(Plugin.pickPython({ root: '/repo', configured: '', platform: 'win32', exists: () => false }), 'python', '没 .venv 退回 python');
  assert.equal(Plugin.pickPython({ root: null, configured: undefined, platform: 'win32', exists: () => true }), 'python', '没有程序目录也退回 python');
  assert.equal(Plugin.pickPython({ root: '/repo', configured: '  D:/py311/python.exe ', platform: 'win32', exists: has(new Set([winVenv])) }), 'D:/py311/python.exe', '用户配了用配的（去首尾空白）');
  assert.equal(Plugin.pickPython({ root: '/repo', configured: '"C:/Program Files/Py/python.exe"', platform: 'win32', exists: () => false }), 'C:/Program Files/Py/python.exe', '带引号的路径去掉引号');

  const isRepo = r => r === '/repo';
  let b = Plugin.pickBackend({ candidates: ['/repo'], isRepo, which: () => null, python: 'D:/py311/python.exe' });
  assert.equal(b.mode, 'repo'); assert.equal(b.exe, 'D:/py311/python.exe'); assert.match(b.command, /py311.*-m link_brain/);

  // ── 2. 旧设置没有 pythonPath ──
  assert.equal(Plugin.__merge({}).pythonPath, '', '默认空 = 按默认找');

  // ── 3. 真走 locateCollection：没 .venv → python；有 .venv → 它；配了 → 配的。起进程和 MCP 命令一致 ──
  let p = makePlugin(repoVault);
  await p.locateCollection();
  assert.equal(p.backend.mode, 'repo'); assert.equal(p.backend.exe, 'python');
  assert.equal(p.mcpArgv()[0], 'python');

  const venvPy = process.platform === 'win32' ? path.join(repo, '.venv', 'Scripts', 'python.exe') : path.join(repo, '.venv', 'bin', 'python');
  fs.mkdirSync(path.dirname(venvPy), { recursive: true }); fs.writeFileSync(venvPy, '');
  p = makePlugin(repoVault);
  await p.locateCollection();
  const realVenv = path.join(fs.realpathSync.native(repo), path.relative(repo, venvPy));
  assert.equal(p.backend.exe, realVenv, '程序目录下有 .venv 就用它');
  spawned.length = 0;
  const r = await p.runPy(['-m', 'link_brain', 'catalog']);
  assert.equal(r.code, 0);
  assert.equal(spawned[0].exe, realVenv, 'runPy 起的就是 .venv 的 python');
  assert.deepEqual([...p.mcpArgv()], [realVenv, '-m', 'link_brain', 'mcp'], '写给外部客户端的 MCP 命令同一个解释器');

  p = makePlugin(repoVault, { pythonPath: 'D:/py311/python.exe' });
  await p.locateCollection();
  assert.equal(p.backend.exe, 'D:/py311/python.exe', '配了用配的');
  assert.equal(p.mcpArgv()[0], 'D:/py311/python.exe');
  spawned.length = 0;
  await p.spawnPy(['-m', 'link_brain', 'doctor']);
  assert.equal(spawned[0].exe, 'D:/py311/python.exe');

  // 没走过 onload（单测 / 早期调用）：照旧 python
  const bare = makePlugin(repoVault);
  assert.equal(bare.currentBackend().exe, 'python');

  fs.rmSync(tmp, { recursive: true, force: true });
  console.log('ok test_python_path');
})().catch(e => { console.error(e); process.exit(1); });

// 1009（别人查出的 bug）：「停止同步」那一步记「手动停止」的调用漏了 '-m','link_brain'——仓库模式（作者本机）下
// 起的是 `python synclog stop --by-user`，直接报错。现在照插件统一入口 spawnPy 的写法补上。不起真进程（假 child_process）。
'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict'), { EventEmitter } = require('events');

const spawned = [];
function fakeSpawn(exe, args, opts) {
  const c = new EventEmitter();
  c.pid = 2000 + spawned.length;
  c.stdout = new EventEmitter(); c.stderr = new EventEmitter();
  c.stdin = new EventEmitter(); c.stdin.write = () => {}; c.stdin.end = () => {};
  c.kill = () => setTimeout(() => c.emit('close', null), 0);
  spawned.push({ exe, args, opts, child: c });
  const isSync = args.includes('sync-favorites');
  if (!isSync) setTimeout(() => { c.stdout.emit('data', Buffer.from('{"ok":true,"message":"已记下"}\n')); c.emit('close', 0); }, 0);
  return c;
}
const notices = [];
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, Buffer,
  require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Notice: class { constructor(m) { notices.push(m); } } }
    : n === 'child_process' ? { spawn: fakeSpawn } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
const Plugin = context.module.exports;

(async () => {
  const p = new Plugin(); p.repoRoot = 'D:/repo';
  p.app = { vault: { adapter: { stat: async () => null, append: async () => {}, exists: async () => false, read: async () => '', write: async () => {} } }, workspace: { trigger() {} } };
  p.lbPath = x => x;
  p.notify = m => notices.push(m);
  // 结束掉正在跑的同步：interruptRunning 用替身（不杀真进程），重点看后面那条「记下手动停止」的命令行
  p.interruptRunning = async () => { p.runningChild.emit('close', 1); return true; };
  const pending = p.spawnPy(['-m', 'link_brain', 'sync-favorites', '--limit', '0'], { exclusive: true, label: '同步收藏' });
  assert.equal(p.running, '同步收藏');
  assert.equal(await p.stopRunning(), true);
  await pending;
  const stop = spawned.find(s => s.args.includes('synclog'));
  assert.ok(stop, '停止后要记一笔「手动停止」');
  assert.equal(stop.exe, 'python');
  assert.deepEqual(Array.from(stop.args), ['-m', 'link_brain', 'synclog', 'stop', '--by-user'], '仓库模式：python -m link_brain synclog …');
  assert.equal(stop.opts.cwd, 'D:/repo');
  assert.ok(notices.some(m => String(m).includes('已停止「同步收藏」')));
  // 后端命令模式（uv 装的 link-brain）：去掉 -m link_brain，接在命令后面
  spawned.length = 0;
  p.backend = { mode: 'command', exe: 'C:/bin/link-brain.exe', prefix: [], cwd: null, command: 'link-brain' };
  const pending2 = p.spawnPy(['-m', 'link_brain', 'sync-favorites'], { exclusive: true, label: '同步收藏' });
  await p.stopRunning(); await pending2;
  const stop2 = spawned.find(s => s.args.includes('synclog'));
  assert.equal(stop2.exe, 'C:/bin/link-brain.exe');
  assert.deepEqual(Array.from(stop2.args), ['synclog', 'stop', '--by-user']);
  console.log('PASS stop sync: synclog stop goes through spawnPy with -m link_brain (repo) / backend prefix (command mode)');
})().catch(e => { console.error(e); process.exit(1); });

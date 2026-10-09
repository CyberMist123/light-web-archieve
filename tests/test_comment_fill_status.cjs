// 1009：后台补评论的进度（_archive/comments-fill-status.json）→ 底部状态栏一行。
// 断言：在跑显示「⟳ 补评论 · 已补 x/y 篇」；等验证 / 掉登录标「⚠ 补评论暂停 · 等你处理」（点了开问题入口）；
// 让夜跑时说「让夜跑先跑」；做完 / 停了 / 10 分钟没刷新（进程没了）都不显示。不起真进程。
'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');

const OBS = { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Setting: class {}, Notice: class {}, Menu: class {} };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, console, URL,
  require: n => n === 'obsidian' ? OBS : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
const line = context.module.exports.commentFillLine;

const now = Date.parse('2026-10-10T01:00:00+11:00');
const iso = ms => new Date(ms).toISOString();

{
  const r = line({ state: 'running', done: 3, total: 197, updated_at: iso(now - 30000), message: '正在补评论 · 已补齐 3/197 篇' }, now);
  assert.equal(r.text, '⟳ 补评论 · 3/197 篇');
  assert.equal(r.human, false);
  assert.match(r.title, /已补齐 3\/197/);
}
{
  const r = line({ state: 'waiting', wait_code: 'CAPTCHA_REQUIRED', done: 3, total: 197, updated_at: iso(now - 60000), message: '补评论暂停 · 小红书要安全验证' }, now);
  assert.equal(r.text, '⚠ 补评论暂停 · 等你处理');
  assert.equal(r.human, true);
}
{
  const r = line({ state: 'paused', wait_code: 'NIGHTLY', done: 3, total: 197, updated_at: iso(now - 60000) }, now);
  assert.equal(r.text, '⏸ 补评论 · 让夜跑先跑');
}
{
  const r = line({ state: 'waiting', wait_code: 'COOLING', done: 190, total: 197, updated_at: iso(now - 60000) }, now);
  assert.equal(r.text, '⏸ 补评论 · 190/197 篇');
}
// 不显示：做完、停了、10 分钟没刷新、没有文件
assert.equal(line({ state: 'done', updated_at: iso(now) }, now), null);
assert.equal(line({ state: 'stopped', updated_at: iso(now) }, now), null);
assert.equal(line({ state: 'running', updated_at: iso(now - 11 * 60000) }, now), null);
assert.equal(line(null, now), null);
console.log('test_comment_fill_status: ok');

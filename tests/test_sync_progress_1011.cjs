// 1011：收藏同步真进度（sync-status.json 的 live，Python favorites._Live 写）→ 状态栏一截 + 目录页标题下两行细进度条。
// 断言：今天 X/上限、库里 a/b（还差 n 篇）、正在抓的标题、歇 N 秒按 next_at 倒数、约几点抓完；超过 15 分钟没刷新不出；
// 同步完 10 分钟内目录页一行「同步完了 · 新收 N 篇」，之后收起；目录页跟着 sync-status.json 的文件事件实时换，不重建整页。不起真进程。
'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const OBS = { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Setting: class {}, Notice: class {}, Menu: class {} };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, console, URL,
  require: n => n === 'obsidian' ? OBS : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
const { syncProgressView: view, renderSyncProgress: render } = context.module.exports;

const now = Date.parse('2026-10-11T22:00:00+11:00');
const iso = ms => new Date(ms).toISOString();
const live = (more = {}) => ({ phase: 'fetching', phase_text: '抓取中', today_new: 35, daily_limit: 150, this_run_new: 3,
  archived: 650, favorites_total: 1246, remaining: 596, title: '悉尼咖啡地图', eta_at: iso(now + 3 * 3600000), ...more });
const running = (lv, at = now - 20000) => ({ state: 'running', updated_at: iso(at), live: lv });

// ── 纯函数 ──
{
  const v = view(running(live()), now);
  assert.equal(v.running, true);
  assert.equal(v.today, '今天 35/150');
  assert.equal(v.lib, '库里 650/1246（还差 596 篇）');
  assert.equal(v.title, '悉尼咖啡地图');
  assert.equal(v.phase, '抓取中');
  assert.equal(v.resting, false);
  assert.ok(Math.abs(v.pct - 35 / 150) < 1e-9);
  assert.match(v.eta, /^约 (明天 )?\d\d:\d\d 抓完今天的$/);
  assert.equal(v.short, '今天 35/150 · 抓取中');
  assert.match(v.tip, /这一趟新收 3 篇/);
  assert.match(v.tip, /正在抓：《悉尼咖啡地图》/);
}
{ // 歇着：按 next_at 倒数；到点了还没新消息 = 「马上抓下一篇」
  const st = running(live({ phase: 'resting', phase_text: '歇 77 秒', rest_s: 77, next_at: iso(now + 77000) }));
  assert.equal(view(st, now).phase, '歇 77 秒');
  assert.equal(view(st, now).resting, true);
  assert.equal(view(st, now + 30500).phase, '歇 47 秒');
  const late = view(st, now + 80000);
  assert.equal(late.resting, false);
  assert.equal(late.phase, '马上抓下一篇');
}
{ // 不限额度（0）：不写「/0」，细条按库里几篇走
  const v = view(running(live({ daily_limit: 0, today_new: 4 })), now);
  assert.equal(v.today, '今天 4 篇');
  assert.ok(Math.abs(v.pct - 650 / 1246) < 1e-9);
  assert.match(v.eta, /抓完$/);
}
{ // 缺数不编：没有库里总数就不出那一截
  const v = view(running(live({ archived: null, favorites_total: null, remaining: null })), now);
  assert.equal(v.lib, '');
}
// 不出：没有 live（老后端）、15 分钟没刷新、不是在跑；刚同步完 10 分钟内给一行「同步完了」
assert.equal(view({ state: 'running', updated_at: iso(now) }, now), null);
assert.equal(view(running(live(), now - 16 * 60000), now), null);
assert.equal(view(null, now), null);
assert.deepEqual(JSON.parse(JSON.stringify(view({ state: 'ready', updated_at: iso(now - 60000), new: 3, deferred: 40 }, now))),
  { running: false, done: true, text: '同步完了 · 新收 3 篇 · 还剩 40 篇明天继续' });
assert.equal(view({ state: 'ready', updated_at: iso(now - 11 * 60000), new: 3 }, now), null);
assert.equal(view({ state: 'failed', updated_at: iso(now), new: 3 }, now), null);

// ── 画出来 ──
{
  const dom = makeDom();
  const el = dom.document.createElement('div');
  render(el, view(running(live()), now));
  assert.equal(el.hidden, false);
  assert.equal(el.querySelector('.lb-syncprog-today').textContent, '今天 35/150');
  assert.equal(el.querySelector('.lb-syncprog-lib').textContent, '库里 650/1246（还差 596 篇）');
  assert.equal(el.querySelector('.lb-syncprog-title').textContent, '《悉尼咖啡地图》');
  assert.equal(el.querySelector('.lb-syncprog-fill').style.width, '23.3%');
  assert.equal(el.querySelectorAll('.lb-syncprog-line').length, 2);
  // 状态栏那一截：一行，不带标题和库里
  render(el, view(running(live({ phase: 'resting', next_at: iso(now + 77000) })), now), { compact: true });
  assert.ok(el.classList.contains('is-compact'));
  assert.equal(el.querySelector('.lb-syncprog-lib'), null);
  assert.equal(el.querySelector('.lb-syncprog-phase').textContent, '歇 77 秒');
  assert.ok(el.querySelector('.lb-syncprog-phase').classList.contains('is-resting'));
  render(el, null);
  assert.equal(el.hidden, true);
  assert.equal(el.children.length, 0);
}

// ── 状态栏：「⟳ 同步收藏」后面跟一截（今天 X/上限 + 细条 + 歇 N 秒），悬停看库里 / 正在抓哪篇；收尾后收起 ──
{
  const { makeObsidian } = require('./_fakeobsidian.cjs');
  const dom = makeDom();
  const ctx = { module: { exports: {} }, URL, process, console, setTimeout, clearTimeout, setInterval, clearInterval, document: dom.document,
    require: n => n === 'obsidian' ? makeObsidian(dom.document, { notices: [] }) : n === 'child_process' ? { spawn() { throw new Error('不许 spawn'); } } : require(n) };
  vm.runInNewContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), ctx);
  const Plugin = ctx.module.exports;
  const plugin = new Plugin({ workspace: makeWorkspace() }, {});
  plugin.taskStatusEl = dom.document.createElement('div');
  const t = Date.now();
  plugin.externalSync = running(live({ phase: 'resting', next_at: iso(t + 77000), eta_at: iso(t + 3600000) }), t - 1000);
  plugin.taskChanged();
  const el = plugin.taskStatusEl;
  assert.equal(el.hidden, false);
  assert.match(el.textContent, /^⟳ 同步收藏今天 35\/150歇 7[67] 秒$/, el.textContent);   // 带 live 的不再叫「夜跑同步」
  assert.ok(el.querySelector('.lb-syncprog.is-compact .lb-syncprog-bar'));
  assert.match(el.title, /库里 650\/1246（还差 596 篇）/);
  assert.match(el.title, /命令行 \/ 计划任务在跑/);
  assert.ok(plugin.syncTick, '歇着时每秒重画倒计时');
  // 插件自己在跑别的任务：不出同步细条
  plugin.running = '刷新目录'; plugin.taskChanged();
  assert.equal(el.querySelector('.lb-syncprog-bar'), null);
  assert.equal(plugin.syncTick, null);
  // 插件自己点的同步：照样出细条
  plugin.running = '同步收藏'; plugin.externalSync = running(live(), t - 1000); plugin.taskChanged();
  assert.equal(el.querySelector('.lb-syncprog-today').textContent, '今天 35/150');
  // 同步完：状态栏收起
  plugin.running = null; plugin.externalSync = { state: 'ready', updated_at: iso(t), new: 2 }; plugin.taskChanged();
  assert.equal(el.hidden, true);
  clearInterval(plugin.syncTick);
}

// ── 目录页：跟着 sync-status.json 的文件事件实时换 ──
(async () => {
  const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
  const DATA = '_archive/catalog-data.json', SYNC = '_archive/sync-status.json';
  const t = Date.now();
  const st = (lv, more = {}) => JSON.stringify({ state: 'running', updated_at: iso(t), live: lv, ...more });
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: iso(t), pinyin_chars: {}, aliases: [], cats_order: [], cats: [], topics: [], items: [
    { id: 'a', title: '一篇', tags: [], cats: [], topics: [], summary: '', search_fields: { body: '一篇' }, note: 'Web/a.md', notes_path: '', cover: '', attachment: 'none', starred: false }] }),
  [SYNC]: st(live({ eta_at: iso(t + 3600000) })) });
  const handlers = {};
  V.vault.on = (name, fn) => { (handlers[name] = handlers[name] || []).push(fn); return { name, fn }; };
  const fire = (name, p) => { for (const fn of handlers[name] || []) fn({ path: p }); };
  const plugin = { settings: {}, running: null, syncProgressView: (s, n) => view(s, n ?? Date.now()), renderSyncProgress: render, refreshProblemSummary: async () => null };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  delete globalThis.__lbState;
  const dom = makeDom();
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js') });
  await A.run(); await tick(20);
  const q = s => A.section.querySelector(s);
  const wrap = q('.lbc-wrap');
  const box = q('.lbc-syncprog');
  assert.ok(box, '标题下有进度块');
  assert.equal(box.hidden, false);
  assert.equal(q('.lbc-syncprog .lb-syncprog-today').textContent, '今天 35/150');
  assert.equal(q('.lbc-syncprog .lb-syncprog-lib').textContent, '库里 650/1246（还差 596 篇）');
  assert.equal(q('.lbc-syncing').textContent, '· 同步中', '有细条时「同步中」不再挤一句');
  assert.match(q('.lbc-syncing').title, /库里 650\/1246/);

  // 存好一篇 → 开始歇：数跟着变、倒计时出现
  V.set(SYNC, st(live({ phase: 'resting', today_new: 36, archived: 651, remaining: 595, next_at: iso(Date.now() + 77000) })));
  fire('modify', SYNC); await tick(20);
  assert.equal(q('.lbc-syncprog .lb-syncprog-today').textContent, '今天 36/150');
  assert.match(q('.lbc-syncprog .lb-syncprog-phase').textContent, /^歇 7[67] 秒$/);
  assert.equal(q('.lbc-wrap'), wrap, '整页没重建');

  // 收尾：record(finished) 重写状态、live 没了 → 一行「同步完了」
  V.set(SYNC, JSON.stringify({ state: 'ready', updated_at: iso(Date.now()), new: 2, deferred: 0, message: '收藏同步完成' }));
  fire('modify', SYNC); await tick(20);
  assert.equal(q('.lbc-syncprog .lb-syncprog-done').textContent, '同步完了 · 新收 2 篇');
  assert.equal(q('.lbc-syncprog .lb-syncprog-bar'), null);
  assert.equal(q('.lbc-syncing').hidden, true);

  // 很久以前的完成：不出
  V.set(SYNC, JSON.stringify({ state: 'ready', updated_at: iso(Date.now() - 3600000), new: 2 }));
  fire('modify', SYNC); await tick(20);
  assert.equal(q('.lbc-syncprog').hidden, true);
  A.component?.unload?.();
  console.log('ok test_sync_progress_1011');
})().catch(e => { console.error(e); process.exit(1); });

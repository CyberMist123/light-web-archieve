// 批次 D · L1 C3 / CM2：插件 starNotes（目录页单星和批量收藏都走它）与 exportArchiveBundle 的提示文案。
// - 参数拼接、--off、每 200 个一批；每个 ok 的 id 发一次 'link-brain:star'；
// - 只有一批都拿不到 JSON 才 throw，错误文字就是原因本身（不出现「收藏失败：收藏失败」）；
// - 只有一批时把后端报回的 catalog_stat 带回（页面 LB.data.adopt 的 written）；
// - 导出成功的提示带相对仓根的路径（CM2：页面不再另报一条）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const notices = [];
const obsidianMock = { Plugin: class {}, Modal: class {}, Notice: class { constructor(m) { notices.push(String(m)); } }, TFile: class {},
  PluginSettingTab: class { constructor(app, plugin) { this.app = app; this.plugin = plugin; } }, Setting: class {}, requestUrl: async () => ({}), MarkdownRenderer: { render: async () => {} } };
const shown = [];
const context = { module: { exports: {} }, URL, require: name => name === 'obsidian' ? obsidianMock
  : name === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } }
  : name === 'electron' ? { shell: { showItemInFolder: p => shown.push(p) } } : require(name) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
const Plugin = context.module.exports;

(async () => {
  const mk = () => {
    const p = new Plugin();
    p.triggered = [];
    p.app = { workspace: { trigger: (name, ...a) => p.triggered.push([name, ...a]) }, vault: { adapter: { getBasePath: () => '/vault' } } };
    return p;
  };
  const res = json => ({ code: json && json.ok ? 0 : 1, json, out: JSON.stringify(json), err: '', all: '', timedOut: false });

  // ① 参数拼接 + --off；一批的 catalog_stat 带回
  {
    const p = mk(); const spawned = [];
    p.spawnPy = async args => { spawned.push(args); const ids = args.slice(4).filter(a => a !== '--off');
      return res({ ok: true, results: ids.map(id => ({ item_id: id, status: 'ok', starred: !args.includes('--off'), error: '' })), catalog_patched: true, catalog_stat: { mtime: 5, size: 9 } }); };
    const r = await p.starNotes(['a', 'b', 'a', ''], false);
    assert.deepEqual(JSON.parse(JSON.stringify(spawned)), [['-m', 'link_brain', 'note', 'star', 'a', 'b', '--off']], '去重、去空、带 --off');
    assert.equal(r.ok, true); assert.equal(r.done, 2); assert.equal(r.failed, 0);
    assert.equal(r.catalog_patched, true); assert.deepEqual(JSON.parse(JSON.stringify(r.catalog_stat)), { mtime: 5, size: 9 });
    assert.deepEqual(JSON.parse(JSON.stringify(p.triggered)), [['link-brain:star', 'a', false], ['link-brain:star', 'b', false]]);
  }
  // ② 450 个 id 分 3 批；每个 ok 的都 trigger；部分失败照样返回逐条结果；多批时不带 catalog_stat
  {
    const p = mk(); const sizes = [];
    p.spawnPy = async args => { const ids = args.slice(4); sizes.push(ids.length);
      return res({ ok: false, results: ids.map(id => ({ item_id: id, status: id === 'id7' ? 'missing' : 'ok', starred: true, error: id === 'id7' ? '库里没有这一篇' : '' })), catalog_patched: true, catalog_stat: { mtime: 1, size: 1 } }); };
    const ids = Array.from({ length: 450 }, (_, i) => 'id' + i);
    const r = await p.starNotes(ids, true);
    assert.deepEqual(sizes, [200, 200, 50]);
    assert.equal(r.results.length, 450); assert.equal(r.done, 449); assert.equal(r.failed, 1); assert.equal(r.ok, false);
    assert.equal(p.triggered.length, 449);
    assert.equal(r.catalog_stat, null, '多批：中间版本对不上，不带 written');
    assert.equal(r.results.find(x => x.item_id === 'id7').error, '库里没有这一篇');
  }
  // ③ 一批都拿不到 JSON → throw，原因本身，不加「收藏失败：」前缀
  {
    const p = mk();
    p.spawnPy = async () => ({ code: 3, json: null, out: '', err: 'Traceback\nPermissionError: EBUSY catalog-data.json', all: '', timedOut: false });
    let err = null; try { await p.starNotes(['x'], true); } catch (e) { err = e; }
    assert.ok(err, '拿不到 JSON 要 throw');
    assert.ok(!/收藏失败/.test(err.message), '不加「收藏失败：」前缀：' + err.message);
    assert.ok(/EBUSY/.test(err.message), '原因本身：' + err.message);
    // 多批里只有一批坏了：不 throw，那一批逐条记失败（带原因）
    let n = 0;
    p.spawnPy = async args => (++n === 2 ? { code: 3, json: null, out: '', err: 'disk full', all: '', timedOut: false }
      : res({ ok: true, results: args.slice(4).map(id => ({ item_id: id, status: 'ok', starred: true })), catalog_patched: false }));
    const r = await p.starNotes(Array.from({ length: 250 }, (_, i) => 'k' + i), true);
    assert.equal(r.done, 200); assert.equal(r.failed, 50);
    assert.ok(r.results.at(-1).error.includes('disk full'));
  }
  // ④ CM2：导出提示带相对仓根路径、「已在资源管理器里选中」
  {
    const p = mk();
    p.runPy = async () => ({ code: 0, json: { path: require('path').join('/vault', '收藏导出', 'x.zip'), notes: 3, images: 5, missing: [] } });
    notices.length = 0;
    await p.exportArchiveBundle(['a'], true, '', { question: 'q' });
    assert.equal(notices.length, 1);
    assert.equal(notices[0], '已导出 3 篇、5 张原图 → 收藏导出/x.zip（已在资源管理器里选中）');
    assert.equal(shown.length, 1);
  }
  console.log('PASS starNotes batching / --off / per-id events / no double prefix / catalog_stat; export notice with vault-relative path');
})().catch(e => { console.error(e); process.exit(1); });

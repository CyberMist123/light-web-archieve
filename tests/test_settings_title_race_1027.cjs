// 1027 她的目录标题（自定义的自定义的标题）在 data.json 里成了空串（10-17 的备份里已经是空的，页面上却一直显示着——只在内存里）。
// 根因：saveMerged 用「内存值 ≠ 快照」认本窗口改过哪些键，但保存之间不排队——
//   改标题的那次保存 S1 和页面 / 设置页同时触发的另一次保存 S2 交叠：S2 的 loadData 读的是 S1 写盘前的旧文件，比较却用 S1 写完才更新的快照，
//   于是刚改的标题被判成「没改过」，内存和 data.json 一起被旧值 '' 盖掉。外部重读（盯文件 / onExternalSettingsChange）插在保存中间同理，
//   还会把「改了、防抖还没存」的键冲回旧值。
// 断言（用 main.js 里真的 saveSettings / setCatalogPrefs / onExternalSettingsChange；磁盘是一份 JSON，loadData 读到的是「开始读那一刻」的文件）：
//   1. 改标题和另一次保存同时发生：标题留在内存，也留在 data.json；
//   2. 外部重读赶在防抖保存之前：本窗口改了还没存的键不被冲掉，别处改的键照样并进来，之后保存两样都在；
//   3. setCatalogPrefs 写完回读：data.json 里的标题对不上就抛错（页面照「没保存上」说），不假装成功。
// 红线：LB_MAIN_JS=<旧版 main.js> 跑本文件，第 1 条在修复前的 main.js 上挂（记在 tests/acceptance/20261027-catalog-arrange.md）。
'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');

const OBS = { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Setting: class {}, Notice: class {}, Menu: class {} };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, URL, console,
  require: n => n === 'obsidian' ? OBS : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.env.LB_MAIN_JS || 'obsidian-plugins/link-brain-actions/main.js', 'utf8') + '\nmodule.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// readDelays：第 n 次 loadData 读完「开始读那一刻」的文件之后，过多少毫秒才交回（模拟 Obsidian adapter.read 的异步、两个读互相超车）
function makePlugin(saved, { readDelays = [] } = {}) {
  const p = new Plugin();
  let disk = JSON.stringify(Plugin.__merge(saved));
  let reads = 0;
  p.disk = () => JSON.parse(disk);
  p.writeDisk = obj => { disk = JSON.stringify(obj); };
  p.loadData = async () => { const snap = disk; const d = readDelays[reads++] || 0; if (d) await sleep(d); return JSON.parse(snap); };
  p.saveData = async obj => { disk = JSON.stringify(obj); };
  p.app = { workspace: { trigger() {} } };
  p.settings = Plugin.__merge(JSON.parse(disk));
  p.snapDisk(JSON.parse(disk));
  return p;
}

(async () => {
  // —— 1. 改标题 + 同时另一次保存（比如目录页防抖存列数）——
  {
    // 第 1 次读（改标题那次）5ms 交回；第 2 次读（另一次保存）在写盘之前就开始读、30ms 后才交回；之后的回读不延迟
    const p = makePlugin({ catalogTitle: '', catalogColumns: 4 }, { readDelays: [5, 30] });
    const a = p.setCatalogPrefs({ title: 'MY ARCHIVE' });
    await sleep(1);
    p.settings.catalogColumns = 5;
    const b = p.saveSettings();
    await Promise.all([a, b]);
    assert.equal(p.settings.catalogTitle, 'MY ARCHIVE', '内存里的标题被旧磁盘值盖掉了');
    assert.equal(p.disk().catalogTitle, 'MY ARCHIVE', 'data.json 里的标题被另一次保存写回了空串');
    assert.equal(p.disk().catalogColumns, 5, '另一次保存的列数也要在');
  }
  // —— 2. 外部重读赶在防抖保存之前 ——
  {
    const p = makePlugin({ catalogTitle: '', catalogColumns: 4, nickname: '' });
    p.settings.catalogTitle = '我的收藏';               // 页面改了，防抖还没存
    const d = p.disk(); d.nickname = '她'; p.writeDisk(d);   // 别处（另一个窗口 / 命令行）改了别的键
    await p.onExternalSettingsChange();
    assert.equal(p.settings.catalogTitle, '我的收藏', '外部重读把还没存的标题冲掉了');
    assert.equal(p.settings.nickname, '她', '别处改的键没并进来');
    await p.saveSettings();
    assert.equal(p.disk().catalogTitle, '我的收藏'); assert.equal(p.disk().nickname, '她');
  }
  // —— 3. 写完回读核对 ——
  {
    const p = makePlugin({ catalogTitle: '' });
    const real = p.saveData;
    p.saveData = async obj => real({ ...obj, catalogTitle: '' });   // 写盘「成功」但标题没进去
    await assert.rejects(() => p.setCatalogPrefs({ title: '标题' }), /没写进设置文件/);
    p.saveData = real;
    await p.setCatalogPrefs({ title: '  标题  ' });
    assert.equal(p.disk().catalogTitle, '标题', '去掉首尾空格后写进去');
  }
  console.log('PASS settings title race 1027: concurrent saves keep the new catalogTitle in memory and data.json · external reload keeps unsaved local keys and merges others · setCatalogPrefs reads back and rejects a write that did not land');
})().catch(e => { console.error('FAIL settings title race 1027', e); process.exit(1); });

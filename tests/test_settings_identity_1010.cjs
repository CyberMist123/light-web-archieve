// 设置保存后，设置页手里拿着的子对象（so = s.sync、httpFields(c, s.textAI) 之类）还得是同一个对象（1010 审查发现）。
// 以前 saveMerged 对「本窗口没改过」的顶层键整个换成磁盘上读回来的新对象：设置页再在旧对象上改开关，
// 界面显示改了、保存也「成功」，其实什么都没写进 data.json——开关立刻保存那条规矩被悄悄架空。
// 断言（用 main.js 里真的 saveMerged / onExternalSettingsChange，磁盘是内存里的一份 JSON）：
//   1. 改了 A 键（批注署名）保存一次后，在早先拿到的 sync 对象上关「下载图片」再保存 → 写进磁盘了，settings.sync 还是那个对象；
//   2. AI 栏：先填问收藏的接口地址保存，再在早先拿到的 visionAI 上填密钥保存 → 两样都在磁盘上；
//   3. 别处改了磁盘上另一个键：保存时把新值并进内存原来的对象里（引用不变），本窗口改的照写；
//   4. data.json 被别处改了（onExternalSettingsChange）：settings 和子对象引用都不变，值换成磁盘上的；
//   5. 数组（问收藏页的模型列表）：内容没变时元素引用不动（正在编辑的那个模型不会变成孤儿）。
'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');

const OBS = { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Setting: class {}, Notice: class {}, Menu: class {} };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, URL, console,
  require: n => n === 'obsidian' ? OBS : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8') + '\nmodule.exports.__merge = mergeSettings;', context);
const Plugin = context.module.exports;

// 磁盘上是一份完整的设置（插件第一次保存以后就是这样：默认值全补齐了）；remote 段不在默认值里，由 remote-ui 挂上（这里照做）
function makePlugin(saved) {
  const p = new Plugin();
  const full = Plugin.__merge(saved);
  if (saved.remote) full.remote = saved.remote;
  let disk = JSON.stringify(full);
  p.disk = () => JSON.parse(disk);
  p.writeDisk = obj => { disk = JSON.stringify(obj); };
  p.loadData = async () => JSON.parse(disk);
  p.saveData = async obj => { disk = JSON.stringify(obj); };
  p.app = { workspace: { trigger() {} } };
  p.settings = Plugin.__merge(JSON.parse(disk));
  if (saved.remote) p.settings.remote = JSON.parse(disk).remote;
  p.snapDisk(JSON.parse(disk));
  return p;
}

(async () => {
  // —— 1. 收藏与同步：先改批注署名，再在早先拿到的 sync 上关「下载图片」——
  {
    const p = makePlugin({ sync: { downloadImages: true, downloadVideo: true }, nickname: '' });
    const s = p.settings, so = s.sync;                       // 设置页 renderSyncTab：const s = this.plugin.settings, so = s.sync
    s.nickname = '我'; await p.saveSettings();
    so.downloadImages = false; await p.saveSettings();      // toggleRow 的 set：v => { so.downloadImages = v; }，然后保存
    assert.equal(p.disk().sync.downloadImages, false, '关掉的「下载图片」没写进 data.json（设置页拿着的 sync 成了孤儿）');
    assert.equal(p.disk().nickname, '我');
    assert.ok(p.settings.sync === so, '保存后 settings.sync 换成了另一个对象');
  }
  // —— 2. AI：先填问收藏的接口，再在早先拿到的 visionAI 上填密钥 ——
  {
    const p = makePlugin({ textAI: { mode: 'http', endpoint: '' }, visionAI: { mode: 'http', endpoint: 'https://api.example.com/v1/chat/completions' } });
    const t = p.settings.textAI, v = p.settings.visionAI;   // httpFields(c, s.textAI) / httpFields(c, s.visionAI)
    t.endpoint = 'https://api.example.com/v1/chat/completions'; await p.saveSettings();
    v.apiKey = 'k-test-only'; await p.saveSettings();
    assert.equal(p.disk().textAI.endpoint, 'https://api.example.com/v1/chat/completions');
    assert.equal(p.disk().visionAI.apiKey, 'k-test-only', '识图的密钥没写进 data.json');
  }
  // —— 3. 别处改了磁盘上另一个键：并进内存原来的对象，本窗口改的照写 ——
  {
    const p = makePlugin({ sync: { downloadImages: true, dailyNewLimit: 50 }, remote: { enabled: false, domain: '' }, nickname: '' });
    const so = p.settings.sync, rem = p.settings.remote;
    const d = p.disk(); d.remote = { enabled: true, domain: 'https://lb.example.test' }; p.writeDisk(d);   // 命令行 / 网页那边改的
    so.downloadImages = false; await p.saveSettings();
    assert.equal(p.disk().sync.downloadImages, false);
    assert.equal(p.disk().remote.domain, 'https://lb.example.test', '别处改的域名被内存旧值盖掉了');
    assert.equal(p.settings.remote.domain, 'https://lb.example.test', '内存没跟上磁盘');
    assert.ok(p.settings.remote === rem && p.settings.sync === so, '引用变了');
  }
  // —— 4. data.json 被别处改了：整份重读也不换对象 ——
  {
    const p = makePlugin({ sync: { downloadImages: true }, nickname: '' });
    const s = p.settings, so = s.sync;
    const d = p.disk(); d.sync.downloadImages = false; d.nickname = '她'; p.writeDisk(d);
    await p.onExternalSettingsChange();
    assert.ok(p.settings === s && p.settings.sync === so, '外部改了以后 settings / sync 换成了别的对象');
    assert.equal(so.downloadImages, false); assert.equal(s.nickname, '她');
    so.downloadImages = true; await p.saveSettings();
    assert.equal(p.disk().sync.downloadImages, true, '重读之后再改的没写进去');
  }
  // —— 5. 模型列表：内容没变时元素引用不动 ——
  {
    const p = makePlugin({ models: [{ name: 'A', mode: 'http' }, { name: 'B', mode: 'cli', command: 'x' }], nickname: '' });
    const m0 = p.settings.models[0], arr = p.settings.models;
    p.settings.nickname = '我'; await p.saveSettings();
    assert.ok(p.settings.models === arr && p.settings.models[0] === m0, '没改过的模型列表被换成了新对象');
    m0.name = 'A2'; await p.saveSettings();
    assert.equal(p.disk().models[0].name, 'A2');
  }
  console.log('PASS settings keep object identity across saves (1010): edits on sub-objects the settings tab holds reach data.json; external changes merged in place');
})().catch(e => { console.error(e); process.exit(1); });

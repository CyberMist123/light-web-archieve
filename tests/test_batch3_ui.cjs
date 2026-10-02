// 第 3 批：用户操作的结果如实反馈（CONVENTIONS §1.5/§1.6、§6.7）。真跑页面脚本和插件 main.js，假 DOM / 假 vault / 假 worker。
// 断言：
//   问收藏：作答中有「停止」，点了走插件 stopArchiveAnswer；停下后留半截 + 「已停止生成」，不给收藏；进度只显示后端阶段
//   收藏回答 / 存判断 / 删已保存：写盘失败不改界面、提示「没保存上，内容还在，可重试」，字留在框里
//   批注：删除失败那条还在、不再报「已删」；提交失败撤回、重试不重复
//   删除收藏：只摘确认删掉的，没删掉的保持选中并说清原因
//   投喂回写：只换成功的那段链接，附言和别的链接原样；导入期间新贴的行不动
//   插件：stopArchiveAnswer 发 {"type":"cancel"}；150 秒超时也走停止协议，不再直接杀 worker
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), vm = require('vm'), { EventEmitter } = require('events');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const LIB = asset('lb-page-lib.js');
const SEARCH = asset('catalog-search.js');
const DATA = '_archive/catalog-data.json';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
function catalogData() {
  const mk = (id, title) => ({ id, title, tags: [], cats: ['城市'], topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: '', attachment: 'none', starred: false });
  return { built_at: '2026-10-02T10:00:00+10:00', pinyin_chars: {}, aliases: [], cats_order: ['城市'], cats: [], topics: [], items: [mk('a', '悉尼咖啡地图'), mk('b', '悉尼海边徒步'), mk('c', '悉尼歌剧院')] };
}
function makeApp(V, plugin) {
  return { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
}
// 某些路径写盘失败（模拟只读 / 被占用）
function failWrites(V, paths, msg = 'EPERM: operation not permitted') {
  const real = V.vault.adapter.write;
  V.vault.adapter.write = async (p, s) => { if (paths.has(p)) throw new Error(msg); return real(p, s); };
}

async function chatTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const V = makeVault({ [DATA]: JSON.stringify(catalogData()), '_archive/chat-session.json': '{"turns":[]}', '_archive/chat-archive.json': '{"entries":[]}' });
  let req, stops = 0;
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { for (const t of String(md).split('\n\n')) el.createEl('p', { text: t }); },
    answerArchive: r => new Promise(res => { req = { ...r, res }; }),
    stopArchiveAnswer() { stops++; return 1; },
    archiveSourceState: () => ({ reader: false, compare: false }),
  };
  const app = makeApp(V, plugin);
  const A = dataviewBlock({ dom, app, code: LIB + '\n' + SEARCH + '\n' + asset('chat-view.js') });
  await A.run();
  const q = s => A.container.querySelector(s);
  const stop = q('.lbchat-stop');
  assert.ok(stop && stop.hidden, '没在作答时不显示停止');
  // 问一句：显示停止；进度只显示后端阶段
  q('.lbchat-search').value = '悉尼有什么'; await q('.lbchat-composer').onsubmit({ preventDefault() {} }); await tick(5);
  assert.ok(!stop.hidden, '作答中显示停止');
  assert.ok(q('.lbchat-body').textContent.includes('正在生成…'), '还没阶段时显示「正在生成…」');
  req.onPhase('挑选材料');
  assert.ok(q('.lbchat-body').textContent.includes('挑选材料…'), '后端阶段原样显示');
  req.onDelta('写到一');
  stop.onclick();
  assert.equal(stops, 1, '停止走插件 stopArchiveAnswer');
  req.res({ status: 'cancelled', markdown: '写到一半' }); await tick(10);
  const turns = JSON.parse(V.get('_archive/chat-session.json')).turns;
  const last = turns.at(-1);
  assert.ok(last.stopped && last.failed && last.content.startsWith('写到一半') && last.content.includes('已停止生成'), JSON.stringify(last));
  assert.ok(stop.hidden, '停下后停止按钮收起');
  assert.equal(q('.lbchat-bookmark'), null, '停下的半截不给收藏');

  // 正常答完一条，再试「收藏回答」写盘失败
  q('.lbchat-search').value = '再问'; await q('.lbchat-composer').onsubmit({ preventDefault() {} }); await tick(5);
  req.res({ status: 'ok', markdown: '答案', sources: [] }); await tick(10);
  failWrites(V, new Set(['_archive/chat-archive.json']));
  const bm = q('.lbchat-bookmark');
  await bm.onclick(); await tick(5);
  assert.ok(!bm.classList.contains('is-saved'), '没写上就不显示已收藏');
  assert.equal(JSON.parse(V.get('_archive/chat-archive.json')).entries.length, 0);
  assert.ok(A.notices.some(m => m.startsWith('没保存上，内容还在，可重试：') && m.includes('EPERM')), A.notices.join('|'));
  console.log('PASS chat: stop button → stopArchiveAnswer, partial kept + 已停止生成, real phases only, bookmark not shown saved when write fails');

  // 「已保存」栏：存判断失败字留在框里；删除失败那条还在
  const tabs = A.container.querySelectorAll('.lbchat-tab');
  await tabs.find(t => t.textContent === '已保存').onclick(); await tick(5);
  const ta = q('.lbchat-arc-input');
  ta.value = 'ib 机不适合'; await q('.lbchat-arc-save').onclick(); await tick(5);
  assert.equal(q('.lbchat-arc-input').value, 'ib 机不适合', '失败时字留在框里');
  assert.equal(A.container.querySelectorAll('.lbchat-arc-item').length, 0, '界面上不出现没存上的那条');
  V.vault.adapter.write = async (p, s) => { V.set(p, s); };
  await q('.lbchat-arc-save').onclick(); await tick(5);
  assert.equal(A.container.querySelectorAll('.lbchat-arc-item').length, 1);
  failWrites(V, new Set(['_archive/chat-archive.json']));
  await q('.lbchat-arc-del').onclick(); await tick(5);
  assert.equal(A.container.querySelectorAll('.lbchat-arc-item').length, 1, '删除没写上，那条还在');
  assert.equal(JSON.parse(V.get('_archive/chat-archive.json')).entries.length, 1);
  console.log('PASS chat archive: save failure keeps text in box, delete failure keeps the entry, both say 没保存上…可重试');
}

async function annotateTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const NOTE = '_archive/xiaohongshu/n1/notes.json';
  const V = makeVault({ [NOTE]: JSON.stringify({ starred: false, annotations: [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }] }) });
  const app = makeApp(V, { settings: {} });
  const A = dataviewBlock({ dom, app, code: LIB + '\n' + asset('annotate-view.js'), params: { itemId: 'xhs-n1', notePath: NOTE } });
  await A.run();
  const box = A.container.querySelector('.lba-annot');
  const texts = () => box.querySelectorAll('.lba-annot-text').map(x => x.textContent);
  failWrites(V, new Set([NOTE]));
  // 删除失败：那条还在、不报「已删」
  await box.querySelector('.lba-del').onclick({ stopPropagation() {} }); await tick(5);
  assert.deepEqual(texts(), ['旧的']);
  assert.ok(A.notices.some(m => m.startsWith('没保存上，内容还在，可重试')), A.notices.join('|'));
  assert.ok(!box.querySelector('.lba-save-hint')?.textContent.includes('已删'));
  // 提交失败：撤回、字留在框里；恢复后重试只多一条
  const ta = box.querySelector('.lba-annot-input');
  ta.value = '新批注'; await ta.onblur(); await tick(5);
  assert.deepEqual(texts(), ['旧的']);
  assert.equal(ta.value, '新批注');
  V.vault.adapter.write = async (p, s) => { V.set(p, s); };
  await ta.onblur(); await tick(5);
  assert.deepEqual(JSON.parse(V.get(NOTE)).annotations.map(a => a.text), ['旧的', '新批注'], '重试不重复');
  console.log('PASS annotate: delete failure keeps the item (no 已删), commit failure rolls back and retry adds exactly one');
}

async function deleteTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const V = makeVault({ [DATA]: JSON.stringify(catalogData()), '_archive/sync-status.json': '{}' });
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {},
    deleteItems: async ids => ({ ok: false, deleted: 1, message: '', results: [{ item_id: 'a', status: 'deleted' }, { item_id: 'b', status: 'failed', error: '文件被占用或没有权限：WinError 32' }, { item_id: 'c', status: 'missing' }] }) };
  const app = makeApp(V, plugin);
  const A = dataviewBlock({ dom, app, code: LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js') });
  A.window.confirm = () => true;
  await A.run();
  const input = A.container.querySelector('.lbc-search');
  input.value = '悉尼'; input.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} });
  const cards = () => A.container.querySelectorAll('.lbc-card');
  cards()[0].oncontextmenu({ preventDefault() {}, clientX: 0, clientY: 0 });
  dom.document.body.querySelectorAll('.lbc-menu-item').find(b => b.textContent === '多选删除').onclick({ stopPropagation() {} });
  cards()[1].onclick({}); cards()[2].onclick({});
  assert.equal(A.container.querySelectorAll('.lbc-card.is-selected').length, 3);
  const del = A.container.querySelectorAll('button').find(b => /^删除选中/.test(b.textContent));
  await del.onclick(); await tick(10);
  const left = cards().map(c => c.querySelector('.lbc-ctitle').textContent);
  assert.ok(!left.includes('悉尼咖啡地图'), '确认删掉的摘掉');
  assert.equal(left.length, 2, '没删掉的两篇还在');
  assert.equal(A.container.querySelectorAll('.lbc-card.is-selected').length, 2, '没删掉的保持选中');
  const msg = A.alerts.at(-1);
  assert.ok(msg.startsWith('已删 1 篇；2 篇没删掉：') && msg.includes('WinError 32') && msg.includes('库里没有'), msg);
  console.log('PASS delete: only confirmed deletions removed, failures stay selected with reasons');
}

function loadPlugin(spawnImpl) {
  const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, URL,
    require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {} } : n === 'child_process' ? { spawn: spawnImpl } : require(n) };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
  return context.module.exports;
}

async function inboxTests() {
  const { rewriteInbox } = loadPlugin(() => {});
  const A = 'https://www.xiaohongshu.com/explore/aaa?xsec_token=T1&xsec_source=pc_share';
  const B = 'https://www.xiaohongshu.com/explore/bbb?xsec_token=T2';
  const original = [`看这两篇 ${A} 和 ${B} 备注：周末做`, `只有一个 ${B}`, '- [ ] ' + A, '别的站 https://example.com/x 留着'].join('\n');
  const current = original + `\n导入时新贴的 ${A}`;
  const byUrl = new Map([[A, { url: A, ok: true, note: '甲' }], [B, { url: B, ok: false }]]);
  const out = rewriteInbox(current, original, byUrl).split('\n');
  assert.equal(out[0], `看这两篇 [[甲]] 和 ${B} 备注：周末做`, '只换成功的那段，附言和失败的链接原样');
  assert.equal(out[1], `只有一个 ${B}`);
  assert.equal(out[2], '- [x] [[甲]]', '整行都成功才打勾');
  assert.equal(out[3], '别的站 https://example.com/x 留着');
  assert.equal(out[4], `导入时新贴的 ${A}`, '导入期间新贴的行不动');
  const both = rewriteInbox(`两个 ${A} ${A} 好`, `两个 ${A} ${A} 好`, byUrl);
  assert.equal(both, '- [x] 两个 [[甲]] [[甲]] 好');
  console.log('PASS inbox: only the imported URL span becomes [[note]], notes/other links kept, new lines untouched');
}

async function pluginCancelTests() {
  const children = [];
  function spawn() { const c = new EventEmitter(); c.stdout = new EventEmitter(); c.stdout.setEncoding = () => {}; c.stderr = new EventEmitter(); c.stdin = new EventEmitter(); c.sent = []; c.stdin.write = s => { c.sent.push(JSON.parse(s)); }; c.kill = () => c.emit('close'); c.pid = 777; children.push(c); return c; }
  const Plugin = loadPlugin(spawn);
  const p = new Plugin(); p.repoRoot = process.cwd(); const killed = []; p.killTree = async pid => { killed.push(pid); return [pid]; };
  const phases = [];
  const a = p.answerArchive({ question: '慢', onPhase: t => phases.push(t) });
  const c = children[0]; const id = c.sent[0].id;
  c.stdout.emit('data', JSON.stringify({ id, type: 'phase', text: '检索收藏' }) + '\n');
  assert.deepEqual(phases, ['检索收藏']);
  assert.equal(p.stopArchiveAnswer(), 1);
  assert.deepEqual(c.sent.at(-1), { id, type: 'cancel' });
  c.stdout.emit('data', JSON.stringify({ id, type: 'result', result: { status: 'cancelled', markdown: '半截' } }) + '\n');
  assert.deepEqual(JSON.parse(JSON.stringify(await a)), { status: 'cancelled', markdown: '半截' });
  assert.deepEqual(killed, [], 'worker 自己停了就不杀 worker');
  // 超时：走 cancel 协议，回 cancelled 后报「超过…已停止」
  p.answerTimeoutMs = 20;
  const b = p.answerArchive({ question: '更慢' });
  const id2 = c.sent.at(-1).id;
  await tick(40);
  assert.deepEqual(c.sent.at(-1), { id: id2, type: 'cancel' }, '超时先发 cancel');
  c.stdout.emit('data', JSON.stringify({ id: id2, type: 'result', result: { status: 'cancelled', markdown: '' } }) + '\n');
  await assert.rejects(b, /超过 0 秒没有完成，已停止|已停止/);
  // worker 卡死不回：宽限期后经 killTree 结束，页面拿到 cancelled
  p.answerTimeoutMs = 150000; p.answerCancelGraceMs = 20;
  const d = p.answerArchive({ question: '卡死' });
  p.stopArchiveAnswer();
  await tick(60);
  assert.deepEqual(killed, [777], '卡死才杀 worker（killTree，跳过读取服务）');
  assert.equal((await d).status, 'cancelled');
  console.log('PASS plugin: stop sends cancel, phases forwarded, timeout uses cancel protocol, stuck worker killed via killTree after grace');
}

(async () => {
  await chatTests();
  await annotateTests();
  await deleteTests();
  await inboxTests();
  await pluginCancelTests();
})().catch(e => { console.error(e); process.exitCode = 1; });

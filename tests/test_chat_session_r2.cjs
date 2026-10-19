// Lot R2 会话面：① 导出 = 当前保留的全部来源（删掉的除外；主要依据全文进包、引用过的标引用号；其他相关以胶囊进回答文件）
// ② 排除 / 保留（pin）是会话级的、存进 chat-session.json，追问 / 重答都显式带上；旧会话没这两个字段 = 空、请求和以前一样
// ③ 证据身份：评论摘录带楼号、图片文字带图序号，来源行悬停（title）和导出的命中原文里都看得到。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';
const SESSION = '_archive/chat-session.json';

(async () => {
  const src = (id, n, excerpts = []) => ({ id, citation: n, title: '主要' + id, note: `Web/${id}.md`, tier: 'primary', excerpts });
  const rel = (id, n) => ({ id, rank: n, title: '相关' + id, note: `Web/${id}.md`, tier: 'related', excerpt: '相关' + id + '的命中摘录' });
  const withId = [{ field: 'comments', text: '担担面是没有汤的', comment_labels: ['c3', 'c3.1'] },
    { field: 'ocr', text: '小贴士：逆纹切条', assets: ['image-002.webp'], images: ['图2'] }, { field: 'body', text: '正文' }];
  // 旧会话：没有 excluded / pinned 字段
  const turns = [{ role: 'user', content: '担担面有没有汤' },
    { role: 'assistant', content: '没有汤 [来源1]', q: '担担面有没有汤', askedAt: '2026-10-04T10:00:00+10:00',
      sources: [src('a', 1, withId), src('b', 2)], related: [rel('c', 3), rel('d', 4)] }];
  const V = makeVault({ /* 1015 前的默认（追问绑来源、接着这段问），新默认见 test_chat_b2_1015 */ '_archive/chat-prefs.json': '{"follow":"sources","keepThread":true}',  [DATA]: JSON.stringify({ built_at: '2026-10-04T10:00:00+10:00', items: [] }),
    // 1020 起「新对话」会开新的一段；这里要验「同一段里重新搜带上排除 / 保留」，只有隐私模式（不自动开新段）还走这条路
    [SESSION]: JSON.stringify({ turns, private: true }), '_archive/chat-archive.json': '{"entries":[]}' });
  const asks = [], bundles = [];
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { el.createEl('p', { text: md }); },
    archiveSourceState: () => ({ reader: false, compare: false }),
    async openArchiveSource() {},
    async exportArchiveBundle(...args) { bundles.push(args); return { path: 'x.zip' }; },
    async answerArchive(req) {
      asks.push(req);
      return { status: 'ok', markdown: '新回答 [来源1]', sources: [src('b', 1), src('e', 2)], related: [rel('f', 3)] };
    },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const open = async () => {
    delete globalThis.__lbState; delete globalThis.__lbListeners;
    const A = dataviewBlock({ dom: makeDom(), app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js') });
    await A.run();
    return A;
  };
  let A = await open();
  const all = s => A.section.querySelectorAll(s);
  const turnEls = () => all('.lbchat-answer');
  const rowButton = (turn, title, cls) => { const links = turn.querySelectorAll('a'); const i = links.findIndex(a => a.textContent.includes(title)); return turn.querySelectorAll(cls)[i]; };

  // 旧会话、没排除没保留：10-04 起追问默认「在当前来源里追问」——只交上一轮留下的来源（主要依据 + 其他相关），不带 excludeIds / pinIds
  // （1015 起「展开细节」只绑那一答的主要依据，见 test_chat_b2_1015；这里改用输入框追问验追问绑定）
  const ask = async text => { A.section.querySelector('.lbchat-search').value = text; await A.section.querySelector('.lbchat-composer').onsubmit({ preventDefault() {} }); };
  await ask('展开重点细节'); await tick(20);
  assert.equal(asks.length, 1);
  assert.deepEqual(Object.keys(asks[0]).filter(k => /Ids$/.test(k)), ['sourceIds']);
  assert.deepEqual(Array.from(asks[0].sourceIds), ['a', 'b', 'c', 'd']);
  // 下面验 R2 的「重新检索」那条路：开关点「新对话」（1020 起「追问 · 新对话」两个词并排），状态跟会话一起存
  const seg = label => all('.lbchat-followmode .lbchat-seg-opt').find(b => b.textContent === label);
  assert.ok(seg('追问').classList.contains('is-on'));
  await seg('新对话').onclick(); await tick(5);
  assert.equal(JSON.parse(V.get(SESSION)).follow, 'search');
  assert.ok(seg('新对话').classList.contains('is-on'));

  // ③ 证据身份：来源行悬停看得到楼号 / 图序号
  const linkA = turnEls()[0].querySelectorAll('a').find(a => a.textContent.includes('主要a'));
  assert.equal(linkA.getAttribute('title'), '命中：评论 c3、c3.1 · 图片文字（识别结果） 图2 · 作者正文');
  assert.equal(turnEls()[0].querySelectorAll('a').find(a => a.textContent.includes('主要b')).getAttribute('title'), null, '没有摘录的不挂 title');

  // ① 导出：主要依据 a、b 全进（b 没被引用也进，标注「没引用」），其他相关 c、d 以胶囊写进回答文件；签名仍是 4 个参数
  const exportBtn = () => turnEls()[0].querySelectorAll('.lbchat-export button').find(b => b.textContent === '导出资料包');
  await exportBtn().onclick(); await tick(5);
  assert.equal(bundles.length, 1);
  assert.equal(bundles[0].length, 4);
  assert.deepEqual(Array.from(bundles[0][0]), ['a', 'b']);
  let md = bundles[0][2];
  assert.ok(md.includes('> 提问原话：担担面有没有汤'));
  assert.ok(md.includes('### [来源1] 主要a\n') && md.includes('### [来源2] 主要b（送进了模型，回答没引用）'));
  assert.ok(md.includes('**评论 c3、c3.1**') && md.includes('**图片文字（识别结果） 图2**'));
  assert.ok(md.includes('## 可能相关（保留着、没送进模型）') && md.includes('- 相关c · 本地正文：Web/c.md') && md.includes('  > 相关c的命中摘录') && md.includes('- 相关d'));
  assert.equal(bundles[0][3].question, '担担面有没有汤');

  // ② 保留 b（主要依据），删掉 c（其他相关）
  await rowButton(turnEls()[0], '主要b', '.lbchat-src-pin').onclick(); await tick(5);
  await rowButton(turnEls()[0], '相关c', '.lbchat-src-del').onclick(); await tick(5);
  let saved = JSON.parse(V.get(SESSION));
  assert.deepEqual(saved.pinned, ['b']);
  assert.deepEqual(saved.excluded, ['c']);
  assert.deepEqual(saved.turns[1].removed, ['c']);
  assert.equal(rowButton(turnEls()[0], '主要b', '.lbchat-src-pin').textContent, '已保留');
  // 删过的不再导出：c 进「删掉的来源」那一行，不再出现在胶囊里
  await exportBtn().onclick(); await tick(5);
  md = bundles[1][2];
  assert.ok(md.includes('这一轮删掉的来源（没导出）：相关c') && !md.includes('- 相关c') && md.includes('- 相关d'));

  // 追问（一次普通提问）：排除和保留都显式带给后端
  await ask('再问一句'); await tick(20);
  assert.equal(asks.length, 2);
  assert.deepEqual(Array.from(asks[1].excludeIds), ['c']);
  assert.deepEqual(Array.from(asks[1].pinIds), ['b']);
  assert.equal(asks[1].sourceIds, undefined);

  // 刷新页面：会话级状态还在
  A = await open();
  saved = JSON.parse(V.get(SESSION));
  assert.deepEqual(saved.pinned, ['b']);
  assert.equal(saved.follow, 'search', '「新对话」刷新后还在');
  assert.ok(seg('新对话').classList.contains('is-on'));
  assert.equal(rowButton(turnEls()[0], '主要b', '.lbchat-src-pin').textContent, '已保留');

  // 重答（第一轮删过 c）：交留下的来源（保留的排最前），排除照样带上；10-04 ②：保留的也作为 pinIds 带上（后端排最前、要求逐条用到）
  const redo = all('.lbchat-src-redo button').find(b => b.textContent.startsWith('按剩下的'));
  assert.equal(redo.textContent, '按剩下的 3 条重新回答');
  await redo.onclick(); await tick(20);
  assert.deepEqual(Array.from(asks[2].sourceIds), ['b', 'a', 'd']);
  assert.deepEqual(Array.from(asks[2].excludeIds), ['c']);
  assert.deepEqual(Array.from(asks[2].pinIds), ['b']);

  // 排除压过保留：把保留着的 b 删掉 → 从 pinned 里拿掉；恢复只恢复这一轮删的
  const last = () => turnEls()[turnEls().length - 1];
  await rowButton(last(), '主要b', '.lbchat-src-del').onclick(); await tick(5);
  saved = JSON.parse(V.get(SESSION));
  assert.deepEqual(saved.pinned, []);
  assert.deepEqual(saved.excluded, ['c', 'b']);
  await last().querySelectorAll('.lbchat-src-redo button').find(b => b.textContent.startsWith('恢复删掉的')).onclick(); await tick(5);
  saved = JSON.parse(V.get(SESSION));
  assert.deepEqual(saved.excluded, ['c'], '只恢复这一轮删掉的 b，第一轮删的 c 还排除着');

  // 插件 answerArchive：excludeIds / pinIds → 请求里的 exclude_ids / pin_ids；空的不发（请求和以前一模一样）
  {
    const fs = require('fs'), vm = require('vm'), { EventEmitter } = require('events');
    const children = [];
    const spawn = () => { const c = new EventEmitter(); c.stdout = new EventEmitter(); c.stdout.setEncoding = () => {}; c.stderr = new EventEmitter(); c.stdin = new EventEmitter(); c.sent = []; c.stdin.write = s => { c.sent.push(JSON.parse(s)); }; c.kill = () => c.emit('close'); c.pid = 1; children.push(c); return c; };
    const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, URL,
      require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {} } : n === 'child_process' ? { spawn } : require(n) };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
    const p = new context.module.exports(); p.repoRoot = process.cwd(); p.settings = { textAI: {} };
    const reply = () => { const c = children[0], id = c.sent.at(-1).id; c.stdout.emit('data', JSON.stringify({ id, type: 'result', result: { status: 'ok', markdown: 'x' } }) + '\n'); return c.sent.at(-1); };
    let pending = p.answerArchive({ question: 'q', excludeIds: ['c', 3], pinIds: ['b'] }); let sent = reply(); await pending;
    assert.deepEqual(sent.exclude_ids, ['c']); assert.deepEqual(sent.pin_ids, ['b']);
    pending = p.answerArchive({ question: 'q', sourceIds: ['a'], excludeIds: ['c'] }); sent = reply(); await pending;
    assert.deepEqual(sent.source_ids, ['a']); assert.deepEqual(sent.exclude_ids, ['c']); assert.equal(sent.pin_ids, undefined);
    pending = p.answerArchive({ question: 'q', excludeIds: [], pinIds: null }); sent = reply(); await pending;
    assert.deepEqual(Object.keys(sent).sort(), ['history', 'id', 'model', 'question']);
  }

  console.log('PASS chat session (R2): export keeps all kept sources (cited marked, related as capsules, removed listed), session excluded/pinned persisted and sent on follow-up / reask, pin yields to later exclusion, comment floor + image number shown');
})().catch(e => { console.error(e); process.exit(1); });

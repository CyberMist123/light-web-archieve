// 第 10 批：问收藏回答下面的来源分两档（主要依据 / 其他相关），每条可 × 删掉，删过之后「按剩下的重新回答」
// 只把留下的来源 id 交给插件（answerArchive 的 sourceIds），不重新检索；删除记在这一轮里、跟会话一起存。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';

(async () => {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const src = (id, n) => ({ id, citation: n, title: '主要' + id, note: `Web/${id}.md`, tier: 'primary', excerpts: [] });
  const rel = (id, n) => ({ id, rank: n, title: '相关' + id, note: `Web/${id}.md`, tier: 'related', excerpt: '' });
  const turns = [{ role: 'user', content: '日本好吃的' },
    { role: 'assistant', content: '有这些 [来源1] [来源2]', q: '日本好吃的', sources: [src('a', 1), src('b', 2)], related: [rel('c', 3), rel('d', 4), rel('e', 5)] }];
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: '2026-10-03T10:00:00+10:00', items: [] }),
    '_archive/chat-session.json': JSON.stringify({ turns }), '_archive/chat-archive.json': '{"entries":[]}' });
  const asks = [];
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { el.createEl('p', { text: md }); },
    archiveSourceState: () => ({ reader: false, compare: false }),
    async openArchiveSource() {},
    async answerArchive(req) {
      asks.push(req);
      return { status: 'ok', markdown: '只按留下的来源回答 [来源1]', sources: [src('b', 1), { ...rel('c', 0), citation: 2, tier: 'primary' }], related: [rel('e', 3)] };
    },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js') });
  await A.run();
  const all = s => A.container.querySelectorAll(s);
  const boxes = () => all('.lbchat-src');
  // 两档：主要依据（送进模型的，带 [来源N]）在前，其他相关在后
  assert.equal(boxes().length, 2);
  assert.ok(boxes()[0].textContent.includes('主要依据 · 2') && boxes()[0].textContent.includes('[来源1] 主要a'));
  assert.ok(boxes()[1].classList.contains('lbchat-src-more') && boxes()[1].textContent.includes('其他相关 · 3'));
  // 删掉主要依据里的 a 和其他相关里的 d
  const del = (box, title) => { const links = box.querySelectorAll('a'); const i = links.findIndex(a => a.textContent.includes(title)); return box.querySelectorAll('.lbchat-src-del')[i]; };
  await del(boxes()[0], '主要a').onclick(); await tick(5);
  await del(boxes()[1], '相关d').onclick(); await tick(5);
  assert.ok(!boxes()[0].textContent.includes('主要a') && boxes()[0].textContent.includes('主要依据 · 1'));
  assert.ok(boxes()[1].textContent.includes('其他相关 · 2') && !boxes()[1].textContent.includes('相关d'));
  const saved = JSON.parse(V.get('_archive/chat-session.json'));
  assert.deepEqual(saved.turns[1].removed, ['a', 'd'], '删除记在这一轮里，跟会话一起存');
  // 按剩下的重新回答：只交留下的来源（主要依据在前、其他相关按原顺序），问题不变
  const redo = all('.lbchat-src-redo button').find(b => b.textContent.startsWith('按剩下的'));
  assert.equal(redo.textContent, '按剩下的 3 条重新回答');
  await redo.onclick(); await tick(20);
  assert.equal(asks.length, 1);
  assert.equal(asks[0].question, '日本好吃的');
  assert.deepEqual(Array.from(asks[0].sourceIds), ['b', 'c', 'e']);
  const after = JSON.parse(V.get('_archive/chat-session.json')).turns;
  assert.equal(after.length, 4);
  assert.equal(after[2].mode, 'reask');
  assert.deepEqual(after[3].related.map(r => r.id), ['e'], '新回答带回新的两档来源');
  assert.ok(A.container.textContent.includes('按留下的 3 条来源重答'));
  // 恢复删掉的
  const undo = all('.lbchat-src-redo button').find(b => b.textContent.startsWith('恢复删掉的'));
  await undo.onclick(); await tick(5);
  assert.deepEqual(JSON.parse(V.get('_archive/chat-session.json')).turns[1].removed, []);
  console.log('PASS ask sources (batch 10): 主要依据 / 其他相关 two tiers, × removes and persists, 按剩下的重新回答 sends only kept source ids, undo');
})().catch(e => { console.error(e); process.exit(1); });

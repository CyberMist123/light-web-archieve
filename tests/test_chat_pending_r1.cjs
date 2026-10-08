// Lot R1：目录页「去问收藏搜「…」」带词跳转，问收藏页已经开着时也要自动问（以前 Dataview 重跑走 reuseDom 挂回旧页面，
// pendingArchiveQuestion 那一行根本不跑，带过来的词一直躺着）。三条路都接：第一次画完、旧页面挂回（onReuse）、
// 目录页发的 link-brain:ask-pending 事件；取走即删，同一个词只问一次。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';

(async () => {
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: '2026-10-04T10:00:00+10:00', items: [] }),
    '_archive/chat-session.json': JSON.stringify({ turns: [] }), '_archive/chat-archive.json': '{"entries":[]}' });
  const asks = [];
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { el.createEl('p', { text: md }); },
    archiveSourceState: () => ({ reader: false, compare: false }),
    async openArchiveSource() {},
    async answerArchive(req) { asks.push(req.question); return { status: 'ok', markdown: '答：' + req.question, sources: [], related: [] }; },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const A = dataviewBlock({ dom: makeDom(), app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js') });

  // 第一次画：带着词来的（问收藏页本来没开）→ 直接问
  plugin.pendingArchiveQuestion = '面点';
  await A.run(); await tick(30);
  assert.deepEqual(asks, ['面点']);
  assert.equal(plugin.pendingArchiveQuestion, undefined, '取走即删');

  // 问收藏页已经开着：Dataview 重跑走 reuseDom（旧 DOM 挂回），以前这里不问 —— 现在 onReuse 里接
  plugin.pendingArchiveQuestion = '担担面';
  await A.rerun(); await tick(30);
  assert.deepEqual(asks, ['面点', '担担面'], '页面开着、挂回旧 DOM 时也要问');
  assert.equal(A.section.querySelectorAll('.lbchat-answer').length, 2);

  // 页面开在别的标签里、Dataview 没重跑：目录页点了之后发 link-brain:ask-pending 事件
  plugin.pendingArchiveQuestion = '红烧牛肉';
  app.workspace.trigger('link-brain:ask-pending'); await tick(30);
  assert.deepEqual(asks, ['面点', '担担面', '红烧牛肉']);

  // 同一个词只问一次：再重跑 / 再发事件都不重复
  await A.rerun(); app.workspace.trigger('link-brain:ask-pending'); await tick(30);
  assert.equal(asks.length, 3);

  // 目录页那一行：点了先设 pending、开问收藏页，再发事件
  const VIEW = asset('catalog-view.js');
  assert.match(VIEW, /p\.pendingArchiveQuestion=committed;await p\.openLibraryPage\('chat'\);app\.workspace\.trigger\?\.\('link-brain:ask-pending'\)/);
  console.log('PASS chat pending (R1): first render / reuseDom / ask-pending event, consumed once');
})().catch(e => { console.error(e); process.exit(1); });

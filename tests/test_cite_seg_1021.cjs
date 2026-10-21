// 1021 她：回答里 [来源N 段k] → 胶囊只显示 [来源N]、记 data-seg；点了把段 k 的证据排第一交给插件 openArchiveSource（右侧跳那一段）；
// 没段号的 [来源N] 按点击那句的上下文挑最像的一段；导出的「引用过」也认带段号的引用。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';

(async () => {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const excerpts = [
    { seg: 1, field: 'body', text: '开头一段讲背景，没有具体做法。', offset: 0, paras: [0] },
    { seg: 2, field: 'ocr', text: '小贴士：牛肉逆纹切条', images: ['图2'], assets: ['raw/v0001/assets/image-002.webp'] },
    { seg: 3, field: 'comments', text: '评论区说要多放一勺醋', comment_labels: ['c3'], speakers: ['评论者：小王（不是作者）'] },
  ];
  const src = { id: 'a', citation: 1, title: '主要a', note: 'Web/a.md', tier: 'primary', excerpts };
  const turns = [{ role: 'user', content: '牛肉怎么切' },
    { role: 'assistant', content: '逆纹切条 [来源1 段2]。\n\n评论区说要多放一勺醋 [来源1]。\n\n背景 [来源1·段1]', q: '牛肉怎么切', sources: [src], related: [] }];
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: '2026-10-03T10:00:00+10:00', items: [] }),
    '_archive/chat-session.json': JSON.stringify({ turns }), '_archive/chat-archive.json': '{"entries":[]}' });
  const opened = [];
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { for (const para of md.split(/\n\n+/)) el.createEl('p', { text: para }); },
    archiveSourceState: () => ({ reader: false, compare: false }),
    async openArchiveSource(note, host, compare, evidence) { opened.push({ note, evidence }); },
    async answerArchive() { return { status: 'ok', markdown: 'x', sources: [], related: [] }; },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js') });
  await A.run();
  const cites = A.section.querySelectorAll('button.lbchat-cite');
  assert.equal(cites.length, 3, '三处引用都成了胶囊');
  assert.deepEqual(cites.map(b => b.textContent), ['[来源1]', '[来源1]', '[来源1]'], '胶囊上不显示段号');
  assert.deepEqual(cites.map(b => b.dataset.seg || ''), ['2', '', '1']);
  assert.ok(cites[0].getAttribute('title').includes('第 2 段'));
  // 点带段号的：插件只负责开笔记（证据传空），页面自己定位；假宿主没有右栏（archiveLeaves 缺）→ 定位日志记 no-reader，但挑的段是段 2（图片文字）
  const lastLog = () => JSON.parse(V.get('_archive/locate-last.json'));
  await cites[0].onclick({ stopPropagation() {} }); await tick(2300);
  assert.equal(opened.length, 1);
  assert.equal(opened[0].note, 'Web/a.md');
  assert.deepEqual(opened[0].evidence, [], '插件不再收证据段（页面自己跳，免得两边都跳）');
  assert.equal(lastLog().seg, 2); assert.equal(lastLog().field, 'ocr'); assert.equal(lastLog().why, 'no-reader');
  // 点没段号的：按那一句上下文（「要多放一勺醋」）挑最像的一段 = 评论 c3
  await cites[1].onclick({ stopPropagation() {} }); await tick(2300);
  assert.equal(lastLog().seg, 3); assert.deepEqual(lastLog().labels, ['c3']);
  // 「·」写法也认
  await cites[2].onclick({ stopPropagation() {} }); await tick(2300);
  assert.equal(lastLog().seg, 1);
  // 来源行「↑ 引用处」照常找得到胶囊（data-cite 不变）
  assert.equal(A.section.querySelectorAll('button.lbchat-cite').filter(b => b.dataset.cite === '1').length, 3);
  console.log('PASS cite seg (1021): [来源N 段k] capsule hides seg, click sends seg excerpt first; plain [来源N] picks by context; · spelling accepted');
})().catch(e => { console.error(e); process.exit(1); });

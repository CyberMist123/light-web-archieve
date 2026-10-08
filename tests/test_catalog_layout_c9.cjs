// 批次 D · L1 C9：按行瀑布流的纯函数（catalog-search.js 末尾）+ 页面摆法。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, asset } = require('./_fake_l1.cjs');

const { lbcColumns, lbcCardHeight, lbcAssign } = new Function(asset('catalog-search.js') + ';return {lbcColumns, lbcCardHeight, lbcAssign}')();

(async () => {
  // 纯函数
  assert.deepEqual(lbcAssign([100, 300, 100, 100, 100], 3).cols, [[0, 3], [1], [2, 4]], '第一排是 0、1、2，之后放进最矮的一列');
  assert.deepEqual(lbcAssign([100, 100, 100, 100], 2).cols, [[0, 2], [1, 3]], '平局取最左');
  assert.deepEqual(lbcAssign([100, 100.3, 50], 2).cols, [[0, 2], [1]], '只差不到 0.5px 不换列');
  const h = (it, w) => lbcCardHeight(it, w);
  const base = { title: '', cover: 'x.webp' };
  const coverOf = it => h(it, 230) - h({ ...it, cover: '' }, 230) + 230 * 0.75;
  assert.equal(Math.round(coverOf({ ...base, cover_w: 1080, cover_h: 1440 }) * 10) / 10, 306.7);
  assert.equal(coverOf({ ...base, cover_w: 1080, cover_h: 2000 }), 360, '封顶 360');
  assert.equal(Math.round((h({ title: '' }, 230) - (12 + 22.4 + 8 + 17 + 26)) * 10) / 10, 172.5, '无封面 = 4:3 占位');
  assert.ok(h({ title: '一'.repeat(40) }, 230) > h({ title: '短' }, 230), '长标题两行');
  assert.equal(h({ title: '一'.repeat(80) }, 230), h({ title: '一'.repeat(40) }, 230), '最多 2 行');
  assert.ok(lbcCardHeight({ title: 'x' }, 230, { low: '片段'.repeat(30) }) > h({ title: 'x' }, 230), '低置信度片段算进去');
  assert.equal(lbcColumns(1200), 4); assert.equal(lbcColumns(1200, { cols: 3 }), 3); assert.equal(lbcColumns(400, { narrow: true }), 2); assert.equal(lbcColumns(100), 1);

  // 页面：网格 1210 宽 → 4 列，排名前 4 的卡分别是第 0–3 列的第一个
  const items = Array.from({ length: 10 }, (_, i) => item('n' + i, '笔记 ' + i, { cover: `_archive/n${i}/c.webp`, cover_w: 1080, cover_h: i % 2 ? 1440 : 1920 }));
  const plugin = { settings: { hiddenCats: [], catalogColumns: 0 }, openLibraryPage() {}, saveSettings() {} };
  const P = await openCatalog({ items, plugin });
  const grid = P.$('.lbc-grid');
  grid.clientWidth = 1210; P.A.resize.trigger(1210); await tick(5);
  const cols = () => P.$$('.lbc-grid-inner > .lbc-col');
  assert.equal(cols().length, 4);
  assert.deepEqual(cols().map(c => c.querySelector('.lbc-card')._lbItem.id), ['n0', 'n1', 'n2', 'n3'], '第一排就是第 1–4 篇');
  const els = new Map(P.cards().map(c => [c._lbItem.id, c]));
  const plan = () => cols().map(c => c.querySelectorAll('.lbc-card').map(x => x._lbItem.id));
  const plan4 = plan();
  // 改列数：卡片还是原来那些元素，列数变了
  plugin.settings.catalogColumns = 3; P.app.workspace.trigger('link-brain:catalog-prefs');
  assert.equal(cols().length, 3);
  assert.ok(P.cards().every(c => els.get(c._lbItem.id) === c), '卡片没重建（引用相同）');
  plugin.settings.catalogColumns = 0; P.app.workspace.trigger('link-brain:catalog-prefs');
  assert.deepEqual(plan(), plan4, '同宽度下分配确定');
  // 宽度变化导致列数变化才重摆（下一帧）；宽度小变、列数不变不动
  const l0 = P.counts().layout;
  P.A.resize.trigger(1230); await tick(5);
  assert.equal(P.counts().layout, l0, '列数没变不重摆');
  P.A.resize.trigger(700); await tick(5);
  assert.equal(cols().length, 2, '窄了 → 2 列');
  // 打开、离开、再打开：同宽度下每列的 id 序列完全一样
  const Q = await openCatalog({ items, plugin, keepState: true, made: { app: P.app, V: P.V, workspace: P.workspace } });
  Q.$('.lbc-grid').clientWidth = 1210; Q.A.resize.trigger(1210); await tick(5);
  assert.deepEqual(Q.$$('.lbc-grid-inner > .lbc-col').map(c => c.querySelectorAll('.lbc-card').map(x => x._lbItem.id)), plan4);
  // 星标页（.lbc-simple）单列
  const S = await openCatalog({ items: items.map(x => ({ ...x, starred: true })), plugin, starred: true });
  S.$('.lbc-grid').clientWidth = 1210; S.A.resize.trigger(1210); await tick(5);
  S.enter('笔记');
  assert.equal(S.$$('.lbc-grid-inner > .lbc-col').length, 1, '星标页单列列表');
  // 封面异步解码（C11）
  assert.equal(P.card('n0').querySelector('img').decoding, 'async');
  console.log('PASS C9 masonry: lbcAssign shortest-column / leftmost tie, lbcCardHeight cover cap / 4:3 / title lines / snippet, lbcColumns; page 4 cols with first row = top 4, column change keeps card elements, deterministic plan, relayout only when column count changes, starred page single column; covers decode async');
})().catch(e => { console.error(e); process.exit(1); });

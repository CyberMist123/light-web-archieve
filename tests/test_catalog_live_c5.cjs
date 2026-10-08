// 批次 D · L1 C5：目录搜索边打边搜——停顿就出结果（不用按回车）、输入法组字中不搜、选完字 / 回车立刻搜、连打只搜一次、清空立刻恢复；
// warmSearch 空闲时把每篇的检索字段算好（第一下打字不现算 9MB 文本）。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, asset } = require('./_fake_l1.cjs');

(async () => {
  const items = [item('a', '悉尼咖啡地图'), item('b', '悉尼海边徒步'), item('c', '电饭煲鸡肉饭'), item('d', '东京咖啡馆')];
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {} };
  const P = await openCatalog({ items, plugin });
  const s = P.search();
  const rank = () => P.counts().rank;
  assert.equal(s.placeholder, '搜索收藏 · #标签');
  // 停顿后自动出结果
  P.type('悉尼');
  assert.equal(P.ids().length, 4, '还在防抖里');
  await tick(150);
  assert.deepEqual(P.ids(), ['a', 'b'], '停顿就搜（不用回车）');
  // 组字中不搜；compositionend 立刻搜
  s.fire('compositionstart', {});
  s.value = 'kafei'; s.fire('input', { isComposing: true });
  await tick(200);
  assert.deepEqual(P.ids(), ['a', 'b'], '组字中不搜');
  s.value = '咖啡'; s.fire('compositionend', {});
  assert.deepEqual(P.ids(), ['a', 'd'], '选完字立刻搜');
  // 回车：不等防抖
  s.value = '鸡肉'; s.fire('input', {});
  P.enter();
  assert.deepEqual(P.ids(), ['c'], '回车立刻搜');
  // 连续 5 次输入只搜 1 次
  const r0 = rank();
  for (const t of ['东', '东京', '东京咖', '东京咖啡', '东京咖啡馆']) P.type(t);
  await tick(150);
  assert.equal(rank() - r0, 1, '连打只搜一次');
  assert.deepEqual(P.ids(), ['d']);
  // 同一个词不重复搜
  const r1 = rank(); P.type('东京咖啡馆'); await tick(150); assert.equal(rank(), r1);
  // 清空：立刻全部恢复
  P.type('');
  assert.equal(P.ids().length, 4, '清空立刻恢复');
  // 防抖还没触发就离开：回来补跑一次
  P.type('电饭煲');
  const Q = await openCatalog({ items, plugin, keepState: true, made: { app: P.app, V: P.V, workspace: P.workspace } });
  assert.equal(Q.search().value, '电饭煲');
  assert.deepEqual(Q.ids(), ['c'], '上次离开时防抖还没触发：恢复后补跑');
  // warmSearch：空闲分片算好每篇的 searchFields（之后第一次搜不再现算）
  const W = new Function(asset('catalog-search.js') + ';return {warmSearch, searchCache, corpusCache}')();
  const list = Array.from({ length: 95 }, (_, i) => ({ title: '第' + i, search_fields: { body: 'x' + i } }));
  const w = W.warmSearch(list, { chunk: 40, idle: f => setTimeout(f, 0) });
  assert.equal(w.done, false);
  await tick(20);
  assert.ok(w.done && list.every(it => W.searchCache.has(it)), '全部预热');
  assert.ok(W.corpusCache.has(list), '最后算一次 corpusText');
  const list2 = [{ title: 'y' }, { title: 'z' }];
  const w2 = W.warmSearch(list2, { chunk: 1, idle: f => setTimeout(f, 0) }); w2.cancel(); await tick(10);
  assert.ok(!W.searchCache.has(list2[1]), 'cancel 之后停');
  console.log('PASS C5 live search: debounce then search without Enter, IME composition waits / compositionend searches, Enter immediate, 5 inputs → 1 rank, same text no rerun, clear restores, pending input re-run on return; warmSearch chunks + corpus + cancel');
})().catch(e => { console.error(e); process.exit(1); });

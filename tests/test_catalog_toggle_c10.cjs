// 批次 D · L1 C10 / C6：勾选只改这张卡的 class（不整卡换新、不重摆），Esc 只在本页是活动标签页时清多选；
// 换搜索词 / 切大类回到结果开头，点星 / 勾选 / 刷新不动滚动。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, ev } = require('./_fake_l1.cjs');

(async () => {
  const items = Array.from({ length: 8 }, (_, i) => item('n' + i, '笔记 ' + i, { cover: `_archive/n${i}/c.webp`, cover_w: 1080, cover_h: 1440, kind: i % 3 ? 'image' : 'video' }));
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {} };
  const P = await openCatalog({ items, plugin });
  const { A, dom } = P;
  const cards0 = P.cards(), img0 = P.card('n2').querySelector('img');
  const pos0 = cards0.map(c => [c.parentNode, c.parentNode.childNodes.indexOf(c)]);
  const c0 = P.counts();
  // 点勾选圈：同一个元素、同一张封面 img；不重排、不重摆；其他卡位置都没变
  P.card('n2').querySelector('.lbc-check').onclick(ev());
  assert.equal(P.card('n2'), cards0[2]); assert.equal(P.card('n2').querySelector('img'), img0);
  assert.ok(P.card('n2').classList.contains('is-selected'));
  assert.equal(P.card('n2').querySelector('.lbc-check').getAttribute('aria-pressed'), 'true');
  const c1 = P.counts();
  assert.equal(c1.layout - c0.layout, 0); assert.equal(c1.rank - c0.rank, 0); assert.equal(c1.build - c0.build, 0);
  assert.deepEqual(P.cards().map(c => [c.parentNode, c.parentNode.childNodes.indexOf(c)]), pos0, '其他卡的父节点和下标都没变');
  assert.equal(P.$('.lbc-selbar').hidden, false);
  assert.ok(P.$('.lbc-wrap').classList.contains('is-selecting'));
  assert.equal(P.$('.lbc-selcount').textContent, '已选 1 篇');
  P.card('n5').querySelector('.lbc-check').onclick(ev());
  assert.equal(P.$('.lbc-selcount').textContent, '已选 2 篇');
  // C15：栏上按钮的顺序和文字；Esc 提示只有一处
  assert.deepEqual(P.$$('.lbc-selbar button').map(b => b.textContent), ['收藏选中', '给 AI（存成选集）', '导出资料包', '更多…', '删除选中 (2)', '退出多选']);
  assert.equal(P.$$('.lbc-selhint').length, 1);
  // Esc：本页不是活动标签页 → 不清；是 → 全部取消、各卡已重画
  const esc = (target = dom.document.body) => dom.document.dispatchEvent({ type: 'keydown', key: 'Escape', target });
  P.app.workspace.activeLeaf = { view: { containerEl: dom.document.body.createEl('div') } };
  esc(); assert.equal(P.$$('.lbc-card.is-selected').length, 2, '别的标签页是活动的：不清');
  A.activate();
  esc(P.search()); assert.equal(P.$$('.lbc-card.is-selected').length, 2, '焦点在搜索框：不清');
  esc();
  assert.equal(P.$$('.lbc-card.is-selected').length, 0, '全部取消');
  assert.equal(P.$('.lbc-selbar').hidden, true);
  assert.equal(P.card('n2'), cards0[2], '取消也不换卡');
  assert.equal(P.counts().layout - c0.layout, 0);

  // C6：滚到 3000 后换搜索词 → 回到结果开头；点星 / 勾选 / refresh 不动滚动
  const sc = A.host, grid = P.$('.lbc-grid'), top = P.$('.lbc-top');
  top.offsetHeight = 200;
  const place = st => { sc.scrollTop = st; grid._rect = { top: 400 - st, height: 5000 }; sc._rect = { top: 0, height: 800 }; };
  place(3000);
  P.enter('笔记 1');
  assert.equal(sc.scrollTop, 400 - 200 - 8, 'scrollTop = gridTop − 顶栏高 − 8');
  place(3000);
  P.card('n1').querySelector('.lbc-check').onclick(ev());
  P.card('n1').querySelector('.lbc-check').onclick(ev());
  assert.equal(sc.scrollTop, 3000, '勾选不动滚动');
  P.card('n1').querySelector('.lbc-star').onclick(ev()); await tick(5);
  assert.equal(sc.scrollTop, 3000, '点星不动滚动');
  // 已经在开头：不动
  place(100); P.cat('视频').onclick(); assert.equal(sc.scrollTop, 100);
  place(3000); P.cat('视频').onclick(); assert.equal(sc.scrollTop, 192, '切大类回到开头');
  console.log('PASS C10 / C15 / C6: check toggles only state classes (same card / img, no rank / layout / build), selbar buttons + one Esc hint, Esc only on the active leaf and not from the search box, scroll back to results on query / filter change only');
})().catch(e => { console.error(e); process.exit(1); });

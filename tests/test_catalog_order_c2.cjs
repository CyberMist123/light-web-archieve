// 批次 D · L1 C2 / X17：点 ☆ 卡片不飞到最前——排名只在结果集的 key 变了才重算；星标 ×1.15 的规则推迟到下一次换筛选 / 换词生效。
// 「已收藏」就地筛选（不再跳星标页），在里面取消收藏卡片留在原位。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, ev } = require('./_fake_l1.cjs');

(async () => {
  const items = ['a', 'b', 'c', 'd', 'e', 'f'].map((id, i) => item(id, '笔记 ' + id, { kind: i % 2 ? 'video' : 'image' }));
  const starCalls = [];
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() { throw new Error('不该再跳星标页'); },
    async starNotes(ids, on) { starCalls.push([ids, on]); return { ok: true, results: ids.map(id => ({ item_id: id, status: 'ok', starred: on, error: '' })), done: ids.length, failed: 0, catalog_patched: false }; } };
  const P = await openCatalog({ items, plugin });
  const order = P.ids();
  assert.deepEqual(order, ['a', 'b', 'c', 'd', 'e', 'f']);
  const rank0 = P.counts().rank, layout0 = P.counts().layout;
  // 点第 4 张的 ☆：顺序不变，那张卡变 ★，不重新打分、不重摆
  P.card('d').querySelector('.lbc-star').onclick(ev()); await tick(5);
  assert.deepEqual(P.ids(), order, '点星后顺序不变');
  assert.ok(P.card('d').querySelector('.lbc-star').classList.contains('is-on'));
  assert.equal(P.card('d').querySelector('.lbc-star').getAttribute('aria-pressed'), 'true');
  assert.equal(P.counts().rank, rank0, '不重新打分');
  assert.equal(P.counts().layout, layout0, '不重摆');
  // 别处（笔记页）点了另一篇的星：link-brain:star 事件只换 ★
  P.app.workspace.trigger('link-brain:star', 'f', true);
  assert.deepEqual(P.ids(), order);
  assert.ok(P.card('f').querySelector('.lbc-star').classList.contains('is-on'));
  // 换筛选再换回来：星标 ×1.15 生效，两篇星标排在最前
  P.cat('视频').onclick(); P.cat('视频').onclick();
  assert.deepEqual(P.ids().slice(0, 2).sort(), ['d', 'f'], '下一次 key 变化时星标排前');
  // 多选「收藏选中」同样不改顺序
  const before = P.ids();
  for (const id of ['a', 'b']) P.card(id).querySelector('.lbc-check').onclick(ev());
  P.$('.lbc-starsel').onclick(); await tick(5);
  assert.deepEqual(starCalls.at(-1), [['a', 'b'], true]);
  assert.deepEqual(P.ids(), before, '批量收藏不改顺序');
  P.$('.lbc-clrsel').onclick();

  // X17：「已收藏」就地筛选（不调 openLibraryPage）、封面墙不切列表、tab 带 is-active、再点恢复；状态存进 star
  const starTab = () => P.cat('已收藏');
  starTab().onclick();
  assert.deepEqual(P.ids().sort(), ['a', 'b', 'd', 'f']);
  assert.ok(starTab().classList.contains('is-active'));
  assert.equal(P.$('.lbc-wrap').classList.contains('lbc-simple'), false, '保持封面墙');
  assert.equal(JSON.parse(globalThis.__lbState['lb:catalog']).star, true, '状态存进 star');
  // 在「已收藏」里取消收藏：卡片留在原位，显示 ☆；换筛选后才消失
  P.card('d').querySelector('.lbc-star').onclick(ev()); await tick(5);
  assert.ok(P.card('d'), '卡片留在原位');
  assert.ok(!P.card('d').querySelector('.lbc-star').classList.contains('is-on'));
  // 1021 范围单选：点「视频」= 换成只看视频（不再和「已收藏」叠加）；再回「已收藏」时取消收藏的那篇才消失
  P.cat('视频').onclick();
  assert.ok(P.cat('视频').classList.contains('is-active') && !starTab().classList.contains('is-active'), '单选：视频亮、已收藏灭');
  starTab().onclick();
  assert.ok(!P.card('d'), '换筛选后消失');
  starTab().onclick();
  assert.equal(P.ids().length, 6, '再点一次恢复全部');
  // 星标页上点「已收藏」/「全部」回目录（走 LB.openPage）
  const S = await openCatalog({ items, plugin, starred: true, frontmatter: { '目录.md': { 'lb-page': 'catalog' } }, files: { '目录.md': '---\nlb-page: catalog\n---\n' } });
  S.cat('已收藏').onclick(); await tick(5);
  assert.equal(S.app.workspace.opened.at(-1)[0], '目录.md');
  console.log('PASS C2 / X17: star / batch star / star event keep order (no rerank, no relayout), next filter change applies the boost; 已收藏 filters in place, unstar keeps the card until the next filter change; starred page buttons go back to the catalog');
})().catch(e => { console.error(e); process.exit(1); });

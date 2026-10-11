// 批次 D · L1 C8：空状态分三种 + 数据读不到；选了大类 / 已收藏时计数显示「x / y 篇」。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog } = require('./_fake_l1.cjs');
const { makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');
const { code } = require('./_fake_l1.cjs');

(async () => {
  const calls = [];
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {}, openImportModal() { calls.push('import'); }, syncNow() { calls.push('sync'); }, async refreshCatalog() { calls.push('refresh'); } };
  // ① 库里没有收藏：两句 + 两个按钮
  let P = await openCatalog({ items: [], plugin });
  assert.ok(P.$('.lbc-empty').textContent.startsWith('还没有收藏：点标题旁的「+」导入网址，或登录后同步收藏'));
  const btns = P.$$('.lbc-empty button');
  assert.deepEqual(btns.map(b => b.textContent), ['导入网址', '立即同步收藏']);
  await btns[0].onclick(); await btns[1].onclick(); await tick(5);
  assert.deepEqual(calls, ['import', 'sync']);
  // ② 「已收藏」里一篇都没有
  const items = [item('a', '悉尼咖啡地图', { cats: ['吃的'], kind: 'image' }), item('b', '电饭煲鸡肉饭', { cats: ['吃的'] }), item('c', '悉尼徒步', { kind: 'video' })];
  P = await openCatalog({ items, plugin });
  P.cat('已收藏').onclick();
  assert.equal(P.$('.lbc-empty-text').textContent, '还没有收藏的：鼠标停在卡片上，点右上角的 ☆');
  P.cat('已收藏').onclick();
  // ⑤ 选了大类：计数「x / y 篇」
  P.cat('吃的').onclick();
  assert.equal(P.$('.lbc-count').textContent, '筛出 2 篇（共 3）');
  // ③ 有筛选、有搜索词、没结果：文案带筛选；[清除筛选] 清筛选、留搜索词
  P.cat('视频').onclick();
  assert.equal(P.$('.lbc-empty-text').textContent, '「吃的 · 视频」里没有内容');
  P.enter('悉尼');
  assert.equal(P.$('.lbc-empty-text').textContent, '「吃的 · 视频」里没有「悉尼」');
  assert.deepEqual(P.$$('.lbc-empty button').map(b => b.textContent), ['清除筛选', '去问收藏搜「悉尼」']);
  P.$$('.lbc-empty button')[0].onclick();
  assert.deepEqual(P.ids().sort(), ['a', 'c'], '筛选清掉、搜索词还在');
  assert.equal(P.search().value, '悉尼');
  assert.ok(P.cat('全部').classList.contains('is-active'));
  // ④ 只有搜索词
  P.enter('不存在的词');
  assert.equal(P.$('.lbc-empty-text').textContent, '没找到「不存在的词」，试试更短的关键词');
  assert.ok(P.$('.lbc-empty .lbc-ask-tip'), '保留「去问收藏」提示');
  // ⑥ 数据读不到：一句话 + [刷新目录]，点了调插件 refreshCatalog
  {
    delete globalThis.__lbState; delete globalThis.__lbListeners;
    const made = makeApp({ files: { '_archive/sync-status.json': '{}' }, plugin });
    const A = dataviewBlock({ dom: makeDom(), app: made.app, code: code() });
    await A.run();
    assert.equal(A.q('.lbc-empty-text').textContent, '目录数据还没生成：点右上「…」→ 刷新目录');
    const b = A.q('.lbc-nodata button');
    assert.equal(b.textContent, '刷新目录');
    await b.onclick(); await tick(5);
    assert.equal(calls.at(-1), 'refresh');
    // 手机上只写字
    delete globalThis.__lbState;
    const madeM = makeApp({ files: { '_archive/sync-status.json': '{}' }, isMobile: true });
    const M = dataviewBlock({ dom: makeDom(), app: madeM.app, code: code() });
    await M.run();
    assert.ok(M.q('.lbc-empty-text').textContent.startsWith('目录数据还没生成'));
    assert.equal(M.q('.lbc-nodata button'), null);
  }
  // 手机上空库：只说一句，没有按钮
  P = await openCatalog({ items: [], isMobile: true });
  assert.equal(P.$('.lbc-empty-text').textContent, '还没有收藏。导入和同步要在电脑上做。');
  assert.equal(P.$$('.lbc-empty button').length, 0);
  console.log('PASS C8 empty states: empty library with import / sync buttons, no starred, filter (+ query) with 清除筛选 keeping the query, query only, missing data with 刷新目录; count x / y with a category');
})().catch(e => { console.error(e); process.exit(1); });

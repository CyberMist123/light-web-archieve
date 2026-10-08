// 批次 D · L1 N9（目录侧）：笔记里点 #标签 → 插件写 pendingCatalogQuery → 目录读完清空、清掉旧筛选、按标签筛（tags ∪ hashtags），不恢复旧滚动。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog } = require('./_fake_l1.cjs');

(async () => {
  const items = [
    item('a', '悉尼咖啡地图', { tags: ['咖啡'], hashtags: ['悉尼生活'] }),
    item('b', '悉尼海边徒步', { tags: ['悉尼生活'], kind: 'video' }),
    item('c', '电饭煲鸡肉饭', { tags: ['做饭'], cats: ['吃的'] }),
  ];
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {} };
  // 上次离开时有大类和视频筛选、滚到了 900
  globalThis.__lbState = { 'lb:catalog': JSON.stringify({ ts: 1, q: '', input: '', cat: '吃的', media: 'video', scrollTop: 900 }) };
  plugin.pendingCatalogQuery = '#悉尼生活';
  const P = await openCatalog({ items, plugin, keepState: true });
  await tick(10);
  assert.equal(P.search().value, '#悉尼生活');
  assert.deepEqual(P.ids().sort(), ['a', 'b'], 'tags 或 hashtags 里有它的都出来');
  assert.ok(P.cat('全部').classList.contains('is-active'), '旧筛选全清');
  assert.equal(plugin.pendingCatalogQuery, '', '读完清空');
  assert.equal(P.A.host.scrollTop, 0, '不恢复旧滚动');
  assert.notEqual(P.dom.document.activeElement, P.search(), '不 focus 搜索框（手机不弹键盘）');
  // onReuse 路径：标签页本来就开着目录，Dataview 重跑时接住
  P.cat('吃的').onclick();
  plugin.pendingCatalogQuery = '#做饭';
  await P.A.rerun();
  assert.equal(P.search().value, '#做饭'); assert.deepEqual(P.ids(), ['c']);
  assert.ok(P.cat('全部').classList.contains('is-active'));
  // 事件路径：当前标签页就是目录，只发 link-brain:catalog-query
  plugin.pendingCatalogQuery = '#咖啡';
  P.app.workspace.trigger('link-brain:catalog-query');
  assert.deepEqual(P.ids(), ['a']);
  assert.equal(plugin.pendingCatalogQuery, '');
  // 星标页：starOnly 保持
  plugin.pendingCatalogQuery = '#悉尼生活';
  const S = await openCatalog({ items: items.map(x => ({ ...x, starred: x.id === 'a' })), plugin, starred: true });
  assert.deepEqual(S.ids(), ['a'], '星标页里只看星标的');
  console.log('PASS N9 pending tag query: first build / onReuse / event paths, filters cleared (starred page keeps starOnly), tags ∪ hashtags, pending consumed, no scroll restore, no focus');
})().catch(e => { console.error(e); process.exit(1); });

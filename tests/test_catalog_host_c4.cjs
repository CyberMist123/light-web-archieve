// 批次 D · L1 C4 + C1 / X14c / C18 静态：目录页挂在 dv.container 后面的 host 上，Dataview 后台重跑不打断输入。
// ① 首建后容器空着，host 是它的兄弟，wrap 在 host 里  ② 聚焦搜索框打字、连续 3 次重跑：焦点 / 字 / wrap 都在，不重读
// ③ 041aca9 的资产上同一用例是红的（重跑一次就失焦）  ④ component 卸载 → host 摘掉  ⑤ 残留的同 role host 不叠出第二个
// ⑥ 整页重建（新容器）3 秒内：焦点和选区还给新的搜索框  ⑦ 卡片因数据变了重建、标签框开着：整个搬进新卡，字还在
'use strict';
const assert = require('node:assert/strict');
const shell = require('./_obsidian_shell.cjs');
const { makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');
const { DATA, tick, item, catalogData, openCatalog, ev, asset } = require('./_fake_l1.cjs');

(async () => {
  const items = [item('a', '悉尼咖啡地图'), item('b', '悉尼海边徒步'), item('c', '电饭煲鸡肉饭', { cats: ['吃的'] })];
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {} };
  const P = await openCatalog({ items, plugin });
  const { A, V, dom } = P;
  // ①
  const host = A.container.nextSibling, wrap = P.$('.lbc-wrap');
  assert.equal(A.container.children.length, 0, '容器本身空着');
  assert.ok(host.classList.contains('lb-page-host') && host.dataset.lbRole === 'catalog');
  assert.equal(wrap.parentNode, host);
  // C1 / X14c / C18：样式在 head，两条 overflow 覆盖都在；没有串到问收藏页的 .lbchat 规则；颜色走共享变量
  const css = dom.document.getElementById('lbc-style').textContent;
  assert.ok(css.includes('.lb-catalog .block-language-dataviewjs{overflow:visible!important;}'));
  assert.ok(css.includes('.markdown-source-view.lb-catalog .cm-embed-block.cm-lang-dataviewjs,.markdown-source-view.lb-catalog .cm-embed-block.cm-lang-dataviewjs:hover{overflow:visible!important;}'));
  assert.ok(!css.includes('.lbchat'), '没有 .lbchat 规则（挂 head 后会串到问收藏页）');
  for (const hex of ['#fff8eb', '#a86513', '#e8d8bc', '#e08a1e', '#e5484d']) assert.ok(!css.includes(hex), 'C18 不再写死 ' + hex);
  assert.ok(css.includes('var(--lb-warn-bg)') && css.includes('var(--lb-danger)'));
  assert.ok(css.includes('.lbc-wrap .lbc-star{') && css.includes('.lbc-wrap .lbc-badges{'), 'X14c：跨页撞名的选择器加 .lbc-wrap 前缀');
  assert.equal(P.$('.lbc-selbar').parentNode, P.$('.lbc-top'), 'C1：多选栏在顶栏里');
  assert.equal(P.$('.lbc-top').lastElementChild, P.$('.lbc-selbar'), '顶栏最后一个子节点');
  // ②
  const search = P.search();
  search.focus(); search.value = 'ka'; search.setSelectionRange(2, 2); search.fire('input', {});
  const reads = V.reads[DATA];
  for (let i = 0; i < 3; i++) await A.rerun();
  assert.equal(dom.document.activeElement, search, '重跑 3 次焦点还在');
  assert.equal(search.value, 'ka');
  assert.equal(P.$('.lbc-wrap'), wrap, 'wrap 是同一个对象');
  assert.equal(V.reads[DATA], reads, '版本没变不重读 catalog-data');
  assert.equal(A.section.querySelectorAll('.lb-page-host').length, 1);
  // ③ 改前代码是红的（同一用例）
  if (shell.revAvailable('041aca9')) {
    delete globalThis.__lbState; delete globalThis.__lbListeners;
    const dom2 = makeDom();
    const made = makeApp({ files: { [DATA]: JSON.stringify(catalogData(items)), '_archive/sync-status.json': '{}' }, plugin: { settings: { hiddenCats: [] } } });
    const B = dataviewBlock({ dom: dom2, app: made.app, code: shell.pageAssets('catalog', { rev: '041aca9' }) });
    await B.run();
    const s2 = B.container.querySelector('.lbc-search'); s2.focus(); s2.value = 'ka';
    await B.rerun();
    assert.notEqual(dom2.document.activeElement, s2, '041aca9：重跑一次就失焦（红线还在）');
  }
  // ④ 卸载 → host 摘掉
  A.component.unload();
  assert.ok(!host.isConnected, '卸载时 host 跟着摘掉');
  // ⑤ 残留 host（上一个渲染器没卸干净）：首建时摘掉，只剩一个
  {
    delete globalThis.__lbState; delete globalThis.__lbListeners;
    const dom3 = makeDom();
    const made = makeApp({ files: { [DATA]: JSON.stringify(catalogData(items)), '_archive/sync-status.json': '{}' }, plugin });
    const C = dataviewBlock({ dom: dom3, app: made.app, code: P.A.run && require('./_fake_l1.cjs').code() });
    const stale = dom3.document.createElement('div'); stale.className = 'lb-page-host'; stale.dataset.lbRole = 'catalog'; C.container.after(stale);
    await C.run();
    assert.equal(C.section.querySelectorAll('.lb-page-host').length, 1, '只剩一个 host');
    assert.ok(!stale.isConnected);
    // ⑥ 整页重建（section 重画 / CM 重建 widget）：3 秒内把焦点和选区还给新的搜索框
    const s3 = C.section.querySelector('.lbc-search');
    s3.focus(); s3.value = 'kafe'; s3.setSelectionRange(2, 3); s3.fire('input', {}); s3.fire('keyup', {});
    await C.recreate(); await tick(5);
    const s4 = C.section.querySelector('.lbc-search');
    assert.notEqual(s4, s3, '新容器整页重建');
    assert.equal(C.section.querySelectorAll('.lb-page-host').length, 1);
    assert.equal(dom3.document.activeElement, s4, '新搜索框拿到焦点');
    assert.equal(s4.value, 'kafe', '字还在（页面状态）');
    assert.deepEqual([s4.selectionStart, s4.selectionEnd], [2, 3], '选区还原');
  }
  // ⑦ 卡片重建时标签框跟着搬
  {
    const Q = await openCatalog({ items, plugin });
    Q.card('a').oncontextmenu(ev());
    Q.pick('编辑标签').onclick(ev());
    const form = Q.card('a').querySelector('form.lbc-tagform');
    const field = form.querySelector('input');
    field.value = '咖啡, 正在打'; field.setSelectionRange(4, 4);
    assert.equal(Q.dom.document.activeElement, field);
    const oldCard = Q.card('a');
    Q.V.set(DATA, JSON.stringify(catalogData([item('a', '悉尼咖啡地图（改了标题）'), items[1], items[2]])));
    await Q.A.rerun(); await tick(5);
    const newCard = Q.card('a');
    assert.notEqual(newCard, oldCard, '标题变了：卡片重建');
    assert.equal(newCard.querySelector('form.lbc-tagform'), form, '标签框整个搬进新卡');
    assert.equal(form.querySelector('input').value, '咖啡, 正在打', '字还在');
    assert.equal(Q.dom.document.activeElement, field, '焦点还在标签框');
    assert.equal(field.selectionStart, 4);
  }
  console.log('PASS C4 host: container empty + host sibling, 3 reruns keep focus / value / wrap / no reread (041aca9 red), unload removes host, stale host removed, recreate restores focus + selection, open tag form moves into rebuilt card; C1 overflow rules + selbar in .lbc-top; X14c head style without .lbchat; C18 shared colors');
})().catch(e => { console.error(e); process.exit(1); });

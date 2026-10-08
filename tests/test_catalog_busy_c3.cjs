// 批次 D · L1 C3 / CM3 / C7：收藏 / 批量收藏 / 删除 / 拖附件 / 导出都有「正在…」，乐观更新失败回滚，结果走 Notice（不用 window.alert / confirm）；
// 点星写完 catalog-data 后 LB.data.adopt（带后端报回的 catalog_stat），下次重跑 0 读、不重摆。
'use strict';
const assert = require('node:assert/strict');
const { DATA, tick, item, catalogData, deferred, openCatalog, ev, asset } = require('./_fake_l1.cjs');

(async () => {
  const items = ['a', 'b', 'c', 'd', 'e', 'f'].map(id => item(id, '悉尼 ' + id));
  let star = null, starCalls = [];
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {}, openAttachments() {},
    starNotes(ids, on) { starCalls.push([ids, on]); star = deferred(); return star.p; } };
  const P = await openCatalog({ items, plugin });
  const { A, V } = P;
  // ① 单星：点完立刻 ★ + .is-starring，按钮 disabled；reject → 回滚，Notice 说原因
  const s = () => P.card('c').querySelector('.lbc-star');
  s().onclick(ev()); await tick(0);
  assert.ok(s().classList.contains('is-on') && s().firstChild.textContent === '★', '点完立刻 ★');
  assert.ok(P.card('c').classList.contains('is-starring')); assert.equal(s().disabled, true);
  s().onclick(ev()); await tick(0);
  assert.equal(starCalls.length, 1, 'busy 时再点不重复调');
  star.reject(new Error('EBUSY')); await tick(5);
  assert.ok(!s().classList.contains('is-on') && s().firstChild.textContent === '☆', '回滚');
  assert.ok(!P.card('c').classList.contains('is-starring')); assert.equal(s().disabled, false);
  assert.ok(A.notices.at(-1).includes('收藏没保存上，可重试：EBUSY'), A.notices.at(-1));
  assert.equal(A.alerts.length, 0);
  // ② 批量：勾 5 篇点「收藏选中」→ starNotes 只调 1 次、参数 5 个 id；等待期间按钮「正在收藏 5 篇…」、删除灰；1 篇失败 → 4 亮 1 回滚
  for (const id of ['a', 'b', 'c', 'd', 'e']) P.card(id).querySelector('.lbc-check').onclick(ev());
  P.$('.lbc-starsel').onclick(); await tick(0);
  assert.equal(starCalls.length, 2); assert.deepEqual(starCalls[1], [['a', 'b', 'c', 'd', 'e'], true]);
  assert.equal(P.$('.lbc-starsel').textContent, '正在收藏 5 篇…');
  assert.equal(P.$('.lbc-delsel').disabled, true); assert.equal(P.$('.lbc-clrsel').disabled, false, '「退出多选」保留可点');
  assert.ok(P.card('a').classList.contains('is-starring'));
  star.resolve({ ok: false, results: ['a', 'b', 'c', 'd', 'e'].map(id => ({ item_id: id, status: id === 'e' ? 'failed' : 'ok', starred: id !== 'e', error: id === 'e' ? '文件被占用' : '' })), done: 4, failed: 1, catalog_patched: false });
  await tick(5);
  assert.deepEqual(['a', 'b', 'c', 'd', 'e'].map(id => P.card(id).querySelector('.lbc-star').classList.contains('is-on')), [true, true, true, true, false]);
  assert.equal(A.notices.at(-1), '已收藏 4 篇；1 篇没收藏上：文件被占用');
  assert.equal(P.$('.lbc-starsel').textContent, '收藏选中');
  assert.equal(P.$('.lbc-delsel').disabled, false);
  P.$('.lbc-clrsel').onclick();

  // ③ CM3：点星写了 catalog-data（patch）→ adopt 之后重跑 0 读、0 重摆，插件缓存版本 = 新 stat
  {
    let doneStar = null;
    plugin.starNotes = async (ids, on) => {
      const d = JSON.parse(V.get(DATA)); for (const it of d.items) if (ids.includes(it.id)) it.starred = on;
      V.set(DATA, JSON.stringify(d));
      const st = await V.vault.adapter.stat(DATA);
      doneStar = { mtime: st.mtime, size: st.size };
      return { ok: true, results: ids.map(id => ({ item_id: id, status: 'ok', starred: on, error: '' })), done: ids.length, failed: 0, catalog_patched: true, catalog_stat: doneStar };
    };
    V.resetCounts();
    const l0 = P.counts().layout;
    P.card('f').querySelector('.lbc-star').onclick(ev()); await tick(5);
    await A.rerun();
    assert.equal(V.reads[DATA] || 0, 0, 'adopt 之后重跑不读 catalog-data');
    assert.equal(P.counts().layout - l0, 0, '也不重摆');
    assert.equal(plugin.catalogCache.version, `${doneStar.mtime}:${doneStar.size}`);
    // written 对不上（夜跑在放锁之后又写过）：不 adopt，走正常 update
    plugin.starNotes = async (ids, on) => {
      const d = JSON.parse(V.get(DATA)); for (const it of d.items) if (ids.includes(it.id)) it.starred = on;
      V.set(DATA, JSON.stringify(d));
      const st = await V.vault.adapter.stat(DATA);
      V.set(DATA, JSON.stringify({ ...d, built_at: '2026-10-09T04:00:00+10:00', count: d.items.length }));   // 别人（夜跑重建）又写了一次
      return { ok: true, results: ids.map(id => ({ item_id: id, status: 'ok', starred: on })), catalog_patched: true, catalog_stat: { mtime: st.mtime, size: st.size } };
    };
    V.resetCounts();
    P.card('a').querySelector('.lbc-star').onclick(ev()); await tick(5);
    await A.rerun();
    assert.equal(V.reads[DATA], 1, 'stat 对不上：重读一次');
  }

  // ④ 删除：页内确认 → 等待期间「删除中…」+ .is-deleting，再点不重复；结果按条摘除；全程不 alert
  {
    let del = null, delCalls = 0;
    plugin.deleteItems = ids => { delCalls++; del = deferred(); return del.p; };
    const Q = await openCatalog({ items, plugin });
    Q.A.window.confirm = () => true;
    for (const id of ['a', 'b']) Q.card(id).querySelector('.lbc-check').onclick(ev());
    Q.$('.lbc-delsel').onclick(); await tick(5);
    assert.equal(delCalls, 1);
    assert.equal(Q.$('.lbc-delsel').textContent, '删除中…'); assert.equal(Q.$('.lbc-delsel').disabled, true);
    assert.ok(Q.card('a').classList.contains('is-deleting'));
    Q.$('.lbc-delsel').onclick(); await tick(5);
    assert.equal(delCalls, 1, '再点一次不重复删');
    del.resolve({ results: [{ item_id: 'a', status: 'deleted' }, { item_id: 'b', status: 'missing' }] }); await tick(5);
    assert.ok(!Q.card('a'), '删掉的摘掉');
    assert.ok(Q.card('b') && !Q.card('b').classList.contains('is-deleting') && Q.card('b').classList.contains('is-selected'), '没删掉的保持选中');
    assert.ok(Q.A.notices.at(-1).startsWith('已删 1 篇；1 篇没删掉：库里没有这一篇'), Q.A.notices.at(-1));
    assert.equal(Q.A.alerts.length, 0); assert.equal(Q.A.confirms.length, 0, '确认框走 LB.confirm（这里退回 window.confirm 桩，不记 confirms）');
  }
  // ⑤ 拖文件：dragenter（Files）→ .is-droptarget；dragleave → 摘；drop → .is-busy 直到 attachFile resolve
  {
    let att = null;
    plugin.attachFile = (id, fp) => { att = deferred(); att.args = [id, fp]; return att.p; };
    const Q = await openCatalog({ items, plugin });
    const c = Q.card('d');
    c.ondragenter({ dataTransfer: { types: ['Files'] }, preventDefault() {} });
    assert.ok(c.classList.contains('is-droptarget'));
    c.ondragleave({});
    assert.ok(!c.classList.contains('is-droptarget'));
    c.ondragenter({ dataTransfer: { types: ['text/plain'] }, preventDefault() {} });
    assert.ok(!c.classList.contains('is-droptarget'), '不是文件不理');
    c.ondrop({ dataTransfer: { files: [{ path: 'C:/x/资料.pdf' }] }, preventDefault() {}, stopPropagation() {} }); await tick(5);
    assert.ok(c.classList.contains('is-busy')); assert.equal(c.dataset.busy, '正在挂…');
    assert.deepEqual(att.args, ['d', 'C:/x/资料.pdf']);
    att.resolve({ text: '', warning: null }); await tick(5);
    assert.ok(!c.classList.contains('is-busy'));
    assert.equal(Q.A.notices.at(-1), '附件已挂到《悉尼 d》并加入搜索');
  }
  // ⑥ 导出（C7 / CM2）：页面只发一条「正在导出」并收起；失败说原因
  {
    plugin.exportArchiveBundle = async () => { throw new Error('磁盘满了'); };
    const Q = await openCatalog({ items, plugin });
    Q.card('a').oncontextmenu(ev()); Q.pick('导出').onclick(ev()); await tick(5);
    const prog = Q.A.noticeLog.filter(n => n.message.startsWith('正在导出'));
    assert.equal(prog.length, 1); assert.ok(prog[0].hidden, '进行中提示收起了');
    assert.equal(Q.A.notices.at(-1), '导出没完成：磁盘满了');
  }
  // 静态：页面源码里不再有 window.alert / window.confirm / 顶部小字
  const src = asset('catalog-view.js');
  assert.ok(!/window\.alert\(/.test(src) && !/window\.confirm\(/.test(src));
  assert.ok(!src.includes('lbc-status') && !src.includes('importStatus'), 'C7：顶部那行小字删了');
  console.log('PASS C3 / CM3 / C7: optimistic star + busy + rollback with reason, batch star = one call with busy selbar and partial rollback, adopt(written) → rerun 0 reads / 0 relayout (stale written → reread), delete busy + single call + per-row result via Notice, drop target / busy, export progress hidden + failure reason, no alert / confirm / status line');
})().catch(e => { console.error(e); process.exit(1); });

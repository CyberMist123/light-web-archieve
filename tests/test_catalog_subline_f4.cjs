// 批次 D · L1 F4：标题下那行拆三块（计数只是字 · 可能相关跳到那一组 · 更新开同步记录）；页面数据比磁盘旧就自动换新；
// update 失败不推进版本、下次重跑重试；跨设备：同步记录比本机目录数据新很多时说一句。
'use strict';
const assert = require('node:assert/strict');
const { DATA, tick, item, catalogData, openCatalog } = require('./_fake_l1.cjs');

(async () => {
  const items = [item('a', '悉尼咖啡地图', { pinyin: 'xi ni ka fei di tu' }), item('b', '东京拉面', { pinyin: 'dong jing la mian' })];
  let syncLogs = 0;
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {}, openSyncLog() { syncLogs++; } };
  const data = catalogData(items, { pinyin_chars: { 西: 'xi', 尼: 'ni' } });
  const P = await openCatalog({ data, plugin });
  const { A, V, dom } = P;
  // 计数：不可点、没有 role；没有可能相关时不渲染那块
  assert.equal(P.$('.lbc-count').textContent, '2 篇');
  assert.equal(P.$('.lbc-count').onclick, undefined); assert.equal(P.$('.lbc-count').getAttribute('role'), null);
  assert.equal(P.$('.lbc-possible-link').hidden, true);
  // 「更新」→ openSyncLog
  await P.$('.lbc-updated').onclick(); await tick(5);
  assert.equal(syncLogs, 1);
  // 有可能相关组：点了滚到那一组标题（减顶栏高 − 8）
  P.enter('西尼');
  const link = P.$('.lbc-possible-link');
  assert.equal(link.hidden, false); assert.equal(link.textContent, '可能相关 1');
  const sc = A.host, head = P.$('.lbc-possible-head');
  sc.scrollTop = 0; sc._rect = { top: 0, height: 800 }; head._rect = { top: 2400, height: 30 }; P.$('.lbc-top').offsetHeight = 180;
  link.onclick();
  assert.equal(sc.scrollTop, 2400 - 180 - 8);
  assert.equal(head.tabIndex, -1); assert.equal(dom.document.activeElement, head, '标题拿到焦点（不滚）');
  P.enter('');

  // 新鲜度：catalog-data 被改写（条数和 built_at 都变）+ modify 事件 → 900ms 后「更新」和计数跟上
  V.set(DATA, JSON.stringify(catalogData([...items, item('c', '新同步进来的')], { built_at: '2026-10-09T06:30:00+10:00' })));
  await tick(900);
  assert.equal(P.$('.lbc-count').textContent, '3 篇');
  assert.match(P.$('.lbc-updated').textContent, /^更新 10\/09 \d\d:30$/);
  assert.equal(A.container.__lbView.version, `${(await V.vault.adapter.stat(DATA)).mtime}:${(await V.vault.adapter.stat(DATA)).size}`, '版本跟上');
  // 看不见时发 modify：不读文件；露出来（活动标签页切过来）才读
  A.leafObj.view.containerEl.hidden = true;
  V.resetCounts();
  V.set(DATA, JSON.stringify(catalogData([...items], { built_at: '2026-10-09T07:00:00+10:00' })));
  await tick(900);
  assert.equal(V.reads[DATA] || 0, 0, '看不见不读');
  A.leafObj.view.containerEl.hidden = false;
  A.activate(); await tick(10);
  assert.equal(V.reads[DATA], 1, '切回来才读');
  assert.equal(P.$('.lbc-count').textContent, '2 篇');
  // update 失败：不推进版本，下次重跑重试成功
  const realRead = V.vault.adapter.read; let fail = 1;
  V.vault.adapter.read = async p => { if (p === DATA && fail-- > 0) throw new Error('EBUSY'); return realRead(p); };
  const handlers = V.handlers.modify; V.handlers.modify = [];   // 只让重跑这条路径去更新
  V.set(DATA, JSON.stringify(catalogData([...items, item('d', '第四篇')], { built_at: '2026-10-09T08:00:00+10:00' })));
  const vBefore = A.container.__lbView.version;
  await A.rerun();
  assert.equal(A.container.__lbView.version, vBefore, 'update 失败不推进版本');
  assert.ok(A.container.__lbView.lastError, '记下 lastError');
  assert.equal(P.$('.lbc-count').textContent, '2 篇');
  await A.rerun();
  assert.equal(P.$('.lbc-count').textContent, '3 篇', '第二次重跑成功');
  V.handlers.modify = handlers; V.vault.adapter.read = realRead;
  // 跨设备：同步记录 last_success 比 built_at 晚 2 小时、本机 stat 没变 → 「这台设备上的目录数据较旧」
  const Q = await openCatalog({ data: catalogData(items, { built_at: '2026-10-08T05:00:00+10:00' }), plugin,
    files: { '_archive/sync-status.json': JSON.stringify({ state: 'ready', last_success: '2026-10-08T07:00:00+10:00', updated_at: '2026-10-08T07:00:00+10:00' }) } });
  assert.equal(Q.$('.lbc-stale').hidden, false);
  assert.ok(Q.$('.lbc-stale').title.includes('本机目录数据还是'), Q.$('.lbc-stale').title);
  const R = await openCatalog({ data: catalogData(items, { built_at: '2026-10-08T06:58:00+10:00' }), plugin,
    files: { '_archive/sync-status.json': JSON.stringify({ state: 'ready', last_success: '2026-10-08T07:00:00+10:00' }) } });
  assert.equal(R.$('.lbc-stale').hidden, true, '差不到 10 分钟不说');
  console.log('PASS F4 subline: count is plain text, possible link only with a possible group and jumps to its head, 更新 → openSyncLog; catalog-data modify refreshes when visible / waits until shown; failed update keeps the version and retries on next rerun; stale-device hint');
})().catch(e => { console.error(e); process.exit(1); });

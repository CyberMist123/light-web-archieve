// 批次 D · L1 C16 / X9：回收站页——挂 host（重跑不闪、不重读）、页头导航、恢复 / 彻底删除的 busy 与 Notice、空状态、读不到不报红、手机只读。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const TRASH = '_archive/trash-data.json';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const CODE = asset('lb-page-lib.js') + '\n' + asset('trash-view.js');
const rows = [
  { item_id: 'xhs-a', title: '悉尼咖啡地图', deleted_at: '2026-10-07T10:00:00+10:00', cover: '_trash/a/c.webp', restorable: true, has_files: true },
  { item_id: 'xhs-b', title: '旧孤儿', restorable: false, has_files: true },   // 没有 deleted_at
];
async function open({ files, plugin, isMobile = false } = {}) {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const made = makeApp({ files: { [TRASH]: JSON.stringify({ items: rows }), '_archive/.keep': '', ...(files || {}) }, plugin, isMobile,
    frontmatter: { '目录.md': { 'lb-page': 'catalog' }, '收藏搜索.md': { 'lb-page': 'chat' } } });
  made.V.set('目录.md', '---\nlb-page: catalog\n---\n'); made.V.set('收藏搜索.md', '---\nlb-page: chat\n---\n');
  const dom = makeDom();
  const A = dataviewBlock({ dom, app: made.app, code: CODE });
  await A.run();
  return { A, dom, ...made };
}

(async () => {
  // 首建 + 重跑：host 结构、版本没变不重读、wrap 同一个
  let calls = [];
  let pending = null;
  const plugin = { trashAction: (kind, ids) => { calls.push([kind, ids]); return new Promise((res, rej) => { pending = { res, rej }; }) }, refreshCatalog: async () => {} };
  let { A, dom, V, app } = await open({ plugin });
  assert.equal(A.container.children.length, 0, '页面挂在 host 上');
  assert.ok(A.container.nextSibling.classList.contains('lb-page-host'));
  assert.ok(dom.document.getElementById('lb-trash-style'), '样式挂 head');
  const wrap = A.q('.lbt-wrap');
  assert.equal(A.q('.lbt-title').textContent, '回收站');
  assert.deepEqual(A.qa('.lb-page-nav button').map(b => b.textContent), ['浏览收藏', '问收藏']);
  assert.equal(A.qa('.lbt-row').length, 2);
  assert.ok(A.qa('.lbt-row')[1].querySelector('.lbt-meta').textContent.includes('旧孤儿笔记'), 'deleted_at 缺失不抛错');
  assert.ok(A.q('.lbt-tools button'), '有文件时才建「清空回收站」');
  const reads = V.reads[TRASH];
  await A.rerun();
  assert.equal(A.q('.lbt-wrap'), wrap, '重跑：同一个 wrap');
  assert.equal(V.reads[TRASH], reads, '版本没变不重读');
  // 页头导航走 LB.openPage（按 frontmatter 找文件，不靠插件）
  A.qa('.lb-page-nav button')[1].onclick();
  await tick(5);
  assert.equal(app.workspace.opened.at(-1)[0], '收藏搜索.md');

  // 恢复：按钮「恢复中…」且 disabled，连点只调一次；成功 → 这一行没了，Notice 带《标题》和「打开」
  const restore = () => A.qa('.lbt-row')[0].querySelectorAll('button').find(b => b.textContent === '恢复' || b.textContent === '恢复中…');
  const btn = restore();
  btn.onclick(); await tick(0);
  assert.equal(btn.textContent, '恢复中…'); assert.equal(btn.disabled, true);
  btn.onclick(); await tick(0);
  assert.equal(calls.length, 1, '连点只调一次');
  pending.res({ results: [{ item_id: 'xhs-a', status: 'restored', visible_note: 'Web/悉尼咖啡地图.md' }] }); await tick(5);
  assert.equal(A.qa('.lbt-row').length, 1, '恢复的那一行摘掉');
  const n = A.noticeLog.at(-1);
  assert.ok(n.message.includes('已恢复《悉尼咖啡地图》'), n.message);
  assert.equal(n.buttons[0].label, '打开');
  n.buttons[0].click(); await tick(5);
  assert.equal(app.workspace.opened.at(-1)[0], 'Web/悉尼咖啡地图.md');
  assert.equal(A.alerts.length, 0);

  // 彻底删除：先页内确认（拒绝就不动）；失败 → 按钮恢复、Notice 说原因
  A.window.confirm = () => false;
  const purge = () => A.qa('.lbt-row')[0].querySelectorAll('button').find(b => /彻底删除|删除中/.test(b.textContent));
  await purge().onclick(); await tick(0);
  assert.equal(calls.length, 1, '没确认不调');
  A.window.confirm = () => true;
  const pb = purge(); pb.onclick(); await tick(5);
  assert.equal(pb.textContent, '删除中…');
  pending.rej(new Error('EBUSY 文件被占用')); await tick(5);
  assert.equal(pb.textContent, '彻底删除'); assert.equal(pb.disabled, false);
  assert.ok(A.notices.at(-1).includes('没删掉：EBUSY'), A.notices.at(-1));
  pb.onclick(); await tick(5); pending.res({ results: [{ item_id: 'xhs-b', status: 'purged' }] }); await tick(5);
  assert.equal(A.qa('.lbt-row')[0].querySelector('.lbt-meta').textContent, '文件已彻底删除');
  assert.equal(A.qa('.lbt-row')[0].querySelectorAll('button').length, 0);
  assert.ok(A.notices.at(-1).startsWith('已彻底删除 1 篇'));
  assert.equal(A.q('.lbt-tools button'), null, '没有文件了：「清空回收站」收起');
  assert.equal(A.alerts.length, 0, '全程不用 window.alert');

  // 空列表：「回收站是空的」，没有清空按钮
  ({ A } = await open({ plugin, files: { [TRASH]: JSON.stringify({ items: [] }) } }));
  assert.ok(A.q('.lbt-empty').textContent.startsWith('回收站是空的'));
  assert.equal(A.q('.lbt-tools button'), null);
  // trash-data 缺失：一句可读的话 + [刷新目录]，不抛错
  {
    delete globalThis.__lbState;
    const made = makeApp({ files: { '_archive/.keep': '' }, plugin });
    const B = dataviewBlock({ dom: makeDom(), app: made.app, code: CODE });
    await B.run();
    assert.ok(B.q('.lbt-empty').textContent.startsWith('回收站还没有数据：刷新一次目录就会生成'));
    assert.equal(B.q('.lbt-empty button').textContent, '刷新目录');
  }
  // 手机：没有按钮，页首写只读那句
  ({ A } = await open({ plugin: null, isMobile: true }));
  assert.equal(A.qa('.lbt-row button').length, 0, '手机不建按钮');
  assert.equal(A.q('.lbt-tools button'), null);
  assert.ok(A.q('.lbt-note').textContent.startsWith('手机上只能看'));
  // 源码：不用 window.alert / confirm
  assert.ok(!/window\.(alert|confirm)\(/.test(asset('trash-view.js')));
  console.log('PASS trash page (C16): host + rerun reuse, page nav via LB.openPage, restore busy / single call / Notice with 打开, purge confirm + failure keeps button + reason, empty / missing data states, mobile read-only');
})().catch(e => { console.error(e); process.exit(1); });

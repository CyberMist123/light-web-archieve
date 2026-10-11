// 10-11 她：「根据 AI 建议刷新目录会闪一下，不太舒服」——index-data.json 变了（点了加进索引 / 后台按内容归完 / 改了归类）要原地更新：
//   ① 选中这一类的篇目没变 → 网格一动不动（不重摆、不摘卡片）、树只改数字（行元素不换）、滚动位置不变
//   ② 篇目变了 → 只摘走离开的那几张卡，其余卡片 / 列元素原样；任何一帧网格里都不会没有卡片（不闪白）
//   ③ 同一份内容通知两次（文件监听 + 插件回调）→ 第二次什么都不做
// 外壳 page-reading，亮色；截图不需要
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const CATS = ['悉尼', '做饭', 'AI', '学习', '穿搭', '家居', '旅行'];
function makeIndex(items, { dropFromHome = 0, aiCount = null, proposals = 2 } = {}) {
  const idOf = it => Number(it.id.slice(-4));
  const cat = it => CATS[idOf(it) % CATS.length];
  const ids = pred => items.filter(pred).map(it => it.id);
  let home = ids(it => cat(it) === '做饭' && idOf(it) % 2 === 0);
  home = home.slice(dropFromHome);
  const cook = ids(it => cat(it) === '做饭').filter(i => !home.includes(i) ? true : true);
  let ai = ids(it => cat(it) === 'AI');
  if (aiCount != null) ai = ai.slice(0, aiCount);
  const rows = [];
  const add = (path, items_, extra = {}) => { const parts = path.split('/'); rows.push({ path, name: parts.at(-1), parent: parts.slice(0, -1).join('/'), depth: parts.length, line: rows.length + 3,
    tags: [], explicit: false, wiki: false, count: items_.length, self_count: items_.length, items: items_, children: [], ...extra }); };
  add('做饭', cook, { children: ['做饭/家常菜', '做饭/烘焙'] });
  add('做饭/家常菜', home, { facets: [{ name: '红烧', items: home.slice(0, 4), count: Math.min(4, home.length) }] });
  add('做饭/烘焙', ids(it => cat(it) === '做饭' && idOf(it) % 2 === 1));
  add('AI', ai);
  for (const c of ['悉尼', '学习', '家居', '旅行']) add(c, ids(it => cat(it) === c));
  for (let k = 0; k < 30; k++) add('长树' + k, []);              // 树够长，能在左栏里滚
  const unc = ids(it => cat(it) === '穿搭');
  return { version: 1, code_version: 't', file: '索引.md', total: items.length, classified: items.length - unc.length, catalog_built_at: '2026-10-08T05:09:12+10:00',
    roots: rows.filter(r => !r.parent).map(r => r.path), nodes: rows, unclassified: { count: unc.length, items: unc }, warnings: [], comments: [], wiki: {},
    text_ai: { ok: true }, assign: {}, proposals: [{ id: 'p1', name: '穿搭灵感', parent: '', kind: 'leftover', count: unc.length, loose: unc.length, items: unc, examples: [] },
      { id: 'p2', name: '红烧系列', parent: '做饭/家常菜', kind: 'split', count: 3, loose: 0, items: home.slice(0, 3), examples: [] }].slice(0, proposals),
    classify: { ai_ok: true, model: 'm', done: items.length, total: items.length, pending: 0, work: 0, spent: { yuan: 0.3 } } };
}

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 160 });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 700 } });
    const files = { '索引.md': '- 做饭\n', '_archive/index-data.json': JSON.stringify(makeIndex(data.items)) };
    const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, files,
      plugin: { methods: { indexAccept: { result: { ok: true, message: '已写进' } }, indexRebuild: { result: null } } } });
    await page.evaluate(() => [...document.querySelectorAll('.lbc-cats .lbc-cat')].find(b => b.textContent === '索引').click()); await S.settle();
    await page.evaluate(() => [...document.querySelectorAll('.lbi-row')].find(r => r.dataset.path === '做饭').querySelector('.lbi-label').click()); await S.settle();
    await page.evaluate(() => [...document.querySelectorAll('.lbi-row')].find(r => r.dataset.path === '做饭/家常菜').querySelector('.lbi-label').click()); await S.settle();
    await S.scrollTo(260); await S.settle();
    await page.evaluate(() => { const p = document.querySelector('.lbi-panel'); p.scrollTop = 120; });
    // 记号 + 观察：卡片 / 列 / 树行做记号；每一帧数网格里的卡片；记下被摘下来的卡片
    const arm = () => page.evaluate(() => {
      const W = window;
      W.__mark = { removedCards: 0, minCards: Infinity, frames: 0, stop: false };
      for (const el of document.querySelectorAll('.lbc-grid .lbc-card, .lbc-grid .lbc-col, .lbi-row')) el.dataset.mk = '1';
      const mo = new MutationObserver(list => { for (const m of list) for (const n of m.removedNodes) if (n.nodeType === 1) {
        if (n.classList.contains('lbc-card') && !n.isConnected) W.__mark.removedCards++;
        if (!n.isConnected) W.__mark.removedCards += n.querySelectorAll ? [...n.querySelectorAll('.lbc-card')].length : 0; } });
      mo.observe(document.querySelector('.lbc-grid'), { childList: true, subtree: true });
      W.__mark.mo = mo;
      const tick = () => { if (W.__mark.stop) return; W.__mark.frames++; W.__mark.minCards = Math.min(W.__mark.minCards, document.querySelectorAll('.lbc-grid .lbc-card').length); requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
    });
    const read = () => page.evaluate(() => { const W = window; W.__mark.stop = true; W.__mark.mo.disconnect();
      const perf = (globalThis.__lbPerf || {}).catalog?.counts || {};
      return { removedCards: W.__mark.removedCards, minCards: W.__mark.minCards, frames: W.__mark.frames,
        keptCards: document.querySelectorAll('.lbc-grid .lbc-card[data-mk="1"]').length, cards: document.querySelectorAll('.lbc-grid .lbc-card').length,
        keptCols: document.querySelectorAll('.lbc-grid .lbc-col[data-mk="1"]').length, cols: document.querySelectorAll('.lbc-grid .lbc-col').length,
        keptRows: document.querySelectorAll('.lbi-row[data-mk="1"]').length, rows: document.querySelectorAll('.lbi-row').length,
        panelScroll: document.querySelector('.lbi-panel').scrollTop, scroll: document.querySelector('.markdown-preview-view').scrollTop,
        aiCount: [...document.querySelectorAll('.lbi-row')].find(r => r.dataset.path === 'AI')?.querySelector('.lbi-n')?.textContent,
        layout: perf.layout, reloads: perf.indexReload || 0, chips: [...document.querySelectorAll('.lbi-chip')].length }; });
    const before = await page.evaluate(() => ({ layout: ((globalThis.__lbPerf || {}).catalog?.counts || {}).layout, panelScroll: document.querySelector('.lbi-panel').scrollTop,
      scroll: document.querySelector('.markdown-preview-view').scrollTop, cards: document.querySelectorAll('.lbc-grid .lbc-card').length }));
    assert.ok(before.panelScroll > 0 && before.scroll > 0 && before.cards > 5, `准备好：左栏和页面都滚过 ${JSON.stringify(before)}`);
    // ① 别的类篇数变了、一条建议没了、状态变了；选中的「家常菜」篇目没变
    await arm();
    await S.setFile('_archive/index-data.json', JSON.stringify(makeIndex(data.items, { aiCount: 5, proposals: 1 })));
    await page.waitForTimeout(450); await S.settle(60);
    const a = await read();
    assert.equal(a.removedCards, 0, `① 没摘任何卡片 ${JSON.stringify(a)}`);
    assert.equal(a.layout, before.layout, `① 没重摆网格 ${JSON.stringify(a)}`);
    assert.ok(a.keptCards === a.cards && a.keptCols === a.cols, `① 卡片 / 列元素原样 ${JSON.stringify(a)}`);
    assert.ok(a.keptRows === a.rows, `① 树的行元素原样（只改了数字）${JSON.stringify(a)}`);
    assert.equal(a.aiCount, '5', '① 树上的篇数换新了');
    assert.equal(a.chips, 1, '① 建议新增少了一条');
    assert.equal(a.panelScroll, before.panelScroll, '① 左栏滚动没动');
    assert.ok(Math.abs(a.scroll - before.scroll) <= 1, `① 页面滚动没动 ${a.scroll} vs ${before.scroll}`);
    assert.ok(a.minCards === before.cards, `① 任何一帧卡片都在 ${JSON.stringify(a)}`);
    // ③ 同一份内容再通知一次：什么都不做
    const reloads = a.reloads;
    await S.setFile('_archive/index-data.json', JSON.stringify(makeIndex(data.items, { aiCount: 5, proposals: 1 })));
    await page.waitForTimeout(450); await S.settle();
    assert.equal((await page.evaluate(() => ((globalThis.__lbPerf || {}).catalog?.counts || {}).indexReload || 0)), reloads, '③ 内容没变不重画');
    // ② 选中这一类少了 2 篇（比如挪进了刚加进索引的子类）：只摘这 2 张，其余原样，不闪白
    await arm();
    await S.setFile('_archive/index-data.json', JSON.stringify(makeIndex(data.items, { aiCount: 5, proposals: 1, dropFromHome: 2 })));
    await page.waitForTimeout(450); await S.settle(60);
    const b = await read();
    assert.equal(b.cards, before.cards - 2, `② 少了 2 张 ${JSON.stringify(b)}`);
    assert.ok(b.removedCards <= 2 + 0, `② 只摘走离开的那 2 张（没有整批摘下再挂回）${JSON.stringify(b)}`);
    assert.ok(b.minCards >= b.cards, `② 没有一帧是空的 ${JSON.stringify(b)}`);
    assert.ok(b.keptRows === b.rows && b.panelScroll === before.panelScroll, `② 树没重建、左栏滚动没动 ${JSON.stringify(b)}`);
    assert.deepEqual(await S.pageErrors(), []);
    console.log('PASS index_inplace_ui：索引更新原地换——篇目不变 0 重摆 0 摘卡、树只改数字、滚动不动；篇目变了只摘走离开的卡、不闪白；同一内容不重画');
    await page.close();
  } finally {
    await browser.close();
  }
})().catch(e => { console.error('FAIL index_inplace_ui', e && e.stack || e); process.exit(1); });

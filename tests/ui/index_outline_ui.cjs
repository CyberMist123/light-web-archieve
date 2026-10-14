// 1015 目录页（她 C2/C3/D/H + 第二批 ui 车）：Obsidian 外壳里驱动真实页面脚本
//   ① 索引大纲树：拖一行到别的行中间 = 放进去当子类、上沿 = 插到前面、拖到「全部」= 提到第一级；第 3 级下面不让放（红框、不调）
//      双击改名（Enter 提交 / Esc 取消）；右键「改名 / 合并到… / 挪到… / 提到第一级 / 在 索引.md 里改」；改完有「撤销」
//   ② 写法提示：level=info（第 4 级并进第 3 级）不出 ⚠；细分「其他」照常能点
//   ③ 卡片角标：多选圈左上、⭐右上，都只在悬停 / 多选时出现；已收藏常驻小黄星（透明底）；选中只一圈贴封面的框
//   ④ 多选栏「按 Esc 退出多选」在最左；⑤ 系列帖标题露后半截、悬停（title）看全名
// 截图落 LWA_QA_DIR
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

function makeIdx(items) {
  const ids = items.map(it => it.id);
  const rows = [];
  const add = (path, its, extra = {}) => {
    const parts = path.split('/');
    rows.push({ path, name: parts[parts.length - 1], parent: parts.slice(0, -1).join('/'), depth: parts.length, line: rows.length + 3,
      tags: [], explicit: false, wiki: false, count: its.length, self_count: its.length, items: its, children: [], ...extra });
  };
  add('美食', ids.slice(0, 40), { children: ['美食/菜谱', '美食/综合'] });
  add('美食/菜谱', ids.slice(0, 30), { children: ['美食/菜谱/牛排'],
    facets: [{ name: '空气炸锅', count: 6, items: ids.slice(0, 6) }, { name: '其他', count: 3, items: ids.slice(6, 9), other: true }] });
  add('美食/菜谱/牛排', ids.slice(0, 5), { hints: ['血源'] });
  add('美食/综合', ids.slice(30, 40));
  add('游戏', ids.slice(40, 60), { children: ['游戏/塞尔达'] });
  add('游戏/塞尔达', ids.slice(40, 50));
  add('工程', ids.slice(60, 70));
  const roots = rows.filter(r => !r.parent).map(r => r.path);
  return { version: 1, code_version: 't', generated_at: '2026-10-15T03:00:00+11:00', file: '索引.md', draft_file: '索引.草稿.md', source_hash: 'x',
    catalog_built_at: '2026-10-08T05:09:12+10:00', total: items.length, classified: 70, roots, nodes: rows,
    unclassified: { count: items.length - 70, items: ids.slice(70) }, cats_order: [...roots, '未归类'],
    warnings: [{ line: 40, level: 'info', text: '第 40 行是第 4 级（最多 3 级）：「血源」这些并进「牛排」当关键词，不另算一类' }],
    comments: [], draft: null, wiki: {}, text_ai: { ok: true, why: '', model: 'm' }, assign: {}, item_tags: {}, proposals: [],
    classify: { ai_ok: true, model: 'm', done: 70, total: 70, pending: 0, work: 0 } };
}

const PLUGIN = { confirmAnswer: true, methods: {
  indexEdit: { result: { ok: true, message: '已改好', undo: 'e1', path: '游戏/牛排' } }, indexRebuild: { result: null },
  indexAssign: { result: { ok: true, message: 'ok' } }, starNotes: { result: { results: [] } },
} };
const calls = async (S, name) => (await S.calls()).filter(c => c[0] === name);
const row = (page, path) => page.locator(`.lbi-panel .lbi-row[data-path="${path}"]`);

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 80, starredEvery: 7 });
  // 系列帖：同一作者三篇共用长前缀
  for (const [k, ep] of [[1, '第 1 集 开场'], [2, '第 2 集 选角'], [3, '第 3 集 结局']]) Object.assign(data.items[k], { title: `【悉尼法学院申请全流程记录】${ep}`, author: '同一个作者' });
  const idx = makeIdx(data.items);
  try {
    for (const theme of ['light', 'dark']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme, data, plugin: PLUGIN,
        files: { '索引.md': '\t美食\n', '_archive/index-data.json': JSON.stringify(idx) } });
      // ③ 角标
      const card = page.locator('.lbc-grid .lbc-card').nth(4);
      const pos = await card.evaluate(c => {
        const r = c.getBoundingClientRect(), ck = c.querySelector('.lbc-check').getBoundingClientRect(), st = c.querySelector('.lbc-star').getBoundingClientRect();
        return { checkLeft: ck.left - r.left, starRight: r.right - st.right, op: getComputedStyle(c.querySelector('.lbc-star')).opacity, ckop: getComputedStyle(c.querySelector('.lbc-check')).opacity };
      });
      assert.ok(pos.checkLeft <= 12 && pos.starRight <= 12, `${theme}：多选圈左上、⭐右上 ${JSON.stringify(pos)}`);
      assert.ok(pos.op === '0' && pos.ckop === '0', `${theme}：不悬停时两个都不出 ${JSON.stringify(pos)}`);
      await card.hover(); await S.settle(200);
      assert.equal(await card.evaluate(c => getComputedStyle(c.querySelector('.lbc-star')).opacity), '1', `${theme}：悬停出⭐`);
      const starred = page.locator('.lbc-grid .lbc-card:has(.lbc-star.is-on)').first();
      const st = await starred.evaluate(c => { const s = getComputedStyle(c.querySelector('.lbc-star')); return { op: s.opacity, bg: s.backgroundColor }; });
      assert.ok(st.op === '1' && /rgba\(0, 0, 0, 0\)|transparent/.test(st.bg), `${theme}：已收藏常驻小黄星（透明底）${JSON.stringify(st)}`);
      // ⑤ 系列帖标题
      const series = await page.evaluate(() => [...document.querySelectorAll('.lbc-ctitle.is-series')].map(e => [e.textContent, e.title]));
      assert.ok(series.length === 3 && series.every(([t, full]) => t.startsWith('…第') && full.startsWith('【悉尼法学院')), `${theme}：系列帖露后半截 + 悬停全名 ${JSON.stringify(series)}`);
      // ④ 多选：Esc 提示在最左；选中只一圈框
      await card.locator('.lbc-check').click(); await S.settle(120);
      const bar = await page.evaluate(() => { const b = document.querySelector('.lbc-selbar'); return [...b.children].filter(e => !e.hidden).map(e => e.className.split(' ')[0]); });
      assert.equal(bar[0], 'lbc-selhint', `${theme}：「按 Esc 退出多选」在最左 ${bar}`);
      const ring = await card.evaluate(c => { const s = getComputedStyle(c.querySelector('.lbc-cover, .lbc-nocover')); return { outline: s.outlineStyle, shadow: s.boxShadow }; });
      assert.ok(ring.outline === 'none' && /3px/.test(ring.shadow), `${theme}：选中 = 贴着封面一圈 ${JSON.stringify(ring)}`);
      await S.screenshot(`outline-cards-select-${theme}`);
      await page.keyboard.press('Escape'); await S.settle(80);
      // ① 大纲树
      await page.evaluate(() => [...document.querySelectorAll('.lbc-cats .lbc-cat')].find(b => b.textContent === '索引').click()); await S.settle();
      for (const p of ['美食', '美食/菜谱']) { await page.evaluate(p => [...document.querySelectorAll('.lbi-row')].find(r => r.dataset.path === p).querySelector('.lbi-label').click(), p); await S.settle(); }
      assert.ok(!(await page.evaluate(() => document.querySelector('.lbi-bar').textContent)).includes('写法要看一眼'), `${theme}：info 级不出 ⚠`);
      const facets = await page.evaluate(() => [...document.querySelectorAll('.lbi-facet')].map(b => b.dataset.name));
      assert.deepEqual(facets, ['空气炸锅', '其他'], `${theme}：细分收「其他」`);
      assert.equal(await row(page, '美食/菜谱').getAttribute('draggable'), 'true', `${theme}：节点能拖`);
      assert.equal(await row(page, '美食/菜谱/牛排').locator('.lbi-label').getAttribute('title'), '包括 血源', `${theme}：第 4 级关键词悬停看`);
      // 拖「牛排」到「游戏」中间 = 放进「游戏」
      await row(page, '美食/菜谱/牛排').dragTo(row(page, '游戏'), { targetPosition: { x: 60, y: 14 } }); await S.settle(150);
      let ed = await calls(S, 'indexEdit');
      assert.deepEqual(ed.at(-1).slice(1), ['move', '美食/菜谱/牛排', { to: '游戏' }], `${theme}：拖到中间 = 放进去 ${JSON.stringify(ed)}`);
      const notes = await S.notices();
      assert.ok(notes.some(n => n.buttons.includes('撤销')), `${theme}：改完能撤销 ${JSON.stringify(notes)}`);
      // 拖到「工程」上沿 = 插到它前面（第一级）
      await row(page, '美食/综合').dragTo(row(page, '工程'), { targetPosition: { x: 60, y: 2 } }); await S.settle(150);
      ed = await calls(S, 'indexEdit');
      assert.deepEqual(ed.at(-1).slice(1), ['move', '美食/综合', { to: '', before: '工程' }], `${theme}：上沿 = 插到前面 ${JSON.stringify(ed.at(-1))}`);
      // 拖到「全部」= 提到第一级
      await row(page, '游戏').locator('.lbi-fold').click(); await S.settle();
      await row(page, '游戏/塞尔达').dragTo(row(page, ''), { targetPosition: { x: 60, y: 14 } }); await S.settle(150);
      ed = await calls(S, 'indexEdit');
      assert.deepEqual(ed.at(-1).slice(1), ['move', '游戏/塞尔达', { to: '' }], `${theme}：拖到全部 = 提到第一级`);
      // 第 3 级下面不让放：不调
      const n0 = (await calls(S, 'indexEdit')).length;
      await row(page, '工程').dragTo(row(page, '美食/菜谱/牛排'), { targetPosition: { x: 60, y: 14 } }); await S.settle(150);
      assert.equal((await calls(S, 'indexEdit')).length, n0, `${theme}：超过 3 级不调`);
      // 双击改名
      await row(page, '工程').locator('.lbi-label').dblclick(); await S.settle(60);
      await page.fill('.lbi-rename', '工程笔记'); await page.keyboard.press('Enter'); await S.settle(150);
      ed = await calls(S, 'indexEdit');
      assert.deepEqual(ed.at(-1).slice(1), ['rename', '工程', { name: '工程笔记' }], `${theme}：双击改名`);
      await row(page, '游戏').locator('.lbi-label').dblclick(); await S.settle(60);
      await page.keyboard.press('Escape'); await S.settle(60);
      assert.equal((await calls(S, 'indexEdit')).length, ed.length, `${theme}：Esc 取消改名不调`);
      // 右键菜单 → 合并到…
      await row(page, '美食').locator('.lbi-label').click(); await S.settle(120);
      await row(page, '美食/综合').locator('.lbi-label').click({ button: 'right' }); await S.settle(60);
      const menu = await page.evaluate(() => [...document.querySelectorAll('.menu .menu-item-title, .lbc-menu .lbc-menu-item')].map(e => e.textContent));
      assert.deepEqual(menu.slice(0, 4), ['改名', '合并到…', '挪到…（放进另一个分类下面）', '提到第一级'], `${theme}：节点右键菜单 ${menu}`);
      await S.screenshot(`outline-tree-menu-${theme}`);
      await page.evaluate(() => [...document.querySelectorAll('.menu .menu-item, .lbc-menu .lbc-menu-item')].find(e => e.textContent.includes('合并到')).click()); await S.settle();
      await page.fill('.lbi-pick-dialog input', '菜谱'); await page.keyboard.press('Enter'); await S.settle(150);
      ed = await calls(S, 'indexEdit');
      assert.deepEqual(ed.at(-1).slice(1), ['merge', '美食/综合', { to: '美食/菜谱' }], `${theme}：合并到`);
      // 截一张拖拽中的落点样子
      await page.evaluate(() => { const r = [...document.querySelectorAll('.lbi-row')].find(x => x.dataset.path === '游戏'); r.classList.add('is-drop-into'); });
      await S.screenshot(`outline-tree-${theme}`);
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS index_outline_ui：大纲树拖拽（放进 / 插前 / 提到第一级 / 超 3 级不放）· 双击改名 · 右键合并 · 撤销 · info 不出 ⚠ · 细分「其他」· 角标左右 + 悬停 + 小黄星 · 选中一圈框 · Esc 提示最左 · 系列帖标题');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error('FAIL index_outline_ui', e && e.stack || e); process.exit(1); });

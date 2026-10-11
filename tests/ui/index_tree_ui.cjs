// 索引树在目录页（Obsidian 外壳：阅读视图 / 亮 · 暗 / 窄屏 / 手机）：
//   ① 顶部分类 = 索引第一级（顺序照索引，0 篇的不出，末尾「未归类」）；固定入口还在，多一个「索引」
//   ② 选中一个大类 → 下面一行二级小标签（带篇数）；吸顶不受影响（|delta| ≤ 1）
//   ③ 10-11「索引」视图：左边可折叠的树（带篇数、默认只展开选中那一支），右边就是卡片网格——点节点右边筛到那些篇，
//      网格上面一行说清选的是什么；树钉在吸顶区下面、自己滚、不露滚动条
//   ④ 上面一行：「未归类 N 篇」· 按内容归类的状态 + 按钮 · 「建议新增」chips（点 = 右边看那几篇 + 加进索引 / 不要）
//   ⑤ AI 建的子类（标「AI 建」，保留 / 不要）· 空分类变淡带 0（删 / 留）· 卡片上「归类…」→ 移到… / 也放进…（选分类小窗，能筛）
//   ⑥ index-data.json 一变（她保存 索引.md / 后台归完）→ 300ms 后换新，卡片元素不重建
//   ⑦ 窄屏 / 手机：树叠在网格上面、没有横向溢出；⑧ 没有 index-data.json（旧后端）照旧按 cats_order，不出「索引」
// 截图落 LWA_QA_DIR（不提交、不必逐张看）
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const CATS = ['悉尼', '做饭', 'AI', '学习', '穿搭', '家居', '旅行'];

let idxFacets = [];
function makeIndexData(items, { rename = null, running = false } = {}) {
  const ids = pred => items.filter(pred).map(it => it.id);
  const idOf = it => Number(it.id.slice(-4));
  const cat = it => CATS[idOf(it) % CATS.length];
  const cook = rename || '做饭';
  const rows = [];
  const add = (path, ids_, extra = {}) => {
    const parts = path.split('/');
    rows.push({ path, name: parts[parts.length - 1], parent: parts.slice(0, -1).join('/'), depth: parts.length, line: rows.length + 6,
      tags: [], explicit: false, wiki: false, count: ids_.length, self_count: ids_.length, items: ids_, children: [], ...extra });
  };
  const cookIds = ids(it => cat(it) === '做饭');
  add(cook, cookIds, { children: [cook + '/家常菜', cook + '/烘焙', cook + '/空气炸锅'], open: true });
  const homeIds = ids(it => cat(it) === '做饭' && idOf(it) % 2 === 0);
  // 10-11 细分标签（多选）：红烧 = 每 4 篇一篇，快手 = 每 3 篇一篇——两个都选 = 同时有（越选越窄）
  const facets = [{ name: '红烧', items: homeIds.filter((_, k) => k % 4 === 0) }, { name: '快手', items: homeIds.filter((_, k) => k % 3 === 0) }, { name: '汤', items: homeIds.slice(0, 2) }]
    .map(f => ({ ...f, count: f.items.length }));
  add(cook + '/家常菜', homeIds, { children: [cook + '/家常菜/红烧肉'], desc: '天天吃的那种', facets });
  idxFacets = facets;
  add(cook + '/家常菜/红烧肉', ids(it => cat(it) === '做饭' && idOf(it) % 4 === 0));
  add(cook + '/烘焙', ids(it => cat(it) === '做饭' && idOf(it) % 4 === 1));
  add(cook + '/空气炸锅', ids(it => cat(it) === '做饭' && idOf(it) % 4 === 3), { virtual: true, proposal: 'v1', line: 0, desc: 'AI 按内容建的子类' });
  add('AI', ids(it => cat(it) === 'AI'), { children: ['AI/伴侣', 'AI/工具'] });
  add('AI/伴侣', ids(it => cat(it) === 'AI' && idOf(it) % 3 === 0), { wiki: true });
  add('AI/工具', ids(it => cat(it) === 'AI' && idOf(it) % 3 !== 0));
  add('旅行', ids(it => cat(it) === '旅行'), { wiki: true, children: ['旅行/成都'] });
  add('旅行/成都', ids(it => cat(it) === '旅行').slice(0, 3));
  for (const c of ['悉尼', '学习', '家居']) add(c, ids(it => cat(it) === c));
  add('空节点', []);
  const unc = ids(it => cat(it) === '穿搭');
  const roots = rows.filter(r => !r.parent).map(r => r.path);
  const assign = {};
  for (const r of rows) for (const i of r.items) if (!rows.some(c => c.parent === r.path && c.items.includes(i))) (assign[i] = assign[i] || []).push(r.path);
  return {
    version: 1, code_version: 'test', generated_at: '2026-10-10T03:00:00+11:00', file: '索引.md', draft_file: '索引.草稿.md',
    source_hash: 'sha256:x' + (rename || ''), catalog_built_at: '2026-10-08T05:09:12+10:00', total: items.length,
    classified: items.length - unc.length, roots, nodes: rows, unclassified: { count: unc.length, items: unc },
    cats_order: [...roots.filter(p => rows.find(r => r.path === p).count), '未归类'],
    warnings: [{ line: 7, text: `第 7 行「${cook}」在第一级重复了（第 6 行已有），合并成一个` }],
    comments: [{ line: 3, text: '需求：最多3级分类，分类可以兼容' }],
    draft: null,
    wiki: { 'AI/伴侣': { file: 'wiki/AI/伴侣.md', exists: true, marked: true, based: 5, new_since: 2, generated_at: '2026-10-10T03:10:00+11:00' },
            '旅行': { file: 'wiki/旅行.md', exists: false, marked: true, based: 0, new_since: 0, generated_at: null } },
    text_ai: { ok: true, why: '', model: 'm' },
    assign,
    item_tags: Object.fromEntries(items.map(it => [it.id, idxFacets.filter(f => f.items.includes(it.id)).map(f => f.name)]).filter(e => e[1].length)),
    proposals: [
      { id: 'p1', name: '穿搭灵感', parent: '', kind: 'leftover', count: unc.length, loose: unc.length, items: unc, examples: [] },
      { id: 'p2', name: '红烧系列', parent: cook + '/家常菜', kind: 'split', count: 3, loose: 0, items: ids(it => cat(it) === '做饭' && idOf(it) % 2 === 0).slice(0, 3), examples: [] },
    ],
    classify: { ai_ok: true, why: '', model: 'fake-flash', done: items.length - 3, total: items.length, pending: 3, work: 3, yuan: 0.02,
      spent: { yuan: 0.31 }, last_run: null, ...(running ? { running: { at: '', done: 40, total: 120, phase: '按内容归类' } } : {}) },
  };
}

const PLUGIN = { confirmAnswer: true, methods: {
  indexUseDraft: { result: { ok: true } }, indexDraft: { result: { ok: true } }, openIndexSuggestions: { result: null }, wikiBuild: { result: null }, indexRebuild: { result: null },
  indexAssign: { result: { ok: true, message: '已移到「烘焙」（只放这一类）', undo: 'u1' } }, indexAccept: { result: { ok: true, message: '已写进', path: '做饭/家常菜/红烧系列' } },
  indexDismiss: { result: { ok: true, message: '不要了' } }, indexEmpty: { result: { ok: true, message: '留着' } }, indexClassify: { result: { ok: true, message: '按内容归好了' } },
  indexFacet: { result: { ok: true, message: '已加上细分标签', undo: 'u3' } },
} };

async function open(browser, { width = 1280, height = 900, theme = 'light', idx, mobile = false, data }) {
  const page = await browser.newPage({ viewport: { width, height } });
  const files = { '索引.md': '- 做饭\n', '索引.草稿.md': '- 吃\n', 'wiki/AI/伴侣.md': '# 伴侣\n' };
  if (idx) files['_archive/index-data.json'] = JSON.stringify(idx);
  const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme, data, files, plugin: PLUGIN, mobile });
  return { page, S };
}
const tabs = page => page.evaluate(() => [...document.querySelectorAll('.lbc-cats .lbc-cat')].map(b => ({ text: b.textContent, on: b.classList.contains('is-active') })));
const chips = page => page.evaluate(() => [...document.querySelectorAll('.lbc-subcats .lbc-subcat')].map(b => ({ text: b.textContent, on: b.classList.contains('is-active'), path: b.dataset.path })));
const cardTitles = page => page.evaluate(() => [...document.querySelectorAll('.lbc-grid .lbc-card .lbc-ctitle')].map(e => e.textContent));
const clickTab = async (page, text) => { await page.evaluate(t => [...document.querySelectorAll('.lbc-cats .lbc-cat')].find(b => b.textContent === t).click(), text); };
const treeRows = page => page.evaluate(() => [...document.querySelectorAll('.lbi-panel .lbi-row')].map(r => ({ path: r.dataset.path, text: r.querySelector('.lbi-label').textContent,
  cls: r.className, acts: [...r.querySelectorAll('.lbi-acts button')].map(b => b.textContent) })));
const clickRow = async (page, path) => { await page.evaluate(p => [...document.querySelectorAll('.lbi-row')].find(n => n.dataset.path === p).querySelector('.lbi-label').click(), path); };
const clickFold = async (page, path) => { await page.evaluate(p => [...document.querySelectorAll('.lbi-row')].find(n => n.dataset.path === p).querySelector('.lbi-fold').click(), path); };
const calls = async (S, name) => (await S.calls()).filter(c => c[0] === name);

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 120 });
  const idx = makeIndexData(data.items);
  const count = path => idx.nodes.find(n => n.path === path).count;
  try {
    for (const theme of ['light', 'dark']) {
      const { page, S } = await open(browser, { theme, idx, data });
      // ① 顶部分类
      const names = (await tabs(page)).map(t => t.text);
      for (const fixed of ['全部', '索引', '今日新增', '已收藏', '视频', '附件']) assert.ok(names.includes(fixed), `${theme}：固定入口「${fixed}」还在 ${names}`);
      assert.deepEqual(names.slice(names.indexOf('附件') + 1), ['做饭', 'AI', '旅行', '悉尼', '学习', '家居', '未归类'], `${theme}：分类 = 索引第一级（0 篇的不出）+ 未归类`);
      // ② 大类 → 二级小标签
      await clickTab(page, '做饭'); await S.settle();
      assert.equal((await cardTitles(page)).length, count('做饭'), `${theme}：点「做饭」只剩这一类`);
      const c = await chips(page);
      assert.ok(c.length >= 2 && c[0].text === `家常菜${count('做饭/家常菜')}`, `${theme}：二级小标签带篇数 ${JSON.stringify(c)}`);
      const c1 = await S.probeSticky({ target: '.lbc-top', by: 600 });
      assert.ok(Math.abs(c1.delta) <= 1, `${theme}：带着二级小标签也吸顶 ${JSON.stringify(c1)}`);
      await S.scrollTo(0);
      // ③ 索引视图：左边树、右边网格
      await clickTab(page, '索引'); await S.settle();
      const lay = await page.evaluate(() => {
        const p = document.querySelector('.lbi-panel'), g = document.querySelector('.lbc-grid'), pr = p.getBoundingClientRect(), gr = g.getBoundingClientRect();
        return { panel: !p.hidden && pr.height > 0, grid: !g.hidden && gr.height > 0, side: pr.right <= gr.left + 1, sub: !!document.querySelector('.lbc-subcats'),
          sbw: getComputedStyle(p).scrollbarWidth, pos: getComputedStyle(p).position, cards: document.querySelectorAll('.lbc-grid .lbc-card').length };
      });
      assert.ok(lay.panel && lay.grid && lay.side && !lay.sub, `${theme}：树在左、网格在右、二级小标签收起 ${JSON.stringify(lay)}`);
      assert.equal(lay.sbw, 'none', `${theme}：树不露滚动条`);
      assert.equal(lay.pos, 'sticky', `${theme}：树钉住`);
      assert.equal(lay.cards, count('做饭'), `${theme}：进索引视图保留刚才选的「做饭」`);
      let rows = await treeRows(page);
      assert.equal(rows[0].text, '全部120', `${theme}：第一行 = 全部 + 篇数`);
      assert.ok(rows.find(r => r.path === '做饭').cls.includes('is-current'), `${theme}：选中的那行标出来`);
      assert.ok(rows.find(r => r.path === '做饭/家常菜') && !rows.find(r => r.path === 'AI/伴侣'), `${theme}：默认只展开选中的那一支`);
      assert.ok(rows.find(r => r.path === '∅未归类' && r.text === `未归类${idx.unclassified.count}`), `${theme}：未归类在最后`);
      const empty = rows.find(r => r.path === '空节点');
      assert.ok(empty.cls.includes('is-empty') && empty.text === '空节点0' && empty.acts.join() === '删,留', `${theme}：空分类变淡、0、删 / 留 ${JSON.stringify(empty)}`);
      const virt = rows.find(r => r.path === '做饭/空气炸锅');
      assert.ok(virt.cls.includes('is-virtual') && /AI 建/.test(virt.text) && virt.acts.slice(0, 2).join() === '保留,不要', `${theme}：AI 建的子类 ${JSON.stringify(virt)}`);
      await clickFold(page, 'AI'); await S.settle();
      rows = await treeRows(page);
      assert.ok(rows.find(r => r.path === 'AI/伴侣' && /wiki/.test(r.text)), `${theme}：展开 AI，wiki 小标 ${JSON.stringify(rows.map(r => r.text))}`);
      await clickRow(page, '做饭/家常菜'); await S.settle();
      assert.equal((await cardTitles(page)).length, count('做饭/家常菜'), `${theme}：点「家常菜」右边只剩这几篇`);
      const head = await page.evaluate(() => document.querySelector('.lbi-head').textContent);
      assert.match(head, /做饭 › 家常菜.*篇.*天天吃的那种/, `${theme}：网格上面一行说清选的是什么 + 她写的说明 ${head}`);
      assert.ok((await tabs(page)).find(t => t.text === '索引').on, `${theme}：点节点不跳出索引视图`);
      assert.match(await page.evaluate(() => document.querySelector('.lbc-count').textContent), new RegExp(`^${count('做饭/家常菜')} / 120 篇`));
      // ④ 上面一行：未归类 / 状态 / 建议新增
      const bar = await page.evaluate(() => ({ text: document.querySelector('.lbi-bar').textContent, chips: [...document.querySelectorAll('.lbi-chip')].map(b => b.textContent) }));
      assert.match(bar.text, /未归类 \d+ 篇/, `${theme}：「未归类 N 篇」${bar.text}`);
      assert.match(bar.text, /还有 3 篇没按内容归，约 ¥0\.02/, `${theme}：按内容归类的状态`);
      assert.match(bar.text, /4 行|1 行像是写给自己的说明/, `${theme}：说明行没当成分类，告诉她`);
      assert.deepEqual(bar.chips, [`穿搭灵感${idx.unclassified.count}`, '红烧系列3'], `${theme}：建议新增 chips`);
      await page.click('.lbi-classify-btn'); await S.settle();
      assert.equal((await calls(S, 'indexClassify')).length, 1, `${theme}：「按内容归类」调插件`);
      await page.evaluate(() => [...document.querySelectorAll('.lbi-chip')].find(b => b.dataset.id === 'p1').click()); await S.settle();
      assert.equal((await cardTitles(page)).length, idx.unclassified.count, `${theme}：点建议 = 右边看那几篇`);
      assert.match(await page.evaluate(() => document.querySelector('.lbi-head').textContent), /建议新增「穿搭灵感」.*第一级/);
      if (theme === 'light') await S.screenshot('index-split-light'); else await S.screenshot('index-split-dark');
      await page.click('.lbi-head .lbi-accept'); await S.settle();
      assert.deepEqual((await calls(S, 'indexAccept')).map(c => c[1]), ['p1'], `${theme}：加进索引调插件`);
      await page.evaluate(() => document.querySelector('.lbi-unc-link').click()); await S.settle();
      assert.ok((await cardTitles(page)).every(t => t.startsWith('穿搭')), `${theme}：「未归类 N 篇」= 右边看未归类`);
      // ⑤ 空分类 / AI 建的
      await page.evaluate(() => [...document.querySelectorAll('.lbi-row')].find(n => n.dataset.path === '空节点').querySelector('.lbi-empty-keep').click()); await S.settle();
      assert.deepEqual((await calls(S, 'indexEmpty')).map(c => c.slice(1)), [['空节点', 'keep']]);
      await clickRow(page, '做饭'); await S.settle();          // 选了未归类后「做饭」那一支收起了：选回来就展开
      await page.evaluate(() => [...document.querySelectorAll('.lbi-row')].find(n => n.dataset.path === '做饭/空气炸锅').querySelector('.lbi-keep-virtual').click()); await S.settle();
      assert.deepEqual((await calls(S, 'indexAccept')).map(c => c[1]), ['p1', 'v1'], `${theme}：AI 建的「保留」`);
      // 卡片上「归类…」（只在索引视图悬停出现）→ 移到… → 选分类小窗（能筛、Enter 选第一个）
      await clickRow(page, '做饭/家常菜'); await S.settle();
      // 10-11 细分标签：选中节点下面一行 chips（带篇数）；多选 = 同时有；清除；卡片上小字
      const home = idx.nodes.find(n => n.path === '做饭/家常菜').facets;
      const both = home[0].items.filter(i => home[1].items.includes(i));
      let fc = await page.evaluate(() => [...document.querySelectorAll('.lbi-facets .lbi-facet')].map(b => b.textContent));
      assert.deepEqual(fc, home.map(f => f.name + f.count), `${theme}：细分标签一行 ${fc}`);
      await page.evaluate(() => document.querySelector('.lbi-facet[data-name="红烧"]').click()); await S.settle();
      assert.equal((await cardTitles(page)).length, home[0].count, `${theme}：选「红烧」只剩这几篇`);
      const tagText = await page.evaluate(() => [...document.querySelectorAll('.lbc-grid .lbc-card .lbc-ftags')].map(e => e.hidden ? '' : e.textContent));
      assert.ok(tagText.length && tagText.every(t => t.includes('红烧')), `${theme}：卡片上小字有细分标签 ${tagText}`);
      fc = await page.evaluate(() => [...document.querySelectorAll('.lbi-facets .lbi-facet')].map(b => b.textContent));
      assert.equal(fc.find(t => t.startsWith('快手')), '快手' + both.length, `${theme}：别的标签显示同时有的篇数 ${fc}`);
      await page.evaluate(() => document.querySelector('.lbi-facet[data-name="快手"]').click()); await S.settle();
      assert.equal((await cardTitles(page)).length, both.length, `${theme}：两个都选 = 同时有（AND）`);
      assert.ok(await page.evaluate(() => !!document.querySelector('.lbi-facet-clear')), `${theme}：有「清除」`);
      await page.evaluate(() => document.querySelector('.lbi-facet-clear').click()); await S.settle();
      assert.equal((await cardTitles(page)).length, count('做饭/家常菜'), `${theme}：清除回到这一类全部`);
      const card = page.locator('.lbc-grid .lbc-card').first();
      await card.hover();
      assert.notEqual(await card.locator('.lbc-reclass').evaluate(b => getComputedStyle(b).display), 'none', `${theme}：悬停出现「归类…」`);
      await card.locator('.lbc-reclass').click(); await S.settle();
      const menu = await page.evaluate(() => [...document.querySelectorAll('.menu .menu-item-title, .lbc-menu .lbc-menu-item')].map(e => e.textContent));
      assert.deepEqual(menu.slice(0, 3), ['移到…（只放这一类）', '也放进…', '从「家常菜」拿掉'], `${theme}：归类菜单 ${menu}`);
      assert.ok(menu.includes('标签：红烧') && menu.includes('加一个标签…'), `${theme}：归类菜单里能加 / 去掉这篇的标签 ${menu}`);
      await page.evaluate(() => [...document.querySelectorAll('.menu .menu-item, .lbc-menu .lbc-menu-item')].find(e => e.textContent.includes('移到')).click()); await S.settle();
      const pick = await page.evaluate(() => ({ rows: [...document.querySelectorAll('.lbi-pick-row')].map(b => b.textContent), virt: [...document.querySelectorAll('.lbi-pick-row')].some(b => b.dataset.path === '做饭/空气炸锅'),
        sbw: getComputedStyle(document.querySelector('.lbi-pick')).scrollbarWidth }));
      assert.ok(pick.rows.length >= 10 && !pick.virt && pick.sbw === 'none', `${theme}：选分类小窗（没有 AI 建的、不露滚动条）${JSON.stringify(pick)}`);
      await page.fill('.lbi-pick-dialog input', '烘焙'); await page.keyboard.press('Enter'); await S.settle();
      const assigned = await calls(S, 'indexAssign');
      assert.deepEqual(assigned[0].slice(2), ['move', '做饭/烘焙'], `${theme}：移到 = indexAssign(ids, 'move', 路径) ${JSON.stringify(assigned)}`);
      assert.equal(await page.evaluate(() => !!document.querySelector('.lbc-dialog-back')), false, `${theme}：选完小窗关掉`);
      // ⑥ 她改完索引：index-data.json 变了 → 换新，卡片元素不重建
      await clickRow(page, 'AI'); await S.settle();
      await page.evaluate(() => { const c = document.querySelector('.lbc-grid .lbc-card'); c.dataset.keep = '1'; });
      const fresh = makeIndexData(data.items, { rename: '吃饭', running: true });
      await S.setFile('_archive/index-data.json', JSON.stringify(fresh));
      await page.waitForTimeout(450); await S.settle();
      rows = await treeRows(page);
      assert.ok(rows.find(r => r.path === '吃饭') && !rows.find(r => r.path === '做饭'), `${theme}：改名后的分类出现在树里`);
      assert.match(await page.evaluate(() => document.querySelector('.lbi-bar').textContent), /AI 正在按内容归类 40\/120/, `${theme}：后台在归：显示真实进度`);
      assert.ok(await page.evaluate(() => !!document.querySelector('.lbc-grid .lbc-card[data-keep="1"]')), `${theme}：卡片元素没重建`);
      // 树钉住：往下滚，树还在吸顶区下面
      await S.scrollTo(0); await S.settle();
      await S.scrollBy(500); await S.settle();
      const stick = await page.evaluate(() => { const t = document.querySelector('.lbc-top').getBoundingClientRect(), p = document.querySelector('.lbi-panel').getBoundingClientRect(); return { gap: p.top - t.bottom }; });
      assert.ok(stick.gap >= 0 && stick.gap <= 16, `${theme}：树钉在吸顶区下面 ${JSON.stringify(stick)}`);
      // 不出索引视图搜索：右边照样筛
      await page.fill('.lbc-search', 'AI'); await page.keyboard.press('Enter'); await S.settle();
      assert.ok((await tabs(page)).find(t => t.text === '索引').on, `${theme}：在索引视图里搜索不跳出`);
      const overflow = await page.evaluate(() => { const w = document.querySelector('.lbc-wrap'); return w.scrollWidth - w.clientWidth; });
      assert.ok(overflow <= 1, `${theme}：没有横向溢出 ${overflow}`);
      // 出了索引视图：卡片上不出「归类…」
      await clickTab(page, '全部'); await S.settle();
      const card2 = page.locator('.lbc-grid .lbc-card').first(); await card2.hover();
      assert.equal(await card2.locator('.lbc-reclass').evaluate(b => getComputedStyle(b).display), 'none', `${theme}：索引视图外不出「归类…」`);
      const errs = await S.pageErrors();
      assert.deepEqual(errs, [], `${theme}：页面没报错 ${errs}`);
      await page.close();
    }
    // ⑦ 窄屏 / 手机：树叠在网格上面
    for (const [label, opts] of [['narrow', { width: 560 }], ['mobile', { width: 390, mobile: true }]]) {
      const { page, S } = await open(browser, { ...opts, idx, data });
      await clickTab(page, '索引'); await S.settle();
      const m = await page.evaluate(() => {
        const p = document.querySelector('.lbi-panel').getBoundingClientRect(), g = document.querySelector('.lbc-grid').getBoundingClientRect();
        // 只量索引这一块（树 / 上面一行 / 网格上面那行）：手机上标题行和搜索框本来就有的溢出不归这一批
        const wr = document.querySelector('.lbc-wrap').getBoundingClientRect();
        const mine = [...document.querySelectorAll('.lbi-bar, .lbi-bar *, .lbi-split, .lbi-panel *, .lbi-head *')].filter(e => e.getBoundingClientRect().width > 0);
        const overflow = Math.max(0, ...mine.map(e => e.getBoundingClientRect().right - wr.right));
        return { stacked: p.bottom <= g.top + 1, narrow: document.querySelector('.lbi-split').classList.contains('is-narrow'), overflow,
          acts: document.querySelectorAll('.lbi-acts').length, classify: !!document.querySelector('.lbi-classify-btn') };
      });
      assert.ok(m.stacked && m.narrow, `${label}：树叠在网格上面 ${JSON.stringify(m)}`);
      assert.ok(m.overflow <= 1, `${label}：没有横向溢出 ${m.overflow}`);
      if (label === 'mobile') assert.ok(!m.acts && !m.classify, `手机上没有要插件的按钮 ${JSON.stringify(m)}`);
      if (label === 'narrow') await S.screenshot('index-split-narrow');
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    // ⑧ 旧后端（没有 index-data.json）：照旧按 cats_order，没有「索引」
    {
      const { page, S } = await open(browser, { idx: null, data });
      const names = (await tabs(page)).map(t => t.text);
      assert.ok(!names.includes('索引') && CATS.every(c => names.includes(c)), `旧后端照旧 ${names}`);
      await clickTab(page, '做饭'); await S.settle();
      assert.ok((await cardTitles(page)).every(t => t.startsWith('做饭')));
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS index_tree_ui：分类 = 索引第一级 · 二级小标签 · 左树右卡 / 折叠 / 钉住 · 未归类 / 归类状态 / 建议新增 · AI 建 / 空分类 · 归类… 移到 · 热更新 · 窄屏 · 旧后端兜底');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error('FAIL index_tree_ui', e && e.stack || e); process.exit(1); });

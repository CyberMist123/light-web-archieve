// 10-10 索引树在目录页（Obsidian 外壳：阅读视图 / 亮 · 暗 / 窄屏 / 手机）：
//   ① 顶部分类 = 索引第一级（顺序照索引，0 篇的不出，末尾「未归类」）；固定入口（全部 / 今日新增 / 导入时间 / 已收藏 / 视频 / 附件）还在，多一个「索引」
//   ② 选中一个大类 → 下面一行二级小标签（带篇数）；点小标签只剩那几篇；吸顶不受影响（|delta| ≤ 1）
//   ③「索引」视图：横向分叉树（子节点在父节点右边、父节点竖直居中在子节点之间），第二级以下默认收起、点「+N」展开；点节点 = 回到网格、筛到那些笔记
//   ④ 草稿横幅「用这版」→ 插件 indexUseDraft；写法提示一行；wiki 小标（有页 / 新增 N / 没文本 AI 时「生成」灰掉并说明可让 GPT 经 MCP 写）
//   ⑤ index-data.json 一变（她保存 索引.md → 插件重算）→ 300ms 后分类换新，卡片元素不重建
//   ⑥ 窄屏 / 手机退化成缩进列表、没有横向溢出；⑦ 没有 index-data.json（旧后端）照旧按 cats_order，不出「索引」
// 截图落 LWA_QA_DIR（不提交、不必逐张看）
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const CATS = ['悉尼', '做饭', 'AI', '学习', '穿搭', '家居', '旅行'];

function makeIndexData(items, { textAi = false, rename = null } = {}) {
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
  add(cook, cookIds, { children: [cook + '/家常菜', cook + '/烘焙'] });
  add(cook + '/家常菜', ids(it => cat(it) === '做饭' && idOf(it) % 2 === 0), { children: [cook + '/家常菜/红烧肉'] });
  add(cook + '/家常菜/红烧肉', ids(it => cat(it) === '做饭' && idOf(it) % 4 === 0));
  add(cook + '/烘焙', ids(it => cat(it) === '做饭' && idOf(it) % 2 === 1));
  add('AI', ids(it => cat(it) === 'AI'), { children: ['AI/伴侣', 'AI/工具'] });
  add('AI/伴侣', ids(it => cat(it) === 'AI' && idOf(it) % 3 === 0), { wiki: true });
  add('AI/工具', ids(it => cat(it) === 'AI' && idOf(it) % 3 !== 0));
  add('旅行', ids(it => cat(it) === '旅行'), { wiki: true, children: ['旅行/成都'] });
  add('旅行/成都', ids(it => cat(it) === '旅行').slice(0, 3));
  for (const c of ['悉尼', '学习', '家居']) add(c, ids(it => cat(it) === c));
  add('空节点', []);
  const unc = ids(it => cat(it) === '穿搭');
  const roots = rows.filter(r => !r.parent).map(r => r.path);
  return {
    version: 1, code_version: 'test', generated_at: '2026-10-10T03:00:00+11:00', file: '索引.md', draft_file: '索引.草稿.md',
    source_hash: 'sha256:x' + (rename || ''), catalog_built_at: '2026-10-08T05:09:12+10:00', total: items.length,
    classified: items.length - unc.length, roots, nodes: rows, unclassified: { count: unc.length, items: unc },
    cats_order: [...roots.filter(p => rows.find(r => r.path === p).count), '未归类'],
    warnings: [{ line: 7, text: `第 7 行「${cook}」在第一级重复了（第 6 行已有），合并成一个` }, { line: 0, text: '目录数据还没建好' }],
    draft: { file: '索引.草稿.md', exists: true, mode: 'ai', roots: ['吃', '玩', 'AI', '学', '家', '澳洲', '杂'], nodes: 20, classified: 110, unclassified: 10, total: items.length, warnings: 0 },
    wiki: { 'AI/伴侣': { file: 'wiki/AI/伴侣.md', exists: true, marked: true, based: 5, new_since: 2, generated_at: '2026-10-10T03:10:00+11:00' },
            '旅行': { file: 'wiki/旅行.md', exists: false, marked: true, based: 0, new_since: 0, generated_at: null } },
    text_ai: textAi ? { ok: true, why: '', model: 'm' } : { ok: false, why: '文本 AI没有 key', model: '' },
  };
}

const PLUGIN = { methods: { indexUseDraft: { result: { ok: true } }, indexDraft: { result: { ok: true } }, openIndexSuggestions: { result: null }, wikiBuild: { result: null } } };

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
const clickLabel = async (page, path) => { await page.evaluate(p => [...document.querySelectorAll('.lbi-node')].find(n => n.dataset.path === p).querySelector(':scope > .lbi-row .lbi-label').click(), path); };

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
      const t0 = await tabs(page);
      const names = t0.map(t => t.text);
      for (const fixed of ['全部', '索引', '今日新增', '已收藏', '视频', '附件']) assert.ok(names.includes(fixed), `${theme}：固定入口「${fixed}」还在 ${names}`);
      const catTabs = names.slice(names.indexOf('附件') + 1);
      assert.deepEqual(catTabs, ['做饭', 'AI', '旅行', '悉尼', '学习', '家居', '未归类'], `${theme}：分类 = 索引第一级（0 篇的不出）+ 未归类`);
      assert.equal(names.indexOf('索引'), names.indexOf('全部') + 1, '「索引」紧挨着「全部」');
      // ② 大类 → 二级小标签
      await clickTab(page, '做饭'); await S.settle();
      let titles = await cardTitles(page);
      assert.equal(titles.length, count('做饭'), `${theme}：点「做饭」只剩这一类 ${titles.length}`);
      assert.ok(titles.every(t => t.startsWith('做饭')), `${theme}：都是做饭`);
      let c = await chips(page);
      assert.deepEqual(c.map(x => x.text), [`家常菜${count('做饭/家常菜')}`, `烘焙${count('做饭/烘焙')}`], `${theme}：二级小标签带篇数 ${JSON.stringify(c)}`);
      assert.ok((await tabs(page)).find(t => t.text === '做饭').on);
      const subBelow = await page.evaluate(() => { const a = document.querySelector('.lbc-cats').getBoundingClientRect(), b = document.querySelector('.lbc-subcats').getBoundingClientRect(); return b.top >= a.bottom - 1 && document.querySelector('.lbc-subcats').parentElement === document.querySelector('.lbc-top'); });
      assert.ok(subBelow, `${theme}：小标签在分类下面一行、也在吸顶区里`);
      await page.evaluate(() => [...document.querySelectorAll('.lbc-subcats .lbc-subcat')][0].click()); await S.settle();
      titles = await cardTitles(page);
      assert.equal(titles.length, count('做饭/家常菜'), `${theme}：点「家常菜」只剩 ${count('做饭/家常菜')} 篇`);
      c = await chips(page);
      assert.ok(c[0].on && !c[1].on && (await tabs(page)).find(t => t.text === '做饭').on, `${theme}：小标签选中、大类还亮着`);
      const sub = await page.evaluate(() => document.querySelector('.lbc-count').textContent);
      assert.match(sub, new RegExp(`^${count('做饭/家常菜')} / 120 篇`), `${theme}：计数行 ${sub}`);
      if (theme === 'light') await S.screenshot('index-subcats-light'); else await S.screenshot('index-subcats-dark');
      const c1 = await S.probeSticky({ target: '.lbc-top', by: 600 });
      assert.ok(Math.abs(c1.delta) <= 1, `${theme}：带着二级小标签也吸顶 ${JSON.stringify(c1)}`);
      await S.scrollTo(0);
      // ③ 索引视图
      await clickTab(page, '索引'); await S.settle();
      const vis = await page.evaluate(() => ({ panel: !document.querySelector('.lbi-panel').hidden && document.querySelector('.lbi-panel').getBoundingClientRect().height > 0,
        grid: document.querySelector('.lbc-grid').hidden, sub: !!document.querySelector('.lbc-subcats') }));
      assert.ok(vis.panel && vis.grid && !vis.sub, `${theme}：索引视图开、网格藏、二级小标签收起 ${JSON.stringify(vis)}`);
      assert.ok((await tabs(page)).find(t => t.text === '索引').on && !(await tabs(page)).find(t => t.text === '全部').on);
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-count').textContent), '120 篇', `${theme}：索引视图里计数行是全库篇数`);
      const tree = await page.evaluate(() => {
        const lab = p => { const n = [...document.querySelectorAll('.lbi-node')].find(x => x.dataset.path === p); const l = n && n.querySelector(':scope > .lbi-row .lbi-label'); if (!l) return null; const r = l.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, cy: (r.top + r.bottom) / 2, text: l.textContent }; };
        return { root: lab(''), cook: lab('做饭'), home: lab('做饭/家常菜'), bake: lab('做饭/烘焙'), pork: lab('做饭/家常菜/红烧肉'), unc: lab('∅未归类'), empty: lab('空节点'),
          fold: (() => { const n = [...document.querySelectorAll('.lbi-node')].find(x => x.dataset.path === '做饭/家常菜'); return n && n.querySelector(':scope > .lbi-row .lbi-fold')?.textContent; })(),
          list: document.querySelector('.lbi-panel').classList.contains('is-list') };
      });
      assert.equal(tree.root.text, '全部120', `${theme}：根 = 全部 + 篇数`);
      assert.equal(tree.cook.text, `做饭${count('做饭')}`);
      assert.ok(!tree.list, `${theme}：宽屏是分叉树不是列表`);
      assert.ok(tree.home.left > tree.cook.right && tree.cook.left > tree.root.right, `${theme}：子节点在父节点右边 ${JSON.stringify(tree)}`);
      assert.ok(tree.cook.cy >= tree.home.cy - 1 && tree.cook.cy <= tree.bake.cy + 1, `${theme}：父节点竖直居中在子节点之间`);
      assert.ok(!tree.pork && tree.fold === '+1', `${theme}：第三级默认收起，显示「+1」${tree.fold}`);
      assert.ok(tree.unc && tree.unc.text === `未归类${idx.unclassified.count}` && tree.empty && tree.empty.text === '空节点0', `${theme}：未归类、0 篇的节点也在图里`);
      await page.evaluate(() => [...document.querySelectorAll('.lbi-node')].find(x => x.dataset.path === '做饭/家常菜').querySelector(':scope > .lbi-row .lbi-fold').click()); await S.settle();
      const pork = await page.evaluate(() => !![...document.querySelectorAll('.lbi-node')].find(x => x.dataset.path === '做饭/家常菜/红烧肉'));
      assert.ok(pork, `${theme}：点「+1」展开第三级`);
      // ④ 草稿横幅 / 写法提示 / wiki 小标
      const extras = await page.evaluate(() => ({
        banner: document.querySelector('.lbi-draft .lbi-banner-text')?.textContent || '',
        warn: document.querySelector('.lbi-warn')?.textContent || '',
        note: document.querySelector('.lbi-note')?.textContent || '',
        wikiPage: (() => { const n = [...document.querySelectorAll('.lbi-node')].find(x => x.dataset.path === 'AI/伴侣'); return n ? n.querySelector(':scope > .lbi-row .lbi-wiki')?.textContent : null; })(),
        gen: (() => { const n = [...document.querySelectorAll('.lbi-node')].find(x => x.dataset.path === '旅行'); const b = n && n.querySelector(':scope > .lbi-row .lbi-wiki-gen'); return b ? { text: b.textContent, disabled: b.disabled } : null; })(),
        draftBtn: document.querySelector('.lbi-draft-btn')?.textContent,
      }));
      assert.match(extras.banner, /AI 起草了一版：7 个大类，能归进 110\/120 篇/, `${theme}：草稿横幅 ${extras.banner}`);
      assert.match(extras.warn, /索引\.md 有 2 处写法要看一眼：第 7 行/, `${theme}：写法提示一行 ${extras.warn}`);
      assert.match(extras.note, /GPT 经 MCP/, `${theme}：没文本 AI 时说清可以让 GPT 经 MCP 写`);
      assert.match(extras.wikiPage, /wiki.*新增 2/, `${theme}：有 wiki 页的节点 ${extras.wikiPage}`);
      assert.deepEqual(extras.gen, { text: '生成', disabled: true }, `${theme}：没文本 AI，「生成」灰掉`);
      assert.equal(extras.draftBtn, '起草一版', `${theme}：没文本 AI 时按钮叫「起草一版」`);
      if (theme === 'light') await S.screenshot('index-tree-light'); else await S.screenshot('index-tree-dark');
      await page.click('.lbi-use-draft'); await S.settle();
      assert.ok((await S.calls()).some(c => c[0] === 'indexUseDraft'), `${theme}：「用这版」调插件 indexUseDraft`);
      // 点节点 = 回网格、筛到那些笔记（第三级：小标签行多一个带 ✕ 的尾巴）
      await clickLabel(page, '做饭/家常菜/红烧肉'); await S.settle();
      titles = await cardTitles(page);
      const v2 = await page.evaluate(() => ({ panel: document.querySelector('.lbi-panel').hidden, grid: document.querySelector('.lbc-grid').hidden }));
      assert.ok(v2.panel && !v2.grid, `${theme}：点节点回到网格`);
      assert.equal(titles.length, count('做饭/家常菜/红烧肉'), `${theme}：筛到红烧肉 ${titles.length}`);
      c = await chips(page);
      assert.ok(c.find(x => x.path === '做饭/家常菜').on && c.find(x => x.path === '做饭/家常菜/红烧肉' && x.on), `${theme}：第三级有带 ✕ 的尾巴 ${JSON.stringify(c)}`);
      await clickTab(page, '索引'); await S.settle();
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-subcats')), null, `${theme}：索引视图里不出二级小标签（哪怕选着第三级）`);
      await clickTab(page, '索引'); await S.settle();
      assert.equal((await cardTitles(page)).length, count('做饭/家常菜/红烧肉'), `${theme}：再点「索引」回到原来的筛选`);
      await page.evaluate(() => [...document.querySelectorAll('.lbc-subcats .lbc-subcat')].find(b => b.dataset.path === '做饭/家常菜/红烧肉').click()); await S.settle();
      assert.equal((await cardTitles(page)).length, count('做饭/家常菜'), `${theme}：点 ✕ 回到第二级`);
      // 未归类
      await clickTab(page, '未归类'); await S.settle();
      titles = await cardTitles(page);
      assert.ok(titles.length === idx.unclassified.count && titles.every(t => t.startsWith('穿搭')), `${theme}：未归类 ${titles.length}`);
      // ⑤ 她改完索引：index-data.json 变了 → 分类换新，卡片元素不重建
      await clickTab(page, 'AI'); await S.settle();
      await page.evaluate(() => { const c = document.querySelector('.lbc-grid .lbc-card'); c.dataset.keep = '1'; });
      const fresh = makeIndexData(data.items, { rename: '吃饭', textAi: true });
      await S.setFile('_archive/index-data.json', JSON.stringify(fresh));
      await page.waitForTimeout(450); await S.settle();
      const t2 = (await tabs(page)).map(t => t.text);
      assert.ok(t2.includes('吃饭') && !t2.includes('做饭'), `${theme}：改名后的分类出现 ${t2}`);
      assert.ok((await tabs(page)).find(t => t.text === 'AI').on, `${theme}：还在的筛选保留`);
      assert.ok(await page.evaluate(() => !!document.querySelector('.lbc-grid .lbc-card[data-keep="1"]')), `${theme}：卡片元素没重建`);
      const errs = await S.pageErrors();
      assert.deepEqual(errs, [], `${theme}：页面没报错 ${errs}`);
      await page.close();
    }
    // ⑥ 窄屏：缩进列表、不横向溢出（宽屏换到窄屏也会跟着变）
    for (const [label, opts] of [['narrow', { width: 520 }], ['mobile', { width: 390, mobile: true }]]) {
      const { page, S } = await open(browser, { ...opts, idx, data });
      await clickTab(page, '索引'); await S.settle();
      const m = await page.evaluate(() => {
        const p = document.querySelector('.lbi-panel');
        const lab = path => { const n = [...document.querySelectorAll('.lbi-node')].find(x => x.dataset.path === path); const r = n.querySelector(':scope > .lbi-row .lbi-label').getBoundingClientRect(); return { left: r.left, top: r.top, bottom: r.bottom }; };
        return { list: p.classList.contains('is-list'), overflow: p.scrollWidth - p.clientWidth, cook: lab('做饭'), home: lab('做饭/家常菜'),
          buttons: [...p.querySelectorAll('.lbi-bar button')].map(b => b.textContent) };
      });
      assert.ok(m.list, `${label}：退化成缩进列表`);
      assert.ok(m.overflow <= 1, `${label}：没有横向溢出 ${m.overflow}`);
      assert.ok(m.home.top >= m.cook.bottom - 1 && m.home.left > m.cook.left, `${label}：子节点在下一行、往里缩 ${JSON.stringify(m)}`);
      if (label === 'mobile') assert.deepEqual(m.buttons, ['编辑索引'], `手机上只留「编辑索引」（起草 / 用这版要电脑）${m.buttons}`);
      if (label === 'narrow') await S.screenshot('index-tree-narrow');
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    {
      const { page, S } = await open(browser, { width: 1280, idx, data });
      await clickTab(page, '索引'); await S.settle();
      await page.setViewportSize({ width: 560, height: 900 }); await page.waitForTimeout(120); await S.settle();
      assert.ok(await page.evaluate(() => document.querySelector('.lbi-panel').classList.contains('is-list')), '宽屏缩到窄屏：跟着变成列表');
      await page.close();
    }
    // ⑦ 旧后端（没有 index-data.json）：照旧按 cats_order，没有「索引」
    {
      const { page, S } = await open(browser, { idx: null, data });
      const names = (await tabs(page)).map(t => t.text);
      assert.ok(!names.includes('索引') && CATS.every(c => names.includes(c)), `旧后端照旧 ${names}`);
      await clickTab(page, '做饭'); await S.settle();
      assert.ok((await cardTitles(page)).every(t => t.startsWith('做饭')));
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-subcats')), null, '旧后端没有二级小标签');
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS index_tree_ui：分类 = 索引第一级 · 二级小标签 · 分叉树 / 折叠 / 点节点筛选 · 草稿 / 提示 / wiki · 热更新 · 窄屏列表 · 旧后端兜底');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error('FAIL index_tree_ui', e && e.stack || e); process.exit(1); });

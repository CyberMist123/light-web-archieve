// 1026 作者的录屏（场景 02 首页编排 / 03 找资料 / 08 首页同步入口）：假 DOM 上真跑整段目录页脚本。
//   ① 筛选条各维度叠加：平台（B站 / 小红书）→ 主题 → Tag → 类型，一路缩小、前面选的不丢；换到 Wiki 再回瀑布流筛选还在；在 Wiki 里点筛选 = 回瀑布流看结果
//   ② 最近导入（1027b 作者：不要「查看全部」）：折成一行，点开往下是列表，框里滚到底接着出更早的
//   ③ Wiki = 长期研究主题（标了 [wiki] 的分类：打开 wiki / 看这些帖子 / 生成）；未归类兜底队列一直露着（分类行 0 篇也留着）
//   ④ 管理（1027b 作者：只留 设置 / 索引编辑 / 刷新目录 / 导出资料 / 回收站，设置最上面）；删除一个分类在索引树上右键，说清帖子去哪（并进 / 回到未归类，帖子不删）
//   ⑤ 编排：1027 起八个模块平级、拖到任何位置、调宽、就地调整——用例挪到 tests/test_catalog_arrange_1027.cjs
//   ⑥ 删除后的提示带「打开回收站」
'use strict';
const assert = require('node:assert/strict');
const { tick, item, catalogData, openCatalog, ev } = require('./_fake_l1.cjs');

const state = () => JSON.parse(globalThis.__lbState['lb:catalog']);
const iso = (d, k) => new Date(Date.UTC(2026, 9, d, k)).toISOString();
const base = () => [
  item('xhs-a', '小红书咖啡', { topics: ['咖啡'], tags: ['手冲'], kind: 'image', ts: iso(20, 1) }),
  item('xhs-b', '小红书咖啡视频', { topics: ['咖啡'], tags: ['手冲'], kind: 'video', ts: iso(21, 1) }),
  item('bili-c', 'B站咖啡视频', { topics: ['咖啡'], tags: ['手冲'], kind: 'video', ts: iso(22, 1) }),
  item('bili-d', 'B站咖啡图文', { topics: ['咖啡'], tags: ['拉花'], kind: 'image', ts: iso(23, 1) }),
  item('bili-e', 'B站做饭', { topics: [], tags: ['手冲'], kind: 'video', cats: ['吃的'], ts: iso(24, 1) }),
];
const dataOf = (items, more = {}) => catalogData(items, { topics: ['咖啡'], ...more });
const notes = [];
const notify = (message, o = {}) => { notes.push({ message, ...o }); return { hide() {} }; };
const pickMenu = (P, re) => { const b = P.menuItems().find(x => re.test(x.textContent)); assert.ok(b, '菜单里有 ' + re + '：' + P.menuItems().map(x => x.textContent)); b.onclick(ev()); };

(async () => {
  // ── ① 维度叠加 ──
  {
    const P = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } } });
    // 1031 作者：两个平台时「图文 / 视频」换成一个来源下拉（不带数）
    assert.ok(P.$('.lbc-platpick') && !P.cat('图文') && P.cat('视频'), '两个平台：来源下拉；1101 作者：全部来源时也出「视频」「文件」');
    P.$('.lbc-platpick').onclick(ev()); assert.deepEqual(P.menuItems().map(x => x.textContent), ['全部来源', '小红书', 'B站'], '不带数，小红书在前'); pickMenu(P, /^B站$/);
    assert.deepEqual(P.ids().sort(), ['bili-c', 'bili-d', 'bili-e'], 'B站');
    P.$('.lbc-thq').onclick();
    assert.deepEqual(P.ids().sort(), ['bili-c', 'bili-d'], 'B站 → 主题「咖啡」');
    P.$('.lbc-tagpick').onclick(ev());
    assert.deepEqual(P.menuItems().map(b => b.textContent).sort(), ['#手冲 1', '#拉花 1'].sort(), 'Tag 菜单只列当前条件下有的');
    pickMenu(P, /^#手冲/);
    assert.deepEqual(P.ids(), ['bili-c'], '→ Tag');
    assert.ok(!P.cat('视频') && !P.cat('图文'), 'B 站下不分图文 / 视频（全是视频）');
    assert.equal(P.$('.lbc-platpick').textContent, 'B站'); assert.equal(P.$('.lbc-tagpick').textContent, '#手冲');
    assert.deepEqual([state().plat, state().tag, state().topic], ['bili', '手冲', '咖啡'], '各维度都进 LB.state');
    // 返回后都还在
    const Q = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } }, keepState: true });
    assert.deepEqual(Q.ids(), ['bili-c']);
    assert.ok(Q.$('.lbc-platpick').classList.contains('is-active') && Q.$('.lbc-tagpick').classList.contains('is-active'));
    // 清除筛选一起清
    Q.$('.lbc-tagpick').onclick(ev()); pickMenu(Q, /全部 Tag/);
    assert.deepEqual(Q.ids().sort(), ['bili-c', 'bili-d']);
  }

  // ── ② 最近导入：点开往下滚 ──
  {
    const many = Array.from({ length: 120 }, (_, i) => item('xhs-' + i, '第 ' + i + ' 篇', { ts: new Date(Date.UTC(2026, 8, 1) + i * 3600e3).toISOString() }));
    const plugin = { settings: { hiddenCats: [] }, async getSyncSchedule() { return null; } };
    const P = await openCatalog({ data: dataOf(many), plugin });
    await tick(5);
    assert.equal(P.$('.lbc-mod-recent .lbc-rec-all'), null, '没有「查看全部」');
    const rc = P.$('.lbc-mod-recent');
    assert.ok(rc.classList.contains('is-folded')); rc.querySelector('.lbc-fold-sum').onclick();
    const ul = rc.querySelector('.lbc-rec');
    const ids = () => P.$$('.lbc-mod-recent .lbc-rec li').map(li => li.dataset.id);
    assert.equal(ids().length, 40, '先画 40 条（框高 6 条，在框里滚）'); assert.equal(ids()[0], 'xhs-119', '新→旧');
    // 滚到底：接着出更早的
    Object.defineProperty(ul, 'scrollHeight', { value: 2000, configurable: true }); Object.defineProperty(ul, 'clientHeight', { value: 240, configurable: true });
    ul.scrollTop = 1700; ul.dispatchEvent({ type: 'scroll' });
    assert.equal(ids().length, 80); assert.equal(ids()[79], 'xhs-40');
    assert.equal(P.$('.lbc-recent')?.hidden ?? true, true, '还在瀑布流（不切到别的视图）');
  }

  // ── ③ 未归类 · 索引编辑里的分类 wiki ──
  {
    const items = base();
    const index = { version: 1, file: '索引.md', total: 5, classified: 4, roots: ['咖啡', '吃的'],
      nodes: [{ path: '咖啡', name: '咖啡', depth: 1, count: 4, self_count: 4, items: ['xhs-a', 'xhs-b', 'bili-c', 'bili-d'], children: [], wiki: true, line: 1 },
        { path: '吃的', name: '吃的', depth: 1, count: 0, self_count: 0, items: [], children: [], line: 2 }],
      unclassified: { count: 1, items: ['bili-e'] }, wiki: { 咖啡: { file: 'wiki/咖啡.md', exists: true, new_since: 2 } }, text_ai: { ok: true } };
    const plugin = { settings: { hiddenCats: [] } };
    const P = await openCatalog({ data: dataOf(items), plugin, files: { '_archive/index-data.json': JSON.stringify(index), 'wiki/咖啡.md': '# 咖啡', '索引.md': '- 咖啡 [wiki]\n- 吃的\n' } });
    assert.ok(P.cat('未归类'), '分类行有未归类');
    // 1031 作者：页头「分类 Wiki」退场——分类的 wiki 在索引编辑里每个分类后面；索引编辑从「管理 → 索引编辑」进，「退出索引编辑」出来
    assert.equal(P.$('.lbc-wiki'), null);
    P.$('.lb-manage').onclick(ev()); await tick(5); pickMenu(P, /^索引编辑$/);
    assert.ok(P.$('.lbc-wrap').classList.contains('is-indexview'));
    assert.ok(P.$('.lbi-wiki-open'), '「咖啡」后面能打开它的 wiki');
    P.$('.lbi-tools .lbi-exit').onclick(ev());
    assert.ok(!P.$('.lbc-wrap').classList.contains('is-indexview'), '退出索引编辑 = 回收藏墙');
    P.cat('未归类').onclick();
    assert.deepEqual(P.ids(), ['bili-e'], '未归类');
    // 0 篇的未归类也留着（淡色）
    const R = await openCatalog({ data: dataOf(items), plugin, files: { '_archive/index-data.json': JSON.stringify({ ...index, unclassified: { count: 0, items: [] } }) } });
    const t = R.cat('未归类');
    assert.ok(t && t.classList.contains('is-empty') && t.dataset.n === '0', '未归类 0 篇也不藏');
    t.onclick(); assert.equal(R.ids().length, 5, '点 0 篇的未归类不清空页面');
  }

  // ── ④ 管理 ──
  {
    const calls = [];
    const plugin = { settings: { hiddenCats: [] }, openCatalogTitle() { calls.push('title'); }, openColumnsPicker() { calls.push('cols'); }, openSetupPage(s) { calls.push('setup:' + s); },
      async confirm(o) { calls.push('confirm:' + o.title); return false; }, notify };
    const index = { version: 1, file: '索引.md', total: 5, classified: 4, roots: ['咖啡'], nodes: [{ path: '咖啡', name: '咖啡', depth: 1, count: 4, items: ['xhs-a', 'xhs-b', 'bili-c', 'bili-d'], children: [], line: 1 }], unclassified: { count: 1, items: ['bili-e'] } };
    const P = await openCatalog({ data: dataOf(base()), plugin, frontmatter: { '回收站.md': { 'lb-page': 'trash' } },
      files: { '回收站.md': '---\nlb-page: trash\n---\n', '_archive/index-data.json': JSON.stringify(index), '_archive/trash-data.json': JSON.stringify({ items: [{ item_id: 'x', has_files: true }, { item_id: 'y', has_files: true }, { item_id: 'z', has_files: false }] }) } });
    P.$('.lb-manage').onclick(ev()); await tick(5);
    // 1027b 作者：管理只留五样，设置在最上面；1031「编排」并进来，加「每行几列」
    const titles = P.menuItems().map(b => b.textContent);
    // 1103 作者：「编排」先收起来，只留「改标题」
    assert.deepEqual(titles, ['设置', '改标题', '✓ 自动', '2 列', '3 列', '4 列', '5 列', '6 列', '索引编辑', '刷新目录（手动）', '导出资料', '回收站（2 篇）']);
    assert.equal(P.dom.document.body.querySelectorAll('.lbc-menu-label').length, 0, '不再分组');
    pickMenu(P, /^回收站（2 篇/); await tick(5);
    assert.equal(P.app.workspace.opened.at(-1)[0], '回收站.md', '点回收站 = 打开回收站页');
    // 每行几列：选了就记进 catalogColumns，再打开勾在那一项
    P.$('.lb-manage').onclick(ev()); await tick(5);
    pickMenu(P, /^4 列$/); await tick(5);
    assert.equal(plugin.settings.catalogColumns, 4);
    P.$('.lb-manage').onclick(ev()); await tick(5);
    assert.ok(P.menuItems().some(b => b.textContent === '✓ 4 列'));
    pickMenu(P, /^设置$/); await tick(5);
    assert.equal(calls.at(-1), 'setup:undefined', '设置 = 打开设置页');
    // 索引编辑 = 分类树视图
    P.$('.lb-manage').onclick(ev()); await tick(5);
    pickMenu(P, /^索引编辑/);
    assert.ok(P.$('.lbc-wrap').classList.contains('is-indexview'));
    // 删除一个分类挪到树上右键：有内容的先问帖子去哪（这里取消）——说清帖子不删、可以回到未归类
    P.$('.lbi-row[data-path="咖啡"] .lbi-label').oncontextmenu(ev()); await tick(5);
    pickMenu(P, /^删除这个分类/); await tick(5);
    assert.equal(calls.at(-1), 'confirm:删掉分类「咖啡」：里面的 4 篇帖子去哪？');
    assert.match(notes.at(-1).message, /没删。要让这 4 篇回到「未归类」/);
  }

  // ── ⑥ 删了之后提示带「打开回收站」 ──
  {
    const plugin = { settings: { hiddenCats: [] }, notify, async deleteItems(ids) { return { results: ids.map(id => ({ item_id: id, status: 'deleted' })) }; } };
    const P = await openCatalog({ data: dataOf(base()), plugin });
    P.card('xhs-a').oncontextmenu(ev());
    pickMenu(P, /^删除（移到回收站）/); await tick(10);
    const n = notes.at(-1);
    assert.match(n.message, /移到了回收站（可恢复）/); assert.deepEqual(n.actions.map(a => a.label), ['打开回收站']);
  }
  console.log('PASS catalog 1026 scenes 02/03/08: platform → topic → tag → type compose and survive a return · 最近导入 folded line → list scrolls in place, loads more at the bottom (no 查看全部) · 未归类 always visible, category wiki inside 索引编辑 (管理 → 索引编辑, exit back) · 管理 grouped (trash with count, delete-category explains where posts go) · delete notice links the trash');
})().catch(e => { console.error(e); process.exit(1); });

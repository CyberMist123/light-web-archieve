// 1026 她的录屏（场景 02 首页编排 / 03 找资料 / 08 首页同步入口）：假 DOM 上真跑整段目录页脚本。
//   ① 筛选条各维度叠加：平台（B站 / 小红书）→ 主题 → Tag → 类型，一路缩小、前面选的不丢；换到 Wiki 再回瀑布流筛选还在；在 Wiki 里点筛选 = 回瀑布流看结果
//   ② 最近导入「查看全部」：按导入时间新→旧的完整列表，一页 50 条翻页，返回瀑布流；页码存 LB.state
//   ③ Wiki = 长期研究主题（标了 [wiki] 的分类：打开 wiki / 看这些帖子 / 生成）；未归类兜底队列一直露着（分类行 0 篇也留着）
//   ④ 管理：分组（整理分类 / 回收站与删除 / 外观与其它），回收站带篇数、点了打开回收站页；删除一个分类说清帖子去哪（并进 / 回到未归类，帖子不删）
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
    assert.ok(P.$('.lbc-platpick'), '两个平台才出平台选择');
    P.$('.lbc-platpick').onclick(ev()); pickMenu(P, /^B站（3）/);
    assert.deepEqual(P.ids().sort(), ['bili-c', 'bili-d', 'bili-e'], 'B站');
    P.$('.lbc-thq').onclick();
    assert.deepEqual(P.ids().sort(), ['bili-c', 'bili-d'], 'B站 → 主题「咖啡」');
    P.$('.lbc-tagpick').onclick(ev());
    assert.deepEqual(P.menuItems().map(b => b.textContent).sort(), ['#手冲（1）', '#拉花（1）'].sort(), 'Tag 菜单只列当前条件下有的');
    pickMenu(P, /^#手冲/);
    assert.deepEqual(P.ids(), ['bili-c'], '→ Tag');
    P.cat('视频').onclick();
    assert.deepEqual(P.ids(), ['bili-c'], '→ 类型视频，前面的都还在');
    assert.equal(P.$('.lbc-platpick').textContent, 'B站'); assert.equal(P.$('.lbc-tagpick').textContent, '#手冲');
    assert.deepEqual([state().plat, state().tag, state().media, state().topic], ['bili', '手冲', 'video', '咖啡'], '各维度都进 LB.state');
    // 换到 Wiki 再回瀑布流：筛选不丢
    P.$('.lbc-view[data-view="wiki"]').onclick();
    assert.equal(P.$('.lbc-grid').hidden, true); assert.equal(P.$('.lbc-wiki').hidden, false);
    P.$('.lbc-view[data-view="grid"]').onclick();
    assert.deepEqual(P.ids(), ['bili-c'], '回瀑布流筛选还在');
    // 在 Wiki 里点一个筛选：回瀑布流看结果（不是改了筛选却还停在 Wiki 空页上）
    P.$('.lbc-view[data-view="wiki"]').onclick();
    P.cat('视频').onclick();
    assert.equal(P.$('.lbc-wiki').hidden, true, '在 Wiki 里点筛选 = 回到瀑布流');
    assert.deepEqual(P.ids().sort(), ['bili-c'].concat(), '视频取消了：B站 · 咖啡 · #手冲');
    // 返回后都还在
    const Q = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } }, keepState: true });
    assert.deepEqual(Q.ids(), ['bili-c']);
    assert.ok(Q.$('.lbc-platpick').classList.contains('is-active') && Q.$('.lbc-tagpick').classList.contains('is-active'));
    // 清除筛选一起清
    Q.$('.lbc-tagpick').onclick(ev()); pickMenu(Q, /全部 Tag/);
    assert.deepEqual(Q.ids().sort(), ['bili-c', 'bili-d']);
  }

  // ── ② 最近导入「查看全部」 ──
  {
    const many = Array.from({ length: 120 }, (_, i) => item('xhs-' + i, '第 ' + i + ' 篇', { ts: new Date(Date.UTC(2026, 8, 1) + i * 3600e3).toISOString() }));
    const plugin = { settings: { hiddenCats: [] }, async getSyncSchedule() { return null; } };
    const P = await openCatalog({ data: dataOf(many), plugin });
    await tick(5);
    const more = P.$('.lbc-mod-recent .lbc-rec-all');
    assert.ok(more, 'RECENT 底下有「查看全部」'); assert.equal(more.textContent, '查看全部 120 篇 →');
    assert.equal(P.$$('.lbc-mod-recent .lbc-rec li').length, 6, '边栏照旧只预览 6 条');
    more.onclick(ev());
    const rows = () => P.$$('.lbc-recent tr.lbc-rrow').map(r => r.dataset.id);
    assert.equal(P.$('.lbc-recent').hidden, false); assert.equal(P.$('.lbc-grid').hidden, true);
    assert.equal(rows().length, 50); assert.equal(rows()[0], 'xhs-119', '新→旧'); assert.equal(rows()[49], 'xhs-70');
    assert.equal(P.$('.lbc-rpage').textContent, '第 1 / 3 页');
    assert.equal(P.$('.lbc-rpager [data-act="prev"]').disabled, true);
    P.$('.lbc-rpager [data-act="next"]').onclick();
    assert.equal(rows()[0], 'xhs-69'); assert.equal(P.$('.lbc-rpage').textContent, '第 2 / 3 页');
    P.$('.lbc-rpager [data-act="next"]').onclick();
    assert.equal(rows().length, 20); assert.equal(P.$('.lbc-rpager [data-act="next"]').disabled, true);
    assert.deepEqual([state().view, state().recentPage], ['recent', 3]);
    P.$('.lbc-recent tr.lbc-rrow').onclick({ ctrlKey: false });
    assert.deepEqual(P.app.workspace.opened.at(-1), ['Web/xhs-119.md'.replace('119', rows()[0].slice(4)), '', false], '点行打开（同一窗格）');
    const Q = await openCatalog({ data: dataOf(many), plugin, keepState: true });
    assert.equal(Q.$('.lbc-rpage').textContent, '第 3 / 3 页', '返回后还在第 3 页');
    Q.$('.lbc-recent [data-act="back"]').onclick();
    assert.equal(Q.$('.lbc-recent').hidden, true); assert.equal(Q.$('.lbc-grid').hidden, false);
  }

  // ── ③ Wiki · 未归类 ──
  {
    const items = base();
    const index = { version: 1, file: '索引.md', total: 5, classified: 4, roots: ['咖啡', '吃的'],
      nodes: [{ path: '咖啡', name: '咖啡', depth: 1, count: 4, self_count: 4, items: ['xhs-a', 'xhs-b', 'bili-c', 'bili-d'], children: [], wiki: true, line: 1 },
        { path: '吃的', name: '吃的', depth: 1, count: 0, self_count: 0, items: [], children: [], line: 2 }],
      unclassified: { count: 1, items: ['bili-e'] }, wiki: { 咖啡: { file: 'wiki/咖啡.md', exists: true, new_since: 2 } }, text_ai: { ok: true } };
    const plugin = { settings: { hiddenCats: [] } };
    const P = await openCatalog({ data: dataOf(items), plugin, files: { '_archive/index-data.json': JSON.stringify(index), 'wiki/咖啡.md': '# 咖啡', '索引.md': '- 咖啡 [wiki]\n- 吃的\n' } });
    assert.ok(P.cat('未归类'), '分类行有未归类');
    P.$('.lbc-view[data-view="wiki"]').onclick();
    assert.equal(P.$('.lbc-wiki h3').textContent, 'Wiki');
    assert.match(P.$('.lbc-wiki-sub').textContent, /长期研究主题/);
    const row = P.$('.lbc-wiki-row[data-path="咖啡"]');
    assert.ok(row); assert.equal(row.querySelector('.lbc-wiki-st').textContent, 'wiki 生成后又进了 2 篇');
    assert.ok(row.querySelector('.lbc-wiki-open') && row.querySelector('.lbc-wiki-gen'));
    const unc = P.$('.lbc-wiki-unc');
    assert.match(unc.textContent, /未归类1 篇/); assert.match(unc.textContent, /兜底队列/);
    row.querySelector('.lbc-wiki-items').onclick(ev());
    assert.equal(P.$('.lbc-wiki').hidden, true); assert.deepEqual(P.ids().sort(), ['bili-c', 'bili-d', 'xhs-a', 'xhs-b'], '看这些帖子 = 筛到这一类');
    P.$('.lbc-view[data-view="wiki"]').onclick();
    P.$('.lbc-wiki-unc .lbc-wiki-items').onclick(ev());
    assert.deepEqual(P.ids(), ['bili-e'], '未归类');
    // 分类树（索引编辑）从 Wiki 页进，开着时视图开关多一项「索引」亮着
    P.$('.lbc-view[data-view="wiki"]').onclick();
    P.$('.lbc-wiki .lbc-index-open').onclick(ev());
    assert.ok(P.$('.lbc-wrap').classList.contains('is-indexview'));
    assert.ok(P.$('.lbc-view[data-view="index"]').classList.contains('is-on'));
    P.$('.lbc-view[data-view="grid"]').onclick();
    assert.equal(P.$('.lbc-view[data-view="index"]'), null, '回瀑布流后「索引」那一项收起');
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
    const groups = P.dom.document.body.querySelectorAll('.lbc-menu-label').map(x => x.textContent);
    assert.deepEqual(groups, ['整理分类', '回收站与删除', '其它']);
    const titles = P.menuItems().map(b => b.textContent);
    assert.ok(titles.includes('回收站（2 篇，可恢复）'), titles);
    assert.ok(titles.some(t => /^索引编辑/.test(t)) && titles.some(t => /^删除一个分类…（只删分类，帖子不删）/.test(t)) && titles.some(t => /^彻底删除…/.test(t)), titles);
    pickMenu(P, /^回收站（2 篇/); await tick(5);
    assert.equal(P.app.workspace.opened.at(-1)[0], '回收站.md', '点回收站 = 打开回收站页');
    // 1027：改标题 / 每行几列挪进「编排」（标题模块 / 收藏墙模块的「调整」），管理菜单里不再重复
    assert.ok(!titles.some(t => /^改标题|^每行几列/.test(t)), titles);
    // 删除一个分类：有内容的先问帖子去哪（这里取消）——说清帖子不删、可以回到未归类
    P.$('.lb-manage').onclick(ev()); await tick(5);
    pickMenu(P, /^删除一个分类/); await tick(5);
    P.dom.document.body.querySelector('.lbi-pick-row[data-path="咖啡"]').onclick(); await tick(5);
    assert.equal(calls.at(-1), 'confirm:删掉分类「咖啡」：里面的 4 篇帖子去哪？');
    const note = notes.at(-1);
    assert.match(note.message, /没删。要让这 4 篇回到「未归类」/);
    // 索引编辑 = 分类树视图
    P.$('.lb-manage').onclick(ev()); await tick(5);
    pickMenu(P, /^索引编辑/);
    assert.ok(P.$('.lbc-wrap').classList.contains('is-indexview'));
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
  console.log('PASS catalog 1026 scenes 02/03/08: platform → topic → tag → type compose and survive Wiki / grid switches (filter in Wiki returns to results) · 最近导入 查看全部 (sorted by import time, 50 per page, page kept) · Wiki = long-term topics + 未归类 always visible · 管理 grouped (trash with count, delete-category explains where posts go) · delete notice links the trash');
})().catch(e => { console.error(e); process.exit(1); });

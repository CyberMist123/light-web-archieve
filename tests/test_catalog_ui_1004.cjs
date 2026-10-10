// 10-04 目录页界面批（她点名）：
// ⑫ 悬停卡片就有选中圈，点圈直接勾选（不用先进多选），勾了就是多选态、全取消就退出
// ⑬ 有选中时右键：「导出」立即导出（沿用上次的「附带原图」，默认带图）；新增「给 AI（存成选集）」
// ⑭ 选集：默认名「主题+MMDD」（共同标签 → 主题 → 大类 → 第一篇标题前 8 字），可改名，存 _archive/selections.json，同名先确认
// ⑮ 导入时间：排序「最近导入」+ 范围 今天 / 近 7 天 / 近 30 天 / 自定义起止，入口是筛选条里一个小按钮；「全部」一并清掉
// ④ 页面外框隐形的样式也在目录页
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json', SEL = '_archive/selections.json';
const DAY = 86400000;
const iso = ms => new Date(ms).toISOString();
const ymd = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');

(async () => {
  const now = Date.now();
  const mk = (id, title, ageDays, tags, cats = ['城市']) => ({ id, title, tags, cats, topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: '', attachment: 'none', starred: false, ts: iso(now - ageDays * DAY), date: ymd(new Date(now - ageDays * DAY)) });
  // 故意不按时间排：默认顺序 = 数据顺序，「最近导入」才按导入时间新→旧
  const items = [mk('old', '两个月前的图数据库', 60, ['graph', '旧']), mk('d3', '三天前的知识图谱', 3, ['graph']), mk('today', '今天导入的咖啡', 0, ['#咖啡']), mk('d20', '二十天前的 Obsidian 插件', 20, [], ['其他'])];
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: iso(now), pinyin_chars: {}, aliases: [], cats_order: ['城市'], cats: [], topics: [], items }), '_archive/sync-status.json': '{}' });
  const exports = [];
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {},
    async exportArchiveBundle(ids, images, md, opts) { exports.push({ ids: [...ids], images, opts }); return { path: '收藏导出/x.zip' }; } };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const CODE = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js');
  let dom, A;
  const open = async (keepState) => {
    if (!keepState) delete globalThis.__lbState;
    delete globalThis.__lbListeners;
    dom = makeDom(); A = dataviewBlock({ dom, app, code: CODE }); A.window.confirm = () => true; await A.run();
  };
  const $ = s => A.section.querySelector(s), $$ = s => A.section.querySelectorAll(s);   // 批次 D：页面挂在 dv.container 后面的 host 上
  const ids = () => $$('.lbc-card').map(c => items.find(it => it.title === c.querySelector('.lbc-ctitle').textContent).id);
  const card = id => $$('.lbc-card').find(c => c.querySelector('.lbc-ctitle').textContent === items.find(it => it.id === id).title);
  const menuItems = () => dom.document.body.querySelectorAll('.lbc-menu-item');
  const pick = label => menuItems().find(b => b.textContent === label || b.textContent === '✓ ' + label);
  const ev = { preventDefault() {}, stopPropagation() {}, clientX: 0, clientY: 0 };

  await open();
  // ④ 目录页也带外框隐形样式（X14c：样式挂 head 的 #lbc-style，wrap 里没有 style）
  assert.ok(dom.document.getElementById('lbc-style').textContent.includes('.cm-embed-block:has(.block-language-dataviewjs)'));
  assert.equal($$('style').length, 0);

  // ⑫ 每张卡都有选中圈；平时不是多选态
  assert.equal($$('.lbc-check').length, 4);
  assert.ok(!A.section.querySelector('.lbc-wrap').classList.contains('is-selecting'));
  card('d3').querySelector('.lbc-check').onclick(ev);
  assert.ok(card('d3').classList.contains('is-selected'));
  assert.equal($('.lbc-selbar').hidden, false, '点圈直接进多选态');
  assert.ok($('.lbc-wrap').classList.contains('is-selecting'), '有选中时每张卡都显示圈');
  assert.equal(card('d3').querySelector('.lbc-check').getAttribute('aria-pressed'), 'true');
  card('old').querySelector('.lbc-check').onclick(ev);
  assert.equal($$('.lbc-card.is-selected').length, 2);
  // 多选态下点卡片本身照旧是勾选（不打开）
  card('today').onclick({}); assert.equal($$('.lbc-card.is-selected').length, 3);
  card('today').onclick({}); assert.equal($$('.lbc-card.is-selected').length, 2);

  // ⑬ 有选中时右键：右键的这张没选上就一起算进来；「导出」立即导出、默认带图，不弹二次选项
  card('d20').oncontextmenu(ev);
  assert.deepEqual(menuItems().map(b => b.textContent), ['导出选中的 3 篇', '给 AI（存成选集）', '收藏选中的 3 篇', '删除选中的 3 篇（移到回收站）', '退出多选']);
  await pick('导出选中的 3 篇').onclick(ev); await tick(5);
  assert.equal(exports.length, 1);
  assert.deepEqual(exports[0].ids.sort(), ['d20', 'd3', 'old']);
  assert.equal(exports[0].images, true);
  assert.equal(dom.document.body.querySelectorAll('.lbc-dialog').length, 0);
  // CM2：成功提示由插件那一条负责；页面只发一条「正在导出」并收起
  assert.ok(A.noticeLog.some(n => n.message === '正在导出 3 篇…' && n.hidden));
  assert.ok(!A.notices.some(m => m.includes('已导出')));
  // 上次取消了「附带原图」（C15：收进「更多…」）：右键导出沿用；换页回来还记得
  $('.lbc-moresel').onclick(ev); pick('附带原图').onclick(ev);
  card('d3').oncontextmenu(ev); await pick('导出选中的 3 篇').onclick(ev); await tick(5);
  assert.equal(exports[1].images, false);
  // 取消选中到 0：退出多选态
  for (const id of ['d3', 'old', 'd20']) card(id).querySelector('.lbc-check').onclick(ev);
  assert.equal($('.lbc-selbar').hidden, true);
  assert.ok(!$('.lbc-wrap').classList.contains('is-selecting'));
  await open(true);
  card('d3').querySelector('.lbc-check').onclick(ev);
  $('.lbc-moresel').onclick(ev);
  assert.equal(menuItems().find(b => b.textContent.endsWith('附带原图')).textContent, '附带原图', '附带原图的选择记住了（没打勾）');
  pick('附带原图').onclick(ev);
  card('d3').querySelector('.lbc-check').onclick(ev);
  // 没选中时右键单张：导出这一篇（立即）、给 AI、多选、删除
  card('today').oncontextmenu(ev);
  assert.deepEqual(menuItems().map(b => b.textContent), ['收藏', '编辑标签', '导出', '给 AI（存成选集）', '多选', '删除（移到回收站）']);
  await pick('导出').onclick(ev); await tick(5);
  assert.deepEqual(exports[2].ids, ['today']); assert.equal(exports[2].images, true);

  // ⑭ 选集：选两篇 graph → 右键「给 AI（存成选集）」→ 默认名 graph+MMDD，可改名 → 存进 selections.json
  card('old').querySelector('.lbc-check').onclick(ev); card('d3').querySelector('.lbc-check').onclick(ev);
  card('d3').oncontextmenu(ev); pick('给 AI（存成选集）').onclick(ev);
  const dlg = () => dom.document.body.querySelector('.lbc-dialog');
  const d = new Date(), mmdd = String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
  assert.equal(dlg().querySelector('input').value, 'graph' + mmdd);
  assert.ok(dlg().textContent.includes('两个月前的图数据库') && dlg().textContent.includes('看一下选集 graph' + mmdd));
  const saveBtn = () => dlg().querySelectorAll('button').find(b => b.textContent === '存');
  await saveBtn().onclick(); await tick(5);
  let doc = JSON.parse(V.get(SEL));
  assert.equal(doc.selections.length, 1);
  assert.equal(doc.selections[0].name, 'graph' + mmdd);
  assert.deepEqual(doc.selections[0].ids.sort(), ['d3', 'old']);
  assert.ok(!Number.isNaN(Date.parse(doc.selections[0].created_at)));
  assert.equal(dlg(), null, '存完对话框关掉');
  assert.ok(A.notices.some(m => m.includes(`已存成选集「graph${mmdd}」，对 AI 说：看一下选集 graph${mmdd}`)));
  // 改名再存一组（selbar 上的按钮同一个入口）；同名不确认就不覆盖
  $$('.lbc-selbar button').find(b => b.textContent === '给 AI（存成选集）').onclick();
  dlg().querySelector('input').value = '  我的 图谱 '; await saveBtn().onclick(); await tick(5);
  doc = JSON.parse(V.get(SEL));
  assert.deepEqual(doc.selections.map(s => s.name), ['我的 图谱', 'graph' + mmdd], '新的在前');
  A.window.confirm = () => false;
  $$('.lbc-selbar button').find(b => b.textContent === '给 AI（存成选集）').onclick();
  dlg().querySelector('input').value = '我的 图谱'; await saveBtn().onclick(); await tick(5);
  assert.equal(JSON.parse(V.get(SEL)).selections.length, 2);
  assert.ok(dlg(), '没确认覆盖：对话框还在');
  // 空名字不存；写盘失败：对话框留着、说清原因
  dlg().querySelector('input').value = ' '; await saveBtn().onclick(); await tick(5);
  assert.ok(dlg().querySelector('.lbc-dialog-err').textContent.includes('起个名字'));
  const realWrite = V.vault.adapter.write; V.vault.adapter.write = async () => { throw new Error('EPERM'); };
  dlg().querySelector('input').value = '新名字'; await saveBtn().onclick(); await tick(5);
  assert.ok(dlg().querySelector('.lbc-dialog-err').textContent.includes('没存上，可重试：EPERM'));
  V.vault.adapter.write = realWrite; A.window.confirm = () => true;
  dlg().querySelectorAll('button').find(b => b.textContent === '取消').onclick();
  assert.equal(dlg(), null);
  // 默认名的退路：没有共同标签 / 主题 / 大类（「其他」不算）→ 第一篇标题前 8 个字（去掉标点空格）
  for (const id of ['old', 'd3']) card(id).querySelector('.lbc-check').onclick(ev);
  card('d20').oncontextmenu(ev); pick('给 AI（存成选集）').onclick(ev);
  assert.equal(dlg().querySelector('input').value, '二十天前的Obs' + mmdd);
  dlg().querySelectorAll('button').find(b => b.textContent === '取消').onclick();
  card('today').oncontextmenu(ev); pick('给 AI（存成选集）').onclick(ev);
  assert.equal(dlg().querySelector('input').value, '咖啡' + mmdd, '标签前面的 # 去掉');
  dlg().querySelectorAll('button').find(b => b.textContent === '取消').onclick();

  // ⑮ 导入时间：筛选条里一个小入口
  await open();
  assert.deepEqual(ids(), ['old', 'd3', 'today', 'd20'], '默认 = 数据顺序');
  const timeTab = () => $('.lbc-time');
  assert.equal(timeTab().textContent, '导入时间');
  timeTab().onclick(ev); pick('最近导入').onclick(ev);
  assert.deepEqual(ids(), ['today', 'd3', 'd20', 'old']);
  assert.equal(timeTab().textContent, '最近导入');
  // 1011 紧凑版：排序一行分段、时间一行小块（全部 / 今天 / 7 天 / 30 天 / 自定义），选中的 is-on + aria-checked
  timeTab().onclick(ev);
  const tm = () => dom.document.body.querySelector('.lbc-time-menu');
  assert.deepEqual(tm().querySelectorAll('.lbc-seg-btn').map(b => b.textContent), ['默认', '最近导入']);
  assert.deepEqual(tm().querySelectorAll('.lbc-chip').map(b => b.textContent), ['全部', '今天', '7 天', '30 天', '自定义']);
  assert.deepEqual(tm().querySelectorAll('.lbc-menu-item.is-on').map(b => b.textContent), ['最近导入', '全部']);
  assert.equal(tm().querySelectorAll('.lbc-chip').find(b => b.textContent === '全部').getAttribute('aria-checked'), 'true');
  assert.equal(tm().querySelector('.lbc-range').hidden, true, '没选自定义时不露起止');
  pick('7 天').onclick(ev);
  assert.deepEqual(ids(), ['today', 'd3']);
  assert.equal(timeTab().textContent, '近 7 天 · 最近导入');
  assert.ok(timeTab().classList.contains('is-active'));
  timeTab().onclick(ev); pick('今天').onclick(ev); assert.deepEqual(ids(), ['today']);
  timeTab().onclick(ev); pick('30 天').onclick(ev); assert.deepEqual(ids(), ['today', 'd3', 'd20']);
  // 自定义起止（起止写反了也认）：点「自定义」只展开起止、菜单不关、筛选不变；点「筛选」才生效
  timeTab().onclick(ev);
  const range = dom.document.body.querySelector('.lbc-range');
  assert.equal(range.hidden, true);
  pick('自定义').onclick(ev);
  assert.ok(tm(), '点自定义菜单不关');
  assert.equal(range.hidden, false, '点自定义露出起止');
  assert.deepEqual(tm().querySelectorAll('.lbc-chip.is-on').map(b => b.textContent), ['自定义']);
  assert.deepEqual(ids(), ['today', 'd3', 'd20'], '还没点筛选：结果不变');
  const [from, to] = range.querySelectorAll('input');
  from.value = ymd(new Date(now - 2 * DAY)); to.value = ymd(new Date(now - 25 * DAY));
  range.querySelector('button').onclick(ev);
  assert.deepEqual(ids(), ['d3', 'd20']);
  assert.ok(/^\d\d-\d\d~\d\d-\d\d · 最近导入$/.test(timeTab().textContent));
  timeTab().onclick(ev);
  assert.equal(tm().querySelector('.lbc-range').hidden, false, '已是自定义：再打开直接露起止');
  assert.deepEqual(tm().querySelectorAll('.lbc-chip.is-on').map(b => b.textContent), ['自定义']);
  tm().__lbcClose();
  // 换页回来还在
  await open(true);
  assert.deepEqual(ids(), ['d3', 'd20']);
  // 和搜索叠加：搜「图」只剩 d3（old 不在时间范围里）
  $('.lbc-search').value = '图'; $('.lbc-search').fire('keydown', { key: 'Enter', isComposing: false, preventDefault() {} });
  assert.deepEqual(ids(), ['d3']);
  $('.lbc-search').value = ''; $('.lbc-search').fire('input');
  // 「全部」把时间筛选和排序一并清掉
  $$('.lbc-cat').find(b => b.textContent === '全部').onclick();
  assert.deepEqual(ids(), ['old', 'd3', 'today', 'd20']);
  assert.equal(timeTab().textContent, '导入时间');

  console.log('PASS catalog 1004: hover check selects without entering multi-select first, right-click 导出 exports immediately (remembered 附带原图), 给 AI saves a named selection (default 主题+MMDD, rename, overwrite confirm, write failure honest), import-time sort / today / 7d / 30d / custom range, 全部 resets');
})().catch(e => { console.error(e); process.exit(1); });

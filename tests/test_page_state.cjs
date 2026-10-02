// 第 2 批（CONVENTIONS §5）：页面状态与重绘。真跑 lb-page-lib.js + 三个页面脚本，假 DOM + 假 Dataview（同一容器反复 rerun）。
// 断言：
//   §5.1 版本没变 → 旧 DOM 原样挂回、不重读 catalog-data；版本变了 → 不重建整页，卡片按 id 复用（封面元素是同一个）
//   §5.2 解析结果缓存在插件对象上：换页回来（新容器）同版本不再读文件
//   §5.3 搜索词 / 筛选 / 多选 / 滚动 / 问答草稿存 sessionStorage，新容器里恢复；草稿不写 vault
//   §5.6 不读 notes.json；link-brain:star 事件更新卡片
//   来源阅读：整段单击不打开；引用编号 / 查看 → 单篇；「加入对照」→ compare；「退出对照」「收起来源」走插件；无假进度轮播
//   批注块：notes.json 没变 → 框原样留着、正在打的字不丢；别处改了 → 只重读重画
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const LIB = asset('lb-page-lib.js');
const SEARCH = asset('catalog-search.js');
const DATA = '_archive/catalog-data.json';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

function catalogData(extra = []) {
  const mk = (id, title, more = {}) => ({ id, title, tags: [], cats: ['城市'], topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: `_archive/${id}/c.png`, cover_w: 600, cover_h: 800, attachment: 'none', starred: false, ...more });
  return { built_at: '2026-10-02T10:00:00+10:00', pinyin_chars: {}, aliases: [], cats_order: ['城市', '吃的'], cats: [], topics: [],
    items: [mk('a', '悉尼咖啡地图'), mk('b', '悉尼海边徒步'), mk('c', '电饭煲鸡肉饭', { cats: ['吃的'] }), ...extra.map(x => mk(...x))] };
}
function makeApp(V, plugin) {
  return { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
}
const titles = c => c.querySelectorAll('.lbc-card').map(x => x.querySelector('.lbc-ctitle').textContent);

async function catalogTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const V = makeVault({ [DATA]: JSON.stringify(catalogData()), '_archive/sync-status.json': '{}' });
  const plugin = { settings: { hiddenCats: [] }, openAttachments() {}, openCategories() {}, openLibraryPage() {}, starNote: async (id, on) => ({ starred: on }) };
  const app = makeApp(V, plugin);
  const code = LIB + '\n' + SEARCH + '\n' + asset('catalog-view.js');
  const A = dataviewBlock({ dom, app, code });
  await A.run();
  assert.equal(V.reads[DATA], 1);
  const wrap = A.container.querySelector('.lbc-wrap');
  assert.ok(wrap.querySelector('style'), '样式在 wrap 里，复用时跟着走');
  // 封面先占位：有宽高就写进 img 属性
  const img = A.container.querySelector('.lbc-cover');
  assert.equal(img.getAttribute('width'), '600'); assert.equal(img.getAttribute('height'), '800');
  // 搜「悉尼」，进多选，选两篇
  const input = A.container.querySelector('.lbc-search');
  input.value = '悉尼'; input.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} });
  assert.deepEqual(titles(A.container), ['悉尼咖啡地图', '悉尼海边徒步']);
  const cards = A.container.querySelectorAll('.lbc-card');
  cards[0].oncontextmenu({ preventDefault() {}, clientX: 0, clientY: 0 });
  dom.document.body.querySelectorAll('.lbc-menu-item').find(b => b.textContent === '多选删除').onclick({ stopPropagation() {} });
  A.container.querySelectorAll('.lbc-card')[1].onclick({});
  assert.equal(A.container.querySelectorAll('.lbc-card.is-selected').length, 2);
  A.host.scrollTop = 640; A.host.fire('scroll'); await tick(40);

  // ── Dataview 重跑、数据没变：整页 DOM 是同一个、不重读、搜索词和多选都在 ──
  const firstCard = A.container.querySelectorAll('.lbc-card')[0];
  await A.rerun();
  assert.equal(A.container.querySelector('.lbc-wrap'), wrap, '旧 DOM 挂回');
  assert.equal(A.container.children.length, 1, '没有叠出第二份');
  assert.equal(V.reads[DATA], 1, '版本没变不重读 catalog-data');
  assert.equal(A.container.querySelector('.lbc-search').value, '悉尼');
  assert.equal(A.container.querySelectorAll('.lbc-card.is-selected').length, 2);

  // ── 数据变了（同步进来一篇）：不重建整页，旧卡片元素复用，新卡片出现，搜索词不丢 ──
  V.set(DATA, JSON.stringify(catalogData([['d', '悉尼超市折扣日']])));
  await A.rerun();
  assert.equal(A.container.querySelector('.lbc-wrap'), wrap, '版本变了也不换整页');
  assert.equal(V.reads[DATA], 2);
  assert.deepEqual(titles(A.container), ['悉尼咖啡地图', '悉尼海边徒步', '悉尼超市折扣日']);
  assert.equal(A.container.querySelectorAll('.lbc-card')[0], firstCard, '没变的卡片是同一个元素（封面不重载）');
  assert.equal(A.container.querySelector('.lbc-search').value, '悉尼');

  // ── 星标：不读 notes.json；事件更新卡片 ──
  assert.equal(Object.keys(V.reads).filter(p => p.endsWith('notes.json')).length, 0, '不再逐篇读 notes.json');
  app.workspace.trigger('link-brain:star', 'b', true);
  const cardB = A.container.querySelectorAll('.lbc-card').find(c => c.querySelector('.lbc-ctitle').textContent === '悉尼海边徒步');
  assert.ok(cardB.querySelector('.lbc-star').classList.contains('is-on'));
  assert.equal(plugin.catalogCache.data.items.find(x => x.id === 'b').starred, true, '缓存里的条目跟着改');

  // ── 打开一篇（同一窗格）再返回：新容器，同版本走插件缓存不读文件；搜索词、多选、滚动恢复 ──
  const B = dataviewBlock({ dom, app, code });
  await B.run();
  assert.equal(V.reads[DATA], 2, '换页回来同版本：用插件对象里的解析结果');
  assert.equal(B.container.querySelector('.lbc-search').value, '悉尼');
  assert.equal(titles(B.container).length, 3);
  assert.equal(B.container.querySelectorAll('.lbc-card.is-selected').length, 2, '多选状态恢复');
  assert.ok(!B.container.querySelector('.lbc-selbar').hidden, '多选条还在');
  await tick(5);
  assert.equal(B.host.scrollTop, 640, '滚动位置恢复');
  // 筛选也恢复：点「吃的」，再换页回来
  B.container.querySelector('.lbc-search').value = ''; B.container.querySelector('.lbc-search').oninput();
  B.container.querySelectorAll('.lbc-cat').find(x => x.textContent === '吃的').onclick();
  const C = dataviewBlock({ dom, app, code });
  await C.run();
  assert.ok(C.container.querySelectorAll('.lbc-cat').find(x => x.textContent === '吃的').classList.contains('is-active'));
  assert.deepEqual(titles(C.container), ['电饭煲鸡肉饭']);
  // 平时点卡片：同一窗格打开（openLinkText 第三个参数 false），按住 Ctrl 才开新标签
  const D = dataviewBlock({ dom, app, code });
  delete globalThis.__lbState;
  await D.run();
  D.container.querySelectorAll('.lbc-card')[0].onclick({});
  D.container.querySelectorAll('.lbc-card')[0].onclick({ ctrlKey: true });
  assert.deepEqual(app.workspace.opened.map(x => x[2]), [false, true]);
  // 计时埋点（§5.8）
  const marks = globalThis.__lbPerf.catalog.marks.map(m => m[0]);
  for (const m of ['read(cache)', 'render', 'restore', 'total']) assert.ok(marks.includes(m), m + ' ' + marks);
  console.log('PASS catalog: rerun reuses DOM without reread, data change updates cards in place, cache across pages, state + scroll restored, no notes.json reads');
}

async function chatTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const V = makeVault({ [DATA]: JSON.stringify(catalogData()), '_archive/chat-session.json': JSON.stringify({ turns: [], draft: '' }), '_archive/chat-archive.json': '{"entries":[]}' });
  const calls = [];
  let reader = false, compare = false, finish;
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { for (const t of String(md).split('\n\n')) el.createEl('p', { text: t }); },
    answerArchive: req => new Promise(res => { finish = r => { req.onDelta('流式'); res(r); }; }),
    openArchiveSource: async (note, host, cmp) => { calls.push(['open', note, cmp]); if (cmp && reader) compare = true; reader = true; },
    archiveSourceState: () => ({ reader, compare }),
    closeArchiveCompare: () => { calls.push(['closeCompare']); compare = false; },
    closeArchiveSources: () => { calls.push(['closeAll']); reader = compare = false; },
  };
  const app = makeApp(V, plugin);
  const code = LIB + '\n' + SEARCH + '\n' + asset('chat-view.js');
  const A = dataviewBlock({ dom, app, code });
  await A.run();
  const wrap = A.container.querySelector('.lbchat');
  assert.equal(A.container.querySelector('.lbchat-reader-layout'), null, '「单篇 / 对照」下拉去掉了');
  // 打草稿：不写 vault
  const ta = A.container.querySelector('.lbchat-search');
  ta.value = '半句草稿'; ta.oninput();
  assert.equal(V.writes['_archive/chat-session.json'] || 0, 0, '键入不写 chat-session.json');
  await A.rerun();
  assert.equal(A.container.querySelector('.lbchat'), wrap, '问收藏页重跑也挂回旧 DOM');
  assert.equal(A.container.querySelector('.lbchat-search').value, '半句草稿');
  const B = dataviewBlock({ dom, app, code });
  await B.run();
  assert.equal(B.container.querySelector('.lbchat-search').value, '半句草稿', '换页回来草稿还在');

  // 提问：只显示「正在生成…」，不轮播
  ta.value = '悉尼有什么'; await A.container.querySelector('.lbchat-composer').onsubmit({ preventDefault() {} });
  await tick(5);
  assert.ok(wrap.textContent.includes('正在生成…'));
  assert.ok(!/正在检索收藏|正在读相关笔记|正在整理答案/.test(wrap.textContent));
  // 生成中 Dataview 重跑：旧 DOM 挂回，流式文字照样写进来
  await A.rerun();
  assert.equal(A.container.querySelector('.lbchat'), wrap);
  finish({ status: 'ok', markdown: '第一段。\n\n咖啡店在这里 [来源1]', sources: [{ citation: 1, title: '悉尼咖啡地图', note: 'Web/a.md', excerpts: [] }] });
  await tick(20);
  assert.equal(V.writes['_archive/chat-session.json'], 2, '只在轮次变化时写会话（问出去一次、答完一次）');
  assert.ok(!JSON.parse(V.get('_archive/chat-session.json')).draft, '会话文件里不再存草稿');
  // 整段单击不打开来源
  const para = A.container.querySelectorAll('p').find(p => p.textContent.includes('咖啡店在这里'));
  assert.ok(!para.onclick, '段落上没有单击打开');
  assert.ok(!para.classList.contains('lbchat-source-block'));
  // 引用编号 → 单篇（复用右侧来源窗格）
  await para.querySelector('.lbchat-cite').onclick({ stopPropagation() {} });
  assert.deepEqual(calls.at(-1), ['open', 'Web/a.md', false]);
  await tick(5);
  const bar = A.container.querySelector('.lbchat-srcbar');
  assert.ok(!bar.hidden); assert.ok(bar.textContent.includes('收起来源')); assert.ok(!bar.textContent.includes('退出对照'));
  // 参考材料：查看 / 加入对照
  const refs = A.container.querySelector('.lbchat-src');
  const btn = t => refs.querySelectorAll('button').find(b => b.textContent === t);
  await btn('查看').onclick(); assert.deepEqual(calls.at(-1), ['open', 'Web/a.md', false]);
  assert.ok(A.container.querySelector('.lbchat-body').classList.contains('lbchat-has-reader'), '右侧有来源时才露出「加入对照」');
  await btn('加入对照').onclick(); assert.deepEqual(calls.at(-1), ['open', 'Web/a.md', true]);
  await tick(5);
  assert.ok(bar.textContent.includes('退出对照'));
  bar.querySelectorAll('button').find(b => b.textContent === '退出对照').onclick();
  assert.deepEqual(calls.at(-1), ['closeCompare']);
  assert.ok(!bar.textContent.includes('退出对照'));
  bar.querySelectorAll('button').find(b => b.textContent === '收起来源').onclick();
  assert.deepEqual(calls.at(-1), ['closeAll']);
  assert.ok(bar.hidden);
  console.log('PASS chat: rerun keeps DOM (even mid-answer), draft in sessionStorage not vault, 正在生成… only, sources open only via cite/title/查看, explicit 加入对照/退出对照/收起来源');
}

async function annotateTests() {
  delete globalThis.__lbState;
  const dom = makeDom();
  const NOTE = '_archive/xiaohongshu/n1/notes.json';
  const V = makeVault({ [NOTE]: JSON.stringify({ starred: false, annotations: [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }] }) });
  const app = makeApp(V, { settings: {} });
  globalThis.Notice = class {};
  const code = LIB + '\n' + asset('annotate-view.js');
  const A = dataviewBlock({ dom, app, code, params: { itemId: 'xhs-n1', notePath: NOTE } });
  await A.run();
  const box = A.container.querySelector('.lba-annot');
  const ta = box.querySelector('.lba-annot-input');
  ta.focus(); ta.value = '正在打的字';
  const readsBefore = V.reads[NOTE];
  await A.rerun();
  assert.equal(A.container.querySelector('.lba-annot'), box, '批注框原样留着');
  assert.equal(V.reads[NOTE], readsBefore, 'notes.json 没变不重读');
  assert.equal(ta.value, '正在打的字');
  // 手机同步回来一条：重读、列表多一条，输入框里的字不动
  V.set(NOTE, JSON.stringify({ starred: true, annotations: [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }, { id: 'a2', ts: '2026-09-02T00:00:00Z', text: '手机写的' }] }));
  await A.rerun();
  assert.equal(A.container.querySelector('.lba-annot'), box);
  assert.deepEqual(box.querySelectorAll('.lba-annot-text').map(x => x.textContent), ['旧的', '手机写的']);
  assert.ok(box.querySelector('.lba-star').classList.contains('is-on'));
  assert.equal(ta.value, '正在打的字');
  // 本端保存：自己写的不算「别处改了」，下次重跑不重读
  ta.value = '新批注'; await ta.onblur(); await tick(5);
  const r = V.reads[NOTE];
  await A.rerun();
  assert.equal(V.reads[NOTE], r, '本端刚写过，版本已跟上');
  console.log('PASS annotate: rerun keeps the box and typed text; external change re-reads and re-renders list only; own save does not trigger reread');
}

(async () => {
  await catalogTests();
  await chatTests();
  await annotateTests();
})().catch(e => { console.error(e); process.exitCode = 1; });

// 1021 目录页改版（Collection+ 设计交接包第 1、2 段）：假 DOM 上真跑整段目录页脚本。
//   ① 页头：雕刻标题的 data-text 跟着标题设置走；「管理」胶囊；没有「浏览收藏」导航；字体 @font-face 走资源路径（过 lbPath，不连外网）
//   ② 范围单选：点一个清掉其他、再点当前项回全部；旧版本存下的叠加状态只留一个；返回后还在（LB.state）
//   ③ 「列表」视图：表格五列、和瀑布流同一份筛选 / 搜索结果、点行打开笔记、视图选择存 LB.state、没结果照旧出空状态
//   ④ 星标主题：快捷标签 → 主题行；+ 新主题行内输入 → 插件 run(topic add) → 重读目录、选中新主题、如实提示；失败说原因、字还在；
//      × 点两次 → run(topic remove)；没有插件（手机）不出建 / 删入口
//   ⑤ 边栏钮：开 / 收只换 class、状态存 LB.state；无封面卡 = 柔和文字封面
'use strict';
const assert = require('node:assert/strict');
const { DATA, tick, item, catalogData, openCatalog, ev } = require('./_fake_l1.cjs');

const today = (() => { const d = new Date(); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })();
const base = () => [
  item('a', '悉尼咖啡地图', { date: today, starred: true, topics: ['咖啡'], author: '咖啡小馆', likes: 12345 }),
  item('b', '电饭煲鸡肉饭', { cats: ['吃的'], kind: 'video', topics: ['做饭'], author: '小锅日记' }),
  item('c', '悉尼周末徒步', { attachment: 'downloaded', attachment_files: ['路线.pdf'], topics: ['咖啡', '做饭'] }),
  item('d', '番茄牛腩', { cats: ['吃的'], date: today, starred: true, author: '小锅日记' }),
];
const dataOf = (items, more = {}) => catalogData(items, { topics: ['咖啡', '做饭', '睡眠'], ...more });
const scope = (P, key) => P.$$('.lbc-scope-tab').find(b => b.dataset.scope === key);
const activeScopes = P => P.$$('.lbc-scope-tab').filter(b => b.classList.contains('is-active')).map(b => b.dataset.scope);
const state = () => JSON.parse(globalThis.__lbState['lb:catalog']);

(async () => {
  // ── ① 页头 ──
  {
    const plugin = { settings: { hiddenCats: [], catalogTitle: 'Collection' }, openManageMenu() {} };
    const P = await openCatalog({ data: dataOf(base()), plugin });
    const t = P.$('.lbc-title-text');
    assert.equal(t.textContent, 'Collection'); assert.equal(t.dataset.text, 'Collection', '刻线层和标题同字');
    assert.ok(t.classList.contains('lbc-engr') && P.$('.lbc-import').classList.contains('lbc-engr'), '标题和 + 都有刻线');
    assert.equal(P.$('.lbc-import').dataset.text, '+');
    plugin.settings.catalogTitle = '我的收藏';
    P.app.workspace.trigger('link-brain:catalog-prefs');
    assert.equal(t.textContent, '我的收藏'); assert.equal(t.dataset.text, '我的收藏', '改标题设置时刻线层一起换');
    assert.equal(P.$('.lb-manage').textContent, '管理', '「…」换成「管理」胶囊');
    assert.ok(P.$('.lbc-tools').contains(P.$('.lb-manage')));
    assert.equal(P.$('.lb-page-nav'), null, '「浏览收藏」导航去掉');
    assert.equal(P.$('.lbc-askbtn').textContent, '问收藏 →');
    assert.equal(P.$('.lbc-search').placeholder, '搜索收藏 · #标签');
    assert.ok(P.$('.lbc-searchbox').contains(P.$('.lbc-search')), '搜索框在胶囊里');
    // 篇数：数字加粗，字照旧
    assert.equal(P.$('.lbc-count').textContent, '4 篇'); assert.equal(P.$('.lbc-count b').textContent, '4');
    // 分类行只放「全部 + 分类」
    assert.deepEqual(P.$$('.lbc-cats .lbc-cat').map(b => b.textContent), ['全部', '城市', '吃的']);
    assert.deepEqual(P.$$('.lbc-scope-tab').map(b => [b.textContent, b.dataset.n]),
      [['全部', '4'], ['今日新增', '2'], ['已收藏', '2'], ['视频', '1'], ['附件', '1'], ['★咖啡', '2'], ['★做饭', '2']], '范围标签 + 前两个星标主题，篇数在 data-n');
    assert.equal(P.$('.lbc-time').textContent, '最新在前');
    // 字体：@font-face 用资源路径（过 lbPath），不连 Google Fonts
    const css = P.dom.document.head.querySelectorAll('style').find(s => s.getAttribute('id') === 'lbc-style').textContent;
    assert.ok(css.includes('@font-face{font-family:"LB Cinzel";src:url("app://_archive/fonts/Cinzel-latin-variable.woff2")'), css.slice(0, 300));
    assert.ok(css.includes('font-family:"LB Cormorant"') && !/googleapis|gstatic/.test(css));
    assert.ok(!/--interactive-accent\)/.test(css.slice(css.indexOf('1021 Collection+'), css.indexOf('.lbc-board{'))), '新页头 / 控制行只用黑白（不用强调色）');
    // 无封面卡 = 柔和文字封面：分类 / 标题 / 日期 / 类型
    const tile = P.card('c').querySelector('.lbc-nocover');
    assert.equal(tile.querySelector('.lbc-tile-cat').textContent, '城市');
    assert.equal(tile.querySelector('.lbc-tile-title').textContent, '悉尼周末徒步');
    assert.equal(tile.querySelector('.lbc-tile-ty').textContent, 'PDF');
    assert.match(tile.style.getPropertyValue('--lbc-tile'), /^#[0-9a-f]{6}$/);
    assert.equal(P.card('b').querySelector('.lbc-tile-ty').textContent, '▶ 视频');
    // 底行：首字头像 + 作者 + ♡；主题小胶囊最多 2 个
    assert.equal(P.card('a').querySelector('.lbc-av').textContent, '咖');
    assert.equal(P.card('a').querySelector('.lbc-au-name').textContent, '咖啡小馆');
    assert.equal(P.card('a').querySelector('.lbc-likes').textContent, '♡ 1.2万');
    assert.deepEqual(P.card('c').querySelectorAll('.lbc-ctopics span').map(s => s.textContent), ['★ 咖啡', '★ 做饭']);
    assert.equal(P.card('d').querySelector('.lbc-ctopics'), null, '不属于主题的不出');
  }

  // ── ② 范围单选 ──
  {
    const P = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } } });
    P.cat('今日新增').onclick();
    assert.deepEqual(P.ids().sort(), ['a', 'd']); assert.deepEqual(activeScopes(P), ['today']);
    P.cat('视频').onclick();
    assert.deepEqual(P.ids(), ['b'], '点「视频」= 换成只看视频，不和今日新增叠加');
    assert.deepEqual(activeScopes(P), ['video']);
    assert.deepEqual([state().today, state().media, state().star], [false, 'video', false]);
    P.cat('视频').onclick();
    assert.equal(P.ids().length, 4, '再点当前项回全部'); assert.deepEqual(activeScopes(P), ['']);
    // 范围和分类各管各的：分类「全部」不清范围
    P.cat('已收藏').onclick(); P.cat('吃的').onclick();
    assert.deepEqual(P.ids(), ['d']);
    P.$$('.lbc-cats .lbc-cat').find(b => b.textContent === '全部').onclick();
    assert.deepEqual(P.ids().sort(), ['a', 'd'], '分类「全部」只清分类');
    assert.deepEqual(activeScopes(P), ['star']);
    // 返回后还在
    const Q = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } }, keepState: true });
    assert.deepEqual(activeScopes(Q), ['star']); assert.deepEqual(Q.ids().sort(), ['a', 'd']);
    // 旧版本存下的叠加状态（今日新增 + 已收藏 + 视频）：只留一个（顺序同 scopeOf：已收藏优先）
    globalThis.__lbState['lb:catalog'] = JSON.stringify({ ...state(), today: true, star: true, media: 'video' });
    const R = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } }, keepState: true });
    assert.deepEqual(activeScopes(R), ['star']);
    assert.deepEqual([state().today, state().media, state().star], [false, '', true]);
  }

  // ── ③ 视图开关（1023 她拍板：只留瀑布流 + Wiki 空页；列表 / 索引入口藏起来）──
  {
    const P = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } } });
    const views = () => P.$$('.lbc-vseg .lbc-view').map(b => [b.textContent, b.classList.contains('is-on')]);
    assert.deepEqual(views(), [['瀑布流', true], ['Wiki', false]], '没有列表 / 索引入口');
    P.$('.lbc-view[data-view="wiki"]').onclick();
    assert.deepEqual(views(), [['瀑布流', false], ['Wiki', true]]);
    assert.equal(P.$('.lbc-grid').hidden, true); assert.equal(P.$('.lbc-wiki').hidden, false);
    assert.equal(state().view, 'wiki', '视图选择存 LB.state');
    const Q = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } }, keepState: true });
    assert.equal(Q.$('.lbc-wiki').hidden, false, '返回后还是 Wiki');
    Q.$('.lbc-view[data-view="grid"]').onclick();
    assert.equal(Q.$('.lbc-wiki').hidden, true); assert.equal(Q.$('.lbc-grid').hidden, false); assert.equal(Q.cards().length, 4);
    assert.equal(state().view, 'grid');
  }

  // ── ④ 星标主题：建 / 删 ──
  {
    const runs = [];
    let reply = null;
    const plugin = { settings: { hiddenCats: [] }, async run(args, label, slow, opts) { runs.push([args, label, opts]); return reply(args); } };
    const P = await openCatalog({ data: dataOf(base()), plugin });
    assert.equal(P.$('.lbc-topics'), null, '没选主题不出主题行');
    scope(P, 'topic:咖啡').onclick();
    assert.deepEqual(P.ids().sort(), ['a', 'c']);
    assert.ok(P.$('.lbc-topics'), '选中主题 → 主题行');
    assert.deepEqual(P.$$('.lbc-topic').map(b => [b.textContent, b.dataset.n, b.classList.contains('is-active')]), [['★咖啡', '2', true], ['★做饭', '2', false], ['★睡眠', '0', false]]);
    // 建：成功 → 后端重建过目录，页面重读、选中新主题、提示几篇
    P.$('.lbc-topic-add').onclick();
    const input = () => P.$('input.lbc-topic-new');
    assert.ok(input(), '行内输入框');
    reply = args => { P.V.set(DATA, JSON.stringify(dataOf(base().map(it => (it.id === 'b' ? { ...it, topics: ['做饭', '电饭煲'] } : it)), { topics: ['咖啡', '做饭', '睡眠', '电饭煲'] }))); return { code: 0, json: { status: 'ok', topic: { id: 't4', name: '电饭煲', count: 1 }, keywords_from: 'name', catalog: 'rebuilt' } }; };
    input().value = '电饭煲';
    input().fire('keydown', { key: 'Enter', isComposing: false, keyCode: 13, preventDefault() {} });
    await tick(10);
    assert.deepEqual(runs.at(-1)[0], ['-m', 'link_brain', 'topic', 'add', '电饭煲']);
    assert.equal(runs.at(-1)[2].quiet, true, '提示由页面说（如实带篇数）');
    assert.deepEqual(P.ids(), ['b'], '重读目录后选中新主题');
    assert.ok(P.$$('.lbc-topic').find(b => b.textContent === '★电饭煲').classList.contains('is-active'));
    assert.equal(P.A.notices.at(-1), '已建主题「电饭煲」：1 篇');
    assert.equal(input(), null, '建完收起输入框');
    // 建：失败 → 说原因，输入框里的字还在
    P.$('.lbc-topic-add').onclick();
    reply = () => ({ code: 1, out: '', json: { status: 'error', error: '主题名要 1-20 个字、不含换行' } });
    input().value = '太长了'.repeat(9);
    input().fire('keydown', { key: 'Enter', isComposing: false, keyCode: 13, preventDefault() {} });
    await tick(10);
    assert.equal(P.A.notices.at(-1), '建主题没做成：主题名要 1-20 个字、不含换行');
    assert.equal(input().value, '太长了'.repeat(9), '失败字还在');
    // 插件忙（code 6）：用插件的占用句
    plugin.busyText = () => '正在同步收藏（3/40），完成后再点，或在底部状态栏停止';
    reply = () => ({ code: 6, out: '', json: { ok: false, message: plugin.busyText() } });
    input().fire('keydown', { key: 'Enter', isComposing: false, keyCode: 13, preventDefault() {} });
    await tick(10);
    assert.equal(P.A.notices.at(-1), '正在同步收藏（3/40），完成后再点，或在底部状态栏停止');
    input().fire('keydown', { key: 'Escape', preventDefault() {}, stopPropagation() {} });
    assert.equal(input(), null, 'Esc 收起输入框');
    // 删：× 点一下变「再点删除」，第二下才删；删的是当前主题 → 回到全部、主题行收起
    const del = name => P.$$('.lbc-topic-wrap').find(w => w.querySelector('.lbc-topic').textContent === '★' + name).querySelector('.lbc-topic-del');
    const before = runs.length;
    del('电饭煲').onclick(ev());
    assert.equal(runs.length, before, '第一下不删');
    assert.equal(del('电饭煲').textContent, '再点删除');
    reply = () => { P.V.set(DATA, JSON.stringify(dataOf(base()))); return { code: 0, json: { status: 'ok', removed: { id: 't4', name: '电饭煲' }, catalog: 'rebuilt' } }; };
    del('电饭煲').onclick(ev());
    await tick(10);
    assert.deepEqual(runs.at(-1)[0], ['-m', 'link_brain', 'topic', 'remove', '电饭煲']);
    assert.equal(P.A.notices.at(-1), '已删主题「电饭煲」');
    assert.equal(P.$('.lbc-topics'), null); assert.equal(P.ids().length, 4);
    // 目录没重建上：如实说主题已存好、目录没刷新
    scope(P, 'topic:咖啡').onclick();
    P.$('.lbc-topic-add').onclick();
    reply = () => ({ code: 0, json: { status: 'ok', topic: { id: 't5', name: '烘焙' }, catalog: 'failed', catalog_error: 'TimeoutError: 锁被占用' } });
    input().value = '烘焙'; input().fire('keydown', { key: 'Enter', isComposing: false, keyCode: 13, preventDefault() {} });
    await tick(10);
    assert.equal(P.A.notices.at(-1), '主题「烘焙」建好了，但目录没重建上：TimeoutError: 锁被占用（点「管理」→ 刷新目录再看）');
  }
  {
    // 一个主题都没有：控制行留「+ 星标主题」入口，点了直接出输入框
    const plugin = { settings: { hiddenCats: [] }, async run() { return { code: 0, json: { status: 'ok' } }; } };
    const P = await openCatalog({ data: dataOf(base().map(it => ({ ...it, topics: [] })), { topics: [] }), plugin });
    assert.equal(P.$$('.lbc-thq').length, 0);
    P.$('.lbc-topic-new-tab').onclick();
    assert.ok(P.$('.lbc-topics input.lbc-topic-new'));
    // 手机（没有插件）：能按主题筛，不出建 / 删入口
    const M = await openCatalog({ data: dataOf(base()), isMobile: true });
    scope(M, 'topic:咖啡').onclick();
    assert.ok(M.$('.lbc-topics'));
    assert.equal(M.$('.lbc-topic-add'), null); assert.equal(M.$('.lbc-topic-del'), null);
    assert.equal(M.$('.lbc-sidetoggle'), null, '手机上没有边栏钮');
  }

  // ── ⑤ 边栏钮 + 给边栏留的位置 ──
  {
    const P = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } } });
    const board = P.$('.lbc-board');
    assert.ok(board && board.querySelector('.lbc-side') && board.querySelector('.lbc-board-main .lbc-grid'), '收藏墙外面一层：左边边栏位、右边网格');
    assert.equal(P.$('.lbc-side').hidden, false, '第 3 段：边栏出来了（内容见 test_catalog_plus_side_1021）'); assert.ok(board.classList.contains('has-side'));
    const btn = P.$('.lbc-sidetoggle');
    assert.equal(btn.getAttribute('aria-pressed'), 'true');
    assert.equal(btn.getAttribute('aria-label'), null, '不设 aria-label（Obsidian 会出悬浮框）');
    btn.onclick();
    assert.ok(P.$('.lbc-wrap').classList.contains('is-side-collapsed')); assert.equal(state().side, false);
    const Q = await openCatalog({ data: dataOf(base()), plugin: { settings: { hiddenCats: [] } }, keepState: true });
    assert.ok(Q.$('.lbc-wrap').classList.contains('is-side-collapsed'), '返回后还是收起');
    assert.equal(Q.$('.lbc-sidetoggle').getAttribute('aria-pressed'), 'false');
  }
  console.log('PASS catalog 1021 Collection+: engraved title follows the title setting, 管理 pill, no 浏览收藏 nav, fonts via resource path; scope tabs single-select (old stacked state normalized, kept after return); 列表 view shares results, opens notes, remembered; topics quick tabs → topic row, add / remove via plugin run with honest notices (ok / failure keeps text / busy / catalog not rebuilt), no entry without plugin; sidebar toggle state + board slot; soft text covers');
})().catch(e => { console.error(e); process.exit(1); });

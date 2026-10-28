// 目录页就地编排：假 DOM 上真跑整段目录页脚本。1027 起步；1028 她「像搭积木一样」：页头拆成小块、宽度按 48 格、页头每一排里块有自己的起点（能留空）。
//   ① 默认布局和改版前一样（标题 + 计数行一排、分类一排、筛选条八小块一排；边栏 16 格：最近导入 · 同步 · Token 费用 · 概览，收藏墙 32 格）；打开不写设置
//   ② 编排：每块都有小工具条（⠿ · 名字 · A− A+ 字体 · 调整 · ×）；拖到排与排之间 = 单独成一排、拖进页头空地 = 就放在那儿（靠近别的块的边吸住）、
//      压在别的块上 = 并排 / 上下；点一下只是选中（不挪）；从块里面按住也能拖，拖完那一下不算点按钮；键盘挪
//   ③ × 放进备选 / 备选里点一下回原位置（带撤销提示）；移除一小块不影响别的（搜索框还在）
//   ④ 调宽：墙那一排两列之间的边、页头每块右边那道边，键盘左右一格（48 格，最窄 3 格），碰到旁边的块就停
//   ⑤ 调整（模块里展开）：最近导入条数、标题文字（catalogTitle，走 setCatalogPrefs 回读核对）、编排时点标题字就地改、收藏墙列数 / 密度、Token 每日上限 + 显示哪段、
//      概览显示哪些数、分类改名 / 换顺序 / 加分类（走 indexEdit → 索引.md）、同步 = 嵌插件那一个同步时间编辑器、字体 / 字号
//   ⑥ Aa 样式：标题 / 正文 / 数字字体、界面大小、卡片间距 → 共享令牌（--lb-font-* / --lb-scale / --lb-gap，没有 LB.applyTheme 就本页兜底写 body）
//   ⑦ 存：400ms 防抖、「保存中… / 已保存」；失败说「没保存上，改动还在页面上，可重试」，改动留在页面上，重试能存；新开一页按存的摆（往返一致）；
//      旧布局换算：1022 / 1026（side / top / …）和 1027（12 格、「筛选与搜索」一整块）都换成 48 格小块
//   ⑧ 手机 / 插件没开：没有「编排」，照默认摆
//   ⑨ 存样式：存为「样式 1」并锁住（退出编排）、改了显示「改过」、恢复默认 / 换回样式 1、改名
'use strict';
const assert = require('node:assert/strict');
const { tick, item, catalogData, openCatalog, ev } = require('./_fake_l1.cjs');

const iso = (d, k) => new Date(Date.UTC(2026, 9, d, k)).toISOString();
const base = () => Array.from({ length: 10 }, (_, i) => item('x' + i, '第 ' + i + ' 篇', { ts: iso(10 + i, 1), date: `2026-10-${10 + i}` }));
const notes = [];
function mkPlugin(more = {}) {
  const calls = [];
  const p = {
    calls, settings: { hiddenCats: [], catalogLayout: null, catalogTitle: '', catalogColumns: 0, catalogStyles: [], catalogStyleCur: '', ...(more.settings || {}) },
    notify(message, o = {}) { notes.push({ message, ...o }); return { hide() {} }; },
    async saveSettings() { calls.push(['save', JSON.parse(JSON.stringify(this.settings.catalogLayout))]); if (p.failSave) throw new Error(p.failSave); },
    markSettingDirty(...k) { calls.push(['dirty', ...k]); },
    async setCatalogPrefs({ title }) { calls.push(['prefs', title]); this.settings.catalogTitle = String(title || '').trim().slice(0, 40); await this.saveSettings(); },
    async getSyncSchedule() { return { enabled: true, summary: '每天 04:00', next_run: new Date(Date.now() + 3600e3).toISOString(), rules: [{ kind: 'daily', times: ['04:00'] }] }; },
    scheduleUI() { return { render(el, o) { calls.push(['sched-render', !!o.onSaved]); el.createEl('div', { cls: 'lb-sched', text: '同步时间编辑器' }); return { destroy() { calls.push(['sched-destroy']); } }; } }; },
    async indexEdit(op, path, o = {}) { calls.push(['indexEdit', op, path, o]); return { ok: true, message: '好了', path: o.name || path }; },
    ...more.methods,
  };
  return p;
}
const saves = p => p.calls.filter(c => c[0] === 'save');
const L = p => p.settings.catalogLayout;
const mod = (P, id) => P.$('.lbc-m-' + id);
const bar = (P, id, act) => mod(P, id).querySelector(`.lbc-mod-bar [data-act="${act}"]`);
const topRows = P => P.$('.lbc-top').children.filter(c => c.classList.contains('lbc-row') && !c.hidden).map(r => r.children.filter(c => c.classList.contains('lbc-rcol') && !c.hidden).map(c => c.children.filter(m => m.classList.contains('lbc-m') && !m.classList.contains('is-gone')).map(m => m.dataset.m)));
const boardCols = P => P.$('.lbc-board').children.filter(c => (c.classList.contains('lbc-side') || c.classList.contains('lbc-wallcol')) && !c.hidden).map(c => c.children.filter(m => m.classList.contains('lbc-m') && !m.classList.contains('is-gone')).map(m => m.dataset.m));
const FILTER_ROW = [['scope'], ['topics'], ['types'], ['albums'], ['picks'], ['sort'], ['view'], ['search'], ['ask']];
const colOf = (P, id) => mod(P, id).parentNode;
const xw = (P, id) => [Number(colOf(P, id).dataset.x), Number(colOf(P, id).dataset.w)];
// 编排用的假几何：页宽 1200（一格 25px）；页头每一排 40 高、排和排之间空 30；块按自己的 x / w 落位。边栏 380 宽、墙 780 宽
function rects(P) {
  let y = 0;
  for (const row of P.$('.lbc-top').children.filter(c => c.classList.contains('lbc-row') && !c.hidden)) {
    const h = row.querySelector('.lbc-m-title') ? 100 : 40;
    row._rect = { top: y, left: 0, width: 1200, height: h };
    for (const c of row.children.filter(c => c.classList.contains('lbc-rcol') && !c.hidden)) {
      const x = Number(c.dataset.x || 0) * 25, w = Number(c.dataset.w || 48) * 25;
      c._rect = { top: y, left: x, width: w, height: h };
      const ms = c.children.filter(m => m.classList.contains('lbc-m') && !m.classList.contains('is-gone'));
      ms.forEach((m, i) => { m._rect = { top: y + i * (h / ms.length), left: x, width: w, height: h / ms.length }; });
    }
    y += h + 30;
  }
  const R = (id, top, left, width, height) => { const el = mod(P, id); if (el && el.parentNode?.classList?.contains('lbc-side')) el._rect = { top, left, width, height }; };
  R('recent', 400, 0, 380, 150); R('sync', 560, 0, 380, 200); R('token', 770, 0, 380, 100); R('overview', 880, 0, 380, 60); R('title', 400, 0, 380, 80);
  const wall = mod(P, 'wall'); wall._rect = { top: 400, left: 420, width: 780, height: 2000 };
  P.$('.lbc-wrap')._rect = { top: 0, left: 0, width: 1200, height: 3000 };
}
async function dragTo(P, id, x, y) {
  const g = bar(P, id, 'drag'), r = mod(P, id)._rect || { left: 0, top: 0 };
  g.fire('pointerdown', { clientX: r.left + 5, clientY: r.top + 5, button: 0, pointerId: 1, preventDefault() {} });
  P.dom.document.dispatchEvent({ type: 'pointermove', clientX: x, clientY: y });
  await tick(5);
  P.dom.document.dispatchEvent({ type: 'pointerup', clientX: x, clientY: y });
  await tick(5);
}
const menuItem = (P, re) => P.dom.document.body.querySelectorAll('.lbc-menu-item').find(b => re.test(b.textContent));

(async () => {
  // ── ① 默认 ──
  {
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    await tick(450);
    assert.deepEqual(topRows(P), [[['title'], ['meta']], [['cats']], FILTER_ROW], '页头三排：标题 + 计数行、分类、筛选条八小块');
    assert.deepEqual(boardCols(P), [['recent', 'sync', 'token', 'overview'], ['wall']], '边栏四块 + 墙');
    assert.equal(P.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,16fr) minmax(0,32fr)', '边栏 16/48、墙 32/48（和改版前一样宽）');
    assert.equal(colOf(P, 'title').style.width, 'calc(34 * 100% / 48)', '页头的块按 48 格定宽');
    assert.equal(colOf(P, 'ask').style.width, '', '筛选小块没拉过宽度：跟内容一样宽');
    assert.ok(colOf(P, 'scope').classList.contains('is-tight') && !colOf(P, 'title').classList.contains('is-tight'), '筛选小块至少有内容那么宽');
    assert.ok(P.$('.lbc-m-search').contains(P.$('.lbc-search')) && P.$('.lbc-m-meta').contains(P.$('.lbc-count')), '搜索框、计数在各自的块里');
    assert.equal(L(p), null); assert.equal(saves(p).length, 0, '打开不写设置');
    assert.equal(P.$('.lbc-mod-bar'), null, '工具条第一次进编排才建');
    assert.ok(P.$('.lbc-top').firstChild.classList.contains('lbc-tools'), '「编排 / 管理」不属于任何模块，在吸顶区最前');
  }

  // ── ② 进编排 + 拖到任何位置 ──
  {
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    assert.ok(P.$('.lbc-wrap').classList.contains('is-arranging'));
    assert.equal(P.$$('.lbc-mod-bar').length, 17, '十七块都有工具条（1028 加了专辑）');
    for (const id of ['title', 'meta', 'scope', 'search', 'recent', 'wall']) assert.ok(bar(P, id, 'drag') && bar(P, id, 'adjust') && bar(P, id, 'remove'), id + '：⠿ / 调整 / ×');
    assert.equal(P.$('.lbc-arrange-tray').nextSibling, P.$('.lbc-top'), '编排条在所有模块上面（页面最前）');
    rects(P);
    // 点一下 ⠿（没挪）= 只是选中，位置不变（1028 她：「点一下 a，a 就跳到下面去了」）
    await dragTo(P, 'meta', 855, 6);
    assert.deepEqual(topRows(P)[0], [['title'], ['meta']], '点一下不挪');
    assert.ok(mod(P, 'meta').classList.contains('is-sel'), '点一下 = 选中');
    // 最近导入 → 标题那一排和分类那一排之间：单独成一排，从最左边起、宽度照旧 16 格
    await dragTo(P, 'recent', 300, 115);
    assert.deepEqual(topRows(P).map(r => r.map(c => c[0])), [['title', 'meta'], ['recent'], ['cats'], FILTER_ROW.map(c => c[0])], '排与排之间 = 单独一排');
    assert.deepEqual(boardCols(P)[0], ['sync', 'token', 'overview']);
    assert.deepEqual(xw(P, 'recent'), [0, 16]);
    assert.equal(P.$$('.lbc-m.is-dragging').length, 0, '拖完不留拖动样式');
    // 问收藏 → 最近导入那一排的空地（x≈1000px = 第 40 格）：就放在那儿
    rects(P);
    await dragTo(P, 'ask', 1005, 140);
    assert.deepEqual(topRows(P)[1], [['recent'], ['ask']], '放进空地');
    assert.deepEqual(xw(P, 'ask'), [40, 4]);
    assert.deepEqual(topRows(P)[3], FILTER_ROW.slice(0, -1), '筛选条那一排少了问收藏，别的不动');
    // 再拖一点，靠近计数行的左边（第 38 格）就吸过去
    rects(P);
    await dragTo(P, 'ask', 930, 140);   // 第 37 格
    assert.deepEqual(xw(P, 'ask'), [37, 4], '离别的块的边 1 格以内吸住（搜索框左边第 37 格）');
    await tick(450);
    const a = L(p).modules.find(m => m.id === 'ask');
    assert.deepEqual([a.x, a.y, a.width], [37, 1, 4], '存成 {x, y, width}（48 格）'); assert.equal(L(p).grid, 48);
    // 从块里面按住拖（不是 ⠿）：真拖了，松手那一下 click 不落到按钮上
    rects(P);
    const sb = mod(P, 'sort');
    let clicked = 0; const tab = sb.querySelector('.lbc-time'); const was = tab.onclick; tab.onclick = () => { clicked++; };
    sb.fire('pointerdown', { target: tab, clientX: sb._rect.left + 5, clientY: sb._rect.top + 5, button: 0, pointerId: 2 });
    P.dom.document.dispatchEvent({ type: 'pointermove', clientX: 600, clientY: 140 }); await tick(5);
    P.dom.document.dispatchEvent({ type: 'pointerup', clientX: 600, clientY: 140 });
    // 浏览器里 click 紧跟着 pointerup 来（在任何定时器之前）
    const eat = P.dom.document.listeners.click || [];
    let stopped = false; for (const fn of eat) fn({ type: 'click', target: tab, stopPropagation() { stopped = true; }, preventDefault() {} });
    assert.ok(stopped, '拖完那一下 click 被吞掉'); assert.equal(clicked, 0); tab.onclick = was;
    await tick(5);
    assert.deepEqual(topRows(P)[1], [['recent'], ['sort'], ['ask']], '从块里面也能拖');
    // 标题 → 边栏里「同步」上面（模块平级：标题能进边栏那一列）
    rects(P);
    await dragTo(P, 'title', 100, 570);
    assert.deepEqual(boardCols(P)[0], ['title', 'sync', 'token', 'overview'], '标题进了边栏');
    assert.ok(mod(P, 'title').parentNode.classList.contains('has-core'), '有页头块的边栏列：边栏收起 / 窄屏时这一块留着');
    // 键盘：⠿ 上按 ↑ = 往上挪（同一列里换位置）；单独一排的就和上一排换；← → 在页头一次挪一格
    bar(P, 'sync', 'drag').onkeydown({ key: 'ArrowUp', preventDefault() {} });
    assert.deepEqual(boardCols(P)[0], ['sync', 'title', 'token', 'overview']);
    bar(P, 'cats', 'drag').onkeydown({ key: 'ArrowUp', preventDefault() {} });
    assert.deepEqual(topRows(P).map(r => r[0][0]), ['meta', 'cats', 'recent', 'scope'], '单独一排的就和上一排换');
    bar(P, 'meta', 'drag').onkeydown({ key: 'ArrowLeft', preventDefault() {} });
    assert.deepEqual(xw(P, 'meta'), [33, 14], '← 挪一格');
    // Esc：先取消选中，再按一次退出（输入框里的 Esc 不算）
    const keys = () => P.dom.document.listeners.keydown || [];
    for (const fn of keys()) fn({ key: 'Escape', target: P.$('.lbc-wrap'), preventDefault() {} });
    assert.equal(P.$$('.lbc-m.is-sel').length, 0, 'Esc 先取消选中'); assert.ok(P.$('.lbc-wrap').classList.contains('is-arranging'));
    for (const fn of keys()) fn({ key: 'Escape', target: P.$('.lbc-wrap'), preventDefault() {} });
    assert.equal(P.$('.lbc-wrap').classList.contains('is-arranging'), false, '再按 Esc 退出编排');
    // 新开一页：按存的摆
    await tick(450);
    const Q = await openCatalog({ data: catalogData(base()), plugin: p });
    assert.deepEqual(topRows(Q).map(r => r[0][0]), ['meta', 'cats', 'recent', 'scope']);
    assert.deepEqual(xw(Q, 'meta'), [33, 14]); assert.deepEqual(xw(Q, 'ask'), [37, 4]);
    assert.deepEqual(boardCols(Q)[0], ['sync', 'title', 'token', 'overview'], '往返一致');
  }

  // ── ③ 移除（进备选）/ 加回 ──
  {
    notes.length = 0;
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    assert.match(P.$('.lbc-at-shelf').textContent, /备选空/, '备选一开始是空的');
    bar(P, 'overview', 'remove').onclick(ev());
    assert.ok(mod(P, 'overview').classList.contains('is-gone'));
    assert.deepEqual(boardCols(P)[0], ['recent', 'sync', 'token']);
    assert.match(notes.at(-1).message, /「概览」放进备选了：内容和功能都还在/);
    const add = P.$('.lbc-at-shelf [data-show="overview"]');
    assert.ok(add && add.textContent === '＋ 概览', '备选里出「＋ 概览」');
    add.onclick();
    assert.deepEqual(boardCols(P)[0], ['recent', 'sync', 'token', 'overview'], '加回原位置');
    // 页头一小块：只藏它自己，搜索框还在
    bar(P, 'scope', 'remove').onclick(ev());
    assert.ok(mod(P, 'scope').classList.contains('is-gone') && !mod(P, 'search').classList.contains('is-gone'));
    assert.deepEqual(topRows(P)[2], FILTER_ROW.slice(1), '筛选条那一排少了「范围」，别的块位置不动');
    assert.deepEqual(xw(P, 'topics'), [12, 6], '空出来的地方就空着（「AI 标签」还从第 12 格起）');
    // 墙那一排：全部边栏模块移除 → 边栏整列让开
    for (const id of ['recent', 'sync', 'token', 'overview']) bar(P, id, 'remove').onclick(ev());
    assert.ok(P.$('.lbc-wrap').classList.contains('is-side-empty'));
    assert.deepEqual(boardCols(P), [['wall']]);
    // 恢复默认（样式 ▾ 里）
    P.$('.lbc-arrange-tray [data-act="styles"]').onclick(ev()); await tick(5);
    menuItem(P, /恢复默认/).onclick(ev());
    await tick(450);
    assert.deepEqual(boardCols(P), [['recent', 'sync', 'token', 'overview'], ['wall']]);
    assert.equal(L(p), null, '恢复默认 = catalogLayout 写回 null');
  }

  // ── ④ 调宽 ──
  {
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    const edge = () => P.$$('.lbc-col-edge').find(e => e.parentNode === P.$('.lbc-board'));
    assert.ok(edge(), '边栏和墙之间有一道可拖的边');
    edge().onkeydown({ key: 'ArrowRight', preventDefault() {} });
    assert.equal(P.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,17fr) minmax(0,31fr)', '→ 边栏宽一格（48 格）');
    for (let i = 0; i < 20; i++) edge().onkeydown({ key: 'ArrowLeft', preventDefault() {} });
    assert.equal(P.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,3fr) minmax(0,45fr)', '最窄 3 格');
    await tick(450);
    assert.equal(L(p).modules.find(m => m.id === 'sync').width, 3);
    assert.equal(L(p).modules.find(m => m.id === 'wall').width, 45);
    // 页头：每块右边一道边；碰到旁边那块就停，往左变窄
    const tEdge = () => P.$$('.lbc-col-edge.is-free').find(e => e.dataset.row === '0' && e.dataset.edge === '0');
    assert.ok(tEdge(), '页头的块右边有一道边');
    tEdge().onkeydown({ key: 'ArrowRight', preventDefault() {} });
    assert.deepEqual(xw(P, 'title'), [0, 34], '右边挨着计数行：不再变宽');
    tEdge().onkeydown({ key: 'ArrowLeft', preventDefault() {} });
    assert.deepEqual(xw(P, 'title'), [0, 33]); assert.equal(colOf(P, 'title').style.width, 'calc(33 * 100% / 48)');
    // 边栏模块的侧边框 = 同一个调宽（左右键）；下边框调高（上下键 / 双击恢复），存进 options.h
    const rx = P.$('.lbc-mod-sync .lbc-m-rs-x');
    assert.ok(rx && !rx.hidden, '并排时侧边框可拖'); assert.equal(rx.classList.contains('is-left'), false, '边栏在左：拖右边框');
    rx.onkeydown({ key: 'ArrowRight', preventDefault() {} });
    assert.equal(P.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,4fr) minmax(0,44fr)');
    const ry = P.$('.lbc-mod-token .lbc-m-rs-y');
    ry.onkeydown({ key: 'ArrowDown', preventDefault() {} }); ry.onkeydown({ key: 'ArrowDown', preventDefault() {} });
    const tk = P.$('.lbc-mod-token');
    assert.ok(tk.classList.contains('has-h')); const h = parseInt(tk.style.getPropertyValue('--lbc-m-h'), 10); assert.ok(h >= 80, '高度 ' + h);
    await tick(450);
    assert.equal(L(p).modules.find(m => m.id === 'token').options.h, h, '高度存进 catalogLayout');
    ry.ondblclick({ stopPropagation() {} });
    assert.equal(tk.classList.contains('has-h'), false, '双击 = 跟内容走');
    // 工具条上直接改字号 / 字体
    const bt = act => P.$(`.lbc-m-sync .lbc-mod-bar [data-act="${act}"]`);
    assert.ok(bt('smaller') && bt('bigger') && bt('font'), '工具条上有 A− / A+ / 字体');
    assert.equal(P.$('.lbc-board-main .lbc-mod-bar [data-act="bigger"]'), null, '收藏墙没有字号');
    bt('bigger').onclick(ev());
    assert.equal(mod(P, 'sync').style.getPropertyValue('--lbc-m-k'), '1.15', 'A+ 一档 = 115%');
    bt('font').onclick(ev()); await tick(5);
    const it = menuItem(P, /思源宋体/);
    assert.ok(it, '字体菜单列出全部字体'); it.onclick(ev());
    assert.match(mod(P, 'sync').style.getPropertyValue('--f-sans'), /Noto Serif SC/, '字体菜单点一下就换');
  }

  // ── ⑤ 调整 + 点标题字就地改 ──
  {
    const p = mkPlugin();
    const index = { version: 1, file: '索引.md', total: 10, classified: 6, roots: ['咖啡', '旅行'],
      nodes: [{ path: '咖啡', name: '咖啡', depth: 1, count: 4, items: ['x0', 'x1', 'x2', 'x3'], children: [], line: 1 }, { path: '旅行', name: '旅行', depth: 1, count: 2, items: ['x4', 'x5'], children: [], line: 2 }],
      unclassified: { count: 4, items: ['x6', 'x7', 'x8', 'x9'] } };
    const P = await openCatalog({ data: catalogData(base(), { usage_month: { month: '2026-10', cost_cny: 1.5 } }), plugin: p, files: { '_archive/index-data.json': JSON.stringify(index), '索引.md': '- 咖啡\n- 旅行\n' } });
    await tick(5);
    P.$('.lb-arrange').onclick();
    bar(P, 'recent', 'adjust').onclick(ev());
    const panel = () => P.$('.lbc-mp');
    assert.equal(panel().dataset.panel, 'recent'); assert.ok(mod(P, 'recent').contains(panel()), '在模块里展开（不弹窗）');
    if (mod(P, 'recent').classList.contains('is-folded')) mod(P, 'recent').querySelector('.lbc-fold-sum').onclick();
    const cnt = panel().querySelector('[data-k="count"]'); cnt.value = '2'; cnt.onchange();
    assert.equal(P.$('.lbc-mod-recent .lbc-rec').style.getPropertyValue('--lbc-rec-rows'), '2');
    const size = panel().querySelector('[data-k="size"]'); size.value = '130'; size.onchange();
    assert.equal(mod(P, 'recent').style.getPropertyValue('--lbc-m-k'), '1.3');
    // 标题文字：「调整」里输入即改，存走 setCatalogPrefs
    bar(P, 'title', 'adjust').onclick(ev());
    const t = panel().querySelector('[data-k="title"]'); t.value = 'MY ARCHIVE'; t.fire('input');
    assert.equal(P.$('.lbc-title-text').textContent, 'MY ARCHIVE', '标题当场换');
    await P.A.rerun(); await tick(5);
    assert.ok(P.$('.lbc-wrap').classList.contains('is-arranging') && P.$('.lbc-mp [data-k="title"]') === t, '重跑后输入框还是同一个');
    await tick(450);
    assert.deepEqual(p.calls.filter(c => c[0] === 'prefs').at(-1), ['prefs', 'MY ARCHIVE']);
    // 编排时点一下标题字：就地改，回车存
    bar(P, 'title', 'adjust').onclick(ev());
    const tl = P.$('.lbc-title-text');
    tl.fire('click', { stopPropagation() {} });
    assert.equal(tl.contentEditable, 'true', '点标题字 = 就地改');
    tl.textContent = 'LER& FABLE+';
    tl.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} });
    assert.equal(tl.contentEditable, 'false');
    await tick(450);
    assert.equal(p.settings.catalogTitle, 'LER& FABLE+', '标题存进 catalogTitle（和「调整」同一个）');
    tl.fire('click', { stopPropagation() {} }); tl.textContent = '不要了';
    tl.onkeydown({ key: 'Escape', isComposing: false, preventDefault() {}, stopPropagation() {} });
    assert.equal(tl.textContent, 'LER& FABLE+', 'Esc 放弃');
    // 收藏墙：列数 / 密度
    bar(P, 'wall', 'adjust').onclick(ev());
    const c3 = panel().querySelector('[data-k="cols"]'); c3.value = '3'; c3.onchange();
    const den = panel().querySelector('[data-k="density"]'); den.value = 's'; den.onchange();
    await tick(450);
    assert.equal(p.settings.catalogColumns, 3);
    assert.equal(L(p).modules.find(m => m.id === 'wall').options.density, 's');
    // Token：显示今天 + 每日上限
    p.runPy = async () => ({ json: { ok: true, budget: { spent_today: 0.42, daily_yuan: 3 } } });
    bar(P, 'token', 'adjust').onclick(ev());
    const per = panel().querySelector('[data-k="period"]'); per.value = 'day'; per.onchange();
    await tick(10);
    assert.equal(P.$('.lbc-mod-token .lbc-tk-big').textContent, '¥ 0.42');
    const bud = panel().querySelector('[data-k="budget"]'); bud.value = '5'; bud.onchange();
    assert.equal(p.settings.budget.dailyYuan, 5);
    // 概览：只留两个数、不要柱图
    bar(P, 'overview', 'adjust').onclick(ev());
    P.$('.lbc-mod-overview .lbc-fold-sum').onclick?.();
    for (const k of ['week', 'cats', 'bars']) { const ck = panel().querySelector(`[data-k="${k}"]`); ck.checked = false; ck.onchange(); }
    assert.deepEqual(P.$$('.lbc-mod-overview .lbc-fig-l').map(x => x.textContent), ['全部收藏', '已收藏']);
    // 分类：改名（走插件 indexEdit → 写 索引.md）
    bar(P, 'cats', 'adjust').onclick(ev());
    const nm = panel().querySelector('.lbc-mp-cat[data-path="咖啡"] [data-k="name"]'); nm.value = '咖啡豆'; nm.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} });
    await tick(10);
    assert.deepEqual(p.calls.filter(c => c[0] === 'indexEdit').at(-1).slice(0, 3), ['indexEdit', 'rename', '咖啡']);
    // 同步：嵌插件那一个同步时间编辑器
    bar(P, 'sync', 'adjust').onclick(ev());
    assert.ok(panel().querySelector('.lb-sched'));
    bar(P, 'sync', 'adjust').onclick(ev());
    assert.equal(P.$('.lbc-mp'), null, '再点「调整」收起');
    await tick(450);
    const Q = await openCatalog({ data: catalogData(base()), plugin: p, files: { '_archive/index-data.json': JSON.stringify(index) } });
    await tick(5);
    assert.equal(mod(Q, 'recent').style.getPropertyValue('--lbc-m-k'), '1.3');
    assert.equal(Q.$('.lbc-title-text').textContent, 'LER& FABLE+');
  }

  // ── ⑥ Aa 样式 ──
  {
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    P.$('.lbc-arrange-tray [data-act="style"]').onclick();
    assert.equal(P.$('.lbc-at-style').hidden, false);
    const sel = k => P.$(`.lbc-arrange-tray [data-theme="${k}"]`);
    const tf = sel('titleFont'); tf.value = 'Georgia'; tf.onchange();
    const host = P.$('.lbc-wrap').parentNode.style;
    assert.equal(host.getPropertyValue('--lb-font-title'), '"Georgia",var(--lb-font-title-base)');
    const gp = sel('gap'); gp.value = '17'; gp.onchange();
    assert.equal(P.$('.lbc-wrap').style.getPropertyValue('--lbc-sp'), '0.71'); assert.equal(host.getPropertyValue('--lb-gap'), '17px');
    const sc = sel('scale'); sc.value = '1.1'; sc.onchange();
    assert.equal(host.getPropertyValue('--lb-scale'), '1.1');
    await tick(450);
    assert.deepEqual(L(p).theme, { titleFont: 'Georgia', bodyFont: '', numberFont: '', scale: 1.1, gap: 17 });
    const gp2 = sel('gap'); gp2.value = '24'; gp2.onchange(); const sc2 = sel('scale'); sc2.value = '1'; sc2.onchange(); const tf2 = sel('titleFont'); tf2.value = ''; tf2.onchange();
    assert.equal(host.getPropertyValue('--lb-scale'), '', '回到默认就把令牌摘掉');
    await tick(450);
    assert.equal(L(p), null);
  }

  // ── ⑦ 存失败：说清、改动留着、重试；旧布局换算 ──
  {
    const p = mkPlugin(); p.failSave = '磁盘满了';
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    bar(P, 'token', 'remove').onclick(ev());
    await tick(450);
    const st = P.$('.lbc-arrange-tray .lbc-at-save');
    assert.equal(st.textContent, '没保存上，改动还在页面上，可重试：磁盘满了'); assert.ok(st.classList.contains('is-fail'));
    assert.ok(mod(P, 'token').classList.contains('is-gone'), '改动还在页面上');
    const retry = P.$('.lbc-arrange-tray [data-act="retry"]'); assert.equal(retry.hidden, false);
    p.failSave = null; await retry.onclick(); await tick(5);
    assert.equal(P.$('.lbc-arrange-tray .lbc-at-save').textContent, '已保存');
    assert.equal(L(p).modules.find(m => m.id === 'token').hidden, true);
    // 1022 / 1026 的旧布局：筛选项收起 = 左边四小块移除，排序 / 视图 / 搜索 / 问收藏还在
    const old = mkPlugin({ settings: { catalogLayout: { side: [{ id: 'overview' }, { id: 'sync', hidden: true }, 'bogus', { id: 'recent' }], top: [{ id: 'title' }, { id: 'filters', hidden: true }, { id: 'cats' }], sideRight: true, sideW: 'l', gap: 's', density: 's' } } });
    const O = await openCatalog({ data: catalogData(base()), plugin: old });
    assert.deepEqual(topRows(O), [[['title'], ['meta']], [['sort'], ['view'], ['search'], ['ask']], [['cats']]]);
    assert.ok(mod(O, 'scope').classList.contains('is-gone') && mod(O, 'picks').classList.contains('is-gone'));
    assert.deepEqual(boardCols(O), [['wall'], ['overview', 'token', 'recent']], '边栏放右边、同步隐藏、Token 补在同步后面');
    assert.equal(O.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,28fr) minmax(0,20fr)', '宽侧栏 = 5/12 → 20/48');
    assert.equal(O.$('.lbc-wrap').style.getPropertyValue('--lbc-sp'), '0.71');
    // 1027 的 12 格：最近导入在标题右边（x 8 / 宽 4）、筛选里不要排序 → 48 格、排序那一块移除
    const v27 = mkPlugin({ settings: { catalogLayout: { modules: [
      { id: 'title', x: 0, y: 0, width: 8, hidden: false }, { id: 'recent', x: 8, y: 0, width: 4, hidden: false },
      { id: 'cats', x: 0, y: 1, width: 12, hidden: false }, { id: 'filters', x: 0, y: 2, width: 12, hidden: false, options: { show: ['scope', 'type', 'tag', 'plat', 'src', 'view', 'ask'] } },
      { id: 'sync', x: 0, y: 3, width: 3, hidden: false }, { id: 'token', x: 0, y: 3, width: 3, hidden: false }, { id: 'overview', x: 0, y: 3, width: 3, hidden: false }, { id: 'wall', x: 3, y: 3, width: 9, hidden: false }] } } });
    const V = await openCatalog({ data: catalogData(base()), plugin: v27 });
    assert.deepEqual(topRows(V)[0], [['title', 'meta'], ['recent']], '标题和别的块并排：计数行叠在标题下面');
    assert.deepEqual(xw(V, 'recent'), [32, 16]);
    assert.ok(mod(V, 'sort').classList.contains('is-gone'), '旧「筛选显示」里去掉的排序 → 这一块移除');
    assert.equal(V.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,12fr) minmax(0,36fr)');
  }

  // ── ⑧ 手机 / 插件没开：没有编排 ──
  {
    const M = await openCatalog({ data: catalogData(base()), isMobile: true });
    assert.equal(M.$('.lb-arrange'), null);
    assert.deepEqual(topRows(M)[0], [['title'], ['meta']], '手机照默认摆');
    const N = await openCatalog({ data: catalogData(base()), plugin: null });
    assert.equal(N.$('.lb-arrange'), null, '插件没开：只读，不出编排');
    assert.deepEqual(boardCols(N), [['recent', 'sync', 'token', 'overview'], ['wall']]);
  }

  // ── ⑨ 存样式 / 锁住 / 恢复 ──
  {
    notes.length = 0;
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    bar(P, 'overview', 'remove').onclick(ev());
    assert.equal(P.$('.lbc-arrange-tray [data-act="save-style"]').textContent, '存为样式');
    P.$('.lbc-arrange-tray [data-act="save-style"]').onclick();
    assert.equal(P.$('.lbc-wrap').classList.contains('is-arranging'), false, '存完锁住（退出编排）');
    assert.deepEqual(p.settings.catalogStyles.map(s => s.name), ['样式 1']); assert.equal(p.settings.catalogStyleCur, '样式 1');
    assert.match(notes.at(-1).message, /存好了：「样式 1」，已锁定/);
    // 再编排、改一下：样式按钮写「改过」
    P.$('.lb-arrange').onclick();
    assert.match(P.$('.lbc-arrange-tray [data-act="styles"]').textContent, /^样式：样式 1 ▾/);
    bar(P, 'recent', 'remove').onclick(ev());
    assert.match(P.$('.lbc-arrange-tray [data-act="styles"]').textContent, /样式 1（改过）/);
    // 恢复默认，再换回样式 1
    P.$('.lbc-arrange-tray [data-act="styles"]').onclick(ev()); await tick(5);
    menuItem(P, /恢复默认/).onclick(ev());
    assert.deepEqual(boardCols(P)[0], ['recent', 'sync', 'token', 'overview']); assert.equal(p.settings.catalogStyleCur, '');
    P.$('.lbc-arrange-tray [data-act="styles"]').onclick(ev()); await tick(5);
    menuItem(P, /样式 1$/).onclick(ev());
    assert.deepEqual(boardCols(P)[0], ['recent', 'sync', 'token'], '换回样式 1（概览不在）');
    // 改名
    P.$('.lbc-arrange-tray [data-act="styles"]').onclick(ev()); await tick(5);
    menuItem(P, /改名/).onclick(ev());
    const inp = P.$('.lbc-arrange-tray .lbc-at-rename'); assert.ok(inp, '样式名就地变输入框');
    inp.value = '晚上看'; inp.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} });
    assert.deepEqual(p.settings.catalogStyles.map(s => s.name), ['晚上看']); assert.equal(p.settings.catalogStyleCur, '晚上看');
    assert.match(P.$('.lbc-arrange-tray [data-act="styles"]').textContent, /样式：晚上看/);
  }
  console.log('PASS catalog arrange 1027/1028: default = previous layout split into blocks, nothing written on open · 16 blocks with light toolbars · click selects without moving · drop between rows = own row, into empty space = stays there (snaps to edges), beside / above / below · drag from inside a block eats the trailing click · keyboard moves · × to 备选 / re-add in place · 48-col edge resize (min 3, stops at neighbour) · inline settings + click-to-edit title · Aa theme → shared tokens · autosave + retry · legacy 1022 / 1027 layouts migrate · mobile / no plugin read-only · saved styles: save locks, dirty mark, restore default / switch / rename');
})().catch(e => { console.error(e); process.exit(1); });

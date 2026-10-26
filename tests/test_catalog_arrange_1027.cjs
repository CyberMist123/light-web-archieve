// 1027 目录页就地编排（design-1027 §2，她批的结构和交互；外观仍是黑白雕刻）：假 DOM 上真跑整段目录页脚本。
//   ① 默认布局和改版前一样（标题 / 分类 / 筛选各一排，边栏 4 格：最近导入 · 同步 · Token 费用 · 概览，收藏墙 8 格）；打开不写设置
//   ② 编排：八个模块头上都有操作条（⠿ · 名字 · 调整 · ×），托盘在收藏墙上面；拖到任何位置——最近导入拖到标题右边成并排、标题拖进边栏
//   ③ × 移除 / 「＋ 模块」加回原位置（带撤销提示）；「筛选与搜索」移除只藏筛选项，搜索框还在
//   ④ 调宽：两列之间的边，键盘左右一格（12 格吸附，最窄 2 格），列宽写进 grid
//   ⑤ 调整（模块里展开）：最近导入条数、标题文字（catalogTitle，走 setCatalogPrefs 回读核对）、收藏墙列数 / 密度、Token 每日上限 + 显示哪段、
//      概览显示哪些数、筛选显示哪些、分类改名 / 换顺序 / 加分类（走 indexEdit → 索引.md）、同步 = 嵌插件那一个同步时间编辑器、字体 / 字号
//   ⑥ Aa 样式：标题 / 正文 / 数字字体、界面大小、卡片间距 → 共享令牌（--lb-font-* / --lb-scale / --lb-gap，没有 LB.applyTheme 就本页兜底写 body）
//   ⑦ 存：400ms 防抖、「保存中… / 已保存」；失败说「没保存上，改动还在页面上，可重试」，改动留在页面上，重试能存；新开一页按存的摆（往返一致）；
//      旧的 1022 / 1026 布局（side / top / sideRight / sideW / gap / density）换算成新的
//   ⑧ 手机 / 插件没开：没有「编排」，照默认摆
'use strict';
const assert = require('node:assert/strict');
const { tick, item, catalogData, openCatalog, ev } = require('./_fake_l1.cjs');

const iso = (d, k) => new Date(Date.UTC(2026, 9, d, k)).toISOString();
const base = () => Array.from({ length: 10 }, (_, i) => item('x' + i, '第 ' + i + ' 篇', { ts: iso(10 + i, 1), date: `2026-10-${10 + i}` }));
const notes = [];
function mkPlugin(more = {}) {
  const calls = [];
  const p = {
    calls, settings: { hiddenCats: [], catalogLayout: null, catalogTitle: '', catalogColumns: 0, ...(more.settings || {}) },
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
// 编排用的假几何：标题 / 分类 / 筛选一排一个，边栏 380 宽、墙 780 宽
function rects(P) {
  const R = (id, top, left, width, height) => { const el = mod(P, id); if (el) el._rect = { top, left, width, height }; };
  R('title', 0, 0, 1200, 100); R('cats', 110, 0, 1200, 40); R('filters', 160, 0, 1200, 40);
  R('recent', 300, 0, 380, 150); R('sync', 460, 0, 380, 200); R('token', 670, 0, 380, 100); R('overview', 780, 0, 380, 60); R('wall', 300, 420, 780, 2000);
}
async function dragTo(P, id, x, y) {
  const g = bar(P, id, 'drag');
  g.fire('pointerdown', { clientX: 5, clientY: 5, button: 0, pointerId: 1, preventDefault() {} });
  P.dom.document.dispatchEvent({ type: 'pointermove', clientX: x, clientY: y });
  await tick(5);
  P.dom.document.dispatchEvent({ type: 'pointerup', clientX: x, clientY: y });
  await tick(5);
}

(async () => {
  // ── ① 默认 ──
  {
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    await tick(450);
    assert.deepEqual(topRows(P), [[['title']], [['cats']], [['filters']]], '页头三排');
    assert.deepEqual(boardCols(P), [['recent', 'sync', 'token', 'overview'], ['wall']], '边栏四块 + 墙');
    assert.equal(P.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,4fr) minmax(0,8fr)', '边栏 4/12、墙 8/12（和改版前一样）');
    assert.equal(L(p), null); assert.equal(saves(p).length, 0, '打开不写设置');
    assert.equal(P.$('.lbc-mod-bar'), null, '操作条第一次进编排才建');
    assert.ok(P.$('.lbc-top').firstChild.classList.contains('lbc-tools'), '「编排 / 管理」不属于任何模块，在吸顶区最前');
  }

  // ── ② 进编排 + 拖到任何位置 ──
  {
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    assert.ok(P.$('.lbc-wrap').classList.contains('is-arranging'));
    assert.deepEqual(P.$$('.lbc-mod-bar .lbc-mb-nm').map(x => x.textContent).sort(), ['Token 费用', '分类', '同步', '收藏墙', '最近导入', '标题 / Logo', '概览', '筛选与搜索'].sort(), '八个模块都有操作条');
    for (const id of ['title', 'cats', 'filters', 'recent', 'sync', 'token', 'overview', 'wall']) assert.ok(bar(P, id, 'drag') && bar(P, id, 'adjust') && bar(P, id, 'remove'), id + '：⠿ / 调整 / ×');
    assert.equal(P.$('.lbc-arrange-tray').nextSibling, P.$('.lbc-board'), '托盘在收藏墙上面');
    rects(P);
    // 最近导入 → 标题右边：标题那一排成两列（标题 8 格、最近导入 4 格）
    await dragTo(P, 'recent', 1150, 50);
    assert.deepEqual(topRows(P)[0], [['title'], ['recent']], '最近导入并排到标题右边');
    assert.deepEqual(boardCols(P)[0], ['sync', 'token', 'overview']);
    assert.equal(P.$('.lbc-top .lbc-row').style.gridTemplateColumns, 'minmax(0,8fr) minmax(0,4fr)');
    assert.equal(P.$$('.lbc-mod.is-dragging').length, 0, '拖完不留拖动样式');
    await tick(450);
    const rec = L(p).modules.find(m => m.id === 'recent');
    assert.deepEqual([rec.x, rec.y, rec.width], [8, 0, 4], '存成 design-1027 的 {x, y, width}');
    // 标题 → 边栏里「同步」上面（模块平级：标题能进边栏那一列）
    rects(P);
    await dragTo(P, 'title', 100, 470);
    assert.deepEqual(boardCols(P)[0], ['title', 'sync', 'token', 'overview'], '标题进了边栏');
    assert.ok(mod(P, 'title').parentNode.classList.contains('lbc-side'));
    assert.ok(mod(P, 'title').parentNode.classList.contains('has-core'), '有标题的边栏列：边栏收起 / 窄屏时这一块留着');
    assert.deepEqual(topRows(P)[0], [['recent']], '标题走了，最近导入独占那一排');
    // 键盘：⠿ 上按 ↑ = 往上挪（同一列里换位置；到列头就单独成一排放上面）
    bar(P, 'sync', 'drag').onkeydown({ key: 'ArrowUp', preventDefault() {} });
    assert.deepEqual(boardCols(P)[0], ['sync', 'title', 'token', 'overview']);
    bar(P, 'filters', 'drag').onkeydown({ key: 'ArrowUp', preventDefault() {} });
    assert.deepEqual(topRows(P).map(r => r[0][0]), ['recent', 'filters', 'cats'], '单独一排的就和上一排换');
    // Esc 退出（输入框里的 Esc 不算）
    const ae = P.dom.document.listeners.keydown || [];
    for (const fn of ae) fn({ key: 'Escape', target: P.$('.lbc-wrap'), preventDefault() {} });
    assert.equal(P.$('.lbc-wrap').classList.contains('is-arranging'), false, 'Esc 退出编排');
    // 新开一页：按存的摆
    await tick(450);
    const Q = await openCatalog({ data: catalogData(base()), plugin: p });
    assert.deepEqual(topRows(Q).map(r => r[0][0]), ['recent', 'filters', 'cats']);
    assert.deepEqual(boardCols(Q)[0], ['sync', 'title', 'token', 'overview'], '往返一致');
  }

  // ── ③ 移除 / 加回 ──
  {
    notes.length = 0;
    const p = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin: p });
    P.$('.lb-arrange').onclick();
    bar(P, 'overview', 'remove').onclick(ev());
    assert.ok(mod(P, 'overview').classList.contains('is-gone'));
    assert.deepEqual(boardCols(P)[0], ['recent', 'sync', 'token']);
    assert.match(notes.at(-1).message, /已移除「概览」：内容和功能都还在/);
    const add = P.$('.lbc-arrange-tray [data-show="overview"]');
    assert.ok(add && add.textContent === '＋ 概览' && !P.$('.lbc-at-mods').hidden, '「＋ 模块」里出「＋ 概览」');
    add.onclick();
    assert.deepEqual(boardCols(P)[0], ['recent', 'sync', 'token', 'overview'], '加回原位置');
    // 筛选与搜索：× 只藏筛选项，搜索框还在
    bar(P, 'filters', 'remove').onclick(ev());
    assert.ok(mod(P, 'filters').classList.contains('is-off') && !mod(P, 'filters').classList.contains('is-gone'));
    assert.ok(mod(P, 'filters').contains(P.$('.lbc-search')));
    assert.ok(P.$('.lbc-arrange-tray [data-show="filters"]'));
    // 墙也能移除；全部边栏模块移除 → 边栏整列让开
    for (const id of ['recent', 'sync', 'token', 'overview']) bar(P, id, 'remove').onclick(ev());
    assert.ok(P.$('.lbc-wrap').classList.contains('is-side-empty'));
    assert.deepEqual(boardCols(P), [['wall']]);
    // 恢复默认
    P.$('.lbc-arrange-tray [data-act="reset"]').onclick();
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
    assert.equal(P.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,5fr) minmax(0,7fr)', '→ 边栏宽一格');
    for (let i = 0; i < 6; i++) edge().onkeydown({ key: 'ArrowLeft', preventDefault() {} });
    assert.equal(P.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,2fr) minmax(0,10fr)', '最窄 2 格');
    await tick(450);
    assert.equal(L(p).modules.find(m => m.id === 'sync').width, 2);
    assert.equal(L(p).modules.find(m => m.id === 'wall').width, 10);
  }

  // ── ⑤ 调整 ──
  {
    const p = mkPlugin();
    const index = { version: 1, file: '索引.md', total: 10, classified: 6, roots: ['咖啡', '旅行'],
      nodes: [{ path: '咖啡', name: '咖啡', depth: 1, count: 4, items: ['x0', 'x1', 'x2', 'x3'], children: [], line: 1 }, { path: '旅行', name: '旅行', depth: 1, count: 2, items: ['x4', 'x5'], children: [], line: 2 }],
      unclassified: { count: 4, items: ['x6', 'x7', 'x8', 'x9'] } };
    const P = await openCatalog({ data: catalogData(base(), { usage_month: { month: '2026-10', cost_cny: 1.5 } }), plugin: p, files: { '_archive/index-data.json': JSON.stringify(index), '索引.md': '- 咖啡\n- 旅行\n' } });
    await tick(5);
    P.$('.lb-arrange').onclick();
    // 最近导入：条数
    bar(P, 'recent', 'adjust').onclick(ev());
    const panel = () => P.$('.lbc-mp');
    assert.equal(panel().dataset.panel, 'recent'); assert.equal(bar(P, 'recent', 'adjust').getAttribute('aria-expanded'), 'true');
    assert.ok(mod(P, 'recent').contains(panel()), '在模块里展开（不弹窗）');
    const cnt = panel().querySelector('[data-k="count"]'); cnt.value = '2'; cnt.onchange();
    assert.equal(P.$$('.lbc-mod-recent .lbc-rec li').length, 2, '最近导入只列 2 条');
    // 字号 / 字体（这一块自己的）
    const size = panel().querySelector('[data-k="size"]'); size.value = '130'; size.onchange();
    assert.equal(mod(P, 'recent').style.getPropertyValue('--lbc-m-k'), '1.3');
    const font = panel().querySelector('[data-k="font"]'); font.value = font.querySelectorAll('option')[2].value; font.onchange();
    assert.match(mod(P, 'recent').style.getPropertyValue('--f-sans'), /^"Noto Serif SC",.*var\(--lb-font-body-base\)$/);
    // 标题文字：输入即改，存走 setCatalogPrefs（插件写完回读核对）
    bar(P, 'title', 'adjust').onclick(ev());
    assert.equal(panel().dataset.panel, 'title', '一次只开一个');
    const t = panel().querySelector('[data-k="title"]'); t.value = 'MY ARCHIVE'; t.fire('input');
    assert.equal(P.$('.lbc-title-text').textContent, 'MY ARCHIVE', '标题当场换');
    // 后台 Dataview 重跑（同步 / 补处理）：编排态、展开的调整、输入框都不重建
    await P.A.rerun(); await tick(5);
    assert.ok(P.$('.lbc-wrap').classList.contains('is-arranging') && P.$('.lbc-mp [data-k="title"]') === t && t.value === 'MY ARCHIVE', '重跑后输入框还是同一个、字还在');
    await tick(450);
    assert.deepEqual(p.calls.filter(c => c[0] === 'prefs').at(-1), ['prefs', 'MY ARCHIVE']);
    assert.equal(p.settings.catalogTitle, 'MY ARCHIVE');
    assert.equal(P.$('.lbc-arrange-tray .lbc-at-save').textContent, '已保存');
    // 收藏墙：列数 / 密度
    bar(P, 'wall', 'adjust').onclick(ev());
    const c3 = panel().querySelector('[data-k="cols"]'); c3.value = '3'; c3.onchange();
    const den = panel().querySelector('[data-k="density"]'); den.value = 's'; den.onchange();
    await tick(450);
    assert.equal(p.settings.catalogColumns, 3, '列数还是 catalogColumns（和 Ctrl + 滚轮同一个）');
    assert.equal(L(p).modules.find(m => m.id === 'wall').options.density, 's');
    // Token：显示今天 + 每日上限（budget.dailyYuan，和设置页同一个）
    p.runPy = async () => ({ json: { ok: true, budget: { spent_today: 0.42, daily_yuan: 3 } } });
    bar(P, 'token', 'adjust').onclick(ev());
    const per = panel().querySelector('[data-k="period"]'); per.value = 'day'; per.onchange();
    await tick(10);
    assert.equal(P.$('.lbc-mod-token .lbc-tk-big').textContent, '¥ 0.42', '今天的花费（插件 usage）');
    const bud = panel().querySelector('[data-k="budget"]'); bud.value = '5'; bud.onchange();
    assert.equal(p.settings.budget.dailyYuan, 5);
    bud.value = '-1'; bud.onchange();
    assert.equal(p.settings.budget.dailyYuan, 5, '负数不收'); assert.match(panel().querySelector('.lbc-mp-note').textContent, /还没改/);
    // 概览：只留两个数、不要柱图
    bar(P, 'overview', 'adjust').onclick(ev());
    P.$('.lbc-mod-overview .lbc-fold-sum').onclick?.();
    for (const k of ['week', 'cats', 'bars']) { const ck = panel().querySelector(`[data-k="${k}"]`); ck.checked = false; ck.onchange(); }
    assert.deepEqual(P.$$('.lbc-mod-overview .lbc-fig-l').map(x => x.textContent), ['全部收藏', '已收藏']);
    assert.equal(P.$$('.lbc-mod-overview .lbc-bar').length, 0);
    // 筛选：不显示 Tag
    bar(P, 'filters', 'adjust').onclick(ev());
    const tag = panel().querySelector('[data-k="tag"]'); tag.checked = false; tag.onchange();
    assert.ok(mod(P, 'filters').classList.contains('lbc-f-no-tag'));
    // 分类：改名 / 往后 / 加一个（都走插件 indexEdit → 写 索引.md）
    bar(P, 'cats', 'adjust').onclick(ev());
    const row = panel().querySelector('.lbc-mp-cat[data-path="咖啡"]');
    const nm = row.querySelector('[data-k="name"]'); nm.value = '咖啡豆'; nm.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} });
    await tick(10);
    assert.deepEqual(p.calls.filter(c => c[0] === 'indexEdit').at(-1).slice(0, 3), ['indexEdit', 'rename', '咖啡']);
    panel().querySelector('.lbc-mp-cat[data-path="咖啡"] [data-act="cat-down"]').onclick(); await tick(10);
    const mv = p.calls.filter(c => c[0] === 'indexEdit').at(-1);
    assert.deepEqual(mv.slice(0, 3), ['indexEdit', 'move', '咖啡']); assert.equal(mv[3].to, ''); assert.equal(mv[3].before, '', '往后 = 插到「旅行」后面（放最后）');
    const nw = panel().querySelector('[data-k="new"]'); nw.value = '摄影'; panel().querySelector('[data-act="cat-add"]').onclick(); await tick(10);
    assert.deepEqual(p.calls.filter(c => c[0] === 'indexEdit').at(-1), ['indexEdit', 'add', '', { name: '摄影' }]);
    // 隐藏一个分类（hiddenCats）
    const show = panel().querySelector('.lbc-mp-cat[data-path="旅行"] [data-k="show"]'); show.checked = false; show.onchange();
    assert.deepEqual(p.settings.hiddenCats, ['旅行']); assert.equal(P.cat('旅行'), undefined, '分类行里不显示');
    // 同步：嵌插件那一个同步时间编辑器（不另做一个）
    bar(P, 'sync', 'adjust').onclick(ev());
    assert.ok(panel().querySelector('.lb-sched'));
    assert.deepEqual(p.calls.filter(c => c[0] === 'sched-render').at(-1), ['sched-render', true]);
    bar(P, 'sync', 'adjust').onclick(ev());
    assert.equal(P.$('.lbc-mp'), null, '再点「调整」收起');
    assert.ok(p.calls.some(c => c[0] === 'sched-destroy'));
    // 往返：新开一页，模块设置都还在
    await tick(450);
    const Q = await openCatalog({ data: catalogData(base()), plugin: p, files: { '_archive/index-data.json': JSON.stringify(index) } });
    await tick(5);
    assert.equal(Q.$$('.lbc-mod-recent .lbc-rec li').length, 2);
    assert.equal(mod(Q, 'recent').style.getPropertyValue('--lbc-m-k'), '1.3');
    assert.ok(mod(Q, 'filters').classList.contains('lbc-f-no-tag'));
    assert.equal(Q.$('.lbc-title-text').textContent, 'MY ARCHIVE');
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
    const host = P.$('.lbc-wrap').parentNode.style;   // LB.applyTheme 写在本页 host 上（共享令牌那条线的接口）
    assert.equal(host.getPropertyValue('--lb-font-title'), '"Georgia",var(--lb-font-title-base)', '标题字 → 共享令牌 --lb-font-title（名字在前、默认栈兜底）');
    const gp = sel('gap'); gp.value = '17'; gp.onchange();
    assert.equal(P.$('.lbc-wrap').style.getPropertyValue('--lbc-sp'), '0.71'); assert.equal(host.getPropertyValue('--lb-gap'), '17px');
    const sc = sel('scale'); sc.value = '1.1'; sc.onchange();
    assert.equal(host.getPropertyValue('--lb-scale'), '1.1');
    await tick(450);
    assert.deepEqual(L(p).theme, { titleFont: 'Georgia', bodyFont: '', numberFont: '', scale: 1.1, gap: 17 }, 'catalogLayout.theme');
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
    // 1022 / 1026 的旧布局
    const old = mkPlugin({ settings: { catalogLayout: { side: [{ id: 'overview' }, { id: 'sync', hidden: true }, 'bogus', { id: 'recent' }], top: [{ id: 'title' }, { id: 'filters', hidden: true }, { id: 'cats' }], sideRight: true, sideW: 'l', gap: 's', density: 's' } } });
    const O = await openCatalog({ data: catalogData(base()), plugin: old });
    assert.deepEqual(topRows(O).map(r => r[0][0]), ['title', 'filters', 'cats']);
    assert.ok(mod(O, 'filters').classList.contains('is-off'));
    assert.deepEqual(boardCols(O), [['wall'], ['overview', 'token', 'recent']], '边栏放右边、同步隐藏、Token 补在同步后面');
    assert.equal(O.$('.lbc-board').style.getPropertyValue('--lbc-board-cols'), 'minmax(0,7fr) minmax(0,5fr)', '宽侧栏 = 5/12');
    assert.equal(O.$('.lbc-wrap').style.getPropertyValue('--lbc-sp'), '0.71', '紧间距 → 卡片间距 17');
  }

  // ── ⑧ 手机 / 插件没开：没有编排 ──
  {
    const M = await openCatalog({ data: catalogData(base()), isMobile: true });
    assert.equal(M.$('.lb-arrange'), null);
    assert.deepEqual(topRows(M), [[['title']], [['cats']], [['filters']]], '手机照默认摆');
    const N = await openCatalog({ data: catalogData(base()), plugin: null });
    assert.equal(N.$('.lb-arrange'), null, '插件没开：只读，不出编排');
    assert.deepEqual(boardCols(N), [['recent', 'sync', 'token', 'overview'], ['wall']]);
  }
  console.log('PASS catalog arrange 1027: default = previous layout, nothing written on open · 8 modules with ⠿ / 调整 / × · drag anywhere (beside the title, title into the side column), keyboard moves · remove / ＋ re-add in place (filters keeps search) · edge resize snaps to 12ths, min 2 · inline settings (recent rows, title via setCatalogPrefs, wall columns / density, token period + daily budget, overview metrics, filters shown, categories rename / reorder / add via indexEdit, hidden cats, embedded sync editor, font / size) · Aa theme → shared tokens · 400ms autosave with 保存中 / 已保存, failure keeps changes + retry · round trip + legacy layout migration · mobile / no plugin read-only');
})().catch(e => { console.error(e); process.exit(1); });

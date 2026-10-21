// 1021 目录页改版第 3 段（Collection+ 设计交接包 DESIGN-SPEC §4、§7）：左侧边栏，假 DOM 上真跑整段目录页脚本。
//   ① 三个模块 RECENT / SYNC / OVERVIEW：小标题（英文 + 中文小字 + 横线 + 箭头）；RECENT 最新 6 篇（今天 HH:MM、否则 M/D），点行打开；
//      OVERVIEW 默认折叠、摘要一行，点开 4 个大数 + 近 14 天柱子（今天加粗）
//   ② 折叠：点小标题 → 一行摘要；点摘要 → 展开；状态存 LB.state（返回后还在），不用 localStorage
//   ③ SYNC：上次 / 下次（插件 getSyncSchedule）、频率、进度 + 「还有 x 小时 x 分」、今日新增、Token 费用（没数据「—」+ 悬停「还没有用量记录」，
//      有 usage_month.cost_cny 显示「约 ¥x.xx」）；齿轮 → 插件 openSetupPage('schedule')（= 设置「收藏与同步」s-xhs 段）
//   ④ 同步状态文件变了：SYNC 跟着重画「同步中 x/y」真实进度、失败显示原因并能点开问题列表；不重建收藏墙、搜索框里的字和焦点还在
//   ⑤ 没插件：SYNC 下次「—」+ 一句说明，不报错；手机 / 星标页不出边栏；收起边栏后整列不显示
'use strict';
const assert = require('node:assert/strict');
const { tick, item, catalogData, openCatalog } = require('./_fake_l1.cjs');

const p2 = n => String(n).padStart(2, '0');
const ymdOf = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const now = new Date();
const today = ymdOf(now);
const daysAgo = k => { const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - k, 9, 30); return d; };
const iso = d => d.toISOString();
// 今天 3 篇（时间不同）、昨天 1 篇、5 天前 2 篇、20 天前 2 篇
const todayAt = (h, m) => { const d = new Date(now); d.setHours(h, m, 0, 0); return d; };
const base = () => [
  item('t1', '今天第一篇', { ts: iso(todayAt(0, 5)), date: today, cats: ['吃的'], starred: true }),
  item('t2', '今天第二篇', { ts: iso(todayAt(0, 7)), date: today }),
  item('t3', '今天第三篇·标题很长很长很长很长很长很长很长很长', { ts: iso(todayAt(0, 9)), date: today, cats: [] }),
  item('y1', '昨天那篇', { ts: iso(daysAgo(1)), date: ymdOf(daysAgo(1)) }),
  item('f1', '五天前 A', { ts: iso(daysAgo(5)), date: ymdOf(daysAgo(5)), starred: true }),
  item('f2', '五天前 B', { ts: iso(daysAgo(5)), date: ymdOf(daysAgo(5)) }),
  item('o1', '很久以前 A', { ts: iso(daysAgo(20)), date: ymdOf(daysAgo(20)) }),
  item('o2', '很久以前 B', { ts: iso(daysAgo(21)), date: ymdOf(daysAgo(21)) }),
];
const state = () => JSON.parse(globalThis.__lbState['lb:catalog']);
const lastOk = new Date(Date.now() - 2 * 3600e3);
const nextRun = new Date(Date.now() + 4 * 3600e3 + 31 * 60e3);
const localIso = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
const sched = () => ({ task: 'LinkBrainNightly', enabled: true, freq: 'daily', next_run: localIso(nextRun), summary: `每天 04:00 · 每 6 小时一次 · 下次 ${localIso(nextRun).slice(5, 16)}`, rules: [] });
const syncFile = more => JSON.stringify({ state: 'ready', updated_at: new Date().toISOString(), last_success: lastOk.toISOString(), ...more });
const mkPlugin = (more = {}) => {
  const calls = [];
  return { calls, settings: { hiddenCats: [] }, scheduleCalls: 0,
    async getSyncSchedule() { this.scheduleCalls++; return sched(); },
    openSetupPage(sec) { calls.push(['setup', sec]); },
    async openProblems() { calls.push(['problems']); },
    ...more };
};
const txt = el => (el ? el.textContent : null);

(async () => {
  // ── ① 三个模块 + RECENT / OVERVIEW ──
  {
    const plugin = mkPlugin();
    const P = await openCatalog({ data: catalogData(base(), { usage_month: { month: today.slice(0, 7), cost_cny: 3.7249 } }), plugin, files: { '_archive/sync-status.json': syncFile() } });
    await tick(5);
    const side = P.$('.lbc-side');
    assert.equal(side.hidden, false); assert.ok(P.$('.lbc-board').classList.contains('has-side'));
    assert.deepEqual(P.$$('.lbc-mod').map(m => m.dataset.mod), ['recent', 'sync', 'overview'], '顺序：RECENT · SYNC · OVERVIEW');
    assert.deepEqual(P.$$('.lbc-lab-en').map(txt), ['RECENT', 'SYNC', 'OVERVIEW']);
    assert.deepEqual(P.$$('.lbc-lab small').map(txt), ['最近导入', '同步与用量', '概览']);
    assert.equal(P.$$('.lbc-lab-line').length, 3); assert.equal(P.$$('.lbc-chev').length, 3);
    // RECENT：最新 6 篇，按 ts 倒序；今天 HH:MM，否则 M/D；分类小字
    const rows = P.$$('.lbc-rec li');
    assert.deepEqual(rows.map(li => li.dataset.id), ['t3', 't2', 't1', 'y1', 'f1', 'f2']);
    assert.deepEqual(rows.slice(0, 3).map(li => txt(li.querySelector('time'))), ['00:09', '00:07', '00:05']);
    const y = daysAgo(1); assert.equal(txt(rows[3].querySelector('time')), `${y.getMonth() + 1}/${y.getDate()}`);
    assert.equal(txt(rows[0].querySelector('.lbc-rec-c')), '未归类'); assert.equal(txt(rows[2].querySelector('.lbc-rec-c')), '吃的');
    // 点行打开（同一窗格）；Ctrl 开新标签；多选模式下也是打开
    rows[1].onclick({ ctrlKey: false });
    assert.deepEqual(P.app.workspace.opened.at(-1), ['Web/t2.md', '', false]);
    rows[1].onclick({ ctrlKey: true });
    assert.deepEqual(P.app.workspace.opened.at(-1), ['Web/t2.md', '', true]);
    // OVERVIEW 默认折叠：只有一行摘要
    const ov = P.$('.lbc-mod-overview');
    assert.ok(ov.classList.contains('is-folded')); assert.equal(ov.querySelector('.lbc-mod-body').hidden, true);
    assert.equal(txt(ov.querySelector('.lbc-fold-sum')), '8 篇 · 近 7 天 +6 · ★ 2');
    ov.querySelector('.lbc-fold-sum').onclick();
    assert.equal(ov.classList.contains('is-folded'), false);
    assert.deepEqual(ov.querySelectorAll('.lbc-fig-n').map(txt), ['8', '6', '2', '2'], '全部 / 近 7 天 / 已收藏 / 在用分类（未归类不算）');
    assert.deepEqual(ov.querySelectorAll('.lbc-fig-l').map(txt), ['全部收藏', '近 7 天新增', '已收藏', '在用分类']);
    const bars = ov.querySelectorAll('.lbc-bar');
    assert.equal(bars.length, 14);
    assert.ok(bars[13].classList.contains('is-today')); assert.equal(txt(bars[13].querySelector('span')), '3', '今天那根标数');
    assert.equal(txt(bars[12].querySelector('span')), '1'); assert.equal(txt(bars[8].querySelector('span')), '2');
    assert.ok(bars[0].classList.contains('is-zero'));
    assert.equal(txt(ov.querySelectorAll('.lbc-days span')[13]), '今');
    assert.equal(state().sideFold.overview, false, '折叠状态进 LB.state');
    // SYNC：上次 / 下次 / 频率 / 进度 / 今日新增 / Token 费用
    const sy = P.$('.lbc-mod-sync');
    assert.equal(plugin.scheduleCalls, 1, '同步计划读一次');
    const big = sy.querySelectorAll('.lbc-sy-big').map(txt);
    assert.equal(big[0], `今天 ${p2(lastOk.getHours())}:${p2(lastOk.getMinutes())}`.replace(/^今天/, lastOk.getDate() === now.getDate() ? '今天' : `${lastOk.getMonth() + 1}/${lastOk.getDate()}`));
    assert.match(big[1], /(今天|\d+\/\d+) \d\d:\d\d/);
    assert.equal(txt(sy.querySelector('.lbc-sy-freq')), '每天 04:00 · 每 6 小时一次', '频率 = summary 去掉「下次」');
    assert.match(txt(sy.querySelectorAll('.lbc-sy-cap span')[1]), /^还有 4 小时 3[01] 分$/);
    const w = parseFloat(sy.querySelector('.lbc-sy-bar i').style.width); assert.ok(w > 25 && w < 35, '进度 = 上次到下次过了多少 ' + w);
    const rowsSy = sy.querySelectorAll('.lbc-sy-row').map(r => [txt(r.querySelector('span')), txt(r.querySelector('b'))]);
    assert.deepEqual(rowsSy, [['今日新增', '3 篇'], ['Token 费用 · 本月', '约 ¥3.72']]);
    assert.match(txt(sy.querySelector('.lbc-fold-sum')), /^下次 (今天|\d+\/\d+) \d\d:\d\d · 本月 约 ¥3\.72$/);
    // 齿轮：打开设置「收藏与同步」（插件 openSetupPage('schedule') → s-xhs 段），不折叠模块
    sy.querySelector('.lbc-gear').onclick({ stopPropagation() {} });
    await tick(5);
    assert.deepEqual(plugin.calls.at(-1), ['setup', 'schedule']);
    assert.equal(sy.classList.contains('is-folded'), false);
    // 折叠 SYNC：只剩摘要；返回后还是折叠
    sy.querySelector('.lbc-lab').onclick();
    assert.ok(sy.classList.contains('is-folded')); assert.equal(sy.querySelector('.lbc-fold-sum').hidden, false);
    assert.deepEqual(state().sideFold, { recent: false, sync: true, overview: false });
    const Q = await openCatalog({ data: catalogData(base()), plugin: mkPlugin(), keepState: true });
    assert.ok(Q.$('.lbc-mod-sync').classList.contains('is-folded') && !Q.$('.lbc-mod-overview').classList.contains('is-folded'), '返回后折叠状态还在');
    // 没有用量记录：「—」+ 悬停说明（不显示 0）
    Q.$('.lbc-mod-sync .lbc-fold-sum').onclick(); await tick(5);
    const tot = Q.$('.lbc-mod-sync .lbc-sy-row.is-tot b');
    assert.equal(txt(tot), '—'); assert.equal(tot.title, '还没有用量记录');
    // 键盘：小标题上 Enter 折叠
    const lab = Q.$('.lbc-mod-recent .lbc-lab');
    lab.onkeydown({ key: 'Enter', target: lab, currentTarget: lab, preventDefault() {} });
    assert.ok(Q.$('.lbc-mod-recent').classList.contains('is-folded'));
    assert.match(txt(Q.$('.lbc-mod-recent .lbc-fold-sum')), /^最新 00:09 · 今天第三篇/);
  }

  // ── ④ 同步状态变化：只重画 SYNC；收藏墙不重建、输入不丢 ──
  {
    const plugin = mkPlugin();
    const P = await openCatalog({ data: catalogData(base()), plugin, files: { '_archive/sync-status.json': syncFile() } });
    await tick(5);
    const s = P.search(); s.value = '还没回车的字'; s.focus?.();
    const cardsBefore = P.cards();
    const wallBefore = P.$('.lbc-grid').firstChild;
    P.V.set('_archive/sync-status.json', syncFile({ state: 'running', done: 3, total: 40, progress: '3/40' }));
    await tick(10);
    const sy = P.$('.lbc-mod-sync');
    assert.equal(sy.dataset.state, 'running');
    assert.equal(txt(sy.querySelector('.lbc-sy-now .lbc-sy-big')), '3/40');
    assert.equal(txt(sy.querySelector('.lbc-sy-now .lbc-sy-k')), '同步中');
    assert.equal(sy.querySelector('.lbc-sy-bar i').style.width, '7.5%', '真实进度 done/total');
    assert.equal(sy.querySelector('.lbc-sy-freq'), null, '同步中不显示倒计时 / 频率');
    assert.equal(P.search().value, '还没回车的字', '输入框里的字还在');
    assert.ok(P.cards().every((c, i) => c === cardsBefore[i]) && P.$('.lbc-grid').firstChild === wallBefore, '收藏墙没重建');
    // 折叠时摘要也跟着变
    sy.querySelector('.lbc-lab').onclick();
    assert.match(txt(sy.querySelector('.lbc-fold-sum')), /^同步中 3\/40 · 本月 —$/);
    sy.querySelector('.lbc-fold-sum').onclick();
    // 失败 / 阻塞：显示原因，点开问题列表
    P.V.set('_archive/sync-status.json', syncFile({ state: 'blocked', code: 'xhs.captcha', label: '撞到验证码', detail: '要你在小红书里过一下验证' }));
    await tick(10);
    const al = sy.querySelector('.lbc-sy-alert');
    assert.ok(al && !al.hidden); assert.equal(txt(al), '撞到验证码：要你在小红书里过一下验证 · 点开看问题列表');
    assert.equal(sy.dataset.state, 'stopped');
    al.onclick(); await tick(5);
    assert.deepEqual(plugin.calls.at(-1), ['problems']);
    // running 但只有 live（没有 done / total）：用收藏已入库 a/b
    P.V.set('_archive/sync-status.json', syncFile({ state: 'running', live: { archived: 120, favorites_total: 300 } }));
    await tick(10);
    assert.equal(txt(sy.querySelector('.lbc-sy-now .lbc-sy-big')), '120/300');
    // 数据变了（refresh）：RECENT 跟着换，不整页重建
    const wrapBefore = P.$('.lbc-wrap');
    P.V.set('_archive/catalog-data.json', JSON.stringify(catalogData([...base(), item('n1', '刚进来的', { ts: new Date().toISOString(), date: today })])));
    await P.A.rerun(); await tick(10);
    assert.equal(P.$('.lbc-wrap'), wrapBefore);
    assert.equal(P.$('.lbc-rec li').dataset.id, 'n1', 'RECENT 换成新数据');
  }

  // ── ⑤ 没插件 / 手机 / 星标页 / 收起 ──
  {
    const P = await openCatalog({ data: catalogData(base()), plugin: null, files: { '_archive/sync-status.json': syncFile() } });
    await tick(5);
    const sy = P.$('.lbc-mod-sync');
    assert.ok(sy, '没插件也出 SYNC');
    assert.equal(sy.querySelectorAll('.lbc-sy-big').map(txt)[1], '—');
    assert.match(txt(sy.querySelector('.lbc-sy-note')), /插件没开/);
    assert.match(txt(sy.querySelector('.lbc-fold-sum')), /^下次 — · 本月 —$/);
    assert.deepEqual(P.A.alerts || [], []);
    // 计划读失败：如实一句
    const bad = mkPlugin({ async getSyncSchedule() { throw new Error('后台没返回同步计划'); } });
    const B = await openCatalog({ data: catalogData(base()), plugin: bad });
    await tick(5);
    assert.equal(txt(B.$('.lbc-mod-sync .lbc-sy-note')), '读不到同步计划：后台没返回同步计划');
    // 手机：没有边栏
    const M = await openCatalog({ data: catalogData(base()), isMobile: true });
    assert.equal(M.$('.lbc-side').hidden, true); assert.equal(M.$('.lbc-mod'), null);
    assert.equal(M.$('.lbc-board').classList.contains('has-side'), false);
    // 星标页：不出
    const S = await openCatalog({ data: catalogData(base()), plugin: mkPlugin(), starred: true });
    assert.equal(S.$('.lbc-mod'), null);
    // 收起：整列不显示（class），返回后还收着；展开时重画
    const C = await openCatalog({ data: catalogData(base()), plugin: mkPlugin() });
    C.$('.lbc-sidetoggle').onclick();
    assert.ok(C.$('.lbc-wrap').classList.contains('is-side-collapsed'));
    C.$('.lbc-sidetoggle').onclick();
    assert.equal(C.$('.lbc-wrap').classList.contains('is-side-collapsed'), false);
    // ResizeObserver：窄于 760（按页面宽）加 is-side-narrow；吸顶变量写到 .lbc-wrap 上
    const wrap = C.$('.lbc-wrap'); const top = C.$('.lbc-top');
    top.offsetHeight = 240; wrap.clientWidth = 700;
    const sc = wrap.closest('.markdown-preview-view'); if (sc) sc.clientHeight = 900;
    C.A.resize.trigger(700, 900); await tick(20);
    assert.ok(wrap.classList.contains('is-side-narrow'), '窄于 760 不出边栏');
    wrap.clientWidth = 1400; C.A.resize.trigger(1400, 900); await tick(20);
    assert.equal(wrap.classList.contains('is-side-narrow'), false);
    assert.equal(wrap.style.getPropertyValue('--lbc-top-h'), '240px');
    if (sc) assert.equal(wrap.style.getPropertyValue('--lbc-pane-h'), '900px');
  }
  console.log('PASS catalog 1021 side: RECENT (latest 6 by ts, HH:MM today else M/D, click opens even in select mode) · SYNC (last / next from getSyncSchedule, freq, time progress + 还有 x 小时 x 分, 今日新增, Token — / 约 ¥, gear → openSetupPage(schedule), running x/y real progress, blocked reason → problems, redraw without rebuilding the wall or losing input) · OVERVIEW (folded by default, 4 figures + 14-day bars) · fold state in LB.state · no plugin / schedule error honest · no side on mobile / starred · narrow < 760 + sticky vars');
})().catch(e => { console.error(e); process.exit(1); });

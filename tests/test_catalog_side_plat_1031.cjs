// 1031 她：目录页左侧栏分平台看（小红书 / B 站）——假 DOM 上真跑整段目录页脚本。
//   ① 只有一个平台的库：SYNC / OVERVIEW 小标题行不出切换，Token 照常
//   ② 两个平台：SYNC、OVERVIEW 标题行各一个「小红书 / B 站」（同一个状态，存 LB.state，返回后还在），默认小红书
//   ③ 切到 B 站：SYNC 读 _archive/bilibili-sync/last-sync.json——上次同步、这次新下 / 失败、「手动同步 · 不定时」、「去同步 →」（openBiliSync），
//      没有「下次同步」；OVERVIEW 只数 B 站的；Token 整块藏起来（编排时照常显示）
//   ④ last-sync.json 变了（同步中 n/m → 进程没了 = 停在第几条、为什么）只重画 SYNC；没插件时手机口径不报错
'use strict';
const assert = require('node:assert/strict');
const { tick, item, catalogData, openCatalog } = require('./_fake_l1.cjs');

const p2 = n => String(n).padStart(2, '0');
const ymdOf = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const now = new Date();
const today = ymdOf(now);
const ago = k => new Date(now.getFullYear(), now.getMonth(), now.getDate() - k, 9, 30);
const BL = '_archive/bilibili-sync/last-sync.json';
const xhs = () => [
  item('xhs-a', '小红书一', { ts: ago(0).toISOString(), date: today, starred: true }),
  item('xhs-b', '小红书二', { ts: ago(1).toISOString(), date: ymdOf(ago(1)) }),
  item('xhs-c', '小红书三', { ts: ago(20).toISOString(), date: ymdOf(ago(20)) }),
];
const bili = () => [
  item('bili-BV1aa', 'B站一', { source: 'bilibili', ts: ago(0).toISOString(), date: today, cats: ['吃的'] }),
  item('bili-BV1bb', 'B站二', { source: 'bilibili', ts: ago(3).toISOString(), date: ymdOf(ago(3)), starred: true }),
];
const finished = new Date(now.getTime() - 3600e3);
const lastDone = () => JSON.stringify({ state: 'done', started_at: new Date(finished.getTime() - 600e3).toISOString(), finished_at: finished.toISOString(),
  counts: { downloaded: 3, failed: 1, multi_p: 2, hit: 40 }, ok: false, code: 'SYNC_FAILED', message: '同步完：新下 3 条' });
const mkPlugin = (more = {}) => {
  const calls = [];
  return { calls, settings: { hiddenCats: [] }, running: null,
    async getSyncSchedule() { return { enabled: true, next_run: new Date(now.getTime() + 3 * 3600e3).toISOString(), summary: '每天 18:00' }; },
    openSetupPage(sec) { calls.push(['setup', sec]); }, openBiliSync() { calls.push(['bili']); },
    async openSyncLog() {}, async openProblems() {}, ...more };
};
const txt = el => (el ? el.textContent : null);
const state = () => JSON.parse(globalThis.__lbState['lb:catalog']);
const sw = (P, mod) => P.$(`.lbc-mod-${mod} .lbc-lab .lbc-plat-sw`);

(async () => {
  // ── ① 只有小红书：不出切换 ──
  {
    const P = await openCatalog({ data: catalogData(xhs(), { usage_month: { month: today.slice(0, 7), cost_cny: 1.5 } }), plugin: mkPlugin() });
    await tick(5);
    assert.equal(sw(P, 'sync').hidden, true, '一个平台：SYNC 不出切换');
    assert.equal(sw(P, 'overview').hidden, true, '一个平台：OVERVIEW 不出切换');
    assert.equal(P.$('.lbc-mod-token').classList.contains('is-plat-off'), false);
    assert.equal(txt(P.$('.lbc-mod-overview .lbc-fold-sum')), '3 篇 · 近 7 天 +2 · ★ 1');
  }

  // ── ②③ 两个平台 ──
  {
    const plugin = mkPlugin();
    const P = await openCatalog({ data: catalogData([...xhs(), ...bili()], { usage_month: { month: today.slice(0, 7), cost_cny: 1.5 } }), plugin, files: { [BL]: lastDone() } });
    await tick(5);
    for (const mod of ['sync', 'overview']) {
      const s = sw(P, mod);
      assert.equal(s.hidden, false, mod + '：两个平台出切换');
      assert.deepEqual(s.querySelectorAll('button').map(b => b.textContent + (b.classList.contains('is-on') ? '*' : '')), ['小红书*', 'B 站'], mod + '：默认小红书');
      assert.ok(s.parentNode.classList.contains('lbc-lab') && s.nextSibling.classList.contains('lbc-chev'), mod + '：在小标题行、箭头左边');
    }
    // 小红书这一面：和原来一样（下次同步），概览只数小红书
    const sy = P.$('.lbc-mod-sync');
    assert.ok(sy.querySelector('.lbc-sy-next'), '小红书：有下次同步');
    assert.equal(txt(P.$('.lbc-mod-overview .lbc-fold-sum')), '3 篇 · 近 7 天 +2 · ★ 1', '概览只数小红书的 3 篇');
    assert.equal(txt(sy.querySelector('.lbc-sy-row b')), '1 篇', '今日新增只数小红书');
    // 点切换不折叠模块
    const before = sy.classList.contains('is-folded');
    const toB = sw(P, 'sync').querySelector('[data-plat="bili"]');
    toB.onclick({ stopPropagation() {} }); await tick(5);
    assert.equal(sy.classList.contains('is-folded'), before, '点切换不折叠');
    // 两处切换一起变；存进 LB.state
    for (const mod of ['sync', 'overview']) assert.deepEqual(sw(P, mod).querySelectorAll('button.is-on').map(txt), ['B 站'], mod + '：跟着变');
    assert.equal(state().sidePlat, 'bili');
    // B 站 SYNC：上次同步 / 这次新下 / 手动同步 / 去同步；没有下次同步
    assert.equal(sy.querySelector('.lbc-sy-next .lbc-sy-k').textContent, '这次新下');
    assert.equal(txt(sy.querySelector('.lbc-sy-next .lbc-sy-big')), '3 条');
    assert.equal(txt(sy.querySelector('.lbc-sy-last .lbc-sy-k')), '上次同步');
    assert.ok(!/下次同步/.test(txt(sy.querySelector('.lbc-mod-body'))), 'B 站不显示下次同步');
    assert.match(txt(sy.querySelector('.lbc-sy-freq')), /^手动同步 · 不定时去同步 →$/);
    assert.equal(sy.querySelector('.lbc-sy-bar'), null, '做完了：没有进度条');
    assert.equal(sy.querySelector('.lbc-sy-alert'), null, '有失败的条目但整趟做完了：不亮红框');
    assert.deepEqual(sy.querySelectorAll('.lbc-sy-row').map(r => r.querySelector('span').textContent + '=' + r.querySelector('b').textContent), ['失败=1 条', '多 P 待选=2 条', '今日新增=1 篇']);
    sy.querySelector('[data-act="bili-go"]').onclick({ stopPropagation() {} }); await tick(5);
    assert.deepEqual(plugin.calls.at(-1), ['bili'], '去同步 → 设置②切到 B 站');
    // 概览只数 B 站；Token 藏起来
    assert.equal(txt(P.$('.lbc-mod-overview .lbc-fold-sum')), '2 篇 · 近 7 天 +2 · ★ 1');
    assert.ok(P.$('.lbc-mod-token').classList.contains('is-plat-off'), 'B 站：Token 藏起来');
    // 折叠摘要
    sy.querySelector('.lbc-lab').onclick();
    assert.match(txt(sy.querySelector('.lbc-fold-sum')), /^上次 今天 \d\d:\d\d · 新下 3 条$/);
    sy.querySelector('.lbc-fold-sum').onclick();

    // ── ④ 同步中：插件在跑「下载 B 站收藏」→ n/m；进程没了 → 停在第几条、为什么 ──
    plugin.running = '下载 B 站收藏';
    P.V.set(BL, JSON.stringify({ state: 'running', started_at: new Date().toISOString(), counts: { downloaded: 2, failed: 0 }, progress: { done: 3, total: 12, at: new Date().toISOString() } }));
    await tick(400);
    assert.equal(sy.dataset.state, 'running');
    assert.equal(txt(sy.querySelector('.lbc-sy-now .lbc-sy-big')), '3/12');
    assert.equal(sy.querySelector('.lbc-sy-bar i').style.width, '25%');
    assert.deepEqual(sy.querySelector('.lbc-sy-cap').querySelectorAll('span').map(txt), ['25%', '第 3/12 条']);
    plugin.running = null;   // 点了「停止」：进程没了，文件还停在 running
    P.V.set(BL, JSON.stringify({ state: 'running', started_at: new Date().toISOString(), counts: { downloaded: 4, failed: 0 }, progress: { done: 5, total: 12, at: new Date().toISOString() } }));
    await tick(400);
    assert.equal(sy.dataset.state, 'stopped');
    const al = sy.querySelector('.lbc-sy-alert');
    assert.match(txt(al), /^停在第 5\/12 条：进程被结束了.*已经下好的都在，再同步只补没下的 · 点这里去同步$/);
    al.onclick({ stopPropagation() {} }); await tick(5);
    assert.deepEqual(plugin.calls.at(-1), ['bili']);
    // 后端自己停下（连着失败 / 磁盘满）：说它写的原因
    P.V.set(BL, JSON.stringify({ state: 'stopped', started_at: new Date().toISOString(), finished_at: new Date().toISOString(), stopped: '磁盘只剩 3.0 GB（阈值 5 GB），停在第 6 条', counts: { downloaded: 5, failed: 0 }, progress: { done: 6, total: 12 } }));
    await tick(400);
    assert.match(txt(sy.querySelector('.lbc-sy-alert')), /^停在第 6\/12 条：磁盘只剩/);

    // 编排时 Token 照常显示（.is-plat-off 只在不编排时藏）——这里只核 class，显示由 CSS 管
    // 返回后还是 B 站
    const Q = await openCatalog({ data: catalogData([...xhs(), ...bili()]), plugin: mkPlugin(), files: { [BL]: lastDone() }, keepState: true });
    await tick(5);
    assert.deepEqual(sw(Q, 'overview').querySelectorAll('button.is-on').map(txt), ['B 站'], '返回后还是 B 站');
    sw(Q, 'overview').querySelector('[data-plat="xhs"]').onclick({ stopPropagation() {} }); await tick(5);
    assert.ok(Q.$('.lbc-mod-sync .lbc-sy-next .lbc-sy-k').textContent === '下次同步', '切回小红书：下次同步回来');
    assert.equal(Q.$('.lbc-mod-token').classList.contains('is-plat-off'), false, '切回小红书：Token 回来');
  }

  // ── B 站有收藏但这台电脑没同步过：一句话，不报错；没插件也不报错 ──
  {
    const P = await openCatalog({ data: catalogData([...xhs(), ...bili()]), plugin: null });
    await tick(5);
    sw(P, 'sync').querySelector('[data-plat="bili"]').onclick({ stopPropagation() {} }); await tick(5);
    const sy = P.$('.lbc-mod-sync');
    assert.equal(sy.querySelector('[data-act="bili-go"]'), null, '没插件：没有去同步按钮');
    assert.ok(sy.querySelectorAll('.lbc-sy-note').some(n => /还没同步过 B 站收藏/.test(txt(n))));
    assert.ok(sy.querySelectorAll('.lbc-sy-note').some(n => /插件没开/.test(txt(n))));
  }
  console.log('PASS catalog side platform 1031: one platform = no switch · switch in SYNC + OVERVIEW title rows (one state, LB.state) · 小红书 side unchanged · B 站 SYNC = last / new / failed / 手动同步 / 去同步 (openBiliSync), no next run · running n/m → interrupted / stopped reason · OVERVIEW counts per platform · Token hidden on B 站 · no plugin ok');
})().catch(e => { console.error(e); process.exit(1); });

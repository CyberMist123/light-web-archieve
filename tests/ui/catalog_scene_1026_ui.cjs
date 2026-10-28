// 1026 她的录屏（场景 02 首页与编排）· Obsidian 外壳 · 真 Chromium。
//   ① 缩窄窗口（1400 / 1100 / 900 / 760 / 600 / 390，边栏开着）：分类一个都不被裁（放不下就换行）、搜索框 / 问收藏整个在视口里、没有横向滚动
//   ② 放大 / 长标题：大标题不超出页头、不压到「编排 / 管理」（录屏 03:05「超出框架」）
//   ③ 已收藏的星：白底小圆黑星（不是整块黑圆）；没收藏的平时看不见（visibility + opacity）
//   ④ 编排（1027 八个模块平级；1028 十六块、工具条指着才出来）：每块都有工具条、编排条在收藏墙上面；拖宽边栏、紧间距、紧凑密度后版面真的变
//   ⑤ 首页同步：上次 / 下次是可点的格子，下面「立即同步 · 查看同步记录」，没有设置齿轮
// 截图进 LWA_QA_DIR（catalog-1026-*.png）
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

function fixture() {
  const data = shell.makeCatalogData({ n: 60 });
  data.schema = 1;
  // 分类多一些（真库 13 个一级分类），看窄了会不会被裁
  data.cats_order = ['悉尼', '做饭', 'AI', '学习', '穿搭', '家居', '旅行', '猫狗萌物', '游戏', '职业', '其他技能', '影视', '工程', '人文'];
  data.items.forEach((it, i) => { it.cats = [data.cats_order[i % data.cats_order.length]]; it.ts = new Date(Date.now() - i * 3600e3).toISOString(); });
  const font = f => 'data:font/woff2;base64,' + fs.readFileSync(path.join(shell.ROOT, 'link_brain/assets/fonts', f)).toString('base64');
  const resources = {
    '_archive/fonts/Cinzel-latin-variable.woff2': font('Cinzel-latin-variable.woff2'),
    '_archive/fonts/CormorantGaramond-Italic-latin-variable.woff2': font('CormorantGaramond-Italic-latin-variable.woff2'),
  };
  const schedule = { task: 'LinkBrainNightly', enabled: true, freq: 'daily', next_run: new Date(Date.now() + 3 * 3600e3).toISOString().slice(0, 19), summary: '每天 18:00', rules: [] };
  const files = { '_archive/sync-status.json': JSON.stringify({ state: 'ready', updated_at: new Date().toISOString(), last_success: new Date(Date.now() - 3600e3).toISOString() }) };
  return { data, resources, schedule, files };
}
const PLUGIN = (schedule, settings = {}) => ({ settings: { hiddenCats: [], ...settings }, methods: { getSyncSchedule: { result: schedule } } });

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const { data, resources, schedule, files } = fixture();
  const shots = [];
  try {
    // ① 缩窄
    for (const width of [1400, 1100, 900, 760, 600, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      // 红线（CONVENTIONS §7.8）：LWA_REV=<改前提交> 跑同一段读改前的资产
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, files, plugin: PLUGIN(schedule), rev: process.env.LWA_REV || null });
      await page.evaluate(() => document.fonts.ready); await S.settle(120);
      const m = await page.evaluate(() => {
        const sc = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view');
        const view = sc.getBoundingClientRect(), cats = document.querySelector('.lbc-cats').getBoundingClientRect();
        const clipped = [...document.querySelectorAll('.lbc-cats .lbc-cat')].filter(b => { const r = b.getBoundingClientRect(); return r.right > cats.right + 1 || r.left < cats.left - 1 || r.right > view.right + 1; }).map(b => b.textContent);
        const inView = s => { const r = document.querySelector(s).getBoundingClientRect(); return r.width > 0 && r.left >= view.left - 1 && r.right <= view.right + 1; };
        return { h: sc.scrollWidth - sc.clientWidth, clipped, n: document.querySelectorAll('.lbc-cats .lbc-cat').length, search: inView('.lbc-searchbox'), ask: inView('.lbc-askbtn'), manage: inView('.lb-manage'),
          wrapCls: document.querySelector('.lbc-cats').className };
      });
      assert.ok(m.h <= 1, `${width}：没有横向滚动 ${m.h}`);
      assert.deepEqual(m.clipped, [], `${width}：分类没被裁 ${JSON.stringify(m)}`);
      assert.equal(m.n, 15, `${width}：全部 + 14 个分类都在`);
      assert.ok(m.search && m.ask && m.manage, `${width}：搜索 / 问收藏 / 管理都在视口里 ${JSON.stringify(m)}`);
      if ([1100, 390].includes(width)) shots.push(await S.screenshot(`catalog-1026-narrow-${width}`));
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    // ② 长标题 / 放大（窄页头 = 放大后的效果）：标题不出页头、不压「编排 / 管理」
    for (const width of [1400, 1000, 820]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, files, plugin: PLUGIN(schedule, { catalogTitle: 'MY LONG COLLECTION ARCHIVE' }) });
      await page.evaluate(() => document.fonts.ready); await S.settle(120);
      const r = await page.evaluate(() => {
        const R = s => document.querySelector(s).getBoundingClientRect();
        const t = R('.lbc-title'), head = R('.lbc-head'), tools = R('.lbc-tools');
        const overlap = !(t.right <= tools.left || t.top >= tools.bottom || t.bottom <= tools.top || t.left >= tools.right);
        return { t: [t.left, t.right], head: [head.left, head.right], overlap };
      });
      assert.ok(r.t[0] >= r.head[0] - 2 && r.t[1] <= r.head[1] + 2, `${width}：长标题在页头里 ${JSON.stringify(r)}`);
      assert.ok(!r.overlap, `${width}：标题不压「编排 / 管理」 ${JSON.stringify(r)}`);
      if (width === 820) shots.push(await S.screenshot('catalog-1026-longtitle-820'));
      await page.close();
    }
    // ③ ④ ⑤
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, files, plugin: PLUGIN(schedule) });
      await page.evaluate(() => document.fonts.ready); await S.settle(120);
      const star = await page.evaluate(() => {
        const on = document.querySelector('.lbc-card .lbc-star.is-on'), off = [...document.querySelectorAll('.lbc-card .lbc-star')].find(s => !s.classList.contains('is-on'));
        const cs = getComputedStyle(on), co = getComputedStyle(off);
        return { bg: cs.backgroundColor, color: cs.color, w: on.getBoundingClientRect().width, offVis: co.visibility, offOp: co.opacity };
      });
      assert.ok(!/^rgb\(34, 34, 34\)|^rgb\(20, 20, 20\)/.test(star.bg), `已收藏的星不是整块黑圆 ${JSON.stringify(star)}`);
      assert.match(star.color, /rgb\(20, 20, 20\)/); assert.equal(Math.round(star.w), 26);
      assert.deepEqual([star.offVis, star.offOp], ['hidden', '0'], '没收藏的平时看不见');
      // ⑤ 同步模块
      const sy = await page.evaluate(() => ({ gear: !!document.querySelector('.lbc-mod-sync .lbc-gear'), cells: [...document.querySelectorAll('.lbc-mod-sync button.lbc-sy-cell')].map(b => b.querySelector('.lbc-sy-k').textContent),
        acts: [...document.querySelectorAll('.lbc-mod-sync .lbc-sy-acts button')].map(b => b.textContent), edit: !!document.querySelector('.lbc-mod-sync button.lbc-sy-freq .lbc-sy-pen') }));
      assert.deepEqual(sy, { gear: false, cells: ['上次同步', '下次同步'], acts: [], edit: true }, '1027b：立即同步 / 查看同步记录藏了，频率那行能改时间');
      await page.click('.lbc-mod-sync .lbc-sy-next'); await S.settle(40);
      assert.deepEqual((await page.evaluate(() => window.calls.filter(c => c[0] === 'openSetupPage' || c[0] === 'openSyncTime').at(-1))).slice(0, 2), ['openSetupPage', 'schedule'], '下次同步 → 设置里那一个同步时间编辑');
      // ④ 编排（1027 起八个模块平级，细节见 catalog_arrange_ui）：每块都有操作条、托盘在收藏墙上面；拖宽边栏、卡片间距、收藏墙密度后版面真的变
      const w0 = await page.evaluate(() => document.querySelector('.lbc-side').getBoundingClientRect().width);
      await page.click('.lbc-tools .lb-arrange'); await S.settle(60);
      // 1028 她：「不像图 2 那么突兀」——十六块都有工具条，平时收着，指着 / 选中那块才出来
      const a = await page.evaluate(() => ({ bars: document.querySelectorAll('.lbc-mod-bar').length, shown: [...document.querySelectorAll('.lbc-mod-bar')].filter(b => getComputedStyle(b).display === 'flex').length,
        trayAbove: document.querySelector('.lbc-arrange-tray').getBoundingClientRect().bottom <= document.querySelector('.lbc-board').getBoundingClientRect().top + 1 }));
      assert.equal(a.bars, 16, '十六块都有工具条'); assert.equal(a.shown, 0, '平时不露工具条'); assert.ok(a.trayAbove, '编排条在收藏墙上面');
      await page.hover('.lbc-m-sync'); await S.settle(60);
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.lbc-m-sync .lbc-mod-bar')).display), 'flex', '指着的那块露出工具条');
      shots.push(await S.screenshot('catalog-1026-arrange'));
      await page.focus('.lbc-board > .lbc-col-edge'); for (let i = 0; i < 4; i++) await page.keyboard.press('ArrowRight'); await S.settle(120);   // 48 格：4 格 = 原来 12 格的 1 格
      const w1 = await page.evaluate(() => document.querySelector('.lbc-side').getBoundingClientRect().width);
      assert.ok(w1 > w0 + 60, `侧栏变宽 ${w0} → ${w1}`);
      const gapOf = () => page.evaluate(() => { const c = [...document.querySelectorAll('.lbc-grid-inner > .lbc-col')]; return c[1].getBoundingClientRect().left - c[0].getBoundingClientRect().right; });
      const gap0 = await gapOf();
      await page.click('.lbc-arrange-tray [data-act="style"]'); await page.selectOption('.lbc-arrange-tray [data-theme="gap"]', '17'); await S.settle(120);
      const gap1 = await gapOf();
      assert.ok(gap1 < gap0 - 4, `卡片间距变紧 ${gap0} → ${gap1}`);
      const n0 = await page.evaluate(() => document.querySelectorAll('.lbc-grid-inner > .lbc-col').length);
      await page.hover('.lbc-m-wall'); await page.click('.lbc-m-wall .lbc-mod-bar [data-act="adjust"]'); await page.selectOption('.lbc-mp [data-k="density"]', 's'); await S.settle(120);
      const n1 = await page.evaluate(() => document.querySelectorAll('.lbc-grid-inner > .lbc-col').length);
      assert.equal(n1, n0 + 1, `紧凑多一列 ${n0} → ${n1}`);
      shots.push(await S.screenshot('catalog-1026-arrange-options'));
      await page.click('.lbc-arrange-tray [data-act="done"]'); await S.settle(60);
      shots.push(await S.screenshot('catalog-1026-after-arrange'));
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS catalog_scene_1026_ui：1400–390 分类不裁 / 搜索问收藏可达 / 无横向滚动 · 长标题不出页头不压按钮 · 星标白底小圆 · 编排十六块工具条（指着才出）+ 编排条 + 侧栏宽度 / 间距 / 密度生效 · 同步可点格子 + 两个按钮。截图：\n  ' + shots.join('\n  '));
  } finally { await browser.close(); }
})().catch(e => { console.error('FAIL catalog_scene_1026_ui', e); process.exit(1); });

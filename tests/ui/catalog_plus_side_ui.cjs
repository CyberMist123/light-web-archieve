// 1021 目录页改版第 3 段（Collection+ DESIGN-SPEC §4、§7）：左侧边栏 · Obsidian 外壳 · 真 Chromium。
//   ① 宽 1400（阅读视图 × 浅 / 深、实时预览 × 浅）：边栏在收藏墙左边（约 4/12，间距 40），三个模块按序；小标题 Cinzel 11px、横线撑满
//   ② 吸顶：往下滚以后页头、边栏都不动（边栏贴在页头底下），只有收藏墙在动；页头上方不留缝（10-08 C1 口径不倒退）
//   ③ 边栏超高自己滚、没有滚动条、没到底底部渐隐（mask），到底去掉
//   ④ 收起边栏 → 收藏墙铺满、列数变多；展开回来
//   ⑤ 760 以下（按页面宽）、390 窄屏不出边栏
//   ⑥ 同步中：SYNC 显示真实进度 x/y，收藏墙不重建、滚动位置不动；没插件不报错
//   ⑦ 返回后滚动位置还在（重建页面后 scrollTop 恢复）
// 截图进 LWA_QA_DIR（catalog-side-*.png），和 _handoff/collection-plus-handoff/prototype/screens/ 01 / 04 / 05 / 07 对照
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

const p2 = n => String(n).padStart(2, '0');
const ymdOf = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const localIso = d => `${ymdOf(d)}T${p2(d.getHours())}:${p2(d.getMinutes())}:00`;
function fixture() {
  const data = shell.makeCatalogData({ n: 60 });
  const now = Date.now();
  // 近 14 天每天导入几篇（今天 5 篇），其余是很久以前
  data.items.forEach((it, i) => {
    const back = i < 5 ? 0 : i < 40 ? 1 + (i % 13) : 30 + i;
    const t = new Date(now - back * 864e5 - (i % 5) * 37 * 60e3);
    if (back === 0) t.setHours(Math.max(0, new Date(now).getHours() - 1), 10 + i * 7 % 50, 0, 0);
    it.ts = t.toISOString(); it.date = ymdOf(t);
    it.title = i % 4 === 0 ? `${it.title}：一个比较长的标题，看看单行省略号` : it.title;
  });
  data.usage_month = { month: ymdOf(new Date()).slice(0, 7), cost_cny: 3.72 };
  const font = f => 'data:font/woff2;base64,' + fs.readFileSync(path.join(shell.ROOT, 'link_brain/assets/fonts', f)).toString('base64');
  const resources = {
    '_archive/fonts/Cinzel-latin-variable.woff2': font('Cinzel-latin-variable.woff2'),
    '_archive/fonts/CormorantGaramond-Italic-latin-variable.woff2': font('CormorantGaramond-Italic-latin-variable.woff2'),
  };
  const next = new Date(now + 5 * 3600e3 + 30 * 60e3);
  const schedule = { task: 'LinkBrainNightly', enabled: true, freq: 'hourly', next_run: localIso(next), summary: `每 6 小时一次 · 下次 ${localIso(next).slice(5, 16)}`, rules: [] };
  const sync = (more = {}) => JSON.stringify({ state: 'ready', updated_at: new Date().toISOString(), last_success: new Date(now - 30 * 60e3).toISOString(), ...more });
  return { data, resources, schedule, sync };
}
const PLUGIN = schedule => ({ methods: { getSyncSchedule: { result: schedule } } });

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const { data, resources, schedule, sync } = fixture();
  const shots = [];
  const R = (page, s) => page.evaluate(s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), height: Math.round(r.height) }; }, s);
  try {
    // ── ①②③④⑦ 宽屏三种宿主 ──
    for (const [host, theme] of [['page-reading', 'light'], ['page-reading', 'dark'], ['page-live', 'light']]) {
      const tag = `${host === 'page-live' ? 'live' : 'reading'}-${theme}-1400`;
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host, kind: 'catalog', theme, data, resources, plugin: PLUGIN(schedule), files: { '_archive/sync-status.json': sync() } });
      await page.evaluate(() => document.fonts.ready); await S.settle(80);
      // 1027b 最近导入默认折成一行：点开再量
      await page.click('.lbc-mod-recent .lbc-fold-sum'); await S.settle(40);
      const m = await page.evaluate(() => {
        const r = s => { const e = document.querySelector(s); const b = e.getBoundingClientRect(); return { left: b.left, right: b.right, top: b.top, width: b.width }; };
        const side = document.querySelector('.lbc-side'), lab = document.querySelector('.lbc-lab-en');
        return { side: r('.lbc-side'), main: r('.lbc-board-main'), board: r('.lbc-board'), mods: [...document.querySelectorAll('.lbc-mod')].map(x => x.dataset.mod),
          labFont: getComputedStyle(lab).fontFamily, labSize: getComputedStyle(lab).fontSize, labWeight: getComputedStyle(lab).fontWeight, labSpacing: getComputedStyle(lab).letterSpacing,
          line: document.querySelector('.lbc-lab-line').getBoundingClientRect().width, sideDisplay: getComputedStyle(side).display, sidePos: getComputedStyle(side).position,
          scrollbar: side.offsetWidth - side.clientWidth,
          rec: (() => { const ul = document.querySelector('.lbc-rec'), b = ul.getBoundingClientRect().bottom; return [...ul.querySelectorAll('li')].filter(li => li.getBoundingClientRect().bottom <= b + 1).length; })(),
          recEllipsis: (() => { const t = document.querySelector('.lbc-rec-t'); return getComputedStyle(t).textOverflow; })(),
          syBig: getComputedStyle(document.querySelector('.lbc-sy-big')).fontSize, cost: document.querySelector('.lbc-mod-token .lbc-tk-big').textContent,
          tkBig: getComputedStyle(document.querySelector('.lbc-mod-token .lbc-tk-big')).fontSize, syStyle: getComputedStyle(document.querySelector('.lbc-sy-big')).fontStyle,
          syFam: getComputedStyle(document.querySelector('.lbc-sy-big')).fontFamily };
      });
      assert.equal(m.sideDisplay, 'block'); assert.equal(m.sidePos, 'sticky');
      assert.deepEqual(m.mods, ['recent', 'sync', 'token', 'overview'], '1027：Token 费用从同步里拆出来，自己一块');
      assert.ok(m.side.right < m.main.left && Math.abs(m.main.left - m.side.right - 40) <= 2, `${tag}：边栏在左、间距 40 ${JSON.stringify([m.side, m.main])}`);
      const ratio = m.side.width / (m.board.width - 40); assert.ok(ratio > 0.3 && ratio < 0.37, `${tag}：边栏约 4/12 ${ratio}`);
      assert.match(m.labFont, /LB Cinzel/); assert.equal(m.labSize, '11px'); assert.equal(m.labWeight, '700');
      assert.ok(Math.abs(parseFloat(m.labSpacing) - 11 * 0.26) < 0.2, `${tag}：字距 .26em ${m.labSpacing}`);
      assert.ok(m.line > 60, `${tag}：横线撑满 ${m.line}`);
      assert.equal(m.scrollbar, 0, `${tag}：边栏不显示滚动条`);
      assert.equal(m.rec, 6, `${tag}：列表框高 = 6 条（其余在框里滚）`); assert.equal(m.recEllipsis, 'ellipsis'); assert.equal(m.syBig, m.tkBig, `${tag}：1027b 大数字一档（同步 = Token）`); assert.ok(parseFloat(m.syBig) >= 24 && parseFloat(m.syBig) <= 34, m.syBig); assert.equal(m.syStyle, 'italic'); assert.match(m.syFam, /Cormorant/, '目录页数字照旧 Cormorant 斜体'); assert.equal(m.cost, '¥ 3.72');
      shots.push(await S.screenshot(`catalog-side-${tag}`));
      // ② 吸顶：滚 1500，页头 / 边栏不动，收藏墙动了；边栏贴在页头底下；页头上方不留缝
      const before = { top: await R(page, '.lbc-top'), side: await R(page, '.lbc-side'), card: await R(page, '.lbc-card') };
      const c1 = await S.probeSticky({ target: '.lbc-top', by: 1500 });
      assert.ok(Math.abs(c1.delta) <= 1, `${tag}：吸顶 |delta| ≤ 1 ${JSON.stringify(c1)}`);
      const after = { top: await R(page, '.lbc-top'), side: await R(page, '.lbc-side'), card: await R(page, '.lbc-card'), sc: await R(page, S.selectors.scroller) };
      assert.ok(Math.abs(after.side.top - after.top.bottom) <= 2, `${tag}：边栏贴在页头底下 ${JSON.stringify([after.top, after.side])}`);
      assert.ok(after.side.bottom <= after.sc.bottom - 10, `${tag}：边栏底不出可视区 ${JSON.stringify([after.side, after.sc])}`);
      assert.ok(after.card.top < before.card.top - 1000, `${tag}：收藏墙在动 ${before.card.top} → ${after.card.top}`);
      const scrolled = await S.scrollTop();
      shots.push(await S.screenshot(`catalog-side-${tag}-scrolled`));
      // ③ 边栏自己滚：展开 OVERVIEW 让它超高 → 底部渐隐；滚到底 → 渐隐去掉；页面没跟着滚
      await page.click('.lbc-mod-overview .lbc-fold-sum'); await S.settle(60);
      const fade = await page.evaluate(() => { const s = document.querySelector('.lbc-side'); return { more: s.classList.contains('is-more'), mask: getComputedStyle(s).maskImage || getComputedStyle(s).webkitMaskImage, over: s.scrollHeight - s.clientHeight }; });
      assert.ok(fade.over > 0 && fade.more && /linear-gradient/.test(fade.mask), `${tag}：超高时底部渐隐 ${JSON.stringify(fade)}`);
      await page.evaluate(() => { const s = document.querySelector('.lbc-side'); s.scrollTop = s.scrollHeight; s.dispatchEvent(new Event('scroll')); }); await S.settle(40);
      const end = await page.evaluate(() => { const s = document.querySelector('.lbc-side'); return { more: s.classList.contains('is-more'), mask: getComputedStyle(s).maskImage || getComputedStyle(s).webkitMaskImage }; });
      assert.ok(!end.more && !/linear-gradient/.test(end.mask), `${tag}：到底去掉渐隐 ${JSON.stringify(end)}`);
      assert.equal(await S.scrollTop(), scrolled, `${tag}：边栏自己滚，页面没动`);
      if (theme === 'light' && host === 'page-reading') {
        await S.scrollTo(0); await page.evaluate(() => { const s = document.querySelector('.lbc-side'); s.scrollTop = s.scrollHeight; s.dispatchEvent(new Event('scroll')); }); await S.settle(60);   // OVERVIEW 在边栏底下：边栏自己滚到底再截
        shots.push(await S.screenshot(`catalog-side-${tag}-overview`));
      }
      await page.click('.lbc-mod-overview .lbc-lab'); await S.settle(40);
      // ⑦ 返回后滚动位置还在：滚到 1200，重建页面（Dataview 重建）后回到 1200
      await S.scrollTo(1200);
      await S.recreate(); await S.settle(200);
      const back = await S.scrollTop();
      assert.ok(Math.abs(back - 1200) <= 2, `${tag}：重建后滚动位置还在 ${back}`);
      await S.scrollTo(0);
      // ④ 收起：边栏不显示、收藏墙铺满、列数变多；再展开
      const colsBefore = await page.evaluate(() => document.querySelectorAll('.lbc-grid-inner:not(.lbc-grid-possible) > .lbc-col').length);
      const mainW = (await R(page, '.lbc-board-main')).width;
      await page.click('.lbc-sidetoggle'); await S.settle(120);
      const col = await page.evaluate(() => ({ side: getComputedStyle(document.querySelector('.lbc-side')).display, main: document.querySelector('.lbc-board-main').getBoundingClientRect().width, cols: document.querySelectorAll('.lbc-grid-inner:not(.lbc-grid-possible) > .lbc-col').length }));
      assert.equal(col.side, 'none'); assert.ok(col.main > mainW + 300, `${tag}：收起后收藏墙铺满 ${mainW} → ${col.main}`);
      assert.ok(col.cols > colsBefore, `${tag}：列数变多 ${colsBefore} → ${col.cols}`);
      if (theme === 'light' && host === 'page-reading') { await S.scrollTo(0); shots.push(await S.screenshot(`catalog-side-${tag}-collapsed`)); }
      await page.click('.lbc-sidetoggle'); await S.settle(120);
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.lbc-side')).display), 'block');
      // ⑥ 同步中：真实进度；收藏墙不重建、滚动不动
      if (theme === 'light' && host === 'page-reading') {
        await S.scrollTo(600);
        const firstCard = await page.evaluate(() => { window.__card0 = document.querySelector('.lbc-card'); return true; });
        void firstCard;
        await S.setFile('_archive/sync-status.json', sync({ state: 'running', done: 12, total: 40, progress: '12/40' })); await S.settle(120);
        const run = await page.evaluate(() => ({ big: document.querySelector('.lbc-sy-now .lbc-sy-big')?.textContent, w: document.querySelector('.lbc-mod-sync .lbc-sy-bar i').style.width, same: document.querySelector('.lbc-card') === window.__card0 }));
        assert.deepEqual(run, { big: '12/40', w: '30%', same: true }, `${tag}：同步中真实进度、收藏墙不重建`);
        assert.equal(await S.scrollTop(), 600);
        await S.scrollTo(0);
        shots.push(await S.screenshot(`catalog-side-${tag}-running`));
      }
      assert.deepEqual(await S.pageErrors(), [], `${tag}：页面没报错`);
      await page.close();
    }
    // ── ⑤ 窄：760 以下 / 390 不出边栏 ──
    for (const width of [740, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, plugin: PLUGIN(schedule), files: { '_archive/sync-status.json': sync() } });
      await S.settle(60);
      const n = await page.evaluate(() => ({ side: getComputedStyle(document.querySelector('.lbc-side')).display, tog: getComputedStyle(document.querySelector('.lbc-sidetoggle')).display, grid: document.querySelector('.lbc-board').getBoundingClientRect().width - document.querySelector('.lbc-board-main').getBoundingClientRect().width, hOverflow: (s => s.scrollWidth - s.clientWidth)(document.querySelector('.workspace-leaf.mod-active .markdown-preview-view')) }));
      assert.equal(n.side, 'none', `${width}：不出边栏`); assert.equal(n.tog, 'none', `${width}：边栏钮也不出`); assert.ok(Math.abs(n.grid) <= 1, `${width}：收藏墙铺满 ${n.grid}`); assert.ok(n.hOverflow <= 1);
      if (width === 390) shots.push(await S.screenshot('catalog-side-reading-light-390'));
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    // ── ⑥ 没插件（插件没开）：SYNC 「—」+ 一句说明，不报错 ──
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, plugin: null, files: { '_archive/sync-status.json': sync() } });
      await S.settle(60);
      const t = await page.evaluate(() => ({ next: document.querySelectorAll('.lbc-mod-sync .lbc-sy-big')[1]?.textContent, note: document.querySelector('.lbc-mod-sync .lbc-sy-note')?.textContent }));
      assert.equal(t.next, '—'); assert.match(t.note, /插件没开/);
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS catalog_plus_side_ui 1021：边栏在左 4/12 · 间距 40 · 小标题 Cinzel 11px 字距 .26em + 横线 · 吸顶后只有收藏墙在动（阅读 / 实时预览 × 浅 / 深，页头不留缝）· 边栏自己滚无滚动条 + 底部渐隐到底去掉 · 收起铺满列数变多 · 760 / 390 不出 · 同步中真实进度不重建墙 · 重建后滚动位置还在 · 没插件不报错。截图：\n  ' + shots.join('\n  '));
  } finally { await browser.close(); }
})().catch(e => { console.error('FAIL catalog_plus_side_ui', e); process.exit(1); });

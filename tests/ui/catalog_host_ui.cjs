// 批次 D · L1 目录页在 Obsidian 外壳里（阅读视图 / 实时预览，1.14.4 的层级和 CSS 子集）：
//   ① 守卫：容器带 Dataview 的行内 overflow-x:auto，实时预览有 .cm-embed-block:hover{overflow:hidden}（别把外壳「修」得不像真宿主）
//   ② C1 吸顶：鼠标停在页上、滚 1500 → 顶栏贴住滚动容器顶边（|delta| ≤ 1，主审裁决 1：上方不留缝）
//   ③ 多选栏在顶栏里：勾一张 → .lbc-selbar 可见、整个落在 .lbc-top 之内；滚动 0 / 1500 两处首次勾选，鼠标下那张卡 |Δy| ≤ 1（C10）
//   ④ 回顶钮：滚过 600 出现，钉在视口底部附近
//   ⑤ C4：聚焦搜索框打字，中间 Dataview 重跑 3 次 → 字不丢、焦点还在
//   ⑥ C9：第一排是排名前 N 篇（rect.top 相差 ≤ 2、按 x 递增）；视口 1280 → 900 列数变了、带标记的卡片元素还在（没重建）
//   ⑦ C2：点 ☆ 之后那张卡原地不动（rect 前后一样）、变成 ★
//   ⑧ X14c：先开问收藏页（它的 head 样式里抄过 .lbc-star{opacity:0}）再开目录 → 没收藏的 ☆ 计算 opacity 是 0（1008 18:50 她：平时隐藏，悬停才出现）
// 截图进 LWA_QA_DIR（默认系统临时目录下 lwa-qa；施工时设成 <worktree>/qa，不提交）
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const results = {};
  const data = shell.makeCatalogData({ n: 120 });
  try {
    for (const host of ['page-reading', 'page-live']) {
      for (const theme of ['light', 'dark']) {
        const tag = `${host}/${theme}`;
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const S = await shell.page(page, { host, kind: 'catalog', theme, data });
        // ① 守卫
        const g = await S.guards();
        assert.equal(g.containerInlineOverflowX, 'auto', `${tag}：容器带 Dataview 写的行内 overflow-x:auto`);
        if (host === 'page-live') assert.ok(g.hoverOverflowHidden && g.inEmbedBlock, `${tag}：实时预览带 :hover{overflow:hidden}`);
        assert.equal(await page.evaluate(() => document.querySelector('.workspace-leaf.mod-active .block-language-dataviewjs').children.length), 0, `${tag}：容器本身空着（页面在 host 上）`);
        // ② 吸顶
        const c1 = await S.probeSticky({ target: '.lbc-top', by: 1500 });
        results[`C1 ${tag}`] = c1;
        assert.ok(Math.abs(c1.delta) <= 1, `${tag}：吸顶 |delta| ≤ 1，实际 ${JSON.stringify(c1)}`);
        if (host === 'page-live') assert.ok(c1.embedHovered, `${tag}：探针时鼠标确实停在代码块上（:hover 规则生效）`);
        if (theme === 'light') await S.screenshot(`catalog-${host === 'page-live' ? 'live' : 'reading'}-sticky`);
        else await S.screenshot(`catalog-${host === 'page-live' ? 'live' : 'reading'}-sticky-dark`);
        // ④ 回顶钮
        const dock = await page.evaluate(() => { const d = document.querySelector('.lbc-totop-dock'); const b = d.querySelector('.lbc-totop').getBoundingClientRect(); return { on: d.classList.contains('is-on'), bottom: b.bottom, vh: innerHeight }; });
        assert.ok(dock.on, `${tag}：滚过 600 出现回顶钮`);
        assert.ok(dock.bottom <= dock.vh - 18 && dock.bottom >= dock.vh - 80, `${tag}：回顶钮钉在视口底部附近 ${JSON.stringify(dock)}`);
        // ③ 多选栏在顶栏里；1500 处首次勾选，鼠标下那张卡相对吸顶区底边不动（a8bbfc4 / 1019 她：吸顶区变高时卡片跟着往下让、不被多选栏盖住——
        //    原来断言「绝对位置不动」，那一版起卡片会正好下移一个多选栏的高度，这条一直红着；1021 改成量离吸顶区底边的距离）
        const pick = await page.evaluate(() => {
          const top = document.querySelector('.lbc-top').getBoundingClientRect().bottom;
          const card = [...document.querySelectorAll('.lbc-card')].find(c => c.getBoundingClientRect().top > top + 40);
          card.dataset.probe = '1';
          return card.getBoundingClientRect().top - top;
        });
        // 1021：鼠标直接移过去点（不用 page.hover / click：卡比视口剩下的地方高时它们会先把卡滚进视野，量到的就不是勾选本身）
        const cb = await page.evaluate(() => { const r = document.querySelector('.lbc-card[data-probe="1"]').getBoundingClientRect(); return [r.left + r.width / 2, Math.min(r.top + 60, innerHeight - 10)]; });
        await page.mouse.move(cb[0], cb[1]); await S.settle(60);
        const ck = await page.evaluate(() => { const r = document.querySelector('.lbc-card[data-probe="1"] .lbc-check').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; });
        await page.mouse.click(ck[0], ck[1]);
        await S.settle();
        const after = await page.evaluate(() => document.querySelector('.lbc-card[data-probe="1"]').getBoundingClientRect().top - document.querySelector('.lbc-top').getBoundingClientRect().bottom);
        assert.ok(Math.abs(after - pick) <= 1, `${tag}：滚到 1500 时首次勾选，那张卡离吸顶区底边 Δy=${after - pick}`);
        const sel = await page.evaluate(() => { const s = document.querySelector('.lbc-selbar'), t = document.querySelector('.lbc-top'); const a = s.getBoundingClientRect(), b = t.getBoundingClientRect(); return { visible: !s.hidden && a.height > 0, inside: a.top >= b.top - 0.5 && a.bottom <= b.bottom + 0.5 && s.parentElement === t }; });
        assert.ok(sel.visible && sel.inside, `${tag}：多选栏在顶栏里 ${JSON.stringify(sel)}`);
        const c1b = await S.probeSticky({ target: '.lbc-top', by: 300 });
        assert.ok(Math.abs(c1b.delta) <= 1, `${tag}：带着多选栏也吸顶 ${JSON.stringify(c1b)}`);
        if (theme === 'light') await S.screenshot(`catalog-select-sticky${host === 'page-live' ? '-live' : ''}`);
        await page.keyboard.press('Escape');
        await page.close();
      }
    }

    // ③ 滚动 0 时首次勾选：下面的卡不往下错
    {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', data });
      await page.evaluate(() => { const c = document.querySelectorAll('.lbc-col')[1].querySelector('.lbc-card'); c.dataset.probe = '1'; });
      await page.hover('.lbc-card[data-probe="1"]');
      assert.equal(await S.scrollTop(), 0, '还在顶上');
      // 同上（1019）：量卡片离吸顶区底边的距离——多选栏出来，卡片跟着往下让、不被盖住，也不额外错位
      const gapNow = () => page.evaluate(() => document.querySelector('.lbc-card[data-probe="1"]').getBoundingClientRect().top - document.querySelector('.lbc-top').getBoundingClientRect().bottom);
      const before = await gapNow();
      await page.click('.lbc-card[data-probe="1"] .lbc-check'); await S.settle();
      const after = await gapNow();
      assert.ok(Math.abs(after - before) <= 1, `滚动 0 首次勾选，离吸顶区底边 Δy=${after - before}`);
      await S.screenshot('catalog-select-first');
      // ⑦ C2：点 ☆ 卡片原地不动
      await page.keyboard.press('Escape'); await S.settle();
      await page.evaluate(() => { const cols = document.querySelectorAll('.lbc-col'); const c = cols[Math.min(2, cols.length - 1)].querySelector('.lbc-card'); c.dataset.star = '1';   /* 1021 边栏开着 1280 宽只有两列 */ });
      await page.hover('.lbc-card[data-star="1"]');
      const was = await page.evaluate(() => document.querySelector('.lbc-card[data-star="1"] .lbc-star').classList.contains('is-on'));
      const r0 = await page.evaluate(() => JSON.stringify(document.querySelector('.lbc-card[data-star="1"]').getBoundingClientRect()));
      await S.screenshot('catalog-star-inplace-before');
      await page.click('.lbc-card[data-star="1"] .lbc-star'); await S.settle(60);
      const r1 = await page.evaluate(() => JSON.stringify(document.querySelector('.lbc-card[data-star="1"]').getBoundingClientRect()));
      assert.equal(r1, r0, '点星后卡片原地不动');
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-card[data-star="1"] .lbc-star').classList.contains('is-on')), !was, '星换了');
      await S.screenshot('catalog-star-inplace-after');
      await page.close();
    }

    // ⑤ C4：两种宿主里打字中间穿插重跑
    for (const host of ['page-reading', 'page-live']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const S = await shell.page(page, { host, kind: 'catalog', data });
      const c4 = await S.probeFocusAfterRerun({ input: '.lbc-search', text: 'kafei', reruns: 3 });
      results[`C4 ${host}`] = c4;
      assert.ok(c4.ok, `${host}：重跑不丢字、不失焦 ${JSON.stringify(c4)}`);
      if (host === 'page-reading') await S.screenshot('catalog-reading-typing');
      await page.close();
    }

    // ⑥ C9：第一排是排名前 N 篇；窄了列数变、卡片不重建
    {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', data: shell.makeCatalogData({ n: 350, starredEvery: 0 }), run: false });
      // 1021：这一条量的是瀑布流分列（1280 宽至少 3 列），按「边栏收起」开（边栏开着时收藏墙只占 8/12）
      await page.evaluate(() => { (window.__lbState = window.__lbState || {})['lb:catalog'] = JSON.stringify({ ts: Date.now(), side: false }); });
      await S.run(); await S.settle();
      await page.waitForFunction(() => !document.querySelector('.lbc-grid[data-lbc-filling]'));   // 1017：首开 350 张是分片补的，等补完再数
      const row = await page.evaluate(() => {
        const cols = [...document.querySelectorAll('.lbc-grid-inner > .lbc-col')];
        const firsts = cols.map(c => c.querySelector('.lbc-card'));
        return { n: cols.length, tops: firsts.map(c => c.getBoundingClientRect().top), xs: firsts.map(c => c.getBoundingClientRect().left), titles: firsts.map(c => c.querySelector('.lbc-ctitle').textContent) };
      });
      assert.ok(row.n >= 3, '1280 宽至少 3 列：' + row.n);
      assert.ok(Math.max(...row.tops) - Math.min(...row.tops) <= 2, '第一排顶边对齐：' + row.tops);
      assert.deepEqual(row.xs, [...row.xs].sort((a, b) => a - b), '按 x 递增');
      const expected = shell.makeCatalogData({ n: 350, starredEvery: 0 }).items.slice(0, row.n).map(x => x.title);
      assert.deepEqual(row.titles, expected, '第一排正好是第 1–N 篇');
      await S.screenshot('catalog-masonry-rows');
      await page.evaluate(() => { document.querySelectorAll('.lbc-card').forEach(c => { c.__mark = 1; }); });
      await page.setViewportSize({ width: 900, height: 900 }); await S.settle(120);
      const after = await page.evaluate(() => ({ n: document.querySelectorAll('.lbc-grid-inner > .lbc-col').length, marked: [...document.querySelectorAll('.lbc-card')].every(c => c.__mark === 1) }));
      assert.ok(after.n < row.n, `窄了列数变少 ${row.n} → ${after.n}`);
      assert.ok(after.marked, '卡片元素还是原来那些（没重建）');
      await page.setViewportSize({ width: 390, height: 844 }); await S.settle(120);
      const noHScroll = await page.evaluate(() => document.querySelector('.markdown-preview-view').scrollWidth <= document.querySelector('.markdown-preview-view').clientWidth + 1);
      assert.ok(noHScroll, '390 宽没有横向滚动');
      await S.screenshot('catalog-masonry-narrow');
      await page.close();
    }

    // ⑧ X14c：两种打开顺序下没收藏的 ☆ 计算 opacity 都是 0（平时隐藏）（第二页在同一个阅读视图里另起一段 dataviewjs 容器跑）
    for (const order of [['chat', 'catalog'], ['catalog', 'chat']]) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: order[0], data });
      await page.evaluate(async code => {
        const sizer = document.querySelector('.workspace-leaf.mod-active .markdown-preview-sizer');
        const pre = document.createElement('div'); pre.className = 'el-pre';
        pre.innerHTML = '<div class="block-language-dataviewjs node-insert-event" style="overflow-x: auto;"></div>';
        sizer.appendChild(pre);
        window.__shell.container = pre.firstChild; window.__shell.section = pre;
        const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
        await new AsyncFunction('dv', 'input', code)(window.__shell.dv(), undefined);
      }, shell.pageAssets(order[1]));
      await S.settle(60);
      const op = await page.evaluate(() => { const st = [...document.querySelectorAll('.lbc-card .lbc-star')].find(s => !s.classList.contains('is-on')); return st ? getComputedStyle(st).opacity : null; });
      assert.equal(op, '0', `${order.join(' → ')}：没收藏的 ☆ 平时隐藏（opacity ${op}）`);
      if (order[0] === 'chat') { await page.evaluate(() => document.querySelector('.lbc-wrap').scrollIntoView()); await S.screenshot('catalog-after-chat'); }
      await page.close();
    }    // 回收站页同理（主审裁决 1）：页头吸顶 |delta| ≤ 1，阅读视图 / 实时预览
    for (const host of ['page-reading', 'page-live']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const trash = { items: Array.from({ length: 60 }, (_, i) => ({ item_id: 'xhs-' + i, title: '删掉的收藏 ' + i, deleted_at: '2026-10-07T10:00:00+10:00', restorable: true, has_files: true })) };
      const S = await shell.page(page, { host, kind: 'trash', files: { '_archive/trash-data.json': JSON.stringify(trash) } });
      const r = await S.probeSticky({ target: '.lbt-head', by: 800 });
      results[`C1 trash ${host}`] = r;
      assert.ok(Math.abs(r.delta) <= 1, `回收站 ${host}：页头吸顶 ${JSON.stringify(r)}`);
      if (host === 'page-reading') { await S.scrollTo(0); await S.screenshot('trash-list'); }
      await page.close();
    }    const pageErrorsNote = '';
    console.log('C1 / C4 读数：' + JSON.stringify(results));
    console.log('PASS catalog host: sticky top |delta| ≤ 1 in reading + live (light / dark), selbar inside sticky top, first select / star keep cards in place, to-top dock, rerun keeps typing + focus, masonry first row = top N and resize keeps card elements, 390 no h-scroll, unstarred ☆ hidden (opacity 0) after chat page' + pageErrorsNote);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

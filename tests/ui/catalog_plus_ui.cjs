// 1021 目录页改版（Collection+ 设计交接包第 1、2 段）：Obsidian 外壳 · 真 Chromium。
//   阅读视图 × 浅 / 深、实时预览 × 浅；宽 1400 和窄 390：
//   ① 雕刻标题用随包字体（LB Cinzel 真加载上，资源路径过 lbPath）；篇数 / 更新在标题右侧、和标题底部对齐（宽屏）
//   ② 分类行居中、可换行、不横向滚；控制行同一行控件同高 34px；「管理」在右上角
//   ③ 吸顶上方不留缝（10-08 C1）照旧：带着新页头在两种宿主里 |delta| ≤ 1
//   ④ 悬停：封面左上错位 + 不模糊的实心投影；无封面卡的柔和封面深色主题下也是浅底深字
//   ⑤ 列表视图 / 主题行 / 窄屏不横向溢出；页面没有报错
// 截图进 LWA_QA_DIR（catalog-plus-*.png），和 _handoff/collection-plus-handoff/prototype/screens/ 对照
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

function fixture() {
  const data = shell.makeCatalogData({ n: 48 });
  data.topics = ['合同法', 'graph', '睡眠'];
  const authors = ['法学笔记本', '小锅日记', '喵学研究所', 'Ann'];
  const day = (() => { const d = new Date(); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; })();
  data.items.forEach((it, i) => {
    it.author = authors[i % 4]; it.likes = i * 137;
    if (i % 5 === 0) it.topics = ['合同法']; if (i % 7 === 0) it.topics = ['graph'];
    if (i % 6 === 0) it.kind = 'video';
    it.date = i < 6 ? day : '2026-10-01';
  });
  const font = f => 'data:font/woff2;base64,' + fs.readFileSync(path.join(shell.ROOT, 'link_brain/assets/fonts', f)).toString('base64');
  const resources = {
    '_archive/fonts/Cinzel-latin-variable.woff2': font('Cinzel-latin-variable.woff2'),
    '_archive/fonts/CormorantGaramond-Italic-latin-variable.woff2': font('CormorantGaramond-Italic-latin-variable.woff2'),
  };
  // 一部分卡有封面图（合成的纯色图），其余是柔和文字封面
  const svg = (c, h) => 'data:image/svg+xml;utf8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="300" height="${h}"><rect width="300" height="${h}" fill="${c}"/><circle cx="150" cy="${h / 2}" r="60" fill="#ffffff88"/></svg>`);
  ['#c94', '#58a', '#7a6', '#a57', '#456', '#b84'].forEach((c, k) => { const it = data.items[k * 3 + 1]; it.cover = `_archive/xiaohongshu/c${k}/cover.svg`; it.cover_w = 300; it.cover_h = 300 + k * 50; resources[it.cover] = svg(c, it.cover_h); });
  return { data, resources };
}

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const { data, resources } = fixture();
  const shots = [];
  try {
    for (const [host, theme, width] of [['page-reading', 'light', 1400], ['page-reading', 'dark', 1400], ['page-live', 'light', 1400], ['page-reading', 'light', 390], ['page-reading', 'dark', 390], ['page-live', 'light', 390]]) {
      const tag = `${host === 'page-live' ? 'live' : 'reading'}-${theme}-${width}`;
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const S = await shell.page(page, { host, kind: 'catalog', theme, data, resources });
      await page.evaluate(() => document.fonts.ready); await S.settle(60);
      const m = await page.evaluate(() => {
        const R = s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height }; };
        const title = document.querySelector('.lbc-title-text');
        const cats = document.querySelector('.lbc-cats');
        const scroller = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view, .workspace-leaf.mod-active .cm-scroller');
        return {
          fontOk: document.fonts.check('900 40px "LB Cinzel"') && [...document.fonts].some(f => f.family.replace(/"/g, '') === 'LB Cinzel' && f.status === 'loaded'),
          titleFamily: getComputedStyle(title).fontFamily, dataText: title.dataset.text, titleText: title.textContent,
          title: R('.lbc-titlerow'), sub: R('.lbc-subline'), manage: R('.lb-manage'), wrap: R('.lbc-wrap'),
          catsScroll: cats.scrollWidth - cats.clientWidth, catsJustify: getComputedStyle(cats).justifyContent, catsWrap: getComputedStyle(cats).flexWrap,
          ctl: ['.lbc-time', '.lbc-vseg', '.lbc-searchbox', '.lbc-askbtn'].map(s => Math.round(R(s).height)),
          hOverflow: scroller.scrollWidth - scroller.clientWidth,
        };
      });
      assert.ok(m.fontOk, `${tag}：随包的 Cinzel 真加载上了（${m.titleFamily}）`);
      assert.equal(m.dataText, m.titleText, `${tag}：刻线层和标题同字`);
      assert.ok(m.catsScroll <= 1 && m.catsJustify === 'center' && m.catsWrap === 'wrap', `${tag}：分类行居中、换行、不横向滚 ${JSON.stringify(m)}`);
      assert.ok(m.ctl.every(h => h === 34), `${tag}：控制行右组同高 34px ${m.ctl}`);
      assert.ok(m.hOverflow <= 1, `${tag}：没有横向滚动 ${m.hOverflow}`);
      if (width >= 1000) {
        assert.ok(m.sub.left >= m.title.right - 1, `${tag}：篇数 / 更新在标题右侧 ${JSON.stringify([m.title, m.sub])}`);
        assert.ok(Math.abs(m.sub.bottom - m.title.bottom) <= 24, `${tag}：和标题底部对齐 ${JSON.stringify([m.title, m.sub])}`);
        assert.ok(m.manage.right >= m.wrap.right - 40 && m.manage.top <= m.title.top + 10, `${tag}：「管理」在右上角 ${JSON.stringify(m.manage)}`);
      } else {
        assert.ok(m.manage.bottom <= m.title.top + 4, `${tag}：窄屏「管理」在标题上面一行 ${JSON.stringify([m.manage, m.title])}`);
      }
      // ③ 吸顶上方不留缝（10-08 C1 口径）
      if (width >= 1000) {
        shots.push(await S.screenshot(`catalog-plus-${tag}`));
        const c1 = await S.probeSticky({ target: '.lbc-top', by: 1200 });
        assert.ok(Math.abs(c1.delta) <= 1, `${tag}：吸顶 |delta| ≤ 1 ${JSON.stringify(c1)}`);
        await S.scrollTo(0);
      } else {
        shots.push(await S.screenshot(`catalog-plus-${tag}`));
        // 窄屏：整块页头吸住会占掉半屏多——吸住时只露搜索那一行起（标题 / 分类行 / 范围标签滚上去），往回滚照常出来
        await S.scrollTo(1500);
        const st = await page.evaluate(() => {
          const sc = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view, .workspace-leaf.mod-active .cm-scroller').getBoundingClientRect();
          return { scTop: sc.top, sb: document.querySelector('.lbc-searchbox').getBoundingClientRect().top, topBottom: document.querySelector('.lbc-top').getBoundingClientRect().bottom, title: document.querySelector('.lbc-titlerow').getBoundingClientRect().bottom };
        });
        assert.ok(st.sb >= st.scTop - 1 && st.sb <= st.scTop + 16, `${tag}：吸住时搜索框贴着顶 ${JSON.stringify(st)}`);
        assert.ok(st.title <= st.scTop && st.topBottom - st.scTop < 140, `${tag}：吸住的那截不到 140px，标题滚上去了 ${JSON.stringify(st)}`);
        if (theme === 'light' && host === 'page-reading') shots.push(await S.screenshot(`catalog-plus-${tag}-stuck`));
        await S.scrollTo(0);
      }
      // ④ 悬停：错位 + 实心投影；柔和封面固定深色字
      if (width >= 1000) {
        const card = page.locator('.lbc-card:has(.lbc-nocover)').first();
        await card.hover(); await S.settle(320);
        const h = await card.evaluate(c => { const t = c.querySelector('.lbc-nocover'), cs = getComputedStyle(t); return { transform: cs.transform, shadow: cs.boxShadow, color: cs.color, bg: cs.backgroundColor }; });
        assert.match(h.transform, /matrix\(1, 0, 0, 1, -3, -3\)/, `${tag}：悬停左上错 3px ${JSON.stringify(h)}`);
        assert.match(h.shadow, /5px 5px 0px 0px/, `${tag}：不模糊的实心投影 ${JSON.stringify(h)}`);
        assert.equal(h.color, 'rgb(20, 20, 20)', `${tag}：柔和封面深色字（深色主题也是）`);
        assert.notEqual(h.bg, 'rgba(0, 0, 0, 0)');
        if (theme === 'light' && host === 'page-reading') shots.push(await S.screenshot(`catalog-plus-${tag}-hover`));
        await page.mouse.move(5, 5);
      }
      assert.deepEqual(await S.pageErrors(), [], `${tag}：页面没报错`);
      await page.close();
    }
    // ⑤ 主题行 + 列表视图（阅读视图 · 浅 · 1400）
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, plugin: { methods: { run: { result: { code: 0, json: { status: 'ok' } } } } } });
      await page.evaluate(() => document.fonts.ready);
      await page.click('.lbc-thq >> nth=0'); await S.settle();
      const row = await page.evaluate(() => { const t = document.querySelector('.lbc-topics'), c = document.querySelector('.lbc-ctl'); return { shown: !!t && t.getBoundingClientRect().height > 0, below: t && t.getBoundingClientRect().top >= c.getBoundingClientRect().bottom - 1, chips: [...t.querySelectorAll('.lbc-topic')].map(b => b.textContent), active: [...t.querySelectorAll('.lbc-topic.is-active')].map(b => b.textContent) }; });
      assert.ok(row.shown && row.below, `主题行在控制行下面 ${JSON.stringify(row)}`);
      assert.deepEqual(row.chips, ['★合同法', '★graph', '★睡眠']); assert.deepEqual(row.active, ['★合同法']);
      await page.hover('.lbc-topic-wrap >> nth=1'); await S.settle(60);
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelectorAll('.lbc-topic-del')[1]).display), 'grid', '悬停胶囊出 ×');
      shots.push(await S.screenshot('catalog-plus-topics'));
      await page.click('.lbc-view[data-view="list"]'); await S.settle();
      const list = await page.evaluate(() => ({ grid: document.querySelector('.lbc-grid').hidden, rows: document.querySelectorAll('.lbc-ltable tr.lbc-lrow').length, w: document.querySelector('.lbc-ltable').getBoundingClientRect().width }));
      assert.ok(list.grid && list.rows > 0 && list.w > 900, `列表视图 ${JSON.stringify(list)}`);
      shots.push(await S.screenshot('catalog-plus-list'));
      await page.click('.lbc-ltable tr.lbc-lrow >> nth=0'); await S.settle();
      assert.equal((await page.evaluate(() => window.opened.at(-1)))[2], false, '点行在同一窗格打开');
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS catalog_plus_ui 1021：随包 Cinzel 加载 · 刻线同字 · 篇数在标题右侧底对齐 · 管理在右上 · 分类居中换行不横滚 · 控制行 34px · 吸顶不留缝（阅读 / 实时预览 × 浅 / 深）· 悬停错位实心投影 · 柔和封面深色字 · 390 不横溢 · 主题行 / 列表视图。截图：\n  ' + shots.join('\n  '));
  } finally { await browser.close(); }
})().catch(e => { console.error('FAIL catalog_plus_ui', e); process.exit(1); });

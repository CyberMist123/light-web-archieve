// 1011 目录页「导入时间」弹层紧凑版（她：每项一个整宽按钮，太乱）。Obsidian 外壳（阅读视图）· 亮 / 暗 · 宽 1280 / 窄 400：
//   ① 排序一行分段（默认 | 最近导入 同一行、都不是整宽）；时间一行小块（全部 / 今天 / 7 天 / 30 天 / 自定义，宽屏同一行）
//   ② 没选自定义时起止不占位；弹层整体矮（两行），比改前那版（main 上的资产）矮一大截——改前读数照打出来（红线：旧版判红）
//   ③ 选中的块一眼可辨：背景色和没选中的不同、字色和自己的背景不同（强调色填满）
//   ④ 点「自定义」：弹层不关、起 ~ 止 + 筛选 露出来且在同一行；窄屏不横向溢出、不出视口
//   ⑤ 页面没有报错
// 截图进 LWA_QA_DIR（不提交、不必逐张看）
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const measure = page => page.evaluate(() => {
  const m = document.querySelector('.lbc-time-menu');
  if (!m) return null;
  const R = e => { const r = e.getBoundingClientRect(); return { top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), height: Math.round(r.height) }; };
  const cs = e => getComputedStyle(e);
  const seg = [...m.querySelectorAll('.lbc-seg-btn')], chips = [...m.querySelectorAll('.lbc-chip')];
  const range = m.querySelector('.lbc-range');
  const on = chips.find(c => c.classList.contains('is-on')), off = chips.find(c => !c.classList.contains('is-on'));
  return {
    menu: R(m), vw: innerWidth, overflowX: m.scrollWidth - m.clientWidth,
    items: m.querySelectorAll('.lbc-menu-item').length,
    seg: seg.map(R), segText: seg.map(b => b.textContent),
    chips: chips.map(R), chipText: chips.map(b => b.textContent),
    rangeShown: !!range && cs(range).display !== 'none' && range.getBoundingClientRect().height > 0,
    rangeParts: range ? [...range.querySelectorAll('input,button')].map(R) : [],
    onBg: on ? cs(on).backgroundColor : null, onColor: on ? cs(on).color : null, offBg: off ? cs(off).backgroundColor : null,
  };
});
const sameRow = rs => rs.length > 0 && rs.every(r => Math.abs(r.top - rs[0].top) <= 1);

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 40 });
  const OLD_REV = 'd320c32';   // 改前那版固定在 1011 上线前的 main，别对照活的 main（上线后它就是紧凑版）
  const out = {};
  try {
    // 改前那版（main 上的资产）：同样点开量一次高度，作对照（红线：旧版没有紧凑结构）
    let oldHeight = null;
    if (shell.revAvailable(OLD_REV)) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, rev: OLD_REV });
      await page.click('.lbc-time'); await S.settle();
      const old = await measure(page);
      oldHeight = old.menu.height;
      out.old = { height: old.menu.height, width: old.menu.width, chips: old.chips.length, seg: old.seg.length };
      if (old.chips.length === 5 && old.seg.length === 2) { oldHeight = null; console.log('（对照版已经是紧凑版：只记读数）'); }
      await page.close();
    }
    for (const theme of ['light', 'dark']) {
      for (const width of [1280, 400]) {
        const tag = `${theme}/${width}`;
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme, data });
        await page.click('.lbc-time'); await S.settle();
        const a = await measure(page);
        assert.ok(a, `${tag}：点「导入时间」出弹层`);
        // ① 一行分段 + 一行小块
        assert.deepEqual(a.segText, ['默认', '最近导入'], tag);
        assert.deepEqual(a.chipText, ['全部', '今天', '7 天', '30 天', '自定义'], tag);
        assert.ok(sameRow(a.seg), `${tag}：排序两段在同一行 ${JSON.stringify(a.seg)}`);
        assert.ok(a.seg.every(r => r.width < a.menu.width * 0.6), `${tag}：排序按钮不是整宽 ${JSON.stringify(a.seg)}`);
        if (width >= 1280) assert.ok(sameRow(a.chips), `${tag}：时间小块在同一行 ${JSON.stringify(a.chips)}`);
        assert.ok(a.chips.every(r => r.width < 90 && r.height <= 30), `${tag}：小块是小块 ${JSON.stringify(a.chips)}`);
        // ② 起止不占位、整体矮
        assert.equal(a.rangeShown, false, `${tag}：没选自定义时不露起止`);
        if (width >= 1280) assert.ok(a.menu.height <= 100, `${tag}：两行高 ≤ 100，实际 ${a.menu.height}`);
        if (oldHeight != null && width >= 1280) assert.ok(a.menu.height < oldHeight / 2, `${tag}：比改前（${oldHeight}px）矮一半以上，实际 ${a.menu.height}`);
        // ③ 选中态一眼可辨
        assert.notEqual(a.onBg, a.offBg, `${tag}：选中的块背景和没选中的不同`);
        assert.notEqual(a.onColor, a.onBg, `${tag}：选中的块字色和背景不同`);
        // 窄屏也不出视口、不横向溢出
        assert.ok(a.menu.left >= 0 && a.menu.right <= a.vw, `${tag}：弹层在视口里 ${JSON.stringify(a.menu)} vw=${a.vw}`);
        assert.ok(a.overflowX <= 1, `${tag}：弹层不横向溢出 ${a.overflowX}`);
        if (width >= 1280) await S.screenshot(`time-menu-${theme}`);
        // ④ 点「自定义」：不关，露起止且同一行
        await page.click('.lbc-time-menu .lbc-chip:has-text("自定义")'); await S.settle();
        const b = await measure(page);
        assert.ok(b, `${tag}：点自定义弹层不关`);
        assert.equal(b.rangeShown, true, `${tag}：点自定义露出起止`);
        assert.ok(sameRow(b.rangeParts) && b.rangeParts.length === 3, `${tag}：起 ~ 止 + 筛选 同一行 ${JSON.stringify(b.rangeParts)}`);
        assert.ok(b.menu.right <= b.vw && b.overflowX <= 1, `${tag}：起止露出后照样不溢出 ${JSON.stringify(b.menu)} ${b.overflowX}`);
        const focused = await page.evaluate(() => document.activeElement && document.activeElement.getAttribute('aria-label'));
        assert.equal(focused, '起', `${tag}：焦点进「起」`);
        if (width >= 1280) await S.screenshot(`time-menu-custom-${theme}`);
        // ⑤ 没报错
        assert.deepEqual(await S.pageErrors(), [], `${tag}：页面没报错`);
        out[tag] = { height: a.menu.height, width: a.menu.width, customHeight: b.menu.height, onBg: a.onBg, offBg: a.offBg };
        await page.close();
      }
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify(out));
  console.log('PASS time menu 1011: sort = one-row segmented, time = one row of chips (wraps on narrow), range only after 自定义 (same row, focus 起), selected chip visibly filled in light + dark, compact vs old, no overflow at 400px');
})().catch(e => { console.error(e); process.exit(1); });

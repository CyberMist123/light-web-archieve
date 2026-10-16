// 1015「目录页首开卡」：真库 859 篇首开时主线程一次 Layout 约 470ms（整页 859 张卡全排版，绝大多数在屏幕外）。
// 改法：.lbc-card 用 content-visibility:auto（屏外的卡跳过排版 / 绘制），占位高度 = 瀑布流本来就用的估算高（lbcCardHeight），
// 写在卡片行内 contain-intrinsic-size: auto <估算>px（auto = 画过一次后记住真高）。overflow-clip-margin 给悬停阴影 / 选中描边留边。
// 本测试：① 每张卡都带估算占位；② 屏外的卡真的被跳过（Layout 总时长 ≤ 关掉它时）；③ 滚到底再回顶，首排位置不变、最后一张能看见；
// ④ 悬停 + 选中的卡和关掉 content-visibility 时逐像素一样（阴影 / 描边没被裁）。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 700 });
  // 正文长一点、中英混排，排版成本接近真库
  for (const it of data.items) { it.summary = ('收藏的长概要，中文和 English mixed 文本。' + it.title).repeat(4); it.title = it.title + '：' + '一段比较长的标题'.repeat(2); }
  const layoutMs = async (page, S) => {
    await browser.startTracing(page, { categories: ['devtools.timeline'] });
    await S.run(); await S.settle();
    await page.waitForFunction(() => !document.querySelector('.lbc-grid[data-lbc-filling]'));   // 1017：首开 700 张是分片补的，量到补完
    await S.settle();
    const ev = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
    return ev.filter(e => e.ph === 'X' && e.name === 'Layout').reduce((a, e) => a + e.dur / 1000, 0);
  };
  const open = async (extraCss) => {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', data, run: false });
    if (extraCss) await page.addStyleTag({ content: extraCss });
    return { page, S, ms: await layoutMs(page, S) };
  };
  try {
    const on = await open(null);
    const off = await open('.lbc-card{content-visibility:visible!important}');
    const { page } = on;
    const info = await page.evaluate(() => { const cs = [...document.querySelectorAll('.lbc-card')]; return { n: cs.length, cv: getComputedStyle(cs[0]).contentVisibility, sized: cs.filter(c => /^auto \d+px$/.test(c.style.containIntrinsicSize)).length }; });
    assert.equal(info.n, 700); assert.equal(info.cv, 'auto', '卡片 content-visibility:auto');
    assert.equal(info.sized, 700, '每张卡都带估算占位高（contain-intrinsic-size: auto Npx）');
    assert.ok(on.ms <= off.ms, `屏外卡跳过排版：Layout ${on.ms.toFixed(0)}ms ≤ 关掉时 ${off.ms.toFixed(0)}ms`);
    // ③ 滚到底再回顶
    const first0 = await page.evaluate(() => { const r = document.querySelector('.lbc-card').getBoundingClientRect(); return [r.top, r.left]; });
    const scroller = await page.evaluate(() => { const el = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view'); return !!el; });
    assert.ok(scroller);
    for (let k = 0; k < 6; k++) { await page.evaluate(() => { const el = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view'); el.scrollTop = el.scrollHeight; el.dispatchEvent(new Event('scroll')); }); await page.waitForTimeout(80); }
    const lastVisible = await page.evaluate(() => { const cards = [...document.querySelectorAll('.lbc-card')]; const vh = innerHeight; return cards.some(c => { const r = c.getBoundingClientRect(); return r.bottom > 0 && r.top < vh && c.querySelector('.lbc-title, .lbc-cover, .lbc-nocover'); }); });
    assert.ok(lastVisible, '滚到底能看见卡片（不是空白占位）');
    await page.evaluate(() => { const el = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view'); el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); }); await page.waitForTimeout(150);
    const first1 = await page.evaluate(() => { const r = document.querySelector('.lbc-card').getBoundingClientRect(); return [r.top, r.left]; });
    assert.deepEqual(first1, first0, '回顶后首排位置不变');
    // ④ 悬停 + 选中外观不被裁
    const card = page.locator('.lbc-card').nth(1); const b = await card.boundingBox();
    const clip = { x: b.x - 20, y: b.y - 24, width: b.width + 40, height: Math.min(b.height + 48, 500) };   // 左右各 20（列间距 24，不碰邻卡）
    await card.hover(); await page.evaluate(() => document.querySelectorAll('.lbc-card')[1].classList.add('is-selected')); await page.waitForTimeout(300);
    const a = await page.screenshot({ clip });
    await page.addStyleTag({ content: '.lbc-card{content-visibility:visible!important}' }); await page.waitForTimeout(300);
    const z = await page.screenshot({ clip });
    const diff = await page.evaluate(async ([a, z]) => {
      const load = src => new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = 'data:image/png;base64,' + src; });
      const [ia, iz] = await Promise.all([load(a), load(z)]);
      const px = i => { const c = document.createElement('canvas'); c.width = i.width; c.height = i.height; const x = c.getContext('2d'); x.drawImage(i, 0, 0); return x.getImageData(0, 0, i.width, i.height).data; };
      const da = px(ia), dz = px(iz); let n = 0;
      for (let k = 0; k < da.length; k += 4) if (Math.abs(da[k] - dz[k]) + Math.abs(da[k + 1] - dz[k + 1]) + Math.abs(da[k + 2] - dz[k + 2]) > 30) n++;
      return n;
    }, [a.toString('base64'), z.toString('base64')]);
    assert.ok(diff <= 20, `悬停阴影 / 选中描边没被裁（差异像素 ${diff}）`);
    assert.deepEqual(await on.S.pageErrors(), []);
    console.log(`PASS catalog first render: 700 cards content-visibility:auto with estimated intrinsic size, Layout ${on.ms.toFixed(0)}ms vs ${off.ms.toFixed(0)}ms without, scroll to end and back keeps first row, hover / selected not clipped`);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

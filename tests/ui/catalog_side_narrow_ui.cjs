// 1031 作者「目录页这里的边框也没有做好，所有的对话框都测试一下不同屏幕」：编排里边栏只给 3/12、窗口 900–1440 时边栏 176–311px，
// 小标题行（OVERVIEW + 小红书 / B 站）出界、上次 / 下次同步被截成「今天 1…」。真 Chromium 量：边栏里没有东西超出边栏右边、
// 没有被省略号截断的大数字 / 小标题行（最近导入的标题本来就是单行省略号，不算）；默认 4/12 也照量一遍。截图进 LWA_QA_DIR。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 40 });
  const now = Date.now();
  data.items.forEach((it, i) => { const t = new Date(now - (i < 4 ? 0 : 1 + (i % 13)) * 864e5); it.ts = t.toISOString(); it.date = it.ts.slice(0, 10); if (i % 3 === 0) it.source = 'bilibili'; });
  const next = new Date(now + 20 * 3600e3), p2 = n => String(n).padStart(2, '0');
  const iso = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}:00`;
  const plugin = { methods: { getSyncSchedule: { result: { task: 'LinkBrainNightly', enabled: true, freq: 'daily', next_run: iso(next), summary: '每天 18:00', rules: [] } } } };
  const sync = JSON.stringify({ state: 'ready', updated_at: new Date().toISOString(), last_success: new Date(now - 30 * 60e3).toISOString() });
  const shots = [];
  try {
    for (const cols of ['minmax(0,3fr) minmax(0,9fr)', '']) for (const w of [900, 1000, 1100, 1200, 1440]) for (const plat of ['xhs', 'bili']) {
      const tag = `${cols ? '3of12' : '4of12'}-${w}-${plat}`;
      const page = await browser.newPage({ viewport: { width: w, height: 1000 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, plugin, files: { '_archive/sync-status.json': sync } });
      await page.evaluate(() => document.fonts.ready); await S.settle(60);
      if (cols) { await page.evaluate(c => document.querySelector('.lbc-board').style.setProperty('--lbc-board-cols', c), cols); await S.settle(40); }
      if (plat === 'bili') { await page.evaluate(() => document.querySelector('.lbc-mod-sync .lbc-plat-sw button[data-plat="bili"]')?.click()); await S.settle(40); }
      const bad = await page.evaluate(() => {
        const side = document.querySelector('.lbc-side'); if (!side || getComputedStyle(side).display === 'none') return ['no side'];
        const sr = side.getBoundingClientRect(), out = [];
        for (const e of side.querySelectorAll('*')) {
          const b = e.getBoundingClientRect(); if (!b.width || e.closest('.lbc-bars,.lbc-days')) continue;
          const name = String(e.className || e.tagName), txt = (e.textContent || '').trim().slice(0, 16);
          if (b.right > sr.right + 1) out.push(`出界 ${name} +${Math.round(b.right - sr.right)} 「${txt}」`);
          const cs = getComputedStyle(e);
          if (!/lbc-rec-t/.test(name) && e.scrollWidth > e.clientWidth + 1 && (cs.textOverflow === 'ellipsis' || cs.display === 'flex')) out.push(`截断 ${name} ${e.scrollWidth}>${e.clientWidth} 「${txt}」`);
        }
        return out;
      });
      assert.deepEqual(bad, [], `${tag}：${bad.join('；')}`);
      if (w === 900 || w === 1440) shots.push(await S.screenshot(`catalog-side-narrow-${tag}`));
      await page.close();
    }
    console.log('PASS catalog_side_narrow_ui 1031：边栏 3/12 和 4/12 × 900–1440 × 小红书 / B 站，没有出界、没有被截断的小标题行 / 大数字。截图：\n  ' + shots.join('\n  '));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

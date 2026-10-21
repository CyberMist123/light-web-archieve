// 1022 目录页改版第 5 段「编排」（Collection+ DESIGN-SPEC §8，她定：模块可拖动排序、隐藏，布局存插件设置，只桌面生效）· Obsidian 外壳 · 真 Chromium。
//   ① 右上角「编排」胶囊在「管理」左边；点了进编排：边栏每块头上出黑色操作条（⠿ / ↑ ↓ / 隐藏），边栏顶部出托盘；模块本身点不动（不会误折叠 / 误打开）
//   ② 真拖动（⠿ 按住拖到另一块下半区）换顺序；↑ ↓ 换顺序；首块 ↑、末块 ↓ 是灰的
//   ③ 隐藏 → 托盘出「+ 概览」，点了加回来；布局写进插件设置 catalogLayout.side 并 saveSettings
//   ④ 全隐藏 → 退出编排后边栏整列让开、边栏钮也不出、收藏墙铺满；再进编排边栏出来（托盘在）
//   ⑤ 新开一页：按插件设置里的布局排（顺序 + 隐藏）；「恢复默认」= catalogLayout 写回 null
//   ⑥ Esc 退出编排；手机 / 星标页没有「编排」；没插件时照样能排，提示一句「插件没开」
// 截图进 LWA_QA_DIR（catalog-arrange-*.png），和 _handoff/collection-plus-handoff/prototype/ 的编排态对照
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

function fixture() {
  const data = shell.makeCatalogData({ n: 40 });
  const now = Date.now();
  data.items.forEach((it, i) => { const t = new Date(now - (i % 9) * 864e5 - i * 60e3); it.ts = t.toISOString(); it.date = t.toISOString().slice(0, 10); });
  data.usage_month = { month: new Date().toISOString().slice(0, 7), cost_cny: 3.72, by_feature: { 识图: 2.5, 问收藏: 1.22 } };
  const font = f => 'data:font/woff2;base64,' + fs.readFileSync(path.join(shell.ROOT, 'link_brain/assets/fonts', f)).toString('base64');
  const resources = {
    '_archive/fonts/Cinzel-latin-variable.woff2': font('Cinzel-latin-variable.woff2'),
    '_archive/fonts/CormorantGaramond-Italic-latin-variable.woff2': font('CormorantGaramond-Italic-latin-variable.woff2'),
  };
  const schedule = { task: 'LinkBrainNightly', enabled: true, freq: 'daily', next_run: new Date(now + 3 * 3600e3).toISOString().slice(0, 19), summary: '每天 04:00', rules: [] };
  const files = { '_archive/sync-status.json': JSON.stringify({ state: 'ready', updated_at: new Date().toISOString(), last_success: new Date(now - 3600e3).toISOString() }) };
  return { data, resources, schedule, files };
}
const order = page => page.evaluate(() => [...document.querySelectorAll('.lbc-side .lbc-mod')].filter(m => !m.hidden).map(m => m.dataset.mod));
const saved = page => page.evaluate(() => JSON.parse(JSON.stringify(window.plugin?.settings?.catalogLayout ?? null)));
const saves = page => page.evaluate(() => window.calls.filter(c => c[0] === 'saveSettings').length);
const waitSave = async (page, n0) => { for (let i = 0; i < 40; i++) { if (await saves(page) > n0) return; await page.waitForTimeout(50); } throw new Error('400ms 后没有 saveSettings'); };

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const { data, resources, schedule, files } = fixture();
  const plugin = (settings = {}) => ({ settings: { hiddenCats: [], ...settings }, methods: { getSyncSchedule: { result: schedule } } });
  const shots = [];
  try {
    for (const theme of ['light', 'dark']) {
      // 高 1500：编排态三块同屏（Playwright 拖放途中去滚边栏会让 Chromium 取消这次拖动；真人拖到边缘浏览器自己会滚）
      const page = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme, data, resources, plugin: plugin(), files });
      await page.evaluate(() => document.fonts.ready); await S.settle(80);
      // ① 胶囊位置；进编排
      const pos = await page.evaluate(() => { const a = document.querySelector('.lbc-tools .lb-arrange').getBoundingClientRect(), m = document.querySelector('.lbc-tools .lb-manage').getBoundingClientRect(); return { a: a.right, m: m.left, h: a.height, bar: getComputedStyle(document.querySelector('.lbc-mod-bar')).display, tray: getComputedStyle(document.querySelector('.lbc-arrange-tray')).display }; });
      assert.ok(pos.a <= pos.m, `${theme}：编排在管理左边 ${JSON.stringify(pos)}`); assert.equal(Math.round(pos.h), 34);
      assert.equal(pos.bar, 'none'); assert.equal(pos.tray, 'none', '平时不出操作条和托盘');
      assert.deepEqual(await order(page), ['recent', 'sync', 'overview']);
      await page.click('.lbc-tools .lb-arrange'); await S.settle(40);
      const on = await page.evaluate(() => ({ cls: document.querySelector('.lbc-wrap').classList.contains('is-arranging'), pressed: document.querySelector('.lb-arrange').getAttribute('aria-pressed'),
        bars: [...document.querySelectorAll('.lbc-mod-bar')].map(b => getComputedStyle(b).display), tray: getComputedStyle(document.querySelector('.lbc-arrange-tray')).display,
        labPE: getComputedStyle(document.querySelector('.lbc-mod .lbc-lab')).pointerEvents,
        upDisabled: document.querySelector('.lbc-mod-recent [data-act="up"]').disabled, downDisabled: document.querySelector('.lbc-mod-overview [data-act="down"]').disabled,
        midUp: document.querySelector('.lbc-mod-sync [data-act="up"]').disabled }));
      assert.ok(on.cls); assert.equal(on.pressed, 'true'); assert.deepEqual(on.bars, ['flex', 'flex', 'flex']); assert.equal(on.tray, 'flex');
      assert.equal(on.labPE, 'none', '编排时模块本身点不动');
      assert.ok(on.upDisabled && on.downDisabled && !on.midUp, '首块 ↑ / 末块 ↓ 是灰的');
      const fold0 = await page.evaluate(() => document.querySelector('.lbc-mod-recent').classList.contains('is-folded'));
      await page.mouse.click(...await page.evaluate(() => { const r = document.querySelector('.lbc-mod-recent .lbc-lab-en').getBoundingClientRect(); return [r.left + 5, r.top + 5]; }));
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-mod-recent').classList.contains('is-folded')), fold0, '编排时点小标题不折叠');
      shots.push(await S.screenshot(`catalog-arrange-reading-${theme}-1400`));
      if (theme === 'dark') { assert.deepEqual(await S.pageErrors(), []); await page.close(); continue; }

      // ② 真拖动：最近导入 拖到 概览 下半区 → sync, overview, recent
      let n0 = await saves(page);
      // Playwright 正式的 HTML5 拖放（按下 ⠿ → 拖到概览下半区）；页面只认 ⠿ 按下后的那一块
      const ovH = await page.evaluate(() => document.querySelector(".lbc-mod-overview").getBoundingClientRect().height);
      await page.dragAndDrop(".lbc-mod-recent .lbc-mb-h", ".lbc-mod-overview", { targetPosition: { x: 40, y: Math.max(1, ovH - 4) } });
      await S.settle(40);
      assert.deepEqual(await order(page), ['sync', 'overview', 'recent'], '拖到概览下面');
      await waitSave(page, n0);
      assert.deepEqual(await saved(page), { side: [{ id: 'sync', hidden: false }, { id: 'overview', hidden: false }, { id: 'recent', hidden: false }] });
      assert.equal(await page.evaluate(() => document.querySelectorAll('.lbc-mod.is-dragging,.lbc-mod.is-drop-before,.lbc-mod.is-drop-after').length), 0, '拖完不留拖动样式');
      // ↑ ↓
      await page.click('.lbc-mod-recent [data-act="up"]'); await S.settle(20);
      assert.deepEqual(await order(page), ['sync', 'recent', 'overview']);
      await page.click('.lbc-mod-sync [data-act="down"]'); await S.settle(20);
      assert.deepEqual(await order(page), ['recent', 'sync', 'overview']);
      // ③ 隐藏概览 → 托盘出「+ 概览」
      n0 = await saves(page);
      await page.click('.lbc-mod-overview [data-act="hide"]'); await S.settle(20);
      assert.deepEqual(await order(page), ['recent', 'sync']);
      assert.equal(await page.textContent('.lbc-arrange-tray [data-show="overview"]'), '+ 概览');
      assert.ok(await page.evaluate(() => document.querySelector('.lbc-mod-sync [data-act="down"]').disabled), '隐藏后同步成了末块');
      await waitSave(page, n0);
      assert.deepEqual((await saved(page)).side.find(m => m.id === 'overview'), { id: 'overview', hidden: true });
      shots.push(await S.screenshot('catalog-arrange-reading-light-1400-hidden'));
      await page.click('.lbc-arrange-tray [data-show="overview"]'); await S.settle(20);
      assert.deepEqual(await order(page), ['recent', 'sync', 'overview'], '+ 加回来（排在原位置）');
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-mod-overview').classList.contains('is-folded')), false, '加回来的模块是展开的');
      // ④ 全隐藏 → 退出编排后边栏让开、墙铺满
      for (const k of ['recent', 'sync', 'overview']) { await page.click(`.lbc-mod-${k} [data-act="hide"]`); await S.settle(10); }
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.lbc-side')).display), 'block', '编排中全隐藏边栏还在（托盘要用）');
      await page.click('.lbc-arrange-tray [data-act="done"]'); await S.settle(60);
      const empty = await page.evaluate(() => ({ side: getComputedStyle(document.querySelector('.lbc-side')).display, tog: getComputedStyle(document.querySelector('.lbc-sidetoggle')).display,
        grid: document.querySelector('.lbc-board-main').getBoundingClientRect().width - document.querySelector('.lbc-board').getBoundingClientRect().width, arranging: document.querySelector('.lbc-wrap').classList.contains('is-arranging') }));
      assert.equal(empty.arranging, false); assert.equal(empty.side, 'none'); assert.equal(empty.tog, 'none'); assert.ok(Math.abs(empty.grid) <= 1, `墙铺满 ${empty.grid}`);
      shots.push(await S.screenshot('catalog-arrange-reading-light-1400-allhidden'));
      await page.click('.lbc-tools .lb-arrange'); await S.settle(40);
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.lbc-arrange-tray')).display), 'flex', '再进编排边栏出来');
      // 「恢复默认」→ null
      n0 = await saves(page);
      await page.click('.lbc-arrange-tray [data-act="reset"]'); await S.settle(20);
      assert.deepEqual(await order(page), ['recent', 'sync', 'overview']);
      await waitSave(page, n0); assert.equal(await saved(page), null);
      // ⑥ Esc 退出
      await page.keyboard.press('Escape'); await S.settle(20);
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-wrap').classList.contains('is-arranging')), false, 'Esc 退出编排');
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    // ⑤ 新开一页：按插件设置排；实时预览宿主同样能用
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host: 'page-live', kind: 'catalog', theme: 'light', data, resources, files,
        plugin: plugin({ catalogLayout: { side: [{ id: 'overview' }, { id: 'sync', hidden: true }, 'bogus', { id: 'recent' }] } }) });
      await S.settle(80);
      assert.deepEqual(await order(page), ['overview', 'recent'], '读插件设置：顺序 + 隐藏，不认识的丢掉');
      await page.click('.lbc-tools .lb-arrange'); await S.settle(40);
      assert.equal(await page.textContent('.lbc-arrange-tray [data-show="sync"]'), '+ 同步与用量');
      shots.push(await S.screenshot('catalog-arrange-live-light-1400'));
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    // ⑥ 手机 / 星标页没有「编排」；没插件照样能排、提示一句
    {
      const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, files, mobile: true });
      await S.settle(60);
      assert.equal(await page.$('.lb-arrange'), null, '手机没有编排');
      await page.close();
    }
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'starred', theme: 'light', data: { ...data, items: data.items.map(x => ({ ...x, starred: true })) }, resources, files, plugin: plugin() });
      await S.settle(60);
      assert.equal(await page.$('.lb-arrange'), null, '星标页没有编排');
      await page.close();
    }
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, files, plugin: null });
      await S.settle(60);
      await page.click('.lbc-tools .lb-arrange'); await S.settle(30);
      await page.click('.lbc-mod-recent [data-act="down"]'); await S.settle(20);
      assert.deepEqual(await order(page), ['sync', 'recent', 'overview']);
      assert.match(await page.evaluate(() => document.body.textContent), /插件没开：这次的编排有效/);
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS catalog_arrange_ui 1022：编排胶囊在管理左边 · 编排态操作条 + 托盘、模块点不动 · 真拖动 / ↑↓ 换序、首末灰 · 隐藏 / + 加回 · 全隐藏边栏让开墙铺满 · 布局存插件设置并 saveSettings · 新开按设置排 · 恢复默认 = null · Esc 退出 · 手机 / 星标页无编排 · 没插件照样排并提示（截图 ' + shots.map(f => path.basename(f)).join(' ') + '）');
  } finally { await browser.close(); }
})().catch(e => { console.error('FAIL catalog_arrange_ui', e); process.exit(1); });

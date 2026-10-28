// 1027 目录页就地编排（design-1027 §2，她批的结构和交互；外观仍是黑白雕刻）· Obsidian 外壳 · 真 Chromium · 真指针拖动。
//   ① 「编排」在「管理」左边；平时没有操作条 / 托盘；默认版面 = 改版前（边栏 4 格、墙 8 格）
//   ② 进编排：十六块都有小工具条（⠿ · 名字 · A− A+ 字体 · 调整 · ×），平时收着、指着才出来（1028 她：不要图 2 那种黑条）；编排条在墙上面，边栏和墙之间一道可拖的边
//   ③ 真拖：最近导入拖到标题右边 → 并排在吸顶区里；标题拖进边栏「同步」上面 → 标题在边栏里
//   ④ 真拖边：边栏变宽 8 格（48 格吸附；原来 12 格的两格）
//   ⑤ 调整在模块里展开（不弹窗、在模块框里）：最近导入改成 2 条；Aa 样式：卡片间距、界面大小真的变
//   ⑥ × 移除 → ＋ 加回；Esc 退出；布局存进插件设置（saveSettings）；新开一页按存的摆
//   ⑦ 手机 / 插件没开：没有「编排」
// 截图进 LWA_QA_DIR（catalog-arrange-*.png）
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
const saved = page => page.evaluate(() => JSON.parse(JSON.stringify(window.plugin?.settings?.catalogLayout ?? null)));
const saves = page => page.evaluate(() => window.calls.filter(c => c[0] === 'saveSettings').length);
const waitSave = async (page, n0) => { for (let i = 0; i < 40; i++) { if (await saves(page) > n0) return; await page.waitForTimeout(50); } throw new Error('400ms 后没有 saveSettings'); };
const R = (page, sel) => page.evaluate(s => { const r = document.querySelector(s)?.getBoundingClientRect(); return r ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height } : null; }, sel);
async function drag(page, from, to, { steps = 12 } = {}) {
  await page.mouse.move(from.x, from.y); await page.mouse.down();
  await page.mouse.move(from.x + 8, from.y + 8, { steps: 2 });
  await page.mouse.move(to.x, to.y, { steps });
  await page.waitForTimeout(40);
  await page.mouse.up();
}
const center = r => ({ x: r.left + r.width / 2, y: r.top + r.height / 2 });

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const { data, resources, schedule, files } = fixture();
  const plugin = (settings = {}) => ({ settings: { hiddenCats: [], ...settings }, methods: { getSyncSchedule: { result: schedule } } });
  const shots = [];
  try {
    for (const theme of ['light', 'dark']) {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1500 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme, data, resources, plugin: plugin(), files });
      await page.evaluate(() => document.fonts.ready); await S.settle(80);
      // ① 胶囊位置；平时没有操作条 / 托盘；默认比例
      const pos = await page.evaluate(() => { const a = document.querySelector('.lbc-tools .lb-arrange').getBoundingClientRect(), m = document.querySelector('.lbc-tools .lb-manage').getBoundingClientRect(); return { a: a.right, m: m.left, h: a.height, bars: document.querySelectorAll('.lbc-mod-bar').length, tray: getComputedStyle(document.querySelector('.lbc-arrange-tray')).display }; });
      assert.ok(pos.a <= pos.m, `${theme}：编排在管理左边 ${JSON.stringify(pos)}`); assert.equal(Math.round(pos.h), 34);
      assert.equal(pos.bars, 0, '平时不建操作条'); assert.equal(pos.tray, 'none');
      const side0 = await R(page, '.lbc-side'), wall0 = await R(page, '.lbc-board-main');
      const ratio = side0.width / (side0.width + wall0.width);
      assert.ok(ratio > 0.3 && ratio < 0.34, `默认边栏 ≈ 4/12 ${ratio}`);
      // ② 进编排
      await page.click('.lbc-tools .lb-arrange'); await S.settle(60);
      const on = await page.evaluate(() => ({ cls: document.querySelector('.lbc-wrap').classList.contains('is-arranging'),
        bars: document.querySelectorAll('.lbc-mod-bar').length, shown: [...document.querySelectorAll('.lbc-mod-bar')].filter(b => getComputedStyle(b).display === 'flex').length,
        tray: getComputedStyle(document.querySelector('.lbc-arrange-tray')).display,
        trayAbove: document.querySelector('.lbc-arrange-tray').getBoundingClientRect().bottom <= document.querySelector('.lbc-board').getBoundingClientRect().top + 1,
        edges: [...document.querySelectorAll('.lbc-board > .lbc-col-edge')].filter(e => getComputedStyle(e).display === 'block').length,
        labPE: getComputedStyle(document.querySelector('.lbc-mod .lbc-lab')).pointerEvents }));
      assert.ok(on.cls); assert.equal(on.bars, 16, '十六块都有工具条'); assert.equal(on.shown, 0, '平时收着');
      assert.equal(on.tray, 'flex'); assert.ok(on.trayAbove, '托盘在墙上面'); assert.equal(on.edges, 1, '边栏和墙之间一道边'); assert.equal(on.labPE, 'none', '编排时模块本身点不动');
      shots.push(await S.screenshot(`catalog-arrange-1027-${theme}-1400`));
      if (theme === 'dark') { assert.deepEqual(await S.pageErrors(), []); await page.close(); continue; }

      // ③ 真拖：最近导入 → 标题右边
      let n0 = await saves(page);
      const grip = async id => { await page.hover(`.lbc-m-${id}`); await page.waitForTimeout(30); return R(page, `.lbc-m-${id} .lbc-mod-bar .lbc-mb-h`); };
      let title = await R(page, '.lbc-m-title');
      await drag(page, center(await grip('recent')), { x: title.right - title.width * 0.06, y: title.top + title.height / 2 });
      await S.settle(80);
      const beside = await page.evaluate(() => { const t = document.querySelector('.lbc-m-title').getBoundingClientRect(), r = document.querySelector('.lbc-m-recent').getBoundingClientRect();
        return { inTop: !!document.querySelector('.lbc-top .lbc-m-recent'), right: r.left >= t.right - 2, sameRow: document.querySelector('.lbc-m-recent').closest('.lbc-row') === document.querySelector('.lbc-m-title').closest('.lbc-row'),   /* 1028 页头一排里的块底对齐 */ drop: document.querySelector('.lbc-drop-ind')?.hidden, dragging: document.querySelectorAll('.is-dragging').length }; });
      assert.deepEqual(beside, { inTop: true, right: true, sameRow: true, drop: true, dragging: 0 }, '最近导入并排在标题右边（吸顶区里）');
      await waitSave(page, n0);
      const rec = (await saved(page)).modules.find(m => m.id === 'recent');
      assert.deepEqual([rec.x, rec.y, rec.width], [18, 0, 16], '和标题分标题的地方（标题 34 → 18），计数行不动');
      // 模块挪到最前：托盘仍在所有模块上面；往下滚也吸在顶上
      const trayTop = await page.evaluate(() => { const t = document.querySelector('.lbc-arrange-tray').getBoundingClientRect(); return [...document.querySelectorAll('.lbc-m')].every(m => getComputedStyle(m).display === 'none' || m.getBoundingClientRect().top >= t.bottom - 1); });
      assert.ok(trayTop, '托盘在第一个模块上方');
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.lbc-tools')).display), 'none', '编排时「编排 / 管理」不和模块抢位置（托盘里有结束编排）');
      await S.scrollTo(600); await S.settle(60);
      const stuck = await page.evaluate(() => { const sc = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view'); return Math.abs(document.querySelector('.lbc-arrange-tray').getBoundingClientRect().top - sc.getBoundingClientRect().top); });
      assert.ok(stuck <= 1, `编排时托盘吸顶 ${stuck}`);
      await S.scrollTo(0); await S.settle(60);
      shots.push(await S.screenshot('catalog-arrange-1027-beside-title'));
      // 标题 → 边栏「同步」上面
      const sync = await R(page, '.lbc-m-sync');
      await drag(page, center(await grip('title')), { x: sync.left + sync.width / 2, y: sync.top + 12 });
      await S.settle(80);
      assert.ok(await page.evaluate(() => !!document.querySelector('.lbc-side > .lbc-m-title')), '标题进了边栏');
      assert.deepEqual(await page.evaluate(() => [...document.querySelector('.lbc-m-title').parentNode.children].filter(m => m.classList.contains('lbc-m')).map(m => m.dataset.m)), ['title', 'sync', 'token', 'overview']);
      title = await R(page, '.lbc-title');
      assert.ok(title.right <= (await R(page, '.lbc-side')).right + 2, '边栏里的标题不出边栏');
      shots.push(await S.screenshot('catalog-arrange-1027-title-in-side'));
      // ④ 真拖边：边栏宽两格
      const sideA = await R(page, '.lbc-side'), board = await R(page, '.lbc-board');
      const edge = await R(page, '.lbc-board > .lbc-col-edge');
      const ep = { x: edge.left + edge.width / 2, y: edge.top + 60 };   // 边和整排一样高（墙很长）：在看得见的那一截上按
      await drag(page, ep, { x: ep.x + board.width / 48 * 8, y: ep.y }, { steps: 8 });
      await S.settle(120);
      const sideB = await R(page, '.lbc-side');
      assert.ok(sideB.width > sideA.width + board.width / 48 * 6, `边栏变宽 8 格 ${sideA.width} → ${sideB.width}`);
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-board').style.getPropertyValue('--lbc-board-cols')), 'minmax(0,24fr) minmax(0,24fr)');
      // ⑤ 调整：最近导入 2 条（面板在模块框里）
      // 1028：点一下块 = 选中，选中的块工具条一直在（不靠鼠标停在上面）
      await page.click('.lbc-m-recent', { position: { x: 20, y: 20 } }); await S.settle(200);
      assert.ok(await page.evaluate(() => document.querySelector('.lbc-m-recent').classList.contains('is-sel')), '点一下 = 选中');
      await page.click('.lbc-m-recent .lbc-mod-bar [data-act="adjust"]'); await S.settle(40);
      const inBox = await page.evaluate(() => { const p = document.querySelector('.lbc-mp').getBoundingClientRect(), m = document.querySelector('.lbc-m-recent').getBoundingClientRect(); return p.left >= m.left - 1 && p.right <= m.right + 1 && p.top >= m.top - 1; });
      assert.ok(inBox, '调整在模块里展开');
      await page.selectOption('.lbc-mp [data-k="count"]', '2'); await S.settle(40);
      // 1027b：条数 = 列表框高（其余在框里滚）；折着的会自己展开
      assert.equal(await page.evaluate(() => { const ul = document.querySelector('.lbc-m-recent .lbc-rec'), b = ul.getBoundingClientRect().bottom; return [...ul.querySelectorAll('li')].filter(li => li.getBoundingClientRect().bottom <= b + 1).length; }), 2);
      shots.push(await S.screenshot('catalog-arrange-1027-adjust'));
      await page.keyboard.press('Escape'); await S.settle(30);
      assert.equal(await page.$('.lbc-mp'), null, 'Esc 先收起调整');
      // Aa 样式：卡片间距、界面大小
      await page.click('.lbc-arrange-tray [data-act="style"]'); await S.settle(30);
      const gapOf = () => page.evaluate(() => { const c = [...document.querySelectorAll('.lbc-grid-inner > .lbc-col')]; return c.length > 1 ? c[1].getBoundingClientRect().left - c[0].getBoundingClientRect().right : 0; });
      const g0 = await gapOf();
      await page.selectOption('.lbc-arrange-tray [data-theme="gap"]', '32'); await S.settle(150);
      const g1 = await gapOf();
      assert.ok(g1 > g0 + 4, `卡片间距变松 ${g0} → ${g1}`);
      const tok0 = await R(page, '.lbc-m-token');
      await page.selectOption('.lbc-arrange-tray [data-theme="scale"]', '1.2'); await S.settle(150);
      const tok1 = await R(page, '.lbc-m-token');
      assert.ok(tok1.height > tok0.height * 1.1, `界面放大 ${tok0.height} → ${tok1.height}`);
      assert.equal(await page.evaluate(() => document.querySelector('.lb-page-host').style.getPropertyValue('--lb-scale')), '1.2', '共享令牌 --lb-scale（LB.applyTheme 写在本页 host）');
      shots.push(await S.screenshot('catalog-arrange-1027-theme'));
      await page.selectOption('.lbc-arrange-tray [data-theme="scale"]', '1'); await S.settle(80);
      // ⑥ × / ＋
      await page.click('.lbc-m-overview', { position: { x: 20, y: 20 } }); await S.settle(200); await page.click('.lbc-m-overview .lbc-mod-bar [data-act="remove"]'); await S.settle(40);
      assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.lbc-m-overview')).display), 'none');
      await page.click('.lbc-arrange-tray [data-show="overview"]'); await S.settle(40);
      assert.notEqual(await page.evaluate(() => getComputedStyle(document.querySelector('.lbc-m-overview')).display), 'none', '＋ 加回');
      n0 = await saves(page);
      await page.mouse.click(5, 5);
      await page.keyboard.press('Escape'); await S.settle(20); await page.keyboard.press('Escape'); await S.settle(40);   // 第一下取消选中，第二下退出
      assert.equal(await page.evaluate(() => document.querySelector('.lbc-wrap').classList.contains('is-arranging')), false, 'Esc 退出编排');
      await waitSave(page, n0);
      const L = await saved(page);
      assert.equal(L.modules.find(m => m.id === 'recent').options.count, 2); assert.equal(L.theme.gap, 32);
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
      // 新开一页按存的摆
      const page2 = await browser.newPage({ viewport: { width: 1400, height: 1100 } });
      const S2 = await shell.page(page2, { host: 'page-live', kind: 'catalog', theme: 'light', data, resources, files, plugin: plugin({ catalogLayout: L }) });
      await S2.settle(80);
      assert.ok(await page2.evaluate(() => !!document.querySelector('.lbc-side > .lbc-m-title') && !!document.querySelector('.lbc-top .lbc-m-recent')), '新开一页：标题在边栏、最近导入在吸顶区');
      await page2.click('.lbc-m-recent .lbc-fold-sum'); await S2.settle(30);   // 新的一页：最近导入照默认折着
      assert.equal(await page2.evaluate(() => document.querySelector('.lbc-m-recent .lbc-rec').style.getPropertyValue('--lbc-rec-rows')), '2');
      shots.push(await S2.screenshot('catalog-arrange-1027-reopen-live'));
      assert.deepEqual(await S2.pageErrors(), []);
      await page2.close();
    }
    // ⑦ 手机 / 插件没开 / 星标页：没有「编排」
    {
      const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, files, mobile: true });
      await S.settle(60);
      assert.equal(await page.$('.lb-arrange'), null, '手机没有编排');
      await page.close();
    }
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data, resources, files, plugin: null });
      await S.settle(60);
      assert.equal(await page.$('.lb-arrange'), null, '插件没开：只读，没有编排');
      assert.ok(await page.$('.lbc-m-token'), '边栏照默认摆');
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    {
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'starred', theme: 'light', data: { ...data, items: data.items.map(x => ({ ...x, starred: true })) }, resources, files, plugin: plugin() });
      await S.settle(60);
      assert.equal(await page.$('.lb-arrange'), null, '星标页没有编排');
      await page.close();
    }
    console.log('PASS catalog_arrange_ui 1027：编排胶囊在管理左边 · 默认边栏 16/48 · 十六块工具条（指着才出）+ 编排条 + 列边 · 真拖：最近导入并排到标题右边、标题进边栏 · 真拖边 +8 格 · 调整在模块里展开（最近导入 2 条）· Aa 样式间距 / 大小生效（共享令牌）· × / ＋ · Esc · 存进 catalogLayout 并按存的重开 · 手机 / 没插件 / 星标页无编排（截图 ' + shots.map(f => path.basename(f)).join(' ') + '）');
  } finally { await browser.close(); }
})().catch(e => { console.error('FAIL catalog_arrange_ui', e); process.exit(1); });

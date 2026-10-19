// 1020 来源（她定）：目录默认只看她自己的收藏；「来源 ▾」切到 聊天分享 / fable / 项目 / 全部；切换记住；全是她自己的就没有这颗按钮。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 30 });
  for (const i of [0, 1, 2, 3, 4]) data.items[i].src = '聊天分享';
  for (const i of [5, 6]) data.items[i].src = 'fable';
  data.items[7].src = 'ai群聊';
  const cards = page => page.evaluate(() => document.querySelectorAll('.lbc-card').length);
  const chip = page => page.evaluate(() => { const c = document.querySelector('.lbc-src'); return c && { text: c.textContent, active: c.classList.contains('is-active') }; });
  const menu = page => page.evaluate(() => [...document.querySelectorAll('.menu .menu-item-title, .lbc-menu .lbc-menu-item')].map(e => e.textContent.replace(/^✓ /, '')));
  const pick = async (page, S, label) => {
    await page.click('.lbc-src'); await S.settle();
    await page.evaluate(l => [...document.querySelectorAll('.menu .menu-item, .lbc-menu .lbc-menu-item')].find(e => e.textContent.replace(/^✓ /, '').startsWith(l)).click(), label);
    await S.settle();
  };
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', data });
    assert.equal(await cards(page), 22, '默认只看她自己的收藏');
    assert.deepEqual(await chip(page), { text: '我的收藏 ▾', active: false });
    await page.click('.lbc-src'); await S.settle();
    assert.deepEqual(await menu(page), ['我的收藏（22）', '全部（30）', '聊天分享（5）', 'fable（2）', 'ai群聊（1）']);
    await page.keyboard.press('Escape'); await S.settle();
    await pick(page, S, '聊天分享');
    assert.equal(await cards(page), 5);
    assert.deepEqual(await chip(page), { text: '聊天分享 ▾', active: true });
    const shot = await S.screenshot('catalog_source_chat');
    await pick(page, S, '全部');
    assert.equal(await cards(page), 30);
    await pick(page, S, 'ai群聊');
    assert.equal(await cards(page), 1);
    assert.deepEqual(await S.pageErrors(), []);

    // 全是她自己的：没有这颗按钮，全显示
    const mine = shell.makeCatalogData({ n: 12 });
    const page2 = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const S2 = await shell.page(page2, { host: 'page-reading', kind: 'catalog', data: mine });
    assert.equal(await cards(page2), 12);
    assert.equal(await chip(page2), null);
    assert.deepEqual(await S2.pageErrors(), []);
    console.log('PASS catalog source (1020): default = 我的收藏 only, 来源 ▾ lists 聊天分享 / fable / 项目 with counts, switching filters + highlights, no chip when all are hers; screenshot ' + shot);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

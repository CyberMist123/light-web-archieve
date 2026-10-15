// 1015：catalog-data.json 拆出检索索引（_archive/catalog-search-index.json）。真页面里核：
// ① 目录首开（含空闲预热）不读索引；② 搜一个只在正文里出现的词：读一次索引、正文命中的那篇出现在结果里；
// ③ 再搜别的词不再读；④ 没有索引文件的旧数据（items 自带 search_fields）照常搜到、不去读索引。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');
const IDX = '_archive/catalog-search-index.json';

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const legacy = shell.makeCatalogData({ n: 40 });
  legacy.items[7].search_fields.body = '只在正文里才有的词：蓝莓司康';
  const split = JSON.parse(JSON.stringify(legacy));
  const index = {};
  for (const it of split.items) { index[it.id] = { search_fields: it.search_fields, pinyin: '' }; delete it.search_fields; }
  split.search_index = 'catalog-search-index.json';
  const titles = page => page.evaluate(() => [...document.querySelectorAll('.lbc-card .lbc-ctitle')].map(e => e.textContent));
  const search = async (page, S, q) => { await page.fill('.lbc-search', q); await page.press('.lbc-search', 'Enter'); await page.waitForTimeout(400); await S.settle(); };
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', data: split, files: { [IDX]: JSON.stringify({ built_at: split.built_at, items: index }) } });
    await page.waitForTimeout(800);   // 让空闲预热跑完
    assert.equal(await page.evaluate(p => window.reads[p] || 0, IDX), 0, '首开不读检索索引');
    assert.equal((await titles(page)).length, 40);
    await search(page, S, '蓝莓司康');
    assert.equal(await page.evaluate(p => window.reads[p] || 0, IDX), 1, '第一次搜索读一次');
    const hit = await titles(page);
    assert.deepEqual(hit, [legacy.items[7].title], '只有正文命中的那篇：' + hit.join('|'));
    const shot = await S.screenshot('catalog_search_index_hit');
    await search(page, S, '悉尼');
    assert.equal(await page.evaluate(p => window.reads[p] || 0, IDX), 1, '再搜不重读');
    assert.deepEqual(await S.pageErrors(), []);

    const page2 = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const S2 = await shell.page(page2, { host: 'page-reading', kind: 'catalog', data: legacy });
    await search(page2, S2, '蓝莓司康');
    assert.ok((await titles(page2)).includes(legacy.items[7].title), '旧数据照常搜到');
    assert.equal(await page2.evaluate(p => window.reads[p] || 0, IDX), 0, '旧数据不读索引');
    assert.deepEqual(await S2.pageErrors(), []);
    console.log('PASS catalog search index: not read on first open, read once on first search, body hit shown, legacy data unaffected; screenshot ' + shot);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

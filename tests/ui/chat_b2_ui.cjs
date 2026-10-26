// 1015 第二批「chat」车：问收藏页真浏览器截图 + 几何（套 Obsidian 外壳，合成数据，不读真 vault）。
//   目录卡（宽 / 窄 / 暗色）、单条展开后「已展开 ↓」、1150 宽左栏不压对话列、收起后「☰ 目录」放回、窄窗「☰ 目录」弹出层、
//   mermaid 视口（＋ / 拖动 / 放大看）、「存一条判断」Enter 存 + 作者 + 标题行 ×。截图进 LWA_QA_DIR。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const pluginInit = (p, app, W) => {
  const lb = W.lb = { asks: [] };
  p.settings = { models: [{ name: 'DeepSeek' }], activeModel: 'DeepSeek', hiddenCats: [] };
  // mermaid 代码块画成 div.mermaid > svg（Obsidian 的样子），其余走 __miniMd
  p.renderMarkdownScoped = async (md, el) => {
    const m = /```mermaid\n([\s\S]*?)```/.exec(md);
    if (m) {
      const box = document.createElement('div'); box.className = 'mermaid';
      box.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="620" height="260" viewBox="0 0 620 260"><rect x="10" y="20" width="160" height="60" rx="8" fill="#dbe4f3" stroke="#6b7c99"/><text x="90" y="55" text-anchor="middle" font-size="14">收藏</text><rect x="230" y="20" width="160" height="60" rx="8" fill="#e6f0dc" stroke="#6b8c55"/><text x="310" y="55" text-anchor="middle" font-size="14">检索</text><rect x="450" y="20" width="160" height="60" rx="8" fill="#f3e3d3" stroke="#a07040"/><text x="530" y="55" text-anchor="middle" font-size="14">目录</text><path d="M170 50H230M390 50H450" stroke="#555" stroke-width="2"/><rect x="230" y="170" width="160" height="60" rx="8" fill="#eee" stroke="#777"/><text x="310" y="205" text-anchor="middle" font-size="14">展开</text><path d="M530 80V200H390" stroke="#555" stroke-width="2" fill="none"/></svg>';
      el.appendChild(box);
      const rest = md.replace(m[0], '');
      const h = await W.__miniMd.render(rest, el);
      return { dispose() { h.dispose(); } };
    }
    const h = await W.__miniMd.render(md, el);
    return { dispose() { h.dispose(); } };
  };
  p.archiveSourceState = () => ({ reader: false, compare: false });
  p.openSetupPage = () => {};
  p.modelState = () => ({ usable: true });
  p.warmAnswerWorker = () => false;
  p.stopArchiveAnswer = () => 1;
  const src = (id, n) => ({ id, citation: n, title: '来源标题 ' + id, note: 'Web/' + id + '.md', tier: 'primary', excerpts: [{ field: 'comments', text: id + ' 评论区说要多放一勺醋', comment_labels: ['c3'] }] });
  const TOC = [
    { id: 'a', title: '辣味鱼片（家常版，十分钟出锅）', author: '小厨房日记', hit: '评论区：郫县豆瓣先炒出红油再下鱼片', source_type: 'comments' },
    { id: 'b', title: '麻辣香锅', author: '周末做饭', hit: '正文：花椒先用小火炸香', source_type: ['body', 'ocr'], price: '$5.5', where: 'Coles 调料区' },
    { id: 'c', title: '水煮牛肉', author: '川菜研究所', hit: '视频里讲牛肉要先码味', source_type: 'transcript' },
    { id: 'd', title: '老干妈炒饭', author: '一人食', hit: '图片文字：隔夜饭更好炒', source_type: 'ocr' },
    { id: 'e', title: '澳洲超市能买到的辣椒酱', author: '悉尼生活', hit: '评论区 c12：Woolworths 也有', source_type: 'comments' },
  ];
  p.answerArchive = req => {
    lb.asks.push({ q: req.question, turnId: req.turnId, expandIds: req.expandIds });
    if (req.expandIds) return Promise.resolve({ status: 'ok', markdown: '## ' + req.question.slice(0, 20) + '\n\n- 鱼片用蛋清淀粉抓匀 [来源1]\n- 评论区补充：豆瓣要剁碎 [来源1]', sources: [src(req.expandIds[0], 1)], related: [] });
    if (/图/.test(req.question)) return Promise.resolve({ status: 'ok', mode: 'direct', markdown: '流程如下：\n\n```mermaid\nflowchart LR\nA-->B\n```\n\n图例：实线 = 数据流 [来源1]', sources: [src('m', 1)], related: [] });
    return Promise.resolve({ status: 'ok', mode: 'toc', turn_id: 'T1', markdown: '收藏里的辣味菜（5 篇）', toc: TOC, coverage_note: '共检到 9 篇，展示 5', suggest: '搜「川菜 家常」',
      source_ids: TOC.map(t => t.id), sources: TOC.slice(0, 3).map((t, i) => src(t.id, i + 1)), related: [] });
  };
};

async function openChat(browser, { width = 1440, height = 900, theme = 'light' } = {}) {
  const page = await browser.newPage({ viewport: { width, height } });
  const S = await shell.page(page, { host: 'page-reading', kind: 'chat', theme, plugin: {}, pluginInit,
    data: { built_at: '2026-10-08T10:00:00+10:00', items: [] }, files: { '_archive/chat-session.json': '{"turns":[]}', '_archive/chat-archive.json': '{"entries":[]}' } });
  await S.settle(60);
  return { page, S };
}
const ask = async (page, S, text, wait = 120) => { await page.click('.lbchat-search'); await page.keyboard.type(text); await page.keyboard.press('Enter'); await S.settle(wait); };
const rect = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); if (!e || !e.offsetParent) return null; const r = e.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height }; }, sel);

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const shots = [];
  try {
    // ── 宽窗：目录卡 + 左栏目录（1 问也有） ──
    let { page, S } = await openChat(browser);
    await ask(page, S, '我要吃辣的');
    assert.equal(await page.locator('.lbchat-tocard-item').count(), 5);
    const rail = await rect(page, '.lbchat-toc');
    assert.ok(rail, '1 问（目录型回答）宽窗就有左栏目录');
    const body = await rect(page, '.lbchat-answer');
    assert.ok(rail.r <= body.l + 1, `左栏不压对话列 rail.r=${rail.r} body.l=${body.l}`);
    shots.push(await S.screenshot('b2-toc-card-wide'));
    // 单条展开 → 新一问「展开 · 1 条来源」，第一条变「已展开 ↓」
    await page.locator('.lbchat-tocard-item').first().locator('.lbchat-tocard-expand').click();
    await S.settle(150);
    const ask1 = await page.evaluate(() => window.lb.asks[1]);
    assert.equal(ask1.turnId, 'T1'); assert.deepEqual(ask1.expandIds, ['a']);
    assert.equal(await page.locator('.lbchat-tocard-expand').first().textContent(), '已展开 ↓');
    shots.push(await S.screenshot('b2-expanded-one'));
    // 点「已展开 ↓」跳回展开那一段
    await page.locator('.lbchat-answer').first().scrollIntoViewIfNeeded();
    await page.locator('.lbchat-tocard-expand').first().click(); await S.settle(40);
    // 1026 目录改成 floating-toc 式，没有收起 / 「目录」按钮了（新样子见 tests/test_chat_toc_f5.cjs）
    await page.close();

    // ── 1150 宽：左栏 + 对话列让位，不重叠 ──
    ({ page, S } = await openChat(browser, { width: 1300 }));
    await ask(page, S, '我要吃辣的');
    const rail2 = await rect(page, '.lbchat-toc'), body2 = await rect(page, '.lbchat-answer');
    assert.ok(await page.evaluate(() => document.querySelector('.lbchat-bodywrap').classList.contains('is-tight')), '1080–1242 档');
    assert.ok(rail2 && body2 && rail2.r <= body2.l + 1, JSON.stringify({ rail2, body2 }));
    shots.push(await S.screenshot('b2-toc-1150'));
    await page.close();

    // ── 窄窗：目录卡不横向溢出（1026 起窄窗也是左边一列短横线，没有「☰ 目录」弹出层，见 tests/test_chat_toc_f5.cjs）──
    ({ page, S } = await openChat(browser, { width: 820, height: 900 }));
    await ask(page, S, '我要吃辣的');
    const noH = await page.evaluate(() => document.querySelector('.lbchat-body').scrollWidth <= document.querySelector('.lbchat-body').clientWidth + 1);
    assert.ok(noH, '目录卡不横向溢出');
    shots.push(await S.screenshot('b2-toc-narrow'));
    await page.close();

    // ── 暗色 ──
    ({ page, S } = await openChat(browser, { theme: 'dark' }));
    await ask(page, S, '我要吃辣的');
    shots.push(await S.screenshot('b2-toc-card-dark'));
    await page.close();

    // ── mermaid 视口 ──
    ({ page, S } = await openChat(browser));
    await ask(page, S, '画个流程图');
    const vp = page.locator('.lbchat-mmd');
    assert.equal(await vp.count(), 1);
    await vp.hover(); await S.settle(30);
    shots.push(await S.screenshot('b2-mermaid'));
    await vp.locator('.lbchat-mmd-btn', { hasText: '＋' }).click();
    await vp.locator('.lbchat-mmd-btn', { hasText: '＋' }).click();
    const box = await vp.boundingBox();
    await page.mouse.move(box.x + 200, box.y + 120); await page.mouse.down(); await page.mouse.move(box.x + 120, box.y + 80, { steps: 5 }); await page.mouse.up();
    const tf = await page.evaluate(() => document.querySelector('.lbchat-mmd-stage').style.transform);
    assert.ok(/scale\(1\.56/.test(tf) && /translate\(-80px, -40px\)/.test(tf), tf);
    shots.push(await S.screenshot('b2-mermaid-zoomed'));
    await page.dblclick('.lbchat-mmd-stage'); await S.settle(20);
    assert.ok(/scale\(1\)/.test(await page.evaluate(() => document.querySelector('.lbchat-mmd-stage').style.transform)));
    await vp.locator('.lbchat-mmd-btn', { hasText: '放大看' }).click(); await S.settle(30);
    const full = await rect(page, '.lbchat-mmd.is-full');
    assert.ok(full && full.w > 1300, JSON.stringify(full));
    shots.push(await S.screenshot('b2-mermaid-full'));
    await page.keyboard.press('Escape'); await S.settle(20);
    assert.equal(await page.locator('.lbchat-mmd.is-full').count(), 0, 'Esc 退出放大');
    await page.close();

    // ── 存一条判断：Enter 存 + 作者 + 标题行 × ──
    ({ page, S } = await openChat(browser));
    await page.locator('.lbchat-tab', { hasText: '已保存' }).click(); await S.settle(30);
    await page.fill('.lbchat-arc-author', '小厨房日记');
    await page.click('.lbchat-arc-input'); await page.keyboard.type('辣味鱼片那篇的豆瓣用量偏多'); await page.keyboard.press('Enter'); await S.settle(60);
    await page.keyboard.type('ib 机不适合'); await page.keyboard.press('Enter'); await S.settle(60);
    assert.equal(await page.locator('.lbchat-arc-item').count(), 2);
    assert.equal(await page.locator('.lbchat-arc-who').first().textContent(), '小厨房日记');
    await page.locator('.lbchat-arc-item').first().hover(); await S.settle(20);
    shots.push(await S.screenshot('b2-judgement'));
    await page.locator('.lbchat-arc-item').first().locator('.lbchat-arc-head .lbchat-arc-del').click(); await S.settle(60);
    assert.equal(await page.locator('.lbchat-arc-item').count(), 1);
    await page.close();
  } finally { await browser.close(); }
  console.log('PASS chat b2 ui: 目录卡宽 / 1150 / 窄 / 暗色，单条展开 → 已展开 ↓，左栏不压对话列、收起可恢复、窄窗弹出层，mermaid ＋ / 拖动 / 放大看 / Esc，判断 Enter 存 + 作者 + × → ' + shots.join(' , '));
})().catch(e => { console.error(e); process.exit(1); });

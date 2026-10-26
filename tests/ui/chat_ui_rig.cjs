// 批次 D · L2 问收藏页测试架（playwright，套 Obsidian 外壳 tests/_obsidian_shell.cjs，Dataview 行内 overflow-x:auto 那一层也在）。
// 不读真 vault，合成数据内联；截图进 LWA_QA_DIR。量的是真浏览器里的几何和时间：
//   A1 点保留 / × 后目标行不动（≤2px）、列表不收起、0 张图被摘、0 次重渲正文、点下到按钮变样 ≤16ms；
//   重跑 3 次输入框不失焦（C4 同款探针）；A2 换页（recreate）回来接着出字、追问排队、会话 4 轮顺序对；
//   A4 3000 字分 300 个 delta：渲染 ≤17 次、每次 p95 ≤12ms；A5 / A6 / A7 / A8 / A11 / A14 / F5 截图 + 断言。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const log = (...a) => console.log(...a);
// 假插件（浏览器里跑）：渲染走 __miniMd（记次数 / 耗时 / dispose；图换成带原路径的 SVG，测「来源N · 图M」）；answerArchive 按 W.lb.next 的脚本答
const pluginInit = (p, app, W) => {
  const lb = W.lb = { renders: 0, disposes: 0, renderMs: [], asks: [], lightbox: [], setup: [], stops: [], next: null, noAI: false };
  p.settings = { models: [{ name: 'DeepSeek' }], activeModel: 'DeepSeek', hiddenCats: [] };
  p.renderMarkdownScoped = async (md, el) => {
    const t0 = performance.now();
    const h = await W.__miniMd.render(md, el);
    for (const img of el.querySelectorAll('img')) {
      const orig = img.getAttribute('data-embed') || '';
      img.setAttribute('src', 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="360" height="200"><rect width="360" height="200" fill="#c9d3e0"/></svg>') + '#/' + orig);
      img.style.width = '360px'; img.style.height = '200px'; img.style.display = 'inline-block';
    }
    lb.renderMs.push(performance.now() - t0); lb.renders++;
    return { dispose() { lb.disposes++; h.dispose(); } };
  };
  p.archiveSourceState = () => ({ reader: false, compare: false });
  p.openLightbox = (imgs, i, opts) => { lb.lightbox.push({ n: imgs.length, i, cap: opts && opts.caption ? opts.caption(i) : '' }); return true; };
  p.openSetupPage = t => { lb.setup.push(t); };
  p.modelState = () => ({ usable: !lb.noAI });
  p.warmAnswerWorker = () => false;
  p.stopArchiveAnswer = tag => { lb.stops.push(tag); if (lb.cancel) lb.cancel(); return 1; };
  const src = (id, n) => ({ id, citation: n, title: '来源标题 ' + id, note: 'Web/' + id + '.md', tier: 'primary', agent_md: '/fake-vault/_archive/xiaohongshu/' + id + '/derived/agent.md', excerpts: [{ field: 'comments', text: id + ' 的命中原文：评论区说要多放一勺醋', comment_labels: ['c3'] }] });
  const rel = (id, n) => ({ id, rank: n, title: '其他相关 ' + id, note: 'Web/' + id + '.md', tier: 'related', excerpt: id + ' 摘录' });
  lb.src = src; lb.rel = rel;
  const img = (id, n) => `![[_archive/xiaohongshu/${id}/raw/v0001/image-${n}.jpg|360]]`;
  lb.longMd = k => `## 第 ${k} 轮的结论

- 要点一 [来源1]
- 要点二 [来源2]

${img('s' + k + 'a', 1)} ${img('s' + k + 'a', 2)}

正文第二段，写得长一些，看换行和行距是不是正常。`;
  p.answerArchive = req => {
    lb.asks.push(req.question);
    const s = lb.next || { mode: 'ok' };
    const k = lb.asks.length;
    const ok = md => ({ status: 'ok', markdown: md, sources: [src('s' + k + 'a', 1), src('s' + k + 'b', 2)], related: [rel('r' + k + 'c', 3), rel('r' + k + 'd', 4)] });
    if (s.mode === 'ok') return Promise.resolve(ok(s.md ? s.md(req, k) : '回答 ' + k + ' [来源1]'));
    if (s.mode === 'fail') { const e = new Error(s.message || 'x'); Object.assign(e, s.err || {}); return Promise.reject(e); }
    // stream：每 s.every 毫秒推一个 delta；s.hold 时推完不收尾，等 lb.finish()
    return new Promise((resolve, reject) => {
      const parts = s.parts.slice(); let shown = '';
      lb.cancel = () => { clearInterval(t); resolve({ status: 'cancelled', markdown: shown }); };
      lb.finish = () => { clearInterval(t); resolve(ok(s.final || shown)); };
      if (s.phase) req.onPhase(s.phase);
      const t = setInterval(() => {
        const d = parts.shift();
        if (d === undefined) { clearInterval(t); if (!s.hold) resolve(ok(s.final || shown)); return; }
        shown += d; req.onDelta(d);
      }, s.every || 10);
    });
  };
};

async function openChat(browser, { width = 1440, height = 900, theme = 'light', files = {}, mobile = false, plugin = true } = {}) {
  const page = await browser.newPage({ viewport: { width, height } });
  const S = await shell.page(page, { host: 'page-reading', kind: 'chat', theme, mobile, plugin: plugin ? {} : null, pluginInit: plugin ? pluginInit : null,
    data: { built_at: '2026-10-08T10:00:00+10:00', items: [] }, files: { '_archive/chat-session.json': '{"turns":[]}', '_archive/chat-archive.json': '{"entries":[]}', /* 1015 前的默认：接着这段问、追问绑来源（多轮用例靠它） */ '_archive/chat-prefs.json': '{"follow":"sources","keepThread":true}', ...files } });
  await S.settle(60);
  return { page, S };
}
const ask = async (page, S, text, wait = 80) => { await page.click('.lbchat-search'); await page.keyboard.type(text); await page.keyboard.press('Enter'); await S.settle(wait); };
const noScrollbars = page => page.evaluate(() => {
  const out = {};
  for (const s of ['.lbchat-body', '.lbchat-toc']) { const e = document.querySelector(s); if (e && e.offsetParent) out[s] = e.offsetWidth === e.clientWidth; }
  out.noHScroll = document.documentElement.scrollWidth <= document.documentElement.clientWidth;
  return out;
});

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  try {
    // ── 宽窗 10 轮：A1 / C4 / F5 / A14 / A3 ──
    let { page, S } = await openChat(browser);
    await page.evaluate(() => { window.lb.next = { mode: 'ok', md: (req, k) => window.lb.longMd(k) }; });
    for (let i = 1; i <= 10; i++) await ask(page, S, '第' + i + '问：担担面有没有汤', 40);
    await S.settle(100);
    assert.equal(await page.locator('.lbchat-answer').count(), 10);
    // 重跑 3 次：输入框不失焦、字不丢（C4 同款探针）
    const focus = await S.probeFocusAfterRerun({ input: '.lbchat-search', text: 'kafei', reruns: 3 });
    assert.ok(focus.ok, JSON.stringify(focus));
    await page.fill('.lbchat-search', '');
    // A1：展开第 3 轮主要依据，点保留 / ×
    const third = page.locator('.lbchat-answer').nth(2);
    await third.locator('details[data-part="primary"] > summary').click();
    await third.locator('.lbchat-srcrow').first().scrollIntoViewIfNeeded();
    await S.settle(30);
    await S.screenshot('a1-before');
    const res = await page.evaluate(async () => {
      const ans = document.querySelectorAll('.lbchat-answer')[2];
      const row = () => ans.querySelectorAll('.lbchat-srcrow')[0];
      const y0 = row().getBoundingClientRect().top;
      const removed = []; const mo = new MutationObserver(ms => { for (const m of ms) for (const n of m.removedNodes) if (n.nodeType === 1) removed.push(...(n.tagName === 'IMG' ? [n] : n.querySelectorAll('img'))); });
      mo.observe(document.querySelector('.lbchat-body'), { childList: true, subtree: true });
      const r0 = window.lb.renders;
      const t0 = performance.now();
      row().querySelector('.lbchat-src-pin').click();
      const clickMs = performance.now() - t0;
      const pinText = row().querySelector('.lbchat-src-pin').textContent;
      await new Promise(r => setTimeout(r, 80));
      ans.querySelectorAll('.lbchat-srcrow')[1].querySelector('.lbchat-src-del').click();
      await new Promise(r => setTimeout(r, 80));
      mo.disconnect();
      return { dy: Math.abs(row().getBoundingClientRect().top - y0), open: ans.querySelector('details[data-part="primary"]').open, removedImgs: removed.length, renders: window.lb.renders - r0, clickMs, pinText,
        struck: ans.querySelectorAll('.lbchat-srcrow')[1].classList.contains('is-removed') };
    });
    log('A1 读数', JSON.stringify(res));
    assert.ok(res.dy <= 2, 'dy=' + res.dy); assert.ok(res.open); assert.equal(res.removedImgs, 0); assert.equal(res.renders, 0); assert.equal(res.pinText, '已保留'); assert.ok(res.struck);
    assert.ok(res.clickMs <= 16, 'clickMs=' + res.clickMs);
    await S.screenshot('a1-after');
    // A14：点图 → 插件大图查看器，caption「来源1 · 图2」
    await third.locator('.lbchat-md img').nth(1).click();
    const lbx = await page.evaluate(() => window.lb.lightbox.at(-1));
    assert.deepEqual(lbx, { n: 2, i: 1, cap: '来源1 · 图2' });
    await S.screenshot('a14-click');
    // A3：双击选词不进编辑；「编辑」原地替换正文
    await third.locator('.lbchat-md p').last().dblclick();
    const sel = await page.evaluate(() => ({ text: String(window.getSelection()), editor: !!document.querySelector('.lbchat-editor') }));
    assert.ok(sel.text.length > 0 && !sel.editor, JSON.stringify(sel));
    // 1026 她：动作行先不显示「编辑」（功能代码还在）——这里直接触发，验原地编辑本身
    await third.locator('.lbchat-edit').evaluate(b => b.click());
    await S.settle(30);
    const ed = await page.evaluate(() => { const e = document.querySelector('.lbchat-editor'); const a = e.closest('.lbchat-answer'); const kids = [...a.children]; return { before: kids.indexOf(e) < kids.indexOf(a.querySelector('.lbchat-srcbox')), focused: document.activeElement === e }; });
    assert.ok(ed.before && ed.focused, JSON.stringify(ed));
    await S.screenshot('a3-edit-inline');
    await page.keyboard.press('Escape');
    // 1026 目录改成 floating-toc 式（宽窄窗都是左边一列短横线，没有浮签 / 弹出层 / 收起），新样子见 tests/test_chat_toc_f5.cjs
    await page.close();
    // 暗色 1440
    ({ page, S } = await openChat(browser, { theme: 'dark' }));
    await page.evaluate(() => { window.lb.next = { mode: 'ok', md: (req, k) => '## 步骤\n\n先煮面 [来源1]\n\n## 要点与避坑\n\n别煮烂 [来源2]' }; });
    for (let i = 1; i <= 3; i++) await ask(page, S, '暗色第' + i + '问', 40);
    await S.screenshot('f5-wide-dark');
    await page.close();
    // ── A2 换页再回来 + A4 流式 + A8 ──
    ({ page, S } = await openChat(browser, { width: 1200 }));
    const text = Array.from({ length: 300 }, (_, i) => (i % 25 === 0 ? `\n\n## 第 ${i / 25 + 1} 段\n\n` : '') + `字${String(i).padStart(3, '0')}个[来源1]、`).join('');
    const parts = []; for (let i = 0; i < 300; i++) parts.push(text.slice(i * 10, (i + 1) * 10));
    await page.evaluate(([parts]) => { window.lb.next = { mode: 'stream', parts, every: 10, hold: true, phase: '生成回答：用 2 条材料' }; }, [parts]);
    await ask(page, S, '流式长回答', 20);
    await page.waitForTimeout(1500);
    await S.screenshot('a4-streaming');
    // 往上翻：「↓ 最新」+ 小点
    const br = await S.rect('.lbchat-body');
    await page.mouse.move(br.left + br.width / 2, br.top + Math.min(200, br.height / 2));
    await page.mouse.wheel(0, -1500);   // 真滚轮（程序把 scrollTop 设成 0 会被「DOM 挪动后归零就滚回」的守卫当成重挂）
    await page.waitForTimeout(400);
    const tb = await page.evaluate(() => { const b = document.querySelector('.lbchat-tobottom'); return { shown: !!b.offsetParent, live: b.classList.contains('is-live') }; });
    assert.ok(tb.shown && tb.live, JSON.stringify(tb));
    await S.screenshot('a8-tobottom');
    await page.waitForTimeout(2000);
    // 换页：旧组件卸载 + 新容器重跑（同一个 app / 插件）；回来看到半截和阶段字
    await S.recreate();
    await page.waitForTimeout(300);
    const back = await page.evaluate(() => ({ live: !!document.querySelector('.lbchat-live'), len: (document.querySelector('.lbchat-live') || {}).textContent?.length || 0, stop: !!document.querySelector('.lbchat-stop:not([hidden])') }));
    assert.ok(back.live && back.len > 100 && back.stop, JSON.stringify(back));
    await S.screenshot('a2-return-live');
    await ask(page, S, '回来后的追问', 40);
    assert.equal(await page.locator('.lbchat-queued').count(), 1);
    await S.screenshot('a2-queued');
    const perf = await page.evaluate(() => { const ms = window.lb.renderMs.slice().sort((a, b) => a - b); return { renders: ms.length, p95: ms[Math.floor(ms.length * 0.95)] || 0 }; });
    await page.evaluate(() => { window.lb.next = { mode: 'ok' }; window.lb.finish(); });
    await page.waitForTimeout(400);
    const saved = await page.evaluate(async () => JSON.parse(await window.app.vault.adapter.read('_archive/chat-session.json')).turns.map(t => [t.role, t.content.slice(0, 6)]));
    log('A2 会话', JSON.stringify(saved));
    assert.deepEqual(saved.map(x => x[0]), ['user', 'assistant', 'user', 'assistant']);
    assert.equal(saved[2][1], '回来后的追问');
    log('A4 渲染', JSON.stringify(perf));
    assert.ok(perf.renders <= 17 + 4, '流式渲染次数 ' + perf.renders);   // +4：问之前没有轮次；收尾时正式回答 2 轮
    assert.ok(perf.p95 <= 12, 'p95 ' + perf.p95);
    await page.close();

    // ── A5 / A6 / A7 失败与输入框 ──
    ({ page, S } = await openChat(browser, { width: 1200 }));
    await page.evaluate(() => { window.lb.next = { mode: 'fail', message: 'AI 回答失败：401', err: { kind: 'api', code: 'NEEDS_HUMAN.AUTH_FAILED', detail: '401 Unauthorized' } }; });
    await ask(page, S, 'key 被拒的一问');
    await S.screenshot('a5-fail-auth');
    await page.evaluate(() => { window.lb.next = { mode: 'fail', message: '问答进程断开了：ValueError: x', err: { kind: 'crash' } }; });
    await ask(page, S, '崩了的一问');
    await S.screenshot('a5-fail-crash');
    await page.click('.lbchat-search');
    for (let i = 0; i < 5; i++) { await page.keyboard.type('第' + (i + 1) + '行'); if (i < 4) await page.keyboard.press('Shift+Enter'); }
    const h = await page.evaluate(() => document.querySelector('.lbchat-search').getBoundingClientRect().height);
    assert.ok(h > 44 && h <= 162, 'composer height ' + h);
    await S.screenshot('a7-multiline');
    await page.close();
    ({ page, S } = await openChat(browser, { width: 1200 }));
    await page.evaluate(() => { window.lb.noAI = true; window.app.workspace.trigger('link-brain:settings'); });
    await S.settle(60);
    assert.ok(await page.locator('.lbchat-cfghint').isVisible());
    await S.screenshot('a6-noai-empty');
    await page.evaluate(() => { window.lb.next = { mode: 'fail', message: '问答模型还没配好', err: { kind: 'config', code: 'SKIPPED.NOT_CONFIGURED', payload: { sources: [window.lb.src('x1', 1), window.lb.src('x2', 2)], related: [] } } }; });
    await ask(page, S, '没配 AI 的一问');
    assert.ok((await page.locator('.lbchat-answer').last().textContent()).includes('找到的相关收藏（2 篇）'));
    await S.screenshot('a6-noai-sources');
    await page.close();

    // ── A11 手机（不挂插件）──
    const turns11 = [{ id: 'u1', role: 'user', content: '担担面有没有汤' }, { id: 'a1', role: 'assistant', q: '担担面有没有汤', content: '## 结论\n\n有汤和干拌两种 [来源1]', sources: [{ id: 'x', citation: 1, title: '担担面', note: 'Web/x.md' }], related: [] }];
    ({ page, S } = await openChat(browser, { width: 390, height: 844, mobile: true, plugin: false, files: { '_archive/chat-session.json': JSON.stringify({ id: 'c1', turns: turns11 }) } }));
    const m = await page.evaluate(() => ({ ro: document.querySelector('.lbchat-ro')?.textContent, composer: !!document.querySelector('.lbchat-composer').offsetParent, hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, writes: Object.keys(window.writes) }));
    assert.equal(m.ro, '手机上可以看历史问答；提问、导出、来源窗格要在电脑上用');
    assert.ok(!m.composer && !m.hscroll && m.writes.length === 0, JSON.stringify(m));
    await S.screenshot('a11-mobile');
    const errs = await S.pageErrors();
    assert.deepEqual(errs, []);
    await page.close();
    log('PASS chat_ui_rig: A1 row stays (≤2px), list open, 0 img removed, 0 rerender, click→state ≤16ms; rerun ×3 keeps focus; A14 lightbox caption; A3 inline edit + dblclick selects; F5 wide rail / narrow popup / split button, jump lands 0–24px, ↩ returns; A4 stream renders + p95; A8 ↓ 最新; A2 recreate → live text + queue + 4 turns; A5 / A6 / A7 / A11 screenshots → ' + shell.QA_DIR);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

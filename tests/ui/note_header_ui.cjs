// 1010 她：①笔记顶上插件那一行变成一行很轻的字「← 目录　原文↗　机读版」——没有框、没有右侧控件（导出挪进右上角 ⋮ 菜单）；
// ②「抓全部评论」要有真进度：画在评论区最上面一行 + 细条（note-actions.js paintFetch）。
// 外壳 note-reading 宿主（真 Chromium，载入真 link-brain.css + 插件 styles.css），亮 / 暗 / 改过橙色的第三方主题各跑一遍：
// 顶栏 callout 照 Obsidian 渲染出来的样子摆好（原文 · 机读版），跑 note-tools.js 的 markdown post-processor，量：
//   一行（三样顶边差 ≤ 2px、行高不超过一行半）、顺序「← 目录 / 原文 / 机读版」、没有「·」、没有「导出」按钮、
//   三样都没有边框和底色、「← 目录」和另外两个链接同一个灰色、间距 ≥ 8px、整行在笔记两栏的上面。截图进 LWA_QA_DIR（不提交、不用看）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

const TOPBAR = '<div data-callout-metadata="" data-callout-fold="" data-callout="lb-topbar" class="callout"><div class="callout-title" dir="auto"><div class="callout-icon"></div><div class="callout-title-inner">Lb-topbar</div></div>'
  + '<div class="callout-content"><p dir="auto"><a data-tooltip-position="top" aria-label="https://www.xiaohongshu.com/explore/synth0001" rel="noopener nofollow" class="external-link" href="https://www.xiaohongshu.com/explore/synth0001" target="_blank">原文</a> · '
  + '<a data-href="_archive/xiaohongshu/synth0001/derived/agent.md" href="_archive/xiaohongshu/synth0001/derived/agent.md" class="internal-link" target="_blank" rel="noopener nofollow">机读版</a></p></div></div>';

function noteHtml() {
  const html = fs.readFileSync(path.join(shell.ROOT, 'tests', 'fixtures', 'note-page', 'image-3x4.html'), 'utf8');
  return html.replace(/<img src="\.\.\/\.\.\/[^"]+"/g, '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="');
}

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const toolsSrc = fs.readFileSync(path.join(shell.ROOT, 'obsidian-plugins', 'link-brain-actions', 'note-tools.js'), 'utf8');
  const rows = [];
  try {
    for (const theme of ['light', 'dark', 'orange']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
      const S = await shell.note(page, { theme, mdHtml: `<div class="el-div lb-test-topbar">${TOPBAR}</div>` + noteHtml(), annotate: false });
      await page.evaluate(src => {
        const m = { exports: {} };
        new Function('require', 'module', 'exports', src)(() => ({}), m, m.exports);
        const pps = [];
        window.__opened = [];
        const plugin = { lbRoot: '', lbPath: p => p, settings: {}, app: window.app, registerEvent() {}, register() {}, registerDomEvent() {},
          registerMarkdownPostProcessor(fn) { pps.push(fn); }, addCommand() {}, notify() {}, async openLibraryPage(role, leaf) { window.__opened.push(role); } };
        const tools = m.exports(window.obsidian, plugin, { fs: { readdirSync: () => [] }, path: { join: (...a) => a.join('/') }, electron: {} });
        tools.attach();
        const sec = document.querySelector('.lb-test-topbar');
        pps[0](sec, { sourcePath: 'Web/Xiaohongshu/合成.md', frontmatter: { link_brain: { item_id: 'xhs-synth0001' } } });
      }, toolsSrc);
      await S.settle(60);
      const r = await page.evaluate(() => {
        const row = document.querySelector('.callout[data-callout="lb-topbar"] p');
        const kids = [...row.children];
        const rect = e => e.getBoundingClientRect();
        const cs = e => getComputedStyle(e);
        const boxy = e => { const s = cs(e); return ['Top', 'Right', 'Bottom', 'Left'].some(k => parseFloat(s['border' + k + 'Width']) > 0 && s['border' + k + 'Style'] !== 'none')
          || (s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== 'transparent') || s.boxShadow !== 'none'; };
        const callout = row.closest('.callout');
        const tops = kids.map(k => Math.round(rect(k).top));
        const gaps = kids.slice(1).map((k, i) => Math.round(rect(k).left - rect(kids[i]).right));
        const fs = parseFloat(cs(row).fontSize);
        const note = document.querySelector('.lb-note');
        return { texts: kids.map(k => k.textContent), tags: kids.map(k => k.tagName), hasDot: row.textContent.includes('·'),
          exportBtn: document.querySelectorAll('.lb-topbar-export, .lb-topbar-tools').length, boxy: [callout, row, ...kids].map(boxy),
          tops, topSpread: Math.max(...tops) - Math.min(...tops), rowH: Math.round(rect(row).height), fontSize: fs, gaps,
          colors: kids.map(k => cs(k).color), aboveNote: rect(callout).bottom <= rect(note).top + 0.5,
          backTitle: kids[0].getAttribute('aria-label') };
      });
      rows.push({ theme, ...r });
      console.log(`笔记顶栏（${theme}）：`, JSON.stringify(r));
      assert.deepEqual(r.texts, ['← 目录', '原文', '机读版'], theme + '：一行三样，顺序对');
      assert.equal(r.hasDot, false, theme + '：没有「·」');
      assert.equal(r.exportBtn, 0, theme + '：没有带框的「导出」');
      assert.deepEqual(r.boxy, r.boxy.map(() => false), theme + '：callout / 行 / 三样都没有框、底色、阴影');
      assert.ok(r.topSpread <= 2, theme + '：三样在同一行（顶边差 ' + r.topSpread + 'px）');
      assert.ok(r.rowH <= r.fontSize * 2, theme + `：只占一行（行高 ${r.rowH}px，字号 ${r.fontSize}px）`);
      assert.ok(r.gaps.every(g => g >= 8), theme + '：间距 ' + r.gaps.join(' / '));
      assert.equal(new Set(r.colors).size, 1, theme + '：「← 目录」和原文 / 机读版同一个灰（' + r.colors.join(' / ') + '）');
      assert.ok(r.aboveNote, theme + '：这一行在两栏笔记上面');
      // 点「← 目录」→ 打开目录页（同一格；目录页自己恢复刚才的滚动和筛选，见 catalog_after_note_ui）
      await page.click('.lb-topbar-back');
      assert.deepEqual(await page.evaluate(() => window.__opened), ['catalog']);
      // 悬停：主题色 + 下划线（和原文 / 机读版一样）
      await page.hover('.lb-topbar-back');
      const hover = await page.evaluate(() => { const s = getComputedStyle(document.querySelector('.lb-topbar-back')); return { deco: s.textDecorationLine, color: s.color }; });
      assert.equal(hover.deco, 'underline', theme + '：悬停有下划线');
      await S.screenshot(`note-header-${theme}`, { clip: { x: 0, y: 0, width: 1280, height: 260 } });
      // —— 同一页：「抓全部评论」的进度（note-actions.js paintFetch）画在评论区最上面，看得见、细条在走 ——
      const fetchGeo = await page.evaluate(src => {
        const m = { exports: {} };
        new Function('require', 'module', 'exports', src)(n => (n === 'fs' ? { readFileSync() { throw new Error('no fs'); } } : { join: (...a) => a.join('/') }), m, m.exports);
        const plugin = { app: window.app, manifest: { dir: '' }, register() {}, registerEvent() {}, registerDomEvent() {}, addCommand() {}, notify() {}, commentFetch: null };
        const na = m.exports(window.obsidian, plugin);
        const now = Date.now();
        plugin.commentFetch = { itemId: 'xhs-synth0001', stage: 'read', text: '打开这篇，把评论一楼一楼展开读下来（热门笔记要几分钟到十几分钟，最多 25 分钟）', startedAt: now - 5000, stageAt: now - 5000, result: null };
        na.paintFetch();
        const box = document.querySelector('.lb-comments > .lb-fetch-progress');
        const first = box && box.parentElement.firstElementChild === box;
        const r = box.getBoundingClientRect(), bar = box.querySelector('.lb-fetch-bar').getBoundingClientRect();
        const next = box.nextElementSibling && box.nextElementSibling.getBoundingClientRect();
        const anim = getComputedStyle(box.querySelector('.lb-fetch-fill')).animationName;
        plugin.commentFetch = { ...plugin.commentFetch, stage: 'media', text: '下载图片 / 语音 6/12', done: 6, total: 12 };
        na.paintFetch();
        window.__na = { na, plugin };
        return { first, h: Math.round(r.height), w: Math.round(r.width), barH: Math.round(bar.height), anim,
          aboveNext: next ? r.bottom <= next.top + 0.5 : true, color: getComputedStyle(box).color };
      }, fs.readFileSync(path.join(shell.ROOT, 'obsidian-plugins', 'link-brain-actions', 'note-actions.js'), 'utf8'));
      await page.waitForTimeout(450);   // 细条宽度有 .3s 过渡
      Object.assign(fetchGeo, await page.evaluate(() => {
        const box = document.querySelector('.lb-comments > .lb-fetch-progress');
        const fill = box.querySelector('.lb-fetch-fill').getBoundingClientRect().width / box.querySelector('.lb-fetch-bar').getBoundingClientRect().width;
        const out = { fill: Math.round(fill * 100) / 100, text: box.querySelector('.lb-fetch-text').textContent };
        const { na, plugin } = window.__na; na.stopFetchTick(); plugin.commentFetch = null; na.paintFetch();
        out.gone = !document.querySelector('.lb-fetch-progress');
        return out;
      }));
      console.log(`抓全部评论进度（${theme}）：`, JSON.stringify(fetchGeo));
      assert.ok(fetchGeo.first && fetchGeo.h >= 18 && fetchGeo.w >= 200, theme + '：进度那一行在评论区最上面、看得见');
      assert.equal(fetchGeo.barH, 3, theme + '：细条 3px');
      assert.equal(fetchGeo.anim, 'lb-slide', theme + '：读评论区时细条来回扫');
      assert.ok(Math.abs(fetchGeo.fill - 0.5) <= 0.02, theme + '：下图 6/12 → 细条走到一半（' + fetchGeo.fill + '）');
      assert.ok(fetchGeo.aboveNext && fetchGeo.gone, theme + '：不压在第一条评论上；清掉后收起');
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    fs.mkdirSync(shell.QA_DIR, { recursive: true });
    fs.writeFileSync(path.join(shell.QA_DIR, 'note-header.json'), JSON.stringify(rows, null, 2));
  } finally { await browser.close(); }
  console.log('PASS note page (1010): header = one light row ← 目录 · 原文 · 机读版 (no dots, no boxed 导出), same muted color, single line, click → catalog; 抓全部评论 progress line on top of comments (indeterminate bar while reading, 6/12 → half), light / dark / third-party theme');
})().catch(e => { console.error(e); process.exit(1); });

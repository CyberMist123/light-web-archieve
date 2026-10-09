// 1010 她报：在目录页点开视频笔记、点「连播…」按标签连播，回到目录后目录往下滚不动、反复被拉回顶部。
// 复现（外壳 page-reading 宿主 = Obsidian 1.14.4 阅读视图，真 Chromium）：同一个标签页先显示一篇（默认钉住的）视频笔记，
// 再换成目录页——Obsidian 同一标签页换文件复用同一个 .markdown-preview-view，旧笔记被摘下；然后真鼠标滚轮往下滚目录。
// 根因（9db45ca 的 media-nav.js）：钉住时给预览容器挂的 scroll 监听（ensureLockedInView：笔记顶被滚出容器上沿就把容器往回滚）
// 换页后没摘；摘下的笔记 getBoundingClientRect().top = 0、容器顶 = 标签栏 + 视图头的高度，每次滚动都被判成「笔记顶在上沿外」，
// 往回滚一个容器顶那么多；往回滚又触发 scroll → 再往回滚……一直滚到 0。连播只是把她带回这个标签页的那条路。
// 红线规矩（CONVENTIONS §7.8）：同一个用例先在 9db45ca（出问题那一版）的 media-nav.js 上跑红、读数打印出来记进验收文件，再对当前文件跑绿。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

const BEFORE = '9db45ca';   // 她报问题时生产上的那一版（main）
const NAV = 'obsidian-plugins/link-brain-actions';

function svg(w, h, label) {
  return 'data:image/svg+xml;base64,' + Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="${w}" height="${h}" fill="#c9d6e3"/><text x="20" y="60" font-size="40">${label}</text></svg>`).toString('base64');
}
function noteHtml() {
  let html = fs.readFileSync(path.join(shell.ROOT, 'tests', 'fixtures', 'note-page', 'video-9x16.html'), 'utf8');
  html = html.replace(/<img src="\.\.\/\.\.\/[^"]+" width="(\d+)" height="(\d+)"/g, (m, w, h) => `<img src="${svg(+w, +h, w + '×' + h)}" width="${w}" height="${h}"`);
  return html.replace(/ poster="\.\.\/\.\.\/[^"]+" src="\.\.\/\.\.\/[^"]+"/g, ` poster="${svg(1080, 1920, 'cover')}"`);
}

// 一次完整的「笔记 → 回目录 → 往下滚」：navRev = null 用当前 media-nav.js，给了就用那一版（git show 只读）
async function scenario(browser, { navRev = null, theme = 'light', savedScroll = 0 } = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  try {
    const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme, data: shell.makeCatalogData({ n: 160 }), run: false });
    // ① 这个标签页先显示一篇视频笔记（阅读视图，默认钉住）
    await page.evaluate(html => {
      const pv = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view');
      pv.classList.add('link-brain', 'xhs-note');
      const sec = document.createElement('div'); sec.className = 'el-div lb-test-note'; sec.innerHTML = html;
      pv.querySelector('.markdown-preview-sizer').insertBefore(sec, pv.querySelector('.el-pre'));
    }, noteHtml());
    await page.evaluate(src => {
      const m = { exports: {} };
      new Function('require', 'module', 'exports', src)(() => ({}), m, m.exports);
      const host = { app: window.app, settings: { media: { loop: false, playlistOrder: 'newest' } }, async saveSettings() {}, notify() {},
        register(fn) { (window.__navCleanups = window.__navCleanups || []).push(fn); }, registerDomEvent(el, t, fn, o) { el.addEventListener(t, fn, o); }, registerEvent() {} };
      window.__nav = m.exports({ Notice: window.obsidian && window.obsidian.Notice }, host);
      window.__nav.attach();
    }, shell.readAsset('media-nav.js', navRev, NAV));
    await S.settle(150);
    const pinned = await page.evaluate(() => !!document.querySelector('.lb-note.lb-media-locked'));
    // ② 换成目录页：Obsidian 复用同一个预览容器——旧笔记那一段摘掉、笔记的 cssclasses 去掉、滚动归零，再由 Dataview 跑目录脚本
    // 页面状态（§5.3）：外壳是 setContent 出来的页，sessionStorage 不让读——lb-page-lib 退回 globalThis.__lbState，就种在那里
    if (savedScroll) await page.evaluate(top => { (window.__lbState = window.__lbState || {})['lb:catalog'] = JSON.stringify({ q: '', scrollTop: top, ts: Date.now() }); }, savedScroll);
    await page.evaluate(() => {
      const pv = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view');
      pv.querySelector('.lb-test-note').remove();
      pv.classList.remove('link-brain', 'xhs-note');
      pv.scrollTop = 0;
    });
    await S.run();
    await S.settle(savedScroll ? 1800 : 300);   // 有存下的位置：等 restoreScroll 恢复完、守满 1.2 秒
    const restored = await S.scrollTop();
    // ③ 真鼠标滚轮往下滚三格，停一停再读（她说的「反复被拉回顶部」：停手后还会不会被拉回去）
    await S.hoverScroller();
    for (let i = 0; i < 3; i++) { await page.mouse.wheel(0, 300); await page.waitForTimeout(250); }
    const afterWheel = await S.scrollTop();
    await page.waitForTimeout(1200);
    const settled = await S.scrollTop();
    // 摘下的笔记 / 预览容器顶各在哪（读数用）
    const geo = await page.evaluate(() => ({ previewTop: Math.round(document.querySelector('.workspace-leaf.mod-active .markdown-preview-view').getBoundingClientRect().top),
      paneLocked: document.querySelector('.workspace-leaf.mod-active .markdown-preview-view').classList.contains('lb-pane-locked'),
      scrollMax: (pv => pv.scrollHeight - pv.clientHeight)(document.querySelector('.workspace-leaf.mod-active .markdown-preview-view')) }));
    const errors = await S.pageErrors();
    return { navRev: navRev || 'current', theme, savedScroll, pinned, restored, afterWheel, settled, ...geo, errors };
  } finally { await page.close(); }
}

(async () => {
  shell.requirePlaywright();
  if (!shell.revAvailable(BEFORE)) { console.log(`SKIP 本仓库里没有 ${BEFORE}：红线读数没法跑`); process.exit(shell.SKIP); }
  const browser = await shell.launch();
  const rows = [];
  try {
    // 红：出问题那一版
    for (const savedScroll of [0, 1500]) {
      const r = await scenario(browser, { navRev: BEFORE, savedScroll });
      rows.push(r);
      console.log(`红（${BEFORE}，回到目录时记着 scrollTop=${savedScroll}）：`, JSON.stringify(r));
      assert.ok(r.pinned, '改前：笔记默认钉住（复现的前提）');
      assert.ok(r.settled <= 10, `改前应当复现「被拉回顶部」：停手后 scrollTop=${r.settled}`);
    }
    // 绿：当前版本，亮 / 暗都跑
    for (const theme of ['light', 'dark']) for (const savedScroll of [0, 1500]) {
      const r = await scenario(browser, { theme, savedScroll });
      rows.push(r);
      console.log(`绿（当前，${theme}，记着 scrollTop=${savedScroll}）：`, JSON.stringify(r));
      assert.ok(r.pinned, '笔记默认钉住');
      assert.deepEqual(r.errors, []);
      assert.equal(r.paneLocked, false, '整页锁（overflow:hidden）不留在目录页上');
      if (savedScroll) assert.ok(Math.abs(r.restored - savedScroll) <= 2, `回到目录：滚动位置恢复到 ${savedScroll}（实际 ${r.restored}）`);
      assert.ok(r.afterWheel >= (savedScroll || 0) + 600, `往下滚三格（各 300）：scrollTop ${r.restored} → ${r.afterWheel}`);
      assert.ok(Math.abs(r.settled - r.afterWheel) <= 1, `停手 1.2 秒后不被拉回：${r.afterWheel} → ${r.settled}`);
    }
    fs.mkdirSync(shell.QA_DIR, { recursive: true });
    fs.writeFileSync(path.join(shell.QA_DIR, 'catalog-after-note-scroll.json'), JSON.stringify(rows, null, 2));
  } finally { await browser.close(); }
  console.log(`PASS catalog after a pinned note (连播 / 返回目录): ${BEFORE} red (pulled back to 0), current green — wheel scrolls and stays, saved scroll restored, light / dark`);
})().catch(e => { console.error(e); process.exit(1); });

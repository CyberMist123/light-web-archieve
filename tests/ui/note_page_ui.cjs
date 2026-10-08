// 批次 D · L3 笔记页（playwright 外壳 note-reading 宿主，真 Chromium / Edge）：
//   N15 测量：1280×800 / 1440×900 / 1920×1080 × 左侧栏开 / 关 × 3:4、9:16、4:3 图和 9:16 视频，改前（932b9f7 的 link-brain.css + annotate-view + media-nav，钉住）/ 改后（默认钉住）：
//       当前那张图 / 视频的高度、--lb-reader-height、批注输入框第一行底部、可视底部（min(左栏底, 状态栏顶, 窗口底)）、不钉时的图片高度（给她对照）。
//       断言：钉住时图片 / 视频高度改前改后差 ≤0.5px；图片类在三种窗口 × 两种侧栏下输入框第一行都在可视区内。截图进 LWA_QA_DIR（note-{W}x{H}-{用例}-{before|after}.png）。
//   N1 真鼠标滚轮：不钉时翻到最后一张再往下滚 → 整页滚；钉住时 → 正文栏滚、图片不动。N15 钉住时滚轮在批注列表上先滚左栏。
//   N15 后台重写这篇（.lb-note 整块换新）：钉住状态、当前张、正文栏 scrollTop 照旧。
//   主审裁决 3：单栏 / 实时预览（page-reading / page-live 宿主，当前资产）重跑 3 次：不定稿、字和焦点都在（7ab44c6 的红线读数在 rig_selfcheck_ui ⑥）。
// 读数打印出来并写到 LWA_QA_DIR/note-n15-measure.json（验收文件 tests/acceptance/20261008-batchD-L3-note.md 照抄）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

const BEFORE = '932b9f7';   // 本线开工基线（L3 改动之前）
const NOTE = '_archive/xiaohongshu/synth0001/notes.json';
const WINDOWS = [[1280, 800], [1440, 900], [1920, 1080]];
const CASES = ['image-3x4', 'image-9x16', 'image-4x3', 'video-9x16'];
const annotations = n => Array.from({ length: n }, (_, i) => ({ id: 'a' + i, ts: `2026-09-0${1 + (i % 8)}T0${i % 10}:00:00Z`, text: `第 ${i + 1} 条批注：合成的批注文字。` }));
const files = (n = 3) => ({ [NOTE]: JSON.stringify({ starred: false, annotations: annotations(n) }) });
const params = { itemId: 'xhs-synth0001', notePath: NOTE };

function svg(w, h, label) {
  return 'data:image/svg+xml;base64,' + Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="#c9d6e3"/><rect x="8" y="8" width="${w - 16}" height="${h - 16}" fill="none" stroke="#7a8fa6" stroke-width="8"/><text x="${w / 2}" y="${h / 2}" font-size="${Math.round(Math.min(w, h) / 6)}" text-anchor="middle" fill="#456" font-family="Arial">${label}</text></svg>`).toString('base64');
}
// 生产渲染的笔记 HTML（tests/fixtures/note-page，tests/tools/note_fixture.py 生成）→ 图片换成同尺寸的现画图
function materialize(name) {
  let html = fs.readFileSync(path.join(shell.ROOT, 'tests', 'fixtures', 'note-page', name + '.html'), 'utf8');
  let n = 0;
  html = html.replace(/<img src="\.\.\/\.\.\/[^"]+" width="(\d+)" height="(\d+)"/g, (m, w, h) => `<img src="${svg(+w, +h, `${++n} · ${w}×${h}`)}" width="${w}" height="${h}"`);
  html = html.replace(/ poster="\.\.\/\.\.\/[^"]+" src="\.\.\/\.\.\/[^"]+"/g, ` poster="${svg(1080, 1920, '视频封面 9:16')}"`);
  return html;
}
function navSource(rev) { return shell.readAsset('media-nav.js', rev, 'obsidian-plugins/link-brain-actions'); }

async function open(browser, { w, h, sidebar = true, kase, rev = null, n = 3 }) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  const S = await shell.note(page, { kind: 'annotate', rev, mdHtml: materialize(kase), files: files(n), params, sidebar });
  if (rev) await page.evaluate(css => { document.getElementById('lb-test-link-brain-css').textContent = css; }, shell.readAsset('link-brain.css', rev));
  await page.evaluate(src => {
    const m = { exports: {} };
    new Function('require', 'module', 'exports', src)(() => ({}), m, m.exports);
    const host = { app: window.app, settings: { media: { loop: false, playlistOrder: 'newest' } }, async saveSettings() {}, notify() {},
      register(fn) { (window.__navCleanups = window.__navCleanups || []).push(fn); }, registerDomEvent(el, t, fn, o) { el.addEventListener(t, fn, o); }, registerEvent() {} };
    window.__nav = m.exports({ Notice: window.obsidian && window.obsidian.Notice }, host);
    window.__nav.attach();
  }, navSource(rev));
  await page.waitForFunction(() => { const i = document.querySelector('.lb-carousel .lb-slide img'); return !i || !i.getClientRects().length || (i.complete && i.naturalWidth > 0); });
  await S.settle(120);
  return { page, S };
}
const measure = page => page.evaluate(() => {
  const note = document.querySelector('.workspace-leaf.mod-active .lb-note');
  const media = note.querySelector('.lb-carousel .lb-slide img, .lb-carousel video');
  const mr = media.getBoundingClientRect();
  const ta = note.querySelector('.lba-annot-input');
  const locked = note.classList.contains('lb-media-locked');
  const side = note.querySelector('.lb-side').getBoundingClientRect();
  const sb = document.querySelector('.status-bar').getBoundingClientRect();
  const sc = document.querySelector('.workspace-leaf.mod-active .markdown-preview-view').getBoundingClientRect();
  let firstLine = null;
  if (ta) { const cs = getComputedStyle(ta), tr = ta.getBoundingClientRect(); firstLine = tr.top + parseFloat(cs.paddingTop) + (parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.6); }
  const visBottom = Math.min(locked ? side.bottom : Infinity, sb.top, innerHeight, sc.bottom);
  const r1 = x => (x == null ? null : Math.round(x * 10) / 10);
  return { locked, mediaH: r1(mr.height), mediaW: r1(mr.width), mediaBottom: r1(mr.bottom), R: r1(parseFloat(getComputedStyle(note).getPropertyValue('--lb-reader-height')) || null),
    firstLine: r1(firstLine), visBottom: r1(visBottom), inView: firstLine != null && firstLine <= visBottom + 0.5, gap: r1(firstLine - visBottom), inSide: !!(ta && ta.closest('.lb-side')) };
});
const clickPin = async page => { await page.hover('.workspace-leaf.mod-active .lb-media'); await page.click('.workspace-leaf.mod-active .lb-media-pin'); await page.waitForTimeout(120); };

(async () => {
  shell.requirePlaywright();
  if (!shell.revAvailable(BEFORE)) { console.log(`SKIP 本仓库里没有 ${BEFORE}：改前改后对照没法跑`); process.exit(shell.SKIP); }
  const browser = await shell.launch();
  const rows = [];
  try {
    // ── N15 测量矩阵 ──
    for (const [w, h] of process.env.LWA_L3_QUICK ? [] : WINDOWS) for (const sidebar of [true, false]) for (const kase of CASES) {   // LWA_L3_QUICK=1：调试时跳过测量矩阵
      const tag = `${w}x${h}${sidebar ? '' : '-nosidebar'}-${kase}`;
      // 改后：默认钉住
      let { page } = await open(browser, { w, h, sidebar, kase });
      const after = await measure(page);
      assert.equal(after.locked, true, tag + '：阅读视图默认钉住');
      assert.ok(after.inSide, tag + '：批注框在左栏图片 / 视频下面');
      if (sidebar) await page.screenshot({ path: qa(`note-${w}x${h}-${kase}-after.png`) });
      await clickPin(page);
      const afterFree = await measure(page);
      await page.close();
      // 改前：932b9f7 默认不钉，点钉住
      ({ page } = await open(browser, { w, h, sidebar, kase, rev: BEFORE }));
      const beforeFree = await measure(page);
      await clickPin(page);
      const before = await measure(page);
      assert.equal(before.locked, true);
      if (sidebar) await page.screenshot({ path: qa(`note-${w}x${h}-${kase}-before.png`) });
      await page.close();
      const row = { window: `${w}×${h}`, sidebar, kase, pinnedBefore: before, pinnedAfter: after, freeBefore: beforeFree, freeAfter: afterFree };
      rows.push(row);
      console.log(`${tag}: 钉住 图高 ${before.mediaH} → ${after.mediaH}（R ${before.R} → ${after.R}）；输入框首行 ${before.firstLine} → ${after.firstLine}，可视底 ${before.visBottom} → ${after.visBottom}，在视口内 ${before.inView} → ${after.inView}；不钉时图高 ${beforeFree.mediaH}`);
      assert.ok(Math.abs(after.mediaH - before.mediaH) <= 0.5, `${tag}：钉住时图片 / 视频高度不变（${before.mediaH} → ${after.mediaH}）`);
      if (kase.startsWith('image')) assert.ok(after.inView, `${tag}：钉住时批注输入框第一行在可视区内（首行底 ${after.firstLine}，可视底 ${after.visBottom}）`);
    }
    if (rows.length) fs.writeFileSync(qa('note-n15-measure.json'), JSON.stringify(rows, null, 2));
    const redBefore = rows.filter(r => r.kase.startsWith('image') && !r.pinnedBefore.inView).length;
    console.log(`改前（${BEFORE}）钉住时图片类输入框首行不在可视区：${redBefore} / ${rows.filter(r => r.kase.startsWith('image')).length} 格`);

    // ── N5：钉住 1280×800 下连打 8 行，光标那一行还在可视区 ──
    {
      const { page } = await open(browser, { w: 1280, h: 800, kase: 'image-3x4' });
      await page.click('.lba-annot-input');
      for (let i = 1; i <= 8; i++) { await page.keyboard.type(`第 ${i} 行批注`); if (i < 8) await page.keyboard.press('Shift+Enter'); }
      await page.waitForTimeout(80);
      const r = await page.evaluate(() => { const ta = document.querySelector('.lba-annot-input'), side = document.querySelector('.lb-side').getBoundingClientRect(); const t = ta.getBoundingClientRect(); return { taH: Math.round(t.height), taBottom: Math.round(t.bottom), lastLineBottom: Math.round(t.bottom - parseFloat(getComputedStyle(ta).paddingBottom)), sideBottom: Math.round(side.bottom), sideScrolled: document.querySelector('.lb-side').scrollTop, lines: ta.value.split('\n').length }; });
      console.log('N5 钉住 1280×800 连打 8 行：', JSON.stringify(r));
      assert.equal(r.lines, 8); assert.ok(r.taH > 100, '输入框随内容长高');
      assert.ok(r.sideScrolled > 0 && r.lastLineBottom <= r.sideBottom + 3, '光标所在的最后一行在左栏可视区里（左栏自己滚到它；容差 3px = 行框和光标框的差）');
      await page.screenshot({ path: qa('annot-autosize.png') });
      await page.close();
    }

    // ── N1 真鼠标滚轮 + N15 左栏滚轮 ──
    {
      const { page, S } = await open(browser, { w: 1440, h: 900, kase: 'image-3x4', n: 14 });
      const img = '.workspace-leaf.mod-active .lb-carousel';
      // 钉住（默认）：滚轮在批注区（图片下面、左栏可视部分里）→ 先滚左栏，正文栏不动
      const pt = await page.evaluate(() => { const side = document.querySelector('.lb-side').getBoundingClientRect(), ta = document.querySelector('.lba-annot-input').getBoundingClientRect(); return { x: ta.left + 40, y: Math.min(ta.top + 10, side.bottom - 6) }; });
      const hit = await page.evaluate(p => { const e = document.elementFromPoint(p.x, p.y); return e && e.className; }, pt);
      const sideOverflow = await page.evaluate(() => { const s = document.querySelector('.lb-side'); return s.scrollHeight - s.clientHeight; });
      console.log('左栏滚轮落点：', hit);
      await page.mouse.move(pt.x, pt.y);
      await page.mouse.wheel(0, 200); await page.waitForTimeout(200);
      let r = await page.evaluate(() => ({ side: document.querySelector('.lb-side').scrollTop, main: document.querySelector('.lb-scroll').scrollTop }));
      console.log('N15 钉住时批注列表上滚轮：', JSON.stringify({ sideOverflow, ...r }));
      assert.ok(sideOverflow > 0 && r.side > 0 && r.main === 0, '左栏能滚：滚轮先滚左栏，正文栏不动');
      // 钉住：翻到最后一张再往下滚 → 正文栏滚、图片不动
      const box = await page.locator(img).boundingBox();
      await page.evaluate(s => { const c = document.querySelector(s); c.scrollLeft = c.scrollWidth; }, img);
      await page.waitForTimeout(400);
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      const y0 = (await page.locator(img).boundingBox()).y;
      await page.mouse.wheel(0, 120); await page.waitForTimeout(450); await page.mouse.wheel(0, 120); await page.waitForTimeout(200);
      r = await page.evaluate(() => ({ main: document.querySelector('.lb-scroll').scrollTop, pane: document.querySelector('.workspace-leaf.mod-active .markdown-preview-view').scrollTop }));
      assert.ok(r.main > 0, `钉住：最后一张往下滚 → 正文栏滚了（${r.main}）`);
      assert.equal((await page.locator(img).boundingBox()).y, y0, '钉住：图片不动');
      // 不钉：最后一张往下滚 → 整页滚
      await clickPin(page);
      await page.evaluate(s => { const c = document.querySelector(s); c.scrollLeft = c.scrollWidth; c.lbFlipAt = 0; }, img);
      await page.waitForTimeout(400);
      const b2 = await page.locator(img).boundingBox();
      await page.mouse.move(b2.x + b2.width / 2, b2.y + Math.min(b2.height / 2, 300));
      const before = await S.scrollTop();
      await page.mouse.wheel(0, 150); await page.waitForTimeout(300);
      const after = await S.scrollTop();
      console.log('N1 不钉时最后一张往下滚：整页 scrollTop', before, '→', after);
      assert.ok(after > before, '不钉：翻到最后一张后滚轮放行，整页滚动');
      await page.close();
    }

    // ── N15 后台重写这篇：钉住状态、当前张、正文 scrollTop 照旧 ──
    {
      const { page, S } = await open(browser, { w: 1440, h: 900, kase: 'image-3x4' });
      await page.evaluate(() => { const c = document.querySelector('.lb-carousel'); c.scrollTo({ left: c.children[2].offsetLeft - c.children[0].offsetLeft, behavior: 'auto' }); });
      await page.evaluate(() => { const s = document.querySelector('.lb-scroll'); s.scrollTop = 300; s.dispatchEvent(new Event('scroll')); });
      await page.waitForTimeout(300);
      const want = await page.evaluate(() => { const idx = c => { const sl = [...c.querySelectorAll(':scope > .lb-slide')]; let b = 0, d = 1e9; sl.forEach((x, i) => { const k = Math.abs(x.offsetLeft - sl[0].offsetLeft - c.scrollLeft); if (k < d) { d = k; b = i; } }); return b; }; return { slide: idx(document.querySelector('.lb-carousel')), top: document.querySelector('.lb-scroll').scrollTop }; });
      await page.evaluate(() => { const old = document.querySelector('.workspace-leaf.mod-active .lb-note'); const t = document.createElement('template'); t.innerHTML = old.outerHTML.replace(/ data-lb-enhanced="1"/g, '').replace(/ class="lb-note[^"]*"/, ' class="lb-note"').replace(/ style="[^"]*"/, ''); const fresh = t.content.firstElementChild; fresh.querySelectorAll('.lb-media-pin,.lb-media-tools,.lba-annot').forEach(e => e.remove()); old.replaceWith(fresh); });
      await S.settle(400);
      const got = await page.evaluate(() => { const idx = c => { const sl = [...c.querySelectorAll(':scope > .lb-slide')]; let b = 0, d = 1e9; sl.forEach((x, i) => { const k = Math.abs(x.offsetLeft - sl[0].offsetLeft - c.scrollLeft); if (k < d) { d = k; b = i; } }); return b; }; const n = document.querySelector('.workspace-leaf.mod-active .lb-note'); return { locked: n.classList.contains('lb-media-locked'), slide: idx(n.querySelector('.lb-carousel')), top: n.querySelector('.lb-scroll').scrollTop, annotInSide: !!n.querySelector('.lb-side .lba-annot') }; });
      console.log('N15 后台重写前后：', JSON.stringify({ want, got }));
      assert.ok(got.locked, '重写后仍钉住');
      assert.equal(want.slide, 2); assert.equal(got.slide, 2, '还在第 3 张');
      assert.ok(Math.abs(got.top - want.top) <= 1, '正文栏 scrollTop 照旧');
      assert.ok(got.annotInSide, '批注框挪回新左栏');
      await page.close();
    }

    // ── 主审裁决 3：单栏 / 实时预览重跑不定稿（真 Chromium，当前资产）──
    for (const host of ['page-reading', 'page-live']) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const S = await shell.page(page, { host, kind: 'annotate', files: files(1), params, frontmatter: {} });
      await page.click('.lba-annot-input');
      await page.keyboard.type('正在');
      for (let i = 0; i < 3; i++) { await S.rerun(); await page.keyboard.type('打'); }
      await page.waitForTimeout(150);
      const r = await page.evaluate(async note => {
        const ta = document.querySelector('.lba-annot-input');
        return { saved: JSON.parse(await window.app.vault.adapter.read(note)).annotations.map(a => a.text), value: ta.value, focused: document.activeElement === ta, boxes: document.querySelectorAll('.lba-annot').length };
      }, NOTE);
      console.log(`单栏批注 ${host === 'page-live' ? '实时预览' : '阅读视图'}（当前资产）重跑 3 次：`, JSON.stringify(r));
      assert.deepEqual(r, { saved: ['第 1 条批注：合成的批注文字。'], value: '正在打打打', focused: true, boxes: 1 }, host + '：不定稿、字和焦点都在');
      await page.close();
    }
    console.log(`PASS note page (L3): N15 measured ${rows.length} cells (pinned media height unchanged vs ${BEFORE}, image input first line in view at 1280×800 / 1440×900 / 1920×1080 with and without sidebar), N5 autosize keeps caret in view, left column wheel-scrolls when pinned, N1 wheel passes through at last image (pinned → body column, free → page), rewrite keeps pin / slide / scroll, single-column + live preview reruns keep typing (no commit)`);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

function qa(name) { fs.mkdirSync(shell.QA_DIR, { recursive: true }); return path.join(shell.QA_DIR, name); }

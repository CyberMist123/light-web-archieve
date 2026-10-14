// 1015 她（C5/C12）：笔记页划重点——默认黄色；右键「划重点（选颜色）▸」；点一下已划的出小条（五个色点 + 取消），
//   换色 / 取消先乐观改、后台（highlight --color / --remove）没写上退回；「视频文字稿 / 视频画面文字」折叠标题小字浅色。
// 外壳 note-reading 宿主（真 Chromium + 真 link-brain.css），跑真的 note-actions.js；runPy 是假的（记参数）。截图进 LWA_QA_DIR。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

function noteHtml() {
  let html = fs.readFileSync(path.join(shell.ROOT, 'tests', 'fixtures', 'note-page', 'image-3x4.html'), 'utf8');
  html = html.replace(/<img src="\.\.\/\.\.\/[^"]+"/g, '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="');
  // 正文里放两处已划的（黄、绿）+ 视频文字稿两个折叠块
  html = html.replace(/<div class="lb-body">/, '<div class="lb-body"><p>先看<mark>这一句重点</mark>，再看<mark class="lb-hl-green">绿色那句</mark>和普通的一句话。</p>'
    + '<details class="lb-transcript"><summary>视频文字稿</summary><p>转写</p></details><details class="lb-transcript"><summary>视频画面文字</summary><p>画面</p></details>');
  return html;
}

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const src = fs.readFileSync(path.join(shell.ROOT, 'obsidian-plugins', 'link-brain-actions', 'note-actions.js'), 'utf8');
  try {
    for (const theme of ['light', 'dark']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
      const NOTE = '_archive/xiaohongshu/synth0001/notes.json';
      const S = await shell.note(page, { theme, mdHtml: noteHtml(), kind: 'annotate', files: { [NOTE]: JSON.stringify({ starred: true, annotations: [] }) }, params: { itemId: 'xhs-synth0001', notePath: NOTE } });
      await S.settle(200);
      await page.evaluate(src => {
        const m = { exports: {} };
        new Function('require', 'module', 'exports', src)(n => (n === 'fs' ? { readFileSync: () => { throw new Error('no'); } } : n === 'path' ? { join: (...a) => a.join('/') } : {}), m, m.exports);
        window.__py = []; window.__menus = [];
        window.__pyAnswer = { ok: true, changed: ['x'], already: [] };
        const leaf = { view: { containerEl: document.body, file: { path: 'Web/Xiaohongshu/合成.md' } } };
        const app = { ...window.app, workspace: { ...(window.app.workspace || {}), getLeavesOfType: () => [leaf], on() { return {}; } },
          metadataCache: { getFileCache: () => ({ frontmatter: { link_brain: { item_id: 'xhs-synth0001' } } }) }, vault: { adapter: { getBasePath: () => '' } } };
        const plugin = { app, manifest: { dir: '' }, settings: {}, register() {}, registerEvent() {}, addCommand() {},
          registerDomEvent(t, ev, fn, cap) { t.addEventListener(ev, fn, cap); }, notify(msg) { (window.__notes = window.__notes || []).push(msg); },
          showMenu(items) { window.__menus.push(items.map(i => [i.title, (i.children || []).map(k => k.title)])); window.__lastItems = items; return {}; },
          async runPy(args) { window.__py.push(args.slice(2)); return { code: 0, json: window.__pyAnswer }; } };
        window.__na = m.exports(window.obsidian, plugin).attach();
      }, src);
      await S.settle(60);
      // 批注区（1015）：没有「批注」二字、⭐ 在写批注框边上、划的重点一行一条列在批注区
      const ann = await page.evaluate(() => { const b = document.querySelector('.lba-annot'); const ta = b.querySelector('.lba-annot-input').getBoundingClientRect(), st = b.querySelector('.lba-star').getBoundingClientRect();
        return { title: !!b.querySelector('.lba-annot-title'), text: b.textContent.includes('批注') && !b.querySelector('.lba-annot-input').placeholder, sameRow: Math.abs(st.top - ta.top) < 20 && st.left >= ta.right - 2,
          marks: [...b.querySelectorAll('.lba-mark-row')].map(r => [r.textContent, r.className]) }; });
      assert.ok(!ann.title && ann.sameRow, `${theme}：没有「批注」二字、⭐ 在输入框右边 ${JSON.stringify(ann)}`);
      assert.deepEqual(ann.marks.map(m => m[0]), ['这一句重点', '绿色那句'], `${theme}：重点列进批注区 ${JSON.stringify(ann.marks)}`);
      assert.ok(/lb-hl-green/.test(ann.marks[1][1]), `${theme}：带颜色`);
      const yellow = await page.evaluate(() => getComputedStyle(document.querySelector('.lb-body mark:not([class])')).backgroundColor);
      assert.match(yellow, /rgba\(255, 214, 10/, `${theme}：默认黄 ${yellow}`);
      const green = await page.evaluate(() => getComputedStyle(document.querySelector('mark.lb-hl-green')).backgroundColor);
      assert.match(green, /rgba\(80, 200, 120/, `${theme}：绿色 ${green}`);
      // 小字浅色的折叠标题
      const sum = await page.evaluate(() => { const s = document.querySelector('details.lb-transcript > summary'), b = document.querySelector('.lb-body p');
        return { fs: parseFloat(getComputedStyle(s).fontSize), body: parseFloat(getComputedStyle(b).fontSize) }; });
      assert.ok(sum.fs <= 12.5 && sum.fs < sum.body, `${theme}：视频文字稿标题小字 ${JSON.stringify(sum)}`);
      // 选中普通字 → 右键菜单：划重点 + 划重点（选颜色）▸
      await page.evaluate(() => {
        const p = document.querySelector('.lb-body p'); const t = [...p.childNodes].at(-1);
        const r = document.createRange(); const i = t.data.indexOf('普通的一句话'); r.setStart(t, i); r.setEnd(t, i + 6);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
        p.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
      });
      let menu = await page.evaluate(() => window.__menus.at(-1));
      assert.deepEqual(menu.map(x => x[0]).slice(0, 2), ['划重点', '划重点（选颜色）'], `${theme}：选字右键 ${JSON.stringify(menu)}`);
      assert.deepEqual(menu[1][1], ['黄', '绿', '蓝', '粉', '紫']);
      await page.evaluate(() => window.__lastItems[1].children[3].onClick());   // 粉
      await S.settle(60);
      let py = await page.evaluate(() => window.__py.at(-1));
      assert.deepEqual(py, ['highlight', 'xhs-synth0001', '普通的一句话', '--color', 'pink', '--json'], `${theme}：选颜色划 ${py}`);
      // 点一下已划的黄 → 小条
      await page.locator('.lb-body mark:not([class])').first().click(); await S.settle(60);
      const pop = await page.evaluate(() => { const p = document.querySelector('.lb-hl-pop'); return p && { dots: p.querySelectorAll('.lb-hl-dot').length, on: p.querySelector('.is-on')?.className, off: p.querySelector('.lb-hl-off')?.textContent }; });
      assert.ok(pop && pop.dots === 5 && /yellow/.test(pop.on) && pop.off === '取消', `${theme}：点重点出小条 ${JSON.stringify(pop)}`);
      await S.screenshot(`note-highlight-pop-${theme}`);
      await page.locator('.lb-hl-pop .lb-hl-dot-blue').click(); await S.settle(60);
      py = await page.evaluate(() => window.__py.at(-1));
      assert.deepEqual(py, ['highlight', 'xhs-synth0001', '这一句重点', '--color', 'blue', '--json'], `${theme}：换色 ${py}`);
      assert.ok(await page.evaluate(() => !!document.querySelector('mark.lb-hl-blue') && !document.querySelector('.lb-hl-pop')), `${theme}：先乐观换上、小条关掉`);
      // 后台没写上 → 退回
      await page.evaluate(() => { window.__pyAnswer = { ok: false, message: '没找到这段原文', changed: [], already: [] }; });
      await page.locator('mark.lb-hl-blue').click(); await S.settle(40);
      await page.locator('.lb-hl-pop .lb-hl-dot-purple').click(); await S.settle(60);
      assert.ok(await page.evaluate(() => !!document.querySelector('mark.lb-hl-blue') && !document.querySelector('mark.lb-hl-purple')), `${theme}：没写上退回原色`);
      // 取消：点小条「取消」= 拆掉（成功）
      await page.evaluate(() => { window.__pyAnswer = { ok: true, changed: ['绿色那句'], already: [] }; });
      await page.locator('mark.lb-hl-green').click(); await S.settle(40);
      await page.locator('.lb-hl-pop .lb-hl-off').click(); await S.settle(60);
      py = await page.evaluate(() => window.__py.at(-1));
      assert.deepEqual(py, ['highlight', 'xhs-synth0001', '绿色那句', '--remove', '--json'], `${theme}：点取消 ${py}`);
      assert.ok(await page.evaluate(() => !document.querySelector('mark.lb-hl-green') && document.querySelector('.lb-body p').textContent.includes('绿色那句')), `${theme}：取消后字还在`);
      // Esc 关小条
      await page.locator('mark.lb-hl-blue').click(); await S.settle(40);
      await page.keyboard.press('Escape'); await S.settle(40);
      assert.ok(!(await page.evaluate(() => !!document.querySelector('.lb-hl-pop'))), `${theme}：Esc 关小条`);
      // 取消了的那条从批注区消失（MutationObserver 带着重列）
      await S.settle(120);
      const left = await page.evaluate(() => [...document.querySelectorAll('.lba-mark-row')].map(r => r.textContent));
      assert.ok(!left.includes('绿色那句'), `${theme}：取消的重点不在批注区了 ${left}`);
      // 右键已划的：换颜色 ▸ + 取消重点
      await page.evaluate(() => { getSelection().removeAllRanges(); document.querySelector('mark.lb-hl-blue').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 200, clientY: 200 })); });
      menu = await page.evaluate(() => window.__menus.at(-1));
      assert.deepEqual(menu.map(x => x[0]), ['换颜色', '取消重点'], `${theme}：右键重点 ${JSON.stringify(menu)}`);
      await S.screenshot(`note-highlight-${theme}`);
      assert.deepEqual(await S.pageErrors(), []);
      await page.close();
    }
    console.log('PASS note_highlight_ui：默认黄 · 选颜色划 · 点重点出小条（换色 / 取消，没写上退回）· Esc 关 · 右键换颜色 / 取消 · 视频文字稿标题小字浅色');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error('FAIL note_highlight_ui', e && e.stack || e); process.exit(1); });

// 批次 D 地基：外壳自检（playwright）——证明测试架抓得到真宿主的毛病，防止有人把外壳「修」得不像真宿主。
//   ① 守卫：dataviewjs 容器带行内 overflow-x:auto；实时预览有 .cm-embed-block:hover{overflow:hidden}（在 @media (hover: hover) 里，且外壳浏览器匹配）
//      和 contain:paint；widget 结构 .embed-actions > .edit-block-button；祖先链对。
//   ② 红线（041aca9 的页面资产，git show 只读取）：C1 吸顶在阅读视图 / 实时预览两种宿主里都红；C4 重跑失焦在两种宿主里都红。
//   ③ 对照：同一个探针也能转绿——只修容器 overflow：阅读视图吸住了但停在 32px 内边距下沿（缝里露卡片，严格口径仍红），实时预览照样失效
//      （:hover 规则被复现了）；两条 overflow:visible + top 设成负的 --file-margins-y → 两种宿主都贴住滚动容器顶、转绿。
//      用地基的 LB.mountHost 搭的最小页面重跑 3 次焦点还在，不用 host 的同一页失焦。
//   ④ 另外两种宿主能起：笔记页（后台 leaf 藏着、状态栏在）、设置窗（内容宽 = 设定值）。
//   ⑤ 真 Chromium：重跑清空容器时有焦点的输入框同步收到 blur（还连着文档）+ 冒泡的 focusout（tests/_fakedom.cjs 照这个做）。
//   ⑥ 红线（7ab44c6 的批注资产）：单栏笔记里批注框在 dv.container 里，重跑 → blur → 半截字被存成正式批注；对照：生产左栏结构不受影响。
// 输出：每个探针的读数打印出来（红的输出要记进地基报告 / 各线验收文件）；截图进 LWA_QA_DIR。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const REV = '041aca9';
const log = (...a) => console.log(...a);

(async () => {
  shell.requirePlaywright();
  if (!shell.revAvailable(REV)) { console.log(`SKIP 本仓库里没有 ${REV}（浅克隆？），红线自检没跑`); process.exit(shell.SKIP); }
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 90 });
  const results = {};
  try {
    for (const host of ['page-reading', 'page-live']) {
      const tag = host === 'page-live' ? '实时预览' : '阅读视图';
      // ── ① 守卫 + ② C1 红 ──
      let page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      let S = await shell.page(page, { host, kind: 'catalog', rev: REV, data });
      const g = await S.guards();
      assert.equal(g.containerInlineOverflowX, 'auto', `${tag}：dataviewjs 容器要有 Dataview 写的行内 overflow-x:auto`);
      assert.equal(g.containerComputedOverflowY, 'auto', `${tag}：overflow-x:auto 让容器成了滚动容器（overflow-y 计算值 auto）`);
      if (host === 'page-live') {
        assert.ok(g.hoverOverflowHidden, '实时预览：外壳 CSS 要有 .cm-embed-block:hover{overflow:hidden}（Obsidian 1.14.4）');
        assert.ok(g.hoverInMedia, '实时预览：那条 :hover 规则和真 app.css 一样放在 @media (hover: hover) 里');
        assert.ok(g.hoverMediaMatches, '外壳浏览器匹配 (hover: hover)（Windows 桌面 Obsidian 有鼠标，规则生效）');
        assert.ok(g.containPaint, '实时预览：外壳 CSS 要有 .cm-content > [contenteditable=false]{contain:paint}（Obsidian 1.14.4）');
        assert.ok(g.inEmbedBlock, '实时预览：容器在 .cm-embed-block.cm-lang-dataviewjs 里');
        assert.ok(g.embedActions, '实时预览：widget 里是 .embed-actions > .edit-block-button（1.14.4 addEditButton）');
      } else assert.ok(g.inPreviewView, '阅读视图：容器在 .markdown-preview-view 里');
      assert.ok(await page.$('.lbc-top'), `${tag}：041aca9 的目录页画出来了`);
      const c1 = await S.probeSticky({ target: '.lbc-top', by: 1500 });
      results[`C1 ${tag}（041aca9）`] = c1;
      log(`C1 吸顶 ${tag} @${REV}:`, JSON.stringify(c1));
      assert.equal(c1.ok, false, `${tag}：041aca9 的吸顶在外壳里必须是红的（外壳抓得到 C1）`);
      assert.ok(c1.scrollTop >= 1400, '真的滚下去了');
      await S.screenshot(`rig-c1-${host}-${REV}`);
      // ③ 对照：只给容器加 overflow:visible（目录线修法的第一条）
      await page.addStyleTag({ content: '.lb-catalog .block-language-dataviewjs{overflow:visible!important}' });
      await S.scrollTo(0);
      const c1fix = await S.probeSticky({ target: '.lbc-top', by: 1500 });
      results[`C1 ${tag} 只加容器 overflow:visible`] = c1fix;
      log(`C1 对照 ${tag}（容器 overflow:visible）:`, JSON.stringify(c1fix));
      let stuckAtPad = c1fix;
      if (host === 'page-live') {
        assert.equal(c1fix.embedHovered, true, '实时预览：鼠标停在页上');
        assert.ok(c1fix.delta < -100, '实时预览：只修容器还不够，:hover{overflow:hidden} 照样让吸顶失效（外壳复现了第二个根因）');
        await page.addStyleTag({ content: '.markdown-source-view.lb-catalog .cm-embed-block.cm-lang-dataviewjs,.markdown-source-view.lb-catalog .cm-embed-block.cm-lang-dataviewjs:hover{overflow:visible!important}' });
        await S.scrollTo(0);
        stuckAtPad = await S.probeSticky({ target: '.lbc-top', by: 1500 });
        results['C1 实时预览 两条 overflow:visible（contain:paint 还在）'] = stuckAtPad;
        log('C1 对照 实时预览（两条 overflow:visible，contain:paint 未动）:', JSON.stringify(stuckAtPad));
      }
      // 吸住了，但停在滚动容器上内边距（--file-margins-y = 32px）的下沿：顶栏上方 32px 的缝里露出滚上去的卡片 → 严格口径判红（复审）
      assert.equal(stuckAtPad.ok, false, `${tag}：top:0 吸在内边距下沿，缝里露卡片，探针判红`);
      assert.equal(stuckAtPad.delta, stuckAtPad.padTop, `${tag}：停在内边距下沿（delta = padTop）`);
      assert.ok(stuckAtPad.gap && stuckAtPad.gap.some(x => x && /lbc-/.test(x)), `${tag}：缝里是页面内容（${JSON.stringify(stuckAtPad.gap)}）`);
      await S.screenshot(`rig-c1-${host}-gap`);
      // ③ 对照：再把吸顶的 top 设成负的内边距 → 贴住滚动容器顶，|delta| ≤ 1，转绿（contain:paint 不影响）
      await page.addStyleTag({ content: '.lb-catalog .lbc-top{top:calc(-1 * var(--file-margins-y))!important}' });
      await S.scrollTo(0);
      const flush = await S.probeSticky({ target: '.lbc-top', by: 1500 });
      results[`C1 ${tag} overflow:visible + top 负内边距`] = flush;
      log(`C1 对照 ${tag}（overflow:visible + top:calc(-1 * var(--file-margins-y))）:`, JSON.stringify(flush));
      assert.equal(flush.ok, true, `${tag}：贴住滚动容器顶后探针转绿（探针不是永远红）`);
      assert.ok(Math.abs(flush.delta) <= 1);
      await page.close();

      // ── ② C4 红 ──
      page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      S = await shell.page(page, { host, kind: 'catalog', rev: REV, data });
      const c4 = await S.probeFocusAfterRerun({ input: '.lbc-search', text: 'kafei', reruns: 3 });
      results[`C4 ${tag}（041aca9）`] = c4;
      log(`C4 重跑失焦 ${tag} @${REV}:`, JSON.stringify(c4));
      assert.equal(c4.ok, false, `${tag}：041aca9 后台重跑时搜索框必须失焦（外壳抓得到 C4）`);
      assert.equal(c4.focused, false);
      await page.close();

      // ③ 对照：地基 LB.mountHost 的最小页面，焦点经得起重跑；不用 host 的同一页失焦
      for (const useHost of [true, false]) {
        page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
        const code = shell.readAsset('lb-page-lib.js') + `
const LB = lbPageLib(dv, app, 'catalog');
if (await LB.reuseDom()) return;
const mount = ${useHost ? "LB.mountHost('probe-host')" : 'dv.container'};
const wrap = mount.createEl('div', { cls: 'lbc-wrap' });
wrap.createEl('input', { cls: 'probe-input', type: 'search' });
LB.keep(wrap, { version: await LB.data.version() });`;
        S = await shell.page(page, { host, code, data });
        const r = await S.probeFocusAfterRerun({ input: '.probe-input', text: 'kafei', reruns: 3 });
        results[`C4 对照 ${tag} ${useHost ? 'mountHost' : '挂在容器里'}`] = r;
        log(`C4 对照 ${tag}（${useHost ? '地基 mountHost' : '挂在容器里'}）:`, JSON.stringify(r));
        assert.equal(r.ok, useHost, useHost ? `${tag}：页面挂在 host 上，重跑 3 次焦点和字都在` : `${tag}：挂在容器里就失焦`);
        if (useHost) {
          const hostInfo = await page.evaluate(() => { const c = window.__shell.container, h = c.nextElementSibling; return { sibling: !!h && h.classList.contains('lb-page-host'), role: h && h.dataset.lbRole, empty: c.children.length === 0 }; });
          assert.deepEqual(hostInfo, { sibling: true, role: 'catalog', empty: true }, 'host 是容器的兄弟，容器本身空着');
          await S.recreate();   // CM 重建 widget / section 重画：旧 component 卸载 → 旧 host 摘掉，只剩新的一个
          assert.equal(await page.evaluate(() => document.querySelectorAll('.lb-page-host').length), 1, '重建后只有一个 host');
        }
        await page.close();
      }
    }

    // ── ⑤ 真 Chromium 的失焦事件（_fakedom 照它做）：Dataview 重跑 innerHTML='' 时，容器里有焦点的输入框同步收到 blur（还连着文档）+ 冒泡的 focusout ──
    {
      const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
      const S = await shell.page(page, { host: 'page-reading', data, code: `
if (!dv.container.querySelector('.probe-input')) {
  const i = dv.container.createEl('input', { cls: 'probe-input' });
  window.__blurLog = window.__blurLog || [];
  i.addEventListener('blur', e => window.__blurLog.push(['blur', i.isConnected, document.activeElement === document.body, e.relatedTarget, e.bubbles]));
  dv.container.parentElement.addEventListener('focusout', e => window.__blurLog.push(['focusout@section', e.target === i]));
}` });
      await page.click('.probe-input');
      await S.rerun();
      const seen = await page.evaluate(() => window.__blurLog);
      log('真 Chromium 重跑清空容器时的失焦事件:', JSON.stringify(seen));
      assert.deepEqual(seen, [['blur', true, true, null, false], ['focusout@section', true]], '重跑清空容器：先同步发 blur（还连着、不冒泡）+ focusout（冒泡），_fakedom 照这个做');
      await page.close();
    }

    // ── ⑥ 红线（批注，复审）：单栏笔记里批注框留在 dv.container（没有 .lb-side 可挪）。重跑时输入框收到 blur → ta.onblur = commit
    //    把半截字存成正式批注、清空输入框。批次 D 基线 7ab44c6 上必须红；对照：生产左栏结构（.xhs-note .lb-side）焦点和字都在、什么都不存。
    const BASE = '7ab44c6';
    if (shell.revAvailable(BASE)) {
      const NOTE = '_archive/xiaohongshu/n1/notes.json';
      const files = { [NOTE]: JSON.stringify({ starred: false, annotations: [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }] }) };
      const single = '<div class="lb-note"><div class="lb-main"><div class="lb-scroll"><p>没有图片的单栏笔记</p></div></div></div>';
      const twoCol = '<div class="lb-note"><div class="lb-side"><div class="lb-carousel"></div></div><div class="lb-main"><div class="lb-scroll"><p>正文</p></div></div></div>';
      for (const [label, mdHtml, rev] of [['单栏 @' + BASE, single, BASE], ['左栏（生产结构，当前资产）', twoCol, null]]) {
        const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        const S = await shell.note(page, { kind: 'annotate', rev, mdHtml, files, params: { itemId: 'xhs-n1', notePath: NOTE } });
        await page.click('.lba-annot-input');
        await page.keyboard.type('正在打的');
        await S.rerun();
        await page.waitForTimeout(150);   // commit 里的 persist 是异步的
        const r = await page.evaluate(async note => {
          const ta = document.querySelector('.lba-annot-input');
          const saved = JSON.parse(await window.app.vault.adapter.read(note)).annotations.map(a => a.text);
          return { inContainer: !!ta.closest('.block-language-dataviewjs'), focused: document.activeElement === ta, value: ta.value, saved };
        }, NOTE);
        log(`批注 ${label}：重跑一次后`, JSON.stringify(r));
        if (rev) {
          assert.equal(r.inContainer, true, '单栏：批注框在 dv.container 里');
          assert.ok(r.saved.includes('正在打的'), '红线：半截字被存成了一条正式批注');
          assert.equal(r.value, '', '红线：输入框被清空'); assert.equal(r.focused, false, '红线：焦点没了');
        } else {
          assert.equal(r.inContainer, false, '左栏：批注框挪出了 dv.container');
          assert.deepEqual(r.saved, ['旧的'], '左栏：什么都没存'); assert.equal(r.value, '正在打的'); assert.equal(r.focused, true);
        }
        await page.close();
      }
    } else log(`（本仓库没有 ${BASE}：跳过批注单栏红线）`);

    // ── ④ 笔记页 / 设置窗 宿主能起 ──
    let page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    let S = await shell.note(page, { variant: 'background', mdHtml: '<div class="lb-note"><div class="lb-side"><div class="lb-carousel"></div></div><div class="lb-main"><div class="lb-scroll"><p>正文</p></div></div></div>' });
    const note = await page.evaluate(() => ({
      xhs: !!document.querySelector('.workspace-leaf.mod-active .markdown-preview-view.xhs-note.link-brain'),
      bg: (() => { const l = [...document.querySelectorAll('.workspace-split.mod-root .workspace-leaf')].find(x => !x.classList.contains('mod-active')); return l ? { shown: l.isShown(), display: getComputedStyle(l).display } : null; })(),
      statusBar: getComputedStyle(document.querySelector('.status-bar')).position,
      annotContainer: (document.querySelector('.workspace-leaf.mod-active .block-language-dataviewjs') || {}).style?.overflowX,
      css: !!document.getElementById('lb-test-link-brain-css') && !!document.getElementById('lb-test-plugin-styles'),
    }));
    log('笔记页宿主:', JSON.stringify(note));
    assert.deepEqual(note, { xhs: true, bg: { shown: false, display: 'none' }, statusBar: 'fixed', annotContainer: 'auto', css: true });
    await S.screenshot('rig-note-reading');
    await page.close();
    for (const width of [650, 800, 1100]) {
      page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
      S = await shell.settings(page, { contentWidth: width, theme: 'dark' });
      const w = await page.evaluate(() => { const c = document.querySelector('.modal.mod-settings .vertical-tab-content'); const cs = getComputedStyle(c); return Math.round(c.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)); });
      assert.ok(Math.abs(w - width) <= 2, `设置窗内容宽 ${w} ≈ ${width}`);
      await page.close();
    }
  } finally { await browser.close(); }
  console.log('PASS rig selfcheck: guards (inline overflow-x:auto, live :hover overflow:hidden inside @media (hover: hover) + contain:paint, .embed-actions, ancestor chains); 041aca9 assets → C1 red in reading & live, C4 red in reading & live; controls: overflow fix alone sticks 32px below the scroller top (gap shows cards → still red), overflow fix + negative --file-margins-y top turns both hosts green, live hover rule reproduced, mountHost keeps focus; real Chromium fires blur + focusout on rerun removal; single-column annotate red on 7ab44c6 (half-typed text committed), left column control clean; note / settings hosts render');
})().catch(e => { console.error(e); process.exit(1); });

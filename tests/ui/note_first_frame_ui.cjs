// 1011 她：打开一篇笔记，先露出没渲染好的原始样子（属性块里一大段 link_brain JSON、蓝色「Lb topbar」框 + 原样链接、
// 字面的 <!-- link-brain:content:start -->），停一下才变成正常页面。
// 根因两层：①目录 / 链接走 openLinkText 不带 mode，按她的默认（实时预览）先渲一遍，插件 file-open 才切阅读视图（main.js
// previewOpenState / patchOpenFile 修，node 用例 tests/test_note_open_preview_1011.cjs）；②cssclasses（link-brain xhs-note）要等
// Obsidian 解析完属性才挂到视图上，在那之前 link-brain.css 里所有 .xhs-note 规则都不生效（本用例）。
// 做法：外壳里照 Obsidian 的顺序摆——视图先出来、还没有 .xhs-note（阅读视图 / 实时预览各一遍），隔 3 帧才挂上类；
// 每一帧（requestAnimationFrame，绘制前那一刻的计算样式 = 这一帧画出来的样子）记：属性块显不显示、顶栏 callout 有没有框和标题、
// 注释那一行显不显示、正文整块露不露。断言：挂上类之前没有任何一帧露出原始样子；挂上类那一帧立刻正常显示；类一直不来也最多遮 1.2 秒。
// 红线：LWA_FIRSTFRAME_REV=d222a02 跑改前的 link-brain.css → 第 0 帧属性块、蓝框标题、注释行全露（读数记在验收文件）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const shell = require('../_obsidian_shell.cjs');

const REV = process.env.LWA_FIRSTFRAME_REV || null;
const NOTE_CSS = shell.readAsset('link-brain.css', REV);
const PLUGIN_CSS = shell.readAsset('styles.css', REV, 'obsidian-plugins/link-brain-actions');

// Obsidian 1.x 属性块的结构（metadata-container > metadata-content > metadata-properties > metadata-property[data-property-key]）
const PROPS = '<div class="metadata-container" tabindex="-1" data-property-count="3"><div class="metadata-properties-heading"><div class="metadata-properties-title">属性</div></div>'
  + '<div class="metadata-content"><div class="metadata-properties">'
  + '<div class="metadata-property" tabindex="0" data-property-key="cssclasses" data-property-type="multitext"><div class="metadata-property-key">cssclasses</div><div class="metadata-property-value">link-brain xhs-note</div></div>'
  + '<div class="metadata-property" tabindex="0" data-property-key="tags" data-property-type="tags"><div class="metadata-property-key">tags</div><div class="metadata-property-value">合成</div></div>'
  + '<div class="metadata-property" tabindex="0" data-property-key="link_brain" data-property-type="unknown"><div class="metadata-property-key">link_brain</div><div class="metadata-property-value">{"item_id":"xhs-synth0001","source":"xiaohongshu"}</div></div>'
  + '</div></div></div>';
const TOPBAR = '<div data-callout-metadata="" data-callout-fold="" data-callout="lb-topbar" class="callout"><div class="callout-title" dir="auto"><div class="callout-icon"></div><div class="callout-title-inner">Lb topbar</div></div>'
  + '<div class="callout-content"><p dir="auto"><a class="lb-topbar-back" href="#">← 目录</a><a class="external-link" href="https://www.xiaohongshu.com/explore/synth0001">原文</a>'
  + '<a class="internal-link" href="_archive/xiaohongshu/synth0001/derived/agent.md">机读版</a></p></div></div>';
function noteHtml() {
  const html = fs.readFileSync(path.join(shell.ROOT, 'tests', 'fixtures', 'note-page', 'image-3x4.html'), 'utf8');
  return html.replace(/<img src="\.\.\/\.\.\/[^"]+"/g, '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="');
}
// 阅读视图（Obsidian 1.x）：视图 > sizer > 每段一个 div；mdCls = 已挂上的 cssclasses
function readingView(mdCls) {
  return `<div class="markdown-reading-view" style="width:100%;height:100%;"><div class="markdown-preview-view markdown-rendered node-insert-event is-readable-line-width allow-fold-headings show-indentation-guide allow-fold-lists show-properties ${mdCls}">`
    + `<div class="markdown-preview-sizer markdown-preview-section"><div class="markdown-preview-pusher" style="width:1px;height:0.1px;margin-bottom:0px;"></div>`
    + `<div class="mod-header mod-ui"><div class="inline-title">合成笔记</div>${PROPS}</div>`
    + `<div class="el-div">${TOPBAR}</div><div class="el-div">${noteHtml()}</div><div class="mod-footer mod-ui"></div></div></div></div>`;
}
// 实时预览：属性块在 cm-sizer 里、注释是 .cm-line 里的 .cm-comment、HTML 块是 cm-html-embed 小部件
function liveView(mdCls) {
  return `<div class="markdown-source-view cm-s-obsidian mod-cm6 node-insert-event is-readable-line-width is-live-preview is-folding show-properties ${mdCls}">`
    + `<div class="cm-editor"><div class="cm-scroller"><div class="cm-sizer"><div class="inline-title" contenteditable="true">合成笔记</div>${PROPS}`
    + `<div class="cm-contentContainer"><div class="cm-content cm-lineWrapping" contenteditable="true" role="textbox">`
    + `<div class="cm-embed-block cm-callout" contenteditable="false">${TOPBAR}</div>`
    + `<div class="cm-line lb-test-comment-line"><span class="cm-comment">&lt;!-- link-brain:content:start --&gt;</span></div>`
    + `<div class="cm-html-embed cm-embed-block" contenteditable="false">${noteHtml()}</div>`
    + `<div class="cm-line"><br></div></div></div></div></div></div></div>`;
}

async function open(page, mode) {
  const styles = [`<style>${shell.THEME_CSS}</style>`, `<style>${shell.SUBSET_CSS}</style>`, `<style>${shell.SHELL_CSS}</style>`,
    `<style id="lb-test-link-brain-css">${NOTE_CSS}</style>`, `<style id="lb-test-plugin-styles">${PLUGIN_CSS}</style>`].join('');
  // 起点：目录页那个标签（换文件时 Obsidian 复用同一个 leaf）
  const leaf = `<div class="workspace-leaf mod-active"><div class="workspace-leaf-content" data-type="markdown" data-mode="${mode === 'live' ? 'source' : 'preview'}">`
    + `<div class="view-header"><div class="view-header-title-container"><div class="view-header-title">📘【小红书收藏目录】</div></div><div class="view-actions"></div></div>`
    + `<div class="view-content lb-test-view"></div></div></div>`;
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8">${styles}</head><body class="theme-light mod-windows is-focused">`
    + `<div class="app-container"><div class="horizontal-main-container"><div class="workspace"><div class="workspace-split mod-vertical mod-root"><div class="workspace-tabs mod-top mod-active"><div class="workspace-tab-container">${leaf}</div></div></div></div></div></div></body></html>`);
}

// 在页面里按 Obsidian 的顺序换上这篇：先插视图（没有 cssclasses），classAt 帧之后才挂 link-brain xhs-note（null = 一直不挂）；
// 每帧记一次读数，记 frames 帧（另可等到 waitMs 再记一帧）
function play(page, { mode, classAt, frames = 8, waitMs = 0 }) {
  const html = mode === 'live' ? liveView('') : readingView('');
  return page.evaluate(async ({ html, mode, classAt, frames, waitMs }) => {
    const host = document.querySelector('.lb-test-view');
    const vis = el => { if (!el) return null; for (let e = el; e && e.nodeType === 1; e = e.parentElement) { const s = getComputedStyle(e); if (s.display === 'none') return false; } return getComputedStyle(el).visibility !== 'hidden'; };
    const read = k => {
      const view = host.querySelector('.markdown-preview-view, .markdown-source-view');
      const callout = host.querySelector('.callout[data-callout="lb-topbar"]');
      const cs = callout ? getComputedStyle(callout) : null;
      return { frame: k, cls: view.classList.contains('xhs-note'),
        props: vis(host.querySelector('.metadata-container')),
        linkBrainJson: vis(host.querySelector('.metadata-property[data-property-key="link_brain"]')),
        calloutTitle: vis(callout && callout.querySelector('.callout-title')),
        calloutBox: !!cs && (parseFloat(cs.borderLeftWidth) > 0 || parseFloat(cs.paddingTop) > 0 || (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent')),
        topbarLinks: vis(callout && callout.querySelector('a.external-link')),
        comment: mode === 'live' ? vis(host.querySelector('.lb-test-comment-line')) : null,
        note: vis(host.querySelector('.lb-note')) };
    };
    const out = [];
    await new Promise(done => {
      let k = 0;
      host.innerHTML = html;   // Obsidian 渲出视图：这一帧还没有 cssclasses
      const tick = () => {
        if (classAt !== null && k === classAt) host.querySelector('.markdown-preview-view, .markdown-source-view').classList.add('link-brain', 'xhs-note');
        out.push(read(k));
        k += 1;
        if (k < frames) requestAnimationFrame(tick); else done();
      };
      requestAnimationFrame(tick);
    });
    if (waitMs) { await new Promise(r => setTimeout(r, waitMs)); await new Promise(r => requestAnimationFrame(r)); out.push({ ...read('after ' + waitMs + 'ms'), late: true }); }
    return out;
  }, { html, mode, classAt, frames, waitMs });
}

const raw = f => f.props || f.linkBrainJson || f.calloutTitle || f.calloutBox || f.comment || (!f.cls && (f.note || f.topbarLinks));

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const report = { rev: REV || 'working tree', runs: [] };
  let red = [];
  try {
    for (const mode of ['reading', 'live']) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
      await open(page, mode);
      // ① 类在第 3 帧才挂上（Obsidian 的真实顺序：视图先渲、属性解析完才挂 cssclasses）
      const seq = await play(page, { mode, classAt: 3, frames: 7 });
      report.runs.push({ mode, case: 'class-at-frame-3', frames: seq });
      console.log(`首帧（${mode}，第 3 帧才挂 .xhs-note）：`, JSON.stringify(seq));
      const shown = seq.filter(raw).map(f => f.frame);
      if (REV) { red.push({ mode, rawFrames: shown, first: seq[0] }); await page.close(); continue; }
      assert.deepEqual(shown, [], `${mode}：挂上 .xhs-note 之前没有任何一帧露出原始样子（露了：第 ${shown.join(' / ')} 帧）`);
      assert.ok(seq.slice(0, 3).every(f => f.props === false && f.linkBrainJson === false), mode + '：属性块（含 link_brain JSON）从第 0 帧起就不显示');
      assert.ok(seq.slice(0, 3).every(f => f.calloutTitle === false && !f.calloutBox), mode + '：顶栏不是蓝框、没有「Lb topbar」标题');
      if (mode === 'live') assert.ok(seq.every(f => f.comment === false), 'live：<!-- link-brain:content:start --> 那一行哪一帧都不显示');
      assert.ok(seq.slice(3).every(f => f.cls && f.note === true && f.topbarLinks === true), mode + '：挂上 .xhs-note 那一帧起正文和顶栏立刻显示');
      // ② cssclasses 一直不来（她把属性删了 / Obsidian 出岔子）：最多遮 1.2 秒，之后照样看得到（不永远空白）
      await open(page, mode);
      const never = await play(page, { mode, classAt: null, frames: 3, waitMs: 1400 });
      report.runs.push({ mode, case: 'class-never', frames: never });
      const last = never[never.length - 1];
      console.log(`首帧（${mode}，一直没有 .xhs-note）：`, JSON.stringify(never));
      assert.ok(never.slice(0, 3).every(f => f.note === false), mode + '：没类的头几帧先不露');
      assert.ok(last.late && last.note === true && last.props === false, mode + '：1.2 秒后放行正文（属性块照样藏着）');
      // ③ 目录页 / 问收藏页（没有 .lb-note）不受影响：同样没类，第 0 帧就可见
      await open(page, mode);
      const other = await page.evaluate(() => { const h = document.querySelector('.lb-test-view');
        h.innerHTML = '<div class="markdown-reading-view"><div class="markdown-preview-view markdown-rendered lb-catalog"><div class="markdown-preview-sizer markdown-preview-section"><div class="el-p"><p class="lb-test-p">目录</p></div></div></div></div>';
        return getComputedStyle(h.querySelector('.markdown-preview-sizer')).visibility; });
      assert.equal(other, 'visible', mode + '：不是归档笔记的页面不遮');
      await page.screenshot({ path: path.join((fs.mkdirSync(shell.QA_DIR, { recursive: true }), shell.QA_DIR), `note-first-frame-${mode}.png`) });
      await page.close();
    }
    fs.mkdirSync(shell.QA_DIR, { recursive: true });
    fs.writeFileSync(path.join(shell.QA_DIR, `note-first-frame${REV ? '-' + REV : ''}.json`), JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
  if (REV) {
    console.log('红线读数（' + REV + '）：', JSON.stringify(red));
    const anyRaw = red.some(r => r.rawFrames.length);
    if (!anyRaw) { console.error(`红线没红：${REV} 的 CSS 下也没露原始样子，用例没抓到她看到的那一下`); process.exit(1); }
    console.log(`RED as expected on ${REV}: raw frames before .xhs-note → ` + red.map(r => `${r.mode} ${r.rawFrames.join('/')}`).join('; '));
    return;
  }
  console.log('PASS note first frames (1011): before cssclasses land (reading + live preview) no frame shows the properties block / link_brain JSON / blue "Lb topbar" callout / content:start comment; content shows the frame .xhs-note lands; never-landing class unveils after 1.2s; non-note pages untouched');
})().catch(e => { console.error(e); process.exit(1); });

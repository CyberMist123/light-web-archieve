// Obsidian 外壳（playwright，批次 D 地基，合入后冻结）：在真 Chromium 里按 Obsidian 1.14.4 + Dataview 0.5.68 的真实层级和 CSS 搭宿主，
// 让页面测试抓得到「测试过了、真机坏了」的那类问题（C1 吸顶失效、C4 重跑失焦）。四种宿主：
//   page-reading  目录 / 问收藏 / 回收站页，阅读视图：滚动容器是 .markdown-preview-view；dataviewjs 容器带 Dataview 写的行内 overflow-x:auto
//   page-live     同上，实时预览：滚动容器是 .cm-scroller；容器在 .cm-preview-code-block.cm-embed-block 里，带 :hover{overflow:hidden} 和 contain:paint
//   note-reading  笔记页：ribbon / 左侧栏 / 标签栏 / 视图头 / 状态栏，载入真 link-brain.css 和插件 styles.css；
//                 变体 background（多一个 display:none 的后台 leaf）、popover（.hover-popover 里再嵌一份）、source-reader（.lb-source-reader）、mobile
//   settings-modal 设置窗（.modal.mod-settings，左 200px 分页 + 右侧滚动内容，内容宽 650 / 800 / 1100）
// 主题：light / dark / orange（亮色 + 改过 --color-orange / --text-warning 的第三方主题）。
// Dataview 模拟和真的一样：shell.rerun() = 同一个容器、同一个 component，先 innerHTML='' 再跑脚本；recreate() = 换新容器和新 component。
// 可选：设 LWA_OBSIDIAN_APP_CSS=<tests/tools/obsidian_css.py 抽到 scratch 的 app.css> 时，把真 app.css 注入在手写子集前面（绝不进仓）。
// 用法（tests/ui/*.cjs）：
//   const shell = require('../_obsidian_shell.cjs');
//   const pw = shell.requirePlaywright();                 // 没装 playwright → 打印「UI 层没跑」并以 77 退出（run-node 记 SKIP）
//   const browser = await shell.launch();                 // 默认 channel msedge，起不来退回 playwright 自带 chromium
//   const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
//   const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme: 'light', data: shell.makeCatalogData({ n: 60 }) });
//   await S.rerun(); const r = await S.probeSticky({ target: '.lbc-top' });
// 守卫（tests/test_rig_selfcheck.cjs 和 tests/ui/rig_selfcheck_ui.cjs）：别把外壳「修」得不像真宿主。
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { installObsidianDom, browserSource } = require('./_fakeobsidian.cjs');
const { miniMdSource } = require('./_mini_md.cjs');

const ROOT = path.resolve(__dirname, '..');
const SKIP = 77;
const QA_DIR = process.env.LWA_QA_DIR || path.join(os.tmpdir(), 'lwa-qa');

// ── CSS ──────────────────────────────────────────────────────────────────────────────────────────────
// 主题变量：出处 Obsidian 1.14.4 app.css 的 body / .theme-light / .theme-dark 默认值（节选，值照原样；字体换成本机有的）
const THEME_CSS = `
body{--header-height:40px;--ribbon-width:44px;--layer-menu:65;--layer-modal:50;--layer-notice:60;--status-bar-position:fixed;--file-line-width:700px;
--file-margins-x:32px;--file-margins-y:32px;--file-margins:var(--file-margins-y) var(--file-margins-x);--font-text-size:16px;--font-preferred-size:var(--font-text-size);
--font-ui-smaller:12px;--font-ui-small:13px;--font-ui-medium:15px;--line-height-normal:1.5;--line-height-tight:1.3;--radius-s:4px;--radius-m:8px;--radius-l:12px;--size-2-1:2px;--size-2-2:4px;--size-2-3:6px;
--size-4-1:4px;--size-4-2:8px;--size-4-3:12px;--size-4-4:16px;--size-4-5:20px;--size-4-6:24px;--size-4-8:32px;--size-4-12:48px;--dialog-width:560px;--dialog-max-width:80vw;
--accent-h:258;--accent-s:88%;--accent-l:66%;
--font-default:ui-sans-serif,-apple-system,BlinkMacSystemFont,system-ui,"Segoe UI","Microsoft YaHei",Roboto,sans-serif;--font-interface:var(--font-default);--font-text:var(--font-default);--font-monospace:ui-monospace,Consolas,monospace;
--background-primary:var(--color-base-00);--background-primary-alt:var(--color-base-10);--background-secondary:var(--color-base-20);--background-secondary-alt:var(--color-base-05);
--background-modifier-border:var(--color-base-30);--background-modifier-border-hover:var(--color-base-35);--background-modifier-border-focus:var(--color-base-40);
--background-modifier-hover:color-mix(in oklch,var(--mono-100) 6.7%,transparent);--background-modifier-message:color-mix(in oklch,black 90%,transparent);
--text-normal:var(--color-base-100);--text-muted:var(--color-base-70);--text-faint:var(--color-base-50);--text-error:var(--color-red);--text-warning:var(--color-orange);--text-success:var(--color-green);
--text-on-accent:white;--color-accent:hsl(var(--accent-h),var(--accent-s),var(--accent-l));--text-accent:var(--color-accent);--link-color:var(--text-accent);
--interactive-accent:var(--color-accent-1);--interactive-normal:var(--color-base-00);--interactive-hover:var(--color-base-10);
--modal-background:var(--background-primary);--menu-background:var(--background-secondary);--notice-background:var(--background-modifier-message);--code-background:var(--background-primary-alt);
--titlebar-background:var(--background-secondary);--tab-container-background:var(--background-secondary);--ribbon-background:var(--background-secondary);--status-bar-background:var(--background-secondary);
--divider-color:var(--background-modifier-border);--embed-block-shadow-hover:0 0 0 1px var(--background-modifier-border),inset 0 0 0 1px var(--background-modifier-border);}
.theme-light{color-scheme:light;--color-base-00:#ffffff;--color-base-05:#fcfcfc;--color-base-10:#fafafa;--color-base-20:#f6f6f6;--color-base-25:#efefef;--color-base-30:#e4e4e4;--color-base-35:#dadada;--color-base-40:#bdbdbd;--color-base-50:#ababab;--color-base-60:#707070;--color-base-70:#5c5c5c;--color-base-100:#222222;
--color-orange:#ec7500;--color-red:#e93147;--color-green:#08b94e;--color-yellow:#e0ac00;--color-accent-1:hsl(calc(var(--accent-h) - 1),calc(var(--accent-s) * 1.01),calc(var(--accent-l) * 1.075));--mono-100:black;}
.theme-dark{color-scheme:dark;--color-base-00:#1C1C1C;--color-base-05:#212121;--color-base-10:#232323;--color-base-20:#282828;--color-base-25:#2e2e2e;--color-base-30:#333333;--color-base-35:#3f3f3f;--color-base-40:#555555;--color-base-50:#666666;--color-base-60:#999999;--color-base-70:#b3b3b3;--color-base-100:#dadada;
--color-orange:#e9973f;--color-red:#fb464c;--color-green:#44cf6e;--color-yellow:#e0de71;--color-accent-1:hsl(calc(var(--accent-h) - 3),calc(var(--accent-s) * 1.02),calc(var(--accent-l) * 1.15));--mono-100:white;
--interactive-accent:var(--color-accent);--interactive-normal:var(--color-base-30);--interactive-hover:var(--color-base-35);--text-accent:var(--color-accent-1);--background-secondary-alt:var(--color-base-30);}
/* 测试架自己的：模拟一个改过橙色的第三方主题（X13 验「颜色跟主题走」） */
body.lb-test-theme-orange{--color-orange:#d35400;--text-warning:#b03a00;}
`;

// 布局子集：每条注明出处版本；只留和滚动容器 / 吸顶 / 尺寸 / 弹层有关的规则，值照原样
const SUBSET_CSS = `
/* 出处：Obsidian 1.14.4 app.css */
*{box-sizing:border-box;}
html,body{margin:0;padding:0;height:100%;width:100%;overscroll-behavior:none;}
body{font-family:var(--font-interface);line-height:var(--line-height-tight);font-size:var(--font-ui-medium);background-color:var(--background-primary);color:var(--text-normal);}
.app-container{display:flex;height:100%;width:100%;flex-direction:column;}
.horizontal-main-container{width:100%;display:flex;overflow:hidden;flex:1 0 0;}
.workspace{display:flex;flex:1 0 0;overflow:hidden;height:100%;}
.workspace-ribbon{width:var(--ribbon-width);flex:0 0 var(--ribbon-width);display:flex;flex-direction:column;overflow:hidden;background-color:var(--ribbon-background);}
.workspace-split{display:flex;background-color:var(--tab-container-background);position:relative;}
.workspace-split.mod-root{background-color:var(--background-primary);}
.workspace-tabs{overflow:hidden;display:flex;flex-direction:column;position:relative;}
.workspace-tabs>*{flex:1 0 0;}
.workspace-tabs .workspace-leaf{height:100%;}
.workspace-tab-header-container{display:flex;background-color:var(--tab-container-background);height:var(--header-height);flex:0 0 auto;}
.workspace-tab-container{display:flex;overflow:hidden;}
.workspace-leaf{display:flex;flex-direction:column;position:relative;contain:strict!important;overflow:hidden;isolation:isolate;}
.workspace-leaf-content{width:100%;height:100%;overflow:hidden;position:relative;display:flex;flex-direction:column;}
.view-header{height:var(--header-height);display:flex;z-index:1;position:relative;}
.view-content{width:100%;height:calc(100% - var(--header-height));}
.workspace-tabs .workspace-leaf .view-content{height:100%;}
.workspace-leaf-content[data-type='markdown'] .view-content{padding:0;overflow:hidden;}
.markdown-reading-view{display:flex;flex-direction:column;}
.markdown-preview-view{font-size:var(--font-preferred-size);font-family:var(--font-text);line-height:var(--line-height-normal);width:100%;height:100%;padding:var(--file-margins);position:relative;overflow-y:auto;overflow-wrap:break-word;color:var(--text-normal);user-select:text;}
.markdown-preview-view.is-readable-line-width .markdown-preview-sizer{max-width:var(--file-line-width);margin-left:auto;margin-right:auto;}
.markdown-source-view.mod-cm6{height:100%;display:flex;flex-direction:column;}
.markdown-source-view.mod-cm6 .cm-editor{flex:1 1;min-height:0;}
.view-content>.markdown-source-view.mod-cm6>.cm-editor>.cm-scroller{padding:var(--file-margins);}
.markdown-source-view.mod-cm6.is-readable-line-width .cm-sizer{max-width:var(--file-line-width);margin-left:auto;margin-right:auto;}
.markdown-source-view.mod-cm6 .cm-sizer{display:flex;flex-direction:column;align-items:stretch;width:100%;min-height:100%;}
.markdown-source-view.mod-cm6 .cm-contentContainer{flex:1 1 auto;display:flex;align-items:stretch;overflow-x:visible;}
.markdown-source-view.mod-cm6 .cm-content{flex-basis:unset!important;width:0;min-height:unset;padding:0;}
.markdown-source-view.mod-cm6 .cm-content>*{margin:0!important;display:block;}
.markdown-source-view.mod-cm6 .cm-content>[contenteditable=false]{contain:paint!important;}
.markdown-source-view.mod-cm6 .cm-embed-block{position:relative;white-space:normal;overflow-wrap:normal;word-break:normal;}
@media (hover: hover){
.markdown-source-view.mod-cm6 .cm-embed-block:not(.cm-table-widget,.cm-lang-base):hover{box-shadow:var(--embed-block-shadow-hover);border-radius:var(--radius-s);overflow:hidden;cursor:text;}
.markdown-source-view.mod-cm6 .cm-embed-block:not(.cm-table-widget,.cm-lang-base):hover .embed-actions{opacity:1;}
}
.markdown-source-view.mod-cm6 .embed-actions{position:absolute;top:var(--size-2-2);inset-inline-end:var(--size-2-2);display:flex;gap:var(--size-2-1);opacity:0;transition:opacity 0.07s ease-out;}
.status-bar{position:var(--status-bar-position);width:auto;bottom:0;inset-inline-end:0;display:flex;gap:8px;padding:4px 8px;font-size:var(--font-ui-smaller);color:var(--text-muted);background-color:var(--status-bar-background);border-top:1px solid var(--divider-color);border-left:1px solid var(--divider-color);border-radius:var(--radius-m) 0 0 0;z-index:var(--layer-notice);}
.notice-container{z-index:var(--layer-notice);position:fixed;top:22px;inset-inline-end:0;padding:10px;overflow:hidden;pointer-events:none;}
.notice{display:flex;flex-direction:column;gap:var(--size-4-2);background-color:var(--notice-background);border-radius:var(--radius-m);color:white;font-size:var(--font-ui-small);padding:10px 14px;margin-bottom:8px;max-width:340px;pointer-events:auto;}
.notice-cta{cursor:pointer;text-decoration:underline;}
.menu{display:flex;flex-direction:column;border:1px solid var(--background-modifier-border-hover);background-color:var(--menu-background);overflow:hidden;padding:0;border-radius:var(--radius-m);box-shadow:0 4px 16px #0003;}
.menu-scroll{padding:var(--size-4-1);}
.menu-item{display:flex;align-items:center;gap:var(--size-4-2);padding:var(--size-4-1) var(--size-4-2);font-size:var(--font-ui-small);border-radius:var(--radius-s);white-space:nowrap;}
.menu-item.is-warning{color:var(--text-error);}.menu-item.is-disabled{opacity:.5;}
.menu-separator{height:1px;margin:4px -4px;background-color:var(--background-modifier-border);}
.modal-container{display:flex;align-items:center;justify-content:center;position:absolute;top:0;bottom:0;inset-inline-start:0;width:100%;z-index:var(--layer-modal);}
.modal-bg{position:absolute;inset:0;background-color:#0006;}
.modal{background-color:var(--modal-background);border-radius:var(--radius-l);border:1px solid var(--background-modifier-border-hover);padding:var(--size-4-4);min-height:100px;width:var(--dialog-width);max-width:var(--dialog-max-width);max-height:85vh;position:relative;display:flex;flex-direction:column;overflow:auto;}
.modal.mod-settings{width:var(--lb-test-settings-width,1100px);max-width:none;height:85vh;padding:0;overflow:hidden;}
.modal.mod-settings .modal-content{margin-top:0;overflow:hidden;display:flex;height:100%;}
.modal.mod-settings .vertical-tab-header{flex:0 0 200px;min-width:200px;max-width:250px;display:flex;flex-direction:column;overflow:hidden;border-inline-end:1px solid var(--divider-color);background:var(--background-secondary);}
.vertical-tab-content-container{position:relative;overflow:hidden;flex-grow:1;}
.vertical-tab-content{overflow-y:auto;height:100%;padding-top:var(--size-4-12);padding-bottom:64px;padding-inline:var(--size-4-8);container-type:inline-size;background-color:var(--background-primary);}
.setting-item{position:relative;display:flex;align-items:center;padding:var(--size-4-4) 0;border-top:1px solid var(--background-modifier-border);}
.setting-item-info{flex:1 1 auto;}
.setting-item-control{flex:1 1 auto;display:flex;align-items:center;justify-content:flex-end;gap:var(--size-4-2);}
.setting-item-description{color:var(--text-muted);font-size:var(--font-ui-smaller);}
.popover.hover-popover{position:absolute;z-index:var(--layer-modal);overflow:hidden;max-width:80vw;width:450px;max-height:400px;border:1px solid var(--background-modifier-border-hover);border-radius:var(--radius-m);background:var(--background-primary);}
.popover.hover-popover>.markdown-embed{max-height:400px;overflow:auto;border:0;padding:0;margin:0;}
.popover.hover-popover .markdown-preview-view{height:auto;}
/* 出处：CodeMirror 6 @codemirror/view baseTheme（Obsidian 1.14.4 内置，运行时注入） */
.cm-editor{position:relative!important;box-sizing:border-box;display:flex!important;flex-direction:column;}
.cm-scroller{display:flex!important;align-items:flex-start!important;font-family:monospace;line-height:1.4;height:100%;overflow-x:auto;position:relative;z-index:0;overflow-anchor:none;}
.cm-content{margin:0;flex-grow:2;flex-shrink:0;display:block;white-space:pre;word-wrap:normal;box-sizing:border-box;min-height:100%;padding:4px 0;outline:none;}
`;

// 外壳自己的（不是 Obsidian 的，只为把宿主撑起来）：根容器占满、左侧栏宽、后台 leaf 藏起来
const SHELL_CSS = `
.workspace-split.mod-root{flex:1 1 0;min-width:0;}
.workspace-split.mod-left-split{flex:0 0 var(--lb-test-left-width,300px);border-inline-end:1px solid var(--divider-color);}
.workspace-split.mod-left-split.is-collapsed{display:none;}
.workspace-tabs.mod-top{flex:1 1 0;min-width:0;}
.workspace-tab-container{flex:1 1 0;min-height:0;}
.workspace-tab-container>.workspace-leaf{flex:1 1 0;}
.workspace-tab-container>.workspace-leaf:not(.mod-active){display:none;}
.markdown-reading-view{width:100%;height:100%;}
`;

// ── 资产 ────────────────────────────────────────────────────────────────────────────────────────────
// 读 link_brain/assets 下的文件；rev 给了（如 '041aca9'）就用 git show 读那一版（只读，不碰工作树）
function readAsset(name, rev = null, dir = 'link_brain/assets') {
  const rel = `${dir}/${name}`;
  if (!rev) return fs.readFileSync(path.join(ROOT, rel), 'utf8');
  return execFileSync('git', ['-C', ROOT, 'show', `${rev}:${rel}`], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, windowsHide: true });
}
const revAvailable = rev => { try { execFileSync('git', ['-C', ROOT, 'cat-file', '-e', `${rev}^{commit}`], { stdio: 'ignore', windowsHide: true }); return true; } catch { return false; } };
// 和 catalog.py / remove.py 拼页面的顺序一致：lb-page-lib + catalog-search + 页面脚本；星标页 = 目录页脚本把两个开关换成 true
function pageAssets(kind, { rev = null } = {}) {
  const lib = readAsset('lb-page-lib.js', rev);
  if (kind === 'annotate') return lib + '\n' + readAsset('annotate-view.js', rev);
  if (kind === 'trash') return lib + '\n' + readAsset('trash-view.js', rev);
  const search = readAsset('catalog-search.js', rev);
  if (kind === 'chat') return lib + '\n' + search + '\n' + readAsset('chat-view.js', rev);
  let code = lib + '\n' + search + '\n' + readAsset('catalog-view.js', rev);
  if (kind === 'starred') code = code.replace('const simplePage = false;', 'const simplePage = true;').replace('const starredPage = false;', 'const starredPage = true;');
  return code;
}

// 合成目录数据（没有真库也能把页面撑高）：n 篇、7 个大类、无封面（.lbc-nocover 占位）
function makeCatalogData({ n = 60, starredEvery = 9, builtAt = '2026-10-08T05:09:12+10:00' } = {}) {
  const cats = ['悉尼', '做饭', 'AI', '学习', '穿搭', '家居', '旅行'];
  const items = Array.from({ length: n }, (_, i) => ({
    id: 'synth-' + String(i).padStart(4, '0'), title: `${cats[i % cats.length]}样例 ${i}`, tags: [], hashtags: [cats[i % cats.length]], cats: [cats[i % cats.length]], topics: [],
    summary: '', search_fields: { body: `第 ${i} 篇的正文，讲${cats[i % cats.length]}。` }, note: `Web/Xiaohongshu/样例${i}.md`, notes_path: `_archive/xiaohongshu/synth-${i}/notes.json`,
    cover: '', attachment: 'none', starred: starredEvery > 0 && i % starredEvery === 0, ts: new Date(Date.UTC(2026, 8, 1) + i * 3600e3).toISOString(), date: '2026-09-01', problems: [],
  }));
  return { built_at: builtAt, pinyin_chars: {}, aliases: [], cats_order: cats, cats: cats.map(name => ({ name, keywords: [name] })), topics: [], state_registry: {}, items };
}

// ── 宿主 DOM ─────────────────────────────────────────────────────────────────────────────────────────
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const DV_CONTAINER = '<div class="block-language-dataviewjs node-insert-event" style="overflow-x: auto;"></div>';   // Dataview 0.5.68 main.js:20535-20537
function leafHtml({ mode, title, body, active = true, extraLeafCls = '', mdCls = '' }) {
  const view = mode === 'live'
    ? `<div class="markdown-source-view cm-s-obsidian mod-cm6 node-insert-event is-readable-line-width is-live-preview is-folding show-properties ${mdCls}">`
      + `<div class="cm-editor"><div class="cm-scroller"><div class="cm-sizer"><div class="inline-title" contenteditable="true">${esc(title)}</div>`
      + `<div class="cm-contentContainer"><div class="cm-content cm-lineWrapping" contenteditable="true" role="textbox">`
      + `<div class="cm-line">---</div><div class="cm-line">lb-page: …</div><div class="cm-line">---</div>`
      + `<div class="cm-preview-code-block cm-embed-block markdown-rendered cm-lang-dataviewjs" contenteditable="false">${body}<div class="embed-actions"><div class="embed-action edit-block-button" aria-label="Edit this block"></div></div></div>`
      + `<div class="cm-line"><br></div></div></div></div></div></div></div>`
    : `<div class="markdown-reading-view" style="width: 100%; height: 100%;"><div class="markdown-preview-view markdown-rendered node-insert-event is-readable-line-width allow-fold-headings show-indentation-guide allow-fold-lists show-properties ${mdCls}">`
      + `<div class="markdown-preview-sizer markdown-preview-section"><div class="markdown-preview-pusher" style="width: 1px; height: 0.1px; margin-bottom: 0px;"></div>`
      + `<div class="mod-header mod-ui"><div class="inline-title">${esc(title)}</div></div>${body}<div class="mod-footer mod-ui"></div></div></div></div>`;
  return `<div class="workspace-leaf${active ? ' mod-active' : ''} ${extraLeafCls}"><div class="workspace-leaf-content" data-type="markdown" data-mode="${mode === 'live' ? 'source' : 'preview'}">`
    + `<div class="view-header"><div class="view-header-title-container"><div class="view-header-title">${esc(title)}</div></div><div class="view-actions"></div></div>`
    + `<div class="view-content">${view}</div></div></div>`;
}
function workspaceHtml({ leaves, ribbon = true, leftSplit = false }) {
  return `<div class="app-container"><div class="horizontal-main-container"><div class="workspace">`
    + (ribbon ? `<div class="workspace-ribbon side-dock-ribbon mod-left"></div>` : '')
    + (leftSplit ? `<div class="workspace-split mod-horizontal mod-sidedock mod-left-split"><div class="workspace-tabs"><div class="workspace-tab-header-container"></div><div class="workspace-tab-container"><div class="workspace-leaf mod-active"><div class="workspace-leaf-content" data-type="file-explorer"><div class="view-content"></div></div></div></div></div></div>` : '')
    + `<div class="workspace-split mod-vertical mod-root"><div class="workspace-tabs mod-top mod-active"><div class="workspace-tab-header-container"><div class="workspace-tab-header is-active"></div></div><div class="workspace-tab-container">${leaves}</div></div></div>`
    + `</div></div></div><div class="status-bar"><div class="status-bar-item">0 个反向链接</div></div>`;
}
// 笔记页正文：mdHtml 是生产 render 出来的「顶栏 callout + .lb-note 块」HTML；annotate:true 时末尾多一段 dataviewjs 容器（批注块）
function noteBody(mdHtml, annotate) {
  return `<div class="el-div">${mdHtml || ''}</div>` + (annotate ? `<div class="el-pre">${DV_CONTAINER}</div>` : '');
}
function hostHtml(host, opts = {}) {
  const title = opts.title || (host === 'note-reading' ? '笔记' : '目录');
  if (host === 'page-reading') return workspaceHtml({ leaves: leafHtml({ mode: 'reading', title, body: `<div class="el-pre">${DV_CONTAINER}</div>` }) });
  if (host === 'page-live') return workspaceHtml({ leaves: leafHtml({ mode: 'live', title, body: DV_CONTAINER }) });
  if (host === 'note-reading') {
    const variant = opts.variant || '';
    const mobile = variant === 'mobile';
    const md = 'link-brain xhs-note';
    let leaves = leafHtml({ mode: 'reading', title, body: noteBody(opts.mdHtml, opts.annotate !== false), mdCls: md, extraLeafCls: variant === 'source-reader' ? 'lb-test-source-reader' : '' });
    if (variant === 'background') leaves += leafHtml({ mode: 'reading', title: title + '（后台）', body: noteBody(opts.mdHtml, false), mdCls: md, active: false });
    let html = workspaceHtml({ leaves, ribbon: !mobile, leftSplit: !mobile && opts.sidebar !== false });
    if (variant === 'popover') html += `<div class="popover hover-popover" style="left:120px;top:160px;"><div class="markdown-embed is-loaded"><div class="markdown-embed-content"><div class="markdown-preview-view markdown-rendered ${md}"><div class="markdown-preview-sizer markdown-preview-section">${noteBody(opts.mdHtml, false)}</div></div></div></div></div>`;
    return html;
  }
  if (host === 'settings-modal') {
    return workspaceHtml({ leaves: leafHtml({ mode: 'reading', title: '笔记', body: '<div class="el-p"><p>（背景）</p></div>' }) })
      + `<div class="modal-container mod-dim"><div class="modal-bg"></div><div class="modal mod-settings mod-sidebar-layout"><div class="modal-close-button"></div>`
      + `<div class="modal-content vertical-tabs-container"><div class="vertical-tab-header"><div class="vertical-tab-nav-item is-active">Link Brain Actions</div></div>`
      + `<div class="vertical-tab-content-container"><div class="vertical-tab-content"></div></div></div></div></div>`;
  }
  throw new Error('未知宿主：' + host);
}
const SELECTORS = {
  'page-reading': { scroller: '.workspace-leaf.mod-active .markdown-preview-view', container: '.workspace-leaf.mod-active .block-language-dataviewjs', section: '.workspace-leaf.mod-active .el-pre' },
  'page-live': { scroller: '.workspace-leaf.mod-active .cm-scroller', container: '.workspace-leaf.mod-active .block-language-dataviewjs', section: '.workspace-leaf.mod-active .cm-embed-block' },
  'note-reading': { scroller: '.workspace-leaf.mod-active .markdown-preview-view', container: '.workspace-leaf.mod-active .block-language-dataviewjs', section: '.workspace-leaf.mod-active .el-pre' },
  'settings-modal': { scroller: '.modal.mod-settings .vertical-tab-content', container: '.modal.mod-settings .vertical-tab-content', section: '.modal.mod-settings .vertical-tab-content' },
};

// ── 页面里的运行时（序列化后注入）：假 app / 假插件 / Dataview 模拟 ─────────────────────────────────────
function shellRuntime(cfg) {
  const W = window, D = document, obs = W.obsidian;
  W.calls = []; W.opened = []; W.reads = {}; W.writes = {}; W.deferred = {}; W.pageErrors = W.pageErrors || [];
  const files = Object.assign({}, cfg.files || {});
  const resources = cfg.resources || {};
  const frontmatter = cfg.frontmatter || {};
  const mtimes = {}; let tick = 1000;
  for (const p of Object.keys(files)) mtimes[p] = ++tick;
  const statOf = p => (p in files ? { mtime: mtimes[p], ctime: mtimes[p], size: String(files[p]).length } : null);
  const fileOf = p => { const i = p.lastIndexOf('/'), name = p.slice(i + 1), dot = name.lastIndexOf('.'); return { path: p, name, basename: dot > 0 ? name.slice(0, dot) : name, extension: dot > 0 ? name.slice(dot + 1) : '', parent: { path: i > 0 ? p.slice(0, i) : '/' }, stat: statOf(p) }; };
  const mkEvents = () => { const h = {}; return {
    on(name, fn) { const ref = { name, fn, e: this }; (h[name] = h[name] || []).push(ref); return ref; },
    offref(ref) { if (ref && h[ref.name]) h[ref.name] = h[ref.name].filter(r => r !== ref); },
    off(name, fn) { h[name] = (h[name] || []).filter(r => r.fn !== fn); },
    trigger(name, ...a) { for (const r of [...(h[name] || [])]) r.fn(...a); },
  }; };
  const vault = Object.assign(mkEvents(), {
    configDir: '.obsidian',
    adapter: {
      async read(p) { W.reads[p] = (W.reads[p] || 0) + 1; if (!(p in files)) throw new Error('ENOENT ' + p); return files[p]; },
      async write(p, s) { W.writes[p] = (W.writes[p] || 0) + 1; files[p] = s; mtimes[p] = ++tick; },
      async append(p, s) { files[p] = (files[p] || '') + s; mtimes[p] = ++tick; },
      async rename(a, b) { files[b] = files[a]; delete files[a]; mtimes[b] = ++tick; },
      async exists(p) { return p in files || Object.keys(files).some(k => k.startsWith(p + '/')); },
      async remove(p) { delete files[p]; },
      async mkdir() {},
      async stat(p) { return statOf(p); },
      getResourcePath: p => resources[p] || resources[p.replace(/^.*?\/(?=_archive\/)/, '')] || '',
      getBasePath: () => '/fake-vault',
    },
    getAbstractFileByPath(p) { if (p === '_archive' || Object.keys(files).some(k => k.startsWith(p + '/'))) return { path: p, children: [] }; return p in files ? fileOf(p) : null; },
    getMarkdownFiles() { return Object.keys(files).filter(k => k.endsWith('.md')).map(fileOf); },
    getFiles() { return Object.keys(files).map(fileOf); },
    async cachedRead(f) { return files[f.path || f]; },
    async read(f) { return files[f.path || f]; },
  });
  // 测试改文件：内容变、mtime 变、发 modify（和 Obsidian 的文件监听一样）
  W.__setFile = (p, s) => { const existed = p in files; files[p] = s; mtimes[p] = ++tick; vault.trigger(existed ? 'modify' : 'create', fileOf(p)); };
  const leafEl = D.querySelector('.workspace-split.mod-root .workspace-leaf.mod-active');
  const leaf = leafEl ? { containerEl: leafEl, view: { containerEl: leafEl.querySelector('.workspace-leaf-content'), file: null, getViewType: () => 'markdown' }, openFile: async f => W.opened.push(['leaf', f.path]), getViewState: () => ({ type: 'markdown', state: {} }), setViewState: async () => {} } : null;
  if (leaf) leaf.view.leaf = leaf;
  const workspace = Object.assign(mkEvents(), {
    activeLeaf: leaf, leaves: leaf ? [leaf] : [],
    async openLinkText(...a) { W.opened.push(a); },
    getLeaf() { return { openFile: async f => W.opened.push(['newleaf', f.path]) }; },
    async revealLeaf(l) { workspace.setActiveLeaf(l); },
    setActiveLeaf(l) { workspace.activeLeaf = l; workspace.trigger('active-leaf-change', l); },
    getLeavesOfType(t) { return workspace.leaves.filter(l => l.view.getViewType() === t); },
    getMostRecentLeaf() { return workspace.activeLeaf; },
    getActiveFile() { return null; },
    getActiveViewOfType() { return workspace.activeLeaf?.view || null; },
    iterateAllLeaves(cb) { workspace.leaves.forEach(cb); },
    onLayoutReady(fn) { fn(); },
  });
  const metadataCache = Object.assign(mkEvents(), {
    getFileCache(f) { const fm = frontmatter[f && f.path || f]; return fm ? { frontmatter: fm } : null; },
    getCache(p) { const fm = frontmatter[p]; return fm ? { frontmatter: fm } : null; },
  });
  const enabled = [];
  const app = W.app = { vault, workspace, metadataCache, isMobile: !!cfg.isMobile, plugins: { plugins: {}, enabledPlugins: new Set(['dataview']), async enablePlugin(id) { enabled.push(id); }, async disablePlugin() {} },
    fileManager: { async processFrontMatter(f, fn) { const fm = frontmatter[f.path] = frontmatter[f.path] || {}; fn(fm); } } };
  W.enabledCalls = enabled;

  // 假插件：每个方法都记进 window.calls；spec.methods[name] = {result} / {fail:'原因'} / {defer:true}（window.deferred[name] 里手动 resolve / reject）/ false（没有这个方法）
  if (cfg.plugin) {
    const spec = cfg.plugin;
    const p = { settings: spec.settings || { hiddenCats: [] }, running: spec.running || null, importing: false, menuOpen: false, catalogCache: null, lbRoot: cfg.folder || '', manifest: { id: 'link-brain-actions', version: 'test' } };
    const rec = (name, args) => W.calls.push([name, ...args]);
    const defaults = {
      starNote: async (id, on) => ({ status: 'ok', starred: !!on }),
      starNotes: async (ids, on) => ({ ok: true, results: ids.map(id => ({ item_id: id, status: 'ok', starred: !!on, error: '' })), done: ids.length, failed: 0, catalog_patched: false }),
      deleteItems: async ids => ({ deleted: ids.length, results: ids.map(id => ({ item_id: id, status: 'ok' })) }),
      attachFile: async () => ({ text: '', warning: null }),
      exportArchiveBundle: async () => ({ path: 'test.zip', notes: 1, images: 0, missing: [] }),
      trashAction: async () => ({ results: [] }),
      openLibraryPage: async () => {}, openArchiveSource: async () => {}, openArchiveMedia: async () => {},
      openAttachments: () => {}, openCategories: () => {}, openPlusMenu: () => {}, openManageMenu: () => {}, openAISettingsMenu: () => {},
      openSyncLog: () => {}, openProblems: () => {}, openSetupPage: () => {}, openPluginSettings: () => {},
      refreshProblemSummary: async () => null, refreshCatalog: async () => ({ code: 0 }), setCatalogPrefs: async () => {}, saveSettings: async () => {},
      answerArchive: async () => ({ status: 'ok', markdown: '回答', sources: [] }), stopArchiveAnswer: () => 0, cancelAnswer: () => true,
      renderMarkdownInto: async (md, el) => { await W.__miniMd.render(md, el); },
      openLightbox: () => null,
    };
    const custom = spec.methods || {};
    for (const name of new Set([...Object.keys(defaults), ...Object.keys(custom)])) {
      const s = custom[name];
      if (s === false) continue;
      const impl = defaults[name] || (() => undefined);
      p[name] = (...args) => {
        rec(name, args);
        if (s && s.defer) return new Promise((resolve, reject) => (W.deferred[name] = W.deferred[name] || []).push({ resolve, reject, args }));
        if (s && s.fail) return Promise.reject(new Error(s.fail));
        if (s && 'result' in s) return Promise.resolve(s.result);
        return impl(...args);
      };
    }
    // 地基接口（照 main.js foundation 段的行为）：notify / confirm / showMenu / busyText
    p.notify = (msg, { kind = 'info', ms, actions = null } = {}) => {
      const list = Array.isArray(actions) ? actions.filter(a => a && a.label) : [];
      const dur = ms ?? (kind === 'error' || kind === 'warn' || list.length ? 8000 : 3000);
      rec('notify', [String(msg), { kind, ms: dur, actions: list.map(a => a.label) }]);
      const n = new obs.Notice(String(msg ?? ''), dur); n.kind = kind;
      for (const a of list) n.addButton(a.label, () => a.run && a.run());
      return n;
    };
    p.confirm = (o = {}) => new Promise(resolve => {
      rec('confirm', [o]);
      if ('confirmAnswer' in spec) { resolve(!!spec.confirmAnswer); return; }
      const m = new obs.Modal(app); let done = false;
      const finish = v => { if (done) return; done = true; resolve(v); m.close(); };
      m.onOpen = () => { m.titleEl.textContent = o.title || '确定吗？'; if (o.body) { const b = D.createElement('p'); b.textContent = o.body; m.contentEl.appendChild(b); }
        const row = D.createElement('div'); row.className = 'modal-button-container'; m.contentEl.appendChild(row);
        const no = D.createElement('button'); no.textContent = o.cancel || '取消'; no.onclick = () => finish(false); row.appendChild(no);
        const yes = D.createElement('button'); yes.textContent = o.ok || '确定'; yes.className = o.danger ? 'mod-destructive mod-cta' : 'mod-cta'; yes.onclick = () => finish(true); row.appendChild(yes);
        setTimeout(() => yes.focus(), 0); };
      m.onClose = () => { if (!done) { done = true; resolve(false); } };
      m.open();
    });
    p.showMenu = (items, evt) => {
      rec('showMenu', [(items || []).map(it => (it && it.separator ? '—' : it && it.title))]);
      const menu = new obs.Menu();
      let count = 0;
      for (const it of items || []) {
        if (!it) continue;
        if (it.separator) { menu.addSeparator(); continue; }
        count++;
        menu.addItem(i => { i.setTitle(it.sub ? it.title + '（' + it.sub + '）' : it.title); if (it.icon) i.setIcon(it.icon); if (it.checked != null) i.setChecked(!!it.checked); if (it.disabled) i.setDisabled(true); if (it.danger) i.setWarning(true); if (it.onClick) i.onClick(e => it.onClick(e)); });
      }
      if (!count) return menu;
      const reset = () => setTimeout(() => { if (p._menu === menu) { p.menuOpen = false; p._menu = null; } }, 0);
      const setHide = menu.onHide.bind(menu);
      setHide(reset);
      menu.onHide = cb => { setHide(() => { reset(); if (typeof cb === 'function') cb(); }); return menu; };
      const anchor = evt && (evt.currentTarget || evt.target) || null;
      const keyboard = !!evt && evt.type !== 'contextmenu' && evt.detail === 0;
      const pointer = !!evt && typeof evt.clientX === 'number' && !keyboard && !(evt.clientX === 0 && evt.clientY === 0);
      try {
        if (pointer) menu.showAtMouseEvent(evt);
        else { const r = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : null; menu.showAtPosition(r ? { x: r.left, y: r.bottom } : { x: 100, y: 100 }); }
      } catch (e) { return menu; }
      p.menuOpen = true; p._menu = menu;
      return menu;
    };
    p.busyText = label => `正在${label || p.running || '处理'}，完成后再点，或在底部状态栏停止`;
    app.plugins.plugins['link-brain-actions'] = p;
    W.plugin = p;
  }
  if (cfg.pluginInit) { try { (new Function('return (' + cfg.pluginInit + ')'))()(W.plugin || null, app, W); } catch (e) { W.pageErrors.push('pluginInit: ' + e.message); } }

  // Dataview：DataviewJSRenderer 的样子——容器创建时写行内 overflow-x:auto；render() = innerHTML='' 再跑脚本
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const sel = cfg.selectors;
  const makeComponent = () => { const c = { _cbs: [], loaded: true,
    register(fn) { c._cbs.push(fn); }, registerEvent(ref) { c.register(() => ref && ref.e && ref.e.offref && ref.e.offref(ref)); },
    registerDomEvent(t, type, fn, o) { t.addEventListener(type, fn, o); c.register(() => t.removeEventListener(type, fn, o)); },
    registerInterval(id) { c.register(() => clearInterval(id)); return id; },
    addChild(x) { try { x && x.load && x.load(); } catch (e) {} c.register(() => x && x.unload && x.unload()); return x; },
    unload() { if (!c.loaded) return; c.loaded = false; while (c._cbs.length) { try { c._cbs.pop()(); } catch (e) {} } },
    render() { return shell.rerun(); } }; return c; };
  const shell = W.__shell = { container: D.querySelector(sel.container), component: makeComponent(), runs: 0, errors: [], params: cfg.params || {} };
  shell.section = shell.container && shell.container.parentElement;
  shell.dv = () => ({ container: shell.container, component: shell.component, current: () => ({ file: { folder: cfg.folder || '', path: cfg.pagePath || ((cfg.folder ? cfg.folder + '/' : '') + 'page.md') } }), page: () => null,
    // 和 Dataview 一样：字符串按行内 markdown 渲染（**粗体** / `代码` / ![[图]]）
    paragraph: t => shell.dv().el('p', t),
    el: (tag, text) => { const e = D.createElement(tag); W.__miniMd.renderInline(text, e); shell.container.appendChild(e); return e; },
    header: (lv, text) => shell.dv().el('h' + lv, text), span: text => shell.dv().el('span', text) });
  shell.run = async () => {
    if (!cfg.code) return;
    shell.runs++;
    const keys = Object.keys(shell.params);
    try { await new AsyncFunction('dv', 'input', ...keys, cfg.code)(shell.dv(), undefined, ...keys.map(k => shell.params[k])); }
    catch (e) { shell.errors.push(String(e && e.stack || e)); throw e; }
  };
  shell.rerun = async () => { shell.container.innerHTML = ''; await shell.run(); };
  shell.recreate = async () => {
    shell.component.unload();
    const fresh = D.createElement('div'); fresh.className = 'block-language-dataviewjs node-insert-event'; fresh.style.overflowX = 'auto';
    shell.container.replaceWith(fresh); shell.container = fresh; shell.component = makeComponent();
    await shell.run();
  };
  shell.detach = () => { shell.component.unload(); shell.section && shell.section.remove(); };
}

// ── node 侧 API ──────────────────────────────────────────────────────────────────────────────────────
function loadPlaywright() { try { return require('playwright'); } catch { return null; } }
function requirePlaywright() {
  const pw = loadPlaywright();
  if (!pw) { console.log('SKIP 没装 playwright：UI 层没跑（照 docs/CONVENTIONS.md §7.7 接上共享 node_modules 后再跑 npm run test:ui）'); process.exit(SKIP); }
  return pw;
}
// 默认 msedge（本机标准路径有）；LWA_PW_CHANNEL='' 用 playwright 自带的 chromium；起不来就退回自带的
async function launch({ headless = true } = {}) {
  const pw = requirePlaywright();
  const channel = process.env.LWA_PW_CHANNEL ?? 'msedge';
  if (channel) { try { return await pw.chromium.launch({ headless, channel }); } catch (e) { /* 退回自带 chromium */ } }
  return pw.chromium.launch({ headless });
}

function cssFiles(host, { plugin = true } = {}) {
  const out = [];
  const add = (p, id) => { const f = path.join(ROOT, p); if (fs.existsSync(f)) out.push({ id, css: fs.readFileSync(f, 'utf8') }); };
  if (host === 'note-reading') add('link_brain/assets/link-brain.css', 'lb-test-link-brain-css');   // CSS 片段（插件把同一份 note.css 注入 head）
  if (plugin) add('obsidian-plugins/link-brain-actions/styles.css', 'lb-test-plugin-styles');     // 插件启用时 Obsidian 全局加载
  return out;
}

async function setup(page, opts = {}) {
  const host = opts.host || 'page-reading';
  const theme = opts.theme || 'light';
  const variant = opts.variant || '';
  const mobile = !!opts.mobile || variant === 'mobile';
  const bodyCls = [theme === 'dark' ? 'theme-dark' : 'theme-light', theme === 'orange' ? 'lb-test-theme-orange' : '', 'mod-windows', 'is-focused',
    mobile ? 'is-mobile is-phone' : '', opts.bodyClass || ''].filter(Boolean).join(' ');
  const appCssPath = opts.appCss ?? process.env.LWA_OBSIDIAN_APP_CSS;
  const appCss = appCssPath && fs.existsSync(appCssPath) ? fs.readFileSync(appCssPath, 'utf8') : '';
  const styles = [
    appCss ? `<style id="obsidian-app-css">${appCss}</style>` : '',
    `<style id="lb-test-theme">${THEME_CSS}</style>`, `<style id="lb-test-obsidian-subset">${SUBSET_CSS}</style>`, `<style id="lb-test-shell">${SHELL_CSS}</style>`,
    ...cssFiles(host, { plugin: opts.plugin !== null && !mobile }).map(f => `<style id="${f.id}">${f.css}</style>`),
    host === 'settings-modal' ? `<style>body{--lb-test-settings-width:${200 + (opts.contentWidth || 800) + 64}px;}</style>` : '',
    host === 'note-reading' && opts.sidebarWidth ? `<style>body{--lb-test-left-width:${opts.sidebarWidth}px;}</style>` : '',
  ].join('');
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8">${styles}</head><body class="${bodyCls}">${hostHtml(host, { ...opts, variant: mobile ? 'mobile' : variant })}</body></html>`);
  // source-reader 变体：插件给右侧来源窗格的 leaf-content 加 .lb-source-reader（main.js openArchiveSource）
  if (variant === 'source-reader') await page.evaluate(() => document.querySelector('.workspace-leaf.mod-active .workspace-leaf-content').classList.add('lb-source-reader'));
  await page.addScriptTag({ content: `(${installObsidianDom.toString()})(window);` });
  await page.addScriptTag({ content: miniMdSource('__miniMd') });
  await page.addScriptTag({ content: 'window.__lbRenderMarkdown=(md,el)=>window.__miniMd.render(md,el);' + browserSource('obsidian') + 'window.Notice=window.obsidian.Notice;' });
}

// 开一页：宿主 + 假 app / 插件 + Dataview 跑页面脚本。返回 S（见下）
async function openPage(page, opts = {}) {
  const host = opts.host || 'page-reading';
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await setup(page, opts);
  const kind = opts.kind || null;
  const code = opts.code ?? (kind ? pageAssets(kind, { rev: opts.rev || null }) : '');
  const folder = opts.folder || '';
  const files = { ...(opts.files || {}) };
  const pre = folder ? folder + '/' : '';
  if (opts.data && !files[pre + '_archive/catalog-data.json']) files[pre + '_archive/catalog-data.json'] = JSON.stringify(opts.data);
  if (!Object.keys(files).some(k => k.startsWith(pre + '_archive/'))) files[pre + '_archive/.keep'] = '';
  const frontmatter = { ...(opts.frontmatter || {}) };
  if (!opts.frontmatter) for (const [role, name] of [['catalog', '目录'], ['chat', '问收藏'], ['starred', '星标收藏'], ['trash', '回收站']]) { files[pre + name + '.md'] = files[pre + name + '.md'] || `---\nlb-page: ${role}\n---\n`; frontmatter[pre + name + '.md'] = { 'lb-page': role }; }
  const cfg = { code, folder, files, frontmatter, resources: opts.resources || {}, isMobile: !!opts.mobile || opts.variant === 'mobile', params: opts.params || {}, pagePath: opts.pagePath,
    plugin: opts.plugin === null || opts.mobile || opts.variant === 'mobile' ? null : (opts.plugin || {}), pluginInit: opts.pluginInit ? String(opts.pluginInit) : null, selectors: SELECTORS[host] };
  await page.evaluate(`(${shellRuntime.toString()})(${JSON.stringify(cfg)})`);
  const S = makeHandle(page, host, errors);
  if (code && opts.run !== false) { await S.run(); await S.settle(); }
  return S;
}

function makeHandle(page, host, errors) {
  const sel = SELECTORS[host];
  const frames = (n = 2) => page.evaluate(n => new Promise(r => { const step = k => (k ? requestAnimationFrame(() => step(k - 1)) : r()); step(n); }), n);
  const S = {
    page, host, selectors: sel, errors,
    async run() { await page.evaluate(() => window.__shell.run()); },
    async settle(ms = 30) { await frames(2); if (ms) await page.waitForTimeout(ms); },
    async rerun() { await page.evaluate(() => window.__shell.rerun()); await S.settle(); },
    async recreate() { await page.evaluate(() => window.__shell.recreate()); await S.settle(); },
    async detach() { await page.evaluate(() => window.__shell.detach()); await S.settle(); },
    async setFile(p, s) { await page.evaluate(([p, s]) => window.__setFile(p, s), [p, s]); },
    async scrollBy(dy) { await page.evaluate(([s, dy]) => { const el = document.querySelector(s); el.scrollTop += dy; el.dispatchEvent(new Event('scroll')); }, [sel.scroller, dy]); await S.settle(); },
    async scrollTo(top) { await page.evaluate(([s, top]) => { const el = document.querySelector(s); el.scrollTop = top; el.dispatchEvent(new Event('scroll')); }, [sel.scroller, top]); await S.settle(); },
    scrollTop: () => page.evaluate(s => document.querySelector(s).scrollTop, sel.scroller),
    rect: s => page.evaluate(s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height }; }, s),
    notices: () => page.evaluate(() => (window.notices || []).map(n => ({ message: n.message, timeout: n.timeout, hidden: n.hidden, kind: n.kind || null, buttons: (n.buttons || []).map(b => b.label) }))),
    calls: () => page.evaluate(() => window.calls),
    pageErrors: () => page.evaluate(() => [...(window.pageErrors || []), ...((window.__shell && window.__shell.errors) || [])]).then(x => [...errors, ...x]),
    async screenshot(name, opts = {}) { fs.mkdirSync(QA_DIR, { recursive: true }); const file = path.join(QA_DIR, name.endsWith('.png') ? name : name + '.png'); await page.screenshot({ path: file, ...opts }); return file; },
    // 守卫读数：宿主是否还像真宿主（容器行内 overflow-x、实时预览 :hover / contain:paint 规则、祖先链）
    guards: () => page.evaluate(([cs]) => {
      const c = document.querySelector(cs);
      const sheet = [...document.styleSheets].map(s => { try { return [...s.cssRules].map(r => r.cssText).join('\n'); } catch { return ''; } }).join('\n');
      // 1.14.4 的 :hover{overflow:hidden} 在 @media (hover: hover) 里：规则在 media 块里，且这台「电脑」匹配 hover:hover（有鼠标）
      const inHoverMedia = [...document.styleSheets].some(s => { try { return [...s.cssRules].some(r => r.media && /hover:\s*hover/.test(r.media.mediaText) && /\.cm-embed-block:not\([^)]*\):hover\s*\{[^}]*overflow:\s*hidden/.test(r.cssText)); } catch { return false; } });
      return { containerInlineOverflowX: c ? c.style.overflowX : null, containerComputedOverflowY: c ? getComputedStyle(c).overflowY : null,
        hoverOverflowHidden: /\.cm-embed-block:not\([^)]*\):hover\s*\{[^}]*overflow:\s*hidden/.test(sheet),
        hoverInMedia: inHoverMedia, hoverMediaMatches: matchMedia('(hover: hover)').matches,
        embedActions: !!(c && c.parentElement && c.parentElement.querySelector(':scope > .embed-actions > .edit-block-button')),
        containPaint: /\.cm-content\s*>\s*\[contenteditable="?false"?\]\s*\{[^}]*contain:\s*paint/.test(sheet),
        inEmbedBlock: !!(c && c.closest('.cm-embed-block.cm-lang-dataviewjs')), inPreviewView: !!(c && c.closest('.markdown-preview-view')) };
    }, [sel.container]),
    // 鼠标移到滚动容器可见区域的中间（不用 page.hover：它会先把元素滚进视野，改掉 scrollTop）
    async hoverScroller() {
      const r = await S.rect(sel.scroller); if (!r) return;
      await page.mouse.move(Math.round(r.left + r.width / 2), Math.round(r.top + Math.min(r.height / 2, 400)));
      await S.settle(0);
    },
    // C1 探针：鼠标停在页面上（实时预览的 .cm-embed-block:hover{overflow:hidden} 要靠它触发），滚动容器往下滚 by 像素，
    // 量 target 顶边和滚动容器顶边的差 delta。口径照 L1：吸顶正常 = |delta| ≤ 1（贴住滚动容器顶）。
    // 滚动容器有上内边距（Obsidian 的 --file-margins，阅读视图 / 实时预览都是 32px）：Chromium 的 sticky top:0 停在内边距下沿，delta = padTop，
    // 这时顶栏上方那条缝里看得见滚上去的卡片——探针判红（gap 里报出缝里是什么）。要不要接受这条缝是界面口味，归主审裁决，测试架不替她默认。
    // 例外：缝里取点（左 / 中 / 右三处）只碰到滚动容器本身或目标自己（页面把缝盖住了）也算正常。吸顶失效 → delta ≈ 原位置 − by（一大段负数）。
    async probeSticky({ target = '.lbc-top', hover = true, by = 1500 } = {}) {
      if (hover) await S.hoverScroller();
      await S.scrollBy(by);
      if (hover) await S.hoverScroller();
      await S.settle();
      return page.evaluate(([ss, ts]) => {
        const s = document.querySelector(ss), t = document.querySelector(ts);
        if (!s || !t) return { ok: false, reason: (s ? '' : '没有滚动容器 ') + (t ? '' : '没有 ' + ts) };
        const sr = s.getBoundingClientRect(), tr = t.getBoundingClientRect(), padTop = Math.round(parseFloat(getComputedStyle(s).paddingTop) || 0);
        const delta = Math.round(tr.top - sr.top);
        const hovered = [...document.querySelectorAll(':hover')].map(e => e.className && String(e.className).split(' ')[0]).filter(Boolean);
        const desc = e => (e ? e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '') : null);
        // 缝（滚动容器顶 → 目标顶）里露出来的是什么：只有 delta > 1 时才有缝
        let gap = null, gapClean = false;
        if (delta > 1) {
          const y = sr.top + Math.max(1, Math.floor(delta / 2));
          const xs = [tr.left + 8, (tr.left + tr.right) / 2, tr.right - 8];
          const hits = xs.map(x => document.elementFromPoint(x, y));
          gapClean = hits.every(h => h && (h === s || t.contains(h)));
          gap = hits.map(desc);
        }
        return { ok: Math.abs(delta) <= 1 || gapClean, delta, padTop, gap, targetTop: Math.round(tr.top), scrollerTop: Math.round(sr.top), scrollTop: Math.round(s.scrollTop), embedHovered: hovered.includes('cm-preview-code-block') };
      }, [sel.scroller, target]);
    },
    // C4 探针：点进输入框、打几个字，中间穿插 reruns 次 Dataview 重跑，最后看值和焦点。正常 → value===text 且焦点还在
    async probeFocusAfterRerun({ input = '.lbc-search', text = 'kafei', reruns = 3 } = {}) {
      await page.click(input);
      const chunks = [text.slice(0, 2), ...text.slice(2).split('')];
      await page.keyboard.type(chunks[0]);
      for (let i = 0; i < reruns; i++) { await S.rerun(); if (chunks[i + 1]) await page.keyboard.type(chunks[i + 1]); }
      for (const rest of chunks.slice(reruns + 1)) await page.keyboard.type(rest);
      return page.evaluate(([s, text]) => {
        const el = document.querySelector(s), a = document.activeElement;
        const desc = a ? (a.tagName.toLowerCase() + (a.className ? '.' + String(a.className).split(' ').join('.') : '')) : null;
        return { ok: !!el && el.value === text && a === el, value: el ? el.value : null, focused: a === el, activeElement: desc };
      }, [input, text]);
    },
  };
  return S;
}

// 笔记页：mdHtml = 生产 render 出来的笔记 HTML（顶栏 callout + .lb-note 块）；annotate:true（默认）末尾带批注块容器；
// kind:'annotate'（要带 params:{itemId, notePath} 和 files 里的 notes.json）或 code 给了就在批注块里跑
async function openNote(page, opts = {}) {
  return openPage(page, { ...opts, host: 'note-reading', kind: opts.kind || null, run: !!(opts.code || opts.kind) });
}
// L5 草案里的名字：notePage(page, {mdHtml, css, theme, width})
async function notePage(page, { mdHtml = '', css = [], theme = 'light', width = null, ...rest } = {}) {
  if (width) await page.setViewportSize({ width, height: (page.viewportSize() || {}).height || 900 });
  const S = await openNote(page, { mdHtml, theme, ...rest });
  for (const c of css) await page.addStyleTag({ content: c });
  return S;
}
async function openSettings(page, opts = {}) { return openPage(page, { ...opts, host: 'settings-modal', run: false }); }

module.exports = {
  ROOT, SKIP, QA_DIR, THEME_CSS, SUBSET_CSS, SHELL_CSS, SELECTORS, DV_CONTAINER,
  requirePlaywright, loadPlaywright, launch, setup, hostHtml, pageAssets, readAsset, revAvailable, makeCatalogData,
  page: openPage, note: openNote, notePage, settings: openSettings,
};

// wiki-view.js — 个人 Wiki 页（10-29）。长相照 design-1028-wiki/prototype.design.html（design.md），结构 / 交互照 prototype.html。
// 前面已内联 lb-page-lib.js 和 catalog-search.js（catalog.py 拼成 _archive/wiki-page.js，Wiki.md 只放引导）。
// 数据：
//   - 读：直接读 PersonalWiki/*.md（顶层，.history / .trash 不算），文件头解析和 personal_wiki.parse_page 同一套（含 Obsidian 块状列表）；
//     hash = 全文（CRLF→LF）SHA-1 前 16 位，和 personal_wiki.content_hash 对得上——保存时当 base_hash 交回去。
//     目录 / 文件夹 / 标签 / 引用 / 小标题 / 待办都在这里现算（同原型的 reindex；文件夹 = role: topic 的页 + 它的 index_tag，顺序看文件夹页的 order）。
//   - 写：一律 provider().wikiCall(op, {args, input}) → `pwiki` 命令（单 writer），页面从不 adapter.write 进 PersonalWiki。
//     改动先显示在界面上（乐观），写盘成功后用返回的 hash 接着存；失败按 §1.5 回滚 + 把用户的改动留成「没保存上的改动」（页顶可一键再存 / 覆盖），
//     提示固定句式「没保存上，内容还在，可重试：<原因>」。CONFLICT（别处改过）= 换成磁盘上的版本，用户的那份留在页顶。
//   - 收藏：LB.data.load() 的 items；正文引用 [标题](lwa:<id>) 点了照问收藏的做法开到右栏（provider().openArchiveSource）。
// 渲染：沿用原型自己的块解析 + 行内渲染（它记着「块 ↔ 源码行」，点一段改一段靠它），不走 Obsidian 的 MarkdownRenderer——
//   简单、稳、单测里可跑；代价是只认原型那几种写法（标题 / 列表 / 待办 / 引用 / 代码 / ```pages / 分隔线 / 图片 / 链接）。
// 和设计稿的出入（见 docs/WIKI-UNIFY-LATER.md）：页头三页切换沿用现有 .lb-page-nav 胶囊；历史放在本页右侧的侧栏里（不占 Obsidian 右栏）；
//   宽度三档用 ResizeObserver 给根加 is-mid / is-narrow（不用容器查询：容器查询会让里面的 position:fixed 弹层 / 抽屉相对 host 定位）。
// 手机 / 插件没启用：只读（能看、能跳、能开原文，不出编辑框和写盘按钮）。
const LB = lbPageLib(dv, app, 'wiki');
if (await LB.reuseDom()) return;
const D = (dv.container && dv.container.ownerDocument) || document;
const WIN = D.defaultView || (typeof window !== 'undefined' ? window : null);
const G = typeof globalThis !== 'undefined' ? globalThis : {};
{ const pane = dv.container.closest && dv.container.closest('.markdown-preview-view, .markdown-source-view'); if (pane) pane.classList.add('lb-wikipage'); }
const provider = LB.provider;
const readOnly = !!LB.mobile || typeof provider()?.wikiCall !== 'function';
const WDIR = 'PersonalWiki';
const SVGNS = 'http://www.w3.org/2000/svg';
const INDEX_DELAY_MS = 3000;   // 存完几秒后重建 _archive/wiki-index.json（给问收藏 / MCP 用），连着存只建一次
const FONT_FILE = '_archive/fonts/CormorantGaramond-Italic-latin-variable.woff2';

// ═════════════ 样式（挂 head；颜色只用 --lb-* / Obsidian 变量，字体只用 --lb-font-*；数字斜体只在 .lbw 里） ═════════════
const fontFace = (family, rel, range, extra = '') => {
  let u = '';
  try { u = String(app.vault.adapter.getResourcePath?.(LB.path(rel)) || ''); } catch (e) { u = ''; }
  return u ? `@font-face{font-family:"${family}";src:url("${u.replace(/"/g, '%22')}") format("woff2");font-weight:300 700;font-style:italic;font-display:swap;unicode-range:${range};${extra}}\n` : '';
};
LB.style('lb-wiki-style', LB.brandFontCss() + fontFace('LB Digits Inline', FONT_FILE, 'U+0030-0039', 'size-adjust:114%;') + `
.markdown-preview-view.lb-wikipage,.markdown-source-view.lb-wikipage{--file-line-width:100%;}
.lb-wikipage .markdown-preview-sizer,.lb-wikipage .markdown-preview-section,.lb-wikipage .cm-sizer,.lb-wikipage .cm-contentContainer,.lb-wikipage .cm-content,.lb-wikipage .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-wikipage .inline-title,.lb-wikipage .metadata-container{display:none!important;}
.lb-wikipage .block-language-dataviewjs{overflow:visible!important;}
.markdown-source-view.lb-wikipage .cm-embed-block.cm-lang-dataviewjs,.markdown-source-view.lb-wikipage .cm-embed-block.cm-lang-dataviewjs:hover{overflow:visible!important;}
.lb-wikipage :is(.el-pre:has(.block-language-dataviewjs),pre:has(.block-language-dataviewjs),.block-language-dataviewjs,.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs),.lb-wikipage :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs):hover{border:0!important;background:transparent!important;box-shadow:none!important;outline:0!important;border-radius:0!important;}
.lb-wikipage :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-lang-dataviewjs) .edit-block-button{display:none!important;}
/* 根：纸和墨；「LB Digits Inline」只挂在这里的宋体 / 黑体栈最前（正文里随手写的数字也斜，别的页不受影响） */
.lbw{--lbw-serif:"LB Digits Inline",var(--lb-font-serif);--lbw-sans:"LB Digits Inline",var(--lb-font-body);--lbw-mono:var(--font-monospace);--lbw-print:5px 5px 0 var(--lb-ink);
  position:relative;box-sizing:border-box;padding:30px 56px 0;color:var(--lb-ink);background:var(--lb-surface);font:400 15px/1.7 var(--lbw-serif);font-variant-numeric:lining-nums;-webkit-font-smoothing:antialiased;}
.lbw *,.lbw *::before,.lbw *::after{box-sizing:border-box;}
.lbw [hidden]{display:none!important;}
.lbw button{font:inherit;color:inherit;background:none;border:0;box-shadow:none;height:auto;margin:0;padding:0;border-radius:0;cursor:pointer;text-align:inherit;}
.lbw button:hover{background:none;box-shadow:none;}
.lbw button:focus-visible,.lbw a:focus-visible,.lbw input:focus-visible,.lbw textarea:focus-visible{outline:2px solid var(--lb-ink);outline-offset:2px;box-shadow:none;}
.lbw a{color:inherit;}
.lbw ::selection{background:var(--lb-ink);color:var(--lb-surface);}
.lbw-ico{display:block;flex:none;width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;}
.lbw-kick{font:700 10.5px/1.3 var(--lb-font-title);letter-spacing:.26em;text-transform:uppercase;color:var(--lb-ink);}
.lbw-zh{font:400 13px/1.3 var(--lbw-serif);letter-spacing:.14em;color:var(--lb-muted);}
.lbw-cap{font:400 12.5px/1.6 var(--lbw-sans);color:var(--lb-muted);}
.lbw-num{font-family:var(--lb-font-num);font-style:italic;font-weight:500;font-variant-numeric:lining-nums tabular-nums;font-size:1.16em;letter-spacing:.01em;}
.lbw-code{font:.84em/1 var(--lbw-mono);color:var(--lb-muted);}
.lbw-kbd{display:inline-block;font:500 11px/1 var(--lbw-sans);padding:3px 6px;border:1px solid var(--lb-line);border-radius:4px;color:var(--lb-muted);white-space:nowrap;}
.lbw .lbw-pill{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 16px;border:1px solid var(--lb-ink);border-radius:999px;background:transparent;color:var(--lb-ink);font:500 13px/1 var(--lbw-sans);white-space:nowrap;}
.lbw .lbw-pill:hover,.lbw .lbw-pill.is-solid{background:var(--lb-ink);color:var(--lb-surface);}
.lbw .lbw-pill:disabled{opacity:.45;cursor:default;}
.lbw .lbw-qbtn{height:32px;padding:0 12px;border-radius:999px;color:var(--lb-muted);font:400 13px var(--lbw-sans);}
.lbw .lbw-qbtn:hover{background:var(--lb-soft);color:var(--lb-ink);}
.lbw-sech{display:flex;align-items:center;gap:14px;margin:0 0 26px;}
.lbw-sech .lbw-kick{font-size:12px;letter-spacing:.32em;}
.lbw-sech .lbw-rule{flex:1;height:1px;background:var(--lb-ink);}
.lbw-sech .lbw-cap{font-size:12px;white-space:nowrap;}
.lbw .lbw-chev{width:28px;height:28px;display:grid;place-items:center;border-radius:999px;color:var(--lb-ink);transition:transform .15s;}
.lbw .lbw-chev.is-shut{transform:rotate(-90deg);}
.lbw-legend{display:flex;align-items:center;gap:14px;font:400 12px/1 var(--lbw-sans);color:var(--lb-muted);white-space:nowrap;}
.lbw-legend i{display:inline-block;width:22px;height:0;border-top:1px solid var(--lb-muted);vertical-align:middle;margin-right:6px;}
.lbw-legend i.is-x{border-top-style:dashed;}
/* 页头（10-31 晚和问收藏对齐）：一行——小号刻线标题 + 三页切换（透明底，当前那页白底小卡）；右边「AI · 历史 · …」方形带框按钮；下面篇数行压一条墨线 */
/* 1101 设计交接包 §1「页头」：三页同一个——字标 + ＋ ｜ 空间切换胶囊 ｜ 右边 meta · 历史 · ···；下面一道 1px 墨线 */
${LB.siteHeaderCss()}
.lbw-hrow{display:flex;align-items:center;flex-wrap:wrap;gap:16px 40px;padding:28px 0 22px;border-bottom:1px solid var(--lb-line);}
.lbw-brandbox{display:flex;align-items:center;gap:2px;}
.lbw .lbw-brand{font-size:44px;line-height:1.02;transform-origin:left center;padding-left:.04em;}
.lbw .lbw-plus{width:40px;height:44px;display:grid;place-items:center;font:500 30px/1 var(--lb-font-title);color:var(--lb-ink);transition:transform .2s;}
.lbw .lbw-plus:hover{transform:rotate(90deg);}
.lbw-acts{display:flex;align-items:center;gap:2px;margin-left:auto;}
.lbw .lbw-hbtn{width:44px;height:44px;display:grid;place-items:center;border:0;border-radius:999px;background:transparent;box-shadow:none;color:var(--lb-ink);}
.lbw .lbw-hbtn .lbw-ico{width:20px;height:20px;}
.lbw .lbw-hbtn:hover,.lbw .lbw-hbtn.is-on{background:var(--lb-soft);color:var(--lb-ink);}
/* 「AI 整理本页」：面包屑那一行右边，不要框（1101 作者），悬停才有浅底 */
.lbw .lbw-hbtn.is-ai{width:auto;height:34px;display:inline-flex;align-items:center;gap:6px;padding:0 12px;margin-left:auto;font:400 13px/1 var(--lbw-sans);}
.lbw .lbw-hbtn.is-ai .lbw-ico{width:15px;height:15px;}
.lbw-crumbrow{display:flex;align-items:center;gap:12px;min-height:34px;}
.lbw-sub{color:var(--lb-muted);}
.lbw-ro{margin:14px 0 0;font:400 12.5px/1.6 var(--lbw-sans);color:var(--lb-muted);}
/* 主体：左浮动目录 + 正文（+ 右侧历史栏） */
.lbw-body{display:grid;grid-template-columns:minmax(0,1fr);column-gap:40px;}
.lbw.has-side .lbw-body{grid-template-columns:minmax(0,1fr) minmax(300px,380px);}
.lbw-main{display:grid;grid-template-columns:248px minmax(0,680px);column-gap:64px;padding:44px 0 120px;}
.lbw.is-home .lbw-main{grid-template-columns:248px minmax(0,1fr);}
/* 10-31 目录整栏收起：正文居中加宽，左下角留「目录」钮 */
.lbw.is-tocoff .lbw-main,.lbw.is-tocoff.is-home .lbw-main{grid-template-columns:minmax(0,760px);justify-content:center;}
.lbw.is-tocoff.is-home .lbw-main{grid-template-columns:minmax(0,1fr);}
.lbw.is-tocoff:not(.is-narrow) .lbw-toc{display:none;}
.lbw.is-tocoff:not(.is-narrow) .lbw-fab{display:inline-flex;align-items:center;gap:8px;position:fixed;left:auto;bottom:22px;z-index:13;height:36px;margin-left:-8px;padding:0 14px 0 12px;border:1px solid var(--lb-line);border-radius:999px;background:var(--lb-surface);font:500 13px/1 var(--lbw-sans);color:var(--lb-ink);}
.lbw-toc{position:sticky;top:20px;align-self:start;max-height:calc(100vh - 40px);overflow:auto;padding:0 4px 0 12px;margin-left:-12px;scrollbar-width:thin;}
.lbw-tools{display:flex;align-items:center;height:32px;margin:0 0 12px -9px;}
.lbw .lbw-tools button{flex:none;width:32px;height:32px;display:grid;place-items:center;border-radius:999px;color:var(--lb-muted);}
.lbw .lbw-tools button:hover,.lbw .lbw-tools button.is-on{background:var(--lb-soft);color:var(--lb-ink);}
.lbw-say{flex:1;min-width:0;text-align:right;padding-left:6px;font:400 11.5px/1 var(--lbw-sans);color:var(--lb-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbw-findw{display:flex;align-items:center;gap:8px;height:38px;margin:0 0 14px;border-bottom:1px solid var(--lb-ink);}
.lbw .lbw-find{flex:1;min-width:0;height:36px;border:0;border-radius:0;padding:0;background:none;box-shadow:none;color:var(--lb-ink);font:400 15px/1 var(--lbw-serif);}
.lbw .lbw-find:focus,.lbw .lbw-find:focus-visible{outline:none;box-shadow:none;}
.lbw-toc mark{background:none;color:var(--lb-ink);font-weight:700;text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:3px;}
.lbw-tmap{margin:0 0 12px;padding:0 0 12px;border-bottom:1px solid var(--lb-line);}
.lbw-tmap-row{display:flex;align-items:center;gap:6px;height:30px;}
.lbw .lbw-tmap-h{display:flex;align-items:center;gap:8px;flex:1;min-width:0;height:30px;color:var(--lb-ink);}
.lbw-tmap-h .lbw-kick{font-size:10px;}
.lbw-tmap-h .lbw-zh{font-size:12px;letter-spacing:.12em;}
.lbw-tmap-h .lbw-rule{flex:1;height:1px;background:var(--lb-line);}
.lbw-tmap-h .lbw-tw{color:var(--lb-muted);transition:transform .15s;}
.lbw-tmap-h .lbw-tw.is-shut{transform:rotate(-90deg);}
.lbw .lbw-mpin{width:28px;height:28px;display:grid;place-items:center;border-radius:999px;color:var(--lb-muted);}
.lbw .lbw-mpin:hover{background:var(--lb-soft);color:var(--lb-ink);}
.lbw .lbw-mpin.is-on{color:var(--lb-ink);}
.lbw-mpin.is-on .lbw-ico{fill:currentColor;}
.lbw-tmap .lbw-graph{margin-top:6px;}
.lbw .lbw-trow{position:relative;display:flex;align-items:baseline;gap:8px;width:100%;padding:4px;text-align:left;color:var(--lb-ink);font:400 14px/1.5 var(--lbw-serif);}
.lbw-tgroup + .lbw-tgroup{margin-top:8px;}
.lbw .lbw-tfold{padding:7px 2px 7px 0;font:600 14.5px/1.35 var(--lbw-serif);}
.lbw-tfold .lbw-tw{flex:none;width:12px;align-self:center;color:var(--lb-muted);transition:transform .15s;transform:rotate(-90deg);}
.lbw-tfold .lbw-tw .lbw-ico{width:12px;height:12px;stroke-width:2;}
.lbw-tfold.is-open .lbw-tw{transform:none;}
.lbw-tfold > .lbw-num{flex:none;min-width:14px;font-size:17px;color:var(--lb-muted);}
.lbw-tfold .lbw-nm{min-width:0;}
.lbw-tfold .lbw-c{margin-left:auto;font-size:16px;color:var(--lb-muted);}
.lbw-tfold:hover .lbw-nm{text-decoration:underline;text-underline-offset:4px;}
.lbw-tfold.is-current::before{content:"";position:absolute;left:-12px;top:9px;bottom:9px;width:2px;background:var(--lb-ink);}
.lbw .lbw-tpage{display:block;padding:4px 4px 4px 34px;}
.lbw .lbw-tpage:hover{background:var(--lb-soft);border-radius:2px;}
.lbw-tpage.is-current{font-weight:700;}
.lbw-tpage.is-current::before{content:"";position:absolute;left:20px;top:7px;bottom:7px;width:2px;background:var(--lb-ink);}
.lbw-trow[draggable=true]{cursor:grab;}
.lbw-tpage[draggable=true]:hover::after{content:"\\2807";position:absolute;left:5px;top:4px;font:400 13px/1.5 var(--lbw-sans);color:var(--lb-muted);}
.lbw-trow.is-drop-before{box-shadow:inset 0 3px 0 var(--lb-ink);}
.lbw-trow.is-drop-after{box-shadow:inset 0 -3px 0 var(--lb-ink);}
.lbw-trow.is-drop-in{background:var(--lb-soft);outline:1px dashed var(--lb-ink);outline-offset:-1px;}
.lbw-trow.is-dragging{opacity:.4;}
.lbw .lbw-thead{padding:2px 4px 2px 46px;font:400 13px/1.55 var(--lbw-serif);color:var(--lb-muted);}
.lbw .lbw-thead.is-here{color:var(--lb-ink);font-weight:600;}
.lbw .lbw-thead.is-here::before{content:"";position:absolute;left:34px;top:6px;bottom:6px;width:2px;background:var(--lb-ink);}
.lbw-thead .lbw-num{font-size:14px;}
.lbw .lbw-thead.is-l3{padding-left:60px;}
.lbw .lbw-thead.is-l4{padding-left:72px;}
.lbw .lbw-thead.is-fold{padding-left:34px;}
.lbw .lbw-thead:hover{color:var(--lb-ink);}
.lbw-ttags{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:18px;padding-top:14px;border-top:1px solid var(--lb-line);}
.lbw .lbw-ttags button{font:400 12.5px/1.6 var(--lbw-sans);color:var(--lb-muted);}
.lbw .lbw-ttags button:hover,.lbw .lbw-ttags button.is-on{color:var(--lb-ink);text-decoration:underline;text-underline-offset:4px;}
.lbw-tnone{margin:6px 0 0;font:400 12.5px/1.6 var(--lbw-sans);color:var(--lb-muted);}
.lbw .lbw-tsnip{display:block;margin-top:1px;font:400 11.5px/1.5 var(--lbw-sans);color:var(--lb-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbw-blk.is-flash{background:color-mix(in srgb,var(--lb-warn) 14%,transparent);}
.lbw-fab,.lbw-scrim{display:none;}
/* 关系图（10-29：力导向、可拖、可缩放；目录小图 / 首页 / 全局图浮层同一套） */
.lbw-graph{display:block;width:100%;height:auto;overflow:hidden;touch-action:none;user-select:none;-webkit-user-select:none;cursor:grab;}
.lbw-graph:active{cursor:grabbing;}
.lbw-graph .e{stroke:var(--lb-line);stroke-width:1.2;vector-effect:non-scaling-stroke;transition:opacity .15s;}
.lbw-graph .e.x{stroke:var(--lb-muted);stroke-width:1;stroke-dasharray:3 4;}
.lbw-graph .e.is-hl{stroke:var(--lb-ink);}
.lbw-graph .nd{cursor:pointer;transition:opacity .15s;}
.lbw-graph .hit{fill:transparent;}
.lbw-graph .dot{fill:var(--lb-muted);transition:fill .12s;}
.lbw-graph .nd:hover .dot,.lbw-graph .nd.is-hl .dot,.lbw-graph .nd.is-cur .dot,.lbw-graph .nd.is-hub .dot{fill:var(--lb-ink);}
.lbw-graph .nd.is-cur .dot{stroke:var(--lb-surface);stroke-width:2;vector-effect:non-scaling-stroke;}
.lbw-graph text{pointer-events:none;paint-order:stroke;stroke:var(--lb-surface);stroke-width:3px;stroke-linejoin:round;}
.lbw-graph .lab{font-family:var(--lbw-serif);font-weight:400;fill:var(--lb-muted);transition:opacity .15s;}
.lbw-graph .lab.cur,.lbw-graph .nd.is-also .lab,.lbw-graph.has-hover .nd.is-hl .lab{fill:var(--lb-ink);}
.lbw-graph .lab.cur{font-weight:700;}
.lbw-graph .lab.hub{font-weight:700;fill:var(--lb-ink);letter-spacing:.04em;}
.lbw-graph.has-hover .nd:not(.is-hl),.lbw-graph.has-hover .e:not(.is-hl){opacity:.2;}
.lbw-graph .hubn{fill:var(--lb-surface);stroke:none;font-family:var(--lb-font-num);font-style:italic;font-weight:500;}
.lbw-gbg{position:fixed;inset:0;z-index:40;background:var(--background-modifier-cover);display:grid;place-items:center;padding:16px;}
.lbw-gpanel{width:min(1400px,92vw);background:var(--lb-surface);border:1px solid var(--lb-ink);border-radius:2px;box-shadow:var(--lbw-print);padding:16px 20px 14px;color:var(--lb-ink);}
.lbw-gpanel .lbw-sech{margin:0 0 10px;}
.lbw-gpanel .lbw-graph{background-image:radial-gradient(var(--lb-line) 1.1px,transparent 1.3px);background-size:20px 20px;}
.lbw-gpanel .lbw-legend > span + span{margin-left:4px;}
/* 正文 */
.lbw-crumb{display:flex;align-items:baseline;flex-wrap:wrap;gap:9px;font:400 13px/1.4 var(--lbw-serif);color:var(--lb-muted);}
.lbw .lbw-crumb button{color:var(--lb-muted);font:inherit;}
.lbw .lbw-crumb button.lbw-kick{font:700 10px/1.3 var(--lb-font-title);letter-spacing:.26em;}
.lbw .lbw-crumb button:hover{color:var(--lb-ink);}
.lbw-crumb .lbw-sep{color:var(--lb-faint);}
.lbw .lbw-ptitle{display:block;width:100%;height:auto;margin:12px 0 0;padding:0 0 4px;border:0;border-bottom:1px solid transparent;border-radius:0;background:transparent;box-shadow:none;font:700 36px/1.25 var(--lbw-serif);letter-spacing:.02em;color:var(--lb-ink);}
.lbw .lbw-ptitle:hover{border-bottom-color:var(--lb-line);}
.lbw .lbw-ptitle:focus,.lbw .lbw-ptitle:focus-visible{outline:none;box-shadow:none;border-bottom-color:var(--lb-ink);}
.lbw .lbw-ptitle[readonly]{border-bottom-color:transparent;}
.lbw-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin-top:14px;font:400 12.5px/1.6 var(--lbw-sans);color:var(--lb-muted);}
.lbw-meta .lbw-num{font-size:16px;color:var(--lb-ink);}
.lbw-meta .lbw-dot{color:var(--lb-faint);}
.lbw-chips{display:inline-flex;flex-wrap:wrap;align-items:center;gap:6px;margin-left:4px;}
.lbw .lbw-chip{display:inline-flex;align-items:center;gap:4px;height:24px;padding:0 11px;border:1px solid var(--lb-ink);border-radius:999px;font:400 12px/1 var(--lbw-sans);color:var(--lb-ink);text-decoration:none;}
.lbw .lbw-chip:hover{background:var(--lb-ink);color:var(--lb-surface);}
.lbw-chip .lbw-x{display:none;margin:0 -4px 0 2px;padding:0 3px;opacity:.7;}
.lbw-chip:hover .lbw-x{display:inline;}
.lbw .lbw-chipadd{display:inline-grid;place-items:center;width:24px;height:24px;border:1px dashed var(--lb-muted);border-radius:999px;color:var(--lb-muted);}
.lbw-chipadd .lbw-ico{width:12px;height:12px;}
.lbw .lbw-chipadd:hover{border-style:solid;border-color:var(--lb-ink);color:var(--lb-ink);}
.lbw .lbw-chipin{height:24px;width:120px;border:0;border-bottom:1px solid var(--lb-ink);border-radius:0;padding:0 2px;background:transparent;box-shadow:none;color:var(--lb-ink);font:400 12.5px var(--lbw-sans);}
.lbw .lbw-chipin:focus{outline:none;box-shadow:none;}
.lbw-draft{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin-top:22px;padding:10px 14px;border:1px solid var(--lb-warn);border-radius:2px;font:400 12.5px/1.6 var(--lbw-sans);color:var(--lb-ink);}
.lbw-draft .lbw-dt{color:var(--lb-warn);font-weight:500;}
.lbw-draft .lbw-sp{flex:1;}
.lbw-doc{margin-top:36px;font:400 15.5px/1.95 var(--lbw-serif);color:var(--lb-ink);overflow-wrap:anywhere;}
.lbw-doc p{margin:0;}
.lbw-doc h1,.lbw-doc h2,.lbw-doc h3,.lbw-doc h4{margin:0;color:var(--lb-ink);}
.lbw-doc h1{font:700 24px/1.4 var(--lbw-serif);padding-top:28px;}
.lbw-doc h2{display:flex;align-items:baseline;gap:12px;padding-top:26px;font:700 19px/1.4 var(--lbw-serif);}
.lbw-doc h2::after{content:"";flex:1;align-self:center;height:1px;background:var(--lb-line);}
.lbw-doc h3{font:700 16.5px/1.5 var(--lbw-serif);padding-top:12px;}
.lbw-doc h4{font:600 15px/1.5 var(--lbw-serif);color:var(--lb-muted);}
.lbw-doc .lbw-hn{font-weight:500;color:var(--lb-muted);margin-right:10px;}
.lbw-doc h2 .lbw-hn{margin-right:0;font-size:22px;}
.lbw-doc ul,.lbw-doc ol{margin:0;padding:0;}
.lbw-doc ul{list-style:none;}
.lbw-doc ol{padding-left:1.7em;}
.lbw-doc ol > li::marker{font-family:var(--lb-font-num);font-style:italic;font-size:1.1em;color:var(--lb-muted);}
.lbw-doc ul > li{position:relative;padding-left:24px;}
.lbw-doc li + li{margin-top:5px;}
.lbw-doc ul > li::before{content:"";position:absolute;left:3px;top:.98em;width:9px;height:1px;background:var(--lb-ink);}
.lbw-doc ul > li.lbw-task{display:flex;align-items:flex-start;gap:11px;padding-left:2px;}
.lbw-doc ul > li.lbw-task::before{display:none;}
.lbw .lbw-task input{flex:none;appearance:none;-webkit-appearance:none;width:14px;height:14px;margin:.55em 0 0;border:1px solid var(--lb-ink);border-radius:2px;background:transparent;cursor:pointer;}
.lbw .lbw-task input:checked{background:var(--lb-ink);box-shadow:inset 0 0 0 2.5px var(--lb-surface);}
.lbw .lbw-task input:disabled{cursor:default;}
.lbw-task.is-done > span{color:var(--lb-muted);text-decoration:line-through;text-decoration-color:var(--lb-faint);}
.lbw-doc blockquote{margin:0;padding:2px 0 2px 18px;border-left:1px solid var(--lb-faint);font:400 13.5px/1.9 var(--lbw-sans);color:var(--lb-muted);}
.lbw-doc pre{margin:0;padding:12px 0;border-top:1px solid var(--lb-line);border-bottom:1px solid var(--lb-line);background:none;overflow:auto;font:12.5px/1.7 var(--lbw-mono);color:var(--lb-ink);}
.lbw-doc code{font:.84em var(--lbw-mono);color:var(--lb-muted);background:none;padding:0;}
.lbw-doc pre code{color:inherit;font-size:inherit;}
.lbw-doc hr{border:0;border-top:1px solid var(--lb-line);margin:10px 0;}
.lbw-doc img{max-width:100%;border-radius:12px;}
.lbw-blk{position:relative;margin:0 -16px;padding:3px 16px;border-radius:2px;transition:background-color .12s;}
.lbw:not(.is-ro) .lbw-blk{cursor:text;}
.lbw-blk + .lbw-blk{margin-top:12px;}
.lbw:not(.is-ro) .lbw-blk:hover{background:var(--lb-soft);}
.lbw .lbw-addblk{display:block;margin-top:18px;padding:4px 0;color:var(--lb-muted);cursor:text;font:400 14px/1.6 var(--lbw-serif);}
.lbw .lbw-addblk:hover{color:var(--lb-ink);}
.lbw .lbw-srced{display:block;width:100%;min-height:60vh;resize:vertical;margin-top:22px;border:1px solid var(--lb-ink);border-radius:2px;padding:16px 18px;background:var(--lb-surface);color:var(--lb-ink);font:13.5px/1.8 var(--lbw-mono);box-shadow:var(--lbw-print);}
.lbw .lbw-srced:focus{outline:none;}
.lbw-fm{margin-top:18px;font:12px/1.6 var(--lbw-mono);color:var(--lb-muted);white-space:pre;overflow:auto;}
.lbw-hint{display:flex;flex-wrap:wrap;align-items:center;gap:6px 16px;margin-top:56px;padding-top:14px;border-top:1px solid var(--lb-line);font:400 12px/1.6 var(--lbw-sans);color:var(--lb-muted);}
.lbw-hint > span{display:inline-flex;align-items:center;gap:6px;}
/* 三种可点的东西：实线 = Wiki 页；点线 + 编号圈 = 收藏；灰字 = #标签 */
.lbw .lbw-pl{color:var(--lb-ink);text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:5px;cursor:pointer;}
.lbw .lbw-pl:hover{text-decoration-thickness:2px;}
.lbw .lbw-ext{color:var(--lb-ink);text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:5px;text-decoration-color:var(--lb-muted);}
.lbw .lbw-ext:hover{text-decoration-color:var(--lb-ink);}
.lbw-ext .lbw-m{margin-left:2px;font:400 .8em var(--lbw-sans);color:var(--lb-muted);}
.lbw .lbw-cite{color:var(--lb-ink);text-decoration:underline dotted;text-decoration-thickness:1.6px;text-underline-offset:5px;text-decoration-color:var(--lb-muted);cursor:pointer;}
.lbw .lbw-cite:hover{text-decoration-color:var(--lb-ink);}
.lbw-cite .lbw-ref{display:inline-grid;place-items:center;min-width:18px;height:18px;margin:0 2px 0 4px;padding:0 4px;border:1px solid var(--lb-ink);border-radius:999px;vertical-align:2px;font:italic 500 13px/1 var(--lb-font-num);color:var(--lb-ink);text-decoration:none;}
.lbw .lbw-cite.is-open{text-decoration-style:solid;text-decoration-color:var(--lb-ink);text-decoration-thickness:1px;}
.lbw-cite.is-open .lbw-ref{background:var(--lb-ink);color:var(--lb-surface);}
.lbw .lbw-cite.is-missing{color:var(--lb-muted);text-decoration-style:dashed;text-decoration-color:var(--lb-warn);}
.lbw-cite.is-missing .lbw-ref{border-style:dashed;border-color:var(--lb-warn);color:var(--lb-warn);font:400 10.5px/1 var(--lbw-sans);}
.lbw .lbw-htag{font:400 .86em var(--lbw-sans);color:var(--lb-muted);text-decoration:none;cursor:pointer;}
.lbw .lbw-htag:hover{color:var(--lb-ink);text-decoration:underline;text-underline-offset:4px;}
/* 自动列表 / 文件清单 */
.lbw-plist{border-top:1px solid var(--lb-ink);}
.lbw-plist-h{display:flex;align-items:baseline;gap:10px;padding:10px 0 6px;}
.lbw-plist-h .lbw-kick{font-size:10px;}
.lbw-plist-h .lbw-cap{font-size:12px;}
.lbw-plist-h > .lbw-num{margin-left:auto;font-size:16px;color:var(--lb-muted);}
.lbw .lbw-prow{display:grid;grid-template-columns:34px minmax(0,1fr) auto;column-gap:14px;align-items:baseline;width:100%;padding:9px 0;border-top:1px solid var(--lb-line);text-align:left;color:var(--lb-ink);text-decoration:none;font:inherit;}
.lbw-prow > .lbw-num{font-size:16px;color:var(--lb-muted);}
.lbw-prow > .lbw-k{font:400 11.5px/1.6 var(--lbw-sans);color:var(--lb-muted);}
.lbw-prow .lbw-pt{min-width:0;}
.lbw-prow .lbw-t{display:block;font:600 15px/1.5 var(--lbw-serif);}
.lbw-prow .lbw-l{display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font:400 13px/1.6 var(--lbw-serif);color:var(--lb-muted);}
.lbw-prow .lbw-d{font:400 12px/1.6 var(--lbw-sans);color:var(--lb-muted);}
.lbw-prow .lbw-d.lbw-num{font-size:14px;}
.lbw .lbw-prow:hover .lbw-t{text-decoration:underline;text-underline-offset:4px;}
.lbw-rest{margin-top:48px;}
.lbw-rnone{margin:10px 0 0;color:var(--lb-muted);font:400 13px/1.6 var(--lbw-sans);}
/* 编辑态（10-31 作者：「不要跳出来一个巨大的黑框，就正常改」）：原地改——编辑框套在和阅读时同一个元素里（p / h2 / li / blockquote），
   字体、字号、行距、缩进全继承，点开不跳；只有一条浅色小工具条浮在这一段右上角（绝对定位，不占地方） */
.lbw-blk.is-editing{background:var(--lb-soft);cursor:text;}
.lbw .lbw-ed,.lbw .lbw-ed:hover,.lbw .lbw-ed:focus,.lbw .lbw-ed:focus-visible{display:block;width:100%;min-width:0;height:auto;min-height:0;margin:0;padding:0;border:0;border-radius:0;background:transparent;box-shadow:none;outline:none;resize:none;overflow:hidden;font:inherit;line-height:inherit;letter-spacing:inherit;color:inherit;caret-color:var(--lb-ink);}
.lbw-ed::placeholder{color:var(--lb-faint);}
.lbw-doc h2.is-ed::after{display:none;}
.lbw-doc h2.is-ed .lbw-ed,.lbw-doc li.lbw-task .lbw-ed{flex:1;}
.lbw-blk.is-raw .lbw-ed{font:12.5px/1.7 var(--lbw-mono);}
.lbw-edbox{display:inline-block;width:14px;height:14px;flex:none;margin:.55em 0 0;border:1px solid var(--lb-ink);border-radius:2px;}
.lbw-edbar{position:absolute;right:0;bottom:100%;z-index:3;display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:0;max-width:100%;margin-bottom:3px;padding:2px 4px;border:1px solid var(--lb-line);border-radius:999px;background:var(--lb-surface);font:400 11.5px/1 var(--lbw-sans);color:var(--lb-muted);}
.lbw .lbw-edbar button{height:22px;padding:0 7px;border-radius:999px;color:var(--lb-muted);font:inherit;}
.lbw .lbw-edbar button:hover{color:var(--lb-ink);background:var(--lb-soft);}
.lbw .lbw-edbar button.is-on{color:var(--lb-ink);font-weight:600;}
.lbw .lbw-edbar button.is-ai{color:var(--lb-ink);}
.lbw-edbar .lbw-sep{width:1px;height:10px;margin:0 3px;background:var(--lb-line);}
/* 宽屏：工具条放到正文右边的空白里，不压上一行的字；中等宽 / 开着右栏 / 手机还在这段右上角 */
.lbw:not(.is-mid):not(.has-side) .lbw-edbar{left:calc(100% + 10px);right:auto;bottom:auto;top:0;flex-wrap:nowrap;width:max-content;max-width:none;margin:0;}
/* 段和段之间：左边空白里悬停出一个 ＋，点了在这段后面插一段 */
.lbw .lbw-ins{position:absolute;left:-14px;top:3px;width:22px;height:22px;display:grid;place-items:center;border-radius:999px;color:var(--lb-faint);opacity:0;transition:opacity .12s;font:400 15px/1 var(--lbw-sans);}
.lbw-blk:hover > .lbw-ins{opacity:1;}
.lbw .lbw-ins:hover{color:var(--lb-ink);background:var(--lb-surface);}
.lbw-blk.is-li + .lbw-blk.is-li{margin-top:3px;}
.lbw-blk.is-editing > .lbw-ins{display:none;}
/* 让 AI 改：这一段下面的小面板 / 整页在右侧栏 */
.lbw-ai{margin:8px 0 4px;padding:12px 14px;border:1px solid var(--lb-line);border-radius:2px;background:var(--lb-surface);font:400 12.5px/1.6 var(--lbw-sans);color:var(--lb-ink);}
.lbw-ai-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px;}
.lbw .lbw-ai-row button{height:26px;padding:0 10px;border:1px solid var(--lb-line);border-radius:999px;color:var(--lb-ink);font:inherit;}
.lbw .lbw-ai-row button:hover{border-color:var(--lb-ink);}
/* 1101：现成说法是一行字，用 | 隔开（不是一排胶囊） */
.lbw .lbw-ai-presets{gap:4px 10px;}
.lbw .lbw-ai-presets button{height:auto;padding:2px 0;border:0;border-radius:0;background:transparent;color:var(--lb-ink);}
.lbw .lbw-ai-presets button:hover{border:0;color:var(--lb-accent,var(--lb-ink));text-decoration:underline;text-underline-offset:3px;}
.lbw .lbw-ai-pipe{color:var(--lb-faint);user-select:none;}
.lbw .lbw-ai-row button.is-solid{background:var(--lb-ink);border-color:var(--lb-ink);color:var(--lb-surface);}
.lbw .lbw-ai input[type=text]{flex:1 1 220px;min-width:0;height:28px;border:0;border-bottom:1px solid var(--lb-ink);border-radius:0;padding:0 2px;background:transparent;box-shadow:none;color:var(--lb-ink);font:400 13px var(--lbw-sans);}
.lbw .lbw-ai input[type=text]:focus{outline:none;box-shadow:none;}
.lbw-ai-note{margin:8px 0 0;color:var(--lb-muted);}
.lbw-ai-note.is-warn{color:var(--lb-warn);}
.lbw-ai-out{margin:10px 0;padding:8px 12px;border-left:2px solid var(--lb-ink);font:400 15px/1.9 var(--lbw-serif);}
/* 逐处勾选：划掉的原文 + 加粗的新字；点一处切换；不要的那处只剩原文（淡一点的虚线框） */
.lbw-ai-diff{max-height:60vh;overflow:auto;margin:4px 0 0;padding:10px 12px;border-left:2px solid var(--lb-ink);white-space:pre-wrap;overflow-wrap:anywhere;font:400 14.5px/1.9 var(--lbw-serif);color:var(--lb-ink);}
.lbw-hk{cursor:pointer;border-radius:2px;box-shadow:0 0 0 1px var(--lb-line);}
.lbw-hk:hover{box-shadow:0 0 0 1px var(--lb-ink);}
.lbw-hk del{color:var(--lb-muted);text-decoration:line-through;text-decoration-color:var(--lb-warn);}
.lbw-hk ins{text-decoration:none;font-weight:700;background:color-mix(in srgb,var(--lb-ink) 8%,transparent);}
.lbw-hk.is-off ins{display:none;}
.lbw-hk.is-off del{text-decoration:none;color:var(--lb-ink);}
.lbw-hk.is-off{box-shadow:0 0 0 1px var(--lb-line);outline:1px dashed var(--lb-faint);}
.lbw .lbw-ai-row button:disabled{opacity:.4;cursor:default;}
.lbw-blk.is-ai-lock{outline:1px dashed var(--lb-muted);outline-offset:-1px;background:color-mix(in srgb,var(--lb-ink) 3%,transparent);cursor:default;}
.lbw-blk.is-ai-lock + .lbw-blk.is-ai-lock{margin-top:0;}
.lbw-blk.is-ai-lock.is-page{outline:none;margin-top:12px;}   /* 整页改：不一段段画框，淡底就够 */
.lbw .lbw-ai-idea{display:block;width:100%;min-height:120px;resize:vertical;padding:8px 10px;border:1px solid var(--lb-line);border-radius:2px;background:var(--lb-surface);box-shadow:none;color:var(--lb-ink);font:400 14px/1.8 var(--lbw-serif);}
.lbw .lbw-ai-idea:focus{outline:none;border-color:var(--lb-ink);}
.lbw-plan-sec{padding:8px 0;border-top:1px solid var(--lb-line);}
.lbw-plan-sec .lbw-num{font-size:16px;color:var(--lb-muted);min-width:14px;}
.lbw-ai-bad{margin:8px 0;padding:8px 10px;border:1px solid var(--lb-warn);border-radius:2px;color:var(--lb-warn);font:400 12.5px/1.7 var(--lbw-sans);}
.lbw-ai-bad > div{color:var(--lb-ink);}
.lbw-ai-srcs{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:8px;font:400 12.5px/1.7 var(--lbw-sans);}
/* 底部 AI 对话框：方框、浮在正文那一栏底部（和问收藏底部输入框一个样子） */
.lbw-dock{position:fixed;z-index:25;box-sizing:border-box;padding:10px 14px 12px;border:1px solid var(--lb-line);border-radius:14px;background:var(--lb-surface);box-shadow:0 8px 28px rgba(0,0,0,.18);font:400 13px/1.6 var(--lbw-sans);color:var(--lb-ink);}
.lbw-dock-head{display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid var(--lb-line);}
.lbw-dock-head .lbw-kick{margin-right:4px;}
.lbw .lbw-dock-head button{height:26px;padding:0 10px;border-radius:8px;color:var(--lb-muted);font:inherit;font-size:12.5px;}
.lbw .lbw-dock-head button:hover{color:var(--lb-ink);background:var(--lb-soft);}
.lbw .lbw-dock-head button.is-on{color:var(--lb-ink);background:var(--lb-soft);font-weight:600;}
.lbw-dock-head .lbw-sp{flex:1;}
.lbw-dock-body{max-height:52vh;overflow:auto;}
.lbw-dock .lbw-ai{margin:0;padding:0;border:0;background:transparent;}
.lbw-dock .lbw-ai-diff{max-height:none;}
.lbw .lbw-selai{position:fixed;z-index:30;height:28px;padding:0 12px;border:1px solid var(--lb-ink);border-radius:999px;background:var(--lb-surface);color:var(--lb-ink);font:500 12.5px/1 var(--lbw-sans);box-shadow:2px 2px 0 var(--lb-ink);}
.lbw-ai-out p{margin:0 0 6px;}
/* 目录首页 */
.lbw-gap{margin-top:80px;}
.lbw-ov{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px 32px;}
.lbw-ov .lbw-big{display:block;font:italic 400 88px/.9 var(--lb-font-num);letter-spacing:-.01em;font-variant-numeric:lining-nums;color:var(--lb-ink);}
.lbw-ov .lbw-lab{display:block;margin-top:14px;font:400 14px/1.4 var(--lbw-sans);color:var(--lb-ink);}
.lbw-folders{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:40px;}
.lbw .lbw-fold{position:relative;display:block;height:300px;width:100%;text-align:left;color:var(--lb-ink);font:inherit;}
.lbw-fold-tab{position:absolute;left:0;top:0;width:46%;height:36px;display:flex;align-items:center;padding:0 14px;border:1px solid var(--lb-ink);border-bottom:0;border-radius:10px 16px 0 0;background:var(--lb-soft);}
.lbw-fold-tab .lbw-kick{font-size:9.5px;letter-spacing:.22em;white-space:nowrap;overflow:hidden;}
.lbw-fold-back{position:absolute;left:0;right:0;top:35px;bottom:0;border:1px solid var(--lb-ink);border-radius:0 14px 14px 14px;background:var(--lb-soft);}
.lbw-fold-sheet{position:absolute;left:30%;right:6%;top:18px;height:150px;padding:12px 14px;border:1px solid var(--lb-line);border-radius:2px;background:var(--lb-surface);transform:rotate(-2.2deg);transform-origin:20% 100%;transition:transform .28s cubic-bezier(.2,.8,.2,1);font:400 10.5px/1.75 var(--lbw-sans);color:var(--lb-muted);overflow:hidden;white-space:nowrap;}
.lbw-fold-sheet.is-s2{left:42%;right:2%;top:26px;transform:rotate(3deg);transform-origin:80% 100%;}
.lbw-fold-sheet .lbw-num{font-size:12px;margin-right:4px;}
.lbw-fold-sheet span{display:block;overflow:hidden;text-overflow:ellipsis;}
.lbw-fold-face{position:absolute;left:0;right:0;top:82px;bottom:0;display:flex;flex-direction:column;padding:18px 22px 20px;border:1px solid var(--lb-ink);border-radius:2px 14px 14px 14px;background:var(--lb-surface);transition:transform .2s,box-shadow .2s;}
.lbw .lbw-fold:hover .lbw-fold-face,.lbw .lbw-fold:focus-visible .lbw-fold-face{transform:translate(-3px,-3px);box-shadow:var(--lbw-print);}
.lbw .lbw-fold:hover .lbw-fold-sheet{transform:translateY(-14px) rotate(-4deg);}
.lbw .lbw-fold:hover .lbw-fold-sheet.is-s2{transform:translateY(-8px) rotate(5deg);}
.lbw-fold-num{position:absolute;right:20px;top:12px;font:italic 500 96px/1 var(--lb-font-num);font-variant-numeric:lining-nums;color:var(--lb-ink);}
.lbw-fold-dots{display:flex;flex-wrap:wrap;gap:6px;max-width:56%;margin-top:4px;}
.lbw-fold-dots i{display:block;width:7px;height:7px;border-radius:50%;background:var(--lb-ink);}
.lbw-fold-dots i.is-o{background:none;box-shadow:inset 0 0 0 1.2px var(--lb-ink);}
.lbw-fold-name{margin-top:auto;font:700 30px/1.15 var(--lbw-serif);letter-spacing:.02em;overflow-wrap:anywhere;}
.lbw-fold-cap{margin-top:8px;font:400 12px/1.4 var(--lbw-sans);color:var(--lb-muted);}
.lbw-fold-cap .lbw-num{font-size:15px;color:var(--lb-ink);}
.lbw-fold.is-loose .lbw-fold-tab,.lbw-fold.is-loose .lbw-fold-back,.lbw-fold.is-loose .lbw-fold-face{border-style:dashed;}
.lbw-fold.is-new .lbw-fold-tab,.lbw-fold.is-new .lbw-fold-face{border:1px dashed var(--lb-muted);background:none;}
.lbw-fold.is-new .lbw-fold-tab{border-bottom:0;}
.lbw-fold.is-new .lbw-fold-face{top:35px;align-items:center;justify-content:center;gap:6px;border-radius:0 14px 14px 14px;}
.lbw .lbw-fold.is-new:hover .lbw-fold-face{transform:none;box-shadow:none;border-color:var(--lb-ink);}
.lbw-fold.is-new .lbw-plus{font:300 64px/1 var(--lb-font-num);color:var(--lb-muted);}
.lbw-map{position:relative;padding:34px 30px 30px;background-color:var(--lb-surface);background-image:radial-gradient(var(--lb-line) 1.1px,transparent 1.3px);background-size:20px 20px;}
.lbw-map .lbw-crop{position:absolute;width:14px;height:14px;border:0 solid var(--lb-ink);}
.lbw-map .is-tl{left:0;top:0;border-left-width:1px;border-top-width:1px;}
.lbw-map .is-tr{right:0;top:0;border-right-width:1px;border-top-width:1px;}
.lbw-map .is-bl{left:0;bottom:0;border-left-width:1px;border-bottom-width:1px;}
.lbw-map .is-br{right:0;bottom:0;border-right-width:1px;border-bottom-width:1px;}
.lbw-map .lbw-corner{position:absolute;font:400 11px/1 var(--lbw-sans);color:var(--lb-muted);letter-spacing:.04em;}
.lbw-map .lbw-corner .lbw-num{font-size:15px;color:var(--lb-ink);}
.lbw-map .lbw-corner.is-n{left:16px;top:12px;}
.lbw-map .lbw-corner.is-mark{right:18px;bottom:14px;font:700 9px/1 var(--lb-font-title);letter-spacing:.24em;}
.lbw-fhead{display:flex;align-items:flex-end;gap:22px;margin-top:10px;}
.lbw-fhead .lbw-big{flex:none;font:italic 500 128px/.78 var(--lb-font-num);font-variant-numeric:lining-nums;letter-spacing:-.02em;color:var(--lb-ink);}
.lbw .lbw-fhead .lbw-ptitle{margin:0;font-size:42px;line-height:1.1;padding-bottom:6px;}
/* 右侧历史栏（设计稿放在 Obsidian 右栏；这里放在本页里，见文件头） */
.lbw-side{position:sticky;top:20px;align-self:start;max-height:calc(100vh - 40px);overflow:auto;margin-top:44px;padding:0 0 40px 24px;border-left:1px solid var(--lb-line);}
.lbw-rbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;font:400 13.5px/1.4 var(--lbw-sans);color:var(--lb-muted);}
.lbw .lbw-rbar button{color:var(--lb-muted);font:inherit;}
.lbw .lbw-rbar button:hover{color:var(--lb-ink);}
.lbw-rbar .is-on{color:var(--lb-ink);font-weight:600;}
.lbw-verbar{display:flex;align-items:center;gap:10px;margin:22px 0 14px;}
.lbw .lbw-verbar input{flex:1;min-width:0;height:34px;border:0;border-bottom:1px solid var(--lb-ink);border-radius:0;padding:0;background:transparent;box-shadow:none;color:var(--lb-ink);font:400 14px var(--lbw-serif);}
.lbw .lbw-verbar input:focus{outline:none;box-shadow:none;}
.lbw .lbw-ver{display:grid;grid-template-columns:auto 1fr auto;gap:2px 12px;align-items:baseline;width:100%;padding:9px 6px;border-top:1px solid var(--lb-line);text-align:left;font:400 14px/1.5 var(--lbw-serif);}
.lbw .lbw-ver:hover,.lbw .lbw-ver.is-on{background:var(--lb-soft);}
.lbw-ver .lbw-k{font:400 11px/1.6 var(--lbw-sans);border:1px solid var(--lb-line);border-radius:999px;padding:0 8px;color:var(--lb-muted);}
.lbw-ver.is-on .lbw-k{border-color:var(--lb-ink);color:var(--lb-ink);}
.lbw-ver .lbw-w{grid-column:2/4;color:var(--lb-muted);font-size:13px;}
.lbw-note{font:400 12px/1.65 var(--lbw-sans);color:var(--lb-muted);}
.lbw-diff{font:12.5px/1.65 var(--lbw-mono);border-top:1px solid var(--lb-ink);border-bottom:1px solid var(--lb-line);overflow:auto;max-height:46vh;margin:12px 0;}
.lbw-diff div{padding:0 8px;white-space:pre-wrap;word-break:break-all;}
.lbw-diff .is-a{background:color-mix(in srgb,var(--lb-ok) 14%,transparent);}
.lbw-diff .is-d{background:color-mix(in srgb,var(--lb-danger) 12%,transparent);text-decoration:line-through;text-decoration-color:var(--lb-muted);}
.lbw-diff .is-c{color:var(--lb-muted);}
/* 弹层（@ 补全、菜单、新建）：墨线框 + 错版投影 */
.lbw-pop{position:fixed;z-index:30;min-width:240px;max-width:380px;background:var(--lb-surface);border:1px solid var(--lb-ink);border-radius:2px;box-shadow:var(--lbw-print);padding:0 0 4px;color:var(--lb-ink);}
.lbw-pop.is-menu{padding:4px 0;}
.lbw-pop.is-sug{width:380px;}
.lbw-pop .lbw-ph{display:flex;align-items:center;gap:10px;padding:11px 14px 9px;margin-bottom:4px;border-bottom:1px solid var(--lb-line);}
.lbw-pop .lbw-ph .lbw-kick{font-size:10px;}
.lbw-pop .lbw-ph .lbw-cap{font-size:12px;}
.lbw-pop .lbw-ph .lbw-q{margin-left:auto;font:600 13px var(--lbw-serif);color:var(--lb-ink);}
.lbw .lbw-pop button{display:block;width:100%;text-align:left;padding:8px 14px;font:500 14px/1.45 var(--lbw-serif);color:var(--lb-ink);}
.lbw-pop button small{display:block;margin-top:2px;font:400 11.5px/1.4 var(--lbw-sans);color:var(--lb-muted);}
.lbw .lbw-pop button:hover{background:var(--lb-soft);}
.lbw .lbw-pop button.is-on{background:var(--lb-ink);color:var(--lb-surface);}
.lbw-pop button.is-on small{color:var(--lb-surface);opacity:.72;}
.lbw .lbw-pop button:disabled{opacity:.45;cursor:default;background:none;color:var(--lb-ink);}
.lbw-pop hr{border:0;border-top:1px solid var(--lb-line);margin:4px 0;}
.lbw-pop .lbw-pf{display:flex;flex-wrap:wrap;gap:4px 14px;padding:8px 14px 6px;margin-top:4px;border-top:1px solid var(--lb-line);font:400 11px/1.4 var(--lbw-sans);color:var(--lb-muted);}
.lbw-mbg{position:fixed;inset:0;z-index:40;background:var(--background-modifier-cover);display:grid;place-items:center;padding:16px;}
.lbw-modal{width:min(440px,100%);background:var(--lb-surface);border:1px solid var(--lb-ink);border-radius:2px;padding:24px 26px 22px;display:grid;gap:20px;box-shadow:var(--lbw-print);color:var(--lb-ink);}
.lbw-modal .lbw-mh{display:grid;gap:6px;}
.lbw-modal .lbw-mh .lbw-kick{font-size:10px;color:var(--lb-muted);}
.lbw-modal h3{margin:0;font:700 22px/1.3 var(--lbw-serif);letter-spacing:.02em;}
.lbw-modal label{display:grid;gap:4px;font:400 12.5px/1.5 var(--lbw-sans);color:var(--lb-muted);}
.lbw .lbw-modal input[type=text],.lbw .lbw-modal select{height:38px;border:0;border-bottom:1px solid var(--lb-ink);border-radius:0;padding:0;background:var(--lb-surface);box-shadow:none;color:var(--lb-ink);font:400 16px var(--lbw-serif);}
.lbw .lbw-modal input[type=text]:focus,.lbw .lbw-modal select:focus{outline:none;box-shadow:none;border-bottom-width:2px;}
.lbw-modal label.lbw-chk{display:flex;gap:10px;align-items:center;color:var(--lb-ink);font-size:13px;}
.lbw .lbw-modal .lbw-chk input{appearance:none;-webkit-appearance:none;width:14px;height:14px;margin:0;border:1px solid var(--lb-ink);border-radius:2px;cursor:pointer;}
.lbw .lbw-modal .lbw-chk input:checked{background:var(--lb-ink);box-shadow:inset 0 0 0 2.5px var(--lb-surface);}
.lbw-modal .lbw-acts2{display:flex;justify-content:flex-end;align-items:center;gap:8px;}
/* 中等宽（右边开着原文格）：目录变窄；再窄：目录收成左下角「目录」，点开从底部升起 */
.lbw.is-mid{padding:24px 32px 0;}
.lbw.is-mid .lbw-brand{font-size:40px;}
.lbw.is-mid .lbw-main,.lbw.is-mid.is-home .lbw-main{grid-template-columns:200px minmax(0,1fr);column-gap:40px;padding-top:36px;}
.lbw.is-mid .lbw-ptitle{font-size:32px;}
.lbw.is-mid .lbw-ov .lbw-big{font-size:72px;}
.lbw.is-mid .lbw-fhead .lbw-big{font-size:104px;}
.lbw.is-mid .lbw-fhead .lbw-ptitle{font-size:36px;}
.lbw.is-mid.has-side .lbw-body{grid-template-columns:minmax(0,1fr);}
.lbw.is-mid .lbw-side{position:fixed;top:0;right:0;bottom:0;width:min(400px,100%);max-height:none;z-index:20;margin:0;padding:26px 24px 40px;background:var(--lb-surface);border-left:1px solid var(--lb-ink);}
.lbw.is-narrow{padding:18px 18px 0;}
.lbw.is-narrow .lbw-brand{font-size:30px;}
.lbw.is-narrow .lbw-hrow{gap:8px;}
.lbw.is-narrow .lbw-acts{padding-bottom:2px;gap:2px;}
.lbw.is-narrow .lbw-main,.lbw.is-narrow.is-home .lbw-main{display:block;padding:30px 0 120px;}
.lbw.is-narrow .lbw-ptitle{font-size:28px;margin-top:10px;}
.lbw.is-narrow .lbw-meta{margin-top:10px;}
.lbw.is-narrow .lbw-chips{margin-left:0;}
.lbw.is-narrow .lbw-doc{margin-top:28px;}
.lbw.is-narrow .lbw-doc h2{padding-top:22px;font-size:18px;}
.lbw.is-narrow .lbw-edbar{border-radius:18px;}
.lbw.is-narrow .lbw-toc{display:none;position:fixed;left:0;right:0;bottom:0;top:auto;width:auto;margin:0;max-height:78vh;z-index:15;background:var(--lb-surface);border-top:1px solid var(--lb-ink);border-radius:18px 18px 0 0;padding:26px 20px 28px;}
.lbw.is-narrow .lbw-toc::before{content:"";position:absolute;left:50%;top:10px;width:40px;height:4px;margin-left:-20px;border-radius:999px;background:var(--lb-line);}
.lbw.is-narrow .lbw-toc.is-open{display:block;}
.lbw.is-narrow .lbw-toc.is-open + .lbw-scrim{display:block;position:fixed;inset:0;z-index:14;background:var(--background-modifier-cover);}
.lbw.is-narrow .lbw-tools button,.lbw.is-narrow .lbw-mpin{width:44px;height:44px;}
.lbw.is-narrow .lbw-tpage{padding-top:9px;padding-bottom:9px;}
.lbw.is-narrow .lbw-tmap .lbw-graph{max-width:280px;margin-left:auto;margin-right:auto;}
.lbw.is-narrow .lbw-fab{display:inline-flex;align-items:center;gap:8px;position:fixed;left:16px;bottom:22px;z-index:13;height:44px;padding:0 18px 0 14px;border:1px solid var(--lb-ink);border-radius:999px;background:var(--lb-surface);box-shadow:3px 3px 0 var(--lb-ink);font:500 14px/1 var(--lbw-sans);color:var(--lb-ink);}
.lbw.is-narrow .lbw-sech{gap:10px;margin-bottom:20px;}
.lbw.is-narrow .lbw-sech .lbw-cap,.lbw.is-narrow .lbw-sech .lbw-legend{display:none;}
.lbw.is-narrow .lbw-gap{margin-top:52px;}
.lbw.is-narrow .lbw-ov{grid-template-columns:repeat(2,minmax(0,1fr));gap:26px 18px;}
.lbw.is-narrow .lbw-ov .lbw-big{font-size:64px;}
.lbw.is-narrow .lbw-folders{grid-template-columns:repeat(2,minmax(0,1fr));gap:24px 16px;}
.lbw.is-narrow .lbw-fold{height:206px;}
.lbw.is-narrow .lbw-fold-tab{height:28px;padding:0 10px;}
.lbw.is-narrow .lbw-fold-back{top:27px;}
.lbw.is-narrow .lbw-fold-sheet{left:49%;right:5%;top:12px;height:96px;padding:8px 10px;font-size:9.5px;}
.lbw.is-narrow .lbw-fold-sheet.is-s2{display:none;}
.lbw.is-narrow .lbw-fold-face{top:58px;padding:12px 14px 14px;}
.lbw.is-narrow .lbw-fold-num{right:12px;top:6px;font-size:58px;}
.lbw.is-narrow .lbw-fold-name{font-size:21px;}
.lbw.is-narrow .lbw-fold.is-new .lbw-fold-face{top:27px;}
.lbw.is-narrow .lbw-map{padding:26px 6px 22px;}
.lbw.is-narrow .lbw-fhead{gap:14px;}
.lbw.is-narrow .lbw-fhead .lbw-big{font-size:76px;}
.lbw.is-narrow .lbw-fhead .lbw-ptitle{font-size:28px;}
.lbw.is-narrow .lbw-hint{margin-top:44px;}
/* 收起目录：压过上面中等宽度的「目录 200px + 正文」两列（10-31：以前正文被塞进 200px 那一列，首页挤成一条） */
.lbw.is-mid.is-tocoff:not(.is-narrow) .lbw-main{grid-template-columns:minmax(0,760px);justify-content:center;}
.lbw.is-mid.is-tocoff.is-home:not(.is-narrow) .lbw-main{grid-template-columns:minmax(0,1fr);}
@media (prefers-reduced-motion: reduce){.lbw-fold-sheet,.lbw-fold-face,.lbw-tw,.lbw-chev{transition:none;}}
${LB.brandCss('.lbw .lbw-brand', '.lbw .lbw-engr')}
.lbw .lbw-brand{font-size:44px;line-height:1.02;transform-origin:left center;}
.lbw.is-mid .lbw-brand{font-size:40px;}
.lbw.is-narrow .lbw-brand{font-size:30px;}
/* ── 1101 设计交接包（design/reference/wiki.html）：三栏 左目录 236 / 中正文 ≤720 / 右「本页 + 引用」236，栏距 56 ── */
.lbw.has-rail .lbw-main{grid-template-columns:236px minmax(0,720px) 236px;column-gap:56px;}
.lbw.has-rail.is-tocoff:not(.is-narrow) .lbw-main{grid-template-columns:minmax(0,720px) 236px;justify-content:center;}
.lbw.is-mid.has-rail .lbw-main{grid-template-columns:200px minmax(0,1fr);column-gap:40px;}
.lbw.is-mid.has-rail .lbw-rail{grid-column:2;position:static;margin-top:48px;}
.lbw.has-side .lbw-rail{display:none;}
.lbw-rail{position:sticky;top:20px;align-self:start;display:flex;flex-direction:column;gap:32px;min-width:0;}
.lbw-rail[hidden]{display:none;}
.lbw.is-narrow .lbw-rail{position:static;margin-top:40px;}
.lbw-mhead{display:flex;align-items:center;gap:10px;margin:0 0 10px;}
.lbw-mhead .lbw-kick{font:700 11px/1 var(--lb-font-title);letter-spacing:.26em;text-transform:uppercase;color:var(--lb-ink);}
.lbw-mhead .lbw-zh{font:400 12px/1 var(--lbw-sans);color:var(--lb-muted);}
.lbw-mhead .lbw-rule{flex:1;height:1px;background:var(--lb-ink);}
.lbw .lbw-rhead{display:flex;justify-content:flex-start;align-items:baseline;gap:12px;width:100%;padding:5px 0;text-align:left;font:400 14px/1.5 var(--lbw-serif);color:var(--lb-muted);}
.lbw .lbw-rhead.is-l3{padding-left:30px;font-size:13px;}
.lbw .lbw-rhead .lbw-rn{flex:none;width:18px;font:italic 500 13px/1.5 var(--lb-font-num);font-variant-numeric:lining-nums;color:var(--lb-muted);}
.lbw .lbw-rhead:hover,.lbw .lbw-rhead.is-here,.lbw .lbw-rhead.is-top{color:var(--lb-ink);}
.lbw .lbw-rhead.is-here,.lbw .lbw-rhead.is-top{font-weight:600;}
.lbw .lbw-rsrc{display:flex;justify-content:flex-start;align-items:flex-start;gap:14px;width:100%;padding:6px 0;text-align:left;}
.lbw .lbw-rsrc.is-gone{opacity:.55;}
.lbw-rthumb{flex:none;width:56px;height:70px;border-radius:8px;overflow:hidden;background:var(--lb-soft);display:flex;align-items:flex-end;}
.lbw-rthumb img{width:100%;height:100%;object-fit:cover;display:block;}
.lbw-rthumb.is-text span{padding:6px;font:700 10px/1.25 var(--lbw-sans);color:var(--lb-ink);}
.lbw-rsrc-t{display:flex;flex-direction:column;gap:4px;min-width:0;}
.lbw-rsrc-k{display:flex;align-items:center;gap:6px;font:400 12px/1 var(--lbw-sans);color:var(--lb-muted);}
.lbw-rsrc-k .lbw-fnum{display:inline-grid;place-items:center;width:18px;height:18px;border:1px solid var(--lb-ink);border-radius:50%;font:italic 500 12px/1 var(--lb-font-num);font-variant-numeric:lining-nums;color:var(--lb-ink);}
.lbw-rsrc-n{font:600 14px/1.45 var(--lbw-serif);color:var(--lb-ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbw .lbw-rsrc:hover .lbw-rsrc-n{text-decoration:underline;text-underline-offset:3px;}
.lbw-rnote{margin:10px 0 0;font:400 12px/1.6 var(--lbw-sans);color:var(--lb-muted);}
/* 左栏：「目录 | 关系图」下划线分页 + ＋，下面一条搜索（只有一道墨线） */
.lbw-ltabs{display:flex;align-items:center;gap:22px;margin:0 0 14px;border-bottom:1px solid var(--lb-line);}
.lbw .lbw-ltab{padding:6px 0 9px;margin-bottom:-1px;border-bottom:2.5px solid transparent;font:400 15px/1.3 var(--lbw-serif);color:var(--lb-muted);}
.lbw .lbw-ltab.is-on{color:var(--lb-ink);font-weight:600;border-bottom-color:var(--lb-ink);}
.lbw .lbw-lnew{margin-left:auto;width:32px;height:32px;display:grid;place-items:center;color:var(--lb-ink);border-radius:999px;}
.lbw .lbw-lnew:hover{background:var(--lb-soft);}
.lbw-findw{gap:8px;height:36px;margin:0 0 18px;padding:0 12px;border:0;border-radius:999px;background:var(--lb-soft);color:var(--lb-muted);}
.lbw-findw .lbw-ico{width:15px;height:15px;flex:none;}
.lbw .lbw-find{font-size:14px;}
.lbw-tmap{border-bottom:0;}
.lbw .lbw-tmap .lbw-mpin{display:inline-flex;align-items:center;gap:6px;width:auto;margin-top:10px;font:400 12.5px/1 var(--lbw-sans);color:var(--lb-muted);}
/* 目录树：不要编号；当前页左边一个实心小圆点；篇数斜体靠右 */
.lbw-tpage.is-current::before{left:22px;top:50%;bottom:auto;width:6px;height:6px;margin-top:-3px;border-radius:50%;}
.lbw-tfold.is-current::before{display:none;}
/* TAGS 标签：目录底下一块，描边小胶囊 */
.lbw-ttags{display:block;margin-top:24px;padding-top:18px;}
.lbw-tagpills{display:flex;flex-wrap:wrap;gap:8px;}
.lbw .lbw-tagpills button{height:30px;padding:0 12px;border:1px solid var(--lb-line);border-radius:999px;font:400 13px/1 var(--lbw-sans);color:var(--lb-muted);text-decoration:none;}
.lbw .lbw-tagpills button:hover,.lbw .lbw-tagpills button.is-on{border-color:var(--lb-ink);color:var(--lb-ink);text-decoration:none;}
/* 数字一律齐线（Cormorant 默认旧式数字高低不齐；font 简写会把它重置掉，这里兜一次） */
.lbw *{font-variant-numeric:lining-nums;}
/* ── 1101 作者：Wiki 不要页头；右上角一小撮「浏览收藏 / 问收藏 / Wiki」+ 历史 + ···（打开一页时在右栏上面），其余几栏从顶上开始 ── */
.lbw-main{grid-template-rows:auto 1fr;padding-top:20px;}
.lbw-corner{grid-row:1;grid-column:2 / -1;justify-self:end;display:flex;align-items:center;gap:6px;margin:0 0 18px;white-space:nowrap;}
.lbw-main > .lbw-toc{grid-column:1;grid-row:1 / 3;}
.lbw-main > .lbw-center{grid-column:2;grid-row:2;}
.lbw.has-rail:not(.is-mid):not(.is-narrow) .lbw-corner{grid-column:3;}
.lbw.has-rail:not(.is-mid):not(.is-narrow) .lbw-main > .lbw-center{grid-row:1 / 3;}
.lbw.has-rail:not(.is-mid):not(.is-narrow) .lbw-main > .lbw-rail{grid-column:3;grid-row:2;}
.lbw.is-mid.has-rail .lbw-main > .lbw-rail{grid-column:2;grid-row:3;}
.lbw.is-tocoff:not(.is-narrow) .lbw-corner{grid-column:1 / -1;}
.lbw.is-tocoff:not(.is-narrow) .lbw-main > .lbw-center{grid-column:1;}
.lbw.is-tocoff.has-rail:not(.is-mid):not(.is-narrow) .lbw-corner,.lbw.is-tocoff.has-rail:not(.is-mid):not(.is-narrow) .lbw-main > .lbw-rail{grid-column:2;}
.lbw.is-narrow .lbw-corner{display:flex;justify-content:flex-end;}
.lbw .lbw-corner .lb-page-nav{background:transparent;padding:0;gap:2px;justify-self:auto;}
/* 按钮照 lb-page-lib 的 .lb-page-nav 原样（13px、9×16、当前页白底 + 0 1px 4px 浅阴影、字重 500）；只把字体定成无衬线（问收藏页当时继承的就是无衬线，Wiki 页默认是衬线） */
.lbw .lbw-corner .lb-page-nav button{font-family:var(--lb-font-title-base,serif),var(--lb-font-serif);}   /* 1101 作者：跳转钮和目录页 / 问收藏一个字体 */
.lbw .lbw-corner .lbw-jumps{gap:8px;}
.lbw .lbw-corner .lbw-jumps button{height:auto;padding:9px 16px;border-radius:9px;font-size:14px;line-height:1.2;background:var(--lb-surface)!important;color:var(--lb-ink);box-shadow:0 1px 4px #0000000c!important;font-weight:500;}
.lbw .lbw-corner .lbw-jumps button:hover{box-shadow:0 2px 8px #00000018!important;}
.lbw .lbw-corner .lbw-acts{margin-left:0;gap:0;}
.lbw .lbw-corner .lbw-hbtn{width:36px;height:36px;}
.lbw .lbw-corner .lbw-hbtn .lbw-ico{width:18px;height:18px;}
.lbw-sub{margin:-8px 0 16px 4px;font:400 12px/1.4 var(--lbw-sans);color:var(--lb-muted);}
.lbw-sub .lbw-num{font:inherit;color:inherit;}
`);

// ═════════════ 小工具 ═════════════
const pad2 = n => String(n).padStart(2, '0');
const norm = s => String(s || '').trim().toLowerCase();
const toDate = v => { if (!v) return null; const d = new Date(v); return isNaN(d) ? null : d; };
const fmtAt = v => { const d = toDate(v); return d ? `${d.getFullYear()}.${pad2(d.getMonth() + 1)}.${pad2(d.getDate())}` : ''; };
const mmdd = v => { const d = toDate(v); return d ? `${pad2(d.getMonth() + 1)}.${pad2(d.getDate())}` : ''; };
const fmtTime = v => { const d = toDate(v); return d ? `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}` : ''; };
const errText = e => String((e && e.message) || e || '未知原因');
const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
// 建元素：h(tag, {cls, text, attr, data, on}, ...子节点)；子节点可以是字符串 / 元素 / 数组 / null
function add(el, kids) {
  for (const k of [kids].flat(Infinity)) if (k != null && k !== false && k !== '') el.append(typeof k === 'object' ? k : String(k));
  return el;
}
function h(tag, p, ...kids) {
  const e = D.createElement(tag);
  if (p) {
    if (p.cls) e.className = p.cls;
    if (p.text != null) e.textContent = String(p.text);
    if (p.attr) for (const [k, v] of Object.entries(p.attr)) if (v != null && v !== false) e.setAttribute(k, v === true ? '' : String(v));
    if (p.data) for (const [k, v] of Object.entries(p.data)) if (v != null) e.dataset[k] = String(v);
    if (p.on) for (const [k, f] of Object.entries(p.on)) e.addEventListener(k, f);
  }
  return add(e, kids);
}
const btn = (p, ...kids) => { const b = h('button', { ...p, attr: { type: 'button', ...(p && p.attr) } }, ...kids); return b; };
const S = (tag, attrs, ...kids) => {
  const e = D.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null) continue;
    if (k === 'class' && e.classList) { for (const c of String(v).split(/\s+/)) if (c) e.classList.add(c); }
    else e.setAttribute(k, String(v));
  }
  return add(e, kids);
};
const sr = text => h('span', { cls: 'lb-visually-hidden', text });   // 给读屏的隐藏文字（不用 title / aria-label：Obsidian 会画成浮框）
const NUM = s => h('span', { cls: 'lbw-num', text: s });
// 文字里的数字包成斜体数字
function nums(str) { const out = []; let last = 0; const s = String(str ?? ''); for (const m of s.matchAll(/\d[\d.:/%,]*/g)) { if (m.index > last) out.push(s.slice(last, m.index)); out.push(NUM(m[0])); last = m.index + m[0].length; } if (last < s.length) out.push(s.slice(last)); return out; }
const kbd = t => h('span', { cls: 'lbw-kbd', text: t });
let uid = 0;
const nextId = pre => `lbw-${pre}-${++uid}`;
const ICONS = {
  home: [['rect', { x: 4, y: 4, width: 6.5, height: 6.5, rx: 1 }], ['rect', { x: 13.5, y: 4, width: 6.5, height: 6.5, rx: 1 }], ['rect', { x: 4, y: 13.5, width: 6.5, height: 6.5, rx: 1 }], ['rect', { x: 13.5, y: 13.5, width: 6.5, height: 6.5, rx: 1 }]],
  pin: [['path', { d: 'M9 3h6l-1 6 4 4H6l4-4z' }], ['path', { d: 'M12 13v8' }]],
  find: [['circle', { cx: 11, cy: 11, r: 6.5 }], ['path', { d: 'm20 20-4.2-4.2' }]],
  up: [['path', { d: 'm7 11 5-5 5 5' }], ['path', { d: 'm7 18 5-5 5 5' }]],
  down: [['path', { d: 'm7 6 5 5 5-5' }], ['path', { d: 'm7 13 5 5 5-5' }]],
  plus: [['path', { d: 'M12 5v14M5 12h14' }]],
  fold: [['path', { d: 'm6 9 6 6 6-6' }]],
  panel: [['rect', { x: 3.5, y: 4.5, width: 17, height: 15, rx: 2 }], ['path', { d: 'M9.5 4.5v15' }]],
  hist: [['path', { d: 'M3 3v5h5' }], ['path', { d: 'M3.05 13A9 9 0 1 0 6 5.3L3 8' }], ['path', { d: 'M12 7v5l3.5 2' }]],
  list: [['path', { d: 'M4 7h16M4 12h16M4 17h10' }]],
  expand: [['path', { d: 'M4 9V4h5' }], ['path', { d: 'M20 9V4h-5' }], ['path', { d: 'M4 15v5h5' }], ['path', { d: 'M20 15v5h-5' }]],
  // 1101 设计交接包：「AI 整理本页」前面的小星、页头「更多」的三个点
  spark: [['path', { d: 'M12 4v4M12 16v4M4 12h4M16 12h4M6.3 6.3l2.8 2.8M14.9 14.9l2.8 2.8M6.3 17.7l2.8-2.8M14.9 9.1l2.8-2.8' }]],
  more: [['circle', { cx: 5, cy: 12, r: 1.6, fill: 'currentColor', stroke: 'none' }], ['circle', { cx: 12, cy: 12, r: 1.6, fill: 'currentColor', stroke: 'none' }], ['circle', { cx: 19, cy: 12, r: 1.6, fill: 'currentColor', stroke: 'none' }]],
};
const icon = name => S('svg', { class: 'lbw-ico', viewBox: '0 0 24 24', 'aria-hidden': 'true' }, (ICONS[name] || []).map(([t, a]) => S(t, a)));

// SHA-1（和 personal_wiki.content_hash 同口径：CRLF / 单独的 CR → LF，UTF-8）；没有 crypto.subtle 时用下面的纯 JS 版
function sha1js(bytes) {
  const ml = bytes.length, len = ((ml + 9 + 63) >> 6) << 6;
  const buf = new Uint8Array(len); buf.set(bytes); buf[ml] = 0x80;
  const view = new DataView(buf.buffer);
  view.setUint32(len - 4, (ml * 8) >>> 0); view.setUint32(len - 8, Math.floor(ml * 8 / 4294967296));
  let h0 = 0x67452301, h1 = 0xEFCDAB89, h2 = 0x98BADCFE, h3 = 0x10325476, h4 = 0xC3D2E1F0;
  const w = new Uint32Array(80);
  for (let o = 0; o < len; o += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(o + i * 4);
    for (let i = 16; i < 80; i++) { const x = w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]; w[i] = (x << 1) | (x >>> 31); }
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i++) {
      const f = i < 20 ? (b & c) | (~b & d) : i < 40 ? b ^ c ^ d : i < 60 ? (b & c) | (b & d) | (c & d) : b ^ c ^ d;
      const k = i < 20 ? 0x5A827999 : i < 40 ? 0x6ED9EBA1 : i < 60 ? 0x8F1BBCDC : 0xCA62C1D6;
      const t = (((a << 5) | (a >>> 27)) + f + e + k + w[i]) >>> 0;
      e = d; d = c; c = ((b << 30) | (b >>> 2)) >>> 0; b = a; a = t;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map(x => x.toString(16).padStart(8, '0')).join('');
}
async function sha1hex(text) {
  const bytes = new TextEncoder().encode(String(text ?? '').replace(/\r\n?/g, '\n'));
  const c = typeof crypto !== 'undefined' ? crypto : null;
  if (c && c.subtle && typeof c.subtle.digest === 'function') {
    try { const out = await c.subtle.digest('SHA-1', bytes); return [...new Uint8Array(out)].map(b => b.toString(16).padStart(2, '0')).join(''); }
    catch (e) { console.debug('[lb] wiki sha1 退回纯 JS', e); }
  }
  return sha1js(bytes);
}
const contentHash = async text => (await sha1hex(text)).slice(0, 16);

// ═════════════ 页面文件：文件头 + 正文（和 personal_wiki.parse_page 同一套） ═════════════
const FIELD_ORDER = ['id', 'title', 'role', 'index_tag', 'order', 'tags', 'created', 'updated'];
const cleanTag = t => String(t ?? '').replace(/[\s,，#\[\]"]+/g, '').trim();
const RESERVED = /^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$/i;
const validId = id => /^[\p{L}\p{N}\p{M}_-]{1,64}$/u.test(id || '') && !RESERVED.test(id);
const unquote = s => s.replace(/^['"]+|['"]+$/g, '');
function scalar(v) {
  v = v.trim();
  if (v.startsWith('"') || v.startsWith('[')) {
    try { return JSON.parse(v); }
    catch (e) { if (v.startsWith('[')) return v.slice(1, -1).split(',').map(s => unquote(s.trim())).filter(Boolean); }   // 原型写的 [a, b]（不带引号）
  }
  return v;
}
function parsePage(text) {
  text = String(text).replace(/\r\n/g, '\n');
  const meta = {};
  let body = text;
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(text);
  if (m) {
    body = text.slice(m[0].length);
    const groups = [];
    for (const line of m[1].split('\n')) {
      if (groups.length && (!line.trim() || line[0] === ' ' || line[0] === '\t' || line.startsWith('- ') || line === '-')) groups[groups.length - 1].push(line);
      else if (line.trim()) groups.push([line]);
    }
    for (const g of groups) {
      while (g.length > 1 && !g[g.length - 1].trim()) g.pop();
      const mm = /^([\w-]+):\s*(.*)$/.exec(g[0]);
      if (!mm || !FIELD_ORDER.includes(mm[1])) continue;
      const items = g.slice(1).filter(x => /^\s*-/.test(x)).map(x => x.replace(/^\s*-\s?/, '').trim());
      if (!mm[2].trim() && items.length) meta[mm[1]] = items.filter(Boolean).map(x => (x.startsWith('"') ? scalar(x) : x.replace(/^'+|'+$/g, '')));
      else meta[mm[1]] = scalar(mm[2]);
    }
  }
  const asList = v => (typeof v === 'string' ? [v] : Array.isArray(v) ? v : []).filter(x => String(x).trim());
  const role = String(meta.role || 'page');
  return {
    id: String(meta.id || ''), title: String(meta.title || '').trim(), role: role === 'topic' ? 'topic' : 'page',
    index_tag: cleanTag(meta.index_tag), order: asList(meta.order).map(String), tags: asList(meta.tags).map(cleanTag).filter(Boolean),
    created: String(meta.created || ''), updated: String(meta.updated || ''), body: body.replace(/^\n+/, ''),
  };
}

// ═════════════ 索引（从正文派生，同原型 reindex / personal_wiki.derive） ═════════════
const CITE_RE = /\[([^\]\n]+)\]\(lwa:([\w-]+)\)/g;
const WL_RE = /\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/g;
const TAG_RE = /(?:^|(?<=[\s(（，。、；：·]))#([^\s#\[\]()（）,，。、;；:：!！?？"'<>*`·]+)/gm;
const stripCode = body => String(body || '').replace(/```[\s\S]*?```/g, m => m.replace(/[^\n]/g, ''));
const plain = s => String(s || '').replace(WL_RE, (_, t, a) => a || t).replace(CITE_RE, '$1').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*`]/g, '').trim();
function leadOf(p) {
  const blocks = stripCode(p.body).split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
  for (const b of blocks) if (!/^(#|>|[-*+]\s|\d+\.)/.test(b)) return plain(b.split('\n')[0]).slice(0, 80);
  for (const b of blocks) { const m = /^\s*([-*+]|\d+\.)\s+(\[[ xX]\]\s+)?(.*)$/.exec(b.split('\n')[0]); if (m) return plain(m[3]).slice(0, 80); }
  return '';
}
function derive(p) {
  const b = stripCode(p.body);
  p._cites = [...new Set([...b.matchAll(CITE_RE)].map(m => m[2]))];
  const inline = [...new Set([...b.matchAll(TAG_RE)].map(m => m[1]).filter(t => !/^\d+$/.test(t)))];
  p._allTags = [...new Set([...(p.tags || []), ...inline])];
  p._heads = []; p._tasks = [];
  b.split('\n').forEach((l, i) => {
    const hh = /^(#{1,4})\s+(.*)$/.exec(l); if (hh) p._heads.push({ level: hh[1].length, text: plain(hh[2]), line: i });
    const t = /^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$/.exec(l); if (t) p._tasks.push({ done: t[1] !== ' ', text: plain(t[2]), line: i });
  });
  p._lead = leadOf(p);
  p._chars = String(p.body || '').replace(/\s/g, '').length;
  return p;
}
const PAGES = new Map();
let IDX = { byTitle: new Map(), byTag: new Map(), catTags: new Set() };
function reindex() {
  const byTitle = new Map(), byTag = new Map(), catTags = new Set();
  for (const p of PAGES.values()) {
    if (!p._heads) derive(p);
    byTitle.set(norm(p.title), p);
    if (p.role === 'topic' && p.index_tag) catTags.add(p.index_tag);
    for (const t of p._allTags) { if (!byTag.has(t)) byTag.set(t, []); byTag.get(t).push(p); }
  }
  IDX = { byTitle, byTag, catTags };
}
const pageByTitle = t => IDX.byTitle.get(norm(t)) || null;
const byUpdated = (a, b) => String(b.updated || '').localeCompare(String(a.updated || ''));
// 文件夹编号按建立先后（created），改名 / 改内容不会让编号跳
const topics = () => [...PAGES.values()].filter(p => p.role === 'topic' && p.index_tag).sort((a, b) => cmpStr(a.created || '~', b.created || '~') || cmpStr(a.file || '', b.file || ''));
const folderOf = tag => topics().find(p => p.index_tag === tag) || null;
const foldersOf = p => p._allTags.filter(t => IDX.catTags.has(t)).map(folderOf).filter(Boolean);
const citedBy = id => { const k = citeKey(id); return [...PAGES.values()].filter(p => p._cites.some(c => citeKey(c) === k)); };
function pagesIn(t) {
  const list = (IDX.byTag.get(t.index_tag) || []).filter(p => p.role === 'page');
  const rank = id => { const k = (t.order || []).indexOf(id); return k < 0 ? 1e6 : k; };
  return list.sort((a, b) => rank(a.id) - rank(b.id) || cmpStr(a.created || '~', b.created || '~') || cmpStr(a.title, b.title));
}
const loosePages = () => [...PAGES.values()].filter(p => p.role === 'page' && !foldersOf(p).length).sort(byUpdated);
const savedOf = p => ({ title: p.title, tags: [...(p.tags || [])], body: p.body, order: [...(p.order || [])] });
const sameState = (a, b) => !!a && !!b && a.title === b.title && a.body === b.body && (a.tags || []).join('\n') === (b.tags || []).join('\n') && (a.order || []).join('\n') === (b.order || []).join('\n');

// ═════════════ 读盘（快，不起 Python） ═════════════
const wdir = () => LB.path(WDIR);
const isPageFile = f => /\.md$/i.test(f) && !f.slice(wdir().length + 1).includes('/');
async function listPages() {
  let listing;
  try { listing = await app.vault.adapter.list(wdir()); } catch (e) { return null; }   // 还没有 PersonalWiki/：空 Wiki
  return (listing?.files || []).filter(isPageFile).sort(cmpStr);
}
async function readDisk() {
  const files = await listPages();
  const out = new Map();
  for (const f of files || []) {
    let text;
    try { text = await app.vault.adapter.read(f); } catch (e) { console.debug('[lb] wiki 读不到', f, e); continue; }
    const name = f.slice(f.lastIndexOf('/') + 1);
    const p = parsePage(text);
    if (!validId(p.id) || out.has(p.id)) { p.id = 'pf-' + (await sha1hex(name)).slice(0, 10); p.adopted = false; }
    if (!p.title) p.title = name.replace(/\.md$/i, '');
    p.file = name; p.path = f; p.hash = await contentHash(text);
    out.set(p.id, p);
  }
  return out;
}
// 磁盘签名（文件名 + mtime:size）：Dataview 重跑 / 文件事件时先比它，没变就不读
async function diskSig() {
  const files = await listPages();
  if (!files) return 'none';
  const parts = [];
  for (const f of files) { let st = null; try { st = await app.vault.adapter.stat?.(f); } catch (e) { st = null; } parts.push(f + ':' + (st ? st.mtime + ':' + st.size : '?')); }
  return parts.join('|');
}
const DATA_FIELDS = ['id', 'title', 'role', 'index_tag', 'order', 'tags', 'created', 'updated', 'body', 'file', 'path', 'hash', 'adopted'];
function adoptDisk(cur, d) { for (const k of DATA_FIELDS) { if (k in d) cur[k] = d[k]; else delete cur[k]; } cur._saved = savedOf(d); cur._stale = false; derive(cur); }
// 磁盘 → 内存：hash 一样的不动（自己刚存的那份也是）；正在存 / 正在改（点开的那段、整页 Markdown 框）/ 正在恢复或重读的那页先不换——
// 用户手上的字是照旧 hash 那版改的，保存时 base_hash 还是旧的 → 后端回 CONFLICT，用户的字进草稿，不会拿新 hash 静悄悄盖掉别处的改动（10-29 审查 1）
const editingPage = p => !!p && ((p._ops || 0) > 0 || (ED && ED.p === p) || (UI.src && UI.view === 'page' && UI.id === p.id));
function mergeDisk(disk) {
  let changed = false, skipped = false;
  for (const [id, d] of disk) {
    const cur = PAGES.get(id);
    if (cur && cur.hash === d.hash) { if (cur.file !== d.file) { cur.file = d.file; cur.path = d.path; } continue; }
    if (editingPage(cur)) { cur._stale = true; skipped = true; continue; }
    if (cur) adoptDisk(cur, d); else { d._saved = savedOf(d); PAGES.set(id, derive(d)); }
    changed = true;
  }
  for (const [id, cur] of [...PAGES]) {
    if (disk.has(id)) continue;
    if (editingPage(cur)) { skipped = true; continue; }
    PAGES.delete(id); changed = true;
  }
  return { changed, skipped };
}
// 改完 / 关掉编辑框时：期间磁盘变过（_stale）而且这页空闲，就补一次重读（忙的话 settled 里补）
const refreshIfStale = p => { if (p && p._stale && !((p._ops || 0) > 0)) scheduleRefresh(50); };
let lastSig = null, refreshing = null;
async function refresh(force = false) {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const sig = await diskSig();
    if (!force && sig === lastSig) return false;
    const disk = await readDisk();
    const { changed, skipped } = mergeDisk(disk);
    lastSig = skipped ? null : sig;   // 有页这次没换（正在改）：签名不记，下次照样重读
    if (changed) { reindex(); afterRefresh(); }
    return changed;
  })();
  try { return await refreshing; } finally { refreshing = null; }
}
let refreshTimer = 0;
const scheduleRefresh = (ms = 500) => { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => { refresh().catch(e => console.debug('[lb] wiki refresh', e)); }, ms); };

// 收藏（引用 / @ 补全 / 标签页的 ARCHIVE 用）
let DATA = {}, ITEMS = [], ITEM_BY = new Map(), ITEM_SHORT = new Map();
// 收藏 id 带来源前缀（domain.item_id：xhs-… / bili-… …）；引用里写成短 id（从 MCP 搜索结果抄来的，不带前缀）也要认：
// 先按完整 id 找；找不到再找「来源前缀-短 id」唯一的那一篇（几个来源撞了同一个短 id 就不猜，当缺失）
// 来源前缀只认 link_brain/domain.py 的 PREFIX（xhs / bili）；那边加来源，这里跟着加一个（别的「abc-123」不是来源前缀，不拆）
const SOURCE_PREFIXES = ['xhs', 'bili'];
const ID_PREFIX = new RegExp('^(' + SOURCE_PREFIXES.join('|') + ')-(.+)$');
async function loadItems() {
  try { DATA = await LB.data.load(); } catch (e) { DATA = {}; }
  ITEMS = LB.schemaBlocks(DATA) ? [] : (Array.isArray(DATA.items) ? DATA.items : []);
  ITEM_BY = new Map(ITEMS.map(it => [it.id, it]));
  ITEM_SHORT = new Map();
  for (const it of ITEMS) { const m = ID_PREFIX.exec(String(it.id || '')); if (m) ITEM_SHORT.set(m[2], ITEM_SHORT.has(m[2]) ? null : it); }
}
const resolveItem = id => ITEM_BY.get(id) || (ITEM_BY.has(id) ? null : ITEM_SHORT.get(id)) || null;
// 比较「是不是同一篇收藏」一律用它：能找到的用收藏的完整 id，找不到的用原文
const citeKey = id => (resolveItem(id) || {}).id || id;
const citeKeys = p => new Set(p._cites.map(citeKey));
const itemType = it => (it.kind === 'video' ? '视频' : it.attachment && it.attachment !== 'none' ? '附件' : '图文');

// ═════════════ 界面状态（§5.3：路由 / 收起的文件夹存 sessionStorage；MAP 图钉存本库的 localStorage，重启后还在） ═════════════
const saved0 = LB.state.load();
const UI = { view: saved0.view || 'home', id: saved0.id || null, tag: saved0.tag || null, ovShut: !!saved0.ovShut,
  find: null, mapOpen: false, src: false, tagEdit: false, caret: null, hist: null, openCite: null, drag: null, drawer: false };
function loadPrefs() {
  let v = null;
  try { v = typeof app.loadLocalStorage === 'function' ? app.loadLocalStorage('lb-wiki-prefs') : null; } catch (e) { v = null; }
  if (typeof v === 'string') { try { v = JSON.parse(v); } catch (e) { v = null; } }
  const base = v && typeof v === 'object' ? v : (saved0.prefs || {});
  return { open: { ...(base.open || {}) }, mapPin: !!base.mapPin, tocOff: !!base.tocOff };
}
const PREFS = loadPrefs();
function saveUi() {
  LB.state.save({ view: UI.view, id: UI.id, tag: UI.tag, ovShut: UI.ovShut, prefs: PREFS });
  try { if (typeof app.saveLocalStorage === 'function') app.saveLocalStorage('lb-wiki-prefs', PREFS); } catch (e) { console.debug('[lb] wiki prefs', e); }
}
// 没保存上的改动：内存（同一次 Obsidian 会话里换页再回来还在）+ 本库 localStorage（重启也在）
const DRAFTS = (G.__lbWikiDrafts = G.__lbWikiDrafts || (() => { try { const v = typeof app.loadLocalStorage === 'function' ? app.loadLocalStorage('lb-wiki-drafts') : null; return v && typeof v === 'object' ? v : {}; } catch (e) { return {}; } })());
function persistDrafts() { try { if (typeof app.saveLocalStorage === 'function') app.saveLocalStorage('lb-wiki-drafts', DRAFTS); } catch (e) { console.debug('[lb] wiki drafts', e); } }

// ═════════════ 骨架 ═════════════
const mount = LB.mountHost('lbw-host');
const wrap = h('div', { cls: 'lbw' + (readOnly ? ' is-ro' : '') + (LB.mobile ? ' is-mobile' : '') });
mount.append(wrap);
try { LB.applyTheme(); } catch (e) { console.debug('[lb] wiki theme', e); }
const R = {};
// 1101 作者：Wiki 不要页头（COLLECTIONS 那一整条不要）——三页切换 + 历史 + ··· 放到右上角（打开一页时就在右栏「ON THIS PAGE」上面）；
// 切换照以前问收藏页的样子：没有外框，当前那页是白底小卡带一点阴影（.lb-page-nav），中英文同一种无衬线字
R.corner = h('div', { cls: 'lbw-corner' }, h('h2', { cls: 'lb-visually-hidden', text: '个人 Wiki' }));
// 1101 作者：只写要跳过去的那两页（不写 Wiki 自己），两颗都是 .lb-page-nav 当前页那种白底 + 浅阴影的小长方形
const nav = h('nav', { cls: 'lb-page-nav lbw-jumps' },
  btn({ text: '浏览收藏', on: { click: () => LB.openPage('catalog') } }),
  btn({ text: '问收藏', on: { click: () => LB.openPage('chat') } }));
const acts = h('div', { cls: 'lbw-acts' });
add(R.corner, [nav, acts]);
// 「全部 N 页 · 更新 …」：放左栏搜索框下面一行小字（renderToc 里挂）
R.sub = h('div', { cls: 'lbw-sub' });
if (!readOnly) {
  // 「AI 整理本页」：只在打开一页时出现，放在那一页的面包屑那一行右边（renderPage 里挂上去）；不要框（1101 作者）
  R.aiBtn = btn({ cls: 'lbw-hbtn is-ai', data: { ai: 'open' }, on: { click: () => openAiFromHead() } }, icon('spark'), h('span', { text: 'AI 整理本页' }));
  R.histBtn = btn({ cls: 'lbw-hbtn', data: { hist: '1' }, on: { click: () => toggleHistory() } }, icon('hist'), sr('这一页的历史版本'));
  acts.append(R.histBtn);
}
// 「···」只读时也在：目录首页 / 全部展开 / 全部收起 / 收起目录这些看的操作收在这里（1101），写盘的几项只读时不列
R.more = btn({ cls: 'lbw-hbtn is-more', on: { click: e => showMoreMenu(e, R.more) } }, icon('more'), sr('更多'));
acts.append(R.more);
if (readOnly) wrap.append(h('p', { cls: 'lbw-ro', text: LB.mobile ? '手机上只能看：Wiki 回电脑上改' : 'Link Brain Actions 插件没启用，Wiki 只能看' }));
const body = h('div', { cls: 'lbw-body' });
const main = h('div', { cls: 'lbw-main' });
R.toc = h('aside', { cls: 'lbw-toc' });
R.scrim = h('div', { cls: 'lbw-scrim', on: { click: () => setDrawer(false) } });
R.center = h('main', { cls: 'lbw-center' });
R.rail = h('aside', { cls: 'lbw-rail' }); R.rail.hidden = true;
add(main, [R.corner, R.toc, R.scrim, R.center, R.rail]);
R.side = h('aside', { cls: 'lbw-side' }); R.side.hidden = true;
add(body, [main, R.side]);
R.fab = btn({ cls: 'lbw-fab', on: { click: () => { if (wrap.classList.contains('is-narrow')) setDrawer(!UI.drawer); else setTocOff(false); } } }, icon('list'), '目录');
wrap.classList.toggle('is-tocoff', !!PREFS.tocOff);
R.layer = h('div', { cls: 'lbw-layer' });
add(wrap, [body, R.fab, R.layer]);

// 三种宽度（design.md §8）：≥1040 宽；680–1040 开着原文格；<680 手机（目录收成「目录」按钮 + 底部抽屉）
let lastW = 0;
// 10-31 作者：「Wiki 页一直在闪屏」——Dataview 每隔几秒重跑（库里有文件在变，比如 B 站同步在下），重跑那一下量到宽度 0，
// 以前当成「变宽了」：先切到宽屏布局再切回来，首页还整个重画（关系图从头动）。现在：量到 0 不算；档位切换留 24px 缓冲
// （滚动条出 / 没让宽度在分界线上来回跳也不翻）；首页只在档位真变了才重画
const BAND = (w, cur) => { const g = 24; const mid = cur.mid ? w < 1040 + g : w < 1040 - g; const narrow = cur.narrow ? w < 680 + g : w < 680 - g; return { mid, narrow }; };
function paintWidth(w) {
  w = Number(w) || wrap.clientWidth || 0;
  fitToc(); placeDock();
  if (w <= 0) return;
  const cur = { mid: wrap.classList.contains('is-mid'), narrow: wrap.classList.contains('is-narrow') };
  const b = lastW ? BAND(w, cur) : { mid: w < 1040, narrow: w < 680 };
  wrap.classList.toggle('is-mid', b.mid);
  wrap.classList.toggle('is-narrow', b.narrow);
  const changed = !!lastW && (b.mid !== cur.mid || b.narrow !== cur.narrow);
  lastW = w;
  if (changed && UI.view === 'home' && !ED) { clearTimeout(paintWidth.t); paintWidth.t = setTimeout(() => { if (UI.view === 'home' && !ED) renderCenter(); }, 150); }
}
if (typeof ResizeObserver === 'function') {
  try { const ro = new ResizeObserver(es => { for (const e of es) paintWidth(e.contentRect && e.contentRect.width); }); ro.observe(wrap); LB.onUnload(() => ro.disconnect()); }
  catch (e) { console.debug('[lb] wiki resize', e); }
}
function setDrawer(on) { UI.drawer = !!on; R.toc.classList.toggle('is-open', UI.drawer); }

// ═════════════ 路由 ═════════════
const current = () => (UI.view === 'page' ? PAGES.get(UI.id) || null : null);
function go(view, arg) {
  commitEditor(false); closePop(); flushSrc();
  const same = view === UI.view && (view === 'page' ? arg === UI.id : view === 'tag' ? arg === UI.tag : true);
  UI.view = view; UI.id = view === 'page' ? arg : null; UI.tag = view === 'tag' ? arg : null;
  if (!same) { UI.src = false; UI.tagEdit = false; UI.mapOpen = false; if (UI.ai && UI.ai.id !== arg) { UI.ai = null; renderDock(); } }
  saveUi(); setDrawer(false);
  if (UI.hist) { if (view === 'page') UI.hist = { id: arg, versions: null, sel: null, texts: {} }; else UI.hist = null; loadHistory(); }
  render();
  if (!same) { const sc = LB.scroller(); if (sc) sc.scrollTop = 0; }
}
const goPage = p => p && go('page', p.id);
const goTag = t => go('tag', t);
function render() {
  closePop();
  if (UI.view === 'page' && !PAGES.has(UI.id)) { UI.view = 'home'; UI.id = null; }
  wrap.classList.toggle('is-home', UI.view === 'home');
  if (R.histBtn) R.histBtn.hidden = UI.view !== 'page';   // 历史是一页的历史：首页 / 标签页不显示（10-31：以前点了只说「先打开一页」）
  renderCenter(); renderSub(); renderToc(); renderSide();
}
function renderKeepScroll() { const sc = LB.scroller(), top = sc ? sc.scrollTop : 0; render(); if (sc) sc.scrollTop = top; }
function afterRefresh() {
  renderSub(); renderToc();
  const srcFocused = UI.src && R.srcEd && D.activeElement === R.srcEd;
  if (!ED && !srcFocused && !(R.tagIn && D.activeElement === R.tagIn) && !(R.title && D.activeElement === R.title)) {
    const sc = LB.scroller(), top = sc ? sc.scrollTop : 0;
    if (UI.view === 'page' && !PAGES.has(UI.id)) { UI.view = 'home'; UI.id = null; }
    wrap.classList.toggle('is-home', UI.view === 'home');
    renderCenter(); if (sc) sc.scrollTop = top;
  }
  if (UI.hist && UI.hist.versions) loadHistory();
}
function renderSub() {
  const pages = [...PAGES.values()].filter(p => p.role === 'page');
  const last = pages.map(p => p.updated).filter(Boolean).sort().pop();
  const d = toDate(last);
  R.sub.textContent = '';
  add(R.sub, nums(`全部 ${pages.length} 页` + (d ? ` · 更新 ${pad2(d.getMonth() + 1)}/${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}` : '')));
}

// ═════════════ Markdown → 块（每块记住源码行号，点一段改一段靠它；原型原样） ═════════════
const isListLine = l => /^\s*([-*+]|\d+[.)])\s+/.test(l);
const indentOf = l => String(l).replace(/\t/g, '  ').length - String(l).replace(/\t/g, '  ').trimStart().length;
const isBlockStart = l => /^#{1,6}\s/.test(l) || /^```/.test(l) || /^>/.test(l) || isListLine(l) || /^(-{3,}|\*{3,})\s*$/.test(l);
function parseBlocks(src) {
  const L = String(src || '').split('\n'), out = [];
  let i = 0;
  while (i < L.length) {
    const l = L[i];
    if (!l.trim()) { i++; continue; }
    const s = i;
    if (/^```/.test(l)) { i++; while (i < L.length && !/^```\s*$/.test(L[i])) i++; i = Math.min(i + 1, L.length); out.push({ type: 'code', s, e: i }); continue; }
    if (/^#{1,6}\s/.test(l)) { out.push({ type: 'h', s, e: ++i }); continue; }
    if (/^(-{3,}|\*{3,})\s*$/.test(l)) { out.push({ type: 'hr', s, e: ++i }); continue; }
    if (/^>/.test(l)) { while (i < L.length && /^>/.test(L[i])) i++; out.push({ type: 'quote', s, e: i }); continue; }
    // 10-31：列表按条拆块（点一条只改这一条）；一条 = 这行 + 下面缩进更深的行（子项 / 续行）
    if (isListLine(l)) { const ind = indentOf(l); i++; while (i < L.length && L[i].trim() && indentOf(L[i]) > ind) i++; out.push({ type: 'li', s, e: i }); continue; }
    while (i < L.length && L[i].trim() && !(i > s && isBlockStart(L[i]))) i++;
    out.push({ type: 'p', s, e: i });
  }
  return { lines: L, blocks: out };
}
// 行内：按最早出现的写法逐段切（同原型 inline 的优先级），直接建 DOM（不拼 HTML）
const INLINE = [
  ['code', /`([^`]+)`/], ['img', /!\[([^\]]*)\]\(([^)\s]+)\)/], ['cite', /\[([^\]\n]+)\]\(lwa:([\w-]+)\)/],
  ['wl', /\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/], ['link', /\[([^\]\n]+)\]\(([^)\s]+)\)/],
  ['url', /(^|[^\w/"=])(https?:\/\/[^\s<]+)/], ['bold', /\*\*([^*]+)\*\*/], ['em', /(^|[^*])\*([^*\n]+)\*/],
  ['tag', /(^|[\s(（，。、；：·])#([^\s#\[\]()（）,，。、;；:：!！?？"'<>*`·]+)/],
];
const PRE_GROUP = { url: 1, em: 1, tag: 1 };
let CITE_NO = new Map();
const safeHref = u => (/^https?:\/\//i.test(u) ? u : '#');
function imgSrc(u) {
  if (/^(https?:|data:image\/)/i.test(u)) return u;
  try { return String(app.vault.adapter.getResourcePath(LB.path(WDIR + '/' + u.replace(/^\.?\//, '')))); } catch (e) { return ''; }
}
function extLink(text, href) {
  const a = h('a', { cls: 'lbw-ext', attr: { href: safeHref(href), target: '_blank', rel: 'noopener' } }, text, h('span', { cls: 'lbw-m', text: '↗' }));
  a.addEventListener('click', e => e.stopPropagation());
  return a;
}
function citeEl(text, id) {
  const it = resolveItem(id);
  const a = h('a', { cls: 'lbw-cite' + (it ? '' : ' is-missing') + (it && UI.openCite === it.id ? ' is-open' : ''), attr: { href: '#' }, data: { item: id } }, text,
    h('span', { cls: 'lbw-ref', text: it ? String(CITE_NO.get(it.id) || '') : '缺' }));
  a.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); openCite(id); });
  return a;
}
function inl(src, parent) {
  let s = String(src ?? '');
  while (s) {
    let best = null;
    for (const [k, re] of INLINE) {
      const m = re.exec(s); if (!m) continue;
      const pre = PRE_GROUP[k] ? m[1] : '';
      const at = m.index + pre.length;
      if (!best || at < best.at) best = { k, m, at };
    }
    if (!best) { parent.append(s); break; }
    const { k, m, at } = best;
    if (at > 0) parent.append(s.slice(0, at));
    s = s.slice(m.index + m[0].length);
    if (k === 'code') parent.append(h('code', { text: m[1] }));
    else if (k === 'img') { const src2 = imgSrc(m[2]); parent.append(src2 ? h('img', { attr: { alt: m[1], src: src2, loading: 'lazy' } }) : m[0]); }
    else if (k === 'cite') parent.append(citeEl(m[1], m[2]));
    else if (k === 'wl') {
      const p = pageByTitle(m[1]);
      if (p) { const a = h('a', { cls: 'lbw-pl', attr: { href: '#' }, text: m[2] || m[1] }); a.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); goPage(p); }); parent.append(a); }
      else parent.append(m[2] || m[1]);
    }
    else if (k === 'link') parent.append(extLink(m[1], m[2]));
    else if (k === 'url') parent.append(extLink(m[2], m[2]));
    else if (k === 'bold') parent.append(inl(m[1], h('strong')));
    else if (k === 'em') parent.append(inl(m[2], h('em')));
    else if (k === 'tag') {
      if (/^\d+$/.test(m[2])) parent.append('#' + m[2]);
      else { const t = m[2]; const a = h('a', { cls: 'lbw-htag', attr: { href: '#' }, data: { tag: t }, text: '#' + t }); a.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); goTag(t); }); parent.append(a); }
    }
  }
  return parent;
}
function renderList(p, lines, s0) {
  const items = [];
  lines.forEach((l, k) => {
    const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(l);
    if (m) items.push({ ind: m[1].replace(/\t/g, '  ').length, ord: /\d/.test(m[2]), text: m[3], line: s0 + k });
    else if (items.length) items[items.length - 1].text += ' ' + l.trim();
  });
  const roots = [], stack = [];
  for (const it of items) {
    while (stack.length && it.ind < stack[stack.length - 1].ind) stack.pop();
    let top = stack[stack.length - 1];
    if (!top || it.ind > top.ind) {
      const list = h(it.ord ? 'ol' : 'ul');
      if (it.ord) { const n = parseInt(/\d+/.exec(lines[it.line - s0])?.[0] || '1', 10); if (n > 1) list.setAttribute('start', String(n)); }
      if (top && top.li) top.li.append(list); else roots.push(list);
      stack.push(top = { ind: it.ind, list, li: null });
    }
    const t = /^\[( |x|X)\]\s+(.*)$/.exec(it.text);
    let li;
    if (t) {
      const done = t[1] !== ' ', lid = nextId('tk');
      const cb = h('input', { attr: { type: 'checkbox', 'aria-labelledby': lid }, data: { line: it.line } });
      cb.checked = done; cb.disabled = readOnly || busyPage(p);
      cb.addEventListener('click', e => { e.stopPropagation(); if (readOnly || cb.disabled) { e.preventDefault(); return; } toggleTask(p, it.line); });
      li = h('li', { cls: 'lbw-task' + (done ? ' is-done' : '') }, cb, inl(t[2], h('span', { attr: { id: lid } })));
    } else li = inl(it.text, h('li'));
    top.list.append(li); top.li = li;
  }
  return roots;
}
// ```pages 自动列表（folder: / tag:，渲染时现算，不写回正文）
function renderQuery(src, self) {
  const q = {};
  for (const l of src.split('\n')) { const m = /^(\w+):\s*(.*)$/.exec(l.trim()); if (m) q[m[1]] = m[2].trim(); }
  const tags = (q.tag || '').split(/[,，\s]+/).filter(Boolean);
  const fTag = q.folder || (!tags.length && self.role === 'topic' ? self.index_tag : '');
  const f = fTag ? folderOf(fTag) : null;
  const list = f ? pagesIn(f).filter(p => p !== self)
    : [...PAGES.values()].filter(p => p !== self && p.role === 'page' && tags.every(t => p._allTags.includes(t))).sort(byUpdated);
  const what = f ? (f === self ? '本文件夹 · 按目录里拖好的顺序' : `「${f.title}」 · 按目录里拖好的顺序`) : `${tags.map(t => '#' + t).join(' ')} · 最近改的在前`;
  return h('div', { cls: 'lbw-plist' },
    h('div', { cls: 'lbw-plist-h' }, h('span', { cls: 'lbw-kick', text: 'PAGES' }), h('span', { cls: 'lbw-cap', text: what }), NUM(String(list.length))),
    list.length ? list.map((p, i) => prow(p, i)) : h('p', { cls: 'lbw-rnone', text: '还没有' }));
}
function renderBlock(b, lines, self) {
  const src = lines.slice(b.s, b.e);
  switch (b.type) {
    case 'h': {
      const m = /^(#{1,6})\s+(.*)$/.exec(src[0]); const n = Math.min(m[1].length, 4);
      const k = (self._heads || []).findIndex(x => x.line === b.s);
      return h('h' + n, { data: { hline: b.s } }, k >= 0 ? h('span', { cls: 'lbw-num lbw-hn', text: pad2(k + 1) }) : null, inl(m[2], h('span')));
    }
    case 'hr': return h('hr');
    case 'quote': { const q = h('blockquote'); src.forEach((l, k) => { if (k) q.append(h('br')); inl(l.replace(/^>\s?/, ''), q); }); return q; }
    case 'li': return renderList(self, src, b.s);
    case 'code': {
      const lang = src[0].replace(/^```/, '').trim();
      const inner = src.slice(1, /^```\s*$/.test(src[src.length - 1]) && src.length > 1 ? -1 : undefined).join('\n');
      return lang === 'pages' ? renderQuery(inner, self) : h('pre', null, h('code', { text: inner }));
    }
    default: { const pEl = h('p'); src.forEach((l, k) => { if (k) pEl.append(h('br')); inl(l, pEl); }); return pEl; }
  }
}

// ═════════════ 目录（浮动：工具行 · Ctrl+F · MAP · 编号文件夹 → 页面 → 当前页小标题 · 标签） ═════════════
function renderToc() {
  const tocEl = R.toc;
  const keepFind = R.findIn && D.activeElement === R.findIn;
  tocEl.textContent = '';
  tocEl.append(h('h2', { cls: 'lb-visually-hidden', text: 'Wiki 目录' }));
  // 1101 设计交接包 §4「Wiki」：左栏顶上只留「目录 | 关系图」（下划线分页）+ 新建 + 一条搜索；全部展开 / 全部收起 / 目录首页 / 收起目录收进页头「···」
  const mapTab = PREFS.leftTab === 'map';
  const tab = (key, text) => btn({ cls: 'lbw-ltab' + ((key === 'map') === mapTab ? ' is-on' : ''), data: { ltab: key }, attr: { 'aria-pressed': String((key === 'map') === mapTab) }, text,
    on: { click: () => { PREFS.leftTab = key; saveUi(); renderToc(); } } });
  tocEl.append(h('div', { cls: 'lbw-ltabs' }, tab('tree', '目录'), tab('map', '关系图'),
    readOnly ? null : btn({ cls: 'lbw-lnew', on: { click: () => newPageModal() } }, icon('plus'), sr('新页面'))));
  const fid = nextId('find');
  const nPages = [...PAGES.values()].filter(x => x.role === 'page').length;
  R.findIn = h('input', { cls: 'lbw-find', attr: { id: fid, placeholder: `搜索 ${nPages} 页`, autocomplete: 'off', spellcheck: 'false' } });
  R.findIn.value = UI.find || '';
  R.findIn.addEventListener('input', () => { UI.find = R.findIn.value ? R.findIn.value : null; renderTree(); });
  R.findIn.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); toggleFind(false); }
    else if (e.key === 'Enter') { e.preventDefault(); const b = R.tree && (R.tree.querySelector('.lbw-tpage[data-page]') || R.tree.querySelector('[data-page]')); const p = b && PAGES.get(b.dataset.page); if (p) openFromFind(p); }
  });
  tocEl.append(h('label', { cls: 'lbw-findw' }, icon('find'), h('span', { cls: 'lb-visually-hidden', text: '搜标题和正文' }), R.findIn), R.sub);
  const cur = current();
  if (R.miniGraph) { R.miniGraph.destroy(); R.miniGraph = null; }   // 换页 / 重画：旧图停掉
  if (mapTab) {
    tocEl.append(h('div', { cls: 'lbw-tmap' }, tocGraph(cur),
      btn({ cls: 'lbw-mpin', data: { global: '1' }, on: { click: () => openGlobalGraph() } }, icon('expand'), h('span', { text: '打开全局图' }))));
    R.tree = null;
    return;
  }
  R.tree = h('div', { cls: 'lbw-tree' });
  tocEl.append(R.tree);
  renderTree();
  if (keepFind && R.findIn) { R.findIn.focus(); try { R.findIn.setSelectionRange(R.findIn.value.length, R.findIn.value.length); } catch (e) { console.debug(e); } }
}
function markText(s, q) {
  if (!q) return [s];
  const out = []; const low = s.toLowerCase(); let i = 0, j;
  while ((j = low.indexOf(q, i)) >= 0) { if (j > i) out.push(s.slice(i, j)); out.push(h('mark', { text: s.slice(j, j + q.length) })); i = j + q.length; }
  if (i < s.length) out.push(s.slice(i));
  return out;
}
// 文件夹展开：用户手动开 / 关过的照用户的（PREFS.open）；没动过的 = 只展开当前页所在的那个（10-31：以前全摊开，21 页就比一屏长）
const looseId = '__loose';
function folderOpen(id) {
  if (PREFS.open && id in PREFS.open) return !!PREFS.open[id];
  const c = current();
  if (!c) return false;
  if (id === looseId) return c.role === 'page' && !foldersOf(c).length;
  const t = PAGES.get(id);
  return !!t && (c === t || foldersOf(c).includes(t));
}
function setFolderOpen(id, on) { PREFS.open = { ...(PREFS.open || {}), [id]: !!on }; saveUi(); renderTree(); }
// 搜：标题 + 正文都搜（10-31：以前只搜标题，搜不到还让去问收藏，可问收藏不读 Wiki）
function bodyHit(p, q) {
  if (!q) return '';
  const plain = String(p.body || '').replace(/\]\(lwa:[\w-]+\)/g, ']').replace(/[#*`>\[\]]/g, '');
  const k = plain.toLowerCase().indexOf(q);
  if (k < 0) return '';
  const a = Math.max(0, k - 14), b = Math.min(plain.length, k + q.length + 30);
  return (a ? '…' : '') + plain.slice(a, b).replace(/\s+/g, ' ') + (b < plain.length ? '…' : '');
}
function renderTree() {
  const tree = R.tree; if (!tree) return;
  tree.textContent = '';
  const cur = current();
  const q = UI.find == null ? '' : norm(UI.find);
  const hitTitle = p => !q || norm(p.title).includes(q);
  const snip = new Map();
  const hit = p => { if (hitTitle(p)) return true; const s = bodyHit(p, q); if (s) snip.set(p.id, s); return !!s; };
  const pageRow = (p, fid) => {
    const row = btn({ cls: 'lbw-trow lbw-tpage' + (cur === p ? ' is-current' : ''), attr: cur === p ? { 'aria-current': 'page' } : null, data: { page: p.id, fid: fid || null }, on: { click: () => openFromFind(p) } },
      markText(p.title, q), snip.get(p.id) ? h('small', { cls: 'lbw-tsnip' }, markText(snip.get(p.id), q)) : null);
    if (!q && !readOnly) { bindDrag(row, p.id, fid); bindDrop(row, { pid: p.id, fid }); }
    // 1101：当前页的小标题挪到右栏「本页」，目录里只列页面
    return [row];
  };
  let any = 0;
  topics().forEach((t, k) => {
    const list = pagesIn(t).filter(hit);
    if (q && !list.length && !hitTitle(t)) return;
    any += list.length + (hitTitle(t) && q ? 1 : 0);
    const open = q ? true : folderOpen(t.id);
    const tw = add(h('span', { cls: 'lbw-tw' }), icon('fold'));
    tw.addEventListener('click', e => { e.stopPropagation(); setFolderOpen(t.id, !open); });
    const row = btn({ cls: 'lbw-trow lbw-tfold' + (open ? ' is-open' : '') + (cur === t ? ' is-current' : ''), attr: cur === t ? { 'aria-current': 'page' } : null, data: { page: t.id }, on: { click: () => goPage(t) } },
      tw, h('span', { cls: 'lbw-nm' }, markText(t.title, q)), h('span', { cls: 'lbw-c lbw-num', text: String(pagesIn(t).length) }));
    if (!q && !readOnly) bindDrop(row, { fid: t.id, into: true });
    tree.append(h('div', { cls: 'lbw-tgroup' }, row, open ? list.map(p => pageRow(p, t.id)) : null));
  });
  const loose = loosePages().filter(hit);
  if (loose.length || !q) {   // 没有未归类的页也留着这一行：拖页到这里 = 拿出文件夹
    any += loose.length;
    const open = q ? true : folderOpen(looseId);
    const ltw = add(h('span', { cls: 'lbw-tw' }), icon('fold'));
    ltw.addEventListener('click', e => { e.stopPropagation(); setFolderOpen(looseId, !open); });
    const row = btn({ cls: 'lbw-trow lbw-tfold' + (open ? ' is-open' : ''), data: { fold: looseId }, on: { click: () => setFolderOpen(looseId, !open) } },
      ltw, h('span', { cls: 'lbw-nm', text: '未归类' }), h('span', { cls: 'lbw-c lbw-num', text: String(loose.length) }));
    if (!q && !readOnly) bindDrop(row, { fid: null, into: true });
    tree.append(h('div', { cls: 'lbw-tgroup' }, row, open ? loose.map(p => pageRow(p, null)) : null));
  }
  if (q && !any) tree.append(h('p', { cls: 'lbw-tnone', text: `标题和正文里都没有「${UI.find}」` }));
  else if (q) tree.append(h('p', { cls: 'lbw-tnone' }, kbd('Enter'), ' 打开第一页'));
  if (!q) {
    const tags = [...IDX.byTag.entries()].filter(([t]) => !IDX.catTags.has(t)).sort((a, b) => b[1].length - a[1].length);
    // 1101：目录底下一块「TAGS 标签」，标签是描边小胶囊
    if (tags.length) tree.append(h('div', { cls: 'lbw-ttags' }, h('div', { cls: 'lbw-mhead' }, h('span', { cls: 'lbw-kick', text: 'TAGS' }), h('span', { cls: 'lbw-zh', text: '标签' })),
      h('div', { cls: 'lbw-tagpills' }, tags.map(([t]) => btn({ cls: UI.view === 'tag' && UI.tag === t ? 'is-on' : '', data: { tag: t }, text: '#' + t, on: { click: () => goTag(t) } })))));
  }
  if (!PAGES.size) tree.append(h('p', { cls: 'lbw-tnone', text: readOnly ? '还没有页面' : '还没有页面：点上面的 ＋ 新建' }));
  spyHeads();
  revealCurrent();
}
// 当前页那一行滚进目录可见范围（只动目录自己的 scrollTop，不带着外层一起滚）
function revealCurrent() {
  const run = () => {
    const box = R.toc, row = R.tree && R.tree.querySelector('.lbw-tpage.is-current, .lbw-tfold.is-current');
    if (!box || !row || box.scrollHeight <= box.clientHeight + 2) return;
    const br = box.getBoundingClientRect(), rr = row.getBoundingClientRect();
    if (rr.top < br.top + 40 || rr.bottom > br.bottom - 40) box.scrollTop += rr.top - br.top - box.clientHeight / 3;
  };
  if (WIN && typeof WIN.requestAnimationFrame === 'function') WIN.requestAnimationFrame(run); else run();
}
// 目录跟着读到哪：视口顶下面一点之上的最后一个小标题，在目录里加粗 + 左边一道线
function spyHeads() {
  if (!R.rail || UI.view !== 'page') return;
  const sc = LB.scroller(); if (!sc) return;
  const top = sc.getBoundingClientRect().top + 96;
  let here = null;
  for (const el of R.center.querySelectorAll('[data-hline]')) { if (el.getBoundingClientRect().top <= top) here = el.dataset.hline; else break; }
  for (const r of R.rail.querySelectorAll('.lbw-rhead')) r.classList.toggle('is-here', here != null && r.dataset.toc === here);
}
// ═════════════ 右栏（1101 设计交接包 §4：本页的小节大纲 + 这页引用的收藏；只在打开一页时有） ═════════════
function renderRail() {
  const rail = R.rail; if (!rail) return;
  rail.textContent = '';
  const cp = UI.view === 'page' ? current() : null, p = cp && cp.role === 'page' ? cp : null;
  rail.hidden = !p;
  wrap.classList.toggle('has-rail', !!p);
  if (!p) return;
  const mhead = (en, zh) => h('div', { cls: 'lbw-mhead' }, h('span', { cls: 'lbw-kick', text: en }), h('span', { cls: 'lbw-zh', text: zh }), h('span', { cls: 'lbw-rule' }));
  const heads = p._heads.filter(x => x.level <= 3);
  rail.append(h('section', { cls: 'lbw-rsec' }, mhead('ON THIS PAGE', '本页'),
    btn({ cls: 'lbw-rhead is-top', on: { click: () => { const sc = LB.scroller(); if (sc) sc.scrollTop = 0; } } }, h('span', { cls: 'lbw-rn', text: '—' }), h('span', { text: '摘要' })),
    heads.map((x, k) => btn({ cls: 'lbw-rhead is-l' + x.level, data: { toc: x.line }, on: { click: () => scrollToHead(x.line) } },
      h('span', { cls: 'lbw-rn lbw-num', text: x.level === 2 ? pad2(heads.filter((y, j) => j <= k && y.level === 2).length) : '' }), h('span', { text: x.text })))));
  const keys = [...new Set(p._cites.map(citeKey))];
  const rows = keys.map((k, i) => {
    const id = p._cites.find(c => citeKey(c) === k), it = resolveItem(id);
    const title = it ? it.title : '（找不到这篇收藏）';
    let src = '';
    if (it && it.cover) { try { src = String(app.vault.adapter.getResourcePath(LB.path(it.cover)) || ''); } catch (e) { src = ''; } }
    const thumb = h('span', { cls: 'lbw-rthumb' + (src ? '' : ' is-text') }, src ? h('img', { attr: { src, alt: '', loading: 'lazy' } }) : h('span', { text: String(title).slice(0, 8) }));
    return btn({ cls: 'lbw-rsrc' + (it ? '' : ' is-gone'), data: { cite: k }, on: { click: () => openCite(id) } }, thumb,
      h('span', { cls: 'lbw-rsrc-t' }, h('span', { cls: 'lbw-rsrc-k' }, h('span', { cls: 'lbw-fnum', text: String(i + 1) }), it ? (/^bili|^bv/i.test(it.id) ? 'B 站' : '小红书') : ''), h('span', { cls: 'lbw-rsrc-n', text: title })));
  });
  rail.append(h('section', { cls: 'lbw-rsec' }, mhead('SOURCES', '引用'), rows.length ? rows : h('p', { cls: 'lbw-rnote', text: '这页还没有引用收藏。' }),
    readOnly ? null : h('p', { cls: 'lbw-rnote', text: '在正文里打 @ 可以再引用一篇收藏。' })));
  spyHeads();
}
// 目录吸住（10-31 晚，作者：「目录往下拉，目录没有固定住」）：先靠 CSS sticky；用户的 Obsidian 里某层祖先让 sticky 失效时，
// 量一下目录顶边是不是已经滚出阅读区，是的话用 translateY 把它拉回来（不超过正文那一栏的底）
function pinToc() {
  const t = R.toc; if (!t) return;
  t.style.transform = '';
  if (wrap.classList.contains('is-narrow') || PREFS.tocOff) return;
  const sc = LB.scroller(); if (!sc) return;
  const top = sc.getBoundingClientRect().top + 12, tr = t.getBoundingClientRect(), mr = main.getBoundingClientRect();
  if (tr.top >= top - 1) return;
  const shift = Math.min(top - tr.top, Math.max(0, mr.bottom - tr.bottom));
  if (shift > 0) t.style.transform = `translateY(${Math.round(shift)}px)`;
}
// 目录的高度跟着 Obsidian 的阅读区，不跟着整个窗口（100vh 会把目录底部压到屏幕外）
function fitToc() { const sc = LB.scroller(); if (sc && sc.clientHeight > 200) R.toc.style.maxHeight = (sc.clientHeight - 40) + 'px'; }
function openFromFind(p) {
  const q = UI.find == null ? '' : norm(UI.find);
  if (UI.find != null) UI.find = null;
  goPage(p);
  if (q && !norm(p.title).includes(q)) {   // 正文里搜到的：滚到那一段，闪一下
    const blk = [...R.center.querySelectorAll('.lbw-blk')].find(b => norm(b.textContent).includes(q));
    if (blk) { try { blk.scrollIntoView({ block: 'center' }); } catch (e) { console.debug(e); } blk.classList.add('is-flash'); setTimeout(() => blk.classList.remove('is-flash'), 1600); }
  }
}
function toggleFind(force) {
  const on = force ?? UI.find == null;
  UI.find = on ? (UI.find ?? '') : null;
  if (on) { setTocOff(false); setDrawer(true); if (PREFS.leftTab === 'map') { PREFS.leftTab = 'tree'; saveUi(); } }
  renderToc();
  if (on && R.findIn) { R.findIn.focus(); R.findIn.select?.(); }
}
// 整栏收起 / 打开目录（记住）；窄屏还是底部抽屉
function setTocOff(off) {
  off = !!off;
  if (!!PREFS.tocOff === off) return;
  PREFS.tocOff = off; saveUi();
  wrap.classList.toggle('is-tocoff', off);
  if (!off) { renderToc(); fitToc(); }
  if (UI.view === 'home' && !ED) renderCenter();
}
function scrollToHead(line) {
  const el = R.center.querySelector(`[data-hline="${line}"]`);
  if (el) { try { el.scrollIntoView({ block: 'start', behavior: 'smooth' }); } catch (e) { el.scrollIntoView(); } }
  setDrawer(false);
}
// 目录里拖页：同一个文件夹里 = 排顺序；拖到别的文件夹的页上 / 文件夹名上 = 挪进那个文件夹；拖到「未归类」= 拿出文件夹
// （10-31：以前只能同文件夹内排，拖到当前页的小标题或别处就没反应；落点加大、插入线加粗）
function clearDrop() { for (const n of R.toc.querySelectorAll('.is-drop-before, .is-drop-after, .is-drop-in')) n.classList.remove('is-drop-before', 'is-drop-after', 'is-drop-in'); }
function bindDrag(row, pid, fid) {
  row.setAttribute('draggable', 'true');
  row.addEventListener('dragstart', ev => {
    UI.drag = { pid, fid: fid || null }; row.classList.add('is-dragging');
    try { if (ev.dataTransfer) { ev.dataTransfer.effectAllowed = 'move'; ev.dataTransfer.setData('text/plain', pid); } } catch (e) { console.debug(e); }
  });
  row.addEventListener('dragend', () => { UI.drag = null; row.classList.remove('is-dragging'); clearDrop(); });
}
function bindDrop(row, { pid = null, fid = null, into = false, after = false }) {
  row.addEventListener('dragover', ev => {
    const d = UI.drag; if (!d || (pid && d.pid === pid && d.fid === (fid || null))) return;
    ev.preventDefault(); ev.stopPropagation();
    clearDrop();
    if (into) { row.classList.add('is-drop-in'); return; }
    const b = row.getBoundingClientRect();
    row.classList.add(!after && ev.clientY < b.top + b.height / 2 ? 'is-drop-before' : 'is-drop-after');
  });
  row.addEventListener('drop', ev => {
    const d = UI.drag; UI.drag = null;
    const before = row.classList.contains('is-drop-before');
    clearDrop();
    if (!d) return;
    ev.preventDefault(); ev.stopPropagation();
    movePage(d.pid, d.fid, fid || null, into ? null : pid, before);
  });
}
function movePage(pid, fromFid, toFid, targetId, before) {
  const p = PAGES.get(pid); if (!p || readOnly) return;
  if (fromFid === toFid) { if (toFid) moveInFolder(toFid, pid, targetId, before); return; }   // 未归类里按修改时间排，不用排
  const from = fromFid ? PAGES.get(fromFid) : null, to = toFid ? PAGES.get(toFid) : null;
  if (busyPage(p) || (to && busyPage(to))) { LB.say('这一页正在恢复 / 删除，好了再拖', { kind: 'warn' }); renderToc(); return; }
  let tags = p.tags.filter(t => !from || t !== from.index_tag);
  if (!to) tags = tags.filter(t => !IDX.catTags.has(t));   // 拖到未归类 = 拿出所有文件夹
  if (to && !tags.includes(to.index_tag)) tags = [...tags, to.index_tag];
  mutate(p, n => { n.tags = tags; }, { note: to ? `挪到「${to.title}」` : '拿出文件夹' });
  if (to) moveInFolder(to.id, pid, targetId, before, { quiet: true });
  if (from && foldersOf(p).includes(from)) LB.say(`《${p.title}》正文里写了 #${from.index_tag}，所以还在「${from.title}」里`, { kind: 'warn' });
  else LB.say(to ? `《${p.title}》挪到了「${to.title}」` : `《${p.title}》放回了未归类`, { kind: 'ok' });
  if (to && !folderOpen(to.id)) PREFS.open = { ...(PREFS.open || {}), [to.id]: true };
  renderToc();
  if (!ED && (current() === p || current() === from || current() === to)) renderKeepScroll();
}
function moveInFolder(fid, pid, targetId, before, { quiet = false } = {}) {
  const t = PAGES.get(fid); if (!t || readOnly) return;
  const ids = pagesIn(t).map(p => p.id).filter(id => id !== pid);
  let at = targetId ? ids.indexOf(targetId) : -1; if (at < 0) at = ids.length; else if (!before) at++;
  ids.splice(at, 0, pid);
  if (busyPage(t)) { LB.say('这个文件夹正在恢复，好了再拖', { kind: 'warn' }); renderToc(); return; }
  mutate(t, n => { n.order = ids; }, { note: '调整顺序' });
  if (quiet) return;
  renderToc(); if (UI.view === 'page' && UI.id === fid && !ED) renderCenter();
}

// ═════════════ 关系图（10-29 作者：照 Quartz 的 graph 组件——力导向、会动、可拖、可缩放、悬停高亮邻居；不用外部库） ═════════════
// 数据（连线规则和以前一样）：
//   局部图（目录 MAP）：当前页 + 所在文件夹（圆心）+ 同文件夹的页（实线）+ 共享标签 / 同引一篇收藏的页（虚线）——深度 1；
//   全局图（首页 MAP、「全局图」浮层）：所有文件夹 + 所有页；文件夹—页实线，引了同一篇收藏的两页虚线。
// 模拟（forceSim）：自己写的小 d3-force，参数含义和 d3 一样：link（静止长度、强度 1/min(两端度数)）、many-body 斥力（两两精确算，
//   300 个点每帧约 4.5 万对）、collide、center；alpha 冷却（alphaDecay = 1 − 0.001^(1/300)，velocityDecay 0.4），alpha < 0.001 停；
//   拖动时 alphaTarget 0.3 重新加热。起点用 d3 的葵花籽排布、抖动用固定种子——同样的数据每次排出来一样。
// 画（forceGraph）：SVG + requestAnimationFrame；平移 / 缩放是一层 <g> 的变换。开始时自动适配（字也算进边框，不切字），用户动过视图就不再自动适配。
// 交互（同 Quartz）：拖点（跟着指针走，松手放开）、滚轮 / 双指缩放（以指针为中心）、拖空白平移、悬停高亮自己和邻居（其余淡到 0.2）、点一下打开；
//   字：悬停的点和邻居、当前页、文件夹名（局部图里还有虚线另一头）一直显示，别的随缩放淡入（Quartz：(k × opacityScale − 1) / 3.75）。
// 生命周期：重画 / 卸载时 destroy（停 rAF、断开观察器）；看不见（MAP 收起就不建、滚出视口、整页被摘下）就暂停，回来再接着动；
//   prefers-reduced-motion：同步算到收敛只画结果，拖动松手后也是一次算好。上一次的位置按图的种类记着，重画同一张图不再从头动一遍。
function relations(p) {
  const out = new Map();
  const put = (q, why) => { if (q !== p && q.role === 'page') { const w = out.get(q.id) || []; w.push(why); out.set(q.id, w); } };
  for (const t of p._allTags) if (!IDX.catTags.has(t)) for (const q of IDX.byTag.get(t) || []) put(q, 'tag');
  for (const id of p._cites) for (const q of citedBy(id)) put(q, 'cite');
  return out;
}
const GRAPHS = new Set();
const POS_CACHE = {};
LB.onUnload(() => { for (const g of [...GRAPHS]) g.destroy(); });
const rafFn = typeof requestAnimationFrame === 'function' ? f => requestAnimationFrame(f) : f => setTimeout(f, 16);
const cafFn = typeof cancelAnimationFrame === 'function' ? id => cancelAnimationFrame(id) : id => clearTimeout(id);
function reducedMotion() {
  try {
    if (typeof matchMedia === 'function') return !!matchMedia('(prefers-reduced-motion: reduce)').matches;
    return !!(WIN && typeof WIN.matchMedia === 'function' && WIN.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch (e) { return false; }
}
function forceSim(nodes, links, o) {
  let seed = 0x2f6b;
  const jiggle = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296 - 0.5) * 1e-6;
  nodes.forEach((n, i) => {
    if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) { const r = 10 * Math.sqrt(0.5 + i), a = i * Math.PI * (3 - Math.sqrt(5)); n.x = r * Math.cos(a); n.y = r * Math.sin(a); }
    n.vx = 0; n.vy = 0;
  });
  const byId = new Map(nodes.map(n => [n.id, n]));
  const L = [], deg = new Map();
  for (const l of links) {
    const s = byId.get(l.source), t = byId.get(l.target);
    if (!s || !t || s === t) continue;
    L.push({ s, t, dashed: !!l.dashed });
    deg.set(s, (deg.get(s) || 0) + 1); deg.set(t, (deg.get(t) || 0) + 1);
  }
  for (const l of L) { const a = deg.get(l.s), b = deg.get(l.t); l.strength = 1 / Math.min(a, b); l.bias = a / (a + b); }
  const sim = {
    nodes, links: L, byId, alpha: 1, alphaMin: 0.001, alphaDecay: 1 - Math.pow(0.001, 1 / 300), alphaTarget: 0, velocityDecay: 0.4,
    get done() { return sim.alpha < sim.alphaMin && sim.alphaTarget === 0; },
    tick() {
      sim.alpha += (sim.alphaTarget - sim.alpha) * sim.alphaDecay;
      const a = sim.alpha, N = nodes.length;
      for (const l of L) {   // link：拉向静止长度
        let x = l.t.x + l.t.vx - l.s.x - l.s.vx || jiggle(), y = l.t.y + l.t.vy - l.s.y - l.s.vy || jiggle();
        let d = Math.sqrt(x * x + y * y);
        d = (d - o.distance) / d * a * l.strength; x *= d; y *= d;
        l.t.vx -= x * l.bias; l.t.vy -= y * l.bias; l.s.vx += x * (1 - l.bias); l.s.vy += y * (1 - l.bias);
      }
      for (let i = 0; i < N; i++) {   // many-body 斥力 + collide（同一个两两循环）
        const p = nodes[i];
        for (let j = i + 1; j < N; j++) {
          const q = nodes[j];
          let x = q.x - p.x, y = q.y - p.y, l2 = x * x + y * y;
          if (l2 === 0) { x = jiggle(); y = jiggle(); l2 = x * x + y * y; }
          const lc = l2 < 1 ? Math.sqrt(l2) : l2;
          const w = o.charge * a / lc;
          p.vx += x * w; p.vy += y * w; q.vx -= x * w; q.vy -= y * w;
          const rr = p.r + q.r + o.pad;
          let cx = q.x + q.vx - p.x - p.vx, cy = q.y + q.vy - p.y - p.vy, c2 = cx * cx + cy * cy;
          if (c2 < rr * rr) {
            if (c2 === 0) { cx = jiggle(); cy = jiggle(); c2 = cx * cx + cy * cy; }
            const l = Math.sqrt(c2), m = (rr - l) / l * o.collide, rp = p.r * p.r, rq = q.r * q.r, k = rq / (rp + rq);
            cx *= m; cy *= m;
            p.vx -= cx * k; p.vy -= cy * k; q.vx += cx * (1 - k); q.vy += cy * (1 - k);
          }
        }
      }
      let sx = 0, sy = 0;
      for (const n of nodes) {
        if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; }
        else { n.vx *= 1 - sim.velocityDecay; n.vy *= 1 - sim.velocityDecay; n.x += n.vx; n.y += n.vy; }
        sx += n.x; sy += n.y;
      }
      if (N) { sx = sx / N * o.center; sy = sy / N * o.center; for (const n of nodes) if (n.fx == null) { n.x -= sx; n.y -= sy; } }   // center
    },
    settle(max = 800) { let i = 0; while (!sim.done && i++ < max) sim.tick(); return i; },
  };
  return sim;
}
// 字宽估算（中文一个字 1em，拉丁字母 0.6em）：适配视图时把字也算进去
const labelWidth = (t, fs) => [...String(t || '')].reduce((s, c) => s + (/[⺀-￿]/.test(c) ? 1 : 0.6), 0) * fs;
function forceGraph({ nodes, links, current = null, also = new Set(), width, height, mode, label, onOpen }) {
  const W = Math.max(120, Math.round(width)), H = Math.max(100, Math.round(height));
  const local = mode === 'local' || mode === 'mini';
  const FS = local ? 9.5 : 11;
  const opacityScale = mode === 'home' ? 2.5 : 1;
  const reduce = reducedMotion();
  const degc = new Map();
  for (const l of links) { degc.set(l.source, (degc.get(l.source) || 0) + 1); degc.set(l.target, (degc.get(l.target) || 0) + 1); }
  for (const n of nodes) { const d = degc.get(n.id) || 0; n.r = n.hub ? (local ? 7 : 9) + Math.sqrt(d) * 1.1 : n.id === current ? 5.5 + Math.sqrt(d) * 0.8 : 2.6 + Math.sqrt(d) * 0.9; }
  const cache = POS_CACHE[mode] || (POS_CACHE[mode] = new Map());
  let cached = 0;
  for (const n of nodes) { const c = cache.get(n.id); if (c) { n.x = c.x; n.y = c.y; cached++; } }
  const sim = forceSim(nodes, links, { distance: local ? 34 : 42, charge: local ? -70 : -60, center: 0.3, collide: 0.7, pad: 4 });
  if (nodes.length && cached === nodes.length) sim.alpha = 0.02;   // 位置都记着：只轻轻收一下
  else if (cached) sim.alpha = 0.5;
  const did = nextId('g');
  const svg = S('svg', { class: 'lbw-graph is-live is-' + mode, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-labelledby': did }, S('desc', { id: did }, label || '关系图'));
  const vp = S('g', { class: 'vp' }), gL = S('g'), gN = S('g');
  vp.append(gL, gN); svg.append(vp);
  const lineEls = sim.links.map(l => { const e = S('line', { class: 'e' + (l.dashed ? ' x' : '') }); gL.append(e); return e; });
  const neigh = new Map(nodes.map(n => [n, new Set([n])]));
  for (const l of sim.links) { neigh.get(l.s).add(l.t); neigh.get(l.t).add(l.s); }
  const nodeEls = new Map(), labEls = new Map();
  let hover = null, drag = null, pan = null, pinch = null;
  for (const n of nodes) {
    const fs = n.hub ? FS * 1.15 : FS;
    n.lw = labelWidth(n.title, fs); n.fs = fs;
    const g = S('g', { class: 'nd' + (n.hub ? ' is-hub' : '') + (n.id === current ? ' is-cur' : '') + (also.has(n.id) ? ' is-also' : ''), 'data-node': n.id });
    g.append(S('circle', { class: 'hit', r: (n.r + 6).toFixed(1) }), S('circle', { class: 'dot', r: n.r.toFixed(1) }));
    if (n.hub && n.no) g.append(S('text', { class: 'hubn', y: (n.r * 0.34).toFixed(1), 'text-anchor': 'middle', style: `font-size:${(n.r * 0.95).toFixed(1)}px` }, n.no));
    const lab = S('text', { class: 'lab' + (n.hub ? ' hub' : '') + (n.id === current ? ' cur' : ''), y: (n.r + fs * 1.15).toFixed(1), 'text-anchor': 'middle', style: `font-size:${fs.toFixed(1)}px` }, n.title);
    g.append(lab); labEls.set(n, lab);
    g.addEventListener('pointerenter', () => { if (!drag && !pan) setHover(n); });
    g.addEventListener('pointerleave', () => { if (!drag) setHover(null); });
    gN.append(g); nodeEls.set(n, g);
  }
  // ── 视图：平移 / 缩放 / 自动适配 ──
  const view = { k: 1, x: W / 2, y: H / 2 };
  let userView = false, lastK = -1;
  function fitTarget() {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const n of nodes) { const hw = Math.max(n.r, n.lw / 2); x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y0 = Math.min(y0, n.y - n.r); y1 = Math.max(y1, n.y + n.r + n.fs * 1.5); }
    if (!Number.isFinite(x0)) return { k: 1, x: W / 2, y: H / 2 };
    const pad = 10, k = Math.max(0.15, Math.min((W - 2 * pad) / Math.max(1, x1 - x0), (H - 2 * pad) / Math.max(1, y1 - y0), local ? 1.6 : 2.2));
    return { k, x: W / 2 - (x0 + x1) / 2 * k, y: H / 2 - (y0 + y1) / 2 * k };
  }
  function fit(ease = 1) { const t = fitTarget(); view.k += (t.k - view.k) * ease; view.x += (t.x - view.x) * ease; view.y += (t.y - view.y) * ease; applyView(); }
  function applyView() {
    vp.setAttribute('transform', `translate(${view.x.toFixed(2)},${view.y.toFixed(2)}) scale(${view.k.toFixed(4)})`);
    if (Math.abs(view.k - lastK) > 0.01) { lastK = view.k; paintLabels(); }
  }
  function paintLabels() {
    const base = Math.max(0, Math.min(1, (view.k * opacityScale - 1) / 3.75));
    const hl = hover ? neigh.get(hover) : null;
    for (const [n, t] of labEls) t.style.opacity = String(n.hub || n.id === current || also.has(n.id) || (hl && hl.has(n)) ? 1 : Number(base.toFixed(3)));
  }
  function setHover(n) {
    if (hover === n) return;
    hover = n;
    const hl = n ? neigh.get(n) : null;
    svg.classList.toggle('has-hover', !!n);
    for (const [m, g] of nodeEls) g.classList.toggle('is-hl', !!hl && hl.has(m));
    sim.links.forEach((l, i) => lineEls[i].classList.toggle('is-hl', !!n && (l.s === n || l.t === n)));
    paintLabels();
  }
  function render() {
    sim.links.forEach((l, i) => { const e = lineEls[i]; e.setAttribute('x1', l.s.x.toFixed(1)); e.setAttribute('y1', l.s.y.toFixed(1)); e.setAttribute('x2', l.t.x.toFixed(1)); e.setAttribute('y2', l.t.y.toFixed(1)); });
    for (const [n, g] of nodeEls) g.setAttribute('transform', `translate(${n.x.toFixed(1)},${n.y.toFixed(1)})`);
  }
  // ── 动画循环 ──
  let rafId = 0, alive = true, paused = false, visible = true;
  const remember = () => { for (const n of nodes) cache.set(n.id, { x: n.x, y: n.y }); };
  function wake() { if (!alive || rafId || reduce) return; rafId = rafFn(frame); }
  function frame() {
    rafId = 0;
    if (!alive) return;
    if (!svg.isConnected || !visible) { paused = true; return; }   // 看不见就停，resume / 观察器叫醒
    sim.tick();
    if (!userView) fit(sim.done ? 1 : 0.18);
    render();
    if (!sim.done || drag) rafId = rafFn(frame);
    else remember();
  }
  function settleNow() { sim.settle(); if (!userView) fit(1); render(); remember(); }
  function reheat(t) { sim.alphaTarget = t; wake(); }
  // ── 指针：拖点 / 平移 / 双指缩放；滚轮缩放 ──
  const pointers = new Map();
  const pid = e => (e.pointerId == null ? 0 : e.pointerId);
  const toLocal = e => { const r = svg.getBoundingClientRect(); const sx = r.width ? W / r.width : 1, sy = r.height ? H / r.height : 1; return { x: ((e.clientX || 0) - (r.left || 0)) * sx, y: ((e.clientY || 0) - (r.top || 0)) * sy }; };
  const toWorld = pt => ({ x: (pt.x - view.x) / view.k, y: (pt.y - view.y) / view.k });
  function zoomAt(pt, k2) {
    k2 = Math.max(0.15, Math.min(6, k2));
    view.x = pt.x - (pt.x - view.x) * k2 / view.k; view.y = pt.y - (pt.y - view.y) * k2 / view.k; view.k = k2;
    userView = true; applyView();
  }
  svg.addEventListener('pointerdown', e => {
    if (e.pointerType === 'mouse' && e.button) return;
    const pt = toLocal(e); pointers.set(pid(e), pt);
    try { if (typeof svg.setPointerCapture === 'function' && e.pointerId != null) svg.setPointerCapture(e.pointerId); } catch (err) { console.debug('[lb] wiki graph capture', err); }
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, k: view.k, last: view.k };
      if (drag) { drag.n.fx = drag.n.fy = null; drag = null; sim.alphaTarget = 0; }
      pan = null; return;
    }
    const ge = e.target && typeof e.target.closest === 'function' ? e.target.closest('[data-node]') : null;
    const n = ge ? sim.byId.get(ge.getAttribute('data-node')) : null;
    if (n) {
      userView = true;   // 拖着的时候视图不再自动适配（不然缩放 / 平移每帧在变，点会离开指针）
      const w = toWorld(pt);
      drag = { n, start: pt, moved: false, dx: n.x - w.x, dy: n.y - w.y };   // 点和指针的相对位置，拖到哪儿都保持
      n.fx = n.x; n.fy = n.y; setHover(n); reheat(0.3);
    }
    else pan = { start: pt, x: view.x, y: view.y, moved: false };
    if (typeof e.preventDefault === 'function') e.preventDefault();
  });
  svg.addEventListener('pointermove', e => {
    if (!pointers.has(pid(e))) return;
    const pt = toLocal(e); pointers.set(pid(e), pt);
    if (pinch && pointers.size >= 2) {
      const [a, b] = [...pointers.values()];
      zoomAt({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, pinch.k * (Math.hypot(a.x - b.x, a.y - b.y) || 1) / pinch.d);
      return;
    }
    if (drag) {
      if (Math.hypot(pt.x - drag.start.x, pt.y - drag.start.y) > 3) drag.moved = true;
      const w = toWorld(pt); drag.n.fx = drag.n.x = w.x + drag.dx; drag.n.fy = drag.n.y = w.y + drag.dy;
      render(); return;
    }
    if (pan) {
      const dx = pt.x - pan.start.x, dy = pt.y - pan.start.y;
      if (Math.hypot(dx, dy) > 3) pan.moved = true;
      view.x = pan.x + dx; view.y = pan.y + dy; userView = true; applyView();
    }
  });
  // 结束拖动：放开那个点、alphaTarget 归零（模拟照常冷下来停掉）。松手 / 取消 / 丢了指针捕获 / 销毁都走这里
  function endDrag() {
    if (!drag) return null;
    const d = drag; drag = null;
    d.n.fx = null; d.n.fy = null; sim.alphaTarget = 0;
    if (alive) { if (reduce) settleNow(); else wake(); }
    return d;
  }
  const up = e => {
    pointers.delete(pid(e));
    if (pinch) { if (pointers.size < 2) pinch = null; return; }
    const d = endDrag();
    if (d && !d.moved && e.type === 'pointerup' && typeof onOpen === 'function') onOpen(d.n);
    pan = null;
  };
  svg.addEventListener('pointerup', up);
  svg.addEventListener('pointercancel', up);
  svg.addEventListener('lostpointercapture', () => { pointers.clear(); pinch = null; pan = null; endDrag(); });
  svg.addEventListener('wheel', e => { if (typeof e.preventDefault === 'function') e.preventDefault(); zoomAt(toLocal(e), view.k * Math.exp(-(Number(e.deltaY) || 0) * 0.0015)); }, { passive: false });
  // 滚出视口就停（目录很长时 MAP 不在眼前）
  let io = null;
  if (typeof IntersectionObserver === 'function') {
    try { io = new IntersectionObserver(es => { for (const en of es) visible = !!en.isIntersecting; if (visible && paused) { paused = false; wake(); } }); io.observe(svg); }
    catch (e) { io = null; }
  }
  const api = {
    svg, sim, view, nodes, links: sim.links, mode, alive: true,
    get running() { return !!rafId; }, get hover() { return hover; },
    nodeEl: id => nodeEls.get(sim.byId.get(id)), setHover, settleNow,
    resume() { if (alive && paused) { paused = false; wake(); } },
    destroy() { if (!alive) return; alive = false; api.alive = false; endDrag(); pointers.clear(); pan = null; pinch = null; if (rafId) cafFn(rafId); rafId = 0; if (io) io.disconnect(); remember(); GRAPHS.delete(api); },
  };
  svg.__lbwGraph = api;
  GRAPHS.add(api);
  if (reduce) settleNow();   // 减少动态效果：同步算到收敛，只画结果
  else { fit(1); render(); wake(); }   // 记着位置的图（alpha 0.02）也交给 rAF 收尾：几帧就停，不在主线程上一口气 O(n²) 硬算
  return api;
}
function hubNumbers() { const m = new Map(); topics().forEach((t, k) => m.set(t.id, pad2(k + 1))); return m; }
const gnode = (p, nos) => ({ id: p.id, title: p.title, hub: p.role === 'topic', no: nos.get(p.id) || '' });
function localGraphData(cur) {
  const nos = hubNumbers();
  const hubs = cur.role === 'topic' ? [cur] : foldersOf(cur);
  const nodes = new Map([[cur.id, gnode(cur, nos)]]), links = [], seen = new Set();
  const link = (a, b, dashed) => { const k = a < b ? a + '|' + b : b + '|' + a; if (a === b || seen.has(k)) return; seen.add(k); links.push({ source: a, target: b, dashed }); };
  for (const hb of hubs) { nodes.set(hb.id, gnode(hb, nos)); for (const q of pagesIn(hb)) { if (!nodes.has(q.id)) nodes.set(q.id, gnode(q, nos)); link(hb.id, q.id, false); } }
  const also = new Set();
  if (cur.role === 'page') for (const [id] of relations(cur)) { const q = PAGES.get(id); if (!q) continue; also.add(id); if (!nodes.has(id)) nodes.set(id, gnode(q, nos)); link(cur.id, id, true); }
  return { nodes: [...nodes.values()], links, also };
}
function globalGraphData() {
  const nos = hubNumbers();
  const nodes = new Map(), links = [];
  for (const t of topics()) { nodes.set(t.id, gnode(t, nos)); for (const p of pagesIn(t)) { if (!nodes.has(p.id)) nodes.set(p.id, gnode(p, nos)); links.push({ source: t.id, target: p.id }); } }
  for (const p of loosePages()) nodes.set(p.id, gnode(p, nos));
  const pages = [...PAGES.values()].filter(p => p.role === 'page' && nodes.has(p.id));
  const keys = pages.map(citeKeys);
  for (let i = 0; i < pages.length; i++) for (let j = i + 1; j < pages.length; j++) {
    if (!keys[i].size || !keys[j].size) continue;
    for (const k of keys[i]) if (keys[j].has(k)) { links.push({ source: pages[i].id, target: pages[j].id, dashed: true }); break; }
  }
  return { nodes: [...nodes.values()], links };
}
const GLOBAL_LABEL = '整个 Wiki 的关系图：文件夹是大圆，页面绕着它；实线 = 同一个文件夹，虚线 = 引了同一篇收藏';
const openNode = n => { const p = PAGES.get(n.id); if (p) goPage(p); };
// 目录顶上的小图：有当前页 = 局部图；首页 / 标签页 = 全局图的缩小版
function tocGraph(cur) {
  if (R.miniGraph) { R.miniGraph.destroy(); R.miniGraph = null; }
  R.miniGraph = cur
    ? forceGraph({ ...localGraphData(cur), current: cur.id, width: 248, height: 200, mode: 'local', label: `「${cur.title}」的关系图：所在文件夹、同文件夹的页、共享标签或引了同一篇收藏的页`, onOpen: openNode })
    : forceGraph({ ...globalGraphData(), width: 248, height: 200, mode: 'mini', label: GLOBAL_LABEL, onOpen: openNode });
  return R.miniGraph.svg;
}
function homeGraph(W, H) {
  if (R.homeGraph) { R.homeGraph.destroy(); R.homeGraph = null; }
  R.homeGraph = forceGraph({ ...globalGraphData(), width: W, height: H, mode: 'home', label: GLOBAL_LABEL, onOpen: openNode });
  return R.homeGraph.svg;
}
// 「全局图」浮层：Esc / 点遮罩关
function openGlobalGraph() {
  closeGlobalGraph(); closePop();
  const vw = (WIN && WIN.innerWidth) || 1200, vh = (WIN && WIN.innerHeight) || 800;
  const W = Math.round(Math.max(320, Math.min(1400, vw * 0.92 - 44))), H = Math.round(Math.max(240, Math.min(900, vh * 0.86 - 70)));
  const g = forceGraph({ ...globalGraphData(), current: UI.view === 'page' ? UI.id : null, width: W, height: H, mode: 'global', label: GLOBAL_LABEL, onOpen: n => { closeGlobalGraph(); openNode(n); } });
  const close = btn({ cls: 'lbw-mpin', on: { click: () => closeGlobalGraph() } }, h('span', { text: '×', attr: { 'aria-hidden': 'true' } }), sr('关掉全局图'));
  const panel = h('div', { cls: 'lbw-gpanel', attr: { role: 'dialog', 'aria-modal': 'true' } },
    h('div', { cls: 'lbw-sech' }, h('span', { cls: 'lbw-kick', text: 'MAP' }), h('span', { cls: 'lbw-zh', text: '全局图' }), h('span', { cls: 'lbw-rule' }),
      h('span', { cls: 'lbw-legend' }, h('span', null, h('i'), '同一个文件夹'), h('span', null, h('i', { cls: 'is-x' }), '引了同一篇收藏'), h('span', { text: '拖动 · 滚轮缩放 · Esc 关' })), close),
    g.svg);
  const bg = h('div', { cls: 'lbw-gbg' }, panel);
  bg.addEventListener('click', e => { if (e.target === bg) closeGlobalGraph(); });
  R.layer.append(bg);
  R.gOverlay = { bg, g };
}
function closeGlobalGraph() { const o = R.gOverlay; if (!o) return; R.gOverlay = null; o.g.destroy(); o.bg.remove(); }

// ═════════════ 中间：首页 / 文件夹页 / 页面 / 标签页 ═════════════
function renderCenter() {
  // ④ 重画只画不存。正常路径上提交点都在重画之前；万一还有没提交的字（编辑框开着 / 整页 Markdown 框里有新字），收进草稿，不存也不丢
  if (ED) { stashUnsaved(ED.p); closeEditor(); }
  { const sp = current(), box = liveSrc(sp); if (box && !box.readOnly && box.value !== sp.body) { stashUnsaved(sp); box._lbDead = true; } }
  if (R.homeGraph) { R.homeGraph.destroy(); R.homeGraph = null; }
  R.center.textContent = '';
  R.saved = R.doc = R.add = R.title = R.srcEd = R.tagIn = null;
  if (UI.view === 'tag') renderTag(UI.tag);
  else if (UI.view === 'page' && PAGES.get(UI.id)) { const p = PAGES.get(UI.id); if (p.role === 'topic') renderFolder(p); else renderPage(p); }
  else renderHome();
  renderRail();
}
const secHead = (kick, zh, ...tail) => h('div', { cls: 'lbw-sech' }, h('span', { cls: 'lbw-kick', text: kick }), h('span', { cls: 'lbw-zh', text: zh }), h('span', { cls: 'lbw-rule' }), tail);
function renderHome() {
  const pages = [...PAGES.values()].filter(p => p.role === 'page');
  const cited = new Set(pages.flatMap(p => [...citeKeys(p)]));
  const ts = topics();
  const sheet = (list, cls = '') => h('span', { cls: 'lbw-fold-sheet' + cls }, list.slice(0, 6).map((p, k) => h('span', null, NUM(pad2(k + 1)), p.title)));
  const dots = list => h('span', { cls: 'lbw-fold-dots', attr: { 'aria-hidden': 'true' } }, list.map(p => h('i', { cls: p._tasks.some(x => !x.done) ? 'is-o' : '' })));
  const folder = (t, k) => {
    const list = pagesIn(t);
    const d = toDate([t, ...list].map(p => p.updated).filter(Boolean).sort().pop());
    return btn({ cls: 'lbw-fold', data: { page: t.id }, on: { click: () => goPage(t) } },
      h('span', { cls: 'lbw-fold-tab' }, h('span', { cls: 'lbw-kick', text: String(t.index_tag).toUpperCase().slice(0, 14) })), h('span', { cls: 'lbw-fold-back' }), h('span', { cls: 'lbw-fold-sheet is-s2' }), sheet(list),
      h('span', { cls: 'lbw-fold-face' }, h('span', { cls: 'lbw-fold-num', text: pad2(k + 1) }), dots(list), h('span', { cls: 'lbw-fold-name', text: t.title }),
        h('span', { cls: 'lbw-fold-cap' }, NUM(String(list.length)), ' 页', d ? [' · 更新 ', NUM(`${pad2(d.getMonth() + 1)}/${pad2(d.getDate())}`)] : null)));
  };
  const loose = loosePages();
  const cw = R.center.clientWidth || 900;
  const W = Math.round(Math.max(300, Math.min(1000, cw - 60))), H = W < 560 ? 300 : 440;
  const week = Date.now() - 7 * 86400000;
  const stat = (n, lab) => h('div', null, h('span', { cls: 'lbw-big', text: String(n) }), h('span', { cls: 'lbw-lab', text: lab }));
  const ovBtn = btn({ cls: 'lbw-chev' + (UI.ovShut ? ' is-shut' : ''), attr: { 'aria-expanded': String(!UI.ovShut) }, on: { click: () => { UI.ovShut = !UI.ovShut; saveUi(); renderCenter(); } } }, icon('fold'), sr(UI.ovShut ? '展开概览' : '收起概览'));
  add(R.center, [
    h('section', null, secHead('OVERVIEW', '概览', ovBtn), UI.ovShut ? null : h('div', { cls: 'lbw-ov' },
      stat(pages.length, '全部页面'), stat(pages.filter(p => (toDate(p.updated)?.getTime() || 0) >= week).length, '近 7 天改过'), stat(cited.size, '引用的收藏'), stat(ts.length, '文件夹'))),
    h('section', { cls: 'lbw-gap' }, secHead('INDEX', '目录', h('span', { cls: 'lbw-cap' }, NUM(pad2(ts.length)), ' 个文件夹 · ', NUM(String(pages.length)), ' 页')),
      h('div', { cls: 'lbw-folders' }, ts.map(folder),
        loose.length ? btn({ cls: 'lbw-fold is-loose', on: { click: () => { PREFS.open = { ...(PREFS.open || {}), [looseId]: true }; saveUi(); setTocOff(false); renderToc(); setDrawer(true); LB.say('未归类的页在左边目录最下面；拖到文件夹上就归进去了'); } } },
          h('span', { cls: 'lbw-fold-tab' }, h('span', { cls: 'lbw-kick', text: 'INBOX' })), h('span', { cls: 'lbw-fold-back' }), sheet(loose),
          h('span', { cls: 'lbw-fold-face' }, h('span', { cls: 'lbw-fold-num', text: '··' }), dots(loose), h('span', { cls: 'lbw-fold-name', text: '未归类' }), h('span', { cls: 'lbw-fold-cap' }, NUM(String(loose.length)), ' 页'))) : null,
        readOnly ? null : btn({ cls: 'lbw-fold is-new', on: { click: () => newPageModal({ folder: true }) } }, h('span', { cls: 'lbw-fold-tab' }, h('span', { cls: 'lbw-kick', text: 'NEW' })),
          h('span', { cls: 'lbw-fold-face' }, h('span', { cls: 'lbw-plus', text: '+', attr: { 'aria-hidden': 'true' } }), h('span', { cls: 'lbw-cap', text: '新文件夹' }))))),
    h('section', { cls: 'lbw-gap' }, secHead('MAP', '关系图', h('span', { cls: 'lbw-legend' }, h('span', null, h('i'), '同一个文件夹'), h('span', null, h('i', { cls: 'is-x' }), '引了同一篇收藏'))),
      h('div', { cls: 'lbw-map' }, ['is-tl', 'is-tr', 'is-bl', 'is-br'].map(c => h('span', { cls: 'lbw-crop ' + c })),
        h('span', { cls: 'lbw-corner is-n' }, 'N° ', NUM(pad2(pages.length))), h('span', { cls: 'lbw-corner is-mark', text: 'LWA / WIKI' }), homeGraph(W, H))),
  ]);
  if (!PAGES.size) R.center.prepend(h('p', { cls: 'lbw-rnone', text: readOnly ? 'Wiki 里还没有页面。' : 'Wiki 里还没有页面：点下面的「新文件夹」，或目录上的 ＋ 新建一页。' }));
}
const crumb = parts => h('nav', { cls: 'lbw-crumb' }, btn({ cls: 'lbw-kick', text: 'INDEX', on: { click: () => go('home') } }), parts.map(x => [h('span', { cls: 'lbw-sep', text: '/', attr: { 'aria-hidden': 'true' } }), x]));
function hint(items) {
  if (LB.mobile) items = ['手机上只读，回电脑上改'];
  else if (readOnly) items = ['插件没启用，只能看'];
  return h('div', { cls: 'lbw-hint' }, items.map(x => h('span', null, x)));
}
function prow(p, i) {
  return btn({ cls: 'lbw-prow', data: { page: p.id }, on: { click: e => { e.stopPropagation(); goPage(p); } } }, NUM(pad2(i + 1)),
    h('span', { cls: 'lbw-pt' }, h('span', { cls: 'lbw-t', text: p.title }), h('span', { cls: 'lbw-l', text: p._lead })), h('span', { cls: 'lbw-d lbw-num', text: mmdd(p.updated) }));
}
function titleInput(p, label) {
  const tid = nextId('title');
  const ti = h('input', { cls: 'lbw-ptitle', attr: { id: tid, type: 'text' } });
  ti.value = p.title;
  R.title = ti;
  if (readOnly) ti.setAttribute('readonly', '');
  else {
    // 事件总是绑上（10-29 四审：忙的时候画出来的框，存完由 paintLock 解冻、不重画，没绑事件就改了也存不上）；忙不忙在处理时判
    if (busyPage(p)) ti.readOnly = true;
    ti.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (e.key === 'Escape') ti.value = p.title; ti.blur(); } });
    ti.addEventListener('blur', () => {
      if (!ti.isConnected || ti.readOnly || busyPage(p)) return;   // 后台摘下（换视图）不当成改名；页面忙（只读）时不收
      const v = ti.value.trim();
      if (!v || v === p.title) { ti.value = p.title; return; }
      const other = pageByTitle(v);
      if (other && other !== p) { LB.say(`已经有一页叫「${v}」了`, { kind: 'warn' }); ti.value = p.title; return; }
      if (mutate(p, n => { n.title = v; })) { renderToc(); renderSub(); } else ti.value = p.title;
    });
  }
  return [h('label', { cls: 'lb-visually-hidden', attr: { for: tid }, text: label }), ti];
}
function savedSpan(p) { R.saved = h('span', { cls: 'lbw-saved' }); paintSaved(p); return R.saved; }
function paintSaved(p) {
  if (!R.saved || !p || current() !== p) return;
  R.saved.textContent = '';
  if (savingPage(p)) R.saved.append('保存中…'); else R.saved.append(NUM(fmtAt(p.updated)));
}
function renderFolder(t) {
  const k = topics().indexOf(t);
  const listed = /```pages/.test(t.body);
  const bodyTxt = stripCode(t.body);
  const rest = listed ? [] : pagesIn(t).filter(p => !bodyTxt.includes(p.title));
  add(R.center, [
    crumb([h('span', null, '文件夹 ', NUM(pad2(k + 1)))]),
    h('div', { cls: 'lbw-fhead' }, h('span', { cls: 'lbw-big', text: pad2(k + 1) }), titleInput(t, '文件夹名')),
    h('div', { cls: 'lbw-meta' }, savedSpan(t), h('span', { cls: 'lbw-dot', text: '·' }), h('span', null, NUM(String(pagesIn(t).length)), ' 页'), h('span', { cls: 'lbw-dot', text: '·' }), h('span', null, NUM(String(t._chars)), ' 字')),
    draftBar(t),
    docNodes(t, '写这个文件夹的索引：分几块、先看什么、为什么关注……'),
    rest.length ? h('div', { cls: 'lbw-rest' }, h('div', { cls: 'lbw-plist' }, h('div', { cls: 'lbw-plist-h' }, h('span', { cls: 'lbw-kick', text: 'MORE' }), h('span', { cls: 'lbw-cap', text: '还没写进上面的页' }), NUM(String(rest.length))), rest.map((p, i) => prow(p, i)))) : null,
    hint(['随时可改，点哪段改哪段', h('span', null, '想要自动列表就写 ', h('span', { cls: 'lbw-code', text: '```pages' })), h('span', null, kbd('Ctrl Alt 0–4'), ' 改层级')]),
  ]);
}
function renderPage(p) {
  const fs = foldersOf(p);
  const chips = h('span', { cls: 'lbw-chips' }, p.tags.map(t => {
    const x = readOnly ? null : h('span', { cls: 'lbw-x', text: '×', attr: { 'aria-hidden': 'true' } });
    if (x) x.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); if (busyPage(p)) return; mutate(p, n => { n.tags = n.tags.filter(g => g !== t); }); renderKeepScroll(); });
    const a = h('a', { cls: 'lbw-chip', attr: { href: '#' }, data: { tag: t } }, '#' + t, x);
    a.addEventListener('click', e => { e.preventDefault(); goTag(t); });
    return a;
  }));
  if (!readOnly) {
    if (UI.tagEdit) {
      const iid = nextId('tag'), lid = nextId('tags');
      const tg = h('input', { cls: 'lbw-chipin', attr: { id: iid, placeholder: '标签 / 文件夹', list: lid, type: 'text' } });
      R.tagIn = tg;
      let done = false;
      const fin = commit => { if (done) return; done = true; const v = cleanTag(tg.value); UI.tagEdit = false; if (commit && v && !p.tags.includes(v) && !busyPage(p)) mutate(p, n => { n.tags = [...n.tags, v]; }); renderKeepScroll(); };
      tg.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); fin(true); } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); fin(false); } });
      tg.addEventListener('blur', () => { if (tg.isConnected) fin(true); });
      add(chips, [h('label', { cls: 'lb-visually-hidden', attr: { for: iid }, text: '加标签或文件夹' }), tg, h('datalist', { attr: { id: lid } }, [...IDX.byTag.keys()].map(t => h('option', { attr: { value: t } })))]);
    } else chips.append(btn({ cls: 'lbw-chipadd', on: { click: () => { UI.tagEdit = true; renderKeepScroll(); } } }, icon('plus'), sr('加标签')));
  }
  add(R.center, [
    h('div', { cls: 'lbw-crumbrow' }, crumb(fs[0] ? [btn({ text: fs[0].title, on: { click: () => goPage(fs[0]) } })] : []), R.aiBtn || null),
    titleInput(p, '标题'),
    h('div', { cls: 'lbw-meta' }, savedSpan(p), h('span', { cls: 'lbw-dot', text: '·' }), h('span', null, NUM(String(p._chars)), ' 字'),
      p._cites.length ? [h('span', { cls: 'lbw-dot', text: '·' }), h('span', null, '引用 ', NUM(String(citeKeys(p).size)), ' 篇收藏')] : null, chips),
    draftBar(p),
    docNodes(p, '写下第一句：为什么关注这件事？'),
    hint(['点哪段改哪段', h('span', null, kbd('Enter'), ' 下一段 / 下一条'), h('span', null, kbd('@'), ' 引用收藏'), h('span', null, kbd('Ctrl Z'), ' 撤销'), h('span', null, kbd('Esc'), ' 收起'), '段落开头打 # / - / [] 换成标题 / 列表 / 待办']),
  ]);
  if (R.tagIn) R.tagIn.focus();
}
function renderTag(tag) {
  const list = (IDX.byTag.get(tag) || []).filter(p => p.role === 'page').sort(byUpdated);
  const inItems = ITEMS.filter(it => (it.tags || []).includes(tag));
  add(R.center, [
    crumb([h('span', { text: '标签' })]),
    h('div', { cls: 'lbw-fhead' }, h('span', { cls: 'lbw-big', text: '#' }), h('h1', { cls: 'lbw-ptitle', text: tag })),
    h('div', { cls: 'lbw-meta' }, h('span', null, NUM(String(list.length)), ' 页'), h('span', { cls: 'lbw-dot', text: '·' }), h('span', null, '收藏里 ', NUM(String(inItems.length)), ' 篇')),
    h('div', { cls: 'lbw-plist', attr: { style: 'margin-top:40px' } }, h('div', { cls: 'lbw-plist-h' }, h('span', { cls: 'lbw-kick', text: 'PAGES' }), h('span', { cls: 'lbw-cap', text: `带 #${tag} 的页` }), NUM(String(list.length))),
      list.length ? list.map((p, i) => prow(p, i)) : h('p', { cls: 'lbw-rnone', text: '没有' })),
    h('div', { cls: 'lbw-plist', attr: { style: 'margin-top:48px' } }, h('div', { cls: 'lbw-plist-h' }, h('span', { cls: 'lbw-kick', text: 'ARCHIVE' }), h('span', { cls: 'lbw-cap', text: `收藏里带 #${tag} 的 · 用得上再引用` }), NUM(String(inItems.length))),
      inItems.length ? inItems.slice(0, 200).map(it => btn({ cls: 'lbw-prow', data: { item: it.id }, on: { click: () => openCite(it.id) } }, h('span', { cls: 'lbw-k', text: itemType(it) }),
        h('span', { cls: 'lbw-pt' }, h('span', { cls: 'lbw-t', text: it.title || '未命名收藏' }), h('span', { cls: 'lbw-l', text: it.summary || '' })), h('span', { cls: 'lbw-d', text: citedBy(it.id).length ? '已引用' : '' })))
        : h('p', { cls: 'lbw-rnone', text: '没有' })),
  ]);
}
function frontText(p) {
  return ['---', `id: ${p.id}`, `title: ${p.title}`, `role: ${p.role}`, p.index_tag ? `index_tag: ${p.index_tag}` : null, p.order && p.order.length ? `order: ${JSON.stringify(p.order)}` : null,
    `tags: ${JSON.stringify(p.tags)}`, p.created ? `created: ${p.created}` : null, p.updated ? `updated: ${p.updated}` : null, '---'].filter(Boolean).join('\n');
}
function docNodes(p, placeholder) {
  if (UI.src && !readOnly) {
    const ta = h('textarea', { cls: 'lbw-srced', attr: { spellcheck: 'false' } });
    ta.value = p.body; R.srcEd = ta;
    let t = 0;
    if (busyPage(p)) ta.readOnly = true;
    // 2 秒没动自动存；失焦 / Esc 立刻存。计时器到点时框已经被换掉（重画 / 换页）就什么都不做——换掉之前已经存过，旧框里的字不能再拿去存（10-29 审查 1）
    ta.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => applySrc(p, ta), 2000); });
    ta.addEventListener('blur', () => { clearTimeout(t); applySrc(p, ta); });
    ta.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); clearTimeout(t); applySrc(p, ta); UI.src = false; renderKeepScroll(); refreshIfStale(p); } });
    return [h('div', { cls: 'lbw-fm', text: frontText(p) + '　← 文件头由页面维护' }), ta];
  }
  CITE_NO = new Map(); for (const id of p._cites) { const k = citeKey(id); if (!CITE_NO.has(k)) CITE_NO.set(k, CITE_NO.size + 1); }
  const { lines, blocks } = parseBlocks(p.body);
  const docEl = h('div', { cls: 'lbw-doc' });
  const A = UI.ai && UI.ai.id === p.id ? UI.ai : null;
  if (A && A.scope === 'part') { const at = relocate(A, p); if (at) Object.assign(A, at); }   // 别处加删了行：跟着挪
  blocks.forEach((b, i) => {
    const blk = add(h('div', { cls: 'lbw-blk' + (b.type === 'li' ? ' is-li' : '') + (aiLocked(p, b) ? (A && A.scope === 'page' ? ' is-ai-lock is-page' : ' is-ai-lock') : ''), data: { i } }), renderBlock(b, lines, p));
    if (!readOnly) {
      blk.addEventListener('click', e => clickBlock(e, blk, p, i));
      // 段和段之间插一段：左边空白里的 ＋（10-31：以前只能在页尾「接着写」）
      blk.append(btn({ cls: 'lbw-ins', text: '+', on: { click: e => { e.stopPropagation(); openEditor(-1, 0, true, { kind: 'p', pre: '', at: b.e }); } } }, sr('在这段后面插一段')));
    }
    docEl.append(blk);
  });
  R.doc = docEl;
  if (readOnly) return [docEl, blocks.length ? null : h('p', { cls: 'lbw-rnone', text: '这一页还是空的' })];
  R.add = btn({ cls: 'lbw-addblk', text: blocks.length ? '＋ 接着写…' : placeholder, on: { click: () => openEditor(-1, null, true) } });
  const draft = blocks.length ? null : btn({ cls: 'lbw-addblk', text: '或者写下你的思路，让 AI 按它搭框架、去收藏里找材料', data: { ai: 'draft' }, on: { click: () => openAiPlan(p) } });
  return [docEl, R.add, draft];
}
// 这一页现在开着、还作数的整页 Markdown 框（被恢复 / 冲突作废的框 _lbDead，不再拿去存）
function applySrc(p, ta) {
  if (!ta.isConnected || R.srcEd !== ta || ta._lbDead || ta.readOnly || ta.value === p.body) return;   // 冻住 / 作废的框不存（④）
  if (mutate(p, n => { n.body = ta.value; })) renderToc();
}
function flushSrc() { if (UI.src && R.srcEd && R.srcEd.isConnected) { const p = current(); if (p) applySrc(p, R.srcEd); } }

// ═════════════ 编辑：原地改，点哪段改哪段（10-31 重做：不出黑框——编辑框套在和阅读时同一个元素里；列表按条、标题按行；
//   Enter 接着下一条 / 下一段，空的一条再 Enter = 结束列表，开头 Backspace = 去掉列表 / 标题记号，↑↓ 走到上一段 / 下一段） ═════════════
let ED = null;   // {i, s, e, ta, p, el, bar, kind, lv, pre, ind, ord, done, cites, citeOf, isNew}
const lineOffset = (lines, n) => { let o = 0; for (let k = 0; k < n; k++) o += lines[k].length + 1; return o; };
function clickBlock(e, blk, p, i) {
  if (e && e.defaultPrevented) return;
  const bk = parseBlocks(p.body).blocks[i];
  if (bk && aiLocked(p, bk)) { LB.say('这一截在让 AI 改：先在 AI 面板里用上或者「不要」，再改'); return; }
  const sel = WIN && typeof WIN.getSelection === 'function' ? WIN.getSelection() : null;
  if (sel && sel.anchorNode && !sel.isCollapsed && blk.contains(sel.anchorNode)) return;   // 在选字，不打断
  let caret = null;
  try {
    if (sel && sel.anchorNode && blk.contains(sel.anchorNode) && typeof D.createRange === 'function') {
      const r = D.createRange(); r.selectNodeContents(blk); r.setEnd(sel.anchorNode, sel.anchorOffset);
      caret = approxCaret(p, i, r.toString().length);
    }
  } catch (err) { caret = null; }
  openEditor(i, caret);
}
// 点在渲染后的第几个字 → 源码里的位置（跳过行首记号、链接地址、** ` 这些看不见的字）
function approxCaret(p, i, pos) {
  const { lines, blocks } = parseBlocks(p.body); const b = blocks[i]; if (!b) return null;
  const src = lines.slice(b.s, b.e).join('\n');
  let seen = 0, k = 0;
  while (k < src.length) {
    if (k === 0 || src[k - 1] === '\n') { const m = /^(\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?|#{1,6}\s+|>\s?)/.exec(src.slice(k)); if (m && m[0]) { k += m[0].length; continue; } }
    if (seen >= pos) return k;
    if (src.startsWith('](', k)) { const e = src.indexOf(')', k); if (e > 0) { k = e + 1; continue; } }
    if (/[\[\]*`]/.test(src[k])) { k++; continue; }
    if (src[k] !== '\n') seen++;
    k++;
  }
  return src.length;
}
function editPage() { if (UI.view !== 'page') return null; return PAGES.get(UI.id) || null; }
// 一块源码的「样子」：段落 / 标题（几级）/ 列表一条 / 待办 / 引用 / 原样（代码、分隔线）；pre = 第一行的记号（编辑时不显示）
function shapeOf(type, first) {
  if (type === 'h') { const m = /^(#{1,6})\s+/.exec(first) || ['## ', '##']; return { kind: 'h', lv: Math.min(m[1].length, 4), pre: m[0] }; }
  if (type === 'li') {
    const m = /^(\s*)([-*+]|\d+[.)])\s+(\[( |x|X)\]\s+)?/.exec(first);
    if (m) return { kind: m[3] ? 'task' : 'li', pre: m[0], ind: m[1], ord: /\d/.test(m[2]), done: !!m[4] && m[4] !== ' ' };
  }
  if (type === 'quote') return { kind: 'quote', pre: '' };
  if (type === 'p') return { kind: 'p', pre: '' };
  return { kind: 'raw', pre: '' };
}
// 下一条的样子：列表接着列表（编号 +1，待办不打勾），标题 / 段落后面接段落
function nextShape(E) {
  if (E.kind === 'task') return { kind: 'task', pre: E.ind + '- [ ] ', ind: E.ind };
  if (E.kind === 'li') {
    const m = /^(\s*)(\d+)([.)])/.exec(E.pre);
    return { kind: 'li', ind: E.ind, ord: E.ord, pre: m ? `${m[1]}${Number(m[2]) + 1}${m[3]} ` : E.pre };
  }
  return { kind: 'p', pre: '' };
}
// 源码 ↔ 编辑框里显示的字：去掉第一行记号（引用块去每行的 >）；收藏引用的长编号换成 @1 @2（存的时候换回来）
function citeToken(E, id) { if (!E.citeOf.has(id)) { const t = '@' + (E.citeOf.size + 1); E.citeOf.set(id, t); E.cites.set(t, id); } return E.citeOf.get(id); }
function toDisplay(E, src) {
  let s = String(src);
  if (E.kind === 'quote') s = s.split('\n').map(l => l.replace(/^>\s?/, '')).join('\n');
  else if (E.pre && s.startsWith(E.pre)) s = s.slice(E.pre.length);
  else if (E.pre && E.pre.startsWith(s)) s = '';
  return s.replace(/\]\(lwa:([\w-]+)\)/g, (m, id) => `](${citeToken(E, id)})`);
}
const untoken = (E, v) => String(v).replace(/\]\((@\d+)\)/g, (m, t) => (E.cites.has(t) ? `](lwa:${E.cites.get(t)})` : m));
function fromDisplay(E, value) {
  const v = untoken(E, String(value).replace(/\s+$/, ''));
  if (!v.trim()) return '';
  const L = v.split('\n');
  if (E.kind === 'h') return '#'.repeat(E.lv) + ' ' + L.join('\n');
  if (E.kind === 'quote') return L.map(l => '> ' + l).join('\n');
  if (E.kind === 'li' || E.kind === 'task') {
    // 框里另起一行（没缩进）= 另一条，照这一条的记号接上
    let pre = E.pre;
    return L.map((l, k) => {
      if (!k) return pre + l;
      if (/^\s/.test(l) || !l.trim()) return l;
      pre = nextShape({ ...E, pre }).pre;
      return pre + l;
    }).join('\n');
  }
  return L.join('\n');
}
// 编辑框外面那一层：和阅读时同一个元素，样式全继承，点开不跳
function shapeEl(E) {
  const ta = E.ta, ind = E.ind ? { style: `margin-left:${E.ind.length * 0.6}em` } : null;
  if (E.kind === 'h') { const el = h('h' + E.lv, { cls: 'is-ed' }); if (E.hn) el.append(h('span', { cls: 'lbw-num lbw-hn', text: E.hn })); el.append(ta); return el; }
  if (E.kind === 'li') { const l = h(E.ord ? 'ol' : 'ul', null, h('li', { attr: ind }, ta)); const n = /^\s*(\d+)/.exec(E.pre); if (E.ord && n && +n[1] > 1) l.setAttribute('start', n[1]); return l; }
  if (E.kind === 'task') return h('ul', null, h('li', { cls: 'lbw-task' + (E.done ? ' is-done' : ''), attr: ind }, h('span', { cls: 'lbw-edbox' }), ta));
  if (E.kind === 'quote') return h('blockquote', null, ta);
  if (E.kind === 'raw') return ta;
  return h('p', null, ta);
}
function reshape(E) {
  const a = selStart(E.ta), b = selEnd(E.ta);
  const old = [...E.el.children].find(x => x !== E.bar);
  const nu = shapeEl(E);
  if (old) old.replaceWith(nu); else E.el.append(nu);
  E.el.classList.toggle('is-li', E.kind === 'li' || E.kind === 'task');
  E.el.classList.toggle('is-raw', E.kind === 'raw');
  paintLevel(E);
  E.ta.focus(); try { E.ta.setSelectionRange(a, b); } catch (e) { console.debug(e); }
  autoGrow(E.ta);
}
// openEditor(i)：改第 i 块；openEditor(-1, caret, true, {at, kind, pre, text})：在第 at 行插一块新的（不给 at = 页尾）
function openEditor(i, caret = null, isNew = false, ins = null) {
  const p = editPage(); if (!p || readOnly || UI.src) return;
  // ② 页面在恢复 / 删除这类「整页换掉」的操作里：不开；等队列空了再开，期间正文被换过就不开了——行号会对不上
  if (busyPage(p)) {
    const body0 = p.body;
    p._q.then(() => setTimeout(() => { if (current() === p && p.body === body0 && !ED && !UI.src) openEditor(i, caret, isNew, ins); }, 0));
    return;
  }
  if (ED && ED.p !== p) commitEditor(false);
  if (ED) {
    // 正在改别的段：先收好那段（行号会变），再按变化量找到要开的那段 / 要插的位置
    const E = ED, n0 = p.body.split('\n').length;
    const was = isNew ? null : parseBlocks(p.body).blocks[i];
    commitEditor(true);
    const delta = p.body.split('\n').length - n0;
    if (isNew) return openEditor(-1, caret, true, ins && ins.at != null ? { ...ins, at: ins.at >= E.e ? ins.at + delta : ins.at } : ins);
    if (!was) return;
    const line = was.s >= E.e ? was.s + delta : was.s;
    const k = parseBlocks(p.body).blocks.findIndex(b => b.s === line);
    if (k >= 0) openEditor(k, caret);
    return;
  }
  if (!R.doc) return;
  const { lines, blocks } = parseBlocks(p.body);
  let s, e, src = '', holder = null, shape;
  if (isNew) {
    s = e = Math.max(0, Math.min(ins && ins.at != null ? ins.at : lines.length, lines.length));
    shape = { kind: 'p', pre: '', ...(ins || {}) };
  } else {
    const b = blocks[i]; if (!b) return;
    s = b.s; e = b.e; src = lines.slice(s, e).join('\n'); holder = R.doc.querySelector(`.lbw-blk[data-i="${i}"]`); if (!holder) return;
    UI.lastLine = { page: p.id, line: s };   // 页头「AI」默认改这一节
    shape = shapeOf(b.type, lines[s]);
    if (shape.kind === 'h') { const k = (p._heads || []).findIndex(x => x.line === s); if (k >= 0) shape.hn = String(k + 1); }
  }
  const ta = h('textarea', { cls: 'lbw-ed', attr: { spellcheck: 'false', rows: '1' } });
  const E = { i, s, e, ta, p, kind: 'p', lv: 2, pre: '', ind: '', ord: false, done: false, hn: '', ...shape, cites: new Map(), citeOf: new Map(), isNew };
  delete E.text; delete E.at;
  if (isNew) ta.value = String(shape.text || '').replace(/\]\(lwa:([\w-]+)\)/g, (m, id) => `](${citeToken(E, id)})`);
  else ta.value = toDisplay(E, src);
  ta.placeholder = isNew && !p.body.trim() ? (p.role === 'topic' ? '一句话说说这个文件夹放什么' : '写下第一句：为什么关注这件事？') : '';
  const lv = (t, v) => btn({ text: t, data: { lv: v } });
  const bar = h('div', { cls: 'lbw-edbar' }, lv('正文', 0), lv('H1', 1), lv('H2', 2), lv('H3', 3), h('span', { cls: 'lbw-sep' }), lv('列表', 'ul'), lv('待办', 'task'),
  );
  bar.addEventListener('mousedown', ev => ev.preventDefault());
  for (const x of bar.querySelectorAll('[data-lv]')) x.addEventListener('click', () => setLevel(ta, x.dataset.lv));
  E.bar = bar;
  E.el = h('div', { cls: 'lbw-blk is-editing' }, bar, shapeEl(E));
  E.el.classList.toggle('is-li', E.kind === 'li' || E.kind === 'task');
  E.el.classList.toggle('is-raw', E.kind === 'raw');
  if (holder) holder.replaceWith(E.el);
  else {
    const k = blocks.reduce((acc, b, j) => (b.e <= s ? j : acc), -1);
    const after = k >= 0 ? R.doc.querySelector(`.lbw-blk[data-i="${k}"]`) : null;
    if (after) after.after(E.el); else R.doc.prepend(E.el);
  }
  ED = E;
  ta.addEventListener('input', () => { mdShortcut(E); autoGrow(ta); suggest(ta); });
  ta.addEventListener('keydown', edKey);
  ta.addEventListener('blur', () => setTimeout(() => {
    if (ED !== E || D.activeElement === ta) return;
    if (!ta.isConnected) { stashUnsaved(E.p); return; }   // §5.9：后台把它摘下（换页 / 关页）不提交，只把字留成草稿
    closePop(); commitEditor(true);
  }, 120));
  paintLevel(E);
  autoGrow(ta); ta.focus();
  let pos = ta.value.length;
  if (isNew && shape.text != null) pos = 0;
  else if (caret != null) pos = Math.min(toDisplay({ ...E, cites: new Map(E.cites), citeOf: new Map(E.citeOf) }, src.slice(0, caret)).length, ta.value.length);
  ta.setSelectionRange(pos, pos);
  if (R.add) R.add.hidden = true;
}
function autoGrow(ta) { try { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; } catch (e) { console.debug(e); } }
const selStart = ta => (typeof ta.selectionStart === 'number' ? ta.selectionStart : ta.value.length);
const selEnd = ta => (typeof ta.selectionEnd === 'number' ? ta.selectionEnd : selStart(ta));
function replaceRange(ta, text, a, b) {
  if (typeof ta.setRangeText === 'function') { ta.setRangeText(text, a, b, 'end'); return; }
  ta.value = ta.value.slice(0, a) + text + ta.value.slice(b);
  ta.setSelectionRange(a + text.length, a + text.length);
}
// 工具条 / Ctrl+Alt+0–4：换这一块的样子（只换记号，字不动）
function setLevel(ta, lv) {
  const E = ED; if (!E || E.ta !== ta) return;
  const n = Number(lv);
  if (lv === 'ul') Object.assign(E, { kind: 'li', ord: false, pre: E.ind + '- ' });
  else if (lv === 'task') Object.assign(E, { kind: 'task', done: false, pre: E.ind + '- [ ] ' });
  else if (n >= 1 && n <= 4) Object.assign(E, { kind: 'h', lv: n, pre: '#'.repeat(n) + ' ', hn: '' });
  else Object.assign(E, { kind: E.kind === 'raw' ? 'raw' : 'p', pre: '', ind: '' });
  reshape(E);
}
function paintLevel(E) {
  const on = E.kind === 'h' ? String(E.lv) : E.kind === 'li' ? 'ul' : E.kind === 'task' ? 'task' : E.kind === 'p' ? '0' : '';
  for (const x of E.bar.querySelectorAll('[data-lv]')) x.classList.toggle('is-on', x.dataset.lv === on);
}
// 段落开头打 Markdown 记号就换样子（# 标题、- 列表、1. 编号、[] 待办、> 引用），记号本身不留在框里
function mdShortcut(E) {
  if (E.kind !== 'p' || selStart(E.ta) > 7) return;
  const v = E.ta.value, m = /^(#{1,4} |[-*+] \[[ xX]?\] |\[\] |[-*+] |\d+[.)] |> )/.exec(v);
  if (!m) return;
  const t = m[1];
  if (t[0] === '#') Object.assign(E, { kind: 'h', lv: t.trim().length, pre: t, hn: '' });
  else if (t.includes('[')) Object.assign(E, { kind: 'task', done: false, pre: '- [ ] ' });
  else if (t[0] === '>') Object.assign(E, { kind: 'quote', pre: '' });
  else if (/\d/.test(t)) Object.assign(E, { kind: 'li', ord: true, pre: t });
  else Object.assign(E, { kind: 'li', ord: false, pre: '- ' });
  E.ta.value = v.slice(t.length);
  E.ta.setSelectionRange(0, 0);
  reshape(E);
}
// 把一块的新源码拼回整页正文（不改 p）：{body, start, end, changed}；start / end = 这块现在在第几行（不含补的空行）
// 段落之间补一个空行；列表一条挨着一条不补（补了会变成松散列表）
function spliceBody(body, s, e, value) {
  const lines = body.split('\n');
  const text = String(value).replace(/\s+$/, '');
  const old = lines.slice(s, e).join('\n');
  if (text === old) return { body, start: s, end: e, changed: false };
  const repl = text ? text.split('\n') : [];
  let start = s;
  if (repl.length) {
    // 两行之间要不要空一行：挨着标题不用；列表挨着列表不用；其余（段落 / 列表 / 引用互相挨着）要空——
    // 不空的话 Obsidian 会把段落当成上一条列表的续行
    const listy = l => isListLine(l) || indentOf(l) > 0;
    const gap = (a, b) => a != null && b != null && !!a.trim() && !!b.trim() && !/^#{1,6}\s/.test(a) && !/^#{1,6}\s/.test(b) && !(listy(a) && isListLine(b));
    const before = s > 0 && gap(lines[s - 1], repl[0]) ? [''] : [];
    const after = e < lines.length && gap(repl[repl.length - 1], lines[e]) ? [''] : [];
    lines.splice(s, e - s, ...before, ...repl, ...after);
    start = s + before.length;
  } else {
    lines.splice(s, e - s);
    if (s > 0 && s < lines.length && !lines[s - 1].trim() && !lines[s].trim()) lines.splice(s, 1);
    else if (s === 0 && lines.length && !lines[0].trim()) lines.splice(0, 1);
  }
  return { body: lines.join('\n'), start, end: start + repl.length, changed: true };
}
const intendedBody = p => (ED && ED.p === p ? spliceBody(p.body, ED.s, ED.e, fromDisplay(ED, ED.ta.value)).body : p.body);
// 收起编辑框：拼回正文（改了就经 mutate 存一次）；返回这块现在的位置 {start, end, empty}
function commitEditor(rerender = true) {
  if (!ED) return null;
  const E = ED, { p, ta } = E;
  const r = spliceBody(p.body, E.s, E.e, fromDisplay(E, ta.value));
  ED = null; closePop();
  if (r.changed) mutate(p, n => { n.body = r.body; });
  UI.caret = { page: p.id, abs: Math.min(lineOffset(r.body.split('\n'), r.start) + selStart(ta), r.body.length) };
  if (rerender) renderKeepScroll(); else E.el.remove();
  refreshIfStale(p);
  return { start: r.start, end: r.end, empty: r.start === r.end };
}
// 走到相邻的一块：dir -1 = 上一块（光标放末尾），+1 = 下一块（光标放开头）
function openNeighbor(p, loc, dir) {
  const blocks = parseBlocks(p.body).blocks;
  if (dir < 0) { let k = -1; blocks.forEach((b, j) => { if (b.e <= loc.start) k = j; }); if (k >= 0) openEditor(k, null); }
  else { const k = blocks.findIndex(b => b.s >= loc.end); if (k >= 0) openEditor(k, 0); }
}
function edKey(ev) {
  if (POP.el && popKey(ev)) return;
  if (ev.isComposing || ev.keyCode === 229) return;   // 输入法正在选字：回车 / 退格都归输入法
  const E = ED; if (!E) return;
  const ta = E.ta, k = String(ev.key || '');
  const at0 = selStart(ta) === 0 && selEnd(ta) === 0, atEnd = selStart(ta) === ta.value.length;
  if (ev.ctrlKey && ev.altKey && /^[0-4]$/.test(k)) { ev.preventDefault(); setLevel(ta, k); return; }
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && k.toLowerCase() === 'z') { ev.stopPropagation(); return; }   // 框里的撤销归框
  if (k === 'Escape') { ev.preventDefault(); ev.stopPropagation(); commitEditor(true); return; }
  const ctrlEnter = k === 'Enter' && (ev.ctrlKey || ev.metaKey);
  if (ctrlEnter || (k === 'Enter' && !ev.shiftKey && !ev.altKey && E.kind !== 'raw' && E.kind !== 'quote')) {
    ev.preventDefault();
    if (!ctrlEnter && (E.kind === 'li' || E.kind === 'task') && !ta.value.trim()) { setLevel(ta, 0); return; }   // 空的一条再回车 = 结束列表
    const rest = ctrlEnter ? '' : untoken(E, ta.value.slice(selEnd(ta)));
    if (!ctrlEnter) ta.value = ta.value.slice(0, selStart(ta));
    const next = ctrlEnter ? { kind: 'p', pre: '' } : nextShape(E);
    const loc = commitEditor(true);
    if (loc) openEditor(-1, 0, true, { ...next, at: loc.end, text: rest });
    return;
  }
  if (k === 'Backspace' && at0) {
    if (E.kind !== 'p' && E.kind !== 'raw') { ev.preventDefault(); setLevel(ta, 0); return; }   // 开头退格 = 去掉标题 / 列表记号
    if (!ta.value) { ev.preventDefault(); const p = E.p, loc = commitEditor(true); if (loc) openNeighbor(p, loc, -1); }
    return;
  }
  if (k === 'Tab' && (E.kind === 'li' || E.kind === 'task')) {
    ev.preventDefault();
    const ind = ev.shiftKey ? E.ind.slice(2) : E.ind + '  ';
    E.pre = ind + E.pre.slice(E.ind.length); E.ind = ind;
    reshape(E); return;
  }
  if ((k === 'ArrowUp' && at0) || (k === 'ArrowDown' && atEnd && !POP.el)) {
    ev.preventDefault();
    const p = E.p, loc = commitEditor(true);
    if (loc) openNeighbor(p, loc, k === 'ArrowUp' ? -1 : 1);
  }
}
function toggleTask(p, line) {
  if (ED && ED.p === p) { commitEditor(true); return; }   // 先存好正在改的那一段（行号会变），再勾
  if (busyPage(p)) return;
  mutate(p, n => {
    const lines = n.body.split('\n');
    if (lines[line] != null) lines[line] = lines[line].replace(/\[( |x|X)\]/, m => (m === '[ ]' ? '[x]' : '[ ]'));
    n.body = lines.join('\n');
  });
  renderKeepScroll();
}

// ═════════════ @ 引用收藏 ═════════════
const POP = { el: null, items: [], on: 0, ta: null, from: 0 };
function closePop() { if (POP.el) POP.el.remove(); POP.el = null; POP.ta = null; }
// 弹层 position:fixed：Obsidian 某层祖先若有 contain / transform，fixed 会相对它算——放好后量一次，差多少挪回多少
function placeFixed(el, x, y) {
  el.style.left = x + 'px'; el.style.top = y + 'px';
  try { const r = el.getBoundingClientRect(); if (r && (r.left || r.top) && (Math.abs(r.left - x) > 1 || Math.abs(r.top - y) > 1)) { el.style.left = (2 * x - r.left) + 'px'; el.style.top = (2 * y - r.top) + 'px'; } }
  catch (e) { console.debug(e); }
}
function citeTitle(it) { return String(it.title || '未命名收藏').replace(/[\[\]\n]/g, ' ').trim(); }
function suggest(ta) {
  const before = ta.value.slice(0, selStart(ta));
  const m = /(^|[\s（(，。：:；])@([^\s@]*)$/.exec(before);
  if (!m) { closePop(); return; }
  const cur = ED ? ED.p : current(), q = m[2];
  let pool;
  if (q) { const r = rankItems(ITEMS, q, DATA.pinyin_chars || {}, DATA.aliases || []); pool = [...r.exact, ...r.possible].map(x => x.it); }
  else pool = ITEMS.filter(it => cur && (it.tags || []).some(t => cur._allTags.includes(t)));
  let list = pool.slice(0, 6).map(it => { const used = citedBy(it.id); return { id: it.id, title: citeTitle(it), sub: `${itemType(it)}${it.author ? ' · ' + it.author : ''}${used.length ? ' · 已在《' + used[0].title + '》引用' : ''}` }; });
  if (!list.length) list = [{ id: '', title: '收藏里没找到', sub: '', off: true }];
  closePop();
  const el = h('div', { cls: 'lbw-pop is-sug', attr: { role: 'listbox' } },
    h('div', { cls: 'lbw-ph' }, h('span', { cls: 'lbw-kick', text: 'ARCHIVE' }), h('span', { cls: 'lbw-cap', text: q ? '从收藏里引用' : '和本页标签相关 · 接着打字搜' }), q ? h('span', { cls: 'lbw-q', text: '@' + q }) : null),
    list.map((x, k) => { const b = btn({ cls: k === 0 && !x.off ? 'is-on' : '', data: { k }, attr: { disabled: !!x.off } }, x.title, x.sub ? h('small', { text: x.sub }) : null); b.addEventListener('click', () => pickPop(k)); return b; }),
    h('div', { cls: 'lbw-pf' }, h('span', { text: '↑↓ 选' }), h('span', { text: 'Enter 插入，接着写一句为什么' }), h('span', { text: 'Esc 关' })));
  el.addEventListener('mousedown', e => e.preventDefault());
  R.layer.append(el);
  const r = ta.getBoundingClientRect();
  const vw = (WIN && WIN.innerWidth) || 1200, vh = (WIN && WIN.innerHeight) || 800;
  const below = r.top + 28 + before.split('\n').length * 30 + 6, ph = el.offsetHeight || 0;
  placeFixed(el, Math.max(8, Math.min(r.left + 12, vw - 392)), below + ph <= vh - 8 ? below : Math.max(8, r.top - ph - 14));
  Object.assign(POP, { el, items: list, on: 0, ta, from: m.index + m[1].length });
}
function popKey(ev) {
  const k = ev.key;
  if (!POP.ta) return false;   // 菜单弹层：只管 Esc（全局那条）
  if (k === 'ArrowDown' || k === 'ArrowUp') { ev.preventDefault(); POP.on = (POP.on + (k === 'ArrowDown' ? 1 : -1) + POP.items.length) % POP.items.length; POP.el.querySelectorAll('button').forEach((b, i) => b.classList.toggle('is-on', i === POP.on)); return true; }
  if (k === 'Enter' || k === 'Tab') { ev.preventDefault(); pickPop(POP.on); return true; }
  if (k === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closePop(); return true; }
  return false;
}
function pickPop(k) {
  const x = POP.items[k], ta = POP.ta; if (!x || x.off || !ta) return;
  const ref = ED && ED.ta === ta ? citeToken(ED, x.id) : 'lwa:' + x.id;   // 编辑框里显示短号 @1，存的时候换回完整 id
  replaceRange(ta, `[${x.title}](${ref}) — `, POP.from, selStart(ta));
  closePop(); autoGrow(ta); ta.focus();
}

// ═════════════ 收藏引用：开到右栏（和问收藏同一个 openArchiveSource） ═════════════
function markOpenCite() { for (const a of wrap.querySelectorAll('.lbw-cite')) a.classList.toggle('is-open', !!UI.openCite && citeKey(a.dataset.item) === UI.openCite); }
function openCite(id) {
  const it = resolveItem(id);
  if (!it) { LB.say('这篇收藏找不到了（可能进了回收站）：正文里的引用留着标题，标成虚线', { kind: 'warn' }); return null; }
  if (!it.note) { LB.say('这篇收藏没有笔记文件，打不开原文', { kind: 'warn' }); return null; }
  UI.openCite = it.id; markOpenCite();
  const p = provider();
  const fail = e => LB.say('打不开原文：' + errText(e), { kind: 'error' });
  try {
    if (p && typeof p.openArchiveSource === 'function') return Promise.resolve(p.openArchiveSource(it.note, LB.container, false, [])).catch(fail);
    return Promise.resolve(app.workspace.openLinkText(LB.path(it.note), '', false)).catch(fail);
  } catch (e) { fail(e); return null; }
}

// ═════════════ 写盘：只经插件 wikiCall（§1：写盘成功才算；失败回滚 + 草稿 + 固定句式） ═════════════
// 10-29 三审后重写成一个小状态机（之前一路打补丁的竞态，都出在「保存在路上时页面还能改」和「重画时顺手存一次」）：
//  ① 每页一条串行队列：保存 / 恢复 / 覆盖 / 存版本 / 删除都是队列里的一项（enqueue），没有旁路。
//  ② 队列里有东西（busyPage）时这页只读：块编辑框不开（点了等队列空了再开；期间页面被换过就不开），整页 Markdown 框只读，
//     标题 / 标签 / 待办 / 拖动都不收。所以带内容的保存只在页面空闲时入队（mutate 是唯一入口），队列里最多一项，
//     不会有「排在别的操作后面、轮到时拿新 hash 盖掉别处版本 / 恢复内容」的保存。
//  ③ 要写的内容在入队那一刻定下（用户到此为止打的字：mutate 把开着的编辑框 / 整页 Markdown 框的字一并收进来）；
//     之后不再从界面上补收。恢复 / 存版本 / 删除不带内容，参数（hash）在轮到时取。
//  ④ 重画只画不存。存只发生在明确的提交点：Esc / 失焦 / 换页 / 整页 Markdown 的自动保存（框活着、没冻住时）。
//     重画时万一还有没提交的字（不该发生），收进草稿，不存也不丢。
//  ⑤ 保存失败：这一项的内容进草稿（新的顶掉旧的）；CONFLICT 换成磁盘上的版本，其它回到上次存上的样子；队列空了照常能改。
//  ⑥ 覆盖 = 一份正文（编辑框里有用户新打的字就用它，否则用草稿）入队一次保存；只有这一次存上才删草稿。
async function wcall(op, opts = {}) {
  const p = provider();
  if (LB.mobile || !p || typeof p.wikiCall !== 'function') throw Object.assign(new Error(LB.mobile ? LB.MOBILE_ONLY_TEXT : '插件没启用，Wiki 只能看'), { code: 'NO_PLUGIN' });
  return p.wikiCall(op, opts);
}
const NOT_SAVED = '没保存上，内容还在，可重试：';
const stateOf = p => ({ title: p.title, tags: [...p.tags], body: p.body, ...(p.role === 'topic' ? { order: [...(p.order || [])] } : {}) });
// 10-31：只有「整页换掉」的操作（恢复 / 删除）锁页（_hard）；普通保存在后台排队、不锁——以前每存一次这页就只读 1.5 秒，Enter 下一段要干等
const busyPage = p => !!p && (p._hard || 0) > 0;
const savingPage = p => !!p && (p._ops || 0) > 0;
const liveSrc = p => (p && UI.src && UI.view === 'page' && UI.id === p.id && R.srcEd && R.srcEd.isConnected && !R.srcEd._lbDead ? R.srcEd : null);
function closeEditor() { if (!ED) return; const { el } = ED; ED = null; closePop(); el?.remove(); }
// ① 队列：task 自己处理成功 / 失败（不抛）；队列空了 settled
function enqueue(p, task, { hard = false } = {}) {
  p._ops = (p._ops || 0) + 1; if (hard) p._hard = (p._hard || 0) + 1;
  paintLock(p); paintSaved(p);
  const job = (p._q || Promise.resolve()).then(task).catch(e => console.debug('[lb] wiki op', e))
    .then(() => { p._ops = Math.max(0, (p._ops || 1) - 1); if (hard) p._hard = Math.max(0, (p._hard || 1) - 1); if (!p._ops) settled(p); });
  p._q = job;
  return job;
}
// 队列空了：解冻（整页 Markdown 框内容没被换就原地解冻）；正文被换过（恢复 / 冲突 / 失败回滚：_repaint）才重画——
// 普通保存不重画（用户可能正在标题 / 标签框里打字）；只画不存；期间磁盘变过就补一次重读
function settled(p) {
  paintLock(p); paintSaved(p);
  if (current() === p && !ED) {
    const box = liveSrc(p);
    if (box && box.value === p.body) { box.readOnly = false; p._repaint = false; }
    else if (p._repaint || box) { p._repaint = false; renderKeepScroll(); }
  }
  if (p._stale) scheduleRefresh(50);
  if (UI.hist && UI.hist.id === p.id && UI.hist.versions) loadHistory();
}
function paintLock(p) {
  if (readOnly || current() !== p) return;
  const lock = busyPage(p);
  wrap.classList.toggle('is-saving', lock);
  if (R.title) R.title.readOnly = lock;
  if (lock && R.srcEd && !R.srcEd._lbDead) R.srcEd.readOnly = true;
  for (const cb of R.center.querySelectorAll('.lbw-task input')) cb.disabled = lock;
}
// ② ③ 带内容的改动的唯一入口：change(next) 在「这一页现在的样子 + 用户编辑框里还没提交的字」上改；
// 页面没在「整页换掉」就照改、排一次保存（10-31 起普通保存不锁页）；在换的话进草稿（不丢）。每次改之前的样子记进撤销栈（Ctrl+Z）
const UNDO = new Map();
function pushUndo(p) { const st = UNDO.get(p.id) || []; st.push({ title: p.title, tags: [...p.tags], body: p.body, ...(p.role === 'topic' ? { order: [...(p.order || [])] } : {}) }); if (st.length > 60) st.shift(); UNDO.set(p.id, st); }
function undoPage(p) {
  const st = p && UNDO.get(p.id);
  if (!st || !st.length) { LB.say('没有可以撤销的了（更早的改动在「历史」里）'); return; }
  const prev = st.pop();
  if (mutate(p, n => Object.assign(n, prev), { note: '撤销', undo: false })) { renderKeepScroll(); LB.say('撤销了上一步'); }
  else st.push(prev);
}
function mutate(p, change, { kind = 'auto', note = '', undo = true } = {}) {
  if (readOnly || !p) return false;
  const next = stateOf(p);
  if (ED && ED.p === p) { next.body = intendedBody(p); closeEditor(); }
  const box = liveSrc(p);
  if (box && !box.readOnly && box.value !== next.body) next.body = box.value;
  change(next);
  if (busyPage(p)) {
    DRAFTS[p.id] = { ...next, at: Date.now(), conflict: false };
    persistDrafts();
    LB.say('这一页正在保存：这次的改动先放在页顶「没保存上的改动」里', { kind: 'warn' });
    return false;
  }
  if (undo) pushUndo(p);
  Object.assign(p, next); derive(p); reindex();
  saveNow(p, { kind, note });
  return true;
}
// 保存：排进这页的队列；还没轮到的那次普通保存就不再另排（轮到时存的是那一刻的最新内容）
function saveNow(p, { kind = 'auto', note = '', fromDraft = null } = {}) {
  if (kind === 'auto' && !fromDraft && p._pendingSave) return p._pendingSave;
  let ok = false, job = null;
  job = enqueue(p, async () => {
    if (p._pendingSave === job) p._pendingSave = null;
    const want = stateOf(p);
    try {
      const res = await wcall('save', { input: { id: p.id, base_hash: p.hash || '', ...want, kind, note } });
      applySaved(p, res.page);
      if (fromDraft && DRAFTS[p.id] === fromDraft) { delete DRAFTS[p.id]; persistDrafts(); p._repaint = true; }   // 草稿条要收起
      scheduleIndex(); ok = true;
    } catch (e) { await saveFailed(p, want, e); }
  }).then(() => ok);
  if (kind === 'auto' && !fromDraft) p._pendingSave = job;
  return job;
}
function applySaved(p, page) {
  if (!page || typeof page !== 'object') return;
  for (const k of ['hash', 'updated', 'created', 'file', 'role', 'index_tag']) if (page[k] != null) p[k] = page[k];
  if (page.id && page.id !== p.id) { PAGES.delete(p.id); p.id = page.id; PAGES.set(p.id, p); }
  delete p.adopted;
  p._saved = { title: page.title ?? p.title, tags: [...(page.tags || p.tags)], body: page.body ?? p.body, order: [...(page.order || p.order || [])] };
  p._stale = false;
  reindex(); renderSub();
  if (UI.view === 'page' && UI.id === p.id) renderToc();
}
function revertTo(p, s) { p.title = s.title; p.tags = [...s.tags]; p.body = s.body; if (p.role === 'topic') p.order = [...(s.order || [])]; derive(p); }
async function reloadPage(p) {
  const saved = p._saved || savedOf(p);
  p._repaint = true;
  try { const d = (await readDisk()).get(p.id); if (d) adoptDisk(p, d); else revertTo(p, saved); }
  catch (err) { console.debug('[lb] wiki reload after conflict', err); revertTo(p, saved); }
}
// ⑤ 失败：这一项的内容进草稿；CONFLICT 换成磁盘版本，其它回到上次存上的样子（重画等队列空了在 settled 里做）
async function saveFailed(p, want, e) {
  const code = (e && e.code) || '';
  const saved = p._saved || savedOf(p);
  // 草稿要的是用户现在手上的全部（这次要存的 + 之后又改的 + 编辑框里还没收的字）；编辑框关掉（正文要换了，行号对不上）
  const box = liveSrc(p);
  const latest = { ...stateOf(p), body: box && !box.readOnly ? box.value : intendedBody(p) };
  if (ED && ED.p === p) closeEditor();
  if (box) box._lbDead = true;   // 框里的字已经在草稿里；正文要换了，这个框不再拿去存
  const draft = { ...want, ...latest, at: Date.now(), conflict: code === 'CONFLICT' };
  p._repaint = true;
  if (code === 'TITLE_TAKEN') draft.title = saved.title;
  const keep = !sameState(draft, { ...saved, order: p.role === 'topic' ? saved.order : undefined });
  if (keep) { DRAFTS[p.id] = draft; persistDrafts(); }
  // 冲突重读磁盘那一会儿锁页（待办 / 标题不收）：重读完之前的改动会被磁盘版本换掉，不能让它看起来存上了
  if (code === 'CONFLICT') { p._hard = (p._hard || 0) + 1; paintLock(p); try { await reloadPage(p); } finally { p._hard = Math.max(0, p._hard - 1); } }
  else revertTo(p, saved);
  reindex(); renderSub(); renderToc();
  const why = code === 'CONFLICT' ? '这页刚在别处改过（Obsidian 或另一个窗口），已换成磁盘上的版本；你的改动在页顶「没保存上的改动」里'
    : code === 'TITLE_TAKEN' ? errText(e) + '；标题已改回原来的' : errText(e);
  LB.say(NOT_SAVED + why, { kind: 'error', actions: keep ? [{ label: code === 'CONFLICT' ? '用我这份覆盖' : '再存一次', run: () => overwrite(p.id) }] : [] });
}
// 把还没提交的字留成草稿（编辑框被后台摘下 / 重画时还开着）：不存，也不丢
function stashUnsaved(p) {
  if (!p) return;
  const next = stateOf(p);
  if (ED && ED.p === p) next.body = intendedBody(p);
  const box = liveSrc(p);
  if (box && !box.readOnly) next.body = box.value;
  if (next.body === p.body) return;
  DRAFTS[p.id] = { ...next, at: Date.now(), conflict: false, unsaved: true };
  persistDrafts();
}
// ⑥ 覆盖：一份正文、一次保存；只有这次存上才删草稿
function overwrite(id) {
  const p = PAGES.get(id), d = DRAFTS[id];
  if (!p || !d) { LB.say('这份改动对应的页找不到了', { kind: 'warn' }); return; }
  if (readOnly) return;
  if (busyPage(p)) { LB.say('这一页正在保存，好了再点', { kind: 'warn' }); return; }
  let body = d.body ?? p.body;
  if (ED && ED.p === p) { const typed = intendedBody(p); closeEditor(); if (typed !== p.body) body = typed; }
  const box = liveSrc(p);
  if (box) { if (!box.readOnly && box.value !== p.body) body = box.value; box._lbDead = true; }
  p.title = d.title ?? p.title; p.tags = [...(d.tags || p.tags)]; p.body = body; if (p.role === 'topic' && d.order) p.order = [...d.order];
  derive(p); reindex();
  saveNow(p, { note: d.conflict ? '用没保存上的改动覆盖' : '', fromDraft: d });
  if (current() === p) renderKeepScroll();
}
// 恢复 / 存版本 / 删除之前：用户手上的字先作为一次普通保存入队（③）
function commitHere(p) { if (ED && ED.p === p) commitEditor(true); else flushSrc(); }
function draftBar(p) {
  const d = DRAFTS[p.id];
  if (!d) return null;
  const n = String(d.body || '').replace(/\s/g, '').length;
  const bar = h('div', { cls: 'lbw-draft', attr: { role: 'status' } },
    h('span', { cls: 'lbw-dt', text: d.unsaved ? '上次没提交的改动' : '没保存上的改动' }),
    h('span', null, nums(`${fmtTime(new Date(d.at).toISOString())} · ${n} 字`)),
    d.conflict ? h('span', { text: '这页在别处改过；覆盖后，被换下的那版留在历史里' }) : null,
    h('span', { cls: 'lbw-sp' }));
  if (!readOnly) bar.append(btn({ cls: 'lbw-pill is-solid', text: d.conflict ? '用我这份覆盖' : '再存一次', data: { draft: 'apply' }, on: { click: () => overwrite(p.id) } }));
  bar.append(btn({ cls: 'lbw-qbtn', text: '复制', data: { draft: 'copy' }, on: { click: async () => {
    try { await WIN.navigator.clipboard.writeText(d.body || ''); LB.say('已复制这份改动的正文', { kind: 'ok' }); }
    catch (e) { LB.say('没复制上：' + errText(e), { kind: 'error' }); }
  } } }));
  bar.append(btn({ cls: 'lbw-qbtn', text: '丢掉', data: { draft: 'drop' }, on: { click: async () => {
    if (!(await LB.confirm({ title: '丢掉这份没保存上的改动？', body: '丢掉后找不回来。', ok: '丢掉', danger: true }))) return;
    if (DRAFTS[p.id] === d) { delete DRAFTS[p.id]; persistDrafts(); }
    if (!ED) renderKeepScroll();
  } } }));
  return bar;
}
let indexTimer = 0;
function scheduleIndex() {
  clearTimeout(indexTimer);
  indexTimer = setTimeout(async () => {
    try { await wcall('index', {}); }
    catch (e) { LB.say('Wiki 索引没更新上（页面本身已经存好）：' + errText(e), { kind: 'warn' }); }
  }, INDEX_DELAY_MS);
}

// ═════════════ 历史（本页右侧栏）：版本列表 · 和现在的逐行差异 · 恢复 · 保存版本 ═════════════
const KIND = { create: '新建', auto: '自动', manual: '版本', restore: '恢复', external: '外部编辑', import: '导入', ai: 'AI', rename: '改名' };
function toggleHistory() {
  if (UI.hist) { UI.hist = null; renderSide(); return; }
  if (UI.ai && UI.ai.scope === 'page') UI.ai = null;
  UI.trash = null;
  const p = current();
  if (!p) { LB.say('先打开一页，再看它的历史'); return; }
  UI.hist = { id: p.id, versions: null, sel: null, texts: {} };
  renderSide(); loadHistory();
}
let histGen = 0;
async function loadHistory() {
  const H = UI.hist; if (!H || !H.id) { renderSide(); return; }
  const gen = ++histGen;
  try {
    const r = await wcall('history', { args: [H.id] });
    if (gen !== histGen || UI.hist !== H) return;
    H.versions = Array.isArray(r?.versions) ? r.versions : []; H.error = '';
  } catch (e) { if (gen !== histGen || UI.hist !== H) return; H.versions = H.versions || []; H.error = errText(e); }
  renderSide();
}
async function pickVersion(ver) {
  const H = UI.hist; if (!H) return;
  H.sel = ver; renderSide();
  if (H.texts[ver]) return;
  try { const r = await wcall('version', { args: [H.id, String(ver)] }); if (UI.hist === H) { H.texts[ver] = r?.version || { body: '' }; renderSide(); } }
  catch (e) { if (UI.hist === H) { H.texts[ver] = { error: errText(e) }; renderSide(); } }
}
function lineDiff(a, b) {
  const A = String(a).split('\n'), B = String(b).split('\n'), n = A.length, m = B.length;
  if (n * m > 4e6) return [...A.map(l => ['d', l]), ...B.map(l => ['a', l])];
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) { if (A[i] === B[j]) { out.push(['c', A[i]]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(['d', A[i++]]); else out.push(['a', B[j++]]); }
  while (i < n) out.push(['d', A[i++]]); while (j < m) out.push(['a', B[j++]]);
  return out;
}
function renderSide() {
  const H = UI.hist, side = R.side, T = UI.trash;
  const on = !!(H || T);
  wrap.classList.toggle('has-side', on);
  if (R.histBtn) R.histBtn.classList.toggle('is-on', !!H);
  side.hidden = !on; side.textContent = '';
  if (T) { renderTrashSide(side); return; }
  if (!H) return;
  const p = PAGES.get(H.id);
  side.append(h('div', { cls: 'lbw-rbar' }, btn({ text: '← 收起', on: { click: () => { UI.hist = null; renderSide(); } } }), h('span', { cls: 'is-on', text: '历史' }), h('span', { text: p ? p.title : '' })));
  if (!p) { side.append(h('p', { cls: 'lbw-note', text: '这一页找不到了。' })); return; }
  const noteIn = h('input', { attr: { type: 'text', placeholder: '这一版改了什么（可不写）' } });
  const saveVer = btn({ cls: 'lbw-pill', text: '保存版本', on: { click: async () => {
    const done = LB.busy(saveVer, '保存中…');
    if (ED && ED.p === p) commitEditor(true);
    const ok = await saveVersion(p, noteIn.value.trim() || '手动保存');
    done();
    if (ok) { LB.say('记了一版', { kind: 'ok' }); H.sel = null; loadHistory(); }
  } } });
  side.append(h('div', { cls: 'lbw-verbar' }, h('label', { cls: 'lb-visually-hidden', text: '这一版的说明' }), noteIn, saveVer));
  if (H.error) side.append(h('p', { cls: 'lbw-note', text: '历史没读到：' + H.error }));
  if (!H.versions) { side.append(h('p', { cls: 'lbw-note', text: '正在读历史…' })); return; }
  if (!H.versions.length) side.append(h('p', { cls: 'lbw-note', text: '还没有历史：存一次就有了' }));
  for (const v of H.versions) {
    side.append(btn({ cls: 'lbw-ver' + (H.sel === v.ver ? ' is-on' : ''), data: { ver: v.ver }, on: { click: () => pickVersion(v.ver) } },
      h('span', { cls: 'lbw-k', text: KIND[v.kind] || v.kind || '' }), h('span', null, nums(fmtTime(v.at))),
      h('span', { cls: 'lbw-note' }, v.add || v.del ? nums(`+${v.add || 0} −${v.del || 0}`) : null), v.note ? h('span', { cls: 'lbw-w', text: v.note }) : null));
  }
  if (H.sel != null) {
    const t = H.texts[H.sel];
    if (!t) side.append(h('p', { cls: 'lbw-note', text: '正在读这一版…' }));
    else if (t.error) side.append(h('p', { cls: 'lbw-note', text: '这一版没读到：' + t.error }));
    else {
      const d = lineDiff(t.body || '', p.body);
      const changed = d.some(x => x[0] !== 'c') || (t.title != null && t.title !== p.title);
      if (!changed) side.append(h('p', { cls: 'lbw-note', text: '和现在一样' }));
      else {
        side.append(h('div', { cls: 'lbw-diff' }, d.map(([k, l]) => h('div', { cls: 'is-' + k, text: (k === 'a' ? '+ ' : k === 'd' ? '− ' : '  ') + (l || ' ') }))));
        const rb = btn({ cls: 'lbw-pill', text: '恢复到这一版', data: { restore: H.sel }, on: { click: () => restoreVersion(p, H.sel, rb) } });
        side.append(rb, ' ', h('span', { cls: 'lbw-note', text: '恢复也记成新的一版' }));
      }
    }
  }
  side.append(h('p', { cls: 'lbw-note', attr: { style: 'margin-top:22px' }, text: '连着打字每 2 分钟合成一次自动快照；「保存版本」单独记一条。历史存在 PersonalWiki/.history 里。' }));
}
// 恢复 / 存版本：队列里的一项（①），不带内容，hash 在轮到时取；用户手上的字先作为一次普通保存入队（③）
function restoreVersion(p, ver, b) {
  if (readOnly) return null;
  commitHere(p);
  const done = LB.busy(b, '恢复中…');
  return enqueue(p, async () => {
    try {
      const r = await wcall('restore', { args: [p.id, String(ver), '--base-hash', p.hash || ''] });
      const pg = r && r.page;
      if (pg) { pushUndo(p); p.title = pg.title ?? p.title; p.tags = [...(pg.tags || p.tags)]; if (pg.body != null) p.body = pg.body; derive(p); applySaved(p, pg); p._repaint = true; }
      LB.say((r && r.message) || '已恢复；恢复前的内容也在历史里', { kind: 'ok' });
      scheduleIndex();
      if (UI.hist) UI.hist.sel = null;
    } catch (e) {
      if (e && e.code === 'CONFLICT') { await reloadPage(p); LB.say('没恢复上：这页刚在别处改过，已换成磁盘上的版本，再点一次恢复', { kind: 'error' }); }
      else LB.say('没恢复上：' + errText(e), { kind: 'error' });
    } finally { done(); }
  }, { hard: true });
}
function saveVersion(p, note) {
  if (readOnly) return Promise.resolve(false);
  commitHere(p);
  let ok = false;
  return enqueue(p, async () => {
    try { const res = await wcall('save', { input: { id: p.id, base_hash: p.hash || '', kind: 'manual', note } }); applySaved(p, res.page); scheduleIndex(); ok = true; }
    catch (e) {
      if (e && e.code === 'CONFLICT') { await reloadPage(p); LB.say('版本没记上：这页刚在别处改过，已换成磁盘上的版本', { kind: 'error' }); }
      else LB.say('版本没记上：' + errText(e), { kind: 'error' });
    }
  }).then(() => ok);
}

// ═════════════ 让 AI 改（10-31 晚重做，作者：「ai 是对 wiki 整体改，不是单行。还有选中段落不方便」） ═════════════
// 范围：编辑时点「AI 改」= 光标所在的那一节（上一个小标题到下一个同级小标题）；页面上拖选了字 = 选中的那几段（浮出「AI 改选中的」）；
//   「…→让 AI 改整页」= 整页（右侧栏）。范围里的段在等 / 看的时候锁住不让改。
// 结果：按字 / 词比（中文按字、英文按词，先按行对齐再细比），每一处改动单独勾选，「用选中的」一次拼好经 pwiki save（kind=ai）存——一步 Ctrl+Z 能撤；
//   回来时那截原文在页里找不到了（别处改过它）就作废，不套用。模型 = 插件设置里的文本 AI；提示词在 link_brain/wiki_ai.py（<replacement> 外框）。
const AI_PRESETS = {
  // 1101 作者：选择太多了——每种最多 3 个，用 | 隔开（「搭个框架」和顶上「按我的思路搭框架」重复，去掉）；别的说法在下面输入框自己说
  part: [['polish', '润色'], ['concise', '精简'], ['expand', '说清楚一点']],
  page: [['structure', '理顺结构'], ['concise', '精简'], ['from_cites', '从引用补要点']],
};
const aiRecent = () => { try { const v = typeof app.loadLocalStorage === 'function' ? app.loadLocalStorage('lb-wiki-ai-recent') : null; return Array.isArray(v) ? v.filter(x => typeof x === 'string').slice(0, 6) : []; } catch (e) { return []; } };
function rememberAsk(text) {
  const t = String(text || '').trim(); if (!t) return;
  try { if (typeof app.saveLocalStorage === 'function') app.saveLocalStorage('lb-wiki-ai-recent', [t, ...aiRecent().filter(x => x !== t)].slice(0, 6)); } catch (e) { console.debug('[lb] wiki ai recent', e); }
}
// 第 line 行所在的那一节：上一个小标题（含）到下一个同级或更高的小标题（不含）；前面没有小标题 = 页首到第一个小标题；去掉末尾空行
function sectionRange(p, line) {
  const lines = p.body.split('\n'), heads = (p._heads || []).filter(x => x.line <= lines.length);
  let s = 0, lv = 0;
  for (const x of heads) if (x.line <= line) { s = x.line; lv = x.level; }
  const next = heads.find(x => x.line > Math.max(s, line - 1) && x.line > s && (!lv || x.level <= lv));
  let e = next ? next.line : lines.length;
  if (!lv && heads.length && heads[0].line > line) e = heads[0].line;
  while (e > s && !lines[e - 1].trim()) e--;
  const head = heads.find(x => x.line === s);
  return { start: s, end: e, what: head ? `「${head.text}」这一节` : '开头这一节' };
}
// 在页里重新找那截原文（期间别处加删了行，行号会挪）：离原来位置最近的那一处；找不到 = 原文被改了
function relocate(A, p) {
  if (A.scope === 'page') return p.body === A.text ? { start: 0, end: p.body.split('\n').length } : null;
  const lines = p.body.split('\n'), want = A.text.split('\n'), n = want.length;
  let best = null;
  for (let k = 0; k + n <= lines.length; k++) {
    if (lines[k] !== want[0]) continue;
    if (lines.slice(k, k + n).join('\n') !== A.text) continue;
    if (best == null || Math.abs(k - A.start) < Math.abs(best - A.start)) best = k;
  }
  return best == null ? null : { start: best, end: best + n };
}
const aiLocked = (p, b) => { const A = UI.ai; if (!A || A.id !== p.id) return false; if (A.scope === 'page') return true; return b.s < A.end && b.e > A.start; };
function openAiPart(p, start, end, what) {
  if (readOnly || !p) return;
  const text = p.body.split('\n').slice(start, end).join('\n');
  if (!text.trim()) { LB.say('这一截是空的，先写一点再让 AI 改'); return; }
  UI.ai = { scope: 'part', id: p.id, start, end, text, what, state: 'ask', ask: '' };
  showAi();
}
// 编辑时工具条上的「AI 改」：先收好正在改的这段，再取它所在的那一节
function aiFromEditor() {
  const E = ED; if (!E) return;
  const p = E.p, loc = commitEditor(false);
  const r = sectionRange(p, loc ? loc.start : E.s);
  openAiPart(p, r.start, r.end, r.what);
}
// 页面上拖选了字：浮一个「AI 改选中的」，范围 = 选区碰到的那几段
function selectedRange() {
  const sel = WIN && typeof WIN.getSelection === 'function' ? WIN.getSelection() : null;
  if (!sel || sel.isCollapsed || !R.doc || !sel.anchorNode || !sel.focusNode) return null;
  const blk = n => { const el = n.nodeType === 1 ? n : n.parentElement; return el && el.closest ? el.closest('.lbw-blk[data-i]') : null; };
  const a = blk(sel.anchorNode), b = blk(sel.focusNode);
  if (!a || !b || !R.doc.contains(a) || !R.doc.contains(b)) return null;
  const p = current(); if (!p) return null;
  const blocks = parseBlocks(p.body).blocks, i = Math.min(+a.dataset.i, +b.dataset.i), j = Math.max(+a.dataset.i, +b.dataset.i);
  if (!blocks[i] || !blocks[j]) return null;
  return { p, start: blocks[i].s, end: blocks[j].e, what: i === j ? '选中的这一段' : `选中的 ${j - i + 1} 段` };
}
function hideSelAi() { if (R.selAi) { R.selAi.remove(); R.selAi = null; } }
function showSelAi() {
  hideSelAi();
  if (readOnly || ED || UI.view !== 'page' || UI.ai) return;
  const r = selectedRange(); if (!r) return;
  let rect = null; try { rect = WIN.getSelection().getRangeAt(0).getBoundingClientRect(); } catch (e) { rect = null; }
  const b = btn({ cls: 'lbw-selai', text: 'AI 改' + r.what.replace(/^选中的/, '选中的'), on: { mousedown: e => e.preventDefault(), click: () => { hideSelAi(); openAiPart(r.p, r.start, r.end, r.what); } } });
  R.layer.append(b); R.selAi = b;
  if (rect && (rect.width || rect.height)) placeFixed(b, Math.max(8, rect.right - 10), rect.bottom + 8);
}
function openAiPage(p, preset = '') {
  if (readOnly || !p) return;
  commitHere(p);
  UI.ai = { scope: 'page', id: p.id, text: p.body, what: '整页', state: 'ask', ask: '' };
  showAi();
  if (preset) runAi(UI.ai, preset, '');
}
function closeAi() { UI.ai = null; renderKeepScroll(); renderDock(); }
// 开 / 换范围：正文重画（锁住的段加框），底部对话框画出来，光标进输入框
function showAi() { hideSelAi(); renderKeepScroll(); renderDock(); const f = R.dock && R.dock.querySelector('textarea, input'); if (f) f.focus(); }
async function runAi(A, preset, ask) {
  if (A !== UI.ai) return;
  const p = PAGES.get(A.id); if (!p) { closeAi(); return; }
  const at = relocate(A, p);
  if (A.scope === 'page') A.text = p.body;
  else if (!at) { Object.assign(A, { state: 'error', error: '这一截在页里找不到了（刚改过它）：关掉重新选' }); paintAi(A); return; }
  else Object.assign(A, at);
  Object.assign(A, { state: 'run', preset, ask, label: preset ? (AI_PRESETS[A.scope].find(x => x[0] === preset) || [, preset])[1] : ask, result: null, error: '', segs: null, pick: null });
  if (ask) rememberAsk(ask);
  paintAi(A);
  try {
    const r = await wcall('ai', { input: { id: A.id, scope: A.scope, text: A.text, preset, instruction: ask }, timeoutMs: 300000 });
    if (A !== UI.ai) return;
    const segs = textDiff(A.text, String(r.text || ''));
    const n = segs.filter(x => x.t === 'ch').length;
    Object.assign(A, { state: n ? 'done' : 'same', result: r, segs, pick: new Set(segs.map((x, i) => (x.t === 'ch' ? i : -1)).filter(i => i >= 0)) });
  } catch (e) { if (A !== UI.ai) return; Object.assign(A, { state: 'error', error: errText(e) }); }
  paintAi(A);
}
const paintAi = A => { if (A === UI.ai) renderDock(); };
// ── 按字 / 词比 ──
// 切词：英文 / 数字按词，空白一段，其余（中文、标点）一个字一个
const toks = s => String(s).match(/[A-Za-z0-9_]+(?:['’.-][A-Za-z0-9_]+)*|[^\S\n]+|\n|[\s\S]/gu) || [];
function lcsOps(A, B) {
  const n = A.length, m = B.length;
  if (n * m > 2.5e6) return null;
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) { if (A[i] === B[j]) { out.push(['=', A[i]]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(['-', A[i++]]); else out.push(['+', B[j++]]); }
  while (i < n) out.push(['-', A[i++]]); while (j < m) out.push(['+', B[j++]]);
  return out;
}
// 段：{t:'eq', s} | {t:'ch', del, add}。先按行对齐（行一样的直接相等），改过的那几行再按字 / 词细比；太大就整块算一处
function textDiff(a, b) {
  const L = s => String(s).split(/(?<=\n)/);
  const out = [];
  const push = (t, x, y = '') => {
    const last = out[out.length - 1];
    if (t === 'eq') { if (last && last.t === 'eq') last.s += x; else out.push({ t, s: x }); }
    else if (last && last.t === 'ch') { last.del += x; last.add += y; } else out.push({ t: 'ch', del: x, add: y });
  };
  const fine = (x, y) => {
    const ops = lcsOps(toks(x), toks(y));
    if (!ops) { push('ch', x, y); return; }
    for (const [k, tk] of ops) { if (k === '=') push('eq', tk); else if (k === '-') push('ch', tk, ''); else push('ch', '', tk); }
  };
  const lo = lcsOps(L(a), L(b));
  if (!lo) fine(a, b);
  else {
    let del = '', add = '';
    const flush = () => { if (del || add) fine(del, add); del = add = ''; };
    for (const [k, ln] of lo) { if (k === '=') { flush(); push('eq', ln); } else if (k === '-') del += ln; else add += ln; }
    flush();
  }
  // 两处改动之间只隔一个字（不是换行）：并成一处，免得满屏碎点
  const merged = [];
  for (const x of out) {
    const prev = merged[merged.length - 1], prev2 = merged[merged.length - 2];
    if (x.t === 'ch' && prev && prev.t === 'eq' && prev2 && prev2.t === 'ch' && [...prev.s].length <= 1 && !prev.s.includes('\n')) {
      merged.pop(); prev2.del += prev.s + x.del; prev2.add += prev.s + x.add;
    } else merged.push(x);
  }
  return merged;
}
const assemble = (segs, pick) => segs.map((x, i) => (x.t === 'eq' ? x.s : pick.has(i) ? x.add : x.del)).join('');
function applyAi(A) {
  const p = PAGES.get(A.id); if (!p || !A.segs) return;
  const at = relocate(A, p);
  if (!at) { LB.say(A.scope === 'page' ? '这页在等 AI 的时候改过了，没套用；可以再让它改一次' : '这一截在等 AI 的时候改过了，没套用；可以再让它改一次', { kind: 'warn' }); return; }
  const next = assemble(A.segs, A.pick);
  if (next === A.text) { LB.say('一处都没选：没改'); return; }
  const n = A.pick.size, all = A.segs.filter(x => x.t === 'ch').length;
  const ok = A.scope === 'page' ? mutate(p, x => { x.body = next; }, { kind: 'ai', note: `AI：${A.label}（用了 ${n}/${all} 处）` })
    : mutate(p, x => { x.body = spliceBody(x.body, at.start, at.end, next).body; }, { kind: 'ai', note: `AI：${A.label}（用了 ${n}/${all} 处）` });
  if (ok) { UI.ai = null; renderKeepScroll(); renderDock(); LB.say(`用了 AI 改的 ${n} 处；不满意按 Ctrl+Z 撤销`, { kind: 'ok' }); }
}
// 逐处勾选的那块：没改的字照常显示，改动处 = 划掉的原文 + 新字，点一下切换「要 / 不要」
function diffView(A) {
  const box = h('div', { cls: 'lbw-ai-diff' });
  A.segs.forEach((x, i) => {
    if (x.t === 'eq') { box.append(x.s); return; }
    const on = A.pick.has(i);
    const hk = h('span', { cls: 'lbw-hk' + (on ? '' : ' is-off'), data: { h: i } }, x.del ? h('del', { text: x.del }) : null, x.add ? h('ins', { text: x.add }) : null);
    hk.addEventListener('click', e => { e.stopPropagation(); if (A.pick.has(i)) A.pick.delete(i); else A.pick.add(i); paintAi(A); });
    box.append(hk);
  });
  return box;
}
// 面板：问（现成说法 / 自己说）→ 在改 → 逐处勾选（用选中的 / 全要 / 全不要 / 再改 / 换说法 / 不要）
function aiBody(A) {
  const out = [];
  if (A.state === 'ask' || A.state === 'error') {
    const inp = h('input', { attr: { type: 'text', placeholder: '或者自己说：比如「语气轻一点」「补一句为什么」' } });
    inp.value = A.ask || '';
    const go2 = () => { const v = inp.value.trim(); if (v) runAi(A, '', v); else inp.focus(); };
    inp.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); go2(); } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeAi(); } });
    const pipes = list => list.flatMap((b, i) => i ? [h('span', { cls: 'lbw-ai-pipe', text: '|', attr: { 'aria-hidden': 'true' } }), b] : [b]);
    out.push(h('div', { cls: 'lbw-ai-row lbw-ai-presets' }, pipes(AI_PRESETS[A.scope].map(([k, t]) => btn({ text: t, data: { preset: k }, on: { click: () => runAi(A, k, '') } })))));
    // 「按我的思路搭框架」只留顶上那一个切换（这里不再重复一颗）
    const recent = aiRecent().slice(0, 3);
    if (recent.length) out.push(h('div', { cls: 'lbw-ai-row lbw-ai-presets', attr: { style: 'margin-top:4px' } }, h('span', { cls: 'lbw-ai-note', attr: { style: 'margin:0' }, text: '用过的：' }), pipes(recent.map(t => btn({ text: t.length > 14 ? t.slice(0, 14) + '…' : t, on: { click: () => runAi(A, '', t) } })))));
    out.push(h('div', { cls: 'lbw-ai-row', attr: { style: 'margin-top:8px' } }, inp, btn({ cls: 'is-solid', text: '改', on: { click: go2 } }), btn({ text: '关', on: { click: closeAi } })));
    if (A.state === 'error') out.push(h('p', { cls: 'lbw-ai-note is-warn', text: A.error }));
    else out.push(h('p', { cls: 'lbw-ai-note', text: '用插件设置里的文本 AI；回来后每处改动你自己勾，点「用选中的」才改进去。' }));
  } else if (A.state === 'run') {
    out.push(h('p', { cls: 'lbw-ai-note', attr: { style: 'margin:0' }, text: `AI 在改${A.what}（${A.label}）… 一般十几秒到一分钟；这期间这一截先别动` }), h('div', { cls: 'lbw-ai-row', attr: { style: 'margin-top:8px' } }, btn({ text: '不等了', on: { click: closeAi } })));
  } else if (A.state === 'same') {
    out.push(h('p', { cls: 'lbw-ai-note', attr: { style: 'margin:0' }, text: 'AI 一个字都没改。' }), h('div', { cls: 'lbw-ai-row', attr: { style: 'margin-top:8px' } },
      btn({ text: A.mode === 'plan' ? '改计划' : '换个说法', on: { click: () => { A.state = A.mode === 'plan' ? 'plan' : 'ask'; paintAi(A); } } }), btn({ text: '关', on: { click: closeAi } })));
  } else if (A.state === 'done') {
    const r = A.result || {}, all = A.segs.filter(x => x.t === 'ch').length, n = A.pick.size;
    out.push(h('p', { cls: 'lbw-ai-note', attr: { style: 'margin:0 0 6px' } }, nums(`改了 ${all} 处，选了 ${n} 处`), '：划线的是原来的，加粗的是 AI 改的；点一处切换要不要'));
    out.push(diffView(A));
    if ((r.lost_cites || []).length) out.push(h('p', { cls: 'lbw-ai-note is-warn', text: `注意：AI 这版少了 ${r.lost_cites.length} 处收藏引用——那几处别勾，或者「再改一次」` }));
    const setAll = on => { A.pick = new Set(on ? A.segs.map((x, i) => (x.t === 'ch' ? i : -1)).filter(i => i >= 0) : []); paintAi(A); };
    out.push(h('div', { cls: 'lbw-ai-row', attr: { style: 'margin-top:8px' } },
      btn({ cls: 'is-solid', text: n === all ? '全部用上' : `用选中的 ${n} 处`, data: { ai: 'apply' }, attr: { disabled: !n }, on: { click: () => applyAi(A) } }),
      btn({ text: '全要', data: { ai: 'all' }, on: { click: () => setAll(true) } }), btn({ text: '全不要', data: { ai: 'none' }, on: { click: () => setAll(false) } }),
      btn({ text: '再改一次', on: { click: () => (A.mode === 'plan' ? runFill(A) : runAi(A, A.preset, A.ask)) } }),
      btn({ text: A.mode === 'plan' ? '改计划' : '换个说法', on: { click: () => { A.state = A.mode === 'plan' ? 'plan' : 'ask'; paintAi(A); } } }), btn({ text: '不要', on: { click: closeAi } })),
      h('p', { cls: 'lbw-ai-note', text: (r.model ? `模型：${r.model} · ` : '') + '用了之后不满意，Ctrl+Z 一步撤回，或者去「历史」里找回' }));
    if (A.mode === 'plan') out.push(...planExtras(A));
  }
  return out;
}
// ── 底部对话框（10-31 晚，作者：「ai 整理应该有一个比较舒服的对话框出现在底下」「和问收藏对齐，都是方型的框」）──
// 页头「AI」打开：有选中的字 → 改选中的那几段；正在改某段 / 刚点过某段 → 那一节；都没有 → 整页（空页 → 按思路搭框架）。
// 顶上一排切换范围（改这一节 / 改整页 / 按我的思路搭框架）。对话框 position:fixed 浮在正文那一栏底部，滚动 / 变宽时按阅读区重新摆
// （placeFixed 会抵掉 Obsidian 祖先 contain / transform 造成的偏移）
function openAiFromHead() {
  const p = current();
  if (!p || readOnly) { LB.say('先打开一页，再让 AI 整理'); return; }
  if (UI.ai) { closeAi(); return; }
  const sel = selectedRange();
  if (sel) { openAiPart(sel.p, sel.start, sel.end, sel.what); return; }
  if (ED && ED.p === p) { aiFromEditor(); return; }
  const at = UI.lastLine && UI.lastLine.page === p.id ? UI.lastLine.line : null;
  if (at != null && p.body.trim()) { const r = sectionRange(p, at); openAiPart(p, r.start, r.end, r.what); return; }
  if (p.body.trim()) openAiPage(p); else openAiPlan(p);
}
function switchScope(k) {
  const A = UI.ai, p = A && PAGES.get(A.id); if (!p) return;
  if (A.state === 'run' || A.state === 'planning' || A.state === 'filling') { LB.say('AI 还在改：等它回来，或者先点「不等了」'); return; }
  if (k === 'page') openAiPage(p);
  else if (k === 'plan') openAiPlan(p);
  else if (k === 'sec') {
    if (!p.body.trim()) { LB.say('这页还是空的：用「按我的思路搭框架」'); return; }
    const line = UI.lastLine && UI.lastLine.page === p.id ? UI.lastLine.line : (A.scope === 'part' ? A.start : 0);
    const r = sectionRange(p, line); openAiPart(p, r.start, r.end, r.what);
  }
}
function renderDock() {
  const A = UI.ai, p = A && PAGES.get(A.id);
  if (!A || !p || UI.view !== 'page' || UI.id !== A.id) { if (R.dock) { R.dock.remove(); R.dock = null; } if (R.aiBtn) R.aiBtn.classList.remove('is-on'); return; }
  const keep = R.dock && R.dock.querySelector('.lbw-dock-body'), top = keep ? keep.scrollTop : 0;
  const d = h('div', { cls: 'lbw-dock', data: { scope: A.scope, mode: A.mode || 'edit' } });
  const tab = (k, text, on) => btn({ cls: on ? 'is-on' : '', text, data: { scope: k }, on: { click: () => switchScope(k) } });
  d.append(h('div', { cls: 'lbw-dock-head' }, h('span', { cls: 'lbw-kick', text: 'AI' }),
    A.scope === 'part' ? tab('sec', '改' + A.what, true) : tab('sec', '改这一节', false),
    tab('page', '改整页', A.scope === 'page' && A.mode !== 'plan'), tab('plan', '按我的思路搭框架', A.mode === 'plan'),
    h('span', { cls: 'lbw-sp' }), btn({ cls: 'lbw-dock-x', text: '收起', data: { dock: 'close' }, on: { click: closeAi } })));
  const bodyEl = h('div', { cls: 'lbw-dock-body' }, h('div', { cls: 'lbw-ai', data: { scope: A.scope, mode: A.mode || 'edit' } }, A.mode === 'plan' ? planBody(A) : aiBody(A)));
  d.append(bodyEl);
  d.addEventListener('click', e => e.stopPropagation());
  if (R.dock) R.dock.replaceWith(d); else wrap.append(d);
  R.dock = d;
  if (R.aiBtn) R.aiBtn.classList.add('is-on');
  bodyEl.scrollTop = top;
  placeDock();
}
function placeDock() {
  const d = R.dock; if (!d) return;
  const sc = LB.scroller(), col = R.center.getBoundingClientRect();
  const vb = sc ? sc.getBoundingClientRect() : { top: 0, bottom: (WIN && WIN.innerHeight) || 800 };
  const w = Math.max(320, Math.min(780, col.width || 680));
  d.style.width = w + 'px';
  placeFixed(d, Math.max(8, (col.left || 0) + ((col.width || w) - w) / 2), Math.max((vb.top || 0) + 8, (vb.bottom || 800) - (d.offsetHeight || 220) - 14));
}
// ═════════════ 按我的思路搭框架（10-31 第二块，作者：「我给一段文字，但我有我的思路，ai 根据我的思路，把资料、wiki 框架配齐」） ═════════════
// 右侧栏：写思路 → AI 出计划（每节标题 + 去收藏里搜什么）→ 用户改 / 删 / 加节 → 「按这个去收藏里找」：每节用问收藏同一套检索，
// 模型只许引候选编号、每条带一句原帖原话（后端核对，对不上的标出来）；用户写的字不动，只往节下补，相反的说法单独一小节 →
// 结果照第一块逐处勾选再存（kind=ai）。后端在 link_brain/wiki_plan.py（pwiki plan / fill）。
function openAiPlan(p) {
  if (readOnly || !p) return;
  commitHere(p);
  UI.ai = { scope: 'page', mode: 'plan', id: p.id, text: p.body, what: '整页', label: '按思路搭框架', state: 'idea', idea: '', sections: [] };
  showAi();
}
async function runPlan(A) {
  if (A !== UI.ai) return;
  if (!A.idea.trim()) { LB.say('先写几句你的思路：想写什么、想要哪几节'); return; }
  const p = PAGES.get(A.id); if (!p) { closeAi(); return; }
  Object.assign(A, { state: 'planning', error: '', text: p.body });
  paintAi(A);
  try {
    const r = await wcall('plan', { input: { id: A.id, idea: A.idea, text: p.body }, timeoutMs: 300000 });
    if (A !== UI.ai) return;
    Object.assign(A, { state: 'plan', sections: (r.sections || []).map(s => ({ title: s.title || '', query: s.query || '', why: s.why || '' })) });
  } catch (e) { if (A !== UI.ai) return; Object.assign(A, { state: 'idea', error: errText(e) }); }
  paintAi(A);
}
async function runFill(A) {
  if (A !== UI.ai) return;
  const secs = A.sections.map(s => ({ ...s, title: s.title.trim(), query: s.query.trim() })).filter(s => s.title);
  if (!secs.length) { LB.say('计划里至少留一节'); return; }
  const p = PAGES.get(A.id); if (!p) { closeAi(); return; }
  Object.assign(A, { state: 'filling', error: '', text: p.body, sections: secs, segs: null, pick: null, result: null });
  paintAi(A);
  try {
    const r = await wcall('fill', { input: { id: A.id, idea: A.idea, text: p.body, sections: secs }, timeoutMs: 600000 });
    if (A !== UI.ai) return;
    const segs = textDiff(A.text, String(r.text || ''));
    Object.assign(A, { state: segs.some(x => x.t === 'ch') ? 'done' : 'same', result: r, segs, pick: new Set(segs.map((x, i) => (x.t === 'ch' ? i : -1)).filter(i => i >= 0)) });
  } catch (e) { if (A !== UI.ai) return; Object.assign(A, { state: 'plan', error: errText(e) }); }
  paintAi(A);
}
function planBody(A) {
  const out = [];
  const note = (t, warn) => h('p', { cls: 'lbw-ai-note' + (warn ? ' is-warn' : ''), text: t });
  if (A.state === 'idea') {
    const ta = h('textarea', { cls: 'lbw-ai-idea', attr: { rows: '6', placeholder: '写下你的思路：想弄清楚什么、你现在怎么看、想要哪几节（一行一节也行）。\nAI 先出计划给你改，你点头了才去收藏里找材料。' } });
    ta.value = A.idea || '';
    ta.addEventListener('input', () => { A.idea = ta.value; });
    out.push(ta, h('div', { cls: 'lbw-ai-row', attr: { style: 'margin-top:8px' } }, btn({ cls: 'is-solid', text: '出计划', data: { plan: 'make' }, on: { click: () => runPlan(A) } }), btn({ text: '关', on: { click: closeAi } })));
    out.push(A.error ? note(A.error, true) : note('你写过的字一个不动，AI 只往各节下面补；每条都带收藏出处和原帖原话。'));
  } else if (A.state === 'planning') {
    out.push(note('AI 在按你的思路拆节… 一般十几秒'), h('div', { cls: 'lbw-ai-row' }, btn({ text: '不等了', on: { click: closeAi } })));
  } else if (A.state === 'plan') {
    out.push(note('计划：每节的小标题和「去收藏里搜什么」都能改；不要的节点 ×。', false));
    A.sections.forEach((s, k) => {
      const ti = h('input', { attr: { type: 'text', placeholder: '小标题' }, data: { k, f: 'title' } }); ti.value = s.title;
      const qi = h('input', { attr: { type: 'text', placeholder: '去收藏里搜什么' }, data: { k, f: 'query' } }); qi.value = s.query;
      ti.addEventListener('input', () => { s.title = ti.value; }); qi.addEventListener('input', () => { s.query = qi.value; });
      out.push(h('div', { cls: 'lbw-plan-sec' }, h('div', { cls: 'lbw-ai-row' }, h('span', { cls: 'lbw-num', text: String(k + 1) }), ti,
        btn({ text: '×', data: { del: k }, on: { click: () => { A.sections.splice(k, 1); paintAi(A); } } }, sr('删掉这一节'))),
      h('div', { cls: 'lbw-ai-row' }, h('span', { cls: 'lbw-ai-note', attr: { style: 'margin:0' }, text: '搜：' }), qi), s.why ? note(s.why) : null));
    });
    out.push(h('div', { cls: 'lbw-ai-row', attr: { style: 'margin-top:8px' } },
      btn({ text: '＋ 加一节', on: { click: () => { A.sections.push({ title: '', query: '', why: '' }); paintAi(A); } } }),
      btn({ cls: 'is-solid', text: '按这个去收藏里找', data: { plan: 'fill' }, on: { click: () => runFill(A) } }),
      btn({ text: '改思路', on: { click: () => { A.state = 'idea'; paintAi(A); } } }), btn({ text: '关', on: { click: closeAi } })));
    if (A.error) out.push(note(A.error, true));
  } else if (A.state === 'filling') {
    out.push(note(`正在按 ${A.sections.length} 节去收藏里找材料，再让 AI 往各节下补… 一般两三分钟；这期间这页先别动`), h('div', { cls: 'lbw-ai-row' }, btn({ text: '不等了', on: { click: closeAi } })));
  } else return aiBody(A);   // done / same：照第一块逐处勾选
  return out;
}
// 补材料的结果附在逐处勾选下面：用到的收藏（S 编号）、原话没对上的（红）、删掉了几条编号对不上的
function planExtras(A) {
  const r = A.result || {}, out = [];
  if ((r.bad_quotes || []).length) out.push(h('div', { cls: 'lbw-ai-bad' }, h('b', { text: `${r.bad_quotes.length} 句「原帖原话」在原帖里没找到——正文里已标「⚠」，别直接信：` }),
    r.bad_quotes.map(x => h('div', null, `${x.src}《${x.title}》：「${x.quote}」`))));
  if (r.dropped) out.push(h('p', { cls: 'lbw-ai-note', text: `另有 ${r.dropped} 条引了不存在的编号，已经删掉。` }));
  if ((r.sources || []).length) out.push(h('div', { cls: 'lbw-ai-srcs' }, h('span', { cls: 'lbw-ai-note', attr: { style: 'margin:0' }, text: `用到的收藏（${r.sources.length} 篇）：` }),
    r.sources.map(x => h('a', { cls: 'lbw-cite', attr: { href: '#' }, text: `${x.n} ${x.title}`, on: { click: e => { e.preventDefault(); openCite(x.id); } } }))));
  return out;
}
// 最近删除（PersonalWiki/.trash）：列出来，一键找回
function openTrash() {
  UI.hist = null; UI.ai = null;
  UI.trash = { rows: null, error: '' };
  renderSide();
  const T = UI.trash;
  wcall('trash', {}).then(r => { if (UI.trash === T) { T.rows = Array.isArray(r?.pages) ? r.pages : []; renderSide(); } })
    .catch(e => { if (UI.trash === T) { T.rows = []; T.error = errText(e); renderSide(); } });
}
function renderTrashSide(side) {
  const T = UI.trash;
  side.append(h('div', { cls: 'lbw-rbar' }, btn({ text: '← 收起', on: { click: () => { UI.trash = null; renderSide(); } } }), h('span', { cls: 'is-on', text: '最近删除' })));
  if (T.error) side.append(h('p', { cls: 'lbw-note', text: '没读到：' + T.error }));
  if (!T.rows) { side.append(h('p', { cls: 'lbw-note', text: '正在读…' })); return; }
  if (!T.rows.length) side.append(h('p', { cls: 'lbw-note', text: '没有删掉的页' }));
  for (const x of T.rows) {
    const b = btn({ cls: 'lbw-pill', text: '找回', data: { undelete: x.name }, on: { click: () => { LB.busy(b, '找回中…'); undeletePage(x.name); } } });
    side.append(h('div', { cls: 'lbw-ver', attr: { style: 'cursor:default' } }, h('span', { cls: 'lbw-k', text: '删除' }), h('span', null, nums(fmtTime(x.at))), h('span', { cls: 'lbw-w', text: x.title }), b));
  }
  side.append(h('p', { cls: 'lbw-note', attr: { style: 'margin-top:22px' }, text: '删掉的页放在 PersonalWiki/.trash 里（Obsidian 不显示点开头的文件夹），历史也都留着。' }));
}

// ═════════════ 新建（页内弹层，不用 window.prompt） ═════════════
function closeModal() { const m = R.layer.querySelector('.lbw-mbg'); if (m) m.remove(); }
function newPageModal(opts = {}) {
  if (readOnly) return;
  closePop(); closeModal();
  const cur = current();
  const inherit = cur ? (cur.role === 'topic' ? cur.index_tag : foldersOf(cur)[0]?.index_tag || '') : '';
  const tin = h('input', { attr: { type: 'text', name: 'ptitle', placeholder: opts.folder ? '例如：做饭' : '例如：住宿偏好' } });
  const sel = opts.folder ? null : h('select', { attr: { name: 'cat' } }, h('option', { attr: { value: '' }, text: '先不归类' }),
    topics().map(t => { const o = h('option', { attr: { value: t.index_tag }, text: t.title }); if (t.index_tag === inherit) o.setAttribute('selected', ''); return o; }));
  if (sel) sel.value = inherit;
  const chk = opts.folder ? null : h('input', { attr: { type: 'checkbox', name: 'prompts' } });
  const ok = h('button', { cls: 'lbw-pill is-solid', text: '创建', attr: { type: 'submit' } });
  const form = h('form', { cls: 'lbw-modal', attr: { autocomplete: 'off' } },
    h('div', { cls: 'lbw-mh' }, h('span', { cls: 'lbw-kick', text: opts.folder ? 'NEW FOLDER' : 'NEW PAGE' }), h('h3', { text: opts.folder ? '新文件夹' : '新页面' })),
    h('label', null, opts.folder ? '文件夹名' : '标题', tin),
    sel ? h('label', null, '放进哪个文件夹', sel) : null,
    chk ? h('label', { cls: 'lbw-chk' }, chk, ' 放几个可删的写作提示') : null,
    h('div', { cls: 'lbw-acts2' }, btn({ cls: 'lbw-qbtn', text: '取消', on: { click: closeModal } }), ok));
  const bg = h('div', { cls: 'lbw-mbg', attr: { role: 'dialog', 'aria-modal': 'true' } }, form);
  bg.addEventListener('mousedown', e => { if (e.target === bg) closeModal(); });
  bg.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeModal(); } });
  let busy = false;
  form.onsubmit = async e => {
    e?.preventDefault?.();
    if (busy) return;
    const title = tin.value.trim(); if (!title) { tin.focus(); return; }
    const exist = pageByTitle(title);
    if (exist) { LB.say(`已经有「${title}」了，直接打开`); closeModal(); goPage(exist); return; }
    const args = [title];
    if (opts.folder) args.push('--topic');
    else { if (sel && sel.value) args.push('--folder', sel.value); if (chk && chk.checked) args.push('--prompts'); }
    busy = true;
    const done = LB.busy(ok, '创建中…');
    try {
      const r = await wcall('create', { args });
      done(); closeModal();
      const pg = r && r.page;
      if (!pg || !pg.id) throw new Error('后端没返回新页面');
      const p = { ...pg, tags: [...(pg.tags || [])], order: [...(pg.order || [])], body: String(pg.body || '') };
      p._saved = savedOf(p); PAGES.set(p.id, derive(p)); reindex();
      scheduleIndex();
      LB.say(r.message || `已新建《${p.title}》`, { kind: 'ok' });
      goPage(p);
      if (p.body) openEditor(0); else openEditor(-1, null, true);   // 新文件夹也直接能写（10-31：以前焦点丢了要再点一下）
    } catch (err) { done(); busy = false; LB.say((opts.folder ? '文件夹没建上：' : '页面没建上：') + errText(err), { kind: 'error' }); }
  };
  R.layer.append(bg);
  tin.focus();
}
async function deletePage(p) {
  if (readOnly || !p) return;
  if (!(await LB.confirm({ title: `删除《${p.title}》？`, body: '删了可以找回：提示里点「撤销」，或者「…」→「最近删除」。历史也留着。', ok: '删除', danger: true }))) return;
  commitHere(p);
  let gone = false;
  await enqueue(p, async () => {
    try {
      const r = await wcall('delete', { args: [p.id, '--base-hash', p.hash || ''] });
      PAGES.delete(p.id); reindex(); gone = true;
      if (UI.hist && UI.hist.id === p.id) UI.hist = null;
      scheduleIndex();
      const name = r && r.trashed;
      LB.say(`已删《${p.title}》`, { kind: 'ok', actions: name ? [{ label: '撤销', run: () => undeletePage(name) }] : [] });
    } catch (e) {
      if (e && e.code === 'CONFLICT') { await reloadPage(p); LB.say('没删掉：这页刚在别处改过，已换成磁盘上的版本，看过再删', { kind: 'error' }); }
      else LB.say('没删掉：' + errText(e), { kind: 'error' });
    }
  }, { hard: true });
  if (gone) go('home');
}
// 找回删掉的页（.trash 在 Obsidian 里看不见：点开头的文件夹不显示，所以页面里要有入口）
async function undeletePage(name) {
  if (readOnly) return;
  try {
    const r = await wcall('undelete', { args: [name] });
    const pg = r && r.page;
    if (!pg || !pg.id) throw new Error('后端没返回这一页');
    const p = { ...pg, tags: [...(pg.tags || [])], order: [...(pg.order || [])], body: String(pg.body || '') };
    p._saved = savedOf(p); PAGES.set(p.id, derive(p)); reindex(); scheduleIndex();
    if (UI.trash) UI.trash.rows = (UI.trash.rows || []).filter(x => x.name !== name);
    LB.say(r.message || `已找回《${p.title}》`, { kind: 'ok' });
    goPage(p);
  } catch (e) { LB.say('没找回来：' + errText(e), { kind: 'error' }); }
}
// 「…」菜单：插件的 obsidian.Menu（LB.showMenu）；插件太旧没有 showMenu 时用页内的小菜单
function showMoreMenu(evt, anchor) {
  const p = current();
  const nav = [
    { title: '目录首页', sub: '文件夹卡片和关系图', onClick: () => go('home') },
    { title: '全部展开', onClick: () => { PREFS.open = Object.fromEntries([...topics().map(t => [t.id, true]), [looseId, true]]); saveUi(); renderToc(); } },
    { title: '全部收起', onClick: () => { PREFS.open = Object.fromEntries([...topics().map(t => [t.id, false]), [looseId, false]]); saveUi(); renderToc(); } },
    { title: PREFS.tocOff ? '打开左边目录' : '收起左边目录', onClick: () => { if (wrap.classList.contains('is-narrow')) setDrawer(!UI.drawer); else setTocOff(!PREFS.tocOff); } },
  ];
  const items = readOnly ? [...nav, { separator: true }, { title: '重新读入', sub: '在 Obsidian 里直接改过 PersonalWiki 时', onClick: () => refresh(true) }] : [
    { title: UI.src ? '回到正文' : '整页 Markdown', disabled: !p, onClick: () => { commitEditor(false); flushSrc(); if (UI.src && liveSrc(p)) liveSrc(p)._lbDead = true; UI.src = !UI.src; renderKeepScroll(); } },
    { title: '新页面', onClick: () => newPageModal() },
    { title: '新文件夹', onClick: () => newPageModal({ folder: true }) },
    // 1101：以前左栏那排小图标（目录首页 / 全部展开 / 全部收起 / 收起目录）收到这里
    { separator: true },
    ...nav,
    { title: '按我的思路搭框架', sub: '写思路 → AI 出计划你改 → 按节去收藏里找材料补上', disabled: !p, onClick: () => p && openAiPlan(p) },
    { title: '让 AI 改整页', sub: '理顺结构 / 精简 / 从引用补要点 / 自己说怎么改', disabled: !p, onClick: () => p && openAiPage(p) },
    { separator: true },
    { title: '最近删除', sub: '删掉的页在这里找回', onClick: () => openTrash() },
    { title: '重新读入', sub: '在 Obsidian 里直接改过 PersonalWiki 时', onClick: () => refresh(true) },
    p ? { title: '删除这一页', danger: true, onClick: () => deletePage(p) } : null,
  ].filter(Boolean);
  if (LB.showMenu(items, evt)) return;
  closePop();
  const el = h('div', { cls: 'lbw-pop is-menu', attr: { role: 'menu' } }, items.map(it => it.separator ? h('hr')
    : btn({ attr: { disabled: !!it.disabled, role: 'menuitem' }, on: { click: () => { closePop(); it.onClick?.(); } } }, it.title, it.sub ? h('small', { text: it.sub }) : null)));
  R.layer.append(el);
  const r = anchor.getBoundingClientRect();
  const vw = (WIN && WIN.innerWidth) || 1200;
  placeFixed(el, Math.max(8, Math.min(r.left, vw - (el.offsetWidth || 260) - 8)), r.bottom + 6);
  POP.el = el; POP.ta = null;
}

// ═════════════ 全局按键（只给用户正在看的这一页）：Ctrl+F 搜标题；Esc 依次关 弹层 → 搜索 → 抽屉 → 历史 ═════════════
// 挂在 window 的捕获阶段（同目录页 onFindKey）：先于 Obsidian 自带的查找拿到 Ctrl+F；没有 window.addEventListener（单测）退回 document
const keyTarget = WIN && typeof WIN.addEventListener === 'function' ? WIN : D;
LB.listen('keys', keyTarget, 'keydown', e => {
  if (e.isComposing) return;
  if (!wrap.isConnected || !(wrap.closest('.workspace-leaf.mod-active') || LB.activeLeafHas(wrap))) return;
  // Obsidian 自己的弹窗（设置、命令面板、确认框）开着，或者按键落在 Wiki 外面的输入框里：都不归 Wiki（10-29 审查 4）
  if (D.querySelector('.modal-container')) return;
  const tgt = e.target;
  if (tgt && tgt.nodeType === 1 && !wrap.contains(tgt) && typeof tgt.closest === 'function' && tgt.closest('input, textarea, select, [contenteditable="true"]')) return;
  const k = String(e.key || '');
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (k.toLowerCase() === 'f' || e.code === 'KeyF')) { e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation?.(); toggleFind(true); return; }
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && k.toLowerCase() === 'z' && !ED && UI.view === 'page' && !readOnly
    && !(tgt && tgt.nodeType === 1 && typeof tgt.closest === 'function' && tgt.closest('input, textarea, select, [contenteditable="true"]'))) {
    e.preventDefault(); e.stopPropagation(); undoPage(current()); return;
  }
  if (k !== 'Escape' || LB.menuOpen() || ED) return;
  let done = true;
  if (R.gOverlay) closeGlobalGraph();
  else if (R.layer.querySelector('.lbw-mbg')) closeModal();
  else if (POP.el) closePop();
  else if (UI.find != null) toggleFind(false);
  else if (UI.drawer) setDrawer(false);
  else if (UI.ai) closeAi();
  else if (UI.trash) { UI.trash = null; renderSide(); }
  else if (UI.hist) { UI.hist = null; renderSide(); }
  else done = false;
  if (done) { e.preventDefault(); e.stopPropagation(); }
}, true);
LB.listen('pop-out', D, 'mousedown', e => { if (POP.el && !(e.target && e.target.closest && (e.target.closest('.lbw-pop') || e.target.closest('.lbw-ed')))) closePop(); });
// PersonalWiki 里的文件变了（Obsidian 里直接改 / 别的窗口存了）：防抖后按磁盘签名重读
for (const ev of ['modify', 'create', 'delete', 'rename']) {
  try {
    const ref = app.vault.on(ev, (f, old) => { const pre = wdir() + '/'; if (String(f?.path || '').startsWith(pre) || String(old || '').startsWith(pre)) scheduleRefresh(); });
    LB.onUnload(() => { try { app.vault.offref(ref); } catch (e) { console.debug(e); } });
  } catch (e) { console.debug('[lb] wiki vault event', e); }
}
LB.onUnload(() => clearTimeout(refreshTimer));

// ═════════════ 开跑 ═════════════
await loadItems();
LB.t('items');
{ const disk = await readDisk(); mergeDisk(disk); lastSig = await diskSig(); }
reindex();
LB.t('pages');
paintWidth();
render();
LB.t('render');
// 拖选了正文：浮「AI 改选中的」（10-31 晚：以前只能在编辑某一段时点「AI 改」，选中段落不方便）
R.center.addEventListener('mouseup', () => setTimeout(showSelAi, 0));
R.center.addEventListener('keyup', e => { if (e.shiftKey) showSelAi(); });
LB.listen('wiki-selai', D, 'mousedown', e => { if (R.selAi && e.target !== R.selAi) hideSelAi(); });
// 目录跟着读到哪（滚动时每帧最多算一次）
{ const sc = LB.scroller(); let spyQ = 0; if (sc) LB.listen('wiki-spy', sc, 'scroll', () => { if (spyQ) return; spyQ = 1; (WIN && WIN.requestAnimationFrame ? WIN.requestAnimationFrame : f => setTimeout(f, 16))(() => { spyQ = 0; spyHeads(); pinToc(); placeDock(); }); }, { passive: true }); }
// 登记这一版 DOM（§5.1 / §5.9）：catalog-data 变了只换收藏（引用编号 / 缺失标记）；Dataview 重跑时按磁盘签名看 PersonalWiki 有没有变
LB.keep(wrap, { version: await LB.data.version(), update: async () => { await loadItems(); if (!ED && !(UI.src && R.srcEd && D.activeElement === R.srcEd)) { const sc = LB.scroller(), top = sc ? sc.scrollTop : 0; renderCenter(); if (sc) sc.scrollTop = top; } },
  onReuse: () => { paintWidth(); for (const g of GRAPHS) g.resume(); refresh().catch(e => console.debug('[lb] wiki refresh', e)); } });

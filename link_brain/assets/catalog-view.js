const simplePage = false;
const starredPage = false;
// 第 2 批（CONVENTIONS §5）：共享前导 lb-page-lib.js 由 catalog.py 内联在本文件前面。
// Dataview 每 2.5 秒重跑本页：数据版本没变 → 上一次的整页 DOM 原样挂回（搜索框、滚动、多选都在）；变了 → 增量更新。
// 批次 D（L1）：页面挂在 dv.container 后面的 host 上（§5.9，重跑碰不到它：不失焦、输入法不断、吸顶不被 Dataview 的 overflow 打断）；
// 样式挂 head（§5.11）；瀑布流 JS 按行排（C9）；点星 / 勾选只改这张卡的状态 class，不重排（C2 / C10）；提示走 Notice（C7）。
const ROLE = starredPage ? 'starred' : 'catalog';
const LB = lbPageLib(dv, app, ROLE);
if (await LB.reuseDom()) return;
const root = dv.container;
// 这个仓可能被挂进别的库的子目录（如 LER Vault/知识库【小红书】/）；数据里的路径都相对 lwa 仓根，统一过 lbPath 补挂载前缀。
const lbPath = LB.path;
const provider = LB.provider;
const mobile = LB.mobile || (!provider() && typeof navigator !== 'undefined' && !!navigator && navigator.maxTouchPoints > 0 && typeof matchMedia === 'function' && matchMedia('(hover: none)').matches);
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-catalog');
const perfCounts = { rank: 0, layout: 0, build: 0 };
const syncPerf = () => { try { const P = (globalThis.__lbPerf = globalThis.__lbPerf || {}); (P[ROLE] = P[ROLE] || {}).counts = perfCounts; } catch {} };
syncPerf();

// 1027 字体样式集（编排「Aa 样式」和模块「调整」里能选的字体）：只写字体名，默认栈在共享令牌 lb-tokens.css（--lb-font-*-base），
// LB.themeVars 把名字排在默认栈前面（没装的字照样退回默认）；页面里的 --f-* 全部读令牌，不再手写字体栈
const FONT_NAMES = {
  cinzel: 'LB Cinzel, Cinzel', song: 'Noto Serif SC, Source Han Serif SC, Songti SC, SimSun', hei: 'Noto Sans SC, Microsoft YaHei UI',
  cormorant: 'LB Cormorant, Cormorant Garamond', kai: 'KaiTi, STKaiti, Kaiti SC', georgia: 'Georgia',
};
// ── 样式（X14c：挂 document.head 的 #lbc-style，目录页和星标页共用；跨页可能撞名的选择器加 .lbc-wrap 前缀） ──
const CSS = `
.markdown-preview-view.lb-catalog,.markdown-source-view.lb-catalog{--file-line-width:100%;}
.lb-catalog .markdown-preview-sizer,.lb-catalog .markdown-preview-section,.lb-catalog .cm-sizer,.lb-catalog .cm-contentContainer,.lb-catalog .cm-content,.lb-catalog .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-catalog .lb-page-host{width:100%;max-width:none;}
.lb-catalog .inline-title,.lb-catalog .metadata-container{display:none!important;}
/* C1 吸顶：Dataview 给容器写的行内 overflow-x:auto（兜底）、实时预览 1.14.4 的 .cm-embed-block:hover{overflow:hidden} 都会让 sticky 失效 */
.lb-catalog .block-language-dataviewjs{overflow:visible!important;}
.markdown-source-view.lb-catalog .cm-embed-block.cm-lang-dataviewjs,.markdown-source-view.lb-catalog .cm-embed-block.cm-lang-dataviewjs:hover{overflow:visible!important;}
/* 10-04（她定）整页外面那层 dataviewjs 代码块的框（边框 / 底色 / 圆角 / 悬停「编辑代码块」按钮）隐形：阅读视图 + 实时预览 */
.lb-catalog :is(.el-pre:has(.block-language-dataviewjs),pre:has(.block-language-dataviewjs),.block-language-dataviewjs,.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs),
.lb-catalog :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs):hover{border:0!important;background:transparent!important;box-shadow:none!important;outline:0!important;border-radius:0!important;}
.lb-catalog :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-lang-dataviewjs) .edit-block-button{display:none!important;}
/* 1021 Collection+ 改版（设计交接包 DESIGN-SPEC §0–3、5、9）：界面只有黑白——文字、选中、细线都用正文色 / 边框色，不用 --interactive-accent；
   颜色只出现在封面里。令牌映射 Obsidian 变量，深浅色自动跟随。标题 / 数字字体随包（_archive/fonts，@font-face 见 fontFaceCss），离线可用 */
.lbc-wrap{--c-bg:var(--background-primary);--c-ink:var(--text-normal);--c-muted:var(--text-muted);--c-faint:var(--text-faint);--c-line:var(--background-modifier-border);--c-soft:var(--background-secondary);
--f-display:var(--lb-font-title);--f-serif:var(--lb-font-serif);--f-latin:var(--lb-font-num);--f-sans:var(--lb-font-body);
--r-card:12px;--ctl-h:34px;--shadow-print:5px 5px 0 var(--text-normal);
/* 1026 她：字体规则统一——标题（雕刻 Cinzel / 衬线中文）· 数字（Cormorant 斜体、等宽数字）· 正文（无衬线）三套，字号只用这几档 */
--fs-body:13.5px;--fs-small:12px;--fs-tab:15.5px;--num-feat:lining-nums tabular-nums;--lbc-sp:1;
width:100%;max-width:1440px;margin:0 auto;box-sizing:border-box;height:auto;display:block;padding:22px 24px 30px;overflow:visible;font-family:var(--f-sans);}
.lbc-wrap button{font-family:inherit;}
.lbc-wrap button:focus-visible,.lbc-wrap input:focus-visible{outline:2px solid var(--c-ink)!important;outline-offset:3px;}
.lbc-top{position:sticky;top:0;background:var(--background-primary);z-index:2;display:flow-root;}
/* 页头：雕刻斜体大标题居中，篇数 / 更新时间在标题右侧、和标题底部对齐；「管理」细线胶囊钉在右上角 */
.lbc-head{position:relative;display:block;margin:0;padding:4px 0 0;container-type:inline-size;}
.lbc-titleblock{display:flex;flex-wrap:wrap;justify-content:center;align-items:flex-end;gap:4px 22px;padding:0 var(--lbc-tools-w,176px);min-width:0;--lbc-title-pad:calc(2 * var(--lbc-tools-w,176px));}
/* 右边让出「编排 / 管理」的实际宽度（JS 量好写进 --lbc-tools-w）；不够宽时左边不再对称预留，篇数 / 更新时间仍能排在标题右侧 */
@container(max-width:1320px){.lbc-titleblock{padding-left:0;--lbc-title-pad:var(--lbc-tools-w,176px);}}
/* 1026 窄（页头不到 760）：「编排 / 管理」退到标题上面一行，标题整行可用 */
@container(max-width:760px){.lbc-head .lbc-titleblock{padding:0;--lbc-title-pad:0px;}}
/* 1027「编排 / 管理」不属于任何模块（标题挪走 / 移除了也还在）：钉在吸顶区右上角；页头窄、第一个不是标题、编排中 → 退成最上面一行（JS 设 .is-tools-static） */
.lbc-top>.lbc-tools{position:absolute;top:0;right:0;}
.lbc-top.is-tools-static>.lbc-tools{position:static;justify-content:flex-end;margin:0 0 8px;}
.lbc-top.is-tools-static .lbc-titleblock{padding:0;--lbc-title-pad:0px;}
.lbc-titlerow{display:flex;align-items:flex-end;justify-content:center;min-width:0;max-width:100%;}
${LB.brandCss('.lbc-title', '.lbc-engr')}
/* 1026 场景 02：标题照共用的雕刻样式，字号再按右侧「编排 / 管理」让出的宽度收（长标题、放大都不出页头） */
.lbc-title{font-size:clamp(24px,min(calc(6.5cqi * var(--lbc-title-k,1)),calc((100cqi - var(--lbc-title-pad,0px) - var(--lbc-sub-w,0px) - 8px) / var(--lbc-title-em,8))),calc(96px * var(--lbc-title-k,1)));font-family:var(--f-display);}
@container(max-width:760px){.lbc-title{--lbc-sub-w:0px;}}   /* 窄：计数行本来就在下面一行，不用给它让位 */
.lbc-wrap .lbc-title button.lbc-import{font:inherit!important;color:var(--c-ink)!important;width:auto!important;height:auto!important;padding:0!important;margin:0 0 0 .02em!important;border:0!important;background:transparent!important;box-shadow:none!important;border-radius:0!important;display:inline-block!important;vertical-align:baseline;line-height:inherit!important;cursor:pointer;transition:transform .45s cubic-bezier(.2,.8,.2,1);}
.lbc-wrap .lbc-title button.lbc-import:hover{transform:rotate(90deg);}
.lbc-wrap .lbc-title button.lbc-import[aria-busy="true"]{opacity:.5;cursor:progress;}
.lbc-tools{position:absolute;top:0;right:0;z-index:1;display:flex;align-items:center;gap:8px;}
.lbc-wrap .lbc-tools button.lb-manage{width:auto!important;height:var(--ctl-h)!important;padding:0 14px!important;border:1px solid var(--c-ink)!important;border-radius:999px!important;background:var(--c-bg)!important;color:var(--c-ink)!important;box-shadow:none!important;font:500 13.5px/1 var(--f-sans)!important;display:inline-flex;align-items:center;gap:7px;white-space:nowrap;transition:background .15s,color .15s;}
.lbc-wrap .lbc-tools button.lb-manage:hover{background:var(--c-ink)!important;color:var(--c-bg)!important;}
.lbc-wrap .lbc-tools button.lb-manage svg{width:14px;height:14px;flex:none;}
.lbc-subline{display:flex;gap:2px 8px;align-items:baseline;justify-content:flex-start;flex-wrap:wrap;min-width:0;padding-bottom:14px;font:16px/1.3 var(--f-latin);color:var(--c-muted);letter-spacing:.02em;font-variant-numeric:lining-nums tabular-nums;}
.lbc-sub{font:inherit;color:var(--c-muted);white-space:nowrap;}
/* 1027b 计数行不写 italic：随包的 Cormorant 只有斜体那一面，数字照样是斜的；中文（篇 / 全部 / 更新）落到衬线中文就是直立的，不被硬斜 */
.lbc-count b{font-weight:600;color:var(--c-ink);}
.lbc-sub-sep{font:inherit;color:var(--c-faint);user-select:none;}
.lbc-wrap button.lbc-sub-link{font:inherit;letter-spacing:inherit;color:var(--c-muted);background:transparent!important;border:0!important;box-shadow:none!important;padding:0!important;height:auto!important;min-height:0;cursor:pointer;border-radius:3px;}
.lbc-wrap button.lbc-sub-link:hover{text-decoration:underline;text-underline-offset:3px;color:var(--c-ink);}
/* 问题 / 同步中 / 数据较旧 / 可能相关：照旧跟在后面，统一成小号文字 */
.lbc-wrap button.lbc-possible-link,.lbc-wrap button.lbc-syncing,.lbc-stale{font:12px/1.3 var(--f-sans);font-style:normal;letter-spacing:0;}
.lbc-stale{color:var(--lb-warn);}
.lbc-subline .lbc-stale{white-space:normal;min-width:0;overflow-wrap:anywhere;}
.lbc-wrap button.lbc-problems{display:inline-flex;align-items:center;gap:3px;min-height:0;height:auto!important;padding:0!important;border:0!important;box-shadow:none!important;background:transparent!important;cursor:pointer;flex:0 0 auto;align-self:center;}
.lbc-problems[hidden],.lbc-syncing[hidden],.lbc-possible-link[hidden],.lbc-sub-sep[hidden],.lbc-stale[hidden]{display:none!important;}
.lbc-prob-n{display:inline-flex;align-items:center;justify-content:center;min-width:16px;height:16px;padding:0 4px;box-sizing:border-box;border-radius:8px;font-size:10.5px;font-style:normal;font-weight:700;font-family:sans-serif;line-height:16px;}
.lbc-prob-need{background:var(--lb-warn);color:var(--text-on-accent,#fff);}
.lbc-prob-other{background:var(--background-modifier-border);color:var(--text-muted);font-weight:600;}
.lbc-titleblock>.lbc-syncprog,.lbc-titleblock>.lbc-mobile-note{flex:1 0 100%;}
.lbc-mobile-note{font-size:12px;line-height:1.5;color:var(--text-muted);margin:0;text-align:center;}
/* 分类行：只放「全部 + 一级分类 + 未归类」；衬线、居中、可换行（不要横向滚动条），选中 2.5px 下划线 */
.lbc-cats{display:flex;align-items:center;justify-content:space-between;flex-wrap:nowrap;gap:6px;overflow-x:auto;scrollbar-width:none;margin:12px 0 0;padding:0 0 2px;font:18px/1.4 var(--f-serif);}
.lbc-cats::-webkit-scrollbar{display:none;}
/* 1026 她：窗口窄了分类不许被裁——放不下一行就换行居中（JS 量出来加 .is-wrap） */
.lbc-cats.is-wrap{flex-wrap:wrap;justify-content:center;column-gap:22px;overflow:visible;}
.lbc-cats button.lbc-cat.is-empty{color:var(--c-faint);}
.lbc-cats button.lbc-cat{flex:none;position:relative;cursor:pointer;color:var(--c-muted);border:0!important;background:transparent!important;box-shadow:none!important;padding:4px 0 8px!important;border-radius:0!important;height:auto!important;font:inherit;font-weight:400;transition:color .2s;}
.lbc-cats button.lbc-cat:hover{color:var(--c-ink);}
.lbc-cats button.lbc-cat.is-active{color:var(--c-ink);font-weight:600;}
.lbc-cats button.lbc-cat.is-active::after{content:"";position:absolute;left:0;right:0;bottom:0;height:2.5px;background:var(--c-ink);}
/* 10-10 索引树：选中一个大类时下面一行它的二级小标签（带篇数），细线胶囊小字；更深一级（索引图里点的）多一个带 ✕ 的小尾巴 */
.lbc-subcats{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:8px;overflow:visible;margin:8px 0 0;padding:0;font-family:var(--f-serif);}
.lbc-subcats button.lbc-subcat{flex:none;display:inline-flex;align-items:baseline;gap:5px;height:auto!important;padding:3px 12px!important;border:1px solid var(--c-line)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);font:13px/1.6 var(--f-serif);cursor:pointer;transition:color .12s,border-color .12s;}
.lbc-subcats button.lbc-subcat:hover{color:var(--c-ink);border-color:var(--c-ink)!important;}
.lbc-subcats button.lbc-subcat.is-active{color:var(--c-ink);border-color:var(--c-ink)!important;font-weight:600;}
.lbc-subcat-n{font:italic 12.5px var(--f-latin);color:var(--c-muted);font-variant-numeric:lining-nums tabular-nums;font-weight:400;}
.lbc-subcats button.lbc-subcat.is-deep{border-style:dashed!important;}
/* 控制行：左边边栏钮 + 范围单选标签 + 前两个星标主题（+ 来源 / 专辑），右边同高 34px 的排序胶囊 · 视图切换 · 搜索胶囊 · 问收藏胶囊 */
.lbc-ctl{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 24px;margin:14px 0 0;padding:0 0 12px;}
.lbc-ctl-l,.lbc-ctl-r{display:flex;align-items:center;flex-wrap:wrap;min-width:0;}
.lbc-ctl-l{gap:2px 22px;}
.lbc-ctl-r{gap:10px;margin-left:auto;}
.lbc-scope{display:contents;}
/* Tag / 平台下拉的小箭头用 CSS 画（不用 ▾ 字符：首开时找后备字体要多排版 10ms） */
.lbc-wrap .lbc-ctl button.lbc-tagpick::after,.lbc-wrap .lbc-ctl button.lbc-platpick::after{content:"";width:5px;height:5px;margin:0 2px 3px 7px;border-right:1.4px solid currentColor;border-bottom:1.4px solid currentColor;transform:rotate(45deg);}
.lbc-ctl-sep{flex:none;width:1px;height:16px;background:var(--c-line);margin:0 -8px;}
.lbc-wrap .lbc-ctl button.lbc-cat,.lbc-wrap .lbc-ctl button.lbc-pick{position:relative;flex:none;height:var(--ctl-h)!important;display:inline-flex;align-items:center;padding:0!important;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);font:15.5px/1 var(--f-serif);font-weight:400;cursor:pointer;white-space:nowrap;transition:color .15s;}
.lbc-wrap .lbc-ctl button.lbc-cat:hover,.lbc-wrap .lbc-ctl button.lbc-pick:hover{color:var(--c-ink);}
.lbc-wrap .lbc-ctl button.lbc-cat.is-active,.lbc-wrap .lbc-ctl button.lbc-pick.is-active{color:var(--c-ink);font-weight:600;}
.lbc-wrap .lbc-ctl button.lbc-cat.is-active::before{content:"";position:absolute;left:0;right:0;bottom:2px;height:2px;background:var(--c-ink);}
.lbc-wrap .lbc-ctl button.lbc-cat[data-n]::after{content:attr(data-n);font:italic 13px/1 var(--f-latin);font-variant-numeric:lining-nums;margin-left:5px;color:var(--c-muted);font-weight:400;}
.lbc-wrap .lbc-ctl .lbc-topic-star{font-size:11px;margin-right:3px;color:inherit;}
.lbc-wrap .lbc-ctl button.lbc-topic-new-tab{color:var(--c-faint);}
.lbc-wrap .lbc-ctl button.lbc-sidetoggle{width:var(--ctl-h)!important;height:var(--ctl-h)!important;padding:0!important;margin-right:-8px;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);display:inline-grid;place-items:center;cursor:pointer;border-radius:999px!important;}
.lbc-wrap .lbc-ctl button.lbc-sidetoggle:hover{color:var(--c-ink);}
.lbc-wrap .lbc-ctl button.lbc-sidetoggle svg{width:15px;height:15px;}
.lbc-side-col{fill:currentColor;}
.lbc-wrap.is-side-collapsed .lbc-side-col{fill:none;}
.lbc-wrap .lbc-ctl button.lbc-pill{height:var(--ctl-h)!important;box-sizing:border-box;display:inline-flex;align-items:center;gap:6px;padding:0 14px!important;border:1px solid var(--c-line)!important;border-radius:999px!important;background:var(--c-bg)!important;box-shadow:none!important;color:var(--c-ink);font:13.5px/1 var(--f-sans);font-weight:400;cursor:pointer;white-space:nowrap;transition:border-color .15s;}
.lbc-wrap .lbc-ctl button.lbc-pill:hover,.lbc-wrap .lbc-ctl button.lbc-pill.is-active{border-color:var(--c-ink)!important;}
.lbc-wrap .lbc-ctl button.lbc-time::after{content:"↓";font:15px/1 var(--f-latin);}
.lbc-vseg[hidden]{display:none!important;}
.lbc-vseg{display:inline-flex;align-items:center;height:var(--ctl-h);box-sizing:border-box;padding:3px;gap:2px;}
.lbc-wrap .lbc-vseg button.lbc-view{height:26px!important;padding:0 12px!important;border:0!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);font:13.5px/1 var(--f-sans);cursor:pointer;white-space:nowrap;}
.lbc-wrap .lbc-vseg button.lbc-view:hover{color:var(--c-ink);}
.lbc-wrap .lbc-vseg button.lbc-view.is-on{background:var(--c-ink)!important;color:var(--c-bg);}
.lbc-searchbox{height:var(--ctl-h);box-sizing:border-box;display:inline-flex;align-items:center;gap:8px;padding:0 12px;border:1px solid var(--c-line);border-radius:999px;background:var(--c-bg);color:var(--c-muted);transition:border-color .15s;cursor:text;}
.lbc-searchbox:hover,.lbc-searchbox:focus-within{border-color:var(--c-ink);}
.lbc-searchbox svg{width:14px;height:14px;flex:none;}
.lbc-wrap input.lbc-search{width:min(210px,44vw)!important;min-width:0;height:32px!important;padding:0!important;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;color:var(--c-ink);font:14px/1.4 var(--f-sans);outline:none;}
.lbc-wrap input.lbc-search:focus,.lbc-wrap input.lbc-search:focus-visible{outline:none!important;box-shadow:none!important;}
.lbc-wrap input.lbc-search::placeholder{color:var(--c-muted);}
/* 1023 搜索框清空 ×：有字才出；原生 search 的叉藏掉，免得两个 */
.lbc-wrap input.lbc-search::-webkit-search-cancel-button{display:none;}
.lbc-wrap button.lbc-search-x{flex:none;width:20px!important;height:20px!important;padding:0!important;margin:0 0 0 2px;border:0!important;border-radius:50%!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);display:grid;place-items:center;cursor:pointer;font:15px/1 var(--f-sans);}
.lbc-wrap button.lbc-search-x:hover{color:var(--c-ink);background:var(--c-soft)!important;}
.lbc-wrap button.lbc-search-x[hidden]{display:none!important;}
/* 星标主题行：只在选中某个主题时出现在控制行下面，左对齐（全部主题 / 各主题胶囊 / + 新主题）；胶囊悬停出 ×，点两次删 */
.lbc-topics{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;margin:0;padding:0 0 12px 56px;}
.lbc-topics-lab{font:700 10.5px/1 var(--f-display);letter-spacing:.24em;margin-right:6px;color:var(--c-ink);}
.lbc-wrap .lbc-topics button.lbc-topic,.lbc-wrap .lbc-topics button.lbc-topic-all,.lbc-wrap .lbc-topics button.lbc-topic-add{display:inline-flex;align-items:center;gap:6px;height:auto!important;padding:5px 13px!important;border:1px solid var(--c-line)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);font:14px/1.3 var(--f-serif);cursor:pointer;transition:color .15s,border-color .15s,background .15s;}
.lbc-wrap .lbc-topics button.lbc-topic:hover,.lbc-wrap .lbc-topics button.lbc-topic-all:hover,.lbc-wrap .lbc-topics button.lbc-topic-add:hover{border-color:var(--c-ink)!important;color:var(--c-ink);}
.lbc-wrap .lbc-topics button.is-active{background:var(--c-ink)!important;border-color:var(--c-ink)!important;color:var(--c-bg);}
.lbc-wrap .lbc-topics button[data-n]::after{content:attr(data-n);font:italic 13px/1 var(--f-latin);font-variant-numeric:lining-nums;}
.lbc-wrap .lbc-topics button.lbc-topic-add{border-style:dashed!important;}
.lbc-topic-star{color:inherit;margin-right:2px;}
.lbc-topic-wrap{position:relative;display:inline-flex;}
.lbc-wrap .lbc-topics button.lbc-topic-del{position:absolute;top:-7px;right:-7px;z-index:1;width:18px;height:18px!important;min-width:18px;padding:0!important;border-radius:999px!important;border:1px solid var(--c-ink)!important;background:var(--c-bg)!important;box-shadow:none!important;color:var(--c-ink);font:11px/1 var(--f-sans);display:none;place-items:center;cursor:pointer;white-space:nowrap;}
.lbc-topic-wrap:hover button.lbc-topic-del,.lbc-wrap .lbc-topics button.lbc-topic-del:focus-visible,.lbc-wrap .lbc-topics button.lbc-topic-del.is-armed{display:grid;}
.lbc-wrap .lbc-topics button.lbc-topic-del.is-armed{width:auto;padding:0 7px!important;background:var(--c-ink)!important;color:var(--c-bg);}
@media(hover:none){.lbc-wrap .lbc-topics button.lbc-topic-del{display:grid;}}
.lbc-wrap .lbc-topics input.lbc-topic-new{width:132px;height:auto!important;padding:4px 0!important;border:0!important;border-bottom:1px solid var(--c-ink)!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;color:var(--c-ink);font:14px/1.3 var(--f-serif);outline:none;}
/* 边栏位：收藏墙那一排（.lbc-board）= 几列边栏（aside.lbc-side，吸在页头下面）+ 收藏墙那一列（.lbc-wallcol）；列宽 = 编排里 12 格的比例（--lbc-board-cols，JS 写）。
   1027 八个模块平级：页头那几排（吸顶区里）和墙下面的几排（.lbc-after）都是「一排 = 几列、一列 = 几个模块（.lbc-m）」 */
.lbc-board{display:block;position:relative;}
.lbc-board-main,.lbc-wallcol{min-width:0;}
.lbc-side[hidden],.lbc-row[hidden],.lbc-rcol[hidden],.lbc-wallcol[hidden]{display:none!important;}
.lbc-board.has-side{display:grid;grid-template-columns:var(--lbc-board-cols,minmax(0,4fr) minmax(0,8fr));column-gap:40px;align-items:start;}
.lbc-row{position:relative;display:grid;column-gap:calc(40px * var(--lbc-sp,1));align-items:start;}
.lbc-row.is-single{display:block;}
.lbc-row.is-free{display:flex;flex-wrap:wrap;align-items:flex-end;column-gap:0;row-gap:4px;}
.lbc-row.is-free>.lbc-rcol{flex:0 0 auto;box-sizing:border-box;}
.lbc-row.is-free>.lbc-rcol.is-tight{min-width:max-content;container-type:normal;}
.lbc-row.is-free>.lbc-rcol.is-gap-r{padding-right:calc(20px * var(--lbc-sp,1));}
.lbc-row.is-free>.lbc-rcol.is-tight.is-gap-r{padding-right:calc(12px * var(--lbc-sp,1));}
.lbc-row.is-free>.lbc-rcol:has(>.lbc-m-search:only-child){min-width:150px;}
/* 1028 右上角「编排 / 管理」钉着时：第一排里伸到它下面的块往下让出按钮的高度；标题那一块不到右边时不用给它留左右空 */
.lbc-row.is-free>.lbc-rcol.is-under-tools{padding-top:calc(var(--ctl-h) + 10px);}
.lbc-top.is-title-clear .lbc-titleblock{padding-left:0;padding-right:0;--lbc-title-pad:0px;}
.lbc-row>.lbc-rcol{min-width:0;container-type:inline-size;}
.lbc-after{display:block;margin-top:calc(26px * var(--lbc-sp,1));}
.lbc-m.is-gone{display:none!important;}
.lbc-wrap .lbc-m{font-family:var(--f-sans);zoom:calc(var(--lb-scale,1) * var(--lbc-m-k,1));}
/* 边栏收起 / 窄 / 索引视图：边栏列让开；放了标题 / 分类 / 筛选的那一列留下这几块（叠在墙上面），别的模块收起 */
.lbc-wrap:is(.is-side-collapsed,.is-side-narrow,.is-indexview) .lbc-board.has-side,.lbc-wrap.is-side-empty .lbc-board.has-side{display:block;}
.lbc-wrap:is(.is-side-collapsed,.is-side-narrow,.is-indexview) .lbc-side:not(.has-core){display:none!important;}
.lbc-wrap:is(.is-side-collapsed,.is-side-narrow,.is-indexview) .lbc-side.has-core{position:static;max-height:none;overflow:visible;}
.lbc-wrap:is(.is-side-collapsed,.is-side-narrow,.is-indexview) .lbc-side.has-core>.lbc-m:not(.is-core){display:none!important;}
@media(max-width:760px){.lbc-board.has-side{display:block;}.lbc-board.has-side>.lbc-side:not(.has-core){display:none!important;}.lbc-board.has-side>.lbc-side.has-core>.lbc-m:not(.is-core){display:none!important;}}
.lbc-wrap.is-side-narrow .lbc-row{display:block;}
.lbc-wrap.is-side-narrow .lbc-row>.lbc-rcol+.lbc-rcol{margin-top:12px;}
/* 1028 窄的时候：页头那几排小块照顺序换行排（不按 48 格），标题 / 分类 / 搜索占整行 */
.lbc-wrap.is-side-narrow .lbc-top .lbc-row.is-free{display:flex;flex-wrap:wrap;align-items:center;column-gap:16px;}
.lbc-wrap.is-side-narrow .lbc-top .lbc-row.is-free>.lbc-rcol{width:auto!important;margin-left:0!important;padding-right:0;padding-top:0;flex:0 1 auto;}
.lbc-wrap.is-side-narrow .lbc-top .lbc-row.is-free>.lbc-rcol+.lbc-rcol{margin-top:0;}
.lbc-wrap.is-side-narrow .lbc-top .lbc-row.is-free>.lbc-rcol:has(.lbc-m-title,.lbc-m-cats,.lbc-m-search){flex:1 1 100%;}
/* 1028：星标页 / 手机没有边栏、不会挂 is-side-narrow——按屏宽也把页头积木排成可换行的一排（390 宽不横滚，catalog_ui_smoke） */
@media(max-width:760px){.lbc-top .lbc-row.is-free{display:flex;flex-wrap:wrap;align-items:center;column-gap:16px;}.lbc-top .lbc-row.is-free>.lbc-rcol{width:auto!important;max-width:100%;min-width:0!important;margin-left:0!important;padding-right:0;padding-top:0;flex:0 1 auto;}.lbc-top .lbc-row.is-free>.lbc-rcol:has(.lbc-m-title,.lbc-m-cats,.lbc-m-search,.lbc-m-scope){flex:1 1 100%;}.lbc-top .lbc-scope,.lbc-top .lbc-subline{flex-wrap:wrap;}}
/* 1021 第 3 段 · 边栏（DESIGN-SPEC §4、§7）：吸在页头下面（top / max-height 由 paintStickyTop 量好写到 .lbc-wrap 上），内容超高自己滚，
   不显示滚动条；没到底时底部 56px 渐隐（.is-more），到底去掉。只有收藏墙随页面滚。窄于 760（按页面宽，.is-side-narrow）或手机不出 */
.lbc-side{position:sticky;top:var(--lbc-side-top,0px);overflow-anchor:none;max-height:calc(var(--lbc-pane-h,100vh) - var(--lbc-top-h,0px) - 16px);overflow-x:hidden;overflow-y:auto;scrollbar-width:none;min-width:0;box-sizing:border-box;padding:6px 0 24px;}
.lbc-side::-webkit-scrollbar{display:none;}
.lbc-side.is-more{-webkit-mask-image:linear-gradient(#000 calc(100% - 56px),transparent);mask-image:linear-gradient(#000 calc(100% - 56px),transparent);}
.lbc-wrap.is-side-narrow .lbc-ctl button.lbc-sidetoggle{display:none!important;}
/* 「索引」视图自己左边有树（这次不动它）：边栏和边栏钮都让开，版式照旧 */
.lbc-wrap.is-indexview .lbc-ctl button.lbc-sidetoggle{display:none!important;}
@media(max-width:760px){.lbc-wrap .lbc-ctl button.lbc-sidetoggle{display:none!important;}}
.lbc-wrap.is-side-empty .lbc-ctl button.lbc-sidetoggle{display:none!important;}
.lbc-mod{margin:0 0 26px;}
.lbc-mod[hidden],.lbc-mod-body[hidden],.lbc-fold-sum[hidden],.lbc-sy-alert[hidden],.lbc-sy-note[hidden]{display:none!important;}
.lbc-lab{display:flex;align-items:center;gap:14px;padding:4px 0 14px;cursor:pointer;user-select:none;color:var(--c-ink);}
.lbc-lab-en{font:700 11px/1 var(--f-display);letter-spacing:.26em;flex:none;}
.lbc-lab small{font:12px/1 var(--f-serif);letter-spacing:.1em;color:var(--c-muted);flex:none;}
.lbc-lab-line{flex:1;height:1px;background:var(--c-ink);min-width:12px;}
.lbc-chev{flex:none;width:14px;height:14px;display:grid;place-items:center;}
.lbc-chev::before{content:"";width:6px;height:6px;border-right:1.5px solid var(--c-ink);border-bottom:1.5px solid var(--c-ink);transform:translateY(-2px) rotate(45deg);transition:transform .25s;}
.lbc-mod.is-folded .lbc-chev::before{transform:translateX(-2px) rotate(-45deg);}
.lbc-wrap .lbc-lab button.lbc-gear{flex:none;width:22px!important;height:22px!important;padding:0!important;margin:0 -4px!important;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);display:grid;place-items:center;cursor:pointer;border-radius:999px!important;transition:color .15s,transform .4s;}
.lbc-wrap .lbc-lab button.lbc-gear:hover{color:var(--c-ink);transform:rotate(60deg);}
/* 1027 编排（design-1027 §2）：右上角「编排」→ 每个模块头上一条黑色操作条（⠿ 拖到任何位置 · 名字 · 调整 · ×），列与列之间一道可拖的边（调宽，12 格吸附），
   收藏墙上面一条托盘（＋ 模块 · Aa 样式 · 保存状态 · 恢复默认 · 结束编排）。「调整」在模块里面展开（不弹窗） */
.lbc-wrap .lbc-tools button.lb-arrange{width:auto!important;height:var(--ctl-h)!important;padding:0 14px!important;border:1px solid var(--c-ink)!important;border-radius:999px!important;background:var(--c-bg)!important;color:var(--c-ink)!important;box-shadow:none!important;display:inline-flex;align-items:center;gap:7px;font:500 13px/1 var(--f-sans)!important;cursor:pointer;white-space:nowrap;}
.lbc-wrap .lbc-tools button.lb-arrange:hover,.lbc-wrap.is-arranging .lbc-tools button.lb-arrange{background:var(--c-ink)!important;color:var(--c-bg)!important;}
.lbc-wrap .lbc-tools button.lb-arrange svg{width:14px;height:14px;flex:none;}
.lbc-wrap.is-indexview .lbc-tools button.lb-arrange,.lbc-wrap.is-side-narrow .lbc-tools button.lb-arrange{display:none!important;}
.lbc-mod-bar,.lbc-arrange-tray,.lbc-col-edge{display:none;}
.lbc-wrap .lbc-lab button.lbc-gear svg{width:15px;height:15px;}
.lbc-fold-sum{font:var(--fs-body)/1.45 var(--f-serif);color:var(--c-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:10px 0;cursor:pointer;}   /* 1027b 她：折起来那一行和展开的列表一行一样大、一样远 */
.lbc-fold-sum:hover{color:var(--c-ink);}
.lbc-fold-sum i{font:italic 15px/1 var(--f-latin);font-variant-numeric:lining-nums tabular-nums;color:var(--c-ink);}
.lbc-rec{list-style:none;margin:0;padding:0;}
/* 1023：RECENT 行和 SYNC 行（.lbc-sy-row）同一套——无衬线 13.5px、10px 行距、只有上分隔线 */
.lbc-rec li{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:12px;align-items:baseline;padding:10px 0;border-top:1px solid var(--c-line);cursor:pointer;margin:0;font-size:13.5px;}
.lbc-rec li:hover .lbc-rec-t{text-decoration:underline;text-underline-offset:3px;}
.lbc-rec time{font:italic 13.5px/1.2 var(--f-latin);color:var(--c-muted);font-variant-numeric:lining-nums tabular-nums;white-space:nowrap;}
.lbc-rec-t{font:13.5px/1.45 var(--f-sans);color:var(--c-ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbc-rec-c{font-size:12px;color:var(--c-muted);white-space:nowrap;}
.lbc-rec-empty{font:14px/1.5 var(--f-serif);color:var(--c-muted);padding:6px 0;}
.lbc-sy-top{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;}
.lbc-sy-k{font-size:12px;color:var(--c-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbc-sy-big{font:500 clamp(20px,8cqi,30px)/1.1 var(--f-latin);color:var(--c-ink);font-variant-numeric:lining-nums tabular-nums;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbc-sy-big i{font-style:italic;}
.lbc-sy-bar{height:3px;background:var(--c-line);margin:16px 0 6px;border-radius:3px;overflow:hidden;}
.lbc-sy-bar i{display:block;height:100%;width:0;background:var(--c-ink);transition:width .4s;}
.lbc-sy-bar.is-unknown i{width:30%!important;opacity:.5;}
.lbc-sy-cap{display:flex;justify-content:space-between;gap:12px;font:italic 13px/1.4 var(--f-latin);color:var(--c-muted);margin-bottom:10px;font-variant-numeric:lining-nums tabular-nums;}
.lbc-sy-cap span:last-child{text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbc-sy-freq{font-size:12px;color:var(--c-muted);margin:-4px 0 10px;line-height:1.5;}
.lbc-wrap button.lbc-sy-alert{display:block;width:100%;text-align:left;height:auto!important;margin:0 0 10px;padding:8px 10px!important;border:1px solid var(--c-ink)!important;border-radius:10px!important;background:transparent!important;box-shadow:none!important;color:var(--c-ink);font:13px/1.5 var(--f-sans);cursor:pointer;white-space:normal;}
.lbc-wrap button.lbc-sy-alert:hover{background:var(--c-soft)!important;}
.lbc-sy-alert b{font-weight:600;}
.lbc-sy-note{font-size:12px;line-height:1.6;color:var(--c-muted);margin:0 0 10px;}
.lbc-sy-row{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:10px 0;border-top:1px solid var(--c-line);font-size:13.5px;}
.lbc-sy-row>span{color:var(--c-muted);}
.lbc-sy-row b{font:600 17px/1.2 var(--f-latin);color:var(--c-ink);font-variant-numeric:lining-nums tabular-nums;white-space:nowrap;}
.lbc-sy-row.is-tot{border-top:1px solid var(--c-ink);}
.lbc-sy-row.is-tot b{font-size:24px;}
.lbc-sy-row.is-tot b.is-none{color:var(--c-muted);font-weight:400;}
.lbc-figs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px 20px;}
/* 1023：大数跟边栏宽走（4 位数也塞得进 1/4 列），兜底不溢出到隔壁 */
.lbc-fig-n{font:500 clamp(20px,calc(10cqi - 6px),48px)/.95 var(--f-latin);color:var(--c-ink);font-variant-numeric:lining-nums tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:clip;min-width:0;}
.lbc-fig-l{font-size:12.5px;color:var(--c-muted);margin-top:8px;}
.lbc-bars{display:grid;grid-template-columns:repeat(14,minmax(0,1fr));gap:6px;align-items:end;height:104px;margin-top:26px;}
.lbc-bar{display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%;gap:5px;min-width:0;}
.lbc-bar span{font:12px/1 var(--f-latin);color:var(--c-muted);font-variant-numeric:lining-nums tabular-nums;visibility:hidden;}
.lbc-bar i{display:block;width:3px;background:var(--c-ink);border-radius:2px 2px 0 0;min-height:1px;}
.lbc-bar.is-zero i{background:var(--c-line);}
.lbc-bar.is-today i{width:7px;}
.lbc-bar.is-today span{visibility:visible;color:var(--c-ink);font-weight:600;}
.lbc-bar:hover span{visibility:visible;}
.lbc-days{display:grid;grid-template-columns:repeat(14,minmax(0,1fr));gap:6px;border-top:1px solid var(--c-ink);padding-top:6px;font:12px/1.2 var(--f-latin);color:var(--c-muted);text-align:center;font-variant-numeric:lining-nums tabular-nums;}
.lbc-days span{white-space:nowrap;min-width:0;}
.lbc-days span:nth-child(odd):not(:last-child){visibility:hidden;}
.lbc-side{container-type:inline-size;}
@container (max-width:340px){.lbc-figs{grid-template-columns:repeat(2,minmax(0,1fr));}.lbc-fig-n{font-size:clamp(20px,calc(20cqi - 10px),48px);}}
/* 10-11「索引」视图：左边可折叠的树（带篇数），右边就是卡片网格（点哪个节点右边就是哪些）；窄了（<700px 或手机）树叠在上面。
   她的口味：不要灰框、不要看得见的滚动条——选中用正文色 + 左侧细线，空分类变淡，按钮都是字链 */
.lbi-bar{display:flex;flex-direction:column;gap:8px;margin:6px 5px 14px;}
.lbi-bar[hidden],.lbi-panel[hidden],.lbi-head[hidden]{display:none!important;}
.lbi-line{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;font-size:12px;line-height:1.7;color:var(--text-muted);}
.lbi-sum{color:var(--text-muted);}
.lbi-status{color:var(--text-muted);}
.lbi-status.is-warn::before{content:"⚠ ";color:var(--lb-warn);}
.lbc-wrap button.lbi-link{font:inherit;font-size:12px;color:var(--text-muted);background:transparent!important;border:0!important;box-shadow:none!important;padding:0!important;height:auto!important;cursor:pointer;text-decoration:underline;text-decoration-color:var(--background-modifier-border);text-underline-offset:3px;}
.lbc-wrap button.lbi-link:hover{color:var(--text-normal);text-decoration-color:currentColor;}
.lbc-wrap button.lbi-link.is-strong{color:var(--text-normal);font-weight:500;}
.lbc-wrap button.lbi-link:disabled{opacity:.5;cursor:default;}
.lbi-unc-link.is-on{color:var(--text-normal)!important;font-weight:500;}
.lbi-chips{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;}
.lbi-chips-label{font-size:12px;color:var(--text-muted);margin-right:2px;}
.lbc-wrap button.lbi-chip{display:inline-flex;align-items:baseline;gap:5px;height:auto;padding:2px 10px;border:1px dashed var(--background-modifier-border)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:12px;font-weight:400;line-height:1.6;cursor:pointer;transition:color .12s,border-color .12s;}
.lbc-wrap button.lbi-chip:hover{color:var(--text-normal);border-color:var(--text-faint)!important;}
.lbc-wrap button.lbi-chip.is-on{color:var(--text-normal);border-style:solid!important;border-color:var(--text-normal)!important;font-weight:500;}
.lbi-chip-n{font-size:10.5px;color:var(--text-faint);font-variant-numeric:tabular-nums;}
.lbi-note{font-size:12px;line-height:1.6;color:var(--text-muted);margin:0;}
.lbi-split.is-on{display:grid;grid-template-columns:minmax(210px,270px) minmax(0,1fr);gap:0 22px;align-items:start;}
.lbi-split.is-on.is-narrow{display:block;}
.lbi-main{min-width:0;}
.lbi-panel{font-size:13px;padding:2px 0 24px 5px;}
.lbi-split.is-on:not(.is-narrow)>.lbi-panel{position:sticky;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:none;}
.lbi-split.is-on:not(.is-narrow)>.lbi-panel::-webkit-scrollbar{display:none;}
.lbi-split.is-narrow>.lbi-panel{padding-bottom:10px;margin-bottom:6px;border-bottom:1px solid var(--background-modifier-border);}
.lbi-tree{display:flex;flex-direction:column;}
.lbi-row{display:flex;align-items:center;gap:2px;min-height:28px;border-left:2px solid transparent;}
.lbi-row.is-current{border-left-color:var(--text-normal);}
/* 1015 大纲树：拖拽落点（上 / 下一条细线 = 插到前 / 后，整行淡底 = 放进去当子类；不能放 = 红色虚线）、改名框 */
.lbi-row[draggable="true"]{cursor:grab;}
.lbi-row.is-dragging{opacity:.4;}
.lbi-row.is-drop-before{box-shadow:inset 0 2px 0 var(--interactive-accent);}
.lbi-row.is-drop-after{box-shadow:inset 0 -2px 0 var(--interactive-accent);}
.lbi-row.is-drop-into{background:color-mix(in srgb,var(--interactive-accent) 14%,transparent);border-radius:6px;}
.lbi-row.is-drop-bad{outline:1px dashed var(--lb-danger);outline-offset:-1px;border-radius:6px;}
.lbc-wrap input.lbi-rename{flex:1 1 auto;min-width:0;height:26px;font-size:13px;padding:2px 6px;margin:1px 4px 1px 0;}
.lbc-wrap button.lbi-fold{flex:none;width:18px;height:22px;padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:12px;line-height:1;cursor:pointer;display:grid;place-items:center;}
.lbc-wrap button.lbi-fold:hover{color:var(--text-normal);}
.lbi-fold-pad{flex:none;width:18px;}
.lbc-wrap button.lbi-label{flex:1 1 auto;min-width:0;display:flex;align-items:baseline;gap:8px;height:auto;padding:4px 6px 4px 2px;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--text-normal);font-size:13px;font-weight:400;line-height:1.45;text-align:left;cursor:pointer;}
.lbc-wrap button.lbi-label:hover .lbi-name{text-decoration:underline;text-decoration-color:var(--background-modifier-border);text-underline-offset:3px;}
.lbi-name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbi-n{flex:none;font-size:11px;color:var(--text-faint);font-variant-numeric:tabular-nums;}
.lbi-row.is-current .lbi-name{font-weight:600;}
.lbi-row.is-root .lbi-name{font-weight:600;}
.lbi-row.is-empty .lbi-name,.lbi-row.is-empty .lbi-n{color:var(--text-faint);}
.lbi-row.is-unc .lbi-name{color:var(--text-muted);}
.lbi-row.is-virtual .lbi-name{color:var(--text-muted);font-style:italic;}
.lbi-badge{flex:none;font-size:10.5px;color:var(--text-faint);border:1px dashed var(--background-modifier-border);border-radius:6px;padding:0 5px;line-height:1.5;}
.lbi-acts{flex:none;display:none;gap:8px;padding-right:4px;}
.lbi-row:hover .lbi-acts,.lbi-row:focus-within .lbi-acts,.lbi-row.is-current .lbi-acts{display:inline-flex;}
@media(hover:none){.lbi-acts{display:inline-flex;}}
.lbi-acts button.lbi-link{font-size:11.5px!important;}
/* 1027b 索引：悬停「改名 / ＋子类」、树底「＋ 加分类」、条上工具靠右 */
.lbi-tools{display:inline-flex;gap:14px;margin-left:auto;}
.lbi-add{gap:6px;padding-top:2px;padding-bottom:2px;}
.lbc-wrap .lbi-add input{flex:1 1 auto;min-width:0;height:26px;padding:0 8px;border:1px solid var(--c-ink);border-radius:4px;background:var(--c-bg);color:var(--c-ink);font:13px var(--f-sans);box-shadow:none;}
.lbc-wrap button.lbi-add-btn{display:block;width:auto!important;height:28px!important;margin:8px 0 0 14px!important;padding:0 12px!important;border:1px dashed var(--c-line)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);font:12.5px/1 var(--f-sans);cursor:pointer;}
.lbc-wrap button.lbi-add-btn:hover{border-color:var(--c-ink)!important;color:var(--c-ink);}
.lbi-tree-tip{margin:8px 0 0 14px;font-size:11.5px;line-height:1.6;color:var(--c-faint);}
.lbi-wiki-mark{flex:none;font-size:10.5px;color:var(--text-faint);}
.lbi-wiki-mark.has-page{color:var(--text-muted);}
.lbi-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;margin:2px 5px 4px;font-size:13px;line-height:1.7;}
.lbi-head-title{font-weight:600;color:var(--text-normal);}
.lbi-head-sub{font-size:12px;color:var(--text-muted);}
.lbi-warn{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 10px;font-size:12px;line-height:1.6;color:var(--text-normal);}
.lbi-warn-mark{color:var(--lb-warn);}
.lbi-warn ol{margin:4px 0 0;padding-left:20px;flex-basis:100%;color:var(--text-muted);}
.lbi-split.is-on .lbc-grid{padding-top:6px;}
/* 10-11 细分标签：选中节点下面一行 chips（实线小圆角，选中 = 正文色描边加粗）；卡片上一行淡字 */
.lbi-facets{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin:4px 5px 2px;}
.lbi-facets[hidden],.lbc-ftags[hidden]{display:none!important;}
.lbi-facets-label{font-size:12px;color:var(--text-muted);margin-right:2px;}
.lbc-wrap button.lbi-facet{display:inline-flex;align-items:baseline;gap:5px;height:auto;padding:2px 10px;border:1px solid var(--background-modifier-border)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:12px;font-weight:400;line-height:1.6;cursor:pointer;transition:color .12s,border-color .12s;}
.lbc-wrap button.lbi-facet:hover{color:var(--text-normal);border-color:var(--text-faint)!important;}
.lbc-wrap button.lbi-facet.is-on{color:var(--text-normal);border-color:var(--text-normal)!important;font-weight:500;}
.lbc-wrap button.lbi-facet.is-zero{opacity:.45;}
.lbc-wrap button.lbi-facet-clear{border-style:dashed!important;}
.lbc-ftags{font-size:11px;line-height:1.5;color:var(--text-faint);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
/* 卡片上「归类…」：只在索引视图里、鼠标停在卡上才出现（和选中圈 / ☆ 同款圆角小钮，排在它们左边） */
.lbc-wrap button.lbc-reclass{position:absolute;top:12px;right:48px;z-index:1;height:26px;box-sizing:border-box;padding:0 10px!important;border-radius:999px!important;border:1.5px solid #fff!important;background:rgba(0,0,0,.28)!important;box-shadow:0 1px 4px #0003!important;color:#fff;font-size:12px;line-height:1;display:none;align-items:center;cursor:pointer;}
.lbc-wrap.is-indexview .lbc-card:hover button.lbc-reclass,.lbc-wrap.is-indexview .lbc-card:focus-within button.lbc-reclass{display:inline-flex;}
.lbc-wrap button.lbc-reclass:hover{background:rgba(0,0,0,.45)!important;}
@media(hover:none){.lbc-wrap.is-indexview button.lbc-reclass{display:inline-flex;}}
/* 选分类的小窗（移到… / 也放进…）：上面一个筛选框，下面整棵树；列表能滚但不露滚动条 */
.lbc-dialog .lbi-pick{margin-top:8px;max-height:min(52vh,420px);overflow-y:auto;scrollbar-width:none;}
.lbc-dialog .lbi-pick::-webkit-scrollbar{display:none;}
.lbc-dialog button.lbi-pick-row{display:flex;width:100%;align-items:baseline;gap:8px;height:auto;padding:5px 8px;border:0!important;border-radius:6px;background:transparent!important;box-shadow:none!important;color:var(--text-normal);font-size:13px;text-align:left;cursor:pointer;}
.lbc-dialog button.lbi-pick-row:hover,.lbc-dialog button.lbi-pick-row:focus-visible,.lbc-dialog button.lbi-pick-row.is-first{background:var(--background-modifier-hover)!important;outline:none;}
.lbc-dialog button.lbi-pick-row.is-here{color:var(--text-faint);cursor:default;}
.lbc-dialog .lbi-pick-n{margin-left:auto;font-size:11px;color:var(--text-faint);}
.lbc-dialog .lbi-pick-empty{padding:10px 8px;color:var(--text-muted);font-size:12px;}
/* C1 / C15：多选栏在吸顶区里（.lbc-top 最后一个子节点），常用的留在栏上，其余收进「更多…」 */
.lbc-selbar{display:flex;flex-wrap:wrap;row-gap:8px;gap:8px 12px;align-items:center;margin:8px 0 10px;padding:10px 14px;border-radius:12px;background:var(--background-secondary);}
.lbc-selbar[hidden]{display:none!important;}
.lbc-selcount{font-size:13px;color:var(--text-muted);}
.lbc-selbar button{border:0;border-radius:8px;padding:6px 14px;white-space:nowrap;}
.lbc-selbar button.mod-warning{background:var(--lb-danger);color:var(--text-on-accent,#fff);font-weight:600;}
.lbc-selbar button.mod-warning:hover{filter:brightness(.92);}
.lbc-selbar button:disabled{opacity:.5;cursor:default;}
.lbc-selbar .lbc-selhint{font-size:12px;color:var(--text-faint);white-space:nowrap;}
.lbc-menu{background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:5px;min-width:120px;}
.lbc-menu-item{display:block;width:100%;text-align:left;border:0;background:transparent;color:var(--text-normal);box-shadow:none;height:auto;padding:7px 14px;border-radius:7px;cursor:pointer;font-size:13px;}
.lbc-menu-item:hover,.lbc-menu-item:focus-visible{background:var(--background-modifier-hover);outline:none;}
.lbc-menu-item.is-danger{color:var(--lb-danger);}
.lbc-menu-group{padding:6px 14px 2px;font-size:11.5px;color:var(--text-faint);}
.lbc-menu-item.is-sub{padding-left:24px;}
.lbc-menu .lbc-menu-head{padding:6px 14px 2px;font-size:11px;color:var(--text-faint);}
.lbc-menu .lbc-menu-item.is-on{color:var(--text-normal);font-weight:600;}
.lbc-menu .lbc-menu-sep{height:1px;margin:4px 6px;background:var(--background-modifier-border);}
.lbc-menu .lbc-range{display:flex;align-items:center;gap:6px;padding:4px 10px 8px;font-size:12px;color:var(--text-muted);}
.lbc-menu .lbc-range[hidden]{display:none!important;}
.lbc-menu .lbc-range input{height:26px;font-size:12px;padding:0 4px;}
.lbc-menu .lbc-range button{height:26px;padding:0 10px;font-size:12px;}
/* 1011 时间菜单紧凑版：左边一列小标签，右边一行分段 / 一行小块；选中用强调色填满（亮 / 暗主题都跟 Obsidian 变量走） */
.lbc-menu.lbc-time-menu{padding:8px 10px;min-width:0;max-width:min(460px,calc(100vw - 16px));box-sizing:border-box;}
.lbc-time-menu .lbc-tm-row{display:flex;align-items:flex-start;gap:10px;padding:3px 0;}
.lbc-time-menu .lbc-tm-label{flex:0 0 auto;width:2.6em;line-height:26px;font-size:12px;color:var(--text-muted);}
.lbc-time-menu .lbc-seg{display:inline-flex;padding:2px;gap:2px;border-radius:8px;background:var(--background-modifier-hover);}
.lbc-time-menu .lbc-chips{display:flex;flex-wrap:wrap;gap:6px;min-width:0;}
.lbc-time-menu .lbc-menu-item{display:inline-flex;align-items:center;justify-content:center;width:auto;height:26px;line-height:1;white-space:nowrap;font-size:12px;padding:0 10px;background:transparent;box-shadow:none;}
.lbc-time-menu .lbc-menu-item:hover{background:var(--background-modifier-hover);}
.lbc-time-menu .lbc-seg-btn{border-radius:6px;color:var(--text-muted);}
.lbc-time-menu .lbc-seg-btn:hover{background:var(--background-primary);color:var(--text-normal);}
.lbc-time-menu .lbc-chip{border-radius:13px;border:1px solid var(--background-modifier-border);color:var(--text-normal);}
.lbc-time-menu .lbc-menu-item.is-on,.lbc-time-menu .lbc-menu-item.is-on:hover{background:var(--text-normal);border-color:var(--text-normal);color:var(--background-primary);font-weight:600;}
.lbc-time-menu .lbc-menu-item:focus-visible{box-shadow:0 0 0 2px var(--text-normal);}
.lbc-time-menu .lbc-range{padding:4px 0 2px calc(2.6em + 10px);flex-wrap:nowrap;}
.lbc-time-menu .lbc-range input{flex:1 1 8.6em;width:8.6em;min-width:0;}
.lbc-time-menu .lbc-range button{flex:0 0 auto;}
/* C9 按行瀑布流：每列一个 flex 子列，卡片按预估高度放进当前最矮的一列 */
.lbc-grid{height:auto;overflow:visible;display:block;padding:12px 5px 30px;}
.lbc-grid[hidden]{display:none!important;}
.lbc-masonry{display:flex;align-items:flex-start;gap:0 var(--lbc-gap,24px);}
.lbc-masonry>.lbc-col{flex:1 1 0;min-width:0;display:flex;flex-direction:column;}
.lbc-card{display:block;width:100%;margin:0 0 26px;cursor:pointer;position:relative;content-visibility:auto;overflow-clip-margin:28px;}
.lbc-cover{display:block;width:100%;height:auto;max-height:360px;object-fit:cover;object-position:top;border:0;border-radius:var(--r-card);transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .25s;pointer-events:none;}
/* 1021 悬停：整张封面向左上错 3px，露出不模糊的实心错版投影（全页唯一的投影）；角标 / 圈跟着封面走 */
.lbc-card:hover :is(.lbc-cover,.lbc-nocover){transform:translate(-3px,-3px);box-shadow:var(--shadow-print);}
.lbc-wrap .lbc-card :is(.lbc-badges,.lbc-check,.lbc-star:not(.is-static),.lbc-reclass){transition:opacity .15s,background .12s,translate .25s cubic-bezier(.2,.8,.2,1);}
.lbc-wrap .lbc-card:hover :is(.lbc-badges,.lbc-check,.lbc-star:not(.is-static),.lbc-reclass){translate:-3px -3px;}
.lbc-card:focus-visible{outline:2px solid var(--c-ink);outline-offset:5px;border-radius:var(--r-card);}
.lbc-card.is-selected .lbc-cover,.lbc-card.is-selected .lbc-nocover{outline:0;box-shadow:0 0 0 3px var(--c-ink)!important;filter:brightness(.94);}
/* 1015 她：选中的框和卡片框叠在一起不舒服——选中只要贴着封面的一圈（不留缝、跟着圆角），选中的卡不再叠键盘焦点框 */
.lbc-card.is-selected:focus-visible{outline:0;}
.lbc-card.is-selected :is(.lbc-cover,.lbc-nocover){transition:none;}
.lbc-card.is-selected:hover :is(.lbc-cover,.lbc-nocover){transform:none;}
.lbc-wrap .lbc-card.is-selected:hover :is(.lbc-badges,.lbc-check,.lbc-star:not(.is-static),.lbc-reclass){translate:none;}
/* 没有封面图：柔和文字封面（按分类取一个浅色底，文字固定深色——深色主题下也是浅底深字）；4:3 和原来一样（卡片高度估算不变） */
.lbc-nocover{aspect-ratio:4/3;box-sizing:border-box;border-radius:var(--r-card);background:var(--lbc-tile,#f2e5b8);color:#141414;display:flex;flex-direction:column;justify-content:space-between;padding:8% 9% 7%;overflow:hidden;container-type:inline-size;transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .25s;}
.lbc-nocover.has-badges{padding-top:calc(8% + 26px);}
.lbc-card:has(>.lbc-nocover) .lbc-badges .lbc-video{display:none;}
.lbc-tile-cat{font:600 clamp(10px,4.4cqi,12px)/1.3 var(--f-sans);letter-spacing:.12em;opacity:.62;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbc-tile-title{margin:auto 0 5%;font:800 clamp(15px,7.6cqi,26px)/1.3 var(--f-sans);letter-spacing:.01em;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;}
.lbc-tile-foot{display:flex;justify-content:space-between;align-items:center;gap:8px;min-height:1.6em;font:italic 500 clamp(12px,5.4cqi,15px)/1 var(--f-latin);font-variant-numeric:lining-nums;opacity:.75;}
.lbc-tile-ty{font:600 clamp(9px,4cqi,11px)/1 var(--f-sans);font-style:normal;letter-spacing:.1em;border:1px solid currentColor;border-radius:999px;padding:.35em .7em;white-space:nowrap;}
.lbc-body{padding:13px 2px 0;}
.lbc-ctitle{font:600 15.5px/1.6 var(--f-serif);color:var(--c-ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
/* 卡片属于某个星标主题：标题下一排细线小胶囊（最多 2 个） */
.lbc-ctopics{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0 0;overflow:hidden;max-height:40px;}
.lbc-ctopics span{font-size:11.5px;line-height:18px;border:1px solid var(--c-ink);border-radius:999px;padding:0 7px;color:var(--c-ink);white-space:nowrap;}
.lbc-cmeta{display:flex;justify-content:space-between;align-items:center;gap:10px;color:var(--c-muted);font-size:13px;line-height:20px;margin-top:8px;font-weight:400;}
.lbc-cmeta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbc-cmeta .lbc-au{display:flex;align-items:center;gap:7px;min-width:0;}
.lbc-cmeta .lbc-av{flex:none;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:var(--lbc-av,#e2e9c9);color:#141414;font:700 10.5px/1 var(--f-sans);overflow:hidden;}
.lbc-likes{flex-shrink:0;font-variant-numeric:tabular-nums;}
.lbc-lowhit{font-size:12px;line-height:1.55;color:var(--text-faint);margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;}
.lbc-empty{padding:40px;color:var(--text-muted);}
.lbc-empty-text{margin:0 0 12px;}
.lbc-empty-actions{display:flex;gap:10px;flex-wrap:wrap;}
.lbc-possible-head{display:flex;align-items:baseline;gap:10px;margin:8px 5px 16px;padding-top:14px;border-top:1px solid var(--background-modifier-border);}
.lbc-possible-head:focus{outline:none;}
.lbc-possible-title{font-size:13px;font-weight:500;color:var(--text-muted);}
.lbc-possible-note{font-size:11px;color:var(--text-faint);}
.lbc-ask-tip{cursor:pointer;margin:0 5px 12px;}
.lbc-card.is-possible .lbc-cover{opacity:.85;}
/* 角标（视频 / 待补 / 疑似附件 / 文件 / 问题）：封面左上角的小号细线胶囊；待补 / 要你处理照旧用共享的警示色（C18） */
.lbc-wrap .lbc-badges{position:absolute;top:10px;left:10px;display:flex;gap:5px;align-items:center;}
.lbc-wrap .lbc-attach{position:static;display:inline-flex;align-items:center;gap:4px;line-height:16px;padding:0 8px;height:22px;box-sizing:border-box;font-size:11px;border-radius:999px;background:var(--c-bg);color:var(--c-ink);border:1px solid var(--c-ink);pointer-events:none;}
.lbc-wrap .lbc-attach.lbc-video{padding:0 6px;}
.lbc-wrap .lbc-attach-todo,.lbc-wrap .lbc-badges .lbc-prob.is-need{color:var(--lb-warn);background:var(--lb-warn-bg);border-color:var(--lb-warn-border);}
.lbc-wrap .lbc-attach-hint{color:var(--c-muted);border-color:var(--c-line);}
.lbc-wrap .lbc-badges .lbc-prob{pointer-events:auto;cursor:help;color:var(--c-muted);border-color:var(--c-line);}
.lbc-wrap .lbc-badges svg{display:block;width:14px;height:14px;flex:none;stroke:currentColor;stroke-width:1.6;fill:none;}
/* ☆ / 选中圈（1021 设计稿）：同款 30px 圆，白底黑字细线；没收藏的平时不显示、悬停才出现（1008 她定），已收藏 = 黑底白星并常显 */
.lbc-wrap .lbc-star{position:absolute;top:10px;right:10px;z-index:1;box-sizing:border-box;width:30px;height:30px;padding:0!important;border-radius:50%!important;border:1px solid var(--c-ink)!important;background:var(--c-bg)!important;box-shadow:none!important;color:var(--c-ink);display:grid;place-items:center;cursor:pointer;opacity:0;visibility:hidden;pointer-events:none;}
.lbc-wrap .lbc-star[hidden]{display:none!important;}
.lbc-wrap .lbc-star svg{width:14px;height:14px;fill:currentColor;stroke:none;}
.lbc-wrap .lbc-card:hover .lbc-star,.lbc-wrap .lbc-card:focus-within .lbc-star,.lbc-wrap.is-selecting .lbc-star{opacity:1;visibility:visible;pointer-events:auto;}
.lbc-wrap .lbc-star:hover{background:var(--c-soft)!important;}
/* 1026 她：已收藏的星原来是整块黑圆，每张卡一个黑点很突兀——改成白底小圆 + 黑星（不描边、一道很淡的影），悬停才出原来的细线圈 */
.lbc-wrap .lbc-star.is-on{width:26px;height:26px;top:12px;right:12px;border-color:transparent!important;background:color-mix(in srgb,#fff 90%,transparent)!important;box-shadow:0 1px 3px #0000002e!important;color:#141414;opacity:1;visibility:visible;pointer-events:auto;}
.lbc-wrap .lbc-star.is-on svg{width:13px;height:13px;}
.lbc-wrap .lbc-star.is-on:hover{border-color:var(--c-ink)!important;background:#fff!important;}
.lbc-wrap .lbc-star.is-pop svg{animation:lbc-starpop .5s cubic-bezier(.3,1.6,.5,1);}
@keyframes lbc-starpop{0%{transform:scale(.6) rotate(-20deg);}60%{transform:scale(1.35) rotate(8deg);}100%{transform:scale(1) rotate(0);}}
.lbc-wrap .lbc-star.is-static{right:10px;cursor:default;}
.lbc-wrap .lbc-card.is-starring .lbc-star{animation:lbc-pulse .8s ease-in-out infinite;cursor:progress;}
@keyframes lbc-pulse{0%,100%{transform:scale(1);}50%{transform:scale(1.15);}}
.lbc-wrap .lbc-card.is-deleting{opacity:.45;pointer-events:none;}
.lbc-card.is-droptarget::after,.lbc-card.is-busy::after{position:absolute;inset:0;display:grid;place-items:center;border-radius:var(--r-card);font-size:13px;color:var(--text-normal);background:color-mix(in srgb,var(--background-primary) 70%,transparent);z-index:3;pointer-events:none;}
.lbc-card.is-droptarget::after{content:"松手挂到这篇";outline:2px dashed var(--c-ink);outline-offset:-2px;}
.lbc-card.is-busy::after{content:attr(data-busy);cursor:progress;}
.lbc-flash{position:absolute;left:50%;top:40%;transform:translate(-50%,-50%);z-index:4;padding:4px 10px;border-radius:8px;background:var(--background-primary);color:var(--lb-ok);font-size:12px;box-shadow:0 2px 8px #0002;pointer-events:none;}
.lbc-tagform{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}
.lbc-tagform input{flex:1 1 100%;width:100%;}
.lbc-tagform-err{flex:1 1 100%;font-size:12px;color:var(--lb-danger);}
.lbc-tagform-err[hidden]{display:none!important;}
.lbc-card-more{position:absolute;right:0;bottom:-4px;width:28px;height:28px;padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:20px;opacity:0;}
.lbc-card:hover .lbc-card-more,.lbc-card:focus-within .lbc-card-more{opacity:1;}
/* 10-04 悬停卡片就出现的选中圈（不用先进「多选模式」）；有选中时每张卡都显示圈 */
.lbc-wrap button.lbc-check{position:absolute;top:10px;left:10px;z-index:1;box-sizing:border-box;width:30px;height:30px;padding:0!important;border-radius:50%!important;border:1px solid var(--c-ink)!important;background:var(--c-bg)!important;box-shadow:none!important;color:transparent;display:grid;place-items:center;cursor:pointer;opacity:0;pointer-events:none;}
.lbc-wrap button.lbc-check svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round;}
.lbc-card:hover button.lbc-check,.lbc-card:focus-within button.lbc-check,.lbc-wrap.is-selecting button.lbc-check{opacity:1;pointer-events:auto;}
.lbc-wrap button.lbc-check:hover{background:var(--c-soft)!important;color:var(--c-muted);}
.lbc-wrap button.lbc-check.is-on{background:var(--c-ink)!important;border-color:var(--c-bg)!important;color:var(--c-bg);opacity:1;pointer-events:auto;}
@media(hover:none){.lbc-wrap button.lbc-check{opacity:1;pointer-events:auto;}.lbc-card-more{opacity:1;}}
/* 1021「列表」视图：简单表格（标题 / 分类 / 作者 / 导入时间 / ♡），和瀑布流共用筛选、搜索结果；点行打开笔记 */
.lbc-list{padding:10px 5px 30px;overflow-x:auto;}
/* 1023「Wiki」占位：以后放长期研究 / 可合并的主题，索引也会并进来；现在只是空页 */
.lbc-wiki{padding:64px 5px 80px;text-align:center;color:var(--c-muted);}
.lbc-wiki[hidden]{display:none!important;}
.lbc-wiki h3{font:italic 500 34px/1.1 var(--f-latin);color:var(--c-ink);margin:0 0 14px;}
.lbc-wiki p{font:14px/1.7 var(--f-serif);margin:0;}
.lbc-list[hidden]{display:none!important;}
.lbc-ltable{width:100%;border-collapse:collapse;font-size:14px;min-width:560px;}
.lbc-ltable th{font:600 12px/1.2 var(--f-serif);letter-spacing:.14em;text-align:left;padding:0 12px 10px 0;border-bottom:1px solid var(--c-ink);color:var(--c-ink);white-space:nowrap;}
.lbc-ltable th.lbc-lt-likes,.lbc-ltable td.lbc-lt-likes{text-align:right;padding-right:4px;}
.lbc-ltable td{padding:12px 12px 12px 0;border-bottom:1px solid var(--c-line);vertical-align:baseline;color:var(--c-ink);}
.lbc-ltable tbody tr.lbc-lrow{cursor:pointer;}
.lbc-ltable tbody tr.lbc-lrow:hover td,.lbc-ltable tbody tr.lbc-lrow.is-selected td{background:var(--c-soft);}
.lbc-ltable tbody tr.lbc-lrow:focus-visible{outline:2px solid var(--c-ink);outline-offset:-2px;}
.lbc-ltable td.lbc-lt-title{font:15px/1.45 var(--f-serif);}
.lbc-ltable td.lbc-lt-title .lbc-lt-star{margin-right:6px;font-size:12px;}
.lbc-ltable td.lbc-lt-cat,.lbc-ltable td.lbc-lt-au{color:var(--c-muted);font-size:13px;white-space:nowrap;max-width:14em;overflow:hidden;text-overflow:ellipsis;}
.lbc-ltable td.lbc-lt-date,.lbc-ltable td.lbc-lt-likes{font:italic 15px var(--f-latin);color:var(--c-muted);font-variant-numeric:lining-nums tabular-nums;white-space:nowrap;}
.lbc-ltable tr.lbc-lt-sep td{padding-top:24px;font-size:12.5px;color:var(--c-muted);cursor:default;}
/* 星标页（.lbc-simple）：单列列表 */
.lbc-simple .lbc-grid{max-width:820px;margin:0 auto;}
.lbc-simple .lbc-card{display:block;margin:0;padding:18px 72px 18px 0;border-bottom:1px solid var(--background-modifier-border);}
.lbc-simple .lbc-cover,.lbc-simple .lbc-nocover{display:none;}
.lbc-simple .lbc-body{padding:0;}
.lbc-simple .lbc-cmeta{justify-content:flex-start;margin-top:4px;}
.lbc-simple .lbc-head{max-width:820px;margin:0 auto 12px;}
.lbc-simple .lbc-cats,.lbc-simple .lbc-ctl,.lbc-simple .lbc-topics{max-width:820px;margin-left:auto;margin-right:auto;}
.lbc-wrap.lbc-simple .lbc-badges{position:static;float:right;margin:2px 0 0 12px;}
.lbc-wrap.lbc-simple .lbc-card:hover :is(.lbc-badges,.lbc-check,.lbc-star){translate:none;}
.lbc-wrap.lbc-simple .lbc-star{top:18px;right:0;}
.lbc-simple button.lbc-check{top:18px;left:auto;right:38px;}
/* 10-04 存成选集的小对话框 */
.lbc-dialog-back{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.28);display:grid;place-items:center;}
.lbc-dialog{width:min(440px,calc(100vw - 32px));box-sizing:border-box;background:var(--background-primary);color:var(--text-normal);border:1px solid var(--background-modifier-border);border-radius:12px;box-shadow:0 10px 32px rgba(0,0,0,.25);padding:18px 18px 14px;font-size:13px;}
.lbc-dialog h3{margin:0 0 6px;font-size:15px;font-weight:600;}
.lbc-dialog .lbc-dialog-list{color:var(--text-muted);font-size:12px;line-height:1.6;margin:0 0 12px;max-height:5.2em;overflow:hidden;}
.lbc-dialog input{width:100%;box-sizing:border-box;height:34px;font-size:14px;}
.lbc-dialog .lbc-dialog-hint{margin:8px 0 0;font-size:12px;color:var(--text-faint);}
.lbc-dialog .lbc-dialog-err{margin:8px 0 0;font-size:12px;color:var(--lb-danger);}
.lbc-dialog .lbc-dialog-bar{display:flex;justify-content:flex-end;gap:8px;margin-top:14px;}
/* C12 手机上「更新」点开的最近几次同步 */
.lbc-synclog-pop{position:fixed;z-index:9999;max-width:min(360px,calc(100vw - 24px));background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:8px 12px;font-size:12px;line-height:1.7;color:var(--text-normal);}
.lbc-synclog-pop .lbc-synclog-empty{color:var(--text-muted);}
/* 10-04 ⑧ 一键回顶部：滚下去之后右下角一个小圆钮；钉在视口底部，滚回顶部就消失 */
.lbc-totop-dock{position:sticky;bottom:22px;height:0;display:flex;justify-content:flex-end;pointer-events:none;z-index:2;}
.lbc-wrap button.lbc-totop{pointer-events:none;transform:translateY(-100%);width:34px;height:34px;padding:0!important;border-radius:50%!important;border:1px solid var(--background-modifier-border)!important;background:var(--background-primary)!important;color:var(--text-muted);box-shadow:0 2px 10px #0000001a!important;display:grid;place-items:center;cursor:pointer;opacity:0;transition:opacity .18s,color .12s,border-color .12s;}
.lbc-wrap button.lbc-totop svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
.lbc-totop-dock.is-on button.lbc-totop{opacity:.82;pointer-events:auto;}
.lbc-totop-dock.is-on button.lbc-totop:hover{opacity:1;color:var(--text-normal);border-color:var(--text-faint)!important;}
/* ── 1026 / 1027 页头那几块（标题与 Logo · 分类 · 筛选与搜索）：「筛选与搜索」移除时只藏筛选项，搜索 / 排序 / 问收藏一直在（她 1026 定） ── */
.lbc-blk{display:block;}
/* 1028 筛选条拆成的小块：每块一行按钮，靠左；块和块之间的距离由编排的列宽 / 间距定 */
.lbc-wrap .lbc-ctl.lbc-ctl-piece{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-start;gap:2px 22px;margin:calc(14px * var(--lbc-sp,1)) 0 0;padding:0 0 12px;min-width:0;}
.lbc-wrap .lbc-ctl-piece.lbc-blk-search .lbc-searchbox{flex:1 1 160px;min-width:0;}
.lbc-wrap .lbc-ctl-piece.lbc-blk-search input.lbc-search{width:100%!important;min-width:0;}
.lbc-wrap .lbc-ctl-piece:empty,.lbc-wrap .lbc-ctl-piece.is-empty{display:none;}
.lbc-blk-meta .lbc-subline{padding-bottom:0;}
.lbc-blk-meta{align-self:end;padding-bottom:14px;}
/* 计数行是窄的一块：「同步中…」→「同步中 12/40」多几个字就会多折一行、页头跳一下——给它留够同样的宽度 */
.lbc-blk-meta .lbc-syncing{display:inline-block;min-width:7.5em;}
.lbc-blk-meta .lbc-syncing[hidden]{display:inline-block!important;visibility:hidden;}   /* 平时也占着位置（看不见），开始同步时页头不变高 */
.lbc-wrap.is-arranging .lbc-top{position:relative;top:0!important;}
/* 1027 编排时「编排 / 管理」不占模块的位置：托盘里有「结束编排」，这两个按钮先收起 */
.lbc-wrap.is-arranging .lbc-top>.lbc-tools{display:none!important;}
/* 区块间距（Aa 样式「卡片间距」）：模块、栏、卡片、页头几行的间距一起按 --lbc-sp 缩放 */
.lbc-board.has-side{column-gap:calc(40px * var(--lbc-sp,1));}
.lbc-mod{margin-bottom:calc(26px * var(--lbc-sp,1));}
.lbc-card{margin-bottom:calc(26px * var(--lbc-sp,1));}
.lbc-ctl{margin-top:calc(14px * var(--lbc-sp,1));}
.lbc-cats{margin-top:calc(12px * var(--lbc-sp,1));}
.lbc-wrap.is-arranging .lbc-arrange-tray{margin:6px 0 18px;}
/* 1026 Wiki（长期研究主题）· 最近导入全部（翻页）——正文无衬线、数字 Cormorant、按钮细线胶囊，和边栏同一套字 */
.lbc-wiki{text-align:left;padding:28px 5px 60px;}
.lbc-wiki-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px;margin-bottom:18px;}
.lbc-wiki-head h3{margin:0;}
.lbc-wiki-sub{flex:1 1 320px;font:var(--fs-body)/1.7 var(--f-sans)!important;color:var(--c-muted);margin:0;}
.lbc-wiki-row{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 16px;padding:14px 0;border-top:1px solid var(--c-line);}
.lbc-wiki-unc{border-top:1px solid var(--c-ink);margin-top:10px;}
.lbc-wiki-t{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;min-width:0;}
.lbc-wiki-t b{font:600 16px/1.4 var(--f-serif);color:var(--c-ink);}
.lbc-wiki-n{font:italic 15px/1 var(--f-latin);font-variant-numeric:var(--num-feat);color:var(--c-muted);}
.lbc-wiki-st{font-size:var(--fs-small);color:var(--c-muted);}
.lbc-wiki-acts{display:flex;flex-wrap:wrap;gap:8px;}
.lbc-wiki-empty{font:var(--fs-body)/1.7 var(--f-sans);color:var(--c-muted);margin:6px 0 12px;}
.lbc-wrap button.lbc-wiki-btn,.lbc-wrap button.lbc-rec-all,.lbc-wrap .lbc-sy-acts button{height:28px!important;padding:0 12px!important;border:1px solid var(--c-line)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--c-ink);font:var(--fs-small)/1 var(--f-sans);cursor:pointer;white-space:nowrap;}
.lbc-wrap button.lbc-wiki-btn:hover:not(:disabled),.lbc-wrap button.lbc-rec-all:hover,.lbc-wrap .lbc-sy-acts button:hover:not(:disabled){border-color:var(--c-ink)!important;}
.lbc-wrap button.lbc-wiki-btn:disabled,.lbc-wrap .lbc-sy-acts button:disabled{opacity:.45;cursor:default;}
.lbc-wrap button.lbc-rec-all{margin-top:10px;}
.lbc-recent{padding:10px 5px 40px;overflow-x:auto;}
.lbc-recent[hidden]{display:none!important;}
.lbc-recent-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin:0 0 16px;}
.lbc-recent-t{font:600 16px/1.4 var(--f-serif);}
.lbc-recent-sub{font-size:var(--fs-small);color:var(--c-muted);}
.lbc-rpager{display:flex;align-items:center;justify-content:center;gap:14px;margin-top:18px;}
.lbc-rpage{font:italic 15px/1 var(--f-latin);font-variant-numeric:var(--num-feat);color:var(--c-muted);}
/* 1026 SYNC：上次 / 下次是可点的格子；下面一行「立即同步 · 查看同步记录」 */
.lbc-wrap button.lbc-sy-cell{display:block;text-align:left;min-width:0;height:auto!important;padding:0!important;margin:0!important;border:0!important;background:transparent!important;box-shadow:none!important;color:inherit;font:inherit;cursor:pointer;border-radius:4px;}
.lbc-wrap button.lbc-sy-cell:hover .lbc-sy-big{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:5px;}
.lbc-sy-acts{display:flex;flex-wrap:wrap;gap:8px;padding-top:12px;border-top:1px solid var(--c-line);}
/* 统一字体规则：数字一律 Cormorant 等宽数字，正文 / 小字只用两档 */
.lbc-rec li,.lbc-sy-row{font-size:var(--fs-body);}
.lbc-sy-k,.lbc-rec-c,.lbc-fig-l,.lbc-sy-freq,.lbc-sy-note{font-size:var(--fs-small);}
.lbc-fig-n,.lbc-sy-big,.lbc-sy-row b,.lbc-rec time,.lbc-subcat-n{font-variant-numeric:var(--num-feat);}
.lbc-menu .lbc-menu-label{font-size:11px;letter-spacing:.12em;color:var(--text-faint);}
/* 窄屏 / 手机（§9）：分类行和控制行换行；控制行右组换到下一行、搜索框撑满；「管理」退到标题上面一行 */
@media(max-width:700px){.lbc-wrap{padding:12px 6px 0;}.lbc-head{display:flex;flex-direction:column;}.lbc-titleblock{padding:0;gap:2px 14px;}.lbc-tools{position:static;order:-1;align-self:flex-end;margin:0 0 8px;}
.lbc-cats{gap:4px 22px;font-size:16.5px;margin-top:8px;}.lbc-wrap .lbc-ctl.lbc-ctl-piece{gap:0 16px;margin-top:6px;padding-bottom:6px;}
.lbc-wrap .lbc-ctl-piece.lbc-blk-search{flex:1 1 100%;}.lbc-topics{padding-left:0;}
.lbc-ctitle{font-size:14.5px;}.lbc-card-more{opacity:1;}.lbc-selbar button{padding:6px 10px;}}
/* 1027b 她（第二次说清）：目录页就要雕刻字 + Cormorant 斜体数字（「就像 OVERVIEW 这种」），但四块风格统一、大小别差太多。
   数字只有三档：大 --lbc-num-lg（上次 / 下次同步、Token、概览四个数一样大，都斜体 400）· 行尾 --lbc-num（今日新增、上限、摘要里的数）· 小 --lbc-num-sm（日期、说明、柱子刻度） */
/* 1027b：数字字体里混着的中文（「0 篇」「人民币估算」）——Cormorant 没有中文，浏览器会把落下去的宋体硬斜成假斜体。
   这个字面（「LB CJK Upright」，在 lb-page-lib 的 brandFontCss 里）只管中文码段、自己声明成 italic：斜体文字里的中文就用它（= 衬线中文原样直立），数字照旧落到 Cormorant。 */
.lbc-wrap{--lbc-num-lg:clamp(24px,8cqi,34px);--lbc-num:15px;--lbc-num-sm:13px;font-synthesis-style:none;}
/* 1027b 她（第三次）：「字体都不一样，统一」——边栏四块里的中文只用一种：衬线中文、直体（概览 / 全部收藏 / 后台每日上限 / 列表标题 / 按钮一样）；
   数字和拉丁字母 Cormorant 斜体；中文混在数字里（「0 篇」「人民币估算」）落到衬线中文，且不许浏览器硬斜（font-synthesis-style:none，整页都关） */
/* 直立中文字面只给边栏四块（挂到全页 / 页头会让首开慢 8–15ms；边栏是首帧之后才画的） */
.lbc-mod{--f-latin:"LB CJK Upright",var(--lb-font-num);}
.lbc-mod{--f-sans:"LB Digits",var(--f-serif);--f-serif:"LB Digits",var(--lb-font-serif);}
.lbc-mod,.lbc-mod *{font-variant-numeric:lining-nums tabular-nums!important;}   /* Cormorant 默认是高低不齐的旧式数字：边栏里一律等高（font: 简写会把它重置，所以每个元素都给） */
/* 标签 / 名字里的数字（「近 7 天」「样例 4」）落 Cormorant 斜体；字母和中文是衬线直立（「AI」「Token」是名字，不斜） */
.lbc-mod .lbc-lab small{letter-spacing:.1em;}
.lbc-mod .lbc-sy-big,.lbc-mod .lbc-fig-n{font:italic 400 var(--lbc-num-lg)/1.05 var(--f-latin);letter-spacing:0;}
.lbc-mod .lbc-sy-big i{font-style:italic;}
.lbc-mod .lbc-sy-row b,.lbc-mod .lbc-sy-row.is-tot b{font:italic 500 var(--lbc-num)/1.2 var(--f-latin);}
.lbc-mod .lbc-fold-sum i{font-size:inherit;color:inherit;}   /* 1027b 她：折起来那一行是一句话——字、数一个颜色一个大小 */
.lbc-mod :is(.lbc-rec time,.lbc-sy-cap,.lbc-bar span,.lbc-days){font-size:var(--lbc-num-sm);}
.lbc-mod .lbc-rec time{font-style:italic;}
/* 最近导入：列表框高 = 条数（调整里 2 / 4 / 6 / 8），框里往下滚接着出更早的 */
.lbc-rec{max-height:calc(var(--lbc-rec-rows,6) * (var(--fs-body,13.5px) * 1.45 + 21px));overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;}
/* 拖出来的高度：内容超出在块里滚（最近导入是列表那一框） */
.lbc-mod.has-h>.lbc-mod-body{max-height:var(--lbc-m-h);overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;}
.lbc-mod-recent.has-h>.lbc-mod-body{max-height:none;overflow:visible;}
.lbc-mod-recent.has-h .lbc-rec{max-height:var(--lbc-m-h);}
/* 1027b 她：最近导入的帖子之间不要横线；列表框里不要浮动的滚动条（滚轮 / 触控板照样滚） */
.lbc-mod-recent .lbc-rec li{border-top:0;}
.lbc-mod-recent .lbc-rec{scrollbar-width:none;}
.lbc-mod-recent .lbc-rec::-webkit-scrollbar{display:none;}
/* 同步：「每天 18:00 · 改」点开就地改时间 */
.lbc-wrap button.lbc-sy-edit{display:inline-flex;align-items:baseline;gap:8px;width:auto;height:auto!important;padding:0!important;margin:-4px 0 10px!important;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);font:var(--fs-small)/1.5 var(--f-sans);cursor:pointer;text-align:left;white-space:normal;}
.lbc-wrap button.lbc-sy-edit:hover{color:var(--c-ink);}
.lbc-sy-pen{color:var(--c-ink);text-decoration:none;}
.lbc-sy-sched{margin:0 0 12px;padding:10px 12px;border:1px solid var(--c-line);border-radius:6px;font:var(--fs-small)/1.5 var(--f-sans);}
/* Token：天 / 周 / 月 */
.lbc-tk-seg{display:flex;gap:2px;margin:0 0 10px;}
.lbc-wrap .lbc-tk-seg button{width:auto!important;height:24px!important;padding:0 12px!important;margin:0!important;border:1px solid transparent!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--c-muted);font:var(--fs-small)/1 var(--f-sans);cursor:pointer;}
.lbc-wrap .lbc-tk-seg button:hover{color:var(--c-ink);}
.lbc-wrap .lbc-tk-seg button.is-on{border-color:var(--c-ink)!important;color:var(--c-ink);font-weight:600;}
.lbc-wrap select.lbc-tk-capsel{height:28px;padding:0 24px 0 8px;border:1px solid var(--c-line);border-radius:6px;background-color:transparent;box-shadow:none;color:var(--c-ink);font:italic 500 var(--lbc-num)/1 var(--f-latin);font-variant-numeric:var(--num-feat);cursor:pointer;}
.lbc-wrap select.lbc-tk-capsel:hover,.lbc-wrap select.lbc-tk-capsel:focus{border-color:var(--c-ink);outline:none;}
.lbc-tk-cap-row{align-items:center;}
.lbc-m-rs{display:none;}
`;
// 1021：标题 / 数字字体随包发（catalog.py 重建时拷进 _archive/fonts/），@font-face 的地址运行时拼（vault 可能挂在别的库子目录里，过 lbPath；
// 不连 Google Fonts，离线照样显示；文件不在时浏览器退回系统衬线字体）
// 1026：字体文件 / @font-face 和问收藏共用 LB.brandFontCss（lb-page-lib），只在那一处
// 1027 编排才用的样式（操作条 / 托盘 / 调整 / 列边）：第一次进编排时才挂（首开少解析一段样式）
const ARRANGE_CSS = `
.lbc-wrap.is-arranging .lbc-side{padding-left:12px;padding-right:12px;-webkit-mask-image:none;mask-image:none;}
/* 1028 她：「不像图 2 那么突兀」——平时只有一圈很淡的细框；指着 = 细框加深，选中 = 墨色细框；黑条换成白底小工具条，只在指着 / 选中时出来 */
.lbc-wrap.is-arranging .lbc-m{position:relative;outline:1px solid transparent;outline-offset:4px;border-radius:3px;cursor:grab;user-select:none;-webkit-user-select:none;transition:outline-color .15s;}
.lbc-wrap.is-arranging .lbc-top .lbc-m,.lbc-wrap.is-arranging .lbc-side .lbc-m{outline-color:var(--c-line);}
.lbc-wrap.is-arranging .lbc-m:hover{outline-color:var(--c-faint);}
.lbc-wrap.is-arranging .lbc-m.is-sel,.lbc-wrap.is-arranging .lbc-m.is-panel{outline:1.5px solid var(--c-ink);}
.lbc-wrap.is-arranging .lbc-m.is-dragging{cursor:grabbing;}
.lbc-wrap.is-arranging .lbc-side .lbc-m{margin-top:34px;}
.lbc-wrap.is-arranging .lbc-top{padding-top:42px;}   /* 第一排块的小工具条在块上方 34px：留够，别伸到编排条底下被盖住（盖住就来回闪） */
.lbc-wrap.is-arranging .lbc-top .lbc-row{margin-top:18px;}
.lbc-wrap.is-arranging .lbc-mod .lbc-lab,.lbc-wrap.is-arranging .lbc-mod .lbc-fold-sum,.lbc-wrap.is-arranging .lbc-mod .lbc-mod-body{pointer-events:none;user-select:none;}
.lbc-wrap.is-arranging .lbc-mod-bar{display:none;position:absolute;z-index:8;top:-34px;left:-5px;align-items:center;gap:1px;height:28px;padding:0 3px;box-sizing:border-box;background:var(--c-bg);color:var(--c-ink);border:1px solid var(--c-line);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.08);font:12px/1 var(--f-sans);white-space:nowrap;cursor:default;}
.lbc-wrap.is-arranging .lbc-m:hover>.lbc-mod-bar,.lbc-wrap.is-arranging .lbc-m.is-sel>.lbc-mod-bar,.lbc-wrap.is-arranging .lbc-m.is-panel>.lbc-mod-bar,.lbc-wrap.is-arranging .lbc-mod-bar:focus-within{display:flex;animation:lbc-pop .14s ease-out;}
.lbc-wrap.is-arranging .lbc-mod-bar::after{content:"";position:absolute;left:0;right:0;top:100%;height:12px;}   /* 工具条和块之间那道缝也算「指着这块」：鼠标从块挪到工具条上，工具条不消失 */
@keyframes lbc-pop{from{opacity:0;transform:translateY(3px);}to{opacity:1;transform:none;}}
.lbc-mod-bar .lbc-mb-nm{color:var(--c-muted);}
.lbc-mod-bar .lbc-mb-h{cursor:grab;width:26px;height:22px;display:grid;place-items:center;border-radius:999px;touch-action:none;flex:none;}
.lbc-mod-bar .lbc-mb-h:active{cursor:grabbing;}
.lbc-mod-bar .lbc-mb-h svg{width:10px;height:14px;}
.lbc-mod-bar .lbc-mb-nm{padding:0 8px 0 2px;font-weight:500;overflow:hidden;text-overflow:ellipsis;}
.lbc-mod-bar .lbc-mb-sep{width:1px;height:12px;background:currentColor;opacity:.3;margin:0 3px;flex:none;}
.lbc-wrap .lbc-mod-bar button.lbc-mb-sz{min-width:26px;padding:0 5px!important;}
.lbc-wrap .lbc-mod-bar button{width:auto!important;min-width:24px;height:22px!important;padding:0 7px!important;margin:0!important;border:0!important;border-radius:999px!important;background:transparent!important;color:inherit!important;box-shadow:none!important;font:inherit!important;cursor:pointer;}
.lbc-wrap .lbc-mod-bar button:hover:not(:disabled),.lbc-wrap .lbc-mod-bar button[aria-expanded="true"]{background:var(--background-modifier-hover,rgba(0,0,0,.05))!important;color:var(--c-ink)!important;}
.lbc-wrap .lbc-mod-bar button:disabled{opacity:.3;cursor:default;}
.lbc-m.is-dragging{opacity:.35;}
.lbc-drop-ind{position:fixed;z-index:60;background:var(--text-normal);border-radius:3px;pointer-events:none;transition:left .08s,top .08s,width .08s,height .08s;}
.lbc-drop-ind.is-slot{background:transparent;border:1.5px dashed var(--text-normal);box-sizing:border-box;border-radius:4px;}
.lbc-guide{position:fixed;z-index:61;width:1px;background:var(--interactive-accent,#2f6fde);pointer-events:none;}
.lbc-guide[hidden]{display:none;}
.lbc-drop-ind[hidden]{display:none;}
.lbc-wrap.is-arranging .lbc-col-edge{display:block;position:absolute;top:0;bottom:0;width:14px;margin:0 0 0 -7px!important;padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important;cursor:col-resize;z-index:4;touch-action:none;}
.lbc-col-edge::before{content:"";position:absolute;left:6px;top:0;bottom:0;width:2px;border-radius:2px;background:var(--c-faint);}
.lbc-col-edge.is-free{top:15%!important;bottom:15%!important;}
.lbc-col-edge.is-free::before{opacity:0;transition:opacity .15s;}
.lbc-row:hover>.lbc-col-edge.is-free::before,.lbc-col-edge.is-free.is-on::before,.lbc-col-edge.is-free:focus-visible::before{opacity:1;}
.lbc-col-edge:hover::before,.lbc-col-edge:focus-visible::before,.lbc-col-edge.is-on::before{background:var(--c-ink);}
.lbc-col-edge .lbc-ce-w{position:absolute;top:6px;left:12px;padding:3px 8px;border-radius:999px;background:var(--c-ink);color:var(--c-bg);font:12px/1 var(--f-sans);white-space:nowrap;display:none;}
.lbc-col-edge.is-on .lbc-ce-w,.lbc-col-edge:focus-visible .lbc-ce-w{display:block;}
/* 1027b 拉虚线边框改大小：下边框调高、左 / 右边框调宽（并排时） */
.lbc-wrap.is-arranging .lbc-m-rs:not([hidden]){display:block;position:absolute;z-index:4;margin:0!important;padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important;touch-action:none;}
.lbc-wrap.is-arranging .lbc-m-rs-y{left:-8px;right:-8px;bottom:-14px;height:12px;cursor:ns-resize;}
.lbc-wrap.is-arranging .lbc-m-rs-x{top:-8px;bottom:-8px;right:-14px;width:12px;cursor:ew-resize;}
.lbc-wrap.is-arranging .lbc-m-rs-x.is-left{right:auto;left:-14px;}
.lbc-m-rs::before{content:"";position:absolute;border-radius:2px;background:var(--c-ink);opacity:0;transition:opacity .15s;}
.lbc-m-rs-y::before{left:0;right:0;top:5px;height:2px;}
.lbc-m-rs-x::before{top:0;bottom:0;left:5px;width:2px;}
.lbc-m-rs:hover::before,.lbc-m-rs:focus-visible::before,.lbc-m-rs.is-on::before{opacity:1;}
.lbc-m-rs-y::after{content:"";position:absolute;left:50%;top:2px;width:28px;height:8px;margin-left:-14px;border-radius:999px;background:var(--c-bg);border:1.5px solid var(--c-faint);box-sizing:border-box;}
.lbc-m-rs-y:hover::after,.lbc-m-rs-y.is-on::after{border-color:var(--c-ink);}
/* 模块里展开的「调整」 */
.lbc-mp{position:relative;z-index:2;margin:0 0 14px;padding:12px 14px;border:1px solid var(--c-ink);border-radius:4px;background:var(--c-bg);color:var(--c-ink);font:13px/1.5 var(--f-sans);zoom:1;}
.lbc-mp-h{display:flex;align-items:center;gap:8px;margin:0 0 8px;font-weight:600;}
.lbc-mp-h .lbc-mp-save{margin-left:auto;font-weight:400;font-size:12px;color:var(--c-muted);}
.lbc-mp-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:6px 0;}
.lbc-mp-row>label,.lbc-mp-k{color:var(--c-muted);font-size:12px;min-width:3.5em;}
.lbc-mp-row label.lbc-mp-ck{color:var(--c-ink);font-size:13px;min-width:0;display:inline-flex;align-items:center;gap:4px;}
.lbc-wrap .lbc-mp select,.lbc-wrap .lbc-mp input[type=text],.lbc-wrap .lbc-mp input[type=number]{height:28px;padding:0 8px;border:1px solid var(--c-line);border-radius:4px;background:var(--c-bg);color:var(--c-ink);font:13px var(--f-sans);max-width:100%;box-sizing:border-box;}
.lbc-wrap .lbc-mp input[type=text]{flex:1 1 140px;min-width:0;}
.lbc-wrap .lbc-mp input[type=number]{width:84px;}
.lbc-wrap .lbc-mp button{width:auto!important;height:26px!important;padding:0 10px!important;margin:0!important;border:1px solid var(--c-line)!important;border-radius:999px!important;background:var(--c-bg)!important;color:var(--c-ink)!important;box-shadow:none!important;font:12.5px/1 var(--f-sans)!important;cursor:pointer;white-space:nowrap;}
.lbc-wrap .lbc-mp button:hover:not(:disabled){border-color:var(--c-ink)!important;}
.lbc-wrap .lbc-mp button:disabled{opacity:.4;cursor:default;}
.lbc-mp-note{margin:6px 0 0;font-size:12px;color:var(--c-muted);}
.lbc-mp-note.is-fail{color:var(--lb-danger);}
.lbc-mp-cats{display:flex;flex-direction:column;gap:4px;margin:4px 0;}
.lbc-mp-cat{display:flex;align-items:center;gap:6px;}
.lbc-mp-cat .lbc-mp-n{font:italic 13px/1 var(--f-latin);color:var(--c-muted);min-width:2em;text-align:right;}
.lbc-mp .lb-sched{margin-top:4px;}
.lbc-wrap.is-arranging .lbc-arrange-tray{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 0 14px;border-bottom:1px solid var(--c-ink);position:sticky;top:var(--lbc-tray-top,0px);z-index:6;background:var(--background-primary);}
.lbc-arrange-tray .lbc-at-k{font:700 11px/1 var(--f-display);letter-spacing:.26em;color:var(--c-ink);}
.lbc-arrange-tray .lbc-at-save{margin-left:auto;font-size:12px;color:var(--c-muted);}
.lbc-arrange-tray .lbc-at-save.is-fail{color:var(--lb-danger);}
.lbc-arrange-tray .lbc-at-hint{order:9;flex:1 1 100%;font-size:12px;line-height:1.6;color:var(--c-muted);}
.lbc-arrange-tray .lbc-at-row{order:8;flex:1 1 100%;display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;}
.lbc-arrange-tray .lbc-at-row[hidden]{display:none;}
.lbc-arrange-tray .lbc-at-row label{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--c-muted);}
.lbc-wrap .lbc-arrange-tray select{height:28px;padding:0 8px;border:1px solid var(--c-line);border-radius:4px;background:var(--c-bg);color:var(--c-ink);font:13px var(--f-sans);}
.lbc-wrap .lbc-arrange-tray button{width:auto!important;height:28px!important;padding:0 12px!important;margin:0!important;border:1px solid var(--c-ink)!important;border-radius:999px!important;background:var(--c-bg)!important;color:var(--c-ink)!important;box-shadow:none!important;font:13px/1 var(--f-sans)!important;cursor:pointer;white-space:nowrap;}
.lbc-wrap .lbc-arrange-tray button:hover:not(:disabled),.lbc-wrap .lbc-arrange-tray button[aria-expanded="true"]{background:var(--c-ink)!important;color:var(--c-bg)!important;}
.lbc-wrap .lbc-arrange-tray button:disabled{opacity:.45;cursor:default;}
.lbc-wrap .lbc-arrange-tray button.is-dash{border-style:dashed!important;color:var(--c-muted)!important;}
.lbc-arrange-tray .lbc-at-shelf{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:0 6px;}
.lbc-arrange-tray .lbc-at-sk{font-size:12px;color:var(--c-muted);margin-right:2px;}
.lbc-arrange-tray .lbc-at-empty{font-size:12px;color:var(--c-faint);}
.lbc-arrange-tray .lbc-at-shelf button{animation:lbc-pop .2s ease-out;}
.lbc-wrap .lbc-arrange-tray input.lbc-at-rename{height:28px;width:9em;padding:0 10px;border:1px solid var(--c-ink);border-radius:999px;background:var(--c-bg);color:var(--c-ink);font:12.5px var(--f-sans);}
.lbc-wrap.is-arranging .lbc-title-text{cursor:text;}
.lbc-title-text.is-editing{outline:none;background:var(--background-modifier-hover,rgba(0,0,0,.05));border-radius:4px;}
.lbc-wrap .lbc-arrange-tray button.is-dash:hover{color:var(--c-bg)!important;}
.lbc-wrap .lbc-arrange-tray button.is-solid{background:var(--c-ink)!important;color:var(--c-bg)!important;}
`;
LB.style('lbc-style', LB.brandFontCss() + CSS);

// ── 挂载点（C4）：dv.container 后面的兄弟 host；Dataview 重跑只清 container，碰不到页面 ──
const mount = LB.mountHost('lbc-host');
const wrap = mount.createEl('div', { cls: 'lbc-wrap' + (simplePage ? ' lbc-simple' : '') });
// 缺插件 / 插件版本对不上 / 手机：说一句、返回 null（电脑上旧实例缺新方法时先重载一次插件）
async function want(method) {
  try { return await LB.ensure(method); }
  catch (e) { LB.say(e?.message || String(e), { kind: mobile ? 'info' : 'error' }); return null; }
}

// 数据读不到 / 格式对不上：整页只放一句话 + 电脑上给 [刷新目录]（refresh=false 时不给按钮，比如数据比页面新该先更新插件）
function stopPage(text, { refresh = true } = {}) {
  const box = wrap.createEl('div', { cls: 'lbc-empty lbc-nodata' });
  box.createEl('p', { cls: 'lbc-empty-text', text });
  if (!mobile && refresh) {
    const b = box.createEl('div', { cls: 'lbc-empty-actions' }).createEl('button', { text: '刷新目录', cls: 'mod-cta' }); b.type = 'button';
    b.onclick = async () => {
      const p = await want('refreshCatalog'); if (!p) return;
      const done = LB.busy(b, '正在刷新目录…');
      try { await p.refreshCatalog(); done(); dv.component?.render?.(); }
      catch (e) { done(); LB.say('目录没刷新上：' + (e?.message || e), { kind: 'error' }); }
    };
  }
}
let data;
try { data = await LB.data.load(); }
catch {
  // C8：数据读不到——说清怎么办；电脑上给 [刷新目录]
  stopPage(mobile ? '目录数据还没生成：在电脑上点右上「…」→ 刷新目录。' : '目录数据还没生成：点右上「…」→ 刷新目录');
  return;
}
// 1025 开源前 P0：格式号对不上（旧数据 / 旧插件）就停在这儿，不按猜的形状读 items——先检查再解析，提示才来得及显示
if (LB.schemaBlocks(data)) {
  stopPage(LB.schemaIssue(data), { refresh: Number(data.schema) < LB.CATALOG_SCHEMA });
  return;
}
// 1020 来源（她定）：src='' 是她自己的收藏；她在 TG 发给 Fable 的和 Fable 自己收的都是「fable」（1025 起不再单列「聊天分享」）、CC / GPT 按项目收的（项目名）
// 各是一个来源（catalog.py 的 src，规则在 domain.py）。目录默认只看她自己的收藏，「来源 ▾」切；已收藏页不分来源。
// items = 当前来源下的那些（下面所有计数 / 排名 / 专辑都按它算），allItems = 全部
let allItems = data.items || [];
let activeSrc = '';   // ''=我的收藏 / '*'=全部 / 其它=那个来源
const srcOf = it => (typeof it.src === 'string' ? it.src : '');
let items = [];
function applySrc() { items = starredPage || activeSrc === '*' ? allItems : allItems.filter(it => srcOf(it) === activeSrc); }
applySrc();
// 笔记当前的标签（后台插件增删标签不必重建目录）：读 Obsidian 的元数据缓存，不走 dv.page 逐篇序列化
function tagsOf(it) {
  if (!it.note) return null;
  try { const fm = app.metadataCache?.getCache?.(lbPath(it.note))?.frontmatter; if (fm && fm.tags !== undefined) return typeof fm.tags === 'string' ? [fm.tags] : Array.from(fm.tags || []); } catch {}
  const page = dv.page?.(lbPath(it.note));
  if (page && page.tags !== undefined) return typeof page.tags === 'string' ? [page.tags] : Array.from(page.tags || []);
  return null;
}
// 10-04：刚在卡片上改过标签的那篇，Obsidian 的元数据缓存要过一会儿才跟上——缓存还是旧的时候别把刚存的标签读回去
function refreshTags() {
  let changed = 0;
  for (const it of items) {
    const tags = tagsOf(it);
    if (it._pendingTags) { if (tags && JSON.stringify(tags) === it._pendingTags) delete it._pendingTags; else continue; }
    if (tags && JSON.stringify(tags) !== JSON.stringify(it.tags || [])) { it.tags = tags; try { searchCache.delete(it); } catch {} changed++; }
  }
  return changed;
}
refreshTags();

// ── 10-10 索引树：_archive/index-data.json（Python 解析 索引.md、归类好的；页面只读，这里不解析、不归类） ──
// 第一级 = 顶部分类 tab（activeCat 存节点路径，「美食/菜谱」）；选中一个大类时下面一行它的二级小标签；「索引」= 横向分叉树。
// 没有这份文件（旧后端 / 还没重算过）= 照旧按 catalog-data 的 cats_order / items[].cats。
const UNC = '∅未归类', UNC_LABEL = '未归类';   // 「未归类」那一档在页面里的键（节点路径不会以 ∅ 开头，她把一个节点叫「未归类」也不撞）
let idx = null, idxRev = 0;
const idxByPath = new Map(), idxSets = new Map();
let idxRaw = null;
async function loadIndex() {
  let next = null, raw = null;
  try {
    raw = await app.vault.adapter.read(lbPath('_archive/index-data.json'));
    if (raw === idxRaw && idx) return false;          // 10-11：内容一字没变（同一次改动的第二个通知）：什么都不动
    const v = JSON.parse(raw);
    if (v && Array.isArray(v.nodes) && Array.isArray(v.roots)) next = v;
  } catch {}
  idxRaw = next ? raw : null;
  idx = next; idxByPath.clear(); idxSets.clear(); idxRev++;
  for (const n of idx?.nodes || []) if (n && typeof n.path === 'string') idxByPath.set(n.path, n);
  // 索引是用更旧的目录数据算的（重建目录时没抢到锁之类）：新收的几篇哪类都不在——请插件重算一次（每对版本只请一次）
  const built = Date.parse(data?.built_at || ''), at = Date.parse(idx?.catalog_built_at || '');
  const pair = `${idx?.catalog_built_at}|${data?.built_at}`;
  if (idx && Number.isFinite(built) && (!Number.isFinite(at) || built > at) && pair !== idxRebuildAsked) {
    idxRebuildAsked = pair;
    try { provider()?.indexRebuild?.(); } catch {}
  }
  return true;
}
let idxRebuildAsked = '';
// 10-11「建议新增」也能像节点一样筛（activeCat = '∅建议:<id>'）：右边看这些笔记，上面一行「加进索引 / 不要」
const PROP = '∅建议:';
const proposalOf = c => (typeof c === 'string' && c.startsWith(PROP) ? (idx?.proposals || []).find(p => p.id === c.slice(PROP.length)) || null : null);
function nodeIds(path) {
  if (!idx || !path) return null;
  if (idxSets.has(path)) return idxSets.get(path);
  const ids = path === UNC ? idx.unclassified?.items : path.startsWith(PROP) ? proposalOf(path)?.items : idxByPath.get(path)?.items;
  const s = Array.isArray(ids) ? new Set(ids) : null;
  idxSets.set(path, s);
  return s;
}
const catLabel = c => (c === UNC ? UNC_LABEL : proposalOf(c) ? '建议新增「' + proposalOf(c).name + '」' : String(c || '').split('/').join(' › '));
function knownCat(c) {
  if (typeof c !== 'string' || !c) return false;
  if (!idx) return (data.cats_order || []).includes(c);
  if (c.startsWith(PROP)) return !!proposalOf(c);
  return c === UNC ? !!idx.unclassified?.count : idxByPath.has(c);
}
function inCat(it) {
  if (!activeCat) return true;
  const s = nodeIds(activeCat);
  if (!(s ? s.has(it.id) : (it.cats || []).includes(activeCat))) return false;
  for (const f of activeFacets) { const fs = facetIds(f); if (!fs || !fs.has(it.id)) return false; }
  return true;
}
// 10-11 细分标签（她：大类最多 3 级，下面还能细分 tag，一篇可以有几个——空气炸锅 + 牛排）：选中节点的 facets，多选 = AND
let activeFacets = [], facetNode = '';
const facetsOf = path => (idxByPath.get(path)?.facets || []).filter(f => f && f.name);
function facetIds(name) {
  const key_ = 'facet\u0001' + activeCat + '\u0001' + name;
  if (idxSets.has(key_)) return idxSets.get(key_);
  const f = facetsOf(activeCat).find(x => x.name === name);
  const set = f ? new Set(f.items || []) : null;
  idxSets.set(key_, set);
  return set;
}
// 筛选结果只跟「选中的这一类有哪些篇 + 选了哪些细分标签」有关：索引重算了但这一类篇目没变 → 结果集的键不变，网格一动不动
function selSig() {
  if (!activeCat) return '';
  const ids = nodeIds(activeCat);
  let h = 0;
  for (const id of ids || []) for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return `${ids ? ids.size : -1}:${h}:${activeFacets.join('\u0001')}:${activeFacets.map(f => facetIds(f)?.size ?? -1).join(',')}`;
}
await loadIndex();

// ── 页面状态 ──
let committed = '', lastRaw = '';
let activeCat = '', todayOnly = false, todoOnly = false, mediaFilter = '', starOnly = starredPage;
// 1026 她（04:44 要先切瀑布流、再切视频、再切附件，反复选）：筛选条拆成几个维度，维度之间叠加（AND）、维度里面单选：
//   范围（全部 / 今日新增 / 已收藏 / ★主题，仍是单选）· 类型 mediaFilter（图文 image / 视频 video / 附件 attachment）· Tag activeTag · 平台 activePlat · 排序（时间胶囊）。
//   分类行 / 子类照旧。换视图（瀑布流 / Wiki / 最近导入全部）一律不清筛选
let activeTag = '', activePlat = '';
let indexView = false;                    // 10-10「索引」视图开着（网格藏起来）
const foldOverride = new Map();           // 索引图里手动展开 / 收起过的节点：路径 → true 展开 / false 收起（默认：第二级以下收起）
// 10-04 导入时间（catalog-data 的 ts = 首次入库时间）：排序 ''=默认 / 'recent'=最近导入；范围 ''=全部 / today / 7d / 30d / custom
let timeSort = '', timeRange = '', timeFrom = '', timeTo = '';
let activeTopic = '', topicBar = null, activeAlbum = '';   // 1019 专辑：她在小红书里分的组（目录项 albums 字段），和标签 / 主题分开
let selectMode = false; const selected = new Set();
let exportImages = true;
let dataRev = 0;            // C2：只有拿到新数据 / 删除成功 / 有搜索词时标签变了才 +1
let stale = false;          // F4：看不见时磁盘上的 catalog-data 变了，露出来再刷新
let leaving = false;        // 点开一篇（同一窗格）之后这一页就要被换掉了：别再记滚动

// 卸载清理（C4）：ResizeObserver、预热、打字防抖、Ctrl 滚轮
const cleanups = [];
// 事件订阅也随页面一起暂存 / 拆（不挂 dv.component.registerEvent：组件卸载时会被强行摘掉）
function lbEvent(emitter, ref) { LB.onUnload(() => { try { emitter.offref(ref); } catch {} }); return ref; }
LB.onUnload(() => { for (const f of cleanups.splice(0)) { try { f(); } catch {} } });   // 1019：走 LB.onUnload，切走暂存时不拆

// 数据变了（同步进来新的、删了、挂了附件）：不重建整页，只换数据再画卡片（卡片按 id 复用）
// strict：读失败就抛（reuseDom 的 update 失败不推进版本，下次重跑重试；F4）
async function refresh({ strict = false } = {}) {
  let v = null, next;
  try { v = await LB.data.version(); next = await LB.data.load(); }
  catch (e) { if (strict) throw e; return false; }
  // 新数据格式对不上：不换数据、不解析，页面留着上一版，标题下说该做什么
  if (LB.schemaBlocks(next)) { paintSchema(next); return false; }
  data = next; allItems = data.items || []; applySrc();
  await loadIndex();
  if (activeCat && !knownCat(activeCat)) activeCat = '';
  refreshTags(); dataRev++; stale = false; paintSchema();
  startWarm();
  renderCatBar();
  withAnchor(() => render());
  paintProblems();
  sideApi?.paintData();
  const view = root.__lbView;
  if (view && v) view.version = v;   // 已经是新数据了：下一次 Dataview 重跑别再更新一遍
  return true;
}
function attachmentPanel(list) { want('openAttachments').then(p => p?.openAttachments(list, () => refresh())); }
// 10-10：分类就是 索引.md 的第一级——「管理分类」/ 右键一个分类 = 打开 索引.md（右键的那一类直接跳到那一行）；旧后端没有索引才走旧的分类弹窗
function editCategories(sel = '') {
  if (idx) { openVaultFile(idx.file || '索引.md', sel ? idxByPath.get(sel)?.line : null); return; }
  want('openCategories').then(p => p?.openCategories(data.cats || [], sel, () => refresh()));
}
// 打开库里一个文件（索引.md / 草稿 / wiki）：同一窗格（§5.4）；给了行号就滚到那一行。不要插件，手机上也能用
async function openVaultFile(rel, line = null) {
  const f = app.vault.getAbstractFileByPath(lbPath(rel));
  if (!f) { LB.say(`找不到 ${rel}：先刷新一次目录`, { kind: 'error' }); return; }
  leaving = true;
  try {
    const leaf = app.workspace.getLeaf ? app.workspace.getLeaf(false) : null;
    if (leaf?.openFile) await leaf.openFile(f, Number(line) > 0 ? { eState: { line: Number(line) - 1 } } : undefined);
    else await app.workspace.openLinkText(lbPath(rel), '', false);
  } catch (e) { leaving = false; LB.say('没打开：' + (e?.message || e), { kind: 'error' }); }
}

// ── 顶栏（吸顶）：标题「Collections +」+ 标题下那一行 + 搜索 + 页面导航 + 大类条 + 多选栏 ──
const top = wrap.createEl('div', { cls: 'lbc-top' });
const head = top.createEl('div', { cls: 'lbc-head' });
const titleBlock = head.createEl('div', { cls: 'lbc-titleblock' });
const titleRow = titleBlock.createEl('div', { cls: 'lbc-titlerow' });
// 10-03：大标题可改（「…→改标题」，存插件设置 catalogTitle；空 = Collections）
const titleOf = LB.brandTitleText;   // 1026：和问收藏同一个来源（lb-page-lib）
const titleText = titleRow.createEl('span', { cls: 'lbc-title' });
// 1021 雕刻斜体大标题：字上再叠一层同样的字（data-text → ::after，描边用底色、往左错一点）= 一道刻线；改标题时 data-text 跟着换（setTitle）
const titleLabel = titleText.createEl('span', { cls: 'lbc-title-text lbc-engr', text: titleOf() });
titleLabel.dataset.text = titleOf();
// 1026 她：放大 / 改了长标题时标题撑出框——字号按「这一行能放多宽 ÷ 标题大概几个字宽」算（CSS --lbc-title-em，Cinzel 大写约 0.78em 一个字，中文 1em）
const titleEm = t => Math.max(4, [...t].reduce((n, ch) => n + (/[　-鿿＀-￯]/.test(ch) ? 1.05 : /\s/.test(ch) ? 0.35 : 0.8), 0) + 0.9);
function setTitle() { const t = titleOf(); if (titleLabel.textContent !== t) titleLabel.setText(t); if (titleLabel.dataset.text !== t) titleLabel.dataset.text = t; const em = titleEm(t).toFixed(2); if (titleText.style.getPropertyValue('--lbc-title-em') !== em) titleText.style.setProperty('--lbc-title-em', em); }
setTitle();
// 「编排 / 管理」（1027：不属于任何模块——标题挪走 / 移除了也还在）：吸顶区第一个子节点，宽屏绝对定位在右上角，窄了 / 编排中退成最上面一行
const tools = top.createEl('div', { cls: 'lbc-tools' });
top.insertBefore(tools, head);
const importButton = mobile ? null : titleText.createEl('button', { cls: 'lbc-import lbc-engr', text: '+' });
if (importButton) importButton.dataset.text = '+';
// F4：标题下那一行拆成三块——计数（只是字）· 可能相关（跳到那一组）· 更新（打开同步记录）
const subLine = titleBlock.createEl('div', { cls: 'lbc-subline' });
// 1027b 她：「标题应该这样（计数行在标题右边），现在怎么到下面去了」——筛选时计数行变长，标题照旧按整行宽度定字号，计数行就被挤下去。
// 量计数行的实际宽度写进 --lbc-sub-w（+ 22px 间距），标题字号让出这一截；只在它真的变了时写（不来回抖）
let subW = -1;
// 计数行太长（带着「数据较旧」这类提醒、超过整行 45%）就不让位：让它照旧换到下面，标题不被压成小字
function fitSubline() {
  // 1028 计数行是自己的一块（「计数行」），不在标题块里时标题不用给它让位
  if (subLine.parentNode !== titleBlock) { if (subW !== 0) { subW = 0; titleBlock.style.removeProperty('--lbc-sub-w'); } return; }
  const w = Math.ceil(Number(subLine.scrollWidth) || 0), full = Number(titleBlock.clientWidth) || 0;
  const want = w && full && w <= full * 0.45 ? w + 22 : 0;
  if (Math.abs(want - subW) < 2) return;
  subW = want;
  if (want) titleBlock.style.setProperty('--lbc-sub-w', want + 'px'); else titleBlock.style.removeProperty('--lbc-sub-w');
}
if (typeof ResizeObserver === 'function') { const ro = new ResizeObserver(() => fitSubline()); ro.observe(subLine); ro.observe(titleBlock); cleanups.push(() => ro.disconnect()); }
const countEl = subLine.createEl('span', { cls: 'lbc-sub lbc-count' });
const sepPossible = subLine.createEl('span', { cls: 'lbc-sub-sep', text: '·' });
const possibleLink = subLine.createEl('button', { cls: 'lbc-sub lbc-sub-link lbc-possible-link' }); possibleLink.type = 'button';
const sepUpdated = subLine.createEl('span', { cls: 'lbc-sub-sep', text: '·' });
const updatedBtn = subLine.createEl('button', { cls: 'lbc-sub lbc-sub-link lbc-updated' }); updatedBtn.type = 'button';
const staleEl = subLine.createEl('span', { cls: 'lbc-sub lbc-stale', text: '· 这台设备上的目录数据较旧' }); staleEl.hidden = true;
// 1025 开源前 P0：目录数据的格式版本和页面对不上（旧数据 / 旧插件）——同一处、同一种字，说清该做什么
const schemaEl = subLine.createEl('span', { cls: 'lbc-sub lbc-stale lbc-schema' }); schemaEl.hidden = true;
function paintSchema(d = data) { const why = LB.schemaIssue(d); schemaEl.hidden = !why; if (why) { schemaEl.setText('· ' + why); schemaEl.title = why; } }
paintSchema();
// 第 4 批（CONVENTIONS §3.3）：顶部问题入口。数字来自 _archive/problems-summary.json；「要你处理」橙色，其余灰色，都为 0 不显示
const probBtn = subLine.createEl('button', { cls: 'lbc-problems' }); probBtn.type = 'button'; probBtn.hidden = true;
// C14：「· 同步中」带上阶段，悬停看全句，点开同步记录
const syncing = subLine.createEl('button', { cls: 'lbc-sub lbc-sub-link lbc-syncing', text: '· 同步中…' }); syncing.type = 'button'; syncing.hidden = true;
// 1011：同步真进度——标题下两行：今天 X/上限 + 细条 + 歇 N 秒（倒计时）；收藏已入库 a/b（还差 n 篇）· 《正在抓的》· 约几点抓完。
// 数和文案由插件 syncProgressView / renderSyncProgress 出（状态栏同一份，样式在插件 styles.css）；刚同步完 10 分钟内一行「同步完了」。
// 插件不在（手机）就不出，退回上面那个「· 同步中」。
const syncProg = titleBlock.createEl('div', { cls: 'lb-syncprog lbc-syncprog' }); syncProg.hidden = true;
if (mobile) titleBlock.createEl('div', { cls: 'lb-mobile-note lbc-mobile-note', text: LB.MOBILE_ONLY_TEXT });
let progTimer = null, progPeriod = 0;
function paintSyncProg() {
  const p = provider();
  const view = p && typeof p.syncProgressView === 'function' ? p.syncProgressView(syncState) : null;
  if (p && typeof p.renderSyncProgress === 'function') p.renderSyncProgress(syncProg, view); else syncProg.hidden = true;
  const want = view?.resting ? 1000 : view ? 30000 : 0;   // 歇着每秒走倒计时；其余半分钟核一次（「同步完了」10 分钟后收起）
  if (want !== progPeriod) { clearInterval(progTimer); progTimer = want ? setInterval(paintSyncProg, want) : null; progPeriod = want; }
  return view;
}
cleanups.push(() => { clearInterval(progTimer); progTimer = null; progPeriod = 0; });
// 「10/16 22:42」：和 toLocaleString('zh-CN', 2-digit 月日时分, 24 小时) 同样的字，但不碰 Intl——首开第一次调 Intl 要初始化区域数据（约 13ms）
const fmtTime = v => { const d = new Date(v); if (!Number.isFinite(d.getTime())) return '—'; const p = n => String(n).padStart(2, '0'); return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
const fmtFull = v => { const d = new Date(v); if (!Number.isFinite(d.getTime())) return '—'; const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };

let syncState = null, probSummary = null, aliveChecked = false, catalogCheckedAt = null;
function regEntry(code) {
  const reg = data.state_registry || {}; code = String(code || ''); if (!code) return null;
  if (reg[code]) return reg[code];
  const dot = code.indexOf('.'), sub = dot >= 0 ? code.slice(dot + 1) : code;
  const hit = Object.keys(reg).find(k => !k.endsWith('.*') && k.slice(k.indexOf('.') + 1) === sub);
  return hit ? reg[hit] : (dot >= 0 ? reg[code.slice(0, dot) + '.*'] || null : null);
}
async function readArchiveJson(p) { try { const v = JSON.parse(await app.vault.adapter.read(lbPath(p))); return v && typeof v === 'object' ? v : null; } catch { return null; } }
const tsOf = v => { const t = Date.parse(v || ''); return Number.isFinite(t) ? t : 0; };
const numOf = (o, ...keys) => { for (const k of keys) { const v = o?.[k]; if (v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v))) return Number(v); } return null; };
function mergeSync(raw, sum) {
  const s = sum && sum.sync && typeof sum.sync === 'object' ? sum.sync : null;
  if (!s) return raw; if (!raw) return s;
  return tsOf(raw.updated_at) > (tsOf(s.updated_at) || tsOf(sum.updated_at)) ? { ...s, ...raw } : { ...raw, ...s };
}
let pageReady = false, idxPending = false;
async function reloadIndex() {
  if (!pageReady) { idxPending = true; return; }
  idxPending = false;
  if (!(await loadIndex())) return;
  perfCounts.indexReload = (perfCounts.indexReload || 0) + 1;
  if (activeCat && !knownCat(activeCat)) activeCat = '';
  if (activeFacets.length) activeFacets = activeFacets.filter(f => facetsOf(activeCat).some(x => x.name === f));
  if (indexView && !idx) indexView = false;
  renderCatBar();
  withAnchor(() => render());
}
async function refreshProblems() {
  const [raw, sum] = await Promise.all([readArchiveJson('_archive/sync-status.json'), readArchiveJson('_archive/problems-summary.json')]);
  probSummary = sum; syncState = mergeSync(raw, sum);
  // 1023：内容没变的重建不改 catalog-data（不刷屏），「核对过」的时间在 catalog-state.checked_at——判「数据较旧」时一起算
  try { catalogCheckedAt = (await readArchiveJson('_archive/catalog-state.json'))?.checked_at || null; } catch {}
  paintProblems();
  // 显示「同步中」但插件这头没在跑任务：请 Python 核一次（进程已死就落盘 INTERRUPTED），每次打开页面最多一次
  const p = provider();
  if (syncState?.state === 'running' && !aliveChecked && p && !p.running && typeof p.refreshProblemSummary === 'function') {
    aliveChecked = true; p.refreshProblemSummary().then(r => { if (r) refreshProblems(); }).catch(() => {});
  }
  checkFresh();
}
// C14：同步阶段——「3/40」这种进度就显示它，没有就取前 10 个字
function syncPhase(st) {
  const p = String(st.progress || st.message || '').trim();
  const m = p.match(/(\d+)\s*\/\s*(\d+)/);
  if (m) return { text: `· 同步中 ${m[1]}/${m[2]}`, full: p };
  if (p) return { text: '· 同步中 · ' + (p.length > 10 ? p.slice(0, 10) + '…' : p), full: p };
  return { text: '· 同步中…', full: '' };
}
function paintProblems() {
  const st = syncState || {}, s = probSummary;
  let need = numOf(s, 'needs_human') || 0; const auto = numOf(s, 'auto') || 0, gaveUp = numOf(s, 'gave_up') || 0;
  if (!s && st.state === 'blocked') need = 1;   // 还没有 problems-summary.json（老库第一次）：同步卡在要人处理时照样亮
  probBtn.empty();
  if (need) probBtn.createEl('span', { cls: 'lbc-prob-n lbc-prob-need', text: String(need) });
  // 1019 她：自动处理中的不亮数字。1027b 她：「不影响实际体验的，就别显示了」——已放弃的（某一篇的附件 / 评论没补上）也不亮，
  // 只数要你动手的；全部的还在问题记录里
  void auto; void gaveUp;
  probBtn.hidden = !need;
  const lines = [];
  if (st.state === 'blocked' || st.state === 'failed') { const why = st.detail || st.message || ''; const head_ = st.label || regEntry(st.code)?.label || ''; if (head_ || why) lines.push(head_ && why ? head_ + '：' + why : head_ || why); }
  const counts = [need && `要你处理 ${need}`].filter(Boolean);
  if (counts.length) lines.push(counts.join(' · '));
  probBtn.title = probBtn.hidden ? '' : [...lines, '点击查看问题列表'].join('\n');
  syncing.hidden = st.state !== 'running';
  if (!syncing.hidden) { const ph = syncPhase(st); syncing.textContent = ph.text; syncing.title = (ph.full ? ph.full + '\n' : '') + '点开看同步记录'; }
  const pv = paintSyncProg();
  if (pv?.running && !syncing.hidden) { syncing.textContent = '· 同步中'; syncing.title = pv.tip + '\n点开看同步记录'; }
  paintSub();
  sideApi?.paintSync();
}
async function openProblemsPanel() {
  if (mobile) { LB.say('问题列表要在电脑上看'); return; }
  const p = await want('openProblems'); if (!p) return;
  try { await p.openProblems(); } catch (e) { LB.say(e?.message || String(e), { kind: 'error' }); }
}
probBtn.onclick = () => openProblemsPanel();
// 「更新」/「同步中」：电脑上打开同步记录；手机上读 sync-log.jsonl 最后 5 行，弹个小浮层（C12）
async function openUpdated(e) {
  if (!mobile) {
    const p = await want('openSyncLog'); if (!p) return;
    try { await p.openSyncLog(); } catch (err) { LB.say(err?.message || String(err), { kind: 'error' }); }
    return;
  }
  closeMenus();
  const TRIG = { manual: '手动同步', nightly: '夜跑同步', schedule: '定时同步', cli: '命令行同步', retry: '重试', import: '手动导入', repair: '自愈' };
  let rows = [];
  try { rows = String(await app.vault.adapter.read(lbPath('_archive/sync-log.jsonl'))).split('\n').filter(l => l.trim()).slice(-5).reverse().map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean); } catch {}
  const pop = document.body.createEl('div', { cls: 'lbc-synclog-pop' });
  if (!rows.length) pop.createEl('div', { cls: 'lbc-synclog-empty', text: '还没有同步记录' });
  for (const r of rows) {
    const doneOk = !!r.finished_at && !r.error;
    pop.createEl('div', { cls: 'lbc-synclog-row', text: `${fmtTime(r.started_at)} · ${TRIG[r.trigger] || '同步'} · 新收 ${Number(r.new) || 0} 篇 · ${doneOk ? '完成' : '没完成'}` });
  }
  const r = (e?.currentTarget || updatedBtn).getBoundingClientRect?.() || { left: 12, bottom: 60 };
  pop.style.left = Math.max(8, r.left) + 'px'; pop.style.top = (r.bottom + 6) + 'px';
  const close = ev => { if (ev && pop.contains(ev.target)) return; pop.remove(); document.removeEventListener('click', close, true); };
  setTimeout(() => document.addEventListener('click', close, true), 0);
  return pop;
}
updatedBtn.onclick = e => openUpdated(e);
syncing.onclick = e => openUpdated(e);
possibleLink.onclick = () => scrollToPossible();
// 文件监听（§5.7）：同步状态 / 问题汇总一变只重画入口这几个字；catalog-data 变了 800ms 防抖后核一次新鲜度（F4）
if (app.vault.on && dv.component?.registerEvent) {
  const watched = new Set([lbPath('_archive/sync-status.json'), lbPath('_archive/problems-summary.json')]);
  const dataPath = lbPath('_archive/catalog-data.json');
  const idxDataPath = lbPath('_archive/index-data.json');
  let freshTimer = null, idxTimer = null;
  const onFile = file => {
    if (watched.has(file?.path)) refreshProblems();
    else if (file?.path === dataPath) { clearTimeout(freshTimer); freshTimer = setTimeout(() => checkFresh(), 800); }
    // 10-10：她改完 索引.md 保存 → 插件重算 index-data.json → 这里 300ms 防抖后换上新的分类 / 索引图（卡片不重建）
    else if (file?.path === idxDataPath) { clearTimeout(idxTimer); idxTimer = setTimeout(() => reloadIndex(), 300); }
  };
  cleanups.push(() => { clearTimeout(freshTimer); clearTimeout(idxTimer); });
  lbEvent(app.vault, app.vault.on('modify', onFile));
  lbEvent(app.vault, app.vault.on('create', onFile));
}

// 1021 右上角「管理」细线胶囊（老的「…」菜单 openManageMenu 1027 删了）
const MANAGE_SVG = '<svg viewBox="0 0 14 14" aria-hidden="true"><rect x="1" y="1" width="5" height="5" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="8" y="1" width="5" height="5" fill="currentColor"/><rect x="1" y="8" width="12" height="5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
const manage = mobile ? null : tools.createEl('button', { cls: 'lb-manage lbc-manage' });
if (manage) { manage.type = 'button'; manage.innerHTML = MANAGE_SVG; manage.createEl('span', { text: '管理' }); }
// 1026 她（16:55「它甚至没有回收站」；分类删了内容去哪不清楚）：「管理」按用途分组——
//   整理分类：索引编辑（分类树）/ 在 索引.md 里改 / 删除一个分类（只删分类，内容不删）
//   回收站与删除：回收站（N 篇，可恢复）/ 彻底删除（在回收站里做，不能恢复）/ 怎么删一篇收藏
//   其它：导出资料 / 设置 / 刷新目录（1027：改标题 / 每行几列挪进「编排」——标题模块、收藏墙模块的「调整」，这里不再重复）
// 页面自己拼菜单（插件的 obsidian.Menu，插件不在时自制），各项调插件原有的方法
let trashCount = null;
async function readTrashCount() {
  try { const d = JSON.parse(await app.vault.adapter.read(lbPath('_archive/trash-data.json'))); trashCount = Array.isArray(d?.items) ? d.items.filter(x => x && x.has_files !== false).length : null; }
  catch { trashCount = null; }
  return trashCount;
}
const openTrash = () => LB.openPage('trash');
async function callPlugin(method, ...args) { const p = await want(method); if (!p) return; try { await p[method](...args); } catch (err) { LB.say('没做成：' + (err?.message || err), { kind: 'error' }); } }
function manageItems() {
  // 1027b 她：「管理就留索引编辑、刷新目录（手动）、导出资料、设置、回收站就行。设置放最上面」
  //   （删分类在索引树里右键 / 「改名」那一排；彻底删除在回收站里；在 索引.md 里改 = 索引条上的「编辑 索引.md」）
  return [
    { title: '设置', icon: 'settings-2', onClick: () => callPlugin('openSetupPage') },
    { separator: true },
    { title: '索引编辑', icon: 'list-tree', onClick: () => openIndexEditor() },
    { title: '刷新目录（手动）', icon: 'refresh-cw', onClick: () => callPlugin('run', ['-m', 'link_brain', 'catalog'], '刷新目录', true) },
    { title: '导出资料', icon: 'folder-open', onClick: () => callPlugin('openExportFolder') },
    { title: trashCount ? `回收站（${trashCount} 篇）` : '回收站', icon: 'trash-2', onClick: openTrash },
  ];
}
if (manage) manage.onclick = async e => {
  e?.stopPropagation?.();
  await readTrashCount();
  const r = manage.getBoundingClientRect?.() || { left: 0, bottom: 0 };
  popMenu(manageItems(), e, manage, { x: r.left, y: r.bottom + 4 });
};
// 删除一个分类：说清楚内容去哪——空分类直接删那一行；有内容的要么并进另一个分类（帖子跟过去），要么在 索引.md 里删那一行（帖子回到「未归类」）。帖子本身都不删
async function deleteCategoryFlow(path = '') {
  if (!idx) { editCategories(); return; }
  const target = path || await pickNode('删除哪个分类？（只删分类，帖子不删）');
  const n = target ? idxByPath.get(target) : null; if (!n) return;
  if (!n.count) { if (n.line && !n.keep_empty) await keepOrDropEmpty(n, 'remove', null); else openVaultFile(idx.file || '索引.md', n.line); return; }
  const into = await LB.confirm({ title: `删掉分类「${n.name}」：里面的 ${n.count} 篇帖子去哪？`,
    body: `帖子本身不会删（要删帖子请在卡片上右键「删除（移到回收站）」）。\n· 并进另一个分类：这 ${n.count} 篇跟着过去，「${n.name}」这一行删掉（能撤销）\n· 取消后可以在 索引.md 里删掉这一行：这些帖子回到「未归类」`,
    ok: '并进另一个分类…' });
  if (!into) { LB.say(`没删。要让这 ${n.count} 篇回到「未归类」，在 索引.md 里删掉「${n.name}」那一行`, { actions: n.line ? [{ label: '打开 索引.md', run: () => openVaultFile(idx.file || '索引.md', n.line) }] : [] }); return; }
  const to = await pickNode(`把「${n.name}」并进…（${n.count} 篇跟过去，帖子不删）`, { here: n.path });
  if (to) await treeEdit('merge', n, { to });
}
// 1022 第 5 段「编排」胶囊（只桌面目录页：手机 / 星标页没有边栏）：点了进编排，再点或「结束编排」/ Esc 退出
// 1027：插件没开就没有「编排」（只读：布局存不下来，不让她白排一通）
const GRIP_SVG = '<svg viewBox="0 0 10 14" aria-hidden="true"><g fill="currentColor"><circle cx="2.5" cy="2.5" r="1.4"/><circle cx="7.5" cy="2.5" r="1.4"/><circle cx="2.5" cy="7" r="1.4"/><circle cx="7.5" cy="7" r="1.4"/><circle cx="2.5" cy="11.5" r="1.4"/><circle cx="7.5" cy="11.5" r="1.4"/></g></svg>';
const arrangeBtn = mobile || simplePage || !provider()?.settings ? null : tools.createEl('button', { cls: 'lb-arrange lbc-arrange' });
if (arrangeBtn) {
  arrangeBtn.type = 'button'; arrangeBtn.innerHTML = GRIP_SVG; arrangeBtn.createEl('span', { text: '编排' });
  arrangeBtn.setAttribute('aria-pressed', 'false');
  if (manage) tools.insertBefore(arrangeBtn, manage);
  arrangeBtn.onclick = () => setArranging(!arranging);
}
if (importButton) importButton.type = 'button';
if (importButton) importButton.onclick = async e => {
  e.preventDefault(); e.stopPropagation();
  importButton.disabled = true; importButton.setAttribute?.('aria-busy', 'true');
  try { (await LB.ensure('openPlusMenu')).openPlusMenu(e); }
  catch (err) { LB.say('菜单没打开：' + (err?.message || err), { kind: 'error' }); }
  finally { importButton.disabled = false; importButton.removeAttribute?.('aria-busy'); }
};
// 大类筛选条 = 分类行（1021：只放「全部 + 一级分类 + 未归类」；范围筛选挪到下面的控制行）
const catBar = top.createEl('div', { cls: 'lbc-cats' });
// 控制行（1021）：边栏钮 + 范围单选 + 星标主题 + 类型 + 来源 / 专辑 / Tag；右边 排序 · 视图 · 搜索 · 问收藏。
// 1028 她（照蓝线拆）：每一组是自己的一块积木（.lbc-m），能单独拖、调宽、移除——范围 · AI 标签 · 类型 · 我的收藏 / Tag · 排序 · 视图 · 搜索 · 问收藏。
//   每块自己带 .lbc-ctl（按钮样式照旧）；标题和计数行也拆成两块。吸顶仍是 .lbc-top 一整块
const TOP_IDS = ['title', 'meta', 'cats', 'scope', 'topics', 'types', 'albums', 'picks', 'sort', 'view', 'search', 'ask'];
const CTL_IDS = ['scope', 'topics', 'types', 'albums', 'picks', 'sort', 'view', 'search', 'ask'];
const blocks = {};
for (const id of TOP_IDS) { const b = top.createEl('div', { cls: 'lbc-blk lbc-blk-' + id + ' lbc-m lbc-m-' + id + ' is-core' + (CTL_IDS.includes(id) ? ' lbc-ctl lbc-ctl-piece' : '') }); b.dataset.blk = id; b.dataset.m = id; blocks[id] = b; }
blocks.title.append(head); blocks.meta.append(subLine); blocks.cats.append(catBar);
const SIDE_SVG = '<svg viewBox="0 0 14 14" aria-hidden="true"><rect x="1" y="1.5" width="12" height="11" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><rect class="lbc-side-col" x="1.7" y="2.2" width="3.6" height="9.6" stroke="currentColor" stroke-width="1"/></svg>';
const sideBtn = mobile || simplePage ? null : blocks.scope.createEl('button', { cls: 'lbc-sidetoggle' });   // 星标页 / 手机没有边栏，也就没有这颗钮
if (sideBtn) {
  sideBtn.type = 'button'; sideBtn.innerHTML = SIDE_SVG;
  sideBtn.createEl('span', { cls: 'lb-visually-hidden', text: '收起 / 展开边栏' });   // 不设 aria-label / title：Obsidian 会渲染成悬浮框（她不要）
  sideBtn.onclick = () => setSideOpen(!sideOpen);
}
const scopeBox = blocks.scope.createEl('div', { cls: 'lbc-scope' });
const topicsBox = blocks.topics.createEl('div', { cls: 'lbc-scope lbc-scope-topics' });
const typesBox = blocks.types.createEl('div', { cls: 'lbc-scope lbc-scope-types' });
const albumsBox = blocks.albums.createEl('div', { cls: 'lbc-scope lbc-scope-albums' });   // 1028 她：专辑放在类型后面，直接点得到
const picksBox = blocks.picks.createEl('div', { cls: 'lbc-scope lbc-scope-picks' });
const timeTab = blocks.sort.createEl('button', { cls: 'lbc-time lbc-pill' }); timeTab.type = 'button';
timeTab.onclick = e => { e?.stopPropagation?.(); openTimeMenu(timeTab); };
const vseg = blocks.view.createEl('div', { cls: 'lbc-vseg' }); vseg.setAttribute('role', 'group');
const SEARCH_SVG = '<svg viewBox="0 0 14 14" aria-hidden="true"><circle cx="6" cy="6" r="4.6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M9.4 9.4 13 13" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
const searchBox = blocks.search.createEl('label', { cls: 'lbc-searchbox' }); searchBox.innerHTML = SEARCH_SVG;
const search = searchBox.createEl('input', { cls: 'lbc-search' });
search.type = 'search'; search.placeholder = '搜索收藏 · #标签';
const searchX = searchBox.createEl('button', { cls: 'lbc-search-x', text: '×' }); searchX.type = 'button'; searchX.hidden = true;
const paintSearchX = () => { searchX.hidden = !search.value; };
searchX.onmousedown = e => e.preventDefault();
searchX.onclick = e => { e.preventDefault(); e.stopPropagation(); search.value = ''; search.dispatchEvent(new Event('input', { bubbles: true })); paintSearchX(); search.focus(); };
search.addEventListener('input', paintSearchX);
const ask = blocks.ask.createEl('button', { cls: 'lbc-askbtn lbc-pill', text: '问收藏 →' }); ask.type = 'button';
ask.onclick = () => LB.openPage('chat');
function clearFilters({ keepStar = starredPage } = {}) { activeCat = ''; todayOnly = false; todoOnly = false; mediaFilter = ''; activeTag = ''; activePlat = ''; activeTopic = ''; activeAlbum = ''; timeRange = ''; timeSort = ''; timeFrom = ''; timeTo = ''; starOnly = keepStar; indexView = false; }
// C19：重建前记下横向位置和焦点所在的 tab，重建后还原；只有用户点 tab 引起的重建才把选中项滚进视野
function renderCatBar({ reveal = false } = {}) {
  const left = catBar.scrollLeft || 0;
  const ae = document.activeElement;
  const focusedLabel = ae && ae.classList?.contains('lbc-cat') && catBar.contains(ae) ? ae.textContent : null;
  catBar.empty();
  const mk = (label, active, on) => {
    const s = catBar.createEl('button', { cls: 'lbc-cat' + (active ? ' is-active' : ''), text: label });
    s.type = 'button'; s.setAttribute('aria-pressed', String(active));
    s.onclick = e => on(e);
    return s;
  };
  const tabClick = fn => () => { leaveSideViews(); fn(); renderCatBar({ reveal: true }); render(); scrollToResults(); };
  // 1021：「全部」= 不分类（范围 / 时间 / 搜索各管各的：范围在控制行「全部」，时间在排序胶囊里）；索引视图里点它回到瀑布流 / 列表
  mk('全部', !activeCat && !indexView, () => { if (activeCat || indexView || viewMode === 'wiki' || viewMode === 'recent') tabClick(() => { activeCat = ''; activeFacets = []; })(); });
  const hiddenCats = provider()?.settings?.hiddenCats || [];
  if (idx) {
    // 第一级节点（有篇数的）= 分类 tab；选中它或它下面任何一级都算选中这一类；点已选中的那一类 = 回到全部
    for (const p of idx.roots) {
      const n = idxByPath.get(p);
      if (!n || !n.count || hiddenCats.includes(n.name)) continue;
      const on = !indexView && (activeCat === p || activeCat.startsWith(p + '/'));
      const tab = mk(n.name, on, tabClick(() => { activeCat = (activeCat === p ? '' : p); }));
      tab.dataset.path = p;
      if (!mobile) tab.oncontextmenu = e => { e.preventDefault(); editCategories(p); };
    }
    // 1026 她：未归类是实际的兜底队列，不隐藏——0 篇也留着（淡色，点了说一句「都归好了」）
    const nUnc = idx.unclassified?.count || 0;
    const tab = mk(UNC_LABEL, !indexView && activeCat === UNC, nUnc ? tabClick(() => { activeCat = (activeCat === UNC ? '' : UNC); }) : () => LB.say('没有未归类的：每一篇都放进分类了'));
    tab.classList.add('lbc-unc-tab'); tab.dataset.n = String(nUnc);
    if (!nUnc) tab.classList.add('is-empty');
  } else {
    for (const cat of (data.cats_order || []).filter(c => !hiddenCats.includes(c))) {
      const tab = mk(cat, activeCat === cat, tabClick(() => { activeCat = (activeCat === cat ? '' : cat); }));
      if (!mobile) tab.oncontextmenu = e => { e.preventDefault(); editCategories(cat); };
    }
  }
  catBar.scrollLeft = left;
  if (focusedLabel) { const again = [...catBar.querySelectorAll('.lbc-cat')].find(b => b.textContent === focusedLabel); try { again?.focus({ preventScroll: true }); } catch { again?.focus?.(); } }
  if (reveal) { try { catBar.querySelector('.lbc-cat.is-active')?.scrollIntoView?.({ inline: 'nearest', block: 'nearest' }); } catch {} }
  paintCatFade();
  renderSubBar();
  renderScope();
  paintTime();
  paintViewSeg();
  renderTopicBar();
}
// ── 1021 范围：单选（她：原来几个开关能叠加，容易点了好几个然后懵了）。内部仍是 todayOnly / starOnly / mediaFilter / todoOnly / activeTopic，
//    但同一时间只让一个生效：点一个清掉其他；再点当前项回到「全部」。'topic:*' = 全部主题（属于任何一个星标主题的）
function scopeOf() {
  if (starOnly && !starredPage) return 'star';
  if (todayOnly) return 'today';
  if (todoOnly) return 'todo';
  if (activeTopic) return 'topic:' + activeTopic;
  return '';
}
function setScope(key) {
  todayOnly = false; todoOnly = false; activeTopic = '';
  if (!starredPage) starOnly = false;
  if (key === 'today') todayOnly = true;
  else if (key === 'todo') todoOnly = true;
  else if (key === 'video' || key === 'attachment') mediaFilter = key;   // 旧调用方：类型现在是单独一维，不清范围
  else if (key === 'star') { if (!starredPage) starOnly = true; }
  else if (typeof key === 'string' && key.startsWith('topic:')) activeTopic = key.slice(6);
}
// ── 1026 类型 / Tag / 平台：各是一维，和范围、分类、搜索叠加 ──
const TYPE_LABEL = { image: '图文', video: '视频', attachment: '附件' };
const hasAtt = it => !!it.attachment && it.attachment !== 'none';
const typeOk = it => !mediaFilter || (mediaFilter === 'video' ? it.kind === 'video' : mediaFilter === 'attachment' ? hasAtt(it) : it.kind !== 'video');
const normTag = t => String(t || '').trim().replace(/^#/, '').toLowerCase();
const tagsAll = it => [...new Set([...(Array.isArray(it.tags) ? it.tags : []), ...(Array.isArray(it.hashtags) ? it.hashtags : [])].map(normTag).filter(Boolean))];
const tagOk = it => !activeTag || tagsAll(it).includes(normTag(activeTag));
// 平台 = 数据里的 platform，没有就看 id 前缀（xhs-… = 小红书）；以后 B 站入库沿用这一套，不另做浏览页
const PLAT_NAMES = { xhs: '小红书', xiaohongshu: '小红书', bili: 'B站', bilibili: 'B站', bv: 'B站', dy: '抖音', douyin: '抖音', web: '网页', wx: '公众号' };
const platOf = it => { const id = String(it.id || ''); const p = typeof it.platform === 'string' && it.platform ? it.platform : id.includes('-') ? id.split('-')[0] : ''; return String(p || '').toLowerCase(); };
const platLabel = p => PLAT_NAMES[p] || p.toUpperCase();
const platOk = it => !activePlat || platOf(it) === activePlat;
function platCounts() { const m = new Map(); for (const it of items) { const p = platOf(it); if (p) m.set(p, (m.get(p) || 0) + 1); } return [...m.entries()].sort((a, b) => b[1] - a[1]); }
// Tag 菜单只列「当前别的条件下」出现最多的几个（越选越窄，不会选出 0 篇）
function tagCounts() {
  const m = new Map(), today = ymd(new Date());
  for (const it of items) {
    if (!passesFilters(it, today, { skipTag: true })) continue;
    for (const t of tagsAll(it)) m.set(t, (m.get(t) || 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh')).slice(0, 40);
}
function pickType(k) { mediaFilter = mediaFilter === k ? '' : k; leaveSideViews(); renderCatBar(); render(); scrollToResults(); }
function pickTag(t) { activeTag = t; leaveSideViews(); renderCatBar(); render(); scrollToResults(); }
function pickPlat(p) { activePlat = p; leaveSideViews(); renderCatBar(); render(); scrollToResults(); }
// Wiki / 最近导入全部 不是「结果」视图：在那里改了筛选就回到瀑布流看结果（筛选本身不动）
function leaveSideViews() { indexView = false; if (viewMode === 'wiki' || viewMode === 'recent') viewMode = 'grid'; }
function pickScope(key) {
  setScope(scopeOf() === key ? '' : key);
  topicAdding = false; topicArmed = '';
  leaveSideViews();
  renderCatBar(); render(); scrollToResults();
}
const topicNames = () => (Array.isArray(data.topics) ? data.topics.filter(n => typeof n === 'string' && n) : []);
const canEditTopics = () => !mobile && !!provider();
const ALBUM_TABS = 4;   // 专辑平铺几个；再多就收进「专辑 ▾」
function renderScope() {
  // 先把已经不存在的主题 / 来源 / 专辑清掉（换数据后）——计数按清完的来源算
  const names = topicNames();
  if (activeTopic && (activeTopic === '*' ? !names.length : !names.includes(activeTopic))) activeTopic = '';
  const srcs = starredPage ? [] : srcCounts();
  if (activeSrc && activeSrc !== '*' && !srcs.some(([n]) => n === activeSrc)) { activeSrc = ''; applySrc(); }
  const albums = albumCounts();
  if (!albums.some(([n]) => n === activeAlbum)) activeAlbum = '';
  const ae = document.activeElement;
  const scopeBoxes = [scopeBox, topicsBox, typesBox, albumsBox, picksBox];
  const focusedKey = ae && scopeBoxes.some(b => b.contains(ae)) ? (ae.dataset?.scope ?? ae.dataset?.type ?? null) : null;
  for (const b of scopeBoxes) b.empty();
  const today = ymd(new Date());
  let nToday = 0, nStar = 0, nVideo = 0, nAtt = 0, nTodo = 0; const topicN = new Map();
  for (const it of items) {
    if (it.date === today) nToday++;
    if (it.starred) nStar++;
    if (it.kind === 'video') nVideo++;
    if (it.attachment && it.attachment !== 'none') nAtt++;
    if (it.attachment === '待补') nTodo++;
    for (const t of Array.isArray(it.topics) ? it.topics : []) topicN.set(t, (topicN.get(t) || 0) + 1);
  }
  const cur = scopeOf();
  // 篇数放 data-n（CSS ::after 画成斜体小数字）：按钮的字还是「视频」「已收藏」，读屏 / 测试按名字找得到
  const mk = (key, label, n, on, click = null, box = scopeBox) => {
    const b = box.createEl('button', { cls: 'lbc-cat lbc-scope-tab' + (on ? ' is-active' : ''), text: label });
    b.type = 'button'; b.dataset.scope = key; b.setAttribute('aria-pressed', String(on));
    if (n != null) b.dataset.n = String(n);
    b.onclick = click || (() => pickScope(key));
    return b;
  };
  mk('', '全部', items.length, !starredPage && cur === '', starredPage ? () => LB.openPage('catalog') : null);
  mk('today', '今日新增', nToday, cur === 'today');
  // X17：「已收藏」就地筛选（星标页上它是当前页，点它回目录）
  mk('star', '已收藏', nStar, starredPage ? cur === '' : cur === 'star', starredPage ? () => LB.openPage('catalog') : null);
  if (nTodo) mk('todo', '待补附件', nTodo, cur === 'todo');
  // 前两个星标主题（topics.json 的顺序）；选中任何一个主题时控制行下面出主题行（全部主题 / 其余主题 / + 新主题）
  for (const name of names.slice(0, 2)) {
    const b = mk('topic:' + name, '', topicN.get(name) || 0, cur === 'topic:' + name, null, topicsBox);
    b.classList.add('lbc-thq');
    b.createEl('span', { cls: 'lbc-topic-star', text: '★' }); b.append(name);
  }
  // 还没有任何主题：留一个入口建第一个（要插件；手机上不出）
  if (!names.length && canEditTopics() && !starredPage) {
    const b = topicsBox.createEl('button', { cls: 'lbc-pick lbc-topic-new-tab', text: '+ 星标主题' }); b.type = 'button'; b.dataset.scope = 'topic-new';
    b.onclick = () => { topicAdding = true; topicFocusNew = true; renderTopicBar(); };
  }
  // 1026 类型（一组，组内单选、和范围叠加）；1028 起是自己的一块（「类型」），不再用细竖线隔
  const nImg = items.length - nVideo;
  for (const [k, n] of [['image', nImg], ['video', nVideo], ['attachment', nAtt]]) {
    const on = mediaFilter === k;
    const b = typesBox.createEl('button', { cls: 'lbc-cat lbc-type-tab' + (on ? ' is-active' : ''), text: TYPE_LABEL[k] });
    b.type = 'button'; b.dataset.type = k; b.dataset.n = String(n); b.setAttribute('aria-pressed', String(on));
    b.onclick = () => pickType(k);
  }
  // Tag ▾：当前条件下最多的 40 个标签，选一个再缩小
  if (!starredPage || items.length) {
    const tchip = picksBox.createEl('button', { cls: 'lbc-pick lbc-tagpick' + (activeTag ? ' is-active' : ''), text: activeTag ? `#${activeTag}` : 'Tag' });
    tchip.type = 'button'; tchip.dataset.scope = 'tag'; tchip.setAttribute('aria-pressed', String(!!activeTag));
    tchip.onclick = e => { const list = tagCounts(); popMenu([
      ...(activeTag ? [{ title: '全部 Tag（取消）', onClick: () => pickTag('') }, { separator: true }] : []),
      ...(list.length ? list.map(([t, c]) => ({ title: `#${t}（${c}）`, checked: normTag(activeTag) === t, onClick: () => pickTag(normTag(activeTag) === t ? '' : t) }))
        : [{ title: '当前条件下没有标签', disabled: true, onClick: () => {} }]),
    ], e, tchip); };
  }
  // 平台 ▾：只有两个以上平台（以后 B 站进来）才出
  const plats = platCounts();
  if (activePlat && !plats.some(([p]) => p === activePlat)) activePlat = '';
  if (plats.length > 1) {
    const pchip = picksBox.createEl('button', { cls: 'lbc-pick lbc-platpick' + (activePlat ? ' is-active' : ''), text: activePlat ? platLabel(activePlat) : '全部平台' });
    pchip.type = 'button'; pchip.dataset.scope = 'plat'; pchip.setAttribute('aria-pressed', String(!!activePlat));
    pchip.onclick = e => popMenu([
      { title: `全部平台（${items.length}）`, checked: !activePlat, onClick: () => pickPlat('') },
      { separator: true },
      ...plats.map(([p, c]) => ({ title: `${platLabel(p)}（${c}）`, checked: p === activePlat, onClick: () => pickPlat(p) })),
    ], e, pchip);
  }
  if (srcs.length) {
    // 1020 来源：默认「我的收藏」不算筛选（不高亮），切到别的来源才高亮
    const mine = allItems.length - srcs.reduce((n, [, c]) => n + c, 0);
    const label = activeSrc === '' ? '我的收藏' : activeSrc === '*' ? '全部来源' : activeSrc;
    const chip = picksBox.createEl('button', { cls: 'lbc-pick lbc-album lbc-src' + (activeSrc ? ' is-active' : ''), text: `${label} ▾` });
    chip.type = 'button'; chip.dataset.scope = 'src';
    chip.setAttribute('aria-pressed', String(!!activeSrc));
    const pick = s_ => { leaveSideViews(); activeSrc = s_; applySrc(); dataRev++; renderCatBar(); render(); scrollToResults(); };
    chip.onclick = e => popMenu([
      { title: `我的收藏（${mine}）`, checked: activeSrc === '', onClick: () => pick('') },
      { title: `全部（${allItems.length}）`, checked: activeSrc === '*', onClick: () => pick('*') },
      { separator: true },
      ...srcs.map(([n, c]) => ({ title: `${n}（${c}）`, checked: n === activeSrc, onClick: () => pick(n) })),
    ], e, chip);
  }
  // 1028 她：专辑是自己的一块（默认在类型后面）。篇数多的前 ALBUM_TABS 个直接平铺成标签（点一下筛、再点取消）；
  //   更多的收进「专辑 ▾」（选中的不在前几个时，那颗写「专辑：名字 ▾」）。没读过专辑：一颗灰的「专辑 ▾」说怎么来
  const pickAlbum = name => { leaveSideViews(); activeAlbum = name; renderCatBar(); render(); scrollToResults(); };
  const shown = albums.length > ALBUM_TABS + 1 ? albums.slice(0, ALBUM_TABS) : albums;
  for (const [n, c] of shown) {
    const on = n === activeAlbum;
    const b = albumsBox.createEl('button', { cls: 'lbc-cat lbc-scope-tab lbc-album-tab' + (on ? ' is-active' : ''), text: n });
    b.type = 'button'; b.dataset.scope = 'album:' + n; b.dataset.n = String(c); b.setAttribute('aria-pressed', String(on));
    b.onclick = () => pickAlbum(on ? '' : n);
  }
  if (albums.length > shown.length) {
    const rest = activeAlbum && !shown.some(([n]) => n === activeAlbum);
    const chip = albumsBox.createEl('button', { cls: 'lbc-pick lbc-album' + (rest ? ' is-active' : ''), text: rest ? `专辑：${activeAlbum} ▾` : '专辑 ▾' });
    chip.type = 'button'; chip.dataset.scope = 'album';
    chip.setAttribute('aria-pressed', String(!!rest));
    chip.onclick = e => popMenu([
      ...(activeAlbum ? [{ title: '全部专辑（取消筛选）', onClick: () => pickAlbum('') }, { separator: true }] : []),
      ...albums.map(([n, c]) => ({ title: `${n}（${c}）`, checked: n === activeAlbum, onClick: () => pickAlbum(n === activeAlbum ? '' : n) })),
    ], e, chip);
  } else if (!albums.length && !starredPage) {
    const chip = albumsBox.createEl('button', { cls: 'lbc-pick lbc-album-none', text: '专辑 ▾' });
    chip.type = 'button'; chip.dataset.scope = 'album';
    chip.onclick = e => popMenu([{ title: '还没读过小红书专辑（同步时会读，读完这里出专辑名）', disabled: true, onClick: () => {} }], e, chip);
  }
  if (focusedKey != null) { const again = scopeBoxes.flatMap(x => [...x.querySelectorAll('button')]).find(b => (b.dataset?.scope ?? b.dataset?.type) === focusedKey); try { again?.focus({ preventScroll: true }); } catch { again?.focus?.(); } }
}
// 排序胶囊：文字跟当前状态（默认「最新在前」；有搜索词时默认是按相关度；选了范围就是「近 7 天」等），点开仍是原来的时间菜单
function paintTime() {
  const t = timeLabel();
  if (timeTab.textContent !== t) timeTab.setText(t);
  const on = !!(timeRange || timeSort);
  timeTab.classList.toggle('is-active', on); timeTab.setAttribute('aria-pressed', String(on));
}
// ── 1021 视图：瀑布流 / 列表（新）/ 索引（功能不变，只换入口）；选择存 LB.state ──
let viewMode = 'grid', recentPage = 1;   // 1026 'recent' = 最近导入全部（翻到第几页）
function paintViewSeg() {
  // 1023 她拍板：只留瀑布流 + Wiki（空页，以后和索引统一）；列表 / 索引入口藏起来，代码不删
  // 1026：「索引」（分类树编辑）从「管理 → 索引编辑」或 Wiki 页进；开着的时候这里多一项「索引」亮着，再点回去
  const want = [['grid', simplePage ? '列表' : '瀑布流'], ...(simplePage ? [] : [['wiki', 'Wiki']]), ...(indexView && idx && !simplePage ? [['index', '索引']] : [])];
  const sig = want.map(w => w[0]).join(',');
  if (vseg.dataset.sig !== sig) {
    vseg.empty();
    for (const [k, label] of want) {
      const b = vseg.createEl('button', { cls: 'lbc-view' + (k === 'index' ? ' lbc-index-tab' : ''), text: label });
      b.type = 'button'; b.dataset.view = k; b.onclick = () => pickView(k);
    }
    vseg.dataset.sig = sig;
    vseg.hidden = want.length < 2;   // 星标页没有索引数据时只剩一项：不出这个开关
  }
  const cur = simplePage ? 'grid' : indexView && idx ? 'index' : viewMode === 'wiki' ? 'wiki' : viewMode === 'recent' ? '' : 'grid';
  for (const b of vseg.querySelectorAll('.lbc-view')) { const on = b.dataset.view === cur; b.classList.toggle('is-on', on); b.setAttribute('aria-pressed', String(on)); }
}
function pickView(k) {
  if (k === 'index') indexView = !indexView;   // 10-10「索引」：横向分叉树看分布，点一个节点 = 筛到那些笔记；再点回到原来的视图
  else { viewMode = ['list', 'wiki', 'recent'].includes(k) ? k : 'grid'; indexView = false; }
  renderCatBar({ reveal: true }); render(); scrollToResults();
}
// ── 1021 边栏：开 / 收状态存 LB.state；这里只换 class 和按钮图标（开 = 左栏实心，收 = 空心） ──
// 边栏内容（第 3 段：RECENT / SYNC / OVERVIEW）在下面「左侧边栏」一节画；开 / 收由 setSideOpen 管（.lbc-wrap.is-side-collapsed），
// 收起 / 窄屏时 CSS 让收藏墙铺满（列数按宽度 lbcColumns 自己变）。各模块折叠状态 sideFold 也存 LB.state（OVERVIEW 默认折叠）
let sideOpen = true;
const sideFold = { recent: true, sync: false, token: false, overview: true };   // 1027b 她：最近导入平时就一行「最新 …」，点开往下滚
let sideApi = null;   // 边栏画好后才有：{ paintSync(), paintData(), paintAll(), fade() }；同步状态 / 数据变了只重画边栏里那一块
function setSideOpen(on) {
  sideOpen = !!on;
  wrap.classList.toggle('is-side-collapsed', !sideOpen);
  if (sideBtn) sideBtn.setAttribute('aria-pressed', String(sideOpen));
  saveState();
  relayoutIfNeeded();
  if (sideOpen) sideApi?.paintAll();
}
// 10-10 二级小标签：选中的大类下面的子节点（带篇数）；点一个 = 筛到它，再点 = 回到这一大类；索引图里点到更深一级时多一个带 ✕ 的尾巴
let subBar = null;
function renderSubBar() {
  const rootPath = idx && activeCat && activeCat !== UNC && !indexView ? activeCat.split('/')[0] : '';
  const rootNode = rootPath ? idxByPath.get(rootPath) : null;
  const kids = (rootNode?.children || []).map(p => idxByPath.get(p)).filter(n => n && n.count);
  const depth = rootNode ? activeCat.split('/').length : 0;
  if (!rootNode || (!kids.length && depth < 3)) { if (subBar) { subBar.remove(); subBar = null; } return; }
  if (!subBar) { subBar = top.createEl('div', { cls: 'lbc-subcats' }); catBar.parentNode.insertBefore(subBar, catBar.nextSibling); barWheel(subBar); }
  const left = subBar.scrollLeft || 0;
  subBar.empty();
  for (const n of kids) {
    const on = activeCat === n.path || activeCat.startsWith(n.path + '/');
    const chip = subBar.createEl('button', { cls: 'lbc-subcat' + (on ? ' is-active' : '') });
    chip.type = 'button'; chip.dataset.path = n.path; chip.setAttribute('aria-pressed', String(on));
    chip.append(n.name);
    chip.createEl('span', { cls: 'lbc-subcat-n', text: String(n.count) });
    chip.onclick = () => { activeCat = (activeCat === n.path ? rootPath : n.path); leaveSideViews(); renderCatBar(); render(); scrollToResults(); };
    if (!mobile) chip.oncontextmenu = e => { e.preventDefault(); editCategories(n.path); };
  }
  if (depth >= 3) {
    const deep = idxByPath.get(activeCat);
    const back = activeCat.split('/').slice(0, 2).join('/');
    const chip = subBar.createEl('button', { cls: 'lbc-subcat is-active is-deep' });
    chip.type = 'button'; chip.dataset.path = activeCat; chip.setAttribute('aria-pressed', 'true');
    chip.append('› ' + (deep?.name || activeCat.split('/').pop()));
    chip.createEl('span', { cls: 'lbc-subcat-n', text: (deep ? String(deep.count) + ' ' : '') + '✕' });
    chip.onclick = () => { activeCat = idxByPath.has(back) ? back : rootPath; renderCatBar(); render(); scrollToResults(); };
  }
  subBar.scrollLeft = left;
}
// 1026 她：窗口窄了分类行被裁掉——一行放得下就照旧单行铺开（space-between），放不下就整行换行居中（不横向滚、不裁）
function catWrapWanted() {
  const kids = [...catBar.children]; const cw = Number(catBar.clientWidth) || 0;
  if (!kids.length || !cw) return null;
  const need = kids.reduce((n, el) => n + (Number(el.offsetWidth) || 0), 0) + 6 * (kids.length - 1);
  return need > cw + 1;
}
function paintCatFade() {
  const max = (catBar.scrollWidth || 0) - (catBar.clientWidth || 0);
  catBar.classList.toggle('has-more-left', max > 1 && catBar.scrollLeft > 1);
  catBar.classList.toggle('has-more-right', max > 1 && catBar.scrollLeft < max - 1);
}
// C19：大类条 / 主题条上竖向滚轮横滚（到头了就放给页面）
function barWheel(bar) {
  bar.addEventListener('wheel', e => {
    if (e.ctrlKey || e.metaKey) return;
    const max = (bar.scrollWidth || 0) - (bar.clientWidth || 0);
    if (max <= 0 || Math.abs(Number(e.deltaX) || 0) > Math.abs(Number(e.deltaY) || 0)) return;
    const dy = Number(e.deltaY) || 0;
    if ((dy > 0 && bar.scrollLeft >= max - 1) || (dy < 0 && bar.scrollLeft <= 0)) return;
    bar.scrollLeft = Math.max(0, Math.min(max, bar.scrollLeft + dy));
    e.preventDefault();
    if (bar === catBar) paintCatFade();
  }, { passive: false });
}
barWheel(catBar);
{ let q = false; catBar.addEventListener('scroll', () => { if (q) return; q = true; requestAnimationFrame(() => { q = false; paintCatFade(); }); }, { passive: true }); }
// 专辑：有几篇（按目录项 albums 汇总，多的在前）；没同步过专辑就是空的，按钮不出现
function albumCounts() {
  const m = new Map();
  for (const it of items) for (const a of Array.isArray(it.albums) ? it.albums : []) if (typeof a === 'string' && a) m.set(a, (m.get(a) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh'));
}
// 来源：不是她自己收藏的那几组各有几篇（多的在前）；全是她自己的就没有这颗按钮
function srcCounts() {
  const m = new Map();
  for (const it of allItems) { const s = srcOf(it); if (s) m.set(s, (m.get(s) || 0) + 1); }
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh'));
}
// 星标主题行（1021）：只在选中某个主题（或正在建第一个）时出现在控制行下面：STARRED · 全部主题 · 各主题胶囊 · + 新主题。
// 建 / 删走插件 run(['-m','link_brain','topic','add'|'remove', 名])（后端顺手重建目录），完了重读目录；结果如实提示（CONVENTIONS §1）。
// 没有插件（手机 / 没启用）就只能筛、不出建 / 删入口。
let topicAdding = false, topicFocusNew = false, topicArmed = '', topicArmTimer = null, topicBusy = false;
cleanups.push(() => clearTimeout(topicArmTimer));
function renderTopicBar() {
  const names = topicNames();
  const can = canEditTopics();
  if (topicAdding && !can) topicAdding = false;
  if (!activeTopic && !topicAdding) { if (topicBar) { topicBar.remove(); topicBar = null; } return; }
  if (!topicBar) { topicBar = top.createEl('div', { cls: 'lbc-topics' }); let ref = null; try { ref = selbar; } catch {} top.insertBefore(topicBar, ref && ref.parentNode === top ? ref : null); }
  const ae = document.activeElement;
  const typing = ae && topicBar.contains(ae) && ae.classList?.contains('lbc-topic-new');
  const draft = typing ? ae.value : (topicBar.querySelector?.('input.lbc-topic-new')?.value || '');
  topicBar.empty();
  topicBar.createEl('span', { cls: 'lbc-topics-lab', text: 'STARRED' });
  const counts = new Map(); let nAny = 0;
  for (const it of items) { const ts = Array.isArray(it.topics) ? it.topics.filter(t => names.includes(t)) : []; if (ts.length) nAny++; for (const t of ts) counts.set(t, (counts.get(t) || 0) + 1); }
  if (names.length) {
    const all = topicBar.createEl('button', { cls: 'lbc-topic-all' + (activeTopic === '*' ? ' is-active' : ''), text: '全部主题' });
    all.type = 'button'; all.dataset.n = String(nAny); all.setAttribute('aria-pressed', String(activeTopic === '*'));
    all.onclick = () => pickScope('topic:*');
  }
  for (const name of names) {
    const w = topicBar.createEl('span', { cls: 'lbc-topic-wrap' });
    const chip = w.createEl('button', { cls: 'lbc-topic' + (activeTopic === name ? ' is-active' : '') });
    chip.type = 'button'; chip.dataset.n = String(counts.get(name) || 0);
    chip.createEl('span', { cls: 'lbc-topic-star', text: '★' }); chip.append(name);
    chip.setAttribute('aria-pressed', String(activeTopic === name));
    chip.onclick = () => pickScope('topic:' + name);
    if (can) {
      // 悬停出 ×；点一下变「再点删除」（4 秒内再点才删），免得手滑
      const armed = topicArmed === name;
      const del = w.createEl('button', { cls: 'lbc-topic-del' + (armed ? ' is-armed' : ''), text: armed ? '再点删除' : '×' });
      del.type = 'button';
      if (!armed) del.createEl('span', { cls: 'lb-visually-hidden', text: `删除主题「${name}」` });
      del.onclick = e => { e?.preventDefault?.(); e?.stopPropagation?.(); armOrRemoveTopic(name, del); };
    }
  }
  if (can) {
    if (topicAdding) {
      const input = topicBar.createEl('input', { cls: 'lbc-topic-new' });
      input.type = 'text'; input.placeholder = '主题名，回车建'; input.value = draft;
      input.addEventListener('keydown', e => {
        if (e.isComposing || e.keyCode === 229) return;
        if (e.key === 'Enter') { e.preventDefault(); addTopic(input.value, input); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation?.(); topicAdding = false; renderTopicBar(); }
      });
      if (typing || topicFocusNew) { topicFocusNew = false; try { input.focus({ preventScroll: true }); } catch { input.focus?.(); } }
    } else {
      const add = topicBar.createEl('button', { cls: 'lbc-topic-add', text: '+ 新主题' }); add.type = 'button';
      add.onclick = () => { topicAdding = true; topicFocusNew = true; renderTopicBar(); };
    }
  }
}
function armOrRemoveTopic(name, btn) {
  clearTimeout(topicArmTimer);
  if (topicArmed !== name) {
    topicArmed = name; renderTopicBar();
    topicArmTimer = setTimeout(() => { topicArmed = ''; renderTopicBar(); }, 4000);
    return;
  }
  topicArmed = '';
  removeTopic(name, btn);
}
const tailLine = s_ => String(s_ || '').trim().split('\n').map(l => l.trim()).filter(Boolean).pop()?.slice(0, 200) || '';
// 跑一条 topic 子命令：返回后端 JSON（status ok / exists），其余一律如实说原因并返回 null
async function runTopic(args, label) {
  if (topicBusy) { LB.say('上一个主题操作还没做完，完成后再点', { kind: 'warn' }); return null; }
  const p = await want('run'); if (!p) return null;
  topicBusy = true;
  let r = null, err = null;
  try { r = await p.run(['-m', 'link_brain', 'topic', ...args], label, false, { quiet: true }); }
  catch (e) { err = e; }
  finally { topicBusy = false; }
  if (err) { LB.say(`${label}没做成：${err?.message || err}`, { kind: 'error' }); return null; }
  const j = r && r.json && typeof r.json === 'object' ? r.json : null;
  if (r?.code === 6) { LB.say(j?.message || (typeof p.busyText === 'function' ? p.busyText() : '正在执行其他任务，完成后再点'), { kind: 'warn' }); return null; }
  if (!j || (j.status !== 'ok' && j.status !== 'exists')) {
    const why = j?.error || j?.message || tailLine(r?.out) || (r?.code != null ? `退出码 ${r.code}` : '后台没返回结果');
    LB.say(`${label}没做成：${why}`, { kind: 'error' });
    return null;
  }
  return j;
}
async function addTopic(raw, input) {
  const name = String(raw || '').trim().replace(/\s+/g, ' ');
  if (!name) { topicAdding = false; renderTopicBar(); return; }
  if (topicNames().includes(name)) { topicAdding = false; setScope('topic:' + name); renderCatBar(); render(); LB.say(`已有主题「${name}」`); return; }
  // 建主题会请问答模型配关键词（没配就用名字本身）、再重建目录：可能要十几秒——输入框锁住、显示进行中，失败字还在
  if (input) input.disabled = true;
  const prog = LB.progress(`正在建主题「${name}」（配关键词、重建目录）…`);
  let j = null;
  try { j = await runTopic(['add', name], '建主题'); }
  finally { prog.hide(); if (input) input.disabled = false; }
  if (!j) { try { input?.focus?.({ preventScroll: true }); } catch {} return; }
  topicAdding = false;
  await refresh();
  const nm = j.topic?.name || name;
  if (topicNames().includes(nm)) setScope('topic:' + nm);
  renderCatBar(); render(); scrollToResults();
  const n = Number(j.topic?.count);
  if (j.catalog === 'failed') LB.say(`主题「${nm}」建好了，但目录没重建上：${j.catalog_error || '原因没报出来'}（点「管理」→ 刷新目录再看）`, { kind: 'warn' });
  else if (j.status === 'exists') LB.say(`已有主题「${nm}」`);
  else LB.say(`已建主题「${nm}」` + (Number.isFinite(n) ? `：${n} 篇` : ''), { kind: 'ok' });
}
async function removeTopic(name, btn) {
  const done = btn?.isConnected ? LB.busy(btn, '正在删…') : () => {};
  let j = null;
  try { j = await runTopic(['remove', name], '删主题'); }
  finally { done(); }
  if (!j) { renderTopicBar(); return; }
  if (activeTopic === name) activeTopic = '';
  await refresh();
  renderCatBar(); render();
  if (j.catalog === 'failed') LB.say(`主题「${name}」删了，但目录没重建上：${j.catalog_error || '原因没报出来'}（点「管理」→ 刷新目录再看）`, { kind: 'warn' });
  else LB.say(`已删主题「${name}」`, { kind: 'ok' });
}
// ── 10-04 导入时间：筛选 + 排序 ──
const TIME_RANGES = { today: '今天', ['7d']: '近 7 天', ['30d']: '近 30 天' };
const ymd = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
function importedAt(it) { const t = Date.parse(it.ts || it.date || ''); return Number.isFinite(t) ? t : 0; }
function timeLabel() {
  const range = timeRange === 'custom' ? `${(timeFrom || '…').slice(5)}~${(timeTo || '…').slice(5)}` : TIME_RANGES[timeRange] || '';
  // 1021 排序胶囊：默认 = 数据顺序（导入新→旧），有搜索词时默认是按相关度
  const topic = activeTopic && activeTopic !== '*' ? '★' + activeTopic : '';
  return [topic, range, timeSort === 'recent' ? '最近导入' : ''].filter(Boolean).join(' · ') || (committed ? '按相关度' : '最新在前');
}
function inTimeRange(it) {
  if (!timeRange) return true;
  const t = importedAt(it); if (!t) return false;
  if (timeRange === 'today') return ymd(new Date(t)) === ymd(new Date());
  if (timeRange === '7d' || timeRange === '30d') return t >= Date.now() - (timeRange === '7d' ? 7 : 30) * 86400000;
  const day = ymd(new Date(t));
  return (!timeFrom || day >= timeFrom) && (!timeTo || day <= timeTo);
}
// ── 自制菜单（时间菜单要放日期输入；插件不在时的右键 / 更多…兜底）：键盘可操作（C17） ──
function closeMenus() { for (const m of document.querySelectorAll('.lbc-menu, .lbc-synclog-pop')) { try { m.__lbcClose ? m.__lbcClose() : m.remove(); } catch { m.remove(); } } }
function menuShell(cls, anchor) {
  closeMenus();
  const menu = document.body.createEl('div', { cls: 'lbc-menu' + (cls ? ' ' + cls : '') });
  menu.setAttribute('role', 'menu');
  const close = ({ refocus = false } = {}) => {
    menu.remove(); document.removeEventListener('click', onDoc); document.removeEventListener('contextmenu', onDoc);
    if (refocus) { try { anchor?.focus?.({ preventScroll: true }); } catch { anchor?.focus?.(); } }
  };
  const onDoc = ev => { if (menu.contains(ev?.target)) return; close(); };
  menu.__lbcClose = close;
  setTimeout(() => { document.addEventListener('click', onDoc); document.addEventListener('contextmenu', onDoc); }, 0);
  menu.addEventListener('keydown', e => {
    // 日期框里的 ↑↓←→ / Home / End 是改日期、挪光标的，不拿来换项（Escape / Tab 照样关）
    const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(String(e.target?.tagName || '').toUpperCase());
    if (inField && e.key !== 'Escape' && e.key !== 'Tab') return;
    const list = [...menu.querySelectorAll('.lbc-menu-item')];
    const i = list.indexOf(document.activeElement);
    const go = k => { const n = list.length; if (!n) return; const el = list[((k % n) + n) % n]; try { el.focus({ preventScroll: true }); } catch { el.focus(); } };
    const horiz = menu.classList.contains('lbc-time-menu');   // 1011 时间菜单一行几块：←→ 也能换
    if (e.key === 'ArrowDown' || (horiz && e.key === 'ArrowRight')) { e.preventDefault(); go(i + 1); }
    else if (e.key === 'ArrowUp' || (horiz && e.key === 'ArrowLeft')) { e.preventDefault(); go(i < 0 ? list.length - 1 : i - 1); }
    else if (e.key === 'Home') { e.preventDefault(); go(0); }
    else if (e.key === 'End') { e.preventDefault(); go(list.length - 1); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close({ refocus: true }); }
    else if (e.key === 'Tab') close();
  });
  return { menu, close };
}
function placeMenu(menu, x, y) {
  menu.style.position = 'fixed'; menu.style.zIndex = '9999';
  const rect = menu.getBoundingClientRect();
  const W = (typeof innerWidth === 'number' ? innerWidth : 1200), H = (typeof innerHeight === 'number' ? innerHeight : 800);
  menu.style.left = Math.max(8, Math.min(x, W - (rect.width || 0) - 8)) + 'px';
  menu.style.top = Math.max(8, Math.min(y, H - (rect.height || 0) - 8)) + 'px';
}
function focusFirst(menu) { const f = menu.querySelector('.lbc-menu-item'); if (f) { try { f.focus({ preventScroll: true }); } catch { f.focus(); } } }
// items: [{title, onClick, danger, checked, separator}]；先用插件的 obsidian.Menu（§5.12），插件不在才自制
function popMenu(items, e, anchor, pos) {
  const real = LB.showMenu(items, e);
  if (real) return real;
  const { menu, close } = menuShell('', anchor);
  for (const it of items) {
    if (!it) continue;
    if (it.separator) { menu.createEl('div', { cls: 'lbc-menu-sep' }); continue; }
    if (it.isLabel) { menu.createEl('div', { cls: 'lbc-menu-group lbc-menu-label', text: it.title }); continue; }
    if (Array.isArray(it.children)) {
      // 二级：自制菜单里是一个小标题 + 缩进的一组（键盘照样上下走）
      menu.createEl('div', { cls: 'lbc-menu-group', text: it.title });
      for (const k of it.children.filter(Boolean)) {
        const b = menu.createEl('button', { cls: 'lbc-menu-item is-sub' + (k.checked ? ' is-on' : ''), text: (k.checked ? '✓ ' : '') + k.title });
        b.type = 'button'; b.setAttribute('role', 'menuitem');
        b.onclick = ev => { ev?.stopPropagation?.(); close(); k.onClick?.(ev); };
      }
      continue;
    }
    const b = menu.createEl('button', { cls: 'lbc-menu-item' + (it.danger ? ' is-danger' : '') + (it.checked ? ' is-on' : ''), text: (it.checked ? '✓ ' : '') + it.title });
    b.type = 'button'; b.setAttribute('role', 'menuitem');
    b.onclick = ev => { ev?.stopPropagation?.(); close(); it.onClick?.(ev); };
  }
  placeMenu(menu, pos?.x ?? 0, pos?.y ?? 0);
  focusFirst(menu);
  return menu;
}
// 1011 紧凑版（她：一项一个整宽按钮太乱）：
//   排序  [默认 | 最近导入]                 ← 一行分段
//   时间  [全部] [今天] [7 天] [30 天] [自定义] ← 一行小块（窄了折行）
//         起 ~ 止 [筛选]                    ← 只在选了「自定义」时出现
// 状态键不变（timeSort / timeRange / timeFrom / timeTo）；点排序 / 时间块立刻生效并关菜单，「自定义」只展开起止、点「筛选」才生效。
const TIME_CHIPS = [['', '全部'], ['today', '今天'], ['7d', '7 天'], ['30d', '30 天']];
function openTimeMenu(anchor) {
  const { menu, close } = menuShell('lbc-time-menu', anchor);
  const apply = () => { close(); leaveSideViews(); renderCatBar(); render(); scrollToResults(); };
  const opt = (parent, cls, label, on, fn) => {
    const b = parent.createEl('button', { cls: 'lbc-menu-item ' + cls + (on ? ' is-on' : ''), text: label });
    b.type = 'button'; b.setAttribute('role', 'menuitemradio'); b.setAttribute('aria-checked', String(!!on));
    b.onclick = ev => { ev?.stopPropagation?.(); fn(ev); };
    return b;
  };
  const line = (label) => {
    const row = menu.createEl('div', { cls: 'lbc-tm-row' });
    row.createEl('span', { cls: 'lbc-tm-label', text: label });
    return row;
  };
  const seg = line('排序').createEl('div', { cls: 'lbc-seg' }); seg.setAttribute('role', 'group');
  opt(seg, 'lbc-seg-btn', '默认', !timeSort, () => { timeSort = ''; apply(); });
  opt(seg, 'lbc-seg-btn', '最近导入', timeSort === 'recent', () => { timeSort = 'recent'; apply(); });
  const chips = line('时间').createEl('div', { cls: 'lbc-chips' }); chips.setAttribute('role', 'group');
  for (const [k, label] of TIME_CHIPS) opt(chips, 'lbc-chip', label, timeRange === k, () => { timeRange = k; if (k) todayOnly = false; apply(); });
  const customChip = opt(chips, 'lbc-chip', '自定义', timeRange === 'custom', () => {
    // 只展开起止，不改筛选；焦点进「起」
    range.hidden = false;
    for (const c of chips.querySelectorAll('.lbc-chip')) { const on = c === customChip; c.classList.toggle('is-on', on); c.setAttribute('aria-checked', String(on)); }
    place();   // 弹层变宽了：重新夹回视口里
    try { from.focus({ preventScroll: true }); } catch { from.focus?.(); }
  });
  const range = menu.createEl('div', { cls: 'lbc-range' }); range.onclick = ev => ev.stopPropagation();
  range.hidden = timeRange !== 'custom';
  const from = range.createEl('input'); from.type = 'date'; from.value = timeFrom; from.setAttribute('aria-label', '起');
  range.createEl('span', { cls: 'lbc-range-sep', text: '~' });
  const to = range.createEl('input'); to.type = 'date'; to.value = timeTo; to.setAttribute('aria-label', '止');
  const ok = range.createEl('button', { cls: 'mod-cta', text: '筛选' }); ok.type = 'button';
  ok.onclick = ev => { ev?.stopPropagation?.(); let a = from.value || '', b = to.value || ''; if (!a && !b) return; if (a && b && a > b) [a, b] = [b, a]; timeFrom = a; timeTo = b; timeRange = 'custom'; todayOnly = false; apply(); };
  // 1027b 她：点「最新在前」就能按主题 / 按分类筛（和分类行、范围里的主题是同一个筛选，点已选中的 = 取消）
  const topics = topicNames();
  if (topics.length) {
    const tc = line('主题').createEl('div', { cls: 'lbc-chips' }); tc.setAttribute('role', 'group');
    opt(tc, 'lbc-chip', '不限', !activeTopic, () => { activeTopic = ''; apply(); });
    for (const name of topics) {
      const n = items.filter(it => (it.topics || []).includes(name)).length;
      opt(tc, 'lbc-chip', `★ ${name} ${n}`, activeTopic === name, () => { activeTopic = activeTopic === name ? '' : name; apply(); }).dataset.topic = name;
    }
  }
  const roots = idx ? idx.roots.map(p_ => idxByPath.get(p_)).filter(n => n && n.count) : (data.cats_order || []).map(c => ({ path: c, name: c, count: items.filter(it => catNameOf(it) === c).length })).filter(n => n.count);
  if (roots.length) {
    const cc = line('分类').createEl('div', { cls: 'lbc-chips' }); cc.setAttribute('role', 'group');
    opt(cc, 'lbc-chip', '不限', !activeCat, () => { activeCat = ''; activeFacets = []; apply(); });
    for (const n of roots) {
      const on = activeCat === n.path || activeCat.startsWith(n.path + '/');
      opt(cc, 'lbc-chip', `${n.name} ${n.count}`, on, () => { activeCat = on ? '' : n.path; activeFacets = []; apply(); }).dataset.path = n.path;
    }
  }
  const place = () => { const r = anchor.getBoundingClientRect(); placeMenu(menu, r.left, r.bottom + 4); };
  place();
  focusFirst(menu);
  return menu;
}

// ── 页面状态（§5.3）：打开一篇再返回 / 页面被重建后，搜索词、筛选、多选、滚动位置照旧 ──
const saved = LB.state.load();
let savedScroll = 0;
if (saved.ts) {
  committed = typeof saved.q === 'string' ? saved.q : '';
  lastRaw = typeof saved.raw === 'string' ? saved.raw : (typeof saved.input === 'string' && saved.input === saved.q ? saved.input.trim() : '');
  if (knownCat(saved.cat)) activeCat = saved.cat;
  indexView = false;   // 1023 索引入口藏了：不再从上次状态恢复
  for (const pair of Array.isArray(saved.fold) ? saved.fold : []) if (Array.isArray(pair) && typeof pair[0] === 'string') foldOverride.set(pair[0], !!pair[1]);
  if (typeof saved.topic === 'string') activeTopic = saved.topic;
  if (typeof saved.album === 'string') activeAlbum = saved.album;   // renderTopicBar 会把已不存在的主题清掉
  if (typeof saved.src === 'string') { activeSrc = saved.src; applySrc(); }   // 已不存在的来源同样由 renderTopicBar 清掉
  todayOnly = !!saved.today; todoOnly = !!saved.todo;
  if (['image', 'video', 'attachment'].includes(saved.media)) mediaFilter = saved.media;
  if (typeof saved.tag === 'string') activeTag = saved.tag;
  if (typeof saved.plat === 'string') activePlat = saved.plat;
  if (!starredPage) starOnly = !!saved.star;
  if (saved.timeSort === 'recent') timeSort = 'recent';
  if (['today', '7d', '30d', 'custom'].includes(saved.timeRange)) timeRange = saved.timeRange;
  const day = v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : ''; timeFrom = day(saved.timeFrom); timeTo = day(saved.timeTo);
  if (!mobile) {
    const known = new Set(items.map(x => x.id));
    for (const id of Array.isArray(saved.select) ? saved.select : []) if (known.has(id)) selected.add(id);
    selectMode = !!saved.selectMode && selected.size > 0;
  }
  savedScroll = Number(saved.scrollTop) || 0;
  if (saved.exportImages === false) exportImages = false;
  if ((saved.view === 'wiki' || saved.view === 'recent') && !simplePage) viewMode = saved.view;
  if (Number(saved.recentPage) > 0) recentPage = Math.floor(Number(saved.recentPage));
  if (saved.side === false) sideOpen = false;
  if (saved.sideFold && typeof saved.sideFold === 'object') for (const k of Object.keys(sideFold)) if (typeof saved.sideFold[k] === 'boolean') sideFold[k] = saved.sideFold[k];
  if (saved.sideFoldRev !== 2) sideFold.recent = true;
}
setScope(scopeOf());   // 1021 范围单选：旧版本存下的叠加状态只留一个（顺序同 scopeOf）
if (!sideOpen) wrap.classList.add('is-side-collapsed');
if (sideBtn) sideBtn.setAttribute('aria-pressed', String(sideOpen));
let scrollTop = savedScroll;
function saveState() {
  LB.state.save({ q: committed, raw: lastRaw, input: search.value, cat: activeCat, topic: activeTopic, album: activeAlbum, src: activeSrc, today: todayOnly, todo: todoOnly, media: mediaFilter, tag: activeTag, plat: activePlat, star: starOnly,
    selectMode, select: [...selected], scrollTop, cols, timeSort, timeRange, timeFrom, timeTo, exportImages,
    iview: indexView, fold: [...foldOverride].slice(-200), view: viewMode, recentPage, side: sideOpen, sideFold: { ...sideFold }, sideFoldRev: 2 });
}

// ── 多选栏（C1 放进吸顶区、C15 常用的留在栏上） ──
const selbar = mobile ? null : top.createEl('div', { cls: 'lbc-selbar' });
let selCount = null, starSel = null, aiBtn = null, expBtn = null, moreBtn = null, delBtn = null, clrBtn = null, selBusy = false;
if (selbar) {
  selbar.hidden = true;
  selbar.createEl('span', { cls: 'lbc-selhint', text: '按 Esc 退出多选' });   // 1015 她：放最左
  selCount = selbar.createEl('span', { cls: 'lbc-selcount' });
  // 1008 她：目录页也要能收藏（★）——多选栏一键收藏 / 取消收藏选中的
  starSel = selbar.createEl('button', { cls: 'lbc-starsel', text: '收藏选中' }); starSel.type = 'button';
  starSel.onclick = () => starMany(items.filter(x => selected.has(x.id)));
  aiBtn = selbar.createEl('button', { cls: 'lbc-aisel', text: '给 AI（存成选集）' }); aiBtn.type = 'button';
  aiBtn.onclick = () => saveSelectionDialog(items.filter(x => selected.has(x.id)));
  expBtn = selbar.createEl('button', { cls: 'lbc-expsel', text: '导出资料包' }); expBtn.type = 'button';
  expBtn.onclick = () => exportNow(items.filter(x => selected.has(x.id)), { button: expBtn });
  moreBtn = selbar.createEl('button', { cls: 'lbc-moresel', text: '更多…' }); moreBtn.type = 'button';
  moreBtn.onclick = e => {
    e?.stopPropagation?.();
    const r = moreBtn.getBoundingClientRect();
    popMenu([
      { title: '复制文件包', onClick: () => copyBundleNow(items.filter(x => selected.has(x.id))) },
      { title: '附带原图', checked: exportImages, onClick: () => { exportImages = !exportImages; saveState(); } },
    ], e, moreBtn, { x: r.left, y: r.bottom + 4 });
  };
  delBtn = selbar.createEl('button', { text: '删除选中', cls: 'mod-warning lbc-delsel' }); delBtn.type = 'button';
  delBtn.onclick = () => confirmDelete(items.filter(x => selected.has(x.id)));
  clrBtn = selbar.createEl('button', { cls: 'lbc-clrsel', text: '退出多选' }); clrBtn.type = 'button';
  clrBtn.onclick = () => clearSelection();
}
function paintSelbar() {
  if (!selbar) return;
  if (selBusy) return;
  const list = items.filter(x => selected.has(x.id));
  selCount.setText(`已选 ${selected.size} 篇`);
  starSel.setText(list.length && list.every(x => x.starred) ? '取消收藏选中' : '收藏选中');
  delBtn.setText(`删除选中${selected.size ? ' (' + selected.size + ')' : ''}`);
  for (const b of [starSel, aiBtn, expBtn, moreBtn, delBtn]) b.disabled = !selected.size || deleting;
}
// 多选栏显隐：吸顶区变高 / 变矮的那一截补进滚动，下面的卡视觉上不动（C1 / C10）
// 以顶栏下第一张卡为锚：切换后量它挪了多少就补多少（浏览器自己的滚动锚定已经补过时量出来是 0，不会补两遍）；下一帧再核一次
function cardUnderTop() {
  const barBottom = top.getBoundingClientRect().bottom;
  for (const c of grid.querySelectorAll('.lbc-card')) { if (c.getBoundingClientRect().bottom > barBottom + 1) return c; }
  return null;
}
function setSelbarVisible(on) {
  if (!selbar || selbar.hidden === !on) return;
  const sc = LB.scroller();
  const a = sc ? cardUnderTop() : null, y0 = a ? a.getBoundingClientRect().top : 0;
  const h0 = top.offsetHeight || 0;
  selbar.hidden = !on;
  if (indexView && idx) paintIndexSticky();     // 吸顶区变高 / 变矮：左边的树跟着挪
  if (!sc) return;
  if (a) {
    const fix = () => { if (!a.isConnected) return; const d = a.getBoundingClientRect().top - (y0 + (top.offsetHeight || 0) - h0); /* 1019 她：吸顶区变高，卡片跟着往下让，不被盖住 */ if (Math.abs(d) >= 0.5) sc.scrollTop = Math.max(0, sc.scrollTop + d); };
    fix(); requestAnimationFrame(fix);
  } else {
    const d = (top.offsetHeight || 0) - h0;
    if (d) sc.scrollTop = Math.max(0, (sc.scrollTop || 0) + d);
  }
}
// 批量收藏 / 删除进行中：栏上能点的都灰掉（「退出多选」保留），收藏按钮换成「正在…」
function setSelbarBusy(text) {
  if (!selbar) return () => {};
  selBusy = true;
  const prev = starSel.textContent;
  for (const b of [starSel, aiBtn, expBtn, moreBtn, delBtn]) b.disabled = true;
  if (text) starSel.setText(text);
  return () => { selBusy = false; starSel.setText(prev); paintSelbar(); };
}

// ── 10-11「索引」视图：左边可折叠的树（带篇数），右边就是卡片网格（同一套卡片，点哪个节点右边就是哪些）；
//    上面一行：篇数 · 「未归类 N 篇」· 按内容归类的状态 · 「建议新增」chips；右边网格上面一行说清选中的是什么、能做什么。
// 起草 / 用这版 / 建议 / 改归属 / 生成 wiki 要插件（跑 Python）；打开 索引.md / 草稿 / wiki 页不要插件（手机上也能看）。
// 1021：收藏墙外面套一层 .lbc-board——左边一列 .lbc-side 是边栏（第 3 段；手机 / 星标页不出），右边 .lbc-board-main 是原来的索引条 + 网格。
// 边栏一开始就占位（has-side），第一次排瀑布流时列数就按留出边栏后的宽度算，不会先排满再挤
const SIDE_ON = !mobile && !simplePage;
const board = wrap.createEl('div', { cls: 'lbc-board' + (SIDE_ON ? ' has-side' : '') });
const side = board.createEl('aside', { cls: 'lbc-side' }); side.hidden = !SIDE_ON;
// 1027：收藏墙那一列（编排时别的模块也能叠在墙上面 / 下面）；墙本身 = 模块 wall
const wallCol = board.createEl('div', { cls: 'lbc-wallcol' });
const boardMain = wallCol.createEl('div', { cls: 'lbc-board-main lbc-m lbc-m-wall' }); boardMain.dataset.m = 'wall';
const ibar = boardMain.createEl('div', { cls: 'lbi-bar' }); ibar.hidden = true;
const split = boardMain.createEl('div', { cls: 'lbi-split' });
const ipanel = split.createEl('div', { cls: 'lbi-panel' }); ipanel.hidden = true;
const imain = split.createEl('div', { cls: 'lbi-main' });
const ihead = imain.createEl('div', { cls: 'lbi-head' }); ihead.hidden = true;
let panelKey = null, barKey = null, propsOpen = false;
// 默认只展开选中的那一支（树不长）；手动展开 / 收起过的照记的来
function nodeOpen(path) { return foldOverride.has(path) ? foldOverride.get(path) : !!activeCat && (activeCat === path || activeCat.startsWith(path + '/')); }
function selectNode(path) {
  if ((path || '') !== activeCat) activeFacets = [];
  activeCat = path || '';
  for (let p = activeCat.startsWith(PROP) ? '' : activeCat; p.includes('/'); p = p.slice(0, p.lastIndexOf('/'))) foldOverride.delete(p.slice(0, p.lastIndexOf('/')));
  renderCatBar(); render(); scrollToResults();
}
async function indexAction(method, btn, busyText, ...args) {
  const p = await want(method); if (!p) return null;
  const done = btn ? LB.busy(btn, busyText) : () => {};
  try { return await p[method](...args); }
  catch (e) { LB.say((busyText || '').replace(/^正在|…$/g, '') + '没成：' + (e?.message || e), { kind: 'error' }); return null; }
  finally { done(); }
}
// 插件那头的结果（{ok, message}）：说一句，成功了马上换上新的索引数据（文件监听也会来，但别让她等 300ms）
async function indexDone(r, okText = '好了') {
  if (!r) return false;
  LB.say(r.message || (r.ok ? okText : '没成'), { kind: r.ok ? 'ok' : 'error' });
  if (r.ok) await reloadIndex();
  return !!r.ok;
}
function panelButton(box, label, fn, cls = 'lbi-link') {
  const b = box.createEl('button', { text: label, cls }); b.type = 'button';
  b.onclick = e => { e?.stopPropagation?.(); fn(b); };
  return b;
}
const pathText = p => String(p || '').split('/').join(' › ');
const money = y => (typeof y === 'number' ? (y >= 0.01 ? `，约 ¥${y.toFixed(2)}` : '，不到 1 分钱') : '');
function classifyStatus() {
  const c = idx?.classify; if (!c) return null;
  if (c.running) return { text: `AI 正在按内容归类${c.running.total ? ` ${c.running.done || 0}/${c.running.total}` : ''}…（归好的会陆续出来）` };
  if (!c.ai_ok) return { text: `没配文本 AI：先按名字和标签找（${c.why || '设置里没配'}）` };
  if (c.error && c.work) return { text: `上次按内容归类没成：${c.error.error || c.error.code || ''}`, warn: true, action: '重试' };
  if (c.blocked) return { text: c.blocked.why, action: '按内容归类' };
  if (c.work) return { text: (c.pending ? `还有 ${c.pending} 篇没按内容归` : '有新改的分类还没核对') + money(c.yuan), action: '按内容归类' };
  const spent = Number(c.spent?.yuan) || 0;
  return { text: `已按内容归类${c.model ? ' · ' + c.model : ''}${spent ? ` · 累计约 ¥${spent.toFixed(2)}` : ''}` };
}
async function runClassify(btn) {
  const r = await indexAction('indexClassify', btn, '正在按内容归类…', { onProgress: ev => { try { btn.setText?.(`正在按内容归类 ${ev.done}/${ev.total}…`); } catch {} } });
  await indexDone(r, '按内容归好了');
}
function renderIndexBar() {
  const key = JSON.stringify([idx.total, idx.classified, idx.unclassified?.count, classifyStatus(), (idx.proposals || []).map(p => [p.id, p.name, p.count]),
    idx.drafting, idx.draft, idx.warnings, idx.comments, idx.text_ai, activeCat, propsOpen, mobile]);
  if (key === barKey) return;
  barKey = key;
  ibar.empty();
  const unc = idx.unclassified?.count || 0;
  const l1 = ibar.createEl('div', { cls: 'lbi-line' });
  l1.createEl('span', { cls: 'lbi-sum', text: `${idx.total} 篇 · 归进分类 ${idx.classified} 篇` });
  if (unc) {
    const u = panelButton(l1, `未归类 ${unc} 篇`, () => selectNode(activeCat === UNC ? '' : UNC), 'lbi-link lbi-unc-link' + (activeCat === UNC ? ' is-on' : ''));
    u.setAttribute('aria-pressed', String(activeCat === UNC));
  } else l1.createEl('span', { cls: 'lbi-sum', text: '没有未归类的' });
  const st = classifyStatus();
  if (st) {
    const sEl = l1.createEl('span', { cls: 'lbi-status' + (st.warn ? ' is-warn' : ''), text: st.warn ? '⚠ 上次按内容归类没成' : st.text });
    if (st.warn) sEl.title = st.text;
    if (st.action && !mobile) panelButton(l1, st.action, b => runClassify(b), 'lbi-link is-strong lbi-classify-btn');
  }
  const tools = l1.createEl('span', { cls: 'lbi-tools' });
  panelButton(tools, '编辑 索引.md', () => openVaultFile(idx.file || '索引.md'), 'lbi-link lbi-edit');
  const props = Array.isArray(idx.proposals) ? idx.proposals : [];
  if (!mobile) {
    panelButton(tools, idx.text_ai?.ok ? 'AI 起草一版新树' : '起草一版', b => indexAction('indexDraft', b, '正在起草…'), 'lbi-link lbi-draft-btn');
    if (unc && !props.length) panelButton(tools, '未归类建议', b => indexAction('openIndexSuggestions', b, '正在找建议…'), 'lbi-link lbi-suggest-btn');
  }
  // 1028 她：「索引得有个地方退出来」——视图开关里的「索引」常被藏着（窄屏 / 只剩一项），这里固定留一个出口，回到进来之前的收藏墙
  panelButton(tools, '退出索引编辑 ×', () => pickView('grid'), 'lbi-link is-strong lbi-exit');
  if (props.length) {
    const chips = ibar.createEl('div', { cls: 'lbi-chips' });
    chips.createEl('span', { cls: 'lbi-chips-label', text: '建议新增' });
    const shown = propsOpen ? props : props.slice(0, 8);
    for (const p of shown) {
      const on = activeCat === PROP + p.id;
      const chip = chips.createEl('button', { cls: 'lbi-chip' + (on ? ' is-on' : '') }); chip.type = 'button';
      chip.dataset.id = p.id; chip.setAttribute('aria-pressed', String(on));
      chip.append(p.name);
      chip.createEl('span', { cls: 'lbi-chip-n', text: String(p.count) });
      chip.onclick = () => selectNode(on ? '' : PROP + p.id);
    }
    if (props.length > 8) panelButton(chips, propsOpen ? '收起' : `还有 ${props.length - 8} 条`, () => { propsOpen = !propsOpen; barKey = null; renderIndexBar(); }, 'lbi-link');
  }
  if (idx.drafting) {
    ibar.createEl('div', { cls: 'lbi-line lbi-drafting' }).createEl('span', { text: 'AI 正在起草一版新的索引…（好了会出现在这里，不会改你的 索引.md）' });
  } else if (idx.draft?.exists) {
    const d = idx.draft;
    const line = ibar.createEl('div', { cls: 'lbi-line lbi-draft' });
    line.createEl('span', { cls: 'lbi-draft-text', text: `${d.mode === 'ai' ? 'AI 起草了一版' : '起草了一版'}：${(d.roots || []).length} 个大类，能归进 ${d.classified}/${d.total} 篇` });
    panelButton(line, '看草稿', () => openVaultFile(d.file || idx.draft_file));
    if (!mobile) panelButton(line, '用这版', b => indexAction('indexUseDraft', b, '正在换…'), 'lbi-link is-strong lbi-use-draft');
  }
  if (!mobile && !idx.text_ai?.ok) {
    ibar.createEl('p', { cls: 'lbi-note', text: `没有能用的文本 AI（${idx.text_ai?.why || '设置里没配'}）：「起草一版」按高频标签出草稿；`
      + 'wiki 生成不了，可以让 GPT 经 MCP 来写（guide 取方法、index 看这个节点的篇目、read 读全文）。' });
  }
  const warns = (idx.warnings || []).filter(w => w && w.text && w.level !== 'info');   // 1015：第 4 级并进第 3 级（info）是她要的写法，不算
  if (warns.length) {
    const w = ibar.createEl('div', { cls: 'lbi-warn' });
    w.createEl('span', { cls: 'lbi-warn-mark', text: '⚠' });
    w.createEl('span', { text: `${idx.file || '索引.md'} 有 ${warns.length} 处写法要看一眼：${warns[0].text}` });
    if (warns[0].line) panelButton(w, '去改', () => openVaultFile(idx.file || '索引.md', warns[0].line));
    if (warns.length > 1) {
      const list = w.createEl('ol'); list.hidden = true;
      for (const x of warns.slice(1, 30)) list.createEl('li', { text: x.text });
      const more = panelButton(w, `还有 ${warns.length - 1} 处`, () => { list.hidden = !list.hidden; more.setText(list.hidden ? `还有 ${warns.length - 1} 处` : '收起'); });
    }
  }
  const notes = (idx.comments || []).filter(c => c && c.line && !c.placeholder);
  if (notes.length) {
    const n = ibar.createEl('div', { cls: 'lbi-line lbi-comments' });
    n.createEl('span', { text: `${idx.file || '索引.md'} 里有 ${notes.length} 行像是写给自己的说明（「${notes[0].text.slice(0, 16)}…」），没当成分类` });
    panelButton(n, '去看', () => openVaultFile(idx.file || '索引.md', notes[0].line));
  }
}
function wikiActs(acts, n) {
  const st = (idx.wiki || {})[n.path] || {};
  if (st.exists) panelButton(acts, st.new_since ? `wiki（新增 ${st.new_since}）` : 'wiki', () => openVaultFile(st.file), 'lbi-link lbi-wiki-open');
  if (!mobile) {
    const gen = panelButton(acts, st.exists ? '更新 wiki' : '生成 wiki', b => indexAction('wikiBuild', b, '正在生成 wiki…', n.path), 'lbi-link lbi-wiki-gen');
    if (!idx.text_ai?.ok) gen.disabled = true;
  }
}
async function keepOrDropEmpty(n, action, btn) {
  if (action === 'remove' && !(await LB.confirm({ title: `从 ${idx.file || '索引.md'} 删掉「${n.name}」？`, ok: '删掉',
    body: `这个分类现在 0 篇。只删分类那一行（下面的子类一起），不碰任何帖子，别的字原样；原文先备份到 _archive/index-history/。` }))) return;
  const r = await indexAction('indexEmpty', btn, action === 'remove' ? '正在删…' : '正在记…', n.path, action);
  if (await indexDone(r) && action === 'remove' && activeCat === n.path) selectNode('');
}
async function acceptProposal(id, btn) {
  const r = await indexAction('indexAccept', btn, '正在写进索引…', id);
  const on = activeCat === PROP + id || idxByPath.get(activeCat)?.proposal === id;
  if (await indexDone(r) && on && r.path) selectNode(r.path);
}
async function dismissProposal(id, btn) {
  const r = await indexAction('indexDismiss', btn, '正在记…', id);
  const on = activeCat === PROP + id || idxByPath.get(activeCat)?.proposal === id;
  if (await indexDone(r) && on) selectNode('');
}
function treeRow(box, n, depth, { cls = '', kids = null } = {}) {
  const children = kids || (n.children || []).map(p => idxByPath.get(p)).filter(Boolean);
  const open = children.length ? (n.path ? nodeOpen(n.path) : true) : false;
  const empty = !n.count && !!n.path && n.path !== UNC;
  const row = box.createEl('div', { cls: 'lbi-row' + cls + (empty ? ' is-empty' : '') + (n.virtual ? ' is-virtual' : '')
    + ((activeCat || '') === n.path ? ' is-current' : '') });
  row.dataset.path = n.path;
  row.style.paddingLeft = (depth * 14) + 'px';
  if (children.length && n.path) {
    const fold = row.createEl('button', { cls: 'lbi-fold', text: open ? '▾' : '▸' }); fold.type = 'button';
    fold.setAttribute('aria-expanded', String(open));
    fold.createEl('span', { cls: 'lb-visually-hidden', text: open ? '收起' : '展开' });
    fold.onclick = e => { e.stopPropagation(); foldOverride.set(n.path, !open); panelKey = null; renderIndexPanel(); saveState(); };
  } else row.createEl('span', { cls: 'lbi-fold-pad' });
  const label = row.createEl('button', { cls: 'lbi-label' }); label.type = 'button';
  label.setAttribute('aria-pressed', String((activeCat || '') === n.path));
  label.createEl('span', { cls: 'lbi-name', text: n.name });
  if (n.virtual) label.createEl('span', { cls: 'lbi-badge', text: 'AI 建' });
  if (n.wiki) label.createEl('span', { cls: 'lbi-wiki-mark' + ((idx.wiki || {})[n.path]?.exists ? ' has-page' : ''), text: 'wiki' });
  label.createEl('span', { cls: 'lbi-n', text: String(n.count) });
  const editable = !mobile && !!n.line && !n.virtual && !!n.path && n.path !== UNC;
  label.onclick = e => { if (e?.detail >= 2 && editable && lastTreeDown === n.path) return; selectNode(n.path); };
  if (n.hints?.length) label.title = '包括 ' + n.hints.join('、');      // 第 4 级并进来的关键词：悬停看
  if (editable) {
    label.oncontextmenu = e => { e.preventDefault(); openNodeMenu(e, n, row); };
    wireDrag(row, n);
  } else if (!mobile && n.path === '' && idx) wireRootDrop(row);
  else if (!mobile && n.line) label.oncontextmenu = e => { e.preventDefault(); editCategories(n.path); };
  if (!mobile) {
    const acts = row.createEl('span', { cls: 'lbi-acts' });
    if (n.virtual) {
      panelButton(acts, '保留', b => acceptProposal(n.proposal, b), 'lbi-link is-strong lbi-keep-virtual');
      panelButton(acts, '不要', b => dismissProposal(n.proposal, b), 'lbi-link lbi-drop-virtual');
    } else if (empty && n.line && !n.keep_empty) {
      panelButton(acts, '删', b => keepOrDropEmpty(n, 'remove', b), 'lbi-link lbi-empty-drop');
      panelButton(acts, '留', b => keepOrDropEmpty(n, 'keep', b), 'lbi-link lbi-empty-keep');
    }
    if (n.wiki) wikiActs(acts, n);
    // 1027b 她：索引里「不方便直接新增 / 编辑」——双击、右键之外，悬停就有「改名 / ＋子类」
    if (editable) {
      panelButton(acts, '改名', () => startRename(row, n), 'lbi-link lbi-q-rename');
      panelButton(acts, '＋子类', () => startAdd(n.path, row), 'lbi-link lbi-q-add');
    }
    if (!acts.childElementCount) acts.remove();
  }
  if (open) for (const k of children) treeRow(box, k, depth + 1);
}
// 加分类：在那一行下面（第一级 = 树底下）出一个输入框，回车加、Esc / 失焦空着就收起；写回 索引.md、能撤销（indexEdit add，和编排「分类」模块同一个）
let adding = '';
function startAdd(parent, afterRow) {
  if (renaming || adding) { ipanel.querySelector('.lbi-add input')?.focus?.(); return; }
  adding = parent || '#';
  if (parent) { foldOverride.set(parent, true); }
  const box = document.createElement('div'); box.className = 'lbi-row lbi-add';
  const depth = parent ? parent.split('/').length : 0;
  box.style.paddingLeft = (depth * 14 + 14) + 'px';
  const inp = document.createElement('input'); inp.type = 'text'; inp.maxLength = 60; inp.placeholder = parent ? `「${pathText(parent)}」下面的新子类` : '新分类名';
  inp.setAttribute('aria-label', inp.placeholder);
  const go = document.createElement('button'); go.type = 'button'; go.className = 'lbi-link is-strong'; go.textContent = '加';
  box.append(inp, go);
  if (afterRow && afterRow.parentNode) afterRow.after(box); else (ipanel.querySelector('.lbi-tree') || ipanel).append(box);
  const end = () => { adding = ''; box.remove(); panelKey = null; renderIndexPanel(); };
  let busy = false;
  const doAdd = async () => {
    const v = inp.value.trim(); if (!v) { end(); return; }
    if (busy) return; busy = true; go.disabled = true; inp.disabled = true;
    const r = await indexAction('indexEdit', null, '正在改索引…', 'add', parent || '', { name: v });
    adding = ''; box.remove();
    await treeEditDone(r);
    if (!r?.ok) { panelKey = null; renderIndexPanel(); }
  };
  go.onmousedown = e => e.preventDefault?.();   // 点「加」时输入框别先失焦收起
  go.onclick = e => { e?.stopPropagation?.(); doAdd(); };
  inp.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault?.(); doAdd(); } else if (e.key === 'Escape') { e.preventDefault?.(); e.stopPropagation?.(); end(); } };
  inp.onblur = () => { if (!busy && !inp.value.trim()) end(); };
  try { inp.focus({ preventScroll: false }); } catch { inp.focus?.(); }
}
// ── 1015 大纲树（她裁定 D）：目录页直接改树——拖拽调层级 / 换顺序、双击改名、右键「改名 / 合并到… / 挪到…」；
//    Python（index edit）写回 索引.md：只动那几行、格式照旧、写前备份；每一步都能撤销 ──
let dragPath = '', lastTreeDown = '';
// 双击改名：第一下选中会重画树、页面还会滚到结果（行换了元素、甚至挪了位置），浏览器的 dblclick 到不了——
// 改在树上认 mousedown 的连击数（浏览器按位置和时间数，不管元素换没换）：第二下 = 改第一下按到的那一行
wrap.addEventListener('mousedown', e => {
  if (e.button !== 0 || mobile) return;
  if (e.detail === 1) {
    const r = ipanel.contains(e.target) ? e.target?.closest?.('.lbi-row') : null;
    lastTreeDown = r && r.querySelector('.lbi-label')?.contains(e.target) ? r.dataset.path : '';
    return;
  }
  if (e.detail === 2 && lastTreeDown) {
    const n = idxByPath.get(lastTreeDown); lastTreeDown = '';
    if (!n || !n.line || n.virtual) return;
    e.preventDefault();
    // 第二下可能落在挪上来的卡片上：吞掉这一下的 click（别顺手点开一篇）
    if (!ipanel.contains(e.target)) wrap.addEventListener('click', ev => { ev.stopPropagation(); ev.preventDefault(); }, { capture: true, once: true });
    startRename(null, n);
  }
}, true);
function movePrefix(from, to) {
  for (const [k, v] of [...foldOverride]) if (k === from || k.startsWith(from + '/')) { foldOverride.delete(k); foldOverride.set(to + k.slice(from.length), v); }
  if (activeCat === from || activeCat.startsWith(from + '/')) activeCat = to + activeCat.slice(from.length);
}
async function treeEditDone(r, { from = '', to = '' } = {}) {
  if (!r) return;
  if (!r.ok) { LB.say(r.message || '没改上', { kind: 'error' }); return; }
  if (from && to && from !== to) movePrefix(from, to);       // 路径变了：展开状态、选中跟着走
  panelKey = null;
  if (r.undo) LB.undoNotice(r.message, async () => {
    const u = await provider()?.indexEdit?.('undo', r.undo);
    if (!u?.ok) throw new Error(u?.message || '没撤销上');
    if (from && to && from !== to) movePrefix(to, from);
    panelKey = null; await reloadIndex();
  });
  else LB.say(r.message || '好了', { kind: 'ok' });
  await reloadIndex();
  if (activeCat && !knownCat(activeCat)) selectNode('');
}
async function treeEdit(op, n, opts = {}) {
  const r = await indexAction('indexEdit', null, '正在改索引…', op, n.path, opts);
  const parent = n.parent || '';
  const to = r?.path || (op === 'rename' ? (parent ? parent + '/' : '') + opts.name
    : op === 'move' ? (opts.to ? opts.to + '/' : '') + n.name : opts.to);
  await treeEditDone(r, { from: n.path, to });
  return r;
}
let renaming = '';           // 正在改名的那一行：改完之前树不重画（不然输入框跟着旧行一起没了）
function startRename(_row, n) {
  if (renaming) return;
  const row = [...ipanel.querySelectorAll('.lbi-row')].find(r => r.dataset.path === n.path) || _row;
  const label = row?.querySelector('.lbi-label'); if (!label || row.querySelector('.lbi-rename')) return;
  renaming = n.path;
  const box = document.createElement('input');
  box.type = 'text'; box.className = 'lbi-rename'; box.value = n.name; box.maxLength = 60;
  box.setAttribute('aria-label', `给「${n.name}」改名`);
  label.hidden = true; label.after(box);
  try { box.focus(); box.select(); } catch {}
  let done = false;
  const finish = async ok => {
    if (done) return; done = true;
    const v = box.value.trim();
    box.remove(); label.hidden = false;
    renaming = ''; panelKey = null;
    if (ok && v && v !== n.name) await treeEdit('rename', n, { name: v });
    else renderIndexPanel();
  };
  box.onkeydown = e => {
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); }
  };
  box.onblur = () => finish(true);
  box.onclick = e => e.stopPropagation();
}
function openNodeMenu(e, n, row) {
  const parentPath = n.parent || '';
  popMenu([
    { title: '改名', onClick: () => startRename(row, n) },
    { title: '合并到…', onClick: async () => {
      const to = await pickNode(`把「${n.name}」合并到…（标签和子类都并过去，「${n.name}」这一行删掉）`, { here: n.path });
      if (to) await treeEdit('merge', n, { to });
    } },
    { title: '挪到…（放进另一个分类下面）', onClick: async () => {
      const to = await pickNode(`把「${n.name}」挪到哪个分类下面`, { here: parentPath });
      if (to) await treeEdit('move', n, { to });
    } },
    parentPath ? { title: '提到第一级', onClick: () => treeEdit('move', n, { to: '' }) } : null,
    { separator: true },
    { title: '删除这个分类…（只删分类，帖子不删）', onClick: () => deleteCategoryFlow(n.path) },   // 1027b 从「管理」挪到这里
    { title: '在 索引.md 里改', onClick: () => editCategories(n.path) },
  ], e, row, { x: e?.clientX || 0, y: e?.clientY || 0 });
}
// 拖一行：落在别的行上部 = 插到它前面（同一级），下部 = 插到它后面，中间 = 放进它下面当子类；落在「全部」= 提到第一级
function dropZone(row, e) {
  const r = row.getBoundingClientRect();
  const y = ((e.clientY || 0) - r.top) / (r.height || 1);
  return y < 0.3 ? 'before' : y > 0.7 ? 'after' : 'into';
}
const DROP_CLS = ['is-drop-before', 'is-drop-after', 'is-drop-into', 'is-drop-bad'];
function clearDropMarks() { for (const el of ipanel.querySelectorAll('.lbi-row')) el.classList.remove(...DROP_CLS); }
// 能不能放：不能放进自己 / 自己下面；放进去当子类时第 3 级下面不能再放；挪过去整棵子树不能超过 3 级
function subtreeHeight(path) { const n = idxByPath.get(path); return 1 + Math.max(0, ...((n?.children || []).map(subtreeHeight))); }
function dropProblem(target, zone) {
  if (!dragPath || !target) return '拖的不是分类';
  if (target.path === dragPath || target.path.startsWith(dragPath + '/')) return '不能放进它自己下面';
  const depth = zone === 'into' ? (target.depth || 1) + 1 : (target.depth || 1);
  if (depth + subtreeHeight(dragPath) - 1 > 3) return '放过去会超过 3 级';
  return '';
}
function wireDrag(row, n) {
  row.draggable = true;
  row.ondragstart = e => {
    dragPath = n.path; row.classList.add('is-dragging');
    try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/x-lb-index', n.path); } catch {}
  };
  row.ondragend = () => { dragPath = ''; row.classList.remove('is-dragging'); clearDropMarks(); };
  row.ondragover = e => {
    if (!dragPath) return;
    const zone = dropZone(row, e), bad = dropProblem(n, zone);
    clearDropMarks();
    row.classList.add(bad ? 'is-drop-bad' : 'is-drop-' + zone);
    if (!bad) { e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch {} }
  };
  row.ondragleave = () => row.classList.remove(...DROP_CLS);
  row.ondrop = async e => {
    if (!dragPath) return;
    e.preventDefault(); e.stopPropagation();
    const zone = dropZone(row, e), bad = dropProblem(n, zone), src = idxByPath.get(dragPath);
    dragPath = ''; clearDropMarks();
    if (!src) return;
    if (bad) { LB.say(bad, { kind: 'error' }); return; }
    if (zone === 'into') { if (src.parent !== n.path) await treeEdit('move', src, { to: n.path }); return; }
    const parent = n.parent || '';
    const sib = (parent ? idxByPath.get(parent)?.children || [] : idx.roots || []).filter(p => p !== src.path);
    const k = sib.indexOf(n.path);
    const beforePath = zone === 'before' ? n.path : (k >= 0 && k + 1 < sib.length ? sib[k + 1] : '');
    // 原地没动（拖到自己前后）：不写
    const cur = (parent ? idxByPath.get(parent)?.children || [] : idx.roots || []);
    const curNext = cur[cur.indexOf(src.path) + 1] || '';
    if ((src.parent || '') === parent && cur.includes(src.path) && curNext === beforePath) return;
    await treeEdit('move', src, { to: parent, before: beforePath ? (idxByPath.get(beforePath)?.name || '') : '' });
  };
}
function wireRootDrop(row) {
  row.ondragover = e => { if (!dragPath || !idxByPath.get(dragPath)?.parent) return; e.preventDefault(); clearDropMarks(); row.classList.add('is-drop-into'); };
  row.ondragleave = () => row.classList.remove(...DROP_CLS);
  row.ondrop = async e => {
    const src = idxByPath.get(dragPath); dragPath = ''; clearDropMarks();
    if (!src || !src.parent) return;
    e.preventDefault();
    await treeEdit('move', src, { to: '' });
  };
}
function panelNarrow() { const w = Number(wrap.clientWidth) || (typeof innerWidth === 'number' ? innerWidth : 1200); return mobile || w < 700; }
function treeShape() {
  // 看得见的行（路径 / 名字 / 标记 / 空不空）+ 展开状态 + 选中：篇数不在里面——篇数变了只改数字
  const vis = [];
  const walk = (p, d) => { const n = idxByPath.get(p); if (!n) return; vis.push([p, n.name, !!n.virtual, !!n.wiki, !!n.keep_empty, !n.count, n.proposal || '', d, (idx.wiki || {})[p]?.exists || false]);
    if ((n.children || []).length && nodeOpen(p)) for (const c of n.children) walk(c, d + 1); };
  for (const r of idx.roots) walk(r, 0);
  return JSON.stringify([vis, !!idx.unclassified?.count, activeCat, mobile]);
}
function patchTreeCounts() {
  for (const row of ipanel.querySelectorAll('.lbi-row')) {
    const p = row.dataset.path;
    const c = p === '' ? idx.total : p === UNC ? (idx.unclassified?.count || 0) : idxByPath.get(p)?.count;
    const el = row.querySelector('.lbi-label .lbi-n');
    if (el && c != null && el.textContent !== String(c)) el.textContent = String(c);
  }
}
function renderIndexPanel() {
  if (!idx) { ipanel.empty(); panelKey = null; return; }
  if (renaming && ipanel.querySelector('.lbi-rename')) return;
  if (adding && ipanel.querySelector('.lbi-add')) return;
  const key = treeShape();
  if (key === panelKey) { patchTreeCounts(); return; }
  panelKey = key;
  const keepScroll = ipanel.scrollTop || 0;
  ipanel.empty();
  const tree = ipanel.createEl('div', { cls: 'lbi-tree' });
  const roots = idx.roots.map(p => idxByPath.get(p)).filter(Boolean);
  treeRow(tree, { path: '', name: '全部', count: idx.total }, 0, { cls: ' is-root', kids: [] });
  for (const r of roots) treeRow(tree, r, 0);
  const unc = idx.unclassified?.count || 0;
  if (unc) treeRow(tree, { path: UNC, name: UNC_LABEL, count: unc }, 0, { cls: ' is-unc', kids: [] });
  if (!mobile && provider()) {
    const add = tree.createEl('button', { cls: 'lbi-add-btn', text: '＋ 加分类' }); add.type = 'button';
    add.onclick = e => { e?.stopPropagation?.(); startAdd('', add); };
    tree.createEl('p', { cls: 'lbi-tree-tip', text: '悬停一行：改名 / ＋子类；拖动换层级和顺序；右键还有合并、挪到…。都写回 索引.md，能撤销。' });
  }
  if (keepScroll) ipanel.scrollTop = keepScroll;
}
// 选中节点的细分标签：一行 chips（篇数 = 和已选的同时有的篇数），多选越选越窄，「清除」回到这一类全部
const ifacets = imain.createEl('div', { cls: 'lbi-facets' }); ifacets.hidden = true;
let facetsKey = null;
function renderIndexFacets() {
  const want = indexView && idx && activeCat && !activeCat.startsWith(PROP) && activeCat !== UNC;
  // 10-11：不在索引视图 / 没选节点时什么都不算（每次 render 都会进来：目录页平常的搜索、打字不能为它多花一点时间）
  if (!want) { if (facetsKey !== '') { facetsKey = ''; ifacets.empty(); ifacets.hidden = true; } return; }
  const list = facetsOf(activeCat);
  const base = nodeIds(activeCat);
  const cur = [...(base || [])].filter(id => activeFacets.every(f => facetIds(f)?.has(id)));
  const counts = list.map(f => (f.items || []).filter(id => cur.includes(id)).length);
  const key = JSON.stringify([activeCat, list.map(f => [f.name, f.count]), activeFacets, counts]);
  if (key === facetsKey) return;
  facetsKey = key;
  ifacets.empty();
  ifacets.hidden = !list.length;
  if (!list.length) return;
  ifacets.createEl('span', { cls: 'lbi-facets-label', text: '细分' });
  list.forEach((f, k) => {
    const on = activeFacets.includes(f.name);
    const chip = ifacets.createEl('button', { cls: 'lbi-facet' + (on ? ' is-on' : '') + (!on && !counts[k] ? ' is-zero' : '') }); chip.type = 'button';
    chip.dataset.name = f.name; chip.setAttribute('aria-pressed', String(on));
    chip.append(f.name);
    chip.createEl('span', { cls: 'lbi-chip-n', text: String(on ? cur.length : counts[k]) });
    chip.onclick = () => { activeFacets = on ? activeFacets.filter(x => x !== f.name) : [...activeFacets, f.name]; render(); scrollToResults(); };
  });
  if (activeFacets.length) {
    const clr = ifacets.createEl('button', { cls: 'lbi-facet lbi-facet-clear', text: '清除' }); clr.type = 'button';
    clr.onclick = () => { activeFacets = []; render(); scrollToResults(); };
  }
}
// 卡片上小字：这一篇帖子的细分标签（标签属于帖子；只在索引视图里，选中这一类那一行里有的排前面）
let cardTagsShown = false;
function paintCardFacets() {
  const on = !!(indexView && idx);
  // 不在索引视图：卡片上本来就没字就什么都不做（平常的搜索 / 打字不为它扫一遍卡片）；刚离开索引视图才清一次
  if (!on && !cardTagsShown) return;
  cardTagsShown = on;
  const front = new Set(on && activeCat ? facetsOf(activeCat).map(f => f.name) : []);
  for (const card of grid.querySelectorAll('.lbc-card')) {
    const id = card._lbItem?.id; const el = card.querySelector('.lbc-ftags'); if (!el) continue;
    const tags = on ? [...(idx.item_tags?.[id] || [])].sort((a, b) => (front.has(b) - front.has(a))) : [];
    const text = tags.slice(0, 5).join(' · ');
    if (el.textContent !== text) el.textContent = text;
    el.hidden = !text;
  }
}
// 右边网格上面一行：选中的是什么、几篇、她写的说明；建议新增 / AI 建的 / 空的分类在这里也能一键处理
function renderIndexHead() {
  ihead.empty();
  const p = proposalOf(activeCat), n = idxByPath.get(activeCat);
  if (!activeCat || (!p && !n && activeCat !== UNC)) { ihead.hidden = true; return; }
  ihead.hidden = false;
  if (p) {
    ihead.createEl('span', { cls: 'lbi-head-title', text: `建议新增「${p.name}」` });
    ihead.createEl('span', { cls: 'lbi-head-sub', text: `${p.parent ? `放在「${pathText(p.parent)}」下面` : '放在第一级'} · ${p.count} 篇${p.loose ? `（其中 ${p.loose} 篇现在没归类）` : ''}` });
    if (!mobile) {
      panelButton(ihead, '加进索引', b => acceptProposal(p.id, b), 'lbi-link is-strong lbi-accept');
      panelButton(ihead, '不要', b => dismissProposal(p.id, b), 'lbi-link lbi-dismiss');
    }
    return;
  }
  if (activeCat === UNC) {
    ihead.createEl('span', { cls: 'lbi-head-title', text: '未归类' });
    ihead.createEl('span', { cls: 'lbi-head-sub', text: `${idx.unclassified?.count || 0} 篇哪个分类都没放进去：卡片上点「归类…」挪到合适的分类，或者点上面的「建议新增」` });
    return;
  }
  ihead.createEl('span', { cls: 'lbi-head-title', text: pathText(n.path) });
  const bits = [`${n.count} 篇`];
  if (n.desc && !n.virtual) bits.push(n.desc);
  if (n.hints?.length) bits.push('包括 ' + n.hints.join('、'));
  if (n.virtual) bits.push('AI 按内容建的子类，点「保留」才写进索引');
  ihead.createEl('span', { cls: 'lbi-head-sub', text: bits.join(' · ') });
  if (mobile) return;
  if (n.virtual) {
    panelButton(ihead, '保留', b => acceptProposal(n.proposal, b), 'lbi-link is-strong lbi-keep-virtual');
    panelButton(ihead, '不要', b => dismissProposal(n.proposal, b), 'lbi-link');
  } else {
    if (!n.count && n.line && !n.keep_empty) {
      panelButton(ihead, '删掉这个分类', b => keepOrDropEmpty(n, 'remove', b), 'lbi-link lbi-empty-drop');
      panelButton(ihead, '留着', b => keepOrDropEmpty(n, 'keep', b), 'lbi-link lbi-empty-keep');
    }
    if (n.line) panelButton(ihead, '在索引里改', () => openVaultFile(idx.file || '索引.md', n.line));
  }
}
// 树钉在左边（吸顶区下面），自己能滚、不露滚动条；高度跟着视口
function paintIndexSticky() {
  if (ipanel.hidden || split.classList.contains('is-narrow')) { ipanel.style.top = ''; ipanel.style.maxHeight = ''; return; }
  const sc = LB.scroller();
  let pad = 0;
  try { pad = parseFloat(getComputedStyle(sc).paddingTop) || 0; } catch {}
  const h = top.offsetHeight || 0;
  ipanel.style.top = Math.round(h - pad + 8) + 'px';
  ipanel.style.maxHeight = Math.max(220, (sc?.clientHeight || (typeof innerHeight === 'number' ? innerHeight : 800)) - h - 20) + 'px';
}
// ── 改归类（「移到… / 也放进… / 从这里拿掉」）：她手动改的存 index-overrides.json，永远压过 AI；能撤销 ──
async function reclassify(list, op, path) {
  if (!list.length) return;
  const p = await want('indexAssign'); if (!p) return;
  let r = null;
  try { r = await p.indexAssign(list.map(x => x.id), op, path); }
  catch (e) { r = { ok: false, message: '没改上：' + (e?.message || e) }; }
  if (!r?.ok) { LB.say(r?.message || '没改上', { kind: 'error' }); return; }
  await reloadIndex();
  if (r.undo) LB.undoNotice(r.message, async () => { const u = await p.indexAssign([], 'undo', r.undo); if (!u?.ok) throw new Error(u?.message || '没撤销上'); await reloadIndex(); });
  else LB.say(r.message, { kind: 'ok' });
}
function pickNode(title, { here = '' } = {}) {
  return new Promise(resolve => {
    document.querySelectorAll('.lbc-dialog-back').forEach(e => e.remove());
    const back = document.body.createEl('div', { cls: 'lbc-dialog-back' });
    const box = back.createEl('div', { cls: 'lbc-dialog lbi-pick-dialog' }); box.onclick = e => e.stopPropagation();
    box.createEl('h3', { text: title });
    const input = box.createEl('input'); input.type = 'text'; input.placeholder = '搜分类名…';
    const list = box.createEl('div', { cls: 'lbi-pick' });
    const nodes = (idx?.nodes || []).filter(n => n && !n.virtual);
    let first = null, done = false;
    const close = v => { if (done) return; done = true; back.remove(); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const paint = () => {
      list.empty(); first = null;
      const q = input.value.trim().toLowerCase();
      const hits = nodes.filter(n => !q || n.path.toLowerCase().includes(q));
      if (!hits.length) { list.createEl('div', { cls: 'lbi-pick-empty', text: '没有这个分类：先在 索引.md 里加一行' }); return; }
      for (const n of hits) {
        const isHere = n.path === here;
        const b = list.createEl('button', { cls: 'lbi-pick-row' + (isHere ? ' is-here' : '') }); b.type = 'button';
        b.dataset.path = n.path;
        b.style.paddingLeft = (8 + (q ? 0 : (n.depth - 1) * 14)) + 'px';
        b.createEl('span', { text: q ? pathText(n.path) : n.name });
        b.createEl('span', { cls: 'lbi-pick-n', text: isHere ? '现在在这' : String(n.count) });
        if (isHere) { b.disabled = true; continue; }
        if (!first) { first = b; if (q) b.classList.add('is-first'); }
        b.onclick = () => close(n.path);
      }
    };
    const onKey = e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); }
      else if (e.key === 'Enter' && !e.isComposing && document.activeElement === input && first) { e.preventDefault(); close(first.dataset.path); }
    };
    document.addEventListener('keydown', onKey, true);
    input.oninput = paint; back.onclick = () => close(null);
    paint();
    try { input.focus(); } catch {}
  });
}
// 卡片右键 /「归类…」/ 多选栏共用：这几篇的改归类菜单项
function reclassItems(list) {
  if (!idx || !list.length) return [];
  const n = list.length > 1 ? `选中的 ${list.length} 篇` : '';
  const node = idxByPath.get(activeCat);
  const here = node && !node.virtual ? node : null;
  const inHere = here ? list.filter(x => nodeIds(here.path)?.has(x.id)) : [];
  return [
    { title: n ? `把${n}移到…` : '移到…（只放这一类）', onClick: async () => { const p = await pickNode(n ? `把${n}移到…` : `把《${(list[0].title || '').slice(0, 18)}》移到…`, { here: list.length === 1 ? (idx.assign?.[list[0].id] || [])[0] : '' }); if (p) reclassify(list, 'move', p); } },
    { title: n ? `把${n}也放进…` : '也放进…', onClick: async () => { const p = await pickNode(n ? `把${n}也放进…` : `《${(list[0].title || '').slice(0, 18)}》也放进…`); if (p) reclassify(list, 'add', p); } },
    inHere.length ? { title: `从「${here.name}」拿掉${inHere.length > 1 ? ` ${inHere.length} 篇` : ''}（只改分类，帖子还在）`, onClick: () => reclassify(inHere, 'remove', here.path) } : null,
    // 10-11 细分标签 = 帖子的标签（她定：标签属于帖子）：打勾 = 这几篇都有；点一下加上 / 去掉（记成她改的，AI 压不过）；
    //   列的是这一类那一行的标签 + 这几篇自己身上的；最后一项起个新的
    ...(() => {
      const own = list.flatMap(x => idx.item_tags?.[x.id] || []);
      const names = [...new Set([...(here ? facetsOf(here.path).filter(f => !f.other).map(f => f.name) : []), ...own])].slice(0, 14);
      // 1015 她：右键菜单太长（标签逐条列出）→ 收进一个「标签 ▸」二级菜单
      const kids = names.map(name => {
        const all = list.every(x => (idx.item_tags?.[x.id] || []).includes(name));
        return { title: name, checked: all, onClick: () => setFacet(list, here?.path || '', all ? 'remove' : 'add', name) };
      });
      kids.push({ title: '加一个标签…', onClick: async () => { const name = await askName(`给${n || '这篇'}加一个标签`); if (name) setFacet(list, here?.path || '', 'add', name); } });
      return [{ title: '标签', children: kids }];
    })(),
  ].filter(Boolean);
}
async function setFacet(list, path, op, name) {
  const p = await want('indexFacet'); if (!p) return;
  let r = null;
  try { r = await p.indexFacet(list.map(x => x.id), path, op, name); }
  catch (e) { r = { ok: false, message: '没改上：' + (e?.message || e) }; }
  if (!r?.ok) { LB.say(r?.message || '没改上', { kind: 'error' }); return; }
  await reloadIndex();
  if (r.undo) LB.undoNotice(r.message, async () => { const u = await (await want('indexAssign'))?.indexAssign([], 'undo', r.undo); if (!u?.ok) throw new Error(u?.message || '没撤销上'); await reloadIndex(); });
  else LB.say(r.message, { kind: 'ok' });
}
function askName(title) {
  return new Promise(resolve => {
    document.querySelectorAll('.lbc-dialog-back').forEach(e => e.remove());
    const back = document.body.createEl('div', { cls: 'lbc-dialog-back' });
    const box = back.createEl('div', { cls: 'lbc-dialog lbi-name-dialog' }); box.onclick = e => e.stopPropagation();
    box.createEl('h3', { text: title });
    const input = box.createEl('input'); input.type = 'text'; input.maxLength = 8; input.placeholder = '2–6 个字，比如 牛排';
    const bar = box.createEl('div', { cls: 'lbc-dialog-bar' });
    const cancel = bar.createEl('button', { text: '取消' }); cancel.type = 'button';
    const ok = bar.createEl('button', { text: '加上', cls: 'mod-cta' }); ok.type = 'button';
    let done = false;
    const close = v => { if (done) return; done = true; back.remove(); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); } else if (e.key === 'Enter' && !e.isComposing && document.activeElement === input) { e.preventDefault(); close(input.value.trim() || null); } };
    document.addEventListener('keydown', onKey, true);
    ok.onclick = () => close(input.value.trim() || null); cancel.onclick = () => close(null); back.onclick = () => close(null);
    try { input.focus(); } catch {}
  });
}

// ── 网格 ──
const grid = imain.createEl('div', { cls: 'lbc-grid' });
const listBox = imain.createEl('div', { cls: 'lbc-list' }); listBox.hidden = true;   // 1021「列表」视图（1023 起入口藏了，代码留着）
// 1026 她：Wiki = 长期研究主题视图（索引.md 里标了 [wiki] 的分类，各自一页 wiki）；未归类是兜底队列，也在这里露着，不藏
const wikiBox = imain.createEl('div', { cls: 'lbc-wiki' }); wikiBox.hidden = true;
let wikiKey = null;
function renderWiki() {
  const nodes = idx ? (idx.nodes || []).filter(n => n && (n.wiki || (idx.wiki || {})[n.path])) : [];
  const unc = idx?.unclassified?.count || 0;
  const key = JSON.stringify([!!idx, nodes.map(n => [n.path, n.count, (idx.wiki || {})[n.path] || null]), unc, !!idx?.text_ai?.ok, mobile]);
  if (key === wikiKey && wikiBox.firstChild) return;
  wikiKey = key;
  wikiBox.empty();
  const head_ = wikiBox.createEl('div', { cls: 'lbc-wiki-head' });
  head_.createEl('h3', { text: 'Wiki' });
  head_.createEl('p', { cls: 'lbc-wiki-sub', text: '长期研究主题：一个分类攒够了内容，就给它一页 wiki（从帖子里整理出来的清单，可以一直更新）。平时找东西用瀑布流和筛选，这里看已经整理过的。' });
  if (idx) { const b = head_.createEl('button', { cls: 'lbc-wiki-btn lbc-index-open', text: '分类树 · 索引编辑' }); b.type = 'button'; b.onclick = () => openIndexEditor(); }
  const list = wikiBox.createEl('div', { cls: 'lbc-wiki-list' });
  if (!idx) list.createEl('p', { cls: 'lbc-wiki-empty', text: '还没有分类索引：刷新一次目录就会生成 索引.md。' });
  else if (!nodes.length) list.createEl('p', { cls: 'lbc-wiki-empty', text: '还没有长期研究主题。在 索引.md 里给一个分类那一行末尾加上 [wiki]，它就会出现在这里。' });
  for (const n of nodes) {
    const st = (idx.wiki || {})[n.path] || {};
    const row = list.createEl('div', { cls: 'lbc-wiki-row' }); row.dataset.path = n.path;
    const t = row.createEl('div', { cls: 'lbc-wiki-t' });
    t.createEl('b', { text: pathText(n.path) });
    t.createEl('span', { cls: 'lbc-wiki-n', text: `${n.count || 0} 篇` });
    t.createEl('span', { cls: 'lbc-wiki-st', text: st.exists ? (st.new_since ? `wiki 生成后又进了 ${st.new_since} 篇` : 'wiki 是最新的') : '还没生成 wiki' });
    const acts = row.createEl('div', { cls: 'lbc-wiki-acts' });
    if (st.exists && st.file) panelButton(acts, '打开 wiki', () => openVaultFile(st.file), 'lbc-wiki-btn lbc-wiki-open');
    panelButton(acts, '看这些帖子', () => { activeCat = n.path; activeFacets = []; viewMode = 'grid'; renderCatBar({ reveal: true }); render(); scrollToResults(); }, 'lbc-wiki-btn lbc-wiki-items');
    if (!mobile) { const g = panelButton(acts, st.exists ? '更新 wiki' : '生成 wiki', b => indexAction('wikiBuild', b, '正在生成 wiki…', n.path), 'lbc-wiki-btn lbc-wiki-gen'); if (!idx.text_ai?.ok) { g.disabled = true; g.title = '没有能用的文本 AI：设置里配一个'; } }
  }
  if (idx) {
    const u = wikiBox.createEl('div', { cls: 'lbc-wiki-row lbc-wiki-unc' });
    const t = u.createEl('div', { cls: 'lbc-wiki-t' });
    t.createEl('b', { text: '未归类' }); t.createEl('span', { cls: 'lbc-wiki-n', text: `${unc} 篇` });
    t.createEl('span', { cls: 'lbc-wiki-st', text: unc ? '还没放进任何分类的兜底队列：挪进分类，或在分类树里看「建议新增」' : '都归好了' });
    if (unc) panelButton(u.createEl('div', { cls: 'lbc-wiki-acts' }), '看这些帖子', () => { activeCat = UNC; viewMode = 'grid'; renderCatBar({ reveal: true }); render(); scrollToResults(); }, 'lbc-wiki-btn lbc-wiki-items');
  }
}
// 「索引编辑」= 分类树视图（拖拽调层级、改名、合并、空分类删 / 留）：入口在「管理」和 Wiki 页
function openIndexEditor() {
  if (!idx) { editCategories(); return; }
  viewMode = 'grid'; indexView = true;
  renderCatBar({ reveal: true }); render(); scrollToResults();
}
// ── 1026 她（15:37「最近导入没法看更多，只有最新的几条」）：最近导入的完整列表——按导入时间新→旧，一页 50 条翻页；当前来源下全部，不受筛选影响 ──
const RECENT_PAGE = 50;
let recentKey = null;
const recentBox = imain.createEl('div', { cls: 'lbc-recent' }); recentBox.hidden = true;
function recentAll() { return items.filter(it => importedAt(it) > 0).sort((a, b) => importedAt(b) - importedAt(a)); }
function openRecentAll() { recentPage = 1; recentKey = null; viewMode = 'recent'; indexView = false; renderCatBar(); render(); scrollToResults(); }
function renderRecent() {
  const all = recentAll();
  const pages = Math.max(1, Math.ceil(all.length / RECENT_PAGE));
  if (recentPage > pages) recentPage = pages;
  const key = [dataRev, items.length, all[0]?.id, recentPage, pages].join('|');
  if (key === recentKey && recentBox.firstChild) return;
  recentKey = key;
  recentBox.empty();
  const bar = recentBox.createEl('div', { cls: 'lbc-recent-head' });
  const back = bar.createEl('button', { cls: 'lbc-wiki-btn', text: '← 回到瀑布流' }); back.type = 'button'; back.dataset.act = 'back';
  back.onclick = () => pickView('grid');
  bar.createEl('b', { cls: 'lbc-recent-t', text: '最近导入 · 全部' });
  bar.createEl('span', { cls: 'lbc-recent-sub', text: `${all.length} 篇，按导入时间新→旧` });
  const table = recentBox.createEl('table', { cls: 'lbc-ltable lbc-rtable' });
  const hr = table.createEl('thead').createEl('tr');
  for (const [cls, t] of [['lbc-lt-date', '导入时间'], ['lbc-lt-title', '标题'], ['lbc-lt-cat', '分类'], ['lbc-lt-au', '作者']]) hr.createEl('th', { cls, text: t });
  const tb = table.createEl('tbody');
  for (const it of all.slice((recentPage - 1) * RECENT_PAGE, recentPage * RECENT_PAGE)) {
    const tr = tb.createEl('tr', { cls: 'lbc-lrow lbc-rrow' }); tr.tabIndex = 0; tr.dataset.id = it.id;
    tr.createEl('td', { cls: 'lbc-lt-date', text: fmtTime(importedAt(it)) });
    const td = tr.createEl('td', { cls: 'lbc-lt-title' }); if (it.starred) td.createEl('span', { cls: 'lbc-lt-star', text: '★' }); td.append(cardTitle(it));
    tr.createEl('td', { cls: 'lbc-lt-cat', text: catNameOf(it) });
    tr.createEl('td', { cls: 'lbc-lt-au', text: it.author || it.source || '收藏' });
    tr.onclick = e => openFromSide(it, e);
    tr.onauxclick = e => { if (e.button === 1) { e.preventDefault?.(); openFromSide(it, e, true); } };
    tr.onkeydown = e => { if (e.target === tr && e.key === 'Enter') openFromSide(it, e); };
    if (!mobile) tr.oncontextmenu = e => { e.preventDefault(); openCardMenu(e, tr, it, { row: true }); };
  }
  const pager = recentBox.createEl('div', { cls: 'lbc-rpager' });
  const go = d => { recentPage = Math.max(1, Math.min(pages, recentPage + d)); render(); scrollToResults(); };
  const prev = pager.createEl('button', { cls: 'lbc-wiki-btn', text: '上一页' }); prev.type = 'button'; prev.dataset.act = 'prev'; prev.disabled = recentPage <= 1; prev.onclick = () => go(-1);
  pager.createEl('span', { cls: 'lbc-rpage', text: `第 ${recentPage} / ${pages} 页` });
  const next = pager.createEl('button', { cls: 'lbc-wiki-btn', text: '下一页' }); next.type = 'button'; next.dataset.act = 'next'; next.disabled = recentPage >= pages; next.onclick = () => go(1);
}
// 10-03（她定）：Ctrl + 加号 / 减号、Ctrl + 鼠标滚轮调瀑布流列数，最少 2 列、最多 6 列（加号 / 往上滚 = 卡片变大、列变少）。
// 列数记在插件设置 catalogColumns（目录页和星标页同一个）；插件不在就记在页面状态。0 = 没调过，按页面宽度自动。
const COLS_MIN = 2, COLS_MAX = 6;
let cols = 0, colsTimer = null, hover = false, wheelAcc = 0, wheelAt = 0, roWidth = 0;
const colsOf = v => { v = Number(v) || 0; return v >= COLS_MIN && v <= COLS_MAX ? Math.round(v) : 0; };
function savedCols() { const p = provider(); return colsOf(p?.settings?.catalogColumns) || (p?.settings ? 0 : colsOf(saved.cols)); }
function applyCols() {
  grid.classList.toggle('lbc-has-cols', !!cols);
  if (cols) grid.style.setProperty('--lbc-cols', String(cols)); else grid.style.removeProperty('--lbc-cols');
}
const narrow = () => (typeof innerWidth === 'number' ? innerWidth : 1200) <= 700;
function gridWidth() { if (roWidth > 0) return roWidth; const w = Number(grid.clientWidth) || 0; return w > 0 ? Math.max(0, w - 10) : 0; }
// 1026 卡片密度（1027 起在收藏墙模块的「调整」里：紧凑 / 标准 / 宽松）：自动列数上 +1 / 0 / −1；手动调过列数（Ctrl + 滚轮）就按手动的
const DENSITY_DELTA = { s: 1, m: 0, l: -1 };
function colCount() {
  if (simplePage) return 1;
  if (cols) return lbcColumns(gridWidth(), { cols, narrow: narrow() });
  const auto = lbcColumns(gridWidth(), { narrow: narrow() });
  const d = DENSITY_DELTA[wallDensity()] || 0;
  return Math.max(1, Math.min(COLS_MAX, auto + d));
}
// 区块间距（1027 起是「Aa 样式」的卡片间距 theme.gap，px，标准 24）：卡片列距跟着缩放（CSS 里模块间距、栏距读同一个 --lbc-sp）
const gapPx = () => Math.round((narrow() ? 14 : 24) * gapScale());
function currentCols() { return cols || laidN || colCount(); }
function setCols(next) {
  next = Math.max(COLS_MIN, Math.min(COLS_MAX, Math.round(next)));
  if (next === cols) return false;
  cols = next; applyCols(); saveState();
  relayoutIfNeeded();
  LB.say(`瀑布流 ${cols} 列`, { ms: 1500 });
  const p = provider();
  if (p?.settings) { p.settings.catalogColumns = cols; p.markSettingDirty?.('catalogColumns'); clearTimeout(p.__lbColsSave); p.__lbColsSave = setTimeout(() => { try { p.saveSettings?.(); } catch {} }, 600); }
  return true;
}
// dir > 0：卡片变大（列少）；dir < 0：卡片变小（列多）
function stepCols(dir) { return setCols(currentCols() + (dir > 0 ? -1 : 1)); }
// 页面级快捷键只给「她正在看的那一页」（CM1：不再看鼠标停在哪）
const pageActive = () => LB.activeLeafHas(wrap);
function onColsKey(e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  const k = e.key, c = e.code;
  const bigger = k === '=' || k === '+' || c === 'Equal' || c === 'NumpadAdd', smaller = k === '-' || k === '_' || c === 'Minus' || c === 'NumpadSubtract';
  if (!bigger && !smaller) return;
  if (!pageActive()) return;
  e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation?.();   // 这一页上不让 Obsidian 整窗缩放
  stepCols(bigger ? 1 : -1);
}
// C10：Ctrl + 滚轮——只有按住 Ctrl 且鼠标在页上时才挂非 passive 的滚轮监听，松开 / 失焦就摘
function onCtrlWheel(e) {
  if (!(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  const now = Date.now(); if (now - wheelAt > 500) wheelAcc = 0; wheelAt = now;
  wheelAcc += Number(e.deltaY) || 0;
  if (Math.abs(wheelAcc) < 100) return;   // 鼠标滚轮一格约 100；触控板捏合是小步，攒够一格再动
  const dir = wheelAcc < 0 ? 1 : -1; wheelAcc = 0; stepCols(dir);
}
let wheelOn = false;
const wheelAttach = () => { if (wheelOn || mobile) return; wheelOn = true; wrap.addEventListener('wheel', onCtrlWheel, { passive: false }); };
const wheelDetach = () => { if (!wheelOn) return; wheelOn = false; wrap.removeEventListener('wheel', onCtrlWheel, { passive: false }); };
cleanups.push(wheelDetach);
wrap.addEventListener('mouseenter', e => { hover = true; if (e?.ctrlKey || e?.metaKey) wheelAttach(); });
wrap.addEventListener('mouseleave', () => { hover = false; wheelDetach(); });
const keyTarget = typeof window !== 'undefined' && window && typeof window.addEventListener === 'function' ? window : document;
LB.listen('cols-key', keyTarget, 'keydown', onColsKey, { capture: true });
LB.listen('ctrl-down', keyTarget, 'keydown', e => { if ((e.key === 'Control' || e.key === 'Meta') && hover) wheelAttach(); }, { passive: true });
LB.listen('ctrl-up', keyTarget, 'keyup', e => { if (e.key === 'Control' || e.key === 'Meta') wheelDetach(); }, { passive: true });
LB.listen('ctrl-blur', keyTarget, 'blur', () => wheelDetach(), { passive: true });

// ── 删除收藏（C3）：直接移到回收站（1019 她：不弹确认） → 只摘后端确认删掉的 ──
let deleting = false;
async function confirmDelete(list) {
  if (!list.length || deleting) return;
  const p = await want('deleteItems'); if (!p) return;
  deleting = true;
  const restoreBar = setSelbarBusy('');
  if (delBtn) { delBtn.setText('删除中…'); delBtn.disabled = true; }
  const cards = list.map(x => cardCache.get(x.id)?.el).filter(Boolean);
  for (const c of cards) c.classList.add('is-deleting');
  try {
    const r = await p.deleteItems(list.map(x => x.id));
    // 第 3 批：只摘后端确认删掉的；没删掉的保持选中、说清几篇和原因（CONVENTIONS §1）
    const results = r?.results || [];
    const gone = new Set(results.filter(x => x.status === 'deleted' || x.status === 'ok').map(x => x.item_id));
    for (let i = items.length - 1; i >= 0; i--) if (gone.has(items[i].id)) items.splice(i, 1);
    for (let i = allItems.length - 1; i >= 0; i--) if (gone.has(allItems[i].id)) allItems.splice(i, 1);   // 1020：items 可能只是一个来源的子集
    for (const id of gone) { selected.delete(id); const c = cardCache.get(id); c?.el?.remove(); cardCache.delete(id); }
    for (const c of cards) c.classList.remove('is-deleting');
    const left = list.filter(x => !gone.has(x.id));
    if (gone.size) { dataRev++; withAnchor(() => render()); }
    if (left.length && !mobile) { for (const x of left) selected.add(x.id); selectMode = true; }
    selectMode = selected.size > 0;
    paintSelectMode();
    if (!left.length) LB.say(`已删 ${gone.size} 篇，移到了回收站（可恢复）`, { kind: 'ok', actions: [{ label: '打开回收站', run: () => LB.openPage('trash') }] });
    else {
      const why = [...new Set(left.map(x => { const row = results.find(y => y.item_id === x.id); return row?.error || (row?.status === 'missing' ? '库里没有这一篇（可能已经删过）' : row ? '没删掉' : '后台没回这一篇的结果'); }))];
      LB.say((gone.size ? `已删 ${gone.size} 篇；` : '') + `${left.length} 篇没删掉：${why.join('；')}` + (gone.size ? '' : '（可以再点一次删除重试）'), { kind: 'error' });
    }
    if (r?.catalog_error) LB.say('目录没重建上：' + r.catalog_error, { kind: 'error' });
  } catch (e) {
    for (const c of cards) c.classList.remove('is-deleting');
    LB.say('删除没完成：' + (e?.message || e) + '（后台没回逐条结果，点「…→刷新目录」核对哪些已经进了回收站）', { kind: 'error' });
  } finally {
    deleting = false; restoreBar(); paintSelbar();
  }
}
// ── 右键编辑标签（C13）：存完收起 + 卡上闪「已保存」；失败说原因、字不动；Esc 关掉不动多选 ──
function openTagEditor(card, it) {
  const body = card.querySelector('.lbc-body');
  if (!body || body.querySelector('form.lbc-tagform')) return;
  const form = body.createEl('form', { cls: 'lbc-tagform' }); form.onclick = e => e.stopPropagation();
  const field = form.createEl('input'); field.type = 'text'; field.value = (it.tags || []).join(', '); field.placeholder = '标签，用逗号分隔';
  const save = form.createEl('button', { text: '保存标签' }); save.type = 'submit';
  const cancel = form.createEl('button', { text: '取消' }); cancel.type = 'button';
  const err = form.createEl('div', { cls: 'lbc-tagform-err' }); err.hidden = true;
  const closeForm = () => { const c = form.closest('.lbc-card'); form.remove(); try { c?.focus?.({ preventScroll: true }); } catch { c?.focus?.(); } };
  cancel.onclick = e => { e?.stopPropagation?.(); closeForm(); };
  form.onkeydown = e => { e.stopPropagation(); if (e.key === 'Escape') { e.preventDefault(); closeForm(); } };
  form.onsubmit = async e => {
    e.preventDefault(); save.disabled = true; save.setText('保存中…'); err.hidden = true;
    const x = form.closest('.lbc-card')?._lbItem || it;
    try {
      const file = app.vault.getAbstractFileByPath(lbPath(x.note));
      if (!file) throw new Error('找不到这篇笔记');
      const tags = [...new Set(field.value.split(/[,，\n]/).map(t => t.trim().replace(/^#/, '')).filter(Boolean))];
      await app.fileManager.processFrontMatter(file, fm => { fm.tags = tags; });
      x.tags = tags; x._pendingTags = JSON.stringify(tags); try { searchCache.delete(x); } catch {}
      if (committed) dataRev++;
      const c = form.closest('.lbc-card'); form.remove();
      if (c) { const f = c.createEl('div', { cls: 'lbc-flash', text: '已保存' }); setTimeout(() => f.remove(), 1500); try { c.focus({ preventScroll: true }); } catch {} }
    } catch (e2) {
      save.disabled = false; save.setText('保存标签');
      err.hidden = false; err.setText('没保存上，内容还在，可重试：' + (e2?.message || e2));
    }
  };
  field.focus();
  return form;
}
// ── 右键菜单（插件的 obsidian.Menu；插件不在时自制，键盘可操作，C17） ──
function openCardMenu(e, card, it, { row = false } = {}) {
  const r = card.getBoundingClientRect();
  const kb = !e || (!e.clientX && !e.clientY);
  const pos = kb ? { x: r.left + 16, y: r.top + 16 } : { x: e.clientX, y: e.clientY };
  let list;
  // 10-04：有选中时右键 = 对选中的这些操作（右键的这张没选上就一起算进来）；「导出」立即导出（沿用「附带原图」）
  if (selectMode && selected.size) {
    if (!selected.has(it.id)) { selected.add(it.id); paintCard(it.id); paintSelbar(); saveState(); }
    const sel = () => items.filter(x => selected.has(x.id));
    const n = selected.size;
    list = [
      { title: `导出选中的 ${n} 篇`, onClick: () => exportNow(sel()) },
      { title: '给 AI（存成选集）', onClick: () => saveSelectionDialog(sel()) },
      { title: sel().every(x => x.starred) ? `取消收藏选中的 ${n} 篇` : `收藏选中的 ${n} 篇`, onClick: () => starMany(sel()) },
      ...reclassItems(sel()),          // 10-11：移到… / 也放进… / 从这里拿掉（有索引才有）
      { title: `删除选中的 ${n} 篇（移到回收站）`, danger: true, onClick: () => confirmDelete(sel()) },
      { title: '退出多选', onClick: () => clearSelection() },
    ];
  } else {
    list = [
      { title: it.starred ? '取消收藏' : '收藏', onClick: () => starMany([it], { single: true }) },
      row ? null : { title: '编辑标签', onClick: () => openTagEditor(card, it) },
      ...reclassItems([it]),
      it.attachment !== 'none' ? { title: '下载 / 挂本地文件', onClick: () => attachmentPanel([it]) } : null,
      typeof provider()?.refineImages === 'function' ? { title: '精细识别图片', onClick: () => provider().refineImages(it.item_id || it.id) } : null,
      { title: '导出', onClick: () => exportNow([it]) },
      { title: '给 AI（存成选集）', onClick: () => saveSelectionDialog([it]) },
      { title: '多选', onClick: () => toggleSelect(it.id, { force: true }) },
      { title: '删除（移到回收站）', danger: true, onClick: () => confirmDelete([it]) },
    ].filter(Boolean);
  }
  return popMenu(list, e, card, pos);
}

// ── 收藏（C3：乐观更新 + busy，失败回滚；一次批量只起 1 个 Python 进程；CM3：写完 adopt，下次重跑 0 读） ──
// 1015 她：收藏那一下星变黄、弹一下（只在点的那一刻，不在每次重画时）
function popStar(id) {
  const st = cardCache.get(id)?.el?.querySelector?.('.lbc-star');
  if (!st) return;
  st.classList.remove('is-pop'); void st.offsetWidth; st.classList.add('is-pop');
  setTimeout(() => st.classList.remove('is-pop'), 600);
}
async function starMany(list, { single = false } = {}) {
  const on = single ? !list[0]?.starred : !list.every(x => x.starred);
  const todo = list.filter(x => !!x.starred !== on && !x._starBusy);
  if (!todo.length) return;
  const p = await want('starNotes'); if (!p) return;
  for (const x of todo) { x._prevStar = !!x.starred; x.starred = on; x._starBusy = true; paintCard(x.id); }
  if (on) for (const x of todo) popStar(x.id);
  const restoreBar = !single ? setSelbarBusy(`正在${on ? '收藏' : '取消收藏'} ${todo.length} 篇…`) : () => {};
  let res = null, err = null;
  try { res = await p.starNotes(todo.map(x => x.id), on); } catch (e) { err = e; }
  const byId = new Map((res?.results || []).map(r => [r.item_id, r]));
  const failed = [];
  for (const x of todo) {
    const row = byId.get(x.id);
    if (!err && row && row.status === 'ok') { x.starred = !!row.starred; if ('starred_at' in row) x.starred_at = row.starred_at; }
    else {
      x.starred = x._prevStar;
      failed.push(err ? (err.message || String(err)) : row?.error || (row?.status === 'missing' ? '库里没有这一篇（可能已经删过）' : row?.status === 'corrupt' ? '这篇的批注文件读不了' : row ? '没保存上' : '后台没回这一篇的结果'));
    }
    x._starBusy = false; delete x._prevStar; paintCard(x.id);
  }
  restoreBar(); paintSelbar();
  if (res?.catalog_patched) { try { LB.data.adopt(await LB.data.version(), data, res.catalog_stat || null); } catch {} }
  const verb = on ? '收藏' : '取消收藏';
  const why = [...new Set(failed)].join('；');
  const okN = todo.length - failed.length;
  if (single || todo.length === 1) { if (failed.length) LB.say(`${verb}没保存上，可重试：${why}`, { kind: 'error' }); }
  else if (!failed.length) LB.say(on ? `已收藏 ${okN} 篇（点「已收藏」筛出来看）` : `已取消收藏 ${okN} 篇`, { kind: 'ok' });
  else LB.say(`${okN ? `已${verb} ${okN} 篇；` : ''}${failed.length} 篇没${verb}上：${why}`, { kind: 'error' });
}
// ── 导出（CM2：成功提示由插件那一条负责；页面只有进行中和失败） ──
async function exportNow(list, { button = null } = {}) {
  if (!list.length) { LB.say('先选几篇'); return; }
  const p = await want('exportArchiveBundle'); if (!p) return;
  const prog = LB.progress(`正在导出 ${list.length} 篇…`);
  const done = button ? LB.busy(button, '导出中…') : () => {};
  try { await p.exportArchiveBundle(list.map(x => x.id), !!exportImages, '', { question: search.value || '选中收藏' }); }
  catch (e) { LB.say('导出没完成：' + (e?.message || e), { kind: 'error' }); }
  finally { prog.hide(); done(); }
}
let copying = false;
async function copyBundleNow(list) {
  if (!list.length || copying) return;
  const p = await want('exportArchiveBundle'); if (!p) return;
  copying = true;
  const prog = LB.progress(`正在打包 ${list.length} 篇…`);
  try { await p.exportArchiveBundle(list.map(x => x.id), !!exportImages, '', { question: search.value || '选中收藏', copy: true }); }
  catch (e) { LB.say('文件包没复制上：' + (e?.message || e), { kind: 'error' }); }
  finally { prog.hide(); copying = false; }
}
// ── 10-04 选集（给 AI 用）：选中的几篇存成有名字的一组，存 _archive/selections.json ──
// 默认名字 = 主题 + 日期（MMDD）：主题取选中篇目共同的标签 → 星标主题 → 大类；都没有就第一篇标题前 8 个字
function defaultSelectionName(list) {
  const d = new Date(), mmdd = String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
  const clean = s => String(s || '').replace(/^#/, '').replace(/[^\p{L}\p{N}]+/gu, '');
  const common = key => { if (!list.length) return ''; const sets = list.map(x => new Set((Array.isArray(x[key]) ? x[key] : []).map(clean).filter(Boolean))); return [...sets[0]].find(v => v !== '其他' && sets.every(s => s.has(v))) || ''; };
  const theme = (common('tags') || common('topics') || common('cats') || clean(list[0]?.title).slice(0, 8) || '选集').slice(0, 12);
  return theme + mmdd;
}
const SELECTIONS = '_archive/selections.json';
async function readSelections() {
  try { const doc = JSON.parse(await app.vault.adapter.read(lbPath(SELECTIONS))); return Array.isArray(doc?.selections) ? doc.selections.filter(r => r && typeof r.name === 'string') : []; }
  catch { return []; }
}
// 存一组：同名就合并（1019 她：abc 存过再存 bd = abcd，不覆盖、不弹窗）；每篇记加入时间（added），给 AI 看；写盘成功才提示（§1.5）
async function storeSelection(name, list) {
  const rows = await readSelections();
  const now = new Date().toISOString();
  const old = rows.find(r => r.name === name);
  const ids = [...(old?.ids || [])];
  const added = { ...(old?.added || {}) };
  for (const x of list) { if (!ids.includes(x.id)) { ids.push(x.id); added[x.id] = now; } }
  for (const id of ids) if (!added[id]) added[id] = old?.created_at || now;
  const row = { name, ids, added, created_at: old?.created_at || now, updated_at: now };
  await app.vault.adapter.write(lbPath(SELECTIONS), JSON.stringify({ selections: [row, ...rows.filter(r => r.name !== name)] }, null, 1));
  return true;
}
function saveSelectionDialog(list) {
  if (!list.length) { LB.say('先选几篇'); return; }
  document.querySelectorAll('.lbc-dialog-back').forEach(e => e.remove());
  const back = document.body.createEl('div', { cls: 'lbc-dialog-back' });
  const box = back.createEl('div', { cls: 'lbc-dialog' }); box.onclick = e => e.stopPropagation();
  box.createEl('h3', { text: `存成选集（${list.length} 篇，给 AI 看）` });
  box.createEl('div', { cls: 'lbc-dialog-list', text: list.slice(0, 6).map(x => x.title || x.id).join('、') + (list.length > 6 ? ` 等 ${list.length} 篇` : '') });
  const input = box.createEl('input'); input.type = 'text'; input.value = defaultSelectionName(list); input.maxLength = 40;
  const hint = box.createEl('div', { cls: 'lbc-dialog-hint' });
  const paintHint = () => hint.setText(`名字就是暗号：以后对 AI 说「看一下选集 ${input.value.trim() || '…'}」`); paintHint();
  const err = box.createEl('div', { cls: 'lbc-dialog-err' }); err.hidden = true;
  const bar = box.createEl('div', { cls: 'lbc-dialog-bar' });
  const cancel = bar.createEl('button', { text: '取消' }); cancel.type = 'button';
  const ok = bar.createEl('button', { text: '存', cls: 'mod-cta' }); ok.type = 'button';
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey, true); };
  const save = async () => {
    const name = input.value.trim().replace(/\s+/g, ' ').slice(0, 40);
    if (!name) { err.hidden = false; err.setText('起个名字'); return; }
    ok.disabled = true; err.hidden = true;
    try {
      if (!(await storeSelection(name, list))) { ok.disabled = false; return; }
      close();
      const phrase = `看一下选集 ${name}`; let copied = false;
      try { await navigator.clipboard.writeText(phrase); copied = true; } catch {}
      LB.say(`已存成选集「${name}」，对 AI 说：${phrase}${copied ? '（这句已复制）' : ''}`, { kind: 'ok', ms: 10000 });
    } catch (e) { ok.disabled = false; err.hidden = false; err.setText('没存上，可重试：' + ((e && e.message) || e)); }
  };
  const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } else if (e.key === 'Enter' && !e.isComposing && document.activeElement === input) { e.preventDefault(); save(); } };
  document.addEventListener('keydown', onKey, true);
  input.oninput = paintHint; ok.onclick = save; cancel.onclick = close; back.onclick = close;
  try { input.focus(); input.select?.(); } catch {}
  return box;
}

// ── 排名（C2：结果集只在 key 变了才重算；点星 / 勾选不重排） ──
let lastRanked = { key: null, exact: [], possible: [], q: '' };
function rankKey() { return JSON.stringify([committed, activeCat, activeTopic, activeAlbum, activeSrc, todayOnly, todoOnly, mediaFilter, activeTag, activePlat, starOnly || starredPage, timeSort, timeRange, timeFrom, timeTo, dataRev, idx ? selSig() : idxRev]); }
// 当前所有筛选（不含搜索词）；skipTag：Tag 菜单算「别的条件下还有哪些标签」时不算 Tag 自己
function passesFilters(it, today = ymd(new Date()), { skipTag = false } = {}) {
  return (!(starredPage || starOnly) || it.starred) && typeOk(it) && (skipTag || tagOk(it)) && platOk(it)
    && (!todayOnly || it.date === today) && (!todoOnly || it.attachment === '待补') && inCat(it)
    && (!activeTopic || (activeTopic === '*' ? (it.topics || []).length > 0 : (it.topics || []).includes(activeTopic))) && (!activeAlbum || (it.albums || []).includes(activeAlbum)) && inTimeRange(it);
}
function rankRows() {
  const key = rankKey();
  if (lastRanked.key === key) return lastRanked;
  perfCounts.rank++;
  const q = normalize(committed);
  const today = ymd(new Date());
  const filtered = items.filter(it => passesFilters(it, today));
  // 第 1 批 1002：先看分数、星标只 ×1.15；拼音 / 错字 / 漏字这类模糊命中单独放「可能相关」，规则见 catalog-search.js rankItems
  const ranked = rankItems(filtered, q, data.pinyin_chars, data.aliases || []);
  let exact = ranked.exact, possible = ranked.possible;
  // 10-04「最近导入」：两组各自按导入时间新→旧（同一时间保持原来的相关度顺序）
  if (timeSort === 'recent') { const byTime = (a, b) => importedAt(b.it) - importedAt(a.it); exact = [...exact].sort(byTime); possible = [...possible].sort(byTime); }
  const withLow = row => ({ ...row, low: q ? lowSnippetFor(row) : '' });   // 原词 / 同语种同义词命中 = ''；低置信度才出浅色片段
  lastRanked = { key, exact: exact.map(withLow), possible: possible.map(withLow), q };
  return lastRanked;
}
// 当前的筛选拼成一句（C8 空状态用）
function filterLabel() {
  return [activeCat && catLabel(activeCat), activeTopic && (activeTopic === '*' ? '★全部主题' : '★' + activeTopic), activeAlbum && '专辑：' + activeAlbum, todayOnly && '今日新增', todoOnly && '待补附件', mediaFilter && TYPE_LABEL[mediaFilter], activePlat && platLabel(activePlat), activeTag && '#' + activeTag,
    starOnly && !starredPage && '已收藏', timeRange && timeLabel().split(' · ')[0]].filter(Boolean).join(' · ');
}
function paintSub() {
  const r = lastRanked.key ? lastRanked : null;
  const filtered = !!(committed || todayOnly || todoOnly || starredPage || starOnly || mediaFilter || activeTag || activePlat || activeTopic || activeAlbum || activeCat || timeRange);
  // 1011 她问「43 / 659 是什么」：43 = 当前筛选 / 搜索命中几篇，659 = 目录里一共几篇（库里所有对象：收藏同步进来的 + 分享 / 导入单篇的，
  // 含后来取消收藏的；回收站里的不算）。和同步进度的「收藏已入库 A/T」不是一个数，悬停写明
  // 1023：默认只看「我的收藏」时，旁边带上全部几篇（问收藏页显示的是全部，两边对得上；ARCH-AUDIT §7）
  const allNote = !starredPage && allItems.length !== items.length ? ` · 全部 ${allItems.length}` : '';
  const countText = (filtered && r ? `筛出 ${r.exact.length} 篇（共 ${items.length}）` : `${items.length} 篇`) + allNote;
  if (countEl.textContent !== countText) {
    countEl.empty();
    if (filtered && r) { countEl.append('筛出 '); countEl.createEl('b', { text: String(r.exact.length) }); countEl.append(` 篇（共 ${items.length}）`); }
    else { countEl.createEl('b', { text: String(items.length) }); countEl.append(' 篇'); }
    if (allNote) countEl.append(allNote);
  }
  countEl.title = (filtered && r ? `当前筛选${filterLabel() ? '（' + filterLabel() + '）' : ''}命中 ${r.exact.length} 篇；` : '')
    + `目录里一共 ${items.length} 篇：收藏同步进来的 + 分享 / 导入单篇的（含后来取消收藏的，回收站里的不算）。收藏夹同步到哪了（收藏已入库几篇 / 还差几篇）点右边「更新」看同步记录`;
  const nPossible = r && !grid.hidden ? r.possible.length : 0;
  possibleLink.hidden = !nPossible; sepPossible.hidden = !nPossible;
  if (nPossible) possibleLink.setText(`可能相关 ${nPossible}`);
  const built = LB.dataUpdatedAt(data);
  updatedBtn.setText(`更新 ${built ? fmtTime(built) : '—'}`);
  updatedBtn.title = `目录数据生成于 ${built ? fmtFull(built) : '—'}（同步或刷新目录后更新）· 点开看同步记录`;
  // F4 跨设备兜底：同步记录显示已经更新过，这台设备上的 catalog-data 还是旧的（同步盘没跟上）
  const last = Math.max(tsOf(syncState?.last_success), tsOf(probSummary?.last_success), tsOf(probSummary?.sync?.last_success));
  const behind = !!built && last > 0 && last - Math.max(tsOf(built), tsOf(catalogCheckedAt)) > 10 * 60000 && !stale;
  staleEl.hidden = !behind;
  if (behind) staleEl.title = `同步记录显示 ${fmtTime(last)} 已更新，本机目录数据还是 ${fmtTime(built)} 的：等同步盘把 _archive/catalog-data.json 同步过来，或在电脑上刷新目录`;
}

// ── 卡片（§5.5 按 id 复用；C10：签名里没有星标 / 选中，状态只改 class） ──
const cardCache = new Map();
let firstCover = null;
 // 1015 系列帖（她 H 节）：同一作者几篇标题共用一长串前缀 → 卡片上露后半截（「…第 3 集」），悬停看全名
let seriesFor = null, seriesCut = new Map();
const SERIES_MIN = 8, SERIES_STRONG = /[】\]）)》｜|\-—–:：·•,，、]/;
function seriesCuts() {
  if (seriesFor === items) return seriesCut;
  seriesFor = items; seriesCut = new Map();
  const by = new Map();
  for (const it of items) { const t = String(it.title || ''); if (t.length < 14) continue; const a = it.author || it.source || ''; if (!by.has(a)) by.set(a, []); by.get(a).push(it); }
  for (const list of by.values()) {
    if (list.length < 2) continue;
    list.sort((a, b) => (String(a.title) < String(b.title) ? -1 : 1));
    const lcp = (a, b) => { let i = 0; const n = Math.min(a.length, b.length); while (i < n && a[i] === b[i]) i++; return i; };
    list.forEach((it, k) => {
      const t = String(it.title);
      let c = Math.max(k ? lcp(t, String(list[k - 1].title)) : 0, k < list.length - 1 ? lcp(t, String(list[k + 1].title)) : 0);
      if (c < SERIES_MIN || t.length - c < 2) return;
      // 别切在一个词中间：往回退到最近的分隔符（「…第 3 集」而不是「…3 集」）；退太多就不退
      // 先找括号 / 竖线 / 冒号这种明显的分界（「【…】第 3 集」），没有再退到空格
      let j = c; while (j > 0 && !SERIES_STRONG.test(t[j - 1])) j--;
      if (j >= SERIES_MIN - 2) c = j;
      else { j = c; while (j > 0 && !/\s/.test(t[j - 1])) j--; if (j >= SERIES_MIN - 2) c = j; }
      const rest = t.slice(c).replace(/^[\s｜|\-—–_:：·•,，、]+/, '');
      if (rest.length >= 2) seriesCut.set(it.id, '…' + rest);
    });
  }
  // 1016（待办 #9）：同一作者、标题一字不差的不同帖（系列重发，不是重复收藏）：标题后面带上发布日期，好分清是哪一篇
  const same = new Map();
  for (const it of items) { const k = (it.author || it.source || '') + '\u0000' + String(it.title || ''); if (!it.title) continue; if (!same.has(k)) same.set(k, []); same.get(k).push(it); }
  for (const list of same.values()) {
    if (list.length < 2) continue;
    for (const it of list) { const d = String(it.published || it.date || '').slice(0, 10); if (d) seriesCut.set(it.id, `${it.title} · ${d}`); }
  }
  return seriesCut;
}
const cardTitle = it => seriesCuts().get(it.id) || it.title || '未命名';
function cardSig(it, fuzzy, low) {
  return JSON.stringify([it.title, cardTitle(it), it.cover, it.cover_w, it.cover_h, it.kind, it.attachment, it.attachment_reason, it.author, it.source, it.likes, it.note, it.problems || null, fuzzy, low || '',
    it.cover ? '' : [catNameOf(it), it.date], cardTopics(it)]);
}
// 1021 卡片外观：无封面 = 柔和文字封面（按分类取一个浅色底：7 个同明度浅色、分类序号取模）；作者首字头像（底色按作者名散列）
const TILE_COLORS = ['#f2d7d0', '#f2e5b8', '#d5e6d6', '#d3e1ef', '#e0d9f0', '#f1dcc6', '#e2e9c9'];
const hashStr = v => { let h = 0; for (const ch of String(v || '')) h = (h * 31 + ch.codePointAt(0)) | 0; return Math.abs(h); };
function catNameOf(it) {
  const c = Array.isArray(it.cats) ? it.cats.find(x => typeof x === 'string' && x) : '';
  if (!c) return UNC_LABEL;
  const root = c.split('/')[0];
  return (idx && idxByPath.get(root)?.name) || root;
}
function tileColor(it) {
  const name = catNameOf(it);
  const order = idx ? (idx.roots || []).map(p => idxByPath.get(p)?.name || p) : (data.cats_order || []);
  const i = order.indexOf(name);
  return TILE_COLORS[(i >= 0 ? i : hashStr(name)) % TILE_COLORS.length];
}
// 「10/21」；不是今年的带上年份
function shortDay(v) {
  const m = String(v || '').match(/^(\d{4})-(\d{2})-(\d{2})/); if (!m) return '';
  const md = `${Number(m[2])}/${Number(m[3])}`;
  return Number(m[1]) === new Date().getFullYear() ? md : `${m[1]}/${md}`;
}
function tileType(it) {
  if (it.kind === 'video') return '▶ 视频';
  if (!it.attachment || it.attachment === 'none') return '';
  const files = Array.isArray(it.attachment_files) ? it.attachment_files : [];
  const f = files[0], name = typeof f === 'string' ? f : (f && (f.name || f.file || f.path)) || '';
  const ext = /\.([a-z0-9]{1,5})$/i.exec(String(name))?.[1]?.toUpperCase() || '';
  return ext ? ext + (files.length > 1 ? ` · ${files.length} 个` : '') : '附件';
}
const cardTopics = it => (Array.isArray(it.topics) ? it.topics.filter(t => typeof t === 'string' && t).slice(0, 2) : []);
const fmtLikes = v => (v == null ? '' : '♡ ' + (Number(v) >= 10000 ? (Number(v) / 10000).toFixed(1) + '万' : v));
const STAR_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6l2.55 5.17 5.7.83-4.13 4.02.98 5.68L12 16.62l-5.1 2.68.98-5.68L3.75 9.6l5.7-.83z"/></svg>';
const CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12.5l4 4 8-9"/></svg>';
const VIDEO_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>';
const FILE_SVG = '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';
// 1017 首开：每张卡 3–4 次 innerHTML 解析 SVG，884 张卡 ParseHTML 约 94ms——同一段 SVG 只解析一次，之后 cloneNode（DOM 和原来一样）。
// 没有 cloneNode 的环境（node 假 DOM）照旧 innerHTML。
const svgTpl = new Map();
function putSvg(el, html, { prepend = false } = {}) {
  let t = svgTpl.get(html);
  if (t === undefined) {
    t = null;
    try { const box = document.createElement('div'); box.innerHTML = html; const f = box.firstElementChild; if (f && typeof f.cloneNode === 'function' && f.tagName && f.tagName.toLowerCase() === 'svg') t = f; } catch {}
    svgTpl.set(html, t);
  }
  if (!t) { if (prepend) { const tmp = document.createElement('span'); tmp.innerHTML = html; el.prepend(...tmp.childNodes); } else el.innerHTML = html; return; }
  const node = t.cloneNode(true);
  if (prepend) el.prepend(node); else el.appendChild(node);
}
function paintCardState(card, it) {
  if (!card || !it) return;
  const on = selected.has(it.id);
  card.classList.toggle('is-selected', on);
  card.classList.toggle('is-starring', !!it._starBusy);
  const check = card.querySelector('.lbc-check');
  if (check) { check.classList.toggle('is-on', on); check.setAttribute('aria-pressed', String(on)); const h = check.querySelector('.lb-visually-hidden'); if (h) h.textContent = on ? '取消选中' : '选中'; }
  const star = card.querySelector('.lbc-star');
  if (star) {
    if (mobile) { star.hidden = !it.starred; return; }
    star.classList.toggle('is-on', !!it.starred);
    star.setAttribute('aria-pressed', String(!!it.starred));
    star.disabled = !!it._starBusy;
    const h = star.querySelector('.lb-visually-hidden'); if (h) h.textContent = it.starred ? '取消收藏' : '收藏';
  }
}
function paintCard(id) { const c = cardCache.get(id); if (c?.el) paintCardState(c.el, c.el._lbItem || items.find(x => x.id === id)); }
function getCard(row) {
  const { it, match, low } = row;
  const fuzzy = !!match.fuzzy;
  const sig = cardSig(it, fuzzy, low);
  const cached = cardCache.get(it.id);
  if (cached && cached.sig === sig) { cached.el._lbItem = it; paintCardState(cached.el, it); return cached.el; }
  const card = buildCard(it, fuzzy, low);
  // C4：同一篇的卡要重建、旧卡里开着标签框——整个搬进新卡，焦点和选区跟着
  // （摘下来时丢的焦点由 layoutGrid 摆完后还回去）
  const form = cached?.el?.querySelector?.('form.lbc-tagform');
  if (form) card.querySelector('.lbc-body')?.append(form);
  cardCache.set(it.id, { sig, el: card });
  return card;
}
function buildCard(it, fuzzy, low) {
  perfCounts.build++;
  // 不设 aria-label：Obsidian 会把 aria-label 渲染成 hover 浮框（她不要那个「悬浮的点的字」）。
  const card = document.createElement('article');
  card.className = 'lbc-card' + (fuzzy ? ' is-possible' : '');
  card.tabIndex = 0; card.setAttribute('role', 'link');
  // 卡片上的事件一律取 card._lbItem（数据刷新后复用的卡片换成新对象）
  card._lbItem = it; const cur = () => card._lbItem;
  if (it.cover) {
    const img = card.createEl('img', { cls: 'lbc-cover' }); img.loading = 'lazy'; img.decoding = 'async'; img.alt = '';
    // 有封面宽高就先占好位置：图片还没加载时版面不跳，返回目录时滚动位置能一次到位
    if (it.cover_w && it.cover_h) { img.setAttribute('width', String(it.cover_w)); img.setAttribute('height', String(it.cover_h)); }
    if (!firstCover) { firstCover = img; img.addEventListener?.('load', () => LB.mark('cover'), { once: true }); }
    img.src = app.vault.adapter.getResourcePath(lbPath(it.cover));
  } else {
    // 1021 柔和文字封面：左上分类小字、左下粗体标题、底部日期；视频 / 附件右下角一个小标签。文字固定深色（深色主题下也是浅底深字）
    const tile = card.createEl('div', { cls: 'lbc-nocover' });
    tile.style.setProperty('--lbc-tile', tileColor(it));
    tile.createEl('div', { cls: 'lbc-tile-cat', text: catNameOf(it) });
    tile.createEl('div', { cls: 'lbc-tile-title', text: cardTitle(it) });
    const foot = tile.createEl('div', { cls: 'lbc-tile-foot' });
    foot.createEl('span', { cls: 'lbc-tile-date', text: shortDay(it.date || it.ts) });
    const ty = tileType(it); if (ty) foot.createEl('span', { cls: 'lbc-tile-ty', text: ty });
  }
  // 附件角标：待补=有文件未下载（警示色），downloaded=有文件已下（灰）
  const badges = card.createEl('div', { cls: 'lbc-badges' });
  if (it.kind === 'video') { const v = badges.createEl('span', { cls: 'lbc-attach lbc-video' }); putSvg(v, VIDEO_SVG); }
  if (it.attachment === '待补') badges.createEl('div', { cls: 'lbc-attach lbc-attach-todo', text: '待补' });
  else if (it.attachment === '线索') badges.createEl('div', { cls: 'lbc-attach lbc-attach-hint', text: '疑似附件', attr: { title: it.attachment_reason || '正文提到附件，但没找到文件' } });
  else if (it.attachment === 'downloaded') badges.createEl('div', { cls: 'lbc-attach', text: '文件' });
  const badge = badges.querySelector('.lbc-attach:not(.lbc-video)');
  if (badge) { try { putSvg(badge, FILE_SVG, { prepend: true }); } catch {} }
  // 第 4 批：这篇的问题标（灰；要你处理的用醒目色），悬停看原因；同一个标签只出一个，和上面附件标同名的不重复出；「未开启」不上卡片
  const shownLabels = new Set(Array.from(badges.querySelectorAll('.lbc-attach'), b => b.textContent)); const probs = new Map();
  for (const p of Array.isArray(it.problems) ? it.problems : []) {
    if (!p || !p.label || p.group === 'off' || shownLabels.has(p.label)) continue;
    const g = probs.get(p.label) || { need: false, hover: [] }; g.need = g.need || p.group === 'needs_you';
    const why = p.hover || p.reason; if (why && !g.hover.includes(why)) g.hover.push(why); probs.set(p.label, g);
  }
  for (const [label, g] of probs) { const b = badges.createEl('span', { cls: 'lbc-attach lbc-prob' + (g.need ? ' is-need' : ''), text: label }); if (g.hover.length) b.title = g.hover.join('\n'); }
  // 1021 无封面卡：类型已经写在文字封面右下角（▶ 视频），左上的视频角标藏起来（CSS）；还有别的角标时文字封面让出顶上一行
  if (!it.cover && badges.querySelector('.lbc-attach:not(.lbc-video)')) card.querySelector('.lbc-nocover')?.classList.add('has-badges');
  if (!mobile) {
    // 10-04：悬停就出现的选中圈——点它直接勾选（不用先进多选）；勾了任何一篇就是多选态，全取消就退出
    const check = card.createEl('button', { cls: 'lbc-check' }); check.type = 'button'; check.setAttribute('aria-pressed', 'false');
    putSvg(check, CHECK_SVG);
    check.createEl('span', { cls: 'lb-visually-hidden', text: '选中' });
    check.onclick = e => { e?.preventDefault?.(); e?.stopPropagation?.(); toggleSelect(cur().id); };
    const star = card.createEl('button', { cls: 'lbc-star' }); star.type = 'button';
    putSvg(star, STAR_SVG);
    star.createEl('span', { cls: 'lb-visually-hidden', text: '收藏' });
    star.onclick = e => { e?.preventDefault?.(); e?.stopPropagation?.(); const x = cur(); if (x._starBusy) return; starMany([x], { single: true }); };
    // 10-11「归类…」：只在索引视图里、悬停才出现（CSS 管显隐）——移到… / 也放进… / 从这里拿掉
    const rc = card.createEl('button', { cls: 'lbc-reclass', text: '归类…' }); rc.type = 'button';
    rc.onclick = e => {
      e?.preventDefault?.(); e?.stopPropagation?.();
      const list = selectMode && selected.size && selected.has(cur().id) ? items.filter(x => selected.has(x.id)) : [cur()];
      const r = rc.getBoundingClientRect();
      popMenu(reclassItems(list), e, rc, { x: r.left, y: r.bottom + 4 });
    };
  } else {
    // 手机：只给已收藏的篇显示一个不可点的 ★（C12）
    const st = card.createEl('span', { cls: 'lbc-star is-on is-static' }); putSvg(st, STAR_SVG);
  }
  const body = card.createEl('div', { cls: 'lbc-body' });
  const ct = body.createEl('div', { cls: 'lbc-ctitle', text: cardTitle(it) });
  if (ct.textContent !== (it.title || '未命名')) { ct.title = it.title; ct.classList.add('is-series'); }   // 露后半截的：悬停看全名
  if (low) body.createEl('div', { cls: 'lbc-lowhit', text: low });
  const ftags = body.createEl('div', { cls: 'lbc-ftags' }); ftags.hidden = true;   // 10-11 索引视图里：这篇在选中这一类的细分标签
  const tops = cardTopics(it);
  if (tops.length) { const tp = body.createEl('div', { cls: 'lbc-ctopics' }); for (const t of tops) tp.createEl('span', { text: '★ ' + t }); }
  const meta = body.createEl('div', { cls: 'lbc-cmeta' });
  const who = it.author || it.source || '收藏';
  const au = meta.createEl('div', { cls: 'lbc-au' });
  const av = au.createEl('span', { cls: 'lbc-av', text: [...String(who)][0] || '·' }); av.style.setProperty('--lbc-av', TILE_COLORS[hashStr(who) % TILE_COLORS.length]);
  au.createEl('span', { cls: 'lbc-au-name', text: who });
  meta.createEl('span', { cls: 'lbc-likes', text: fmtLikes(it.likes) });
  if (!mobile) {
    // C3 拖文件：进入有文件的拖拽 → 虚线框「松手挂到这篇」；松手后 busy 到 attachFile 返回
    let depth = 0;
    const hasFiles = e => { const t = e?.dataTransfer?.types; return !!t && (Array.from(t).includes('Files')); };
    card.ondragenter = e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; card.classList.add('is-droptarget'); };
    card.ondragover = e => { if (!hasFiles(e)) return; e.preventDefault(); card.classList.add('is-droptarget'); };
    card.ondragleave = () => { depth = Math.max(0, depth - 1); if (!depth) card.classList.remove('is-droptarget'); };
    card.ondrop = async e => {
      e.preventDefault(); e.stopPropagation(); depth = 0; card.classList.remove('is-droptarget');
      const x = cur(); const f = e.dataTransfer?.files?.[0]; if (!f) return;
      let fp = f.path; try { if (!fp) fp = require('electron').webUtils?.getPathForFile(f); } catch {}
      if (!fp) { attachmentPanel([x]); return; }
      const p = await want('attachFile'); if (!p) return;
      card.dataset.busy = '正在挂…'; card.classList.add('is-busy');
      try {
        const result = await p.attachFile(x.id, fp);
        card.classList.remove('is-busy'); delete card.dataset.busy;
        LB.say(result?.warning || `附件已挂到《${x.title || x.id}》并加入搜索`, { kind: result?.warning ? 'warn' : 'ok' });
        await refresh();
      } catch (err) { card.classList.remove('is-busy'); delete card.dataset.busy; LB.say('没挂上：' + (err?.message || err), { kind: 'error' }); }
    };
  }
  // 多选模式：点击=勾选/取消；平时=打开笔记（同一窗格，§5.4；按住 Ctrl 照 Obsidian 习惯开新标签；中键也开新标签，C17）
  const open = (e, forceNew = false) => openItem(cur(), e, forceNew);
  card.onclick = e => open(e);
  card.onkeydown = e => { if (e.target === card && e.key === 'Enter') { e.preventDefault(); open(e); } };
  card.onauxclick = e => { if (e.button === 1) { e.preventDefault(); open(e, true); } };
  card.onmousedown = e => { if (e.button === 1) e.preventDefault(); };   // 不出自动滚动图标
  if (!mobile) card.oncontextmenu = e => { e.preventDefault(); openCardMenu(e, card, cur()); };
  paintCardState(card, it);
  return card;
}

// 多选模式：点击=勾选/取消；平时=打开笔记（同一窗格，§5.4；按住 Ctrl 照 Obsidian 习惯开新标签；中键也开新标签，C17）
function openItem(x, e, forceNew = false) {
  if (!x) return;
  if (selectMode && !forceNew) { toggleSelect(x.id); return; }
  if (!x.note) return;
  const newTab = forceNew || !!(e && (e.ctrlKey || e.metaKey));
  saveState(); if (!newTab) leaving = true;
  app.workspace.openLinkText(lbPath(x.note), '', newTab);
}

// ── 1021「列表」视图：简单表格（标题、分类、作者、导入时间、♡），和瀑布流用同一份筛选 / 搜索结果；点行打开笔记，右键同卡片菜单 ──
let listKey = null;
function renderList(r) {
  if (listKey === r.key && listBox.firstChild) { paintListSel(); return; }
  listKey = r.key;
  perfCounts.list = (perfCounts.list || 0) + 1;
  listBox.empty();
  const table = listBox.createEl('table', { cls: 'lbc-ltable' });
  const hr = table.createEl('thead').createEl('tr');
  for (const [cls, t] of [['lbc-lt-title', '标题'], ['lbc-lt-cat', '分类'], ['lbc-lt-au', '作者'], ['lbc-lt-date', '导入时间'], ['lbc-lt-likes', '♡']]) hr.createEl('th', { cls, text: t });
  const tb = table.createEl('tbody');
  const row = ({ it }) => {
    const tr = tb.createEl('tr', { cls: 'lbc-lrow' + (selected.has(it.id) ? ' is-selected' : '') });
    tr.tabIndex = 0; tr._lbItem = it; tr.dataset.id = it.id;
    const td = tr.createEl('td', { cls: 'lbc-lt-title' });
    if (it.starred) td.createEl('span', { cls: 'lbc-lt-star', text: '★' });
    td.append(cardTitle(it));
    tr.createEl('td', { cls: 'lbc-lt-cat', text: catNameOf(it) });
    tr.createEl('td', { cls: 'lbc-lt-au', text: it.author || it.source || '收藏' });
    tr.createEl('td', { cls: 'lbc-lt-date', text: shortDay(it.date || it.ts) });
    tr.createEl('td', { cls: 'lbc-lt-likes', text: it.likes == null ? '' : fmtLikes(it.likes).replace(/^♡ /, '') });
    tr.onclick = e => openItem(tr._lbItem, e);
    tr.onkeydown = e => { if (e.target === tr && e.key === 'Enter') { e.preventDefault(); openItem(tr._lbItem, e); } };
    tr.onauxclick = e => { if (e.button === 1) { e.preventDefault(); openItem(tr._lbItem, e, true); } };
    tr.onmousedown = e => { if (e.button === 1) e.preventDefault(); };
    if (!mobile) tr.oncontextmenu = e => { e.preventDefault(); openCardMenu(e, tr, tr._lbItem, { row: true }); };
  };
  for (const rw of r.exact) row(rw);
  if (r.possible.length) {
    const sep = tb.createEl('tr', { cls: 'lbc-lt-sep' });
    sep.createEl('td', { text: `可能相关 · ${r.possible.length} 篇（拼音相近、错一个字、漏字，不是原词命中）`, attr: { colspan: '5' } });
    for (const rw of r.possible) row(rw);
  }
}
function paintListSel() {
  if (listBox.hidden) return;
  for (const tr of listBox.querySelectorAll('tr.lbc-lrow')) tr.classList.toggle('is-selected', selected.has(tr.dataset.id));
}

// ── 多选（C10：只改这张卡的 class；进 / 出多选时补滚动，下面的卡不动） ──
function paintSelectMode() {
  paintListSel();
  wrap.classList.toggle('is-selecting', selectMode && selected.size > 0);
  setSelbarVisible(selectMode && selected.size > 0);
  paintSelbar();
}
function toggleSelect(id, { force = false } = {}) {
  if (mobile) return;
  if (force) { if (!selected.has(id)) { if (!selectMode) selected.clear(); selected.add(id); } }
  else if (selectMode && selected.has(id)) selected.delete(id);
  else { if (!selectMode) selected.clear(); selected.add(id); }
  selectMode = selected.size > 0;
  paintCard(id);
  paintSelectMode();
  saveState();
}
function clearSelection() {
  const ids = [...selected];
  selected.clear(); selectMode = false;
  for (const id of ids) paintCard(id);
  paintSelectMode();
  saveState();
}

// ── 排版（C9：按行瀑布流；只在结果集或列数变化时重摆） ──
let laidKey = null, laidN = 0;
// 1017 首开即出：一次要新建很多张卡（真库首开 884 张：建卡 + 解析 + 排版约 200ms，期间一帧不出）时，
// 只同步建「看得见的这一屏多一点」（滚动位置 + 1.25 屏；返回目录要恢复的位置也算在内），下面的卡等第一帧画出来以后分片补上
// （每片 ≤8ms，补到原来的位置：瀑布流分配和占位高照旧按全部结果算，补完和一次建完一模一样）。
// 要新建的卡不多（< FILL_MIN，含平常的搜索 / 筛选 / 数据刷新——卡片按 id 复用）就照旧一次建完。
const FILL_MIN = 200, FILL_SLICE_MS = 8;
let fillJob = null, restoreTarget = 0;
function cancelFill() {
  if (!fillJob) return;
  fillJob.stop = true; fillJob = null;
  try { grid.removeAttribute('data-lbc-filling'); } catch {}
}
cleanups.push(cancelFill);
function fillBudget() {
  const sc = LB.scroller();
  const vh = Number(sc?.clientHeight) || (typeof innerHeight === 'number' ? innerHeight : 0) || 900;
  return Math.max(Number(sc?.scrollTop) || 0, restoreTarget || 0) + vh * 1.25;
}
// 估算每一行（卡）的顶边：和 layoutInto 同一份分配 + 估算高（不读真实高度）
function planTops(plan, heights, g, offset = 0) {
  const tops = new Array(heights.length).fill(0);
  for (const idxs of plan) { let y = offset; for (const i of idxs) { tops[i] = y; y += (Number(heights[i]) || 0) + g; } }
  return tops;
}
function layoutInto(box, rows, n, { limit = rows.length, deferred = null } = {}) {
  // 10-11：不再 box.empty() 再整批挂回（她：按 AI 建议刷新目录会闪一下）——列复用、卡片只在位置不对时挪，多余的摘掉
  const W = gridWidth(), g = gapPx();
  const colW = n > 1 && W > 0 ? (W - g * (n - 1)) / n : (W || 230);
  box.style.setProperty('--lbc-gap', g + 'px');
  const heights = rows.map(r => lbcCardHeight(r.it, colW, { low: r.low }));
  const { cols: plan } = lbcAssign(heights, n);
  for (const el of [...box.children]) if (!el.classList.contains('lbc-col')) el.remove();
  const cols = [...box.children];
  while (cols.length < plan.length) cols.push(box.createEl('div', { cls: 'lbc-col' }));
  while (cols.length > plan.length) cols.pop().remove();
  // 1015 首开卡：.lbc-card 是 content-visibility:auto（屏外的卡不排版），占位高 = 上面的估算高（画过一次后 auto 记住真高）
  const cardAt = i => { const c = getCard(rows[i]); const h = Math.round(heights[i]); if (h > 0 && c.__lbH !== h) { c.__lbH = h; c.style.containIntrinsicSize = `auto ${h}px`; } return c; };
  plan.forEach((idxs, ci) => {
    const col = cols[ci];
    // limit 之后的卡（分配上一定排在每列的尾巴）留给 deferred 分片补
    const want = idxs.filter(i => i < limit).map(cardAt);
    want.forEach((card, k) => { if (col.children[k] !== card) col.insertBefore(card, col.children[k] || null); });
    while (col.children.length > want.length) col.lastElementChild.remove();
  });
  if (limit < rows.length && deferred) {
    const colOf = new Array(rows.length);
    plan.forEach((idxs, ci) => { for (const i of idxs) colOf[i] = ci; });
    for (let i = limit; i < rows.length; i++) deferred.push(() => { const c = cardAt(i); if (c.parentNode !== cols[colOf[i]] || c.nextSibling) cols[colOf[i]].appendChild(c); });
  }
}
// 首开 / 大批新卡：先算各块能同步建几张（按估算顶边 ≤ 预算），要分片的新卡够多才分片
function fillLimits(blocks, n) {
  const W = gridWidth(), g = gapPx();
  const colW = n > 1 && W > 0 ? (W - g * (n - 1)) / n : (W || 230);
  const budget = fillBudget();
  let offset = 0, fresh = 0;
  const limits = blocks.map(rows => {
    const heights = rows.map(r => lbcCardHeight(r.it, colW, { low: r.low }));
    const { cols: plan, heights: sums } = lbcAssign(heights, n);
    const tops = planTops(plan, heights, g, offset);
    offset += Math.max(0, ...sums.map((h, ci) => h + g * plan[ci].length)) + 60;
    let k = rows.length;
    for (let i = 0; i < rows.length; i++) if (tops[i] > budget) { k = i; break; }
    for (let i = k; i < rows.length; i++) if (!cardCache.has(rows[i].it.id)) fresh++;
    return k;
  });
  return fresh >= FILL_MIN ? limits : blocks.map(rows => rows.length);
}
function runFill(tasks) {
  const job = fillJob = { stop: false, i: 0 };
  grid.setAttribute('data-lbc-filling', String(tasks.length));
  const clock = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
  const step = () => {
    if (job.stop || fillJob !== job) return;
    const t0 = clock();
    while (job.i < tasks.length && clock() - t0 < FILL_SLICE_MS) { try { tasks[job.i](); } catch {} job.i++; }
    if (job.i < tasks.length) { setTimeout(step, 0); return; }
    fillJob = null;
    try { grid.removeAttribute('data-lbc-filling'); } catch {}
    if (cardTagsShown || (indexView && idx)) paintCardFacets();
    LB.mark('cards-filled');
  };
  // 第一帧（顶栏 + 头几屏卡片）先画出来，再开始补
  const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : (f => setTimeout(f, 16));
  raf(() => setTimeout(step, 0));
}
function layoutGrid() {
  const r = rankRows();
  const n = colCount();
  perfCounts.layout++;
  laidKey = r.key; laidN = n;
  // 重摆会把卡片摘下再挂回（Chromium 摘有焦点的元素会失焦）：记下网格里有焦点的元素和选区，摆完还回去
  const ae = document.activeElement;
  const keep = ae && ae !== document.body && grid.contains(ae) ? { el: ae, s: ae.selectionStart, e: ae.selectionEnd } : null;
  try { layoutBody(r, n); }
  finally {
    if (keep && keep.el.isConnected && document.activeElement !== keep.el) {
      try { keep.el.focus({ preventScroll: true }); } catch { try { keep.el.focus(); } catch {} }
      if (keep.s != null) { try { keep.el.setSelectionRange(keep.s, keep.e); } catch {} }
    }
  }
}
function layoutBody(r, n) {
  cancelFill();
  const shown = r.exact.length + r.possible.length;
  const simpleEmpty = simplePage && !starredPage && !committed && !activeCat && !activeTopic && !activeAlbum && !todayOnly && !todoOnly;
  if (simpleEmpty || !shown) {
    grid.empty();
    if (committed && !committed.startsWith('#') && !mobile && shown) {
      const tip = grid.createEl('div', { cls: 'lbc-possible-note lbc-ask-tip', text: `按关键词筛选。想把同义词、相关内容也找出来 → 去问收藏搜「${committed}」` });
      tip.onclick = () => askInChat(committed);
    }
    if (simpleEmpty) { grid.createEl('div', { cls: 'lbc-empty', text: '输入关键词搜索收藏；想让 AI 分析，点上面的「问收藏」。' }); return; }
    renderEmpty(); return;
  }
  // 10-11：有卡片的时候不清空网格——几块（搜索提示 / 精确命中 / 可能相关）按需复用，卡片按差异挪（不闪白、焦点和图片都在）
  const reuse = test => [...grid.children].find(test) || null;
  const has = (el, c) => el.classList.contains(c);
  const want = [];
  // 第 10 批：目录搜索是关键词精确筛选；想连同义词 / 语义一起找，一键带着这个词去问收藏
  if (committed && !committed.startsWith('#') && !mobile) {
    const tip = reuse(el => has(el, 'lbc-ask-tip')) || document.createElement('div');
    tip.className = 'lbc-possible-note lbc-ask-tip';
    tip.textContent = `按关键词筛选。想把同义词、相关内容也找出来 → 去问收藏搜「${committed}」`;
    tip.onclick = () => askInChat(committed);
    want.push(tip);
  }
  const exactBox = reuse(el => has(el, 'lbc-grid-inner') && !has(el, 'lbc-grid-possible')) || Object.assign(document.createElement('div'), { className: 'lbc-grid-inner lbc-masonry' });
  want.push(exactBox);
  if (r.possible.length) {
    let headEl = reuse(el => has(el, 'lbc-possible-head'));
    if (!headEl) {
      headEl = document.createElement('div'); headEl.className = 'lbc-possible-head';
      headEl.createEl('span', { cls: 'lbc-possible-title' });
      headEl.createEl('span', { cls: 'lbc-possible-note', text: '拼音相近、错一个字、漏字或图片里的零散字母，不是原词命中' });
    }
    headEl.querySelector('.lbc-possible-title').textContent = `可能相关 · ${r.possible.length} 篇`;
    const possibleBox = reuse(el => has(el, 'lbc-grid-possible')) || Object.assign(document.createElement('div'), { className: 'lbc-grid-inner lbc-grid-possible lbc-masonry' });
    want.push(headEl, possibleBox);
  }
  for (const el of [...grid.children]) if (!want.includes(el)) el.remove();
  want.forEach((el, k) => { if (grid.children[k] !== el) grid.insertBefore(el, grid.children[k] || null); });
  const [limE, limP] = fillLimits([r.exact, r.possible], n);
  const deferred = [];
  layoutInto(exactBox, r.exact, n, { limit: limE, deferred });
  if (r.possible.length) layoutInto(want[want.length - 1], r.possible, n, { limit: limP, deferred });
  if (deferred.length) runFill(deferred);
}
async function askInChat(q) {
  const p = provider(); if (p) p.pendingArchiveQuestion = q;
  await LB.openPage('chat');
  app.workspace.trigger?.('link-brain:ask-pending');
}
// C8：空状态分三种
function renderEmpty() {
  const box = grid.createEl('div', { cls: 'lbc-empty' });
  const text = t => box.createEl('p', { cls: 'lbc-empty-text', text: t });
  const actions = () => box.querySelector('.lbc-empty-actions') || box.createEl('div', { cls: 'lbc-empty-actions' });
  const btn = (label, fn) => { const b = actions().createEl('button', { text: label }); b.type = 'button'; b.onclick = fn; return b; };
  if (!items.length) {
    if (mobile) { text('还没有收藏。导入和同步要在电脑上做。'); return; }
    text('还没有收藏：点标题旁的「+」导入网址，或登录后同步收藏');
    btn('导入网址', async () => (await want('openImportModal'))?.openImportModal());
    btn('立即同步收藏', async () => (await want('syncNow'))?.syncNow());
    return;
  }
  if ((starOnly || starredPage) && !items.some(x => x.starred)) { text('还没有收藏的：鼠标停在卡片上，点右上角的 ☆'); return; }
  const label = filterLabel();
  if (label) {
    text(committed ? `「${label}」里没有「${committed}」` : `「${label}」里没有内容`);
    btn('清除筛选', () => { clearFilters(); renderCatBar(); render(); scrollToResults(); });
    if (committed && !committed.startsWith('#') && !mobile) btn(`去问收藏搜「${committed}」`, () => askInChat(committed));
    return;
  }
  text(`没找到「${committed}」，试试更短的关键词`);
  if (!mobile && provider()?.openLibraryPage && !committed.startsWith('#')) {
    const tip = box.createEl('div', { cls: 'lbc-possible-note lbc-ask-tip', text: `想把同义词、相关内容也找出来 → 去问收藏搜「${committed}」` });
    tip.onclick = () => askInChat(committed);
  }
}
function render() {
  // 10-11「索引」视图开着：左边树、右边照样是网格（筛到选中的节点），上面一行状态 / 建议新增
  const showIndex = indexView && !!idx;
  wrap.classList.toggle('is-indexview', showIndex);
  ibar.hidden = !showIndex; ipanel.hidden = !showIndex;
  split.classList.toggle('is-on', showIndex);
  split.classList.toggle('is-narrow', showIndex && panelNarrow());
  if (activeFacets.length && (!showIndex || facetNode !== activeCat)) activeFacets = [];
  facetNode = activeCat;
  if (showIndex) { renderIndexBar(); renderIndexPanel(); renderIndexHead(); paintIndexSticky(); }
  else ihead.hidden = true;
  renderIndexFacets();
  const r = rankRows();
  // 1021「列表」：有结果时网格藏起来、画表格；没结果照旧在网格里出空状态（清除筛选 / 去问收藏）
  const listMode = viewMode === 'list' && !showIndex && !simplePage && (r.exact.length + r.possible.length) > 0;
  const wikiMode = viewMode === 'wiki' && !showIndex && !simplePage;
  const recentMode = viewMode === 'recent' && !showIndex && !simplePage;
  wrap.classList.toggle('is-listview', listMode);
  grid.hidden = listMode || wikiMode || recentMode; listBox.hidden = !listMode; wikiBox.hidden = !wikiMode; recentBox.hidden = !recentMode;
  if (wikiMode) { cancelFill(); renderWiki(); }
  else if (recentMode) { cancelFill(); renderRecent(); }
  else if (listMode) { cancelFill(); renderList(r); }
  else {
    if (listBox.firstChild) { listBox.empty(); listKey = null; }
    const n = colCount();
    if (r.key !== laidKey || n !== laidN) layoutGrid();
  }
  paintCardFacets();
  paintSub();
  paintSelectMode();
  saveState();
}
function relayoutIfNeeded() { if (!grid.hidden && colCount() !== laidN) withAnchor(() => layoutGrid()); }
// 数据刷新 / 删除 / 列数变化时：记下顶栏下第一张卡的位置，重摆后修正 scrollTop，视野不跳（C9）
function withAnchor(fn) {
  const sc = LB.scroller();
  if (!sc || !(sc.scrollTop > 0)) return fn();
  const barBottom = top.getBoundingClientRect().bottom;
  let anchor = null, before = 0;
  for (const card of grid.querySelectorAll('.lbc-card')) { const r = card.getBoundingClientRect(); if (r.bottom > barBottom) { anchor = card._lbItem?.id; before = r.top; break; } }
  const out = fn();
  if (anchor) { const el = cardCache.get(anchor)?.el; if (el && el.isConnected) { const d = el.getBoundingClientRect().top - before; if (d) sc.scrollTop += d; } }
  return out;
}
// C6：换搜索词 / 切大类后回到结果开头（只有已经滚过结果开头时才动）
function scrollToResults() {
  const sc = LB.scroller(); if (!sc) return;
  const target = (grid.hidden ? listBox : grid).getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - stuckHeight() - 8;
  if (sc.scrollTop > target + 4) sc.scrollTop = Math.max(0, target);
}
function scrollToPossible() {
  const sc = LB.scroller(); const h = grid.querySelector('.lbc-possible-head'); if (!sc || !h) return;
  const target = Math.max(0, h.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - stuckHeight() - 8);
  try { sc.scrollTo({ top: target, behavior: 'smooth' }); } catch { sc.scrollTop = target; }
  if (typeof sc.scrollTo !== 'function') sc.scrollTop = target;
  h.tabIndex = -1; try { h.focus({ preventScroll: true }); } catch {}
}

// ── 搜索（C5：边打边搜；防抖按渲染耗时自适应 40–120ms；输入法组字中不搜；选完字 / 回车立刻搜） ──
let typingTimer = null, composing = false, renderEma = 30;
const now = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
// 防抖 + 渲染 + 下一帧 ≤150ms（RELEASE-BAR §2）：外壳实测按 140−EMA 算正好压线（p95 151ms），留一帧的余量取 120−EMA、上限 100
const delay = () => Math.max(40, Math.min(100, 120 - renderEma));
// 目录只做搜索（0926 Owner）：整句（语音打进来的）搜不到时退成关键词再搜；规则在 catalog-search.js resolveQuery
function commitSearch() {
  clearTimeout(typingTimer); typingTimer = null;
  const raw = search.value.trim();
  // 10-11：「索引」视图里网格就在右边，搜索照样在选中的节点里搜（不再跳出索引视图）
  const before = committed;
  const t0 = now();
  lastRaw = raw;
  committed = resolveQuery(search.value, items, data.pinyin_chars, data.aliases || []);
  render();
  renderEma = 0.3 * (now() - t0) + 0.7 * renderEma;
  if (committed !== before) scrollToResults();
}
function liveCommit() { if (composing) return; if (search.value.trim() === lastRaw) return; commitSearch(); }
search.addEventListener('input', e => {
  saveState();
  if (composing || e?.isComposing) return;
  clearTimeout(typingTimer);
  if (!search.value.trim()) { commitSearch(); return; }
  typingTimer = setTimeout(liveCommit, delay());
});
search.addEventListener('compositionstart', () => { composing = true; clearTimeout(typingTimer); });
search.addEventListener('compositionend', () => { composing = false; liveCommit(); });
search.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
  e.preventDefault(); commitSearch();
});
cleanups.push(() => clearTimeout(typingTimer));
search.value = typeof saved.input === 'string' ? saved.input : committed;
paintSearchX();
LB.trackFocus(search, 'search');
// 首次搜索预热（C5）：首屏画完后空闲时分片算 searchFields；refresh 换了 items 就重启；卸载时停
let warm = null;
function startWarm() { try { warm?.cancel(); } catch {} warm = warmSearch(items); }
cleanups.push(() => { try { warm?.cancel(); } catch {} });

// ── N9：带 #标签 打开目录（notes 线写 plugin.pendingCatalogQuery）——清掉旧筛选，按标签筛 ──
function takePendingQuery() {
  const p = provider();
  const q = typeof p?.pendingCatalogQuery === 'string' ? p.pendingCatalogQuery.trim() : '';
  if (!q) return false;
  p.pendingCatalogQuery = '';
  clearFilters();
  search.value = q; paintSearchX();
  commitSearch();
  renderCatBar();
  scrollToResults();
  return true;
}

// ── 新鲜度（F4）：磁盘上的 catalog-data 比页面里的新——看得见就刷新，看不见记 stale，露出来再刷 ──
let checking = false;
async function checkFresh() {
  if (checking) return;
  const view = root.__lbView; if (!view || view.el !== wrap && view.el !== mount) return;
  checking = true;
  try {
    const v = await LB.data.version();
    if (!v || v === view.version) { stale = false; return; }
    const visible = wrap.isConnected && (typeof wrap.isShown === 'function' ? wrap.isShown() : (typeof wrap.getClientRects === 'function' ? wrap.getClientRects().length > 0 : true));
    if (!visible) { stale = true; return; }
    try { await refresh({ strict: true }); } catch (e) { view.lastError = e; }
  } finally { checking = false; paintSub(); }
}
if (app.workspace?.on && dv.component?.registerEvent) {
  lbEvent(app.workspace, app.workspace.on('active-leaf-change', () => { if (stale && LB.activeLeafHas(wrap)) checkFresh(); }));
  // 星标以 catalog-data 为准 + link-brain:star 事件（§5.6）：只换这张卡的 ★，不重排（C2）
  lbEvent(app.workspace, app.workspace.on('link-brain:star', (id, on) => { const it = items.find(x => x.id === id); if (it && !it._starBusy && !!it.starred !== !!on) { it.starred = !!on; paintCard(id); paintSelbar(); } }));
  // 10-03：「…→改标题 / 每行几列」改完就地换（不重建卡片）
  lbEvent(app.workspace, app.workspace.on('link-brain:catalog-prefs', () => { setTitle(); const c = savedCols(); if (c !== cols) { cols = c; applyCols(); relayoutIfNeeded(); } reloadLayout(); }));
  lbEvent(app.workspace, app.workspace.on('link-brain:catalog-query', () => { if (takePendingQuery()) saveState(); }));
}
{ const winTarget = typeof window !== 'undefined' && window && typeof window.addEventListener === 'function' ? window : null;
  if (winTarget) LB.listen('focus-fresh', winTarget, 'focus', () => checkFresh()); }

// ── 1021 第 3 段 · 左侧边栏（DESIGN-SPEC §4）：RECENT 最近导入 · SYNC 同步与用量 · OVERVIEW 概览 ──
// 每块点小标题行折叠成一行摘要、点摘要展开（sideFold 存 LB.state）。数据：RECENT / OVERVIEW 从 items 算；SYNC 读 refreshProblems 拿到的
// syncState（sync-status.json / problems-summary.json 较新的那份）+ 插件 getSyncSchedule()（60 秒缓存；没插件就「—」加一句说明）。
// 同步状态变了（文件监听 → refreshProblems → paintProblems）只重画 SYNC 那一块；数据变了（refresh）只重画 RECENT / OVERVIEW。不碰收藏墙、不动输入框。
const GEAR_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
const pad2 = n => String(n).padStart(2, '0');
const hmOf = t => { const d = new Date(t); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
const mdOf = t => { const d = new Date(t); return `${d.getMonth() + 1}/${d.getDate()}`; };
const sameDay = (a, b) => ymd(new Date(a)) === ymd(new Date(b));
// 那一篇是哪天进的库：date（和「今日新增」同一口径）→ 没有就用 ts 的本地日期
function dayOf(it) { if (typeof it.date === 'string' && /^\d{4}-\d{2}-\d{2}/.test(it.date)) return it.date.slice(0, 10); const t = importedAt(it); return t ? ymd(new Date(t)) : ''; }
// 「还有 5 小时 30 分」
function leftText(ms) {
  if (!(ms > 0)) return '马上开始';
  const m = Math.max(1, Math.round(ms / 60000)), h = Math.floor(m / 60), r = m % 60;
  return h ? `还有 ${h} 小时${r ? ` ${r} 分` : ''}` : `还有 ${r} 分`;
}
function sideModule(key, en, zh, { gear = null } = {}) {
  const sec = side.createEl('section', { cls: 'lbc-mod lbc-mod-' + key + ' lbc-m lbc-m-' + key }); sec.dataset.mod = key; sec.dataset.m = key;
  // 1027 编排操作条（⠿ / 名字 / 调整 / ×）由「编排」一节第一次进编排时统一加（ensureBars），平时不建
  const lab = sec.createEl('div', { cls: 'lbc-lab' }); lab.setAttribute('role', 'button'); lab.tabIndex = 0;
  lab.createEl('span', { cls: 'lbc-lab-en', text: en }); lab.createEl('small', { text: zh });
  lab.createEl('span', { cls: 'lbc-lab-line' });
  if (gear) {
    const g = lab.createEl('button', { cls: 'lbc-gear' }); g.type = 'button'; g.innerHTML = GEAR_SVG;
    g.createEl('span', { cls: 'lb-visually-hidden', text: '同步设置' });
    g.onclick = e => { e?.stopPropagation?.(); gear(g); };
  }
  lab.createEl('span', { cls: 'lbc-chev' });
  const sum = sec.createEl('div', { cls: 'lbc-fold-sum' }); sum.setAttribute('role', 'button'); sum.tabIndex = 0;
  const body = sec.createEl('div', { cls: 'lbc-mod-body' });
  const toggle = () => { sideFold[key] = !sideFold[key]; paintFold(key); saveState(); if (!sideFold[key]) paintMod(key); sideFadeSoon(); };
  const onKey = e => { if (e.target !== e.currentTarget) return; if (e.key === 'Enter' || e.key === ' ') { e.preventDefault?.(); toggle(); } };
  lab.onclick = toggle; sum.onclick = toggle; lab.onkeydown = onKey; sum.onkeydown = onKey;
  return { key, sec, lab, sum, body, sig: null };
}
function paintFold(key) {
  const m = mods[key]; if (!m) return; const f = !!sideFold[key];
  m.sec.classList.toggle('is-folded', f); m.body.hidden = f; m.sum.hidden = !f;
  m.lab.setAttribute('aria-expanded', String(!f));
}
// 摘要：<i> 里的数字 / 时间用 Cormorant 斜体
function setSum(m, parts) {
  const sig = JSON.stringify(parts); if (m.sumSig === sig) return; m.sumSig = sig;
  m.sum.empty();
  for (const p of parts) { if (Array.isArray(p)) m.sum.createEl('i', { text: p[0] }); else m.sum.append(p); }
}

// 边栏里点一篇：多选模式下也是打开（不是勾选）；同一窗格，Ctrl / 中键开新标签（§5.4）
function openFromSide(it, e, forceNew = false) {
  if (!it?.note) return;
  const newTab = forceNew || !!(e && (e.ctrlKey || e.metaKey));
  saveState(); if (!newTab) leaving = true;
  app.workspace.openLinkText(lbPath(it.note), '', newTab);
}
// RECENT：按入库时间 ts 新→旧；今天显示 HH:MM，否则 M/D；点行打开笔记（同一窗格，Ctrl 开新标签）
// 1027b 她：不要「查看全部」——折起来是一行「最新 …」，点开往下就是列表，框高 = 「调整」里的条数（2 / 4 / 6 / 8）或拖出来的高度，
// 在框里往下滚接着出更早的（每次多画 RECENT_STEP 条，不一次铺 1000+ 行）
const RECENT_STEP = 40;
let recentShown = RECENT_STEP;
function paintRecent() {
  const m = mods.recent; const now = Date.now();
  const all = items.filter(it => importedAt(it) > 0).sort((a, b) => importedAt(b) - importedAt(a));
  const list = all.slice(0, Math.max(modOpt('recent').count, recentShown));
  const when = it => { const t = importedAt(it); return sameDay(t, now) ? hmOf(t) : mdOf(t); };
  setSum(m, list.length ? ['最新 ', [when(list[0])], ' · ' + String(list[0].title || '（无标题）')] : ['还没有收藏']);
  if (sideFold.recent) return;
  const sig = ymd(new Date(now)) + '|' + modOpt('recent').count + '|' + list.map(it => [it.id, importedAt(it), it.title, catNameOf(it)].join('\u0001')).join('\u0002');
  if (m.sig === sig) return; m.sig = sig;
  const keep = m.body.querySelector?.('.lbc-rec')?.scrollTop || 0;
  m.body.empty();
  if (!list.length) { m.body.createEl('div', { cls: 'lbc-rec-empty', text: '还没有收藏' }); return; }
  const ul = m.body.createEl('ul', { cls: 'lbc-rec' });
  ul.style.setProperty('--lbc-rec-rows', String(modOpt('recent').count));
  ul.addEventListener('scroll', () => {
    if (recentShown >= all.length) return;
    if (ul.scrollHeight - ul.scrollTop - ul.clientHeight < 120) { recentShown += RECENT_STEP; paintRecent(); }
  }, { passive: true });
  for (const it of list) {
    const li = ul.createEl('li'); li.tabIndex = 0; li.setAttribute('role', 'button'); li.dataset.id = it.id;
    li.createEl('time', { text: when(it) });
    li.createEl('span', { cls: 'lbc-rec-t', text: String(it.title || '（无标题）') });
    li.createEl('span', { cls: 'lbc-rec-c', text: catNameOf(it) });
    li.onclick = e => openFromSide(it, e);
    li.onauxclick = e => { if (e.button === 1) { e.preventDefault?.(); openFromSide(it, e, true); } };
    li.onkeydown = e => { if (e.key === 'Enter') openFromSide(it, e); };
  }
  if (keep) ul.scrollTop = keep;
}

// SYNC：上次 / 下次（大号 Cormorant）+ 频率 + 从上次到下次的时间进度；同步中 = 真实进度；失败 / 阻塞 = 原因（点开问题列表）
let schedule = null, scheduleErr = '', scheduleAt = 0, scheduleBusy = false;
async function loadSchedule({ force = false } = {}) {
  const p = provider();
  if (!p || typeof p.getSyncSchedule !== 'function' || scheduleBusy) return;
  if (!force && scheduleAt && Date.now() - scheduleAt < 60000) return;
  scheduleBusy = true;
  try { schedule = await p.getSyncSchedule(); scheduleErr = schedule?.error ? String(schedule.error) : ''; }
  catch (e) { scheduleErr = e?.message || String(e); }
  finally { scheduleBusy = false; scheduleAt = Date.now(); }
  paintSync();
}
function syncRunText(st) {
  const d = numOf(st, 'done'), t = numOf(st, 'total');
  if (d != null && t) return { text: `同步中 ${d}/${t}`, pct: Math.min(1, d / t) };
  const lv = st.live && typeof st.live === 'object' ? st.live : {};
  const a = numOf(lv, 'archived'), ft = numOf(lv, 'favorites_total');
  if (a != null && ft) return { text: `同步中 ${a}/${ft}`, pct: Math.min(1, a / ft) };
  const m = String(st.progress || '').match(/(\d+)\s*\/\s*(\d+)/);
  if (m && Number(m[2])) return { text: `同步中 ${m[1]}/${m[2]}`, pct: Math.min(1, Number(m[1]) / Number(m[2])) };
  return { text: '同步中', pct: null };
}
function paintSync() {
  const m = mods.sync; if (!m) return;
  const now = Date.now(), st = syncState || {}, p = provider();
  const last = Math.max(tsOf(st.last_success), tsOf(probSummary?.last_success), tsOf(probSummary?.sync?.last_success));
  const next = schedule && schedule.enabled !== false ? tsOf(schedule.next_run) : 0;
  if (next && next < now - 60000 && Date.now() - scheduleAt > 60000) loadSchedule({ force: true });   // 下次那一刻过了：再问一次计划任务
  const running = st.state === 'running', stopped = st.state === 'blocked' || st.state === 'failed';
  const run = running ? syncRunText(st) : null;
  const nToday = (() => { const d = ymd(new Date(now)); let n = 0; for (const it of items) if (dayOf(it) === d) n++; return n; })();
  const bigWhen = t => t ? [sameDay(t, now) ? '今天' : mdOf(t), hmOf(t)] : null;
  const why = stopped ? [st.label || regEntry(st.code)?.label || (st.state === 'blocked' ? '同步停下了，要你处理' : '上次同步没成功'), st.detail || st.message || ''].filter(Boolean) : [];
  // 摘要：下次 今天 21:04（1027：费用拆成自己的「Token 费用」模块）
  const nx = bigWhen(next);
  setSum(m, running ? [run.text] : stopped ? ['同步停了'] : nx ? ['下次 ', [nx.join(' ')]] : ['下次 —']);
  if (sideFold.sync) return;
  const freq = schedule ? String(schedule.summary || '').replace(/\s*·\s*下次 .*$/, '') : '';
  const note = !p ? (mobile ? LB.MOBILE_ONLY_TEXT : '插件没开：下次同步、定时设置看不到（收藏照常可以浏览）')
    : scheduleErr ? '读不到同步计划：' + scheduleErr : '';
  const sig = JSON.stringify([syncEditOpen ? 0 : Math.floor(now / 30000), last, next, freq, note, running && run, why, nToday, !!schedule, syncEditOpen ? 0 : scheduleBusy, syncEditOpen]);
  if (m.sig === sig) return; m.sig = sig;
  const b = m.body; b.empty();
  if (stopped) {
    const a = b.createEl('button', { cls: 'lbc-sy-alert' }); a.type = 'button';
    a.createEl('b', { text: why[0] }); if (why[1]) a.append('：' + why[1]);
    a.append(' · 点开看问题列表');
    a.onclick = () => openProblemsPanel();
  }
  const topRow = b.createEl('div', { cls: 'lbc-sy-top' });
  // v = [前半, 斜体后半] / 字符串 / null（—）
  // 1026 她（首页只留三件可点的同步信息）：上次同步 → 同步记录；下次同步 → 设置「收藏与同步」里那一个同步时间编辑（openSetupPage('schedule')，和向导同一处）
  const cell = (k, v, cls = '', click = null, tip = '') => {
    const c = topRow.createEl(click ? 'button' : 'div', { cls: cls + (click ? ' lbc-sy-cell' : '') });
    if (click) { c.type = 'button'; c.onclick = e => { e?.stopPropagation?.(); click(); }; if (tip) c.title = tip; }
    c.createEl('div', { cls: 'lbc-sy-k', text: k }); const big = c.createEl('div', { cls: 'lbc-sy-big' }); if (Array.isArray(v)) { big.append(v[0] + ' '); big.createEl('i', { text: v[1] }); } else big.setText(v || '—'); return big;
  };
  cell('上次同步', bigWhen(last), 'lbc-sy-last', mobile ? null : () => openUpdated(), '点开看同步记录');
  if (running) cell('同步中', run.text.replace('同步中', '').trim() || '…', 'lbc-sy-now', mobile ? null : () => openUpdated(), '点开看同步记录');
  else cell('下次同步', nx, 'lbc-sy-next', p ? () => openSyncSettings() : null, '改同步时间（设置 · 收藏与同步）');
  m.sec.dataset.state = running ? 'running' : stopped ? 'stopped' : 'idle';
  const bar = b.createEl('div', { cls: 'lbc-sy-bar' }); const fill = bar.createEl('i');
  const cap = b.createEl('div', { cls: 'lbc-sy-cap' });
  if (running) {
    const pv = p && typeof p.syncProgressView === 'function' ? p.syncProgressView(st) : null;
    if (run.pct == null) bar.classList.add('is-unknown'); else fill.style.width = (Math.round(run.pct * 1000) / 10) + '%';
    cap.createEl('span', { text: run.pct == null ? '同步中' : Math.round(run.pct * 100) + '%' });
    cap.createEl('span', { text: pv?.running ? (pv.eta || pv.phase || pv.today || '') : String(st.progress || st.message || '') });
  } else if (last && next && next > last) {
    const pct = Math.max(0, Math.min(1, (now - last) / (next - last)));
    fill.style.width = (Math.round(pct * 1000) / 10) + '%';
    cap.createEl('span', { text: Math.round(pct * 100) + '%' }); cap.createEl('span', { text: leftText(next - now) });
  } else {
    cap.createEl('span', { text: '' });
    cap.createEl('span', { text: !p ? '' : !schedule && !scheduleErr ? '正在读同步计划…' : next ? leftText(next - now) : '没有下次' });
  }
  // 1027b 她：同步时间在这里就能改——点「每天 18:00 · 改」在块里展开同一个同步时间编辑器（schedule-ui，和设置页同一处），再点收起
  if (!running && (freq || p)) {
    const editable = !!p && !mobile;
    const f = b.createEl(editable ? 'button' : 'div', { cls: 'lbc-sy-freq' + (editable ? ' lbc-sy-edit' : '') });
    f.createEl('span', { cls: 'lbc-sy-freq-t', text: freq || '没有定时' });
    if (editable) {
      f.type = 'button'; f.title = '改同步时间'; f.dataset.act = 'sched'; f.setAttribute('aria-expanded', String(syncEditOpen));
      f.createEl('span', { cls: 'lbc-sy-pen', text: syncEditOpen ? '收起' : '改' });
      f.onclick = e => { e?.stopPropagation?.(); syncEditOpen = !syncEditOpen; m.sig = null; paintSync(); sideFadeSoon(); };
      if (syncEditOpen) syncEditor(b, p);
    }
  }
  if (note) b.createEl('p', { cls: 'lbc-sy-note', text: note });
  const row = (k, v, cls = '') => { const r = b.createEl('div', { cls: 'lbc-sy-row' + (cls ? ' ' + cls : '') }); r.createEl('span', { text: k }); return r.createEl('b', { text: v }); };
  row('今日新增', `${nToday} 篇`);
  // 1027b 她：「立即同步 / 查看同步记录」两个按钮藏掉（同步记录 = 点「上次同步」；立即同步在设置「收藏与同步」、命令面板里）
}
let syncEditOpen = false, syncEd = null;
function syncEditor(b, p) {
  try { syncEd?.destroy?.(); } catch {}
  syncEd = null;
  const holder = b.createEl('div', { cls: 'lbc-sy-sched' });
  holder.onclick = e => e?.stopPropagation?.();
  if (typeof p.scheduleUI === 'function') {
    try { syncEd = p.scheduleUI().render(holder, { primary: false, onSaved: () => loadSchedule({ force: true }) }); return; }
    catch (e) { holder.empty(); holder.createEl('p', { cls: 'lbc-sy-note', text: '同步时间编辑器没画上：' + (e?.message || e) }); }
  }
  const go = holder.createEl('button', { cls: 'lbc-sy-edit', text: '去设置里改同步时间 →' }); go.type = 'button'; go.onclick = () => openSyncSettings();
}
async function openSyncSettings(btn) {
  // 1026：同步时间只有一个编辑处（设置「收藏与同步」data-section="sync-time"）：新插件有 openSyncTime 就直达，旧的走 openSetupPage('schedule')（落到同一处）
  const q = provider();
  if (q && typeof q.openSyncTime === 'function') { try { await q.openSyncTime(); } catch (e) { LB.say('设置没打开：' + (e?.message || e), { kind: 'error' }); } return; }
  const p = await want('openSetupPage'); if (!p) return;
  try { p.openSetupPage('schedule'); } catch (e) { LB.say('设置没打开：' + (e?.message || e), { kind: 'error' }); }
  void btn;
}

// OVERVIEW：全部 / 近 7 天 / 已收藏 / 在用分类（48px 大数字）+ 近 14 天每日导入（黑细柱，今天加粗标数）
function paintOverview() {
  const m = mods.overview; const now = new Date();
  const days = []; for (let k = 13; k >= 0; k--) { const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - k); days.push({ key: ymd(d), d, n: 0 }); }
  const byDay = new Map(days.map(x => [x.key, x]));
  const week = new Set(days.slice(-7).map(x => x.key));
  let nWeek = 0, nStar = 0; const cats = new Set();
  for (const it of items) {
    const dk = dayOf(it); const slot = byDay.get(dk); if (slot) slot.n++;
    if (week.has(dk)) nWeek++;
    if (it.starred) nStar++;
    cats.add(catNameOf(it));
  }
  cats.delete(UNC_LABEL);
  setSum(m, [[String(items.length)], ' 篇 · 近 7 天 ', ['+' + nWeek], ' · ★ ', [String(nStar)]]);
  if (sideFold.overview) return;
  const sig = JSON.stringify([items.length, nWeek, nStar, cats.size, days.map(x => x.key + ':' + x.n), modOpt('overview').metrics]);
  if (m.sig === sig) return; m.sig = sig;
  const b = m.body; b.empty();
  const figs = b.createEl('div', { cls: 'lbc-figs' });
  const show = new Set(modOpt('overview').metrics);   // 1027：显示哪几个数在模块「调整」里勾
  for (const [k, n, l] of [['all', items.length, '全部收藏'], ['week', nWeek, '近 7 天新增'], ['star', nStar, '已收藏'], ['cats', cats.size, '在用分类']]) {
    if (!show.has(k)) continue;
    const f = figs.createEl('div', { cls: 'lbc-fig' }); f.createEl('div', { cls: 'lbc-fig-n', text: String(n) }); f.createEl('div', { cls: 'lbc-fig-l', text: l });
  }
  if (!show.has('bars')) return;
  const max = Math.max(1, ...days.map(x => x.n));
  const bars = b.createEl('div', { cls: 'lbc-bars' });
  days.forEach((x, i) => {
    const c = bars.createEl('div', { cls: 'lbc-bar' + (x.n ? '' : ' is-zero') + (i === 13 ? ' is-today' : '') });
    c.title = `${mdOf(x.d)}：${x.n} 篇`;
    c.createEl('span', { text: String(x.n) });
    c.createEl('i').style.height = (x.n ? Math.max(4, Math.round(x.n / max * 72)) : 1) + 'px';
  });
  const dl = b.createEl('div', { cls: 'lbc-days' });
  days.forEach((x, i) => dl.createEl('span', { text: i === 13 ? '今' : mdOf(x.d) }));
}

// 底部渐隐：边栏内容没到底才加（到底 / 不超高就去掉）；1027 起边栏可以有好几列（每列各算各的）
const asides = [side];
function sideFade() {
  if (!SIDE_ON) return;
  for (const a of asides) {
    const more = (Number(a.scrollHeight) || 0) - (Number(a.scrollTop) || 0) - (Number(a.clientHeight) || 0) > 2;
    a.classList.toggle('is-more', more);
  }
}
let fadeRaf = 0;
function sideFadeSoon() { if (fadeRaf) return; const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : f => setTimeout(f, 16); fadeRaf = raf(() => { fadeRaf = 0; sideFade(); }) || 1; }
const mods = {};
// 1027：托盘在所有模块上面（页面最前，编排时吸顶、滚动也在）——模块怎么挪都不会把它挤到中间去
const arrangeTray = arrangeBtn ? wrap.createEl('div', { cls: 'lbc-arrange-tray' }) : null;
if (arrangeTray) wrap.insertBefore(arrangeTray, top);
// 墙下面的几排（模块被拖到收藏墙那一排的下面时）
const afterEl = wrap.createEl('div', { cls: 'lbc-after' }); afterEl.hidden = true;
board.after(afterEl);

// ── 1027 编排（design-1027 §2，她批的结构和交互；外观仍是现在的黑白雕刻）：八个模块平级——
//    标题 / Logo · 分类 · 筛选与搜索 · 最近导入 · 同步 · Token 费用 · 概览 · 收藏墙。
// 布局 = 几排；一排 = 几列（宽度按 12 格，列宽是比例）；一列 = 从上到下几个模块。收藏墙所在的那一排是 .lbc-board（边栏列吸在页头下面、各自滚），
// 它前面的几排进吸顶区 .lbc-top，后面的几排进 .lbc-after。任何模块都能拖到任何位置（叠在别的模块上下 / 放到它左右成新的一列），
// 边缘拖动调宽（吸附到 1/12、最窄 2 格），× 移除（内容和功能都在，「＋ 模块」加回原位置），「调整」在模块里展开（字体、字号、这个模块自己的设置）。
// 存插件设置 catalogLayout = {modules: [{id, x, y, width, hidden, typography: {font, size}, options}], theme: {titleFont, bodyFont, numberFont, scale, gap}}
//   （design-1027 §5 的形状：y = 第几排，x = 这一列从第几格起，同一 (y, x) 的模块按数组顺序从上到下）；和默认一样的不写，全默认 = null。
//   旧的 {side, top, sideRight, sideW, gap, density}（1022 / 1026）读的时候换算一次，下次保存写成新形状。
// 标题文字、收藏墙列数、费用上限、分类、同步时间不在 catalogLayout 里：仍是各自唯一的来源（catalogTitle / catalogColumns / budget.dailyYuan / 索引.md / 计划任务）。
// 手机 / 星标页 / 插件没开：照默认摆，只读（没有「编排」）。
// 1028 她：「像搭积木一样」——页头拆成小块（标题 · 计数行 · 分类 · 范围 · AI 标签 · 类型 · 我的收藏 / Tag · 排序 · 视图 · 搜索 · 问收藏），宽度按 48 格，
//   页头 / 墙下面的每一排里每一块有自己的起点 x（可以留空、随便横着摆）；收藏墙那一排仍是几列铺满（边栏一列里的块始终一样宽）。
const GRID = 48, MIN_W = 3;
const MOD_IDS = ['title', 'meta', 'cats', 'scope', 'topics', 'types', 'albums', 'picks', 'sort', 'view', 'search', 'ask', 'recent', 'sync', 'token', 'overview', 'wall'];
const MOD_NAMES = { title: '标题', meta: '计数行', cats: '分类', scope: '范围', topics: 'AI 标签', types: '类型', albums: '专辑', picks: '我的收藏 / Tag', sort: '排序', view: '视图', search: '搜索', ask: '问收藏',
  recent: '最近导入', sync: '同步', token: 'Token 费用', overview: '概览', wall: '收藏墙' };
const SIDE_MODS = ['recent', 'sync', 'token', 'overview'];
const CORE_MODS = new Set(TOP_IDS);
const OPT_DEFAULT = {
  recent: { count: 6, h: 0 },
  sync: { h: 0 },
  overview: { metrics: ['all', 'week', 'star', 'cats', 'bars'], h: 0 },
  token: { period: 'month', h: 0 },
  wall: { density: 'm' },
};
const OPT_CHOICES = {
  recent: { count: [2, 4, 6, 8] },
  overview: { metrics: ['all', 'week', 'star', 'cats', 'bars'] },
  token: { period: ['day', 'week', 'month'] },
  wall: { density: ['s', 'm', 'l'] },
};
const FONT_SET = [['', '跟随全站'], [FONT_NAMES.cinzel, 'Cinzel 雕刻'], [FONT_NAMES.song, '衬线（思源宋体）'], [FONT_NAMES.hei, '无衬线（思源黑体）'],
  [FONT_NAMES.cormorant, 'Cormorant 斜体'], [FONT_NAMES.kai, '楷体'], [FONT_NAMES.georgia, 'Georgia']];
// 模块自己的字体：同一套名字 → 令牌的写法（名字在前、默认栈在后）
const fontVar = (name, role) => { if (!name) return ''; try { const v = LB.themeVars?.({ [role]: name })?.[role === 'titleFont' ? '--lb-font-title' : '--lb-font-body']; if (v) return v; } catch {} return name; };
const SIZE_SET = [85, 100, 115, 130, 150];
const SCALE_SET = [[0.9, '小'], [1, '标准'], [1.1, '大'], [1.2, '特大']];
const GAP_SET = [[17, '紧凑'], [24, '标准'], [32, '宽松']];
const THEME_DEFAULT = { titleFont: '', bodyFont: '', numberFont: '', scale: 1, gap: 24 };
// 默认 = 1027 的样子：标题一排（计数行在右边）、分类一排、筛选条一排（左边几组 + 右边 排序 · 视图 · 搜索 · 问收藏）、边栏 16 / 墙 32
const DEFAULT_ROWS = () => [
  { cols: [{ x: 0, w: 34, mods: ['title'] }, { x: 34, w: 14, mods: ['meta'] }] },
  { cols: [{ x: 0, w: 48, mods: ['cats'] }] },
  { cols: [{ x: 0, w: 12, mods: ['scope'] }, { x: 12, w: 6, mods: ['topics'] }, { x: 18, w: 5, mods: ['types'] }, { x: 23, w: 4, mods: ['albums'] }, { x: 27, w: 4, mods: ['picks'] },
    { x: 31, w: 3, mods: ['sort'] }, { x: 34, w: 3, mods: ['view'] }, { x: 37, w: 7, mods: ['search'] }, { x: 44, w: 4, mods: ['ask'] }] },
  { cols: [{ w: 16, mods: ['recent', 'sync', 'token', 'overview'] }, { w: 32, mods: ['wall'] }] }];
const ENGINE = SIDE_ON;   // 手机 / 星标页：没有边栏模块，照默认摆
const clone = v => JSON.parse(JSON.stringify(v));
const cfgDefault = id => ({ hidden: false, font: '', size: 100, opt: clone(OPT_DEFAULT[id] || {}) });
function cleanOpt(id, raw) {
  const out = clone(OPT_DEFAULT[id] || {}), ch = OPT_CHOICES[id] || {};
  if (!raw || typeof raw !== 'object') return out;
  for (const k of Object.keys(out)) {
    const v = raw[k];
    if (Array.isArray(out[k])) { if (Array.isArray(v)) out[k] = ch[k].filter(x => v.includes(x)); }
    else if (k === 'h') out.h = modH(v);
    else if (ch[k]?.includes(v)) out[k] = v;
  }
  return out;
}
const fontOf = v => (typeof v === 'string' ? v.slice(0, 200) : '');
// 1027b 边栏模块的高度（编排时拖下边框）：0 = 跟内容走；否则 80–1600px，内容超出在块里滚
const modH = v => { const n = Math.round(Number(v)); return Number.isFinite(n) && n >= 80 ? Math.min(1600, n) : 0; };
const sizeOf = v => { const n = Math.round(Number(v)); return Number.isFinite(n) && n >= 60 && n <= 200 ? n : 100; };
function cleanTheme(t) {
  const o = { ...THEME_DEFAULT };
  if (!t || typeof t !== 'object') return o;
  for (const k of ['titleFont', 'bodyFont', 'numberFont']) o[k] = fontOf(t[k]);
  const sc = Number(t.scale); if (Number.isFinite(sc) && sc >= 0.8 && sc <= 1.4) o.scale = Math.round(sc * 100) / 100;
  const g = Number(t.gap); if (Number.isFinite(g) && g >= 8 && g <= 48) o.gap = Math.round(g);
  return o;
}
// 一排凑整：收藏墙那一排 = 几列铺满 48 格（x 不用）；别的排 = 每块自己的起点 x + 宽 w，不重叠、不出 48 格，空着的地方就空着
const isBoardRow = r => r.cols.some(c => c.mods.includes('wall'));
function fitRow(row) {
  const board = isBoardRow(row);
  const cap = board ? 6 : 12;
  if (row.cols.length > cap) { const extra = row.cols.splice(cap); for (const c of extra) row.cols[cap - 1].mods.push(...c.mods); }
  for (const c of row.cols) c.w = Math.max(MIN_W, Math.min(GRID, Math.round(Number(c.w) || 0) || MIN_W));
  if (board) {
    for (const c of row.cols) delete c.x;
    if (row.cols.length === 1) { row.cols[0].w = GRID; return; }
    let sum = row.cols.reduce((n, c) => n + c.w, 0);
    if (sum !== GRID) { for (const c of row.cols) c.w = Math.max(MIN_W, Math.round(c.w * GRID / sum)); sum = row.cols.reduce((n, c) => n + c.w, 0); }
    let guard = 96;
    while (sum !== GRID && guard--) {
      const c = sum > GRID ? row.cols.filter(x => x.w > MIN_W).sort((a, b) => b.w - a.w)[0] : row.cols.slice().sort((a, b) => b.w - a.w)[0];
      if (!c) break; c.w += sum > GRID ? -1 : 1; sum += sum > GRID ? -1 : 1;
    }
    return;
  }
  // 自由排：先按起点排好；放不下（总宽超 48）就按比例缩，再从左往右推开重叠、从右往左收回出界
  let auto = 0;
  for (const c of row.cols) { const x = Math.round(Number(c.x)); c.x = Number.isFinite(x) ? Math.max(0, x) : auto; auto = c.x + c.w; }
  row.cols.sort((a, b) => a.x - b.x);
  let sum = row.cols.reduce((n, c) => n + c.w, 0);
  if (sum > GRID) {
    for (const c of row.cols) c.w = Math.max(MIN_W, Math.floor(c.w * GRID / sum));
    sum = row.cols.reduce((n, c) => n + c.w, 0);
    while (sum > GRID) { const c = row.cols.filter(x => x.w > MIN_W).sort((a, b) => b.w - a.w)[0]; if (!c) break; c.w--; sum--; }
  }
  let end = 0;
  for (const c of row.cols) { if (c.x < end) c.x = end; end = c.x + c.w; }
  let lim = GRID;
  for (let k = row.cols.length - 1; k >= 0; k--) { const c = row.cols[k]; if (c.x + c.w > lim) c.x = Math.max(0, lim - c.w); lim = c.x; }
}
const defaultSlot = id => { const rs = DEFAULT_ROWS(); for (let ri = 0; ri < rs.length; ri++) for (const c of rs[ri].cols) if (c.mods.includes(id)) return { ri, x: c.x ?? 0, w: c.w }; return { ri: 0, x: 0, w: GRID }; };
// 整理：去掉空列 / 空排、每个模块只出现一次、缺的模块补回默认位置
function normalizeRows(rows) {
  const seen = new Set();
  for (const r of rows) for (const c of r.cols) c.mods = c.mods.filter(id => MOD_IDS.includes(id) && !seen.has(id) && seen.add(id));
  for (const r of rows) r.cols = r.cols.filter(c => c.mods.length);
  rows = rows.filter(r => r.cols.length);
  const missing = MOD_IDS.filter(id => !seen.has(id));
  for (const id of missing) {
    if (id === 'wall') { rows.push({ cols: [{ w: GRID, mods: ['wall'] }] }); continue; }
    if (SIDE_MODS.includes(id)) {
      // 放回边栏那一列（和别的边栏模块在一起，按默认顺序插）；没有就在墙左边开一列
      let col = null;
      for (const r of rows) for (const c of r.cols) if (!col && c.mods.some(m => SIDE_MODS.includes(m))) col = c;
      if (!col) { const br = rows.find(isBoardRow); col = { w: 16, mods: [] }; br.cols.unshift(col); }
      const order = SIDE_MODS.indexOf(id); let at = col.mods.length;
      for (let i = 0; i < col.mods.length; i++) if (SIDE_MODS.includes(col.mods[i]) && SIDE_MODS.indexOf(col.mods[i]) > order) { at = i; break; }
      col.mods.splice(at, 0, id);
      continue;
    }
    // 页头的小块：默认那一排的伙伴在哪一排、那个位置又空着 → 放回去；不然单独成一排，放在墙那一排上面
    const d = defaultSlot(id), mates = DEFAULT_ROWS()[d.ri].cols.flatMap(c => c.mods);
    let bi = rows.findIndex(isBoardRow); if (bi < 0) bi = rows.length;
    const host = rows.slice(0, bi).find(r => r.cols.some(c => c.mods.some(m => mates.includes(m))) && !r.cols.some(c => c.x < d.x + d.w && d.x < c.x + c.w));
    if (host) host.cols.push({ x: d.x, w: d.w, mods: [id] });
    else rows.splice(Math.min(d.ri, bi), 0, { cols: [{ x: d.x, w: d.w, mods: [id] }] });
  }
  for (const r of rows) fitRow(r);
  return rows;
}
// 1022 / 1026 的旧布局 → 1027 的「排 / 列」（12 格；下面 upgradeRows 再换成 48 格的小块）
function migrateLegacy(L, cfg, theme) {
  const ids = (list, allowed) => { const out = [], seen = new Set(); if (Array.isArray(list)) for (const m of list) { const id = typeof m === 'string' ? m : m?.id; if (allowed.includes(id) && !seen.has(id)) { seen.add(id); out.push({ id, hidden: !!(m && typeof m === 'object' && m.hidden) }); } } for (const id of allowed) if (!seen.has(id)) out.push({ id, hidden: false }); return out; };
  const top_ = ids(L.top, ['title', 'cats', 'filters']), side_ = ids(L.side, ['recent', 'sync', 'overview']);
  let filtersHidden = false;
  for (const m of [...top_, ...side_]) { if (m.id === 'filters') filtersHidden = m.hidden; else cfg[m.id].hidden = m.hidden; }
  const sideMods = side_.map(m => m.id); sideMods.splice(sideMods.indexOf('sync') + 1, 0, 'token');
  const sw = { s: 3, m: 4, l: 5 }[L.sideW] || 4;
  const sideCol = { w: sw, mods: sideMods }, wallC = { w: 12 - sw, mods: ['wall'] };
  if (['s', 'm', 'l'].includes(L.density)) cfg.wall.opt.density = L.density;
  if (L.gap === 's') theme.gap = 17; else if (L.gap === 'l') theme.gap = 32;
  return { rows: [...top_.map(m => ({ cols: [{ x: 0, w: 12, mods: [m.id] }] })), { cols: L.sideRight === true ? [wallC, sideCol] : [sideCol, wallC] }], filtersHidden };
}
// 1027（12 格、「筛选与搜索」一整块、标题带计数行）→ 1028（48 格小块）：宽度 ×4；筛选条那一列按默认比例拆成八块铺在原来的宽度里；
// 标题那一列：整排只有它 → 右边分出计数行，否则计数行叠在标题下面。旧「筛选项收起」= 左边四块（范围 · AI 标签 · 类型 · 我的收藏 / Tag）移除；
// 旧「调整」里选掉的筛选项 = 对应的块移除
function upgradeRows(rows, cfg, { filtersHidden = false, show = null } = {}) {
  const FROW = DEFAULT_ROWS()[2].cols;
  for (const r of rows) {
    let x = 0;
    for (const c of r.cols) { c.x = Number.isFinite(Number(c.x)) ? Number(c.x) * 4 : x; c.w = (Number(c.w) || 3) * 4; x = c.x + c.w; }
    const out = [];
    for (const c of r.cols) {
      const k = c.mods.indexOf('filters');
      if (k >= 0) {
        c.mods.splice(k, 1);
        if (c.mods.length) out.push(c);
        const kw = c.w / GRID;
        let px = c.x;
        for (const fc of FROW) { const w = Math.max(MIN_W, Math.round(fc.w * kw)); out.push({ x: px, w, mods: fc.mods.slice() }); px += w; }
        continue;
      }
      const t = c.mods.indexOf('title');
      if (t >= 0 && !c.mods.includes('meta')) {
        if (r.cols.length === 1 && c.mods.length === 1) { const tw = Math.max(MIN_W, c.w - 14); out.push({ x: c.x, w: tw, mods: ['title'] }, { x: c.x + tw, w: 14, mods: ['meta'] }); continue; }
        c.mods.splice(t + 1, 0, 'meta');
      }
      out.push(c);
    }
    r.cols = out;
  }
  const hide = id => { if (cfg[id]) cfg[id].hidden = true; };
  if (filtersHidden) for (const id of ['scope', 'topics', 'types', 'albums', 'picks']) hide(id);
  if (Array.isArray(show)) {
    const has = k => show.includes(k);
    if (!has('scope')) { hide('scope'); hide('topics'); }
    if (!has('type')) hide('types');
    if (!has('tag') && !has('plat') && !has('src')) { hide('picks'); hide('albums'); }
    for (const k of ['sort', 'view', 'ask']) if (!has(k)) hide(k);
  }
  return rows;
}
function parseLayout(L) {
  const cfg = {}; for (const id of MOD_IDS) cfg[id] = cfgDefault(id);
  let theme = cleanTheme(L && L.theme), rows;
  if (L && typeof L === 'object' && Array.isArray(L.modules)) {
    const v48 = Number(L.grid) === GRID;
    const byY = new Map(), seen = new Set();
    let oldF = null;
    L.modules.forEach((m, i) => {
      const id = m && m.id;
      if (!(MOD_IDS.includes(id) || (!v48 && id === 'filters')) || seen.has(id)) return; seen.add(id);
      const y = Number.isFinite(Number(m.y)) ? Number(m.y) : 1e6 + i, x = Number.isFinite(Number(m.x)) ? Number(m.x) : 0;
      if (id === 'filters') oldF = { hidden: !!m.hidden, show: Array.isArray(m.options?.show) ? m.options.show : null };
      else cfg[id] = { hidden: !!m.hidden, font: fontOf(m.typography?.font), size: sizeOf(m.typography?.size), opt: cleanOpt(id, m.options) };
      if (!byY.has(y)) byY.set(y, new Map());
      const row = byY.get(y); if (!row.has(x)) row.set(x, { x, w: Number(m.width) || 0, mods: [] });
      const col = row.get(x); col.w = Math.max(col.w, Number(m.width) || 0); col.mods.push(id); if (m.fixed === true) col.fixed = true;
    });
    rows = [...byY.entries()].sort((a, b) => a[0] - b[0]).map(([, cols]) => ({ cols: [...cols.entries()].sort((a, b) => a[0] - b[0]).map(([, c]) => c) }));
    if (!v48) rows = upgradeRows(rows, cfg, { filtersHidden: !!oldF?.hidden, show: oldF?.show });
  } else if (L && typeof L === 'object' && ['side', 'top', 'sideRight', 'sideW', 'gap', 'density'].some(k => k in L)) {
    const m = migrateLegacy(L, cfg, theme); rows = upgradeRows(m.rows, cfg, { filtersHidden: m.filtersHidden });
  } else rows = DEFAULT_ROWS();
  return { rows: normalizeRows(rows), cfg, theme };
}
function readLayout() { const L = provider()?.settings?.catalogLayout; return parseLayout(L && typeof L === 'object' ? L : null); }
let layout = ENGINE ? readLayout() : { rows: DEFAULT_ROWS(), cfg: Object.fromEntries(MOD_IDS.map(id => [id, cfgDefault(id)])), theme: { ...THEME_DEFAULT } };
const modCfg = id => layout.cfg[id] || cfgDefault(id);
function modOpt(id) { return modCfg(id).opt; }
function wallDensity() { return modOpt('wall').density || 'm'; }
function gapScale() { return Math.round(((layout.theme.gap || 24) / 24) * 100) / 100; }
function layoutToSetting() {
  const out = {};
  const sameRows = JSON.stringify(layout.rows) === JSON.stringify(normalizeRows(DEFAULT_ROWS()));
  const sameCfg = MOD_IDS.every(id => JSON.stringify(layout.cfg[id]) === JSON.stringify(cfgDefault(id)));
  if (!sameRows || !sameCfg) {
    const list = [];
    layout.rows.forEach((r, y) => { let x = 0; const board = isBoardRow(r); for (const c of r.cols) { if (!board) x = c.x; for (const id of c.mods) {
      const g = layout.cfg[id], m = { id, x, y, width: c.w, hidden: !!g.hidden };
      if (c.fixed && !board) m.fixed = true;
      if (g.font || g.size !== 100) m.typography = { font: g.font, size: g.size };
      if (JSON.stringify(g.opt) !== JSON.stringify(OPT_DEFAULT[id] || {})) m.options = clone(g.opt);
      list.push(m);
    } x += c.w; } });
    out.modules = list; out.grid = GRID;
  }
  if (JSON.stringify(layout.theme) !== JSON.stringify(THEME_DEFAULT)) out.theme = { ...layout.theme };
  return Object.keys(out).length ? out : null;
}

// ── 摆放（只在位置真变了时挪节点：挪会让里面的搜索框失焦） ──
const modEl = id => id === 'wall' ? boardMain : blocks[id] || mods[id]?.sec || null;
const present = id => !!modEl(id);
const topRowEls = [], afterRowEls = [];
let boardColEls = [];
function rowEl(pool, i) {
  if (!pool[i]) { const r = document.createElement('div'); r.className = 'lbc-row'; pool[i] = { el: r, cols: [] }; }
  return pool[i];
}
function colEl(row, j) {
  if (!row.cols[j]) { const c = document.createElement('div'); c.className = 'lbc-rcol'; row.cols[j] = c; }
  return row.cols[j];
}
const kidsOf = el => [...(el.children || [])];
function fillCol(colNode, ids) {
  let k = 0;
  for (const id of ids) {
    const el = modEl(id); if (!el) continue;
    const at = kidsOf(colNode).filter(c => c.classList?.contains('lbc-m'));
    if (at[k] !== el) colNode.insertBefore(el, at[k] || null);
    k++;
  }
}
function placeRows(container, data_, pool, ref) {
  const used = [];
  data_.forEach((r, i) => {
    const row = rowEl(pool, i); used.push(row.el);
    r.cols.forEach((c, j) => { const cn = colEl(row, j); if (cn.parentNode !== row.el || kidsOf(row.el).filter(x => x.classList?.contains('lbc-rcol'))[j] !== cn) row.el.insertBefore(cn, kidsOf(row.el).filter(x => x.classList?.contains('lbc-rcol'))[j] || null); fillCol(cn, c.mods); });
    for (const extra of row.cols.splice(r.cols.length)) extra.remove();
  });
  const cur = kidsOf(container).filter(x => x.classList?.contains('lbc-row'));
  if (used.some((el, i) => cur[i] !== el)) for (const el of used) container.insertBefore(el, ref && ref.parentNode === container ? ref : null);
  for (const extra of pool.splice(data_.length)) extra.el.remove();
}
function newAside() { const a = document.createElement('aside'); a.className = 'lbc-side'; a.addEventListener('scroll', () => sideFade(), { passive: true }); try { roRef?.observe(a); } catch {} return a; }
function placeBoard(r) {
  const want = []; let ai = 0;
  for (const c of r.cols) {
    let node;
    if (c.mods.includes('wall')) node = wallCol;
    else { if (!asides[ai]) asides[ai] = newAside(); node = asides[ai++]; }
    want.push(node); fillCol(node, c.mods);
  }
  // 多出来的边栏列：第一列（side）留着当空位（藏起来），别的摘掉
  for (let i = asides.length - 1; i >= Math.max(ai, 1); i--) { if (asides[i] !== side) asides[i].remove(); asides.splice(i, 1); }
  boardColEls = want.slice();
  if (!ai) { side.hidden = true; want.unshift(side); }
  const cur = kidsOf(board).filter(x => x === wallCol || x.classList?.contains('lbc-side'));
  if (want.length !== cur.length || want.some((el, i) => cur[i] !== el)) for (const el of want) board.insertBefore(el, null);
}
const isGone = id => !!modCfg(id).hidden;
function visibleIn(ids) { return ids.some(id => present(id) && !isGone(id)); }
function templateOf(cols) { const vis = cols.filter(c => visibleIn(c.mods)); return { vis, tpl: vis.map(c => `minmax(0,${c.w}fr)`).join(' ') }; }
function paintVisibility() {
  for (const id of MOD_IDS) {
    const el = modEl(id); if (!el) continue;
    const g = modCfg(id);
    el.classList.toggle('is-gone', isGone(id));
    // 字体 / 字号：字体改的是这一块里的正文 / 衬线（标题块连雕刻字一起）；字号 = 这一块缩放（标题按比例放大上限）
    const set = (k, v) => { if (v) { if (el.style.getPropertyValue(k) !== v) el.style.setProperty(k, v); } else if (el.style.getPropertyValue(k)) el.style.removeProperty(k); };
    const fb = fontVar(g.font, 'bodyFont');
    set('--f-sans', fb); set('--f-serif', fb); if (id === 'title') set('--f-display', fontVar(g.font, 'titleFont'));
    const k = g.size === 100 ? '' : String(g.size / 100);
    if (id === 'title') { set('--lbc-title-k', k); set('--lbc-m-k', ''); } else set('--lbc-m-k', k);
    if (SIDE_MODS.includes(id)) { const h = modH(g.opt?.h); el.classList.toggle('has-h', !!h); set('--lbc-m-h', h ? h + 'px' : ''); }
  }
  const bi = boardIndex();
  // 1028 页头 / 墙下面的排：48 格，每块宽 w 格、离前一块空 (x − 前一块的尾) 格（空着的地方就空着）；只有一块、而且铺满整排 = 普通块。
  //   筛选那些小块（.is-tight）至少有自己内容那么宽：不在块里折行；前面的块比格子宽时后面的往右顺延（fitFreeGaps 量了再定空多少），实在挤不下整块换行
  const TIGHT = new Set(CTL_IDS.filter(id => id !== 'search'));   // 搜索框能缩（最窄 140px）
  const setS = (el, k, v) => { if (el.style[k] !== v) el.style[k] = v; };
  const paintRow = (pool, data_) => data_.forEach((r, i) => {
    const row = pool[i]; if (!row) return;
    const vis = r.cols.filter(c => visibleIn(c.mods));
    row.el.hidden = !vis.length;
    const single = vis.length === 1 && vis[0].x === 0 && vis[0].w === GRID;
    row.el.classList.toggle('is-single', single);
    row.el.classList.toggle('is-free', !single);
    let end = 0;
    r.cols.forEach((c, j) => {
      const node = row.cols[j]; if (!node) return;
      const on = visibleIn(c.mods);
      node.hidden = !on;
      node.dataset.x = String(c.x); node.dataset.w = String(c.w);
      if (!on) return;
      end = c.x + c.w;
      const tight = c.mods.every(id => TIGHT.has(id));
      // 筛选小块：没拉过宽度 = 跟内容一样宽（格子只当起点用）；拉过（fixed）= 拉的那么宽，内容更宽时照内容
      setS(node, 'width', single || (tight && !c.fixed) ? '' : `calc(${c.w} * 100% / ${GRID})`);
      if (single) setS(node, 'marginLeft', '');
      node.classList.toggle('is-gap-r', !single && c.x + c.w < GRID);
      node.classList.toggle('is-tight', tight);
    });
    if (row.el.style.gridTemplateColumns) row.el.style.gridTemplateColumns = '';
    void end;
  });
  paintRow(topRowEls, layout.rows.slice(0, bi));
  paintRow(afterRowEls, layout.rows.slice(bi + 1));
  afterEl.hidden = !afterRowEls.some(r => !r.el.hidden);
  // 收藏墙那一排
  const br = layout.rows[bi];
  let ai = 0, nVis = 0;
  for (const c of br.cols) {
    const node = c.mods.includes('wall') ? wallCol : asides[ai++];
    const vis = visibleIn(c.mods);
    if (node === wallCol) node.hidden = !vis; else { node.hidden = !SIDE_ON || !vis; if (vis) nVis++; node.classList.toggle('has-core', c.mods.some(id => CORE_MODS.has(id) && present(id) && !isGone(id))); }
  }
  const { tpl } = templateOf(br.cols);
  if (board.style.getPropertyValue('--lbc-board-cols') !== tpl) { if (tpl) board.style.setProperty('--lbc-board-cols', tpl); else board.style.removeProperty('--lbc-board-cols'); }
  wrap.classList.toggle('is-side-empty', SIDE_ON && !nVis);
  fitFreeGaps();
  for (const id of MOD_IDS) { const el = modEl(id); if (el) el.classList.toggle('is-core', CORE_MODS.has(id)); }
}
// 1028 自由排的「起点」：块左边离这一排左边 = x 格；前面的块因为内容比格子宽占多了，就从它后面接着放（不重叠）。量现在的宽度再写 margin-left（px），
// 先读后写；窄屏（换行排）不管
function fitFreeGaps() {
  if (wrap.classList.contains('is-side-narrow')) { for (const pool of [...topRowEls, ...afterRowEls]) for (const n of pool?.cols || []) if (n.style.marginLeft) n.style.marginLeft = ''; return; }
  const bi = boardIndex(), plan = [];
  layout.rows.forEach((r, i) => {
    if (i === bi) return;
    const pool = i < bi ? topRowEls[i] : afterRowEls[i - bi - 1]; if (!pool || pool.el.hidden || !pool.el.classList.contains('is-free')) return;
    const W = Number(pool.el.clientWidth) || 0; if (!W) return;
    const unit = W / GRID, items = [];
    r.cols.forEach((c, j) => { const node = pool.cols[j]; if (node && !node.hidden) items.push({ node, x: c.x, w: Math.max(0, Number(node.getBoundingClientRect?.().width) || 0) }); });
    // 先按起点算每块前面要空多少；整排放不下时把空隙按比例压小（块本身不缩），还不够才换行
    let cur = 0;
    for (const it of items) { it.m = Math.max(0, it.x * unit - cur); cur += it.m + it.w; }
    const slack = W - items.reduce((n, it) => n + it.w, 0) - 1, sumM = items.reduce((n, it) => n + it.m, 0);
    const k = sumM > 0 && sumM > slack ? Math.max(0, slack) / sumM : 1;
    for (const it of items) { const m = Math.floor(it.m * k); plan.push([it.node, m ? m + 'px' : '']); }
  });
  for (const [node, v] of plan) if (node.style.marginLeft !== v) node.style.marginLeft = v;
}
function boardIndex() { const i = layout.rows.findIndex(r => r.cols.some(c => c.mods.includes('wall'))); return i < 0 ? layout.rows.length - 1 : i; }
function applyLayout({ relayout = true } = {}) {
  const bi = boardIndex();
  placeRows(top, layout.rows.slice(0, bi), topRowEls, selbar);
  placeRows(afterEl, layout.rows.slice(bi + 1), afterRowEls, null);
  placeBoard(layout.rows[bi]);
  paintVisibility();
  applyThemeNow();
  fitFreeGaps();
  if (arranging) { paintTray(); paintEdges(); for (const id of MOD_IDS) paintBar(id); }
  if (pageReady && relayout) { laidN = 0; relayoutIfNeeded(); paintStickyTop(); }
  sideFadeSoon();
}
// ── 全站样式（Aa 样式）：共享令牌 --lb-font-title / --lb-font-body / --lb-font-num / --lb-scale / --lb-gap；
//    有 LB.applyTheme（共享样式令牌那条线）就交给它，没有就本页兜底写到 body 上（同一组变量名，合进来以后两边一样） ──
let themeTouched = false;   // 首开、样式是默认的：不写变量（少一次整页样式重算）
function applyThemeNow() {
  const t = layout.theme;
  const isDefault = JSON.stringify(t) === JSON.stringify(THEME_DEFAULT);
  if (isDefault && !themeTouched) { if (wrap.style.getPropertyValue('--lbc-sp')) wrap.style.removeProperty('--lbc-sp'); return; }
  themeTouched = true;
  if (typeof LB.applyTheme === 'function') { try { LB.applyTheme(JSON.stringify(t) === JSON.stringify(THEME_DEFAULT) ? null : { ...t }, mount); } catch (e) { console.error('[lb] 样式没套上', e); } }
  else {
    const el = mount;
    const set = (k, v) => { if (!el?.style) return; if (v) { if (el.style.getPropertyValue(k) !== v) el.style.setProperty(k, v); } else if (el.style.getPropertyValue(k)) el.style.removeProperty(k); };
    set('--lb-font-title', t.titleFont); set('--lb-font-body', t.bodyFont); set('--lb-font-num', t.numberFont);
    set('--lb-scale', t.scale !== 1 ? String(t.scale) : ''); set('--lb-gap', t.gap !== 24 ? t.gap + 'px' : '');
  }
  const sp = String(gapScale());
  if (wrap.style.getPropertyValue('--lbc-sp') !== sp) wrap.style.setProperty('--lbc-sp', sp);
}

// ── 保存：改完马上生效，后台 400ms 防抖存（saveSettings → link-brain:settings，再广播 link-brain:catalog-prefs 让别的目录页就地换）；
//    托盘 / 展开的「调整」里一处小字：保存中… / 已保存 / 没保存上（改动还在页面上，可重试）——CONVENTIONS §1.5 ──
let saveTimer = null, saveSeq = 0, saveState_ = { kind: 'idle', text: '' }, pendingKeys = new Set();
function setSaveState(kind, text) { saveState_ = { kind, text }; paintSaveState(); }
function paintSaveState() {
  for (const el of [arrangeTray?.querySelector?.('.lbc-at-save'), openPanel?.el?.querySelector?.('.lbc-mp-save')]) {
    if (!el) continue;
    el.textContent = saveState_.text; el.classList.toggle('is-fail', saveState_.kind === 'fail');
    el.title = saveState_.kind === 'fail' ? saveState_.text : '';
  }
  const retry = arrangeTray?.querySelector?.('[data-act="retry"]'); if (retry) retry.hidden = saveState_.kind !== 'fail';
}
function saveSettingSoon(...keys) {
  const p = provider(); if (!p?.settings) return;
  for (const k of keys) pendingKeys.add(k);
  setSaveState('pending', '保存中…');
  clearTimeout(saveTimer); saveTimer = setTimeout(flushSave, 400);
}
function saveLayout() { const p = provider(); if (!p?.settings) return; p.settings.catalogLayout = layoutToSetting(); saveSettingSoon('catalogLayout'); }
async function flushSave() {
  clearTimeout(saveTimer); saveTimer = null;
  const p = provider(); if (!p?.settings) return;
  const keys = [...pendingKeys]; pendingKeys = new Set();
  const seq = ++saveSeq;
  setSaveState('saving', '保存中…');
  try {
    p.markSettingDirty?.(...keys);
    if (keys.includes('catalogTitle') && typeof p.setCatalogPrefs === 'function') await p.setCatalogPrefs({ title: p.settings.catalogTitle });
    else await p.saveSettings?.();
    if (seq === saveSeq) setSaveState('ok', '已保存');
    // 「Aa 样式」是全站的：插件把同一份 theme 写到 body（设置页、问收藏、笔记页跟着走）
    if (keys.includes('catalogLayout')) { try { p.applyTheme?.(); } catch {} }
    try { app.workspace.trigger('link-brain:catalog-prefs', { layout: true }); } catch {}
  } catch (e) {
    for (const k of keys) pendingKeys.add(k);
    if (seq === saveSeq) setSaveState('fail', '没保存上，改动还在页面上，可重试：' + (e?.message || e));
  }
}
cleanups.push(() => { if (saveTimer) flushSave(); });   // 离开页面时防抖还没到：照存
// 别的目录页 / 设置页改了布局：就地换（自己刚存的那份一样，不动）
function reloadLayout() {
  // 1028：正在拖块 / 拖边 / 拖高度时不重读——上一次保存刚写完发的通知会把磁盘上的旧布局读回来，盖掉手上正拖着的宽度（「拖边没反应」的根因）；松手会存，存完再对齐
  if (!ENGINE || saveTimer || drag || edgeDrag || hDrag) return;
  const next = readLayout();
  if (JSON.stringify(next) === JSON.stringify(layout)) return;
  layout = next; applyLayout();
  if (openPanel) refreshPanel();
}

// ── 移动：拖动 / 方向键 / 「调整」里的上下左右 ──
function locate(id) {
  for (let ri = 0; ri < layout.rows.length; ri++) { const r = layout.rows[ri]; for (let ci = 0; ci < r.cols.length; ci++) { const k = r.cols[ci].mods.indexOf(id); if (k >= 0) return { ri, ci, k, row: r, col: r.cols[ci] }; } }
  return null;
}
// 从原位置摘下来：这一列空了就整列去掉——墙那一排把宽度给墙（或旁边那一列），自由排就空着；这一排空了整排去掉
function detachMod(id) {
  const at = locate(id); if (!at) return null;
  const was = { w: at.col.w, x: at.col.x };
  at.col.mods.splice(at.k, 1);
  if (!at.col.mods.length) {
    const board = isBoardRow(at.row);
    at.row.cols.splice(at.ci, 1);
    if (at.row.cols.length) { if (board) { const heir = at.row.cols.find(c => c.mods.includes('wall')) || at.row.cols[Math.min(at.ci, at.row.cols.length - 1)]; heir.w += was.w; } }
    else layout.rows.splice(at.ri, 1);
  }
  return was;
}
// 在 ref 这一列的左 / 右开一列。墙那一排：宽度从 ref 那一列分（宽的分 16 格、中等 12 格、窄的 8 格）；自由排：照它原来的宽度贴过去，挤不下 fitRow 会往旁边推
function splitCol(row, ci, side_, id, w0) {
  const ref = row.cols[ci];
  if (!isBoardRow(row)) {
    // 自由排：旁边有空地就放空地（最多照它原来的宽度）；没有就和 ref 分 ref 的地方，别的块不动
    if (row.cols.length >= 12) return false;
    const want = Math.max(MIN_W, Math.min(GRID, w0 || 8));
    const prevEnd = ci > 0 ? row.cols[ci - 1].x + row.cols[ci - 1].w : 0, nextX = row.cols[ci + 1]?.x ?? GRID;
    const free = side_ === 'left' ? ref.x - prevEnd : nextX - (ref.x + ref.w);
    let nw, x;
    if (free >= MIN_W) { nw = Math.min(want, free); x = side_ === 'left' ? ref.x - nw : ref.x + ref.w; }
    else {
      nw = Math.min(want, ref.w - MIN_W); if (nw < MIN_W) return false;
      ref.w -= nw;
      if (side_ === 'left') { x = ref.x; ref.x += nw; } else x = ref.x + ref.w;
    }
    row.cols.splice(side_ === 'left' ? ci : ci + 1, 0, { x, w: nw, mods: [id] });
    return true;
  }
  if (row.cols.length >= 6) return false;
  let nw = ref.w >= 32 ? 16 : ref.w >= 20 ? 12 : 8;
  let donor = ref;
  if (donor.w - nw < MIN_W) donor = row.cols.filter(c => c.w - nw >= MIN_W).sort((a, b) => b.w - a.w)[0];
  if (!donor) { nw = MIN_W; donor = row.cols.filter(c => c.w >= MIN_W * 2).sort((a, b) => b.w - a.w)[0]; }
  if (!donor) return false;
  donor.w -= nw;
  row.cols.splice(side_ === 'left' ? ci : ci + 1, 0, { w: nw, mods: [id] });
  return true;
}
// zone：before / after = 叠在 ref 上 / 下；left / right = 并排；slot = 放进自由排的空地（opt.row = 那一排对象，opt.x = 起点）；newrow = 在 opt.row 的上 / 下（opt.below）单独成一排
function moveModule(id, refId, zone, opt = {}) {
  if (!ENGINE || id === refId) return false;
  const before = JSON.stringify(layout.rows);
  const was = detachMod(id) || {};
  const w0 = was.w;
  if (zone === 'slot' || zone === 'newrow') {
    const ri = layout.rows.indexOf(opt.row);
    const w = Math.max(MIN_W, Math.min(GRID, opt.w || w0 || 8));
    if (zone === 'slot' && ri >= 0 && !isBoardRow(opt.row)) opt.row.cols.push({ x: Math.max(0, Math.min(GRID - w, Math.round(opt.x || 0))), w, mods: [id] });
    else { const at = ri < 0 ? (opt.below ? layout.rows.length : 0) : ri + (opt.below ? 1 : 0); layout.rows.splice(at, 0, { cols: [{ x: Math.max(0, Math.min(GRID - w, Math.round(opt.x || 0))), w, mods: [id] }] }); }
  } else {
    const at = locate(refId);
    if (!at) { layout.rows = JSON.parse(before); return false; }
    if (zone === 'left' || zone === 'right') { if (!splitCol(at.row, at.ci, zone, id, w0)) at.col.mods.splice(at.k + 1, 0, id); }
    else at.col.mods.splice(at.k + (zone === 'after' ? 1 : 0), 0, id);
  }
  layout.rows = normalizeRows(layout.rows);
  if (JSON.stringify(layout.rows) === before) return false;
  applyLayout(); saveLayout();
  return true;
}
// ↑ / ↓：同一列里换位置；到了一列的头 / 尾：单独成一排，放到这一排的上 / 下面（本来就单独一排就和上 / 下一排换）
function stepModule(id, d) {
  const at = locate(id); if (!at) return false;
  const before = JSON.stringify(layout.rows);
  const j = at.k + d;
  if (j >= 0 && j < at.col.mods.length) { [at.col.mods[at.k], at.col.mods[j]] = [at.col.mods[j], at.col.mods[at.k]]; }
  else if (at.row.cols.length === 1 && at.col.mods.length === 1) {
    const rj = at.ri + d; if (rj < 0 || rj >= layout.rows.length) return false;
    [layout.rows[at.ri], layout.rows[rj]] = [layout.rows[rj], layout.rows[at.ri]];
  } else {
    // 收藏墙那一排的列尾再往下 = 跑到无尽的墙下面去了：键盘不这样挪（真要放墙下面就拖）
    if (d > 0 && at.ri === boardIndex()) return false;
    const x = isBoardRow(at.row) ? 0 : at.col.x;
    const was = detachMod(id) || {};
    const ri = locate(at.row.cols.find(c => c.mods.length)?.mods[0])?.ri;
    const base = ri == null ? Math.min(at.ri, layout.rows.length) : ri;
    layout.rows.splice(d < 0 ? base : base + 1, 0, { cols: [{ x, w: isBoardRow(at.row) ? GRID : (was.w || GRID), mods: [id] }] });
  }
  layout.rows = normalizeRows(layout.rows);
  if (JSON.stringify(layout.rows) === before) return false;
  applyLayout(); saveLayout(); return true;
}
// ← / →：自由排里一次挪 1 格（碰到旁边那块就停）；墙那一排：挪进左 / 右边那一列（放在最后），那边没有列就在这一边开一列
function sideStep(id, d) {
  const at = locate(id); if (!at) return false;
  const before = JSON.stringify(layout.rows);
  if (!isBoardRow(at.row) && at.col.mods.length === 1) {
    const nb = at.row.cols[at.ci + d];
    const lo = at.ci > 0 ? at.row.cols[at.ci - 1].x + at.row.cols[at.ci - 1].w : 0, hi = (at.row.cols[at.ci + 1]?.x ?? GRID) - at.col.w;
    const nx = at.col.x + d;
    if (nx < lo || nx > hi) { if (!nb) return false; [at.row.cols[at.ci], at.row.cols[at.ci + d]] = [nb, at.col]; const a = at.row.cols[Math.min(at.ci, at.ci + d)], b = at.row.cols[Math.max(at.ci, at.ci + d)]; const x0 = Math.min(a.x, b.x); a.x = x0; b.x = x0 + a.w; }
    else at.col.x = nx;
  } else {
    const nb = at.row.cols[at.ci + d];
    if (nb) { detachMod(id); const again = locate(nb.mods[0]); again.col.mods.push(id); }
    else if (at.col.mods.length > 1) { at.col.mods.splice(at.k, 1); if (!splitCol(at.row, at.ci, d < 0 ? 'left' : 'right', id, at.col.w)) at.col.mods.splice(at.k, 0, id); }
    else return false;
  }
  layout.rows = normalizeRows(layout.rows);
  if (JSON.stringify(layout.rows) === before) return false;
  applyLayout(); saveLayout(); return true;
}
function setModHidden(id, hidden, { undo = true } = {}) {
  const g = modCfg(id); if (g.hidden === !!hidden) return;
  g.hidden = !!hidden;
  if (hidden && openPanel?.id === id) closePanel();
  if (hidden && selId === id) selId = '';
  applyLayout(); saveLayout();
  if (hidden) {
    if (undo) LB.undoNotice(`「${MOD_NAMES[id]}」放进备选了：内容和功能都还在，编排条上「备选」里点一下就回来`, async () => setModHidden(id, false, { undo: false }));
    if (arranging) paintTray();
  } else if (SIDE_MODS.includes(id)) { sideFold[id] = false; paintFold(id); paintMod(id); saveState(); }
}
// 调宽。墙那一排：第 j 列和第 j+1 列（都看得见的相邻两列）之间那道边，du 格（左正右负按第 j 列算）；
// 自由排：第 j 块的右边，du 格——往右最多到下一块的起点（或 48 格），往左最窄 MIN_W
function resizeCols(bi_, j, du) {
  const r = layout.rows[bi_]; if (!r) return false;
  const vis = r.cols.filter(c => visibleIn(c.mods)); const a = vis[j]; if (!a) return false;
  if (!isBoardRow(r)) {
    const i = r.cols.indexOf(a), lim = r.cols[i + 1]?.x ?? GRID;
    const n = Math.max(MIN_W - a.w, Math.min(lim - a.x - a.w, du)); if (!n) return false;
    a.w += n; a.fixed = true;
  } else {
    const b = vis[j + 1]; if (!b) return false;
    const n = Math.max(MIN_W - a.w, Math.min(b.w - MIN_W, du)); if (!n) return false;
    a.w += n; b.w -= n;
  }
  paintVisibility(); paintEdges();
  return true;
}

// ── 操作条（第一次进编排才建）：⠿（按住拖到任何位置；聚焦后方向键移动）· 名字 · 调整 · × ──
const bars = {};
function ensureBar(id) {
  const el = modEl(id); if (!el || bars[id]) return bars[id];
  const bar = document.createElement('div'); bar.className = 'lbc-mod-bar lbc-m-bar' + (TOP_IDS.includes(id) ? ' lbc-blk-bar' : '');
  el.insertBefore(bar, el.firstChild);
  const grip = bar.createEl('button', { cls: 'lbc-mb-h' }); grip.type = 'button'; grip.innerHTML = GRIP_SVG; grip.dataset.act = 'drag';
  grip.setAttribute('aria-label', `拖动「${MOD_NAMES[id]}」；方向键：上下换位置、左右换列`);
  grip.addEventListener('pointerdown', e => startModDrag(e, id, grip));
  grip.onkeydown = e => {
    const k = e.key; let done = false;
    if (k === 'ArrowUp' || k === 'ArrowDown') done = stepModule(id, k === 'ArrowUp' ? -1 : 1);
    else if (k === 'ArrowLeft' || k === 'ArrowRight') done = sideStep(id, k === 'ArrowLeft' ? -1 : 1);
    else return;
    e.preventDefault?.(); if (done) try { grip.focus({ preventScroll: false }); } catch {}
  };
  bar.createEl('span', { cls: 'lbc-mb-nm', text: MOD_NAMES[id] });
  bar.createEl('span', { cls: 'lbc-mb-sep' });
  // 1027b 她：「调整样式不方便」——字号、字体直接在操作条上：A− / A+ 一下一档（85 / 100 / 115 / 130 / 150%），「字体 ▾」弹一张单子点一下就换；
  // 别的设置还在「调整」里（和这里是同一份 g.font / g.size，改哪边另一边跟着）
  let sm = null, lg = null;
  if (id !== 'wall') {
    sm = bar.createEl('button', { cls: 'lbc-mb-sz', text: 'A−' }); sm.type = 'button'; sm.dataset.act = 'smaller';
    lg = bar.createEl('button', { cls: 'lbc-mb-sz', text: 'A+' }); lg.type = 'button'; lg.dataset.act = 'bigger';
    sm.onclick = e => { e?.stopPropagation?.(); stepSize(id, -1); };
    lg.onclick = e => { e?.stopPropagation?.(); stepSize(id, 1); };
  }
  const ft = bar.createEl('button', { text: '字体 ▾' }); ft.type = 'button'; ft.dataset.act = 'font'; ft.setAttribute('aria-haspopup', 'menu');
  ft.onclick = e => {
    e?.stopPropagation?.();
    const g = modCfg(id), r = ft.getBoundingClientRect?.() || { left: 0, bottom: 0 };
    popMenu(FONT_SET.map(([v, n]) => ({ title: n, checked: (g.font || '') === v, onClick: () => setModFont(id, v) })), e, ft, { x: r.left, y: r.bottom + 4 });
  };
  bar.createEl('span', { cls: 'lbc-mb-sep' });
  const adj = bar.createEl('button', { text: '调整' }); adj.type = 'button'; adj.dataset.act = 'adjust'; adj.setAttribute('aria-expanded', 'false');
  adj.onclick = e => { e?.stopPropagation?.(); togglePanel(id); };
  const x = bar.createEl('button', { text: '×' }); x.type = 'button'; x.dataset.act = 'remove';
  x.setAttribute('aria-label', `「${MOD_NAMES[id]}」放进备选`); x.title = '放进备选（编排条上点一下就回来）';
  x.onclick = e => { e?.stopPropagation?.(); setModHidden(id, true); };
  // 1027b 她：拉着虚线边框就改大小——下边框调高（边栏四块），左 / 右边框调宽（和旁边一列并排时；吸附 1/12，和列间竖线同一套）
  const rx = document.createElement('button'); rx.type = 'button'; rx.className = 'lbc-m-rs lbc-m-rs-x'; rx.hidden = true;
  rx.addEventListener('pointerdown', e => { const at = colPos(id); if (!at) return; e.stopPropagation?.(); startEdgeDrag(e, at.ri, at.edge, rx, at.host); });
  rx.onkeydown = e => { const at = colPos(id); if (!at || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return; e.preventDefault?.(); if (resizeCols(at.ri, at.edge, e.key === 'ArrowLeft' ? -1 : 1)) { saveLayout(); relayoutSoon(); } };
  el.append(rx);
  let ry = null;
  if (SIDE_MODS.includes(id)) {
    ry = document.createElement('button'); ry.type = 'button'; ry.className = 'lbc-m-rs lbc-m-rs-y';
    ry.setAttribute('aria-label', `调「${MOD_NAMES[id]}」的高度（上下键；双击 = 跟内容走）`); ry.title = '拖动调高度 · 双击恢复跟内容走';
    ry.addEventListener('pointerdown', e => startHeightDrag(e, id, ry));
    ry.ondblclick = e => { e?.stopPropagation?.(); setModHeight(id, 0, true); };
    ry.onkeydown = e => { if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return; e.preventDefault?.(); setModHeight(id, (modH(modOpt(id).h) || heightBox(id)) + (e.key === 'ArrowUp' ? -20 : 20), true); };
    el.append(ry);
  }
  bars[id] = { bar, grip, adj, x, rx, ry, sm, lg, ft };
  // 1028 积木：块的任何地方都能按住拖（按钮、输入框、链接、拉手除外——它们照常用）；点一下 = 选中
  el.addEventListener('pointerdown', e => {
    if (!arranging || (e.button != null && e.button !== 0)) return;
    const t = e.target;
    if (t && typeof t.closest === 'function' && t.closest('.lbc-mod-bar, .lbc-m-rs, .lbc-col-edge, .lbc-mp, input, textarea, select, a, [contenteditable="true"]')) return;
    e.stopPropagation?.();
    startModDrag(e, id, el, { soft: true });
  });
  paintBar(id);
  return bars[id];
}
function stepSize(id, d) {
  const g = modCfg(id); let i = SIZE_SET.indexOf(g.size);
  if (i < 0) i = Math.max(0, SIZE_SET.findIndex(n => n >= g.size));
  const n = SIZE_SET[Math.max(0, Math.min(SIZE_SET.length - 1, i + d))];
  if (n === g.size) return;
  g.size = n; if (!layout.cfg[id]) layout.cfg[id] = g;
  paintVisibility(); saveLayout(); relayoutSoon(); paintBar(id);
  if (openPanel?.id === id) refreshPanel();
}
function setModFont(id, v) {
  const g = modCfg(id); if ((g.font || '') === v) return;
  g.font = v; if (!layout.cfg[id]) layout.cfg[id] = g;
  paintVisibility(); saveLayout(); paintBar(id);
  if (openPanel?.id === id) refreshPanel();
}
// 这一块在哪一排、它右边（最后一列就左边）那条列边是第几条；不和别的列并排 → null
function colPos(id) {
  for (const c of edgeContainers()) {
    const j = c.vis.findIndex(col => col.mods.includes(id)); if (j < 0) continue;
    return { ri: c.ri, host: c.host, j, n: c.vis.length, edge: j < c.vis.length - 1 ? j : j - 1, left: j === c.vis.length - 1 };
  }
  return null;
}
function paintResizers() {
  for (const id of MOD_IDS) {
    const b = bars[id]; if (!b?.rx) continue;
    const at = arranging && !isGone(id) ? colPos(id) : null;
    b.rx.hidden = !at;
    if (at) { b.rx.classList.toggle('is-left', at.left); b.rx.setAttribute('aria-label', `调「${MOD_NAMES[id]}」的宽度（左右键）`); b.rx.title = '拖动调宽度'; }
  }
}
// 高度：拖的是内容框（最近导入 = 列表那一框）；松手存
const heightBox = id => { const el = modEl(id); const box = id === 'recent' ? el?.querySelector?.('.lbc-rec') || mods.recent?.body : mods[id]?.body; return Math.round(Number(box?.getBoundingClientRect?.().height) || 0); };
function setModHeight(id, h, save) {
  const g = modCfg(id); const v = h ? Math.max(80, modH(h) || 80) : 0;
  if ((g.opt.h || 0) === v) return;
  g.opt = { ...g.opt, h: v }; if (!layout.cfg[id]) layout.cfg[id] = g;
  paintVisibility(); sideFadeSoon();
  if (save) saveLayout();
}
let hDrag = null;
function startHeightDrag(e, id, el) {
  if (!arranging || (e.button != null && e.button !== 0)) return;
  e.preventDefault?.(); e.stopPropagation?.();
  if (sideFold[id]) { sideFold[id] = false; paintFold(id); paintMod(id); }
  hDrag = { id, y0: e.clientY, h0: modH(modOpt(id).h) || heightBox(id) || 200, el, pointer: e.pointerId, moved: false };
  try { el.setPointerCapture?.(e.pointerId); } catch {}
  el.classList.add('is-on');
}
docOn('pointermove', e => { if (!hDrag) return; const d = hDrag, h = Math.round(d.h0 + e.clientY - d.y0); if (Math.abs(e.clientY - d.y0) < 2 && !d.moved) return; d.moved = true; setModHeight(d.id, h, false); });
docOn('pointerup', () => { if (!hDrag) return; const d = hDrag; hDrag = null; try { d.el.releasePointerCapture?.(d.pointer); } catch {} d.el.classList.remove('is-on'); if (d.moved) saveLayout(); });
function paintBar(id) {
  const b = bars[id]; if (!b) return;
  if (b.sm) {
    const sz = modCfg(id).size;
    b.sm.disabled = sz <= SIZE_SET[0]; b.lg.disabled = sz >= SIZE_SET[SIZE_SET.length - 1];
    b.sm.title = b.lg.title = `字号 ${sz}%`;
    b.sm.setAttribute('aria-label', `「${MOD_NAMES[id]}」字小一档（现在 ${sz}%）`); b.lg.setAttribute('aria-label', `「${MOD_NAMES[id]}」字大一档（现在 ${sz}%）`);
  }
  if (b.ft) { const f = modCfg(id).font || ''; const nm = (FONT_SET.find(([v]) => v === f) || [f, f])[1]; b.ft.title = '字体：' + nm; b.ft.setAttribute('aria-label', `「${MOD_NAMES[id]}」字体（现在：${nm}）`); }
  b.adj.setAttribute('aria-expanded', String(openPanel?.id === id));
  modEl(id)?.classList.toggle('is-panel', openPanel?.id === id);
}

// ── 拖动（1028 积木）：按住块的任何地方（按钮、输入框除外）或 ⠿ 拖；挪不到 6px = 只是点了一下（选中），位置不动。
//    落点：页头 / 墙下面那几排的空地 = 就放在那儿（起点按指针算、靠近别的块的边就吸住，出一条对齐线）；排和排之间 = 单独成一排；
//    压在别的块上 = 和以前一样：左 / 右五分之一并排，其余上半放它上面、下半放它下面（收藏墙中间那一大片按左右半边算）。Esc 取消 ──
let drag = null;
const dropInd = (() => { const d = document.createElement('div'); d.className = 'lbc-drop-ind'; d.hidden = true; return d; })();
const guideEl = (() => { const d = document.createElement('div'); d.className = 'lbc-guide'; d.hidden = true; return d; })();
// 自由排（页头 / 墙下面）的 DOM 和布局：[{ri, row, el, rect}]
function freeRows() {
  const bi = boardIndex(), out = [];
  layout.rows.forEach((r, i) => {
    if (i === bi) return;
    const pool = i < bi ? topRowEls[i] : afterRowEls[i - bi - 1]; if (!pool || pool.el.hidden) return;
    const rect = pool.el.getBoundingClientRect?.(); if (!rect || !(rect.width > 0)) return;
    out.push({ ri: i, row: r, el: pool.el, rect });
  });
  return out;
}
// 所有自由排里块的左右边（格数），给吸附用；skip = 正在拖 / 拉的那一块
function snapEdges(skip) {
  const xs = new Set();
  for (const r of layout.rows) { if (isBoardRow(r)) { let x = 0; for (const c of r.cols) { if (visibleIn(c.mods)) { xs.add(x); xs.add(x + c.w); } x += c.w; } continue; }
    for (const c of r.cols) if (visibleIn(c.mods) && !c.mods.includes(skip)) { xs.add(c.x); xs.add(c.x + c.w); } }
  return [...xs];
}
const snapTo = (v, list, tol = 1) => { let best = null; for (const e of list) if (Math.abs(e - v) <= tol && (best == null || Math.abs(e - v) < Math.abs(best - v))) best = e; return best; };
function paintGuide(px) {
  if (px == null) { guideEl.hidden = true; return; }
  if (!guideEl.parentNode) wrap.append(guideEl);
  const wr = wrap.getBoundingClientRect?.() || { top: 0, height: 900 };
  guideEl.hidden = false; const s = guideEl.style; s.left = Math.round(px) + 'px'; s.top = Math.max(0, wr.top) + 'px'; s.height = Math.max(40, Math.min(wr.bottom ?? 900, typeof innerHeight === 'number' ? innerHeight : 900) - Math.max(0, wr.top)) + 'px';
}
function dropTarget(x, y, self) {
  // 1) 页头 / 墙下面的排：指针在某一排的高度里、底下没有别的块 → 放进这一排的空地；在两排之间 → 单独成一排
  const w = Math.max(MIN_W, locate(self)?.col?.w || 8);
  const rows = freeRows();
  for (const fr of rows) {
    const { rect } = fr;
    if (y < rect.top - 6 || y > rect.bottom + 6) continue;
    const over = (topRowEls[fr.ri]?.cols || afterRowEls[fr.ri - boardIndex() - 1]?.cols || []).some(n => { if (n.hidden || n.contains(modEl(self))) return false; const r = n.getBoundingClientRect?.(); return r && x >= r.left && x <= r.right; });
    if (over) break;
    const unit = rect.width / GRID;
    let gx = Math.round((x - (drag?.dx || 0) - rect.left) / unit);
    const edges = snapEdges(self);
    const sl = snapTo(gx, edges), sr = snapTo(gx + w, edges);
    let snap = null;
    if (sl != null) { gx = sl; snap = sl; } else if (sr != null) { gx = sr - w; snap = sr; }
    gx = Math.max(0, Math.min(GRID - w, gx));
    return { zone: 'slot', row: fr.row, x: gx, w, r: { left: rect.left + gx * unit, right: rect.left + (gx + w) * unit, top: rect.top, bottom: rect.bottom, width: w * unit, height: rect.height }, guide: snap == null ? null : rect.left + snap * unit };
  }
  if (rows.length) {
    const first = rows[0], last = rows[rows.length - 1], bi = boardIndex();
    const topRows = rows.filter(fr => fr.ri < bi);
    for (let k = 0; k + 1 < topRows.length; k++) {
      const a = topRows[k].rect, b = topRows[k + 1].rect;
      if (y > a.bottom + 6 && y < b.top - 6) return { zone: 'newrow', row: topRows[k].row, below: true, x: 0, w, r: { left: a.left, top: (a.bottom + b.top) / 2, width: a.width, height: 0, right: a.right, bottom: (a.bottom + b.top) / 2 } };
    }
    if (topRows.length && y < first.rect.top - 6 && y > first.rect.top - 60) return { zone: 'newrow', row: first.row, below: false, x: 0, w, r: { left: first.rect.left, top: first.rect.top - 8, width: first.rect.width, height: 0, right: first.rect.right, bottom: first.rect.top - 8 } };
    void last;
  }
  // 2) 压在别的块上：并排 / 上面 / 下面
  let best = null, bestD = Infinity;
  for (const id of MOD_IDS) {
    if (id === self || !present(id) || isGone(id)) continue;
    const el = modEl(id), r = el.getBoundingClientRect?.(); if (!r || !(r.width > 0)) continue;
    const dx = x < r.left ? r.left - x : x > r.right ? x - r.right : 0, dy = y < r.top ? r.top - y : y > r.bottom ? y - r.bottom : 0;
    const d_ = Math.hypot(dx, dy); if (d_ < bestD) { bestD = d_; best = { id, r }; }
  }
  if (!best || bestD > 80) return null;
  const { r } = best, rx = (x - r.left) / (r.width || 1);
  let zone;
  if (best.id === 'wall' && r.height > 240) zone = y < r.top + 80 ? 'before' : y > r.bottom - 80 ? 'after' : rx < 0.5 ? 'left' : 'right';
  else zone = rx < 0.2 ? 'left' : rx > 0.8 ? 'right' : y < r.top + r.height / 2 ? 'before' : 'after';
  return { id: best.id, zone, r };
}
function paintDrop(t) {
  if (!t) { dropInd.hidden = true; dropInd.classList.remove('is-slot'); paintGuide(null); return; }
  const { r, zone } = t, s = dropInd.style; dropInd.hidden = false;
  dropInd.classList.toggle('is-slot', zone === 'slot');
  if (zone === 'slot') { s.left = r.left + 'px'; s.top = r.top + 'px'; s.width = r.width + 'px'; s.height = Math.max(24, r.height) + 'px'; }
  else if (zone === 'left' || zone === 'right') { s.left = ((zone === 'left' ? r.left : r.right) - 2) + 'px'; s.top = Math.max(0, r.top) + 'px'; s.width = '4px'; s.height = Math.max(24, Math.min(r.bottom, (typeof innerHeight === 'number' ? innerHeight : 900)) - Math.max(0, r.top)) + 'px'; }
  else if (zone === 'newrow') { s.left = r.left + 'px'; s.top = (r.top - 2) + 'px'; s.width = r.width + 'px'; s.height = '4px'; }
  else { s.left = r.left + 'px'; s.top = ((zone === 'before' ? r.top - 12 : r.bottom + 8)) + 'px'; s.width = r.width + 'px'; s.height = '4px'; }
  paintGuide(t.guide ?? null);
}
function startModDrag(e, id, grip, { soft = false } = {}) {
  if (!arranging || (e.button != null && e.button !== 0)) return;
  if (!soft) e.preventDefault?.();   // 从块里面按下（soft）：不拦，点一下照常是点按钮；真拖了松手时吞掉那一下 click
  const er = modEl(id)?.getBoundingClientRect?.();
  drag = { id, grip, pointer: e.pointerId, target: null, raf: 0, x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, moved: false, dx: er ? e.clientX - er.left : 0 };
  try { grip.setPointerCapture?.(e.pointerId); } catch {}
  if (!dropInd.parentNode) wrap.append(dropInd);
}
function onDragMove(e) {
  if (!drag) return;
  drag.x = e.clientX; drag.y = e.clientY;
  if (!drag.moved && Math.hypot(drag.x - drag.x0, drag.y - drag.y0) < 6) return;   // 只是点了一下：不算拖（1028 她：「点一下 a，a 就跳到下面去了」）
  if (!drag.moved) { drag.moved = true; modEl(drag.id)?.classList.add('is-dragging'); }
  // 拖到上下边缘：滚动容器跟着滚
  const sc = LB.scroller(); const vh = typeof innerHeight === 'number' ? innerHeight : 900;
  if (sc) { if (e.clientY > vh - 60) sc.scrollTop += 18; else if (e.clientY < 80) sc.scrollTop -= 18; }
  if (drag.raf) return;
  const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : f => setTimeout(f, 16);
  drag.raf = raf(() => { if (!drag) return; drag.raf = 0; drag.target = dropTarget(drag.x, drag.y, drag.id); paintDrop(drag.target); }) || 1;
}
function endModDrag(cancel = false) {
  if (!drag) return;
  const d = drag; drag = null;
  try { d.grip.releasePointerCapture?.(d.pointer); } catch {}
  modEl(d.id)?.classList.remove('is-dragging'); paintDrop(null);
  if (!d.moved) { if (!cancel) selectMod(d.id); return; }
  // 真拖过：松手那一下 click 别落到块里的按钮上（不然拖完筛选条，顺手点了「视频」）
  if (typeof document !== 'undefined' && document.addEventListener) { const eat = ev => { ev.stopPropagation?.(); ev.preventDefault?.(); }; document.addEventListener('click', eat, true); setTimeout(() => document.removeEventListener('click', eat, true), 0); }
  const t = cancel ? null : (d.target || dropTarget(d.x, d.y, d.id));
  if (!t) return;
  if (t.zone === 'slot' || t.zone === 'newrow') moveModule(d.id, null, t.zone, { row: t.row, x: t.x, w: t.w, below: t.below });
  else moveModule(d.id, t.id, t.zone);
  selectMod(d.id);
}
function docOn(type, fn) { if (typeof document === 'undefined' || !document.addEventListener) return; document.addEventListener(type, fn); cleanups.push(() => { try { document.removeEventListener(type, fn); } catch {} }); }
const onDragUp = () => endModDrag(false), onDragCancel = () => endModDrag(true);
docOn('pointermove', onDragMove); docOn('pointerup', onDragUp); docOn('pointercancel', onDragCancel);

// ── 选中（1028）：编排时点一下块 = 选中，只有选中 / 指着的那块露出小工具条和拉手；点空白处取消 ──
let selId = '';
function selectMod(id) {
  if (selId === id) return;
  if (selId) modEl(selId)?.classList.remove('is-sel');
  selId = id && present(id) ? id : '';
  if (selId) modEl(selId)?.classList.add('is-sel');
}

// ── 调宽（编排时）：墙那一排 = 列与列之间的竖线；自由排 = 每块右边一道竖线。吸附到格子，靠近别的块的边就吸住（出对齐线）；聚焦后左右键 ──
const edgeEls = [];
function edgeContainers() {
  const bi = boardIndex(), out = [];
  layout.rows.forEach((r, i) => {
    const vis = r.cols.filter(c => visibleIn(c.mods));
    const free = i !== bi;
    if (!free && vis.length < 2) return;
    if (free && !vis.length) return;
    let host, nodes;
    if (i === bi) { host = board; nodes = boardColEls.filter(n => !n.hidden); }
    else { const pool = i < bi ? topRowEls[i] : afterRowEls[i - bi - 1]; if (!pool) return; host = pool.el; nodes = pool.cols.filter(n => !n.hidden); }
    out.push({ ri: i, host, nodes, vis, free });
  });
  return out;
}
function paintEdges() {
  // 重画前记下焦点在哪一道边上，画完放回去（键盘连按左右键调宽时不断）
  const ae = typeof document !== 'undefined' ? document.activeElement : null;
  const keep = ae && edgeEls.includes(ae) ? [ae.dataset.row, ae.dataset.edge] : null;
  try { paintEdgesNow(); } finally { if (keep) { const again = edgeEls.find(x => x.dataset.row === keep[0] && x.dataset.edge === keep[1]); try { again?.focus({ preventScroll: true }); } catch {} } }
}
function paintEdgesNow() {
  for (const e of edgeEls.splice(0)) e.remove();
  paintResizers();
  if (!arranging || !ENGINE || wrap.classList.contains('is-side-narrow')) return;
  for (const { ri, host, nodes, vis, free } of edgeContainers()) {
    const hr = host.getBoundingClientRect?.() || { left: 0 };
    const n = free ? nodes.length : nodes.length - 1;
    for (let j = 0; j < n; j++) {
      const a = nodes[j].getBoundingClientRect?.(), b = free ? null : nodes[j + 1].getBoundingClientRect?.();
      const ed = document.createElement('button'); ed.type = 'button'; ed.className = 'lbc-col-edge' + (free ? ' is-free' : '');
      ed.dataset.row = String(ri); ed.dataset.edge = String(j);
      const label = free ? `调宽「${vis[j].mods.map(id => MOD_NAMES[id]).join(' / ')}」：现在 ${vis[j].w}/48（左右键）` : `调宽：左边 ${vis[j].w}/48、右边 ${vis[j + 1].w}/48（左右键）`;
      ed.setAttribute('aria-label', label);
      const badge = document.createElement('span'); badge.className = 'lbc-ce-w'; badge.textContent = free ? `${vis[j].w}` : `${vis[j].w} / ${vis[j + 1].w}`; ed.append(badge);
      if (a && free) ed.style.left = Math.round(a.right - hr.left) + 'px';
      else if (a && b) ed.style.left = Math.round((a.right + b.left) / 2 - hr.left) + 'px';
      ed.onkeydown = e => { if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return; e.preventDefault?.(); if (resizeCols(ri, j, e.key === 'ArrowLeft' ? -1 : 1)) { saveLayout(); relayoutSoon(); const again = edgeEls.find(x => x.dataset.row === String(ri) && x.dataset.edge === String(j)); try { again?.focus(); } catch {} } };
      ed.addEventListener('pointerdown', e => startEdgeDrag(e, ri, j, ed, host));
      host.append(ed); edgeEls.push(ed);
    }
  }
}
let edgeDrag = null;
function startEdgeDrag(e, ri, j, ed, host) {
  if (!arranging || (e.button != null && e.button !== 0)) return;
  e.preventDefault?.();
  const r = layout.rows[ri], vis = r.cols.filter(c => visibleIn(c.mods)), free = !isBoardRow(r);
  const sum = free ? GRID : vis.reduce((n, c) => n + c.w, 0);
  const width = Number(host.getBoundingClientRect?.().width) || 1;
  edgeDrag = { ri, j, x0: e.clientX, a0: vis[j].w, unit: width / sum, applied: 0, ed, pointer: e.pointerId, free, left: host.getBoundingClientRect?.().left || 0 };
  try { ed.setPointerCapture?.(e.pointerId); } catch {}
  ed.classList.add('is-on');
}
function onEdgeMove(e) {
  if (!edgeDrag) return;
  const d = edgeDrag;
  let want = Math.round((e.clientX - d.x0) / d.unit);
  const vis = layout.rows[d.ri].cols.filter(c => visibleIn(c.mods));
  const a = vis[d.j]; if (!a) return;
  // 吸附：拉的这条边离别的块的左 / 右边 1 格以内就吸过去（墙那一排按累计宽度算）
  const x0 = d.free ? a.x : vis.slice(0, d.j).reduce((n, c) => n + c.w, 0);
  const snap = snapTo(x0 + d.a0 + want, snapEdges(a.mods[0]).filter(v => v > x0));
  if (snap != null) want = snap - x0 - d.a0;
  paintGuide(snap == null ? null : d.left + snap * d.unit);
  const du = want - d.applied;
  if (!du) return;
  const before = a.w;
  if (resizeCols(d.ri, d.j, du)) { d.applied += a.w - before; d.ed = edgeEls.find(x => x.dataset.row === String(d.ri) && x.dataset.edge === String(d.j)) || d.ed; d.ed.classList.add('is-on'); }
}
function endEdgeDrag() {
  if (!edgeDrag) return;
  const d = edgeDrag; edgeDrag = null;
  try { d.ed.releasePointerCapture?.(d.pointer); } catch {}
  d.ed.classList.remove('is-on'); paintGuide(null);
  if (d.applied) { saveLayout(); relayoutSoon(); }
}
docOn('pointermove', onEdgeMove); docOn('pointerup', endEdgeDrag);
let relayoutTimer = null;
function relayoutSoon() { clearTimeout(relayoutTimer); relayoutTimer = setTimeout(() => { if (pageReady) { laidN = 0; relayoutIfNeeded(); paintStickyTop(); paintEdges(); } }, 60); }
cleanups.push(() => clearTimeout(relayoutTimer));

// ── 「调整」：在模块里展开（一次只开一个；改了马上生效、后台存；输入框不因为保存 / 后台重跑被重建） ──
let openPanel = null;
function closePanel() {
  if (!openPanel) return;
  const p = openPanel; openPanel = null;
  try { p.destroy?.(); } catch {}
  p.el.remove();
  paintBar(p.id);
}
function togglePanel(id) { if (openPanel?.id === id) { closePanel(); return; } closePanel(); openPanel = buildPanel(id); paintBar(id); paintSaveState(); }
function refreshPanel() { if (!openPanel) return; const id = openPanel.id; closePanel(); openPanel = buildPanel(id); paintBar(id); paintSaveState(); }
function mkSelect(parent, choices, value, onChange, label) {
  const s = parent.createEl('select'); if (label) s.setAttribute('aria-label', label);
  for (const [v, t] of choices) { const o = s.createEl('option', { text: t }); o.value = String(v); }
  s.value = String(value);
  s.onchange = () => onChange(s.value);
  return s;
}
function mkRow(box, k) { const r = box.createEl('div', { cls: 'lbc-mp-row' }); if (k) r.createEl('span', { cls: 'lbc-mp-k', text: k }); return r; }
function buildPanel(id) {
  const host = modEl(id), bar = bars[id]?.bar;
  const box = document.createElement('div'); box.className = 'lbc-mp'; box.dataset.panel = id;
  host.insertBefore(box, bar ? bar.nextSibling : host.firstChild);
  const h = box.createEl('div', { cls: 'lbc-mp-h' });
  h.createEl('span', { text: MOD_NAMES[id] + ' · 调整' });
  h.createEl('span', { cls: 'lbc-mp-save' });
  const g = modCfg(id);
  const p = provider();
  const panel = { id, el: box, destroy: null };
  // 字体 / 字号（全站的在托盘「Aa 样式」里；这里是这一块自己的）
  const r1 = mkRow(box, '字体');
  const fonts = FONT_SET.some(([v]) => v === g.font) ? FONT_SET : [...FONT_SET, [g.font, g.font]];
  mkSelect(r1, fonts, g.font, v => { g.font = v; paintVisibility(); saveLayout(); }, MOD_NAMES[id] + '字体').dataset.k = 'font';
  if (id !== 'wall') {
    r1.createEl('span', { cls: 'lbc-mp-k', text: '字号' });
    mkSelect(r1, SIZE_SET.map(n => [n, n + '%']), g.size, v => { g.size = sizeOf(v); paintVisibility(); saveLayout(); relayoutSoon(); }, MOD_NAMES[id] + '字号').dataset.k = 'size';
  }
  // 这个模块自己的设置
  const body = box.createEl('div', { cls: 'lbc-mp-body' });
  panelBody[id]?.(body, g, p, panel);
  // 上下左右（键盘 / 不想拖的时候）
  const mv = mkRow(box, '位置');
  const mb = (t, act, fn) => { const b = mv.createEl('button', { text: t }); b.type = 'button'; b.dataset.act = act; b.onclick = e => { e?.stopPropagation?.(); fn(); }; return b; };
  mb('↑ 上移', 'up', () => stepModule(id, -1)); mb('↓ 下移', 'down', () => stepModule(id, 1));
  mb('← 左移', 'left', () => sideStep(id, -1)); mb('→ 右移', 'right', () => sideStep(id, 1));
  mb('收起', 'close', () => closePanel());
  return panel;
}
const panelBody = {
  title(body, g, p) {
    const r = mkRow(body, '标题');
    const inp = r.createEl('input', { type: 'text' }); inp.dataset.k = 'title';
    inp.placeholder = '留空 = 默认标题'; inp.maxLength = 40; inp.value = String(p?.settings?.catalogTitle || '');
    inp.addEventListener('input', () => {
      if (!p?.settings) return;
      p.settings.catalogTitle = inp.value.trim().slice(0, 40);
      setTitle(); saveSettingSoon('catalogTitle');
    });
    body.createEl('p', { cls: 'lbc-mp-note', text: '留空 = 默认标题。问收藏页的标题同一个。' });
  },
  cats(body) {
    if (!idx) {
      body.createEl('p', { cls: 'lbc-mp-note', text: '分类在 索引.md 里（还没生成索引）：' });
      const b = mkRow(body).createEl('button', { text: '打开 索引.md' }); b.type = 'button'; b.onclick = () => editCategories();
      return;
    }
    const hidden = new Set(provider()?.settings?.hiddenCats || []);
    const list = body.createEl('div', { cls: 'lbc-mp-cats' });
    const roots = idx.roots || [];
    roots.forEach((path, i) => {
      const n = idxByPath.get(path); if (!n) return;
      const row = list.createEl('div', { cls: 'lbc-mp-cat' }); row.dataset.path = path;
      const ck = row.createEl('input', { type: 'checkbox' }); ck.checked = !hidden.has(n.name); ck.setAttribute('aria-label', `分类行里显示「${n.name}」`); ck.dataset.k = 'show';
      ck.onchange = () => {
        const q = provider(); if (!q?.settings) return;
        const set = new Set(q.settings.hiddenCats || []); if (ck.checked) set.delete(n.name); else set.add(n.name);
        q.settings.hiddenCats = [...set]; renderCatBar(); saveSettingSoon('hiddenCats');
      };
      const name = row.createEl('input', { type: 'text' }); name.value = n.name; name.maxLength = 60; name.dataset.k = 'name'; name.setAttribute('aria-label', `给「${n.name}」改名`);
      const commit = async () => { const v = name.value.trim(); if (!v || v === n.name) { name.value = n.name; return; } name.disabled = true; const r = await treeEdit('rename', n, { name: v }); name.disabled = false; if (!r?.ok) name.value = v; else refreshPanel(); };
      name.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault?.(); commit(); } else if (e.key === 'Escape') { e.stopPropagation?.(); name.value = n.name; } };
      name.onchange = () => commit();
      row.createEl('span', { cls: 'lbc-mp-n', text: String(n.count || 0) });
      const up = row.createEl('button', { text: '↑' }); up.type = 'button'; up.dataset.act = 'cat-up'; up.disabled = i === 0; up.setAttribute('aria-label', `「${n.name}」往前`);
      const dn = row.createEl('button', { text: '↓' }); dn.type = 'button'; dn.dataset.act = 'cat-down'; dn.disabled = i === roots.length - 1; dn.setAttribute('aria-label', `「${n.name}」往后`);
      up.onclick = async () => { const r = await treeEdit('move', n, { to: '', before: roots[i - 1] }); if (r?.ok) refreshPanel(); };
      dn.onclick = async () => { const r = await treeEdit('move', n, { to: '', before: roots[i + 2] || '' }); if (r?.ok) refreshPanel(); };
    });
    const add = mkRow(body, '加一个');
    const inp = add.createEl('input', { type: 'text' }); inp.placeholder = '新分类名'; inp.maxLength = 60; inp.dataset.k = 'new';
    const go = add.createEl('button', { text: '＋ 加分类' }); go.type = 'button'; go.dataset.act = 'cat-add';
    const doAdd = async () => {
      const v = inp.value.trim(); if (!v) { inp.focus?.(); return; }
      go.disabled = true;
      const r = await indexAction('indexEdit', null, '正在改索引…', 'add', '', { name: v });
      go.disabled = false;
      if (r?.ok) { inp.value = ''; await treeEditDone(r); refreshPanel(); } else if (r) LB.say(r.message || '没加上', { kind: 'error' });
    };
    go.onclick = () => doAdd();
    inp.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault?.(); doAdd(); } };
    const more = mkRow(body);
    const tree = more.createEl('button', { text: '分类树（子类、合并、拖拽）→' }); tree.type = 'button'; tree.onclick = () => { setArranging(false); openIndexEditor(); };
    body.createEl('p', { cls: 'lbc-mp-note', text: '改名 / 换顺序 / 加分类都写回 索引.md（能撤销）；取消勾选只是分类行里不显示，帖子不动。删除分类在「管理」里。' });
  },
  recent(body, g) {
    // 1027b 条数 = 列表框高几条（其余在框里滚）；改的时候折着就展开，马上看得到
    mkSelect(mkRow(body, '框高'), OPT_CHOICES.recent.count.map(n => [n, n + ' 条']), g.opt.count, v => { g.opt.count = Number(v); if (sideFold.recent) { sideFold.recent = false; paintFold('recent'); saveState(); } mods.recent && (mods.recent.sig = null); paintRecent(); saveLayout(); }, '最近导入列表框高几条').dataset.k = 'count';
  },
  sync(body, g, p, panel) {
    // 同步时间只有一个编辑器（schedule-ui 的 render，设置页「收藏与同步」、首次设置用的同一个）：嵌在这里，保存 = 真去改计划任务，结果照实说
    const holder = body.createEl('div', { cls: 'lbc-mp-sched' });
    if (p && typeof p.scheduleUI === 'function') {
      try {
        const ed = p.scheduleUI().render(holder, { primary: false, onSaved: () => loadSchedule({ force: true }) });
        panel.destroy = () => { try { ed.destroy(); } catch {} };
        return;
      } catch (e) { holder.empty(); holder.createEl('p', { cls: 'lbc-mp-note is-fail', text: '同步时间编辑器没画上：' + (e?.message || e) }); }
    }
    const b = mkRow(body).createEl('button', { text: '改同步时间（设置 · 收藏与同步）' }); b.type = 'button'; b.onclick = () => openSyncSettings();
  },
  token(body, g, p) {
    mkSelect(mkRow(body, '显示'), TOKEN_PERIODS.map(([k, , long]) => [k, long]), g.opt.period, v => setTokenPeriod(v), 'Token 费用显示哪一段').dataset.k = 'period';
    const r = mkRow(body, '后台每日上限 ¥');
    const inp = r.createEl('input', { type: 'number' }); inp.min = '0'; inp.step = '1'; inp.dataset.k = 'budget'; inp.setAttribute('aria-label', '后台每日费用上限（元，0 = 不限）');
    const cur = p?.settings?.budget?.dailyYuan; inp.value = cur === undefined || cur === '' || cur == null ? '' : String(cur);
    inp.placeholder = usage?.budget && Number.isFinite(+usage.budget.daily_yuan) ? String(+usage.budget.daily_yuan) : '默认';
    const note = body.createEl('p', { cls: 'lbc-mp-note', text: '每天（北京时间）花到这个数，夜里补识图、补概要就只用免费的；你自己问收藏不受限。0 = 不限。和设置页「AI」里是同一个。' });
    inp.onchange = () => {
      const err = setBudget(inp.value);
      if (err) { note.textContent = err; note.classList.add('is-fail'); return; }
      note.classList.remove('is-fail');
    };
  },
  overview(body, g) {
    const r = mkRow(body, '显示');
    const NAMES = { all: '全部收藏', week: '近 7 天', star: '已收藏', cats: '在用分类', bars: '近 14 天柱图' };
    for (const k of OPT_CHOICES.overview.metrics) {
      const l = r.createEl('label', { cls: 'lbc-mp-ck' }); const ck = l.createEl('input', { type: 'checkbox' }); ck.checked = g.opt.metrics.includes(k); ck.dataset.k = k; l.append(NAMES[k]);
      ck.onchange = () => { const set = new Set(g.opt.metrics); if (ck.checked) set.add(k); else set.delete(k); g.opt.metrics = OPT_CHOICES.overview.metrics.filter(x => set.has(x)); mods.overview && (mods.overview.sig = null); paintOverview(); saveLayout(); };
    }
  },
  wall(body, g, p) {
    const r = mkRow(body, '每行');
    mkSelect(r, [[0, '自动'], [2, '2 列'], [3, '3 列'], [4, '4 列'], [5, '5 列'], [6, '6 列']], cols || 0, v => {
      const n = colsOf(v); cols = n; applyCols(); saveState();
      const q = provider(); if (q?.settings) { q.settings.catalogColumns = n; saveSettingSoon('catalogColumns'); }
      laidN = 0; relayoutIfNeeded();
    }, '收藏墙每行几列').dataset.k = 'cols';
    r.createEl('span', { cls: 'lbc-mp-k', text: '密度' });
    mkSelect(r, [['s', '紧凑（多一列）'], ['m', '标准'], ['l', '宽松（少一列）']], g.opt.density, v => { g.opt.density = v; saveLayout(); laidN = 0; relayoutIfNeeded(); }, '卡片密度').dataset.k = 'density';
    body.createEl('p', { cls: 'lbc-mp-note', text: '在目录页上按 Ctrl + 加号 / 减号、Ctrl + 滚轮也能调列数（同一个设置）。密度只在「自动」时起作用。' });
    void p;
  },
};

// ── Token 费用（1027 从同步模块拆出来）：本月 = 目录数据里的 usage_month（不起进程）；今天 = 插件跑一次 usage（60 秒内复用） ──
let usage = null, usageAt = 0, usageBusy = false, usageErr = '';
async function loadUsage({ force = false } = {}) {
  const p = provider();
  if (!p || typeof p.runPy !== 'function' || usageBusy || mobile) return;
  if (!force && usageAt && Date.now() - usageAt < 60000) return;
  usageBusy = true;
  try { const r = await p.runPy(['-m', 'link_brain', 'usage'], { label: '读 AI 用量', timeoutMs: 45000, fallback: '没读出来' }); if (!r?.json || r.json.ok === false) throw new Error(r?.json?.message || '没读出来'); usage = r.json; usageErr = ''; }
  catch (e) { usageErr = e?.message || String(e); }
  finally { usageBusy = false; usageAt = Date.now(); }
  if (mods.token) mods.token.sig = null;
  paintToken();
}
const yuan = v => (v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v)) ? '¥' + Number(v).toFixed(2) : '—');
// 1027b 她：费用能在块里直接切 天 / 周 / 月；周 = 近 7 天（usage summary 的 7d 窗口，和设置页「用量」同一口径）
const TOKEN_PERIODS = [['day', '天', '今天（北京时间）'], ['week', '周', '近 7 天'], ['month', '月', '本月（人民币估算）']];
function setTokenPeriod(v) {
  const g = modCfg('token'); if (!TOKEN_PERIODS.some(([k]) => k === v) || g.opt.period === v) return;
  g.opt.period = v; if (mods.token) mods.token.sig = null; paintToken(); saveLayout();
}
// 后台每日上限：'' = 默认（删掉 dailyYuan）；返回错误文字或 ''
function setBudget(raw) {
  const q = provider(); if (!q?.settings) return '插件没开，改不了';
  raw = String(raw ?? '').trim();
  if (raw === '') { const b = { ...(q.settings.budget || {}) }; delete b.dailyYuan; q.settings.budget = b; }
  else { const n = Math.round(Number(raw) * 100) / 100; if (!Number.isFinite(n) || n < 0) return '上限要是 0 或正数（0 = 不限），还没改'; q.settings.budget = { ...(q.settings.budget || {}), dailyYuan: n }; }
  if (mods.token) mods.token.sig = null; paintToken(); saveSettingSoon('budget');
  return '';
}
const CAP_CHOICES = [0, 1, 2, 3, 5, 10, 20, 50];
function paintToken() {
  const m = mods.token; if (!m) return;
  const p = provider(), period = TOKEN_PERIODS.some(([k]) => k === modOpt('token').period) ? modOpt('token').period : 'month';
  const um = data?.usage_month || {};
  const capSet = p?.settings?.budget?.dailyYuan;
  const capIsSet = capSet !== undefined && capSet !== '' && capSet != null;
  const cap = capIsSet ? Number(capSet) : (usage?.budget && Number.isFinite(+usage.budget.daily_yuan) ? +usage.budget.daily_yuan : null);
  const capText = cap == null || !Number.isFinite(cap) ? '默认' : cap > 0 ? '¥' + cap : '不限';
  const wk = usage?.summary?.windows?.['7d']?.total;
  const val = period === 'month' ? (um.cost_cny ?? null) : period === 'week' ? (wk ? wk.cost : null) : (usage?.budget ? usage.budget.spent_today : null);
  const pname = { day: '今天 ', week: '近 7 天 ', month: '本月 ' }[period];
  setSum(m, [pname, [val == null ? '—' : '约 ' + yuan(val)], ' · 上限 ' + capText]);
  if (period !== 'month' && !usage && !usageAt) loadUsage();
  if (sideFold.token) return;
  const sig = JSON.stringify([period, val, capText, capIsSet, usageBusy, usageErr, um.month, um.unpriced, um.by_feature, !!p]);
  if (m.sig === sig) return; m.sig = sig;
  const b = m.body; b.empty();
  // 天 / 周 / 月：块里一排小字切换（和「调整」里的同一个设置）
  const seg = b.createEl('div', { cls: 'lbc-tk-seg', attr: { role: 'tablist', 'aria-label': '费用看哪一段' } });
  for (const [k, short, long] of TOKEN_PERIODS) {
    const t = seg.createEl('button', { cls: k === period ? 'is-on' : '', text: short }); t.type = 'button'; t.dataset.period = k; t.title = long;
    t.setAttribute('role', 'tab'); t.setAttribute('aria-selected', String(k === period));
    t.onclick = e => { e?.stopPropagation?.(); setTokenPeriod(k); };
  }
  const big = b.createEl('div', { cls: 'lbc-sy-big lbc-tk-big' });
  if (val == null) big.setText('—'); else { big.append('¥ '); big.createEl('i', { text: Number(val).toFixed(2) }); }
  b.createEl('div', { cls: 'lbc-sy-cap lbc-tk-cap' }).createEl('span', { text: period === 'month' ? `${um.month || '本月'} · 人民币估算` : period === 'week' ? '近 7 天 · 人民币估算' : '今天（北京时间）· 人民币估算' });
  // 后台每日上限：直接下拉改（和设置「AI」、「调整」里是同一个 budget.dailyYuan）
  const r = b.createEl('div', { cls: 'lbc-sy-row lbc-tk-cap-row' }); r.createEl('span', { text: '后台每日上限' });
  r.title = '每天（北京时间）花到这个数，夜里补识图、补概要就只用免费的；你自己问收藏不受限。';
  if (p?.settings && !mobile) {
    const dflt = usage?.budget && Number.isFinite(+usage.budget.daily_yuan) && !capIsSet ? +usage.budget.daily_yuan : null;
    const opts = [['', dflt != null ? `默认（¥${dflt}）` : '默认'], ...CAP_CHOICES.map(n => [String(n), n ? '¥' + n : '不限'])];
    if (capIsSet && !CAP_CHOICES.includes(Number(capSet))) opts.push([String(capSet), '¥' + capSet]);
    const sel = r.createEl('select', { cls: 'lbc-tk-capsel' }); sel.setAttribute('aria-label', '后台每日费用上限');
    for (const [v, t] of opts) sel.createEl('option', { value: v, text: t });
    sel.value = capIsSet ? String(capSet) : '';
    sel.onclick = e => e?.stopPropagation?.();
    sel.onchange = () => {
      const v = sel.value;   // 别的数（比如 ¥4）在「编排 → Token 费用 → 调整」里填
      const err = setBudget(v);
      if (err) { LB.say(err, { kind: 'error' }); sel.value = capIsSet ? String(capSet) : ''; }
    };
  } else r.createEl('b', { text: capText });
  if (period === 'month') {
    const bf = um.by_feature || {};
    if (val == null) b.createEl('p', { cls: 'lbc-sy-note', text: '还没有用量记录' });
    else big.title = [`${um.month || '本月'} 调用 AI 的估算费用（人民币，按价格表 ${um.as_of || ''} 现价）${um.unpriced ? `（${um.unpriced} 次没有价格表，没算进去）` : ''}`, ...Object.keys(bf).map(k => `${k} ¥${Number(bf[k]).toFixed(2)}`)].join('\n');
  } else if (usageBusy && !usage) b.createEl('p', { cls: 'lbc-sy-note', text: '正在读用量…' });
  else if (usageErr && !usage) b.createEl('p', { cls: 'lbc-sy-note', text: '读不到用量：' + usageErr });
  else if (!p) b.createEl('p', { cls: 'lbc-sy-note', text: mobile ? LB.MOBILE_ONLY_TEXT : '插件没开：看不到今天 / 近 7 天的用量' });
  else if (usage?.budget?.over) b.createEl('p', { cls: 'lbc-sy-note', text: '今天到上限了：后台补跑先只用免费的，北京时间明天 0 点恢复。' });
}

// ── 存过的样式（1028 她：「存好了作为样式锁定。可以恢复默认 or 恢复样式 1（自己定名字）」）：插件设置 catalogStyles = [{name, layout}]、catalogStyleCur = 当前那个 ──
function stylesList() { const v = provider()?.settings?.catalogStyles; return Array.isArray(v) ? v.filter(x => x && typeof x.name === 'string' && x.name.trim()) : []; }
const curStyleName = () => String(provider()?.settings?.catalogStyleCur || '');
const sameLayout = L => JSON.stringify(parseLayout(L && typeof L === 'object' ? clone(L) : null)) === JSON.stringify(layout);
function styleDirty() { const st = stylesList().find(x => x.name === curStyleName()); return st ? !sameLayout(st.layout) : !!curStyleName(); }
function nextStyleName(list) { let n = list.length + 1; while (list.some(x => x.name === '样式 ' + n)) n++; return '样式 ' + n; }
// 存：当前有名字就存回那一个，没有就新起一个「样式 N」；存完锁住（退出编排）
function saveStyle({ asNew = false } = {}) {
  const p = provider(); if (!p?.settings) return;
  const list = stylesList().map(x => ({ ...x }));
  let name = asNew ? '' : curStyleName();
  const L = clone(layoutToSetting() || {});
  const st = name && list.find(x => x.name === name);
  if (st) st.layout = L; else { name = nextStyleName(list); list.push({ name, layout: L }); }
  p.settings.catalogStyles = list; p.settings.catalogStyleCur = name;
  saveSettingSoon('catalogStyles', 'catalogStyleCur');
  setArranging(false);
  LB.say(`存好了：「${name}」，已锁定（点「编排」再改）`, { kind: 'ok' });
}
// 换：name 空 = 恢复默认
function applyStyle(name) {
  const p = provider();
  const st = name ? stylesList().find(x => x.name === name) : null;
  if (name && !st) return;
  closePanel(); selectMod('');
  layout = parseLayout(st ? clone(st.layout) : null);
  if (p?.settings) p.settings.catalogStyleCur = st ? name : '';
  applyLayout(); saveLayout(); saveSettingSoon('catalogStyleCur');
  if (arranging) paintTray();
  LB.say(st ? `换成了「${name}」` : '目录页已恢复默认布局（标题、列数、分类、同步时间不受影响）', { kind: 'ok' });
}
function renameStyle(old, nu) {
  const p = provider(); nu = String(nu || '').trim().slice(0, 24);
  if (!p?.settings || !nu || nu === old) return false;
  const list = stylesList().map(x => ({ ...x }));
  if (list.some(x => x.name === nu)) { LB.say(`已经有一个叫「${nu}」的样式了`, { kind: 'warn' }); return false; }
  const st = list.find(x => x.name === old); if (!st) return false;
  st.name = nu; p.settings.catalogStyles = list;
  if (curStyleName() === old) p.settings.catalogStyleCur = nu;
  saveSettingSoon('catalogStyles', 'catalogStyleCur'); paintTray(); return true;
}
function deleteStyle(name) {
  const p = provider(); if (!p?.settings) return;
  const before = stylesList();
  p.settings.catalogStyles = before.filter(x => x.name !== name);
  const wasCur = curStyleName() === name; if (wasCur) p.settings.catalogStyleCur = '';
  saveSettingSoon('catalogStyles', 'catalogStyleCur'); paintTray();
  LB.undoNotice(`删了样式「${name}」（页面现在的样子不变）`, async () => { p.settings.catalogStyles = before; if (wasCur) p.settings.catalogStyleCur = name; saveSettingSoon('catalogStyles', 'catalogStyleCur'); paintTray(); });
}
// 改名：样式名那颗按钮就地变成输入框，回车确定、Esc 放弃
function editStyleName(btn, name) {
  const inp = document.createElement('input'); inp.type = 'text'; inp.className = 'lbc-at-rename'; inp.value = name; inp.maxLength = 24; inp.setAttribute('aria-label', '样式名字');
  btn.replaceWith(inp); try { inp.focus(); inp.select(); } catch {}
  let done = false;
  const end = ok => { if (done) return; done = true; if (!(ok && renameStyle(name, inp.value))) paintTray(); };
  inp.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault?.(); end(true); } else if (e.key === 'Escape') { e.preventDefault?.(); e.stopPropagation?.(); end(false); } };
  inp.onblur = () => end(true);
}

// ── 编排条（编排时在页头上面）：ARRANGE · 备选（× 掉的块，点一下回来）· Aa 样式 · 样式 ▾ · 存为样式 · 保存状态 · 完成 ──
let trayStyleOpen = false;
function paintTray() {
  if (!arrangeTray) return;
  const ae = document.activeElement, focusKey = ae && arrangeTray.contains(ae) ? (ae.dataset?.act || ae.dataset?.show || ae.dataset?.theme || '') : '';
  arrangeTray.empty();
  arrangeTray.createEl('span', { cls: 'lbc-at-k', text: 'ARRANGE' });
  const btn = (parent, text, attrs = {}, cls = '') => { const b = parent.createEl('button', { cls, text }); b.type = 'button'; for (const [k, v] of Object.entries(attrs)) b.dataset[k] = v; return b; };
  // 备选：移除了的块都在这里（虚线小胶囊），点一下回到原来的位置
  const shelf = arrangeTray.createEl('div', { cls: 'lbc-at-shelf', attr: { 'aria-label': '备选' } });
  shelf.createEl('span', { cls: 'lbc-at-sk', text: '备选' });
  const off = MOD_IDS.filter(id => present(id) && modCfg(id).hidden);
  if (!off.length) shelf.createEl('span', { cls: 'lbc-at-empty', text: '空（× 掉的块会放在这里）' });
  for (const id of off) { const b = btn(shelf, '＋ ' + MOD_NAMES[id], { show: id }, 'is-dash'); b.onclick = () => { setModHidden(id, false); selectMod(id); }; }
  const styleB = btn(arrangeTray, 'Aa 样式', { act: 'style' }); styleB.setAttribute('aria-expanded', String(trayStyleOpen));
  styleB.onclick = () => { trayStyleOpen = !trayStyleOpen; paintTray(); };
  // 样式 ▾：恢复默认 · 存过的每一个（点了换过去）· 改名 · 删掉
  const cur = curStyleName(), dirty = styleDirty();
  const pickB = btn(arrangeTray, `样式：${cur || '默认'}${dirty ? '（改过）' : ''} ▾`, { act: 'styles' }); pickB.setAttribute('aria-haspopup', 'menu');
  pickB.onclick = e => {
    const list = stylesList();
    popMenu([
      { title: '恢复默认', checked: !cur, onClick: () => applyStyle('') },
      ...(list.length ? [{ separator: true }] : []),
      ...list.map(st => ({ title: st.name, checked: st.name === cur, onClick: () => applyStyle(st.name) })),
      ...(cur ? [{ separator: true }, { title: `给「${cur}」改名`, onClick: () => { const again = arrangeTray.querySelector('[data-act="styles"]'); if (again) editStyleName(again, cur); } },
        { title: `删掉「${cur}」`, onClick: () => deleteStyle(cur) }] : []),
      ...(cur ? [{ title: '另存为新样式', onClick: () => saveStyle({ asNew: true }) }] : []),
    ], e, pickB);
  };
  const saveB = btn(arrangeTray, cur ? (dirty ? `存回「${cur}」` : '存好了') : '存为样式', { act: 'save-style' });
  saveB.title = '存下现在的样子，存完锁住（不会误拖）；点「编排」再改';
  saveB.onclick = () => saveStyle();
  arrangeTray.createEl('span', { cls: 'lbc-at-save' });
  const retry = btn(arrangeTray, '重试', { act: 'retry' }); retry.hidden = true; retry.onclick = () => flushSave();
  const done = btn(arrangeTray, '完成', { act: 'done' }, 'is-solid'); done.onclick = () => setArranging(false);
  // Aa 样式：全站三套字 + 界面大小 + 卡片间距（共享令牌，问收藏 / 笔记页用同一组）
  const st = arrangeTray.createEl('div', { cls: 'lbc-at-row lbc-at-style' }); st.hidden = !trayStyleOpen;
  const t = layout.theme;
  const pick = (label, key, choices) => {
    const l = st.createEl('label', { text: label });
    const opts = choices.some(([v]) => String(v) === String(t[key])) ? choices : [...choices, [t[key], String(t[key])]];
    const s = mkSelect(l, opts, t[key], v => { t[key] = typeof THEME_DEFAULT[key] === 'number' ? Number(v) : v; layout.theme = cleanTheme(t); applyThemeNow(); saveLayout(); if (key === 'gap' || key === 'scale') relayoutSoon(); paintTray(); }, label);
    s.dataset.theme = key;
  };
  pick('标题字', 'titleFont', FONT_SET.map(([v, n]) => [v, v ? n : '默认（Cinzel 雕刻）']));
  pick('正文字', 'bodyFont', FONT_SET.map(([v, n]) => [v, v ? n : '默认（思源黑体）']));
  pick('数字', 'numberFont', FONT_SET.map(([v, n]) => [v, v ? n : '默认（Cormorant 斜体）']));
  pick('界面大小', 'scale', SCALE_SET);
  pick('卡片间距', 'gap', GAP_SET);
  arrangeTray.createEl('div', { cls: 'lbc-at-hint', text: '按住一块拖到任何位置：放进空地 = 就在那儿，压在别的块左右 = 并排，排与排之间 = 单独一排；靠近别的块的边会吸住。拉块右边的竖线调宽，点标题字直接改。× 放进备选。改了马上生效、自动保存；「存为样式」存下来并锁住。只在电脑上。' });
  paintSaveState();
  if (focusKey) { const again = [...arrangeTray.querySelectorAll('button, select')].find(b => (b.dataset?.act || b.dataset?.show || b.dataset?.theme || '') === focusKey); try { again?.focus({ preventScroll: true }); } catch {} }
}
// ── 标题：编排时点一下标题字就地改（回车确定、Esc 放弃；空 = 默认标题），和「管理 → 改标题」是同一个 catalogTitle ──
function editTitleInline() {
  const p = provider(); if (!p?.settings || titleLabel.isContentEditable) return;
  const old = String(p.settings.catalogTitle || '');
  titleLabel.contentEditable = 'true'; titleLabel.classList.add('is-editing');
  titleLabel.setText(old || titleOf());
  try { titleLabel.focus(); document.getSelection?.()?.selectAllChildren?.(titleLabel); } catch {}
  let done = false;
  const end = ok => {
    if (done) return; done = true;
    titleLabel.contentEditable = 'false'; titleLabel.classList.remove('is-editing');
    const v = String(titleLabel.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40);
    if (ok && v !== old && v !== titleOf()) { p.settings.catalogTitle = v; saveSettingSoon('catalogTitle'); }
    setTitle();
  };
  titleLabel.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault?.(); end(true); } else if (e.key === 'Escape') { e.preventDefault?.(); e.stopPropagation?.(); end(false); } };
  titleLabel.onblur = () => end(true);
}
titleLabel.addEventListener('click', e => { if (!arranging || drag) return; e.stopPropagation?.(); editTitleInline(); });
function onArrangeKey(e) {
  if (!arranging || e.key !== 'Escape') return;
  if (drag) { e.preventDefault?.(); endModDrag(true); return; }
  if (edgeDrag) { e.preventDefault?.(); endEdgeDrag(); return; }
  const t = e.target;
  if (t && typeof t.closest === 'function' && t.closest('input, textarea, select, [contenteditable]')) return;   // 输入框里的 Esc 不退出编排
  e.preventDefault?.();
  if (openPanel) { const id = openPanel.id; closePanel(); try { bars[id]?.adj.focus(); } catch {} return; }
  if (selId) { selectMod(''); return; }
  setArranging(false);
}
let arranging = false;
function setArranging(on) {
  if (!arrangeBtn || arranging === !!on) return;
  arranging = !!on;
  if (arranging) { LB.style('lbc-arrange-style', ARRANGE_CSS); for (const id of MOD_IDS) ensureBar(id); if (!sideOpen) setSideOpen(true); }
  else { closePanel(); endModDrag(true); endEdgeDrag(); selectMod(''); if (saveTimer) flushSave(); }
  wrap.classList.toggle('is-arranging', arranging);
  arrangeBtn.setAttribute('aria-pressed', String(arranging));
  if (typeof document !== 'undefined') { if (arranging) document.addEventListener('keydown', onArrangeKey, true); else document.removeEventListener('keydown', onArrangeKey, true); }
  paintTray(); for (const id of MOD_IDS) paintBar(id);
  paintStickyTop();
  paintEdges();
  sideFadeSoon();
}
cleanups.push(() => { try { document.removeEventListener('keydown', onArrangeKey, true); } catch {} });
// 编排时点空白处：取消选中
wrap.addEventListener('pointerdown', e => { if (!arranging || !selId) return; const t = e.target; if (t && typeof t.closest === 'function' && t.closest('.lbc-m, .lbc-arrange-tray, .lbc-col-edge, .menu, .lbc-mp')) return; selectMod(''); });
function paintMod(key) { if (key === 'recent') paintRecent(); else if (key === 'sync') paintSync(); else if (key === 'overview') paintOverview(); else if (key === 'token') paintToken(); }
let roRef = null;
if (SIDE_ON) {
  mods.recent = sideModule('recent', 'RECENT', '最近导入');
  mods.sync = sideModule('sync', 'SYNC', '同步');   // 1026：齿轮去掉（首页设置入口太多），改时间点「下次同步」；1027：费用拆到 Token 费用
  mods.token = sideModule('token', 'TOKEN', 'Token 费用');
  mods.overview = sideModule('overview', 'OVERVIEW', '概览');
  for (const k of Object.keys(mods)) paintFold(k);
  side.addEventListener('scroll', () => sideFade(), { passive: true });
}
applyLayout({ relayout: false });
if (SIDE_ON) {
  const visible = () => sideOpen && !wrap.classList.contains('is-side-narrow') && !wrap.classList.contains('is-indexview') && !(typeof document !== 'undefined' && document.hidden);
  // 半分钟走一次倒计时 / 「今天」的界线（只重画 SYNC / RECENT 那几个字；签名没变就不动 DOM）
  const sideTimer = setInterval(() => { if (!visible()) return; paintSync(); paintRecent(); }, 30000);
  sideTimer?.unref?.();   // 单测（node）里别让这个钟拖住进程；浏览器里是数字，没有 unref
  cleanups.push(() => clearInterval(sideTimer));
  // 首开不拖慢封面（RELEASE-BAR §2）：边栏内容等第一帧画出来之后再填（live 之前的重画请求都是空操作，live 那一下整块画一次）
  let live = false;
  sideApi = {
    paintSync: () => { if (!live) return; paintSync(); sideFadeSoon(); },
    paintData: () => { if (!live) return; paintRecent(); paintOverview(); paintSync(); paintToken(); sideFadeSoon(); },
    paintAll: () => { if (!live) return; paintRecent(); paintSync(); paintToken(); paintOverview(); sideFadeSoon(); },
    start: () => { if (live) return; live = true; sideApi.paintAll(); },
    fade: sideFade,
  };
}

// ── 吸顶的 top（主审裁决 1）：取滚动容器上内边距的负值，sticky 贴住滚动容器顶边，上方不留缝（主 / 副 split 里内边距不同，不写死） ──
// 1021 窄屏（≤700px）：新页头 + 分类行 + 控制行加起来半屏多高，整块吸住就没地方看卡了——吸顶 top 再往上让出「搜索框以上」那一截
// （sticky 的负 top：吸住时只露搜索那一行 + 主题行 + 多选栏，往回滚整块照常出来）。宽屏照旧整块吸住（设计稿：只有收藏墙在动）。
let stickyHide = 0;
const stuckHeight = () => Math.max(0, (top.offsetHeight || 0) - stickyHide);
function paintStickyTop() {
  const sc = LB.scroller(); if (!sc) return;
  let pad = 0;
  try { const cs = (typeof getComputedStyle === 'function') ? getComputedStyle(sc) : null; pad = parseFloat(cs?.paddingTop) || 0; } catch {}
  // 1026：搜索框离页头顶多远按两个框的位置差量（页头里分了几块，offsetTop 的参照会变）
  stickyHide = narrow() && top.contains(searchBox) ? Math.max(0, Math.round((searchBox.getBoundingClientRect?.().top || 0) - (top.getBoundingClientRect?.().top || 0)) - 8) : 0;
  // 先读后写（RELEASE-BAR §2 首开）：工具条宽度、分类行放不放得下在这一次排版里一起量，写放在最后，不多触发整页重排
  const tw = Math.round(Number(tools.offsetWidth) || 0), catWrap = catWrapWanted(), topW = Number(top.clientWidth) || 0;
  // 1027「编排 / 管理」：吸顶区第一块是标题、够宽、不在编排 → 钉在右上角（标题两边让出它的宽度）；否则退成最上面一行
  const firstMod = (() => { for (const r of top.children || []) { if (!r.classList?.contains('lbc-row') || r.hidden) continue; for (const c of r.children || []) { if (c.hidden) continue; for (const m of c.children || []) if (m.classList?.contains('lbc-m') && !m.classList.contains('is-gone')) return m.dataset?.m || ''; } } return ''; })();
  const toolsStatic = narrow() || arranging || firstMod !== 'title' || (topW > 0 && topW < 760);
  const v = pad + stickyHide ? `${-(pad + stickyHide)}px` : '0px';
  if (top.style.top !== v) top.style.top = v;
  if (arrangeTray) { const tv = pad ? `${-pad}px` : '0px'; if (wrap.style.getPropertyValue('--lbc-tray-top') !== tv) wrap.style.setProperty('--lbc-tray-top', tv); }
  if (indexView && idx) paintIndexSticky();
  paintSideSticky(sc, pad);
  const twv = tw > 0 ? (tw + 20) + 'px' : '';
  if (twv && top.style.getPropertyValue('--lbc-tools-w') !== twv) top.style.setProperty('--lbc-tools-w', twv);
  if (top.classList.contains('is-tools-static') !== toolsStatic) top.classList.toggle('is-tools-static', toolsStatic);
  paintUnderTools(toolsStatic, tw);
  fitFreeGaps();
  if (arranging) paintEdges();
  if (catWrap != null && catBar.classList.contains('is-wrap') !== catWrap) catBar.classList.toggle('is-wrap', catWrap);
}
// 1028 页头第一排：右上角钉着「编排 / 管理」时，伸到它下面的块（默认是计数行）加 is-under-tools 往下让；标题那一块够不到右边 → 标题两边不用再留按钮的空
function paintUnderTools(toolsStatic, tw) {
  const bi = boardIndex();
  const firstI = layout.rows.findIndex((r, i) => i < bi && topRowEls[i] && !topRowEls[i].el.hidden);
  let titleClear = false;
  layout.rows.forEach((r, i) => {
    if (i >= bi || !topRowEls[i]) return;
    r.cols.forEach((c, j) => {
      const node = topRowEls[i].cols[j]; if (!node) return;
      const toolsCols = tw > 0 ? Math.ceil((tw + 20) / Math.max(1, (Number(top.clientWidth) || 1200) / GRID)) : 8;
      const under = !toolsStatic && i === firstI && c.x + c.w > GRID - toolsCols && !c.mods.includes('title');
      if (node.classList.contains('is-under-tools') !== under) node.classList.toggle('is-under-tools', under);
      if (c.mods.includes('title') && (i !== firstI || c.x + c.w <= GRID - toolsCols)) titleClear = true;
    });
  });
  if (top.classList.contains('is-title-clear') !== titleClear) top.classList.toggle('is-title-clear', titleClear);
}
// 1021 第 3 段：边栏吸在页头下面——--lbc-top-h = 吸住时页头露出来的高度，--lbc-side-top = 边栏的 sticky top（和 .lbc-top 同一个参照：
// 页头 top 是 -(pad + stickyHide)，边栏就贴在它底下），--lbc-pane-h = 滚动容器可视高度（边栏 max-height 用）。窄于 760（按页面宽）不出边栏
function paintSideSticky(sc, pad) {
  if (!SIDE_ON) return;
  const ww = Number(wrap.clientWidth) || 0;
  wrap.classList.toggle('is-side-narrow', ww > 0 && ww < 760);
  const topH = Math.max(0, Math.round((Number(top.offsetHeight) || 0) - stickyHide));
  const set = (k, v) => { if (wrap.style.getPropertyValue(k) !== v) wrap.style.setProperty(k, v); };
  set('--lbc-top-h', topH + 'px');
  set('--lbc-side-top', (topH - Math.round(pad)) + 'px');
  const ph = Math.round(Number(sc?.clientHeight) || 0);
  if (ph > 0) set('--lbc-pane-h', ph + 'px');
  sideApi?.fade();
}
// ── ResizeObserver（C9）：宽度变了导致列数变了才重摆（下一帧、带锚点）；顺手重算吸顶 top ──
if (typeof ResizeObserver === 'function') {
  let pending = false;
  const ro = new ResizeObserver(entries => {
    const w = (entries || []).find(e => e.target === grid)?.contentRect?.width;
    if (w > 0) roWidth = Math.max(0, w - 10);
    paintStickyTop();
    if (pending) return; pending = true;
    requestAnimationFrame(() => {
      pending = false;
      // 10-11 索引视图：页面变窄 / 变宽时树在左边还是叠在上面跟着换（换了网格宽度会变，下一次再按列数重摆）
      if (indexView && idx && split.classList.contains('is-narrow') !== panelNarrow()) { render(); return; }
      if (!grid.hidden && colCount() !== laidN) withAnchor(() => layoutGrid());
    });
  });
  ro.observe(grid);
  ro.observe(wrap);
  // 1021 边栏吸顶：页头高度（多选栏 / 主题行出来收起）、滚动容器高度变了都要重算 --lbc-top-h / --lbc-pane-h；边栏内容高度变了重算渐隐
  if (SIDE_ON) { ro.observe(top); const sc = LB.scroller(); if (sc) ro.observe(sc); for (const a of asides) ro.observe(a); roRef = ro; }
  cleanups.push(() => ro.disconnect());
}

// ── Esc（C17）：先关菜单 / 浮层；输入框里、别的页、菜单刚关的那一下都不清多选 ──
LB.listen('esc', document, 'keydown', e => {
  if (e.key !== 'Escape') return;
  if (document.querySelector('.lbc-menu, .lbc-synclog-pop')) { closeMenus(); e.preventDefault(); return; }
  if (LB.menuOpen() || e.defaultPrevented) return;
  const t = e.target;
  if (t === search || (t && typeof t.closest === 'function' && t.closest('input, textarea, [contenteditable], .lbc-tagform, .lbc-dialog'))) return;
  if (!selectMode || !LB.activeLeafHas(wrap)) return;
  clearSelection();
});

// ── 首屏 ──
cols = savedCols(); applyCols();
await refreshProblems();
restoreTarget = savedScroll;   // 1017：要恢复的滚动位置附近的卡同步建好（restoreScroll 一次到位）
const restoredWithPending = takePendingQuery();
// 上次离开时防抖还没触发（输入框里的字和上次搜的不一样）：恢复后补跑一次
if (!restoredWithPending && saved.ts && typeof saved.input === 'string' && saved.input.trim() !== lastRaw) commitSearch();
renderCatBar(); render();
// 1021 边栏：第一帧之后才填内容；同步计划异步读（插件 60 秒缓存），读到了只重画 SYNC 那一块
if (sideApi) requestAnimationFrame(() => { sideApi.start(); loadSchedule(); });
if (restoredWithPending || !(savedScroll > 0)) restoreTarget = 0;   // 要恢复滚动的：滚到位之前（含首帧的列数重摆）都按那个位置留卡，见下面 restoreScroll
pageReady = true;
if (idxPending) reloadIndex();
paintStickyTop();
LB.t('render');
startWarm();
// 点开一篇（同一窗格）之后这一页就要被换掉了：别再记滚动（Obsidian 换笔记时会把滚动容器归零）
// 10-04 ⑧ 一键回顶部：钉在页面最后（sticky 贴视口底），滚过一屏左右才出现
const toTopDock = wrap.createEl('div', { cls: 'lbc-totop-dock' });
const toTop = toTopDock.createEl('button', { cls: 'lbc-totop', attr: { title: '回到顶部', 'aria-label': '回到顶部' } }); toTop.type = 'button';
toTop.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg>';
toTop.onclick = () => { const el = LB.scroller(); if (!el) return; try { el.scrollTo({ top: 0, behavior: 'smooth' }); } catch { el.scrollTop = 0; } };
function paintToTop(t) {
  const kids = wrap.children; if (kids && kids[kids.length - 1] !== toTopDock) wrap.append(toTopDock);   // sticky 底部要在最后才贴得住
  const on = Number(t) > 600; toTopDock.className = 'lbc-totop-dock' + (on ? ' is-on' : ''); toTop.tabIndex = on ? 0 : -1;
}
paintToTop(savedScroll);
LB.onScroll(t => { paintToTop(t); if (leaving) return; scrollTop = t; saveState(); });
// 10-04 ⑨ Ctrl+F：当前视图是目录页时 = 跳到并聚焦目录搜索框，拦掉 Obsidian 自带的查找；别的页不拦（CM1）
function onFindKey(e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
  if (String(e.key || '').toLowerCase() !== 'f' && e.code !== 'KeyF') return;
  if (!pageActive()) return;
  e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation?.();
  try { search.scrollIntoView?.({ block: 'nearest' }); } catch {}
  search.focus(); try { search.select?.(); } catch {}
}
LB.listen('find-key', keyTarget, 'keydown', onFindKey, { capture: true });
// 1027 设置页③「目录的样子 → 去目录编排」：插件写 pendingCatalogArrange（时间戳）+ 发 link-brain:catalog-arrange，目录页读完即删、直接进编排
function takePendingArrange() {
  const p = provider();
  if (!p || !p.pendingCatalogArrange) return false;
  const at = p.pendingCatalogArrange;
  p.pendingCatalogArrange = 0;
  if (Date.now() - at > 60000) return false;
  if (!SIDE_ON) { LB.say('这里没有编排：在电脑上打开目录页点右上角「编排」', { kind: 'warn' }); return false; }
  setArranging(true);
  return true;
}
takePendingArrange();
if (app.workspace?.on && dv.component?.registerEvent) lbEvent(app.workspace, app.workspace.on('link-brain:catalog-arrange', () => takePendingArrange()));
// 登记这一版 DOM：Dataview 下次重跑时版本没变就原样挂回；变了走 refresh（只换数据、卡片复用；失败不推进版本）
LB.keep(wrap, { park: true, onAdopt: () => { LB.restoreFocus(search, 'search'); if (scrollTop > 0) LB.restoreScroll(scrollTop); }, version: await LB.data.version(), update: () => { syncPerf(); return refresh({ strict: true }); }, onReuse: () => {
  syncPerf();
  if (refreshTags() && committed) dataRev++;
  takePendingQuery();
  takePendingArrange();
  const c = savedCols(); if (c !== cols && (c || LB.provider()?.settings)) { cols = c; applyCols(); }
  setTitle();
  render();
  paintStickyTop();
  sideApi?.start(); sideApi?.paintAll(); loadSchedule();
  if (stale) checkFresh();
} });
if (provider()?.focusCatalogSearch) { provider().focusCatalogSearch = false; search.focus(); }
else LB.restoreFocus(search, 'search');
if (savedScroll > 0 && !restoredWithPending) Promise.resolve(LB.restoreScroll(savedScroll)).then(() => paintToTop(LB.scroller()?.scrollTop || 0)).catch(() => {}).finally(() => { restoreTarget = 0; });   // 滚到位时记一笔 scroll-restored@
LB.t('restore');
LB.t('total');

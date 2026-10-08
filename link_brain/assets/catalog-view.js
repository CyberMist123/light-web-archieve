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
.lbc-wrap{width:100%;max-width:1440px;margin:0 auto;box-sizing:border-box;height:auto;display:block;padding:22px 24px 30px;overflow:visible;font-family:"Noto Sans SC","Segoe UI","Microsoft YaHei UI",sans-serif;}
.lbc-wrap button{font-family:inherit;}
.lbc-top{position:sticky;top:0;background:var(--background-primary);z-index:2;}
.lbc-head{display:grid;grid-template-columns:1fr auto;align-items:center;text-align:left;gap:18px 20px;margin:0 0 12px;}
.lbc-titleblock{display:flex;flex-direction:column;align-items:center;gap:10px;grid-column:1;grid-row:1;width:max-content;max-width:100%;}
.lbc-titlerow{display:flex;align-items:center;justify-content:center;gap:10px;}
.lbc-title{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:32px;font-weight:700;letter-spacing:.01em;line-height:1.05;color:var(--text-normal);}
.lbc-wrap .lbc-title button.lbc-import{font:inherit!important;color:var(--text-normal)!important;transition:color .12s;width:auto!important;height:auto!important;padding:0 0 0 .12em!important;margin:0!important;border:0!important;background:transparent!important;box-shadow:none!important;border-radius:0!important;display:inline!important;vertical-align:baseline;line-height:inherit!important;cursor:pointer;}
.lbc-wrap .lbc-title button.lbc-import:hover{color:var(--interactive-accent)!important;}
.lbc-wrap .lbc-title button.lbc-import[aria-busy="true"]{opacity:.5;cursor:progress;}
.lbc-tools{grid-column:2;grid-row:1;justify-self:end;display:flex;align-items:center;gap:10px;}
.lbc-subline{display:flex;gap:7px;align-items:center;justify-content:center;flex-wrap:wrap;}
.lbc-sub{font-size:10px;color:var(--text-faint);letter-spacing:.06em;white-space:nowrap;}
.lbc-sub-sep{font-size:10px;color:var(--text-faint);user-select:none;}
.lbc-wrap button.lbc-sub-link{font:inherit;font-size:10px;letter-spacing:.06em;color:var(--text-faint);background:transparent!important;border:0!important;box-shadow:none!important;padding:0!important;height:auto!important;min-height:0;cursor:pointer;border-radius:3px;}
.lbc-wrap button.lbc-sub-link:hover{text-decoration:underline;text-underline-offset:2px;color:var(--text-muted);}
.lbc-wrap button.lbc-sub-link:focus-visible{outline:2px solid var(--interactive-accent)!important;outline-offset:2px;}
.lbc-stale{font-size:10px;color:var(--lb-warn);}
.lbc-wrap button.lbc-problems{display:inline-flex;align-items:center;gap:3px;min-height:0;height:auto!important;padding:0!important;border:0!important;box-shadow:none!important;background:transparent!important;cursor:pointer;flex:0 0 auto;}
.lbc-problems[hidden],.lbc-syncing[hidden],.lbc-possible-link[hidden],.lbc-sub-sep[hidden],.lbc-stale[hidden]{display:none!important;}
.lbc-prob-n{display:inline-flex;align-items:center;justify-content:center;min-width:16px;height:16px;padding:0 4px;box-sizing:border-box;border-radius:8px;font-size:10.5px;font-weight:700;font-family:sans-serif;line-height:16px;}
.lbc-prob-need{background:var(--lb-warn);color:var(--text-on-accent,#fff);}
.lbc-prob-other{background:var(--background-modifier-border);color:var(--text-muted);font-weight:600;}
.lbc-search{grid-column:1/-1;grid-row:3;justify-self:start;width:100%!important;min-width:0;max-width:none!important;text-align:left;height:40px!important;padding:0 15px!important;border:1px solid var(--background-modifier-border)!important;border-radius:8px!important;background:var(--background-secondary)!important;box-shadow:none!important;font:inherit;font-size:14px;}
.lbc-search:focus{border-color:var(--interactive-accent)!important;outline:none;}
.lbc-wrap .lb-page-nav{grid-column:1;grid-row:2;justify-self:start;padding:0;background:transparent;}
.lbc-mobile-note{font-size:12px;line-height:1.5;color:var(--text-muted);margin:0;text-align:center;}
.lbc-cats{display:flex;align-items:center;gap:20px;flex-wrap:nowrap;overflow-x:auto;margin:0;padding:0 0 12px;font-size:13px;font-family:inherit;scrollbar-width:thin;}
.lbc-cats.has-more-right{-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 32px),transparent);mask-image:linear-gradient(to right,#000 calc(100% - 32px),transparent);}
.lbc-cats.has-more-left{-webkit-mask-image:linear-gradient(to right,transparent,#000 32px);mask-image:linear-gradient(to right,transparent,#000 32px);}
.lbc-cats.has-more-left.has-more-right{-webkit-mask-image:linear-gradient(to right,transparent,#000 32px,#000 calc(100% - 32px),transparent);mask-image:linear-gradient(to right,transparent,#000 32px,#000 calc(100% - 32px),transparent);}
.lbc-cats button.lbc-cat{flex:none;cursor:pointer;color:var(--text-muted);border:0!important;border-bottom:2px solid transparent!important;background:transparent!important;box-shadow:none!important;padding:8px 0;border-radius:0;height:auto;font-size:13px;font-weight:400;transition:color .12s;}
.lbc-cats button.lbc-cat:hover{color:var(--text-normal);}
.lbc-cats button.lbc-cat.is-active{color:var(--text-normal);border-bottom-color:var(--text-normal)!important;font-weight:500;}
/* 星标主题 chip（Lot E）：cats 栏下一排，只在有主题时出现 */
.lbc-topics{display:flex;align-items:center;gap:8px;flex-wrap:nowrap;overflow-x:auto;margin:0;padding:0 0 12px;font-family:inherit;}
.lbc-topics button.lbc-topic{flex:none;height:auto;padding:3px 11px;border:1px solid var(--background-modifier-border)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:12px;font-weight:400;line-height:1.6;cursor:pointer;transition:color .12s,border-color .12s;}
.lbc-topics button.lbc-topic:hover{color:var(--text-normal);}
.lbc-topics button.lbc-topic.is-active{color:var(--text-normal);border-color:var(--text-normal)!important;font-weight:500;}
.lbc-topic-star{color:var(--lb-star);margin-right:4px;}
/* C1 / C15：多选栏在吸顶区里（.lbc-top 最后一个子节点），常用的留在栏上，其余收进「更多…」 */
.lbc-selbar{display:flex;flex-wrap:wrap;row-gap:8px;gap:8px 12px;align-items:center;margin:8px 0 10px;padding:10px 14px;border-radius:12px;background:var(--background-secondary);}
.lbc-selbar[hidden]{display:none!important;}
.lbc-selcount{font-size:13px;color:var(--text-muted);}
.lbc-selbar button{border:0;border-radius:8px;padding:6px 14px;white-space:nowrap;}
.lbc-selbar button.mod-warning{background:var(--lb-danger);color:var(--text-on-accent,#fff);font-weight:600;}
.lbc-selbar button.mod-warning:hover{filter:brightness(.92);}
.lbc-selbar button:disabled{opacity:.5;cursor:default;}
.lbc-selbar .lbc-selhint{margin-left:auto;font-size:12px;color:var(--text-faint);white-space:nowrap;}
.lbc-menu{background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:5px;min-width:120px;}
.lbc-menu-item{display:block;width:100%;text-align:left;border:0;background:transparent;color:var(--text-normal);box-shadow:none;height:auto;padding:7px 14px;border-radius:7px;cursor:pointer;font-size:13px;}
.lbc-menu-item:hover,.lbc-menu-item:focus-visible{background:var(--background-modifier-hover);outline:none;}
.lbc-menu-item.is-danger{color:var(--lb-danger);}
.lbc-menu .lbc-menu-head{padding:6px 14px 2px;font-size:11px;color:var(--text-faint);}
.lbc-menu .lbc-menu-item.is-on{color:var(--interactive-accent);font-weight:500;}
.lbc-menu .lbc-menu-sep{height:1px;margin:4px 6px;background:var(--background-modifier-border);}
.lbc-menu .lbc-range{display:flex;align-items:center;gap:6px;padding:4px 10px 8px;font-size:12px;color:var(--text-muted);}
.lbc-menu .lbc-range input{height:26px;font-size:12px;padding:0 4px;}
.lbc-menu .lbc-range button{height:26px;padding:0 10px;font-size:12px;}
/* C9 按行瀑布流：每列一个 flex 子列，卡片按预估高度放进当前最矮的一列 */
.lbc-grid{height:auto;overflow:visible;display:block;padding:12px 5px 30px;}
.lbc-grid[hidden]{display:none!important;}
.lbc-masonry{display:flex;align-items:flex-start;gap:0 var(--lbc-gap,24px);}
.lbc-masonry>.lbc-col{flex:1 1 0;min-width:0;display:flex;flex-direction:column;}
.lbc-card{display:block;width:100%;margin:0 0 26px;cursor:pointer;position:relative;}
.lbc-cover{display:block;width:100%;height:auto;max-height:360px;object-fit:cover;object-position:top;border:0;border-radius:12px;transition:transform .16s,box-shadow .16s;pointer-events:none;}
.lbc-card:hover .lbc-cover{transform:translateY(-2px);box-shadow:0 6px 18px #00000012;}
.lbc-card:focus-visible{outline:2px solid var(--interactive-accent);outline-offset:5px;border-radius:12px;}
.lbc-card.is-selected .lbc-cover,.lbc-card.is-selected .lbc-nocover{outline:3px solid var(--interactive-accent);outline-offset:2px;filter:brightness(.92);}
.lbc-nocover{aspect-ratio:4/3;border-radius:12px;background:var(--background-secondary);display:grid;place-items:center;color:var(--text-muted);font-size:30px;}
.lbc-body{padding:12px 2px 0;}
.lbc-ctitle{font-size:14px;line-height:1.6;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbc-cmeta{display:flex;justify-content:space-between;gap:10px;color:var(--text-muted);font-size:11px;margin-top:8px;font-weight:300;}
.lbc-cmeta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbc-likes{flex-shrink:0;transition:opacity .12s;}.lbc-card:hover .lbc-likes,.lbc-card:focus-within .lbc-likes{opacity:0;}
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
/* 角标：待补 / 要你处理用共享的警示色（C18，深色主题下不再是米白贴纸） */
.lbc-wrap .lbc-badges{position:absolute;top:8px;left:8px;display:flex;gap:5px;align-items:center;}
.lbc-wrap .lbc-attach{position:static;display:inline-flex;align-items:center;gap:4px;line-height:16px;padding:3px 6px;height:22px;box-sizing:border-box;font-size:11px;border-radius:6px;background:var(--background-primary);color:var(--text-muted);border:1px solid var(--background-modifier-border);pointer-events:none;}
.lbc-wrap .lbc-attach-todo,.lbc-wrap .lbc-badges .lbc-prob.is-need{color:var(--lb-warn);background:var(--lb-warn-bg);border-color:var(--lb-warn-border);}
.lbc-wrap .lbc-attach-hint{color:var(--text-muted);background:var(--background-secondary);border-color:var(--background-modifier-border);}
.lbc-wrap .lbc-badges .lbc-prob{pointer-events:auto;cursor:help;color:var(--text-muted);background:var(--background-secondary);border-color:var(--background-modifier-border);}
.lbc-wrap .lbc-badges svg{display:block;width:14px;height:14px;flex:none;stroke:currentColor;stroke-width:1.6;fill:none;}
/* ★ 常显（1008 她定）：没收藏的半透明，悬停 / 聚焦 / 已收藏全显；加 .lbc-wrap 前缀，不受问收藏页样式影响（X14c） */
.lbc-wrap .lbc-star{position:absolute;right:42px;top:8px;width:30px;height:30px;padding:0!important;border:0!important;border-radius:50%;background:var(--background-primary)!important;color:var(--text-muted);box-shadow:0 1px 5px #0002!important;font-size:21px;cursor:pointer;opacity:.55;pointer-events:auto;transition:opacity .15s;}
.lbc-wrap .lbc-card:hover .lbc-star,.lbc-wrap .lbc-card:focus-within .lbc-star,.lbc-wrap .lbc-star.is-on{opacity:1;}
.lbc-wrap .lbc-star.is-on{color:var(--text-normal);}
.lbc-wrap .lbc-star.is-static{right:8px;cursor:default;box-shadow:none!important;}
.lbc-wrap .lbc-card.is-starring .lbc-star{animation:lbc-pulse .8s ease-in-out infinite;cursor:progress;}
@keyframes lbc-pulse{0%,100%{transform:scale(1);}50%{transform:scale(1.15);}}
.lbc-wrap .lbc-card.is-deleting{opacity:.45;pointer-events:none;}
.lbc-card.is-droptarget::after,.lbc-card.is-busy::after{position:absolute;inset:0;display:grid;place-items:center;border-radius:12px;font-size:13px;color:var(--text-normal);background:color-mix(in srgb,var(--background-primary) 70%,transparent);z-index:3;pointer-events:none;}
.lbc-card.is-droptarget::after{content:"松手挂到这篇";outline:2px dashed var(--interactive-accent);outline-offset:-2px;}
.lbc-card.is-busy::after{content:attr(data-busy);cursor:progress;}
.lbc-flash{position:absolute;left:50%;top:40%;transform:translate(-50%,-50%);z-index:4;padding:4px 10px;border-radius:8px;background:var(--background-primary);color:var(--lb-ok);font-size:12px;box-shadow:0 2px 8px #0002;pointer-events:none;}
.lbc-tagform{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}
.lbc-tagform input{flex:1 1 100%;width:100%;}
.lbc-tagform-err{flex:1 1 100%;font-size:12px;color:var(--lb-danger);}
.lbc-tagform-err[hidden]{display:none!important;}
.lbc-card-more{position:absolute;right:0;bottom:-4px;width:28px;height:28px;padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:20px;opacity:0;}
.lbc-card:hover .lbc-card-more,.lbc-card:focus-within .lbc-card-more{opacity:1;}
/* 10-04 悬停卡片就出现的选中圈（不用先进「多选模式」）；有选中时每张卡都显示圈 */
.lbc-wrap button.lbc-check{position:absolute;top:8px;right:8px;z-index:1;width:26px;height:26px;padding:0!important;border-radius:50%!important;border:1.5px solid #fff!important;background:rgba(0,0,0,.28)!important;box-shadow:0 1px 4px #0003!important;color:transparent;display:grid;place-items:center;cursor:pointer;opacity:0;pointer-events:none;transition:opacity .15s,background .12s;}
.lbc-wrap button.lbc-check svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round;}
.lbc-card:hover button.lbc-check,.lbc-card:focus-within button.lbc-check,.lbc-wrap.is-selecting button.lbc-check{opacity:1;pointer-events:auto;}
.lbc-wrap button.lbc-check:hover{background:rgba(0,0,0,.45)!important;}
.lbc-wrap button.lbc-check.is-on{background:var(--interactive-accent)!important;border-color:var(--interactive-accent)!important;color:#fff;opacity:1;pointer-events:auto;}
@media(hover:none){.lbc-wrap button.lbc-check{opacity:1;pointer-events:auto;}.lbc-card-more{opacity:1;}.lbc-cmeta{padding-right:30px;}.lbc-card:hover .lbc-likes{opacity:1;}.lbc-wrap .lbc-star{opacity:1;}}
/* 星标页（.lbc-simple）：单列列表 */
.lbc-simple .lbc-grid{max-width:820px;margin:0 auto;}
.lbc-simple .lbc-card{display:block;margin:0;padding:18px 72px 18px 0;border-bottom:1px solid var(--background-modifier-border);}
.lbc-simple .lbc-cover,.lbc-simple .lbc-nocover{display:none;}
.lbc-simple .lbc-body{padding:0;}
.lbc-simple .lbc-cmeta{justify-content:flex-start;margin-top:4px;}
.lbc-simple .lbc-head{max-width:820px;margin:0 0 24px;}
.lbc-simple .lbc-cats{max-width:820px;margin:0 auto;}
.lbc-wrap.lbc-simple .lbc-badges{position:static;float:right;margin:2px 0 0 12px;}
.lbc-wrap.lbc-simple .lbc-star{top:16px;right:0;}
.lbc-simple button.lbc-check{top:18px;right:34px;border-color:var(--background-modifier-border)!important;background:var(--background-primary)!important;}
.lbc-simple button.lbc-check.is-on{background:var(--interactive-accent)!important;}
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
@media(max-width:700px){.lbc-wrap{padding:12px 6px 0;}.lbc-head{gap:12px;}.lbc-title{font-size:28px;}.lbc-cats{gap:18px;}.lbc-ctitle{font-size:14px;}.lbc-card-more{opacity:1;}.lbc-selbar button{padding:6px 10px;}}
`;
LB.style('lbc-style', CSS);

// ── 挂载点（C4）：dv.container 后面的兄弟 host；Dataview 重跑只清 container，碰不到页面 ──
const mount = LB.mountHost('lbc-host');
const wrap = mount.createEl('div', { cls: 'lbc-wrap' + (simplePage ? ' lbc-simple' : '') });
// 缺插件 / 插件版本对不上 / 手机：说一句、返回 null（电脑上旧实例缺新方法时先重载一次插件）
async function want(method) {
  try { return await LB.ensure(method); }
  catch (e) { LB.say(e?.message || String(e), { kind: mobile ? 'info' : 'error' }); return null; }
}

let data;
try { data = await LB.data.load(); }
catch {
  // C8：数据读不到——说清怎么办；电脑上给 [刷新目录]
  const box = wrap.createEl('div', { cls: 'lbc-empty lbc-nodata' });
  box.createEl('p', { cls: 'lbc-empty-text', text: mobile ? '目录数据还没生成：在电脑上点右上「…」→ 刷新目录。' : '目录数据还没生成：点右上「…」→ 刷新目录' });
  if (!mobile) {
    const b = box.createEl('div', { cls: 'lbc-empty-actions' }).createEl('button', { text: '刷新目录', cls: 'mod-cta' }); b.type = 'button';
    b.onclick = async () => {
      const p = await want('refreshCatalog'); if (!p) return;
      const done = LB.busy(b, '正在刷新目录…');
      try { await p.refreshCatalog(); done(); dv.component?.render?.(); }
      catch (e) { done(); LB.say('目录没刷新上：' + (e?.message || e), { kind: 'error' }); }
    };
  }
  return;
}
let items = data.items || [];
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

// ── 页面状态 ──
let committed = '', lastRaw = '';
let activeCat = '', todayOnly = false, todoOnly = false, mediaFilter = '', starOnly = starredPage;
// 10-04 导入时间（catalog-data 的 ts = 首次入库时间）：排序 ''=默认 / 'recent'=最近导入；范围 ''=全部 / today / 7d / 30d / custom
let timeSort = '', timeRange = '', timeFrom = '', timeTo = '';
let activeTopic = '', topicBar = null;
let selectMode = false; const selected = new Set();
let exportImages = true;
let dataRev = 0;            // C2：只有拿到新数据 / 删除成功 / 有搜索词时标签变了才 +1
let stale = false;          // F4：看不见时磁盘上的 catalog-data 变了，露出来再刷新
let leaving = false;        // 点开一篇（同一窗格）之后这一页就要被换掉了：别再记滚动

// 卸载清理（C4）：ResizeObserver、预热、打字防抖、Ctrl 滚轮
const cleanups = [];
try { dv.component?.register?.(() => { for (const f of cleanups.splice(0)) { try { f(); } catch {} } }); } catch {}

// 数据变了（同步进来新的、删了、挂了附件）：不重建整页，只换数据再画卡片（卡片按 id 复用）
// strict：读失败就抛（reuseDom 的 update 失败不推进版本，下次重跑重试；F4）
async function refresh({ strict = false } = {}) {
  let v = null, next;
  try { v = await LB.data.version(); next = await LB.data.load(); }
  catch (e) { if (strict) throw e; return false; }
  data = next; items = data.items || [];
  refreshTags(); dataRev++; stale = false;
  startWarm();
  renderCatBar();
  withAnchor(() => render());
  paintProblems();
  const view = root.__lbView;
  if (view && v) view.version = v;   // 已经是新数据了：下一次 Dataview 重跑别再更新一遍
  return true;
}
function attachmentPanel(list) { want('openAttachments').then(p => p?.openAttachments(list, () => refresh())); }
function editCategories(sel = '') { want('openCategories').then(p => p?.openCategories(data.cats || [], sel, () => refresh())); }

// ── 顶栏（吸顶）：标题「Collections +」+ 标题下那一行 + 搜索 + 页面导航 + 大类条 + 多选栏 ──
const top = wrap.createEl('div', { cls: 'lbc-top' });
const head = top.createEl('div', { cls: 'lbc-head' });
const titleBlock = head.createEl('div', { cls: 'lbc-titleblock' });
const titleRow = titleBlock.createEl('div', { cls: 'lbc-titlerow' });
// 10-03：大标题可改（「…→改标题」，存插件设置 catalogTitle；空 = Collections）
const titleOf = () => String(LB.provider()?.settings?.catalogTitle || '').trim() || 'Collections';
const titleText = titleRow.createEl('span', { cls: 'lbc-title' });
const titleLabel = titleText.createEl('span', { cls: 'lbc-title-text', text: titleOf() });
const tools = head.createEl('div', { cls: 'lbc-tools' });
const importButton = mobile ? null : titleText.createEl('button', { cls: 'lbc-import', text: '+' });
if (mobile) titleBlock.createEl('div', { cls: 'lb-mobile-note lbc-mobile-note', text: LB.MOBILE_ONLY_TEXT });
// F4：标题下那一行拆成三块——计数（只是字）· 可能相关（跳到那一组）· 更新（打开同步记录）
const subLine = titleBlock.createEl('div', { cls: 'lbc-subline' });
const countEl = subLine.createEl('span', { cls: 'lbc-sub lbc-count' });
const sepPossible = subLine.createEl('span', { cls: 'lbc-sub-sep', text: '·' });
const possibleLink = subLine.createEl('button', { cls: 'lbc-sub lbc-sub-link lbc-possible-link' }); possibleLink.type = 'button';
const sepUpdated = subLine.createEl('span', { cls: 'lbc-sub-sep', text: '·' });
const updatedBtn = subLine.createEl('button', { cls: 'lbc-sub lbc-sub-link lbc-updated' }); updatedBtn.type = 'button';
const staleEl = subLine.createEl('span', { cls: 'lbc-sub lbc-stale', text: '· 这台设备上的目录数据较旧' }); staleEl.hidden = true;
// 第 4 批（CONVENTIONS §3.3）：顶部问题入口。数字来自 _archive/problems-summary.json；「要你处理」橙色，其余灰色，都为 0 不显示
const probBtn = subLine.createEl('button', { cls: 'lbc-problems' }); probBtn.type = 'button'; probBtn.hidden = true;
// C14：「· 同步中」带上阶段，悬停看全句，点开同步记录
const syncing = subLine.createEl('button', { cls: 'lbc-sub lbc-sub-link lbc-syncing', text: '· 同步中…' }); syncing.type = 'button'; syncing.hidden = true;
const fmtTime = v => { const d = new Date(v); return Number.isFinite(d.getTime()) ? d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'; };
const fmtFull = v => { const d = new Date(v); if (!Number.isFinite(d.getTime())) return '—'; const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };

let syncState = null, probSummary = null, aliveChecked = false;
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
async function refreshProblems() {
  const [raw, sum] = await Promise.all([readArchiveJson('_archive/sync-status.json'), readArchiveJson('_archive/problems-summary.json')]);
  probSummary = sum; syncState = mergeSync(raw, sum); paintProblems();
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
  if (auto + gaveUp) probBtn.createEl('span', { cls: 'lbc-prob-n lbc-prob-other', text: String(auto + gaveUp) });
  probBtn.hidden = !need && !(auto + gaveUp);
  const lines = [];
  if (st.state === 'blocked' || st.state === 'failed') { const why = st.detail || st.message || ''; const head_ = st.label || regEntry(st.code)?.label || ''; if (head_ || why) lines.push(head_ && why ? head_ + '：' + why : head_ || why); }
  const counts = [need && `要你处理 ${need}`, auto && `正在自动处理 ${auto}`, gaveUp && `已放弃 ${gaveUp}`].filter(Boolean);
  if (counts.length) lines.push(counts.join(' · '));
  probBtn.title = probBtn.hidden ? '' : [...lines, '点击查看问题列表'].join('\n');
  syncing.hidden = st.state !== 'running';
  if (!syncing.hidden) { const ph = syncPhase(st); syncing.textContent = ph.text; syncing.title = (ph.full ? ph.full + '\n' : '') + '点开看同步记录'; }
  paintSub();
}
probBtn.onclick = async () => {
  if (mobile) { LB.say('问题列表要在电脑上看'); return; }
  const p = await want('openProblems'); if (!p) return;
  try { await p.openProblems(); } catch (e) { LB.say(e?.message || String(e), { kind: 'error' }); }
};
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
  let freshTimer = null;
  const onFile = file => {
    if (watched.has(file?.path)) refreshProblems();
    else if (file?.path === dataPath) { clearTimeout(freshTimer); freshTimer = setTimeout(() => checkFresh(), 800); }
  };
  cleanups.push(() => clearTimeout(freshTimer));
  dv.component.registerEvent(app.vault.on('modify', onFile));
  dv.component.registerEvent(app.vault.on('create', onFile));
}

const search = head.createEl('input', { cls: 'lbc-search' });
search.type = 'search'; search.placeholder = '搜索收藏 · #标签';
const pageNav = head.createEl('nav', { cls: 'lb-page-nav' });
const browse = pageNav.createEl('button', { text: '浏览收藏', cls: 'is-current' }); browse.setAttribute('aria-current', 'page'); browse.onclick = () => LB.openPage('catalog');
const ask = pageNav.createEl('button', { text: '问收藏' }); ask.onclick = () => LB.openPage('chat');
const manage = mobile ? null : tools.createEl('button', { cls: 'lb-manage', text: '…' });
if (manage) manage.onclick = async e => { const p = await want('openManageMenu'); p?.openManageMenu(e, { categories: () => editCategories() }); };
if (importButton) importButton.type = 'button';
if (importButton) importButton.onclick = async e => {
  e.preventDefault(); e.stopPropagation();
  importButton.disabled = true; importButton.setAttribute?.('aria-busy', 'true');
  try { (await LB.ensure('openPlusMenu')).openPlusMenu(e); }
  catch (err) { LB.say('菜单没打开：' + (err?.message || err), { kind: 'error' }); }
  finally { importButton.disabled = false; importButton.removeAttribute?.('aria-busy'); }
};
// 大类筛选条（小红书式 tab）：单选，一次一个；「全部」或再点当前项清空。
const catBar = top.createEl('div', { cls: 'lbc-cats' });
function anyFilter() { return !!(activeCat || todayOnly || todoOnly || mediaFilter || (starOnly && !starredPage) || activeTopic || timeRange || timeSort); }
function clearFilters({ keepStar = starredPage } = {}) { activeCat = ''; todayOnly = false; todoOnly = false; mediaFilter = ''; activeTopic = ''; timeRange = ''; timeSort = ''; timeFrom = ''; timeTo = ''; starOnly = keepStar; }
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
  const tabClick = fn => () => { fn(); renderCatBar({ reveal: true }); render(); scrollToResults(); };
  mk('全部', !anyFilter() && !starredPage, () => {
    if (starredPage) { LB.openPage('catalog'); return; }
    if (anyFilter()) tabClick(() => clearFilters())();
  });
  mk('今日新增', todayOnly, tabClick(() => { todayOnly = !todayOnly; if (todayOnly) todoOnly = false; }));
  // 10-04：导入时间（排序 + 范围）收在这一个小入口里，点开是小菜单
  const timeTab = mk(timeLabel(), !!(timeRange || timeSort), e => { e?.stopPropagation?.(); openTimeMenu(timeTab); }); timeTab.classList.add('lbc-time');
  // X17：「已收藏」就地筛选（星标页上点它回目录）
  mk('已收藏', starredPage || starOnly, () => { if (starredPage) { LB.openPage('catalog'); return; } tabClick(() => { starOnly = !starOnly; })(); });
  mk('视频', mediaFilter === 'video', tabClick(() => { mediaFilter = mediaFilter === 'video' ? '' : 'video'; }));
  mk('附件', mediaFilter === 'attachment', tabClick(() => { mediaFilter = mediaFilter === 'attachment' ? '' : 'attachment'; }));
  const todo = items.filter(x => x.attachment === '待补').length;
  if (todo) mk(`待补附件 ${todo}`, todoOnly, tabClick(() => { todoOnly = !todoOnly; if (todoOnly) todayOnly = false; }));
  for (const cat of (data.cats_order || []).filter(c => !(provider()?.settings?.hiddenCats || []).includes(c))) {
    const tab = mk(cat, activeCat === cat, tabClick(() => { activeCat = (activeCat === cat ? '' : cat); }));
    if (!mobile) tab.oncontextmenu = e => { e.preventDefault(); editCategories(cat); };
  }
  catBar.scrollLeft = left;
  if (focusedLabel) { const again = [...catBar.querySelectorAll('.lbc-cat')].find(b => b.textContent === focusedLabel); try { again?.focus({ preventScroll: true }); } catch { again?.focus?.(); } }
  if (reveal) { try { catBar.querySelector('.lbc-cat.is-active')?.scrollIntoView?.({ inline: 'nearest', block: 'nearest' }); } catch {} }
  paintCatFade();
  renderTopicBar();
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
function renderTopicBar() {
  const names = Array.isArray(data.topics) ? data.topics.filter(n => typeof n === 'string' && n) : [];
  if (!names.includes(activeTopic)) activeTopic = '';
  if (!names.length) { if (topicBar) { topicBar.remove(); topicBar = null; } return; }
  if (!topicBar) { topicBar = top.createEl('div', { cls: 'lbc-topics' }); top.insertBefore(topicBar, catBar.nextSibling); barWheel(topicBar); }
  topicBar.empty();
  for (const name of names) {
    // 不设 aria-label / title：Obsidian 会渲染成悬浮框（她不要）。
    const chip = topicBar.createEl('button', { cls: 'lbc-topic' + (activeTopic === name ? ' is-active' : '') });
    chip.type = 'button';
    chip.createEl('span', { cls: 'lbc-topic-star', text: '★' }); chip.append(name);
    chip.setAttribute('aria-pressed', String(activeTopic === name));
    chip.onclick = () => { activeTopic = (activeTopic === name ? '' : name); renderCatBar(); render(); scrollToResults(); };
  }
}
// ── 10-04 导入时间：筛选 + 排序 ──
const TIME_RANGES = { today: '今天', ['7d']: '近 7 天', ['30d']: '近 30 天' };
const ymd = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
function importedAt(it) { const t = Date.parse(it.ts || it.date || ''); return Number.isFinite(t) ? t : 0; }
function timeLabel() {
  const range = timeRange === 'custom' ? `${(timeFrom || '…').slice(5)}~${(timeTo || '…').slice(5)}` : TIME_RANGES[timeRange] || '';
  return [range, timeSort === 'recent' ? '最近导入' : ''].filter(Boolean).join(' · ') || '导入时间';
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
    const list = [...menu.querySelectorAll('.lbc-menu-item')];
    const i = list.indexOf(document.activeElement);
    const go = k => { const n = list.length; if (!n) return; const el = list[((k % n) + n) % n]; try { el.focus({ preventScroll: true }); } catch { el.focus(); } };
    if (e.key === 'ArrowDown') { e.preventDefault(); go(i + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); go(i < 0 ? list.length - 1 : i - 1); }
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
    const b = menu.createEl('button', { cls: 'lbc-menu-item' + (it.danger ? ' is-danger' : '') + (it.checked ? ' is-on' : ''), text: (it.checked ? '✓ ' : '') + it.title });
    b.type = 'button'; b.setAttribute('role', 'menuitem');
    b.onclick = ev => { ev?.stopPropagation?.(); close(); it.onClick?.(ev); };
  }
  placeMenu(menu, pos?.x ?? 0, pos?.y ?? 0);
  focusFirst(menu);
  return menu;
}
function openTimeMenu(anchor) {
  const { menu, close } = menuShell('lbc-time-menu', anchor);
  const apply = () => { close(); renderCatBar(); render(); scrollToResults(); };
  const item = (label, on, fn) => { const b = menu.createEl('button', { cls: 'lbc-menu-item' + (on ? ' is-on' : ''), text: (on ? '✓ ' : '') + label }); b.type = 'button'; b.onclick = ev => { ev?.stopPropagation?.(); fn(); apply(); }; return b; };
  menu.createEl('div', { cls: 'lbc-menu-head', text: '排序' });
  item('默认', !timeSort, () => { timeSort = ''; });
  item('最近导入', timeSort === 'recent', () => { timeSort = 'recent'; });
  menu.createEl('div', { cls: 'lbc-menu-sep' });
  menu.createEl('div', { cls: 'lbc-menu-head', text: '导入时间' });
  item('全部时间', !timeRange, () => { timeRange = ''; });
  for (const [k, label] of Object.entries(TIME_RANGES)) item(label, timeRange === k, () => { timeRange = k; todayOnly = false; });
  menu.createEl('div', { cls: 'lbc-menu-head', text: '自定义起止' });
  const row = menu.createEl('div', { cls: 'lbc-range' }); row.onclick = ev => ev.stopPropagation();
  const from = row.createEl('input'); from.type = 'date'; from.value = timeFrom;
  row.createEl('span', { text: '~' });
  const to = row.createEl('input'); to.type = 'date'; to.value = timeTo;
  const ok = row.createEl('button', { text: '筛选' }); ok.type = 'button';
  ok.onclick = ev => { ev?.stopPropagation?.(); let a = from.value || '', b = to.value || ''; if (!a && !b) return; if (a && b && a > b) [a, b] = [b, a]; timeFrom = a; timeTo = b; timeRange = 'custom'; todayOnly = false; apply(); };
  const r = anchor.getBoundingClientRect();
  placeMenu(menu, r.left, r.bottom + 4);
  focusFirst(menu);
  return menu;
}

// ── 页面状态（§5.3）：打开一篇再返回 / 页面被重建后，搜索词、筛选、多选、滚动位置照旧 ──
const saved = LB.state.load();
let savedScroll = 0;
if (saved.ts) {
  committed = typeof saved.q === 'string' ? saved.q : '';
  lastRaw = typeof saved.raw === 'string' ? saved.raw : (typeof saved.input === 'string' && saved.input === saved.q ? saved.input.trim() : '');
  if (typeof saved.cat === 'string' && (data.cats_order || []).includes(saved.cat)) activeCat = saved.cat;
  if (typeof saved.topic === 'string') activeTopic = saved.topic;   // renderTopicBar 会把已不存在的主题清掉
  todayOnly = !!saved.today; todoOnly = !!saved.todo;
  if (['video', 'attachment'].includes(saved.media)) mediaFilter = saved.media;
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
}
let scrollTop = savedScroll;
function saveState() {
  LB.state.save({ q: committed, raw: lastRaw, input: search.value, cat: activeCat, topic: activeTopic, today: todayOnly, todo: todoOnly, media: mediaFilter, star: starOnly,
    selectMode, select: [...selected], scrollTop, cols, timeSort, timeRange, timeFrom, timeTo, exportImages });
}

// ── 多选栏（C1 放进吸顶区、C15 常用的留在栏上） ──
const selbar = mobile ? null : top.createEl('div', { cls: 'lbc-selbar' });
let selCount = null, starSel = null, aiBtn = null, expBtn = null, moreBtn = null, delBtn = null, clrBtn = null, selBusy = false;
if (selbar) {
  selbar.hidden = true;
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
  selbar.createEl('span', { cls: 'lbc-selhint', text: '按 Esc 退出多选' });
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
  if (!sc) return;
  if (a) {
    const fix = () => { if (!a.isConnected) return; const d = a.getBoundingClientRect().top - y0; if (Math.abs(d) >= 0.5) sc.scrollTop = Math.max(0, sc.scrollTop + d); };
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

// ── 网格 ──
const grid = wrap.createEl('div', { cls: 'lbc-grid' });
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
function colCount() { return simplePage ? 1 : lbcColumns(gridWidth(), { cols, narrow: narrow() }); }
function currentCols() { return cols || laidN || colCount(); }
function setCols(next) {
  next = Math.max(COLS_MIN, Math.min(COLS_MAX, Math.round(next)));
  if (next === cols) return false;
  cols = next; applyCols(); saveState();
  relayoutIfNeeded();
  LB.say(`瀑布流 ${cols} 列`, { ms: 1500 });
  const p = provider();
  if (p?.settings) { p.settings.catalogColumns = cols; clearTimeout(p.__lbColsSave); p.__lbColsSave = setTimeout(() => { try { p.saveSettings?.(); } catch {} }, 600); }
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

// ── 删除收藏（C3）：页内确认 → 移到回收站 → 只摘后端确认删掉的 ──
let deleting = false;
async function confirmDelete(list) {
  if (!list.length || deleting) return;
  const names = list.slice(0, 4).map(x => '《' + (x.title || x.id) + '》').join('、') + (list.length > 4 ? '…' : '');
  const ok = await LB.confirm({ title: `删除 ${list.length} 篇？`, body: names + '\n移到回收站，以后不再同步；可以在回收站恢复。', ok: '删除', danger: true });
  if (!ok || deleting) return;
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
    for (const id of gone) { selected.delete(id); const c = cardCache.get(id); c?.el?.remove(); cardCache.delete(id); }
    for (const c of cards) c.classList.remove('is-deleting');
    const left = list.filter(x => !gone.has(x.id));
    if (gone.size) { dataRev++; withAnchor(() => render()); }
    if (left.length && !mobile) { for (const x of left) selected.add(x.id); selectMode = true; }
    selectMode = selected.size > 0;
    paintSelectMode();
    if (!left.length) LB.say(`已删 ${gone.size} 篇（可在回收站恢复）`, { kind: 'ok' });
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
function openCardMenu(e, card, it) {
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
      { title: `删除选中的 ${n} 篇（移到回收站）`, danger: true, onClick: () => confirmDelete(sel()) },
      { title: '退出多选', onClick: () => clearSelection() },
    ];
  } else {
    list = [
      { title: it.starred ? '取消收藏' : '收藏', onClick: () => starMany([it], { single: true }) },
      { title: '编辑标签', onClick: () => openTagEditor(card, it) },
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
async function starMany(list, { single = false } = {}) {
  const on = single ? !list[0]?.starred : !list.every(x => x.starred);
  const todo = list.filter(x => !!x.starred !== on && !x._starBusy);
  if (!todo.length) return;
  const p = await want('starNotes'); if (!p) return;
  for (const x of todo) { x._prevStar = !!x.starred; x.starred = on; x._starBusy = true; paintCard(x.id); }
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
// 存一组：同名先确认再覆盖；写盘成功才提示（§1.5），失败对话框留着、字还在
async function storeSelection(name, list) {
  const rows = await readSelections();
  if (rows.some(r => r.name === name) && !(await LB.confirm({ title: `覆盖选集「${name}」？`, body: '已经有叫这个名字的选集，覆盖它吗？', ok: '覆盖' }))) return false;
  const row = { name, ids: list.map(x => x.id), created_at: new Date().toISOString() };
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
function rankKey() { return JSON.stringify([committed, activeCat, activeTopic, todayOnly, todoOnly, mediaFilter, starOnly || starredPage, timeSort, timeRange, timeFrom, timeTo, dataRev]); }
function rankRows() {
  const key = rankKey();
  if (lastRanked.key === key) return lastRanked;
  perfCounts.rank++;
  const q = normalize(committed);
  const today = ymd(new Date());
  const filtered = items.filter(it => (!(starredPage || starOnly) || it.starred) && (!mediaFilter || (mediaFilter === 'video' ? it.kind === 'video' : it.attachment && it.attachment !== 'none'))
    && (!todayOnly || it.date === today) && (!todoOnly || it.attachment === '待补') && (!activeCat || (it.cats || []).includes(activeCat))
    && (!activeTopic || (it.topics || []).includes(activeTopic)) && inTimeRange(it));
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
  return [activeCat, activeTopic && '★' + activeTopic, todayOnly && '今日新增', todoOnly && '待补附件', mediaFilter === 'video' && '视频', mediaFilter === 'attachment' && '附件',
    starOnly && !starredPage && '已收藏', timeRange && timeLabel().split(' · ')[0]].filter(Boolean).join(' · ');
}
function paintSub() {
  const r = lastRanked.key ? lastRanked : null;
  const filtered = !!(committed || todayOnly || todoOnly || starredPage || starOnly || mediaFilter || activeTopic || activeCat || timeRange);
  countEl.setText(filtered && r ? `${r.exact.length} / ${items.length} 篇` : `${items.length} 篇`);
  const nPossible = r && !grid.hidden ? r.possible.length : 0;
  possibleLink.hidden = !nPossible; sepPossible.hidden = !nPossible;
  if (nPossible) possibleLink.setText(`可能相关 ${nPossible}`);
  const built = LB.dataUpdatedAt(data);
  updatedBtn.setText(`更新 ${built ? fmtTime(built) : '—'}`);
  updatedBtn.title = `目录数据生成于 ${built ? fmtFull(built) : '—'}（同步或刷新目录后更新）· 点开看同步记录`;
  // F4 跨设备兜底：同步记录显示已经更新过，这台设备上的 catalog-data 还是旧的（同步盘没跟上）
  const last = Math.max(tsOf(syncState?.last_success), tsOf(probSummary?.last_success), tsOf(probSummary?.sync?.last_success));
  const behind = !!built && last > 0 && last - tsOf(built) > 10 * 60000 && !stale;
  staleEl.hidden = !behind;
  if (behind) staleEl.title = `同步记录显示 ${fmtTime(last)} 已更新，本机目录数据还是 ${fmtTime(built)} 的：等同步盘把 _archive/catalog-data.json 同步过来，或在电脑上刷新目录`;
}

// ── 卡片（§5.5 按 id 复用；C10：签名里没有星标 / 选中，状态只改 class） ──
const cardCache = new Map();
let firstCover = null;
function cardSig(it, fuzzy, low) {
  return JSON.stringify([it.title, it.cover, it.cover_w, it.cover_h, it.kind, it.attachment, it.attachment_reason, it.author, it.source, it.likes, it.note, it.problems || null, fuzzy, low || '']);
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
    const t = [...star.childNodes].find(n => n.nodeType === 3);
    if (t) t.textContent = it.starred ? '★' : '☆'; else star.prepend(it.starred ? '★' : '☆');
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
  const form = cached?.el?.querySelector?.('form.lbc-tagform');
  if (form) {
    const field = form.querySelector('input');
    const had = field && document.activeElement === field, s = field?.selectionStart, e = field?.selectionEnd;
    card.querySelector('.lbc-body')?.append(form);
    if (had) { try { field.focus({ preventScroll: true }); } catch { field.focus(); } try { field.setSelectionRange(s, e); } catch {} }
  }
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
  } else card.createEl('div', { cls: 'lbc-nocover', text: it.kind === 'video' ? '▷' : '▤' });
  // 附件角标：待补=有文件未下载（警示色），downloaded=有文件已下（灰）
  const badges = card.createEl('div', { cls: 'lbc-badges' });
  if (it.kind === 'video') { const v = badges.createEl('span', { cls: 'lbc-attach lbc-video' }); v.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>'; }
  if (it.attachment === '待补') badges.createEl('div', { cls: 'lbc-attach lbc-attach-todo', text: '待补' });
  else if (it.attachment === '线索') badges.createEl('div', { cls: 'lbc-attach lbc-attach-hint', text: '疑似附件', attr: { title: it.attachment_reason || '正文提到附件，但没找到文件' } });
  else if (it.attachment === 'downloaded') badges.createEl('div', { cls: 'lbc-attach', text: '文件' });
  const badge = badges.querySelector('.lbc-attach:not(.lbc-video)');
  if (badge) { try { const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); icon.setAttribute('viewBox', '0 0 24 24'); icon.innerHTML = '<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>'; badge.prepend(icon); } catch {} }
  // 第 4 批：这篇的问题标（灰；要你处理的用醒目色），悬停看原因；同一个标签只出一个，和上面附件标同名的不重复出；「未开启」不上卡片
  const shownLabels = new Set(Array.from(badges.querySelectorAll('.lbc-attach'), b => b.textContent)); const probs = new Map();
  for (const p of Array.isArray(it.problems) ? it.problems : []) {
    if (!p || !p.label || p.group === 'off' || shownLabels.has(p.label)) continue;
    const g = probs.get(p.label) || { need: false, hover: [] }; g.need = g.need || p.group === 'needs_you';
    const why = p.hover || p.reason; if (why && !g.hover.includes(why)) g.hover.push(why); probs.set(p.label, g);
  }
  for (const [label, g] of probs) { const b = badges.createEl('span', { cls: 'lbc-attach lbc-prob' + (g.need ? ' is-need' : ''), text: label }); if (g.hover.length) b.title = g.hover.join('\n'); }
  if (!mobile) {
    // 10-04：悬停就出现的选中圈——点它直接勾选（不用先进多选）；勾了任何一篇就是多选态，全取消就退出
    const check = card.createEl('button', { cls: 'lbc-check' }); check.type = 'button'; check.setAttribute('aria-pressed', 'false');
    check.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12.5l4 4 8-9"/></svg>';
    check.createEl('span', { cls: 'lb-visually-hidden', text: '选中' });
    check.onclick = e => { e?.preventDefault?.(); e?.stopPropagation?.(); toggleSelect(cur().id); };
    const star = card.createEl('button', { cls: 'lbc-star', text: '☆' }); star.type = 'button';
    star.createEl('span', { cls: 'lb-visually-hidden', text: '收藏' });
    star.onclick = e => { e?.preventDefault?.(); e?.stopPropagation?.(); const x = cur(); if (x._starBusy) return; starMany([x], { single: true }); };
  } else {
    // 手机：只给已收藏的篇显示一个不可点的 ★（C12）
    card.createEl('span', { cls: 'lbc-star is-on is-static', text: '★' });
  }
  const body = card.createEl('div', { cls: 'lbc-body' }); body.createEl('div', { cls: 'lbc-ctitle', text: it.title || '未命名' });
  if (low) body.createEl('div', { cls: 'lbc-lowhit', text: low });
  const meta = body.createEl('div', { cls: 'lbc-cmeta' }); meta.createEl('span', { text: it.author || it.source || '收藏' }); meta.createEl('span', { cls: 'lbc-likes', text: it.likes == null ? '' : '♡ ' + (Number(it.likes) >= 10000 ? (Number(it.likes) / 10000).toFixed(1) + '万' : it.likes) });
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
  const open = (e, forceNew = false) => {
    if (selectMode && !forceNew) { toggleSelect(cur().id); return; }
    const x = cur(); if (!x.note) return;
    const newTab = forceNew || !!(e && (e.ctrlKey || e.metaKey));
    saveState(); if (!newTab) leaving = true;
    app.workspace.openLinkText(lbPath(x.note), '', newTab);
  };
  card.onclick = e => open(e);
  card.onkeydown = e => { if (e.target === card && e.key === 'Enter') { e.preventDefault(); open(e); } };
  card.onauxclick = e => { if (e.button === 1) { e.preventDefault(); open(e, true); } };
  card.onmousedown = e => { if (e.button === 1) e.preventDefault(); };   // 不出自动滚动图标
  if (!mobile) card.oncontextmenu = e => { e.preventDefault(); openCardMenu(e, card, cur()); };
  paintCardState(card, it);
  return card;
}

// ── 多选（C10：只改这张卡的 class；进 / 出多选时补滚动，下面的卡不动） ──
function paintSelectMode() {
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
function layoutInto(box, rows, n) {
  box.empty();
  const W = gridWidth(), g = narrow() ? 14 : 24;
  const colW = n > 1 && W > 0 ? (W - g * (n - 1)) / n : (W || 230);
  box.style.setProperty('--lbc-gap', g + 'px');
  const heights = rows.map(r => lbcCardHeight(r.it, colW, { low: r.low }));
  const { cols: plan } = lbcAssign(heights, n);
  for (const idxs of plan) {
    const col = box.createEl('div', { cls: 'lbc-col' });
    const frag = document.createDocumentFragment();
    for (const i of idxs) frag.append(getCard(rows[i]));
    col.append(frag);
  }
}
function layoutGrid() {
  const r = rankRows();
  const n = colCount();
  perfCounts.layout++;
  laidKey = r.key; laidN = n;
  grid.empty();
  const shown = r.exact.length + r.possible.length;
  // 第 10 批：目录搜索是关键词精确筛选；想连同义词 / 语义一起找，一键带着这个词去问收藏
  if (committed && !committed.startsWith('#') && !mobile && shown) {
    const tip = grid.createEl('div', { cls: 'lbc-possible-note lbc-ask-tip', text: `按关键词筛选。想把同义词、相关内容也找出来 → 去问收藏搜「${committed}」` });
    tip.onclick = () => askInChat(committed);
  }
  if (simplePage && !starredPage && !committed && !activeCat && !activeTopic && !todayOnly && !todoOnly) { grid.createEl('div', { cls: 'lbc-empty', text: '输入关键词搜索收藏；想让 AI 分析，点上面的「问收藏」。' }); return; }
  if (!shown) { renderEmpty(); return; }
  const exactBox = grid.createEl('div', { cls: 'lbc-grid-inner lbc-masonry' });
  layoutInto(exactBox, r.exact, n);
  if (r.possible.length) {
    const headEl = grid.createEl('div', { cls: 'lbc-possible-head' });
    headEl.createEl('span', { cls: 'lbc-possible-title', text: `可能相关 · ${r.possible.length} 篇` });
    headEl.createEl('span', { cls: 'lbc-possible-note', text: '拼音相近、错一个字、漏字或图片里的零散字母，不是原词命中' });
    const possibleBox = grid.createEl('div', { cls: 'lbc-grid-inner lbc-grid-possible lbc-masonry' });
    layoutInto(possibleBox, r.possible, n);
  }
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
  if ((starOnly || starredPage) && !items.some(x => x.starred)) { text('还没有收藏的：在卡片上点 ☆'); return; }
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
  const r = rankRows();
  const n = colCount();
  if (r.key !== laidKey || n !== laidN) layoutGrid();
  paintSub();
  paintSelectMode();
  saveState();
}
function relayoutIfNeeded() { if (colCount() !== laidN) withAnchor(() => layoutGrid()); }
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
  const target = grid.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - top.offsetHeight - 8;
  if (sc.scrollTop > target + 4) sc.scrollTop = Math.max(0, target);
}
function scrollToPossible() {
  const sc = LB.scroller(); const h = grid.querySelector('.lbc-possible-head'); if (!sc || !h) return;
  const target = Math.max(0, h.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - top.offsetHeight - 8);
  try { sc.scrollTo({ top: target, behavior: 'smooth' }); } catch { sc.scrollTop = target; }
  if (typeof sc.scrollTo !== 'function') sc.scrollTop = target;
  h.tabIndex = -1; try { h.focus({ preventScroll: true }); } catch {}
}

// ── 搜索（C5：边打边搜；防抖按渲染耗时自适应 40–120ms；输入法组字中不搜；选完字 / 回车立刻搜） ──
let typingTimer = null, composing = false, renderEma = 30;
const now = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
const delay = () => Math.max(40, Math.min(120, 140 - renderEma));
// 目录只做搜索（0926 Owner）：整句（语音打进来的）搜不到时退成关键词再搜；规则在 catalog-search.js resolveQuery
function commitSearch() {
  clearTimeout(typingTimer); typingTimer = null;
  const raw = search.value.trim();
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
  search.value = q;
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
  dv.component.registerEvent(app.workspace.on('active-leaf-change', () => { if (stale && LB.activeLeafHas(wrap)) checkFresh(); }));
  // 星标以 catalog-data 为准 + link-brain:star 事件（§5.6）：只换这张卡的 ★，不重排（C2）
  dv.component.registerEvent(app.workspace.on('link-brain:star', (id, on) => { const it = items.find(x => x.id === id); if (it && !it._starBusy && !!it.starred !== !!on) { it.starred = !!on; paintCard(id); paintSelbar(); } }));
  // 10-03：「…→改标题 / 每行几列」改完就地换（不重建卡片）
  dv.component.registerEvent(app.workspace.on('link-brain:catalog-prefs', () => { titleLabel.setText(titleOf()); const c = savedCols(); if (c !== cols) { cols = c; applyCols(); relayoutIfNeeded(); } }));
  dv.component.registerEvent(app.workspace.on('link-brain:catalog-query', () => { if (takePendingQuery()) saveState(); }));
}
{ const winTarget = typeof window !== 'undefined' && window && typeof window.addEventListener === 'function' ? window : null;
  if (winTarget) LB.listen('focus-fresh', winTarget, 'focus', () => checkFresh()); }

// ── 吸顶的 top（主审裁决 1）：取滚动容器上内边距的负值，sticky 贴住滚动容器顶边，上方不留缝（主 / 副 split 里内边距不同，不写死） ──
function paintStickyTop() {
  const sc = LB.scroller(); if (!sc) return;
  let pad = 0;
  try { const cs = (typeof getComputedStyle === 'function') ? getComputedStyle(sc) : null; pad = parseFloat(cs?.paddingTop) || 0; } catch {}
  const v = pad ? `${-pad}px` : '0px';
  if (top.style.top !== v) top.style.top = v;
}
// ── ResizeObserver（C9）：宽度变了导致列数变了才重摆（下一帧、带锚点）；顺手重算吸顶 top ──
if (typeof ResizeObserver === 'function') {
  let pending = false;
  const ro = new ResizeObserver(entries => {
    const w = entries?.[0]?.contentRect?.width;
    if (w > 0) roWidth = Math.max(0, w - 10);
    paintStickyTop();
    if (pending) return; pending = true;
    requestAnimationFrame(() => { pending = false; if (colCount() !== laidN) withAnchor(() => layoutGrid()); });
  });
  ro.observe(grid);
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
const restoredWithPending = takePendingQuery();
// 上次离开时防抖还没触发（输入框里的字和上次搜的不一样）：恢复后补跑一次
if (!restoredWithPending && saved.ts && typeof saved.input === 'string' && saved.input.trim() !== lastRaw) commitSearch();
renderCatBar(); render();
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
// 登记这一版 DOM：Dataview 下次重跑时版本没变就原样挂回；变了走 refresh（只换数据、卡片复用；失败不推进版本）
LB.keep(wrap, { version: await LB.data.version(), update: () => { syncPerf(); return refresh({ strict: true }); }, onReuse: () => {
  syncPerf();
  if (refreshTags() && committed) dataRev++;
  takePendingQuery();
  const c = savedCols(); if (c !== cols && (c || LB.provider()?.settings)) { cols = c; applyCols(); }
  if (titleLabel.textContent !== titleOf()) titleLabel.setText(titleOf());
  render();
  paintStickyTop();
  if (stale) checkFresh();
} });
if (provider()?.focusCatalogSearch) { provider().focusCatalogSearch = false; search.focus(); }
else LB.restoreFocus(search, 'search');
if (savedScroll > 0 && !restoredWithPending) Promise.resolve(LB.restoreScroll(savedScroll)).then(() => paintToTop(LB.scroller()?.scrollTop || 0)).catch(() => {});   // 滚到位时记一笔 scroll-restored@
LB.t('restore');
LB.t('total');

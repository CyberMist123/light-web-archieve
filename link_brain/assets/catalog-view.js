const simplePage = false;
const starredPage = false;
// 第 2 批（CONVENTIONS §5）：共享前导 lb-page-lib.js 由 catalog.py 内联在本文件前面。
// Dataview 每 2.5 秒重跑本页：数据版本没变 → 上一次的整页 DOM 原样挂回（搜索框、滚动、多选都在）；变了 → 增量更新。
const LB = lbPageLib(dv, app, starredPage ? 'starred' : 'catalog');
if (await LB.reuseDom()) return;
const root = dv.container;
// 这个仓可能被挂进别的库的子目录（如 LER Vault/知识库【小红书】/）；数据里的路径都相对 lwa 仓根，统一过 lbPath 补挂载前缀。
const lbPath = LB.path;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-catalog');
const wrap=root.createEl('div',{cls:'lbc-wrap'+(simplePage?' lbc-simple':'')});
// 样式放进 wrap 里：复用时整个 wrap 挂回去，样式跟着走
const style = wrap.createEl('style');
style.textContent = `
.markdown-preview-view.lb-catalog,.markdown-source-view.lb-catalog{--file-line-width:100%;}
.lb-catalog .markdown-preview-sizer,.lb-catalog .markdown-preview-section,.lb-catalog .cm-sizer,.lb-catalog .cm-contentContainer,.lb-catalog .cm-content,.lb-catalog .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-catalog .inline-title,.lb-catalog .metadata-container{display:none!important;}
.lbc-wrap{width:100%;padding:24px clamp(8px,2vw,36px) 40px;box-sizing:border-box;font-family:var(--font-interface),"Segoe UI","Microsoft YaHei",sans-serif;}
.lbc-head{display:flex;flex-direction:column;align-items:center;text-align:center;gap:13px;margin:8px 0 22px;}
.lbc-titleblock{display:flex;flex-direction:column;align-items:center;gap:5px;}
.lbc-titlerow{display:flex;align-items:baseline;justify-content:center;gap:4px;}
.lbc-title{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:42px;font-weight:700;letter-spacing:.01em;line-height:1.05;}
.lbc-wrap button.lbc-import{border:0!important;background:transparent!important;box-shadow:none!important;outline:0;border-radius:0!important;height:auto!important;font-family:Georgia,'Playfair Display','Times New Roman',serif!important;font-style:italic;font-size:40px;font-weight:700;line-height:1;color:var(--text-normal);cursor:pointer;padding:0 4px;transition:color .12s;}
.lbc-import:hover{color:var(--interactive-accent);}
.lbc-subline{display:flex;gap:7px;align-items:center;justify-content:center;}
.lbc-search{width:100%!important;min-width:0;max-width:440px!important;text-align:center;height:36px!important;box-shadow:none!important;border-radius:0!important;background:transparent!important;border:0!important;border-bottom:1px solid var(--background-modifier-border)!important;padding:0 2px!important;}
.lbc-search:focus{border-bottom-color:var(--interactive-accent)!important;}
.lbc-sub{font-size:12px;color:var(--text-normal);white-space:nowrap;}
.lbc-sync{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:#e08a1e;color:#fff;font-size:11px;font-weight:700;font-family:sans-serif;cursor:pointer;flex:0 0 auto;}
.lbc-sync[hidden]{display:none;}
.lbc-wrap button.lbc-sync.lbc-account-status{width:16px;height:16px!important;min-height:0;padding:0!important;border:0!important;box-shadow:none!important;background:#e08a1e!important;color:#fff;font-size:11px;font-weight:700;border-radius:50%!important;}
.lbc-wrap button.lbc-sub.lbc-account-status{background:transparent!important;border:0!important;box-shadow:none!important;padding:0!important;height:auto!important;cursor:default;}
.lbc-account-status[hidden]{display:none!important;}
.lbc-grid{columns:250px;column-gap:32px;}
.lbc-card{display:inline-block;vertical-align:top;width:100%;margin:0 0 36px;break-inside:avoid;cursor:pointer;position:relative;}
.lbc-attach{position:absolute;top:8px;right:8px;font-size:11px;line-height:1;padding:4px 8px;border-radius:9px;background:rgba(0,0,0,.55);color:#fff;pointer-events:none;backdrop-filter:blur(2px);}
.lbc-attach-todo{background:#e08a1e;}.lbc-attach-hint{background:#9a9a9a;}
.lbc-cover{display:block;width:100%;height:auto;max-height:360px;object-fit:cover;object-position:top;border-radius:16px;border:1px solid var(--background-modifier-border);transition:filter .15s;pointer-events:none;}
.lbc-card:hover .lbc-cover{filter:brightness(.95);}
.lbc-card:focus-visible{outline:2px solid var(--interactive-accent);outline-offset:5px;border-radius:16px;}
.lbc-card.is-selected .lbc-cover,.lbc-card.is-selected .lbc-nocover{outline:3px solid var(--interactive-accent);outline-offset:2px;filter:brightness(.92);}
.lbc-selbar{display:flex;gap:12px;align-items:center;margin:0 0 18px;padding:10px 14px;border-radius:12px;background:var(--background-secondary);}
.lbc-selbar[hidden]{display:none!important;}
.lbc-selcount{font-size:13px;color:var(--text-muted);margin-right:auto;}
.lbc-selbar button{border:0;border-radius:8px;padding:6px 14px;}
.lbc-selbar button.mod-warning{background:#e5484d;color:#fff;font-weight:600;}
.lbc-selbar button.mod-warning:hover{background:#d13c41;}
.lbc-selbar button.mod-warning:disabled{opacity:.5;}
.lbc-menu{background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:5px;min-width:120px;}
.lbc-menu-item{padding:7px 14px;border-radius:7px;cursor:pointer;font-size:13px;}
.lbc-menu-item:hover{background:var(--background-modifier-hover);}
.lbc-menu-item.is-danger{color:var(--text-error,#c0392b);}
.lbc-nocover{aspect-ratio:4/3;border-radius:16px;background:var(--background-secondary);display:grid;place-items:center;color:var(--text-muted);font-size:30px;}
.lbc-body{padding:11px 8px 0;}
.lbc-ctitle{font-size:14px;line-height:1.7;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbc-cmeta{display:flex;justify-content:space-between;gap:10px;color:var(--text-muted);font-size:12px;margin-top:8px;}
.lbc-cmeta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbc-empty{padding:40px;color:var(--text-muted);}
.lbc-status{font-size:12px;color:var(--text-muted);}
.lbc-cats{display:flex;flex-wrap:wrap;align-items:center;margin:0 0 22px;font-size:13px;font-family:var(--font-interface),sans-serif;}
.lbc-cat{padding:4px 12px;cursor:pointer;color:var(--text-muted);border-radius:8px;transition:color .12s;}
.lbc-cat:hover{color:var(--text-normal);}
.lbc-cat.is-active{color:var(--interactive-accent);font-weight:600;}
.lbc-cat-sep{color:var(--background-modifier-border);user-select:none;pointer-events:none;}
.lbc-ai{max-width:820px;margin:30px auto;padding:0 12px;}.lbc-ai[hidden],.lbc-grid[hidden]{display:none!important;}
.lbc-ai-q{color:var(--text-muted);font-size:13px;margin:6px 0 12px;}
.lbc-ai-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px;}
.lbc-ai-answer{line-height:1.7;}
.lbc-ai-answer p:first-child{margin-top:0;}
.lbc-ai-meta{color:var(--text-faint);font-size:11px;margin-top:14px;}
.lbc-ans-card{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--background-modifier-border);}
.lbc-ans-card:last-child{border-bottom:0;}
.lbc-ans-thumb{flex:0 0 68px;width:68px;height:68px;border-radius:10px;overflow:hidden;cursor:pointer;background:var(--background-secondary);}
.lbc-ans-thumb img{width:100%;height:100%;object-fit:cover;object-position:top;pointer-events:none;}
.lbc-ans-thumb:hover{filter:brightness(.93);}
.lbc-ans-nocover{width:100%;height:100%;display:grid;place-items:center;color:var(--text-muted);}
.lbc-ans-body{flex:1;min-width:0;}
.lbc-ans-title{font-size:13px;font-weight:600;margin-bottom:3px;}
.lbc-ans-excerpt{font-size:12.5px;line-height:1.6;color:var(--text-muted);}
.lbc-ai-error{padding:12px 14px;border-radius:10px;background:var(--background-modifier-error,rgba(220,80,80,.12));color:var(--text-error,#c0392b);}
.lbc-ai-error strong{display:block;margin-bottom:4px;}
.lbc-wrap button{font-family:inherit;}
.lbc-attach{display:flex;align-items:center;gap:4px;background:var(--background-primary);color:var(--text-muted);border:1px solid var(--background-modifier-border);border-radius:6px;padding:4px 6px;backdrop-filter:none;}
.lbc-attach-todo{color:#a86513;background:#fff8eb;border-color:#e8d8bc;}.lbc-attach-hint{color:var(--text-muted);background:var(--background-secondary);border-color:var(--background-modifier-border);}
.lbc-attach svg{width:12px;height:12px;}
.lbc-view-switch{font-size:12px!important;color:var(--text-muted);background:transparent!important;border:0!important;box-shadow:none!important;}
.lbc-simple .lbc-grid{columns:auto;max-width:820px;margin:0 auto;}
.lbc-simple .lbc-card{display:block;margin:0;padding:18px 0;border-bottom:1px solid var(--background-modifier-border);}
.lbc-simple .lbc-cover,.lbc-simple .lbc-nocover{display:none;}
.lbc-simple .lbc-attach{top:20px;}
.lbc-simple .lbc-body{padding:0 80px 0 0;}
.lbc-simple .lbc-cmeta{justify-content:flex-start;}
.lbc-simple .lbc-head{max-width:820px;margin:25px auto 35px;}
.lbc-simple .lbc-cats{max-width:820px;margin:0 auto 25px;}
.lbc-result-excerpt{font-size:13px;color:var(--text-muted);line-height:1.7;margin-top:6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbc-turn{margin:0 0 30px;line-height:1.8;font-size:15px;overflow-wrap:anywhere;}
.lbc-user{margin-left:auto;padding:10px 16px;border-radius:15px;background:var(--background-secondary);max-width:85%;width:fit-content;white-space:pre-wrap;}
.lbc-sources{font-size:12px;color:var(--text-muted);margin:14px 0;}
.lbc-sources a{display:block;margin:6px 0;cursor:pointer;}
.lbc-follow{display:flex;gap:8px;align-items:flex-end;margin-top:24px;}
.lbc-follow textarea{flex:1;min-height:70px;resize:vertical;border-radius:14px;padding:12px;font-family:inherit;}
@media(max-width:650px){.lbc-grid{columns:180px;column-gap:18px;}.lbc-sub{width:100%;margin:0;}.lbc-wrap{padding:12px 4px;}}

.lb-page-nav{display:flex;grid-column:2;grid-row:1;gap:2px;padding:4px;background:var(--background-secondary);border-radius:12px;justify-self:center;white-space:nowrap;}
.lb-page-nav button{font:inherit;font-size:13px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);border-radius:9px;padding:9px 16px;height:auto;cursor:pointer;}
.lb-page-nav button.is-current{background:var(--background-primary)!important;color:var(--text-normal);box-shadow:0 1px 4px #0000000c!important;font-weight:500;}
.lb-manage{font-size:24px!important;font-weight:500;background:transparent!important;border:0!important;box-shadow:none!important;color:var(--text-muted);padding:0!important;width:40px;height:40px;border-radius:10px;cursor:pointer;}
.lb-manage:hover{background:var(--background-secondary)!important;color:var(--text-normal);}
.lbc-wrap button:focus-visible,.lbchat button:focus-visible{outline:2px solid var(--interactive-accent)!important;outline-offset:3px;}
.lbc-live,.lbchat-live{white-space:pre-wrap;}

.lbc-wrap{max-width:1440px;margin:0 auto;padding:32px clamp(16px,3vw,48px) 64px;font-family:"Noto Sans SC","Segoe UI","Microsoft YaHei UI",sans-serif;}
.lbc-head{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;text-align:left;gap:28px 20px;margin:0 0 24px;}
.lbc-titleblock{align-items:flex-start;gap:10px;grid-column:1;grid-row:1;}
.lbc-title{color:var(--text-normal);}
.lbc-tools{grid-column:3;grid-row:1;justify-self:end;display:flex;align-items:center;gap:10px;}
.lbc-wrap button.lbc-import{width:40px;height:44px!important;border-radius:10px!important;padding:0;}
.lbc-wrap button.lbc-import:hover{color:var(--interactive-accent);}
.lbc-sub{color:var(--text-faint);font-size:11px;letter-spacing:.06em;}
.lbc-search{grid-column:1/-1;grid-row:2;justify-self:start;max-width:520px!important;text-align:left;height:44px!important;padding:0 15px!important;border:1px solid var(--background-modifier-border)!important;border-radius:12px!important;background:var(--background-secondary)!important;font:inherit;font-size:14px;}
.lbc-search:focus{border-color:var(--interactive-accent)!important;outline:none;}
.lbc-cats{gap:24px;flex-wrap:nowrap;overflow-x:auto;padding-bottom:5px;margin-bottom:28px;font-family:inherit;}
.lbc-cats button.lbc-cat{flex:none;border:0!important;border-bottom:2px solid transparent!important;background:transparent!important;box-shadow:none!important;padding:8px 0;border-radius:0;height:auto;font-size:13px;font-weight:400;}
.lbc-cats button.is-active{color:var(--text-normal);border-bottom-color:var(--text-normal)!important;font-weight:500;}
.lbc-grid{columns:240px;column-gap:28px;}
.lbc-card{margin-bottom:32px;}
.lbc-cover,.lbc-nocover{border:0;border-radius:12px;transition:transform .16s,box-shadow .16s;}
.lbc-card:hover .lbc-cover{filter:none;transform:translateY(-2px);box-shadow:0 6px 18px #00000012;}
.lbc-body{padding:12px 2px 0;}
.lbc-ctitle{font-size:15px;font-weight:500;line-height:1.6;}
.lbc-cmeta{margin-top:8px;padding-right:0;font-weight:300;}.lbc-likes{flex-shrink:0;transition:opacity .12s;}.lbc-card:hover .lbc-likes,.lbc-card:focus-within .lbc-likes{opacity:0;}
.lbc-card-more{position:absolute;right:0;bottom:-4px;width:28px;height:28px;padding:0!important;border:0!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:20px;opacity:0;}
.lbc-card:hover .lbc-card-more,.lbc-card:focus-within .lbc-card-more{opacity:1;}
.lbc-menu-item{display:block;width:100%;text-align:left;border:0;background:transparent;color:var(--text-normal);box-shadow:none;height:auto;}
@media(max-width:700px){.lbc-wrap{padding:20px 12px 48px;}.lbc-head{grid-template-columns:1fr auto;gap:24px 10px;}.lbc-tools{grid-column:2;}.lbc-title{font-size:34px;}.lbc-wrap button.lbc-import{font-size:32px;}.lbc-head .lb-page-nav{grid-column:1/-1;grid-row:2;justify-self:start;}.lbc-search{grid-row:3;max-width:none!important;}.lbc-grid{columns:150px;column-gap:16px;}.lbc-cats{gap:22px;}.lbc-ctitle{font-size:14px;}.lbc-card-more{opacity:1;}.lbc-sub{width:auto;}.lbc-simple .lbc-head{margin:0 0 24px;}}

/* The waterfall grows with the page; only its header sticks while scrolling. */
.lbc-wrap{height:auto;display:block;padding:22px 24px 30px;overflow:visible;}
.lbc-top{position:sticky;top:0;background:var(--background-primary);z-index:2;}
.lbc-head{gap:18px;margin-bottom:12px;grid-template-columns:1fr auto;}
.lbc-title{font-size:32px;}.lbc-tools{grid-column:2;}.lb-page-nav{grid-column:1;grid-row:2;justify-self:start;padding:0;background:transparent;}
.lbc-search{grid-row:3;max-width:none!important;height:40px!important;border-radius:8px!important;}
.lbc-cats{gap:20px;margin:0;padding:0 0 12px;}.lbc-sub{font-size:10px;}
.lbc-grid{height:auto;overflow:visible;columns:auto;display:block;padding:12px 5px 30px;}
.lbc-grid-inner{columns:230px;column-gap:24px;}
.lbc-card{margin-bottom:26px;}.lbc-ctitle{font-size:14px;}.lbc-cmeta{font-size:11px;}
.lbc-star{position:absolute;right:8px;top:8px;width:30px;height:30px;padding:0!important;border:0!important;border-radius:50%;background:var(--background-primary)!important;color:var(--text-muted);box-shadow:0 1px 5px #0002!important;font-size:21px;cursor:pointer;}
.lbc-star.is-on{color:var(--text-normal);}.lbc-attach{right:auto;left:8px;}@media(hover:none){.lbc-card-more{opacity:1;}.lbc-cmeta{padding-right:30px;}.lbc-card:hover .lbc-likes{opacity:1;}}
@media(max-width:700px){.lbc-wrap{padding:12px 6px 0;}.lbc-head{gap:12px;}.lbc-title{font-size:28px;}.lbc-grid-inner{columns:145px;column-gap:14px;}.lbc-cats{gap:18px;}}

.lb-visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
.lbc-star{opacity:0;pointer-events:none;transition:opacity .15s;}.lbc-card:hover .lbc-star,.lbc-card:focus-within .lbc-star{opacity:1;pointer-events:auto;}
@media(hover:none){.lbc-star{opacity:1;pointer-events:auto;}}
.lbc-badges{position:absolute;top:8px;left:8px;display:flex;gap:5px;align-items:center;}
.lbc-badges .lbc-attach{position:static;display:inline-flex;align-items:center;line-height:16px;padding:3px 6px;gap:4px;height:22px;box-sizing:border-box;}
.lbc-badges svg{display:block;width:14px;height:14px;flex:none;stroke:currentColor;stroke-width:1.6;fill:none;}
.lbc-simple .lbc-grid-inner{columns:auto;}.lbc-simple .lbc-card{padding:18px 42px 18px 0;}.lbc-simple .lbc-body{padding:0;}.lbc-simple .lbc-badges{position:static;float:right;margin:2px 0 0 12px;}.lbc-simple .lbc-star{top:16px;right:0;}.lbc-simple .lbc-cmeta{margin-top:4px;}
.lbchat-bookmark svg{width:18px;height:18px;display:block;stroke:currentColor;stroke-width:1.6;fill:none;}.lbchat-bookmark.is-saved svg{fill:currentColor;}
.lbchat .lbchat-composer{margin-top:24px;margin-bottom:14px;}.lbchat{height:calc(100vh - 80px);}

.lbc-titleblock{align-items:center;width:max-content;max-width:100%;}
.lbc-titlerow{align-items:center;gap:10px;}
/* 0925：「+」放进标题里继承同一套字（斜体衬线、同字号），与 09-18 版一致（粗斜衬线、正文色、悬停主题色） */.lbc-wrap .lbc-title button.lbc-import{font:inherit!important;color:var(--text-normal)!important;transition:color .12s;width:auto!important;height:auto!important;padding:0 0 0 .12em!important;margin:0!important;border:0!important;background:transparent!important;box-shadow:none!important;border-radius:0!important;display:inline!important;vertical-align:baseline;line-height:inherit!important;cursor:pointer;}.lbc-wrap .lbc-title button.lbc-import:hover{color:var(--interactive-accent)!important;}
.lb-manage{font-family:Arial,sans-serif!important;line-height:1!important;display:grid;place-items:center;}
/* 星标主题 chip（Lot E）：cats 栏下一排，只在有主题时出现；与 cats 同字族，胶囊外框 + ★ 区分。 */
.lbc-topics{display:flex;align-items:center;gap:8px;flex-wrap:nowrap;overflow-x:auto;margin:0;padding:0 0 12px;font-family:inherit;}
.lbc-topics button.lbc-topic{flex:none;height:auto;padding:3px 11px;border:1px solid var(--background-modifier-border)!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:12px;font-weight:400;line-height:1.6;cursor:pointer;transition:color .12s,border-color .12s;}
.lbc-topics button.lbc-topic:hover{color:var(--text-normal);}
.lbc-topics button.lbc-topic.is-active{color:var(--text-normal);border-color:var(--text-normal)!important;font-weight:500;}
.lbc-topic-star{color:#d9a21b;margin-right:4px;}
/* 搜索结果（1002 她定）：卡片只留标题，不显示命中摘录；模糊命中单独一组「可能相关」。 */
.lbc-possible-head{display:flex;align-items:baseline;gap:10px;margin:8px 5px 16px;padding-top:14px;border-top:1px solid var(--background-modifier-border);}
.lbc-possible-title{font-size:13px;font-weight:500;color:var(--text-muted);}
.lbc-possible-note{font-size:11px;color:var(--text-faint);}
.lbc-card.is-possible .lbc-cover{opacity:.85;}

`;
// 刚部署了新插件、内存里还是旧实例（缺新方法）：重载一次；正在同步 / 导入时不动它
if(LB.provider() && typeof LB.provider().openAttachments!=='function') await LB.ensure('openAttachments').catch(()=>{});
let data;
try { data = await LB.data.load(); }
catch { wrap.createEl('p',{text:'目录尚未生成，请在归档操作中重建目录。'}); return; }
let items = data.items || [];
// 笔记当前的标签（后台插件增删标签不必重建目录）：读 Obsidian 的元数据缓存，不走 dv.page 逐篇序列化
function tagsOf(it){
  if(!it.note)return null;
  try{const fm=app.metadataCache?.getCache?.(lbPath(it.note))?.frontmatter;if(fm&&fm.tags!==undefined)return typeof fm.tags==='string'?[fm.tags]:Array.from(fm.tags||[]);}catch{}
  const page=dv.page?.(lbPath(it.note));
  if(page&&page.tags!==undefined)return typeof page.tags==='string'?[page.tags]:Array.from(page.tags||[]);
  return null;
}
function refreshTags(){let changed=0;for(const it of items){const tags=tagsOf(it);if(tags&&JSON.stringify(tags)!==JSON.stringify(it.tags||[])){it.tags=tags;changed++;}}return changed;}
refreshTags();
const provider=LB.provider;
let committed='',chatMode=false,messages=[],busy=false;
// 数据变了（同步进来新的、删了、挂了附件）：不重建整页，只换数据再画卡片（卡片按 id 复用，见 render）
async function refresh(next){
  try{data=await LB.data.load();}catch{if(!next)return;data=next;}
  items=data.items||[];refreshTags();renderCatBar();render();
  const view=root.__lbView;if(view)view.version=await LB.data.version();   // 已经是新数据了：下一次 Dataview 重跑别再更新一遍
}
function attachmentPanel(list){if(typeof provider()?.openAttachments!=='function'){importStatus.setText('附件工具未载入，请重新启用 Link Brain Actions 插件。');return;}provider().openAttachments(list,refresh);}
function editCategories(selected=''){provider()?.openCategories(data.cats||[],selected,refresh);}
// 第一行：左=标题「Collections +」+ 其下计数·更新·未同步(!)；右=搜索横线。
const top=wrap.createEl('div',{cls:'lbc-top'});
const head=top.createEl('div',{cls:'lbc-head'});
const titleBlock=head.createEl('div',{cls:'lbc-titleblock'});
const titleRow=titleBlock.createEl('div',{cls:'lbc-titlerow'});
const titleText=titleRow.createEl('span',{cls:'lbc-title',text:'Collections'});
const tools=head.createEl('div',{cls:'lbc-tools'});
const importButton=titleText.createEl('button',{cls:'lbc-import',text:'+'});
const subLine=titleBlock.createEl('div',{cls:'lbc-subline'});
let todayOnly=false;
const sub=subLine.createEl('span',{cls:'lbc-sub'});
// 0927 Owner：只留一个「!」，只报要人处理的错（同步/账号）；附件待补会自动重跑，补齐入口只在底栏。
let todoCount=0;
// 0926 Owner：按老样子——只有出问题时才在计数后面出一个橙色圆「!」，悬停看原因，点一下直接修。
const accountStatus=subLine.createEl('button',{cls:'lbc-sync lbc-account-status'});accountStatus.hidden=true;
// 同步状态：出问题时是「! 需要登录 / 需要验证 / 同步失败」，点一下直接进入修复（扫码 / 验证窗口）。
let syncState=null;
async function refreshSyncStatus(){
  try { let s=JSON.parse(await app.vault.adapter.read(lbPath('_archive/sync-status.json'))); if(s&&s.state==='running'&&s.pid){let alive=true;try{process.kill(s.pid,0);}catch(e){alive=e.code==='EPERM';}if(!alive)s={...s,state:'failed',code:'INTERRUPTED',message:'上次同步中途被打断（Obsidian 关闭或进程被结束），已抓的都在；再点一次同步会接着来',detail:s.progress||''};} syncState=s; } catch { syncState=null; }
  const st=syncState||{};
  const label={NOT_LOGGED_IN:'需要登录',CAPTCHA_REQUIRED:'需要验证',WRONG_ACCOUNT:'登错号',INTERRUPTED:'同步被打断',DISCONNECTED:'服务未运行',NOT_INSTALLED:'未安装读取组件'}[st.code]
    ||(st.state==='blocked'?(st.account?'需要登录':'同步暂停'):st.state==='failed'?'同步失败':'');
  syncLabel=label;paintBadge();
}
let syncLabel='';
function paintBadge(){
  const st=syncState||{};const label=syncLabel;
  const why=[label&&label+(st.detail||st.message?'：'+(st.detail||st.message):'')].filter(Boolean);
  accountStatus.empty();accountStatus.className='lbc-sync lbc-account-status';
  if(why.length){accountStatus.setText('!');accountStatus.title=why.join('\n')+'\n点击处理';}
  else if(st.state==='running'){accountStatus.className='lbc-sub lbc-account-status';accountStatus.setText('· 同步中…');accountStatus.title='';}
  // 0926 Owner：已同步就不显示，只有报错才出现
  accountStatus.hidden=!why.length&&st.state!=='running';
}
accountStatus.onclick=async()=>{
  try { await (await LB.ensure('fixFromCatalog')).fixFromCatalog(); }
  catch(error){try{new Notice(error.message,10000);}catch{window.alert(error.message);}}
};
await refreshSyncStatus();
if(app.vault.on && dv.component?.registerEvent){
  const update=file=>{if(file.path===lbPath('_archive/sync-status.json'))refreshSyncStatus();};
  dv.component.registerEvent(app.vault.on('modify',update));
  dv.component.registerEvent(app.vault.on('create',update));
}
const search=head.createEl('input',{cls:'lbc-search'});
search.type='search';search.placeholder='搜索收藏…';
const pageNav=head.createEl('nav',{cls:'lb-page-nav'});
const browse=pageNav.createEl('button',{text:'浏览收藏',cls:'is-current'});browse.setAttribute('aria-current','page');browse.onclick=()=>provider().openLibraryPage('catalog');
const ask=pageNav.createEl('button',{text:'问收藏'});ask.onclick=()=>provider().openLibraryPage('chat');
const importStatus=wrap.createEl('div',{cls:'lbc-status'});
const manage=tools.createEl('button',{cls:'lb-manage',text:'…'});
manage.onclick=e=>provider()?.openManageMenu(e,{categories:()=>editCategories()});
importButton.type='button';

importButton.onclick=async e=>{
  e.preventDefault();e.stopPropagation();importStatus.setText('');
  try{
    if(typeof LB.provider()?.openPlusMenu!=='function')importStatus.setText('正在载入…');
    (await LB.ensure('openPlusMenu')).openPlusMenu(e);importStatus.setText('');
  }catch(error){importStatus.setText('菜单未打开：'+error.message);}
};
// 大类筛选条（小红书式 tab，灰竖线分隔）：单选，一次一个；「全部」或再点当前项清空。
let activeCat='';let todoOnly=false,mediaFilter='',starOnly=starredPage;
// 星标主题（Lot E）：单选，再点取消；可与大类叠加过滤。没有主题时 activeTopic 恒为空、整行不建。
let activeTopic='',topicBar=null;
const catBar=top.createEl('div',{cls:'lbc-cats'});
function renderCatBar(){
  catBar.empty();
  const mk=(label,active,on)=>{const s=catBar.createEl('button',{cls:'lbc-cat'+(active?' is-active':''),text:label});s.setAttribute('aria-pressed',String(active));s.onclick=()=>{if(label!=='…')chatMode=false;on();};return s;};
  mk('全部',!activeCat&&!todayOnly&&!todoOnly&&!mediaFilter&&!starOnly&&!activeTopic,()=>{if(starredPage){provider().openLibraryPage('catalog');return;}if(activeCat||todayOnly||todoOnly||mediaFilter||starOnly||activeTopic){activeCat='';todayOnly=false;todoOnly=false;mediaFilter='';starOnly=false;activeTopic='';renderCatBar();render();}});
  mk('今日新增',todayOnly,()=>{todayOnly=!todayOnly;if(todayOnly)todoOnly=false;renderCatBar();render();});
  mk('已收藏',starredPage,()=>provider().openLibraryPage(starredPage?'catalog':'starred'));
  mk('视频',mediaFilter==='video',()=>{mediaFilter=mediaFilter==='video'?'':'video';renderCatBar();render();});
  mk('附件',mediaFilter==='attachment',()=>{mediaFilter=mediaFilter==='attachment'?'':'attachment';renderCatBar();render();});
  const todo=items.filter(x=>x.attachment==='待补').length;
  if(todo)mk(`待补附件 ${todo}`,todoOnly,()=>{todoOnly=!todoOnly;if(todoOnly)todayOnly=false;renderCatBar();render();});
  for(const cat of (data.cats_order||[]).filter(c=>!(provider()?.settings.hiddenCats||[]).includes(c))){
    const tab=mk(cat,activeCat===cat,()=>{activeCat=(activeCat===cat?'':cat);renderCatBar();render();});
    tab.oncontextmenu=e=>{e.preventDefault();editCategories(cat);};
  }
  renderTopicBar();
}
function renderTopicBar(){
  const names=Array.isArray(data.topics)?data.topics.filter(n=>typeof n==='string'&&n):[];
  if(!names.includes(activeTopic))activeTopic='';
  if(!names.length){if(topicBar){topicBar.remove();topicBar=null;}return;}
  if(!topicBar)topicBar=top.createEl('div',{cls:'lbc-topics'});
  topicBar.empty();
  for(const name of names){
    // 不设 aria-label / title：Obsidian 会渲染成悬浮框（她不要）。
    const chip=topicBar.createEl('button',{cls:'lbc-topic'+(activeTopic===name?' is-active':'')});
    chip.createEl('span',{cls:'lbc-topic-star',text:'★'});chip.append(name);
    chip.setAttribute('aria-pressed',String(activeTopic===name));
    chip.onclick=()=>{chatMode=false;activeTopic=(activeTopic===name?'':name);renderCatBar();render();};
  }
}
// 多选删除状态
let selectMode=false;const selected=new Set();
// 页面状态（§5.3）：打开一篇再返回 / 页面被重建后，搜索词、筛选、多选、滚动位置照旧
const saved=LB.state.load();
let savedScroll=0;
if(saved.ts){
  committed=typeof saved.q==='string'?saved.q:'';
  if(typeof saved.cat==='string'&&(data.cats_order||[]).includes(saved.cat))activeCat=saved.cat;
  if(typeof saved.topic==='string')activeTopic=saved.topic;   // renderTopicBar 会把已不存在的主题清掉
  todayOnly=!!saved.today;todoOnly=!!saved.todo;
  if(['video','attachment'].includes(saved.media))mediaFilter=saved.media;
  if(!starredPage)starOnly=!!saved.star;
  const known=new Set(items.map(x=>x.id));
  for(const id of Array.isArray(saved.select)?saved.select:[])if(known.has(id))selected.add(id);
  selectMode=!!saved.selectMode;
  savedScroll=Number(saved.scrollTop)||0;
}
let scrollTop=savedScroll;
function saveState(){
  LB.state.save({q:committed,input:search.value,cat:activeCat,topic:activeTopic,today:todayOnly,todo:todoOnly,media:mediaFilter,star:starOnly,
    selectMode,select:[...selected],scrollTop});
}
const selbar=wrap.createEl('div',{cls:'lbc-selbar'});selbar.hidden=true;
const selCount=selbar.createEl('span',{cls:'lbc-selcount'});
const imageLabel=selbar.createEl('label',{text:'附带原图 '});const bundleImages=imageLabel.createEl('input');bundleImages.type='checkbox';bundleImages.checked=true;
const expBtn=selbar.createEl('button',{text:'导出资料包'});
expBtn.onclick=async()=>{const sel=items.filter(x=>selected.has(x.id));if(!sel.length){window.alert('先选几篇');return;}expBtn.disabled=true;expBtn.setText('导出中…');try{const {path}=await provider().exportArchiveBundle(sel.map(x=>x.id),bundleImages.checked,'',{question:search.value||'选中收藏'});expBtn.setText('导出资料包');try{new Notice('已导出机读版 → '+path);}catch{}}catch(e){expBtn.setText('导出失败');window.alert('导出失败：'+e.message);}finally{setTimeout(()=>{expBtn.disabled=false;expBtn.setText('导出资料包');},1500);}};
const copyBundle=selbar.createEl('button',{text:'复制文件包'});copyBundle.onclick=async()=>{copyBundle.disabled=true;try{await provider().exportArchiveBundle(items.filter(x=>selected.has(x.id)).map(x=>x.id),bundleImages.checked,'',{question:search.value||'选中收藏',copy:true});}catch(e){window.alert(e.message);}finally{copyBundle.disabled=false;}};
const delBtn=selbar.createEl('button',{text:'删除选中',cls:'mod-warning'});
delBtn.onclick=()=>confirmDelete(items.filter(x=>selected.has(x.id)));
const clrBtn=selbar.createEl('button',{text:'退出多选'});clrBtn.onclick=()=>{selectMode=false;selected.clear();render();};
const ai=wrap.createEl('section',{cls:'lbc-ai'});ai.hidden=true;
const grid=wrap.createEl('div',{cls:'lbc-grid'});

// 删除收藏：确认 → 移到回收站 → 本地从 items 摘掉 → 重渲染
async function confirmDelete(list){
  if(!list.length)return;
  const names=list.slice(0,4).map(x=>x.title||x.id).join('、')+(list.length>4?` 等 ${list.length} 篇`:'');
  if(!window.confirm(`删除收藏：${names}\n\n将移入回收站，不再同步；可以在回收站恢复。确定吗？`))return;
  const provider=app.plugins.plugins['link-brain-actions'];
  if(typeof provider?.deleteItems!=='function'){window.alert('删除功能需要启用 Link Brain Actions 插件');return;}
  try{
    const r=await provider.deleteItems(list.map(x=>x.id));
    const gone=new Set((r.results||[]).filter(x=>x.status==='deleted').map(x=>x.item_id));
    for(let i=items.length-1;i>=0;i--)if(gone.has(items[i].id))items.splice(i,1);
    selected.clear();render();
  }catch(e){window.alert('删除失败：'+e.message);}
}
// 右键编辑标签
function openTagEditor(body,it){
  if(body.querySelector('form'))return;
  const form=body.createEl('form');form.onclick=e=>e.stopPropagation();form.onkeydown=e=>e.stopPropagation();
  const field=form.createEl('input');field.type='text';field.value=(it.tags||[]).join(', ');field.placeholder='标签，用逗号分隔';field.style.width='100%';
  const save=form.createEl('button',{text:'保存标签'});save.type='submit';
  const cancel=form.createEl('button',{text:'取消'});cancel.type='button';cancel.onclick=()=>form.remove();
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;
    try{const file=app.vault.getAbstractFileByPath(lbPath(it.note));const tags=[...new Set(field.value.split(/[,，\n]/).map(t=>t.trim().replace(/^#/, '')).filter(Boolean))];
      await app.fileManager.processFrontMatter(file,fm=>{fm.tags=tags;});it.tags=tags;searchCache.delete(it);render();
    }catch{save.disabled=false;save.setText('保存失败，重试');}
  };field.focus();
}
// 右键小菜单：编辑标签 / 删除收藏
function openCardMenu(e,body,it){
  document.querySelectorAll('.lbc-menu').forEach(m=>m.remove());
  const menu=document.body.createEl('div',{cls:'lbc-menu'});
  menu.style.cssText=`position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:9999;`;
  const add=(label,fn,danger)=>{const b=menu.createEl('button',{cls:'lbc-menu-item'+(danger?' is-danger':'')});b.setText(label);b.onclick=ev=>{ev.stopPropagation();menu.remove();fn();};};
  add('编辑标签',()=>openTagEditor(body,it));
  if(it.attachment!=='none'){add('下载 / 挂本地文件',()=>attachmentPanel([it]));}
  if(typeof provider()?.refineImages==='function')add('精细识别图片',()=>provider().refineImages(it.item_id||it.id));
  add('删除收藏',()=>confirmDelete([it]),true);
  add('多选删除',()=>{selectMode=true;selected.add(it.id);render();});
  add('多选导出机读版',()=>{selectMode=true;selected.add(it.id);render();});
  const rect=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(e.clientX,innerWidth-rect.width-8))+'px';menu.style.top=Math.max(8,Math.min(e.clientY,innerHeight-rect.height-8))+'px';
  const close=()=>{menu.remove();document.removeEventListener('click',close);document.removeEventListener('contextmenu',close);};
  setTimeout(()=>{document.addEventListener('click',close);document.addEventListener('contextmenu',close);},0);
}
// 卡片按 id 复用（§5.5）：内容和选中状态都没变的卡片原样挂回，封面图不重载、不闪；变了的才重建。
const cardCache=new Map();
function cardSig(it,fuzzy){
  return JSON.stringify([it.title,it.cover,it.cover_w,it.cover_h,it.kind,it.attachment,it.attachment_reason,!!it.starred,it.author,it.source,it.likes,it.note,
    fuzzy,selectMode&&selected.has(it.id)]);
}
function render(){renderGrid();saveState();}
function renderGrid(){
  grid.empty();const exactCards=grid.createEl('div',{cls:'lbc-grid-inner'});const q=normalize(committed);const asking=chatMode;
  const now=new Date();const today=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  const filtered=items.filter(it=>(!(starredPage||starOnly)||it.starred)&&(!mediaFilter||(mediaFilter==='video'?it.kind==='video':it.attachment&&it.attachment!=='none'))&&(!todayOnly||it.date===today)&&(!todoOnly||it.attachment==='待补')&&(!activeCat||(it.cats||[]).includes(activeCat))&&(!activeTopic||(it.topics||[]).includes(activeTopic)));
  // 第 1 批 1002：先看分数、星标只 ×1.15；拼音 / 错字 / 漏字这类模糊命中单独放「可能相关」，规则见 catalog-search.js rankItems
  const ranked=rankItems(filtered,q,data.pinyin_chars,data.aliases||[]);
  const shown=[...ranked.exact,...ranked.possible];
  sub.setText((q||todayOnly||todoOnly||starredPage||mediaFilter||activeTopic?`${ranked.exact.length} / ${items.length} 篇`+(ranked.possible.length?` · 可能相关 ${ranked.possible.length}`:''):`${items.length} 篇`)+` · 更新 ${new Date(data.built_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}`);
  todoCount=items.filter(x=>x.attachment==='待补').length;paintBadge();
  ai.hidden=!asking;grid.hidden=asking;
  if(asking){selbar.hidden=true;return;}
  if(simplePage&&!starredPage&&!q&&!activeCat&&!activeTopic&&!todayOnly&&!todoOnly){grid.createEl('div',{cls:'lbc-empty',text:'输入关键词搜索收藏；想让 AI 分析，点上面的「问收藏」。'});selbar.hidden=true;return;}
  selbar.hidden=!selectMode;
  if(selectMode){selCount.setText(`已选 ${selected.size} 篇 · 点封面继续勾选 · ESC 退出`);delBtn.setText(`删除选中${selected.size?' ('+selected.size+')':''}`);delBtn.disabled=!selected.size;}
  if(!shown.length){grid.createEl('div',{cls:'lbc-empty',text:'没找到，试试更短的关键词。'});return;}
  let possibleCards=null;
  for(const {it,match} of shown){
    if(match.fuzzy&&!possibleCards){
      const headEl=grid.createEl('div',{cls:'lbc-possible-head'});
      headEl.createEl('span',{cls:'lbc-possible-title',text:`可能相关 · ${ranked.possible.length} 篇`});
      headEl.createEl('span',{cls:'lbc-possible-note',text:'拼音相近、错一个字或漏字，不是原词命中'});
      possibleCards=grid.createEl('div',{cls:'lbc-grid-inner lbc-grid-possible'});
    }
    const cards=possibleCards||exactCards;
    const sig=cardSig(it,!!match.fuzzy);const cached=cardCache.get(it.id);
    if(cached&&cached.sig===sig){cached.el._lbItem=it;cards.append(cached.el);continue;}
    const card=buildCard(cards,it,!!match.fuzzy);cardCache.set(it.id,{sig,el:card});
  }
}
function buildCard(cards,it,fuzzy){
    // 不设 aria-label：Obsidian 会把 aria-label 渲染成 hover 浮框（她不要那个「悬浮的点的字」）。
    const card=cards.createEl('article',{cls:'lbc-card'+(selectMode&&selected.has(it.id)?' is-selected':'')+(fuzzy?' is-possible':'')});card.tabIndex=0;card.setAttribute('role','link');
    // 卡片上的事件一律取 card._lbItem（数据刷新后复用的卡片换成新对象）
    card._lbItem=it;const cur=()=>card._lbItem;
    if(it.cover){const img=card.createEl('img',{cls:'lbc-cover'});img.loading='lazy';img.alt='';
      // 有封面宽高就先占好位置：图片还没加载时版面不跳，返回目录时滚动位置能一次到位
      if(it.cover_w&&it.cover_h){img.setAttribute('width',String(it.cover_w));img.setAttribute('height',String(it.cover_h));}
      if(!firstCover){firstCover=img;img.addEventListener?.('load',()=>LB.mark('cover'),{once:true});}
      img.src=app.vault.adapter.getResourcePath(lbPath(it.cover));}
    else card.createEl('div',{cls:'lbc-nocover',text:it.kind==='video'?'▷':'▤'});
    // 附件角标：待补=有文件未下载（橙），downloaded=有文件已下（灰）
    const badges=card.createEl('div',{cls:'lbc-badges'});
    if(it.kind==='video'){const videoBadge=badges.createEl('span',{cls:'lbc-attach lbc-video'});videoBadge.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>';}
    if(it.attachment==='待补')badges.createEl('div',{cls:'lbc-attach lbc-attach-todo',text:'待补'});
 else if(it.attachment==='线索')badges.createEl('div',{cls:'lbc-attach lbc-attach-hint',text:'疑似附件',attr:{title:it.attachment_reason||'正文提到附件，但没找到文件'}});
    else if(it.attachment==='downloaded')badges.createEl('div',{cls:'lbc-attach',text:'文件'});
    const badge=badges.querySelector('.lbc-attach:not(.lbc-video)');if(badge){try{const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.innerHTML='<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>';badge.prepend(icon);}catch(err){window.alert(err.message);}}
    const star=card.createEl('button',{cls:'lbc-star'+(it.starred?' is-on':''),text:it.starred?'★':'☆'});
    star.setAttribute('aria-pressed',String(!!it.starred));star.createEl('span',{cls:'lb-visually-hidden',text:it.starred?'取消收藏':'收藏'});
    star.onclick=async e=>{e.preventDefault();e.stopPropagation();star.disabled=true;const x=cur();try{const result=await provider().starNote(x.id,!x.starred);x.starred=result.starred;render();}catch(err){importStatus.setText(err.message);star.disabled=false;}};
    const body=card.createEl('div',{cls:'lbc-body'});body.createEl('div',{cls:'lbc-ctitle',text:it.title||'未命名'});
    const meta=body.createEl('div',{cls:'lbc-cmeta'});meta.createEl('span',{text:it.author||it.source||'收藏'});meta.createEl('span',{cls:'lbc-likes',text:it.likes==null?'':'♡ '+(Number(it.likes)>=10000?(Number(it.likes)/10000).toFixed(1)+'万':it.likes)});
    card.ondragover=e=>{e.preventDefault();};card.ondrop=async e=>{e.preventDefault();e.stopPropagation();const x=cur();const f=e.dataTransfer.files[0];if(!f)return;const fp=f.path||require('electron').webUtils?.getPathForFile(f);if(!fp){attachmentPanel([x]);return;}try{const result=await provider().attachFile(x.id,fp);await refresh();importStatus.setText(result.warning||'附件已保存并加入搜索');}catch(err){importStatus.setText('挂载失败：'+err.message);}};
    // 多选模式：点击=勾选/取消；平时=打开笔记（同一窗格，§5.4；按住 Ctrl 照 Obsidian 习惯开新标签）
    const toggle=()=>{const x=cur();selected.has(x.id)?selected.delete(x.id):selected.add(x.id);render();};
    const open=e=>{if(selectMode){toggle();return;}const x=cur();if(!x.note)return;const newTab=!!(e&&(e.ctrlKey||e.metaKey));saveState();if(!newTab)leaving=true;app.workspace.openLinkText(lbPath(x.note),'',newTab);};

    card.onclick=open;card.onkeydown=e=>{if(e.target===card&&e.key==='Enter'){e.preventDefault();open(e);}};
    card.oncontextmenu=e=>{e.preventDefault();openCardMenu(e,body,cur());};
    return card;
}
// ESC 退出多选（LB.listen 去重：重开页面时摘掉上一份监听器，别叠加）
LB.listen('esc',document,'keydown',e=>{if(e.key==='Escape'&&selectMode){selectMode=false;selected.clear();render();}});
async function drawChat(){
  ai.empty();
  for(const msg of messages){
    const row=ai.createEl('div',{cls:'lbc-turn'+(msg.role==='user'?' lbc-user':'')});
    if(msg.role==='user')row.setText(msg.content);
    else {
      await provider().renderMarkdownInto(msg.content,row);
      if(msg.sources?.length){
        const refs=row.createEl('details',{cls:'lbc-sources'});refs.createEl('summary',{text:`参考材料 · ${msg.sources.length}`});
        for(const src of msg.sources){const a=refs.createEl('a',{text:`[来源${src.citation}] ${src.title}`});a.onclick=()=>app.workspace.openLinkText(lbPath(src.note||src.agent_md),'',true);}
      }
    }
  }
  if(busy)ai.createEl('p',{cls:'lbc-status',text:'正在阅读收藏并整理回答…'});
  const form=ai.createEl('form',{cls:'lbc-follow'});
  const input=form.createEl('textarea');input.placeholder=messages.length?'继续追问…':'输入问题…';input.disabled=busy;
  const send=form.createEl('button',{text:'发送'});send.disabled=busy;send.type='submit';
  form.onsubmit=e=>{e.preventDefault();const q=input.value.trim();if(q&&!busy)sendQuestion(q);};
  input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();form.requestSubmit();}};
}
async function sendQuestion(q){
  if(busy)return;
  const history=messages.filter(m=>!m.failed).map(({role,content})=>({role,content}));
  messages.push({role:'user',content:q});busy=true;chatMode=true;render();await drawChat();
  try {const live=ai.createEl('div',{cls:'lbc-turn lbc-live'});const result=await provider().answerArchive({question:q,history,onDelta:delta=>{ai.querySelector('.lbc-status')?.remove();live.appendText(delta);}});messages.push({role:'assistant',content:result.markdown||'没有可用的回答。',sources:result.sources||[]});}
  catch(e){messages.push({role:'assistant',failed:true,content:'回答失败：'+e.message+'\n\n请重试。'});}
  finally{busy=false;await drawChat();}
}
search.onkeydown=e=>{
  if(e.key!=='Enter'||e.isComposing)return;
  e.preventDefault();commitSearch();
};
// 目录只做搜索（0926 Owner）：AI 深度回答在「问收藏」页。整句（语音打进来的）搜不到时退成关键词再搜。
// 整串短语库里没有就拆词（「悉尼咖啡」→「悉尼 咖啡」），还不中再按口语整句抽关键词；规则在 catalog-search.js resolveQuery。
function commitSearch(){
  if(busy)return;chatMode=false;committed=resolveQuery(search.value,items,data.pinyin_chars,data.aliases||[]);
  render();
}
search.oninput=()=>{if(!search.value&&!busy){committed='';chatMode=false;render();}else saveState();};
search.value=typeof saved.input==='string'?saved.input:committed;
let firstCover=null;
renderCatBar();render();
LB.t('render');
// 星标以 catalog-data 为准（点星标时后端同步改它）+ link-brain:star 事件，不再每次打开读 350 份 notes.json（§5.6）
if(app.workspace.on){const ref=app.workspace.on('link-brain:star',(id,on)=>{const it=items.find(x=>x.id===id);if(it&&it.starred!==on){it.starred=on;render();}});dv.component.registerEvent(ref);}
// 点开一篇（同一窗格）之后这一页就要被换掉了：别再记滚动（Obsidian 换笔记时会把滚动容器归零）
let leaving=false;
LB.onScroll(top=>{if(leaving)return;scrollTop=top;saveState();});
// 登记这一版 DOM：Dataview 下次重跑时版本没变就原样挂回；变了走 refresh（只换数据、卡片复用）
LB.keep(wrap,{version:await LB.data.version(),update:()=>refresh(),onReuse:()=>{if(refreshTags())render();}});
if(provider()?.focusCatalogSearch){provider().focusCatalogSearch=false;search.focus();}
if(savedScroll>0)LB.restoreScroll(savedScroll);   // 滚到位时记一笔 scroll-restored@
LB.t('restore');
LB.t('total');

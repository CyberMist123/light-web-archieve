// chat-view.js — 收藏搜索页的极简版（Owner 2026-09-17）。
// 无框线、居中、像聊天：搜收藏 + 问 AI 一体；会话持久化（跳走再回来不丢，直到点「清空」）；
// 「存档」栏可存可删——既存 AI 报告，也存 Owner 自己写的判断。配色全走 Obsidian 主题变量。
// 依赖：本文件前面已内联 catalog-search.js（score/normalize）；provider = link-brain-actions 插件。
const root = dv.container;
// 这个仓可能被挂进别的库的子目录（如 LER Vault/知识库【小红书】/）；数据里的路径都相对 lwa 仓根，
// 统一过 lbPath 补上挂载前缀。仓根 = 从本页往上第一个带 _archive 的目录。
const LB_ROOT=(()=>{try{let d=dv.current()?.file?.folder||'';while(d&&!app.vault.getAbstractFileByPath(d+'/_archive'))d=d.includes('/')?d.slice(0,d.lastIndexOf('/')):'';return d;}catch{return '';}})();
const lbPath=p=>p&&LB_ROOT?`${LB_ROOT}/${p}`:p;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-chatpage');
const provider = () => app.plugins.plugins['link-brain-actions'];
const SESSION_PATH = lbPath('_archive/chat-session.json');
const ARCHIVE_PATH = lbPath('_archive/chat-archive.json');
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

let data = {};
try { data = JSON.parse(await app.vault.adapter.read(lbPath('_archive/catalog-data.json'))); } catch {}
let items = data.items || [];

let session = { turns: [], draft: '' };
let archive = { entries: [] };
try { session = JSON.parse(await app.vault.adapter.read(SESSION_PATH)); } catch {}
try { archive = JSON.parse(await app.vault.adapter.read(ARCHIVE_PATH)); } catch {}
session.turns = Array.isArray(session.turns) ? session.turns : [];
session.draft = typeof session.draft === 'string' ? session.draft : '';
archive.entries = Array.isArray(archive.entries) ? archive.entries : [];

let lane = 'chat', busy = false, thinkTimer = null;
const saveSession = async () => { try { await app.vault.adapter.write(SESSION_PATH, JSON.stringify(session)); } catch {} };
const saveArchive = async () => { try { await app.vault.adapter.write(ARCHIVE_PATH, JSON.stringify(archive, null, 2)); } catch {} };
let compareSources=false;
const openNote = (source,compare=compareSources,context="") => {
  const src=typeof source==='string'?{note:source}:source;
  const chunks=(src?.excerpts||[]).filter(p=>p.field==='body'||p.field==='comments');
  if(context){const normalized=context.replace(/\s/g,'').toLowerCase();const score=p=>{const text=String(p.text).replace(/\s/g,'').toLowerCase();let n=0;for(let i=0;i<normalized.length-3;i++)if(text.includes(normalized.slice(i,i+4)))n++;return n;};chunks.sort((a,b)=>score(b)-score(a));}
  if(src?.note)return Promise.resolve(provider().openArchiveSource(src.note,root,compare,chunks)).catch(e=>window.alert(e.message));
};

const style = root.createEl('style');
style.textContent = `
.markdown-preview-view.lb-chatpage,.markdown-source-view.lb-chatpage{--file-line-width:100%;}
.lb-chatpage .markdown-preview-sizer,.lb-chatpage .markdown-preview-section,.lb-chatpage .cm-sizer,.lb-chatpage .cm-contentContainer,.lb-chatpage .cm-content,.lb-chatpage .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-chatpage .inline-title,.lb-chatpage .metadata-container{display:none!important;}
.lbchat{max-width:720px;margin:0 auto;padding:28px clamp(14px,3vw,20px) 120px;font-family:var(--font-interface),"Segoe UI","Microsoft YaHei",sans-serif;color:var(--text-normal);}
.lbchat-head{display:flex;flex-direction:column;align-items:center;text-align:center;gap:12px;margin:8px 0 22px;}
.lbchat-titleblock{display:flex;flex-direction:column;align-items:center;gap:6px;}
.lbchat-titlerow{display:flex;align-items:baseline;justify-content:center;gap:9px;}
.lbchat-title{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:42px;font-weight:700;letter-spacing:.01em;line-height:1.05;color:var(--text-normal);}
.lbchat-plus{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:40px;font-weight:700;line-height:1;color:var(--text-normal);cursor:pointer;transition:color .12s;}
.lbchat-plus:hover{color:var(--interactive-accent);}
.lbchat-sub{font-size:12px;color:var(--text-faint);letter-spacing:.02em;}
.lbchat-search{width:100%;max-width:440px;height:38px;text-align:center;border:none!important;border-bottom:1px solid var(--background-modifier-border)!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;padding:0 2px!important;font-size:15px!important;color:var(--text-normal);margin-top:2px;transition:border-color .15s;}
.lbchat-search:focus{outline:none;border-bottom-color:var(--interactive-accent)!important;box-shadow:none!important;}
.lbchat-search[hidden]{display:none;}
.lbchat-nav{display:flex;align-items:center;justify-content:center;gap:16px;margin:0 0 32px;flex-wrap:wrap;}
.lbchat-navsep{color:var(--background-modifier-border);user-select:none;}
.lbchat-tab{cursor:pointer;font-size:13px;color:var(--text-faint);padding:2px 0;transition:color .12s;}
.lbchat-tab:hover{color:var(--text-muted);}
.lbchat-tab.is-on{color:var(--text-normal);font-weight:600;}
.lbchat-clear{cursor:pointer;font-size:12px;color:var(--text-faint);transition:color .12s;}
.lbchat-clear:hover{color:var(--text-error,#e5534b);}
.lbchat-clear[hidden]{display:none;}
.lbchat-body{min-height:40px;}
.lbchat-empty{color:var(--text-faint);font-size:14px;line-height:1.9;padding:8px 0;}
.lbchat-turn{margin:0 0 26px;line-height:1.8;font-size:15px;overflow-wrap:anywhere;}
.lbchat-user{color:var(--text-normal);font-weight:500;}
.lbchat-user .lbchat-qmark{color:var(--text-faint);margin-right:8px;}
.lbchat-answer{line-height:1.8;}
.lbchat-answer p:first-child{margin-top:0;}
.lbchat-answer p:last-child{margin-bottom:0;}
.lbchat-actions{display:flex;gap:16px;margin-top:10px;}
.lbchat-act{cursor:pointer;font-size:12px;color:var(--text-faint);transition:color .12s;}
.lbchat-act:hover{color:var(--interactive-accent);}
.lbchat-src{margin-top:12px;font-size:12px;color:var(--text-muted);}
.lbchat-src summary{cursor:pointer;color:var(--text-faint);}
.lbchat-src a{display:block;margin:6px 0;cursor:pointer;color:var(--link-color);}
.lbchat-hits{display:flex;flex-direction:column;gap:16px;}
.lbchat-hit{cursor:pointer;}
.lbchat-hit-title{font-size:14px;font-weight:600;color:var(--text-normal);}
.lbchat-hit-title:hover{color:var(--interactive-accent);}
.lbchat-hit-meta{font-size:12px;color:var(--text-faint);margin-top:2px;}
.lbchat-hit-ex{font-size:13px;color:var(--text-muted);line-height:1.65;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbchat-think{display:flex;align-items:center;gap:8px;color:var(--text-muted);font-size:14px;margin:0 0 26px;}
.lbchat-dot{width:6px;height:6px;border-radius:50%;background:var(--interactive-accent);opacity:.5;animation:lbchatpulse 1s ease-in-out infinite;}
@keyframes lbchatpulse{0%,100%{opacity:.25;transform:scale(.8);}50%{opacity:1;transform:scale(1);}}
.lbchat-arc-add{display:flex;gap:10px;align-items:flex-end;margin:0 0 24px;}
.lbchat-arc-input{flex:1;resize:vertical;min-height:38px;border:none;border-bottom:1px solid var(--background-modifier-border);border-radius:0;background:transparent;color:var(--text-normal);font:inherit;font-size:14px;padding:6px 2px;box-sizing:border-box;}
.lbchat-arc-input:focus{border-bottom-color:var(--interactive-accent);outline:none;}
.lbchat-arc-save{cursor:pointer;font-size:13px;color:var(--text-faint);padding-bottom:8px;white-space:nowrap;}
.lbchat-arc-save:hover{color:var(--interactive-accent);}
.lbchat-arc-item{margin:0 0 24px;}
.lbchat-arc-meta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text-faint);margin-bottom:5px;}
.lbchat-arc-kind{color:var(--interactive-accent);}
.lbchat-arc-del{margin-left:auto;cursor:pointer;opacity:0;transition:opacity .12s;}
.lbchat-arc-item:hover .lbchat-arc-del{opacity:1;}
.lbchat-arc-del:hover{color:var(--text-error,#e5534b);}
.lbchat-arc-body{line-height:1.8;font-size:15px;}

.lb-page-nav{display:flex;grid-column:2;grid-row:1;gap:2px;padding:4px;background:var(--background-secondary);border-radius:12px;justify-self:center;white-space:nowrap;}
.lb-page-nav button{font:inherit;font-size:13px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);border-radius:9px;padding:9px 16px;height:auto;cursor:pointer;}
.lb-page-nav button.is-current{background:var(--background-primary)!important;color:var(--text-normal);box-shadow:0 1px 4px #0000000c!important;font-weight:500;}
.lb-manage{font-size:24px!important;font-weight:500;background:transparent!important;border:0!important;box-shadow:none!important;color:var(--text-muted);padding:0!important;width:40px;height:40px;border-radius:10px;cursor:pointer;}
.lb-manage:hover{background:var(--background-secondary)!important;color:var(--text-normal);}
.lbc-wrap button:focus-visible,.lbchat button:focus-visible{outline:2px solid var(--interactive-accent)!important;outline-offset:3px;}
.lbc-live,.lbchat-live{white-space:pre-wrap;}

.lbchat{max-width:1440px;box-sizing:border-box;padding:32px clamp(16px,3vw,48px) 80px;font-family:"Noto Sans SC","Segoe UI","Microsoft YaHei UI",sans-serif;}
.lbchat-head{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;text-align:left;gap:28px 20px;margin:0 0 60px;}
.lbchat-titleblock{align-items:flex-start;gap:10px;grid-column:1;grid-row:1;}
.lbchat-tools{grid-column:3;grid-row:1;justify-self:end;display:flex;align-items:center;gap:10px;}
.lbchat button.lbchat-plus{font-family:Georgia,serif;font-size:40px;font-weight:700;font-style:italic;background:transparent;border:0;box-shadow:none;width:40px;height:44px;padding:0;}
.lbchat-sub{font-size:11px;letter-spacing:.06em;}
.lbchat-composer{max-width:700px;margin:0 auto 18px;display:flex;align-items:flex-end;gap:12px;padding:14px;border:1px solid var(--background-modifier-border);border-radius:18px;background:var(--background-secondary);}
.lbchat-composer:focus-within{border-color:var(--interactive-accent);}
.lbchat-composer[hidden]{display:none;}
.lbchat-search{flex:1;min-width:0;max-width:none;box-sizing:border-box;resize:vertical;min-height:64px;height:64px;text-align:left;border:0!important;padding:4px!important;font:inherit!important;font-size:15px!important;line-height:1.6;}
.lbchat-send{background:var(--text-normal)!important;color:var(--background-primary)!important;box-shadow:none!important;border:0!important;border-radius:10px;height:36px;padding:0 16px;flex:none;cursor:pointer;}
.lbchat-send:disabled{opacity:.4;cursor:wait;}
.lbchat-nav{max-width:700px;justify-content:flex-start;margin:0 auto 32px;gap:24px;}
.lbchat button.lbchat-tab{border:0!important;background:transparent!important;box-shadow:none!important;border-radius:0;padding:8px 0;font-family:inherit;font-size:13px;height:auto;}
.lbchat button.lbchat-tab.is-on{border-bottom:2px solid var(--text-normal)!important;}
.lbchat-clear{display:none!important;}
.lbchat-body{max-width:700px;margin:0 auto;}
.lbchat-empty{font-size:13px;}
.lbchat-user{margin-left:auto;background:var(--background-secondary);border-radius:14px;padding:10px 16px;width:fit-content;max-width:90%;}
.lbchat button.lbchat-act,.lbchat button.lbchat-arc-del{font-family:inherit;background:transparent;border:0;box-shadow:none;padding:0;font-size:12px;height:auto;}
.lbchat-arc-del{opacity:1;}
@media(max-width:700px){.lbchat{padding:20px 12px 48px;}.lbchat-head{grid-template-columns:1fr auto;gap:24px 10px;margin-bottom:36px;}.lbchat-tools{grid-column:2;}.lbchat-title{font-size:34px;}.lbchat button.lbchat-plus{font-size:32px;}.lbchat-head .lb-page-nav{grid-column:1/-1;grid-row:2;justify-self:start;}.lbchat-composer{padding:12px;gap:8px;}.lbchat-send{padding:0 12px;}}

.lbchat{height:calc(100vh - 110px);display:flex;flex-direction:column;padding:22px 24px 0;overflow:hidden;}
.lbchat-head{flex:none;grid-template-columns:1fr auto;gap:14px;margin:0 0 20px;}
.lbchat-title{font-size:32px;}.lbchat-tools{grid-column:2;gap:12px;flex-wrap:wrap;justify-content:flex-end;}
.lbchat-head .lb-page-nav{grid-column:1/-1;grid-row:2;justify-self:start;background:transparent;padding:0;}
.lbchat-nav{display:none;}.lbchat-body{flex:1;min-height:0;overflow:auto;width:100%;max-width:850px;padding:0 8px 24px;box-sizing:border-box;}
.lbchat-composer{flex:none;width:100%;max-width:850px;box-sizing:border-box;margin:0 auto;padding:10px 12px;border-radius:10px;background:var(--background-primary);}
.lbchat-search{height:38px;min-height:38px;max-height:160px;margin:0;}.lbchat-turn{font-size:14px;line-height:1.85;}
.lbchat-answer h1,.lbchat-answer h2,.lbchat-answer h3{font-size:1.15em;line-height:1.6;}
.lbchat button.lbchat-tab{font-size:12px;}.lbchat-src button{margin-right:14px;}
.lbchat-cite{display:inline!important;font:inherit!important;font-size:12px!important;border:0!important;box-shadow:none!important;background:var(--background-secondary)!important;color:var(--link-color);padding:1px 5px!important;height:auto;border-radius:4px;cursor:pointer;}
.lbchat-editor{width:100%;min-height:230px;font:inherit;line-height:1.7;resize:vertical;box-sizing:border-box;}
.lbchat-editbar{display:flex;gap:12px;margin:8px 0;}.lbchat-source-block{cursor:pointer;}.lbchat-source-block:hover{background:var(--background-secondary);border-radius:4px;}
@media(max-width:700px){.lbchat{padding:12px 6px 0;}.lbchat-title{font-size:28px;}.lbchat-tools{gap:8px;}.lbchat-head{gap:10px;margin-bottom:18px;}.lbchat-composer{padding:8px;}.lbchat-body{padding:0 4px 20px;}}

.lb-visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
.lbc-star{opacity:0;pointer-events:none;transition:opacity .15s;}.lbc-card:hover .lbc-star,.lbc-card:focus-within .lbc-star{opacity:1;pointer-events:auto;}
@media(hover:none){.lbc-star{opacity:1;pointer-events:auto;}}
.lbc-badges{position:absolute;top:8px;left:8px;display:flex;gap:5px;align-items:center;}
.lbc-badges .lbc-attach{position:static;display:inline-flex;align-items:center;line-height:16px;padding:3px 6px;gap:4px;height:22px;box-sizing:border-box;}
.lbc-badges svg{display:block;width:14px;height:14px;flex:none;stroke:currentColor;stroke-width:1.6;fill:none;}
.lbc-simple .lbc-grid-inner{columns:auto;}.lbc-simple .lbc-card{padding:18px 42px 18px 0;}.lbc-simple .lbc-body{padding:0;}.lbc-simple .lbc-badges{position:static;float:right;margin:2px 0 0 12px;}.lbc-simple .lbc-star{top:16px;right:0;}.lbc-simple .lbc-cmeta{margin-top:4px;}
.lbchat-bookmark svg{width:18px;height:18px;display:block;stroke:currentColor;stroke-width:1.6;fill:none;}.lbchat-bookmark.is-saved svg{fill:currentColor;}
.lbchat .lbchat-composer{margin-top:24px;margin-bottom:14px;}.lbchat{height:calc(100vh - 80px);}
.lbchat-hist{background:transparent;border:0;color:var(--text-muted);cursor:pointer;padding:6px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;transition:color .12s,background .12s;}
.lbchat-hist:hover{color:var(--text-normal);background:var(--background-modifier-hover);}
.lbchat-histpanel{position:fixed;width:320px;max-height:60vh;overflow:auto;background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.22);padding:6px;z-index:9999;}
.lbchat-histhead{display:flex;align-items:center;justify-content:space-between;padding:6px 8px 8px;font-size:12px;color:var(--text-muted);border-bottom:1px solid var(--background-modifier-border);margin-bottom:4px;}
.lbchat-histclear{cursor:pointer;font-size:12px;color:var(--text-error,#e5534b);background:transparent;border:0;padding:2px 6px;border-radius:6px;}
.lbchat-histclear:hover{background:var(--background-modifier-hover);}
.lbchat-histclear:disabled{opacity:.4;cursor:default;}
.lbchat-histitem{display:block;width:100%;text-align:left;background:transparent;border:0;cursor:pointer;font-size:13px;color:var(--text-normal);padding:8px 8px;border-radius:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbchat-histitem:hover{background:var(--background-modifier-hover);}
.lbchat-histempty{padding:14px 8px;font-size:12px;color:var(--text-faint);text-align:center;}

.lbchat-titleblock{align-items:center;width:max-content;max-width:100%;}
.lbchat-titlerow{align-items:center;gap:10px;}
/* 0925：「+」放进标题里继承同一套字，与目录页一致 */.lbchat-title button.lbchat-plus{font:inherit!important;color:var(--text-normal)!important;transition:color .12s;width:auto!important;height:auto!important;padding:0 0 0 .12em!important;margin:0!important;border:0!important;background:transparent!important;box-shadow:none!important;border-radius:0!important;display:inline!important;vertical-align:baseline;line-height:inherit!important;cursor:pointer;}.lbchat-title button.lbchat-plus:hover{color:var(--interactive-accent)!important;}
.lb-manage{font-family:Arial,sans-serif!important;line-height:1!important;display:grid;place-items:center;}
.lbchat-export summary{cursor:pointer;color:var(--text-muted);}.lbchat-export[open]{padding:6px;border-radius:8px;background:var(--background-secondary);}.lbchat-export label{font-size:12px;margin-right:8px;}
`;

const wrap = root.createEl('div', { cls: 'lbchat' });
// Size against the actual Obsidian pane, not the entire screen (tabs/toolbars
// and pane offsets otherwise push the composer below the visible area).
const fitPane=()=>{const viewport=root.closest('.workspace-leaf-content')||(pane&&['auto','scroll','hidden'].includes(getComputedStyle(pane).overflowY)?pane:null);const bottom=Math.min(window.innerHeight,viewport?.getBoundingClientRect().bottom||window.innerHeight);wrap.style.height=Math.max(240,bottom-wrap.getBoundingClientRect().top-16)+'px';};
const resizeObserver=new ResizeObserver(fitPane);resizeObserver.observe(pane||document.documentElement);
if(dv.component?.register)dv.component.register(()=>resizeObserver.disconnect());
requestAnimationFrame(fitPane);
// 图1 顶头：Collections + 标题 + 计数/更新，右边一条下划线搜索（问答时这一整块都不动）。
const head = wrap.createEl('div', { cls: 'lbchat-head' });
const titleBlock = head.createEl('div', { cls: 'lbchat-titleblock' });
const titleRow = titleBlock.createEl('div', { cls: 'lbchat-titlerow' });
const titleText = titleRow.createEl('span', { cls: 'lbchat-title', text: 'Collections' });
const tools=head.createEl('div',{cls:'lbchat-tools'});
const readerLayout=head.createEl('select',{cls:'lbchat-reader-layout'});
readerLayout.style.cssText='grid-column:1/-1;grid-row:3;justify-self:end;max-width:100%;font:inherit;font-size:12px;';
readerLayout.createEl('option',{text:'原文 · 单篇'}).value='single';
readerLayout.createEl('option',{text:'原文 · 上下对照'}).value='compare';
readerLayout.onchange=()=>{compareSources=readerLayout.value==='compare';};
const plus = titleText.createEl('button', { cls: 'lbchat-plus', text: '+' });


plus.onclick = (evt) => {
  const p = provider();
  if (typeof p?.openPlusMenu !== 'function') { try { new Notice('需要启用 Link Brain Actions 插件'); } catch {} return; }
  p.openPlusMenu(evt);
};
const sub = titleBlock.createEl('div', { cls: 'lbchat-sub' });
try {
  const t = new Date(data.built_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
  sub.setText(`${items.length} 篇 · 更新 ${t}`);
} catch { sub.setText(`${items.length} 篇`); }
const pageNav=head.createEl('nav',{cls:'lb-page-nav'});
const browse=pageNav.createEl('button',{text:'浏览收藏'});browse.onclick=()=>provider().openLibraryPage('catalog');
const ask=pageNav.createEl('button',{text:'问收藏',cls:'is-current'});ask.setAttribute('aria-current','page');
const manage=tools.createEl('button',{cls:'lb-manage',text:'…'});
manage.onclick=e=>provider()?.openAISettingsMenu(e);
// 提问历史 logo：点开看本会话提过的问题，可一键清空
const histBtn=tools.createEl('button',{cls:'lbchat-hist',attr:{'aria-label':'提问历史',title:'提问历史'}});
histBtn.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l3.5 2"/></svg>';
histBtn.onclick=e=>{e.stopPropagation();toggleHistory(histBtn);};
const composer=wrap.createEl('form',{cls:'lbchat-composer'});
const search = composer.createEl('textarea', { cls: 'lbchat-search' });
search.rows=2;search.placeholder = '问问你的收藏…'; search.value = session.draft || '';
const send=composer.createEl('button',{cls:'lbchat-send',text:'发送'});send.type='submit';
composer.onsubmit=e=>{e.preventDefault();if(busy||!search.value.trim())return;const v=search.value;search.value='';session.draft='';submit(v);};

// 第二行：对话/存档 切换 + 同步/浏览/清空
const nav = wrap.createEl('div', { cls: 'lbchat-nav' });
const tabChat = tools.createEl('button', { cls: 'lbchat-tab', text: '对话' });
const tabArch = tools.createEl('button', { cls: 'lbchat-tab', text: '已保存' });


const bodyEl = wrap.createEl('div', { cls: 'lbchat-body' });
wrap.append(composer);

// 顶部搜索框 = 唯一输入：回车触发（/ 开头问 AI，否则搜），草稿持久化
search.oninput = () => { session.draft = search.value; saveSession(); };
search.onkeydown = e => {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
  e.preventDefault();composer.requestSubmit();
};

// ── 搜索 ──
function runSearch(q) {
  const nq = normalize(q);
  const scored = items
    .map(it => ({ it, s: score(it, nq, data.pinyin_chars, data.aliases || []) }))
    .filter(x => x.s > 0).sort((a, b) => b.s - a.s).slice(0, 12);
  return scored.map(({ it }) => {
    const text = it.search_text || it.summary || '';
    const pos = nq ? text.toLowerCase().indexOf(nq.split(/\s+/)[0]) : -1;
    const ex = pos >= 0 ? text.slice(Math.max(0, pos - 40), Math.max(0, pos - 40) + 200) : text.slice(0, 200);
    return { id: it.id, title: it.title || '未命名', note: it.note, author: it.author || it.source || '收藏', excerpt: ex };
  });
}

// ── 会话渲染 ──
async function drawChat() {
  const scroll=bodyEl.scrollTop;
  bodyEl.empty();
  search.placeholder=session.turns.length?'继续追问…':'搜索你的收藏，或直接提问…';

  if (!session.turns.length && !busy) {
    bodyEl.createEl('div', { cls: 'lbchat-empty', text: '答案来自你的收藏，参考材料会附在回答下方。' });
  }
  for (const t of session.turns) {
    if (t.role === 'user') {
      const el = bodyEl.createEl('div', { cls: 'lbchat-turn lbchat-user' });
      if (t.mode === 'search') el.createEl('span', { cls: 'lbchat-qmark', text: '搜' });
      el.appendText(t.content);
    } else if (t.role === 'search') {
      const el = bodyEl.createEl('div', { cls: 'lbchat-turn' });
      if (!t.results.length) { el.createEl('div', { cls: 'lbchat-empty', text: '没找到，试试更短的关键词。' }); continue; }
      const hits = el.createEl('div', { cls: 'lbchat-hits' });
      for (const r of t.results) {
        const h = hits.createEl('div', { cls: 'lbchat-hit' });
        h.createEl('div', { cls: 'lbchat-hit-title', text: r.title });
        h.createEl('div', { cls: 'lbchat-hit-meta', text: r.author });
        if (r.excerpt) h.createEl('div', { cls: 'lbchat-hit-ex', text: r.excerpt });
        h.onclick = () => openNote(r.note);
      }
    } else { // assistant
      const el = bodyEl.createEl('div', { cls: 'lbchat-turn lbchat-answer' });
      try { await provider().renderMarkdownInto(t.content, el); } catch { el.setText(t.content); }
      bindSources(el,t.sources||[]);
      if (t.sources && t.sources.length) {
        const refs = el.createEl('details', { cls: 'lbchat-src' });
        refs.createEl('summary', { text: `参考材料 · ${t.sources.length}` });
        for (const src of t.sources) {
          const a = refs.createEl('a', { text: `[来源${src.citation}] ${src.title}` });
          a.onclick = () => openNote(src);
          const compare=refs.createEl('button',{cls:'lbchat-act',text:'上下对照'});compare.onclick=()=>openNote(src,true);
          const copySource=refs.createEl('button',{cls:'lbchat-act',text:'复制来源'});copySource.onclick=async()=>{await navigator.clipboard.writeText(sourceText(src));copySource.setText('已复制');};

        }
      }
      if (!t.failed) {
        const acts = el.createEl('div', { cls: 'lbchat-actions' });
        const copy=acts.createEl('button',{cls:'lbchat-act',text:'复制'});copy.onclick=async()=>{try{await navigator.clipboard.writeText(t.content+'\n\n'+(t.sources||[]).map(sourceText).join('\n\n'));copy.setText('已复制');}catch{copy.setText('复制失败');}};
        const exportOptions=acts.createEl('details',{cls:'lbchat-export'});exportOptions.createEl('summary',{text:'导出'});const imageLabel=exportOptions.createEl('label',{text:'附带原图 '});const bundleImages=imageLabel.createEl('input');bundleImages.type='checkbox';bundleImages.checked=true;
        const used=new Set([...t.content.matchAll(/\[来源(\d+)\]/g)].map(m=>Number(m[1])));
        const currentSources=(t.sources||[]).filter(s=>!used.size||used.has(Number(s.citation)));
        for(const [label,copy] of [['导出资料包',false],['复制文件包',true]]){
          const exportBtn=exportOptions.createEl('button',{cls:'lbchat-act',text:label});
          exportBtn.onclick=async()=>{exportBtn.disabled=true;exportBtn.setText(copy?'复制中…':'导出中…');try{await provider().exportArchiveBundle(currentSources.map(s=>s.id),bundleImages.checked,answerExportMd({...t,sources:currentSources}),{question:t.q||'当前问答',askedAt:t.askedAt||"unknown",copy});}catch(e){window.alert(e.message);}finally{exportBtn.disabled=false;exportBtn.setText(label);}};
        }
        const details=acts.createEl('button',{cls:'lbchat-act',text:'展开重点细节'});details.disabled=busy;details.onclick=()=>submit('请继续展开上一答最相关的重点项，摘录原文重要细节，说明具体机制、触发条件和限制，区分作者说法和评论。');
        if(!t.savedId)t.savedId=archive.entries.find(e=>e.kind==='report'&&e.content===t.content)?.id;
        const saved=()=>archive.entries.some(e=>e.id===t.savedId);
        const save=acts.createEl('button',{cls:'lbchat-act lbchat-bookmark'});
        save.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg><span class="lb-visually-hidden">收藏回答</span>';
        const paintSave=()=>{save.classList.toggle('is-saved',saved());save.setAttribute('aria-pressed',String(saved()));};paintSave();
        save.onclick=async()=>{
          if(saved())archive.entries=archive.entries.filter(e=>e.id!==t.savedId);
          else{t.savedId=uid();archive.entries.unshift({id:t.savedId,ts:new Date().toISOString(),kind:'report',title:t.q||'AI 整理',content:t.content,sources:t.sources||[]});}
          await saveArchive();await saveSession();paintSave();
        };
        el.ondblclick=e=>{if(e.target.closest('button,textarea'))return;for(const block of el.querySelectorAll('.lbchat-source-block'))clearTimeout(block._lbClickTimer);editText(el,t,async()=>{const stored=archive.entries.find(x=>x.id===t.savedId);if(stored){stored.content=t.content;await saveArchive();}await saveSession();await drawChat();});};
      }
    }
  }
  if (busy) {
    const th = bodyEl.createEl('div', { cls: 'lbchat-think' });
    th.createEl('span', { cls: 'lbchat-dot' });
    const label = th.createEl('span');
    const phases = ['正在检索收藏…', '正在读相关笔记…', '正在整理答案…'];
    let i = 0; label.setText(phases[0]);
    clearInterval(thinkTimer);
    thinkTimer = setInterval(() => { i = (i + 1) % phases.length; label.setText(phases[i]); }, 1400);
  } else { clearInterval(thinkTimer); thinkTimer = null; }
  bodyEl.scrollTop=scroll;
}

async function drawArchive() {
  bodyEl.empty();

  const addRow = bodyEl.createEl('div', { cls: 'lbchat-arc-add' });
  const ta = addRow.createEl('textarea', { cls: 'lbchat-arc-input' });
  ta.placeholder = '写一条自己的判断存起来（如「ib 机不适合」）…';
  const saveIt = addRow.createEl('button', { cls: 'lbchat-arc-save', text: '存' });
  saveIt.onclick = async () => {
    const txt = ta.value.trim(); if (!txt) return;
    archive.entries.unshift({ id: uid(), ts: new Date().toISOString(), kind: 'note', title: '', content: txt });
    ta.value = ''; await saveArchive(); drawArchive();
  };
  if (!archive.entries.length) { bodyEl.createEl('div', { cls: 'lbchat-empty', text: '还没有保存的内容。可以保存回答，或在上面记下自己的判断。' }); return; }
  for (const e of archive.entries) {
    const item = bodyEl.createEl('div', { cls: 'lbchat-arc-item' });
    const meta = item.createEl('div', { cls: 'lbchat-arc-meta' });
    meta.createEl('span', { cls: 'lbchat-arc-kind', text: e.kind === 'note' ? '判断' : 'AI 报告' });
    meta.createEl('span', { text: fmtTs(e.ts) + (e.title ? ' · ' + e.title : '') });
    const edit=meta.createEl('button',{cls:'lbchat-act',text:'编辑'});edit.onclick=()=>editText(item,e,async()=>{await saveArchive();await drawArchive();});
    const del = meta.createEl('button', { cls: 'lbchat-arc-del', text: '✕' });
    del.onclick = async () => { archive.entries = archive.entries.filter(x => x.id !== e.id); await saveArchive(); drawArchive(); };
    const b = item.createEl('div', { cls: 'lbchat-arc-body' });
    try { await provider().renderMarkdownInto(e.content, b); } catch { b.setText(e.content); }
    bindSources(b,e.sources||[]);
  }
}
function fmtTs(ts) { try { const d = new Date(ts); return `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; } catch { return ''; } }

async function submit(raw) {
  const text = (raw || '').trim(); if (!text || busy) return;
  session.draft = '';
  {
    const q = text.replace(/^\//,'').trim(); if (!q) return;
    const askedAt=new Date().toISOString();
    session.turns.push({ role: 'user', content: q, mode: 'ask', askedAt });
    await saveSession(); busy = true;send.disabled=true;search.disabled=true; await drawChat();bodyEl.scrollTop=bodyEl.scrollHeight;
    try {
      const history = session.turns.filter(t => t.role === 'user' || t.role === 'assistant').filter(t => !t.failed)
        .map(t => ({ role: t.role === 'assistant' ? 'assistant' : 'user', content: t.content }));
      const live=bodyEl.createEl('div',{cls:'lbchat-turn lbchat-answer lbchat-live'});
      const r = await provider().answerArchive({ question: q, history:history.slice(0,-1),onDelta:delta=>{clearInterval(thinkTimer);bodyEl.querySelector('.lbchat-think')?.remove();live.appendText(delta);} });
      session.turns.push({ role: 'assistant', content: r.markdown || '没有可用的回答。', sources: r.sources || [], q, askedAt });
    } catch (e) {
      session.turns.push({ role: 'assistant', failed: true, content: '回答失败：' + (e.message || e) + '\n\n请重试。' });
    } finally { busy = false;send.disabled=false;search.disabled=false; await saveSession(); await drawChat(); }
  }
}

// ── 栏切换 / 清空 ──（顶头 Collections+ 标题 + 搜索始终不动；只切换下面的正文）
async function setLane(next) {
  lane = next;
  tabChat.classList.toggle('is-on', lane === 'chat');
  tabArch.classList.toggle('is-on', lane === 'archive');
  composer.hidden = lane !== 'chat';   // 存档栏用它自己的输入框，顶部搜索只服务对话栏

  if (lane === 'chat') await drawChat(); else await drawArchive();
}
tabChat.onclick = () => setLane('chat');
tabArch.onclick = () => setLane('archive');
await setLane('chat');

if(provider()?.pendingArchiveQuestion){const q=provider().pendingArchiveQuestion;delete provider().pendingArchiveQuestion;await submit(q);}

function sourceText(src){
  const absolute=src.markdown_path || (src.note&&app.vault.adapter.getBasePath?app.vault.adapter.getBasePath().replace(/[\\/]$/,'')+'/'+lbPath(src.note):src.agent_md||'');
  return `[来源${src.citation}] ${src.title}\n${src.url||''}\n本地正文：${absolute}`;
}
// ── 机读版导出 ──（回答 + 参考材料原样落成一份 md，扔给 GPT 用）
function tsSlug(){const d=new Date();const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}${p(d.getMonth()+1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;}
async function writeExport(name,md){
  const dir='收藏导出';try{await app.vault.adapter.mkdir(lbPath(dir));}catch{}
  const path=lbPath(`${dir}/${name}.md`);
  await app.vault.adapter.write(path,md);
  try{app.workspace.openLinkText(path,'',true);}catch{}
  return path;
}
function answerExportMd(t){
  const L=[`# ${t.q||'AI 整理'}`,'',`> 导出于 ${new Date().toLocaleString('zh-CN')} · 机读版（问收藏）`,'','## 回答','',t.content,''];
  if(t.sources&&t.sources.length){
    L.push('## 参考材料','');
    const labels={body:'作者正文',comments:'评论',ocr:'图片文字',attachments:'附件正文',transcript:'视频转写'};
    for(const s of t.sources){
      L.push(`### [来源${s.citation}] ${s.title}`);
      if(s.url)L.push(`- 链接：${s.url}`);
      if(s.markdown_path||s.agent_md)L.push(`- 本地机读：${s.markdown_path||s.agent_md}`);
      if(s.note)L.push(`- 本地正文：${s.note}`);
      if(s.excerpts?.length){L.push('','#### 命中原文');for(const p of s.excerpts)L.push(`**${labels[p.field]||p.field}**`,'',`> ${String(p.text).replace(/\n/g,'\n> ')}`,'');}
      L.push('');
    }
  }
  return L.join('\n');
}
// ── 提问历史面板 ──（本会话问过的问题；点一条回填输入框，或一键清空整段对话）
function toggleHistory(anchor){
  document.querySelectorAll('.lbchat-histpanel').forEach(p=>p.remove());
  if(anchor._open){anchor._open=false;return;}
  anchor._open=true;
  const qs=session.turns.filter(t=>t.role==='user');
  const panel=document.body.createEl('div',{cls:'lbchat-histpanel'});
  const headRow=panel.createEl('div',{cls:'lbchat-histhead'});
  headRow.createEl('span',{text:`提问历史 · ${qs.length}`});
  const clr=headRow.createEl('button',{cls:'lbchat-histclear',text:'一键清空'});
  clr.disabled=!session.turns.length;
  clr.onclick=async()=>{if(!window.confirm('清空本会话所有提问和回答？（已保存的回答不受影响）'))return;session.turns=[];session.draft='';await saveSession();panel.remove();anchor._open=false;await drawChat();};
  if(!qs.length){panel.createEl('div',{cls:'lbchat-histempty',text:'还没有提问'});}
  else for(const t of [...qs].reverse()){const row=panel.createEl('button',{cls:'lbchat-histitem'});row.setText((t.mode==='search'?'🔍 ':'')+t.content);row.onclick=()=>{search.value=t.content;session.draft=t.content;saveSession();search.focus();panel.remove();anchor._open=false;};}
  const r=anchor.getBoundingClientRect();
  panel.style.top=(r.bottom+6)+'px';panel.style.left=Math.max(8,Math.min(r.left,window.innerWidth-328))+'px';
  const close=ev=>{if(panel.contains(ev.target)||ev.target===anchor||anchor.contains(ev.target))return;panel.remove();anchor._open=false;document.removeEventListener('click',close);};
  setTimeout(()=>document.addEventListener('click',close),0);
}
function bindSources(el,sources){
  const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
  for(const node of nodes){
    if(node.parentElement.closest('a,code,pre,button'))continue;
    const matches=[...node.textContent.matchAll(/\[来源(\d+)\]/g)];if(!matches.length)continue;
    const frag=document.createDocumentFragment();let last=0;
    for(const m of matches){frag.append(document.createTextNode(node.textContent.slice(last,m.index)));const src=sources.find(x=>Number(x.citation)===Number(m[1]));
      if(src){const b=document.createElement('button');b.className='lbchat-cite';b.textContent=m[0];b.onclick=e=>{e.stopPropagation();openNote(src,compareSources,b.closest('p,li')?.textContent||'');};frag.append(b);}else frag.append(document.createTextNode(m[0]));last=m.index+m[0].length;}
    frag.append(document.createTextNode(node.textContent.slice(last)));node.replaceWith(frag);
  }
  for(const block of el.querySelectorAll('p,li,h1,h2,h3')){const cite=block.querySelector('.lbchat-cite');if(!cite)continue;block.classList.add('lbchat-source-block');block.onclick=e=>{if(e.target.closest('a,button')||window.getSelection()?.toString())return;clearTimeout(block._lbClickTimer);if(e.detail<2)block._lbClickTimer=setTimeout(()=>cite.click(),260);};}
  for(const a of el.querySelectorAll('a')){const href=a.getAttribute('data-href')||a.getAttribute('href');const src=sources.find(x=>href===x.url||href===x.note||href===x.note?.replace(/\.md$/,''));if(src)a.onclick=e=>{e.preventDefault();e.stopPropagation();openNote(src);};}
}
function editText(host,entry,save){
  if(host.querySelector('.lbchat-editor'))return;
  const editor=host.createEl('textarea',{cls:'lbchat-editor'});editor.value=entry.content;
  const bar=host.createEl('div',{cls:'lbchat-editbar'});const ok=bar.createEl('button',{text:'保存修改'});const cancel=bar.createEl('button',{text:'取消'});
  ok.onclick=async()=>{entry.content=editor.value;await save();};cancel.onclick=()=>{editor.remove();bar.remove();};editor.focus();
}

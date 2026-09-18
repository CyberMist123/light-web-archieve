const simplePage = false;
const root = dv.container;
// 这个仓可能被挂进别的库的子目录（如 LER Vault/知识库【小红书】/）；数据里的路径都相对 lwa 仓根，
// 统一过 lbPath 补上挂载前缀。仓根 = 从本页往上第一个带 _archive 的目录。
const LB_ROOT=(()=>{try{let d=dv.current()?.file?.folder||'';while(d&&!app.vault.getAbstractFileByPath(d+'/_archive'))d=d.includes('/')?d.slice(0,d.lastIndexOf('/')):'';return d;}catch{return '';}})();
const lbPath=p=>p&&LB_ROOT?`${LB_ROOT}/${p}`:p;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-catalog');
const style = root.createEl('style');
style.textContent = `
.markdown-preview-view.lb-catalog,.markdown-source-view.lb-catalog{--file-line-width:100%;}
.lb-catalog .markdown-preview-sizer,.lb-catalog .markdown-preview-section,.lb-catalog .cm-sizer,.lb-catalog .cm-contentContainer,.lb-catalog .cm-content,.lb-catalog .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-catalog .inline-title,.lb-catalog .metadata-container{display:none!important;}
.lbc-wrap{width:100%;padding:24px clamp(8px,2vw,36px) 40px;box-sizing:border-box;font-family:var(--font-interface),"Segoe UI","Microsoft YaHei",sans-serif;}
.lbc-head{display:flex;flex-direction:column;align-items:center;text-align:center;gap:13px;margin:8px 0 22px;}
.lbc-titleblock{display:flex;flex-direction:column;align-items:center;gap:5px;}
.lbc-titlerow{display:flex;align-items:baseline;justify-content:center;gap:4px;}
.lbc-title{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:42px;font-weight:600;letter-spacing:.01em;line-height:1.05;}
.lbc-wrap button.lbc-import{border:0!important;background:transparent!important;box-shadow:none!important;outline:0;border-radius:0!important;height:auto!important;font-family:Georgia,'Playfair Display','Times New Roman',serif!important;font-style:italic;font-size:38px;line-height:1;color:var(--text-faint);cursor:pointer;padding:0 4px;transition:color .12s;}
.lbc-import:hover{color:var(--interactive-accent);}
.lbc-subline{display:flex;gap:7px;align-items:center;justify-content:center;}
.lbc-search{width:100%!important;min-width:0;max-width:440px!important;text-align:center;height:36px!important;box-shadow:none!important;border-radius:0!important;background:transparent!important;border:0!important;border-bottom:1px solid var(--background-modifier-border)!important;padding:0 2px!important;}
.lbc-search:focus{border-bottom-color:var(--interactive-accent)!important;}
.lbc-sub{font-size:12px;color:var(--text-normal);white-space:nowrap;}
.lbc-sync{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:#e08a1e;color:#fff;font-size:11px;font-weight:700;font-family:sans-serif;cursor:pointer;flex:0 0 auto;}
.lbc-sync[hidden]{display:none;}
.lbc-grid{columns:250px;column-gap:32px;}
.lbc-card{display:inline-block;vertical-align:top;width:100%;margin:0 0 36px;break-inside:avoid;cursor:pointer;position:relative;}
.lbc-attach{position:absolute;top:8px;right:8px;font-size:11px;line-height:1;padding:4px 8px;border-radius:9px;background:rgba(0,0,0,.55);color:#fff;pointer-events:none;backdrop-filter:blur(2px);}
.lbc-attach-todo{background:#e08a1e;}
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
.lbc-attach-todo{color:#a86513;background:#fff8eb;border-color:#e8d8bc;}
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
`;
const pluginId='link-brain-actions';
let loadedPlugin=app.plugins.plugins[pluginId];
if(loadedPlugin && typeof loadedPlugin.openAttachments!=='function' && !loadedPlugin.running && !loadedPlugin.importing){
  await app.plugins.disablePlugin(pluginId);await app.plugins.enablePlugin(pluginId);
}
let data;
try { data = JSON.parse(await app.vault.adapter.read(lbPath('_archive/catalog-data.json'))); }
catch { root.createEl('p',{text:'目录尚未生成，请在归档操作中重建目录。'}); return; }
let items = data.items || [];
// 每次打开读笔记当前属性，后台插件增删标签无需重建目录。
for (const it of items) {
  const page = it.note ? dv.page(lbPath(it.note)) : null;
  if (page && page.tags !== undefined) {
    it.tags = typeof page.tags === 'string' ? [page.tags] : Array.from(page.tags || []);
  }
}
const wrap=root.createEl('div',{cls:'lbc-wrap'+(simplePage?' lbc-simple':'')});
const provider=()=>app.plugins.plugins['link-brain-actions'];
let committed='',chatMode=false,messages=[],busy=false;
async function refresh(next){data=next;items=next.items||[];renderCatBar();render();}
function attachmentPanel(list){if(typeof provider()?.openAttachments!=='function'){importStatus.setText('附件工具未载入，请重新启用 Link Brain Actions 插件。');return;}provider().openAttachments(list,refresh);}
function editCategories(selected=''){provider()?.openCategories(data.cats||[],selected,refresh);}
// 第一行：左=标题「Collections +」+ 其下计数·更新·未同步(!)；右=搜索横线。
const head=wrap.createEl('div',{cls:'lbc-head'});
const titleBlock=head.createEl('div',{cls:'lbc-titleblock'});
const titleRow=titleBlock.createEl('div',{cls:'lbc-titlerow'});
titleRow.createEl('span',{cls:'lbc-title',text:'Collections'});
const importButton=titleRow.createEl('button',{cls:'lbc-import',text:'+'});importButton.setAttribute('aria-label','导入收藏');importButton.title='导入收藏';
const subLine=titleBlock.createEl('div',{cls:'lbc-subline'});
let todayOnly=false;
const sub=subLine.createEl('span',{cls:'lbc-sub'});
const syncSpan=subLine.createEl('span',{cls:'lbc-sync'});syncSpan.hidden=true;syncSpan.setText('!');
syncSpan.onclick=()=>attachmentPanel(items.filter(it=>it.attachment==='待补'));
const search=head.createEl('input',{cls:'lbc-search'});
search.type='search';search.placeholder='搜索收藏…';search.title='Enter 搜索 · #标签 · /问题 问 AI';search.setAttribute('aria-label','搜索收藏');
const switchView=head.createEl('button',{cls:'lbc-view-switch',text:simplePage?'浏览收藏':'简洁搜索'});switchView.onclick=()=>app.workspace.openLinkText(lbPath(simplePage?'小红书收藏目录.md':'收藏搜索.md'),'',false);
const importStatus=wrap.createEl('div',{cls:'lbc-status'});
const trashButton=head.createEl('button',{cls:'lbc-view-switch',text:'回收站'});
trashButton.onclick=()=>app.workspace.openLinkText(lbPath('回收站.md'),'',false);
importButton.type='button';
importButton.setAttribute('aria-label','导入收藏 / 同步收藏夹');importButton.title='导入收藏 / 同步收藏夹';
importButton.onclick=async e=>{
  e.preventDefault();e.stopPropagation();importStatus.setText('');
  try{
    const id='link-brain-actions';let plugin=app.plugins.plugins[id];
    if(typeof plugin?.openPlusMenu!=='function'){
      importStatus.setText('正在载入…');
      if(plugin)await app.plugins.disablePlugin(id);
      await app.plugins.enablePlugin(id);plugin=app.plugins.plugins[id];
    }
    if(typeof plugin?.openPlusMenu!=='function')throw new Error('插件未加载，请在第三方插件中启用 Link Brain Actions');
    plugin.openPlusMenu(e);importStatus.setText('');
  }catch(error){importStatus.setText('菜单未打开：'+error.message);}
};
// 大类筛选条（小红书式 tab，灰竖线分隔）：单选，一次一个；「全部」或再点当前项清空。
let activeCat='';let todoOnly=false;
const catBar=wrap.createEl('div',{cls:'lbc-cats'});
function renderCatBar(){
  catBar.empty();
  const mk=(label,active,on)=>{const s=catBar.createEl('span',{cls:'lbc-cat'+(active?' is-active':''),text:label});s.onclick=()=>{if(label!=='…')chatMode=false;on();};return s;};
  mk('全部',!activeCat&&!todayOnly&&!todoOnly,()=>{if(activeCat||todayOnly||todoOnly){activeCat='';todayOnly=false;todoOnly=false;renderCatBar();render();}});
  mk('今日新增',todayOnly,()=>{todayOnly=!todayOnly;if(todayOnly)todoOnly=false;renderCatBar();render();});
  const todo=items.filter(x=>x.attachment==='待补').length;
  if(todo)mk(`待补附件 ${todo}`,todoOnly,()=>{todoOnly=!todoOnly;if(todoOnly)todayOnly=false;renderCatBar();render();});
  for(const cat of (data.cats_order||[]).filter(c=>!(provider()?.settings.hiddenCats||[]).includes(c))){
    catBar.createEl('span',{cls:'lbc-cat-sep',text:'│'});
    const tab=mk(cat,activeCat===cat,()=>{activeCat=(activeCat===cat?'':cat);renderCatBar();render();});
    tab.oncontextmenu=e=>{e.preventDefault();editCategories(cat);};
  }
  mk('…',false,()=>editCategories());
}
// 多选删除状态
let selectMode=false;const selected=new Set();
const selbar=wrap.createEl('div',{cls:'lbc-selbar'});selbar.hidden=true;
const selCount=selbar.createEl('span',{cls:'lbc-selcount'});
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
  const add=(label,fn,danger)=>{const b=menu.createEl('div',{cls:'lbc-menu-item'+(danger?' is-danger':'')});b.setText(label);b.onclick=ev=>{ev.stopPropagation();menu.remove();fn();};};
  add('编辑标签',()=>openTagEditor(body,it));
  if(it.attachment!=='none'){add('下载 / 挂本地文件',()=>attachmentPanel([it]));}
  add('删除收藏',()=>confirmDelete([it]),true);
  add('多选删除',()=>{selectMode=true;selected.add(it.id);render();});
  const close=()=>{menu.remove();document.removeEventListener('click',close);document.removeEventListener('contextmenu',close);};
  setTimeout(()=>{document.addEventListener('click',close);document.addEventListener('contextmenu',close);},0);
}
function render(){
  grid.empty();const q=normalize(committed);const asking=chatMode;
  const now=new Date();const today=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  const shown=items.filter(it=>(!todayOnly||it.date===today)&&(!todoOnly||it.attachment==='待补')&&(!activeCat||(it.cats||[]).includes(activeCat))).map(it=>({it,score:score(it,q,data.pinyin_chars,data.aliases||[])})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
  sub.setText((q||todayOnly||todoOnly?`${shown.length} / ${items.length} 篇`:`${items.length} 篇`)+` · 更新 ${new Date(data.built_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}`);
  const todoCount=items.filter(x=>x.attachment==='待补').length;
  if(todoCount){syncSpan.title=`${todoCount} 篇附件待处理 · 点此补跑`;syncSpan.hidden=false;}else syncSpan.hidden=true;
  ai.hidden=!asking;grid.hidden=asking;
  if(asking){selbar.hidden=true;return;}
  if(simplePage&&!q&&!activeCat&&!todayOnly&&!todoOnly){grid.createEl('div',{cls:'lbc-empty',text:'搜收藏，或输入 /问题 让 AI 整理答案。'});selbar.hidden=true;return;}
  selbar.hidden=!selectMode;
  if(selectMode){selCount.setText(`已选 ${selected.size} 篇 · 点封面继续勾选 · ESC 退出`);delBtn.setText(`删除选中${selected.size?' ('+selected.size+')':''}`);delBtn.disabled=!selected.size;}
  if(!shown.length){grid.createEl('div',{cls:'lbc-empty',text:'没找到，试试更短的关键词。'});return;}
  for(const {it} of shown){
    // 不设 aria-label：Obsidian 会把 aria-label 渲染成 hover 浮框（她不要那个「悬浮的点的字」）。
    const card=grid.createEl('article',{cls:'lbc-card'+(selectMode&&selected.has(it.id)?' is-selected':'')});card.tabIndex=0;card.setAttribute('role','link');
    if(it.cover){const img=card.createEl('img',{cls:'lbc-cover'});img.loading='lazy';img.alt='';img.src=app.vault.adapter.getResourcePath(lbPath(it.cover));}
    else card.createEl('div',{cls:'lbc-nocover',text:it.kind==='video'?'▷':'▤'});
    // 附件角标：待补=有文件未下载（橙），downloaded=有文件已下（灰）
    if(it.attachment==='待补')card.createEl('div',{cls:'lbc-attach lbc-attach-todo',text:'待补'});
    else if(it.attachment==='downloaded')card.createEl('div',{cls:'lbc-attach',text:'文件'});
    const badge=card.querySelector('.lbc-attach');if(badge){const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.innerHTML='<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>';badge.prepend(icon);}
    const body=card.createEl('div',{cls:'lbc-body'});body.createEl('div',{cls:'lbc-ctitle',text:it.title||'未命名'});
    const meta=body.createEl('div',{cls:'lbc-cmeta'});meta.createEl('span',{text:it.author||it.source||'收藏'});meta.createEl('span',{text:it.likes==null?'':'♡ '+(Number(it.likes)>=10000?(Number(it.likes)/10000).toFixed(1)+'万':it.likes)});
    if(simplePage){const text=it.search_text||it.summary||'';const pos=q?text.toLowerCase().indexOf(q):-1;body.createEl('div',{cls:'lbc-result-excerpt',text:text.slice(Math.max(0,pos-40),Math.max(0,pos-40)+220)});}
    card.ondragover=e=>{e.preventDefault();};card.ondrop=async e=>{e.preventDefault();e.stopPropagation();const f=e.dataTransfer.files[0];if(!f)return;const fp=f.path||require('electron').webUtils?.getPathForFile(f);if(!fp){attachmentPanel([it]);return;}try{const result=await provider().attachFile(it.id,fp);await refresh(JSON.parse(await app.vault.adapter.read(lbPath('_archive/catalog-data.json'))));importStatus.setText(result.warning||'附件已保存并加入搜索');}catch(err){importStatus.setText('挂载失败：'+err.message);}};
    // 多选模式：点击=勾选/取消；平时=打开笔记
    const toggle=()=>{selected.has(it.id)?selected.delete(it.id):selected.add(it.id);render();};
    const open=()=>{if(selectMode){toggle();return;}if(it.note)app.workspace.openLinkText(lbPath(it.note),'',false);};
    card.onclick=open;card.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();open();}};
    card.oncontextmenu=e=>{e.preventDefault();openCardMenu(e,body,it);};
  }
}
// ESC 退出多选（去重：重开页面时先摘掉上一份监听器，别叠加）
if(window.__lbcEsc)document.removeEventListener('keydown',window.__lbcEsc);
window.__lbcEsc=e=>{if(e.key==='Escape'&&selectMode){selectMode=false;selected.clear();render();}};
document.addEventListener('keydown',window.__lbcEsc);
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
  try {const result=await provider().answerArchive({question:q,history});messages.push({role:'assistant',content:result.markdown||'没有可用的回答。',sources:result.sources||[]});}
  catch(e){messages.push({role:'assistant',failed:true,content:'回答失败：'+e.message+'\n\n请重试。'});}
  finally{busy=false;await drawChat();}
}
search.onkeydown=e=>{
  if(e.key!=='Enter'||e.isComposing)return;
  e.preventDefault();const raw=search.value.trim();
  if(raw.startsWith('/')){if(!raw.slice(1).trim()||busy)return;messages=[];committed='';sendQuestion(raw.slice(1).trim());}
  else {if(busy)return;chatMode=false;committed=raw;render();}
};
search.oninput=()=>{if(!search.value&&!busy){committed='';chatMode=false;render();}};
renderCatBar();render();

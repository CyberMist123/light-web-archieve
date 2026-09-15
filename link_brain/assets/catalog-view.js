const root = dv.container;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-catalog');
const style = root.createEl('style');
style.textContent = `
.markdown-preview-view.lb-catalog,.markdown-source-view.lb-catalog{--file-line-width:100%;}
.lb-catalog .markdown-preview-sizer,.lb-catalog .markdown-preview-section,.lb-catalog .cm-sizer,.lb-catalog .cm-contentContainer,.lb-catalog .cm-content,.lb-catalog .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-catalog .inline-title,.lb-catalog .metadata-container{display:none!important;}
.lbc-wrap{width:100%;padding:24px clamp(8px,2vw,36px) 40px;box-sizing:border-box;}
.lbc-head{display:flex;align-items:center;gap:22px;margin:0 0 22px;flex-wrap:wrap;}
.lbc-title{font-size:22px;font-weight:650;letter-spacing:.02em;}
.lbc-search{flex:1;min-width:180px;max-width:660px!important;height:44px!important;border:0!important;box-shadow:none!important;border-radius:24px!important;background:var(--background-secondary)!important;padding:0 20px!important;}
.lbc-sub{font-size:11px;color:var(--text-faint);margin-left:auto;white-space:nowrap;}
.lbc-grid{columns:250px;column-gap:32px;}
.lbc-card{display:inline-block;vertical-align:top;width:100%;margin:0 0 36px;break-inside:avoid;cursor:pointer;}
.lbc-cover{display:block;width:100%;height:auto;max-height:360px;object-fit:cover;object-position:top;border-radius:16px;border:1px solid var(--background-modifier-border);transition:filter .15s;}
.lbc-card:hover .lbc-cover{filter:brightness(.95);}
.lbc-card:focus-visible{outline:2px solid var(--interactive-accent);outline-offset:5px;border-radius:16px;}
.lbc-card.is-selected .lbc-cover,.lbc-card.is-selected .lbc-nocover{outline:3px solid var(--interactive-accent);outline-offset:2px;filter:brightness(.92);}
.lbc-selbar{display:flex;gap:12px;align-items:center;margin:0 0 18px;padding:10px 14px;border-radius:12px;background:var(--background-secondary);}
.lbc-selcount{font-size:13px;color:var(--text-muted);margin-right:auto;}
.lbc-selbar button{border:0;border-radius:8px;padding:6px 14px;}
.lbc-selbar button.mod-warning{background:var(--background-modifier-error,rgba(220,80,80,.15));color:var(--text-error,#c0392b);}
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
.lbc-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:0 0 30px;}
.lbc-toolbar button{border:0;box-shadow:none;border-radius:20px;padding:8px 16px;background:var(--background-secondary);}
.lbc-toolbar button.is-active{color:var(--interactive-accent);background:var(--background-modifier-hover);}
.lbc-import{margin-left:auto;}
.lbc-status{font-size:12px;color:var(--text-muted);}
.lbc-cats{display:flex;flex-wrap:wrap;align-items:center;margin:0 0 22px;font-size:13px;}
.lbc-cat{padding:4px 12px;cursor:pointer;color:var(--text-muted);border-radius:8px;transition:color .12s;}
.lbc-cat:hover{color:var(--text-normal);}
.lbc-cat.is-active{color:var(--interactive-accent);font-weight:600;}
.lbc-cat-sep{color:var(--background-modifier-border);user-select:none;pointer-events:none;}
.lbc-ai{padding:22px;border:1px solid var(--background-modifier-border);border-radius:16px;margin-bottom:24px;}
.lbc-ai-q{color:var(--text-muted);font-size:13px;margin:6px 0 12px;}
.lbc-ai-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px;}
.lbc-ai-answer{line-height:1.7;}
.lbc-ai-answer p:first-child{margin-top:0;}
.lbc-ai-meta{color:var(--text-faint);font-size:11px;margin-top:14px;}
.lbc-ai-error{padding:12px 14px;border-radius:10px;background:var(--background-modifier-error,rgba(220,80,80,.12));color:var(--text-error,#c0392b);}
.lbc-ai-error strong{display:block;margin-bottom:4px;}
@media(max-width:650px){.lbc-grid{columns:180px;column-gap:18px;}.lbc-sub{width:100%;margin:0;}.lbc-wrap{padding:12px 4px;}}
`;
let data;
try { data = JSON.parse(await app.vault.adapter.read('_archive/catalog-data.json')); }
catch { root.createEl('p',{text:'目录尚未生成，请在归档操作中重建目录。'}); return; }
const items = data.items || [];
// 每次打开读笔记当前属性，后台插件增删标签无需重建目录。
for (const it of items) {
  const page = it.note ? dv.page(it.note) : null;
  if (page && page.tags !== undefined) {
    it.tags = typeof page.tags === 'string' ? [page.tags] : Array.from(page.tags || []);
  }
}
const wrap=root.createEl('div',{cls:'lbc-wrap'});
const head=wrap.createEl('div',{cls:'lbc-head'});
head.createEl('span',{cls:'lbc-title',text:'我的收藏'});
const search=head.createEl('input',{cls:'lbc-search'});
search.type='search';search.placeholder='搜索收藏…';search.title='普通搜索 · #标签 · /问知识库';search.setAttribute('aria-label','搜索收藏');
const toolbar=wrap.createEl('div',{cls:'lbc-toolbar'});
const sub=toolbar.createEl('span',{cls:'lbc-sub'});
let todayOnly=false;
const allButton=toolbar.createEl('button',{text:'全部',cls:'is-active'});
const todayButton=toolbar.createEl('button',{text:'今日新增'});
allButton.onclick=()=>{todayOnly=false;allButton.addClass('is-active');todayButton.removeClass('is-active');render();};
todayButton.onclick=()=>{todayOnly=true;todayButton.addClass('is-active');allButton.removeClass('is-active');render();};
const selectButton=toolbar.createEl('button',{text:'多选'});
selectButton.onclick=()=>{selectMode=!selectMode;selected.clear();selectButton.toggleClass('is-active',selectMode);render();};
const importButton=toolbar.createEl('button',{text:'+ 导入',cls:'lbc-import'});
const importStatus=wrap.createEl('div',{cls:'lbc-status'});
importButton.type='button';
importButton.onclick=async e=>{
  e.preventDefault();e.stopPropagation();importButton.disabled=true;importStatus.setText('');
  try{
    const id='link-brain-actions';let plugin=app.plugins.plugins[id];
    if(plugin?.running||plugin?.importing)throw new Error('已有归档任务运行中，请稍后再导入');
    if(typeof plugin?.openImportModal!=='function'){
      importStatus.setText('正在载入导入工具…');
      if(plugin)await app.plugins.disablePlugin(id);
      await app.plugins.enablePlugin(id);plugin=app.plugins.plugins[id];
    }
    if(typeof plugin?.openImportModal!=='function')throw new Error('导入插件未加载，请在第三方插件中启用 Link Brain Actions');
    plugin.openImportModal();importStatus.setText('');
  }catch(error){importStatus.setText('导入未打开：'+error.message);}
  finally{importButton.disabled=false;}
};
// 大类筛选条（小红书式 tab，灰竖线分隔）：多选=「或」（命中任一大类即显示）；「全部」清空。
const activeCats=new Set();
const catBar=wrap.createEl('div',{cls:'lbc-cats'});
function renderCatBar(){
  catBar.empty();
  const mk=(label,active,on)=>{const s=catBar.createEl('span',{cls:'lbc-cat'+(active?' is-active':''),text:label});s.onclick=on;return s;};
  mk('全部',activeCats.size===0,()=>{if(activeCats.size){activeCats.clear();renderCatBar();render();}});
  for(const cat of (data.cats_order||[])){
    catBar.createEl('span',{cls:'lbc-cat-sep',text:'│'});
    mk(cat,activeCats.has(cat),()=>{activeCats.has(cat)?activeCats.delete(cat):activeCats.add(cat);renderCatBar();render();});
  }
}
// 多选删除状态
let selectMode=false;const selected=new Set();
const selbar=wrap.createEl('div',{cls:'lbc-selbar'});selbar.hidden=true;
const selCount=selbar.createEl('span',{cls:'lbc-selcount'});
const delBtn=selbar.createEl('button',{text:'删除选中',cls:'mod-warning'});
delBtn.onclick=()=>confirmDelete(items.filter(x=>selected.has(x.id)));
const clrBtn=selbar.createEl('button',{text:'清空选择'});clrBtn.onclick=()=>{selected.clear();render();};
const ai=wrap.createEl('section',{cls:'lbc-ai'});ai.hidden=true;
const grid=wrap.createEl('div',{cls:'lbc-grid'});

// 删除收藏（不可逆）：确认 → 后端删文件+索引 → 本地从 items 摘掉 → 重渲染
async function confirmDelete(list){
  if(!list.length)return;
  const names=list.slice(0,4).map(x=>x.title||x.id).join('、')+(list.length>4?` 等 ${list.length} 篇`:'');
  if(!window.confirm(`删除收藏：${names}\n\n会删掉笔记和归档文件，不可恢复。确定吗？`))return;
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
    try{const file=app.vault.getAbstractFileByPath(it.note);const tags=[...new Set(field.value.split(/[,，\n]/).map(t=>t.trim().replace(/^#/, '')).filter(Boolean))];
      await app.fileManager.processFrontMatter(file,fm=>{fm.tags=tags;});it.tags=tags;render();
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
  add('删除收藏',()=>confirmDelete([it]),true);
  const close=()=>{menu.remove();document.removeEventListener('click',close);document.removeEventListener('contextmenu',close);};
  setTimeout(()=>{document.addEventListener('click',close);document.addEventListener('contextmenu',close);},0);
}
function render(){
  grid.empty();const raw=search.value.trim();const asking=raw.startsWith('/');const q=normalize(asking?raw.slice(1):raw);
  const now=new Date();const today=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  const shown=items.filter(it=>(!todayOnly||it.date===today)&&(activeCats.size===0||(it.cats||[]).some(cc=>activeCats.has(cc)))).map(it=>({it,score:score(it,q,data.pinyin_chars)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
  sub.setText((q||todayOnly?`${shown.length} / ${items.length} 篇`:`${items.length} 篇`)+` · 更新 ${new Date(data.built_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}`);
  ai.hidden=!asking;ai.empty();
  if(asking){
    ai.createEl('strong',{text:'问知识库'});
    ai.createEl('p',{cls:'lbc-ai-q',text:q||'在 / 后输入你的问题（例：所有 AI 做梦相关，链接给我 / 提取 github 地址）'});
    const provider=app.plugins.plugins['link-brain-actions'];
    const answer=ai.createEl('div',{cls:'lbc-ai-answer'});
    if(typeof provider?.answerArchive!=='function'){
      answer.setText('AI 未接入：请在「第三方插件」里启用 Link Brain Actions，并在其设置里配置「文本 AI」。下方仍显示本地检索结果。');
    } else if(!q){
      answer.setText('在 / 后面输入问题，然后点「提问」。打字不发请求、不花 token。');
    } else {
      const bar=ai.createEl('div',{cls:'lbc-ai-bar'});
      const ask=bar.createEl('button',{text:'提问',cls:'mod-cta'});
      const copyBtn=bar.createEl('button',{text:'复制回答'});copyBtn.disabled=true;
      const meta=ai.createEl('div',{cls:'lbc-ai-meta'});
      answer.setText('点「提问」，AI 会自己重新检索整库、只把少量片段送模型来回答。');
      let lastMd='';
      copyBtn.onclick=async()=>{if(!lastMd)return;try{await navigator.clipboard.writeText(lastMd);copyBtn.setText('已复制');setTimeout(()=>copyBtn.setText('复制回答'),1500);}catch{copyBtn.setText('复制失败');setTimeout(()=>copyBtn.setText('复制回答'),1500);}};
      ask.onclick=async()=>{
        ask.disabled=true;copyBtn.disabled=true;answer.empty();answer.setText('正在检索并回答…');meta.setText('');
        try{
          const r=await provider.answerArchive({question:q});
          answer.empty();lastMd=r.markdown||'';
          await provider.renderMarkdownInto(lastMd||'（无内容）',answer,'小红书收藏目录.md');
          copyBtn.disabled=!lastMd;
          const u=r.usage?` · tokens ${r.usage.total_tokens||((r.usage.prompt_tokens||0)+(r.usage.completion_tokens||0))||'?'}`:'';
          meta.setText(`意图 ${r.intent} · 全库命中 ${r.matches} 篇 · 送模型 ${r.materials} 篇${u}`);
          if((provider.settings?.tts?.endpoint||'').trim() && r.model_called && !bar.querySelector('.lbc-ai-speak')){
            const speak=bar.createEl('button',{text:'🔊 朗读',cls:'lbc-ai-speak'});
            speak.onclick=async()=>{speak.disabled=true;const old=speak.textContent;speak.setText('合成中…');try{await provider.speak(lastMd);}catch(e){meta.setText('朗读失败：'+e.message);}finally{speak.setText(old);speak.disabled=false;}};
          }
        }catch(e){
          answer.empty();
          const box=answer.createEl('div',{cls:'lbc-ai-error'});
          box.createEl('strong',{text:'⚠ 检索失败'});
          box.createEl('div',{text:String(e.message||e)});
          box.createEl('div',{cls:'lbc-ai-meta',text:'常见原因：文本 AI 未配置或不通（设置里点「测试文本 AI」）、后端未启动。问题还在，改完可再点「提问」。'});
        }
        finally{ask.disabled=false;}
      };
    }
  }
  selbar.hidden=!selectMode;
  if(selectMode)selCount.setText(`已选 ${selected.size} 篇`);
  if(!shown.length){grid.createEl('div',{cls:'lbc-empty',text:'没找到，试试更短的关键词。'});return;}
  for(const {it} of shown){
    // 不设 aria-label：Obsidian 会把 aria-label 渲染成 hover 浮框（她不要那个「悬浮的点的字」）。
    const card=grid.createEl('article',{cls:'lbc-card'+(selectMode&&selected.has(it.id)?' is-selected':'')});card.tabIndex=0;card.setAttribute('role','link');
    if(it.cover){const img=card.createEl('img',{cls:'lbc-cover'});img.loading='lazy';img.alt='';img.src=app.vault.adapter.getResourcePath(it.cover);}
    else card.createEl('div',{cls:'lbc-nocover',text:it.kind==='video'?'▷':'▤'});
    const body=card.createEl('div',{cls:'lbc-body'});body.createEl('div',{cls:'lbc-ctitle',text:it.title||'未命名'});
    const meta=body.createEl('div',{cls:'lbc-cmeta'});meta.createEl('span',{text:it.author||it.source||'收藏'});meta.createEl('span',{text:it.likes==null?'':'♡ '+(Number(it.likes)>=10000?(Number(it.likes)/10000).toFixed(1)+'万':it.likes)});
    // 多选模式：点击=勾选/取消；平时=打开笔记
    const toggle=()=>{selected.has(it.id)?selected.delete(it.id):selected.add(it.id);render();};
    const open=()=>{if(selectMode){toggle();return;}if(it.note)app.workspace.openLinkText(it.note,'',false);};
    card.onclick=open;card.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();open();}};
    card.oncontextmenu=e=>{e.preventDefault();openCardMenu(e,body,it);};
  }
}
let timer;search.oninput=()=>{clearTimeout(timer);timer=setTimeout(render,120);};renderCatBar();render();

const root = dv.container;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-catalog');
const style = root.createEl('style');
style.textContent = `
.markdown-preview-view.lb-catalog,.markdown-source-view.lb-catalog{--file-line-width:100%;}
.lb-catalog .markdown-preview-sizer,.lb-catalog .markdown-preview-section,.lb-catalog .cm-sizer,.lb-catalog .cm-contentContainer,.lb-catalog .cm-content,.lb-catalog .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-catalog .inline-title,.lb-catalog .metadata-container{display:none!important;}
.lbc-wrap{width:100%;padding:12px 4px;box-sizing:border-box;}
.lbc-head{display:flex;align-items:center;gap:24px;margin:0 0 28px;flex-wrap:wrap;}
.lbc-title{font-size:22px;font-weight:650;letter-spacing:.02em;}
.lbc-search{flex:1;min-width:180px;max-width:660px!important;height:44px!important;border:0!important;box-shadow:none!important;border-radius:24px!important;background:var(--background-secondary)!important;padding:0 20px!important;}
.lbc-sub{font-size:12px;color:var(--text-muted);margin-left:auto;}
.lbc-grid{columns:210px;column-gap:24px;}
.lbc-card{display:inline-block;vertical-align:top;width:100%;margin:0 0 26px;break-inside:avoid;cursor:pointer;}
.lbc-cover{display:block;width:100%;height:auto;max-height:360px;object-fit:cover;object-position:top;border-radius:16px;border:1px solid var(--background-modifier-border);transition:filter .15s;}
.lbc-card:hover .lbc-cover{filter:brightness(.95);}
.lbc-card:focus-visible{outline:2px solid var(--interactive-accent);outline-offset:5px;border-radius:16px;}
.lbc-nocover{aspect-ratio:4/3;border-radius:16px;background:var(--background-secondary);display:grid;place-items:center;color:var(--text-muted);font-size:30px;}
.lbc-body{padding:11px 8px 0;}
.lbc-ctitle{font-size:14px;line-height:1.55;font-weight:550;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbc-cmeta{display:flex;justify-content:space-between;gap:10px;color:var(--text-muted);font-size:12px;margin-top:8px;}
.lbc-cmeta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbc-empty{padding:40px;color:var(--text-muted);}
.lbc-toolbar{display:flex;gap:10px;align-items:center;margin:0 0 22px;}
.lbc-toolbar button{border:0;box-shadow:none;border-radius:20px;padding:8px 16px;background:var(--background-secondary);}
.lbc-toolbar button.is-active{color:var(--interactive-accent);background:var(--background-modifier-hover);}
.lbc-ai{padding:22px;border:1px solid var(--background-modifier-border);border-radius:16px;margin-bottom:24px;white-space:pre-wrap;}
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
search.type='search';search.placeholder='搜索收藏 /问AI的问题 #标签';search.setAttribute('aria-label','搜索收藏');
const sub=head.createEl('span',{cls:'lbc-sub'});
const toolbar=wrap.createEl('div',{cls:'lbc-toolbar'});
let todayOnly=false;
const allButton=toolbar.createEl('button',{text:'全部',cls:'is-active'});
const todayButton=toolbar.createEl('button',{text:'今日新增'});
allButton.onclick=()=>{todayOnly=false;allButton.addClass('is-active');todayButton.removeClass('is-active');render();};
todayButton.onclick=()=>{todayOnly=true;todayButton.addClass('is-active');allButton.removeClass('is-active');render();};
const importButton=toolbar.createEl('button',{text:'+ 导入链接'});
importButton.onclick=()=>app.commands.executeCommandById('link-brain-actions:import-links');
const ai=wrap.createEl('section',{cls:'lbc-ai'});ai.hidden=true;
const grid=wrap.createEl('div',{cls:'lbc-grid'});
function render(){
  grid.empty();const raw=search.value.trim();const asking=raw.startsWith('/');const q=normalize(asking?raw.slice(1):raw);
  const now=new Date();const today=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  const shown=items.filter(it=>!todayOnly||it.date===today).map(it=>({it,score:score(it,q,data.pinyin_chars)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
  sub.setText((q||todayOnly?`${shown.length} / ${items.length} 篇`:`${items.length} 篇`)+` · 更新 ${new Date(data.built_at).toLocaleString('zh-CN',{hour12:false})}`);
  ai.hidden=!asking;ai.empty();
  if(asking){
    ai.createEl('strong',{text:'问 AI'});ai.createEl('p',{text:q||'在 / 后输入你的问题'});
    const answer=ai.createEl('div',{text:'AI 回答尚未接入。下方显示本地检索结果；接入后回答会显示在这里。'});
    const provider=app.plugins.plugins['link-brain-actions'];
    if(typeof provider?.answerArchive==='function'){
      answer.setText('点击提问，结合当前检索到的收藏回答。');const ask=ai.createEl('button',{text:'提问'});
      ask.onclick=async()=>{ask.disabled=true;answer.setText('正在回答…');try{answer.setText(await provider.answerArchive({question:q,items:shown.slice(0,12).map(x=>x.it)}));}catch(e){answer.setText('回答失败：'+e.message);}finally{ask.disabled=false;}};
    }
  }
  if(!shown.length){grid.createEl('div',{cls:'lbc-empty',text:'没找到，试试更短的关键词。'});return;}
  for(const {it} of shown){
    const card=grid.createEl('article',{cls:'lbc-card'});card.tabIndex=0;card.setAttribute('role','link');card.setAttribute('aria-label',it.title||'打开收藏');
    card.title=it.summary||it.title||'';
    if(it.cover){const img=card.createEl('img',{cls:'lbc-cover'});img.loading='lazy';img.alt='';img.src=app.vault.adapter.getResourcePath(it.cover);}
    else card.createEl('div',{cls:'lbc-nocover',text:it.kind==='video'?'▷':'▤'});
    const body=card.createEl('div',{cls:'lbc-body'});body.createEl('div',{cls:'lbc-ctitle',text:it.title||'未命名'});
    const meta=body.createEl('div',{cls:'lbc-cmeta'});meta.createEl('span',{text:it.author||it.source||'收藏'});meta.createEl('span',{text:it.likes==null?'':'♡ '+(Number(it.likes)>=10000?(Number(it.likes)/10000).toFixed(1)+'万':it.likes)});
    const open=()=>{if(it.note)app.workspace.openLinkText(it.note,'',false);};card.onclick=open;card.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();open();}};
    card.oncontextmenu=e=>{
      e.preventDefault();if(card.querySelector('form'))return;
      const form=body.createEl('form');form.onclick=e=>e.stopPropagation();form.onkeydown=e=>e.stopPropagation();
      const field=form.createEl('input');field.type='text';field.value=(it.tags||[]).join(', ');field.placeholder='标签，用逗号分隔';field.setAttribute('aria-label','编辑收藏标签');field.style.width='100%';
      const save=form.createEl('button',{text:'保存标签'});save.type='submit';
      const cancel=form.createEl('button',{text:'取消'});cancel.type='button';cancel.onclick=()=>form.remove();
      form.onsubmit=async e=>{e.preventDefault();save.disabled=true;
        try{const file=app.vault.getAbstractFileByPath(it.note);const tags=[...new Set(field.value.split(/[,，\n]/).map(t=>t.trim().replace(/^#/, '')).filter(Boolean))];
          await app.fileManager.processFrontMatter(file,fm=>{fm.tags=tags;});it.tags=tags;render();
        }catch{save.disabled=false;save.setText('保存失败，重试');}
      };field.focus();
    };
  }
}
let timer;search.oninput=()=>{clearTimeout(timer);timer=setTimeout(render,120);};render();

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
.lbc-nocover{aspect-ratio:4/3;border-radius:16px;background:var(--background-secondary);display:grid;place-items:center;color:var(--text-muted);font-size:30px;}
.lbc-body{padding:11px 8px 0;}
.lbc-ctitle{font-size:14px;line-height:1.7;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbc-cmeta{display:flex;justify-content:space-between;gap:10px;color:var(--text-muted);font-size:12px;margin-top:8px;}
.lbc-cmeta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbc-empty{padding:40px;color:var(--text-muted);}
.lbc-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:0 0 30px;}
.lbc-toolbar button{border:0;box-shadow:none;border-radius:20px;padding:8px 16px;background:var(--background-secondary);}
.lbc-toolbar button.is-active{color:var(--interactive-accent);background:var(--background-modifier-hover);}
.lbc-ai{padding:22px;border:1px solid var(--background-modifier-border);border-radius:16px;margin-bottom:24px;}
.lbc-ai-q{color:var(--text-muted);font-size:13px;margin:6px 0 12px;}
.lbc-ai-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px;}
.lbc-ai-answer{line-height:1.7;}
.lbc-ai-answer p:first-child{margin-top:0;}
.lbc-ai-meta{color:var(--text-faint);font-size:11px;margin-top:14px;}
.lbc-import{margin-left:auto;}
.lbc-status{font-size:12px;color:var(--text-muted);}
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
const ai=wrap.createEl('section',{cls:'lbc-ai'});ai.hidden=true;
const grid=wrap.createEl('div',{cls:'lbc-grid'});
function render(){
  grid.empty();const raw=search.value.trim();const asking=raw.startsWith('/');const q=normalize(asking?raw.slice(1):raw);
  const now=new Date();const today=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  const shown=items.filter(it=>!todayOnly||it.date===today).map(it=>({it,score:score(it,q,data.pinyin_chars)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
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
        }catch(e){answer.empty();answer.setText('回答失败：'+e.message);}
        finally{ask.disabled=false;}
      };
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

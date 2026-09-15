const root = dv.container;
const style = root.createEl('style');
style.textContent = `
.markdown-preview-view.lb-catalog,.markdown-source-view.lb-catalog{--file-line-width:100%;}
.lb-catalog .markdown-preview-sizer,.lb-catalog .markdown-preview-section,.lb-catalog .cm-sizer,.lb-catalog .cm-contentContainer,.lb-catalog .cm-content,.lb-catalog .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-catalog .inline-title{display:none;}
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
search.type='search';search.placeholder='搜索收藏，几个关键词也可以…';search.setAttribute('aria-label','搜索收藏');
const sub=head.createEl('span',{cls:'lbc-sub'});
const grid=wrap.createEl('div',{cls:'lbc-grid'});
const normalize=s=>String(s||'').normalize('NFKC').toLowerCase().replace(/[#，。！？、]/g,' ');
function score(it,q){
  if(!q)return 1;
  const title=normalize(it.title),hay=normalize([it.title,it.summary,it.search_text,it.author,...(it.tags||[])].join(' '));
  const terms=q.split(/\s+/).filter(Boolean);let total=0;
  for(const term of terms){
    if(title.includes(term)){total+=8;continue;}
    if(hay.includes(term)){total+=4;continue;}
    // 非连续字串匹配：例如「记忆框架」可命中「记忆管理框架」。
    let pos=0;for(const c of term){pos=hay.indexOf(c,pos);if(pos<0)break;pos++;}
    if(pos>=0 && term.length>=2){total+=1;continue;}
    // 英文近似拼写：允许一个插入、删除或替换。
    const near=term.length>=4 && /^[a-z]+$/.test(term) && hay.split(/[^a-z]+/).some(word=>{
      if(Math.abs(word.length-term.length)>1)return false;
      let i=0,j=0,errors=0;while(i<term.length&&j<word.length){if(term[i]===word[j]){i++;j++;}else{if(++errors>1)return false;if(term.length>=word.length)i++;if(word.length>=term.length)j++;}}
      return errors+(term.length-i)+(word.length-j)<=1;
    });
    if(near){total+=1;continue;}return 0;
  }return total;
}
function render(){
  grid.empty();const q=normalize(search.value).trim();
  const shown=items.map(it=>({it,score:score(it,q)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
  sub.setText(q?`${shown.length} / ${items.length} 篇`:`${items.length} 篇`);
  if(!shown.length){grid.createEl('div',{cls:'lbc-empty',text:'没找到，试试更短的关键词。'});return;}
  for(const {it} of shown){
    const card=grid.createEl('article',{cls:'lbc-card'});card.tabIndex=0;card.setAttribute('role','link');card.setAttribute('aria-label',it.title||'打开收藏');
    card.title=it.summary||it.title||'';
    if(it.cover){const img=card.createEl('img',{cls:'lbc-cover'});img.loading='lazy';img.alt='';img.src=app.vault.adapter.getResourcePath(it.cover);}
    else card.createEl('div',{cls:'lbc-nocover',text:it.kind==='video'?'▷':'▤'});
    const body=card.createEl('div',{cls:'lbc-body'});body.createEl('div',{cls:'lbc-ctitle',text:it.title||'未命名'});
    const meta=body.createEl('div',{cls:'lbc-cmeta'});meta.createEl('span',{text:it.author||it.source||'收藏'});meta.createEl('span',{text:it.date||''});
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

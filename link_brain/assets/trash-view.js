const LB_ROOT=(()=>{let d=dv.current()?.file?.folder||'';while(d&&!app.vault.getAbstractFileByPath(d+'/_archive'))d=d.includes('/')?d.slice(0,d.lastIndexOf('/')):'';return d;})();
const lbPath=p=>LB_ROOT?LB_ROOT+'/'+p:p;
const root=dv.container;
const provider=()=>app.plugins.plugins['link-brain-actions'];
async function action(kind,ids){
  if(kind!=='restore'&&!window.confirm('彻底删除文件？此操作不可恢复，仍会屏蔽以后同步。'))return;
  try{await provider().trashAction(kind,ids);await draw();}
  catch(e){window.alert(e.message);}
}
async function draw(){
  root.empty();
  const data=JSON.parse(await app.vault.adapter.read(lbPath('_archive/trash-data.json')));
  const clear=root.createEl('button',{text:'清空回收站'});
  clear.disabled=!data.items.some(x=>x.has_files);
  clear.onclick=()=>action('empty',[]);
  root.createEl('p',{text:'已彻底删除的条目保留记录，不会重新同步。'});
  for(const item of data.items){
    const row=root.createEl('div');row.style.cssText='display:flex;gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid var(--background-modifier-border)';
    if(item.cover&&item.has_files){const img=row.createEl('img');img.src=app.vault.adapter.getResourcePath(lbPath(item.cover));img.style.cssText='width:64px;height:72px;object-fit:cover;border-radius:8px';}
    const text=row.createEl('div');text.style.flex='1';
    text.createEl('div',{text:item.title||'未命名收藏'});
    text.createEl('small',{text:item.deleted_at.slice(0,10)+(item.restorable?'':item.has_files?' · 旧孤儿笔记，归档缺失':' · 文件已彻底删除')});
    if(item.restorable){
      row.createEl('button',{text:'恢复'}).onclick=()=>action('restore',[item.item_id]);
    }
    if(item.has_files)row.createEl('button',{text:'彻底删除'}).onclick=()=>action('purge',[item.item_id]);
  }
}
await draw();

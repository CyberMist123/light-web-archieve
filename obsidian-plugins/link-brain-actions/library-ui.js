module.exports = function(obsidian) {
const {Modal, Notice} = obsidian;
const fs = require('fs/promises');
const path = require('path');
const electron = require('electron');

function cleanName(name) { return name.normalize('NFKC').toLowerCase().replace(/\s*\(\d+\)(?=\.[^.]+$)/,'').replace(/[\s_-]/g,''); }
function filePath(file) { return file.path || electron.webUtils?.getPathForFile(file); }

class AttachmentModal extends Modal {
  constructor(plugin, items, refresh) { super(plugin.app); this.plugin=plugin; this.items=items; this.refresh=refresh; this.busy=false; }
  onOpen() {
    this.alive=true;
    const el=this.contentEl;
    el.createEl('h2',{text:'补齐附件'});
    const note=el.createEl('select');note.style.width='100%';
    this.items.forEach((it,i)=>note.createEl('option',{value:String(i),text:it.title}));
    const docs=el.createEl('select');docs.style.cssText='width:100%;margin:12px 0';this.docs=docs;
    const folder=el.createEl('p');folder.style.cssText='font-size:12px;color:var(--text-muted);overflow-wrap:anywhere';
    folder.setText('下载目录：'+this.plugin.settings.downloads.folder+'（可在插件设置修改）');
    const zone=el.createEl('div',{text:'把文件拖到这里，或选择本地文件'});
    zone.style.cssText='border:1px dashed var(--background-modifier-border);border-radius:12px;padding:24px;text-align:center;margin:12px 0';
    const picker=zone.createEl('input');picker.type='file';picker.style.cssText='display:block;margin:12px auto 0;max-width:100%';
    picker.onchange=()=>{if(picker.files[0])this.attach(filePath(picker.files[0]));};
    zone.ondragover=e=>{e.preventDefault();e.stopPropagation();};
    zone.ondrop=e=>{e.preventDefault();e.stopPropagation();if(e.dataTransfer.files[0])this.attach(filePath(e.dataTransfer.files[0]));};
    const controls=el.createEl('div');controls.style.cssText='display:flex;gap:8px;flex-wrap:wrap';
    const open=controls.createEl('button',{text:'打开原网页，等待下载'});
    open.onclick=()=>this.waitDownload();
    controls.createEl('button',{text:'刷新推荐文件'}).onclick=()=>this.scan();
    controls.createEl('button',{text:'停止等待'}).onclick=()=>{this.stop();this.status.setText('已停止等待；网页标签可以手动关闭。');};
    this.status=el.createEl('p');this.status.style.cssText='font-size:13px;white-space:pre-wrap';
    this.list=el.createEl('div');
    note.onchange=()=>{this.stop();this.item=this.items[Number(note.value)];this.fillDocs();this.scan();};
    docs.onchange=()=>{this.stop();this.scan();};
    this.item=this.items[0];this.fillDocs();this.scan();
  }
  fillDocs() {
    this.docs.empty();
    (this.item.attachment_files||[]).forEach((f,i)=>this.docs.createEl('option',{value:String(i),text:(f.downloaded?'已存 · ':f.doc_id?'待补 · ':'线索待确认 · ')+f.name}));
    const idx=(this.item.attachment_files||[]).findIndex(f=>!f.downloaded);
    if(idx>=0)this.docs.value=String(idx);
    if(this.status)this.status.setText((this.item.attachment_errors||[]).map(r=>r.error).join("\n"));
  }
  selected() { return (this.item.attachment_files||[])[Number(this.docs.value)] || {}; }
  async candidates() {
    const folder=this.plugin.settings.downloads.folder;
    const names=await fs.readdir(folder,{withFileTypes:true});
    const expected=cleanName(this.selected().name||'');
    const title=cleanName(this.item.title||'');
    const files=await Promise.all(names.filter(f=>f.isFile()&&!/\.(crdownload|part|tmp|download)$/i.test(f.name)).map(async f=>{
      const full=path.join(folder,f.name),st=await fs.stat(full),name=cleanName(f.name);
      const stem=cleanName(path.parse(f.name).name);
      return {path:full,name:f.name,size:st.size,mtime:st.mtimeMs,exact:!!expected&&name===expected,
        rank:expected&&name===expected?2:stem.length>2&&(title.includes(stem)||expected.includes(stem))?1:0};
    }));
    return files.filter(f=>f.size>0).sort((a,b)=>b.rank-a.rank||b.mtime-a.mtime);
  }
  async scan() {
    try {
      const files=await this.candidates();if(!this.alive)return;
      this.list.empty();this.list.createEl('h4',{text:'匹配优先，其次最近下载'});
      for(const f of files.slice(0,8)) {
        const b=this.list.createEl('button',{text:(f.rank?'推荐 · ':'')+f.name});
        b.style.cssText='display:block;width:100%;text-align:left;margin:6px 0;overflow:hidden;text-overflow:ellipsis';
        b.onclick=()=>this.attach(f.path);
      }
      if(!files.length)this.list.createEl('p',{text:'目录中还没有文件。'});
    }catch(e){this.status.setText('无法读取下载目录：'+e.message);}
  }
  async attach(full) {
    if(this.busy)return;
    if(!full){this.status.setText('无法取得文件路径，请用文件选择器重新选择。');return;}
    this.stop();this.busy=true;const item=this.item,doc=this.selected();
    this.status.setText('正在挂载并提取正文…');
    try {
      const result=await this.plugin.attachFile(item.id,full,doc.doc_id);
      const current=JSON.parse(await this.app.vault.adapter.read(this.plugin.lbPath('_archive/catalog-data.json')));
      const fresh=current.items.find(x=>x.id===item.id);if(fresh)Object.assign(item,fresh);
      this.fillDocs();if(this.refresh)await this.refresh(current);
      this.status.setText(result.warning||((item.attachment_missing||0)>0?'文件已保存，这篇还有附件待补。':'附件已保存，正文已加入搜索。可以关闭下载网页。'));
      new Notice(this.status.textContent,8000);
    }catch(e){this.status.setText('挂载失败：'+e.message);}
    finally{this.busy=false;}
  }
  async waitDownload() {
    if(this.busy)return;
    this.stop();
    const att=this.selected(),url=att.url||this.item.url;
    if(!/^https?:\/\//.test(url||'')){this.status.setText('这篇没有可打开的原网页，请拖入文件。');return;}
    try {
      const before=await this.candidates();this.before=new Map(before.map(f=>[f.path,`${f.size}:${f.mtime}`]));
      await electron.shell.openExternal(url);
      this.deadline=Date.now()+this.plugin.settings.downloads.waitMinutes*60000;
      this.status.setText('已打开本地浏览器。请在网页点击下载；等待同名文件完成后自动挂载。可随时停止。');
      this.previous=new Map();
      const tick=async()=>{
        if(!this.alive||!this.deadline)return;
        if(Date.now()>this.deadline){this.stop();this.status.setText('等待超时，没有找到同名完整文件。网页标签可以关闭；若文件名不同，请刷新推荐或拖入文件。');return;}
        try {
          const files=await this.candidates();
          if(!this.alive||!this.deadline)return;
          for(const f of files) {
            const sig=`${f.size}:${f.mtime}`;
            if(f.exact&&this.before.get(f.path)!==sig&&this.previous.get(f.path)===sig){await this.attach(f.path);return;}
          }
          this.previous=new Map(files.map(f=>[f.path,`${f.size}:${f.mtime}`]));
          this.timer=setTimeout(tick,2000);
        }catch(e){this.stop();this.status.setText('等待下载失败：'+e.message+'。可关闭网页后手动拖入文件。');}
      };
      this.timer=setTimeout(tick,2000);
    }catch(e){this.status.setText('无法开始下载：'+e.message);}
  }
  stop(){clearTimeout(this.timer);this.deadline=0;}
  onClose(){this.alive=false;this.stop();}
}

class CategoriesModal extends Modal {
  constructor(plugin,cats,selected,refresh){super(plugin.app);this.plugin=plugin;this.cats=JSON.parse(JSON.stringify(cats));this.selected=selected;this.refresh=refresh;this.hidden=new Set(plugin.settings.hiddenCats);}
  onOpen(){this.draw();}
  draw(){
    const el=this.contentEl;el.empty();el.createEl('h2',{text:'目录标签'});
    el.createEl('p',{text:'关联标签用逗号分隔。隐藏只影响目录；增减关联标签不会改写笔记。'});
    this.cats.forEach((cat,i)=>{
      const row=el.createEl('div');row.style.cssText='display:flex;gap:6px;flex-wrap:wrap;margin:10px 0';
      const name=row.createEl('input');name.value=cat.name;name.style.width='110px';name.oninput=()=>{if(this.hidden.delete(cat.name))this.hidden.add(name.value);cat.name=name.value;};
      const tags=row.createEl('input');tags.value=cat.keywords.join(', ');tags.style.cssText='flex:1;min-width:160px';tags.placeholder='关联标签';tags.oninput=()=>cat.keywords=tags.value.split(/[,，、]/).map(x=>x.trim()).filter(Boolean);
      const hide=row.createEl('input');hide.type='checkbox';hide.checked=this.hidden.has(cat.name);row.createEl('span',{text:'隐藏'});hide.onchange=()=>hide.checked?this.hidden.add(cat.name):this.hidden.delete(cat.name);
      row.createEl('button',{text:'↑'}).onclick=()=>{if(i){[this.cats[i-1],this.cats[i]]=[this.cats[i],this.cats[i-1]];this.draw();}};
      row.createEl('button',{text:'↓'}).onclick=()=>{if(i<this.cats.length-1){[this.cats[i+1],this.cats[i]]=[this.cats[i],this.cats[i+1]];this.draw();}};
      row.createEl('button',{text:'删除'}).onclick=()=>{this.cats.splice(i,1);this.draw();};
      if(cat.name===this.selected)setTimeout(()=>tags.focus(),0);
    });
    el.createEl('button',{text:'增加大类'}).onclick=()=>{this.cats.push({name:'新大类',keywords:[]});this.draw();};
    const save=el.createEl('button',{text:'保存',cls:'mod-cta'});
    save.onclick=async()=>{
      save.disabled=true;
      try {
        this.plugin.settings.catalogCats=this.cats.filter(c=>c.name.trim());
        this.plugin.settings.hiddenCats=[...this.hidden];await this.plugin.saveSettings();
        const r=await this.plugin.spawnCapture(['-m','link_brain','catalog']);
        if(r.code!==0)throw Error(r.err||r.out);
        if(this.refresh)await this.refresh(JSON.parse(await this.app.vault.adapter.read(this.plugin.lbPath('_archive/catalog-data.json'))));
        this.close();
      }catch(e){new Notice('保存失败：'+e.message);save.disabled=false;}
    };
  }
}

return {AttachmentModal,CategoriesModal,cleanName};
};

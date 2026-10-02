const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const context={module:{exports:{}},process,setTimeout,clearTimeout,require:n=>n==='obsidian'?{Plugin:class{},PluginSettingTab:class{},Modal:class{}}:require(n)};
vm.createContext(context);vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8'),context);
(async()=>{
 const p=new context.module.exports();p.lbRoot='知识库【小红书】';
 const leaves=[],splits=[],opened=[];
 const owner={id:'owner',view:{containerEl:{contains:()=>true}}};leaves.push(owner);
 p.app={vault:{getAbstractFileByPath:path=>({path})},workspace:{getLeavesOfType:()=>[owner],getMostRecentLeaf:()=>owner,getLeafById:id=>leaves.find(l=>l.id===id),setActiveLeaf:l=>assert.equal(l,owner),createLeafBySplit:(base,direction)=>{
  const leaf={id:String(leaves.length),openFile:async(file,opts)=>opened.push({file,opts}),view:{containerEl:{classList:{add:()=>{}}}}};leaves.push(leaf);splits.push([base.id,direction]);return leaf;
 }}};
 await p.openArchiveSource('Web/a.md',{});await p.openArchiveSource('Web/b.md',{});
 assert.equal(splits.length,1);assert.equal(splits[0][1],'vertical');assert.equal(opened[1].file.path,'知识库【小红书】/Web/b.md');assert.equal(opened[1].opts.active,false);
 await p.openArchiveSource('Web/c.md',{},true);await p.openArchiveSource('Web/d.md',{},true);
 assert.equal(splits.length,2);assert.equal(splits[1][1],'horizontal');assert.equal(splits[1][0],'1');
 leaves.pop();await p.openArchiveSource('Web/e.md',{},true);assert.equal(splits.length,3);
 // 第 2 批：明确的「退出对照」「收起来源」；状态给页面画来源条
 for(const l of leaves)l.detach=function(){const i=leaves.indexOf(this);if(i>=0)leaves.splice(i,1);};
 assert.deepEqual({...p.archiveSourceState({})},{reader:true,compare:true});
 p.closeArchiveCompare({});
 assert.deepEqual({...p.archiveSourceState({})},{reader:true,compare:false});
 assert.equal(leaves.length,2,'只关了下方对照格');
 await p.openArchiveSource('Web/f.md',{});assert.equal(splits.length,3,'单篇照旧复用右侧来源窗格，不新开');
 p.closeArchiveSources({});
 assert.deepEqual({...p.archiveSourceState({})},{reader:false,compare:false});
 assert.equal(leaves.length,1,'右侧全关，只剩问答页');
 // 右侧没有来源时点「加入对照」：放进来源窗格（右侧），不往下拆
 const before=splits.length;await p.openArchiveSource('Web/g.md',{},true);
 assert.equal(splits.length,before+1);assert.equal(splits.at(-1)[1],'vertical');
 assert.deepEqual({...p.archiveSourceState({})},{reader:true,compare:false});
 console.log('PASS reader: mounted path, right split reuse, stacked compare reuse, recreate closed pane, preserve question focus, close compare / close all, state for source bar');
})().catch(e=>{console.error(e);process.exitCode=1;});

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
 console.log('PASS reader: mounted path, right split reuse, stacked compare reuse, recreate closed pane, preserve question focus');
})().catch(e=>{console.error(e);process.exitCode=1;});

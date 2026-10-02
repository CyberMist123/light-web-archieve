const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),{EventEmitter}=require('events');
let command,opened=[];
const context={module:{exports:{}},process,Buffer,setTimeout,clearTimeout,require:n=>{
 if(n==='obsidian')return {Plugin:class{},PluginSettingTab:class{},Modal:class{},Notice:class{}};
 if(n==='electron')return {shell:{openPath:async p=>{opened.push(p);return '';}}};
 if(n==='child_process')return {spawn:(exe,args)=>{command={exe,args};const child=new EventEmitter();child.stderr=new EventEmitter();setTimeout(()=>child.emit('close',0),0);return child;}};
 return require(n);
}};
vm.createContext(context);vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8'),context);
(async()=>{
 const plugin=new context.module.exports();
 await plugin.copyFileBundle("D:\\资料\\O'Brien.zip");
 const script=Buffer.from(command.args.at(-1),'base64').toString('utf16le');assert.ok(command.args.includes('-STA'));assert.ok(script.includes('SetFileDropList'));assert.ok(script.includes("O''Brien.zip"));
 await plugin.openArchiveMedia({attachment_files:[{name:'资料.pdf',file:'D:/资料.pdf',downloaded:true}]},'file',{});assert.equal(opened[0],'D:/资料.pdf');
 // 合成一个最小对象目录（测试不碰真库，CONVENTIONS §7.5）：meta.json → raw/v0001/manifest.json → 视频文件
 const path=require('path'),os=require('os');
 const vault=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'lb-media-')),'vault');
 const obj=path.join(vault,'_archive','xiaohongshu','n1'),raw=path.join(obj,'raw','v0001');
 fs.mkdirSync(path.join(raw,'assets'),{recursive:true});fs.mkdirSync(path.join(obj,'derived'),{recursive:true});
 fs.writeFileSync(path.join(obj,'meta.json'),JSON.stringify({current_version:1}));
 fs.writeFileSync(path.join(raw,'manifest.json'),JSON.stringify({media:[{role:'image',file:'assets/a.webp',download_status:'ok'},{role:'video',file:'assets/v.mp4',download_status:'ok'}]}));
 fs.writeFileSync(path.join(raw,'assets','v.mp4'),'');
 plugin.lbRoot='';plugin.app={vault:{adapter:{getBasePath:()=>vault}}};
 const video={kind:'video',agent_md:'_archive/xiaohongshu/n1/derived/agent.md'};
 await plugin.openArchiveMedia(video,'video',{});assert.ok(fs.existsSync(opened[1]));assert.ok(opened[1].endsWith('.mp4'));fs.rmSync(path.dirname(vault),{recursive:true,force:true});
 console.log('PASS file/video local target selection and Windows file-drop clipboard command; external apps and actual clipboard not modified');
})().catch(e=>{console.error(e);process.exit(1)});

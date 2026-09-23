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
 plugin.lbRoot='';plugin.app={vault:{adapter:{getBasePath:()=>require('path').resolve('vault')}}};
 const data=JSON.parse(fs.readFileSync('vault/_archive/catalog-data.json','utf8'));const video=data.items.find(x=>x.kind==='video');
 await plugin.openArchiveMedia(video,'video',{});assert.ok(fs.existsSync(opened[1]));assert.ok(opened[1].endsWith('.mp4'));
 console.log('PASS file/video local target selection and Windows file-drop clipboard command; external apps and actual clipboard not modified');
})().catch(e=>{console.error(e);process.exit(1)});

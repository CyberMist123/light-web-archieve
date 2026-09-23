const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),{EventEmitter}=require('events');
const children=[];
function spawn(){const c=new EventEmitter();c.stdout=new EventEmitter();c.stdout.setEncoding=()=>{};c.stderr=new EventEmitter();c.stdin=new EventEmitter();c.stdin.write=s=>{c.last=JSON.parse(s);};c.kill=()=>c.emit('close');children.push(c);return c;}
const context={module:{exports:{}},process,setTimeout,clearTimeout,require:n=>n==='obsidian'?{Plugin:class{},PluginSettingTab:class{},Modal:class{}}:n==='child_process'?{spawn}:require(n)};
vm.createContext(context);vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8'),context);
(async()=>{
 const p=new context.module.exports();p.repoRoot=process.cwd();const chunks=[];
 const a=p.requestAnswer({question:'a'},s=>chunks.push(s));const c=children[0];
 c.stdout.emit('data','{"id":"1","type":"del');c.stdout.emit('data','ta","text":"字"}\n{"id":"1","type":"result","result":{"status":"ok"}}\n');
 assert.equal((await a).status,'ok');assert.deepEqual(chunks,['字']);
 const b=p.requestAnswer({question:'b'});const rejected=assert.rejects(b,/断开/);c.emit('close');await rejected;assert.equal(children.length,2);
 const d=p.requestAnswer({question:'c'});children[1].stdout.emit('data',JSON.stringify({id:children[1].last.id,type:'result',result:{status:'ok'}})+'\n');assert.equal((await d).status,'ok');
 p.onunload();assert.equal(children.length,2);assert.equal(p.answerPending.size,0);
 console.log('PASS worker: chunked JSON, stream dispatch, reuse, crash rejection/restart, unload cleanup');
})().catch(e=>{console.error(e);process.exitCode=1;});

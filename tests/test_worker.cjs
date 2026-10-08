const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),{EventEmitter}=require('events');
const children=[];
function spawn(){const c=new EventEmitter();c.stdout=new EventEmitter();c.stdout.setEncoding=()=>{};c.stderr=new EventEmitter();c.stdin=new EventEmitter();c.stdin.write=s=>{c.last=JSON.parse(s);};c.kill=()=>c.emit('close');children.push(c);return c;}
const notices=[];
class Notice{constructor(m){notices.push(String(m));}}
const context={module:{exports:{}},process,setTimeout,clearTimeout,require:n=>n==='obsidian'?{Plugin:class{},PluginSettingTab:class{},Modal:class{},Notice}:n==='child_process'?{spawn}:require(n)};
vm.createContext(context);vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8'),context);
(async()=>{
 const p=new context.module.exports();p.repoRoot=process.cwd();const chunks=[];const killed=[];
 // §6.2：worker 一律经 killTree 结束（连同它起的 claude / codex），这里记下调用、再让假 worker 关掉
 p.killTree=async pid=>{killed.push(pid);return [pid];};
 const a=p.requestAnswer({question:'a'},s=>chunks.push(s));const c=children[0];
 c.stdout.emit('data','{"id":"1","type":"del');c.stdout.emit('data','ta","text":"字"}\n{"id":"1","type":"result","result":{"status":"ok"}}\n');
 assert.equal((await a).status,'ok');assert.deepEqual(chunks,['字']);
 const b=p.requestAnswer({question:'b'});const rejected=assert.rejects(b,/断开/);c.emit('close');await rejected;assert.equal(children.length,2);
 const d=p.requestAnswer({question:'c'});children[1].stdout.emit('data',JSON.stringify({id:children[1].last.id,type:'result',result:{status:'ok'}})+'\n');assert.equal((await d).status,'ok');
 children[1].pid=4242;p.onunload();await new Promise(r=>setTimeout(r,0));assert.deepEqual(killed,[4242]);assert.equal(children.length,2);assert.equal(p.answerPending.size,0);
 console.log('PASS worker: chunked JSON, stream dispatch, reuse, crash rejection/restart, unload cleanup via killTree');

 // ── 批次 D · L2 ──
 children.length=0;
 const q=new context.module.exports();q.repoRoot=process.cwd();q.killTree=async()=>[];
 let now=1_000_000;q.now=()=>now;
 // A13：第一问（新起 worker）先报「正在启动问答」；4 秒后再问不报
 const phases=[];
 const r1=q.requestAnswer({question:'x'},null,t=>phases.push(t));
 assert.deepEqual(phases,['正在启动问答']);
 const w=children[0];w.stdout.emit('data',JSON.stringify({id:w.last.id,type:'result',result:{status:'ok'}})+'\n');await r1;
 now+=5000;phases.length=0;
 const r2=q.requestAnswer({question:'y'},null,t=>phases.push(t));
 assert.deepEqual(phases,[]);
 w.stdout.emit('data',JSON.stringify({id:w.last.id,type:'result',result:{status:'ok'}})+'\n');await r2;
 // A5：崩溃前 stderr 有堆栈 → reject 带「断开」和最后一行，kind=crash
 const r3=q.requestAnswer({question:'z'});
 w.stderr.emit('data','Traceback (most recent call last):\n  File "x"\nValueError: x\n');
 const crashed=r3.then(()=>null,e=>e);w.emit('close');const e3=await crashed;
 assert.ok(/断开/.test(e3.message)&&e3.message.includes('ValueError: x'),e3.message);assert.equal(e3.kind,'crash');
 // answerArchive：not_configured（带 2 条来源）→ kind=config + payload；AUTH → api + code
 const reply=payload=>{const ww=children.at(-1);ww.stdout.emit('data',JSON.stringify({id:ww.last.id,type:'result',result:payload})+'\n');};
 let pr=q.answerArchive({question:'问'});await new Promise(r=>setTimeout(r,0));
 reply({status:'error',error_kind:'not_configured',code:'SKIPPED.NOT_CONFIGURED',error:'没填接口地址',markdown:'问答模型还没配好',sources:[{id:'a'},{id:'b'}]});
 let e=await pr.then(()=>null,x=>x);
 assert.equal(e.kind,'config');assert.equal(e.payload.sources.length,2);assert.equal(e.message,'问答模型还没配好','message 不变（设置页照旧显示）');
 pr=q.answerArchive({question:'问'});await new Promise(r=>setTimeout(r,0));
 reply({status:'error',error_kind:'api',code:'NEEDS_HUMAN.AUTH_FAILED',error:'401',markdown:'AI 回答失败：401'});
 e=await pr.then(()=>null,x=>x);assert.equal(e.kind,'api');assert.equal(e.code,'NEEDS_HUMAN.AUTH_FAILED');assert.equal(e.detail,'401');
 pr=q.answerArchive({question:'问'});await new Promise(r=>setTimeout(r,0));
 reply({status:'error',error_kind:'crash',error:'索引坏了',markdown:'问答出错了：RuntimeError：索引坏了'});
 e=await pr.then(()=>null,x=>x);assert.equal(e.kind,'crash');
 // warmAnswerWorker：没有 worker 才起一次，再调不重复起
 const n0=children.length;q.answerWorker=null;
 assert.equal(q.warmAnswerWorker(),true);assert.equal(children.length,n0+1);
 assert.equal(q.warmAnswerWorker(),false);assert.equal(children.length,n0+1);
 q.unloading=true;q.answerWorker=null;assert.equal(q.warmAnswerWorker(),false);
 console.log('PASS worker L2: cold-start phase only on spawn / <4s, crash error carries stderr tail + kind, answerArchive kinds config/api/crash with payload, warmAnswerWorker once');

 // N11 askAboutNote：没有 item_id → Notice + false；有 → pendingArchiveScope + 打开问收藏 + ask-pending
 const fm={'LB/Web/a.md':{link_brain:{item_id:'xhs-1'},title:'番茄炒蛋'}};
 const triggered=[],opened=[];
 const s=new context.module.exports();s.lbRoot='LB';
 s.app={metadataCache:{getFileCache:f=>fm[f.path]?{frontmatter:fm[f.path]}:null},workspace:{trigger:n=>triggered.push(n),getActiveFile:()=>null}};
 s.openLibraryPage=async role=>{opened.push(role);};
 assert.equal(await s.askAboutNote({path:'LB/Web/plain.md',basename:'plain'}),false);
 assert.ok(notices.some(m=>m.includes('这篇不是收藏笔记')));assert.deepEqual(opened,[]);
 assert.equal(await s.askAboutNote({path:'LB/Web/a.md',basename:'a'}),true);
 assert.deepEqual(JSON.parse(JSON.stringify({...s.pendingArchiveScope,at:0})),{ids:['xhs-1'],title:'番茄炒蛋',note:'Web/a.md',at:0});
 assert.deepEqual(opened,['chat']);assert.deepEqual(triggered,['link-brain:ask-pending']);
 console.log('PASS worker L2: askAboutNote sets pendingArchiveScope, opens chat page, triggers ask-pending; non-archive note refused');
})().catch(e=>{console.error(e);process.exitCode=1;});

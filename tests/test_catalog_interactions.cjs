const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const score = new Function(fs.readFileSync('link_brain/assets/catalog-search.js','utf8')+';return score')();
const item = {title:'记忆管理框架',tags:['AI'],pinyin:'jiyiguanlikuangjia',summary:''};
for(const q of ['jiyi','jiy','jiyu','记忆框架','#ai','jiyi guanli']) assert.ok(score(item,q)>0,q);
for(const q of ['香蕉','#食谱','不存在的关键词']) assert.equal(score(item,q),0,q);
const obsidianMock={Plugin:class{},Modal:class{},Notice:class{},TFile:class{},PluginSettingTab:class{constructor(app,plugin){this.app=app;this.plugin=plugin;}},Setting:class{},requestUrl:async()=>({}),MarkdownRenderer:{render:async()=>{}}};
const context={module:{exports:{}},URL,require:name=>name==='obsidian'?obsidianMock:require(name)};
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8')+';module.exports.cleanLinks=cleanLinks;module.exports.parseCatsText=parseCatsText;module.exports.serializeCats=serializeCats;',context);
const Plugin=context.module.exports;
const links=Plugin.cleanLinks('分享：https://www.xiaohongshu.com/explore/abc?xsec_token=keep&share_from=test，重复 https://www.xiaohongshu.com/explore/abc?xsec_token=keep https://xiaohongshu.com.evil.test/a https://xhslink.com/a/test。');
assert.equal(links.length,2);
assert.equal(links[0],'https://www.xiaohongshu.com/explore/abc?xsec_token=keep');
assert.equal(links[1],'https://xhslink.com/a/test');
// rednote.com 现在也认（她的分享链接大多是这个域）；分享垃圾参数清掉、只留 xsec_token/source
const rn=Plugin.cleanLinks('https://www.rednote.com/discovery/item/6aa?xsec_token=T1&source=web&xhsshare=pc&shareRedId=x&xsec_source=pc_feed');
assert.equal(rn.length,1);
assert.ok(rn[0].includes('rednote.com/discovery/item/6aa'));
assert.ok(rn[0].includes('xsec_token=T1')&&rn[0].includes('xsec_source=pc_feed'));
assert.ok(!rn[0].includes('source=web')&&!rn[0].includes('xhsshare')&&!rn[0].includes('shareRedId'));
// 大类文本 <-> 数组
const cats=Plugin.parseCatsText('人机恋: 人机恋, AI伴侣\n吃的：菜, 饭');
assert.equal(cats.length,2);assert.equal(cats[0].name,'人机恋');assert.equal(cats[0].keywords.join(','),'人机恋,ai伴侣');
assert.equal(cats[1].keywords.join(','),'菜,饭');  // 中文冒号也认
assert.equal(Plugin.serializeCats(cats),'人机恋: 人机恋, ai伴侣\n吃的: 菜, 饭');
(async()=>{
  const plugin=new Plugin();const calls=[];
  plugin.run=async args=>{calls.push(args);return {stdout:JSON.stringify({items:[{status:'hit',visible_note:'Web/Xiaohongshu/已归档.md'}]})};};
  let lastDone=-1,lastTotal=-1;
  const results=await plugin.importText('https://xhslink.com/a/test https://xhslink.com/a/test',()=>{},(d,t)=>{lastDone=d;lastTotal=t;});
  assert.equal(results.length,1);assert.equal(results[0].note,'已归档');assert.equal(calls.length,2);
  assert.equal(calls[1][2],'catalog');assert.equal(plugin.importing,false);
  assert.equal(lastDone,1);assert.equal(lastTotal,1);  // 进度回调到位
  // expandAndCleanLinks：解析 Python clean 的 JSON
  plugin.spawnCapture=async args=>{assert.equal(args[2],'clean');return {out:JSON.stringify({count:1,urls:[{clean:'https://x/1',has_token:true}]}),err:''};};
  const cl=await plugin.expandAndCleanLinks('some text');assert.equal(cl.length,1);assert.equal(cl[0].clean,'https://x/1');
  // deleteItems：spawn delete <id...>、解析结果
  plugin.spawnCapture=async args=>{assert.equal(args[2],'delete');assert.equal(args.slice(3).join(','),'id1,id2');return {out:JSON.stringify({deleted:2,results:[{item_id:'id1',status:'deleted'},{item_id:'id2',status:'deleted'}]}),err:''};};
  const del=await plugin.deleteItems(['id1','id2','']);assert.equal(del.deleted,2);
  const empty=await plugin.deleteItems([]);assert.equal(empty.deleted,0);assert.equal(empty.results.length,0);  // 空不 spawn
  // 目录页「+」菜单按钮：旧插件实例缺 openPlusMenu 时 disable/enable 恢复后再打开
  const view=fs.readFileSync('link_brain/assets/catalog-view.js','utf8');
  const handler=view.slice(view.indexOf('importButton.onclick=')+'importButton.onclick='.length,view.indexOf('\n// 大类筛选条'));
  let opened=0,reloaded=0,status='';const button={disabled:false};
  const app={plugins:{plugins:{'link-brain-actions':{}},disablePlugin:async()=>{},enablePlugin:async()=>{reloaded++;app.plugins.plugins['link-brain-actions']={openPlusMenu:()=>opened++};}}};
  const click=new Function('app','importButton','importStatus','return '+handler)(app,button,{setText:s=>status=s});
  await click({preventDefault(){},stopPropagation(){}});
  assert.equal(reloaded,1);assert.equal(opened,1);assert.equal(button.disabled,false);
  // answerArchive 薄壳：解析后端 `ask` 的 JSON、非 ok 抛错
  const p2=new Plugin();
  p2.spawnCapture=async args=>{assert.equal(args[2],'ask');assert.equal(args[3],'AI 做梦');
    return {code:0,out:'log line\n'+JSON.stringify({status:'ok',markdown:'答案',matches:3,materials:2,intent:'qa',model_called:true})+'\n',err:''};};
  const ans=await p2.answerArchive({question:'  AI 做梦  '});
  assert.equal(ans.markdown,'答案');assert.equal(ans.matches,3);assert.equal(ans.intent,'qa');
  p2.spawnCapture=async()=>({code:1,out:JSON.stringify({status:'error',markdown:'没内容'}),err:''});
  await assert.rejects(p2.answerArchive({question:'x'}),/没内容/);
  await assert.rejects(p2.answerArchive({question:'  '}),/问题是空的/);
  // 设置默认值合到位（未存过 data 时用内置默认）
  const p3=new Plugin();p3.app={vault:{adapter:{getBasePath:()=>'/repo/vault'}}};p3.loadData=async()=>null;
  p3.addSettingTab=()=>{};p3.addCommand=()=>{};p3.addRibbonIcon=()=>{};
  await p3.onload();
  assert.equal(p3.settings.textAI.mode,'media');assert.equal(p3.settings.retrieval.topK,8);
  assert.ok(p3.settings.prompts.answer.length>10);
  console.log('PASS: fuzzy/pinyin/tag search, URL cleaning, deduplication, import results and rebuild, answerArchive, settings defaults');
})().catch(e=>{console.error(e);process.exitCode=1;});

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const score = new Function(fs.readFileSync('link_brain/assets/catalog-search.js','utf8')+';return score')();
// 1002 第 1 批：catalog.py 把拼音写成空格分隔的整音节；拼音只认整音节（jiy / jiyu 这种半个音节、差一个字母的不再算）
const item = {title:'记忆管理框架',tags:['AI'],pinyin:'ji yi guan li kuang jia',summary:''};
for(const q of ['jiyi','记忆框架','#ai','jiyi guanli','guanlikuang']) assert.ok(score(item,q)>0,q);
for(const q of ['香蕉','#食谱','不存在的关键词','jiy','jiyu','yig']) assert.equal(score(item,q),0,q);
const obsidianMock={Plugin:class{},Modal:class{},Notice:class{},TFile:class{},PluginSettingTab:class{constructor(app,plugin){this.app=app;this.plugin=plugin;}},Setting:class{},requestUrl:async()=>({}),MarkdownRenderer:{render:async()=>{}}};
// node 测试不许起真进程（CONVENTIONS §7.5）：child_process 换成一碰就炸的桩
const context={module:{exports:{}},URL,require:name=>name==='obsidian'?obsidianMock:name==='child_process'?{spawn(){throw new Error('测试里不许 spawn 真进程');}}:require(name)};
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
  const {results}=await plugin.importText('https://xhslink.com/a/test https://xhslink.com/a/test',()=>{},(d,t)=>{lastDone=d;lastTotal=t;});
  assert.equal(results.length,1);assert.equal(results[0].note,'已归档');assert.equal(calls.length,2);
  assert.equal(calls[1][2],'catalog');assert.equal(plugin.importing,false);
  assert.equal(lastDone,1);assert.equal(lastTotal,1);  // 进度回调到位
  // expandAndCleanLinks：解析 Python clean 的 JSON
  const res=out=>({code:0,json:JSON.parse(out),out,err:'',all:out,timedOut:false});
  plugin.spawnPy=async args=>{assert.equal(args[2],'clean');return res(JSON.stringify({count:1,urls:[{clean:'https://x/1',has_token:true}]}));};
  const cl=await plugin.expandAndCleanLinks('some text');assert.equal(cl.length,1);assert.equal(cl[0].clean,'https://x/1');
  // deleteItems：spawn delete <id...>、解析结果
  plugin.spawnPy=async args=>{assert.equal(args[2],'delete');assert.equal(args.slice(3).join(','),'id1,id2');return res(JSON.stringify({deleted:2,results:[{item_id:'id1',status:'deleted'},{item_id:'id2',status:'deleted'}]}));};
  const del=await plugin.deleteItems(['id1','id2','']);assert.equal(del.deleted,2);
  const empty=await plugin.deleteItems([]);assert.equal(empty.deleted,0);assert.equal(empty.results.length,0);  // 空不 spawn
  // 目录页「+」菜单按钮：旧插件实例缺 openPlusMenu 时 disable/enable 恢复后再打开
  const view=fs.readFileSync('link_brain/assets/catalog-view.js','utf8');
  const mark='importButton.onclick = ';const handler=view.slice(view.indexOf(mark)+mark.length,view.indexOf('\n// 大类筛选条')).trim().replace(/;$/,'');
  let opened=0,reloaded=0,status='';const button={disabled:false};
  const app={plugins:{plugins:{'link-brain-actions':{}},disablePlugin:async()=>{},enablePlugin:async()=>{reloaded++;app.plugins.plugins['link-brain-actions']={openPlusMenu:()=>opened++};}}};
  const lib=fs.readFileSync('link_brain/assets/lb-page-lib.js','utf8');
  const LB=new Function('dv','app',lib+';return lbPageLib(dv,app,"catalog")')({container:{},current:()=>({file:{folder:''}})},app);
  const click=new Function('app','importButton','LB','return '+handler)(app,button,LB);
  await click({preventDefault(){},stopPropagation(){}});
  assert.equal(reloaded,1);assert.equal(opened,1);assert.equal(button.disabled,false);
  // answerArchive 薄壳：解析后端 `ask` 的 JSON、非 ok 抛错
  const p2=new Plugin();
  p2.requestAnswer=async request=>{assert.equal(request.question,'AI 做梦');
    return {status:'ok',markdown:'答案',matches:3,materials:2,intent:'qa',model_called:true};};
  const ans=await p2.answerArchive({question:'  AI 做梦  '});
  assert.equal(ans.markdown,'答案');assert.equal(ans.matches,3);assert.equal(ans.intent,'qa');
  p2.requestAnswer=async()=>({status:'error',markdown:'没内容'});
  await assert.rejects(p2.answerArchive({question:'x'}),/没内容/);
  await assert.rejects(p2.answerArchive({question:'  '}),/问题是空的/);
  // 设置默认值合到位（未存过 data 时用内置默认）
  const p3=new Plugin();p3.app={vault:{adapter:{getBasePath:()=>'/repo/vault'}},workspace:{onLayoutReady:()=>{}}};p3.loadData=async()=>null;
  p3.addSettingTab=()=>{};p3.addCommand=()=>{};p3.addRibbonIcon=()=>{};
  p3.addStatusBarItem=()=>({setText(){}});p3.readSyncFiles=async()=>({});
  await p3.onload();
  assert.equal(p3.settings.textAI.mode,'http');assert.equal(p3.settings.asrAI.mode,'capswriter');assert.equal(p3.settings.summaryAI.mode,'inherit');assert.equal(p3.settings.retrieval.topK,8);
  assert.ok(p3.settings.prompts.answer.length>10);
  console.log('PASS: fuzzy/pinyin/tag search, URL cleaning, deduplication, import results and rebuild, answerArchive, settings defaults');
})().catch(e=>{console.error(e);process.exitCode=1;});

// ── Lot E 星标主题 chip：用极简假 DOM 真跑整段目录页脚本（search + view） ──
// 断言：无主题时不建 .lbc-topics（DOM 与没有这功能时一致）；有主题时 chip 出现、点击过滤、再点取消、
// 与「全部」/大类联动；全页不设 aria-label（Obsidian 会渲染成悬浮框，Owner 不要）。
// 批次 D：改用共享假 DOM（tests/_fakedom.cjs）；页面挂在 host 上，查 A.section
const { makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');
async function runCatalogPage(data,{view=fs.readFileSync('link_brain/assets/catalog-view.js','utf8'),syncState={},summary=null,onAccountOpen=()=>{}}={}){
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const files={'_archive/catalog-data.json':JSON.stringify(data),'_archive/sync-status.json':JSON.stringify(syncState)};
  if(summary)files['_archive/problems-summary.json']=JSON.stringify(summary);
  const plugin={settings:{hiddenCats:[]},openAccountStatus:onAccountOpen,openProblems:onAccountOpen,openAttachments(){},openCategories(){},openLibraryPage(){}};
  const {app}=makeApp({files,plugin});
  const dom=makeDom();
  const search=fs.readFileSync('link_brain/assets/lb-page-lib.js','utf8')+'\n'+fs.readFileSync('link_brain/assets/catalog-search.js','utf8');
  const A=dataviewBlock({dom,app,code:search+'\n'+view});
  await A.run();
  const root=A.section;
  const cards=()=>root.querySelectorAll('.lbc-card').map(c=>c.querySelector('.lbc-ctitle').textContent);
  const chips=()=>root.querySelectorAll('.lbc-topic');
  const cat=label=>root.querySelectorAll('.lbc-cat').find(b=>b.textContent===label);
  return {root,cards,chips,cat};
}
(async()=>{
  const base={built_at:new Date().toISOString(),pinyin_chars:{},aliases:[],cats_order:['记忆','吃的'],cats:[],items:[
    {id:'a',title:'长期记忆方案',tags:['记忆'],cats:['记忆'],topics:['AI 记忆层'],summary:'',search_text:'',attachment:'none'},
    {id:'b',title:'快手菜',tags:['菜谱'],cats:['吃的'],topics:[],summary:'',search_text:'',attachment:'none'},
    {id:'c',title:'睡前记忆整理',tags:['睡眠'],cats:['记忆'],topics:['AI 记忆层','睡眠'],summary:'',search_text:'',attachment:'none'},
  ]};
  // 无主题（旧数据没有 topics 键 / 新数据 topics:[]）：整行不建，卡片照旧
  for(const data of [{...base,items:base.items.map(({topics,...it})=>it)},{...base,topics:[]}]){
    const page=await runCatalogPage(data);
    assert.equal(page.root.querySelectorAll('.lbc-topics').length,0);
    assert.deepEqual(page.root.querySelector('.lbc-top').children.map(c=>c.className),['lbc-head','lbc-cats','lbc-selbar'],'C1：多选栏在吸顶区里（最后一个子节点）');
    assert.equal(page.cards().length,3);
  }
  // 有主题：chip 出现、★ 前缀、点击过滤、再点取消
  const page=await runCatalogPage({...base,topics:['AI 记忆层','睡眠']});
  assert.deepEqual(page.root.querySelector('.lbc-top').children.map(c=>c.className),['lbc-head','lbc-cats','lbc-topics','lbc-selbar']);
  assert.deepEqual(page.chips().map(c=>c.textContent),['★AI 记忆层','★睡眠']);
  assert.equal(page.chips()[0].querySelector('.lbc-topic-star').textContent,'★');
  page.chips()[0].onclick();
  assert.deepEqual(page.cards(),['长期记忆方案','睡前记忆整理']);
  assert.ok(page.chips()[0].classList.contains('is-active'));assert.equal(page.chips()[0].getAttribute('aria-pressed'),'true');
  assert.ok(!page.cat('全部').classList.contains('is-active'));
  assert.equal(page.root.querySelector('.lbc-count').textContent,'筛出 2 篇（共 3）');
  page.chips()[0].onclick();
  assert.equal(page.cards().length,3);assert.ok(page.cat('全部').classList.contains('is-active'));
  // 单选：切到「睡眠」只剩 c
  page.chips()[0].onclick();page.chips()[1].onclick();
  assert.deepEqual(page.cards(),['睡前记忆整理']);
  assert.ok(!page.chips()[0].classList.contains('is-active')&&page.chips()[1].classList.contains('is-active'));
  // 「全部」清掉主题
  page.cat('全部').onclick();
  assert.equal(page.cards().length,3);assert.ok(page.chips().every(c=>!c.classList.contains('is-active')));
  // 与大类叠加：吃的 ∩ AI 记忆层 = 空；记忆 ∩ AI 记忆层 = a,c
  page.cat('吃的').onclick();page.chips()[0].onclick();
  assert.equal(page.cards().length,0);
  page.cat('记忆').onclick();
  assert.deepEqual(page.cards(),['长期记忆方案','睡前记忆整理']);
  // 全页不设 aria-label
  assert.equal(page.root.querySelector('.lbc-wrap').all().filter(e=>('aria-label' in e.attrs||'title' in e.attrs)&&!e.classList.contains('lbc-updated')&&!e.classList.contains('lbc-totop')).length,0,'卡片 / 筛选条不设 aria-label、title（「更新」的 title 是她要的悬停全句）');
  // 主题名不认识的旧 activeTopic / 坏数据不炸
  const bad=await runCatalogPage({...base,topics:[null,'',42]});
  assert.equal(bad.root.querySelectorAll('.lbc-topics').length,0);
  // 第 4 批：「!」升级成问题入口——要你处理=橙色数字、其余=灰色数字、都为 0 不显示；点开 = 插件 openProblems()（问题列表）
  let opened=0;
  const reg={'NEEDS_HUMAN.NOT_LOGGED_IN':{label:'需要登录',hover:'',group:'needs_you',where:'top+card'},'NEEDS_HUMAN.CAPTCHA_REQUIRED':{label:'需要验证',hover:'',group:'needs_you',where:'top+card'}};
  const failed=await runCatalogPage({...base,state_registry:reg},{syncState:{state:'blocked',account:'xhs',code:'NOT_LOGGED_IN',updated_at:'2026-10-02T04:00:00+10:00'},summary:{updated_at:'2026-10-02T04:01:00+10:00',needs_human:1,auto:2,gave_up:1,skipped:5},onAccountOpen:()=>opened++});
  const entry=failed.root.querySelector('.lbc-problems');
  assert.equal(entry.hidden,false);
  assert.equal(entry.querySelector('.lbc-prob-need').textContent,'1');assert.equal(entry.querySelector('.lbc-prob-other').textContent,'3','自动处理中 + 已放弃，未开启不计数');
  assert.ok(entry.title.startsWith('需要登录'),entry.title);
  await entry.onclick();assert.equal(opened,1,'问题入口走插件 openProblems');
  const captcha=await runCatalogPage({...base,state_registry:reg},{syncState:{state:'blocked',account:'xhs',code:'CAPTCHA_REQUIRED'}});
  const cap=captcha.root.querySelector('.lbc-problems');
  assert.equal(cap.querySelector('.lbc-prob-need').textContent,'1','还没有 problems-summary.json 时同步卡住照样亮');assert.ok(cap.title.startsWith('需要验证'));
  const ok=await runCatalogPage(base,{syncState:{state:'ready',updated_at:'2026-09-25T04:10:00+10:00'},summary:{needs_human:0,auto:0,gave_up:0,skipped:3}});
  assert.equal(ok.root.querySelector('.lbc-problems').hidden,true,'都为 0 不显示');
  console.log('PASS: problems entry next to count (orange needs-you / gray others, hidden at 0) opens openProblems');
  console.log('PASS: topic chips (absent when no topics, filter/toggle/single-select, 全部 reset, AND with cats, no aria-label)');
})().catch(e=>{console.error(e);process.exitCode=1;});

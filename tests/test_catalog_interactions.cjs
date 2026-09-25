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
  p2.requestAnswer=async request=>{assert.equal(request.question,'AI 做梦');
    return {status:'ok',markdown:'答案',matches:3,materials:2,intent:'qa',model_called:true};};
  const ans=await p2.answerArchive({question:'  AI 做梦  '});
  assert.equal(ans.markdown,'答案');assert.equal(ans.matches,3);assert.equal(ans.intent,'qa');
  p2.requestAnswer=async()=>({status:'error',markdown:'没内容'});
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

// ── Lot E 星标主题 chip：用极简假 DOM 真跑整段目录页脚本（search + view） ──
// 断言：无主题时不建 .lbc-topics（DOM 与没有这功能时一致）；有主题时 chip 出现、点击过滤、再点取消、
// 与「全部」/大类联动；全页不设 aria-label（Obsidian 会渲染成悬浮框，Owner 不要）。
function fakeDom(){
  class El{
    constructor(tag){this.tagName=String(tag).toUpperCase();this.children=[];this.parent=null;this.attrs={};this.classList=new Set();this.style={};this.hidden=false;this._text='';}
    get className(){return [...this.classList].join(' ');}
    set className(v){this.classList=new Set(String(v||'').split(/\s+/).filter(Boolean));}
    get textContent(){return this._text+this.children.map(c=>typeof c==='string'?c:c.textContent).join('');}
    set textContent(v){this.children=[];this._text=String(v);}
    createEl(tag,opts={}){const el=new El(tag);if(opts.cls)el.className=opts.cls;if(opts.text!=null)el._text=String(opts.text);for(const [k,v] of Object.entries(opts))if(!['cls','text'].includes(k))el.setAttribute(k,v);this.append(el);return el;}
    append(...nodes){for(const n of nodes){if(n instanceof El){n.parent=this;}this.children.push(n);}}
    prepend(n){if(n instanceof El)n.parent=this;this.children.unshift(n);}
    appendText(t){this.children.push(String(t));}
    empty(){this.children=[];this._text='';}
    setText(t){this.textContent=t;}
    remove(){if(this.parent){this.parent.children=this.parent.children.filter(c=>c!==this);this.parent=null;}}
    setAttribute(k,v){this.attrs[k]=String(v);}
    getAttribute(k){return this.attrs[k]??null;}
    hasClass(c){return this.classList.has(c);}
    closest(){return null;}
    matches(sel){const m=sel.match(/^([a-z]*)((?:\.[\w-]+)*)(?::not\(\.([\w-]+)\))?$/i);if(!m)return false;
      if(m[1]&&this.tagName!==m[1].toUpperCase())return false;
      for(const c of (m[2]||'').split('.').filter(Boolean))if(!this.classList.has(c))return false;
      return !(m[3]&&this.classList.has(m[3]));}
    all(){const out=[];for(const c of this.children)if(c instanceof El){out.push(c,...c.all());}return out;}
    querySelector(sel){return this.all().find(e=>e.matches(sel))||null;}
    querySelectorAll(sel){return this.all().filter(e=>e.matches(sel));}
    getBoundingClientRect(){return {width:0,height:0};}
  }
  const body=new El('body');
  const document={body,addEventListener(){},removeEventListener(){},querySelectorAll:s=>body.querySelectorAll(s),createElementNS:(ns,t)=>new El(t)};
  return {El,document};
}
async function runCatalogPage(data,{view=fs.readFileSync('link_brain/assets/catalog-view.js','utf8'),syncState={},onAccountOpen=()=>{}}={}){
  const {El,document}=fakeDom();
  const root=new El('div');const window={alert(){},confirm:()=>false};
  const app={vault:{adapter:{read:async p=>JSON.stringify(p.endsWith('sync-status.json')?syncState:data),getResourcePath:x=>x},getAbstractFileByPath:()=>null},
    plugins:{plugins:{'link-brain-actions':{settings:{hiddenCats:[]},openAccountStatus:onAccountOpen,fixFromCatalog:onAccountOpen,openAttachments(){},openCategories(){},openLibraryPage(){}}}},
    workspace:{openLinkText(){}}};
  const dv={container:root,current:()=>({file:{folder:''}}),page:()=>null};
  const search=fs.readFileSync('link_brain/assets/catalog-search.js','utf8');
  await new Function('app','dv','document','window','return (async()=>{'+search+'\n'+view+'\n})()')(app,dv,document,window);
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
    assert.deepEqual(page.root.querySelector('.lbc-top').children.map(c=>c.className),['lbc-head','lbc-cats']);
    assert.equal(page.cards().length,3);
  }
  // 有主题：chip 出现、★ 前缀、点击过滤、再点取消
  const page=await runCatalogPage({...base,topics:['AI 记忆层','睡眠']});
  assert.deepEqual(page.root.querySelector('.lbc-top').children.map(c=>c.className),['lbc-head','lbc-cats','lbc-topics']);
  assert.deepEqual(page.chips().map(c=>c.textContent),['★AI 记忆层','★睡眠']);
  assert.equal(page.chips()[0].querySelector('.lbc-topic-star').textContent,'★');
  page.chips()[0].onclick();
  assert.deepEqual(page.cards(),['长期记忆方案','睡前记忆整理']);
  assert.ok(page.chips()[0].classList.has('is-active'));assert.equal(page.chips()[0].getAttribute('aria-pressed'),'true');
  assert.ok(!page.cat('全部').classList.has('is-active'));
  assert.ok(page.root.querySelector('.lbc-sub').textContent.startsWith('2 / 3 篇'));
  page.chips()[0].onclick();
  assert.equal(page.cards().length,3);assert.ok(page.cat('全部').classList.has('is-active'));
  // 单选：切到「睡眠」只剩 c
  page.chips()[0].onclick();page.chips()[1].onclick();
  assert.deepEqual(page.cards(),['睡前记忆整理']);
  assert.ok(!page.chips()[0].classList.has('is-active')&&page.chips()[1].classList.has('is-active'));
  // 「全部」清掉主题
  page.cat('全部').onclick();
  assert.equal(page.cards().length,3);assert.ok(page.chips().every(c=>!c.classList.has('is-active')));
  // 与大类叠加：吃的 ∩ AI 记忆层 = 空；记忆 ∩ AI 记忆层 = a,c
  page.cat('吃的').onclick();page.chips()[0].onclick();
  assert.equal(page.cards().length,0);
  page.cat('记忆').onclick();
  assert.deepEqual(page.cards(),['长期记忆方案','睡前记忆整理']);
  // 全页不设 aria-label
  assert.equal(page.root.all().filter(e=>'aria-label' in e.attrs||'title' in e.attrs).length,0);
  // 主题名不认识的旧 activeTopic / 坏数据不炸
  const bad=await runCatalogPage({...base,topics:[null,'',42]});
  assert.equal(bad.root.querySelectorAll('.lbc-topics').length,0);
  let opened=0;
  const failed=await runCatalogPage(base,{syncState:{state:'blocked',account:'xhs',code:'NOT_LOGGED_IN'},onAccountOpen:()=>opened++});
  const account=failed.root.querySelector('.lbc-account-status');
  assert.equal(account.textContent,'!需要登录');assert.ok(account.classList.has('is-alert'));
  await account.onclick();assert.equal(opened,1,'「!」直接走插件的修复入口');
  const captcha=await runCatalogPage(base,{syncState:{state:'blocked',account:'xhs',code:'CAPTCHA_REQUIRED'}});
  const cap=captcha.root.querySelector('.lbc-account-status');
  assert.equal(cap.textContent,'!需要验证');assert.ok(cap.classList.has('is-warn'));
  const service=await runCatalogPage(base,{syncState:{state:'blocked',account:null}});
  assert.equal(service.root.querySelector('.lbc-account-status').textContent,'!同步暂停');
  const ok=await runCatalogPage(base,{syncState:{state:'ready',updated_at:'2026-09-25T04:10:00+10:00'}});
  assert.equal(ok.root.querySelector('.lbc-account-status').hidden,true,'同步正常时不显示');
  console.log('PASS: directory shows sync failure next to count and opens account login');
  console.log('PASS: topic chips (absent when no topics, filter/toggle/single-select, 全部 reset, AND with cats, no aria-label)');
})().catch(e=>{console.error(e);process.exitCode=1;});

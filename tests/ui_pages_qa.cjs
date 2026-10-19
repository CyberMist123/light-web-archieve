// Render the shipped dataview scripts in a browser harness; this is not native Obsidian acceptance.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const out=process.env.LWA_QA_DIR||path.join(require('os').tmpdir(),'lwa-pages');fs.mkdirSync(out,{recursive:true});
 const data=JSON.parse(fs.readFileSync('vault/_archive/catalog-data.json','utf8'));
 const covers={};for(const it of data.items){if(it.cover&&fs.existsSync(path.join('vault',it.cover)))covers[it.cover]='data:image/webp;base64,'+fs.readFileSync(path.join('vault',it.cover)).toString('base64');}
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1280,height:960}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function setup(kind,theme,prefix=''){
  const dark=theme==='dark';
  await page.setContent(`<style>:root{color-scheme:${dark?'dark':'light'};--text-normal:${dark?'#e7e7ea':'#252527'};--text-muted:${dark?'#acacb2':'#77777d'};--text-faint:${dark?'#96969e':'#8c8c93'};--background-primary:${dark?'#202022':'#fff'};--background-secondary:${dark?'#2b2b2e':'#f5f5f7'};--background-modifier-border:${dark?'#3e3e43':'#e4e4e8'};--background-modifier-hover:${dark?'#36363b':'#eeeef1'};--interactive-accent:#6b71c9;--link-color:#6b71c9;--text-error:#ce5454}body{margin:0;background:var(--background-primary);color:var(--text-normal)}button{font:inherit;cursor:pointer}textarea,input{color:var(--text-normal);box-sizing:border-box}button:disabled{cursor:wait}</style><main class="markdown-preview-view"><div id="root"></div></main>`);
  await page.evaluate(({data,covers,prefix,kind})=>{
   try{sessionStorage.clear();}catch{}window.__lbState={};/* 1015：页面状态存 sessionStorage['lb:<页>']（不可用时 window.__lbState），setContent 不清——上一轮点开的「已收藏」会被带进下一轮 */
   if(kind==='starred')data.items.forEach((it,i)=>it.starred=i<2);
   Element.prototype.createEl=function(tag,opts={}){const el=document.createElement(tag);if(opts.cls)el.className=opts.cls;if(opts.text!=null)el.textContent=opts.text;this.append(el);return el;};
   Element.prototype.empty=function(){this.replaceChildren();};/* 1015：Obsidian 的全局 createDiv / createEl / createSpan（问收藏页流式块用） */window.createEl=(tag,o={})=>{const e=document.createElement(tag);if(o.cls)e.className=o.cls;if(o.text!=null)e.textContent=o.text;return e;};window.createDiv=o=>createEl('div',o);window.createSpan=o=>createEl('span',o);Element.prototype.setText=function(t){this.textContent=t;};Element.prototype.appendText=function(t){this.append(document.createTextNode(t));};
   window.mediaOpened=[];window.bundles=[];window.opened=[];window.reads=[];window.writes=[];window.asks=[];window.menus=[];window.copied='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async s=>{window.copied=s;}}});
   const item=data.items.find(x=>x.note);
   window.app={vault:{getAbstractFileByPath:p=>p===(prefix?prefix+'/':'')+'_archive'?{}:null,adapter:{read:async p=>{reads.push(p);return p.endsWith('catalog-data.json')?JSON.stringify(data):p.endsWith('notes.json')?JSON.stringify({starred:!!data.items.find(it=>it.notes_path&&p.endsWith(it.notes_path))?.starred}):'{}';},write:async(p,s)=>writes.push(p),getBasePath:()=> 'D:/LIGHT WEB ARCHIEVE/vault',getResourcePath:p=>covers[p.slice(prefix?prefix.length+1:0)]||''},getMarkdownFiles:()=>['小红书收藏目录.md','星标收藏.md','收藏搜索.md','回收站.md'].map(n=>({path:(prefix?prefix+'/':'')+n,parent:{path:prefix||'/'}}))},metadataCache:{getFileCache:f=>({frontmatter:{'lb-page':{'小红书收藏目录.md':'catalog','星标收藏.md':'starred','收藏搜索.md':'chat','回收站.md':'trash'}[f.path.split('/').pop()]}}),getCache:()=>null},workspace:{openLinkText:(...args)=>opened.push(args)},plugins:{plugins:{'link-brain-actions':{
    settings:{hiddenCats:[]},openArchiveMedia:async(it,kind)=>mediaOpened.push(kind),openArchiveSource:(p,root,compare)=>{opened.push([(prefix?prefix+'/':'')+p,compare]);},starNote:async(id,on)=>({starred:on}),openAttachments:()=>{},openCategories:()=>{},openPlusMenu:()=>menus.push('plus'),openManageMenu:()=>menus.push('manage'),openAISettingsMenu:()=>menus.push('ai-settings'),exportArchiveBundle:async(...args)=>{bundles.push(args);return {path:'test.zip'};},
    answerArchive:async r=>{asks.push({question:r.question,history:r.history});r.onDelta('正在逐字呈现');await new Promise(resolve=>setTimeout(resolve,300));r.onDelta('收藏中的内容。');await new Promise(resolve=>setTimeout(resolve,300));return {markdown:'这段回答演示收藏问答的阅读布局。\n\n具体内容以收藏原文为依据，材料不足时会明确说明。[来源1]',sources:[{id:item.id,citation:1,title:item.title,note:item.note,excerpts:[{field:'body',text:'收藏中的内容'}]}]};},
    renderMarkdownInto:async(s,el)=>{for(const t of s.split('\n\n'))el.createEl('p',{text:t});}
   }}}};
   window.dv={container:document.querySelector('#root'),current:()=>({file:{folder:prefix}}),page:()=>null};
  },{data,covers,prefix,kind});
  let code=fs.readFileSync('link_brain/assets/lb-page-lib.js','utf8')+'\n'+fs.readFileSync('link_brain/assets/catalog-search.js','utf8')+'\n'+fs.readFileSync('link_brain/assets/'+(kind==='chat'?'chat-view.js':'catalog-view.js'),'utf8');
  if(kind==='starred')code=code.replace('const simplePage = false;','const simplePage = true;').replace('const starredPage = false;','const starredPage = true;');
  await page.evaluate(async code=>{await new Function('return (async()=>{'+code+'})()')();},code);
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>{img.loading='eager';return img.decode().catch(()=>{});}));});
 }
 for(const theme of ['light','dark']){
  for(const kind of ['catalog','chat']){
   await page.setViewportSize({width:1280,height:960});await setup(kind,theme);
   if(kind==='chat'){
    await page.locator('.lbchat-search').fill('帮我整理收藏里的相关内容');await page.locator('.lbchat-send').click();
    await page.locator('.lbchat-live').waitFor();assert.ok((await page.locator('.lbchat-live').textContent()).includes('正在逐字'));
    await page.locator('.lbchat-send:enabled').waitFor();assert.equal(await page.locator('.lbchat-src').getAttribute('open'),null);
   }
   if(kind==='catalog'){
    // 1008 18:50 她：没收藏的 ☆ 平时隐藏（opacity 0），悬停才出现；批次 D · C3：点星走 starNotes 一次批量（这里的插件桩只有 starNote → 页面先重载插件再说一句，星回滚）
    const offCard=page.locator('.lbc-card').nth(await page.locator('.lbc-card').evaluateAll(cs=>cs.findIndex(c=>!c.querySelector('.lbc-star.is-on'))));/* 1015：真库第一篇可能已收藏（已收藏常驻黄星），取第一张没收藏的 */assert.equal(await offCard.locator('.lbc-star').evaluate(e=>getComputedStyle(e).opacity),'0');await page.evaluate(()=>{app.plugins.plugins['link-brain-actions'].starNotes=async(ids,on)=>({ok:true,results:ids.map(id=>({item_id:id,status:'ok',starred:on})),catalog_patched:false});});await offCard.hover();const offStar=offCard.locator('.lbc-star');await offStar.click();assert.equal(await offStar.getAttribute('aria-pressed'),'true');
    await page.getByRole('button',{name:'视频',exact:true}).click();assert.ok(await page.locator('.lbc-card').count()>0);assert.ok(await page.locator('.lbc-card').evaluateAll(cs=>cs.every(c=>c.querySelector('.lbc-video'))),'视频筛选下每张卡都有视频角标');/* 1015：角标只是标记（点卡片进笔记页再播），不再断言点角标直接开播 */await page.getByRole('button',{name:'全部',exact:true}).click();
    assert.equal(await page.locator('.lbc-grid').evaluate(el=>getComputedStyle(el).overflowY),'visible');
    assert.ok((await page.locator('.lbc-grid').boundingBox()).height>1920,'waterfall must extend beyond the viewport');
    // 吸顶：这里用 window.scrollTo 滚整页是假阳性（真宿主滚的是 .markdown-preview-view / .cm-scroller），改由 tests/ui/catalog_host_ui.cjs 在 Obsidian 外壳里验（批次 D · C1）
    await page.locator('.lbc-card').last().scrollIntoViewIfNeeded();assert.ok((await page.locator('.lbc-card').last().boundingBox()).y<960,'last card remains reachable');await page.evaluate(()=>window.scrollTo(0,0));
   }else{
    await page.locator('.lbchat-cite').click();assert.ok((await page.evaluate(()=>opened)).length);
    await page.getByRole('button',{name:'复制',exact:true}).click();assert.ok((await page.evaluate(()=>copied)).includes('D:/LIGHT WEB ARCHIEVE/vault/Web/'));
    await page.locator('.lbchat-answer .lbchat-edit').first().click();await page.locator('.lbchat-editor').fill('我修改过的回答 [来源1]');await page.getByRole('button',{name:'保存修改',exact:true}).click();assert.ok((await page.locator('.lbchat-answer').textContent()).includes('我修改过'));
    await page.locator('.lbchat-export summary').click();await page.locator('.lbchat-export input').uncheck();await page.getByRole('button',{name:'导出资料包',exact:true}).click();assert.equal(await page.evaluate(()=>bundles[0][1]),false);assert.ok(await page.evaluate(()=>bundles[0][2].includes('来源')));await page.getByRole('button',{name:'导出资料包',exact:true}).click();assert.equal(await page.evaluate(()=>bundles.length),2);await page.getByRole('button',{name:'复制文件包',exact:true}).click();assert.equal(await page.evaluate(()=>bundles.at(-1)[3].copy),true);await page.locator('.lbchat-export summary').click();
    await page.locator('.lbchat-bookmark').click();assert.equal(await page.locator('.lbchat-bookmark').getAttribute('aria-pressed'),'true');await page.getByRole('button',{name:'已保存',exact:true}).click();assert.ok((await page.locator('.lbchat-arc-body').textContent()).includes('我修改过'));await page.getByRole('button',{name:'对话',exact:true}).click();
   }
   await page.screenshot({path:path.join(out,kind+'-'+theme+'.png')});
   await page.setViewportSize({width:390,height:844});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),kind+' mobile overflow');
   await page.screenshot({path:path.join(out,kind+'-'+theme+'-mobile.png')});
  }
 }
 for(const prefix of ['', '知识库【小红书】']){
  await setup('chat','light',prefix);
  await page.locator('.lb-manage').click();   // 1020：问收藏页输入框的 + 去掉了（导入在浏览收藏页）
  assert.deepEqual(await page.evaluate(()=>menus),['ai-settings']);
  await page.locator('.lbchat-search').fill('不用斜杠也能提问');await page.locator('.lbchat-search').press('Enter');await page.locator('.lbchat-send:enabled').waitFor();
  assert.equal(await page.evaluate(()=>asks[0].question),'不用斜杠也能提问');
  await page.locator('.lbchat-src > summary').click();await page.locator('.lbchat-src a').click();
  await page.locator('.lb-page-nav button').first().click();
  const io=await page.evaluate(()=>({reads,writes,opened}));const root=prefix?prefix+'/':'';
  for(const p of [...io.reads,...io.writes,...io.opened.map(x=>x[0])])assert.ok(p.startsWith(root),p);
  assert.equal(io.opened.at(-1)[0],root+'小红书收藏目录.md');
  await page.locator('.lbchat-search').fill('继续展开细节');await page.locator('.lbchat-search').press('Enter');await page.locator('.lbchat-send:enabled').waitFor();assert.equal(await page.evaluate(()=>asks[1].history.length),2);
  await setup('catalog','light',prefix);await page.locator('.lbc-card').first().click();
  assert.ok((await page.evaluate(()=>opened[0][0])).startsWith(root+'Web/'));
  assert.equal(await page.locator('.lbc-card-more').count(),0);await page.locator('.lbc-card').first().click({button:'right'});assert.equal(await page.locator('.lbc-menu').count(),1);
  assert.equal(await page.locator('[aria-label="收藏导航"]').count(),0);
  // 批次 D · X17：「已收藏」就地筛选（不再跳星标页）
  {const before=(await page.evaluate(()=>opened)).length;await page.locator('.lbc-cat').filter({hasText:'已收藏'}).click();assert.equal((await page.evaluate(()=>opened)).length,before,'不跳页');assert.ok(await page.locator('.lbc-cat.is-active').filter({hasText:'已收藏'}).count());assert.ok(await page.evaluate(()=>[...document.querySelectorAll('.lbc-card .lbc-star')].every(s=>s.classList.contains('is-on'))),'只剩已收藏的');}
 }
 await page.setViewportSize({width:1100,height:900});await setup('starred','light');assert.equal(await page.locator('.lbc-card').count(),2);assert.equal(await page.locator('.lbc-cover:visible').count(),0);assert.equal(await page.locator('.lbc-grid-inner > .lbc-col').count(),1,'星标页单列（批次 D · C9 按行瀑布流：列是 .lbc-col）');await page.screenshot({path:path.join(out,'starred-text.png')});
 await page.locator('.lbc-cat').filter({hasText:'已收藏'}).click();assert.equal(await page.evaluate(()=>opened.at(-1)[0]),'小红书收藏目录.md');
 await setup('chat','light');await page.evaluate(()=>{const pane=document.querySelector('main');pane.style.cssText='height:650px;margin-top:80px;overflow:auto';window.scrollTo(0,0);});
 await page.waitForFunction(()=>document.querySelector('.lbchat-composer').getBoundingClientRect().bottom<=document.querySelector('main').getBoundingClientRect().bottom);
 await page.locator('.lbchat-search').fill('分栏测试');await page.locator('.lbchat-search').press('Enter');await page.locator('.lbchat-send:enabled').waitFor();await page.locator('.lbchat-cite').first().click();
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS shipped pages, pane-constrained composer, visible compare selector and starred-filter exit. '+out);
})().catch(e=>{console.error(e);process.exit(1);});   // 1015：失败时浏览器没关会让进程一直挂着，直接退出

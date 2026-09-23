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
   if(kind==='starred')data.items.forEach((it,i)=>it.starred=i<2);
   Element.prototype.createEl=function(tag,opts={}){const el=document.createElement(tag);if(opts.cls)el.className=opts.cls;if(opts.text!=null)el.textContent=opts.text;this.append(el);return el;};
   Element.prototype.empty=function(){this.replaceChildren();};Element.prototype.setText=function(t){this.textContent=t;};Element.prototype.appendText=function(t){this.append(document.createTextNode(t));};
   window.mediaOpened=[];window.bundles=[];window.opened=[];window.reads=[];window.writes=[];window.asks=[];window.menus=[];window.copied='';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async s=>{window.copied=s;}}});
   const item=data.items.find(x=>x.note);
   window.app={vault:{getAbstractFileByPath:p=>p===(prefix?prefix+'/':'')+'_archive'?{}:null,adapter:{read:async p=>{reads.push(p);return p.endsWith('catalog-data.json')?JSON.stringify(data):p.endsWith('notes.json')?JSON.stringify({starred:!!data.items.find(it=>it.notes_path&&p.endsWith(it.notes_path))?.starred}):'{}';},write:async(p,s)=>writes.push(p),getBasePath:()=> 'D:/LIGHT WEB ARCHIEVE/vault',getResourcePath:p=>covers[p.slice(prefix?prefix.length+1:0)]||''}},workspace:{openLinkText:(...args)=>opened.push(args)},plugins:{plugins:{'link-brain-actions':{
    settings:{hiddenCats:[]},openArchiveMedia:async(it,kind)=>mediaOpened.push(kind),openArchiveSource:(p,root,compare)=>{opened.push([(prefix?prefix+'/':'')+p,compare]);},starNote:async(id,on)=>({starred:on}),openAttachments:()=>{},openCategories:()=>{},openPlusMenu:()=>menus.push('plus'),openManageMenu:()=>menus.push('manage'),openAISettingsMenu:()=>menus.push('ai-settings'),exportArchiveBundle:async(...args)=>{bundles.push(args);return {path:'test.zip'};},
    answerArchive:async r=>{asks.push({question:r.question,history:r.history});r.onDelta('正在逐字呈现');await new Promise(resolve=>setTimeout(resolve,300));r.onDelta('收藏中的内容。');await new Promise(resolve=>setTimeout(resolve,300));return {markdown:'这段回答演示收藏问答的阅读布局。\n\n具体内容以收藏原文为依据，材料不足时会明确说明。[来源1]',sources:[{id:item.id,citation:1,title:item.title,note:item.note,excerpts:[{field:'body',text:'收藏中的内容'}]}]};},
    renderMarkdownInto:async(s,el)=>{for(const t of s.split('\n\n'))el.createEl('p',{text:t});}
   }}}};
   window.dv={container:document.querySelector('#root'),current:()=>({file:{folder:prefix}}),page:()=>null};
  },{data,covers,prefix,kind});
  let code=fs.readFileSync('link_brain/assets/catalog-search.js','utf8')+'\n'+fs.readFileSync('link_brain/assets/'+(kind==='chat'?'chat-view.js':'catalog-view.js'),'utf8');
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
    assert.equal(await page.locator('.lbc-star').first().evaluate(e=>getComputedStyle(e).opacity),'0');await page.locator('.lbc-card').first().hover();await page.locator('.lbc-star').first().click();assert.equal(await page.locator('.lbc-star').first().getAttribute('aria-pressed'),'true');
    await page.getByRole('button',{name:'视频',exact:true}).click();assert.ok(await page.locator('.lbc-card').count()>0);await page.locator('.lbc-video').first().click();assert.equal(await page.evaluate(()=>mediaOpened.at(-1)),'video');await page.getByRole('button',{name:'全部',exact:true}).click();
    assert.equal(await page.locator('.lbc-grid').evaluate(el=>getComputedStyle(el).overflowY),'visible');
    assert.ok((await page.locator('.lbc-grid').boundingBox()).height>1920,'waterfall must extend beyond the viewport');
    await page.evaluate(()=>window.scrollTo(0,800));assert.equal((await page.locator('.lbc-top').boundingBox()).y,0,'header sticks during page scroll');
    await page.locator('.lbc-card').last().scrollIntoViewIfNeeded();assert.ok((await page.locator('.lbc-card').last().boundingBox()).y<960,'last card remains reachable');await page.evaluate(()=>window.scrollTo(0,0));
   }else{
    await page.locator('.lbchat-cite').click();assert.ok((await page.evaluate(()=>opened)).length);
    await page.getByRole('button',{name:'复制',exact:true}).click();assert.ok((await page.evaluate(()=>copied)).includes('D:/LIGHT WEB ARCHIEVE/vault/Web/'));
    await page.locator('.lbchat-answer p').first().dblclick();await page.locator('.lbchat-editor').fill('我修改过的回答 [来源1]');await page.getByRole('button',{name:'保存修改',exact:true}).click();assert.ok((await page.locator('.lbchat-answer').textContent()).includes('我修改过'));
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
  await page.locator('.lbchat-plus').click();await page.locator('.lb-manage').click();
  assert.deepEqual(await page.evaluate(()=>menus),['plus','ai-settings']);
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
  await page.locator('.lbc-cat').filter({hasText:'已收藏'}).click();assert.equal(await page.evaluate(()=>opened.at(-1)[0]),root+'星标收藏.md');
 }
 await page.setViewportSize({width:1100,height:900});await setup('starred','light');assert.equal(await page.locator('.lbc-card').count(),2);assert.equal(await page.locator('.lbc-cover:visible').count(),0);assert.equal(await page.locator('.lbc-grid-inner').evaluate(e=>getComputedStyle(e).columnCount),'auto');await page.screenshot({path:path.join(out,'starred-text.png')});
 await page.locator('.lbc-cat').filter({hasText:'已收藏'}).click();assert.equal(await page.evaluate(()=>opened.at(-1)[0]),'小红书收藏目录.md');
 await setup('chat','light');await page.evaluate(()=>{const pane=document.querySelector('main');pane.style.cssText='height:650px;margin-top:80px;overflow:auto';window.scrollTo(0,0);});
 await page.waitForFunction(()=>document.querySelector('.lbchat-composer').getBoundingClientRect().bottom<=document.querySelector('main').getBoundingClientRect().bottom);
 await page.locator('.lbchat-reader-layout').selectOption('compare');await page.locator('.lbchat-search').fill('分栏测试');await page.locator('.lbchat-search').press('Enter');await page.locator('.lbchat-send:enabled').waitFor();await page.locator('.lbchat-cite').click();assert.equal(await page.evaluate(()=>opened.at(-1)[1]),true);
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS shipped pages, pane-constrained composer, visible compare selector and starred-filter exit. '+out);
})().catch(e=>{console.error(e);process.exitCode=1;});

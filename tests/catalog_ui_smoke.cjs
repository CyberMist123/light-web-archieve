// Run with NODE_PATH pointing at the bundled playwright installation.
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');

(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const aliases=JSON.parse(fs.readFileSync('link_brain/assets/search-aliases.json','utf8'));
  const data={built_at:new Date().toISOString(),pinyin_chars:{},aliases,cats_order:['音乐','吃的'],cats:[{name:'音乐',keywords:['music']},{name:'吃的',keywords:['菜谱']}],items:[
    {id:'a',title:'Music collection',tags:['music'],cats:['音乐'],summary:'原文中的播放方式与音乐清单。',search_fields:{body:'原文中的播放方式与音乐清单。'},search_text:'原文中的播放方式与音乐清单。',note:'a.md',attachment:'none'},
    {id:'b',title:'十分钟快手菜谱',tags:['菜谱'],cats:['吃的'],search_text:'鸡肉 200 克，蒸 20 分钟。',note:'b.md',attachment:'待补',attachment_missing:1},
  ]};
  const search=fs.readFileSync('link_brain/assets/catalog-search.js','utf8');
  const view=fs.readFileSync('link_brain/assets/catalog-view.js','utf8');
  const setup=async(simple=false)=>{
    await page.setContent(`<style>:root{--font-interface:'Segoe UI','Microsoft YaHei',sans-serif;--text-normal:#262626;--text-muted:#757575;--text-faint:#999;--background-primary:#fff;--background-secondary:#f5f5f5;--background-modifier-border:#e5e5e5;--interactive-accent:#8869c9;--text-error:#b33}body{margin:20px;background:#fff;color:var(--text-normal)}button{padding:6px 10px;border:1px solid #ddd;border-radius:6px;background:#fff;cursor:pointer}input,textarea{box-sizing:border-box;border:1px solid #ddd;color:#262626}a{color:#8869c9}</style><main class="markdown-preview-view"><div id="root"></div></main>`);
    await page.evaluate(({data})=>{
      Element.prototype.createEl=function(tag,opts={}){const el=document.createElement(tag);if(opts.cls)el.className=opts.cls;if(opts.text!=null)el.textContent=opts.text;for(const [k,v]of Object.entries(opts))if(!['cls','text'].includes(k))el.setAttribute(k,v);this.append(el);return el;};
      Element.prototype.empty=function(){this.replaceChildren();};Element.prototype.setText=function(t){this.textContent=t;};
      window.asks=[];window.opened=[];window.panels=[];
      window.app={vault:{adapter:{read:async()=>JSON.stringify(data),getResourcePath:x=>x},getName:()=> 'vault'},plugins:{plugins:{'link-brain-actions':{
        settings:{hiddenCats:[]},openAttachments:(list)=>window.panels.push(list),openCategories:(cats,selected)=>window.panels.push(selected||'all'),openImportModal:()=>window.panels.push('import'),openPlusMenu:()=>window.panels.push('import'),
        answerArchive:async request=>{window.asks.push(request);return {markdown:'材料：鸡肉 200 克。\n步骤：蒸 20 分钟。[来源1]',sources:[{citation:1,title:'十分钟快手菜谱',note:'b.md'}]};},
        renderMarkdownInto:async(text,el)=>{el.setText(text);el.style.whiteSpace='pre-wrap';}
      }}},workspace:{openLinkText:(...args)=>window.opened.push(args)}};
      window.dv={container:document.querySelector('#root'),page:()=>null};
    },{data});
    await page.evaluate(async code=>{await new Function('return (async()=>{'+code+'})()')();},search+'\n'+(simple?view.replace('const simplePage = false;','const simplePage = true;'):view));
  };
  await setup();
  assert.equal(await page.locator('.lbc-card').count(),2);
  const input=page.locator('.lbc-search');await input.fill('音乐');
  assert.equal(await page.locator('.lbc-card').count(),2,'typing does not run search');
  await input.press('Enter');assert.equal(await page.locator('.lbc-card').count(),1);
  for(const term of ['音','music']){await input.fill(term);await input.press('Enter');assert.equal(await page.locator('.lbc-card').count(),1);}
  await page.locator('.lbc-import').click();assert.equal(await page.evaluate(()=>panels.at(-1)),'import');
  await input.fill('/菜谱');await input.press('Enter');await page.locator('.lbc-follow textarea:enabled').waitFor();
  assert.equal(await page.locator('.lbc-grid').isVisible(),false);
  assert.equal(await page.locator('.lbc-turn').count(),2);
  await page.locator('.lbc-follow textarea').fill('没有烤箱呢');await page.locator('.lbc-follow textarea').press('Enter');
  await page.locator('.lbc-follow textarea:enabled').waitFor();
  assert.equal(await page.evaluate(()=>asks[1].history.length),2);
  await page.locator('.lbc-sources summary').first().click();await page.locator('.lbc-sources a').first().click();
  assert.equal(await page.evaluate(()=>opened.at(-1)[0]),'b.md');
  const out=process.env.LWA_QA_DIR||path.join(require('os').tmpdir(),'lwa-ui-qa');fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'chat.png'),fullPage:true});
  await setup(true);assert.equal(await page.locator('.lbc-card').count(),0);
  await page.locator('.lbc-search').fill('菜谱');await page.locator('.lbc-search').press('Enter');
  assert.equal(await page.locator('.lbc-card').count(),1);assert.equal(await page.locator('.lbc-grid').evaluate(el=>getComputedStyle(el).columnCount),'auto');
  await page.screenshot({path:path.join(out,'search.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.locator('.lbc-sync').click();assert.equal(await page.evaluate(()=>panels.at(-1)[0].id),'b');
  await page.setViewportSize({width:900,height:900});
  await page.evaluate(code=>{
    window.fakeFiles=[{name:'教程.pdf',size:10,mtime:1},{name:'其他.pdf',size:20,mtime:4},{name:'教程.pdf.crdownload',size:50,mtime:4}];
    const item={id:'file-note',title:'教程收藏',attachment:'待补',url:'https://example.com/note',attachment_missing:1,attachment_files:[{name:'教程.pdf',doc_id:'doc1',downloaded:false}]};
    const mocks={
      obsidian:{Modal:class{constructor(app){this.app=app;this.contentEl=document.body.createEl('div');this.contentEl.style.cssText='max-width:650px;margin:20px auto;padding:25px;border:1px solid #ddd;border-radius:14px';}open(){this.onOpen();}close(){this.onClose?.();this.contentEl.remove();}},Notice:class{}},
      'fs/promises':{readdir:async()=>fakeFiles.map(f=>({name:f.name,isFile:()=>true})),stat:async p=>{const f=fakeFiles.find(f=>p.endsWith('/'+f.name));return {size:f.size,mtimeMs:f.mtime};}},
      path:{join:(...parts)=>parts.join('/'),parse:name=>({name:name.replace(/\.[^.]+$/,'')})},
      electron:{shell:{openExternal:async url=>{window.browserUrl=url;}}}
    };
    const module={exports:{}};new Function('require','module',code)(name=>mocks[name],module);
    window.attached=[];
    const plugin={lbPath:p=>p,app:{vault:{adapter:{read:async()=>JSON.stringify({items:[{...item,attachment:'downloaded',attachment_missing:0,attachment_files:[{name:'教程.pdf',doc_id:'doc1',downloaded:true}]}]})}}},settings:{downloads:{folder:'C:/Downloads',waitMinutes:1}},attachFile:async(...args)=>{attached.push(args);return {};}};
    window.attachmentModal=new (module.exports(mocks.obsidian).AttachmentModal)(plugin,[item],()=>{});attachmentModal.open();
  },fs.readFileSync('obsidian-plugins/link-brain-actions/library-ui.js','utf8'));
  await page.waitForTimeout(50);
  assert.equal(await page.locator('button').filter({hasText:'推荐 · 教程.pdf'}).count(),1);
  await page.evaluate(()=>attachmentModal.waitDownload());
  await page.waitForTimeout(2200);
  assert.equal(await page.evaluate(()=>attached.length),0,'unchanged downloads must not auto-attach');
  await page.evaluate(()=>{fakeFiles[0]={name:'教程.pdf',size:100,mtime:20};});
  await page.waitForFunction(()=>attached.length===1,{},{timeout:6500});
  assert.deepEqual(await page.evaluate(()=>attached[0]),['file-note','C:/Downloads/教程.pdf','doc1']);
  await page.screenshot({path:path.join(out,'attachment.png'),fullPage:true});
  await page.evaluate(async()=>{attachmentModal.plugin.attachFile=async()=>{throw Error('disk full');};await attachmentModal.attach('C:/Downloads/教程.pdf');});
  assert.ok((await page.evaluate(()=>attachmentModal.status.textContent)).includes('挂载失败：disk full'));
  await page.evaluate(()=>attachmentModal.close());
  assert.deepEqual(errors,[]);await browser.close();console.log('PASS browser: Enter, bilingual search, chat follow-up, sources, import, attachment queue, folder watch, attachment failure, list view, 390px width. Screenshots: '+out);
})().catch(e=>{console.error(e);process.exitCode=1;});

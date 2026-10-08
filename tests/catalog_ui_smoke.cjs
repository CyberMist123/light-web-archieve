// 目录页冒烟（批次 D · L1 按现行结构重写）：在 Obsidian 外壳（tests/_obsidian_shell.cjs）里真跑目录页——
//   边打边搜（停顿出结果、不用回车）、中英同义词、「+」菜单、去问收藏、星标页单列、390 宽不横滚；
//   C5 打字预算：350 / 1000 篇合成数据，每 60ms 敲一个字共 6 个，量「最后一个 input 事件 → 网格变动后的下一帧」，p95 ≤150ms / ≤300ms（RELEASE-BAR §2）；
//   附件队列窗口（library-ui.js）照旧。
// 跑法：node tests/catalog_ui_smoke.cjs（run-node 的 UI 层；没装 playwright 记 SKIP）
const shell=require('./_obsidian_shell.cjs');
const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');
const step=s=>{if(process.env.LWA_SMOKE_DEBUG)console.log('· '+s);};

(async()=>{
  shell.requirePlaywright();
  const browser=await shell.launch();
  // 断言失败也关浏览器（以前挂在这里：进程不退出，run-node 等满 180 秒才算超时）
  try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const aliases=JSON.parse(fs.readFileSync('link_brain/assets/search-aliases.json','utf8'));
  const data={built_at:new Date().toISOString(),pinyin_chars:{},aliases,cats_order:['音乐','吃的'],cats:[{name:'音乐',keywords:['music']},{name:'吃的',keywords:['菜谱']}],topics:[],state_registry:{},items:[
    {id:'a',title:'Music collection',tags:['music'],cats:['音乐'],summary:'原文中的播放方式与音乐清单。',search_fields:{body:'原文中的播放方式与音乐清单。'},note:'a.md',attachment:'none'},
    {id:'b',title:'十分钟快手菜谱',tags:['菜谱'],cats:['吃的'],search_fields:{body:'鸡肉 200 克，蒸 20 分钟。'},note:'b.md',attachment:'待补',attachment_missing:1},
  ]};
  const out=process.env.LWA_QA_DIR||path.join(require('os').tmpdir(),'lwa-qa');fs.mkdirSync(out,{recursive:true});
  let S=await shell.page(page,{host:'page-reading',kind:'catalog',data,plugin:{methods:{openPlusMenu:{result:null}}}});
  const cards=()=>page.locator('.lbc-card').count();
  assert.equal(await cards(),2);step('opened');
  const input=page.locator('.lbc-search');
  // 边打边搜：停顿就出结果（不用按回车）
  await input.fill('音乐');await page.waitForTimeout(200);
  assert.equal(await cards(),1,'停顿后自动出结果');
  for(const term of ['音','music']){await input.fill(term);await page.waitForTimeout(200);assert.equal(await cards(),1,term);}
  await input.fill('');await page.waitForTimeout(50);assert.equal(await cards(),2,'清空立刻恢复');
  step('search ok');
  // 「+」菜单走插件 openPlusMenu
  await page.locator('.lbc-import').click();
  assert.ok((await S.calls()).some(c=>c[0]==='openPlusMenu'));
  // 搜不到同义词时「去问收藏」：设 pendingArchiveQuestion、跳问收藏页（按 frontmatter 找文件）
  await input.fill('菜谱');await page.waitForTimeout(200);
  await page.locator('.lbc-ask-tip').click();await S.settle();
  assert.equal(await page.evaluate(()=>window.plugin.pendingArchiveQuestion),'菜谱');
  assert.equal(await page.evaluate(()=>window.opened.at(-1)[0]),'问收藏.md');
  await S.screenshot('catalog-live-search');
  step('ask ok');
  // 星标页：单列列表
  S=await shell.page(page,{host:'page-reading',kind:'starred',data:{...data,items:data.items.map(x=>({...x,starred:true}))}});
  await page.locator('.lbc-search').fill('菜谱');await page.waitForTimeout(200);
  assert.equal(await cards(),1);
  assert.equal(await page.locator('.lbc-grid-inner > .lbc-col').count(),1,'星标页单列');
  await S.screenshot('starred-search');
  // 390 宽不横滚
  await page.setViewportSize({width:390,height:844});await S.settle(80);
  assert.ok(await page.evaluate(()=>{const s=document.querySelector('.markdown-preview-view');return s.scrollWidth<=s.clientWidth+1;}));

  step('starred ok');
  // C5 打字预算
  const budget={};
  for(const [n,limit] of [[350,150],[1000,300]]){
    await page.setViewportSize({width:1280,height:900});
    S=await shell.page(page,{host:'page-reading',kind:'catalog',data:shell.makeCatalogData({n})});
    await page.evaluate(()=>{
      const s=document.querySelector('.lbc-search');window.__ev=[];
      s.addEventListener('input',()=>window.__ev.push(['in',performance.now()]));
      new MutationObserver(()=>{const t=performance.now();requestAnimationFrame(()=>window.__ev.push(['mut',t,performance.now()]));}).observe(document.querySelector('.lbc-grid'),{childList:true,subtree:true});
    });
    const words=['悉尼样例 1','做饭样例 2','学习样例 3','穿搭样例 4','家居样例 5','旅行样例 6','AI样例 7','悉尼样例 8','做饭样例 9','学习样例 1','穿搭样例 2','家居样例 3'];
    const lat=[];
    for(const w of words){
      await page.click('.lbc-search');await page.keyboard.press('Control+A');await page.keyboard.press('Backspace');await page.waitForTimeout(200);
      await page.evaluate(()=>{window.__ev=[];});
      for(const ch of [...w].slice(0,6)){await page.keyboard.type(ch);await page.waitForTimeout(60);}
      await page.waitForTimeout(500);
      // 最后一个 input → 它之后第一次网格变动的下一帧
      const ev=await page.evaluate(()=>window.__ev);
      const last=Math.max(...ev.filter(e=>e[0]==='in').map(e=>e[1]));
      const m=ev.find(e=>e[0]==='mut'&&e[1]>=last);
      if(m)lat.push(m[2]-last);
    }
    lat.sort((a,b)=>a-b);    const p95=lat[Math.min(lat.length-1,Math.ceil(lat.length*0.95)-1)];
    budget[n]={samples:lat.length,p50:Math.round(lat[Math.floor(lat.length/2)]),p95:Math.round(p95)};
    assert.ok(lat.length>=words.length-1,'每轮都量到了：'+lat.length);
    assert.ok(p95<=limit,`${n} 篇：最后一键到结果 p95=${Math.round(p95)}ms（预算 ${limit}ms）`);
  }
  step('budget ok');
  console.log('C5 打字预算（外壳 Chromium，不是 Obsidian 实测）：'+JSON.stringify(budget));
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
  assert.deepEqual(errors,[]);}catch(e){await browser.close().catch(()=>{});throw e;}await browser.close();console.log('PASS browser: live search without Enter, bilingual search, + menu, ask-in-chat jump, starred single column, 390px width, typing budget 350 / 1000, attachment queue, folder watch, attachment failure. Screenshots: '+(process.env.LWA_QA_DIR||require('path').join(require('os').tmpdir(),'lwa-qa')));
})().catch(e=>{console.error(e);process.exitCode=1;});
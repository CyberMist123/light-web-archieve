const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage({viewport:{width:1100,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const css=fs.readFileSync('link_brain/assets/link-brain.css','utf8');
 const source=fs.readFileSync('obsidian-plugins/link-brain-native-media-nav/main.js','utf8');
 const data=JSON.parse(fs.readFileSync('vault/_archive/catalog-data.json','utf8'));
 const covers=data.items.filter(x=>x.cover).slice(0,12).map(x=>'data:image/webp;base64,'+fs.readFileSync(path.join('vault',x.cover)).toString('base64'));
 async function setup(video=false){
  await page.setContent(`<style>:root{--background-primary:white;--background-secondary:#f5f5f5;--text-normal:#222;--text-muted:#777;--text-faint:#999;--interactive-accent:#666}body{margin:20px;font-family:Arial}button{cursor:pointer}.markdown-preview-view{height:calc(100vh - 40px);overflow:auto;} ${css}</style><main class="markdown-preview-view xhs-note"><div class="lb-note"><div class="lb-side"><section class="lb-media"><div class="lb-carousel">${video?'<figure class="lb-slide"><video controls></video></figure>':''}${covers.map(src=>`<figure class="lb-slide"><img src="${src}"></figure>`).join('')}</div></section></div><div class="lb-main"><div class="lb-scroll"><h2>图文阅读测试</h2>${'<p>作者正文与评论，可独立滚动查看。</p>'.repeat(70)}</div></div></div><div style="height:500px">笔记底部</div></main>`);
  await page.evaluate(source=>{
   Element.prototype.createEl=function(tag,o={}){const e=document.createElement(tag);if(o.cls)e.className=o.cls;if(o.text!=null)e.textContent=o.text;this.append(e);return e;};Element.prototype.setText=function(s){this.textContent=s;};
   class Plugin{register(){}registerDomEvent(el,name,fn){el.addEventListener(name,fn);}}
   const m={exports:{}};new Function('require','module',source)(()=>({Plugin}),m);window.plugin=new m.exports();plugin.onload();
  },source);
 }
 await setup();assert.equal(await page.locator('.lb-media-pin').getAttribute('aria-pressed'),'true');
 const picture=await page.locator('.lb-carousel').boundingBox();await page.locator('.lb-scroll').evaluate(e=>e.scrollTop=700);assert.equal((await page.locator('.lb-carousel').boundingBox()).y,picture.y);
 assert.equal(await page.locator('.lb-media-pages,.lb-thumbnails').count(),0);
 await page.locator('.lb-carousel').click({position:{x:30,y:50}});await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.querySelector('.lb-carousel').scrollLeft>100);
 await page.locator('.lb-media-pin').click();assert.equal(await page.locator('.lb-media-pin').getAttribute('aria-pressed'),'false');assert.equal(await page.locator('.lb-main').evaluate(e=>getComputedStyle(e).overflow),'visible');
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await setup(true);assert.equal(await page.locator('.lb-media-pages').count(),0);assert.equal(await page.locator('.lb-slide:visible').count(),1);
 const arrow=await page.locator('.lb-carousel').evaluate(e=>getComputedStyle(e,'::scroll-button(right)').content);assert.ok(arrow==='none'||arrow==='normal'||arrow==='');
 const lockedVideo=await page.locator('video').boundingBox();await page.locator('video').hover();await page.mouse.wheel(0,650);await page.waitForTimeout(150);
 assert.equal((await page.locator('video').boundingBox()).y,lockedVideo.y,'video must remain fixed under real wheel input');
 assert.equal(await page.locator('main').evaluate(e=>e.scrollTop),0);assert.ok(await page.locator('.lb-scroll').evaluate(e=>e.scrollTop>0));
 await page.locator('.lb-video-speed').click();assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),1.25);
 const box=await page.locator('.lb-video-speed').boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+80,box.y+box.height/2,{steps:8});await page.mouse.up();assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),2.25);
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS media: pin/unpin, stationary images, original image paging, no duplicate page toolbar, narrow layout, no video paging overlay, click and drag playback speed');
})().catch(e=>{console.error(e);process.exitCode=1;});

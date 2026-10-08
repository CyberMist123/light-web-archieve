const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage({viewport:{width:1100,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const css=fs.readFileSync('link_brain/assets/link-brain.css','utf8');
 const source=fs.readFileSync('obsidian-plugins/link-brain-actions/media-nav.js','utf8');   // 第 5 批 B2：图片导航并进主插件
 // 批次 D · L3：封面改用现画的图（3:4，12 张），不再读真库——worktree 里也能跑
 const covers=Array.from({length:12},(_,i)=>'data:image/svg+xml;base64,'+Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="hsl(${i*30},60%,72%)"/><text x="40" y="140" font-size="120" font-family="Arial">${i+1}</text></svg>`).toString('base64'));
 async function setup(video=false){
  await page.setContent(`<style>:root{--background-primary:white;--background-secondary:#f5f5f5;--text-normal:#222;--text-muted:#777;--text-faint:#999;--interactive-accent:#666}body{margin:20px;font-family:Arial}button{cursor:pointer}.markdown-preview-view{height:calc(100vh - 40px);overflow:auto;} ${css}</style><main class="markdown-preview-view xhs-note"><div class="lb-note"><div class="lb-side"><section class="lb-media"><div class="lb-carousel">${video?'<figure class="lb-slide"><video controls></video></figure>':''}${covers.map(src=>`<figure class="lb-slide"><img src="${src}"></figure>`).join('')}</div></section></div><div class="lb-main"><div class="lb-scroll"><h2>图文阅读测试</h2>${'<p>作者正文与评论，可独立滚动查看。</p>'.repeat(70)}</div></div></div><div style="height:500px">笔记底部</div></main>`);
  await page.evaluate(source=>{
   Element.prototype.createEl=function(tag,o={}){const e=document.createElement(tag);if(o.cls)e.className=o.cls;if(o.text!=null)e.textContent=o.text;this.append(e);return e;};Element.prototype.setText=function(s){this.textContent=s;};Element.prototype.createDiv=function(o={}){return this.createEl('div',o);};
   const host={app:{},settings:{media:{loop:false,playlistOrder:'newest'}},async saveSettings(){window.__saved=(window.__saved||0)+1;},register(){},registerDomEvent(el,name,fn,opts){el.addEventListener(name,fn,opts);}};
   const m={exports:{}};new Function('require','module',source)(()=>({}),m);window.plugin=m.exports({},host);plugin.attach();
  },source);
 }
 // 0926 起默认不钉（跟正文一起滚），要钉住点右上角的钉
 await setup();assert.equal(await page.locator('.lb-media-pin').getAttribute('aria-pressed'),'false');
 await page.locator('.lb-carousel').hover();await page.locator('.lb-media-pin').click();assert.equal(await page.locator('.lb-media-pin').getAttribute('aria-pressed'),'true');
 const picture=await page.locator('.lb-carousel').boundingBox();await page.locator('.lb-scroll').evaluate(e=>e.scrollTop=700);assert.equal((await page.locator('.lb-carousel').boundingBox()).y,picture.y);
 assert.equal(await page.locator('.lb-media-pages,.lb-thumbnails').count(),0);
 await page.locator('.lb-carousel').click({position:{x:30,y:50},modifiers:['Alt']});   // 选中图片区（带 Alt：普通单击会打开大图查看器）await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.querySelector('.lb-carousel').scrollLeft>100);
 await page.locator('.lb-media-pin').click();assert.equal(await page.locator('.lb-media-pin').getAttribute('aria-pressed'),'false');assert.equal(await page.locator('.lb-main').evaluate(e=>getComputedStyle(e).overflow),'visible');
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await setup(true);assert.equal(await page.locator('.lb-media-pages').count(),0);assert.equal(await page.locator('.lb-slide:visible').count(),1);
 const arrow=await page.locator('.lb-carousel').evaluate(e=>getComputedStyle(e,'::scroll-button(right)').content);assert.ok(arrow==='none'||arrow==='normal'||arrow==='');
 // 10-04：视频控制条和倍速行平时藏着，鼠标放到视频上才出现，移开再藏；Tab 到视频上也出现；藏 / 显不改版面
 await page.mouse.move(1000,880);await page.waitForTimeout(50);
 const vbox0=await page.locator('video').boundingBox();
 assert.equal(await page.locator('video').evaluate(v=>v.controls),false,'not hovered: native controls hidden');
 assert.equal(await page.locator('.lb-media-tools').evaluate(e=>getComputedStyle(e).opacity),'0','not hovered: speed row hidden');
 await page.locator('video').hover();await page.waitForTimeout(200);
 assert.equal(await page.locator('video').evaluate(v=>v.controls),true,'hover: controls shown');
 assert.equal(await page.locator('.lb-media-tools').evaluate(e=>getComputedStyle(e).opacity),'1','hover: speed row shown');
 await page.locator('.lb-video-speed').hover();assert.equal(await page.locator('video').evaluate(v=>v.controls),true,'moving onto the speed row keeps controls');
 await page.mouse.move(1000,880);await page.waitForTimeout(200);
 assert.equal(await page.locator('video').evaluate(v=>v.controls),false,'leave: hidden again');
 assert.deepEqual(await page.locator('video').boundingBox(),vbox0,'showing / hiding controls does not move the video');
 await page.locator('video').evaluate(v=>v.blur());await page.keyboard.press('Tab');await page.waitForTimeout(50);
 if(await page.evaluate(()=>document.activeElement&&document.activeElement.tagName)==='VIDEO')assert.equal(await page.locator('video').evaluate(v=>v.controls),true,'keyboard focus shows controls');
 await page.locator('video').hover();await page.locator('.lb-media-pin').click();assert.equal(await page.locator('.lb-media-pin').getAttribute('aria-pressed'),'true');
 const lockedVideo=await page.locator('video').boundingBox();await page.locator('video').hover();await page.mouse.wheel(0,650);await page.waitForTimeout(150);
 assert.equal((await page.locator('video').boundingBox()).y,lockedVideo.y,'video must remain fixed under real wheel input');
 assert.equal(await page.locator('main').evaluate(e=>e.scrollTop),0);assert.ok(await page.locator('.lb-scroll').evaluate(e=>e.scrollTop>0));
 await page.locator('.lb-video-speed').click();assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),1.25);
 const box=await page.locator('.lb-video-speed').boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+80,box.y+box.height/2,{steps:8});await page.mouse.up();assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),2.25);
 // 批次 D · F6：循环 / 连播… 和倍速在同一行、同样悬停才出现；点循环 = video.loop + 存设置
 assert.equal(await page.locator('.lb-media-tools .lb-video-loop').count(),1);assert.equal(await page.locator('.lb-media-tools .lb-video-playlist').count(),1);
 await page.locator('.lb-video-loop').click();assert.equal(await page.locator('video').evaluate(v=>v.loop),true);assert.equal(await page.locator('.lb-video-loop').getAttribute('aria-pressed'),'true');assert.equal(await page.evaluate(()=>window.__saved),1);
 assert.equal(await page.locator('.lb-video-loop').evaluate(e=>getComputedStyle(e).fontSize),'13px','循环按钮不被 :first-child/:last-child 放大');assert.equal(await page.locator('.lb-video-playlist').evaluate(e=>getComputedStyle(e).fontSize),'13px');
 await page.mouse.move(1000,880);await page.waitForTimeout(200);assert.equal(await page.locator('.lb-media-tools').evaluate(e=>getComputedStyle(e).opacity),'0','移开：整行（含循环 / 连播）藏起来');
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS media: video controls + speed row only on hover / keyboard focus, pin/unpin, stationary images, original image paging, no duplicate page toolbar, narrow layout, no video paging overlay, click and drag playback speed');
})().catch(e=>{console.error(e);process.exit(1);});

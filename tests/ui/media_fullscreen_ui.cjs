// 1026 她（录屏 13:22）：「你看它不是全屏。」——真 Edge 里：笔记页视频点「全屏」，整块（画面 + 倍速 / 循环 / 连播）铺满屏幕，
// 画面按比例占满、工具行看得见能点；退出后右栏正文的滚动位置还在。大图查看器 ⛶ 同样铺满。（真视频 tests/fixtures/tiny-1s.mp4）
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage({viewport:{width:1100,height:800}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const css=fs.readFileSync('link_brain/assets/link-brain.css','utf8');const source=fs.readFileSync('obsidian-plugins/link-brain-actions/media-nav.js','utf8');
 const mp4='data:video/mp4;base64,'+fs.readFileSync('tests/fixtures/tiny-1s.mp4').toString('base64');
 const img='data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#c33"/></svg>').toString('base64');
 const paras=Array.from({length:80},(_,i)=>`<p>第 ${i+1} 段正文</p>`).join('');
 await page.setContent(`<style>body{margin:0}${css}</style><main class="markdown-preview-view xhs-note" style="height:800px;overflow:auto"><div class="lb-note" data-lb-item="xhs-v"><div class="lb-side"><section class="lb-media"><div class="lb-carousel"><figure class="lb-slide"><video controls muted src="${mp4}" style="width:400px;height:300px"></video></figure></div></section></div><div class="lb-main"><div class="lb-scroll" style="height:400px!important;max-height:400px!important;overflow-y:auto!important;display:block!important">${paras}</div></div></div>
  <div class="lb-note" data-lb-item="xhs-i"><div class="lb-side"><section class="lb-media"><div class="lb-carousel"><figure class="lb-slide"><img src="${img}"></figure><figure class="lb-slide"><img src="${img}"></figure></div></section></div><div class="lb-main"><p>图文</p></div></div></main>`);
 await page.evaluate(source=>{
  Element.prototype.createEl=function(tag,o={}){const e=document.createElement(tag);if(o.cls)e.className=o.cls;if(o.text!=null)e.textContent=o.text;this.append(e);return e;};Element.prototype.setText=function(s){this.textContent=s;};Element.prototype.createDiv=function(o={}){return this.createEl('div',o);};
  const host={app:{},settings:{media:{loop:false,playlistOrder:'newest'}},async saveSettings(){},register(){},registerDomEvent(el,n,f,o){el.addEventListener(n,f,o);}};
  const m={exports:{}};new Function('require','module',source)(()=>({}),m);window.plugin=m.exports({},host);plugin.attach();
 },source);
 await page.waitForFunction(()=>document.querySelector('video').readyState>=2);
 await page.evaluate(()=>{document.querySelector('.lb-scroll').scrollTop=600;});
 assert.equal(await page.evaluate(()=>document.querySelector('.lb-scroll').scrollTop),600,'fixture: 右栏能滚');
 const media=page.locator('.lb-media').first();
 await media.hover();
 await page.locator('.lb-video-full').click();
 await page.waitForFunction(()=>document.fullscreenElement&&document.fullscreenElement.classList.contains('lb-media'));
 await page.waitForTimeout(150);
 const r=await page.evaluate(()=>{const m=document.fullscreenElement,v=m.querySelector('video'),t=m.querySelector('.lb-media-tools');const mb=m.getBoundingClientRect(),vb=v.getBoundingClientRect(),tb=t.getBoundingClientRect();
  return {mw:mb.width,mh:mb.height,vw:vb.width,vh:vb.height,iw:innerWidth,ih:innerHeight,tools:getComputedStyle(t).opacity,tTop:tb.top,tBottom:tb.bottom,btn:m.querySelector('.lb-video-full').textContent,cl:v.getAttribute('controlslist')};});
 assert.ok(Math.abs(r.mw-r.iw)<2&&Math.abs(r.mh-r.ih)<2,`整块铺满屏幕 ${JSON.stringify(r)}`);
 assert.ok(r.vw>=r.iw-2&&r.vh>r.ih*0.8,`画面占满（按比例） ${JSON.stringify(r)}`);
 assert.equal(r.tools,'1','全屏里倍速 / 循环 / 连播那一行看得见');assert.ok(r.tBottom<=r.ih+1&&r.tTop>r.ih*0.8,'工具行在屏幕底部');
 assert.equal(r.btn,'退出全屏');assert.equal(r.cl,'nofullscreen');
 await page.locator('.lb-video-speed').click();
 assert.equal(await page.evaluate(()=>document.querySelector('video').playbackRate),1.25,'全屏里倍速照样能点');
 await page.locator('.lb-video-full').click();
 await page.waitForFunction(()=>!document.fullscreenElement);await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>document.querySelector('.lb-scroll').scrollTop),600,'退出后右栏正文还停在原处');
 assert.equal(await page.evaluate(()=>document.querySelector('.lb-media').classList.contains('is-lb-fullscreen')),false);
 // 大图：点图开大图 → ⛶ 铺满屏幕；Esc 键先退全屏（这里用 exitFullscreen 模拟浏览器的 Esc），大图还开着
 await page.locator('.lb-note[data-lb-item="xhs-i"] .lb-slide img').first().click();
 await page.locator('.lb-lightbox .lb-lb-full').click();
 await page.waitForFunction(()=>document.fullscreenElement&&document.fullscreenElement.classList.contains('lb-lightbox'));
 const box=await page.evaluate(()=>{const b=document.querySelector('.lb-lightbox img').getBoundingClientRect();return {h:b.height,ih:innerHeight};});
 assert.ok(box.h>box.ih*0.95,`全屏里图按屏幕高放大 ${JSON.stringify(box)}`);
 await page.evaluate(()=>document.exitFullscreen());await page.waitForFunction(()=>!document.fullscreenElement);
 assert.equal(await page.locator('.lb-lightbox').count(),1,'退出全屏不关大图');
 await page.keyboard.press('Escape');assert.equal(await page.locator('.lb-lightbox').count(),0,'再按 Esc 关大图');
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS media fullscreen (Edge): note video 全屏 fills screen with speed/loop row visible and clickable, exit keeps .lb-scroll position; lightbox ⛶ fills screen, exit keeps lightbox, Esc closes');
})().catch(e=>{console.error(e);process.exit(1);});

// 1015：点视频画面正中要可靠地切换播放 / 暂停（真 Edge + 真视频 tests/fixtures/tiny-1s.mp4）。
// 修之前在 Edge 150 上复现的两条根因（见 media-nav.js clickToggle）：
//   ① 原生「点画面切换」延后约 300ms 执行，期间再点就把前一下取消 → 隔 250ms 连点 4 下，一次 play/pause 都没有；
//   ② controls 被悬停逻辑关着时点画面完全没反应。
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage({viewport:{width:1100,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const css=fs.readFileSync('link_brain/assets/link-brain.css','utf8');const source=fs.readFileSync('obsidian-plugins/link-brain-actions/media-nav.js','utf8');
 const mp4='data:video/mp4;base64,'+fs.readFileSync('tests/fixtures/tiny-1s.mp4').toString('base64');
 const covers=['<svg xmlns="http://www.w3.org/2000/svg" width="60" height="80"><rect width="60" height="80" fill="#ccc"/></svg>'].map(s=>'data:image/svg+xml;base64,'+Buffer.from(s).toString('base64'));
 await page.setContent(`<style>body{margin:20px}${css}</style><main class="markdown-preview-view xhs-note"><div class="lb-note"><div class="lb-side"><section class="lb-media"><div class="lb-carousel"><figure class="lb-slide"><video controls muted src="${mp4}" style="width:400px;height:300px"></video></figure>${covers.map(s=>`<figure class="lb-slide"><img src="${s}"></figure>`).join('')}</div></section></div><div class="lb-main"><p>正文</p></div></div></main>`);
 await page.evaluate(source=>{
  Element.prototype.createEl=function(tag,o={}){const e=document.createElement(tag);if(o.cls)e.className=o.cls;if(o.text!=null)e.textContent=o.text;this.append(e);return e;};Element.prototype.setText=function(s){this.textContent=s;};Element.prototype.createDiv=function(o={}){return this.createEl('div',o);};
  const host={app:{},settings:{media:{loop:true,playlistOrder:'newest'}},async saveSettings(){},register(){},registerDomEvent(el,n,f,o){el.addEventListener(n,f,o);}};
  const m={exports:{}};new Function('require','module',source)(()=>({}),m);window.plugin=m.exports({},host);plugin.attach();
 },source);
 await page.waitForFunction(()=>document.querySelector('video').readyState>=2);
 await page.evaluate(()=>{const v=document.querySelector('video');window.log=[];['play','pause'].forEach(n=>v.addEventListener(n,()=>log.push(n)));});
 const v=page.locator('video');const box=await v.boundingBox();const cx=box.x+box.width/2,cy=box.y+box.height/2;
 const take=()=>v.evaluate(v=>({paused:v.paused,log:log.splice(0)}));
 // 一下一下点：每下立刻切（不等 300ms）
 for(const want of [false,true,false,true]){await page.mouse.click(cx,cy);await page.waitForTimeout(60);assert.equal((await take()).paused,want,'click on picture toggles at once');}
 // 隔 250ms 连点 4 下：4 次切换都算（原生会全吞掉）
 for(let i=0;i<4;i++){await page.mouse.click(cx,cy);await page.waitForTimeout(250);}
 await page.waitForTimeout(400);let r=await take();assert.deepEqual(r.log,['play','pause','play','pause'],'rapid clicks each count');assert.equal(r.paused,true);
 // 从外面移进来马上点
 await page.mouse.move(1000,880);await page.waitForTimeout(100);await page.mouse.move(cx,cy);await page.mouse.down();await page.mouse.up();await page.waitForTimeout(60);
 assert.equal((await take()).paused,false,'click right after entering plays');
 await page.mouse.click(cx,cy);await page.waitForTimeout(60);assert.equal((await take()).paused,true);
 // 控制条因悬停状态没对上而关着：点画面照样切；光标一动控制条补出来
 await v.evaluate(v=>{v.controls=false;});await page.mouse.click(cx,cy);await page.waitForTimeout(60);
 assert.equal((await take()).paused,false,'click works even when controls are off');
 await page.mouse.click(cx,cy);await page.waitForTimeout(60);assert.equal((await take()).paused,true);
 await page.mouse.move(1000,880);await page.waitForTimeout(50);await v.evaluate(v=>{v.controls=false;});
 await page.mouse.move(cx,cy);await page.mouse.move(cx+5,cy+5);await page.waitForTimeout(50);assert.equal(await v.evaluate(v=>v.controls),true,'pointer moving over video shows controls');
 // 底部原生控制条那一条不接管（交给原生的进度 / 音量 / 全屏）
 const prevented=await v.evaluate(v=>{const r=v.getBoundingClientRect();const ev=new MouseEvent('click',{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.bottom-10,button:0});v.dispatchEvent(ev);return ev.defaultPrevented;});
 assert.equal(prevented,false,'bottom control bar left to native');
 // 视频不会弹大图查看器
 assert.equal(await page.locator('.lb-lightbox').count(),0);
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS video click: picture click toggles at once, rapid clicks each count, works with controls off, control bar left native, no lightbox');
})().catch(e=>{console.error(e);process.exit(1);});

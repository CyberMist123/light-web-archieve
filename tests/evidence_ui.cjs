const {chromium}=require('playwright');
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const context={module:{exports:{}},process,setTimeout,clearTimeout,require:n=>n==='obsidian'?{Plugin:class{},PluginSettingTab:class{},Modal:class{}}:require(n)};
vm.createContext(context);vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8'),context);
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage();
 const proto=context.module.exports.prototype;
 await page.setContent(`<div id="reader"><div class="markdown-preview-view"><div class="xhs-note"><div class="lb-carousel"><div class="lb-slide"><img src="../../_archive/x/raw/v0001/assets/a.webp"></div><div class="lb-slide"><img src="../../_archive/x/raw/v0001/assets/b.webp"></div></div><div class="lb-body"><p>Nightly memory consolidation builds and prunes duplicate edges.</p><p>Unrelated opening paragraph.</p></div><div class="lb-comment-text">The author confirmed that naps run between conversations.</div><details class="lb-transcript"><div class="lb-body"><p>The transcript explains how memories become connected.</p></div></details></div></div></div>`);
 const result=await page.evaluate(async methods=>{
  const plugin={};for(const [name,code] of Object.entries(methods))plugin[name]=new Function('return '+(code.startsWith('async ')?code.replace('async ','async function '):'function '+code))();
  const root=document.querySelector('#reader');const leaf={view:{containerEl:root}};const request=leaf.lbEvidenceRequest={};
  await plugin.locateArchiveEvidence(leaf,[{field:'body',text:'Nightly memory consolidation builds and prunes duplicate edges.'}],request);
  const body=root.querySelector('.lb-evidence-hit').textContent;
  await plugin.locateArchiveEvidence(leaf,[{field:'ocr',text:'image evidence',assets:['raw/v0001/assets/b.webp']}],request);
  const image=root.querySelector('.lb-evidence-hit').getAttribute('src');
  await plugin.locateArchiveEvidence(leaf,[{field:'comments',text:'The author confirmed that naps run between conversations.'}],request);
  const comment=root.querySelector('.lb-evidence-hit').classList.contains('lb-comment-text');
  await plugin.locateArchiveEvidence(leaf,[{field:'transcript',text:'The transcript explains how memories become connected.'}],request);
  const transcript=root.querySelector('.lb-transcript').open;
  await plugin.locateArchiveEvidence(leaf,[{field:'body',text:'memory'}],request);
  const missing=!root.querySelector('.lb-evidence-hit')&&!root.querySelector('.lb-evidence-bar');
  return {body,image,comment,transcript,missing,bars:root.querySelectorAll('.lb-evidence-bar').length};
 },{evidenceTargets:proto.evidenceTargets.toString(),locateArchiveEvidence:proto.locateArchiveEvidence.toString()});
 assert.ok(result.body.startsWith('Nightly'));assert.ok(result.image.endsWith('b.webp'));assert.ok(result.comment&&result.transcript&&result.missing);assert.equal(result.bars,0);
 await browser.close();console.log('PASS evidence: paragraph, exact image, comment, hidden transcript, no false topic match, replacement toolbar');
})().catch(e=>{console.error(e);process.exit(1)});

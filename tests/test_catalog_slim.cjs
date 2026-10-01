// 1001 审计 ui-4：catalog-data 不再带 search_text；目录页/问收藏页的打分与摘录改从 search_fields 取，旧数据照样能用。
// 跑法：node tests/test_catalog_slim.cjs
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync('link_brain/assets/catalog-search.js','utf8')+'\nthis.score=score;this.itemText=itemText;',ctx);
const slim={id:'a',title:'家常菜',tags:[],summary:'概要',search_fields:{transcript:'',body:'正文',attachments:'番茄炒蛋先炒蛋'}};
const legacy={id:'b',title:'旧数据',tags:[],summary:'概要',search_text:'旧版拼好的全文 番茄'};
assert.equal(ctx.itemText(slim),'正文\n番茄炒蛋先炒蛋');
assert.equal(ctx.itemText(legacy),'旧版拼好的全文 番茄');
assert.equal(ctx.itemText({summary:'只有概要'}),'只有概要');
assert.ok(ctx.score(slim,'番茄炒蛋')>0,'附件全文仍参与打分');
assert.ok(ctx.score(legacy,'番茄')>0,'旧数据 search_text 仍参与打分');
for(const f of ['catalog-view.js','chat-view.js'])
  assert.ok(!/it\.search_text/.test(fs.readFileSync('link_brain/assets/'+f,'utf8')),f+' 不再直接读 search_text');
console.log('PASS catalog slim: itemText from search_fields, legacy search_text fallback, scoring unchanged');

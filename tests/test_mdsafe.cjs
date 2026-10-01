// 1001 审计 C-2：插件 neutralizeMarkdown 与 link_brain/mdsafe.py 同一套规则（共用 fixtures/mdsafe_cases.json），
// 且 renderMarkdownInto 交给 Obsidian 渲染的一定是清洗后的文本。跑法：node tests/test_mdsafe.cjs
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const rendered=[];
const obsidian={Plugin:class{},PluginSettingTab:class{},Modal:class{},MarkdownRenderer:{render:async(app,md)=>{rendered.push(md);}}};
const context={module:{exports:{}},process,setTimeout,clearTimeout,require:n=>n==='obsidian'?obsidian:require(n)};
vm.createContext(context);vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8'),context);
const cases=JSON.parse(fs.readFileSync('tests/fixtures/mdsafe_cases.json','utf8'));
(async()=>{
  const p=new context.module.exports();
  for(const c of cases){
    assert.equal(p.neutralizeMarkdown(c.input),c.expected,c.name);
    assert.equal(p.neutralizeMarkdown(c.expected),c.expected,c.name+' (idempotent)');
  }
  assert.equal(p.neutralizeMarkdown(null),'');
  await p.renderMarkdownInto("答：\n```dataviewjs\nx\n```\n`$=1`",{setText(){}});
  assert.equal(rendered.length,1);
  assert.ok(!/```dataviewjs/.test(rendered[0])&&!/`\$=/.test(rendered[0]),rendered[0]);
  // chat-view.js 的导出走插件同一个函数
  const chat=fs.readFileSync('link_brain/assets/chat-view.js','utf8');
  assert.ok(/return safeMd\(L\.join/.test(chat)&&/neutralizeMarkdown/.test(chat));
  console.log(`PASS mdsafe: ${cases.length} shared cases, renderMarkdownInto neutralizes, chat export uses it`);
})().catch(e=>{console.error(e);process.exitCode=1;});

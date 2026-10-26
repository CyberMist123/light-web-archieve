// 1026 她：提问气泡底下一排小图标——复制 / 重来（退回到这一问再问一遍）/ 编辑（放回输入框，发送时从这一问重来）
'use strict';
const assert = require('node:assert/strict');
const { tick, makePlugin, openChat } = require('./_fake_L2.cjs');

(async () => {
  const P = makePlugin();
  const C = await openChat({ plugin: P });
  await C.ask('第一问');
  await C.ask('第二问');
  assert.equal(C.saved().turns.length, 4);
  const acts = i => C.qa('.lbchat-user')[i].querySelectorAll('.lbchat-uact');
  assert.deepEqual(acts(0).map(b => b.getAttribute('aria-label').slice(0, 2)), ['复制', '重来', '编辑']);
  assert.ok(!C.qa('.lbchat-user')[0].querySelector('.lbchat-user-edit'), '气泡里不再放「编辑」');
  // 重来第二问：退回到它之前，用同一句话再问一遍
  const n = P.calls.asks.length;
  await acts(1)[1].onclick({ stopPropagation() {} }); await tick(30);
  assert.equal(P.calls.asks.length, n + 1); assert.equal(P.calls.asks.at(-1).question, '第二问');
  assert.deepEqual(C.saved().turns.filter(t => t.role === 'user').map(t => t.content), ['第一问', '第二问']);
  // 编辑第一问：放回输入框；改了发送 → 第一问和后面的都换掉
  acts(0)[2].onclick({ stopPropagation() {} });
  assert.equal(C.search.value, '第一问');
  await C.ask('第一问（改过）');
  assert.deepEqual(C.saved().turns.filter(t => t.role === 'user').map(t => t.content), ['第一问（改过）']);
  assert.equal(C.saved().turns.length, 2);
  // 编辑后清空输入框 = 作罢：再问不截断
  await C.ask('第二个新问题');
  acts(0)[2].onclick({ stopPropagation() {} });
  C.search.value = ''; C.search.oninput();
  await C.ask('另起一问');
  assert.equal(C.saved().turns.filter(t => t.role === 'user').length, 3);
  console.log('PASS chat useracts (1026): copy / rewind / edit under the bubble; rewind re-asks; edit replaces from that question; clearing the box cancels the edit');
})().catch(e => { console.error(e); process.exit(1); });

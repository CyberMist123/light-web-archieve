// 批次 D · L2 A2：回答中换页再回来——接着看见出字和真实阶段；追问进排队（队列在插件上）；前一个回答不丢（写回合并，不整份覆盖）。
// 两个 Dataview 块共用同一个 app / 插件 / vault：A.detach() = 同一窗格换走（组件卸载、这一段摘掉），再开一页 = 换回来。
'use strict';
const assert = require('node:assert/strict');
const { tick, makePlugin, openChat } = require('./_fake_L2.cjs');

(async () => {
  const P = makePlugin(); P.hold();
  const A = await openChat({ plugin: P });
  const shared = { plugin: P, app: A.app, dom: A.dom, V: A.V };

  // (1) 页 A 提问，出了一段字，换走；再开页 B：B 接着显示那段字和当前阶段
  await A.ask('问一');
  const req1 = P.pending()[0].req;
  req1.onPhase('检索收藏：相关 3 / 共 10 条');
  req1.onDelta('第一段');
  A.A.detach();
  const B = await openChat(shared);
  await tick(10);
  assert.ok(B.q('.lbchat-live'), 'B 有流式那一块');
  assert.ok(B.q('.lbchat-live').textContent.includes('第一段'));
  req1.onPhase('生成回答：用 3 条材料'); await tick(5);
  req1.onDelta('\n第二段'); await tick(250);
  assert.ok(B.q('.lbchat-live').textContent.includes('第二段'), '新字接着出（200ms 节流后）');
  assert.equal(P.plugin.chatInFlight.phase, '生成回答：用 3 条材料');
  assert.ok(!B.q('.lbchat-stop').hidden, 'B 上也有 ■');

  // (7) 1026 她「还在回答，切不了」：作答中「清空」照样能点（这一问在后台接着答、答完进它自己那段；细节见 test_chat_bg_1026）
  const n0 = B.saved().turns.length;
  const clear = B.q('.lbchat-clearall');
  assert.ok(!clear.disabled, '作答中「清空」不再锁住');
  // (6) B 的 ■：停的是问收藏那一问（tag 'chat'）
  B.q('.lbchat-stop').onclick();
  assert.deepEqual(P.calls.stops, ['chat']);

  // (2) 在 B 里追问：不并发提问，进排队
  await B.ask('追问');
  assert.equal(P.calls.asks.length, 1, '不并发');
  assert.ok(B.q('.lbchat-queued'), '标「排队」');
  assert.equal(P.plugin.chatQueue.length, 1);

  // (3) 旧问题答完（旧闭包写回）：会话文件依次是 [问一, 答一, 追问…]，历史文件相同；B 自动发出「追问」
  P.reply({ status: 'ok', markdown: '答一', sources: [], related: [] }); await tick(40);
  let turns = B.saved().turns;
  assert.deepEqual(turns.slice(0, 3).map(t => t.content), ['问一', '答一', '追问']);
  const histFile = JSON.parse(B.V.get(`_archive/chat-history/${B.saved().id}.json`));
  assert.deepEqual(histFile.turns.slice(0, 2).map(t => t.content), ['问一', '答一']);
  assert.equal(P.calls.asks.length, 2, 'B 接着把排队的追问发出去');
  assert.equal(P.calls.asks[1].question, '追问');
  assert.equal(n0, 1);
  // (4) 答二完成：4 轮，问答交替，id 唯一
  P.reply({ status: 'ok', markdown: '答二', sources: [], related: [] }); await tick(40);
  turns = B.saved().turns;
  assert.deepEqual(turns.map(t => t.role), ['user', 'assistant', 'user', 'assistant']);
  assert.deepEqual(turns.map(t => t.content), ['问一', '答一', '追问', '答二']);
  assert.equal(new Set(turns.map(t => t.id)).size, 4);
  assert.equal(B.answers().length, 2);

  // (5) 两页都连着：B 入队、C 页答完，只多问 1 次
  const C2 = await openChat(shared);
  await C2.ask('三');
  await B.ask('四'); await tick(5);
  assert.equal(P.calls.asks.length, 3);
  P.reply({ status: 'ok', markdown: '答三', sources: [], related: [] }); await tick(40);
  assert.equal(P.calls.asks.length, 4, '排队的只被取一次');
  P.reply({ status: 'ok', markdown: '答四', sources: [], related: [] }); await tick(40);
  assert.deepEqual(B.saved().turns.slice(4).map(t => t.content), ['三', '答三', '四', '答四']);
  // 两页画出来的一样
  assert.deepEqual(B.qa('.lbchat-turn').map(e => e.dataset.key), C2.qa('.lbchat-turn').map(e => e.dataset.key));

  console.log('PASS chat L2 A2: inflight on plugin (switch page and come back → live text + real phase), ■ stops tag chat, follow-up queued on plugin and asked once after the old closure writes back, answers merged after their own question (no overwrite); 清空 no longer locked while answering (1026)');
})().catch(e => { console.error(e); process.exit(1); });

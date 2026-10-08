// 批次 D · L2：问收藏页底层（A1 按轮缓存 / 乐观更新 / 写链、mountHost 焦点与组字、A3 原地编辑、A4 流式排版、A5 失败分原因、A7 输入框长高、A8 ↓ 最新）
'use strict';
const assert = require('node:assert/strict');
const { tick, src, rel, makePlugin, openChat } = require('./_fake_L2.cjs');
const { makeClock } = require('./_clock.cjs');

async function hostAndFocus() {
  const C = await openChat();
  const { A } = C;
  // 页面挂在容器后面的兄弟 host 上
  assert.equal(A.container.nextElementSibling, C.host, 'host 是 dv.container 的兄弟');
  assert.equal(C.q('.lbchat').parentNode, C.host);
  const s = C.search;
  let blurs = 0; s.addEventListener('blur', () => blurs++);
  s.value = '半句'; s.focus();
  s.dispatchEvent({ type: 'compositionstart', bubbles: true });
  for (let i = 0; i < 3; i++) await A.rerun();
  assert.equal(C.dom.document.activeElement, s, '重跑 3 次后焦点还在输入框');
  assert.equal(blurs, 0, '重跑不触发失焦');
  assert.equal(C.search, s, '同一个输入框');
  // 组字状态还在：组字中按 Enter 不发
  s.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} }); await tick(10);
  assert.equal(C.calls.asks.length, 0, '组字中（compositionstart 后没 end）回车不提交');
  s.dispatchEvent({ type: 'compositionend', bubbles: true });
  s.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} }); await tick(20);
  assert.equal(C.calls.asks.length, 1);
  console.log('PASS chat L2 mountHost: page on host beside dv.container; 3 reruns keep focus + IME composition (no blur), Enter while composing ignored');
}

async function a1() {
  const C = await openChat();
  await C.ask('第一问'); await C.ask('第二问');
  // 第二问默认绑定上一轮来源；两轮回答都在
  assert.equal(C.answers().length, 2);
  const mdEls = C.qa('.lbchat-md');
  const renders = C.md.stats.renders;
  const first = () => C.answers()[0];
  // (a) 点第 1 轮「保留」：不重渲 markdown，正文节点还是原来那两个
  C.rowOf('主要a', first()).querySelector('.lbchat-src-pin').onclick(); await tick(10);
  assert.equal(C.md.stats.renders, renders, '点保留不重渲 markdown');
  assert.ok(C.qa('.lbchat-md').every((m, i) => m === mdEls[i]), '.lbchat-md 还是原来的对象');
  // (d) 同步：点下那一帧按钮已是新状态（不 await）
  const pinB = C.rowOf('主要b', first()).querySelector('.lbchat-src-pin');
  const r = pinB.onclick();
  assert.equal(C.rowOf('主要b', first()).querySelector('.lbchat-src-pin').textContent, '已保留', '返回前按钮已变样');
  await r; await tick(5);
  // (b) 展开主要依据 + 点开命中，再保留 / ×：仍展开
  const det = () => first().querySelector('details[data-part="primary"]');
  det().open = true; det().dispatchEvent({ type: 'toggle' });
  C.rowOf('主要a', first()).querySelector('.lbchat-src-hitbtn').onclick();
  C.rowOf('主要b', first()).querySelector('.lbchat-src-pin').onclick(); await tick(10);
  assert.equal(det().open, true, '保留后主要依据仍展开');
  const hitOf = row => { const kids = row.parentNode.children; return kids[kids.indexOf(row) + 1]; };
  assert.equal(hitOf(C.rowOf('主要a', first())).hidden, false, '命中仍展开');
  // (c) × 之后那行还在，划掉、只剩「恢复」，summary 减 1；点「恢复」复原
  C.rowOf('主要b', first()).querySelector('.lbchat-src-del').onclick(); await tick(10);
  const rowB = C.rowOf('主要b', first());
  assert.ok(rowB.classList.contains('is-removed'));
  assert.deepEqual(rowB.querySelectorAll('button').map(b => b.textContent), ['恢复']);
  assert.ok(det().querySelector('summary').textContent.startsWith('主要依据 · 1'));
  assert.equal(det().open, true, '× 之后仍展开');
  rowB.querySelector('.lbchat-src-restore').onclick(); await tick(10);
  assert.ok(!C.rowOf('主要b', first()).classList.contains('is-removed'));
  assert.ok(det().querySelector('summary').textContent.startsWith('主要依据 · 2'));
  // (g) 并发 3 个操作：每轮回答节点只出现一次、顺序不乱
  C.rowOf('主要a', first()).querySelector('.lbchat-src-pin').onclick();
  C.rowOf('主要b', first()).querySelector('.lbchat-src-del').onclick();
  const more = first().querySelector('details[data-part="related"]');
  C.rowOf('相关c', more).querySelector('.lbchat-src-check').onclick({ stopPropagation() {} });
  first().querySelector('.lbchat-src-add').onclick();
  await tick(20);
  const keys = C.qa('.lbchat-turn').map(e => e.dataset.key);
  assert.equal(new Set(keys).size, keys.length, '没有重复节点');
  assert.deepEqual(keys, C.saved().turns.map(t => t.id), '顺序和会话一致');
  assert.equal(C.md.stats.renders, renders, '这一串操作都没重渲正文');
  console.log('PASS chat L2 A1 (a)(b)(c)(d)(g): source ops rebuild only the source box (no markdown rerender, same .lbchat-md), sync button state, details / hit stay open, × keeps the row struck with 恢复, concurrent ops keep one node per turn');
}

async function a1Writes() {
  const C = await openChat();
  await C.ask('第一问');
  // (e) 写盘延迟 20ms：连点两下保留，写入严格串行，最后写的是「取消保留」
  const real = C.V.vault.adapter.write;
  let active = 0, maxActive = 0; const pins = [];
  C.V.vault.adapter.write = async (p, s) => { active++; maxActive = Math.max(maxActive, active); await tick(20); if (p === C.SESSION) pins.push(JSON.parse(s).pinned); await real(p, s); active--; };
  C.rowOf('主要a').querySelector('.lbchat-src-pin').onclick();
  C.rowOf('主要a').querySelector('.lbchat-src-pin').onclick();
  await tick(200);
  assert.equal(maxActive, 1, '写入严格串行');
  assert.deepEqual(pins.at(-1), [], '最后一次写入的是取消保留');
  assert.deepEqual(C.saved().pinned, []);
  // (f) 写盘失败：回到磁盘值 + 提示
  C.V.vault.adapter.write = async (p, s) => { if (p === C.SESSION) throw new Error('EPERM'); return real(p, s); };
  C.rowOf('主要a').querySelector('.lbchat-src-del').onclick(); await tick(30);
  assert.ok(!C.rowOf('主要a').classList.contains('is-removed'), '没写上：那行回到磁盘状态');
  assert.ok(C.A.notices.some(m => m.startsWith('没保存上，内容还在，可重试：') && m.includes('EPERM')), C.A.notices.join('|'));
  C.V.vault.adapter.write = real;
  // (h) 旧会话（没有 id）：加载后写盘，每轮都有 id
  const old = await openChat({ turns: [{ role: 'user', content: '旧问' }, { role: 'assistant', q: '旧问', content: '旧答', sources: [], related: [] }] });
  assert.ok(old.saved().turns.every(t => typeof t.id === 'string' && t.id), JSON.stringify(old.saved().turns));
  // (i) dispose：被替换的轮次 dispose 恰好 1 次；组件卸载时剩下的全部 dispose
  const D = await openChat();
  await D.ask('一'); await D.ask('二');
  const before = D.md.stats.disposes;
  D.answers()[0].querySelector('.lbchat-edit').onclick();
  const ed = D.q('.lbchat-editor'); ed.value = '改过的答案';
  await ed.onkeydown({ key: 'Enter', ctrlKey: true, preventDefault() {} }); await tick(20);
  assert.equal(D.md.stats.disposes, before + 1, '只换掉的那一轮 dispose 一次');
  D.A.component.unload();
  assert.equal(D.md.stats.live, 0, '卸载时剩下的全部 dispose');
  console.log('PASS chat L2 A1 (e)(f)(h)(i): plugin write chain serial (last write = unpinned), write failure rolls back to disk + 没保存上…, old sessions get ids, replaced turn disposed once and the rest on unload');
}

async function a3() {
  const C = await openChat();
  await C.ask('第一问');
  const ans = C.answers()[0];
  ans.fire('dblclick', { target: ans.querySelector('.lbchat-md p') });
  assert.equal(C.q('.lbchat-editor'), null, '双击不进编辑');
  ans.querySelector('.lbchat-edit').onclick();
  const ed = C.q('.lbchat-editor');
  const bar = ed.nextElementSibling, md = bar.nextElementSibling;
  assert.ok(bar.classList.contains('lbchat-editbar') && md.classList.contains('lbchat-md') && md.hidden, '编辑框在正文位置（正文藏起来）');
  assert.ok(ans.children.indexOf(ed) < ans.children.indexOf(ans.querySelector('.lbchat-srcbox')), '编辑框在来源块之前');
  assert.equal(C.dom.document.activeElement, ed);
  // 先存到「已保存」，编辑后那条同步改
  await ans.querySelector('.lbchat-bookmark').onclick(); await tick(5);
  ed.value = '新答案';
  await ed.onkeydown({ key: 'Enter', ctrlKey: true, preventDefault() {} }); await tick(20);
  assert.equal(C.saved().turns[1].content, '新答案');
  assert.equal(JSON.parse(C.V.get(C.ARCHIVE)).entries[0].content, '新答案');
  assert.equal(C.q('.lbchat-editor'), null);
  // Esc 取消
  C.answers()[0].querySelector('.lbchat-edit').onclick();
  C.q('.lbchat-editor').onkeydown({ key: 'Escape', preventDefault() {}, stopPropagation() {} });
  assert.equal(C.q('.lbchat-editor'), null); assert.equal(C.answers()[0].querySelector('.lbchat-md').hidden, false);
  // 写盘失败：内容改回、编辑框还在
  const real = C.V.vault.adapter.write;
  C.V.vault.adapter.write = async (p, s) => { if (p === C.SESSION) throw new Error('EPERM'); return real(p, s); };
  C.answers()[0].querySelector('.lbchat-edit').onclick();
  const ed2 = C.q('.lbchat-editor'); ed2.value = '没存上的';
  await ed2.onkeydown({ key: 'Enter', ctrlKey: true, preventDefault() {} }); await tick(20);
  assert.ok(C.q('.lbchat-editor'), '失败时编辑框留着');
  assert.equal(C.saved().turns[1].content, '新答案');
  console.log('PASS chat L2 A3: no dblclick edit; 编辑 replaces the body in place (before sources, focused); Ctrl+Enter saves session + saved copy; Esc cancels; failure keeps editor');
}

async function a4() {
  const clock = makeClock();
  const realTick = clock.tick;
  // 假时钟只推定时器；页面里写盘 / 渲染的 Promise 链比它每步冲的几轮微任务深，推完再让真事件循环转几圈
  clock.tick = async ms => { const r = await realTick(ms); for (let i = 0; i < 5; i++) await new Promise(res => setImmediate(res)); return r; };
  const P = makePlugin(); P.hold();
  const C = await openChat({ plugin: P, params: clock.params, run: false });
  await C.A.run(); await clock.tick(50);
  C.search.value = '流式'; C.q('.lbchat-composer').onsubmit({ preventDefault() {} }); await clock.tick(20);
  const req = P.pending()[0].req;
  req.onDelta('## 结论\n'); await clock.tick(200);
  const live = () => C.q('.lbchat-live');
  assert.ok(live().querySelector('.lbchat-md h2'), '整行到了就排版成标题');
  assert.ok(!live().textContent.includes('##'));
  req.onDelta('一句 [来源1]'); await clock.tick(200);
  assert.ok(live().querySelector('.lbchat-live-tail').textContent.includes('[来源1]'), '没换行的留在 tail 原样');
  req.onDelta('\n'); await clock.tick(200);
  assert.ok(live().querySelector('.lbchat-cite.is-pending'), '换行后变成占位胶囊');
  req.onDelta('[看图：来源2 图3]\n'); await clock.tick(200);
  const ph = live().querySelector('.lbchat-imgph');
  assert.ok(ph && ph.textContent.includes('来源2 图3'));
  // 200ms 内 20 个 delta：渲染 1–2 次
  const r0 = C.md.stats.renders;
  for (let i = 0; i < 20; i++) { req.onDelta('第' + i + '行\n'); await clock.tick(5); }
  await clock.tick(250);
  assert.ok(C.md.stats.renders - r0 >= 1 && C.md.stats.renders - r0 <= 2, '节流：' + (C.md.stats.renders - r0));
  const key = live().dataset.key;
  P.reply({ status: 'ok', markdown: '## 结论\n\n正式答案 [来源1]', sources: [src('a', 1)], related: [] }); await clock.tick(50);
  assert.equal(C.q('.lbchat-live'), null);
  assert.equal(C.answers().at(-1).dataset.key, key, '正式回答和流式那块是同一个 key');
  // 流式各版都 dispose 了（只剩正式回答那一份还活着）
  assert.equal(C.md.stats.live, 1);
  console.log('PASS chat L2 A4: streaming renders whole lines (heading, pending cite, image placeholder), tail keeps the unfinished line, 200ms throttle, final answer replaces the live block with the same key, live versions disposed');
}

async function a5() {
  const P = makePlugin();
  const C = await openChat({ plugin: P });
  const err = (msg, extra) => Object.assign(new Error(msg), extra);
  const cases = [
    [err('问答模型还没配好', { kind: 'config', code: 'SKIPPED.NOT_CONFIGURED' }), '问答还没配 AI（归档、浏览、搜索不受影响）', ['去设置', '重试', '改一下再问']],
    [err('AI 回答失败：401', { kind: 'api', code: 'NEEDS_HUMAN.AUTH_FAILED', detail: '401' }), 'AI 接口拒绝了这把 key：401', ['去设置', '重试', '改一下再问']],
    [err('问答进程断开了：ValueError: x', { kind: 'crash' }), '问答进程断开了：ValueError: x', ['重试', '改一下再问']],
  ];
  for (const [e, text, btns] of cases) {
    P.plugin.reply = () => e;
    await C.ask('问' + text.length);
    const last = C.answers().at(-1);
    assert.equal(last.querySelector('.lbchat-fail').textContent, text);
    assert.deepEqual(last.querySelector('.lbchat-actions').querySelectorAll('button').map(b => b.textContent), btns);
    assert.equal((last.textContent.match(/重试/g) || []).length, 1, '「重试」只出现一次（按钮）');
  }
  C.answers().at(-1).querySelector('.lbchat-gosetup')?.onclick();
  // 重试：同一个问题、同样的来源；最后一轮的失败记录被替换
  P.plugin.reply = req => ({ status: 'ok', markdown: '这回答上了', sources: [], related: [] });
  const lastQ = C.saved().turns.at(-2).content, n = C.saved().turns.length;
  C.answers().at(-1).querySelector('.lbchat-retry').onclick(); await tick(30);
  assert.equal(C.calls.asks.at(-1).question, lastQ);
  assert.equal(C.saved().turns.length, n, '失败的那一对换成新的一对');
  assert.equal(C.saved().turns.at(-1).content, '这回答上了');
  // 绑定来源的追问失败后重试：带原来的 sourceIds
  P.plugin.reply = req => ({ status: 'ok', markdown: '有来源 [来源1]', sources: [src('a', 1)], related: [] });
  await C.ask('有来源的');
  P.plugin.reply = () => err('x', { kind: 'api', code: 'TRANSIENT.HTTP_429' });
  await C.ask('追问一下');
  assert.equal(C.answers().at(-1).querySelector('.lbchat-fail').textContent, '接口限流了，过一会儿再试');
  const bound = C.calls.asks.at(-1).sourceIds;
  P.plugin.reply = req => ({ status: 'ok', markdown: 'ok', sources: [], related: [] });
  C.answers().at(-1).querySelector('.lbchat-retry').onclick(); await tick(30);
  assert.deepEqual(Array.from(C.calls.asks.at(-1).sourceIds), Array.from(bound));
  // 改一下再问
  P.plugin.reply = () => err('x', { kind: 'timeout' });
  await C.ask('会超时的问题');
  assert.equal(C.answers().at(-1).querySelector('.lbchat-fail').textContent, '网络或接口暂时没响应');
  C.answers().at(-1).querySelector('.lbchat-rephrase').onclick();
  assert.equal(C.search.value, '会超时的问题'); assert.equal(C.dom.document.activeElement, C.search);
  // 停止轮：复制不含「已停止生成」，有「重试」
  P.plugin.reply = () => ({ status: 'cancelled', markdown: '写到一半' });
  await C.ask('停');
  const stopped = C.answers().at(-1);
  assert.deepEqual(stopped.querySelector('.lbchat-actions').querySelectorAll('button').map(b => b.textContent), ['复制', '重试']);
  await stopped.querySelector('.lbchat-copy').onclick();
  assert.equal(C.clip.at(-1), '写到一半');
  console.log('PASS chat L2 A5: failure text by reason (config / auth / crash / 429 / timeout) with one 重试, 去设置 for config+auth, retry replaces the failed pair and reuses sourceIds, 改一下再问 refills + focuses, stopped turn copy without the stop line');
}

async function a7a8() {
  const P = makePlugin(); P.hold();
  const C = await openChat({ plugin: P });
  const s = C.search;
  s.scrollHeight = 120; s.oninput(); assert.equal(s.style.height, '120px');
  s.scrollHeight = 400; s.oninput(); assert.equal(s.style.height, '160px');
  assert.ok(C.q('.lbchat-composer').classList.contains('is-multi'));
  s.value = '发出去'; s.scrollHeight = 30; await C.q('.lbchat-composer').onsubmit({ preventDefault() {} }); await tick(10);
  assert.equal(s.style.height, '40px');
  // A8：往上翻了，来字 → 「↓ 最新」出现并带小点；点它回到底部、隐藏
  const body = C.body, btn = C.q('.lbchat-tobottom');
  body.scrollHeight = 2000; body.clientHeight = 300; body.scrollTop = 100; (body.listeners.scroll || []).forEach(fn => fn());
  assert.equal(btn.hidden, false);
  P.pending()[0].req.onDelta('新字\n'); await tick(5);
  assert.ok(btn.classList.contains('is-live'));
  btn.onclick();
  assert.equal(body.scrollTop, body.scrollHeight); assert.equal(btn.hidden, true);
  P.reply({ status: 'ok', markdown: '完', sources: [], related: [] }); await tick(20);
  console.log('PASS chat L2 A7 / A8: composer grows to 160px max and back to 40px after send; ↓ 最新 shows when scrolled up, dots on new text, jumps to bottom');
}

(async () => {
  await hostAndFocus();
  await a1();
  await a1Writes();
  await a3();
  await a4();
  await a5();
  await a7a8();
})().catch(e => { console.error(e); process.exit(1); });

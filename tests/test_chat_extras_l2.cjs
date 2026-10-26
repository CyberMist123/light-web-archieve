// 批次 D · L2 问收藏页小件：A6 没配问答 AI、A12「我保存的」原地展开 + 切回对话回到原处、A13 打字预热、A14 大图查看器、
// A15 已保存删除可撤销、A16 键盘与焦点、A17 设置实时生效、M1 隐私模式清空 / 切换可撤销、M3 没有原生 alert / confirm、N11 问这篇、忙时带词进插件队列
'use strict';
const assert = require('node:assert/strict');
const { asset } = require('./_fakedom.cjs');
const { tick, src, rel, makePlugin, openChat } = require('./_fake_L2.cjs');

const err = (msg, extra) => Object.assign(new Error(msg), extra);

async function a6() {
  const P = makePlugin({ settings: { models: [{ name: 'DeepSeek' }, { name: '通义' }], activeModel: 'DeepSeek' }, modelState: name => ({ name, usable: name !== 'DeepSeek' }) });
  const C = await openChat({ plugin: P });
  const opts = C.q('.lbchat-model').children.map(o => o.textContent);
  assert.deepEqual(opts, ['DeepSeek（未配置）', '通义'], 'X10：没配好的模型标「（未配置）」');
  const hint = C.q('.lbchat-empty .lbchat-cfghint');
  assert.ok(hint && hint.textContent.includes('问答还没配 AI'), '空白页事先提示');
  hint.querySelector('button').onclick();
  assert.deepEqual(P.calls.setup, ['ai']);
  // 问了才发现没配：失败轮列出找到的相关收藏
  P.plugin.reply = () => err('问答模型还没配好', { kind: 'config', code: 'SKIPPED.NOT_CONFIGURED', payload: { sources: [src('a', 1), src('b', 2)], related: [] } });
  await C.ask('担担面');
  const last = C.answers().at(-1);
  assert.ok(last.textContent.includes('问答还没配 AI，先列出找到的相关收藏（2 篇）'));
  assert.equal(last.querySelectorAll('.lbchat-srcrow').length, 2);
  assert.ok(!last.textContent.includes('请重试'));
  assert.ok(!C.q('.lbchat-cfgbar').hidden, '有会话时输入框上方一行提示');
  // 换到配好的模型：提示收起
  const pick = C.q('.lbchat-model'); pick.value = '通义'; await pick.onchange(); await tick(5);
  assert.ok(C.q('.lbchat-cfgbar').hidden);
  console.log('PASS chat L2 A6 / X10: modelState usable=false → empty-page hint + 去设置 + （未配置） option, config failure still lists found sources without 请重试, hint follows the model picker');
}

async function a12() {
  const P = makePlugin();
  const C = await openChat({ plugin: P, files: { '_archive/chat-archive.json': JSON.stringify({ entries: [{ id: 's2', ts: '2026-10-04T08:00:00+10:00', kind: 'note', title: '', content: '做梦是1\n第二行' }] }) } });
  P.plugin.reply = () => ({ status: 'ok', markdown: '答 [来源1] [来源2]', sources: [src('a', 1), src('saved:s2', 2, { title: '做梦是1', source_kind: 'saved', saved_id: 's2', note: null })], related: [] });
  await C.ask('梦');
  const row = C.rowOf('做梦是1');
  row.querySelector('a').onclick(); await tick(5);
  const box = () => { const kids = row.parentNode.children; return kids.filter(k => k.classList.contains('lbchat-src-saved'))[0]; };
  assert.equal(C.q('.lbchat-tab.is-on').textContent, '对话', '不切整页');
  assert.equal(box().hidden, false); assert.ok(box().textContent.includes('做梦是1'));
  C.rowOf('做梦是1').querySelector('a').onclick(); await tick(5);
  assert.equal(box().hidden, true, '再点收起');
  // 胶囊点进来：展开所在列表、行下展开
  C.answers()[0].querySelector('button.lbchat-cite[data-cite="2"]').onclick({ stopPropagation() {} }); await tick(5);
  assert.equal(C.answers()[0].querySelector('details[data-part="primary"]').open, true);
  assert.equal(box().hidden, false);
  // 从「已保存」切回对话：回到切走前的 lastTop（没在底部跟随时）
  const body = C.body;
  body.scrollHeight = 3000; body.clientHeight = 300; body.scrollTop = 700; (body.listeners.scroll || []).forEach(fn => fn());
  await C.qa('.lbchat-tab').find(t => t.textContent === '已保存').onclick(); await tick(5);
  body.scrollTop = 900;
  await C.qa('.lbchat-tab').find(t => t.textContent === '对话').onclick(); await tick(5);
  assert.equal(body.scrollTop, 700);
  console.log('PASS chat L2 A12: 我保存的 source expands inline under its row (title toggles, cite opens it), lane stays chat; back from 已保存 restores lastTop');
}

async function a13a14() {
  const P = makePlugin();
  const C = await openChat({ plugin: P });
  C.search.value = '担'; C.search.oninput(); C.search.value = '担担'; C.search.oninput();
  assert.equal(P.calls.warm, 1, '第一次打字预热，60 秒内不再调');
  // A14：回答里的两张图，点第 2 张 → 插件大图查看器
  const img = (id, n) => `![[_archive/xiaohongshu/${id}/raw/v0001/image-${n}.jpg|360]]`;
  P.plugin.reply = () => ({ status: 'ok', markdown: `看图 [来源1]\n\n${img('a', 1)} ${img('a', 2)}`, sources: [src('a', 1)], related: [] });
  await C.ask('图');
  const imgs = C.answers()[0].querySelectorAll('.lbchat-md img');
  assert.equal(imgs.length, 2);
  // 插件没有这个接口：不拦截、不抛错
  let ev = { type: 'click', bubbles: true }; imgs[1].dispatchEvent(ev);
  const calls = [];
  P.plugin.openLightbox = (list, i, opts) => { calls.push({ list, i, opts }); return null; };
  ev = C.dom.event('click', { bubbles: true }); imgs[1].dispatchEvent(ev);
  assert.equal(calls.length, 1); assert.equal(ev.defaultPrevented, false, 'openLightbox 返回 null（media-nav 还没有）→ 退回原样');
  P.plugin.openLightbox = (list, i, opts) => { calls.push({ list, i, opts }); return true; };
  ev = C.dom.event('click', { bubbles: true }); imgs[1].dispatchEvent(ev);
  const c = calls.at(-1);
  assert.equal(c.list.length, 2); assert.equal(c.i, 1); assert.equal(ev.defaultPrevented, true);
  assert.equal(c.opts.caption(1), '来源1 · 图2');
  await c.opts.onCaption(1); await tick(5);
  assert.deepEqual(P.calls.opened.at(-1), 'Web/a.md');
  // 仓挂在别的库的子目录：渲染前 ![[_archive/ 补前缀
  const seen = [];
  const P2 = makePlugin({ renderMarkdownScoped: async (md, el) => { seen.push(md); return { dispose() {} }; } });
  const folder = '知识库【小红书】';
  const D = await openChat({ plugin: P2, folder });
  P2.plugin.reply = () => ({ status: 'ok', markdown: img('a', 1), sources: [], related: [] });
  await D.ask('图');
  assert.ok(seen.some(m => m.includes(`![[${folder}/_archive/`)), seen.join('|'));
  console.log('PASS chat L2 A13 / A14: first keystroke warms the worker once; answer image click → plugin.openLightbox(list, index, caption 来源N · 图M, onCaption opens source), null → not intercepted; ![[_archive/ gets the mount prefix');
}

async function a15() {
  const P = makePlugin();
  const entries = [{ id: 'e1', ts: '2026-10-04T08:00:00+10:00', kind: 'note', title: '', content: '第一条' }, { id: 'e2', ts: '2026-10-04T09:00:00+10:00', kind: 'note', title: '', content: '第二条判断' }];
  const C = await openChat({ plugin: P, files: { '_archive/chat-archive.json': JSON.stringify({ entries }) } });
  await C.qa('.lbchat-tab').find(t => t.textContent === '已保存').onclick(); await tick(5);
  C.V.resetCounts();
  await C.qa('.lbchat-arc-del')[1].onclick(); await tick(5);
  assert.deepEqual(JSON.parse(C.V.get(C.ARCHIVE)).entries.map(e => e.id), ['e1']);
  const n = C.A.noticeLog.at(-1);
  assert.ok(n.message.includes('已删除「第二条判断」') && n.buttons[0].label === '撤销', n.message);
  n.buttons[0].click(); await tick(10);
  assert.deepEqual(JSON.parse(C.V.get(C.ARCHIVE)).entries.map(e => e.id), ['e1', 'e2'], '撤销回到原下标');
  assert.equal(C.V.writes[C.ARCHIVE], 2);
  assert.equal(C.qa('.lbchat-arc-item').length, 2);
  // 撤销写盘失败：条目不出现，说「没保存上…」
  await C.qa('.lbchat-arc-del')[0].onclick(); await tick(5);
  const real = C.V.vault.adapter.write;
  C.V.vault.adapter.write = async (p, s) => { if (p === C.ARCHIVE) throw new Error('EPERM'); return real(p, s); };
  C.A.noticeLog.at(-1).buttons[0].click(); await tick(10);
  assert.deepEqual(JSON.parse(C.V.get(C.ARCHIVE)).entries.map(e => e.id), ['e2']);
  assert.ok(C.A.notices.at(-1).startsWith('没保存上，内容还在，可重试：'));
  console.log('PASS chat L2 A15: deleting a saved entry shows 撤销 (restores at the same index, 2 writes); undo write failure says 没保存上…');
}

async function a16() {
  // 进页聚焦：活动叶子里抢，不在活动叶子不抢
  const C = await openChat(); await tick(20);
  assert.equal(C.dom.document.activeElement, C.search, '活动标签页里进页光标在输入框');
  const D = await openChat({ active: false }); await tick(20);
  assert.notEqual(D.dom.document.activeElement, D.search);
  // ↑ 取回上一问
  await C.ask('上一问');
  C.search.value = ''; C.search.selectionStart = 0;
  let pd = false; C.search.onkeydown({ key: 'ArrowUp', isComposing: false, preventDefault() { pd = true; } });
  assert.equal(C.search.value, '上一问'); assert.ok(pd);
  const esc = (extra = {}) => { const e = C.dom.event('keydown', { key: 'Escape', bubbles: true, ...extra }); C.dom.document.dispatchEvent(e); return e; };
  // 面板开着：Esc 关面板、不停止
  C.q('.lbchat-hist').onclick({ stopPropagation() {} }); await tick(5);
  assert.ok(C.dom.document.querySelector('.lbchat-histpanel'));
  esc();
  assert.equal(C.dom.document.querySelector('.lbchat-histpanel'), null);
  assert.deepEqual(C.calls.stops, []);
  // 编辑中：Esc 取消编辑
  C.answers()[0].querySelector('.lbchat-edit').onclick();
  esc(); assert.equal(C.q('.lbchat-editor'), null); assert.deepEqual(C.calls.stops, []);
  // 作答中：Esc = ■；组字中不管
  C.P.hold();
  await C.ask('慢的');
  const e1 = esc({ isComposing: true }); assert.deepEqual(C.calls.stops, []); assert.equal(e1.defaultPrevented, false);
  const e2 = esc(); assert.deepEqual(C.calls.stops, ['chat']); assert.ok(e2.defaultPrevented);
  C.P.reply({ status: 'cancelled', markdown: '' }); await tick(30);
  console.log('PASS chat L2 A16: focus on open only in the active leaf; ↑ recalls the last question; Esc closes panel → cancels edit → stops answering (tag chat), ignored while composing');
}

async function a17() {
  const P = makePlugin({ settings: { models: [{ name: 'DeepSeek' }], activeModel: 'DeepSeek' } });
  const C = await openChat({ plugin: P });
  P.plugin.settings.chatPlaceholder = '想问啥';
  P.plugin.settings.models.push({ name: '通义' });
  C.app.workspace.trigger('link-brain:settings'); await tick(20);
  assert.equal(C.search.placeholder, '想问啥');
  assert.deepEqual(C.q('.lbchat-model').children.map(o => o.value), ['DeepSeek', '通义']);
  assert.equal(C.q('.lbchat-model').value, 'DeepSeek', '保留原来的选择');
  await C.A.rerun();
  assert.deepEqual(C.q('.lbchat-model').children.map(o => o.value), ['DeepSeek', '通义'], 'reuse 之后也在');
  console.log('PASS chat L2 A17: link-brain:settings refreshes the placeholder and the model list (selection kept), also after reuse');
}

async function m1m3() {
  const P = makePlugin();
  const C = await openChat({ plugin: P, session: { id: 'p1', private: true, turns: [] }, files: {
    '_archive/chat-history/h1.json': JSON.stringify({ id: 'h1', startedAt: '2026-10-01T10:00:00+10:00', turns: [{ id: 'x1', role: 'user', content: '老问题' }] }),
    '_archive/chat-history/index.json': JSON.stringify({ conversations: [{ id: 'h1', startedAt: '2026-10-01T10:00:00+10:00', title: '老问题', turns: 1 }] }) } });
  C.A.window.confirm = () => { throw new Error('不该弹原生确认'); };
  await C.ask('隐私问题');
  await C.q('.lbchat-clearall').onclick(); await tick(10);
  assert.deepEqual(C.saved().turns, []);
  const n = C.A.noticeLog.at(-1);
  assert.ok(n.message.includes('已清空（隐私模式') && n.buttons[0].label === '撤销', n.message);
  n.buttons[0].click(); await tick(20);
  assert.equal(C.saved().turns.length, 2); assert.equal(C.saved().private, true); assert.equal(C.saved().id, 'p1');
  assert.ok(!JSON.parse(C.V.get(C.INDEX)).conversations.some(c => c.id === 'p1'), '隐私的那段不进历史');
  // 切到别的历史对话：同样可撤销
  C.q('.lbchat-hist').onclick({ stopPropagation() {} }); await tick(5);
  const item = C.dom.document.querySelectorAll('.lbchat-histitem').find(r => r.dataset.id === 'h1');
  await item.querySelector('.lbchat-histq').onclick(); await tick(20);
  assert.equal(C.saved().id, 'h1');
  const n2 = C.A.noticeLog.at(-1);
  assert.ok(n2.message.includes('已切换') && n2.buttons[0].label === '撤销', n2.message);
  n2.buttons[0].click(); await tick(20);
  assert.equal(C.saved().id, 'p1'); assert.equal(C.saved().private, true);
  // M3：打不开来源 → Notice，不弹 alert；资产里没有原生 alert / confirm
  P.plugin.openArchiveSource = async () => { throw new Error('文件不见了'); };
  await C.answers()[0].querySelector('.lbchat-srcrow a').onclick(); await tick(5);
  assert.deepEqual(C.A.alerts, []);
  assert.ok(C.A.notices.some(m => m === '打不开来源：文件不见了'));
  const code = asset('chat-view.js');
  assert.ok(!code.includes('window.alert(') && !code.includes('window.confirm('));
  console.log('PASS chat L2 M1 / M3: private clear and switch-away are undoable for 8s (no native confirm, never into history); source open failure → Notice, no alert / confirm in the asset');
}

async function n11() {
  const P = makePlugin();
  P.plugin.pendingArchiveScope = { ids: ['xhs-1'], title: '番茄炒蛋', note: 'Web/xhs-1.md', at: Date.now() };
  const C = await openChat({ plugin: P }); await tick(20);
  assert.equal(P.calls.asks.length, 0, '不自动提交');
  assert.equal(P.plugin.pendingArchiveScope, undefined, '取走即删');
  assert.equal(C.dom.document.activeElement, C.search);
  // 1026：来源固定在输入框里那枚小条上（只问这篇 · 标题 ×），标题点了右侧打开这篇
  const chip = C.q('.lbchat-composer .lbchat-scopechip');
  assert.ok(chip && !chip.hidden && chip.textContent.includes('只问这篇') && chip.textContent.includes('番茄炒蛋'));
  assert.ok(C.search.placeholder.includes('问这篇'));
  chip.querySelector('.lbchat-scopechip-title').onclick(); await tick(10);
  assert.ok(P.calls.opened.includes('Web/xhs-1.md'), '小条上的标题打开这一篇');
  await C.A.rerun();
  assert.ok(C.q('.lbchat-scopechip').textContent.includes('番茄炒蛋'), 'Dataview 重跑后还在');
  // 换页回来（整页重建）也还在：存在页面状态里
  const D = await openChat({ plugin: P, app: C.app, dom: C.dom, V: C.V });
  assert.ok(D.q('.lbchat-scopechip').textContent.includes('番茄炒蛋'));
  await C.ask('几个蛋');
  assert.deepEqual(Array.from(P.calls.asks[0].sourceIds), ['xhs-1']);
  const turns = C.saved().turns;
  assert.equal(turns[0].mode, 'scope'); assert.equal(turns[0].scopeTitle, '番茄炒蛋');
  assert.ok(C.answers().length === 1 && C.q('.lbchat-user .lbchat-scopetag').textContent.includes('只问这篇：番茄炒蛋'));
  assert.ok(C.q('.lbchat-scopechip').hidden, '提交后清掉');
  // 回答能回到这一篇：气泡上的标签、回答下的「打开这篇」都开它
  const nOpen = P.calls.opened.length;
  C.q('.lbchat-user .lbchat-scopetag').onclick({ stopPropagation() {} }); await tick(10);
  C.answers()[0].querySelectorAll('.lbchat-act').find(b => b.textContent === '打开这篇').onclick(); await tick(10);
  assert.deepEqual(P.calls.opened.slice(nOpen), ['Web/xhs-1.md', 'Web/xhs-1.md']);
  // 取消
  P.plugin.pendingArchiveScope = { ids: ['xhs-2'], title: '可乐鸡翅', note: 'Web/xhs-2.md', at: Date.now() };
  C.app.workspace.trigger('link-brain:ask-pending'); await tick(10);
  assert.ok(C.q('.lbchat-scopechip').textContent.includes('可乐鸡翅'));
  C.q('.lbchat-scope-cancel').onclick();
  await C.ask('下一问');
  assert.ok(!P.calls.asks.at(-1).sourceIds || !Array.from(P.calls.asks.at(-1).sourceIds).includes('xhs-2'));
  // 忙时目录页带过来的词：进插件队列
  P.hold();
  await C.ask('慢');
  P.plugin.pendingArchiveQuestion = '悉尼咖啡';
  C.app.workspace.trigger('link-brain:ask-pending'); await tick(10);
  assert.deepEqual(P.plugin.chatQueue.map(x => x.q), ['悉尼咖啡']);
  P.release(); P.reply({ status: 'ok', markdown: 'ok', sources: [], related: [] }); await tick(40);
  assert.equal(P.calls.asks.at(-1).question, '悉尼咖啡');
  assert.equal(P.calls.asks.at(-1).sourceIds, undefined, '带过来的是新问题，照常检索');
  console.log('PASS chat L2 N11: pendingArchiveScope presets the source (no auto submit, focus in box, survives rerun / rebuild), submit sends sourceIds and marks the turn, 取消 clears; busy catalog jump goes into plugin.chatQueue');
}

// 审查回归：作答中编辑另一条回答、答完后保存，改动不能丢（答完读回磁盘合并时保留内存里的轮次对象）；
// 别的问收藏页写了会话时，这一页开着的编辑框和里面的字还在
async function editWhileBusy() {
  const P = makePlugin();
  const C = await openChat({ plugin: P });
  await C.ask('第一问');
  P.hold(); await C.ask('第二问');
  C.answers()[0].querySelector('.lbchat-edit').onclick(); await tick(5);
  const ed = C.q('.lbchat-editor'); assert.ok(ed, '作答中可以打开编辑');
  ed.value = '我改过的回答';
  P.reply({ status: 'ok', markdown: '答二', sources: [], related: [] }); await tick(40);
  assert.ok(C.q('.lbchat-editor'), '答完编辑框还在');
  C.q('.lbchat-editsave').onclick(); await tick(40);
  const disk = C.saved().turns;
  assert.equal(disk.length, 4);
  assert.equal(disk[1].content, '我改过的回答', '磁盘上是改后的正文');
  assert.equal(disk[3].content, '答二', '第二问的回答也在');
  assert.ok(C.answers()[0].querySelector('.lbchat-md').textContent.includes('我改过的回答'), '屏幕上是改后的正文');

  // 两页：B 开着编辑框，A 写了会话（问一句）→ B 的编辑框和字都在，保存后两条都在磁盘
  const shared = { plugin: P, app: C.app, dom: C.dom, V: C.V };
  const B = await openChat(shared);
  B.answers()[0].querySelector('.lbchat-edit').onclick(); await tick(5);
  const edB = B.q('.lbchat-editor'); edB.value = 'B 改的';
  P.release(); await C.ask('第三问', 40);
  assert.equal(C.saved().turns.length, 6, 'A 的第三问写盘了');
  assert.ok(edB.isConnected && B.q('.lbchat-editor') === edB, 'B 的编辑框没被摘掉');
  assert.equal(edB.value, 'B 改的');
  B.q('.lbchat-editsave').onclick(); await tick(40);
  const d2 = C.saved().turns;
  assert.equal(d2.length, 6, 'B 保存没把 A 的第三问冲掉');
  assert.equal(d2[1].content, 'B 改的');
  console.log('PASS chat L2 edit while busy: an edit opened during answering saves to disk and screen after the answer lands; another page writing the session keeps the open editor on this page and its text');
}

(async () => {
  await a6();
  await a12();
  await a13a14();
  await a15();
  await a16();
  await a17();
  await m1m3();
  await n11();
  await editWhileBusy();
})().catch(e => { console.error(e); process.exit(1); });

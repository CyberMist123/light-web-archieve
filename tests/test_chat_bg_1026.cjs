// 1026 第三轮（她录屏 04 / 05 / 06 问收藏那几段）：
//   ① 发出去 1 秒内就看得见这一问（不等写盘、不等模型）；生成状态在问题下面（还没出字：阶段 + 秒数；出字后：回答顶上一行）
//   ② 正在答时照样能切历史 / 清空：这一问在后台接着答、答完进它自己那段；输入框上面一行「后台还在回答 · 回去看」，回去接着看出字；
//      隐私模式那段（切走就找不回）才拦
//   ③ 换页切走、整页暂存再挂回新视图（recreate）后：「问这篇」照样取走、来源固定在输入框里那枚小条上（改前 root 指着旧容器，直接返回）
//   ④ 报告：动作（目录 / 来源 / 编辑 / 复制 / 导出 / 存到已保存）——1028 她：在这一答最下面、来源之后（顶上那版是 bug），没有「展开细节」；
//      存上后旁边「已保存 · 打开」，点了到「已保存」那一条
//   ⑤ 1028 她：右栏顶上的证据条（← 回到报告 · 来源：xxx · 上一条 / 下一条）不画了；点引用照样右栏定位、左栏不动、左边那一处亮着；
//      找不到时原帖开着、提示里给「再找一次」；从「可能相关」打开也不画条
'use strict';
const assert = require('node:assert/strict');
const { tick, makePlugin, openChat, src } = require('./_fake_L2.cjs');

async function bubbleFirst() {
  const P = makePlugin(); P.hold();
  const C = await openChat({ plugin: P, prefs: null, turns: [{ id: 'u0', role: 'user', content: '旧问题' }, { id: 'a0', role: 'assistant', content: '旧回答', sources: [], related: [] }] });
  // 写盘卡住（真机：写链前面还有别的写、或者盘慢）：问题照样当场出现
  const adapter = C.V.vault.adapter, realWrite = adapter.write.bind(adapter);
  let gate = null; const held = [];
  adapter.write = (p, s) => { if (!gate) return realWrite(p, s); return new Promise(r => held.push(() => r(realWrite(p, s)))); };
  gate = true;
  const t0 = Date.now();
  C.search.value = '新的一问'; C.q('.lbchat-composer').onsubmit({ preventDefault() {} });
  await tick(30);
  const users = C.qa('.lbchat-user');
  assert.ok(users.some(u => u.textContent.includes('新的一问')), '写盘没完也看得见这一问');
  assert.ok(Date.now() - t0 < 1000);
  assert.ok(!users.some(u => u.textContent.includes('旧问题')), '新问题开了新的一段（上一段在写链里进历史）');
  const think = C.q('.lbchat-think');
  assert.ok(think, '问题下面有生成状态');
  assert.equal(think.previousElementSibling, users.find(u => u.textContent.includes('新的一问')), '状态就在这一问下面');
  assert.ok(think.querySelector('.lbchat-elapsed'), '带秒数');
  P.pending()[0].req.onPhase('检索收藏'); await tick(5);
  assert.ok(think.textContent.includes('检索收藏'));
  gate = null; while (held.length) held.shift()(); await tick(30);
  P.pending()[0].req.onDelta('第一行\n'); await tick(250);
  assert.ok(C.q('.lbchat-live .lbchat-genstat'), '出字后回答顶上一行状态');
  P.reply({ status: 'ok', markdown: '答完', sources: [], related: [] }); await tick(40);
  assert.deepEqual(C.saved().turns.map(t => t.content), ['新的一问', '答完']);
  const hist = JSON.parse(C.V.get(C.INDEX));
  assert.ok(hist.conversations.length >= 2, '上一段进了历史');
  console.log('PASS chat bg ①: question bubble shows before any write / answer, status (phase + seconds) right under it, streamed answer has a status line');
}

async function switchWhileAnswering() {
  const P = makePlugin(); P.hold();
  const other = { id: 'convX', startedAt: '2026-10-01T10:00:00.000Z', turns: [{ id: 'xu', role: 'user', content: '另一段的问题' }, { id: 'xa', role: 'assistant', content: '另一段的回答', sources: [], related: [] }] };
  const C = await openChat({ plugin: P, files: { '_archive/chat-history/index.json': JSON.stringify({ conversations: [{ id: 'convX', startedAt: other.startedAt, title: '另一段的问题', turns: 1 }] }), '_archive/chat-history/convX.json': JSON.stringify(other) } });
  await C.ask('慢慢答的问题');
  const mine = C.saved().id;
  const req = P.pending()[0].req;
  req.onDelta('前半截\n'); await tick(250);
  assert.ok(C.q('.lbchat-live'));
  // 「还在回答，切不了」→ 现在切得过去
  C.q('.lbchat-hist').onclick({ stopPropagation() {} }); await tick(5);
  const row = C.dom.document.querySelectorAll('.lbchat-histq').find(b => b.textContent.includes('另一段'));
  await row.onclick(); await tick(30);
  assert.equal(C.saved().id, 'convX', '切到了另一段');
  assert.ok(C.qa('.lbchat-user').some(u => u.textContent.includes('另一段的问题')));
  assert.ok(!C.q('.lbchat-live') && !C.q('.lbchat-think'), '别的段里不画后台那一问的流式');
  const bg = C.q('.lbchat-bgbar');
  assert.ok(!bg.hidden && bg.textContent.includes('后台还在回答') && bg.textContent.includes('慢慢答的问题'), bg.textContent);
  assert.ok(C.q('.lbchat-stop').hidden, '输入框里的 ■ 只管这段；后台那一问的停止在那一行');
  req.onDelta('后半截\n'); await tick(250);
  assert.ok(!C.q('.lbchat-live'));
  // 回去看：回到那段、接着看出字
  await bg.querySelector('.lbchat-bg-go').onclick(); await tick(260);
  assert.equal(C.saved().id, mine);
  assert.ok(C.q('.lbchat-live') && C.q('.lbchat-live').textContent.includes('后半截'), '回去接着看出字');
  assert.ok(C.q('.lbchat-bgbar').hidden);
  // 再切走，答完：回答进它自己那段的历史，当前这段不多一轮
  C.q('.lbchat-hist').onclick({ stopPropagation() {} }); await tick(5);
  const row2 = C.dom.document.querySelectorAll('.lbchat-histq').find(b => b.textContent.includes('另一段'));
  await row2.onclick(); await tick(30);
  P.reply({ status: 'ok', markdown: '后台答完了', sources: [], related: [] }); await tick(60);
  assert.equal(C.saved().id, 'convX');
  assert.deepEqual(C.saved().turns.map(t => t.content), ['另一段的问题', '另一段的回答'], '当前这段没被插进别人的回答');
  const h = JSON.parse(C.V.get(`_archive/chat-history/${mine}.json`));
  assert.deepEqual(h.turns.map(t => t.content), ['慢慢答的问题', '后台答完了'], '回答进了它自己那段');
  assert.ok(C.q('.lbchat-bgbar').hidden, '答完那一行收起');
  // 隐私模式那段在答：切走找不回来——这种还拦
  const Q = makePlugin(); Q.hold();
  const D = await openChat({ plugin: Q, session: { id: 'priv', private: true, turns: [] }, files: { '_archive/chat-history/index.json': JSON.stringify({ conversations: [{ id: 'convX', startedAt: other.startedAt, title: '另一段的问题', turns: 1 }] }), '_archive/chat-history/convX.json': JSON.stringify(other) } });
  await D.ask('隐私里问');
  D.q('.lbchat-hist').onclick({ stopPropagation() {} }); await tick(5);
  await D.dom.document.querySelectorAll('.lbchat-histq').find(b => b.textContent.includes('另一段')).onclick(); await tick(20);
  assert.equal(D.saved().id, 'priv');
  assert.ok(D.A.notices.some(m => m.includes('隐私模式这段还在回答')), D.A.notices.join('|'));
  Q.reply({ status: 'ok', markdown: '好', sources: [], related: [] }); await tick(30);
  console.log('PASS chat bg ②: switching history while answering works; the answer keeps streaming in the background and lands in its own conversation; 后台还在回答 · 回去看 resumes the live text; private conversation still blocks');
}

async function adoptThenAskThis() {
  const P = makePlugin();
  const C = await openChat({ plugin: P });
  C.q('.lbchat-tab:nth-child(1)');
  const arch = C.qa('.lbchat-tab').find(b => b.textContent === '已保存');
  await arch.onclick(); await tick(10);
  const oldRoot = C.A.container;
  await C.A.recreate(); await tick(20);   // 切走（整页暂存）再回来：挂到新的 dv.container 后面
  assert.notEqual(C.A.container, oldRoot);
  P.plugin.pendingArchiveScope = { ids: ['xhs-9'], title: '番茄炒蛋怎么做才嫩', note: 'Web/xhs-9.md', at: Date.now() };
  C.app.workspace.trigger('link-brain:ask-pending'); await tick(20);
  assert.equal(P.plugin.pendingArchiveScope, undefined, '挂回新视图后照样取走（改前 root 还指着旧容器，直接 return）');
  const chip = C.q('.lbchat-scopechip');
  assert.ok(chip && !chip.hidden && chip.textContent.includes('番茄炒蛋怎么做才嫩'), '来源固定在输入框里');
  assert.ok(!C.q('.lbchat-composer').hidden, '回到对话栏（不是停在「已保存」）');
  console.log('PASS chat bg ③: after park + adopt onto a new container, 问这篇 is consumed, lane switches to 对话, chip in the composer');
}

async function reportTop() {
  const P = makePlugin({ reply: req => ({ status: 'ok', markdown: '## 第一类\n\n要点 [来源1]\n\n## 第二类\n\n要点 [来源2]', sources: [src('a', 1), src('b', 2)], related: [] }) });
  const C = await openChat({ plugin: P, prefs: { follow: 'search', report: true } });
  await C.ask('ai 做梦');
  const ans = C.answers()[0];
  assert.ok(ans.classList.contains('is-report'));
  // 1028 她：操作条在这一答最下面（来源之后），上边一道细线
  const top = ans.querySelector('.lbchat-actions-report');
  assert.ok(top && ans.lastElementChild === top, '动作在这一答最下面');
  assert.ok(!ans.querySelector('.lbchat-actions-top'), '顶上不再有操作条');
  const srcbox = ans.querySelector('.lbchat-srcbox');
  assert.ok(srcbox && srcbox.nextElementSibling === top, '紧跟在来源后面');
  assert.ok(ans.firstElementChild.classList.contains('lbchat-md'), '正文在最前（紧挨问题气泡的是正文，不是操作条）');
  const labels = top.querySelectorAll('.lbchat-act').map(b => b.textContent).filter(Boolean);
  for (const k of ['目录', '来源', '编辑', '复制', '存成笔记'].slice(0, 4)) assert.ok(labels.includes(k), k + ' 在操作条里：' + labels.join(','));
  assert.ok(top.querySelector('.lbchat-export') && top.querySelector('.lbchat-bookmark'));
  assert.ok(!labels.includes('展开细节'), '报告不给「展开细节」');
  const css = [...C.dom.document.head.querySelectorAll('style')].map(x => x.textContent).join('\n');
  const rule = /\.lbchat \.lbchat-actions-report\{([^}]*)\}/.exec(css)?.[1] || '';
  assert.ok(/border-top:1px solid/.test(rule) && /border-bottom:0/.test(rule), '上边细线、下边不要线：' + rule);
  // 来源：跳到主要依据并展开
  top.querySelectorAll('.lbchat-act').find(b => b.textContent === '来源').onclick(); await tick(5);
  assert.ok(ans.querySelector('details.lbchat-src').open);
  // 存到已保存 → 旁边「已保存 · 打开」→ 打开到「已保存」那一条
  await top.querySelector('.lbchat-bookmark').onclick(); await tick(20);
  const tag = C.answers()[0].querySelector('.lbchat-savedtag');
  assert.ok(tag && !tag.hidden && tag.textContent.includes('已保存'), '存上以后旁边写着');
  await tag.querySelector('.lbchat-saved-open').onclick(); await tick(20);
  const item = C.q('.lbchat-arc-item');
  assert.ok(item && item.open, '到了「已保存」，那一条展开着');
  console.log('PASS chat bg ④: report actions at the bottom after sources, border-top only (目录 / 来源 / 编辑 / 复制 / 导出 / 存成笔记 / 书签), no 展开细节, saved tag + one-click open');
}

async function evidenceBar() {
  const box = { el: null };
  const P = makePlugin({
    reply: () => ({ status: 'ok', markdown: '先说正文 [来源1 段1]。\n\n再看评论 [来源1 段2]。\n\n找不到的 [来源1 段3]。',
      sources: [src('a', 1, { excerpts: [{ seg: 1, field: 'body', text: '正文第一段讲火候要小', paras: [0] }, { seg: 2, field: 'comments', text: '三楼说多放醋', comment_labels: ['c3'] }, { seg: 3, field: 'body', text: '这一段原帖里根本没有画出来', paras: [9] }] })],
      related: [{ id: 'r', rank: 2, title: '相关一篇', note: 'Web/r.md', tier: 'related', excerpt: 'x' }] }),
  });
  const C0 = await openChat({ plugin: P, prefs: null, run: false });
  const doc = C0.dom.document;
  const container = doc.createElement('div'); doc.body.append(container);
  const content = container.createEl('div', { cls: 'view-content' });
  const leaf = { id: 'reader', parent: null, view: { containerEl: container, file: null } };
  Object.assign(P.plugin, {
    archiveLeaves: () => ({ reader: leaf, owner: null }),
    archiveSourceState: () => ({ reader: true, compare: false }),
    async openArchiveSource(note) {
      P.calls.opened.push(note);
      if (leaf.view.file?.path === note) return;
      leaf.view.file = { path: note };
      setTimeout(() => {
        content.textContent = '';
        const n = content.createEl('div', { cls: 'lb-note' }); n.setAttribute('data-lb-item', note === 'Web/a.md' ? 'a' : 'r');
        const body = n.createEl('div', { cls: 'lb-body' }); body.createEl('p', { text: '正文第一段讲火候要小' }).setAttribute('data-p', '0');
        const c = n.createEl('article', { cls: 'lb-comment' }); c.setAttribute('data-cid', 'c3'); c.createEl('div', { cls: 'lb-comment-text', text: '三楼说多放醋' });
      }, 20);
    },
  });
  await C0.A.run(); await tick(5);
  const C = C0;
  await C.ask('火候');
  C.body.scrollHeight = 2000; C.body.clientHeight = 400;   // 往上翻着读（不在底部跟随）
  C.body.scrollTop = 37; C.body.dispatchEvent(new C.dom.Event('scroll')); await tick(5);
  const cites = () => C.answers()[0].querySelectorAll('.lbchat-md button.lbchat-cite');
  const bar = () => [...container.children].find(x => x.classList.contains('lb-evbar'));
  // 1028 她：右栏顶上不再画证据条（回到报告 / 来源：xxx / 上一条 / 下一条 都不要）；定位、左栏不动、左边亮着照旧
  cites()[0].onclick({ stopPropagation() {} }); await tick(400);
  assert.ok(!bar(), '右栏顶上没有证据条');
  assert.ok(!container.textContent.includes('回到报告'));
  assert.equal(container.firstElementChild, content, 'view-content 还是右栏第一块');
  assert.equal(leaf.view.file.path, 'Web/a.md', '右栏开了原帖');
  cites()[1].onclick({ stopPropagation() {} }); await tick(400);
  assert.ok(JSON.parse(C.V.get('_archive/locate-last.json')).target === 'comment:c3');
  assert.equal(C.body.scrollTop, 37, '左栏没被带走');
  assert.ok(cites()[1].classList.contains('is-on'), '左边亮着当前这一处');
  assert.ok(!bar());
  // 找不到：原帖开着，提示里给「再找一次」（不靠证据条）
  cites()[2].onclick({ stopPropagation() {} }); await tick(400);
  assert.ok(!bar(), '找不到时也不画条');
  assert.equal(leaf.view.file.path, 'Web/a.md', '原帖还开着');
  const warn = C.A.noticeLog.find(n => n.message.includes('没找到引用的那一处'));
  assert.ok(warn && warn.buttons.some(b => b.label === '再找一次'), C.A.notices.join('|'));
  const before = JSON.parse(C.V.get('_archive/locate-history.json')).length;
  warn.buttons.find(b => b.label === '再找一次').click(); await tick(400);
  assert.equal(JSON.parse(C.V.get('_archive/locate-history.json')).length, before + 1, '再找了一次');
  // 从「可能相关」打开：同样不画条
  const more = C.answers()[0].querySelector('details.lbchat-src-more'); more.open = true;
  const relRow = C.rowOf('相关一篇');
  relRow.querySelector('a').onclick(); await tick(100);
  assert.equal(leaf.view.file.path, 'Web/r.md');
  assert.ok(!bar(), '从「可能相关」打开也没有证据条');
  // 悬停卡片也写短的辨识信息
  cites()[1].dispatchEvent(new C.dom.Event('focus'));
  assert.ok(doc.body.querySelector('.lbchat-citepop .w').textContent.startsWith('来源 1 · 评论第 3 楼'));
  console.log('PASS chat bg ⑤ (1028): no evidence bar in the reader; cite locate still works, left stays + lit; not found keeps the note + 再找一次 in the notice; 可能相关 opens without a bar');
}

(async () => {
  await bubbleFirst();
  await switchWhileAnswering();
  await adoptThenAskThis();
  await reportTop();
  await evidenceBar();
})().catch(e => { console.error(e); process.exit(1); });

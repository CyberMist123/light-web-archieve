// 10-04 问收藏第二批（车 C）页面：
// ③ 来源多选（主要依据 / 其他相关都能选，悬停出圈）→「加入来源」/「删除」；② 加入的来源重答时作为 pinIds 带上
// ④ 来源行精简：没有「查看」「加入对照」「复制来源」，新增「命中」（在该行下展开命中原文，带字段身份）；「我保存的」带小标
// ⑤ 清空只开新对话、不删记录；所有问答自动进历史（按天分组、点一行恢复、多选删除）；隐私模式开着不进历史；旧会话补进历史
// ⑥ 已保存默认只一行标题，点开才展开
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';
const SESSION = '_archive/chat-session.json';
const INDEX = '_archive/chat-history/index.json';
const CODE = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js');

(async () => {
  const src = (id, n, extra = {}) => ({ id, citation: n, title: '主要' + id, note: `Web/${id}.md`, tier: 'primary', excerpts: [], ...extra });
  const rel = (id, n, extra = {}) => ({ id, rank: n, title: '相关' + id, note: `Web/${id}.md`, tier: 'related', excerpt: '', ...extra });
  // 旧会话：10-04 前的 chat-session.json，没有 id、没有历史
  const oldSession = { turns: [{ role: 'user', content: '旧问题', askedAt: '2026-10-02T12:00:00+10:00' }, { role: 'assistant', q: '旧问题', content: '旧回答', sources: [], related: [] }], excluded: [], pinned: [] };
  const V = makeVault({ /* 1015 前的默认（追问绑来源、接着这段问），新默认见 test_chat_b2_1015 */ '_archive/chat-prefs.json': '{"follow":"sources","keepThread":true}', 
    [DATA]: JSON.stringify({ built_at: '2026-10-04T10:00:00+10:00', items: [] }),
    [SESSION]: JSON.stringify(oldSession),
    '_archive/chat-archive.json': JSON.stringify({ entries: [
      { id: 's1', ts: '2026-10-04T09:00:00+10:00', kind: 'report', title: '担担面有没有汤', content: '# 结论\n\n有汤和干拌两种。' },
      { id: 's2', ts: '2026-10-04T08:00:00+10:00', kind: 'note', title: '', content: '做梦是1\n第二行' }] }),
  });
  const asks = [];
  let reply = () => ({ status: 'ok', markdown: '第一轮 [来源1]', related: [rel('c', 3, { excerpt: '相关c 命中那句', excerpt_field: 'comments' }), rel('d', 4)],
    sources: [src('a', 1, { excerpts: [{ field: 'comments', text: '评论里说要加醋', comment_labels: ['c3'] }, { field: 'ocr', text: '图上写着辣度三级', images: ['图2'] }, { field: 'body', text: '第三段不显示' }] }),
              src('saved:s2', 2, { title: '做梦是1', source_kind: 'saved', saved_id: 's2', note: null, excerpts: [{ field: 'saved', text: '做梦是1' }] })] });
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { el.createEl('p', { text: md }); },
    archiveSourceState: () => ({ reader: false, compare: false }),
    async openArchiveSource() {},
    async answerArchive(req) { asks.push(req); return reply(req); },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  let A, dom;
  const open = async () => {
    delete globalThis.__lbState; delete globalThis.__lbListeners;
    dom = makeDom();
    A = dataviewBlock({ dom, app, code: CODE });
    await A.run(); await tick(5);
  };
  const all = s => A.section.querySelectorAll(s);
  const one = s => A.section.querySelector(s);
  const ask = async q => { one('.lbchat-search').value = q; await one('.lbchat-composer').requestSubmit(); await tick(20); };
  const session = () => JSON.parse(V.get(SESSION));
  const index = () => JSON.parse(V.get(INDEX));
  const panel = () => dom.document.querySelector('.lbchat-histpanel');
  const openHistory = async () => { if (panel()) one('.lbchat-hist').onclick({ stopPropagation() {} }); one('.lbchat-hist').onclick({ stopPropagation() {} }); await tick(1); return panel(); };

  // ⑤ 旧会话一打开就补进历史（有了 id），旧数据不丢
  await open();
  const oldId = session().id;
  assert.ok(oldId, '旧会话补上了 id');
  assert.deepEqual(index().conversations.map(c => c.title), ['旧问题']);
  assert.equal(JSON.parse(V.get(`_archive/chat-history/${oldId}.json`)).turns.length, 2);

  // 新问一句 → 自动进历史（同一段对话，目录里 1 条，第一问不变）
  await ask('担担面怎么做');
  assert.equal(index().conversations.length, 1);
  assert.equal(index().conversations[0].turns, 2);

  // ④ 来源行：没有 查看 / 加入对照 / 复制来源；「我保存的」带小标；命中 → 该行下面展开 1–2 段命中原文（带字段身份）
  const turn = () => all('.lbchat-answer').at(-1);
  const rows = () => turn().querySelectorAll('.lbchat-srcrow');
  const rowOf = title => rows().find(r => r.querySelector('a').textContent.includes(title));
  for (const gone of ['查看', '加入对照', '复制来源']) assert.ok(!turn().querySelectorAll('button').some(b => b.textContent === gone), gone);
  assert.equal(rowOf('做梦是1').querySelector('.lbchat-src-kind').textContent, '我保存的');
  assert.equal(rowOf('主要a').querySelector('.lbchat-src-kind'), null);
  const hitBtn = rowOf('主要a').querySelector('.lbchat-src-hitbtn');
  const detail = () => { const kids = rowOf('主要a').parentNode.children; return kids[kids.indexOf(rowOf('主要a')) + 1]; };
  assert.ok(detail().classList.contains('lbchat-src-hit') && detail().hidden, '命中原文默认收着，紧挨在这一行下面');
  hitBtn.onclick(); assert.equal(detail().hidden, false); assert.equal(hitBtn.getAttribute('aria-expanded'), 'true');
  assert.deepEqual(detail().children.map(d => d.textContent), ['评论 c3：评论里说要加醋', '图片文字（识别结果） 图2：图上写着辣度三级'], '最多两段，带楼号 / 图序号');
  hitBtn.onclick(); assert.equal(detail().hidden, true);
  const relDetail = () => { const r = rowOf('相关c'); r.querySelector('.lbchat-src-hitbtn').onclick(); const kids = r.parentNode.children; return kids[kids.indexOf(r) + 1]; };
  assert.equal(relDetail().textContent, '评论：相关c 命中那句');
  assert.equal(rowOf('相关d').querySelector('.lbchat-src-hitbtn'), null, '没有命中原文的不给「命中」');

  // ③ 多选：两个列表都有选中圈；选了出一行操作；取消就收起
  assert.equal(rows().filter(r => r.querySelector('.lbchat-src-check')).length, 4);
  const bulk = () => turn().querySelector('.lbchat-src-bulk');
  assert.equal(bulk().hidden, true);
  rowOf('相关c').querySelector('.lbchat-src-check').onclick({});
  rowOf('主要a').querySelector('.lbchat-src-check').onclick({});
  assert.equal(bulk().hidden, false);
  assert.ok(bulk().textContent.includes('已选 2 条') && bulk().textContent.includes('加入来源') && bulk().textContent.includes('删除'));
  assert.ok(turn().classList.contains('lbchat-selecting'), '有选中时每行都露出圈');
  bulk().querySelectorAll('button').find(b => b.textContent === '取消').onclick();
  assert.equal(bulk().hidden, true); assert.equal(turn().querySelectorAll('.lbchat-src-check.is-on').length, 0);

  // 加入来源：相关c 提为主要依据（新编号）并保留，主要a 也保留；重答按钮写明含手动加入几条
  rowOf('相关c').querySelector('.lbchat-src-check').onclick({});
  rowOf('主要a').querySelector('.lbchat-src-check').onclick({});
  await bulk().querySelectorAll('button').find(b => b.textContent === '加入来源').onclick(); await tick(5);
  let s = session();
  assert.deepEqual(s.pinned, ['c', 'a']);
  const t1 = s.turns[3];
  assert.deepEqual(t1.sources.map(x => [x.id, x.citation]), [['a', 1], ['saved:s2', 2], ['c', 3]]);
  assert.deepEqual(t1.related.map(x => x.id), ['d']);
  assert.ok(rowOf('[来源3] 相关c'), '提上来的进了主要依据');
  const redo = () => turn().querySelectorAll('.lbchat-src-redo button')[0];
  assert.equal(redo().textContent, '加入后重新回答（4 条，含手动加入 1 条）');

  // ② 重答：sourceIds 里加入的排最前，pinIds 一并带上（后端据此排最前、给足证据、逐条用到）
  reply = () => ({ status: 'ok', markdown: '重答 [来源1][来源2]', sources: [src('c', 1), src('a', 2)], related: [] });
  await redo().onclick(); await tick(20);
  const last = asks.at(-1);
  assert.deepEqual(Array.from(last.sourceIds).slice(0, 2), ['c', 'a']);
  assert.deepEqual(Array.from(last.pinIds), ['c', 'a']);

  // 多选删除（主要依据里的）：进本会话排除，可恢复
  rowOf('主要a').querySelector('.lbchat-src-check').onclick({});
  await bulk().querySelectorAll('button').find(b => b.textContent === '删除').onclick(); await tick(5);
  s = session();
  assert.deepEqual(s.excluded, ['a']); assert.deepEqual(s.pinned, ['c']);
  assert.ok(turn().querySelectorAll('.lbchat-src-redo button').some(b => b.textContent === '恢复删掉的 1 条'));

  // ⑥ 已保存：每条只一行标题（回答 = 提问原话；判断 = 第一行），默认收起；点开才看到正文
  await one('.lbchat-tab:not(.is-on)').onclick(); await tick(5);
  const items = all('.lbchat-arc-item');
  assert.equal(items.length, 2);
  assert.deepEqual(items.map(i => i.querySelector('.lbchat-arc-title').textContent), ['担担面有没有汤', '做梦是1']);
  assert.ok(items.every(i => i.tagName === 'DETAILS' && !i.open && i.getAttribute('open') === null), '默认收起');
  assert.equal(items[0].querySelector('summary').textContent.includes('有汤和干拌'), false, '收起时一行里没有正文');
  await all('.lbchat-tab').find(b => b.textContent === '对话').onclick(); await tick(5);

  // ⑤ 清空 = 开一段新对话（不确认），旧的那段还在历史里
  const firstId = session().id;
  await one('.lbchat-clearall').onclick(); await tick(5);
  assert.notEqual(session().id, firstId); assert.equal(session().turns.length, 0);
  assert.ok(V.get(`_archive/chat-history/${firstId}.json`));
  await ask('悉尼咖啡');
  assert.equal(index().conversations.length, 2);

  // 历史面板：按天分组（日期 + 周几），每行 = 第一问 + 时间；当前那段标「当前」
  let p = await openHistory();
  assert.ok(p, '时钟点开 = 历史面板');
  const days = p.querySelectorAll('.lbchat-histday').map(d => d.textContent);
  assert.ok(days.every(d => /^\d{4}-\d{2}-\d{2} 周[日一二三四五六]$/.test(d)), days.join('|'));
  assert.ok(days.includes('2026-10-02 周五'), '旧会话按它第一问那天分组');
  const titles = () => panel().querySelectorAll('.lbchat-histq').map(b => b.textContent);
  assert.deepEqual(titles(), ['悉尼咖啡', '旧问题']);
  assert.ok(panel().querySelector('.lbchat-histitem.is-current').textContent.includes('当前'));
  assert.match(panel().querySelector('.lbchat-histtime').textContent, /^\d{2}:\d{2}$/);

  // 点一行恢复那段对话（当前这段已在历史里）
  await panel().querySelectorAll('.lbchat-histq').find(b => b.textContent === '旧问题').onclick(); await tick(5);
  assert.equal(session().id, firstId);
  assert.equal(panel(), null, '恢复后面板收起');
  assert.ok(A.section.textContent.includes('旧回答') && A.section.textContent.includes('重答'));
  assert.deepEqual(session().excluded, ['a'], '会话级排除 / 保留一起恢复');

  // 多选删除：选中「悉尼咖啡」那段 → 删除；删的是记录
  p = await openHistory();
  const rowCheck = t => panel().querySelectorAll('.lbchat-histitem').find(r => r.textContent.includes(t)).querySelector('.lbchat-histcheck');
  rowCheck('悉尼咖啡').onclick({});
  assert.ok(panel().querySelector('.lbchat-histbar').textContent.includes('已选 1 段'));
  const goneId = index().conversations.find(c => c.title === '悉尼咖啡').id;
  await panel().querySelectorAll('.lbchat-histbar button').find(b => b.textContent === '删除').onclick(); await tick(5);
  assert.deepEqual(index().conversations.map(c => c.title), ['旧问题']);
  assert.equal(V.get(`_archive/chat-history/${goneId}.json`), undefined, '对话文件也删了');
  assert.equal(session().id, firstId, '删的不是当前这段：页面不动');

  // 删到当前这段：页面换成新对话
  rowCheck('旧问题').onclick({});
  await panel().querySelectorAll('.lbchat-histbar button').find(b => b.textContent === '删除').onclick(); await tick(5);
  assert.deepEqual(index().conversations, []);
  assert.equal(session().turns.length, 0);

  // 隐私模式：开着时问答不进历史；时钟旁出现「隐私模式」小字；关掉时这一段存进历史
  p = await openHistory();
  const priv = panel().querySelector('.lbchat-histpriv input');
  priv.checked = true; await priv.onchange(); await tick(5);
  assert.equal(session().private, true);
  assert.equal(one('.lbchat-privtag').hidden, false);
  await ask('不想留记录的问题');
  assert.deepEqual(index().conversations, [], '隐私模式下不进历史');
  assert.equal(session().turns.length, 2, '当前页面照样留着（换页回来还在）');
  // 隐私模式是开关：清空后的新一段也还是隐私
  await one('.lbchat-clearall').onclick(); await tick(5);
  assert.equal(session().private, true); assert.deepEqual(index().conversations, []);
  await ask('还是隐私');
  p = await openHistory();
  const priv2 = panel().querySelector('.lbchat-histpriv input');
  priv2.checked = false; await priv2.onchange(); await tick(5);
  assert.equal(session().private, false); assert.equal(one('.lbchat-privtag').hidden, true);
  assert.deepEqual(index().conversations.map(c => c.title), ['还是隐私'], '关掉隐私模式：当前这段存进历史');
  // 再开：这段从历史里拿掉
  const priv3 = panel().querySelector('.lbchat-histpriv input');
  priv3.checked = true; await priv3.onchange(); await tick(5);
  assert.deepEqual(index().conversations, []);

  // 写盘失败（历史目录写不进）：清空不换对话，提示原因
  priv3.checked = false; await priv3.onchange(); await tick(5);
  const write = V.vault.adapter.write;
  V.vault.adapter.write = async (p2, x) => { if (p2.startsWith('_archive/chat-history/')) throw new Error('磁盘满'); return write(p2, x); };
  const keepId = session().id;
  await one('.lbchat-clearall').onclick(); await tick(5);
  assert.equal(session().id, keepId, '没存进历史就不清');
  assert.ok(A.notices.some(n => String(n).includes('磁盘满')));
  V.vault.adapter.write = write;

  console.log('PASS chat ui2 1004: multi-select both lists → 加入来源 (related→primary + pinned, pinIds on reask) / 删除 / 取消, rows without 查看/加入对照/复制来源, 命中 expands 1–2 excerpts with field identity, 我保存的 tag, 已保存 collapsed to title, 清空 = new conversation (history kept), history panel grouped by day + restore + multi-delete, privacy mode keeps out of history, old session migrated');
})().catch(e => { console.error(e); process.exit(1); });

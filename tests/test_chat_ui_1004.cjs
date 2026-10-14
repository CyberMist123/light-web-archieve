// 10-04 问收藏页界面批（她点名）：
// ① 标题旁「+」换成「清空」（输入框左边的 + 照旧开导入菜单）
// ② 追问默认绑定上一轮「留下的来源」（sourceIds 通路，不重新检索）；「改为重新搜」开关存进 chat-session.json；新会话 / 清空后 / 从目录页带词跳来的第一问照常检索
// ③ 对话区内滚动条隐藏（仍可滚）  ④ dataviewjs 外框隐形  ⑥ 来源入口看得见（收起时小字提示，展开后保留 / × 小按钮）
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';
const SESSION = '_archive/chat-session.json';
const CODE = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js');

(async () => {
  const src = (id, n) => ({ id, citation: n, title: '主要' + id, note: `Web/${id}.md`, tier: 'primary', excerpts: [] });
  const rel = (id, n) => ({ id, rank: n, title: '相关' + id, note: `Web/${id}.md`, tier: 'related', excerpt: '' });
  const V = makeVault({ /* 1015 前的默认（追问绑来源、接着这段问），新默认见 test_chat_b2_1015 */ '_archive/chat-prefs.json': '{"follow":"sources","keepThread":true}',  [DATA]: JSON.stringify({ built_at: '2026-10-04T10:00:00+10:00', items: [] }), '_archive/chat-archive.json': '{"entries":[]}' });
  const asks = [], menus = [];
  let reply = () => ({ status: 'ok', markdown: '第一轮 [来源1]', sources: [src('a', 1), src('b', 2)], related: [rel('c', 3)] });
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (md, el) => { el.createEl('p', { text: md }); },
    archiveSourceState: () => ({ reader: false, compare: false }),
    async openArchiveSource() {},
    openPlusMenu: () => menus.push('plus'),
    async answerArchive(req) { asks.push(req); return reply(req); },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  let A, DOM;
  const open = async () => {
    delete globalThis.__lbState; delete globalThis.__lbListeners;
    DOM = makeDom(); A = dataviewBlock({ dom: DOM, app, code: CODE });
    A.window.confirm = () => true;
    await A.run();
  };
  const all = s => A.section.querySelectorAll(s);
  const one = s => A.section.querySelector(s);
  const ask = async q => { one('.lbchat-search').value = q; await one('.lbchat-composer').requestSubmit(); await tick(20); };
  const saved = () => JSON.parse(V.get(SESSION));

  await open();
  // ① 标题旁的「+」去掉了（标题里也没有「清空」）；没对话时那行小字和「清空」都不出；输入框左边的 + 还在、还是导入菜单
  assert.equal(all('.lbchat-plus').length, 0);
  assert.equal(one('.lbchat-titlerow').querySelectorAll('button').length, 0);
  assert.equal(all('.lbchat-clearall').length, 0);
  const clear = { get disabled() { return one('.lbchat-followbar .lbchat-clearall').disabled; } };
  one('.lbchat-cplus').onclick({});
  assert.deepEqual(menus, ['plus']);
  // ④ ③ 样式：dataviewjs 外框隐形（阅读 + 实时预览、悬停编辑按钮），对话区不画滚动条
  const css = (DOM.document.getElementById('lbchat-style') || one('style')).textContent;   // 10-04 晚：样式挪进 document.head
  assert.ok(css.includes('.lb-chatpage,.lb-catalog,.lb-trashpage') && css.includes('.cm-embed-block:has(.block-language-dataviewjs)') && css.includes('.edit-block-button{display:none!important;}'));
  assert.ok(/\.lbchat \.lbchat-body,[^{]*\{scrollbar-width:none;\}/.test(css) && css.includes('.lbchat .lbchat-body::-webkit-scrollbar'));

  // ② 新会话第一问：照常检索（不带 sourceIds），还没有绑定那一行
  assert.equal(one('.lbchat-followbar').hidden, true);
  await ask('日本有什么好吃的');
  assert.equal(asks.length, 1);
  assert.equal(asks[0].sourceIds, undefined);
  assert.equal(clear.disabled, false);
  // 答完：输入框上面出现「在当前 3 条来源里追问 · 改为重新搜」
  const bar = one('.lbchat-followbar');
  assert.equal(bar.hidden, false);
  assert.ok(bar.textContent.includes('在当前 3 条来源里追问') && bar.textContent.includes('改为重新搜'));
  assert.equal(bar.querySelector('.lbchat-clearall').textContent, '清空', '「清空」在来源那行小字旁边');
  assert.equal(one('.lbchat-search').placeholder, '在当前来源里继续追问…');

  // ⑥ 来源入口：收起时 summary 后面有提示小字；每行 标题 + 保留 + × 在同一行里
  const box = () => all('.lbchat-src')[all('.lbchat-src').length - 2];
  assert.ok(box().querySelector('summary').textContent.includes('点开可多选 / 保留 / 删除来源'));
  assert.equal(box().getAttribute('open'), null, '来源默认仍收起');
  const rowOf = title => all('.lbchat-srcrow').filter(r => r.querySelector('a').textContent.includes(title)).pop();
  assert.ok(rowOf('主要a').querySelector('.lbchat-src-pin') && rowOf('主要a').querySelector('.lbchat-src-del'));
  // 保留 b、删掉 a → summary 上看得到「已保留 1」，按钮变「已保留」
  await rowOf('主要b').querySelector('.lbchat-src-pin').onclick(); await tick(5);
  assert.equal(rowOf('主要b').querySelector('.lbchat-src-pin').textContent, '已保留');
  assert.ok(rowOf('主要b').querySelector('.lbchat-src-pin').classList.contains('is-on'));
  assert.ok(box().querySelector('summary').textContent.includes('已保留 1'));
  await rowOf('主要a').querySelector('.lbchat-src-del').onclick(); await tick(5);

  // 追问：只在上一轮留下的来源里答（保留的 b 排前，删掉的 a 不要）；排除照样带上；10-04 ②：保留的 b 也作为 pinIds 带上
  reply = () => ({ status: 'ok', markdown: '只看留下的 [来源1]', sources: [src('b', 1)], related: [rel('c', 2)] });
  await ask('哪家最便宜');
  assert.deepEqual(Array.from(asks[1].sourceIds), ['b', 'c']);
  assert.deepEqual(Array.from(asks[1].excludeIds), ['a']);
  assert.deepEqual(Array.from(asks[1].pinIds), ['b']);
  assert.equal(asks[1].history.length, 2, '追问照样带上一轮对话');
  let turns = saved().turns;
  assert.equal(turns[2].mode, 'follow');
  assert.equal(turns[2].sources, 2);
  assert.ok(A.section.textContent.includes('在当前 2 条来源里追问'));

  // 改为重新搜：下一问重新检索（不带 sourceIds，带会话的排除 / 保留），状态存进会话文件
  await one('.lbchat-follow-switch').onclick(); await tick(5);
  assert.equal(saved().follow, 'search');
  assert.ok(one('.lbchat-followbar').textContent.includes('下一问重新搜收藏') && one('.lbchat-followbar').textContent.includes('改为在当前'));
  assert.equal(one('.lbchat-search').placeholder, '继续追问…');
  await ask('换个城市呢');
  assert.equal(asks[2].sourceIds, undefined);
  assert.deepEqual(Array.from(asks[2].pinIds), ['b']);
  assert.equal(saved().turns[4].mode, 'ask');

  // 刷新页面：开关状态还在；改回当前来源
  await open();
  assert.ok(one('.lbchat-follow-switch').textContent.startsWith('改为在当前'));
  await one('.lbchat-follow-switch').onclick(); await tick(5);
  assert.equal(saved().follow, 'sources');

  // 停掉的回答不算「上一轮」：绑到之前那条没失败的
  reply = () => ({ status: 'cancelled', markdown: '半截', sources: [src('z', 1)], related: [] });
  await ask('停一下');
  reply = () => ({ status: 'ok', markdown: 'ok', sources: [src('b', 1)], related: [] });
  await ask('接着问');
  assert.ok(!Array.from(asks[4].sourceIds).includes('z'));

  // ① ⑤ 「清空」（10-04 改）：不弹确认、不删记录——当前页面换成一段新对话（轮次、排除、保留清掉，开关回到默认）；清空后第一问照常检索
  A.window.confirm = () => { throw new Error('清空不该再弹确认'); };
  const oldId = saved().id;
  await one('.lbchat-clearall').onclick(); await tick(5);
  assert.notEqual(saved().id, oldId, '换了一段新对话');
  assert.ok(V.get('_archive/chat-history/' + oldId + '.json'), '旧的那段还在历史里');
  const after = saved();
  assert.deepEqual(after.turns, []); assert.deepEqual(after.excluded, []); assert.deepEqual(after.pinned, []);
  assert.equal(after.follow, 'sources');
  assert.equal(all('.lbchat-clearall').length, 0);
  assert.equal(one('.lbchat-followbar').hidden, true);
  await ask('新话题');
  assert.equal(asks.at(-1).sourceIds, undefined);
  assert.equal(asks.at(-1).excludeIds, undefined);

  // 从目录页带词跳过来的那一问（pendingArchiveQuestion）：是新问题，照常检索，不绑上一轮
  plugin.pendingArchiveQuestion = '悉尼咖啡';
  const before = asks.length;
  await open(); await tick(20);
  assert.equal(asks.length, before + 1);
  assert.equal(asks.at(-1).question, '悉尼咖啡');
  assert.equal(asks.at(-1).sourceIds, undefined);
  // 之后手打的追问又按默认绑定
  await ask('再说说');
  assert.ok(Array.isArray(asks.at(-1).sourceIds));

  console.log('PASS chat 1004: title + removed, 清空 beside the source line above the composer (no confirm, new conversation, old one kept in history, resets follow), composer + unchanged, follow-up bound to kept sources by default (pinned first, removed dropped, stopped answers skipped), 改为重新搜 persisted, fresh after clear / catalog jump, source rows show 保留 / × with hint, scrollbar + block frame CSS');
})().catch(e => { console.error(e); process.exit(1); });

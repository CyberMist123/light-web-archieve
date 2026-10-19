// 1015 第二批「chat」车：问收藏前端。
//   ① 默认每问重新搜 + 每问开新对话（上一段先进历史）；「接着这段」偏好存 _archive/chat-prefs.json；隐私模式不自动清
//   ② 「展开」绑那一答自己：turnId（后端给的 turn_id，没有就用本地轮次 id）+ 来源 id；只带那一答当上下文；不受「每问新开」影响
//   ③ 先目录后展开：mode='toc' + toc 列表 → 目录卡（序号 / 标题 / 作者 / 命中点 / 来源类型），逐条展开 / 全部展开，展开过的变「已展开 ↓」；
//      后端没给 toc / mode='direct' → 照原样渲染（兼容兜底）
//   ④ 目录（左栏 / 弹出层）1 问也出（回答有目录卡或 ≥2 小标题）；窄窗 / 收起后有「☰ 目录」点回来
//   ⑤ 右栏来源视频首图（poster 按笔记目录解析）
//   ⑥ 「存一条判断」Enter 入站、作者、× 在标题行可删
//   ⑦ mermaid 视口：＋ / － / 复位 / 放大看
'use strict';
const assert = require('node:assert/strict');
const { tick, src, rel, makePlugin, openChat } = require('./_fake_L2.cjs');

const TOC = [
  { id: 'a', title: '辣味鱼片', author: '作者甲', hit: '评论区说加一勺郫县豆瓣', source_type: 'comments' },
  { id: 'b', title: '麻辣香锅', author: '作者乙', hit: '正文：花椒先炸', source_type: ['body', 'ocr'], price: '$5', where: 'Coles' },
  { id: 'c', title: '水煮牛肉', author: '作者丙', hit: '视频里讲火候', source_type: 'transcript' },
];

(async () => {
  // ── ① 新默认 ──
  {
    const P = makePlugin();
    const C = await openChat({ plugin: P, prefs: null });
    await C.ask('担担面有没有汤');
    const first = C.saved().id;
    const seg = (CC, label) => CC.qa('.lbchat-followmode .lbchat-seg-opt').find(b => b.textContent === label);
    // 1020：输入框上方一个开关「追问 · 新对话」，默认新对话；不再有「改为……」和「接着这段」
    assert.ok(seg(C, '新对话').classList.contains('is-on'), '默认新对话（重新搜）');
    assert.ok(!seg(C, '追问').classList.contains('is-on'));
    assert.equal(C.q('.lbchat-keepthread'), null);
    assert.equal(C.q('.lbchat-clearall').textContent, '清空上下文');
    await C.ask('麻婆豆腐怎么做');
    assert.equal(P.calls.asks[1].sourceIds, undefined, '第二问重新检索，不绑上一答来源');
    assert.deepEqual(P.calls.asks[1].history, [], '新对话：不带上一段的历史');
    const s = C.saved();
    assert.notEqual(s.id, first, '开了新对话');
    assert.deepEqual(s.turns.map(t => t.role), ['user', 'assistant']);
    const hist = JSON.parse(C.V.get(C.INDEX));
    assert.ok(hist.conversations.some(c => c.id === first), '上一段进了历史');
    assert.equal(C.qa('.lbchat-user').length, 1, '页面上只剩这一问');
    // 点「追问」：followPicked 记在会话里；下一问留在这段、带历史、只在上一答的来源里答
    await seg(C, '追问').onclick(); await tick(5);
    assert.equal(C.saved().follow, 'sources'); assert.equal(C.saved().followPicked, true);
    await C.ask('辣不辣');
    assert.equal(C.saved().id, s.id);
    assert.equal(C.saved().turns.length, 4);
    assert.equal(P.calls.asks[2].history.length, 2);
    assert.deepEqual(Array.from(P.calls.asks[2].sourceIds), ['a', 'b', 'c', 'd']);
    // 重开页面：她点过的追问开关还在；新对话回到默认
    const C2 = await openChat({ plugin: P, prefs: null, V: C.V });
    assert.ok(seg(C2, '追问').classList.contains('is-on'));
    // 老会话（1015 前默认存的 follow:'sources'、没 followPicked）→ 按新默认重新搜
    const C3 = await openChat({ prefs: null, session: { id: 'old', turns: [{ id: 'u', role: 'user', content: 'x' }, { id: 'v', role: 'assistant', content: 'y', q: 'x', sources: [src('a', 1)] }], follow: 'sources' } });
    assert.ok(seg(C3, '新对话').classList.contains('is-on'));
    // 失败后「重试」是同一问：不因每问新开清掉（新问题先开新对话，失败；重试留在同一段）
    const P5 = makePlugin();
    const C5 = await openChat({ plugin: P5, prefs: null });
    await C5.ask('第一问');
    P5.plugin.reply = () => Object.assign(new Error('x'), { kind: 'api', code: 'TRANSIENT.HTTP_429' });
    await C5.ask('第二问');
    const sid = C5.saved().id;
    P5.plugin.reply = req => ({ status: 'ok', markdown: '好了', sources: [], related: [] });
    await C5.qa('.lbchat-retry')[0].onclick(); await tick(20);
    assert.equal(C5.saved().id, sid); assert.deepEqual(C5.saved().turns.map(t => t.content), ['第二问', '好了']);
    // 隐私模式：不自动清（清了找不回），也不显示「每问新开」开关
    const C4 = await openChat({ prefs: null, session: { id: 'p', private: true, turns: [] } });
    await C4.ask('一'); await C4.ask('二');
    assert.equal(C4.saved().id, 'p'); assert.equal(C4.saved().turns.length, 4);
    assert.equal(C4.q('.lbchat-keepthread'), null);
  }

  // ── ② 展开绑那一答 ──
  {
    const P = makePlugin();
    P.plugin.reply = req => ({ status: 'ok', markdown: '答：' + req.question + ' [来源1]', sources: [src('a', 1), src('b', 2)], related: [rel('c', 3)], turn_id: 'T-' + P.calls.asks.length });
    const C = await openChat({ plugin: P, prefs: null });
    await C.ask('辣椒酱哪家好');
    const btn = C.answers()[0].querySelectorAll('.lbchat-act').find(b => b.textContent === '展开细节');
    assert.ok(btn, '普通回答有「展开细节」');
    assert.equal(C.answers()[0].querySelectorAll('.lbchat-act').find(b => b.textContent === '展开重点细节'), undefined, '固定话术按钮没了');
    await btn.onclick(); await tick(20);
    const req = P.calls.asks[1];
    assert.equal(req.turnId, 'T-1');
    assert.deepEqual(Array.from(req.expandIds), ['a', 'b']);
    assert.deepEqual(Array.from(req.sourceIds), ['a', 'b'], '老后端也只在这两篇里答');
    assert.ok(req.question.includes('辣椒酱哪家好'), '带原问题，不会被当成新话题');
    assert.equal(req.history.length, 2); assert.equal(req.history[0].content, '辣椒酱哪家好');
    const s = C.saved();
    assert.equal(s.turns.length, 4, '展开不开新对话');
    assert.equal(s.turns[2].mode, 'expand');
    assert.ok(C.qa('.lbchat-user')[1].textContent.includes('展开 · 2 条来源'));
    // 删了 b 再展开：只带留下的
    C.rowOf('主要b', C.answers()[0]).querySelector('.lbchat-src-del').onclick(); await tick(10);
    C.answers()[0].querySelectorAll('.lbchat-act').find(b => b.textContent === '展开细节').onclick(); await tick(20);
    assert.deepEqual(Array.from(P.calls.asks[2].expandIds), ['a']);
    // 没有 turn_id 的老后端：用本地轮次 id
    P.plugin.reply = req => ({ status: 'ok', markdown: '老后端', sources: [src('x', 1)], related: [] });
    await C.ask('另一问');   // 开新对话
    C.answers()[0].querySelectorAll('.lbchat-act').find(b => b.textContent === '展开细节').onclick(); await tick(20);
    assert.equal(P.calls.asks[4].turnId, C.saved().turns[1].id);
  }

  // ── ③ 先目录后展开 + ④ 目录 ──
  {
    const P = makePlugin();
    P.plugin.reply = req => (req.expandIds ? { status: 'ok', markdown: '## 辣味鱼片\n\n细节 [来源1]', sources: [src('a', 1)], related: [] }
      : { status: 'ok', mode: 'toc', turn_id: 'T9', markdown: '收藏里的辣味菜（3 篇）', toc: TOC, source_ids: ['a', 'b', 'c'], coverage_note: '共检到 5 篇，展示 3', suggest: '搜「川菜 家常」',
        sources: [src('a', 1), src('b', 2)], related: [rel('c', 3)] });
    const C = await openChat({ plugin: P, prefs: null });
    await C.ask('我要吃辣的');
    const ans = C.answers()[0];
    const card = ans.querySelector('.lbchat-tocard');
    assert.ok(card, '目录卡');
    assert.ok(card.querySelector('.lbchat-tocard-title').textContent.includes('目录 · 3 条'));
    assert.ok(card.textContent.includes('共检到 5 篇，展示 3') && card.textContent.includes('可补：搜「川菜 家常」'));
    const items = card.querySelectorAll('.lbchat-tocard-item');
    assert.equal(items.length, 3);
    assert.equal(items[0].querySelector('.lbchat-tocard-name').textContent, '辣味鱼片');
    assert.equal(items[0].querySelector('.lbchat-tocard-author').textContent, '作者甲');
    assert.deepEqual(items[0].querySelectorAll('.lbchat-tocard-kind').map(x => x.textContent), ['评论']);
    assert.deepEqual(items[1].querySelectorAll('.lbchat-tocard-kind').map(x => x.textContent), ['正文', '图片文字']);
    assert.ok(items[1].querySelector('.lbchat-tocard-hit').textContent.includes('价格：$5') && items[1].textContent.includes('哪买：Coles'));
    assert.deepEqual(items[2].querySelectorAll('.lbchat-tocard-kind').map(x => x.textContent), ['视频文字稿']);
    assert.equal(ans.querySelectorAll('.lbchat-act').find(b => b.textContent === '展开细节'), undefined, '目录型回答不给整答「展开细节」');
    const saved0 = C.saved().turns[1];
    assert.equal(saved0.answerMode, 'toc'); assert.equal(saved0.turnId, 'T9'); assert.deepEqual(saved0.sourceIds, ['a', 'b', 'c']);
    // 标题点开来源（右侧）
    items[2].querySelector('.lbchat-tocard-name').onclick(); await tick(5);
    assert.deepEqual(P.calls.opened, ['Web/c.md']);
    // ④ 1 问也有目录（回答是目录卡）：窄窗 → 页头按钮 + 左上「☰ 目录」；弹出层里有条目
    const peek = C.q('.lbchat-tocbtn');
    assert.equal(peek.hidden, false, '1 问（目录型回答）窄窗也有目录按钮');
    assert.equal(peek.textContent, '目录');
    peek.onclick({ stopPropagation() {} });
    const panel = C.dom.document.querySelector('.lbchat-tocpanel');
    assert.ok(panel, '点「☰ 目录」弹出');
    assert.deepEqual(panel.querySelectorAll('.lbchat-toc-item').map(b => b.getAttribute('title')), ['辣味鱼片', '麻辣香锅', '水煮牛肉']);
    peek.onclick({ stopPropagation() {} });
    // 单条展开：turn_id + 这一条的 id
    items[0].querySelector('.lbchat-tocard-expand').onclick(); await tick(20);
    const req = P.calls.asks[1];
    assert.equal(req.turnId, 'T9'); assert.deepEqual(Array.from(req.expandIds), ['a']);
    assert.ok(req.question.includes('辣味鱼片') && req.question.includes('我要吃辣的'));
    const again = C.answers()[0].querySelectorAll('.lbchat-tocard-expand');
    assert.equal(again[0].textContent, '已展开 ↓'); assert.equal(again[1].textContent, '展开');
    assert.deepEqual(Object.keys(C.saved().turns[1].expanded), ['a'], '展开记录存盘');
    // 全部展开
    C.answers()[0].querySelector('.lbchat-tocard-all').onclick(); await tick(20);
    assert.deepEqual(Array.from(P.calls.asks[2].expandIds), ['a', 'b', 'c']);
    assert.equal(C.saved().turns.length, 6, '展开都接在这段里');
    // 宽窗：左栏；收起后「☰ 目录」点了放回来
    const wrapEl = C.q('.lbchat-bodywrap');
    wrapEl.clientWidth = 1150; C.A.resize.trigger(1150, 800); await tick(5);
    assert.ok(wrapEl.classList.contains('is-wide') && wrapEl.classList.contains('is-tight'), '1080–1242 也有左栏，对话列让位');
    assert.equal(C.q('.lbchat-toc').hidden, false);
    C.q('.lbchat-toc-fold').onclick();
    assert.equal(C.q('.lbchat-toc').hidden, true); assert.equal(C.q('.lbchat-tocbtn').hidden, false);
    C.q('.lbchat-tocbtn').onclick({ stopPropagation() {} });
    C.dom.document.querySelector('.lbchat-tocpanel .lbchat-toc-fold').onclick();   // 弹出层里「固定在左边」
    assert.equal(C.q('.lbchat-toc').hidden, false, '收起可恢复');
  }
  // 兼容兜底：没给 toc / mode=direct / toc 是空的 → 照原样渲染，没有目录卡；groups 形状也认
  {
    for (const extra of [{}, { mode: 'direct', toc: TOC }, { mode: 'toc', toc: [] }, { mode: 'toc', toc: 'bad' }]) {
      const P = makePlugin();
      P.plugin.reply = () => ({ status: 'ok', markdown: '普通回答 [来源1]', sources: [src('a', 1)], related: [], ...extra });
      const C = await openChat({ plugin: P, prefs: null });
      await C.ask('q');
      assert.equal(C.answers()[0].querySelector('.lbchat-tocard'), null, JSON.stringify(extra));
      assert.ok(C.answers()[0].querySelectorAll('.lbchat-act').find(b => b.textContent === '展开细节'));
    }
    const P = makePlugin();
    P.plugin.reply = () => ({ status: 'ok', mode: 'toc', toc: { groups: [{ name: '家常菜', items: [{ n: 1, name: '辣味鱼片', src: 'a', author: 'xx', line: '一句' }] }] }, markdown: '', sources: [src('a', 1)], related: [] });
    const C = await openChat({ plugin: P, prefs: null });
    await C.ask('q');
    const card = C.answers()[0].querySelector('.lbchat-tocard');
    assert.equal(card.querySelector('.lbchat-tocard-group').textContent, '家常菜');
    assert.equal(card.querySelector('.lbchat-tocard-item').dataset.id, 'a');
    assert.equal(card.querySelector('.lbchat-tocard-hit').textContent, '一句');
  }

  // ── ⑤ 右栏视频首图 ──
  {
    const P = makePlugin();
    const C = await openChat({ plugin: P, prefs: null });
    const pane = C.dom.document.body.createEl('div');
    const v = pane.createEl('video'); v.setAttribute('poster', '../_archive/xiaohongshu/a/raw/v0001/cover%201.jpg');
    const ok = pane.createEl('video'); ok.setAttribute('poster', 'app://already');
    P.plugin.archiveLeaves = () => ({ reader: { view: { containerEl: pane } }, compare: null });
    await C.ask('q');
    C.rowOf('主要a').querySelector('a').onclick(); await tick(10);
    assert.equal(v.getAttribute('poster'), 'app://_archive/xiaohongshu/a/raw/v0001/cover 1.jpg', 'poster 按笔记目录解析');
    assert.equal(v.preload, 'none');
    assert.equal(ok.getAttribute('poster'), 'app://already');
    C.rowOf('主要a').querySelector('a').onclick(); await tick(10);
    assert.equal(v.getAttribute('poster'), 'app://_archive/xiaohongshu/a/raw/v0001/cover 1.jpg', '幂等');
  }

  // ── ⑥ 存一条判断 ──
  {
    const C = await openChat({ prefs: null });
    await C.qa('.lbchat-tab').find(t => t.textContent === '已保存').onclick(); await tick(5);
    const ta = C.q('.lbchat-arc-input'), who = C.q('.lbchat-arc-author');
    ta.value = 'ib 机不适合';
    who.value = '作者甲';
    ta.fire('keydown', { key: 'Enter', isComposing: true }); await tick(10);
    assert.equal(JSON.parse(C.V.get(C.ARCHIVE)).entries.length, 0, '组字中的 Enter 不存');
    ta.fire('keydown', { key: 'Enter', shiftKey: true }); await tick(10);
    assert.equal(JSON.parse(C.V.get(C.ARCHIVE)).entries.length, 0, 'Shift+Enter 换行');
    ta.fire('keydown', { key: 'Enter' }); await tick(20);
    let entries = JSON.parse(C.V.get(C.ARCHIVE)).entries;
    assert.equal(entries.length, 1); assert.equal(entries[0].author, '作者甲'); assert.equal(entries[0].kind, 'note');
    assert.equal(C.q('.lbchat-arc-input').value, '', '存了清框');
    assert.equal(C.q('.lbchat-arc-author').value, '作者甲', '作者记住');
    const item = C.q('.lbchat-arc-item');
    assert.equal(item.querySelector('.lbchat-arc-who').textContent, '作者甲');
    assert.ok(item.querySelector('.lbchat-arc-meta').textContent.includes('判断 · 作者甲'));
    // 作者空 = 我
    C.q('.lbchat-arc-author').value = ''; C.q('.lbchat-arc-input').value = '第二条';
    C.q('.lbchat-arc-input').fire('keydown', { key: 'Enter' }); await tick(20);
    entries = JSON.parse(C.V.get(C.ARCHIVE)).entries;
    assert.equal(entries[0].author, '我');
    // × 在标题行：点了删、不展开
    const del = C.q('.lbchat-arc-head .lbchat-arc-del');
    assert.ok(del, '× 在标题行');
    let stopped = false;
    await del.onclick({ preventDefault() {}, stopPropagation() { stopped = true; } }); await tick(10);
    assert.ok(stopped);
    assert.equal(JSON.parse(C.V.get(C.ARCHIVE)).entries.length, 1);
  }

  // ── ⑦ mermaid 视口 ──
  {
    const P = makePlugin({ renderMarkdownScoped: (m, el) => { const box = el.createEl('div', { cls: 'mermaid' }); box.createEl('svg'); el.createEl('p', { text: m }); return { dispose() {} }; } });
    const C = await openChat({ plugin: P, prefs: null });
    await C.ask('画个图');
    const vp = C.answers()[0].querySelector('.lbchat-mmd');
    assert.ok(vp, '套了视口');
    assert.ok(vp.querySelector('.lbchat-mmd-stage .mermaid svg'));
    const btns = vp.querySelectorAll('.lbchat-mmd-btn').map(b => b.textContent);
    assert.deepEqual(btns, ['＋', '－', '复位', '放大看']);
    const stage = vp.querySelector('.lbchat-mmd-stage');
    vp.querySelectorAll('.lbchat-mmd-btn')[0].onclick({ stopPropagation() {} });
    assert.ok(stage.style.transform.includes('scale(1.25)'));
    assert.ok(vp.classList.contains('is-moved'));
    vp.querySelectorAll('.lbchat-mmd-btn')[2].onclick({ stopPropagation() {} });
    assert.ok(stage.style.transform.includes('scale(1)') && !vp.classList.contains('is-moved'));
    vp.querySelectorAll('.lbchat-mmd-btn')[3].onclick({ stopPropagation() {} });
    assert.ok(vp.classList.contains('is-full'));
    assert.equal(vp.querySelectorAll('.lbchat-mmd-btn')[3].textContent, '退出');
    assert.equal(C.answers()[0].querySelectorAll('.lbchat-mmd').length, 1, '只包一次');
  }

  // 样式表括号配平（1015 一次清理留下半截 @media，把后面的规则全吞进窄屏里）
  {
    const css = require('fs').readFileSync(require('path').join(__dirname, '..', 'link_brain', 'assets', 'chat-view.js'), 'utf8').split("LB.style('lbchat-style', `")[1].split('`);')[0].replace(/\/\*[\s\S]*?\*\//g, '');
    let d = 0; for (const c of css) { if (c === '{') d++; if (c === '}') d--; assert.ok(d >= 0 && d <= 2, 'CSS 括号'); }
    assert.equal(d, 0, 'CSS 括号配平');
  }
  console.log('PASS chat b2 1015: 默认每问重新搜 + 每问开新对话（上一段进历史，偏好可改、隐私不清）；展开绑那一答 turn_id + 来源 id（老后端 sourceIds 兜底、本地 id 兜底）；目录卡逐条 / 全部展开 + 已展开；无 toc 照旧；1 问也有目录、窄窗有目录按钮 / 收起后「固定在左边」可恢复；右栏视频 poster；判断 Enter 存 + 作者 + 标题行删除；mermaid 缩放视口');
})().catch(e => { console.error(e); process.exit(1); });

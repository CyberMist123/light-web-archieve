// 批次 D · L2 F5 → 1026 floating-toc 版：问收藏目录——左边一列横线，悬停 / 钉住展开；条目 = 问题（问）/ 回答小标题（H2/H3）/ 引用过的帖子（帖）；
// 点问题、小标题跳过去并能「↩ 回到刚才」；钉住记在页面状态；已保存 / 清空时隐藏。不用 sticky、不画滚动条。
'use strict';
const assert = require('node:assert/strict');
const { tick, src, rel, makePlugin, openChat } = require('./_fake_L2.cjs');

(async () => {
  const P = makePlugin();
  const C = await openChat({ plugin: P });
  const toc = () => C.q('.lbchat-toc');
  const items = () => toc().querySelectorAll('.lbchat-ftoc-item');
  // (a) 1 问、没小标题：没有目录；不再有「目录」按钮
  await C.ask('担担面有没有汤');
  assert.equal(toc().hidden, true); assert.equal(C.q('.lbchat-tocbtn').hidden, true);
  P.plugin.reply = () => ({ status: 'ok', markdown: '## 步骤\n\n先煮面 [来源1]\n\n## 要点与避坑\n\n别煮烂', sources: [src('a', 1), src('b', 2)], related: [rel('c', 3)] });
  await C.ask('怎么做');
  P.plugin.reply = () => Object.assign(new Error('x'), { kind: 'api', code: 'TRANSIENT.HTTP_429' });
  await C.ask('第三问');
  // (b) 第 2 问起出现：横线条（is-float），按钮一直不出
  assert.equal(toc().hidden, false); assert.ok(toc().classList.contains('is-float')); assert.equal(C.q('.lbchat-tocbtn').hidden, true);
  // (c) 条目：问题带「问」，小标题带 H2，引用过的帖子「[号] 短标题」带「帖」（没引用的主要b 不列）；失败那问只有问题
  const rows = items().map(r => [r.dataset.level, r.querySelector('.lbchat-ftoc-text').textContent, r.querySelector('.lbchat-ftoc-tag').textContent]);
  assert.deepEqual(rows, [['1', '1  担担面有没有汤', '问'], ['2', '[1] 主要a', '帖'], ['1', '2  怎么做', '问'], ['2', '步骤', 'H2'], ['2', '要点与避坑', 'H2'], ['2', '[1] 主要a', '帖'], ['1', '3  第三问', '问']]);
  // 工具条六个按钮（钉住 / 搜 / 到顶 / 到底 / 复制 / 全部折叠）
  assert.equal(toc().querySelectorAll('.lbchat-ftoc-tool').length, 6);
  // (d) 点第 1 问：跳过去、出现「↩ 回到刚才」，回到底部跟随
  const body = C.body;
  body.scrollHeight = 3000; body.clientHeight = 400; body.scrollTop = 2600; body._rect = { top: 100, left: 0, width: 850, height: 400 };
  (body.listeners.scroll || []).forEach(fn => fn());
  const users = C.qa('.lbchat-user');
  users[0]._rect = { top: -2400, left: 0, width: 500, height: 40 };
  users[1]._rect = { top: -1200, left: 0, width: 500, height: 40 };
  users[2]._rect = { top: 300, left: 0, width: 500, height: 40 };
  items()[0].querySelector('.lbchat-ftoc-text').onclick();
  assert.equal(body.scrollTop, 2600 + (-2400) - 100 - 12);
  const back = C.q('.lbchat-back');
  assert.equal(back.hidden, false);
  back.onclick();
  assert.equal(body.scrollTop, body.scrollHeight, '原来在底部跟随：回到底部');
  // (e) 折叠「2 怎么做」：它下面的小标题 / 帖子藏起来，再点展开
  items()[2].querySelector('.lbchat-ftoc-chev').onclick({ stopPropagation() {} });
  assert.deepEqual(items().map(r => !!r.hidden), [false, false, false, true, true, true, false]);
  items()[2].querySelector('.lbchat-ftoc-chev').onclick({ stopPropagation() {} });
  assert.ok(items().every(r => !r.hidden));
  // (f) 钉住：记在页面状态
  toc().querySelector('.lbchat-ftoc-tool.is-pin').onclick({ stopPropagation() {} });
  assert.ok(toc().querySelector('.lbchat-ftoc-tool.is-pin').classList.contains('is-on'), '钉住按钮亮起（窄窗时面板仍收成横线）');
  // (g) 「↑ 引用处」：跳到胶囊并闪一下（来源行功能，和目录无关，照旧）
  const up = C.rowOf('主要a', C.answers()[1]).querySelector('.lbchat-src-back');
  assert.ok(up, '正文里引用过 [来源1] 才有「↑ 引用处」');
  assert.equal(C.rowOf('主要b', C.answers()[1]).querySelector('.lbchat-src-back'), null);
  up.onclick();
  assert.ok(C.answers()[1].querySelector('button.lbchat-cite[data-cite="1"]').classList.contains('lbchat-flash'));
  // (h) 切到「已保存」：目录隐藏；清空：隐藏
  await C.qa('.lbchat-tab').find(t => t.textContent === '已保存').onclick(); await tick(5);
  assert.equal(toc().hidden, true);
  await C.qa('.lbchat-tab').find(t => t.textContent === '对话').onclick(); await tick(5);
  await C.q('.lbchat-clearall').onclick(); await tick(10);
  assert.equal(toc().hidden, true);
  // (i) 静态：目录规则不含 sticky、收起态隐藏滚动条；对话区仍隐藏滚动条
  const css = C.dom.document.getElementById('lbchat-style').textContent;
  const tocRules = css.split('\n').filter(l => l.includes('.lbchat-toc'));
  assert.ok(tocRules.length && tocRules.every(l => !l.includes('sticky')));
  assert.ok(tocRules.some(l => l.startsWith('.lbchat-toc.is-float{') && l.includes('scrollbar-width:none')));
  assert.ok(/\.lbchat \.lbchat-body,[^{]*\{scrollbar-width:none;\}/.test(css));
  console.log('PASS chat L2 F5 (floating-toc): from the 2nd question, 问 / H2 / [n] 帖 rows, 6-tool bar, jump + ↩ 回到刚才, fold a group, ↑ 引用处 flashes, hidden on 已保存 / clear, no sticky, no scrollbars');
})().catch(e => { console.error(e); process.exit(1); });

// 批次 D · L2 F5：问收藏目录——多问时在问题 / 回答（含小标题）/ 来源之间跳，并能「↩ 回到刚才」。
// 宽窗（bodywrap ≥1242）是对话列左边一栏，窄窗是页头「目录 · N 问」+ 弹出层；不用 sticky、不画滚动条、跳旧回答不改追问绑定。
'use strict';
const assert = require('node:assert/strict');
const { tick, src, rel, makePlugin, openChat } = require('./_fake_L2.cjs');

(async () => {
  const P = makePlugin();
  const C = await openChat({ plugin: P });
  // (a) 1 问时没有目录
  await C.ask('担担面有没有汤');
  assert.equal(C.q('.lbchat-toc').hidden, true); assert.equal(C.q('.lbchat-tocbtn').hidden, true);
  P.plugin.reply = () => ({ status: 'ok', markdown: '## 步骤\n\n先煮面 [来源1]\n\n## 要点与避坑\n\n别煮烂', sources: [src('a', 1), src('b', 2)], related: [rel('c', 3)] });
  await C.ask('怎么做');
  P.plugin.reply = () => Object.assign(new Error('x'), { kind: 'api', code: 'TRANSIENT.HTTP_429' });
  await C.ask('第三问');
  // (b) 窄窗：只有按钮；点开弹出层，选一项后关
  const btn = C.q('.lbchat-tocbtn');
  assert.equal(btn.hidden, false); assert.equal(btn.textContent, '目录 · 3 问');
  btn.onclick({ stopPropagation() {} });
  const panel = () => C.dom.document.querySelector('.lbchat-tocpanel');
  assert.ok(panel());
  // (c) 条目：每问一组 q / a / s；小标题 chip；失败轮「没答上」
  const groups = panel().querySelectorAll('.lbchat-tocgrp');
  assert.equal(groups.length, 3);
  assert.ok(groups[1].querySelector('.lbchat-toc-q').textContent.includes('2 怎么做'));
  assert.ok(groups[1].querySelector('.lbchat-toc-q').textContent.startsWith('↳'), '追问前加 ↳');
  assert.deepEqual(groups[1].querySelectorAll('.lbchat-toc-h').map(b => b.textContent), ['步骤', '要点与避坑']);
  assert.equal(groups[1].querySelector('.lbchat-toc-s').textContent, '来源 2 · 相关 1');
  assert.equal(groups[2].querySelector('.lbchat-toc-a').textContent, '没答上');
  assert.equal(groups[2].querySelector('.lbchat-toc-s'), null, '没有来源的轮不显示「来源」');
  // (d) 点第 1 问：跳过去、不再跟随、出现「↩ 回到刚才」；面板关掉
  const body = C.body;
  body.scrollHeight = 3000; body.clientHeight = 400; body.scrollTop = 2600; body._rect = { top: 100, left: 0, width: 850, height: 400 };
  (body.listeners.scroll || []).forEach(fn => fn());
  const users = C.qa('.lbchat-user');
  users[0]._rect = { top: -2400, left: 0, width: 500, height: 40 };
  users[1]._rect = { top: -1200, left: 0, width: 500, height: 40 };
  users[2]._rect = { top: 300, left: 0, width: 500, height: 40 };
  groups[0].querySelector('.lbchat-toc-q').onclick();
  assert.equal(panel(), null, '选一项后弹出层关闭');
  assert.equal(body.scrollTop, 2600 + (-2400) - 100 - 12);
  const back = C.q('.lbchat-back');
  assert.equal(back.hidden, false);
  back.onclick();
  assert.equal(body.scrollTop, body.scrollHeight, '原来在底部跟随：回到底部');
  assert.equal(back.hidden, true);
  // (e) 点「来源 2 · 相关 1」：展开那一轮的主要依据，之后来源操作重画仍展开
  btn.onclick({ stopPropagation() {} });
  panel().querySelectorAll('.lbchat-tocgrp')[1].querySelector('.lbchat-toc-s').onclick();
  const ans2 = C.answers()[1];
  assert.equal(ans2.querySelector('details[data-part="primary"]').open, true);
  C.rowOf('主要a', ans2).querySelector('.lbchat-src-pin').onclick(); await tick(10);
  assert.equal(C.answers()[1].querySelector('details[data-part="primary"]').open, true, '重画仍展开');
  // (f) 「↑ 引用处」：跳到胶囊并闪一下
  const up = C.rowOf('主要a', C.answers()[1]).querySelector('.lbchat-src-back');
  assert.ok(up, '正文里引用过 [来源1] 才有「↑ 引用处」');
  assert.equal(C.rowOf('主要b', C.answers()[1]).querySelector('.lbchat-src-back'), null);
  up.onclick();
  assert.ok(C.answers()[1].querySelector('button.lbchat-cite[data-cite="1"]').classList.contains('lbchat-flash'));
  // 跳到旧回答不改追问绑定（仍绑最新一轮成功的回答）
  const before = JSON.stringify(C.saved().follow);
  assert.equal(before, '"sources"');
  // (b') 宽窗：左栏出现、按钮隐藏
  const wrapEl = C.q('.lbchat-bodywrap');
  wrapEl.clientWidth = 1400; C.A.resize.trigger(1400, 800); await tick(5);
  assert.ok(wrapEl.classList.contains('is-wide'));
  assert.equal(C.q('.lbchat-toc').hidden, false); assert.equal(btn.hidden, true);
  // (g) 滚到第 2 问那一带：第 2 组 is-here
  users[0]._rect = { top: -900, left: 0, width: 500, height: 40 };
  users[1]._rect = { top: 110, left: 0, width: 500, height: 40 };
  users[2]._rect = { top: 900, left: 0, width: 500, height: 40 };
  body.scrollTop = 1500; (body.listeners.scroll || []).forEach(fn => fn()); await tick(20);
  const here = C.q('.lbchat-toc').querySelectorAll('.lbchat-tocgrp').map(g => g.classList.contains('is-here'));
  assert.deepEqual(here, [false, true, false]);
  // 收起左栏 → 按钮回来（记住状态）
  C.q('.lbchat-toc-fold').onclick();
  assert.equal(C.q('.lbchat-toc').hidden, true); assert.equal(btn.hidden, false);
  // (h) 切到「已保存」：目录隐藏
  await C.qa('.lbchat-tab').find(t => t.textContent === '已保存').onclick(); await tick(5);
  assert.equal(btn.hidden, true);
  await C.qa('.lbchat-tab').find(t => t.textContent === '对话').onclick(); await tick(5);
  // 清空：目录隐藏
  await C.q('.lbchat-clearall').onclick(); await tick(10);
  assert.equal(btn.hidden, true); assert.equal(C.q('.lbchat-toc').hidden, true);
  // (i) 静态：目录规则不含 sticky、含 scrollbar-width:none；对话区仍隐藏滚动条
  const css = C.dom.document.getElementById('lbchat-style').textContent;
  const tocRules = css.split('\n').filter(l => l.includes('.lbchat-toc'));
  assert.ok(tocRules.length && tocRules.every(l => !l.includes('sticky')));
  assert.ok(tocRules.some(l => l.startsWith('.lbchat-toc{') && l.includes('scrollbar-width:none')));
  assert.ok(/\.lbchat \.lbchat-body,[^{]*\{scrollbar-width:none;\}/.test(css));
  console.log('PASS chat L2 F5: TOC from the 2nd question (narrow → 目录 · N 问 popup, wide → left rail with is-here), q / a (heading chips, 没答上) / s groups, jump + ↩ 回到刚才 (back to bottom-follow), 来源 opens the list (kept open across redraws), ↑ 引用处 flashes the cite, hidden on 已保存 / clear, no sticky, no scrollbars');
})().catch(e => { console.error(e); process.exit(1); });

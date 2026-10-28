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
  // (c) 条目：问题 / 小标题 / 引用过的帖子（没引用的主要b 不列）；失败那问只有问题
  // 1028 她：不再挂「问 / H2 / H3 / 帖」小字；帖子序号去掉方括号、单独一段斜体数字（.lbchat-ftoc-n）；问题行 is-q、帖子行 is-post
  assert.equal(toc().querySelectorAll('.lbchat-ftoc-tag').length, 0, '没有层级小字');
  const kind = r => (r.classList.contains('is-q') ? 'q' : r.classList.contains('is-post') ? 'post' : 'h');
  const rows = items().map(r => [r.dataset.level, kind(r), r.querySelector('.lbchat-ftoc-n')?.textContent || '', r.querySelector('.lbchat-ftoc-text').textContent]);
  assert.deepEqual(rows, [['1', 'q', '', '1  担担面有没有汤'], ['2', 'post', '1', '1主要a'], ['1', 'q', '', '2  怎么做'], ['2', 'h', '', '步骤'], ['2', 'h', '', '要点与避坑'], ['2', 'post', '1', '1主要a'], ['1', 'q', '', '3  第三问']]);
  assert.ok(!toc().textContent.includes('[1]'), '序号不带方括号');
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
  // (j) 1028 她：目录样式——问题加粗大一号墨色；帖子楷体（局部变量）浅灰、行距 1.9、比节标题多缩一级；序号用数字字体斜体；当前那一节墨色细线 + 500，不用紫色
  const rule = sel => { const i = css.indexOf(sel + '{'); assert.ok(i >= 0, '缺规则 ' + sel); return css.slice(i + sel.length + 1, css.indexOf('}', i)); };
  const q = rule('.lbchat-ftoc-item.is-q > .lbchat-ftoc-text');
  assert.ok(q.includes('font-size:var(--lb-fs-body)') && q.includes('font-weight:700') && q.includes('color:var(--lb-ink)'), q);
  const post = rule('.lbchat-ftoc-item.is-post > .lbchat-ftoc-text');
  assert.ok(post.includes('font-family:var(--lbchat-kai)') && post.includes('color:var(--lb-faint)') && post.includes('line-height:1.9'), post);
  assert.ok(rule('.lbchat-ftoc-item.is-post').includes('calc(1rem + 24px)'), '帖子比节标题（+12px）再缩一级');
  assert.ok(/--lbchat-kai:"KaiTi"[^;]*var\(--lb-font-serif\)/.test(css), '楷体局部变量，兜底用样式集衬线（不写死 serif）');
  const num = rule('.lbchat-toc-n,.lbchat-ftoc-n');
  assert.ok(num.includes('font-family:var(--lb-font-num)') && num.includes('font-style:italic'), num);
  const here = rule('.lbchat-ftoc-item.is-here > .lbchat-ftoc-text');
  assert.ok(here.includes('box-shadow:inset 2px 0 0 var(--lb-ink)') && !here.includes('interactive-accent'), here);
  assert.ok(rule('.lbchat-ftoc-item.is-here:not(.is-q) > .lbchat-ftoc-text').includes('font-weight:500'));
  assert.ok(!/is-here[^{]*\{[^}]*interactive-accent/.test(css.split('\n').filter(l => l.includes('ftoc') || l.includes('tocgrp')).join('\n')), '当前那一节不再用紫色');
  const pq = rule('.lbchat-toc button.lbchat-toc-q,.lbchat-tocpanel button.lbchat-toc-q');
  assert.ok(pq.includes('font-size:var(--lb-fs-body)') && pq.includes('font-weight:700'), '弹出目录里的问题也加粗大一号：' + pq);
  console.log('PASS chat L2 F5 (floating-toc): from the 2nd question, question / heading / post rows (1028: no 问/H2/帖 tags, italic n, kai posts, ink here-line), 6-tool bar, jump + ↩ 回到刚才, fold a group, ↑ 引用处 flashes, hidden on 已保存 / clear, no sticky, no scrollbars');
})().catch(e => { console.error(e); process.exit(1); });

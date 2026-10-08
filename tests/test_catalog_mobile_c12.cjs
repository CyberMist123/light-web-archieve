// 批次 D · L1 C12：手机上目录页只读——建不起来的按钮不建、三页之间按文件跳、「更新」在页面里读同步记录、不拦长按。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, ev } = require('./_fake_l1.cjs');

(async () => {
  const items = [item('a', '悉尼咖啡地图', { starred: true }), item('b', '电饭煲鸡肉饭')];
  const log = Array.from({ length: 7 }, (_, i) => JSON.stringify({ run_id: 'r' + i, trigger: i % 2 ? 'nightly' : 'manual', started_at: `2026-10-0${i + 1}T04:0${i}:00+10:00`, finished_at: i === 6 ? null : `2026-10-0${i + 1}T05:00:00+10:00`, new: i, error: false })).join('\n') + '\n';
  const P = await openCatalog({ items, isMobile: true, files: { '_archive/sync-log.jsonl': log, '收藏搜索.md': '---\nlb-page: chat\n---\n' }, frontmatter: { '收藏搜索.md': { 'lb-page': 'chat' } } });
  const { A, dom } = P;
  for (const sel of ['.lbc-import', '.lb-manage', '.lbc-check', '.lbc-selbar']) assert.equal(P.$(sel), null, '手机上不建 ' + sel);
  assert.equal(P.$$('button.lbc-star').length, 0, '没有可点的星');
  assert.equal(P.card('a').querySelector('.lbc-star').classList.contains('is-static'), true, '已收藏的显示一个不可点的 ★');
  assert.equal(P.card('b').querySelector('.lbc-star').hidden, true, '没收藏的不显示');
  assert.equal(P.$('.lbc-mobile-note').textContent, '手机上只能看：导入、同步、问 AI、收藏要在电脑上用');
  // 跳页：按 frontmatter 找到问收藏页，openLinkText
  P.$$('.lb-page-nav button').find(b => b.textContent === '问收藏').onclick(); await tick(5);
  assert.equal(P.app.workspace.opened.at(-1)[0], '收藏搜索.md');
  // 「更新」：读 sync-log.jsonl 最后 5 行，浮层；点外面关
  await P.$('.lbc-updated').onclick(ev()); await tick(5);
  const pop = dom.document.body.querySelector('.lbc-synclog-pop');
  assert.ok(pop, '弹出浮层');
  const rows = pop.querySelectorAll('.lbc-synclog-row').map(r => r.textContent);
  assert.equal(rows.length, 5, '最多 5 行');
  assert.match(rows[0], /^10\/07 \d\d:06 · 手动同步 · 新收 6 篇 · 没完成$/);   // 时刻按本机时区显示
  assert.match(rows[1], /^10\/06 \d\d:05 · 夜跑同步 · 新收 5 篇 · 完成$/);
  // Esc 关浮层（不动别的）
  dom.document.dispatchEvent({ type: 'keydown', key: 'Escape', target: dom.document.body });
  assert.equal(dom.document.body.querySelector('.lbc-synclog-pop'), null);
  // 问题角标：照样显示数字；点了只说一句
  // 长按 / 右键：不拦（不设 oncontextmenu）
  assert.equal(P.card('a').oncontextmenu, undefined, '不拦截 contextmenu');
  // 卡片照常能点开
  P.card('b').onclick({}); assert.equal(P.app.workspace.opened.at(-1)[0], 'Web/b.md');
  assert.equal(A.alerts.length, 0);
  // 手机：问题入口点了只说一句
  const Q = await openCatalog({ items, isMobile: true, files: { '_archive/problems-summary.json': JSON.stringify({ needs_human: 1, auto: 0, gave_up: 0 }) } });
  assert.equal(Q.$('.lbc-problems').hidden, false, '手机上照样显示数字');
  await Q.$('.lbc-problems').onclick(); await tick(5);
  assert.equal(Q.A.notices.at(-1), '问题列表要在电脑上看');
  console.log('PASS C12 mobile: no import / manage / check / selbar / clickable star, static ★ for starred, mobile note, page jump by frontmatter, 更新 → last 5 sync-log rows in a popover (Esc closes), no contextmenu interception, problems badge says desktop only');
})().catch(e => { console.error(e); process.exit(1); });

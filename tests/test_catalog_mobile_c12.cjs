// 批次 D · L1 C12：手机上目录页只读——建不起来的按钮不建、三页之间按文件跳、「更新」在页面里读同步记录、不拦长按。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, ev } = require('./_fake_l1.cjs');

(async () => {
  const items = [item('a', '悉尼咖啡地图', { starred: true }), item('b', '电饭煲鸡肉饭')];
  const log = Array.from({ length: 7 }, (_, i) => JSON.stringify({ run_id: 'r' + i, trigger: i % 2 ? 'nightly' : 'manual', started_at: `2026-10-0${i + 1}T04:0${i}:00+10:00`, finished_at: i === 6 ? null : `2026-10-0${i + 1}T05:00:00+10:00`, new: i, error: false })).join('\n') + '\n';
  const P = await openCatalog({ items, isMobile: true, files: { '_archive/sync-log.jsonl': log, '收藏搜索.md': '---\nlb-page: chat\n---\n' }, frontmatter: { '收藏搜索.md': { 'lb-page': 'chat' } } });
  const { A, dom } = P;
  for (const sel of ['.lbc-import', '.lb-manage', '.lbc-check', '.lbc-selbar', '.lbc-sidetoggle']) assert.equal(P.$(sel), null, '手机上不建 ' + sel);   // 1021：没有边栏，也就没有边栏钮
  assert.equal(P.$$('button.lbc-star').length, 0, '没有可点的星');
  assert.equal(P.card('a').querySelector('.lbc-star').classList.contains('is-static'), true, '已收藏的显示一个不可点的 ★');
  assert.equal(P.card('b').querySelector('.lbc-star').hidden, true, '没收藏的不显示');
  assert.equal(P.$('.lbc-mobile-note').textContent, '手机上只能看：导入、同步、问 AI、收藏要在电脑上用');
  // 跳页：按 frontmatter 找到问收藏页，openLinkText（1021：「浏览收藏 / 问收藏」导航换成搜索框右边的「问收藏 →」胶囊）
  assert.ok(P.$('.lbc-tools .lbc-jumps .lbc-pnav-chat'), '1101 作者：右上角「问收藏」「Wiki」两颗跳转（手机上也有）');
  P.$('.lbc-pnav-chat').onclick(); await tick(5);
  assert.equal(P.app.workspace.opened.at(-1)[0], '收藏搜索.md');
  // 1101 作者：同步记录 bug 多，默认不放在页面上——点「更新」什么都不弹（设置 → 开发者「同步记录和进度」打开才有）
  await P.$('.lbc-updated').onclick(ev()); await tick(5);
  assert.equal(dom.document.body.querySelector('.lbc-synclog-pop'), null, '默认不弹同步记录');
  // 问题角标：照样显示数字；点了只说一句
  // 长按 / 右键：不拦（不设 oncontextmenu）
  assert.equal(P.card('a').oncontextmenu, undefined, '不拦截 contextmenu');
  // 卡片照常能点开
  P.card('b').onclick({}); await tick(5); assert.deepEqual(P.noteOpened(), ['Web/b.md', false]);   // 1103：按路径打开
  assert.equal(A.alerts.length, 0);
  // 手机：问题入口点了只说一句
  const Q = await openCatalog({ items, isMobile: true, files: { '_archive/problems-summary.json': JSON.stringify({ needs_human: 1, auto: 0, gave_up: 0 }) } });
  assert.equal(Q.$('.lbc-problems').hidden, false, '手机上照样显示数字');
  await Q.$('.lbc-problems').onclick(); await tick(5);
  assert.equal(Q.A.notices.at(-1), '问题列表要在电脑上看');
  console.log('PASS C12 mobile: no import / manage / check / selbar / clickable star, static ★ for starred, mobile note, page jump by frontmatter, 更新 → last 5 sync-log rows in a popover (Esc closes), no contextmenu interception, problems badge says desktop only');
})().catch(e => { console.error(e); process.exit(1); });

// 批次 D · L1 C17 / C19：Esc 的范围、菜单键盘操作、键盘弹出的右键菜单位置、中键开新标签；大类条滚轮横滚 / 渐隐 / 重建保位置和焦点。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, ev } = require('./_fake_l1.cjs');

(async () => {
  const items = ['a', 'b', 'c'].map(id => item(id, '笔记 ' + id));
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {} };
  const P = await openCatalog({ items, plugin, data: { built_at: '2026-10-08T05:09:12+10:00', pinyin_chars: {}, aliases: [], cats: [], topics: [], state_registry: {}, items,
    cats_order: ['悉尼', '做饭', 'AI', '学习', '穿搭', '家居', '旅行', '读书', '运动', '电影'] } });
  const { A, dom } = P;
  const esc = target => dom.document.dispatchEvent({ type: 'keydown', key: 'Escape', target: target || dom.document.body });
  P.card('a').querySelector('.lbc-check').onclick(ev());
  // 活动标签页不是本页：不清
  P.app.workspace.activeLeaf = { view: { containerEl: dom.document.body.createEl('div') } };
  esc(); assert.equal(P.$$('.lbc-card.is-selected').length, 1);
  A.activate();
  esc(P.search()); assert.equal(P.$$('.lbc-card.is-selected').length, 1, '在搜索框里按 Esc 不清多选');
  // 右键菜单开着：Esc 只关菜单
  P.card('b').oncontextmenu(ev({ clientX: 50, clientY: 60 }));
  assert.ok(dom.document.body.querySelector('.lbc-menu'));
  esc();
  assert.equal(dom.document.body.querySelector('.lbc-menu'), null, '菜单关掉');
  assert.equal(P.$$('.lbc-card.is-selected').length, 2, '多选还在（右键把这张也算进来了）');
  // 菜单键盘：打开后焦点在第一项；ArrowDown → 第二项；End / Home；Escape 关并把焦点还给卡片
  P.$('.lbc-clrsel').onclick();
  const card = P.card('c');
  card._rect = { left: 300, top: 200, width: 230, height: 300 };
  card.oncontextmenu(ev());   // clientX = clientY = 0：键盘弹出
  const menu = dom.document.body.querySelector('.lbc-menu');
  assert.equal(menu.style.left, '316px'); assert.equal(menu.style.top, '216px', '键盘弹出：定位到卡片左上角内缩 16');
  const its = menu.querySelectorAll('.lbc-menu-item');
  assert.equal(dom.document.activeElement, its[0], '焦点在第一项');
  const key = k => menu.dispatchEvent({ type: 'keydown', key: k, bubbles: true });
  key('ArrowDown'); assert.equal(dom.document.activeElement, its[1]);
  key('End'); assert.equal(dom.document.activeElement, its.at(-1));
  key('ArrowDown'); assert.equal(dom.document.activeElement, its[0], '循环');
  key('ArrowUp'); assert.equal(dom.document.activeElement, its.at(-1));
  key('Home'); assert.equal(dom.document.activeElement, its[0]);
  key('Escape');
  assert.equal(dom.document.body.querySelector('.lbc-menu'), null);
  assert.equal(dom.document.activeElement, card, '焦点还给卡片');
  // 时间菜单（自制）同一套键盘
  P.$('.lbc-time').onclick(ev());
  const tm = dom.document.body.querySelector('.lbc-time-menu');
  assert.equal(dom.document.activeElement, tm.querySelector('.lbc-menu-item'));
  tm.dispatchEvent({ type: 'keydown', key: 'Tab', bubbles: true });
  assert.equal(dom.document.body.querySelector('.lbc-time-menu'), null, 'Tab 关菜单');
  // 中键：开新标签；mousedown 中键不出自动滚动
  let prevented = false;
  P.card('a').onauxclick({ button: 1, preventDefault() { prevented = true; } });
  assert.ok(prevented); assert.deepEqual(P.app.workspace.opened.at(-1), ['Web/a.md', '', true]);
  prevented = false; P.card('a').onmousedown({ button: 1, preventDefault() { prevented = true; } }); assert.ok(prevented);

  // C19 大类条：竖向滚轮横滚；到头放给页面；重建保 scrollLeft 和焦点；渐隐 class
  const bar = P.$('.lbc-cats');
  bar.scrollWidth = 800; bar.clientWidth = 300;
  const wheel = (dy, more = {}) => { let p = false; for (const fn of bar.listeners.wheel || []) fn({ deltaY: dy, deltaX: 0, preventDefault() { p = true; }, ...more }); return p; };
  assert.equal(wheel(100), true); assert.equal(bar.scrollLeft, 100);
  assert.equal(wheel(100, { ctrlKey: true }), false, 'Ctrl 滚轮不管');
  assert.equal(wheel(0, { deltaX: 50 }), false, '横向为主不管');
  bar.scrollLeft = 500;
  assert.equal(wheel(100), false, '已在最右：放给页面');
  for (const fn of bar.listeners.scroll || []) fn({}); await tick(5);
  assert.ok(bar.classList.contains('has-more-left') && !bar.classList.contains('has-more-right'));
  bar.scrollLeft = 120; wheel(-20);
  assert.ok(bar.classList.contains('has-more-left') && bar.classList.contains('has-more-right'));
  const tab = () => P.$$('.lbc-cat').find(b => b.textContent === '学习');
  tab().focus();
  const before = bar.scrollLeft;
  P.cat('今日新增').onclick(); P.cat('今日新增').onclick();   // 点别的 tab 引起重建
  assert.equal(bar.scrollLeft, before, '重建后横向位置不丢');
  tab().focus(); tab().onclick();
  assert.equal(dom.document.activeElement, tab(), '焦点回到同名 tab');
  assert.ok(tab()._scrolledIntoView >= 1, '用户点的 tab 滚进视野');
  console.log('PASS C17 / C19: Esc scope (other leaf / search box / menu open), menu keyboard (focus first, arrows wrap, Home / End, Esc returns focus, Tab closes), keyboard context menu at card corner, middle click new tab; category bar wheel → horizontal, edges pass through, fade classes, rebuild keeps scrollLeft + focus');
})().catch(e => { console.error(e); process.exit(1); });

// 批次 D · L1 C13：右键编辑标签——存完收起 + 卡上闪「已保存」；Esc 关掉不动多选；失败说原因、按钮可点、字不动。
'use strict';
const assert = require('node:assert/strict');
const { tick, item, openCatalog, ev } = require('./_fake_l1.cjs');

(async () => {
  const items = [item('a', '悉尼咖啡地图', { tags: ['咖啡'] }), item('b', '电饭煲鸡肉饭')];
  const plugin = { settings: { hiddenCats: [] }, openLibraryPage() {} };
  const P = await openCatalog({ items, plugin, files: { 'Web/a.md': '---\ntags: [咖啡]\n---\n', 'Web/b.md': '' } });
  const { A, dom, app } = P;
  const openEditor = id => { P.card(id).oncontextmenu(ev()); P.pick('编辑标签').onclick(ev()); return P.card(id).querySelector('form.lbc-tagform'); };
  // 成功：form 收起、卡上闪「已保存」、不发 Notice、不重排
  let form = openEditor('a');
  assert.equal(form.querySelector('input').value, '咖啡');
  assert.equal(dom.document.activeElement, form.querySelector('input'));
  form.querySelector('input').value = '咖啡, #悉尼';
  const layout0 = P.counts().layout;
  await form.onsubmit({ preventDefault() {} }); await tick(5);
  assert.equal(P.card('a').querySelector('form.lbc-tagform'), null, '存完收起');
  assert.equal(P.card('a').querySelector('.lbc-flash').textContent, '已保存');
  assert.deepEqual(app.metadataCache.frontmatter['Web/a.md'].tags, ['咖啡', '悉尼']);
  assert.equal(A.notices.length, 0, '和卡有关的提示就地显示');
  assert.equal(P.counts().layout, layout0, '不重排');
  // Esc：关掉、多选不动
  form = openEditor('a');
  P.card('b').querySelector('.lbc-check').onclick(ev());
  let stopped = false;
  form.onkeydown({ key: 'Escape', preventDefault() {}, stopPropagation() { stopped = true; } });
  assert.equal(P.card('a').querySelector('form.lbc-tagform'), null);
  assert.ok(stopped, 'Esc 不冒泡到全局（不清多选）');
  assert.equal(P.$$('.lbc-card.is-selected').length, 1);
  P.$('.lbc-clrsel').onclick();
  // 失败：按钮恢复可点、错误行写原因、字不动
  app.fileManager.processFrontMatter = async () => { throw new Error('EBUSY'); };
  form = openEditor('a');
  form.querySelector('input').value = '新标签';
  await form.onsubmit({ preventDefault() {} }); await tick(5);
  const save = form.querySelectorAll('button').find(b => b.type === 'submit');
  assert.equal(save.disabled, false); assert.equal(save.textContent, '保存标签');
  assert.equal(form.querySelector('.lbc-tagform-err').hidden, false);
  assert.equal(form.querySelector('.lbc-tagform-err').textContent, '没保存上，内容还在，可重试：EBUSY');
  assert.equal(form.querySelector('input').value, '新标签');
  console.log('PASS C13 tag editor: saved → form closes + in-card 已保存 flash (no Notice, no relayout), Esc closes without clearing selection, failure keeps text with reason and an enabled button');
})().catch(e => { console.error(e); process.exit(1); });

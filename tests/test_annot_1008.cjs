// 批次 D · L3 批注块（annotate-view.js）：
//   主审裁决 3 —— 单栏笔记 / 实时预览里 Dataview 重跑不再把半截字存成正式批注（7ab44c6 上的红线读数见 tests/test_rig_selfcheck.cjs，这里是同一用例在当前资产上转绿）；
//   N4 删除原位可撤销 5 秒、触屏 ✎✕ 常显；N5 输入框 / 编辑框随内容长高；N13 ★ 乐观更新、提示只说一次；N16 手机上 ★ 灰掉并说明；
//   N-M1 写新批注时点旧批注 ✎ / 编辑中点另一条 ✎✕ 第一下就生效；N15 钉住紧凑样式在样式块里。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const NOTE = '_archive/xiaohongshu/n1/notes.json';
const CODE = asset('lb-page-lib.js') + '\n' + asset('annotate-view.js');
const disk = (made) => JSON.parse(made.V.get(NOTE));

async function open({ annotations = [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }, { id: 'a2', ts: '2026-09-02T00:00:00Z', text: '第二条' }], plugin = { settings: {} }, mode = 'reading', side = true, isMobile = false } = {}) {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const made = makeApp({ files: { [NOTE]: JSON.stringify({ starred: false, annotations }) }, plugin, isMobile });
  const dom = makeDom();
  const A = dataviewBlock({ dom, app: made.app, mode, code: CODE, params: { itemId: 'xhs-n1', notePath: NOTE } });
  if (side) { A.host.classList.add('xhs-note'); A.host.createEl('div', { cls: 'lb-side' }); }
  await A.run(); await tick(5);
  const box = A.host.querySelector('.lba-annot');
  return { made, dom, A, box, ta: box.querySelector('.lba-annot-input'), texts: () => box.querySelectorAll('.lba-annot-text').map(x => x.textContent) };
}

(async () => {
  // ── 主审裁决 3：单栏 / 实时预览，重跑不定稿（同 test_rig_selfcheck 的 7ab44c6 用例，当前资产转绿）──
  for (const mode of ['reading', 'live']) {
    const { made, dom, A, box, ta } = await open({ mode, side: false, annotations: [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }] });
    assert.ok(!A.container.contains(ta), mode + '：批注框不在 dv.container 里（挂在它后面的 host 上）');
    assert.ok(box.closest('.lb-page-host') && box.closest('.lb-page-host').previousElementSibling === A.container, mode + '：host 紧跟在容器后面（位置和以前一样在这一段末尾）');
    let blurs = 0; ta.addEventListener('blur', () => { blurs++; });
    ta.focus(); ta.value = '正在打的';
    await A.rerun(); await tick(20);
    const reading = { blurs, focused: dom.document.activeElement === ta, value: ta.value, saved: disk(made).annotations.map(a => a.text) };
    console.log(`批注单栏 ${mode === 'live' ? '实时预览' : '阅读视图'}（当前资产，假 DOM）：重跑一次后 ${JSON.stringify(reading)}`);
    assert.deepEqual(reading, { blurs: 0, focused: true, value: '正在打的', saved: ['旧的'] }, mode + '：重跑不失焦、不定稿、字还在');
    assert.equal(A.host.querySelectorAll('.lba-annot').length, 1, mode + '：只有一个批注框');
    // Obsidian 重画这一段（component 卸载、host 被摘）：框被摘下 → 只存草稿，不落成一条
    A.detach(); await tick(20);
    assert.deepEqual(disk(made).annotations.map(a => a.text), ['旧的'], mode + '：摘下这一段不定稿');
    assert.equal(disk(made).draft, '正在打的', mode + '：半截字存成草稿，重开这篇还在');
  }
  { // 她主动离开输入框（框还在原处）：照旧失焦即定稿（N3 不改）
    const { made, dom, ta } = await open({ side: false });
    ta.focus(); ta.value = '离开时定稿';
    dom.document.body.focus?.(); ta.blur?.(); await ta.onblur(); await tick(5);
    assert.ok(disk(made).annotations.some(a => a.text === '离开时定稿'), '主动失焦照样定稿');
    assert.equal(ta.value, '');
  }
  { // 框被挪进左栏（左栏晚渲染）时正在打字：不定稿、焦点还回来
    const { made, dom, A, box, ta } = await open({ side: false });
    ta.focus(); ta.value = '挪动中';
    A.host.classList.add('xhs-note');
    const side = A.host.createEl('div', { cls: 'lb-side' });
    side.appendChild(box);   // placeUnderImages 做的事
    await tick(20);
    assert.ok(!disk(made).annotations.some(a => a.text === '挪动中'), '挪动不定稿');
    assert.equal(dom.document.activeElement, ta, '焦点还回输入框');
    assert.equal(ta.value, '挪动中');
  }

  // ── N4：删除原位可撤销 ──
  globalThis.__lbaUndoMs = 60;
  {
    const { made, box, texts } = await open();
    await box.querySelector('.lba-del').onclick({ stopPropagation() {} }); await tick(5);
    assert.deepEqual(texts(), ['第二条']);
    const row = box.querySelector('.lba-undo-row');
    assert.ok(row && row.textContent.includes('已删 · 撤销'), '原位出现「已删 · 撤销」');
    assert.equal(box.querySelector('.lba-annot-list').children[0], row, '撤销行在被删那条原来的位置');
    assert.ok(disk(made).deleted.includes('a1'), '磁盘记了墓碑');
    await box.querySelector('.lba-undo').onclick({ stopPropagation() {} }); await tick(5);
    assert.deepEqual(texts(), ['旧的', '第二条'], '撤销后回到原位');
    const back = disk(made).annotations.find(a => a.text === '旧的');
    assert.ok(back && back.ts === '2026-09-01T00:00:00Z' && back.id !== 'a1', '同 text / ts、换了 id');
    assert.ok(!box.querySelector('.lba-undo-row'));
    // 过期自动消失
    await box.querySelector('.lba-del').onclick({ stopPropagation() {} }); await tick(5);
    assert.ok(box.querySelector('.lba-undo-row'));
    await tick(100);
    assert.ok(!box.querySelector('.lba-undo-row'), '过了时限撤销行消失');
  }
  { // 撤销写盘失败：这条再次消失，提示可重试
    const { made, A, box, texts } = await open();
    await box.querySelector('.lba-del').onclick({ stopPropagation() {} }); await tick(5);
    made.app.vault.adapter.write = async () => { throw new Error('磁盘满'); };
    await box.querySelector('.lba-undo').onclick({ stopPropagation() {} }); await tick(5);
    assert.deepEqual(texts(), ['第二条']);
    assert.ok(A.notices.some(m => m.startsWith('没保存上，内容还在，可重试')), A.notices.join('|'));
  }
  // ── N5：随内容长高 ──
  {
    const { box, ta } = await open();
    ta.scrollHeight = 120; ta.oninput(); assert.equal(ta.style.height, '120px');
    ta.scrollHeight = 500; ta.oninput(); assert.equal(ta.style.height, '320px'); assert.equal(ta.style.overflowY, 'auto');
    const edit = box.querySelector('.lba-edit');
    await edit.onclick({ stopPropagation() {} });
    const editor = box.querySelector('.lba-edit-input');
    assert.ok(editor, '编辑框打开');
    editor.scrollHeight = 90; editor.oninput(); assert.equal(editor.style.height, '90px');
    await editor.onblur();
  }

  // ── N-M1 ──
  {
    const { made, box, ta, texts } = await open();
    const ctl = box.querySelector('.lba-ctl'); let prevented = false;
    ctl.onpointerdown({ preventDefault() { prevented = true; } });
    assert.ok(prevented, '按下 ✎✕ 不让输入框失焦');
    // 输入框里有字时点 ✎：编辑框打开；随后输入框失焦落成一条，编辑框还在
    ta.focus(); ta.value = '写到一半';
    await box.querySelectorAll('.lba-edit')[0].onclick({ stopPropagation() {} });
    assert.ok(box.querySelector('.lba-edit-input'), '第一下就打开编辑框');
    await ta.onblur(); await tick(5);
    assert.ok(box.querySelector('.lba-edit-input'), '新批注定稿后编辑框没被冲掉');
    assert.ok(disk(made).annotations.some(a => a.text === '写到一半'));
    // 编辑 A 时点 B 的 ✎：A 先存，B 第一下就打开
    box.querySelector('.lba-edit-input').value = '旧的（改）';
    await box.querySelectorAll('.lba-edit')[1].onclick({ stopPropagation() {} }); await tick(5);
    assert.ok(disk(made).annotations.some(a => a.text === '旧的（改）'), 'A 的改动先存盘');
    const editing = box.querySelectorAll('.lba-annot-item').filter(r => r.querySelector('.lba-edit-input'));
    assert.equal(editing.length, 1); assert.equal(editing[0].querySelector('.lba-annot-text').textContent, '第二条', 'B 的编辑框打开了');
    // 编辑 B 时点 A 的 ✕：B 先存，A 删掉并出撤销行
    box.querySelector('.lba-edit-input').value = '第二条（改）';
    await box.querySelectorAll('.lba-del')[0].onclick({ stopPropagation() {} }); await tick(5);
    assert.ok(disk(made).annotations.some(a => a.text === '第二条（改）'), 'B 先存');
    assert.ok(!texts().includes('旧的（改）') && box.querySelector('.lba-undo-row'), 'A 删掉、出撤销行');
  }

  // ── N13：★ 乐观更新 ──
  {
    let resolveStar, rejectStar, calls = 0;
    const plugin = { settings: {}, starNote: () => { calls++; return new Promise((res, rej) => { resolveStar = res; rejectStar = rej; }); } };
    const { A, box } = await open({ plugin });
    const star = box.querySelector('.lba-star'), hint = box.querySelector('.lba-star-hint');
    star.onclick();
    assert.ok(star.classList.contains('is-on'), '点下就亮');
    assert.ok(star.classList.contains('is-busy'));
    assert.equal(hint.textContent, '正在收藏…');
    star.onclick(); assert.equal(calls, 1, '忙的时候再点不多调');
    resolveStar({ starred: true }); await tick(5);
    assert.equal(A.notices.at(-1), '已收藏');
    assert.ok(!star.classList.contains('is-busy'));
    star.onclick(); rejectStar(new Error('收藏失败：后台没起来')); await tick(5);
    assert.ok(star.classList.contains('is-on'), '取消失败 → 回到已收藏');
    assert.equal(A.notices.at(-1), '收藏失败：后台没起来', '只有一个前缀');
    assert.equal(hint.textContent, '没收藏上');
  }

  // ── N16：手机上 / 插件没开 ──
  {
    let called = 0;
    const { A, box } = await open({ plugin: { settings: {}, starNote: async () => { called++; return { starred: true }; } }, isMobile: true });
    const star = box.querySelector('.lba-star');
    assert.ok(star.classList.contains('is-disabled'));
    assert.ok(star.getAttribute('title').includes('手机上只能看'));
    star.onclick(); star.onclick(); await tick(5);
    assert.equal(called, 0, '手机上不调 starNote');
    assert.equal(A.notices.filter(m => m.includes('手机上只能看')).length, 1, '同一篇只说一次');
  }
  {
    const { box } = await open({ plugin: { settings: {} } });
    assert.ok(box.querySelector('.lba-star').getAttribute('title').includes('启用 Link Brain Actions'), '电脑上插件没开：说怎么开');
  }

  // ── 样式块：触屏常显、钉住紧凑（N15） ──
  {
    const { dom } = await open();
    const text = dom.document.getElementById('lba-annot-style').textContent;
    assert.ok(text.includes('@media (hover:none){.lba-ctl{opacity:1;}}'));
    assert.ok(text.includes('.lb-media-locked .lba-annot.lba-in-side > .lba-input-row{order:-1'));   // 1015：输入框和 ⭐ 一行，整行钉在图下
    assert.ok(/\.lba-star\.is-on\{[^}]*color:var\(--lb-star/.test(text), '1015：收藏的星是黄的');
    assert.ok(!/lb-slide|max-height|grid-template/.test((text.split('批次 D · N15')[1] || '').split('1015')[0]), '紧凑模式只调间距和顺序，不碰图片尺寸 / grid');
  }
  // ── 1015 她：删「批注」二字；⭐ 在写批注框边上 ──
  {
    const { box } = await open();
    assert.ok(!box.querySelector('.lba-annot-title'), '没有「批注」两个字');
    const row = box.querySelector('.lba-input-row');
    assert.ok(row && row.querySelector('.lba-annot-input') && row.querySelector('.lba-star'), '⭐ 和写批注框在一行');
    assert.ok(!box.querySelector('.lba-annot-head .lba-star'), '⭐ 不在上面那一行');
  }
  console.log('PASS annotate 1008: single-column rerun keeps typing (no commit, focus kept, detach saves draft only; leaving the box still commits), undo row 5s, autosize, ✎✕ first click works while typing/editing, ★ optimistic + single prefix, mobile ★ disabled once-notice, pinned compact CSS');
})().catch(e => { console.error(e); process.exit(1); });

// 批次 D 地基：测试架自检（node 侧）——防有人把测试架「修」得不像真宿主。C1 当初没被抓到，就是因为假 DOM 和外壳少了这几条：
//   ① 假 dataviewBlock 的容器带 Dataview 写的行内 overflow-x:auto（阅读视图 / 实时预览都有）；
//   ② live 模式的祖先链里有 .cm-embed-block（实时预览的 :hover{overflow:hidden} / contain:paint 就作用在它身上）；
//   ③ 元素摘离文档后 activeElement 回到 body，并且摘之前同步发 blur / focusout（和 Chromium 一样；没有这条测不出 C4，也测不出「失焦即保存」被重跑误触发）；
//   ④ playwright 外壳的 CSS 里有 Obsidian 1.14.4 的 :hover{overflow:hidden} 和 contain:paint 两条；外壳的容器也带行内 overflow-x:auto。
// 外加：在 041aca9 的目录页资产上，假 DOM 里 C4 是红的（重跑一次搜索框就失焦）；在 7ab44c6 的批注资产上，单栏批注框重跑会把半截字存成批注（红）。
// playwright 版的红线自检在 tests/ui/rig_selfcheck_ui.cjs。
'use strict';
const assert = require('node:assert/strict');
const { makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');
const shell = require('./_obsidian_shell.cjs');

const DATA = '_archive/catalog-data.json';
(async () => {
  // ① ② 两种模式的结构
  const dom = makeDom();
  const { app } = makeApp({ files: { [DATA]: '{"items":[]}' } });
  const R = dataviewBlock({ dom, app, code: '' });
  assert.equal(R.container.style.overflowX, 'auto', '阅读视图：容器带行内 overflow-x:auto');
  assert.ok(R.container.closest('.el-pre') && R.container.closest('.markdown-preview-sizer.markdown-preview-section') && R.container.closest('.markdown-preview-view.markdown-rendered'));
  assert.ok(R.container.closest('.workspace-leaf.mod-active') && R.container.closest('.workspace-leaf-content[data-type=markdown]') && R.container.closest('.view-content') && R.container.closest('.markdown-reading-view'));
  assert.equal(R.host, R.container.closest('.markdown-preview-view'), 'A.host = 阅读视图的滚动容器');
  assert.equal(R.section, R.container.parentNode);
  const L = dataviewBlock({ dom, app, code: '', mode: 'live' });
  assert.equal(L.container.style.overflowX, 'auto', '实时预览：容器带行内 overflow-x:auto');
  assert.ok(L.container.closest('.cm-preview-code-block.cm-embed-block.cm-lang-dataviewjs'), '实时预览：祖先链里有 .cm-embed-block');
  assert.equal(L.section.getAttribute('contenteditable'), 'false', 'widget 是 .cm-content 下的 [contenteditable=false]（contain:paint 作用在它上面）');
  assert.ok(L.section.parentNode.classList.contains('cm-content'));
  assert.ok(L.container.closest('.markdown-source-view.mod-cm6.is-live-preview') && L.container.closest('.cm-editor'));
  assert.equal(L.host, L.container.closest('.cm-scroller'), 'A.host = 实时预览的滚动容器 .cm-scroller');
  assert.ok(L.section.querySelector('.edit-block-button'), '「编辑代码块」按钮在容器后面');
  const I = dataviewBlock({ dom, app, code: '', active: false });
  assert.ok(!I.leaf.classList.contains('mod-active'), 'active:false 的叶子不带 .mod-active');

  // ③ 脱离文档即失焦（摘元素 / 清空父元素 / 挪走都算），focus() 对不在文档里的元素无效
  const box = R.section.createEl('div'), input = box.createEl('input');
  input.focus(); assert.equal(dom.document.activeElement, input);
  box.remove(); assert.equal(dom.document.activeElement, dom.document.body, '摘下来的子树里有焦点 → 回到 body');
  input.focus(); assert.equal(dom.document.activeElement, dom.document.body, '不在文档里的元素拿不到焦点');
  R.section.append(box); input.focus(); assert.equal(dom.document.activeElement, input);
  R.section.innerHTML = ''; assert.equal(dom.document.activeElement, dom.document.body, 'innerHTML 清空也失焦（Dataview 重跑就是这么清的）');
  // ③' 摘的时候发 blur / focusout（和 Chromium 151 / Edge 150 实测一致：同步、元素还连着、activeElement 已是 body、relatedTarget=null；
  //     blur 不冒泡、focusout 冒泡到祖先和 document）。复审抓到的：以前假 DOM 不发，「失焦即保存」被 Dataview 重跑误触发这类问题在 node 层测不到
  for (const how of ['innerHTML', 'remove', 'textContent', 'move']) {
    const holder = R.section.createEl('div'); const inp = holder.createEl('input');
    const seen = [];
    inp.addEventListener('blur', e => seen.push(['blur', inp.isConnected, dom.document.activeElement === dom.document.body, e.relatedTarget ?? null, !!e.bubbles]));
    const onOut = e => seen.push(['focusout@section', e.target === inp]); R.section.addEventListener('focusout', onOut);
    inp.focus();
    if (how === 'innerHTML') holder.innerHTML = '';
    else if (how === 'remove') inp.remove();
    else if (how === 'textContent') holder.textContent = '';
    else dom.document.body.append(inp);
    R.section.removeEventListener('focusout', onOut);
    assert.deepEqual(seen, [['blur', true, true, null, false], ['focusout@section', true]], how + '：摘之前同步发 blur（不冒泡）+ focusout（冒泡）');
    assert.equal(dom.document.activeElement, dom.document.body);
    holder.remove(); inp.remove();
  }
  { // 元素自己有焦点时清空它自己的子节点：焦点不动、不发 blur
    const ta = R.section.createEl('textarea'); ta.appendText('x'); let n = 0; ta.addEventListener('blur', () => n++);
    ta.focus(); ta.textContent = ''; assert.equal(dom.document.activeElement, ta); assert.equal(n, 0); ta.remove();
  }

  // ④ playwright 外壳的 CSS / DOM 守卫
  assert.ok(shell.SUBSET_CSS.includes('@media (hover: hover){\n.markdown-source-view.mod-cm6 .cm-embed-block:not(.cm-table-widget,.cm-lang-base):hover{box-shadow:var(--embed-block-shadow-hover);border-radius:var(--radius-s);overflow:hidden;cursor:text;}'),
    '外壳 CSS 有 Obsidian 1.14.4 的 .cm-embed-block:hover{overflow:hidden}，和真 app.css 一样放在 @media (hover: hover) 里');
  assert.ok(L.section.querySelector('.embed-actions > .edit-block-button'), '实时预览：.embed-actions > .edit-block-button（1.14.4 addEditButton 的结构）');
  assert.equal(L.container.nextSibling, L.section.querySelector('.embed-actions'), '容器在 .embed-actions 前面');
  assert.ok(shell.SUBSET_CSS.includes('.markdown-source-view.mod-cm6 .cm-content>[contenteditable=false]{contain:paint!important;}'), '外壳 CSS 有 contain:paint');
  assert.ok(/\/\* 出处：Obsidian 1\.14\.4 app\.css \*\//.test(shell.SUBSET_CSS) && /CodeMirror 6/.test(shell.SUBSET_CSS), '每段注明出处版本');
  for (const host of ['page-reading', 'page-live']) assert.ok(shell.hostHtml(host).includes('<div class="block-language-dataviewjs node-insert-event" style="overflow-x: auto;"></div>'), host + '：容器带行内 overflow-x:auto');
  assert.ok(/cm-embed-block markdown-rendered cm-lang-dataviewjs" contenteditable="false"><div class="block-language-dataviewjs/.test(shell.hostHtml('page-live')), 'page-live：容器在 .cm-embed-block 里');
  assert.ok(/markdown-preview-view markdown-rendered[^"]*"><div class="markdown-preview-sizer markdown-preview-section">/.test(shell.hostHtml('page-reading')), 'page-reading：阅读视图层级');
  const note = shell.hostHtml('note-reading', { variant: 'background', mdHtml: '<div class="lb-note"></div>' });
  assert.ok(note.includes('workspace-ribbon') && note.includes('mod-left-split') && note.includes('status-bar') && note.includes('view-header') && note.includes('xhs-note'), '笔记页宿主：ribbon / 侧栏 / 视图头 / 状态栏');
  assert.equal((note.match(/class="workspace-leaf[ "]/g) || []).length, 3, '主叶子 + 后台叶子（+ 左侧栏一个）');
  assert.ok(shell.hostHtml('note-reading', { variant: 'popover' }).includes('popover hover-popover'));
  assert.ok(shell.hostHtml('settings-modal').includes('modal mod-settings') && shell.hostHtml('settings-modal').includes('vertical-tab-content'));
  assert.ok(shell.THEME_CSS.includes('.theme-dark{') && shell.THEME_CSS.includes('.theme-light{') && shell.THEME_CSS.includes('body.lb-test-theme-orange{'), '亮 / 暗 / 改了橙色 三套主题变量');

  // 红线：041aca9 的目录页在假 DOM 里重跑一次就失焦（C4 抓得到）
  if (shell.revAvailable('041aca9')) {
    delete globalThis.__lbState; delete globalThis.__lbListeners;
    const items = Array.from({ length: 4 }, (_, i) => ({ id: 'n' + i, title: 't' + i, tags: [], cats: [], topics: [], search_fields: { body: 'b' }, note: `Web/n${i}.md`, cover: '', attachment: 'none', starred: false, ts: '2026-10-01T00:00:00Z', date: '2026-10-01' }));
    const made = makeApp({ files: { [DATA]: JSON.stringify({ built_at: '2026-10-08T00:00:00Z', pinyin_chars: {}, aliases: [], cats_order: [], cats: [], topics: [], items }), '_archive/sync-status.json': '{}' }, plugin: { settings: { hiddenCats: [] } } });
    const dom2 = makeDom();
    const A = dataviewBlock({ dom: dom2, app: made.app, code: shell.pageAssets('catalog', { rev: '041aca9' }) });
    await A.run();
    const search = A.q('.lbc-search');
    search.focus(); search.value = 'ka';
    await A.rerun();
    const lost = dom2.document.activeElement !== search;
    console.log(`C4 @041aca9（假 DOM）：重跑一次后 activeElement = ${dom2.document.activeElement === dom2.document.body ? 'body' : dom2.document.activeElement?.className}，搜索框值 = ${JSON.stringify(search.value)}`);
    assert.ok(lost, '041aca9 的目录页：重跑一次搜索框就失焦（假 DOM 抓得到 C4）');
    assert.equal(A.container.querySelector('.lbc-search'), search, '同一个搜索框被挂回去了，只是失了焦');
  } else console.log('（本仓库没有 041aca9：跳过假 DOM 里的 C4 红线）');

  // 红线（批注，复审）：单栏笔记 / 实时预览里批注框留在 dv.container 里（没有 .xhs-note .lb-side 可挪）。Dataview 重跑清空容器时
  // 正在打字的输入框同步收到 blur → annotate-view 的 ta.onblur = commit 把半截字存成一条正式批注、清空输入框、焦点也没了。
  // 批次 D 基线 7ab44c6 上两种视图都必须是红的；修法归笔记线（L3），修好后在当前资产上写同一个用例转绿。
  const BASE = '7ab44c6';
  if (shell.revAvailable(BASE)) {
    const NOTE = '_archive/xiaohongshu/n1/notes.json';
    for (const mode of ['reading', 'live']) {
      delete globalThis.__lbState; delete globalThis.__lbListeners;
      const made = makeApp({ files: { [NOTE]: JSON.stringify({ starred: false, annotations: [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }] }) }, plugin: { settings: {} } });
      const dom3 = makeDom();
      const B = dataviewBlock({ dom: dom3, app: made.app, mode, code: shell.pageAssets('annotate', { rev: BASE }), params: { itemId: 'xhs-n1', notePath: NOTE } });
      await B.run();
      const ta = B.q('.lba-annot-input');
      assert.ok(ta && B.container.contains(ta), mode + '：单栏时批注框留在 dv.container 里');
      let blurs = 0; ta.addEventListener('blur', () => { blurs++; });
      ta.focus(); ta.value = '正在打的';
      await B.rerun();
      await new Promise(r => setTimeout(r, 50));   // commit 里的 persist 是异步的
      const saved = JSON.parse(made.V.get(NOTE)).annotations.map(a => a.text);
      const reading = { blurs, focused: dom3.document.activeElement === ta, value: ta.value, saved };
      console.log(`批注单栏 ${mode === 'live' ? '实时预览' : '阅读视图'} @${BASE}（假 DOM）：重跑一次后 ${JSON.stringify(reading)}`);
      assert.equal(blurs, 1, mode + '：重跑清空容器 → 输入框收到 blur');
      assert.ok(saved.includes('正在打的'), mode + '：红线——半截字被存成了一条正式批注');
      assert.equal(reading.value, '', mode + '：红线——输入框被清空');
      assert.equal(reading.focused, false, mode + '：红线——焦点没了');
    }
  } else console.log(`（本仓库没有 ${BASE}：跳过批注单栏红线）`);
  console.log('PASS rig selfcheck (node): container inline overflow-x:auto in reading + live, live ancestor chain has .cm-embed-block (+ .embed-actions), detach / innerHTML / move drops focus to body and fires blur + focusout first (like Chromium), shell CSS keeps 1.14.4 :hover overflow:hidden (inside @media (hover: hover)) + contain:paint, hosts structured like Obsidian, C4 red on 041aca9 assets, single-column annotate box red on 7ab44c6 (rerun blur commits half-typed text)');
})().catch(e => { console.error(e); process.exit(1); });

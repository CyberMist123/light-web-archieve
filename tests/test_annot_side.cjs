// 硬规矩（她定，10-03 第二次被改坏后加的守卫）：阅读视图里批注框永远在左栏图片 / 视频下面（.xhs-note .lb-side）。
// 坏过两次：1002 左栏晚渲染只等 3 秒；10-03 Obsidian 重画左栏后 reuseDom 把批注框挂回全文最底下就 return，没再挪回左栏。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

(async () => {
  delete globalThis.__lbState;
  const dom = makeDom();
  const NOTE = '_archive/xiaohongshu/n1/notes.json';
  const V = makeVault({ [NOTE]: JSON.stringify({ starred: false, annotations: [{ id: 'a1', ts: '2026-09-01T00:00:00Z', text: '旧的' }] }) });
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': { settings: {} } } }, metadataCache: { getCache: () => null } };
  globalThis.Notice = class {};
  const code = asset('lb-page-lib.js') + '\n' + asset('annotate-view.js');
  V.vault.adapter.getResourcePath = p => 'app://local/' + p;
  globalThis.Image = class { set src(v) { this._src = v; this.naturalWidth = 3; this.naturalHeight = 4; setTimeout(() => this.onload && this.onload(), 0); } };
  const A = dataviewBlock({ dom, app, code, folder: 'Web/Xiaohongshu', params: { itemId: 'xhs-n1', notePath: NOTE } });
  // 笔记阅读视图：.markdown-preview-view.xhs-note 里有左栏 .lb-side（图片 / 视频），批注块在全文最底下渲染
  A.host.classList.add('xhs-note');
  let side = A.host.createEl('div', { cls: 'lb-side' });
  const video = side.createEl('video');
  video.setAttribute('poster', '../../_archive/xiaohongshu/n1/raw/v0001/assets/cover-001.webp');
  await A.run(); await tick(5);
  // 视频封面：poster 换成 Obsidian 能加载的地址，框按封面比例（3:4），点了再加载
  assert.equal(video.getAttribute('poster'), 'app://local/_archive/xiaohongshu/n1/raw/v0001/assets/cover-001.webp');
  assert.equal(video.style.aspectRatio, '3 / 4');
  assert.equal(video.preload, 'none');
  const box = A.host.querySelector('.lba-annot');
  assert.ok(box, '有批注框');
  assert.equal(box.parentNode, side, '第一次渲染：批注框挪到左栏图片下面');

  // Obsidian 重画左栏（滚动卸载 / 重开这篇）：旧左栏连同批注框被摘掉，换一个新的左栏
  side.remove();
  side = A.host.createEl('div', { cls: 'lb-side' });
  await A.rerun(); await tick(5);
  assert.equal(A.host.querySelectorAll('.lba-annot').length, 1, '只有一个批注框');
  assert.equal(A.host.querySelector('.lba-annot'), box, '复用原来的批注框（正在打的字不丢）');
  assert.equal(box.parentNode, side, 'Dataview 复用页面后批注框仍在左栏，不掉到全文最底下');
  console.log('PASS annotate: box stays under the left-column images after Obsidian rebuilds the column and Dataview reuses the page');
})().catch(e => { console.error(e); process.exit(1); });

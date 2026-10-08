// 批次 D 地基（复审补）：lb-page-lib 在真 Chromium 里的几何 / 层叠。
//   ① LB.busy 的遮罩只盖住目标：目标没定位（static）时临时给 position:relative，遮罩 rect = 目标 rect，不溢出到整页；恢复后 position 还原。
//   ② lb-shared 排在页面样式前面：head 里先有旧的页面样式（热部署不重启，chat-view 原地复用 lbchat-style），页面对共用规则的覆盖照样生效。
//   ③ 帧 / 计时改用词法名字（让 tests/_clock.cjs 整个生效）后，restoreScroll 在真浏览器里照样滚到位、不报错。
// 两条在 e6db07f（地基第一版）上都是红的：遮罩盖住 .markdown-preview-view 整页；lb-shared 追加在 head 末尾、把页面覆盖盖回去。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const log = (...a) => console.log(...a);
(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const data = shell.makeCatalogData({ n: 4 });
  try {
    for (const host of ['page-reading', 'page-live']) {
      const tag = host === 'page-live' ? '实时预览' : '阅读视图';
      // ① busy 遮罩的几何
      let page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
      let S = await shell.page(page, { host, data, code: shell.readAsset('lb-page-lib.js') + `
const LB = lbPageLib(dv, app, 'catalog'); window.__LB = LB;
if (await LB.reuseDom()) return;
const host = LB.mountHost('t');
const card = host.createEl('div', { cls: 'probe-card' });
card.style.cssText = 'width:220px;height:120px;margin:40px 0 0 60px;background:#eee';
LB.keep(card, { version: await LB.data.version() });` });
      const r = await page.evaluate(() => {
        const card = document.querySelector('.probe-card');
        window.__done = window.__LB.busy(card, '正在收藏…');
        const veil = card.querySelector('.lb-busy-veil');
        const a = card.getBoundingClientRect(), b = veil.getBoundingClientRect();
        const pick = x => ({ top: Math.round(x.top), left: Math.round(x.left), width: Math.round(x.width), height: Math.round(x.height) });
        return { card: pick(a), veil: pick(b), position: card.style.position };
      });
      log(`busy 遮罩 ${tag}:`, JSON.stringify(r));
      assert.deepEqual(r.veil, r.card, `${tag}：遮罩正好盖住目标，不溢出到整页`);
      assert.equal(r.position, 'relative');
      await S.rerun();
      assert.ok(await page.$('.probe-card .lb-busy-veil'), '重跑不影响进行中的遮罩（host 不被清空）');
      const after = await page.evaluate(() => { window.__done(); const c = document.querySelector('.probe-card'); return { veil: !!c.querySelector('.lb-busy-veil'), position: c.style.position, busy: c.classList.contains('is-busy') }; });
      assert.deepEqual(after, { veil: false, position: '', busy: false }, `${tag}：恢复原样`);
      await page.close();
    }

    // ② lb-shared 排在页面样式前面
    const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
    await shell.page(page, { host: 'page-reading', data, code: `
if (!document.getElementById('lbchat-style')) {
  const old = document.createElement('style'); old.id = 'lbchat-style';
  old.textContent = '.lbchat .lb-page-nav{grid-column:1;justify-self:start}';   // 页面自己的覆盖（同等优先级，靠后写的赢）
  document.head.appendChild(old);
}
` + shell.readAsset('lb-page-lib.js') + `
const LB = lbPageLib(dv, app, 'chat');
if (await LB.reuseDom()) return;
const host = LB.mountHost('t');
const wrap = host.createEl('div', { cls: 'lbchat' });
wrap.style.display = 'grid'; wrap.style.gridTemplateColumns = '1fr 1fr 1fr';
wrap.createEl('div', { cls: 'lb-page-nav', text: '目录 · 问收藏' });
LB.keep(wrap, { version: await LB.data.version() });` });
    const o = await page.evaluate(() => {
      const ids = [...document.head.querySelectorAll('style')].map(s => s.id).filter(x => x === 'lb-shared' || x === 'lbchat-style');
      const nav = document.querySelector('.lb-page-nav'), cs = getComputedStyle(nav);
      return { order: ids, gridColumnStart: cs.gridColumnStart, justifySelf: cs.justifySelf };
    });
    log('lb-shared 与页面样式的顺序:', JSON.stringify(o));
    assert.deepEqual(o.order, ['lb-shared', 'lbchat-style'], 'lb-shared 插到已有的页面样式前面');
    assert.equal(o.gridColumnStart, '1', '页面对共用规则的覆盖生效（没被 lb-shared 盖回 grid-column:2）');
    assert.equal(o.justifySelf, 'start');
    // ③ 帧 / 计时改用词法名字后，在真浏览器里照样能跑（requestAnimationFrame 不带 this 调用不报 Illegal invocation）
    const S2 = await shell.page(await browser.newPage({ viewport: { width: 1000, height: 700 } }), { host: 'page-reading', data, code: shell.readAsset('lb-page-lib.js') + `
const LB = lbPageLib(dv, app, 'catalog'); window.__LB = LB;
const host = LB.mountHost('t'); host.createEl('div').style.height = '3000px';` });
    const restored = await S2.page.evaluate(async () => ({ ok: await window.__LB.restoreScroll(400, { holdMs: 200 }), top: document.querySelector('.markdown-preview-view').scrollTop }));
    log('restoreScroll（真浏览器）:', JSON.stringify(restored));
    assert.deepEqual(restored, { ok: true, top: 400 }, 'restoreScroll 在真浏览器里滚到位');
    assert.deepEqual(await S2.pageErrors(), [], '没有页面报错');
    await S2.page.close();
    await page.close();
  } finally { await browser.close(); }
  console.log('PASS page-lib geometry: busy veil covers exactly its target in reading + live (static target gets position:relative, restored after); lb-shared placed before an existing page style so page overrides win; restoreScroll works in a real browser with lexical rAF / performance');
})().catch(e => { console.error(e); process.exit(1); });

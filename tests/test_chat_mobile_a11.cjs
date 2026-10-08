// 批次 D · L2 A11：手机 / 插件没启用——问收藏页只读：排版照常（Dataview 的 dv.el 兜底渲染）、跳转可用、绝不写盘。
'use strict';
const assert = require('node:assert/strict');
const { makeMiniMd } = require('./_mini_md.cjs');
const { tick, src, openChat } = require('./_fake_L2.cjs');

(async () => {
  const turns = [
    { id: 'u1', role: 'user', content: '担担面', askedAt: '2026-10-02T12:00:00+10:00' },
    { id: 'a1', role: 'assistant', q: '担担面', content: '## 结论\n\n有汤的 [来源1]', sources: [src('a', 1)], related: [] },
  ];
  for (const isMobile of [true, false]) {
    // 旧会话（不在历史里）：电脑上会补进历史，只读时不写
    const C = await openChat({ turns, noPlugin: true, isMobile, run: false,
      files: { 'Catalog.md': '---\nlb-page: catalog\n---\n' } });
    // Dataview 的 dv.el：块级 markdown（真 Dataview 也是整段渲染）
    const md = makeMiniMd();
    C.A.dv.el = (tag, text, attrs = {}) => { const el = C.A.container.createEl(tag, attrs); md.render(text, el); return el; };
    C.app.metadataCache.getFileCache = f => (f.path === 'Catalog.md' ? { frontmatter: { 'lb-page': 'catalog' } } : null);
    C.V.resetCounts();
    await C.A.run(); await tick(20);
    // (a) 历史回答排好版
    const h2 = C.answers()[0].querySelector('.lbchat-md h2');
    assert.ok(h2 && h2.textContent === '结论', '历史回答是排好版的');
    // (b) 输入框藏起来；页顶一句只读说明
    assert.equal(C.q('.lbchat-composer').hidden, true);
    assert.equal(C.q('.lbchat-ro').textContent, isMobile ? '手机上可以看历史问答；提问、导出、来源窗格要在电脑上用' : 'Link Brain Actions 插件没启用，这页只能看');
    // 只留「复制」；来源行没有选中圈 / 保留 / ×；followBar 不显示
    assert.deepEqual(C.answers()[0].querySelector('.lbchat-actions').querySelectorAll('button').map(b => b.textContent), ['复制']);
    assert.equal(C.qa('.lbchat-src-pin').length + C.qa('.lbchat-src-del').length + C.qa('.lbchat-src-check').length, 0);
    assert.equal(C.q('.lbchat-followbar').hidden, true);
    // (c) 点 [来源1] → openLinkText(lbPath('Web/a.md'))；「浏览收藏」走 LB.openPage('catalog')
    C.answers()[0].querySelector('.lbchat-cite').onclick({ stopPropagation() {} }); await tick(5);
    assert.deepEqual(C.app.workspace.opened.at(-1).slice(0, 1), ['Web/a.md']);
    C.qa('.lb-page-nav button').find(b => b.textContent === '浏览收藏').onclick(); await tick(5);
    assert.deepEqual(C.app.workspace.opened.at(-1).slice(0, 1), ['Catalog.md']);
    // (e) 历史面板：看得到，没有隐私开关 / 选中圈；点一段只在内存里切换
    C.q('.lbchat-hist').onclick({ stopPropagation() {} }); await tick(5);
    assert.equal(C.dom.document.querySelector('.lbchat-histpriv'), null);
    assert.equal(C.dom.document.querySelectorAll('.lbchat-histcheck').length, 0);
    // (d) 全程没写盘（含启动时的旧会话补进历史）
    assert.deepEqual(C.V.writes, {}, JSON.stringify(C.V.writes));
    // (f) 没弹原生 alert
    assert.deepEqual(C.A.alerts, []);
  }
  console.log('PASS chat L2 A11: no plugin (phone / disabled) → read-only page: answers rendered via dv.el, composer hidden + 只读 line (phone / desktop wording), only 复制, cite / 浏览收藏 open via openLinkText / lb-page, history viewable without toggles, zero writes, no alert');
})().catch(e => { console.error(e); process.exit(1); });

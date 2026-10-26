// 1021 她：点引用 → 右侧原帖跳到那一处（插件 locateOnePassage）。真浏览器里量：
//   ① 正文按 <p data-p> 锚点直达、原句包进临时高亮；② 锚点文字对不上（旧渲染 / 库重建过）退回逐字原文找；
//   ③ 评论按 data-cid、折叠的评论区自动展开；④ 图片按文件名切轮播到那张图；⑤ 文字稿 details 打开；
//   ⑥ 只滚原帖自己的滚动区，外层（工作区）scrollTop 不动，不出「上一处 / 下一处」条；⑦ 找不到就什么都不做（fail-open）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), vm = require('vm'), path = require('path');
const shell = require('../_obsidian_shell.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {} } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'obsidian-plugins/link-brain-actions/main.js'), 'utf8'), context);
const proto = context.module.exports.prototype;
const METHODS = ['evidenceTargets', 'passageTarget', 'scrollWithinNote', 'flashPassage', 'markPassageSentence', 'locateOnePassage'];
const methods = Object.fromEntries(METHODS.map(n => [n, proto[n].toString()]));

const HTML = `<style>
#outer{height:400px;overflow:auto}#reader{height:2000px}.lb-scroll{height:300px;overflow:hidden}.lb-carousel{display:flex;overflow-x:auto;width:300px}.lb-slide{flex:0 0 300px}
.lb-evidence-hit{outline:2px solid blue}
</style>
<div id="outer"><div style="height:600px">上面占位</div><div id="reader"><div class="markdown-source-view" style="display:none"><div class="lb-note"><div class="lb-body"><p data-p="1">中间这段讲做法：牛肉先逆纹切条，用黑胡椒和一点点生抽腌十分钟。然后下锅大火快煎，不要翻太多次。</p></div><section class="lb-detail"><div class="lb-comments"><article class="lb-comment" data-cid="c2"><div class="lb-replies"><details><summary>展开</summary><article class="lb-comment lb-reply" data-cid="c2.1"><div class="lb-comment-text">作者回复：可以，但鸡肉要少腌一会儿，不然口感会柴。</div></article></details></div></article></div></section></div></div><div class="markdown-preview-view"><div class="lb-note">
<div class="lb-carousel"><figure class="lb-slide"><img src="../../_archive/xiaohongshu/x/raw/v0001/assets/image-001.webp" width="300" height="100"></figure><figure class="lb-slide"><img src="../../_archive/xiaohongshu/x/raw/v0001/assets/image-002.webp" width="300" height="100"></figure></div>
<div class="lb-scroll">
<div class="lb-body"><p data-p="0">开头一段讲背景，和做法没有关系，只是铺垫的话。</p><p data-p="1">中间这段讲做法：牛肉先逆纹切条，用黑胡椒和一点点生抽腌十分钟。然后下锅大火快煎，不要翻太多次。</p><p data-p="2">结尾一段感谢大家收看，记得点赞收藏。</p></div>
<details class="lb-transcript"><summary>视频文字稿</summary><div class="lb-body"><p data-p="0">稿子第一段。</p><p data-p="1">稿子第二段讲火候，全程大火，颜色变深就出锅。</p></div></details>
<div style="height:500px"></div>
<section class="lb-detail"><div class="lb-comments">
<article class="lb-comment" data-cid="c1"><div class="lb-comment-text">一楼：做了，好吃。</div></article>
<article class="lb-comment" data-cid="c2"><div class="lb-comment-text">二楼：请问能用鸡肉吗</div><div class="lb-replies"><details><summary>展开</summary><article class="lb-comment lb-reply" data-cid="c2.1"><div class="lb-comment-text">作者回复：可以，但鸡肉要少腌一会儿，不然口感会柴。</div></article></details></div></article>
</div></section>
</div></div></div></div></div>`;

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 900, height: 500 } });
    await page.setContent(HTML);
    const out = await page.evaluate(async methods => {
      const plugin = {};
      for (const [name, code] of Object.entries(methods)) plugin[name] = new Function('return ' + (code.startsWith('async ') ? code.replace('async ', 'async function ') : 'function ' + code))();
      const root = document.querySelector('#reader'); const outer = document.querySelector('#outer'); const scroll = root.querySelector('.lb-scroll');
      outer.scrollTop = 0; scroll.scrollTop = 0;
      const leaf = { view: { containerEl: root } };
      const go = async part => { const request = leaf.lbEvidenceRequest = {}; const ok = await plugin.locateOnePassage(leaf, part, request); await new Promise(r => setTimeout(r, 450)); /* 等平滑滚动停下 */ const hit = root.querySelector('.lb-evidence-hit'); return { ok, hit: hit ? hit.textContent || hit.getAttribute('src') : '', mark: !!root.querySelector('.lb-locate-mark'), outer: outer.scrollTop, scroll: scroll.scrollTop, bars: root.querySelectorAll('.lb-evidence-bar').length }; };
      const r = {};
      const inPreview = () => { const h = root.querySelector('.lb-evidence-hit'); return !!(h && h.closest('.markdown-preview-view')); };
      // ① 锚点直达 + 原句高亮（段 1 里只亮「先逆纹切条…」那一句）；隐藏的编辑视图里有同一段，必须落到阅读视图那份
      r.anchor = await go({ field: 'body', text: '牛肉先逆纹切条，用黑胡椒和一点点生抽腌十分钟。', offset: 20, paras: [1] });
      r.anchorMarkOnlySentence = r.anchor.hit.includes('逆纹切条') && !r.anchor.hit.includes('结尾');
      r.anchorInPreview = inPreview();
      // ② 锚点指错段（旧渲染）→ 退回逐字找，仍落在段 1
      r.stale = await go({ field: 'body', text: '然后下锅大火快煎，不要翻太多次。', paras: [0] });
      // ③ 评论楼中楼：data-cid 直达，折叠自动展开
      r.comment = await go({ field: 'comments', text: '可以，但鸡肉要少腌一会儿', comment_labels: ['c2.1'] });
      r.commentOpen = root.querySelector('.markdown-preview-view .lb-replies details').open; r.commentInPreview = inPreview();
      // ④ 图片：按文件名切到第 2 张
      r.image = await go({ field: 'ocr', text: '小贴士', images: ['图2'], assets: ['raw/v0001/assets/image-002.webp'] });
      r.carouselLeft = root.querySelector('.lb-carousel').scrollLeft;
      // ④b 视频帖：封面 slide 隐藏，落到 <video poster=封面> 上
      const vc = document.createElement('div'); vc.className = 'lb-carousel'; vc.id = 'vc'; vc.innerHTML = '<figure class="lb-slide"><video poster="../../_archive/xiaohongshu/v/raw/v0001/assets/cover-001.webp" width="300" height="100"></video></figure><figure class="lb-slide" style="display:none"><img src="../../_archive/xiaohongshu/v/raw/v0001/assets/cover-001.webp"></figure>';
      root.querySelector('.markdown-preview-view .lb-note').prepend(vc);
      r.video = await go({ field: 'ocr', text: '封面字', images: ['图1'], assets: ['raw/v0001/assets/cover-001.webp'] });
      r.videoTag = (root.querySelector('.lb-media-hit') || {}).tagName;
      vc.remove();
      // ⑤ 文字稿：details 打开
      r.transcript = await go({ field: 'transcript', text: '全程大火，颜色变深就出锅', paras: [1] });
      r.transcriptOpen = root.querySelector('.lb-transcript').open;
      // ⑦ 找不到：不动
      await new Promise(r => setTimeout(r, 300));
      const before = scroll.scrollTop;
      r.missing = await go({ field: 'body', text: '完全没有的一句话完全没有的一句话完全没有', paras: [7] });
      r.missingMoved = scroll.scrollTop !== before;
      // 6 秒后临时高亮拆掉、文字不变
      await new Promise(r => setTimeout(r, 6200));
      r.cleared = !root.querySelector('.lb-locate-mark') && root.querySelector('.lb-body p[data-p="1"]').textContent.includes('牛肉先逆纹切条，用黑胡椒');
      return r;
    }, methods);
    console.log(JSON.stringify(out));
    assert.ok(out.anchor.ok && out.anchor.mark && out.anchorMarkOnlySentence && out.anchorInPreview, '① 锚点直达、只亮那一句、落在可见的阅读视图');
    assert.ok(out.commentInPreview, '③ 评论落在可见的阅读视图，不是隐藏的编辑视图');
    assert.ok(out.stale.ok && out.stale.hit.includes('大火快煎'), '② 锚点对不上退回原文找');
    assert.ok(out.comment.ok && out.comment.hit.includes('鸡肉要少腌') && out.commentOpen, '③ 评论楼中楼直达并展开');
    assert.ok(out.image.ok && out.image.hit.endsWith('image-002.webp') && out.carouselLeft > 0, '④ 图片切到第 2 张');
    assert.ok(out.video.ok && out.videoTag === 'VIDEO', '④b 视频帖封面落到 video 上：' + JSON.stringify([out.video, out.videoTag]));
    assert.ok(out.transcript.ok && out.transcriptOpen && out.transcript.hit.includes('全程大火'), '⑤ 文字稿打开并定位');
    for (const k of ['anchor', 'stale', 'comment', 'image', 'transcript', 'missing']) { assert.equal(out[k].outer, 0, k + '：外层滚动区没被卷动'); assert.equal(out[k].bars, 0, k + '：不出工具条'); }
    assert.ok(out.transcript.scroll > 0 && out.image.scroll > 0, '原帖自己的滚动区滚到了那一段：' + JSON.stringify([out.transcript.scroll, out.image.scroll]));
    assert.ok(!out.missing.ok && !out.missing.hit && !out.missingMoved, '⑦ 找不到就不动');
    assert.ok(out.cleared, '6 秒后临时高亮拆掉、文字原样');
    console.log('PASS cite jump (1021): anchor jump + sentence mark, stale anchor falls back to text, comment data-cid opens fold, image by filename, transcript opens, outer never scrolls, fail-open');
    await page.close();
    // ── 问收藏页：悬停 [来源N] 胶囊 → 原文小卡（标题 · 段k · 来源类型 · 原文前几行）；移开收起；点了交给插件跳那一段 ──
    const chat = await browser.newPage({ viewport: { width: 1200, height: 800 } });
    const excerpts = [{ seg: 1, field: 'body', text: '开头一段讲背景。', offset: 0, paras: [0] }, { seg: 2, field: 'ocr', text: '小贴士：牛肉逆纹切条，黑胡椒多放一点', images: ['图2'], assets: ['raw/v0001/assets/image-002.webp'] }];
    const turns = [{ role: 'user', content: '牛肉怎么切' }, { role: 'assistant', content: '逆纹切条 [来源1 段2]。', q: '牛肉怎么切', sources: [{ id: 'a', citation: 1, title: '黑椒牛肉意面', note: 'Web/a.md', tier: 'primary', excerpts }], related: [] }];
    const pluginInit = (p, app, W) => {
      W.lb = { opened: [] };
      p.settings = { models: [{ name: 'DeepSeek' }], activeModel: 'DeepSeek', hiddenCats: [] };
      p.renderMarkdownInto = async (md, el) => { for (const para of md.split(/\n\n+/)) { const e = document.createElement('p'); e.textContent = para; el.append(e); } };
      p.archiveSourceState = () => ({ reader: false, compare: false });
      p.openArchiveSource = async (note, host, compare, evidence) => { W.lb.opened.push({ note, n: (evidence || []).length });
        // 假右栏：插件开笔记后页面自己去里面定位
        let r = document.querySelector('#fake-reader'); if (!r) { r = document.createElement('div'); r.id = 'fake-reader'; r.style.cssText = 'position:fixed;right:0;top:0;width:320px;height:600px;overflow:hidden'; r.innerHTML = '<div class="markdown-preview-view"><div class="lb-note"><div class="lb-carousel" style="display:flex;overflow-x:auto;width:300px"><figure class="lb-slide" style="flex:0 0 300px"><img src="../../_archive/xiaohongshu/a/raw/v0001/assets/image-001.webp" width="300" height="100"></figure><figure class="lb-slide" style="flex:0 0 300px"><img src="../../_archive/xiaohongshu/a/raw/v0001/assets/image-002.webp" width="300" height="100"></figure></div><div class="lb-body"><p data-p="0">开头一段讲背景。</p></div></div></div>'; document.body.append(r); }
        W.lb.reader = r; };
      p.archiveLeaves = () => ({ reader: W.lb.reader ? { view: { containerEl: W.lb.reader } } : null });
      p.modelState = () => ({ usable: true }); p.warmAnswerWorker = () => false;
    };
    const S = await shell.page(chat, { host: 'page-reading', kind: 'chat', theme: 'light', plugin: {}, pluginInit, data: { built_at: '2026-10-08T10:00:00+10:00', items: [] },
      files: { '_archive/chat-session.json': JSON.stringify({ turns }), '_archive/chat-archive.json': '{"entries":[]}', '_archive/chat-prefs.json': '{"follow":"sources"}' } });
    await S.settle(80);
    const cite = chat.locator('button.lbchat-cite').first();
    assert.equal(await cite.textContent(), '1', '1026 起胶囊只显示来源号上标');
    assert.equal(await cite.getAttribute('aria-label'), '来源1 第 2 段');
    await cite.hover(); await S.settle(500);
    const pop = await chat.evaluate(() => { const b = document.querySelector('.lbchat-citepop'); if (!b) return null; const r = b.getBoundingClientRect(); return { t: b.querySelector('.t').textContent, w: b.querySelector('.w').textContent, q: b.querySelector('.q').textContent, inView: r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight }; });
    assert.ok(pop && pop.t === '黑椒牛肉意面' && pop.w.includes('段2') && pop.w.includes('图片文字') && pop.w.includes('图2') && pop.q.includes('逆纹切条') && pop.inView, JSON.stringify(pop));
    await S.screenshot('cite-hover-pop');
    await chat.mouse.move(5, 5); await S.settle(100);
    assert.equal(await chat.locator('.lbchat-citepop').count(), 0, '移开就收');
    await cite.click(); await S.settle(100);
    const opened = await chat.evaluate(() => window.lb.opened);
    assert.equal(opened.length, 1); assert.equal(opened[0].note, 'Web/a.md'); assert.equal(opened[0].n, 0, '插件不再收证据段');
    await S.settle(900);
    const jumped = await chat.evaluate(() => { const r = document.querySelector('#fake-reader'); const hit = r.querySelector('.lb-evidence-hit'); return { src: hit ? hit.getAttribute('src') : null, left: r.querySelector('.lb-carousel').scrollLeft }; });
    assert.ok(jumped.src && jumped.src.endsWith('image-002.webp') && jumped.left > 0, '页面自己把右栏轮播切到第 2 张并描框：' + JSON.stringify(jumped));
    assert.equal(await chat.locator('.lbchat-citepop').count(), 0, '点了小卡也收');
    console.log('PASS cite hover (1021): popover shows title / 段2 · 图片文字 图2 / excerpt, hides on leave, click hands seg-2 evidence to plugin');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });

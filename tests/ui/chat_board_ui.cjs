// 1020 问收藏陈列版（技能 layout: board）：真浏览器截图 + 断言（套 Obsidian 外壳，合成数据，不读真 vault）。
//   宽 / 窄 / 暗色截图；分模块 + 先看这几个 + 每条封面；点封面 = 右侧打开那篇原帖；没网址的写「看原帖」；
//   不认识的段落（可补）照 Markdown 接在下面；「存成笔记」写进 报告/ 且带封面嵌图和出处双链；格式对不上就照普通 Markdown。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const COLORS = ['#c9b79c', '#9fb4c7', '#b7c9a8', '#d6b3b3', '#b9b0d0', '#c7c09a'];
const cover = (id, i) => `_archive/xiaohongshu/${id}/raw/v0001/assets/cover-001.webp`;
const svg = c => 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400"><rect width="300" height="400" fill="${c}"/><rect x="30" y="40" width="240" height="150" rx="10" fill="#ffffff66"/><rect x="30" y="220" width="180" height="16" rx="8" fill="#ffffff88"/><rect x="30" y="250" width="140" height="16" rx="8" fill="#ffffff66"/></svg>`);
const IDS = ['p1', 'p2', 'p3', 'p4', 'p5', 'p6'];
const RESOURCES = Object.fromEntries(IDS.map((id, i) => [cover(id, i), svg(COLORS[i])]));

const BOARD_MD = `# 多 agent 群聊项目陈列
> 给自己搭多 AI 群聊挑参考：6 篇里抽出 6 个能直接看的项目
## 先看这几个
- **Raven** —— 角色分工最清楚，先看它怎么拆调研 / 写码 / 设计[来源1]
- **群聊式工作台** —— 界面最接近你想要的「一个群里多个 AI」[来源2]
- **鼠鼠施工队** —— 开源、能直接跑[来源3]
- **Raven 角色表** —— 同一篇里给的角色表，可以直接抄[来源1]
## 多 agent 框架
做底座时看：怎么拆角色、谁来调度
- **Raven** · https://github.com/example/raven —— 帖里：不做万能 agent，把调研、写码、设计拆给不同角色，连续跑几天；借鉴：角色表照抄一份，调度层别学它的硬编码顺序[来源1]
- **多 agent 调度台** · 看原帖 —— 帖里：作者自己搓的调度台，能看每个 agent 在干嘛；借鉴：「谁在说话」的状态条可以直接借[来源4][来源1]
## 群聊界面
- **群聊式工作台** · https://example.com/workbench —— 帖里：所有 AI 在一个群里，@ 谁谁回；借鉴：@ 的交互和消息分色[来源2]
- **鼠鼠施工队** · github.com/example/shushu —— 帖里：开源，多 AI 协作群聊，自带几个角色模板；借鉴：角色模板的写法[来源3]
- **四个 AI 的群** —— 帖里：只有截图，没给项目；借鉴：群公告当共享记忆的思路[来源5]
## 记忆与会话
- **群聊 session 管理** · 看原帖 —— 帖里：每个 AI 一份 session，群消息按需分发；借鉴：分发规则[来源6]
- **群公告记忆** · 看原帖 —— 帖里：拿群公告当共享记忆，作者说「省掉一半 token」；借鉴：公告模板[来源6]
## 评论区还提到
- **无聊斋** —— 帖里：评论区回答纯好笑时第一个被推[来源6]
- **正经叭叭** —— 帖里：同上，评论区点名[来源6]
- **朋嗑儿** —— 帖里：同上，评论区点名[来源6]
## 可补
- 收藏里没有讲「多 AI 怎么防互相刷屏」的，可补：搜小红书「多agent 限流」`;

// pluginInit 是序列化进浏览器跑的：常量经参数带进去（见 openChat）
const pluginBody = (p, app, W, BOARD_MD, IDS) => {
  const lb = W.lb = { asks: [], opened: [] };
  p.settings = { models: [{ name: 'DeepSeek' }], activeModel: 'DeepSeek', hiddenCats: [] };
  p.renderMarkdownScoped = async (md, el) => { const h = await W.__miniMd.render(md, el); return { dispose() { h.dispose(); } }; };
  p.archiveSourceState = () => ({ reader: false, compare: false });
  // 假的右侧原帖：图片轮播两张 + 正文两段 + 收起的评论（点「帖里」跳转在这里面找）
  p.openArchiveSource = note => {
    lb.opened.push(note);
    let box = document.getElementById('fake-reader');
    if (!box) { box = document.createElement('div'); box.id = 'fake-reader'; document.body.append(box); }
    const id = note.replace(/^.*\//, '').replace(/\.md$/, '');
    const slide = n => `<figure class="lb-slide" style="flex:none;width:200px;margin:0"><img src="app://x/_archive/xiaohongshu/${id}/raw/v0001/assets/image-00${n}.webp?7" style="width:200px;height:120px"></figure>`;
    box.innerHTML = `<div class="lb-note"><div class="lb-carousel" style="display:flex;overflow-x:auto;width:200px">${slide(1)}${slide(2)}</div>`
      + `<div class="lb-body"><p>开头的铺垫话，和哪一条都不沾。</p><p>第一句先说背景，讲作者为什么想做这个项目。拿群公告当共享记忆，作者实测能省掉一半 token。最后一句讲别的事情，是和这条无关的收尾。</p></div>`
      + `<details><summary>评论</summary><div class="lb-comment-text">纯好笑的话无聊斋第一，正经叭叭也行</div></details></div>`;
    lb.reader = { view: { containerEl: box } };
    return Promise.resolve();
  };
  p.archiveLeaves = () => ({ reader: lb.reader || null });
  p.openSetupPage = () => {};
  p.modelState = () => ({ usable: true });
  p.warmAnswerWorker = () => false;
  p.stopArchiveAnswer = () => 1;
  const src = (id, n) => ({ id, citation: n, title: '来源帖 ' + id, note: 'Web/Xiaohongshu/' + id + '.md', tier: 'primary',
    cover: `_archive/xiaohongshu/${id}/raw/v0001/assets/cover-001.webp`, excerpts: [{ field: 'body', text: id + ' 正文' }] });
  p.answerArchive = req => {
    lb.asks.push(req.question);
    if (/普通/.test(req.question)) return Promise.resolve({ status: 'ok', mode: 'direct', skill: 'wiki', layout: 'board', markdown: '收藏里只有一篇讲这个[来源1]，没法分类陈列。', sources: [src('p1', 1)], related: [] });
    return Promise.resolve({ status: 'ok', mode: 'direct', skill: 'wiki', layout: 'board', markdown: BOARD_MD,
      sources: IDS.map((id, i) => src(id, i + 1)).map((s, i) => i === 4 ? { ...s, cover: '' } : s), related: [] });
  };
};

async function openChat(browser, { width = 1280, height = 1000, theme = 'light' } = {}) {
  const page = await browser.newPage({ viewport: { width, height } });
  const S = await shell.page(page, { host: 'page-reading', kind: 'chat', theme, plugin: {}, resources: RESOURCES,
    pluginInit: `(p, app, W) => (${pluginBody})(p, app, W, ${JSON.stringify(BOARD_MD)}, ${JSON.stringify(IDS)})`,
    data: { built_at: '2026-10-20T10:00:00+10:00', items: [] }, files: { '_archive/chat-session.json': '{"turns":[]}', '_archive/chat-archive.json': '{"entries":[]}',
      '_archive/xiaohongshu/p3/derived/agent.md': ['# 鼠鼠', '## 图片 OCR', '### 第1张（图1 · image-001.webp）', '封面字',
        '### 第2张（图2 · image-002.webp）', '鼠鼠施工队 开源 角色模板', '## 评论', ''].join(String.fromCharCode(10, 10)) } });
  await S.settle(60);
  return { page, S };
}
const ask = async (page, S, text, wait = 150) => { await page.click('.lbchat-search'); await page.keyboard.type(text); await page.keyboard.press('Enter'); await S.settle(wait); };

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const shots = [];
  try {
    let { page, S } = await openChat(browser);
    // 1020：输入框里模型下拉旁边「回答 · 报告」，默认回答；没有 +
    assert.equal(await page.locator('.lbchat-cplus').count(), 0);
    const modeOpt = label => page.locator('.lbchat-answermode .lbchat-seg-opt', { hasText: label });
    assert.ok(await modeOpt('回答').evaluate(e => e.classList.contains('is-on')));
    await modeOpt('报告').click(); await S.settle(20);
    assert.ok(await modeOpt('报告').evaluate(e => e.classList.contains('is-on')));
    await ask(page, S, '多agent群聊 帮我整理成 wiki');
    assert.equal(await page.evaluate(() => window.lb.asks[0]), '/报告 多agent群聊 帮我整理成 wiki', '报告档：问题前加 /报告 发给后端');
    assert.equal(await page.locator('.lbchat-user .lbchat-qmark', { hasText: '报告' }).count(), 1, '她那一问标「报告」');
    assert.equal(await page.locator('.lbchat-user').first().evaluate(e => e.textContent.includes('/报告')), false, '气泡里不显示标记');
    assert.equal(await page.locator('.lbboard').count(), 1, '陈列版渲染出来');
    assert.equal(await page.locator('.lbboard-title').textContent(), '多 agent 群聊项目陈列');
    // 1020 她：先看这几个里同一篇的合成一张卡（Raven 和 Raven 角色表都出自 p1）
    assert.equal(await page.locator('.lbboard-topcard').count(), 3);
    assert.deepEqual(await page.locator('.lbboard-topcard.is-multi .lbboard-name').allTextContents(), ['Raven', 'Raven 角色表']);
    assert.equal(await page.locator('.lbboard-topcard.is-multi .lbboard-cover').count(), 1);
    assert.equal(await page.locator('.lbboard-sec').count(), 4, '四个类别（可补不算类别）');
    assert.equal(await page.locator('.lbboard-row').count(), 8, '评论区只点名的三条合成一行');
    const thin = page.locator('.lbboard-row.is-thin');
    assert.deepEqual(await thin.locator('.lbboard-name').allTextContents(), ['无聊斋', '正经叭叭', '朋嗑儿']);
    assert.ok(!(await thin.textContent()).includes('同上'), '「同上，评论区点名」不再显示');
    // 连着出自同一篇：后一条不重复封面（留同宽空位）
    assert.ok(await page.locator('.lbboard-row', { hasText: '群公告记忆' }).locator('.lbboard-cover').evaluate(e => e.classList.contains('is-ghost')));
    // 1020 她：分类导航不在正文里，进左边目录（浮动板）：先看这几个 + 三类，类下面是条目
    assert.equal(await page.locator('.lbboard-navbtn').count(), 0);
    assert.deepEqual(await page.locator('.lbchat-toc .lbchat-toc-cat').allTextContents(), ['先看这几个', '多 agent 框架', '群聊界面', '记忆与会话', '评论区还提到']);
    assert.equal(await page.locator('.lbchat-toc .lbchat-toc-sub').count(), 10, '合成一行的名字在目录里也逐个列');
    // 网址：有的给链接，「看原帖」的写无链接
    assert.equal(await page.locator('.lbboard-row a.lbboard-url').count(), 3);
    assert.equal(await page.locator('.lbboard-row', { hasText: '鼠鼠施工队' }).locator('a.lbboard-url').getAttribute('href'), 'https://github.com/example/shushu', '裸域名补成 https 链接');
    assert.equal(await page.locator('.lbboard-url.is-none').count(), 0, '没网址就不写「无链接 · 看原帖」');
    assert.equal(await page.locator('.lbboard', { hasText: '无链接' }).count(), 0);
    // 帖里 / 借鉴分开
    const first = page.locator('.lbboard-sec').first().locator('.lbboard-row').first();
    assert.match(await first.locator('.lbboard-text').first().textContent(), /^帖里不做万能 agent/);
    assert.match(await first.locator('.lbboard-text.is-why').textContent(), /^借鉴角色表照抄一份/);
    assert.equal(await first.locator('.lbboard-text').first().evaluate(e => /\[来源/.test(e.textContent)), false, '引用号不留在正文里');
    // 封面：有图的是 img，没封面的（来源5）给占位字
    assert.ok(await first.locator('.lbboard-cover img').count() === 1);
    const noCover = page.locator('.lbboard-row', { hasText: '四个 AI 的群' }).locator('.lbboard-cover');
    assert.ok(await noCover.evaluate(e => e.classList.contains('is-empty')));
    // 「可补」照 Markdown 接在下面
    assert.match(await page.locator('.lbboard-rest').textContent(), /可补：搜小红书/);
    // 两条出处（来源4 + 来源1）
    assert.equal(await page.locator('.lbboard-row', { hasText: '多 agent 调度台' }).locator('.lbboard-srclink').count(), 2);
    shots.push(await S.screenshot('board-wide'));
    await page.evaluate(() => document.querySelector('.lbboard').scrollIntoView({ block: 'start' })); await S.settle(30);
    shots.push(await S.screenshot('board-wide-top'));
    // 点封面 = 右侧打开那篇原帖
    await first.locator('.lbboard-cover').click(); await S.settle(40);
    assert.deepEqual(await page.evaluate(() => window.lb.opened), ['Web/Xiaohongshu/p1.md']);
    await page.locator('.lbboard-topcard').nth(1).locator('.lbboard-cover').click(); await S.settle(40);
    assert.equal(await page.evaluate(() => window.lb.opened[1]), 'Web/Xiaohongshu/p2.md', '先看这几个的封面也能点开原帖');
    // 整张卡都能点：点文字也开原帖（和点来源一样）；点「出自」里的链接只开那一篇、不重复开
    await page.locator('.lbboard-row', { hasText: '多 agent 调度台' }).locator('.lbboard-text').first().click(); await S.settle(40);
    assert.equal(await page.evaluate(() => window.lb.opened.at(-1)), 'Web/Xiaohongshu/p4.md');
    const nOpen = await page.evaluate(() => window.lb.opened.length);
    await page.locator('.lbboard-row', { hasText: '多 agent 调度台' }).locator('.lbboard-srclink').nth(1).click(); await S.settle(40);
    assert.deepEqual(await page.evaluate(n => window.lb.opened.slice(n), nOpen), ['Web/Xiaohongshu/p1.md']);
    // 点「帖里」那段字 → 打开原帖并跳到那一处：正文段落（引号原话）、收起的评论（名字，自动展开）、图片（agent.md 里第 2 张的识别文字有名字 → 第 2 张）
    const hit = () => page.evaluate(() => { const e = document.querySelector('#fake-reader .lb-evidence-hit'); return e ? (e.tagName === 'IMG' ? 'img:' + e.getAttribute('src').replace(/^.*\//, '').replace(/\?.*$/, '') : e.textContent.slice(0, 12)) : null; });
    await page.locator('.lbboard-row', { hasText: '群公告记忆' }).locator('.lbboard-text').first().click(); await S.settle(250);
    assert.equal(await hit(), '拿群公告当共享记忆，作者', '长段落只标那一句');
    assert.equal(await page.evaluate(() => document.querySelector('#fake-reader .lb-locate-mark')?.textContent), '拿群公告当共享记忆，作者实测能省掉一半 token。');
    assert.equal(await page.evaluate(() => document.querySelector('#fake-reader mark')), null, '临时标记不用 <mark>（那是划重点的）');
    assert.deepEqual(await page.evaluate(() => [document.documentElement.scrollTop, document.body.scrollTop, (document.querySelector('.workspace') || {}).scrollTop || 0]), [0, 0, 0], '跳转不卷动外层（输入框悬空的根因）');
    await page.locator('.lbboard-row.is-thin .lbboard-chip', { hasText: '无聊斋' }).click(); await S.settle(250);
    assert.equal(await hit(), '纯好笑的话无聊斋第一，正');
    assert.equal(await page.evaluate(() => document.querySelector('#fake-reader details').open), true, '收起的评论自动展开');
    await page.locator('.lbboard-row', { hasText: '鼠鼠施工队' }).locator('.lbboard-text').first().click(); await S.settle(250);
    assert.equal(await hit(), 'img:image-002.webp', '图片切到第 2 张');
    // 目录里点条目跳到那一条
    await page.locator('.lbchat-toc .lbchat-toc-sub', { hasText: '群聊 session 管理' }).click(); await S.settle(60);
    // 「存成笔记」：报告/ 下一篇 md，带封面嵌图、出处双链、网址
    await page.locator('.lbchat-savenote').click(); await S.settle(80);
    const note = await page.evaluate(() => { const k = Object.keys(window.__files || {}).find(x => /报告\//.test(x)); return k ? [k, window.__files[k]] : null; })
      .catch(() => null);
    const written = note || await page.evaluate(async () => { const ad = window.app.vault.adapter; const p = '报告/多 agent 群聊项目陈列.md'; return (await ad.exists(p)) ? [p, await ad.read(p)] : null; });
    assert.ok(written, '存成笔记写出了文件');
    assert.match(written[1], /^---\nlb-report: board/);
    assert.match(written[1], /## 出处\n\n!\[\[_archive\/xiaohongshu\/p1\/raw\/v0001\/assets\/cover-001\.webp\|110\]\]/);
    assert.equal((written[1].match(/cover-001\.webp/g) || []).length, 5, '封面只在「出处」排一次（6 篇里 1 篇没封面）');
    assert.ok(!/\[来源\d+\]/.test(written[1]), '引用号都换成了双链');
    assert.match(written[1], /\[\[Web\/Xiaohongshu\/p1\|《来源帖 p1》\]\]/);
    assert.match(written[1], /- 网址：\[github\.com\/example\/raven\]\(https:\/\/github\.com\/example\/raven\)/);
    assert.ok(!written[1].includes('无链接'));
    assert.ok(written[1].includes('**无聊斋**（评论区回答纯好笑时第一个被推） · **正经叭叭** · **朋嗑儿**'), '只点名的并成一行');
    assert.ok(!written[1].includes('同上'));
    assert.match(written[1], /- 借鉴：角色表照抄一份/);
    assert.ok((await page.evaluate(() => window.opened)).some(a => /报告\//.test(String(a[0]))), '存完打开那篇笔记');
    // 输入框上方一行：「追问 · 新对话」+ 清空上下文，不再有「改为……」
    assert.deepEqual(await page.locator('.lbchat-followmode .lbchat-seg-opt').allTextContents(), ['追问', '新对话']);
    assert.equal(await page.locator('.lbchat-clearbox .lbchat-clearall').textContent(), '清空上下文');
    assert.equal(await page.locator('.lbchat-followbar', { hasText: '改为' }).count(), 0);
    await page.evaluate(() => { const b = document.querySelector('.lbchat-body'); if (b) b.scrollTop = b.scrollHeight; }); await S.settle(30);
    shots.push(await S.screenshot('board-composer'));
    // 切回「回答」：不带标记；格式对不上（只有一句话）→ 照普通 Markdown
    await modeOpt('回答').click(); await S.settle(20);
    await ask(page, S, '普通的一问');
    assert.equal(await page.evaluate(() => window.lb.asks.at(-1)), '普通的一问');
    const last = page.locator('.lbchat-answer').last();
    assert.equal(await last.locator('.lbboard').count(), 0, '第二答不是陈列格式，照普通 Markdown');
    assert.match(await last.locator('.lbchat-md').textContent(), /没法分类陈列/);
    assert.equal(await last.locator('.lbchat-savenote').count(), 0, '不是陈列的回答没有「存成笔记」');
    await page.close();

    ({ page, S } = await openChat(browser, { theme: 'dark' }));
    await ask(page, S, '多agent群聊 帮我整理成 wiki');
    await page.evaluate(() => document.querySelector('.lbboard').scrollIntoView({ block: 'start' })); await S.settle(30);
    shots.push(await S.screenshot('board-dark'));
    await page.close();

    // 窄窗（右侧开着原帖时问收藏这一栏 < 1080）：对话区左边贴「目录」浮签，点了在旁边弹出目录浮动板
    ({ page, S } = await openChat(browser, { width: 900, height: 900 }));
    await ask(page, S, '多agent群聊 帮我整理成 wiki');
    assert.equal(await page.locator('.lbchat-toc').isVisible().catch(() => false), false);
    assert.ok(await page.locator('.lbchat-tocfab').isVisible(), '窄窗有目录浮签');
    await page.locator('.lbchat-tocfab').click(); await S.settle(40);
    assert.ok(await page.locator('.lbchat-tocpanel.is-side').isVisible());
    assert.ok((await page.locator('.lbchat-tocpanel .lbchat-toc-cat').count()) >= 4);
    shots.push(await S.screenshot('board-narrow-toc'));
    await page.close();

    ({ page, S } = await openChat(browser, { width: 420, height: 900 }));
    await ask(page, S, '多agent群聊 帮我整理成 wiki');
    const noH = await page.evaluate(() => { const b = document.querySelector('.lbchat-body') || document.body; return b.scrollWidth <= b.clientWidth + 1; });
    assert.ok(noH, '窄屏不横向溢出');
    await page.evaluate(() => document.querySelector('.lbboard').scrollIntoView({ block: 'start' })); await S.settle(30);
    shots.push(await S.screenshot('board-narrow'));
    await page.close();
    console.log('PASS chat_board_ui', shots.join(' '));
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });

// 1026 她：问收藏点 [来源N] 跳原帖时灵时不灵 + [来源1] 太多（交接《LWA 引用跳转修复 + NotebookLM 式证据对照》第五节）。
// 假右栏照真机的毛病搭：阅读格复用，openFile 先切文件、内容晚一拍才画（画好之前上一篇的 DOM 还在）；新的打开会取消上一次还没画的。
// 验的是结果：右栏文件、看得见的 data-lb-item、高亮元素（图片 src / 评论楼号 / 段序号）、日志里的请求号四者对得上。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';

(async () => {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const dom = makeDom();
  const A_EX = [
    { seg: 1, field: 'body', text: '先定设计体系再让AI动手写页面', paras: [0] },
    { seg: 2, field: 'ocr', text: '配色卡片：主色辅色和点缀色', images: ['图2'], assets: ['raw/v0001/assets/image-002.webp'] },
    { seg: 3, field: 'ocr', text: '封面：写前端前必读', images: ['图1'], assets: ['raw/v0001/assets/image-001.webp'] },
    { seg: 4, field: 'comments', text: '鸡肉也可以但要少腌一会儿', comment_labels: ['c5.1'] },
    { seg: 5, field: 'ocr', text: '圆角和间距表', images: ['图3'], assets: ['raw/v0001/assets/image-003.webp'] },
    { seg: 6, field: 'body', text: '我最近也在做网站，先建一个视觉参考池。下面分享6个网站：curated.design 高质量官网，land-book.com 落地页结构，landing.gallery 页面区块', paras: [1, 2] },
  ];
  const srcAtt = { id: 'xhs-att', citation: 5, title: '带附件', note: 'Web/a.md', tier: 'primary',
    attachments: [{ name: 'x.pdf', downloaded: true, file: 'D:/vault/_archive/xhs/att/attachments/x.pdf', markdown: 'D:/vault/_archive/xhs/att/derived/attachments/1.md' }],
    excerpts: [{ seg: 1, field: 'attachments', text: '第二页里讲的重要规则写在这里，别的页没有' }] };
  const srcA = { id: 'xhs-a', citation: 1, title: '前端规范', note: 'Web/a.md', tier: 'primary', excerpts: A_EX };
  const srcB = { id: 'xhs-b', citation: 2, title: '另一篇', note: 'Web/b.md', tier: 'primary', excerpts: [{ seg: 1, field: 'ocr', text: 'B 帖的图', images: ['图1'], assets: ['raw/v0001/assets/image-101.webp'] }] };
  const srcOld = { id: 'xhs-old', citation: 3, title: '老帖', note: 'Web/old.md', tier: 'primary', excerpts: [{ seg: 1, field: 'body', text: '老帖正文这一段讲火候', paras: [0] }] };
  // 拆图前的旧回答：同一个段号 2 落在两张图上
  const srcDup = { id: 'xhs-a', citation: 4, title: '前端规范（旧答）', note: 'Web/a.md', tier: 'primary', excerpts: [
    { seg: 2, field: 'ocr', text: '封面：写前端前必读', images: ['图1'], assets: ['raw/v0001/assets/image-001.webp'] },
    { seg: 2, field: 'ocr', text: '配色卡片：主色辅色和点缀色', images: ['图2'], assets: ['raw/v0001/assets/image-002.webp'] }] };
  const md = [
    '先定设计体系 [来源1 段1]，配色看图 [来源1 段2]，封面写着必读 [来源1 段3]，配色再说一遍 [来源1 段2]。',   // P0
    '评论区说鸡肉也行 [来源1 段4]',                                       // P1
    'B 帖那张图 [来源2 段1]',                                             // P2
    '改写得完全不沾边的一句话 [来源1]',                                   // P3
    '圆角那张图 [来源1 段5]',                                             // P4（图3 没画出来）
    '段号写错了 [来源1 段9]',                                             // P5
    '老帖没有 data-lb-item [来源3 段1]',                                  // P6
    '历史回答：主色辅色和点缀色的配色卡片 [来源1]',                       // P7（没段号，上下文唯一对上段 2）
    '旧答案同号两段、上下文不沾边 [来源4 段2]',                           // P8
    '旧答案同号两段：主色辅色和点缀色的配色卡片 [来源4 段2]',             // P9
    '那张配色图 [来源1 图2]',                                             // P10（模型写图号）
    '轮播第四张 [来源1 图4]',                                             // P11（证据里没有图4 的识别文字）
    '[来源1]《前端规范》— 配色起点。必看：图1。',                           // P12（来源导读：胶囊在句首，看整行）
    '站点有 curated.design（高质量官网）、land-book.com（落地页结构）[来源1 段6]',   // P13（一段证据盖两段原文）
    '附件里写了规则 [来源5 段1]',                                         // P14（附件）
    '这一段讲配色卡片怎么用',
    '![[_archive/xiaohongshu/a/raw/v0001/assets/image-002.webp|360]]',   // 图单独一段：挪到上一段旁边
  ].join('\n\n');
  const turns = [{ role: 'user', content: '前端怎么做' },
    { role: 'assistant', content: md, q: '前端怎么做', sources: [srcA, srcB, srcOld, srcDup, srcAtt], related: [] }];
  const V = makeVault({ [DATA]: JSON.stringify({ built_at: '2026-10-03T10:00:00+10:00', items: [] }),
    '_archive/chat-session.json': JSON.stringify({ turns }), '_archive/chat-archive.json': '{"entries":[]}',
    '_archive/xhs/att/attachments/x.pdf': '%PDF', '_archive/xhs/att/derived/attachments/1.md': '# x.pdf\n\n## 第 1 页\n\n封面\n\n## 第 2 页\n\n第二页里讲的重要规则写在这里，别的页没有\n' });
  V.vault.adapter.basePath = 'D:\\vault';

  // ── 假右栏 ──
  const box = dom.document.createElement('div');
  dom.document.body.append(box);
  const img = (car, f) => { const fig = car.createEl('figure', { cls: 'lb-slide' }); const im = fig.createEl('img'); im.setAttribute('src', 'app://x/D:/vault/_archive/xiaohongshu/' + f + '?1'); return im; };
  const PAGES = {
    'Web/a.md': () => {
      const note = box.createEl('div', { cls: 'lb-note' }); note.setAttribute('data-lb-item', 'xhs-a');
      const car = note.createEl('div', { cls: 'lb-carousel' }); img(car, 'a/raw/v0001/assets/image-001.webp'); img(car, 'a/raw/v0001/assets/image-002.webp'); img(car, 'a/raw/v0001/assets/image-004.jpg');   // 图3 没画
      const body = note.createEl('div', { cls: 'lb-body' }); const p0 = body.createEl('p', { text: '先定设计体系再让AI动手写页面' }); p0.setAttribute('data-p', '0');
      body.createEl('p', { text: '我最近也在做网站，先建一个视觉参考池。' }).setAttribute('data-p', '1');
      body.createEl('p', { text: '下面分享6个网站：curated.design 高质量官网，land-book.com 落地页结构，landing.gallery 页面区块' }).setAttribute('data-p', '2');
      const c5 = note.createEl('article', { cls: 'lb-comment' }); c5.setAttribute('data-cid', 'c5'); c5.createEl('div', { cls: 'lb-comment-text', text: '五楼：能换鸡肉吗' });
      const det = c5.createEl('details'); det.open = false;
      const r = det.createEl('article', { cls: 'lb-comment lb-reply' }); r.setAttribute('data-cid', 'c5.1'); r.createEl('div', { cls: 'lb-comment-text', text: '鸡肉也可以但要少腌一会儿' });
    },
    'Web/b.md': () => {
      const note = box.createEl('div', { cls: 'lb-note' }); note.setAttribute('data-lb-item', 'xhs-b');
      img(note.createEl('div', { cls: 'lb-carousel' }), 'b/raw/v0001/assets/image-101.webp');
    },
    'Web/old.md': () => {   // 旧渲染：没有 data-lb-item
      const note = box.createEl('div', { cls: 'lb-note' });
      const p0 = note.createEl('div', { cls: 'lb-body' }).createEl('p', { text: '老帖正文这一段讲火候' }); p0.setAttribute('data-p', '0');
    },
  };
  const DELAY = { 'Web/a.md': 150, 'Web/b.md': 400, 'Web/old.md': 300 };
  let pending = 0;
  const leaf = { view: { containerEl: box, file: null } };
  const opened = [];
  const plugin = {
    settings: { models: [] },
    renderMarkdownInto: async (text, el) => { for (const para of text.split(/\n\n+/)) { if (para.startsWith('![[')) el.createEl('p').createEl('span', { cls: 'internal-embed image-embed' }).createEl('img'); else el.createEl('p', { text: para }); } },
    archiveSourceState: () => ({ reader: true, compare: false }),
    archiveLeaves: () => ({ reader: leaf }),
    async openArchiveSource(note) {
      opened.push(note);
      if (leaf.view.file?.path === note) return;   // 同一篇再开：Obsidian 不重画
      leaf.view.file = { path: note };
      clearTimeout(pending);
      pending = setTimeout(() => { box.textContent = ''; PAGES[note](); }, DELAY[note]);
    },
    async answerArchive() { return { status: 'ok', markdown: 'x', sources: [], related: [] }; },
  };
  const app = { vault: V.vault, workspace: makeWorkspace(), plugins: { plugins: { 'link-brain-actions': plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null } };
  const A = dataviewBlock({ dom, app, code: asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js') });
  await A.run();

  const ps = A.section.querySelectorAll('p').filter(p => p.querySelector('button.lbchat-cite'));
  assert.equal(ps.length, 15);
  const caps = i => ps[i].querySelectorAll('button.lbchat-cite');
  const lastLog = () => JSON.parse(V.get('_archive/locate-last.json'));
  const click = (i, k = 0) => caps(i)[k].onclick({ stopPropagation() {} });
  const lit = () => box.querySelectorAll('.lb-evidence-hit');

  // ① 显示：按出处顺序编 1、2、3（像脚注）；同段完全相同的 (来源1, 段2) 只留第一个；同一出处在别段再出现沿用同一个号
  assert.deepEqual(caps(0).map(b => b.textContent + ':' + (b.dataset.seg || '')), ['1:1', '2:2', '3:3'], '只合并同一出处，编号按阅读顺序');
  assert.ok(!/ ，| 。/.test(ps[0].textContent), '拿掉的胶囊不留空格');
  assert.equal(caps(0)[1].getAttribute('aria-label'), '出处：前端规范');
  const all = A.section.querySelectorAll('button.lbchat-cite').map(b => Number(b.textContent));
  assert.ok(all.every((n, i) => n <= Math.max(0, ...all.slice(0, i)) + 1), '编号只会按顺序往上加：' + all.join(','));

  // ② 悬停：卡片显示的就是会跳的那段；对不上时说清楚只会打开原帖；悬停不碰右栏
  const pop = () => dom.document.body.querySelector('.lbchat-citepop');
  caps(0)[1].dispatchEvent(new dom.Event('focus'));
  assert.ok(pop().textContent.includes('图2') && pop().textContent.includes('配色卡片') && !pop().textContent.includes('段'), pop().textContent);
  caps(3)[0].dispatchEvent(new dom.Event('focus'));
  assert.equal(pop().textContent, '前端规范', '对不上原文（模型自己的概括）只写标题，不解释');
  caps(3)[0].dispatchEvent(new dom.Event('blur'));
  assert.equal(opened.length, 0, '悬停不打开原帖');

  // ③ 多图段号：段2 → 图2、段3 → 图1，各落各的图（第一次打开要等 a 画好）
  await click(0, 1); await tick(500);
  let log = lastLog();
  assert.equal(log.ok, true, JSON.stringify(log));
  assert.equal(log.target, 'asset:raw/v0001/assets/image-002.webp');
  assert.equal(log.file, 'Web/a.md'); assert.equal(log.shown, 'xhs-a');
  await click(0, 2); await tick(300);
  assert.equal(lastLog().target, 'asset:raw/v0001/assets/image-001.webp', '段3 = 图1');
  await click(0, 0); await tick(300);
  assert.equal(lastLog().target, 'para:0', '正文段命中 data-p');

  // ④ 评论楼中楼：折叠的 details 打开，亮的是 c5.1
  await click(1); await tick(300);
  log = lastLog();
  assert.equal(log.ok, true, JSON.stringify(log)); assert.equal(log.target, 'comment:c5.1');
  assert.equal(box.querySelector('details').open, true, '楼中楼展开了');

  // ⑤ A → B：B 画好之前 A 的 DOM 还在，不许在 A 里定位
  await click(2); await tick(150);
  assert.equal(box.querySelector('.lb-note').getAttribute('data-lb-item'), 'xhs-a', '（前提）这时右栏还是 A 的旧 DOM');
  await tick(600);
  log = lastLog();
  assert.equal(log.ok, true, JSON.stringify(log));
  assert.equal(log.shown, 'xhs-b'); assert.equal(log.target, 'asset:raw/v0001/assets/image-101.webp');
  assert.ok(log.waitMs >= 200, '等到 B 画好才找：' + log.waitMs);

  // ⑥ 快速连点 B → A：B 还没画完就点 A——右栏、高亮、日志都落在最后一次（A 段2 → 图2）
  await click(2); await tick(20);   // 已在 B：同篇不重画，直接定位
  await click(6); await tick(50);   // 开 old（300ms 才画）
  const lastReq = click(0, 1);      // 立刻改点 A（段2）
  await lastReq; await tick(600);
  log = lastLog();
  assert.equal(leaf.view.file.path, 'Web/a.md');
  assert.equal(box.querySelector('.lb-note').getAttribute('data-lb-item'), 'xhs-a', '右栏最后是 A');
  assert.equal(log.note, 'Web/a.md'); assert.equal(log.target, 'asset:raw/v0001/assets/image-002.webp');
  assert.ok(lit().every(el => el.getAttribute('src')?.includes('image-002')), '只有 A 的图2 亮着');

  // ⑦ A → B → A 同一拍里连点：只有最后一次真的打开
  const before = opened.length;
  click(2); click(1); await click(0, 2); await tick(400);
  assert.deepEqual(opened.slice(before), ['Web/a.md'], '中间那次被取代，没去开 B');
  assert.equal(lastLog().target, 'asset:raw/v0001/assets/image-001.webp');

  // ⑧ 老帖没有 data-lb-item：靠「文件对 + 打开后才画出来」判断，不把上一篇的 DOM 当成它
  await click(6); await tick(100);
  assert.ok(box.querySelector('.lb-note[data-lb-item="xhs-a"]'), '（前提）老帖画好之前 A 的 DOM 还在');
  await tick(500);
  log = lastLog();
  assert.equal(log.ok, true, JSON.stringify(log)); assert.equal(log.file, 'Web/old.md'); assert.equal(log.target, 'para:0');
  assert.ok(log.waitMs >= 200, '没把 A 的旧 DOM 当老帖：' + log.waitMs);

  // ⑨ 失败要诚实：没段号又对不上 → 只开原帖；指定图3 缺 → 不跳图1；段号不存在 → 不猜；旧答案同号两段消不了歧义 → 不猜
  for (const [i, why] of [[3, 'no-match'], [4, 'not-found'], [5, 'seg-missing'], [8, 'seg-ambiguous']]) {
    await click(i); await tick(400);
    log = lastLog();
    assert.equal(log.ok, false, `P${i}: ` + JSON.stringify(log)); assert.equal(log.why, why, `P${i}`);
    assert.ok(!log.target, `P${i} 没有落到任何元素`);
  }
  assert.equal(leaf.view.file.path, 'Web/a.md', '失败时原帖照样打开了');

  // ⑩ 历史回答没段号、上下文唯一对上 → 照跳；旧答案同号两段但上下文分得出 → 跳对的那张
  await click(7); await tick(300);
  assert.equal(lastLog().target, 'asset:raw/v0001/assets/image-002.webp', '没段号按上下文唯一选中段 2');
  await click(9); await tick(300);
  assert.equal(lastLog().target, 'asset:raw/v0001/assets/image-002.webp', '同号两段按上下文消歧');

  // ⑫ 第二轮：模型写图号 [来源1 图2] → 图2；证据里没有的图4 → 按文件名 image-004.* 找到；来源导读「必看：图1」→ 图1
  await click(10); await tick(300);
  assert.equal(lastLog().target, 'asset:raw/v0001/assets/image-002.webp', JSON.stringify(lastLog()));
  await click(11); await tick(300);
  assert.equal(lastLog().target, 'asset:raw/v0001/assets/image-004.jpg', JSON.stringify(lastLog()));
  await click(12); await tick(300);
  assert.equal(lastLog().target, 'asset:raw/v0001/assets/image-001.webp', '导读行按整行里的「图1」：' + JSON.stringify(lastLog()));
  // ⑬ 一段证据盖住原帖两段：按引用前那句（网站清单）挑第 2 段，不再落到作者开场那句
  await click(13); await tick(300);
  assert.equal(lastLog().target, 'para:2', JSON.stringify(lastLog()));
  // ⑭ 附件：在右栏旁边新开一页，PDF 跳到第 2 页
  const leavesBefore = app.workspace.leaves.length;
  await click(14); await tick(300);
  log = lastLog();
  assert.equal(log.ok, true, JSON.stringify(log)); assert.equal(log.target, 'attachment:_archive/xhs/att/attachments/x.pdf#page=2');
  assert.equal(app.workspace.leaves.length, leavesBefore + 1, '新开了一页');
  // 定位历史留最近几次（她一轮点好几处时排障用）
  assert.ok(JSON.parse(V.get('_archive/locate-history.json')).length >= 10);

  // ⑮ 回答里的图：单独一段的图挪进它前面那段开头，靠右并排（不再插在两段字中间），空出来的那段拿掉
  const em = A.section.querySelector('.lbchat-float-img');
  assert.ok(em, '图打上并排的类');
  assert.equal(em.parentElement.tagName, 'P'); assert.ok(em.parentElement.textContent.includes('这一段讲配色卡片怎么用'));
  assert.equal(em.parentElement.firstChild, em, '在那段开头（浮动从段首开始）');
  assert.ok(!A.section.querySelectorAll('.lbchat-md p').some(p => !p.textContent.trim() && !p.querySelector('img')), '没留下空段');

  // ⑪ 来源标题只打开帖子、不定位
  const n = opened.length, stamp = lastLog().at;
  const title = A.section.querySelectorAll('.lbchat-src-title, .lbchat-src a, a').find(a => a.textContent.includes('另一篇') && typeof a.onclick === 'function');
  assert.ok(title, '来源行里有「另一篇」的标题链接');
  await title.onclick({ preventDefault() {}, stopPropagation() {} }); await tick(600);
  assert.equal(opened.length, n + 1); assert.equal(leaf.view.file.path, 'Web/b.md'); assert.equal(lastLog().at, stamp, '标题点开不写定位日志');

  console.log('PASS cite jump (1026): (source,seg) merge + superscript; hover = click target; multi-image segs; comment reply; A→B waits for B; rapid clicks land on last; old note without data-lb-item; honest failures; history cites; title opens only');
})().catch(e => { console.error(e); process.exit(1); });

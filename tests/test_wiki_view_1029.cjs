// 10-29 个人 Wiki 页（wiki-view.js）：挂 host + 重跑复用、目录（文件夹 / 页 / 小标题）、点一段改一段 → Esc 经 wikiCall('save') 带 base_hash 存、
// 下一次用返回的 hash、CONFLICT 不丢字（固定句式 + 页顶草稿 + 换成磁盘版本）、引用开右栏 / 缺失、@ 补全插入、拖动排序存文件夹 order、
// 新建走 wikiCall('create')、没插件只读、整页没有 title / aria-label、hash 和 personal_wiki.content_hash 同口径（含纯 JS 回退）。
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const CODE = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('wiki-view.js');
const pyHash = text => crypto.createHash('sha1').update(text.replace(/\r\n?/g, '\n'), 'utf8').digest('hex').slice(0, 16);

// 合成数据（虚构，不含真实内容）
const TRAVEL = `---
id: pw-travel
title: 旅行
role: topic
index_tag: travel
order: ["pw-stay"]
tags: ["travel"]
created: 2026-10-01T10:00:00+08:00
updated: 2026-10-20T10:00:00+08:00
---

学懂怎么选，也记下偏好。

\`\`\`pages
\`\`\`
`;
const STAY = `---
id: pw-stay
title: 住宿偏好
role: page
tags: ["travel", "hotels"]
created: 2026-10-02T10:00:00+08:00
updated: 2026-10-27T21:10:00+08:00
---

为什么记：每次订酒店都从头翻收藏。

## 在意什么
- 安静 > 位置
- [ ] 预算上限？

## 参考
- [示例咖啡地图](lwa:it-1) — 喜欢这个思路
- [已经删掉的收藏](lwa:gone-9)
`;
const KYOTO = `---
id: pw-kyoto
title: 京都想住的地方
role: page
tags: ["travel"]
created: 2026-10-03T10:00:00+08:00
updated: 2026-10-10T10:00:00+08:00
---

种草先挂着。
`;
// Obsidian 里新建的页：没有 id、属性面板写的块状列表、CRLF
const TEA = '---\r\ntitle: 冷泡茶比例\r\ntags:\r\n  - 茶\r\n---\r\n\r\n1 克茶配 50 毫升水。\r\n';
const ITEMS = [
  { id: 'it-1', title: '示例咖啡地图', tags: ['travel'], summary: '海边的几家店', author: '示例作者 A', note: 'Web/示例/it-1.md', kind: 'image', attachment: 'none', search_fields: { body: '咖啡 地图' } },
  { id: 'it-2', title: '示例酒店差评怎么读', tags: ['hotels'], summary: '看差评', author: '示例作者 B', note: 'Web/示例/it-2.md', kind: 'video', attachment: 'none', search_fields: { body: '差评' } },
];
const FILES = {
  '_archive/catalog-data.json': JSON.stringify({ built_at: '2026-10-29T09:00:00+08:00', items: ITEMS }),
  'Wiki.md': '---\nlb-page: wiki\n---\n',
  '目录.md': '---\nlb-page: catalog\n---\n',
  '收藏搜索.md': '---\nlb-page: chat\n---\n',
  'PersonalWiki/旅行.md': TRAVEL,
  'PersonalWiki/住宿偏好.md': STAY,
  'PersonalWiki/京都想住的地方.md': KYOTO,
  'PersonalWiki/冷泡茶比例.md': TEA,
  'PersonalWiki/.history/pw-stay/log.json': '{"versions":[]}',
  'PersonalWiki/.trash/20261001-旧页.md': '---\nid: pw-old\ntitle: 旧页\n---\n',
};

// 像真插件的假 wikiCall（读写的是同一个假磁盘）：controllable delay（plugin.delay 毫秒，期间页面可以接着操作）、
// save / restore / delete 先拿磁盘上的全文算 hash 和 base_hash 比，对不上抛 CONFLICT（和 personal_wiki.save_page 一样），
// 对得上才写回假磁盘（V.set，会发 modify，页面照常走文件事件）；failAt = {op, n, code, message} 让第 n 次该操作失败一次；
// 抛出的错误和 main.js wikiCall 一样：Error(message) + .code + .result。
function fakeMeta(text) {
  const t = text.replace(/\r\n/g, '\n');
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(t);
  const meta = {};
  if (m) for (const line of m[1].split('\n')) { const mm = /^([\w-]+):\s*(.*)$/.exec(line); if (mm && mm[2].trim()) { const v = mm[2].trim(); try { meta[mm[1]] = /^["[]/.test(v) ? JSON.parse(v) : v; } catch { meta[mm[1]] = v; } } }
  return { meta, body: m ? t.slice(m[0].length).replace(/^\n+/, '') : t };
}
function fakeRender(p) {
  return ['---', `id: ${p.id}`, `title: ${p.title}`, `role: ${p.role || 'page'}`, p.index_tag ? `index_tag: ${p.index_tag}` : null,
    p.order && p.order.length ? `order: ${JSON.stringify(p.order)}` : null, `tags: ${JSON.stringify(p.tags || [])}`,
    p.created ? `created: ${p.created}` : null, `updated: ${p.updated}`, '---'].filter(Boolean).join('\n') + '\n\n' + String(p.body || '').replace(/^\n+|\n+$/g, '') + '\n';
}
function fakePlugin() {
  const calls = [], opened = [];
  let n = 0;
  const counts = {};
  const plugin = {
    calls, opened, delay: 1, failAt: null, V: null,
    pathOf(id) {
      for (const k of plugin.V.disk.keys()) {
        if (!/^PersonalWiki\/[^/]+\.md$/.test(k)) continue;
        const { meta } = fakeMeta(plugin.V.disk.get(k));
        const pid = meta.id || 'pf-' + crypto.createHash('sha1').update(k.slice(k.lastIndexOf('/') + 1)).digest('hex').slice(0, 10);
        if (pid === id) return k;
      }
      return null;
    },
    write(path, page) {
      const text = fakeRender(page);
      const next = `PersonalWiki/${page.title}.md`;
      if (path && path !== next) plugin.V.disk.delete(path);
      plugin.V.set(next, text);
      return { ...page, file: next.slice(13), hash: pyHash(text) };
    },
    check(id, base) {
      const path = plugin.pathOf(id);
      if (!path) throw Object.assign(new Error('找不到这一页'), { code: 'NOT_FOUND' });
      const text = plugin.V.disk.get(path);
      if (base && base !== pyHash(text)) throw Object.assign(new Error('这页在别处改过了（另一个窗口或 Obsidian 里），先重新打开再改'), { code: 'CONFLICT' });
      const { meta, body } = fakeMeta(text);
      return { path, meta, body };
    },
    async wikiCall(op, { args = [], input = null } = {}) {
      const call = { op, args, input };
      calls.push(call);
      await tick(plugin.delay);
      counts[op] = (counts[op] || 0) + 1;
      try {
        const f = plugin.failAt;
        if (f && f.op === op && f.n === counts[op]) { plugin.failAt = null; throw Object.assign(new Error(f.message), { code: f.code }); }
        call.result = run(op, args, input);
        return call.result;
      } catch (e) { e.result = { ok: false, code: e.code, message: e.message }; call.error = e; throw e; }
    },
    openArchiveSource(note, host, compare, ev) { opened.push([note, host, compare, ev]); return Promise.resolve(); },
  };
  const now = () => '2026-10-29T12:00:' + pad(++n % 60) + '+08:00';
  const pad = x => String(x).padStart(2, '0');
  function run(op, args, input) {
    if (op === 'save') {
      const { path, meta, body } = plugin.check(input.id, input.base_hash);
      const page = { id: input.id, title: input.title ?? meta.title, role: meta.role || 'page', index_tag: meta.index_tag || '', order: input.order ?? meta.order ?? [],
        tags: input.tags ?? meta.tags ?? [], created: meta.created || '', updated: now(), body: input.body ?? body };
      return { ok: true, code: '', message: '已保存', page: plugin.write(path, page), changed: true, version: { ver: n, kind: input.kind } };
    }
    if (op === 'restore') {
      const bi = args.indexOf('--base-hash');
      const { path, meta } = plugin.check(args[0], bi > 0 ? args[bi + 1] : '');
      const page = { id: args[0], title: '住宿偏好', role: meta.role || 'page', tags: ['travel'], created: meta.created || '', updated: now(), body: '很早以前的正文。' };
      return { ok: true, message: '已恢复；恢复前的内容也在历史里', page: plugin.write(path, page), changed: true };
    }
    if (op === 'create') {
      const topic = args.includes('--topic');
      const fi = args.indexOf('--folder');
      const page = { id: 'pw-new' + (++n), title: args[0], role: topic ? 'topic' : 'page', index_tag: topic ? args[0] : '', order: [], tags: topic ? [args[0]] : fi > 0 ? [args[fi + 1]] : [], created: now(), updated: now(), body: '' };
      return { ok: true, message: `已新建《${args[0]}》`, page: plugin.write(null, page) };
    }
    if (op === 'history') return { ok: true, versions: [{ ver: 2, at: '2026-10-29T11:00:00+08:00', kind: 'auto', note: '', add: 1, del: 0 }, { ver: 1, at: '2026-10-02T10:00:00+08:00', kind: 'create', note: '新建', add: 0, del: 0 }] };
    if (op === 'version') return { ok: true, version: { ver: Number(args[1]), title: '住宿偏好', tags: ['travel'], body: '很早以前的正文。' } };
    if (op === 'index') return { ok: true, message: '索引已更新' };
    throw Object.assign(new Error('没写这个 op：' + op), { code: 'BAD_ARGS' });
  }
  return plugin;
}

async function open({ plugin = null, isMobile = false, params = {}, files = null, expand = true } = {}) {
  delete globalThis.__lbState; delete globalThis.__lbListeners; delete globalThis.__lbWikiDrafts; delete globalThis.__lbPark;
  const made = makeApp({ files: files ? { ...FILES, ...files } : FILES, plugin, isMobile, frontmatter: { '目录.md': { 'lb-page': 'catalog' }, '收藏搜索.md': { 'lb-page': 'chat' }, 'Wiki.md': { 'lb-page': 'wiki' } } });
  if (plugin) plugin.V = made.V;
  const dom = makeDom();
  const A = dataviewBlock({ dom, app: made.app, code: CODE, params });
  await A.run();
  await tick(5);
  // 10-31 起目录默认只展开当前页所在的文件夹；下面的老用例照旧从展开的目录里点页（「全部展开」= 工具行第 4 颗）
  if (expand) { const b = A.qa('.lbw-tools button')[3]; if (b) { b.click(); await tick(1); } }
  return { A, dom, ...made };
}
const texts = (A, sel) => A.qa(sel).map(e => e.textContent);
const key = (A, el, k, extra = {}) => el.dispatchEvent(new A.window.KeyboardEvent('keydown', { key: k, ...extra }));
const tocPage = (A, title) => A.qa('.lbw-tpage').find(b => b.textContent === title);

(async () => {
  const plugin = fakePlugin();
  const { A, dom, V, app } = await open({ plugin, expand: false });

  // ── 挂 host、样式进 head、首页 ──
  assert.equal(A.container.children.length, 0, '页面挂在 host 上，不进 dv.container');
  const host = A.container.nextSibling;
  assert.ok(host.classList.contains('lb-page-host') && host.dataset.lbRole === 'wiki');
  assert.ok(dom.document.getElementById('lb-wiki-style'), '样式挂 head');
  assert.match(dom.document.getElementById('lb-wiki-style').textContent, /LB Digits Inline/);
  assert.match(dom.document.getElementById('lb-wiki-style').textContent, /\.lbw\{--lbw-serif:"LB Digits Inline",var\(--lb-font-serif\)/, 'Digits Inline 只挂在 .lbw 的字栈里');
  const wrap = A.q('.lbw');
  assert.deepEqual(texts(A, '.lb-page-nav button'), ['浏览收藏', '问收藏', 'Wiki'], '页头沿用现有胶囊三页切换');
  assert.ok(A.q('.lb-page-nav button.is-current').textContent === 'Wiki');
  assert.match(A.q('.lbw-sub').textContent, /^全部 3 页 · 更新 \d\d\/\d\d \d\d:\d\d$/, '篇数行：只数 role=page，更新时间取最新');
  assert.equal(A.qa('.lbw-fold').length, 3, '首页：一个文件夹 + 未归类 + 新文件夹');
  assert.ok(A.q('.lbw-ov'), '首页有 OVERVIEW 数字');
  assert.ok(A.q('.lbw-map svg') || A.q('.lbw-map .lbw-graph'), '首页有关系图');

  // ── 目录：文件夹（编号 · 名字 · 页数）、文件夹里的页按 order、未归类、.history / .trash 不算 ──
  const folds = texts(A, '.lbw-tfold');
  assert.ok(folds[0].includes('旅行') && folds[0].endsWith('2'), folds.join('|'));
  assert.ok(folds[1].includes('未归类'));
  assert.deepEqual(texts(A, '.lbw-tpage'), [], '首页：文件夹默认都收起（10-31：只展开当前页所在的那个）');
  A.qa('.lbw-tools button')[3].click(); await tick(1);   // 全部展开
  assert.deepEqual(texts(A, '.lbw-tpage'), ['住宿偏好', '京都想住的地方', '冷泡茶比例'], '文件夹里 order 在前，未归类在后；块状 tags 认得');
  assert.ok(!A.q('.lbw-tpage[data-page="pw-old"]'), '.trash 里的不算');
  assert.ok(texts(A, '.lbw-ttags button').includes('#hotels') && texts(A, '.lbw-ttags button').includes('#茶'));

  // ── 重跑：同一个 wrap，PersonalWiki 没变就不重读 ──
  const reads = V.reads['PersonalWiki/住宿偏好.md'];
  await A.rerun(); await tick(5);
  assert.equal(A.q('.lbw'), wrap, '重跑：同一个 wrap');
  assert.equal(V.reads['PersonalWiki/住宿偏好.md'], reads, '磁盘签名没变，不重读');

  // ── 打开一页：标题、元信息、当前页小标题进目录、引用编号 ──
  tocPage(A, '住宿偏好').click();
  assert.equal(A.q('.lbw-ptitle').value, '住宿偏好');
  assert.deepEqual(texts(A, '.lbw-thead'), ['1在意什么', '2参考'], '当前页的 H1–H4 进目录');
  const cites = A.qa('.lbw-cite');
  assert.equal(cites.length, 2);
  assert.equal(cites[0].querySelector('.lbw-ref').textContent, '1', '编号 = 本页第一次出现的顺序');
  assert.ok(cites[1].classList.contains('is-missing') && cites[1].querySelector('.lbw-ref').textContent === '缺', '找不到的收藏：缺');
  cites[0].click(); await tick(2);
  assert.equal(plugin.opened.length, 1);
  assert.equal(plugin.opened[0][0], 'Web/示例/it-1.md', '引用开右栏：openArchiveSource(笔记, 本页容器, false, [])');
  assert.equal(plugin.opened[0][1], A.container);
  assert.equal(plugin.opened[0][2], false); assert.deepEqual(plugin.opened[0][3], []);
  assert.ok(A.q('.lbw-cite.is-open'), '开着的那篇圈变实心');
  A.qa('.lbw-cite')[1].click(); await tick(2);
  assert.equal(plugin.opened.length, 1, '缺失的不开');
  assert.ok(A.notices.at(-1).includes('找不到了'));

  // ── 点一段 → 编辑框 + 层级条；Esc → wikiCall('save') 带 base_hash（= Python content_hash）；下次用返回的 hash ──
  A.qa('.lbw-blk')[0].click();
  let ta = A.q('.lbw-ed');
  assert.ok(ta && A.q('.lbw-edbar'), '点一段出编辑框和层级工具条');
  assert.deepEqual(texts(A, '.lbw-edbar button'), ['正文', 'H1', 'H2', 'H3', '列表', '待办', 'AI 改'], '10-31：浅色小工具条，AI 改接上了');
  assert.ok(!A.q('.lbw-edbar button[disabled]'));
  assert.equal(ta.parentElement.tagName, 'P', '原地改：编辑框套在和阅读时同一个元素里');
  assert.equal(ta.value, '为什么记：每次订酒店都从头翻收藏。');
  ta.value = '为什么记：订酒店前先看这页。';
  key(A, ta, 'Escape'); await tick(10);
  let saves = plugin.calls.filter(c => c.op === 'save');
  assert.equal(saves.length, 1, 'Esc 收起 = 存一次');
  assert.equal(saves[0].input.id, 'pw-stay');
  assert.equal(saves[0].input.base_hash, pyHash(STAY), 'base_hash = 磁盘全文 SHA-1 前 16 位（和 personal_wiki.content_hash 一样）');
  assert.ok(saves[0].input.body.startsWith('为什么记：订酒店前先看这页。\n\n## 在意什么'));
  assert.equal(saves[0].input.kind, 'auto');
  assert.ok(!A.q('.lbw-ed'), '编辑框收起');
  assert.ok(A.q('.lbw-doc').textContent.includes('订酒店前先看这页'));
  // Ctrl+Alt+2 改层级
  A.qa('.lbw-blk')[0].click(); ta = A.q('.lbw-ed');
  ta.setSelectionRange(0, 0);
  key(A, ta, '2', { ctrlKey: true, altKey: true });
  assert.ok(ta.closest('h2') && ta.value.startsWith('为什么记'), 'Ctrl+Alt+2 = H2（记号不显示在框里，框换进 h2）');
  key(A, ta, '0', { ctrlKey: true, altKey: true });
  assert.equal(ta.parentElement.tagName, 'P', 'Ctrl+Alt+0 = 回到正文');
  ta.value = '为什么记：订酒店前先看这一页。';
  key(A, ta, 'Escape'); await tick(10);
  saves = plugin.calls.filter(c => c.op === 'save');
  assert.equal(saves[1].result.page.hash, pyHash(V.get('PersonalWiki/住宿偏好.md')), '假插件真写了磁盘');
  assert.equal(saves[1].input.base_hash, saves[0].result.page.hash, '下一次保存用上一次返回的 hash');

  // ── @ 补全：打 @ + 词 → 弹层；Enter 插入 [标题](lwa:id) — ──
  A.qa('.lbw-blk')[0].click(); ta = A.q('.lbw-ed');
  ta.value = '再看 @咖啡'; ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.dispatchEvent(new A.window.Event('input'));
  const pop = A.q('.lbw-pop');
  assert.ok(pop, '@ 出补全弹层');
  assert.ok(pop.querySelector('button.is-on').textContent.startsWith('示例咖啡地图'));
  assert.ok(pop.querySelector('small').textContent.includes('图文 · 示例作者 A · 已在《住宿偏好》引用'));
  key(A, ta, 'Enter');
  assert.equal(ta.value, '再看 [示例咖啡地图](@1) — ', 'Enter 插入引用（框里显示短号，存时换回完整 id），光标停在破折号后');
  assert.ok(!A.q('.lbw-pop'), '插入后弹层关掉');
  key(A, ta, 'Escape'); await tick(10);
  saves = plugin.calls.filter(c => c.op === 'save');
  assert.ok(saves[2].input.body.startsWith('再看 [示例咖啡地图](lwa:it-1) —'));

  // ── CONFLICT：别处改过 → 固定句式、她的字留在页顶草稿、页面换成磁盘版本；「用我这份覆盖」再存（base_hash = 新磁盘 hash） ──
  const OTHER = STAY.replace('为什么记：每次订酒店都从头翻收藏。', '在别处改过的正文。');
  V.set('PersonalWiki/住宿偏好.md', OTHER);   // 「Obsidian 里改了」：假插件按磁盘核 base_hash，自然撞 CONFLICT
  A.qa('.lbw-blk')[0].click(); ta = A.q('.lbw-ed');
  ta.value = '她刚写的一句话。';
  key(A, ta, 'Escape'); await tick(20);
  assert.ok(A.notices.some(m => m.startsWith('没保存上，内容还在，可重试：')), A.notices.join(' | '));
  assert.ok(A.q('.lbw-doc').textContent.includes('在别处改过的正文'), '换成磁盘上的版本');
  const draft = A.q('.lbw-draft');
  assert.ok(draft && draft.textContent.includes('没保存上的改动'), '她的改动留在页顶');
  const apply = A.qa('.lbw-draft button').find(b => b.textContent === '用我这份覆盖');
  assert.ok(apply);
  apply.click(); await tick(20);
  saves = plugin.calls.filter(c => c.op === 'save');
  const last = saves.at(-1);
  assert.equal(last.input.base_hash, pyHash(OTHER), '覆盖时 base_hash = 磁盘上那一版');
  assert.ok(last.input.body.startsWith('她刚写的一句话。'), '存的是她那份');
  assert.ok(!A.q('.lbw-draft'), '存上了，草稿条收起');

  // ── 待办勾选也是一次保存 ──
  const before = saves.length;
  A.q('.lbw-task input').click(); await tick(10);
  saves = plugin.calls.filter(c => c.op === 'save');
  assert.equal(saves.length, before + 1);
  assert.ok(saves.at(-1).input.body.includes('- [x] 预算上限？'));

  // ── 历史侧栏：版本列表、选一版看差异 ──
  A.q('.lbw-hbtn:not(.is-more)').click(); await tick(10);
  assert.ok(!A.q('.lbw-side').hidden, '历史在本页右侧栏');
  assert.equal(A.qa('.lbw-ver').length, 2);
  A.qa('.lbw-ver')[1].click(); await tick(10);
  assert.ok(A.q('.lbw-diff'), '选一版：和现在的逐行差异');
  assert.ok(A.q('.lbw-diff .is-d').textContent.includes('很早以前的正文'));
  key(A, dom.document, 'Escape');
  assert.ok(A.q('.lbw-side').hidden, 'Esc 关历史');

  // ── 拖动排序：同一文件夹内，存文件夹页的 order ──
  const kyoto = tocPage(A, '京都想住的地方'), stay = tocPage(A, '住宿偏好');
  assert.equal(kyoto.getAttribute('draggable'), 'true');
  kyoto.dispatchEvent(new A.window.Event('dragstart', { dataTransfer: { setData() {} } }));
  stay.dispatchEvent(new A.window.Event('dragover', { clientY: -1 }));
  assert.ok(stay.classList.contains('is-drop-before'));
  stay.dispatchEvent(new A.window.Event('drop', { clientY: -1 }));
  await tick(10);
  saves = plugin.calls.filter(c => c.op === 'save');
  assert.equal(saves.at(-1).input.id, 'pw-travel');
  assert.deepEqual(saves.at(-1).input.order, ['pw-kyoto', 'pw-stay'], '顺序记在文件夹页的 order');
  assert.deepEqual(texts(A, '.lbw-tpage').slice(0, 2), ['京都想住的地方', '住宿偏好']);

  // ── Ctrl+F：目录里搜标题；Esc 关 ──
  key(A, dom.document, 'f', { ctrlKey: true });
  const find = A.q('.lbw-find');
  assert.ok(find, 'Ctrl+F 出目录搜索');
  find.value = '京都'; find.dispatchEvent(new A.window.Event('input'));
  assert.deepEqual(texts(A, '.lbw-tpage'), ['京都想住的地方']);
  assert.ok(A.q('.lbw-tpage mark'));
  key(A, find, 'Escape');
  assert.ok(!A.q('.lbw-find'));

  // ── 新建：页内弹层（不用 window.prompt），wikiCall('create') ──
  A.qa('.lbw-tools button').find(b => b.textContent.includes('新页面')).click();
  const form = A.q('.lbw-modal');
  assert.ok(form, '新页面弹层');
  form.querySelector('input').value = '新的一页';
  await form.requestSubmit(); await tick(10);
  const cr = plugin.calls.filter(c => c.op === 'create').at(-1);
  assert.equal(cr.args[0], '新的一页');
  assert.ok(cr.args.includes('--folder') && cr.args.includes('travel'), '从文件夹里的页新建：默认放进同一个文件夹');
  assert.equal(A.q('.lbw-ptitle').value, '新的一页');
  assert.ok(A.q('.lbw-ed'), '新建后直接进编辑');
  key(A, A.q('.lbw-ed'), 'Escape'); await tick(5);

  // ── 没有 title / aria-label；不用浏览器对话框 ──
  const all = [host, ...host.all()];
  const bad = all.filter(e => e.getAttribute && (e.getAttribute('title') != null || e.getAttribute('aria-label') != null));
  assert.equal(bad.length, 0, '整页没有 title / aria-label：' + bad.map(e => e.tagName + '.' + e.className).join(','));
  assert.equal(A.alerts.length, 0);
  assert.ok(!/window\.(alert|confirm|prompt)\(|\balert\(|\bprompt\(/.test(asset('wiki-view.js')));
  assert.ok(!/adapter\.write\(/.test(asset('wiki-view.js')), '页面不直接写 PersonalWiki');

  // ── 存完几秒建一次索引（连着存只建一次） ──
  await tick(3300);
  assert.equal(plugin.calls.filter(c => c.op === 'index').length, 1, '索引防抖：只建一次');

  // ── 没有 crypto.subtle：纯 JS SHA-1 回退，hash 一样 ──
  {
    const p2 = fakePlugin();
    const { A: B } = await open({ plugin: p2, params: { crypto: undefined } });
    B.qa('.lbw-tpage').find(b => b.textContent === '冷泡茶比例').click();
    assert.ok(B.q('.lbw-doc').textContent.includes('1 克茶配 50 毫升水'));
    B.qa('.lbw-blk')[0].click();
    const t2 = B.q('.lbw-ed'); t2.value = '1 克茶配 60 毫升水。';
    key(B, t2, 'Escape'); await tick(10);
    const s = p2.calls.find(c => c.op === 'save');
    assert.equal(s.input.base_hash, pyHash(TEA), 'CRLF 文件的 hash 也对得上');
    assert.match(s.input.id, /^pf-[0-9a-f]{10}$/, '没写 id 的页：按文件名派生 pf-…（和后端 scan 一样）');
    assert.equal(s.input.id, 'pf-' + crypto.createHash('sha1').update('冷泡茶比例.md').digest('hex').slice(0, 10));
  }

  // ── 没插件：只读（能看、能跳、能开原文；没有编辑框 / 新建 / 历史） ──
  {
    const { A: C, app: app2 } = await open({ plugin: null });
    assert.ok(C.q('.lbw-ro').textContent.includes('只能看'));
    assert.equal(C.q('.lbw-hbtn'), null, '没有「…」和历史');
    assert.ok(!C.q('.lbw-fold.is-new'), '没有新文件夹');
    C.qa('.lbw-tpage').find(b => b.textContent === '住宿偏好').click();
    assert.equal(C.q('.lbw-addblk'), null);
    C.qa('.lbw-blk')[0].click();
    assert.equal(C.q('.lbw-ed'), null, '点段落不出编辑框');
    assert.equal(C.q('.lbw-ptitle').getAttribute('readonly'), '');
    assert.equal(C.q('.lbw-task input').disabled, true);
    C.q('.lbw-cite').click(); await tick(2);
    assert.equal(app2.workspace.opened.at(-1)[0], 'Web/示例/it-1.md', '没插件：引用照样打开笔记');
    assert.ok(C.q('.lbw-hint').textContent.includes('只能看'));
  }
  // 手机：只读那句
  {
    const { A: M } = await open({ plugin: null, isMobile: true });
    assert.ok(M.q('.lbw-ro').textContent.startsWith('手机上只能看'));
  }

  // ═════ 10-29 审查（Codex）：每条一个独立用例，各自新开一页（修之前都是红的） ═════
  const F = 'PersonalWiki/住宿偏好.md';
  const NOT_SAVED = '没保存上，内容还在，可重试：';
  const failed = [];
  const reviewCase = async (name, fn) => { try { await fn(); console.log('  ok   ' + name); } catch (e) { failed.push(name); console.log('  FAIL ' + name + '\n       ' + String(e && e.message).split('\n')[0]); } };

  // 审查 1：整页 Markdown 改着、别处改了这页 → 存的时候必须撞 CONFLICT，不许拿刷新来的新 hash 盖掉别处的改动
  await reviewCase('审查1 整页 Markdown + 别处改了', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    B.q('.lbw-hbtn.is-more').click();
    B.qa('.lbw-pop button').find(b => b.textContent.startsWith('整页 Markdown')).click();
    const src = B.q('.lbw-srced'); assert.ok(src, '整页 Markdown 编辑框');
    src.focus();
    src.value = src.value.replace('为什么记：每次订酒店都从头翻收藏。', '为什么记：她在源码里改的。');
    src.dispatchEvent(new B.window.Event('input'));
    VB.set(F, OTHER);
    await tick(700);   // 文件事件防抖（500ms）后页面重读磁盘
    key(B, src, 'Escape'); await tick(40);
    assert.ok(P.calls.some(c => c.op === 'save' && c.error && c.error.code === 'CONFLICT'), '保存撞 CONFLICT');
    assert.ok(VB.get(F).includes('在别处改过的正文') && !VB.get(F).includes('她在源码里改的'), '别处的改动没被静悄悄盖掉');
    assert.ok(B.q('.lbw-draft'), '她的那份留在页顶');
    assert.ok(B.notices.some(m => m.startsWith(NOT_SAVED)));
    await tick(2200);   // 源码框的 2 秒自动保存计时器：框被换掉以后不许再拿旧字存一次
    assert.ok(VB.get(F).includes('在别处改过的正文'), '旧源码框的计时器没有补存旧字');
  });

  // 审查 2：CONFLICT 后正在重读磁盘时她想再改（勾待办）→ 三审起页面这时只读（待办勾选框灰掉、点了不排保存），不许在她没按「用我这份覆盖」时盖掉别处的版本
  await reviewCase('审查2 CONFLICT 重读期间又排了保存', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    const read0 = VB.vault.adapter.read; let slow = 0;
    VB.vault.adapter.read = async f => { if (slow) await tick(slow); return read0(f); };
    tocPage(B, '住宿偏好').click();
    B.qa('.lbw-blk')[0].click(); const t1 = B.q('.lbw-ed');
    VB.set(F, OTHER);
    t1.value = '她刚写的一句话。';
    slow = 40;
    key(B, t1, 'Escape'); await tick(15);   // 保存撞 CONFLICT，页面正在慢慢重读磁盘
    assert.ok(P.calls.some(c => c.op === 'save' && c.error && c.error.code === 'CONFLICT'), '先撞 CONFLICT');
    const cb = B.q('.lbw-task input');
    assert.equal(cb.disabled, true, '保存 / 重读在路上：待办勾选框灰掉');
    cb.click();                               // 点了也不排保存
    await tick(400); slow = 0;
    assert.equal(P.calls.filter(c => c.op === 'save').length, 1, '重读期间没有排进第二次保存');
    assert.ok(VB.get(F).includes('在别处改过的正文') && !VB.get(F).includes('她刚写的一句话'), '没按覆盖就不许盖掉别处的改动');
    assert.ok(B.q('.lbw-doc').textContent.includes('在别处改过的正文'), '页面是磁盘上的版本');
    const ap = B.qa('.lbw-draft button').find(b => b.textContent === '用我这份覆盖');
    assert.ok(ap, '草稿条在');
    ap.click(); await tick(40);
    assert.ok(VB.get(F).includes('她刚写的一句话'), '覆盖存的是她那份');
    assert.ok(!B.q('.lbw-task input').disabled, '存完解冻，待办照常能勾');
    assert.equal(B.qa('.lbw-draft').length, 0);
  });

  // 审查 3：恢复还没回来时点一段想改 → 不开编辑框（不留旧行号的编辑框）；恢复后再改是对的那一段
  await reviewCase('审查3 恢复进行中点段落', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    B.q('.lbw-hbtn:not(.is-more)').click(); await tick(10);
    B.qa('.lbw-ver')[1].click(); await tick(10);
    P.delay = 60;
    B.q('.lbw-side [data-restore]').click(); await tick(5);
    B.qa('.lbw-blk')[1].click();
    assert.equal(B.q('.lbw-ed'), null, '恢复进行中不开编辑框');
    await tick(150); P.delay = 1;
    assert.ok(VB.get(F).includes('很早以前的正文。'), '恢复写上了');
    const n0 = P.calls.filter(c => c.op === 'save').length;
    B.qa('.lbw-blk')[0].click();
    assert.equal(B.q('.lbw-ed').value, '很早以前的正文。', '恢复后打开的是恢复后的那一段');
    key(B, B.q('.lbw-ed'), 'Escape'); await tick(20);
    assert.equal(P.calls.filter(c => c.op === 'save').length, n0, '没改不存；没有拿旧行号拼出来的保存');
    assert.equal(B.qa('.lbw-draft').length, 0);
  });

  // 审查 4：Obsidian 自己的弹窗（设置、命令面板）开着时，Ctrl+F 不归 Wiki
  await reviewCase('审查4 Obsidian 弹窗开着时 Ctrl+F', async () => {
    const P = fakePlugin(); const { A: B, dom: d2 } = await open({ plugin: P });
    const m = d2.document.body.createEl('div', { cls: 'modal-container' });
    key(B, d2.document, 'f', { ctrlKey: true });
    assert.equal(B.q('.lbw-find'), null, '弹窗开着：不抢 Ctrl+F');
    m.remove();
    key(B, d2.document, 'f', { ctrlKey: true });
    assert.ok(B.q('.lbw-find'), '弹窗关了照常');
  });

  // 审查 5（补测，三审起按新规则）：保存在路上时页面只读（标题框只读、待办灰掉、编辑框等存完再开）；中间一次保存失败（插件原样抛 LOCK_BUSY）
  // → 那次的内容进草稿、页面回到上次存上的样子、照常能改；后面的保存用最新的 hash；提示带插件给的原因；草稿「再存一次」能存上
  await reviewCase('审查5 保存中只读 + 中间失败一次', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    P.delay = 30;
    P.failAt = { op: 'save', n: 2, code: 'LOCK_BUSY', message: 'Wiki 正在保存别的改动，稍后再试' };
    B.qa('.lbw-blk')[0].click(); const t1 = B.q('.lbw-ed'); t1.value = '第一处改动。'; key(B, t1, 'Escape');
    // 10-31 起普通保存不锁页（以前每存一次这页只读 1.5 秒，Enter 下一段要干等）
    assert.ok(!B.q('.lbw-ptitle').readOnly, '保存在路上：标题照常能改');
    assert.ok(!B.q('.lbw-task input').disabled, '保存在路上：待办照常能勾');
    B.qa('.lbw-blk')[1].click();
    assert.ok(B.q('.lbw-ed'), '保存在路上：点别的段马上打开');
    key(B, B.q('.lbw-ed'), 'Escape'); await tick(80);
    const ti = B.q('.lbw-ptitle'); assert.ok(!ti.readOnly, '存完解冻');
    ti.focus(); ti.value = '住宿偏好（新）'; ti.blur(); await tick(80);    // 第二次保存：失败
    let ss = P.calls.filter(c => c.op === 'save');
    assert.equal(ss.length, 2);
    assert.equal(ss[1].error && ss[1].error.code, 'LOCK_BUSY');
    assert.ok(B.notices.includes(NOT_SAVED + 'Wiki 正在保存别的改动，稍后再试'), '插件抛的原因原样带到提示里');
    assert.equal(B.q('.lbw-ptitle').value, '住宿偏好', '页面回到上次存上的样子');
    assert.ok(B.q('.lbw-draft'), '没存上的那次在草稿里');
    B.q('.lbw-task input').click(); await tick(80);                         // 第三次：照常能改能存
    ss = P.calls.filter(c => c.op === 'save');
    assert.equal(ss.length, 3);
    assert.equal(ss[2].input.base_hash, ss[0].result.page.hash, '失败那次之后用的是最新存上的 hash');
    assert.ok(VB.get(F).includes('第一处改动。') && VB.get(F).includes('- [x] 预算上限？'));
    B.qa('.lbw-draft button').find(b => b.textContent === '再存一次').click(); await tick(80);
    assert.ok(VB.get('PersonalWiki/住宿偏好（新）.md'), '草稿再存一次：标题改上了');
    assert.equal(B.qa('.lbw-draft').length, 0);
  });

  // ═════ 10-29 二审（Codex 复查）：整页 Markdown 模式的两条 + 补测 ═════
  const enterSrc = B => {
    B.q('.lbw-hbtn.is-more').click();
    B.qa('.lbw-pop button').find(b => b.textContent.startsWith('整页 Markdown')).click();
    const src = B.q('.lbw-srced'); assert.ok(src, '整页 Markdown 编辑框'); return src;
  };
  const openRestore = async B => {
    B.q('.lbw-hbtn:not(.is-more)').click(); await tick(10);
    B.qa('.lbw-ver')[1].click(); await tick(10);
    return B.q('.lbw-side [data-restore]');
  };

  // A：整页 Markdown 开着时恢复到旧版（她什么都没打）→ 恢复后不许把旧框里恢复前的正文自动存回去
  await reviewCase('二审A 整页 Markdown 开着时恢复', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    const src = enterSrc(B);
    const rb = await openRestore(B);
    P.delay = 40;
    rb.click(); await tick(5);
    assert.equal(src.readOnly, true, '恢复进行中：整页 Markdown 框冻住');
    await tick(150); P.delay = 1; await tick(20);
    assert.ok(VB.get(F).includes('很早以前的正文。') && !VB.get(F).includes('每次订酒店都从头翻收藏'), '恢复的内容没被旧框盖回去');
    assert.equal(P.calls.filter(c => c.op === 'save').length, 0, '恢复后没有自动保存');
    const src2 = B.q('.lbw-srced');
    assert.ok(src2 && src2 !== src && src2.value.includes('很早以前的正文。'), '新框里是恢复后的正文');
  });

  // B：整页 Markdown 已经发出一次保存 → 三审起框在保存回来之前只读（打不进字，不存在「发出之后又打的字」）；
  // 撞 CONFLICT → 框换成磁盘版本、能接着改；草稿里是她发出去的全部字，覆盖能存上
  await reviewCase('二审B 保存在路上框只读、撞 CONFLICT 后覆盖', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    const src = enterSrc(B);
    VB.set(F, OTHER);                      // 别处先改了
    P.delay = 60;
    src.focus();
    src.value = src.value.replace('为什么记：每次订酒店都从头翻收藏。', '为什么记：源码里第一句。');
    src.blur(); await tick(5);             // 失焦 = 存（带旧 hash，路上）
    assert.ok(!src.readOnly, '10-31：保存在路上框照常能打字');
    await tick(250); P.delay = 1;
    const box2 = B.q('.lbw-srced');
    assert.ok(box2 && !box2.readOnly && box2.value.includes('在别处改过的正文'), '回来后：框里是磁盘上的版本，能接着改');
    assert.ok(P.calls.some(c => c.op === 'save' && c.error && c.error.code === 'CONFLICT'));
    assert.ok(VB.get(F).includes('在别处改过的正文'), '别处的版本还在');
    const ap = B.qa('.lbw-draft button').find(b => b.textContent === '用我这份覆盖');
    assert.ok(ap, '草稿条在');
    ap.click(); await tick(40);
    assert.ok(VB.get(F).includes('源码里第一句'), '覆盖存的是她那份：' + JSON.stringify(P.calls.filter(c => c.op === 'save').map(c => [c.input.body.slice(0, 40), c.error && c.error.code])) + ' disk=' + VB.get(F).slice(-80));
  });

  // 补测：恢复失败 → 页面照常能改能存（块编辑框 + 整页 Markdown 框都解冻）
  await reviewCase('补测 恢复失败后照常能改能存', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    let rb = await openRestore(B);
    P.failAt = { op: 'restore', n: 1, code: 'LOCK_BUSY', message: 'Wiki 正在保存别的改动，稍后再试' };
    rb.click(); await tick(30);
    assert.ok(B.notices.some(m => m === '没恢复上：Wiki 正在保存别的改动，稍后再试'));
    B.qa('.lbw-blk')[0].click(); const t1 = B.q('.lbw-ed');
    assert.ok(t1, '恢复失败后能开编辑框');
    t1.value = '恢复失败后改的。'; key(B, t1, 'Escape'); await tick(20);
    assert.ok(VB.get(F).includes('恢复失败后改的。'), '能存上');
    // 整页 Markdown 开着时恢复失败：框解冻，接着打的字照常存
    const src = enterSrc(B);
    rb = B.q('.lbw-side [data-restore]') || (await openRestore(B));
    P.failAt = { op: 'restore', n: 2, code: 'WRITE_FAILED', message: '写不进去' };
    rb.click(); await tick(30);
    const box = B.q('.lbw-srced');
    assert.ok(!box.readOnly, '整页 Markdown 框解冻');
    box.value = box.value + '\n\n解冻后打的字。'; key(B, box, 'Escape'); await tick(20);
    assert.ok(VB.get(F).includes('解冻后打的字。'));
  });

  // 补测：冲突后重读磁盘抛异常 → 页面不卡在「正在重新读入」：能开编辑框、能再存（再撞冲突、重读成功后能覆盖）
  await reviewCase('补测 冲突重读抛异常后不卡住', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    const list0 = VB.vault.adapter.list;
    B.qa('.lbw-blk')[0].click(); let t1 = B.q('.lbw-ed');
    VB.set(F, OTHER);
    VB.vault.adapter.list = async () => ({ get files() { throw new Error('磁盘读不到'); } });
    t1.value = '第一次写的。'; key(B, t1, 'Escape'); await tick(30);
    VB.vault.adapter.list = list0;
    assert.ok(B.notices.some(m => m.startsWith(NOT_SAVED)));
    B.qa('.lbw-blk')[0].click(); t1 = B.q('.lbw-ed');
    assert.ok(t1, '重读失败后没卡住：能开编辑框');
    t1.value = '第二次写的。'; key(B, t1, 'Escape'); await tick(40);
    const ap = B.qa('.lbw-draft button').find(b => b.textContent === '用我这份覆盖');
    assert.ok(ap, '第二次照样撞冲突、留草稿');
    ap.click(); await tick(40);
    assert.ok(VB.get(F).includes('第二次写的。'), '覆盖能存上');
  });

  // 补测：按键落在 Wiki 外面的输入框里（侧栏搜索等）→ Esc / Ctrl+F 都不归 Wiki
  await reviewCase('补测 Wiki 外的输入框里按 Esc / Ctrl+F', async () => {
    const P = fakePlugin(); const { A: B, dom: d2 } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    B.q('.lbw-hbtn:not(.is-more)').click(); await tick(10);
    assert.equal(B.q('.lbw-side').hidden, false);
    const outside = d2.document.body.createEl('input');
    outside.dispatchEvent(new B.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.equal(B.q('.lbw-side').hidden, false, '外面输入框里的 Esc 不关 Wiki 的历史栏');
    outside.dispatchEvent(new B.window.KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true }));
    assert.equal(B.q('.lbw-find'), null, '外面输入框里的 Ctrl+F 不归 Wiki');
    key(B, d2.document, 'Escape');
    assert.equal(B.q('.lbw-side').hidden, true, '在 Wiki 里按 Esc 照常关');
  });

  // ═════ 10-29 三审：保存在路上时点恢复；有草稿时在编辑框里打了新字再点「用我这份覆盖」 ═════
  // 三审1：整页 Markdown 的保存还在路上（会撞 CONFLICT），她点了恢复 → 最后磁盘上是恢复的版本，没有任何保存把它盖回去；她的字在草稿里
  await reviewCase('三审1 保存在路上时点恢复', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    const src = enterSrc(B);
    const rb = await openRestore(B);
    VB.set(F, OTHER);                          // 别处先改了：她这次保存会撞 CONFLICT
    P.delay = 50;
    src.focus();
    src.value = src.value.replace('为什么记：每次订酒店都从头翻收藏。', '为什么记：源码里改的。');
    src.blur();                                // 存（路上）
    rb.click();                                // 紧接着点恢复
    await tick(400); P.delay = 1; await tick(30);
    const ss = P.calls.filter(c => c.op === 'save');
    assert.equal(ss.length, 1, '只有她那一次保存（撞 CONFLICT），恢复之后没有别的保存：' + ss.map(c => c.error ? c.error.code : 'ok').join(','));
    assert.equal(ss[0].error && ss[0].error.code, 'CONFLICT');
    assert.ok(P.calls.some(c => c.op === 'restore' && c.result), '恢复做了');
    assert.ok(VB.get(F).includes('很早以前的正文。') && !VB.get(F).includes('在别处改过的正文'), '磁盘上是恢复的版本：' + VB.get(F).slice(-60));
    const box = B.q('.lbw-srced');
    assert.ok(box && box.value.includes('很早以前的正文。') && !box.readOnly, '框里是恢复后的正文，能接着改');
    assert.ok(B.q('.lbw-draft'), '她的那份在草稿里');
  });

  // 三审2：有草稿，她在编辑框里又打了新字，点「用我这份覆盖」→ 只发一次保存（她最新的字）；这次失败 → 草稿就是她最新的字，不许丢
  await reviewCase('三审2 打了新字再覆盖、覆盖失败', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    B.qa('.lbw-blk')[0].click(); let t1 = B.q('.lbw-ed');
    VB.set(F, OTHER);
    t1.value = '旧草稿里的话。'; key(B, t1, 'Escape'); await tick(40);   // 撞 CONFLICT → 草稿
    assert.ok(B.q('.lbw-draft'), '先有一份草稿');
    B.qa('.lbw-blk')[0].click(); t1 = B.q('.lbw-ed');
    assert.ok(t1, '页面能接着改');
    t1.value = '她新打的字。';
    const n0 = P.calls.filter(c => c.op === 'save').length;
    P.failAt = { op: 'save', n: n0 + 1, code: 'LOCK_BUSY', message: 'Wiki 正在保存别的改动，稍后再试' };
    B.qa('.lbw-draft button').find(b => b.textContent === '用我这份覆盖').click();
    await tick(60);
    const ss = P.calls.filter(c => c.op === 'save').slice(n0);
    assert.equal(ss.length, 1, '覆盖只发一次保存：' + ss.map(c => c.input.body.slice(0, 8)).join(' | '));
    assert.ok(ss[0].input.body.startsWith('她新打的字。'), '这一次存的是她最新的字');
    assert.ok(!VB.get(F).includes('她新打的字'), '这次没存上');
    const ap = B.qa('.lbw-draft button').find(b => b.textContent === '用我这份覆盖' || b.textContent === '再存一次');
    assert.ok(ap, '草稿还在');
    ap.click(); await tick(60);
    assert.ok(VB.get(F).includes('她新打的字。'), '再点一次：草稿里是她最新的字，存上了');
    assert.equal(B.qa('.lbw-draft').length, 0, '存上了草稿才收');
  });

  // ═════ 10-29 四审 ═════
  // 四审1：改着 A 段、没按 Esc 直接点 B 段 → A 入队保存；B 不能马上开（页面忙），要等 A 存完再开；A 撞 CONFLICT（页面换成磁盘版本）→ B 不开，
  // 不会拿旧行号把 B 的字拼进新正文的错位置
  await reviewCase('四审1 改着 A 直接点 B、A 撞 CONFLICT', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    B.qa('.lbw-blk')[0].click(); const ta = B.q('.lbw-ed');
    ta.value = 'A 段改了。';
    VB.set(F, OTHER);                       // 别处先改了：A 的保存会撞 CONFLICT
    P.delay = 40;
    B.q('.lbw-blk[data-i="2"]').click();   // 没按 Esc 直接点 B（列表第一条，按段号点）
    const tb = B.q('.lbw-ed');
    assert.ok(tb && tb.value === '安静 > 位置', '10-31：A 在存，B 马上就能改（列表按条开，记号不显示）');
    tb.value = '安静 > 一切';
    await tick(200); P.delay = 1; await tick(20);
    const ss = P.calls.filter(c => c.op === 'save');
    assert.equal(ss.length, 1, '只有 A 那一次保存');
    assert.equal(ss[0].error && ss[0].error.code, 'CONFLICT');
    assert.equal(B.q('.lbw-ed'), null, '页面被换成磁盘版本：B 的编辑框收起（旧行号作废）');
    assert.ok(VB.get(F).includes('在别处改过的正文') && !VB.get(F).includes('一切'), '没按覆盖不盖掉别处');
    B.qa('.lbw-draft button').find(b => b.textContent === '用我这份覆盖').click(); await tick(30);
    assert.ok(VB.get(F).includes('A 段改了。') && VB.get(F).includes('- 安静 > 一切'), 'A、B 两处的字都在草稿里，覆盖都存上：' + JSON.stringify(VB.get(F)));
    VB.set(F, OTHER); await tick(700);
    B.qa('.lbw-blk')[0].click();
    assert.equal(B.q('.lbw-ed').value, '在别处改过的正文。', '重新点：按新正文开');
  });
  await reviewCase('四审1b 改着 A 直接点 B、A 存上', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    B.qa('.lbw-blk')[0].click(); B.q('.lbw-ed').value = 'A 段改了。';
    P.delay = 40;
    B.q('.lbw-blk[data-i="1"]').click();   // 编辑框占了 0 号段的位置：按段号点
    assert.equal(B.q('.lbw-ed') && B.q('.lbw-ed').value, '在意什么', '10-31：A 在存，B 马上打开，是对的那一段（标题记号不显示）');
    assert.ok(B.q('.lbw-ed').closest('h2'));
    B.q('.lbw-ed').value = '在意的事'; key(B, B.q('.lbw-ed'), 'Escape'); await tick(150); P.delay = 1; await tick(30);
    assert.ok(VB.get(F).includes('A 段改了。\n\n## 在意的事\n- 安静 > 位置') && !VB.get(F).includes('每次订酒店都从头翻收藏'), '两段都改在对的位置：' + JSON.stringify(VB.get(F)));
  });

  // 四审2：块保存在路上时切到整页 Markdown → 重画出来的标题框先是只读的；存完解冻后改标题、失焦，照常存
  await reviewCase('四审2 保存中切整页 Markdown 后改标题', async () => {
    const P = fakePlugin(); const { A: B, V: VB } = await open({ plugin: P });
    tocPage(B, '住宿偏好').click();
    B.qa('.lbw-blk')[0].click(); const ta = B.q('.lbw-ed'); ta.value = '先改一段。';
    P.delay = 40;
    key(B, ta, 'Escape');
    enterSrc(B);
    const ti = B.q('.lbw-ptitle');
    assert.ok(!ti.readOnly, '10-31：保存在路上标题照常能改');
    ti.focus(); ti.value = '住宿偏好（改名）'; ti.blur(); await tick(150); P.delay = 1; await tick(30);
    assert.ok((VB.get('PersonalWiki/住宿偏好（改名）.md') || '').includes('先改一段。'), '改名排在那次保存后面，两样都存上');
    assert.ok(P.calls.some(c => c.op === 'save' && c.input.title === '住宿偏好（改名）' && c.result), '失焦照常存标题');
    assert.ok(VB.get('PersonalWiki/住宿偏好（改名）.md'));
  });

  // ═════ 10-29 五轮（她在真 Obsidian 里用过之后）：短 id 引用；关系图照 Quartz 做成力导向 ═════
  // 手动驱动的 requestAnimationFrame：step(n) 跑 n 帧；记下 cancelAnimationFrame
  const manualRaf = () => {
    const q = new Map(), cancelled = []; let id = 0;
    return {
      q, cancelled,
      params: { requestAnimationFrame: f => { q.set(++id, f); return id; }, cancelAnimationFrame: i => { cancelled.push(i); q.delete(i); } },
      step(n = 1) { for (let k = 0; k < n; k++) { const fs = [...q.values()]; q.clear(); for (const f of fs) f(16 * k); } },
    };
  };
  const homeG = B => { const svg = B.q('.lbw-map svg.lbw-graph'); assert.ok(svg && svg.__lbwGraph, '首页 MAP 是活的关系图'); return svg.__lbwGraph; };
  const ptr = (B, el, type, x, y, extra = {}) => el.dispatchEvent(new B.window.Event(type, { bubbles: true, pointerId: 1, pointerType: 'mouse', button: 0, clientX: x, clientY: y, ...extra }));

  // 五轮1：收藏 id 带来源前缀（xhs-…），引用写成短 id 也认；撞号（两个来源同一个短 id）不猜；处处按同一篇算
  await reviewCase('五轮1 短 id 引用', async () => {
    const items = [...ITEMS,
      { id: 'xhs-6a84ab', title: '示例长 id 收藏', tags: ['茶'], summary: '冷泡的做法', author: '示例作者 C', note: 'Web/示例/xhs-6a84ab.md', kind: 'image', attachment: 'none', search_fields: { body: '冷泡 做法' } },
      { id: 'xhs-dup1', title: '撞号一', tags: [], note: 'Web/示例/a.md', search_fields: { body: '' } },
      { id: 'bili-dup1', title: '撞号二', tags: [], note: 'Web/示例/b.md', search_fields: { body: '' } }];
    const files = {
      '_archive/catalog-data.json': JSON.stringify({ built_at: '2026-10-29T09:00:00+08:00', items }),
      'PersonalWiki/短引用.md': '---\nid: pw-short\ntitle: 短引用\nrole: page\ntags: ["茶"]\ncreated: 2026-10-05T10:00:00+08:00\nupdated: 2026-10-05T10:00:00+08:00\n---\n\n- [抄来的短 id](lwa:6a84ab) — 从搜索里抄的\n- [写全的](lwa:xhs-6a84ab)\n- [撞号的](lwa:dup1)\n',
      'PersonalWiki/另一页.md': '---\nid: pw-other\ntitle: 另一页\nrole: page\ntags: []\ncreated: 2026-10-06T10:00:00+08:00\nupdated: 2026-10-06T10:00:00+08:00\n---\n\n参考 [同一篇](lwa:xhs-6a84ab)。\n',
    };
    const P = fakePlugin(); const { A: B } = await open({ plugin: P, files });
    tocPage(B, '短引用').click();
    const cs = B.qa('.lbw-cite');
    assert.equal(cs.length, 3);
    assert.ok(!cs[0].classList.contains('is-missing'), '短 id 找得到');
    assert.equal(cs[0].querySelector('.lbw-ref').textContent, '1');
    assert.equal(cs[1].querySelector('.lbw-ref').textContent, '1', '短 id 和完整 id 是同一篇：同一个编号');
    assert.ok(cs[2].classList.contains('is-missing') && cs[2].querySelector('.lbw-ref').textContent === '缺', '两个来源撞了同一个短 id：不猜');
    assert.ok(B.q('.lbw-meta').textContent.includes('引用 2 篇收藏'), '按篇数算（短 id + 完整 id 算一篇，撞号的那篇单算）：' + B.q('.lbw-meta').textContent);
    cs[0].click(); await tick(2);
    assert.equal(P.opened.at(-1)[0], 'Web/示例/xhs-6a84ab.md', '开原文：解析出来的那篇');
    assert.ok(B.q('.lbw-cite.is-open'), '开着的那篇圈变实心');
    // @：「已在《…》引用」按同一篇算；插入写完整 id
    B.qa('.lbw-blk')[0].click(); const ta = B.q('.lbw-ed');
    ta.value = '@冷泡'; ta.setSelectionRange(ta.value.length, ta.value.length);
    ta.dispatchEvent(new B.window.Event('input'));
    const pop = B.q('.lbw-pop');
    assert.ok(pop && pop.querySelector('button.is-on').textContent.startsWith('示例长 id 收藏'));
    assert.ok(pop.querySelector('small').textContent.includes('已在《'), '@ 补全：已在别的页引用（短 id 写的也算）');
    key(B, ta, 'Enter');
    assert.ok(ta.value.startsWith('[示例长 id 收藏](@'), '框里显示短号');
    key(B, ta, 'Escape'); await tick(30);
    assert.ok(P.calls.filter(c => c.op === 'save').at(-1).input.body.includes('[示例长 id 收藏](lwa:xhs-6a84ab) —'), '存的是完整的带前缀 id');
    // 标签页：PAGES / ARCHIVE 两张清单（这一轮顺手发现：以前 add() 只收了表头，清单是空的）；ARCHIVE 里这篇「已引用」
    B.qa('.lbw-ttags button').find(b => b.textContent === '#茶').click();
    const row = B.q('.lbw-prow[data-item="xhs-6a84ab"]');
    assert.ok(row && row.textContent.includes('已引用'), 'ARCHIVE：这篇已引用：' + (row ? row.textContent : 'no row; prows=' + JSON.stringify(B.qa('.lbw-prow').map(r => [r.getAttribute('data-item'), r.textContent]))));
    // 全局图：一页写短 id、一页写完整 id，算「引了同一篇」→ 虚线
    B.q('[data-global]').click();
    const gg = B.q('.lbw-gbg svg.lbw-graph').__lbwGraph;
    assert.ok(gg.links.some(l => l.dashed && [l.s.id, l.t.id].sort().join() === 'pw-other,pw-short'), '关系图：同引一篇的虚线（短 id 也认）');
  });

  // 五轮2：力导向一步步冷却、收敛后自己停；同样的数据排出来一样；不重叠；适配后字不出框
  await reviewCase('五轮2 收敛、确定、不切字', async () => {
    const run = async () => {
      const R1 = manualRaf();
      const { A: B } = await open({ plugin: fakePlugin(), params: R1.params });
      const g = homeG(B);
      assert.ok(g.running, '开页就在动（排着 rAF）');
      const a0 = g.sim.alpha; R1.step(5);
      assert.ok(g.sim.alpha < a0, 'alpha 在冷却');
      let frames = 5;
      while (g.running && frames < 3000) { R1.step(); frames++; }
      assert.ok(!g.running && g.sim.done, '收敛后自己停，不再排帧');
      assert.ok(frames > 100 && frames < 1500, '帧数合理：' + frames);
      const [, , W, H] = g.svg.getAttribute('viewBox').split(' ').map(Number);
      for (const n of g.nodes) {
        const k = g.view.k, sx = n.x * k + g.view.x, sy = n.y * k + g.view.y, hw = Math.max(n.r, n.lw / 2) * k;
        assert.ok(sx - hw >= -1 && sx + hw <= W + 1 && sy - n.r * k >= -1 && sy + (n.r + n.fs * 1.5) * k <= H + 1, '点和字都在框里：' + n.title);
      }
      for (let i = 0; i < g.nodes.length; i++) for (let j = i + 1; j < g.nodes.length; j++) {
        const a = g.nodes[i], b = g.nodes[j];
        assert.ok(Math.hypot(a.x - b.x, a.y - b.y) >= (a.r + b.r) * 0.8, '不叠在一起：' + a.title + ' / ' + b.title);
      }
      return g.nodes.map(n => [n.id, Number(n.x.toFixed(3)), Number(n.y.toFixed(3))]);
    };
    const s1 = await run(), s2 = await run();
    assert.deepEqual(s1, s2, '同样的数据：排出来一样（起点确定、抖动固定种子）');
  });

  // 五轮3：拖点（跟着指针走、重新加热、别的点跟着动；松手放开）；悬停高亮邻居其余淡掉；点一下打开；滚轮缩放
  await reviewCase('五轮3 拖动 / 悬停 / 点开 / 缩放', async () => {
    const R1 = manualRaf();
    const { A: B } = await open({ plugin: fakePlugin(), params: R1.params });
    const g = homeG(B);
    while (g.running) R1.step();
    const n = g.nodes.find(x => x.id === 'pw-kyoto'), el = g.nodeEl('pw-kyoto');
    const x0 = n.x;
    ptr(B, el, 'pointerdown', 100, 100);
    assert.equal(g.sim.alphaTarget, 0.3, '按下：重新加热');
    assert.ok(g.running, '按下：又动起来');
    ptr(B, g.svg, 'pointermove', 170, 130);
    assert.ok(Math.abs(n.x - x0) > 1 && n.fx === n.x, '点跟着指针走');
    const others = g.nodes.filter(m => m !== n), before = others.map(m => [m.x, m.y]);
    R1.step(15);
    assert.ok(others.some((m, i) => Math.hypot(m.x - before[i][0], m.y - before[i][1]) > 0.01), '加热后别的点跟着动');
    ptr(B, g.svg, 'pointerup', 170, 130);
    assert.equal(n.fx, null, '松手放开'); assert.equal(g.sim.alphaTarget, 0);
    assert.equal(B.q('.lbw-ptitle'), null, '拖动不算点开');
    while (g.running) R1.step();
    // 悬停：自己和邻居高亮，别的淡掉；字跟着
    g.nodeEl('pw-travel').dispatchEvent(new B.window.Event('pointerenter'));
    assert.ok(g.svg.classList.contains('has-hover'));
    for (const id of ['pw-travel', 'pw-stay', 'pw-kyoto']) assert.ok(g.nodeEl(id).classList.contains('is-hl'), id + ' 高亮');
    const tea = g.nodes.find(x => x.title === '冷泡茶比例');
    assert.ok(!g.nodeEl(tea.id).classList.contains('is-hl'), '不相连的点淡掉');
    const labOf = id => g.nodeEl(id).querySelector('text.lab') || g.nodeEl(id).querySelectorAll('text').at(-1);
    assert.equal(String(labOf('pw-stay').style.opacity), '1', '邻居的字显示');
    g.nodeEl('pw-travel').dispatchEvent(new B.window.Event('pointerleave'));
    assert.ok(!g.svg.classList.contains('has-hover'));
    // 字随缩放淡入（Quartz：(k × opacityScale − 1) / 3.75）
    const op0 = Number(labOf('pw-stay').style.opacity);
    g.svg.dispatchEvent(new B.window.Event('wheel', { deltaY: -800, clientX: 200, clientY: 150 }));
    assert.ok(g.view.k > 1 && Number(labOf('pw-stay').style.opacity) >= op0, '放大后普通页的字更清楚');
    // 点一下 = 打开
    const st = g.nodeEl('pw-stay');
    ptr(B, st, 'pointerdown', 50, 50); ptr(B, g.svg, 'pointerup', 50, 50);
    assert.equal(B.q('.lbw-ptitle').value, '住宿偏好', '点关系图里的页 = 打开');
    assert.equal(g.alive, false, '换页：首页大图停掉');
    // 目录里的局部图：当前页大一号；点文件夹打开文件夹页；收起 MAP 就停掉
    B.q('.lbw-tmap-h').click();
    const mg = B.q('.lbw-tmap svg.lbw-graph').__lbwGraph;
    assert.equal(mg.mode, 'local');
    assert.ok(mg.nodeEl('pw-stay').classList.contains('is-cur'));
    assert.ok(mg.nodes.find(x => x.id === 'pw-stay').r > mg.nodes.find(x => x.id === 'pw-kyoto').r, '当前页大一号');
    assert.ok(mg.nodeEl('pw-travel').classList.contains('is-hub'), '文件夹是圆心（墨色实心 + 斜体编号）');
    ptr(B, mg.nodeEl('pw-travel'), 'pointerdown', 10, 10); ptr(B, mg.svg, 'pointerup', 10, 10);
    assert.equal(B.q('.lbw-ptitle').value, '旅行', '点文件夹 = 打开文件夹页');
    assert.equal(mg.alive, false, '换页：旧的局部图停掉');
    assert.equal(B.q('.lbw-tmap svg.lbw-graph'), null, '没钉住：换页后 MAP 收起（原型的规矩）');
    B.q('.lbw-tmap-h').click();
    const mg2 = B.q('.lbw-tmap svg.lbw-graph').__lbwGraph;
    assert.ok(mg2.alive && mg2.nodeEl('pw-travel').classList.contains('is-cur'), '展开：文件夹页的局部图');
    B.q('.lbw-tmap-h').click();
    assert.equal(B.q('.lbw-tmap svg.lbw-graph'), null); assert.equal(mg2.alive, false, '收起 MAP：图停掉');
  });

  // 五轮4：「全局图」浮层：MAP 一行的图标钮打开；Esc / 点遮罩关；关掉就停；点里面的页 = 关浮层 + 打开
  await reviewCase('五轮4 全局图浮层', async () => {
    const R1 = manualRaf();
    const { A: B, dom: d2 } = await open({ plugin: fakePlugin(), params: R1.params });
    const gb = B.q('[data-global]');
    assert.ok(gb && gb.querySelector('.lb-visually-hidden').textContent === '打开全局图', '图标钮 + 隐藏文字');
    gb.click();
    let og = B.q('.lbw-gbg svg.lbw-graph').__lbwGraph;
    assert.equal(og.mode, 'global'); assert.ok(og.running);
    key(B, d2.document, 'Escape');
    assert.equal(B.q('.lbw-gbg'), null, 'Esc 关'); assert.equal(og.alive, false, '关掉就停');
    B.q('[data-global]').click();
    og = B.q('.lbw-gbg svg.lbw-graph').__lbwGraph;
    B.q('.lbw-gbg').click();
    assert.equal(B.q('.lbw-gbg'), null, '点遮罩关'); assert.equal(og.alive, false);
    B.q('[data-global]').click();
    og = B.q('.lbw-gbg svg.lbw-graph').__lbwGraph;
    ptr(B, og.nodeEl('pw-kyoto'), 'pointerdown', 5, 5); ptr(B, og.svg, 'pointerup', 5, 5);
    assert.equal(B.q('.lbw-gbg'), null, '点了页：浮层关掉');
    assert.equal(B.q('.lbw-ptitle').value, '京都想住的地方', '打开那一页');
  });

  // 五轮5：卸载就停 rAF（cancelAnimationFrame），之后不再排帧
  await reviewCase('五轮5 卸载停 rAF', async () => {
    const R1 = manualRaf();
    const { A: B } = await open({ plugin: fakePlugin(), params: R1.params });
    const g = homeG(B);
    assert.ok(g.running && R1.q.size >= 1);
    R1.step(3);
    B.detach();
    assert.equal(g.alive, false, '卸载：图销毁');
    assert.ok(R1.cancelled.length >= 1, '卸载：调了 cancelAnimationFrame');
    R1.step(3);
    assert.equal(R1.q.size, 0, '卸载后不再排帧');
  });

  // 五轮6：prefers-reduced-motion：同步算到收敛只画结果，不排动画帧；拖动松手后一次算好
  await reviewCase('五轮6 减少动态效果', async () => {
    const R1 = manualRaf();
    const { A: B } = await open({ plugin: fakePlugin(), params: { ...R1.params, matchMedia: () => ({ matches: true }) } });
    const g = homeG(B);
    assert.ok(g.sim.done && !g.running, '一开始就是收敛好的样子');
    assert.equal(R1.q.size, 0, '不排动画帧');
    const n = g.nodes.find(x => x.id === 'pw-kyoto');
    ptr(B, g.nodeEl('pw-kyoto'), 'pointerdown', 100, 100);
    ptr(B, g.svg, 'pointermove', 150, 120);
    assert.equal(n.fx, n.x, '拖动照样跟手');
    ptr(B, g.svg, 'pointerup', 150, 120);
    assert.ok(g.sim.done && !g.running && R1.q.size === 0, '松手后一次算好，不排帧');
  });

  // 五轮7：约 300 个点也要顺：每一步模拟平均几毫秒
  await reviewCase('五轮7 300 个点', async () => {
    const files = {};
    for (let f = 0; f < 6; f++) files[`PersonalWiki/夹${f}.md`] = `---\nid: pw-f${f}\ntitle: 夹${f}\nrole: topic\nindex_tag: t${f}\ntags: ["t${f}"]\ncreated: 2026-10-0${f + 1}T10:00:00+08:00\nupdated: 2026-10-0${f + 1}T10:00:00+08:00\n---\n\n\`\`\`pages\n\`\`\`\n`;
    for (let i = 0; i < 294; i++) files[`PersonalWiki/页${i}.md`] = `---\nid: pw-p${i}\ntitle: 页${i}\nrole: page\ntags: ["t${i % 6}"]\ncreated: 2026-10-10T10:00:00+08:00\nupdated: 2026-10-10T10:00:00+08:00\n---\n\n${i % 7 === 0 ? '参考 [示例咖啡地图](lwa:it-1)。' : '一句话。'}\n`;
    const R1 = manualRaf();
    const { A: B } = await open({ plugin: fakePlugin(), params: R1.params, files });
    const g = homeG(B);
    assert.ok(g.nodes.length >= 300, '点数：' + g.nodes.length);
    const t0 = process.hrtime.bigint();
    R1.step(40);
    const ms = Number(process.hrtime.bigint() - t0) / 1e6 / 40;
    assert.ok(ms < 12, '每帧（模拟 + 改 SVG 属性）平均 ' + ms.toFixed(2) + 'ms');
    while (g.running) R1.step();
    assert.ok(g.sim.done && g.nodes.every(n => Number.isFinite(n.x) && Number.isFinite(n.y)));
  });

  // ═════ 10-29 六轮（关系图 + 短 id 的复查） ═════
  // 六轮1：拖动时不再自动适配（视图不动），点和指针的相对位置保持（按下时点在指针右下 d，拖到哪儿还是右下 d）
  await reviewCase('六轮1 拖动时视图不跳、点不漂', async () => {
    const R1 = manualRaf();
    const { A: B } = await open({ plugin: fakePlugin(), params: R1.params });
    const g = homeG(B);
    R1.step(5);                                   // 还在动（自动适配还在跟）
    const n = g.nodes.find(x => x.id === 'pw-kyoto');
    const v0 = { ...g.view };
    const sx0 = n.x * v0.k + v0.x, sy0 = n.y * v0.k + v0.y;
    ptr(B, g.nodeEl('pw-kyoto'), 'pointerdown', 100, 100);
    ptr(B, g.svg, 'pointermove', 170, 130);
    R1.step(12);
    assert.deepEqual({ ...g.view }, v0, '拖着的时候视图不动（不再自动适配）');
    const sx = n.x * g.view.k + g.view.x, sy = n.y * g.view.k + g.view.y;
    assert.ok(Math.abs(sx - (sx0 + 70)) < 0.01 && Math.abs(sy - (sy0 + 30)) < 0.01, `点跟着指针走、相对位置不变：(${sx.toFixed(2)},${sy.toFixed(2)}) vs (${(sx0 + 70).toFixed(2)},${(sy0 + 30).toFixed(2)})`);
    ptr(B, g.svg, 'pointerup', 170, 130);
  });

  // 六轮2：只认已知来源前缀（domain.py 的 PREFIX：xhs / bili）；别的「abc-123」不当来源前缀——不误认、也不把唯一的短 id 搅成「撞号」
  await reviewCase('六轮2 只认已知来源前缀', async () => {
    const items = [...ITEMS,
      { id: 'xhs-123', title: '小红书那篇', tags: [], note: 'Web/示例/x.md', search_fields: { body: '' } },
      { id: 'demo-123', title: '不是来源前缀', tags: [], note: 'Web/示例/d.md', search_fields: { body: '' } },
      { id: 'demo-abc', title: '只有怪前缀', tags: [], note: 'Web/示例/e.md', search_fields: { body: '' } },
      { id: 'bili-777', title: 'B 站那篇', tags: [], note: 'Web/示例/b.md', search_fields: { body: '' } }];
    const files = {
      '_archive/catalog-data.json': JSON.stringify({ built_at: '2026-10-29T09:00:00+08:00', items }),
      'PersonalWiki/前缀.md': '---\nid: pw-pre\ntitle: 前缀\nrole: page\ntags: []\ncreated: 2026-10-05T10:00:00+08:00\nupdated: 2026-10-05T10:00:00+08:00\n---\n\n- [a](lwa:123)\n- [b](lwa:abc)\n- [c](lwa:777)\n',
    };
    const P = fakePlugin(); const { A: B } = await open({ plugin: P, files });
    tocPage(B, '前缀').click();
    const cs = B.qa('.lbw-cite');
    assert.ok(!cs[0].classList.contains('is-missing'), '123 → xhs-123（demo-123 不是来源前缀，不算撞号）');
    cs[0].click(); await tick(2);
    assert.equal(P.opened.at(-1)[0], 'Web/示例/x.md');
    assert.ok(cs[1].classList.contains('is-missing'), 'abc 只有 demo-abc：demo 不是来源前缀，不认');
    assert.ok(!cs[2].classList.contains('is-missing'), '777 → bili-777');
  });

  // 六轮3：再次打开（位置都记着的）全局图：不在主线程上一口气算完，照常交给 rAF 收尾；减少动态效果才同步算
  await reviewCase('六轮3 记着位置的图不同步硬算', async () => {
    const R1 = manualRaf();
    const { A: B, dom: d2 } = await open({ plugin: fakePlugin(), params: R1.params });
    B.q('[data-global]').click();
    let og = B.q('.lbw-gbg svg.lbw-graph').__lbwGraph;
    while (og.running) R1.step();
    key(B, d2.document, 'Escape');
    B.q('[data-global]').click();
    og = B.q('.lbw-gbg svg.lbw-graph').__lbwGraph;
    assert.ok(og.running && !og.sim.done, '再开：交给 rAF，不当场同步算完');
    let frames = 0; while (og.running && frames < 500) { R1.step(); frames++; }
    assert.ok(og.sim.done && frames < 400, '几帧就收好：' + frames);
  });

  // 六轮4：拖到一半丢了指针捕获 / 卸载：结束拖动、alphaTarget 归零，模拟不会一直热着
  await reviewCase('六轮4 丢捕获 / 卸载时结束拖动', async () => {
    const R1 = manualRaf();
    const { A: B } = await open({ plugin: fakePlugin(), params: R1.params });
    const g = homeG(B);
    while (g.running) R1.step();
    const n = g.nodes.find(x => x.id === 'pw-stay');
    ptr(B, g.nodeEl('pw-stay'), 'pointerdown', 100, 100);
    ptr(B, g.svg, 'pointermove', 130, 100);
    g.svg.dispatchEvent(new B.window.Event('lostpointercapture', { pointerId: 1 }));
    assert.equal(n.fx, null, '丢捕获：放开那个点'); assert.equal(g.sim.alphaTarget, 0, '丢捕获：不再加热');
    let frames = 0; while (g.running && frames < 1000) { R1.step(); frames++; }
    assert.ok(!g.running && g.sim.done, '丢捕获后照常冷下来、停掉');
    // 卸载时正拖着
    ptr(B, g.nodeEl('pw-stay'), 'pointerdown', 100, 100);
    assert.equal(g.sim.alphaTarget, 0.3);
    B.detach();
    assert.equal(g.alive, false);
    assert.equal(n.fx, null, '卸载：放开那个点'); assert.equal(g.sim.alphaTarget, 0, '卸载：不再加热');
    R1.step(3); assert.equal(R1.q.size, 0);
  });

  // 六轮5：滚出视口就停、回来接着动；Dataview 重跑挂回同一张图（不重建），照常动
  await reviewCase('六轮5 出视口暂停 / 重跑复用', async () => {
    const R1 = manualRaf();
    const ios = [];
    class FakeIO { constructor(cb) { this.cb = cb; ios.push(this); } observe(el) { this.el = el; } disconnect() { this.off = true; } }
    const { A: B } = await open({ plugin: fakePlugin(), params: { ...R1.params, IntersectionObserver: FakeIO } });
    const g = homeG(B);
    const io = ios.find(x => x.el === g.svg);
    assert.ok(io, '观察着这张图');
    R1.step(3);
    io.cb([{ isIntersecting: false }]);
    R1.step(1);
    assert.equal(g.running, false, '出视口：停（不再排帧）');
    const a = g.sim.alpha; R1.step(5); assert.equal(g.sim.alpha, a, '停着不算');
    io.cb([{ isIntersecting: true }]);
    assert.ok(g.running, '回来：接着动');
    const svg = g.svg;
    await B.rerun(); await tick(5);
    assert.equal(B.q('.lbw-map svg.lbw-graph'), svg, '重跑：同一张图挂回去');
    assert.ok(g.alive && g.running, '重跑后照常动');
    let frames = 0; while (g.running && frames < 1500) { R1.step(); frames++; }
    assert.ok(g.sim.done);
    B.detach(); assert.ok(io.off, '卸载：观察器断开');
  });

  if (failed.length) { console.error('FAIL wiki page review cases: ' + failed.join(' / ')); process.exit(1); }
  console.log('PASS wiki page (10-29): host + rerun reuse, TOC folders/pages/heads, block edit → save(base_hash = content_hash) → next uses returned hash, CONFLICT keeps text (fixed sentence + draft + overwrite), cite → openArchiveSource / missing, @ insert, task toggle, history diff, drag order, Ctrl+F, create modal, no title/aria-label, index debounce, sha1 fallback, read-only / mobile; review 1–5 (source mode vs external edit, conflict reread vs queued save, restore vs editor, Ctrl+F under Obsidian modal, mid-queue failure); second review (restore with source box open, typing after save sent + CONFLICT, restore failure stays editable, reread throws not stuck, Esc / Ctrl+F from inputs outside the Wiki); third review (per-page op queue + page lock: restore while a source save is in flight, overwrite = one save and the draft survives its failure); fourth review (click another block while editing waits for the save and cancels if the page was replaced; title stays bound after switching to source mode mid-save); fifth round (short-id citations resolve to the prefixed item everywhere; Quartz-style force graph: deterministic convergence, fit without clipped labels, drag + reheat, hover fade, click opens, zoom label fade, global overlay, rAF cancelled on unload, reduced motion, 300 nodes); sixth round (drag keeps view + pointer offset, only known source prefixes, cached graph finishes via rAF, lostpointercapture / unload end the drag, offscreen pause + rerun reuse)');
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });

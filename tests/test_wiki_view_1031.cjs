// 10-31 个人 Wiki 整理（她：「程序不通……整一个都不太好用」「编辑时不要跳出来一个巨大的黑框，就正常改」「让 ai 改，操作也接上」
// 「拖动页面，有时会跑到下面去。目录也不方便隐藏」）：
//   编辑 = 原地改（编辑框套在 p / h2 / li 里，记号不显示，引用长 id 显示成 @1）；列表按条开；Enter 下一条 / 下一段，空条再 Enter 结束列表；
//   段落开头打 # / - / [] 换样子；开头 Backspace 去记号；Ctrl+Enter 新段落接在后面（以前把字插到了别段开头）；段间 ＋ 插一段；Ctrl+Z 撤销；
//   普通保存不锁页（Enter 下一段马上能打）；让 AI 改一段 / 整页（只拿建议，「用这版」才存，kind=ai，原文变了不套用）；
//   目录默认只展开当前页所在的文件夹、整栏收起 / 左下角「目录」打开；拖页到别的文件夹 = 改归属；没排过的页按建立先后（不随修改跳）；
//   Ctrl+F 搜正文、回车开第一「页」（以前开成文件夹）；删了能撤销 / 最近删除找回；首页不显示历史钮；新文件夹建好直接能写。
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const CODE = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('wiki-view.js');
const pyHash = text => crypto.createHash('sha1').update(text.replace(/\r\n?/g, '\n'), 'utf8').digest('hex').slice(0, 16);

// 合成数据（虚构）
const page = (id, title, { role = 'page', tags = [], order = null, index_tag = '', created = '2026-10-01T10:00:00+08:00', body = '' } = {}) => ['---', `id: ${id}`, `title: ${title}`, `role: ${role}`,
  index_tag ? `index_tag: ${index_tag}` : null, order ? `order: ${JSON.stringify(order)}` : null, `tags: ${JSON.stringify(tags)}`, `created: ${created}`, 'updated: 2026-10-20T10:00:00+08:00', '---', '', body].filter(x => x != null).join('\n');
const FILES = {
  '_archive/catalog-data.json': JSON.stringify({ built_at: '2026-10-29T09:00:00+08:00', items: [
    { id: 'xhs-aa1', title: '示例咖啡地图', tags: ['travel'], summary: '几家店', note: 'Web/示例/a.md', kind: 'image', attachment: 'none', search_fields: { body: '咖啡' } }] }),
  'Wiki.md': '---\nlb-page: wiki\n---\n',
  'PersonalWiki/旅行.md': page('pw-travel', '旅行', { role: 'topic', index_tag: 'travel', tags: ['travel'], order: ['pw-stay'], body: '学懂怎么选。\n' }),
  'PersonalWiki/做饭.md': page('pw-cook', '做饭', { role: 'topic', index_tag: 'cook', tags: ['cook'], created: '2026-10-02T10:00:00+08:00', body: '' }),
  'PersonalWiki/住宿偏好.md': page('pw-stay', '住宿偏好', { tags: ['travel'], body: '为什么记：每次都从头翻。\n\n## 在意什么\n- 安静\n- 干净\n- [ ] 预算？\n\n## 参考\n- [示例咖啡地图](lwa:xhs-aa1) — 喜欢\n\n结尾一段。\n' }),
  'PersonalWiki/京都.md': page('pw-kyoto', '京都', { tags: ['travel'], created: '2026-10-03T10:00:00+08:00', body: '种草先挂着，町屋民宿。\n' }),
  'PersonalWiki/早餐.md': page('pw-bf', '早餐', { tags: ['cook'], body: '燕麦。\n' }),
};

function fakeMeta(text) {
  const t = text.replace(/\r\n/g, '\n');
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(t);
  const meta = {};
  if (m) for (const line of m[1].split('\n')) { const mm = /^([\w-]+):\s*(.*)$/.exec(line); if (mm && mm[2].trim()) { const v = mm[2].trim(); try { meta[mm[1]] = /^["[]/.test(v) ? JSON.parse(v) : v; } catch { meta[mm[1]] = v; } } }
  return { meta, body: m ? t.slice(m[0].length).replace(/^\n+/, '') : t };
}
// 像真插件的假 wikiCall：读写同一个假磁盘，save 按磁盘核 base_hash
function fakePlugin() {
  let n = 0;
  const P = { calls: [], opened: [], delay: 1, V: null, trash: new Map(), aiText: '改好的一段。', aiFail: null, aiDelay: 1,
    pathOf(id) { for (const k of P.V.disk.keys()) { if (/^PersonalWiki\/[^/]+\.md$/.test(k) && fakeMeta(P.V.disk.get(k)).meta.id === id) return k; } return null; },
    write(path, pg) {
      const text = page(pg.id, pg.title, { role: pg.role, tags: pg.tags, order: pg.order && pg.order.length ? pg.order : null, index_tag: pg.index_tag, created: pg.created, body: pg.body });
      const next = `PersonalWiki/${pg.title}.md`;
      if (path && path !== next) P.V.disk.delete(path);
      P.V.set(next, text);
      return { ...pg, file: next.slice(13), hash: pyHash(text) };
    },
    async wikiCall(op, { args = [], input = null } = {}) {
      const call = { op, args, input }; P.calls.push(call);
      await tick(op === 'ai' ? P.aiDelay : P.delay);
      try { call.result = run(op, args, input); return call.result; }
      catch (e) { call.error = e; throw e; }
    },
    openArchiveSource(note) { P.opened.push(note); return Promise.resolve(); },
  };
  function run(op, args, input) {
    if (op === 'save') {
      const path = P.pathOf(input.id); const text = P.V.disk.get(path);
      if (input.base_hash && input.base_hash !== pyHash(text)) throw Object.assign(new Error('这页在别处改过了'), { code: 'CONFLICT' });
      const { meta, body } = fakeMeta(text);
      const pg = { id: input.id, title: input.title ?? meta.title, role: meta.role || 'page', index_tag: meta.index_tag || '', order: input.order ?? meta.order ?? [], tags: input.tags ?? meta.tags ?? [], created: meta.created, body: input.body ?? body };
      return { ok: true, message: '已保存', page: P.write(path, pg), changed: true };
    }
    if (op === 'create') {
      const topic = args.includes('--topic'); const fi = args.indexOf('--folder');
      const pg = { id: 'pw-new' + (++n), title: args[0], role: topic ? 'topic' : 'page', index_tag: topic ? args[0] : '', order: [], tags: topic ? [args[0]] : fi > 0 ? [args[fi + 1]] : [], created: '2026-10-31T10:00:0' + n + '+08:00', body: '' };
      return { ok: true, message: `已新建《${args[0]}》`, page: P.write(null, pg) };
    }
    if (op === 'delete') {
      const path = P.pathOf(args[0]); const name = '20261031-1200-' + path.slice(13);
      P.trash.set(name, P.V.disk.get(path)); P.V.disk.delete(path); P.V.set('PersonalWiki/.trash/' + name, P.trash.get(name));
      return { ok: true, id: args[0], title: fakeMeta(P.trash.get(name)).meta.title, trashed: name };
    }
    if (op === 'trash') return { ok: true, pages: [...P.trash.keys()].map(k => ({ name: k, id: fakeMeta(P.trash.get(k)).meta.id, title: fakeMeta(P.trash.get(k)).meta.title, at: '2026-10-31T12:00' })) };
    if (op === 'undelete') {
      const text = P.trash.get(args[0]); if (!text) throw Object.assign(new Error('删除记录里没有这一页了'), { code: 'NOT_FOUND' });
      P.trash.delete(args[0]); P.V.disk.delete('PersonalWiki/.trash/' + args[0]);
      const { meta, body } = fakeMeta(text);
      const pg = { id: meta.id, title: meta.title, role: meta.role, index_tag: meta.index_tag || '', order: meta.order || [], tags: meta.tags || [], created: meta.created, body };
      return { ok: true, message: `已找回《${meta.title}》`, page: P.write(null, pg) };
    }
    if (op === 'plan') return { ok: true, sections: P.planReply.sections, model: 'demo' };
    if (op === 'fill') return { ok: true, ...P.fillReply };
    if (op === 'ai') {
      if (P.aiFail) throw Object.assign(new Error(P.aiFail), { code: 'NOT_CONFIGURED' });
      return { ok: true, text: typeof P.aiText === 'function' ? P.aiText(input) : P.aiText, model: 'demo-model', lost_cites: [], scope: input.scope };
    }
    if (op === 'history') return { ok: true, versions: [] };
    if (op === 'index') return { ok: true };
    throw Object.assign(new Error('没写这个 op：' + op), { code: 'BAD_ARGS' });
  }
  return P;
}

async function open({ plugin, files = null } = {}) {
  delete globalThis.__lbState; delete globalThis.__lbListeners; delete globalThis.__lbWikiDrafts; delete globalThis.__lbPark;
  const made = makeApp({ files: files ? { ...FILES, ...files } : FILES, plugin, frontmatter: { 'Wiki.md': { 'lb-page': 'wiki' } } });
  if (plugin) plugin.V = made.V;
  const dom = makeDom();
  const A = dataviewBlock({ dom, app: made.app, code: CODE });
  await A.run(); await tick(5);
  return { A, dom, ...made };
}
const key = (A, el, k, extra = {}) => el.dispatchEvent(new A.window.KeyboardEvent('keydown', { key: k, bubbles: true, ...extra }));
const texts = (A, sel) => A.qa(sel).map(e => e.textContent);
const body = (V, f) => fakeMeta(V.get('PersonalWiki/' + f)).body;
const tools = A => A.qa('.lbw-tools button');
// 把所有文件夹点开（每点一次目录会重画，所以每次重新找）再点那一页
async function expandAll(A) { for (let k = 0; k < 9; k++) { const f = A.qa('.lbw-tfold').find(x => !x.classList.contains('is-open')); if (!f) return; f.querySelector('.lbw-tw').click(); await tick(1); } }
const openPage = async (A, id) => { await expandAll(A); A.q(`.lbw-tpage[data-page="${id}"]`).click(); await tick(2); };
const blk = (A, text) => A.qa('.lbw-blk').find(b => b.textContent.includes(text));
const failed = [];
const run = async (name, fn) => { try { await fn(); console.log('  ok   ' + name); } catch (e) { failed.push(name); console.log('  FAIL ' + name + '\n       ' + String(e && e.stack || e).split('\n').slice(0, 3).join('\n       ')); } };

(async () => {
  await run('目录：首页全收起、打开一页只展开它所在的文件夹；没排过的页按建立先后', async () => {
    const P = fakePlugin(); const { A } = await open({ plugin: P });
    assert.deepEqual(texts(A, '.lbw-tpage'), [], '首页：文件夹都收起（以前全摊开）');
    await openPage(A, 'pw-stay');
    // 打开一页后清掉手动展开，看默认：只有「旅行」开着
    tools(A)[2].click(); await tick(1);    // 全部收起（写进 PREFS.open）
    assert.deepEqual(texts(A, '.lbw-tpage'), []);
    A.qa('.lbw-tfold')[0].querySelector('.lbw-tw').click(); await tick(1);
    assert.deepEqual(texts(A, '.lbw-tpage'), ['住宿偏好', '京都'], 'order 里的在前；没排过的按建立先后（不按修改时间跳）');
    assert.ok(A.q('.lbw-tpage.is-current'), '当前页加粗');
    assert.ok(A.qa('.lbw-thead').length >= 2, '当前页的小标题在目录里');
  });

  await run('目录整栏收起 / 左下角「目录」打开（记住）', async () => {
    const P = fakePlugin(); const { A } = await open({ plugin: P });
    const wrap = A.q('.lbw');
    tools(A).find(b => b.textContent.includes('收起目录')).click(); await tick(1);
    assert.ok(wrap.classList.contains('is-tocoff'), '整栏收起');
    A.q('.lbw-fab').click(); await tick(1);
    assert.ok(!wrap.classList.contains('is-tocoff'), '「目录」钮打开');
  });

  await run('原地改：段落 / 列表一条 / 标题，记号不显示；首页没有历史钮', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    assert.ok(A.q('.lbw-hbtn[data-hist]').hidden, '首页不显示历史钮');
    await openPage(A, 'pw-stay');
    assert.ok(!A.q('.lbw-hbtn[data-hist]').hidden);
    blk(A, '干净').click();
    let ta = A.q('.lbw-ed');
    assert.equal(ta.value, '干净', '点一条只开这一条，「- 」不显示');
    assert.equal(ta.parentElement.tagName, 'LI', '编辑框套在 li 里（样式跟阅读时一样）');
    assert.ok(A.q('.lbw-blk.is-editing .lbw-edbar'), '浅色小工具条');
    ta.value = '干净整洁'; key(A, ta, 'Escape'); await tick(10);
    assert.ok(body(V, '住宿偏好.md').includes('- 安静\n- 干净整洁\n- [ ] 预算？'), '只改了那一条：' + body(V, '住宿偏好.md'));
    blk(A, '在意什么').click(); ta = A.q('.lbw-ed');
    assert.equal(ta.value, '在意什么'); assert.ok(ta.closest('h2'));
    key(A, ta, 'Escape'); await tick(5);
    blk(A, '示例咖啡地图').click(); ta = A.q('.lbw-ed');
    assert.equal(ta.value, '[示例咖啡地图](@1) — 喜欢', '引用的长 id 显示成 @1');
    ta.value = ta.value + '！'; key(A, ta, 'Escape'); await tick(10);
    assert.ok(body(V, '住宿偏好.md').includes('- [示例咖啡地图](lwa:xhs-aa1) — 喜欢！'), '存回完整 id');
    assert.ok(body(V, '住宿偏好.md').includes('## 参考\n- [示例'), '没多补空行');
  });

  await run('Enter 下一条 / 空条结束列表 / Ctrl+Enter 新段落接在后面 / 开头 Backspace 去记号 / 段落开头打记号', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-stay');
    blk(A, '安静').click(); let ta = A.q('.lbw-ed');
    ta.setSelectionRange(2, 2); key(A, ta, 'Enter'); await tick(5);
    ta = A.q('.lbw-ed'); assert.ok(ta && ta.parentElement.tagName === 'LI', 'Enter：下一条列表，马上能打（不等保存）');
    ta.value = '朝南' + ta.value; ta.setSelectionRange(ta.value.length, ta.value.length); key(A, ta, 'Enter'); await tick(5);
    ta = A.q('.lbw-ed'); assert.equal(ta.value, '');
    key(A, ta, 'Enter'); await tick(1);
    assert.equal(A.q('.lbw-ed').parentElement.tagName, 'P', '空的一条再 Enter = 结束列表，变成段落');
    ta = A.q('.lbw-ed'); ta.value = '列表后面的话'; key(A, ta, 'Escape'); await tick(20);
    let b = body(V, '住宿偏好.md');
    assert.ok(b.includes('- 安静\n- 朝南\n\n列表后面的话\n\n- 干净'), b);
    // Ctrl+Enter：10-31 走查发现以前新写的段按 Ctrl+Enter，接着打的字跑到别段开头
    A.q('.lbw-addblk').click(); ta = A.q('.lbw-ed');
    ta.value = '第二段'; key(A, ta, 'Enter', { ctrlKey: true }); await tick(5);
    ta = A.q('.lbw-ed'); ta.value = '第三段'; key(A, ta, 'Escape'); await tick(20);
    b = body(V, '住宿偏好.md');
    assert.ok(b.endsWith('结尾一段。\n\n第二段\n\n第三段') || b.endsWith('结尾一段。\n\n第二段\n\n第三段\n'), JSON.stringify(b.slice(-40)));
    // 开头 Backspace：标题 → 正文
    blk(A, '在意什么').click(); ta = A.q('.lbw-ed'); ta.setSelectionRange(0, 0);
    key(A, ta, 'Backspace');
    assert.equal(A.q('.lbw-ed').parentElement.tagName, 'P', '开头退格去掉标题记号');
    key(A, A.q('.lbw-ed'), 'Escape'); await tick(20);
    assert.ok(body(V, '住宿偏好.md').includes('\n在意什么\n'), body(V, '住宿偏好.md'));
    // 段落开头打 [] → 待办
    A.q('.lbw-addblk').click(); ta = A.q('.lbw-ed');
    ta.value = '[] 订机票'; ta.setSelectionRange(3, 3); ta.dispatchEvent(new A.window.Event('input'));
    ta = A.q('.lbw-ed'); assert.equal(ta.value, '订机票'); assert.ok(ta.closest('.lbw-task'), '[] 开头 = 待办');
    key(A, ta, 'Escape'); await tick(20);
    assert.ok(body(V, '住宿偏好.md').includes('- [ ] 订机票'));
  });

  await run('段间 ＋ 插一段；Ctrl+Z 撤销', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-stay');
    blk(A, '为什么记').querySelector('.lbw-ins').click(); await tick(1);
    const ta = A.q('.lbw-ed'); assert.ok(ta, '＋：在这段后面开一段新的');
    ta.value = '插进来的一段'; key(A, ta, 'Escape'); await tick(20);
    assert.ok(body(V, '住宿偏好.md').startsWith('为什么记：每次都从头翻。\n\n插进来的一段\n\n## 在意什么'), body(V, '住宿偏好.md'));
    key(A, A.dom ? A.dom.document : A.window.document, 'z', { ctrlKey: true }); await tick(20);
    assert.ok(!body(V, '住宿偏好.md').includes('插进来的一段'), 'Ctrl+Z 撤销上一步（也存盘）');
    assert.ok(A.notices.some(m => m.includes('撤销了上一步')));
  });

  await run('普通保存不锁页：存着的时候标题 / 待办照常能改，连着改都存上', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-stay');
    P.delay = 40;
    blk(A, '为什么记').click(); A.q('.lbw-ed').value = '第一处。'; key(A, A.q('.lbw-ed'), 'Escape');
    assert.ok(!A.q('.lbw-task input').disabled);
    A.q('.lbw-task input').click();   // 存着的时候勾待办：排在后面
    blk(A, '结尾一段').click(); A.q('.lbw-ed').value = '结尾改了。'; key(A, A.q('.lbw-ed'), 'Escape');
    await tick(200); P.delay = 1; await tick(20);
    const b = body(V, '住宿偏好.md');
    assert.ok(b.startsWith('第一处。') && b.includes('- [x] 预算？') && b.includes('结尾改了。'), b);
    assert.ok(P.calls.filter(c => c.op === 'save').length <= 3, '还没轮到的保存合成一次');
    assert.equal(A.qa('.lbw-draft').length, 0);
  });

  await run('让 AI 改：范围 = 光标所在那一节；范围里锁住；按字比、逐处勾选；用选中的 = 一次存（kind=ai）、Ctrl+Z 一步撤', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-stay');
    blk(A, '干净').click();                                   // 光标在「在意什么」那一节的一条里
    A.q('.lbw-hbtn[data-ai]').click(); await tick(5);
    assert.ok(A.q('.lbw-dock .lbw-ai[data-scope="part"]'), '页头「AI」：底部对话框，范围 = 光标所在那一节');
    assert.ok(A.q('.lbw-dock-head').textContent.includes('改「在意什么」这一节'));
    assert.ok(!A.q('.lbw-edbar [data-ai]'), '格式条上没有「AI 改」了');
    assert.deepEqual(texts(A, '.lbw-ai [data-preset]'), ['润色', '精简', '说清楚一点', '改成列表', '只改错字']);
    assert.equal(A.qa('.lbw-blk.is-ai-lock').length, 4, '这一节（小标题 + 三条）锁住');
    blk(A, '干净').click(); await tick(1);
    assert.equal(A.q('.lbw-ed'), null, '锁住的段点了不开编辑'); assert.ok(A.notices.at(-1).includes('在让 AI 改'));
    P.aiText = '## 在意什么\n- 安静的房间\n- 干净\n- [ ] 预算多少？';
    A.q('.lbw-ai [data-preset="polish"]').click(); await tick(15);
    const call = P.calls.find(c => c.op === 'ai');
    assert.deepEqual([call.input.scope, call.input.preset, call.input.text], ['part', 'polish', '## 在意什么\n- 安静\n- 干净\n- [ ] 预算？']);
    const hk = A.qa('.lbw-ai-diff .lbw-hk');
    assert.equal(hk.length, 2, '两处改动：「的房间」「多少」（中文按字比，不是整行）');
    assert.deepEqual(hk.map(x => x.querySelector('ins') && x.querySelector('ins').textContent), ['的房间', '多少']);
    assert.ok(A.q('.lbw-ai').textContent.includes('改了 2 处，选了 2 处'));
    hk[0].click(); await tick(1);                              // 第一处不要
    assert.ok(A.q('.lbw-ai-diff .lbw-hk[data-h]').classList.contains('is-off'));
    assert.equal(A.q('.lbw-ai [data-ai="apply"]').textContent, '用选中的 1 处');
    A.q('.lbw-ai [data-ai="apply"]').click(); await tick(20);
    const sv = P.calls.filter(c => c.op === 'save').at(-1);
    assert.equal(sv.input.kind, 'ai'); assert.match(sv.input.note, /AI：润色（用了 1\/2 处）/);
    assert.ok(body(V, '住宿偏好.md').includes('## 在意什么\n- 安静\n- 干净\n- [ ] 预算多少？\n'), body(V, '住宿偏好.md'));
    assert.equal(A.qa('.lbw-blk.is-ai-lock').length, 0, '用完解锁');
    key(A, A.window.document, 'z', { ctrlKey: true }); await tick(20);
    assert.ok(body(V, '住宿偏好.md').includes('- [ ] 预算？'), 'Ctrl+Z 一步撤回');
  });

  await run('让 AI 改：等的时候别处加了行 → 跟着挪照样套用；那截原文被改了 → 作废；没配 AI 说清楚；AI 没改说没改', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-stay');
    blk(A, '结尾一段').click(); A.q('.lbw-hbtn[data-ai]').click(); await tick(5);
    P.aiDelay = 40; P.aiText = '结尾改了一段。';
    const inp = A.q('.lbw-ai input'); inp.value = '语气轻一点'; key(A, inp, 'Enter'); await tick(5);
    assert.ok(A.q('.lbw-ai').textContent.includes('AI 在改'));
    assert.equal(P.calls.filter(c => c.op === 'ai').at(-1).input.instruction, '语气轻一点', '自己说的话原样给 AI');
    blk(A, '为什么记').querySelector('.lbw-ins').click(); await tick(1);   // 等的时候在上面插一段
    A.q('.lbw-ed').value = '上面新插的一段'; key(A, A.q('.lbw-ed'), 'Escape'); await tick(10);
    await tick(60); P.aiDelay = 1;
    A.q('.lbw-ai [data-ai="apply"]').click(); await tick(20);
    assert.ok(body(V, '住宿偏好.md').includes('上面新插的一段') && body(V, '住宿偏好.md').includes('结尾改了一段。') && !body(V, '住宿偏好.md').includes('结尾一段。'), '行号挪了也套在对的地方');
    // 原文被改了 → 作废
    blk(A, '为什么记').click(); A.q('.lbw-hbtn[data-ai]').click(); await tick(5);
    P.aiText = '为什么记：改过。';
    A.q('.lbw-ai [data-preset="fix"]').click(); await tick(15);
    V.set('PersonalWiki/住宿偏好.md', V.get('PersonalWiki/住宿偏好.md').replace('为什么记：每次都从头翻。', '在 Obsidian 里改了这句。')); await tick(700);
    const n0 = P.calls.filter(c => c.op === 'save').length;
    A.q('.lbw-ai [data-ai="apply"]').click(); await tick(10);
    assert.equal(P.calls.filter(c => c.op === 'save').length, n0, '没套用');
    assert.ok(A.notices.at(-1).includes('改过了，没套用'));
    A.qa('.lbw-ai button').find(b => b.textContent === '不要').click(); await tick(2);
    // 没配 AI
    blk(A, '结尾改了').click(); A.q('.lbw-hbtn[data-ai]').click(); await tick(5);
    P.aiFail = 'AI 没改成：没有能用的文本 AI（没配）';
    A.q('.lbw-ai [data-preset="fix"]').click(); await tick(15);
    assert.ok(A.q('.lbw-ai').textContent.includes('没有能用的文本 AI'), '原因写在面板上');
    P.aiFail = null; P.aiText = input => input.text;   // 原样回来
    A.q('.lbw-ai [data-preset="fix"]').click(); await tick(15);
    assert.ok(A.q('.lbw-ai').textContent.includes('一个字都没改'));
  });

  await run('让 AI 改整页：右侧栏逐处勾选，不再整页「用这版」', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-kyoto');
    A.q('.lbw-hbtn.is-more').click();
    A.qa('.lbw-pop button').find(b => b.textContent.startsWith('让 AI 改整页')).click(); await tick(2);
    assert.ok(A.q('.lbw-dock .lbw-ai[data-scope="page"]') && A.q('.lbw-side').hidden, '底部对话框（不占右侧栏）');
    assert.deepEqual(texts(A, '.lbw-dock [data-preset]'), ['理顺结构', '精简', '从引用补要点', '搭个框架', '润色']);
    assert.ok(A.qa('.lbw-blk.is-ai-lock').length >= 1, '整页锁住');
    P.aiText = '## 为什么\n种草先挂着，町屋民宿。\n\n## 想住\n- 町屋';
    A.q('.lbw-dock [data-preset="structure"]').click(); await tick(15);
    assert.ok(A.qa('.lbw-dock .lbw-hk').length >= 2, '逐处');
    A.q('.lbw-dock [data-ai="none"]').click(); await tick(1);
    assert.ok(A.q('.lbw-dock [data-ai="apply"]').getAttribute('disabled') != null, '全不要时「用」点不了');
    A.q('.lbw-dock [data-ai="all"]').click(); await tick(1);
    A.q('.lbw-dock [data-ai="apply"]').click(); await tick(20);
    assert.ok(body(V, '京都.md').startsWith('## 为什么\n种草先挂着，町屋民宿。\n\n## 想住'), body(V, '京都.md'));
    assert.ok(!A.q('.lbw-dock'), '用完收起');
  });

  await run('按我的思路搭框架：写思路 → 出计划 → 改计划 → 去收藏里找 → 逐处勾选存；原话没对上的标红', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-kyoto');
    A.q('.lbw-hbtn.is-more').click();
    A.qa('.lbw-pop button').find(b => b.textContent.startsWith('按我的思路搭框架')).click(); await tick(2);
    assert.ok(A.q('.lbw-dock .lbw-ai[data-mode="plan"] textarea'), '右侧栏先写思路');
    A.q('.lbw-dock [data-plan="make"]').click(); await tick(2);
    assert.ok(A.notices.at(-1).includes('先写几句'), '空思路不发');
    const ta = A.q('.lbw-dock textarea'); ta.value = '想住町屋，想要两节：住哪、怎么订'; ta.dispatchEvent(new A.window.Event('input'));
    P.planReply = { sections: [{ title: '住哪', query: '京都 町屋 民宿', why: '' }, { title: '怎么订', query: '京都 订房', why: '' }, { title: '多余的一节', query: 'x', why: '' }] };
    A.q('.lbw-dock [data-plan="make"]').click(); await tick(15);
    assert.equal(P.calls.find(c => c.op === 'plan').input.idea, '想住町屋，想要两节：住哪、怎么订');
    assert.equal(A.qa('.lbw-dock .lbw-plan-sec').length, 3, '计划三节');
    A.q('.lbw-dock [data-del="2"]').click(); await tick(1);              // 删掉多余的
    const q0 = A.q('.lbw-dock input[data-f="query"]'); q0.value = '京都 町屋 一个人'; q0.dispatchEvent(new A.window.Event('input'));
    P.fillReply = { text: '种草先挂着，町屋民宿。\n\n## 住哪\n\n- 町屋安静。 [示例咖啡地图](lwa:xhs-aa1)\n  > 「几家店」\n\n## 怎么订\n\n- 提前两个月。 [示例咖啡地图](lwa:xhs-aa1)\n  > 「瞎编的」（⚠ 原帖里没找到这句，别直接信）',
      sources: [{ n: 'S1', id: 'xhs-aa1', title: '示例咖啡地图' }], bad_quotes: [{ src: 'S1', title: '示例咖啡地图', quote: '瞎编的' }], dropped: 1, model: 'demo' };
    A.q('.lbw-dock [data-plan="fill"]').click(); await tick(15);
    const fc = P.calls.find(c => c.op === 'fill');
    assert.deepEqual(fc.input.sections.map(s => [s.title, s.query]), [['住哪', '京都 町屋 一个人'], ['怎么订', '京都 订房']], '改过的计划原样交给后端');
    assert.equal(fc.input.text, '种草先挂着，町屋民宿。\n', '交的是这页现在的正文');
    assert.ok(A.qa('.lbw-dock .lbw-hk').length >= 1, '逐处勾选');
    assert.ok(A.q('.lbw-dock .lbw-ai-bad').textContent.includes('瞎编的'), '原话没对上的标出来');
    assert.ok(A.q('.lbw-dock .lbw-ai-srcs').textContent.includes('S1 示例咖啡地图'));
    assert.ok(A.q('.lbw-dock').textContent.includes('1 条引了不存在的编号'));
    A.q('.lbw-dock [data-ai="apply"]').click(); await tick(20);
    const sv = P.calls.filter(c => c.op === 'save').at(-1);
    assert.equal(sv.input.kind, 'ai'); assert.match(sv.input.note, /按思路搭框架/);
    assert.ok(body(V, '京都.md').startsWith('种草先挂着，町屋民宿。\n\n## 住哪'), body(V, '京都.md'));
  });

  await run('页头和问收藏对齐：一行（标题 + 三页切换 + 右边 AI · 历史 · …）；页头「AI」默认改哪一截', async () => {
    const P = fakePlugin(); const { A } = await open({ plugin: P });
    const row = A.q('.lbw-hrow');
    assert.ok(row.querySelector('.lb-page-nav'), '三页切换和标题在同一行');
    assert.deepEqual(A.qa('.lbw-acts .lbw-hbtn').map(b => b.dataset.ai ? 'AI' : b.dataset.hist ? '历史' : b.classList.contains('is-more') ? '…' : '?'), ['AI', '历史', '…'], '从左到右 AI · 历史 · …');
    A.q('.lbw-hbtn[data-ai]').click(); await tick(1);
    assert.ok(A.notices.at(-1).includes('先打开一页'), '首页点 AI：先打开一页');
    await openPage(A, 'pw-kyoto');
    A.q('.lbw-hbtn[data-ai]').click(); await tick(2);
    assert.ok(A.q('.lbw-dock .lbw-ai[data-scope="page"]'), '没点过哪段：改整页');
    assert.ok(A.q('.lbw-dock-head [data-scope="page"]').classList.contains('is-on'));
    A.q('.lbw-dock-head [data-scope="plan"]').click(); await tick(2);
    assert.ok(A.q('.lbw-dock .lbw-ai[data-mode="plan"]'), '对话框顶上切到「按我的思路搭框架」');
    A.q('.lbw-hbtn[data-ai]').click(); await tick(2);
    assert.ok(!A.q('.lbw-dock'), '再点一次页头 AI = 收起');
    blk(A, '种草').click(); key(A, A.q('.lbw-ed'), 'Escape'); await tick(10);   // 点过一段
    A.q('.lbw-hbtn[data-ai]').click(); await tick(2);
    assert.ok(A.q('.lbw-dock .lbw-ai[data-scope="part"]'), '点过某段：改那一节');
    key(A, A.window.document, 'Escape'); await tick(2);
    assert.ok(!A.q('.lbw-dock'), 'Esc 收起');
    const P2 = fakePlugin(); const { A: B } = await open({ plugin: P2, files: { 'PersonalWiki/空页.md': page('pw-empty', '空页', {}) } });
    await openPage(B, 'pw-empty');
    B.q('.lbw-hbtn[data-ai]').click(); await tick(2);
    assert.ok(B.q('.lbw-dock .lbw-ai[data-mode="plan"]'), '空页：直接按思路搭框架');
  });

  await run('空页：「让 AI 先搭个框架」', async () => {
    const P = fakePlugin(); const { A } = await open({ plugin: P, files: { 'PersonalWiki/空页.md': page('pw-empty', '空页', {}) } });
    await openPage(A, 'pw-empty');
    const d = A.q('[data-ai="draft"]'); assert.ok(d);
    d.click(); await tick(2);
    assert.ok(A.q('.lbw-dock .lbw-ai[data-mode="plan"] textarea'), '空页：写思路搭框架');
  });

  await run('Ctrl+F 搜正文，回车开第一「页」（以前开成文件夹）', async () => {
    const P = fakePlugin(); const { A } = await open({ plugin: P });
    key(A, A.window.document, 'f', { ctrlKey: true });
    const f = A.q('.lbw-find'); f.value = '町屋'; f.dispatchEvent(new A.window.Event('input'));
    assert.deepEqual(A.qa('.lbw-tpage').map(b => b.dataset.page), ['pw-kyoto'], '正文里搜到');
    assert.ok(A.q('.lbw-tsnip').textContent.includes('町屋'), '带命中那句');
    f.value = '京都'; f.dispatchEvent(new A.window.Event('input'));
    key(A, f, 'Enter'); await tick(2);
    assert.equal(A.q('.lbw-ptitle').value, '京都', '回车开的是页，不是它所在的文件夹');
  });

  await run('拖页：到别的文件夹 = 换文件夹（标签 + 那边的顺序）；到未归类 = 拿出来', async () => {
    const P = fakePlugin(); const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-kyoto');
    await expandAll(A);
    const kyoto = A.q('.lbw-tpage[data-page="pw-kyoto"]'), bf = A.q('.lbw-tpage[data-page="pw-bf"]');
    kyoto.dispatchEvent(new A.window.Event('dragstart', { dataTransfer: { setData() {} } }));
    bf.dispatchEvent(new A.window.Event('dragover', { clientY: -1 }));
    assert.ok(bf.classList.contains('is-drop-before'));
    bf.dispatchEvent(new A.window.Event('drop', { clientY: -1 })); await tick(20);
    assert.deepEqual(fakeMeta(V.get('PersonalWiki/京都.md')).meta.tags, ['cook'], '标签换成那个文件夹的');
    assert.deepEqual(fakeMeta(V.get('PersonalWiki/做饭.md')).meta.order, ['pw-kyoto', 'pw-bf'], '排在放下的位置');
    const k2 = A.q('.lbw-tpage[data-page="pw-kyoto"]');
    k2.dispatchEvent(new A.window.Event('dragstart', { dataTransfer: { setData() {} } })); await tick(1);
    const loose = A.q('.lbw-tfold[data-fold="__loose"]'); assert.ok(loose, '拖着的时候「未归类」也能放');
    loose.dispatchEvent(new A.window.Event('dragover', {})); loose.dispatchEvent(new A.window.Event('drop', {})); await tick(20);
    assert.deepEqual(fakeMeta(V.get('PersonalWiki/京都.md')).meta.tags, [], '拿出文件夹');
  });

  await run('删了能撤销；最近删除里找回；新文件夹建好直接能写', async () => {
    const P = fakePlugin(); let asked = 0; P.confirm = async () => { asked++; return true; };
    const { A, V } = await open({ plugin: P });
    await openPage(A, 'pw-kyoto');
    A.q('.lbw-hbtn.is-more').click();
    A.qa('.lbw-pop button').find(b => b.textContent.startsWith('删除这一页')).click(); await tick(20);
    assert.equal(asked, 1, '先确认');
    assert.ok(!V.get('PersonalWiki/京都.md'), '删了');
    assert.ok(A.notices.at(-1).startsWith('已删《京都》'));
    {
      A.q('.lbw-hbtn.is-more').click();
      A.qa('.lbw-pop button').find(b => b.textContent.startsWith('最近删除')).click(); await tick(10);
      const u = A.q('.lbw-side [data-undelete]'); assert.ok(u, '最近删除里有它');
      u.click(); await tick(20);
      assert.ok(V.get('PersonalWiki/京都.md'), '找回了');
      assert.equal(A.q('.lbw-ptitle').value, '京都', '找回后打开它');
    }
    tools(A)[0].click(); await tick(1);
    A.q('.lbw-fold.is-new').click();
    A.q('.lbw-modal input').value = '读书'; await A.q('.lbw-modal').requestSubmit(); await tick(10);
    assert.ok(A.q('.lbw-ed'), '新文件夹建好直接进编辑');
  });

  await run('不闪：量到宽度 0（Dataview 重跑那一下）不切布局、首页不重画；分界线附近有缓冲；收起目录压过中等宽度', async () => {
    const P = fakePlugin(); const { A } = await open({ plugin: P });
    const wrap = A.q('.lbw');
    A.resize.trigger(1000, 800); await tick(200);
    assert.ok(wrap.classList.contains('is-mid'));
    const first = A.q('.lbw-center').firstChild;
    A.resize.trigger(0, 800); await tick(200);
    assert.ok(wrap.classList.contains('is-mid'), '宽度 0 不算：还是中等宽');
    A.resize.trigger(1000, 800); await tick(200);
    assert.equal(A.q('.lbw-center').firstChild, first, '首页没有重画');
    A.resize.trigger(1050, 800); await tick(200);
    assert.ok(wrap.classList.contains('is-mid'), '刚过 1040 不翻（缓冲 24px）');
    assert.equal(A.q('.lbw-center').firstChild, first);
    A.resize.trigger(1100, 800); await tick(200);
    assert.ok(!wrap.classList.contains('is-mid'), '真变宽了才翻');
    const css = A.window.document.getElementById('lb-wiki-style').textContent;
    assert.ok(css.includes('.lbw.is-mid.is-tocoff.is-home:not(.is-narrow) .lbw-main{grid-template-columns:minmax(0,1fr);}'), '收起目录压过中等宽度两列');
  });

  if (failed.length) { console.log('FAIL wiki 10-31: ' + failed.join(' / ')); process.exit(1); }
  console.log('PASS wiki 10-31: in-place editing (li per item, markers hidden, @n cite tokens, Enter/empty-Enter/Ctrl+Enter/Backspace/shortcuts, insert between, Ctrl+Z), saves no longer lock, AI block/page/draft, TOC current-folder only + hide, body search, cross-folder drag, delete undo + trash, new folder editor');
})().catch(e => { console.error(e); process.exit(1); });

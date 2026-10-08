// 批次 D 地基：lb-page-lib.js 的共享接口（mountHost / reuseDom 版本语义 / adopt / style / 手机与跳页 / 提示与确认 / 菜单 / 焦点兜底 / activeLeafHas）。
// 用升级后的假 DOM（tests/_fakedom.cjs）：容器带行内 overflow-x:auto、脱离文档即失焦、component 可卸载。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeVault, makeApp, dataviewBlock } = require('./_fakedom.cjs');
const { makeClock } = require('./_clock.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const DATA = '_archive/catalog-data.json';
const catalog = (n, extra = {}) => JSON.stringify({ built_at: '2026-10-08T05:09:12+10:00', items: Array.from({ length: n }, (_, i) => ({ id: 'n' + i, title: 't' + i })), ...extra });
const LIB = asset('lb-page-lib.js');
// 最小页面：挂 host、搜索框、计数；update 可注入失败
const PAGE = LIB + `
const LB = lbPageLib(dv, app, 'catalog');
globalThis.__LB = LB;
if (await LB.reuseDom()) return;
globalThis.__built = (globalThis.__built || 0) + 1;
const host = LB.mountHost('t-host');
const wrap = host.createEl('div', { cls: 'lbc-wrap' });
const input = wrap.createEl('input', { cls: 'lbc-search' });
LB.trackFocus(input, 'search');
const data = await LB.data.load();
globalThis.__data = data;
const count = wrap.createEl('div', { cls: 'count', text: String(data.items.length) });
LB.keep(wrap, { version: await LB.data.version(), update: async v => {
  if (globalThis.__failUpdate) { globalThis.__failUpdate--; throw new Error('读坏了'); }
  globalThis.__updates = (globalThis.__updates || 0) + 1;
  const d = await LB.data.load(); count.setText(String(d.items.length));
} });
LB.restoreFocus(input, 'search');
`;
const fresh = () => { for (const k of ['__lbState', '__lbListeners', '__LB', '__built', '__data', '__failUpdate', '__updates', '__lbNotices', '__lbUndoNotice']) delete globalThis[k]; };

async function hostAndVersion() {
  fresh();
  const dom = makeDom();
  const plugin = { settings: {} };
  const { app, V } = makeApp({ files: { [DATA]: catalog(3) }, plugin });
  const A = dataviewBlock({ dom, app, code: PAGE });
  await A.run();
  const host = A.container.nextSibling;
  // mountHost：host 是容器的兄弟，容器本身空着；容器带 Dataview 的行内 overflow-x:auto
  assert.equal(A.container.style.overflowX, 'auto');
  assert.equal(A.container.children.length, 0, '页面不进 dv.container');
  assert.ok(host && host.classList.contains('lb-page-host') && host.classList.contains('t-host'));
  assert.equal(host.dataset.lbRole, 'catalog'); assert.equal(host.getAttribute('data-lb-role'), 'catalog');
  const wrap = host.querySelector('.lbc-wrap'), input = wrap.querySelector('.lbc-search');
  assert.equal(wrap.parentNode, host);
  // 重跑 3 次：host、wrap 都是同一个对象，搜索框焦点和字都在，不重建
  input.focus(); input.value = 'ka';
  for (let i = 0; i < 3; i++) await A.rerun();
  assert.equal(A.container.nextSibling, host); assert.equal(host.querySelector('.lbc-wrap'), wrap);
  assert.equal(dom.document.activeElement, input, '重跑 3 次后焦点还在');
  assert.equal(input.value, 'ka'); assert.equal(globalThis.__built, 1, '没整页重建');
  assert.equal(A.qa('.lb-page-host').length, 1, 'q / qa 在 section 范围里找得到 host');

  // reuseDom 版本语义：update 抛错 → 版本不推进、记 lastError；下次重跑重试成功才推进
  const view = A.container.__lbView, v1 = view.version;
  assert.equal(view.host, host, 'keep 连 host 一起登记');
  V.set(DATA, catalog(5));
  globalThis.__failUpdate = 1;
  await A.rerun();
  assert.equal(view.version, v1, 'update 失败：版本不推进');
  assert.equal(view.lastError?.message, '读坏了');
  assert.equal(wrap.querySelector('.count').textContent, '3');
  await A.rerun();
  assert.notEqual(view.version, v1, '第二次重跑重试成功、版本推进');
  assert.equal(view.lastError, null); assert.equal(globalThis.__updates, 1);
  assert.equal(wrap.querySelector('.count').textContent, '5');
  await A.rerun(); assert.equal(globalThis.__updates, 1, '版本相同不再 update');
  // updating 锁：update 进行中又来一次重跑 → 只挂回 DOM、不叠第二次 update
  V.set(DATA, catalog(6));
  let release; globalThis.__failUpdate = 0;
  const slow = view.update; view.update = async v => { await new Promise(r => { release = r; }); return slow(v); };
  const first = A.rerun(); await tick(5);
  assert.ok(view.updating, '进行中锁');
  await A.rerun();
  assert.equal(globalThis.__updates, 1, '叠在一起的重跑不再起第二次 update');
  release(); await first;
  assert.equal(globalThis.__updates, 2); assert.equal(view.updating, null);
  // 撞锁的那次重跑带来了更新的版本（复审 race）：update 读完 7 还没结束时写了 8 并重跑（撞锁返回）→ 这一轮做完再核磁盘版本，接着更新到 8
  V.set(DATA, catalog(7));
  let release2; view.update = async v => { await slow(v); await new Promise(r => { release2 = r; }); };
  const second = A.rerun(); await tick(5);
  assert.equal(wrap.querySelector('.count').textContent, '7', 'update 读到 7 后挂起');
  V.set(DATA, catalog(8));
  await A.rerun();
  assert.ok(view.updating, '撞锁：这一次只挂回 DOM');
  view.update = slow;
  release2(); await second;
  const LB = globalThis.__LB;
  assert.equal(wrap.querySelector('.count').textContent, '8', '撞锁带来的新版本没丢');
  assert.equal(view.version, await LB.data.version(), 'view.version 跟上磁盘');
  assert.equal(view.updating, null);
  // 锁 30 秒兜底：上一轮 update 卡死（永不 resolve）→ 之后的重跑照样更新
  V.set(DATA, catalog(9));
  view.updating = { at: Date.now() - 31000 };
  await A.rerun();
  assert.equal(wrap.querySelector('.count').textContent, '9', '卡死的锁不挡后面的更新');
  assert.equal(view.updating, null);
  const updatesNow = globalThis.__updates;

  // adopt：页面刚改过 catalog-data（点星 → patch_items），内存那份就是插件缓存那份 → 推进两边版本，下次重跑 0 读
  const cached = plugin.catalogCache.data;
  assert.equal(cached.items.length, 9, '插件缓存里是最近一次 update 读进来的那份');
  cached.items[0].starred = true;   // 乐观改了内存（缓存同一份对象）
  V.set(DATA, catalog(9, { patched: true }));
  V.resetCounts();
  const v = await LB.data.version();
  const st = await app.vault.adapter.stat(DATA);
  assert.equal(LB.data.adopt(v, {}), false, '不是缓存那份对象：不推进');
  // written（写者报回的写完那一刻的 stat）对不上 = 写者放锁之后别人又写过 → 不 adopt
  assert.equal(LB.data.adopt(v, cached, { mtime: st.mtime + 5, size: st.size }), false, 'written 的 mtime 对不上：不 adopt');
  assert.equal(LB.data.adopt(v, cached, { mtime: st.mtime, size: st.size + 1 }), false, 'written 的 size 对不上：不 adopt');
  assert.notEqual(plugin.catalogCache.version, v, '没 adopt 就没推进');
  assert.equal(LB.data.adopt(v, cached, `${st.mtime + 1}:${st.size}`), true, 'mtime 差 1ms 也认（Obsidian 的 stat 是 Math.round）');
  assert.equal(plugin.catalogCache.version, v); assert.equal(view.version, v);
  assert.equal(LB.data.adopt(v, cached), true, '不给 written：照旧推进（兼容）');
  await A.rerun();
  assert.equal(V.reads[DATA] || 0, 0, 'adopt 之后重跑读文件 0 次');
  assert.equal(globalThis.__updates, updatesNow, '也不走 update');
  // adopt 只推进「版本看 catalog-data」的那一页：批注块（版本看 notes.json）只推进插件缓存
  {
    fresh();
    const NOTE = '_archive/xiaohongshu/n1/notes.json';
    const p2 = { settings: {} };
    const m2 = makeApp({ files: { [DATA]: catalog(2), [NOTE]: '{}' }, plugin: p2 });
    const N = dataviewBlock({ dom, app: m2.app, code: LIB + `
const LB = lbPageLib(dv, app, 'annotate'); globalThis.__LB = LB;
if (await LB.reuseDom()) return;
const d = await LB.data.load(); globalThis.__data = d;
const box = dv.container.createEl('div', { cls: 'lba-annot' });
LB.keep(box, { versionOf: { abs: '${NOTE}' }, version: await LB.data.version({ abs: '${NOTE}' }) });` });
    await N.run();
    const nv = N.container.__lbView.version, dv2 = await globalThis.__LB.data.version();
    assert.equal(globalThis.__LB.data.adopt(dv2, globalThis.__data), true, '插件缓存照样推进');
    assert.equal(N.container.__lbView.version, nv, '批注块登记的 notes.json 版本不被 catalog 版本覆盖');
  }
  // dataUpdatedAt
  assert.equal(LB.dataUpdatedAt({ built_at: '2026-10-08T05:09:12+10:00' }), '2026-10-08T05:09:12+10:00');
  assert.equal(LB.dataUpdatedAt({}), null); assert.equal(LB.dataUpdatedAt(null), null);

  // unload：component.unload → host 摘掉
  A.component.unload();
  assert.equal(host.isConnected, false, 'unload 之后 host 被移除');

  // 残留 host 去重：容器后面先有一个同 role 的残留 host（上一个渲染器没卸干净）
  fresh();
  const B = dataviewBlock({ dom, app, code: PAGE });
  const stale = dom.document.createElement('div'); stale.className = 'lb-page-host'; stale.setAttribute('data-lb-role', 'catalog');
  const other = dom.document.createElement('div'); other.className = 'lb-page-host'; other.setAttribute('data-lb-role', 'chat');
  B.container.after(stale); stale.after(other);
  await B.run();
  assert.equal(B.qa('.lb-page-host').filter(h => h.dataset.lbRole === 'catalog').length, 1, '同 role 残留被去掉，只剩一个');
  assert.equal(stale.isConnected, false); assert.equal(other.isConnected, true, '别的 role 的不动');
  // 没有 container.after（老环境）：退回 container
  fresh();
  const C = dataviewBlock({ dom, app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await C.run();
  C.container.after = undefined;
  assert.equal(globalThis.__LB.mountHost('x'), C.container);
  // 用错的保护：同一次运行里调两次 mountHost → 还是同一个 host（不把刚画好的当残留删掉）；keep(host) 本身 → 重跑不报错
  fresh();
  const D2 = dataviewBlock({ dom, app, code: LIB + `
const LB = lbPageLib(dv, app, 'catalog');
if (await LB.reuseDom()) return;
const h1 = LB.mountHost('a'); h1.createEl('div', { cls: 'drawn', text: '画好了' });
const h2 = LB.mountHost('a');
globalThis.__same = h1 === h2;
LB.keep(h2, { version: await LB.data.version() });` });
  await D2.run();
  assert.equal(globalThis.__same, true, '第二次 mountHost 返回同一个 host');
  assert.equal(D2.qa('.drawn').length, 1, '画好的内容还在');
  await D2.rerun(); await D2.rerun();
  assert.equal(D2.container.nextSibling.classList.contains('lb-page-host'), true, 'keep(host) 之后重跑：host 还在容器后面');
  assert.equal(D2.qa('.drawn').length, 1);
  assert.equal(D2.container.nextSibling.parentNode, D2.section, 'host 没被挂进自己里面');
  console.log('PASS mountHost (sibling host, survives 3 reruns with focus, dedupe, unload, idempotent per run, keep(host) ok) + reuseDom version semantics (advance only on success, retry, updating lock, re-check after update so a version arriving mid-update is not dropped, 30s stale-lock fallback) + adopt (0 reads, written stat check, only catalog-versioned views) + dataUpdatedAt');
}

async function focusRestore() {
  fresh();
  const dom = makeDom();
  const { app } = makeApp({ files: { [DATA]: catalog(2) }, plugin: { settings: {} } });
  const A = dataviewBlock({ dom, app, code: PAGE });
  await A.run();
  const FK = 'lb:catalog:focus';
  const rec = () => JSON.parse(globalThis.__lbState[FK] || '{}');
  let input = A.q('.lbc-search');
  input.focus(); input.value = 'kafei'; input.setSelectionRange(2, 4); input.fire('select');
  const st = rec();
  assert.equal(st.focus, 'search'); assert.equal(st.selStart, 2); assert.equal(st.selEnd, 4); assert.ok(Date.now() - st.focusAt < 1000);
  // 焦点记录单放一个键：页面 saveState 用 state.save 整体覆盖页面状态，冲不掉它（复审：滚一下滚轮就把焦点记录清了）
  globalThis.__LB.state.save({ q: 'kafei', scrollTop: 120 });
  assert.equal(rec().focus, 'search', 'state.save 覆盖页面状态后焦点记录还在');
  assert.equal(JSON.parse(globalThis.__lbState['lb:catalog']).focus, undefined, '页面状态里不再混焦点字段');
  // 整页重建（section 重画 / CM 重建 widget：新容器 + 新 component）：3 秒内把焦点和选区还给新的搜索框
  await A.recreate();
  const next = A.q('.lbc-search');
  assert.notEqual(next, input, '整页重建了');
  assert.equal(dom.document.activeElement, next, '焦点还给新的搜索框');
  assert.deepEqual([next.selectionStart, next.selectionEnd], [2, 4], '选区也还原');
  // 她聚焦后停手 5 秒（focusAt 是 5 秒前），这时整页重建：失焦（摘掉）那一刻记 blurAt，照样还焦点
  globalThis.__lbState[FK] = JSON.stringify({ ...rec(), focusAt: Date.now() - 5000 });
  await A.recreate();
  assert.equal(dom.document.activeElement, A.q('.lbc-search'), '停手很久后才重建：从重建那一刻算 3 秒，照样还');
  // 残留的旧记录（重建时这个框并没有焦点）：超过 3 秒不抢
  A.q('.lbc-search').blur(); await tick(5);
  globalThis.__lbState[FK] = JSON.stringify({ focus: 'search', selStart: 0, selEnd: 0, focusAt: Date.now() - 5000, blurAt: Date.now() - 5000 });
  await A.recreate();
  assert.notEqual(dom.document.activeElement, A.q('.lbc-search'), '3 秒前的焦点不抢');
  // 她自己点走（焦点到页面外）：清掉记录
  const box = A.q('.lbc-search'); box.focus();
  const outside = dom.document.body.createEl('input'); outside.focus();
  await tick(5);
  assert.equal(rec().focus, null, '点到别处就不再还焦点');
  console.log('PASS trackFocus / restoreFocus: own sessionStorage key survives page state.save; focus + selection restored within 3s of a full rebuild (window counted from the blur at removal, so idle typing still restores); stale or user-moved focus not restored');
}

async function styleAndShared() {
  fresh();
  const dom = makeDom();
  const { app } = makeApp({ files: { [DATA]: catalog(1) } });
  const A = dataviewBlock({ dom, app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog'); globalThis.__LB2 = lbPageLib(dv, app, 'chat');` });
  await A.run(); await A.rerun();
  const head = dom.document.head;
  assert.equal(head.querySelectorAll('style').filter(s => s.getAttribute('id') === 'lb-shared').length, 1, 'lb-shared 只注入一份');
  const shared = dom.document.getElementById('lb-shared').textContent;
  for (const v of ['--lb-warn:', '--lb-warn-bg:', '--lb-warn-border:', '--lb-danger:', '--lb-danger-bg:', '--lb-ok:', '--lb-star:', '.lb-page-nav', '.lb-manage', '.lb-visually-hidden', 'focus-visible', '.lb-mobile-note', '.lb-busy-veil'])
    assert.ok(shared.includes(v), 'lb-shared 有 ' + v);
  assert.ok(!/\.lbc-star|\.lbc-badges/.test(shared), '.lbc-star / .lbc-badges 不进共用样式（留在目录自己的样式里）');
  const LB = globalThis.__LB;
  const s1 = LB.style('lbc-style', '.a{color:red}');
  const s2 = LB.style('lbc-style', '.a{color:red}');
  assert.equal(s1, s2); assert.equal(s1.parentNode, head, '挂在 head');
  LB.style('lbc-style', '.a{color:blue}');
  assert.equal(head.querySelectorAll('style').filter(s => s.getAttribute('id') === 'lbc-style').length, 1, '不重复叠加');
  assert.equal(s1.textContent, '.a{color:blue}', '文本不同才替换');
  const order = () => head.children.filter(s => s.tagName === 'STYLE').map(s => s.getAttribute('id'));
  assert.ok(order().indexOf('lb-shared') < order().indexOf('lbc-style'), 'lb-shared 在页面样式前面');

  // lb-shared 必须排在页面样式前面：热部署不重启时旧的 lbchat-style 先在 head 里（chat-view 原地复用），lb-shared 也要插到它前面
  const dom2 = makeDom();
  const old = dom2.document.head.createEl('style', { attr: { id: 'lbchat-style' } }); old.textContent = '@media (max-width:600px){.lb-page-nav{grid-column:1}}';
  dom2.document.head.createEl('style', { attr: { id: 'obsidian-snippet' } });
  const B = dataviewBlock({ dom: dom2, app, code: LIB + `lbPageLib(dv, app, 'chat');` });
  await B.run();
  const ids2 = dom2.document.head.children.map(s => s.getAttribute('id'));
  assert.ok(ids2.indexOf('lb-shared') < ids2.indexOf('lbchat-style'), 'lb-shared 插到已有的页面样式前面：' + ids2.join(','));
  // 已经在后面的 lb-shared（上一版注入的）：下一次初始化挪到页面样式前面
  dom2.document.head.append(dom2.document.getElementById('lb-shared'));
  await B.rerun();
  const ids3 = dom2.document.head.children.map(s => s.getAttribute('id'));
  assert.ok(ids3.indexOf('lb-shared') < ids3.indexOf('lbchat-style'), '挪回页面样式前面：' + ids3.join(','));
  assert.equal(ids3.filter(x => x === 'lb-shared').length, 1);

  // 弹出窗口：脚本在主窗口里 eval（document 是主窗口的），容器在弹出窗口的 document 里 → 样式、host 都进弹出窗口
  const mainDom = makeDom(), popDom = makeDom();
  const P = dataviewBlock({ dom: popDom, app, params: { document: mainDom.document }, code: LIB + `
const LB = lbPageLib(dv, app, 'catalog'); globalThis.__LB = LB;
LB.style('lbc-style', '.x{}');
globalThis.__host = LB.mountHost('pop');` });
  await P.run();
  assert.ok(popDom.document.getElementById('lb-shared') && popDom.document.getElementById('lbc-style'), '样式挂在弹出窗口的 head');
  assert.equal(mainDom.document.getElementById('lb-shared'), null, '主窗口 head 里没有');
  assert.equal(globalThis.__host.ownerDocument, popDom.document); assert.equal(P.container.nextSibling, globalThis.__host);
  console.log('PASS LB.style: one <style> per id in head, replaced only when text changes; lb-shared injected once with color vars + shared rules, always before page styles (also moved there on re-init); popout window gets its own styles / host');
}

async function mobileAndPages() {
  // 手机：插件不在 / 不全 → need 说只读并返回 null；ensure 直接抛只读、不去 enablePlugin
  fresh();
  const dom = makeDom();
  let made = makeApp({ files: { [DATA]: catalog(1) }, isMobile: true });
  let A = dataviewBlock({ dom, app: made.app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run();
  let LB = globalThis.__LB;
  assert.equal(LB.mobile, true);
  assert.equal(LB.MOBILE_ONLY_TEXT, '手机上只能看：导入、同步、问 AI、收藏要在电脑上用');
  assert.equal(LB.need('starNote'), null);
  assert.equal(A.notices.at(-1), LB.MOBILE_ONLY_TEXT, '手机上 need 提示只读那句');
  await assert.rejects(LB.ensure('starNote'), e => e.message === LB.MOBILE_ONLY_TEXT);
  assert.deepEqual(made.app.plugins.enabled, [], '手机上 ensure 不调 enablePlugin');
  const top = A.section.createEl('div', { cls: 'top' }); top.createEl('h1', { text: '目录' });
  LB.mobileNote(top); LB.mobileNote(top);
  assert.equal(top.querySelectorAll('.lb-mobile-note').length, 1, '只插一次');
  assert.equal(top.firstChild.classList.contains('lb-mobile-note'), true, '插在页首');
  // 电脑：插件没启用 / 版本对不上
  fresh();
  made = makeApp({ files: { [DATA]: catalog(1) } });
  A = dataviewBlock({ dom, app: made.app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run(); LB = globalThis.__LB;
  assert.equal(LB.need('starNote'), null);
  assert.match(A.notices.at(-1), /启用 Link Brain Actions/);
  LB.mobileNote(top); assert.equal(top.querySelectorAll('.lb-mobile-note').length, 1, '电脑上 mobileNote 什么都不做');
  made.app.plugins.plugins['link-brain-actions'] = { settings: {} };
  assert.equal(LB.need('starNote'), null); assert.match(A.notices.at(-1), /版本对不上/);
  const p = made.app.plugins.plugins['link-brain-actions']; p.starNote = async () => ({});
  assert.equal(LB.need('starNote'), p);
  // 插件忙：ensure 用插件统一的占用句
  fresh();
  const busyPlugin = { running: '同步收藏', busyText: () => '正在同步收藏（3/40），完成后再点，或在底部状态栏停止' };
  made = makeApp({ files: { [DATA]: catalog(1) }, plugin: busyPlugin });
  A = dataviewBlock({ dom, app: made.app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run();
  await assert.rejects(globalThis.__LB.ensure('openSyncLog'), e => e.message === busyPlugin.busyText());

  // openPage：不靠插件，按仓根那层 frontmatter 的 lb-page 找页，同一窗格 openLinkText
  fresh();
  made = makeApp({ files: { 'Lib/_archive/catalog-data.json': catalog(1), 'Lib/目录.md': '', 'Lib/问收藏.md': '', 'Lib/Web/问收藏副本.md': '', '问收藏.md': '' },
    frontmatter: { 'Lib/目录.md': { 'lb-page': 'catalog' }, 'Lib/问收藏.md': { 'lb-page': 'chat' }, 'Lib/Web/问收藏副本.md': { 'lb-page': 'chat' }, '问收藏.md': { 'lb-page': 'chat' } } });
  A = dataviewBlock({ dom, app: made.app, folder: 'Lib/Web', code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run(); LB = globalThis.__LB;
  assert.equal(LB.root, 'Lib');
  assert.equal(await LB.openPage('chat'), true);
  assert.deepEqual(made.workspace.opened.at(-1), ['Lib/问收藏.md', '', false], '只认仓根那一层的页');
  assert.equal(await LB.openPage('trash'), false);
  assert.match(A.notices.at(-1), /还没有这个页面/);
  console.log('PASS mobile (need → null + 只读那句, ensure throws without enablePlugin, mobileNote once), desktop need wording (启用 / 版本对不上), busy ensure uses busyText, openPage by lb-page frontmatter at repo root');
}

async function noticesAndConfirm() {
  // 有插件：say / progress / undoNotice / confirm 都转给插件
  fresh();
  const dom = makeDom();
  const notified = [], confirmed = [];
  const handles = [];
  const plugin = {
    notify(msg, o) { const h = { msg, o, hidden: false, messages: [msg], setMessage(m) { h.messages.push(m); }, hide() { h.hidden = true; } }; notified.push(h); handles.push(h); return h; },
    async confirm(o) { confirmed.push(o); return true; },
    menuOpen: false, showMenu(items, evt) { this.lastMenu = { items, evt }; this.menuOpen = true; return { items }; },
  };
  let made = makeApp({ files: { [DATA]: catalog(1) }, plugin });
  let A = dataviewBlock({ dom, app: made.app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run(); let LB = globalThis.__LB;
  LB.say('已保存', { kind: 'ok' });
  assert.deepEqual([notified[0].msg, notified[0].o.kind, notified[0].o.ms], ['已保存', 'ok', 3000], '成功默认 3 秒');
  LB.say('没删掉：EPERM', { kind: 'error' }); assert.equal(notified[1].o.ms, 8000, '失败默认 8 秒');
  const pr = LB.progress('正在导出…'); assert.equal(notified[2].o.ms, 0, '进行中常驻');
  pr.set('正在导出 3/10'); pr.hide(); assert.deepEqual(notified[2].messages, ['正在导出…', '正在导出 3/10']); assert.ok(notified[2].hidden);
  assert.equal(await LB.confirm({ title: '删除？', danger: true }), true); assert.equal(confirmed[0].danger, true);
  const items = [{ title: '收藏', onClick() {} }];
  assert.ok(LB.showMenu(items, { pageX: 1 })); assert.equal(plugin.lastMenu.items, items); assert.equal(LB.menuOpen(), true);
  plugin.menuOpen = false; assert.equal(LB.menuOpen(), false);
  let undone = 0;
  LB.undoNotice('已删除「标题」', () => { undone++; });
  const u = notified.at(-1); assert.equal(u.o.actions[0].label, '撤销'); assert.equal(u.o.ms, 6000);
  await u.o.actions[0].run(); assert.equal(undone, 1);
  LB.undoNotice('已清空', () => { throw new Error('磁盘满'); }, 8000);
  const u2 = notified.at(-1);
  await u2.o.actions[0].run(); await tick();
  assert.equal(notified.at(-1).msg, '没保存上，内容还在，可重试：磁盘满', '撤销失败照固定句式说原因');
  LB.undoNotice('第三条', () => {}); assert.ok(u2.hidden, '同一时刻只留最新一个撤销提示');

  // 没插件：直接 new Notice（Obsidian 1.14 的 addButton）；确认退回 window.confirm
  fresh();
  made = makeApp({ files: { [DATA]: catalog(1) } });
  A = dataviewBlock({ dom, app: made.app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run(); LB = globalThis.__LB;
  LB.say('已复制', { kind: 'ok' });
  assert.equal(A.noticeLog.at(-1).message, '已复制'); assert.equal(A.noticeLog.at(-1).timeout, 3000);
  let ran = 0;
  LB.say('同步没做完', { kind: 'error', actions: [{ label: '查看同步记录', run: () => { ran++; } }] });
  const n = A.noticeLog.at(-1);
  assert.deepEqual(n.buttons.map(b => b.label), ['查看同步记录']); assert.equal(n.timeout, 8000);
  n.buttons[0].click(); await tick();
  assert.equal(ran, 1); assert.ok(n.hidden, '点按钮先收起提示');
  const p2 = LB.progress('正在刷新目录'); p2.set('目录已刷新'); p2.hide();
  assert.deepEqual(A.noticeLog.at(-1).messages, ['正在刷新目录', '目录已刷新']); assert.equal(A.noticeLog.at(-1).timeout, 0); assert.ok(A.noticeLog.at(-1).hidden);
  let undo2 = 0; LB.undoNotice('已删除', () => { undo2++; });
  A.noticeLog.at(-1).buttons[0].click(); await tick(); assert.equal(undo2, 1);
  assert.equal(await LB.confirm({ title: '删掉？', body: '可以在回收站恢复' }), false, '假 window.confirm 默认 false');
  assert.deepEqual(A.confirms, ['删掉？\n\n可以在回收站恢复']);
  A.window.confirm = () => true; assert.equal(await LB.confirm({ title: '好吗' }), true);
  assert.equal(LB.showMenu([{ title: 'x' }], {}), null, '没插件：showMenu 返回 null'); assert.equal(LB.menuOpen(), false);
  // 单测里连 Notice 都没有：记进 globalThis.__lbNotices
  fresh();
  A = dataviewBlock({ dom, app: made.app, params: { Notice: undefined }, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run();
  globalThis.__LB.say('没有 Notice 也不炸', { kind: 'warn' });
  assert.deepEqual([globalThis.__lbNotices.at(-1).message, globalThis.__lbNotices.at(-1).kind, globalThis.__lbNotices.at(-1).ms], ['没有 Notice 也不炸', 'warn', 8000]);
  console.log('PASS say / progress / undoNotice / confirm / showMenu: plugin path (notify / confirm / showMenu, 3s ok / 8s error / 0 progress, undo failure wording, one undo at a time) and no-plugin path (Notice + addButton, window.confirm fallback, __lbNotices in bare tests)');
}

async function busyAndLeaf() {
  fresh();
  const dom = makeDom();
  const made = makeApp({ files: { [DATA]: catalog(1) } });
  const A = dataviewBlock({ dom, app: made.app, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run(); const LB = globalThis.__LB;
  const btn = A.section.createEl('button', { text: '导出' }); btn.createEl('span', { cls: 'icon' });
  const done = LB.busy(btn, '导出中…');
  assert.equal(btn.disabled, true); assert.equal(btn.textContent, '导出中…'); assert.ok(btn.classList.contains('is-busy'));
  done(); assert.equal(btn.disabled, false); assert.equal(btn.textContent, '导出'); assert.ok(btn.querySelector('.icon'), '原来的图标还在');
  const card = A.section.createEl('div', { cls: 'lbc-card' });
  const d2 = LB.busy(card, '正在收藏…');
  assert.equal(card.querySelector('.lb-busy-veil').textContent, '正在收藏…'); assert.ok(card.classList.contains('is-busy'));
  assert.equal(card.style.position, 'relative', '没定位的目标临时给 position:relative（遮罩只盖住它，不盖整页）');
  d2('已收藏', 10); assert.equal(card.querySelector('.lb-busy-veil').textContent, '已收藏');
  await tick(20); assert.equal(card.querySelector('.lb-busy-veil'), null); assert.ok(!card.classList.contains('is-busy'));
  assert.equal(card.style.position, '', '恢复原样');
  const abs = A.section.createEl('div'); abs.style.position = 'absolute';
  const d3 = LB.busy(abs, '…'); assert.equal(abs.style.position, 'absolute', '本来就定位的不动'); d3(); assert.equal(abs.style.position, 'absolute');
  // activeLeafHas：在文档里、看得见、在活动叶子的容器里
  const el = A.section.createEl('div', { cls: 'probe' });
  assert.equal(LB.activeLeafHas(el), false, '还没有活动叶子');
  A.activate();
  assert.equal(LB.activeLeafHas(el), true);
  made.workspace.setActiveLeaf({ view: { containerEl: dom.document.body.createEl('div') } });
  assert.equal(LB.activeLeafHas(el), false, '活动叶子是别的页');
  A.activate(); A.leaf.style.display = 'none';
  assert.equal(LB.activeLeafHas(el), false, '藏着（display:none）不算');
  A.leaf.style.display = ''; el.remove();
  assert.equal(LB.activeLeafHas(el), false, '摘下来了不算');
  console.log('PASS busy (button disabled + text, restored with icons; card veil, final text held then removed) + activeLeafHas (connected, shown, inside active leaf)');
}

// tests/_clock.cjs 经 params 注入的假时钟对 lb-page-lib 整个生效（复审：以前计时用 globalThis.performance、帧用 globalThis.rAF，只生效一半）
async function clockParams() {
  fresh();
  const dom = makeDom();
  const clock = makeClock();
  const { app } = makeApp({ files: { [DATA]: catalog(1) } });
  const A = dataviewBlock({ dom, app, params: clock.params, code: LIB + `globalThis.__LB = lbPageLib(dv, app, 'catalog');` });
  await A.run();
  const sc = A.host; sc.scrollTop = 0;
  let done = null;
  globalThis.__LB.restoreScroll(500).then(ok => { done = ok; });
  await clock.tick(10000);
  assert.equal(done, true, '假时钟推进 10 秒：恢复滚动跑完了');
  assert.equal(clock.pending(), 0, '没有残留的定时器 / 帧');
  sc.scrollTop = 0; await clock.tick(2000);
  assert.equal(sc.scrollTop, 0, '跑完之后不再把滚动拽回 500');
  console.log('PASS clock params: restoreScroll timing + frames both follow tests/_clock.cjs');
}

(async () => {
  await hostAndVersion();
  await focusRestore();
  await clockParams();
  await styleAndShared();
  await mobileAndPages();
  await noticesAndConfirm();
  await busyAndLeaf();
})().catch(e => { console.error(e); process.exit(1); });

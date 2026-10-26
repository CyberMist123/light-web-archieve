// 批次 D · L5 note-tools.js：F1-b 恢复 / 撤销 / 从快照找回；F1-d 改坏笔记就地提示 + JS noteDamage 与 Python diagnose 共用样本一致；
// F3-a 顶栏「导出」注入（幂等、只对归档笔记）+ 导出菜单 + 进行中防连点 + 成功 / 降级 / 失败三种提示。不起 Python（runPy 是假的）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), os = require('os');
const { ROOT, makeDom, makeWorkspace, makeMetadataCache } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const DIR = 'obsidian-plugins/link-brain-actions';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const factory = require(path.join(ROOT, DIR, 'note-tools.js'));

function setup({ runPy, files = {}, root = '' } = {}) {
  const dom = makeDom(), D = dom.document;
  const notices = [];
  const obs = makeObsidian(D, { notices });
  const ws = makeWorkspace();
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-nt-'));
  const pre = root ? root + '/' : '';
  const note = { path: pre + 'Web/Xiaohongshu/做饭.md', basename: '做饭' };
  const bare = { path: pre + 'Web/Xiaohongshu/没id.md', basename: '没id' };
  const other = { path: pre + 'Web/随手记.md', basename: '随手记' };
  const fm = { [note.path]: { link_brain: { item_id: 'xhs-abc' } } };
  const calls = [], cmds = {}, events = {}, pps = [];
  const contents = { [note.path]: files.note || '', [bare.path]: files.bare || '' };
  const plugin = {
    lbRoot: root, lbPath: p => (root ? `${root}/${p}` : p),
    settings: {},
    app: { workspace: ws, metadataCache: makeMetadataCache(fm),
      vault: { adapter: { getBasePath: () => base }, cachedRead: async f => contents[f.path] || '', getAbstractFileByPath: p => [note, bare, other].find(f => f.path === p) || null } },
    registerEvent() {}, register() {}, registerDomEvent(t, ty, fn, o) { t.addEventListener(ty, fn, o); },
    registerMarkdownPostProcessor(fn) { pps.push(fn); },
    addCommand(c) { cmds[c.id] = c; },
    notify(msg, opts = {}) { const n = { msg, opts, hidden: false, hide() { n.hidden = true; } }; notices.push(n); return n; },
    runPy: async (args, opts) => { calls.push({ args, opts }); return runPy ? runPy(args, opts) : { json: { ok: true } }; },
  };
  ws.on = (name, fn) => { events[name] = fn; return { name, fn, e: ws }; };
  const shell = { opened: [], shown: [], openPath(p) { this.opened.push(p); }, showItemInFolder(p) { this.shown.push(p); } };
  const inst = factory(obs, plugin, { electron: { shell } });
  inst.attach();
  return { dom, D, obs, ws, plugin, inst, note, bare, other, calls, cmds, events, pps, notices, base, contents, shell };
}

(async () => {
  // ── itemOf ──
  {
    const S = setup({ root: 'LB' });
    assert.deepEqual(S.inst.itemOf(S.note), { itemId: 'xhs-abc', file: S.note, rel: 'Web/Xiaohongshu/做饭.md' });
    assert.deepEqual(S.inst.itemOf(S.bare), { itemId: null, file: S.bare, rel: 'Web/Xiaohongshu/没id.md' });
    assert.equal(S.inst.itemOf(S.other), null);
  }
  // ── file-menu：普通笔记不加项；缺 item_id 但在可见目录照样加；有快照才出「从快照找回…」 ──
  {
    const S = setup();
    const m1 = new S.obs.Menu(); S.events['file-menu'](m1, S.other); assert.equal(m1.items.length, 0);
    const m2 = new S.obs.Menu(); S.events['file-menu'](m2, S.bare);
    assert.deepEqual(m2.items.filter(i => !i.separator).map(i => i.title), ['恢复这篇（按存档重写，可撤销）']);
    const m3 = new S.obs.Menu(); S.events['file-menu'](m3, S.note);
    assert.ok(!m3.find('从快照找回…'));
    assert.ok(m3.find('导出 PDF（和页面一样）') && m3.find('导出压缩包（这一篇的全部本地资料）'));
    fs.mkdirSync(path.join(S.base, '_archive/xiaohongshu/abc/history'), { recursive: true });
    fs.writeFileSync(path.join(S.base, '_archive/xiaohongshu/abc/history/visible-20261008-153000-restore.txt'), 'x');
    const m4 = new S.obs.Menu(); S.events['file-menu'](m4, S.note); assert.ok(m4.find('从快照找回…'));
    // 有视频：压缩包标题带大小
    const obj = path.join(S.base, '_archive/xiaohongshu/abc');
    fs.mkdirSync(path.join(obj, 'raw/v0001/assets'), { recursive: true });
    fs.writeFileSync(path.join(obj, 'meta.json'), JSON.stringify({ current_version: 1 }));
    fs.writeFileSync(path.join(obj, 'raw/v0001/manifest.json'), JSON.stringify({ media: [{ role: 'video', file: 'assets/v.mp4', download_status: 'ok' }] }));
    fs.writeFileSync(path.join(obj, 'raw/v0001/assets/v.mp4'), Buffer.alloc(3 * 1024 * 1024));
    const m5 = new S.obs.Menu(); S.events['file-menu'](m5, S.note);
    assert.ok(m5.find('导出压缩包（这一篇的全部本地资料） · 含视频 3 MB'));
  }
  // ── 恢复：先存盘切阅读视图；runPy 参数；成功带「撤销」；撤销发同名快照；连点只发一次 ──
  {
    let release;
    const S = setup({ runPy: async args => {
      if (args.includes('--undo')) return { json: { ok: true } };
      await new Promise(r => { release = r; });
      return { json: { ok: true, message: '已按存档恢复「做饭」', snapshot: 'visible-20261008-153000-restore.txt' } };
    } });
    const saved = [];
    const leaf = { view: { file: S.note, getMode: () => 'source', save: async () => saved.push(1), getViewType: () => 'markdown' },
      getViewState: () => ({ type: 'markdown', state: { mode: 'source', file: S.note.path } }), async setViewState(s) { leaf.vs = s; } };
    S.ws.leaves.push(leaf);
    const p1 = S.inst.restore(S.note);
    await tick();
    await S.inst.restore(S.note);
    assert.equal(S.notices.at(-1).msg, '正在恢复这篇，稍等');
    release(); await p1;
    assert.equal(saved.length, 1); assert.equal(leaf.vs.state.mode, 'preview');
    assert.equal(S.calls.length, 1);
    assert.deepEqual(S.calls[0].args, ['-m', 'link_brain', 'restore', 'xhs-abc', '--path', 'Web/Xiaohongshu/做饭.md', '--json']);
    const n = S.notices.at(-1);
    assert.equal(n.msg, '已按存档恢复「做饭」'); assert.equal(n.opts.actions[0].label, '撤销');
    await n.opts.actions[0].run();
    assert.deepEqual(S.calls.at(-1).args.slice(3), ['xhs-abc', '--path', 'Web/Xiaohongshu/做饭.md', '--undo', '--snapshot', 'visible-20261008-153000-restore.txt', '--json']);
    assert.equal(S.notices.at(-1).msg, '已撤销：回到恢复前那一版');
  }
  // ── 恢复失败：「没恢复：」开头，没有按钮；缺 item_id 不传 id ──
  {
    const S = setup({ runPy: async () => ({ json: { ok: false, message: '找不到这条收藏' } }) });
    await S.inst.restore(S.bare);
    assert.deepEqual(S.calls[0].args.slice(3), ['--path', 'Web/Xiaohongshu/没id.md', '--json']);
    const n = S.notices.at(-1);
    assert.ok(n.msg.startsWith('没恢复：找不到这条收藏')); assert.ok(!n.opts.actions);
  }
  // ── 从快照找回：SuggestModal 每份写清是什么、找回怎么做；选中发 --from-snapshot（1026：坏的不原样写回），成功带「撤销」 ──
  {
    const S = setup({ runPy: async args => args.includes('--list')
      ? { json: { ok: true, snapshots: [
        { name: 'visible-20261008-153000-restore.txt', ts: '2026-10-08T15:30:00', reason: 'restore', bytes: 43008, broken: true,
          summary: '页面结构坏了（两栏正文块被换行拆开了），存档 v1 那一版的排版，1 条留言', how: '找回会只取它里面你写的东西、按现在的存档重新排版（不会把坏的页面写回来）' },
        { name: 'visible-20261008-152000-render.txt', ts: '2026-10-08T15:20:00', reason: 'render', bytes: 40960 }] } }
      : args.includes('--from-snapshot') ? { json: { ok: true, mode: 'rebuilt', snapshot: 'visible-20261008-160000-restore.txt', message: '已从快照找回「做饭」：…按存档重新排版' } }
      : { json: { ok: true } } });
    const m = await S.inst.pickSnapshot(S.note);
    const list = m.getSuggestions('');
    const el = S.D.createElement('div'); m.renderSuggestion(list[0], el);
    assert.equal(el.querySelector('.lb-snap-title').textContent, '10-08 15:30 · 恢复前 · 42 KB');
    const desc = el.querySelector('.lb-snap-desc');
    assert.ok(desc.classList.contains('is-broken') && desc.textContent.includes('页面结构坏了') && desc.textContent.includes('不会把坏的页面写回来'));
    const el2 = S.D.createElement('div'); m.renderSuggestion(list[1], el2);
    assert.equal(el2.textContent, '10-08 15:20 · 重渲前 · 40 KB', '老后端没给说明：只有一行');
    assert.equal(m.getSuggestions('坏了').length, 1, '说明也能搜');
    m.onChooseSuggestion(list[0]); await tick(); await tick();
    assert.deepEqual(S.calls.at(-1).args.slice(3), ['xhs-abc', '--path', 'Web/Xiaohongshu/做饭.md', '--from-snapshot', 'visible-20261008-153000-restore.txt', '--json']);
    const n = S.notices.at(-1);
    assert.ok(n.msg.startsWith('已从快照找回') && n.opts.actions[0].label === '撤销');
    await n.opts.actions[0].run();
    assert.deepEqual(S.calls.at(-1).args.slice(3), ['xhs-abc', '--path', 'Web/Xiaohongshu/做饭.md', '--undo', '--snapshot', 'visible-20261008-160000-restore.txt', '--json'], '撤销回到找回前那一版');
  }
  // ── 命令：只对归档笔记 ──
  {
    const S = setup();
    S.ws.activeFile = S.other; assert.equal(S.cmds['restore-note'].checkCallback(true), false);
    S.ws.activeFile = S.bare; assert.equal(S.cmds['restore-note'].checkCallback(true), true);
    assert.equal(S.cmds['export-note-pdf'].checkCallback(true), false);
    S.ws.activeFile = S.note; assert.equal(S.cmds['export-note-zip'].checkCallback(true), true);
    for (const id of ['restore-note', 'restore-note-undo', 'restore-note-snapshot', 'export-note-pdf', 'export-note-zip']) assert.ok(S.cmds[id], id);
  }
  // ── F1-d：JS noteDamage 与 Python 共用样本一致 ──
  {
    const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'note_damage_cases.json'), 'utf8'));
    const apply = (t, patch) => {
      for (const op of patch) {
        if (op[0] === 'replace') { const i = t.indexOf(op[1]); if (i >= 0) t = t.slice(0, i) + op[2] + t.slice(i + op[1].length); }
        else if (op[0] === 'cut') { const s = t.indexOf(op[1]); const e = s >= 0 ? t.indexOf(op[2], s) : -1; if (s >= 0 && e >= 0) t = t.slice(0, s) + t.slice(e + op[2].length); }
      }
      return t;
    };
    assert.ok(data.cases.length >= 9);
    for (const c of data.cases) assert.deepEqual(factory.noteDamage(apply(data.base, c.patch)), c.expect, c.name);
  }
  // ── F1-d：打开坏笔记出一条带「恢复」的提示；同一路径第二次不再弹；好笔记不弹 ──
  {
    const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'note_damage_cases.json'), 'utf8'));
    const S = setup({ files: { note: data.base.replace('<!-- link-brain:content:end -->', '') } });
    S.events['file-open'](S.note); await tick();
    const n = S.notices.at(-1);
    assert.ok(n.msg.startsWith('这篇的页面结构被改坏了（正文的受管标记被删了）'));
    assert.equal(n.opts.actions[0].label, '恢复');
    const before = S.notices.length;
    S.events['file-open'](S.note); await tick();
    assert.equal(S.notices.length, before);
    S.contents[S.note.path] = data.base;
    S.events['file-open'](S.note); await tick();
    assert.equal(S.notices.length, before);
    // 从源码切回阅读视图时再查
    S.contents[S.note.path] = data.base.replace('annotate-view.js', 'x.js');
    const lf = { view: { file: S.note, getMode: () => 'source' } };
    S.ws.leaves.push(lf); lf.view.getViewType = () => 'markdown';
    S.events['layout-change'](); lf.view.getMode = () => 'preview'; S.events['layout-change'](); await tick();
    assert.ok(S.notices.at(-1).msg.includes('底部的批注块没了'));
  }
  // ── 1010：顶栏那一行 =「← 目录　原文　机读版」（post-processor 注入「← 目录」、去掉「·」；幂等；只对归档笔记；不再有「导出 ▾」）──
  {
    const opened = [];
    const S = setup();
    S.plugin.openLibraryPage = async (role, leaf) => { opened.push([role, leaf]); };
    const mk = (withOldButton = false) => {
      const el = S.D.createElement('div');
      const c = el.createEl('div', { cls: 'callout', attr: { 'data-callout': 'lb-topbar' } });
      c.createEl('div', { cls: 'callout-title' });
      const content = c.createEl('div', { cls: 'callout-content' });
      const p = content.createEl('p');
      p.createEl('a', { cls: 'external-link', text: '原文' });
      p.appendChild(S.D.createTextNode(' · '));
      p.createEl('a', { cls: 'internal-link', text: '机读版' });
      if (withOldButton) content.createEl('span', { cls: 'lb-topbar-tools' }).createEl('button', { cls: 'lb-topbar-export', text: '导出' });
      return el;
    };
    const el = mk(true);
    S.pps[0](el, { sourcePath: S.note.path, frontmatter: { link_brain: { item_id: 'xhs-abc' } } });
    S.pps[0](el, { sourcePath: S.note.path, frontmatter: { link_brain: { item_id: 'xhs-abc' } } });
    const p = el.querySelector('.callout-content p');
    assert.ok(p.classList.contains('lb-topbar-row'));
    assert.deepEqual(p.children.map(x => x.textContent), ['← 目录', '原文', '机读版'], '一行三样：← 目录 · 原文 · 机读版（顺序）');
    assert.ok(!p.textContent.includes('·'), '中间的「·」去掉了（间距交给样式）');
    assert.equal(el.querySelectorAll('.lb-topbar-back').length, 1, '幂等：再跑一次不重复插');
    assert.equal(el.querySelectorAll('.lb-topbar-export, .lb-topbar-tools').length, 0, '老版本留下的「导出 ▾」摘掉了');
    const back = p.children[0];
    assert.equal(back.tagName, 'A', '是一个链接样的字，不是按钮（不吃主题的按钮框）');
    assert.equal(back.getAttribute('tabindex'), '0');
    const el2 = mk(); S.pps[0](el2, { sourcePath: S.other.path, frontmatter: {} });
    assert.equal(el2.querySelectorAll('.lb-topbar-back').length, 0, '不是归档笔记：不动');
    // 点「← 目录」：在笔记自己那一格打开目录页（目录页自己记着滚动和筛选）；Ctrl 点开新标签
    const leaf = { view: { containerEl: el, getViewType: () => 'markdown' } };
    S.ws.leaves.push(leaf);
    let stopped = 0;
    for (const fn of back.listeners.click) fn({ preventDefault() {}, stopPropagation() { stopped++; } });
    await tick();
    assert.deepEqual(opened.at(-1), ['catalog', leaf]);
    assert.equal(stopped, 1);
    for (const fn of back.listeners.click) fn({ ctrlKey: true, preventDefault() {}, stopPropagation() {} });
    await tick();
    assert.equal(opened.at(-1)[0], 'catalog'); assert.notEqual(opened.at(-1)[1], leaf); assert.deepEqual(S.ws.gotLeaves.at(-1), 'tab');
    for (const fn of back.listeners.keydown) fn({ key: 'Enter', preventDefault() {} });
    await tick();
    assert.deepEqual(opened.at(-1), ['catalog', leaf], '键盘 Enter 也行');
  }
  // ── 1010：导出在 ⋮ 菜单里是「导出 ▸」子菜单（Obsidian 1.14 有 setSubmenu）——PDF / 压缩包 ──
  {
    const S = setup();
    const proto = Object.getPrototypeOf(new S.obs.Menu().addItem(() => {}).items[0]);
    proto.setSubmenu = function () { this.submenu = this.submenu || new S.obs.Menu(); return this.submenu; };   // 照 1.14.4 MenuItem.setSubmenu（返回一个 Menu）
    try {
      const m = new S.obs.Menu(); S.events['file-menu'](m, S.note, 'more-options');
      const ex = m.find('导出');
      assert.ok(ex && ex.submenu, '⋮ 菜单里一项「导出」，带子菜单');
      assert.deepEqual(ex.submenu.items.map(i => i.title), ['PDF（和页面一样）', '压缩包（这一篇的全部本地资料）']);
      assert.ok(!m.find('导出 PDF（和页面一样）'), '不再平铺两项');
      assert.ok(m.find('恢复这篇（按存档重写，可撤销）'));
      const m2 = new S.obs.Menu(); S.events['file-menu'](m2, S.bare, 'more-options');
      assert.ok(!m2.find('导出'), '没有 item_id 的不给导出');
    } finally { delete proto.setSubmenu; }
  }
  // ── F3：进行中防连点；成功 / 降级 / 失败提示 ──
  {
    let release;
    const S = setup({ runPy: async args => { await new Promise(r => { release = r; }); return { json: { ok: true, message: '已导出 PDF（6 页）', path: 'D:/x/收藏导出/做饭_20261009.pdf', fallback: '' } }; } });
    const btn = S.D.createElement('button'); btn.textContent = '导出';
    const p = S.inst.exportPdf(S.note, btn);
    await tick();
    assert.equal(btn.getAttribute('aria-busy'), 'true'); assert.equal(btn.textContent, '导出中…');
    await S.inst.exportPdf(S.note, btn);
    assert.equal(S.notices.at(-1).msg, '正在导出，稍等');
    release(); await p;
    assert.equal(S.calls.length, 1);
    assert.deepEqual(S.calls[0].args, ['-m', 'link_brain', 'export-note', 'xhs-abc', '--pdf', '--json', '--stdin']);
    assert.equal(btn.textContent, '导出'); assert.equal(btn.getAttribute('aria-busy'), null);
    const n = S.notices.at(-1);
    assert.equal(n.msg, '已导出 PDF（6 页）：做饭_20261009.pdf');
    assert.deepEqual(n.opts.actions.map(a => a.label), ['打开', '在文件夹中显示']);
    n.opts.actions[0].run(); assert.deepEqual(S.shell.opened, ['D:/x/收藏导出/做饭_20261009.pdf']);
    assert.ok(S.notices.some(x => x.opts.ms === 0 && x.hidden), '进度提示常驻、完成后收起');
  }
  {
    const S = setup({ runPy: async () => ({ json: { ok: true, fallback: 'html', path: 'D:/x/a.html', message: 'x' } }) });
    await S.inst.exportPdf(S.note);
    const n = S.notices.at(-1);
    assert.equal(n.msg, '没找到 Edge / Chrome：已生成网页版，打开后按 Ctrl+P 另存为 PDF'); assert.equal(n.opts.actions[0].label, '打开网页版');
  }
  {
    const S = setup({ runPy: async () => { throw Object.assign(new Error('炸了'), { result: { json: null } }); } });
    await S.inst.exportZip(S.note);
    assert.ok(S.notices.at(-1).msg.startsWith('没导出：炸了'));
  }
  {
    const S = setup({ runPy: async () => ({ json: { ok: true, message: '已打包：2 张原图（1 MB）', path: 'D:/x/a.zip' } }) });
    await S.inst.exportZip(S.note);
    assert.equal(S.notices.at(-1).msg, '已打包：2 张原图（1 MB）：a.zip');
    assert.deepEqual(S.calls[0].args.slice(3), ['xhs-abc', '--zip', '--json']);
  }
  console.log('PASS note-tools');
})().catch(e => { console.error(e); process.exit(1); });

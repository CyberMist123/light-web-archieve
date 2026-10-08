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
  // ── 从快照找回：SuggestModal 文案；选中发 --undo --snapshot ──
  {
    const S = setup({ runPy: async args => args.includes('--list')
      ? { json: { ok: true, snapshots: [{ name: 'visible-20261008-153000-restore.txt', ts: '2026-10-08T15:30:00', reason: 'restore', bytes: 43008 }] } }
      : { json: { ok: true } } });
    const m = await S.inst.pickSnapshot(S.note);
    const list = m.getSuggestions('');
    const el = S.D.createElement('div'); m.renderSuggestion(list[0], el);
    assert.equal(el.textContent, '10-08 15:30 · 恢复前 · 42 KB');
    m.onChooseSuggestion(list[0]); await tick();
    assert.ok(S.calls.at(-1).args.includes('--snapshot'));
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
  // ── F3-a：post-processor 注入（幂等；只对归档笔记）──
  {
    const S = setup();
    const mk = () => {
      const el = S.D.createElement('div');
      const c = el.createEl('div', { cls: 'callout', attr: { 'data-callout': 'lb-topbar' } });
      c.createEl('div', { cls: 'callout-title' });
      c.createEl('div', { cls: 'callout-content' }).createEl('p', { text: '原文' });
      return el;
    };
    const el = mk();
    S.pps[0](el, { sourcePath: S.note.path, frontmatter: { link_brain: { item_id: 'xhs-abc' } } });
    S.pps[0](el, { sourcePath: S.note.path, frontmatter: { link_brain: { item_id: 'xhs-abc' } } });
    const btns = el.querySelectorAll('.lb-topbar-export');
    assert.equal(btns.length, 1); assert.equal(btns[0].textContent, '导出'); assert.equal(btns[0].getAttribute('aria-haspopup'), 'menu');
    const el2 = mk(); S.pps[0](el2, { sourcePath: S.other.path, frontmatter: {} });
    assert.equal(el2.querySelectorAll('.lb-topbar-export').length, 0);
    // 点了出菜单两项
    btns[0].click?.() ?? btns[0].dispatchEvent({ type: 'click' });
    const menu = S.obs.Menu.open;
    assert.ok(menu, '出菜单');
    assert.deepEqual(menu.items.map(i => i.title), ['导出 PDF（和页面一样）', '导出压缩包（这一篇的全部本地资料）']);
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

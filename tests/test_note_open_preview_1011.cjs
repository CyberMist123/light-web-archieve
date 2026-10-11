// 1011 她：打开一篇先露出原始 Markdown 再变正常页。根因之一：目录 / 链接 / 同步记录走 openLinkText(不带 mode)，按默认（实时预览）
// 先渲一遍，插件 file-open 才切阅读视图。修：main.js patchOpenFile 在 WorkspaceLeaf.prototype.openFile 这一层给归档笔记补 mode:'preview'。
// 这里：归档笔记（frontmatter.link_brain.item_id）不带 mode → 带上 preview、别的 openState（eState 跳行）照留；调用方给了 mode 的照它；
// 普通笔记 / 非 md / 读不到属性缓存的不动（fail-open）；卸载还原原型；别的插件后来又包了一层时，卸载后我们这层变直通、不拆别人的链。
// 首帧样子（cssclasses 挂上之前）由 tests/ui/note_first_frame_ui.cjs 管。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), vm = require('vm');
const { makeDom, makeWorkspace, ROOT } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const PLUGIN_DIR = 'obsidian-plugins/link-brain-actions';
const dom = makeDom();
const obs = makeObsidian(dom.document, {});
const calls = [];
class WorkspaceLeaf { async openFile(file, openState) { calls.push({ leaf: this, path: file && file.path, openState: openState === undefined ? undefined : JSON.parse(JSON.stringify(openState)) }); return 'opened'; } }
const ORIGINAL = WorkspaceLeaf.prototype.openFile;
obs.WorkspaceLeaf = WorkspaceLeaf;
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, console, Buffer, document: dom.document,
  require: n => (n === 'obsidian' ? obs : n === 'child_process' ? { spawn() { throw new Error('不许起进程'); } } : require(n)) };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8'), context);
const Plugin = context.module.exports;

const fm = {
  'Web/Xiaohongshu/合成.md': { cssclasses: ['link-brain', 'xhs-note'], link_brain: { item_id: 'xhs-synth0001' } },
  '随手记.md': { tags: ['x'] },
};
let cacheThrows = false;
const app = { workspace: makeWorkspace(), vault: { adapter: {} },
  metadataCache: { getFileCache(f) { if (cacheThrows) throw new Error('缓存坏了'); return fm[f.path] ? { frontmatter: fm[f.path] } : null; } } };
const p = new Plugin(app, { id: 'link-brain-actions', dir: PLUGIN_DIR, version: 'test' });
const unloads = [];
p.register = fn => unloads.push(fn);
const file = pth => new obs.TFile(pth);

(async () => {
  assert.equal(p.patchOpenFile(), true, '有 WorkspaceLeaf 就装上');
  const leaf = new WorkspaceLeaf();
  const last = () => calls[calls.length - 1];

  assert.equal(await leaf.openFile(file('Web/Xiaohongshu/合成.md')), 'opened', '返回值照原样');
  assert.deepEqual(last().openState, { state: { mode: 'preview' } }, '归档笔记不带 mode → 第一下就是阅读视图');
  assert.equal(last().leaf, leaf, 'this 还是那个 leaf');

  await leaf.openFile(file('Web/Xiaohongshu/合成.md'), { eState: { line: 4 } });
  assert.deepEqual(last().openState, { eState: { line: 4 }, state: { mode: 'preview' } }, '跳行（索引 / 目录「第几行」）照留');

  await leaf.openFile(file('Web/Xiaohongshu/合成.md'), { active: false, state: { mode: 'source', source: false } });
  assert.deepEqual(last().openState, { active: false, state: { mode: 'source', source: false } }, '调用方自己给了 mode 的照它的');

  await leaf.openFile(file('随手记.md'));
  assert.equal(last().openState, undefined, '普通笔记不动（她自己的笔记照她的默认视图）');
  await leaf.openFile(file('附件/合成.pdf'));
  assert.equal(last().openState, undefined, '非 md 不动');

  cacheThrows = true;
  await leaf.openFile(file('Web/Xiaohongshu/合成.md'), { eState: { line: 1 } });
  assert.deepEqual(last().openState, { eState: { line: 1 } }, '读属性缓存出错：照原样打开（fail-open）');
  cacheThrows = false;

  // 别的插件后来又包了一层：卸载时不拆它的链，我们这层变直通
  const ours = WorkspaceLeaf.prototype.openFile;
  const theirs = function (f, s) { return ours.call(this, f, s); };
  WorkspaceLeaf.prototype.openFile = theirs;
  unloads.forEach(fn => fn());
  assert.equal(WorkspaceLeaf.prototype.openFile, theirs, '别人的那层留着');
  await leaf.openFile(file('Web/Xiaohongshu/合成.md'));
  assert.equal(last().openState, undefined, '卸载后我们这层不再改 openState');

  // 没人再包：卸载直接还原原型
  WorkspaceLeaf.prototype.openFile = ORIGINAL;
  unloads.length = 0;
  p.patchOpenFile();
  assert.notEqual(WorkspaceLeaf.prototype.openFile, ORIGINAL);
  unloads.forEach(fn => fn());
  assert.equal(WorkspaceLeaf.prototype.openFile, ORIGINAL, '卸载还原原型');

  // 没有 WorkspaceLeaf（很老的 Obsidian / 假宿主）：不装、不报错
  const saved = obs.WorkspaceLeaf; obs.WorkspaceLeaf = undefined;
  assert.equal(p.patchOpenFile(), false);
  obs.WorkspaceLeaf = saved;

  // onload 里真的调了 patchOpenFile（源码钉一下，免得以后挪丢）
  const src = fs.readFileSync(path.join(ROOT, PLUGIN_DIR, 'main.js'), 'utf8');
  assert.ok(/this\.patchOpenFile\(\);\s*\n\s*if \(this\.app\.workspace\?\.on\) this\.registerEvent\(this\.app\.workspace\.on\('file-open'/.test(src), 'onload 先装 patchOpenFile，file-open 切视图留作兜底');
  console.log('PASS note open preview (1011): archived notes open straight in reading view via WorkspaceLeaf.openFile (mode preview added, eState kept, explicit mode respected, plain notes / non-md / cache errors untouched), unload restores or turns pass-through');
})().catch(e => { console.error(e); process.exit(1); });

// 1104 作者：开着两栏时，从目录点开的笔记放到另一栏，目录自己不跳走；左右不固定（看目录在哪边）。只有目录一栏 → 和原来一样本栏打开。
// 断言：LB.otherPane() 找的是同一窗口里、别的分栏当前显示着的那一栏（同一组的别的标签不算；几栏取最近用过的）；
// 目录的 openItem / openVaultFile 有另一栏就在那里打开（不起 openLinkText、目录不标 leaving），没有就照旧。
'use strict';
const fs = require('fs'), assert = require('assert/strict');

const lib = fs.readFileSync('link_brain/assets/lb-page-lib.js', 'utf8');
const view = fs.readFileSync('link_brain/assets/catalog-view.js', 'utf8');
const fnSrc = name => {
  const at = view.indexOf('\nfunction ' + name + '(') + 1;
  const asyncAt = view.indexOf('\nasync function ' + name + '(') + 1;
  const start = at > 0 ? at : asyncAt;
  assert.ok(start > 0, '找不到 ' + name);
  let depth = 0, i = view.indexOf('{', start);
  for (; i < view.length; i++) { if (view[i] === '{') depth++; else if (view[i] === '}' && --depth === 0) break; }
  return view.slice(start, i + 1);
};

const doc = {};
const el = name => ({ name, ownerDocument: doc, contains: x => x === name + ':page' });
const leaf = (name, parent, activeTime) => ({ name, parent, activeTime, view: { containerEl: el(name) }, opened: [], openFile(f, st) { this.opened.push([f.path, st]); return Promise.resolve(); } });

function world(leaves) {
  const opened = [];
  const app = {
    vault: { getAbstractFileByPath: p => ({ path: p }) },
    workspace: {
      getLeavesOfType: () => leaves,
      iterateRootLeaves: cb => leaves.forEach(cb),
      openLinkText: (p, s, newTab) => opened.push([p, newTab]),
      getLeaf: () => leaves[0],
    },
  };
  const LB = new Function('dv', 'app', lib + ';return lbPageLib(dv,app,"catalog")')({ container: 'cat:page', current: () => ({ file: { folder: '' } }) }, app);
  const env = { leaving: false, saved: 0, said: [] };
  const make = new Function('app', 'LB', 'lbPath', 'env', `
    let selectMode = false; const toggleSelect = () => {};
    const saveState = () => { env.saved++; };
    let leaving = false;
    Object.defineProperty(env, 'leaving', { get: () => leaving });
    ${fnSrc('openInOtherPane')}
    ${fnSrc('openItem')}
    ${fnSrc('openVaultFile')}
    return { openItem, openVaultFile };`);
  const fns = make(app, { ...LB, say: (m) => env.said.push(m) }, x => x, env);
  return { app, LB, opened, env, ...fns };
}

(async () => {
  // 只有目录一栏：和原来一样，本栏打开
  {
    const g1 = {};
    const cat = leaf('cat', g1, 5);
    const w = world([cat]);
    assert.equal(w.LB.otherPane(), null);
    w.openItem({ note: 'a.md' });
    assert.deepEqual(w.opened, [['a.md', false]]);
    assert.equal(w.env.leaving, true, '本栏打开：目录要走');
  }
  // 两栏，目录在左：在右边那栏打开；目录不走、不起 openLinkText
  {
    const gL = {}, gR = {};
    const cat = leaf('cat', gL, 5), right = leaf('right', gR, 9);
    const w = world([cat, right]);
    assert.equal(w.LB.otherPane(), right);
    w.openItem({ note: 'b.md' });
    await Promise.resolve();
    assert.deepEqual(w.opened, [], '不走 openLinkText');
    assert.equal(right.opened[0][0], 'b.md');
    assert.equal(right.opened[0][1].active, false, '焦点留在目录，下一次点还是开在那一栏');
    assert.equal(w.env.leaving, false, '目录留在原地');
    // Ctrl：照 Obsidian 习惯开新标签
    w.openItem({ note: 'c.md' }, { ctrlKey: true });
    assert.deepEqual(w.opened, [['c.md', true]]);
    // 索引 / 草稿文件：也在另一栏，带上行号
    await w.openVaultFile('索引.md', 12);
    assert.deepEqual(right.opened[1], ['索引.md', { eState: { line: 11 }, active: false }]);
  }
  // 左右不固定：目录在右边 → 开在左边那栏
  {
    const gL = {}, gR = {};
    const left = leaf('left', gL, 3), cat = leaf('cat', gR, 7);
    const w = world([left, cat]);
    assert.equal(w.LB.otherPane(), left);
  }
  // 同一组里的别的标签不算「另一栏」（会把目录这个标签换走）；别的组没显示的标签也不算
  {
    const g = { currentTab: 0 }, g2 = { currentTab: 1 };
    const cat = leaf('cat', g, 5), sameGroupTab = leaf('tab', g, 99);
    const hidden = leaf('hidden', g2, 50), shown = leaf('shown', g2, 10);
    g.children = [cat, sameGroupTab]; g2.children = [hidden, shown];
    const w = world([cat, sameGroupTab, hidden, shown]);
    assert.equal(w.LB.otherPane(), shown);
  }
  // 三栏：取最近用过的那一栏
  {
    const a = leaf('cat', {}, 1), b = leaf('b', {}, 20), c = leaf('c', {}, 40);
    assert.equal(world([a, b, c]).LB.otherPane(), c);
  }
  // 弹出窗口里的栏不算（不是同一个窗口）
  {
    const cat = leaf('cat', {}, 1), pop = leaf('pop', {}, 50);
    pop.view.containerEl.ownerDocument = {};
    assert.equal(world([cat, pop]).LB.otherPane(), null);
  }
  console.log('PASS catalog other pane 1104: with two panes a click opens in the other one (catalog stays, either side); one pane → same as before; tabs / hidden / popout not counted; most recent wins');
})().catch(e => { console.error(e); process.exitCode = 1; });

// 1001 审计 ingest/note-9、ui/ui-6：批注块两处同时开着（两个窗格 / 手机经 WebDAV 同步回来）不互相冲掉；
// notes.json 读坏了不当空、另存 .corrupt、暂停保存。直接跑生产那份 assets/annotate-view.js（和 bootstrap 一样用 AsyncFunction 起）。
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

const code = fs.readFileSync(path.join(__dirname, '..', 'link_brain', 'assets', 'annotate-view.js'), 'utf8');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

function el(tag, cls = '', text = '') {
  const e = {
    tag, cls, text, children: [], style: {}, value: '', placeholder: '', disabled: false, parent: null,
    classList: { add(c) { e.cls += ' ' + c; }, toggle() {} },
    createEl(t, o = {}) { const c = el(t, o.cls || '', o.text || ''); c.parent = e; e.children.push(c); return c; },
    setText(t) { e.text = t; }, empty() { e.children = []; }, closest() { return null; },
    all(sel) {
      const want = sel.replace(/^\./, ''); const out = [];
      (function walk(n) { for (const c of n.children) { if (c.cls.split(/\s+/).includes(want)) out.push(c); walk(c); } })(e);
      return out;
    },
    querySelector(sel) { return e.all(sel)[0] || null; }, querySelectorAll(sel) { return e.all(sel); },
    appendChild(c) { e.children.push(c); }, remove() {}, focus() {}, setSelectionRange() {},
  };
  return e;
}

const disk = new Map();
const adapter = {
  async exists(p) { return disk.has(p); },
  async read(p) { if (!disk.has(p)) throw new Error('ENOENT ' + p); return disk.get(p); },
  async write(p, s) { disk.set(p, s); },
};
const notices = [];
globalThis.Notice = class { constructor(m) { notices.push(m); } };
const NOTE = '_archive/xiaohongshu/n1/notes.json';
const app = { vault: { adapter }, plugins: { plugins: {} }, workspace: { on() { return {}; } } };

async function openView() {
  const dv = { container: el('div'), component: { registerEvent() {} } };
  await new AsyncFunction('dv', 'app', 'itemId', 'notePath', code)(dv, app, 'xhs-n1', NOTE);
  const ta = dv.container.querySelector('.lba-annot-input');
  return {
    dv, ta,
    async write(text) { ta.value = text; await ta.onblur(); },
    async del(text) {
      const item = dv.container.all('.lba-annot-item').find(i => i.querySelector('.lba-annot-text').text === text);
      assert.ok(item, '界面上应有这条：' + text);
      await item.querySelector('.lba-del').onclick({ stopPropagation() {} });
    },
    texts() { return dv.container.all('.lba-annot-text').map(x => x.text); },
  };
}
const onDisk = () => JSON.parse(disk.get(NOTE));
const diskTexts = () => onDisk().annotations.map(a => a.text);

(async () => {
  // ---- 两个视图同时开着：各写各的，谁也不吞谁 ----
  disk.set(NOTE, JSON.stringify({ starred: false, annotations: [{ ts: '2026-09-01T00:00:00Z', text: '旧的' }] }));
  const A = await openView();
  const B = await openView();
  await A.write('A 写的');
  await B.write('B 写的');
  assert.deepEqual(diskTexts(), ['旧的', 'A 写的', 'B 写的']);
  assert.ok(onDisk().annotations.slice(1).every(a => a.id), '新批注带 id');
  assert.deepEqual(B.texts(), ['旧的', 'A 写的', 'B 写的'], 'B 保存后把 A 那条也显示出来');

  // B 删掉老批注；A 还是旧视图（内存里有「旧的」），它再写一条不能把删掉的复活
  await B.del('旧的');
  assert.deepEqual(diskTexts(), ['A 写的', 'B 写的']);
  assert.ok(onDisk().deleted.length === 1, '删除记墓碑');
  await A.write('A 第二条');
  assert.deepEqual(diskTexts(), ['A 写的', 'B 写的', 'A 第二条']);

  // 手机经 WebDAV 同步回来一条 + Python 点了 ⭐：电脑上那个一直开着的视图打个草稿也不冲掉
  const phone = onDisk();
  phone.annotations.push({ id: 'aphone1', ts: '2099-01-01T00:00:00Z', text: '手机写的' });
  phone.starred = true;
  disk.set(NOTE, JSON.stringify(phone));
  A.ta.value = '还没写完';
  await A.ta.oninput();
  await new Promise(r => setTimeout(r, 650));  // 草稿 500ms 防抖
  assert.deepEqual(diskTexts(), ['A 写的', 'B 写的', 'A 第二条', '手机写的']);
  assert.equal(onDisk().starred, true);
  assert.equal(onDisk().draft, '还没写完');

  // ---- notes.json 读坏了：不当空、另存 .corrupt、暂停保存 ----
  const broken = '{"starred": false, "annotations": [{"ts": "2026-09-0';
  disk.set(NOTE, broken);
  notices.length = 0;
  const C = await openView();
  assert.equal(disk.get(NOTE + '.corrupt'), broken, '原文件另存 .corrupt');
  assert.ok(notices.some(m => m.includes('corrupt')), '提示她');
  assert.equal(C.ta.disabled, true);
  await C.write('不该被存');
  assert.equal(disk.get(NOTE), broken, '读坏期间绝不拿空数据盖回去');

  console.log('PASS annotate merge: 两视图并集合并、删除墓碑不复活、保留手机/⭐、坏文件另存 .corrupt 且暂停保存');
})().catch(e => { console.error(e); process.exitCode = 1; });

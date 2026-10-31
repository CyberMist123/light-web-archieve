// 1031 作者「没有让我选哪些下载」：设置页②「挑选要同步的…」→ 挑选弹窗（settings-v6.js biliPicker）。
//   收藏夹（含稍后再看）每个一个开关，关掉的存 settings.bilibili.skipFolders、同步时 --skip-folder；
//   长视频：门槛下拉（同「超过多长先不下」）、逐条勾、全选 / 全不选；勾上 = choose --allow，取消 = --undo；
//   「保存」「保存并开始同步」；没扫过收藏夹时提示先预估 / 同步；存失败弹窗不关、句式固定。
// 不起真进程（CONVENTIONS §7.5）：runPy / run 是替身；Modal 是替身。
'use strict';
const assert = require('assert/strict');
const path = require('path');
const { makeDom } = require('./_fakedom.cjs');

const dom = makeDom();
const doc = dom.document;
const El = doc.createElement('div').constructor;
El.prototype.removeClass = function (...c) { this.classList.remove(...c); };
El.prototype.toggleClass = function (c, on) { this.classList.toggle(c, on); };

class Setting {
  constructor(container) {
    this.settingEl = container.createDiv({ cls: 'setting-item' });
    const info = this.settingEl.createDiv({ cls: 'setting-item-info' });
    this.nameEl = info.createDiv({ cls: 'setting-item-name' });
    this.descEl = info.createDiv({ cls: 'setting-item-description' });
    this.controlEl = this.settingEl.createDiv({ cls: 'setting-item-control' });
  }
  setName(n) { this.nameEl.setText(n); return this; }
  setDesc(d) { this.descEl.setText(d); return this; }
  addToggle(cb) {
    const el = this.controlEl.createEl('div', { cls: 'checkbox-container' });
    let change = null;
    const t = { toggleEl: el, getValue: () => !!el.checked, setValue(v) { const was = !!el.checked; el.checked = !!v; if (change && was !== !!v) change(!!v); return t; },
      setDisabled() { return t; }, onChange(f) { change = f; el.onchange = () => f(el.checked); return t; } };
    cb(t); return this;
  }
  addDropdown(cb) {
    const el = this.controlEl.createEl('select');
    const d = { selectEl: el, options: [], addOption(v, l) { d.options.push([v, l]); return d; }, setValue(v) { el.value = v; return d; },
      onChange(f) { el.onchange = () => f(el.value); return d; } };
    cb(d); return this;
  }
}
const modals = [];
class Modal {
  constructor(app) { this.app = app; this.modalEl = doc.createElement('div'); this.contentEl = this.modalEl.createDiv({ cls: 'modal-content' }); this.isOpen = false; }
  open() { doc.body.appendChild(this.modalEl); this.isOpen = true; modals.push(this); }
  close() { this.modalEl.remove(); this.isOpen = false; if (this.onClose) this.onClose(); }
}

const flush = () => new Promise(r => setTimeout(r, 0));
const settle = async (n = 10) => { for (let i = 0; i < n; i++) await flush(); };

const LONG = it => ({ duration_text: '2:00:00', upper: 'UP', url: '', ...it });
const PICK = {
  ok: true, empty: false, message: '收藏夹 3 个',
  folders: [{ id: 'toview', title: '稍后再看', media_count: 4, private: true, kind: 'toview', scanned: true },
    { id: '11', title: '音乐', media_count: 30, private: false, kind: 'folder', scanned: true },
    { id: '12', title: '私房', media_count: 2, private: true, kind: 'folder', scanned: true }],
  long: { total: 3, chosen: 1, max_duration: 3600, items: [
    LONG({ bvid: 'BV1a', title: '长课', duration: 7200, folders: ['音乐'], folder_ids: ['11'], chosen: false }),
    LONG({ bvid: 'BV1b', title: '长剧', duration: 5000, folders: ['私房'], folder_ids: ['12'], chosen: true }),
    LONG({ bvid: 'BV1c', title: '纪录片', duration: 9000, folders: ['稍后再看', '音乐'], folder_ids: ['toview', '11'], chosen: false })] },
};

function makePlugin() {
  const p = { settings: {}, calls: [], runs: [], notices: [], saves: 0, saveFails: 0, chooseFails: 0, running: null, listeners: new Set(), pick: PICK };
  p.lbPath = x => x;
  p.app = { vault: { adapter: { read: async () => '{}' }, getAbstractFileByPath: () => null }, workspace: { getLeaf: () => ({ openFile() {} }) } };
  p.settingsPages = () => ({ LINKS: {} });
  p.saveSettings = async () => { if (p.saveFails > 0) { p.saveFails--; throw new Error('磁盘满了（合成）'); } p.saves++; };
  p.notify = (m, o = {}) => p.notices.push({ m, ...o });
  p.busyButton = (btn, t) => { const was = btn.textContent; btn.textContent = t; btn.disabled = true; return () => { btn.textContent = was; btn.disabled = false; }; };
  p.busyText = () => `正在${p.running}，完成后再点，或在底部状态栏停止`;
  p.onTask = cb => { p.listeners.add(cb); return () => p.listeners.delete(cb); };
  p.taskChanged = () => { for (const cb of p.listeners) cb(); };
  p.runPy = async args => {
    const line = args.slice(2).join(' ');
    p.calls.push(line);
    const sub = args.slice(2, 4).join(' ');
    if (sub === 'bilibili status') return { code: 0, json: { ok: true, state: 'logged_in', tv: { state: 'logged_out' } } };
    if (sub === 'bilibili last') return { code: 0, json: { ok: true, exists: false } };
    if (sub === 'bilibili pick') return { code: 0, json: p.pick };
    if (sub === 'bilibili choose') { if (p.chooseFails > 0) { p.chooseFails--; throw new Error('后台出错（合成）'); } return { code: 0, json: { ok: true, message: '放行 1 条' } }; }
    return { code: 0, json: { ok: true, message: 'ok' } };
  };
  p.run = async (args, label) => {
    p.runs.push({ args, label });
    p.running = label; p.taskChanged();
    await new Promise(r => setTimeout(r, 5));
    p.running = null; p.taskChanged();
    return { code: 0, json: { ok: true, message: '同步完：新下 1 条', counts: {} } };
  };
  return p;
}

(async () => {
  const plugin = makePlugin();
  const V = require(path.resolve('obsidian-plugins/link-brain-actions/settings-v6.js'))({ Setting, Modal }, plugin);
  const B = V.bili;
  assert.deepEqual(B.biliSkip({ skipFolders: [12, ' toview ', null, '12'] }), ['12', 'toview'], 'id 一律字符串、去空、去重');

  // —— 设置页②：显眼的入口按钮 + 看得见的说明；原来折叠的超长清单没了 ——
  const tab = { stops: [], help() {} };
  const card = doc.createElement('div');
  doc.body.appendChild(card);
  B.biliSync(card, tab);
  await settle();
  const btnIn = (root, t) => root.querySelectorAll('button').find(b => b.textContent === t);
  const entry = btnIn(card, '挑选要同步的…');
  assert.ok(entry && entry.classList.contains('is-primary'), '入口是主样式按钮');
  assert.match(card.textContent, /现在全部收藏夹和稍后再看都同步/);
  assert.ok(!card.querySelector('details') && !card.querySelector('.lb-bili-long'), '折叠的超长清单被挑选页取代');
  assert.ok(!plugin.calls.some(c => c.startsWith('bilibili long')), '设置页不再自己读超长清单');

  // —— 打开弹窗：只读本地（bilibili pick），列收藏夹开关和长视频 ——
  entry.onclick();
  await settle();
  const m = modals.at(-1);
  assert.ok(m && m.isOpen && m.modalEl.classList.contains('lb-bili-pick-modal'));
  assert.ok(plugin.calls.includes('bilibili pick --json --max-duration 3600'));
  const box = m.contentEl;
  const folderRows = box.querySelectorAll('.lb-bili-pick-folder');
  assert.deepEqual(folderRows.map(r => r.querySelector('.setting-item-name').textContent), ['稍后再看', '音乐', '私房']);
  assert.match(folderRows[2].querySelector('.setting-item-description').textContent, /2 条 · 私密/);
  assert.match(folderRows[0].textContent, /移出稍后再看的不删本地/);
  assert.ok(folderRows.every(r => r.querySelector('.checkbox-container').checked), '默认全开');
  const rows = () => box.querySelectorAll('.lb-bili-long-row');
  assert.deepEqual(rows().map(r => r.getAttribute('data-bvid')), ['BV1a', 'BV1b', 'BV1c']);
  assert.deepEqual(rows().map(r => r.querySelector('input').checked), [false, true, false], '已放行的勾着');
  assert.match(box.textContent, /超过 1 小时、还没入库的 3 条，勾上 1 条/);
  assert.match(rows()[2].textContent, /稍后再看、音乐/, '列出所在收藏夹');

  // 关掉「私房」：只在私房里的那条变灰、写明不会下；纪录片还在音乐里，不灰
  const tgl = folderRows[2].querySelector('.checkbox-container');
  tgl.checked = false; tgl.onchange();
  assert.ok(rows()[1].classList.contains('is-off') && /所在收藏夹都关了/.test(rows()[1].textContent));
  assert.ok(!rows()[2].classList.contains('is-off'));
  // 全选 / 全不选
  btnIn(box, '全选').onclick();
  assert.deepEqual(rows().map(r => r.querySelector('input').checked), [true, true, true]);
  assert.match(box.textContent, /勾上 3 条/);
  btnIn(box, '全不选').onclick();
  const cbA = rows()[0].querySelector('input'); cbA.checked = true; cbA.onchange();
  // → BV1a 新勾（allow）、BV1b 取消（undo）、BV1c 没变

  // —— 保存：choose 失败 → 弹窗不关、句式固定、勾的都还在 ——
  plugin.chooseFails = 1;
  await btnIn(box, '保存').onclick(); await settle();
  assert.ok(m.isOpen, '没存上不关弹窗');
  assert.match(plugin.notices.at(-1).m, /^没保存上，内容还在，可重试：后台出错/);
  assert.equal(plugin.notices.at(-1).kind, 'error');
  assert.equal(rows()[0].querySelector('input').checked, true);
  // 再存：设置里记下关掉的收藏夹；choose 带 --allow / --undo
  await btnIn(box, '保存').onclick(); await settle();
  assert.ok(!m.isOpen, '存好关弹窗');
  assert.deepEqual(plugin.settings.bilibili.skipFolders, ['12']);
  assert.equal(plugin.calls.filter(c => c.startsWith('bilibili choose')).at(-1), 'bilibili choose --json --allow BV1a --undo BV1b');
  assert.match(plugin.notices.at(-1).m, /已保存：跳过 1 个收藏夹，放行 1 条，撤销 1 条/);
  assert.match(card.textContent, /现在跳过 1 个收藏夹/, '设置页那行说明跟着变');
  assert.deepEqual(B.biliSyncArgs(plugin.settings.bilibili).filter((x, i, a) => a[i - 1] === '--skip-folder'), ['12'], '同步时传 --skip-folder');

  // —— 再打开：私房是关着的；改门槛 = 存「超过多长先不下」并按新门槛重读；「保存并开始同步」→ 起同步 ——
  btnIn(card, '挑选要同步的…').onclick(); await settle();
  const m2 = modals.at(-1), box2 = m2.contentEl;
  assert.equal(box2.querySelectorAll('.lb-bili-pick-folder')[2].querySelector('.checkbox-container').checked, false, '关掉的记住了');
  const th = box2.querySelector('.lb-bili-pick-threshold select');
  assert.equal(th.value, '3600');
  th.value = '7200'; await th.onchange(); await settle();
  assert.equal(plugin.settings.bilibili.maxDuration, 7200, '门槛就是「超过多长先不下」');
  assert.ok(plugin.calls.includes('bilibili pick --json --max-duration 7200'), '按新门槛重读');
  // 稍后再看也能关
  const tvT = box2.querySelectorAll('.lb-bili-pick-folder')[0].querySelector('.checkbox-container');
  tvT.checked = false; tvT.onchange();
  await btnIn(box2, '保存并开始同步').onclick(); await settle(20);
  assert.ok(!m2.isOpen);
  assert.deepEqual(plugin.settings.bilibili.skipFolders, ['12', 'toview']);
  const run = plugin.runs.at(-1);
  assert.equal(run.label, '下载 B 站收藏');
  assert.deepEqual(run.args.filter((x, i, a) => a[i - 1] === '--skip-folder'), ['12', 'toview']);
  assert.equal(run.args[run.args.indexOf('--max-duration') + 1], '7200');
  assert.equal(run.args[run.args.indexOf('--workers') + 1], '8', '默认 8 路');

  // —— 没扫过收藏夹：提示先预估 / 同步；门槛设成不限：没有要挑的 ——
  plugin.pick = { ok: true, empty: true, folders: [], long: { items: [], total: 0 }, message: '还没扫过收藏夹' };
  const api = B.biliPicker({}); await api.ready; await settle();
  assert.match(api.modal.contentEl.textContent, /还没扫过收藏夹：先关掉这里，点一次「预估」或「立即同步」/);
  api.modal.close();
  plugin.settings.bilibili.maxDuration = 0;
  plugin.pick = PICK;
  const api2 = B.biliPicker({}); await api2.ready; await settle();
  assert.match(api2.modal.contentEl.textContent, /现在是「不限」：多长的都会下，没有要挑的/);
  assert.equal(api2.modal.contentEl.querySelectorAll('.lb-bili-long-row').length, 0);
  api2.modal.close();
  console.log('PASS settings ② B 站挑选页（1031）：入口按钮取代折叠清单；收藏夹（含稍后再看）开关存 skipFolders 并传 --skip-folder；长视频门槛同设置、逐条勾 / 全选 / 全不选 → choose --allow/--undo；存失败不关弹窗；保存并开始同步；没扫过 / 不限的提示');
})().catch(e => { console.error(e); process.exit(1); });

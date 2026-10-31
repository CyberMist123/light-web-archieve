// 1031 作者「没有让我选哪些下载」：设置页②的挑选弹窗（settings-v6.js biliPicker）。
// 1101 起弹窗只管收藏夹（「选同步哪些收藏夹…」）：收藏夹（含稍后再看）每个一个开关，关掉的存 settings.bilibili.skipFolders、同步时 --skip-folder；
//   太长 / 分 P 多的视频改到「挑要下的视频」页（bili-pending-view.js）——设置页上是主按钮「挑要下的视频…」，弹窗里不再有勾选。
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
  p.app = { vault: { adapter: { read: async () => '{}' }, getAbstractFileByPath: () => null, getMarkdownFiles: () => [] }, metadataCache: { getFileCache: () => null },
    workspace: { getLeaf: () => ({ openFile() {} }) } };
  p.pagesOpened = [];
  p.openLibraryPage = async role => { p.pagesOpened.push(role); };
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

  // —— 设置页②：主按钮「挑要下的视频…」开那一页；「选同步哪些收藏夹…」开弹窗 ——
  const tab = { stops: [], help() {} };
  const card = doc.createElement('div');
  doc.body.appendChild(card);
  B.biliSync(card, tab);
  await settle();
  const btnIn = (root, t) => root.querySelectorAll('button').find(b => b.textContent === t);
  const pend = btnIn(card, '挑要下的视频…');
  assert.ok(pend && pend.classList.contains('is-primary'), '挑视频是主按钮');
  assert.match(card.textContent, /超过 1 小时、分 P 超过 5 个的视频先只记链接，在「挑要下的视频」里选中点「下载」就会下。现在全部收藏夹和稍后再看都同步/);
  assert.ok(!btnIn(card, '挑选要同步的…'), '旧入口名没了');
  await pend.onclick(); await settle();
  assert.deepEqual(plugin.pagesOpened, ['bili-pending']);
  const entry = btnIn(card, '选同步哪些收藏夹…');
  assert.ok(entry && !entry.classList.contains('is-primary'));

  // —— 打开弹窗：只读本地（bilibili pick），只列收藏夹开关，没有逐条勾选 ——
  entry.onclick();
  await settle();
  const m = modals.at(-1);
  assert.ok(m && m.isOpen && m.modalEl.classList.contains('lb-bili-pick-modal'));
  assert.ok(plugin.calls.includes('bilibili pick --json --max-duration 3600'));
  const box = m.contentEl;
  assert.match(box.textContent, /选同步哪些 B 站收藏夹/);
  const folderRows = box.querySelectorAll('.lb-bili-pick-folder');
  assert.deepEqual(folderRows.map(r => r.querySelector('.setting-item-name').textContent), ['稍后再看', '音乐', '私房']);
  assert.match(folderRows[2].querySelector('.setting-item-description').textContent, /2 条 · 私密/);
  assert.match(folderRows[0].textContent, /移出稍后再看的不删本地/);
  assert.ok(folderRows.every(r => r.querySelector('.checkbox-container').checked), '默认全开');
  assert.equal(box.querySelectorAll('.lb-bili-long-row').length, 0, '弹窗里不再逐条勾视频');
  assert.ok(!box.querySelector('.lb-bili-pick-threshold'), '门槛只在设置页那一行');

  // 关掉「私房」；全开 / 全关
  const tgl = folderRows[2].querySelector('.checkbox-container');
  tgl.checked = false; tgl.onchange();
  btnIn(box, '全关').onclick();
  assert.ok(folderRows.every(r => !r.querySelector('.checkbox-container').checked));
  btnIn(box, '全开').onclick();
  tgl.checked = false; tgl.onchange();

  // —— 保存：存失败 → 弹窗不关、句式固定、开关都还在 ——
  plugin.saveFails = 1;
  await btnIn(box, '保存').onclick(); await settle();
  assert.ok(m.isOpen, '没存上不关弹窗');
  assert.match(plugin.notices.at(-1).m, /^没保存上，内容还在，可重试：磁盘满了/);
  assert.equal(plugin.notices.at(-1).kind, 'error');
  assert.equal(tgl.checked, false);
  await btnIn(box, '保存').onclick(); await settle();
  assert.ok(!m.isOpen, '存好关弹窗');
  assert.deepEqual(plugin.settings.bilibili.skipFolders, ['12']);
  assert.ok(!plugin.calls.some(c => c.startsWith('bilibili choose')), '弹窗不再动放行表');
  assert.match(plugin.notices.at(-1).m, /已保存：跳过 1 个收藏夹/);
  assert.match(card.textContent, /现在跳过 1 个收藏夹/, '设置页那行说明跟着变');
  assert.deepEqual(B.biliSyncArgs(plugin.settings.bilibili).filter((x, i, a) => a[i - 1] === '--skip-folder'), ['12'], '同步时传 --skip-folder');

  // —— 再打开：私房是关着的；「保存并开始同步」→ 起同步 ——
  btnIn(card, '选同步哪些收藏夹…').onclick(); await settle();
  const m2 = modals.at(-1), box2 = m2.contentEl;
  assert.equal(box2.querySelectorAll('.lb-bili-pick-folder')[2].querySelector('.checkbox-container').checked, false, '关掉的记住了');
  const tvT = box2.querySelectorAll('.lb-bili-pick-folder')[0].querySelector('.checkbox-container');
  tvT.checked = false; tvT.onchange();
  await btnIn(box2, '保存并开始同步').onclick(); await settle(20);
  assert.ok(!m2.isOpen);
  assert.deepEqual(plugin.settings.bilibili.skipFolders, ['12', 'toview']);
  const run = plugin.runs.at(-1);
  assert.equal(run.label, '下载 B 站收藏');
  assert.deepEqual(run.args.filter((x, i, a) => a[i - 1] === '--skip-folder'), ['12', 'toview']);
  assert.equal(run.args[run.args.indexOf('--workers') + 1], '8', '默认 8 路');

  // —— 没扫过收藏夹：提示先预估 / 同步 ——
  plugin.pick = { ok: true, empty: true, folders: [], long: { items: [], total: 0 }, message: '还没扫过收藏夹' };
  const api = B.biliPicker({}); await api.ready; await settle();
  assert.match(api.modal.contentEl.textContent, /还没扫过收藏夹：先关掉这里，点一次「预估」或「立即同步」/);
  api.modal.close();

  // —— 「挑要下的视频」页调的插件方法：下载 / 不下 = choose --allow / --undo（带当前门槛，后端顺手重写页面数据）；choose 失败照实抛 ——
  plugin.settings.bilibili.maxDuration = 7200;
  await B.choosePending({ allow: ['BV1a'] });
  assert.equal(plugin.calls.at(-1), 'bilibili choose --json --max-duration 7200 --allow BV1a');
  await B.choosePending({ undo: ['BV1b'] });
  assert.equal(plugin.calls.at(-1), 'bilibili choose --json --max-duration 7200 --undo BV1b');
  await B.choosePending({ deny: ['BV1c', 'BV1d'] });
  assert.equal(plugin.calls.at(-1), 'bilibili choose --json --max-duration 7200 --deny BV1c --deny BV1d', '删除 = --deny');
  plugin.chooseFails = 1;
  await assert.rejects(() => B.choosePending({ allow: ['BV1a'] }), /后台出错/);
  // 现在开始下载：同设置页「立即同步」的参数；正在跑别的就不起
  const n0 = plugin.runs.length;
  await B.syncNow(); await settle(20);
  assert.equal(plugin.runs.length, n0 + 1); assert.equal(plugin.runs.at(-1).label, '下载 B 站收藏');
  assert.equal(plugin.runs.at(-1).args[plugin.runs.at(-1).args.indexOf('--max-duration') + 1], '7200');
  plugin.running = '同步收藏';
  assert.equal(await B.syncNow(), null); assert.equal(plugin.runs.length, n0 + 1);
  assert.match(plugin.notices.at(-1).m, /正在同步收藏/);
  plugin.running = null;
  console.log('PASS settings ② B 站（1101）：主按钮「挑要下的视频…」开那一页；「选同步哪些收藏夹…」弹窗只管收藏夹（含稍后再看）开关、存 skipFolders 并传 --skip-folder；存失败弹窗不关；页面调的 choose --allow/--undo 带门槛、现在开始下载走同一个互斥任务');
})().catch(e => { console.error(e); process.exit(1); });

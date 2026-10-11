// 10-10 索引树（插件侧）：她保存 索引.md → 防抖 1.5 秒重算 _archive/index-data.json（目录页监听它换分类 / 索引图）；
// 起草（AI / 高频标签，只写 索引.草稿.md）· 用这版（先确认，后端写前备份）· 未归类建议（弹窗列建议，点「加入」才写回 索引.md）·
// 生成 / 更新 wiki（先估价、确认，再带真实进度跑）。设置页那一节在 main.js fieldCategories（用设置页自己的 link / help 积木），按钮调这里挂到 plugin 上的方法。
// 解析和归类只在 Python（link_brain/indextree.py）；这里只跑命令、说结果（CONVENTIONS §1.7：提示只用 json.message）。
// 工厂 (obsidian, plugin, deps?) => ({attach, detach, ...})；deps 给测试注入 setTimeout / clearTimeout。
'use strict';

module.exports = function indexUI(obsidian, plugin, deps = {}) {
  const app = plugin.app;
  const setT = deps.setTimeout || ((fn, ms) => setTimeout(fn, ms));
  const clearT = deps.clearTimeout || (id => clearTimeout(id));
  const DEBOUNCE_MS = deps.debounceMs ?? 1500;
  const settings = () => plugin.settings || {};

  // 和 Python indextree.index_rel 同一套规则：越界 / 不是 .md / 进 _ 或 . 开头的目录 → 默认 索引.md
  function indexRel() {
    const r = String(settings().indexFile || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    if (!r || !/\.md$/i.test(r) || /^[A-Za-z]:/.test(r) || r.split('/').includes('..') || /^[._]/.test(r.split('/')[0])) return '索引.md';
    return r;
  }
  const draftRel = () => indexRel().slice(0, -3) + '.草稿.md';
  const json = r => (r && r.json) || {};
  const say = (j, fallback, extra = {}) => plugin.notify(j.message || fallback, { kind: j.ok === false ? 'error' : 'ok', ...extra });

  async function openFile(rel, line = null) {
    const f = app.vault.getAbstractFileByPath(plugin.lbPath(rel));
    if (!f) { plugin.notify(`找不到 ${rel}`, { kind: 'error' }); return; }
    const leaf = app.workspace.getLeaf(false);
    await leaf.openFile(f, Number(line) > 0 ? { eState: { line: Number(line) - 1 } } : undefined);
  }

  // ── 保存 索引.md → 重算（同一时刻只跑一份；跑的时候又保存了 = 跑完再来一次） ──
  let timer = null, building = false, again = false, lastWarn = '';
  async function rebuild() {
    if (building) { again = true; return null; }
    building = true;
    try {
      const r = await plugin.runPy(['-m', 'link_brain', 'index', 'build'], { label: '重算索引', fallback: '索引没重算上', timeoutMs: 120000 });
      const j = json(r);
      if (j.ok === false) plugin.notify(j.message || '索引没重算上', { kind: 'error' });
      else if (!j.unchanged) {
        // 写法提示：同一批提示只说一次（她边写边自动保存，别每次保存都弹）；目录页「索引」里一直有那一行
        const warns = Array.isArray(j.warnings) ? j.warnings.filter(w => w && w.line) : [];
        const sig = warns.map(w => w.text).join('|');
        if (warns.length && sig !== lastWarn) plugin.notify(`${indexRel()} 有 ${warns.length} 处写法要看一眼：${warns[0].text}`, { kind: 'warn' });
        lastWarn = sig;
      }
      return j;
    } catch (e) {
      plugin.notify('索引没重算上：' + (e?.message || e), { kind: 'error' });
      return null;
    } finally {
      building = false;
      if (again) { again = false; schedule(); }
    }
  }
  function schedule() { clearT(timer); timer = setT(() => { timer = null; rebuild(); }, DEBOUNCE_MS); }
  function onFile(file) { if (file && file.path === plugin.lbPath(indexRel())) schedule(); }

  // ── 起草 / 用这版 ──
  async function indexDraft() {
    const r = await plugin.runPy(['-m', 'link_brain', 'index', 'draft'], { label: '起草索引', fallback: '没起草成', timeoutMs: 8 * 60000 });
    const j = json(r);
    say(j, '起草好了', j.ok === false ? {} : { actions: [{ label: '看草稿', run: () => openFile(draftRel()) }] });
    return j;
  }
  async function indexUseDraft() {
    const ok = await plugin.confirm({ title: '换成草稿这一版？', body: `现在的 ${indexRel()} 会先备份到 _archive/index-history/，想找回随时能找回。`, ok: '用这版' });
    if (!ok) return null;
    const r = await plugin.runPy(['-m', 'link_brain', 'index', 'use-draft'], { label: '用草稿', fallback: '没换成', okCodes: [0, 2] });
    const j = json(r);
    say(j, '已换成草稿那版');
    return j;
  }

  // ── 未归类建议：弹窗列出来，一条一个「加入」 ──
  class SuggestModal extends obsidian.Modal {
    constructor() { super(app); this.rows = []; }
    async onOpen() {
      const el = this.contentEl;
      el.empty?.();
      this.titleEl?.setText?.('未归类建议');
      el.addClass?.('lb-index-suggest');
      this.status = el.createEl('p', { cls: 'lb-index-suggest-status', text: '正在看未归类的笔记…' });
      this.list = el.createEl('div', { cls: 'lb-index-suggest-list' });
      const bar = el.createEl('div', { cls: 'modal-button-container' });
      const edit = bar.createEl('button', { text: `打开 ${indexRel()}` }); edit.onclick = () => { this.close(); openFile(indexRel()); };
      this.again = bar.createEl('button', { text: '重新找' }); this.again.onclick = () => this.load();
      await this.load();
    }
    async load() {
      this.list.empty?.(); if (!this.list.empty) this.list.textContent = '';
      this.status.setText?.('正在看未归类的笔记…') ?? (this.status.textContent = '正在看未归类的笔记…');
      const done = plugin.busyButton(this.again, '正在找…');
      let j = {};
      try { j = json(await plugin.runPy(['-m', 'link_brain', 'index', 'suggest'], { label: '未归类建议', fallback: '没找到建议', timeoutMs: 5 * 60000 })); }
      catch (e) { j = { ok: false, message: '没找到建议：' + (e?.message || e) }; }
      finally { done(); }
      const text = j.message || '没找到建议';
      if (this.status.setText) this.status.setText(text); else this.status.textContent = text;
      for (const s of j.suggestions || []) this.row(s);
      return j;
    }
    row(s) {
      const row = this.list.createEl('div', { cls: 'lb-index-suggest-row' });
      row.dataset.id = s.id;
      const main = row.createEl('div', { cls: 'lb-index-suggest-main' });
      const where = s.path ? `「${s.path}」` : '';
      main.createEl('div', { cls: 'lb-index-suggest-title', text: s.action === 'add_tags'
        ? `给${where}补标签：${(s.tags || []).join('、')}`
        : `新建「${s.name}」` + (s.path ? `（放在${where}下面）` : '（第一级）') + ((s.tags || []).length ? `，标签：${s.tags.join('、')}` : '') });
      const ex = (s.examples || []).filter(Boolean);
      main.createEl('div', { cls: 'lb-index-suggest-sub', text: `多归进 ${s.gain} 篇` + (ex.length ? `：${ex.join('、')}` : '') + (s.why ? ` · ${s.why}` : '') });
      const add = row.createEl('button', { text: '加入', cls: 'mod-cta' });
      add.onclick = async () => {
        const done = plugin.busyButton(add, '正在加…');
        let j = {};
        try { j = json(await plugin.runPy(['-m', 'link_brain', 'index', 'apply', '--id', s.id], { label: '加入索引', fallback: '没加上', okCodes: [0, 1, 2] })); }
        catch (e) { j = { ok: false, message: '没加上：' + (e?.message || e) }; }
        if (j.ok) { done('已加入', 60000); add.disabled = true; row.addClass?.('is-done'); }
        else done();
        say(j, j.ok ? '已加入' : '没加上');
      };
      this.rows.push(row);
      return row;
    }
    onClose() { this.contentEl.empty?.(); }
  }
  function openIndexSuggestions() { const m = new SuggestModal(); m.open(); return m; }

  // ── 生成 / 更新 wiki：先估价 → 确认 → 带真实进度跑 ──
  async function wikiBuild(nodePath) {
    let est = {};
    try { est = json(await plugin.runPy(['-m', 'link_brain', 'wiki', 'build', nodePath, '--estimate'], { label: '估价', fallback: '没估出来', okCodes: [0, 1, 2] })); }
    catch (e) { plugin.notify('没估出来：' + (e?.message || e), { kind: 'error' }); return null; }
    if (!est.ok) { plugin.notify(est.message || '生成不了', { kind: est.code && String(est.code).startsWith('SKIPPED.') ? 'info' : 'error' }); return est; }
    const ok = await plugin.confirm({ title: `生成「${est.node}」的 wiki？`, ok: '生成',
      body: `${est.message}。只读这个节点收的笔记，原帖一个字不动；要几分钟，可以先去做别的。` });
    if (!ok) return null;
    const notice = plugin.notify(`正在生成「${est.node}」的 wiki…`, { ms: 0 });
    const show = t => { try { notice?.setMessage?.(t); } catch {} };
    let j = {};
    try {
      j = json(await plugin.runPy(['-m', 'link_brain', 'wiki', 'build', nodePath, '--progress'], {
        label: '生成 wiki', fallback: 'wiki 没生成', okCodes: [0, 1, 2], timeoutMs: 60 * 60000,
        onLine: line => { try { const ev = JSON.parse(line); if (ev && ev.type === 'progress' && ev.text) show(`生成「${est.node}」的 wiki：${ev.text}`); } catch {} } }));
    } catch (e) { j = { ok: false, message: 'wiki 没生成：' + (e?.message || e) }; }
    finally { try { notice?.hide?.(); } catch {} }
    say(j, 'wiki 已生成', j.ok ? { actions: [{ label: '打开', run: () => openFile(j.file) }] } : {});
    return j;
  }

  // ── 10-11 按内容归类 / 手动改归属 / 建议新增 / 空节点：都只跑 Python 拿结果（JSON），提示和撤销由页面做（LB.say / LB.undoNotice）；
  //    写完 Python 会重算 index-data.json，页面的文件监听照样换新 ──
  async function indexCmd(args, label, fallback, { timeoutMs = 120000, onLine = null } = {}) {
    try {
      const r = await plugin.runPy(['-m', 'link_brain', 'index', ...args], { label, fallback, okCodes: [0, 1, 2], timeoutMs, onLine });
      const j = json(r);
      return Object.keys(j).length ? j : { ok: false, message: fallback };
    } catch (e) { return { ok: false, message: `${fallback}：` + (e?.message || e) }; }
  }
  // op：move（只放这一类）/ add（也放进）/ remove（从这里拿掉）/ reset / undo（path = 撤销号）
  function indexAssign(ids, op, path = '') {
    const args = ['assign', '--op', String(op), '--path', String(path || '')];
    for (const id of ids || []) args.push('--item', String(id));
    return indexCmd(args, '改归类', '没改上');
  }
  // 10-11 细分标签：给几篇加 / 去掉某个节点下的细分标签（op = add / remove），压过 AI
  function indexFacet(ids, path, op, name) {
    const args = ['facet', '--path', String(path || ''), '--op', String(op), '--name', String(name || '')];
    for (const id of ids || []) args.push('--item', String(id));
    return indexCmd(args, '细分标签', '没改上');
  }
  const indexAccept = id => indexCmd(['accept', '--id', String(id)], '加进索引', '没加上');
  const indexDismiss = id => indexCmd(['dismiss', '--id', String(id)], '不要这条建议', '没记上');
  const indexEmpty = (path, action) => indexCmd(['empty', '--path', String(path), action === 'remove' ? '--remove' : '--keep'], '空分类', '没改上');
  // 手动「按内容归类」：带真实进度（Python 一行一个进度事件），整库第一次几分钟
  function indexClassify({ onProgress = null } = {}) {
    return indexCmd(['classify', '--progress'], '按内容归类', '没归完', {
      timeoutMs: 40 * 60000,
      onLine: line => { try { const ev = JSON.parse(line); if (ev && ev.type === 'progress' && onProgress) onProgress(ev); } catch {} } });
  }

  return {
    indexRel, draftRel, rebuild, schedule, openIndexSuggestions, indexDraft, indexUseDraft, wikiBuild, SuggestModal,
    indexAssign, indexAccept, indexDismiss, indexEmpty, indexClassify, indexFacet,
    attach() {
      // Obsidian 开库时会给每个已有文件发一次 create：等布局好了再挂，别一开库就重算一遍
      const hook = () => { if (app.vault?.on) for (const ev of ['modify', 'create']) plugin.registerEvent(app.vault.on(ev, onFile)); };
      if (app.workspace?.onLayoutReady) app.workspace.onLayoutReady(hook); else hook();
      // 页面（catalog-view.js）调的入口：LB.ensure / want(method) 找的就是这几个名字
      plugin.indexDraft = indexDraft;
      plugin.indexUseDraft = indexUseDraft;
      plugin.openIndexSuggestions = openIndexSuggestions;
      plugin.wikiBuild = wikiBuild;
      plugin.openIndexFile = line => openFile(indexRel(), line);
      plugin.indexRebuild = () => schedule();          // 页面发现索引是用旧目录数据算的：重算一次（防抖、同一时刻一份）
      plugin.indexAssign = indexAssign;                // 10-11：目录页「移到… / 也放进… / 从这里拿掉」、撤销
      plugin.indexFacet = indexFacet;                  // 卡片「归类…」里加 / 去掉细分标签
      plugin.indexAccept = indexAccept;                // 「建议新增」加进索引 / AI 建的子类「保留」
      plugin.indexDismiss = indexDismiss;
      plugin.indexEmpty = indexEmpty;                  // 空分类：删 / 留
      plugin.indexClassify = indexClassify;            // 手动「按内容归类」（后台自动的由 Python 自己拉起）
      plugin.addCommand?.({ id: 'index-edit', name: '编辑索引（打开 索引.md）', callback: () => openFile(indexRel()) });
      plugin.addCommand?.({ id: 'index-draft', name: '索引：AI 起草一版（写在草稿里）', callback: () => indexDraft().catch(e => plugin.notify('没起草成：' + (e?.message || e), { kind: 'error' })) });
      plugin.addCommand?.({ id: 'index-suggest', name: '索引：未归类建议', callback: () => openIndexSuggestions() });
    },
    detach() { clearT(timer); timer = null; },
  };
};

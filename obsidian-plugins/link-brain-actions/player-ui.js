// player-ui.js — 批次 D · L5 F6-c：按标签连播视频。
//   openTagPicker({itemId})：标签选择弹窗（playlist --tags）+ 顺序「新→旧 / 旧→新 / 乱序」→ playlist --tag … → 播放视图；
//   播放视图（ItemView 'lb-player'）：自动下一条、上一条 / 下一条、单曲循环（播放器自己的，默认关，不读写 settings.media.loop）、
//   「#标签 · 顺序 · 第 i / N」、打开笔记（右侧拆分，播放器继续播）。重启恢复标签页时不自动起 Python，点「继续」才读。
// 插件 onload 里 require(...)(obsidian, plugin).attach()，实例在 plugin.playerUI；笔记页视频工具行的「连播…」调 openTagPicker。
'use strict';

const VIEW_TYPE = 'lb-player';
const ORDER_TEXT = { newest: '新→旧', oldest: '旧→新', shuffle: '乱序' };
const SPEEDS = [1, 1.25, 1.5, 2, 0.75];
const mmss = s => { const n = Math.round(Number(s) || 0); return n ? `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}` : ''; };
const norm = t => String(t || '').trim().replace(/^#/, '').trim().toLowerCase();

module.exports = (obsidian, plugin, deps = {}) => {
  const app = () => plugin.app;
  const later = deps.setTimeout || ((fn, ms) => setTimeout(fn, ms));
  let pending = null;

  async function py(args, label) {
    try { const r = await plugin.runPy(args, { label, timeoutMs: 120000, okCodes: [0, 1, 2] }); return r && r.json; }
    catch (e) { return (e && e.result && e.result.json) || { ok: false, message: (e && e.message) || String(e) }; }
  }
  const playlistArgs = ({ tag, order, seed, start }) => ['-m', 'link_brain', 'playlist', '--tag', tag, '--order', order,
    ...(seed != null && order === 'shuffle' ? ['--seed', String(seed)] : []), ...(start ? ['--start', start] : []), '--json'];

  function noteTagsOf(itemId) {
    if (!itemId) return [];
    try {
      for (const f of app().vault.getMarkdownFiles()) {
        const fm = app().metadataCache.getFileCache(f)?.frontmatter;
        if (fm && fm.link_brain && fm.link_brain.item_id === itemId) {
          const t = fm.tags;
          return (Array.isArray(t) ? t : typeof t === 'string' ? t.split(',') : []).map(x => String(x).trim().replace(/^#/, '')).filter(Boolean);
        }
      }
    } catch {}
    return [];
  }

  class TagPickerModal extends obsidian.Modal {
    constructor(a, { itemId = null, noteTags = null } = {}) {
      super(a);
      this.itemId = itemId; this.noteTags = noteTags || noteTagsOf(itemId);
      this.tags = []; this.query = ''; this.sel = 0; this.composing = false;
      this.order = (plugin.settings && plugin.settings.media && plugin.settings.media.playlistOrder) || 'newest';
    }
    onOpen() {
      const c = this.contentEl; c.empty?.(); c.classList.add('lb-tagpick');
      this.titleEl?.setText?.('按标签连播视频');
      this.input = c.createEl('input', { type: 'text', cls: 'lb-tagpick-input', attr: { placeholder: '找标签…' } });
      this.status = c.createEl('div', { cls: 'lb-tagpick-status', text: '读取标签…' });
      this.listEl = c.createEl('div', { cls: 'lb-tagpick-list' });
      this.msgEl = c.createEl('div', { cls: 'lb-tagpick-msg' });
      const seg = c.createEl('div', { cls: 'lb-tagpick-order' });
      this.orderBtns = Object.keys(ORDER_TEXT).map(k => {
        const b = seg.createEl('button', { text: ORDER_TEXT[k], attr: { type: 'button', 'data-order': k } });
        b.addEventListener('click', () => this.setOrder(k));
        return b;
      });
      this.startBtn = c.createEl('button', { cls: 'mod-cta lb-tagpick-start', text: '开始', attr: { type: 'button' } });
      this.startBtn.addEventListener('click', () => this.start());
      this.input.addEventListener('compositionstart', () => { this.composing = true; });
      this.input.addEventListener('compositionend', () => { this.composing = false; this.filter(this.input.value); });
      this.input.addEventListener('input', e => { if (e.isComposing || this.composing || e.keyCode === 229) return; this.filter(this.input.value); });
      this.input.addEventListener('keydown', e => {
        if (e.isComposing || e.keyCode === 229) return;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault?.(); this.move(e.key === 'ArrowDown' ? 1 : -1); }
        else if (e.key === 'Enter') { e.preventDefault?.(); this.start(); }
      });
      this.paintOrder();
      this.ready = this.load();
      return this.ready;
    }
    setOrder(k) {
      this.order = k;
      if (plugin.settings) { plugin.settings.media = { ...(plugin.settings.media || {}), playlistOrder: k }; try { plugin.saveSettings?.(); } catch {} }
      this.paintOrder();
    }
    paintOrder() { for (const b of this.orderBtns || []) { const on = b.getAttribute('data-order') === this.order; b.classList.toggle('is-active', on); b.setAttribute('aria-pressed', String(on)); } }
    async load() {
      const j = await py(['-m', 'link_brain', 'playlist', '--tags', '--json'], '读取标签');
      if (!j || !j.ok) { this.status.textContent = (j && j.message) || '标签没读出来'; return; }
      const mine = this.noteTags.map(norm);
      const rank = t => { const i = mine.indexOf(norm(t.tag)); return i < 0 ? 1e9 : i; };
      this.tags = [...(j.tags || [])].sort((a, b) => rank(a) - rank(b));
      this.status.textContent = this.tags.length ? '' : '还没有带视频的标签';
      this.filter('');
      const pre = this.view.findIndex(t => mine.includes(norm(t.tag)) && t.playable >= 1);
      if (pre >= 0) { this.sel = pre; this.paint(); }
    }
    filter(q) { this.query = q; const n = norm(q); this.view = this.tags.filter(t => !n || norm(t.tag).includes(n)); this.sel = 0; this.paint(); }
    move(d) { if (!this.view.length) return; this.sel = (this.sel + d + this.view.length) % this.view.length; this.paint(); }
    paint() {
      this.listEl.empty?.(); if (!this.listEl.empty) this.listEl.textContent = '';
      (this.view || []).forEach((t, i) => {
        const miss = t.count - t.playable;
        const row = this.listEl.createEl('div', { cls: 'lb-tagpick-row' + (i === this.sel ? ' is-selected' : ''), text: `#${t.tag} · ${t.playable} 条` + (miss > 0 ? `（${miss} 条没下载）` : '') });
        row.addEventListener('click', () => { this.sel = i; this.paint(); });
        row.addEventListener('dblclick', () => { this.sel = i; this.start(); });
      });
    }
    async start(tagOverride) {
      const t = tagOverride || (this.view && this.view[this.sel] && this.view[this.sel].tag);
      if (!t) return null;
      this.msgEl.textContent = '';
      const opts = { tag: t, order: this.order, start: this.itemId };
      const j = await py(playlistArgs(opts), '连播');
      if (!j || !j.ok) {
        this.msgEl.textContent = (j && j.message) || '没读到这组视频';
        for (const s of (j && j.suggestions) || []) {
          const a = this.msgEl.createEl('button', { cls: 'lb-tagpick-sugg', text: '#' + s, attr: { type: 'button' } });
          a.addEventListener('click', () => this.start(s));
        }
        return j;
      }
      this.close();
      await startPlaylist(j, { tag: j.tag || t, order: this.order });
      return j;
    }
  }

  class PlayerView extends obsidian.ItemView {
    constructor(leaf) { super(leaf); this.items = null; this.idx = 0; this.loop = false; this.failed = new Set(); this.st = {}; this.speed = 0; }
    getViewType() { return VIEW_TYPE; }
    getDisplayText() { return this.st.tag ? `连播 #${this.st.tag}` : '连播'; }
    getIcon() { return 'list-video'; }
    getState() { return { tag: this.st.tag, order: this.st.order, seed: this.st.seed, index: this.idx }; }
    async setState(state, result) {
      this.st = { tag: state && state.tag, order: (state && state.order) || 'newest', seed: state && state.seed };
      if (pending) { const p = pending; pending = null; this.load(p, p.start_index || 0); }
      else if (!this.items && this.st.tag) this.paintResume((state && state.index) || 0);
      return super.setState ? super.setState(state, result) : undefined;
    }
    async onOpen() { this.root = this.contentEl.createEl('div', { cls: 'lb-player' }); this.contentEl.addEventListener('keydown', e => this.onKey(e)); if (!this.contentEl.hasAttribute('tabindex')) this.contentEl.tabIndex = 0; }
    async onClose() { this.release(); }
    release() { const v = this.video; if (v) { try { v.pause(); } catch {} v.removeAttribute('src'); try { v.load(); } catch {} } }
    paintResume(index) {
      this.ensureRoot(); this.root.empty?.(); this.root.textContent = '';
      const b = this.root.createEl('div', { cls: 'lb-player-resume', text: `上次在连播 #${this.st.tag} · 第 ${index + 1} 条` });
      const go = b.createEl('button', { text: '继续', attr: { type: 'button' } });
      go.addEventListener('click', async () => {
        const j = await py(playlistArgs({ tag: this.st.tag, order: this.st.order, seed: this.st.seed }), '连播');
        if (j && j.ok) this.load(j, Math.min(index, (j.items || []).length - 1));
        else plugin.notify((j && j.message) || '没读到这组视频', { kind: 'error' });
      });
    }
    ensureRoot() { if (!this.root) this.root = this.contentEl.createEl('div', { cls: 'lb-player' }); }
    load(j, index = 0) {
      this.items = j.items || []; this.failed = new Set(); this.loop = false;
      this.st = { tag: j.tag, order: j.order, seed: j.seed };
      this.ensureRoot(); this.root.empty?.(); this.root.textContent = '';
      const head = this.root.createEl('div', { cls: 'lb-player-head' });
      this.headText = head.createEl('span', { cls: 'lb-player-pos' });
      const sw = head.createEl('button', { text: '换标签…', attr: { type: 'button' } });
      sw.addEventListener('click', () => openTagPicker({}));
      this.stage = this.root.createEl('div', { cls: 'lb-player-stage' });
      const v = this.video = this.stage.createEl('video', { cls: 'lb-player-video' });
      v.autoplay = true; v.playsInline = true; v.preload = 'auto'; v.setAttribute('playsinline', '');
      v.addEventListener('ended', () => this.onEnded());
      v.addEventListener('error', () => this.onError());
      const tools = this.stage.createEl('div', { cls: 'lb-player-tools' });
      const btn = (cls, text, fn, label) => { const b = tools.createEl('button', { cls, text, attr: { type: 'button', 'aria-label': label || text } }); b.addEventListener('click', fn); return b; };
      btn('lb-player-prev', '⏮ 上一条', () => this.prev());
      this.speedBtn = btn('lb-player-speed', '1×', () => this.cycleSpeed(), '倍速');
      this.loopBtn = btn('lb-player-loop', '循环', () => this.toggleLoop(), '单曲循环');
      this.loopBtn.setAttribute('aria-pressed', 'false');
      btn('lb-player-next', '下一条 ⏭', () => this.next());
      this.endEl = this.stage.createEl('div', { cls: 'lb-player-end' }); this.endEl.style.display = 'none';
      try { plugin.mediaNav?.hoverControls?.(this.stage, v); } catch {}
      const t = this.root.createEl('div', { cls: 'lb-player-title' });
      this.titleText = t.createEl('span');
      const open = t.createEl('button', { text: '打开笔记', attr: { type: 'button' } });
      open.addEventListener('click', () => this.openNote());
      const det = this.root.createEl('details', { cls: 'lb-player-list' });
      det.createEl('summary', { text: '列表' });
      this.ol = det.createEl('ol');
      this.items.forEach((it, i) => {
        const li = this.ol.createEl('li', { text: `${it.title || '（无标题）'}` + (mmss(it.duration_sec) ? ` · ${mmss(it.duration_sec)}` : '') });
        li.addEventListener('click', () => this.play(i));
      });
      this.play(Math.max(0, index));
    }
    src(rel) { return app().vault.adapter.getResourcePath(plugin.lbPath(rel)); }
    play(i) {
      if (!this.items || i < 0 || i >= this.items.length) return;
      this.idx = i;
      const it = this.items[i], v = this.video;
      this.endEl.style.display = 'none';
      v.loop = this.loop;
      if (it.poster) v.setAttribute('poster', this.src(it.poster)); else v.removeAttribute('poster');
      v.src = this.src(it.video);
      if (this.speed) v.playbackRate = SPEEDS[this.speed];
      try { const p = v.play?.(); if (p && p.catch) p.catch(() => {}); } catch {}
      this.paintPos();
      app().workspace?.requestSaveLayout?.();
    }
    paintPos() {
      const it = this.items[this.idx] || {};
      this.headText.textContent = `#${this.st.tag} · ${ORDER_TEXT[this.st.order] || ''} · 第 ${this.idx + 1} / ${this.items.length}`;
      this.titleText.textContent = [it.title, it.author, mmss(it.duration_sec)].filter(Boolean).join(' · ');
      [...this.ol.children].forEach((li, i) => { li.classList.toggle('is-current', i === this.idx); li.classList.toggle('is-failed', this.failed.has(i)); });
    }
    next() { if (this.idx < this.items.length - 1) this.play(this.idx + 1); else this.finish(); }
    prev() { if (this.idx > 0) this.play(this.idx - 1); }
    onEnded() { if (this.loop) return; this.next(); }
    onError() {
      if (!this.items) return;
      this.failed.add(this.idx); this.paintPos();
      this.titleText.textContent = '播不了 · ' + this.titleText.textContent;
      if (this.failed.size >= this.items.length) { this.showEnd(`这组视频都播不了：${this.video.error ? '文件不在了或解码不了' : '原因不明'}`, false); return; }
      const at = this.idx;
      later(() => { if (this.idx === at) this.next(); }, 1500);
    }
    finish() { this.showEnd(`#${this.st.tag} 的 ${this.items.length} 条播完了`, true); }
    showEnd(text, buttons) {
      const e = this.endEl; e.empty?.(); e.textContent = ''; e.style.display = '';
      e.createEl('div', { text });
      if (!buttons) return;
      const again = e.createEl('button', { cls: 'lb-player-again', text: '从头再播', attr: { type: 'button' } });
      again.addEventListener('click', () => this.play(0));
      const shuf = e.createEl('button', { cls: 'lb-player-shuffle', text: '乱序再播', attr: { type: 'button' } });
      shuf.addEventListener('click', async () => {
        const j = await py(playlistArgs({ tag: this.st.tag, order: 'shuffle' }), '连播');
        if (j && j.ok) this.load(j, 0);
      });
    }
    toggleLoop() { this.loop = !this.loop; this.video.loop = this.loop; this.loopBtn.setAttribute('aria-pressed', String(this.loop)); this.loopBtn.classList.toggle('is-active', this.loop); }
    cycleSpeed() { this.speed = (this.speed + 1) % SPEEDS.length; this.video.playbackRate = SPEEDS[this.speed]; this.speedBtn.textContent = SPEEDS[this.speed] + '×'; }
    async openNote() {
      const it = this.items && this.items[this.idx];
      if (!it || !it.note) return;
      const file = app().vault.getAbstractFileByPath(plugin.lbPath(it.note));
      if (!file) { plugin.notify('这篇笔记找不到了：可能改了名或删了', { kind: 'warn' }); return; }
      const ws = app().workspace;
      let leaf = this.noteLeaf;
      if (!leaf || (ws.getLeavesOfType && !ws.getLeavesOfType('markdown').includes(leaf))) leaf = this.noteLeaf = ws.getLeaf('split', 'vertical');
      await leaf.openFile(file);
    }
    onKey(e) {
      const k = e.key;
      if (k === 'PageDown' || k === 'n' || k === 'N') { e.preventDefault?.(); this.next(); }
      else if (k === 'PageUp' || k === 'p' || k === 'P') { e.preventDefault?.(); this.prev(); }
      else if (k === 'l' || k === 'L') { e.preventDefault?.(); this.toggleLoop(); }
    }
  }

  async function startPlaylist(j, { tag, order } = {}) {
    const ws = app().workspace;
    let leaf = (ws.getLeavesOfType && ws.getLeavesOfType(VIEW_TYPE)[0]) || ws.getLeaf('tab');
    pending = { ...j, tag: j.tag || tag, order: j.order || order };
    await leaf.setViewState({ type: VIEW_TYPE, active: true, state: { tag: pending.tag, order: pending.order, seed: j.seed, index: j.start_index || 0 } });
    if (pending && leaf.view && typeof leaf.view.load === 'function') { const p = pending; pending = null; leaf.view.load(p, p.start_index || 0); }
    ws.revealLeaf?.(leaf);
    return leaf.view;
  }

  function openTagPicker({ itemId = null, noteTags = null } = {}) {
    const m = new TagPickerModal(app(), { itemId, noteTags });
    m.open();
    return m;
  }

  return {
    VIEW_TYPE,
    attach() {
      plugin.registerView?.(VIEW_TYPE, leaf => new PlayerView(leaf));
      plugin.addCommand?.({ id: 'video-playlist', name: '按标签连播视频…', callback: () => openTagPicker({}) });
    },
    openTagPicker, startPlaylist, TagPickerModal, PlayerView,
  };
};

// note-actions.js — 批次 D · L3 笔记页动作（插件 onload 里 require(...)(obsidian, plugin).attach()，实例在 plugin.noteActions）：
//   N2  笔记样式挂到 document.head（note.css，和 link_brain/assets/link-brain.css 逐字节相同；css-change 后挪到最后，片段旧了也盖不掉新规则）
//       + body.lb-actions-on（桌面插件开着才显示「现在抓」、可点的标签这些入口）
//   N8 / N14 评论区「现在抓全部评论 / 现在抓」→ 确认后 plugin.fetchAllComments(file)
//   N9  正文标签（原帖话题）点了 → plugin.pendingCatalogQuery='#标签' → 同一窗格开目录（Ctrl 开新标签）→ 'link-brain:catalog-query'
//   N10 阅读视图选中正文 / 评论文字右键「划重点 / 取消重点」（只走 <mark>，先乐观包上、没写上的退回）
//   N11 ⋯ 菜单 / 命令面板「问这篇」→ plugin.askAboutNote(file)（问收藏那边由 L2 接）
//   N17 没开 Dataview（或它的 JS 查询）时打开归档笔记也挂提示条（复用目录页那条）
// 图片右键（F2）归 image-actions.js，这里遇到图片上的右键直接让开。
'use strict';
const fs = require('fs');
const path = require('path');

const NOTE_STYLE_ID = 'lb-note-style';
const mmss = ms => { const s = Math.max(0, Math.floor((Number(ms) || 0) / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
// 划重点只收这几处的文字（和内容层的转义片段一一对应；评论里的「回复 xx：」不算）
const PHRASE_SCOPE = '.lb-body p, .lb-comment-text, .lb-note-title, .lb-comment-asr';

class NoteActions {
  constructor(obsidian, plugin) {
    this.obsidian = obsidian || {};
    this.plugin = plugin;
    this.attached = false;
    this.styleEl = null;
  }
  get app() { return this.plugin.app; }
  doc() { return typeof document !== 'undefined' ? document : null; }
  notify(msg, opts) {
    try { if (typeof this.plugin.notify === 'function') return this.plugin.notify(msg, opts); } catch {}
    try { const N = this.obsidian.Notice || (typeof Notice === 'function' ? Notice : null); if (N) return new N(msg); } catch {}
    return null;
  }
  fm(file) { try { return file ? this.app.metadataCache.getFileCache(file)?.frontmatter || null : null; } catch { return null; } }
  itemIdOf(file) { const id = this.fm(file)?.link_brain?.item_id; return typeof id === 'string' && id ? id : ''; }
  markdownLeaves() {
    const ws = this.app && this.app.workspace;
    if (!ws) return [];
    try { if (typeof ws.getLeavesOfType === 'function') return ws.getLeavesOfType('markdown') || []; } catch {}
    return ws.leaves || [];
  }
  leafOf(el) {
    for (const l of this.markdownLeaves()) { const c = l && l.view && l.view.containerEl; if (c && typeof c.contains === 'function' && c.contains(el)) return l; }
    return null;
  }
  inReading(el) { return !!(el && typeof el.closest === 'function' && el.closest('.markdown-reading-view, .markdown-preview-view') && !el.closest('.markdown-source-view')); }

  attach() {
    if (this.attached) return this;
    this.attached = true;
    const D = this.doc();
    this.injectNoteStyle();
    if (D && D.body && D.body.classList) {
      D.body.classList.add('lb-actions-on');
      this.plugin.register?.(() => { try { D.body.classList.remove('lb-actions-on'); } catch {} });
    }
    if (D && typeof this.plugin.registerDomEvent === 'function') {
      this.plugin.registerDomEvent(D, 'click', (e) => this.onClick(e));
      this.plugin.registerDomEvent(D, 'keydown', (e) => this.onKey(e));
      this.plugin.registerDomEvent(D, 'contextmenu', (e) => this.onContextMenu(e), true);
    }
    const ws = this.app && this.app.workspace;
    if (ws && typeof ws.on === 'function' && typeof this.plugin.registerEvent === 'function') {
      this.plugin.registerEvent(ws.on('file-menu', (menu, file) => this.onFileMenu(menu, file)));
      this.plugin.registerEvent(ws.on('file-open', (file) => { this.onFileOpen(file); if (this.plugin.commentFetch) this.paintFetch(); }));
      this.plugin.registerEvent(ws.on('css-change', () => this.keepStyleLast()));
      this.plugin.registerEvent(ws.on('link-brain:comment-fetch', () => this.paintFetch()));   // 1010：抓全部评论的进度
    }
    this.plugin.register?.(() => this.stopFetchTick());
    if (typeof this.plugin.addCommand === 'function') {
      this.plugin.addCommand({ id: 'note-ask', name: '问这篇（打开问收藏，来源 = 当前笔记）', checkCallback: (checking) => {
        const file = ws && typeof ws.getActiveFile === 'function' ? ws.getActiveFile() : null;
        if (!this.itemIdOf(file)) return false;
        if (!checking) this.ask(file);
        return true;
      } });
      this.plugin.addCommand({ id: 'note-highlight-selection', name: '划重点 / 取消重点（选中的文字）', checkCallback: (checking) => {
        const ctx = this.selectionContext();
        if (!ctx || (!ctx.phrases.length && !ctx.mark)) return false;
        if (!checking) { if (ctx.phrases.length) this.highlight(ctx); else this.unhighlight(ctx); }
        return true;
      } });
    }
    return this;
  }
  detach() {
    this.attached = false;
    this.stopFetchTick();
    try { const D = this.doc(); if (D && D.querySelectorAll) for (const b of [...D.querySelectorAll('.lb-fetch-progress')]) b.remove(); } catch {}
    try { this.styleEl && this.styleEl.remove(); } catch {}
    this.styleEl = null;
    const D = this.doc();
    try { D && D.body && D.body.classList.remove('lb-actions-on'); } catch {}
  }

  // ── N2 ──
  injectNoteStyle() {
    const D = this.doc();
    if (!D || !D.head) return null;
    let css = '';
    try {
      const base = this.app.vault.adapter.getBasePath();
      css = fs.readFileSync(path.join(base, this.plugin.manifest.dir, 'note.css'), 'utf8');
    } catch (e) { console.error('[lb] 笔记样式没读到（照常用 CSS 片段）', e); return null; }
    let el = D.getElementById(NOTE_STYLE_ID);
    if (!el) {
      el = D.createElement('style');
      el.id = NOTE_STYLE_ID;
      D.head.appendChild(el);
    }
    if (el.textContent !== css) el.textContent = css;
    this.styleEl = el;
    this.plugin.register?.(() => { try { el.remove(); } catch {} });
    this.keepStyleLast();
    return el;
  }
  keepStyleLast() {
    const el = this.styleEl, D = this.doc();
    if (el && el.isConnected && D && D.head && D.head.lastElementChild !== el) D.head.appendChild(el);
  }

  // ── N8 / N14 / N9 ──
  onClick(e) {
    const D = this.doc();
    const t = e && e.target && typeof e.target.closest === 'function' ? e.target : null;
    if (!t || !D || !D.body.classList.contains('lb-actions-on')) return;
    const act = t.closest('.xhs-note .lb-act-fetch-comments');
    if (act && this.inReading(act)) { e.preventDefault?.(); this.askFetchComments(act); return; }
    const tag = t.closest('.xhs-note .lb-tags .lb-tag');
    if (tag && this.inReading(tag)) { e.preventDefault?.(); return this.openTag(tag, e); }
    return undefined;
  }
  onKey(e) {
    if (!e || (e.key !== 'Enter' && e.key !== ' ')) return;
    const t = e.target && typeof e.target.closest === 'function' ? e.target.closest('.xhs-note .lb-act-fetch-comments') : null;
    if (!t || !this.inReading(t)) return;
    e.preventDefault?.();
    this.askFetchComments(t);
  }
  askFetchComments(el) {
    const leaf = this.leafOf(el);
    const file = leaf && leaf.view && leaf.view.file;
    if (!file) { this.notify('没找到这篇笔记'); return; }
    if (this.plugin.running) { this.notify(`正在${this.plugin.running}，完成后再点`); return; }
    // 多点一下确认：这会开页面、用号
    this.notify('抓这篇的全部评论？热门笔记要几分钟到十几分钟；进度就显示在评论区顶上，完成后页面自动更新。', { ms: 12000, actions: [{ label: '开始抓', run: () => this.plugin.fetchAllComments(file) }] });
  }

  // ── 1010：手动「抓全部评论」的进度（plugin.commentFetch，main.js fetchAllComments 写；事件 'link-brain:comment-fetch'）──
  // 画在这篇笔记（.lb-note[data-lb-item=<id>]）评论区（.lb-comments）最上面：一行字 + 一根细条（读评论区时来回扫，
  // 下图 / 语音时按真计数走）；只显示后端发来的阶段（CONVENTIONS §1.6），已用时间是本机钟。Obsidian 重画这一段时这一行会丢：
  // 进行中每秒补画一次（顺手刷新已用时间）；做完显示结果，plugin 过几秒把 commentFetch 清掉，这一行跟着收起。
  fetchLine(st, now = Date.now()) {
    if (!st) return '';
    if (st.result) return (st.result.ok ? '✓ ' : '⚠ 没抓完：') + String(st.result.message || '').replace(/^评论没抓：/, '');
    const took = mmss(now - (st.stageAt || st.startedAt || now));
    if (st.stage === 'lock') return `⟳ 抓全部评论 · ${st.text} · 已等 ${took}`;
    if (st.stage === 'read') return `⟳ 抓全部评论 · ${st.text} · 已用 ${took}`;
    return `⟳ 抓全部评论 · ${st.text || '正在…'}`;
  }
  paintFetch() {
    const D = this.doc();
    if (!D || typeof D.querySelectorAll !== 'function') return;
    const st = this.plugin.commentFetch || null;
    const boxes = [...D.querySelectorAll('.lb-fetch-progress')];
    if (!st) { for (const b of boxes) b.remove(); this.stopFetchTick(); return; }
    const id = String(st.itemId || '');
    const hosts = [...D.querySelectorAll('.xhs-note .lb-note .lb-comments')].filter(h => h.closest('.lb-note')?.getAttribute?.('data-lb-item') === id);
    for (const b of boxes) if (!hosts.some(h => h.contains(b))) b.remove();   // 别的笔记上的残留
    const text = this.fetchLine(st);
    const pct = !st.result && st.stage === 'media' && st.total ? Math.max(0, Math.min(100, Math.round((st.done || 0) / st.total * 100))) : null;
    for (const h of hosts) {
      let box = [...(h.children || [])].find(c => c.classList?.contains('lb-fetch-progress')) || null;
      if (!box) {
        box = D.createElement('div'); box.className = 'lb-fetch-progress';
        box.setAttribute('role', 'status'); box.setAttribute('aria-live', 'polite');
        const t = D.createElement('div'); t.className = 'lb-fetch-text'; box.appendChild(t);
        const bar = D.createElement('div'); bar.className = 'lb-fetch-bar';
        const fill = D.createElement('div'); fill.className = 'lb-fetch-fill'; bar.appendChild(fill); box.appendChild(bar);
        h.insertBefore(box, h.firstChild);
      }
      const t = box.querySelector('.lb-fetch-text'), fill = box.querySelector('.lb-fetch-fill');
      if (t && t.textContent !== text) t.textContent = text;
      box.classList.toggle('is-done', !!(st.result && st.result.ok));
      box.classList.toggle('is-failed', !!(st.result && !st.result.ok));
      box.classList.toggle('is-indeterminate', !st.result && pct == null);
      if (fill) fill.style.width = pct == null ? '' : pct + '%';
    }
    if (st.result) this.stopFetchTick();
    else if (!this.fetchTick) this.fetchTick = setInterval(() => this.paintFetch(), 1000);
  }
  stopFetchTick() { if (this.fetchTick) { clearInterval(this.fetchTick); this.fetchTick = null; } }
  async openTag(el, e) {
    const tag = String(el.textContent || '').replace(/^#/, '').trim();
    if (!tag) return;
    this.plugin.pendingCatalogQuery = '#' + tag;
    const ws = this.app.workspace;
    const leaf = e && (e.ctrlKey || e.metaKey) && typeof ws.getLeaf === 'function' ? ws.getLeaf('tab') : this.leafOf(el);
    try { await this.plugin.openLibraryPage('catalog', leaf || null); }
    catch (err) { console.error('[lb] 目录没打开', err); this.notify('目录没打开：' + ((err && err.message) || err)); return; }
    ws.trigger?.('link-brain:catalog-query');
  }

  // ── N11 ──
  onFileMenu(menu, file) {
    if (!menu || !this.itemIdOf(file)) return;
    menu.addItem(i => i.setTitle('问这篇').setIcon('message-circle').onClick(() => this.ask(file)));
  }
  async ask(file) {
    if (typeof this.plugin.askAboutNote !== 'function') { this.notify('「问这篇」要更新 Link Brain Actions 插件'); return false; }
    try { return await this.plugin.askAboutNote(file); }
    catch (err) { console.error('[lb] 问这篇没打开', err); this.notify('问收藏没打开：' + ((err && err.message) || err)); return false; }
  }

  // ── N17 ──
  onFileOpen(file) {
    if (!this.itemIdOf(file)) return;
    let ds = null;
    try { ds = typeof this.plugin.dataviewState === 'function' ? this.plugin.dataviewState() : null; } catch {}
    if (!ds || ds === 'ok') return;
    const MV = this.obsidian.MarkdownView;
    const view = MV && typeof this.app.workspace.getActiveViewOfType === 'function' ? this.app.workspace.getActiveViewOfType(MV) : null;
    try { this.plugin.onboardingUI().dataviewBanner(view); } catch (e) { console.error('[lb] Dataview 提示没画上', e); }
  }

  // ── N10 划重点 ──
  // 选区（在某篇归档笔记阅读视图的 .lb-scroll 里）→ {scroll, leaf, file, itemId, range, phrases:[{text, node, start, end}], mark}
  selectionContext(target = null) {
    const D = this.doc();
    if (!D) return null;
    const sel = typeof D.getSelection === 'function' ? D.getSelection() : (typeof window !== 'undefined' && window.getSelection ? window.getSelection() : null);
    const range = sel && sel.rangeCount && !sel.isCollapsed ? sel.getRangeAt(0) : null;
    const anchor = target || (range && (range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement));
    const scroll = anchor && typeof anchor.closest === 'function' ? anchor.closest('.markdown-reading-view .xhs-note .lb-scroll, .markdown-preview-view.xhs-note .lb-scroll') : null;
    if (!scroll || anchor.closest('.markdown-source-view')) return null;
    const leaf = this.leafOf(scroll);
    const file = leaf && leaf.view && leaf.view.file;
    const itemId = this.itemIdOf(file);
    if (!itemId) return null;
    const mark = target && typeof target.closest === 'function' ? target.closest('mark') : null;
    const phrases = range && scroll.contains(range.commonAncestorContainer) ? selectionPhrases(range, scroll) : [];
    return { scroll, leaf, file, itemId, range, phrases, mark: mark && scroll.contains(mark) ? mark : null };
  }
  onContextMenu(e) {
    const t = e && e.target && typeof e.target.closest === 'function' ? e.target : null;
    if (!t || t.closest('img')) return;   // 图片右键归 image-actions（F2）
    if (!t.closest('.markdown-reading-view .xhs-note .lb-scroll, .markdown-preview-view.xhs-note .lb-scroll')) return;
    const ctx = this.selectionContext(t);
    if (!ctx || (!ctx.phrases.length && !ctx.mark)) return;
    const items = [];
    if (ctx.phrases.length) items.push({ title: '划重点', icon: 'highlighter', onClick: () => this.highlight(ctx) });
    if (ctx.mark) items.push({ title: '取消重点', icon: 'eraser', onClick: () => this.unhighlight(ctx) });
    if (ctx.range) items.push({ title: '复制', icon: 'copy', onClick: () => { try { navigator.clipboard.writeText(String(ctx.range.toString())); } catch {} } });
    e.preventDefault();
    e.stopPropagation();
    if (typeof this.plugin.showMenu === 'function') { this.plugin.showMenu(items, e); return; }
    const M = this.obsidian.Menu;
    if (!M) return;
    const menu = new M();
    for (const it of items) menu.addItem(i => i.setTitle(it.title).setIcon(it.icon).onClick(it.onClick));
    menu.showAtMouseEvent(e);
  }
  async highlight(ctx) {
    const D = this.doc();
    const words = ctx.phrases.map(p => p.text);
    const all = String(ctx.scroll.textContent || '');
    for (const w of words) {
      const n = all.split(w).length - 1;
      if (n > 1) { this.notify(`这句出现了 ${n} 次，只会划第一处`); break; }
    }
    // §1.5 先乐观：每段包一层淡色 pending mark；没写上的退回
    const marks = [];
    for (const p of ctx.phrases.slice().reverse()) {
      try {
        const r = D.createRange();
        r.setStart(p.node, p.start); r.setEnd(p.node, p.end);
        const m = D.createElement('mark');
        m.className = 'lb-mark-pending';
        r.surroundContents(m);
        marks.unshift({ text: p.text, el: m });
      } catch { marks.unshift({ text: p.text, el: null }); }
    }
    try { D.getSelection && D.getSelection().removeAllRanges(); } catch {}
    let res = null;
    try { res = await this.plugin.runPy(['-m', 'link_brain', 'highlight', ctx.itemId, ...words, '--json'], { okCodes: [0, 1], timeoutMs: 30000, label: '划重点', fallback: '划重点没写上' }); }
    catch (err) { res = { json: null, error: err }; }
    const json = res && res.json;
    const ok = new Set(json && Array.isArray(json.changed) ? json.changed : []);
    for (const x of json && Array.isArray(json.already) ? json.already : []) ok.add(x);
    const failed = marks.filter(m => !ok.has(m.text));
    for (const m of failed) unwrap(m.el);
    if (!json) { this.notify('没划上：' + ((res && res.error && res.error.message) || '后台没返回结果')); return; }
    if (failed.length) this.notify(`有 ${failed.length} 段没划上：这几个字在原文里对不上（试试只选同一行里的字）`);
    // 成功的由 Obsidian 重画这一块（文件改了），钉住状态 / 正文滚动由图片导航保住
  }
  async unhighlight(ctx) {
    const phrase = String(ctx.mark && ctx.mark.textContent || '').trim();
    if (!phrase) return;
    let res = null;
    try { res = await this.plugin.runPy(['-m', 'link_brain', 'highlight', ctx.itemId, phrase, '--remove', '--json'], { okCodes: [0, 1], timeoutMs: 30000, label: '取消重点', fallback: '取消重点没写上' }); }
    catch (err) { this.notify('没取消上：' + ((err && err.message) || err)); return; }
    const json = res && res.json;
    if (!json || !json.ok) this.notify((json && json.message) || '没取消上');
  }
}

// 和选区相交、在允许范围里的文字节点，各截出选中的那段（trim 后 ≥2 个字才算一段）：自然按 <br> / span 切开
function selectionPhrases(range, scroll) {
  const D = scroll.ownerDocument || (typeof document !== 'undefined' ? document : null);
  if (!D || typeof D.createTreeWalker !== 'function') return [];
  const SHOW_TEXT = (typeof NodeFilter !== 'undefined' && NodeFilter.SHOW_TEXT) || 4;
  const walker = D.createTreeWalker(scroll, SHOW_TEXT);
  const out = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const host = n.parentElement;
    if (!host || !host.closest(PHRASE_SCOPE) || host.closest('.lb-reply-target') || host.closest('mark')) continue;
    if (typeof range.intersectsNode === 'function' && !range.intersectsNode(n)) continue;
    let start = 0, end = n.data.length;
    if (n === range.startContainer) start = range.startOffset;
    if (n === range.endContainer) end = range.endOffset;
    const raw = n.data.slice(start, end);
    const lead = raw.length - raw.trimStart().length, text = raw.trim();
    if (text.length < 2) continue;
    out.push({ text, node: n, start: start + lead, end: start + lead + text.length });
  }
  return out;
}
function unwrap(el) {
  if (!el || !el.parentNode) return;
  const parent = el.parentNode;
  while (el.firstChild) parent.insertBefore(el.firstChild, el);
  parent.removeChild(el);
  try { parent.normalize(); } catch {}
}

module.exports = (obsidian, plugin) => new NoteActions(obsidian, plugin);
module.exports.NoteActions = NoteActions;
module.exports.selectionPhrases = selectionPhrases;

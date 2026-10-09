// note-tools.js — 批次 D · L5：笔记工具。
//   F1-b 恢复这篇：⋯ 菜单 / 文件列表右键 / 命令「恢复这篇」「撤销上次恢复」「从快照找回…」（后端 restore，先存快照、可撤销）；
//   F1-d 打开改坏的笔记就地提示一次（noteDamage 与 link_brain/restore.py 的 diagnose 同口径，共用样本 tests/fixtures/note_damage_cases.json）；
//   F3-a 导出：右上角 ⋮ 菜单「导出 ▸」子菜单（PDF / 压缩包）+ 命令。1010 她：顶栏右端那个带框的「导出 ▾」删掉。
//   1010 她：笔记顶上插件那一行变成一行很轻的字「← 目录　原文↗　机读版」——「← 目录」由 markdown post-processor 注入（不烤进 md），
//   点了在这一格打开目录页（目录页自己记着刚才的滚动位置和筛选）；md 里 原文 / 机读版 之间的「·」在显示时去掉，间距交给样式。
// 插件 onload 里 require(...)(obsidian, plugin).attach()，实例在 plugin.noteTools。
'use strict';

const VIS = 'Web/Xiaohongshu/';
const CONTENT_START = '<!-- link-brain:content:start -->';
const CONTENT_END = '<!-- link-brain:content:end -->';
const COMMENTS_START = '<!-- link-brain:comments:start -->';
const COMMENTS_END = '<!-- link-brain:comments:end -->';
const ISSUE_TEXT = {
  FRONTMATTER_BROKEN: '属性（frontmatter）写坏了',
  ITEM_ID_MISSING: '属性里的 item_id 没了',
  CSSCLASSES_MISSING: '属性里的 cssclasses 没了，两栏样式会丢',
  CONTENT_MARKERS_MISSING: '正文的受管标记被删了',
  NOTE_BLOCK_MISSING: '两栏正文块没了',
  NOTE_BLOCK_SPLIT: '两栏正文块被换行拆开了',
  COMMENTS_MARKERS_MISSING: '留言层的标记被删了',
  ANNOTATE_BLOCK_MISSING: '底部的批注块没了',
};
const SNAP_REASON = { restore: '恢复前', undo: '撤销前', render: '重渲前', heal: '自愈前' };
const SOURCE_OF_PREFIX = { xhs: 'xiaohongshu' };

const FM_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/;
const ITEM_ID_RE = /^link_brain:[ \t]*\r?\n(?:[ \t]+.*\r?\n)*?[ \t]+item_id:[ \t]*([^\s#]+)/m;
const count = (s, sub) => s.split(sub).length - 1;

// 属性块写坏（Python 侧是「逐键容错 YAML 也解析不了」）：这里认最常见的那种——某行方括号 / 花括号没配对
function fmBroken(fm) {
  return fm.split(/\r?\n/).some(l => count(l, '[') !== count(l, ']') || count(l, '{') !== count(l, '}'));
}
function fmCssclasses(fm) {
  const lines = fm.split(/\r?\n/);
  const i = lines.findIndex(l => /^cssclasses\s*:/.test(l));
  if (i < 0) return null;
  const v = lines[i].replace(/^cssclasses\s*:/, '').trim();
  if (v) return v.replace(/^\[|\]$/g, '').split(',').map(x => x.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
  const out = [];
  for (let j = i + 1; j < lines.length && /^\s+-\s*/.test(lines[j]); j++) out.push(lines[j].replace(/^\s+-\s*/, '').trim().replace(/^["']|["']$/g, ''));
  return out;
}

// 与 restore.diagnose 同顺序、同口径；空数组 = 没坏。块外手写不算坏（F1-c 处理）。
function noteDamage(text) {
  text = String(text || '');
  const out = [];
  const m = FM_RE.exec(text);
  const fm = m ? m[1] : null;
  const broken = fm != null && fmBroken(fm);
  if (broken) out.push('FRONTMATTER_BROKEN');
  const hit = fm != null ? ITEM_ID_RE.exec(fm + '\n') : null;
  if (!hit || !hit[1].replace(/^["']|["']$/g, '')) out.push('ITEM_ID_MISSING');
  const cc = fm != null && !broken ? fmCssclasses(fm) : null;
  if (!cc || !cc.includes('xhs-note')) out.push('CSSCLASSES_MISSING');
  const s = text.indexOf(CONTENT_START), e = text.indexOf(CONTENT_END);
  const region = s !== -1 && e > s ? text.slice(s, e) : null;
  if (region == null) out.push('CONTENT_MARKERS_MISSING');
  const lines = (region != null ? region : text).split('\n').filter(l => l.replace(/^\s+/, '').startsWith('<div class="lb-note'));
  if (!lines.length) out.push('NOTE_BLOCK_MISSING');
  else if (count(lines[0], '<div') !== count(lines[0], '</div>')) out.push('NOTE_BLOCK_SPLIT');
  const cs = text.indexOf(COMMENTS_START), ce = text.indexOf(COMMENTS_END);
  if (cs === -1 || ce === -1 || ce < cs) out.push('COMMENTS_MARKERS_MISSING');
  const blocks = text.match(/```dataviewjs\r?\n[\s\S]*?```/g) || [];
  if (!blocks.some(b => b.includes('annotate-view.js'))) out.push('ANNOTATE_BLOCK_MISSING');
  return out;
}
const reasonText = issues => issues.map(x => ISSUE_TEXT[x] || x).join('；');

function fmtSize(n) { return n >= 1024 * 1024 ? `${Math.round(n / 1024 / 1024)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`; }

module.exports = (obsidian, plugin, deps = {}) => {
  const fs = deps.fs || require('fs');
  const path = deps.path || require('path');
  const electron = () => { if (deps.electron) return deps.electron; try { return require('electron'); } catch { return null; } };
  const doc = () => (typeof document !== 'undefined' ? document : null);
  const restoring = new Set(), exporting = new Set(), warned = new Set();
  const app = () => plugin.app;
  const prefix = () => (plugin.lbRoot ? plugin.lbRoot + '/' : '');
  const basePath = () => { try { return app().vault.adapter.getBasePath(); } catch { return ''; } };
  const absOf = rel => path.join(basePath(), plugin.lbPath ? plugin.lbPath(rel) : rel);

  // 认这篇是哪条：frontmatter.link_brain.item_id；没有但在可见目录下 → itemId:null（后端按 --path 认）
  function itemOf(file) {
    if (!file || typeof file.path !== 'string' || !/\.md$/i.test(file.path)) return null;
    let iid = null;
    try { iid = app().metadataCache.getFileCache(file)?.frontmatter?.link_brain?.item_id || null; } catch {}
    const pre = prefix();
    const inRoot = !pre || file.path.startsWith(pre);
    const rel = inRoot ? file.path.slice(pre.length) : file.path;
    if (iid) return { itemId: String(iid), file, rel };
    if (inRoot && rel.startsWith(VIS)) return { itemId: null, file, rel };
    return null;
  }
  function objectRelOf(itemId) {
    if (!itemId) return null;
    const i = String(itemId).indexOf('-');
    if (i <= 0) return null;
    const pre = itemId.slice(0, i), sid = itemId.slice(i + 1);
    return `_archive/${SOURCE_OF_PREFIX[pre] || pre}/${sid}`;
  }
  function hasSnapshots(info) {
    const rel = info && objectRelOf(info.itemId);
    if (!rel) return false;
    try { return fs.readdirSync(absOf(rel + '/history')).some(n => /^visible-.*\.txt$/.test(n)); } catch { return false; }
  }
  function videoBytes(info) {
    const rel = info && objectRelOf(info.itemId);
    if (!rel) return 0;
    try {
      const obj = absOf(rel);
      const meta = JSON.parse(fs.readFileSync(path.join(obj, 'meta.json'), 'utf8'));
      const raw = path.join(obj, 'raw', 'v' + String(meta.current_version).padStart(4, '0'));
      const man = JSON.parse(fs.readFileSync(path.join(raw, 'manifest.json'), 'utf8'));
      const v = (man.media || []).find(m => m.role === 'video' && m.download_status === 'ok' && m.file);
      if (!v) return 0;
      return fs.statSync(v.file.startsWith('raw/') ? path.join(obj, v.file) : path.join(raw, v.file)).size;
    } catch { return 0; }
  }
  const restoreArgs = (info, extra) => ['-m', 'link_brain', 'restore', ...(info.itemId ? [info.itemId] : []), '--path', info.rel, ...extra, '--json'];
  async function py(args, opts) {
    try { const r = await plugin.runPy(args, opts); return { json: r && r.json, err: r && r.err }; }
    catch (e) { return { json: e && e.result && e.result.json, err: (e && e.message) || String(e) }; }
  }
  const why = (r, dflt) => (r.json && r.json.message) || String(r.err || '').trim().split('\n').pop() || dflt;

  // 同一文件在源码模式：先存盘再切阅读视图，免得编辑器缓冲在外部改写后又盖回去
  async function settle(file) {
    let leaves = [];
    try { leaves = app().workspace.getLeavesOfType('markdown') || []; } catch {}
    for (const leaf of leaves) {
      const v = leaf.view;
      if (!v || v.file !== file) continue;
      if (typeof v.getMode === 'function' && v.getMode() === 'source') {
        try { await v.save?.(); } catch {}
        const st = leaf.getViewState();
        await leaf.setViewState({ ...st, state: { ...(st.state || {}), mode: 'preview' } });
      }
    }
  }

  async function restore(file) {
    const info = itemOf(file);
    if (!info) return null;
    if (restoring.has(file.path)) { plugin.notify('正在恢复这篇，稍等'); return null; }
    restoring.add(file.path);
    try {
      await settle(file);
      const r = await py(restoreArgs(info, []), { label: '恢复笔记', timeoutMs: 120000 });
      if (r.json && r.json.ok) {
        warned.delete(file.path);
        const snap = r.json.snapshot;
        plugin.notify(r.json.message || '已按存档恢复', { kind: 'ok', ms: 12000, actions: [{ label: '撤销', run: () => undo(file, snap) }] });
      } else plugin.notify(`没恢复：${why(r, '原因不明')}（文件没动）`, { kind: 'error' });
      return r.json;
    } finally { restoring.delete(file.path); }
  }

  async function undo(file, snapshot) {
    const info = itemOf(file);
    if (!info) return null;
    await settle(file);
    const r = await py(restoreArgs(info, ['--undo', ...(snapshot ? ['--snapshot', snapshot] : [])]), { label: '撤销恢复', timeoutMs: 60000 });
    if (r.json && r.json.ok) plugin.notify(snapshot ? '已撤销：回到恢复前那一版' : '已撤销上次恢复', { kind: 'ok' });
    else plugin.notify(`没撤销：${why(r, '原因不明')}`, { kind: 'error' });
    return r.json;
  }

  function snapLabel(s) {
    const t = String(s.ts || '');
    return `${t.slice(5, 10)} ${t.slice(11, 16)} · ${SNAP_REASON[s.reason] || s.reason || '快照'} · ${fmtSize(Number(s.bytes) || 0)}`;
  }
  async function pickSnapshot(file) {
    const info = itemOf(file);
    if (!info) return null;
    const r = await py(restoreArgs(info, ['--list']), { label: '列快照', timeoutMs: 60000 });
    const snaps = (r.json && r.json.snapshots) || [];
    if (!snaps.length) { plugin.notify(r.json ? '这篇还没有快照' : `没读到快照：${why(r, '原因不明')}`); return null; }
    const Base = obsidian.SuggestModal;
    class SnapModal extends Base {
      constructor(a) { super(a); this.setPlaceholder?.('选一份快照写回（当前这版会先存一份，可再撤销）'); }
      getSuggestions(q) { q = String(q || '').trim(); return snaps.filter(s => !q || snapLabel(s).includes(q)); }
      renderSuggestion(s, el) { el.setText ? el.setText(snapLabel(s)) : (el.textContent = snapLabel(s)); }
      onChooseSuggestion(s) { undo(file, s.name); }
    }
    const m = new SnapModal(app());
    m.open();
    return m;
  }

  async function checkDamage(file) {
    const info = itemOf(file);
    if (!info) return [];
    let text = '';
    try { text = await app().vault.cachedRead(file); } catch { return []; }
    const issues = noteDamage(text);
    if (!issues.length) { warned.delete(file.path); return issues; }
    if (warned.has(file.path)) return issues;
    warned.add(file.path);
    plugin.notify(`这篇的页面结构被改坏了（${reasonText(issues)}）。恢复会按存档重写，你写的属性、留言、重点都保留，改坏的这版先存快照，可撤销。`,
      { kind: 'warn', ms: 15000, actions: [{ label: '恢复', run: () => restore(file) }] });
    return issues;
  }

  // ── 导出 ──
  function shellOpen(p) { try { electron()?.shell?.openPath(p); } catch {} }
  function shellShow(p) { try { electron()?.shell?.showItemInFolder(p); } catch {} }
  const base = p => String(p || '').split(/[\\/]/).pop();

  async function exportNote(file, kind, btn) {
    const info = itemOf(file);
    if (!info) return null;
    if (!info.itemId) { plugin.notify('没导出：这篇属性里的 item_id 没了，先「恢复这篇」', { kind: 'error' }); return null; }
    if (exporting.has(file.path)) { plugin.notify('正在导出，稍等'); return null; }
    exporting.add(file.path);
    const label = btn ? btn.textContent : '';
    if (btn) { btn.setAttribute('aria-busy', 'true'); btn.textContent = '导出中…'; }
    const progress = plugin.notify(kind === 'pdf' ? '正在导出 PDF：排版、打印…' : '正在打包这一篇的本地资料…', { ms: 0 });
    try {
      let input = null;
      const args = ['-m', 'link_brain', 'export-note', info.itemId, kind === 'pdf' ? '--pdf' : '--zip', '--json'];
      if (kind === 'pdf') {
        let font = '';
        try { font = getComputedStyle(doc().body).getPropertyValue('--font-text').trim(); } catch {}
        args.push('--stdin');
        input = JSON.stringify({ font });
      }
      const r = await py(args, { label: kind === 'pdf' ? '导出 PDF' : '导出压缩包', timeoutMs: 600000, input });
      const j = r.json;
      try { progress?.hide?.(); } catch {}
      if (!j) { plugin.notify(`没导出：${why(r, '原因不明')}`, { kind: 'error' }); return null; }
      const name = base(j.path);
      if (kind === 'zip') {
        if (j.ok) plugin.notify(`${j.message}：${name}`, { kind: 'ok', actions: [{ label: '在文件夹中显示', run: () => shellShow(j.path) }] });
        else plugin.notify(`没导出：${j.message || '原因不明'}`, { kind: 'error' });
      } else if (j.ok && !j.fallback) {
        plugin.notify(`${j.message}：${name}`, { kind: 'ok', actions: [{ label: '打开', run: () => shellOpen(j.path) }, { label: '在文件夹中显示', run: () => shellShow(j.path) }] });
      } else if (j.ok && j.fallback === 'html') {
        plugin.notify('没找到 Edge / Chrome：已生成网页版，打开后按 Ctrl+P 另存为 PDF', { kind: 'warn', actions: [{ label: '打开网页版', run: () => shellOpen(j.path) }] });
      } else {
        plugin.notify(`没导出：${j.message || '原因不明'}`, { kind: 'error', actions: j.path ? [{ label: '打开网页版', run: () => shellOpen(j.path) }] : null });
      }
      return j;
    } finally {
      exporting.delete(file.path);
      if (btn) { btn.removeAttribute('aria-busy'); btn.textContent = label || '导出'; }
    }
  }
  const exportPdf = (file, btn) => exportNote(file, 'pdf', btn);
  const exportZip = (file, btn) => exportNote(file, 'zip', btn);

  function zipTitle(info, short = false) {
    const n = videoBytes(info);
    return (short ? '压缩包（这一篇的全部本地资料）' : '导出压缩包（这一篇的全部本地资料）') + (n ? ` · 含视频 ${fmtSize(n)}` : '');
  }
  // 导出的几种格式：⋮ 菜单「导出 ▸」的子菜单（Obsidian 1.14 的 MenuItem.setSubmenu）；没有子菜单的老版本退回两项平铺
  function addExportItems(menu, file, info) {
    let sub = null;
    menu.addItem(item => {
      item.setTitle('导出').setIcon?.('download');
      try { sub = typeof item.setSubmenu === 'function' ? item.setSubmenu() : null; } catch { sub = null; }
      if (!sub) item.setTitle('导出 PDF（和页面一样）').setIcon?.('file-text').onClick(() => exportPdf(file));
    });
    if (sub) {
      sub.addItem(i => i.setTitle('PDF（和页面一样）').setIcon?.('file-text').onClick(() => exportPdf(file)));
      sub.addItem(i => i.setTitle(zipTitle(info, true)).setIcon?.('package').onClick(() => exportZip(file)));
    } else menu.addItem(i => i.setTitle(zipTitle(info)).setIcon?.('package').onClick(() => exportZip(file)));
    return sub;
  }

  // 笔记在哪一格（点「← 目录」就在这一格打开目录页）
  function leafOfEl(el) {
    let leaves = [];
    try { leaves = app().workspace.getLeavesOfType('markdown') || []; } catch {}
    return leaves.find(l => { const c = l && l.view && l.view.containerEl; return c && typeof c.contains === 'function' && c.contains(el); }) || null;
  }
  async function backToCatalog(el, evt) {
    const ws = app().workspace;
    const leaf = evt && (evt.ctrlKey || evt.metaKey) && typeof ws.getLeaf === 'function' ? ws.getLeaf('tab') : leafOfEl(el);
    try { await plugin.openLibraryPage('catalog', leaf || null); }
    catch (err) { console.error('[lb] 目录没打开', err); plugin.notify('目录没打开：' + ((err && err.message) || err), { kind: 'error' }); }
  }

  // 顶栏 callout（「原文 · 机读版」那一行）：最左插一个「← 目录」，去掉中间的「·」（幂等；只对归档笔记）。
  // 老版本插件留下的「导出 ▾」按钮（热重载时还在页面上）顺手摘掉。
  function postProcess(el, ctx) {
    if (!el || !el.querySelectorAll) return;
    const sp = (ctx && ctx.sourcePath) || '';
    const ok = !!(ctx && ctx.frontmatter && ctx.frontmatter.link_brain && ctx.frontmatter.link_brain.item_id)
      || (sp && sp.slice(prefix().length).startsWith(VIS) && (!prefix() || sp.startsWith(prefix())));
    if (!ok) return;
    const callouts = [...(el.matches && el.matches('.callout[data-callout="lb-topbar"]') ? [el] : []), ...el.querySelectorAll('.callout[data-callout="lb-topbar"]')];
    for (const c of callouts) {
      const content = c.querySelector('.callout-content');
      if (!content) continue;
      for (const old of [...content.querySelectorAll('.lb-topbar-tools')]) old.remove();
      const row = content.querySelector('p') || content;
      row.classList.add('lb-topbar-row');
      for (const n of [...row.childNodes]) if (n.nodeType === 3 && /^[\s·•]*$/.test(n.textContent || '')) n.remove();
      if (row.querySelector('.lb-topbar-back')) continue;
      const D = row.ownerDocument || doc();
      const a = D.createElement('a');
      a.className = 'lb-topbar-back';
      a.textContent = '← 目录';
      a.setAttribute('role', 'link');
      a.setAttribute('tabindex', '0');
      a.setAttribute('aria-label', '回到目录页（停在刚才看的位置）');
      a.addEventListener('click', e => { try { e.preventDefault(); e.stopPropagation(); } catch {} backToCatalog(a, e); });
      a.addEventListener('keydown', e => { if (e.key !== 'Enter' && e.key !== ' ') return; try { e.preventDefault(); } catch {} backToCatalog(a, e); });
      row.insertBefore(a, row.firstChild);
    }
  }

  // ⋮ 菜单 / 文件列表右键 / 标签页右键：导出 ▸（PDF / 压缩包）· 恢复这篇 · 从快照找回…
  function fileMenu(menu, file, source) {
    const info = itemOf(file);
    if (!info) return;
    menu.addSeparator?.();
    if (info.itemId) addExportItems(menu, file, info);
    menu.addItem(i => i.setTitle('恢复这篇（按存档重写，可撤销）').setIcon?.('history').onClick(() => restore(file)));
    if (hasSnapshots(info)) menu.addItem(i => i.setTitle('从快照找回…').setIcon?.('archive-restore').onClick(() => pickSnapshot(file)));
  }

  const activeFile = () => { try { return app().workspace.getActiveFile(); } catch { return null; } };
  const cmd = (id, name, fn, need = () => true) => plugin.addCommand({
    id, name, checkCallback: checking => {
      const f = activeFile(), info = itemOf(f);
      if (!info || !need(info)) return false;
      if (!checking) fn(f);
      return true;
    },
  });

  const inst = {
    attach() {
      plugin.registerMarkdownPostProcessor?.((el, ctx) => postProcess(el, ctx));
      const ws = app().workspace;
      if (ws && ws.on) {
        plugin.registerEvent(ws.on('file-menu', (menu, file, source) => fileMenu(menu, file, source)));
        plugin.registerEvent(ws.on('file-open', file => { if (file) checkDamage(file).catch?.(() => {}); }));
        plugin.registerEvent(ws.on('layout-change', () => {
          let leaves = [];
          try { leaves = ws.getLeavesOfType('markdown') || []; } catch {}
          for (const leaf of leaves) {
            const v = leaf.view, mode = v && typeof v.getMode === 'function' ? v.getMode() : null;
            if (leaf.__lbMode === 'source' && mode === 'preview' && v.file) checkDamage(v.file).catch?.(() => {});
            leaf.__lbMode = mode;
          }
        }));
      }
      cmd('restore-note', '恢复当前笔记（按存档重写，可撤销）', restore);
      cmd('restore-note-undo', '撤销上次恢复', f => undo(f));
      cmd('restore-note-snapshot', '从快照找回当前笔记…', pickSnapshot);
      cmd('export-note-pdf', '导出当前笔记为 PDF', f => exportPdf(f), i => !!i.itemId);
      cmd('export-note-zip', '导出当前笔记为压缩包', f => exportZip(f), i => !!i.itemId);
    },
    restore, undo, pickSnapshot, exportPdf, exportZip, checkDamage, noteDamage, itemOf, backToCatalog,
    _internals: { postProcess, fileMenu, addExportItems, hasSnapshots, videoBytes, snapLabel, reasonText, warned, restoring, exporting },
  };
  return inst;
};
module.exports.noteDamage = noteDamage;

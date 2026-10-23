// 回收站页（批次 D · C16 / X9）：lb-page-lib.js 由 remove.publish_trash 内联在本文件前面（和目录页同一套前导）。
// 页面挂在 dv.container 后面的 host 上（Dataview 重跑不闪）；样式挂 head 的 #lb-trash-style；
// 动作有「恢复中… / 删除中…」、页内确认、成功 / 失败都走 Notice（不用 window.alert / confirm）；手机只读。
const LB = lbPageLib(dv, app, 'trash');
if (await LB.reuseDom()) return;
const root = dv.container;
const TRASH = '_archive/trash-data.json';
{ const pane = root.closest && root.closest('.markdown-preview-view, .markdown-source-view'); if (pane) pane.classList.add('lb-trashpage'); }
LB.style('lb-trash-style', `
.lb-trashpage .markdown-preview-sizer,.lb-trashpage .markdown-preview-section,.lb-trashpage .cm-sizer,.lb-trashpage .cm-contentContainer,.lb-trashpage .cm-content,.lb-trashpage .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-trashpage .inline-title,.lb-trashpage .metadata-container{display:none!important;}
/* C1 同理：Dataview 的行内 overflow-x:auto、实时预览 :hover{overflow:hidden} 会让页头吸顶失效 */
.lb-trashpage .block-language-dataviewjs{overflow:visible!important;}
.markdown-source-view.lb-trashpage .cm-embed-block.cm-lang-dataviewjs,.markdown-source-view.lb-trashpage .cm-embed-block.cm-lang-dataviewjs:hover{overflow:visible!important;}
/* 10-04（她定）整页外面那层 dataviewjs 代码块的框隐形 */
.lb-trashpage :is(.el-pre:has(.block-language-dataviewjs),pre:has(.block-language-dataviewjs),.block-language-dataviewjs,.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs),.lb-trashpage :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs):hover{border:0!important;background:transparent!important;box-shadow:none!important;outline:0!important;border-radius:0!important;}
.lb-trashpage :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-lang-dataviewjs) .edit-block-button{display:none!important;}
.lbt-wrap{max-width:820px;margin:0 auto;padding:22px 16px 40px;box-sizing:border-box;font-family:"Noto Sans SC","Segoe UI","Microsoft YaHei UI",sans-serif;}
.lbt-head{position:sticky;top:0;z-index:2;background:var(--background-primary);display:grid;grid-template-columns:1fr auto;align-items:center;gap:12px 16px;padding:0 0 12px;}
.lbt-title{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:30px;font-weight:700;line-height:1.1;}
.lbt-wrap .lb-page-nav{grid-column:1;grid-row:2;justify-self:start;padding:0;background:transparent;}
.lbt-tools{grid-column:2;grid-row:1;justify-self:end;}
.lbt-note{grid-column:1/-1;font-size:12px;line-height:1.6;color:var(--text-muted);margin:0;}
.lbt-row{display:flex;gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid var(--background-modifier-border);position:relative;}
.lbt-row.is-busy{opacity:.6;}
.lbt-cover{flex:0 0 64px;width:64px;height:72px;object-fit:cover;border-radius:8px;background:var(--background-secondary);}
.lbt-text{flex:1;min-width:0;}
.lbt-name{font-size:14px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbt-meta{font-size:12px;color:var(--text-muted);margin-top:2px;}
.lbt-actions{display:flex;gap:8px;flex:none;}
.lbt-actions{align-items:center;}
/* 1023：红色保留，但不要整块实心红（Obsidian 的 mod-warning 底色 + 我们的红字 = 按钮上看不见字）：红字红框、底透明，悬停才浅红底 */
.lbt-wrap button.lbt-danger{background:transparent!important;color:var(--lb-danger,#e03e3e)!important;border:1px solid var(--lb-danger,#e03e3e)!important;box-shadow:none!important;}
.lbt-wrap button.lbt-danger:hover{background:rgba(224,62,62,.08)!important;}
.lbt-tools{display:flex;gap:10px;align-items:center;}
/* 已彻底删除的记录：收进右上角一个小图标，点开才看；可选中重新导入，可切瀑布流 / 目录 */
.lbt-wrap button.lbt-rec-btn{display:inline-flex;align-items:center;gap:6px;background:transparent!important;box-shadow:none!important;border:1px solid var(--background-modifier-border)!important;color:var(--text-muted);font-size:12px;}
.lbt-wrap button.lbt-rec-btn.is-on{color:var(--text-normal);border-color:var(--text-normal)!important;}
.lbt-wrap button.lbt-rec-btn svg{width:14px;height:14px;}
.lbt-recs{margin:6px 0 22px;padding:14px 0 6px;border-top:1px solid var(--text-normal);}
.lbt-recs[hidden]{display:none!important;}
.lbt-recs-bar{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin-bottom:12px;font-size:12px;color:var(--text-muted);}
.lbt-recs-bar .lbt-sp{flex:1;}
.lbt-seg{display:inline-flex;padding:2px;border-radius:999px;background:var(--background-secondary);}
.lbt-wrap .lbt-seg button{height:auto!important;padding:4px 12px!important;border:0!important;border-radius:999px!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);font-size:12px;transition:background .15s,color .15s;}
.lbt-wrap .lbt-seg button.is-on{background:var(--text-normal)!important;color:var(--background-primary)!important;}
.lbt-recs-list.is-grid{columns:3 180px;column-gap:12px;}
.lbt-rec{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--background-modifier-border);cursor:pointer;font-size:13px;break-inside:avoid;}
.lbt-recs-list.is-grid .lbt-rec{flex-direction:column;gap:6px;padding:12px;margin:0 0 12px;border:1px solid var(--background-modifier-border);border-radius:10px;}
.lbt-recs-list.is-grid .lbt-rec.is-sel{border-color:var(--text-normal);}
.lbt-rec input{margin:3px 0 0;flex:none;}
.lbt-rec-t{flex:1;min-width:0;line-height:1.5;}
.lbt-rec-d{font-size:12px;color:var(--text-muted);white-space:nowrap;}
.lbt-empty{padding:40px 0;color:var(--text-muted);}
.lbt-empty-sub{font-size:12px;color:var(--text-faint);margin-top:6px;}
`);
const mount = LB.mountHost('lbt-host');
const wrap = mount.createEl('div', { cls: 'lbt-wrap' });
const head = wrap.createEl('div', { cls: 'lbt-head' });
head.createEl('div', { cls: 'lbt-title', text: '回收站' });
const tools = head.createEl('div', { cls: 'lbt-tools' });
const nav = head.createEl('nav', { cls: 'lb-page-nav' });
nav.createEl('button', { text: '浏览收藏' }).onclick = () => LB.openPage('catalog');
nav.createEl('button', { text: '问收藏' }).onclick = () => LB.openPage('chat');
head.createEl('p', { cls: 'lbt-note', text: LB.mobile ? LB.MOBILE_ONLY_TEXT : '在这里彻底删除的收藏不会再同步。建议在「设置 → 文件与链接 → 排除的文件」加 _trash' });
const recsBox = wrap.createEl('div', { cls: 'lbt-recs' }); recsBox.hidden = true;
const list =wrap.createEl('div', { cls: 'lbt-list' });
let busy = false;
// 吸顶的 top 取滚动容器上内边距的负值（主审裁决 1，同目录页）
function paintStickyTop() {
  const sc = LB.scroller(); if (!sc) return;
  let pad = 0;
  try { pad = parseFloat((typeof getComputedStyle === 'function' ? getComputedStyle(sc) : null)?.paddingTop) || 0; } catch {}
  head.style.top = pad ? `${-pad}px` : '0px';
}
async function readData() {
  try { const d = JSON.parse(await app.vault.adapter.read(LB.path(TRASH))); return d && Array.isArray(d.items) ? d : null; }
  catch { return null; }
}
async function act(kind, item, btn, row) {
  if (busy || LB.mobile) return;
  const name = item ? '《' + (item.title || '未命名收藏') + '》' : '';
  if (kind === 'purge' && !(await LB.confirm({ title: `彻底删除${name}的文件？`, body: '不能恢复；以后也不会再同步。', ok: '彻底删除', danger: true }))) return;
  if (kind === 'empty' && !(await LB.confirm({ title: '清空回收站？', body: '回收站里所有收藏的文件都会彻底删除，不能恢复；以后也不会再同步。', ok: '清空', danger: true }))) return;
  const p = LB.need('trashAction'); if (!p) return;
  busy = true;
  const done = LB.busy(btn, kind === 'restore' ? '恢复中…' : '删除中…');
  row?.classList.add('is-busy');
  try {
    const r = await p.trashAction(kind, item ? [item.item_id] : []);
    done();
    if (kind === 'restore') {
      row?.remove();
      items = items.filter(x => x !== item); paintClear();
      const note = (r?.results || []).find(x => x.item_id === item.item_id)?.visible_note || '';
      LB.say(`已恢复${name}，回到目录了`, { kind: 'ok', actions: note ? [{ label: '打开', run: () => app.workspace.openLinkText(LB.path(note), '', false) }] : [] });
    } else if (kind === 'purge') {
      row?.classList.remove('is-busy');
      item.has_files = false; item.restorable = false;
      row?.remove();   // 1023：彻底删除的不再摆在列表里，收进「记录」小图标
      LB.say('已彻底删除 1 篇，不会再同步', { kind: 'ok' });
      paintClear(); paintRecs();
    } else {
      LB.say('回收站清空了，这些不会再同步', { kind: 'ok' });
      await draw();
    }
  } catch (e) {
    done(); row?.classList.remove('is-busy');
    LB.say((kind === 'restore' ? '没恢复上：' : '没删掉：') + (e?.message || e), { kind: 'error' });
  } finally { busy = false; }
}
let items = [];
// 1023：已彻底删除的只剩一条屏蔽记录（防止再同步回来）——平时不摆在列表里，收进右上角「记录」小图标
let recsOpen = false, recsView = 'list';
const recSel = new Set();
try { recsView = sessionStorage.getItem('lbt-recs-view') === 'grid' ? 'grid' : 'list'; } catch {}
const records = () => items.filter(x => !x.has_files);
function paintClear() {
  tools.empty();
  const recs = records();
  if (recs.length) {
    const rb = tools.createEl('button', { cls: 'lbt-rec-btn' + (recsOpen ? ' is-on' : ''), attr: { title: '已彻底删除的记录（不会再同步）', 'aria-pressed': String(recsOpen) } }); rb.type = 'button';
    rb.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4"/></svg>';
    rb.append(String(recs.length));
    rb.onclick = () => { recsOpen = !recsOpen; paintClear(); paintRecs(); };
  }
  if (LB.mobile || !items.some(x => x.has_files)) return;
  const clear = tools.createEl('button', { text: '清空回收站', cls: 'lbt-danger' }); clear.type = 'button';
  clear.onclick = () => act('empty', null, clear, null);
}
function paintRecs() {
  const recs = records();
  recsBox.hidden = !recsOpen || !recs.length;
  recsBox.empty();
  if (recsBox.hidden) return;
  for (const id of [...recSel]) if (!recs.some(x => x.item_id === id)) recSel.delete(id);
  const bar = recsBox.createEl('div', { cls: 'lbt-recs-bar' });
  bar.createEl('span', { text: `已彻底删除 ${recs.length} 篇 · 不会再同步；选中可以重新导入` });
  bar.createEl('span', { cls: 'lbt-sp' });
  const seg = bar.createEl('div', { cls: 'lbt-seg' });
  for (const [k, label] of [['grid', '瀑布流'], ['list', '目录']]) {
    const b = seg.createEl('button', { text: label, cls: recsView === k ? 'is-on' : '' }); b.type = 'button';
    b.onclick = () => { recsView = k; try { sessionStorage.setItem('lbt-recs-view', k); } catch {} paintRecs(); };
  }
  if (!LB.mobile) {
    const imp = bar.createEl('button', { text: recSel.size ? `重新导入 ${recSel.size} 篇` : '重新导入' }); imp.type = 'button';
    imp.disabled = !recSel.size || busy;
    imp.onclick = () => reimport(imp);
  }
  const box = recsBox.createEl('div', { cls: 'lbt-recs-list ' + (recsView === 'grid' ? 'is-grid' : 'is-list') });
  for (const item of recs) {
    const on = recSel.has(item.item_id);
    const r = box.createEl('label', { cls: 'lbt-rec' + (on ? ' is-sel' : '') });
    const cb = r.createEl('input', { type: 'checkbox' }); cb.checked = on; cb.disabled = LB.mobile;
    cb.onchange = () => { if (cb.checked) recSel.add(item.item_id); else recSel.delete(item.item_id); paintRecs(); };
    r.createEl('span', { cls: 'lbt-rec-t', text: item.title || '未命名收藏' });
    const day = typeof item.deleted_at === 'string' ? item.deleted_at.slice(0, 10) : '';
    if (day) r.createEl('span', { cls: 'lbt-rec-d', text: day + ' 删除' });
  }
}
// 重新导入：先解除屏蔽记录（trash forget），再按原链接走正常导入
async function reimport(btn) {
  if (busy || !recSel.size) return;
  const p = LB.need('trashAction'); if (!p) return;
  const picked = records().filter(x => recSel.has(x.item_id));
  if (!(await LB.confirm({ title: `重新导入 ${picked.length} 篇？`, body: '会解除「不再同步」，按原链接重新抓一次。', ok: '重新导入' }))) return;
  busy = true;
  const done = LB.busy(btn, '导入中…');
  try {
    const r = await p.trashAction('forget', picked.map(x => x.item_id));
    const urls = (r?.results || []).filter(x => x.status === 'forgotten' && x.url).map(x => x.url);
    recSel.clear();
    if (urls.length && typeof p.importText === 'function') await p.importText(urls.join('\n'));
    done();
    LB.say(urls.length ? `已重新导入 ${urls.length} 篇` : '没有可导入的链接', { kind: urls.length ? 'ok' : 'warn' });
    await draw();
  } catch (e) { done(); LB.say('没导入上：' + (e?.message || e), { kind: 'error' }); }
  finally { busy = false; }
}
async function draw() {
  const data = await readData();
  list.empty();
  items = data ? data.items : [];
  paintClear(); paintRecs();
  if (!data) {
    const box = list.createEl('div', { cls: 'lbt-empty' });
    box.createEl('div', { text: '回收站还没有数据：刷新一次目录就会生成' });
    if (!LB.mobile) {
      const b = box.createEl('button', { text: '刷新目录' }); b.type = 'button';
      b.onclick = async () => { const p = LB.need('refreshCatalog'); if (!p) return; const done = LB.busy(b, '正在刷新目录…'); try { await p.refreshCatalog(); done(); await draw(); } catch (e) { done(); LB.say('目录没刷新上：' + (e?.message || e), { kind: 'error' }); } };
    }
    return;
  }
  const live = items.filter(x => x.has_files);
  if (!live.length) {
    const box = list.createEl('div', { cls: 'lbt-empty' });
    box.createEl('div', { text: '回收站是空的' });
    box.createEl('div', { cls: 'lbt-empty-sub', text: '删除的收藏会先放在这里，可以恢复' });
    return;
  }
  for (const item of live) {
    const row = list.createEl('div', { cls: 'lbt-row' });
    if (item.cover && item.has_files) { const img = row.createEl('img', { cls: 'lbt-cover' }); img.alt = ''; img.loading = 'lazy'; img.src = app.vault.adapter.getResourcePath(LB.path(item.cover)); }
    const text = row.createEl('div', { cls: 'lbt-text' });
    text.createEl('div', { cls: 'lbt-name', text: item.title || '未命名收藏' });
    const day = typeof item.deleted_at === 'string' ? item.deleted_at.slice(0, 10) : '';
    const why = item.restorable ? '' : item.has_files ? '旧孤儿笔记，归档缺失' : '文件已彻底删除';
    text.createEl('div', { cls: 'lbt-meta', text: [day && `${day} 删除`, why].filter(Boolean).join(' · ') });
    if (LB.mobile) continue;
    const actions = row.createEl('div', { cls: 'lbt-actions' });
    if (item.restorable) { const b = actions.createEl('button', { text: '恢复' }); b.type = 'button'; b.onclick = () => act('restore', item, b, row); }
    if (item.has_files) { const b = actions.createEl('button', { text: '彻底删除', cls: 'lbt-danger' }); b.type = 'button'; b.onclick = () => act('purge', item, b, row); }
    if (!actions.children.length) actions.remove();
  }
}
await draw();
paintStickyTop();
// 动作完成后 Python 会重建 trash-data；下一次 Dataview 重跑版本变了就重读重画（版本没变原样挂回）
LB.keep(wrap, { version: await LB.data.version(TRASH), versionOf: TRASH, update: () => draw(), onReuse: () => paintStickyTop() });

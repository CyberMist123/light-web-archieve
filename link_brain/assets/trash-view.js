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
.lbt-actions button.mod-warning{color:var(--lb-danger);}
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
head.createEl('p', { cls: 'lbt-note', text: LB.mobile ? LB.MOBILE_ONLY_TEXT : '删除的收藏不会再同步；彻底删除后只留一条记录，防止重新同步。建议在「设置 → 文件与链接 → 排除的文件」加 _trash' });
const list = wrap.createEl('div', { cls: 'lbt-list' });
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
  if (kind === 'empty' && !(await LB.confirm({ title: '清空回收站？', body: '回收站里所有收藏的文件都会彻底删除，不能恢复；记录保留，以后也不会再同步。', ok: '清空', danger: true }))) return;
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
      row?.querySelector('.lbt-actions')?.remove();
      const meta = row?.querySelector('.lbt-meta'); if (meta) meta.textContent = '文件已彻底删除';
      item.has_files = false; item.restorable = false;
      LB.say('已彻底删除 1 篇（记录保留，不会再同步）', { kind: 'ok' });
      paintClear();
    } else {
      LB.say('回收站清空了（记录保留，不会再同步）', { kind: 'ok' });
      await draw();
    }
  } catch (e) {
    done(); row?.classList.remove('is-busy');
    LB.say((kind === 'restore' ? '没恢复上：' : '没删掉：') + (e?.message || e), { kind: 'error' });
  } finally { busy = false; }
}
let items = [];
function paintClear() {
  tools.empty();
  if (LB.mobile || !items.some(x => x.has_files)) return;
  const clear = tools.createEl('button', { text: '清空回收站', cls: 'mod-warning' }); clear.type = 'button';
  clear.onclick = () => act('empty', null, clear, null);
}
async function draw() {
  const data = await readData();
  list.empty();
  items = data ? data.items : [];
  paintClear();
  if (!data) {
    const box = list.createEl('div', { cls: 'lbt-empty' });
    box.createEl('div', { text: '回收站还没有数据：刷新一次目录就会生成' });
    if (!LB.mobile) {
      const b = box.createEl('button', { text: '刷新目录' }); b.type = 'button';
      b.onclick = async () => { const p = LB.need('refreshCatalog'); if (!p) return; const done = LB.busy(b, '正在刷新目录…'); try { await p.refreshCatalog(); done(); await draw(); } catch (e) { done(); LB.say('目录没刷新上：' + (e?.message || e), { kind: 'error' }); } };
    }
    return;
  }
  if (!items.length) {
    const box = list.createEl('div', { cls: 'lbt-empty' });
    box.createEl('div', { text: '回收站是空的' });
    box.createEl('div', { cls: 'lbt-empty-sub', text: '删除的收藏会先放在这里，可以恢复' });
    return;
  }
  for (const item of items) {
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
    if (item.has_files) { const b = actions.createEl('button', { text: '彻底删除', cls: 'mod-warning' }); b.type = 'button'; b.onclick = () => act('purge', item, b, row); }
    if (!actions.children.length) actions.remove();
  }
}
await draw();
paintStickyTop();
// 动作完成后 Python 会重建 trash-data；下一次 Dataview 重跑版本变了就重读重画（版本没变原样挂回）
LB.keep(wrap, { version: await LB.data.version(TRASH), versionOf: TRASH, update: () => draw(), onReuse: () => paintStickyTop() });

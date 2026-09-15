// 笔记底部批注块（Owner 2026-09-16）。每篇可见笔记末尾烤一段 bootstrap 载入本文件。
// 正文照常渲染在上面，这块只挂最底下；批注/⭐ 都存 sidecar notes.json，绝不写进正文。
// 入参：(dv, app, itemId, notePath)  notePath = _archive/<source>/<source_id>/notes.json
// ⭐ 收藏（复制正文到 vault 根）走插件跑 Python；纯批注前端直接写 sidecar。
const root = dv.container;
root.classList.add('lba-annot-host');
// Notice 在 dataviewjs 里不保证是全局，包一层兜底（跟 catalog-view 的谨慎一致）
const notify = (m) => { try { new Notice(m); } catch { console.log('[annot]', m); } };

const style = root.createEl('style');
style.textContent = `
.lba-annot{margin-top:22px;padding-top:14px;border-top:1px solid var(--background-modifier-border);font-family:var(--font-interface),sans-serif;}
.lba-annot-head{display:flex;align-items:center;gap:10px;margin-bottom:8px;}
.lba-annot-title{font-size:13px;font-weight:600;color:var(--text-normal);}
.lba-star{cursor:pointer;font-size:18px;line-height:1;user-select:none;filter:grayscale(1);opacity:.5;transition:.12s;}
.lba-star.is-on{filter:none;opacity:1;}
.lba-star:hover{opacity:.85;}
.lba-star-hint{font-size:11px;color:var(--text-muted);}
.lba-annot-list{display:flex;flex-direction:column;gap:8px;margin-bottom:10px;}
.lba-annot-item{background:var(--background-secondary);border-radius:10px;padding:8px 11px;font-size:13px;line-height:1.6;color:var(--text-normal);white-space:pre-wrap;word-break:break-word;position:relative;}
.lba-annot-item .lba-ts{display:block;font-size:11px;color:var(--text-muted);margin-bottom:2px;}
.lba-annot-item.is-fable{border-left:3px solid var(--interactive-accent);}
.lba-annot-item .lba-fable-tag{font-size:10px;color:var(--interactive-accent);font-weight:600;margin-left:6px;}
.lba-annot-item .lba-del{position:absolute;top:6px;right:8px;cursor:pointer;color:var(--text-faint);font-size:12px;opacity:0;transition:.12s;}
.lba-annot-item:hover .lba-del{opacity:1;}
.lba-annot-empty{font-size:12.5px;color:var(--text-muted);cursor:text;padding:6px 0;}
.lba-annot-editor{display:none;flex-direction:column;gap:8px;}
.lba-annot-editor.is-open{display:flex;}
.lba-annot-editor textarea{width:100%;min-height:60px;resize:vertical;border:1px solid var(--background-modifier-border);border-radius:10px;padding:8px 11px;font:inherit;font-size:13px;background:var(--background-primary);color:var(--text-normal);box-sizing:border-box;}
.lba-annot-bar{display:flex;gap:8px;align-items:center;}
.lba-annot-bar button{cursor:pointer;}
.lba-annot-bar .lba-tip{font-size:11px;color:var(--text-muted);}
`;

const box = root.createEl('div', { cls: 'lba-annot' });
const head = box.createEl('div', { cls: 'lba-annot-head' });
head.createEl('span', { cls: 'lba-annot-title', text: '批注' });
const star = head.createEl('span', { cls: 'lba-star', text: '★' });
star.title = '点亮 = 收藏（复制到 vault 根，可随手删）';
const starHint = head.createEl('span', { cls: 'lba-star-hint' });

const list = box.createEl('div', { cls: 'lba-annot-list' });
const empty = box.createEl('div', { cls: 'lba-annot-empty', text: '双击这里写批注…（@fable 开头 = 给 Fable 的留言）' });
const editor = box.createEl('div', { cls: 'lba-annot-editor' });
const ta = editor.createEl('textarea');
ta.placeholder = '写点什么…（@fable 开头 = 留言给 Fable，先只记着）';
const bar = editor.createEl('div', { cls: 'lba-annot-bar' });
const saveBtn = bar.createEl('button', { text: '保存', cls: 'mod-cta' });
const cancelBtn = bar.createEl('button', { text: '收起' });
bar.createEl('span', { cls: 'lba-tip', text: '⌘/Ctrl+Enter 保存' });

let data = { starred: false, annotations: [] };

async function load() {
  try { data = JSON.parse(await app.vault.adapter.read(notePath)); }
  catch { data = { starred: false, annotations: [] }; }
  data.starred = !!data.starred;
  data.annotations = Array.isArray(data.annotations) ? data.annotations : [];
}
async function persist() {
  await app.vault.adapter.write(notePath, JSON.stringify(data, null, 2) + '\n');
}
function fmtTs(ts) {
  try { const d = new Date(ts); return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; }
  catch { return ts || ''; }
}
function renderStar() {
  star.classList.toggle('is-on', data.starred);
  starHint.setText(data.starred ? '已收藏' : '');
}
function renderList() {
  list.empty();
  const items = data.annotations;
  empty.style.display = items.length ? 'none' : '';
  for (let i = 0; i < items.length; i++) {
    const a = items[i];
    const el = list.createEl('div', { cls: 'lba-annot-item' + (a.to_fable ? ' is-fable' : '') });
    const ts = el.createEl('span', { cls: 'lba-ts', text: fmtTs(a.ts) });
    if (a.to_fable) ts.createEl('span', { cls: 'lba-fable-tag', text: '给 Fable' });
    el.appendText(a.text || '');
    const del = el.createEl('span', { cls: 'lba-del', text: '✕' });
    del.title = '删这条批注';
    del.onclick = async () => { data.annotations.splice(i, 1); await persist(); renderList(); };
  }
}
function openEditor() { editor.classList.add('is-open'); ta.focus(); }
function closeEditor() { editor.classList.remove('is-open'); ta.value = ''; }

empty.ondblclick = openEditor;
list.ondblclick = openEditor;
cancelBtn.onclick = closeEditor;
saveBtn.onclick = async () => {
  const text = ta.value.trim();
  if (!text) { closeEditor(); return; }
  const to_fable = text.toLowerCase().startsWith('@fable');
  data.annotations.push({ ts: new Date().toISOString(), text, to_fable });
  await persist();
  closeEditor(); renderList();
};
ta.onkeydown = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); saveBtn.click(); } };

star.onclick = async () => {
  const next = !data.starred;
  const provider = app.plugins.plugins['link-brain-actions'];
  if (typeof provider?.starNote !== 'function') { notify('收藏需要启用 Link Brain Actions 插件'); return; }
  star.style.pointerEvents = 'none';
  try {
    const r = await provider.starNote(itemId, next);
    data.starred = (r && typeof r.starred === 'boolean') ? r.starred : next;
    renderStar();
    notify(data.starred ? `已收藏 → ${r?.copy_path || 'vault 根'}` : '已取消收藏（删掉副本）');
  } catch (e) { notify('收藏失败：' + (e.message || e)); }
  finally { star.style.pointerEvents = ''; }
};

await load();
renderStar();
renderList();

// 笔记底部批注块（Owner 2026-09-16）。每篇可见笔记末尾烤一段 bootstrap 载入本文件。
// 正文照常渲染在上面，这块只挂最底下；批注/⭐ 都存 sidecar notes.json，绝不写进正文。
// 入参：(dv, app, itemId, notePath)  notePath = _archive/<source>/<source_id>/notes.json
// 自动保存：边打字边存草稿（防丢），失焦 / Ctrl+Enter 落成一条批注。⭐ 收藏走插件跑 Python。
const root = dv.container;
root.classList.add('lba-annot-host');
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
.lba-save-hint{margin-left:auto;font-size:11px;color:var(--text-faint);transition:opacity .2s;}
.lba-annot-list{display:flex;flex-direction:column;gap:8px;margin-bottom:10px;}
.lba-annot-item{background:var(--background-secondary);border-radius:10px;padding:8px 11px;font-size:13px;line-height:1.6;color:var(--text-normal);white-space:pre-wrap;word-break:break-word;position:relative;}
.lba-annot-item .lba-ts{display:block;font-size:11px;color:var(--text-muted);margin-bottom:2px;}
.lba-annot-item.is-fable{border-left:3px solid var(--interactive-accent);}
.lba-annot-item .lba-fable-tag{font-size:10px;color:var(--interactive-accent);font-weight:600;margin-left:6px;}
.lba-annot-item .lba-del{position:absolute;top:6px;right:8px;cursor:pointer;color:var(--text-faint);font-size:12px;opacity:0;transition:.12s;}
.lba-annot-item:hover .lba-del{opacity:1;}
.lba-annot-input{width:100%;min-height:44px;resize:vertical;border:1px solid var(--background-modifier-border);border-radius:10px;padding:8px 11px;font:inherit;font-size:13px;background:var(--background-primary);color:var(--text-normal);box-sizing:border-box;}
.lba-annot-input:focus{border-color:var(--interactive-accent);outline:none;}
`;

const box = root.createEl('div', { cls: 'lba-annot' });
const head = box.createEl('div', { cls: 'lba-annot-head' });
head.createEl('span', { cls: 'lba-annot-title', text: '批注' });
const star = head.createEl('span', { cls: 'lba-star', text: '★' });
star.title = '点亮 = 收藏（复制到 vault 根，可随手删）';
const starHint = head.createEl('span', { cls: 'lba-star-hint' });
const saveHint = head.createEl('span', { cls: 'lba-save-hint' });

const list = box.createEl('div', { cls: 'lba-annot-list' });
const ta = box.createEl('textarea', { cls: 'lba-annot-input' });
ta.placeholder = '写批注…（自动保存；换行继续写，写完点别处即落一条。@fable 开头 = 留言给 Fable）';

let data = { starred: false, annotations: [], draft: '' };

async function load() {
  try { data = JSON.parse(await app.vault.adapter.read(notePath)); }
  catch { data = { starred: false, annotations: [], draft: '' }; }
  data.starred = !!data.starred;
  data.annotations = Array.isArray(data.annotations) ? data.annotations : [];
  data.draft = typeof data.draft === 'string' ? data.draft : '';
}
async function persist() {
  await app.vault.adapter.write(notePath, JSON.stringify(data, null, 2) + '\n');
}
function flash(msg) { saveHint.setText(msg); saveHint.style.opacity = '1'; clearTimeout(flash._t); flash._t = setTimeout(() => { saveHint.style.opacity = '0'; }, 1400); }
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
  for (let i = 0; i < data.annotations.length; i++) {
    const a = data.annotations[i];
    const el = list.createEl('div', { cls: 'lba-annot-item' + (a.to_fable ? ' is-fable' : '') });
    const ts = el.createEl('span', { cls: 'lba-ts', text: fmtTs(a.ts) });
    if (a.to_fable) ts.createEl('span', { cls: 'lba-fable-tag', text: '给 Fable' });
    el.appendText(a.text || '');
    const del = el.createEl('span', { cls: 'lba-del', text: '✕' });
    del.title = '删这条批注';
    del.onclick = async () => { data.annotations.splice(i, 1); await persist(); renderList(); flash('已删'); };
  }
}

// 自动保存草稿（防丢）：停手 500ms 落一次 draft，不新增条目
let draftTimer;
ta.oninput = () => {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(async () => { data.draft = ta.value; await persist(); flash('草稿已存'); }, 500);
};
// 落成一条批注：失焦或 Ctrl/Cmd+Enter；空白就只清草稿
async function commit() {
  clearTimeout(draftTimer);
  const text = ta.value.trim();
  if (!text) { if (data.draft) { data.draft = ''; await persist(); } return; }
  const to_fable = text.toLowerCase().startsWith('@fable');
  data.annotations.push({ ts: new Date().toISOString(), text, to_fable });
  data.draft = '';
  ta.value = '';
  await persist();
  renderList();
  flash('已保存');
}
ta.onblur = commit;
ta.onkeydown = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); commit(); } };

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
ta.value = data.draft || '';

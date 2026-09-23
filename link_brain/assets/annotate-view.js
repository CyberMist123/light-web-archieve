// 笔记底部批注块（Owner 2026-09-16）。每篇可见笔记末尾烤一段 bootstrap 载入本文件。
// 正文照常渲染在上面，这块只挂最底下；批注/⭐ 都存 sidecar notes.json，绝不写进正文。
// 入参：(dv, app, itemId, notePath)  notePath = _archive/<source>/<source_id>/notes.json
// 自动保存：边打字边存草稿（防丢），失焦 / Ctrl+Enter 落成一条批注。⭐ 收藏走插件跑 Python。
const root = dv.container;
root.classList.add('lba-annot-host');
const notify = (m) => { try { new Notice(m); } catch { console.log('[annot]', m); } };
const nickname = () => app.plugins.plugins['link-brain-actions']?.settings?.nickname || '';

const style = root.createEl('style');
style.textContent = `
/* 批注区去框线、留白（Owner 2026-09-17）：不要盒子/分隔线，配色随 Obsidian 主题变量。 */
.lba-annot{margin-top:30px;font-family:var(--font-interface),sans-serif;}
.lba-annot-head{display:flex;align-items:center;gap:10px;margin-bottom:12px;}
.lba-annot-title{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-faint);}
.lba-star{cursor:pointer;font-size:18px;line-height:1;user-select:none;filter:grayscale(1);opacity:.45;transition:.12s;}
.lba-star.is-on{filter:none;opacity:1;}
.lba-star:hover{opacity:.85;}
.lba-star-hint{font-size:11px;color:var(--text-muted);}
.lba-save-hint{margin-left:auto;font-size:11px;color:var(--text-faint);transition:opacity .2s;}
.lba-annot-list{display:flex;flex-direction:column;gap:18px;margin-bottom:16px;}
.lba-annot-item{padding:0 44px 0 0;font-size:14px;line-height:1.75;color:var(--text-normal);white-space:pre-wrap;word-break:break-word;position:relative;}
.lba-annot-item .lba-ts{display:block;font-size:11px;color:var(--text-faint);margin-bottom:3px;}
.lba-annot-item .lba-fable-tag{font-size:10px;color:var(--interactive-accent);font-weight:600;margin-left:6px;}
.lba-edited{font-size:10px;color:var(--text-faint);margin-left:6px;}
.lba-annot-text{display:inline;}
.lba-ctl{position:absolute;top:0;right:0;display:flex;gap:10px;align-items:center;opacity:0;transition:opacity .12s;}
.lba-annot-item:hover .lba-ctl{opacity:1;}
.lba-ctl .lba-edit,.lba-ctl .lba-del{cursor:pointer;color:var(--text-faint);font-size:13px;line-height:1;transition:.12s;user-select:none;}
.lba-ctl .lba-edit:hover{opacity:1;color:var(--interactive-accent);}
.lba-ctl .lba-del:hover{opacity:1;color:var(--text-error,#e5534b);}
.lba-edit-input{margin-top:4px;}
.lba-annot-input{width:100%;min-height:38px;resize:vertical;border:none;border-radius:0;padding:6px 0;font:inherit;font-size:14px;background:transparent;color:var(--text-normal);box-sizing:border-box;}
.lba-annot-input:focus{outline:none;}
.lba-annot-input::placeholder{color:var(--text-faint);}
`;

const box = root.createEl('div', { cls: 'lba-annot' });
const head = box.createEl('div', { cls: 'lba-annot-head' });
head.createEl('span', { cls: 'lba-annot-title', text: '批注' });
const star = head.createEl('span', { cls: 'lba-star', text: '★' });

const starHint = head.createEl('span', { cls: 'lba-star-hint' });
const saveHint = head.createEl('span', { cls: 'lba-save-hint' });

const list = box.createEl('div', { cls: 'lba-annot-list' });
const ta = box.createEl('textarea', { cls: 'lba-annot-input' });
ta.placeholder = '写批注…';  // 真正的提示由 setPlaceholder() 按有没有内容决定

let data = { starred: false, annotations: [], draft: '' };

async function load() {
  try { data = JSON.parse(await app.vault.adapter.read(notePath)); }
  catch { data = { starred: false, annotations: [], draft: '' }; }
  data.starred = !!data.starred;
  data.annotations = Array.isArray(data.annotations) ? data.annotations : [];
  data.draft = typeof data.draft === 'string' ? data.draft : '';
}
async function persist() {
  try{data.starred=!!JSON.parse(await app.vault.adapter.read(notePath)).starred;}catch{}
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
function setPlaceholder() {
  // 已经有批注时不再写那长串灰字提示（Owner 2026-09-17）
  ta.placeholder = data.annotations.length
    ? '写批注…'
    : '写批注…（@fable 开头 = 留言给 Fable）';
}
function startEdit(el, textSpan, i) {
  if (el.querySelector('.lba-edit-input')) return;   // 已在编辑
  const a = data.annotations[i];
  const editor = el.createEl('textarea', { cls: 'lba-annot-input lba-edit-input' });
  editor.value = a.text || '';
  textSpan.style.display = 'none';
  editor.focus();
  editor.setSelectionRange(editor.value.length, editor.value.length);
  let done = false;
  const save = async () => {
    if (done) return; done = true;
    const t = editor.value.trim();
    if (t && t !== a.text) {
      a.text = t;
      a.to_fable = t.toLowerCase().startsWith('@fable');
      a.edited = true;
      await persist();
      flash('已改');
    }
    renderList();
  };
  const cancel = () => { if (done) return; done = true; renderList(); };
  editor.onkeydown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); save(); }
    else if (e.key === 'Escape') { e.preventDefault(); cancel(); }
  };
  editor.onblur = save;
}
function renderList() {
  list.empty();
  for (let i = 0; i < data.annotations.length; i++) {
    const a = data.annotations[i];
    const el = list.createEl('div', { cls: 'lba-annot-item' + (a.to_fable ? ' is-fable' : '') });
    const who = a.author || (a.to_fable ? '' : nickname());
    const ts = el.createEl('span', { cls: 'lba-ts', text: (who ? who + ' · ' : '') + fmtTs(a.ts) });
    if (a.to_fable) ts.createEl('span', { cls: 'lba-fable-tag', text: '给 Fable' });
    if (a.edited) ts.createEl('span', { cls: 'lba-edited', text: '· 已编辑' });
    const textSpan = el.createEl('span', { cls: 'lba-annot-text' });
    textSpan.setText(a.text || '');
    const ctl = el.createEl('span', { cls: 'lba-ctl' });
    const edit = ctl.createEl('span', { cls: 'lba-edit', text: '✎' });

    edit.onclick = (ev) => { ev.stopPropagation(); startEdit(el, textSpan, data.annotations.indexOf(a)); };
    const del = ctl.createEl('span', { cls: 'lba-del', text: '✕' });

    // 按对象身份删（不认渲染时的下标，避免编辑/重渲后下标错位导致"删不掉"）
    del.onclick = async (ev) => {
      ev.stopPropagation();
      const idx = data.annotations.indexOf(a);
      if (idx >= 0) data.annotations.splice(idx, 1);
      try { await persist(); } catch (err) { flash('删除没存上：' + (err.message || err)); }
      renderList();
      flash('已删');
    };
  }
  setPlaceholder();
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
  data.annotations.push({ ts: new Date().toISOString(), text, to_fable, author: to_fable ? '' : nickname() });
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
    notify(data.starred ? '已加入星标收藏' : '已取消收藏');
  } catch (e) { notify('收藏失败：' + (e.message || e)); }
  finally { star.style.pointerEvents = ''; }
};

await load();
renderStar();
renderList();
ta.value = data.draft || '';

if(app.workspace.on){const ref=app.workspace.on('link-brain:star',(id,on)=>{if(id===itemId){data.starred=on;renderStar();}});dv.component.registerEvent(ref);}

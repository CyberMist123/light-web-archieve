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
.lba-annot.lba-in-side{margin-top:14px;}
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

// 0928 Owner：批注挪到左栏图片下面，和图在一屏。只在阅读视图挪（编辑视图里挪 DOM 会和编辑器打架），
// 事件都绑在 box 上，挪了照样能用；重渲染时先清掉左栏里的旧副本，不会叠出两个。
(function moveUnderImages(tries = 0) {
  const view = root.closest('.markdown-reading-view, .markdown-preview-view');
  const side = view && view.querySelector('.xhs-note .lb-side');
  if (!side) { if (view && tries < 20) setTimeout(() => moveUnderImages(tries + 1), 150); return; }
  side.querySelectorAll(':scope > .lba-annot').forEach(el => { if (el !== box) el.remove(); });
  box.classList.add('lba-in-side');
  side.appendChild(box);
})();

let data = { starred: false, annotations: [], draft: '' };
// 1001（审计 note-9 / ui-6）：同一篇在两个窗格开着、或手机经 WebDAV 同步回来一条，以前后保存的一方整份覆盖、
// 把对方的批注冲掉。现在保存前重读磁盘，按条合并：本端只增 / 改 / 删自己动过的那几条，删除记墓碑（deleted）。
let base = new Map();   // 上次和磁盘对齐时的批注：key → JSON，用来算「本端动过哪几条」
let locked = '';        // 非空 = notes.json 读坏了：原文件已另存 .corrupt，这一篇暂停保存，绝不拿空的盖回去
const akey = (a) => a.id || ('ts:' + (a.ts || '') + '|' + (a.text || ''));  // 老批注没 id：按时间 + 原文认
const newId = () => 'a' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
const snap = (arr) => new Map(arr.map(a => [akey(a), JSON.stringify(a)]));
const pause = (ms) => new Promise(r => setTimeout(r, ms));

async function readDisk() {
  // {ok:true, doc} 或 {ok:false, raw}；文件不在 = 还没有批注
  let raw;
  try {
    if (!(await app.vault.adapter.exists(notePath))) return { ok: true, doc: {} };
    raw = await app.vault.adapter.read(notePath);
  } catch (e) { return { ok: false, raw: null, err: e }; }
  try {
    const doc = JSON.parse(raw);
    if (!doc || typeof doc !== 'object' || Array.isArray(doc)) throw new Error('不是对象');
    return { ok: true, doc };
  } catch (e) { return { ok: false, raw, err: e }; }
}
async function readDiskSettled() {
  const first = await readDisk();
  if (first.ok) return first;
  await pause(400);  // 同步软件可能正替换到一半：等一下再读一次
  return readDisk();
}
async function quarantine(raw) {
  locked = 'notes.json 读不了';
  if (raw != null) {
    let bak = notePath + '.corrupt';
    try {
      if (await app.vault.adapter.exists(bak) && (await app.vault.adapter.read(bak)) !== raw) {
        bak = notePath + '.corrupt-' + new Date().toISOString().replace(/[:.]/g, '-');
      }
      await app.vault.adapter.write(bak, raw);
    } catch {}
  }
  ta.disabled = true;
  ta.placeholder = '批注文件读坏了，暂停保存';
  notify('这篇的批注文件读不了：原文件已另存 notes.json.corrupt，修好或删掉 notes.json 后重开这篇。期间不保存，免得盖掉原来的批注。');
}
function adopt(doc) {
  data = {
    ...doc,
    starred: !!doc.starred,
    annotations: Array.isArray(doc.annotations) ? doc.annotations : [],
    draft: typeof doc.draft === 'string' ? doc.draft : '',
  };
  base = snap(data.annotations);
}

async function load() {
  const disk = await readDiskSettled();
  if (!disk.ok) { await quarantine(disk.raw); adopt({}); return; }
  adopt(disk.doc);
}
async function persist() {
  if (locked) throw new Error('批注文件读坏了，暂停保存');
  const disk = await readDiskSettled();
  if (!disk.ok) { await quarantine(disk.raw); throw new Error('批注文件读坏了，暂停保存'); }
  const d = disk.doc;
  const tomb = new Set(Array.isArray(d.deleted) ? d.deleted : []);
  const mine = new Map(data.annotations.map(a => [akey(a), a]));
  for (const k of base.keys()) if (!mine.has(k)) tomb.add(k);            // 本端删掉的
  const out = (Array.isArray(d.annotations) ? d.annotations : []).filter(a => !tomb.has(akey(a)));
  for (const [k, a] of mine) {
    if (base.get(k) === JSON.stringify(a) || tomb.has(k)) continue;       // 没动过 / 别处已删（删除优先）
    const i = out.findIndex(x => akey(x) === k);
    if (i >= 0) out[i] = a; else out.push(a);                              // 本端改过的 / 新加的
  }
  out.sort((x, y) => String(x.ts || '').localeCompare(String(y.ts || '')));
  // ⭐ 由插件跑 Python 写，以磁盘为准；草稿是这一端正在打的字
  const doc = { ...d, starred: !!d.starred, annotations: out, deleted: [...tomb].slice(-500), draft: data.draft };
  if (!doc.deleted.length) delete doc.deleted;
  await app.vault.adapter.write(notePath, JSON.stringify(doc, null, 2) + '\n');
  const before = JSON.stringify(data.annotations);
  adopt(doc);
  if (JSON.stringify(data.annotations) !== before && !list.querySelector('.lba-edit-input')) renderList();
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
function startEdit(el, textSpan, key) {
  if (el.querySelector('.lba-edit-input')) return;   // 已在编辑
  const a = data.annotations.find(x => akey(x) === key);
  if (!a) { renderList(); return; }                   // 别处已经删了这条
  const editor = el.createEl('textarea', { cls: 'lba-annot-input lba-edit-input' });
  editor.value = a.text || '';
  textSpan.style.display = 'none';
  editor.focus();
  editor.setSelectionRange(editor.value.length, editor.value.length);
  let done = false;
  const save = async () => {
    if (done) return; done = true;
    const t = editor.value.trim();
    // 按 key 取当前那条（中途 persist 过的话内存里已是新对象）；老批注没 id：先给一个，旧 key 自然成墓碑
    const cur = data.annotations.find(x => akey(x) === key);
    if (t && cur && t !== cur.text) {
      if (!cur.id) cur.id = newId();
      cur.text = t;
      cur.to_fable = t.toLowerCase().startsWith('@fable');
      cur.edited = true;
      try { await persist(); flash('已改'); } catch (err) { flash('没存上：' + (err.message || err)); }
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

    const key = akey(a);
    edit.onclick = (ev) => { ev.stopPropagation(); startEdit(el, textSpan, key); };
    const del = ctl.createEl('span', { cls: 'lba-del', text: '✕' });

    // 按批注的 key 删（不认渲染时的下标 / 对象身份：合并保存后内存里换成了新对象）
    del.onclick = async (ev) => {
      ev.stopPropagation();
      const idx = data.annotations.findIndex(x => akey(x) === key);
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
  draftTimer = setTimeout(async () => {
    data.draft = ta.value;
    try { await persist(); flash('草稿已存'); } catch (err) { flash('草稿没存上：' + (err.message || err)); }
  }, 500);
};
// 落成一条批注：失焦或 Ctrl/Cmd+Enter；空白就只清草稿
async function commit() {
  clearTimeout(draftTimer);
  if (locked) return;  // 文件读坏了：字留在输入框里，不清、不存
  const text = ta.value.trim();
  if (!text) { if (data.draft) { data.draft = ''; try { await persist(); } catch {} } return; }
  const to_fable = text.toLowerCase().startsWith('@fable');
  data.annotations.push({ id: newId(), ts: new Date().toISOString(), text, to_fable, author: to_fable ? '' : nickname() });
  data.draft = '';
  try { await persist(); } catch (err) { flash('没存上：' + (err.message || err)); return; }
  ta.value = '';
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

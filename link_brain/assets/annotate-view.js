// 笔记底部批注块（Owner 2026-09-16）。每篇可见笔记末尾烤一段 bootstrap 载入本文件。
// 正文照常渲染在上面，这块只挂最底下；批注/⭐ 都存 sidecar notes.json，绝不写进正文。
// 入参：(dv, app, itemId, notePath)  notePath = _archive/<source>/<source_id>/notes.json
// 自动保存：边打字边存草稿（防丢），失焦 / Ctrl+Enter 落成一条批注。⭐ 收藏走插件跑 Python。
// 第 2 批：catalog.py 写 _archive/annotate-view.js 时在前面拼了共享前导 lb-page-lib.js（CONVENTIONS §5）。
// Dataview 每 2.5 秒（库里任何一篇 md 变了）重跑这块：notes.json 没变 → 上一次的批注框原样留着（正在打的字、光标都在）；
// 变了（另一个窗格 / 手机同步 / ⭐）→ 只重读、重画列表，不重建框。前导不在（单测直接跑本文件）就照旧每次重建。
const LB = typeof lbPageLib === 'function' ? lbPageLib(dv, app, 'annotate') : null;
// 10-03 她：批注又跑到最底下了。根因：Obsidian 重画左栏 / 重开这篇时，批注框跟着旧左栏被摘下，
// reuseDom 把它挂回本容器（全文最底下）就 return 了，没再挪回左栏。现在复用这条路也照样挪。
// 硬规矩（她定，别再改）：阅读视图里批注框永远在左栏图片 / 视频下面。tests/test_annot_side.cjs 守着。
if (LB && await LB.reuseDom()) { placeUnderImages(dv.container, LB.container?.__lbView?.el); return; }
const root = dv.container;
root.classList.add('lba-annot-host');
const notify = (m) => { try { new Notice(m); } catch { console.log('[annot]', m); } };
const nickname = () => app.plugins.plugins['link-brain-actions']?.settings?.nickname || '';
// 10-03 她：「@某人 开头 = 留言给某人」是她自己的设置（给她的 AI），默认不启用；设置里「批注留言对象」填名字才开。
// 存储字段沿用 to_fable（下游按它读），显示用设置里的名字。
const mention = () => String(app.plugins.plugins['link-brain-actions']?.settings?.annotateMention || '').trim();
const isMention = (t) => { const m = mention(); return !!m && String(t).toLowerCase().startsWith('@' + m.toLowerCase()); };

// 1002：样式放进 document.head（全页共用一份）。原来放在批注块自己的容器里——批注框挪进左栏后，
// Obsidian 卸载底部那段时样式跟着没了，左栏里的批注框就变成没样式的样子。
const hasDoc = typeof document !== 'undefined' && !!document.head;   // 单测的假 DOM 里没有 document
const style = (hasDoc && document.getElementById('lba-annot-style')) || (hasDoc ? document.head : root).createEl('style', { attr: { id: 'lba-annot-style' } });
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
// 1002：Obsidian 阅读视图按滚动位置渲染 / 卸载段落——长笔记里批注块渲染时，左栏那段可能还没渲染或已被卸掉，
// 旧版只等 3 秒就放弃，批注就留在全文最底下。改成一直盯着这篇的视图：左栏一出现（或被重建）就挪过去。
// 同一篇重渲染出新的批注块时，旧块让位（lbaGen 只认最新的那个），不会两个块抢一个左栏。
placeUnderImages(root, box);
function placeUnderImages(root, box) {
  if (!root || !box) return;
  const view = root.closest('.markdown-reading-view, .markdown-preview-view');
  if (!view) return;
  const gen = String(Date.now()) + Math.random().toString(36).slice(2, 6);
  view.dataset.lbaGen = gen;
  let queued = false, mo = null;
  const place = () => {
    queued = false;
    if (!view.isConnected || view.dataset.lbaGen !== gen) { mo?.disconnect(); return; }
    fixVideos(view);
    const side = view.querySelector('.xhs-note .lb-side');
    if (!side || box.parentElement === side) return;
    side.querySelectorAll(':scope > .lba-annot').forEach(el => { if (el !== box) el.remove(); });
    box.classList.add('lba-in-side');
    side.appendChild(box);
  };
  place();
  mo = new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(place); } });
  mo.observe(view, { childList: true, subtree: true });
}

// 10-03 她：视频变成一个奇怪的横条（灰底、没封面）。根因：Obsidian 阅读视图只改写 <img src> / <video src> 的相对路径，
// 不改 poster——封面加载不出来，视频框按默认比例显示。这里把 poster 换成 Obsidian 能加载的地址，并按封面比例定框，
// 看起来和封面图一样，点一下开始播放。Obsidian 重画左栏后新的 <video> 也会被 place() 再修一遍（幂等）。
function fixVideos(view) {
  let folder = '';
  try { folder = (dv.current()?.file?.folder || ''); } catch {}
  for (const v of view.querySelectorAll('.lb-side video')) {
    const raw = v.getAttribute && v.getAttribute('poster');
    if (!raw || v.dataset.lbPoster === raw) continue;
    v.dataset.lbPoster = raw;
    if (/^(app|https?|data|blob):/i.test(raw)) continue;
    const parts = [];
    for (const seg of (folder ? folder + '/' + raw : raw).split('/')) {
      if (!seg || seg === '.') continue;
      if (seg === '..') parts.pop(); else parts.push(seg);
    }
    let url = '';
    try { url = app.vault.adapter.getResourcePath(decodeURIComponent(parts.join('/'))); } catch { continue; }
    v.setAttribute('poster', url);
    v.dataset.lbPoster = url;
    v.preload = 'none';   // 点了再加载：封面先出来，不先拉视频头
    const img = new Image();
    img.onload = () => {
      if (!img.naturalWidth || !img.naturalHeight) return;
      Object.assign(v.style, { aspectRatio: img.naturalWidth + ' / ' + img.naturalHeight, width: '100%', height: 'auto',
        maxHeight: '75vh', objectFit: 'contain', background: 'transparent', borderRadius: 'inherit' });
    };
    img.src = url;
  }
}

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
  if (LB) LB.rekeep().catch(() => {});   // 自己写的不算「别处改了」
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
    : (mention() ? `写批注…（@${mention()} 开头 = 留言给 ${mention()}）` : '写批注…');
}
// 第 3 批：失败回滚用的快照（批注列表 + 草稿）；提示固定句式（CONVENTIONS §1.5），比 1.4 秒的小字多留一会儿
function snapshot() { return { annotations: JSON.parse(JSON.stringify(data.annotations)), draft: data.draft }; }
function restore(s) { data.annotations = s.annotations; data.draft = s.draft; }
function failNotice(err) {
  const msg = '没保存上，内容还在，可重试：' + ((err && err.message) || err || '未知原因');
  notify(msg);
  saveHint.setText(msg); saveHint.style.opacity = '1'; clearTimeout(flash._t); flash._t = setTimeout(() => { saveHint.style.opacity = '0'; }, 6000);
}
function startEdit(el, textSpan, key, initial) {
  if (el.querySelector('.lba-edit-input')) return;   // 已在编辑
  const a = data.annotations.find(x => akey(x) === key);
  if (!a) { renderList(); return; }                   // 别处已经删了这条
  const editor = el.createEl('textarea', { cls: 'lba-annot-input lba-edit-input' });
  editor.value = typeof initial === 'string' ? initial : (a.text || '');
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
      // 第 3 批（CONVENTIONS §1.5）：先留快照；写盘失败把这条改回原样、编辑框带着刚打的字重新打开
      const prev = snapshot();
      if (!cur.id) cur.id = newId();
      cur.text = t;
      cur.to_fable = isMention(t);
      cur.edited = true;
      try { await persist(); }
      catch (err) {
        restore(prev); renderList();
        failNotice(err);
        const row = [...list.querySelectorAll('.lba-annot-item')][data.annotations.findIndex(x => akey(x) === key)];
        if (row) { startEdit(row, row.querySelector('.lba-annot-text'), key, t); }
        return;
      }
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
    if (a.to_fable) ts.createEl('span', { cls: 'lba-fable-tag', text: mention() ? '给 ' + mention() : '留言' });
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
      const prev = snapshot();
      const idx = data.annotations.findIndex(x => akey(x) === key);
      if (idx >= 0) data.annotations.splice(idx, 1);
      // 删成功才说「已删」；失败把这条放回去（以前先报错、紧接着 flash('已删') 把错误盖掉）
      try { await persist(); } catch (err) { restore(prev); renderList(); failNotice(err); return; }
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
  if (!text) { if (data.draft) { data.draft = ''; try { await persist(); } catch (err) { flash('草稿没清掉：' + (err.message || err)); } } return; }
  const to_fable = isMention(text);
  const prev = snapshot();
  data.annotations.push({ id: newId(), ts: new Date().toISOString(), text, to_fable, author: to_fable ? '' : nickname() });
  data.draft = '';
  // 失败把刚 push 的那条撤回（不然再提交一次会多出一条重复批注），字留在输入框里
  try { await persist(); } catch (err) { restore(prev); failNotice(err); return; }
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
LB?.t('read');
renderStar();
renderList();
ta.value = data.draft || '';
LB?.t('render');
// 登记这一版：notes.json 没变就留着这个框；变了只重读重画（正在编辑某条、正在输入框里打字时不动那部分）
LB?.keep(box, { versionOf: { abs: notePath }, version: await LB.data.version({ abs: notePath }), update: async () => {
  await load();
  renderStar();
  if (!list.querySelector('.lba-edit-input')) renderList();
  const typing = typeof document !== 'undefined' && document.activeElement === ta;
  if (!typing && !ta.disabled) ta.value = data.draft || '';
} });
LB?.t('total');

if(app.workspace.on){const ref=app.workspace.on('link-brain:star',(id,on)=>{if(id===itemId){data.starred=on;renderStar();}});dv.component.registerEvent(ref);}

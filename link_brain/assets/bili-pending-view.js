// 「挑要下的视频」页（1101 作者：B 站待选清单「打了勾划掉了，是删还是要下呢，很迷惑；而且不能默认用户会用命令行」；
// 再改：「不是一个个点，是复用目录的瀑布流 / 目录切换，选中，下载；其他不下载或删除，放回收站。也不要说太长，写具体几小时几分钟、分几 P」）。
// 同步时超过时长上限、分 P 超过 5 个的 B 站收藏只记了链接，这一页列出来：每条一张封面卡片（封面、标题、UP、时长、几 P、收藏夹、收藏时间），
// 点卡片 = 选中 / 取消（左上角圈），可全选；选中后顶上一条：「下载」= `bilibili choose --allow`（下次同步就下，也可以马上开始）、
// 「删除」= `choose --deny`（不下载、不进收藏，写删除屏蔽，在回收站的记录里，能撤销 / 重新导入）、点过下载的还能「不下了」= `--undo`。
// 没选的就留在这里（只记了链接）。顶上切「瀑布流 / 目录」（同目录页、回收站的叫法），按收藏夹筛。
// lb-page-lib.js 由 sync.publish_pending 拼在本文件前面（写进 _archive/bili-pending-page.js，仓根的 md 只放引导）。
// 数据：_archive/bilibili-sync/pending-data.json（后端只读本地快照算的，不连 B 站）；手机上只能看。
const LB = lbPageLib(dv, app, 'bili-pending');
if (await LB.reuseDom()) return;
const root = dv.container;
const DATA = '_archive/bilibili-sync/pending-data.json';
const RUN_LABEL = '下载 B 站收藏';   // 同 settings-v6.js BILI_RUN_LABEL
{ const pane = root.closest && root.closest('.markdown-preview-view, .markdown-source-view'); if (pane) pane.classList.add('lb-bilipage'); }
LB.style('lb-bilipick-style', `
.lb-bilipage .markdown-preview-sizer,.lb-bilipage .markdown-preview-section,.lb-bilipage .cm-sizer,.lb-bilipage .cm-contentContainer,.lb-bilipage .cm-content,.lb-bilipage .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-bilipage .markdown-preview-sizer,.lb-bilipage .markdown-preview-section,.lb-bilipage .cm-sizer,.lb-bilipage .cm-contentContainer,.lb-bilipage .cm-content,.lb-bilipage .block-language-lb-page{width:100%!important;max-width:none!important;}
.lb-bilipage .inline-title,.lb-bilipage .metadata-container{display:none!important;}
.lb-bilipage .block-language-dataviewjs{overflow:visible!important;}
.markdown-source-view.lb-bilipage .cm-embed-block.cm-lang-dataviewjs,.markdown-source-view.lb-bilipage .cm-embed-block.cm-lang-dataviewjs:hover{overflow:visible!important;}
.lb-bilipage :is(.el-pre:has(.block-language-dataviewjs),pre:has(.block-language-dataviewjs),.block-language-dataviewjs,.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs),.lb-bilipage :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs):hover{border:0!important;background:transparent!important;box-shadow:none!important;outline:0!important;border-radius:0!important;}
.lb-bilipage :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-lang-dataviewjs) .edit-block-button{display:none!important;}
.lb-bilipage .block-language-lb-page{overflow:visible!important;}
.markdown-source-view.lb-bilipage .cm-embed-block.cm-lang-lb-page,.markdown-source-view.lb-bilipage .cm-embed-block.cm-lang-lb-page:hover{overflow:visible!important;}
.lb-bilipage :is(.el-pre:has(.block-language-lb-page),pre:has(.block-language-lb-page),.block-language-lb-page,.cm-embed-block:has(.block-language-lb-page),.cm-preview-code-block.cm-lang-lb-page),.lb-bilipage :is(.cm-embed-block:has(.block-language-lb-page),.cm-preview-code-block.cm-lang-lb-page):hover{border:0!important;background:transparent!important;box-shadow:none!important;outline:0!important;border-radius:0!important;}
.lb-bilipage :is(.cm-embed-block:has(.block-language-lb-page),.cm-lang-lb-page) .edit-block-button{display:none!important;}
.lbb-wrap{--bili-t:#18191c;--bili-m:#9499a0;--bili-blue:#00aeec;max-width:1440px;margin:0 auto;padding:22px 24px 40px;box-sizing:border-box;font-family:var(--lb-font-body);container-type:inline-size;}
.theme-dark .lbb-wrap{--bili-t:var(--lb-ink);--bili-m:var(--lb-muted);}
.lbb-head{position:sticky;top:0;z-index:2;background:var(--lb-surface);padding:0 0 12px;display:flex;flex-direction:column;gap:12px;}
.lbb-titlerow{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;}
.lbb-title{font-family:var(--lb-font-title);font-style:italic;font-size:30px;font-weight:700;line-height:1.1;}
.lbb-titlerow .lbb-sp{flex:1;}
.lbb-wrap .lb-page-nav{grid-column:auto;grid-row:auto;justify-self:auto;}
.lbb-note{font-size:var(--lb-fs-body);line-height:1.7;color:var(--lb-muted);margin:0;max-width:780px;}
.lbb-note b{color:var(--lb-ink);font-weight:600;}
.lbb-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;font-size:var(--lb-fs-small);color:var(--lb-muted);}
.lbb-bar .lbb-sp{flex:1;}
.lbb-seg{display:inline-flex;padding:2px;border-radius:var(--lb-radius-pill);background:var(--lb-soft);}
.lbb-wrap .lbb-seg button{height:auto!important;padding:5px 13px!important;border:0!important;border-radius:var(--lb-radius-pill)!important;background:transparent!important;box-shadow:none!important;color:var(--lb-muted);font-size:var(--lb-fs-small);cursor:pointer;transition:background .15s,color .15s;}
.lbb-wrap .lbb-seg button.is-on{background:var(--lb-ink)!important;color:var(--lb-surface)!important;}
.lbb-wrap select.lbb-folder{height:auto;padding:4px 26px 4px 10px;border-radius:var(--lb-radius-pill);font-size:var(--lb-fs-small);max-width:220px;}
.lbb-all{display:inline-flex;align-items:center;gap:6px;cursor:pointer;user-select:none;color:var(--lb-ink);}
.lbb-all input{margin:0;cursor:pointer;}
.lbb-count{white-space:nowrap;}
/* 选中后的动作条（和回收站 / 目录多选一个意思）；点过下载的：「现在开始下载」 */
.lbb-act,.lbb-go{display:flex;flex-wrap:wrap;align-items:center;gap:10px 12px;padding:10px 14px;border-radius:10px;background:var(--lb-soft);font-size:var(--lb-fs-body);color:var(--lb-ink);}
.lbb-act[hidden],.lbb-go[hidden]{display:none!important;}
.lbb-act .lbb-sp,.lbb-go .lbb-sp{flex:1;}
.lbb-wrap .lbb-act button,.lbb-wrap .lbb-go button{height:auto!important;padding:7px 16px!important;border-radius:8px!important;font-size:14px;cursor:pointer;box-shadow:none!important;border:1px solid var(--lb-line)!important;background:var(--lb-surface)!important;color:var(--lb-ink)!important;}
.lbb-wrap button.lbb-cta{background:var(--bili-blue)!important;border-color:var(--bili-blue)!important;color:#fff!important;font-weight:600;}
.lbb-wrap button.lbb-danger{color:var(--lb-danger,#e03e3e)!important;border-color:var(--lb-danger,#e03e3e)!important;background:transparent!important;}
.lbb-wrap button.lbb-plain{border-color:transparent!important;background:transparent!important;color:var(--lb-muted)!important;}
.lbb-wrap .lbb-act button:disabled,.lbb-wrap .lbb-go button:disabled{opacity:.55;cursor:default;}
/* 瀑布流：照目录页 B 站卡片（.lbc-card.is-bili）——16:9、圆角 6、底部渐变条（左几 P、右时长）、标题 15/22 两行、下面灰字 */
.lbb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:26px 20px;padding:14px 0 30px;}
.lbb-card{display:flex;flex-direction:column;min-width:0;position:relative;cursor:pointer;user-select:none;border-radius:8px;}
.lbb-card:focus-visible{outline:2px solid var(--lb-ink);outline-offset:4px;}
.lbb-media{position:relative;display:block;width:100%;aspect-ratio:16/9;border-radius:6px;overflow:hidden;background:var(--lb-soft);}
.lbb-media img{display:block;width:100%;height:100%;object-fit:cover;pointer-events:none;}
.lbb-nocover{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:10%;box-sizing:border-box;background:#e3edf2;color:#18191c;font:700 15px/1.45 var(--lb-font-body);text-align:center;overflow:hidden;}
.lbb-nocover span{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.lbb-stats{position:absolute;left:0;right:0;bottom:0;box-sizing:border-box;height:38px;padding:16px 8px 6px;display:flex;align-items:center;gap:8px;background:linear-gradient(180deg,rgba(0,0,0,0) 0%,rgba(0,0,0,.8) 100%);color:#fff;font:400 13px/16px var(--lb-font-body);font-variant-numeric:tabular-nums;}
.lbb-stats .lbb-dur{margin-left:auto;}
/* 左上角圈：选中实心（同目录页多选的勾选圈） */
.lbb-check{position:absolute;top:8px;left:8px;width:24px;height:24px;border-radius:50%;box-sizing:border-box;border:2px solid #fff;background:rgba(0,0,0,.28);display:grid;place-items:center;color:#fff;font:700 14px/1 var(--lb-font-body);}
.lbb-card.is-sel .lbb-check{background:var(--bili-blue);border-color:var(--bili-blue);}
.lbb-card.is-sel .lbb-media{box-shadow:0 0 0 3px var(--bili-blue);}
.lbb-mark{position:absolute;top:8px;right:8px;padding:2px 8px;border-radius:4px;background:var(--bili-blue);color:#fff;font:600 12px/18px var(--lb-font-body);}
.lbb-ctitle{margin-top:12px;font:500 15px/22px var(--lb-font-body);color:var(--bili-t);height:44px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;}
.lbb-card:hover .lbb-ctitle{color:var(--bili-blue);}
.lbb-meta{margin-top:6px;font:400 13px/18px var(--lb-font-body);color:var(--bili-m);display:flex;flex-direction:column;gap:2px;min-width:0;}
.lbb-meta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbb-meta .lbb-len{color:var(--bili-t);}
.lbb-meta .lbb-done{color:var(--lb-ink);}
.lbb-wrap a.lbb-open{color:var(--bili-m);text-decoration:underline;text-underline-offset:2px;}
.lbb-wrap a.lbb-open:hover{color:var(--bili-blue);}
.lbb-off{margin-top:4px;font-size:12px;line-height:1.5;color:var(--text-warning,#c27c00);}
.lbb-card.is-done{cursor:default;}
.lbb-card.is-done .lbb-media{opacity:.7;}
/* 目录：一行一条，圈在最左，小封面，文字 */
.lbb-grid.is-list{display:block;padding-top:4px;}
.lbb-grid.is-list .lbb-card{flex-direction:row;align-items:center;gap:14px;padding:10px 8px;border-bottom:1px solid var(--lb-line);border-radius:0;}
.lbb-grid.is-list .lbb-card.is-sel{background:var(--lb-soft);}
.lbb-grid.is-list .lbb-card.is-sel .lbb-media{box-shadow:none;}
.lbb-grid.is-list .lbb-check{position:static;flex:none;border-color:var(--lb-line);background:transparent;color:transparent;}
.lbb-grid.is-list .lbb-card.is-sel .lbb-check{background:var(--bili-blue);border-color:var(--bili-blue);color:#fff;}
.lbb-grid.is-list .lbb-media{flex:0 0 150px;width:150px;}
.lbb-grid.is-list .lbb-stats{height:28px;padding:10px 6px 4px;font-size:12px;}
.lbb-grid.is-list .lbb-mark{display:none;}
.lbb-grid.is-list .lbb-text{flex:1;min-width:0;}
.lbb-grid.is-list .lbb-ctitle{margin-top:0;height:auto;-webkit-line-clamp:1;}
.lbb-grid.is-list .lbb-meta{flex-direction:row;flex-wrap:wrap;gap:0 12px;}
.lbb-tag{display:inline-block;margin-left:8px;padding:0 6px;border-radius:4px;background:var(--bili-blue);color:#fff;font-size:12px;line-height:18px;vertical-align:1px;}
@container (max-width:620px){.lbb-grid.is-list .lbb-media{flex-basis:110px;width:110px;}}
@media (max-width:600px){.lbb-wrap{padding:12px 0 32px;}.lbb-title{font-size:24px;}.lbb-grid{grid-template-columns:1fr;}}
.lbb-empty{padding:48px 0;color:var(--lb-muted);font-size:var(--lb-fs-body);line-height:1.8;}
.lbb-empty b{display:block;color:var(--lb-ink);font-size:16px;font-weight:600;margin-bottom:4px;}
`);
const mount = LB.mountHost('lbb-host');
const wrap = mount.createEl('div', { cls: 'lbb-wrap' });
const head = wrap.createEl('div', { cls: 'lbb-head' });
const titleRow = head.createEl('div', { cls: 'lbb-titlerow' });
titleRow.createEl('div', { cls: 'lbb-title', text: 'B 站 · 挑要下的视频' });
titleRow.createEl('span', { cls: 'lbb-sp' });
const nav = titleRow.createEl('nav', { cls: 'lb-page-nav' });
nav.createEl('button', { text: '浏览收藏' }).onclick = () => LB.openPage('catalog');
nav.createEl('button', { text: '回收站' }).onclick = () => LB.openPage('trash');
const note = head.createEl('p', { cls: 'lbb-note' });
const goBar = head.createEl('div', { cls: 'lbb-go' }); goBar.hidden = true;
const actBar = head.createEl('div', { cls: 'lbb-act' }); actBar.hidden = true;
const bar = head.createEl('div', { cls: 'lbb-bar' });
const grid = wrap.createEl('div', { cls: 'lbb-grid' });

let data = null, items = [], hasData = false, busy = false;
const saved = LB.state.load() || {};
let view = saved.view === 'list' ? 'list' : 'grid';
let folder = typeof saved.folder === 'string' ? saved.folder : '';
const sel = new Set(Array.isArray(saved.sel) ? saved.sel : []);
const keepState = () => LB.state.save({ view, folder, sel: [...sel] });

// 时长一律写成「1 小时 30 分」（1101 作者：要具体数字）；封面右下角照 B 站写 1:30:00
const clock = sec => {
  const s = Math.max(0, Math.round(Number(sec) || 0)); if (!s) return '';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60, p = n => String(n).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(r)}` : `${m}:${p(r)}`;
};
const hm = sec => {
  const m = Math.round((Number(sec) || 0) / 60); if (!m) return Number(sec) > 0 ? '不到 1 分钟' : '';
  const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} 小时${r ? ` ${r} 分` : ''}` : `${m} 分钟`;
};
const lenText = it => [hm(it.duration), it.page_count > 1 ? `分 ${it.page_count} P` : ''].filter(Boolean).join(' · ');
const favDay = t => { const n = Number(t) || 0; if (!n) return ''; const d = new Date(n * 1000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const skipped = () => { try { const s = LB.provider()?.settings?.bilibili?.skipFolders; return new Set((Array.isArray(s) ? s : []).map(String)); } catch { return new Set(); } };
const allDone = it => it.page_count > 1 && (it.done || 0) >= it.page_count;
const okUrl = url => /^https:\/\/(www\.)?bilibili\.com\//.test(url || '');

async function readData() {
  try { const d = JSON.parse(await app.vault.adapter.read(LB.path(DATA))); return d && Array.isArray(d.items) ? d : null; }
  catch { return null; }
}
function paintNote() {
  note.empty();
  if (LB.mobile) { note.setText(LB.MOBILE_ONLY_TEXT); return; }
  const lim = data && data.max_duration ? hm(data.max_duration) : '';
  note.append('同步 B 站收藏时，' + (lim ? `超过 ${lim}的视频、` : '') + `分 P 超过 ${(data && data.auto_max) || 5} 个的视频没有自动下载，都列在这里。点卡片选中（可以全选），再点`);
  note.createEl('b', { text: '「下载」' });
  note.append('；不要的选中点');
  note.createEl('b', { text: '「删除」' });
  note.append('：不下载、不进收藏，放进回收站，以后同步也不会再出现。没选的先留在这里。');
}
function paintGo() {
  const n = items.filter(it => it.chosen && !allDone(it)).length;
  const p = LB.provider();
  const running = p && p.running === RUN_LABEL;
  goBar.hidden = LB.mobile || (!n && !running);
  goBar.empty();
  if (goBar.hidden) return;
  goBar.createEl('span', { text: running ? '正在下载 B 站收藏：底部状态栏能看进度、能停止' : `点了「下载」的 ${n} 个，下次同步时下载；也可以现在就开始` });
  goBar.createEl('span', { cls: 'lbb-sp' });
  if (running) return;
  const b = goBar.createEl('button', { cls: 'lbb-cta', text: '现在开始下载' }); b.type = 'button';
  b.disabled = !!(p && p.running);
  b.onclick = () => syncNow(b);
}
async function syncNow(btn) {
  const p = LB.need('biliSyncNow'); if (!p) return;
  if (p.running) { LB.say(p.busyText ? p.busyText() : '正在忙，稍后再点', { kind: 'warn' }); return; }
  const done = LB.busy(btn, '正在开始…');
  try { const pending = p.biliSyncNow(); done(); paintGo(); await pending; }
  catch (e) { done(); LB.say('没开始下载：' + (e?.message || e), { kind: 'error' }); }
  finally { paintGo(); }
}
const shown = () => items.filter(it => !folder || (it.folder_ids || []).map(String).includes(folder));
const selectable = it => !allDone(it);
const picked = () => shown().filter(it => sel.has(it.bvid) && selectable(it));
function paintAct() {
  const list = picked();
  actBar.hidden = LB.mobile || !list.length;
  actBar.empty();
  if (actBar.hidden) return;
  const total = list.reduce((a, it) => a + (Number(it.duration) || 0), 0);
  actBar.createEl('span', { cls: 'lbb-act-text', text: `已选 ${list.length} 个 · 一共 ${hm(total) || '0 分钟'}` });
  actBar.createEl('span', { cls: 'lbb-sp' });
  const btn = (text, cls, act, run) => { const b = actBar.createEl('button', { text, cls }); b.type = 'button'; b.dataset.act = act; b.disabled = busy; b.onclick = () => run(b); return b; };
  const fresh = list.filter(it => !it.chosen), chosen = list.filter(it => it.chosen);
  if (fresh.length) btn(`下载${chosen.length ? ` ${fresh.length} 个` : ''}`, 'lbb-cta', 'download', b => act('allow', fresh, b));
  if (chosen.length) btn('不下了', '', 'undo', b => act('undo', chosen, b));
  btn('删除', 'lbb-danger', 'delete', b => act('deny', list, b));
  btn('取消选择', 'lbb-plain', 'clear', () => { sel.clear(); keepState(); paintList(); });
}
function paintBar() {
  bar.empty();
  if (!hasData || !items.length) return;
  const viewSeg = bar.createEl('div', { cls: 'lbb-seg lbb-view' });
  for (const [k, label] of [['grid', '瀑布流'], ['list', '目录']]) {
    const b = viewSeg.createEl('button', { text: label, cls: view === k ? 'is-on' : '' }); b.type = 'button'; b.dataset.view = k;
    b.setAttribute('aria-pressed', String(view === k));
    b.onclick = () => { view = k; keepState(); paintBar(); paintList(); };
  }
  const folders = (data.folders || []).filter(f => items.some(it => (it.folder_ids || []).map(String).includes(String(f.id))));
  if (folder && !folders.some(f => String(f.id) === folder)) folder = '';
  if (folders.length > 1) {
    const s = bar.createEl('select', { cls: 'dropdown lbb-folder' });
    s.setAttribute('aria-label', '按收藏夹看');
    s.createEl('option', { text: '全部收藏夹', value: '' });
    for (const f of folders) s.createEl('option', { text: f.title || f.id, value: String(f.id) });
    s.value = folder;
    s.onchange = () => { folder = s.value; keepState(); paintList(); };
  }
  if (!LB.mobile) {
    const all = bar.createEl('label', { cls: 'lbb-all' });
    all.createEl('input', { type: 'checkbox', cls: 'lbb-all-cb' });
    all.createEl('span', { text: '全选' });
  }
  bar.createEl('span', { cls: 'lbb-sp' });
  bar.createEl('span', { cls: 'lbb-count' });
}
function paintCount() {
  const list = shown(), can = list.filter(selectable);
  const el = bar.querySelector('.lbb-count');
  if (el) el.setText(`${list.length} 个 · 点了下载的 ${list.filter(it => it.chosen && !allDone(it)).length} 个`);
  const cb = bar.querySelector('.lbb-all-cb');
  if (cb) {
    cb.checked = !!can.length && can.every(it => sel.has(it.bvid));
    cb.disabled = !can.length;
    cb.onchange = () => { if (cb.checked) for (const it of can) sel.add(it.bvid); else for (const it of can) sel.delete(it.bvid); keepState(); paintList(); };
  }
}
function paintList() {
  grid.empty();
  grid.className = 'lbb-grid ' + (view === 'list' ? 'is-list' : 'is-cover');
  for (const id of [...sel]) if (!items.some(it => it.bvid === id && selectable(it))) sel.delete(id);
  if (!hasData || !items.length) {
    const box = grid.createEl('div', { cls: 'lbb-empty' });
    if (!hasData || !data.synced) {
      box.createEl('b', { text: '还没同步过 B 站收藏' });
      box.append('在设置「收藏与同步 → B 站」点「立即同步」；超过时长、分 P 多的视频会列在这里，等你挑。');
    } else {
      box.createEl('b', { text: '没有要挑的视频' });
      box.append('收藏里的视频都自动下了。以后超过时长、分 P 多的会列在这里。');
    }
    paintAct(); paintGo();
    return;
  }
  const list = shown();
  if (!list.length) grid.createEl('div', { cls: 'lbb-empty', text: '这个收藏夹里没有要挑的视频' });
  const off = skipped();
  for (const it of list) card(it, off);
  paintCount(); paintAct(); paintGo();
}
function toggle(it) {
  if (LB.mobile || busy || !selectable(it)) return;
  if (sel.has(it.bvid)) sel.delete(it.bvid); else sel.add(it.bvid);
  keepState(); paintList();
}
function card(it, off) {
  const finished = allDone(it), on = sel.has(it.bvid);
  const el = grid.createEl('div', { cls: 'lbb-card' + (on ? ' is-sel' : '') + (finished ? ' is-done' : '') + (it.chosen && !finished ? ' is-chosen' : '') });
  el.dataset.bvid = it.bvid;
  if (!LB.mobile && !finished) {
    el.tabIndex = 0; el.setAttribute('role', 'checkbox'); el.setAttribute('aria-checked', String(on));
    el.onclick = e => { if (e.target?.closest?.('a')) return; toggle(it); };
    el.onkeydown = e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(it); } };
  }
  const media = el.createEl('div', { cls: 'lbb-media' });
  if (it.cover) {
    const img = media.createEl('img'); img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.src = it.cover;
    img.onerror = () => { img.remove(); media.prepend(noCover(it)); };
  } else media.append(noCover(it));
  const stats = media.createEl('div', { cls: 'lbb-stats' });
  if (it.page_count > 1) stats.createEl('span', { text: `${it.page_count}P` });
  stats.createEl('span', { cls: 'lbb-dur', text: clock(it.duration) });
  if (it.chosen && !finished) media.createEl('span', { cls: 'lbb-mark', text: '要下' });
  if (!LB.mobile && !finished) (view === 'list' ? el : media)[view === 'list' ? 'prepend' : 'append'](checkEl(on));
  const text = el.createEl('div', { cls: 'lbb-text' });
  const t = text.createEl('div', { cls: 'lbb-ctitle', text: it.title || it.bvid });
  if (view === 'list' && it.chosen && !finished) t.createEl('span', { cls: 'lbb-tag', text: '要下' });
  const meta = text.createEl('div', { cls: 'lbb-meta' });
  const line1 = meta.createEl('span', { cls: 'lbb-len', text: lenText(it) });
  if (okUrl(it.url)) {
    line1.append(' · ');
    const a = line1.createEl('a', { cls: 'lbb-open', text: '去 B 站看', href: it.url }); a.target = '_blank'; a.rel = 'noopener';
  }
  meta.createEl('span', { text: [it.upper, (it.folders || []).length ? '收藏夹：' + it.folders.join('、') : '', favDay(it.fav_time) ? `${favDay(it.fav_time)} 收藏` : ''].filter(Boolean).join(' · ') });
  if (finished) { meta.createEl('span', { cls: 'lbb-done', text: `已经下好了（${it.page_count} P 都在库里）` }); return; }
  if (it.page_count > 1 && it.done) meta.createEl('span', { cls: 'lbb-done', text: `已经下了 ${it.done} / ${it.page_count} P` });
  const ids = (it.folder_ids || []).map(String);
  if (ids.length && ids.every(id => off.has(id))) text.createEl('div', { cls: 'lbb-off', text: '它所在的收藏夹设成了不同步：点了下载也不会下，先在设置里把收藏夹打开' });
}
function checkEl(on) { const d = grid.ownerDocument.createElement('span'); d.className = 'lbb-check'; d.textContent = on ? '✓' : ''; d.setAttribute('aria-hidden', 'true'); return d; }
function noCover(it) {
  const d = grid.ownerDocument.createElement('div'); d.className = 'lbb-nocover';
  const s = grid.ownerDocument.createElement('span'); s.textContent = it.title || it.bvid; d.appendChild(s);
  return d;
}
// 选中的一批：下载（allow）/ 不下了（undo）/ 删除（deny，进回收站的记录、以后不再同步，能撤销）。交给插件跑 `bilibili choose`
// （顺手重写 pending-data.json）；没存上照固定句式说原因，选中的都还在。
async function act(kind, list, btn) {
  if (LB.mobile || busy || !list.length) return;
  const n = list.length;
  if (kind === 'deny' && !(await LB.confirm({ title: `删除这 ${n} 个视频？`, body: '不下载、不进收藏；放进回收站的记录里，以后同步也不会再出现。想要回来可以在回收站重新导入。', ok: '删除', danger: true }))) return;
  const p = LB.need('biliChoose'); if (!p) return;
  busy = true;
  const done = LB.busy(btn, kind === 'allow' ? '正在记下…' : kind === 'deny' ? '正在删除…' : '正在改…');
  const ids = list.map(it => it.bvid);
  try {
    await p.biliChoose({ [kind]: ids });
    done();
    for (const id of ids) sel.delete(id);
    if (kind === 'allow') for (const it of list) it.chosen = true;
    if (kind === 'undo') for (const it of list) it.chosen = false;
    if (kind === 'deny') items = items.filter(it => !ids.includes(it.bvid));
    keepState();
    const total = hm(list.reduce((a, it) => a + (Number(it.duration) || 0), 0));
    if (kind === 'allow') LB.say(`记下了 ${n} 个（一共 ${total}）：下次同步时下载`, { kind: 'ok', actions: p.running ? [] : [{ label: '现在开始下载', run: () => syncNow(goBar.querySelector('.lbb-cta')) }] });
    else if (kind === 'undo') LB.say(`${n} 个改成不下了：还留在这里`, { kind: 'ok' });
    else LB.undoNotice(`删除了 ${n} 个：放进回收站，以后不再同步`, async () => {
      await p.biliChoose({ undo: ids });
      if (typeof p.trashAction === 'function') await p.trashAction('forget', ids.map(id => 'bili-' + id));
      await draw();
    });
  } catch (e) {
    done();
    LB.say('没保存上，内容还在，可重试：' + (e?.message || e), { kind: 'error' });
  } finally { busy = false; paintList(); }
}
async function draw() {
  data = await readData();
  hasData = !!data;
  items = hasData ? data.items.filter(it => it && it.bvid) : [];
  paintNote(); paintBar(); paintList();
}
await draw();
// 吸顶的 top 取滚动容器上内边距的负值（同回收站页）
function paintStickyTop() {
  const sc = LB.scroller(); if (!sc) return;
  let pad = 0;
  try { pad = parseFloat((typeof getComputedStyle === 'function' ? getComputedStyle(sc) : null)?.paddingTop) || 0; } catch {}
  head.style.top = pad ? `${-pad}px` : '0px';
}
paintStickyTop();
// 同步开始 / 结束：顶上那条「现在开始下载」跟着变
{ const p = LB.provider(); if (p && typeof p.onTask === 'function') { const off = p.onTask(() => paintGo()); if (typeof off === 'function') LB.onUnload(off); } }
// 选完 / 同步完后端重写 pending-data.json：下一次 Dataview 重跑版本变了就重读重画（版本没变原样挂回）
LB.keep(wrap, { version: await LB.data.version(DATA), versionOf: DATA, update: () => draw(), onReuse: () => { paintStickyTop(); paintGo(); } });

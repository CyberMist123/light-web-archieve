// chat-view.js — 收藏搜索页的极简版（Owner 2026-09-17）。
// 无框线、居中、像聊天：搜收藏 + 问 AI 一体；会话持久化（跳走再回来不丢，直到点「清空」）；
// 「存档」栏可存可删——既存 AI 报告，也存 Owner 自己写的判断。配色全走 Obsidian 主题变量。
// 依赖：本文件前面已内联 lb-page-lib.js（共享前导，CONVENTIONS §5）和 catalog-search.js（score/normalize）；provider = link-brain-actions 插件。
// 第 2 批：Dataview 每 2.5 秒重跑本页时，版本没变就把上一次的整页 DOM 挂回（正在生成的回答、输入框、滚动都在）。
// 批次 D · L2：
//   - 页面挂在 LB.mountHost 的 host 上（dv.container 的兄弟）：Dataview 重跑只清容器，输入框不失焦、输入法组字不断（§5.9）；
//   - 对话区按轮缓存 DOM（views，key = 轮次 id）：保留 / × / 加入来源只原地重建那一轮的来源块，不重渲正文、不收起展开的列表（A1）；
//   - 正在生成的回答、排队的问题放在插件对象上（chatInFlight / chatQueue，§5.3）：换页再回来接着看出字，追问进排队（A2）；
//   - 会话文件只经插件级写链 chatSaveChain 串行写；答完先读回磁盘、把回答插到自己那条问题后面（不整份覆盖）；
//   - 流式输出按行排版（A4）、失败按原因给「重试 / 改一下再问」（A5）、没配问答 AI 照样列出相关收藏（A6）、手机 / 插件没启用只读（A11）、
//     目录（F5）、键盘（A16）等，见各段注释。
const LB = lbPageLib(dv, app, 'chat');
if (await LB.reuseDom()) return;
const root = dv.container;
// 这个仓可能被挂进别的库的子目录（如 LER Vault/知识库【小红书】/）；数据里的路径都相对 lwa 仓根，统一过 lbPath 补挂载前缀。
const lbPath = LB.path;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-chatpage');
const provider = LB.provider;
// A11：手机上（插件是桌面专用）或插件没启用 → 只读：排版照常、跳转可用、绝不写盘
const readOnly = !provider() || !!LB.mobile;
const SESSION_PATH = lbPath('_archive/chat-session.json');
const ARCHIVE_PATH = lbPath('_archive/chat-archive.json');
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const pageId = uid();
// 轮次稳定 id（A1）：旧会话没有 id 的这里补上，第一次写盘时带进文件
const ensureIds = turns => { for (const t of turns || []) if (t && (typeof t.id !== 'string' || !t.id)) t.id = uid(); return turns; };
// 磁盘读回的轮次并进内存：同 id 的轮次保留内存里的对象、原地换成磁盘字段（编辑框 / 视图闭包拿着的对象不失效），新的直接用磁盘对象
const adoptTurns = (mem, disk) => {
  const byId = new Map((mem || []).filter(t => t && t.id).map(t => [t.id, t]));
  return ensureIds(disk).map(d => {
    const m = d && byId.get(d.id); if (!m || m === d) return d;
    for (const k of Object.keys(m)) if (!(k in d)) delete m[k];
    return Object.assign(m, d);
  });
};

let data = {};
// 1019：事件订阅随页面暂存 / 拆（切走暂存时不被组件卸载强行摘掉）
function lbEvent(ref) { LB.onUnload(() => { try { app.workspace.offref(ref); } catch {} }); return ref; }
try { data = await LB.data.load(); } catch {}
let items = data.items || [];

let session = { turns: [], draft: '' };
let archive = { entries: [] };
try { session = JSON.parse(await app.vault.adapter.read(SESSION_PATH)); } catch {}
try { archive = JSON.parse(await app.vault.adapter.read(ARCHIVE_PATH)); } catch {}
session.turns = ensureIds(Array.isArray(session.turns) ? session.turns : []);
session.draft = typeof session.draft === 'string' ? session.draft : '';
// R2 会话状态（10-04）：排除 / 保留（pin）是整个会话的，跨轮生效——追问、重答都读这同一份；旧会话没这两个字段 = 空
const idList = v => Array.isArray(v) ? [...new Set(v.filter(x => typeof x === 'string' && x))] : [];
session.excluded = idList(session.excluded);
session.pinned = idList(session.pinned);
// 1015 她定：默认每问重新搜（'search'）；她点「改为在当前来源追问」才 'sources'（这一段对话里记住，followPicked 标明是她点的）。
// 页面偏好（_archive/chat-prefs.json，跨对话）：follow = 新对话的默认（缺省 'search'）；keepThread = 新问题接着这段问（缺省 false = 每问开新对话，上一段已自动进历史）
const PREFS_PATH = lbPath('_archive/chat-prefs.json');
let prefs = { follow: 'search', keepThread: false, report: false };
try { const raw = JSON.parse(await app.vault.adapter.read(PREFS_PATH)); prefs = { follow: raw.follow === 'sources' ? 'sources' : 'search', keepThread: !!raw.keepThread, report: !!raw.report }; } catch {}
// 读进来的会话（文件 / 历史 / 别页写的）统一过它：她没点过开关的一律按偏好默认
const followOf = o => (o && o.followPicked && (o.follow === 'search' || o.follow === 'sources') ? o.follow : prefs.follow);
session.follow = followOf(session);
session.followPicked = !!session.followPicked;
archive.entries = Array.isArray(archive.entries) ? archive.entries : [];
// 10-04 ⑤ 历史：每段对话一个 id；所有问答默认自动存进历史（_archive/chat-history/<id>.json + index.json），「清空」只是开始新的一段。
// 隐私模式（session.private）是个开关：开着时这段对话照样留在当前页（chat-session.json，换页回来还在），但不进历史；清空即没。
session.id = typeof session.id === 'string' && session.id ? session.id : uid();
session.startedAt = session.startedAt || session.turns.find(t => t.askedAt)?.askedAt || new Date().toISOString();
session.private = !!session.private;
const HISTORY_DIR = lbPath('_archive/chat-history');
const HISTORY_INDEX = HISTORY_DIR + '/index.json';
const historyFile = id => `${HISTORY_DIR}/${String(id).replace(/[^\w-]/g, '')}.json`;
const histOf = h => (h && Array.isArray(h.conversations) ? { conversations: h.conversations.filter(c => c && typeof c.id === 'string') } : null);
let hist = { conversations: [] };
try { hist = histOf(JSON.parse(await app.vault.adapter.read(HISTORY_INDEX))) || hist; } catch {}

// 草稿（正在打的字）只存 sessionStorage（§5.3）
const pageState = LB.state.load();
const saveDraft = v => LB.state.patch({ draft: v });
let lane = 'chat', busy = false;
// 第 3 批（CONVENTIONS §1.5）：写盘失败一律抛给调用方；M3：不再退回浏览器原生 alert
const notice = (msg, ms = 8000) => { try { new Notice(msg, ms); } catch { try { console.warn('[lb] chat', msg); } catch {} } };
const NOT_SAVED = '没保存上，内容还在，可重试：';
const BUSY_TEXT = '正在回答，答完再切换';
const errText = e => (e && e.message) || String(e || '未知原因');
// 所有写盘的唯一出口：只读（手机 / 插件没启用）一律不写——不产生同步冲突，也不会把失败写回电脑（A11）
const writeJson = (file, obj, pretty) => readOnly ? Promise.resolve() : app.vault.adapter.write(file, pretty ? JSON.stringify(obj, null, 2) : JSON.stringify(obj));
const sessionSnapshot = () => JSON.parse(JSON.stringify({ id: session.id, startedAt: session.startedAt, turns: session.turns, excluded: session.excluded, pinned: session.pinned, follow: session.follow, followPicked: session.followPicked, private: session.private }));
const firstQuestion = turns => (turns.find(t => t.role === 'user')?.content || '').trim();
const ensureHistoryDir = async () => { if (readOnly) return; try { if (!(await app.vault.adapter.exists?.(HISTORY_DIR))) await app.vault.adapter.mkdir?.(HISTORY_DIR); } catch {} };
// 插件级写链（§5.3 chatSaveChain）：几个问收藏页（含换页前那一页还在等回答的旧闭包）写会话 / 历史一律排队，不交叉覆盖
let localChain = Promise.resolve();
function enqueueWrite(fn) {
  const p = provider();
  const prev = (p && p.chatSaveChain) || localChain;
  const next = Promise.resolve(prev).catch(() => {}).then(fn);
  const tail = next.catch(() => {});
  if (p) p.chatSaveChain = tail; else localChain = tail;
  return next;
}
const announce = () => { try { app.workspace.trigger?.('link-brain:chat-session', pageId); } catch {} };
// 当前这段写进历史：对话文件 + 目录（目录写前先重读、按 id 合并，别的页刚写的那段不被冲掉）
async function saveToHistory(current) {
  if (readOnly || current.private || !current.turns.length) return;
  await ensureHistoryDir();
  await writeJson(historyFile(current.id), current);
  let base = hist;
  try { base = histOf(JSON.parse(await app.vault.adapter.read(HISTORY_INDEX))) || hist; } catch {}
  const entry = { id: current.id, startedAt: current.startedAt, updatedAt: new Date().toISOString(), title: firstQuestion(current.turns).slice(0, 120), turns: current.turns.filter(t => t.role === 'user').length };
  const next = { conversations: [entry, ...base.conversations.filter(c => c.id !== current.id)] };
  await writeJson(HISTORY_INDEX, next);
  hist = next;
}
async function dropFromHistory(ids) {
  const gone = new Set(ids);
  const next = { conversations: hist.conversations.filter(c => !gone.has(c.id)) };
  await writeJson(HISTORY_INDEX, next);
  hist = next;
  for (const id of gone) { try { if (!readOnly) await app.vault.adapter.remove?.(historyFile(id)); } catch {} }
}
const saveSession = async () => {
  const current = sessionSnapshot();
  await writeJson(SESSION_PATH, current);
  await saveToHistory(current);
};
// 经写链写一次会话，成功后广播（别的问收藏页据此重读）；抛错给调用方
const persist = () => enqueueWrite(saveSession).then(() => { if (!readOnly) announce(); });
const saveArchive = () => writeJson(ARCHIVE_PATH, archive, true);
const savePrefs = () => writeJson(PREFS_PATH, prefs, true);
// 对话轮次：内存里已经显示了，写不进文件只影响「重开页面还在不在」——如实说一句，不打断作答
const keepSession = () => persist().catch(e => { notice('对话没写进文件，重开这一页会丢：' + errText(e)); });
// 「已保存」栏的改动：快照 → 改 → 写盘；失败回滚快照、提示（§1.5 统一写法）
async function archiveChange(mutate) {
  const prev = JSON.stringify(archive.entries);
  mutate();
  try { await saveArchive(); return true; }
  catch (e) { archive.entries = JSON.parse(prev); notice(NOT_SAVED + errText(e)); return false; }
}
// 来源阅读（第 2 批）：引用编号、来源标题会打开来源，一律放进右侧同一个来源窗格（复用）。
// A12：「我保存的」来源在原地展开，不切整页；A11：没插件时走 openLinkText
// 1021 她：点引用要跳到正文那一处——seg（模型写的 [来源N 段k]）直接指定证据段；没段号就按点击那句的上下文挑最像的一段。
// 挑好的排第一，插件 openArchiveSource 只跳第一段（不出工具条、只滚原帖自己的滚动区）
function openNote(source, compare = false, context = '', fromCite = null, seg = null) {
  const src = typeof source === 'string' ? { note: source } : source;
  if (src?.source_kind === 'saved') { openSavedInline(src, fromCite); return; }
  const all = (src?.excerpts || []).filter(p => p && p.text);
  const picked = seg ? all.find(p => Number(p.seg) === Number(seg)) : null;
  let chunks = picked ? [picked, ...all.filter(p => p !== picked)] : all.slice();
  if (!picked && context) { const normalized = context.replace(/\s/g, '').toLowerCase(); const score = p => { const text = String(p.text).replace(/\s/g, '').toLowerCase(); let n = 0; for (let i = 0; i < normalized.length - 3; i++) if (text.includes(normalized.slice(i, i + 4))) n++; return n; }; chunks.sort((a, b) => score(b) - score(a)); }
  if (!src?.note) return;
  userAt = 0; dragging = false;   // 点来源这一下不是在滚（之前滚到一半的不算）
  const p = provider();
  if (!p || typeof p.openArchiveSource !== 'function') {
    try { return Promise.resolve(app.workspace.openLinkText(lbPath(src.note), '', false)).catch(e => notice('打不开来源：' + errText(e))); }
    catch (e) { notice('打不开来源：' + errText(e)); return; }
  }
  // 1022 她：真机点引用没跳——插件没重载还是旧 main.js（关开插件也不保险）。改成页面自己定位：页面脚本每次重开都是新的，
  // 插件只负责把笔记开到右栏（证据传空，免得新插件也跳一次）。定位结果写 _archive/locate-last.json（排障用，fail-open）
  return Promise.resolve().then(() => p.openArchiveSource(src.note, root, compare, [])).then(() => { paintSourceBar(); settle(); watchReaderVideos(src.note); })
    .then(() => chunks.length ? locateInReader(src, chunks[0]) : null)
    .catch(e => notice('打不开来源：' + errText(e)));
}
// ── 1022 点引用 → 右栏原帖那一处（页面侧实现；和插件 locateOnePassage 同一套规则）──
// 先按锚点直达（render 1021 起：<p data-p=段序号> / <article data-cid=楼号>；证据段带 paras / comment_labels / assets），
// 锚点对不上原文（旧渲染）再逐字找；图片按文件名切轮播。只滚原帖自己的滚动区（boardScrollWithin），原句包临时 span 亮 6 秒。
function passageCompact(s) { return String(s || '').normalize('NFKC').replace(/\s+/g, '').toLowerCase(); }
function passageTargetIn(box, part) {
  const quote = passageCompact(part.text);
  const run = (a, b, w) => { for (let i = 0; i + w <= a.length; i++) if (b.includes(a.slice(i, i + w))) return true; return false; };
  const verify = el => { const text = passageCompact(el.textContent); if (!quote || !text) return false; if (quote.length < 24) return quote.length >= 6 && (text.includes(quote) || quote.includes(text)); if (text.length < 12) return quote.includes(text); return quote.includes(text) || run(text, quote, 24) || run(quote, text, 24); };
  if (part.field === 'ocr' || part.field === 'comment_ocr') {
    const assets = (part.assets || []).map(x => String(x).replace(/\\/g, '/')); const names = assets.map(a => a.split('/').pop());
    // 1022 她：视频帖封面的识别文字——封面图那张 slide 在视频帖里是 display:none（CSS 563），要落到 <video poster=封面> 上；同名多处时挑看得见的
    const same = u => { const src = decodeURIComponent(u || '').replace(/\\/g, '/').split('?')[0]; const name = src.split('/').pop(); return assets.some(a => src.endsWith('/' + a) || src === a) || names.some(n => n && name === n); };
    const all = [...box.querySelectorAll('.lb-slide img, .lb-slide video[poster], img.lb-comment-image')].filter(m => same(m.getAttribute('src')) || same(m.getAttribute('poster')));
    const visible = all.find(m => m.getClientRects().length > 0);
    return { el: visible || all[0] || null, how: visible ? 'asset' : all[0] ? 'asset-hidden' : 'none' };
  }
  const anchors = [];
  if (part.field === 'comments') { for (const l of part.comment_labels || []) { const el = box.querySelector(`article.lb-comment[data-cid="${String(l).replace(/[^\w.]/g, '')}"] .lb-comment-text`); if (el) anchors.push(el); } }
  else if (['body', 'transcript', 'screen'].includes(part.field)) {
    const scope = part.field === 'body' ? '.lb-body' : '.lb-transcript .lb-body';
    for (const i of part.paras || []) for (const el of box.querySelectorAll(`${scope} p[data-p="${Number(i)}"]`)) { if (part.field === 'body' && el.closest('.lb-transcript')) continue; anchors.push(el); }
  }
  const ok = anchors.find(verify); if (ok) return { el: ok, how: 'anchor', anchors: anchors.length };
  if (anchors.length && !quote) return { el: anchors[0], how: 'anchor-noquote', anchors: anchors.length };
  const selectors = { body: '.lb-body p', comments: '.lb-comment-text', transcript: '.lb-transcript .lb-body p', screen: '.lb-transcript .lb-body p' };
  if (!selectors[part.field]) return { el: null, how: 'nofield', anchors: anchors.length };
  const el = [...box.querySelectorAll(selectors[part.field])].filter(el => !(part.field === 'body' && el.closest('.lb-transcript'))).find(verify) || null;
  return { el, how: el ? 'text' : 'none', anchors: anchors.length };
}
function markPassageIn(el, quote) {
  const q = passageCompact(quote); const nodes = []; const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let all = '';
  while (tw.nextNode()) { nodes.push([tw.currentNode, all.length]); all += tw.currentNode.nodeValue; }
  const score = s => { const c = passageCompact(s); let n = 0; for (let i = 0; i + 6 <= c.length; i++) if (q.includes(c.slice(i, i + 6))) n++; return n; };
  let best = null;
  for (const seg of all.matchAll(/[^。！？!?；;\n]+[。！？!?；;]?/g)) { if (!passageCompact(seg[0])) continue; const s = score(seg[0]); if (s > 0 && (!best || s > best.s)) best = { s, a: seg.index, b: seg.index + seg[0].length }; }
  const flash = () => { el.classList.add('lb-evidence-hit'); setTimeout(() => el.classList.remove('lb-evidence-hit'), 6000); return el; };
  if (!best || passageCompact(all).length < 40) return flash();
  const marks = [];
  for (const [node, off] of nodes) { const a = Math.max(best.a, off), b = Math.min(best.b, off + node.nodeValue.length); if (a >= b) continue; const r = document.createRange(); r.setStart(node, a - off); r.setEnd(node, b - off); const mk = document.createElement('span'); mk.className = 'lb-evidence-hit lb-locate-mark'; try { r.surroundContents(mk); marks.push(mk); } catch {} }
  if (!marks.length) return flash();
  setTimeout(() => { for (const mk of marks) { const p = mk.parentNode; if (!p) continue; while (mk.firstChild) p.insertBefore(mk.firstChild, mk); p.removeChild(mk); p.normalize?.(); } }, 6000);
  return marks[0];
}
async function locateInReader(src, part) {
  const log = { at: new Date().toISOString(), note: src?.note, field: part?.field, seg: part?.seg, labels: part?.comment_labels || part?.paras || part?.assets || null, text: String(part?.text || '').slice(0, 60) };
  const done = async (ok, why) => {
    Object.assign(log, { ok, why });
    try { await app.vault.adapter.write(lbPath('_archive/locate-last.json'), JSON.stringify(log, null, 1)); } catch {}
    if (!ok) notice(why === 'no-reader' ? '右栏没打开原帖，跳不过去' : why === 'not-rendered' ? '原帖还没画完，再点一次引用' : '原帖里没找到引用的那一段，只打开了原帖', 4000);
    return ok;
  };
  const p = provider();
  let box = null;
  for (let i = 0; i < 20 && !box; i++) { try { box = p?.archiveLeaves?.(root)?.reader?.view?.containerEl || null; } catch {} if (!box) await new Promise(r => setTimeout(r, 100)); }
  if (!box) return done(false, 'no-reader');
  // 大帖（几百楼评论）Obsidian 要画好几秒：最多等 12 秒
  let i = 0; for (; i < 120 && !box.querySelector('.lb-note, .lb-body'); i++) await new Promise(r => setTimeout(r, 100));
  log.waitMs = i * 100; log.comments = box.querySelectorAll('article.lb-comment').length; log.paras = box.querySelectorAll('.lb-body p[data-p]').length;
  if (!box.querySelector('.lb-note, .lb-body')) return done(false, 'not-rendered');
  box.querySelectorAll('.lb-evidence-hit').forEach(el => el.classList.remove('lb-evidence-hit'));
  const { el, how, anchors } = passageTargetIn(box, part);
  log.how = how; log.anchors = anchors;
  if (!el) return done(false, 'not-found');
  let up = el.parentElement; while (up && up !== box) { if (up.tagName === 'DETAILS') up.open = true; up = up.parentElement; }
  const carousel = el.closest('.lb-carousel');
  const flashMedia = m => { m.classList.add('lb-evidence-hit', 'lb-media-hit'); setTimeout(() => m.classList.remove('lb-evidence-hit', 'lb-media-hit'), 6000); };
  const mediaLog = m => { log.inView = m.getClientRects().length > 0 && (() => { const r = m.getBoundingClientRect(), b = box.getBoundingClientRect(); return r.bottom > b.top && r.top < b.bottom; })(); };
  if (carousel) { const slide = el.closest('.lb-slide'); const first = carousel.querySelector('.lb-slide'); if (slide) carousel.scrollLeft = slide.offsetLeft - (first ? first.offsetLeft : 0); boardScrollWithin(carousel, box); flashMedia(el); mediaLog(el); return done(true, 'image'); }
  if (el.tagName === 'IMG' || el.tagName === 'VIDEO') { boardScrollWithin(el, box); flashMedia(el); mediaLog(el); return done(true, 'image'); }
  const target = markPassageIn(el, part.text);
  boardScrollWithin(target, box);
  log.scrolled = [...(function* () { for (let u = target.parentElement; u && u !== box.parentElement; u = u.parentElement) if (boardScrollable(u)) yield (u.className || u.tagName).toString().slice(0, 40) + '@' + Math.round(u.scrollTop); })()];
  log.inView = (() => { const r = target.getBoundingClientRect(), b = box.getBoundingClientRect(); return r.top >= b.top && r.bottom <= b.bottom; })();
  return done(true, how);
}
// 1015 右栏来源里的视频没首图（审计 F：问收藏这边没调 fixVideos）。和笔记页 annotate-view 的 fixVideos 同一个修法：
// Obsidian 阅读视图只改写 <video src>、不改 poster → 把 poster 按笔记所在目录解析成能加载的地址，按封面比例定框，点了再加载视频。
// 右侧阅读格是异步画的（还会重画），盯 8 秒 DOM 变化，幂等（dataset.lbPoster）。
function fixVideosIn(view, note) {
  if (!view?.querySelectorAll) return 0;
  const folder = String(lbPath(note || '')).split('/').slice(0, -1).join('/');
  let n = 0;
  for (const v of view.querySelectorAll('video')) {
    const raw = v.getAttribute && v.getAttribute('poster');
    if (!raw || v.dataset.lbPoster === raw) continue;
    v.dataset.lbPoster = raw;
    if (/^(app|https?|data|blob|capacitor):/i.test(raw)) continue;
    const parts = [];
    for (const seg of (folder ? folder + '/' + raw : raw).split('/')) { if (!seg || seg === '.') continue; if (seg === '..') parts.pop(); else parts.push(seg); }
    let url = '';
    try { url = app.vault.adapter.getResourcePath(decodeURIComponent(parts.join('/'))); } catch { continue; }
    if (!url) continue;
    v.setAttribute('poster', url); v.dataset.lbPoster = url; v.preload = 'none'; n++;
    try {
      const img = new Image();
      img.onload = () => { if (!img.naturalWidth || !img.naturalHeight) return; Object.assign(v.style, { aspectRatio: img.naturalWidth + ' / ' + img.naturalHeight, width: '100%', height: 'auto', maxHeight: '75vh', objectFit: 'contain', background: 'transparent', borderRadius: 'inherit' }); };
      img.src = url;
    } catch {}
  }
  return n;
}
let readerVideoWatch = null;
function watchReaderVideos(note) {
  try { readerVideoWatch?.(); } catch {}
  readerVideoWatch = null;
  const p = provider();
  let leaves = null;
  try { leaves = p?.archiveLeaves?.(root); } catch {}
  const panes = [leaves?.reader, leaves?.compare].map(l => l?.view?.containerEl).filter(Boolean);
  if (!panes.length) return;
  for (const v of panes) fixVideosIn(v, note);
  if (typeof MutationObserver !== 'function') return;
  let queued = false;
  const mo = new MutationObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; for (const v of panes) fixVideosIn(v, note); }); });
  for (const v of panes) mo.observe(v, { childList: true, subtree: true });
  const timer = setTimeout(() => mo.disconnect(), 8000);
  readerVideoWatch = () => { clearTimeout(timer); mo.disconnect(); };
}

// 样式挂 head（LB.style 按 id 去重；lb-shared 排在它前面）。X14：从目录页抄来的 .lb-page-nav / .lb-manage / .lbc-* 规则删了，那些在 lb-shared 里
LB.style('lbchat-style', `
.markdown-preview-view.lb-chatpage,.markdown-source-view.lb-chatpage{--file-line-width:100%;}
.lb-chatpage .markdown-preview-sizer,.lb-chatpage .markdown-preview-section,.lb-chatpage .cm-sizer,.lb-chatpage .cm-contentContainer,.lb-chatpage .cm-content,.lb-chatpage .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-chatpage .inline-title,.lb-chatpage .metadata-container{display:none!important;}
.lbchat{max-width:720px;margin:0 auto;padding:28px clamp(14px,3vw,20px) 120px;font-family:var(--font-interface),"Segoe UI","Microsoft YaHei",sans-serif;color:var(--text-normal);}
.lbchat-head{display:flex;flex-direction:column;align-items:center;text-align:center;gap:12px;margin:8px 0 22px;}
.lbchat-titleblock{display:flex;flex-direction:column;align-items:center;gap:6px;}
.lbchat-titlerow{display:flex;align-items:baseline;justify-content:center;gap:9px;}
.lbchat-title{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:42px;font-weight:700;letter-spacing:.01em;line-height:1.05;color:var(--text-normal);}
.lbchat-plus{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:40px;font-weight:700;line-height:1;color:var(--text-normal);cursor:pointer;transition:color .12s;}
.lbchat-plus:hover{color:var(--interactive-accent);}
.lbchat-sub{font-size:12px;color:var(--text-faint);letter-spacing:.02em;}
.lbchat-search{width:100%;max-width:440px;height:38px;text-align:center;border:none!important;border-bottom:1px solid var(--background-modifier-border)!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;padding:0 2px!important;font-size:15px!important;color:var(--text-normal);margin-top:2px;transition:border-color .15s;}
.lbchat-search:focus{outline:none;border-bottom-color:var(--interactive-accent)!important;box-shadow:none!important;}
.lbchat-search[hidden]{display:none;}
.lbchat-nav{display:flex;align-items:center;justify-content:center;gap:16px;margin:0 0 32px;flex-wrap:wrap;}
.lbchat-navsep{color:var(--background-modifier-border);user-select:none;}
.lbchat-tab{cursor:pointer;font-size:13px;color:var(--text-faint);padding:2px 0;transition:color .12s;}
.lbchat-tab:hover{color:var(--text-muted);}
.lbchat-tab.is-on{color:var(--text-normal);font-weight:600;}
.lbchat-clear{cursor:pointer;font-size:12px;color:var(--text-faint);transition:color .12s;}
.lbchat-clear:hover{color:var(--text-error,#e5534b);}
.lbchat-clear[hidden]{display:none;}
.lbchat-body{min-height:40px;}
.lbchat-empty{color:var(--text-faint);font-size:14px;line-height:1.9;padding:8px 0;}
.lbchat-turn{margin:0 0 26px;line-height:1.8;font-size:15px;overflow-wrap:anywhere;content-visibility:auto;contain-intrinsic-size:auto 320px;}
/* 1020：content-visibility 会把 position:fixed 关在这一轮里——mermaid「放大看」那一轮放开（否则铺不满窗口） */
.lbchat-turn:has(.lbchat-mmd.is-full){content-visibility:visible;contain:none;}
.lbchat-user{color:var(--text-normal);font-weight:500;}
.lbchat-user .lbchat-qmark{color:var(--text-faint);margin-right:8px;}
.lbchat-answer{line-height:1.8;}
.lbchat-md p:first-child{margin-top:0;}
.lbchat-md p:last-child{margin-bottom:0;}
.lbchat-actions{display:flex;gap:16px;margin-top:10px;}
.lbchat-act{cursor:pointer;font-size:12px;color:var(--text-faint);transition:color .12s;}
.lbchat-act:hover{color:var(--interactive-accent);}
.lbchat-src{margin-top:12px;font-size:12px;color:var(--text-muted);}
.lbchat-src summary{cursor:pointer;color:var(--text-faint);}
.lbchat-src a{cursor:pointer;color:var(--link-color);}
.lbchat-hits{display:flex;flex-direction:column;gap:16px;}
.lbchat-hit{cursor:pointer;}
.lbchat-hit-title{font-size:14px;font-weight:600;color:var(--text-normal);}
.lbchat-hit-title:hover{color:var(--interactive-accent);}
.lbchat-hit-meta{font-size:12px;color:var(--text-faint);margin-top:2px;}
.lbchat-hit-ex{font-size:13px;color:var(--text-muted);line-height:1.65;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbchat-think{display:flex;align-items:center;gap:8px;color:var(--text-muted);font-size:14px;margin:0 0 26px;}
.lbchat-dot{width:6px;height:6px;border-radius:50%;background:var(--interactive-accent);opacity:.5;animation:lbchatpulse 1s ease-in-out infinite;}
@keyframes lbchatpulse{0%,100%{opacity:.25;transform:scale(.8);}50%{opacity:1;transform:scale(1);}}
.lbchat-arc-add{display:flex;gap:10px;align-items:flex-end;margin:0 0 24px;width:100%;box-sizing:border-box;}
.lbchat-arc-input{flex:1 1 auto;min-width:16em;width:100%;resize:vertical;min-height:38px;border:none;border-bottom:1px solid var(--background-modifier-border);border-radius:0;background:transparent;color:var(--text-normal);font:inherit;font-size:14px;padding:6px 2px;box-sizing:border-box;}
.lbchat-arc-input:focus{border-bottom-color:var(--interactive-accent);outline:none;}
.lbchat-arc-save{cursor:pointer;font-size:13px;color:var(--text-faint);padding-bottom:8px;white-space:nowrap;}
.lbchat-arc-save:hover{color:var(--interactive-accent);}
.lbchat-arc-item{margin:0 0 24px;}
.lbchat-arc-meta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text-faint);margin-bottom:5px;}
.lbchat-arc-kind{color:var(--interactive-accent);}
.lbchat-arc-del{margin-left:auto;cursor:pointer;opacity:0;transition:opacity .12s;}
.lbchat-arc-item:hover .lbchat-arc-del{opacity:1;}
.lbchat-arc-del:hover{color:var(--text-error,#e5534b);}
.lbchat-arc-body{line-height:1.8;font-size:15px;}
.lbchat-live-tail{white-space:pre-wrap;}
.lbchat{max-width:1440px;box-sizing:border-box;padding:32px clamp(16px,3vw,48px) 80px;font-family:"Noto Sans SC","Segoe UI","Microsoft YaHei UI",sans-serif;}
.lbchat-head{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;text-align:left;gap:28px 20px;margin:0 0 60px;}
.lbchat-titleblock{align-items:flex-start;gap:10px;grid-column:1;grid-row:1;}
.lbchat-tools{grid-column:3;grid-row:1;justify-self:end;display:flex;align-items:center;gap:10px;}
.lbchat button.lbchat-plus{font-family:Georgia,serif;font-size:40px;font-weight:700;font-style:italic;background:transparent;border:0;box-shadow:none;width:40px;height:44px;padding:0;}
.lbchat-sub{font-size:11px;letter-spacing:.06em;}
.lbchat-composer{max-width:700px;margin:0 auto 18px;display:flex;align-items:flex-end;gap:12px;padding:14px;border:1px solid var(--background-modifier-border);border-radius:18px;background:var(--background-secondary);}
.lbchat-composer:focus-within{border-color:var(--interactive-accent);}
.lbchat-composer[hidden]{display:none;}
.lbchat-search{flex:1;min-width:0;max-width:none;box-sizing:border-box;resize:vertical;min-height:64px;height:64px;text-align:left;border:0!important;padding:4px!important;font:inherit!important;font-size:15px!important;line-height:1.6;}
.lbchat-send{background:var(--text-normal)!important;color:var(--background-primary)!important;box-shadow:none!important;border:0!important;border-radius:10px;height:36px;padding:0 16px;flex:none;cursor:pointer;}
.lbchat-mic{display:none!important;background:transparent!important;box-shadow:none!important;border:0!important;height:36px;width:36px;padding:0;flex:none;display:grid;place-items:center;color:var(--text-muted);cursor:pointer;border-radius:10px;}
.lbchat-mic:hover{color:var(--text-normal);background:var(--background-modifier-hover)!important;}
.lbchat-mic.is-recording{color:var(--color-red);animation:lbchat-rec 1.1s ease-in-out infinite;}
@keyframes lbchat-rec{50%{opacity:.35;}}
.lbchat-send:disabled{opacity:.4;cursor:wait;}
.lbchat button.lbchat-stop{flex:none;width:36px;height:36px;padding:0;border-radius:50%!important;display:grid;place-items:center;border:1px solid var(--background-modifier-border)!important;background:var(--background-secondary)!important;color:var(--text-normal);box-shadow:none!important;cursor:pointer;}
.lbchat button.lbchat-stop[hidden]{display:none;}
.lbchat button.lbchat-stop:disabled{opacity:.5;cursor:wait;}
.lbchat-nav{max-width:700px;justify-content:flex-start;margin:0 auto 32px;gap:24px;}
.lbchat button.lbchat-tab{border:0!important;background:transparent!important;box-shadow:none!important;border-radius:0;padding:8px 0;font-family:inherit;font-size:13px;height:auto;}
.lbchat button.lbchat-tab.is-on{border-bottom:2px solid var(--text-normal)!important;}
.lbchat-clear{display:none!important;}
.lbchat-body{max-width:700px;margin:0 auto;}
.lbchat-empty{font-size:13px;}
.lbchat-user{margin-left:auto;background:var(--background-secondary);border-radius:14px;padding:10px 16px;width:fit-content;max-width:90%;}
.lbchat button.lbchat-act,.lbchat button.lbchat-arc-del{font-family:inherit;background:transparent;border:0;box-shadow:none;padding:0;font-size:12px;height:auto;}
.lbchat-arc-del{opacity:1;}
@media(max-width:700px){.lbchat{padding:20px 12px 48px;}.lbchat-head{grid-template-columns:1fr auto;gap:24px 10px;margin-bottom:36px;}.lbchat-tools{grid-column:2;}.lbchat-title{font-size:34px;}.lbchat button.lbchat-plus{font-size:32px;}.lbchat-head .lb-page-nav{grid-column:1/-1;grid-row:2;justify-self:start;}.lbchat-composer{padding:12px;gap:8px;}.lbchat-send{padding:0 12px;}}
.lbchat{height:calc(100vh - 110px);display:flex;flex-direction:column;padding:22px 24px 0;overflow:hidden;}
.lbchat-head{flex:none;grid-template-columns:1fr auto;gap:14px;margin:0 0 20px;}
.lbchat-title{font-size:32px;}.lbchat-tools{grid-column:2;gap:12px;flex-wrap:wrap;justify-content:flex-end;}
.lbchat-head .lb-page-nav{grid-column:1/-1;grid-row:2;justify-self:start;background:transparent;padding:0;}
.lbchat-nav{display:none;}.lbchat-body{flex:1;min-height:0;overflow:auto;width:100%;max-width:850px;padding:0 8px 24px;box-sizing:border-box;}
.lbchat-composer{flex:none;width:100%;max-width:850px;box-sizing:border-box;margin:0 auto;padding:10px 12px;border-radius:10px;background:var(--background-primary);}
.lbchat-search{height:38px;min-height:38px;max-height:160px;margin:0;}.lbchat-turn{font-size:14px;line-height:1.85;}
.lbchat button.lbchat-tab{font-size:12px;}
.lbchat-editor{width:100%;min-height:120px;max-height:70vh;font:inherit;line-height:1.7;resize:none;overflow-y:auto;scrollbar-width:none;box-sizing:border-box;}
.lbchat-editbar{display:flex;gap:12px;margin:8px 0;}
.lbchat-srcbar{flex:none;width:100%;max-width:850px;margin:8px auto -12px;box-sizing:border-box;display:flex;align-items:center;gap:14px;padding:0 8px;font-size:12px;color:var(--text-faint);}
.lbchat-srcbar[hidden]{display:none;}
.lbchat-body:not(.lbchat-has-reader) .lbchat-addcmp{display:none;}
@media(max-width:700px){.lbchat{padding:12px 6px 0;}.lbchat-title{font-size:28px;}.lbchat-tools{gap:8px;}.lbchat-head{gap:10px;margin-bottom:18px;}.lbchat-composer{padding:8px;}.lbchat-body{padding:0 4px 20px;}}
.lbchat .lbchat-composer{align-items:center;gap:6px;padding:8px 10px 8px 14px;border-radius:28px;border:1px solid var(--background-modifier-border);background:var(--background-primary);box-shadow:0 2px 12px #0000000f;}
.lbchat .lbchat-composer:focus-within{border-color:var(--background-modifier-border-hover);}
.lbchat .lbchat-search{height:40px;min-height:40px;max-height:160px;overflow-y:auto;scrollbar-width:none;resize:none;padding:9px 4px!important;background:transparent!important;box-shadow:none!important;}
.lbchat .lbchat-search::placeholder{color:var(--text-faint);}
.lbchat button.lbchat-cplus{flex:none;width:34px;height:34px;padding:0;border:0!important;box-shadow:none!important;background:transparent!important;font-size:24px;font-weight:300;line-height:1;color:var(--text-normal);border-radius:50%;cursor:pointer;}
.lbchat button.lbchat-cplus:hover{background:var(--background-modifier-hover)!important;}
.lbchat .lbchat-model{flex:none;max-width:130px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);font:inherit;font-size:13px;cursor:pointer;padding:0 4px;}
.lbchat .lbchat-model[hidden]{display:none;}
.lbchat .lbchat-mic{border-radius:50%;}
.lbchat button.lbchat-send{width:36px;height:36px;padding:0;border-radius:50%!important;display:grid;place-items:center;}
.lbchat-queue{flex:none;width:100%;max-width:850px;margin:12px auto -14px;box-sizing:border-box;display:flex;flex-direction:column;gap:6px;}
.lbchat-queue[hidden]{display:none;}
.lbchat-queued{display:flex;align-items:center;gap:8px;padding:6px 10px 6px 14px;border-radius:14px;background:var(--background-secondary);font-size:13px;color:var(--text-muted);}
.lbchat-queued-tag{font-size:11px;color:var(--text-faint);flex:none;}
.lbchat-queued-text{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbchat button.lbchat-queued-x{flex:none;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-faint);font-size:16px;padding:0 4px;height:auto;cursor:pointer;}
.lbchat button.lbchat-queued-x:hover{color:var(--text-normal);}
.lbchat button.lbchat-queued-now{flex:none;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);font-size:12px;padding:0 6px;height:auto;cursor:pointer;white-space:nowrap;}
.lbchat button.lbchat-queued-now:hover{color:var(--text-normal);}
.lbchat-bookmark svg{width:18px;height:18px;display:block;stroke:currentColor;stroke-width:1.6;fill:none;}.lbchat-bookmark.is-saved svg{fill:currentColor;}
.lbchat .lbchat-composer{margin-top:24px;margin-bottom:14px;}.lbchat{height:calc(100vh - 80px);}
.lbchat-hist{background:transparent;border:0;color:var(--text-muted);cursor:pointer;padding:6px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;transition:color .12s,background .12s;}
.lbchat-hist:hover{color:var(--text-normal);background:var(--background-modifier-hover);}
.lbchat-histpanel{position:fixed;width:360px;max-height:60vh;overflow:auto;background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.22);padding:6px;z-index:9999;}
.lbchat-histhead{display:flex;align-items:center;justify-content:space-between;padding:6px 8px 8px;font-size:12px;color:var(--text-muted);border-bottom:1px solid var(--background-modifier-border);margin-bottom:4px;}
.lbchat-histclear{cursor:pointer;font-size:12px;color:var(--text-error,#e5534b);background:transparent;border:0;padding:2px 6px;border-radius:6px;}
.lbchat-histclear:hover{background:var(--background-modifier-hover);}
.lbchat-histclear:disabled{opacity:.4;cursor:default;}
.lbchat-histitem{display:block;width:100%;text-align:left;background:transparent;border:0;cursor:pointer;font-size:13px;color:var(--text-normal);padding:8px 8px;border-radius:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lbchat-histitem:hover{background:var(--background-modifier-hover);}
.lbchat-histempty{padding:14px 8px;font-size:12px;color:var(--text-faint);text-align:center;}
.lbchat-titleblock{align-items:center;width:max-content;max-width:100%;}
.lbchat-titlerow{align-items:center;gap:10px;}
/* 0925：「+」放进标题里继承同一套字，与目录页一致 */.lbchat-title button.lbchat-plus{font:inherit!important;color:var(--text-normal)!important;transition:color .12s;width:auto!important;height:auto!important;padding:0 0 0 .12em!important;margin:0!important;border:0!important;background:transparent!important;box-shadow:none!important;border-radius:0!important;display:inline!important;vertical-align:baseline;line-height:inherit!important;cursor:pointer;}.lbchat-title button.lbchat-plus:hover{color:var(--interactive-accent)!important;}
.lbchat-export summary{cursor:pointer;color:var(--text-muted);}.lbchat-export[open]{padding:6px;border-radius:8px;background:var(--background-secondary);}.lbchat-export label{font-size:12px;margin-right:8px;}
/* 10-04（她定）④ 整页外面那层 dataviewjs 代码块的框（边框 / 底色 / 圆角 / 悬停时的「编辑代码块」按钮）一律隐形：阅读视图 + 实时预览 */
:is(.lb-chatpage,.lb-catalog,.lb-trashpage) :is(.el-pre:has(.block-language-dataviewjs),pre:has(.block-language-dataviewjs),.block-language-dataviewjs,.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs),
:is(.lb-chatpage,.lb-catalog,.lb-trashpage) :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-preview-code-block.cm-lang-dataviewjs):hover{border:0!important;background:transparent!important;box-shadow:none!important;outline:0!important;border-radius:0!important;}
:is(.lb-chatpage,.lb-catalog,.lb-trashpage) :is(.cm-embed-block:has(.block-language-dataviewjs),.cm-lang-dataviewjs) .edit-block-button{display:none!important;}
/* ③ 对话区不要那条可拖的内滚动条：照样能滚（滚轮 / 触摸 / 键盘），回答时照样跟到底，只是不画滚动条 */
.lbchat .lbchat-body,.markdown-preview-view.lb-chatpage{scrollbar-width:none;}
.lbchat .lbchat-body::-webkit-scrollbar,.markdown-preview-view.lb-chatpage::-webkit-scrollbar{display:none;width:0;height:0;}
/* ① 「清空」：输入框左上方那行来源小字旁边，同款浅色小字按钮（标题旁的「+」去掉了） */
.lbchat button.lbchat-follow-switch.lbchat-clearall:hover:not(:disabled){color:var(--text-error,#e5534b);}
.lbchat button.lbchat-follow-switch.lbchat-clearall:disabled{opacity:.45;cursor:default;}
/* ② 追问绑定当前来源：输入框上面一行小字 + 开关 */
.lbchat-followbar{flex:none;width:100%;max-width:850px;margin:10px auto -16px;box-sizing:border-box;display:flex;align-items:center;gap:6px;padding:0 14px;font-size:12px;color:var(--text-faint);}
.lbchat-followbar[hidden]{display:none;}
.lbchat button.lbchat-follow-switch{font:inherit;font-size:12px;color:var(--text-muted);background:transparent!important;border:0!important;box-shadow:none!important;padding:0 2px;height:auto;cursor:pointer;text-decoration:underline;text-decoration-color:var(--background-modifier-border);text-underline-offset:3px;}
.lbchat button.lbchat-follow-switch:hover{color:var(--text-normal);text-decoration-color:currentColor;}
.lbchat-user .lbchat-qmark.is-follow{display:block;margin:0 0 2px;font-size:11px;font-weight:400;line-height:1.5;}
/* ⑤ 回答排版：标题别太大、段距行距舒服、列表缩进正常、引用块浅色左线；跟随主题变量（明暗都行） */
.lbchat .lbchat-turn{margin-bottom:28px;}
.lbchat .lbchat-user{font-size:14px;line-height:1.7;padding:9px 15px;border-radius:16px 16px 4px 16px;color:var(--text-normal);}
.lbchat .lbchat-answer{font-size:14.5px;line-height:1.78;color:var(--text-normal);}
.lbchat .lbchat-answer p{margin:0 0 .7em;}
.lbchat .lbchat-answer h1,.lbchat .lbchat-answer h2,.lbchat .lbchat-answer h3,.lbchat .lbchat-answer h4,.lbchat .lbchat-answer h5,.lbchat .lbchat-answer h6{font-family:inherit;font-weight:650;line-height:1.5;color:var(--text-normal);letter-spacing:0;border:0;padding:0;}
.lbchat .lbchat-answer h1{font-size:1.16em;margin:1.15em 0 .45em;}
.lbchat .lbchat-answer h2{font-size:1.08em;margin:1.05em 0 .4em;}
.lbchat .lbchat-answer h3,.lbchat .lbchat-answer h4,.lbchat .lbchat-answer h5,.lbchat .lbchat-answer h6{font-size:1em;margin:.9em 0 .3em;}
.lbchat .lbchat-md > :first-child,.lbchat .lbchat-md > :first-child > :first-child{margin-top:0;}
.lbchat .lbchat-answer ul,.lbchat .lbchat-answer ol{margin:.15em 0 .75em;padding-left:1.45em;}
.lbchat .lbchat-answer li{margin:.18em 0;padding-left:.1em;}
.lbchat .lbchat-answer li > ul,.lbchat .lbchat-answer li > ol{margin:.1em 0 .2em;}
.lbchat .lbchat-answer li > p{margin:0;}
.lbchat .lbchat-answer blockquote{margin:.5em 0 .8em;padding:.05em 0 .05em .9em;border:0;border-left:2px solid var(--background-modifier-border);background:transparent;color:var(--text-muted);font-style:normal;}
.lbchat .lbchat-answer blockquote p{margin:.2em 0;}
.lbchat .lbchat-answer hr{border:0;border-top:1px solid var(--background-modifier-border);margin:1.1em 0;}
.lbchat .lbchat-answer strong{font-weight:600;}
.lbchat .lbchat-answer code{font-size:.88em;padding:.1em .35em;border-radius:4px;background:var(--background-secondary);}
.lbchat .lbchat-answer pre code{padding:0;background:transparent;}
.lbchat .lbchat-answer table{border-collapse:collapse;margin:.4em 0 .9em;font-size:.95em;}
.lbchat .lbchat-answer th,.lbchat .lbchat-answer td{border:1px solid var(--background-modifier-border);padding:4px 9px;}
/* [来源N] 小胶囊：不抢眼，悬停才显链接色 */
.lbchat button.lbchat-cite{display:inline-block!important;font:inherit!important;font-size:11px!important;line-height:1.55!important;vertical-align:1px;margin:0 2px;padding:0 6px!important;height:auto;border:0!important;box-shadow:none!important;border-radius:999px!important;background:var(--background-modifier-hover)!important;color:var(--text-muted)!important;cursor:pointer;white-space:nowrap;}
.lbchat button.lbchat-cite:hover{color:var(--link-color)!important;background:var(--background-secondary)!important;}
/* 1022 点引用落到图 / 视频上：描一圈会被轮播裁掉，改成外发光脉冲，看得见 */
.lb-source-reader .lb-media-hit,.xhs-note .lb-media-hit{outline:none!important;box-shadow:0 0 0 4px var(--interactive-accent),0 0 18px 4px var(--interactive-accent)!important;animation:lbmediahit 1s ease-in-out 4;}
@keyframes lbmediahit{0%,100%{box-shadow:0 0 0 4px var(--interactive-accent),0 0 18px 4px var(--interactive-accent)}50%{box-shadow:0 0 0 1px var(--interactive-accent),0 0 4px 1px var(--interactive-accent)}}
/* 1021 悬停引用 → 原文小卡 */
.lbchat-citepop{position:fixed;z-index:9999;width:min(360px,calc(100vw - 16px));padding:8px 11px;border-radius:10px;background:var(--background-primary);border:1px solid var(--background-modifier-border);box-shadow:0 8px 28px rgba(0,0,0,.18);font-size:12px;line-height:1.55;color:var(--text-normal);pointer-events:none;}
.lbchat-citepop .t{font-weight:600;margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbchat-citepop .w{color:var(--text-faint);font-size:11px;margin-bottom:3px;}
.lbchat-citepop .q{color:var(--text-muted);display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical;overflow:hidden;white-space:pre-line;}
.lbchat .lbchat-actions{gap:18px;margin-top:12px;align-items:center;flex-wrap:wrap;}
/* ⑥ 来源：收起时「主要依据 · N」后面一行浅色小字告诉她能在里面保留 / 删除；展开后每行 保留 / × 是同样醒目的小按钮 */
.lbchat .lbchat-src{margin-top:14px;font-size:12.5px;}
.lbchat .lbchat-src > summary{color:var(--text-muted);padding:2px 0;}
.lbchat .lbchat-src > summary:hover{color:var(--text-normal);}
.lbchat-src-hint{margin-left:10px;font-size:11.5px;color:var(--text-faint);}
.lbchat-src-kept{margin-left:10px;font-size:11.5px;color:var(--interactive-accent);}
.lbchat-src[open] .lbchat-src-hint{display:none;}
.lbchat-srcrow{display:flex;align-items:center;gap:12px;padding:6px 2px;border-bottom:1px solid color-mix(in srgb,var(--background-modifier-border) 70%,transparent);}
.lbchat-srcrow:last-child{border-bottom:0;}
.lbchat-srcrow > a{flex:1 1 auto;min-width:0;margin:0;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--link-color);text-decoration:none;}
.lbchat-srcrow > a:hover{text-decoration:underline;}
.lbchat-srcrow-acts{flex:none;display:flex;align-items:center;gap:12px;}
/* ③ 多选：每行左边一个选中圈，悬停（或已有选中）才出现，样子同目录页卡片的圈（小一号） */
.lbchat button.lbchat-src-check{flex:none;width:17px;height:17px;padding:0!important;margin:0;border-radius:50%!important;border:1.5px solid var(--text-faint)!important;background:var(--background-primary)!important;box-shadow:none!important;color:transparent;display:grid;place-items:center;cursor:pointer;opacity:0;transition:opacity .12s,background .12s;}
.lbchat button.lbchat-src-check svg{width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;}
.lbchat-srcrow:hover button.lbchat-src-check,.lbchat-srcrow:focus-within button.lbchat-src-check,.lbchat-selecting button.lbchat-src-check{opacity:1;}
.lbchat button.lbchat-src-check:hover{border-color:var(--interactive-accent)!important;}
.lbchat button.lbchat-src-check.is-on{opacity:1;background:var(--interactive-accent)!important;border-color:var(--interactive-accent)!important;color:var(--text-on-accent,#fff);}
.lbchat-srcrow.is-picked{background:color-mix(in srgb,var(--interactive-accent) 7%,transparent);}
.lbchat-src-kind{flex:none;font-size:10.5px;line-height:1.6;padding:0 6px;border-radius:999px;color:var(--interactive-accent);border:1px solid color-mix(in srgb,var(--interactive-accent) 45%,transparent);}
.lbchat-src-bulk{display:flex;gap:16px;align-items:center;font-size:12px;margin:8px 0 2px;padding:7px 12px;border-radius:10px;background:var(--background-secondary);}
.lbchat-src-bulk[hidden]{display:none;}
.lbchat-src-bulkcount{color:var(--text-muted);margin-right:auto;}
.lbchat .lbchat-src-bulk button.lbchat-act{font-size:12px;color:var(--text-normal);}
.lbchat .lbchat-src-bulk button.lbchat-src-bulkdel:hover{color:var(--text-error,#e5534b);}
/* ④ 「命中」：点了在该行下面展开 1–2 段命中原文（带字段身份：评论 c3 / 图2 / 我保存的） */
.lbchat-src-hit{margin:0 0 4px 29px;padding:6px 10px;border-left:2px solid var(--background-modifier-border);color:var(--text-muted);font-size:12px;line-height:1.7;}
.lbchat-src-hit[hidden]{display:none;}
.lbchat-src-hit > div + div{margin-top:4px;}
.lbchat .lbchat-srcrow button.lbchat-src-hitbtn.is-on{color:var(--text-normal);}
/* ⑥ 已保存：默认只一行标题，点开才展开正文 */
.lbchat-arc-item{margin:0;border-bottom:1px solid color-mix(in srgb,var(--background-modifier-border) 70%,transparent);}
.lbchat-arc-item>summary.lbchat-arc-head{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:12px;padding:11px 2px;}
.lbchat-arc-item>summary.lbchat-arc-head::-webkit-details-marker{display:none;}
.lbchat-arc-title{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;color:var(--text-normal);}
.lbchat-arc-head:hover .lbchat-arc-title{color:var(--interactive-accent);}
.lbchat-arc-when{flex:none;font-size:11px;color:var(--text-faint);}
.lbchat-arc-item[open]{padding-bottom:16px;}
.lbchat-arc-item[open] .lbchat-arc-title{white-space:normal;font-weight:600;}
/* ⑤ 隐私模式小字 + 历史面板 */
.lbchat button.lbchat-privtag{font:inherit;font-size:11.5px;height:auto;padding:2px 8px;border-radius:999px!important;border:1px solid var(--background-modifier-border)!important;background:transparent!important;box-shadow:none!important;color:var(--text-muted);cursor:pointer;}
.lbchat button.lbchat-privtag[hidden]{display:none;}
.lbchat-hist.is-private{color:var(--interactive-accent);}
.lbchat-histhead .lbchat-histtitle{font-weight:600;color:var(--text-normal);}
.lbchat-histpriv{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--text-muted);cursor:pointer;}
.lbchat-histpriv input{margin:0;accent-color:var(--interactive-accent);}
.lbchat-histbar{display:flex;align-items:center;gap:12px;padding:6px 8px;margin:0 0 4px;border-radius:8px;background:var(--background-secondary);font-size:12px;color:var(--text-muted);}
.lbchat-histbar span{margin-right:auto;}
.lbchat-histpanel button.lbchat-histbtn{font:inherit;font-size:12px;height:auto;padding:2px 6px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-normal);cursor:pointer;}
.lbchat-histpanel button.lbchat-histdel{color:var(--text-error,#e5534b);}
.lbchat-histpanel button.lbchat-histbtn:disabled{opacity:.4;cursor:default;}
.lbchat-histday{padding:10px 8px 4px;font-size:11.5px;color:var(--text-faint);letter-spacing:.02em;}
.lbchat-histpanel .lbchat-histitem{display:flex;align-items:center;gap:8px;width:100%;box-sizing:border-box;padding:5px 8px;border-radius:8px;white-space:normal;overflow:visible;cursor:default;}
.lbchat-histpanel .lbchat-histitem:hover,.lbchat-histpanel .lbchat-histitem.is-picked{background:var(--background-modifier-hover);}
.lbchat-histpanel .lbchat-histitem.is-current .lbchat-histq{font-weight:600;}
.lbchat-histpanel button.lbchat-histq{flex:1 1 auto;min-width:0;text-align:left;font:inherit;font-size:13px;height:auto;padding:2px 0;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-normal);cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lbchat-histnow{flex:none;font-size:10.5px;color:var(--interactive-accent);}
.lbchat-histtime{flex:none;font-size:11px;color:var(--text-faint);font-variant-numeric:tabular-nums;}
.lbchat-histpanel button.lbchat-src-check{flex:none;width:16px;height:16px;padding:0!important;border-radius:50%!important;border:1.5px solid var(--text-faint)!important;background:var(--background-primary)!important;box-shadow:none!important;color:transparent;display:grid;place-items:center;cursor:pointer;opacity:0;}
.lbchat-histpanel button.lbchat-src-check svg{width:10px;height:10px;fill:none;stroke:currentColor;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;}
.lbchat-histpanel .lbchat-histitem:hover button.lbchat-src-check,.lbchat-histpanel button.lbchat-src-check.is-on,.lbchat-histpanel:has(.lbchat-histbar) button.lbchat-src-check{opacity:1;}
.lbchat-histpanel button.lbchat-src-check.is-on{background:var(--interactive-accent)!important;border-color:var(--interactive-accent)!important;color:var(--text-on-accent,#fff);}
.lbchat .lbchat-srcrow button.lbchat-src-pin,.lbchat .lbchat-srcrow button.lbchat-src-del{border:1px solid var(--background-modifier-border)!important;border-radius:999px;padding:0 10px;height:22px;line-height:20px;font-size:11.5px;color:var(--text-muted);background:var(--background-primary)!important;}
.lbchat .lbchat-srcrow button.lbchat-src-del{padding:0 8px;font-size:13px;}
.lbchat .lbchat-srcrow button.lbchat-src-pin:hover{color:var(--text-normal);border-color:var(--text-muted)!important;}
.lbchat .lbchat-srcrow button.lbchat-src-pin.is-on{background:var(--interactive-accent)!important;border-color:var(--interactive-accent)!important;color:var(--text-on-accent,#fff);}
.lbchat .lbchat-srcrow button.lbchat-src-pin.is-on::before{content:'✓ ';}
.lbchat .lbchat-srcrow button.lbchat-src-del:hover{color:var(--text-error,#e5534b);border-color:var(--text-error,#e5534b)!important;}
@media(max-width:700px){.lbchat-srcrow{flex-wrap:wrap;gap:4px 12px;}.lbchat-srcrow > a{flex-basis:100%;}.lbchat-followbar{padding:0 8px;}}
/* ── 批次 D · L2 ── */
.lbchat{position:relative;}
/* F5：对话列外面包一层 bodywrap（目录左栏、浮钮都绝对定位在它里面，不进文档流、不挤对话列；不用 sticky：Dataview 行内 overflow-x:auto 会让它失效） */
.lbchat-bodywrap{position:relative;flex:1;min-height:0;display:flex;justify-content:center;width:100%;}
.lbchat-bodywrap > .lbchat-body{flex:1 1 auto;}
.lbchat-md > p:first-child{margin-top:0;}
.lbchat-md > p:last-child{margin-bottom:0;}
.lbchat .lbchat-md img{cursor:zoom-in;}
.lbchat-fail{color:var(--text-muted);}
.lbchat-srcrow.is-removed > a{text-decoration:line-through;color:var(--text-faint);}
.lbchat .lbchat-srcrow button.lbchat-src-back{font-size:11.5px;color:var(--text-faint);}
.lbchat .lbchat-srcrow button.lbchat-src-back:hover{color:var(--text-normal);}
.lbchat-src-saved{margin:0 0 4px 29px;padding:6px 10px;border-left:2px solid var(--background-modifier-border);color:var(--text-muted);font-size:12.5px;line-height:1.7;}
.lbchat-src-saved[hidden]{display:none;}
.lbchat .lbchat-src-saved button.lbchat-act{margin-top:4px;}
@keyframes lbchatflash{0%{background:color-mix(in srgb,var(--interactive-accent) 18%,transparent);}100%{background:transparent;}}
.lbchat-flash{animation:lbchatflash 1.2s ease-out;}
.lbchat .lbchat-cite.is-pending{display:inline-block;font-size:11px;line-height:1.55;vertical-align:1px;margin:0 2px;padding:0 6px;border-radius:999px;background:var(--background-modifier-hover);color:var(--text-faint);white-space:nowrap;cursor:default;}
.lbchat-imgph{display:inline-block;font-size:11px;line-height:1.6;padding:0 8px;margin:0 2px;border-radius:999px;background:var(--background-modifier-hover);color:var(--text-faint);white-space:nowrap;}
.lbchat-search::-webkit-scrollbar{display:none;width:0;height:0;}
.lbchat .lbchat-composer.is-multi{align-items:flex-end;}
.lbchat-editor::-webkit-scrollbar{display:none;width:0;height:0;}
.lbchat-edithint{font-size:11px;color:var(--text-faint);align-self:center;}
.lbchat-ro{flex:none;width:100%;max-width:850px;margin:-8px auto 12px;box-sizing:border-box;padding:0 8px;font-size:12px;color:var(--text-faint);}
.lbchat-cfghint{font-size:12px;color:var(--text-faint);margin-top:6px;}
.lbchat-cfgbar{flex:none;width:100%;max-width:850px;margin:10px auto -12px;box-sizing:border-box;padding:0 14px;font-size:12px;color:var(--text-faint);}
.lbchat-cfgbar[hidden]{display:none;}
.lbchat button.lbchat-cfgbtn{font:inherit;font-size:12px;color:var(--text-muted);background:transparent!important;border:0!important;box-shadow:none!important;padding:0 2px;height:auto;cursor:pointer;text-decoration:underline;text-underline-offset:3px;}
.lbchat-scopetag{display:block;margin:0 0 2px;font-size:11px;font-weight:400;color:var(--text-faint);}
/* A8 / F5：右下角浮钮（↓ 最新、↩ 回到刚才），跟着 850px 对话列的右缘走 */
.lbchat-floaters{position:absolute;right:max(12px,calc(50% - 425px + 12px));bottom:12px;display:flex;flex-direction:column;align-items:flex-end;gap:8px;z-index:2;pointer-events:none;}
.lbchat-floaters > *{pointer-events:auto;}
.lbchat button.lbchat-tobottom{position:relative;width:32px;height:32px;padding:0;border-radius:50%!important;display:grid;place-items:center;border:1px solid var(--background-modifier-border)!important;background:var(--background-primary)!important;color:var(--text-muted);box-shadow:0 2px 8px #0000001a!important;cursor:pointer;font-size:15px;}
.lbchat button.lbchat-tobottom:hover{color:var(--text-normal);}
.lbchat button.lbchat-tobottom.is-live::after{content:'';position:absolute;top:1px;right:1px;width:6px;height:6px;border-radius:50%;background:var(--interactive-accent);animation:lbchatpulse 1s ease-in-out infinite;}
.lbchat button.lbchat-back{height:28px;padding:0 12px;border-radius:999px!important;border:1px solid var(--background-modifier-border)!important;background:var(--background-primary)!important;color:var(--text-muted);box-shadow:0 2px 8px #0000001a!important;font-size:12px;cursor:pointer;}
.lbchat button.lbchat-back:hover{color:var(--text-normal);}
.lbchat-floaters [hidden]{display:none!important;}
/* F5 目录：宽窗是对话列左边的一栏（绝对定位，无边框无底色，自己能滚但不画滚动条）；窄窗是页头「目录」按钮 + 弹出层 */
.lbchat-toc{position:absolute;top:0;bottom:0;width:176px;left:max(8px,calc(50% - 425px - 196px));overflow-y:auto;scrollbar-width:none;font-size:12px;color:var(--text-muted);padding:2px 0 24px;box-sizing:border-box;}
.lbchat-toc::-webkit-scrollbar,.lbchat-tocpanel::-webkit-scrollbar{display:none;width:0;height:0;}
.lbchat-toc[hidden]{display:none;}
.lbchat-tochead{display:flex;align-items:center;justify-content:space-between;padding:0 8px 6px;color:var(--text-faint);font-size:11.5px;}
.lbchat button.lbchat-toc-fold{font:inherit;font-size:13px;height:auto;padding:0 4px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-faint);cursor:pointer;}
.lbchat-tocgrp{padding:4px 8px 6px;border-left:2px solid transparent;}
.lbchat-tocgrp.is-here{border-left-color:var(--interactive-accent);color:var(--text-normal);}
.lbchat-toc button,.lbchat-tocpanel button{font:inherit;font-size:12px;height:auto;border:0!important;box-shadow:none!important;background:transparent!important;color:inherit;cursor:pointer;padding:1px 0;text-align:left;}
.lbchat-toc button:hover,.lbchat-tocpanel button:hover{color:var(--interactive-accent);}
button.lbchat-toc-q{display:block;width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-normal)!important;}
.lbchat-tocgrp:not(.is-here) button.lbchat-toc-q{color:var(--text-muted)!important;}
.lbchat-toc-tag{font-size:10.5px;color:var(--interactive-accent);margin-right:4px;}
.lbchat-toc-row{display:flex;flex-wrap:wrap;align-items:center;gap:2px 8px;padding-left:12px;color:var(--text-faint);}
button.lbchat-toc-h{max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11.5px!important;}
.lbchat-toc-row .lbchat-dot{display:inline-block;margin-left:4px;vertical-align:middle;}
.lbchat button.lbchat-tocbtn{font:inherit;font-size:12px;height:auto;padding:4px 0;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);cursor:pointer;}
.lbchat button.lbchat-tocbtn[hidden]{display:none;}
.lbchat-tocpanel{position:fixed;width:300px;max-height:60vh;overflow-y:auto;scrollbar-width:none;background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.22);padding:6px 4px;z-index:9999;font-size:12px;color:var(--text-muted);}
/* ── 1015 第二批 ── */
/* 目录卡（先目录后展开）：无框，序号 + 标题（点开来源）+ 作者 + 来源类型小标；第二行命中点；右边「展开」 */
.lbchat-tocard{margin:12px 0 4px;padding:10px 0 4px;border-top:1px solid color-mix(in srgb,var(--background-modifier-border) 70%,transparent);}
.lbchat-tocard-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:0 0 6px;font-size:12.5px;color:var(--text-muted);}
.lbchat-tocard-title{font-weight:600;color:var(--text-normal);}
.lbchat-tocard-note{font-size:11.5px;color:var(--text-faint);}
.lbchat .lbchat-tocard-head button.lbchat-tocard-all{margin-left:auto;color:var(--interactive-accent);}
.lbchat-tocard-list{list-style:none;margin:0;padding:0;}
.lbchat-tocard-group{margin:10px 0 2px;font-size:11.5px;color:var(--text-faint);letter-spacing:.02em;}
.lbchat-tocard-item{display:flex;align-items:flex-start;gap:10px;padding:7px 2px;border-bottom:1px solid color-mix(in srgb,var(--background-modifier-border) 55%,transparent);}
.lbchat-tocard-item:last-child{border-bottom:0;}
.lbchat-tocard-n{flex:none;min-width:1.4em;text-align:right;font-size:12px;line-height:1.75;color:var(--text-faint);font-variant-numeric:tabular-nums;}
.lbchat-tocard-main{flex:1 1 auto;min-width:0;}
.lbchat-tocard-line{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;font-size:14px;line-height:1.6;}
.lbchat button.lbchat-tocard-name,.lbchat span.lbchat-tocard-name{font:inherit;font-size:14px;font-weight:600;color:var(--text-normal);background:transparent!important;border:0!important;box-shadow:none!important;padding:0;height:auto;text-align:left;cursor:pointer;white-space:normal;}
.lbchat span.lbchat-tocard-name{cursor:default;}
.lbchat button.lbchat-tocard-name:hover{color:var(--interactive-accent);}
.lbchat-tocard-author{font-size:12px;color:var(--text-muted);}
.lbchat-tocard-kind{font-size:10.5px;line-height:1.6;padding:0 6px;border-radius:999px;color:var(--text-muted);background:var(--background-modifier-hover);}
.lbchat-tocard-hit{font-size:12.5px;line-height:1.65;color:var(--text-muted);margin-top:1px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbchat .lbchat-tocard-item button.lbchat-tocard-expand{flex:none;align-self:center;border:1px solid var(--background-modifier-border)!important;border-radius:999px!important;padding:0 10px!important;height:22px!important;line-height:20px;font-size:11.5px!important;color:var(--text-muted);background:var(--background-primary)!important;}
.lbchat .lbchat-tocard-item button.lbchat-tocard-expand:hover:not(:disabled){color:var(--text-normal);border-color:var(--text-muted)!important;}
.lbchat .lbchat-tocard-item button.lbchat-tocard-expand.is-done{color:var(--interactive-accent);border-color:color-mix(in srgb,var(--interactive-accent) 45%,transparent)!important;}
.lbchat button.lbchat-act:disabled{opacity:.45;cursor:default;}
.lbchat-tocard-suggest{margin-top:8px;font-size:12px;color:var(--text-faint);}
/* 目录：1080–1242 时对话列往右让出左栏 */
.lbchat-bodywrap.is-tight{padding-left:188px;box-sizing:border-box;}
.lbchat-bodywrap.is-tight > .lbchat-toc{left:4px;}
.lbchat-toc-item{color:var(--text-muted);}
/* 「下一问」开关行：两个开关一行放不下就折行 */
.lbchat-followbar{flex-wrap:wrap;row-gap:2px;}
/* 已保存：Enter 存、作者小框、× 在标题行 */
.lbchat-arc-add{align-items:flex-end;}
.lbchat .lbchat-arc-input{min-height:38px;height:38px;resize:none;}
.lbchat .lbchat-arc-author{flex:0 0 7.5em;width:7.5em;min-width:0;border:0;border-bottom:1px solid var(--background-modifier-border);border-radius:0;background:transparent!important;box-shadow:none!important;font:inherit;font-size:12.5px;color:var(--text-muted);padding:6px 2px;}
.lbchat .lbchat-arc-author:focus{border-bottom-color:var(--interactive-accent);outline:none;}
.lbchat-arc-who{flex:none;font-size:11px;line-height:1.6;padding:0 7px;border-radius:999px;color:var(--interactive-accent);border:1px solid color-mix(in srgb,var(--interactive-accent) 40%,transparent);}
.lbchat-arc-head .lbchat-arc-del{flex:none;margin-left:0;opacity:0;color:var(--text-faint);}
.lbchat-arc-item:hover .lbchat-arc-head .lbchat-arc-del,.lbchat-arc-head .lbchat-arc-del:focus-visible{opacity:1;}
@media (hover:none){.lbchat-arc-head .lbchat-arc-del{opacity:1;}}
/* mermaid 视口：图大于框时可拖、可缩放；放大看 = 铺满窗口 */
.lbchat-mmd{position:relative;overflow:hidden;max-height:62vh;margin:.4em 0 .9em;border-radius:8px;background:var(--background-secondary);cursor:grab;touch-action:none;user-select:none;}
.lbchat-mmd.is-drag{cursor:grabbing;}
.lbchat-mmd-stage{position:relative;z-index:0;transform-origin:0 0;padding:10px;will-change:transform;}
.lbchat-mmd-stage .mermaid{margin:0;}
.lbchat-mmd-stage svg{max-width:100%;height:auto;}
.lbchat-mmd-bar{position:absolute;z-index:2;right:6px;top:6px;display:flex;gap:4px;opacity:0;transition:opacity .12s;}
.lbchat-mmd:hover .lbchat-mmd-bar,.lbchat-mmd.is-moved .lbchat-mmd-bar,.lbchat-mmd.is-full .lbchat-mmd-bar,.lbchat-mmd:focus-within .lbchat-mmd-bar{opacity:1;}
@media (hover:none){.lbchat-mmd-bar{opacity:1;}}
.lbchat .lbchat-mmd button.lbchat-mmd-btn{font:inherit;font-size:11.5px;height:24px;min-width:24px;padding:0 7px;border-radius:6px!important;border:1px solid var(--background-modifier-border)!important;background:var(--background-primary)!important;box-shadow:none!important;color:var(--text-muted);cursor:pointer;}
.lbchat .lbchat-mmd button.lbchat-mmd-btn:hover{color:var(--text-normal);}
.lbchat-mmd.is-full{position:fixed;inset:24px;z-index:9998;max-height:none;background:var(--background-primary);border:1px solid var(--background-modifier-border);box-shadow:0 12px 40px rgba(0,0,0,.28);}
.lbchat-mmd.is-full .lbchat-mmd-stage svg{max-width:none;}
/* 1020 输入框上方一行：左「追问 · 新对话」，右「收起来源 · 清空上下文」；两个词并排的开关（选中的加深 + 下划线） */
.lbchat-ctlrow{flex:none;width:100%;max-width:850px;margin:10px auto -16px;box-sizing:border-box;display:flex;align-items:center;gap:14px;padding:0 14px;font-size:12px;color:var(--text-faint);}
.lbchat-ctlrow .lbchat-followbar{flex:1 1 auto;min-width:0;width:auto;max-width:none;margin:0;padding:0;}
.lbchat-ctlrow .lbchat-srcbar{flex:none;width:auto;max-width:none;margin:0;padding:0;gap:12px;}
.lbchat-clearbox{flex:none;}
.lbchat-clearbox[hidden]{display:none;}
.lbchat-seg{display:inline-flex;align-items:baseline;gap:4px;}
.lbchat-seg-dot{color:var(--text-faint);}
.lbchat button.lbchat-seg-opt{font:inherit;font-size:12px;height:auto;padding:0 1px 2px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-faint);cursor:pointer;border-radius:0!important;border-bottom:1.5px solid transparent!important;}
.lbchat button.lbchat-seg-opt:hover{color:var(--text-muted);}
.lbchat button.lbchat-seg-opt.is-on{color:var(--text-normal);font-weight:600;border-bottom-color:currentColor!important;cursor:default;}
.lbchat-modebox{flex:none;display:inline-flex;align-items:center;margin-right:2px;}
.lbchat-modebox .lbchat button.lbchat-seg-opt,.lbchat-modebox button.lbchat-seg-opt{font-size:13px!important;}
@media(max-width:700px){.lbchat-ctlrow{padding:0 8px;gap:8px;flex-wrap:wrap;}}
/* ── 1020 陈列版（技能 layout: board）：一份陈列目录。细线分隔、不套框不加阴影；左封面右文字，窄屏封面缩小 ── */
.lbboard{display:flex;flex-direction:column;gap:22px;margin:2px 0 6px;}
.lbboard-head{border-bottom:1.5px solid var(--text-normal);padding-bottom:10px;}
.lbboard-title{font-family:var(--font-text);font-size:1.45em;font-weight:700;line-height:1.25;letter-spacing:.01em;}
.lbboard-lead{margin-top:6px;font-size:13px;line-height:1.65;color:var(--text-muted);}
.lbboard-cat{display:flex;align-items:baseline;gap:8px;font-size:13px;font-weight:600;letter-spacing:.04em;color:var(--text-normal);padding-bottom:6px;border-bottom:1px solid var(--background-modifier-border);}
.lbboard-n{font-size:11px;font-weight:400;color:var(--text-faint);font-variant-numeric:tabular-nums;}
.lbboard-desc{margin:6px 0 2px;font-size:12.5px;line-height:1.6;color:var(--text-muted);}
.lbboard-top{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:14px 16px;margin-top:10px;}
.lbboard-topcard{display:flex;flex-direction:column;gap:5px;min-width:0;}
.lbboard-topcard .lbboard-cover{width:100%;height:auto;aspect-ratio:3/4;}
.lbboard-topcard .lbboard-name{font-size:13.5px;}
.lbboard-topwhy{font-size:12px;line-height:1.55;color:var(--text-muted);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.lbboard-row{display:flex;gap:14px;align-items:flex-start;padding:12px 0;border-bottom:1px solid color-mix(in srgb,var(--background-modifier-border) 60%,transparent);}
.lbboard-row:last-child{border-bottom:0;}
.lbboard-cover{flex:none;width:84px;height:112px;border-radius:6px;overflow:hidden;background:var(--background-modifier-hover);display:flex;align-items:center;justify-content:center;}
.lbboard-cover img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .2s;}
.lbboard-cover.is-empty span{font-size:11px;color:var(--text-faint);padding:0 6px;text-align:center;line-height:1.4;}
.lbboard .is-link{cursor:pointer;border-radius:8px;transition:background .12s;}
.lbboard .is-link:hover{background:var(--background-modifier-hover);}
.lbboard .is-link:hover .lbboard-cover img{transform:scale(1.03);}
.lbboard .is-link:focus-visible{outline:2px solid var(--interactive-accent);outline-offset:2px;}
.lbboard-row.is-link{margin:0 -8px;padding-left:8px;padding-right:8px;}
.lbboard-topcard.is-link{padding:6px;margin:-6px;}
.lbchat-toc-board{display:flex;flex-direction:column;align-items:flex-start;gap:1px;margin:2px 0 4px 14px;}
.lbchat button.lbchat-toc-h.lbchat-toc-cat{color:var(--text-muted);margin-top:3px;}
.lbchat button.lbchat-toc-h.lbchat-toc-sub{padding-left:14px!important;color:var(--text-faint);font-size:11px!important;}
.lbboard-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:4px;}
.lbboard-line{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;}
.lbboard-name{font-weight:600;font-size:14.5px;line-height:1.4;color:var(--text-normal);}
.lbboard-url{font-family:var(--font-monospace);font-size:11.5px;color:var(--interactive-accent);word-break:break-all;}
.lbboard-text{font-size:13px;line-height:1.65;color:var(--text-normal);}
.lbboard-text.is-why{color:var(--text-normal);}
.lbboard-lab{display:inline-block;margin-right:6px;font-size:10.5px;letter-spacing:.06em;color:var(--text-faint);}
.lbboard-text.is-why .lbboard-lab{color:var(--interactive-accent);}
.lbboard-src{font-size:11.5px;color:var(--text-faint);line-height:1.6;}
.lbchat button.lbboard-srclink{font:inherit;font-size:11.5px;height:auto;padding:0;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);cursor:pointer;}
.lbchat button.lbboard-srclink:hover{color:var(--interactive-accent);}
.lbboard-rest{margin-top:4px;}
.lbboard-cover.is-ghost{height:1px;background:transparent;visibility:hidden;}
.lbboard-row.is-thin{padding-top:8px;padding-bottom:8px;align-items:center;}
.lbboard-row.is-thin .lbboard-cover:not(.is-ghost){width:56px;height:74px;}
.lbboard-row.is-thin .lbboard-cover.is-ghost{width:56px;}
.lbboard-chips{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 8px;line-height:1.6;}
.lbboard-chip{display:inline-flex;align-items:baseline;gap:6px;}
.lbboard-chip .lbboard-name{font-size:14px;}
.lbboard-chipnote{font-size:12px;color:var(--text-muted);}
.lbboard-chipsep{color:var(--text-faint);}
.lbboard-jump{cursor:pointer;border-radius:4px;}
.lbboard-jump:hover{text-decoration:underline;text-decoration-color:var(--text-faint);text-underline-offset:3px;}
.lbboard-topbody{display:flex;flex-direction:column;gap:5px;min-width:0;}
.lbboard-topcard.is-multi{grid-column:span 2;flex-direction:row;align-items:flex-start;gap:12px;}
.lbboard .lbboard-topcard.is-multi .lbboard-cover{width:calc(50% - 8px);flex:none;}
.lbboard-topcard.is-multi .lbboard-topbody{flex:1 1 auto;}
.lbboard-topitem + .lbboard-topitem{margin-top:6px;padding-top:6px;border-top:1px dashed var(--background-modifier-border);}
@media (max-width:520px){.lbboard-row .lbboard-cover{width:64px;height:86px;}.lbboard-top{grid-template-columns:repeat(2,minmax(0,1fr));}}
/* ── 1020 输入框照 Codex：灰色窄条（追问 · 新对话 / 收起来源 · 清空上下文）连在白色输入卡顶上；输入卡里上面输入、下面一排工具 ── */
.lbchat .lbchat-composer{flex-direction:column;align-items:stretch;gap:2px;padding:12px 12px 10px 16px;border-radius:22px;position:relative;z-index:1;box-shadow:0 4px 18px #00000012;margin-top:0;}
.lbchat .lbchat-search{flex:none;width:100%;height:44px;min-height:44px;padding:6px 2px!important;font-size:14.5px;}
.lbchat-cbar{display:flex;align-items:center;justify-content:space-between;gap:10px;}
.lbchat-cbar-left,.lbchat-cbar-right{display:flex;align-items:center;gap:8px;min-width:0;}
.lbchat .lbchat-cbar .lbchat-modebox{margin:0;}
.lbchat .lbchat-cbar .lbchat-model{max-width:150px;font-size:13px;color:var(--text-muted);}
.lbchat .lbchat-cbar button.lbchat-send{width:34px;height:34px;}
.lbchat-ctlrow{width:calc(100% - 28px);max-width:822px;margin:14px auto -14px;padding:8px 18px 22px;border-radius:16px 16px 0 0;background:var(--background-secondary);border:1px solid var(--background-modifier-border);border-bottom:0;font-size:12.5px;}
.lbchat-ctlrow:not(:has(> :not([hidden]))){display:none;}
.lbchat-ctlrow + .lbchat-composer{margin-top:0;}
.lbchat-tocfab{position:absolute;left:0;top:14px;z-index:6;writing-mode:vertical-rl;letter-spacing:.2em;padding:12px 5px!important;height:auto!important;font-size:12px!important;border-radius:0 10px 10px 0!important;border:1px solid var(--background-modifier-border)!important;border-left:0!important;background:var(--background-secondary)!important;color:var(--text-muted)!important;box-shadow:none!important;cursor:pointer;}
.lbchat-tocfab:hover{color:var(--text-normal)!important;}
.lbchat-tocfab[hidden]{display:none!important;}
.lbchat-tocpanel.is-side{max-height:70vh;}
`);

const host = LB.mountHost('lbchat-host');
const wrap = host.createEl('div', { cls: 'lbchat' });
// Size against the actual Obsidian pane, not the entire screen (tabs/toolbars
// and pane offsets otherwise push the composer below the visible area).
const fitPane = () => { const viewport = root.closest('.workspace-leaf-content') || (pane && ['auto', 'scroll', 'hidden'].includes(getComputedStyle(pane).overflowY) ? pane : null); const bottom = Math.min(window.innerHeight, viewport?.getBoundingClientRect().bottom || window.innerHeight); wrap.style.height = Math.max(240, bottom - wrap.getBoundingClientRect().top - 16) + 'px'; };
const resizeObserver = new ResizeObserver(fitPane); resizeObserver.observe(pane || document.documentElement);
LB.onUnload(() => resizeObserver.disconnect());
requestAnimationFrame(fitPane);
const head = wrap.createEl('div', { cls: 'lbchat-head' });
const titleBlock = head.createEl('div', { cls: 'lbchat-titleblock' });
const titleRow = titleBlock.createEl('div', { cls: 'lbchat-titlerow' });
titleRow.createEl('span', { cls: 'lbchat-title', text: 'Collections' });
const tools = head.createEl('div', { cls: 'lbchat-tools' });
let clearBtn = null;
const paintClear = () => { if (clearBtn) clearBtn.disabled = isBusy() || !session.turns.length; };
const sub = titleBlock.createEl('div', { cls: 'lbchat-sub' });
// F4-chat：和目录页同一个「真实数据更新时间」（LB.dataUpdatedAt）
function paintSub() {
  const at = LB.dataUpdatedAt(data);
  const d = at ? new Date(at) : null;
  if (!d || isNaN(d)) { sub.setText(`${items.length} 篇`); return; }
  sub.setText(`${items.length} 篇 · 更新 ${d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}`);
}
paintSub();
const pageNav = head.createEl('nav', { cls: 'lb-page-nav' });
const browse = pageNav.createEl('button', { text: '浏览收藏' });
browse.onclick = () => { const p = provider(); if (p?.openLibraryPage) p.openLibraryPage('catalog'); else LB.openPage('catalog'); };
const ask = pageNav.createEl('button', { text: '问收藏', cls: 'is-current' }); ask.setAttribute('aria-current', 'page');
if (!readOnly) { const manage = tools.createEl('button', { cls: 'lb-manage', text: '…' }); manage.onclick = e => provider()?.openAISettingsMenu(e); }
// ⑤ 历史入口（时钟）：点开 = 全部历史对话，按天分组，点一行恢复；可多选删除；顶上「隐私模式」开关
const histBtn = tools.createEl('button', { cls: 'lbchat-hist', attr: { 'aria-label': '历史对话', title: '历史对话（按天，点一段恢复）' } });
histBtn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l3.5 2"/></svg>';
histBtn.onclick = e => { e?.stopPropagation?.(); toggleHistory(histBtn); };
// A11：页顶一行只读说明
if (readOnly) wrap.createEl('div', { cls: 'lbchat-ro', text: LB.mobile ? '手机上可以看历史问答；提问、导出、来源窗格要在电脑上用' : 'Link Brain Actions 插件没启用，这页只能看' });
const composer = wrap.createEl('form', { cls: 'lbchat-composer' });
// 0926 Owner：输入框照 Codex 的样子——左「+」、灰字提示（设置里可改）、右边模型下拉 + 麦克风 + 圆形发送。
const cfg = () => provider()?.settings || {};
const queueEl = wrap.createEl('div', { cls: 'lbchat-queue' });
const search = composer.createEl('textarea', { cls: 'lbchat-search' });
search.rows = 1; search.value = typeof pageState.draft === 'string' ? pageState.draft : (session.draft || '');
// 1020 她：「回答 · 报告」放模型下拉旁边；选报告 = 这一问起出陈列版（问题前加 /报告 发给后端，见 ask.REPORT_MARK），切回来为止
const modeBox = composer.createEl('span', { cls: 'lbchat-modebox' });
function paintAnswerMode() {
  modeBox.empty();
  if (readOnly) return;
  segSwitch(modeBox, 'lbchat-answermode', [['answer', '回答', '照常回答'], ['report', '报告', '出陈列版报告：分类、每条配出处帖封面、网址和可以借鉴的点']],
    prefs.report ? 'report' : 'answer', async key => { prefs.report = key === 'report'; paintAnswerMode(); try { await savePrefs(); } catch (e) { notice(NOT_SAVED + errText(e)); } });
}
paintAnswerMode();
const modelPick = composer.createEl('select', { cls: 'lbchat-model', attr: { title: '回答用的模型（设置 → AI → 问答模型里增删）' } });
// A6 / X10：问答 AI 配没配好——优先插件 modelState(name).usable（设置线），老插件退回 askModelStatus(name).ready；都没有 = 不知道（不提示，fail-open）
function aiReady(name) {
  const p = provider();
  try {
    if (typeof p?.modelState === 'function') { const st = p.modelState(name || undefined); if (st && typeof st.usable === 'boolean') return st.usable; }
    if (typeof p?.askModelStatus === 'function') { const st = p.askModelStatus(name || undefined); if (st && typeof st.ready === 'boolean') return st.ready; }
  } catch {}
  return null;
}
// A17：保留当前选择（原来选中的还在列表里就不变）；没配好的模型标「（未配置）」
const fillModels = () => {
  const keep = modelPick.value;
  modelPick.empty(); const list = (cfg().models || []).filter(m => m && m.name && !m.hidden);   // 1015：设置里没勾的模型不进下拉
  if (!list.length || readOnly) { modelPick.hidden = true; return; } modelPick.hidden = false;
  for (const m of list) modelPick.createEl('option', { text: m.name + (aiReady(m.name) === false ? '（未配置）' : '') }).value = m.name;
  modelPick.value = list.some(m => m.name === keep) ? keep : list.some(m => m.name === cfg().activeModel) ? cfg().activeModel : list[0].name;
};
fillModels();
modelPick.onchange = async () => { const p = provider(); paintCfgHint(); if (!p) return; p.settings.activeModel = modelPick.value; await p.saveSettings?.(); };
// 语音：点一下开始录，再点一下结束；识别结果直接填进输入框（不加 /）。全局按住 CapsLock 也行。
const mic = composer.createEl('button', { cls: 'lbchat-mic', attr: { title: '语音提问（再点一次结束）' } }); mic.type = 'button';
mic.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>';
mic.onclick = () => provider()?.toggleVoice?.({ target: search, button: mic });
// 第 3 批：正在作答时多一个「停止」（■）。只停问收藏页的问答（tag 'chat'），设置页「试问一句」不受影响
const stop = composer.createEl('button', { cls: 'lbchat-stop', attr: { title: '停止生成', 'aria-label': '停止生成' } }); stop.type = 'button'; stop.hidden = true;
stop.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"/></svg>';
const stopAnswer = () => { const p = provider(); if (!p?.stopArchiveAnswer) return false; stop.disabled = true; showPhase('正在停止'); if (!p.stopArchiveAnswer('chat')) { stop.disabled = false; return false; } return true; };
stop.onclick = () => stopAnswer();
function paintSend() { stop.hidden = !isBusy(); stop.disabled = false; paintClear(); }
const send = composer.createEl('button', { cls: 'lbchat-send', attr: { title: '发送（回答中会排队）' } }); send.type = 'submit';
// 1020 她：照 Codex / CC 的输入框排——输入区独占一行，工具排在下面一行
const cbar = composer.createDiv({ cls: 'lbchat-cbar' });
cbar.createDiv({ cls: 'lbchat-cbar-left' }).append(modeBox);
cbar.createDiv({ cls: 'lbchat-cbar-right' }).append(modelPick, mic, stop, send);
send.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
if (readOnly) composer.hidden = true;
// 回答进行中照常能打字：再发就进队列（像 Codex 追加提问），可点 × 取消，上一条答完自动接着问。
// A2：队列放在插件对象上（chatQueue），换页再回来还在；所有问收藏页订阅 link-brain:chat-queue 一起重画
const chatQueue = () => { const p = provider(); if (!p) return []; if (!Array.isArray(p.chatQueue)) p.chatQueue = []; return p.chatQueue; };
const queueChanged = () => { drawQueue(); try { app.workspace.trigger?.('link-brain:chat-queue', pageId); } catch {} };
function enqueue(q, opts = {}) { chatQueue().push({ q, opts, at: Date.now() }); queueChanged(); }
function drawQueue() {
  const list = chatQueue();
  queueEl.empty(); queueEl.hidden = !list.length;
  list.forEach((item, i) => {
    const row = queueEl.createEl('div', { cls: 'lbchat-queued' });
    row.createEl('span', { cls: 'lbchat-queued-tag', text: '排队' }); row.createEl('span', { cls: 'lbchat-queued-text', text: item.q });
    const now = row.createEl('button', { cls: 'lbchat-queued-now', text: '↳ 立即发送', attr: { title: '停掉正在生成的回答，马上问这条' } }); now.type = 'button'; now.onclick = () => sendNow(i);
    const x = row.createEl('button', { cls: 'lbchat-queued-x', text: '×', attr: { title: '取消发送' } }); x.type = 'button'; x.onclick = () => { chatQueue().splice(i, 1); queueChanged(); };
  });
}
// 排队那条「立即发送」（参照 Codex 的「引导」）：挪到队首，停掉当前回答；停下后答完那一页的 finally 会从队首接着问它（换页回来也一样）。
function sendNow(i) {
  const list = chatQueue(); const [item] = list.splice(i, 1); if (item === undefined) return;
  list.unshift(item); queueChanged();
  if (!isBusy()) { drainQueue(); return; }
  stopAnswer();
}
drawQueue();
composer.onsubmit = e => {
  e?.preventDefault?.(); if (readOnly) return;
  const v = search.value.trim(); if (!v) return;
  search.value = ''; saveDraft(''); autosize();
  if (isBusy()) { enqueue(v, scopeOpts()); if (scope) clearScope(); return; }
  submit(v);
};

// 第二行：对话 / 已保存 切换
const tabChat = tools.createEl('button', { cls: 'lbchat-tab', text: '对话' });
const tabArch = tools.createEl('button', { cls: 'lbchat-tab', text: '已保存' });
// 隐私模式开着时，时钟左边一枚小字「隐私模式」（点它 = 打开历史面板，开关在面板顶上）
const privTag = tools.createEl('button', { cls: 'lbchat-privtag', text: '隐私模式', attr: { title: '隐私模式：这段对话不进历史（点开历史面板可关掉）' } });
privTag.type = 'button';
tools.insertBefore?.(privTag, histBtn);
privTag.onclick = e => { e?.stopPropagation?.(); toggleHistory(histBtn); };
// F5：窄窗 / 左栏收起时，时钟左边的「目录 · N 问」
const tocBtn = tools.createEl('button', { cls: 'lbchat-tocbtn', attr: { title: '问题目录（跳到某一问 / 回答 / 来源）', 'aria-label': '问题目录' } }); tocBtn.type = 'button'; tocBtn.hidden = true;
tools.insertBefore?.(tocBtn, histBtn);
tocBtn.onclick = e => { e?.stopPropagation?.(); toggleTocPanel(); };
const paintPrivacy = () => { privTag.hidden = !session.private; histBtn.classList.toggle('is-private', !!session.private); };
paintPrivacy();
// 开 = 这段对话从历史里拿掉、之后也不进；关 = 现在这段（有轮次的话）存进历史。写盘失败原样放回并提示
async function setPrivate(on) {
  if (isBusy()) { notice(BUSY_TEXT, 3000); return false; }
  if (readOnly || !!on === session.private) return false;
  const prevHist = hist;
  session.private = !!on;
  try {
    await enqueueWrite(async () => {
      if (on) { if (hist.conversations.some(c => c.id === session.id)) await dropFromHistory([session.id]); await writeJson(SESSION_PATH, sessionSnapshot()); }
      else await saveSession();
    });
    announce();
  } catch (e) { session.private = !on; hist = prevHist; notice(NOT_SAVED + errText(e)); paintPrivacy(); return false; }
  paintPrivacy();
  notice(on ? '隐私模式已开：这段对话不进历史' : '隐私模式已关：这段对话会存进历史', 2500);
  return true;
}

// F5 / A8：对话区外包一层 bodywrap；目录左栏和右下浮钮绝对定位在它里面
const bodyWrap = wrap.createEl('div', { cls: 'lbchat-bodywrap' });
// 1020 她：「toc 没看到」——窄窗时目录只剩页头右上角一个小「目录」。对话区左边贴一个竖排浮签，点了弹出目录浮动板
const tocFab = bodyWrap.createEl('button', { cls: 'lbchat-tocfab', text: '目录', attr: { title: '目录：问题 / 分类 / 条目，点了跳过去', 'aria-label': '目录' } });
tocFab.type = 'button'; tocFab.hidden = true;
tocFab.onclick = e => { e?.stopPropagation?.(); toggleTocPanel(tocFab); };
const bodyEl = bodyWrap.createEl('div', { cls: 'lbchat-body' });
const tocEl = bodyWrap.createEl('nav', { cls: 'lbchat-toc', attr: { 'aria-label': '问题目录' } }); tocEl.hidden = true;
const floaters = bodyWrap.createEl('div', { cls: 'lbchat-floaters' });
const backBtn = floaters.createEl('button', { cls: 'lbchat-back', text: '↩ 回到刚才', attr: { title: '回到跳转前看的位置' } }); backBtn.type = 'button'; backBtn.hidden = true;
const toBottom = floaters.createEl('button', { cls: 'lbchat-tobottom', text: '↓', attr: { 'aria-label': '回到最新', title: '回到最新' } }); toBottom.type = 'button'; toBottom.hidden = true;
// 跟到底（验收第 3 批体验观察）：停在底部时新内容（新一问、阶段字、逐行出字）自动带到眼前；
// 自己往上翻了就不抢，翻回底部又接着跟
let stick = true, drawing = false, unseen = false, back = null;
const nearBottom = () => bodyEl.scrollHeight - bodyEl.scrollTop - bodyEl.clientHeight < 48;
const follow = () => { if (stick) bodyEl.scrollTop = bodyEl.scrollHeight; };
// 1003 修「点到来源，问收藏自动回首行」：DOM 被挪动后归零就滚回 lastTop（在底部跟随的回到底部）。
let lastTop = Number.isFinite(pageState.scrollTop) ? pageState.scrollTop : 0, userAt = 0, dragging = false;
const touched = e => {
  if (e && e.type === 'pointerdown') { if (e.target !== bodyEl) return; dragging = true; }   // 只有点在对话区滚动条上的 pointerdown 算滚动
  userAt = Date.now();
};
const userRecently = () => dragging || Date.now() - userAt < 400;
for (const t of ['wheel', 'touchstart', 'pointerdown', 'keydown']) bodyEl.addEventListener?.(t, touched, { passive: true });
LB.listen('scroll-keys', document, 'keydown', touched);   // 焦点不在对话区时按 PageUp / Home 也算
LB.listen('scroll-drag-end', document, 'pointerup', () => { dragging = false; });
const reset = () => bodyEl.scrollTop < 2 && lastTop > 2 && !userRecently();
function keepPlace() {
  if (lane !== 'chat' || drawing || !bodyEl.isConnected) return;
  if (stick) { follow(); return; }
  if (Math.abs(bodyEl.scrollTop - lastTop) > 2) bodyEl.scrollTop = lastTop;
}
function settle() { keepPlace(); try { requestAnimationFrame(keepPlace); } catch {} }
try { const ro = new ResizeObserver(() => { if (reset() || stick) keepPlace(); }); ro.observe(bodyEl); LB.onUnload(() => ro.disconnect()); } catch {}
// A8：往上翻时浮一个「↓ 最新」；不在底部时有新内容（出字 / 新回答）带小点
function paintFloaters() {
  const show = lane === 'chat' && !stick && session.turns.length > 0;
  toBottom.hidden = !show;
  toBottom.classList.toggle('is-live', show && unseen);
  backBtn.hidden = !(lane === 'chat' && back);
}
const markUnseen = () => { if (!stick) { unseen = true; paintFloaters(); } };
toBottom.onclick = () => { stick = true; userAt = 0; unseen = false; back = null; follow(); lastTop = bodyEl.scrollTop; LB.state.patch({ scrollTop: lastTop }); paintFloaters(); };
backBtn.onclick = () => {
  if (!back) return;
  const b = back; back = null;
  stick = b.stick; userAt = Date.now();
  if (stick) follow(); else bodyEl.scrollTop = b.top;
  lastTop = bodyEl.scrollTop; LB.state.patch({ scrollTop: lastTop }); paintFloaters();
};
// 右侧来源窗格开着时才出现的一行：明确的「退出对照」「收起来源」
const sourceBar = wrap.createEl('div', { cls: 'lbchat-srcbar' });
sourceBar.hidden = true;
function paintSourceBar() {
  const st = provider()?.archiveSourceState?.(root) || { reader: false, compare: false };
  sourceBar.empty(); sourceBar.hidden = !st.reader;
  bodyEl.classList.toggle('lbchat-has-reader', !!st.reader);
  if (!st.reader) return;
  if (st.compare) { const off = sourceBar.createEl('button', { cls: 'lbchat-act', text: '退出对照' }); off.type = 'button'; off.onclick = () => { provider().closeArchiveCompare(root); paintSourceBar(); }; }
  const close = sourceBar.createEl('button', { cls: 'lbchat-act', text: '收起来源' }); close.type = 'button'; close.onclick = () => { provider().closeArchiveSources(root); paintSourceBar(); };
}
// A6：有会话时的「问答还没配 AI」一行（在 followBar 上面，不挤「清空」）
const cfgBar = wrap.createEl('div', { cls: 'lbchat-cfgbar' }); cfgBar.hidden = true;
// ② 追问绑定当前来源：输入框上面一行小字「在当前 N 条来源里追问 · 改为重新搜」，点了才重新检索；状态跟会话一起存
const ctlRow = wrap.createEl('div', { cls: 'lbchat-ctlrow' });
const followBar = ctlRow.createEl('div', { cls: 'lbchat-followbar' });
followBar.hidden = true;
ctlRow.append(sourceBar);
const clearBox = ctlRow.createEl('div', { cls: 'lbchat-clearbox' }); clearBox.hidden = true;
wrap.append(queueEl); wrap.append(cfgBar); wrap.append(ctlRow); wrap.append(composer);

// ── 输入框：回车发送；组字中不发；A7 随内容长高；A16 ↑ 取回上一问；A13 第一次打字预热问答进程 ──
let composing = false, warmedAt = 0;
search.addEventListener('compositionstart', () => { composing = true; });
search.addEventListener('compositionend', () => { composing = false; });
function autosize() {
  try {
    search.style.height = 'auto';
    const h = Math.min(Number(search.scrollHeight) || 0, 160);
    search.style.height = Math.max(40, h) + 'px';
    composer.classList.toggle('is-multi', h > 44);
  } catch {}
}
search.oninput = () => {
  saveDraft(search.value); autosize();
  if (!readOnly && Date.now() - warmedAt > 60000) { warmedAt = Date.now(); try { provider()?.warmAnswerWorker?.(); } catch {} }
};
search.onkeydown = e => {
  if (e.isComposing || composing) return;
  if (e.key === 'ArrowUp' && !search.value && !(search.selectionStart > 0)) {
    const lastQ = [...session.turns].reverse().find(t => t.role === 'user');
    if (lastQ) { e.preventDefault?.(); search.value = lastQ.content; autosize(); saveDraft(search.value); try { search.setSelectionRange(search.value.length, search.value.length); } catch {} }
    return;
  }
  if (e.key !== 'Enter' || e.shiftKey) return;
  e.preventDefault?.(); composer.requestSubmit();
};
LB.trackFocus(search, 'search');
autosize();

// ── 渲染 ──
// markdown 一律走 renderScoped：插件 renderMarkdownScoped（返回 dispose）> 老插件 renderMarkdownInto > 没插件时 Dataview 的 dv.el（A11）。
// 回答里的 ![[_archive/…]] 先补挂载前缀（A14）：仓被挂进别的库的子目录时链接也解析到对的文件；仓根为空时不变
const fixEmbeds = md => String(md ?? '').replace(/!\[\[_archive\//g, '![[' + lbPath('_archive/'));
async function renderScoped(md, el) {
  md = fixEmbeds(md);
  const p = provider();
  try {
    if (typeof p?.renderMarkdownScoped === 'function') { const h = await p.renderMarkdownScoped(md, el, ''); return () => { try { h?.dispose?.(); } catch {} }; }
    if (typeof p?.renderMarkdownInto === 'function') { await p.renderMarkdownInto(md, el); return () => {}; }
    if (typeof dv.el === 'function') { const node = dv.el('div', md, { cls: 'lbchat-dvmd' }); el.append(node); return () => {}; }   // Dataview 异步渲染，节点整个挪过来，图片晚到也在里面
  } catch {}
  el.setText(md);
  return () => {};
}
// 每轮 DOM 缓存（A1）：key = 轮次 id → {el, sig, dispose}。sig 只取影响正文 / 气泡的字段；来源、按钮在 paintExtras 里原地重建
const views = new Map();
const sigOf = t => JSON.stringify(t.role === 'user' ? ['u', t.content, t.mode, t.sources, t.scopeTitle, !!t.report]
  : t.role === 'assistant' ? ['a', t.content, !!t.failed, !!t.stopped, t.error?.kind || '', t.error?.code || '', t.mode || '', t.answerMode || '', (t.toc || []).length, t.layout || '']
    : [t.role, (t.results || []).length]);
function disposeView(v) { try { v?.dispose?.(); } catch {} }
// 强制全量重建（恢复历史 / 清空 / 重读别页写的会话）：兜住 sig 漏掉的字段
function resetViews() { for (const v of views.values()) { disposeView(v); v.el.remove(); } views.clear(); }
let archiveDisposers = [];
const disposeArchive = () => { for (const d of archiveDisposers.splice(0)) { try { d(); } catch {} } };
let liveView = null;   // {key, el, md, tail, dispose, head}
const disposeLive = () => { if (!liveView) return; try { liveView.dispose?.(); } catch {} liveView = null; };
function disposeAll() { for (const v of views.values()) disposeView(v); views.clear(); disposeArchive(); disposeLive(); }
LB.onUnload(() => disposeAll());
// 页内状态（不写盘）：展开过的来源 / 命中 / 我保存的（openState）、多选（picks）、本页内划掉的来源（struck）
const openState = new Set();
const picks = new Map();
const struck = new Set();

async function buildTurn(t) {
  const key = t.id;
  if (t.role === 'user') {
    const el = createDiv({ cls: 'lbchat-turn lbchat-user' }); el.dataset.key = key;
    if (t.mode === 'scope') el.createEl('span', { cls: 'lbchat-scopetag', text: `只问这一篇：《${t.scopeTitle || ''}》` });
    if (t.mode === 'search') el.createEl('span', { cls: 'lbchat-qmark', text: '搜' });
    if (t.report) el.createEl('span', { cls: 'lbchat-qmark', text: '报告' });
    if (t.mode === 'reask') el.createEl('span', { cls: 'lbchat-qmark', text: `按留下的 ${t.sources || ''} 条来源重答` });
    if (t.mode === 'follow') el.createEl('span', { cls: 'lbchat-qmark is-follow', text: `在当前 ${t.sources || ''} 条来源里追问` });
    if (t.mode === 'expand') el.createEl('span', { cls: 'lbchat-qmark is-follow', text: `展开 · ${t.sources || ''} 条来源` });
    el.appendText(t.content);
    return { el, sig: sigOf(t), dispose: () => {} };
  }
  if (t.role === 'search') {
    const el = createDiv({ cls: 'lbchat-turn' }); el.dataset.key = key;
    if (!(t.results || []).length) el.createEl('div', { cls: 'lbchat-empty', text: '没找到，试试更短的关键词。' });
    else {
      const hits = el.createEl('div', { cls: 'lbchat-hits' });
      for (const r of t.results) {
        const h = hits.createEl('div', { cls: 'lbchat-hit' });
        h.createEl('div', { cls: 'lbchat-hit-title', text: r.title });
        h.createEl('div', { cls: 'lbchat-hit-meta', text: r.author });
        if (r.excerpt) h.createEl('div', { cls: 'lbchat-hit-ex', text: r.excerpt });
        h.onclick = () => openNote(r.note);
      }
    }
    return { el, sig: sigOf(t), dispose: () => {} };
  }
  const el = createDiv({ cls: 'lbchat-turn lbchat-answer' }); el.dataset.key = key;
  const md = el.createEl('div', { cls: 'lbchat-md' });
  let dispose = () => {};
  if (t.failed && t.error) md.createEl('div', { cls: 'lbchat-fail', text: t.content });   // A5：失败轮正文就一句人话
  else {
    const board = t.layout === 'board' ? parseBoard(t.content) : null;
    if (boardCount(board) >= 2) { md.addClass('is-board'); dispose = await renderBoard(md, t, board); }
    else { dispose = await renderScoped(t.content, md); bindSources(md, t.sources || []); enhanceMermaid(md); }
  }
  el._lbToc = el.createEl('div', { cls: 'lbchat-tocard-box' });
  el._lbSrc = el.createEl('div', { cls: 'lbchat-srcbox' });
  el._lbActs = el.createEl('div', { cls: 'lbchat-actions' });
  paintExtras(el, t);
  return { el, sig: sigOf(t), dispose };
}

// ── 1015 mermaid 图：自己实现缩放 / 拖动（不装第三方插件）。Obsidian 把 ```mermaid 画成 div.mermaid > svg（异步），
// 这里给它套一层视口：Ctrl+滚轮 / 「＋ −」缩放，按住拖动平移，双击或「复位」回原样，「放大看」铺满窗口（Esc / 再点退出）。幂等（data-lb-mmd）。
function enhanceMermaid(scope) {
  if (!scope?.querySelectorAll) return 0;
  let n = 0;
  for (const box of scope.querySelectorAll('.mermaid')) {
    if (box.dataset.lbMmd || box.closest('.lbchat-live') || box.closest('.lbchat-editor')) continue;
    const svg = box.querySelector('svg'); if (!svg) continue;
    box.dataset.lbMmd = '1'; n++;
    const vp = createDiv({ cls: 'lbchat-mmd' });
    box.parentNode.insertBefore(vp, box);
    const stage = vp.createEl('div', { cls: 'lbchat-mmd-stage' });
    stage.append(box);
    const bar = vp.createEl('div', { cls: 'lbchat-mmd-bar' });
    let k = 1, x = 0, y = 0;
    const apply = () => { stage.style.transform = `translate(${x}px, ${y}px) scale(${k})`; vp.classList.toggle('is-moved', k !== 1 || x !== 0 || y !== 0); };
    const zoom = (f, cx, cy) => {
      const nk = Math.min(6, Math.max(0.3, k * f));
      if (cx != null) { x = cx - (cx - x) * (nk / k); y = cy - (cy - y) * (nk / k); }
      k = nk; apply();
    };
    const reset = () => { k = 1; x = 0; y = 0; apply(); };
    const btn = (text, title, fn, cls = '') => { const b = bar.createEl('button', { cls: 'lbchat-mmd-btn' + (cls ? ' ' + cls : ''), text, attr: { title, 'aria-label': title } }); b.type = 'button'; b.onclick = e => { e?.stopPropagation?.(); fn(); }; return b; };
    btn('＋', '放大', () => zoom(1.25)); btn('－', '缩小', () => zoom(0.8)); btn('复位', '回到原样（双击图也行）', reset);
    const full = btn('放大看', '铺满窗口看（Esc 退出）', () => toggleFull(), 'lbchat-mmd-full');
    const toggleFull = (force) => { const on = force ?? !vp.classList.contains('is-full'); vp.classList.toggle('is-full', on); full.setText(on ? '退出' : '放大看'); reset(); };
    vp._lbExitFull = () => { if (!vp.classList.contains('is-full')) return false; toggleFull(false); return true; };
    vp.addEventListener?.('wheel', e => {
      if (!e.ctrlKey && !vp.classList.contains('is-full')) return;   // 平时滚轮照常滚对话；Ctrl+滚轮（触控板捏合）才缩放
      e.preventDefault?.(); e.stopPropagation?.();
      const r = vp.getBoundingClientRect();
      zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    let drag = null;
    vp.addEventListener?.('pointerdown', e => { if (e.button !== 0 || e.target.closest?.('.lbchat-mmd-bar')) return; drag = { sx: e.clientX, sy: e.clientY, x, y }; vp.classList.add('is-drag'); try { vp.setPointerCapture?.(e.pointerId); } catch {} });
    vp.addEventListener?.('pointermove', e => { if (!drag) return; x = drag.x + e.clientX - drag.sx; y = drag.y + e.clientY - drag.sy; apply(); });
    const end = () => { drag = null; vp.classList.remove('is-drag'); };
    vp.addEventListener?.('pointerup', end); vp.addEventListener?.('pointercancel', end);
    vp.addEventListener?.('dblclick', e => { if (e.target.closest?.('.lbchat-mmd-bar')) return; reset(); });
  }
  return n;
}
// ── 会话渲染（A1）：串行锁 + 只重画变了的轮 ──
let drawP = null, drawAgain = false, drawOpts = {};
function drawChat(opts = {}) {
  drawOpts = { ...drawOpts, ...opts };
  if (drawP) { drawAgain = true; return drawP; }
  drawP = (async () => { do { drawAgain = false; const o = drawOpts; drawOpts = {}; await drawChatOnce(o); } while (drawAgain); })().finally(() => { drawP = null; });
  return drawP;
}
async function drawChatOnce({ restore } = {}) {
  if (!wrap.isConnected && !root.isConnected) return;   // A2：已脱离页面的旧闭包不画
  if (lane !== 'chat') return;
  const scroll = restore === 'bottom' ? null : Number.isFinite(restore) ? restore : (reset() ? lastTop : bodyEl.scrollTop), wasStick = restore === 'bottom' ? true : stick;
  drawing = true;
  try {
    // 从「已保存」栏切回来：那一栏的节点摘掉（对话各轮的缓存节点留着，下面按顺序挂回去，不重渲）
    for (const n of [...bodyEl.children]) if (!n.classList.contains('lbchat-turn') || n.classList.contains('lbchat-live') && !liveView) n.remove();
    disposeArchive();
    const want = new Set(session.turns.map(t => t.id));
    for (const [k, v] of [...views]) if (!want.has(k)) { disposeView(v); v.el.remove(); views.delete(k); }
    let cursor = null;
    for (const t of session.turns) {
      let v = views.get(t.id);
      const sig = sigOf(t);
      if (!v || v.sig !== sig) {
        const nv = await buildTurn(t);
        if (v) { v.el.replaceWith(nv.el); disposeView(v); }
        else if (liveView && liveView.key === t.id && liveView.el.parentNode === bodyEl) { liveView.el.replaceWith(nv.el); disposeLive(); }   // A4：正式回答原地换掉流式那一块，不先删（不闪空白）
        views.set(t.id, nv); v = nv;
      } else if (t.role === 'assistant') paintExtras(v.el, t);
      const expected = cursor ? cursor.nextSibling : bodyEl.firstChild;
      if (expected !== v.el) bodyEl.insertBefore(v.el, expected);
      cursor = v.el;
    }
    // 末尾：空状态 / 流式那一块 / 阶段字
    const f = inflight();
    if (liveView && (!f || f.id !== liveView.key)) { liveView.el.remove(); disposeLive(); }
    if (!session.turns.length && !isBusy()) {
      const empty = bodyEl.createEl('div', { cls: 'lbchat-empty', text: '答案来自你的收藏，参考材料会附在回答下方。' });
      empty._lbEmpty = true;
      paintCfgHint();
    }
    if (isBusy() && f) {
      if (f.text) { ensureLive(f); scheduleLive(true); }
      else { const th = bodyEl.createEl('div', { cls: 'lbchat-think' }); th.createEl('span', { cls: 'lbchat-dot' }); th.createEl('span', { cls: 'lbchat-phase', text: phaseText() }); }
    } else if (isBusy()) { const th = bodyEl.createEl('div', { cls: 'lbchat-think' }); th.createEl('span', { cls: 'lbchat-dot' }); th.createEl('span', { cls: 'lbchat-phase', text: phaseText() }); }
  } finally { drawing = false; }
  stick = wasStick;
  if (stick) bodyEl.scrollTop = bodyEl.scrollHeight; else if (scroll != null) bodyEl.scrollTop = scroll;
  paintFollow(); paintClear(); paintCfgHint(); paintFloaters(); paintToc();
}
// 来源块 / 操作行原地重建（A1）：不碰 markdown；展开状态、多选、本页划掉的都从页内状态还原；键盘焦点跟到新按钮上
function paintExtras(el, t) {
  if (!el._lbSrc) return;
  const active = document.activeElement;
  const focusKey = active && (el._lbSrc.contains(active) || el._lbActs.contains(active)) ? active.dataset?.k : null;
  if (el._lbToc) { const tb = createDiv({ cls: 'lbchat-tocard-box' }); drawTocCard(tb, el, t); el._lbToc.replaceWith(tb); el._lbToc = tb; }
  const box = createDiv({ cls: 'lbchat-srcbox' });
  drawSources(box, el, t);
  const acts = createDiv({ cls: 'lbchat-actions' });
  drawActions(acts, el, t);
  el._lbSrc.replaceWith(box); el._lbSrc = box;
  el._lbActs.replaceWith(acts); el._lbActs = acts;
  if (focusKey) { const again = el.querySelector(`[data-k="${focusKey}"]`); try { again?.focus?.({ preventScroll: true }); } catch {} }
}
// pinned / excluded 是会话级的：所有回答轮的来源块都要重建（不碰 markdown）。点的那一轮同步重建（点下那一帧就是新状态），
// 其余轮下一帧一起补（十几轮时同步全做会吃掉一帧的预算）
let extrasQueued = false;
function paintAllExtras(nowId = null) {
  const paintOne = t => { const v = views.get(t.id); if (v) paintExtras(v.el, t); };
  const rest = () => { extrasQueued = false; for (const t of session.turns) if (t.role === 'assistant' && t.id !== nowId) paintOne(t); paintFollow(); paintToc(); };
  if (!nowId) { rest(); return; }
  const t = session.turns.find(x => x.id === nowId); if (t) paintOne(t);
  if (!extrasQueued) { extrasQueued = true; requestAnimationFrame(() => { nowId = null; rest(); }); }
}
// 来源类操作（保留 / × / 加入来源 / 删除 / 恢复）：先改内存、同步重建来源块，写盘放后台（写链串行）。
// 写盘失败：读回磁盘上的会话当真值（连点多次时以磁盘为准，不把后面成功的也回滚），重画，说原因
function srcOp(mutate, tid = null) {
  if (readOnly) return Promise.resolve();
  mutate();
  paintAllExtras(tid);
  return persist().catch(async e => {
    try {
      const disk = JSON.parse(await app.vault.adapter.read(SESSION_PATH));
      if (disk && Array.isArray(disk.turns) && disk.id === session.id) {
        session.turns = adoptTurns(session.turns, disk.turns); session.excluded = idList(disk.excluded); session.pinned = idList(disk.pinned);
      }
    } catch {}
    notice(NOT_SAVED + errText(e));
    await drawChat();
  });
}

function drawActions(acts, el, t) {
  const mk = (text, cls, k, title) => { const b = acts.createEl('button', { cls: 'lbchat-act' + (cls ? ' ' + cls : ''), text, attr: title ? { title } : {} }); b.type = 'button'; b.dataset.k = k; return b; };
  if (t.failed && t.error) {
    // A5 / A6：失败轮——「重试」「改一下再问」；没配 AI / key 被拒 / 欠费另给「去设置」
    if (readOnly) return;
    const code = String(t.error.code || '');
    if (t.error.kind === 'config' || code === 'NEEDS_HUMAN.AUTH_FAILED' || /QUOTA/.test(code)) mk('去设置', 'lbchat-gosetup', 'setup').onclick = () => { try { provider()?.openSetupPage?.('ai'); } catch (e) { notice(errText(e)); } };
    if (t.q) {
      mk('重试', 'lbchat-retry', 'retry').onclick = () => retryTurn(t);
      mk('改一下再问', 'lbchat-rephrase', 'rephrase').onclick = () => rephrase(t);
    }
    return;
  }
  if (t.failed && t.stopped) {
    // 停止的半截：给「复制」（不含「已停止生成」那行）和「重试」
    const copy = mk('复制', 'lbchat-copy', 'copy');
    copy.onclick = async () => { try { await navigator.clipboard.writeText(stripStopped(t.content)); copy.setText('已复制'); } catch { copy.setText('复制失败'); } };
    if (t.q && !readOnly) mk('重试', 'lbchat-retry', 'retry').onclick = () => retryTurn(t);
    return;
  }
  if (t.failed) return;   // 旧版失败轮：只显示原文
  const copy = mk('复制', 'lbchat-copy', 'copy');
  copy.onclick = async () => { try { await navigator.clipboard.writeText(t.content + '\n\n' + (t.sources || []).map(sourceText).join('\n\n')); copy.setText('已复制'); } catch { copy.setText('复制失败'); } };
  if (readOnly) return;
  // A3：双击不再进编辑（留给选词复制）；操作行的「编辑」原地替换正文
  mk('编辑', 'lbchat-edit', 'edit').onclick = () => editAnswer(el, t, true);
  const exportOptions = acts.createEl('details', { cls: 'lbchat-export' }); exportOptions.createEl('summary', { text: '导出' });
  const imageLabel = exportOptions.createEl('label', { text: '附带原图 ' }); const bundleImages = imageLabel.createEl('input'); bundleImages.type = 'checkbox'; bundleImages.checked = true;
  // R2：导出 = 当前保留的全部来源（删掉的除外）——主要依据全文进包、回答引用过的标引用号；其他相关以胶囊（标题 + 链接 + 命中摘录）写进回答文件
  for (const [label, copyMode] of [['导出资料包', false], ['复制文件包', true]]) {
    const exportBtn = exportOptions.createEl('button', { cls: 'lbchat-act', text: label });
    exportBtn.onclick = async () => {
      const used = new Set([...t.content.matchAll(/\[来源(\d+)(?:\s*[·· ]?\s*段(\d+))?\]/g)].map(m => Number(m[1])));
      const gone = new Set(t.removed || []);
      const currentSources = (t.sources || []).filter(s => !gone.has(srcKey(s))).map(s => ({ ...s, cited: used.has(Number(s.citation)) }));
      const keptRelated = (t.related || []).filter(s => !gone.has(srcKey(s)));
      const dropped = [...(t.sources || []), ...(t.related || [])].filter(s => gone.has(srcKey(s)));
      exportBtn.disabled = true; exportBtn.setText(copyMode ? '复制中…' : '导出中…');
      let failed = false;
      try { await provider().exportArchiveBundle(currentSources.map(s => s.id), bundleImages.checked, answerExportMd({ ...t, sources: currentSources, related: keptRelated, dropped }), { question: t.q || '当前问答', askedAt: t.askedAt || 'unknown', copy: copyMode }); }
      catch (e) { failed = true; notice('导出没成：' + errText(e)); exportBtn.setText('导出失败'); setTimeout(() => { exportBtn.setText(label); }, 3000); }
      finally { exportBtn.disabled = false; if (!failed) exportBtn.setText(label); }
    };
  }
  if (t.layout === 'board' && boardCount(parseBoard(t.content)) >= 2) {
    const note = mk('存成笔记', 'lbchat-savenote', 'savenote', '把这份陈列存进库里「报告」文件夹（封面、出处链接都带上，手机 Obsidian 也能看）');
    note.onclick = async () => {
      note.disabled = true;
      try { const path = await saveBoardNote(t); if (path) { notice('已存成笔记：' + path.replace(/^.*?报告\//, '报告/'), 3000); try { await app.workspace.openLinkText(path, '', true); } catch {} } }
      catch (e) { notice('没存成：' + errText(e)); }
      finally { note.disabled = false; }
    };
  }
  // 1015：「展开」绑这一答自己（turn + 留下的主要依据 id），不再对「上一答」发固定话术；目录型回答在目录卡里逐条 / 全部展开
  if (!(t.answerMode === 'toc' && (t.toc || []).length)) {
    const removedHere = new Set(t.removed || []);
    const ids = (t.sources || []).filter(s => !removedHere.has(srcKey(s))).map(s => s.id).filter(Boolean);
    if (ids.length) { const details = mk('展开细节', 'lbchat-expand', 'more', `只在这一答的 ${ids.length} 条来源里展开细节（原帖和评论区分开写）`); details.disabled = isBusy(); details.onclick = () => expandTurn(t, ids, t.q || '这一答'); }
  }
  if (!t.savedId) t.savedId = archive.entries.find(e => e.kind === 'report' && e.content === t.content)?.id;
  const saved = () => archive.entries.some(e => e.id === t.savedId);
  const save = mk('', 'lbchat-bookmark', 'save');
  save.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg><span class="lb-visually-hidden">存到已保存</span>';
  const paintSave = () => { save.classList.toggle('is-saved', saved()); save.setAttribute('aria-pressed', String(saved())); save.setAttribute('title', saved() ? '从「已保存」移除' : '存到「已保存」'); }; paintSave();
  save.onclick = async () => {
    if (save.disabled) return; save.disabled = true;
    const wasSaved = saved(), prevId = t.savedId;
    const ok = await archiveChange(() => {
      if (wasSaved) archive.entries = archive.entries.filter(e => e.id !== t.savedId);
      else { t.savedId = uid(); archive.entries.unshift({ id: t.savedId, ts: new Date().toISOString(), kind: 'report', title: t.q || 'AI 整理', content: t.content, sources: t.sources || [] }); }
    });
    if (!ok) t.savedId = prevId;
    else { await keepSession(); notice(wasSaved ? '已从「已保存」移除' : '已存到「已保存」', 2500); }
    save.disabled = false; paintSave();
  };
}
// 目录卡（1015 先目录后展开）：「1 · 标题 · 作者 · 命中点 · [来源类型]」每条可单独展开，顶上「全部展开」；标题点开来源（右侧）
function drawTocCard(box, el, t) {
  const toc = t.answerMode === 'toc' && !t.failed ? (t.toc || []) : [];
  if (!toc.length) return;
  const card = box.createEl('div', { cls: 'lbchat-tocard' });
  const head = card.createEl('div', { cls: 'lbchat-tocard-head' });
  head.createEl('span', { cls: 'lbchat-tocard-title', text: `目录 · ${toc.length} 条` });
  if (t.tocNote) head.createEl('span', { cls: 'lbchat-tocard-note', text: t.tocNote });
  const done = t.expanded && typeof t.expanded === 'object' ? t.expanded : {};
  const allIds = toc.map(it => it.id).filter(Boolean);
  const canAct = !readOnly;
  if (canAct && allIds.length > 1) {
    const all = head.createEl('button', { cls: 'lbchat-act lbchat-tocard-all', text: '全部展开', attr: { title: `把这 ${allIds.length} 条一起展开（一次作答，按条写细节）` } }); all.type = 'button'; all.dataset.k = 'toc-all';
    all.disabled = isBusy();
    all.onclick = () => expandTurn(t, allIds, `全部 ${allIds.length} 条`);
  }
  const findSrc = it => [...(t.sources || []), ...(t.related || [])].find(s => s.id && s.id === it.id) || (it.note ? { note: it.note, title: it.title } : null);
  let group = null;
  const list = card.createEl('ol', { cls: 'lbchat-tocard-list' });
  for (const it of toc) {
    if (it.group && it.group !== group) { group = it.group; list.createEl('li', { cls: 'lbchat-tocard-group', text: it.group }); }
    const li = list.createEl('li', { cls: 'lbchat-tocard-item' });
    if (it.id) li.dataset.id = it.id;
    li.createEl('span', { cls: 'lbchat-tocard-n', text: String(it.n) });
    const main = li.createEl('div', { cls: 'lbchat-tocard-main' });
    const line = main.createEl('div', { cls: 'lbchat-tocard-line' });
    const src = findSrc(it);
    const tb = line.createEl(src ? 'button' : 'span', { cls: 'lbchat-tocard-name', text: it.title, attr: { title: src ? '在右侧打开这一篇' : it.title } });
    if (src) { tb.type = 'button'; tb.onclick = () => openNote(src); }
    if (it.author) line.createEl('span', { cls: 'lbchat-tocard-author', text: it.author });
    for (const k of kindLabels(it.kind)) line.createEl('span', { cls: 'lbchat-tocard-kind', text: k });
    const sub = [it.hit, it.price && `价格：${it.price}`, it.where && `哪买：${it.where}`].filter(Boolean).join(' · ');
    if (sub) main.createEl('div', { cls: 'lbchat-tocard-hit', text: sub });
    if (!canAct || !it.id) continue;
    const to = done[it.id];
    const b = li.createEl('button', { cls: 'lbchat-act lbchat-tocard-expand' + (to ? ' is-done' : ''), text: to ? '已展开 ↓' : '展开', attr: { title: to ? '跳到展开的那一段' : '只展开这一条（带着这一答的 turn 和这篇的 id）' } }); b.type = 'button'; b.dataset.k = 'toc:' + it.id;
    if (to) b.onclick = () => { const v = views.get(to); if (v) jumpTo(v.el, { flash: true }); else expandTurn(t, [it.id], it.title); };
    else { b.disabled = isBusy(); b.onclick = () => expandTurn(t, [it.id], it.title); }
  }
  if (t.tocSuggest) card.createEl('div', { cls: 'lbchat-tocard-suggest', text: '可补：' + t.tocSuggest });
}
const stripStopped = s => String(s || '').replace(/\n*> 已停止生成。\s*$/, '').trim();

// ── A3 编辑：原地替换正文（编辑框在来源块之前）；Ctrl+Enter 保存、Esc 取消；写盘失败内容改回、编辑框留着 ──
function editText(mdEl, entryOrGet, save, focus = true) {
  const cur = () => (typeof entryOrGet === 'function' ? entryOrGet() : entryOrGet);
  const entry = cur();
  const parent = mdEl.parentNode;
  if (!parent || parent.querySelector('.lbchat-editor')) return null;
  const editor = createEl('textarea', { cls: 'lbchat-editor' }); editor.value = entry.content;
  const bar = createDiv({ cls: 'lbchat-editbar' });
  const ok = bar.createEl('button', { cls: 'lbchat-act lbchat-editsave', text: '保存修改' }); ok.type = 'button';
  const cancel = bar.createEl('button', { cls: 'lbchat-act lbchat-editcancel', text: '取消' }); cancel.type = 'button';
  bar.createEl('span', { cls: 'lbchat-edithint', text: 'Ctrl+Enter 保存 · Esc 取消' });
  parent.insertBefore(editor, mdEl); parent.insertBefore(bar, mdEl);
  mdEl.hidden = true;
  const grow = () => { try { editor.style.height = 'auto'; const vh = (window.innerHeight || 800) * 0.7; editor.style.height = Math.min(Number(editor.scrollHeight) || 120, vh) + 'px'; } catch {} };
  grow(); editor.oninput = grow;
  const close = () => { editor.remove(); bar.remove(); mdEl.hidden = false; };
  const doSave = async () => {
    const e0 = cur(); const prev = e0.content; e0.content = editor.value; ok.disabled = true;
    try { await save(e0); if (editor.isConnected) close(); }
    catch (e) { e0.content = prev; notice(NOT_SAVED + errText(e)); }
    finally { ok.disabled = false; }
  };
  ok.onclick = doSave; cancel.onclick = close;
  editor.onkeydown = e => {
    if (e.isComposing) return;
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault?.(); doSave(); }
    else if (e.key === 'Escape') { e.preventDefault?.(); e.stopPropagation?.(); close(); }
  };
  editor._lbCancel = close;
  if (focus) { try { editor.focus({ preventScroll: true }); editor.setSelectionRange(editor.value.length, editor.value.length); } catch {} }
  return editor;
}
function editAnswer(el, t, focus) {
  const mdEl = el.querySelector('.lbchat-md'); if (!mdEl) return;
  // 按 id 取会话里当前那一轮（作答中 / 别的页写盘后会话会被读回合并）
  editText(mdEl, () => session.turns.find(x => x && x.id === t.id) || t, async cur => {
    const stored = archive.entries.find(x => x.id === cur.savedId);
    if (stored) { const prev = stored.content; stored.content = cur.content; try { await saveArchive(); } catch (e) { stored.content = prev; throw e; } }
    await enqueueWrite(saveSession); announce();
    await drawChat();
  }, focus);
}

// ── ② 追问绑定当前来源（10-04） ──
// 上一轮回答 = 最近一条没失败 / 没被停掉的回答；它「留下的来源」= 主要依据 + 其他相关里没删的，本会话保留（pin）的排最前，排除的不要
function lastAnswer() { for (let i = session.turns.length - 1; i >= 0; i--) { const t = session.turns[i]; if (t.role === 'assistant' && !t.failed) return t; } return null; }
function keptIds(t) {
  if (!t) return [];
  const removed = new Set(t.removed || []), ex = new Set(session.excluded);
  const kept = [...(t.sources || []), ...(t.related || [])].filter(s => !removed.has(srcKey(s))).map(s => s.id).filter(Boolean);
  return [...new Set([...session.pinned.filter(k => !removed.has(k)), ...kept])].filter(k => !ex.has(k));
}
function boundIds() { return session.follow === 'search' ? [] : keptIds(lastAnswer()); }
// N11「问这篇」：来源预设成这一篇（存页面状态，Dataview 重跑 / 换页回来还在），提交后清掉
let scope = pageState.scope && Array.isArray(pageState.scope.ids) && pageState.scope.ids.length ? pageState.scope : null;
const scopeOpts = () => (scope ? { scope: { ...scope } } : {});
function clearScope() { scope = null; LB.state.patch({ scope: null }); paintFollow(); }
// 1020 她：两个词并排的小开关（选中的加深 + 下划线），点另一个就切过去；不写「改为……」
function segSwitch(parent, cls, opts, current, onPick) {
  const box = parent.createEl('span', { cls: 'lbchat-seg ' + cls, attr: { role: 'radiogroup' } });
  opts.forEach(([key, label, title], i) => {
    if (i) box.createEl('span', { cls: 'lbchat-seg-dot', text: '·' });
    const b = box.createEl('button', { cls: 'lbchat-seg-opt' + (key === current ? ' is-on' : ''), text: label, attr: { type: 'button', role: 'radio', 'aria-checked': String(key === current), title } });
    b.dataset.k = key;
    b.onclick = () => { if (key !== current) onPick(key); };
  });
  return box;
}
function paintFollow() {
  followBar.empty(); clearBox.empty(); clearBtn = null;
  const ids = lane === 'chat' ? keptIds(lastAnswer()) : [];
  const bound = session.follow === 'sources';
  followBar.hidden = readOnly || lane !== 'chat' || (!session.turns.length && !scope);
  clearBox.hidden = readOnly || lane !== 'chat' || !session.turns.length;
  search.placeholder = scope ? `问这篇：${scope.title || ''}…` : !session.turns.length ? (cfg().chatPlaceholder || '问点什么呢？') : ids.length && bound ? '在当前来源里继续追问…' : '继续追问…';
  if (!clearBox.hidden) {
    clearBtn = clearBox.createEl('button', { cls: 'lbchat-follow-switch lbchat-clearall', text: '清空上下文', attr: { title: session.private ? '开始新对话（隐私模式：这段不进历史，8 秒内可撤销）' : '开始新对话（这段已自动存进历史）' } });
    clearBtn.type = 'button';
    clearBtn.onclick = () => clearSession();
    paintClear();
  }
  if (followBar.hidden) return;
  if (scope) {
    followBar.createEl('span', { cls: 'lbchat-follow-label', text: '只问这一篇：' });
    const t = followBar.createEl('button', { cls: 'lbchat-follow-switch lbchat-scope-title', text: `《${scope.title || ''}》`, attr: { title: '在右侧打开这一篇' } }); t.type = 'button';
    t.onclick = () => openNote(scope.note);
    followBar.createEl('span', { cls: 'lbchat-follow-sep', text: '·' });
    const x = followBar.createEl('button', { cls: 'lbchat-follow-switch lbchat-scope-cancel', text: '取消', attr: { title: '不只问这一篇了，照常检索' } }); x.type = 'button';
    x.onclick = () => clearScope();
    return;
  }
  // 追问 = 接着这段、只在上面留下的来源里答（还没有来源就接着这段重新搜）；新对话 = 重新搜整个收藏，这段自动进历史（隐私模式不进）
  segSwitch(followBar, 'lbchat-followmode', [
    ['sources', '追问', ids.length ? `接着这段问，只在上面这 ${ids.length} 条来源里答` : '接着这段问'],
    ['search', '新对话', session.private ? '下一问重新搜整个收藏（隐私模式：不开新段）' : '下一问重新搜整个收藏，这段自动存进历史'],
  ], bound ? 'sources' : 'search', async key => { session.follow = key; session.followPicked = true; paintFollow(); await keepSession(); });
}
// A6：问答 AI 没配好的事先提示——空白页在「答案来自你的收藏…」下面一行，有会话时在输入框上方一行；「去设置」打开设置页 AI 栏
function paintCfgHint() {
  const off = !readOnly && aiReady(modelPick.hidden ? '' : modelPick.value) === false;
  const fill = el => {
    el.empty(); el.appendText('问答还没配 AI（归档、浏览、搜索不受影响）· ');
    const b = el.createEl('button', { cls: 'lbchat-cfgbtn', text: '去设置' }); b.type = 'button';
    b.onclick = () => { try { provider()?.openSetupPage?.('ai'); } catch (e) { notice(errText(e)); } };
  };
  const empty = [...bodyEl.children].find(n => n._lbEmpty);
  if (empty) {
    let h = empty.querySelector('.lbchat-cfghint');
    if (off && !h) { h = empty.createEl('div', { cls: 'lbchat-cfghint' }); fill(h); }
    else if (!off && h) h.remove();
  }
  cfgBar.hidden = !(off && lane === 'chat' && session.turns.length > 0);
  if (!cfgBar.hidden && !cfgBar.childNodes.length) fill(cfgBar);
}
// ⑤ 「清空」（10-04 改）：只清当前页面显示、开始一段新对话，不删记录——这一段已经自动存在历史里。
// M1：隐私模式下不进历史，清空后 8 秒内可撤销（不再弹原生确认）
async function clearSession() {
  if (isBusy()) { notice(BUSY_TEXT, 3000); return false; }
  if (readOnly || !session.turns.length) return false;
  const prev = sessionSnapshot(), prevHist = hist;
  try { await enqueueWrite(() => saveToHistory(prev)); } catch (e) { notice('没清空：这段对话没能存进历史，内容还在：' + errText(e)); return false; }
  const ok = await startConversation(prev, prevHist);
  if (ok && prev.private) LB.undoNotice('已清空（隐私模式，这段不进历史）', () => startConversation(sessionSnapshot(), hist, { ...prev, private: true }), 8000);
  return ok;
}
async function startConversation(prev = sessionSnapshot(), prevHist = hist, next = null) {
  const keepPrivate = session.private;
  Object.assign(session, next ? { ...next, turns: ensureIds(next.turns || []) } : { id: uid(), startedAt: new Date().toISOString(), turns: [], excluded: [], pinned: [], follow: prefs.follow, followPicked: false });
  session.private = next ? !!next.private : keepPrivate;
  try { await enqueueWrite(() => writeJson(SESSION_PATH, sessionSnapshot())); announce(); }
  catch (e) { Object.assign(session, prev); hist = prevHist; notice('没清空：' + errText(e)); return false; }
  saveDraft(''); lastTop = 0; stick = true; back = null; unseen = false; struck.clear(); picks.clear(); openState.clear();
  LB.state.patch({ scrollTop: next ? undefined : 0 });
  paintPrivacy();
  resetViews();
  if (lane !== 'chat') await setLane('chat'); else await drawChat({ restore: 'bottom' });
  focusSearch();
  return true;
}

// ── 「已保存」栏 ──
async function drawArchive() {
  bodyEl.empty(); disposeArchive(); followBar.hidden = true; cfgBar.hidden = true;
  const addRow = bodyEl.createEl('div', { cls: 'lbchat-arc-add' });
  const ta = addRow.createEl('textarea', { cls: 'lbchat-arc-input' });
  ta.placeholder = '写一条自己的判断，Enter 存（Shift+Enter 换行）…';
  ta.rows = 1;
  // 1015「标作者」：这条判断是谁说的 / 关于哪位作者——小输入框，空着 = 我
  const who = addRow.createEl('input', { cls: 'lbchat-arc-author', attr: { type: 'text', placeholder: '作者（空 = 我）', 'aria-label': '作者', title: '这条判断标哪个作者（空着 = 我自己）' } });
  who.value = typeof LB.state.load().arcAuthor === 'string' ? LB.state.load().arcAuthor : '';
  if (readOnly) addRow.hidden = true;
  const saveIt = addRow.createEl('button', { cls: 'lbchat-arc-save', text: '存' });
  let saving = false;
  saveIt.onclick = async () => {
    const txt = ta.value.trim(); if (!txt || saving) return;
    const author = String(who.value || '').trim();
    saving = true;
    // 写盘成功才清输入框；失败字留在框里（§1.5）
    try { if (!(await archiveChange(() => archive.entries.unshift({ id: uid(), ts: new Date().toISOString(), kind: 'note', title: '', content: txt, author: author || '我' })))) return; }
    finally { saving = false; }
    ta.value = ''; LB.state.patch({ arcAuthor: author }); await drawArchive(); notice('已保存', 2000);
    try { bodyEl.querySelector('.lbchat-arc-input')?.focus?.({ preventScroll: true }); } catch {}
  };
  // 1015：Enter 直接存（组字中不算；Shift+Enter 换行）
  const enterSave = e => { if (e.isComposing || e.keyCode === 229 || e.key !== 'Enter' || e.shiftKey) return; e.preventDefault?.(); saveIt.onclick(); };
  ta.addEventListener('keydown', enterSave); who.addEventListener('keydown', enterSave);
  if (!archive.entries.length) { bodyEl.createEl('div', { cls: 'lbchat-empty', text: '还没有保存的内容。可以保存回答，或在上面记下自己的判断。' }); paintFloaters(); paintToc(); return; }
  // ⑥ 已保存：默认每条只一行标题（回答 = 提问原话；自己写的判断 = 第一行），点开才展开正文
  for (const e of archive.entries) {
    const item = bodyEl.createEl('details', { cls: 'lbchat-arc-item' });
    item.dataset.savedId = String(e.id);
    const headEl = item.createEl('summary', { cls: 'lbchat-arc-head' });
    if (e.kind === 'note') headEl.createEl('span', { cls: 'lbchat-arc-who', text: e.author || '我', attr: { title: '作者' } });
    headEl.createEl('span', { cls: 'lbchat-arc-title', text: (e.title || String(e.content || '').trim().split('\n')[0] || '未命名').replace(/^#+\s*/, '') });
    headEl.createEl('span', { cls: 'lbchat-arc-when', text: fmtTs(e.ts) });
    const meta = item.createEl('div', { cls: 'lbchat-arc-meta' });
    meta.createEl('span', { cls: 'lbchat-arc-kind', text: e.kind === 'note' ? `判断 · ${e.author || '我'}` : 'AI 报告' });
    const b = item.createEl('div', { cls: 'lbchat-arc-body' });
    archiveDisposers.push(await renderScoped(e.content, b));
    bindSources(b, e.sources || []); enhanceMermaid(b);
    if (readOnly) continue;
    const edit = meta.createEl('button', { cls: 'lbchat-act', text: '编辑' }); edit.type = 'button';
    edit.onclick = () => { item.open = true; editText(b, e, async () => { await saveArchive(); await drawArchive(); }); };
    // 1015「可简单删除」：× 放在标题那一行（不用先点开），点了不展开这一条
    const del = headEl.createEl('button', { cls: 'lbchat-arc-del', text: '✕', attr: { title: '删除（几秒内可撤销）', 'aria-label': '删除这条' } }); del.type = 'button';
    // A15：删了几秒内可撤销（不弹确认，保持她「不弹确认」的风格）；撤销写盘失败照固定句式说
    del.onclick = async ev => {
      ev?.preventDefault?.(); ev?.stopPropagation?.();
      const index = archive.entries.findIndex(x => x.id === e.id);
      if (!(await archiveChange(() => { archive.entries = archive.entries.filter(x => x.id !== e.id); }))) return;
      await drawArchive();
      const title = (e.title || String(e.content || '').trim().split('\n')[0] || '未命名').replace(/^#+\s*/, '').slice(0, 20);
      LB.undoNotice(`已删除「${title}」`, async () => {
        const ok = await archiveChange(() => { archive.entries.splice(Math.min(Math.max(index, 0), archive.entries.length), 0, e); });
        if (!ok) return true;   // archiveChange 已经说过「没保存上…」，别再说一遍
        if (lane === 'archive') await drawArchive();
        return true;
      }, 6000);
    };
  }
  paintFloaters(); paintToc();
}
function fmtTs(ts) { try { const d = new Date(ts); return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; } catch { return ''; } }

// ── 回答下面的来源（第 10 批）：「主要依据」= 送进模型的那些（带 [来源N]），「其他相关」= 候选池其余（默认收起）。
// A1：× 之后那行留在原位划掉（本页内），只剩「恢复」；summary 计数按留下的算。重开页面后被删的照旧不显示
const srcKey = s => s.id || s.note || s.title;
function drawSources(box, el, t) {
  const primary = t.sources || [], related = t.related || [];
  if (!primary.length && !related.length) return;
  const removed = new Set(t.removed || []);
  const canEdit = !readOnly && !isBusy();
  const selected = picks.get(t.id) || new Map();
  picks.set(t.id, selected);
  let bulk = null, bulkCount = null;
  const paintBulk = () => { if (!bulk) return; bulk.hidden = !selected.size; bulkCount.setText(`已选 ${selected.size} 条`); el.classList.toggle('lbchat-selecting', selected.size > 0); };
  // 加入来源 = 「其他相关」里的提为主要依据，并且和主要依据里选中的一起「保留」（本会话之后的追问 / 重答都带上、排最前）
  const promote = list => {
    const ids = list.map(src => src.id).filter(Boolean);
    if (!ids.length) return 0;
    session.pinned = idList([...session.pinned, ...ids]);
    session.excluded = session.excluded.filter(k => !ids.includes(k));
    t.removed = (t.removed || []).filter(k => !ids.includes(k));
    for (const k of ids) struck.delete(t.id + ':' + k);
    let next = Math.max(0, ...(t.sources || []).map(x => Number(x.citation) || 0));
    const moved = (t.related || []).filter(src => ids.includes(src.id));
    t.sources = [...(t.sources || []), ...moved.map(src => ({ ...src, citation: ++next, tier: 'primary', added: true }))];
    t.related = (t.related || []).filter(src => !ids.includes(src.id));
    t.added = idList([...(t.added || []), ...moved.map(src => src.id)]);
    if (moved.length) for (const s of moved) flashKeys.add(t.id + ':' + srcKey(s));
    return ids.length;
  };
  // × / 删除 = 本会话排除（可恢复）：记进这一轮的 removed，也记进会话的 excluded；排除压过保留
  const drop = list => {
    const keys = list.map(srcKey).filter(Boolean);
    t.removed = idList([...(t.removed || []), ...keys]);
    session.excluded = idList([...session.excluded, ...keys]);
    session.pinned = session.pinned.filter(k => !keys.includes(k));
    t.added = (t.added || []).filter(k => !keys.includes(k));
    for (const k of keys) struck.add(t.id + ':' + k);
  };
  const restore = keys => {
    const back = new Set(keys);
    t.removed = (t.removed || []).filter(k => !back.has(k));
    session.excluded = session.excluded.filter(k => !back.has(k));
    for (const k of keys) struck.delete(t.id + ':' + k);
  };
  const togglePin = src => srcOp(() => { const k = src.id; if (session.pinned.includes(k)) session.pinned = session.pinned.filter(x => x !== k); else promote([src]); }, t.id);
  const hitText = src => {
    const parts = (src.excerpts || []).filter(p => p && p.text).slice(0, 2);
    const clip = x => { const s = String(x || '').replace(/\s+/g, ' ').trim(); return s.length > 140 ? s.slice(0, 140) + '…' : s; };
    if (parts.length) return parts.map(p => `${partWhere(p) || '原文'}：${clip(p.text)}`);
    if (src.excerpt) return [`${partWhere({ field: src.excerpt_field || '' }) || '原文'}：${clip(src.excerpt)}`];
    return [];
  };
  const mdEl = el.querySelector('.lbchat-md');
  // 每行：选中圈 · 标题（点开原文；「我保存的」带小标、原地展开）· ↑ 引用处 · 命中 · 保留 · ×
  const row = (list, src, label, tier) => {
    const key = srcKey(src);
    const gone = key && removed.has(key);
    if (gone && !struck.has(t.id + ':' + key)) return;
    const line = list.createEl('div', { cls: 'lbchat-srcrow' + (gone ? ' is-removed' : '') });
    if (key) line.dataset.srcKey = key;
    if (flashKeys.delete(t.id + ':' + key)) line.classList.add('lbchat-flash');
    if (!gone && canEdit && key) {
      const on = selected.has(key);
      const pick = line.createEl('button', { cls: 'lbchat-src-check' + (on ? ' is-on' : ''), attr: { role: 'checkbox', 'aria-checked': String(on), 'aria-label': '选中：' + (src.title || ''), title: '选中（可多选）' } });
      pick.type = 'button'; pick.dataset.k = 'pick:' + key;
      if (on) line.classList.add('is-picked');
      pick.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
      pick.onclick = e => { e?.stopPropagation?.(); const now = !selected.has(key); if (now) selected.set(key, src); else selected.delete(key); pick.classList.toggle('is-on', now); pick.setAttribute('aria-checked', String(now)); line.classList.toggle('is-picked', now); paintBulk(); };
    }
    if (src.source_kind === 'saved') line.createEl('span', { cls: 'lbchat-src-kind', text: '我保存的' });
    const a = line.createEl('a', { text: label });
    const where = evidenceWhere(src);
    if (where) a.setAttribute('title', '命中：' + where);
    a.onclick = () => openNote(src);
    const acts = line.createEl('span', { cls: 'lbchat-srcrow-acts' });
    if (gone) {
      const rb = acts.createEl('button', { cls: 'lbchat-act lbchat-src-restore', text: '恢复', attr: { title: '放回来源（本会话之后的追问 / 重答照常用它）' } }); rb.type = 'button'; rb.dataset.k = 'restore:' + key;
      rb.onclick = () => srcOp(() => restore([key]), t.id);
      return;
    }
    // F5：本轮正文里引用过它 → 「↑ 引用处」跳到第一个胶囊
    if (tier === 'primary' && mdEl && mdEl.querySelector(`button.lbchat-cite[data-cite="${src.citation}"]`)) {
      const up = acts.createEl('button', { cls: 'lbchat-act lbchat-src-back', text: '↑ 引用处', attr: { title: '跳到回答里引用它的地方' } }); up.type = 'button'; up.dataset.k = 'up:' + key;
      up.onclick = () => { const c = mdEl.querySelector(`button.lbchat-cite[data-cite="${src.citation}"]`); if (c) jumpTo(c, { flash: true }); };
    }
    const lines = hitText(src);
    if (lines.length) {
      const hk = `${t.id}:hit:${key}`;
      const open = openState.has(hk);
      const hit = acts.createEl('button', { cls: 'lbchat-act lbchat-src-hitbtn' + (open ? ' is-on' : ''), text: '命中', attr: { title: '看这一篇命中的原文', 'aria-expanded': String(open) } }); hit.type = 'button'; hit.dataset.k = 'hit:' + key;
      // 命中原文就挂在这一行下面（同一个列表里，紧跟着它）；再点收起
      const detail = list.createEl('div', { cls: 'lbchat-src-hit' }); detail.hidden = !open;
      for (const l of lines) detail.createEl('div', { text: l });
      hit.onclick = () => { detail.hidden = !detail.hidden; const now = !detail.hidden; if (now) openState.add(hk); else openState.delete(hk); hit.setAttribute('aria-expanded', String(now)); hit.classList.toggle('is-on', now); };
    }
    if (src.source_kind === 'saved') drawSavedInline(list, t, src);
    if (canEdit && src.id) { const on = session.pinned.includes(src.id); const pin = acts.createEl('button', { cls: 'lbchat-act lbchat-src-pin' + (on ? ' is-on' : ''), text: on ? '已保留' : '保留', attr: { title: on ? '取消保留' : '本会话后面的追问 / 重答都带上这篇（可取消）', 'aria-pressed': String(on) } }); pin.type = 'button'; pin.dataset.k = 'pin:' + key; pin.onclick = () => togglePin(src); }
    if (canEdit && key) { const x = acts.createEl('button', { cls: 'lbchat-act lbchat-src-del', text: '×', attr: { title: '从来源里删掉（本会话不再用，可恢复）' } }); x.type = 'button'; x.dataset.k = 'del:' + key; x.onclick = () => srcOp(() => drop([src]), t.id); }
  };
  // 收起时 summary 后面的浅色小字（默认仍收起，她 10-03 验收过）；展开就不再提示
  const summaryOf = (d, text, list, hint) => {
    const s = d.createEl('summary'); s.appendText(text);
    const kept = list.filter(x => x.id && session.pinned.includes(x.id)).length;
    if (kept) s.createEl('span', { cls: 'lbchat-src-kept', text: `已保留 ${kept}` });
    if (hint && canEdit) s.createEl('span', { cls: 'lbchat-src-hint', text: '点开可多选 / 保留 / 删除来源' });
  };
  const details = (cls, k) => {
    const d = box.createEl('details', { cls });
    const sk = `${t.id}:${k}`;
    if (openState.has(sk)) d.open = true;
    d.dataset.part = k;
    d.addEventListener('toggle', () => { if (d.open) openState.add(sk); else openState.delete(sk); });
    return d;
  };
  const visible = list => list.filter(s => !removed.has(srcKey(s)) || struck.has(t.id + ':' + srcKey(s)));
  const keptPrimary = primary.filter(s => !removed.has(srcKey(s))), keptRelated = related.filter(s => !removed.has(srcKey(s)));
  let hinted = false;
  if (visible(primary).length || !related.length) {
    const refs = details('lbchat-src', 'primary');
    summaryOf(refs, related.length ? `主要依据 · ${keptPrimary.length}` : `参考材料 · ${keptPrimary.length}`, keptPrimary, hinted = keptPrimary.length > 0);
    for (const src of visible(primary)) row(refs, src, `[来源${src.citation}] ${src.title}`, 'primary');
  }
  if (visible(related).length) {
    const more = details('lbchat-src lbchat-src-more', 'related');
    summaryOf(more, `可能相关 · ${keptRelated.length}`, keptRelated, !hinted);
    for (const src of visible(related)) row(more, src, src.title, 'related');
  }
  if (canEdit) {
    bulk = box.createEl('div', { cls: 'lbchat-src-bulk' }); bulk.hidden = true;
    bulkCount = bulk.createEl('span', { cls: 'lbchat-src-bulkcount' });
    const add = bulk.createEl('button', { cls: 'lbchat-act lbchat-src-add', text: '加入来源', attr: { title: '选中的「可能相关」提为主要依据；选中的都保留（之后的追问 / 重答都带上、必须用到）' } }); add.type = 'button';
    const del = bulk.createEl('button', { cls: 'lbchat-act lbchat-src-bulkdel', text: '删除', attr: { title: '从来源里删掉（本会话不再用，可恢复）' } }); del.type = 'button';
    const cancel = bulk.createEl('button', { cls: 'lbchat-act', text: '取消' }); cancel.type = 'button';
    add.onclick = () => { let n = 0; const list = [...selected.values()]; selected.clear(); const p = srcOp(() => { n = promote(list); }, t.id); if (n) notice(`已加入 ${n} 条来源：重新回答时排最前、逐条用到`, 3000); return p; };
    del.onclick = () => { const list = [...selected.values()]; const n = list.length; selected.clear(); const p = srcOp(() => drop(list), t.id); if (n) notice(`已删除 ${n} 条来源（可恢复）`, 2500); return p; };
    cancel.onclick = () => { selected.clear(); for (const b of box.querySelectorAll('.lbchat-src-check.is-on')) { b.classList.remove('is-on'); b.setAttribute('aria-checked', 'false'); } for (const r of box.querySelectorAll('.lbchat-srcrow.is-picked')) r.classList.remove('is-picked'); paintBulk(); };
    paintBulk();
  }
  const added = (t.added || []).filter(k => session.pinned.includes(k) && !removed.has(k));
  if ((removed.size || added.length) && !readOnly) {
    const bar = box.createEl('div', { cls: 'lbchat-actions lbchat-src-redo' });
    // 保留过的（含前几轮的）排最前，一起交给重答；删掉的不在里面
    const kept = [...keptPrimary, ...keptRelated].map(s => s.id).filter(Boolean);
    const keep = [...new Set([...session.pinned.filter(k => !removed.has(k)), ...kept])];
    const label = added.length ? `加入后重新回答（${keep.length} 条，含手动加入 ${added.length} 条）` : `按剩下的 ${keep.length} 条重新回答`;
    const redo = bar.createEl('button', { cls: 'lbchat-act', text: label }); redo.type = 'button'; redo.dataset.k = 'redo';
    redo.disabled = isBusy() || !keep.length || !t.q;
    redo.onclick = () => submit(t.q, { sourceIds: keep });
    const undo = bar.createEl('button', { cls: 'lbchat-act', text: `恢复删掉的 ${removed.size} 条` }); undo.type = 'button'; undo.hidden = !removed.size; undo.dataset.k = 'undo';
    undo.onclick = () => srcOp(() => restore([...(t.removed || [])]), t.id);
  }
}
const flashKeys = new Set();
// A12：「我保存的」来源——行下面原地展开那条保存的正文（同「命中」款式），块尾「在「已保存」里打开」
function drawSavedInline(list, t, src) {
  const sk = `${t.id}:saved:${srcKey(src)}`;
  const box = list.createEl('div', { cls: 'lbchat-src-saved' });
  box.dataset.savedKey = srcKey(src);
  box.hidden = !openState.has(sk);
  const fill = async () => {
    if (box._lbFilled) return; box._lbFilled = true;
    const entry = archive.entries.find(e => String(e.id) === String(src.saved_id));
    if (!entry) { box.createEl('div', { text: '这条「已保存」已经删掉了' }); return; }
    const body = box.createEl('div', { cls: 'lbchat-src-saved-body' });
    const d = await renderScoped(entry.content, body);
    const v = views.get(t.id); if (v) { const prev = v.dispose; v.dispose = () => { prev(); d(); }; } else archiveDisposers.push(d);
    const go = box.createEl('button', { cls: 'lbchat-act lbchat-src-saved-open', text: '在「已保存」里打开' }); go.type = 'button';
    go.onclick = () => setLane('archive').then(() => { const item = [...bodyEl.querySelectorAll('.lbchat-arc-item')].find(x => x.dataset.savedId === String(src.saved_id)); if (item) { item.open = true; item.scrollIntoView?.({ block: 'nearest' }); } });
  };
  if (!box.hidden) fill();
  box._lbToggle = (force) => { const open = force ?? box.hidden; box.hidden = !open; if (open) { openState.add(sk); fill(); } else openState.delete(sk); };
}
function openSavedInline(src, fromCite) {
  // 先找到这一行所在的回答（从胶囊点进来就是胶囊所在那一轮；从行标题点就是那一行）
  const answer = fromCite?.closest?.('.lbchat-answer') || null;
  const key = srcKey(src);
  const rows = (answer || bodyEl).querySelectorAll('.lbchat-srcrow').filter(r => r.dataset.srcKey === key);
  const line = rows[rows.length - 1];
  if (!line) return;
  const d = line.closest('details');
  if (d && !d.open) { d.open = true; const t = session.turns.find(x => x.id === line.closest('.lbchat-answer')?.dataset.key); if (t) openState.add(`${t.id}:${d.dataset.part}`); }
  let box = line.nextElementSibling;
  while (box && !box.classList.contains('lbchat-src-saved') && !box.classList.contains('lbchat-srcrow')) box = box.nextElementSibling;
  if (!box || !box.classList.contains('lbchat-src-saved')) return;
  if (fromCite) { box._lbToggle?.(true); jumpTo(line, { flash: true, keepBack: true }); }
  else box._lbToggle?.();
}

// ── 正在生成的回答（A2 / A4）：登记在插件对象上（§5.3 chatInFlight），别的问收藏页（换页回来的新页）照样看得见出字和阶段 ──
const inflight = () => provider()?.chatInFlight || null;
function inFlightElsewhere() { const f = inflight(); return !!(f && f.page !== pageId); }
// 「忙」统一判定：自己在答，或者别的问收藏页在答（同一时刻只答一问）
function isBusy() { return busy || inFlightElsewhere(); }
function phaseText() { const f = inflight(); return f && f.phase ? f.phase + '…' : '正在处理…'; }
function showPhase(text) {
  const f = inflight(); if (f && f.page === pageId) { f.phase = text; try { app.workspace.trigger?.('link-brain:chat-live', pageId); } catch {} }
  paintPhase();
}
function paintPhase() { const el = bodyEl.querySelector('.lbchat-phase'); if (el) el.setText(phaseText()); if (stick) follow(); }
// 流式那一块：div.lbchat-md（已排好版的整行）+ span.lbchat-live-tail（最后一行还没写完的纯文本）
function ensureLive(f) {
  if (liveView && liveView.key === f.id && liveView.el.parentNode === bodyEl) return liveView;
  disposeLive();
  const el = createDiv({ cls: 'lbchat-turn lbchat-answer lbchat-live' }); el.dataset.key = f.id;
  const md = el.createEl('div', { cls: 'lbchat-md' });
  const tail = el.createEl('span', { cls: 'lbchat-live-tail' });
  const think = bodyEl.querySelector('.lbchat-think');
  if (think) think.replaceWith(el); else bodyEl.append(el);
  liveView = { key: f.id, el, md, tail, head: '', dispose: null };
  return liveView;
}
// 节流：距上次渲染 ≥200ms 且上一次渲染完了才渲染；渲染中途又来字就记一笔，完了补一次
let liveTimer = null, liveLast = 0, liveBusy = false, liveDirty = false;
function scheduleLive(now = false) {
  if (liveBusy) { liveDirty = true; return; }
  if (liveTimer) { if (!now) return; clearTimeout(liveTimer); liveTimer = null; }
  const wait = now ? 0 : Math.max(0, 200 - (Date.now() - liveLast));
  liveTimer = setTimeout(async () => {
    liveTimer = null; liveBusy = true; liveDirty = false;
    try { const f = inflight(); if (f && lane === 'chat' && wrap.isConnected) await renderLive(f); }
    finally { liveBusy = false; liveLast = Date.now(); if (liveDirty) { liveDirty = false; scheduleLive(); } }
  }, wait);
}
async function renderLive(f) {
  const lv = ensureLive(f);
  const text = String(f.text || '');
  const cut = text.lastIndexOf('\n');
  const headMd = text.slice(0, cut + 1), tailText = text.slice(cut + 1);
  if (headMd && headMd !== lv.head) {
    const off = createDiv();
    const dispose = await renderScoped(headMd, off);
    if (liveView !== lv) { dispose(); return; }
    bindSources(off, [], { pending: true });
    bindSeeImg(off);
    lv.md.replaceChildren(...off.childNodes);
    try { lv.dispose?.(); } catch {}
    lv.dispose = dispose; lv.head = headMd;
  }
  lv.tail.setText(tailText);
  if (stick) follow(); else markUnseen();
  paintTocLive();
}
// 模型写的 [看图：来源N 图M] 在流式时先显示成小胶囊占位（和 ask.py 的 _SEE_IMG 同一条）；答完由后端换成真图
const SEE_IMG = /[ \t]*\[看图[：:]\s*来源\s*(\d+)\s*[，,、 ]*图\s*(\d+)\]/g;
function bindSeeImg(el) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const text = node.textContent; const matches = [...text.matchAll(SEE_IMG)]; if (!matches.length) continue;
    const frag = document.createDocumentFragment(); let last = 0;
    for (const m of matches) {
      frag.append(document.createTextNode(text.slice(last, m.index)));
      const ph = document.createElement('span'); ph.className = 'lbchat-imgph'; ph.textContent = `图 · 来源${m[1]} 图${m[2]}`; frag.append(ph);
      last = m.index + m[0].length;
    }
    frag.append(document.createTextNode(text.slice(last))); node.replaceWith(frag);
  }
}

// 从目录页带词跳过来要自动问的那一句是新问题：照常检索，不绑上一轮的来源
let nextFresh = !!provider()?.pendingArchiveQuestion;
// opts.sourceIds（第 10 批「按剩下的重新回答」）：只用这些来源再答一次；opts.scope（N11）：只问这一篇；opts.fresh：照常检索
async function submit(raw, opts = {}) {
  if (readOnly) return;
  const text = (raw || '').trim(); if (!text) return;
  if (isBusy()) { enqueue(text, opts); return; }
  const p = provider(); if (!p) return;
  const q = text.replace(/^\//, '').trim(); if (!q) return;
  const askedAt = new Date().toISOString();
  const fresh = !!opts.fresh || nextFresh; nextFresh = false;
  // 1015「展开」：绑定那一答的 turn + 来源 id（opts.expand = {turnId, ids, q, label, of}），只在这些来源里展开，不再发固定话术给「上一答」
  const ex = opts.expand && Array.isArray(opts.expand.ids) && opts.expand.ids.length ? opts.expand : null;
  const sc = Array.isArray(opts.sourceIds) || ex ? null : (opts.scope || scope);
  const ids = ex ? ex.ids : Array.isArray(opts.sourceIds) ? opts.sourceIds : sc ? sc.ids : null;
  const reask = Array.isArray(ids);
  const bound = !reask && !fresh ? boundIds() : [];
  const pinned = reask ? ids : bound.length ? bound : null;
  const mode = ex ? 'expand' : sc ? 'scope' : reask ? 'reask' : bound.length ? 'follow' : 'ask';
  // A5「重试」要原样再问一次：记下这一问用的来源 / 是否重新检索
  const retry = ex ? { expand: { ...ex, ids: [...ex.ids] } } : reask ? { sourceIds: [...ids] } : bound.length ? { sourceIds: [...bound] } : fresh ? { fresh: true } : {};
  if (sc && scope) clearScope();
  // 1015「默认清空」：重新搜的新问题（含「问这篇」）默认开新对话；她选了「接着这段」/ 隐私模式 / 重试那一问时不清
  // 1020：只有「新对话」档才开新段（「追问」档接着这段，没来源时照常重新搜）；keepThread 这个旧偏好不再出现在界面
  const newThread = (mode === 'ask' || mode === 'scope') && session.follow !== 'sources' && !opts.keep && !session.private && session.turns.length > 0;
  const report = !ex && !!prefs.report;
  const backendQ = ex ? `展开「${ex.label || ex.q || ''}」的细节（原问题：${ex.q || ''}）` : report ? '/报告 ' + q : q;
  const userTurn = { id: uid(), role: 'user', content: q, mode, askedAt, ...(report ? { report: true } : {}), ...(pinned ? { sources: pinned.length } : {}), ...(sc ? { scopeTitle: sc.title || '' } : {}), ...(ex ? { expandOf: ex.of || '' } : {}) };
  const answerId = uid();
  // 第一个 await 之前同步登记（两页不会各取一条并发）
  busy = true;
  const info = { page: pageId, id: answerId, userTurnId: userTurn.id, convId: session.id, private: !!session.private, q, askedAt, phase: '', text: '', startedAt: Date.now() };
  p.chatInFlight = { ...info };
  let turn = null, shown = '';
  try {
    if (newThread) {
      // 这段先进历史（写不进就不清，照旧接在这段后面问），再换一段新对话
      try { const prev = sessionSnapshot(); await enqueueWrite(() => saveToHistory(prev)); beginFresh(); info.convId = session.id; p.chatInFlight.convId = session.id; }
      catch (e) { notice('这段没能存进历史，新问题先接在这段后面：' + errText(e)); }
    }
    session.turns.push(userTurn);
    if (ex) markExpanded(ex, userTurn.id);
    stick = true; userAt = 0; back = null; unseen = false;
    paintSend();
    await keepSession();
    await drawChat({ restore: 'bottom' }); follow();
    // 展开只带被展开那一答（问题 + 回答）当上下文：省 token，也不会被当成新话题
    const exTurn = ex ? session.turns.find(x => x.id === ex.of) : null;
    const history = ex ? (exTurn ? [{ role: 'user', content: exTurn.q || ex.q || '' }, { role: 'assistant', content: exTurn.content }] : [])
      : session.turns.filter(t => t.role === 'user' || t.role === 'assistant').filter(t => !t.failed)
        .map(t => ({ role: t.role === 'assistant' ? 'assistant' : 'user', content: t.content })).slice(0, -1);
    // 会话级约束显式传给后端：没排除 / 没保留时请求和以前一模一样
    const constraints = { ...(session.excluded.length ? { excludeIds: [...session.excluded] } : {}), ...(session.pinned.length ? { pinIds: [...session.pinned] } : {}) };
    // 1018 v2.1 §5：接着这段问时带上一答的 turn_id / 会话线 id（后端按它继承来源、解析「第 N 篇」）；新话题 / 展开不带
    const prevAnswer = (ex || fresh || newThread) ? null : [...session.turns].reverse().find(t => t.role === 'assistant' && !t.failed && typeof t.turnId === 'string' && t.turnId && t.id !== answerId);
    const link = prevAnswer ? { parentTurnId: prevAnswer.turnId, ...(prevAnswer.threadId ? { threadId: prevAnswer.threadId } : {}) } : {};
    const r = await p.answerArchive({ question: backendQ, model: modelPick.hidden ? '' : modelPick.value, history, ...(pinned ? { sourceIds: pinned } : {}), ...constraints, ...link, tag: 'chat',
      ...(ex ? { turnId: ex.turnId, expandIds: [...ex.ids] } : {}),
      onPhase: showPhase,
      onDelta: delta => {
        shown += delta;
        const f = inflight(); if (f && f.id === answerId) { f.text = (f.text || '') + delta; try { app.workspace.trigger?.('link-brain:chat-live', pageId); } catch {} }
        if (!wrap.isConnected || lane !== 'chat') return;   // 已脱离页面的旧闭包只把字记在插件上
        if (f && f.text) { ensureLive(f); scheduleLive(); }
        if (stick) follow(); else markUnseen();
      } });
    if (r.status === 'cancelled') {
      // 停止：留下已经生成的那半截，明确标「已停止」；算失败轮次（不进追问上下文、不给收藏 / 导出）
      const part = (r.markdown || shown || '').trim();
      turn = { id: answerId, role: 'assistant', failed: true, stopped: true, content: (part ? part + '\n\n' : '') + '> 已停止生成。', sources: r.sources || [], related: r.related || [], q, askedAt, retry, mode };
    } else turn = { id: answerId, role: 'assistant', content: r.markdown || '没有可用的回答。', sources: r.sources || [], related: r.related || [], q, askedAt, ...answerShape(r), ...(ex ? { expandOf: ex.of || '' } : {}) };
  } catch (e) {
    const payload = e && e.payload || {};
    const sources = payload.sources || [], related = payload.related || [];
    const kind = e?.kind || 'api';
    const content = kind === 'config' && sources.length + related.length ? `问答还没配 AI，先列出找到的相关收藏（${sources.length + related.length} 篇）` : failText(e);
    turn = { id: answerId, role: 'assistant', failed: true, error: { kind, code: String(e?.code || ''), detail: String(e?.detail || '') }, content, q, askedAt, retry, mode, sources, related };
  } finally {
    busy = false;
    const f = inflight(); if (f && f.page === pageId && f.id === answerId) delete p.chatInFlight;
    if (turn) await commitAnswer(info, turn);
    paintSend();
    announce();
    if (wrap.isConnected) { if (!stick) markUnseen(); await drawChat(); drainQueue(); }
  }
}
// 1015 每问开新对话：这段已进历史，换成一段空对话（不画，submit 接着画）
function beginFresh() {
  Object.assign(session, { id: uid(), startedAt: new Date().toISOString(), turns: [], excluded: [], pinned: [], follow: prefs.follow, followPicked: false });
  lastTop = 0; stick = true; back = null; unseen = false; struck.clear(); picks.clear(); openState.clear();
  LB.state.patch({ scrollTop: 0 });
  resetViews();
}
// ── 1015 先目录后展开：响应里的 mode / toc / turn_id / source_ids（ask 车约定）。缺字段 = 老后端，照原样渲染 ──
const tocStr = v => (v == null ? '' : String(v)).replace(/\s+/g, ' ').trim();
function normToc(raw) {
  const list = Array.isArray(raw) ? raw
    : raw && Array.isArray(raw.groups) ? raw.groups.flatMap(g => (Array.isArray(g?.items) ? g.items : []).map(it => (it && typeof it === 'object' ? { ...it, group: it.group || g.name } : it)))
      : raw && Array.isArray(raw.items) ? raw.items : [];
  return list.filter(x => x && typeof x === 'object').slice(0, 80).map((it, i) => ({
    n: Number(it.n) || i + 1,
    id: tocStr(it.id || it.src || it.source_id),
    title: tocStr(it.title || it.name) || '（无标题）',
    author: tocStr(it.author || it.nickname),
    hit: tocStr(it.hit || it.hit_point || it.hits || it.point || it.line || it.why),
    kind: Array.isArray(it.source_type || it.kind) ? (it.source_type || it.kind).map(tocStr).join('、') : tocStr(it.source_type || it.kind || it.type || it.field),
    group: tocStr(it.group),
    note: tocStr(it.note), url: tocStr(it.url),
    price: tocStr(it.price ?? it.extra?.price), where: tocStr(it.where ?? it.extra?.where),
  }));
}
function answerShape(r) {
  const out = {};
  if (!r || typeof r !== 'object') return out;
  if (typeof r.turn_id === 'string' && r.turn_id) out.turnId = r.turn_id;
  if (typeof r.thread_id === 'string' && r.thread_id) out.threadId = r.thread_id;   // 1018 会话线：下一问带回去
  if (Array.isArray(r.source_ids)) out.sourceIds = idList(r.source_ids);
  if (r.layout === 'board') out.layout = 'board';   // 1020 陈列版（技能 layout: board）
  const toc = normToc(r.toc), m = r.mode === 'toc' || r.mode === 'direct' ? r.mode : '';
  if (toc.length && m !== 'direct') {
    out.answerMode = 'toc'; out.toc = toc;
    const cov = tocStr(r.coverage_note || r.toc?.coverage_note), sug = tocStr(r.suggest || r.toc?.suggest);
    if (cov) out.tocNote = cov;
    if (sug) out.tocSuggest = sug;
  } else if (m) out.answerMode = 'direct';
  return out;
}
const KIND_LABEL = { body: '正文', post: '正文', title: '标题', tags: '标签', comments: '评论', comment: '评论', ocr: '图片文字', image: '图片', images: '图片', vision: '图片', video: '视频', transcript: '视频文字稿', frames: '视频画面文字', attachments: '附件', attachment: '附件', file: '附件', notes: '批注', annotation: '批注', annotations: '批注', highlights: '高亮', highlight: '高亮', saved: '我保存的', author: '作者' };
const kindLabels = k => [...new Set(String(k || '').split(/[,，、|/\s]+/).filter(Boolean).map(x => KIND_LABEL[x.toLowerCase()] || x))];
// 展开过的条目：记在被展开那一答上（id → 展开那一问的轮次 id），按钮变「已展开 ↓」点了跳过去
function markExpanded(ex, userTurnId) {
  const t = session.turns.find(x => x.id === ex.of); if (!t) return;
  const map = t.expanded && typeof t.expanded === 'object' ? { ...t.expanded } : {};
  for (const id of ex.ids) map[id] = userTurnId;
  t.expanded = map;
}
// 「展开」一律经它：带上那一答的 turn_id（后端给的，没有就用本地轮次 id）+ 来源 id
function expandTurn(t, ids, label) {
  const list = idList(ids);
  if (!list.length || !t) return;
  submit(`展开：${label}`, { expand: { turnId: t.turnId || t.id, of: t.id, ids: list, q: t.q || '', label } });
}
// 写回合并（A2，修「回答丢了」）：在写链里先读磁盘上的会话，把回答插在自己那条问题后面（找不到就追加），磁盘版并回内存再写。
// 这段对话已经被换掉了（正常被 isBusy 挡住，这里只是兜底）：写进它的历史文件（隐私模式的不写）
function commitAnswer(info, turn) {
  const insert = turns => { if (turns.some(x => x.id === turn.id)) return turns; const i = turns.findIndex(x => x.id === info.userTurnId); if (i < 0) turns.push(turn); else turns.splice(i + 1, 0, turn); return turns; };
  return enqueueWrite(async () => {
    let disk = null;
    try { disk = JSON.parse(await app.vault.adapter.read(SESSION_PATH)); } catch {}
    if (disk && Array.isArray(disk.turns) && disk.id === info.convId) {
      insert(ensureIds(disk.turns));
      if (session.id === info.convId) {
        session.turns = adoptTurns(session.turns, disk.turns); session.excluded = idList(disk.excluded); session.pinned = idList(disk.pinned);
        session.follow = followOf(disk); session.followPicked = !!disk.followPicked; session.private = !!disk.private;
        await saveSession();
      } else { await writeJson(SESSION_PATH, disk); if (!disk.private) await saveToHistory({ ...disk, startedAt: disk.startedAt || info.askedAt }); }
      return;
    }
    if (!disk || !Array.isArray(disk.turns)) { if (session.id === info.convId) { insert(session.turns); await saveSession(); } return; }
    if (info.private) return;
    let conv = null;
    try { conv = JSON.parse(await app.vault.adapter.read(historyFile(info.convId))); } catch {}
    if (!conv || !Array.isArray(conv.turns)) return;
    insert(ensureIds(conv.turns));
    await saveToHistory({ ...conv, id: info.convId, private: false });
  }).then(() => announce()).catch(e => { notice('对话没写进文件，重开这一页会丢：' + errText(e)); });
}
// A5：失败的人话，只有一层前缀，不说两遍「请重试」
function failText(e) {
  const kind = e?.kind, code = String(e?.code || ''), detail = String(e?.detail || '').trim();
  if (kind === 'config') return '问答还没配 AI（归档、浏览、搜索不受影响）';
  if (code === 'NEEDS_HUMAN.AUTH_FAILED') return 'AI 接口拒绝了这把 key：' + (detail || '没说原因');
  if (/QUOTA_EXCEEDED/.test(code)) return 'AI 接口提示欠费或额度用完';
  if (/HTTP_429/.test(code)) return '接口限流了，过一会儿再试';
  if (/HTTP_5\d\d|HTTP_5XX|NETWORK|STEP_TIMEOUT|SERVICE_BUSY/.test(code) || kind === 'timeout') return '网络或接口暂时没响应';
  if (kind === 'crash') return errText(e);
  const why = (detail || errText(e)).replace(/^(AI )?回答失败[：:]\s*/, '').replace(/[，,。\s]*请重试。?$/, '').trim();
  return '没答上：' + (why || '未知原因');
}
// 「重试」：失败轮是最后一轮时先把这一对（失败回答和它的问题）从会话里拿掉再问；不是最后一轮就留着记录直接问
function retryTurn(t) {
  if (isBusy()) { notice(BUSY_TEXT, 3000); return; }
  const i = session.turns.indexOf(t);
  if (i === session.turns.length - 1) {
    const prev = session.turns[i - 1];
    session.turns.splice(prev && prev.role === 'user' ? i - 1 : i, prev && prev.role === 'user' ? 2 : 1);
  }
  return submit(t.q, { ...(t.retry || {}), keep: true });   // 重试是同一问：不因「每问开新对话」清掉这段
}
// 「改一下再问」：原问题放回输入框，光标在末尾
function rephrase(t) {
  search.value = t.q || ''; autosize(); saveDraft(search.value);
  try { search.focus({ preventScroll: true }); search.setSelectionRange(search.value.length, search.value.length); } catch {}
}
// 排队的接着问（A2）：本页不在文档里 / 事件触发时本页看不见 / 还有人在答 → 不取
function drainQueue(fromEvent = false) {
  if (!wrap.isConnected) return;
  if (fromEvent && typeof root.isShown === 'function' && !root.isShown()) return;
  if (isBusy()) return;
  const list = chatQueue(); if (!list.length) return;
  const next = list.shift(); queueChanged();
  submit(next.q, next.opts || {});
}

// ── 栏切换 ──（顶头标题 + 输入框始终不动；只切换下面的正文）
async function setLane(next) {
  const was = lane;
  lane = next;
  tabChat.classList.toggle('is-on', lane === 'chat');
  tabArch.classList.toggle('is-on', lane === 'archive');
  composer.hidden = readOnly || lane !== 'chat';   // 存档栏用它自己的输入框，顶部搜索只服务对话栏
  closeTocPanel();
  // A12：从别的栏切回对话 → 回到切走前读的那一轮（lastTop），在底部跟随的回到底部
  if (lane === 'chat') await drawChat(was !== 'chat' ? { restore: stick ? 'bottom' : lastTop } : {}); else await drawArchive();
}
tabChat.onclick = () => setLane('chat');
tabArch.onclick = () => setLane('archive');

// ── F5 问收藏目录 ──
const TOC_MIN_QUESTIONS = 2;
let tocWide = false, tocCollapsed = pageState.toc === 'collapsed', tocPanel = null;
function tocGroups() {
  const groups = [];
  for (const t of session.turns) {
    if (t.role === 'user') groups.push({ q: t, a: null });
    else if (t.role === 'assistant' && groups.length && !groups[groups.length - 1].a) groups[groups.length - 1].a = t;
  }
  return groups;
}
function fillToc(box, onPick) {
  box.empty();
  const groups = tocGroups(), f = inflight();
  groups.forEach((g, i) => {
    const grp = box.createEl('div', { cls: 'lbchat-tocgrp' }); grp.dataset.key = g.q.id;
    const qb = grp.createEl('button', { cls: 'lbchat-toc-q', attr: { title: g.q.content } }); qb.type = 'button';
    if (g.q.mode === 'scope') qb.createEl('span', { cls: 'lbchat-toc-tag', text: '篇' });
    qb.appendText(`${g.q.mode === 'follow' ? '↳ ' : ''}${i + 1} ${g.q.content}`);
    qb.onclick = () => { const el = views.get(g.q.id)?.el; if (el) jumpTo(el, { flash: true }); onPick?.(); };
    const live = f && f.userTurnId === g.q.id;
    if (g.a || live) {
      const row = grp.createEl('div', { cls: 'lbchat-toc-row lbchat-toc-arow' });
      const ab = row.createEl('button', { cls: 'lbchat-toc-a' }); ab.type = 'button';
      if (live && !g.a) { ab.setText('回答中…'); row.createEl('span', { cls: 'lbchat-dot' }); ab.onclick = () => { const el = liveView?.el || bodyEl.querySelector('.lbchat-think'); if (el) jumpTo(el); onPick?.(); }; }
      else {
        ab.setText(g.a.failed ? (g.a.stopped ? '已停止' : '没答上') : '回答');
        const ael = views.get(g.a.id)?.el;
        ab.onclick = () => { if (ael) jumpTo(ael, { flash: true }); onPick?.(); };
        // 目录型回答：条目（前 8 条）也进左栏，点了跳到目录卡那一行
        if (ael && !g.a.failed && g.a.answerMode === 'toc') for (const it of (g.a.toc || []).slice(0, 8)) {
          const hb = row.createEl('button', { cls: 'lbchat-toc-h lbchat-toc-item', text: `${it.n} ${it.title}`.slice(0, 14), attr: { title: it.title } }); hb.type = 'button';
          hb.onclick = () => { const li = [...ael.querySelectorAll('.lbchat-tocard-item')].find(x => x.dataset.id === it.id); jumpTo(li || ael, { flash: true }); onPick?.(); };
        }
        // 1020 报告版：分类 → 条目两级进目录（她：分类导航做成浮动板），点了跳到那一类 / 那一条
        if (ael && !g.a.failed && ael.querySelector('.lbboard')) {
          const bx = grp.createEl('div', { cls: 'lbchat-toc-board' });   // 单独一块竖排（回答那一行是横排的）
          const top = ael.querySelector('.lbboard-topsec');
          if (top) { const hb = bx.createEl('button', { cls: 'lbchat-toc-h lbchat-toc-cat', text: '先看这几个' }); hb.type = 'button'; hb.onclick = () => { jumpTo(top, { flash: true }); onPick?.(); }; }
          for (const sec of ael.querySelectorAll('.lbboard-sec')) {
            const name = sec.querySelector('.lbboard-cat')?.firstChild?.textContent || '';
            const hb = bx.createEl('button', { cls: 'lbchat-toc-h lbchat-toc-cat', text: name.slice(0, 14), attr: { title: name } }); hb.type = 'button';
            hb.onclick = () => { jumpTo(sec, { flash: true }); onPick?.(); };
            for (const nm of [...sec.querySelectorAll('.lbboard-row .lbboard-name')].slice(0, 30)) {
              const n = nm.textContent || '', r = nm.closest('.lbboard-row');
              const ib = bx.createEl('button', { cls: 'lbchat-toc-h lbchat-toc-sub', text: n.slice(0, 14), attr: { title: n } }); ib.type = 'button';
              ib.onclick = () => { jumpTo(r, { flash: true }); onPick?.(); };
            }
          }
        }
        if (ael && !g.a.failed) for (const h of [...ael.querySelectorAll('.lbchat-md h1, .lbchat-md h2, .lbchat-md h3')].slice(0, 6)) {
          const hb = row.createEl('button', { cls: 'lbchat-toc-h', text: String(h.textContent || '').trim().slice(0, 12), attr: { title: h.textContent || '' } }); hb.type = 'button';
          hb.onclick = () => { jumpTo(h, { flash: true }); onPick?.(); };
        }
      }
    }
    if (g.a && ((g.a.sources || []).length || (g.a.related || []).length)) {
      const removed = new Set(g.a.removed || []);
      const kp = (g.a.sources || []).filter(s => !removed.has(srcKey(s))).length, kr = (g.a.related || []).filter(s => !removed.has(srcKey(s))).length;
      const row = grp.createEl('div', { cls: 'lbchat-toc-row' });
      const sb = row.createEl('button', { cls: 'lbchat-toc-s', text: `来源 ${kp} · 相关 ${kr}` }); sb.type = 'button';
      sb.onclick = () => {
        const ael = views.get(g.a.id)?.el; if (!ael) return;
        const d = ael.querySelector('details[data-part="primary"]') || ael.querySelector('details[data-part="related"]');
        if (d) { d.open = true; openState.add(`${g.a.id}:${d.dataset.part}`); jumpTo(d.querySelector('summary') || d, { flash: true }); }
        onPick?.();
      };
    }
  });
}
// 1015「TOC 又不见了」：根因是 ≥2 问才出、宽窗要 ≥1242。现在 1 问时只要回答有目录卡 / ≥2 个小标题也出；1080 起就有左栏；窄窗 / 收起后页头「目录」按钮弹出层（里面「固定在左边」放回左栏）
function tocWorth() {
  const asks = session.turns.filter(t => t.role === 'user').length;
  if (asks >= TOC_MIN_QUESTIONS) return true;
  return session.turns.some(t => t.role === 'assistant' && !t.failed && ((t.answerMode === 'toc' && (t.toc || []).length) || (views.get(t.id)?.el?.querySelectorAll('.lbchat-md h1, .lbchat-md h2, .lbchat-md h3, .lbboard-sec').length || 0) >= 2));
}
function paintToc() {
  const n = session.turns.filter(t => t.role === 'user').length;
  const show = lane === 'chat' && n > 0 && tocWorth();
  const side = show && tocWide && !tocCollapsed;
  tocEl.hidden = !side;
  tocBtn.hidden = !(show && !side);
  tocFab.hidden = tocBtn.hidden;
  tocBtn.setText(n >= 2 ? `目录 · ${n} 问` : '目录');
  if (!show) closeTocPanel();
  if (side) {
    tocEl.empty();
    const headRow = tocEl.createEl('div', { cls: 'lbchat-tochead' });
    headRow.createEl('span', { text: '目录' });
    const fold = headRow.createEl('button', { cls: 'lbchat-toc-fold', text: '‹', attr: { title: '收起目录（之后在右上角「目录」里打开）', 'aria-label': '收起目录' } }); fold.type = 'button';
    fold.onclick = () => { tocCollapsed = true; LB.state.patch({ toc: 'collapsed' }); paintToc(); };
    const list = tocEl.createEl('div', { cls: 'lbchat-toclist' });
    fillToc(list);
    markHere();
  }
  if (tocPanel) { const list = tocPanel.querySelector('.lbchat-toclist'); if (list) fillToc(list, closeTocPanel); }
}
// A4 每次流式渲染只更新「回答中」那一条（不整个重排）
function paintTocLive() { if (!tocEl.hidden || tocPanel) paintToc(); }
function toggleTocPanel(anchor = tocBtn) {
  if (tocPanel) { closeTocPanel(); return; }
  const doc = wrap.ownerDocument || document;
  tocPanel = doc.body.createEl('div', { cls: 'lbchat-tocpanel' });
  const headRow = tocPanel.createEl('div', { cls: 'lbchat-tochead' }); headRow.createEl('span', { text: '目录' });
  if (tocWide && tocCollapsed) { const unfold = headRow.createEl('button', { cls: 'lbchat-toc-fold', text: '固定在左边', attr: { title: '宽窗时把目录放回对话左边' } }); unfold.type = 'button'; unfold.onclick = () => { tocCollapsed = false; LB.state.patch({ toc: 'open' }); closeTocPanel(); paintToc(); }; }
  fillToc(tocPanel.createEl('div', { cls: 'lbchat-toclist' }), closeTocPanel);
  try {
    const r = anchor.getBoundingClientRect();
    if (anchor === tocFab) { tocPanel.addClass('is-side'); tocPanel.style.top = Math.max(8, r.top) + 'px'; tocPanel.style.left = (r.right + 6) + 'px'; }   // 浮签旁边展开
    else { tocPanel.style.top = (r.bottom + 6) + 'px'; tocPanel.style.left = Math.max(8, Math.min(r.right - 300, (window.innerWidth || 1200) - 308)) + 'px'; }
  } catch {}
  const outside = ev => { if (!tocPanel || tocPanel.contains(ev.target) || [tocBtn, tocFab].some(b => ev.target === b || b.contains(ev.target))) return; closeTocPanel(); };
  tocPanel._lbOutside = outside;
  setTimeout(() => { if (tocPanel && tocPanel._lbOutside === outside) doc.addEventListener('click', outside); }, 0);
}
function closeTocPanel() {
  if (!tocPanel) return;
  const doc = wrap.ownerDocument || document;
  try { doc.removeEventListener('click', tocPanel._lbOutside); } catch {}
  tocPanel.remove(); tocPanel = null;
}
LB.onUnload(() => closeTocPanel());
// 宽窗（bodywrap ≥ 850 + 2×196）才有左栏
try {
  const tro = new ResizeObserver(entries => {
    const w = bodyWrap.clientWidth || entries?.[0]?.contentRect?.width || 0;
    // ≥1242：左栏放在 850 对话列左边的空白里；1080–1242：对话列往右让出左栏的宽度（is-tight），不重叠
    const wide = w >= 1080, tight = wide && w < 1242;
    bodyWrap.classList.toggle('is-tight', tight);
    if (wide !== tocWide) { tocWide = wide; bodyWrap.classList.toggle('is-wide', wide); paintToc(); }
  });
  tro.observe(bodyWrap); LB.onUnload(() => tro.disconnect());
} catch {}
// 当前位置：视口顶边以上最后一个问题那一组 is-here；左栏只改自己的 scrollTop（不用 scrollIntoView，免得带着外层一起滚）
let hereQueued = false;
function markHere() {
  if (tocEl.hidden) return;
  const top = bodyEl.getBoundingClientRect().top;
  let key = null;
  for (const el of bodyEl.querySelectorAll('.lbchat-user')) { if (el.getBoundingClientRect().top - top <= 24) key = el.dataset.key; else break; }
  if (!key) key = bodyEl.querySelector('.lbchat-user')?.dataset.key || null;
  let here = null;
  for (const g of tocEl.querySelectorAll('.lbchat-tocgrp')) { const on = g.dataset.key === key; g.classList.toggle('is-here', on); if (on) here = g; }
  if (here) {
    const rt = tocEl.getBoundingClientRect(), gt = here.getBoundingClientRect();
    if (gt.top < rt.top) tocEl.scrollTop -= rt.top - gt.top + 8;
    else if (gt.bottom > rt.bottom) tocEl.scrollTop += gt.bottom - rt.bottom + 8;
  }
}
// 跳转：瞬时（不用 smooth，免得和「DOM 挪动后归零就滚回」的守卫打架）；记下跳前的位置给「↩ 回到刚才」
function jumpTo(el, { open = false, flash = false } = {}) {
  if (!el || !bodyEl.contains(el)) return;
  if (!back) back = { top: bodyEl.scrollTop, stick };
  if (open) { const d = el.closest('details'); if (d) d.open = true; }
  const top = Math.max(0, bodyEl.scrollTop + el.getBoundingClientRect().top - bodyEl.getBoundingClientRect().top - 12);
  stick = false; lastTop = top; userAt = Date.now();
  bodyEl.scrollTop = top; LB.state.patch({ scrollTop: top });
  if (flash) { el.classList.remove('lbchat-flash'); el.classList.add('lbchat-flash'); setTimeout(() => el.classList.remove('lbchat-flash'), 1300); }
  paintFloaters(); markHere();
}

// ── 第一次画 ──
await setLane('chat');
paintSend();
// 旧会话（10-04 前没有历史这回事）：有轮次又不在历史里 → 现在存一次，旧数据不丢（只读时 writeJson 不写）
if (!readOnly && session.turns.length && !session.private && !hist.conversations.some(c => c.id === session.id)) await keepSession();
LB.t('render');
// 对话区滚动位置（§5.3）：记下来，换页回来恢复；没记过 = 停在最新一轮（底部）
if (Number.isFinite(pageState.scrollTop)) { bodyEl.scrollTop = pageState.scrollTop; stick = nearBottom(); }
else { stick = true; follow(); }
bodyEl.addEventListener?.('scroll', () => {
  if (lane !== 'chat' || drawing || !bodyEl.isConnected) return;
  if (reset()) { keepPlace(); return; }   // 被挪过 DOM 的归零：不记、滚回去
  lastTop = bodyEl.scrollTop; stick = nearBottom(); LB.state.patch({ scrollTop: lastTop });
  if (stick) unseen = false;
  if (back && Math.abs(bodyEl.scrollTop - back.top) < 48 && Date.now() - userAt > 50) back = null;   // 自己滚回原处了
  paintFloaters();
  if (!hereQueued) { hereQueued = true; requestAnimationFrame(() => { hereQueued = false; markHere(); }); }
}, { passive: true });
// 页头 / 输入框上滚滚轮也滚对话区（整页是定高的，那一块本身没有可滚的东西）；对话区里面、能滚的输入框里面交给浏览器
const canScroll = (el, dy) => {
  for (let n = el; n && n !== wrap; n = n.parentElement) {
    const room = n.scrollHeight - n.clientHeight;
    if (room > 1 && (n.tagName === 'TEXTAREA' || /(auto|scroll)/.test(getComputedStyle(n).overflowY || '')) && (dy > 0 ? n.scrollTop < room - 1 : n.scrollTop > 0)) return true;
  }
  return false;
};
wrap.addEventListener?.('wheel', e => {
  if (e.ctrlKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
  const t = e.target;
  if (!t || typeof t.closest !== 'function' || bodyEl.contains(t) || t.closest('select') || t.closest('.lbchat-toc') || canScroll(t, e.deltaY)) return;
  userAt = Date.now();
  bodyEl.scrollTop += e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? bodyEl.clientHeight : 1);
  if (lane === 'chat') { lastTop = bodyEl.scrollTop; stick = nearBottom(); paintFloaters(); }
  e.preventDefault();
}, { passive: false });
// A14：回答里的图点了用插件的大图查看器（和笔记页同一个：←/→、滚轮、缩放），底下写「来源N · 图M」。
// 用委托：Obsidian 的图片嵌入可能在渲染完之后才异步生成 img。插件没有这个接口（openLightbox 返回 null / 手机上）就不拦截，保持原样
bodyEl.addEventListener?.('click', e => {
  const img = e.target;
  if (!img || img.tagName !== 'IMG' || typeof img.closest !== 'function' || !img.closest('.lbchat-md') || img.closest('.lbchat-editor') || img.closest('.lbchat-live')) return;
  const p = provider(); if (typeof p?.openLightbox !== 'function') return;
  const answer = img.closest('.lbchat-answer');
  const t = session.turns.find(x => x.id === answer?.dataset.key);
  const imgs = [...(answer || img.closest('.lbchat-md')).querySelectorAll('.lbchat-md img')];
  const i = Math.max(0, imgs.indexOf(img));
  const meta = imgs.map(x => imageSource(x, t?.sources || []));
  let r;
  try { r = p.openLightbox(imgs, i, { caption: k => meta[k]?.label || '', onCaption: k => { if (meta[k]?.src) openNote(meta[k].src); } }); } catch { return; }
  if (r === null) return;
  e.preventDefault?.(); e.stopPropagation?.();
});
// 图片属于哪个来源：图片地址（解码、统一成正斜杠）里含这个来源的对象目录（agent_md 的上上级）；序号取 image-(\d+)
function imageSource(img, sources) {
  let s = String(img.currentSrc || img.getAttribute?.('src') || img.src || '');
  try { s = decodeURIComponent(s); } catch {}
  s = s.replace(/\\/g, '/').replace(/\?.*$/, '');
  for (const src of sources) {
    if (!src.agent_md) continue;
    const obj = String(src.agent_md).replace(/\\/g, '/').split('/').slice(0, -2);
    const tail = obj.slice(-2).join('/');
    if (!tail || !(s.includes('/' + tail + '/') || s.startsWith(tail + '/'))) continue;
    const m = s.match(/image-(\d+)\./);
    return { src, label: m ? `来源${src.citation} · 图${Number(m[1])}` : `来源${src.citation}` };
  }
  return null;
}
LB.t('restore');
paintSourceBar();
if (app.workspace.on && dv.component?.registerEvent) {
  // 用户自己关了右侧窗格：那一行跟着收起
  lbEvent(app.workspace.on('layout-change', () => { paintSourceBar(); settle(); }));
  // 别的问收藏页写了会话（答完 / 改了来源 / 清空）：重读再画（强制全量重建），然后看排队
  lbEvent(app.workspace.on('link-brain:chat-session', from => {
    paintSend();
    if (from === pageId || busy) return;
    app.vault.adapter.read(SESSION_PATH).then(async raw => {
      const next = JSON.parse(raw);
      if (!Array.isArray(next.turns)) return;
      session.turns = adoptTurns(session.id === next.id ? session.turns : [], next.turns); session.excluded = idList(next.excluded); session.pinned = idList(next.pinned);
      session.follow = followOf(next); session.followPicked = !!next.followPicked;
      if (typeof next.id === 'string' && next.id) { session.id = next.id; session.startedAt = next.startedAt || session.startedAt; }
      session.private = !!next.private; paintPrivacy();
      if (!bodyEl.querySelector('.lbchat-editor')) resetViews();
      if (lane === 'chat') await drawChat();
      drainQueue(true);
    }).catch(() => {});
    app.vault.adapter.read(HISTORY_INDEX).then(raw => { hist = histOf(JSON.parse(raw)) || hist; }).catch(() => {});
  }));
  // 别的问收藏页正在出字 / 换阶段（A2）：接着画半截
  lbEvent(app.workspace.on('link-brain:chat-live', from => {
    if (from === pageId || lane !== 'chat') return;
    const f = inflight(); if (!f) return;
    paintSend();
    if (f.text) { bodyEl.querySelector('.lbchat-think')?.remove(); ensureLive(f); scheduleLive(); }
    else if (!bodyEl.querySelector('.lbchat-think')) drawChat();
    paintPhase();
    if (stick) follow(); else markUnseen();
  }));
  lbEvent(app.workspace.on('link-brain:chat-queue', from => { if (from !== pageId) drawQueue(); }));
  // A17：设置改了（模型增删改名、输入框提示文字）——rAF 合并后重填下拉、提示、配置提示
  let settingsQueued = false;
  lbEvent(app.workspace.on('link-brain:settings', () => {
    if (settingsQueued) return; settingsQueued = true;
    requestAnimationFrame(() => { settingsQueued = false; fillModels(); paintFollow(); paintCfgHint(); });
  }));
}
// 登记这一版 DOM（连 host 一起，§5.9）：catalog-data 变了只换数据、改篇数，不重建对话
LB.keep(wrap, { park: true, version: await LB.data.version(), update: async () => {
  try { data = await LB.data.load(); items = data.items || []; paintSub(); } catch {}
}, onReuse: () => { paintSourceBar(); paintSend(); fillModels(); settle(); } });
LB.t('total');

// mermaid 是异步画出来的 svg：对话区 DOM 一变（rAF 合并）补一遍
try {
  let mmdQueued = false;
  const mmo = new MutationObserver(() => { if (mmdQueued) return; mmdQueued = true; requestAnimationFrame(() => { mmdQueued = false; enhanceMermaid(bodyEl); }); });
  mmo.observe(bodyEl, { childList: true, subtree: true });
  LB.onUnload(() => mmo.disconnect());
} catch {}
// ── A16 键盘与焦点 ──
// 进页 / 清空 / 恢复后光标在输入框（只在本页是活动标签页时，不抢别处的焦点）；整页重建 3 秒内把焦点和选区还回去
function focusSearch() {
  if (readOnly || composer.hidden) return;
  try { if (!wrap.closest('.workspace-leaf.mod-active')) return; search.focus({ preventScroll: true }); } catch {}
}
requestAnimationFrame(() => { if (!LB.restoreFocus(search, 'search')) focusSearch(); });
// Esc：先关面板（历史 / 目录），再取消编辑，再停止生成；组字中、别的标签页、开着模态框 / 大图时不管
LB.listen('esc', document, 'keydown', e => {
  if (e.key !== 'Escape' || e.isComposing || composing) return;
  if (!wrap.isConnected || !(wrap.closest('.workspace-leaf.mod-active') || LB.activeLeafHas(wrap))) return;
  const doc = wrap.ownerDocument || document;
  if (doc.querySelector('.modal-container') || doc.querySelector('.lb-lightbox') || LB.menuOpen()) return;
  let done = false;
  const fullMmd = bodyEl.querySelector('.lbchat-mmd.is-full');
  if (fullMmd && fullMmd._lbExitFull?.()) done = true;
  else if (histBtn._open) { toggleHistory(histBtn); done = true; }
  else if (tocPanel) { closeTocPanel(); done = true; }
  else { const ed = bodyEl.querySelector('.lbchat-editor'); if (ed) { ed._lbCancel?.(); done = true; } else if (isBusy()) { done = stopAnswer() || true; } }
  if (done) { e.preventDefault?.(); e.stopPropagation?.(); }
}, true);

// 目录页「去问收藏搜「…」」带词跳过来（R1）/ 笔记的「问这篇」（N11）：第一次画完、旧页面挂回时（onReuse）、ask-pending 事件三处都接。
// 取走即删；问这篇只预设来源、光标进输入框，不自动提交；带词的照常自动问（正在回答就排进队列）
function takePending(fromEvent) {
  const p = provider(); if (!p) return;
  if (root.isConnected === false) return;
  if (fromEvent && typeof root.isShown === 'function' && !root.isShown()) return;
  const sc = p.pendingArchiveScope;
  if (sc && typeof sc === 'object') {
    delete p.pendingArchiveScope;
    if (Array.isArray(sc.ids) && sc.ids.length && !(Date.now() - (Number(sc.at) || 0) > 5 * 60 * 1000)) {
      scope = { ids: sc.ids.filter(x => typeof x === 'string'), title: String(sc.title || ''), note: sc.note || '' };
      LB.state.patch({ scope });
      const go = () => { paintFollow(); try { search.focus({ preventScroll: true }); } catch {} };
      if (lane !== 'chat') setLane('chat').then(go); else go();
    }
  }
  const q = p.pendingArchiveQuestion; if (!q || typeof q !== 'string') return;
  delete p.pendingArchiveQuestion;
  if (lane !== 'chat') setLane('chat');
  if (isBusy()) { enqueue(q, { fresh: true }); return; }
  submit(q);
}
LB.container && LB.container.__lbView && (LB.container.__lbView.onReuse = (prev => () => { try { prev && prev(); } finally { takePending(); } })(LB.container.__lbView.onReuse));
if (app.workspace.on && dv.component?.registerEvent) lbEvent(app.workspace.on('link-brain:ask-pending', () => takePending(true)));
takePending();
drainQueue();

function sourceText(src) {
  const absolute = src.markdown_path || (src.note && app.vault.adapter.getBasePath ? app.vault.adapter.getBasePath().replace(/[\\/]$/, '') + '/' + lbPath(src.note) : src.agent_md || '');
  return `[来源${src.citation}] ${src.title}\n${src.url || ''}\n本地正文：${absolute}`;
}
// 1001 审计 C-2：回答和命中原文都是不可信文本，落成 md 前过插件的清洗（规则在 link_brain/mdsafe.py）
function safeMd(md) { const p = provider(); return p && typeof p.neutralizeMarkdown === 'function' ? p.neutralizeMarkdown(md) : md; }
// 证据身份（R2）：评论摘录带楼号，图片文字带图序号
function partWhere(p) {
  const label = { body: '作者正文', comments: '评论', ocr: '图片文字', attachments: '附件正文', transcript: '视频转写', notes: '我的批注', saved: '我保存的' }[p.field] || p.field || '';
  if (p.field === 'comments' && p.comment_labels?.length) return `${label} ${p.comment_labels.join('、')}`;
  if (p.field === 'ocr' && p.images?.length) return `${label}（识别结果） ${p.images.join('、')}`;
  return label;
}
function evidenceWhere(src) { return [...new Set((src.excerpts || []).map(partWhere).filter(Boolean))].join(' · '); }
function answerExportMd(t) {
  const L = [`# ${t.q || 'AI 整理'}`, '', `> 导出于 ${new Date().toLocaleString('zh-CN')} · 机读版（问收藏）`];
  if (t.q) L.push(`> 提问原话：${t.q}`);
  if (t.dropped?.length) L.push(`> 这一轮删掉的来源（没导出）：${t.dropped.map(s => s.title).join('、')}`);
  L.push('', '## 回答', '', t.content, '');
  if (t.sources && t.sources.length) {
    L.push('## 参考材料', '');
    for (const s of t.sources) {
      L.push(`### [来源${s.citation}] ${s.title}${s.cited === false ? '（送进了模型，回答没引用）' : ''}`);
      if (s.url) L.push(`- 链接：${s.url}`);
      if (s.markdown_path || s.agent_md) L.push(`- 本地机读：${s.markdown_path || s.agent_md}`);
      if (s.note) L.push(`- 本地正文：${s.note}`);
      if (s.excerpts?.length) { L.push('', '#### 命中原文'); for (const p of s.excerpts) L.push(`**${partWhere(p)}**`, '', `> ${String(p.text).replace(/\n/g, '\n> ')}`, ''); }
      L.push('');
    }
  }
  if (t.related && t.related.length) {
    L.push('## 可能相关（保留着、没送进模型）', '');
    for (const s of t.related) {
      L.push(`- ${s.title}${s.url ? ` · ${s.url}` : ''}${s.note ? ` · 本地正文：${s.note}` : ''}`);
      if (s.excerpt) L.push(`  > ${String(s.excerpt).replace(/\n/g, ' ')}`);
    }
    L.push('');
  }
  return safeMd(L.join('\n'));
}
// ── ⑤ 历史面板（右上角时钟）：按天分组，点一行恢复那段对话；悬停出选中圈，可多选删除；顶上是「隐私模式」开关 ──
const WEEK = '日一二三四五六';
const dayKey = ts => { const d = new Date(ts); if (isNaN(d)) return '更早'; const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} 周${WEEK[d.getDay()]}`; };
const hhmm = ts => { const d = new Date(ts); return isNaN(d) ? '' : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
function historyRows() {
  const rows = hist.conversations.map(c => ({ ...c }));
  if (session.turns.length && !session.private && !rows.some(c => c.id === session.id))
    rows.unshift({ id: session.id, startedAt: session.startedAt, title: firstQuestion(session.turns), turns: session.turns.filter(t => t.role === 'user').length });
  return rows.sort((a, b) => String(b.startedAt || '').localeCompare(String(a.startedAt || '')));
}
// 恢复一段历史；M1：隐私模式那段切走后找不回来——不再弹原生确认，改成 8 秒内可撤销
async function restoreConversation(id) {
  if (isBusy()) { notice(BUSY_TEXT, 3000); return false; }
  if (id === session.id) return false;
  let conv;
  try { conv = JSON.parse(await app.vault.adapter.read(historyFile(id))); }
  catch (e) { notice('这段对话没读出来：' + errText(e)); return false; }
  const prev = sessionSnapshot(), prevHist = hist;
  try { if (!prev.private) await enqueueWrite(() => saveToHistory(prev)); } catch (e) { notice('没切换：当前这段没能存进历史，内容还在：' + errText(e)); return false; }
  const ok = await startConversation(prev, prevHist, {
    id, startedAt: conv.startedAt || new Date().toISOString(), turns: Array.isArray(conv.turns) ? conv.turns : [],
    excluded: idList(conv.excluded), pinned: idList(conv.pinned), follow: followOf(conv), followPicked: !!conv.followPicked, private: false });
  if (ok && prev.private && prev.turns.length) LB.undoNotice('已切换（隐私模式那段不进历史）', () => startConversation(sessionSnapshot(), hist, { ...prev, private: true }), 8000);
  return ok;
}
async function deleteConversations(ids) {
  if (isBusy()) { notice(BUSY_TEXT, 3000); return false; }
  if (readOnly || !ids.length) return false;
  const prevHist = hist;
  try { await enqueueWrite(() => dropFromHistory(ids)); } catch (e) { hist = prevHist; notice('没删掉：' + errText(e)); return false; }
  if (ids.includes(session.id)) await startConversation();
  notice(`已删除 ${ids.length} 段对话`, 2500);
  return true;
}
function toggleHistory(anchor) {
  const doc = wrap.ownerDocument || document;
  doc.querySelectorAll('.lbchat-histpanel').forEach(p => p.remove());
  if (anchor._open) { anchor._open = false; return; }
  anchor._open = true;
  const panel = doc.body.createEl('div', { cls: 'lbchat-histpanel' });
  const win = doc.defaultView || window;
  const place = () => { try { const r = anchor.getBoundingClientRect(); panel.style.top = (r.bottom + 6) + 'px'; panel.style.left = Math.max(8, Math.min(r.right - 360, (win.innerWidth || window.innerWidth) - 368)) + 'px'; } catch {} };
  const close = () => { panel.remove(); anchor._open = false; doc.removeEventListener('click', outside); try { win.removeEventListener?.('resize', place); } catch {} };
  const picked = new Set();
  const draw = () => {
    panel.empty();
    const rows = historyRows();
    const headRow = panel.createEl('div', { cls: 'lbchat-histhead' });
    headRow.createEl('span', { cls: 'lbchat-histtitle', text: `历史 · ${rows.length} 段` });
    if (!readOnly) {
      const priv = headRow.createEl('label', { cls: 'lbchat-histpriv', attr: { title: '开着时这段对话不进历史（清空后就没了）' } });
      const box = priv.createEl('input', { attr: { type: 'checkbox' } }); box.checked = !!session.private;
      priv.appendText('隐私模式');
      box.onchange = async () => { if (isBusy()) { box.checked = !!session.private; notice(BUSY_TEXT, 3000); return; } await setPrivate(box.checked); draw(); };
    }
    if (picked.size && !readOnly) {
      const bar = panel.createEl('div', { cls: 'lbchat-histbar' });
      bar.createEl('span', { text: `已选 ${picked.size} 段` });
      const all = bar.createEl('button', { cls: 'lbchat-histbtn', text: picked.size === rows.length ? '全不选' : '全选' }); all.type = 'button';
      all.onclick = () => { if (picked.size === rows.length) picked.clear(); else rows.forEach(r => picked.add(r.id)); draw(); };
      const del = bar.createEl('button', { cls: 'lbchat-histbtn lbchat-histdel', text: '删除' }); del.type = 'button';
      del.onclick = async () => { if (await deleteConversations([...picked])) { picked.clear(); draw(); } };
      const cancel = bar.createEl('button', { cls: 'lbchat-histbtn', text: '取消' }); cancel.type = 'button'; cancel.onclick = () => { picked.clear(); draw(); };
    }
    if (!rows.length) { panel.createEl('div', { cls: 'lbchat-histempty', text: session.private ? '隐私模式开着：这段对话不进历史' : '还没有历史对话。问过的都会自动存在这里' }); return; }
    let day = '';
    for (const c of rows) {
      const k = dayKey(c.startedAt);
      if (k !== day) { day = k; panel.createEl('div', { cls: 'lbchat-histday', text: k }); }
      const row = panel.createEl('div', { cls: 'lbchat-histitem' + (c.id === session.id ? ' is-current' : '') + (picked.has(c.id) ? ' is-picked' : '') });
      row.dataset.id = c.id;
      if (!readOnly) {
        const pick = row.createEl('button', { cls: 'lbchat-src-check lbchat-histcheck' + (picked.has(c.id) ? ' is-on' : ''), attr: { role: 'checkbox', 'aria-checked': String(picked.has(c.id)), 'aria-label': '选中：' + (c.title || '') } });
        pick.type = 'button'; pick.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
        pick.onclick = e => { e?.stopPropagation?.(); picked.has(c.id) ? picked.delete(c.id) : picked.add(c.id); draw(); };
      }
      const q = row.createEl('button', { cls: 'lbchat-histq', text: c.title || '（没有提问）', attr: { title: c.title || '' } }); q.type = 'button';
      if (c.id === session.id) row.createEl('span', { cls: 'lbchat-histnow', text: '当前' });
      row.createEl('span', { cls: 'lbchat-histtime', text: hhmm(c.startedAt) });
      q.onclick = async () => {
        if (picked.size) { picked.has(c.id) ? picked.delete(c.id) : picked.add(c.id); draw(); return; }
        if (isBusy()) { notice(BUSY_TEXT, 3000); return; }
        if (c.id === session.id) { close(); return; }
        if (await restoreConversation(c.id)) close();
      };
    }
  };
  draw();
  place();
  // A16：面板开着时跟着窗口大小重算位置
  try { win.addEventListener?.('resize', place); } catch {}
  const outside = ev => { if (panel.contains(ev.target) || ev.target === anchor || anchor.contains(ev.target) || !ev.target.isConnected) return; close(); };
  setTimeout(() => doc.addEventListener('click', outside), 0);
}
// [来源N] → 胶囊（打开来源，右侧）；pending（流式时）= 不可点的同款胶囊。胶囊带 data-cite（F5「↑ 引用处」用）
// ── 1020 陈列版（技能 layout: board，她：借鉴那份灵感板）──
// 回答照技能的陈列格式写（skills.BOARD_FORMAT）：# 报告名 / > 一句 / ## 先看这几个 / ## 类别 / - **名字** · 网址 —— 帖里：…；借鉴：…[来源N]。
// 这里解析成分模块的陈列：每条左边是出处帖封面（点了右侧打开原帖），右边名字 + 网址 + 帖里 / 借鉴 + 出处。
// 解析不出 2 条以上就照普通 Markdown 显示（格式只是约定）；不认识的段落（可补、自检提示…）照 Markdown 接在陈列下面。
// 都写成函数声明：页面开头恢复历史时 buildTurn 就会用到，const 在这里还没初始化（TDZ）
function BOARD_ITEM() { return /^\s*[-*]\s+\*\*(.+?)\*\*\s*(.*)$/; }
function BOARD_URL() { return /https?:\/\/[^\s<>()（）\[\]【】「」"'，。；、]+/; }
function BOARD_CITE() { return /\[来源(\d+)(?:\s*[·· ]?\s*段(\d+))?\]/g; }   // 1021：[来源N 段M] 也认
function boardItem(name, rest) {
  const cites = [...String(rest).matchAll(BOARD_CITE())].map(m => Number(m[1]));
  // 1020：这一条自带的配图（正文图 / 评论区的图），后端换成了同一行里的 ![[路径|配图]]；页面拿它当配图，比帖子封面准
  const img = (String(rest).match(/!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]/) || [])[1] || '';
  let text = String(rest).replace(/!\[\[[^\]]*\]\]/g, '').replace(BOARD_CITE(), '').trim();
  const cut = text.search(/——|—/);
  const head = cut >= 0 ? text.slice(0, cut) : text;
  let body = cut >= 0 ? text.slice(cut).replace(/^[—]+\s*/, '') : '';
  const urlHit = head.match(BOARD_URL());
  // 模型常写不带 http 的裸域名（github.com/x/y）：「· 网址 ——」那一格像域名就补成 https（后端 unseen_links 已核过帖里有）
  const bare = head.replace(/^[·\s]+/, '').trim();
  const url = urlHit ? urlHit[0].replace(/[.,;:!?)/]+$/, '')
    : /^[a-z0-9-]+(\.[a-z0-9-]+)+(\/\S*)?$/i.test(bare) ? 'https://' + bare.replace(/[.,;:!?)/]+$/, '') : '';
  if (cut < 0 && !url) body = head.replace(/^[·\s]+/, '');
  const praise = (body.match(/帖里[:：]\s*([\s\S]*?)(?=[；;]?\s*借鉴[:：]|$)/) || [])[1] || '';
  const why = (body.match(/借鉴[:：]\s*([\s\S]*)$/) || [])[1] || '';
  const clean = s => String(s || '').replace(/[；;。\s]+$/, '').trim();
  return { name: clean(name.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')), url, cites, img,
    praise: clean(praise || (why ? '' : body)), why: clean(why) };
}
function parseBoard(md) {
  const out = { title: '', lead: '', top: [], groups: [], rest: [] };
  let cur = null, fence = false, seenSection = false;
  const flush = () => {
    if (!cur) return;
    if (cur.items.length) { if (cur.isTop) out.top.push(...cur.items); else out.groups.push(cur); out.rest.push(...cur.tail); }
    else out.rest.push('## ' + cur.name, ...(cur.desc ? [cur.desc] : []), ...cur.tail);
    cur = null;
  };
  for (const raw of String(md || '').split('\n')) {
    const line = raw.replace(/\s+$/, '');
    if (/^\s*```/.test(line)) fence = !fence;
    if (fence || /^\s*```/.test(line)) { (cur ? cur.tail : out.rest).push(raw); continue; }
    let m;
    if (!seenSection && !out.title && (m = /^#\s+(.+)$/.exec(line))) { out.title = m[1].trim(); continue; }
    if (!seenSection && !out.lead && (m = /^>\s?(.+)$/.exec(line))) { out.lead = m[1].trim(); continue; }
    if ((m = /^#{2,3}\s+(.+)$/.exec(line))) { flush(); seenSection = true; cur = { name: m[1].trim(), desc: '', items: [], tail: [], isTop: /先看/.test(m[1]) }; continue; }
    if (!cur) { out.rest.push(raw); continue; }
    if ((m = BOARD_ITEM().exec(line))) { cur.items.push(boardItem(m[1], m[2])); continue; }
    if (line.trim() && !cur.items.length && !cur.desc && !/^[>!|<-]/.test(line.trim())) { cur.desc = line.trim(); continue; }
    cur.tail.push(raw);
  }
  flush();
  return out;
}
function boardCount(b) { return b ? b.groups.reduce((n, g) => n + g.items.length, 0) : 0; }
function boardImgUrl(path) { try { return app.vault.adapter.getResourcePath(lbPath(String(path).replace(/^\/+/, ''))); } catch { return ''; } }
function boardCover(src) {
  const c = src && src.cover;
  if (!c) return '';
  try { return app.vault.adapter.getResourcePath(lbPath(String(c).replace(/^\/+/, ''))); } catch { return ''; }
}
// 1020 她：只有名字 / 一句「同上，评论区点名」的条目——不单独占一张大卡，同一篇连着的合成一行
function BOARD_NOISE() { return /^(?:(?:同上|同前|同样|同一串[^，。；]*|评论区(?:也|里)?(?:点名|提到|有人推)|只有名字)[，。；、\s]*)+$/; }   // 函数声明：页面开头恢复历史时就会用到（const 有 TDZ）
function boardThin(it) { const p = String(it.praise || '').trim(); return !it.img && !it.url && !it.why && (p.length <= 24 || BOARD_NOISE().test(p)); }
function boardNote(it) { const p = String(it.praise || '').trim(); return BOARD_NOISE().test(p) ? '' : p; }
// ── 1020 她：点「帖里」那段字 → 右侧打开原帖、跳到那一处并标出原句。
// 匹配（1020 第二版；第一版只认名字 / 引号原话，真报告 15/35 条对不上）：「帖里 / 借鉴 / 名字」切成两字片段，在原帖每段正文、每条评论、
// 每张图的识别文字（agent.md「### 第N张（…· image-00N.webp）」）里按 idf 加权算覆盖率（各段都有的「群聊」这种不算数），
// 名字或引号原话原样出现再加分；离线拿她两份真报告测 35/35。图片切轮播到第 N 张描框；正文 / 评论只把重合最多的那一句标出来。
// 滚动只滚原帖自己的滚动区（scrollIntoView 会把 Obsidian 整个工作区一起卷上去——1020 输入框悬空的根因）。
function boardCompact(s) { return String(s || '').normalize('NFKC').replace(/\s+/g, '').toLowerCase(); }
function boardGrams(s) {
  const out = new Set();
  for (const m of boardCompact(s).matchAll(/[a-z0-9]{2,}|[一-鿿]+/g)) {
    const w = m[0];
    if (/^[a-z0-9]/.test(w)) out.add(w); else for (let i = 0; i < w.length - 1; i++) out.add(w.slice(i, i + 2));
  }
  return out;
}
function boardMatcher(it, texts) {
  const q = [...boardGrams([it.name, it.praise, it.why].join(' '))];
  const gs = texts.map(t => boardGrams(t));
  const n = gs.length;
  const w = new Map(q.map(g => [g, Math.log((n + 1) / (gs.filter(G => G.has(g)).length + 0.5))]));
  const tot = [...w.values()].reduce((a, b) => a + b, 0) || 1;
  const names = String(it.name || '').replace(/[《》]/g, '').split(/[、,，/｜|]/).map(boardCompact).filter(x => x.length >= 2);
  const quotes = [...[it.praise, it.why].join(' ').matchAll(/[「“"]([^」”"]{3,40})[」”"]/g)].map(m => boardCompact(m[1]));
  const weigh = G => q.reduce((a, g) => a + (G.has(g) ? w.get(g) : 0), 0);
  return {
    score(i) {
      const c = boardCompact(texts[i]);
      return weigh(gs[i]) / tot + 0.25 * names.some(x => c.includes(x)) + 0.25 * quotes.some(x => c.includes(x));
    },
    sentence: text => weigh(boardGrams(text)),
  };
}
// 1022 她：真机没滚——右栏原帖的滚动容器是 Obsidian 阅读视图，插件锁外层视口时给它 overflow:hidden（lb-pane-locked），
// 只认 auto/scroll 就把它跳过了。hidden 的容器脚本照样能滚：只要内容比容器高就算；从里到外瞬时滚（平滑滚是异步的，外层会读到旧坐标）
function boardScrollable(up) { const st = getComputedStyle(up); return st.overflowY !== 'visible' && up.scrollHeight > up.clientHeight + 1; }
function boardScrollWithin(el, box) {
  for (let up = el.parentElement; up && up !== box.parentElement; up = up.parentElement) {
    if (!boardScrollable(up)) continue;
    const top = up.scrollTop + el.getBoundingClientRect().top - up.getBoundingClientRect().top - up.clientHeight / 3;
    up.scrollTop = Math.max(0, top);
  }
}
// 把元素里重合最多的那一句包进 <span class="lb-evidence-hit">（跨 <br> / 行内节点也行），过几秒拆掉
function boardMarkSentence(el, m) {
  const nodes = []; const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let all = '';
  while (tw.nextNode()) { nodes.push([tw.currentNode, all.length]); all += tw.currentNode.nodeValue; }
  let best = null;
  for (const seg of all.matchAll(/[^。！？!?；;\n]+[。！？!?；;]?/g)) {
    if (!boardCompact(seg[0])) continue;
    const s = m.sentence(seg[0]);
    if (!best || s > best.s) best = { s, a: seg.index, b: seg.index + seg[0].length };
  }
  if (!best || all.length < 40) { el.classList.add('lb-evidence-hit'); setTimeout(() => el.classList.remove('lb-evidence-hit'), 4500); return el; }
  const marks = [];
  for (const [node, off] of nodes) {
    const a = Math.max(best.a, off), b = Math.min(best.b, off + node.nodeValue.length);
    if (a >= b) continue;
    const r = document.createRange(); r.setStart(node, a - off); r.setEnd(node, b - off);
    const mk = document.createElement('span'); mk.className = 'lb-evidence-hit lb-locate-mark';   // 不用 <mark>：那是「划重点」的元素，会被当成她划过的
    try { r.surroundContents(mk); marks.push(mk); } catch {}
  }
  setTimeout(() => { for (const mk of marks) { const p = mk.parentNode; if (!p) continue; while (mk.firstChild) p.insertBefore(mk.firstChild, mk); p.removeChild(mk); p.normalize?.(); } }, 6000);
  return marks[0] || el;
}
async function boardLocate(src, it) {
  const p = provider();
  await openNote(src);
  const box = p?.archiveLeaves?.(root)?.reader?.view?.containerEl;
  if (!box) return false;
  for (let i = 0; i < 25 && !box.querySelector('.lb-note, .lb-body'); i++) await new Promise(r => setTimeout(r, 80));
  const cands = [...box.querySelectorAll('.lb-body p, .lb-comment-text')].map(el => ({ el, text: el.textContent || '' }));
  try {
    const id = String(src.id || '').replace(/^xhs-/, '');
    const md = id ? await app.vault.adapter.read(lbPath(`_archive/xiaohongshu/${id}/derived/agent.md`)) : '';
    const imgs = [...box.querySelectorAll('.lb-slide img')];
    for (const b of md.split(/\n(?=### 第\d+张（)/)) {
      const m = /^### 第(\d+)张（[^·）]*·\s*([^）\s]+)）/.exec(b);
      if (!m) continue;
      const img = imgs.find(x => decodeURIComponent(x.getAttribute('src') || '').split('?')[0].endsWith('/' + m[2]));
      if (img) cands.push({ el: img, text: b.split(/\n## /)[0], img: true });
    }
  } catch {}
  if (!cands.length) return false;
  const m = boardMatcher(it, cands.map(c => c.text));
  let best = null;
  cands.forEach((c, i) => { const s = m.score(i); if (!best || s > best.s) best = { ...c, s }; });
  if (!best || best.s < 0.18) return false;
  let up = best.el.parentElement; while (up && up !== box) { if (up.tagName === 'DETAILS') up.open = true; up = up.parentElement; }
  const carousel = best.el.closest('.lb-carousel');
  if (carousel) {
    const slide = best.el.closest('.lb-slide');
    carousel.scrollTo({ left: slide.offsetLeft - carousel.querySelector('.lb-slide').offsetLeft, behavior: 'smooth' });
    boardScrollWithin(carousel, box);
    best.el.classList.add('lb-evidence-hit'); setTimeout(() => best.el.classList.remove('lb-evidence-hit'), 4500);
    return true;
  }
  const target = boardMarkSentence(best.el, m);
  boardScrollWithin(target, box);
  return true;
}
async function renderBoard(el, t, board) {
  const srcOf = n => (t.sources || []).find(s => Number(s.citation) === Number(n));
  const firstSrc = it => it.cites.map(srcOf).find(Boolean) || null;
  const byName = new Map(); for (const g of board.groups) for (const it of g.items) if (!byName.has(it.name)) byName.set(it.name, it);
  const wrap = el.createDiv({ cls: 'lbboard' });
  // 整张卡（图 + 字）点了打开原帖；点「帖里」那段字跳到原帖里那一处；网址 / 出处链接自己处理、不冒泡
  const clickable = (card, src) => {
    if (!src) return;
    card.addClass('is-link'); card.setAttribute('role', 'button'); card.tabIndex = 0;
    card.setAttribute('title', '打开原帖：' + (src.title || ''));
    card.onclick = e => { if (e?.target?.closest?.('a,button,.lbboard-jump')) return; openNote(src); };
    card.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault?.(); openNote(src); } };
  };
  const jump = (node, src, it) => {
    if (!src) return;
    node.addClass('lbboard-jump'); node.setAttribute('title', '跳到原帖里这一处');
    node.onclick = e => { e?.stopPropagation?.(); boardLocate(src, it); };
  };
  const cover = (box, src, label, ghost = false, own = '') => {
    if (own) ghost = false;   // 自带配图的条目总是显示自己的图
    const url = ghost ? '' : own ? boardImgUrl(own) : boardCover(src);
    const c = box.createDiv({ cls: 'lbboard-cover' + (ghost ? ' is-ghost' : url ? '' : ' is-empty') });
    if (ghost) return;
    if (url) { const img = c.createEl('img', { attr: { src: url, alt: '', loading: 'lazy' } }); img.onerror = () => { img.remove(); c.addClass('is-empty'); c.createSpan({ text: label }); }; }
    else c.createSpan({ text: label });
  };
  const sources = (box, it) => {
    const list = [...new Set(it.cites)].map(srcOf).filter(Boolean);
    if (!list.length) return;
    const p = box.createDiv({ cls: 'lbboard-src' }); p.createSpan({ text: '出自 ' });
    list.forEach((s, i) => { if (i) p.appendText('、'); const a = p.createEl('button', { cls: 'lbboard-srclink', text: '《' + (s.title || '原帖') + '》', attr: { type: 'button' } }); a.onclick = e => { e?.stopPropagation?.(); openNote(s); }; });
  };
  if (board.title || board.lead) {
    const head = wrap.createDiv({ cls: 'lbboard-head' });
    if (board.title) head.createDiv({ cls: 'lbboard-title', text: board.title });
    if (board.lead) head.createDiv({ cls: 'lbboard-lead', text: board.lead });
  }
  // 先看这几个：出自同一篇的合成一张卡（她 1020：封面一样的别重复放）——封面出一次，下面列名字和各自一句
  if (board.top.length) {
    const sec = wrap.createDiv({ cls: 'lbboard-topsec' });
    sec.createDiv({ cls: 'lbboard-cat', text: '先看这几个' });
    const grid = sec.createDiv({ cls: 'lbboard-top' });
    const cards = [];
    for (const raw of board.top.slice(0, 8)) {
      const it = raw.cites.length ? raw : { ...raw, cites: (byName.get(raw.name) || {}).cites || [] };
      const src = firstSrc(it);
      const key = src ? src.id : 'none:' + it.name;
      let card = cards.find(c => c.key === key);
      if (!card) { card = { key, src, items: [] }; cards.push(card); }
      card.items.push({ it, why: raw.why || raw.praise });
    }
    for (const c of cards) {
      const card = grid.createDiv({ cls: 'lbboard-topcard' + (c.items.length > 1 ? ' is-multi' : '') });
      const own = c.items.map(x => x.it.img || (byName.get(x.it.name) || {}).img).find(Boolean) || '';
      cover(card, c.src, c.items[0].it.name.slice(0, 4), false, own);
      const body = card.createDiv({ cls: 'lbboard-topbody' });
      for (const { it, why } of c.items) {
        const one = body.createDiv({ cls: 'lbboard-topitem' });
        one.createDiv({ cls: 'lbboard-name', text: it.name });
        if (why) one.createDiv({ cls: 'lbboard-topwhy', text: why });
      }
      clickable(card, c.src);
    }
  }
  board.groups.forEach((g, i) => {
    const sec = wrap.createDiv({ cls: 'lbboard-sec', attr: { 'data-cat': String(i) } });
    const h = sec.createDiv({ cls: 'lbboard-cat' }); h.appendText(g.name); h.createSpan({ cls: 'lbboard-n', text: String(g.items.length) });
    if (g.desc) sec.createDiv({ cls: 'lbboard-desc', text: g.desc.replace(BOARD_CITE(), '') });
    // 连着几条出自同一篇：封面只在第一条出，后面留同宽空位对齐；只有名字的薄条目连着的合成一行
    let prev = null;
    for (let j = 0; j < g.items.length; j++) {
      const it = g.items[j], src = firstSrc(it);
      const same = !!src && prev === src.id;
      prev = src ? src.id : null;
      if (boardThin(it)) {
        const run = [it];
        while (j + 1 < g.items.length && boardThin(g.items[j + 1]) && (firstSrc(g.items[j + 1])?.id || null) === (src?.id || null)) run.push(g.items[++j]);
        const row = sec.createDiv({ cls: 'lbboard-row is-thin', attr: { 'data-item': `${i}-${j}` } });
        cover(row, src, g.name.slice(0, 4), same);
        const main = row.createDiv({ cls: 'lbboard-main' });
        const list = main.createDiv({ cls: 'lbboard-chips' });
        run.forEach((x, k) => {
          if (k) list.createSpan({ cls: 'lbboard-chipsep', text: '·' });
          const chip = list.createSpan({ cls: 'lbboard-chip' });
          chip.createSpan({ cls: 'lbboard-name', text: x.name });
          const note = boardNote(x); if (note) chip.createSpan({ cls: 'lbboard-chipnote', text: note });
          jump(chip, firstSrc(x) || src, x);
        });
        sources(main, { cites: [...new Set(run.flatMap(x => x.cites))] });
        clickable(row, src);
        continue;
      }
      const row = sec.createDiv({ cls: 'lbboard-row', attr: { 'data-item': `${i}-${j}` } });
      cover(row, src, g.name.slice(0, 4), same, it.img);
      const main = row.createDiv({ cls: 'lbboard-main' });
      const line = main.createDiv({ cls: 'lbboard-line' });
      line.createSpan({ cls: 'lbboard-name', text: it.name });
      if (it.url) line.createEl('a', { cls: 'lbboard-url', text: it.url.replace(/^https?:\/\//, '').replace(/\/$/, ''), attr: { href: it.url, target: '_blank', rel: 'noopener' } });
      if (it.praise) { const p = main.createDiv({ cls: 'lbboard-text' }); p.createSpan({ cls: 'lbboard-lab', text: '帖里' }); p.appendText(it.praise); jump(p, src, it); }
      if (it.why) { const p = main.createDiv({ cls: 'lbboard-text is-why' }); p.createSpan({ cls: 'lbboard-lab', text: '借鉴' }); p.appendText(it.why); jump(p, src, it); }
      sources(main, it);
      clickable(row, src);
    }
  });
  const rest = board.rest.join('\n').trim();
  if (!rest) return () => {};
  const tail = el.createDiv({ cls: 'lbboard-rest' });
  const d = await renderScoped(rest, tail); bindSources(tail, t.sources || []);
  return d;
}
// 「存成笔记」：陈列版写成库里「报告/」下的一篇 Markdown，手机 Obsidian 也能看。
// 封面只在开头「出处」排一次；每条 = 三级标题 + 网址 / 帖里 / 借鉴 / 出自双链；只有名字的条目并成一行列在那一类最后；
// 引用号 [来源N] 一律换成那篇的双链（来源导读也是），大纲里「分类 → 条目」两级
function safeName(s) { return String(s || '').replace(/[\\/:*?"<>|#^[\]\n\r]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 60) || '问收藏报告'; }
function boardNoteMd(t, board) {
  const srcOf = n => (t.sources || []).find(s => Number(s.citation) === Number(n));
  const link = s => `[[${lbPath(String(s.note || '').replace(/\.md$/, ''))}|《${String(s.title || '原帖').replace(/[|\]]/g, ' ')}》]]`;
  const from = it => [...new Set(it.cites)].map(srcOf).filter(s => s && s.note).map(link).join('、');
  const cites = text => String(text || '').replace(BOARD_CITE(), (m, n) => { const s = srcOf(n); return s && s.note ? link(s) : ''; });
  const used = [];
  for (const it of [...board.top, ...board.groups.flatMap(g => g.items)]) for (const n of it.cites) { const s = srcOf(n); if (s && !used.includes(s)) used.push(s); }
  const out = ['---', 'lb-report: board', `question: ${JSON.stringify(t.q || '')}`, `asked: ${JSON.stringify(t.askedAt || new Date().toISOString())}`,
    `sources: ${used.length}`, 'tags: [lb-report]', '---', '', `# ${board.title || t.q || '问收藏报告'}`, ''];
  if (board.lead) out.push(`> ${cites(board.lead)}`, '');
  if (used.length) {
    out.push('## 出处', '');
    const covers = used.filter(s => s.cover).map(s => `![[${lbPath(String(s.cover).replace(/^\/+/, ''))}|110]]`);
    if (covers.length) out.push(covers.join(' '), '');
    used.forEach((s, i) => out.push(`${i + 1}. ${link(s)}`));
    out.push('');
  }
  if (board.top.length) {
    out.push('## 先看这几个', '');
    for (const it of board.top) out.push(`- **${it.name}** —— ${it.why || it.praise}`);
    out.push('');
  }
  for (const g of board.groups) {
    out.push(`## ${g.name}`, '');
    if (g.desc) out.push(cites(g.desc), '');
    const thin = g.items.filter(boardThin);
    for (const it of g.items.filter(x => !boardThin(x))) {
      out.push(`### ${it.name}`, '');
      if (it.img) out.push(`![[${lbPath(String(it.img).replace(/^\/+/, ''))}|200]]`, '');
      if (it.url) out.push(`- 网址：[${it.url.replace(/^https?:\/\//, '').replace(/\/$/, '')}](${it.url})`);
      if (it.praise) out.push(`- 帖里：${it.praise}`);
      if (it.why) out.push(`- 借鉴：${it.why}`);
      if (from(it)) out.push(`- 出自：${from(it)}`);
      out.push('');
    }
    if (thin.length) {
      out.push((thin.length < g.items.length ? '还提到：' : '') + thin.map(it => `**${it.name}**` + (boardNote(it) ? `（${boardNote(it)}）` : '')).join(' · ')
        + (from({ cites: [...new Set(thin.flatMap(x => x.cites))] }) ? ` —— 出自 ${from({ cites: [...new Set(thin.flatMap(x => x.cites))] })}` : ''), '');
    }
  }
  const rest = cites(board.rest.join('\n')).trim();
  if (rest) out.push(rest, '');
  return out.join('\n');
}
async function saveBoardNote(t) {
  const board = parseBoard(t.content);
  if (boardCount(board) < 2) { notice('这一答不是陈列格式，没法存成报告笔记'); return null; }
  const dir = lbPath('报告');
  try { if (!(await app.vault.adapter.exists(dir))) await app.vault.adapter.mkdir(dir); } catch {}
  const base = safeName(board.title || t.q);
  let path = `${dir}/${base}.md`;
  for (let k = 2; k < 50 && (await app.vault.adapter.exists(path)); k++) path = `${dir}/${base} ${k}.md`;
  await app.vault.adapter.write(path, boardNoteMd(t, board));
  return path;
}
// 1021 悬停引用胶囊 → 小卡：来源标题 · 这一段在哪（段k · 正文 / 图N / 评论 cN）· 原文前几行。只读、不开右栏；移开 / 点击就收。
function citePop() {   // 函数声明 + 懒建：页面开头恢复历史时 bindSources 就会用到（const 在这里还没初始化，TDZ）
  if (citePop._i) return citePop._i;
  let box = null, timer = 0;
  const KIND = { body: '正文', comments: '评论区', ocr: '图片文字', comment_ocr: '评论区图片', transcript: '视频文字稿', screen: '视频画面文字', attachments: '附件', notes: '批注', highlights: '重点' };
  const hide = () => { clearTimeout(timer); timer = 0; if (box) { box.remove(); box = null; } };
  const pick = (src, seg, context) => {
    const all = (src?.excerpts || []).filter(p => p && p.text);
    if (seg) { const p = all.find(x => Number(x.seg) === Number(seg)); if (p) return p; }
    if (!context || !all.length) return all[0] || null;
    const normalized = String(context).replace(/\s/g, '').toLowerCase();
    const score = p => { const text = String(p.text).replace(/\s/g, '').toLowerCase(); let n = 0; for (let i = 0; i < normalized.length - 3; i++) if (text.includes(normalized.slice(i, i + 4))) n++; return n; };
    return all.slice().sort((a, b) => score(b) - score(a))[0] || null;
  };
  const where = p => {
    if (!p) return '';
    const ids = (p.images || p.comment_labels || p.comments || []).slice(0, 3).join('、');
    return (p.seg ? `段${p.seg} · ` : '') + (KIND[p.field] || p.field || '') + (ids ? ' ' + ids : '') + (p.speakers?.length ? ' · ' + p.speakers.slice(0, 2).join('、') : '');
  };
  const show = (btn, src, seg, context) => {
    hide();
    const p = pick(src, seg, context);
    box = document.createElement('div'); box.className = 'lbchat-citepop';
    const t = document.createElement('div'); t.className = 't'; t.textContent = src?.title || '未命名'; box.append(t);
    const w = document.createElement('div'); w.className = 'w'; w.textContent = p ? where(p) : '原文在右侧打开'; box.append(w);
    if (p) { const q = document.createElement('div'); q.className = 'q'; q.textContent = String(p.text).trim().slice(0, 240); box.append(q); }
    document.body.append(box);
    const r = btn.getBoundingClientRect(), bw = box.offsetWidth || 320, bh = box.offsetHeight || 80;
    const left = Math.max(8, Math.min(r.left, window.innerWidth - bw - 8));
    const top = r.bottom + 6 + bh > window.innerHeight ? Math.max(8, r.top - bh - 6) : r.bottom + 6;
    box.style.left = left + 'px'; box.style.top = top + 'px';
  };
  const bind = (btn, src, seg, context) => {
    btn.addEventListener('mouseenter', () => { clearTimeout(timer); timer = setTimeout(() => show(btn, src, seg, context), 320); });
    btn.addEventListener('mouseleave', hide);
    btn.addEventListener('focus', () => show(btn, src, seg, context));
    btn.addEventListener('blur', hide);
  };
  return (citePop._i = { bind, hide });
}
function bindSources(el, sources, { pending = false } = {}) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    if (node.parentElement?.closest('a,code,pre,button')) continue;
    const matches = [...node.textContent.matchAll(/\[来源(\d+)(?:\s*[·· ]?\s*段(\d+))?\]/g)]; if (!matches.length) continue;
    const frag = document.createDocumentFragment(); let last = 0;
    for (const m of matches) {
      frag.append(document.createTextNode(node.textContent.slice(last, m.index)));
      const src = pending ? null : sources.find(x => Number(x.citation) === Number(m[1]));
      const label = `[来源${m[1]}]`, seg = m[2] ? Number(m[2]) : 0;   // 1021：段号不显示在胶囊上（噪音），记在 data-seg；点了直达那一段
      if (pending) { const s = document.createElement('span'); s.className = 'lbchat-cite is-pending'; s.textContent = label; s.dataset.cite = m[1]; frag.append(s); }
      else if (src) {
        const b = document.createElement('button'); b.className = 'lbchat-cite'; b.textContent = label; b.dataset.cite = m[1]; if (seg) b.dataset.seg = String(seg);
        b.setAttribute('title', seg ? `打开原帖，跳到引用的第 ${seg} 段（右侧）` : '打开原帖，跳到引用的那一处（右侧）');
        b.onclick = e => { e?.stopPropagation?.(); citePop().hide(); openNote(src, false, b.closest('p,li')?.textContent || '', b, seg); };
        citePop().bind(b, src, seg, b.closest('p,li')?.textContent || '');
        frag.append(b);
      }
      else frag.append(document.createTextNode(m[0]));
      last = m.index + m[0].length;
    }
    frag.append(document.createTextNode(node.textContent.slice(last))); node.replaceWith(frag);
  }
  if (pending) return;
  for (const a of el.querySelectorAll('a')) { const href = a.getAttribute('data-href') || a.getAttribute('href'); const src = sources.find(x => href === x.url || href === x.note || href === x.note?.replace(/\.md$/, '')); if (src) a.onclick = e => { e?.preventDefault?.(); e?.stopPropagation?.(); openNote(src); }; }
}

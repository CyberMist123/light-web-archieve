// chat-view.js — 收藏搜索页的极简版（Owner 2026-09-17）。
// 无框线、居中、像聊天：搜收藏 + 问 AI 一体；会话持久化（跳走再回来不丢，直到点「清空」）；
// 「存档」栏可存可删——既存 AI 报告，也存 Owner 自己写的判断。配色全走 Obsidian 主题变量。
// 依赖：本文件前面已内联 catalog-search.js（score/normalize）；provider = link-brain-actions 插件。
const root = dv.container;
// 这个仓可能被挂进别的库的子目录（如 LER Vault/知识库【小红书】/）；数据里的路径都相对 lwa 仓根，
// 统一过 lbPath 补上挂载前缀。仓根 = 从本页往上第一个带 _archive 的目录。
const LB_ROOT=(()=>{try{let d=dv.current()?.file?.folder||'';while(d&&!app.vault.getAbstractFileByPath(d+'/_archive'))d=d.includes('/')?d.slice(0,d.lastIndexOf('/')):'';return d;}catch{return '';}})();
const lbPath=p=>p&&LB_ROOT?`${LB_ROOT}/${p}`:p;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-chatpage');
const provider = () => app.plugins.plugins['link-brain-actions'];
const SESSION_PATH = lbPath('_archive/chat-session.json');
const ARCHIVE_PATH = lbPath('_archive/chat-archive.json');
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

let data = {};
try { data = JSON.parse(await app.vault.adapter.read(lbPath('_archive/catalog-data.json'))); } catch {}
let items = data.items || [];

let session = { turns: [], draft: '' };
let archive = { entries: [] };
try { session = JSON.parse(await app.vault.adapter.read(SESSION_PATH)); } catch {}
try { archive = JSON.parse(await app.vault.adapter.read(ARCHIVE_PATH)); } catch {}
session.turns = Array.isArray(session.turns) ? session.turns : [];
session.draft = typeof session.draft === 'string' ? session.draft : '';
archive.entries = Array.isArray(archive.entries) ? archive.entries : [];

let lane = 'chat', busy = false, thinkTimer = null;
const saveSession = async () => { try { await app.vault.adapter.write(SESSION_PATH, JSON.stringify(session)); } catch {} };
const saveArchive = async () => { try { await app.vault.adapter.write(ARCHIVE_PATH, JSON.stringify(archive, null, 2)); } catch {} };
const openNote = (path) => { if (path) app.workspace.openLinkText(lbPath(path), '', true); }; // 新叶打开，别把本页冲掉

const style = root.createEl('style');
style.textContent = `
.markdown-preview-view.lb-chatpage,.markdown-source-view.lb-chatpage{--file-line-width:100%;}
.lb-chatpage .markdown-preview-sizer,.lb-chatpage .markdown-preview-section,.lb-chatpage .cm-sizer,.lb-chatpage .cm-contentContainer,.lb-chatpage .cm-content,.lb-chatpage .block-language-dataviewjs{width:100%!important;max-width:none!important;}
.lb-chatpage .inline-title,.lb-chatpage .metadata-container{display:none!important;}
.lbchat{max-width:720px;margin:0 auto;padding:28px clamp(14px,3vw,20px) 120px;font-family:var(--font-interface),"Segoe UI","Microsoft YaHei",sans-serif;color:var(--text-normal);}
.lbchat-head{display:flex;flex-direction:column;align-items:center;text-align:center;gap:12px;margin:8px 0 22px;}
.lbchat-titleblock{display:flex;flex-direction:column;align-items:center;gap:6px;}
.lbchat-titlerow{display:flex;align-items:baseline;justify-content:center;gap:9px;}
.lbchat-title{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:42px;font-weight:600;letter-spacing:.01em;line-height:1.05;color:var(--text-normal);}
.lbchat-plus{font-family:Georgia,'Playfair Display','Times New Roman',serif;font-style:italic;font-size:38px;line-height:1;color:var(--text-faint);cursor:pointer;transition:color .12s;}
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
.lbchat-turn{margin:0 0 26px;line-height:1.8;font-size:15px;overflow-wrap:anywhere;}
.lbchat-user{color:var(--text-normal);font-weight:500;}
.lbchat-user .lbchat-qmark{color:var(--text-faint);margin-right:8px;}
.lbchat-answer{line-height:1.8;}
.lbchat-answer p:first-child{margin-top:0;}
.lbchat-answer p:last-child{margin-bottom:0;}
.lbchat-actions{display:flex;gap:16px;margin-top:10px;}
.lbchat-act{cursor:pointer;font-size:12px;color:var(--text-faint);transition:color .12s;}
.lbchat-act:hover{color:var(--interactive-accent);}
.lbchat-src{margin-top:12px;font-size:12px;color:var(--text-muted);}
.lbchat-src summary{cursor:pointer;color:var(--text-faint);}
.lbchat-src a{display:block;margin:6px 0;cursor:pointer;color:var(--link-color);}
.lbchat-hits{display:flex;flex-direction:column;gap:16px;}
.lbchat-hit{cursor:pointer;}
.lbchat-hit-title{font-size:14px;font-weight:600;color:var(--text-normal);}
.lbchat-hit-title:hover{color:var(--interactive-accent);}
.lbchat-hit-meta{font-size:12px;color:var(--text-faint);margin-top:2px;}
.lbchat-hit-ex{font-size:13px;color:var(--text-muted);line-height:1.65;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lbchat-think{display:flex;align-items:center;gap:8px;color:var(--text-muted);font-size:14px;margin:0 0 26px;}
.lbchat-dot{width:6px;height:6px;border-radius:50%;background:var(--interactive-accent);opacity:.5;animation:lbchatpulse 1s ease-in-out infinite;}
@keyframes lbchatpulse{0%,100%{opacity:.25;transform:scale(.8);}50%{opacity:1;transform:scale(1);}}
.lbchat-arc-add{display:flex;gap:10px;align-items:flex-end;margin:0 0 24px;}
.lbchat-arc-input{flex:1;resize:vertical;min-height:38px;border:none;border-bottom:1px solid var(--background-modifier-border);border-radius:0;background:transparent;color:var(--text-normal);font:inherit;font-size:14px;padding:6px 2px;box-sizing:border-box;}
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
`;

const wrap = root.createEl('div', { cls: 'lbchat' });
// 图1 顶头：Collections + 标题 + 计数/更新，右边一条下划线搜索（问答时这一整块都不动）。
const head = wrap.createEl('div', { cls: 'lbchat-head' });
const titleBlock = head.createEl('div', { cls: 'lbchat-titleblock' });
const titleRow = titleBlock.createEl('div', { cls: 'lbchat-titlerow' });
titleRow.createEl('span', { cls: 'lbchat-title', text: 'Collections' });
const plus = titleRow.createEl('span', { cls: 'lbchat-plus', text: '+' });
plus.title = '导入收藏 / 同步收藏夹';
plus.onclick = (evt) => {
  const p = provider();
  if (typeof p?.openPlusMenu !== 'function') { try { new Notice('需要启用 Link Brain Actions 插件'); } catch {} return; }
  p.openPlusMenu(evt);
};
const sub = titleBlock.createEl('div', { cls: 'lbchat-sub' });
try {
  const t = new Date(data.built_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
  sub.setText(`${items.length} 篇 · 更新 ${t}`);
} catch { sub.setText(`${items.length} 篇`); }
const search = head.createEl('input', { cls: 'lbchat-search' });
search.type = 'search'; search.placeholder = '搜索收藏，或 / 问 AI…'; search.value = session.draft || '';

// 第二行：对话/存档 切换 + 同步/浏览/清空
const nav = wrap.createEl('div', { cls: 'lbchat-nav' });
const tabChat = nav.createEl('span', { cls: 'lbchat-tab', text: '对话' });
const tabArch = nav.createEl('span', { cls: 'lbchat-tab', text: '存档' });
nav.createEl('span', { cls: 'lbchat-navsep', text: '·' });
const browseLink = nav.createEl('span', { cls: 'lbchat-tab', text: '浏览目录' });
browseLink.onclick = () => app.workspace.openLinkText(lbPath('小红书收藏目录.md'), '', false);
const clearBtn = nav.createEl('span', { cls: 'lbchat-clear', text: '清空' });
const bodyEl = wrap.createEl('div', { cls: 'lbchat-body' });

// 顶部搜索框 = 唯一输入：回车触发（/ 开头问 AI，否则搜），草稿持久化
search.oninput = () => { session.draft = search.value; saveSession(); };
search.onkeydown = e => {
  if (e.key !== 'Enter' || e.isComposing) return;
  e.preventDefault();
  const v = search.value; search.value = ''; session.draft = '';
  submit(v);
};

// ── 搜索 ──
function runSearch(q) {
  const nq = normalize(q);
  const scored = items
    .map(it => ({ it, s: score(it, nq, data.pinyin_chars, data.aliases || []) }))
    .filter(x => x.s > 0).sort((a, b) => b.s - a.s).slice(0, 12);
  return scored.map(({ it }) => {
    const text = it.search_text || it.summary || '';
    const pos = nq ? text.toLowerCase().indexOf(nq.split(/\s+/)[0]) : -1;
    const ex = pos >= 0 ? text.slice(Math.max(0, pos - 40), Math.max(0, pos - 40) + 200) : text.slice(0, 200);
    return { id: it.id, title: it.title || '未命名', note: it.note, author: it.author || it.source || '收藏', excerpt: ex };
  });
}

// ── 会话渲染 ──
async function drawChat() {
  bodyEl.empty();
  clearBtn.hidden = session.turns.length === 0;
  if (!session.turns.length && !busy) {
    bodyEl.createEl('div', { cls: 'lbchat-empty', text: '搜收藏，或用 / 开头问 AI 整理答案。' });
  }
  for (const t of session.turns) {
    if (t.role === 'user') {
      const el = bodyEl.createEl('div', { cls: 'lbchat-turn lbchat-user' });
      if (t.mode === 'search') el.createEl('span', { cls: 'lbchat-qmark', text: '搜' });
      el.appendText(t.content);
    } else if (t.role === 'search') {
      const el = bodyEl.createEl('div', { cls: 'lbchat-turn' });
      if (!t.results.length) { el.createEl('div', { cls: 'lbchat-empty', text: '没找到，试试更短的关键词。' }); continue; }
      const hits = el.createEl('div', { cls: 'lbchat-hits' });
      for (const r of t.results) {
        const h = hits.createEl('div', { cls: 'lbchat-hit' });
        h.createEl('div', { cls: 'lbchat-hit-title', text: r.title });
        h.createEl('div', { cls: 'lbchat-hit-meta', text: r.author });
        if (r.excerpt) h.createEl('div', { cls: 'lbchat-hit-ex', text: r.excerpt });
        h.onclick = () => openNote(r.note);
      }
    } else { // assistant
      const el = bodyEl.createEl('div', { cls: 'lbchat-turn lbchat-answer' });
      try { await provider().renderMarkdownInto(t.content, el); } catch { el.setText(t.content); }
      if (t.sources && t.sources.length) {
        const refs = el.createEl('details', { cls: 'lbchat-src' });
        refs.createEl('summary', { text: `参考材料 · ${t.sources.length}` });
        for (const src of t.sources) {
          const a = refs.createEl('a', { text: `[来源${src.citation}] ${src.title}` });
          a.onclick = () => openNote(src.note || src.agent_md);
        }
      }
      if (!t.failed) {
        const acts = el.createEl('div', { cls: 'lbchat-actions' });
        const save = acts.createEl('span', { cls: 'lbchat-act', text: '存到存档' });
        save.onclick = async () => {
          archive.entries.unshift({ id: uid(), ts: new Date().toISOString(), kind: 'report', title: t.q || 'AI 整理', content: t.content });
          await saveArchive(); save.setText('已存 ✓'); save.style.color = 'var(--interactive-accent)';
        };
      }
    }
  }
  if (busy) {
    const th = bodyEl.createEl('div', { cls: 'lbchat-think' });
    th.createEl('span', { cls: 'lbchat-dot' });
    const label = th.createEl('span');
    const phases = ['正在检索收藏…', '正在读相关笔记…', '正在整理答案…'];
    let i = 0; label.setText(phases[0]);
    clearInterval(thinkTimer);
    thinkTimer = setInterval(() => { i = (i + 1) % phases.length; label.setText(phases[i]); }, 1400);
  } else { clearInterval(thinkTimer); thinkTimer = null; }
}

async function drawArchive() {
  bodyEl.empty();
  clearBtn.hidden = true;
  const addRow = bodyEl.createEl('div', { cls: 'lbchat-arc-add' });
  const ta = addRow.createEl('textarea', { cls: 'lbchat-arc-input' });
  ta.placeholder = '写一条自己的判断存起来（如「ib 机不适合」）…';
  const saveIt = addRow.createEl('span', { cls: 'lbchat-arc-save', text: '存' });
  saveIt.onclick = async () => {
    const txt = ta.value.trim(); if (!txt) return;
    archive.entries.unshift({ id: uid(), ts: new Date().toISOString(), kind: 'note', title: '', content: txt });
    ta.value = ''; await saveArchive(); drawArchive();
  };
  if (!archive.entries.length) { bodyEl.createEl('div', { cls: 'lbchat-empty', text: '还没有存档。对话里点「存到存档」，或在上面写自己的判断。' }); return; }
  for (const e of archive.entries) {
    const item = bodyEl.createEl('div', { cls: 'lbchat-arc-item' });
    const meta = item.createEl('div', { cls: 'lbchat-arc-meta' });
    meta.createEl('span', { cls: 'lbchat-arc-kind', text: e.kind === 'note' ? '判断' : 'AI 报告' });
    meta.createEl('span', { text: fmtTs(e.ts) + (e.title ? ' · ' + e.title : '') });
    const del = meta.createEl('span', { cls: 'lbchat-arc-del', text: '✕' }); del.title = '删除';
    del.onclick = async () => { archive.entries = archive.entries.filter(x => x.id !== e.id); await saveArchive(); drawArchive(); };
    const b = item.createEl('div', { cls: 'lbchat-arc-body' });
    try { await provider().renderMarkdownInto(e.content, b); } catch { b.setText(e.content); }
  }
}
function fmtTs(ts) { try { const d = new Date(ts); return `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; } catch { return ''; } }

async function submit(raw) {
  const text = (raw || '').trim(); if (!text || busy) return;
  session.draft = '';
  if (text.startsWith('/')) {
    const q = text.slice(1).trim(); if (!q) return;
    session.turns.push({ role: 'user', content: q, mode: 'ask' });
    await saveSession(); busy = true; await drawChat();
    try {
      const history = session.turns.filter(t => t.role === 'user' || t.role === 'assistant').filter(t => !t.failed)
        .map(t => ({ role: t.role === 'assistant' ? 'assistant' : 'user', content: t.content }));
      const r = await provider().answerArchive({ question: q, history });
      session.turns.push({ role: 'assistant', content: r.markdown || '没有可用的回答。', sources: r.sources || [], q });
    } catch (e) {
      session.turns.push({ role: 'assistant', failed: true, content: '回答失败：' + (e.message || e) + '\n\n请重试。' });
    } finally { busy = false; await saveSession(); await drawChat(); }
  } else {
    session.turns.push({ role: 'user', content: text, mode: 'search' });
    session.turns.push({ role: 'search', results: runSearch(text) });
    await saveSession(); await drawChat();
  }
}

// ── 栏切换 / 清空 ──（顶头 Collections+ 标题 + 搜索始终不动；只切换下面的正文）
function setLane(next) {
  lane = next;
  tabChat.classList.toggle('is-on', lane === 'chat');
  tabArch.classList.toggle('is-on', lane === 'archive');
  search.hidden = lane !== 'chat';   // 存档栏用它自己的输入框，顶部搜索只服务对话栏
  clearBtn.hidden = lane !== 'chat' || !session.turns.length;
  if (lane === 'chat') drawChat(); else drawArchive();
}
tabChat.onclick = () => setLane('chat');
tabArch.onclick = () => setLane('archive');
clearBtn.onclick = async () => {
  if (!session.turns.length) return;
  if (!window.confirm('清空当前对话？存档里已保存的不受影响。')) return;
  session.turns = []; session.draft = ''; search.value = ''; await saveSession(); drawChat();
  clearBtn.hidden = true;
};

setLane('chat');

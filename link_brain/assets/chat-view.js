// chat-view.js — 收藏搜索页的极简版（Owner 2026-09-17）。
// 无框线、居中、像聊天：搜收藏 + 问 AI 一体；会话持久化（跳走再回来不丢，直到点「清空」）；
// 「存档」栏可存可删——既存 AI 报告，也存 Owner 自己写的判断。配色全走 Obsidian 主题变量。
// 依赖：本文件前面已内联 lb-page-lib.js（共享前导，CONVENTIONS §5）和 catalog-search.js（score/normalize）；provider = link-brain-actions 插件。
// 第 2 批：Dataview 每 2.5 秒重跑本页时，版本没变就把上一次的整页 DOM 挂回（正在生成的回答、输入框、滚动都在）。
const LB = lbPageLib(dv, app, 'chat');
if (await LB.reuseDom()) return;
const root = dv.container;
// 这个仓可能被挂进别的库的子目录（如 LER Vault/知识库【小红书】/）；数据里的路径都相对 lwa 仓根，统一过 lbPath 补挂载前缀。
const lbPath = LB.path;
const pane = root.closest('.markdown-preview-view, .markdown-source-view');
if (pane) pane.classList.add('lb-chatpage');
const provider = LB.provider;
const SESSION_PATH = lbPath('_archive/chat-session.json');
const ARCHIVE_PATH = lbPath('_archive/chat-archive.json');
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

let data = {};
try { data = await LB.data.load(); } catch {}
let items = data.items || [];

let session = { turns: [], draft: '' };
let archive = { entries: [] };
try { session = JSON.parse(await app.vault.adapter.read(SESSION_PATH)); } catch {}
try { archive = JSON.parse(await app.vault.adapter.read(ARCHIVE_PATH)); } catch {}
session.turns = Array.isArray(session.turns) ? session.turns : [];
session.draft = typeof session.draft === 'string' ? session.draft : '';
// R2 会话状态（10-04）：排除 / 保留（pin）是整个会话的，跨轮生效——追问、重答都读这同一份；旧会话没这两个字段 = 空
const idList = v => Array.isArray(v) ? [...new Set(v.filter(x => typeof x === 'string' && x))] : [];
session.excluded = idList(session.excluded);
session.pinned = idList(session.pinned);
// 10-04 追问绑定来源：'sources'（默认）= 有上一轮回答时，追问只在它留下的来源里答、不重新检索；'search' = 她点了「改为重新搜」
session.follow = session.follow === 'search' ? 'search' : 'sources';
archive.entries = Array.isArray(archive.entries) ? archive.entries : [];

// 草稿（正在打的字）只存 sessionStorage（§5.3）：以前每敲一个字都写 vault 里的 chat-session.json，会让别的页跟着刷新
const pageState = LB.state.load();
const saveDraft = v => LB.state.patch({ draft: v });
let lane = 'chat', busy = false;
// 会话文件只在问答轮次变了时写；draft 不再进文件（旧文件里的 draft 只在第一次读时接过来）
// 第 3 批（CONVENTIONS §1.5）：写盘失败一律抛给调用方——写成功才改界面，失败把内存改回去并提示，不再 catch {} 空吞。
const notice = (msg, ms = 8000) => { try { new Notice(msg, ms); } catch { window.alert(msg); } };
const NOT_SAVED = '没保存上，内容还在，可重试：';
const errText = e => (e && e.message) || String(e || '未知原因');
const writeJson = (file, obj, pretty) => app.vault.adapter.write(file, pretty ? JSON.stringify(obj, null, 2) : JSON.stringify(obj));
const saveSession = () => writeJson(SESSION_PATH, { turns: session.turns, excluded: session.excluded, pinned: session.pinned, follow: session.follow });
const saveArchive = () => writeJson(ARCHIVE_PATH, archive, true);
// 对话轮次：内存里已经显示了，写不进文件只影响「重开页面还在不在」——如实说一句，不打断作答
const keepSession = async () => { try { await saveSession(); } catch (e) { notice('对话没写进文件，重开这一页会丢：' + errText(e)); } };
// 「已保存」栏的改动：快照 → 改 → 写盘；失败回滚快照、重画、提示（§1.5 统一写法）
async function archiveChange(mutate) {
  const prev = JSON.stringify(archive.entries);
  mutate();
  try { await saveArchive(); return true; }
  catch (e) { archive.entries = JSON.parse(prev); notice(NOT_SAVED + errText(e)); return false; }
}
// 来源阅读（第 2 批，核实版 3.1/3.2）：只有引用编号、来源标题、「查看」按钮会打开来源，一律放进右侧同一个来源窗格（复用）；
// 「加入对照」把这一篇放到来源窗格下方对照；「退出对照」关掉下方那格；「收起来源」右侧全关。整段文字单击不再打开任何东西。
const openNote = (source,compare=false,context="") => {
  const src=typeof source==='string'?{note:source}:source;
  const chunks=(src?.excerpts||[]).filter(p=>p.field==='body'||p.field==='comments');
  if(context){const normalized=context.replace(/\s/g,'').toLowerCase();const score=p=>{const text=String(p.text).replace(/\s/g,'').toLowerCase();let n=0;for(let i=0;i<normalized.length-3;i++)if(text.includes(normalized.slice(i,i+4)))n++;return n;};chunks.sort((a,b)=>score(b)-score(a));}
  if(src?.note){userAt=0;dragging=false;}   // 点来源这一下不是在滚（之前滚到一半的不算）
  if(src?.note)return Promise.resolve(provider().openArchiveSource(src.note,root,compare,chunks)).then(()=>{paintSourceBar();settle();}).catch(e=>window.alert(e.message));
};

const style = root.createEl('style');
style.textContent = `
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

.lb-page-nav{display:flex;grid-column:2;grid-row:1;gap:2px;padding:4px;background:var(--background-secondary);border-radius:12px;justify-self:center;white-space:nowrap;}
.lb-page-nav button{font:inherit;font-size:13px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);border-radius:9px;padding:9px 16px;height:auto;cursor:pointer;}
.lb-page-nav button.is-current{background:var(--background-primary)!important;color:var(--text-normal);box-shadow:0 1px 4px #0000000c!important;font-weight:500;}
.lb-manage{font-size:24px!important;font-weight:500;background:transparent!important;border:0!important;box-shadow:none!important;color:var(--text-muted);padding:0!important;width:40px;height:40px;border-radius:10px;cursor:pointer;}
.lb-manage:hover{background:var(--background-secondary)!important;color:var(--text-normal);}
.lbc-wrap button:focus-visible,.lbchat button:focus-visible{outline:2px solid var(--interactive-accent)!important;outline-offset:3px;}
.lbc-live,.lbchat-live{white-space:pre-wrap;}

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
.lbchat-editor{width:100%;min-height:230px;font:inherit;line-height:1.7;resize:vertical;box-sizing:border-box;}
.lbchat-editbar{display:flex;gap:12px;margin:8px 0;}
.lbchat-srcbar{flex:none;width:100%;max-width:850px;margin:8px auto -12px;box-sizing:border-box;display:flex;align-items:center;gap:14px;padding:0 8px;font-size:12px;color:var(--text-faint);}
.lbchat-srcbar[hidden]{display:none;}
.lbchat-body:not(.lbchat-has-reader) .lbchat-addcmp{display:none;}
@media(max-width:700px){.lbchat{padding:12px 6px 0;}.lbchat-title{font-size:28px;}.lbchat-tools{gap:8px;}.lbchat-head{gap:10px;margin-bottom:18px;}.lbchat-composer{padding:8px;}.lbchat-body{padding:0 4px 20px;}}

.lbchat .lbchat-composer{align-items:center;gap:6px;padding:8px 10px 8px 14px;border-radius:28px;border:1px solid var(--background-modifier-border);background:var(--background-primary);box-shadow:0 2px 12px #0000000f;}
.lbchat .lbchat-composer:focus-within{border-color:var(--background-modifier-border-hover);}
.lbchat .lbchat-search{height:40px;min-height:40px;resize:none;padding:9px 4px!important;background:transparent!important;box-shadow:none!important;}
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
.lb-visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
.lbc-star{opacity:0;pointer-events:none;transition:opacity .15s;}.lbc-card:hover .lbc-star,.lbc-card:focus-within .lbc-star{opacity:1;pointer-events:auto;}
@media(hover:none){.lbc-star{opacity:1;pointer-events:auto;}}
.lbc-badges{position:absolute;top:8px;left:8px;display:flex;gap:5px;align-items:center;}
.lbc-badges .lbc-attach{position:static;display:inline-flex;align-items:center;line-height:16px;padding:3px 6px;gap:4px;height:22px;box-sizing:border-box;}
.lbc-badges svg{display:block;width:14px;height:14px;flex:none;stroke:currentColor;stroke-width:1.6;fill:none;}
.lbc-simple .lbc-grid-inner{columns:auto;}.lbc-simple .lbc-card{padding:18px 42px 18px 0;}.lbc-simple .lbc-body{padding:0;}.lbc-simple .lbc-badges{position:static;float:right;margin:2px 0 0 12px;}.lbc-simple .lbc-star{top:16px;right:0;}.lbc-simple .lbc-cmeta{margin-top:4px;}
.lbchat-bookmark svg{width:18px;height:18px;display:block;stroke:currentColor;stroke-width:1.6;fill:none;}.lbchat-bookmark.is-saved svg{fill:currentColor;}
.lbchat .lbchat-composer{margin-top:24px;margin-bottom:14px;}.lbchat{height:calc(100vh - 80px);}
.lbchat-hist{background:transparent;border:0;color:var(--text-muted);cursor:pointer;padding:6px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;transition:color .12s,background .12s;}
.lbchat-hist:hover{color:var(--text-normal);background:var(--background-modifier-hover);}
.lbchat-histpanel{position:fixed;width:320px;max-height:60vh;overflow:auto;background:var(--background-primary);border:1px solid var(--background-modifier-border);border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.22);padding:6px;z-index:9999;}
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
.lb-manage{font-family:Arial,sans-serif!important;line-height:1!important;display:grid;place-items:center;}
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
.lbchat .lbchat-answer > :first-child,.lbchat .lbchat-answer > :first-child > :first-child{margin-top:0;}
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
.lbchat .lbchat-srcrow button.lbchat-src-pin,.lbchat .lbchat-srcrow button.lbchat-src-del{border:1px solid var(--background-modifier-border)!important;border-radius:999px;padding:0 10px;height:22px;line-height:20px;font-size:11.5px;color:var(--text-muted);background:var(--background-primary)!important;}
.lbchat .lbchat-srcrow button.lbchat-src-del{padding:0 8px;font-size:13px;}
.lbchat .lbchat-srcrow button.lbchat-src-pin:hover{color:var(--text-normal);border-color:var(--text-muted)!important;}
.lbchat .lbchat-srcrow button.lbchat-src-pin.is-on{background:var(--interactive-accent)!important;border-color:var(--interactive-accent)!important;color:var(--text-on-accent,#fff);}
.lbchat .lbchat-srcrow button.lbchat-src-pin.is-on::before{content:'✓ ';}
.lbchat .lbchat-srcrow button.lbchat-src-del:hover{color:var(--text-error,#e5534b);border-color:var(--text-error,#e5534b)!important;}
@media(max-width:700px){.lbchat-srcrow{flex-wrap:wrap;gap:4px 12px;}.lbchat-srcrow > a{flex-basis:100%;}.lbchat-followbar{padding:0 8px;}}
`;

const wrap = root.createEl('div', { cls: 'lbchat' });
// Size against the actual Obsidian pane, not the entire screen (tabs/toolbars
// and pane offsets otherwise push the composer below the visible area).
const fitPane=()=>{const viewport=root.closest('.workspace-leaf-content')||(pane&&['auto','scroll','hidden'].includes(getComputedStyle(pane).overflowY)?pane:null);const bottom=Math.min(window.innerHeight,viewport?.getBoundingClientRect().bottom||window.innerHeight);wrap.style.height=Math.max(240,bottom-wrap.getBoundingClientRect().top-16)+'px';};
const resizeObserver=new ResizeObserver(fitPane);resizeObserver.observe(pane||document.documentElement);
if(dv.component?.register)dv.component.register(()=>resizeObserver.disconnect());
requestAnimationFrame(fitPane);
// 图1 顶头：Collections + 标题 + 计数/更新，右边一条下划线搜索（问答时这一整块都不动）。
const head = wrap.createEl('div', { cls: 'lbchat-head' });
const titleBlock = head.createEl('div', { cls: 'lbchat-titleblock' });
const titleRow = titleBlock.createEl('div', { cls: 'lbchat-titlerow' });
const titleText = titleRow.createEl('span', { cls: 'lbchat-title', text: 'Collections' });
const tools=head.createEl('div',{cls:'lbchat-tools'});
// 10-04 她定：标题旁的「+」去掉（它开的「导入网址 / 同步 / 账号」菜单和输入框左边的 + 是同一个，留在那边）；
// 「清空」（清空本会话的提问和回答）放在输入框左上方那行来源小字旁边，同款浅色小字按钮——见 paintFollow
let clearBtn = null;
const paintClear = () => { if (clearBtn) clearBtn.disabled = busy || !session.turns.length; };
const sub = titleBlock.createEl('div', { cls: 'lbchat-sub' });
function paintSub(){
  try {
    const t = new Date(data.built_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    sub.setText(`${items.length} 篇 · 更新 ${t}`);
  } catch { sub.setText(`${items.length} 篇`); }
}
paintSub();
const pageNav=head.createEl('nav',{cls:'lb-page-nav'});
const browse=pageNav.createEl('button',{text:'浏览收藏'});browse.onclick=()=>provider().openLibraryPage('catalog');
const ask=pageNav.createEl('button',{text:'问收藏',cls:'is-current'});ask.setAttribute('aria-current','page');
const manage=tools.createEl('button',{cls:'lb-manage',text:'…'});
manage.onclick=e=>provider()?.openAISettingsMenu(e);
// 提问历史 logo：点开看本会话提过的问题，可一键清空
const histBtn=tools.createEl('button',{cls:'lbchat-hist',attr:{'aria-label':'提问历史',title:'提问历史'}});
histBtn.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l3.5 2"/></svg>';
histBtn.onclick=e=>{e.stopPropagation();toggleHistory(histBtn);};
const composer=wrap.createEl('form',{cls:'lbchat-composer'});
// 0926 Owner：输入框照 Codex 的样子——左「+」、灰字提示（设置里可改）、右边模型下拉 + 麦克风 + 圆形发送。
const cfg=()=>provider()?.settings||{};
const queueEl=wrap.createEl('div',{cls:'lbchat-queue'});
const composerPlus=composer.createEl('button',{cls:'lbchat-cplus',text:'+',attr:{title:'收一条链接 / 导入'}});composerPlus.type='button';
composerPlus.onclick=e=>provider()?.openPlusMenu?.(e);
const search = composer.createEl('textarea', { cls: 'lbchat-search' });
search.rows=1;search.placeholder = cfg().chatPlaceholder || '问点什么呢？'; search.value = typeof pageState.draft === 'string' ? pageState.draft : (session.draft || '');
const modelPick=composer.createEl('select',{cls:'lbchat-model',attr:{title:'回答用的模型（设置 → AI → 问答模型里增删）'}});
const fillModels=()=>{modelPick.empty();const list=(cfg().models||[]).filter(m=>m&&m.name);
  if(!list.length){modelPick.hidden=true;return;}modelPick.hidden=false;
  for(const m of list)modelPick.createEl('option',{text:m.name}).value=m.name;
  modelPick.value=list.some(m=>m.name===cfg().activeModel)?cfg().activeModel:list[0].name;};
fillModels();
modelPick.onchange=async()=>{const p=provider();if(!p)return;p.settings.activeModel=modelPick.value;await p.saveSettings?.();};
// 语音：点一下开始录，再点一下结束；识别结果直接填进输入框（不加 /）。全局按住 CapsLock 也行。
const mic=composer.createEl('button',{cls:'lbchat-mic',attr:{title:'语音提问（再点一次结束）'}});mic.type='button';
mic.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>';
mic.onclick=()=>provider()?.toggleVoice?.({target:search,button:mic});
// 第 3 批：正在作答时多一个「停止」（■）。停掉的是这一问（连同它起的 claude / codex），排队的照常接着问——不想要就点排队那条的 ×
const stop=composer.createEl('button',{cls:'lbchat-stop',attr:{title:'停止生成','aria-label':'停止生成'}});stop.type='button';stop.hidden=true;
stop.innerHTML='<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"/></svg>';
stop.onclick=()=>{const p=provider();if(!p?.stopArchiveAnswer)return;stop.disabled=true;showPhase('正在停止');if(!p.stopArchiveAnswer()){stop.disabled=false;}};
function paintSend(){const on=busy||inFlightElsewhere();stop.hidden=!on;stop.disabled=false;paintClear();}
const send=composer.createEl('button',{cls:'lbchat-send',attr:{title:'发送（回答中会排队）'}});send.type='submit';
send.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
// 回答进行中照常能打字：再发就进队列（像 Codex 追加提问），可点 × 取消，上一条答完自动接着问。
const queued=[];
const drawQueue=()=>{queueEl.empty();queueEl.hidden=!queued.length;queued.forEach((q,i)=>{const row=queueEl.createEl('div',{cls:'lbchat-queued'});
  row.createEl('span',{cls:'lbchat-queued-tag',text:'排队'});row.createEl('span',{cls:'lbchat-queued-text',text:q});
  const now=row.createEl('button',{cls:'lbchat-queued-now',text:'↳ 立即发送',attr:{title:'停掉正在生成的回答，马上问这条'}});now.type='button';now.onclick=()=>sendNow(i);
  const x=row.createEl('button',{cls:'lbchat-queued-x',text:'×',attr:{title:'取消发送'}});x.type='button';x.onclick=()=>{queued.splice(i,1);drawQueue();};});};
// 排队那条「立即发送」（参照 Codex 的「引导」）：挪到队首，停掉当前回答；停下后 submit 的 finally 会从队首接着问它。
function sendNow(i){const [q]=queued.splice(i,1);if(q===undefined)return;queued.unshift(q);drawQueue();
  if(!busy){const next=queued.shift();drawQueue();submit(next);return;}
  const p=provider();stop.disabled=true;showPhase('正在停止');if(!p?.stopArchiveAnswer?.())stop.disabled=false;}
drawQueue();
composer.onsubmit=e=>{e.preventDefault();const v=search.value.trim();if(!v)return;search.value='';saveDraft('');
  if(busy){queued.push(v);drawQueue();return;}submit(v);};

// 第二行：对话/存档 切换 + 同步/浏览/清空
const nav = wrap.createEl('div', { cls: 'lbchat-nav' });
const tabChat = tools.createEl('button', { cls: 'lbchat-tab', text: '对话' });
const tabArch = tools.createEl('button', { cls: 'lbchat-tab', text: '已保存' });


const bodyEl = wrap.createEl('div', { cls: 'lbchat-body' });
// 跟到底（验收第 3 批体验观察）：停在底部时新内容（新一问、阶段字、逐行出字）自动带到眼前；
// 自己往上翻了就不抢，翻回底部又接着跟
let stick = true, drawing = false;
const nearBottom = () => bodyEl.scrollHeight - bodyEl.scrollTop - bodyEl.clientHeight < 48;
const follow = () => { if (stick) bodyEl.scrollTop = bodyEl.scrollHeight; };
// 1003 修「点到来源，问收藏自动回首行」：对话区是页里自己的滚动容器（.lbchat-body）。浏览器把元素摘下再挂上时会把它的滚动位置归零——
// 点「查看」/引用编号第一次开右侧来源窗格，Obsidian 拆分标签页会把本页整个 DOM 挪进新分栏；Dataview 重跑时 reuseDom 把整页摘下再挂回。
// 两种都不是用户在滚。lastTop 只记用户滚动 / 我们自己定的位置；没有用户输入却「归零」了就滚回 lastTop（在底部跟随的回到底部）。
// 「用户在滚」= 最近 400ms 有滚轮 / 触摸 / 按键（连续滚时事件一直来，会一直续上），或正按着对话区的滚动条拖
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
// 挪 DOM 的那一刻和 Obsidian 排版可能差一帧：当下滚回去，下一帧再确认一次
function settle() { keepPlace(); try { requestAnimationFrame(keepPlace); } catch {} }
// 摘下再挂上 / 分栏变窄时对话区尺寸会变：顺带滚回原处（防住 Obsidian 不发 layout-change 的挪法）
try { const ro = new ResizeObserver(() => { if (reset() || stick) keepPlace(); }); ro.observe(bodyEl); dv.component?.register?.(() => ro.disconnect()); } catch {}
// 右侧来源窗格开着时才出现的一行：明确的「退出对照」「收起来源」
const sourceBar = wrap.createEl('div', { cls: 'lbchat-srcbar' });
sourceBar.hidden = true;
function paintSourceBar(){
  const st=provider()?.archiveSourceState?.(root)||{reader:false,compare:false};
  sourceBar.empty();sourceBar.hidden=!st.reader;
  bodyEl.classList.toggle('lbchat-has-reader',!!st.reader);
  if(!st.reader)return;
  sourceBar.createEl('span',{cls:'lbchat-srcbar-label',text:st.compare?'右侧：来源 + 对照':'右侧：来源'});
  if(st.compare){const off=sourceBar.createEl('button',{cls:'lbchat-act',text:'退出对照'});off.type='button';off.onclick=()=>{provider().closeArchiveCompare(root);paintSourceBar();};}
  const close=sourceBar.createEl('button',{cls:'lbchat-act',text:'收起来源'});close.type='button';close.onclick=()=>{provider().closeArchiveSources(root);paintSourceBar();};
}
// ② 追问绑定当前来源：输入框上面一行小字「在当前 N 条来源里追问 · 改为重新搜」，点了才重新检索；状态跟会话一起存
const followBar = wrap.createEl('div', { cls: 'lbchat-followbar' });
followBar.hidden = true;
wrap.append(sourceBar);wrap.append(queueEl);wrap.append(followBar);wrap.append(composer);

// 顶部搜索框 = 唯一输入：回车触发（/ 开头问 AI，否则搜），草稿持久化
search.oninput = () => saveDraft(search.value);
search.onkeydown = e => {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
  e.preventDefault();composer.requestSubmit();
};

// ── 会话渲染 ──
async function drawChat() {
  const scroll=reset()?lastTop:bodyEl.scrollTop, wasStick=stick;
  drawing=true;  // 清空重画时浏览器会把滚动夹回 0 并发 scroll 事件：那不是用户在翻，别据此改跟随
  bodyEl.empty();

  if (!session.turns.length && !busy) {
    bodyEl.createEl('div', { cls: 'lbchat-empty', text: '答案来自你的收藏，参考材料会附在回答下方。' });
  }
  for (const t of session.turns) {
    if (t.role === 'user') {
      const el = bodyEl.createEl('div', { cls: 'lbchat-turn lbchat-user' });
      if (t.mode === 'search') el.createEl('span', { cls: 'lbchat-qmark', text: '搜' });
      if (t.mode === 'reask') el.createEl('span', { cls: 'lbchat-qmark', text: `按留下的 ${t.sources || ''} 条来源重答` });
      if (t.mode === 'follow') el.createEl('span', { cls: 'lbchat-qmark is-follow', text: `在当前 ${t.sources || ''} 条来源里追问` });
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
      bindSources(el,t.sources||[]);
      drawSources(el,t);
      if (!t.failed) {
        const acts = el.createEl('div', { cls: 'lbchat-actions' });
        const copy=acts.createEl('button',{cls:'lbchat-act',text:'复制'});copy.onclick=async()=>{try{await navigator.clipboard.writeText(t.content+'\n\n'+(t.sources||[]).map(sourceText).join('\n\n'));copy.setText('已复制');}catch{copy.setText('复制失败');}};
        const exportOptions=acts.createEl('details',{cls:'lbchat-export'});exportOptions.createEl('summary',{text:'导出'});const imageLabel=exportOptions.createEl('label',{text:'附带原图 '});const bundleImages=imageLabel.createEl('input');bundleImages.type='checkbox';bundleImages.checked=true;
        // R2：导出 = 当前保留的全部来源（删掉的除外）——主要依据全文进包、回答引用过的标引用号；其他相关以胶囊（标题 + 链接 + 命中摘录）写进回答文件
        const used=new Set([...t.content.matchAll(/\[来源(\d+)\]/g)].map(m=>Number(m[1])));
        const gone=new Set(t.removed||[]);
        const currentSources=(t.sources||[]).filter(s=>!gone.has(srcKey(s))).map(s=>({...s,cited:used.has(Number(s.citation))}));
        const keptRelated=(t.related||[]).filter(s=>!gone.has(srcKey(s)));
        const dropped=[...(t.sources||[]),...(t.related||[])].filter(s=>gone.has(srcKey(s)));
        for(const [label,copy] of [['导出资料包',false],['复制文件包',true]]){
          const exportBtn=exportOptions.createEl('button',{cls:'lbchat-act',text:label});
          exportBtn.onclick=async()=>{exportBtn.disabled=true;exportBtn.setText(copy?'复制中…':'导出中…');try{await provider().exportArchiveBundle(currentSources.map(s=>s.id),bundleImages.checked,answerExportMd({...t,sources:currentSources,related:keptRelated,dropped}),{question:t.q||'当前问答',askedAt:t.askedAt||"unknown",copy});}catch(e){window.alert(e.message);}finally{exportBtn.disabled=false;exportBtn.setText(label);}};
        }
        const details=acts.createEl('button',{cls:'lbchat-act',text:'展开重点细节'});details.disabled=busy;details.onclick=()=>submit('请继续展开上一答最相关的重点项，摘录原文重要细节，说明具体机制、触发条件和限制，区分作者说法和评论。');
        if(!t.savedId)t.savedId=archive.entries.find(e=>e.kind==='report'&&e.content===t.content)?.id;
        const saved=()=>archive.entries.some(e=>e.id===t.savedId);
        const save=acts.createEl('button',{cls:'lbchat-act lbchat-bookmark'});
        save.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg><span class="lb-visually-hidden">收藏回答</span>';
        const paintSave=()=>{save.classList.toggle('is-saved',saved());save.setAttribute('aria-pressed',String(saved()));};paintSave();
        save.onclick=async()=>{
          if(save.disabled)return;save.disabled=true;
          const wasSaved=saved(),prevId=t.savedId;
          const ok=await archiveChange(()=>{
            if(wasSaved)archive.entries=archive.entries.filter(e=>e.id!==t.savedId);
            else{t.savedId=uid();archive.entries.unshift({id:t.savedId,ts:new Date().toISOString(),kind:'report',title:t.q||'AI 整理',content:t.content,sources:t.sources||[]});}
          });
          if(!ok)t.savedId=prevId;
          else{await keepSession();notice(wasSaved?'已取消收藏':'已收藏到「已保存」',2500);}
          save.disabled=false;paintSave();
        };
        el.ondblclick=e=>{if(e.target.closest('button,textarea'))return;editText(el,t,async()=>{const stored=archive.entries.find(x=>x.id===t.savedId);if(stored){const prev=stored.content;stored.content=t.content;try{await saveArchive();}catch(e){stored.content=prev;throw e;}}await saveSession();await drawChat();});};
      }
    }
  }
  // 进度只显示后端真实发来的阶段（检索收藏 / 挑选材料 / 生成回答），没有阶段就「正在生成…」（CONVENTIONS §1.6）
  if (busy || inFlightElsewhere()) {
    const th = bodyEl.createEl('div', { cls: 'lbchat-think' });
    th.createEl('span', { cls: 'lbchat-dot' });
    th.createEl('span', { cls: 'lbchat-phase', text: phaseText() });
  }
  drawing=false; stick=wasStick;
  if (stick) bodyEl.scrollTop = bodyEl.scrollHeight; else bodyEl.scrollTop = scroll;
  paintFollow(); paintClear();
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
// 这一问要不要绑：默认绑（有上一轮且留下了来源）；她点了「改为重新搜」/ 新会话第一问 / 从目录页带词跳来的新问题 → 照常检索
function boundIds() { return session.follow === 'search' ? [] : keptIds(lastAnswer()); }
function paintFollow() {
  followBar.empty(); clearBtn = null;
  const ids = lane === 'chat' ? keptIds(lastAnswer()) : [];
  const bound = session.follow !== 'search';
  followBar.hidden = lane !== 'chat' || !session.turns.length;
  search.placeholder = !session.turns.length ? '搜索你的收藏，或直接提问…' : ids.length && bound ? '在当前来源里继续追问…' : '继续追问…';
  if (followBar.hidden) return;
  if (ids.length) {
    followBar.createEl('span', { cls: 'lbchat-follow-label', text: bound ? `在当前 ${ids.length} 条来源里追问` : '追问会重新搜索收藏' });
    followBar.createEl('span', { cls: 'lbchat-follow-sep', text: '·' });
    const sw = followBar.createEl('button', { cls: 'lbchat-follow-switch', text: bound ? '改为重新搜' : '改回当前来源', attr: { title: bound ? '下一问起重新检索整个收藏（不再只看上面这些来源）' : '追问只在上一轮留下的来源里回答，不重新检索', 'aria-pressed': String(!bound) } });
    sw.type = 'button';
    sw.onclick = async () => { session.follow = bound ? 'search' : 'sources'; paintFollow(); await keepSession(); };
    followBar.createEl('span', { cls: 'lbchat-follow-sep', text: '·' });
  }
  clearBtn = followBar.createEl('button', { cls: 'lbchat-follow-switch lbchat-clearall', text: '清空', attr: { title: '清空本会话的提问和回答（已保存的不受影响）' } });
  clearBtn.type = 'button';
  clearBtn.onclick = () => clearSession();
  paintClear();
}
// ① 清空本会话（标题旁的「清空」和提问历史里的「一键清空」是同一个）：先确认；写盘失败就原样放回
async function clearSession() {
  if (busy || !session.turns.length) return false;
  if (!window.confirm('清空本会话所有提问和回答？（已保存的回答不受影响）')) return false;
  const prev = { turns: session.turns, excluded: session.excluded, pinned: session.pinned, follow: session.follow };
  session.turns = []; session.excluded = []; session.pinned = []; session.follow = 'sources';
  try { await saveSession(); } catch (e) { Object.assign(session, prev); notice('没清空：' + errText(e)); return false; }
  saveDraft(''); lastTop = 0; stick = true; LB.state.patch({ scrollTop: 0 });
  await drawChat();
  return true;
}

async function drawArchive() {
  bodyEl.empty(); followBar.hidden = true;

  const addRow = bodyEl.createEl('div', { cls: 'lbchat-arc-add' });
  const ta = addRow.createEl('textarea', { cls: 'lbchat-arc-input' });
  ta.placeholder = '写一条自己的判断存起来（如「ib 机不适合」）…';
  const saveIt = addRow.createEl('button', { cls: 'lbchat-arc-save', text: '存' });
  saveIt.onclick = async () => {
    const txt = ta.value.trim(); if (!txt) return;
    // 写盘成功才清输入框；失败字留在框里（§1.5）
    if (!(await archiveChange(() => archive.entries.unshift({ id: uid(), ts: new Date().toISOString(), kind: 'note', title: '', content: txt })))) return;
    ta.value = ''; await drawArchive(); notice('已保存', 2000);
  };
  if (!archive.entries.length) { bodyEl.createEl('div', { cls: 'lbchat-empty', text: '还没有保存的内容。可以保存回答，或在上面记下自己的判断。' }); return; }
  for (const e of archive.entries) {
    const item = bodyEl.createEl('div', { cls: 'lbchat-arc-item' });
    const meta = item.createEl('div', { cls: 'lbchat-arc-meta' });
    meta.createEl('span', { cls: 'lbchat-arc-kind', text: e.kind === 'note' ? '判断' : 'AI 报告' });
    meta.createEl('span', { text: fmtTs(e.ts) + (e.title ? ' · ' + e.title : '') });
    const edit=meta.createEl('button',{cls:'lbchat-act',text:'编辑'});edit.onclick=()=>editText(item,e,async()=>{await saveArchive();await drawArchive();});
    const del = meta.createEl('button', { cls: 'lbchat-arc-del', text: '✕' });
    del.onclick = async () => { if (await archiveChange(() => { archive.entries = archive.entries.filter(x => x.id !== e.id); })) { await drawArchive(); notice('已删除', 2000); } };
    const b = item.createEl('div', { cls: 'lbchat-arc-body' });
    try { await provider().renderMarkdownInto(e.content, b); } catch { b.setText(e.content); }
    bindSources(b,e.sources||[]);
  }
}
// ── 回答下面的来源（第 10 批）：按相关度分两档——「主要依据」= 送进模型的那些（带 [来源N]），「其他相关」= 候选池其余（默认收起）。
// 每条可 × 删掉（记在这一轮的 removed 里，跟会话一起存）；删过之后出现「按剩下的重新回答」：只用留下的来源再答一次，不重新检索。
const srcKey = s => s.id || s.note || s.title;
function drawSources(el, t) {
  const primary = t.sources || [], related = t.related || [];
  if (!primary.length && !related.length) return;
  const removed = new Set(t.removed || []);
  // × = 本会话排除（可恢复）：记进这一轮的 removed（显示），也记进会话的 excluded（之后追问 / 重答都不再用）；排除压过保留
  const remove = async src => { const k = srcKey(src); t.removed = [...removed, k]; session.excluded = idList([...session.excluded, k]); session.pinned = session.pinned.filter(x => x !== k); await keepSession(); await drawChat(); };
  // 保留（pin）：这篇在本会话之后的追问 / 重答里一直带上；不锁死搜索范围，新来源照样能进
  const togglePin = async src => { const k = src.id; session.pinned = session.pinned.includes(k) ? session.pinned.filter(x => x !== k) : idList([...session.pinned, k]); session.excluded = session.excluded.filter(x => x !== k); await keepSession(); await drawChat(); };
  // 10-04 ⑥：每条来源一行（标题 + 右边一排按钮），「保留」和「×」是同样醒目的小按钮，已保留的实心带 ✓
  const row = (box, src, label, full) => {
    const line = box.createEl('div', { cls: 'lbchat-srcrow' });
    const a = line.createEl('a', { text: label });
    const where = evidenceWhere(src);
    if (where) a.setAttribute('title', '命中：' + where);
    a.onclick = () => openNote(src);
    const acts = line.createEl('span', { cls: 'lbchat-srcrow-acts' });
    const view = acts.createEl('button', { cls: 'lbchat-act', text: '查看' }); view.type = 'button'; view.onclick = () => openNote(src);
    if (full) {
      // 右侧已经开着来源时才有「加入对照」（没有来源可对照时不出现，免得第一次和第二次点行为不同）
      const compare = acts.createEl('button', { cls: 'lbchat-act lbchat-addcmp', text: '加入对照' }); compare.type = 'button'; compare.onclick = () => openNote(src, true);
      const copySource = acts.createEl('button', { cls: 'lbchat-act', text: '复制来源' }); copySource.onclick = async () => { await navigator.clipboard.writeText(sourceText(src)); copySource.setText('已复制'); };
    }
    if (!busy && src.id) { const on = session.pinned.includes(src.id); const pin = acts.createEl('button', { cls: 'lbchat-act lbchat-src-pin' + (on ? ' is-on' : ''), text: on ? '已保留' : '保留', attr: { title: on ? '取消保留' : '本会话后面的追问 / 重答都带上这篇（可取消）', 'aria-pressed': String(on) } }); pin.type = 'button'; pin.onclick = () => togglePin(src); }
    if (!busy && srcKey(src)) { const x = acts.createEl('button', { cls: 'lbchat-act lbchat-src-del', text: '×', attr: { title: '从来源里删掉（本会话不再用，可恢复）' } }); x.type = 'button'; x.onclick = () => remove(src); }
  };
  // 收起时 summary 后面的浅色小字（默认仍收起，她 10-03 验收过）；展开就不再提示
  const summaryOf = (box, text, list, hint) => {
    const s = box.createEl('summary'); s.appendText(text);
    const kept = list.filter(x => x.id && session.pinned.includes(x.id)).length;
    if (kept) s.createEl('span', { cls: 'lbchat-src-kept', text: `已保留 ${kept}` });
    if (hint && !busy) s.createEl('span', { cls: 'lbchat-src-hint', text: '点开可保留 / 删除来源' });
  };
  const keptPrimary = primary.filter(s => !removed.has(srcKey(s))), keptRelated = related.filter(s => !removed.has(srcKey(s)));
  let hinted = false;
  if (keptPrimary.length || !related.length) {
    const refs = el.createEl('details', { cls: 'lbchat-src' });
    summaryOf(refs, related.length ? `主要依据 · ${keptPrimary.length}` : `参考材料 · ${keptPrimary.length}`, keptPrimary, hinted = keptPrimary.length > 0);
    for (const src of keptPrimary) row(refs, src, `[来源${src.citation}] ${src.title}`, true);
  }
  if (keptRelated.length) {
    const more = el.createEl('details', { cls: 'lbchat-src lbchat-src-more' });
    summaryOf(more, `其他相关 · ${keptRelated.length}`, keptRelated, !hinted);
    for (const src of keptRelated) row(more, src, src.title, false);
  }
  if (removed.size) {
    const bar = el.createEl('div', { cls: 'lbchat-actions lbchat-src-redo' });
    // 保留过的（含前几轮的）排最前，一起交给重答；删掉的不在里面
    const kept = [...keptPrimary, ...keptRelated].map(s => s.id).filter(Boolean);
    const keep = [...new Set([...session.pinned.filter(k => !removed.has(k)), ...kept])];
    const redo = bar.createEl('button', { cls: 'lbchat-act', text: `按剩下的 ${keep.length} 条重新回答` }); redo.type = 'button';
    redo.disabled = busy || !keep.length || !t.q;
    redo.onclick = () => submit(t.q, { sourceIds: keep });
    const undo = bar.createEl('button', { cls: 'lbchat-act', text: `恢复删掉的 ${removed.size} 条` }); undo.type = 'button';
    undo.onclick = async () => { const back = new Set(t.removed || []); t.removed = []; session.excluded = session.excluded.filter(k => !back.has(k)); await keepSession(); await drawChat(); };
  }
}
function fmtTs(ts) { try { const d = new Date(ts); return `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; } catch { return ''; } }

// 换页再回来时上一页还在等回答：插件对象上记一笔（§5.3「进行中的事」），新页面显示「正在生成…」，答完收到事件再重读会话
function inFlightElsewhere(){const f=provider()?.chatInFlight;return !!(f&&f.page!==pageId);}
function phaseText(){const f=provider()?.chatInFlight;return (f&&f.phase?f.phase+'…':'正在生成…');}
function showPhase(text){const p=provider();if(p&&p.chatInFlight)p.chatInFlight.phase=text;const el=bodyEl.querySelector('.lbchat-phase');if(el)el.setText(phaseText());follow();}
const pageId=uid();
// 从目录页带词跳过来要自动问的那一句是新问题：照常检索，不绑上一轮的来源（页面打开时插件上挂着 pendingArchiveQuestion）
let nextFresh = !!provider()?.pendingArchiveQuestion;
// opts.sourceIds（第 10 批「按剩下的重新回答」）：只用这些来源再答一次，不重新检索
// 10-04 ②：没给 sourceIds 时，会话里已有上一轮回答 → 默认只在它留下的来源里答（同一条 sourceIds 通路）；opts.fresh / 「改为重新搜」→ 照常检索
async function submit(raw, opts = {}) {
  const text = (raw || '').trim(); if (!text || busy) return;
  {
    const q = text.replace(/^\//,'').trim(); if (!q) return;
    const askedAt=new Date().toISOString();
    const fresh = !!opts.fresh || nextFresh; nextFresh = false;
    const reask = Array.isArray(opts.sourceIds);
    const bound = !reask && !fresh ? boundIds() : [];
    const pinned = reask ? opts.sourceIds : bound.length ? bound : null;
    session.turns.push({ role: 'user', content: q, mode: reask ? 'reask' : bound.length ? 'follow' : 'ask', askedAt, ...(pinned ? { sources: pinned.length } : {}) });
    await keepSession(); busy = true; stick = true; await drawChat(); follow();
    try {
      const history = session.turns.filter(t => t.role === 'user' || t.role === 'assistant').filter(t => !t.failed)
        .map(t => ({ role: t.role === 'assistant' ? 'assistant' : 'user', content: t.content }));
      const live=bodyEl.createEl('div',{cls:'lbchat-turn lbchat-answer lbchat-live'});
      const p = provider(); if (p) p.chatInFlight = { page: pageId, q };
      paintSend();
      let shown='';
      // 会话级约束显式传给后端（不指望 8 条 history 隐式带到）；没排除 / 没保留时请求和以前一模一样
      const constraints = { ...(session.excluded.length ? { excludeIds: [...session.excluded] } : {}), ...(session.pinned.length && !pinned ? { pinIds: [...session.pinned] } : {}) };
      const r = await p.answerArchive({ question: q, model: modelPick.hidden?'':modelPick.value, history:history.slice(0,-1), ...(pinned ? { sourceIds: pinned } : {}), ...constraints,
        onPhase:showPhase,
        onDelta:delta=>{bodyEl.querySelector('.lbchat-think')?.remove();shown+=delta;live.appendText(delta);follow();} });
      if (r.status === 'cancelled') {
        // 停止：留下已经生成的那半截，明确标「已停止」；算失败轮次（不进追问上下文、不给收藏 / 导出）
        const part = (r.markdown || shown || '').trim();
        session.turns.push({ role: 'assistant', failed: true, stopped: true, content: (part ? part + '\n\n' : '') + '> 已停止生成。', sources: r.sources || [], related: r.related || [], q, askedAt });
      } else session.turns.push({ role: 'assistant', content: r.markdown || '没有可用的回答。', sources: r.sources || [], related: r.related || [], q, askedAt });
    } catch (e) {
      session.turns.push({ role: 'assistant', failed: true, content: '回答失败：' + (e.message || e) + '\n\n请重试。' });
    } finally {
      busy = false; paintSend(); await keepSession();
      const p = provider(); if (p && p.chatInFlight?.page === pageId) { delete p.chatInFlight; app.workspace.trigger?.('link-brain:chat-session', pageId); }
      await drawChat(); if(queued.length){const next=queued.shift();drawQueue();submit(next);}
    }
  }
}

// ── 栏切换 / 清空 ──（顶头 Collections+ 标题 + 搜索始终不动；只切换下面的正文）
async function setLane(next) {
  lane = next;
  tabChat.classList.toggle('is-on', lane === 'chat');
  tabArch.classList.toggle('is-on', lane === 'archive');
  composer.hidden = lane !== 'chat';   // 存档栏用它自己的输入框，顶部搜索只服务对话栏

  if (lane === 'chat') await drawChat(); else await drawArchive();
}
tabChat.onclick = () => setLane('chat');
tabArch.onclick = () => setLane('archive');
await setLane('chat');
paintSend();
LB.t('render');
// 对话区滚动位置（§5.3）：记下来，换页回来恢复；没记过 = 停在最新一轮（底部）
if (Number.isFinite(pageState.scrollTop)) { bodyEl.scrollTop = pageState.scrollTop; stick = nearBottom(); }
else { stick = true; follow(); }
bodyEl.addEventListener?.('scroll', () => {
  if (lane !== 'chat' || drawing || !bodyEl.isConnected) return;
  if (reset()) { keepPlace(); return; }   // 被挪过 DOM 的归零：不记、滚回去
  lastTop = bodyEl.scrollTop; stick = nearBottom(); LB.state.patch({ scrollTop: lastTop });
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
  if (!t || typeof t.closest !== 'function' || bodyEl.contains(t) || t.closest('select') || canScroll(t, e.deltaY)) return;
  userAt = Date.now();
  bodyEl.scrollTop += e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? bodyEl.clientHeight : 1);
  if (lane === 'chat') { lastTop = bodyEl.scrollTop; stick = nearBottom(); }
  e.preventDefault();
}, { passive: false });
LB.t('restore');
paintSourceBar();
if (app.workspace.on && dv.component?.registerEvent) {
  // 用户自己关了右侧窗格：那一行跟着收起
  dv.component.registerEvent(app.workspace.on('layout-change', () => { paintSourceBar(); settle(); }));
  // 别的页面（换页前的那一个）答完了：重读会话再画
  dv.component.registerEvent(app.workspace.on('link-brain:chat-session', from => {
    paintSend();
    if (from === pageId || busy) return;
    app.vault.adapter.read(SESSION_PATH).then(raw => { const next = JSON.parse(raw); if (Array.isArray(next.turns)) { session.turns = next.turns; session.excluded = idList(next.excluded); session.pinned = idList(next.pinned); session.follow = next.follow === 'search' ? 'search' : 'sources'; if (lane === 'chat') drawChat(); } }).catch(() => {});
  }));
}
// 登记这一版 DOM：catalog-data 变了只换数据、改篇数，不重建对话
LB.keep(wrap, { version: await LB.data.version(), update: async () => {
  try { data = await LB.data.load(); items = data.items || []; paintSub(); } catch {}
}, onReuse: () => { paintSourceBar(); paintSend(); settle(); } });
LB.t('total');

// 目录页「去问收藏搜「…」」带词跳过来（R1 修）：以前只在本页第一次画的时候看一眼 pendingArchiveQuestion——问收藏页已经开着时，
// Dataview 重跑走 reuseDom 直接挂回旧页面，这段根本不跑，带过来的词就一直躺着不问。现在三处都接：第一次画完、旧页面挂回时（onReuse）、
// 以及目录页发的 link-brain:ask-pending 事件（页面开在别的标签里）。取走即删，同一个词只问一次；正在回答就排进队列。
function takePending(fromEvent){
  const p=provider(); const q=p&&p.pendingArchiveQuestion; if(!q||typeof q!=='string')return;
  if(root.isConnected===false)return;   // 已经关掉 / 被换走的页面不接
  if(fromEvent&&typeof root.isShown==='function'&&!root.isShown())return;   // 事件只给看得见的那一页接（别的标签里藏着的问收藏页不抢）
  delete p.pendingArchiveQuestion;
  if(lane!=='chat')setLane('chat');
  if(busy){queued.push(q);drawQueue();return;}
  submit(q);
}
LB.container && LB.container.__lbView && (LB.container.__lbView.onReuse = (prev => () => { try { prev && prev(); } finally { takePending(); } })(LB.container.__lbView.onReuse));
if (app.workspace.on && dv.component?.registerEvent) dv.component.registerEvent(app.workspace.on('link-brain:ask-pending', () => takePending(true)));
takePending();

function sourceText(src){
  const absolute=src.markdown_path || (src.note&&app.vault.adapter.getBasePath?app.vault.adapter.getBasePath().replace(/[\\/]$/,'')+'/'+lbPath(src.note):src.agent_md||'');
  return `[来源${src.citation}] ${src.title}\n${src.url||''}\n本地正文：${absolute}`;
}
// ── 机读版导出 ──（回答 + 参考材料原样落成一份 md，扔给 GPT 用）
function tsSlug(){const d=new Date();const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}${p(d.getMonth()+1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;}
async function writeExport(name,md){
  const dir='收藏导出';try{await app.vault.adapter.mkdir(lbPath(dir));}catch{}
  const path=lbPath(`${dir}/${name}.md`);
  await app.vault.adapter.write(path,safeMd(md));
  try{app.workspace.openLinkText(path,'',true);}catch{}
  return path;
}
// 1001 审计 C-2：回答和命中原文都是不可信文本，落成 md 前过插件的清洗（规则在 link_brain/mdsafe.py）
function safeMd(md){const p=provider();return p&&typeof p.neutralizeMarkdown==='function'?p.neutralizeMarkdown(md):md;}
// 证据身份（R2）：评论摘录带楼号（c3 = 第 3 楼，c3.1 = 它下面第 1 条回复，和机读版同一套编号），图片文字带图序号（后端给好的「图2」「评论c5的图1」）
function partWhere(p){
  // 函数里定义（不放顶层 const）：drawChat 在文件读到这里之前就会调到它
  const label={body:'作者正文',comments:'评论',ocr:'图片文字',attachments:'附件正文',transcript:'视频转写',notes:'我的批注'}[p.field]||p.field||'';
  if(p.field==='comments'&&p.comment_labels?.length)return `${label} ${p.comment_labels.join('、')}`;
  if(p.field==='ocr'&&p.images?.length)return `${label}（识别结果） ${p.images.join('、')}`;
  return label;
}
function evidenceWhere(src){return [...new Set((src.excerpts||[]).map(partWhere).filter(Boolean))].join(' · ');}
function answerExportMd(t){
  const L=[`# ${t.q||'AI 整理'}`,'',`> 导出于 ${new Date().toLocaleString('zh-CN')} · 机读版（问收藏）`];
  if(t.q)L.push(`> 提问原话：${t.q}`);
  if(t.dropped?.length)L.push(`> 这一轮删掉的来源（没导出）：${t.dropped.map(s=>s.title).join('、')}`);
  L.push('','## 回答','',t.content,'');
  if(t.sources&&t.sources.length){
    L.push('## 参考材料','');
    for(const s of t.sources){
      L.push(`### [来源${s.citation}] ${s.title}${s.cited===false?'（送进了模型，回答没引用）':''}`);
      if(s.url)L.push(`- 链接：${s.url}`);
      if(s.markdown_path||s.agent_md)L.push(`- 本地机读：${s.markdown_path||s.agent_md}`);
      if(s.note)L.push(`- 本地正文：${s.note}`);
      if(s.excerpts?.length){L.push('','#### 命中原文');for(const p of s.excerpts)L.push(`**${partWhere(p)}**`,'',`> ${String(p.text).replace(/\n/g,'\n> ')}`,'');}
      L.push('');
    }
  }
  if(t.related&&t.related.length){
    L.push('## 其他相关（保留着、没送进模型）','');
    for(const s of t.related){
      L.push(`- ${s.title}${s.url?` · ${s.url}`:''}${s.note?` · 本地正文：${s.note}`:''}`);
      if(s.excerpt)L.push(`  > ${String(s.excerpt).replace(/\n/g,' ')}`);
    }
    L.push('');
  }
  return safeMd(L.join('\n'));
}
// ── 提问历史面板 ──（本会话问过的问题；点一条回填输入框，或一键清空整段对话）
function toggleHistory(anchor){
  document.querySelectorAll('.lbchat-histpanel').forEach(p=>p.remove());
  if(anchor._open){anchor._open=false;return;}
  anchor._open=true;
  const qs=session.turns.filter(t=>t.role==='user');
  const panel=document.body.createEl('div',{cls:'lbchat-histpanel'});
  const headRow=panel.createEl('div',{cls:'lbchat-histhead'});
  headRow.createEl('span',{text:`提问历史 · ${qs.length}`});
  const clr=headRow.createEl('button',{cls:'lbchat-histclear',text:'一键清空'});
  clr.disabled=!session.turns.length||busy;
  clr.onclick=async()=>{if(await clearSession()){panel.remove();anchor._open=false;}};
  if(!qs.length){panel.createEl('div',{cls:'lbchat-histempty',text:'还没有提问'});}
  else for(const t of [...qs].reverse()){const row=panel.createEl('button',{cls:'lbchat-histitem'});row.setText((t.mode==='search'?'🔍 ':'')+t.content);row.onclick=()=>{search.value=t.content;saveDraft(t.content);search.focus();panel.remove();anchor._open=false;};}
  const r=anchor.getBoundingClientRect();
  panel.style.top=(r.bottom+6)+'px';panel.style.left=Math.max(8,Math.min(r.left,window.innerWidth-328))+'px';
  const close=ev=>{if(panel.contains(ev.target)||ev.target===anchor||anchor.contains(ev.target))return;panel.remove();anchor._open=false;document.removeEventListener('click',close);};
  setTimeout(()=>document.addEventListener('click',close),0);
}
function bindSources(el,sources){
  const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
  for(const node of nodes){
    if(node.parentElement.closest('a,code,pre,button'))continue;
    const matches=[...node.textContent.matchAll(/\[来源(\d+)\]/g)];if(!matches.length)continue;
    const frag=document.createDocumentFragment();let last=0;
    for(const m of matches){frag.append(document.createTextNode(node.textContent.slice(last,m.index)));const src=sources.find(x=>Number(x.citation)===Number(m[1]));
      if(src){const b=document.createElement('button');b.className='lbchat-cite';b.textContent=m[0];b.onclick=e=>{e.stopPropagation();openNote(src,false,b.closest('p,li')?.textContent||'');};frag.append(b);}else frag.append(document.createTextNode(m[0]));last=m.index+m[0].length;}
    frag.append(document.createTextNode(node.textContent.slice(last)));node.replaceWith(frag);
  }
  for(const a of el.querySelectorAll('a')){const href=a.getAttribute('data-href')||a.getAttribute('href');const src=sources.find(x=>href===x.url||href===x.note||href===x.note?.replace(/\.md$/,''));if(src)a.onclick=e=>{e.preventDefault();e.stopPropagation();openNote(src);};}
}
function editText(host,entry,save){
  if(host.querySelector('.lbchat-editor'))return;
  const editor=host.createEl('textarea',{cls:'lbchat-editor'});editor.value=entry.content;
  const bar=host.createEl('div',{cls:'lbchat-editbar'});const ok=bar.createEl('button',{text:'保存修改'});const cancel=bar.createEl('button',{text:'取消'});
  // 写盘失败：内容改回原样、编辑框留着（字还在），提示可重试
  ok.onclick=async()=>{const prev=entry.content;entry.content=editor.value;ok.disabled=true;
    try{await save();}catch(e){entry.content=prev;notice(NOT_SAVED+errText(e));}finally{ok.disabled=false;}};
  cancel.onclick=()=>{editor.remove();bar.remove();};editor.focus();
}

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
const saveSession = () => writeJson(SESSION_PATH, { turns: session.turns });
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
.lbchat-answer h1,.lbchat-answer h2,.lbchat-answer h3{font-size:1.15em;line-height:1.6;}
.lbchat button.lbchat-tab{font-size:12px;}.lbchat-src button{margin-right:14px;}
.lbchat-cite{display:inline!important;font:inherit!important;font-size:12px!important;border:0!important;box-shadow:none!important;background:var(--background-secondary)!important;color:var(--link-color);padding:1px 5px!important;height:auto;border-radius:4px;cursor:pointer;}
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
const plus = titleText.createEl('button', { cls: 'lbchat-plus', text: '+' });


plus.onclick = (evt) => {
  const p = provider();
  if (typeof p?.openPlusMenu !== 'function') { try { new Notice('需要启用 Link Brain Actions 插件'); } catch {} return; }
  p.openPlusMenu(evt);
};
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
function paintSend(){const on=busy||inFlightElsewhere();stop.hidden=!on;stop.disabled=false;}
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
wrap.append(sourceBar);wrap.append(queueEl);wrap.append(composer);

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
  search.placeholder=session.turns.length?'继续追问…':'搜索你的收藏，或直接提问…';

  if (!session.turns.length && !busy) {
    bodyEl.createEl('div', { cls: 'lbchat-empty', text: '答案来自你的收藏，参考材料会附在回答下方。' });
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
      bindSources(el,t.sources||[]);
      if (t.sources && t.sources.length) {
        const refs = el.createEl('details', { cls: 'lbchat-src' });
        refs.createEl('summary', { text: `参考材料 · ${t.sources.length}` });
        for (const src of t.sources) {
          const a = refs.createEl('a', { text: `[来源${src.citation}] ${src.title}` });
          a.onclick = () => openNote(src);
          const view=refs.createEl('button',{cls:'lbchat-act',text:'查看'});view.type='button';view.onclick=()=>openNote(src);
          // 右侧已经开着来源时才有「加入对照」（没有来源可对照时不出现，免得第一次和第二次点行为不同）
          const compare=refs.createEl('button',{cls:'lbchat-act lbchat-addcmp',text:'加入对照'});compare.type='button';compare.onclick=()=>openNote(src,true);
          const copySource=refs.createEl('button',{cls:'lbchat-act',text:'复制来源'});copySource.onclick=async()=>{await navigator.clipboard.writeText(sourceText(src));copySource.setText('已复制');};

        }
      }
      if (!t.failed) {
        const acts = el.createEl('div', { cls: 'lbchat-actions' });
        const copy=acts.createEl('button',{cls:'lbchat-act',text:'复制'});copy.onclick=async()=>{try{await navigator.clipboard.writeText(t.content+'\n\n'+(t.sources||[]).map(sourceText).join('\n\n'));copy.setText('已复制');}catch{copy.setText('复制失败');}};
        const exportOptions=acts.createEl('details',{cls:'lbchat-export'});exportOptions.createEl('summary',{text:'导出'});const imageLabel=exportOptions.createEl('label',{text:'附带原图 '});const bundleImages=imageLabel.createEl('input');bundleImages.type='checkbox';bundleImages.checked=true;
        const used=new Set([...t.content.matchAll(/\[来源(\d+)\]/g)].map(m=>Number(m[1])));
        const currentSources=(t.sources||[]).filter(s=>!used.size||used.has(Number(s.citation)));
        for(const [label,copy] of [['导出资料包',false],['复制文件包',true]]){
          const exportBtn=exportOptions.createEl('button',{cls:'lbchat-act',text:label});
          exportBtn.onclick=async()=>{exportBtn.disabled=true;exportBtn.setText(copy?'复制中…':'导出中…');try{await provider().exportArchiveBundle(currentSources.map(s=>s.id),bundleImages.checked,answerExportMd({...t,sources:currentSources}),{question:t.q||'当前问答',askedAt:t.askedAt||"unknown",copy});}catch(e){window.alert(e.message);}finally{exportBtn.disabled=false;exportBtn.setText(label);}};
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
}

async function drawArchive() {
  bodyEl.empty();

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
function fmtTs(ts) { try { const d = new Date(ts); return `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; } catch { return ''; } }

// 换页再回来时上一页还在等回答：插件对象上记一笔（§5.3「进行中的事」），新页面显示「正在生成…」，答完收到事件再重读会话
function inFlightElsewhere(){const f=provider()?.chatInFlight;return !!(f&&f.page!==pageId);}
function phaseText(){const f=provider()?.chatInFlight;return (f&&f.phase?f.phase+'…':'正在生成…');}
function showPhase(text){const p=provider();if(p&&p.chatInFlight)p.chatInFlight.phase=text;const el=bodyEl.querySelector('.lbchat-phase');if(el)el.setText(phaseText());follow();}
const pageId=uid();
async function submit(raw) {
  const text = (raw || '').trim(); if (!text || busy) return;
  {
    const q = text.replace(/^\//,'').trim(); if (!q) return;
    const askedAt=new Date().toISOString();
    session.turns.push({ role: 'user', content: q, mode: 'ask', askedAt });
    await keepSession(); busy = true; stick = true; await drawChat(); follow();
    try {
      const history = session.turns.filter(t => t.role === 'user' || t.role === 'assistant').filter(t => !t.failed)
        .map(t => ({ role: t.role === 'assistant' ? 'assistant' : 'user', content: t.content }));
      const live=bodyEl.createEl('div',{cls:'lbchat-turn lbchat-answer lbchat-live'});
      const p = provider(); if (p) p.chatInFlight = { page: pageId, q };
      paintSend();
      let shown='';
      const r = await p.answerArchive({ question: q, model: modelPick.hidden?'':modelPick.value, history:history.slice(0,-1),
        onPhase:showPhase,
        onDelta:delta=>{bodyEl.querySelector('.lbchat-think')?.remove();shown+=delta;live.appendText(delta);follow();} });
      if (r.status === 'cancelled') {
        // 停止：留下已经生成的那半截，明确标「已停止」；算失败轮次（不进追问上下文、不给收藏 / 导出）
        const part = (r.markdown || shown || '').trim();
        session.turns.push({ role: 'assistant', failed: true, stopped: true, content: (part ? part + '\n\n' : '') + '> 已停止生成。', sources: r.sources || [], q, askedAt });
      } else session.turns.push({ role: 'assistant', content: r.markdown || '没有可用的回答。', sources: r.sources || [], q, askedAt });
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
    app.vault.adapter.read(SESSION_PATH).then(raw => { const next = JSON.parse(raw); if (Array.isArray(next.turns)) { session.turns = next.turns; if (lane === 'chat') drawChat(); } }).catch(() => {});
  }));
}
// 登记这一版 DOM：catalog-data 变了只换数据、改篇数，不重建对话
LB.keep(wrap, { version: await LB.data.version(), update: async () => {
  try { data = await LB.data.load(); items = data.items || []; paintSub(); } catch {}
}, onReuse: () => { paintSourceBar(); paintSend(); settle(); } });
LB.t('total');

if(provider()?.pendingArchiveQuestion){const q=provider().pendingArchiveQuestion;delete provider().pendingArchiveQuestion;await submit(q);}

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
function answerExportMd(t){
  const L=[`# ${t.q||'AI 整理'}`,'',`> 导出于 ${new Date().toLocaleString('zh-CN')} · 机读版（问收藏）`,'','## 回答','',t.content,''];
  if(t.sources&&t.sources.length){
    L.push('## 参考材料','');
    const labels={body:'作者正文',comments:'评论',ocr:'图片文字',attachments:'附件正文',transcript:'视频转写'};
    for(const s of t.sources){
      L.push(`### [来源${s.citation}] ${s.title}`);
      if(s.url)L.push(`- 链接：${s.url}`);
      if(s.markdown_path||s.agent_md)L.push(`- 本地机读：${s.markdown_path||s.agent_md}`);
      if(s.note)L.push(`- 本地正文：${s.note}`);
      if(s.excerpts?.length){L.push('','#### 命中原文');for(const p of s.excerpts)L.push(`**${labels[p.field]||p.field}**`,'',`> ${String(p.text).replace(/\n/g,'\n> ')}`,'');}
      L.push('');
    }
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
  clr.disabled=!session.turns.length;
  clr.onclick=async()=>{if(!window.confirm('清空本会话所有提问和回答？（已保存的回答不受影响）'))return;const prev=session.turns;session.turns=[];
    try{await saveSession();}catch(e){session.turns=prev;notice('没清空：'+errText(e));return;}
    saveDraft('');panel.remove();anchor._open=false;await drawChat();};
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

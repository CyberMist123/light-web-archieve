// lb-page-lib.js — 收藏页面共用的前导（CONVENTIONS §5）。catalog.py 把它内联在目录页 / 星标页 / 问收藏页的
// dataviewjs 最前面，也拼在 _archive/annotate-view.js（每篇笔记的批注块）最前面；页面脚本只调：
//   const LB = lbPageLib(dv, app, role);          // role: catalog | starred | chat | annotate
//   if (await LB.reuseDom()) return;              // 数据版本没变、上一次的 DOM 还在 → 挂回去，结束（§5.1）
// 背景：Dataview 每 2.5 秒（库里任何一篇 md 变了）就把整块清空重跑。以前每次都重读 5MB 的 catalog-data、
// 重建全部卡片，搜索词、滚动、多选、正在打的字都会丢。现在：
//   - 版本 = catalog-data.json（批注块是 notes.json）的 mtime:size；同一个 Dataview 容器里旧 DOM 原样挂回；
//     版本变了也不重建整页，交给页面的 update() 做增量（卡片按 id 复用）；
//   - 解析好的 catalog-data 缓存在插件对象 catalogCache 上（§5.2），三张页共用，插件没加载时退回每次读；
//   - 页面状态（搜索词、筛选、滚动、多选、草稿）存 sessionStorage['lb:<role>']（§5.3），打开一篇再返回时恢复；
//   - 计时：console.debug('[lb] <页> <阶段> <ms>')（§5.8），最近一次也挂在 window.__lbPerf[role] 上方便验收时读。
// 批次 D 地基（CONVENTIONS §5 / §1.7）：页面挂在 dv.container 后面的兄弟节点 host 上（mountHost）、样式挂 head（style + lb-shared）、
// 提示 / 确认 / 菜单 / 忙碌态 / 手机只读 / 跳页 / 焦点兜底的共用助手。本文件合入后冻结，新共享接口走主审的地基补丁。
// 共用样式（lbPageLib 初始化时注入 head 的 #lb-shared）：颜色变量和插件 styles.css 顶部那块同值（tests/test_css_vars_x13.cjs 锁住）。
// 橙色只给状态字和细条；说明文字保持正文色，前面加「⚠」。
const LB_SHARED_CSS = `
body{--lb-warn:var(--text-warning,var(--color-orange));--lb-warn-bg:var(--background-secondary);--lb-warn-border:var(--background-modifier-border);--lb-danger:var(--text-error);--lb-danger-bg:var(--background-secondary);--lb-ok:var(--text-success,var(--color-green));--lb-star:var(--color-yellow,#d9a21b);}
@supports (color: color-mix(in srgb, red, blue)){body{--lb-warn-bg:color-mix(in srgb,var(--lb-warn) 14%,var(--background-primary));--lb-warn-border:color-mix(in srgb,var(--lb-warn) 35%,var(--background-modifier-border));--lb-danger-bg:color-mix(in srgb,var(--text-error) 12%,var(--background-primary));}}
.lb-page-nav{display:flex;grid-column:2;grid-row:1;gap:2px;padding:4px;background:var(--background-secondary);border-radius:12px;justify-self:center;white-space:nowrap;}
.lb-page-nav button{font:inherit;font-size:13px;border:0!important;box-shadow:none!important;background:transparent!important;color:var(--text-muted);border-radius:9px;padding:9px 16px;height:auto;cursor:pointer;}
.lb-page-nav button.is-current{background:var(--background-primary)!important;color:var(--text-normal);box-shadow:0 1px 4px #0000000c!important;font-weight:500;}
.lb-manage{font-size:24px!important;font-weight:500;background:transparent!important;border:0!important;box-shadow:none!important;color:var(--text-muted);padding:0!important;width:40px;height:40px;border-radius:10px;cursor:pointer;font-family:Arial,sans-serif!important;line-height:1!important;display:grid;place-items:center;}
.lb-manage:hover{background:var(--background-secondary)!important;color:var(--text-normal);}
.lb-page-host button:focus-visible,.lbc-wrap button:focus-visible,.lbchat button:focus-visible{outline:2px solid var(--interactive-accent)!important;outline-offset:3px;}
.lb-visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
.lb-mobile-note{font-size:12px;line-height:1.5;color:var(--text-muted);margin:0 0 10px;}
.is-busy{cursor:progress;}
.lb-busy-veil{position:absolute;inset:0;z-index:3;display:grid;place-items:center;border-radius:inherit;background:var(--background-primary);opacity:.85;color:var(--text-muted);font-size:12px;cursor:progress;}
`;
function lbPageLib(dv, app, role) {
  const G = typeof globalThis !== 'undefined' ? globalThis : {};
  const clock = () => (G.performance && typeof G.performance.now === 'function' ? G.performance.now() : Date.now());
  const started = clock();
  let last = started;
  const container = dv && dv.container;
  // Dataview 页里 document / window / Notice 都是全局；node 单测（tests/_fakedom.cjs）把它们当参数传进来
  const doc = (typeof document !== 'undefined' && document) || G.document || null;
  const win = (typeof window !== 'undefined' && window) || G.window || null;
  const NoticeCls = (typeof Notice === 'function' && Notice) || (typeof G.Notice === 'function' && G.Notice) || null;
  const perf = (G.__lbPerf = G.__lbPerf || {});
  const marks = [];
  perf[role] = { at: Date.now(), marks };
  // 计时：每一段记「距上一个点」的毫秒数；total 记从开跑到现在
  function t(label) {
    const now = clock();
    const ms = Math.round(now - (label === 'total' ? started : last));
    if (label !== 'total') last = now;
    marks.push([label, ms]);
    try { console.debug(`[lb] ${role} ${label} ${ms}ms`); } catch {}
    return ms;
  }
  // 绝对时刻（距开跑）：给「封面出来了」这种异步终点用
  function mark(label) {
    const ms = Math.round(clock() - started);
    marks.push([label + '@', ms]);
    try { console.debug(`[lb] ${role} ${label} @${ms}ms`); } catch {}
    return ms;
  }

  // 仓根：从本页往上第一个带 _archive 的目录（这个仓可能被挂进别的库的子目录）
  const root = (() => {
    try {
      let d = (dv.current && dv.current()?.file?.folder) || '';
      while (d && !app.vault.getAbstractFileByPath(d + '/_archive')) d = d.includes('/') ? d.slice(0, d.lastIndexOf('/')) : '';
      return d;
    } catch { return ''; }
  })();
  const path = p => (p && root ? `${root}/${p}` : p);

  const PID = 'link-brain-actions';
  const provider = () => app?.plugins?.plugins?.[PID];
  // 手机（X3）：插件是桌面专用，手机上页面只读；需要插件的按钮点了只说这一句
  const mobile = !!(app && app.isMobile);
  const MOBILE_ONLY_TEXT = '手机上只能看：导入、同步、问 AI、收藏要在电脑上用';
  // 插件方法不在（刚部署了新 main.js、旧实例还在内存里）就重载一次插件；正在跑同步 / 导入时不重载，免得打断它
  // 手机上直接说只读（不去 enablePlugin）；插件忙时用插件统一的占用句（busyText）
  async function ensure(method) {
    if (mobile) throw new Error(MOBILE_ONLY_TEXT);
    let p = provider();
    if (typeof p?.[method] === 'function') return p;
    if (p && (p.running || p.importing)) {
      let msg = '';
      try { if (typeof p.busyText === 'function') msg = p.busyText(); } catch {}
      throw new Error(msg || `插件正在跑「${p.running || '导入'}」，等它完成再点`);
    }
    if (!app.plugins?.enablePlugin) throw new Error('请在第三方插件中启用 Link Brain Actions');
    if (p) await app.plugins.disablePlugin(PID);
    await app.plugins.enablePlugin(PID);
    p = provider();
    if (typeof p?.[method] !== 'function') throw new Error('插件未加载，请在第三方插件中启用 Link Brain Actions');
    return p;
  }

  // ── 页面状态（§5.3）：只存可 JSON 化的小对象；sessionStorage 不可用（单测 / 隐私模式）就放内存 ──
  const KEY = 'lb:' + role;
  const mem = (G.__lbState = G.__lbState || {});
  const store = (() => {
    try { const s = G.sessionStorage; if (!s) return null; s.setItem('lb:__probe', '1'); s.removeItem('lb:__probe'); return s; }
    catch { return null; }
  })();
  const state = {
    load() {
      try { const raw = store ? store.getItem(KEY) : mem[KEY]; const v = raw ? JSON.parse(raw) : null; return v && typeof v === 'object' ? v : {}; }
      catch { return {}; }
    },
    save(obj) {
      try {
        const raw = JSON.stringify({ ...obj, ts: Date.now() });
        if (raw.length > 200000) return false;   // 防呆：别把 items 之类的大东西塞进来
        if (store) store.setItem(KEY, raw); else mem[KEY] = raw;
        return true;
      } catch { return false; }
    },
    patch(obj) { return state.save({ ...state.load(), ...obj }); },
  };

  // ── 数据版本（§5.1）+ 解析缓存（§5.2） ──
  const DATA = '_archive/catalog-data.json';
  const fmt = st => (st && st.mtime ? `${st.mtime}:${st.size}` : null);
  // 版本看哪个文件：默认 catalog-data（仓根相对）；批注块传 {abs: notePath}（已经是库内完整路径）
  const where = rel => (rel && typeof rel === 'object' ? rel.abs : path(rel));
  // 同步版：Obsidian 文件索引里的 stat，不等 IO；Dataview 清空容器后马上挂回旧 DOM，中间不让出一帧（不闪、不丢滚动）
  function versionSync(rel = DATA) {
    try { return fmt(app.vault.getAbstractFileByPath(where(rel))?.stat); } catch { return null; }
  }
  // 磁盘版：以它为准（索引里的 stat 可能晚一拍）
  async function version(rel = DATA) {
    try { const st = await app.vault.adapter.stat?.(where(rel)); if (st) return fmt(st); } catch {}
    return versionSync(rel);
  }
  const data = {
    version,
    versionSync,
    async load({ force = false } = {}) {
      const p = provider();
      const v = await version();
      const c = p && p.catalogCache;
      if (!force && c && v && c.version === v && c.root === root && c.data) { t('read(cache)'); return c.data; }
      const raw = await app.vault.adapter.read(path(DATA));
      t('read');
      const parsed = JSON.parse(raw);
      t('parse');
      if (p && v) p.catalogCache = { version: v, root, data: parsed };
      return parsed;
    },
    // 页面刚自己写过数据（点星后 catalog.patch_items 改了 catalog-data）：内存里那份就是磁盘上的新内容 →
    // 把插件缓存的版本和本页登记的版本都推进到 v，下次 Dataview 重跑不再整读（CM3）。dataObj 必须就是缓存里那份对象。
    adopt(v, dataObj) {
      const c = provider()?.catalogCache;
      if (!v || !c || c.root !== root || !dataObj || c.data !== dataObj) return false;
      c.version = v;
      const view = container && container.__lbView;
      if (view && view.role === role) view.version = v;
      return true;
    },
  };
  // 目录数据的生成时刻（catalog.build 每次重写；patch_items 不改它）：目录页和问收藏页的「更新 …」都显示它（F4）
  const dataUpdatedAt = d => (d && typeof d === 'object' && d.built_at ? String(d.built_at) : null);

  // ── 页面挂载点（§5.9，C4）：页面 DOM 挂在 dv.container 后面的兄弟节点 host 上 ──
  // Dataview 重跑只清 container.innerHTML（0.5.68：main.js:19056），碰不到它的兄弟，输入框不失焦、输入法不断。
  // 卸载（Obsidian 重画这一段 / 关页）时 component.register 摘掉 host。批注块不用它（它要挪到左栏图片下面）。
  let hostEl = null;
  function mountHost(cls = '') {
    if (!container || typeof container.after !== 'function' || !doc) return container;
    for (let n = container.nextElementSibling ?? container.nextSibling; n;) {
      const next = n.nextElementSibling ?? n.nextSibling;
      if (n.classList?.contains('lb-page-host') && (n.dataset?.lbRole ?? n.getAttribute?.('data-lb-role')) === role) n.remove();   // 上一个渲染器没卸干净的残留
      else break;
      n = next;
    }
    const host = doc.createElement('div');
    host.className = 'lb-page-host' + (cls ? ' ' + cls : '');
    host.dataset.lbRole = role;
    container.after(host);
    try { dv.component?.register?.(() => host.remove()); } catch {}
    hostEl = host;
    return host;
  }

  // ── 旧 DOM 复用（§5.1） ──
  // keep(el, {version, versionOf, update, onReuse})：页面建好后登记；update(newVersion) 由页面做增量更新
  // 用了 mountHost 的页面会连 host 一起登记，重跑时把 host 挂回 container 后面、el 挂回 host
  function keep(el, opts = {}) {
    if (!container) return;
    container.__lbView = { role, el, host: opts.host || hostEl, version: opts.version ?? null, versionOf: opts.versionOf || DATA, update: opts.update, onReuse: opts.onReuse,
      updating: false, lastError: null };
  }
  // 页面自己刚写过版本文件（批注保存）：把登记的版本跟上，免得下次重跑当成「别处改了」再读一遍
  async function rekeep() {
    const view = container && container.__lbView;
    if (view && view.role === role) view.version = await version(view.versionOf);
  }
  // 同一个标签页里藏着的编辑视图（实时预览）也会把 dataviewjs 跑一遍——阅读模式下它看不见，白读一遍数据、白建一遍卡片。
  // 看不见就先不画，等它真的露出来（切到编辑模式）再让 Dataview 重画这一块。
  async function deferIfHidden() {
    if (!container || typeof container.closest !== 'function') return false;
    if (!container.isConnected) await new Promise(r => (G.requestAnimationFrame || (f => setTimeout(f, 16)))(r));
    const editor = container.closest('.markdown-source-view');
    if (!editor || typeof container.isShown !== 'function' || container.isShown()) return false;
    if (typeof G.ResizeObserver !== 'function' || typeof dv.component?.render !== 'function') return false;
    const ro = new G.ResizeObserver(() => { if (container.isShown()) { ro.disconnect(); dv.component.render(); } });
    ro.observe(editor);
    try { dv.component.register?.(() => ro.disconnect()); } catch {}
    t('deferred(hidden editor)');
    return true;
  }
  // 返回 true = 这一次不用再画了（旧 DOM 已挂回 / 增量更新完 / 在看不见的编辑视图里先不画）
  // 版本语义（批次 D，F4）：update 成功才推进 view.version；失败记 view.lastError、保留旧版本，下次重跑重试；
  // view.updating 是进行中锁——两次重跑叠在一起时只做一次 update。
  async function reuseDom() {
    if (await deferIfHidden()) return true;
    const view = container && container.__lbView;
    if (!view || view.role !== role || !view.el) return false;
    if (view.host) {
      // 挂在 host 上的页：host 被摘了（少见）就挂回 container 后面；el 始终在 host 里
      if (!view.host.isConnected && container.isConnected && typeof container.after === 'function') container.after(view.host);
      if (view.el.parentNode !== view.host) view.host.append(view.el);
    } else if (!view.el.isConnected && view.el.parentNode !== container) container.append(view.el);   // 批注框挪在左栏就留在原处；被 Dataview 清空摘下来的挂回本容器
    t('reuse');
    const v = await version(view.versionOf);
    if (v && view.version && v !== view.version && typeof view.update === 'function') {
      if (view.updating) { t('total'); return true; }
      view.updating = true;
      const before = view.version;
      try {
        await view.update(v);
        if (view.version === before) view.version = v;   // update 自己推进过（rekeep / adopt）就以它为准
        view.lastError = null;
      } catch (e) {
        view.lastError = e;
        try { console.debug('[lb] ' + role + ' update failed (will retry on next rerun)', e); } catch {}
      } finally { view.updating = false; }
      t('update');
    } else {
      if (v && !view.version) view.version = v;
      try { view.onReuse?.(); } catch {}
    }
    t('total');
    return true;
  }

  // ── 全局监听去重：同一个 key 只留最新一份，组件卸载时摘掉（代替 window.__lbcEsc 这类挂钩） ──
  // opts：addEventListener 的第三个参数（如 {capture: true}）；摘的时候用同一个
  function listen(key, target, type, fn, opts) {
    const reg = (G.__lbListeners = G.__lbListeners || {});
    const k = role + ':' + key;
    const prev = reg[k];
    if (prev) { try { prev.target.removeEventListener(prev.type, prev.fn, prev.opts); } catch {} }
    target.addEventListener(type, fn, opts);
    reg[k] = { target, type, fn, opts };
    try { dv.component?.register?.(() => { if (reg[k]?.fn === fn) { target.removeEventListener(type, fn, opts); delete reg[k]; } }); } catch {}
  }

  // ── 滚动：阅读视图里滚的是整个 .markdown-preview-view；记住位置，回来时等内容长够了再滚回去 ──
  function scroller() {
    try { return container?.closest?.('.markdown-preview-view, .cm-scroller') || null; } catch { return null; }
  }
  // 封面图懒加载、内容逐步长高：最多试 maxMs；用户自己动了滚轮 / 键盘就不再抢
  // 恢复后再「守」一小会儿：Obsidian 后退时会按它自己记的位置（按行算，对整页一个代码块的目录页就是 0）再滚一次，把我们恢复的冲掉
  // 1003：用户动一下就放手——滚轮 / 触摸 / 按住滚动条在滚动容器上；键盘在整页任何地方（焦点常在正文 body 上，不在滚动容器里）。
  // 同一个滚动容器上新起一次恢复先停掉上一次（以前两个循环会每帧轮流把 scrollTop 设成各自的值）；结束时摘掉自己的监听。
  let restoring = false;
  function restoreScroll(top, { maxMs = 2500, holdMs = 1200 } = {}) {
    const el = scroller();
    if (!el || !(top > 0)) return Promise.resolve(false);
    try { el.__lbRestoreStop?.(); } catch {}
    return new Promise(resolve => {
      const until = clock() + maxMs;
      let stop = false, reachedAt = 0, finished = false;
      const quit = () => { stop = true; };
      const doc = typeof document !== 'undefined' ? document : G.document;
      const on = [[el, 'wheel'], [el, 'touchstart'], [el, 'pointerdown'], [el, 'keydown'], [doc, 'keydown']].filter(([t]) => t && typeof t.addEventListener === 'function');
      for (const [t, type] of on) { try { t.addEventListener(type, quit, { passive: true }); } catch {} }
      el.__lbRestoreStop = quit;
      const raf = G.requestAnimationFrame || (fn => setTimeout(fn, 16));
      const done = ok => {
        if (finished) return; finished = true;
        for (const [t, type] of on) { try { t.removeEventListener(type, quit); } catch {} }
        if (el.__lbRestoreStop === quit) { delete el.__lbRestoreStop; restoring = false; }
        resolve(ok);
      };
      restoring = true;
      const step = () => {
        if (stop) return done(reachedAt > 0);
        const now = clock();
        if (Math.abs(el.scrollTop - top) > 2) el.scrollTop = top;
        if (!reachedAt && Math.abs(el.scrollTop - top) <= 2) { reachedAt = now; mark('scroll-restored'); }
        if ((reachedAt && now - reachedAt > holdMs) || now > until) return done(reachedAt > 0);
        raf(step);
      };
      step();
    });
  }
  function onScroll(fn) {
    const el = scroller();
    if (!el) return;
    let queued = false;
    const raf = G.requestAnimationFrame || (f => setTimeout(f, 16));
    // 同一个标签页里换成别的笔记时 Obsidian 复用这个滚动容器、把它滚回 0：那不是本页的滚动，不记
    const mine = () => !!(container && container.isConnected && el.contains(container));
    const handler = () => { if (queued || restoring || !mine()) return; queued = true; raf(() => { queued = false; if (mine() && !restoring) fn(el.scrollTop); }); };
    listen('scroll', el, 'scroll', handler);
  }

  // ── 样式挂 head（X14，§5.10）：按 id 建一个 <style>，文本不同才替换；没有 head（极简环境）挂到 container ──
  function style(id, css) {
    css = String(css ?? '');
    let el = null;
    if (doc && doc.head) {
      el = (typeof doc.getElementById === 'function' && doc.getElementById(id)) || null;
      if (!el) { el = doc.createElement('style'); el.setAttribute('id', id); doc.head.appendChild(el); }
    } else if (container) {
      el = [...(container.querySelectorAll?.('style') || [])].find(s => s.getAttribute?.('id') === id) || null;
      if (!el) { el = (doc || container.ownerDocument)?.createElement?.('style') || null; if (!el) return null; el.setAttribute('id', id); container.append(el); }
    }
    if (el && el.textContent !== css) el.textContent = css;
    return el;
  }
  try { style('lb-shared', LB_SHARED_CSS); } catch {}

  // ── 提示（X6，§1.7）：优先插件 notify（同一套时长 / 按钮）；插件不在时 new Notice；单测里没有 Notice 就记进 globalThis.__lbNotices ──
  // actions: [{label, run}]（点了先关提示再 run）。默认时长：成功 / 普通 3 秒，失败 / 警示 8 秒；ms=0 常驻。
  function record(msg, opts) { const list = (G.__lbNotices = G.__lbNotices || []); const n = { message: msg, ...opts, hidden: false, setMessage(m) { n.message = m; }, hide() { n.hidden = true; } }; list.push(n); return n; }
  function say(msg, { kind = 'info', ms, actions } = {}) {
    msg = String(msg ?? '');
    const list = Array.isArray(actions) ? actions.filter(a => a && a.label) : [];
    const dur = ms ?? (kind === 'error' || kind === 'warn' || list.length ? 8000 : 3000);
    const p = provider();
    if (typeof p?.notify === 'function') { try { return p.notify(msg, { kind, ms: dur, actions: list }); } catch {} }
    if (!NoticeCls) return record(msg, { kind, ms: dur, actions: list });
    const runAction = a => Promise.resolve().then(() => a.run?.()).catch(err => say(err?.message || String(err), { kind: 'error' }));
    try {
      // Obsidian 1.14 的 Notice 自带 addButton（点了先 hide 再回调）；老版本没有就用 DocumentFragment 自己放按钮
      if (list.length && typeof NoticeCls.prototype?.addButton === 'function') {
        const n = new NoticeCls(msg, dur);
        for (const a of list) n.addButton(a.label, () => runAction(a));
        return n;
      }
      if (list.length && doc && typeof doc.createDocumentFragment === 'function') {
        let n = null;
        const frag = doc.createDocumentFragment();
        const text = doc.createElement('div'); text.className = 'lb-notice-text'; text.textContent = msg; frag.appendChild(text);
        const row = doc.createElement('div'); row.className = 'lb-notice-actions'; frag.appendChild(row);
        for (const a of list) {
          const b = doc.createElement('button'); b.textContent = a.label; b.className = 'lb-notice-btn';
          b.addEventListener('click', e => { try { e?.preventDefault?.(); e?.stopPropagation?.(); } catch {} try { n?.hide?.(); } catch {} runAction(a); });
          row.appendChild(b);
        }
        n = new NoticeCls(frag, dur);
        return n;
      }
      return new NoticeCls(msg, dur);
    } catch { return record(msg, { kind, ms: dur, actions: list }); }
  }
  // 进行中提示：常驻，set 换成后端真实阶段，hide 收起（结束后再 say 一句结果）
  function progress(msg) {
    const n = say(msg, { kind: 'info', ms: 0 });
    return { set(m) { try { n?.setMessage?.(String(m ?? '')); } catch {} }, hide() { try { n?.hide?.(); } catch {} } };
  }
  // 删了 / 清空了之后的「撤销」：同一时刻只留最新一个；撤销失败（抛错或返回 false）照固定句式说原因（§1.5）
  function undoNotice(msg, onUndo, ms = 6000) {
    try { G.__lbUndoNotice?.hide?.(); } catch {}
    const n = say(msg, { kind: 'ok', ms, actions: [{ label: '撤销', run: async () => {
      try { const r = await onUndo?.(); if (r === false) throw new Error('撤销没完成'); }
      catch (e) { say('没保存上，内容还在，可重试：' + (e?.message || String(e)), { kind: 'error' }); }
    } }] });
    const handle = { hide() { try { n?.hide?.(); } catch {} if (G.__lbUndoNotice === handle) G.__lbUndoNotice = null; } };
    G.__lbUndoNotice = handle;
    return handle;
  }
  // 确认框：插件的 Obsidian 风格 Modal（Enter 确定、Esc 取消）；插件不在（手机 / 没启用）才退回浏览器自带的 confirm
  async function confirm({ title = '确定吗？', body = '', ok = '确定', cancel = '取消', danger = false } = {}) {
    const p = provider();
    if (typeof p?.confirm === 'function') { try { return !!(await p.confirm({ title, body, ok, cancel, danger })); } catch { return false; } }
    // 全仓唯一允许的浏览器自带确认框（tests/test_no_native_dialogs.cjs 只放行这里）
    try { return typeof window !== 'undefined' && typeof window.confirm === 'function' ? !!window.confirm(title + (body ? '\n\n' + body : '')) : !!win?.confirm?.(title + (body ? '\n\n' + body : '')); } catch { return false; }
  }
  // 发起处的「正在…」：按钮禁用换字；卡片 / 区块加 .is-busy 和一层 .lb-busy-veil。done(finalText?, holdMs?) 恢复原样（给了 finalText 先显示它 holdMs 毫秒）
  function busy(el, text = '') {
    if (!el) return () => {};
    const isButton = el.tagName === 'BUTTON';
    const prevNodes = isButton ? [...(el.childNodes || [])] : null, prevDisabled = !!el.disabled;
    let veil = null, finished = false;
    el.classList?.add('is-busy'); el.setAttribute?.('aria-busy', 'true');
    if (isButton) { el.disabled = true; if (text) el.textContent = text; }
    else if (doc) { veil = doc.createElement('div'); veil.className = 'lb-busy-veil'; veil.textContent = text; el.append(veil); }
    const restore = () => {
      if (isButton) { el.textContent = ''; el.append(...prevNodes); el.disabled = prevDisabled; }
      veil?.remove(); el.classList?.remove('is-busy'); el.removeAttribute?.('aria-busy');
    };
    return (finalText, holdMs = 1200) => {
      if (finished) return; finished = true;
      if (!finalText) return restore();
      if (isButton) el.textContent = finalText; else if (veil) veil.textContent = finalText;
      setTimeout(restore, holdMs);
    };
  }

  // ── 手机与跳页（X3）──
  // 缺插件或缺方法：先说一句（手机：只读；电脑：请启用 / 版本对不上），返回 null。同步、不重载插件（要自动重载用 ensure）
  function need(method) {
    const p = provider();
    if (typeof p?.[method] === 'function') return p;
    if (mobile) say(MOBILE_ONLY_TEXT, { kind: 'info' });
    else if (!p) say('请在「设置 → 第三方插件」里启用 Link Brain Actions', { kind: 'error' });
    else say('插件版本对不上：在「第三方插件」里重新加载 Link Brain Actions', { kind: 'error' });
    return null;
  }
  // 手机上往页首插一次浅色小字（各页可传自己的话）；电脑上什么都不做
  function mobileNote(host, text = MOBILE_ONLY_TEXT) {
    if (!mobile || !host || !doc) return null;
    let el = [...(host.children || [])].find(c => c.classList?.contains('lb-mobile-note')) || null;
    if (!el) { el = doc.createElement('div'); el.className = 'lb-mobile-note'; host.prepend(el); }
    if (el.textContent !== text) el.textContent = text;
    return el;
  }
  // 跳到目录 / 问收藏 / 已收藏 / 回收站：不靠插件——在仓根那一层按 frontmatter 的 lb-page 找文件，openLinkText（同一窗格，§5.4）
  async function openPage(target) {
    try {
      const files = app?.vault?.getMarkdownFiles?.() || [];
      for (const f of files) {
        const folder = f.parent ? (f.parent.path === '/' ? '' : f.parent.path) : (f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : '');
        if (folder !== root) continue;
        if (app.metadataCache?.getFileCache?.(f)?.frontmatter?.['lb-page'] !== target) continue;
        await app.workspace.openLinkText(f.path, '', false);
        return true;
      }
    } catch {}
    say('还没有这个页面：在电脑上点「…→刷新目录」生成', { kind: 'info' });
    return false;
  }

  // ── 菜单（X15）：插件的 obsidian.Menu（自带 Esc / 方向键）；插件不在返回 null，页面自己处理 ──
  // menuOpen：菜单关掉后延一拍才变回 false，页面全局 Esc 先判它（同一次 Esc 不当成菜单外的 Esc）
  function showMenu(items, evt) { const p = provider(); return typeof p?.showMenu === 'function' ? p.showMenu(items, evt) : null; }
  const menuOpen = () => !!provider()?.menuOpen;

  // ── 焦点兜底（C4）：整页重建（新容器）后 3 秒内把焦点和选区还给同一个输入框 ──
  function trackFocus(input, key) {
    if (!input || typeof input.addEventListener !== 'function') return;
    const save = () => { try { state.patch({ focus: key, selStart: input.selectionStart ?? null, selEnd: input.selectionEnd ?? null, focusAt: Date.now() }); } catch {} };
    for (const type of ['focus', 'focusin', 'input', 'keyup', 'select']) input.addEventListener(type, save);
    input.addEventListener('blur', e => {
      const to = e && e.relatedTarget;
      const scope = (container && container.__lbView && container.__lbView.host) || hostEl || container;
      if (to && scope && typeof scope.contains === 'function' && scope.contains(to)) return;
      // 被整页重建摘掉（不是她点走）不清：等一拍看它还在不在文档里
      setTimeout(() => { try { if (input.isConnected && state.load().focus === key) state.patch({ focus: null }); } catch {} }, 0);
    });
  }
  function restoreFocus(input, key, withinMs = 3000) {
    const st = state.load();
    if (!input || st.focus !== key || !(Date.now() - (Number(st.focusAt) || 0) < withinMs)) return false;
    try { input.focus({ preventScroll: true }); } catch { try { input.focus(); } catch { return false; } }
    try { if (st.selStart != null && typeof input.setSelectionRange === 'function') input.setSelectionRange(st.selStart, st.selEnd ?? st.selStart); } catch {}
    return true;
  }
  // 元素在文档里、看得见，并且在当前活动标签页（activeLeaf）的容器里：快捷键只给「她正在看的那一页」
  function activeLeafHas(el) {
    try {
      if (!el || !el.isConnected) return false;
      const shown = typeof el.isShown === 'function' ? el.isShown() : (typeof el.getClientRects === 'function' ? el.getClientRects().length > 0 : true);
      if (!shown) return false;
      const leaf = app?.workspace?.activeLeaf;
      const box = leaf?.view?.containerEl || leaf?.containerEl;
      return !!(box && typeof box.contains === 'function' && box.contains(el));
    } catch { return false; }
  }

  return { root, path, provider, ensure, state, data, keep, rekeep, reuseDom, listen, scroller, restoreScroll, onScroll, t, mark, role, container,
    // 批次 D 地基
    mountHost, style, dataUpdatedAt, mobile, MOBILE_ONLY_TEXT, mobileNote, need, openPage,
    say, progress, undoNotice, confirm, busy, showMenu, menuOpen, trackFocus, restoreFocus, activeLeafHas };
}

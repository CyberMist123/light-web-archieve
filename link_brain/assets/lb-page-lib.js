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
function lbPageLib(dv, app, role) {
  const G = typeof globalThis !== 'undefined' ? globalThis : {};
  const clock = () => (G.performance && typeof G.performance.now === 'function' ? G.performance.now() : Date.now());
  const started = clock();
  let last = started;
  const container = dv && dv.container;
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
  // 插件方法不在（刚部署了新 main.js、旧实例还在内存里）就重载一次插件；正在跑同步 / 导入时不重载，免得打断它
  async function ensure(method) {
    let p = provider();
    if (typeof p?.[method] === 'function') return p;
    if (p && (p.running || p.importing)) throw new Error(`插件正在跑「${p.running || '导入'}」，等它完成再点`);
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
  };

  // ── 旧 DOM 复用（§5.1） ──
  // keep(el, {version, versionOf, update, onReuse})：页面建好后登记；update(newVersion) 由页面做增量更新
  function keep(el, opts = {}) {
    if (!container) return;
    container.__lbView = { role, el, version: opts.version ?? null, versionOf: opts.versionOf || DATA, update: opts.update, onReuse: opts.onReuse };
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
  async function reuseDom() {
    if (await deferIfHidden()) return true;
    const view = container && container.__lbView;
    if (!view || view.role !== role || !view.el) return false;
    // 已经被挪到别处（批注框在左栏）就留在原处；被 Dataview 清空摘下来的挂回本容器
    if (!view.el.isConnected && view.el.parentNode !== container) container.append(view.el);
    t('reuse');
    const v = await version(view.versionOf);
    if (v && view.version && v !== view.version && typeof view.update === 'function') {
      view.version = v;
      try { await view.update(v); } catch (e) { try { console.debug('[lb] ' + role + ' update failed', e); } catch {} }
      t('update');
    } else {
      if (v && !view.version) view.version = v;
      try { view.onReuse?.(); } catch {}
    }
    t('total');
    return true;
  }

  // ── 全局监听去重：同一个 key 只留最新一份，组件卸载时摘掉（代替 window.__lbcEsc 这类挂钩） ──
  function listen(key, target, type, fn) {
    const reg = (G.__lbListeners = G.__lbListeners || {});
    const k = role + ':' + key;
    const prev = reg[k];
    if (prev) { try { prev.target.removeEventListener(prev.type, prev.fn); } catch {} }
    target.addEventListener(type, fn);
    reg[k] = { target, type, fn };
    try { dv.component?.register?.(() => { if (reg[k]?.fn === fn) { target.removeEventListener(type, fn); delete reg[k]; } }); } catch {}
  }

  // ── 滚动：阅读视图里滚的是整个 .markdown-preview-view；记住位置，回来时等内容长够了再滚回去 ──
  function scroller() {
    try { return container?.closest?.('.markdown-preview-view, .cm-scroller') || null; } catch { return null; }
  }
  // 封面图懒加载、内容逐步长高：最多试 maxMs；用户自己动了滚轮 / 键盘就不再抢
  // 恢复后再「守」一小会儿：Obsidian 后退时会按它自己记的位置（按行算，对整页一个代码块的目录页就是 0）再滚一次，把我们恢复的冲掉
  let restoring = false;
  function restoreScroll(top, { maxMs = 2500, holdMs = 1200 } = {}) {
    const el = scroller();
    if (!el || !(top > 0)) return Promise.resolve(false);
    return new Promise(resolve => {
      const until = clock() + maxMs;
      let stop = false, reachedAt = 0;
      const quit = () => { stop = true; };
      const opts = { once: true, passive: true };
      try { el.addEventListener('wheel', quit, opts); el.addEventListener('keydown', quit, opts); el.addEventListener('pointerdown', quit, opts); } catch {}
      const raf = G.requestAnimationFrame || (fn => setTimeout(fn, 16));
      const done = ok => { restoring = false; resolve(ok); };
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

  return { root, path, provider, ensure, state, data, keep, rekeep, reuseDom, listen, scroller, restoreScroll, onScroll, t, mark, role, container };
}

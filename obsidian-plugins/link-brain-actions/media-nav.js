// media-nav.js — 第 5 批 B2：原「Link Brain Native Media Nav」插件（obsidian-plugins/link-brain-native-media-nav）并进主插件：
// 归档笔记里图片 ←/→ 与滚轮翻页、点图放大（lightbox）、钉住媒体、视频倍速。main.js 只接两行：require 本文件 → attach()。
// 批次 D · L3（本文件全归笔记线）：N1 滚轮翻到头放行；N12 只盯新出现的轮播、尺寸监听用完就放；N15 默认钉住 + 每篇记住钉没钉 / 第几张 / 正文滚到哪、
// 钉住时左栏能用滚轮滚；N-M2 ←/→ 不翻后台 / 别的分栏；MN-0 旧插件只在 manifests 里也有时才让位；
// 对外：openLightbox(images, index, {caption, onCaption, onClose})（L2 问收藏回答里的图用）、hoverControls；视频工具行「循环」「连播…」。
'use strict';
const OLD_PLUGIN_ID = 'link-brain-native-media-nav';

// 直接驱动标准两栏渲染里的图片滑动条 `.lb-carousel`（`<figure class="lb-slide">`），
// 不再依赖整宽的 `[!link-brain-media]` callout —— 这样「左图右文」两栏保留，
// ←/→ 只翻左边那一列的图。稳一点的老规矩仍在：只有先点/聚焦过图片区才接管，
// 正文编辑区、输入框、CodeMirror、文字选中状态都不抢键。
const CAROUSEL_SELECTOR = ".xhs-note .lb-carousel";
const NOTE_ROOT_SELECTOR =
  ".markdown-preview-view.xhs-note, .markdown-reading-view.xhs-note, .markdown-source-view.xhs-note";
const BLOCKED_SELECTOR = [
  "input",
  "textarea",
  "select",
  "button",
  ".cm-editor",
  ".cm-content",
  ".suggestion-container",
  '[contenteditable="true"]'
].join(", ");
const STATE_MAX = 200;   // 每篇记住的状态最多留 200 篇（按最近使用淘汰，插件卸载就清空）
const raf = (f) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(f) : setTimeout(f, 16));
const nowMs = () => (typeof performance !== 'undefined' && performance && typeof performance.now === 'function' ? performance.now() : Date.now());

function getCarouselFromTarget(target) {
  if (!(target instanceof Element)) return null;
  return target.closest(CAROUSEL_SELECTOR);
}

function getSlides(carousel) {
  const videoSlide=carousel.querySelector('.lb-slide:has(video)');
  if(videoSlide)return [videoSlide];
  return Array.from(carousel.children).filter(
    (el) => el.classList && el.classList.contains("lb-slide")
  );
}

function getNearestIndex(carousel, slides) {
  const left = carousel.scrollLeft;
  let bestIndex = 0;
  let bestDist = Infinity;
  for (let i = 0; i < slides.length; i += 1) {
    const dist = Math.abs(slides[i].offsetLeft - slides[0].offsetLeft - left);
    if (dist < bestDist) {
      bestDist = dist;
      bestIndex = i;
    }
  }
  return bestIndex;
}

function isBlockedTarget(target) {
  return target instanceof Element && !!target.closest(BLOCKED_SELECTOR);
}

// 这个元素在 dy 方向上还能不能自己滚（滚动容器 + 还没到头）
function canScroll(el, dy) {
  if (!el || el.nodeType !== 1) return false;
  const sh = el.scrollHeight || 0, ch = el.clientHeight || 0;
  if (sh <= ch + 1) return false;
  let oy = '';
  try { oy = (typeof getComputedStyle === 'function' ? getComputedStyle(el).overflowY : '') || ''; } catch {}
  if (!oy && el.style) oy = el.style.overflowY || '';
  if (oy !== 'auto' && oy !== 'scroll') return false;
  const top = el.scrollTop || 0;
  return dy > 0 ? top + ch < sh - 1 : top > 0;
}

class MediaNav {
  constructor(plugin, obsidian) {
    this.plugin = plugin; this.obsidian = obsidian || null; this.attached = false;
    this.stats = { scan: 0, fit: 0, fitMs: 0 };   // N12：只是整数累加（测量用，正式代码里也留着）
    this.ros = new Set();                           // 每个轮播一个尺寸监听；轮播不在了就自己断开
    this.noteState = new Map();                     // N15：key（item_id / 文件路径）→ {locked, slide, scroll}
    this.paneScrolls = new Map();                   // 1010：钉住时挂在预览容器上的 scroll 监听 → 容器（插件卸载时一起摘）
  }
  // 原插件里的 this.register / this.registerDomEvent：挂到主插件上，主插件卸载时一起清掉
  register(fn) { this.plugin.register(fn); }
  registerDomEvent(el, type, fn, opts) { this.plugin.registerDomEvent(el, type, fn, opts); }
  // 旧插件还开着就不接管（两份同时开会弹两层大图），由它继续工作；停用旧插件后重启 Obsidian 即由这里接管。
  // MN-0：Obsidian 1.14 会把目录已经不在的插件 id 留在 enabledPlugins 里（只对 manifests 里有的才 loadPlugin）——只认「开着且真装着」。
  oldPluginEnabled() {
    const pl = this.plugin.app && this.plugin.app.plugins;
    if (!pl || !pl.enabledPlugins || typeof pl.enabledPlugins.has !== 'function' || !pl.enabledPlugins.has(OLD_PLUGIN_ID)) return false;
    return !!((pl.manifests && pl.manifests[OLD_PLUGIN_ID]) || (pl.plugins && pl.plugins[OLD_PLUGIN_ID]));
  }
  attach() {
    if (this.attached) return true;
    if (this.oldPluginEnabled()) { this.skipped = true; console.info('[lb] 旧插件 ' + OLD_PLUGIN_ID + ' 还开着：图片导航先由它负责'); return false; }
    this.attached = true;
    this.onload();
    // 1026 她：作者行的「← 目录」不要了（顶栏那行已有「← 目录」）——不再调 catalogBack()；方法留着，以后要再加回来只改这里
    return true;
  }
  notice(msg) {
    try { if (typeof this.plugin.notify === 'function') { this.plugin.notify(msg); return; } } catch {}
    try { const N = (this.obsidian && this.obsidian.Notice) || (typeof Notice === 'function' ? Notice : null); if (N) new N(msg); } catch {}
  }

  // 整页锁（lb-pane-locked）残留：同一窗格从钉住的笔记换到目录页时，不清掉整页 overflow:hidden 就滚不动了
  // 1010 审查：钉着笔记的标签页直接关掉，那个容器再也不会滚——它的 scroll 监听（连带摘下的笔记）会一直留着。换页 / 布局变了就清一遍。
  prunePaneScrolls() {
    for (const [fn, pv] of this.paneScrolls) {
      if (pv && pv.isConnected === false) { try { pv.removeEventListener('scroll', fn); } catch {} this.paneScrolls.delete(fn); }
    }
  }
  cleanupStaleLocks() {
    if (typeof document.querySelectorAll !== 'function') return;
    document.querySelectorAll('.lb-pane-locked').forEach(p => { if (!p.querySelector('.lb-media-locked')) p.classList.remove('lb-pane-locked'); });
  }
  scan() {
    this.cleanupStaleLocks();
    if (typeof document.querySelectorAll !== 'function') return;
    document.querySelectorAll(CAROUSEL_SELECTOR).forEach(c => this.enhance(c));
  }

  onload() {
    this.activeCarousel = null;
    this.scan();
    // N12：只对新出现的轮播排一次 scan（问收藏流式出答案、别处打字这类无关插入不再全文档扫描）；
    // 新节点落在一个已锁整页、但里面已经没有钉住笔记的窗格里（换到了目录页）就地清锁。
    let queued = false;
    const observer = new MutationObserver(records => {
      let want = false;
      for (const r of records) {
        for (const n of r.addedNodes || []) {
          if (!n || n.nodeType !== 1) continue;
          const pv = typeof n.closest === 'function' ? n.closest('.lb-pane-locked') : null;
          if (pv && !pv.querySelector('.lb-media-locked')) pv.classList.remove('lb-pane-locked');
          if (!want && ((typeof n.matches === 'function' && n.matches('.lb-carousel')) || (typeof n.querySelector === 'function' && n.querySelector('.lb-carousel')))) want = true;
        }
      }
      if (!want || queued) return;
      queued = true;
      queueMicrotask(() => { queued = false; this.stats.scan++; this.scan(); });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    this.register(() => observer.disconnect());
    const ws = this.plugin.app && this.plugin.app.workspace;
    if (ws && typeof ws.on === 'function' && typeof this.plugin.registerEvent === 'function') {
      for (const ev of ['file-open', 'layout-change']) this.plugin.registerEvent(ws.on(ev, () => { this.cleanupStaleLocks(); this.prunePaneScrolls(); queueMicrotask(() => this.scan()); }));
    }
    this.register(() => { for (const ro of this.ros) { try { ro.disconnect(); } catch {} } this.ros.clear(); this.noteState.clear();
      for (const [fn, pv] of this.paneScrolls) { try { pv.removeEventListener('scroll', fn); } catch {} } this.paneScrolls.clear(); });
    this.register(()=>{document.querySelectorAll('.lb-media-tools,.lb-media-pin,.lb-thumbnails').forEach(e=>e.remove());document.querySelectorAll('[data-lb-enhanced]').forEach(e=>delete e.dataset.lbEnhanced);document.querySelectorAll('.lb-media-locked,.lb-media-free').forEach(e=>e.classList.remove('lb-media-locked','lb-media-free'));document.querySelectorAll('.lb-pane-locked').forEach(e=>e.classList.remove('lb-pane-locked'));document.querySelectorAll('.xhs-note .lb-carousel video').forEach(v=>{v.controls=true;});});

    const rememberCarousel = (event) => {
      const carousel = getCarouselFromTarget(event.target);
      if (carousel) this.activeCarousel = carousel;
    };

    this.registerDomEvent(document, "pointerdown", rememberCarousel);
    this.registerDomEvent(document, "focusin", rememberCarousel);

    this.registerDomEvent(document, "keydown", (event) => {
      if (event.defaultPrevented) return;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const selection = window.getSelection ? window.getSelection() : null;
      if (selection && !selection.isCollapsed) return;

      const target = event.target instanceof Element ? event.target : null;
      if (isBlockedTarget(target)) return;

      const carousel = getCarouselFromTarget(target) || this.activeCarousel;
      if (!carousel || !carousel.isConnected) return;
      if (!carousel.closest(NOTE_ROOT_SELECTOR)) return;
      if (!this.isCarouselActive(carousel, target)) return;   // N-M2：后台标签页 / 另一个分栏里看不见的那篇不翻

      const slides = getSlides(carousel);
      if (slides.length < 2) return;

      const currentIndex = getNearestIndex(carousel, slides);
      const delta = event.key === "ArrowRight" ? 1 : -1;
      const nextIndex = Math.max(
        0,
        Math.min(slides.length - 1, currentIndex + delta)
      );

      if (nextIndex === currentIndex) return;

      // 只横向滚动这个滑动条，不用 scrollIntoView，避免连带把整页/两栏跳动。
      carousel.scrollTo({ left: slides[nextIndex].offsetLeft-slides[0].offsetLeft, behavior: "smooth" });

      this.activeCarousel = carousel;
      event.preventDefault();
      event.stopPropagation();
    });

    this.setupLightbox();
  }

  // N-M2：①display:none（后台标签页）不接管；②按键发生在另一个 leaf 里不接管；③焦点在 body / 不在任何 leaf 里时，要求当前活动 leaf 包含它
  isCarouselActive(carousel, target) {
    if (carousel.offsetParent === null) return false;
    const leafOf = (el) => (el && typeof el.closest === 'function' ? el.closest('.workspace-leaf') : null);
    const tl = target && target !== document.body ? leafOf(target) : null;
    const cl = leafOf(carousel);
    if (tl && cl && tl !== cl) return false;
    if (!tl) {
      const al = this.plugin.app && this.plugin.app.workspace && this.plugin.app.workspace.activeLeaf;
      const ce = al && al.containerEl;
      if (ce && typeof ce.contains === 'function' && !ce.contains(carousel)) return false;
    }
    return true;
  }

  // 1002 Owner：单击图片放大看。左栏图片和评论图都能点；←/→、滚轮切换上一张/下一张，
  // Ctrl+滚轮或双击放大（+ / - / 0 也行），放大后拖动或滚轮挪画面，Esc / 点空白处关闭。
  // 关闭时左栏滑动条停在最后看的那张。
  setupLightbox() {
    const IMG_SELECTOR = ".xhs-note .lb-carousel .lb-slide img, .xhs-note img.lb-comment-image";
    const style = document.createElement("style");
    style.textContent = [
      ".lb-lightbox{position:fixed;inset:0;z-index:var(--layer-modal,50);background:rgba(0,0,0,.94);display:flex;align-items:center;justify-content:center;user-select:none;}",
      ".lb-lightbox img{max-width:92vw;max-height:88vh;object-fit:contain;transform-origin:center center;cursor:zoom-in;transition:transform .12s ease-out;}",
      ".lb-lightbox.is-zoomed img{cursor:grab;}",
      ".lb-lightbox.is-dragging img{cursor:grabbing;transition:none;}",
      ".lb-lightbox button{position:absolute;border:0!important;box-shadow:none!important;background:rgba(255,255,255,.12)!important;color:#fff;border-radius:999px!important;width:44px;height:44px;font-size:24px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;}",
      ".lb-lightbox button:hover{background:rgba(255,255,255,.24)!important;}",
      ".lb-lightbox .lb-lb-prev{left:18px;top:50%;transform:translateY(-50%);}",
      ".lb-lightbox .lb-lb-next{right:18px;top:50%;transform:translateY(-50%);}",
      ".lb-lightbox .lb-lb-close{right:18px;top:18px;width:38px;height:38px;font-size:16px;}",
      ".lb-lightbox .lb-lb-count{position:absolute;left:50%;bottom:18px;transform:translateX(-50%);color:rgba(255,255,255,.85);font-size:13px;background:rgba(0,0,0,.35);padding:3px 12px;border-radius:999px;}",
      ".lb-lightbox .lb-lb-caption{position:absolute;left:50%;bottom:50px;transform:translateX(-50%);max-width:80vw;text-align:center;color:rgba(255,255,255,.85);font-size:13px;}",
      ".lb-lightbox .lb-lb-caption.is-link{cursor:pointer;text-decoration:underline;text-underline-offset:2px;}",
      ".lb-lightbox .lb-lb-caption:empty{display:none;}",
      ".lb-lightbox[data-single] .lb-lb-prev,.lb-lightbox[data-single] .lb-lb-next{display:none;}",
    ].join("\n");
    document.head.appendChild(style);
    this.register(() => style.remove());
    this.register(() => this.closeLightbox());

    this.registerDomEvent(document, "click", (e) => {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      if (e.defaultPrevented) return;   // 1003：新旧两份插件同开时另一份已经接了这一下，别再弹第二层大图
      const img = e.target instanceof Element ? e.target.closest(IMG_SELECTOR) : null;
      if (!img || img.closest(".lb-lightbox")) return;
      if (!img.closest(NOTE_ROOT_SELECTOR)) return;   // 只在小红书归档笔记里接管
      const carousel = img.closest(".lb-carousel");
      const note = img.closest(".xhs-note") || document;
      const imgs = carousel
        ? getSlides(carousel).map((s) => s.querySelector("img")).filter(Boolean)
        : Array.from(note.querySelectorAll("img.lb-comment-image"));
      if (!imgs.length) return;
      e.preventDefault();
      e.stopPropagation();
      const lbNote = img.closest('.lb-note');
      this.openLightbox(imgs, Math.max(0, imgs.indexOf(img)), { onClose: (last) => {
        if (!carousel || !carousel.isConnected) return;
        const slides = getSlides(carousel), s = slides[last];
        if (s) carousel.scrollTo({ left: s.offsetLeft - slides[0].offsetLeft, behavior: "auto" });
        if (lbNote) this.saveNoteState(this.noteKey(lbNote), { slide: last });
      } });
    }, true);
  }
  closeLightbox() { if (this._lbClose) { const c = this._lbClose; this._lbClose = null; c(); } }

  // 大图查看器（笔记页点图、L2 问收藏回答里的图共用一套）：images = img 元素或 {src, alt}；
  // opts.caption(i) 显示在计数上面，给了 onCaption(i) 就能点（点了先关）；opts.onClose(lastIndex)。返回 {close()}；没有图返回 null。
  // 右键菜单开着时 Esc / 方向键归菜单；只有左键能拖动。
  openLightbox(images, index = 0, opts = {}) {
    const imgs = (Array.isArray(images) ? images : []).map(x => (typeof x === 'string' ? { src: x } : x)).filter(x => x && (x.currentSrc || x.src));
    if (!imgs.length) return null;
    this.closeLightbox();
    let idx = Math.max(0, Math.min(imgs.length - 1, Number(index) || 0));
    let scale = 1, tx = 0, ty = 0, lastWheel = 0, drag = null;
    const menuOpen = () => !!(this.plugin.menuOpen || (typeof document.querySelector === 'function' && document.querySelector('body > .menu')));

    const el = document.body.createDiv({ cls: "lb-lightbox" });
    if (imgs.length < 2) el.dataset.single = "1";
    const view = el.createEl("img");
    const prev = el.createEl("button", { cls: "lb-lb-prev", text: "‹" });
    const next = el.createEl("button", { cls: "lb-lb-next", text: "›" });
    const shut = el.createEl("button", { cls: "lb-lb-close", text: "✕" });
    const count = el.createDiv({ cls: "lb-lb-count" });
    const cap = typeof opts.caption === 'function' ? el.createDiv({ cls: "lb-lb-caption" + (typeof opts.onCaption === 'function' ? " is-link" : "") }) : null;
    prev.setAttribute("aria-label", "上一张");
    next.setAttribute("aria-label", "下一张");
    shut.setAttribute("aria-label", "关闭");

    const apply = () => {
      view.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
      el.classList.toggle("is-zoomed", scale > 1.01);
    };
    const resetZoom = () => { scale = 1; tx = 0; ty = 0; apply(); };
    const show = (i) => {
      idx = (i + imgs.length) % imgs.length;
      view.src = imgs[idx].currentSrc || imgs[idx].src;
      view.alt = imgs[idx].alt || "";
      count.setText(`${idx + 1} / ${imgs.length}`);
      if (cap) { let t = ''; try { t = String(opts.caption(idx) || ''); } catch {} cap.setText(t); }
      resetZoom();
    };
    // 以光标为中心缩放：光标下那一点缩放前后不动
    const zoomAt = (factor, cx, cy) => {
      const r = view.getBoundingClientRect();
      const ox = cx - (r.left + r.width / 2), oy = cy - (r.top + r.height / 2);
      const ns = Math.min(8, Math.max(1, scale * factor));
      const k = ns / scale;
      tx += ox * (1 - k);
      ty += oy * (1 - k);
      scale = ns;
      if (scale <= 1.01) { scale = 1; tx = 0; ty = 0; }
      apply();
    };

    const onKey = (e) => {
      if (menuOpen()) return;   // 右键菜单开着：Esc / 方向键归菜单
      const stop = () => { e.preventDefault(); e.stopPropagation(); };
      if (e.key === "Escape" || e.key === "Esc" || e.keyCode === 27) { stop(); this.closeLightbox(); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowRight") { stop(); show(idx + (e.key === "ArrowRight" ? 1 : -1)); }
      else if (e.key === "+" || e.key === "=") { stop(); zoomAt(1.25, innerWidth / 2, innerHeight / 2); }
      else if (e.key === "-") { stop(); zoomAt(0.8, innerWidth / 2, innerHeight / 2); }
      else if (e.key === "0") { stop(); resetZoom(); }
    };
    const onWheel = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.ctrlKey) { zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY); return; }
      if (scale > 1.01) { tx -= e.deltaX; ty -= e.deltaY; apply(); return; }   // 放大后滚轮挪画面
      const now = Date.now();
      if (now - lastWheel < 220 || Math.abs(e.deltaY) + Math.abs(e.deltaX) < 4) return;
      lastWheel = now;
      show(idx + ((e.deltaY || e.deltaX) > 0 ? 1 : -1));
    };
    const onDown = (e) => {
      if (typeof e.button === 'number' && e.button !== 0) return;   // 右键不拖
      if (e.target !== view || scale <= 1.01) return;
      e.preventDefault();
      drag = { x: e.clientX, y: e.clientY, tx, ty, moved: false };
      el.classList.add("is-dragging");
    };
    const onMove = (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      tx = drag.tx + dx;
      ty = drag.ty + dy;
      apply();
    };
    const onUp = () => {
      if (!drag) return;
      el.classList.remove("is-dragging");
      setTimeout(() => { drag = null; }, 0);   // 让紧跟着的 click 知道刚才是在拖
    };

    view.addEventListener("dblclick", (e) => { e.stopPropagation(); scale > 1.01 ? resetZoom() : zoomAt(2, e.clientX, e.clientY); });
    view.addEventListener("click", (e) => e.stopPropagation());
    el.addEventListener("click", (e) => { if (drag && drag.moved) return; if (e.target === el) this.closeLightbox(); });
    prev.addEventListener("click", (e) => { e.stopPropagation(); show(idx - 1); });
    next.addEventListener("click", (e) => { e.stopPropagation(); show(idx + 1); });
    shut.addEventListener("click", (e) => { e.stopPropagation(); this.closeLightbox(); });
    if (cap && typeof opts.onCaption === 'function') cap.addEventListener("click", (e) => { e.stopPropagation(); const i = idx; this.closeLightbox(); try { opts.onCaption(i); } catch (err) { console.error('[lb] 大图说明点击出错', err); } });
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onKey, true);
    show(idx);

    const closer = () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      el.remove();
      if (typeof opts.onClose === 'function') { try { opts.onClose(idx); } catch (err) { console.error('[lb] 大图关闭回调出错', err); } }
    };
    this._lbClose = closer;
    return { close: () => { if (this._lbClose === closer) this.closeLightbox(); }, get index() { return idx; }, el };
  }

  // ── N15：每篇的状态（key = .lb-note 的 data-lb-item；没有就用所在 markdown leaf 的文件路径）──
  leafOfNote(note) {
    const ws = this.plugin.app && this.plugin.app.workspace;
    if (!ws) return null;
    const leaves = typeof ws.getLeavesOfType === 'function' ? ws.getLeavesOfType('markdown') : (ws.leaves || []);
    for (const l of leaves || []) { const c = l && l.view && l.view.containerEl; if (c && typeof c.contains === 'function' && c.contains(note)) return l; }
    return null;
  }
  noteKey(note) {
    const id = note && note.dataset && note.dataset.lbItem;
    if (id) return 'item:' + id;
    const l = this.leafOfNote(note);
    const p = l && l.view && l.view.file && l.view.file.path;
    return p ? 'path:' + p : '';
  }
  itemIdOf(note) {
    const id = note && note.dataset && note.dataset.lbItem;
    if (id) return id;
    const l = this.leafOfNote(note), f = l && l.view && l.view.file;
    try { return (f && this.plugin.app.metadataCache.getFileCache(f)?.frontmatter?.link_brain?.item_id) || ''; } catch { return ''; }
  }
  getNoteState(key) {
    if (!key || !this.noteState.has(key)) return null;
    const st = this.noteState.get(key);
    this.noteState.delete(key); this.noteState.set(key, st);   // 最近使用排到最后
    return st;
  }
  saveNoteState(key, patch) {
    if (!key) return;
    const st = { ...(this.noteState.get(key) || {}), ...patch };
    this.noteState.delete(key); this.noteState.set(key, st);
    while (this.noteState.size > STATE_MAX) this.noteState.delete(this.noteState.keys().next().value);
  }
  // 问收藏的来源窗格（登记在 leaf.lbArchiveReader / lbArchiveCompare）
  isArchiveReaderLeaf(note) {
    const ws = this.plugin.app && this.plugin.app.workspace;
    if (!ws) return false;
    const leaves = typeof ws.getLeavesOfType === 'function' ? ws.getLeavesOfType('markdown') : (ws.leaves || []);
    for (const l of leaves || []) {
      const r = l && l.lbArchiveReader;
      for (const x of [r, r && r.lbArchiveCompare]) {
        const c = x && ((x.view && x.view.containerEl) || x.containerEl);
        if (c && typeof c.contains === 'function' && c.contains(note)) return true;
      }
    }
    return false;
  }
  // 默认钉住只在：阅读视图里、不在来源窗格 / 悬停预览 / 嵌入里（那些地方钉住会让图变小或抢滚轮）
  shouldDefaultLock(note, preview) {
    if (!preview || typeof note.closest !== 'function') return false;
    if (!note.closest('.markdown-reading-view')) return false;
    if (note.closest('.lb-source-reader, .hover-popover, .popover, .markdown-embed')) return false;
    if (this.isArchiveReaderLeaf(note)) return false;
    return true;
  }
  // 钉住时 note 顶部已经被滚出 preview 上沿（Obsidian 恢复了旧的滚动位置 / 先往下滚了再点钉）：把 preview 往回滚差值
  // 1010：笔记已经不在这个预览容器里（同一标签页换成了目录页，Obsidian 复用容器、把笔记摘下）就什么都不做——
  // 摘下的元素 getBoundingClientRect() 全是 0，会被当成「顶在上沿外」，把目录页一路拉回顶部。
  ensureLockedInView(note, preview) {
    if (!preview || typeof note.getBoundingClientRect !== 'function' || typeof preview.getBoundingClientRect !== 'function') return;
    if (note.isConnected === false || (typeof preview.contains === 'function' && !preview.contains(note))) return;
    const nt = note.getBoundingClientRect().top, pt = preview.getBoundingClientRect().top;
    if (nt < pt - 0.5) { preview.scrollTop = Math.max(0, (preview.scrollTop || 0) - (pt - nt)); if (typeof note.querySelector === 'function') note.querySelector('.lb-carousel')?.lbFit?.(); }
  }

  enhance(carousel){
    if(carousel.dataset.lbEnhanced){const n=carousel.closest('.lb-note');if(n&&n.classList.contains('lb-media-locked'))carousel.lbFit?.();return;}   // N12：只给钉住的再量一次
    carousel.dataset.lbEnhanced='1';
    const media=carousel.closest('.lb-media'),note=carousel.closest('.lb-note');
    if(!media||!note)return;
    const leaf=note.closest('.workspace-leaf-content');
    let resize=null;
    // 0929 Owner：钉住时评论拉不到底——右下角状态栏浮在页面上盖住底部，要让开它
    const fit=()=>{
      if(carousel.isConnected===false){if(resize){resize.disconnect();this.ros.delete(resize);resize=null;}return;}   // N12：轮播不在了就放掉监听
      const t0=nowMs();this.stats.fit++;
      let bottom=Math.min(window.innerHeight,leaf?.getBoundingClientRect().bottom||window.innerHeight);const sb=document.querySelector('.status-bar')?.getBoundingClientRect(),nr=note.getBoundingClientRect();if(sb&&sb.height&&sb.top<bottom&&sb.left<nr.right&&sb.right>nr.left)bottom=sb.top;note.style.setProperty('--lb-reader-height',Math.max(200,bottom-note.getBoundingClientRect().top-20)+'px');
      this.stats.fitMs+=nowMs()-t0;
    };
    if(typeof ResizeObserver==='function'){resize=new ResizeObserver(fit);resize.observe(leaf||document.documentElement);this.ros.add(resize);}
    carousel.lbFit=fit;fit();
    const preview=note.closest('.markdown-preview-view, .markdown-reading-view');
    const key=this.noteKey(note);
    const st=this.getNoteState(key);
    let pin=null,touched=false,onPaneScroll=null;
    const setLocked=locked=>{
      note.classList.toggle('lb-media-locked',locked);note.classList.toggle('lb-media-free',!locked);
      preview?.classList.toggle('lb-pane-locked',locked);
      if(pin){pin.setAttribute('aria-pressed',String(locked));const s=pin.querySelector('span');if(s)s.textContent=locked?'取消固定媒体':'固定媒体';}
      fit();
      if(locked&&preview){
        this.ensureLockedInView(note,preview);
        // 1010 她报「连播 / 看完笔记回到目录，往下滚不动、反复被拉回顶部」：这个 scroll 监听挂在预览容器上，而同一标签页换文件时
        // Obsidian 复用这个容器——笔记被摘下后它还在，每次滚动都把目录页往回拉。现在笔记一不在容器里就摘掉自己。
        if(!onPaneScroll){let q=false;const fn=onPaneScroll=()=>{
          if(note.isConnected===false||!preview.contains(note)){preview.removeEventListener('scroll',fn);this.paneScrolls.delete(fn);if(onPaneScroll===fn)onPaneScroll=null;return;}
          if(q)return;q=true;raf(()=>{q=false;if(note.isConnected!==false&&note.classList.contains('lb-media-locked'))this.ensureLockedInView(note,preview);});};
          preview.addEventListener('scroll',fn);this.paneScrolls.set(fn,preview);}
        // 钉住后页面不能滚：促一下 Obsidian 阅读视图把底部（批注 bootstrap 那段）渲染出来
        raf(()=>{try{if(typeof preview.dispatchEvent==='function'&&typeof Event==='function')preview.dispatchEvent(new Event('scroll'));}catch{}});
      }else if(onPaneScroll&&preview){preview.removeEventListener('scroll',onPaneScroll);this.paneScrolls.delete(onPaneScroll);onPaneScroll=null;}
    };
    // 0926 Owner：滚轮停在图片上 = 翻页（一格一张，节流防连跳）；刚打开的笔记直接认它，←/→ 不用先点图。
    this.activeCarousel=carousel;
    if(preview)this.paneWheel(preview);
    pin=media.createEl('button',{cls:'lb-media-pin'});
    pin.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3h8l-1 6 4 4v2H5v-2l4-4zM12 15v7"/></svg><span class="lb-visually-hidden">取消固定媒体</span>';
    pin.onclick=()=>{touched=true;const locked=!note.classList.contains('lb-media-locked');setLocked(locked);this.saveNoteState(key,{locked});};
    // 1008 她定：默认钉住（批注框紧贴图片下面、能直接写）；同一篇后台重写后照原样（钉没钉、第几张、正文滚到哪）
    const auto=this.shouldDefaultLock(note,preview);
    setLocked(st&&typeof st.locked==='boolean'?st.locked:auto);
    if(!st&&auto)raf(()=>raf(()=>{if(!touched&&note.isConnected!==false&&!this.shouldDefaultLock(note,preview))setLocked(false);}));   // 来源窗格的类是 openFile 之后才加的
    const slides=getSlides(carousel);
    if(st&&st.slide>0&&slides[st.slide])raf(()=>carousel.scrollTo({left:slides[st.slide].offsetLeft-slides[0].offsetLeft,behavior:'auto'}));
    // 当前张：每帧最多记一次；轮播已被摘下（Obsidian 重写这篇）就不记（摘下后 offsetLeft 全是 0，会把「第几张」冲成 0）
    let slideQ=false;
    carousel.addEventListener('scroll',()=>{if(slideQ)return;slideQ=true;raf(()=>{slideQ=false;if(carousel.isConnected===false)return;this.saveNoteState(key,{slide:getNearestIndex(carousel,getSlides(carousel))});});});
    const sc=note.querySelector('.lb-scroll');
    if(sc){
      let q=false,restoring=false;
      sc.addEventListener('scroll',()=>{if(restoring||q)return;q=true;raf(()=>{q=false;if(sc.isConnected===false)return;this.saveNoteState(key,{scroll:sc.scrollTop||0});});});
      if(st&&st.scroll>0&&note.classList.contains('lb-media-locked')){
        // 评论图懒加载会长高：最多试 1 秒；她一动滚轮 / 键盘就停
        restoring=true;const until=Date.now()+1000,target=st.scroll;
        const stop=()=>{restoring=false;note.removeEventListener('wheel',stop);note.removeEventListener('keydown',stop);};
        note.addEventListener('wheel',stop);note.addEventListener('keydown',stop);
        const step=()=>{if(!restoring)return;sc.scrollTop=target;if(Math.abs((sc.scrollTop||0)-target)<=1||Date.now()>until){stop();return;}raf(step);};
        step();
      }
    }
    const bar=media.createEl('div',{cls:'lb-media-tools'});
    const video=carousel.querySelector('video');
    if(video){
      this.hoverControls(media,video);
      this.clickToggle(video);
      const speed=bar.createEl('button',{cls:'lb-video-speed',text:'1×'});
      const setRate=value=>{video.playbackRate=Math.min(4,Math.max(.25,Math.round(value*20)/20));speed.setText(Number(video.playbackRate.toFixed(2))+'×');};
      let drag=null,moved=false;
      speed.onpointerdown=e=>{drag={x:e.clientX,rate:video.playbackRate};moved=false;speed.setPointerCapture(e.pointerId);};
      speed.onpointermove=e=>{if(!drag)return;const delta=e.clientX-drag.x;if(Math.abs(delta)>4)moved=true;if(moved)setRate(drag.rate+delta/80);};
      speed.onpointerup=e=>{drag=null;if(speed.hasPointerCapture(e.pointerId))speed.releasePointerCapture(e.pointerId);};
      speed.onpointercancel=()=>{drag=null;};
      speed.onclick=e=>{if(e&&e.detail&&speed.blur)speed.blur();if(moved){moved=false;return;}const rates=[1,1.25,1.5,2,3];setRate(rates.find(r=>r>video.playbackRate+.01)||1);};
      speed.onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();setRate(video.playbackRate+(e.key==='ArrowRight'?.25:-.25));}};
      // 批次 D · F6：单曲循环（记住选择，settings.media.loop）+「连播…」（按标签连播，播放器归 L5 的 player-ui）
      const loopOn=!!(this.plugin.settings&&this.plugin.settings.media&&this.plugin.settings.media.loop);
      video.loop=loopOn;
      const loop=bar.createEl('button',{cls:'lb-video-loop',text:'循环'});
      loop.setAttribute('aria-pressed',String(loopOn));loop.setAttribute('title','单曲循环（再点关掉）');
      loop.onclick=async e=>{
        if(e&&e.detail&&loop.blur)loop.blur();   // 鼠标点完不留焦点：不然 :focus-within 让工具行一直挂着（她要悬停才出现）
        const on=!video.loop;
        const s=this.plugin.settings||(this.plugin.settings={});
        s.media={...(s.media||{}),loop:on};
        video.loop=on;loop.setAttribute('aria-pressed',String(on));
        document.querySelectorAll('.xhs-note .lb-carousel video').forEach(v=>{v.loop=on;});
        document.querySelectorAll('.xhs-note .lb-video-loop').forEach(b=>b.setAttribute('aria-pressed',String(on)));
        try{await this.plugin.saveSettings?.();}catch(e){console.error('[lb] 循环设置没存上',e);}
      };
      const playlist=bar.createEl('button',{cls:'lb-video-playlist',text:'连播…'});
      playlist.setAttribute('title','按标签连播视频');
      playlist.onclick=e=>{
        if(e&&e.detail&&playlist.blur)playlist.blur();
        const ui=this.plugin.playerUI;
        if(ui&&typeof ui.openTagPicker==='function'){try{const r=ui.openTagPicker({itemId:this.itemIdOf(note)});if(r&&typeof r.catch==='function')r.catch(e=>console.error('[lb] 连播没打开',e));}catch(e){console.error('[lb] 连播没打开',e);}}
        else this.notice('连播还没装好：更新 Link Brain Actions 插件后再试');
      };
      return;
    }
    bar.remove(); // Image paging uses the original centered controls and per-image counter.
  }

  // 10-04 Owner：正文视频的控制条（播放 / 进度 / 音量 / 全屏 / ⋮）平时藏着，鼠标放到视频（连同下面的倍速行）上才出现，移开就藏。
  // 做法是切 video 的 controls 属性（原生控制条没法只靠 CSS 稳定地藏）：播放不受影响；键盘 Tab 到视频上（:focus-visible）也出现，
  // 鼠标点过之后焦点留在视频上不算（不然点完播放移开，控制条一直挂着）。触屏（没有悬停）照旧一直显示；倍速行的显隐在 link-brain.css。
  hoverControls(media,video){
    const mm=typeof window!=='undefined'&&window.matchMedia?window.matchMedia('(hover: none)'):null;
    if(mm&&mm.matches)return;
    let over=false,keyboard=false;
    try{over=media.matches(':hover');}catch{}
    const paint=()=>{video.controls=over||keyboard;};
    if(!video.hasAttribute('tabindex'))video.tabIndex=0;
    media.addEventListener('mouseenter',()=>{over=true;paint();});
    media.addEventListener('mouseleave',()=>{over=false;paint();});
    // 1015：鼠标没动过、视频在光标下被重画时 mouseenter 不会来，控制条就一直藏着——光标一动就补上
    media.addEventListener('pointermove',e=>{if(!over&&e.pointerType!=='touch'){over=true;paint();}});
    media.addEventListener('focusin',e=>{let fv=false;try{fv=e.target.matches(':focus-visible');}catch{}if(fv){keyboard=true;paint();}});
    media.addEventListener('focusout',e=>{if(!media.contains(e.relatedTarget)){keyboard=false;paint();}});
    paint();
  }

  // 1015 修「点视频画面正中有时不播、只能点播放键，再点又行」。根因在 Chromium 原生控制条（Edge 150 实测，tests/ui/video_click_ui.cjs）：
  // ① 点画面的播放/暂停是延后执行的（等约 300ms 看是不是双击），这期间再点一下就把前一下取消——画面没反应时人自然会再点，于是两下都没了；
  // ② 原生「点画面切换」只在 video.controls 为真时生效，而 controls 由上面的悬停逻辑切，悬停状态没对上时点画面完全没反应。
  // 改法：画面上的单击由我们自己接管（preventDefault 掉原生那份，立刻切、每下都算），底部原生控制条那一条（进度/音量/全屏）照旧交给原生。
  clickToggle(video){
    const BAR=48;   // 原生控制条高度约 40px，留点余量
    video.addEventListener('click',e=>{
      if(e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
      if(e.target!==video)return;
      if(video.controls){const r=video.getBoundingClientRect();if(r.height>BAR*2&&e.clientY>r.bottom-BAR)return;}
      e.preventDefault();
      MediaNav.togglePlay(video);
    });
  }
  static togglePlay(video){
    if(video.paused||video.ended){
      try{const p=video.play();if(p&&typeof p.catch==='function')p.catch(err=>{if(!err||err.name!=='AbortError')console.error('[lb] 视频没播起来',err);});}
      catch(err){console.error('[lb] 视频没播起来',err);}
    }else video.pause();
  }

  // 10-04 ⑩（1023 恢复）笔记正文回目录页：作者行最左边一个不起眼的「← 目录」（两栏布局不动）。点了在同一个窗格打开目录页
  // （按页头 lb-page: catalog 找，不写死文件名）；目录页自己记着搜索词和滚动位置，回去就是原来那样。
  // 不改 render.py（那样要全库重渲染）：笔记渲染出来后由这里补进去，阅读视图和实时预览都认 .lb-note 里的 .lb-author-row。
  catalogBack() {
    if (this.backAttached) return;
    this.backAttached = true;
    const plugin = this.plugin;
    const add = row => {
      if (!row || [...row.children].some(c => c.classList.contains('lb-back-catalog'))) return;
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'lb-back-catalog'; btn.textContent = '← 目录';
      btn.title = '回到目录页'; btn.setAttribute('aria-label', '回到目录页');
      const stop = e => { e.preventDefault(); e.stopPropagation(); };
      btn.addEventListener('mousedown', stop);   // 实时预览里别把光标点进这块 HTML
      btn.addEventListener('click', e => {
        stop(e);
        const ws = plugin.app && plugin.app.workspace;
        let leaf = null;
        try { ws.iterateAllLeaves(l => { if (!leaf && l.view && l.view.containerEl && l.view.containerEl.contains(btn)) leaf = l; }); } catch {}
        Promise.resolve(plugin.openLibraryPage && plugin.openLibraryPage('catalog', leaf)).catch(err => console.error('[lb] 回目录页没打开', err));
      });
      row.insertBefore(btn, row.firstChild);
    };
    const scan = () => document.querySelectorAll('.lb-note .lb-author-row').forEach(add);
    scan();
    let queued = false;
    const observer = new MutationObserver(records => { if (queued || !records.some(r => [...r.addedNodes].some(n => n.nodeType === 1))) return; queued = true; queueMicrotask(() => { queued = false; scan(); }); });
    observer.observe(document.body, { childList: true, subtree: true });
    this.register(() => { observer.disconnect(); document.querySelectorAll('.lb-back-catalog').forEach(e => e.remove()); this.backAttached = false; });
  }

  // 1003 修「目录页 / 问收藏页有时滚轮滚不动」：Obsidian 同一个标签页换文件时复用同一个 .markdown-preview-view。
  // 每个预览容器只挂一个监听（挂点 PANE_WHEEL_KEY 新旧两份插件共用，后来的替换先前的，不会两份都翻页），
  // 事件来了才现找「这个容器里此刻」被钉住的笔记 / 光标下的图片；找不到就什么都不拦，顺手清掉残留的 lb-pane-locked。
  // 批次 D：N1 翻到最后一张（或第一张往上）后放行，不再吞滚轮；N15 钉住时左栏（批注列表）能用滚轮滚，左栏到头才转给正文栏。
  paneWheel(preview){
    const KEY='__lbMediaWheel';
    const prev=preview[KEY];if(prev)preview.removeEventListener('wheel',prev);
    const wheel=e=>{
      const t=e.target instanceof Element?e.target:null;
      if(!t||!preview.contains(t)||e.ctrlKey)return;
      if(Math.abs(e.deltaY)>=Math.abs(e.deltaX)){   // 图片上滚轮 = 翻页（一格一张，节流防连跳）
        const carousel=t.closest('.lb-carousel');
        if(carousel&&carousel.dataset.lbEnhanced){
          const list=getSlides(carousel);
          if(list.length>=2){
            const now=Date.now(),since=now-(carousel.lbFlipAt||0);
            // 平滑滚动还没到位时 getNearestIndex 会落后：600ms 内认上次的目标
            const cur=since<600&&typeof carousel.lbTargetIndex==='number'?carousel.lbTargetIndex:getNearestIndex(carousel,list);
            const next=Math.max(0,Math.min(list.length-1,cur+(e.deltaY>0?1:-1)));
            if(next!==cur){
              e.preventDefault();if(since<350)return;
              carousel.lbFlipAt=now;carousel.lbTargetIndex=next;
              carousel.scrollTo({left:list[next].offsetLeft-list[0].offsetLeft,behavior:'smooth'});this.activeCarousel=carousel;return;
            }
            if(since<350){e.preventDefault();return;}   // 惯性还在翻页动画里：不突然滚页面
            // 到头了：放行（钉住时转给正文栏，没钉住时浏览器滚整页）
          }
        }
      }
      if(Math.abs(e.deltaX)>Math.abs(e.deltaY))return;
      const note=preview.querySelector('.lb-note.lb-media-locked');
      if(!note){if(preview.classList.contains('lb-pane-locked'))preview.classList.remove('lb-pane-locked');return;}
      const scroller=note.querySelector('.lb-scroll');
      if(!scroller||t.closest('.lb-scroll'))return;
      const side=t.closest('.lb-side');
      if(side&&note.contains(side)&&!t.closest('.lb-carousel')){
        for(let el=t;el;el=el.parentNode){if(canScroll(el,e.deltaY))return;if(el===side)break;}   // 左栏自己还能滚：交给浏览器
      }
      scroller.scrollTop+=e.deltaY*(e.deltaMode===1?16:1);e.preventDefault();
    };
    preview[KEY]=wheel;preview.addEventListener('wheel',wheel,{passive:false});
    this.register(()=>{preview.removeEventListener('wheel',wheel);if(preview[KEY]===wheel){delete preview[KEY];preview.classList.remove('lb-pane-locked');}});
  }
}

module.exports = function (obsidian, plugin) { return new MediaNav(plugin, obsidian); };
module.exports.MediaNav = MediaNav;
module.exports.OLD_PLUGIN_ID = OLD_PLUGIN_ID;
module.exports.getSlides = getSlides;
module.exports.canScroll = canScroll;

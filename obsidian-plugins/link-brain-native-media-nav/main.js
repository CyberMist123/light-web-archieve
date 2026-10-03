const { Plugin } = require("obsidian");

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

module.exports = class LinkBrainNativeMediaNavPlugin extends Plugin {
  async onload() {
    this.activeCarousel = null;
    const scan=()=>{document.querySelectorAll('.lb-pane-locked').forEach(p=>{if(!p.querySelector('.lb-media-locked'))p.classList.remove('lb-pane-locked');});document.querySelectorAll(CAROUSEL_SELECTOR).forEach(c=>this.enhance(c));};
    scan();
    let queued=false;
    const observer=new MutationObserver(records=>{if(queued||!records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1)))return;queued=true;queueMicrotask(()=>{queued=false;scan();});});
    observer.observe(document.body,{childList:true,subtree:true});
    this.register(()=>observer.disconnect());
    this.register(()=>{document.querySelectorAll('.lb-media-tools,.lb-media-pin,.lb-thumbnails').forEach(e=>e.remove());document.querySelectorAll('[data-lb-enhanced]').forEach(e=>delete e.dataset.lbEnhanced);document.querySelectorAll('.lb-media-locked,.lb-media-free').forEach(e=>e.classList.remove('lb-media-locked','lb-media-free'));});

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
      ".lb-lightbox[data-single] .lb-lb-prev,.lb-lightbox[data-single] .lb-lb-next{display:none;}",
    ].join("\n");
    document.head.appendChild(style);
    this.register(() => style.remove());

    let current = null;
    const close = () => { if (current) { const c = current; current = null; c(); } };
    this.register(close);

    const open = (img) => {
      close();
      const carousel = img.closest(".lb-carousel");
      const note = img.closest(".xhs-note") || document;
      const imgs = carousel
        ? getSlides(carousel).map((s) => s.querySelector("img")).filter(Boolean)
        : Array.from(note.querySelectorAll("img.lb-comment-image"));
      if (!imgs.length) return;
      let index = Math.max(0, imgs.indexOf(img));
      let scale = 1, tx = 0, ty = 0, lastWheel = 0, drag = null;

      const el = document.body.createDiv({ cls: "lb-lightbox" });
      if (imgs.length < 2) el.dataset.single = "1";
      const view = el.createEl("img");
      const prev = el.createEl("button", { cls: "lb-lb-prev", text: "‹" });
      const next = el.createEl("button", { cls: "lb-lb-next", text: "›" });
      const shut = el.createEl("button", { cls: "lb-lb-close", text: "✕" });
      const count = el.createDiv({ cls: "lb-lb-count" });
      prev.setAttribute("aria-label", "上一张");
      next.setAttribute("aria-label", "下一张");
      shut.setAttribute("aria-label", "关闭");

      const apply = () => {
        view.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
        el.classList.toggle("is-zoomed", scale > 1.01);
      };
      const resetZoom = () => { scale = 1; tx = 0; ty = 0; apply(); };
      const show = (i) => {
        index = (i + imgs.length) % imgs.length;
        view.src = imgs[index].currentSrc || imgs[index].src;
        view.alt = imgs[index].alt || "";
        count.setText(`${index + 1} / ${imgs.length}`);
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
        const stop = () => { e.preventDefault(); e.stopPropagation(); };
        if (e.key === "Escape" || e.key === "Esc" || e.keyCode === 27) { stop(); close(); }
        else if (e.key === "ArrowLeft" || e.key === "ArrowRight") { stop(); show(index + (e.key === "ArrowRight" ? 1 : -1)); }
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
        show(index + ((e.deltaY || e.deltaX) > 0 ? 1 : -1));
      };
      const onDown = (e) => {
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
      el.addEventListener("click", (e) => { if (drag && drag.moved) return; if (e.target === el) close(); });
      prev.addEventListener("click", (e) => { e.stopPropagation(); show(index - 1); });
      next.addEventListener("click", (e) => { e.stopPropagation(); show(index + 1); });
      shut.addEventListener("click", (e) => { e.stopPropagation(); close(); });
      el.addEventListener("wheel", onWheel, { passive: false });
      el.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("keydown", onKey, true);
      show(index);

      current = () => {
        window.removeEventListener("keydown", onKey, true);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        el.remove();
        if (carousel && carousel.isConnected) {
          const slides = getSlides(carousel), s = slides[index];
          if (s) carousel.scrollTo({ left: s.offsetLeft - slides[0].offsetLeft, behavior: "auto" });
        }
      };
    };

    this.registerDomEvent(document, "click", (e) => {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      if (e.defaultPrevented) return;   // 1003：新旧两份插件同开时另一份已经接了这一下，别再弹第二层大图
      const img = e.target instanceof Element ? e.target.closest(IMG_SELECTOR) : null;
      if (!img || img.closest(".lb-lightbox")) return;
      if (!img.closest(NOTE_ROOT_SELECTOR)) return;   // 只在小红书归档笔记里接管
      e.preventDefault();
      e.stopPropagation();
      open(img);
    }, true);
  }

  enhance(carousel){
    if(carousel.dataset.lbEnhanced){carousel.lbFit?.();return;}carousel.dataset.lbEnhanced='1';
    const media=carousel.closest('.lb-media'),note=carousel.closest('.lb-note');
    if(!media||!note)return;
    const leaf=note.closest('.workspace-leaf-content');
    // 0929 Owner：钉住时评论拉不到底——右下角状态栏浮在页面上盖住底部，要让开它
    const fit=()=>{let bottom=Math.min(window.innerHeight,leaf?.getBoundingClientRect().bottom||window.innerHeight);const sb=document.querySelector('.status-bar')?.getBoundingClientRect(),nr=note.getBoundingClientRect();if(sb&&sb.height&&sb.top<bottom&&sb.left<nr.right&&sb.right>nr.left)bottom=sb.top;note.style.setProperty('--lb-reader-height',Math.max(200,bottom-note.getBoundingClientRect().top-20)+'px');};
    const resize=new ResizeObserver(fit);carousel.lbFit=fit;resize.observe(leaf||document.documentElement);this.register(()=>resize.disconnect());fit();
    const preview=note.closest('.markdown-preview-view, .markdown-reading-view');
    const setLocked=locked=>{
      note.classList.toggle('lb-media-locked',locked);note.classList.toggle('lb-media-free',!locked);
      preview?.classList.toggle('lb-pane-locked',locked);fit();
    };
    setLocked(false); // 0926 Owner：默认不钉，图/视频按原尺寸跟正文一起滚；要钉住再点右上角的钉
    // 0926 Owner：滚轮停在图片上 = 翻页（一格一张，节流防连跳）；刚打开的笔记直接认它，←/→ 不用先点图。
    this.activeCarousel=carousel;
    if(preview)this.paneWheel(preview);
    const pin=media.createEl('button',{cls:'lb-media-pin'});
    pin.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3h8l-1 6 4 4v2H5v-2l4-4zM12 15v7"/></svg><span class="lb-visually-hidden">取消固定媒体</span>';
    pin.setAttribute('aria-pressed','false');pin.querySelector('span').textContent='固定媒体';
    pin.onclick=()=>{const locked=!note.classList.contains('lb-media-locked');setLocked(locked);pin.setAttribute('aria-pressed',String(locked));pin.querySelector('span').textContent=locked?'取消固定媒体':'固定媒体';};
    const slides=getSlides(carousel);
    const bar=media.createEl('div',{cls:'lb-media-tools'});
    const video=carousel.querySelector('video');
    if(video){
      const speed=bar.createEl('button',{cls:'lb-video-speed',text:'1×'});
      const setRate=value=>{video.playbackRate=Math.min(4,Math.max(.25,Math.round(value*20)/20));speed.setText(Number(video.playbackRate.toFixed(2))+'×');};
      let drag=null,moved=false;
      speed.onpointerdown=e=>{drag={x:e.clientX,rate:video.playbackRate};moved=false;speed.setPointerCapture(e.pointerId);};
      speed.onpointermove=e=>{if(!drag)return;const delta=e.clientX-drag.x;if(Math.abs(delta)>4)moved=true;if(moved)setRate(drag.rate+delta/80);};
      speed.onpointerup=e=>{drag=null;if(speed.hasPointerCapture(e.pointerId))speed.releasePointerCapture(e.pointerId);};
      speed.onpointercancel=()=>{drag=null;};
      speed.onclick=()=>{if(moved){moved=false;return;}const rates=[1,1.25,1.5,2,3];setRate(rates.find(r=>r>video.playbackRate+.01)||1);};
      speed.onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();setRate(video.playbackRate+(e.key==='ArrowRight'?.25:-.25));}};
      return;
    }
    bar.remove(); // Image paging uses the original centered controls and per-image counter.
  }

  // 1003 修「目录页 / 问收藏页有时滚轮滚不动」：Obsidian 同一个标签页换文件时复用同一个 .markdown-preview-view。
  // 以前每篇笔记往它身上挂一个滚轮监听、闭包里攥着那篇笔记、到插件卸载才摘——换到目录页 / 问收藏页后，
  // 看过并「钉住媒体」的旧笔记（已不在页面上，类名还是 lb-media-locked）的监听照样把滚轮转给它那条脱离页面的 .lb-scroll
  // 并 preventDefault → 整页滚不动。现在：每个预览容器只挂一个监听（挂点 PANE_WHEEL_KEY 新旧两份插件共用，后来的替换先前的，
  // 不会两份都翻页），事件来了才现找「这个容器里此刻」被钉住的笔记 / 光标下的图片；找不到就什么都不拦，顺手清掉残留的 lb-pane-locked。
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
            e.preventDefault();const now=Date.now();if(now-(carousel.lbFlipAt||0)<350)return;carousel.lbFlipAt=now;
            const i=Math.max(0,Math.min(list.length-1,getNearestIndex(carousel,list)+(e.deltaY>0?1:-1)));
            carousel.scrollTo({left:list[i].offsetLeft-list[0].offsetLeft,behavior:'smooth'});this.activeCarousel=carousel;return;
          }
        }
      }
      if(Math.abs(e.deltaX)>Math.abs(e.deltaY))return;
      const note=preview.querySelector('.lb-note.lb-media-locked');
      if(!note){if(preview.classList.contains('lb-pane-locked'))preview.classList.remove('lb-pane-locked');return;}
      const scroller=note.querySelector('.lb-scroll');
      if(scroller&&!t.closest('.lb-scroll')){scroller.scrollTop+=e.deltaY*(e.deltaMode===1?16:1);e.preventDefault();}
    };
    preview[KEY]=wheel;preview.addEventListener('wheel',wheel,{passive:false});
    this.register(()=>{preview.removeEventListener('wheel',wheel);if(preview[KEY]===wheel){delete preview[KEY];preview.classList.remove('lb-pane-locked');}});
  }
};

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
  }

  enhance(carousel){
    if(carousel.dataset.lbEnhanced){carousel.lbFit?.();return;}carousel.dataset.lbEnhanced='1';
    const media=carousel.closest('.lb-media'),note=carousel.closest('.lb-note');
    if(!media||!note)return;
    const leaf=note.closest('.workspace-leaf-content');
    const fit=()=>{const bottom=Math.min(window.innerHeight,leaf?.getBoundingClientRect().bottom||window.innerHeight);note.style.setProperty('--lb-reader-height',Math.max(200,bottom-note.getBoundingClientRect().top-20)+'px');};
    const resize=new ResizeObserver(fit);carousel.lbFit=fit;resize.observe(leaf||document.documentElement);this.register(()=>resize.disconnect());fit();
    const preview=note.closest('.markdown-preview-view, .markdown-reading-view');
    const setLocked=locked=>{
      note.classList.toggle('lb-media-locked',locked);note.classList.toggle('lb-media-free',!locked);
      preview?.classList.toggle('lb-pane-locked',locked);fit();
    };
    setLocked(true);
    const wheel=e=>{if(!note.classList.contains('lb-media-locked')||e.ctrlKey||Math.abs(e.deltaX)>Math.abs(e.deltaY))return;
      const scroller=note.querySelector('.lb-scroll');if(scroller&&!e.target.closest('.lb-scroll')){scroller.scrollTop+=e.deltaY*(e.deltaMode===1?16:1);e.preventDefault();}
    };
    preview?.addEventListener('wheel',wheel,{passive:false});
    this.register(()=>{preview?.removeEventListener('wheel',wheel);preview?.classList.remove('lb-pane-locked');});
    const pin=media.createEl('button',{cls:'lb-media-pin'});
    pin.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3h8l-1 6 4 4v2H5v-2l4-4zM12 15v7"/></svg><span class="lb-visually-hidden">取消固定媒体</span>';
    pin.setAttribute('aria-pressed','true');
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
};

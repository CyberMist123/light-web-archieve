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
  return Array.from(carousel.children).filter(
    (el) => el.classList && el.classList.contains("lb-slide")
  );
}

function getNearestIndex(carousel, slides) {
  const left = carousel.scrollLeft;
  let bestIndex = 0;
  let bestDist = Infinity;
  for (let i = 0; i < slides.length; i += 1) {
    const dist = Math.abs(slides[i].offsetLeft - left);
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
      carousel.scrollTo({ left: slides[nextIndex].offsetLeft, behavior: "smooth" });

      this.activeCarousel = carousel;
      event.preventDefault();
      event.stopPropagation();
    });
  }
};

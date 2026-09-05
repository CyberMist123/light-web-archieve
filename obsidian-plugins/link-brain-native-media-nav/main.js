const { Plugin } = require("obsidian");

const CAROUSEL_SELECTOR = '.callout[data-callout="link-brain-media"] .callout-content';
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
  return Array.from(carousel.children).filter((el) => el.tagName === "P");
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

      const noteRoot = carousel.closest(
        ".markdown-preview-view.xhs-note, .markdown-reading-view.xhs-note"
      );
      if (!noteRoot) return;

      const slides = getSlides(carousel);
      if (slides.length < 2) return;

      const currentIndex = getNearestIndex(carousel, slides);
      const delta = event.key === "ArrowRight" ? 1 : -1;
      const nextIndex = Math.max(
        0,
        Math.min(slides.length - 1, currentIndex + delta)
      );

      if (nextIndex === currentIndex) return;

      slides[nextIndex].scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "start"
      });

      this.activeCarousel = carousel;
      event.preventDefault();
      event.stopPropagation();
    });
  }
};

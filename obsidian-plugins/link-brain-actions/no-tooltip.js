// no-tooltip.js — 1031 她：「这些气泡全取消吧」。LWA 自己的界面（类名 lb* 开头的元素和它们里面）悬停不出任何提示气泡：
// 浏览器按 title 画的白框、Obsidian 按 aria-label 画的黑气泡（全局 .tooltip）都不出。别的插件 / Obsidian 自己的界面不动。
// 做法：鼠标移进 LWA 元素时（捕获阶段，抢在 Obsidian 的悬停处理和浏览器的 title 延时之前）——
//   ① 这一串祖先上的 title 挪进 aria-label（读屏照样念，原来有 aria-label 的不覆盖），再删掉 title；
//   ② 给 body 挂 .lb-notip，styles.css 里 body.lb-notip .tooltip 藏掉；移到 LWA 外面就摘掉，别处的提示照常。
// 页面脚本（link_brain/assets/*）不用改：以后新加的 title 也在悬停那一刻被摘掉。
'use strict';
const LB_CLS = /(^|\s)lb[a-z]*-/;
const DEPTH = 40;

function inLwa(el) {
  // 走到 body 就停：body 自己挂着 .lb-notip（和别的 lb 开关类），算进来就处处都是 LWA 了
  for (let n = el, i = 0; n && i < DEPTH && n !== n.ownerDocument?.body; n = n.parentElement, i++) {
    const c = typeof n.className === 'string' ? n.className : typeof n.getAttribute === 'function' ? n.getAttribute('class') : '';   // SVG 的 className 不是字符串
    if (c && LB_CLS.test(c)) return true;
  }
  return false;
}

function stripTitles(el) {
  for (let n = el, i = 0; n && i < DEPTH; n = n.parentElement, i++) {
    if (typeof n.hasAttribute !== 'function' || !n.hasAttribute('title')) continue;
    const t = n.getAttribute('title');
    if (t && !n.hasAttribute('aria-label')) n.setAttribute('aria-label', t);
    n.removeAttribute('title');
  }
}

function onOver(ev) {
  const el = ev.target?.nodeType === 3 ? ev.target.parentElement : ev.target;   // 落在文字节点上 → 取它的元素
  const body = el?.ownerDocument?.body;
  if (!el || !body) return;
  const mine = inLwa(el);
  if (mine) stripTitles(el);
  body.classList.toggle('lb-notip', mine);
}

module.exports = (obsidian, plugin) => ({
  attach() {
    const hook = doc => { if (doc) plugin.registerDomEvent(doc, 'mouseover', onOver, true); };
    if (typeof document !== 'undefined') hook(document);
    // 弹出窗口（把页面拖成独立窗口）各有一个 document
    if (plugin.app.workspace?.on) plugin.registerEvent(plugin.app.workspace.on('window-open', (_w, win) => hook(win?.document)));
    plugin.register(() => { try { document.body.classList.remove('lb-notip'); } catch {} });
  },
  _test: { inLwa, stripTitles, onOver },
});

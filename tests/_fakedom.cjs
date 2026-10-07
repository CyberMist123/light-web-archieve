// 极简假 DOM + 假 Obsidian / Dataview，给页面脚本的 node 测试用（CONVENTIONS §7：node 侧无浏览器）。
// 够跑 lb-page-lib.js + catalog-view.js / chat-view.js / annotate-view.js 整段：
//   - 元素：Obsidian 的 createEl / empty / setText / appendText，加 DOM 常用的 append / remove / closest / querySelector(All) / 事件；
//   - Dataview：同一个容器、同一个 component 反复重跑（rerun 先 innerHTML='' 再整段再跑一遍，和 Dataview 0.5 的 render() 一样）；
//   - vault：内存里的文件表，记每个路径被读 / 写了几次（断言「没重读 5MB 数据」「草稿不写 vault」用）。
// 批次 D 地基（本文件合入后冻结；各线只在自己的 tests/_fake_<线>.cjs 里加东西）——让假宿主像真宿主：
//   - 元素：after / before / next(Element)Sibling / previous(Element)Sibling / ownerDocument / isShown / offsetParent（可设 null）/
//     getClientRects / scrollTo / scrollBy / scrollIntoView / replaceChildren / dispatchEvent；scrollTop、scrollHeight、clientHeight、
//     clientWidth、offsetHeight、offsetWidth、offsetTop 可写；el._rect = {top,left,width,height} 注入 getBoundingClientRect；
//     dataset ↔ data-* 属性、id ↔ id 属性互通；style 有 setProperty / getPropertyValue / removeProperty / cssText。
//   - 焦点：document.activeElement 初始是 body；focus() 只对连在文档上的元素生效并发 blur/focusout → focus/focusin（focusin/out 冒泡）；
//     **被摘下的子树里有焦点 → activeElement 回到 body**（innerHTML='' 清空也算；和 Chromium 一样不发 blur）——没有这条测不出 C4。
//   - 事件：el.fire(type, ev) 只调自己的监听（老行为）；el.dispatchEvent(ev) 按 bubbles 冒泡到祖先和 document；click() 调自己的监听 + onclick。
//   - dataviewBlock：真实祖先链（阅读视图 / mode:'live' 实时预览），容器带 Dataview 写的行内 overflow-x:auto；
//     返回 section、q / qa、component.unload / recreate / detach、可控 ResizeObserver、Notice 记录（setMessage / hide / addButton）。
//   - makeVault 的 on / emit 真能存处理函数并发事件；makeWorkspace 有 activeLeaf / getLeavesOfType / revealLeaf / getLeaf / offref /
//     active-leaf-change；makeMetadataCache 带 lb-page frontmatter；makeApp 一把组装（app.isMobile 开关）。
'use strict';
const fs = require('fs');
const path = require('path');
const { makeMiniMd } = require('./_mini_md.cjs');

const ROOT = path.resolve(__dirname, '..');
const asset = name => fs.readFileSync(path.join(ROOT, 'link_brain', 'assets', name), 'utf8');

const kebab = s => String(s).replace(/[A-Z]/g, c => '-' + c.toLowerCase());
const camel = s => String(s).replace(/-([a-z])/g, (_, c) => c.toUpperCase());

// 行内样式：普通属性照旧直接读写（el.style.width='3px'）；自定义属性（--x）用原名存，setProperty / getPropertyValue 两边都认
class Style {
  setProperty(name, value) { name = String(name); if (name.startsWith('--')) this[name] = String(value); else this[camel(name)] = String(value); }
  getPropertyValue(name) { name = String(name); const v = name.startsWith('--') ? this[name] : this[camel(name)]; return v == null ? '' : String(v); }
  removeProperty(name) { name = String(name); const k = name.startsWith('--') ? name : camel(name); const v = this[k]; delete this[k]; return v == null ? '' : String(v); }
  get cssText() { return Object.keys(this).filter(k => this[k] !== '' && this[k] != null).map(k => `${k.startsWith('--') ? k : kebab(k)}: ${this[k]};`).join(' '); }
  set cssText(v) { for (const k of Object.keys(this)) delete this[k]; for (const part of String(v || '').split(';')) { const i = part.indexOf(':'); if (i > 0) this.setProperty(part.slice(0, i).trim(), part.slice(i + 1).trim()); } }
}

function makeDom() {
  const doc = {};
  const siblings = n => (n.parentNode ? n.parentNode.childNodes : null);
  const nextOf = n => { const s = siblings(n); return s ? s[s.indexOf(n) + 1] || null : null; };
  const prevOf = n => { const s = siblings(n); return s ? s[s.indexOf(n) - 1] || null : null; };
  class TextNode {
    constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
    get parentElement() { return this.parentNode; }
    get nextSibling() { return nextOf(this); }
    get previousSibling() { return prevOf(this); }
    get ownerDocument() { return doc; }
    get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === doc.documentElement; }
    replaceWith(...nodes) { const p = this.parentNode; if (!p) return; const i = p.childNodes.indexOf(this); const flat = flatten(nodes); for (const n of flat) detach(n); p.childNodes.splice(i, 1, ...flat); for (const n of flat) n.parentNode = p; this.parentNode = null; }
    remove() { detach(this); }
  }
  class Fragment {
    constructor() { this.nodeType = 11; this.childNodes = []; }
    append(...nodes) { for (const n of nodes) { const x = typeof n === 'string' ? new TextNode(n) : n; detach(x); x.parentNode = this; this.childNodes.push(x); } }
    appendChild(n) { this.append(n); return n; }
    prepend(...nodes) { const flat = flatten(nodes); for (const n of flat) { detach(n); n.parentNode = this; } this.childNodes.unshift(...flat); }
    get children() { return this.childNodes.filter(n => n instanceof El); }
    get firstChild() { return this.childNodes[0] || null; }
    get textContent() { return this.childNodes.map(n => n.textContent).join(''); }
    all() { const out = []; for (const c of this.children) out.push(c, ...c.all()); return out; }
    querySelector(sel) { const f = parseSel(sel); return this.all().find(e => f.some(x => x(e))) || null; }
    querySelectorAll(sel) { const f = parseSel(sel); return this.all().filter(e => f.some(x => x(e))); }
    // Obsidian 也给 DocumentFragment 加了这几个
    createEl(tag, o = {}) { const el = makeEl(tag, o); this.append(el); return el; }
    createDiv(o = {}) { return this.createEl('div', typeof o === 'string' ? { cls: o } : o); }
    createSpan(o = {}) { return this.createEl('span', typeof o === 'string' ? { cls: o } : o); }
    appendText(t) { this.append(String(t)); }
  }
  const flatten = nodes => nodes.flatMap(n => (n instanceof Fragment ? n.childNodes.splice(0) : [typeof n === 'string' ? new TextNode(n) : n]));
  // 被摘下的子树里有焦点：activeElement 回到 body（Chromium 不对被移除的焦点元素发 blur）
  function dropFocusIn(n) { const a = doc.activeElement; if (a && a !== doc.body && n && (a === n || (typeof n.contains === 'function' && n.contains(a)))) doc.activeElement = doc.body; }
  function detach(n) { const p = n.parentNode; if (p) { const i = p.childNodes.indexOf(n); if (i >= 0) p.childNodes.splice(i, 1); n.parentNode = null; dropFocusIn(n); } }
  function simpleSel(s) {
    const m = s.match(/^([a-z0-9]*)((?:\.[\w-]+|\[[\w-]+(?:=["']?[^\]"']*["']?)?\])*)((?::not\(\.[\w-]+\))*)$/i);
    if (!m) return () => false;
    const tag = m[1].toUpperCase();
    const cls = [...m[2].matchAll(/\.([\w-]+)/g)].map(x => x[1]);
    const attrs = [...m[2].matchAll(/\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g)].map(x => [x[1], x[2]]);
    const nots = [...m[3].matchAll(/:not\(\.([\w-]+)\)/g)].map(x => x[1]);
    return el => (!tag || el.tagName === tag) && cls.every(c => el.classList.contains(c)) && nots.every(c => !el.classList.contains(c))
      && attrs.every(([k, v]) => (v === undefined ? el.getAttribute(k) != null : el.getAttribute(k) === v));
  }
  // 支持后代选择器「.a .b」和子代「.a > .b」（最后一段匹配元素本身，前面几段按顺序在祖先里找）
  function parseSel(sel) {
    return sel.split(',').map(s => s.trim()).filter(Boolean).map(s => {
      const tokens = s.replace(/^:scope\s*>\s*/, '').replace(/\s*>\s*/g, ' > ').split(/\s+/);
      const steps = []; let child = false;
      for (const t of tokens) { if (t === '>') { child = true; continue; } steps.push({ f: simpleSel(t), child }); child = false; }
      const last = steps.pop();
      return el => {
        if (!last.f(el)) return false;
        let i = steps.length - 1, n = el.parentNode, mustBeParent = last.child;
        while (i >= 0 && n) {
          if (n.classList && steps[i].f(n)) { mustBeParent = steps[i].child; i--; }
          else if (mustBeParent) return false;
          n = n.parentNode;
        }
        return i < 0;
      };
    });
  }
  function mkEvent(type, init = {}) {
    const e = { type, bubbles: false, cancelable: true, defaultPrevented: false, propagationStopped: false, isComposing: false, keyCode: 0, ...init };
    e.preventDefault = () => { e.defaultPrevented = true; };
    e.stopPropagation = () => { e.propagationStopped = true; };
    e.stopImmediatePropagation = () => { e.propagationStopped = true; e.immediateStopped = true; };
    return e;
  }
  function callListeners(node, e) {
    e.currentTarget = node;
    for (const fn of [...((node.listeners && node.listeners[e.type]) || [])]) { fn.call(node, e); if (e.immediateStopped) break; }
    if (node !== doc && typeof node['on' + e.type] === 'function') node['on' + e.type](e);
  }
  // 冒泡：自己 → 祖先 → document（bubbles 为假只到自己）
  function emit(target, e) {
    if (!e.target) e.target = target;
    callListeners(target, e);
    if (!e.bubbles) return !e.defaultPrevented;
    for (let n = target.parentNode; n && !e.propagationStopped; n = n.parentNode) if (n.listeners) callListeners(n, e);
    if (!e.propagationStopped && target !== doc && target.isConnected) callListeners(doc, e);
    return !e.defaultPrevented;
  }
  function makeEl(tag, o = {}) {
    const el = new El(tag);
    if (o.cls) el.className = Array.isArray(o.cls) ? o.cls.join(' ') : o.cls;
    if (o.text != null) el.append(o.text instanceof Fragment ? o.text : String(o.text));
    if (o.attr) for (const [k, v] of Object.entries(o.attr)) if (v != null && v !== false) el.setAttribute(k, v === true ? '' : v);
    if (o.type) el.type = o.type;
    if (o.title) el.setAttribute('title', o.title);
    if (o.value != null) el.value = o.value;
    if (o.placeholder) el.placeholder = o.placeholder;
    if (o.href) el.setAttribute('href', o.href);
    return el;
  }
  class El {
    constructor(tag) {
      this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.childNodes = []; this.parentNode = null; this.attrs = {}; this.style = new Style();
      const attrs = this.attrs;
      this.dataset = new Proxy({}, {
        get: (_, k) => (typeof k === 'string' ? attrs['data-' + kebab(k)] : undefined),
        set: (_, k, v) => { attrs['data-' + kebab(k)] = String(v); return true; },
        deleteProperty: (_, k) => { delete attrs['data-' + kebab(k)]; return true; },
        has: (_, k) => ('data-' + kebab(k)) in attrs,
        ownKeys: () => Object.keys(attrs).filter(a => a.startsWith('data-')).map(a => camel(a.slice(5))),
        getOwnPropertyDescriptor: (_, k) => (('data-' + kebab(k)) in attrs ? { enumerable: true, configurable: true, value: attrs['data-' + kebab(k)] } : undefined),
      });
      this._cls = new Set(); this.hidden = false; this.value = ''; this.disabled = false; this.checked = false; this.listeners = {}; this.scrollTop = 0; this.scrollLeft = 0; this.scrollHeight = 0; this.clientHeight = 0;
      this._m = {}; this._rect = null; this._op = undefined;
      const self = this;
      this.classList = {
        add: (...c) => c.forEach(x => self._cls.add(x)), remove: (...c) => c.forEach(x => self._cls.delete(x)),
        toggle: (c, on) => { const want = on === undefined ? !self._cls.has(c) : !!on; want ? self._cls.add(c) : self._cls.delete(c); return want; },
        contains: c => self._cls.has(c), has: c => self._cls.has(c),
        get length() { return self._cls.size; },
        [Symbol.iterator]: () => self._cls[Symbol.iterator](),
      };
    }
    get className() { return [...this._cls].join(' '); }
    set className(v) { this._cls = new Set(String(v || '').split(/\s+/).filter(Boolean)); }
    get id() { return this.attrs.id || ''; }
    set id(v) { this.attrs.id = String(v); }
    get children() { return this.childNodes.filter(n => n instanceof El); }
    get childElementCount() { return this.children.length; }
    get parentElement() { return this.parentNode instanceof El ? this.parentNode : null; }
    get firstChild() { return this.childNodes[0] || null; }
    get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
    get firstElementChild() { return this.children[0] || null; }
    get lastElementChild() { const c = this.children; return c[c.length - 1] || null; }
    get nextSibling() { return nextOf(this); }
    get previousSibling() { return prevOf(this); }
    get nextElementSibling() { let n = nextOf(this); while (n && !(n instanceof El)) n = nextOf(n); return n; }
    get previousElementSibling() { let n = prevOf(this); while (n && !(n instanceof El)) n = prevOf(n); return n; }
    get ownerDocument() { return doc; }
    get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === doc.documentElement; }
    get textContent() { return this.childNodes.map(n => n.textContent).join(''); }
    set textContent(v) { for (const n of this.childNodes) { n.parentNode = null; dropFocusIn(n); } this.childNodes = []; if (v !== '' && v != null) this.append(String(v)); }
    set innerHTML(v) { this.textContent = ''; if (v) this.append(String(v).replace(/<[^>]+>/g, '')); }
    get innerHTML() { return this.textContent; }
    // 量尺寸：显式写过的值优先，其次注入的 _rect，都没有就是 0
    get clientWidth() { return this._m.clientWidth ?? this._rect?.width ?? 0; }
    set clientWidth(v) { this._m.clientWidth = v; }
    get offsetWidth() { return this._m.offsetWidth ?? this._rect?.width ?? 0; }
    set offsetWidth(v) { this._m.offsetWidth = v; }
    get offsetHeight() { return this._m.offsetHeight ?? this._rect?.height ?? 0; }
    set offsetHeight(v) { this._m.offsetHeight = v; }
    get offsetTop() { return this._m.offsetTop ?? this._rect?.top ?? 0; }
    set offsetTop(v) { this._m.offsetTop = v; }
    get offsetLeft() { return this._m.offsetLeft ?? this._rect?.left ?? 0; }
    set offsetLeft(v) { this._m.offsetLeft = v; }
    // 显示与否：连在文档上，祖先里没有 hidden / display:none；offsetParent 被显式设成 null 也算看不见（Obsidian 的 isShown 就看它）
    _shownRaw() { if (!this.isConnected) return false; for (let n = this; n instanceof El; n = n.parentNode) if (n.hidden || n.style.display === 'none') return false; return true; }
    get offsetParent() { if (this._op !== undefined) return this._op; return this._shownRaw() ? (this.parentElement || doc.body) : null; }
    set offsetParent(v) { this._op = v; }
    isShown() { return this._shownRaw() && this.offsetParent !== null; }
    getClientRects() { return this.isShown() ? [this.getBoundingClientRect()] : []; }
    createEl(tag, o = {}) { const el = makeEl(tag, typeof o === 'string' ? { cls: o } : o); if (o && o.prepend) this.prepend(el); else this.append(el); return el; }
    createDiv(o = {}) { return this.createEl('div', typeof o === 'string' ? { cls: o } : o); }
    createSpan(o = {}) { return this.createEl('span', typeof o === 'string' ? { cls: o } : o); }
    addClass(...c) { this.classList.add(...c); }
    removeClass(...c) { this.classList.remove(...c); }
    toggleClass(c, on) { this.classList.toggle(c, on); }
    hasClass(c) { return this.classList.contains(c); }
    append(...nodes) { for (const n of flatten(nodes)) { detach(n); n.parentNode = this; this.childNodes.push(n); } }
    appendChild(n) { this.append(n); return n; }
    insertBefore(n, ref) { if (!ref) { this.append(n); return n; } const flat = flatten([n]); for (const x of flat) detach(x); this.childNodes.splice(this.childNodes.indexOf(ref), 0, ...flat); for (const x of flat) x.parentNode = this; return n; }
    prepend(...nodes) { const flat = flatten(nodes); for (const n of flat) { detach(n); n.parentNode = this; } this.childNodes.unshift(...flat); }
    after(...nodes) { const p = this.parentNode; if (!p) return; const flat = flatten(nodes).filter(n => n !== this); for (const n of flat) detach(n); p.childNodes.splice(p.childNodes.indexOf(this) + 1, 0, ...flat); for (const n of flat) n.parentNode = p; }
    before(...nodes) { const p = this.parentNode; if (!p) return; const flat = flatten(nodes).filter(n => n !== this); for (const n of flat) detach(n); p.childNodes.splice(p.childNodes.indexOf(this), 0, ...flat); for (const n of flat) n.parentNode = p; }
    replaceChildren(...nodes) { this.textContent = ''; this.append(...nodes); }
    appendText(t) { this.append(String(t)); }
    empty() { this.textContent = ''; }
    setText(t) { this.textContent = t; }
    getText() { return this.textContent; }
    detach() { detach(this); }
    remove() { detach(this); }
    replaceWith(...n) { TextNode.prototype.replaceWith.call(this, ...n); }
    setAttribute(k, v) { if (k === 'style') this.style.cssText = String(v); this.attrs[k] = String(v); }
    setAttr(k, v) { if (v == null || v === false) this.removeAttribute(k); else this.setAttribute(k, v === true ? '' : v); }
    getAttribute(k) { return this.attrs[k] ?? null; }
    hasAttribute(k) { return k in this.attrs; }
    removeAttribute(k) { delete this.attrs[k]; }
    toggleAttribute(k, on) { const want = on === undefined ? !(k in this.attrs) : !!on; if (want) this.attrs[k] = ''; else delete this.attrs[k]; return want; }
    matches(sel) { return parseSel(sel).some(f => f(this)); }
    closest(sel) { const fs_ = parseSel(sel); let n = this; while (n instanceof El) { if (fs_.some(f => f(n))) return n; n = n.parentNode; } return null; }
    all() { const out = []; for (const c of this.children) out.push(c, ...c.all()); return out; }
    querySelector(sel) { const f = parseSel(sel); return this.all().find(e => f.some(x => x(e))) || null; }
    querySelectorAll(sel) { const f = parseSel(sel); return this.all().filter(e => f.some(x => x(e))); }
    find(sel) { return this.querySelector(sel); }
    findAll(sel) { return this.querySelectorAll(sel); }
    contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
    addEventListener(t, fn, opts) {
      if (typeof fn !== 'function') return;
      const list = (this.listeners[t] = this.listeners[t] || []);
      if (opts && typeof opts === 'object' && opts.once) { const self = this; const w = function (e) { self.removeEventListener(t, w); return fn.call(this, e); }; w._orig = fn; list.push(w); }
      else list.push(fn);
    }
    removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter(f => f !== fn && f._orig !== fn); }
    fire(t, ev = {}) { const e = { type: t, target: this, preventDefault() {}, stopPropagation() {}, ...ev }; for (const fn of [...(this.listeners[t] || [])]) fn(e); if (typeof this['on' + t] === 'function') return this['on' + t](e); }
    dispatchEvent(ev) { const e = ev && typeof ev.preventDefault === 'function' ? ev : mkEvent(ev.type, ev); return emit(this, e); }
    getBoundingClientRect() {
      const r = this._rect || {}; const top = r.top || 0, left = r.left || 0, width = r.width || 0, height = r.height || 0;
      return { top, left, width, height, bottom: r.bottom ?? top + height, right: r.right ?? left + width, x: left, y: top };
    }
    scrollTo(a, b) { if (a && typeof a === 'object') { if (a.top != null) this.scrollTop = a.top; if (a.left != null) this.scrollLeft = a.left; } else { if (a != null) this.scrollLeft = a; if (b != null) this.scrollTop = b; } }
    scrollBy(a, b) { if (a && typeof a === 'object') { this.scrollTop += a.top || 0; this.scrollLeft += a.left || 0; } else { this.scrollLeft += a || 0; this.scrollTop += b || 0; } }
    scrollIntoView(opts) { this._scrolledIntoView = (this._scrolledIntoView || 0) + 1; this._scrollIntoViewOpts = opts; }
    focus() {
      if (!this.isConnected || this.disabled || doc.activeElement === this) return;
      const prev = doc.activeElement && doc.activeElement !== doc.body ? doc.activeElement : null;
      doc.activeElement = this;
      if (prev) { emit(prev, mkEvent('blur', { relatedTarget: this })); emit(prev, mkEvent('focusout', { relatedTarget: this, bubbles: true })); }
      emit(this, mkEvent('focus', { relatedTarget: prev })); emit(this, mkEvent('focusin', { relatedTarget: prev, bubbles: true }));
    }
    blur() {
      if (doc.activeElement !== this) return;
      doc.activeElement = doc.body;
      emit(this, mkEvent('blur', { relatedTarget: null })); emit(this, mkEvent('focusout', { relatedTarget: null, bubbles: true }));
    }
    setSelectionRange(s, e) { this.selectionStart = s; this.selectionEnd = e ?? s; }
    select() { this.selectionStart = 0; this.selectionEnd = String(this.value || '').length; }
    requestSubmit() { return this.onsubmit?.({ preventDefault() {} }); }
    click() {
      const e = mkEvent('click', { detail: 1, button: 0 }); e.target = this; e.currentTarget = this;
      for (const fn of [...(this.listeners.click || [])]) fn.call(this, e);
      return this.onclick?.(e);
    }
  }
  doc.documentElement = new El('html');
  doc.body = doc.documentElement.createEl('body');
  doc.head = doc.documentElement.createEl('head');
  doc.activeElement = doc.body;
  doc.listeners = {};
  doc.nodeType = 9;
  doc._hasFocus = true;
  doc.hasFocus = () => !!doc._hasFocus;
  doc.createElement = t => new El(t);
  doc.createElementNS = (ns, t) => new El(t);
  doc.createTextNode = t => new TextNode(t);
  doc.createDocumentFragment = () => new Fragment();
  doc.createTreeWalker = rootEl => {
    const nodes = []; (function walk(n) { for (const c of n.childNodes) { if (c instanceof TextNode) nodes.push(c); else if (c instanceof El) walk(c); } })(rootEl);
    let i = -1; return { get currentNode() { return nodes[i]; }, nextNode() { i++; return i < nodes.length ? nodes[i] : null; } };
  };
  doc.addEventListener = (t, fn) => { if (typeof fn === 'function') (doc.listeners[t] = doc.listeners[t] || []).push(fn); };
  doc.removeEventListener = (t, fn) => { doc.listeners[t] = (doc.listeners[t] || []).filter(f => f !== fn); };
  doc.dispatchEvent = ev => { const e = ev && typeof ev.preventDefault === 'function' ? ev : mkEvent(ev.type, ev); if (!e.target) e.target = doc; callListeners(doc, e); return !e.defaultPrevented; };
  doc.querySelectorAll = s => doc.documentElement.querySelectorAll(s);
  doc.querySelector = s => doc.documentElement.querySelector(s);
  doc.getElementById = id => doc.documentElement.all().find(e => e.attrs.id === id) || null;
  // 事件构造（测试里造带 isComposing / keyCode 的键盘事件、带 relatedTarget 的焦点事件）
  class Event {
    constructor(type, init = {}) { Object.assign(this, { bubbles: false, cancelable: true, isComposing: false, keyCode: 0, ...init }); this.type = type; this.defaultPrevented = false; this.propagationStopped = false; }
    preventDefault() { this.defaultPrevented = true; }
    stopPropagation() { this.propagationStopped = true; }
    stopImmediatePropagation() { this.propagationStopped = true; this.immediateStopped = true; }
  }
  class KeyboardEvent extends Event {}
  class MouseEvent extends Event {}
  class FocusEvent extends Event {}
  // Obsidian 的全局 createEl / createDiv / createSpan / createFragment
  const globals = {
    createEl: (tag, o = {}, cb) => { const el = makeEl(tag, typeof o === 'string' ? { cls: o } : o); cb?.(el); return el; },
    createDiv: (o = {}, cb) => globals.createEl('div', o, cb),
    createSpan: (o = {}, cb) => globals.createEl('span', o, cb),
    createFragment: cb => { const f = new Fragment(); cb?.(f); return f; },
  };
  return { El, TextNode, Fragment, document: doc, Event, KeyboardEvent, MouseEvent, FocusEvent, event: mkEvent, ...globals };
}

// 假文件对象（Obsidian TFile 的形状）
function fileOf(p, stat) {
  const slash = p.lastIndexOf('/'), name = p.slice(slash + 1), dot = name.lastIndexOf('.');
  return { path: p, name, basename: dot > 0 ? name.slice(0, dot) : name, extension: dot > 0 ? name.slice(dot + 1) : '', parent: { path: slash > 0 ? p.slice(0, slash) : '/' }, stat };
}

// 假 vault：files = {path: string}；记读写次数；on / emit 真能存处理函数，set() 发 modify（新文件发 create）
function makeVault(files = {}) {
  const disk = new Map(Object.entries(files));
  const mtimes = new Map();
  let clock = 1000;
  const reads = {}, writes = {};
  const handlers = {};
  const touch = p => mtimes.set(p, ++clock);
  for (const p of disk.keys()) touch(p);
  const statOf = p => (disk.has(p) ? { mtime: mtimes.get(p), ctime: mtimes.get(p), size: disk.get(p).length } : null);
  const adapter = {
    async read(p) { reads[p] = (reads[p] || 0) + 1; if (!disk.has(p)) throw new Error('ENOENT ' + p); return disk.get(p); },
    async write(p, s) { writes[p] = (writes[p] || 0) + 1; disk.set(p, s); touch(p); },
    async append(p, s) { writes[p] = (writes[p] || 0) + 1; disk.set(p, (disk.get(p) || '') + s); touch(p); },
    async rename(a, b) { if (!disk.has(a)) throw new Error('ENOENT ' + a); disk.set(b, disk.get(a)); disk.delete(a); touch(b); },
    async exists(p) { return disk.has(p) || [...disk.keys()].some(k => k.startsWith(p + '/')); },
    async remove(p) { if (!disk.has(p)) throw new Error('ENOENT ' + p); disk.delete(p); },
    async mkdir() {},
    async list(dir) {
      const pre = dir === '/' || dir === '' ? '' : dir.replace(/\/$/, '') + '/';
      const files_ = new Set(), folders = new Set();
      for (const k of disk.keys()) { if (!k.startsWith(pre)) continue; const rest = k.slice(pre.length); const i = rest.indexOf('/'); if (i < 0) files_.add(k); else folders.add(pre + rest.slice(0, i)); }
      return { files: [...files_], folders: [...folders] };
    },
    async stat(p) { return statOf(p); },
    getResourcePath: p => 'app://' + p,
    getBasePath: () => '/fake-vault',
  };
  const vault = {
    adapter,
    configDir: '.obsidian',
    getAbstractFileByPath(p) { if (p === '_archive' || [...disk.keys()].some(k => k.startsWith(p + '/'))) return { path: p, children: [] }; return disk.has(p) ? fileOf(p, statOf(p)) : null; },
    getMarkdownFiles() { return [...disk.keys()].filter(k => k.endsWith('.md')).map(k => fileOf(k, statOf(k))); },
    getFiles() { return [...disk.keys()].map(k => fileOf(k, statOf(k))); },
    async read(f) { return adapter.read(f.path || f); },
    async cachedRead(f) { return adapter.read(f.path || f); },
    on(name, fn) { const ref = { name, fn, e: vault }; (handlers[name] = handlers[name] || []).push(ref); return ref; },
    offref(ref) { if (ref && handlers[ref.name]) handlers[ref.name] = handlers[ref.name].filter(r => r !== ref); },
    trigger(name, ...a) { for (const r of [...(handlers[name] || [])]) r.fn(...a); },
  };
  const emit = (name, file) => { const f = typeof file === 'string' ? fileOf(file, statOf(file)) : file; vault.trigger(name, f); };
  return {
    vault, disk, reads, writes, handlers,
    set(p, s) { const existed = disk.has(p); disk.set(p, s); touch(p); emit(existed ? 'modify' : 'create', p); },
    get: p => disk.get(p),
    emit,
    resetCounts() { for (const k of Object.keys(reads)) delete reads[k]; for (const k of Object.keys(writes)) delete writes[k]; },
  };
}

// 假 workspace：事件可摘（offref）；activeLeaf / getLeavesOfType / revealLeaf / getLeaf / setActiveLeaf（发 active-leaf-change）
function makeLeaf({ containerEl = null, file = null, type = 'markdown' } = {}) {
  const leaf = {
    opened: [], view: { containerEl, file, getViewType: () => type, leaf: null },
    async openFile(f) { leaf.opened.push(f); leaf.view.file = f; },
    getViewState: () => ({ type, state: { file: leaf.view.file?.path, mode: 'preview' } }),
    async setViewState(s) { leaf.viewState = s; },
    detach() { leaf.detached = true; },
  };
  leaf.view.leaf = leaf;
  return leaf;
}
function makeWorkspace() {
  const handlers = {};
  const ws = {
    handlers, opened: [], revealed: [], gotLeaves: [], leaves: [], layoutReady: [], activeLeaf: null, activeFile: null,
    on(name, fn) { const ref = { name, fn, e: ws }; (handlers[name] = handlers[name] || []).push(fn); ref._fn = fn; return ref; },
    offref(ref) { if (ref && handlers[ref.name]) handlers[ref.name] = handlers[ref.name].filter(f => f !== ref.fn); },
    off(name, fn) { handlers[name] = (handlers[name] || []).filter(f => f !== fn); },
    trigger(name, ...a) { for (const fn of [...(handlers[name] || [])]) fn(...a); },
    openLinkText(...a) { this.opened.push(a); },
    getLeavesOfType(type) { return this.leaves.filter(l => (l.view?.getViewType?.() || l.type) === type); },
    async revealLeaf(leaf) { this.revealed.push(leaf); this.setActiveLeaf(leaf); },
    getLeaf(newLeaf) { const leaf = makeLeaf(); this.gotLeaves.push(newLeaf ?? null); this.leaves.push(leaf); return leaf; },
    setActiveLeaf(leaf) { this.activeLeaf = leaf; this.trigger('active-leaf-change', leaf); },
    getMostRecentLeaf() { return this.activeLeaf; },
    getActiveFile() { return this.activeFile; },
    getActiveViewOfType() { return this.activeLeaf?.view || null; },
    iterateAllLeaves(cb) { for (const l of this.leaves) cb(l); },
    onLayoutReady(fn) { this.layoutReady.push(fn); },   // 不自动调：插件 onload 里的启动检查会起计时器
  };
  return ws;
}

// 假 metadataCache：frontmatter = {路径: {lb-page: 'catalog', ...}}
function makeMetadataCache(frontmatter = {}) {
  return {
    frontmatter,
    getFileCache(f) { const fm = frontmatter[f?.path ?? f]; return fm ? { frontmatter: fm } : null; },
    getCache(p) { const fm = frontmatter[p]; return fm ? { frontmatter: fm } : null; },
  };
}

// 一把组装：app = {vault, workspace, metadataCache, plugins, isMobile}；plugin 为 null = 插件没启用
function makeApp({ files = {}, plugin = null, frontmatter = {}, isMobile = false, V = null } = {}) {
  const vaultBox = V || makeVault(files);
  const workspace = makeWorkspace();
  const enabled = [];
  const app = {
    vault: vaultBox.vault, workspace, metadataCache: makeMetadataCache(frontmatter), isMobile,
    plugins: { plugins: plugin ? { 'link-brain-actions': plugin } : {}, enabled, async enablePlugin(id) { enabled.push(id); }, async disablePlugin() {} },
    fileManager: { async processFrontMatter(file, fn) { const fm = frontmatter[file.path] = frontmatter[file.path] || {}; fn(fm); } },
  };
  return { app, V: vaultBox, workspace };
}

// 可控 ResizeObserver：记下所有实例；trigger(width, height) 给每个还在观察的实例回调一次
function makeResizeObservers() {
  const instances = [];
  class ResizeObserver {
    constructor(cb) { this.cb = cb; this.targets = new Set(); this.disconnected = false; instances.push(this); }
    observe(el) { this.targets.add(el); this.disconnected = false; }
    unobserve(el) { this.targets.delete(el); }
    disconnect() { this.targets.clear(); this.disconnected = true; }
  }
  const trigger = (width = 1000, height = 800) => {
    for (const ro of instances) if (!ro.disconnected && ro.targets.size) ro.cb([...ro.targets].map(target => ({ target, contentRect: { width, height, top: 0, left: 0 } })), ro);
  };
  return { ResizeObserver, instances, trigger, live: () => instances.filter(ro => !ro.disconnected && ro.targets.size) };
}

// 起一个 Dataview 块：同一个容器 + 同一个 component 可以 rerun（模拟 2.5 秒刷新）
// 真实祖先链（Obsidian 1.14.4 + Dataview 0.5.68）：
//   阅读视图 .workspace-leaf(.mod-active) > .workspace-leaf-content[data-type=markdown] > .view-content > .markdown-reading-view >
//            .markdown-preview-view.markdown-rendered（= A.host / A.scroller，滚动容器）> .markdown-preview-sizer.markdown-preview-section >
//            .el-pre（= A.section）> .block-language-dataviewjs（= A.container，行内 overflow-x:auto）
//   mode:'live' .view-content > .markdown-source-view.mod-cm6.is-live-preview > .cm-editor > .cm-scroller（= A.host / A.scroller）> .cm-sizer >
//            .cm-contentContainer > .cm-content > .cm-preview-code-block.cm-embed-block.cm-lang-dataviewjs（= A.section）> 容器 + .edit-block-button
// 选项：active:false（叶子不带 .mod-active）；params 里可覆盖 setTimeout / clearTimeout / Date 等（tests/_clock.cjs）
function dataviewBlock({ dom, app, code, params = {}, folder = '', mode = 'reading', active = true } = {}) {
  const D = dom.document;
  const leaf = D.body.createEl('div', { cls: 'workspace-leaf' + (active ? ' mod-active' : '') });
  const leafContent = leaf.createEl('div', { cls: 'workspace-leaf-content', attr: { 'data-type': 'markdown', 'data-mode': mode === 'live' ? 'source' : 'preview' } });
  const viewContent = leafContent.createEl('div', { cls: 'view-content' });
  let host, section;
  if (mode === 'live') {
    const sv = viewContent.createEl('div', { cls: 'markdown-source-view cm-s-obsidian mod-cm6 is-live-preview' });
    const editor = sv.createEl('div', { cls: 'cm-editor' });
    host = editor.createEl('div', { cls: 'cm-scroller' });
    const sizer = host.createEl('div', { cls: 'cm-sizer' });
    const content = sizer.createEl('div', { cls: 'cm-contentContainer' }).createEl('div', { cls: 'cm-content', attr: { contenteditable: 'true' } });
    content.createEl('div', { cls: 'cm-line', text: '---' });
    section = content.createEl('div', { cls: 'cm-preview-code-block cm-embed-block markdown-rendered cm-lang-dataviewjs', attr: { contenteditable: 'false' } });
  } else {
    host = viewContent.createEl('div', { cls: 'markdown-reading-view' }).createEl('div', { cls: 'markdown-preview-view markdown-rendered' });
    section = host.createEl('div', { cls: 'markdown-preview-sizer markdown-preview-section' }).createEl('div', { cls: 'el-pre' });
  }
  const leafObj = makeLeaf({ containerEl: leafContent });
  const notices = [], noticeLog = [], alerts = [], confirms = [];
  const ro = makeResizeObservers();
  class FakeNotice {
    constructor(message, timeout) {
      this.timeout = timeout; this.hidden = false; this.buttons = []; this.messages = [];
      this.containerEl = this.noticeEl = D.createElement('div'); this.containerEl.className = 'notice';
      this.messageEl = this.containerEl.createDiv({ cls: 'notice-message' });
      this.setMessage(message);
      notices.push(this.message); noticeLog.push(this);
    }
    setMessage(m) { this.messageEl.textContent = ''; if (m && typeof m === 'object' && m.nodeType === 11) this.messageEl.append(m); else this.messageEl.append(String(m ?? '')); this.message = this.messageEl.textContent; this.messages.push(this.message); return this; }
    setAutoHide(ms) { this.timeout = ms; return this; }
    hide() { this.hidden = true; }
    // Obsidian 1.14 的 Notice.addButton：点了先 hide 再回调
    addButton(label, cb) {
      const box = this.buttonContainerEl || (this.buttonContainerEl = this.containerEl.createDiv({ cls: 'notice-button-container' }));
      const el = box.createDiv({ cls: 'notice-cta', text: label });
      el.addEventListener('click', e => { this.hide(); cb(e); });
      this.buttons.push({ label, el, click: () => el.click() });
      return this;
    }
  }
  let mkContainer, cur;
  const newComponent = () => {
    const comp = {
      events: [], cleanups: [], loaded: true, renders: 0,
      registerEvent(ref) { this.events.push(ref); },
      register(fn) { this.cleanups.push(fn); },
      registerDomEvent(el, type, fn, opts) { el.addEventListener(type, fn, opts); this.cleanups.push(() => el.removeEventListener(type, fn, opts)); },
      registerInterval(id) { this.cleanups.push(() => clearInterval(id)); return id; },
      addChild(c) { try { c?.load?.(); } catch {} this.cleanups.push(() => c?.unload?.()); return c; },
      render() { this.renders++; return A.rerun(); },   // Dataview 的 DataviewJSRenderer.render()：清空再跑
      unload() {   // Obsidian Component.unload：登记的回调后进先出；registerEvent 的事件经 offref 摘掉
        if (!this.loaded) return; this.loaded = false;
        while (this.cleanups.length) { try { this.cleanups.pop()(); } catch {} }
        for (const ref of this.events.splice(0)) { try { (ref?.e || app?.workspace)?.offref?.(ref); } catch {} }
      },
    };
    return comp;
  };
  mkContainer = () => {
    const container = D.createElement('div');
    container.className = 'block-language-dataviewjs node-insert-event';
    container.style.overflowX = 'auto';   // Dataview 0.5.68 main.js:20535-20537 在 dataviewjs(el) 里写的行内样式
    const editBtn = mode === 'live' ? section.querySelector('.edit-block-button') : null;
    if (editBtn) section.insertBefore(container, editBtn); else section.append(container);
    if (mode === 'live' && !editBtn) section.createEl('div', { cls: 'edit-block-button', attr: { 'aria-label': 'Edit this block' } });
    const component = newComponent();
    // dv.el / paragraph / header / span：和 Dataview 一样把字符串按行内 markdown 渲染（**粗体**、`代码`、![[图]]），手机兜底页用
    const md = makeMiniMd();
    const dv = { container, component, current: () => ({ file: { folder, path: (folder ? folder + '/' : '') + 'page.md' } }), page: () => null,
      el(tag, text, attrs = {}) { const el = container.createEl(tag, attrs); md.renderInline(text, el); return el; },
      paragraph(t, attrs) { return dv.el('p', t, attrs); },
      header(level, text, attrs) { return dv.el('h' + level, text, attrs); },
      span(text, attrs) { return dv.el('span', text, attrs); } };
    return { container, component, dv };
  };
  cur = mkContainer();
  const window = { alert(m) { alerts.push(m); }, confirm(m) { confirms.push(m); return false; }, innerHeight: 800, innerWidth: 1200, getSelection: () => ({ toString: () => '' }),
    document: D, Event: dom.Event, KeyboardEvent: dom.KeyboardEvent, MouseEvent: dom.MouseEvent, FocusEvent: dom.FocusEvent };
  // 注意：这个 window 故意没有 addEventListener——页面脚本会退回挂在 document 上，测试按 document.listeners 派发键盘事件（老行为）
  const baseEnv = () => ({
    dv: cur.dv, app, document: D, window, Notice: FakeNotice, ResizeObserver: ro.ResizeObserver, NodeFilter: { SHOW_TEXT: 4 },
    requestAnimationFrame: f => setTimeout(f, 0), getComputedStyle: () => ({ overflowY: 'visible' }), innerWidth: 1200, innerHeight: 800,
    MutationObserver: class { observe() {} disconnect() {} takeRecords() { return []; } },
    createEl: dom.createEl, createDiv: dom.createDiv, createSpan: dom.createSpan, createFragment: dom.createFragment,
    setTimeout, clearTimeout, setInterval, clearInterval,
  });
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  let fn = null, names = null;
  const run = () => {
    const env = { ...baseEnv(), ...params };
    const keys = Object.keys(env);
    if (!fn || names.join() !== keys.join()) { names = keys; fn = new AsyncFunction(...keys, code); }
    return fn(...keys.map(k => env[k]));
  };
  const inSection = () => [section];
  const A = {
    get dv() { return cur.dv; }, get container() { return cur.container; }, get component() { return cur.component; },
    host, scroller: host, section, leaf, leafContent, view: viewContent, leafObj, mode,
    notices, noticeLog, alerts, confirms, window, resize: ro, ResizeObserver: ro.ResizeObserver, run,
    async rerun() { cur.container.innerHTML = ''; await run(); },
    // section 重画 / CM 重建 widget：旧 component 卸载、旧容器摘掉，同一个 section 里换新容器和新 component 再跑
    async recreate() { cur.component.unload(); cur.container.remove(); cur = mkContainer(); await run(); },
    // 同一窗格换页：component 卸载（register 的回调、registerEvent 的事件都摘掉）+ 这一段从文档里摘掉
    detach() { cur.component.unload(); section.remove(); },
    q: sel => { for (const s of inSection()) { const hit = s.querySelector(sel); if (hit) return hit; } return null; },
    qa: sel => inSection().flatMap(s => s.querySelectorAll(sel)),
    activate() { if (app?.workspace) { if (typeof app.workspace.setActiveLeaf === 'function') app.workspace.setActiveLeaf(leafObj); else app.workspace.activeLeaf = leafObj; } return leafObj; },
  };
  return A;
}

module.exports = { ROOT, asset, makeDom, makeVault, makeWorkspace, makeLeaf, makeMetadataCache, makeApp, makeResizeObservers, fileOf, dataviewBlock };

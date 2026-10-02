// 极简假 DOM + 假 Obsidian / Dataview，给页面脚本的 node 测试用（CONVENTIONS §7：node 侧无浏览器）。
// 够跑 lb-page-lib.js + catalog-view.js / chat-view.js / annotate-view.js 整段：
//   - 元素：Obsidian 的 createEl / empty / setText / appendText，加 DOM 常用的 append / remove / closest / querySelector(All) / 事件；
//   - Dataview：同一个容器、同一个 component 反复重跑（rerun 先 innerHTML='' 再整段再跑一遍，和 Dataview 0.5 的 render() 一样）；
//   - vault：内存里的文件表，记每个路径被读 / 写了几次（断言「没重读 5MB 数据」「草稿不写 vault」用）。
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const asset = name => fs.readFileSync(path.join(ROOT, 'link_brain', 'assets', name), 'utf8');

function makeDom() {
  const doc = {};
  class TextNode {
    constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
    get parentElement() { return this.parentNode; }
    replaceWith(...nodes) { const p = this.parentNode; if (!p) return; const i = p.childNodes.indexOf(this); const flat = flatten(nodes); for (const n of flat) detach(n); p.childNodes.splice(i, 1, ...flat); for (const n of flat) n.parentNode = p; this.parentNode = null; }
    remove() { detach(this); }
  }
  class Fragment {
    constructor() { this.nodeType = 11; this.childNodes = []; }
    append(...nodes) { for (const n of nodes) { const x = typeof n === 'string' ? new TextNode(n) : n; detach(x); x.parentNode = this; this.childNodes.push(x); } }
  }
  const flatten = nodes => nodes.flatMap(n => (n instanceof Fragment ? n.childNodes.splice(0) : [typeof n === 'string' ? new TextNode(n) : n]));
  function detach(n) { const p = n.parentNode; if (p) { const i = p.childNodes.indexOf(n); if (i >= 0) p.childNodes.splice(i, 1); n.parentNode = null; } }
  function parseSel(sel) {
    return sel.split(',').map(s => s.trim()).filter(Boolean).map(s => {
      const m = s.replace(/^:scope\s*>\s*/, '').match(/^([a-z0-9]*)((?:\.[\w-]+)*)((?::not\(\.[\w-]+\))*)$/i);
      if (!m) return () => false;
      const tag = m[1].toUpperCase(), cls = m[2].split('.').filter(Boolean), nots = [...m[3].matchAll(/:not\(\.([\w-]+)\)/g)].map(x => x[1]);
      return el => (!tag || el.tagName === tag) && cls.every(c => el.classList.contains(c)) && nots.every(c => !el.classList.contains(c));
    });
  }
  class El {
    constructor(tag) {
      this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.childNodes = []; this.parentNode = null; this.attrs = {}; this.style = {}; this.dataset = {};
      this._cls = new Set(); this.hidden = false; this.value = ''; this.disabled = false; this.checked = false; this.listeners = {}; this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 0;
      const self = this;
      this.classList = {
        add: (...c) => c.forEach(x => self._cls.add(x)), remove: (...c) => c.forEach(x => self._cls.delete(x)),
        toggle: (c, on) => { const want = on === undefined ? !self._cls.has(c) : !!on; want ? self._cls.add(c) : self._cls.delete(c); return want; },
        contains: c => self._cls.has(c), has: c => self._cls.has(c),
      };
    }
    get className() { return [...this._cls].join(' '); }
    set className(v) { this._cls = new Set(String(v || '').split(/\s+/).filter(Boolean)); }
    get children() { return this.childNodes.filter(n => n instanceof El); }
    get parentElement() { return this.parentNode instanceof El ? this.parentNode : null; }
    get firstChild() { return this.childNodes[0] || null; }
    get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === doc.documentElement; }
    get textContent() { return this.childNodes.map(n => n.textContent).join(''); }
    set textContent(v) { for (const n of this.childNodes) n.parentNode = null; this.childNodes = []; if (v !== '' && v != null) this.append(String(v)); }
    set innerHTML(v) { this.textContent = ''; if (v) this.append(String(v).replace(/<[^>]+>/g, '')); }
    get innerHTML() { return this.textContent; }
    createEl(tag, o = {}) {
      const el = new El(tag);
      if (o.cls) el.className = o.cls;
      if (o.text != null) el.append(String(o.text));
      if (o.attr) for (const [k, v] of Object.entries(o.attr)) el.setAttribute(k, v);
      if (o.type) el.type = o.type;
      this.append(el); return el;
    }
    createDiv(o = {}) { return this.createEl('div', o); }
    createSpan(o = {}) { return this.createEl('span', o); }
    addClass(...c) { this.classList.add(...c); }
    append(...nodes) { for (const n of flatten(nodes)) { detach(n); n.parentNode = this; this.childNodes.push(n); } }
    appendChild(n) { this.append(n); return n; }
    prepend(...nodes) { const flat = flatten(nodes); for (const n of flat) { detach(n); n.parentNode = this; } this.childNodes.unshift(...flat); }
    appendText(t) { this.append(String(t)); }
    empty() { this.textContent = ''; }
    setText(t) { this.textContent = t; }
    remove() { detach(this); }
    replaceWith(...n) { TextNode.prototype.replaceWith.call(this, ...n); }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return this.attrs[k] ?? null; }
    removeAttribute(k) { delete this.attrs[k]; }
    matches(sel) { return parseSel(sel).some(f => f(this)); }
    closest(sel) { const fs_ = parseSel(sel); let n = this; while (n instanceof El) { if (fs_.some(f => f(n))) return n; n = n.parentNode; } return null; }
    all() { const out = []; for (const c of this.children) out.push(c, ...c.all()); return out; }
    querySelector(sel) { const f = parseSel(sel); return this.all().find(e => f.some(x => x(e))) || null; }
    querySelectorAll(sel) { const f = parseSel(sel); return this.all().filter(e => f.some(x => x(e))); }
    contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
    removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter(f => f !== fn); }
    fire(t, ev = {}) { const e = { type: t, target: this, preventDefault() {}, stopPropagation() {}, ...ev }; for (const fn of [...(this.listeners[t] || [])]) fn(e); if (typeof this['on' + t] === 'function') return this['on' + t](e); }
    getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }; }
    focus() { doc.activeElement = this; }
    blur() { if (doc.activeElement === this) doc.activeElement = null; }
    setSelectionRange() {}
    requestSubmit() { return this.onsubmit?.({ preventDefault() {} }); }
    click() { return this.onclick?.({ preventDefault() {}, stopPropagation() {}, target: this, detail: 1 }); }
  }
  doc.documentElement = new El('html');
  doc.body = doc.documentElement.createEl('body');
  doc.head = doc.documentElement.createEl('head');
  doc.activeElement = null;
  doc.listeners = {};
  doc.createElement = t => new El(t);
  doc.createElementNS = (ns, t) => new El(t);
  doc.createTextNode = t => new TextNode(t);
  doc.createDocumentFragment = () => new Fragment();
  doc.createTreeWalker = rootEl => {
    const nodes = []; (function walk(n) { for (const c of n.childNodes) { if (c instanceof TextNode) nodes.push(c); else if (c instanceof El) walk(c); } })(rootEl);
    let i = -1; return { get currentNode() { return nodes[i]; }, nextNode() { i++; return i < nodes.length ? nodes[i] : null; } };
  };
  doc.addEventListener = (t, fn) => { (doc.listeners[t] = doc.listeners[t] || []).push(fn); };
  doc.removeEventListener = (t, fn) => { doc.listeners[t] = (doc.listeners[t] || []).filter(f => f !== fn); };
  doc.querySelectorAll = s => doc.documentElement.querySelectorAll(s);
  doc.querySelector = s => doc.documentElement.querySelector(s);
  doc.getElementById = id => doc.documentElement.all().find(e => e.attrs.id === id) || null;
  return { El, TextNode, document: doc };
}

// 假 vault：files = {path: string}；记读写次数
function makeVault(files = {}) {
  const disk = new Map(Object.entries(files));
  const mtimes = new Map();
  let clock = 1000;
  const reads = {}, writes = {};
  const touch = p => mtimes.set(p, ++clock);
  for (const p of disk.keys()) touch(p);
  const adapter = {
    async read(p) { reads[p] = (reads[p] || 0) + 1; if (!disk.has(p)) throw new Error('ENOENT ' + p); return disk.get(p); },
    async write(p, s) { writes[p] = (writes[p] || 0) + 1; disk.set(p, s); touch(p); },
    async exists(p) { return disk.has(p); },
    async stat(p) { return disk.has(p) ? { mtime: mtimes.get(p), size: disk.get(p).length } : null; },
    getResourcePath: p => 'app://' + p,
  };
  const vault = {
    adapter,
    getAbstractFileByPath(p) { if (p === '_archive' || [...disk.keys()].some(k => k.startsWith(p + '/'))) return { path: p, children: [] }; return disk.has(p) ? { path: p, stat: { mtime: mtimes.get(p), size: disk.get(p).length } } : null; },
    on: () => ({}),
  };
  return {
    vault, disk, reads, writes,
    set(p, s) { disk.set(p, s); touch(p); },
    get: p => disk.get(p),
    resetCounts() { for (const k of Object.keys(reads)) delete reads[k]; for (const k of Object.keys(writes)) delete writes[k]; },
  };
}

function makeWorkspace() {
  const handlers = {};
  return {
    handlers, opened: [],
    on(name, fn) { (handlers[name] = handlers[name] || []).push(fn); return { name, fn }; },
    trigger(name, ...a) { for (const fn of handlers[name] || []) fn(...a); },
    openLinkText(...a) { this.opened.push(a); },
  };
}

// 起一个 Dataview 块：同一个容器 + 同一个 component 可以 rerun（模拟 2.5 秒刷新）；host 挂在 body 下（isConnected 为真）
function dataviewBlock({ dom, app, code, params = {}, folder = '' }) {
  const host = dom.document.body.createEl('div', { cls: 'markdown-preview-view' });
  const container = host.createEl('div', { cls: 'block-language-dataviewjs' });
  const component = { events: [], cleanups: [], registerEvent(ref) { this.events.push(ref); }, register(fn) { this.cleanups.push(fn); } };
  const dv = { container, component, current: () => ({ file: { folder } }), page: () => null, paragraph(t) { container.createEl('p', { text: t }); } };
  const names = ['dv', 'app', 'document', 'window', 'Notice', 'ResizeObserver', 'NodeFilter', 'requestAnimationFrame', 'getComputedStyle', 'innerWidth', 'innerHeight', 'MutationObserver', ...Object.keys(params)];
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const fn = new AsyncFunction(...names, code);
  const alerts = [];
  const window = { alert(m) { alerts.push(m); }, confirm: () => false, innerHeight: 800, innerWidth: 1200, getSelection: () => ({ toString: () => '' }) };
  const notices = [];
  const env = [dv, app, dom.document, window, class { constructor(m) { notices.push(m); } }, class { observe() {} disconnect() {} }, { SHOW_TEXT: 4 },
    f => setTimeout(f, 0), () => ({ overflowY: 'visible' }), 1200, 800, class { observe() {} disconnect() {} }, ...Object.values(params)];
  const run = () => fn(...env);
  return {
    dv, container, host, component, notices, alerts, window, run,
    async rerun() { container.innerHTML = ''; await run(); },
  };
}

module.exports = { ROOT, asset, makeDom, makeVault, makeWorkspace, dataviewBlock };

// 假 obsidian 模块（批次 D 地基，合入后冻结）：node（tests/_fakedom.cjs 的假 document）和 playwright（真 document）共用同一份。
//   node：      const { makeObsidian } = require('./_fakeobsidian.cjs'); const obs = makeObsidian(dom.document, { notices });
//               vm 里 require('obsidian') 换成 obs（见 tests/test_plugin_foundation.cjs）。
//   playwright：await page.addScriptTag({ content: browserSource('obsidian') })  → window.obsidian（外壳 tests/_obsidian_shell.cjs 自动做）。
// 结构照 Obsidian 1.14.4（app.js 里核过）：
//   - Menu：body > .menu > .menu-scroll > .menu-item.tappable(.menu-item-icon + .menu-item-title) / .menu-separator；setWarning → .is-warning，
//     setChecked → .mod-checked，setDisabled → .is-disabled；Esc、点菜单外面关闭；onHide 只留最后一个回调（和真的一样）；
//     z-index 取 var(--layer-menu, 65)。打开的菜单在 obs.Menu.open 里。
//   - Notice：body > .notice-container > .notice > .notice-message（+ .notice-button-container > .notice-cta）；addButton 点了先 hide 再回调；
//     不自动消失（测试读得到），setAutoHide / hide / setMessage 都记下来。全部进 opts.notices。
//   - Modal：body > .modal-container.mod-dim > .modal-bg + .modal > .modal-close-button + .modal-header > .modal-title, .modal-content；Esc 关；
//     打开时 open()→onOpen，close()→onClose。
//   - Setting：.setting-item > .setting-item-info(.setting-item-name / .setting-item-description) + .setting-item-control；
//     ButtonComponent.setWarning 在 1.14.4 = mod-destructive + mod-cta。
//   - SuggestModal / ItemView / PluginSettingTab / Plugin / Component / MarkdownRenderer / setIcon / TFile / MarkdownView / Platform：最小实现。
// 只用标准 DOM（createElement / append / classList / addEventListener），Obsidian 的 createEl 这类扩展由宿主提供（假 DOM 自带，外壳装在原型上）。
'use strict';

function makeObsidian(document, opts) {
  opts = opts || {};
  const notices = opts.notices || [];
  const menus = opts.menus || [];
  const D = document;
  const el = (tag, cls, parent, text) => {
    const e = D.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    if (parent) parent.appendChild(e);
    return e;
  };
  const setContent = (target, v) => { target.textContent = ''; if (v && typeof v === 'object' && v.nodeType === 11) target.appendChild(v); else target.textContent = String(v == null ? '' : v); };
  const toggle = (e, c, on) => { if (on) e.classList.add(c); else e.classList.remove(c); };
  const docListen = (type, fn) => { D.addEventListener(type, fn, true); return () => D.removeEventListener(type, fn, true); };

  function setIcon(target, name) {
    if (!target) return;
    target.textContent = '';
    const svg = D.createElementNS ? D.createElementNS('http://www.w3.org/2000/svg', 'svg') : D.createElement('svg');
    svg.setAttribute('class', 'svg-icon lucide-' + name);
    svg.setAttribute('data-icon', name);
    target.appendChild(svg);
    target.setAttribute('data-icon', name);
  }

  class Events {
    constructor() { this._h = {}; }
    on(name, fn) { const ref = { name, fn, e: this }; (this._h[name] = this._h[name] || []).push(ref); return ref; }
    off(name, fn) { this._h[name] = (this._h[name] || []).filter(r => r.fn !== fn); }
    offref(ref) { if (ref && this._h[ref.name]) this._h[ref.name] = this._h[ref.name].filter(r => r !== ref); }
    trigger(name, ...a) { for (const r of [...(this._h[name] || [])]) r.fn(...a); }
  }

  class Component {
    constructor() { this._loaded = false; this._cbs = []; this._children = []; }
    load() { if (this._loaded) return; this._loaded = true; this.onload && this.onload(); for (const c of this._children) c.load(); }
    unload() {
      if (!this._loaded) return; this._loaded = false;
      for (const c of this._children.splice(0)) c.unload();
      while (this._cbs.length) { try { this._cbs.pop()(); } catch (e) { /* 和 Obsidian 一样不让一个清理拦住其余 */ } }
      this.onunload && this.onunload();
    }
    onload() {} onunload() {}
    addChild(c) { this._children.push(c); if (this._loaded) c.load(); return c; }
    removeChild(c) { this._children = this._children.filter(x => x !== c); c.unload(); return c; }
    register(fn) { this._cbs.push(fn); }
    registerEvent(ref) { this.register(() => ref && ref.e && ref.e.offref && ref.e.offref(ref)); }
    registerDomEvent(target, type, fn, o) { target.addEventListener(type, fn, o); this.register(() => target.removeEventListener(type, fn, o)); }
    registerInterval(id) { this.register(() => clearInterval(id)); return id; }
  }

  // ── Notice ──
  class Notice {
    constructor(message, duration) {
      const box = D.body.querySelector(':scope > .notice-container') || el('div', 'notice-container', D.body);
      this.containerEl = el('div', 'notice', box);
      this.messageEl = this.noticeEl = el('div', 'notice-message', this.containerEl);
      this.duration = duration === undefined ? 4000 : duration;
      this.hidden = false; this.buttons = []; this.messages = []; this.buttonContainerEl = null;
      this.setMessage(message);
      this.containerEl.addEventListener('click', () => this.hide());
      notices.push(this);
    }
    get message() { return this.messageEl.textContent; }
    get timeout() { return this.duration; }
    setMessage(m) { setContent(this.messageEl, m); this.messages.push(this.messageEl.textContent); return this; }
    setAutoHide(ms) { this.duration = ms; return this; }
    addButton(label, cb) {
      if (!this.buttonContainerEl) this.buttonContainerEl = el('div', 'notice-button-container', this.containerEl);
      const b = el('div', 'notice-cta', this.buttonContainerEl, label);
      b.addEventListener('click', e => { if (e && e.stopPropagation) e.stopPropagation(); this.hide(); cb(e); });
      this.buttons.push({ label, el: b, click: () => b.click() });
      return this;
    }
    hide() { if (this.hidden) return; this.hidden = true; this.containerEl.remove(); }
  }

  // ── Menu ──
  class MenuItem {
    constructor(menu) {
      this.menu = menu; this.disabled = false; this.checked = null; this.callback = null;
      this.dom = el('div', 'menu-item tappable');
      this.iconEl = el('div', 'menu-item-icon', this.dom);
      this.titleEl = el('div', 'menu-item-title', this.dom);
      this.dom.addEventListener('click', e => this.handle(e));
    }
    handle(e) { if (this.disabled) return; if (e && (e.button || 0) !== 0) return; if (e && e.defaultPrevented) return; const cb = this.callback; this.menu.hide(); if (cb) cb(e); }
    setTitle(t) { setContent(this.titleEl, t); this.title = this.titleEl.textContent; return this; }
    setIcon(name) { setIcon(this.iconEl, name); this.icon = name; return this; }
    setChecked(on) { this.checked = !!on; toggle(this.dom, 'mod-checked', !!on); return this; }
    setDisabled(on) { this.disabled = !!on; toggle(this.dom, 'is-disabled', !!on); return this; }
    setWarning(on) { this.warning = !!on; toggle(this.dom, 'is-warning', !!on); return this; }
    setSection(s) { this.section = s; this.dom.setAttribute('data-section', s); return this; }
    setIsLabel(on) { toggle(this.dom, 'is-label', !!on); return this; }
    onClick(fn) { this.callback = fn; return this; }
    click() { this.dom.click(); }
  }
  class Menu extends Component {
    constructor() {
      super(); this.items = []; this.hideCallback = null; this.shown = false;
      this.dom = el('div', 'menu'); el('div', 'menu-grabber', this.dom);
      this.scrollEl = el('div', 'menu-scroll', this.dom);
      this.dom.style.zIndex = 'var(--layer-menu, 65)';
      this.dom.style.position = 'fixed';
      menus.push(this);
    }
    addItem(cb) { const it = new MenuItem(this); this.items.push(it); cb(it); return this; }
    addSeparator() { this.items.push({ separator: true, dom: el('div', 'menu-separator') }); return this; }
    // 1.14.4：onHide 只有一个槽位（后设的顶掉先设的）；hide() 先把槽位清空再回调；没有菜单项时 showAtPosition 直接返回、不显示
    onHide(fn) { this.hideCallback = fn; return this; }
    showAtPosition(pos) {
      if (this.items.length === 0) { this.unload(); return this; }
      if (Menu.open && Menu.open !== this) Menu.open.hide();
      this.pos = pos || { x: 0, y: 0 };
      for (const it of this.items) this.scrollEl.appendChild(it.dom);
      this.dom.style.left = (this.pos.x || 0) + 'px'; this.dom.style.top = (this.pos.y || 0) + 'px';
      D.body.appendChild(this.dom); this.shown = true; Menu.open = this; this.load();
      const offKey = docListen('keydown', e => { if (e.key === 'Escape') { if (e.preventDefault) e.preventDefault(); this.hide(); } });
      const offDown = docListen('mousedown', e => { if (!this.dom.contains(e.target)) this.hide(); });
      this.register(offKey); this.register(offDown);
      return this;
    }
    showAtMouseEvent(evt) { this.mouseEvent = evt; return this.showAtPosition({ x: evt.clientX, y: evt.clientY }); }   // 1.14.4 只看 clientX / clientY
    hide() {
      if (!this.shown) return this;
      this.shown = false; this.dom.remove(); if (Menu.open === this) Menu.open = null;
      this.unload();
      const cb = this.hideCallback; this.hideCallback = null; if (cb) cb();
      return this;
    }
    close() { return this.hide(); }
    // 测试用：按标题找菜单项
    find(title) { return this.items.find(it => !it.separator && it.title === title) || null; }
  }
  Menu.open = null;

  // ── Modal ──
  class Scope {
    constructor() { this.keys = []; }
    register(mods, key, fn) { const h = { mods: mods || [], key, fn }; this.keys.push(h); return h; }
    unregister(h) { this.keys = this.keys.filter(x => x !== h); }
  }
  class Modal {
    constructor(app) {
      this.app = app; this.scope = new Scope(); this.isOpen = false;
      this.containerEl = el('div', 'modal-container mod-dim');
      el('div', 'modal-bg', this.containerEl);
      this.modalEl = el('div', 'modal', this.containerEl);
      this.closeButtonEl = el('div', 'modal-close-button', this.modalEl);
      this.headerEl = el('div', 'modal-header', this.modalEl);
      this.titleEl = el('div', 'modal-title', this.headerEl);
      this.contentEl = el('div', 'modal-content', this.modalEl);
      this.closeButtonEl.addEventListener('click', () => this.close());
    }
    setTitle(t) { setContent(this.titleEl, t); return this; }
    setContent(c) { setContent(this.contentEl, c); return this; }
    open() {
      if (this.isOpen) return; this.isOpen = true;
      D.body.appendChild(this.containerEl);
      this._offKey = docListen('keydown', e => {
        for (const h of this.scope.keys) if (h.key === e.key) { const r = h.fn(e); if (r === false && e.preventDefault) e.preventDefault(); return; }
        if (e.key === 'Escape') { if (e.preventDefault) e.preventDefault(); this.close(); }
      });
      this.onOpen();
    }
    close() { if (!this.isOpen) return; this.isOpen = false; if (this._offKey) this._offKey(); this.containerEl.remove(); this.onClose(); }
    onOpen() {} onClose() {}
  }
  class SuggestModal extends Modal {
    constructor(app) {
      super(app); this.limit = 0; this.emptyStateText = '没有匹配';
      this.modalEl.classList.add('prompt');
      this.inputEl = el('input', 'prompt-input', this.contentEl); this.inputEl.type = 'text';
      this.resultContainerEl = el('div', 'prompt-results', this.contentEl);
      this.suggestions = [];
      this.inputEl.addEventListener('input', () => this.updateSuggestions());
      this.inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing && this.suggestions.length) { if (e.preventDefault) e.preventDefault(); this.choose(0, e); } });
    }
    setPlaceholder(t) { this.inputEl.placeholder = t; }
    async updateSuggestions() {
      const list = await this.getSuggestions(this.inputEl.value || '');
      this.suggestions = (this.limit ? list.slice(0, this.limit) : list) || [];
      this.resultContainerEl.textContent = '';
      if (!this.suggestions.length) { el('div', 'suggestion-empty', this.resultContainerEl, this.emptyStateText); return; }
      this.suggestions.forEach((s, i) => { const row = el('div', 'suggestion-item', this.resultContainerEl); this.renderSuggestion(s, row); row.addEventListener('click', e => this.choose(i, e)); });
    }
    choose(i, evt) { const s = this.suggestions[i]; this.close(); this.onChooseSuggestion(s, evt); }
    open() { super.open(); this.updateSuggestions(); }
    getSuggestions() { return []; } renderSuggestion(s, row) { row.textContent = String(s); } onChooseSuggestion() {}
  }

  // ── 设置组件 ──
  class ButtonComponent {
    constructor(parent) { this.buttonEl = el('button', '', parent); this.disabled = false; }
    setButtonText(t) { this.buttonEl.textContent = t; return this; }
    setCta() { this.buttonEl.classList.add('mod-cta'); return this; }
    removeCta() { this.buttonEl.classList.remove('mod-cta'); return this; }
    setWarning() { this.buttonEl.classList.add('mod-destructive'); return this.setCta(); }   // 1.14.4：setDestructive().setCta()
    setDestructive() { this.buttonEl.classList.add('mod-destructive'); return this; }
    setDisabled(on) { this.disabled = !!on; this.buttonEl.disabled = !!on; return this; }
    setIcon(name) { setIcon(this.buttonEl, name); return this; }
    setTooltip(t) { this.buttonEl.setAttribute('aria-label', t); return this; }
    setClass(c) { this.buttonEl.classList.add(c); return this; }
    onClick(fn) { this.buttonEl.addEventListener('click', fn); return this; }
    then(cb) { cb(this); return this; }
  }
  class ExtraButtonComponent {
    constructor(parent) { this.extraSettingsEl = el('div', 'clickable-icon extra-setting-button', parent); }
    setIcon(name) { setIcon(this.extraSettingsEl, name); return this; }
    setTooltip(t) { this.extraSettingsEl.setAttribute('aria-label', t); return this; }
    setDisabled(on) { toggle(this.extraSettingsEl, 'is-disabled', !!on); return this; }
    onClick(fn) { this.extraSettingsEl.addEventListener('click', fn); return this; }
  }
  class ValueComponent {
    setValue(v) { this._set(v); return this; } getValue() { return this._get(); }
    onChange(fn) { this._change = fn; return this; }
    setDisabled(on) { this.disabled = !!on; return this; }
    then(cb) { cb(this); return this; }
  }
  class TextComponent extends ValueComponent {
    constructor(parent, tag) { super(); this.inputEl = el(tag || 'input', '', parent); if (!tag) this.inputEl.type = 'text'; this.inputEl.addEventListener('input', () => this._change && this._change(this.inputEl.value)); }
    _set(v) { this.inputEl.value = v == null ? '' : String(v); } _get() { return this.inputEl.value; }
    setPlaceholder(t) { this.inputEl.placeholder = t; return this; }
  }
  class TextAreaComponent extends TextComponent { constructor(parent) { super(parent, 'textarea'); } }
  class ToggleComponent extends ValueComponent {
    constructor(parent) { super(); this.toggleEl = el('div', 'checkbox-container', parent); this.value = false; this.toggleEl.addEventListener('click', () => { if (this.disabled) return; this._set(!this.value); this._change && this._change(this.value); }); }
    _set(v) { this.value = !!v; toggle(this.toggleEl, 'is-enabled', this.value); } _get() { return this.value; }
  }
  class DropdownComponent extends ValueComponent {
    constructor(parent) { super(); this.selectEl = el('select', 'dropdown', parent); this.selectEl.addEventListener('change', () => this._change && this._change(this.selectEl.value)); }
    addOption(v, label) { const o = el('option', '', this.selectEl, label); o.value = v; return this; }
    addOptions(map) { for (const k of Object.keys(map)) this.addOption(k, map[k]); return this; }
    _set(v) { this.selectEl.value = v; } _get() { return this.selectEl.value; }
  }
  class SliderComponent extends ValueComponent {
    constructor(parent) { super(); this.sliderEl = el('input', 'slider', parent); this.sliderEl.type = 'range'; }
    setLimits(min, max, step) { this.limits = [min, max, step]; return this; } setDynamicTooltip() { return this; }
    _set(v) { this.sliderEl.value = String(v); } _get() { return Number(this.sliderEl.value); }
  }
  class Setting {
    constructor(containerEl) {
      this.settingEl = el('div', 'setting-item', containerEl);
      this.infoEl = el('div', 'setting-item-info', this.settingEl);
      this.nameEl = el('div', 'setting-item-name', this.infoEl);
      this.descEl = el('div', 'setting-item-description', this.infoEl);
      this.controlEl = el('div', 'setting-item-control', this.settingEl);
      this.components = [];
    }
    setName(t) { setContent(this.nameEl, t); return this; }
    setDesc(t) { setContent(this.descEl, t); return this; }
    setHeading() { this.settingEl.classList.add('setting-item-heading'); return this; }
    setClass(c) { this.settingEl.classList.add(c); return this; }
    setTooltip(t) { this.nameEl.setAttribute('aria-label', t); return this; }
    setDisabled(on) { toggle(this.settingEl, 'is-disabled', !!on); for (const c of this.components) c.setDisabled && c.setDisabled(on); return this; }
    _add(C, cb) { const c = new C(this.controlEl); this.components.push(c); cb && cb(c); return this; }
    addButton(cb) { return this._add(ButtonComponent, cb); }
    addExtraButton(cb) { return this._add(ExtraButtonComponent, cb); }
    addText(cb) { return this._add(TextComponent, cb); }
    addTextArea(cb) { return this._add(TextAreaComponent, cb); }
    addToggle(cb) { return this._add(ToggleComponent, cb); }
    addDropdown(cb) { return this._add(DropdownComponent, cb); }
    addSlider(cb) { return this._add(SliderComponent, cb); }
    then(cb) { cb(this); return this; }
  }
  class PluginSettingTab {
    constructor(app, plugin) { this.app = app; this.plugin = plugin; this.containerEl = el('div', 'vertical-tab-content'); }
    display() {} hide() {}
  }
  class ItemView extends Component {
    constructor(leaf) {
      super(); this.leaf = leaf; this.app = leaf && leaf.app; this.actions = [];
      this.containerEl = el('div', 'workspace-leaf-content');
      this.headerEl = el('div', 'view-header', this.containerEl);
      this.contentEl = el('div', 'view-content', this.containerEl);
    }
    getViewType() { return 'item'; } getDisplayText() { return ''; } getIcon() { return 'document'; }
    addAction(icon, title, cb) { const a = el('div', 'clickable-icon view-action', this.headerEl); setIcon(a, icon); a.setAttribute('aria-label', title); a.addEventListener('click', cb); this.actions.push({ icon, title, el: a }); return a; }
    async onOpen() {} async onClose() {}
  }
  class Plugin extends Component {
    constructor(app, manifest) {
      super(); this.app = app; this.manifest = manifest || { id: 'test-plugin', dir: '' };
      this.commands = []; this.ribbonIcons = []; this.settingTabs = []; this.statusBarItems = []; this._data = null; this.saved = [];
    }
    addCommand(c) { this.commands.push(c); return c; }
    addRibbonIcon(icon, title, cb) { const r = el('div', 'side-dock-ribbon-action clickable-icon'); r.setAttribute('aria-label', title); r.addEventListener('click', cb); this.ribbonIcons.push({ icon, title, cb, el: r }); return r; }
    addSettingTab(t) { this.settingTabs.push(t); }
    addStatusBarItem() {
      const bar = D.body.querySelector('.status-bar') || el('div', 'status-bar', D.body);
      const item = el('div', 'status-bar-item plugin-' + String(this.manifest.id || 'x'), bar);
      this.statusBarItems.push(item); this.register(() => item.remove());
      return item;
    }
    async loadData() { return this._data; }
    async saveData(d) { this._data = JSON.parse(JSON.stringify(d)); this.saved.push(this._data); }
  }
  class TAbstractFile {}
  class TFile extends TAbstractFile { constructor(p) { super(); if (p) { this.path = p; const n = p.split('/').pop(); this.name = n; this.basename = n.replace(/\.[^.]+$/, ''); this.extension = (n.match(/\.([^.]+)$/) || [, ''])[1]; } } }
  class TFolder extends TAbstractFile {}
  class MarkdownView extends ItemView { getViewType() { return 'markdown'; } }
  const MarkdownRenderer = {
    renders: 0,
    async render(app, md, target, sourcePath, component) { MarkdownRenderer.renders++; if (opts.renderMarkdown) return opts.renderMarkdown(md, target, sourcePath, component); setContent(target, md); },
    async renderMarkdown(md, target, sourcePath, component) { return MarkdownRenderer.render(null, md, target, sourcePath, component); },
  };
  const Platform = { isMobile: !!opts.isMobile, isMobileApp: !!opts.isMobile, isDesktop: !opts.isMobile, isDesktopApp: !opts.isMobile, isPhone: !!opts.isMobile, isWin: true, isMacOS: false };
  const requestUrl = async () => { throw new Error('假 obsidian：测试里不联网（requestUrl）'); };
  const normalizePath = p => String(p || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/^\/|\/$/g, '');
  const debounce = (fn, ms) => { let t = null; const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms || 0); }; d.cancel = () => clearTimeout(t); return d; };
  return { Notice, Menu, MenuItem, Modal, SuggestModal, Scope, Setting, PluginSettingTab, ItemView, Plugin, Component, Events,
    ButtonComponent, ExtraButtonComponent, TextComponent, TextAreaComponent, ToggleComponent, DropdownComponent, SliderComponent,
    TAbstractFile, TFile, TFolder, MarkdownView, MarkdownRenderer, Platform, requestUrl, normalizePath, debounce, setIcon,
    notices, menus };
}

// Obsidian 给 DOM 原型加的那些方法（createEl / createDiv / empty / setText / addClass / isShown …）和全局 createEl / createFragment。
// 只给 playwright 外壳用（假 DOM 自带）：await page.addScriptTag({ content: `(${installObsidianDom})(window)` })
function installObsidianDom(win) {
  const N = win.Node.prototype, E = win.Element.prototype, F = win.DocumentFragment.prototype, d = win.document;
  const make = (tag, o, cb) => {
    if (typeof o === 'string') o = { cls: o };
    o = o || {};
    const e = d.createElement(tag);
    if (o.cls) e.className = Array.isArray(o.cls) ? o.cls.join(' ') : o.cls;
    if (o.text != null) { if (typeof o.text === 'object' && o.text.nodeType === 11) e.appendChild(o.text); else e.textContent = String(o.text); }
    if (o.attr) for (const k of Object.keys(o.attr)) { const v = o.attr[k]; if (v != null && v !== false) e.setAttribute(k, v === true ? '' : String(v)); }
    if (o.title) e.title = o.title;
    if (o.type) e.type = o.type;
    if (o.value != null) e.value = o.value;
    if (o.placeholder) e.placeholder = o.placeholder;
    if (o.href) e.href = o.href;
    if (o.parent) { if (o.prepend) o.parent.prepend(e); else o.parent.appendChild(e); }
    if (cb) cb(e);
    return e;
  };
  const def = (proto, name, fn) => { if (!(name in proto)) Object.defineProperty(proto, name, { value: fn, configurable: true, writable: true }); };
  for (const proto of [E, F]) {
    def(proto, 'createEl', function (tag, o, cb) { const e = make(tag, o, cb); if (o && typeof o === 'object' && o.prepend) this.prepend(e); else this.appendChild(e); return e; });
    def(proto, 'createDiv', function (o, cb) { return this.createEl('div', o, cb); });
    def(proto, 'createSpan', function (o, cb) { return this.createEl('span', o, cb); });
    def(proto, 'appendText', function (t) { this.appendChild(d.createTextNode(String(t))); });
    def(proto, 'empty', function () { while (this.firstChild) this.removeChild(this.firstChild); });
    def(proto, 'setText', function (t) { this.textContent = String(t == null ? '' : t); });
    def(proto, 'find', function (s) { return this.querySelector(s); });
    def(proto, 'findAll', function (s) { return Array.from(this.querySelectorAll(s)); });
  }
  def(N, 'detach', function () { if (this.parentNode) this.parentNode.removeChild(this); });
  def(N, 'instanceOf', function (C) { return this instanceof C; });
  def(E, 'getText', function () { return this.textContent; });
  def(E, 'addClass', function (...c) { this.classList.add(...c); });
  def(E, 'removeClass', function (...c) { this.classList.remove(...c); });
  def(E, 'toggleClass', function (c, on) { this.classList.toggle(c, on); });
  def(E, 'hasClass', function (c) { return this.classList.contains(c); });
  def(E, 'setAttr', function (k, v) { if (v == null || v === false) this.removeAttribute(k); else this.setAttribute(k, v === true ? '' : String(v)); });
  def(E, 'getAttr', function (k) { return this.getAttribute(k); });
  def(E, 'isShown', function () { return !!this.offsetParent; });   // Obsidian 1.14 的定义
  def(E, 'show', function () { this.style.display = ''; });
  def(E, 'hide', function () { this.style.display = 'none'; });
  def(E, 'toggle', function (on) { this.style.display = on ? '' : 'none'; });
  def(E, 'onClickEvent', function (fn, o) { this.addEventListener('click', fn, o); this.addEventListener('auxclick', fn, o); });
  win.createEl = (tag, o, cb) => make(tag, o, cb);
  win.createDiv = (o, cb) => make('div', o, cb);
  win.createSpan = (o, cb) => make('span', o, cb);
  win.createFragment = cb => { const f = d.createDocumentFragment(); if (cb) cb(f); return f; };
  win.activeDocument = d; win.activeWindow = win;
}

// 给 playwright 注入用的源码：window[name] = makeObsidian(document, {notices: window.notices, menus: window.menus})
function browserSource(name = 'obsidian') {
  return `(function(){window.notices=window.notices||[];window.menus=window.menus||[];
window.${name}=(${makeObsidian.toString()})(document,{notices:window.notices,menus:window.menus,renderMarkdown:window.__lbRenderMarkdown});})();`;
}

module.exports = { makeObsidian, installObsidianDom, browserSource };

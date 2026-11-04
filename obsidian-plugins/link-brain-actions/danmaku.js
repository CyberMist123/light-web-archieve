// danmaku.js — 1031 作者：B 站视频的弹幕。media-nav 给正文视频装工具行时调 attach()：
// 只认 B 站来源（item_id 是 bili-<BV>，或视频地址在 _archive/bilibili/<BV>/ 下），读 meta.json → 当前版本 manifest 里 role=danmaku 的 XML，
// 叠在画面上播：滚动 / 顶部 / 底部三种 + 高级弹幕（mode 7）按坐标静态停几秒，跟 video.currentTime 走（暂停就停、拖进度条按新时间重排、倍速跟着变），
// 全屏时照样在（层挂在 .lb-media 里）。
// 1031 作者（第二轮）：「弹幕直接复用批注」——用户自己的弹幕 = 这篇 notes.json 里带视频时间（video_t 秒）的批注，带细框飘；不带时间的不播。
// 写批注只走批注框（annotate-view.js 的「发弹幕」框），本文件只读 notes.json + 听 link-brain:annotations 事件（批注框存完就发），不写盘。
// 以前那套 danmaku-mine.json 去掉了（一次性迁移：python -m link_brain.migrate_danmaku_mine，见 FORMAT.md）。
// 性能：弹幕按时间排好、只往前走一个指针；只给屏幕上的那几十条建节点（节点回收复用）；每帧只改这几条的 transform，宽度用 canvas 量字、不读布局。
// 设置记在插件设置 settings.media.danmaku（所有视频共用）：开关、透明度、字号、显示区域、滚动速度、屏蔽三种。焦点在视频上按 D 开关（全屏里也行）；
// 1104 作者（参考 B 站播放器）：工具行里两个电视形「弹」图标——开关（关着时右下角带 ⊘）、设置（带齿轮）；画面上不再浮一个圆「弹」（全屏时工具行也在）。
'use strict';

const DEFAULTS = Object.freeze({ on: true, opacity: 0.9, scale: 1, area: 0.5, speed: 1, block: Object.freeze({ scroll: false, top: false, bottom: false }) });
const AREAS = [[0.25, '1/4 屏'], [0.5, '半屏'], [1, '全屏']];
const SPEEDS = [[0.7, '慢'], [1, '标准'], [1.35, '快'], [1.7, '很快']];
const BLOCKS = [['scroll', '滚动'], ['top', '顶部'], ['bottom', '底部']];
const SCROLL_SEC = 8;     // 标准速度：一条滚动弹幕从右边进、左边出要 8 秒（和 B 站网页端差不多）
const FIX_SEC = 4;        // 顶部 / 底部弹幕停 4 秒
const MAX_LIVE = 150;     // 同屏最多这么多条，再多就丢（B 站「防挡」也是丢）
const LATE_SEC = 1;       // 播放中晚到超过 1 秒的不补（卡了一下 / 切回来之后不一下子冒一堆）
const GAP = 12;           // 同一行前后两条至少隔开这么多像素
const POOL_MAX = 200;
const NOTES_FILE = 'notes.json';
const MINE_TEXT_MAX = 40;  // 批注当弹幕飘：只飘前 40 个字（批注常是一整段话），多的用「…」
const ADV_MAX = 15;        // 高级弹幕最多停 15 秒
const ADV_W = 672, ADV_H = 438;   // 高级弹幕的像素坐标按 B 站旧播放器舞台算（填小数 ≤1 的是比例）
const AWAKE_MS = 2000;     // （保留导出给旧用例）1104 起画面上不再浮「弹」字开关
const ANNOT_EVENT = 'link-brain:annotations';
const STYLE_ID = 'lb-danmaku-style';
const SID_RE = /^[A-Za-z0-9_-]{3,64}$/;

const live = new Set();          // 当前挂着的控制器（设置一变全都换；插件卸载全拆）
const xmlCache = new Map();      // 「文件路径 + sha256」→ 解析好的原弹幕（同一篇重画不重读重解析；最多 12 份）

function clamp(v, lo, hi) { v = Number(v); return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo; }
function nearest(v, list, d) {
  const n = Number(v);
  if (v === null || v === undefined || v === '' || !Number.isFinite(n)) return d;
  let best = list[0][0];
  for (const [x] of list) if (Math.abs(x - n) < Math.abs(best - n)) best = x;
  return best;
}
// 插件设置里的 media.danmaku → 一份完整、范围合法的设置（缺的补默认；不认识的值就近取档）
function normalizeSettings(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const b = r.block && typeof r.block === 'object' ? r.block : {};
  const num = (v, d, lo, hi) => (v === undefined || v === null || v === '' || !Number.isFinite(Number(v)) ? d : clamp(v, lo, hi));
  return {
    on: r.on === undefined ? DEFAULTS.on : !!r.on,
    opacity: num(r.opacity, DEFAULTS.opacity, 0.1, 1),
    scale: num(r.scale, DEFAULTS.scale, 0.5, 2),
    area: nearest(r.area, AREAS, DEFAULTS.area),
    speed: nearest(r.speed, SPEEDS, DEFAULTS.speed),
    block: { scroll: !!b.scroll, top: !!b.top, bottom: !!b.bottom },
  };
}
function settingsOf(plugin) { return normalizeSettings(plugin && plugin.settings && plugin.settings.media && plugin.settings.media.danmaku); }

// ── 解析 B 站弹幕 XML：<d p="出现秒数,模式,字号,十进制颜色,发送时间戳,...">文字</d> ──
const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
function decodeEntities(s) {
  return String(s).replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === '#') {
      const n = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      try { return Number.isFinite(n) && n > 0 ? String.fromCodePoint(n) : m; } catch { return m; }
    }
    const v = ENT[e.toLowerCase()];
    return v === undefined ? m : v;
  });
}
// B 站模式：1 / 2 / 3 滚动（2、3 是旧的变体）、6 逆向（当滚动画）、4 底部、5 顶部；7 高级（静态显示，见 parseAdv）；8 代码 / 9 BAS 不画
const MODE = { 1: 'scroll', 2: 'scroll', 3: 'scroll', 6: 'scroll', 4: 'bottom', 5: 'top', 7: 'adv' };
// 高级弹幕的正文是一个 JSON 数组：[x, y, "透明度起-止", 停留秒数, 文字, 旋转Z, 旋转Y, 终点x, 终点y, 移动毫秒, 延迟毫秒, 描边, 字体, 线性, 路径]。
// 1031 作者：「能简单支持就支持」——只取 位置 / 起始透明度 / 停留秒数 / 文字，在那个位置静态停几秒；旋转、移动、路径都不做。读不懂的丢掉。
function advPos(v, ref) {
  const s = String(v == null ? '' : v).trim(), n = Number(s);
  if (!s || !Number.isFinite(n)) return 0;
  return clamp(s.includes('.') && n <= 1 ? n : n / ref, 0, 0.98);
}
function parseAdv(raw) {
  let a;
  try { a = JSON.parse(raw); } catch { return null; }
  if (!Array.isArray(a) || a.length < 5) return null;
  const text = String(a[4] == null ? '' : a[4]).replace(/\/n/g, '\n').replace(/\r/g, '').split('\n').map(x => x.trimEnd()).join('\n').trim().slice(0, 2000);
  if (!text) return null;
  const alpha = parseFloat(String(a[2] == null ? '1' : a[2]).split('-')[0]);
  return { x: advPos(a[0], ADV_W), y: advPos(a[1], ADV_H), alpha: Number.isFinite(alpha) ? clamp(alpha, 0.05, 1) : 1, dur: clamp(Number(a[3]) || 4, 0.5, ADV_MAX), text };
}
function parseXml(text) {
  const out = [];
  const re = /<d\s[^>]*?\bp\s*=\s*"([^"]*)"[^>]*>([\s\S]*?)<\/d>/g;
  const src = String(text || '');
  let m;
  while ((m = re.exec(src))) {
    const p = m[1].split(',');
    const time = Number(p[0]), mode = MODE[Number(p[1])];
    if (!Number.isFinite(time) || time < 0 || !mode) continue;
    const color = Number(p[3]);
    const base = { time, mode, size: clamp(Number(p[2]) || 25, 12, mode === 'adv' ? 128 : 64), color: Number.isFinite(color) ? color & 0xffffff : 0xffffff, mine: false };
    if (mode === 'adv') {
      const adv = parseAdv(decodeEntities(m[2]));
      if (adv) out.push({ ...base, ...adv });
      continue;
    }
    const txt = decodeEntities(m[2]).replace(/\s*[\r\n]+\s*/g, ' ').trim();
    if (!txt) continue;
    out.push({ ...base, text: txt });
  }
  out.sort((a, b) => a.time - b.time);
  return out;
}
function colorCss(n) { return '#' + ((Number(n) || 0) & 0xffffff).toString(16).padStart(6, '0'); }
// 第一个 time >= t 的下标
function lowerBound(arr, t) { let lo = 0, hi = arr.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid].time < t) lo = mid + 1; else hi = mid; } return lo; }
// 第一个 time > t 的下标
function upperBound(arr, t) { let lo = 0, hi = arr.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid].time <= t) lo = mid + 1; else hi = mid; } return lo; }
// 量不了字（没有 canvas）时按字数估：中日韩 / 全角一个字宽 1em，其余 0.58em
function estimateWidth(text, px) {
  let n = 0;
  for (const ch of String(text)) n += ch.codePointAt(0) > 0x2e7f ? 1 : 0.58;
  return Math.ceil(n * px);
}

// 顶部 / 底部停 FIX_SEC 秒；高级弹幕停它自己写的秒数
function holdOf(d) { return d.mode === 'adv' ? (Number(d.dur) || FIX_SEC) : FIX_SEC; }

// ── 弹幕引擎：只管「在时间 t 时屏幕上该有哪些、在哪」，不碰 video；控制器每帧把时间喂进来 ──
class Engine {
  constructor(layer, { measure = null } = {}) {
    this.layer = layer; this.doc = layer.ownerDocument;
    this.items = []; this.next = 0; this.live = []; this.pool = [];
    this.W = 0; this.H = 0; this.t = 0;
    this.settings = normalizeSettings(null);
    this.measure = measure || estimateWidth;
    this.stats = { emitted: 0, created: 0, dropped: 0 };   // 测试和排查用
    this.layout();
  }
  setItems(items) { this.items = items.slice().sort((a, b) => a.time - b.time); this.reset(this.t); }
  setSettings(s) {
    const next = normalizeSettings(s), cur = this.settings;
    const relayout = next.scale !== cur.scale || next.area !== cur.area || next.speed !== cur.speed || JSON.stringify(next.block) !== JSON.stringify(cur.block);
    this.settings = next;
    if (relayout) { this.layout(); this.reset(this.t); }
  }
  resize(W, H) {
    W = Math.max(0, Math.round(W || 0)); H = Math.max(0, Math.round(H || 0));
    if (W === this.W && H === this.H) return false;
    this.W = W; this.H = H; this.layout(); this.reset(this.t);
    return true;
  }
  layout() {
    const s = this.settings;
    // 字号跟着画面大小走（小窗里 25 号字不至于占半屏，全屏也不至于太小），再乘用户调的倍数
    this.k = clamp(Math.sqrt(Math.max(1, this.W * this.H)) / 800, 0.55, 1.25) * s.scale;
    this.laneH = Math.max(12, Math.ceil(25 * this.k * 1.3));
    this.nLanes = Math.max(1, Math.floor((this.H * s.area) / this.laneH));
    this.dur = SCROLL_SEC / s.speed;
    this.lanes = { scroll: new Array(this.nLanes).fill(null), top: new Array(this.nLanes).fill(null), bottom: new Array(this.nLanes).fill(null) };
  }
  fontPx(d) { return Math.max(10, Math.round(d.size * this.k)); }
  // 放一条：找一行不会撞车的；没有就丢（force = 用户刚发的那条，挤也要挤上去）。visibleNow = 一出来就整条在画面里（暂停时发也看得见）
  emit(d, start, { force = false, visibleNow = false } = {}) {
    const s = this.settings;
    if (!force && (s.block[d.mode] || this.live.length >= MAX_LIVE)) return null;
    const px = this.fontPx(d);
    if (d.mode === 'adv') return this.emitAdv(d, start, px);
    const w = this.measure(d.text, px, this.doc) + (d.mine ? 10 : 0);
    let lane = -1, v = 0;
    if (d.mode === 'scroll') {
      v = (this.W + w) / this.dur;
      if (visibleNow) start -= (w + GAP) / v;
      const L = this.lanes.scroll;
      let best = 0, bestRoom = -Infinity;
      for (let i = 0; i < L.length; i++) {
        const r = L[i];
        if (!r || r.dead) { lane = i; break; }
        const tail = this.W - (start - r.start) * r.v + r.w;   // 这一行上一条的尾巴，在新的这条出发那一刻在哪
        const room = this.W - tail;
        // 尾巴已经进了画面，而且新的这条（更长 = 更快）追上它之前它已经出去了
        if (room >= GAP && (v <= r.v || room / (v - r.v) >= tail / r.v)) { lane = i; break; }
        if (room > bestRoom) { bestRoom = room; best = i; }
      }
      if (lane < 0 && force) lane = best;
    } else {
      const L = this.lanes[d.mode];
      for (let i = 0; i < L.length; i++) { const r = L[i]; if (!r || r.dead || start - r.start >= FIX_SEC) { lane = i; break; } }
      if (lane < 0 && force) lane = 0;
    }
    if (lane < 0) { this.stats.dropped++; return null; }
    let el = this.pool.pop();
    if (!el) { el = this.doc.createElement('div'); this.stats.created++; }
    el.className = 'lb-dm-item' + (d.mode === 'scroll' ? '' : ' is-fixed') + (d.mine ? ' is-mine' : '');
    el.textContent = d.text;
    el.style.color = colorCss(d.color);
    el.style.fontSize = px + 'px';
    el.style.opacity = '';
    const y = d.mode === 'bottom' ? Math.max(0, this.H - (lane + 1) * this.laneH) : lane * this.laneH;
    const rec = { d, el, mode: d.mode, lane, start, w, v, y, dead: false };
    el.style.transform = d.mode === 'scroll' ? `translate3d(${this.W}px,${y}px,0)` : `translate3d(-50%,${y}px,0)`;
    this.lanes[d.mode][lane] = rec;
    this.live.push(rec);
    this.layer.appendChild(el);
    this.stats.emitted++;
    return rec;
  }
  // 高级弹幕：不占行，按 XML 里的位置（画面比例）放，起始透明度，停 d.dur 秒
  emitAdv(d, start, px) {
    let el = this.pool.pop();
    if (!el) { el = this.doc.createElement('div'); this.stats.created++; }
    el.className = 'lb-dm-item is-adv';
    el.textContent = d.text;
    el.style.color = colorCss(d.color);
    el.style.fontSize = px + 'px';
    el.style.opacity = String(d.alpha == null ? 1 : d.alpha);
    const x = Math.round(d.x * this.W), y = Math.round(d.y * this.H);
    el.style.transform = `translate3d(${x}px,${y}px,0)`;
    const rec = { d, el, mode: 'adv', lane: -1, start, w: 0, v: 0, y, dead: false };
    this.live.push(rec);
    this.layer.appendChild(el);
    this.stats.emitted++;
    return rec;
  }
  drop(r) {
    if (r.dead) return;
    r.dead = true;
    r.el.remove();
    if (this.pool.length < POOL_MAX) this.pool.push(r.el);
  }
  // 只改屏幕上这几条的 transform；出了画面 / 到点的收回池子
  place(t) {
    let j = 0;
    for (const r of this.live) {
      if (r.dead) continue;
      if (r.mode === 'scroll') {
        const x = this.W - (t - r.start) * r.v;
        if (x + r.w < 0) { this.drop(r); continue; }
        r.el.style.transform = `translate3d(${x.toFixed(1)}px,${r.y}px,0)`;
      } else if (t - r.start >= holdOf(r.d)) { this.drop(r); continue; }
      this.live[j++] = r;
    }
    this.live.length = j;
  }
  // 播放中的一帧：时间往回跳或一下跳太远（拖进度条、循环回到开头）就按新时间重排，否则只放到点的那几条
  frame(t) {
    if (!(t >= this.t - 0.25 && t <= this.t + 2)) { this.reset(t); return; }
    this.t = Math.max(this.t, t);
    const items = this.items;
    while (this.next < items.length && items[this.next].time <= this.t) {
      const d = items[this.next++];
      if (this.t - d.time <= LATE_SEC) this.emit(d, d.time);
    }
    this.place(this.t);
  }
  clear() {
    for (const r of this.live) this.drop(r);
    this.live = [];
    for (const k of Object.keys(this.lanes)) this.lanes[k].fill(null);
  }
  // 按时间 t 重排：清掉屏幕上的，把「此刻本该还在画面里」的按各自出发时间放回去（拖进度条后画面和从头播到这里一样）
  reset(t) {
    t = Math.max(0, Number(t) || 0);
    this.clear();
    this.t = t;
    const items = this.items;
    let i = lowerBound(items, t - Math.max(this.dur, FIX_SEC, ADV_MAX));
    for (; i < items.length && items[i].time <= t; i++) {
      const d = items[i], age = t - d.time;
      if (d.mode === 'scroll' ? age < this.dur : age < holdOf(d)) this.emit(d, d.time);
    }
    this.next = i;
    this.place(t);
  }
  // 用户刚发的一条：插进时间线（已经播过的位置，不会被指针再放一次），立刻挤上画面
  insertNow(d, t) {
    const idx = upperBound(this.items, d.time);
    this.items.splice(idx, 0, d);
    if (idx <= this.next) this.next++;
    const rec = this.emit(d, t, { force: true, visibleNow: true });
    this.place(this.t);
    return rec;
  }
  removeItem(d) {
    const idx = this.items.indexOf(d);
    if (idx >= 0) { this.items.splice(idx, 1); if (idx < this.next) this.next--; }
    for (const r of this.live) if (r.d === d) this.drop(r);
    this.live = this.live.filter(r => !r.dead);
  }
}

// ── 找到这条视频的归档：item_id bili-<BV>，没有 item_id 就看视频地址 ──
function decodeSafe(s) { try { return decodeURIComponent(String(s || '')); } catch { return String(s || ''); } }
function sourceIdOf(itemId, src) {
  const id = String(itemId || '');
  if (id) { const m = /^bili-(.+)$/.exec(id); return m && SID_RE.test(m[1]) ? m[1] : ''; }
  const m = /\/_archive\/bilibili\/([A-Za-z0-9_-]+)\//.exec(decodeSafe(src).replace(/\\/g, '/'));
  return m && SID_RE.test(m[1]) ? m[1] : '';
}
async function readJson(adapter, p) { try { const v = JSON.parse(await adapter.read(p)); return v && typeof v === 'object' ? v : null; } catch { return null; } }
function cleanText(s, max = MINE_TEXT_MAX) {
  const t = String(s == null ? '' : s).replace(/[\r\n\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
  const chars = [...t];
  return chars.length > max ? chars.slice(0, max).join('') + '…' : t;
}
// 批注的 key：和 annotate-view.js 的 akey 同一认法（老批注没 id 按 时间 + 原文认），删除墓碑 deleted[] 按它算
function annotKey(a) { return a.id || ('ts:' + (a.ts || '') + '|' + (a.text || '')); }
// notes.json（或批注框发来的 {annotations, deleted}）→ 用户的弹幕：没删的、非空的、带视频时间 video_t（≥0 的数）的批注，按时间排好。
// 不带时间的不播；草稿不算。一律白色滚动、带细框（is-mine）。
function annotationItems(doc) {
  if (!doc || typeof doc !== 'object' || !Array.isArray(doc.annotations)) return [];
  const tomb = new Set(Array.isArray(doc.deleted) ? doc.deleted : []);
  const out = [];
  for (const a of doc.annotations) {
    if (!a || typeof a !== 'object' || typeof a.video_t !== 'number' || !Number.isFinite(a.video_t) || a.video_t < 0) continue;
    const key = annotKey(a);
    if (tomb.has(key)) continue;
    const text = cleanText(a.text);
    if (!text) continue;
    out.push({ time: a.video_t, mode: 'scroll', size: 25, color: 0xffffff, text, mine: true, id: key });
  }
  out.sort((x, y) => x.time - y.time);
  return out;
}
// notes.json：文件不在 = 没有批注；读不懂就当没有（批注框那边会把坏文件另存 .corrupt 并暂停保存，这里只是不播）
async function readNotes(adapter, file) {
  try {
    if (typeof adapter.exists === 'function' && !(await adapter.exists(file))) return { items: [], broken: false };
    const doc = JSON.parse(String(await adapter.read(file)).replace(/^\uFEFF/, ''));
    return { items: annotationItems(doc), broken: !doc || typeof doc !== 'object' };
  } catch { return { items: [], broken: true }; }
}

function ensureStyle(doc) {
  if (!doc || !doc.head || (typeof doc.getElementById === 'function' && doc.getElementById(STYLE_ID))) return;
  if (typeof doc.getElementById !== 'function' && doc.head.querySelector && doc.head.querySelector('#' + STYLE_ID)) return;
  const st = doc.createElement('style');
  st.id = STYLE_ID;
  st.textContent = CSS;
  doc.head.appendChild(st);
}
// 颜色只用样式集变量；弹幕字本身照 XML 的颜色，黑描边（和 B 站一样）
const CSS = [
  '.lb-dm-layer{position:absolute;inset:0;z-index:3;pointer-events:none;overflow:hidden;contain:strict;font-family:var(--lb-font-body);font-weight:700;line-height:1.25;}',
  '.lb-dm-layer[hidden]{display:none!important;}',
  '.lb-dm-item{position:absolute;left:0;top:0;white-space:pre;will-change:transform;user-select:none;text-shadow:1px 0 1px #000,-1px 0 1px #000,0 1px 1px #000,0 -1px 1px #000;}',
  '.lb-dm-item.is-fixed{left:50%;}',
  '.lb-dm-item.is-mine{box-shadow:0 0 0 1px rgb(255 255 255 / .9);border-radius:3px;padding:0 4px;}',
  '.lb-dm-flash{position:absolute;left:12px;bottom:56px;z-index:5;pointer-events:none;padding:2px 10px;border-radius:var(--lb-radius-pill);background:rgb(0 0 0 / .6);color:#fff;font-family:var(--lb-font-body);font-size:var(--lb-fs-small);opacity:0;transition:opacity .2s;}',
  '.lb-dm-flash.is-on{opacity:1;}',
  '.lb-dm-panel{position:absolute;left:8px;z-index:8;width:min(320px,calc(100% - 16px));box-sizing:border-box;padding:var(--lb-space-3);display:flex;flex-direction:column;gap:var(--lb-space-2);border:1px solid var(--lb-line);border-radius:var(--lb-radius);background:var(--lb-surface);color:var(--lb-ink);font-family:var(--lb-font-body);font-size:var(--lb-fs-small);box-shadow:0 6px 24px rgb(0 0 0 / .2);}',
  '.lb-dm-panel[hidden]{display:none!important;}',
  '.lb-dm-row{display:flex;align-items:center;gap:var(--lb-space-2);flex-wrap:wrap;}',
  '.lb-dm-label{flex:0 0 4.5em;color:var(--lb-muted);}',
  '.lb-dm-row input[type="range"]{flex:1;min-width:90px;margin:0;}',
  '.lb-dm-val{min-width:3.2em;text-align:right;font-variant-numeric:tabular-nums;}',
  '.lb-dm-seg{display:flex;flex-wrap:wrap;gap:4px;}',
  '.lb-dm-panel button{height:24px;padding:0 9px;border:1px solid var(--lb-line);border-radius:var(--lb-radius-pill);background:transparent;box-shadow:none;color:var(--lb-muted);font:inherit;cursor:pointer;}',
  '.lb-dm-panel button[aria-pressed="true"]{background:var(--lb-accent);border-color:var(--lb-accent);color:var(--lb-surface);}',
  '.lb-dm-panel .lb-dm-close{align-self:flex-end;}',
  '.lb-dm-tip,.lb-dm-count{margin:0;color:var(--lb-muted);line-height:1.5;}',
  // 高级弹幕：多行照原样（\n 换行），左上角对齐它写的坐标
  '.lb-dm-item.is-adv{line-height:1.15;}',
  // 1104 作者（参考 B 站播放器底栏）：「弹幕」「弹幕设置」是两个电视形图标——框里一个「弹」，右下角小角标：开关关着 = ⊘，设置 = 齿轮；颜色跟工具行的字
  '.xhs-note .lb-media-tools button.lb-dm-icobtn{display:inline-flex;align-items:center;justify-content:center;width:38px;min-width:0;padding:0 6px!important;}',
  '.lb-dm-ico{position:relative;display:inline-block;width:24px;height:19px;box-sizing:border-box;margin-top:3px;border:2px solid currentColor;border-radius:5px;}',
  '.lb-dm-ico::before{content:"弹";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font:700 11px/1 var(--lb-font-body);}',
  '.lb-dm-ico::after{content:"";position:absolute;right:-7px;bottom:-6px;width:12px;height:12px;box-sizing:border-box;border-radius:50%;background:#000;color:inherit;display:flex;align-items:center;justify-content:center;font:700 10px/1 var(--lb-font-body);}',
  '.lb-dm-toggle[aria-pressed="true"] .lb-dm-ico::after{display:none;}',
  '.lb-dm-toggle[aria-pressed="false"] .lb-dm-ico{opacity:.7;}',
  '.lb-dm-toggle[aria-pressed="false"] .lb-dm-ico::after{border:1.6px solid currentColor;background:#000 linear-gradient(45deg,transparent 43%,currentColor 43%,currentColor 57%,transparent 57%);}',
  '.lb-dm-menu .lb-dm-ico::after{content:"⚙";font-size:11px;}',
  '.xhs-note .lb-media.is-lb-fullscreen .lb-dm-panel{bottom:auto!important;top:12px!important;}',
  '@media print{.lb-dm-layer,.lb-dm-panel,.lb-dm-flash{display:none!important;}}',
].join('\n');

// 用 canvas 量字宽（不碰布局）；量不了就按字数估
function makeMeasure(doc, layer) {
  let ctx = null, family = null;
  try { const c = doc.createElement('canvas'); ctx = c && typeof c.getContext === 'function' ? c.getContext('2d') : null; } catch { ctx = null; }
  if (!ctx || typeof ctx.measureText !== 'function') return estimateWidth;
  return (text, px) => {
    if (family === null) {
      family = 'sans-serif';
      try { const win = doc.defaultView; const f = win && typeof win.getComputedStyle === 'function' ? win.getComputedStyle(layer).fontFamily : ''; if (f) family = f; } catch {}
    }
    ctx.font = `700 ${px}px ${family}`;
    const w = ctx.measureText(String(text)).width;
    return Number.isFinite(w) && w > 0 ? Math.ceil(w) + 2 : estimateWidth(text, px);
  };
}

// 1104：B 站那样的图标按钮——画出来的是 .lb-dm-ico（CSS），字（「弹幕」「弹幕设置」）留给读屏，不显示
function icoBtn(doc, cls, label) {
  const b = doc.createElement('button');
  b.type = 'button'; b.className = cls + ' lb-dm-icobtn'; b.setAttribute('aria-label', label);
  const ico = doc.createElement('span'); ico.className = 'lb-dm-ico'; ico.setAttribute('aria-hidden', 'true'); b.appendChild(ico);
  const t = doc.createElement('span'); t.className = 'lb-visually-hidden'; t.textContent = label; b.appendChild(t);
  return b;
}
function btn(doc, cls, text) {
  const b = doc.createElement('button');
  b.type = 'button'; b.className = cls; b.textContent = text;
  return b;
}
function div(doc, cls, text) {
  const d = doc.createElement('div');
  if (cls) d.className = cls;
  if (text != null) d.textContent = text;
  return d;
}

// ── 挂到一条视频上。不是 B 站来源 / 找不到归档：返回 null，什么都不加 ──
async function attach({ plugin, media, video, note = null, bar = null, itemId = '', notice = null } = {}) {
  if (!plugin || !media || !video) return null;
  const src = video.currentSrc || (typeof video.getAttribute === 'function' && video.getAttribute('src')) || video.src || '';
  const sid = sourceIdOf(itemId, src);
  if (!sid) return null;
  const adapter = plugin.app && plugin.app.vault && plugin.app.vault.adapter;
  if (!adapter || typeof adapter.read !== 'function') return null;
  const lbPath = p => (typeof plugin.lbPath === 'function' ? plugin.lbPath(p) : p);
  const base = lbPath(`_archive/bilibili/${sid}`);
  const meta = await readJson(adapter, base + '/meta.json');
  if (!meta || (meta.source && meta.source !== 'bilibili')) return null;
  const say = (msg, kind) => {
    try { if (typeof plugin.notify === 'function') { plugin.notify(msg, { kind }); return; } } catch {}
    try { if (typeof notice === 'function') notice(msg); } catch {}
  };

  // 原弹幕：当前版本 manifest 里 role=danmaku、download_status=ok 的那个文件
  let orig = [], origState = 'none', origError = '';
  const ver = Number(meta.current_version) || 0;
  if (ver > 0) {
    const vdir = `raw/v${String(ver).padStart(4, '0')}`;
    const manifest = await readJson(adapter, `${base}/${vdir}/manifest.json`);
    const entry = manifest && Array.isArray(manifest.media) ? manifest.media.find(m => m && m.role === 'danmaku' && m.download_status === 'ok' && typeof m.file === 'string') : null;
    if (entry && !/(^|\/)\.\.(\/|$)/.test(entry.file)) {
      const file = `${base}/${entry.file}`, key = file + '#' + (entry.sha256 || entry.bytes || '');
      try {
        if (xmlCache.has(key)) { orig = xmlCache.get(key); xmlCache.delete(key); xmlCache.set(key, orig); }
        else {
          orig = parseXml(await adapter.read(file));
          xmlCache.set(key, orig);
          while (xmlCache.size > 12) xmlCache.delete(xmlCache.keys().next().value);
        }
        origState = 'ok';
      } catch (e) { origState = 'failed'; origError = (e && e.message) || String(e); console.error('[lb] 原弹幕没读出来', e); }
    }
  }
  // 用户的弹幕 = 这篇 notes.json 里带 video_t 的批注（批注框写；这里只读）
  const notesPath = `${base}/${NOTES_FILE}`;
  const itemKey = String(meta.item_id || ('bili-' + sid));
  const notesDoc = await readNotes(adapter, notesPath);
  if (notesDoc.broken) console.error('[lb] ' + notesPath + ' 读不懂，先不播批注弹幕');
  const mine = notesDoc.items;
  if (media.isConnected === false || video.isConnected === false) return null;   // 读的工夫里这篇被重画了
  if (media.__lbDanmaku) return media.__lbDanmaku;

  const doc = media.ownerDocument;
  const win = (doc && doc.defaultView) || (typeof window !== 'undefined' ? window : null);
  const rafFn = win && typeof win.requestAnimationFrame === 'function' ? f => win.requestAnimationFrame(f) : f => setTimeout(() => f(Date.now()), 16);
  const cafFn = win && typeof win.cancelAnimationFrame === 'function' ? id => win.cancelAnimationFrame(id) : id => clearTimeout(id);
  const nowMs = () => (typeof performance !== 'undefined' && performance && typeof performance.now === 'function' ? performance.now() : Date.now());
  ensureStyle(doc);

  // 画面上的层：挂在视频那一格（.lb-slide）里，全屏的是整块 .lb-media，所以全屏照样在
  const slide = (typeof video.closest === 'function' && video.closest('.lb-slide')) || video.parentElement || media;
  const layer = div(doc, 'lb-dm-layer'); layer.setAttribute('aria-hidden', 'true');
  slide.appendChild(layer);
  const flash = div(doc, 'lb-dm-flash'); slide.appendChild(flash);
  const engine = new Engine(layer, { measure: makeMeasure(doc, layer) });
  engine.setItems(orig.concat(mine));

  // 工具行：「弹幕」开关 +「弹幕设置」
  const toggleBtn = icoBtn(doc, 'lb-dm-toggle', '弹幕');
  const menuBtn = icoBtn(doc, 'lb-dm-menu', '弹幕设置');
  if (bar) { bar.appendChild(toggleBtn); bar.appendChild(menuBtn); }

  // 设置弹层（挂在 .lb-media 里：全屏里打开也看得见）
  const panel = div(doc, 'lb-dm-panel'); panel.hidden = true;
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', '弹幕设置');
  const row = (label) => { const r = div(doc, 'lb-dm-row'); r.appendChild(div(doc, 'lb-dm-label', label)); panel.appendChild(r); return r; };
  const range = (label, min, max, step, key, toVal, fromVal) => {
    const r = row(label);
    const input = doc.createElement('input'); input.type = 'range'; input.min = String(min); input.max = String(max); input.step = String(step);
    input.setAttribute('aria-label', label);
    const val = div(doc, 'lb-dm-val');
    r.appendChild(input); r.appendChild(val);
    input.addEventListener('input', () => { setSetting({ [key]: fromVal(input.value) }, false); });
    input.addEventListener('change', () => { setSetting({ [key]: fromVal(input.value) }, true); });
    return { sync: s => { input.value = String(toVal(s[key])); val.textContent = Math.round(s[key] * 100) + '%'; }, input };
  };
  const seg = (label, list, key) => {
    const r = row(label), box = div(doc, 'lb-dm-seg'); r.appendChild(box);
    const bs = list.map(([v, text]) => { const b = btn(doc, 'lb-dm-opt', text); b.addEventListener('click', () => setSetting({ [key]: v }, true)); box.appendChild(b); return [v, b]; });
    return { sync: s => { for (const [v, b] of bs) b.setAttribute('aria-pressed', String(s[key] === v)); }, buttons: bs };
  };
  const ctlOpacity = range('透明度', 10, 100, 5, 'opacity', v => Math.round(v * 100), x => Number(x) / 100);
  const ctlScale = range('字号', 50, 200, 10, 'scale', v => Math.round(v * 100), x => Number(x) / 100);
  const ctlArea = seg('显示区域', AREAS, 'area');
  const ctlSpeed = seg('滚动速度', SPEEDS, 'speed');
  const blockRow = row('屏蔽'), blockBox = div(doc, 'lb-dm-seg'); blockRow.appendChild(blockBox);
  const blockBtns = BLOCKS.map(([k, text]) => {
    const b = btn(doc, 'lb-dm-opt', text);
    b.addEventListener('click', () => { const cur = settingsOf(plugin); setSetting({ block: { ...cur.block, [k]: !cur.block[k] } }, true); });
    blockBox.appendChild(b); return [k, b];
  });
  const count = doc.createElement('p'); count.className = 'lb-dm-count'; panel.appendChild(count);
  const tip = doc.createElement('p'); tip.className = 'lb-dm-tip';
  tip.textContent = '点一下画面再按 D 开关弹幕（全屏里也能按，或点工具行的「弹」图标）。自己的弹幕 = 视频下面「发弹幕」框里发的，带细框飘，只存在本机，不会发到 B 站。';
  panel.appendChild(tip);
  const closeBtn = btn(doc, 'lb-dm-close', '收起'); panel.appendChild(closeBtn);
  media.appendChild(panel);


  let raf = 0, lastVt = -1, baseVt = 0, baseNow = 0, flashTimer = null, destroyed = false, ro = null;
  const alive = () => !destroyed && media.isConnected !== false && video.isConnected !== false;
  const curTime = () => Math.max(0, Number(video.currentTime) || 0);
  const stopLoop = () => { if (raf) { cafFn(raf); raf = 0; } };
  const loop = (now) => {
    raf = 0;
    if (!alive()) { ctl.destroy(); return; }
    if (!settingsOf(plugin).on || video.paused || video.ended) return;
    now = typeof now === 'number' ? now : nowMs();
    const vt = curTime();
    // currentTime 不是每一帧都变：两次变化之间按倍速往前推（最多推 0.25 秒），画面走得匀
    if (vt !== lastVt) { lastVt = vt; baseVt = vt; baseNow = now; }
    let t = baseVt + Math.min(0.25, Math.max(0, now - baseNow) / 1000 * (Number(video.playbackRate) || 1));
    if (t < engine.t && t > engine.t - 0.2) t = engine.t;   // 别往回抖
    engine.frame(t);
    raf = rafFn(loop);
  };
  const startLoop = () => { if (!raf && alive() && settingsOf(plugin).on && !video.paused) { lastVt = -1; raf = rafFn(loop); } };
  const syncTo = () => { if (settingsOf(plugin).on) { engine.reset(curTime()); lastVt = -1; } };
  const measureLayer = () => {
    // 层是 inset:0 铺满视频那一格的，量那一格就是量层
    if (typeof slide.getBoundingClientRect !== 'function') return;
    const r = slide.getBoundingClientRect();
    if (r && r.width > 0 && r.height > 0) { engine.t = curTime(); engine.resize(r.width, r.height); }
  };

  const showFlash = (text) => {
    flash.textContent = text; flash.classList.add('is-on');
    clearTimeout(flashTimer); flashTimer = setTimeout(() => flash.classList.remove('is-on'), 1400);
  };
  const updateCount = () => {
    const nMine = engine.items.reduce((n, d) => n + (d.mine ? 1 : 0), 0);
    const head = origState === 'ok' ? `原弹幕 ${orig.length} 条` : origState === 'failed' ? `原弹幕没读出来（${origError}）` : '这条视频没存下原弹幕';
    count.textContent = `${head} · 我的批注弹幕 ${nMine} 条` + (notesDoc.broken ? `（${NOTES_FILE} 读不懂，先没播）` : '');
  };

  const placePanel = () => {
    if (!bar || typeof media.getBoundingClientRect !== 'function' || typeof bar.getBoundingClientRect !== 'function') return;
    const mr = media.getBoundingClientRect(), br = bar.getBoundingClientRect();
    if (!(mr.height > 0)) return;
    // 工具行在画面下面（平常）→ 弹层往上开；钉住时工具行浮在画面左上 → 往下开
    if (br.top - mr.top > mr.height / 2) { panel.style.top = ''; panel.style.bottom = Math.max(0, mr.bottom - br.top + 6) + 'px'; }
    else { panel.style.bottom = ''; panel.style.top = Math.max(0, br.bottom - mr.top + 6) + 'px'; }
  };
  const onDocDown = (e) => {
    const t = e && e.target;
    if (panel.hidden || !t || panel.contains(t) || menuBtn.contains(t)) return;
    closePanel();
  };
  const openPanel = () => { applySettings(); placePanel(); panel.hidden = false; menuBtn.setAttribute('aria-expanded', 'true'); doc.addEventListener('pointerdown', onDocDown, true); };
  const closePanel = () => { panel.hidden = true; menuBtn.setAttribute('aria-expanded', 'false'); doc.removeEventListener('pointerdown', onDocDown, true); };

  function applySettings() {
    if (!alive()) { ctl.destroy(); return; }
    const s = settingsOf(plugin);
    layer.style.opacity = String(s.opacity);
    layer.hidden = !s.on;
    media.classList.toggle('lb-dm-off', !s.on);
    toggleBtn.setAttribute('aria-pressed', String(s.on));
    toggleBtn.setAttribute('aria-label', s.on ? '弹幕：开（点一下关；也可按 D）' : '弹幕：关（点一下开；也可按 D）');   // 不用 title：LWA 界面不出气泡（no-tooltip.js）
    const wasOn = ctl.on;
    ctl.on = s.on;
    engine.setSettings(s);
    if (s.on) { if (!wasOn) syncTo(); startLoop(); }
    else { stopLoop(); engine.clear(); }
    ctlOpacity.sync(s); ctlScale.sync(s); ctlArea.sync(s); ctlSpeed.sync(s);
    for (const [k, b] of blockBtns) b.setAttribute('aria-pressed', String(s.block[k]));
    updateCount();
  }
  // 改设置：内存里先改、所有视频一起换；save=true 时存盘，没存上拨回原来的样子并说原因
  async function setSetting(patch, save) {
    const s = plugin.settings || (plugin.settings = {});
    const prev = settingsOf(plugin);
    const next = normalizeSettings({ ...prev, ...patch, block: { ...prev.block, ...(patch.block || {}) } });
    s.media = { ...(s.media || {}), danmaku: next };
    broadcast();
    if (!save) return true;
    try {
      if (typeof plugin.markSettingDirty === 'function') plugin.markSettingDirty('media');
      if (typeof plugin.saveSettings === 'function') await plugin.saveSettings();
      return true;
    } catch (e) {
      const cur = plugin.settings || s;
      cur.media = { ...(cur.media || {}), danmaku: prev };
      broadcast();
      say('没保存上，开关已拨回原来的位置：' + ((e && e.message) || e), 'error');
      return false;
    }
  }
  const toggle = async (fromKey) => {
    const on = !settingsOf(plugin).on;
    const p = setSetting({ on }, true);
    if (fromKey) showFlash(on ? '弹幕：开（再按 D 关）' : '弹幕：关（再按 D 开）');
    return p;
  };

  // 批注变了（批注框存完发 link-brain:annotations，或重开时重读）：按 key 对一遍——没变的不动，删掉 / 改过的撤下，
  // 新写的（这一端刚记的、时间就在眼前）立刻挤上画面，其余排进时间线等播到那里
  function setMine(next) {
    const cur = new Map(engine.items.filter(d => d.mine).map(d => [d.id, d]));
    const now = curTime(), on = settingsOf(plugin).on;
    const fresh = [];
    for (const d of next) {
      const old = cur.get(d.id);
      if (old && old.text === d.text && old.time === d.time) { cur.delete(d.id); continue; }
      if (old) { engine.removeItem(old); cur.delete(d.id); }
      else if (on && Math.abs(d.time - now) <= 3) { fresh.push(d); continue; }
      const idx = upperBound(engine.items, d.time); engine.items.splice(idx, 0, d); if (idx <= engine.next) engine.next++;
      // 改了字的那条如果此刻本该在画面上：按原出发时间放回去
      if (on && old && d.time <= engine.t && engine.t - d.time < engine.dur) engine.emit(d, d.time);
    }
    for (const old of cur.values()) engine.removeItem(old);
    for (const d of fresh) { if (Math.abs(engine.t - now) > 0.25) engine.reset(now); engine.insertNow(d, now); }
    if (on && video.paused) engine.place(engine.t);
    updateCount();
  }
  const ws = plugin.app && plugin.app.workspace;
  let wsRef = null;
  if (ws && typeof ws.on === 'function') {
    wsRef = ws.on(ANNOT_EVENT, (id, data) => {
      if (String(id || '') !== itemKey || !alive()) return;
      try { setMine(annotationItems(data)); } catch (e) { console.error('[lb] 批注弹幕没换上', e); }
    });
  }

  // 键盘：焦点在这条视频（或它的工具行）上按 D；全屏时焦点在哪都算
  const onKey = (e) => {
    if (!alive()) { ctl.destroy(); return; }
    if (!e || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    if (e.key === 'Escape' && !panel.hidden) { const t = e.target; if (t && panel.contains(t)) { e.preventDefault(); e.stopPropagation?.(); closePanel(); menuBtn.focus?.(); } return; }
    if (e.key !== 'd' && e.key !== 'D') return;
    const t = e.target;
    if (t && typeof t.closest === 'function' && t.closest('input, textarea, select, [contenteditable="true"], .cm-editor')) return;
    const inMedia = !!(t && typeof media.contains === 'function' && media.contains(t));
    const fs = (doc && doc.fullscreenElement === media) || media.classList.contains('is-lb-fullscreen');
    if (!inMedia && !fs) return;
    e.preventDefault();
    toggle(true);
  };
  doc.addEventListener('keydown', onKey);

  const blurAfterMouse = (b, e) => { if (e && e.detail && typeof b.blur === 'function') b.blur(); };
  toggleBtn.addEventListener('click', e => { blurAfterMouse(toggleBtn, e); toggle(false); });
  menuBtn.addEventListener('click', e => { blurAfterMouse(menuBtn, e); if (panel.hidden) openPanel(); else closePanel(); });
  closeBtn.addEventListener('click', () => closePanel());

  const onPlay = () => { lastVt = -1; startLoop(); };
  const onPause = () => { stopLoop(); if (settingsOf(plugin).on) engine.place(engine.t); };
  const onSeeked = () => { syncTo(); if (!video.paused) startLoop(); };
  const onReset = () => { engine.t = 0; syncTo(); };
  video.addEventListener('play', onPlay);
  video.addEventListener('playing', onPlay);
  video.addEventListener('pause', onPause);
  video.addEventListener('ended', onPause);
  video.addEventListener('seeked', onSeeked);
  video.addEventListener('emptied', onReset);
  const RO = win && win.ResizeObserver;
  if (typeof RO === 'function') { try { ro = new RO(() => measureLayer()); ro.observe(slide); } catch { ro = null; } }

  const ctl = {
    sid, itemId: itemKey, media, video, layer, panel, toggleBtn, menuBtn, engine, on: false,
    applySettings, setSetting, toggle, setMine, openPanel, closePanel,
    get origState() { return origState; },
    // 测试用：不等 rAF，按给定时间画一帧
    tick(t) { engine.frame(t); },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      stopLoop(); clearTimeout(flashTimer);
      try { if (ro) ro.disconnect(); } catch {}
      try { if (wsRef && ws && typeof ws.offref === 'function') ws.offref(wsRef); } catch {}
      doc.removeEventListener('keydown', onKey);
      doc.removeEventListener('pointerdown', onDocDown, true);
      for (const [t, fn] of [['play', onPlay], ['playing', onPlay], ['pause', onPause], ['ended', onPause], ['seeked', onSeeked], ['emptied', onReset]]) video.removeEventListener(t, fn);
      engine.clear();
      for (const el of [layer, flash, panel, toggleBtn, menuBtn]) { try { el.remove(); } catch {} }
      media.classList.remove('lb-dm-off');
      if (media.__lbDanmaku === ctl) media.__lbDanmaku = null;
      live.delete(ctl);
    },
  };
  media.__lbDanmaku = ctl;
  live.add(ctl);
  measureLayer();
  applySettings();
  return ctl;
}

// 设置变了：所有挂着的视频一起换；已经不在文档里的顺手拆掉
function broadcast() {
  for (const c of [...live]) {
    if (c.media.isConnected === false) { c.destroy(); continue; }
    try { c.applySettings(); } catch (e) { console.error('[lb] 弹幕设置没换上', e); }
  }
}
function destroyAll() { for (const c of [...live]) c.destroy(); xmlCache.clear(); }

module.exports = {
  attach, destroyAll, broadcast, normalizeSettings, parseXml, parseAdv, sourceIdOf, annotationItems, readNotes, Engine,
  controllers: live, DEFAULTS, AREAS, SPEEDS, NOTES_FILE, ANNOT_EVENT, ADV_MAX, AWAKE_MS, SCROLL_SEC, FIX_SEC, MAX_LIVE, estimateWidth, lowerBound, upperBound,
};

// danmaku.js — 1031 她：B 站视频的弹幕。media-nav 给正文视频装工具行时调 attach()：
// 只认 B 站来源（item_id 是 bili-<BV>，或视频地址在 _archive/bilibili/<BV>/ 下），读 meta.json → 当前版本 manifest 里 role=danmaku 的 XML，
// 连同她本地发的 `_archive/bilibili/<BV>/danmaku-mine.json`（只存本机，绝不发到 B 站；格式见 FORMAT.md「B 站弹幕：本地发的弹幕」）一起，
// 叠在画面上播：滚动 / 顶部 / 底部三种，跟 video.currentTime 走（暂停就停、拖进度条按新时间重排、倍速跟着变），全屏时照样在（层挂在 .lb-media 里）。
// 性能：弹幕按时间排好、只往前走一个指针；只给屏幕上的那几十条建节点（节点回收复用）；每帧只改这几条的 transform，宽度用 canvas 量字、不读布局。
// 设置记在插件设置 settings.media.danmaku（所有视频共用）：开关、透明度、字号、显示区域、滚动速度、屏蔽三种。焦点在视频上按 D 开关（全屏里也行）。
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
const MINE_FILE = 'danmaku-mine.json';
const TEXT_MAX = 100;
const STYLE_ID = 'lb-danmaku-style';
const SID_RE = /^[A-Za-z0-9_-]{3,64}$/;

const live = new Set();          // 当前挂着的控制器（设置一变全都换；插件卸载全拆）
const xmlCache = new Map();      // 「文件路径 + sha256」→ 解析好的原弹幕（同一篇重画不重读重解析；最多 12 份）
const writeChains = new Map();   // danmaku-mine.json 路径 → 写盘链（同一个文件的写排队）

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
// B 站模式：1 / 2 / 3 滚动（2、3 是旧的变体）、6 逆向（当滚动画）、4 底部、5 顶部；7 高级 / 8 代码 / 9 BAS 不画
const MODE = { 1: 'scroll', 2: 'scroll', 3: 'scroll', 6: 'scroll', 4: 'bottom', 5: 'top' };
const MODE_CODE = { scroll: 1, bottom: 4, top: 5 };
function parseXml(text) {
  const out = [];
  const re = /<d\s[^>]*?\bp\s*=\s*"([^"]*)"[^>]*>([\s\S]*?)<\/d>/g;
  const src = String(text || '');
  let m;
  while ((m = re.exec(src))) {
    const p = m[1].split(',');
    const time = Number(p[0]), mode = MODE[Number(p[1])];
    if (!Number.isFinite(time) || time < 0 || !mode) continue;
    const txt = decodeEntities(m[2]).replace(/\s*[\r\n]+\s*/g, ' ').trim();
    if (!txt) continue;
    const color = Number(p[3]);
    out.push({ time, mode, size: clamp(Number(p[2]) || 25, 12, 64), color: Number.isFinite(color) ? color & 0xffffff : 0xffffff, text: txt, mine: false });
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
    // 字号跟着画面大小走（小窗里 25 号字不至于占半屏，全屏也不至于太小），再乘她调的倍数
    this.k = clamp(Math.sqrt(Math.max(1, this.W * this.H)) / 800, 0.55, 1.25) * s.scale;
    this.laneH = Math.max(12, Math.ceil(25 * this.k * 1.3));
    this.nLanes = Math.max(1, Math.floor((this.H * s.area) / this.laneH));
    this.dur = SCROLL_SEC / s.speed;
    this.lanes = { scroll: new Array(this.nLanes).fill(null), top: new Array(this.nLanes).fill(null), bottom: new Array(this.nLanes).fill(null) };
  }
  fontPx(d) { return Math.max(10, Math.round(d.size * this.k)); }
  // 放一条：找一行不会撞车的；没有就丢（force = 她刚发的那条，挤也要挤上去）。visibleNow = 一出来就整条在画面里（暂停时发也看得见）
  emit(d, start, { force = false, visibleNow = false } = {}) {
    const s = this.settings;
    if (!force && (s.block[d.mode] || this.live.length >= MAX_LIVE)) return null;
    const px = this.fontPx(d), w = this.measure(d.text, px, this.doc) + (d.mine ? 10 : 0);
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
    const y = d.mode === 'bottom' ? Math.max(0, this.H - (lane + 1) * this.laneH) : lane * this.laneH;
    const rec = { d, el, mode: d.mode, lane, start, w, v, y, dead: false };
    el.style.transform = d.mode === 'scroll' ? `translate3d(${this.W}px,${y}px,0)` : `translate3d(-50%,${y}px,0)`;
    this.lanes[d.mode][lane] = rec;
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
      } else if (t - r.start >= FIX_SEC) { this.drop(r); continue; }
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
    let i = lowerBound(items, t - Math.max(this.dur, FIX_SEC));
    for (; i < items.length && items[i].time <= t; i++) {
      const d = items[i], age = t - d.time;
      if (d.mode === 'scroll' ? age < this.dur : age < FIX_SEC) this.emit(d, d.time);
    }
    this.next = i;
    this.place(t);
  }
  // 她刚发的一条：插进时间线（已经播过的位置，不会被指针再放一次），立刻挤上画面
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
function cleanText(s) { return String(s == null ? '' : s).replace(/[\r\n\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim().slice(0, TEXT_MAX); }
function isoNow(d = new Date()) {
  const p = n => String(Math.floor(Math.abs(n))).padStart(2, '0');
  const off = -d.getTimezoneOffset();
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${off >= 0 ? '+' : '-'}${p(off / 60)}:${p(off % 60)}`;
}
function mineToItem(r) {
  const mode = MODE[Number(r.mode)] || 'scroll';
  return { time: Number(r.time), mode, size: clamp(Number(r.size) || 25, 12, 64), color: Number.isFinite(Number(r.color)) ? Number(r.color) & 0xffffff : 0xffffff, text: cleanText(r.text), mine: true, id: String(r.id || '') };
}
function validMine(r) { return r && typeof r === 'object' && Number.isFinite(Number(r.time)) && Number(r.time) >= 0 && typeof r.text === 'string' && cleanText(r.text); }

// danmaku-mine.json：{ok, items, broken}。文件不在 = 空；上次换名换到一半崩了（只剩 .bak）就读 .bak；读不懂 = broken（不许覆盖它）
async function readMineDoc(adapter, file) {
  for (const p of [file, file + '.bak']) {
    let raw;
    try { if (typeof adapter.exists === 'function' && !(await adapter.exists(p))) continue; raw = await adapter.read(p); }
    catch { continue; }
    let doc = null;
    try { doc = JSON.parse(String(raw).replace(/^﻿/, '')); } catch { return { items: [], broken: true, path: p }; }
    if (!doc || typeof doc !== 'object' || !Array.isArray(doc.items)) return { items: [], broken: true, path: p };
    return { items: doc.items.filter(validMine), broken: false, path: p, doc };
  }
  return { items: [], broken: false, path: null };
}
// 原子写（CONVENTIONS §6.5）：先写 .tmp 再换名。Obsidian 的 adapter.rename 目标已存在会报错：旧的先挪成 .bak，换名成功再删 .bak；失败把旧的挪回去
async function writeJsonAtomic(adapter, file, obj) {
  const text = JSON.stringify(obj, null, 2) + '\n';
  const tmp = file + '.tmp', bak = file + '.bak';
  await adapter.write(tmp, text);
  const had = typeof adapter.exists === 'function' ? await adapter.exists(file) : false;
  if (had) {
    if (await adapter.exists(bak)) await adapter.remove(bak);
    await adapter.rename(file, bak);
  }
  try { await adapter.rename(tmp, file); }
  catch (e) { if (had) { try { await adapter.rename(bak, file); } catch {} } throw e; }
  if (had) { try { await adapter.remove(bak); } catch {} }
}
function chain(key, fn) {
  const prev = writeChains.get(key) || Promise.resolve();
  const p = prev.then(fn, fn);
  writeChains.set(key, p.catch(() => {}));
  return p;
}
// 追加一条：在写盘链里先读磁盘最新（别的窗口可能也发过），再写回
function appendMine(adapter, file, rec, head) {
  return chain(file, async () => {
    const cur = await readMineDoc(adapter, file);
    if (cur.broken) throw new Error(MINE_FILE + ' 读不懂，没改它（先把它挪走或修好）');
    const items = cur.items.filter(x => x.id !== rec.id).concat([rec]);
    await writeJsonAtomic(adapter, file, { schema_version: 1, item_id: head.item_id, source_id: head.source_id, updated_at: rec.created_at, items });
  });
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
  '.lb-dm-flash{position:absolute;left:12px;bottom:12px;z-index:5;pointer-events:none;padding:2px 10px;border-radius:var(--lb-radius-pill);background:rgb(0 0 0 / .6);color:#fff;font-family:var(--lb-font-body);font-size:var(--lb-fs-small);opacity:0;transition:opacity .2s;}',
  '.lb-dm-flash.is-on{opacity:1;}',
  '.xhs-note .lb-media-tools .lb-dm-toggle,.xhs-note .lb-media-tools .lb-dm-menu{font-size:13px!important;}',
  '.xhs-note .lb-media-tools .lb-dm-toggle[aria-pressed="true"]{color:var(--lb-ink);font-weight:600;}',
  '.xhs-note .lb-media-locked .lb-media:has(video) .lb-media-tools .lb-dm-toggle[aria-pressed="true"]{color:#fff;}',
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
  '.lb-dm-send{display:flex;align-items:center;gap:var(--lb-space-2);margin:0 0 var(--lb-space-3);}',
  '.lb-dm-send[hidden]{display:none!important;}',
  '.lb-dm-send .lb-dm-input{flex:1;min-width:0;height:30px;box-sizing:border-box;padding:0 var(--lb-space-3);border:1px solid var(--lb-line);border-radius:var(--lb-radius-pill);background:var(--lb-soft);color:var(--lb-ink);font-family:var(--lb-font-body);font-size:var(--lb-fs-small);}',
  '.lb-dm-send .lb-dm-send-btn{flex:none;height:30px;padding:0 var(--lb-space-4);border:0;border-radius:var(--lb-radius-pill);background:var(--lb-accent);color:var(--lb-surface);box-shadow:none;font-family:var(--lb-font-body);font-size:var(--lb-fs-small);cursor:pointer;}',
  '.lb-dm-send .lb-dm-send-btn:disabled{opacity:.45;cursor:default;}',
  '.xhs-note .lb-media.is-lb-fullscreen .lb-dm-panel{bottom:auto!important;top:12px!important;}',
  '@media print{.lb-dm-layer,.lb-dm-send,.lb-dm-panel,.lb-dm-flash{display:none!important;}}',
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
  const minePath = `${base}/${MINE_FILE}`;
  const mineDoc = await readMineDoc(adapter, minePath);
  if (mineDoc.broken) console.error('[lb] ' + minePath + ' 读不懂，先不播我发的弹幕');
  const mine = mineDoc.items.map(mineToItem).filter(d => d.text);
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
  const toggleBtn = btn(doc, 'lb-dm-toggle', '弹幕');
  const menuBtn = btn(doc, 'lb-dm-menu', '弹幕设置');
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
  tip.textContent = '点一下画面再按 D 开关弹幕（全屏里也能按）。自己发的弹幕带细框，只存在本机，不会发到 B 站。';
  panel.appendChild(tip);
  const closeBtn = btn(doc, 'lb-dm-close', '收起'); panel.appendChild(closeBtn);
  media.appendChild(panel);

  // 视频下面一条发弹幕（不挡画面；弹幕关着时收起）
  const sendRow = div(doc, 'lb-dm-send');
  const input = doc.createElement('input'); input.type = 'text'; input.className = 'lb-dm-input';
  input.maxLength = TEXT_MAX; input.setAttribute('maxlength', String(TEXT_MAX));
  input.placeholder = '发个弹幕：只存在本机，不会发到 B 站（Enter 发送）';
  input.setAttribute('aria-label', '发弹幕');
  const sendBtn = btn(doc, 'lb-dm-send-btn', '发送');
  sendRow.appendChild(input); sendRow.appendChild(sendBtn);
  if (typeof media.after === 'function') media.after(sendRow);
  else if (media.parentNode) media.parentNode.insertBefore(sendRow, media.nextSibling);

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
    count.textContent = `${head} · 我发的 ${nMine} 条` + (mineDoc.broken ? `（${MINE_FILE} 读不懂，先没播）` : '');
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
    sendRow.hidden = !s.on;
    media.classList.toggle('lb-dm-off', !s.on);
    toggleBtn.setAttribute('aria-pressed', String(s.on));
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

  async function send(raw) {
    const text = cleanText(raw);
    if (!text) return false;
    const t = curTime();
    const rec = { id: 'm' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), time: Math.round(t * 1000) / 1000, text, mode: MODE_CODE.scroll, color: 0xffffff, size: 25, created_at: isoNow() };
    const d = mineToItem(rec);
    if (settingsOf(plugin).on) { if (Math.abs(engine.t - t) > 0.25) engine.reset(t); engine.insertNow(d, t); }
    else { const idx = upperBound(engine.items, d.time); engine.items.splice(idx, 0, d); if (idx <= engine.next) engine.next++; }
    if (input.value && cleanText(input.value) === text) input.value = '';
    updateCount();
    try {
      await appendMine(adapter, minePath, rec, { item_id: meta.item_id || ('bili-' + sid), source_id: meta.source_id || sid });
      return true;
    } catch (e) {
      engine.removeItem(d); updateCount();
      if (!input.value) input.value = text;
      say('没保存上，内容还在，可重试：' + ((e && e.message) || e), 'error');
      return false;
    }
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
  sendBtn.addEventListener('click', () => { send(input.value); });
  input.addEventListener('keydown', e => {
    e.stopPropagation?.();   // 打字时 D / ←→ 不归视频
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); send(input.value); }
    else if (e.key === 'Escape') { e.preventDefault(); input.blur?.(); }
  });

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
    sid, media, video, layer, panel, sendRow, toggleBtn, menuBtn, engine, input, on: false,
    applySettings, setSetting, toggle, send, openPanel, closePanel,
    get origState() { return origState; },
    // 测试用：不等 rAF，按给定时间画一帧
    tick(t) { engine.frame(t); },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      stopLoop(); clearTimeout(flashTimer);
      try { if (ro) ro.disconnect(); } catch {}
      doc.removeEventListener('keydown', onKey);
      doc.removeEventListener('pointerdown', onDocDown, true);
      for (const [t, fn] of [['play', onPlay], ['playing', onPlay], ['pause', onPause], ['ended', onPause], ['seeked', onSeeked], ['emptied', onReset]]) video.removeEventListener(t, fn);
      engine.clear();
      for (const el of [layer, flash, panel, sendRow, toggleBtn, menuBtn]) { try { el.remove(); } catch {} }
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
  attach, destroyAll, broadcast, normalizeSettings, parseXml, sourceIdOf, readMineDoc, writeJsonAtomic, appendMine, Engine,
  controllers: live, DEFAULTS, AREAS, SPEEDS, MINE_FILE, SCROLL_SEC, FIX_SEC, MAX_LIVE, estimateWidth, lowerBound, upperBound,
};

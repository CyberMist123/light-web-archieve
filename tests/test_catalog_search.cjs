// 搜索回归（第 1 批 1002）：和 Python tests/test_search_regression.py 读同一份查询集 + 合成数据。
// 跑法：node tests/test_catalog_search.cjs
// 查询集每条：must_top = 精确命中区按顺序以这几篇开头；must_include = 在精确命中区；
// fuzzy_only = 出现、但只在「可能相关」区；must_exclude = 完全不出现；exact_max = 精确命中区最多几篇。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const SEARCH = fs.readFileSync('link_brain/assets/catalog-search.js', 'utf8');
const LIB = fs.readFileSync('link_brain/assets/lb-page-lib.js', 'utf8');
const VIEW = fs.readFileSync('link_brain/assets/catalog-view.js', 'utf8');
const data = JSON.parse(fs.readFileSync('tests/fixtures/catalog-data.sample.json', 'utf8'));
const queries = JSON.parse(fs.readFileSync('tests/fixtures/search_queries.json', 'utf8'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(SEARCH + '\nthis.S={normalize,score,matchItem,rankItems,resolveQuery,pinyinUnits,pinyinMatch,hitExcerpt,hitSummary,splitPhrase};', ctx);
const S = ctx.S;

function check(q, exact, possible) {
  const e = Array.from(exact, r => r.it.id), p = Array.from(possible, r => r.it.id);  // vm 里的数组换成本地数组再比
  const all = new Set([...e, ...p]);
  const tag = `「${q.query}」 exact=${JSON.stringify(e)} possible=${JSON.stringify(p)}`;
  assert.deepEqual(e.slice(0, q.must_top.length), q.must_top, 'must_top ' + tag);
  for (const id of q.must_include || []) assert.ok(e.includes(id), `must_include ${id} ${tag}`);
  for (const id of q.fuzzy_only || []) assert.ok(p.includes(id) && !e.includes(id), `fuzzy_only ${id} ${tag}`);
  for (const id of q.must_exclude || []) assert.ok(!all.has(id), `must_exclude ${id} ${tag}`);
  if (q.exact_max != null) assert.ok(e.length <= q.exact_max, `exact_max ${tag}`);
}

// ── 1. 纯函数：resolveQuery（拆短语 / 口语）→ rankItems（精确 / 可能相关，分数优先 + 星标 ×1.15） ──
for (const q of queries) {
  const committed = S.resolveQuery(q.query, data.items, data.pinyin_chars, data.aliases);
  const r = S.rankItems(data.items, S.normalize(committed), data.pinyin_chars, data.aliases);
  check(q, r.exact, r.possible);
}
assert.equal(S.resolveQuery('悉尼咖啡', data.items, data.pinyin_chars, data.aliases), '悉尼 咖啡', '库里没有的整串短语拆成库里有的词');
assert.equal(S.resolveQuery('AI做梦', data.items, data.pinyin_chars, data.aliases), 'ai 做梦', '中英混写库里没有整串就按字母 / 汉字分开');
assert.equal(S.resolveQuery('西尼咖啡馆', data.items, data.pinyin_chars, data.aliases), '西尼咖啡馆', '拆不成「每段至少两个字且库里都有」就不拆');
// 拼音整音节规则
const sy = ['xi', 'ni', '/', 'xin', 'nian', 'ka', 'fei'];
const units = t => S.pinyinUnits(S.normalize(t), {悉: 'xi', 西: 'xi', 尼: 'ni', 新: 'xin', 年: 'nian', 咖: 'ka', 啡: 'fei'});
for (const t of ['西尼', 'xini', '新年', 'xinnian', '新nian', 'kafei']) assert.ok(S.pinyinMatch(sy, units(t)), t);
for (const t of ['xin', 'xi', '西', 'xinian', 'nixin', 'xinia', '尼新']) assert.ok(!S.pinyinMatch(sy, units(t)), t);
assert.equal(S.pinyinUnits('悉尼2', {悉: 'xi', 尼: 'ni'}), null, '带数字不按拼音猜');
assert.equal(S.pinyinUnits('悉尼', {悉: 'xi'}), null, '有字查不到读音就不走拼音');
// 旧数据（拼音连写）整音节自然不中，不会撑爆
assert.equal(S.score({title: '新年计划', pinyin: 'xinnianjihua'}, '西尼', {西: 'xi', 尼: 'ni'}), 0);
// 命中摘录：按第一个有原文命中的词定位；「悉尼」只在标题 → 用「咖啡」在图片文字里的位置，并高亮
const walk = data.items.find(it => it.id === 'syd-walk');
const m = S.matchItem(walk, '悉尼 咖啡', data.pinyin_chars, data.aliases);
const ex = S.hitExcerpt(walk, m);
assert.equal(ex.label, '图片文字');
assert.deepEqual(Array.from(ex.marks, ([a, b]) => ex.text.slice(a, b)), ['咖啡']);
assert.equal(S.hitSummary(m), '命中标题、图片文字');
const market = data.items.find(it => it.id === 'syd-market');
const exm = S.hitExcerpt(market, S.matchItem(market, '悉尼', data.pinyin_chars, data.aliases));
assert.equal(exm.label, '正文');assert.ok(exm.text.startsWith('悉尼每个周末'));
const fuzzyWalk = S.matchItem(walk, '西尼', data.pinyin_chars, data.aliases);
assert.ok(fuzzyWalk.fuzzy);assert.equal(S.hitSummary(fuzzyWalk), '拼音相近：西尼');assert.equal(S.hitExcerpt(walk, fuzzyWalk), null);
console.log(`PASS search rules: ${queries.length} regression queries (pinyin whole-syllable, possible zone, score-first star boost, phrase split, excerpts)`);

// ── 1b. 第 10 批：英文按词边界 + 每条结果的命中类型 / 命中片段（row.hit） ──
{
  const S2 = (() => { const c = {}; vm.createContext(c); vm.runInContext(SEARCH + '\nthis.S={hasTerm,termIndex,rankItems,normalize,hitInfo};', c); return c.S; })();
  assert.ok(!S2.hasTerm('cafeine free', 'ai'), 'cafeine 不算命中 ai');
  assert.ok(S2.hasTerm('ai做梦', 'ai') && S2.hasTerm('openai 的 ai', 'ai') === true);
  assert.ok(S2.hasTerm('llms', 'llm') && !S2.hasTerm('llmxyz', 'llm'), '短词允许复数，不许接别的字母');
  assert.ok(S2.hasTerm('dreaming', 'dream') && !S2.hasTerm('daydream', 'dream'), '长词按词首');
  assert.equal(S2.termIndex('cafeine ai', 'ai'), 8);
  const rows = q => { const r = S2.rankItems(data.items, S2.normalize(q), data.pinyin_chars, data.aliases); return [...r.exact, ...r.possible]; };
  // 原词命中：高置信度，片段来自原文并标出位置
  const walk = rows('咖啡').find(r => r.it.id === 'syd-walk').hit;
  assert.equal(walk.kind, 'exact'); assert.equal(walk.confidence, 'high');
  assert.equal(walk.snippet.field, 'ocr'); assert.equal(walk.snippet.label, '图片文字');
  assert.deepEqual(Array.from(walk.snippet.marks, ([a, b]) => walk.snippet.text.slice(a, b)), ['咖啡']);
  // 换语种的同义词（做梦 → dream）：低置信度，片段是 dream 出现的那段
  const half = rows('做梦').find(r => r.it.id === 'half-price').hit;
  assert.equal(half.kind, 'alias'); assert.equal(half.confidence, 'low'); assert.ok(half.crossLanguage);
  assert.equal(half.variant, 'dream'); assert.ok(/dream/i.test(half.snippet.text));
  // 拼音（西尼 → 悉尼）：低置信度，原文里没有这个词，片段给标题
  const py = rows('西尼').find(r => r.it.id === 'syd-walk').hit;
  assert.equal(py.kind, 'pinyin'); assert.equal(py.confidence, 'low'); assert.equal(py.snippet.field, 'title');
  // 批注命中：片段标「批注」
  const note = rows('复刻').find(r => r.it.id === 'note-only').hit;
  assert.equal(note.snippet.label, '批注'); assert.equal(note.confidence, 'high');
  // 只在图片文字里的一两个字母（AI）：低置信度，进「可能相关」
  const bits = S2.rankItems(data.items, S2.normalize('ai 助手'), data.pinyin_chars, data.aliases);
  const ocrAi = bits.possible.find(r => r.it.id === 'ocr-ai');
  assert.ok(ocrAi && !bits.exact.some(r => r.it.id === 'ocr-ai'));
  assert.equal(ocrAi.hit.kind, 'ocrbits'); assert.equal(ocrAi.hit.confidence, 'low'); assert.equal(ocrAi.hit.snippet.label, '图片文字');
  console.log('PASS batch 10: latin word boundary (cafeine ≠ ai), row.hit kind / confidence / snippet, annotations searchable');
}

// ── 2. 真页面脚本：catalog-search.js + catalog-view.js 整段在假 DOM 里跑，输入查询按回车，看卡片顺序和摘录 ──
function fakeDom() {
  class El {
    constructor(tag) { this.tagName = String(tag).toUpperCase(); this.children = []; this.parent = null; this.attrs = {}; this.classList = new Set(); this.style = {}; this.hidden = false; this._text = ''; }
    get className() { return [...this.classList].join(' '); }
    set className(v) { this.classList = new Set(String(v || '').split(/\s+/).filter(Boolean)); }
    get textContent() { return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
    set textContent(v) { this.children = []; this._text = String(v); }
    createEl(tag, opts = {}) { const el = new El(tag); if (opts.cls) el.className = opts.cls; if (opts.text != null) el._text = String(opts.text); for (const [k, v] of Object.entries(opts)) if (!['cls', 'text'].includes(k)) el.setAttribute(k, v); this.append(el); return el; }
    append(...nodes) { for (const n of nodes) { if (n instanceof El) n.parent = this; this.children.push(n); } }
    prepend(n) { if (n instanceof El) n.parent = this; this.children.unshift(n); }
    appendText(t) { this.children.push(String(t)); }
    empty() { this.children = []; this._text = ''; }
    setText(t) { this.textContent = t; }
    remove() { if (this.parent) { this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; } }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return this.attrs[k] ?? null; }
    closest() { return null; }
    focus() {}
    matches(sel) { const m = sel.match(/^([a-z]*)((?:\.[\w-]+)*)$/i); if (!m) return false; if (m[1] && this.tagName !== m[1].toUpperCase()) return false; return (m[2] || '').split('.').filter(Boolean).every(c => this.classList.has(c)); }
    all() { const out = []; for (const c of this.children) if (c instanceof El) out.push(c, ...c.all()); return out; }
    querySelector(sel) { return this.all().find(e => e.matches(sel)) || null; }
    querySelectorAll(sel) { return this.all().filter(e => e.matches(sel)); }
    getBoundingClientRect() { return {width: 0, height: 0, top: 0, bottom: 0}; }
  }
  const body = new El('body');
  return {El, document: {body, addEventListener() {}, removeEventListener() {}, querySelectorAll: s => body.querySelectorAll(s), createElementNS: (ns, t) => new El(t)}};
}
async function openCatalog() {
  const {El, document} = fakeDom();
  const root = new El('div');
  const app = {vault: {adapter: {read: async p => JSON.stringify(p.endsWith('sync-status.json') ? {} : data), getResourcePath: x => x}, getAbstractFileByPath: () => null},
    plugins: {plugins: {'link-brain-actions': {settings: {hiddenCats: []}, openAttachments() {}, openCategories() {}, openLibraryPage() {}}}},
    workspace: {openLinkText() {}}};
  const dv = {container: root, current: () => ({file: {folder: ''}}), page: () => null};
  await new Function('app', 'dv', 'document', 'window', 'return (async()=>{' + LIB + '\n' + SEARCH + '\n' + VIEW + '\n})()')(app, dv, document, {alert() {}, confirm: () => false});
  const input = root.querySelector('input.lbc-search');
  const grid = root.querySelector('div.lbc-grid');
  return {
    root,
    search(text) { input.value = text; input.onkeydown({key: 'Enter', isComposing: false, preventDefault() {}}); }
  };
}
(async () => {
  // 卡片没有 id 属性，用标题反查
  const byTitle = Object.fromEntries(data.items.map(it => [it.title, it.id]));
  const page = await openCatalog();
  const ids = () => page.root.querySelector('div.lbc-grid').all().filter(e => e.matches('.lbc-ctitle') || e.matches('.lbc-possible-head'))
    .map(e => e.matches('.lbc-possible-head') ? '|' : byTitle[e.textContent]);
  for (const q of queries) {
    page.search(q.query);
    const seq = ids(), cut = seq.indexOf('|');
    const exact = (cut < 0 ? seq : seq.slice(0, cut)).map(id => ({it: {id}}));
    const possible = (cut < 0 ? [] : seq.slice(cut + 1)).map(id => ({it: {id}}));
    check(q, exact, possible);
  }
  // 「悉尼 咖啡」第一张卡：只有标题，不出命中摘录（1002 她定：有标题就够了）
  page.search('悉尼 咖啡');
  const first = page.root.querySelector('article.lbc-card');
  assert.equal(first.querySelector('.lbc-ctitle').textContent, walk.title);
  assert.equal(first.querySelectorAll('.lbc-result-excerpt').length, 0);
  // 「西尼」：只有可能相关区
  page.search('西尼');
  assert.ok(page.root.querySelector('.lbc-possible-head').textContent.startsWith('可能相关 · 2 篇'));
  const fuzzyCard = page.root.querySelector('article.lbc-card');
  assert.ok(fuzzyCard.classList.has('is-possible'));
  assert.ok(page.root.querySelector('.lbc-sub').textContent.startsWith(`0 / ${data.items.length} 篇 · 可能相关 2`));
  // 没有查询词时不出摘录、不分区
  page.search('');
  assert.equal(page.root.querySelectorAll('.lbc-result-excerpt').length, 0);
  assert.equal(page.root.querySelectorAll('.lbc-possible-head').length, 0);
  console.log('PASS catalog page: Enter → exact cards, then 「可能相关」 group; cards show titles only');
})().catch(e => { console.error(e); process.exitCode = 1; });

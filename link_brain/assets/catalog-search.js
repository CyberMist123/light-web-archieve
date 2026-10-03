function normalize(value) { return String(value || '').normalize('NFKC').toLowerCase().trim(); }
function fuzzyContains(text, term) {
  if (text.includes(term)) return true;
  if (term.length < 3) return false;
  const limit = term.length >= 9 ? 2 : 1;
  let prev = Array.from({length: term.length + 1}, (_, i) => i);
  for (const char of text) {
    const row = [0];
    for (let j = 1; j <= term.length; j++) row[j] = Math.min(row[j-1]+1, prev[j]+1, prev[j-1]+(char===term[j-1]?0:1));
    if (row[term.length] <= limit) return true;
    prev = row;
  }
  return false;
}
// 1001 审计 ui-4：catalog-data 不再另存一份拼好的 search_text（全文存两遍、10MB）；摘录从 search_fields 现拼，旧数据兜底
function itemText(it) { const fs = it.search_fields; return (fs ? Object.values(fs).filter(Boolean).join('\n') : '') || it.search_text || it.summary || ''; }

// ── 搜索规则（第 1 批 1002，与 retrieval.py 对齐，回归集 tests/search_regression.json） ──
// 1. 每个词先找原词（含 search-aliases 里的同义词），命中 = 精确命中，按字段权重计分。
// 2. 原词不中才走模糊：标题错一个字 / 拼音整音节相同（同音错字「西尼」→悉尼）/ 漏字。
//    模糊命中的整篇放进「可能相关」区，排在精确命中之后，不混排。
// 3. 拼音只认整音节：「悉尼」= xi·ni 两个完整音节按顺序相邻；xin 撞不上 xi·ni；至少两个音节才算。
// 4. 多个词 = 都要中（AND）。排序先看分数，星标只 ×1.15（与 retrieval.rank 同口径），同分星标在前。
// notes = 她自己的批注（第 10 批进检索，和标签同权；与 retrieval.WEIGHTS 一致）
const SEARCH_WEIGHTS = {title:12,tags:10,notes:10,body:7,attachments:6,transcript:6,ocr:5,comments:3,summary:2,author:1};
const SEARCH_FIELD_LABELS = {title:'标题',tags:'标签',notes:'批注',body:'正文',attachments:'附件',transcript:'视频转写',ocr:'图片文字',comments:'评论',summary:'概要',author:'作者'};
const STAR_BOOST = 1.15;
const FUZZY_LABELS = {ocrbits:'图片里的零散字母', pinyin:'拼音相近', typo:'标题错字', gap:'漏字'};
const searchCache = new WeakMap();
function searchFields(it) {
  let fs = searchCache.get(it);
  if (!fs) {
    fs = Object.fromEntries(Object.entries({title:it.title,tags:(it.tags||[]).join(' '),summary:it.summary,author:it.author,...(it.search_fields||{body:it.search_text})}).map(([k,v])=>[k,normalize(v)]));
    searchCache.set(it,fs);
  }
  return fs;
}
function termVariants(term, aliases = []) {
  return [...new Set([term,...aliases.filter(g=>Array.isArray(g)&&(g.includes(term)||(term==='音'&&g.includes('音乐')))).flat().map(normalize)])];
}
// 英文按词边界（第 10 批，与 retrieval._pattern 同一规则）：字母 / 数字开头的词，前面不能紧挨字母数字（cafeine 不再命中 ai）；
// 4 个字母以下的纯字母数字词，后面也不能紧挨字母（允许复数 s / es：llm → llms）；长词按词首（dream → dreaming）。中文照旧子串。
const termRegexCache = new Map();
function termRegex(v) {
  if (termRegexCache.has(v)) return termRegexCache.get(v);
  let re = null;
  if (/^[a-z0-9]/.test(v)) {
    const tail = /^[a-z0-9]+$/.test(v) && v.length < 4 ? '(?:e?s)?(?![a-z])' : '';
    re = new RegExp('(?<![a-z0-9])' + v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + tail, 'g');
  }
  termRegexCache.set(v, re);
  return re;
}
function termIndex(text, v, from = 0) {
  const re = termRegex(v);
  if (!re) return text.indexOf(v, from);
  re.lastIndex = from;
  const m = re.exec(text);
  return m ? m.index : -1;
}
function hasTerm(text, v) { return !!v && text.includes(v) && termIndex(text, v) >= 0; }
// 图片文字里的一两个字母（ai、ok）：OCR 常把小字 / 货架标签拆出零散字母（超市小票里的「AI I」），只在图片文字里中的
// 一两个字母的英文词算低置信度命中（kind 'ocrbits'，进「可能相关」），不和原词命中混排。与 retrieval.match 同规则。
const isShortLatin = v => /^[a-z0-9]{1,2}$/.test(v) && !/^[0-9]+$/.test(v);
// 条目的拼音音节：catalog.py 写成空格分隔的整音节（标点处是「/」断开）。旧数据是连写的一长串，整音节匹配自然不中（fail-closed）。
const syllableCache = new WeakMap();
function itemSyllables(it) {
  let s = syllableCache.get(it);
  if (!s) { s = normalize(it.pinyin).split(/\s+/).filter(Boolean); syllableCache.set(it, s); }
  return s;
}
// 查询词 → 拼音单元：汉字一个字 = 一个整音节；连续字母 = 若干个相邻整音节拼起来。查不到读音的汉字 → null（不走拼音）。
function pinyinUnits(term, chars = {}) {
  const units = [];
  for (const part of term.match(/[a-z]+|[一-鿿]|[^\sa-z一-鿿]+/g) || []) {
    if (/^[a-z]+$/.test(part)) units.push({latin: part});
    else if (/^[一-鿿]$/.test(part)) { if (!chars[part]) return null; units.push({syl: normalize(chars[part])}); }
    else if (/[a-z0-9一-鿿]/.test(part)) return null;  // 数字等：不按拼音猜
  }
  return units.length ? units : null;
}
function pinyinMatch(sylls, units) {
  if (!units || !sylls.length) return false;
  const go = (u, s, used) => {
    if (u === units.length) return used >= 2;
    const unit = units[u];
    if (unit.syl) return s < sylls.length && sylls[s] === unit.syl && go(u + 1, s + 1, used + 1);
    let acc = '';
    for (let k = s; k < sylls.length && acc.length < unit.latin.length; k++) {
      acc += sylls[k];
      if (acc === unit.latin && go(u + 1, k + 1, used + k - s + 1)) return true;
    }
    return false;
  };
  for (let i = 0; i < sylls.length; i++) if (go(0, i, 0)) return true;
  return false;
}
// 一篇对一个查询的命中明细：{score, fuzzy, hits:[{term, kind, field, variant}]}；不中返回 null。
function matchItem(it, query, chars = {}, aliases = []) {
  const q = normalize(query);
  if (!q) return {score: 1, fuzzy: false, hits: []};
  if (q.startsWith('#')) {
    const wanted = q.split(/[\s#]+/).filter(Boolean);
    return wanted.some(t => (it.tags || []).some(tag => normalize(tag).replace(/^#/, '') === t)) ? {score: 10, fuzzy: false, hits: [{term: q, kind: 'exact', field: 'tags', variant: ''}]} : null;
  }
  const fs = searchFields(it);
  let total = 0, fuzzy = false;
  const hits = [];
  for (const term of q.split(/\s+/).filter(Boolean)) {
    let best = 0, hit = null;
    for (const v of termVariants(term, aliases)) for (const [key, text] of Object.entries(fs)) {
      const w = (SEARCH_WEIGHTS[key] || 1) * (v === term ? 1 : .75);
      if (w > best && hasTerm(text, v) && !(key === 'ocr' && isShortLatin(v))) { best = w; hit = {term, kind: v === term ? 'exact' : 'alias', field: key, variant: v}; }
    }
    if (best) { total += best; hits.push(hit); continue; }
    fuzzy = true;
    const bits = termVariants(term, aliases).find(v => isShortLatin(v) && hasTerm(fs.ocr || '', v));
    if (bits) { total += 2; hits.push({term, kind: 'ocrbits', field: 'ocr', variant: bits}); continue; }
    // 纯字母的短词（xin、ai）错一个字母 / 漏字母能撞上一大片英文单词：字母词至少 4 个才认这两种模糊
    const latinShort = /^[a-z0-9]+$/.test(term) && term.length < 4;
    if (!latinShort && fuzzyContains(fs.title, term)) { total += 3; hits.push({term, kind: 'typo', field: 'title'}); continue; }
    if (pinyinMatch(itemSyllables(it), pinyinUnits(term, chars))) { total += 2; hits.push({term, kind: 'pinyin', field: 'pinyin'}); continue; }
    // 漏字/不连续输入仅允许短距离跨越，避免从整篇不同位置拼出结果。
    const hay = Object.values(fs).join(' ');
    let gap = false;
    for (let start = hay.indexOf(term[0]); start >= 0 && term.length >= 2 && !latinShort; start = hay.indexOf(term[0], start + 1)) {
      let p = start;
      for (const c of term) { p = hay.indexOf(c, p); if (p < 0) break; p++; }
      if (p >= 0 && p-start <= term.length*2) { gap = true; break; }
    }
    if (gap) { total += 1; hits.push({term, kind: 'gap', field: ''}); continue; }
    return null;
  }
  return {score: total, fuzzy, hits};
}
function score(it, query, chars = {}, aliases = []) { const m = matchItem(it, query, chars, aliases); return m ? m.score : 0; }
// 排序：精确命中在前（exact），模糊命中单独一组（possible）。组内按 分数 × 星标加成，同分星标在前，再同分保持原顺序（新→旧）。
function rankItems(list, query, chars = {}, aliases = []) {
  const exact = [], possible = [];
  list.forEach((it, index) => {
    const m = matchItem(it, query, chars, aliases);
    if (!m || m.score <= 0) return;
    const row = {it, score: m.score, rank: m.score * (it.starred ? STAR_BOOST : 1), match: m, index};
    // 第 10 批：每条带命中类型和命中片段（row.hit，见 hitInfo），用到才算——几百条结果不必每条都切摘录
    let info;
    Object.defineProperty(row, 'hit', {enumerable: true, get() { if (info === undefined) info = hitInfo(it, m); return info; }});
    (m.fuzzy ? possible : exact).push(row);
  });
  const order = (a, b) => b.rank - a.rank || Number(!!b.it.starred) - Number(!!a.it.starred) || a.index - b.index;
  return {exact: exact.sort(order), possible: possible.sort(order)};
}

// 整串短语库里一处都没有时拆成库里有的词：「悉尼咖啡」→「悉尼 咖啡」、「AI做梦」→「ai 做梦」，和拆开输入找回同一批（不调 AI、不需词典）。
const corpusCache = new WeakMap();
function corpusText(list) {
  let text = corpusCache.get(list);
  if (text == null) { text = list.map(it => Object.values(searchFields(it)).join(' ')).join('\n'); corpusCache.set(list, text); }
  return text;
}
function splitPhrase(term, list) {
  const scripts = term.match(/[a-z0-9]+|[一-鿿]+/g) || [];
  const mixed = scripts.length > 1 && scripts.join('') === term && scripts.every(p => p.length >= 2);
  if (!mixed && !/^[一-鿿]{4,12}$/.test(term)) return term;
  const hay = corpusText(list);
  if (hay.includes(term)) return term;
  // 中英混写（「AI做梦」）先按字母 / 汉字分开，汉字那段再按下面的规则拆
  if (mixed) return scripts.map(p => /^[一-鿿]/.test(p) ? splitPhrase(p, list) : p).join(' ');
  const seen = new Map(), has = s => { if (!seen.has(s)) seen.set(s, hay.includes(s)); return seen.get(s); };
  // 段数最少的拆法；每段至少两个字、并且库里出现过（单字一拆就到处都中，宁可不拆）。
  const best = Array(term.length + 1).fill(null); best[0] = [];
  for (let i = 0; i < term.length; i++) {
    if (!best[i]) continue;
    for (let j = i + 2; j <= Math.min(term.length, i + 8); j++) {
      const part = term.slice(i, j);
      if (has(part) && (!best[j] || best[i].length + 1 < best[j].length)) best[j] = [...best[i], part];
    }
  }
  const got = best[term.length];
  return got && got.length > 1 ? got.join(' ') : term;
}
// 用户按回车时提交的查询：先原样；整串短语库里没有就拆词；还是什么都不中，就按口语整句抽关键词再试。
function resolveQuery(raw, list, chars = {}, aliases = []) {
  raw = String(raw || '').trim().replace(/^\//, '');
  if (!raw || raw.startsWith('#')) return raw;
  const split = text => normalize(text).split(/\s+/).filter(Boolean).map(t => splitPhrase(t, list)).join(' ');
  const any = q => list.some(it => matchItem(it, q, chars, aliases));
  const first = split(raw);
  if (any(first)) return first === normalize(raw) ? raw : first;
  const kw = spokenKeywords(raw);
  if (kw && kw !== raw) { const second = split(kw); if (any(second)) return second; }
  return raw;
}
// 卡片上的命中摘录：按查询里第一个有原文命中的词定位，标出来自哪里（正文 / 评论 / 图片文字 / 附件 / 视频转写），并给出要高亮的位置。
const EXCERPT_FIELDS = ['notes', 'body', 'ocr', 'attachments', 'transcript', 'comments', 'summary'];
function hitExcerpt(it, m, width = 120) {
  if (!m || !m.hits.length) return null;
  const raw = Object.assign({summary: it.summary, title: it.title}, it.search_fields || {body: it.search_text});
  const words = [...new Set(m.hits.filter(h => h.variant).flatMap(h => [h.variant, h.term]).filter(Boolean))].sort((a, b) => b.length - a.length);
  for (const h of m.hits) {
    if (!h.variant) continue;
    for (const field of EXCERPT_FIELDS) {
      const original = String(raw[field] || '');
      const lower = original.toLowerCase();
      let pos = termIndex(lower, h.variant), source = original;
      if (pos < 0) { const n = normalize(original); pos = termIndex(n, h.variant); source = n; }
      if (pos < 0) continue;
      const start = Math.max(0, pos - 30);
      let text = source.slice(start, start + width).replace(/\s+/g, ' ').trim();
      if (start > 0) text = '…' + text;
      if (start + width < source.length) text += '…';
      return {field, label: SEARCH_FIELD_LABELS[field], text, marks: markRanges(text, words)};
    }
  }
  return null;
}
// 一条结果的命中类型 + 命中片段（第 10 批，给卡片标题下的浅色小字用）：
// {kind: 'exact'|'alias'|'ocrbits'|'typo'|'pinyin'|'gap', confidence: 'high'|'low', crossLanguage, term, variant,
//  snippet: {field, label, text, marks: [[起, 止]…]} | null}
// kind = 这一篇里最弱的那种命中（错字 > 拼音 > 漏字 > 图片里的零散字母 > 同义词 > 原词）；低置信度 = 前四种，或换了语种的同义词（做梦 → dream）。
// snippet 优先给低置信度那个词的出处：同义词按原文摘一段；错字 / 拼音 / 漏字（原文里没有这个词）给标题。
const HIT_ORDER = ['typo', 'pinyin', 'gap', 'ocrbits', 'alias'];
const isLatin = s => /[a-z0-9]/.test(s) && !/[一-鿿]/.test(s);
function crossLanguage(h) { return h.kind === 'alias' && !!h.variant && isLatin(h.term) !== isLatin(h.variant); }
function hitInfo(it, m) {
  if (!m || !m.hits.length) return null;
  const lowHits = m.hits.filter(h => FUZZY_LABELS[h.kind] || crossLanguage(h));
  const kind = HIT_ORDER.find(k => m.hits.some(h => h.kind === k)) || 'exact';
  const focus = lowHits[0] || m.hits[0];
  let snippet = null;
  if (focus.variant) {
    snippet = hitExcerpt(it, {hits: [focus], fuzzy: m.fuzzy});
    if (!snippet && (focus.field === 'title' || focus.field === 'tags')) {
      const text = focus.field === 'title' ? String(it.title || '') : (it.tags || []).join(' ');
      snippet = {field: focus.field, label: SEARCH_FIELD_LABELS[focus.field], text, marks: markRanges(text, [focus.variant])};
    }
  }
  if (!snippet) snippet = {field: 'title', label: SEARCH_FIELD_LABELS.title, text: String(it.title || ''), marks: []};
  return {kind, confidence: lowHits.length ? 'low' : 'high', crossLanguage: m.hits.some(crossLanguage),
          term: focus.term, variant: focus.variant || '', snippet};
}
function markRanges(text, words) {
  const lower = text.toLowerCase(), out = [];
  for (const w of words) {
    if (!w) continue;
    for (let i = termIndex(lower, w); i >= 0; i = termIndex(lower, w, i + w.length)) {
      if (!out.some(([a, b]) => i < b && i + w.length > a)) out.push([i, i + w.length]);
    }
  }
  return out.sort((a, b) => a[0] - b[0]);
}
// 命中来源一句话：「标题、图片文字」/「拼音相近：西尼」，卡片上和摘录放一起。
function hitSummary(m) {
  if (!m || !m.hits.length) return '';
  const exact = [...new Set(m.hits.filter(h => h.variant || h.kind === 'exact').map(h => SEARCH_FIELD_LABELS[h.field]).filter(Boolean))];
  const fuzzy = m.hits.filter(h => FUZZY_LABELS[h.kind]).map(h => `${FUZZY_LABELS[h.kind]}：${h.term}`);
  return [...fuzzy, ...(exact.length ? ['命中' + exact.join('、')] : [])].join(' · ');
}

// 10-03（她定）：置信度低的命中（同义词 / 换语种 / 扩词 / 拼音相近 / 标题错字 / 漏字 / 语义）在卡片标题下浅色显示检索到的那段；
// 原词命中仍只显示标题（她的规矩：搜索卡片只留标题）。命中明细来自 matchItem 的 hits[].kind（exact 以外都算低置信度，
// 以后加的 kind 如 semantic 也算）；结果里带了现成片段（match.snippet / hit.snippet）就直接用。
const LOW_LABELS = {...FUZZY_LABELS, alias: '同义词', semantic: '意思相近', translate: '换语种', expand: '扩词'};
function lowConfidenceSnippet(it, m) {
  if (!m || !Array.isArray(m.hits) || !m.hits.length) return '';
  const low = m.hits.filter(h => h && h.kind && h.kind !== 'exact');
  if (!low.length) return '';
  const given = m.snippet || low.map(h => h.snippet).find(Boolean);
  if (given) return String(given).replace(/\s+/g, ' ').trim();
  const ex = hitExcerpt(it, {hits: low});
  if (ex) return `${ex.label}：${ex.text}`;
  return low.map(h => {
    const label = LOW_LABELS[h.kind] || '相关';
    if (h.variant && h.variant !== h.term) return `${label}：${h.term} → ${h.variant}`;
    return `${label}：${h.term}`;
  }).join(' · ');
}

// 语音/整句 → 关键词（0926）：去掉口头的「帮我找一下、那个、有没有…的」，剩下的词用空格分开，照常关键词+模糊匹配，不调用 AI。
const SPOKEN_FILLER = /帮我|给我|请你|请|我想要|我想|想要|想看|找一下|找找|搜一下|搜搜|查一下|查查|看一下|看看|一下|那个|这个|那篇|一篇|之前|以前|收藏里的?|收藏的|我收藏|收藏过?|笔记|关于|有关|有没有|有什么|有哪些|是什么|怎么做|怎么样|怎么|如何|什么|哪些|一些|的内容|的帖子|的吗|吗|呢|吧|啊|呀|嘛|了|找|搜/g;
function spokenKeywords(text) {
  const parts = String(text || '').replace(/[，。！？、,.!?；;：:“”"'（）()\s]+/g, ' ').replace(SPOKEN_FILLER, ' ')
    .split(/[\s的]+/).filter(t => t.length >= 2 || /[a-z0-9]/i.test(t));
  return [...new Set(parts)].join(' ');
}

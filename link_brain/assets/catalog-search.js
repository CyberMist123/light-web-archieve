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
const searchCache = new WeakMap();
function score(it, query, chars = {}, aliases = []) {
  const q = normalize(query);
  if (!q) return 1;
  if (q.startsWith('#')) {
    const wanted = q.split(/[\s#]+/).filter(Boolean);
    return wanted.some(t => (it.tags || []).some(tag => normalize(tag).replace(/^#/, '') === t)) ? 10 : 0;
  }
  let fs = searchCache.get(it);
  if (!fs) {
    fs = Object.fromEntries(Object.entries({title:it.title,tags:(it.tags||[]).join(' '),summary:it.summary,author:it.author,...(it.search_fields||{body:it.search_text})}).map(([k,v])=>[k,normalize(v)]));
    searchCache.set(it,fs);
  }
  const title = fs.title;
  const hay = Object.values(fs).join(' ');
  const weights={title:12,tags:10,body:7,attachments:6,transcript:6,ocr:5,comments:3,summary:2,author:1};
  let total = 0;
  for (const term of q.split(/\s+/).filter(Boolean)) {
    const variants=[term,...aliases.filter(g=>g.includes(term)||(term==='音'&&g.includes('音乐'))).flat()];
    let best=0;
    for(const v of new Set(variants))for(const [key,text] of Object.entries(fs))if(text.includes(v))best=Math.max(best,(weights[key]||1)*(v===term?1:.75));
    if(best){total+=best;continue;}
    if (fuzzyContains(title, term)) { total += 3; continue; }
    const phonetic = Array.from(term, c => chars[c] || c).join('');
    if (phonetic.length >= 3 && fuzzyContains(normalize(it.pinyin), phonetic)) { total += 2; continue; }
    // 漏字/不连续输入仅允许短距离跨越，避免从整篇不同位置拼出结果。
    let matched = false;
    for (let start = hay.indexOf(term[0]); start >= 0; start = hay.indexOf(term[0], start + 1)) {
      let p = start;
      for (const c of term) { p = hay.indexOf(c, p); if (p < 0) break; p++; }
      if (p >= 0 && p-start <= term.length*2 && term.length>=2) { matched=true; break; }
    }
    if (matched) { total++; continue; }
    return 0;
  }
  return total;
}

// 语音/整句 → 关键词（0926）：去掉口头的「帮我找一下、那个、有没有…的」，剩下的词用空格分开，照常关键词+模糊匹配，不调用 AI。
const SPOKEN_FILLER = /帮我|给我|请你|请|我想要|我想|想要|想看|找一下|找找|搜一下|搜搜|查一下|查查|看一下|看看|一下|那个|这个|那篇|一篇|之前|以前|收藏里的?|收藏的|我收藏|收藏过?|笔记|关于|有关|有没有|有什么|有哪些|是什么|怎么做|怎么样|怎么|如何|什么|哪些|一些|的内容|的帖子|的吗|吗|呢|吧|啊|呀|嘛|了|找|搜/g;
function spokenKeywords(text) {
  const parts = String(text || '').replace(/[，。！？、,.!?；;：:“”"'（）()\s]+/g, ' ').replace(SPOKEN_FILLER, ' ')
    .split(/[\s的]+/).filter(t => t.length >= 2 || /[a-z0-9]/i.test(t));
  return [...new Set(parts)].join(' ');
}

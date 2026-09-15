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
function score(it, query, chars = {}) {
  const q = normalize(query);
  if (!q) return 1;
  if (q.startsWith('#')) {
    const wanted = q.split(/[\s#]+/).filter(Boolean);
    return wanted.some(t => (it.tags || []).some(tag => normalize(tag).replace(/^#/, '') === t)) ? 10 : 0;
  }
  const title = normalize(it.title);
  const hay = normalize([it.title, it.summary, it.search_text, it.author, ...(it.tags||[])].join(' '));
  let total = 0;
  for (const term of q.split(/\s+/).filter(Boolean)) {
    if (title.includes(term)) { total += 10; continue; }
    if (hay.includes(term)) { total += 5; continue; }
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

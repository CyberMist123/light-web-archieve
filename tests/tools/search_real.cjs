// 真数据搜索对照（只读、只打印、不断言，结果不进仓）。
// 跑法：LB_REAL_CATALOG=<vault>/_archive/catalog-data.json node tests/tools/search_real.cjs 悉尼 "悉尼 咖啡" 西尼
//   可选 LB_REAL_VAULT=<vault>：按目录页的做法读每篇 notes.json 里的当前星标（不设就用 catalog-data 里的）。
// 用的是仓库里真实的 catalog-search.js（resolveQuery → rankItems，与目录页回车后的排序同一段代码）。
const fs = require('node:fs');
const path = require('node:path');

const file = process.env.LB_REAL_CATALOG;
if (!file) { console.error('请设 LB_REAL_CATALOG 指向 catalog-data.json'); process.exit(2); }
const src = fs.readFileSync(path.join(__dirname, '..', '..', 'link_brain', 'assets', 'catalog-search.js'), 'utf8');
const S = new Function(src + '\nreturn {normalize,resolveQuery,rankItems,hitSummary,hitExcerpt};')();
const data = JSON.parse(fs.readFileSync(file, 'utf8'));
const items = data.items || [];
const vault = process.env.LB_REAL_VAULT;
if (vault) for (const it of items) if (it.notes_path) { try { it.starred = !!JSON.parse(fs.readFileSync(path.join(vault, it.notes_path), 'utf8')).starred; } catch {} }
const syllableData = items.some(it => /\s/.test(it.pinyin || ''));
if (!syllableData) console.log('注意：这份 catalog-data 的 pinyin 还是旧的连写格式（没用新版 catalog 重建），拼音整音节匹配不会生效');

const queries = process.argv.slice(2);
for (const raw of (queries.length ? queries : ['悉尼', '悉尼 咖啡', '悉尼咖啡', '西尼', '鸡肉 电饭煲', '鸡肉 快手', 'AI 做梦', 'AI 记忆 开源'])) {
  const t0 = process.hrtime.bigint();
  const committed = S.resolveQuery(raw, items, data.pinyin_chars, data.aliases || []);
  const r = S.rankItems(items, S.normalize(committed), data.pinyin_chars, data.aliases || []);
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  console.log(`\n=== 「${raw}」 → 「${committed}」 精确 ${r.exact.length} · 可能相关 ${r.possible.length} / ${items.length}  (${ms.toFixed(1)} ms)`);
  const show = (rows, label) => rows.slice(0, 10).forEach((row, i) => {
    const ex = S.hitExcerpt(row.it, row.match);
    console.log(`${label}${i + 1}. ${row.it.starred ? '★' : ' '} s=${row.score} [${S.hitSummary(row.match)}] ${String(row.it.title).slice(0, 40)}${ex ? `  ‹${ex.label}› ${ex.text.slice(0, 40)}` : ''}`);
  });
  show(r.exact, '');
  if (r.possible.length) { console.log('--- 可能相关'); show(r.possible, '?'); }
  const stars = r.exact.map((row, i) => row.it.starred ? `#${i + 1}(s=${row.score})` : null).filter(Boolean);
  console.log('精确区星标位置：', stars.join(' ') || '无');
}

// Lot R1 子词回退：目录页 catalog-search.js 和 Python retrieval.keyword_hits 读同一份夹具 tests/fixtures/subword_r1.json、
// 同一规则（短查询原词只中 ≤2 篇时，稀有中文词拆单字进「可能相关」；整词命中多、或拼音已找回同音篇时不拆）。
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const SEARCH = fs.readFileSync('link_brain/assets/catalog-search.js', 'utf8');
const F = JSON.parse(fs.readFileSync('tests/fixtures/subword_r1.json', 'utf8'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(SEARCH + '\nthis.S={normalize,rankItems,subwordParts,lowSnippetFor};', ctx);
const S = ctx.S;

for (const c of F.cases) {
  const r = S.rankItems(F.items, S.normalize(c.query), F.chars, []);
  const exact = Array.from(r.exact, x => x.it.id), possible = Array.from(r.possible, x => x.it.id);
  const tag = `「${c.query}」 exact=${JSON.stringify(exact)} possible=${JSON.stringify(possible)}`;
  assert.deepEqual([...exact].sort(), [...c.exact].sort(), 'exact ' + tag);
  for (const id of c.possible_include) assert.ok(possible.includes(id), 'possible_include ' + id + ' ' + tag);
  for (const id of c.exclude) assert.ok(!exact.includes(id) && !possible.includes(id), 'exclude ' + id + ' ' + tag);
}
// 拆字命中的卡片：低置信度，标题下浅色小字给出处（沿用已有的低置信度显示，不改排版）
const r = S.rankItems(F.items, '面点', F.chars, []);
const sub = Array.from(r.possible).find(x => x.it.id === 'noodle-title');
assert.equal(sub.hit.kind, 'subword');
assert.equal(sub.hit.confidence, 'low');
assert.match(S.lowSnippetFor(sub), /面/);
assert.deepEqual(Array.from(S.subwordParts('面点')), ['面', '点']);
assert.deepEqual(Array.from(S.subwordParts('面点', ['面'])), []);
assert.deepEqual(Array.from(S.subwordParts('pasta')), []);
console.log('PASS catalog subword fallback (R1): same fixture as Python keyword_hits');

// 1015：检索全文拆到 _archive/catalog-search-index.json——目录首开（含首屏预热）不读它；第一次带词搜索才读，
// 读完按 id 并回 items、清缓存、调页面登记的 update 重算；读到之前这次搜索按标题 / 标签 / 概要出结果。
// 跑法：node tests/test_search_index_lazy_1015.cjs
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const reads = [], updates = [];
const index = {items: {a: {search_fields: {body: '正文里才有：番茄炒蛋先炒蛋'}, pinyin: 'jia chang cai'}, b: {search_fields: {body: '别的'}, pinyin: ''}}};
const app = {vault: {adapter: {read: async p => { reads.push(p); return JSON.stringify(index); }}}};
const provider = {};
const LB = {root: '', provider: () => provider, path: rel => rel, t() {},
  data: {versionSync: () => '1:10', version: async () => '1:10'},
  container: {__lbView: {version: 'v1', update: async v => { updates.push(v); }}}};
const ctx = {app, LB, console, setTimeout, requestIdleCallback: f => setTimeout(f, 0)};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('link_brain/assets/catalog-search.js', 'utf8') +
  '\nthis.rankItems=rankItems;this.resolveQuery=resolveQuery;this.warmSearch=warmSearch;this.ensureSearchIndex=ensureSearchIndex;this.st=searchIndexState;', ctx);

(async () => {
  const items = [{id: 'a', title: '家常菜', tags: [], summary: '概要'}, {id: 'b', title: '番茄图鉴', tags: [], summary: ''}];
  // 首开：空查询排序 + 首屏预热都不读索引
  ctx.rankItems(items, '', {}, []);
  const w = ctx.warmSearch(items, {idle: f => f()});
  assert.ok(w.done);
  assert.equal(reads.length, 0, '首开不读检索索引');
  // 第一次搜：先按标题出（b 中），后台读索引
  const first = ctx.rankItems(items, '番茄炒蛋', {}, []);
  assert.ok(!first.exact.some(r => r.it.id === 'a'), '索引没到之前正文命中不了');
  assert.ok(ctx.st.loading, '开始后台读');
  ctx.rankItems(items, '番茄炒蛋', {}, []);   // 读的过程中再搜不重复读
  await ctx.st.loading;
  assert.deepEqual(reads, ['_archive/catalog-search-index.json']);
  assert.deepEqual(updates, ['v1'], '读完让页面重算一次');
  assert.equal(items[0].search_fields.body, index.items.a.search_fields.body);
  assert.equal(items[0].pinyin, 'jia chang cai');
  const again = ctx.rankItems(items, '番茄炒蛋', {}, []);
  assert.equal(again.exact[0].it.id, 'a', '并回后正文命中（预热时缓存的字段已作废）');
  // 页面拿到一份新的 items（插件没缓存时 refresh 重读）：同版本的索引直接同步并回，不再读盘
  const fresh = [{id: 'a', title: '家常菜', tags: [], summary: '概要'}];
  assert.equal(ctx.ensureSearchIndex(fresh), true);
  assert.equal(fresh[0].search_fields.body, index.items.a.search_fields.body);
  assert.equal(reads.length, 1);
  // 旧数据（items 自带 search_fields）不读
  assert.equal(ctx.ensureSearchIndex([{id: 'z', search_fields: {body: 'x'}}]), true);
  // 解析结果挂在插件对象上，三张页共用
  assert.equal(provider.searchIndexCache.version, '1:10');
  console.log('PASS search index lazy: not read on first open/warm, read once on first search, merged + view.update, legacy untouched');
})().catch(e => { console.error(e); process.exit(1); });

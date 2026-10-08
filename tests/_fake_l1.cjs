// 批次 D · L1（目录 / 星标 / 回收站页）node 用例共用：在共享假 DOM（tests/_fakedom.cjs，冻结件）上开目录页。
'use strict';
const { asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const DATA = '_archive/catalog-data.json';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const code = ({ starred = false } = {}) => {
  let c = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('catalog-view.js');
  if (starred) c = c.replace('const simplePage = false;', 'const simplePage = true;').replace('const starredPage = false;', 'const starredPage = true;');
  return c;
};
function item(id, title, more = {}) {
  return { id, title, tags: [], hashtags: [], cats: ['城市'], topics: [], summary: '', search_fields: { body: title }, note: `Web/${id}.md`,
    notes_path: `_archive/xiaohongshu/${id}/notes.json`, cover: '', attachment: 'none', starred: false, problems: [], ts: '2026-10-01T00:00:00Z', date: '2026-10-01', ...more };
}
function catalogData(items, more = {}) {
  return { built_at: '2026-10-08T05:09:12+10:00', pinyin_chars: {}, aliases: [], cats_order: ['城市', '吃的'], cats: [], topics: [], state_registry: {}, items, ...more };
}
// 手动控制的 Promise（插件方法挂起 / 失败）
function deferred() { let resolve, reject; const p = new Promise((a, b) => { resolve = a; reject = b; }); return { p, resolve, reject }; }

async function openCatalog({ items = [], data = null, plugin = null, files = {}, isMobile = false, mode = 'reading', frontmatter = {}, keepState = false, made = null, dom = null, params = {}, starred = false } = {}) {
  if (!keepState) delete globalThis.__lbState;
  delete globalThis.__lbListeners; delete globalThis.__lbNotices;
  // 新的假库 mtime 从同一处起算：别让上一个库留在插件对象上的解析缓存（版本字符串可能撞上）被当成这个库的
  if (plugin && !made) plugin.catalogCache = null;
  made = made || makeApp({ files: { [DATA]: JSON.stringify(data || catalogData(items)), '_archive/sync-status.json': '{}', ...files }, plugin, isMobile, frontmatter });
  dom = dom || makeDom();
  const A = dataviewBlock({ dom, app: made.app, code: code({ starred }), mode, params });
  await A.run();
  const $ = s => A.section.querySelector(s), $$ = s => A.section.querySelectorAll(s);
  const cards = () => $$('.lbc-card');
  return {
    A, dom, ...made, $, $$, cards,
    ids: () => cards().map(c => c._lbItem.id),
    titles: () => cards().map(c => c.querySelector('.lbc-ctitle').textContent),
    card: id => cards().find(c => c._lbItem.id === id),
    counts: () => ({ ...(globalThis.__lbPerf[starred ? 'starred' : 'catalog'].counts || {}) }),
    search: () => $('.lbc-search'),
    type(text) { const s = $('.lbc-search'); s.value = text; s.fire('input', {}); },
    enter(text) { const s = $('.lbc-search'); if (text != null) s.value = text; s.fire('keydown', { key: 'Enter', isComposing: false, keyCode: 13, preventDefault() {} }); },
    cat: label => $$('.lbc-cat').find(b => b.textContent === label),
    menuItems: () => dom.document.body.querySelectorAll('.lbc-menu-item'),
    pick: label => dom.document.body.querySelectorAll('.lbc-menu-item').find(b => b.textContent === label || b.textContent === '✓ ' + label),
  };
}
const ev = (more = {}) => ({ preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, clientX: 0, clientY: 0, ...more });

module.exports = { DATA, tick, code, item, catalogData, deferred, openCatalog, ev, asset };

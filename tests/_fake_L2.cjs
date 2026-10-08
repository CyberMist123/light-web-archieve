// 问收藏页（chat-view.js）的 node 测试夹具（批次 D · L2 自己的；_fakedom.cjs 冻结，不往里加）。
//   const C = await openChat({ turns, plugin: {...覆盖}, files, folder, params, active });
//   C.q / C.qa（在本页所在的 section 里找：页面挂在 dv.container 的兄弟 host 上）、C.ask('问题')、C.md（极简渲染器的计数）
// 假插件：renderMarkdownScoped = tests/_mini_md.cjs（记渲染 / dispose 次数）；answerArchive 默认马上答，C.hold() 后改成挂起、C.reply(r) 放行。
'use strict';
const { asset, makeDom, makeVault, makeWorkspace, dataviewBlock } = require('./_fakedom.cjs');
const { makeMiniMd } = require('./_mini_md.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const CODE = asset('lb-page-lib.js') + '\n' + asset('catalog-search.js') + '\n' + asset('chat-view.js');
const DATA = '_archive/catalog-data.json';
const SESSION = '_archive/chat-session.json';
const ARCHIVE = '_archive/chat-archive.json';
const INDEX = '_archive/chat-history/index.json';

const src = (id, n, extra = {}) => ({ id, citation: n, title: '主要' + id, note: `Web/${id}.md`, tier: 'primary', agent_md: `/fake-vault/_archive/xiaohongshu/${id}/derived/agent.md`,
  excerpts: [{ field: 'comments', text: id + ' 的命中原文', comment_labels: ['c1'] }], ...extra });
const rel = (id, n, extra = {}) => ({ id, rank: n, title: '相关' + id, note: `Web/${id}.md`, tier: 'related', excerpt: id + ' 摘录', ...extra });

function makePlugin(over = {}) {
  const md = makeMiniMd();
  const calls = { asks: [], opened: [], stops: [], lightbox: [], setup: [], warm: 0 };
  let holding = false, pending = [];
  const plugin = {
    settings: { models: [] },
    renderMarkdownScoped: (m, el) => md.render(m, el),
    archiveSourceState: () => ({ reader: false, compare: false }),
    async openArchiveSource(note) { calls.opened.push(note); },
    stopArchiveAnswer(tag) { calls.stops.push(tag); return 1; },
    openSetupPage(tab) { calls.setup.push(tab); },
    warmAnswerWorker() { calls.warm++; return true; },
    reply: req => ({ status: 'ok', markdown: '答：' + req.question + ' [来源1]', sources: [src('a', 1), src('b', 2)], related: [rel('c', 3), rel('d', 4)] }),
    answerArchive(req) {
      calls.asks.push(req);
      if (holding) return new Promise((res, rej) => pending.push({ req, res, rej }));
      try { const r = plugin.reply(req); return r instanceof Error ? Promise.reject(r) : Promise.resolve(r); } catch (e) { return Promise.reject(e); }
    },
    ...over,
  };
  return { plugin, md, calls,
    hold() { holding = true; },
    release() { holding = false; },
    pending: () => pending,
    // 放行最早挂起的那一问（r 是结果，或 Error 走失败）
    reply(r) { const p = pending.shift(); if (!p) throw new Error('没有挂起的提问'); if (r instanceof Error) p.rej(r); else p.res(r); return p.req; },
  };
}

async function openChat({ turns = [], session = null, plugin = null, files = {}, folder = '', params = {}, active = true, app = null, dom = null, V = null, noPlugin = false, isMobile = false, run = true } = {}) {
  const P = plugin || makePlugin();
  const pre = folder ? folder + '/' : '';
  if (!V) V = makeVault({ [pre + DATA]: JSON.stringify({ built_at: '2026-10-08T10:00:00+10:00', items: [] }),
    [pre + SESSION]: JSON.stringify(session || { turns }), [pre + ARCHIVE]: '{"entries":[]}', ...files });
  if (!app) app = { vault: V.vault, workspace: makeWorkspace(), isMobile, plugins: { plugins: noPlugin ? {} : { 'link-brain-actions': P.plugin }, enablePlugin: async () => {}, disablePlugin: async () => {} }, metadataCache: { getCache: () => null, getFileCache: () => null } };
  if (!dom) { delete globalThis.__lbState; delete globalThis.__lbListeners; delete globalThis.__lbUndoNotice; dom = makeDom(); }
  const clip = [];
  const A = dataviewBlock({ dom, app, code: CODE, folder, active, params: { navigator: { clipboard: { writeText: async t => { clip.push(t); } } }, ...params } });
  if (run) { await A.run(); await tick(5); }
  const C = {
    A, V, app, dom, P, plugin: P.plugin, md: P.md, calls: P.calls, clip, SESSION: pre + SESSION, ARCHIVE: pre + ARCHIVE, INDEX: pre + INDEX,
    q: s => A.section.querySelector(s),
    qa: s => A.section.querySelectorAll(s),
    get host() { return A.section.querySelector('.lb-page-host'); },
    get body() { return A.section.querySelector('.lbchat-body'); },
    get search() { return A.section.querySelector('.lbchat-search'); },
    async ask(text, wait = 20) { C.search.value = text; await A.section.querySelector('.lbchat-composer').onsubmit({ preventDefault() {} }); await tick(wait); },
    saved: () => JSON.parse(V.get(pre + SESSION)),
    answers: () => A.section.querySelectorAll('.lbchat-answer:not(.lbchat-live)'),
    rowOf: (title, scope = A.section) => scope.querySelectorAll('.lbchat-srcrow').filter(r => r.querySelector('a').textContent.includes(title)).pop(),
  };
  return C;
}

module.exports = { tick, CODE, DATA, SESSION, ARCHIVE, INDEX, src, rel, makePlugin, openChat };

// 1016：设置页「模型与提供商 → 用量与余额」（usage-ui.js）+ 问题面板 key 失效那条的「控制台」「充值」跳转。
// 假 DOM + 假 runPy（不起真进程，CONVENTIONS §7.5）；网址只认后端给的 https。
'use strict';
const assert = require('node:assert/strict');
const path = require('path');
const { ROOT, makeDom } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const DIR = 'obsidian-plugins/link-brain-actions';
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const opened = [];
global.window = { open: url => opened.push(url) };

const LINKS = {
  deepseek: { name: 'DeepSeek', console: 'https://platform.deepseek.com/', recharge: 'https://platform.deepseek.com/top_up', usage: 'https://platform.deepseek.com/usage' },
  aliyun: { name: '通义千问', console: 'https://bailian.console.aliyun.com/cn-beijing/', recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge',
    usage: 'https://bailian.console.aliyun.com/cn-beijing/costing-balance/usage-statistics' },
};
const feat = (o) => ({ calls: 1, failed: 0, items: 0, in: 0, out: 0, sec: 0, cost: 0, unpriced: 0, ...o });
const SUMMARY = {
  features: { vision: '识图', summary: '概要', ask: '问收藏', embed: '向量（embedding）' },
  as_of: '2026-10-03',
  windows: {
    today: { total: feat({ calls: 9, in: 1200, out: 300, cost: 0.0123, free: 6 }), features: { ask: feat({ calls: 3, in: 1200, out: 300, cost: 0.0123 }) },
      providers: { deepseek: feat({ calls: 3, in: 1200, out: 300, cost: 0.0123 }), google: feat({ calls: 4, free: 4 }), cli: feat({ calls: 2, free: 2 }) },
      models: { 'deepseek|deepseek-flash': feat({ provider: 'deepseek', model: 'deepseek-flash', calls: 3, cost: 0.0123 }),
        'google|gemini-3.5-flash': feat({ provider: 'google', model: 'gemini-3.5-flash', calls: 4, free: 4 }), 'cli|': feat({ provider: 'cli', model: '', calls: 2, free: 2 }) },
      unpriced_models: [{ provider: 'google', model: 'gemini-embedding-2', calls: 2 }] },
    '7d': { total: feat({ calls: 9, cost: 1.5 }), features: { vision: feat({ calls: 5, failed: 2, items: 2, in: 20000, out: 900, cost: 1.4 }),
      ask: feat({ calls: 3, cost: 0.1 }), embed: feat({ calls: 1, unpriced: 1 }) }, providers: {} },
    '30d': { total: feat({ calls: 0 }), features: {}, providers: {} },
  },
  month: { deepseek: feat({ calls: 3, cost: 0.0123 }), aliyun: feat({ calls: 6, cost: 1.4, unpriced: 1 }) },
  recent: [{ ts: new Date().toISOString(), f: 'ask', p: 'deepseek', m: 'deepseek-flash', in: 400, out: 100, ok: true, cost: 0.0041, status: 'paid' },
    { ts: new Date().toISOString(), f: 'summary', p: 'google', m: 'gemini-3.5-flash', in: 900, out: 80, ok: true, item: 'n1', cost: 0, status: 'free' }],
  recent_limit: 200,
};

async function settingsPane() {
  const dom = makeDom(), D = dom.document;
  const OBS = makeObsidian(D);
  const calls = [];
  const plugin = {
    async runPy(args) {
      calls.push(args.join(' '));
      if (args.includes('--balance')) return { code: 0, json: { ok: true, balances: {
        deepseek: { ok: true, available: true, balances: [{ currency: 'CNY', total: '105.38', granted: '4.40', topped_up: '100.97' }] },
        aliyun: { ok: false, unsupported: true, message: '百炼没有用 API key 能查的余额接口' } },
        keys: { aliyun: { code: 'NEEDS_HUMAN.AUTH_FAILED', caps: ['visionAI', 'summaryAI'] } } } };
      return { code: 0, json: { ok: true, summary: SUMMARY, links: LINKS, keys: {} } };
    },
    failBox(c, what, e) { c.createEl('p', { cls: 'lb-fail', text: what + '：' + e.message }); },
  };
  // 和 main.js 设置页同样的两块积木（card / link）
  const tab = {
    card(parent, title, section, { desc = '' } = {}) {
      const card = parent.createDiv({ cls: 'lb-card', attr: { 'data-section': section } });
      const head = card.createDiv({ cls: 'lb-card-head' }); head.createDiv({ cls: 'lb-card-title', text: title });
      const body = card.createDiv({ cls: 'lb-card-body' }); if (desc) body.createEl('p', { cls: 'lb-card-desc', text: desc });
      body.head = head; return body;
    },
    link(row, text, onClick) { let el; row.addButton(b => { b.setButtonText(text).onClick(onClick); el = b.buttonEl; el.addClass('lb-link'); }); return el; },
  };
  const ui = require(path.join(ROOT, DIR, 'usage-ui.js'))(OBS, plugin);
  const host = D.body.createDiv();
  const stop = ui.render(host, tab);
  await tick(); await tick(); await tick();

  assert.deepEqual(calls, ['-m link_brain usage', '-m link_brain usage --balance'], '先读本地账本、再联网查余额');
  const prov = id => host.querySelectorAll('.lb-usage-provider').find(r => r.getAttribute('data-provider') === id);
  const ds = prov('deepseek'), qw = prov('aliyun');
  assert.ok(ds && qw, 'DeepSeek、千问各一行');
  assert.ok(ds.textContent.includes('余额 ¥105.38（充值 100.97 + 赠送 4.40）'), ds.textContent);
  assert.ok(ds.textContent.includes('本月 ¥0.0123 · 3 次调用'));
  assert.ok(qw.textContent.includes('这家查不了'), '千问不编余额');
  assert.ok(qw.textContent.includes('key 用不了（可能欠费、过期或没开通）：影响识图、概要'), qw.textContent);   // 1016 她：别吓人
  assert.ok(qw.textContent.includes('1 次的模型不在价格表里'));
  const btn = (row, t) => row.querySelectorAll('button').find(b => b.textContent === t);
  assert.deepEqual(ds.querySelectorAll('button').map(b => b.textContent), ['控制台', '充值', '看用量']);
  assert.equal(host.querySelectorAll('button').filter(b => b.classList.contains('mod-cta')).length, 0, '跳转都是次要按钮，不抢主按钮');
  btn(qw, '充值').click(); btn(ds, '看用量').click();
  assert.deepEqual(opened.splice(0), [LINKS.aliyun.recharge, LINKS.deepseek.usage], '点了打开后端给的网址');

  // 明细表：默认今天；切 7 天
  const cells = () => host.querySelectorAll('.lb-usage-grid tr').map(tr => tr.querySelectorAll('th,td').map(td => td.textContent));
  assert.deepEqual(cells()[1], ['问收藏', '—', '3', '1200', '300', '¥0.0123']);
  host.querySelectorAll('.lb-usage-win').find(b => b.getAttribute('data-win') === '7d').onclick();
  const week = cells();
  assert.deepEqual(week[1], ['识图', '2', '5（失败 2）', '2.0 万', '900', '¥1.40']);
  assert.deepEqual(week.find(r => r[0] === '向量（embedding）').slice(-1), ['未计价'], '价格表里没有的不编金额：写「未计价」');
  assert.equal(week[week.length - 1][0], '合计');
  // 1026：按服务商 / 按 API 或模型 切换（今天那一段）；免费的写「免费 / 未计费」不算进 ¥；查不到价的点名「未计价」；每次调用一行可追溯
  host.querySelectorAll('.lb-usage-win').find(b => b.getAttribute('data-win') === 'today').onclick();
  assert.deepEqual(host.querySelectorAll('.lb-usage-dim').map(b => b.textContent), ['按服务商', '按 API 或模型', '按功能']);
  host.querySelectorAll('.lb-usage-dim').find(b => b.getAttribute('data-dim') === 'providers').onclick();
  assert.equal(host.querySelector('.lb-usage-grid').getAttribute('data-dim'), 'providers');
  let rows = cells();
  assert.deepEqual(rows[0][0], '服务商');
  assert.deepEqual(rows.find(r => r[0] === 'DeepSeek').slice(-1), ['¥0.0123']);
  assert.deepEqual(rows.find(r => r[0] === 'Gemini').slice(-1), ['免费 / 未计费'], 'Gemini 免费 key：不算进 ¥');
  assert.deepEqual(rows.find(r => r[0] === '本机命令行').slice(-1), ['免费 / 未计费'], '本机命令行（OpenCode 等）：不算进 ¥');
  assert.deepEqual(rows.at(-1).slice(-1), ['¥0.0123 · 免费 6 次'], '合计只算真花的钱，免费的单说');
  host.querySelectorAll('.lb-usage-dim').find(b => b.getAttribute('data-dim') === 'models').onclick();
  rows = cells();
  assert.deepEqual(rows[0][0], 'API / 模型');
  assert.ok(rows.some(r => r[0] === 'deepseek-flash · DeepSeek' && r.at(-1) === '¥0.0123'), JSON.stringify(rows));
  assert.ok(rows.some(r => r[0] === 'gemini-3.5-flash · Gemini' && r.at(-1) === '免费 / 未计费'));
  assert.ok(rows.some(r => r[0] === '本机命令行（没记下是哪个）' && r.at(-1) === '免费 / 未计费'), '命令行空模型名也有名字');
  assert.match(host.querySelector('.lb-usage-gaps').textContent, /未计价（价格表里查不到.*gemini-embedding-2 · Gemini：2 次/, '未计价的模型点名');
  const callsFold = host.querySelector('details[data-section="usage-calls"]');
  callsFold.open = true; callsFold.fire('toggle');
  const callRows = callsFold.querySelectorAll('tr').map(tr => tr.querySelectorAll('th,td').map(td => td.textContent));
  assert.deepEqual(callRows[0], ['时间', '功能', 'API / 模型', 'token（入 / 出）', '金额', '哪一篇']);
  assert.ok(callRows.some(r => r[1] === '问收藏' && r[2] === 'deepseek-flash · DeepSeek' && r[4] === '¥0.0041'), JSON.stringify(callRows));
  assert.ok(callRows.some(r => r[4] === '免费 / 未计费' && r[5] === 'n1'), '免费的那次也列着、带哪一篇');
  host.querySelectorAll('.lb-usage-dim').find(b => b.getAttribute('data-dim') === 'features').onclick();
  host.querySelectorAll('.lb-usage-win').find(b => b.getAttribute('data-win') === '30d').onclick();
  assert.ok(host.textContent.includes('这段时间没调用过 AI。'));
  assert.ok(host.textContent.includes('以控制台账单为准'), '说清是估算');
  stop();

  // 读不出来：卡片里一句原因 + 重试（不让整栏空掉）
  const bad = require(path.join(ROOT, DIR, 'usage-ui.js'))(OBS, { ...plugin, async runPy() { throw new Error('找不到 Python'); } });
  const host2 = D.body.createDiv(); bad.render(host2, tab); await tick(); await tick();
  assert.ok(host2.querySelector('.lb-fail').textContent.includes('找不到 Python'));
  console.log('PASS usage settings: per-provider balance / month cost / key warning + 控制台 · 充值 · 看用量 open backend URLs; table by window × 按服务商 / 按 API 或模型 / 按功能, free = 免费 / 未计费 (not in ¥), unpriced = 未计价 + named, per-call rows; failure says why');
}

function problemsLinks() {
  const ui = require(path.join(ROOT, DIR, 'problems-ui.js'))({ Modal: class {}, Notice: class {} }, { manifest: {}, app: {} });
  const row = { code: 'NEEDS_HUMAN.AUTH_FAILED', group: 'needs_you', step: 'ai.vision',
    links: { provider: '通义千问', console: LINKS.aliyun.console, recharge: LINKS.aliyun.recharge } };
  const fixes = ui._internals.fixesFor(row);
  assert.deepEqual(fixes.map(f => f[0]), ['打开设置', '通义千问控制台', '充值']);
  assert.ok(fixes.slice(1).every(f => f[2] === 'lb-problem-ext'), '跳转不是主按钮样式');
  fixes[2][1]();
  assert.deepEqual(opened.splice(0), [LINKS.aliyun.recharge]);
  assert.deepEqual(ui._internals.fixesFor({ ...row, links: { console: 'javascript:alert(1)' } }).map(f => f[0]), ['打开设置'], '只认 https');
  assert.deepEqual(ui._internals.fixesFor({ ...row, code: 'TRANSIENT.NETWORK', group: 'auto' }), []);
  console.log('PASS problems panel: key 失效 / 欠费 row gets <provider>控制台 + 充值 (https only), opens in browser');
}

(async () => { await settingsPane(); problemsLinks(); })().catch(e => { console.error(e); process.exit(1); });

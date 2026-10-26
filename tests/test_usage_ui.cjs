// 1016 → 1027：设置页④「AI 控制台」（usage-ui.js renderConsole）+ 问题面板 key 失效那条的「控制台」「充值」跳转。
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
    '7d': { total: feat({ calls: 9, cost: 1.5, unpriced: 1 }), features: { vision: feat({ calls: 5, failed: 2, items: 2, in: 20000, out: 900, cost: 1.4 }),
      ask: feat({ calls: 3, cost: 0.1 }), embed: feat({ calls: 1, unpriced: 1 }) },
      providers: { deepseek: feat({ calls: 3, cost: 0.1 }), aliyun: feat({ calls: 5, cost: 1.4 }), google: feat({ calls: 1, unpriced: 1 }) } },
    '30d': { total: feat({ calls: 0 }), features: {}, providers: {} },
  },
  month: { deepseek: feat({ calls: 3, cost: 0.0123 }), aliyun: feat({ calls: 6, cost: 1.4, unpriced: 1 }) },
  recent: [{ ts: new Date().toISOString(), f: 'ask', p: 'deepseek', m: 'deepseek-flash', in: 400, out: 100, ok: true, cost: 0.0041, status: 'paid' },
    { ts: new Date().toISOString(), f: 'summary', p: 'google', m: 'gemini-3.5-flash', in: 900, out: 80, ok: true, item: 'n1', cost: 0, status: 'free' }],
  recent_limit: 200,
};

// 1027：设置页④「AI 控制台」（usage-ui.js renderConsole）——一行今天 / 本月 / 每天最多花；点开左边折线（固定高度，只画真花了钱的）、右边三种看法 + 小表
const DATES = Array.from({ length: 30 }, (_, i) => { const d = new Date(2026, 8, 28 + i); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; });
SUMMARY.series = { dates: DATES,
  providers: { deepseek: DATES.map((_, i) => (i === 29 ? 0.0123 : i === 28 ? null : i === 26 ? 0.5 : 0)), aliyun: DATES.map((_, i) => (i === 27 ? 1.4 : 0)) },
  models: { 'deepseek|deepseek-flash': DATES.map((_, i) => (i === 29 ? 0.0123 : 0)) },
  features: { ask: DATES.map((_, i) => (i === 29 ? 0.0123 : 0)), vision: DATES.map((_, i) => (i === 27 ? 1.4 : 0)), a: DATES.map(() => 0.01), b: DATES.map(() => 0.02), c: DATES.map(() => 0.03) } };

async function settingsPane() {
  const dom = makeDom(), D = dom.document;
  const OBS = makeObsidian(D);
  const calls = [];
  let saveFail = false;
  const plugin = {
    settings: { budget: {} },
    async saveSettings() { if (saveFail) throw new Error('磁盘满了'); },
    notify(m) { (plugin.notes ||= []).push(m); },
    async runPy(args) {
      calls.push(args.join(' '));
      return { code: 0, json: { ok: true, summary: SUMMARY, links: LINKS, keys: {}, budget: { daily_yuan: 3, spent_today: 0.83, over: false } } };
    },
    failBox(c, what, e) { c.createEl('p', { cls: 'lb-fail', text: what + '：' + e.message }); },
  };
  const tab = { help(row, text) { const q = row.nameEl.createSpan({ cls: 'lb-help', text: 'ⓘ' }); q.setAttribute('aria-label', text); return q; } };
  const ui = require(path.join(ROOT, DIR, 'usage-ui.js'))(OBS, plugin);
  const host = D.body.createDiv();
  const view = {};
  const c = ui.renderConsole(host, tab, { view });
  await tick(); await tick(); await tick();
  assert.deepEqual(calls, ['-m link_brain usage'], '只读本地账本（余额在「更多 → 服务商与余额」才联网查）');
  const vals = host.querySelectorAll('.lb-console-v').map(v => v.textContent);
  assert.equal(vals[0], '¥0.83', '今天（北京时间，和上限同一天）');
  assert.equal(vals[1], '¥1.41', '本月 = 各家本月合计');
  assert.match(host.textContent, /另有 1 次未计价/);
  const input = host.querySelector('input.lb-spend-input');
  assert.equal(input.value, '3', '没存过：显示后端默认');
  assert.match(host.querySelector('.lb-console-cap .lb-help').getAttribute('aria-label'), /后台的付费处理.*手动问收藏.*不受限/, 'ⓘ：只管后台付费处理');
  input.value = '5'; input.fire('change'); await tick();
  assert.equal(plugin.settings.budget.dailyYuan, 5, '改了就存');
  saveFail = true; input.value = '9'; input.fire('change'); await tick(); saveFail = false;
  assert.equal(plugin.settings.budget.dailyYuan, 5, '存失败改回'); assert.equal(input.value, '5');
  // 默认收着：点开是左右两栏
  const body = host.querySelector('.lb-console-body');
  assert.equal(body.hidden, true, '默认收起');
  host.querySelector('.lb-console-toggle').onclick(); await tick();
  assert.equal(body.hidden, false); assert.equal(view.open, true, '展开记在这次会话里');
  assert.ok(host.querySelector('.lb-console-grid .lb-console-left .lb-chart') && host.querySelector('.lb-console-grid .lb-console-right .lb-usage-grid'), '两栏：左图右表');
  assert.equal(host.querySelector('.lb-chart').style.height, '190px', '折线固定 190px 高');
  // 折线：近 7 天按服务商——DeepSeek、百炼两条；Gemini（全是免费的）不画；那天只有免费 / 未计价 = 断开，不画成 ¥0
  const lines = () => host.querySelectorAll('.lb-chart [data-key]');
  assert.deepEqual(lines().map(p => p.getAttribute('data-key')), ['aliyun', 'deepseek']);
  const ds = lines().find(p => p.getAttribute('data-key') === 'deepseek').getAttribute('d');
  assert.equal((ds.match(/M/g) || []).length, 2, 'null 那天断开成两段：' + ds);
  assert.deepEqual(host.querySelectorAll('.lb-chart-key').map(k => k.textContent), ['阿里云百炼', 'DeepSeek · 虚线'], '图例：名字 + 线型（黑白，不靠颜色）');
  // 表：服务商、近 7 天；免费 / 未计费、未计价各一行
  const cells = () => host.querySelectorAll('.lb-usage-grid tr').map(tr => tr.querySelectorAll('th,td').map(td => td.textContent));
  let rows = cells();
  assert.deepEqual(rows[0], ['服务商', '近 7 天']);
  assert.deepEqual(rows.slice(-3), [['已计价合计', '¥1.50'], ['免费 / 未计费', '—'], ['未计价', '1 次']]);
  assert.deepEqual(rows.find(r => r[0] === '向量（embedding）') || null, null);
  // 换看法：功能（多于 4 条：前三条 + 「其他 N 项」）
  host.querySelectorAll('.lb-usage-dim').find(b => b.getAttribute('data-dim') === 'features').onclick();
  rows = cells();
  assert.deepEqual(rows[0], ['功能', '近 7 天']);
  assert.ok(rows.some(r => r[0] === '识图' && r[1] === '¥1.40'));
  assert.ok(rows.some(r => r[0] === '向量（embedding）' && r[1] === '未计价'), '价格表里没有的写「未计价」，不编金额');
  assert.equal(lines().length, 4, '最多 4 条线');
  assert.match(host.querySelectorAll('.lb-chart-key').at(-1).textContent, /^其他 2 项/);
  // 时段：近 30 天——这段没调用过
  const period = host.querySelector('select.lb-console-period');
  period.value = '30d'; period.onchange(); await tick();
  assert.ok(host.textContent.includes('这段时间没调用过 AI。'));
  assert.ok(host.textContent.includes('以服务商账单为准'), '说清是估算');
  // 每次调用一行（可追溯到哪一篇）
  period.value = '7d'; period.onchange();
  const callsFold = host.querySelector('details[data-section="usage-calls"]');
  callsFold.open = true; callsFold.fire('toggle');
  const callRows = callsFold.querySelectorAll('tr').map(tr => tr.querySelectorAll('th,td').map(td => td.textContent));
  assert.deepEqual(callRows[0], ['时间', '功能', 'API / 模型', 'token（入 / 出）', '金额', '哪一篇']);
  assert.ok(callRows.some(r => r[1] === '问收藏' && r[2] === 'deepseek-flash · DeepSeek' && r[4] === '¥0.0041'), JSON.stringify(callRows));
  assert.ok(callRows.some(r => r[4] === '免费 / 未计费' && r[5] === 'n1'), '免费的那次也列着、带哪一篇');
  c.stop();

  // 纯函数：没花过钱的不画、只有免费的那天是 null、全是 0 的不进折线
  const m = ui.chartModel({ summary: { series: { dates: ['a', 'b', 'c'], providers: { x: [0, 0, 0], y: [null, 0.2, 0] } } } }, 'providers', 3);
  assert.deepEqual(m.lines.map(l => l.key), ['y']); assert.equal(m.lines[0].vals[0], null); assert.ok(m.max >= 0.2);
  assert.deepEqual(ui.chartModel({ summary: {} }, 'models', 7).lines, [], '老后端没有 series：不画、不报错');
  // 没有花钱的调用：图里一句，不画 ¥0 的线
  const host3 = D.body.createDiv();
  const empty = require(path.join(ROOT, DIR, 'usage-ui.js'))(OBS, { ...plugin, async runPy() { return { json: { ok: true, summary: { ...SUMMARY, series: { dates: DATES, providers: {} } }, budget: {} } }; } });
  empty.renderConsole(host3, tab, { view: { open: true } }); await tick(); await tick();
  assert.match(host3.querySelector('.lb-chart-empty').textContent, /免费 \/ 未计价的不画成 ¥0/);
  // 读不出来：一句原因 + 重试
  const bad = require(path.join(ROOT, DIR, 'usage-ui.js'))(OBS, { ...plugin, async runPy() { throw new Error('找不到 Python'); } });
  const host2 = D.body.createDiv(); bad.renderConsole(host2, tab, {}); await tick(); await tick();
  assert.ok(host2.querySelector('.lb-fail').textContent.includes('找不到 Python'));
  console.log('PASS AI console: today / month / one daily cap (saves, reverts on failure); expands to chart (fixed 190px, paid only — free / unpriced days break the line, free-only keys not drawn, ≤4 lines + 其他) + table by 服务商 / 模型 / 功能 × 7 / 30 days with 免费 / 未计费 and 未计价 rows; per-call rows; failure says why');
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

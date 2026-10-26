// usage-ui.js — 1016 设置页「模型与提供商 → 用量与余额」：每家提供商的余额 / 本月花费 / 密钥状态 + 「控制台」「充值」「看用量」跳转，
// 下面一张明细表（今天 / 7 天 / 30 天 × 按服务商 / 按 API 或模型 / 按功能，1026）+ 未计价的模型点名 + 每次调用一行（可追溯到哪一篇）。数据只来自后端 `link_brain usage [--balance]`（CONVENTIONS §1 最后一行 JSON），
// 金额是后端按 pricing.json 现价折算的估算；跳转网址也由后端给（pricing.json providers，10-16 核对过）。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Setting } = obsidian;
  const WINDOWS = [['today', '今天'], ['7d', '近 7 天'], ['30d', '近 30 天']];
  // 1026（录屏 25:09「没有按照 API 来换的」）：三种看法切换——按服务商 / 按 API 或模型 / 按功能；都是后端 usage.summary 按同一套价格规则算的
  const DIMS = [['providers', '按服务商'], ['models', '按 API 或模型'], ['features', '按功能']];
  const PROV_NAME = { deepseek: 'DeepSeek', aliyun: '阿里云百炼', google: 'Gemini', openai: 'OpenAI', cli: '本机命令行', other: '其他' };
  const ORDER = ['deepseek', 'aliyun'];
  const CAP_TEXT = { textAI: '问收藏', summaryAI: '概要', visionAI: '识图', 'visionAI.refine': '精细识图', embedAI: '向量' };
  // 1016 她：别吓人——说「用不了」和可能的原因，不说「被拒」
  const KEY_TEXT = { AUTH_FAILED: 'key 用不了（可能欠费、过期或没开通）', QUOTA_EXCEEDED: '额度用完了' };

  const yuan = v => (v == null || !Number.isFinite(+v) ? '—' : '¥' + (+v < 0.1 && +v > 0 ? (+v).toFixed(4).replace(/0+$/, '') : (+v).toFixed(2)));
  const num = v => { const n = +v || 0; return n >= 10000 ? (n / 10000).toFixed(n >= 1e6 ? 0 : 1) + ' 万' : String(n); };
  const openUrl = url => {
    if (!/^https:\/\//.test(url || '')) return;
    try { require('electron').shell.openExternal(url); return; } catch {}
    try { window.open(url); } catch (e) { console.error('[lb] 网页没打开', e); }
  };

  function balanceText(b) {
    if (!b) return '';
    if (b.unsupported) return '余额：这家查不了（' + (b.message || '去控制台看') + '）';
    if (!b.ok) return '余额没查到：' + (b.message || '原因不明');
    const parts = (b.balances || []).map(x => `${x.currency === 'USD' ? '$' : '¥'}${x.total}` +
      (x.granted && +x.granted > 0 ? `（充值 ${x.topped_up} + 赠送 ${x.granted}）` : ''));
    return '余额 ' + (parts.join(' · ') || '0') + (b.available === false ? ' · 不够调用了' : '');
  }

  // opts.tableOnly（1018 AI 页重排）：只画「各功能用了多少」那张表——余额 / 控制台已经在 AI 页的「钥匙串」里；opts.data = AI 页已读回的数据，不再读一遍
  // 一格金额：只按真算出来的钱写 ¥；免费的写「免费 / 未计费」（本机命令行、Gemini 免费 key 池，她 1023 拍板：不算进 ¥）；
  // 价格表里查不到的写「未计价」，不编数、不当 0
  function moneyText(v) {
    v = v || {};
    const calls = +v.calls || 0, free = +v.free || 0, unpriced = +v.unpriced || 0, paid = Math.max(0, calls - free - unpriced);
    if (calls && free === calls) return '免费 / 未计费';
    if (calls && unpriced === calls) return '未计价';
    if (calls && free + unpriced === calls) return [`免费 ${free} 次`, `未计价 ${unpriced} 次`].join(' · ');
    const parts = [paid || !calls ? yuan(v.cost) : ''];
    if (free) parts.push(`免费 ${free} 次`);
    if (unpriced) parts.push(`未计价 ${unpriced} 次`);
    return parts.filter(Boolean).join(' · ');
  }
  function rowName(dim, key, v, names) {
    if (dim === 'features') return names[key] || key;
    if (dim === 'providers') return PROV_NAME[key] || key;
    const prov = PROV_NAME[v.provider] || v.provider || '';
    const model = v.model || (v.provider === 'cli' ? '本机命令行（没记下是哪个）' : '（没记模型名）');
    return prov && model !== prov && !model.startsWith('本机命令行') ? `${model} · ${prov}` : model;
  }

  function render(host, tab, opts = {}) {
    let alive = true, data = opts.data || null, win = 'today', dim = 'features';
    const tableOnly = !!opts.tableOnly;
    const top = tableOnly ? null : tab.card(host, '余额与控制台', 'usage-providers', { desc: '每家一行：余额、这个月花了多少，点按钮直接打开它的网页（要在网页里登录）。' });
    const topBody = top ? top.createDiv({ cls: 'lb-usage-providers' }) : host.createDiv({ cls: 'lb-usage-providers is-hidden' });
    // tableOnly（设置页「模型与费用 → 花了多少」）不再套一层卡片：上面一行切换，下面表格
    let feat;
    if (tableOnly) { feat = host.createDiv({ cls: 'lb-usage-block', attr: { 'data-section': 'usage-features' } }); feat.head = feat.createDiv({ cls: 'lb-usage-head' }); }
    else feat = tab.card(host, '花了多少', 'usage-features');
    const dimBar = feat.head.createDiv({ cls: 'lb-usage-dims', attr: { role: 'tablist', 'aria-label': '怎么看花费' } });
    const switcher = feat.head.createDiv({ cls: 'lb-usage-windows', attr: { role: 'tablist', 'aria-label': '时间段' } });
    const table = feat.createDiv({ cls: 'lb-usage-table' });
    const gaps = feat.createDiv({ cls: 'lb-usage-gaps' });
    const calls = feat.createEl('details', { cls: 'lb-row-fold lb-usage-calls', attr: { 'data-section': 'usage-calls' } });
    const callsSum = calls.createEl('summary');
    callsSum.createDiv({ cls: 'lb-rf-name', text: '每次调用' });
    const callsDesc = callsSum.createDiv({ cls: 'lb-rf-desc', text: '' });
    const callsBody = calls.createDiv({ cls: 'lb-rf-body' });
    calls.addEventListener?.('toggle', () => { if (calls.open && data) paintCalls(); });
    const foot = feat.createEl('p', { cls: 'lb-card-desc lb-usage-foot' });
    tab.link(new Setting(feat), '刷新', () => load(), '重新读一遍用量和余额');

    const tabs = (bar, list, cur, cls, attr, pick) => {
      bar.empty();
      for (const [id, label] of list) {
        const b = bar.createEl('button', { cls: cls + (id === cur ? ' is-active' : ''), text: label,
          attr: { type: 'button', role: 'tab', 'aria-selected': String(id === cur), [attr]: id } });
        b.onclick = () => pick(id);
      }
    };
    const paintSwitch = () => {
      tabs(dimBar, DIMS, dim, 'lb-usage-dim', 'data-dim', id => { dim = id; paintSwitch(); paintTable(); });
      tabs(switcher, WINDOWS, win, 'lb-usage-win', 'data-win', id => { win = id; paintSwitch(); paintTable(); if (calls.open) paintCalls(); });
    };

    function paintProviders() {
      topBody.empty();
      if (tableOnly) return;
      const links = data.links || {}, month = (data.summary || {}).month || {}, keys = data.keys || {}, bal = data.balances || {};
      const ids = [...ORDER.filter(k => links[k]), ...Object.keys(month).filter(k => !links[k] && k !== 'cli')];
      for (const id of ids) {
        const l = links[id] || {}, m = month[id], k = keys[id];
        const row = new Setting(topBody).setName(l.name || id);
        row.settingEl.addClass('lb-usage-provider'); row.settingEl.setAttribute?.('data-provider', id);
        const desc = row.descEl;
        if (bal[id] || data.balances) desc.createDiv({ cls: 'lb-usage-balance' + (bal[id] && !bal[id].ok && !bal[id].unsupported ? ' is-warn' : ''), text: balanceText(bal[id]) || '余额：正在查…' });
        desc.createDiv({ cls: 'lb-usage-month', text: m ? `本月 ${m.calls && m.free === m.calls ? '免费 / 未计费' : yuan(m.cost)} · ${m.calls} 次调用${m.unpriced ? `（${m.unpriced} 次的模型不在价格表里，没算钱）` : ''}` : '本月没用过' });
        if (k) {
          const sub = String(k.code || '').split('.').pop();
          desc.createDiv({ cls: 'lb-usage-key is-warn', text: `${KEY_TEXT[sub] || k.code}：影响${(k.caps || []).map(c => CAP_TEXT[c] || c).join('、')}；配了备用的会自动改用备用` });
        }
        for (const [label, key] of [['控制台', 'console'], ['充值', 'recharge'], ['看用量', 'usage']]) {
          if (!l[key]) continue;
          const el = tab.link(row, label, () => openUrl(l[key]), `在浏览器打开 ${l.name || id} 的${label}页`);
          el?.setAttribute?.('data-link', key);
        }
      }
      if (!ids.length) topBody.createEl('p', { cls: 'lb-card-desc', text: '还没用过要钱的 AI。' });
    }

    function paintTable() {
      table.empty();
      const sum = data.summary || {};
      const w = (sum.windows || {})[win] || { features: {}, total: {} };
      const names = sum.features || {};
      const t = table.createEl('table', { cls: 'lb-usage-grid', attr: { 'data-dim': dim } });
      const head = t.createEl('tr');
      const first = { features: '功能', providers: '服务商', models: 'API / 模型' }[dim];
      for (const h of [first, '篇数', '调用', '输入 token', '输出 token', '金额']) head.createEl('th', { text: h });
      const rows = Object.entries(w[dim] || {});
      if (dim !== 'features') rows.sort((x, y) => (+y[1].cost || 0) - (+x[1].cost || 0) || (+y[1].calls || 0) - (+x[1].calls || 0));
      for (const [k, v] of rows) {
        const tr = t.createEl('tr', { attr: { 'data-key': k, ...(dim === 'features' ? { 'data-feature': k } : {}) } });
        tr.createEl('td', { text: rowName(dim, k, v, names) });
        tr.createEl('td', { text: v.items ? String(v.items) : '—' });
        tr.createEl('td', { text: String(v.calls) + (v.failed ? `（失败 ${v.failed}）` : '') });
        tr.createEl('td', { text: v.sec && !v.in ? `${Math.round(v.sec / 60)} 分钟音频` : num(v.in) });
        tr.createEl('td', { text: num(v.out) });
        const m = tr.createEl('td', { cls: 'lb-usage-money', text: moneyText(v) });
        if (v.calls && v.free === v.calls) m.addClass?.('is-free');
        if (v.unpriced) m.addClass?.('is-unpriced');
      }
      if (!rows.length) t.createEl('tr').createEl('td', { text: '这段时间没调用过 AI。', attr: { colspan: '6' } });
      else {
        const tot = w.total || {}, tr = t.createEl('tr', { cls: 'lb-usage-total' });
        for (const v of ['合计', '', String(tot.calls || 0), num(tot.in), num(tot.out), moneyText(tot)]) tr.createEl('td', { text: v });
      }
      // 未计价的模型（价格表里查不到 → 没算进 ¥）：点名列出来，补价格在 ~/.link-brain/pricing.json
      gaps.empty();
      const un = w.unpriced_models || [];
      if (un.length) {
        gaps.createDiv({ cls: 'lb-usage-gap-title', text: '未计价（价格表里查不到，没算进上面的 ¥）' });
        const ul = gaps.createEl('ul');
        for (const u of un) ul.createEl('li', { text: `${rowName('models', '', u, names)}：${u.calls} 次` });
      }
      const recent = sum.recent || [];
      callsDesc.setText(recent.length ? `最近 ${recent.length} 次：几点、哪个功能、哪家哪个模型、多少 token、多少钱` : '还没有调用记录');
      foot.setText(`金额是人民币，按价格表（${sum.as_of || '—'} 核对）现价折算的估算，以控制台账单为准；DeepSeek 按调用时刻分高峰 / 空闲价。「免费 / 未计费」= 本机命令行（OpenCode、Codex 等）和 Gemini 免费 key，不算进 ¥；「未计价」= 价格表里查不到这个模型，没算钱也不当 0。「今天」从这台电脑的 0 点算；阿里云 / DeepSeek 的账单按北京时间分天、还要晚几个小时才出，对不上时看「近 7 天」。连上的 Claude / ChatGPT 搜收藏、问收藏花的也都记在这里。`);
    }

    // 每次调用一行（后端账本原样：时间 · 功能 · 服务商 · 模型 · token · 金额 · 哪一篇）——只读、只显示，不记 key 和内容
    function paintCalls() {
      callsBody.empty();
      const sum = data.summary || {}, names = sum.features || {};
      const days = { today: 1, '7d': 7, '30d': 30 }[win] || 30;
      const since = new Date(); since.setHours(0, 0, 0, 0); since.setDate(since.getDate() - (days - 1));
      const list = (sum.recent || []).filter(r => { const t = Date.parse(r.ts); return !Number.isFinite(t) || t >= since.getTime(); });
      if (!list.length) { callsBody.createDiv({ cls: 'setting-item-description', text: '这段时间没有调用记录。' }); return; }
      const t = callsBody.createEl('table', { cls: 'lb-usage-grid lb-usage-callgrid' });
      const head = t.createEl('tr');
      for (const h of ['时间', '功能', 'API / 模型', 'token（入 / 出）', '金额', '哪一篇']) head.createEl('th', { text: h });
      for (const r of list) {
        const tr = t.createEl('tr', { attr: { 'data-status': r.status || '' } });
        tr.createEl('td', { text: String(r.ts || '').replace('T', ' ').slice(5, 16) });
        tr.createEl('td', { text: (names[r.f] || r.f || '') + (r.ok === false ? '（失败）' : '') });
        tr.createEl('td', { text: rowName('models', '', { provider: r.p, model: r.m }, names) });
        tr.createEl('td', { text: r.sec ? `${r.sec} 秒音频` : `${num(r.in)} / ${num(r.out)}` });
        tr.createEl('td', { text: r.status === 'free' ? '免费 / 未计费' : r.status === 'unpriced' ? '未计价' : yuan(r.cost) });
        tr.createEl('td', { text: r.item ? String(r.item).slice(0, 18) : '—' });
      }
      if (sum.recent_limit && (sum.recent || []).length >= sum.recent_limit) callsBody.createDiv({ cls: 'setting-item-description', text: `只列最近 ${sum.recent_limit} 次；更早的在 _archive/usage/ 的账本里（一行一次调用）。` });
    }

    function paint() { if (!alive || !data) return; paintProviders(); paintSwitch(); paintTable(); }

    async function load() {
      topBody.empty(); table.empty(); foot.setText('');
      const wait = topBody.createEl('p', { cls: 'lb-card-desc lb-usage-wait', text: '正在读用量…' });
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'usage'], { label: '读用量', timeoutMs: 30000, fallback: '用量没读出来' });
        if (!alive) return;
        if (!r.json || r.json.ok === false) throw new Error((r.json && r.json.message) || '用量没读出来');
        data = r.json; paint();
      } catch (e) { if (alive) { wait.remove(); plugin.failBox?.(topBody, '用量', e, () => load()); } return; }
      // 余额要联网（DeepSeek 一次请求），后到后只换上面那块
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'usage', '--balance'], { label: '查余额', timeoutMs: 30000, fallback: '余额没查到' });
        if (!alive || !r.json || r.json.ok === false) return;
        data = { ...data, balances: r.json.balances || {}, keys: r.json.keys || data.keys };
        paintProviders();
      } catch (e) { if (alive) { data = { ...data, balances: { deepseek: { ok: false, message: e.message } } }; paintProviders(); } }
    }

    if (data) paint(); else load();
    return () => { alive = false; };
  }

  return { render, openUrl, balanceText, moneyText };
};

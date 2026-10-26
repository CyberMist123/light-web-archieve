// usage-ui.js — 设置页④「AI 控制台」（1027 设置页六组；接 1026 的三种看法和每次调用）。
//   一行：今天 ¥ · 本月 ¥ · 每天最多花 ¥[输入框]（budget.dailyYuan，只拦后台付费的补处理，她手动问收藏不拦）；
//   点开是左右两栏：左边一张折线（固定 190px 高，绝不撑出去；只画真花了钱的——免费 / 未计费、未计价的不画成 ¥0），
//   右边 服务商 / 模型 / 功能 切换 + 近 7 / 30 天 + 一张小表（含「免费 / 未计费」「未计价」两行）；下面「每次调用」一行一次可追溯到哪一篇。
// 数据只来自后端 `link_brain usage`（CONVENTIONS §1 最后一行 JSON）：summary.windows（表）· summary.series（折线，usage.series）·
//   summary.recent（每次调用）· budget（今天 / 上限）。金额是后端按 pricing.json 现价折算的人民币估算，前端不算价钱。
// 1027：旧的「余额与控制台」卡片（非 tableOnly 那一支）删了——服务商、余额、控制台 / 充值在④「更多 → 服务商与余额」（settings-pages.js renderKeyring）。
'use strict';
module.exports = function (obsidian, plugin) {
  const PERIODS = [['7d', 7, '近 7 天'], ['30d', 30, '近 30 天']];
  const DIMS = [['providers', '服务商'], ['models', '模型'], ['features', '功能']];
  const PROV_NAME = { deepseek: 'DeepSeek', aliyun: '阿里云百炼', google: 'Gemini', openai: 'OpenAI', cli: '本机命令行', other: '其他' };
  // 黑白：线型区分（实线 / 虚线 / 点线 / 点划线），不靠颜色
  const DASH = ['', '6 4', '2 3', '8 3 2 3'];
  const DASH_NAME = ['实线', '虚线', '点线', '点划线'];
  const CHART_H = 190;

  const yuan = v => (v == null || !Number.isFinite(+v) ? '—' : '¥' + (+v < 0.1 && +v > 0 ? (+v).toFixed(4).replace(/0+$/, '') : (+v).toFixed(2)));
  const num = v => { const n = +v || 0; return n >= 10000 ? (n / 10000).toFixed(n >= 1e6 ? 0 : 1) + ' 万' : String(n); };
  const openUrl = url => {
    if (!/^https:\/\//.test(url || '')) return;
    try { require('electron').shell.openExternal(url); return; } catch {}
    try { window.open(url); } catch (e) { console.error('[lb] 网页没打开', e); }
  };

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
    v = v || {};
    const [p0, m0] = String(key || '').split('|');
    const pv = v.provider != null ? v.provider : p0, md = v.model != null ? v.model : m0;
    const prov = PROV_NAME[pv] || pv || '';
    const model = md || (pv === 'cli' ? '本机命令行（没记下是哪个）' : '（没记模型名）');
    return prov && model !== prov && !model.startsWith('本机命令行') ? `${model} · ${prov}` : model;
  }
  const monthOf = data => {
    const month = ((data && data.summary) || {}).month || {};
    const vals = Object.values(month);
    return { cost: vals.reduce((a, m) => a + (+(m && m.cost) || 0), 0), unpriced: vals.reduce((a, m) => a + (+(m && m.unpriced) || 0), 0) };
  };

  // 折线的数：近 N 天、这个维度里真花过钱的那几条（最多 4 条，其余并成「其他」）；某天只有免费 / 未计价 = null（断开，不画成 ¥0）
  function chartModel(data, dim, days) {
    const se = ((data && data.summary) || {}).series || {};
    const dates = (se.dates || []).slice(-days);
    const names = ((data && data.summary) || {}).features || {};
    const all = Object.entries(se[dim] || {}).map(([k, arr]) => {
      const vals = (arr || []).slice(-days);
      return { key: k, name: rowName(dim, k, null, names), vals, total: vals.reduce((a, v) => a + (+v || 0), 0) };
    }).filter(x => x.vals.some(v => v != null && +v > 0)).sort((a, b) => b.total - a.total);
    let lines = all.slice(0, 4);
    if (all.length > 4) {
      lines = all.slice(0, 3);
      const rest = all.slice(3);
      const vals = dates.map((_, i) => { const xs = rest.map(r => r.vals[i]); return xs.every(v => v == null) ? null : xs.reduce((a, v) => a + (+v || 0), 0); });
      lines.push({ key: 'other', name: `其他 ${rest.length} 项`, vals, total: rest.reduce((a, r) => a + r.total, 0) });
    }
    const max = Math.max(0, ...lines.flatMap(l => l.vals.map(v => +v || 0)));
    const nice = max <= 0 ? 0 : (() => { const p = Math.pow(10, Math.floor(Math.log10(max))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= max) return m * p; return 10 * p; })();
    return { dates, lines, max: nice };
  }

  function paintChart(box, legend, model) {
    box.empty(); legend.empty();
    const doc = box.ownerDocument || document;
    const NS = 'http://www.w3.org/2000/svg';
    if (!model.lines.length) {
      box.createDiv({ cls: 'lb-chart-empty', text: '这段时间没有花钱的调用（免费 / 未计价的不画成 ¥0）' });
      return;
    }
    const W = 600, H = CHART_H - 24, n = Math.max(1, model.dates.length - 1);
    const svg = doc.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `近 ${model.dates.length} 天的人民币花费折线`);
    svg.setAttribute('class', 'lb-chart-svg');
    const y = v => H - 2 - (model.max ? (v / model.max) * (H - 6) : 0);
    for (let k = 0; k <= 3; k++) {
      const gy = y(model.max * k / 3);
      const ln = doc.createElementNS(NS, 'line');
      for (const [a, b] of [['x1', 0], ['x2', W], ['y1', gy], ['y2', gy]]) ln.setAttribute(a, String(b));
      ln.setAttribute('class', 'lb-chart-grid'); ln.setAttribute('vector-effect', 'non-scaling-stroke');
      svg.appendChild(ln);
      const lab = box.createDiv({ cls: 'lb-chart-y', text: yuan(model.max * k / 3) });
      lab.style.top = `${(gy / H) * (CHART_H - 24)}px`;
    }
    model.lines.forEach((l, i) => {
      let d = '', pen = false;
      l.vals.forEach((v, j) => {
        if (v == null) { pen = false; return; }   // 免费 / 未计价的那天：断开
        const px = (j / n) * W, py = y(+v || 0);
        d += `${pen ? 'L' : 'M'}${px.toFixed(1)} ${py.toFixed(1)} `;
        pen = true;
      });
      const p = doc.createElementNS(NS, 'path');
      p.setAttribute('d', d.trim()); p.setAttribute('class', 'lb-chart-line'); p.setAttribute('vector-effect', 'non-scaling-stroke');
      p.setAttribute('data-key', l.key);
      if (DASH[i]) p.setAttribute('stroke-dasharray', DASH[i]);
      svg.appendChild(p);
      const item = legend.createSpan({ cls: 'lb-chart-key' });
      item.createSpan({ cls: 'lb-chart-swatch is-' + i });
      item.createSpan({ text: l.name + (i ? ' · ' + DASH_NAME[i] : '') });
    });
    box.appendChild(svg);
    const xs = box.createDiv({ cls: 'lb-chart-x' });
    const md = s => String(s || '').slice(5).replace('-', '.');
    xs.createSpan({ text: md(model.dates[0]) }); xs.createSpan({ text: md(model.dates.at(-1)) });
  }

  // host：控制台画在这里；opts.load(force) → usage JSON（设置页一分钟内复用的那份）；opts.view：本次 Obsidian 会话里记住的展开 / 维度 / 时段
  function renderConsole(host, tab, opts = {}) {
    let alive = true, data = null;
    const view = opts.view || {};
    view.dim ||= 'providers'; view.period ||= '7d';
    const s = plugin.settings;
    const box = host.createDiv({ cls: 'lb-console', attr: { 'data-section': 'ai-console' } });
    const line = box.createDiv({ cls: 'lb-console-line' });
    const fold = line.createEl('button', { cls: 'lb-console-toggle', attr: { type: 'button', 'aria-expanded': String(!!view.open), 'aria-controls': 'lb-console-body' } });
    const today = fold.createSpan({ cls: 'lb-console-cell' });
    today.createSpan({ cls: 'lb-console-k', text: '今天' });
    const todayV = today.createSpan({ cls: 'lb-console-v', text: '—' });
    const month = fold.createSpan({ cls: 'lb-console-cell' });
    month.createSpan({ cls: 'lb-console-k', text: '本月' });
    const monthV = month.createSpan({ cls: 'lb-console-v', text: '—' });
    const monthSub = month.createSpan({ cls: 'lb-console-sub' });
    fold.createSpan({ cls: 'lb-console-more', text: view.open ? '收起' : '看明细' });
    // 每天最多花：唯一的上限输入框（目录页 Token 模块读同一个 budget.dailyYuan）；默认值只在后端（budget.DEFAULT_YUAN）
    const cap = line.createDiv({ cls: 'lb-console-cell lb-console-cap', attr: { 'data-section': 'ai-spend' } });
    const capK = cap.createSpan({ cls: 'lb-console-k', text: '每天最多花' });
    tab?.help?.({ nameEl: capK }, '只管后台的付费处理（夜里补识图、补概要、整理）：今天（北京时间）花到这个数就先停，明天接着补；你手动问收藏、连上的 Claude / ChatGPT 不受限。填 0 不限。');
    const capRow = cap.createSpan({ cls: 'lb-console-v' });
    capRow.createSpan({ text: '¥' });
    const input = capRow.createEl('input', { cls: 'lb-spend-input', attr: { type: 'number', min: '0', step: '0.5', 'aria-label': '后台每天最多花多少元（0 = 不限）' } });
    const capNote = cap.createSpan({ cls: 'lb-console-sub' });
    const over = box.createDiv({ cls: 'lb-console-over' });
    const body = box.createDiv({ cls: 'lb-console-body', attr: { id: 'lb-console-body' } });
    body.hidden = !view.open;
    const grid = body.createDiv({ cls: 'lb-console-grid' });
    const left = grid.createDiv({ cls: 'lb-console-left' });
    const chart = left.createDiv({ cls: 'lb-chart' });
    chart.style.height = CHART_H + 'px';
    const legend = left.createDiv({ cls: 'lb-chart-legend' });
    const right = grid.createDiv({ cls: 'lb-console-right' });
    const ctl = right.createDiv({ cls: 'lb-console-ctl' });
    const dimBar = ctl.createDiv({ cls: 'lb-seg lb-usage-dims', attr: { role: 'tablist', 'aria-label': '按什么看' } });
    const period = ctl.createEl('select', { cls: 'dropdown lb-console-period', attr: { 'aria-label': '时段' } });
    for (const [id, , label] of PERIODS) period.createEl('option', { text: label, attr: { value: id } });
    period.value = view.period;
    const table = right.createDiv({ cls: 'lb-usage-table' });
    const gaps = right.createDiv({ cls: 'lb-usage-gaps' });
    const calls = body.createEl('details', { cls: 'lb-row-fold lb-usage-calls', attr: { 'data-section': 'usage-calls' } });
    const callsSum = calls.createEl('summary');
    callsSum.createDiv({ cls: 'lb-rf-name', text: '每次调用' });
    const callsDesc = callsSum.createDiv({ cls: 'lb-rf-desc', text: '' });
    const callsBody = calls.createDiv({ cls: 'lb-rf-body' });
    calls.addEventListener?.('toggle', () => { if (calls.open && data) paintCalls(); });
    const foot = body.createEl('p', { cls: 'setting-item-description lb-usage-foot' });

    fold.onclick = () => {
      view.open = !view.open; body.hidden = !view.open;
      fold.setAttribute('aria-expanded', String(view.open));
      fold.querySelector('.lb-console-more')?.setText?.(view.open ? '收起' : '看明细');
      if (view.open && data) paintBody();
    };
    period.onchange = () => { view.period = period.value; paintBody(); };

    const savedCap = () => (s.budget && s.budget.dailyYuan !== undefined && s.budget.dailyYuan !== '' ? +s.budget.dailyYuan : null);
    const paintCap = () => {
      const b = (data && data.budget) || {};
      const cur = savedCap() != null && Number.isFinite(savedCap()) ? savedCap() : Number.isFinite(+b.daily_yuan) ? +b.daily_yuan : '';
      if (input.ownerDocument?.activeElement !== input) input.value = String(cur);
      capNote.setText(cur === 0 ? '不限' : '');
    };
    input.addEventListener('change', async () => {
      const raw = String(input.value).trim();
      const n = Math.max(0, Math.round(+raw * 100) / 100);
      if (raw === '' || !Number.isFinite(n)) { paintCap(); return; }
      const prev = s.budget ? { ...s.budget } : undefined;
      s.budget = { ...(s.budget || {}), dailyYuan: n };
      try { await plugin.saveSettings(); paintCap(); }
      catch (e) { s.budget = prev; paintCap(); plugin.notify('没保存上，已改回原来的：' + ((e && e.message) || e), { kind: 'error' }); }
    });

    function paintHead() {
      const b = data.budget || {}, m = monthOf(data);
      todayV.setText(yuan(b.spent_today));
      monthV.setText(yuan(m.cost));
      monthSub.setText(m.unpriced ? `另有 ${m.unpriced} 次未计价` : '');
      over.setText(b.over ? '今天到上限了：后台的付费处理先停，北京时间明天 0 点恢复；你手动问收藏不受影响。' : '');
      paintCap();
    }
    function paintDims() {
      dimBar.empty();
      for (const [id, label] of DIMS) {
        const b = dimBar.createEl('button', { cls: 'lb-usage-dim' + (id === view.dim ? ' is-active' : ''), text: label,
          attr: { type: 'button', role: 'tab', 'aria-selected': String(id === view.dim), 'aria-pressed': String(id === view.dim), 'data-dim': id } });
        b.onclick = () => { view.dim = id; paintBody(); };
      }
    }
    function paintTable() {
      table.empty();
      const sum = data.summary || {}, names = sum.features || {};
      const w = (sum.windows || {})[view.period] || { total: {} };
      const t = table.createEl('table', { cls: 'lb-usage-grid', attr: { 'data-dim': view.dim } });
      const head = t.createEl('tr');
      head.createEl('th', { text: DIMS.find(d => d[0] === view.dim)[1] });
      head.createEl('th', { text: (PERIODS.find(p => p[0] === view.period) || [])[2] || '' });
      const rows = Object.entries(w[view.dim] || {}).sort((x, y) => (+y[1].cost || 0) - (+x[1].cost || 0) || (+y[1].calls || 0) - (+x[1].calls || 0));
      for (const [k, v] of rows) {
        const tr = t.createEl('tr', { attr: { 'data-key': k } });
        tr.createEl('td', { text: rowName(view.dim, k, v, names) });
        const m = tr.createEl('td', { cls: 'lb-usage-money', text: moneyText(v) });
        m.setAttribute('title', `${v.calls || 0} 次调用 · 输入 ${num(v.in)} / 输出 ${num(v.out)} token` + (v.failed ? ` · 失败 ${v.failed}` : ''));
        if (v.calls && v.free === v.calls) m.addClass?.('is-free');
        if (v.unpriced) m.addClass?.('is-unpriced');
      }
      if (!rows.length) t.createEl('tr').createEl('td', { text: '这段时间没调用过 AI。', attr: { colspan: '2' } });
      const tot = w.total || {};
      const add = (label, value, cls) => { const tr = t.createEl('tr', { cls }); tr.createEl('td', { text: label }); tr.createEl('td', { text: value }); };
      add('已计价合计', yuan(tot.cost || 0), 'lb-usage-total');
      add('免费 / 未计费', tot.free ? `${tot.free} 次` : '—', 'lb-usage-free');
      add('未计价', tot.unpriced ? `${tot.unpriced} 次` : '—', 'lb-usage-unpriced');
      gaps.empty();
      const un = w.unpriced_models || [];
      if (un.length) gaps.setText('未计价（价格表里查不到，没算进 ¥）：' + un.map(u => `${rowName('models', '', u, names)} ${u.calls} 次`).join('、'));
      const recent = sum.recent || [];
      callsDesc.setText(recent.length ? `最近 ${recent.length} 次：几点、哪个功能、哪家哪个模型、多少 token、多少钱` : '还没有调用记录');
      foot.setText(`人民币估算，按价格表（${sum.as_of || '—'} 核对）现价折算，以服务商账单为准；「免费 / 未计费」= 本机命令行和免费 key，不算进 ¥，也不表示第三方订阅免费；「未计价」= 价格表里查不到，没算钱也不当 0。折线和表按这台电脑的日子分天；「今天」和上限按北京时间。`);
    }
    // 每次调用一行（后端账本原样：时间 · 功能 · 服务商 · 模型 · token · 金额 · 哪一篇）——只读、只显示，不记 key 和内容
    function paintCalls() {
      callsBody.empty();
      const sum = data.summary || {}, names = sum.features || {};
      const days = (PERIODS.find(p => p[0] === view.period) || [0, 30])[1];
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
    function paintBody() {
      if (!alive || !data) return;
      period.value = view.period;
      paintDims(); paintTable();
      const days = (PERIODS.find(p => p[0] === view.period) || [0, 7])[1];
      paintChart(chart, legend, chartModel(data, view.dim, days));
      if (calls.open) paintCalls();
    }
    async function load(force = false) {
      try {
        const json = opts.load ? await opts.load(force) : (await plugin.runPy(['-m', 'link_brain', 'usage'], { label: '读 AI 用量', timeoutMs: 45000, fallback: '用量没读出来' })).json;
        if (!alive) return;
        if (!json || json.ok === false) throw new Error((json && json.message) || '用量没读出来');
        data = json;
        paintHead();
        if (view.open) paintBody(); else { paintDims(); }
        opts.onData && opts.onData(data);
      } catch (e) {
        if (!alive) return;
        todayV.setText('—'); monthV.setText('—'); paintCap();
        over.empty();
        plugin.failBox?.(over, 'AI 用量', e, () => { over.empty(); load(true); });
      }
    }
    paintCap();
    load(false);
    return { stop: () => { alive = false; }, reload: () => load(true), get data() { return data; } };
  }

  return { renderConsole, chartModel, moneyText, rowName, openUrl, CHART_H };
};

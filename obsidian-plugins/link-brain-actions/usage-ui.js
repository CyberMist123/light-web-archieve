// usage-ui.js — 1016 设置页「模型与提供商 → 用量与余额」：每家提供商的余额 / 本月花费 / 密钥状态 + 「控制台」「充值」「看用量」跳转，
// 下面一张各功能明细表（今天 / 7 天 / 30 天）。数据只来自后端 `link_brain usage [--balance]`（CONVENTIONS §1 最后一行 JSON），
// 金额是后端按 pricing.json 现价折算的估算；跳转网址也由后端给（pricing.json providers，10-16 核对过）。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Setting } = obsidian;
  const WINDOWS = [['today', '今天'], ['7d', '近 7 天'], ['30d', '近 30 天']];
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

  function render(host, tab) {
    let alive = true, data = null, win = 'today';
    const top = tab.card(host, '余额与控制台', 'usage-providers', { desc: '每家一行：余额、这个月花了多少，点按钮直接打开它的网页（要在网页里登录）。' });
    const topBody = top.createDiv({ cls: 'lb-usage-providers' });
    const feat = tab.card(host, '各功能用了多少', 'usage-features');
    const switcher = feat.head.createDiv({ cls: 'lb-usage-windows', attr: { role: 'tablist' } });
    const table = feat.createDiv({ cls: 'lb-usage-table' });
    const foot = feat.createEl('p', { cls: 'lb-card-desc lb-usage-foot' });
    tab.link(new Setting(feat), '刷新', () => load(), '重新读一遍用量和余额');

    const paintSwitch = () => {
      switcher.empty();
      for (const [id, label] of WINDOWS) {
        const b = switcher.createEl('button', { cls: 'lb-usage-win' + (id === win ? ' is-active' : ''), text: label,
          attr: { type: 'button', role: 'tab', 'aria-selected': String(id === win), 'data-win': id } });
        b.onclick = () => { win = id; paintSwitch(); paintTable(); };
      }
    };

    function paintProviders() {
      topBody.empty();
      const links = data.links || {}, month = (data.summary || {}).month || {}, keys = data.keys || {}, bal = data.balances || {};
      const ids = [...ORDER.filter(k => links[k]), ...Object.keys(month).filter(k => !links[k] && k !== 'cli')];
      for (const id of ids) {
        const l = links[id] || {}, m = month[id], k = keys[id];
        const row = new Setting(topBody).setName(l.name || id);
        row.settingEl.addClass('lb-usage-provider'); row.settingEl.setAttribute?.('data-provider', id);
        const desc = row.descEl;
        if (bal[id] || data.balances) desc.createDiv({ cls: 'lb-usage-balance' + (bal[id] && !bal[id].ok && !bal[id].unsupported ? ' is-warn' : ''), text: balanceText(bal[id]) || '余额：正在查…' });
        desc.createDiv({ cls: 'lb-usage-month', text: m ? `本月 ${yuan(m.cost)} · ${m.calls} 次调用${m.unpriced ? `（${m.unpriced} 次的模型不在价格表里，没算钱）` : ''}` : '本月没用过' });
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
      const w = ((data.summary || {}).windows || {})[win] || { features: {}, total: {} };
      const names = (data.summary || {}).features || {};
      const t = table.createEl('table', { cls: 'lb-usage-grid' });
      const head = t.createEl('tr');
      for (const h of ['功能', '篇数', '调用', '输入 token', '输出 token', '金额']) head.createEl('th', { text: h });
      const rows = Object.entries(w.features || {});
      for (const [f, v] of rows) {
        const tr = t.createEl('tr', { attr: { 'data-feature': f } });
        tr.createEl('td', { text: names[f] || f });
        tr.createEl('td', { text: v.items ? String(v.items) : '—' });
        tr.createEl('td', { text: String(v.calls) + (v.failed ? `（失败 ${v.failed}）` : '') });
        tr.createEl('td', { text: f === 'asr' && v.sec ? `${Math.round(v.sec / 60)} 分钟音频` : num(v.in) });
        tr.createEl('td', { text: num(v.out) });
        tr.createEl('td', { text: v.unpriced && !v.cost ? '—' : yuan(v.cost) });
      }
      if (!rows.length) t.createEl('tr').createEl('td', { text: '这段时间没调用过 AI。', attr: { colspan: '6' } });
      else {
        const tot = w.total || {}, tr = t.createEl('tr', { cls: 'lb-usage-total' });
        for (const v of ['合计', '', String(tot.calls || 0), num(tot.in), num(tot.out), yuan(tot.cost)]) tr.createEl('td', { text: v });
      }
      foot.setText(`金额是按价格表（${(data.summary || {}).as_of || '—'} 核对）现价折算的估算，以控制台账单为准；DeepSeek 按调用时刻分高峰 / 空闲价；「—」= 价格表里没有这个模型。本机命令行模型不花钱，算调用次数不算钱。「今天」从这台电脑的 0 点算；阿里云 / DeepSeek 的账单按北京时间分天、还要晚几个小时才出，对不上时看「近 7 天」。连上的 Claude / ChatGPT 搜收藏、问收藏花的也都记在这里。`);
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

    load();
    return () => { alive = false; };
  }

  return { render, openUrl, balanceText };
};

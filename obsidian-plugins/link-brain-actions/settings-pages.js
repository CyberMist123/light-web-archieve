// settings-pages.js — 设置页里「服务商」那几块小积木（1027 设置页六组以后只剩这些）：
//   LINKS（各家拿 key / 控制台 / 充值的兜底网址，后端 usage.links 给了就以后端为准）·
//   renderKeyring（④「更多 → 服务商与余额」：按服务商一行——管哪些功能、key 从哪来、余额、本月、key 出了问题、控制台 / 充值 / 拿 key）·
//   routeText（④「更多 → 接口与密钥」选了一项后的那一句：主用 → 备用，现在谁在干活）。
// 1027 删掉：1016 四页签（概览 / 同步 / 更多 / 第一次的四步指引 / 「需要你留意」）和 1018 AI 页（花费三格 · 每个功能用谁 · 只用免费的功能）——
//   六组设置页（settings-v6.js）里各有唯一的一处；首次设置在 settings-v6.js renderGuide。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Setting } = obsidian;

  const openUrl = url => {
    if (!/^https:\/\//.test(url || '')) return;
    try { require('electron').shell.openExternal(url); return; } catch {}
    try { window.open(url); } catch (e) { console.error('[lb] 网页没打开', e); }
  };

  // —— 提供商：哪家管哪些功能由后端认（ai_routes 每一格带 provider，pricing.provider_of 一处），这里只放名字和跳转兜底 ——
  const PROVIDER_NAME = { google: 'Gemini', aliyun: '阿里云百炼', deepseek: 'DeepSeek', openai: 'OpenAI' };
  const LINKS = {
    google: { key: 'https://aistudio.google.com/apikey', console: 'https://aistudio.google.com/', usage: 'https://aistudio.google.com/usage' },
    aliyun: { key: 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key', console: 'https://bailian.console.aliyun.com/cn-beijing/',
      recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge' },
    deepseek: { key: 'https://platform.deepseek.com/api_keys', console: 'https://platform.deepseek.com/', recharge: 'https://platform.deepseek.com/top_up' },
    openai: { key: 'https://platform.openai.com/api-keys' },
  };
  const fmtYuan = v => (v == null || !Number.isFinite(+v) ? '—' : '¥' + (+v >= 10 ? (+v).toFixed(1) : (+v).toFixed(2)));

  // 现在是谁在干活：用备用时是状态里点名的那个，否则是第一个
  function workingIndex(f) {
    if (f.state !== 'backup') return 0;
    const t = String(f.state_text || '');
    const i = (f.chain || []).findIndex((c, k) => k > 0 && ((c.model && t.includes(c.model)) || t.includes(c.label)));
    return i > 0 ? i : 0;
  }
  // 「主用 → 备用」一句（后端 ai_routes 给的链）：现在在干活的那一格标出来；没开 / 没配如实说
  function routeText(data, featureId) {
    const f = ((data && data.features) || []).find(x => x.id === featureId);
    if (!f) return '';
    if (!(f.chain || []).length) return '还没配';
    const w = workingIndex(f);
    const chain = f.chain.map((c, i) => (i === w && f.on ? '【' + c.label + '】' : c.label)).join(' → ');
    return (f.on ? '' : '（关着）') + chain + (f.state && !['ok', 'off'].includes(f.state) && f.state_text ? ' · ' + f.state_text : '');
  }

  function balanceText(b) {
    const parts = (b.balances || []).map(x => `${x.currency === 'USD' ? '$' : '¥'}${x.total}`);
    return '余额 ' + (parts.join(' · ') || '0') + (b.available === false ? '（不够调用了）' : '');
  }

  function renderKeyring(box, data, tab) {
    box.empty();
    const links = data.links || {}, month = (data.summary || {}).month || {}, keys = data.keys || {}, bal = data.balances || null;
    const by = new Map();
    for (const f of data.features || []) (f.chain || []).forEach((c, i) => {
      if (!c.provider || c.provider === 'cli') return;
      const r = by.get(c.provider) || { id: c.provider, uses: [], key: '' };
      const label = f.name.replace(' · 打标签', '') + (i ? '（备用）' : '');
      if (f.on && !r.uses.includes(label)) r.uses.push(label);
      if (!r.key && c.key) r.key = c.key;
      by.set(c.provider, r);
    });
    const order = ['google', 'deepseek', 'aliyun', 'openai'];
    const rows = [...by.values()].sort((a, b) => ((order.indexOf(a.id) + 1) || 99) - ((order.indexOf(b.id) + 1) || 99));
    if (!rows.length) { box.createEl('p', { cls: 'setting-item-description', text: '还没接要 key 的 AI。不接也能存、能按关键词搜；要用就在上面「接口与密钥」里粘一把 key。' }); return; }
    for (const r of rows) {
      const l = { ...(LINKS[r.id] || {}), ...(links[r.id] || {}) };
      const name = PROVIDER_NAME[r.id] || l.name || r.id;
      const row = new Setting(box).setName(name);
      row.settingEl.addClass('lb-key-ring-row'); row.settingEl.setAttribute('data-provider', r.id);
      const desc = row.descEl;
      desc.createDiv({ text: '管：' + (r.uses.join(' · ') || '现在没有功能在用') });
      desc.createDiv({ cls: 'lb-key-src', text: 'key：' + (r.key || '没填') });
      const m = month[r.id], b = bal && bal[r.id];
      const money = [];
      if (b && b.ok) money.push(balanceText(b));
      else if (b && b.unsupported) money.push('余额要去控制台看');
      // 1026：全是免费 key / 本机命令行的那家写「免费 / 未计费」，不写 ¥0.00；查不到价的次数单说
      if (m) money.push(m.calls && m.free === m.calls ? `本月免费 / 未计费 · ${m.calls} 次` : `本月 ${fmtYuan(m.cost)} · ${m.calls} 次` + (m.free ? `（免费 ${m.free} 次）` : '') + (m.unpriced ? `（未计价 ${m.unpriced} 次）` : ''));
      else if (r.id === 'google') money.push('免费额度，不花钱');
      if (money.length) desc.createDiv({ text: money.join(' · ') });
      const k = keys[r.id];
      if (k) desc.createDiv({ cls: 'lb-key-warn', text: (String(k.code || '').endsWith('QUOTA_EXCEEDED') ? '额度用完了' : 'key 用不了（可能欠费、过期或没开通）') + '：配了备用的会自动改用备用' });
      for (const [text, url] of [['控制台', l.console], ['充值', l.recharge], ['拿 key', l.key || l.key_url]])
        if (url) tab.link(row, text, () => openUrl(url), `在浏览器打开 ${name} 的${text}页`);
    }
  }

  return { LINKS, PROVIDER_NAME, renderKeyring, routeText, workingIndex, balanceText, openUrl };
};

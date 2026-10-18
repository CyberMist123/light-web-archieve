// settings-pages.js — 1016 设置页重做（她：用户懒得动、不想看的别放设置；要确认的、要知道的才放，小白看得懂，一次别让人选太多）。
// 四个页签：概览 · 同步 · AI · 更多。每页小标题 + 平铺的行，不套框；细项一律收进「更多」或页底的折叠里。
// 第一次用（库里还没有收藏、也没走完指引）概览页换成四步指引：放在哪 → 登录小红书 → AI 帮忙 → 开始同步。
// 这里只排版和接线：每一行的读写、保存失败拨回等仍用设置页（tab）上原有的方法。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Setting } = obsidian;

  const openUrl = url => {
    if (!/^https:\/\//.test(url || '')) return;
    try { require('electron').shell.openExternal(url); return; } catch {}
    try { window.open(url); } catch (e) { console.error('[lb] 网页没打开', e); }
  };

  // —— 小积木 ——
  function heading(parent, text, section) {
    const h = parent.createDiv({ cls: 'lb-sec-h', text });
    if (section) h.setAttribute('data-section', section);
    return h;
  }
  // 页底折叠：默认收着，标题一句话说里面是什么
  function fold(parent, title, section) {
    const d = parent.createEl('details', { cls: 'lb-fold' });
    if (section) d.setAttribute('data-section', section);
    d.createEl('summary', { text: title });
    return d.createDiv({ cls: 'lb-fold-body' });
  }
  function safe(tab, c, what, fn) { return tab.safe ? tab.safe(c, what, fn) : fn(); }

  // —— 提供商：从接口地址认是哪家（和 Python usage.provider_of 同一套）——
  const PROVIDER_NAME = { google: 'Gemini', aliyun: '阿里云百炼', deepseek: 'DeepSeek', openai: 'OpenAI' };
  const LINKS = {
    google: { key: 'https://aistudio.google.com/apikey', console: 'https://aistudio.google.com/', usage: 'https://aistudio.google.com/usage' },
    aliyun: { key: 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key', console: 'https://bailian.console.aliyun.com/cn-beijing/',
      recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge' },
    deepseek: { key: 'https://platform.deepseek.com/api_keys', console: 'https://platform.deepseek.com/', recharge: 'https://platform.deepseek.com/top_up' },
    openai: { key: 'https://platform.openai.com/api-keys' },
  };
  function providerOf(endpoint, model) {
    const e = String(endpoint || '').toLowerCase(), m = String(model || '').toLowerCase();
    if (e.includes('deepseek') || (!e && m.startsWith('deepseek'))) return 'deepseek';
    if (e.includes('aliyuncs') || e.includes('dashscope') || (!e && m.startsWith('qwen'))) return 'aliyun';
    if (e.includes('openai.com')) return 'openai';
    if (e.includes('googleapis')) return 'google';
    if (!e) return '';
    return e.split('://').pop().split('/')[0];
  }
  // 每个功能现在用谁：[{id, label, cap, fallback?}]，按功能列；off / cli 的不算 API
  function featureUses(s) {
    const out = [];
    const add = (label, cfg, extra = {}) => {
      if (!cfg || cfg.mode === 'off' || cfg.mode === 'cli' || cfg.mode === 'capswriter') return;
      const id = providerOf(cfg.endpoint, cfg.model);
      if (id) out.push({ id, label, pool: cfg.keyPool || '', ...extra });
    };
    const text = s.textAI || {};
    add('问收藏', text);
    const sum = s.summaryAI || {};
    if (sum.mode === 'inherit' || !sum.mode) add('概要', { ...text, model: sum.model || text.model }); else add('概要', sum);
    if (sum.fallback) add('概要', sum.fallback, { backup: true });
    const vis = s.visionAI || {};
    add('识图', vis);
    if (vis.refine) add('精细识图', vis.refine, { backup: true });
    const emb = s.embedAI || (vis.mode === 'http' && !vis.keyPool ? { ...vis, endpoint: String(vis.endpoint || '').replace(/\/chat\/completions$/, '/embeddings') } : null);
    add('语义搜索', emb);
    if ((s.asrAI || {}).mode === 'http') add('视频转文字', s.asrAI);
    return out;
  }
  function providerRows(s) {
    const by = new Map();
    for (const u of featureUses(s)) {
      const row = by.get(u.id) || { id: u.id, main: [], backup: [], pool: '' };
      (u.backup ? row.backup : row.main).push(u.label);
      if (u.pool) row.pool = u.pool;
      by.set(u.id, row);
    }
    const order = ['google', 'deepseek', 'aliyun', 'openai'];
    return [...by.values()].sort((a, b) => ((order.indexOf(a.id) + 1) || 99) - ((order.indexOf(b.id) + 1) || 99))
      .map(r => ({ ...r, main: [...new Set(r.main)], backup: [...new Set(r.backup.filter(x => !r.main.includes(x)))] }));
  }

  // —— 「需要你留意」：只列真要人动手的；措辞说发生了什么、有没有影响、点哪里（她：别吓人、别 bossy）——
  const ACCOUNT_STEPS = new Set(['login', 'sync.favorites']);
  function attentionText(p) {
    const code = String(p.code || ''), sub = code.split('.').pop(), step = String(p.step || '');
    if (step.startsWith('ai.') || ['AUTH_FAILED', 'QUOTA_EXCEEDED'].includes(sub)) {
      // 1018：只认「坏的是谁」那一段——原因里「已换用 通义千问 …」是顶上的备用，以前被当成坏的那家，概览就冤枉了百炼
      const reason = String(p.reason || '');
      const head = reason.split('已换用')[0];
      const backup = (reason.match(/已换用 ([^（；;]+)/) || [])[1] || '';
      const m = head.match(/^([^（(；;]+?)（([^，,）)]+)/);
      const named = String(p.links?.provider || '');
      const pick = t => /Gemini|Google/.test(t) ? 'Gemini' : /DeepSeek/.test(t) ? 'DeepSeek' : /通义|千问|百炼/.test(t) ? '阿里云百炼' : '';
      const who = pick(named) || pick(head) || (m ? m[2] : 'AI');
      const what = step === 'ai.vision' ? '识图' : step === 'ai.summary' ? '概要' : step === 'ai.embed' ? '语义搜索' : step === 'ai.refine' ? '精细识图' : '';
      const desc = backup ? `可能欠费、过期或没开通服务。${what || '这项'}没停：已自动改用 ${backup.trim()} 顶上。`
        : `可能欠费、过期或没开通服务${what ? `；影响${what}` : ''}。配了备用的会自动改用备用。`;
      return { title: `${who}的 key 用不了`, desc,
        provider: who === '阿里云百炼' ? 'aliyun' : who === 'DeepSeek' ? 'deepseek' : who === 'Gemini' ? 'google' : '' };
    }
    if (sub === 'NOTE_RESTRICTED') return { title: `有一篇要在网页上验证一下才能看`, desc: p.title ? `《${String(p.title).slice(0, 24)}》` : '', restricted: p.item_id };
    return { title: p.label || '有一件事没做成', desc: String(p.hover || p.reason || '').slice(0, 80) };
  }

  async function paintAttention(box, tab) {
    box.empty();
    let list = [];
    try {
      const cached = plugin.problemsCache && Date.now() - plugin.problemsCache.at < 60000 ? plugin.problemsCache : null;
      let problems = cached ? cached.problems : null;
      if (!problems) {
        const r = await plugin.runPy(['-m', 'link_brain', 'problems', 'list'], { label: '读取需要留意的事', fallback: '读不到', timeoutMs: 60000, quiet: true });
        problems = (r && r.json && Array.isArray(r.json.problems)) ? r.json.problems : [];
        plugin.problemsCache = { problems, summary: r?.json?.summary || null, at: Date.now() };
      }
      list = problems.filter(p => p.group === 'needs_you' && !p.hidden && !p.resolved_at && !ACCOUNT_STEPS.has(String(p.step || '')));
    } catch (e) { console.error('[lb] 需要留意的事没读到', e); return; }
    if (!list.length) return;   // 没事就整块不出现
    heading(box, '需要你留意', 'attention');
    const seen = new Set();
    for (const p of list.slice(0, 5)) {
      const t = attentionText(p);
      if (seen.has(t.title)) continue;
      seen.add(t.title);
      const row = new Setting(box).setName(t.title).setDesc(t.desc || '');
      row.settingEl.addClass('lb-attn-row');
      const links = LINKS[t.provider] || null;
      if (links?.console) tab.link(row, '去控制台看看', () => openUrl(links.console), '在浏览器打开它的控制台');
      if (t.provider) tab.link(row, '换一把 key', () => tab.showTab('ai'), '到 AI 页改 key');
      if (t.restricted && plugin.openNoteVerify) tab.link(row, '打开验证', () => plugin.openNoteVerify(t.restricted), '打开这篇，过一下验证');
    }
    if (list.length > 5) tab.link(new Setting(box).setName(`还有 ${list.length - 5} 件`), '查看', () => plugin.openProblems(), '打开完整记录');
  }

  // ———————————————————— 概览 ————————————————————
  function renderOverview(c, tab) {
    const att = c.createDiv({ cls: 'lb-attn' });
    paintAttention(att, tab).catch(console.error);
    heading(c, '小红书账号', 'status');
    safe(tab, c, '小红书账号', () => plugin.renderAccounts(c));
    heading(c, '收藏', 'collect-status');
    safe(tab, c, '收藏同步', () => tab.stops.push(plugin.renderSyncRow(c, { compact: true, onSchedule: () => tab.showTab('sync') })));
    const more = new Setting(c).setName('全部记录').setDesc('每次同步做了什么、哪里没做成、系统已经怎么处理的。');
    tab.link(more, '打开', () => plugin.openProblems(), '打开同步与问题记录');
  }

  // ———————————————————— 同步：三项，其余收进折叠 ————————————————————
  function renderSync(c, tab) {
    const s = plugin.settings, so = s.sync;
    heading(c, '什么时候同步', 'schedule');
    const row = new Setting(c).setName('自动同步').setDesc('电脑开着就会按时同步，Obsidian 不用开。');
    row.settingEl.addClass('lb-sched-row');
    safe(tab, c, '自动同步', () => { const ed = plugin.scheduleUI().render(c.createDiv({ cls: 'lb-sched-host' }), { primary: false }); tab.stops.push(() => ed.destroy()); });
    heading(c, '存什么', 'collect');
    tab.toggleRow(c, '存视频', '关掉只存封面和地址，省硬盘。', () => so.downloadVideo, v => { so.downloadVideo = v; });
    tab.fieldCommentFloors(c);
    const more = fold(c, '更多同步选项：放在哪、每次多少篇、补评论节奏', 'sync-more');
    tab.fieldCollectionFolder(more);
    tab.toggleRow(more, '存图片', '关掉只存文字和图片地址。', () => so.downloadImages, v => { so.downloadImages = v; });
    tab.toggleRow(more, '登录后马上同步', '第一次扫码登录成功后就开始。', () => so.autoAfterLogin, v => { so.autoAfterLogin = v; });
    tab.fieldPerRunLimit(more);
    tab.fieldDailyLimit(more);
    tab.fieldFillPace(more);
  }

  // ———————————————————— AI（1018 重排）：花费 · 每个功能用谁 · 钥匙串 ————————————————————
  // 她：设置太乱——同一套「接口 / key / 模型」出现三遍，备用走了最贵的模型也看不出来。现在：
  //   顶上三格：今天花了多少（北京时间，和账单同一天）· 本月 · 每天上限（超了后台补跑只用免费的，她自己问收藏不受限）；
  //   功能表：一个功能一行，主用 → 备用从左往右顶，写现在谁在干活、大概多少钱；点一行展开这一项的细项（原「详细设置」拆到各行里）；
  //   钥匙串：按服务商列，key 从哪来、余额、本月、管哪些功能、控制台 / 充值 / 拿 key。
  // 数据一次读回：`link_brain usage`（summary · links · keys · features · budget），余额另一次（要联网）。
  const ROUTE_TOGGLE = { ask: ['ai_text', '问收藏、概要、语义搜索一起开关'], vision: ['ai_vision', '识图、精细识图一起开关'],
    ocr: ['ocr', ''], asr: ['asr', ''], capslock: ['capslock', ''] };
  const STATE_CLS = { ok: 'is-ok', backup: 'is-warn', budget: 'is-warn', waiting: 'is-warn', down: 'is-bad', off: 'is-off' };
  const STATE_SHORT = { ok: '正常', backup: '用备用', budget: '到上限', waiting: '暂时不通', down: '停了', off: '关着' };
  const fmtYuan = v => (v == null || !Number.isFinite(+v) ? '—' : '¥' + (+v >= 10 ? (+v).toFixed(1) : (+v).toFixed(2)));

  function localRoutes(s) {
    const sel = new Set(Array.isArray(s.setup?.selected) ? s.setup.selected : ['core', 'reader', 'dataview', 'ocr']);
    const st = on => (on ? ['ok', '正常'] : ['off', '关着']);
    const ocrOn = s.ocr?.mode !== 'off', asrOn = sel.has('asr') || ['capswriter', 'http'].includes(s.asrAI?.mode);
    const http = s.asrAI?.mode === 'http';
    const row = (id, name, on, label, price) => { const [state, text] = st(on); return { id, name, on, state, state_text: text, chain: [{ label, price, free: price === '免费' }] }; };
    return [
      row('ocr', '认图片里的字', ocrOn, '本机 OCR', '免费'),
      row('asr', '视频说话转文字', asrOn, http ? `在线接口 ${s.asrAI.model || 'whisper-1'}` : '本机 CapsWriter', http ? '按用量' : '免费'),
      row('capslock', '按住 CapsLock 说话', !!s.voice?.capsLock, '本机 CapsWriter', '免费'),
    ];
  }

  // 现在是谁在干活：用备用时是状态里点名的那个，否则是第一个
  function workingIndex(f) {
    if (f.state !== 'backup') return 0;
    const t = String(f.state_text || '');
    const i = (f.chain || []).findIndex((c, k) => k > 0 && ((c.model && t.includes(c.model)) || t.includes(c.label)));
    return i > 0 ? i : 0;
  }

  function paintSpend(box, data, tab) {
    box.empty();
    const s = plugin.settings;
    const b = data.budget || {}, month = (data.summary || {}).month || {};
    const monthTotal = Object.values(month).reduce((a, m) => a + (+(m && m.cost) || 0), 0);
    const cell = (label, value) => {
      const d = box.createDiv({ cls: 'lb-spend-cell' });
      d.createDiv({ cls: 'lb-spend-label', text: label });
      return [d, d.createDiv({ cls: 'lb-spend-value', text: value })];
    };
    const [today] = cell('今天（北京时间）', fmtYuan(b.spent_today));
    if (b.over) today.addClass('is-warn');
    cell('本月', fmtYuan(monthTotal));
    const [capCell, capVal] = cell('每天上限', '');
    const saved = s.budget && s.budget.dailyYuan !== undefined && s.budget.dailyYuan !== '' ? +s.budget.dailyYuan : null;
    const cur = saved != null && Number.isFinite(saved) ? saved : +(b.daily_yuan ?? 3);
    capVal.createSpan({ text: '¥' });
    const input = capVal.createEl('input', { cls: 'lb-spend-input', attr: { type: 'number', min: '0', step: '1', 'aria-label': '每天花费上限（元，0 = 不限）' } });
    input.value = String(cur);
    const unit = capVal.createSpan({ cls: 'lb-spend-unit', text: cur > 0 ? '' : '不限' });
    input.addEventListener('change', async () => {
      const n = Math.max(0, Math.round(+input.value * 100) / 100);
      if (!Number.isFinite(n)) { input.value = String(cur); return; }
      const prev = s.budget ? { ...s.budget } : undefined;
      s.budget = { ...(s.budget || {}), dailyYuan: n };
      try {
        await plugin.saveSettings();
        unit.setText(n > 0 ? '' : '不限');
        plugin.notify(n > 0 ? `每天上限改成 ¥${n}：超了后台补跑只用免费的` : '每天上限关了：后台补跑不限花费');
      } catch (e) { s.budget = prev; input.value = String(cur); plugin.notify('没保存上，已改回原来的：' + e.message, { kind: 'error' }); }
    });
    tab.help?.({ nameEl: capCell.querySelector('.lb-spend-label') }, '今天（北京时间）花到这个数，夜里补识图、补概要就只用免费的（Gemini 免费 key、本机），明天接着补；你自己问收藏、连上的 Claude / ChatGPT 不受限。0 = 不限。');
    if (b.over) box.createDiv({ cls: 'lb-spend-note', text: '今天到上限了：后台补跑先只用免费的，北京时间明天 0 点恢复。想今天补完就把上限调高。' });
  }

  function paintRoutes(box, data, tab, redraw) {
    box.empty();
    const s = plugin.settings, home = plugin.homeUI ? plugin.homeUI() : null;
    if (data.routes_error) box.createDiv({ cls: 'setting-item-description', text: '各功能的配置没读全：' + data.routes_error });
    const feats = [...(data.features || []), ...localRoutes(s)];
    for (const f of feats) {
      const d = box.createEl('details', { cls: 'lb-route ' + (STATE_CLS[f.state] || ''), attr: { 'data-feature': f.id, 'data-state': f.state } });
      const head = d.createEl('summary', { cls: 'lb-route-head' });
      head.createSpan({ cls: 'lb-route-name', text: f.name });
      const chain = head.createSpan({ cls: 'lb-route-chain' });
      const w = workingIndex(f);
      (f.chain || []).forEach((c, i) => {
        if (i) chain.createSpan({ cls: 'lb-route-arrow', text: '→' });
        const el = chain.createSpan({ cls: 'lb-route-step' + (i === w && f.on ? ' is-working' : '') + (c.free ? ' is-free' : ''), text: c.label });
        el.setAttribute('title', [c.price, c.key ? 'key：' + c.key : ''].filter(Boolean).join(' · '));
      });
      if (!(f.chain || []).length) chain.createSpan({ cls: 'lb-route-step', text: '还没配' });
      if (f.id === 'ask' && (f.choices || []).length > 1) chain.createSpan({ cls: 'lb-route-more', text: `· 问收藏页能换 ${f.choices.length} 个` });
      const cur = (f.chain || [])[w];
      head.createSpan({ cls: 'lb-route-price', text: f.on && cur ? (cur.price || '') : '' });
      const pill = head.createSpan({ cls: 'lb-route-state', text: STATE_SHORT[f.state] || f.state });
      pill.setAttribute('title', f.state_text || '');
      const body = d.createDiv({ cls: 'lb-route-body' });
      let drawn = false;
      d.addEventListener('toggle', () => {
        if (!d.open || drawn) return;
        drawn = true;
        if (!['ok', 'off'].includes(f.state) && f.state_text) body.createDiv({ cls: 'lb-route-why', text: f.state_text });
        const tg = ROUTE_TOGGLE[f.id];
        if (tg && home && home.featureToggle) {
          const row = new Setting(body).setName('打开这项').setDesc(tg[1]);
          safe(tab, body, '开关', () => home.featureToggle(row, tg[0], () => redraw()));
        }
        const draw = {
          ask: () => { tab.sectionTextAI?.(body, { heading: false }); tab.renderChatModels(body); },
          summary: () => tab.renderSummaryAI(body),
          vision: () => tab.sectionVisionAI?.(body),
          refine: () => tab.renderRefineAI(body),
          embed: () => body.createEl('p', { cls: 'setting-item-description', text: '把问题和收藏变成向量、按意思找；跟着这家的 key 走，一般不用动。每次搜索几乎不花钱。' }),
          ocr: () => tab.renderOcrAI(body),
          asr: () => tab.renderVoiceAI(body),
          capslock: () => body.createEl('p', { cls: 'setting-item-description', text: '在任何软件里按住 CapsLock 说话、松开就出字；用本机的语音识别，不联网、不花钱。' }),
        }[f.id];
        if (draw) safe(tab, body, f.name, draw);
      });
    }
  }

  function balanceText(b) {
    const parts = (b.balances || []).map(x => `${x.currency === 'USD' ? '$' : '¥'}${x.total}`);
    return '余额 ' + (parts.join(' · ') || '0') + (b.available === false ? '（不够调用了）' : '');
  }

  function paintKeyring(box, data, tab) {
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
    if (!rows.length) { box.createEl('p', { cls: 'setting-item-description', text: '还没接要 key 的 AI。不接也能存、能按关键词搜；想要概要、识图、按意思找，点上面任一行展开去填。' }); return; }
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
      if (m) money.push(`本月 ${fmtYuan(m.cost)} · ${m.calls} 次`);
      else if (r.id === 'google') money.push('免费额度，不花钱');
      if (money.length) desc.createDiv({ text: money.join(' · ') });
      const k = keys[r.id];
      if (k) desc.createDiv({ cls: 'lb-key-warn', text: (String(k.code || '').endsWith('QUOTA_EXCEEDED') ? '额度用完了' : 'key 用不了（可能欠费、过期或没开通）') + '：配了备用的会自动改用备用' });
      for (const [text, url] of [['控制台', l.console], ['充值', l.recharge], ['拿 key', l.key || l.key_url]])
        if (url) tab.link(row, text, () => openUrl(url), `在浏览器打开 ${name} 的${text}页`);
    }
  }

  function renderAI(c, tab) {
    const s = plugin.settings;
    let alive = true, data = null;
    const spend = c.createDiv({ cls: 'lb-spend', attr: { 'data-section': 'ai-spend' } });
    heading(c, '每个功能用谁', 'ai-routes');
    c.createEl('p', { cls: 'lb-sec-desc', text: '从左往右顶：前面的不行（额度用完、key 用不了、到了上限）才轮到后面的。点一行改它用哪个、调细项。' });
    const routes = c.createDiv({ cls: 'lb-routes' });
    heading(c, '钥匙串', 'ai-api');
    c.createEl('p', { cls: 'lb-sec-desc', text: '按服务商列：key 从哪来、花了多少、管哪些功能。key 在上面每一项展开里改。' });
    const ring = c.createDiv({ cls: 'lb-keyring' });
    const usageBody = fold(c, '花了多少：各功能明细（今天 / 7 天 / 30 天）', 'ai-usage');
    const promptBody = fold(c, '提示词（一般不用改）', 'ai-prompts');
    safe(tab, promptBody, '提示词', () => tab.renderPrompts(promptBody));
    const free = new Setting(c).setName('只用免费的功能').setDesc('关掉问收藏、概要和识图，只留本机跑的那几样；key 留着，随时打开。');
    free.settingEl.addClass('lb-light-row');
    tab.link(free, '全部关掉', async () => {
      if (!await plugin.confirm({ title: '关掉全部 AI？', body: '问收藏、自动概要和识图都会停；填好的密钥不删，随时打开就能接着用。', ok: '全部关掉', danger: true })) return;
      const prev = s.setup ? JSON.parse(JSON.stringify(s.setup)) : undefined;
      const sel = new Set(Array.isArray(s.setup?.selected) ? s.setup.selected : []);
      sel.delete('ai_text'); sel.delete('ai_vision');
      s.setup = { ...(s.setup || {}), selected: [...sel] };
      try { await plugin.saveSettings(); } catch (e) { s.setup = prev; plugin.notify('没保存上，原来的选择没动：' + e.message, { kind: 'error' }); }
      load();
    }, '换成轻量版：不要任何密钥');

    let usageDrawn = false;
    const usageFold = usageBody.parentElement;
    usageFold?.addEventListener?.('toggle', () => {
      if (usageDrawn || !usageFold.open) return;
      usageDrawn = true;
      safe(tab, usageBody, '用量', () => tab.stops.push(plugin.usageUI().render(usageBody.createDiv({ cls: 'lb-usage-host' }), tab, { tableOnly: true, data })));
    });
    async function load() {
      spend.empty(); routes.empty(); ring.empty();
      routes.createEl('p', { cls: 'setting-item-description lb-loading', text: '正在读每个功能用谁、花了多少…' });
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'usage'], { label: '读 AI 用量', timeoutMs: 45000, fallback: '没读出来' });
        if (!alive) return;
        if (!r.json || r.json.ok === false) throw new Error((r.json && r.json.message) || '没读出来');
        data = r.json;
        paintSpend(spend, data, tab); paintRoutes(routes, data, tab, load); paintKeyring(ring, data, tab);
      } catch (e) { if (alive) { routes.empty(); plugin.failBox?.(routes, 'AI 用量', e, () => load()); } return; }
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'usage', '--balance'], { label: '查余额', timeoutMs: 30000, fallback: '余额没查到' });
        if (!alive || !r.json || r.json.ok === false) return;
        data = { ...data, balances: r.json.balances || {}, keys: r.json.keys || data.keys };
        paintKeyring(ring, data, tab);
      } catch (e) { console.error('[lb] 余额没查到', e); }
    }
    load();
    tab.stops.push(() => { alive = false; });
  }

  // ———————————————————— 接其他 AI（1018 从「更多」里的折叠升成独立页签）————————————————————
  function renderConnect(c, tab) {
    safe(tab, c, '连接其他 AI', () => tab.stops.push(plugin.remoteUI?.renderConnect(c, () => tab.display(), tab)));
  }

  // ———————————————————— 更多：目录与批注 · 技能 · 附件 · 高级 ————————————————————
  function renderMore(c, tab) {
    const s = plugin.settings;
    heading(c, '目录与批注', 'catalog');
    new Setting(c).setName('批注署名').setDesc('你写的批注署这个名字；空着不署名。')
      .addText(t => t.setPlaceholder('我').setValue(s.nickname || '').onChange(async v => { s.nickname = v.trim(); await tab.save(); }));
    new Setting(c).setName('留言对象').setDesc('以「@名字」开头的批注标成留言给它；空着不启用。')
      .addText(t => t.setPlaceholder('不启用').setValue(s.annotateMention || '').onChange(async v => { s.annotateMention = v.trim(); await tab.save(); }));
    tab.fieldCategories(c);
    const skills = fold(c, '技能：问收藏时按问题选用的写法（菜谱、攻略…）', 'skills');
    safe(tab, skills, '技能', () => tab.renderSkillsTab(skills));
    const att = fold(c, '附件：手动下载、还没下到的', 'attach');
    tab.fieldDownloadFolder(att);
    tab.numberField(att, '等下载最多几分钟', '手动下载附件时，在下载文件夹里等文件出现多久。',
      { get: () => s.downloads.waitMinutes, set: v => s.downloads.waitMinutes = v, def: 5, unit: '分钟' });
    tab.link(new Setting(att).setName('还没下到的附件'), '查看', async () => {
      try {
        const data = plugin.catalogCache?.data || JSON.parse(await plugin.app.vault.adapter.read(plugin.lbPath('_archive/catalog-data.json')));
        plugin.openAttachments(data.items.filter(it => it.attachment === '待补'));
      } catch (e) { plugin.notify('这一块暂时读不到：' + e.message, { kind: 'error' }); }
    }, '列出还没下到附件的笔记');
    const adv = fold(c, '高级：一键装好、后端程序、检查这台电脑、重走第一次的指引', 'developer');
    const home = plugin.homeUI ? plugin.homeUI() : null;
    if (home) safe(tab, adv, '一键装好', () => tab.stops.push(home.renderRun(adv, tab)));
    safe(tab, adv, '高级', () => tab.renderDeveloperCard(adv));
    tab.link(new Setting(adv).setName('第一次的指引'), '重走一遍', () => { s.onboarding = { ...(s.onboarding || {}), force: true, step: 0 }; tab.save().then(() => tab.showTab('overview')); }, '在概览页重新走四步指引');
  }

  // ———————————————————— 第一次：四步指引（照 MAA 的设置指引：右边步骤线，左边一次一件事）————————————————————
  const STEPS = [['folder', '放在哪'], ['login', '登录小红书'], ['ai', 'AI 帮忙'], ['start', '开始同步']];
  // 指引自己记走没走完（guideDone）：onboarding.done 是启动时「按轻量版自动跑一次」记的，和指引无关
  async function needsGuide() {
    const ob = plugin.settings.onboarding || {};
    if (ob.force) return true;
    if (ob.guideDone) return false;
    try { return !(await plugin.app.vault.adapter.exists(plugin.lbPath('_archive/catalog-data.json'))); } catch { return false; }
  }

  function renderGuide(c, tab) {
    const s = plugin.settings;
    s.onboarding = s.onboarding || {};
    let step = Math.min(Math.max(+s.onboarding.step || 0, 0), STEPS.length - 1);
    const wrap = c.createDiv({ cls: 'lb-guide' });
    const left = wrap.createDiv({ cls: 'lb-guide-main' });
    const right = wrap.createDiv({ cls: 'lb-guide-steps' });
    const finish = async () => { s.onboarding = { ...s.onboarding, guideDone: true, force: false, step: 0 }; await tab.save(); tab.showTab('overview'); };
    const go = async n => { step = n; s.onboarding.step = n; await tab.save(); paint(); };
    const paint = () => {
      right.empty();
      STEPS.forEach(([, label], i) => {
        if (i) right.createDiv({ cls: 'lb-guide-line' + (i <= step ? ' is-done' : '') });
        const st = right.createDiv({ cls: 'lb-guide-step' + (i < step ? ' is-done' : i === step ? ' is-on' : '') });
        st.createSpan({ cls: 'lb-guide-dot', text: i < step ? '✓' : String(i + 1) });
        st.createSpan({ text: label });
      });
      left.empty();
      const [id] = STEPS[step];
      const title = t => left.createDiv({ cls: 'lb-guide-title', text: t });
      const hint = t => left.createEl('p', { cls: 'lb-guide-hint', text: t });
      if (id === 'folder') {
        title('收藏放在哪个文件夹？');
        hint('一般不用改，直接下一步。');
        tab.fieldCollectionFolder(left);
      } else if (id === 'login') {
        title('登录你收藏用的小红书号');
        hint('用手机扫码。登录状态只存在这台电脑上。');
        safe(tab, left, '小红书账号', () => plugin.renderAccounts(left));
      } else if (id === 'ai') {
        title('要不要 AI 帮你整理？');
        hint('不用也能存、能按关键词搜。用的话会帮你写概要、认图里的字、按意思找收藏。');
        const pick = (label, desc, fn) => { const r = new Setting(left).setName(label).setDesc(desc); r.settingEl.addClass('lb-guide-choice'); r.addButton(b => b.setButtonText('选这个').onClick(fn)); return r; };
        pick('用免费的 Gemini', '要一把 Google 的 key，每天额度够日常用。', () => { openUrl(LINKS.google.key); tab.showTab('ai'); });
        pick('用付费的（DeepSeek / 阿里云）', '按用量付费，日常每月大约几块钱。', () => tab.showTab('ai'));
        pick('先不用', '以后在「AI」页随时打开。', () => go(step + 1));
      } else {
        title('开始同步');
        hint('第一次会把以前的收藏分几天慢慢补完，像人一样读，不伤号。之后每天自动同步。');
        const home = plugin.homeUI ? plugin.homeUI() : null;   // 先把这台电脑缺的装好（读取组件、认字模型…），装好了这一块只剩一句「都装好了」
        if (home) safe(tab, left, '一键装好', () => tab.stops.push(home.renderRun(left, tab)));
        new Setting(left).setName('现在开始').addButton(b => b.setCta().setButtonText('开始同步').onClick(async () => { plugin.syncNow?.(); await finish(); }));
      }
      const nav = left.createDiv({ cls: 'lb-guide-nav' });
      const prev = nav.createEl('button', { text: '上一步' }); prev.disabled = step === 0; prev.onclick = () => go(step - 1);
      const skip = nav.createEl('button', { cls: 'lb-link', text: '跳过指引' }); skip.onclick = finish;
      if (step < STEPS.length - 1) { const next = nav.createEl('button', { cls: 'mod-cta', text: '下一步' }); next.onclick = () => go(step + 1); }
    };
    paint();
  }

  return { renderOverview, renderSync, renderAI, renderConnect, renderMore, renderGuide, needsGuide, providerRows, featureUses, attentionText, providerOf };
};

// settings-v6.js — 1018 她批的设置页 v6（设计稿 cyberlink\workdesk\20261018-lwa-settings-v6.html）。
//   一页翻完：最上面「状态」（账户 · 同步 · API 费用 · 识别 · 读取，点一行跳到下面那张卡）→ 小红书 → 识别与问答 → 知识库接入 AI → 更多。
//   第一次用：同一个位置换成首次设置——「推荐设置，一键开始」（扫码就完）或「自定义」四步（登录 · 同步 · 识别与问答 · 接入 AI），
//   走完这里就变回上面的状态页。
//   她的规矩：设置页只放用户要动的；报错只有两种在这里修（掉登录 → 原地扫码；key 欠费 / 失效 → 充值直达 / 换 key），其余在首页；
//   每行「名称 + 一句说明 + 右侧控件」，不写大段字；不需要用户动的不露面（本机认字、语音转文字只是开关）。
// 这里只排版和接线：每一行的读写、保存失败拨回仍用设置页（tab）、home-ui、remote-ui 上原有的方法。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Setting, Modal } = obsidian;
  const pages = plugin.settingsPages();
  const home = () => (plugin.homeUI ? plugin.homeUI() : null);
  const safe = (tab, c, what, fn) => (tab.safe ? tab.safe(c, what, fn) : fn());
  const openUrl = url => {
    if (!/^https:\/\//.test(url || '')) return;
    try { require('electron').shell.openExternal(url); return; } catch {}
    try { window.open(url); } catch (e) { console.error('[lb] 网页没打开', e); }
  };
  const fmtYuan = v => (v == null || !Number.isFinite(+v) ? '—' : '¥' + (+v >= 10 ? (+v).toFixed(1) : (+v).toFixed(2)));

  // —— 图标：Claudian 的官方 SVG（provider-icons.js，MIT）；Gemini、千问 Claudian 里没有 → 不画图标，只写名字 ——
  const PROV = { google: 'Gemini', deepseek: 'DeepSeek', aliyun: '通义千问', openai: 'OpenAI' };
  const icons = (() => { try { return plugin.providerIcons ? plugin.providerIcons() : null; } catch (e) { console.error('[lb] 图标没加载上', e); return null; } })();
  const iconInto = (parent, id, size) => (icons ? icons.icon(parent, id, size) : null);
  const group = (parent, text) => parent.createDiv({ cls: 'lb-grp', text });
  const meta = (row, text) => row.controlEl.createSpan({ cls: 'lb-meta', text });
  // 点一行跳到下面那张卡
  function jump(tab, section) {
    const el = tab.containerEl.querySelector(`[data-section="${section}"]`);
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
  function jumpRow(row, tab, section) {
    row.settingEl.addClass('lb-jump');
    row.addExtraButton(b => b.setIcon('chevron-right').setTooltip('去设置里改').onClick(() => jump(tab, section)));
    return row;
  }

  // —— 共用数据：用量（今天 / 本月 / 上限 / 每家 key 的状态）和本机应用，一分钟内复用 ——
  const cache = plugin.v6Cache || (plugin.v6Cache = {});
  function cached(key, ttl, load) {
    const hit = cache[key];
    if (hit && hit.promise && Date.now() - hit.at < ttl) return hit.promise;
    const promise = load().catch(e => { delete cache[key]; throw e; });
    cache[key] = { at: Date.now(), promise };
    return promise;
  }
  const loadUsage = (force = false) => {
    if (force) delete cache.usage;
    return cached('usage', 60000, async () => {
      const r = await plugin.runPy(['-m', 'link_brain', 'usage'], { label: '读 AI 用量', timeoutMs: 45000, fallback: '没读出来' });
      if (!r.json || r.json.ok === false) throw new Error((r.json && r.json.message) || '没读出来');
      return r.json;
    });
  };
  const loadApps = (force = false) => {
    if (force) delete cache.apps;
    return cached('apps', 60000, async () => {
      const r = await plugin.runPy(['-m', 'link_brain', 'connect', 'status'], { label: '本机 AI 应用', timeoutMs: 60000, fallback: '没读出来' });
      if (!r.json || r.json.ok === false) throw new Error((r.json && r.json.message) || '没读出来');
      return r.json;
    });
  };
  // 哪几家在用（按设置里配的接口认）+ 哪家的 key 出了问题
  function providersInUse(usage) {
    const by = new Map();
    for (const f of (usage && usage.features) || []) for (const c of f.chain || []) {
      if (!c.provider || c.provider === 'cli' || !PROV[c.provider]) continue;
      by.set(c.provider, true);
    }
    if (!usage) for (const u of pages.featureUses(plugin.settings)) if (PROV[u.id]) by.set(u.id, true);
    return ['google', 'deepseek', 'aliyun', 'openai'].filter(id => by.has(id));
  }
  function keyTrouble(usage) {
    const keys = (usage && usage.keys) || {};
    const out = [];
    for (const [id, k] of Object.entries(keys)) {
      if (!PROV[id]) continue;
      const quota = String(k.code || '').endsWith('QUOTA_EXCEEDED');
      out.push({ id, name: PROV[id], quota, text: `${PROV[id]} ${quota ? '额度用完或余额不足' : 'key 用不了'}` });
    }
    return out;
  }

  // ———————————————————— 粘一把 key：认出是哪家，只往空着的格子里填 ————————————————————
  const blank = v => !String(v || '').trim();
  const hasKeyRef = cfg => !!(cfg && (cfg.apiKey || cfg.keyFile || cfg.apiKeyEnv || cfg.keyPool));
  async function addKey(raw) {
    const key = String(raw || '').trim();
    if (!key) { plugin.notify('先粘贴一把 key'); return null; }
    const r = await plugin.runPy(['-m', 'link_brain', 'keys', 'detect'], { input: key + '\n', label: '认 key', timeoutMs: 40000, okCodes: [0, 1], fallback: '没认出来' });
    const j = r && r.json;
    if (!j || !j.ok) { plugin.notify((j && j.message) || '没认出来', { kind: 'error' }); return null; }
    const s = plugin.settings;
    const before = JSON.parse(JSON.stringify(Object.fromEntries(Object.keys(j.fills || {}).map(k => [k, s[k]]))));
    const filled = [];
    const NAMES = { textAI: '问收藏', summaryAI: '概要', visionAI: '看懂图片', embedAI: '按意思搜' };
    for (const [cap, sugg] of Object.entries(j.fills || {})) {
      const cfg = s[cap] || (s[cap] = {});
      const sameEndpoint = String(cfg.endpoint || '').replace(/\/+$/, '') === sugg.endpoint;
      if (blank(cfg.endpoint) || (cap === 'embedAI' && !hasKeyRef(cfg) && sameEndpoint)) {
        // 空着的一格：填地址、模型（模型空着才填）和这把 key；已经填好的地址、别的密钥引用一个不动
        Object.assign(cfg, { mode: 'http', endpoint: sugg.endpoint }, blank(cfg.model) ? { model: sugg.model } : {}, hasKeyRef(cfg) ? {} : { apiKey: key });
        filled.push(NAMES[cap] || cap);
      } else if (sameEndpoint && !hasKeyRef(cfg)) {
        cfg.apiKey = key; filled.push(NAMES[cap] || cap);   // 地址就是这家、只是还没有 key
      }
    }
    if (!filled.length) { plugin.notify(`认出是 ${j.name}：对应的几项都已经配好了，没改`, { ms: 8000 }); return j; }
    try {
      await plugin.saveSettings();
      const h = home();
      if (h && s.textAI && !blank(s.textAI.endpoint)) await h.setFeature('ai_text', true).catch(() => {});
      if (h && s.visionAI && !blank(s.visionAI.endpoint) && filled.includes('看懂图片')) await h.setFeature('ai_vision', true).catch(() => {});
    } catch (e) {
      for (const k of Object.keys(j.fills || {})) { if (before[k] === undefined) delete s[k]; else s[k] = before[k]; }
      plugin.notify('没保存上，原来的设置没动：' + ((e && e.message) || e), { kind: 'error' });
      return null;
    }
    delete cache.usage;
    plugin.notify(`认出是 ${j.name}：已用在 ${filled.join('、')}（已经配好的没动）`, { kind: 'ok', ms: 8000 });
    return j;
  }
  function keyModal(onDone) {
    const m = new Modal(plugin.app);
    m.titleEl.setText('添加 API key');
    const c = m.contentEl;
    c.createEl('p', { cls: 'setting-item-description', text: '粘贴进来，自动认出是哪家。只存在这台电脑的插件设置里。' });
    const input = c.createEl('input', { cls: 'lb-key-paste', attr: { type: 'password', placeholder: '粘贴 API key', 'aria-label': 'API key' } });
    const links = c.createDiv({ cls: 'lb-prov-links' });
    links.createSpan({ cls: 'setting-item-description', text: '还没有？去申请：' });
    for (const id of ['google', 'deepseek', 'aliyun', 'openai']) {
      const l = (pages.LINKS || {})[id];
      if (!l || !l.key) continue;
      const a = links.createEl('button', { cls: 'lb-link', text: PROV[id] + (id === 'google' ? '（有免费额度）' : '') });
      a.onclick = () => openUrl(l.key);
    }
    const row = c.createDiv({ cls: 'lb-modal-actions' });
    const ok = row.createEl('button', { cls: 'mod-cta', text: '认出并用上' });
    ok.onclick = async () => {
      ok.disabled = true; ok.setText('正在认…');
      const j = await addKey(input.value);
      ok.disabled = false; ok.setText('认出并用上');
      if (j && j.ok) { m.close(); onDone && onDone(); }
    };
    m.open();
    setTimeout(() => input.focus(), 30);
  }

  // ———————————————————— 状态（v6 顶部；首次设置走完也就是它）————————————————————
  function renderStatus(c, tab) {
    const body = tab.card(c, '状态', 's-status');
    const lamp = body.head.createSpan({ cls: 'lb-lamp is-ok', attr: { 'aria-label': '状态灯' } });
    const sync = body.head.createEl('button', { cls: 'lb-sync-now', text: '立即同步' });
    sync.onclick = async () => {
      if (plugin.running) { plugin.notify(plugin.busyText(), { kind: 'warn' }); return; }
      sync.disabled = true;
      try { await plugin.syncNow(); } catch (e) { plugin.notify(e.message, { kind: 'error' }); } finally { sync.disabled = false; paintLamp(); }
    };
    const fix = body.createDiv({ cls: 'lb-fix' });   // 黄灯那一句：只有 key 欠费 / 失效（掉登录在账户那一行原地扫码）
    safe(tab, body, '小红书账号', () => plugin.renderAccounts(body));
    safe(tab, body, '同步', () => tab.stops.push(plugin.renderSyncRow(body, { compact: true, onSchedule: () => jump(tab, 's-xhs') })));
    const cost = jumpRow(new Setting(body).setName('API 费用').setDesc('读取中…'), tab, 's-ai');
    const rec = jumpRow(new Setting(body).setName('识别').setDesc('读取中…'), tab, 's-ai');
    const reads = jumpRow(new Setting(body).setName('读取').setDesc('读取中…'), tab, 's-mcp');
    let alive = true, keyBad = false;
    tab.stops.push(() => { alive = false; });
    const h = home();
    const recLine = uses => {
      const local = [];
      if (h && h.isOn('ocr')) local.push('识图转文字');
      if (h && h.isOn('asr')) local.push('语音转文字');
      const ai = uses.map(id => PROV[id]);
      return [local.length ? '本机 ' + local.join('、') : '', ai.length ? 'AI 用 ' + ai.join('、') : '没配 AI（只用免费的本机功能）'].filter(Boolean).join(' · ');
    };

    const paintLamp = async () => {
      let state = 'ok', title = '正常';
      try {
        const { raw } = await plugin.readSyncFiles();
        if (raw && raw.state === 'running') { state = 'busy'; title = '正在同步'; }
      } catch {}
      const acct = body.querySelector?.('.lb-acct-row .lb-acct-state');
      const acctText = acct ? acct.textContent || '' : '';
      if (keyBad || (acctText && !/已登录|进行中/.test(acctText))) { state = 'warn'; title = '要你处理一件事'; }
      if (!alive) return;
      lamp.className = 'lb-lamp is-' + state;
      lamp.setAttribute('aria-label', title); lamp.setAttribute('title', title);
    };
    loadUsage().then(u => {
      if (!alive) return;
      const b = u.budget || {}, month = Object.values((u.summary || {}).month || {}).reduce((a, m) => a + (+(m && m.cost) || 0), 0);
      const cap = plugin.settings.budget && plugin.settings.budget.dailyYuan !== undefined ? +plugin.settings.budget.dailyYuan : +(b.daily_yuan ?? 3);
      cost.setDesc(`今天 ${fmtYuan(b.spent_today)} · 本月 ${fmtYuan(month)} · 每天上限 ${cap > 0 ? '¥' + cap : '不限'}` + (b.over ? ' · 今天到上限了，后台先只跑免费的' : ''));
      const uses = providersInUse(u);
      rec.setDesc(recLine(uses));
      const bad = keyTrouble(u);
      keyBad = bad.length > 0;
      fix.empty();
      for (const k of bad.slice(0, 2)) {
        const line = fix.createDiv({ cls: 'lb-fix-line' });
        line.createSpan({ text: k.text });
        const l = { ...((pages.LINKS || {})[k.id] || {}), ...((u.links || {})[k.id] || {}) };
        if (l.recharge || l.console) { const a = line.createEl('button', { cls: 'lb-link', text: l.recharge ? '去充值 ↗' : '去控制台 ↗' }); a.onclick = () => openUrl(l.recharge || l.console); }
        const ch = line.createEl('button', { cls: 'lb-link', text: '换一个 key' });
        ch.onclick = () => keyModal(() => tab.display());
      }
      paintLamp();
    }).catch(e => { if (alive) { cost.setDesc(''); plugin.failBox?.(cost.descEl, 'API 费用', e, () => { loadUsage(true); tab.display(); }); rec.setDesc(recLine(providersInUse(null))); } });
    loadApps().then(j => {
      if (!alive) return;
      const on = (j.apps || []).filter(a => a.connected).map(a => a.name);
      const web = plugin.settings.remote && plugin.settings.remote.enabled;
      reads.setDesc(on.length || web ? '已接入 ' + [...on, web ? '网页端' : ''].filter(Boolean).join(' · ') : '还没接入别的 AI 应用');
    }).catch(() => { if (alive) reads.setDesc('还没接入别的 AI 应用'); });
    if (h && !h.state().plan) h.loadPlan().then(() => { if (alive) rec.setDesc(recLine(providersInUse(cache.usageLast || null))); }).catch(() => {});
    paintLamp();
    setTimeout(() => { if (alive) paintLamp(); }, 2500);   // 账户那一行读完再看一次灯
  }

  // ———————————————————— 小红书 ————————————————————
  function renderXhs(c, tab) {
    renderXhsInto(tab.card(c, '小红书', 's-xhs'), tab);
  }

  // ———————————————————— 识别与问答（本机两项 + 用 key 的三项；设置页另有 AI 服务 · 问收藏模型 · 每天上限）————————————————————
  function aiRows(body, tab, { guide = false, onChange = null } = {}) {
    const s = plugin.settings, h = home();
    const redraw = () => { body.empty?.(); aiRows(body, tab, { guide, onChange }); onChange && onChange(); };
    // 功能清单还没读回时「开没开」都是关：读回来再画一遍（子项「按住 CapsLock 说话」要看语音转文字开没开）
    if (h && !h.state().plan) h.loadPlan().then(() => { if (h.state().plan && body.parentNode) redraw(); }).catch(() => {});
    const feat = (name, desc, id, tag) => {
      const row = new Setting(body).setName(name).setDesc(desc);
      row.settingEl.addClass('lb-feat'); row.settingEl.setAttribute?.('data-id', id);
      if (tag) meta(row, tag);
      if (h) safe(tab, body, name, () => h.featureToggle(row, id, () => { if (id === 'asr') redraw(); }));
      return row;
    };
    // 1018 晚她：一屏放得下——本机三项只写名字；要 key 的三项一句说明 + 右边「约 ¥x / 100 篇 · 哪家」
    feat('识图', '', 'ocr', '免费 · 本机');
    feat('语音', '', 'asr', '免费 · 本机');
    if (h && h.isOn('asr')) feat('按 CapsLock 转文字', '', 'capslock', '免费 · 本机');
    group(body, guide ? '需要 API key · 可跳过' : '用 API key');
    // 价钱：setup estimate（按库里平均每篇的量 × 官方单价；配了模型按配的、没配按推荐）
    const priceMeta = {};
    const SHORT = { DeepSeek: 'DeepSeek', '通义千问': '千问', 'Google Gemini': 'Gemini', OpenAI: 'OpenAI' };
    const paintPrices = est => {
      for (const it of ((est && est.data && est.data.items) || [])) {
        const el = priceMeta[it.id];
        if (!el || it.yuan == null) continue;
        const y = +it.yuan;
        el.setText(`约 ¥${y >= 1 ? y.toFixed(2) : y >= 0.01 ? y.toFixed(2) : y.toFixed(3)} / 100 篇 · ${SHORT[it.provider] || it.provider || ''}`);
      }
    };
    // 按意思搜 / 概要：各自的开关是这一项的 mode（off ↔ 原来的）；打开时顺手把「问收藏 · 概要 · 打标」那一组勾上（后台门禁看它）
    const capToggle = (name, desc, cap, onMode) => {
      const row = new Setting(body).setName(name).setDesc(desc);
      row.settingEl.addClass('lb-feat'); row.settingEl.setAttribute?.('data-cap', cap);
      const cfg = () => s[cap] || (s[cap] = {});
      row.addToggle(t => {
        let reverting = false;
        t.setValue(cfg().mode !== 'off' && (cap !== 'summaryAI' || !h || h.isOn('ai_text'))).onChange(async v => {
          if (reverting) return;
          const prev = JSON.parse(JSON.stringify(cfg()));
          if (v) { cfg().mode = cfg().prevMode || onMode; delete cfg().prevMode; }
          else { if (cfg().mode !== 'off') cfg().prevMode = cfg().mode; cfg().mode = 'off'; }
          try {
            await plugin.saveSettings();
            if (v && h) await h.setFeature('ai_text', true);
          } catch (e) {
            s[cap] = prev; reverting = true; try { t.setValue(!v); } catch {} finally { reverting = false; }
            plugin.notify('没保存上，开关已拨回原来的位置：' + ((e && e.message) || e), { kind: 'error' }); return;
          }
          delete cache.usage;
        });
      });
      return row;
    };
    priceMeta.embed = meta(capToggle('按意思搜', 'embedding 向量：搜「便宜的火锅」也能找到「人均 50 的锅子」', 'embedAI', 'http'), '');
    priceMeta.summary = meta(capToggle('概要', '当篇摘要、关联网址，方便后续搜索', 'summaryAI', 'inherit'), '');
    if (h) priceMeta.vision = meta(feat('AI 识图', 'OCR、表格、流程图更精准，还有图片描述', 'ai_vision', ''), '');
    // 价钱那一格要在开关左边
    for (const el of Object.values(priceMeta)) el.parentElement?.prepend?.(el);
    if (h) { const est = h.state().estimate; if (est && est.data) paintPrices(est); else h.loadEstimate().then(paintPrices).catch(() => {}); }
    // AI 服务：用的是哪几家（图标）+ 添加 key
    const svc = body.createDiv({ cls: 'lb-svc', attr: { 'data-section': 'ai-keys' } });
    const paintSvc = u => {
      svc.empty();
      const chips = svc.createDiv({ cls: 'lb-prov' });
      const bad = new Set(keyTrouble(u).map(k => k.id));
      for (const id of providersInUse(u)) {
        const chip = chips.createSpan({ cls: 'lb-pv' + (bad.has(id) ? ' is-warn' : ''), attr: { 'data-provider': id } });
        iconInto(chip, id, 14); chip.createSpan({ text: PROV[id] + (id === 'google' ? ' · 免费额度' : '') });
        chip.createSpan({ cls: 'lb-pv-dot' });
      }
      const add = chips.createEl('button', { cls: 'lb-pv is-add', text: '＋ 添加 key' });
      add.onclick = () => keyModal(() => tab.display());
      if (!providersInUse(u).length) svc.createDiv({ cls: 'setting-item-description', text: '粘一把 key 就能用上面三项；没有的话 Gemini 有免费额度。' });
    };
    paintSvc(null);
    loadUsage().then(u => { cache.usageLast = u; paintSvc(u); }).catch(() => {});
  }

  function renderAICard(c, tab) {
    const s = plugin.settings;
    const body = tab.card(c, '识别与问答', 's-ai');
    const rows = body.createDiv({ cls: 'lb-ai-rows' });
    aiRows(rows, tab);
    // 问收藏用的模型：问收藏页下拉里的那几个
    const models = (s.models || []).map(m => m.name).filter(Boolean);
    if (models.length) {
      const row = new Setting(body).setName('问收藏用的模型').setDesc('回答质量主要看这一项');
      row.addDropdown(d => {
        for (const n of models) d.addOption(n, n);
        d.setValue(models.includes(s.activeModel) ? s.activeModel : models[0]).onChange(async v => {
          const prev = s.activeModel; s.activeModel = v;
          try { await plugin.saveSettings(); plugin.app.workspace.trigger?.('link-brain:models-changed'); }
          catch (e) { s.activeModel = prev; d.setValue(prev); plugin.notify('没保存上：' + e.message, { kind: 'error' }); }
        });
      });
    }
    // 每天最多花（只拦后台补跑，问收藏不受限）
    const cap = new Setting(body).setName('每天最多花').setDesc('到了上限，后台只跑免费的；问收藏不受限');
    const saved = s.budget && s.budget.dailyYuan !== undefined && s.budget.dailyYuan !== '' ? +s.budget.dailyYuan : 3;
    cap.addText(t => {
      t.inputEl.type = 'number'; t.inputEl.min = '0'; t.inputEl.addClass?.('lb-num');
      t.setValue(String(Number.isFinite(saved) ? saved : 3));
      t.inputEl.addEventListener('change', async () => {
        const n = Math.max(0, Math.round(+t.inputEl.value * 100) / 100);
        if (!Number.isFinite(n)) { t.setValue(String(saved)); return; }
        const prev = s.budget ? { ...s.budget } : undefined;
        s.budget = { ...(s.budget || {}), dailyYuan: n };
        try { await plugin.saveSettings(); delete cache.usage; }
        catch (e) { s.budget = prev; t.setValue(String(saved)); plugin.notify('没保存上，已改回原来的：' + e.message, { kind: 'error' }); }
      });
    });
    meta(cap, '元 / 天，0 = 不限').addClass('lb-meta-after');
  }

  // ———————————————————— 知识库接入 AI ————————————————————
  function appRows(body, tab, { guide = false } = {}) {
    const list = body.createDiv({ cls: 'lb-apps' });
    list.createDiv({ cls: 'setting-item-description lb-loading', text: '正在看这台电脑装了哪些 AI 应用…' });
    let alive = true;
    tab.stops.push(() => { alive = false; });
    const paint = j => {
      if (!alive) return;
      list.empty();
      const apps = j.apps || [];
      if (!apps.length) list.createDiv({ cls: 'setting-item-description', text: '这台电脑上还没有能接入的 AI 应用（Claude Code、Codex、Claude 桌面版等）。装好后会出现在这里。' });
      for (const a of apps) {
        // 照 Claudian 设置页「Claude Code v2.1.302 · 自动检测」那一行：图标（右下角绿点 = 找到了）· 名字 + 版本 · 一句 · 右边开关
        const row = new Setting(list).setName(a.name);
        row.settingEl.addClass('lb-app'); row.settingEl.setAttribute?.('data-app', a.id);
        const iconBox = row.settingEl.ownerDocument.createElement('div');
        iconBox.className = 'lb-app-icon';
        iconInto(iconBox, a.id, 26);
        const dot = row.settingEl.ownerDocument.createElement('span');
        dot.className = 'lb-app-dot';
        iconBox.appendChild(dot);
        row.settingEl.insertBefore(iconBox, row.settingEl.firstChild);
        if (a.version) row.nameEl.createSpan({ cls: 'lb-app-ver', text: 'v' + a.version });
        const how = a.via === 'claudian' ? '用 Claudian 里设的路径' : '自动检测';
        if (a.oneclick) {
          row.setDesc(a.connected ? '已接入' : how);
          row.addToggle(t => {
            let busy = false;
            t.setValue(!!a.connected).onChange(async on => {
              if (busy) return;
              busy = true; row.setDesc(on ? '正在接入…' : '正在断开…');
              let res = null;
              try { const r = await plugin.runPy(['-m', 'link_brain', 'connect', on ? 'add' : 'remove', a.id], { label: '接入 AI', timeoutMs: 120000, okCodes: [0, 1] }); res = r.json || {}; }
              catch (e) { res = { ok: false, message: e.message }; }
              if (res.ok) {
                a.connected = on;
                row.setDesc(on ? '已接入' : how);
                plugin.notify(res.message || (on ? '已接入' : '已断开'), { kind: 'ok', ms: 8000 });
              } else {
                try { t.setValue(!on); } catch {}
                row.setDesc((res.message || '没做成') + (res.command ? '' : ''));
                if (res.command) tab.link(row, '复制命令', () => plugin.copyText(res.command), '复制到终端自己运行');
              }
              delete cache.apps;
              busy = false;
            });
          });
        } else {
          row.setDesc(how + ' · 复制设置，粘进它的 MCP 设置');
          tab.link(row, '复制设置', () => plugin.copyText(j.json || ''), '复制 MCP 设置（JSON）');
        }
      }
      // 别的能接 MCP 的软件（Cursor 之类，上面认不出来的）：复制设置自己粘
      if (!guide) {
        const other = new Setting(list).setName('其他应用').setDesc('Cursor 等支持 MCP 的软件：复制设置，粘进它的 MCP 设置');
        other.settingEl.addClass('lb-app'); other.settingEl.setAttribute?.('data-app', 'other');
        tab.link(other, '复制设置', () => plugin.copyText(j.json || ''), '复制 MCP 设置（JSON）');
      }
      const miss = j.not_installed || [];
      if (miss.length && !guide) list.createDiv({ cls: 'lb-note', text: miss.join('、') + ' 没装，装好后会出现在这里。' });
    };
    loadApps().then(paint).catch(e => { if (alive) { list.empty(); plugin.failBox?.(list, '本机 AI 应用', e, () => { loadApps(true); tab.display(); }); } });
  }

  // 网页端（ChatGPT、claude.ai、手机）：一键复制接入说明——连接地址 + 两家各几步 + 口令在哪（口令本身不进剪贴板）
  function webGuideText() {
    const r = plugin.settings.remote || {};
    const url = r.domain ? r.domain.replace(/\/+$/, '') + '/mcp' : '';
    return ['LWA 收藏库（MCP，只读：能搜、能读、能看图，不能改也不能删）',
      '连接地址：' + (url || '还没填域名——先在 LWA 设置「知识库接入 AI → 网页端」里填你的域名'),
      '',
      'ChatGPT：设置 → Apps & Connectors → Advanced settings 打开 Developer mode → Create，名字填 LWA，URL 粘上面的连接地址，认证选 OAuth。',
      'claude.ai（网页 / 手机 App）：设置 → Connectors → Add custom connector，名字填 LWA，URL 粘上面的连接地址。',
      '第一次连接会打开 LWA 的授权页：输入 LWA 设置里的口令，点「允许连接」就好。',
      '用的时候说「在我的收藏里搜……」。'].join('\n');
  }
  function webRow(body, tab, { guide = false } = {}) {
    const r = plugin.settings.remote || {};
    const row = new Setting(body).setName('ChatGPT、claude.ai 网页版和手机')
      .setDesc(r.domain ? '复制接入说明，照着在网页版里加一个连接器' : guide ? '要先有域名：走完后在设置「知识库接入 AI」里填，再复制接入说明' : '先在下面填好域名，再复制接入说明');
    row.settingEl.addClass('lb-web-row');
    tab.link(row, '复制接入说明', () => plugin.copyText(webGuideText()), '复制连接地址和接入步骤（不含口令）');
    return row;
  }

  function renderConnectCard(c, tab) {
    const body = tab.card(c, '知识库接入 AI', 's-mcp', { desc: '接入后，在这些应用里能搜索和阅读你的收藏。只读，不会修改或删除，随时可以断开。' });
    body.head.createSpan({ cls: 'lb-card-hint', text: '只读' });
    group(body, '本地应用');
    appRows(body, tab);
    // 可以读取的范围（对所有接入的 AI 都一样）
    const r = plugin.settings.remote || {};
    const folders = Array.isArray(r.folders) ? r.folders : [];
    const scope = body.createEl('details', { cls: 'lb-row-fold', attr: { 'data-section': 'mcp-folders' } });
    const sum = scope.createEl('summary');
    sum.createDiv({ cls: 'lb-rf-name', text: '可以读取的范围' });
    sum.createDiv({ cls: 'lb-rf-desc', text: folders.length ? folders.map(f => (f === '@xhs' ? '小红书收藏库' : f.split(/[\\/]/).pop() || f)).join(' · ') : '小红书收藏库' });
    let scopeDrawn = false;
    scope.addEventListener('toggle', () => {
      if (!scope.open || scopeDrawn) return; scopeDrawn = true;
      safe(tab, scope, '开放的文件夹', () => tab.stops.push(plugin.remoteUI?.renderConnect(scope.createDiv(), () => tab.display(), tab, { part: 'folders' })));
    });
    group(body, '网页端 · 要你自己的域名');
    webRow(body, tab);
    const web = body.createEl('details', { cls: 'lb-row-fold', attr: { 'data-section': 'remote' } });
    const ws = web.createEl('summary');
    ws.createDiv({ cls: 'lb-rf-name', text: '域名、口令、已连上的' });
    ws.createDiv({ cls: 'lb-rf-desc', text: r.enabled ? '远程访问开着' + (r.domain ? ' · ' + r.domain : '') : '远程访问没开' });
    let webDrawn = false;
    const fillWeb = () => {
      if (!web.open || webDrawn) return; webDrawn = true;
      safe(tab, web, '网页端', () => tab.stops.push(plugin.remoteUI?.renderConnect(web.createDiv(), () => tab.display(), tab, { part: 'web' })));
    };
    web.addEventListener('toggle', fillWeb);
    if (tab.view && tab.view().openRemote) { web.open = true; tab.view().openRemote = false; fillWeb(); }
  }

  // ———————————————————— 更多：每一项一行，点开在原地展开 ————————————————————
  function renderMoreCard(c, tab) {
    const s = plugin.settings, so = s.sync;
    const body = tab.card(c, '更多', 's-more');
    body.head.createSpan({ cls: 'lb-card-hint', text: '不动也能用' });
    const item = (name, desc, section, draw) => {
      const d = body.createEl('details', { cls: 'lb-row-fold', attr: { 'data-section': section } });
      const sm = d.createEl('summary');
      sm.createDiv({ cls: 'lb-rf-name', text: name });
      if (desc) sm.setAttribute('title', desc);   // 1018 晚她：更多这里线太多、字太多——只留名字，说明放悬停
      const inner = d.createDiv({ cls: 'lb-rf-body' });
      let drawn = false;
      d.addEventListener('toggle', () => { if (!d.open || drawn) return; drawn = true; safe(tab, inner, name, () => draw(inner)); });
      return d;
    };
    item('批注署名', '你的批注署什么名字；「@名字」开头的标成留言', 'catalog', b => {
      new Setting(b).setName('批注署名').setDesc('空着不署名')
        .addText(t => t.setPlaceholder('我').setValue(s.nickname || '').onChange(async v => { s.nickname = v.trim(); await tab.save(); }));
      new Setting(b).setName('留言对象').setDesc('以「@名字」开头的批注标成留言给它；空着不启用')
        .addText(t => t.setPlaceholder('不启用').setValue(s.annotateMention || '').onChange(async v => { s.annotateMention = v.trim(); await tab.save(); }));
    });
    item('每项功能用哪个模型', '谁在干活、备用顺序、每家 key 和花费明细', 'ai-more', b => pages.renderAI(b, tab, { noPrompts: true }));
    item('回答长度与提示词', '', 'ai-prompts', b => tab.renderPrompts(b));
    item('目录与写法', '分类目录；问收藏按问题选的写法（Skill）', 'skills', b => { tab.fieldCategories(b); tab.renderSkillsTab(b); });
    item('同步细项', '收藏放在哪、存不存图片、每次多少篇、补评论节奏', 'sync-more', b => {
      tab.fieldCollectionFolder(b);
      tab.toggleRow(b, '存图片', '关掉只存文字和图片地址', () => so.downloadImages, v => { so.downloadImages = v; });
      tab.toggleRow(b, '登录后马上同步', '第一次扫码登录成功后就开始', () => so.autoAfterLogin, v => { so.autoAfterLogin = v; });
      tab.fieldPerRunLimit(b); tab.fieldFillPace(b);
    });
    item('附件', '手动下载、还没下到的', 'attach', b => {
      tab.fieldDownloadFolder(b);
      tab.numberField(b, '等下载最多几分钟', '手动下载附件时，在下载文件夹里等文件出现多久',
        { get: () => s.downloads.waitMinutes, set: v => s.downloads.waitMinutes = v, def: 5, unit: '分钟' });
      tab.link(new Setting(b).setName('还没下到的附件'), '查看', async () => {
        try {
          const data = plugin.catalogCache?.data || JSON.parse(await plugin.app.vault.adapter.read(plugin.lbPath('_archive/catalog-data.json')));
          plugin.openAttachments(data.items.filter(it => it.attachment === '待补'));
        } catch (e) { plugin.notify('这一块暂时读不到：' + e.message, { kind: 'error' }); }
      }, '列出还没下到附件的笔记');
    });
    item('这台电脑', '组件装没装齐、一键装好 / 跑完、后端程序', 'developer', b => {
      const h = home();
      if (h) { tab.stops.push(h.renderStatus(b, tab, { machineOnly: true })); tab.stops.push(h.renderRun(b, tab)); }
      tab.renderDeveloperCard(b);
    });
    const again = new Setting(body).setName('重新走一遍首次设置');
    again.settingEl.addClass('lb-more-row');
    tab.link(again, '开始', async () => { s.onboarding = { ...(s.onboarding || {}), force: true, guideDone: false, step: 0 }; await tab.save(); tab.display(); try { tab.containerEl.scrollTop = 0; } catch {} }, '回到首次设置');
  }

  // ———————————————————— 一页 ————————————————————
  function renderPage(c, tab) {
    renderStatus(c, tab);
    renderXhs(c, tab);
    renderAICard(c, tab);
    renderConnectCard(c, tab);
    renderMoreCard(c, tab);
  }

  // ———————————————————— 首次设置 ————————————————————
  const STEPS = [['login', '登录小红书'], ['sync', '同步'], ['ai', '识别与问答'], ['connect', '接入其他 AI']];
  async function needsGuide() {
    const ob = plugin.settings.onboarding || {};
    if (ob.force) return true;
    if (ob.guideDone) return false;
    try { return !(await plugin.app.vault.adapter.exists(plugin.lbPath('_archive/catalog-data.json'))); } catch { return false; }
  }
  function renderGuide(c, tab) {
    const s = plugin.settings;
    s.onboarding = s.onboarding || {};
    let step = Math.min(Math.max(+s.onboarding.step || 0, 0), STEPS.length);   // 0 = 欢迎页，1..4 = 四步
    const quick = () => s.onboarding.mode === 'quick';
    const wrap = c.createDiv({ cls: 'lb-guide' });
    const left = wrap.createDiv({ cls: 'lb-guide-main' });
    const right = wrap.createDiv({ cls: 'lb-guide-steps' });
    const finish = async (run = true) => {
      s.onboarding = { ...s.onboarding, guideDone: true, force: false, step: 0 };
      const h = home();
      try { if (quick() && h) await h.applyPreset('recommended'); } catch (e) { console.error('[lb] 推荐设置没用上', e); }
      await tab.save();
      tab.display();
      try { tab.containerEl.scrollTop = 0; } catch {}
      // 装好打开的功能 + 同步 + 补处理一口气跑完（进度在状态页和底部状态栏）
      if (run && h) h.runAll({ quiet: false }).catch(e => console.error('[lb] 首次跑没跑完', e));
    };
    const go = async n => { step = n; s.onboarding.step = n; await tab.save(); paint(); };
    const paint = () => {
      right.empty();
      right.toggleClass?.('is-hidden', step === 0);
      STEPS.forEach(([, label], i) => {
        const k = i + 1;
        if (i) right.createDiv({ cls: 'lb-guide-line' + (k <= step ? ' is-done' : '') });
        const st = right.createDiv({ cls: 'lb-guide-step' + (k < step ? ' is-done' : k === step ? ' is-on' : '') });
        st.createSpan({ text: label });
        st.createSpan({ cls: 'lb-guide-dot', text: k < step ? '✓' : String(k) });
        st.onclick = () => { if (k <= step || s.onboarding.mode === 'custom') go(k); };
      });
      left.empty();
      const card = left.createDiv({ cls: 'lb-card lb-guide-card' });
      const head = card.createDiv({ cls: 'lb-card-head' });
      const body = card.createDiv({ cls: 'lb-card-body' });
      const title = (t, hint) => { head.createDiv({ cls: 'lb-card-title', text: t }); if (hint) head.createSpan({ cls: 'lb-card-hint', text: hint }); };
      const nav = () => {
        const n = card.createDiv({ cls: 'lb-guide-nav' });
        const last = step === STEPS.length || (quick() && step === 1);
        const next = n.createEl('button', { cls: 'mod-cta', text: last ? '完成' : '下一步' });
        next.onclick = () => (last ? finish() : go(step + 1));
        if (step > 1) n.createEl('button', { text: '上一步' }).onclick = () => go(step - 1);
        const out = n.createEl('button', { cls: 'lb-link lb-push', text: '以后再说' });
        out.onclick = () => finish(false);   // 以后再说：只记走完，不替她开跑
      };
      const id = step ? STEPS[step - 1][0] : 'welcome';
      if (id === 'welcome') {
        title('开始使用 LWA');
        body.createEl('p', { cls: 'lb-guide-hint', text: '把小红书收藏存进这个库，图片、视频里的字都能搜，AI 能帮你翻。' });
        const big = (cls, name, desc, mode) => {
          const b = body.createEl('button', { cls: 'lb-big ' + cls });
          b.createDiv({ cls: 'lb-big-name', text: name }); b.createDiv({ cls: 'lb-big-desc', text: desc });
          b.onclick = async () => { s.onboarding.mode = mode; await go(1); };
        };
        big('is-pri', '推荐设置，一键开始', '扫码登录后按推荐值配好，之后都能在设置里改', 'quick');
        big('', '自定义', '四步，每一步都已填好推荐值', 'custom');
        return;
      }
      if (id === 'login') {
        title('登录小红书', quick() ? '扫完就好' : '第 1 步');
        body.createEl('p', { cls: 'lb-guide-hint', text: '用小红书 App 扫码。登录后马上开始收你最近的收藏；登录状态只存在这台电脑上。' });
        safe(tab, body, '小红书账号', () => plugin.renderAccounts(body));
      } else if (id === 'sync') {
        title('同步', '不改就用推荐值');
        renderXhsInto(body, tab);
      } else if (id === 'ai') {
        title('识别与问答', '本机两项免费，其余需要 key');
        aiRows(body, tab, { guide: true });
      } else {
        title('接入其他 AI（MCP）', '只读 · 可跳过');
        body.createEl('p', { cls: 'lb-guide-hint', text: '通过 MCP 把收藏库接给这些应用：在里面就能搜索、阅读你的收藏。只读，不会修改或删除，随时可以断开。' });
        group(body, '本地应用 · 不用域名');
        appRows(body, tab, { guide: true });
        group(body, '网页端 · 要你自己的域名');
        webRow(body, tab, { guide: true });
      }
      nav();
    };
    paint();
  }
  // 引导里的「同步」一步：和设置页小红书卡同样几行（不再套一层卡片）
  function renderXhsInto(body, tab) {
    const so = plugin.settings.sync;
    const row = new Setting(body).setName('自动同步时间').setDesc('电脑开着就会同步，不用开 Obsidian');
    row.settingEl.addClass('lb-sched-row');
    safe(tab, body, '自动同步', () => { const ed = plugin.scheduleUI().render(body.createDiv({ cls: 'lb-sched-host' }), { primary: false }); tab.stops.push(() => ed.destroy()); });
    tab.fieldDailyLimit(body);
    tab.fieldCommentFloors(body);
    tab.toggleRow(body, '保存视频', '关掉只存封面和链接，省硬盘', () => so.downloadVideo, v => { so.downloadVideo = v; });
  }

  return { renderPage, renderGuide, needsGuide, renderStatus, renderXhs, renderAICard, renderConnectCard, renderMoreCard, addKey, keyModal, STEPS, PROV };
};

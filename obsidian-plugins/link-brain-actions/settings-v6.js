// settings-v6.js — 1018 她批的设置页 v6（设计稿 cyberlink\workdesk\20261018-lwa-settings-v6.html）。
//   1026（录屏场景 08）按要做的事排：最上面「状态」（账户 · 同步 · API 费用 · 识别 · 读取；整行能点，落到能改的那个控件上、闪一下）→
//   ① 收藏与同步 ② 内容、目录及管理 ③ 识别与问答 ④ 模型与费用 ⑤ 外部 AI 接入 ⑥ 高级 / 修复。
//   常用的平铺；识别模型、提示词、调度节奏、令牌这些技术细项收进各组自己的「高级」折叠，不再一股脑扔进「更多」。
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
  const SYNC_TIME = 'sync-time';   // 唯一的自动同步时间编辑器的落点（plugin.openSyncTime() / openSetupPage('sync-time' | 'schedule')）
  const fmtYuan = v => (v == null || !Number.isFinite(+v) ? '—' : '¥' + (+v >= 10 ? (+v).toFixed(1) : (+v).toFixed(2)));

  // —— 图标：Claudian 的官方 SVG（provider-icons.js，MIT）；Gemini、千问 Claudian 里没有 → 不画图标，只写名字 ——
  const PROV = { google: 'Gemini', deepseek: 'DeepSeek', aliyun: '通义千问', openai: 'OpenAI' };
  const icons = (() => { try { return plugin.providerIcons ? plugin.providerIcons() : null; } catch (e) { console.error('[lb] 图标没加载上', e); return null; } })();
  const iconInto = (parent, id, size) => (icons ? icons.icon(parent, id, size) : null);
  const group = (parent, text) => parent.createDiv({ cls: 'lb-grp', text });
  const meta = (row, text) => row.controlEl.createSpan({ cls: 'lb-meta', text });
  // 1026 她（录屏 23:23「很奇怪的跳转」、23:34「点了没有反应」）：状态行跳过去要落在**能改的那个控件**上，不是卡片顶；
  // 整行都能点（以前只有右边那个小箭头能点，点字没反应）；落地后那一块闪一下、焦点放进第一个输入框，找不到就说一句。
  // 落点在收着的折叠里：一层层打开（toggle 里懒画的那块就画出来），再滚。返回落到的元素（测试用）。
  function focusSection(tab, section, { quiet = false } = {}) {
    const root = tab && tab.containerEl;
    const el = root && root.querySelector(`[data-section="${section}"]`);
    if (!el) { if (!quiet) plugin.notify('这一项还没画出来，稍等一下再点', { kind: 'warn' }); return null; }
    for (let n = el; n && n !== root; n = n.parentNode) {
      if (n.tagName === 'DETAILS' && !n.open) { try { n.open = true; } catch {} }
    }
    const land = () => {
      try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch { try { el.scrollIntoView(); } catch {} }
      el.addClass?.('lb-flash');
      setTimeout(() => { try { el.removeClass?.('lb-flash'); } catch {} }, 1600);
      const ctl = [...(el.querySelectorAll?.('input, select, textarea') || [])].find(x => x.getAttribute?.('type') !== 'hidden');
      if (ctl && typeof ctl.focus === 'function') { try { ctl.focus({ preventScroll: true }); } catch {} }
    };
    land();
    setTimeout(() => { if (el.isConnected !== false) land(); }, 120);
    if (el.lbReady && typeof el.lbReady.then === 'function') el.lbReady.then(() => land(), () => {});   // 编辑器读完现在的定时再落一次（输入框这时才在）   // 折叠刚打开、里面后画的块把位置顶下去：再对一次
    return el;
  }
  const jump = (tab, section) => focusSection(tab, section);
  function jumpRow(row, tab, section, tip = '去改') {
    row.settingEl.addClass('lb-jump');
    row.settingEl.setAttribute?.('data-jump', section);
    row.settingEl.setAttribute?.('role', 'button');
    row.settingEl.setAttribute?.('tabindex', '0');
    row.settingEl.setAttribute?.('aria-label', `${row.nameEl.textContent || ''}：${tip}`);
    const go = ev => { if (ev && ev.target && ev.target.closest?.('button, a, input, select, .lb-link, .extra-setting-button')) return; jump(tab, section); };
    row.settingEl.onclick = go;
    row.settingEl.onkeydown = ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault?.(); jump(tab, section); } };
    row.addExtraButton(b => b.setIcon('chevron-right').setTooltip(tip).onClick(() => jump(tab, section)));
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
  // 哪几家在用（后端 ai_routes 每一格给的 provider；没读到用量时不猜）+ 哪家的 key 出了问题
  function providersInUse(usage) {
    if (!usage) return null;
    const by = new Map();
    for (const f of (usage && usage.features) || []) for (const c of f.chain || []) {
      if (!c.provider || c.provider === 'cli' || !PROV[c.provider]) continue;
      by.set(c.provider, true);
    }
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
    // 「改时间」直接落在自动同步时间那个编辑器上（和首页齿轮、首次设置、同步记录「改定时」是同一个，见 syncTimeEditor）
    safe(tab, body, '同步', () => tab.stops.push(plugin.renderSyncRow(body, { compact: true, onSchedule: () => jump(tab, SYNC_TIME) })));
    const cost = jumpRow(new Setting(body).setName('API 费用').setDesc('读取中…'), tab, 'ai-spend', '去看花费、改每天上限');
    const rec = jumpRow(new Setting(body).setName('识别').setDesc('读取中…'), tab, 'ai-feats', '去开关识别功能');
    const reads = jumpRow(new Setting(body).setName('读取').setDesc('读取中…'), tab, 'mcp-apps', '去接入其他 AI');
    let alive = true, keyBad = false;
    tab.stops.push(() => { alive = false; });
    const h = home();
    const recLine = uses => {
      const local = [];
      if (h && h.isOn('ocr')) local.push('识图转文字');
      if (h && h.isOn('asr')) local.push('语音转文字');
      const ai = (uses || []).map(id => PROV[id]);
      const aiText = uses == null ? 'AI 用哪家还没读到' : ai.length ? 'AI 用 ' + ai.join('、') : '没配 AI（只用免费的本机功能）';
      return [local.length ? '本机 ' + local.join('、') : '', aiText].filter(Boolean).join(' · ');
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
      // 默认上限只在后端（budget.DEFAULT_YUAN）：status 给的 daily_yuan 已经是「存过的值或默认」
      const cap = plugin.settings.budget && plugin.settings.budget.dailyYuan !== undefined && plugin.settings.budget.dailyYuan !== '' ? +plugin.settings.budget.dailyYuan : +b.daily_yuan;
      const capText = !Number.isFinite(cap) ? '—' : cap > 0 ? '¥' + cap : '不限';
      const unpriced = Object.values((u.summary || {}).month || {}).reduce((a, m) => a + (+(m && m.unpriced) || 0), 0);
      cost.setDesc(`今天 ${fmtYuan(b.spent_today)} · 本月 ${fmtYuan(month)}${unpriced ? `（另有 ${unpriced} 次未计价）` : ''} · 每天上限 ${capText}` + (b.over ? ' · 今天到上限了，后台先只跑免费的' : ''));
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

  // ———————————————————— ① 收藏与同步 ————————————————————
  // 常用的平铺（自动同步时间 · 每天多少篇 · 评论楼层 · 存视频 / 图片 · 同步记录）；调度节奏、放在哪这些技术细项收进本组「高级」
  function renderXhs(c, tab) {
    const so = plugin.settings.sync;
    const body = tab.card(c, '收藏与同步', 's-xhs');
    renderXhsInto(body, tab);
    tab.toggleRow(body, '存图片', '关掉只存文字和图片地址', () => so.downloadImages, v => { so.downloadImages = v; });
    const log = new Setting(body).setName('同步记录').setDesc('每次同步收了几篇、哪里没做成');
    tab.link(log, '打开', () => plugin.openSyncLog?.(), '打开同步记录');
    advFold(body, tab, '高级：放在哪、每次多少篇、补评论节奏', 'sync-more', b => {
      tab.fieldCollectionFolder(b);
      tab.toggleRow(b, '登录后马上同步', '第一次扫码登录成功后就开始', () => so.autoAfterLogin, v => { so.autoAfterLogin = v; });
      tab.fieldPerRunLimit(b); tab.fieldFillPace(b);
    });
  }
  // 每组的「高级」：一行折叠，点开才画（技术细项：识别模型、提示词、调度节奏、令牌…）
  function advFold(body, tab, name, section, draw, { desc = '' } = {}) {
    const d = body.createEl('details', { cls: 'lb-row-fold lb-adv', attr: { 'data-section': section } });
    const sm = d.createEl('summary');
    sm.createDiv({ cls: 'lb-rf-name', text: name });
    if (desc) sm.setAttribute('title', desc);
    const inner = d.createDiv({ cls: 'lb-rf-body' });
    let drawn = false;
    d.addEventListener('toggle', () => { if (!d.open || drawn) return; drawn = true; safe(tab, inner, name, () => draw(inner)); });
    return d;
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
      const inUse = providersInUse(u) || [];
      for (const id of inUse) {
        const chip = chips.createSpan({ cls: 'lb-pv' + (bad.has(id) ? ' is-warn' : ''), attr: { 'data-provider': id } });
        iconInto(chip, id, 14); chip.createSpan({ text: PROV[id] + (id === 'google' ? ' · 免费额度' : '') });
        chip.createSpan({ cls: 'lb-pv-dot' });
      }
      const add = chips.createEl('button', { cls: 'lb-pv is-add', text: '＋ 添加 key' });
      add.onclick = () => keyModal(() => tab.display());
      if (u && !inUse.length) svc.createDiv({ cls: 'setting-item-description', text: '粘一把 key 就能用上面三项；没有的话 Gemini 有免费额度。' });
    };
    paintSvc(null);
    loadUsage().then(u => { cache.usageLast = u; paintSvc(u); }).catch(() => {});
  }

  // ———————————————————— ③ 识别与问答 ————————————————————
  function renderAICard(c, tab) {
    const s = plugin.settings;
    const body = tab.card(c, '识别与问答', 's-ai');
    const rows = body.createDiv({ cls: 'lb-ai-rows', attr: { 'data-section': 'ai-feats' } });
    aiRows(rows, tab);
    // 问收藏用的模型：问收藏页下拉里的那几个
    const models = (s.models || []).map(m => m.name).filter(Boolean);
    if (models.length) {
      const row = new Setting(body).setName('问收藏用的模型').setDesc('回答质量主要看这一项');
      row.settingEl.setAttribute?.('data-section', 'ask-model');
      row.addDropdown(d => {
        for (const n of models) d.addOption(n, n);
        d.setValue(models.includes(s.activeModel) ? s.activeModel : models[0]).onChange(async v => {
          const prev = s.activeModel; s.activeModel = v;
          try { await plugin.saveSettings(); plugin.app.workspace.trigger?.('link-brain:models-changed'); }
          catch (e) { s.activeModel = prev; d.setValue(prev); plugin.notify('没保存上：' + e.message, { kind: 'error' }); }
        });
      });
    }
    // 本组高级：提示词（每项功能用哪个模型、key、花费、每天上限在「模型与费用」）
    advFold(body, tab, '高级：回答长度与提示词', 'ai-prompts', b => tab.renderPrompts(b));
  }

  // ———————————————————— ④ 模型与费用 ————————————————————
  // 今天 / 本月 / 每天上限（唯一的上限输入框）→ 每个功能用谁（点开一行 = 这一项的模型细项）→ 钥匙串 →
  // 花了多少（按服务商 / 按 API 或模型 / 按功能切换，人民币；免费的写「免费 / 未计费」；查不到价的列「未计价」；每次调用一行可追溯）
  function renderCostCard(c, tab) {
    const body = tab.card(c, '模型与费用', 's-cost');
    body.head.createSpan({ cls: 'lb-card-hint', text: '人民币 · 按价格表估算' });
    safe(tab, body, '模型与费用', () => pages.renderAI(body, tab, { noPrompts: true, inlineUsage: true, load: force => loadUsage(!!force) }));
  }

  // ———————————————————— 知识库接入 AI ————————————————————
  function appRows(body, tab, { guide = false } = {}) {
    const list = body.createDiv({ cls: 'lb-apps', attr: { 'data-section': 'mcp-apps' } });
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
  // 网页端接入步骤（1018 她照 ChatGPT 现在的界面核过：设置 → 插件 → 浏览目录 → 右上角「添加」→「添加自定义 MCP 服务器」）。
  // 设置页里展开就能照着做，也能一键复制（口令本身不进剪贴板，授权页上再输）
  function webSteps() {
    const r = plugin.settings.remote || {};
    const url = r.domain ? r.domain.replace(/\/+$/, '') + '/mcp' : '';
    return {
      url,
      chatgpt: ['打开 ChatGPT 设置 → 左边「插件」→ 右上角「浏览目录」',
        '右上角「添加」→「添加自定义 MCP 服务器」',
        '名称随便填（比如 LWA）；连接选「服务器 URL」，粘上面的连接地址；身份验证选 OAuth',
        '勾上「我已了解，并希望继续」→「创建为插件」',
        '会跳到 LWA 的授权页：输入口令（在下面「域名、口令、已连上的」里复制），点「允许连接」就连上了'],
      claude: ['打开 claude.ai 设置 → Connectors →「Add custom connector」',
        '名字随便填，URL 粘上面的连接地址 →「Add」',
        '点「Connect」跳到 LWA 的授权页：输入口令，点「允许连接」'],
    };
  }
  function webGuideText() {
    const w = webSteps();
    const list = a => a.map((x, k) => `${k + 1}. ${x}`).join('\n');
    return ['LWA 收藏库（MCP，只读：能搜、能读、能看图，不能改也不能删）',
      '连接地址：' + (w.url || '还没填域名——先在 LWA 设置「外部 AI 接入 → 接入网页端」里填你的域名'),
      '', 'ChatGPT：', list(w.chatgpt), '', 'claude.ai（网页 / 手机 App）：', list(w.claude), '',
      '用的时候说「在我的收藏里搜……」。'].join('\n');
  }
  function webRow(body, tab, { guide = false } = {}) {
    const w = webSteps();
    const d = body.createEl('details', { cls: 'lb-row-fold lb-web-row', attr: { 'data-section': 'web-howto' } });
    const sm = d.createEl('summary');
    sm.createDiv({ cls: 'lb-rf-name', text: 'ChatGPT、claude.ai 网页版和手机' });
    sm.createDiv({ cls: 'lb-rf-desc', text: w.url ? '点开看怎么接；也能一键复制步骤' : guide ? '要先有域名：走完后在设置「外部 AI 接入」里填' : '先在下面填好域名' });
    const copy = sm.createEl('button', { cls: 'lb-link lb-rf-act', text: '复制接入说明' });
    copy.setAttribute('aria-label', '复制连接地址和接入步骤（不含口令）');
    copy.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); plugin.copyText(webGuideText()); };
    const inner = d.createDiv({ cls: 'lb-web-howto' });
    const addr = inner.createDiv({ cls: 'lb-web-addr' });
    addr.createSpan({ cls: 'lb-web-label', text: '连接地址' });
    addr.createEl('code', { text: w.url || '还没填域名' });
    if (w.url) { const b = addr.createEl('button', { cls: 'lb-link', text: '复制' }); b.onclick = () => plugin.copyText(w.url); }
    for (const [name, steps] of [['ChatGPT', w.chatgpt], ['claude.ai（网页 / 手机 App）', w.claude]]) {
      inner.createDiv({ cls: 'lb-web-label', text: name });
      const ol = inner.createEl('ol');
      for (const s of steps) ol.createEl('li', { text: s });
    }
    return d;
  }

  // ———————————————————— ⑤ 外部 AI 接入 ————————————————————
  // 1026 她（录屏 23:59「可以读取范围」）：按要做的事排——接入电脑端 · 接入网页端 · 可读取哪些库；接入说明、口令 / 访问令牌紧挨着各自那一段；
  // 开没开在卡片标题右边一眼看得到（电脑端接了几个 · 网页端开没开）。
  function mcpStateText(apps, r) {
    const n = apps == null ? null : apps.filter(a => a.connected).length;
    return ['只读', n == null ? '' : n ? `电脑端已接入 ${n} 个` : '电脑端没接', r.enabled ? '网页端开着' : '网页端没开'].filter(Boolean).join(' · ');
  }
  function renderConnectCard(c, tab) {
    const body = tab.card(c, '外部 AI 接入', 's-mcp', { desc: '接入后，在这些应用里能搜索和阅读你的收藏。只读，不会修改或删除，随时可以断开。' });
    const r = plugin.settings.remote || {};
    const state = body.head.createSpan({ cls: 'lb-card-hint lb-mcp-state', text: mcpStateText(null, r) });
    let alive = true;
    tab.stops.push(() => { alive = false; });
    loadApps().then(j => { if (alive) state.setText(mcpStateText(j.apps || [], r)); }).catch(() => {});
    group(body, '接入电脑端 · 不用域名');
    appRows(body, tab);
    group(body, '接入网页端 · ' + (r.enabled ? '远程访问开着' + (r.domain ? '（' + r.domain + '）' : '') : '要你自己的域名；远程访问没开'));
    webRow(body, tab);
    // 域名、口令、已连上的：紧挨着接入说明（授权页要输的口令就在这里复制；给不支持口令的软件的访问令牌在它里面的「高级」——1010 她：新手面上只讲口令）
    const web = body.createEl('details', { cls: 'lb-row-fold', attr: { 'data-section': 'remote' } });
    const ws = web.createEl('summary');
    ws.createDiv({ cls: 'lb-rf-name', text: '域名、口令、已连上的' });
    ws.createDiv({ cls: 'lb-rf-desc', text: r.enabled ? '远程访问开着' + (r.domain ? ' · ' + r.domain : '') + ' · 已连上的在里面' : '远程访问没开：在这里填域名、打开' });
    let webDrawn = false;
    const fillWeb = () => {
      if (!web.open || webDrawn) return; webDrawn = true;
      safe(tab, web, '网页端', () => tab.stops.push(plugin.remoteUI?.renderConnect(web.createDiv(), () => tab.display(), tab, { part: 'web' })));
    };
    web.addEventListener('toggle', fillWeb);
    if (tab.view && tab.view().openRemote) { web.open = true; tab.view().openRemote = false; fillWeb(); }
    // 可以读取的范围（对所有接入的 AI 都一样）：现在开放的库直接写在这一行上
    group(body, '可读取哪些库 · 电脑端和网页端一样');
    const folders = Array.isArray(r.folders) ? r.folders : [];
    const scope = body.createEl('details', { cls: 'lb-row-fold', attr: { 'data-section': 'mcp-folders' } });
    const sum = scope.createEl('summary');
    sum.createDiv({ cls: 'lb-rf-name', text: '开放给 AI 的库' });
    sum.createDiv({ cls: 'lb-rf-desc', text: (folders.length ? folders.map(f => (f === '@xhs' ? '小红书收藏库' : f.split(/[\\/]/).pop() || f)).join(' · ') : '小红书收藏库') + ' · 点开增减' });
    let scopeDrawn = false;
    scope.addEventListener('toggle', () => {
      if (!scope.open || scopeDrawn) return; scopeDrawn = true;
      safe(tab, scope, '开放的文件夹', () => tab.stops.push(plugin.remoteUI?.renderConnect(scope.createDiv(), () => tab.display(), tab, { part: 'folders' })));
    });
  }

  // ———————————————————— ② 内容、目录及管理 ————————————————————
  function renderContentCard(c, tab) {
    const s = plugin.settings;
    const body = tab.card(c, '内容、目录及管理', 's-content');
    const ann = body.createDiv({ cls: 'lb-annot-rows', attr: { 'data-section': 'catalog' } });
    new Setting(ann).setName('批注署名').setDesc('空着不署名')
      .addText(t => t.setPlaceholder('我').setValue(s.nickname || '').onChange(async v => { s.nickname = v.trim(); await tab.save(); }));
    new Setting(ann).setName('留言对象').setDesc('以「@名字」开头的批注标成留言给它；空着不启用')
      .addText(t => t.setPlaceholder('不启用').setValue(s.annotateMention || '').onChange(async v => { s.annotateMention = v.trim(); await tab.save(); }));
    advFold(body, tab, '目录与写法', 'skills', b => { tab.fieldCategories(b); tab.renderSkillsTab(b); }, { desc: '分类目录（索引）；问收藏按问题选的写法（Skill）' });
    advFold(body, tab, '附件', 'attach', b => {
      tab.fieldDownloadFolder(b);
      tab.numberField(b, '等下载最多几分钟', '手动下载附件时，在下载文件夹里等文件出现多久',
        { get: () => s.downloads.waitMinutes, set: v => s.downloads.waitMinutes = v, def: 5, unit: '分钟' });
      tab.link(new Setting(b).setName('还没下到的附件'), '查看', async () => {
        try {
          const data = plugin.catalogCache?.data || JSON.parse(await plugin.app.vault.adapter.read(plugin.lbPath('_archive/catalog-data.json')));
          plugin.openAttachments(data.items.filter(it => it.attachment === '待补'));
        } catch (e) { plugin.notify('这一块暂时读不到：' + e.message, { kind: 'error' }); }
      }, '列出还没下到附件的笔记');
    }, { desc: '手动下载、还没下到的' });
    if (typeof plugin.openLibraryPage === 'function') {
      const trash = new Setting(body).setName('回收站').setDesc('删掉的收藏在这里，能恢复');
      tab.link(trash, '打开', () => plugin.openLibraryPage('trash'), '打开回收站');
    }
  }

  // ———————————————————— ⑥ 高级 / 修复 ————————————————————
  function renderMoreCard(c, tab) {
    const s = plugin.settings;
    const body = tab.card(c, '高级 / 修复', 's-more');
    body.head.createSpan({ cls: 'lb-card-hint', text: '不动也能用' });
    if (typeof plugin.openProblems === 'function') {
      const pr = new Setting(body).setName('问题与修复').setDesc('哪里没做成、系统已经怎么处理的；能一键修');
      tab.link(pr, '打开', () => plugin.openProblems(), '打开问题列表');
    }
    advFold(body, tab, '这台电脑', 'developer', b => {
      const h = home();
      if (h) { tab.stops.push(h.renderStatus(b, tab, { machineOnly: true })); tab.stops.push(h.renderRun(b, tab)); }
      tab.renderDeveloperCard(b);
    }, { desc: '组件装没装齐、一键装好 / 跑完、后端程序' });
    const again = new Setting(body).setName('重新走一遍首次设置');
    again.settingEl.addClass('lb-more-row');
    tab.link(again, '开始', async () => { s.onboarding = { ...(s.onboarding || {}), force: true, guideDone: false, step: 0 }; await tab.save(); tab.display(); try { tab.containerEl.scrollTop = 0; } catch {} }, '回到首次设置');
  }

  // ———————————————————— 一页：状态 + 按要做的事排的六组 ————————————————————
  // ① 收藏与同步 ② 内容、目录及管理 ③ 识别与问答 ④ 模型与费用 ⑤ 外部 AI 接入 ⑥ 高级 / 修复
  function renderPage(c, tab) {
    renderStatus(c, tab);
    renderXhs(c, tab);
    renderContentCard(c, tab);
    renderAICard(c, tab);
    renderCostCard(c, tab);
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
    // 「同步」一步里的时间编辑器和设置页是同一个（syncTimeEditor）：改了没点「保存定时」就离开这一步 → 替她存上，存不上就留在这一步说原因
    let syncEd = null;
    const leaveSync = async () => {
      const ed = syncEd;
      if (!ed) return true;
      if (ed.isDirty && ed.isDirty()) {
        const res = await ed.saveNow();
        if (!res || !res.ok) { plugin.notify('自动同步时间没保存上，先看一下这一步：' + ((res && res.error) || '原因不明'), { kind: 'error' }); return false; }
      }
      try { ed.destroy(); } catch {}
      syncEd = null;
      return true;
    };
    const go = async n => { if (!(await leaveSync())) return; step = n; s.onboarding.step = n; await tab.save(); paint(); };
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
        next.onclick = async () => { if (last) { if (await leaveSync()) await finish(); } else await go(step + 1); };
        if (step > 1) n.createEl('button', { text: '上一步' }).onclick = () => go(step - 1);
        const out = n.createEl('button', { cls: 'lb-link lb-push', text: '以后再说' });
        out.onclick = async () => { if (await leaveSync()) await finish(false); };   // 以后再说：只记走完，不替她开跑
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
        syncEd = renderXhsInto(body, tab);
      } else if (id === 'ai') {
        title('识别与问答', '本机两项免费，其余需要 key');
        aiRows(body, tab, { guide: true });
      } else {
        title('接入其他 AI（MCP）', '只读 · 可跳过');
        body.createEl('p', { cls: 'lb-guide-hint', text: '通过 MCP 把收藏库接给这些应用：在里面就能搜索、阅读你的收藏。只读，不会修改或删除，随时可以断开。' });
        group(body, '接入电脑端 · 不用域名');
        appRows(body, tab, { guide: true });
        group(body, '接入网页端 · 要你自己的域名');
        webRow(body, tab, { guide: true });
      }
      nav();
    };
    paint();
  }
  // ———————————————————— 唯一的「自动同步时间」编辑器 ————————————————————
  // 设置页「收藏与同步」、首次设置「同步」一步用的都是它（里面是 schedule-ui.js 那一个组件；值只在后端计划任务里，两边读写同一份）；
  // 首页齿轮 / 同步记录「改定时」/ 账号弹窗「定时…」走 plugin.openSyncTime() → 打开设置页落到 data-section="sync-time"。
  function syncTimeEditor(body, tab) {
    const wrap = body.createDiv({ cls: 'lb-sync-time', attr: { 'data-section': SYNC_TIME } });
    const row = new Setting(wrap).setName('自动同步时间').setDesc('电脑开着就会同步，不用开 Obsidian');
    row.settingEl.addClass('lb-sched-row');
    let ed = null;
    safe(tab, wrap, '自动同步', () => {
      ed = plugin.scheduleUI().render(wrap.createDiv({ cls: 'lb-sched-host' }), { primary: false });
      wrap.lbReady = ed.ready;
      tab.stops.push(() => ed.destroy());
    });
    return ed;
  }
  // 「同步」那几行：设置页①和首次设置共用（不再套一层卡片）；返回时间编辑器
  function renderXhsInto(body, tab) {
    const so = plugin.settings.sync;
    const ed = syncTimeEditor(body, tab);
    tab.fieldDailyLimit(body);
    tab.fieldCommentFloors(body);
    tab.toggleRow(body, '保存视频', '关掉只存封面和链接，省硬盘', () => so.downloadVideo, v => { so.downloadVideo = v; });
    return ed;
  }

  return { renderPage, renderGuide, needsGuide, renderStatus, renderXhs, renderContentCard, renderAICard, renderCostCard, renderConnectCard, renderMoreCard,
    syncTimeEditor, focusSection, addKey, keyModal, STEPS, PROV, SYNC_TIME };
};

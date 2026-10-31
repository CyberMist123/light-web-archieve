// settings-v6.js — 设置页（1027 第三版，设计稿 design-1027/prototype.html「设置」+ design.md §3；作者批：六组一页滚完）。
//   左边是锚点（窄了变成顶上一条横排），右边一组一组往下：
//   ① 账号登录（每个平台一张账号卡：小红书 = 状态 + 扫码 / 去验证 / 重试，⋯ 里 状态检查 / 切换账号 / 退出账号；B 站 = 网页 + 电视端登录、同步选项、预估 / 立即同步 / 上次摘要（1031））
//   ② 收藏与同步（同步：收藏同步一行 + 同步开关 + 同步时间（唯一的编辑器，改了自动存）+ 每天新收；存哪些：图片 · 视频 · 评论楼数）
//   ③ 目录与批注（目录的样子 → 去目录编排；批注署名。样式都在目录页「编排 → Aa 样式」，这里不放）
//   ④ 高级功能（一项一行带图标：转 Markdown · 语音转文字 · 识图 · 问答模型 · 概要与标签 · 按意思搜；AI 控制台）
//   ⑤ CLI 与外接 MCP（本机命令行；让其他 AI 读收藏：电脑端 / 网页端两张卡；开放收藏库）
//   ⑥ 修复（当前状态 + 检查 / 全部修一遍；问题记录只有这一个入口）
//   每组只放常用的，其余在组底「＋ 更多」（点开才画）；说明一律在 ⓘ 悬停里；改了就存，没有「保存」按钮，常规改动不弹窗。
//   第一次用：同一个位置换成首次设置（推荐设置一键开始 / 自定义四步），四步里用的就是下面这些行（同一个值、同一个编辑器）。
// 这里只排版和接线：每一行的读写、保存失败拨回仍用设置页（tab）、home-ui、remote-ui、schedule-ui、usage-ui 上原有的方法。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Setting } = obsidian;
  const pages = plugin.settingsPages();
  const home = () => (plugin.homeUI ? plugin.homeUI() : null);
  const safe = (tab, c, what, fn) => (tab.safe ? tab.safe(c, what, fn) : fn());
  const S = () => plugin.settings;
  const openUrl = url => {
    if (!/^https:\/\//.test(url || '')) return;
    try { require('electron').shell.openExternal(url); return; } catch {}
    try { window.open(url); } catch (e) { console.error('[lb] 网页没打开', e); }
  };
  const errText = e => (e && e.message) || String(e || '');
  const SYNC_TIME = 'sync-time';   // 唯一的自动同步时间编辑器的落点（plugin.openSyncTime() / openSetupPage('sync-time' | 'schedule')）
  const GROUPS = [['g-account', '01', '账号登录'], ['g-sync', '02', '收藏与同步'], ['g-catalog', '03', '目录与批注'],
    ['g-advanced', '04', '高级功能'], ['g-connect', '05', 'CLI 与外接 MCP'], ['g-repair', '06', '修复']];
  const PROV = { google: 'Gemini', deepseek: 'DeepSeek', aliyun: '通义千问', openai: 'OpenAI' };
  const CAP_NAME = { textAI: '问答', summaryAI: '概要', visionAI: '识图', 'visionAI.refine': '精细识图', embedAI: '按意思搜', asrAI: '语音转文字' };

  // —— 图标：一套线条图标（24 格、1.5 粗、圆头），和名字成对出现；屏幕阅读器读名字 ——
  const ICONS = {
    doc: [['path', { d: 'M7 3h7l4 4v14H7z' }], ['path', { d: 'M14 3v4h4' }], ['path', { d: 'M10 12h5M10 16h5' }]],
    audio: [['path', { d: 'M4 10v4M7.5 7v10M11 4v16M14.5 8v8M18 6v12M21 10v4' }]],
    image: [['rect', { x: 3, y: 4.5, width: 18, height: 15, rx: 1.5 }], ['circle', { cx: 8.5, cy: 9.5, r: 1.5 }], ['path', { d: 'M3 17l5-5 4 4 3-3 6 6' }]],
    chat: [['path', { d: 'M4 5h16v11H9.5L5 20v-4H4z' }], ['path', { d: 'M8 9h8M8 12.5h5' }]],
    summary: [['path', { d: 'M4 6h16M4 10h12M4 14h16M4 18h9' }]],
    search: [['circle', { cx: 10.5, cy: 10.5, r: 6 }], ['path', { d: 'M15 15l5.5 5.5' }]],
  };
  function iconEl(parent, id) {
    const doc = parent.ownerDocument || document, NS = 'http://www.w3.org/2000/svg';
    const wrap = parent.createSpan ? parent.createSpan({ cls: 'lb-feat-icon', attr: { 'aria-hidden': 'true', 'data-icon': id } }) : null;
    if (!wrap) return null;
    const svg = doc.createElementNS(NS, 'svg');
    for (const [k, v] of Object.entries({ viewBox: '0 0 24 24', width: '18', height: '18', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })) svg.setAttribute(k, v);
    for (const [tag, attrs] of ICONS[id] || []) { const n = doc.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); svg.appendChild(n); }
    wrap.appendChild(svg);
    return wrap;
  }

  // —— 小积木 ——
  // 一行：名字（可带图标）+ ⓘ 悬停说明 + 右边控件；说明不占行（作者：每行「名称 + 控件」，规则在 ⓘ 里）
  function row(parent, tab, name, help = '', { icon = '', cls = '', section = '' } = {}) {
    const r = new Setting(parent).setName(name);
    if (icon) { const ic = iconEl(r.nameEl, icon); if (ic && r.nameEl.firstChild !== ic) r.nameEl.insertBefore(ic, r.nameEl.firstChild); r.settingEl.addClass('lb-feat'); }
    if (cls) r.settingEl.addClass(cls);
    if (section) r.settingEl.setAttribute?.('data-section', section);
    if (help) tab.help(r, help);
    return r;
  }
  const sub = (parent, text, section = '') => parent.createDiv({ cls: 'lb-subhead', text, attr: section ? { 'data-section': section } : {} });
  // 下拉：改了立刻做 apply；没做成把下拉拨回去并说原因（和开关同一句式，CONVENTIONS §8）
  function select(r, options, get, apply, { label = '' } = {}) {
    let dd = null;
    r.addDropdown(d => {
      dd = d;
      for (const [v, text] of options) d.addOption(v, text);
      d.setValue(get());
      if (label) d.selectEl?.setAttribute?.('aria-label', label);
      d.onChange(async v => {
        const before = get();
        try { await apply(v); }
        catch (e) { try { d.setValue(get() === v ? before : get()); } catch {} plugin.notify('没保存上，已改回原来的：' + errText(e), { kind: 'error' }); return; }
        try { d.setValue(get()); } catch {}
      });
    });
    return dd;
  }

  // 组底「＋ 更多」：点开才画；holds = 里面的落点（focusSection 找不到落点时先把它打开画出来）
  function more(group, tab, section, draw, { holds = [] } = {}) {
    const d = group.createEl('details', { cls: 'lb-more', attr: { 'data-section': section, 'data-holds': holds.join(' ') } });
    d.createEl('summary', { text: '＋ 更多' });
    const inner = d.createDiv({ cls: 'lb-more-body' });
    let drawn = false;
    d.lbDraw = () => { if (drawn) return; drawn = true; safe(tab, inner, '更多', () => draw(inner)); };
    d.addEventListener('toggle', () => { if (d.open) d.lbDraw(); });
    return d;
  }

  // 1026 作者（录屏 23:23「很奇怪的跳转」、23:34「点了没有反应」）：跳过去要落在**能改的那个控件**上，不是组顶；
  // 落点在收着的「更多」里：先打开、画出来，再滚；落地后那一块闪一下、焦点放进第一个输入框，找不到就说一句。返回落到的元素（测试用）。
  function focusSection(tab, section, { quiet = false } = {}) {
    const root = tab && tab.containerEl;
    let el = root && root.querySelector(`[data-section="${section}"]`);
    if (!el && root) {
      const box = [...root.querySelectorAll('details.lb-more')].find(d => String(d.getAttribute('data-holds') || '').split(' ').includes(section));
      if (box) { box.open = true; box.lbDraw && box.lbDraw(); el = root.querySelector(`[data-section="${section}"]`); }
    }
    if (!el) { if (!quiet) plugin.notify('这一项还没画出来，稍等一下再点', { kind: 'warn' }); return null; }
    for (let n = el; n && n !== root; n = n.parentNode) {
      if (n.tagName === 'DETAILS' && !n.open) { try { n.open = true; n.lbDraw && n.lbDraw(); } catch {} }
      if (n.hidden && typeof n.lbShow === 'function') { try { n.lbShow(); } catch {} }   // 1031：落点在没选中的平台页里（②小红书 / B 站切换）→ 先切过去
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
    if (el.lbReady && typeof el.lbReady.then === 'function') el.lbReady.then(() => land(), () => {});   // 编辑器读完现在的定时再落一次（输入框这时才在）
    return el;
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
  // 哪家的 key 出了问题（后端 usage.keys：{服务商: {code, caps}}，caps = 哪几项在用这家时撞上的）
  function keyTrouble(usage) {
    const keys = (usage && usage.keys) || {};
    const out = [];
    for (const [id, k] of Object.entries(keys)) {
      if (!PROV[id]) continue;
      const quota = String(k.code || '').endsWith('QUOTA_EXCEEDED');
      const caps = Array.isArray(k.caps) ? k.caps : [];
      out.push({ id, name: PROV[id], quota, caps, text: `${PROV[id]} ${quota ? '额度用完或余额不足' : 'key 用不了'}` + (caps.length ? `（${[...new Set(caps.map(c => CAP_NAME[c] || c))].join('、')}）` : '') });
    }
    return out;
  }
  // ———————————————————— 粘一把 key ————————————————————
  // 唯一的 key 入口（④「更多 → 接口与密钥」，首次设置第 3 步也是它）：粘进来 → 后端认出是哪家（`keys detect`，key 走标准输入）→
  //   这家的 key 正好用不了（usage.keys 点了名）→ 换掉：在用这家的那几格（主用 / 备用 / 精细识图那一层）填上新 key（apiKey 排最前，原来的
  //   密钥文件 / 环境变量引用一个不删）；否则 → 只往空着的格子里填（已经填好的地址、别的密钥引用一个不动）。
  const blank = v => !String(v || '').trim();
  const hasKeyRef = cfg => !!(cfg && (cfg.apiKey || cfg.keyFile || cfg.apiKeyEnv || cfg.keyPool));
  async function detectKey(key) {
    const r = await plugin.runPy(['-m', 'link_brain', 'keys', 'detect'], { input: key + '\n', label: '认 key', timeoutMs: 40000, okCodes: [0, 1], fallback: '没认出来' });
    return r && r.json;
  }
  async function addKey(raw, { detected = null } = {}) {
    const key = String(raw || '').trim();
    if (!key) { plugin.notify('先粘贴一把 key'); return null; }
    const j = detected || await detectKey(key);
    if (!j || !j.ok) { plugin.notify((j && j.message) || '没认出来', { kind: 'error' }); return null; }
    const s = S();
    const before = JSON.parse(JSON.stringify(Object.fromEntries(Object.keys(j.fills || {}).map(k => [k, s[k]]))));
    const filled = [];
    const NAMES = { textAI: '问收藏', summaryAI: '概要', visionAI: '识图', embedAI: '按意思搜' };
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
      if (h && s.visionAI && !blank(s.visionAI.endpoint) && filled.includes('识图')) await h.setFeature('ai_vision', true).catch(() => {});
    } catch (e) {
      for (const k of Object.keys(j.fills || {})) { if (before[k] === undefined) delete s[k]; else s[k] = before[k]; }
      plugin.notify('没保存上，原来的设置没动：' + errText(e), { kind: 'error' });
      return null;
    }
    delete cache.usage;
    plugin.notify(`认出是 ${j.name}：已用在 ${filled.join('、')}（已经配好的没动）`, { kind: 'ok', ms: 8000 });
    return j;
  }
  // 哪几格在用这家：后端 `keys detect` 给的 slots（「summaryAI.fallback」「visionAI.refine」…，pricing.provider_of 一处认哪家，前端不猜）；
  // 只换撞上问题的那几项（caps，来自 usage.keys）；概要「跟随问答」撞上了 = 问答那一格
  function slotsFor(slots, caps) {
    const s = S();
    const roots = new Set((caps || []).map(c => String(c).split('.')[0]));
    if (roots.has('summaryAI') && s.summaryAI && (!s.summaryAI.mode || s.summaryAI.mode === 'inherit')) roots.add('textAI');
    const pick = (slots || []).filter(p => !roots.size || roots.has(String(p).split('.')[0]));
    const out = [];
    for (const p of pick) {
      const [root, sub] = String(p).split('.');
      const cfg = s[root] && typeof s[root] === 'object' ? (sub ? s[root][sub] : s[root]) : null;
      if (cfg && typeof cfg === 'object' && !out.includes(cfg)) out.push(cfg);
    }
    return out;
  }
  // 1027 修：以前状态卡上「换一个 key」只往空格子里填——key 坏了的那一格已经有密钥引用，换不掉。现在换的是在用这家、撞上问题的那几格。
  async function replaceKey(provider, raw, caps, slots) {
    const key = String(raw || '').trim();
    if (!key) { plugin.notify('先粘贴一把 key'); return null; }
    const s = S();
    if (!Array.isArray(slots)) { plugin.notify('后台程序是旧版，认不出哪几格在用这家：先更新后台程序，或在下面选那一项自己填 key', { kind: 'warn', ms: 10000 }); return null; }
    const targets = slotsFor(slots, caps);
    if (!targets.length) { plugin.notify(`认出是 ${PROV[provider] || provider}，但没找到哪一项在用它的接口：在下面选那一项，自己填 key`, { kind: 'warn', ms: 10000 }); return null; }
    const snap = JSON.parse(JSON.stringify({ textAI: s.textAI, summaryAI: s.summaryAI, visionAI: s.visionAI, embedAI: s.embedAI, asrAI: s.asrAI }));
    for (const slot of targets) slot.apiKey = key;   // apiKey 排在 keyPool / keyFile / 环境变量前面（providers.resolve_key）：不删原来的引用也能换掉
    try { await plugin.saveSettings(); }
    catch (e) { for (const [k, v] of Object.entries(snap)) { if (v === undefined) delete s[k]; else s[k] = v; } plugin.notify('没保存上，原来的 key 没动：' + errText(e), { kind: 'error' }); return null; }
    delete cache.usage;
    const used = [...new Set((caps || []).map(c => CAP_NAME[c] || c))];
    plugin.notify(`已换上新的 ${PROV[provider] || provider} key${used.length ? '：用在 ' + used.join('、') : ''}（下一次调用就用它；原来的 key 文件 / 环境变量没删）`, { kind: 'ok', ms: 10000 });
    return { provider, slots: targets.length };
  }
  async function pasteKey(raw) {
    const key = String(raw || '').trim();
    if (!key) { plugin.notify('先粘贴一把 key'); return null; }
    const j = await detectKey(key);
    if (!j || !j.ok) { plugin.notify((j && j.message) || '没认出来', { kind: 'error' }); return null; }
    let usage = null;
    try { usage = await loadUsage(); } catch {}
    const bad = keyTrouble(usage).find(k => k.id === j.provider);
    if (bad) return replaceKey(j.provider, key, bad.caps, j.slots);
    return addKey(key, { detected: j });
  }
  function keyBox(parent, tab, { onDone = null } = {}) {
    const wrap = parent.createDiv({ cls: 'lb-key-paste-row', attr: { 'data-section': 'ai-key-paste' } });
    const r = row(wrap, tab, '粘一把 key', '从 AI 服务商网站复制一串 key 粘进来，自动认出是哪家、填进要用它的几项（这家原来的 key 坏了就换掉）。只存在这台电脑上。');
    let input = null, btn = null;
    r.addText(t => { input = t.inputEl; t.inputEl.type = 'password'; t.inputEl.addClass?.('lb-key-paste'); t.setPlaceholder('粘贴 API key'); t.inputEl.setAttribute?.('autocomplete', 'off'); t.inputEl.setAttribute?.('aria-label', 'API key'); });
    r.addButton(b => { btn = b; b.setButtonText('认出并用上').onClick(async () => {
      b.setDisabled(true); b.setButtonText('正在认…');
      let res = null;
      try { res = await pasteKey(input.value); } finally { b.setDisabled(false); b.setButtonText('认出并用上'); }
      if (res) { input.value = ''; onDone && onDone(res); }
    }); });
    const links = wrap.createDiv({ cls: 'lb-prov-links setting-item-description' });
    links.createSpan({ text: '还没有 key？在这里拿（Google 的有免费额度，最省事）：' });
    for (const id of ['google', 'deepseek', 'aliyun', 'openai']) {
      const l = (pages.LINKS || {})[id];
      if (!l || !l.key) continue;
      const a = links.createEl('button', { cls: 'lb-link', text: PROV[id] + (id === 'google' ? '（有免费额度）' : '') });
      a.onclick = () => openUrl(l.key);
    }
    return { input: () => input, button: () => btn };
  }

  // ———————————————————— ① 账号登录 ————————————————————
  function groupAccount(g, tab) {
    const twin = g.createDiv({ cls: 'lb-twin' });
    const xhs = twin.createDiv({ cls: 'lb-twin-card', attr: { 'data-platform': 'xhs', 'data-section': 'account-xhs' } });
    const head = xhs.createDiv({ cls: 'lb-twin-head' });
    head.createEl('strong', { text: '小红书' });
    head.createSpan({ cls: 'lb-twin-note', text: '登哪个号就同步哪个号' });
    safe(tab, xhs, '小红书账号', () => plugin.renderAccounts(xhs, { inCard: true }));
    const bili = twin.createDiv({ cls: 'lb-twin-card lb-bili', attr: { 'data-platform': 'bilibili', 'data-section': 'account-bili' } });
    safe(tab, bili, 'B 站', () => biliCard(bili, tab));
  }

  // ———————————————————— ① B 站（1031 作者：只做手动同步，不做定时）————————————————————
  // 一张卡：登录（网页 + 电视端两行状态、扫码弹窗）· 同步选项（存 settings.bilibili）· 「预估」「立即同步」· 上次同步摘要。
  // 后端：`bilibili status|login|logout|sync|last`（CONVENTIONS §1：最后一行 JSON，提示只用 json.message）。
  // 悬停气泡在 LWA 里全局去掉了：说明一律写成卡里看得见的字。
  // 1031 作者：同时下几路放到 1–8、默认 8（撞 412/429 后端自动退回一路）；skipFolders = 挑选页里关掉的收藏夹 id（'toview' = 稍后再看）
  const BILI_DEFAULTS = { quality: 'max', maxDuration: 3600, danmaku: true, workers: 8, skipFolders: [] };
  const BILI_QUALITY = [['max', '最高'], ['1080', '1080p'], ['720', '720p']];
  const BILI_DURATION = [['1800', '30 分钟'], ['3600', '1 小时'], ['7200', '2 小时'], ['0', '不限']];
  const BILI_WORKERS_MAX = 8;
  const BILI_WORKERS = Array.from({ length: BILI_WORKERS_MAX }, (_, i) => [String(i + 1), `${i + 1} 路`]);
  const BILI_RUN_LABEL = '下载 B 站收藏';      // 状态栏那一条（别带「同步」两个字：那是小红书同步记录的口径，停止时会去记小红书的同步记录）
  const BILI_EST_LABEL = '预估 B 站收藏';
  let biliStatus = null;   // ①登录卡读到的状态，②「立即同步」先看一眼
  const biliOpts = () => ({ ...BILI_DEFAULTS, ...((S() || {}).bilibili || {}) });
  // 关掉的收藏夹 id：只认非空字符串、去重、排序（存设置和传后端都用它）
  const biliSkip = o => [...new Set((Array.isArray(o && o.skipFolders) ? o.skipFolders : []).map(x => String(x == null ? '' : x).trim()).filter(Boolean))].sort();
  function biliSyncArgs(o, { dryRun = false } = {}) {
    const q = BILI_QUALITY.some(([v]) => v === o.quality) ? o.quality : 'max';
    const w = Math.min(BILI_WORKERS_MAX, Math.max(1, parseInt(o.workers, 10) || 1));
    const d = Math.max(0, parseInt(o.maxDuration, 10) || 0);
    const args = ['-m', 'link_brain', 'bilibili', 'sync', '--json', '--quality', q, '--max-duration', String(d), '--workers', String(w)];
    if (o.danmaku === false) args.push('--no-danmaku');
    for (const id of biliSkip(o)) args.push('--skip-folder', id);
    if (dryRun) args.push('--dry-run');
    return args;
  }
  // 改一个选项就存；没存上拨回原值，句式同 CONVENTIONS §8
  async function saveBili(key, value) {
    const s = S();
    const before = s.bilibili ? { ...s.bilibili } : undefined;
    s.bilibili = { ...biliOpts(), [key]: value };
    try { await plugin.saveSettings(); }
    catch (e) { if (before === undefined) delete s.bilibili; else s.bilibili = before; throw e; }
  }
  const fmtDur = sec => { const m = Math.round((Number(sec) || 0) / 60); if (m < 1) return '不到 1 分钟'; const h = Math.floor(m / 60); return h ? `${h} 小时${m % 60 ? ' ' + (m % 60) + ' 分' : ''}` : `${m} 分钟`; };
  const fmtSize = b => { const n = Number(b) || 0; return n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : Math.round(n / 1048576) + ' MB'; };
  function biliLoginLines(j) {
    const web = !j ? '网页登录：读不到状态' : j.state === 'logged_in' ? `网页登录：已登录${j.mid_masked ? '（' + j.mid_masked + '）' : ''}${j.vip ? ' · 大会员' : ''}`
      : j.state === 'logged_out' ? '网页登录：没登录（读收藏夹要登录）' : `网页登录：查不到（${j.message || '网络不通'}）`;
    const tv = j && j.tv;
    const tvText = !tv ? '电视端：读不到状态' : tv.state === 'logged_in' ? '电视端：已登录（优先拿无水印、更高画质的片源）'
      : tv.state === 'expired' ? '电视端：登录已失效，重新扫一次（不扫也能下，走网页片源）' : '电视端：没登录（可选；不扫也能下，走网页片源，可能带水印）';
    return [web, tvText];
  }
  function estimateText(e) {
    if (!e || e.count == null) return '';
    if (!e.count) return '没有要下的：收藏里的视频都已经在库里了';
    const head = `要下 ${e.count} 条 · 总时长 ${fmtDur(e.total_duration_s)}`;
    if (!e.size_bytes) return head + (e.error ? `（估不出体积：${e.error}）` : '');
    return `${head} · 约 ${fmtSize(e.size_bytes.low)}–${fmtSize(e.size_bytes.high)} · 约 ${fmtDur(e.eta_s.low)}–${fmtDur(e.eta_s.high)}`;
  }
  function lastText(l) {
    if (!l || !l.exists) return { main: '还没同步过 B 站收藏', sub: '' };
    // 1101 作者「小白看得懂」：说人话——下了几条、几条没下成、几个分集很多的视频等你挑；超长 / 失效的一句带过
    const bits = [`这次新下了 ${l.downloaded} 条`];
    if (l.failed) bits.push(`${l.failed} 条没下成（下次同步会再试）`);
    if (l.multi_p) bits.push(`${l.multi_p} 个分集很多的视频等你挑要不要下`);
    const d = l.details || {};
    const quiet = [d.long ? `${d.long} 条太长` : '', d.invalid ? `${d.invalid} 条已经被删 / 失效` : ''].filter(Boolean);
    return { main: l.message || '', sub: bits.join('；') + '。' + (quiet.length ? `另外 ${quiet.join('、')}，先没下，不用管。` : '') };
  }
  function openVaultNote(rel) {
    if (!rel) { plugin.notify('还没有待选清单：同步一次就有'); return; }
    const f = plugin.app.vault.getAbstractFileByPath?.(plugin.lbPath(rel));
    if (!f) { plugin.notify('还没有待选清单：同步一次就有'); return; }
    // 1031 作者「待选清单打不开」：其实开了，但 Obsidian 1.14 的设置是独立窗口、挡在主窗口前面——先关设置，开好后把主窗口提到前面
    try { plugin.app.setting?.close?.(); } catch {}
    const leaf = plugin.app.workspace.getLeaf('tab');
    Promise.resolve(leaf.openFile(f)).then(() => {
      try { plugin.app.workspace.setActiveLeaf?.(leaf, { focus: true }); } catch {}
      try { (leaf.view?.containerEl?.win || window).focus?.(); } catch {}
    }).catch(e => plugin.notify('待选清单没打开：' + errText(e), { kind: 'error' }));
  }
  // 扫码弹窗：后端把二维码存成临时 PNG（`--qr-png`），这里每秒看一眼文件、画出来；过期换新码时文件被覆盖，图跟着换。
  // 关掉弹窗 = 取消（killTree 那个登录进程）。登录态存在本机 ~/.link-brain/bilibili/，扫一次以后自动复用。
  function biliQrLogin({ tv = false } = {}) {
    const os = require('os'), fs = require('fs'), path = require('path');
    const png = path.join(os.tmpdir(), `lwa-bili-qr-${tv ? 'tv-' : ''}${Date.now()}.png`);
    const Modal = obsidian.Modal;
    return new Promise(resolve => {
      let child = null, done = false, timer = null, lastMtime = 0, img = null, hint = null, modal = null;
      const finish = r => { if (done) return; done = true; if (timer) clearInterval(timer); try { fs.unlinkSync(png); } catch {} resolve(r); };
      if (Modal) {
        modal = new Modal(plugin.app);
        modal.modalEl?.addClass?.('lb-bili-qr-modal');
        const c = modal.contentEl;
        c.createEl('h2', { text: tv ? '扫码登录 B 站（电视端）' : '扫码登录 B 站' });
        c.createEl('p', { text: '用手机哔哩哔哩 App 扫下面的二维码，在手机上点确认。二维码约 3 分钟过期，过期会自动换新的。' });
        c.createEl('p', { cls: 'setting-item-description', text: tv ? '电视端登录只用来拿无水印、更高画质的片源；和网页登录分开扫一次。'
          : '登录态只存在这台电脑上（~/.link-brain/bilibili/），扫一次以后自动复用，不用每次扫。' });
        img = c.createEl('img', { cls: 'lb-bili-qr', attr: { alt: 'B 站登录二维码' } });
        hint = c.createEl('p', { cls: 'lb-bili-qr-hint', text: '正在取二维码…' });
        modal.onClose = () => { if (!done && child) { plugin.killTree(child.pid).catch(() => {}); } finish({ cancelled: true }); };
        modal.open();
      }
      timer = setInterval(() => {
        try {
          const st = fs.statSync(png);
          if (st.mtimeMs !== lastMtime && img) { lastMtime = st.mtimeMs; img.src = 'data:image/png;base64,' + fs.readFileSync(png).toString('base64'); hint.setText('等你扫码…'); }
        } catch {}
      }, 1000);
      const args = ['-m', 'link_brain', 'bilibili', 'login', '--json', '--qr-png', png, '--timeout', '300'];
      if (tv) args.push('--tv');
      plugin.spawnPy(args, { label: tv ? 'B 站电视端扫码' : 'B 站扫码', timeoutMs: 330000, onChild: ch => { child = ch; } }).then(r => {
        const j = r && r.json;
        if (!done && hint && !lastMtime && /qrcode/.test((r && r.err) || '')) hint.setText('没画出二维码：这台电脑缺 qrcode 包（python -m pip install qrcode）');
        finish({ json: j, code: r && r.code });
        try { modal && modal.close(); } catch {}
      });
    });
  }

  // 1031 作者：「你看小红书多简洁？和这个对齐」——一行「昵称 · ✓ 已登录」+ ⋯ 菜单；只给一个「扫码登录」：
  // 扫的是电视端码（后端同一次扫码把网页端 cookie 也存上，tvapi.save_web_cookies）；万一网页端没带上，再点一次扫网页端。
  function biliCard(card, tab) {
    const head = card.createDiv({ cls: 'lb-twin-head' });
    head.createEl('strong', { text: 'B 站' });
    head.createSpan({ cls: 'lb-twin-note', text: '收藏夹名当专辑' });
    const box = card.createDiv({ cls: 'lb-accounts lb-bili-login', attr: { 'data-section': 'bili-login' } });
    // 手搭和小红书 renderAccountRow 同一套类名（setting-item lb-acct-row / lb-acct-who / lb-acct-state / lb-acct-guide / ⋯），样子自动一致
    const rowEl = box.createDiv({ cls: 'setting-item lb-acct-row' });
    const info = rowEl.createDiv({ cls: 'setting-item-info' });
    const nameEl = info.createDiv({ cls: 'setting-item-name' });
    const who = nameEl.createSpan({ cls: 'lb-acct-who' });
    const state = nameEl.createSpan({ cls: 'lb-acct-state', text: '检查中' });
    const guide = info.createDiv({ cls: 'setting-item-description' }).createDiv({ cls: 'lb-acct-guide' });
    const ctl = rowEl.createDiv({ cls: 'setting-item-control' });
    const primaryEl = ctl.createEl('button', { cls: 'lb-bili-scan', text: '扫码登录' });
    // 1031 用户截图：登着还露「扫码登录」——Obsidian 给 button 写了 display，盖过 hidden 属性；显隐一律走 style.display
    const showPrimary = on => { primaryEl.hidden = !on; primaryEl.style.display = on ? '' : 'none'; };
    primaryEl.type = 'button'; showPrimary(false); primaryEl.onclick = () => login(primaryEl);
    const moreEl = ctl.createDiv({ cls: 'clickable-icon extra-setting-button lb-bili-more', attr: { 'aria-label': '更多', role: 'button', tabindex: '0' } });
    try { obsidian.setIcon ? obsidian.setIcon(moreEl, 'more-horizontal') : moreEl.setText('⋯'); } catch { moreEl.setText('⋯'); }
    moreEl.addEventListener('click', e => openMenu(e));
    const primary = { setButtonText: t => primaryEl.setText(t), buttonEl: { show: () => showPrimary(true), hide: () => showPrimary(false) } };
    const webOk = j => j && j.state === 'logged_in';
    const tvOk = j => j && j.tv && j.tv.state === 'logged_in';
    // 下一步只有一个：两边都没登 / 电视端没登 → 扫电视端（顺带网页端）；只差网页端 → 扫网页端
    const nextScan = j => (!tvOk(j) ? 'tv' : !webOk(j) ? 'web' : null);
    const paintLogin = j => {
      biliStatus = j;
      const any = webOk(j) || tvOk(j);
      who.setText(webOk(j) ? (j.mid_masked || '') : '');   // 只给打码的号（真名不出状态，test_login_status_never_exposes_cookie_values）
      const bits = [];
      if (j && j.vip) bits.push('大会员');
      if (tvOk(j)) bits.push('无水印片源');
      state.setText(!j ? '无法确认' : (webOk(j) ? ' · ✓ 已登录' : any ? '还差一步' : j.state === 'unknown' ? '无法确认' : '没登录') + (webOk(j) && bits.length ? `（${bits.join(' · ')}）` : ''));
      state.className = 'lb-acct-state is-' + (webOk(j) ? 'ready' : 'not_logged_in');
      const next = nextScan(j);
      guide.setText(!j ? '' : !next ? '' : next === 'web' ? '网页端还没登上：点「扫码登录」再扫一次（读收藏夹要用）'
        : webOk(j) ? '电视端没登：点 ⋯ →「重新扫码登录」扫一次能拿无水印片源（不扫也能下）' : '用手机 B 站 App 扫一次码就行，之后自动复用');
      if (next && !(webOk(j) && next === 'tv')) { primary.setButtonText('扫码登录'); primary.buttonEl.show(); } else primary.buttonEl.hide();
    };
    const loadStatus = async () => {
      try { const r = await plugin.runPy(['-m', 'link_brain', 'bilibili', 'status', '--json'], { label: 'B 站登录状态', timeoutMs: 60000, okCodes: [0, 1, 5] }); paintLogin(r.json); }
      catch (e) { paintLogin(null); guide.setText('暂时读不到登录状态：' + errText(e)); }
    };
    const login = async (btn, which = nextScan(biliStatus) || 'tv') => {
      const done = btn ? plugin.busyButton(btn, '等扫码…') : () => {};
      try {
        const r = await biliQrLogin({ tv: which === 'tv' });
        if (r.cancelled) { plugin.notify('已取消扫码'); return; }
        const ok = r.json && r.json.state === 'logged_in';
        plugin.notify(ok ? 'B 站已登录' : ((r.json && r.json.message) || '没登录上'), { kind: ok ? 'ok' : 'warn' });
      } finally { done(); await loadStatus(); }
    };
    const logout = async () => {
      if (!(await plugin.confirm({ title: '退出 B 站登录？', body: '只删这台电脑上存的登录态（网页端和电视端），已下载的视频不动。', ok: '退出', danger: true }))) return;
      try {
        for (const extra of [[], ['--tv']]) await plugin.runPy(['-m', 'link_brain', 'bilibili', 'logout', '--json', ...extra], { label: 'B 站退出登录', timeoutMs: 60000 });
        plugin.notify('已退出 B 站登录');
      } catch (e) { plugin.notify('没退出：' + errText(e), { kind: 'error' }); }
      finally { await loadStatus(); }
    };
    const openMenu = evt => plugin.showMenu && plugin.showMenu([
      { title: '重新扫码登录', icon: 'qr-code', onClick: () => login(null, 'tv') },
      { title: '检查登录状态', icon: 'refresh-cw', onClick: () => loadStatus() },
      { title: '退出登录', icon: 'log-out', danger: true, onClick: () => logout() },
    ], evt);
    loadStatus();
  }

  // —— 挑选页（1031 作者「没有让我选哪些下载」）：一个大弹窗，内容可滚动 ——
  //   收藏夹：全部收藏夹 + 稍后再看，每个一个开关「同步这个收藏夹」，默认全开；关掉的存 settings.bilibili.skipFolders（按 id），
  //     同步时传 `--skip-folder <id>`，后端整个跳过（不扫、不下）。
  //   长视频：顶上选门槛（就是「超过多长先不下」那个设置），下面列超过门槛、还没入库的视频逐条勾；勾上 = `choose --allow`，取消 = `--undo`。
  //   数据只读本地（`bilibili pick`：上次列到的收藏夹 + 本地快照），不连 B 站；没扫过就叫用户先预估 / 同步一次。
  //   底部「保存」「保存并开始同步」；关掉弹窗 = 不存。
  function biliPicker({ onSaved, onSyncNow } = {}) {
    const Modal = obsidian.Modal;
    if (!Modal) { plugin.notify('这里打不开挑选页：Obsidian 太旧，没有弹窗组件', { kind: 'warn' }); return null; }
    const modal = new Modal(plugin.app);
    modal.modalEl?.addClass?.('lb-bili-pick-modal');
    const c = modal.contentEl;
    c.createEl('h2', { text: '挑选要同步的 B 站收藏' });
    c.createEl('p', { cls: 'lb-bili-note', text: '关掉的收藏夹以后同步时整个跳过（不扫、不下；已经下好的不动）。超过时长的视频、超过 5 P 的多 P 默认只记链接，勾上的下次同步就下。这里只读这台电脑上扫过的记录，不连 B 站。' });
    const body = c.createDiv({ cls: 'lb-bili-pick-body' });
    const foot = c.createDiv({ cls: 'lb-bili-pick-foot' });
    const skip = new Set(biliSkip(biliOpts()));
    const skip0 = [...skip].sort().join('\n');
    const picks = new Map();   // bvid → { was（后端记的放行）, now（用户现在勾的）}；换门槛重读时保留
    let data = null;
    const longRows = [];       // [{ it, cb, lab }]：当前画出来的长视频行
    const multiRows = [];      // 同上：超过 5 P 的多 P 行（勾 = 放行，和长视频走同一个 choose --allow）
    const offNote = it => (it.folder_ids || []).length > 0 && it.folder_ids.every(id => skip.has(String(id)));
    const paintOff = () => {
      for (const r of [...longRows, ...multiRows]) {
        const off = offNote(r.it);
        r.lab.toggleClass?.('is-off', off);
        r.off.setText(off ? '所在收藏夹都关了，勾了也不会下' : '');
      }
    };
    const countText = () => {
      const items = (data && data.long && data.long.items) || [];
      return `超过 ${fmtDur(biliOpts().maxDuration)}、还没入库的 ${items.length} 条，勾上 ${items.filter(it => picks.get(it.bvid)?.now).length} 条`;
    };
    let countEl = null;
    const paint = () => {
      body.empty();
      longRows.length = 0; multiRows.length = 0;
      const j = data || {};
      // 收藏夹
      const fsec = body.createDiv({ cls: 'lb-bili-pick-sec', attr: { 'data-section': 'bili-pick-folders' } });
      fsec.createEl('h3', { text: '收藏夹' });
      const folders = j.folders || [];
      if (!folders.length) fsec.createDiv({ cls: 'lb-bili-warn', text: '还没扫过收藏夹：先关掉这里，点一次「预估」或「立即同步」，扫一遍收藏夹。' });
      else {
        fsec.createDiv({ cls: 'lb-bili-note', text: '默认全开；关掉 = 以后同步时整个跳过。新建的收藏夹自动算开着。' });
        const tools = fsec.createDiv({ cls: 'lb-bili-pick-tools' });
        const toggles = [];
        const setAll = on => { for (const t of toggles) t.setValue(on); };
        tools.createEl('button', { cls: 'lb-link', text: '全开' }).onclick = () => setAll(true);
        tools.createEl('button', { cls: 'lb-link', text: '全关' }).onclick = () => setAll(false);
        for (const f of folders) {
          const id = String(f.id);
          const desc = [f.media_count == null ? '条数等下次同步' : `${f.media_count} 条`, f.private ? '私密' : '',
            f.kind === 'toview' ? '移出稍后再看的不删本地' : (f.scanned === false ? '还没扫过' : '')].filter(Boolean).join(' · ');
          const r = new Setting(fsec).setName(f.title || id).setDesc(desc);
          r.settingEl.addClass?.('lb-bili-pick-folder');
          r.settingEl.setAttribute?.('data-folder', id);
          r.addToggle(t => {
            toggles.push(t);
            t.toggleEl?.setAttribute?.('aria-label', '同步这个收藏夹：' + (f.title || id));
            t.setValue(!skip.has(id)).onChange(v => { if (v) skip.delete(id); else skip.add(id); paintOff(); });
          });
        }
      }
      // 多 P（1031 作者：不超过 5 P 的同步时自动拆开一个 P 一条下；更多的在这里勾）
      const mitems = (j.multi && j.multi.items) || [];
      if (mitems.length) {
        const msec = body.createDiv({ cls: 'lb-bili-pick-sec', attr: { 'data-section': 'bili-pick-multi' } });
        msec.createEl('h3', { text: '多 P 视频' });
        msec.createDiv({ cls: 'lb-bili-note', text: `不超过 ${j.multi.auto_max || 5} P 的同步时自动下（一个 P 一篇）；下面这些 P 数多，勾上的下次同步把每个 P 都下。` });
        const mcount = msec.createDiv({ cls: 'lb-bili-pick-count' });
        const mtext = () => `超过 ${j.multi.auto_max || 5} P 的 ${mitems.length} 条，勾上 ${mitems.filter(it => picks.get(it.bvid)?.now).length} 条`;
        const mlist = msec.createDiv({ cls: 'lb-bili-long-list' });
        for (const it of mitems) {
          if (!picks.has(it.bvid)) picks.set(it.bvid, { was: !!it.chosen, now: !!it.chosen });
          const p = picks.get(it.bvid);
          p.was = !!it.chosen;
          const lab = mlist.createEl('label', { cls: 'lb-bili-long-row', attr: { 'data-bvid': it.bvid } });
          const cb = lab.createEl('input', { attr: { type: 'checkbox' } });
          cb.checked = !!p.now;
          cb.onchange = () => { p.now = !!cb.checked; mcount.setText(mtext()); };
          lab.createSpan({ cls: 'lb-bili-long-dur', text: `${it.page_count} P` + (it.done ? `（已下 ${it.done}）` : '') });
          lab.createSpan({ cls: 'lb-bili-long-title', text: it.title || it.bvid });
          lab.createSpan({ cls: 'lb-bili-long-meta', text: [it.duration_text, it.upper, (it.folders || []).join('、')].filter(Boolean).join(' · ') });
          const off = lab.createSpan({ cls: 'lb-bili-long-off', text: '' });
          multiRows.push({ it, cb, lab, off });
        }
        mcount.setText(mtext());
      }
      // 长视频
      const lsec = body.createDiv({ cls: 'lb-bili-pick-sec', attr: { 'data-section': 'bili-pick-long' } });
      lsec.createEl('h3', { text: '长视频' });
      const th = new Setting(lsec).setName('超过多长先不下');
      th.settingEl.addClass?.('lb-bili-pick-threshold');
      th.addDropdown(d => {
        for (const [v, t] of BILI_DURATION) d.addOption(v, t);
        d.setValue(String(biliOpts().maxDuration));
        d.selectEl?.setAttribute?.('aria-label', 'B 站时长上限');
        d.onChange(async v => {
          const before = String(biliOpts().maxDuration);
          try { await saveBili('maxDuration', parseInt(v, 10) || 0); }
          catch (e) { try { d.setValue(before); } catch {} plugin.notify('没保存上，已改回原来的：' + errText(e), { kind: 'error' }); return; }
          try { onSaved && onSaved(); } catch {}
          await load();
        });
      });
      lsec.createDiv({ cls: 'lb-bili-note', text: '和「超过多长先不下」是同一个设置，改了马上存。' });
      const d = biliOpts().maxDuration;
      const items = (j.long && j.long.items) || [];
      if (!d) { lsec.createDiv({ cls: 'lb-bili-note', text: '现在是「不限」：多长的都会下，没有要挑的。' }); paintOff(); return; }
      if (!items.length) { lsec.createDiv({ cls: 'lb-bili-note', text: folders.length ? `没有超过 ${fmtDur(d)}、还没入库的视频。` : '' }); paintOff(); return; }
      const bar = lsec.createDiv({ cls: 'lb-bili-pick-tools' });
      countEl = bar.createSpan({ cls: 'lb-bili-pick-count', text: '' });
      const setLong = on => { for (const r of longRows) { r.cb.checked = on; picks.get(r.it.bvid).now = on; } countEl.setText(countText()); };
      bar.createEl('button', { cls: 'lb-link', text: '全选' }).onclick = () => setLong(true);
      bar.createEl('button', { cls: 'lb-link', text: '全不选' }).onclick = () => setLong(false);
      const list = lsec.createDiv({ cls: 'lb-bili-long-list' });
      for (const it of items) {
        if (!picks.has(it.bvid)) picks.set(it.bvid, { was: !!it.chosen, now: !!it.chosen });
        const p = picks.get(it.bvid);
        p.was = !!it.chosen;
        const lab = list.createEl('label', { cls: 'lb-bili-long-row', attr: { 'data-bvid': it.bvid } });
        const cb = lab.createEl('input', { attr: { type: 'checkbox' } });
        cb.checked = !!p.now;
        cb.onchange = () => { p.now = !!cb.checked; countEl.setText(countText()); };
        lab.createSpan({ cls: 'lb-bili-long-dur', text: it.duration_text || '' });
        lab.createSpan({ cls: 'lb-bili-long-title', text: it.title || it.bvid });
        lab.createSpan({ cls: 'lb-bili-long-meta', text: [it.upper, (it.folders || []).join('、')].filter(Boolean).join(' · ') });
        const off = lab.createSpan({ cls: 'lb-bili-long-off', text: '' });
        longRows.push({ it, cb, lab, off });
      }
      countEl.setText(countText());
      paintOff();
    };
    const load = async () => {
      body.empty();
      body.createDiv({ cls: 'lb-bili-note', text: '正在读这台电脑上扫过的收藏夹记录…' });
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'bilibili', 'pick', '--json', '--max-duration', String(biliOpts().maxDuration)], { label: 'B 站挑选页', timeoutMs: 60000 });
        data = (r && r.json) || {};
      } catch (e) {
        body.empty();
        if (plugin.failBox) plugin.failBox(body, '挑选页', e, load); else body.createDiv({ cls: 'lb-bili-warn', text: '读不到本地记录：' + errText(e) });
        return;
      }
      paint();
    };
    // 存：先存收藏夹开关（设置），再把长视频的变化交给后端（choose）；哪步没成就说原因，弹窗不关、勾的都还在
    const save = async () => {
      const skipArr = [...skip].sort();
      const allow = [], undo = [];
      for (const [bv, p] of picks) { if (p.now && !p.was) allow.push(bv); if (!p.now && p.was) undo.push(bv); }
      try {
        if (skipArr.join('\n') !== skip0) await saveBili('skipFolders', skipArr);
        if (allow.length || undo.length) {
          const args = ['-m', 'link_brain', 'bilibili', 'choose', '--json'];
          for (const bv of allow) args.push('--allow', bv);
          for (const bv of undo) args.push('--undo', bv);
          await plugin.runPy(args, { label: 'B 站选择', timeoutMs: 60000 });
          for (const bv of allow) picks.get(bv).was = true;
          for (const bv of undo) picks.get(bv).was = false;
        }
      } catch (e) { plugin.notify('没保存上，内容还在，可重试：' + errText(e), { kind: 'error' }); return false; }
      const bits = [skipArr.length ? `跳过 ${skipArr.length} 个收藏夹` : '收藏夹全部同步'];
      if (allow.length) bits.push(`放行 ${allow.length} 条`);
      if (undo.length) bits.push(`撤销 ${undo.length} 条`);
      plugin.notify('已保存：' + bits.join('，'), { kind: 'ok' });
      try { onSaved && onSaved(); } catch {}
      return true;
    };
    const saveBtn = foot.createEl('button', { cls: 'lb-btn', text: '保存' });
    const goBtn = foot.createEl('button', { cls: 'lb-btn mod-cta', text: '保存并开始同步' });
    const lock = async (btn, text, after) => {
      const done = plugin.busyButton(btn, text);
      saveBtn.disabled = goBtn.disabled = true;
      let ok = false;
      try { ok = await save(); } finally { done(); saveBtn.disabled = goBtn.disabled = false; }
      if (ok) { modal.close(); if (after) after(); }
    };
    saveBtn.onclick = () => lock(saveBtn, '正在保存…');
    goBtn.onclick = () => lock(goBtn, '正在保存…', onSyncNow);
    modal.open();
    const ready = load();
    return { modal, ready, save, skip, picks };
  }

  // ② 收藏与同步 · B 站同步（1031 作者：和小红书统一——①只放账号登录，同步选项 / 立即同步 / 上次 / 超长清单在②）
  function biliSync(card, tab) {
    // —— 同步选项 ——
    const opts = card.createDiv({ cls: 'lb-bili-opts', attr: { 'data-section': 'bili-options' } });
    const o = biliOpts();
    select(row(opts, tab, '画质'), BILI_QUALITY, () => biliOpts().quality, v => saveBili('quality', v), { label: 'B 站画质' });
    opts.createDiv({ cls: 'setting-item-description lb-bili-note', text: '最高 = 你的账号能拿到的最高清晰度：普通账号最高 1080P，大会员能到 4K / 8K。不要杜比视界（Obsidian 里放不了）。' });
    const durSel = select(row(opts, tab, '超过多长先不下'), BILI_DURATION, () => String(biliOpts().maxDuration), v => saveBili('maxDuration', parseInt(v, 10) || 0), { label: 'B 站时长上限' });
    opts.createDiv({ cls: 'setting-item-description lb-bili-note', text: '超过的先只记链接；想下哪几条，在下面「挑选要同步的…」里勾。' });
    select(row(opts, tab, '同时下几路'), BILI_WORKERS, () => String(biliOpts().workers), v => saveBili('workers', parseInt(v, 10) || 1), { label: 'B 站并行路数' });
    opts.createDiv({ cls: 'setting-item-description lb-bili-note', text: '路数多下得快，网络和硬盘也更忙；B 站一限流就自动退回一路接着下。电脑不太稳（比如下着下着蓝屏）就先用 1–2 路。' });
    const tg = (name, key) => row(opts, tab, name).addToggle(t => {
      let quiet = false;
      t.setValue(o[key] !== false).onChange(async v => {
        if (quiet) return;
        try { await saveBili(key, v); }
        catch (e) { quiet = true; try { t.setValue(!v); } finally { quiet = false; } plugin.notify('没保存上，开关已拨回原来的位置：' + errText(e), { kind: 'error' }); }
      });
    });
    tg('保存弹幕', 'danmaku');

    // —— 1031 作者「没有让我选哪些下载」：显眼的「挑选要同步的…」→ 弹窗里开关收藏夹（含稍后再看）、逐条勾超长视频（取代原来折叠的超长清单）——
    const pickBox = card.createDiv({ cls: 'lb-bili-pick-entry', attr: { 'data-section': 'bili-pick' } });
    const pickBtn = pickBox.createEl('button', { cls: 'lb-btn is-primary lb-bili-pick-btn', text: '挑选要同步的…' });
    const pickNote = pickBox.createDiv({ cls: 'setting-item-description lb-bili-note' });
    const paintPick = () => {
      const n = biliSkip(biliOpts()).length;
      pickNote.setText((n ? `现在跳过 ${n} 个收藏夹。` : '现在全部收藏夹和稍后再看都同步。') + '点开可以关掉不想同步的收藏夹、勾选超过时长也要下的视频。');
    };
    paintPick();
    pickBtn.onclick = () => biliPicker({
      onSaved: () => { paintPick(); try { durSel && durSel.setValue(String(biliOpts().maxDuration)); } catch {} },
      onSyncNow: () => runBtn.onclick(),
    });

    // —— 预估 / 立即同步 / 停止 ——
    const act = card.createDiv({ cls: 'lb-bili-actions', attr: { 'data-section': 'bili-sync' } });
    const estBtn = act.createEl('button', { cls: 'lb-btn', text: '预估' });
    const runBtn = act.createEl('button', { cls: 'lb-btn', text: '立即同步' });
    const stopBtn = act.createEl('button', { cls: 'lb-btn lb-bili-stop', text: '停止' });
    stopBtn.hidden = true; stopBtn.style.display = 'none';   // 同上：hidden 会被按钮样式盖掉
    const est = card.createDiv({ cls: 'lb-bili-estimate' });
    const last = card.createDiv({ cls: 'lb-bili-last', attr: { 'data-section': 'bili-last' } });
    const paintLast = l => {
      last.empty();
      const t = lastText(l);
      last.createDiv({ cls: 'lb-bili-last-main', text: '上次：' + t.main });
      if (t.sub) last.createDiv({ cls: 'lb-bili-last-sub', text: t.sub });
      // 1101 作者：待选清单那篇笔记（打勾 = 划掉、让人用命令行）太迷惑——直接打开「挑选要同步的…」弹窗勾要下的
      if (l && l.exists && (l.multi_p || (l.details || {}).long)) { const a = last.createEl('button', { cls: 'lb-link', text: '挑要下的视频…' }); a.onclick = () => pickBtn.onclick(); }
    };
    // 1031 作者：跑的时候还挂着上一趟的报错，看着像没在跑——开跑就换成进度，跑完再读回「上次」
    const paintLive = text => { last.empty(); last.createDiv({ cls: 'lb-bili-last-main', text }); };
    const loadLast = async () => {
      try { const r = await plugin.runPy(['-m', 'link_brain', 'bilibili', 'last', '--json'], { label: 'B 站上次同步', timeoutMs: 60000 }); paintLast(r.json); }
      catch (e) { last.empty(); plugin.failBox ? plugin.failBox(last, '上次同步', e, loadLast) : null; }
    };
    const mine = () => plugin.running === BILI_RUN_LABEL || plugin.running === BILI_EST_LABEL;
    const paintRunning = () => { const on = mine(); stopBtn.hidden = !on; stopBtn.style.display = on ? '' : 'none'; estBtn.disabled = runBtn.disabled = !!plugin.running; };
    stopBtn.onclick = async () => { if (await plugin.stopRunning()) { await loadLast(); } paintRunning(); };
    // 跑的时候每 3 秒读一次 last-sync.json 的进度（后端每条写一次），状态栏写「n/m 条」
    const watchProgress = since => {
      const timer = setInterval(async () => {
        if (plugin.running !== BILI_RUN_LABEL) { clearInterval(timer); return; }
        try {
          const j = JSON.parse(await plugin.app.vault.adapter.read(plugin.lbPath('_archive/bilibili-sync/last-sync.json')));
          const p = j && j.state === 'running' && j.progress;
          if (p && Date.parse(j.started_at || '') >= since - 60000) { plugin.runningProgress = `${p.done}/${p.total} 条`; plugin.taskChanged(); paintLive(`正在同步：第 ${p.done}/${p.total} 条`); }
        } catch {}
      }, 3000);
      return () => clearInterval(timer);
    };
    estBtn.onclick = async () => {
      if (plugin.running) { plugin.notify(plugin.busyText(), { kind: 'warn' }); return; }
      const done = plugin.busyButton(estBtn, '正在预估…');
      est.setText('正在读收藏夹（6 小时内扫过的直接复用，不重扫）…');
      paintRunning();
      try {
        const r = await plugin.run(biliSyncArgs(biliOpts(), { dryRun: true }), BILI_EST_LABEL, false, { quiet: true });
        const j = r && r.json;
        est.empty();
        if (!j) { est.setText(r && r.code === 6 ? plugin.busyText() : '没预估出来（已停止或后台出错）'); return; }
        if (!j.ok) { est.createDiv({ cls: 'lb-bili-warn', text: '⚠ ' + (j.message || '没预估出来') }); return; }
        est.createDiv({ cls: 'lb-bili-est-main', text: estimateText(j.estimate) || j.message });
        const e = j.estimate || {};
        if (e.basis) est.createDiv({ cls: 'setting-item-description', text: `都是估计：体积按${e.basis.size}；速度按${e.basis.speed}。` });
        if (j.counts && j.counts.multi_p) est.createDiv({ cls: 'setting-item-description', text: `另有超过 5 P 的多 P ${j.counts.multi_p} 条没算在内：在「挑选要同步的…」里勾了才下。` });
      } finally { done(); paintRunning(); }
    };
    runBtn.onclick = async () => {
      if (plugin.running) { plugin.notify(plugin.busyText(), { kind: 'warn' }); return; }
      if (biliStatus && biliStatus.state === 'logged_out') { plugin.notify('B 站还没登录：先点「扫码登录」', { kind: 'warn' }); return; }
      const done = plugin.busyButton(runBtn, '正在同步…');
      const started = Date.now();
      const pending = plugin.run(biliSyncArgs(biliOpts()), BILI_RUN_LABEL, true, { quiet: true });
      paintRunning();
      paintLive('正在同步：先读收藏夹（6 小时内扫过的直接复用），再一条条下');
      const stopWatch = watchProgress(started);
      plugin.notify('B 站收藏开始下载：底部状态栏能看进度、能停止；关掉设置页也照样在跑', { ms: 5000 });
      try {
        const r = await pending;
        const j = r && r.json;
        if (j) {
          const acts = j.counts && j.counts.multi_p ? [{ label: '挑要下的视频…', run: () => pickBtn.onclick() }] : null;
          plugin.notify(j.message || (j.ok ? '同步完成' : '同步没做完'), { kind: j.ok ? 'ok' : 'warn', ms: 8000, actions: acts });
        } else if (r && r.code !== 6) plugin.notify('B 站同步停了：已经下好的都在，再点「立即同步」只补没下的', { kind: 'warn' });
      } finally { stopWatch(); done(); paintRunning(); await loadLast(); }
    };
    const off = plugin.onTask ? plugin.onTask(paintRunning) : null;
    if (off) (tab.stops || (tab.stops = [])).push(off);   // 设置页关掉时（hide / disposeStops）注销
    paintRunning();
    loadLast();
  }

  // ———————————————————— ② 收藏与同步 ————————————————————
  // 唯一的「自动同步时间」编辑器：设置页②、首次设置「同步」一步用的都是它（里面是 schedule-ui.js 那一个组件；值只在后端计划任务里，两边读写同一份）；
  // 首页 / 同步记录「改定时」/ 账号弹窗「定时…」走 plugin.openSyncTime() → 打开设置页落到 data-section="sync-time"。
  // 1027：上面一行「同步」开关（开 = 按下面的时间注册 / 恢复计划任务；关 = 关掉），下面「同步时间」改了自动存（没有「保存定时」）。
  function syncTimeEditor(body, tab) {
    const wrap = body.createDiv({ cls: 'lb-sync-time', attr: { 'data-section': SYNC_TIME } });
    const sw = row(wrap, tab, '同步', '开着就按下面的时间自动收新收藏；电脑开着就行，不用开 Obsidian。', { cls: 'lb-sync-switch' });
    const when = row(wrap, tab, '同步时间', '按这台电脑上的时间。几条可以一起用，比如每周一 08:00 + 每天 16:00；改了自动保存。', { cls: 'lb-sched-row' });
    const host = wrap.createDiv({ cls: 'lb-sched-host' });
    let ed = null, toggle = null, quiet = false;
    const showTimes = on => { const hide = on === false; when.settingEl.toggleClass?.('is-hidden', hide); host.toggleClass?.('is-hidden', hide); };
    sw.addToggle(t => {
      toggle = t;
      t.setValue(false).onChange(async v => {
        if (quiet || !ed) return;
        t.setDisabled?.(true);
        const res = await ed.setEnabled(v);
        t.setDisabled?.(false);
        if (!res || !res.ok) { quiet = true; try { t.setValue(!v); } finally { quiet = false; } plugin.notify((v ? '没打开：' : '没关上：') + ((res && res.error) || '原因不明'), { kind: 'error' }); }
      });
    });
    safe(tab, wrap, '自动同步', () => {
      ed = plugin.scheduleUI().render(host, {
        onState: on => { showTimes(on); if (toggle && on != null && toggle.getValue() !== on) { quiet = true; try { toggle.setValue(on); } finally { quiet = false; } } },
      });
      wrap.lbReady = ed.ready;
      tab.stops.push(() => ed.destroy());
    });
    return ed;
  }
  function syncRows(body, tab) {
    const so = S().sync;
    const ed = syncTimeEditor(body, tab);
    tab.fieldDailyLimit(body);
    sub(body, '存哪些');
    tab.toggleRow(body, '图片', '', () => so.downloadImages, v => { so.downloadImages = v; }, { help: '关掉只存文字和图片地址。' });
    tab.toggleRow(body, '视频', '', () => so.downloadVideo, v => { so.downloadVideo = v; }, { help: '关掉只存封面和链接，省硬盘。' });
    tab.fieldCommentFloors(body);
    return ed;
  }
  // 1031 作者：「小红书和 B 站会混淆」——顶上一个切换（小红书 · 实时同步 / B 站 · 暂不支持实时同步），选哪个只出哪个的设置。
  // 每次打开设置页默认小红书（别处「改定时」跳过来的锚点都在小红书那页）。
  // 1101：首次设置「同步」一步也用这个切换（小红书一页 = 同步时间 / 存哪些，B 站一页 = 同步选项 / 挑选 / 立即同步）
  function platPanes(g) {
    const sw = g.createDiv({ cls: 'lb-plat-switch', attr: { role: 'tablist', 'data-section': 'sync-switch' } });
    const paneX = g.createDiv({ cls: 'lb-plat-pane', attr: { 'data-platform': 'xhs' } });
    const paneB = g.createDiv({ cls: 'lb-plat-pane', attr: { 'data-platform': 'bilibili' } });
    const tabs = [['xhs', '小红书', '实时同步', paneX], ['bilibili', 'B 站', '暂不支持实时同步 · 手动同步', paneB]].map(([id, name, note, pane]) => {
      const t = sw.createEl('button', { cls: 'lb-plat-tab', attr: { role: 'tab', 'data-platform': id } });
      t.type = 'button';
      t.createSpan({ cls: 'lb-plat-name', text: name });
      t.createSpan({ cls: 'lb-plat-note', text: note });
      t.onclick = () => pick(id);
      return { id, t, pane };
    });
    const pick = id => { for (const x of tabs) { const on = x.id === id; x.t.classList.toggle('is-on', on); x.t.setAttribute('aria-selected', String(on)); x.pane.hidden = !on; } };
    pick('xhs');
    // 1031：目录页侧栏「去同步 →」落在 B 站那一页（focusSection 往上找到藏着的平台页就先切过去）
    for (const x of tabs) x.pane.lbShow = () => pick(x.id);
    return { paneX, paneB, pick };
  }
  function groupSync(g, tab) {
    const s = S(), so = s.sync;
    const { paneX, paneB } = platPanes(g);
    sub(paneX, '同步');
    safe(tab, paneX, '收藏同步', () => tab.stops.push(plugin.renderSyncRow(paneX, { compact: true })));
    syncRows(paneX, tab);
    const bili = paneB.createDiv({ cls: 'lb-bili lb-bili-sync', attr: { 'data-section': 'sync-bili' } });
    safe(tab, bili, 'B 站同步', () => biliSync(bili, tab));
    more(paneX, tab, 'sync-more', b => {
      tab.fieldCollectionFolder(b);
      tab.toggleRow(b, '登录后马上同步', '', () => so.autoAfterLogin, v => { so.autoAfterLogin = v; }, { help: '第一次扫码登录成功后就开始同步。' });
      tab.fieldPerRunLimit(b);
      tab.fieldFillPace(b);
      const att = b.createDiv({ attr: { 'data-section': 'attach' } });
      tab.fieldDownloadFolder(att);
      tab.numberField(att, '等下载最多', '', { get: () => s.downloads.waitMinutes, set: v => s.downloads.waitMinutes = v, def: 5, unit: '分钟',
        help: '你手动下载附件时，在下载文件夹里等文件出现多久。' }).then(r => r.controlEl.createSpan({ cls: 'lb-unit', text: '分钟' }));
      tab.link(row(att, tab, '还没下到的附件', '自动下不来的附件，在这里一篇一篇手动补。'), '查看', async () => {
        try {
          const data = plugin.catalogCache?.data || JSON.parse(await plugin.app.vault.adapter.read(plugin.lbPath('_archive/catalog-data.json')));
          plugin.openAttachments(data.items.filter(it => it.attachment === '待补'));
        } catch (e) { plugin.notify('这一块暂时读不到：' + e.message, { kind: 'error' }); }
      }, '列出还没下到附件的笔记');
      tab.link(row(b, tab, '同步记录', '每次同步收了几篇、哪里没做成。'), '打开', () => plugin.openSyncLog?.(), '打开同步记录');
    }, { holds: ['attach', 'collect'] });
  }

  // ———————————————————— ③ 目录与批注 ————————————————————
  function groupCatalog(g, tab) {
    const s = S();
    const look = row(g, tab, '目录的样子', '布局、字体、字号都在目录页点「编排」改（编排里的「Aa 样式」）；这里不另放一套。', { section: 'catalog-look' });
    tab.link(look, '去目录编排 ↗', () => plugin.openCatalogArrange?.(), '打开目录并进入编排');
    look.controlEl.querySelector?.('button')?.removeClass?.('lb-link');
    row(g, tab, '批注署名', '笔记底下你写的批注署这个名字；空着就不署名。', { section: 'annot' })
      .addText(t => t.setPlaceholder('不署名').setValue(s.nickname || '').onChange(async v => { s.nickname = v.trim(); await tab.save(); }));
    // 1101 作者「设置里的自定义：小红书点赞到千 / 万的不显示点赞数」：卡片右下角的 ♡ 数，到这个数就不写（目录页就地换）
    row(g, tab, '点赞数', '小红书卡片右下角的 ♡ 点赞数。', { section: 'likes' })
      .addDropdown(d => {
        for (const [v, t] of [['0', '都显示'], ['1000', '上千的不显示'], ['10000', '上万的不显示']]) d.addOption(v, t);
        d.setValue(String(Number(s.catalogHideLikesFrom) || 0)).onChange(async v => {
          s.catalogHideLikesFrom = Number(v) || 0; await tab.save();
          plugin.app.workspace?.trigger?.('link-brain:catalog-prefs');
        });
      });
    more(g, tab, 'catalog-more', b => {
      row(b, tab, '留言对象', '批注开头写「@名字」，就算留给它的话（比如你的 AI 助手）；空着不启用。')
        .addText(t => t.setPlaceholder('不启用').setValue(s.annotateMention || '').onChange(async v => { s.annotateMention = v.trim(); await tab.save(); }));
      tab.fieldCategories(b);
    }, { holds: ['catalog', 'index'] });
  }

  // ———————————————————— ④ 高级功能 ————————————————————
  // 一项功能一个控件（作者：别先开一层再进另一页改模式）；底下的双重门禁（setup.selected 和各能力的 mode）在这里一起对上：
  //   语音转文字：关闭 / 本机（setup 'asr' + asrAI.mode=capswriter）/ 在线接口（asrAI.mode=http）；
  //   识图：关闭（'ocr' 关，识图跟着关）/ 本机认字（'ocr' 开、'ai_vision' 关）/ 本机认字 + AI 识图（'ai_vision' 开）；
  //   问答模型：问收藏页下拉里的同一个值（activeModel）；「关闭」= 'ai_text' 关（问答、概要、按意思搜是同一个开关，三行都如实显示关）；
  //   概要与标签：关闭（summaryAI.mode=off）/ 跟随问答模型（inherit）/ 单独配置（http 或命令行，细项在「更多 → 接口与密钥」）；
  //   按意思搜：embedAI.mode（没配过的关了再开 = 回到后端默认，不留一个空的 embedAI）。打开概要 / 按意思搜 / 选模型都顺手打开 'ai_text'。
  const selectedOf = () => { const su = S().setup || {}; return Array.isArray(su.selected) ? su.selected : null; };
  // 和后端 providers.gate 同一规则：选过（列表）+ 对齐过（aiSynced）+ 没勾 = 关
  const gated = comp => { const su = S().setup || {}, sel = selectedOf(); return !!(sel && su.aiSynced && !sel.includes(comp)); };
  const planOn = id => { const h = home(); if (h && h.state && h.state().plan) return h.isOn(id); const sel = selectedOf(); return sel ? sel.includes(id) : null; };
  const asrValue = () => { const m = (S().asrAI || {}).mode; return m === 'http' ? 'http' : m === 'capswriter' || m === 'media' ? 'local' : 'off'; };
  const visionValue = () => {
    const ocrOn = planOn('ocr'); const ocr = ocrOn == null ? (S().ocr || {}).mode !== 'off' : ocrOn;
    if (!ocr) return 'off';
    return gated('ai_vision') || planOn('ai_vision') === false ? 'local' : 'ai';
  };
  const textOn = () => !gated('ai_text');
  const askValue = () => (textOn() ? (S().activeModel || '') : 'off');
  const summaryValue = () => { const m = (S().summaryAI || {}).mode; return !textOn() || m === 'off' ? 'off' : (!m || m === 'inherit') ? 'inherit' : 'custom'; };
  const embedValue = () => textOn() && (!S().embedAI || S().embedAI.mode !== 'off');
  const RUNTIME = ['setup', 'ocr', 'asrAI', 'textAI', 'summaryAI', 'visionAI', 'voice', 'embedAI', 'activeModel'];
  async function apply(change) {
    const s = S();
    const snap = JSON.parse(JSON.stringify(Object.fromEntries(RUNTIME.map(k => [k, s[k]]))));
    try { await change(); }
    catch (e) { for (const k of RUNTIME) s[k] = snap[k]; throw e; }
    delete cache.usage;
    plugin.app.workspace?.trigger?.('link-brain:models-changed');
  }
  // 还没选过（setup.selected 不是列表）= 后端不拦（fail-open）：先按「现在实际在跑的」落成一份列表再改，免得「关闭」点了没反应
  const materialize = () => {
    const s = S();
    s.setup = s.setup && typeof s.setup === 'object' ? s.setup : {};
    if (Array.isArray(s.setup.selected)) return;
    const on = ['core', 'reader', 'dataview'];
    if ((s.ocr || {}).mode !== 'off') on.push('ocr');
    if ((s.asrAI || {}).mode === 'capswriter') on.push('asr');
    if (s.voice && s.voice.capsLock) on.push('capslock');
    on.push('ai_text');
    if (on.includes('ocr')) on.push('ai_vision');
    s.setup.selected = on; s.setup.aiSynced = true;
  };
  const feature = async (id, on) => { const h = home(); if (!h) throw new Error('功能清单没加载上：重启一次 Obsidian 再试'); materialize(); await h.setFeature(id, on); };
  const ensureText = async () => { if (gated('ai_text')) await feature('ai_text', true); };
  async function setAsr(v) {
    const s = S(); s.asrAI = s.asrAI || {};
    await apply(async () => {
      if (v === 'http') { s.asrAI.mode = 'http'; await plugin.saveSettings(); return; }
      if (v === 'local') {
        if (s.asrAI.mode !== 'capswriter') s.asrAI.mode = 'off';
        await feature('asr', true);
        if (s.asrAI.mode !== 'capswriter') { s.asrAI.mode = 'capswriter'; await plugin.saveSettings(); }
        return;
      }
      if (planOn('asr')) await feature('asr', false);
      if (s.asrAI.mode !== 'off') { s.asrAI.mode = 'off'; await plugin.saveSettings(); }
    });
  }
  async function setVision(v) {
    await apply(async () => {
      if (v === 'off') return feature('ocr', false);
      if (v === 'local') { await feature('ocr', true); if (planOn('ai_vision')) await feature('ai_vision', false); return; }
      await feature('ai_vision', true);
    });
  }
  async function setAsk(v) {
    const s = S();
    await apply(async () => {
      if (v === 'off') return feature('ai_text', false);
      s.activeModel = v;
      await plugin.saveSettings();
      await ensureText();
    });
  }
  async function setSummary(v) {
    const s = S(); const cfg = s.summaryAI || (s.summaryAI = {});
    await apply(async () => {
      if (v === 'off') { if (cfg.mode && cfg.mode !== 'off') cfg.prevMode = cfg.mode; cfg.mode = 'off'; await plugin.saveSettings(); return; }
      if (v === 'inherit') { cfg.mode = 'inherit'; delete cfg.prevMode; }
      else { cfg.mode = ['http', 'cli'].includes(cfg.prevMode) ? cfg.prevMode : ['http', 'cli'].includes(cfg.mode) ? cfg.mode : 'http'; delete cfg.prevMode; }
      await plugin.saveSettings();
      await ensureText();
    });
  }
  async function setEmbed(on) {
    const s = S();
    await apply(async () => {
      if (!on) {
        if (!s.embedAI) s.embedAI = { mode: 'off', wasDefault: true };   // 原来没配过：记一下，再打开就回到后端默认
        else { if (s.embedAI.mode && s.embedAI.mode !== 'off') s.embedAI.prevMode = s.embedAI.mode; s.embedAI.mode = 'off'; }
        await plugin.saveSettings(); return;
      }
      if (s.embedAI && s.embedAI.wasDefault) s.embedAI = undefined;   // 存盘时 undefined 不写出去 = 回到「没配过」（后端照旧跟着问答那家走）
      else if (s.embedAI) { s.embedAI.mode = s.embedAI.prevMode || (s.embedAI.mode === 'off' ? 'http' : s.embedAI.mode || 'http'); delete s.embedAI.prevMode; }
      await plugin.saveSettings();
      await ensureText();
    });
  }
  // 功能那几行（④ 和首次设置第 3 步共用）；返回 repaint（功能清单读回来后把下拉对上实际值）
  function featureRows(g, tab, { guide = false } = {}) {
    const s = S();
    const ctl = {};
    if (!guide) row(g, tab, '转 Markdown', '附件里的 PDF、Word 自动转成文字存在本机，扫描件走本机认字；不用设置，不花钱。', { icon: 'doc', section: 'ai-docconv' })
      .controlEl.createSpan({ cls: 'lb-feat-tag', text: 'PDF / Word · 本机免费 · 自动' });
    const asr = row(g, tab, '语音转文字', '把视频里说的话转成文字，搜得到。本机免费；在线接口按用量付费（接口在「更多 → 接口与密钥」）。', { icon: 'audio', section: 'ai-asr' });
    ctl.asr = select(asr, [['off', '关闭'], ['local', '本机 · 免费'], ['http', '在线接口']], asrValue, v => setAsr(v).then(() => repaint()), { label: '语音转文字' });
    const vis = row(g, tab, '识图', '认出图片里的字（本机，免费）；选 AI 还会看懂表格、流程图并描述图片（要 key）。', { icon: 'image', section: 'ai-vision' });
    ctl.vision = select(vis, [['off', '关闭'], ['local', '本机认字 · 免费'], ['ai', '本机认字 + AI 识图']], visionValue, v => setVision(v).then(() => repaint()), { label: '识图' });
    const models = () => (s.models || []).filter(m => m && m.name && !m.hidden).map(m => [m.name, m.name]);
    const ask = row(g, tab, '问答模型', '问收藏用哪个模型（和问收藏页输入框右边的下拉是同一个）。选「关闭」= 问答、概要、按意思搜都不用 AI。', { icon: 'chat', section: 'ask-model' });
    ctl.ask = select(ask, [...models(), ['off', '关闭']], askValue, v => setAsk(v).then(() => repaint()), { label: '问答模型' });
    const sum = row(g, tab, '概要与标签', '每篇自动写概要、打标签，不动你手改的。「单独配置」在「更多 → 接口与密钥 → 概要与标签」里选接口或命令行。', { icon: 'summary', section: 'ai-summary' });
    ctl.summary = select(sum, [['off', '关闭'], ['inherit', '跟随问答模型'], ['custom', '单独配置']], summaryValue, v => setSummary(v).then(() => repaint()), { label: '概要与标签' });
    const emb = row(g, tab, '按意思搜', '按意思找相近的收藏（搜「便宜的火锅」也能找到「人均 50 的锅子」）；关掉照样能按关键词搜。', { icon: 'search', section: 'ai-embed' });
    emb.addToggle(t => {
      ctl.embed = t;
      let reverting = false;
      t.setValue(embedValue()).onChange(async v => {
        if (reverting || ctl.quiet) return;
        try { await setEmbed(v); }
        catch (e) { reverting = true; try { t.setValue(!v); } catch {} finally { reverting = false; } plugin.notify('没保存上，开关已拨回原来的位置：' + errText(e), { kind: 'error' }); return; }
        repaint();
      });
    });
    // 选了要 key 的但还没配：那一行下面一句 + 去填（落到「接口与密钥」那一格）
    const hint = (r, text, cap) => {
      let el = r.descEl.querySelector?.('.lb-feat-need');
      if (!text) { el?.remove?.(); return; }
      if (!el) el = r.descEl.createDiv({ cls: 'lb-feat-need' });
      el.empty?.(); el.createSpan({ text });
      if (cap && !guide) { const b = el.createEl('button', { cls: 'lb-link', text: '去填' }); b.onclick = () => openApiFor(tab, cap); }
    };
    const ready = cap => { const c = s[cap] || {}; return c.mode === 'cli' ? !!(c.command || c.preset) : !!(c.endpoint && (c.apiKey || c.keyFile || c.apiKeyEnv || c.keyPool)); };
    function paintHints() {
      hint(vis, visionValue() === 'ai' && !ready('visionAI') ? '还没配识图用的接口和 key' : '', 'vision');
      hint(asr, asrValue() === 'http' && !(s.asrAI && s.asrAI.endpoint) ? '还没填在线接口' : '', 'asr');
      hint(sum, summaryValue() === 'custom' && !ready('summaryAI') ? '单独配置还没填好' : '', 'summary');
      const m = (s.models || []).find(x => x.name === s.activeModel) || {};
      hint(ask, askValue() !== 'off' && (!m.mode || m.mode === 'inherit') && !ready('textAI') ? '问答用的接口和 key 还没填' : '', 'ask');
    }
    function repaint() {
      const set = (d, v) => { try { if (d && d.getValue() !== v) d.setValue(v); } catch {} };
      set(ctl.asr, asrValue()); set(ctl.vision, visionValue()); set(ctl.ask, askValue()); set(ctl.summary, summaryValue());
      if (ctl.embed && ctl.embed.getValue() !== embedValue()) { ctl.quiet = true; try { ctl.embed.setValue(embedValue()); } catch {} finally { ctl.quiet = false; } }
      paintHints();
    }
    paintHints();
    const h = home();
    let alive = true; if (tab.stops) tab.stops.push(() => { alive = false; });
    if (h && h.state && !h.state().plan) h.loadPlan().then(() => { if (alive) repaint(); }).catch(() => {});
    return repaint;
  }
  function openApiFor(tab, cap) {
    const v = tab.view ? tab.view() : {};
    v.apiCap = cap;
    const box = tab.containerEl?.querySelector?.('[data-section="ai-keys"]');
    if (box && box.lbPick) box.lbPick(cap);
    focusSection(tab, 'ai-keys');
  }
  // 「更多 → 接口与密钥」：先选哪一项，下面是这一项的接口 / 模型 / key / 测试（一次只看一项）；最上面「粘一把 key」
  function apiConfig(b, tab, usageP) {
    const s = S();
    const box = b.createDiv({ cls: 'lb-api', attr: { 'data-section': 'ai-keys' } });
    // 旧版「本机千问配置」（mode=media）：只如实说一句，不在界面里偷偷改写；改了对应那一格就存成新格式
    if (['textAI', 'visionAI', 'asrAI', 'ocr'].some(k => s[k] && s[k].mode === 'media'))
      box.createEl('p', { cls: 'setting-item-description lb-legacy-note', text: '你的设置里还有旧版「本机千问配置」：程序已经按等价的新设置在跑（识图、概要走千问兼容接口，语音走本机 CapsWriter，认字在本机）。改一下对应那一格就会存成新格式。' });
    // 一把 key 都没有时这一格在「高级功能」最上面（只留一处）；有了 key 才回到这里
    if (hasAnyKey()) keyBox(box, tab, { onDone: () => draw() });
    else box.createEl('p', { cls: 'setting-item-description', text: '还没有 key：在「高级功能」最上面粘一把。' });
    const CAPS = [['ask', '问答模型'], ['summary', '概要与标签'], ['vision', 'AI 识图'], ['refine', '精细识图'], ['asr', '语音转文字（在线）'], ['embed', '按意思搜']];
    const v = tab.view ? tab.view() : {};
    const pick = row(box, tab, '配置哪一项', '一次只看一项：它用哪个接口、模型、key，下面就能测。', { section: 'ai-keys-pick' });
    let dd = null;
    pick.addDropdown(d => { dd = d; for (const [id, n] of CAPS) d.addOption(id, n); d.setValue(v.apiCap || 'ask'); d.onChange(x => { v.apiCap = x; draw(); }); });
    const route = box.createDiv({ cls: 'setting-item-description lb-api-route' });
    const area = box.createDiv({ cls: 'lb-api-fields' });
    box.lbPick = cap => { v.apiCap = cap; try { dd.setValue(cap); } catch {} draw(); };
    const redraw = () => draw();
    area.redraw = redraw;
    function draw() {
      const cap = v.apiCap || 'ask';
      area.empty();
      usageP.then(u => { route.setText(u ? (pages.routeText(u, cap === 'ask' ? 'ask' : cap) ? '现在：' + pages.routeText(u, cap === 'ask' ? 'ask' : cap) : '') : ''); }).catch(() => route.setText(''));
      safe(tab, area, '接口与密钥', () => ({
        ask: () => {
          if (s.textAI.mode === 'cli') {
            area.createEl('p', { cls: 'setting-item-description', text: '问收藏 · 概要现在用本机命令行（在「CLI 与外接 MCP → 本机命令行」里换）。' });
            tab.textField(area, '自己写命令', '', 'codex exec --skip-git-repo-check -', () => s.textAI.command, x => { s.textAI.command = x; if (x) delete s.textAI.preset; },
              false, { help: '问题从标准输入送进去、回答从标准输出读回来；选了「本机命令行」里的程序就不用填。' });
          } else tab.httpFields(area, s.textAI, { modelHint: 'deepseek-v4-flash', modelDesc: '' });
          tab.addTestButton(area, '测试（发一句话，几乎不花钱）', ['-m', 'link_brain', 'selftest', 'text']);
          sub(area, '问收藏页能换的模型', 'models');
          tab.renderChatModels(area);
        },
        summary: () => {
          const m = s.summaryAI.mode || 'inherit';
          if (m === 'off') { area.createEl('p', { cls: 'setting-item-description', text: '概要关着：在上面「概要与标签」里打开。' }); return; }
          if (m === 'inherit') {
            tab.textField(area, '只换模型名', '', s.textAI.model || '', () => s.summaryAI.model, x => s.summaryAI.model = x, false, { help: '空着 = 和问答用同一个模型；填了只换模型名，接口和 key 照旧。' });
          } else {
            tab.modeSetting(area, '单独配置用什么', '', s.summaryAI, [['http', '另配一个接口'], ['cli', '本机命令行（不要 key、不花钱）']],
              { help: '本机命令行（Codex / Claude Code / OpenCode）用它自己的登录，每篇慢一些。' });
            if (s.summaryAI.mode === 'cli') tab.cliPicker(area, s.summaryAI);
            else tab.httpFields(area, s.summaryAI, { modelHint: 'qwen3.7-flash / gpt-4o-mini', modelDesc: '' });
          }
          tab.addTestButton(area, '测试概要模型（发一段短文，几乎不花钱）', ['-m', 'link_brain', 'selftest', 'summary']);
        },
        vision: () => {
          tab.httpFields(area, s.visionAI, { modelHint: 'qwen3.8-flash', modelDesc: '' });
          tab.addTestButton(area, '测试识图（发一张小图，几乎不花钱）', ['-m', 'link_brain', 'selftest', 'vision']);
        },
        refine: () => {
          const own = s.visionAI.refine && typeof s.visionAI.refine === 'object';
          if (own) {
            area.createEl('p', { cls: 'setting-item-description', text: '精细识图（第二层）单独配了接口：' });
            tab.httpFields(area, s.visionAI.refine, { modelHint: 'qwen3.8-max', modelDesc: '' });
          } else area.createEl('p', { cls: 'setting-item-description', text: '精细识图和识图用同一个接口和 key；模型名在「识别细项 → 精细识图模型」里改。' });
        },
        asr: () => {
          if (s.asrAI.mode !== 'http') { area.createEl('p', { cls: 'setting-item-description', text: '语音转文字现在不用在线接口：在上面「语音转文字」选「在线接口」才用这里。' }); return; }
          tab.httpFields(area, s.asrAI, { modelHint: 'whisper-1', modelDesc: '', kind: 'asr' });
          tab.addTestButton(area, '测试语音转文字（发 1 秒录音，几乎不花钱）', ['-m', 'link_brain', 'selftest', 'asr']);
        },
        embed: () => {
          if (!s.embedAI || s.embedAI.wasDefault) {
            area.createEl('p', { cls: 'setting-item-description', text: '按意思搜现在用默认：跟着问答 / 识图那家的千问 key 走，一般不用动。' });
            tab.link(new Setting(area).setName('单独配一个接口'), '单独配置', async () => {
              s.embedAI = { mode: embedValue() ? 'http' : 'off' };
              try { await plugin.saveSettings(); } catch (e) { s.embedAI = undefined; plugin.notify('没保存上：' + errText(e), { kind: 'error' }); }
              draw();
            }, '给按意思搜单独填接口和 key');
            return;
          }
          tab.httpFields(area, s.embedAI, { modelHint: 'text-embedding-v4', modelDesc: '', kind: 'embed' });
        },
      })[cap]());
    }
    draw();
    return box;
  }
  // 这台电脑上配过任何一把在线接口的 key 没有（只看设置，不联网）
  function hasAnyKey() {
    const s = S();
    const has = c => !!(c && (c.apiKey || c.keyFile || c.apiKeyEnv || (Array.isArray(c.keyPool) ? c.keyPool.length : c.keyPool)));
    return ['textAI', 'visionAI', 'summaryAI', 'asrAI', 'embedAI', 'refineAI', 'ocr'].some(k => has(s[k])) || (s.models || []).some(has);
  }
  function groupAdvanced(g, tab) {
    const s = S();
    // 1027b 作者：「作为初次使用者，填 api key 是否不太方便？」——是：要点开「＋ 更多」才看得到。一把都没有时直接摆在最上面
    if (!hasAnyKey()) {
      const first = g.createDiv({ cls: 'lb-key-first', attr: { 'data-section': 'ai-key-first' } });
      first.createEl('p', { cls: 'lb-key-first-lead', text: '本机的功能（转 Markdown、本机认字、本机语音）不用 key 就能用。要用 AI 识图、问收藏、概要，先粘一把 API key：' });
      keyBox(first, tab, { onDone: () => tab.display() });
    }
    featureRows(g, tab);
    const usageP = loadUsage().catch(() => null);
    // key 用不了 / 额度用完：一句 + 去充值 + 换 key（落到「更多 → 接口与密钥」那一格，粘新 key 就换掉坏的那几格）
    const trouble = g.createDiv({ cls: 'lb-key-trouble', attr: { 'data-section': 'key-trouble' } });
    usageP.then(u => {
      for (const k of keyTrouble(u).slice(0, 3)) {
        const line = trouble.createDiv({ cls: 'lb-fix-line' });
        line.createSpan({ text: k.text });
        const l = { ...((pages.LINKS || {})[k.id] || {}), ...(((u && u.links) || {})[k.id] || {}) };
        if (l.recharge || l.console) { const a = line.createEl('button', { cls: 'lb-link', text: l.recharge ? '去充值 ↗' : '去控制台 ↗' }); a.onclick = () => openUrl(l.recharge || l.console); }
        const ch = line.createEl('button', { cls: 'lb-link', text: '换 key' });
        ch.onclick = () => focusSection(tab, 'ai-key-paste');
      }
    });
    sub(g, 'AI 控制台', 'ai-console-head');
    const v = tab.view ? tab.view() : {};
    v.console ||= {};
    safe(tab, g, 'AI 控制台', () => { const c = plugin.usageUI().renderConsole(g, tab, { load: force => loadUsage(!!force), view: v.console }); tab.stops.push(c.stop); });
    more(g, tab, 'ai-more', b => {
      sub(b, '接口与密钥');
      apiConfig(b, tab, usageP);
      sub(b, '服务商与余额', 'ai-providers');
      const ring = b.createDiv({ cls: 'lb-keyring' });
      ring.createEl('p', { cls: 'setting-item-description lb-loading', text: '正在读各家的情况…' });
      usageP.then(async u => {
        if (!u) { ring.empty(); plugin.failBox?.(ring, '服务商', new Error('用量没读出来'), () => { loadUsage(true); tab.display(); }); return; }
        pages.renderKeyring(ring, u, tab);
        try {   // 余额要联网（DeepSeek 一次请求），后到后只换这一块
          const r = await plugin.runPy(['-m', 'link_brain', 'usage', '--balance'], { label: '查余额', timeoutMs: 30000, fallback: '余额没查到' });
          if (r && r.json && r.json.ok !== false) pages.renderKeyring(ring, { ...u, balances: r.json.balances || {}, keys: r.json.keys || u.keys }, tab);
        } catch (e) { console.error('[lb] 余额没查到', e); }
      });
      sub(b, '识别细项', 'ai-recog');
      const pair = b.createDiv({ cls: 'lb-pair' });
      recogRows(pair, tab);
      sub(b, '问答细项', 'ai-ask');
      const pair2 = b.createDiv({ cls: 'lb-pair' });
      askRows(pair2, tab);
      sub(b, '提示词', 'ai-prompts');
      tab.renderPrompts(b);
      sub(b, '问收藏的写法', 'skills');
      tab.renderSkillsTab(b);
    }, { holds: ['ai-keys', 'ai-key-paste', 'ai-keys-pick', 'ai-providers', 'ai-recog', 'ai-ask', 'ai-prompts', 'skills', 'skills-hidden', 'models', 'prompts'] });
  }
  // 识别细项（两列）：CapsLock 说话 · CapsWriter 在哪 · 本机语音的端口 · 视频画面里的字 · 本机认字精度 · 认字模型在哪 · 精细识图模型 · 测试
  function recogRows(c, tab) {
    const s = S(), h = home();
    const caps = row(c, tab, '按 CapsLock 说话', '在任何软件里按住 CapsLock 说话、松开就出字；用本机的语音转文字，要先把「语音转文字」选成「本机」。', { section: 'ai-capslock' });
    caps.settingEl.setAttribute?.('data-id', 'capslock');
    if (h) safe(tab, c, '按 CapsLock 说话', () => h.featureToggle(caps, 'capslock'));
    if (asrValue() !== 'local') { caps.settingEl.addClass('is-disabled'); caps.controlEl.querySelector?.('.checkbox-container')?.setAttribute?.('aria-disabled', 'true'); caps.settingEl.setAttribute?.('title', '先把「语音转文字」选成「本机」'); }
    row(c, tab, 'CapsWriter 装在哪', '空着 = 自动找（含 start_client.exe 的文件夹）。')
      .addText(t => t.setPlaceholder('例如 C:\\CapsWriter-Offline').setValue(s.voice.capsWriterDir || '').onChange(async v => { s.voice.capsWriterDir = v.trim(); await tab.save(); }));
    tab.textField(c, '本机语音识别的端口', '', '6016', () => String(s.asrAI.port || ''), v => s.asrAI.port = v, false, { help: '空着 = 读 CapsWriter 自己的设置（出厂是 6016）。' });
    tab.toggleRow(c, '认视频画面里的字', '', () => s.visionAI.videoScreenText !== false, v => { s.visionAI.videoScreenText = v; },
      { help: '字幕、文字卡也收进笔记和搜索；每 2 秒抽一帧认字，最长看前 3 分钟，只占本机 CPU，不花钱。' });
    const tier = row(c, tab, '本机认字精度', '「标准」认得准；电脑配置很低就选「轻量」。标准多占约 180 MB 内存、慢约 3 倍。');
    select(tier, [['medium', '标准'], ['small', '轻量']], () => s.ocr.modelTier || 'medium', async v => {
      const prev = s.ocr.modelTier; s.ocr.modelTier = v;
      try { await plugin.saveSettings(); } catch (e) { s.ocr.modelTier = prev; throw e; }
    }, { label: '本机认字精度' });
    tab.textField(c, '认字模型放在哪', '', '空着就行', () => s.ocr.modelDir, v => s.ocr.modelDir = v, false, { help: '空着 = 自动下载。已经下好 PP-OCRv6 模型的，填它所在的文件夹。' });
    // 精细识图模型：真正起作用的是 visionAI.refine.model（单独配了第二层时）→ 否则 refineModel → 否则和识图同一个；改的就是起作用的那一个
    const own = () => s.visionAI.refine && typeof s.visionAI.refine === 'object';
    tab.textField(c, '精细识图模型', '', s.visionAI.model || '跟随识图', () => (own() ? s.visionAI.refine.model : s.visionAI.refineModel), v => { if (own()) s.visionAI.refine.model = v; else s.visionAI.refineModel = v; },
      false, { help: '只用来重看少数要紧的图（流程图、大表格、第一遍靠不住的）；空着 = 和识图同一个模型。' + (own() ? '（现在改的是单独配的第二层）' : '') });
    tab.addTestButton(c, '测试认字（本机跑，不花钱）', ['-m', 'link_brain', 'selftest', 'ocr']);
    tab.addTestButton(c, asrValue() === 'http' ? '测试语音转文字（发 1 秒录音，几乎不花钱）' : '测试语音转文字（本机跑，不花钱）', ['-m', 'link_brain', 'selftest', 'asr']);
  }
  // 问答细项（两列）：扩展同义词 · 回答长度上限 · 给模型看的字数 · 每篇摘录字数 · 参考篇数（都是发给模型的预算，不是收藏库的上限）
  function askRows(c, tab) {
    const s = S();
    tab.toggleRow(c, '扩展同义词', '', () => s.retrieval.queryExpand !== false, v => { s.retrieval.queryExpand = v; },
      { help: '提问时先想几个同义词、地名、角色一起搜；每问多一次很小的调用（用写概要的模型），和检索同时跑。' });
    const n = (name, get, set, def, help, unit = '') => tab.numberField(c, name, '', { get, set, def, help }).then(r => { if (unit) r.controlEl.createSpan({ cls: 'lb-unit', text: unit }); });
    n('回答长度上限', () => s.textAI.maxTokens, v => s.textAI.maxTokens = v, 1200, '模型一次最多写这么多 token（约等于字数）。', 'token');
    n('给模型看的字数', () => s.retrieval.totalCharLimit, v => s.retrieval.totalCharLimit = v, 8000, '从收藏里摘出来、一起发给模型的字数上限。', '字');
    n('每篇摘录字数', () => s.retrieval.fragChars, v => s.retrieval.fragChars = v, 800, '每篇收藏摘一段，这段最长多少字。', '字');
    n('参考篇数', () => s.retrieval.topK, v => s.retrieval.topK = v, 8, '一次至少拿几篇收藏给模型看（字数够时会多拿几篇）。', '篇');
  }

  // ———————————————————— ⑤ CLI 与外接 MCP ————————————————————
  // 本机命令行 = LWA 用哪个 AI（textAI 走命令行时用哪个程序：Codex / Claude Code / OpenCode…，表从后端 usage --table 读）；
  // 让其他 AI 读收藏 = 别的 AI 怎么读 LWA（电脑端一个开关接上 · 网页端要你自己的网址）。两件事分开写，不把命令行当成一条外接。
  function cliRow(c, tab) {
    const s = S();
    const r = row(c, tab, '命令行程序', '用它自己的登录，不要 key，LWA 不替它算钱；选了就问收藏、写概要（跟随问答时）都用它，每问约 20 秒。选「不用」= 用接口。', { section: 'cli' });
    const host = r.controlEl.createDiv({ cls: 'lb-cli-host' });
    host.createSpan({ cls: 'setting-item-description lb-loading', text: '读取中…' });
    const paint = (table, err) => {
      host.empty();
      if (!table) { plugin.failBox?.(host, '', err || new Error('命令行列表没读到'), () => { plugin.aiTableCache = null; tab.display(); }); return; }
      const list = table.cli || [];
      const sel = host.createEl('select', { cls: 'dropdown', attr: { 'aria-label': '命令行程序' } });
      sel.createEl('option', { text: '不用（用接口）', attr: { value: '' } });
      for (const x of list) sel.createEl('option', { text: x.name, attr: { value: x.id } });
      const curId = () => { if (s.textAI.mode !== 'cli') return ''; const x = s.textAI.preset ? list.find(c => c.preset === s.textAI.preset) : list.find(c => c.command && c.command === s.textAI.command); return x ? x.id : (s.textAI.command ? '' : ''); };
      sel.value = curId();
      sel.onchange = async () => {
        const prev = JSON.parse(JSON.stringify(s.textAI));
        const pick = list.find(x => x.id === sel.value);
        if (!pick) { s.textAI.mode = ['http'].includes(s.textAI.prevMode) ? s.textAI.prevMode : 'http'; delete s.textAI.prevMode; }
        else {
          if (s.textAI.mode !== 'cli') s.textAI.prevMode = s.textAI.mode;
          s.textAI.mode = 'cli';
          if (pick.preset) { s.textAI.preset = pick.preset; delete s.textAI.command; } else { s.textAI.command = pick.command; delete s.textAI.preset; }
        }
        try { await plugin.saveSettings(); }
        catch (e) { s.textAI = prev; sel.value = curId(); plugin.notify('没保存上，已改回原来的：' + errText(e), { kind: 'error' }); return; }
        delete cache.usage;
        plugin.app.workspace?.trigger?.('link-brain:models-changed');
      };
    };
    tab.loadAiTable().then(t => paint(t), e => paint(null, e));
  }
  // 电脑端：照 Claudian 设置页「Claude Code v2.1.302 · 自动检测」那一行：图标（右下角点 = 找到了）· 名字 + 版本 · 一句 · 右边开关
  function appRows(body, tab, { guide = false, onState = null } = {}) {
    const list = body.createDiv({ cls: 'lb-apps', attr: { 'data-section': 'mcp-apps' } });
    list.createDiv({ cls: 'setting-item-description lb-loading', text: '正在看这台电脑装了哪些 AI 应用…' });
    let alive = true;
    tab.stops.push(() => { alive = false; });
    const icons = (() => { try { return plugin.providerIcons ? plugin.providerIcons() : null; } catch (e) { console.error('[lb] 图标没加载上', e); return null; } })();
    const paint = j => {
      if (!alive) return;
      list.empty();
      const apps = j.apps || [];
      onState && onState(apps);
      if (!apps.length) list.createDiv({ cls: 'setting-item-description', text: '这台电脑上还没有能接入的 AI 应用（Claude Code、Codex、Claude 桌面版等）。装好后会出现在这里。' });
      for (const a of apps) {
        const r = new Setting(list).setName(a.name);
        r.settingEl.addClass('lb-app'); r.settingEl.setAttribute?.('data-app', a.id);
        const iconBox = r.settingEl.ownerDocument.createElement('div');
        iconBox.className = 'lb-app-icon';
        if (icons) icons.icon(iconBox, a.id, 22);
        const dot = r.settingEl.ownerDocument.createElement('span');
        dot.className = 'lb-app-dot';
        iconBox.appendChild(dot);
        r.settingEl.insertBefore(iconBox, r.settingEl.firstChild);
        if (a.version) r.nameEl.createSpan({ cls: 'lb-app-ver', text: 'v' + a.version });
        const how = a.via === 'claudian' ? '用 Claudian 里设的路径' : '自动检测';
        if (a.oneclick) {
          r.setDesc(a.connected ? '已接入' : how);
          r.addToggle(t => {
            let busy = false;
            t.setValue(!!a.connected).onChange(async on => {
              if (busy) return;
              busy = true; r.setDesc(on ? '正在接入…' : '正在断开…');
              let res = null;
              try { const x = await plugin.runPy(['-m', 'link_brain', 'connect', on ? 'add' : 'remove', a.id], { label: '接入 AI', timeoutMs: 120000, okCodes: [0, 1] }); res = x.json || {}; }
              catch (e) { res = { ok: false, message: e.message }; }
              if (res.ok) {
                a.connected = on;
                r.setDesc(on ? '已接入' : how);
                plugin.notify(res.message || (on ? '已接入' : '已断开'), { kind: 'ok', ms: 8000 });
                onState && onState(apps);
              } else {
                busy = true; try { t.setValue(!on); } catch {} finally { busy = false; }
                r.setDesc(res.message || '没做成');
                if (res.command) tab.link(r, '复制命令', () => plugin.copyText(res.command), '复制到终端自己运行');
              }
              delete cache.apps;
              busy = false;
            });
          });
        } else {
          r.setDesc(how + ' · 复制设置，粘进它的 MCP 设置');
          tab.link(r, '复制设置', () => plugin.copyText(j.json || ''), '复制 MCP 设置（JSON）');
        }
      }
      // 别的能接 MCP 的软件（Cursor 之类，上面认不出来的）：复制设置自己粘
      if (!guide) {
        const other = new Setting(list).setName('其他应用').setDesc('Cursor 等：复制设置，粘进它的 MCP 设置');
        other.settingEl.addClass('lb-app'); other.settingEl.setAttribute?.('data-app', 'other');
        tab.link(other, '复制设置', () => plugin.copyText(j.json || ''), '复制 MCP 设置（JSON）');
      }
      const miss = j.not_installed || [];
      if (miss.length && !guide) list.createDiv({ cls: 'lb-note setting-item-description', text: miss.join('、') + ' 没装，装好后会出现在这里。' });
    };
    loadApps().then(paint).catch(e => { if (alive) { list.empty(); plugin.failBox?.(list, '本机 AI 应用', e, () => { loadApps(true); tab.display(); }); } });
  }
  function groupConnect(g, tab) {
    sub(g, '本机命令行');
    cliRow(g, tab);
    sub(g, '让其他 AI 读收藏');
    const twin = g.createDiv({ cls: 'lb-twin lb-mcp-twin' });
    const pc = twin.createDiv({ cls: 'lb-twin-card', attr: { 'data-section': 'mcp-pc' } });
    const ph = pc.createDiv({ cls: 'lb-twin-head' });
    ph.createEl('strong', { text: '电脑端' });
    const pcState = ph.createSpan({ cls: 'lb-twin-note lb-mcp-state', text: '读取中…' });
    pc.createEl('p', { cls: 'setting-item-description', text: 'Claude Code / Codex / Claude 桌面版，一个开关接上。只读，随时能断开。' });
    appRows(pc, tab, { onState: apps => { const n = apps.filter(a => a.connected).length; pcState.setText(n ? `● 已接入 ${n} 个` : '○ 还没接'); } });
    const web = twin.createDiv({ cls: 'lb-twin-card', attr: { 'data-section': 'remote' } });
    const wh = web.createDiv({ cls: 'lb-twin-head' });
    wh.createEl('strong', { text: '网页端' });
    web.createEl('p', { cls: 'setting-item-description', text: 'ChatGPT、claude.ai 网页版和手机 App，要你自己的网址。只读。' });
    safe(tab, web, '网页端', () => tab.stops.push(plugin.remoteUI?.renderConnect(web, () => tab.display(), tab, { part: 'web', toggleHost: wh })));
    // 1028 作者：「MCP 显示实际 tg 功能（现在没有介绍）」——TG 机器人那边接的是同一套只读 MCP，再加两条只在 TG 有的路：
    //   发链接入库（机器人调 catch --origin tg，目录里记在「Fable」组）、批注 @ 它（note notify 交给通知命令，回复写回批注框）
    // 1101 作者：不是「在 Telegram 里」——这套 MCP 任何 AI 都能连，标题说连上的 AI 能做什么；发链接入库要你自己的机器人后台对接（MCP 里没有）
    sub(g, '连接 MCP 的 AI 能做什么', 'mcp-tg');
    const tg = g.createDiv({ cls: 'lb-tg', attr: { 'data-section': 'mcp-tg' } });
    for (const [name, desc, help, tag] of [
      ['发链接就入库', '脚本入库转录，几分钟后发 AI 机读版链接。',
        '要你的机器人后台对接（MCP 里没有这一项）：收到消息就在后台跑一次「link-brain catch "<消息原文>" --origin tg」，它找出里面的小红书链接收进库，只回一行 JSON（机读版在哪）。目录里记在「Fable」那一组；已经在库的直接告诉你在哪，不重抓。', '要后台对接'],
      ['问收藏', '走上面这套只读 MCP：搜、问、读全文 / 附件 / 图片、看最近收的。',
        '也能看分类索引、Wiki 和你的批注。只读，不会改也不会删。'],
      ['批注里 @ TA', '批注以「@名字」开头，定时送到 AI，回复写回同一个批注框。',
        '手机上写的也算。名字在 ③ 目录与批注 →「更多」→「留言对象」里填；还要配好通知命令（~/.link-brain/notify-cmd.txt）。'],
    ]) {
      const r = new Setting(tg).setName(name).setDesc(desc);
      r.settingEl.addClass('lb-tg-row');
      tab.help(r, help);
      if (tag) r.nameEl.createSpan({ cls: 'lb-tg-tag', text: tag });
    }
    const open = row(g, tab, '开放收藏库', '小红书和 B 站的收藏。AI 只能看，不能改也不能删：可见笔记，加上每篇的机读版、附件全文、批注。.obsidian、隐藏文件夹、插件设置、密钥、数据库和日志永远不开放。别的文件夹在「更多」里加。', { section: 'mcp-folders' });
    safe(tab, g, '开放收藏库', () => plugin.remoteUI?.xhsToggle(open, null));   // 1101：说明并进上面那个 ⓘ（以前两个 ⓘ 并排）
    more(g, tab, 'connect-more', b => {
      sub(b, '还开放了哪些文件夹', 'mcp-folders-more');
      safe(tab, b, '开放的文件夹', () => tab.stops.push(plugin.remoteUI?.renderConnect(b.createDiv(), () => tab.display(), tab, { part: 'folders', skipXhs: true })));
      sub(b, '端口、访问令牌、访问记录', 'tokens');
      safe(tab, b, '远程访问细项', () => plugin.remoteUI?.renderAdvanced(b.createDiv(), tab));
    }, { holds: ['mcp-folders-more', 'tokens'] });
  }

  // ———————————————————— ⑥ 修复 ————————————————————
  function groupRepair(g, tab) {
    const s = S();
    // 1027b 作者：「重新走首次设置」放前面——第一次用、或者哪里坏了，先找的就是它（「一键装好」1028 挪到页顶「懒人安装」）
    tab.link(row(g, tab, '重新走一遍首次设置', '再走一遍「登录 · 同步 · 识别与问答 · 接入其他 AI」；改的还是这一页上的同一份设置。', { section: 'first-run' }), '开始', async () => {
      s.onboarding = { ...(s.onboarding || {}), force: true, guideDone: false, step: 0 };
      await tab.save(); tab.display(); try { tab.containerEl.scrollTop = 0; } catch {}
    }, '回到首次设置');
    const st = row(g, tab, '当前状态', '哪里没做成、系统已经怎么处理的，按问题记录算；点「检查」再看一遍这台电脑缺什么。', { section: 'repair-state' });
    st.setDesc('读取中…');
    const out = g.createDiv({ cls: 'lb-check-box' });
    let alive = true;
    tab.stops.push(() => { alive = false; });
    const paint = async () => {
      let sum = null;
      try { ({ sum } = await plugin.readSyncFiles()); } catch {}
      if (!alive) return;
      const n = sum ? (+sum.needs_human || 0) : 0, auto = sum ? (+sum.auto || 0) + (+sum.gave_up || 0) : 0;
      // 1027b 作者：「不影响实际体验的，就别显示了」——只说要你动手的；自动处理 / 已放弃的在「问题记录」里
      void auto;
      st.setDesc(!sum ? '还没有问题记录' : n ? `⚠ ${n} 件要你处理` : '没有要你处理的');
      st.settingEl.toggleClass?.('is-warn', n > 0);
    };
    const check = tab.link(st, '检查', async () => {
      const done = plugin.busyButton ? plugin.busyButton(check, '正在检查…') : () => {};
      out.empty();
      try {
        await plugin.refreshProblemSummary?.();
        await paint();
        const data = await plugin.checkRuntime();
        if (!alive) return;
        for (const r of (data && data.checks) || []) {
          const ok = ['ready', 'configured'].includes(r.state);
          out.createDiv({ cls: 'lb-check-line' + (ok ? '' : ' is-warn'), text: (ok ? '✓ ' : '⚠ ') + r.label + '：' + r.message + (r.next_step && !ok ? ' — ' + r.next_step : '') });
        }
      } catch (e) { if (alive) plugin.failBox?.(out, '检查结果', e, () => check.click?.()); }
      finally { done(); }
    }, '只读：重新核一遍问题记录，看这台电脑缺什么，不改任何东西');
    const fix = tab.link(st, '全部修一遍', async () => {
      if (plugin.running) { plugin.notify(plugin.busyText(), { kind: 'warn' }); return; }
      const done = plugin.busyButton ? plugin.busyButton(fix, '正在修 / 最多 15 分钟') : () => {};
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'problems', 'repair'], { label: '当场修复', fallback: '修复没有返回结果', timeoutMs: 17 * 60000 });
        plugin.notify((r && r.json && r.json.message) || '修复没有返回结果', { ms: 12000 });
      } catch (e) { plugin.notify('修复没跑完：' + errText(e), { kind: 'error' }); }
      finally { done(); paint(); }
    }, '能当场修的都修一遍（风控 / 验证类不碰）');
    fix?.removeClass?.('lb-link');
    const probs = row(g, tab, '问题记录', '每一条：发生了什么、系统做了什么、你要不要动手；能一条一条修、复制诊断。', { section: 'problems' });
    tab.link(probs, '打开', () => plugin.openProblems?.(), '打开问题记录');
    paint();
    const vault = plugin.app.vault;
    if (vault && typeof vault.on === 'function') {
      const watched = plugin.lbPath('_archive/problems-summary.json');
      let timer = null;
      const ref = ['modify', 'create'].map(ev => vault.on(ev, f => { if (!alive || f?.path !== watched) return; clearTimeout(timer); timer = setTimeout(paint, 300); }));
      tab.stops.push(() => { clearTimeout(timer); for (const r of ref) { try { vault.offref(r); } catch {} } });
    }
    more(g, tab, 'repair-more', b => {
      const h = home();
      sub(b, '这台电脑', 'machine');
      if (h) tab.stops.push(h.renderStatus(b, tab, { machineOnly: true, noProblems: true }));   // 「一键装好」在页顶「懒人安装」
      sub(b, '后台程序', 'developer');
      tab.renderBackendRows(b);
      tab.link(row(b, tab, '目录显示不对', '重新整理一遍目录页（几秒到一分钟），不改任何收藏文件。', { section: 'rebuild' }), '重建目录',
        async () => { await plugin.run(['-m', 'link_brain', 'catalog'], '重建目录'); }, '重新整理一遍目录页');
      tab.link(row(b, tab, '诊断信息', '插件 / Python 版本、各步上次运行结果、最近 50 条问题；已经去掉密钥、账号和本机路径。', { section: 'diagnostic' }), '复制（已脱敏）',
        () => plugin.problemsUI?.().copyReport(), '复制脱敏后的诊断信息，发给帮你看的人');
      // 1101 作者「同步记录和进度藏好一点」：放到最底下的「开发者选项」
      sub(b, '开发者选项', 'devopts');
      // 1101 作者：同步记录 bug 多，平时不放在页面上；要看再从这里打开
      tab.toggleRow(b, '同步记录和进度', '', () => !!plugin.settings.devSyncLog, v => { plugin.settings.devSyncLog = !!v; }, {
        help: '打开后：目录页右上角出现同步记录（钟），「更新」和边栏「上次同步」能点开同步记录，状态栏显示同步 / 补评论进度。平时关着。',
        onChange: () => { plugin.taskChanged?.(); plugin.app.workspace?.trigger?.('link-brain:catalog-prefs'); } });
    }, { holds: ['machine', 'developer', 'rebuild', 'diagnostic', 'devopts'] });
  }

  // ———————————————————— 一页：左边锚点 + 六组 ————————————————————
  function renderPage(c, tab) {
    c.addClass?.('is-v7');
    const page = c.createDiv({ cls: 'lb-v7 lb-scope' });   // .lb-scope：样式集的字号 / 颜色变量在这一层按「Aa 样式」倍数重算
    const nav = page.createEl('nav', { cls: 'lb-anchors', attr: { 'aria-label': '设置分组' } });
    const main = page.createDiv({ cls: 'lb-v7-main' });
    const head = main.createDiv({ cls: 'lb-v7-head' });
    head.createDiv({ cls: 'lb-eyebrow lb-kicker', text: 'PREFERENCES / 按你的习惯' });
    const lead = head.createEl('p', { cls: 'lb-v7-lead', text: '常用的留在眼前，其余都在「更多」。改动自动保存。' });
    const saved = lead.createSpan({ cls: 'lb-saved', attr: { role: 'status' } });
    // 1028 作者：页顶加「懒人安装」——第一次用不想一项项看，点一下装好打开的功能、把同步 / 认字 / 概要 / 整理目录跑完（原来在 ⑥ 修复最前面，挪到这里，只留一处）
    const h0 = home();
    if (h0) {
      const lazy = head.createDiv({ cls: 'lb-lazy', attr: { 'data-section': 'lazy-install' } });
      lazy.createEl('strong', { cls: 'lb-lazy-title', text: '懒人安装' });
      safe(tab, lazy, '懒人安装', () => tab.stops.push(h0.renderRun(lazy, tab)));
    }
    const groups = {};
    for (const [id, n, title] of GROUPS) {
      const a = nav.createEl('a', { cls: 'lb-anchor', attr: { href: '#' + id, 'data-target': id } });
      a.createEl('b', { text: n }); a.createSpan({ text: title });
      a.onclick = ev => { ev?.preventDefault?.(); const el = groups[id].section; try { el.scrollIntoView({ block: 'start', behavior: 'smooth' }); } catch { try { el.scrollIntoView(); } catch {} } mark(id); };
      const sec = main.createEl('section', { cls: 'lb-group', attr: { 'data-section': id, id } });
      const h = sec.createDiv({ cls: 'lb-group-head' });
      h.createSpan({ cls: 'lb-num', text: n }); h.createEl('h2', { text: title });
      groups[id] = sec.createDiv({ cls: 'lb-group-body' });
      groups[id].section = sec;
    }
    nav.createDiv({ cls: 'lb-anchor-foot', text: '所有页面共用一份设置。' });
    const draw = { 'g-account': groupAccount, 'g-sync': groupSync, 'g-catalog': groupCatalog, 'g-advanced': groupAdvanced, 'g-connect': groupConnect, 'g-repair': groupRepair };
    for (const [id] of GROUPS) safe(tab, groups[id], GROUPS.find(x => x[0] === id)[2], () => draw[id](groups[id], tab));
    // 锚点跟着滚动高亮当前那一组（滚的是 Obsidian 设置窗口的内容区）
    const mark = id => { for (const a of nav.querySelectorAll('.lb-anchor')) a.toggleClass?.('is-current', a.getAttribute('data-target') === id); };
    mark('g-account');
    const scroller = tab.containerEl;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : f => setTimeout(f, 16))(() => {
        frame = 0;
        const top = scroller.getBoundingClientRect ? scroller.getBoundingClientRect().top : 0;
        let cur = GROUPS[0][0];
        for (const [id] of GROUPS) { const r = groups[id].section.getBoundingClientRect?.(); if (r && r.top - top <= 120) cur = id; }
        mark(cur);
        fitStick();
      });
    };
    scroller?.addEventListener?.('scroll', onScroll, { passive: true });
    tab.stops.push(() => scroller?.removeEventListener?.('scroll', onScroll));
    // 1028 作者：窄屏吸顶的锚点条要「整一块固定」，不是一条细条、上面还漏出底下的字。
    //   条吸住的位置离滚动区可见的顶边还差一段（Obsidian 内容区的内边距 / 外层再套的滚动区，各版本不一样），这段里就露字。
    //   不猜是哪一种：吸住时量条离可见顶边差多少，交给 CSS（--lb-stick-pad）——条往上伸这么高、吸到最顶上，伸出去的部分是底色
    let stickPad = 0;
    const viewTop = () => {
      // 真正在滚的那一层（可能是 containerEl，也可能是它外面一层）
      for (let el = page.parentElement; el; el = el.parentElement) {
        const cs = el.ownerDocument?.defaultView?.getComputedStyle?.(el);
        if (cs && /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight) return el.getBoundingClientRect().top;
      }
      return scroller?.getBoundingClientRect ? scroller.getBoundingClientRect().top : null;
    };
    const fitStick = () => {
      try {
        const cs = nav.ownerDocument?.defaultView?.getComputedStyle?.(nav);
        if (!cs || cs.flexDirection !== 'row' || !nav.getBoundingClientRect) return;   // 宽屏锚点在左栏，不用盖
        const top = viewTop();
        if (top == null) return;
        const gap = Math.round(nav.getBoundingClientRect().top - top);
        // 没吸住时条还在原位（离顶边远），这时只按「页面离顶边多高」先伸一下；吸住了（离顶边很近）再精确补差
        const pageGap = Math.round(page.getBoundingClientRect().top - top + stickPad);
        const want = gap > 0 && gap < 160 ? stickPad + gap : !stickPad && pageGap > 0 && pageGap < 160 ? pageGap : stickPad;
        if (want !== stickPad) { stickPad = want; page.style?.setProperty?.('--lb-stick-pad', stickPad + 'px'); }
      } catch {}
    };
    (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : f => setTimeout(f, 0))(fitStick);
    const win = scroller?.ownerDocument?.defaultView;
    const refit = () => { stickPad = 0; page.style?.setProperty?.('--lb-stick-pad', '0px'); fitStick(); };
    win?.addEventListener?.('resize', refit);
    tab.stops.push(() => win?.removeEventListener?.('resize', refit));
    // 「已保存」只在真写进 data.json 之后出现（saveSettings 成功后广播 link-brain:settings）
    const ws = plugin.app.workspace;
    if (ws && typeof ws.on === 'function') {
      const ref = ws.on('link-brain:settings', () => { const d = new Date(); saved.setText(` · 已保存 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`); });
      tab.stops.push(() => { try { ws.offref(ref); } catch {} });
    }
    return page;
  }

  // ———————————————————— 首次设置 ————————————————————
  // 1101 作者「开了 B 站同步，首次设置也要改」：第 1 步登录两张账号卡（和设置页①同一套），第 2 步同步用②的小红书 / B 站切换
  const STEPS = [['login', '登录账号'], ['sync', '同步'], ['ai', '识别与问答'], ['connect', '接入其他 AI']];
  async function needsGuide() {
    const ob = S().onboarding || {};
    if (ob.force) return true;
    if (ob.guideDone) return false;
    try { return !(await plugin.app.vault.adapter.exists(plugin.lbPath('_archive/catalog-data.json'))); } catch { return false; }
  }
  function renderGuide(c, tab) {
    const s = S();
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
      // 装好打开的功能 + 同步 + 补处理一口气跑完（进度在设置页⑥和底部状态栏）
      if (run && h) h.runAll({ quiet: false }).catch(e => console.error('[lb] 首次跑没跑完', e));
      // B 站只做手动同步（1031 作者）：视频大，不替用户开下；登上了就提一句去哪点
      if (run && biliStatus && biliStatus.state === 'logged_in') plugin.notify('B 站收藏不自动下（视频占地方）：在「收藏与同步 → B 站」先「预估」，再「立即同步」。', { ms: 12000,
        actions: [{ label: '去 B 站同步', run: () => focusSection(tab, 'sync-bili') }] });
    };
    // 「同步」一步里的时间编辑器和设置页是同一个（syncTimeEditor）：在这一步动过时间、还没生效就离开 → 替用户按这个时间打开，存不上就留在这一步说原因
    let syncEd = null, edits0 = null;
    const leaveSync = async () => {
      const ed = syncEd;
      if (!ed) return true;
      const touched = ed.isDirty() || (edits0 != null && JSON.stringify(ed.rows) !== edits0);
      if (touched) {
        const res = await ed.saveNow({ force: ed.enabled() !== true });
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
        out.onclick = async () => { if (await leaveSync()) await finish(false); };   // 以后再说：只记走完，不替用户开跑
      };
      const id = step ? STEPS[step - 1][0] : 'welcome';
      if (id === 'welcome') {
        title('开始使用 LWA');
        body.createEl('p', { cls: 'lb-guide-hint', text: '把小红书、B 站的收藏存进这个库，图片、视频里的字都能搜，AI 能帮你翻。' });
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
        title('登录账号', quick() ? '扫完就好' : '第 1 步');
        body.createEl('p', { cls: 'lb-guide-hint', text: '用哪个就登哪个，用手机 App 扫码。小红书登好马上开始收最近的收藏；B 站扫一次以后自动复用。登录状态只存在这台电脑上。' });
        // 两张账号卡、平台切换的样式都挂在 .lb-v7 下（设置页那一套）；首次设置外层是 .lb-v6，这里套一层同样式的块
        const v7 = body.createDiv({ cls: 'lb-v7 lb-guide-v7' });
        safe(tab, v7, '账号登录', () => groupAccount(v7, tab));
      } else if (id === 'sync') {
        title('同步', '不改就用推荐值');
        const { paneX, paneB } = platPanes(body.createDiv({ cls: 'lb-v7 lb-guide-v7' }));
        syncEd = syncRows(paneX, tab);
        edits0 = null;
        if (syncEd && syncEd.ready) syncEd.ready.then(() => { if (syncEd) edits0 = JSON.stringify(syncEd.rows); });
        const bili = paneB.createDiv({ cls: 'lb-bili lb-bili-sync', attr: { 'data-section': 'sync-bili' } });
        safe(tab, bili, 'B 站同步', () => biliSync(bili, tab));
      } else if (id === 'ai') {
        title('识别与问答', '本机的免费，其余要 key');
        featureRows(body, tab, { guide: true });
        keyBox(body, tab, { onDone: () => paint() });
      } else {
        title('接入其他 AI（MCP）', '只读 · 可跳过');
        body.createEl('p', { cls: 'lb-guide-hint', text: '通过 MCP 把收藏库接给这些应用：在里面就能搜索、阅读你的收藏。只读，不会修改或删除，随时可以断开。' });
        appRows(body, tab, { guide: true });
        body.createEl('p', { cls: 'setting-item-description', text: 'ChatGPT、claude.ai 网页版要你自己的网址：走完后在设置「CLI 与外接 MCP → 网页端」里打开。' });
      }
      nav();
    };
    paint();
  }

  return { renderPage, renderGuide, needsGuide, syncTimeEditor, syncRows, featureRows, focusSection, addKey, replaceKey, pasteKey, keyTrouble, slotsFor,
    bili: { biliCard, biliSync, biliSyncArgs, biliLoginLines, biliPicker, biliSkip, estimateText, lastText, BILI_DEFAULTS, BILI_WORKERS, BILI_RUN_LABEL },
    STEPS, PROV, SYNC_TIME, GROUPS, _values: { asrValue, visionValue, askValue, summaryValue, embedValue }, _parts: { apiConfig, recogRows, askRows } };
};

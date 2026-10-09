// home-ui.js — 1009 她的裁决（docs/SETUP-CONTRACT.md）：设置页顶部就是这一块，不再有分步向导、不再单独有「开始」页。
//   状态：小红书账号 · 收藏同步（立即同步 / 定时）· 评论补齐进度 · 问题
//   功能：每项一个开关（磁盘 / 内存 / 状态）；AI 两项打开就在原地填接口 / Key / 模型；一个「一键装好 / 跑完」按钮
//         （`setup run`：装好缺的 → 确认登录 → 同步 → 识图 / 概要 → 目录 → 索引 → 评论补齐转后台），进度就在按钮下面。
//   零配置：新装（库里还没有收藏）第一次打开 Obsidian 就按轻量版自动跑一次（firstRun）。
// main.js 只接几行：homeUI() 按需 require；设置页 display() 调 renderStatus / renderFeatures；onboarding-ui.startup 调 firstRun。
// 本模块不起进程：一律经 plugin.runPy / spawnPy（CONVENTIONS §1.4、§6.1）；进度只显示后端发来的（§1.6）。
'use strict';

const LIGHT = ['core', 'reader', 'dataview', 'ocr'];
const STATUS_TEXT = { ready: '已就绪', missing: '没装', partial: '不完整', failed: '没装上', unknown: '没查出来', needs_key: '要填 Key' };
const STAGE_MARK = { running: '⟳', ok: '✓', skipped: '–', failed: '✗' };
const AI_CAP = { ai_text: 'textAI', ai_vision: 'visionAI' };

const num = v => (v === null || v === undefined || v === '' || typeof v === 'boolean' || !Number.isFinite(Number(v)) ? null : Number(v));

// —— 选择规则（纯函数，单测直接测；搬自第 7 批 setup-ui.js）——
function compMap(comps) { return new Map((comps || []).map(c => [c.id, c])); }
function withDeps(ids, comps) {
  const m = compMap(comps), out = new Set();
  const add = id => { if (out.has(id) || !m.has(id)) return; out.add(id); for (const d of m.get(id).depends || []) add(d); };
  for (const id of ids || []) add(id);
  for (const c of comps || []) if (c.required) add(c.id);
  return (comps || []).map(c => c.id).filter(id => out.has(id));
}
function withoutDependents(ids, id, comps) {
  const m = compMap(comps);
  if (m.get(id)?.required) return withDeps(ids, comps);
  const drop = new Set([id]);
  let grew = true;
  while (grew) { grew = false; for (const c of comps || []) if (!drop.has(c.id) && !c.required && (c.depends || []).some(d => drop.has(d))) { drop.add(c.id); grew = true; } }
  return withDeps((ids || []).filter(x => !drop.has(x)), comps);
}
function toggleSelection(ids, id, on, comps) { return on ? withDeps([...(ids || []), id], comps) : withoutDependents(ids, id, comps); }
// 1009 她：没选过 = 轻量版（装上就能用，不要任何 key）
function initialSelection(saved, plan) {
  const comps = plan?.components || [];
  if (Array.isArray(saved)) return withDeps(saved, comps);
  const light = plan?.presets?.light;
  return withDeps(Array.isArray(light) ? light : LIGHT, comps);
}
function totals(ids, comps) {
  const sel = new Set(ids || []);
  let disk = 0, ram = 0, unknown = 0;
  for (const c of comps || []) if (sel.has(c.id)) {
    const d = num(c.disk_mb), r = num(c.ram_mb);
    if (d == null && r == null) unknown++;
    disk += d || 0; ram += r || 0;
  }
  return { disk, ram, unknown };
}
function fmtMB(v) {
  const n = num(v);
  if (n == null) return '?';
  return n >= 1024 ? (Math.round(n / 102.4) / 10) + ' GB' : Math.round(n) + ' MB';
}
function yuan(v) { const n = num(v); return n == null ? '—' : '¥' + (n < 0.1 && n > 0 ? n.toFixed(3) : n.toFixed(2)); }
// 进度事件（setup run 的 stage 事件 / setup install 的组件事件）→ 一行字 + 百分比
function progressView(ev) {
  if (!ev) return null;
  const done = num(ev.done), total = num(ev.total);
  const pct = done != null && total ? Math.max(0, Math.min(100, Math.round(done / total * 100))) : null;
  const mb = x => (x / 1048576).toFixed(1);
  const size = done != null && total ? (total >= 1048576 ? `${mb(done)} / ${mb(total)} MB` : `${done} / ${total}`) : '';
  return { pct, text: [ev.phase || ev.label, pct != null ? pct + '%' : '', size, ev.text].filter(Boolean).join(' · ') };
}
// `setup run` 的事件流 → 各步状态（{stage: {state, text, label, index}}）+ 正在装的组件进度
function applyRunEvent(run, ev) {
  if (!ev || typeof ev !== 'object') return run;
  if (ev.type === 'result') { run.result = ev; run.state = 'done'; return run; }
  if (ev.type !== 'progress') return run;
  if (ev.component && ev.stage === 'install') { run.install = ev; return run; }
  if (!ev.stage) return run;
  const cur = run.stages[ev.stage] || {};
  run.stages[ev.stage] = { ...cur, label: ev.label || cur.label, index: ev.index || cur.index, count: ev.count || cur.count,
    state: ev.state || cur.state || 'running', text: ev.text != null && ev.text !== '' ? ev.text : (ev.state !== 'running' ? '' : cur.text || '') };
  if (ev.state === 'running') run.current = ev.stage;
  return run;
}
// 评论补齐那一行（状态文件 + fill-status 的统计）
function fillLine(st, info, now = Date.now()) {
  const live = st && ['running', 'waiting', 'paused'].includes(st.state) && now - Date.parse(st.updated_at || '') < 10 * 60000;
  if (live) return st.message || '后台在补评论';
  if (info && info.ok) return info.pending ? `${info.pending} 篇的评论还没补齐（共缺 ${info.missing} 条回复）` + (info.stuck ? ` · ${info.stuck} 篇连着补不上（见问题面板）` : '')
    : '评论都补齐了' + (info.stuck ? `（${info.stuck} 篇连着补不上，见问题面板）` : '');
  if (st && st.message) return st.message;
  return '';
}

module.exports = function homeUI(obsidian, plugin) {
  const { Setting, Notice } = obsidian;
  const S = () => plugin.homeState || (plugin.homeState = { plan: null, planError: null, planLoading: null, estimate: null, run: null,
    fillInfo: null, child: null });
  const setup = () => {
    const s = plugin.settings;
    if (!s.setup || typeof s.setup !== 'object') s.setup = {};
    return s.setup;
  };
  const save = () => Promise.resolve(plugin.saveSettings()).catch(e => new Notice('没保存上：' + e.message, 8000));
  const comps = () => S().plan?.components || [];
  const selected = () => initialSelection(setup().selected, S().plan);
  const errText = e => (e && e.message) || String(e || '');

  async function loadPlan(force = false) {
    const st = S();
    if (st.plan && !force) return st.plan;
    if (st.planLoading) return st.planLoading;
    st.planLoading = (async () => {
      try {
        const { json } = await plugin.runPy(['-m', 'link_brain', 'setup', 'plan'], { label: '读取功能清单', fallback: '读不到功能清单', timeoutMs: 60000, okCodes: [0, 1, 2] });
        if (!json || !Array.isArray(json.components)) throw new Error((json && json.message) || '后台没返回功能清单');
        st.plan = json; st.planError = null;
      } catch (e) { st.planError = e; }
      finally { st.planLoading = null; }
      return st.plan;
    })();
    return st.planLoading;
  }
  async function loadEstimate() {
    const st = S();
    if (st.estimate && !st.estimate.error) return st.estimate;
    try {
      const { json } = await plugin.runPy(['-m', 'link_brain', 'setup', 'estimate', '--posts', '100'], { label: '估算价格', timeoutMs: 120000, okCodes: [0, 1, 2] });
      st.estimate = json && json.ok !== false ? { data: json } : { error: (json && json.message) || '估不出价格' };
    } catch (e) { st.estimate = { error: errText(e) }; }
    return st.estimate;
  }

  // —— 一键装好 / 跑完 ——（exclusive：占「正在跑」的互斥位，底部状态栏可停）
  let painters = new Set();
  const repaint = () => { for (const p of painters) { try { p(); } catch (e) { console.error('[lb] 设置页没重画上', e); } } };
  async function runAll({ quiet = false } = {}) {
    const st = S();
    if (plugin.running) { plugin.notify(plugin.busyText(), { kind: 'warn' }); return null; }
    if (!Array.isArray(setup().selected)) { setup().selected = selected(); await save(); }
    st.run = { state: 'running', stages: {}, current: null, install: null, result: null, startedAt: Date.now() };
    repaint();
    let lineFrame = null;
    const r = await plugin.spawnPy(['-m', 'link_brain', 'setup', 'run'], {
      exclusive: true, label: '装好并跑完', timeoutMs: 6 * 3600000,
      onChild: ch => { st.child = ch; },
      onLine: line => {
        let ev; try { ev = JSON.parse(line); } catch { return; }
        applyRunEvent(st.run, ev);
        const sg = ev.stage && st.run.stages[ev.stage];
        if (sg && sg.state === 'running') { plugin.runningProgress = sg.label || ''; plugin.taskChanged?.(); }
        if (lineFrame == null) lineFrame = setTimeout(() => { lineFrame = null; repaint(); }, 120);
      },
    });
    st.child = null;
    if (!st.run.result) st.run.result = r.json && r.json.type === 'result' ? r.json
      : { ok: false, message: r.timedOut ? '超过 6 小时没跑完，已停止；做了的都存好了' : (r.code === 6 && r.busy ? plugin.busyText() : (String(r.err || '').trim().split('\n').pop() || '没跑完')) };
    st.run.state = 'done';
    repaint();
    const res = st.run.result;
    if (!quiet) {
      const human = res.code === 'NEEDS_HUMAN';
      plugin.notify(res.message || (res.ok ? '都跑完了' : '没跑完'), { kind: res.ok ? 'ok' : human ? 'warn' : 'error', ms: human ? 0 : undefined,
        actions: human ? [{ label: '去扫码 / 验证', run: () => plugin.openSetupPage?.('status') }] : null });
    }
    loadPlan(true).then(repaint);
    return res;
  }
  async function stopRun() { await plugin.stopRunning?.(); }

  // —— 首次（零配置）：新装、库里还没有收藏 → 按轻量版自动跑一次 ——
  async function firstRun() {
    const s = setup();
    if (s.firstRunAt) return 'done-before';
    s.firstRunAt = new Date().toISOString();
    let fresh = true;
    try { fresh = !(await plugin.app.vault.adapter.exists(plugin.lbPath('_archive/catalog-data.json'))); } catch { fresh = true; }
    if (!fresh) { await save(); return 'existing-library'; }   // 老库（作者本机）：只记一笔，选择不动
    if (!Array.isArray(s.selected)) s.selected = [...LIGHT];
    await save();
    plugin.notify('Link Brain 装好了：正在按轻量版（不要任何 key）自动装好并同步，进度在底部状态栏和设置页顶部。', { ms: 12000,
      actions: [{ label: '打开设置', run: () => plugin.openSetupPage?.() }] });
    runAll().catch(e => console.error('[lb] 首次自动跑没跑完', e));
    return 'started';
  }

  // —— 画：状态 ——
  function renderStatus(c, tab) {
    const box = c.createDiv({ cls: 'lb-home-status' });
    box.createEl('h3', { text: '状态' });
    try { plugin.renderAccounts(box); } catch (e) { box.createEl('p', { cls: 'lb-setup-error', text: '账号那一行没画上：' + errText(e) }); }
    const stops = [];
    try { stops.push(plugin.renderSyncRow(box)); } catch (e) { console.error('[lb] 同步那一行没画上', e); }
    const fill = new Setting(box).setName('评论补齐').setDesc('读取中…');
    fill.settingEl.addClass('lb-fill-row');
    let fillBtn = null;
    fill.addButton(b => { fillBtn = b; b.setButtonText('现在补').onClick(async () => {
      b.setDisabled(true);
      const r = await plugin.ensureCommentFill('settings');
      b.setDisabled(false);
      plugin.notify((r && r.message) || '后台补评论已经在跑', { kind: 'ok' });
      paintFill();
    }); });
    const probs = new Setting(box).setName('问题').setDesc('');
    probs.settingEl.addClass('lb-probs-row');
    probs.addButton(b => b.setButtonText('打开问题面板').onClick(() => plugin.openProblems()));
    let alive = true;
    const paintFill = async () => {
      const { sum, fill: st } = await plugin.readSyncFiles();
      if (!alive) return;
      const line = fillLine(st, S().fillInfo);
      fill.setDesc(line || '读取中…');
      const live = st && ['running', 'waiting', 'paused'].includes(st.state) && Date.now() - Date.parse(st.updated_at || '') < 10 * 60000;
      if (fillBtn) fillBtn.buttonEl.toggleClass?.('is-hidden', !!live || !(S().fillInfo?.pending > 0));
      const n = sum ? (num(sum.needs_human) || 0) : 0, auto = sum ? (num(sum.auto) || 0) + (num(sum.gave_up) || 0) : 0;
      probs.setDesc(!sum ? '还没有问题记录' : n ? `⚠ ${n} 件要你处理` + (auto ? ` · 另有 ${auto} 条在自动处理 / 已放弃` : '')
        : auto ? `${auto} 条在自动处理 / 已放弃，不用管` : '没有问题');
    };
    paintFill();
    plugin.runPy(['-m', 'link_brain', 'comments', '--fill-status'], { label: '评论补齐进度', timeoutMs: 120000 })
      .then(r => { S().fillInfo = r.json; if (alive) paintFill(); }).catch(() => {});
    const vault = plugin.app.vault;
    let refs = [], timer = null;
    if (vault && typeof vault.on === 'function') {
      const watched = new Set([plugin.lbPath('_archive/comments-fill-status.json'), plugin.lbPath('_archive/problems-summary.json')]);
      const onFile = f => { if (!alive || !watched.has(f?.path)) return; clearTimeout(timer); timer = setTimeout(() => { if (alive) paintFill(); }, 300); };
      refs = ['modify', 'create'].map(ev => vault.on(ev, onFile));
    }
    return () => {
      alive = false; clearTimeout(timer);
      for (const r of refs) { try { vault.offref(r); } catch {} }
      for (const s of stops) { try { s && s(); } catch {} }
    };
  }

  // —— 画：功能（开关 + AI 原地填 + 一键装好 / 跑完）——
  function renderFeatures(c, tab) {
    const box = c.createDiv({ cls: 'lb-home-features' });
    const head = box.createDiv({ cls: 'lb-home-head' });
    head.createEl('h3', { text: '功能' });
    const presets = head.createDiv({ cls: 'lb-home-presets' });
    const list = box.createDiv({ cls: 'lb-feat-list' });
    const aiBox = box.createDiv({ cls: 'lb-feat-ai' });      // AI 两项打开了就在原地填（紧跟在清单下面）
    const foot = box.createDiv({ cls: 'lb-feat-total' });
    const runBox = box.createDiv({ cls: 'lb-run' });
    let alive = true;

    const paintList = () => {
      list.empty(); presets.empty(); foot.empty();
      const st = S();
      if (!st.plan) {
        if (st.planError) {
          const err = list.createDiv({ cls: 'lb-setup-error' });
          err.createEl('p', { text: '读不到功能清单：' + errText(st.planError) });
          const acts = err.createDiv({ cls: 'lb-setup-actions' });
          acts.createEl('button', { text: '重试' }).onclick = () => { st.planError = null; paintList(); loadPlan(true).then(() => alive && paintAll()); };
          if (st.planError.backendMissing) acts.createEl('button', { text: '复制安装命令' }).onclick = () => plugin.copyText('uv tool install link-brain');
        } else list.createEl('p', { cls: 'setting-item-description lb-loading', text: '读取功能清单' });
        return;
      }
      const ids = selected(), cs = comps(), sel = new Set(ids);
      // 两个快捷：轻量版（不要任何 key）/ 全部打开
      const light = presets.createEl('button', { cls: 'lb-preset', text: '轻量版（不要 key）' });
      light.onclick = async () => {
        const keyed = ids.some(id => AI_CAP[id]);
        if (keyed && !await plugin.confirm({ title: '换成轻量版？', body: '会停掉问答、概要和识图（Key 不删，随时打开）。', ok: '换成轻量版', danger: true })) return;
        setup().selected = withDeps(st.plan.presets?.light || LIGHT, cs); await save(); paintAll();
      };
      for (const comp of cs) {
        if (comp.later) continue;   // 远程阅读在「连接 AI」里
        const row = new Setting(list).setName(comp.name || comp.id);
        row.settingEl.addClass('lb-feat'); row.settingEl.setAttribute?.('data-id', comp.id);
        const status = (st.run && st.run.installed && st.run.installed[comp.id]) || comp.status;
        const bits = [`磁盘 ${fmtMB(comp.disk_mb)} · 内存 ${fmtMB(comp.ram_mb)}`];
        if (sel.has(comp.id) && status && !comp.needs_key) bits.push(status === 'ready' ? '✓ 已就绪' : '⚠ ' + (STATUS_TEXT[status] || status) + '（点下面「一键装好」）');
        if (comp.needs_key && sel.has(comp.id)) bits.push(aiReady(comp.id) ? '✓ 已填好' : '⚠ 要填接口 / Key（就在下面）');
        row.setDesc(bits.join(' · '));
        if (comp.desc) row.descEl.setAttribute?.('title', comp.desc);
        if (comp.required) {
          row.settingEl.addClass('is-required');
          if (comp.id === 'dataview' && status !== 'ready') row.addButton(b => b.setButtonText('打开第三方插件').onClick(() => plugin.openPluginSettings('community-plugins')));
          continue;
        }
        row.addToggle(t => t.setValue(sel.has(comp.id)).onChange(async v => {
          setup().selected = toggleSelection(selected(), comp.id, v, cs);
          await applyRuntime(new Set(setup().selected));
          await save(); paintList(); paintAI();
        }));
      }
      const t = totals(ids, cs);
      foot.setText(`合计：磁盘 ${fmtMB(t.disk)} · 内存 ${fmtMB(t.ram)}` + (t.unknown ? `（另有 ${t.unknown} 项没给数）` : ''));
      if (st.plan.totals_basis) foot.setAttribute?.('title', st.plan.totals_basis);
    };
    // 开关是唯一入口：顺手把实际起作用的那几个设置对上（OCR 方式、本机语音识别、CapsLock 客户端、AI 方式），别处不再各有一个开关
    const applyRuntime = async on => {
      const s = plugin.settings;
      if (s.ocr) s.ocr.mode = on.has('ocr') ? (s.ocr.mode === 'off' ? 'local' : s.ocr.mode || 'local') : 'off';
      if (s.asrAI) { if (on.has('asr') && s.asrAI.mode === 'off') s.asrAI.mode = 'capswriter'; if (!on.has('asr') && s.asrAI.mode === 'capswriter') s.asrAI.mode = 'off'; }
      if (s.textAI && on.has('ai_text') && s.textAI.mode === 'off') s.textAI.mode = 'http';
      if (s.visionAI && on.has('ai_vision') && s.visionAI.mode === 'off') s.visionAI.mode = 'http';
      const caps = on.has('capslock');
      if (s.voice && !!s.voice.capsLock !== caps) {
        let ok = !caps;
        try { ok = await plugin.setCapsVoice(caps); } catch { ok = false; }
        s.voice.capsLock = caps && !!ok;
        if (caps && !ok) plugin.notify('CapsLock 语音输入要先装好 CapsWriter：点下面「一键装好 / 跑完」', { kind: 'warn' });
      }
    };
    const aiReady = id => {
      const cfg = plugin.settings[AI_CAP[id]] || {};
      return cfg.mode === 'cli' ? !!cfg.command : cfg.mode === 'http' ? !!(cfg.endpoint && cfg.model && (cfg.apiKey || cfg.keyFile || cfg.apiKeyEnv)) : false;
    };

    // AI 两项：打开了就在原地填（不另开分页）
    const paintAI = () => {
      aiBox.empty();
      const ids = new Set(selected());
      if (!S().plan) return;
      if (!ids.has('ai_text') && !ids.has('ai_vision')) {
        aiBox.createEl('p', { cls: 'setting-item-description lb-free-line', text: '不填 key 也能用：归档、浏览、关键词搜索、本地 OCR、本地语音。打开上面「AI 问答」或「识图」就在这里填接口。' });
        return;
      }
      const est = S().estimate;
      const estLine = aiBox.createDiv({ cls: 'setting-item-description lb-estimate-line' });
      if (!est) { estLine.setText('估算价格…'); loadEstimate().then(() => { if (alive) paintAI(); }); }
      else if (est.error) estLine.setText('估不出价格：' + est.error);
      else {
        const items = (est.data.items || []).filter(it => (it.id === 'summary' && ids.has('ai_text')) || (it.id === 'vision' && ids.has('ai_vision')));
        estLine.setText('参考价（每 100 篇）：' + items.map(it => `${it.name} ${yuan(it.yuan)}（${it.provider || ''}${it.api_model || it.model ? ' ' + (it.api_model || it.model) : ''}）`).join(' · ')
          + (est.data.prices?.as_of ? `，价格核对于 ${est.data.prices.as_of}` : ''));
        for (const it of items) if (it.endpoint && it.openai_compatible !== false) {
          const cap = it.id === 'vision' ? 'visionAI' : 'textAI';
          const cur = plugin.settings[cap] || {};
          if (cur.endpoint === it.endpoint && cur.model === (it.api_model || it.model)) continue;
          estLine.createEl('button', { cls: 'lb-estimate-use', text: `用${it.provider || '建议'}的${it.id === 'vision' ? '识图' : '问答'}接口` }).onclick = async () => {
            const previous = JSON.parse(JSON.stringify(cur));
            const next = { ...previous, mode: 'http', endpoint: it.endpoint, model: it.api_model || it.model };
            const host = v => { try { return new URL(v).hostname; } catch { return ''; } };
            if (host(previous.endpoint) !== host(next.endpoint)) for (const k of ['apiKey', 'keyFile', 'keyField', 'apiKeyEnv']) delete next[k];
            plugin.settings[cap] = next; await save();
            plugin.notify(`已换成 ${it.provider} 的地址和模型：再填这家的 Key`, { ms: 8000, actions: [{ label: '撤销', run: async () => { plugin.settings[cap] = previous; await save(); paintAI(); } }] });
            paintAI();
          };
        }
      }
      if (ids.has('ai_text')) { const t = aiBox.createDiv({ cls: 'lb-feat-cap', attr: { 'data-cap': 'textAI' } }); t.createEl('h4', { text: 'AI 问答 · 概要 · 打标' }); tab.sectionTextAI(t, { heading: false }); }
      if (ids.has('ai_vision')) { const v = aiBox.createDiv({ cls: 'lb-feat-cap', attr: { 'data-cap': 'visionAI' } }); v.createEl('h4', { text: '识图' }); tab.sectionVisionAI(v); }
    };

    // 一键装好 / 跑完 + 进度
    const paintRun = () => {
      runBox.empty();
      const st = S(), run = st.run;
      const acts = runBox.createDiv({ cls: 'lb-run-actions' });
      const busy = !!(run && run.state === 'running');
      if (busy) acts.createEl('button', { cls: 'lb-run-stop', text: '停止' }).onclick = () => stopRun();
      else {
        const go = acts.createEl('button', { cls: 'lb-run-go mod-cta', text: '一键装好 / 跑完' });
        go.disabled = !st.plan || !!plugin.running;
        go.onclick = () => runAll();
        acts.createEl('span', { cls: 'setting-item-description', text: plugin.running && !busy ? plugin.busyText() : '装好打开的功能，再同步收藏、OCR / 识图、概要、目录、索引一口气跑完（没开 AI 就跑轻量版）。' });
      }
      if (!run) return;
      const steps = runBox.createDiv({ cls: 'lb-run-steps' });
      const order = Object.values(run.stages).sort((a, b) => (a.index || 0) - (b.index || 0));
      for (const sg of order) {
        const row = steps.createDiv({ cls: 'lb-run-step is-' + (sg.state || 'running') });
        row.createSpan({ cls: 'lb-run-mark', text: STAGE_MARK[sg.state] || '○' });
        row.createSpan({ cls: 'lb-run-label', text: sg.label || '' });
        if (sg.text) row.createSpan({ cls: 'lb-run-text', text: sg.text });
      }
      if (busy && run.install) {
        const pv = progressView(run.install);
        const bar = runBox.createDiv({ cls: 'lb-bar' + (pv && pv.pct != null ? '' : ' is-indeterminate') });
        const fill = bar.createDiv({ cls: 'lb-bar-fill' });
        if (pv && pv.pct != null) fill.style.width = pv.pct + '%';
        runBox.createDiv({ cls: 'setting-item-description', text: '正在装 ' + (run.install.component || '') + '：' + (pv ? pv.text : '') });
      }
      if (run.result) runBox.createDiv({ cls: 'lb-run-result' + (run.result.ok ? ' is-done' : ' is-failed'), text: run.result.message || '' });
    };

    const paintAll = () => { if (!alive) return; paintList(); paintAI(); paintRun(); };
    painters.add(paintAll);
    paintAll();
    if (!S().plan) loadPlan().then(() => { if (alive) paintAll(); });
    return () => { alive = false; painters.delete(paintAll); };
  }

  return { renderStatus, renderFeatures, runAll, stopRun, firstRun, loadPlan, state: S,
    _internals: { withDeps, withoutDependents, toggleSelection, initialSelection, totals, fmtMB, yuan, progressView, applyRunEvent, fillLine } };
};
module.exports._internals = { withDeps, withoutDependents, toggleSelection, initialSelection, totals, fmtMB, yuan, progressView, applyRunEvent, fillLine, LIGHT };

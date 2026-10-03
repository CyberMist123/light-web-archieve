// setup-ui.js — 第 7 批：设置页「开始」分页（参照 MAA 初始设置：左边功能勾选清单，右边竖排步骤 + 上一步 / 下一步，一页走完）。
// main.js 只接几行：setupUI() 按需 require 本文件；设置页「开始」分页调 render(pane, tab)，返回注销函数（关设置页 / 换分页时调）。
// 契约见 docs/SETUP-CONTRACT.md：
//   左：`setup plan` 的功能清单（勾选框 · 名称 · 磁盘 / 内存 · 齿轮跳到对应分页）+ 预设（轻量版 / 推荐 / 全部）+ 底部合计；选择存 settings.setup.selected。
//   右：① 选了什么 ② 一键检查并安装（`setup check` → fix:auto 的逐项 `setup install`，读 stdout 进度事件画进度条）③ 扫码（账号卡片）
//       ④ 同步设置（定时 / 每天上限 / 图片·视频·评论，下面 `setup backfill` 的补跑进度）⑤ AI（`setup estimate` 价格 + 文本 AI 三格 + 「试问一句」）。
//   走完（或任何时候）收成总览：每步 ✓ / 未完成 +「修改」。
// 本模块不起进程：一律经 plugin.runPy（CONVENTIONS §1.4）；结果如实显示（§1.6：进度只显示后端发来的，不编）。
// 进行中的检查 / 安装 / 试问状态放在插件对象（plugin.setupState），换分页、重画都接得上，关设置页也不打断。
'use strict';

const scheduleUI = require('./schedule-ui.js');
const STEPS = ['选功能', '检查并安装', '扫码登录', '同步设置', 'AI（选填）'];
const NUM = ['①', '②', '③', '④', '⑤'];
const TABS = new Set(['start', 'sync', 'ai', 'remote', 'advanced']);
const FREE_LINE = '不填 key 也能用：归档、浏览、关键词搜索、本地 OCR、本地语音。';
const STATUS_TEXT = { ready: '✓ 就绪', missing: '缺', partial: '不完整', failed: '没装上', unknown: '没查出来',
  queued: '等着装', installing: '安装中', stopped: '已停止', manual: '要你手动', needs_key: '在 ⑤ 填 key' };

const num = v => (v === null || v === undefined || v === '' || typeof v === 'boolean' || !Number.isFinite(Number(v)) ? null : Number(v));

// —— 选择规则（纯函数，单测直接测）——
function compMap(comps) { return new Map((comps || []).map(c => [c.id, c])); }
// 勾上一项：连它依赖的一起勾（递归）；必选项永远在
function withDeps(ids, comps) {
  const m = compMap(comps), out = new Set();
  const add = id => { if (out.has(id) || !m.has(id)) return; out.add(id); for (const d of m.get(id).depends || []) add(d); };
  for (const id of ids || []) add(id);
  for (const c of comps || []) if (c.required) add(c.id);
  return (comps || []).map(c => c.id).filter(id => out.has(id));   // 按清单顺序
}
// 取消一项：依赖它的跟着取消（递归）；必选项取消不了
function withoutDependents(ids, id, comps) {
  const m = compMap(comps);
  if (m.get(id)?.required) return withDeps(ids, comps);
  const drop = new Set([id]);
  let grew = true;
  while (grew) { grew = false; for (const c of comps || []) if (!drop.has(c.id) && !c.required && (c.depends || []).some(d => drop.has(d))) { drop.add(c.id); grew = true; } }
  return withDeps((ids || []).filter(x => !drop.has(x)), comps);
}
function toggleSelection(ids, id, on, comps) { return on ? withDeps([...(ids || []), id], comps) : withoutDependents(ids, id, comps); }
// 存着的选择 → 清单里认得的 + 依赖补齐；没选过用后端「推荐」，再没有用各项 default
function initialSelection(saved, plan) {
  const comps = plan?.components || [];
  if (Array.isArray(saved)) return withDeps(saved, comps);
  const rec = plan?.presets?.recommended;
  return withDeps(Array.isArray(rec) ? rec : comps.filter(c => c.default).map(c => c.id), comps);
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
function samePreset(ids, presets, comps) {
  const key = a => withDeps(a, comps).join(',');
  const mine = key(ids);
  return ['light', 'recommended', 'full'].find(p => Array.isArray(presets?.[p]) && key(presets[p]) === mine) || '';
}
function fmtMB(v) {
  const n = num(v);
  if (n == null) return '?';
  return n >= 1024 ? (Math.round(n / 102.4) / 10) + ' GB' : Math.round(n) + ' MB';
}
// 第 ② 步检查 / 安装的：勾了的、不是「以后」的、不要 key 的（要 key 的在第 ⑤ 步填，选填，不挡「全部就绪」）
function installTargets(ids, comps) {
  const m = compMap(comps);
  return (ids || []).filter(id => m.has(id) && !m.get(id).later && !m.get(id).needs_key);
}
// 进度事件 → {pct|null, text}
function progressView(ev) {
  if (!ev) return null;
  const done = num(ev.done), total = num(ev.total);
  const pct = done != null && total ? Math.max(0, Math.min(100, Math.round(done / total * 100))) : null;
  const mb = x => (x / 1048576).toFixed(1);
  const size = done != null && total ? (total >= 1048576 ? `${mb(done)} / ${mb(total)} MB` : `${done} / ${total}`) : '';
  return { pct, text: [ev.phase, pct != null ? pct + '%' : '', size, ev.text].filter(Boolean).join(' · ') };
}
// 补跑一行：「收藏 N 篇，已入库 M 篇，按每天 X 篇约还要 D 天」。X 用此刻设置里的「每天最多新抓」（刚改完就跟着变），缺的数不显示那段
function backfillLine(b, limit) {
  if (!b) return '';
  const total = num(b.favorites_total), archived = num(b.archived);
  const left = num(b.deferred) ?? (total != null && archived != null ? Math.max(0, total - archived) : null);
  const lim = num(limit) ?? num(b.daily_limit);
  const parts = [total != null && `收藏 ${total} 篇`, archived != null && `已入库 ${archived} 篇`];
  if (left === 0) parts.push('已全部入库');
  else if (lim === 0) parts.push('每天不限量（一次抓完，容易触发风控）');
  else if (left != null && lim) parts.push(`按每天 ${lim} 篇约还要 ${Math.ceil(left / lim)} 天`);
  else if (num(b.days_left) != null) parts.push(`约还要 ${num(b.days_left)} 天`);
  return parts.filter(Boolean).join('，');
}
function yuan(v) { const n = num(v); return n == null ? '—' : '¥' + (n < 0.1 && n > 0 ? n.toFixed(3) : n.toFixed(2)); }

module.exports = function setupUI(obsidian, plugin) {
  const { Setting, Notice } = obsidian;

  const S = () => plugin.setupState || (plugin.setupState = { plan: null, planError: null, planLoading: null, rows: {}, order: [],
    running: false, stop: false, child: null, message: '', backfill: null, estimate: null, ask: null });
  const cfg = () => {
    const s = plugin.settings;
    if (!s.setup || typeof s.setup !== 'object') s.setup = {};
    const c = s.setup;
    if (!Number.isInteger(c.step) || c.step < 1 || c.step > 5) c.step = 1;
    if (!Array.isArray(c.passed)) c.passed = [];
    return c;
  };
  const save = () => Promise.resolve(plugin.saveSettings()).catch(e => new Notice('没保存上：' + e.message, 8000));
  const comps = () => S().plan?.components || [];
  const selected = () => initialSelection(cfg().selected, S().plan);
  const nameOf = id => compMap(comps()).get(id)?.name || id;
  const aiConfigured = () => {
    try { return plugin.onboardingUI().aiConfigured(plugin.settings); }
    catch { const t = plugin.settings.textAI || {}; return t.mode === 'cli' ? !!t.command : t.mode === 'http' ? !!(t.endpoint && (t.apiKey || t.keyFile)) : false; }
  };
  const errText = e => (e && e.message) || String(e || '');
  // 深合并（对象逐层合，数组 / 标量整体替换）：把后端 install 返回的 settings_patch 合进插件设置
  const mergeInto = (dst, src) => {
    for (const [k, v] of Object.entries(src || {})) {
      if (v && typeof v === 'object' && !Array.isArray(v) && dst[k] && typeof dst[k] === 'object' && !Array.isArray(dst[k])) mergeInto(dst[k], v);
      else dst[k] = v;
    }
    return dst;
  };

  // —— 后端调用（都经 runPy；失败如实带原因）——
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
  async function loadSimple(key, args, label) {
    const st = S();
    st[key] = { loading: true };
    try {
      const { json } = await plugin.runPy(['-m', 'link_brain', 'setup', ...args], { label, fallback: label + '没有结果', timeoutMs: 120000, okCodes: [0, 1, 2] });
      if (!json) throw new Error('后台没返回结果');
      if (json.ok === false) throw new Error(json.message || label + '没成');
      st[key] = { data: json };
    } catch (e) { st[key] = { error: errText(e) }; }
    return st[key];
  }

  // ② 一键检查并安装：check → fix:auto 的逐项 install（一次一项）→ 全部 ready 才算这步完成
  async function runCheck({ install = true, only = null } = {}) {
    const st = S();
    if (st.running) return;
    st.running = true; st.stop = false; st.message = '';
    notify();
    try {
      const ids = only || installTargets(selected(), comps());
      if (!ids.length) { st.message = '左边没勾要装的功能。'; return; }
      let res;
      try {
        res = await plugin.runPy(['-m', 'link_brain', 'setup', 'check', '--components', ids.join(',')],
          { label: '检查功能', fallback: '检查没有结果', timeoutMs: 5 * 60000, okCodes: [0, 1, 2, 5] });
      } catch (e) { st.message = '没检查成：' + errText(e); return; }
      const results = res.json && Array.isArray(res.json.results) ? res.json.results : null;
      if (!results) { st.message = '没检查成：' + ((res.json && res.json.message) || '后台没返回检查结果'); return; }
      for (const r of results) {
        const manual = r.status !== 'ready' && r.fix !== 'auto';
        st.rows[r.item_id] = { ...r, status: r.status === 'ready' ? 'ready' : manual ? 'manual' : install ? 'queued' : r.status, checkStatus: r.status, progress: null };
      }
      st.order = [...new Set([...ids, ...results.map(r => r.item_id)])];
      notify();
      if (!install) return;
      for (const r of results) {
        if (st.stop) break;
        if (st.rows[r.item_id].status !== 'queued') continue;
        await installOne(r.item_id);
      }
      for (const id of Object.keys(st.rows)) if (st.rows[id].status === 'queued') st.rows[id].status = st.rows[id].checkStatus || 'missing';
    } finally {
      st.running = false; st.child = null; st.current = null;
      notify();
      if (install) loadPlan(true).then(() => notify());   // 装完清单上的「已装」跟着变
    }
  }
  async function installOne(id) {
    const st = S();
    const row = st.rows[id] = { item_id: id, ...(st.rows[id] || {}), status: 'installing', error: '', progress: null };
    st.current = id;
    notify();
    try {
      const r = await plugin.runPy(['-m', 'link_brain', 'setup', 'install', '--component', id], {
        label: '安装' + nameOf(id), fallback: '安装没有结果', timeoutMs: 90 * 60000, okCodes: [0, 1, 2, 5],
        timeoutMessage: '安装' + nameOf(id) + '超过 90 分钟没装完，已停止。再点「重试」会接着装或从头干净重来。',
        onChild: ch => { st.child = ch; },
        onLine: line => {
          let ev; try { ev = JSON.parse(line); } catch { return; }
          if (ev && ev.type === 'progress') { row.progress = ev; rowsPainter?.(); }
        },
      });
      const j = r.json;
      if (st.stop) { row.status = 'stopped'; row.error = '已停止。再点「重试」会接着装或从头干净重来。'; }
      else if (j && j.type !== 'progress' && (j.type === 'result' || 'ok' in j || 'status' in j)) {
        const ok = j.status === 'ready' || (j.status == null && j.ok === true);
        row.status = ok ? 'ready' : 'failed';
        row.error = ok ? '' : (j.message || j.error || '没装上（后台没说原因）');
        if (j.code) row.code = j.code;
        if (j.detail) row.detail = j.detail;
        if (j.fix_hint) row.fix_hint = j.fix_hint;
        if (j.fix) row.fix = j.fix;
        if (!ok && j.manual) row.status = 'manual';   // 只能手动做的（如 Dataview、发布地址没配）：给做法，不算装失败
        // 后端装完改了插件设置（如 CapsWriter 地址 / 端口、OCR 模型目录）：合进内存里的设置再存，
        // 不然插件下次保存会用旧设置把它盖掉
        if (j.settings_patch && typeof j.settings_patch === 'object') {
          try { mergeInto(plugin.settings, j.settings_patch); await plugin.saveSettings?.(); }
          catch (e) { row.error = (row.error ? row.error + '；' : '') + '设置没存上：' + errText(e); }
        }
      } else { row.status = 'failed'; row.error = (String(r.err || '').trim().split('\n').pop()) || '安装没有返回结果'; }
    } catch (e) {
      row.status = st.stop ? 'stopped' : 'failed';
      row.error = st.stop ? '已停止。再点「重试」会接着装或从头干净重来。' : errText(e);
    }
    st.current = null; st.child = null;
    notify();
  }
  async function stopInstall() {
    const st = S();
    st.stop = true;
    const ch = st.child;
    if (ch && ch.pid) { try { await plugin.killTree(ch.pid); } catch (e) { console.error('[lb] 停止安装', e); } }
    notify();
  }
  async function retry(id) {
    const st = S();
    if (st.running) return;
    st.running = true; st.stop = false;
    try { await installOne(id); } finally { st.running = false; notify(); loadPlan(true).then(() => notify()); }
  }

  // 每步完成了没有（总览和步骤条用）
  function stepState(n) {
    const c = cfg(), st = S();
    if (n === 1) return Array.isArray(c.selected) ? { done: true, text: `勾了 ${c.selected.length} 项` } : { done: false, text: '还没选（先用推荐）' };
    if (n === 2) {
      if (!st.plan) return { done: false, text: '还没检查' };
      const m = compMap(comps());
      const ids = installTargets(selected(), comps());
      if (!ids.length) return { done: false, text: '没有要装的（左边没勾）' };
      const bad =ids.filter(id => (st.rows[id]?.status || m.get(id)?.status) !== 'ready');
      return bad.length ? { done: false, text: `${bad.length} 项没就绪：` + bad.map(nameOf).join('、') } : { done: true, text: '全部就绪' };
    }
    if (n === 3) {
      const a = plugin.accountState?.xhs;
      return a === 'ready' ? { done: true, text: '已登录' } : { done: false, text: a && a !== 'checking' ? '还没登录' : '还没确认' };
    }
    if (n === 4) {
      const lim = dailyLimit();
      return c.passed.includes(4) ? { done: true, text: '每天最多新抓 ' + (lim === 0 ? '不限' : lim + ' 篇') } : { done: false, text: '还没看过' };
    }
    if (aiConfigured()) return { done: true, text: '已配置文本 AI' };
    return { done: false, text: c.passed.includes(5) ? '没填（选填，不填也能用）' : '还没填（选填）' };
  }
  let tabRef = null;
  const dailyLimit = () => (tabRef && tabRef.dailyLimit ? tabRef.dailyLimit() : num(plugin.settings.sync?.dailyNewLimit));

  // —— 画面 ——（render 一次 = 当前这张设置页；notify 只重画会变的几块，不重画账号卡片）
  let live = null;
  function notify() { if (live) live.update(); }

  function render(pane, tab) {
    tabRef = tab;
    const root = pane.createDiv({ cls: 'lb-setup' });
    const left = root.createDiv({ cls: 'lb-setup-left' });
    const right = root.createDiv({ cls: 'lb-setup-right' });
    const me = { alive: true, left, right, update: () => {} };
    live = me;

    // 左：预设 + 功能清单 + 合计
    const paintLeft = () => {
      left.empty();
      const st = S();
      left.createEl('h3', { text: '要哪些功能' });
      if (!st.plan) {
        if (st.planError) {
          const box = left.createDiv({ cls: 'lb-setup-error' });
          box.createEl('p', { text: '读不到功能清单：' + errText(st.planError) });
          const acts = box.createDiv({ cls: 'lb-setup-actions' });
          acts.createEl('button', { text: '重试' }).onclick = () => { st.planError = null; paintLeft(); loadPlan(true).then(() => me.alive && paintAll()); };
          if (st.planError.backendMissing) acts.createEl('button', { text: '复制安装命令' }).onclick = () => plugin.copyText('uv tool install link-brain');
        } else left.createEl('p', { cls: 'setting-item-description lb-loading', text: '读取功能清单' });
        return;
      }
      const ids = selected(), cs = comps();
      const presets = st.plan.presets || {};
      const cur = samePreset(ids, presets, cs);
      const pre = left.createDiv({ cls: 'lb-setup-presets' });
      for (const [k, label] of [['light', '轻量版（不要任何 key）'], ['recommended', '推荐'], ['full', '全部']]) {
        if (!Array.isArray(presets[k])) continue;
        const b = pre.createEl('button', { cls: 'lb-preset' + (cur === k ? ' is-active' : ''), text: label, attr: { 'data-preset': k } });
        b.onclick = async () => { cfg().selected = withDeps(presets[k], cs); await save(); paintAll(); };
      }
      const list = left.createDiv({ cls: 'lb-setup-list' });
      const sel = new Set(ids);
      for (const c of cs) {
        const row = list.createDiv({ cls: 'lb-comp' + (sel.has(c.id) ? ' is-on' : '') + (c.required ? ' is-required' : '') + (c.later ? ' is-later' : ''), attr: { 'data-id': c.id } });
        const box = row.createEl('input', { type: 'checkbox', cls: 'lb-comp-check' });
        box.type = 'checkbox';
        box.checked = sel.has(c.id);
        box.disabled = !!c.required;
        if (c.required) box.setAttribute('title', '必需，不能取消');
        box.onchange = async () => {
          if (c.required) { box.checked = true; return; }
          cfg().selected = toggleSelection(selected(), c.id, !!box.checked, cs);
          await save(); paintAll();
        };
        const info = row.createDiv({ cls: 'lb-comp-info' });
        const head = info.createDiv({ cls: 'lb-comp-name' });
        head.createSpan({ text: c.name || c.id });
        if (c.later) head.createSpan({ cls: 'lb-tag is-later', text: '以后' });
        if (c.needs_key) head.createSpan({ cls: 'lb-tag', text: '要 key' });
        if (c.required) head.createSpan({ cls: 'lb-tag', text: '必需' });
        const meta = info.createDiv({ cls: 'lb-comp-meta' });
        meta.createSpan({ text: `磁盘 ${fmtMB(c.disk_mb)} · 内存 ${fmtMB(c.ram_mb)}` });
        const status = st.rows[c.id]?.status || c.status;
        if (status && !c.later) meta.createSpan({ cls: 'lb-comp-status is-' + status, text: ' · ' + (status === 'ready' ? '已装好' : STATUS_TEXT[status] || status) });
        if (c.desc || c.detail) info.setAttribute('title', [c.desc, c.detail].filter(Boolean).join('\n'));
        const tabId = TABS.has(c.settings_tab) ? c.settings_tab : 'advanced';
        const gear = row.createEl('button', { cls: 'lb-comp-gear clickable-icon', text: '⚙', attr: { 'aria-label': '详细设置', title: '详细设置', 'data-tab': tabId } });
        gear.onclick = () => tab.showTab(tabId);
      }
      const t = totals(ids, cs);
      const foot = left.createDiv({ cls: 'lb-setup-total' });
      foot.createDiv({ cls: 'lb-setup-total-line', text: `合计：磁盘 ${fmtMB(t.disk)} · 内存 ${fmtMB(t.ram)}` + (t.unknown ? `（另有 ${t.unknown} 项没给数）` : '') });
      if (st.plan.totals_basis) foot.createDiv({ cls: 'setting-item-description', text: st.plan.totals_basis });
    };

    // 右：标题 + 竖排步骤条 + 当前步 + 上一步 / 下一步；或总览
    const head = right.createDiv({ cls: 'lb-setup-head' });
    const bar = right.createDiv({ cls: 'lb-steps' });
    const body = right.createDiv({ cls: 'lb-step-body' });
    const nav = right.createDiv({ cls: 'lb-step-nav' });
    let paintStepParts = null;   // 当前步里会变的那几块（安装行、试问回答……）

    const paintHead = () => {
      head.empty();
      const c = cfg();
      head.createEl('h3', { text: c.collapsed ? '设置总览' : '设置指引' });
      const b = head.createEl('button', { cls: 'lb-setup-toggle', text: c.collapsed ? '展开向导' : '收起为总览' });
      b.onclick = async () => { c.collapsed = !c.collapsed; await save(); paintRight(); };
    };
    const paintBar = () => {
      bar.empty();
      const c = cfg();
      bar.toggleClass('is-hidden', !!c.collapsed);
      if (c.collapsed) return;
      STEPS.forEach((title, i) => {
        const n = i + 1, ss = stepState(n);
        const it = bar.createEl('button', { cls: 'lb-step' + (n === c.step ? ' is-current' : '') + (ss.done ? ' is-done' : ''), attr: { 'data-step': String(n) } });
        it.createSpan({ cls: 'lb-step-num', text: ss.done && n !== c.step ? '✓' : NUM[i] });
        it.createSpan({ cls: 'lb-step-title', text: title });
        it.onclick = async () => { c.step = n; await save(); paintRight(); };
      });
    };
    const paintOverview = () => {
      const c = cfg();
      const list = body.createDiv({ cls: 'lb-overview' });
      STEPS.forEach((title, i) => {
        const n = i + 1, ss = stepState(n);
        const row = list.createDiv({ cls: 'lb-overview-row' + (ss.done ? ' is-done' : ''), attr: { 'data-step': String(n) } });
        row.createSpan({ cls: 'lb-overview-mark', text: ss.done ? '✓' : '○' });
        row.createSpan({ cls: 'lb-overview-title', text: NUM[i] + ' ' + title });
        row.createSpan({ cls: 'lb-overview-state', text: ss.done ? ss.text : '未完成 · ' + ss.text });
        const b = row.createEl('button', { text: '修改' });
        b.onclick = async () => { c.collapsed = false; c.step = n; await save(); paintRight(); };
      });
    };
    const paintNav = () => {
      nav.empty();
      const c = cfg();
      if (c.collapsed) return;
      const prev = nav.createEl('button', { cls: 'lb-step-prev', text: '上一步' });
      prev.disabled = c.step <= 1;
      prev.onclick = async () => { if (c.step > 1) { c.step--; await save(); paintRight(); } };
      const last = c.step >= 5;
      const next = nav.createEl('button', { cls: 'lb-step-next mod-cta', text: last ? '完成' : '下一步' });
      next.onclick = async () => {
        if (!c.passed.includes(c.step)) c.passed.push(c.step);
        if (c.step === 1 && !Array.isArray(c.selected)) c.selected = selected();   // 走过第 ① 步 = 认了现在的勾选
        if (last) c.collapsed = true; else c.step++;
        await save(); paintRight();
      };
    };
    const paintBody = () => {
      body.empty(); paintStepParts = null;
      const c = cfg();
      if (c.collapsed) { paintOverview(); return; }
      body.createEl('h4', { cls: 'lb-step-heading', text: NUM[c.step - 1] + ' ' + STEPS[c.step - 1] });
      try { [step1, step2, step3, step4, step5][c.step - 1](body); }
      catch (e) { console.error('[lb] 开始页这一步没画上', e); body.createEl('p', { cls: 'lb-setup-error', text: '这一步没画上：' + errText(e) }); }
    };
    const paintRight = () => { if (!me.alive) return; paintHead(); paintBar(); paintBody(); paintNav(); };
    const paintAll = () => { if (!me.alive) return; paintLeft(); paintRight(); };
    me.update = () => { if (!me.alive) return; paintLeft(); paintBar(); paintStepParts?.(); };
    const paintRows = () => { if (me.alive) paintStepParts?.(); };

    rowsPainter = paintRows;

    // ① 选了什么
    function step1(box) {
      const ids = selected(), m = compMap(comps());
      box.createEl('p', { cls: 'setting-item-description', text: '左边勾的就是要装的功能，随时可以改；右边一步步装好、登录、设好同步。灰勾的是必需项。' });
      if (!S().plan) { box.createEl('p', { cls: 'setting-item-description', text: '功能清单还没读到。' }); }
      else {
        const t = totals(ids, comps());
        const sum = box.createDiv({ cls: 'lb-step-summary' });
        sum.createDiv({ text: `你勾了 ${ids.length} 项：` + ids.map(nameOf).join('、') });
        sum.createDiv({ text: `合计约占磁盘 ${fmtMB(t.disk)}、内存 ${fmtMB(t.ram)}。` });
        const keyed = ids.filter(id => m.get(id)?.needs_key);
        if (keyed.length) sum.createDiv({ text: '要 API key 的：' + keyed.map(nameOf).join('、') + '（第 ⑤ 步填，不填也能用别的）' });
        const later = ids.filter(id => m.get(id)?.later);
        if (later.length) sum.createDiv({ text: '标了「以后」的这次不装：' + later.map(nameOf).join('、') + '（要用时去对应分页）' });
      }
      tab.fieldCollectionFolder(box);
    }

    // ② 一键检查并安装
    function step2(box) {
      box.createEl('p', { cls: 'setting-item-description', text: '按左边勾的检查一遍：缺的能自动装的逐项装好（显示进度），装不了的给你步骤。全部就绪就不用再回来补装。' });
      const acts = box.createDiv({ cls: 'lb-setup-actions' });
      const rowsBox = box.createDiv({ cls: 'lb-install-rows' });
      const msg = box.createDiv({ cls: 'lb-install-summary' });
      const paint = () => {
        const st = S();
        acts.empty();
        if (st.running) {
          acts.createEl('button', { cls: 'lb-install-stop', text: '停止' }).onclick = () => stopInstall();
        } else {
          const go = acts.createEl('button', { cls: 'lb-install-go mod-cta', text: '一键检查并安装' });
          go.onclick = () => runCheck({ install: true });
          go.disabled = !st.plan;
          const chk = acts.createEl('button', { cls: 'lb-install-check', text: '只重新检查' });
          chk.onclick = () => runCheck({ install: false });
          chk.disabled = !st.plan;
        }
        rowsBox.empty();
        for (const id of st.order) {
          const r = st.rows[id]; if (!r) continue;
          const row = rowsBox.createDiv({ cls: 'lb-install-row is-' + r.status, attr: { 'data-id': id } });
          const line = row.createDiv({ cls: 'lb-install-line' });
          line.createSpan({ cls: 'lb-install-name', text: nameOf(id) });
          line.createSpan({ cls: 'lb-install-status', text: STATUS_TEXT[r.status] || r.status });
          const pv = r.status === 'installing' || (r.progress && r.status !== 'ready') ? progressView(r.progress) : null;
          if (r.status === 'installing') {
            const p = row.createDiv({ cls: 'lb-bar' + (pv && pv.pct != null ? '' : ' is-indeterminate') });
            const fill = p.createDiv({ cls: 'lb-bar-fill' });
            if (pv && pv.pct != null) fill.style.width = pv.pct + '%';
            row.createDiv({ cls: 'lb-install-progress', text: pv ? pv.text : '正在开始…' });
          } else if (pv && r.status !== 'ready') row.createDiv({ cls: 'lb-install-progress', text: '停在：' + pv.text });
          if (r.detail && r.status !== 'installing') row.createDiv({ cls: 'lb-install-detail', text: r.detail });
          if (r.error) row.createDiv({ cls: 'lb-install-error', text: (r.status === 'stopped' ? '' : '原因：') + r.error });
          if (r.status === 'manual' && r.fix_hint) row.createDiv({ cls: 'lb-install-hint', text: '怎么做：' + r.fix_hint });
          const btns = row.createDiv({ cls: 'lb-install-btns' });
          if (!st.running && (r.status === 'failed' || r.status === 'stopped') && r.fix !== 'manual') btns.createEl('button', { text: '重试' }).onclick = () => retry(id);
          if (id === 'dataview' && r.status !== 'ready') btns.createEl('button', { text: '打开第三方插件' }).onclick = () => plugin.openPluginSettings('community-plugins');
          if (!st.running && r.status === 'manual') btns.createEl('button', { text: '重新检查' }).onclick = () => runCheck({ install: false, only: [id] });
        }
        const ss = stepState(2);
        msg.className = 'lb-install-summary' + (ss.done ? ' is-done' : '');
        msg.setText(st.message || (st.running ? (st.current ? '正在装：' + nameOf(st.current) : '正在检查…') : st.order.length ? (ss.done ? '✓ 全部就绪' : '还没全部就绪：' + ss.text) : ''));
      };
      paintStepParts = paint;
      paint();
    }

    // ③ 扫码登录：就是账号卡片（同一个扫码流程）
    function step3(box) {
      box.createEl('p', { cls: 'setting-item-description', text: '用手机小红书 App 扫一次码。一个号覆盖收藏、评论、附件；登录过期才需要再扫。可以先跳过，以后在「同步与内容」分页扫。' });
      try { plugin.renderAccounts(box); }
      catch (e) { box.createEl('p', { cls: 'lb-setup-error', text: '账号卡片没画上：' + errText(e) }); }
    }

    // ④ 同步设置：每天几点 / 每天上限 / 图片·视频·评论 / 附件 + 补跑进度
    function step4(box) {
      // 10-03：定时和设置页「定时…」弹窗是同一个组件（schedule-ui.js）：一次性 / 每周几 / 每天几次 / 每 1–6 小时
      const sched = new Setting(box).setName('定时同步').setDesc('关着 Obsidian 也按时同步（电脑要开着）。');
      sched.settingEl.addClass('lb-sched-setting');
      try { me.sched = scheduleUI(obsidian, plugin).render(box.createDiv({ cls: 'lb-sched-host' })); }
      catch (e) { box.createEl('p', { cls: 'lb-setup-error', text: '定时设置没加载上：' + errText(e) }); }
      tab.fieldDailyLimit(box, () => paintBackfill());
      tab.fieldMediaToggles(box);
      box.createEl('p', { cls: 'setting-item-description', text: '附件（PDF / Word 等）：同步时自动下载、在本机转成文字，不用设置；网页上要手动下载的，放进「同步与内容」里的下载文件夹会自动认领。' });
      const bf = box.createDiv({ cls: 'lb-backfill' });
      const paintBackfill = () => {
        bf.empty();
        const b = S().backfill;
        if (!b || b.loading) { bf.createDiv({ cls: 'setting-item-description lb-loading', text: '读取补跑进度' }); return; }
        if (b.error) { bf.createDiv({ cls: 'setting-item-description', text: '读不到补跑进度：' + b.error }); return; }
        const d = b.data, line = backfillLine(d, dailyLimit());
        bf.createDiv({ cls: 'lb-backfill-line', text: line || '还没有收藏数据（登录并同步一次后再看）' });
        const total = num(d.favorites_total), done = num(d.archived);
        if (total && done != null) {
          const p = bf.createDiv({ cls: 'lb-bar' });
          p.createDiv({ cls: 'lb-bar-fill' }).style.width = Math.min(100, Math.round(done / total * 100)) + '%';
        }
      };
      paintStepParts = paintBackfill;
      paintBackfill();
      if (!S().backfill || S().backfill.error) loadSimple('backfill', ['backfill'], '读取补跑进度').then(() => { if (me.alive && cfg().step === 4) paintBackfill(); });
    }

    // ⑤ AI（选填）：不填也能用 → 建议接口 + 每 100 篇价格 → 填 key → 试问一句
    function step5(box) {
      box.createEl('p', { cls: 'lb-free-line', text: FREE_LINE });
      const est = box.createDiv({ cls: 'lb-estimate' });
      const paintEst = () => {
        est.empty();
        const e = S().estimate;
        if (!e || e.loading) { est.createDiv({ cls: 'setting-item-description lb-loading', text: '估算价格' }); return; }
        if (e.error) { est.createDiv({ cls: 'setting-item-description', text: '估不出价格：' + e.error }); return; }
        const d = e.data;
        est.createDiv({ cls: 'lb-estimate-head', text: `建议接口和价格（每 ${num(d.posts) || 100} 篇）` });
        const tbl = est.createDiv({ cls: 'lb-estimate-list' });
        for (const it of d.items || []) {
          const row = tbl.createDiv({ cls: 'lb-estimate-row', attr: { 'data-id': it.id || '' } });
          row.createSpan({ cls: 'lb-estimate-name', text: it.name || it.id });
          row.createSpan({ cls: 'lb-estimate-model', text: [it.provider, it.model].filter(Boolean).join(' · ') });
          row.createSpan({ cls: 'lb-estimate-price', text: yuan(it.yuan) + ' / ' + (it.per || '100 篇') });
          if (it.how) row.setAttribute('title', it.how);
        }
        const basis = d.basis || {};
        const how = basis.from_library
          ? `按你库里 ${num(basis.sample) ?? '?'} 篇的平均量估：每篇约 ${num(basis.avg_chars) ?? '?'} 字、${num(basis.avg_images) ?? '?'} 张图、${num(basis.avg_video_min) ?? '?'} 分钟视频。`
          : '库里还没有收藏，按典型值估。';
        const asOf = d.prices && d.prices.as_of ? `价格核对于 ${d.prices.as_of}。` : '价格日期未知。';
        est.createDiv({ cls: 'setting-item-description', text: how + asOf + (Array.isArray(d.local_free) && d.local_free.length ? '本地免费：' + d.local_free.map(nameOf).join('、') + '。' : '') });
        if (Array.isArray(d.prices?.sources) && d.prices.sources.length) est.createDiv({ cls: 'setting-item-description lb-estimate-src', text: '出处：' + d.prices.sources.join('  ') });
      };
      paintEst();
      if (!S().estimate || S().estimate.error) loadSimple('estimate', ['estimate', '--posts', '100'], '估算价格').then(() => { if (me.alive && cfg().step === 5) paintEst(); });

      tab.sectionTextAI(box, { heading: false });

      // 试问一句：走真实问答（和问收藏页同一个 answerArchive），回答直接显示在这一步
      let question = '我的收藏里有什么值得先看的？';
      const ask = new Setting(box).setName('试问一句').setDesc('用上面的文本 AI 真问一次你的收藏（和「问收藏」页同一条路）。');
      ask.settingEl.addClass('lb-ask-row');
      ask.addText(t => t.setValue(question).onChange(v => { question = v; }));
      ask.addButton(b => b.setButtonText('问').setCta().onClick(() => askOnce(question)));
      const out = box.createDiv({ cls: 'lb-ask-out' });
      const paintAsk = () => {
        out.empty();
        const a = S().ask;
        if (!a) return;
        if (a.status === 'running') {
          const top = out.createDiv({ cls: 'lb-ask-phase lb-loading', text: a.phase || '正在问' });
          top.createEl('button', { cls: 'lb-ask-stop', text: '停止' }).onclick = () => plugin.stopArchiveAnswer?.();
        }
        if (a.status === 'error') out.createDiv({ cls: 'lb-ask-error', text: '没答上：' + a.error });
        if (a.status === 'cancelled') out.createDiv({ cls: 'lb-ask-phase', text: '已停止生成' });
        if (a.text) out.createDiv({ cls: 'lb-ask-answer', text: a.text });
        if (a.status === 'ok' && a.sources != null) out.createDiv({ cls: 'setting-item-description', text: `用了 ${a.sources} 条收藏做依据。` });
      };
      paintStepParts = () => { paintEst(); paintAsk(); };
      paintAsk();
    }
    async function askOnce(question) {
      const st = S();
      if (st.ask && st.ask.status === 'running') return;
      const q = String(question || '').trim();
      if (!q) { new Notice('先写一句要问的'); return; }
      const a = st.ask = { status: 'running', phase: '', text: '' };
      notify();
      try {
        const r = await plugin.answerArchive({ question: q, onPhase: t => { a.phase = t; rowsPainter?.(); }, onDelta: d => { a.text += d || ''; rowsPainter?.(); } });
        if (r && r.status === 'cancelled') { a.status = 'cancelled'; a.text = r.markdown || a.text; }
        else { a.status = 'ok'; a.text = (r && r.markdown) || a.text || '（回答是空的）'; a.sources = Array.isArray(r?.sources) ? r.sources.length : null; }
      } catch (e) { a.status = 'error'; a.error = errText(e); }
      notify();
    }

    plugin.setupNotify = () => { if (me.alive) { paintBar(); if (cfg().collapsed) paintBody(); } };
    paintAll();
    if (!S().plan) loadPlan().then(() => { if (me.alive) paintAll(); });
    return () => {
      me.alive = false;
      if (live === me) live = null;
      if (rowsPainter === paintRows) { rowsPainter = null; plugin.setupNotify = null; }
    };
  }
  let rowsPainter = null;

  return { render, loadPlan, runCheck, installOne, stopInstall, stepState, state: S,
    _internals: { withDeps, withoutDependents, toggleSelection, initialSelection, totals, samePreset, fmtMB, installTargets, progressView, backfillLine, yuan } };
};
module.exports._internals = { withDeps, withoutDependents, toggleSelection, initialSelection, totals, samePreset, fmtMB, installTargets, progressView, backfillLine, yuan };

// home-ui.js — 设置页「概览」和「AI」两栏的内容 +「一键装好 / 跑完」+ 零配置首次自动跑（docs/SETUP-CONTRACT.md）。
//   1009 作者的裁决：没有分步向导；装上就按轻量版自动跑；功能是开关、一个「一键装好 / 跑完」按钮。
//   1010 作者：设置页恢复分栏（概览 / 收藏与同步 / AI / 连接其他 AI / 高级），按「什么都不懂的新用户」重写——
//     概览 = 状态（账号 · 收藏同步 · 评论补齐 · 问题 · 这台电脑）+ 这一栏唯一的主按钮「一键装好 / 跑完」；
//     AI  = 第一句「要不要 AI：不填也能用；填了多出 问收藏、自动概要、识图」→ 每个功能一个开关、旁边标价钱
//           （本地的写「免费（本机跑）」，要钱的用 `setup estimate` 的「约 ¥x / 100 篇」「约 ¥x / 次」，估不出写「按用量」）
//           → 去哪弄密钥、大概多少钱 → 打开了的那几项的接口 / 密钥 / 模型。
//   文案规矩：每项说明一行；「?」悬停只讲规则（后果写在按钮字或确认框里）；子选项只在父开关打开后出现；
//           按钮不能点时旁边一句为什么；开关改了立刻存，存失败拨回原值并提示一句。
// main.js 只接几行：homeUI() 按需 require；设置页（1027 六组）⑥ 修复「更多」调 renderStatus / renderRun，④ 的功能选择走 featureToggle / setFeature；
//   onboarding-ui.startup 调 firstRun。1027：旧的 renderAI（「AI」一栏的开关清单 + 填推荐值）删掉——功能开关只在设置页④一处。
// 本模块不起进程：一律经 plugin.runPy / spawnPy（CONVENTIONS §1.4、§6.1）；进度只显示后端发来的（§1.6）。
'use strict';

const LIGHT = ['core', 'reader', 'ocr'];
const STATUS_TEXT = { ready: '已装好', missing: '还没装', partial: '没装全', failed: '没装上', unknown: '没查出来', needs_key: '要填密钥' };
const STAGE_MARK = { running: '⟳', ok: '✓', skipped: '–', failed: '✗', waiting: '…' };   // waiting：小红书等扫码（1103，不算失败）
const AI_CAP = { ai_text: 'textAI', ai_vision: 'visionAI' };
// 1010：给新手看的名字（后端 setup plan 的名字是给命令行 / 日志的，这里只换说法）。price：'free' = 本机跑；数组 = setup estimate 的哪几项
const FEATURE_TEXT = {
  core: { name: '程序本体', short: '程序', desc: '同步、浏览、关键词搜索' },
  reader: { name: '读取组件', short: '读取组件', desc: '读小红书收藏、评论、附件用' },
  ocr: { name: '认图片里的字', short: '认字', desc: '本地 OCR：截图、表格里的字也能搜到', price: 'free' },
  asr: { name: '视频说话转文字', short: '语音转文字', desc: '本地语音识别：视频里说的话也能搜到', price: 'free' },
  capslock: { name: '按住 CapsLock 说话打字', short: 'CapsLock 说话', desc: '在任何软件里按住 CapsLock 说话，松开就出字', price: 'free' },
  ai_text: { name: '问收藏 · 自动概要 · 打标签', short: '问收藏', desc: '用你的收藏回答问题；每篇自动写概要、打标签', price: [['summary', '概要和打标签'], ['ask', '问收藏']] },
  ai_vision: { name: '识图', short: '识图', desc: '看懂表格、流程图、截图，看到的也能搜到', price: [['vision', '']] },
};
const AI_ORDER = ['ocr', 'asr', 'capslock', 'ai_text', 'ai_vision'];
// 1102：`setup run` 结果 code → 结束提示上给哪颗按钮。号的事（掉登录 / 验证 / 风控：NEEDS_HUMAN 或 NEEDS_HUMAN.<账号码>）才出「去扫码 / 验证」；
// 读取组件没起来（TRANSIENT.DISCONNECTED）/ 没装（NEEDS_HUMAN.NOT_INSTALLED）出「重试」——以前一律弹扫码，被杀毒隔离的人去扫了也白扫
const READER_CODES = ['TRANSIENT.DISCONNECTED', 'NEEDS_HUMAN.NOT_INSTALLED'];
const ACCOUNT_SUBCODES = ['NOT_LOGGED_IN', 'CAPTCHA_REQUIRED', 'ACCOUNT_RISK', 'RISK_HOLD', 'WRONG_ACCOUNT', 'ACCOUNT_BLOCKED'];
function resultKind(code) {
  const c = String(code || '');
  if (READER_CODES.includes(c)) return 'reader';
  if (c === 'NEEDS_HUMAN' || ACCOUNT_SUBCODES.some(x => c === 'NEEDS_HUMAN.' + x)) return 'account';
  return '';
}
const RUN_STATE_FILE = '_archive/setup-run.json';
const NO_RESULT_TEXT = '安装程序没有返回结果，详情见日志';
// setup-run.json（pipeline 每步落盘）→ 设置页的 run 对象。pid 活着 = 还在后台跑（续画）；死了又没 result = 上次没跑完
function runFromState(state, alive) {
  if (!state || typeof state !== 'object' || !Array.isArray(state.stages)) return null;
  const run = { state: 'running', resumed: true, stages: {}, current: null, install: null, result: null,
    startedAt: Date.parse(state.started_at || '') || Date.now(), pid: state.pid || null };
  const count = Object.keys(STAGE_LABEL).length;
  state.stages.forEach((s, i) => { if (s && s.id) run.stages[s.id] = { label: s.label || s.id, index: i + 1, count, state: s.state || 'ok', text: s.text || '' }; });
  const lastLabel = state.stages.length ? (state.stages[state.stages.length - 1].label || '') : '';
  if (state.current) { run.current = state.current; run.stages[state.current] = { label: STAGE_LABEL[state.current] || state.current, index: Object.keys(run.stages).length + 1, count, state: 'running', text: '' }; }
  if (!state.running && state.result && typeof state.result === 'object') { run.state = 'done'; run.result = state.result; return run; }
  if (state.running && alive) return run;
  const stopped = state.current ? (STAGE_LABEL[state.current] || state.current) : lastLabel;
  run.state = 'done';
  run.result = { ok: false, interrupted: true, code: 'TRANSIENT.INTERRUPTED', stopped,
    message: stopped ? `上次没跑完，停在「${stopped}」` : '上次没跑完' };
  return run;
}
const STAGE_LABEL = { catalog_first: '生成目录页', install: '装好要用的组件', login: '确认小红书登录', sync: '同步收藏（含 OCR / 识图 / 概要）', enrich: '补识图 / 概要',
  catalog: '整理目录', embed: '建语义索引', comments: '评论补齐（读不完的后台接着补）' };

const num = v => (v === null || v === undefined || v === '' || typeof v === 'boolean' || !Number.isFinite(Number(v)) ? null : Number(v));
// 1028：后台补评论多久没刷新算停了——状态文件里 Python 写的 stale_min 优先（comment_fill.STALE_MIN），旧文件按 15 分钟
const fillStaleMs = st => (Number(st?.stale_min) > 0 ? Number(st.stale_min) : 15) * 60000;

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
// 1009 作者：没选过 = 轻量版（装上就能用，不要任何 key）
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
// 1010 作者：每个功能旁标清价钱。本地的「免费（本机跑）」；要钱的用 setup estimate：「约 ¥x / 100 篇」「约 ¥x / 次」；估不出「按用量」
function priceText(id, est) {
  const f = FEATURE_TEXT[id];
  if (!f || !f.price) return '';
  if (f.price === 'free') return '免费（本机跑）';
  if (!est) return '按用量（在估）';
  const items = (est.data && Array.isArray(est.data.items)) ? est.data.items : [];
  const bits = [];
  for (const [key, label] of f.price) {
    const it = items.find(x => x && x.id === key);
    const v = it ? num(it.yuan) : null;
    if (v == null) continue;
    bits.push(`${label ? label + ' ' : ''}约 ${yuan(v)} / ${it.per === '次' ? '次' : (it.per || '100 篇')}`);
  }
  return bits.length ? bits.join(' · ') : '按用量';
}
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
  if (ev.component && ev.stage === 'install') {
    // 1103：后端每装完一项报一条结果（state ok / failed + status）：记下来、清掉「正在装 X」；其余是下载进度
    if (ev.state === 'ok' || ev.state === 'failed') {
      run.installed = { ...(run.installed || {}), [ev.component]: ev.status || (ev.state === 'ok' ? 'ready' : 'failed') };
      run.install = null;
    } else run.install = ev;
    return run;
  }
  if (!ev.stage) return run;
  if (ev.stage !== 'install' || ev.state !== 'running') run.install = null;   // 装组件那一步过去了：别再挂着「正在装」
  const cur = run.stages[ev.stage] || {};
  run.stages[ev.stage] = { ...cur, label: ev.label || cur.label, index: ev.index || cur.index, count: ev.count || cur.count,
    state: ev.state || cur.state || 'running', text: ev.text != null && ev.text !== '' ? ev.text : (ev.state !== 'running' ? '' : cur.text || '') };
  if (ev.state === 'running') run.current = ev.stage;
  return run;
}
// 评论补齐那一行（状态文件 + fill-status 的统计）
// 1103：懒人安装卡片上那一句结果（完整的在「06 修复」）：做成了 = 原话（太长只留第一句）；没成 = 一句是哪类事
function briefResult(r) {
  if (!r) return '';
  const msg = String(r.message || '');
  if (r.ok) return msg.length <= 48 ? msg : msg.split('；')[0];
  const failed = (r.stages || []).filter(x => x && x.state === 'failed').length;
  const code = String(r.code || '');
  if (r.noResult) return '这一轮没正常收尾';
  if (code === 'TRANSIENT.DISCONNECTED') return '读取组件没起来';
  if (code === 'NEEDS_HUMAN.NOT_INSTALLED') return '读取组件没装上';
  if (code.startsWith('NEEDS_HUMAN')) return '小红书要你处理（登录 / 验证）';
  return failed ? `跑完了，有 ${failed} 步没成` : (msg.split('；')[0] || '没跑完');
}

function fillLine(st, info, now = Date.now()) {
  const live = st && ['running', 'waiting', 'paused'].includes(st.state) && now - Date.parse(st.updated_at || '') < fillStaleMs(st);
  if (live) return st.message || '后台在补评论';
  if (info && info.ok) return info.pending ? `${info.pending} 篇的评论还没补齐（共缺 ${info.missing} 条回复）` + (info.stuck ? ` · ${info.stuck} 篇连着补不上（见问题列表）` : '')
    : '评论都补齐了' + (info.stuck ? `（${info.stuck} 篇连着补不上，见问题列表）` : '');
  if (st && st.message) return st.message;
  return '';
}

module.exports = function homeUI(obsidian, plugin) {
  const { Setting, Notice } = obsidian;
  const S = () => plugin.homeState || (plugin.homeState = { plan: null, planError: null, planLoading: null, estimate: null, estimateLoading: null,
    run: null, fillInfo: null, child: null });
  const setup = () => {
    const s = plugin.settings;
    if (!s.setup || typeof s.setup !== 'object') s.setup = {};
    return s.setup;
  };
  const save = () => Promise.resolve(plugin.saveSettings()).catch(e => new Notice('没保存上：' + e.message, 8000));
  const comps = () => S().plan?.components || [];
  const selected = () => initialSelection(setup().selected, S().plan);
  // 1010：本机那几样（认字 / 语音转文字 / CapsLock 说话）的开关显示「实际在用的」：选过，或者装好了而且设置里正开着——
  // 老用户的选择列表里可能没有，但其实一直在用（比如一直按 CapsLock 说话），开关要和实际对得上
  const runtimeOn = id => {
    const s = plugin.settings || {};
    if (id === 'ocr') return !!s.ocr && s.ocr.mode !== 'off';
    if (id === 'asr') return !!s.asrAI && s.asrAI.mode === 'capswriter';
    if (id === 'capslock') return !!(s.voice && s.voice.capsLock);
    return false;
  };
  const effective = () => {
    const ids = new Set(selected());
    for (const comp of comps()) if (!ids.has(comp.id) && comp.status === 'ready' && runtimeOn(comp.id)) ids.add(comp.id);
    return withDeps([...ids], comps());
  };
  const errText = e => (e && e.message) || String(e || '');
  // 1018 作者：识图「还没配」——关掉「识图转文字」会顺带关掉依赖它的识图，再打开认字却不补回来，识图就悄悄停了。
  // 现在：关掉一项时记下顺带关掉的（setup.dropped[这一项]），再打开这一项就把它们一起开回来。
  function nextSelection(cur, id, v, cs) {
    const s = setup();
    if (!s.dropped || typeof s.dropped !== 'object') s.dropped = {};
    if (v) { const back = Array.isArray(s.dropped[id]) ? s.dropped[id] : []; delete s.dropped[id]; return withDeps([...(cur || []), id, ...back], cs); }
    const after = withoutDependents(cur, id, cs);
    const lost = (cur || []).filter(x => x !== id && !after.includes(x));
    if (lost.length) s.dropped[id] = lost; else delete s.dropped[id];
    return after;
  }

  // 功能清单（`setup plan`）是「装没装」的唯一来源。1103：强制刷新不复用进行中的旧查询（那份可能是装之前发的）；
  // 读完通知所有显示点重画（概览「这台电脑」、设置④「现在」那几行、页顶提示——都挂在 painters 上），并让 AI 用量缓存失效。
  async function loadPlan(force = false) {
    const st = S();
    if (st.plan && !force) return st.plan;
    if (st.planLoading) {
      if (!force) return st.planLoading;
      try { await st.planLoading; } catch {}
    }
    st.planLoading = (async () => {
      try {
        const { json } = await plugin.runPy(['-m', 'link_brain', 'setup', 'plan'], { label: '读取功能清单', fallback: '读不到功能清单', timeoutMs: 60000, okCodes: [0, 1, 2] });
        if (!json || !Array.isArray(json.components)) throw new Error((json && json.message) || '后台没返回功能清单');
        st.plan = json; st.planError = null;
      } catch (e) { st.planError = e; }
      finally { st.planLoading = null; }
      if (plugin.v6Cache) delete plugin.v6Cache.usage;
      repaint();
      return st.plan;
    })();
    return st.planLoading;
  }
  async function loadEstimate(force = false) {
    const st = S();
    if (st.estimate && !st.estimate.error && !force) return st.estimate;
    if (st.estimateLoading) return st.estimateLoading;
    st.estimateLoading = (async () => {
      try {
        const { json } = await plugin.runPy(['-m', 'link_brain', 'setup', 'estimate', '--posts', '100'], { label: '估算价格', timeoutMs: 120000, okCodes: [0, 1, 2] });
        st.estimate = json && json.ok !== false ? { data: json } : { error: (json && json.message) || '估不出价格' };
      } catch (e) { st.estimate = { error: errText(e) }; }
      finally { st.estimateLoading = null; }
      return st.estimate;
    })();
    return st.estimateLoading;
  }

  // —— 一键装好 / 跑完 ——（exclusive：占「正在跑」的互斥位，底部状态栏可停）
  let painters = new Set();
  const repaint = () => { for (const p of painters) { try { p(); } catch (e) { console.error('[lb] 设置页没重画上', e); } } };
  async function runAll({ quiet = false } = {}) {
    const st = S();
    if (plugin.running) { plugin.notify(plugin.busyText(), { kind: 'warn' }); return null; }
    // 1103：重启 Obsidian 后接上的那一轮还在后台跑（plugin.running 是空的）——不再起第二轮
    if (resumedRunning()) { plugin.notify('上次启动的懒人安装还在后台跑，进度在设置页「懒人安装」；跑完再点', { kind: 'warn' }); return null; }
    // 1102：还没有后端（新电脑）→ 先自己装（uv → Python → link-brain），装不上就把原因留在这一块，不往下跑
    if (backendMissing()) {
      const got = await installBackend({ quiet });
      if (!got || !got.ok) return got;
    }
    if (!Array.isArray(setup().selected)) setup().selected = selected();
    setup().runVault = plugin.vaultDir || '';   // 1103：这一轮写到哪（收藏位置本轮钉死；改了下一轮生效，续画按它读）
    await save();
    st.run = { state: 'running', stages: {}, current: null, install: null, result: null, startedAt: Date.now() };
    repaint();
    let lineFrame = null;
    const r = await plugin.spawnPy(['-m', 'link_brain', 'setup', 'run'], {
      exclusive: true, label: '装好并跑完', timeoutMs: 6 * 3600000,
      onChild: ch => { st.child = ch; },
      onLine: line => {
        let ev; try { ev = JSON.parse(line); } catch { return; }
        applyRunEvent(st.run, ev);
        // 1103：装完一项 / 装组件那一步结束 → 马上重读功能清单（各处「装没装」跟着变），不等整轮几小时跑完
        if (ev.stage === 'install' && (ev.state === 'ok' || ev.state === 'failed')) loadPlan(true).catch(() => {});
        const sg = ev.stage && st.run.stages[ev.stage];
        if (sg && sg.state === 'running') { plugin.runningProgress = sg.label || ''; plugin.taskChanged?.(); }
        if (lineFrame == null) lineFrame = setTimeout(() => { lineFrame = null; repaint(); }, 120);
      },
    });
    st.child = null;
    if (!st.run.result) {
      if (r.json && r.json.type === 'result') st.run.result = r.json;
      else if (r.timedOut) st.run.result = { ok: false, message: '超过 6 小时没跑完，已停止；做了的都存好了' };
      else if (r.code === 6 && r.busy) st.run.result = { ok: false, message: plugin.busyText() };
      else {
        // 1102（CONVENTIONS §1.7）：没有 result JSON 不把 stderr（多半是 traceback）弹给人——一句话 + 「打开日志」，stderr 尾巴折进「详情」
        const tail = String(r.err || '').trim().split('\n').slice(-12).join('\n');
        st.run.result = { ok: false, code: 'TRANSIENT.STEP_CRASHED', message: NO_RESULT_TEXT, noResult: true, exit: r.code,
          detail: (tail ? tail + '\n' : '') + '日志：<收藏库>/_archive/ob-actions.log；后台进度：~/.link-brain/logs/setup-run.log' };
        try { await plugin.log?.(`[一键装好 / 跑完] exit=${r.code} 没有返回结果\n${String(r.all || r.err || '').trim()}`); } catch (e) { console.error('[lb] 日志没写上', e); }
      }
    }
    st.run.state = 'done';
    repaint();
    const res = st.run.result;
    if (!quiet) {
      const kind = resultKind(res.code);
      const actions = kind === 'account' ? [{ label: '去扫码 / 验证', run: () => plugin.openSetupPage?.('status') }]
        : kind === 'reader' ? [{ label: '重试', run: () => runAll() }]
        : res.noResult ? [{ label: '打开日志', run: () => plugin.openActionLog?.() }] : null;
      plugin.notify(res.message || (res.ok ? '都跑完了' : '没跑完'), { kind: res.ok ? 'ok' : kind ? 'warn' : 'error', ms: kind ? 0 : undefined, actions });
    }
    loadPlan(true).catch(() => {});
    // 1103：这一轮跑的时候才扫了码（同步那步跳过了）→ 接着再跑一轮，这次会同步
    if (st.syncAfterRun) { st.syncAfterRun = false; setTimeout(() => runAll({ quiet }).catch(e => console.error('[lb] 登录后接着同步没起来', e)), 1500); }
    return res;
  }
  const resumedRunning = () => { const r = S().run; return !!(r && r.resumed && r.state === 'running'); };
  // —— 1102：Obsidian 关掉时安装没停（onunload 不杀子进程），进度在 _archive/setup-run.json ——
  // 打开设置页 / 启动时：文件说 running 且 pid 活着 → 续画（盯文件 + 每 3 秒再读一次，直到 result 出来或 pid 死了）；
  // 死了又没 result → 「上次没跑完，停在 X 步」+「再跑一次」。本会话自己在跑（st.run 已有）就不碰。
  // 1103：上一轮写在哪个收藏位置就去哪读（用户中途改了位置是下一轮生效，上一轮的进度文件还在旧位置）
  async function readRunState() {
    try {
      const rv = setup().runVault;
      let raw;
      if (rv && plugin.vaultDir && rv !== plugin.vaultDir) raw = require('fs').readFileSync(require('path').join(rv, '_archive', 'setup-run.json'), 'utf8');
      else raw = await plugin.app.vault.adapter.read(plugin.lbPath(RUN_STATE_FILE));
      const v = JSON.parse(raw);
      return v && typeof v === 'object' ? v : null;
    } catch { return null; }
  }
  const alive = pid => (typeof plugin.pidAlive === 'function' ? !!plugin.pidAlive(pid) : false);
  async function resumeRun() {
    const st = S();
    if (st.run || plugin.running) return st.run || null;
    const state = await readRunState();
    if (!state || (!state.running && !st.resumeWatching)) return null;   // 跑完了的旧结果不重放；只接「还在跑」或「没跑完」
    if (st.run) return st.run;
    const run = runFromState(state, alive(state.pid));
    if (!run) return null;
    st.run = run;
    repaint();
    plugin.taskChanged?.();
    if (run.state === 'running') watchResumed();
    return run;
  }
  function watchResumed() {
    const st = S();
    if (st.resumeWatching) return;
    st.resumeWatching = true;
    const stop = () => {
      st.resumeWatching = false; clearInterval(st.resumeTimer); st.resumeTimer = null;
      for (const r of refs) { try { vault.offref(r); } catch {} }
    };
    const tick = async () => {
      const run = st.run;
      if (!run || !run.resumed || run.state !== 'running') { stop(); return; }
      const state = await readRunState();
      const next = runFromState(state, state ? alive(state.pid) : false);
      if (!next) return;
      next.resumed = true;
      st.run = next;
      plugin.taskChanged?.();   // 1103：状态栏也显示接上的这一轮
      if (next.state === 'done') {
        stop();
        if (st.syncAfterRun) { st.syncAfterRun = false; setTimeout(() => runAll().catch(e => console.error('[lb] 登录后接着同步没起来', e)), 1500); }
        const res = next.result;
        plugin.notify(res.message || (res.ok ? '都跑完了' : '没跑完'), { kind: res.ok ? 'ok' : res.interrupted ? 'warn' : 'error',
          actions: res.interrupted ? [{ label: '再跑一次', run: () => runAll() }] : null });
        loadPlan(true).catch(() => {});
      }
      repaint();
    };
    const vault = plugin.app.vault;
    let refs = [];
    if (vault && typeof vault.on === 'function') {
      const watched = plugin.lbPath(RUN_STATE_FILE);
      refs = ['modify', 'create'].map(ev => vault.on(ev, f => { if (f?.path === watched) tick(); }));
    }
    st.resumeTimer = setInterval(tick, 3000);
  }
  async function stopRun() { await plugin.stopRunning?.(); }

  // —— 1102 托管模式：没找到后端 → 插件自己装（backend-install.js ensureBackend：uv → Python 3.12 → venv → link-brain → 自检）——
  //    进度就画在「懒人安装」这一块（renderRun 的 paintRun 读 S().backendRun）；装好后 loadPlan 重读这台电脑。upgrade=true 是「更新后端」。
  async function installBackend({ upgrade = false, quiet = false } = {}) {
    const st = S();
    if (st.backendRun && st.backendRun.state === 'running') { plugin.notify('正在装后端，装完再点', { kind: 'warn' }); return null; }
    if (plugin.running) { plugin.notify(plugin.busyText(), { kind: 'warn' }); return null; }
    st.backendRun = { state: 'running', upgrade, stages: {}, result: null, startedAt: Date.now() };
    repaint();
    let frame = null;
    let res;
    try {
      res = await plugin.backendInstall().ensureBackend(plugin, { upgrade, onProgress: ev => {
        st.backendRun.stages[ev.stage] = ev;
        plugin.runningProgress = (ev.label || '') + (ev.text ? '：' + ev.text : '');
        plugin.taskChanged?.();
        if (frame == null) frame = setTimeout(() => { frame = null; repaint(); }, 120);
      } });
    } catch (e) { res = { ok: false, code: 'PERMANENT.BAD_PACKAGE', message: '安装后端时出错：' + (e && e.message || e) }; }
    plugin.runningProgress = ''; plugin.taskChanged?.();
    st.backendRun.result = res; st.backendRun.state = 'done';
    repaint();
    if (!quiet) plugin.notify(res.message || (res.ok ? '后端装好了' : '后端没装上'), { kind: res.ok ? 'ok' : 'error', ms: res.ok ? 6000 : 12000,
      actions: res.ok ? null : [{ label: '打开设置', run: () => plugin.openSetupPage?.() }] });
    if (res.ok) { st.plan = null; st.planError = null; loadPlan(true).catch(() => {}); if (st.asrPending) installAsr(); }
    return res;
  }
  const backendMissing = () => { try { return plugin.currentBackend?.().mode === 'missing'; } catch { return false; } };

  // —— 首次（零配置）：新装、库里还没有收藏 → 按轻量版自动跑一次 ——
  async function firstRun() {
    const s = setup();
    // 1102：启动时接上关 Obsidian 前没跑完的那一轮。1103：先等它判定完——还在后台跑就不再起新的一轮
    try { await resumeRun(); } catch (e) { console.error('[lb] 上次的安装进度没读到', e); }
    if (resumedRunning()) return 'resumed';
    if (s.firstRunAt) return 'done-before';
    s.firstRunAt = new Date().toISOString();
    let fresh = true;
    try { fresh = !(await plugin.app.vault.adapter.exists(plugin.lbPath('_archive/catalog-data.json'))); } catch { fresh = true; }
    if (!fresh) { await save(); return 'existing-library'; }   // 老库（作者本机）：只记一笔，选择不动
    if (!Array.isArray(s.selected)) s.selected = [...LIGHT];
    await save();
    // 1103 作者：全自动、不要「开始」——直接把人带到「懒人安装」卡片（上面能边跑边改选项，下面是进度）；已经开着就不重画（别冲掉正在填的）
    try { if (!(plugin.app?.setting?.activeTab && plugin.app.setting.activeTab === plugin.settingTab)) plugin.openSetupPage?.(); }
    catch (e) { console.error('[lb] 设置页没打开', e); }
    plugin.notify('Link Brain 正在自动安装并同步：进度在设置页「懒人安装」，上面的选项随时能改。', { ms: 12000,
      actions: [{ label: '看进度', run: () => plugin.openSetupPage?.() }] });
    runAll().catch(e => console.error('[lb] 首次自动跑没跑完', e));
    return 'started';
  }

  // —— 小积木：次要按钮（像链接）、「?」、这一块读不到 ——
  // 次要动作一律用它（每栏最多一个主按钮）：样子是一行字的链接，title 写清点了会发生什么
  function linkButton(row, text, onClick, title = '') {
    let el = null;
    row.addButton(b => {
      b.setButtonText(text).onClick(onClick);
      el = b.buttonEl || null;
      el?.addClass?.('lb-link');
      if (title) el?.setAttribute?.('aria-label', title);
    });
    return el;
  }
  // 「?」悬停：只讲规则是什么（设置页那一格自己画；单测里的假设置页没有就不画）
  const help = (tab, row, text) => (tab && typeof tab.help === 'function' ? tab.help(row, text) : null);
  // 开关改了立刻存；存失败拨回原值并提示一句。Obsidian 1.14 的 ToggleComponent.setValue 会再触发 onChange——拨回时挡一下，别来回弹
  function bindToggle(t, value, apply) {
    let reverting = false;
    t.setValue(value).onChange(async v => {
      if (reverting) return;
      try { await apply(v); }
      catch (e) {
        reverting = true;
        try { t.setValue(!v); } catch {} finally { reverting = false; }
        plugin.notify('没保存上，开关已拨回原来的位置：' + errText(e), { kind: 'error' });
      }
    });
    return t;
  }
  function failBox(container, what, err, retry) {
    if (typeof plugin.failBox === 'function') return plugin.failBox(container, what, err, retry);
    const box = container.createDiv({ cls: 'lb-setup-error' });
    box.createEl('p', { text: (what ? what + '：' : '') + '这一块暂时读不到，点重试' });
    if (retry) box.createEl('button', { text: '重试' }).onclick = retry;
    return box;
  }

  // —— 画：概览 · 状态（账号 · 收藏同步 · 评论补齐 · 问题 · 这台电脑）——
  // machineOnly（1018 设置页 v6「更多 → 这台电脑」）：账号和收藏同步已经在最上面的状态卡里，这里只画评论补齐 · 问题 · 这台电脑
  // noProblems（1027 设置页⑥）：「问题记录」那一行由⑥自己画（入口只留一处），这里不再画
  function renderStatus(c, tab, { machineOnly = false, noProblems = false } = {}) {
    const box = c.createDiv({ cls: 'lb-home-status', attr: { 'data-section': machineOnly ? 'machine' : 'status' } });
    const stops = [];
    if (!machineOnly) {
      try { plugin.renderAccounts(box); } catch (e) { failBox(box, '小红书账号', e, () => tab?.display?.()); }
      try { stops.push(plugin.renderSyncRow(box, { compact: true, onSchedule: () => tab?.showTab?.('schedule') })); }
      catch (e) { console.error('[lb] 同步那一行没画上', e); failBox(box, '收藏同步', e, () => tab?.display?.()); }
    }
    const fill = new Setting(box).setName('评论补齐').setDesc('读取中…');
    fill.settingEl.addClass('lb-fill-row');
    let fillBtn = null;
    fillBtn = linkButton(fill, '现在补', async () => {
      if (fillBtn) fillBtn.disabled = true;
      const r = await plugin.ensureCommentFill('settings');
      if (fillBtn) fillBtn.disabled = false;
      plugin.notify((r && r.message) || '后台补评论已经在跑', { kind: 'ok' });
      paintFill();
    }, '在后台接着补没读全的评论（不用等夜里）');
    const probs = noProblems ? null : new Setting(box).setName('问题').setDesc('');
    if (probs) {
      probs.settingEl.addClass('lb-probs-row');
      linkButton(probs, '打开问题列表', () => plugin.openProblems(), '看哪些地方没做成、系统已经做了什么');
    }
    const machine = new Setting(box).setName('这台电脑').setDesc('读取中…');
    machine.settingEl.addClass('lb-machine-row');
    help(tab, machine, '打开了的功能各自装好没有。没装好的，点下面「一键装好 / 跑完」会自动装。');
    const machineErr = box.createDiv({ cls: 'lb-machine-err' });
    let alive = true;
    const paintFill = async () => {
      const { sum, fill: st } = await plugin.readSyncFiles();
      if (!alive) return;
      const line = fillLine(st, S().fillInfo);
      fill.setDesc(line || '读取中…');
      const live = st && ['running', 'waiting', 'paused'].includes(st.state) && Date.now() - Date.parse(st.updated_at || '') < fillStaleMs(st);
      fillBtn?.toggleClass?.('is-hidden', !!live || !(S().fillInfo?.pending > 0));
      const n = sum ? (num(sum.needs_human) || 0) : 0, auto = sum ? (num(sum.auto) || 0) + (num(sum.gave_up) || 0) : 0;
      if (probs) probs.setDesc(!sum ? '还没有问题记录' : n ? `⚠ ${n} 件要你处理` + (auto ? ` · 另有 ${auto} 条在自动处理 / 已放弃` : '')
        : auto ? `${auto} 条在自动处理 / 已放弃，不用管` : '没有问题');
    };
    const paintMachine = () => {
      machineErr.empty?.();
      const st = S();
      if (!st.plan) {
        if (st.planError) {
          machine.setDesc('');
          const fb = failBox(machineErr, '这台电脑', st.planError, () => { st.planError = null; paintMachine(); loadPlan(true).then(() => alive && repaint()); });
          if (st.planError.backendMissing && fb) {
            const b = fb.createEl('button', { cls: 'lb-link', text: '复制安装命令' });
            b.onclick = () => plugin.copyText('uv tool install link-brain');
          }
        } else machine.setDesc('读取中…');
        return;
      }
      const sel = new Set(effective());
      const bits = [];
      for (const comp of comps()) {
        if (comp.later || comp.needs_key || !sel.has(comp.id)) continue;
        const status = (st.run && st.run.installed && st.run.installed[comp.id]) || comp.status;
        const label = (FEATURE_TEXT[comp.id] || {}).short || comp.name || comp.id;
        bits.push(status === 'ready' ? '✓ ' + label : `⚠ ${label}${STATUS_TEXT[status] ? '（' + STATUS_TEXT[status] + '）' : ''}`);
      }
      const t = totals([...sel], comps());
      machine.setDesc(bits.join(' · ') + (t.disk ? `　共占磁盘约 ${fmtMB(t.disk)}` : ''));
    };
    painters.add(paintMachine);
    paintFill();
    paintMachine();
    if (!S().plan) loadPlan().then(() => { if (alive) repaint(); });
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
      alive = false; clearTimeout(timer); painters.delete(paintMachine);
      for (const r of refs) { try { vault.offref(r); } catch {} }
      for (const s of stops) { try { s && s(); } catch {} }
    };
  }

  // —— 画：概览 · 一键装好 / 跑完（这一栏唯一的主按钮）+ 进度 ——
  // brief（设置页顶的懒人安装卡片）：结果只留一句 + 「详情在 06 修复」；完整的结果 / 没成的几步由 renderRunDetails 画在修复区
  function renderRun(c, tab, { brief = false, onDetails = null } = {}) {
    const runBox = c.createDiv({ cls: 'lb-run', attr: { 'data-section': 'run' } });
    let alive = true;
    const paintRun = () => {
      if (!alive) return;
      runBox.empty();
      const st = S(), run = st.run;
      const acts = runBox.createDiv({ cls: 'lb-run-actions' });
      const busy = !!(run && run.state === 'running');
      const br = st.backendRun, installing = !!(br && br.state === 'running');
      const missing = backendMissing();
      if (busy && run.resumed) acts.createEl('span', { cls: 'setting-item-description', text: '上次关 Obsidian 前启动的安装还在后台跑，这里停不了；进度照文件续画' });
      else if (busy) acts.createEl('button', { cls: 'lb-run-stop', text: '停止（做了的都留着）' }).onclick = () => stopRun();
      else if (missing || installing) {
        // 1102：还没有后端（新电脑，可能连 Python 都没有）→ 这个主按钮先管「一键装好」：自己下载 uv / Python / link-brain
        const go = acts.createEl('button', { cls: 'lb-run-go lb-run-install mod-cta', text: installing ? '正在装后端…' : '一键装好' });
        go.disabled = installing;
        go.onclick = () => installBackend();
        acts.createEl('span', { cls: 'setting-item-description', text: installing ? '正在下载并安装后端程序（uv · Python 3.12 · link-brain），进度在下面。'
          : '这台电脑还没有后端程序：点一下自动装到 ~/.link-brain（没有 Python 也行，约 100 MB）。装好后这里变成「一键装好 / 跑完」。' });
      } else {
        const again = !!(run && run.result && run.result.interrupted);
        const go = acts.createEl('button', { cls: 'lb-run-go mod-cta', text: again ? '再跑一次' : '一键装好 / 跑完' });
        // 按钮不能点时，旁边一句为什么
        const why = plugin.running ? plugin.busyText() : st.planError ? '读不到这台电脑装了什么：上面「这台电脑」那一行点重试' : !st.plan ? '正在看这台电脑装了什么…' : '';
        go.disabled = !!why;
        go.onclick = () => runAll();
        acts.createEl('span', { cls: 'setting-item-description' + (why ? ' lb-why' : ''),
          text: why || (brief ? '装好上面勾的，再把同步、认字、整理目录一口气跑完。'
            : '装好打开的功能，再把同步小红书收藏、认图片里的字、概要、整理目录一口气跑完（没开 AI 就只跑免费的部分）。B 站视频占地方，不在这里下：到「收藏与同步 → B 站」手动同步。') });
      }
      // 装后端的五步（uv → Python → 环境 → link-brain → 自检）：跑的时候逐步画 ✓ / ⟳ / ✗ + 下载进度条；完了只留一句结果
      if (br && (installing || (br.result && !run))) {
        const steps = runBox.createDiv({ cls: 'lb-run-steps lb-backend-steps' });
        if (installing) for (const sg of Object.values(br.stages)) {
          const rowEl = steps.createDiv({ cls: 'lb-run-step is-' + (sg.state || 'running') });
          rowEl.createSpan({ cls: 'lb-run-mark', text: STAGE_MARK[sg.state] || '○' });
          rowEl.createSpan({ cls: 'lb-run-label', text: sg.label || sg.stage || '' });
          if (sg.text) rowEl.createSpan({ cls: 'lb-run-text', text: sg.text });
        }
        // 1103：只有拿得到字节总数的下载（uv、link-brain wheel）画百分比；其余（装依赖、装 Python）画不定进度条，不编百分比
        const cur = installing ? Object.values(br.stages).find(sg => sg.state === 'running') : null;
        if (cur) {
          const pv = cur.total ? progressView(cur) : null;
          const bar = runBox.createDiv({ cls: 'lb-bar' + (pv && pv.pct != null ? '' : ' is-indeterminate') });
          const fill = bar.createDiv({ cls: 'lb-bar-fill' });
          if (pv && pv.pct != null) fill.style.width = pv.pct + '%';
        }
        if (br.result) runBox.createDiv({ cls: 'lb-run-result' + (br.result.ok ? ' is-done' : ' is-failed'), text: br.result.message || '' });
      }
      if (!run) return;
      // 1027b 作者：跑完了只留一句结果——每一步的 ✓ / ✗（比如没开的 CapsLock）不影响用，不再摆出来；跑的时候照旧一步步显示
      if (busy) {
      const steps = runBox.createDiv({ cls: 'lb-run-steps' });
      const order = Object.values(run.stages).sort((a, b) => (a.index || 0) - (b.index || 0));
      for (const sg of order) {
        const row = steps.createDiv({ cls: 'lb-run-step is-' + (sg.state || 'running') });
        row.createSpan({ cls: 'lb-run-mark', text: STAGE_MARK[sg.state] || '○' });
        row.createSpan({ cls: 'lb-run-label', text: sg.label || '' });
        // 1103：同步那一步不显示子进程的日志尾巴，改用同步状态文件的篇数（和设置页同步那一行、状态栏同一份）
        const text = sg === run.stages.sync && sg.state === 'running' && st.syncLine ? st.syncLine : sg.text;
        if (text) row.createSpan({ cls: 'lb-run-text', text });
      }
      }
      // 1103：视频说话转文字（约 2 GB）勾上后单独在后台下载，进度也画在这一张卡片上
      const ar = st.asrRun;
      if (ar && (ar.state === 'running' || ar.result)) {
        const line = runBox.createDiv({ cls: 'lb-run-asr setting-item-description' });
        if (ar.state === 'running') {
          const pv = ar.ev ? progressView(ar.ev) : null;
          line.setText('视频说话转文字：' + (pv ? pv.text : '准备下载…'));
          const bar = runBox.createDiv({ cls: 'lb-bar' + (pv && pv.pct != null ? '' : ' is-indeterminate') });
          const fill = bar.createDiv({ cls: 'lb-bar-fill' });
          if (pv && pv.pct != null) fill.style.width = pv.pct + '%';
        } else line.setText('视频说话转文字：' + (ar.result.ok ? '装好了' : (ar.result.message || '没装上')));
      }
      if (busy && run.install) {
        const pv = progressView(run.install);
        const bar = runBox.createDiv({ cls: 'lb-bar' + (pv && pv.pct != null ? '' : ' is-indeterminate') });
        const fill = bar.createDiv({ cls: 'lb-bar-fill' });
        if (pv && pv.pct != null) fill.style.width = pv.pct + '%';
        const label = (FEATURE_TEXT[run.install.component] || {}).name || run.install.component || '';
        runBox.createDiv({ cls: 'setting-item-description', text: '正在装 ' + label + '：' + (pv ? pv.text : '') });
      }
      if (brief && run.result) {
        // 1103 作者：卡片上只留一句结果；哪几步没成、要你做什么，在「06 修复」（和那里的「当前状态」同一份）
        const line = runBox.createDiv({ cls: 'lb-run-result' + (run.result.ok ? ' is-done' : ' is-failed'), text: briefResult(run.result) });
        if (!run.result.ok && onDetails) line.createEl('button', { cls: 'lb-link', text: '详情在「06 修复」' }).onclick = () => onDetails();
      } else if (run.result && run.result.noResult) failBox(runBox, '一键装好 / 跑完', { message: run.result.detail || '' }, () => runAll()).createEl('button', { cls: 'lb-link', text: '打开日志' }).onclick = () => plugin.openActionLog?.();
      else if (run.result) runBox.createDiv({ cls: 'lb-run-result' + (run.result.ok ? ' is-done' : ' is-failed'), text: run.result.message || '' });
    };
    painters.add(paintRun);
    paintRun();
    if (!S().plan && !backendMissing()) loadPlan().catch(() => {});   // 没后端时 setup plan 起不来，不白跑一趟
    if (!S().run && !backendMissing()) resumeRun().catch(e => console.error('[lb] 上次的安装进度没读到', e));   // 1102：打开设置页时接上后台那一轮
    // 1103：同步那一行跟着同步状态文件走（文件一变就重读、重画），说法和设置页同步那一行一致
    const paintSync = async () => {
      try {
        const line = plugin.syncProgressText ? plugin.syncProgressText(await plugin.readSyncStatus()) : '';
        if (line !== S().syncLine) { S().syncLine = line; if (alive) paintRun(); }
      } catch {}
    };
    const vault = plugin.app.vault;
    let refs = [];
    if (vault && typeof vault.on === 'function' && typeof plugin.readSyncStatus === 'function') {
      const watched = plugin.lbPath('_archive/sync-status.json');
      refs = ['modify', 'create'].map(ev => vault.on(ev, f => { if (f?.path === watched) paintSync(); }));
      paintSync();
    }
    return () => { alive = false; painters.delete(paintRun); for (const r of refs) { try { vault.offref(r); } catch {} } };
  }

  // 1103：修复区「上次一键装好 / 跑完」——完整结果 + 没成的几步（卡片上只有一句，详情只在这里，一处说清）
  function renderRunDetails(c) {
    const box = c.createDiv({ cls: 'lb-run-details', attr: { 'data-section': 'run-details' } });
    const paint = () => {
      box.empty();
      const run = S().run, r = run && run.result;
      if (!r) { box.createDiv({ cls: 'setting-item-description', text: run && run.state === 'running' ? '正在跑：进度在页顶「懒人安装」' : '还没跑过' }); return; }
      box.createDiv({ cls: 'lb-run-result' + (r.ok ? ' is-done' : ' is-failed'), text: r.message || r.detail || briefResult(r) });
      for (const sg of (r.stages || []).filter(x => x && x.state === 'failed')) box.createDiv({ cls: 'setting-item-description is-warn', text: `✗ ${sg.label || sg.id}：${sg.text || ''}` });
      if (r.noResult) box.createEl('button', { cls: 'lb-link', text: '打开日志' }).onclick = () => plugin.openActionLog?.();
    };
    painters.add(paint);
    paint();
    return () => painters.delete(paint);
  }

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
      if (caps && !ok) plugin.notify('按住 CapsLock 说话要先装好语音识别：到「更多 → 高级」点「一键装好 / 跑完」', { kind: 'warn' });
    }
  };
  const RUNTIME_KEYS = ['setup', 'ocr', 'asrAI', 'textAI', 'visionAI', 'voice'];
  const snapRuntime = () => JSON.parse(JSON.stringify(Object.fromEntries(RUNTIME_KEYS.map(k => [k, plugin.settings[k]]))));
  // 1018：几把 key 轮流用（keyPool，key 在别处的文件里）也算填好了——以前识图走 Gemini 池时一直挂「还要填密钥」
  const aiReady = id => {
    const cfg = plugin.settings[AI_CAP[id]] || {};
    return cfg.mode === 'cli' ? !!(cfg.command || cfg.preset) : cfg.mode === 'http' ? !!(cfg.endpoint && cfg.model && (cfg.apiKey || cfg.keyFile || cfg.apiKeyEnv || cfg.keyPool)) : false;
  };

  // 1018 AI 页重排：功能表每一行自己的开关（依赖一起开、关掉把依赖它的也关、实际起作用的设置跟着对上）
  // 功能清单还没读回时 effective() 是空的（会画成「关」）：先读清单，再悄悄把开关拨到实际值——不触发保存
  function featureToggle(row, id, after) {
    const on = () => new Set(effective()).has(id);
    let quiet = false;
    row.addToggle(t => {
      if (!S().plan) loadPlan().then(() => {
        const want = on();
        if (t.getValue() !== want) { quiet = true; try { t.setValue(want); } finally { quiet = false; } }
      }).catch(e => console.error('[lb] 功能清单没读到', e));
      return bindToggle(t, on(), async v => {
      if (quiet) return;
      if (!S().plan) await loadPlan();
      const cs = comps();
      if (!cs.some(x => x.id === id)) throw new Error('功能清单里没有「' + id + '」');
      const snap = snapRuntime();
      setup().selected = nextSelection(effective(), id, v, cs);
      setup().aiSynced = true;   // 1027：用户在设置页点过 = 选择已经对齐（插件下次启动不再按「配好了 key」替用户勾回去）
      try { await applyRuntime(new Set(setup().selected)); await plugin.saveSettings(); }
      catch (e) { for (const k of RUNTIME_KEYS) plugin.settings[k] = snap[k]; throw e; }
      finally { repaint(); if (after) after(); }
      });
    });
    return on;
  }

  // 1018 设置页 v6：不经开关直接开 / 关一项（粘了 key 自动打开对应功能、「一键推荐」）；规则同 featureToggle（依赖一起开、关掉把依赖它的也关）
  async function setFeature(id, v) {
    if (!S().plan) await loadPlan();
    const cs = comps();
    if (!cs.some(x => x.id === id)) throw new Error('功能清单里没有「' + id + '」');
    if (new Set(effective()).has(id) === !!v) return;
    const snap = snapRuntime();
    setup().selected = nextSelection(effective(), id, v, cs);
    setup().aiSynced = true;
    try { await applyRuntime(new Set(setup().selected)); await plugin.saveSettings(); }
    catch (e) { for (const k of RUNTIME_KEYS) plugin.settings[k] = snap[k]; throw e; }
    finally { repaint(); }
  }
  // 「一键推荐」：一次换成推荐那一组（没有能用的 key 就先不勾要 key 的）
  async function applyPreset(name = 'recommended') {
    if (!S().plan) await loadPlan();
    const cs = comps();
    const want = ((S().plan && S().plan.presets && S().plan.presets[name]) || LIGHT).filter(id => !AI_CAP[id] || aiReady(id));
    const snap = snapRuntime();
    setup().selected = withDeps(want, cs);
    try { await applyRuntime(new Set(setup().selected)); await plugin.saveSettings(); }
    catch (e) { for (const k of RUNTIME_KEYS) plugin.settings[k] = snap[k]; throw e; }
    finally { repaint(); }
  }
  const isOn = id => new Set(effective()).has(id);

  // —— 1103：懒人安装卡片上的选择 ——
  // 没后端 / 功能清单还没读回时也能存（不走依赖 plan 的 featureToggle）；setup run 每一步开始时现读 setup.selected。
  const choiceOn = id => { const sel = setup().selected; return Array.isArray(sel) ? sel.includes(id) : LIGHT.includes(id); };
  const asrReady = () => { const c = comps().find(x => x.id === 'asr'); return !!(c && c.status === 'ready'); };
  async function setChoice(id, on) {
    const s = setup();
    const before = Array.isArray(s.selected) ? [...s.selected] : null;
    const cur = before || [...LIGHT];
    // 关掉认字顺带关识图、关掉语音转文字顺带关 CapsLock（它们靠前者）
    const deps = { ocr: ['ai_vision'], asr: ['capslock'] }[id] || [];
    s.selected = on ? [...new Set([...cur, id])] : cur.filter(x => x !== id && !deps.includes(x));
    const snap = snapRuntime();
    const ps = plugin.settings;
    if (id === 'ocr' && ps.ocr) ps.ocr.mode = on ? (ps.ocr.mode && ps.ocr.mode !== 'off' ? ps.ocr.mode : 'local') : 'off';
    if (id === 'asr' && ps.asrAI) { if (!on && ps.asrAI.mode === 'capswriter') ps.asrAI.mode = 'off'; if (on && asrReady()) ps.asrAI.mode = 'capswriter'; }
    try { await plugin.saveSettings(); }
    catch (e) { for (const k of RUNTIME_KEYS) ps[k] = snap[k]; if (before) s.selected = before; else delete s.selected; throw e; }
    repaint();
    // 视频说话转文字（约 2 GB）不进自动安装：勾上（存成功之后）且还没装 → 后台单独下载，不占「正在跑」、不挡别的
    if (id === 'asr' && on && !asrReady()) installAsr();
  }
  // 后端还没装好时先记着，装好后再下（installBackend 成功时接上）
  function installAsr() {
    const st = S();
    if (st.asrRun && st.asrRun.state === 'running') return st.asrRun.promise;
    if (backendMissing()) { st.asrPending = true; repaint(); return Promise.resolve(null); }
    st.asrPending = false;
    st.asrRun = { state: 'running', ev: null, result: null };
    repaint();
    let frame = null;
    st.asrRun.promise = plugin.spawnPy(['-m', 'link_brain', 'setup', 'install', '--component', 'asr'], {
      label: '下载视频说话转文字', timeoutMs: 3 * 3600000,
      onLine: line => {
        let ev; try { ev = JSON.parse(line); } catch { return; }
        if (ev.type === 'result') st.asrRun.result = ev;
        else if (ev.type === 'progress') { st.asrRun.ev = ev; if (frame == null) frame = setTimeout(() => { frame = null; repaint(); }, 300); }
      },
    }).then(r => {
      const res = st.asrRun.result || (r.json && r.json.type === 'result' ? r.json : { ok: false, message: '视频说话转文字没装上，详情见日志' });
      st.asrRun.result = res; st.asrRun.state = 'done';
      // Python 已经把补丁写进 data.json；插件内存里也合一份，免得下次保存把它盖掉
      if (res.settings_patch) mergeInto(plugin.settings, res.settings_patch);
      plugin.notify(res.ok ? '视频说话转文字装好了' : (res.message || '视频说话转文字没装上'), { kind: res.ok ? 'ok' : 'error' });
      loadPlan(true).catch(() => {});
      repaint();
      return res;
    });
    return st.asrRun.promise;
  }
  function mergeInto(target, patch) {
    for (const [k, v] of Object.entries(patch || {})) {
      if (v && typeof v === 'object' && !Array.isArray(v) && target[k] && typeof target[k] === 'object') mergeInto(target[k], v);
      else target[k] = v;
    }
    return target;
  }
  // 设置页其它模块（设置④「现在」那几行、页顶提示）挂到同一个重画上：功能清单一刷新它们就跟着变
  function onRepaint(fn) { painters.add(fn); return () => painters.delete(fn); }

  return { renderStatus, renderRun, renderRunDetails, featureToggle, setFeature, applyPreset, isOn, aiReady, runAll, stopRun, firstRun, resumeRun, loadPlan, loadEstimate, state: S, bindToggle, installBackend,
    choiceOn, setChoice, installAsr, onRepaint, resumedRunning,
    _internals: { repaint, withDeps, withoutDependents, toggleSelection, initialSelection, totals, fmtMB, yuan, priceText, progressView, applyRunEvent, fillLine, resultKind, runFromState, briefResult } };
};
module.exports._internals = { briefResult, withDeps, withoutDependents, toggleSelection, initialSelection, totals, fmtMB, yuan, priceText, progressView, applyRunEvent, fillLine, resultKind, runFromState, LIGHT, FEATURE_TEXT, AI_ORDER, READER_CODES, NO_RESULT_TEXT, RUN_STATE_FILE };

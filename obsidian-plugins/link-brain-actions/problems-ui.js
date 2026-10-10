// problems-ui.js — 第 4 批：目录页顶部问题入口点开的「问题」窗口（CONVENTIONS §3.3，RELEASE-BAR P12）。
// main.js 只接两行：problemsUI() 按需 require 本文件；openProblems() { return this.problemsUI().open(); }
// 数据：python -m link_brain problems list → {ok, summary, problems:[{ts,key,step,item_id,title,code,reason,action,next_at,count,resolved_at,label,hover,group,
//        hidden,hidden_repeats,dismissable,verify_result,evidence_id,…}]}
//       python -m link_brain problems export --plugin-version X → {ok, text}（Python 已脱敏）
// 文案：每条的标签 / 原因（label / hover）全由 Python 登记表填好（problems.STATE_REGISTRY）；这里只有分组名、按钮名、系统动作的中文。
// 本模块不起进程：一律经 plugin.runPy（CONVENTIONS §1.4），失败如实提示。
// 10-04 当场自愈：每条非风控问题一个「现在修」（problems repair --key K），顶部「全部修一遍」（problems repair）；
//       状态一句话（status_text：正在修 / 预计 N 分钟、等到几点、要你看一眼…）和修不好的说明（repair_note）都由 Python 填好。
//       风控 / 登录类（等你处理组）保持原来的人工按钮，绝不自动处理。
// 1008（L6）：
//   B2 隐藏——「已放弃」的行有「隐藏」、组标题旁「全部隐藏（N）」（problems dismiss），列表底部默认收起的「已隐藏 · N」可「恢复显示」
//      （problems undismiss）；隐藏是她手动、可恢复、照样导出，不弹确认框。已放弃的行按钮叫「再试一次」。
//   C20 先画缓存、修完只换那一行——plugin.problemsCache 有就立刻按它画（标题旁「正在刷新…」），后台再读；签名没变只去掉
//      「正在刷新」，变了整体重画但保住滚动；「现在修」/ 人工按钮结束后只替换那一行（修好的标「✓ 已修好」、不删行免得跳动）。
//   B1 验证——关窗后熔断还在（verify_result）时多一个「没看到验证，恢复」（plugin.restoreHold，她亲手确认才发）；
//      出事时落了证据（evidence_id）的给「查看截图」（plugin.openRiskEvidence，直接打开本机文件，路径不出本机）。
//   X8「打开设置」直达 AI 分页（plugin.openSetupPage('ai')）。
// 1011（她：自愈的就不要显示报错）：已解决 / 轻微的（Python 标 minor：评论楼中楼只缺 ≤2 条）不进列表、不进组计数——只在「复制报错」里。
//   「现在修」修好的那一行先就地标「✓ 已修好」（点完那一刻不跳），停 RESOLVED_LINGER_MS 后从列表里拿掉（组空了连组标题一起拿掉）。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Modal, Notice } = obsidian;
  const GROUPS = [['needs_you', '等你处理'], ['auto', '正在自动处理'], ['gave_up', '已放弃'], ['off', '未开启']];
  const GROUP_OF_CLASS = { NEEDS_HUMAN: 'needs_you', TRANSIENT: 'auto', PERMANENT: 'gave_up', SKIPPED: 'off' };
  // 系统已经做了什么（problems.ACTIONS 词表）
  // 10-04：不再说「下晚再试」——非风控的问题都能当场修；要等的（限频 / 网页那侧拦了）由 Python 的 status_text 写清等到几点
  const ACTION_TEXT = { retrying: '正在修', retry_later: '待修复', gave_up: '已放弃', needs_human: '等你处理', skipped: '未开启' };
  // 「现在修」/「全部修一遍」等多久（后端默认预算：单条 20 分钟、全部 15 分钟；这里多给 2 分钟收尾）
  const REPAIR_ONE_MS = 22 * 60000, REPAIR_ALL_MS = 17 * 60000;
  // 要人处理的行带哪个按钮（按细分码，和 accounts.SOLUTIONS 的 action 对齐）
  const LOGIN = new Set(['NOT_LOGGED_IN', 'ACCOUNT_RISK', 'WRONG_ACCOUNT', 'RISK_HOLD']);
  const VERIFY = new Set(['CAPTCHA_REQUIRED', 'RISK_HOLD', 'ACCOUNT_RISK']);
  const ACCOUNT_PANEL = new Set(['NOT_INSTALLED', 'DISCONNECTED']);
  const AI_SETTINGS = new Set(['AUTH_FAILED', 'QUOTA_EXCEEDED']);
  // 验证窗口关了、熔断还在（读取组件 d7 的 verify_result）：才给「没看到验证，恢复」。cleared / owner_cleared = 已经好了
  const VERIFY_STILL_HELD = new Set(['no_captcha_seen', 'still_risk', 'not_read', 'window_failed', 'still_held']);

  const subOf = code => { const s = String(code || ''); const i = s.indexOf('.'); return i >= 0 ? s.slice(i + 1) : s; };
  const groupOf = r => (r && GROUPS.some(([g]) => g === r.group) ? r.group : GROUP_OF_CLASS[String(r?.code || '').split('.')[0]] || 'auto');
  const isHidden = r => !!(r && r.hidden);
  function shortTime(v) {
    const t = Date.parse(v || '');
    if (!Number.isFinite(t)) return '';
    const d = new Date(t), p = n => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  function actionText(r) {
    if (r.status_text) return r.status_text;
    const base = ACTION_TEXT[r.action] || '';
    const at = r.action === 'retry_later' || r.action === 'retrying' ? shortTime(r.next_at) : '';
    return at ? `${base}（${at}）` : base;
  }
  // 一行的签名：这些都没变 = 这一行看起来不变（C20：后台重读回来不必重画）
  const signature = r => [r.key, r.code, r.action, r.status_text, r.repair_state, r.repair_note, r.count, r.hidden, r.hidden_repeats,
    r.verify_result, r.evidence_id, r.repairing].map(v => v == null ? '' : String(v)).join('|');
  const listSignature = rows => (rows || []).map(signature).join('\n');
  const say = (msg, ms = 8000) => { try { new Notice(msg, ms); } catch {} };
  // 用户看得到的行：没解决、也不是轻微的（Python 的 problems list 已经滤过，这里再守一道，老后端 / 缓存也不漏）
  const visibleRow = x => !!x && !x.resolved_at && !x.minor;
  const openRows = j => (j && Array.isArray(j.problems) ? j.problems.filter(visibleRow) : []);
  const timing = { resolvedLingerMs: 2500 };

  // 「查看」：按 item_id 在目录数据里找那篇的笔记，同一窗格打开（和目录卡片点开一样）
  async function catalogItems() {
    const c = plugin.catalogCache;
    if (c && c.data && Array.isArray(c.data.items)) return c.data.items;
    const raw = await plugin.app.vault.adapter.read(plugin.lbPath('_archive/catalog-data.json'));
    return JSON.parse(raw).items || [];
  }
  async function openItem(itemId) {
    let items;
    try { items = await catalogItems(); } catch (e) { throw new Error('读不到目录数据：' + e.message); }
    const it = items.find(x => x && (x.id === itemId || x.item_id === itemId));
    if (!it || !it.note) throw new Error('库里找不到这一篇（可能已经删了）');
    await plugin.app.workspace.openLinkText(plugin.lbPath(it.note), '', false);
  }
  function openAISettings() {
    // X8：直达 AI 分页（openSetupPage 认分页名）；老插件没有它就退回打开插件设置
    if (typeof plugin.openSetupPage === 'function') return plugin.openSetupPage('ai');
    plugin.app.setting.open(); plugin.app.setting.openTabById(plugin.manifest.id);
  }

  // 这一行能直接修的按钮：[文字, 动作, cls]
  function fixesFor(r) {
    if (groupOf(r) !== 'needs_you') return [];
    const sub = subOf(r.code), out = [];
    if (LOGIN.has(sub)) out.push(['扫码登录', () => plugin.fixFromCatalog('login')]);
    if (VERIFY.has(sub)) out.push(['打开验证', () => plugin.fixFromCatalog('verify')]);
    if (VERIFY.has(sub) && VERIFY_STILL_HELD.has(String(r.verify_result || '')) && typeof plugin.restoreHold === 'function')
      out.push(['没看到验证，恢复', () => plugin.restoreHold(), 'lb-problem-restore']);
    if (ACCOUNT_PANEL.has(sub)) out.push(['账号与同步…', () => plugin.openAccountStatus()]);
    if (AI_SETTINGS.has(sub)) out.push(['打开设置', openAISettings]);
    return out;
  }

  async function copyReport() {
    let r;
    try {
      r = await plugin.runPy(['-m', 'link_brain', 'problems', 'export', '--plugin-version', String(plugin.manifest?.version || '?')],
        { label: '复制报错', fallback: '后台没生成诊断信息', timeoutMs: 60000 });
    } catch (e) { say('复制报错没成功：' + e.message, 10000); return false; }
    const j = r.json;
    if (!j || j.ok === false || typeof j.text !== 'string' || !j.text) { say('复制报错没成功：' + ((j && (j.message || j.error)) || '后台没生成诊断信息'), 10000); return false; }
    try { await navigator.clipboard.writeText(j.text); }
    catch (e) { say('复制报错没成功：剪贴板写不进去（' + (e && e.message || e) + '）', 10000); return false; }
    say('已复制诊断信息（已去掉密钥和本机路径）');
    return true;
  }

  async function fetchList() {
    const r = await plugin.runPy(['-m', 'link_brain', 'problems', 'list'], { label: '读取问题列表', fallback: '读不到问题列表', timeoutMs: 60000 });
    const j = r.json;
    if (!j || j.ok === false || !Array.isArray(j.problems)) throw new Error((j && (j.message || j.error)) || '后台没返回列表');
    plugin.problemsCache = { problems: j.problems, summary: j.summary || null, at: Date.now() };
    return j;
  }

  class ProblemsModal extends Modal {
    constructor() { super(plugin.app); this.loading = null; this.hiddenOpen = false; }
    onOpen() {
      this.modalEl?.addClass?.('lb-problems-modal');
      const c = this.contentEl;
      c.empty();
      const head = c.createDiv({ cls: 'lb-problems-head' });
      head.createEl('h2', { text: '问题' });
      this.refreshEl = head.createSpan({ cls: 'lb-problems-refresh', text: '' });
      const copy = head.createEl('button', { cls: 'lb-problems-copy', text: '复制报错' });
      copy.onclick = async () => { copy.disabled = true; try { await copyReport(); } finally { copy.disabled = false; } };
      const repair = head.createEl('button', { cls: 'lb-problems-repair-all', text: '全部修一遍' });
      repair.onclick = () => this.repair(repair);
      this.body = c.createDiv({ cls: 'lb-problems-body' });
      const cache = plugin.problemsCache;
      if (cache && Array.isArray(cache.problems)) {
        // C20：先按缓存画（不清空成「正在读取…」），后台再读一次
        this.paint(cache.problems);
        this.setRefreshing(true);
        return this.refresh();
      }
      return this.load();
    }
    onClose() { this.contentEl.empty(); }
    setRefreshing(on) { if (this.refreshEl) this.refreshEl.textContent = on ? '正在刷新…' : ''; }
    alive() { return this.body && this.body.isConnected !== false; }
    // 滚动的是 .modal（Obsidian 里）或内容区：重画前后各记 / 还一次
    keepScroll(fn) {
      const els = [this.modalEl, this.contentEl].filter(Boolean);
      const saved = els.map(e => e.scrollTop || 0);
      fn();
      els.forEach((e, i) => { try { e.scrollTop = saved[i]; } catch {} });
    }
    async refresh() {
      let j;
      try { j = await fetchList(); }
      catch (e) { this.setRefreshing(false); say('问题列表没刷新上：' + e.message); return; }
      this.setRefreshing(false);
      if (!this.alive()) return;
      if (listSignature(openRows(j)) === listSignature(this.rows)) return;   // 没变：一行不动
      this.keepScroll(() => this.paint(j.problems));
    }
    // 「现在修」（key = 那一条）/「全部修一遍」（不带 key）：进行中按钮显示「正在修 / 预计 N 分钟」，结束如实提示结果；
    // 单条只换那一行（C20），全部修一遍整体重画但保住滚动
    async repair(button, key, minutes) {
      if (this.repairing) { say('上一轮修复还在跑，等它跑完'); return null; }
      this.repairing = true;
      const label = button.textContent;
      button.disabled = true;
      button.addClass?.('is-running');
      button.textContent = key ? `正在修 / 预计 ${Math.max(1, Number(minutes) || 5)} 分钟` : '正在修 / 最多 15 分钟';
      let j = null;
      try {
        const args = ['-m', 'link_brain', 'problems', 'repair'];
        if (key) args.push('--key', key);
        const r = await plugin.runPy(args, { label: '当场修复', fallback: '修复没有返回结果', timeoutMs: key ? REPAIR_ONE_MS : REPAIR_ALL_MS });
        j = r.json || null;
        const left = j && Array.isArray(j.results) ? j.results.find(x => x && x.status !== 'resolved') : null;
        say((j && j.message ? j.message : '修复没有返回结果') + (key && left && left.message ? '\n' + left.message : ''), 12000);
      } catch (e) { say('修复没跑完：' + e.message, 12000); }
      finally {
        this.repairing = false;
        button.disabled = false;
        button.removeClass?.('is-running');
        button.textContent = label;
      }
      if (this.alive()) {
        if (key) await this.replaceRow(key);
        else await this.reloadKeepScroll();
      }
      return j;
    }
    async reloadKeepScroll() {
      let j;
      try { j = await fetchList(); } catch (e) { say('问题列表没刷新上：' + e.message); return; }
      if (this.alive()) this.keepScroll(() => this.paint(j.problems));
    }
    // 重读一次，只换 key 那一行（没了 = 修好了：标「✓ 已修好」、去掉按钮，不从列表里删，免得跳动）；组标题计数跟着改
    async replaceRow(key) {
      let j;
      try { j = await fetchList(); } catch (e) { say('问题列表没刷新上：' + e.message); return; }
      if (!this.alive()) return;
      const fresh = openRows(j);
      const old = this.findRow(key);
      const now = fresh.find(x => x.key === key);
      const moved = now && old && (isHidden(now) !== old.hasClass?.('is-hidden') || groupOf(now) !== old.dataset?.group);
      if (!old || moved) { this.keepScroll(() => this.paint(j.problems)); return; }
      if (!now) {
        old.addClass?.('is-resolved');
        const line = old.querySelector('.lb-problem-line');
        if (line) { line.empty?.(); line.createSpan({ cls: 'lb-problem-done', text: '✓ 已修好' }); }
        old.querySelector('.lb-problem-btns')?.remove();
        setTimeout(() => this.dropResolved(key), timing.resolvedLingerMs);
      } else {
        const holder = old.parentNode;
        const tmp = holder.createDiv();
        const el = this.row(tmp, now);
        old.replaceWith(el);
        tmp.remove();
      }
      this.rows = fresh;
      this.updateCounts();
    }
    // 修好的那一行停一会儿后拿掉（还标着已修好才拿：期间整体重画过就不用管了）；组空了连组拿掉，全空了画「没有问题」
    dropResolved(key) {
      if (!this.alive()) return;
      const el = this.findRow(key);
      if (!el || !el.hasClass?.('is-resolved')) return;
      this.keepScroll(() => {
        const sec = el.parentNode;
        el.remove();
        if (sec && sec.hasClass?.('lb-problems-group') && !sec.querySelector('.lb-problem')) sec.remove();
        if (!this.body.querySelector('.lb-problem')) this.paint(this.rows);
      });
    }
    findRow(key) { return Array.from(this.body.querySelectorAll('.lb-problem')).find(r => (r.getAttribute?.('data-key') ?? r.dataset?.key) === key) || null; }
    updateCounts() {
      for (const [g, name] of GROUPS) {
        const h = this.body.querySelector(`.lb-problems-group.is-${g} h3`);
        if (h) h.textContent = `${name} · ${this.rows.filter(x => !isHidden(x) && groupOf(x) === g).length}`;
      }
      const hs = this.body.querySelector('.lb-problems-hidden-toggle');
      if (hs) hs.textContent = `已隐藏 · ${this.rows.filter(isHidden).length}`;
    }
    async load() {
      const body = this.body;
      body.empty();
      body.createEl('p', { cls: 'lb-problems-status', text: '正在读取…' });
      let j;
      try { j = await fetchList(); }
      catch (e) { body.empty(); body.createEl('p', { cls: 'lb-problems-status mod-warning', text: '读不到问题列表：' + e.message }); return; }
      this.paint(j.problems);
    }
    paint(problems) {
      const body = this.body;
      body.empty();
      const rows = (problems || []).filter(visibleRow);
      this.rows = rows;
      const shown = rows.filter(x => !isHidden(x)), hidden = rows.filter(isHidden);
      if (!shown.length && !hidden.length) { body.createEl('p', { cls: 'lb-problems-status lb-problems-empty', text: '没有问题' }); return; }
      if (!shown.length) body.createEl('p', { cls: 'lb-problems-status lb-problems-empty', text: '没有问题' });
      for (const [g, name] of GROUPS) {
        const list = shown.filter(x => groupOf(x) === g);
        if (!list.length) continue;
        const sec = body.createDiv({ cls: 'lb-problems-group is-' + g });
        const h = sec.createDiv({ cls: 'lb-problems-group-head' });
        h.createEl('h3', { text: `${name} · ${list.length}` });
        const can = list.filter(x => x.dismissable);
        if (g === 'gave_up' && can.length) {
          const all = h.createEl('button', { cls: 'lb-problems-hide-all', text: `全部隐藏（${can.length}）` });
          all.onclick = () => this.dismiss(all, null);
        }
        for (const x of list) this.row(sec, x);
      }
      if (hidden.length) {
        // 默认收起：她隐藏过的条目在这里，可以恢复；同一原因又出现过几次照实写
        const sec = body.createDiv({ cls: 'lb-problems-group lb-problems-hidden is-hidden-group' });
        const toggle = sec.createEl('button', { cls: 'lb-problems-hidden-toggle', text: `已隐藏 · ${hidden.length}` });
        const list = sec.createDiv({ cls: 'lb-problems-hidden-list' });
        const show = on => { this.hiddenOpen = on; list.hidden = !on; toggle.setAttribute?.('aria-expanded', on ? 'true' : 'false'); };
        toggle.onclick = () => show(!this.hiddenOpen);
        for (const x of hidden) this.row(list, x);
        show(this.hiddenOpen);
      }
    }
    // 隐藏一条（key）/ 整组已放弃（key=null）：可恢复，不弹确认框；结束如实提示、重画（保住滚动）
    async dismiss(button, key) {
      button.disabled = true;
      try {
        const args = ['-m', 'link_brain', 'problems', 'dismiss', ...(key ? ['--key', key] : ['--group', 'gave_up'])];
        const r = await plugin.runPy(args, { label: '隐藏问题', fallback: '隐藏没有返回结果', timeoutMs: 60000 });
        const j = r.json;
        say(j && j.message ? j.message : '隐藏没有返回结果', j && j.ok === false ? 10000 : 6000);
      } catch (e) { say('隐藏没成功：' + e.message, 10000); }
      finally { button.disabled = false; }
      if (this.alive()) await this.reloadKeepScroll();
    }
    async undismiss(button, key) {
      button.disabled = true;
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'problems', 'undismiss', '--key', key], { label: '恢复显示', fallback: '恢复没有返回结果', timeoutMs: 60000 });
        say(r.json && r.json.message ? r.json.message : '恢复没有返回结果');
      } catch (e) { say('恢复没成功：' + e.message, 10000); }
      finally { button.disabled = false; }
      if (this.alive()) await this.reloadKeepScroll();
    }
    row(sec, x) {
      const row = sec.createDiv({ cls: 'lb-problem' + (isHidden(x) ? ' is-hidden' : '') });
      try { row.setAttribute('data-key', x.key || ''); row.setAttribute('data-group', groupOf(x)); } catch {}
      if (row.dataset) { row.dataset.key = x.key || ''; row.dataset.group = groupOf(x); }
      const line = row.createDiv({ cls: 'lb-problem-line' });
      line.createSpan({ cls: 'lb-problem-time', text: shortTime(x.ts) });
      line.createSpan({ cls: 'lb-problem-title', text: x.title || x.step_label || x.step || '' });
      line.createSpan({ cls: 'lb-problem-label', text: x.label || x.code || '' });
      const act = actionText(x);
      if (act) line.createSpan({ cls: 'lb-problem-action', text: act });
      if (Number(x.count) > 1) line.createSpan({ cls: 'lb-problem-count', text: `${x.count} 次` });
      if (isHidden(x) && Number(x.hidden_repeats) > 0) line.createSpan({ cls: 'lb-problem-hidden-repeats', text: `隐藏后又出现 ${x.hidden_repeats} 次` });
      const why = x.hover || x.reason;
      if (why) row.createDiv({ cls: 'lb-problem-why', text: why });
      // 当场修过没好：试过什么、为什么没好、下一步（Python 写好的一句）
      if (x.repair_note && x.repair_state === 'failed') row.createDiv({ cls: 'lb-problem-repair-note', text: x.repair_note });
      const btns = row.createDiv({ cls: 'lb-problem-btns' });
      let n = 0;
      if (isHidden(x)) {
        n++;
        const b = btns.createEl('button', { cls: 'lb-problem-undismiss', text: '恢复显示' });
        b.onclick = () => this.undismiss(b, x.key);
      }
      // 风控 / 登录 / key 这类（等你处理）保持人工按钮；「连续几天没修好」不是风控，也给「现在修」
      // 1008：AI 接口归并的那一条（step ai.*）换好 key 后也能点「现在修」补跑；已放弃的叫「再试一次」
      if (!isHidden(x) && x.repairable && (groupOf(x) !== 'needs_you' || subOf(x.code) === 'STUCK' || String(x.step || '').startsWith('ai.'))) {
        n++;
        const repair = btns.createEl('button', { cls: 'lb-problem-repair', text: groupOf(x) === 'gave_up' ? '再试一次' : '现在修' });
        if (x.repairing) { repair.disabled = true; repair.textContent = `正在修 / 预计 ${Math.max(1, Number(x.repair_minutes) || 5)} 分钟`; }
        repair.onclick = () => this.repair(repair, x.key, x.repair_minutes);
      }
      if (!isHidden(x) && x.dismissable && groupOf(x) === 'gave_up') {
        n++;
        const b = btns.createEl('button', { cls: 'lb-problem-dismiss', text: '隐藏' });
        b.onclick = () => this.dismiss(b, x.key);
      }
      if (x.item_id) {
        n++;
        const b = btns.createEl('button', { cls: 'lb-problem-open', text: '查看' });
        b.onclick = async () => {
          try { await openItem(x.item_id); this.close(); }
          catch (e) { say('打不开这一篇：' + e.message); }
        };
      }
      if (!isHidden(x)) for (const [text, fn, cls] of fixesFor(x)) {
        n++;
        const b = btns.createEl('button', { cls: 'lb-problem-fix mod-cta' + (cls ? ' ' + cls : ''), text });
        b.onclick = async () => {
          b.disabled = true;
          try { await fn(); } catch (e) { say(e.message, 10000); }
          finally { b.disabled = false; }
          if (this.alive()) await this.replaceRow(x.key);
        };
      }
      if (x.evidence_id && typeof plugin.openRiskEvidence === 'function') {
        // 出事那一刻程序看见的页面（本机截图，有私密收藏，不会被复制出去）
        n++;
        const b = btns.createEl('button', { cls: 'lb-problem-evidence', text: '查看截图' });
        b.onclick = async () => { try { await plugin.openRiskEvidence(x.evidence_id); } catch (e) { say('截图打不开：' + e.message, 10000); } };
      }
      if (!n) btns.remove();
      return row;
    }
  }

  return {
    ProblemsModal,
    open() { const m = new ProblemsModal(); m.open(); return m; },
    copyReport,
    _internals: { groupOf, actionText, fixesFor, shortTime, signature, visibleRow, timing },
  };
};

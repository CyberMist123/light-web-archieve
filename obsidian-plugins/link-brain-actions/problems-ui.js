// problems-ui.js — 第 4 批：目录页顶部问题入口点开的「问题」窗口（CONVENTIONS §3.3，RELEASE-BAR P12）。
// main.js 只接两行：problemsUI() 按需 require 本文件；openProblems() { return this.problemsUI().open(); }
// 数据：python -m link_brain problems list → {ok, summary, problems:[{ts,key,step,item_id,title,code,reason,action,next_at,count,resolved_at,label,hover,group}]}
//       python -m link_brain problems export --plugin-version X → {ok, text}（Python 已脱敏）
// 文案：每条的标签 / 原因（label / hover）全由 Python 登记表填好（problems.STATE_REGISTRY）；这里只有分组名、按钮名、系统动作的中文。
// 本模块不起进程：一律经 plugin.runPy（CONVENTIONS §1.4），失败如实提示。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Modal, Notice } = obsidian;
  const GROUPS = [['needs_you', '等你处理'], ['auto', '正在自动处理'], ['gave_up', '已放弃'], ['off', '未开启']];
  const GROUP_OF_CLASS = { NEEDS_HUMAN: 'needs_you', TRANSIENT: 'auto', PERMANENT: 'gave_up', SKIPPED: 'off' };
  // 系统已经做了什么（problems.ACTIONS 词表）
  const ACTION_TEXT = { retrying: '已重试', retry_later: '下晚再试', gave_up: '放弃', needs_human: '等你处理', skipped: '未开启' };
  // 要人处理的行带哪个按钮（按细分码，和 accounts.SOLUTIONS 的 action 对齐）
  const LOGIN = new Set(['NOT_LOGGED_IN', 'ACCOUNT_RISK', 'WRONG_ACCOUNT', 'RISK_HOLD']);
  const VERIFY = new Set(['CAPTCHA_REQUIRED', 'RISK_HOLD', 'ACCOUNT_RISK']);
  const ACCOUNT_PANEL = new Set(['NOT_INSTALLED', 'DISCONNECTED']);
  const AI_SETTINGS = new Set(['AUTH_FAILED', 'QUOTA_EXCEEDED']);

  const subOf = code => { const s = String(code || ''); const i = s.indexOf('.'); return i >= 0 ? s.slice(i + 1) : s; };
  const groupOf = r => (r && GROUPS.some(([g]) => g === r.group) ? r.group : GROUP_OF_CLASS[String(r?.code || '').split('.')[0]] || 'auto');
  function shortTime(v) {
    const t = Date.parse(v || '');
    if (!Number.isFinite(t)) return '';
    const d = new Date(t), p = n => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  function actionText(r) {
    const base = ACTION_TEXT[r.action] || '';
    const at = r.action === 'retry_later' || r.action === 'retrying' ? shortTime(r.next_at) : '';
    return at ? `${base}（${at}）` : base;
  }
  const say = (msg, ms = 8000) => { try { new Notice(msg, ms); } catch {} };

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

  // 这一行能直接修的按钮：[文字, 动作]
  function fixesFor(r) {
    if (groupOf(r) !== 'needs_you') return [];
    const sub = subOf(r.code), out = [];
    if (LOGIN.has(sub)) out.push(['扫码登录', () => plugin.fixFromCatalog('login')]);
    if (VERIFY.has(sub)) out.push(['打开验证', () => plugin.fixFromCatalog('verify')]);
    if (ACCOUNT_PANEL.has(sub)) out.push(['账号与同步…', () => plugin.openAccountStatus()]);
    if (AI_SETTINGS.has(sub)) out.push(['打开设置', () => { plugin.app.setting.open(); plugin.app.setting.openTabById(plugin.manifest.id); }]);
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

  class ProblemsModal extends Modal {
    constructor() { super(plugin.app); this.loading = null; }
    onOpen() {
      this.modalEl?.addClass?.('lb-problems-modal');
      const c = this.contentEl;
      c.empty();
      const head = c.createDiv({ cls: 'lb-problems-head' });
      head.createEl('h2', { text: '问题' });
      const copy = head.createEl('button', { cls: 'lb-problems-copy', text: '复制报错' });
      copy.onclick = async () => { copy.disabled = true; try { await copyReport(); } finally { copy.disabled = false; } };
      this.body = c.createDiv({ cls: 'lb-problems-body' });
      return this.load();
    }
    onClose() { this.contentEl.empty(); }
    async load() {
      const body = this.body;
      body.empty();
      body.createEl('p', { cls: 'lb-problems-status', text: '正在读取…' });
      let r;
      try { r = await plugin.runPy(['-m', 'link_brain', 'problems', 'list'], { label: '读取问题列表', fallback: '读不到问题列表', timeoutMs: 60000 }); }
      catch (e) { body.empty(); body.createEl('p', { cls: 'lb-problems-status mod-warning', text: '读不到问题列表：' + e.message }); return; }
      const j = r.json;
      body.empty();
      if (!j || j.ok === false || !Array.isArray(j.problems)) {
        body.createEl('p', { cls: 'lb-problems-status mod-warning', text: '读不到问题列表：' + ((j && (j.message || j.error)) || '后台没返回列表') });
        return;
      }
      const rows = j.problems.filter(x => x && !x.resolved_at);
      if (!rows.length) { body.createEl('p', { cls: 'lb-problems-status lb-problems-empty', text: '没有问题' }); return; }
      for (const [g, name] of GROUPS) {
        const list = rows.filter(x => groupOf(x) === g);
        if (!list.length) continue;
        const sec = body.createDiv({ cls: 'lb-problems-group is-' + g });
        sec.createEl('h3', { text: `${name} · ${list.length}` });
        for (const x of list) this.row(sec, x);
      }
    }
    row(sec, x) {
      const row = sec.createDiv({ cls: 'lb-problem' });
      const line = row.createDiv({ cls: 'lb-problem-line' });
      line.createSpan({ cls: 'lb-problem-time', text: shortTime(x.ts) });
      line.createSpan({ cls: 'lb-problem-title', text: x.title || x.step || '' });
      line.createSpan({ cls: 'lb-problem-label', text: x.label || x.code || '' });
      const act = actionText(x);
      if (act) line.createSpan({ cls: 'lb-problem-action', text: act });
      if (Number(x.count) > 1) line.createSpan({ cls: 'lb-problem-count', text: `${x.count} 次` });
      const why = x.hover || x.reason;
      if (why) row.createDiv({ cls: 'lb-problem-why', text: why });
      const btns = row.createDiv({ cls: 'lb-problem-btns' });
      let n = 0;
      if (x.item_id) {
        n++;
        const b = btns.createEl('button', { cls: 'lb-problem-open', text: '查看' });
        b.onclick = async () => {
          try { await openItem(x.item_id); this.close(); }
          catch (e) { say('打不开这一篇：' + e.message); }
        };
      }
      for (const [text, fn] of fixesFor(x)) {
        n++;
        const b = btns.createEl('button', { cls: 'lb-problem-fix mod-cta', text });
        b.onclick = async () => {
          b.disabled = true;
          try { await fn(); } catch (e) { say(e.message, 10000); }
          finally { b.disabled = false; }
          if (this.body && this.body.isConnected !== false) await this.load();
        };
      }
      if (!n) btns.remove();
    }
  }

  return {
    ProblemsModal,
    open() { const m = new ProblemsModal(); m.open(); return m; },
    copyReport,
    _internals: { groupOf, actionText, fixesFor, shortTime },
  };
};

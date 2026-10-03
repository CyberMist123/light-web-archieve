// report-ui.js — 目录页标题下「N 篇 · 更新 …」那行点开的窗口。10-03 起是「同步记录」（替换第 6 批的「本周同步情况」；
// `report week` 命令还在，窗口不再用它）。main.js 只接两行：reportUI() 按需 require 本文件；openSyncLog() { return this.reportUI().open(); }
// 数据：python -m link_brain synclog list → {ok, runs:[{run_id, trigger, started_at, finished_at, running?, stale?, new,
//   counts:{note|attachment|video|vision|summary:{ok,failed}}, items:[{kind,id,title,note,ok,reason}], errors:[{step,reason,code}], error}],
//   backlog: {favorites_total, archived, deferred, days_left} | null}
// 没有后端（比如手机上）就直接读库里的 _archive/sync-log.jsonl（看得到记录，没有第一排的积压）。
// 第一排：「一共 N 篇收藏，已入库 M 篇，预计还要 D 天同步完」（积压清零就不显示）；下面按时间倒序每次同步一行：
//   「10/03 04:00 夜跑 · 正文 3 ✅ 附件 2 ✅ 视频 1 ✅」，有失败写「附件 1 ❌」；⬇️ 展开看这次处理了哪些标题（点标题同一窗格打开）。
// 顶部「立即同步」「改定时」（plugin.syncNow / openSyncSettings）。
// 有报错的那条默认展开：原因 +「重试」（`synclog retry --run`：只重跑失败的那几篇 / 那一步，结果如实提示）；没报错的默认收起。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Modal, Notice } = obsidian;
  const say = (msg, ms = 8000) => { try { new Notice(msg, ms); } catch {} };
  const n = v => Number(v) || 0;
  const KIND_ORDER = ['note', 'attachment', 'video', 'vision', 'summary'];
  const KIND_CN = { note: '正文', attachment: '附件', video: '视频', vision: '识图', summary: '概要' };
  const TRIGGER_CN = { manual: '手动', nightly: '夜跑', schedule: '定时', cli: '命令行', retry: '重试' };
  const LOG = '_archive/sync-log.jsonl';
  const pad = x => String(x).padStart(2, '0');

  function when(ts) {
    const d = new Date(ts || '');
    if (!Number.isFinite(d.getTime())) return String(ts || '').slice(5, 16).replace('-', '/').replace('T', ' ');
    return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function countsText(run) {
    const c = run.counts || {};
    const out = [];
    for (const k of KIND_ORDER) {
      const x = c[k];
      if (!x || !(n(x.ok) || n(x.failed))) continue;
      out.push([KIND_CN[k], n(x.ok) && `${n(x.ok)} ✅`, n(x.failed) && `${n(x.failed)} ❌`].filter(Boolean).join(' '));
    }
    return out.join(' ');
  }
  // 一行：「10/03 04:00 夜跑 · 新收 3 · 正文 3 ✅ 附件 2 ✅」
  function lineText(run) {
    const head = `${when(run.started_at)} ${TRIGGER_CN[run.trigger] || run.trigger || ''}`.trim();
    const parts = [head];
    if (n(run.new)) parts.push(`新收 ${n(run.new)}`);
    const c = countsText(run);
    if (c) parts.push(c);
    else if (!(run.errors || []).length) parts.push(run.running ? '' : '没有新内容');
    if (run.running) parts.push('进行中…');
    else if ((run.errors || []).length && !c) parts.push('没做完');
    return parts.filter(Boolean).join(' · ');
  }
  function backlogText(b) {
    if (!b || !n(b.favorites_total) || !n(b.deferred)) return '';
    const days = b.days_left == null ? '' : `，预计还要 ${n(b.days_left)} 天同步完`;
    return `一共 ${n(b.favorites_total)} 篇收藏，已入库 ${n(b.archived)} 篇${days || '，还在补'}`;
  }
  const failedCount = run => (run.items || []).filter(it => !it.ok).length + (run.errors || []).length;

  // 没有后端：直接读库里的 jsonl（新的在前；没收尾又 8 小时没动的当作结束了）
  async function readLocal() {
    const raw = await plugin.app.vault.adapter.read(plugin.lbPath(LOG));
    const rows = [];
    for (const line of String(raw || '').split(/\r?\n/)) {
      if (!line.trim()) continue;
      try { const r = JSON.parse(line); if (r && r.run_id) rows.push(r); } catch {}
    }
    const now = Date.now();
    return rows.reverse().map(r => {
      if (r.finished_at) return r;
      const last = Date.parse(r.updated_at || r.started_at || '');
      return Number.isFinite(last) && now - last < 8 * 3600e3 ? { ...r, running: true } : { ...r, stale: true };
    });
  }

  async function openNote(note) {
    if (!note) throw new Error('这一篇还没生成正文');
    await plugin.app.workspace.openLinkText(plugin.lbPath(note), '', false);
  }

  class SyncLogModal extends Modal {
    constructor() { super(plugin.app); this.open_ = new Set(); }
    onOpen() {
      this.modalEl?.addClass?.('lb-report-modal');
      const c = this.contentEl;
      c.empty();
      c.createEl('h2', { text: '同步记录' });
      // 10-03（她定）：顶部「立即同步」「改定时」
      const top = c.createDiv({ cls: 'lb-synclog-top' });
      const now = top.createEl('button', { cls: 'mod-cta lb-synclog-sync', text: '立即同步' });
      now.onclick = () => { this.close(); try { plugin.syncNow(); } catch (e) { say('没同步起来：' + e.message); } };
      const plan = top.createEl('button', { cls: 'lb-synclog-plan', text: '改定时' });
      plan.onclick = () => { this.close(); try { plugin.openSyncSettings(); } catch (e) { say('打不开定时设置：' + e.message); } };
      this.body = c.createDiv({ cls: 'lb-report-body lb-synclog' });
      return this.load();
    }
    onClose() { this.contentEl.empty(); }
    async load() {
      const body = this.body;
      body.empty();
      body.createEl('p', { cls: 'lb-report-status', text: '正在读取…' });
      let runs = null, backlog = null, why = '';
      try {
        const r = await plugin.runPy(['-m', 'link_brain', 'synclog', 'list', '--limit', '30'], { label: '读取同步记录', fallback: '读不到同步记录', timeoutMs: 60000 });
        const j = r.json;
        if (j && j.ok !== false && Array.isArray(j.runs)) { runs = j.runs; backlog = j.backlog || null; }
        else why = (j && (j.message || j.error)) || '后台没返回数据';
      } catch (e) { why = e.message; }
      if (!runs) {
        try { runs = await readLocal(); }
        catch { body.empty(); body.createEl('p', { cls: 'lb-report-status mod-warning', text: why ? '读不到同步记录：' + why : '还没有同步记录（下次同步完会记在这里）' }); return; }
      }
      body.empty();
      this.render(runs, backlog);
    }
    render(runs, backlog) {
      const body = this.body;
      const b = backlogText(backlog);
      if (b) body.createDiv({ cls: 'lb-synclog-backlog', text: b });
      if (!runs.length) { body.createEl('p', { cls: 'lb-report-status lb-report-empty', text: '还没有同步记录（下次同步完会记在这里）' }); return; }
      for (const run of runs) this.row(body, run);
    }
    row(body, run) {
      const bad = !!run.error || failedCount(run) > 0;
      const box = body.createDiv({ cls: 'lb-synclog-run' + (bad ? ' is-error' : '') + (run.running ? ' is-running' : ''), attr: { 'data-run': run.run_id } });
      const head = box.createDiv({ cls: 'lb-synclog-head' });
      head.createSpan({ cls: 'lb-synclog-line', text: lineText(run) });
      const hasDetail = (run.items || []).length || (run.errors || []).length;
      // 有报错的默认展开；没报错的收起只显示一行
      let open = this.open_.has(run.run_id) || (bad && !this.open_.has('!' + run.run_id));
      const toggle = hasDetail ? head.createEl('button', { cls: 'lb-synclog-toggle', text: open ? '⬆️' : '⬇️' }) : null;
      const detail = box.createDiv({ cls: 'lb-synclog-detail' });
      const paint = () => {
        detail.empty();
        detail.hidden = !open;
        if (toggle) { toggle.setText(open ? '⬆️' : '⬇️'); toggle.setAttribute('aria-expanded', String(open)); }
        if (open) this.detail(detail, run, bad);
      };
      if (toggle) toggle.onclick = () => {
        open = !open;
        this.open_.delete(run.run_id); this.open_.delete('!' + run.run_id);
        this.open_.add(open ? run.run_id : '!' + run.run_id);
        paint();
      };
      paint();
    }
    detail(el, run, bad) {
      for (const e of run.errors || []) {
        el.createDiv({ cls: 'lb-synclog-err', text: '❌ ' + (e.reason || e.code || '出错了') });
      }
      const items = [...(run.items || [])].sort((a, b) => (a.ok === b.ok ? KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) : a.ok ? 1 : -1));
      for (const it of items) {
        const row = el.createDiv({ cls: 'lb-synclog-item' + (it.ok ? '' : ' is-failed') });
        row.createSpan({ cls: 'lb-synclog-mark', text: it.ok ? '✅' : '❌' });
        row.createSpan({ cls: 'lb-synclog-kind', text: KIND_CN[it.kind] || it.kind || '' });
        const label = it.title || it.id || it.url || '（没有标题）';
        const t = row.createEl(it.note ? 'a' : 'span', { cls: 'lb-synclog-title', text: label });
        if (it.note) {
          t.href = '#';
          t.onclick = async e => {
            e?.preventDefault?.();
            try { await openNote(it.note); this.close(); }
            catch (err) { say('打不开这一篇：' + err.message); }
          };
        }
        if (!it.ok && it.reason) row.createSpan({ cls: 'lb-synclog-reason', text: it.reason });
      }
      if (n(run.items_dropped)) el.createDiv({ cls: 'lb-synclog-more', text: `还有 ${n(run.items_dropped)} 条没记标题` });
      if (!bad || run.running) return;
      const acts = el.createDiv({ cls: 'lb-synclog-actions' });
      const btn = acts.createEl('button', { cls: 'mod-cta lb-synclog-retry', text: '重试' });
      const msg = acts.createSpan({ cls: 'lb-synclog-retrymsg' });
      if (run.retried_at) msg.setText(`上次重试：${when(run.retried_at)}`);
      if ((run.errors || []).length && typeof plugin.openProblems === 'function') {
        const p = acts.createEl('button', { cls: 'lb-report-problems', text: '看问题' });
        p.onclick = async () => { try { await plugin.openProblems(); this.close(); } catch (e) { say('打不开问题列表：' + e.message); } };
      }
      btn.onclick = async () => {
        btn.disabled = true; btn.setText('重试中…'); msg.setText('只重跑这次失败的那几篇 / 那一步，可能要几分钟');
        let r;
        try { r = await plugin.spawnPy(['-m', 'link_brain', 'synclog', 'retry', '--run', run.run_id], { exclusive: true, label: '重试同步失败项', timeoutMs: 3 * 3600e3 }); }
        catch (e) { r = { code: -1, json: null, err: e.message }; }
        btn.disabled = false; btn.setText('重试');
        if (r.busy) { msg.setText(r.err || '还有别的任务在跑，等它完事再点'); return; }
        if (r.timedOut) { msg.setText('重试超过 3 小时没跑完，已停止'); return; }
        const j = r.json;
        if (!j) { msg.setText('重试没跑成：' + (String(r.err || '').trim().split('\n').filter(Boolean).pop() || `退出码 ${r.code}`)); return; }
        say(j.message || (j.ok ? '重试完成' : '重试后还有没好的'), 10000);
        this.open_.add(run.run_id);
        await this.load();
        const box = Array.from(this.body.querySelectorAll('.lb-synclog-run')).find(x => x.getAttribute('data-run') === run.run_id);
        const after = box && box.querySelector('.lb-synclog-retrymsg');
        if (after) after.setText((j.ok ? '✅ ' : '') + (j.message || ''));
        else if (box) box.createDiv({ cls: 'lb-synclog-retrymsg', text: (j.ok ? '✅ ' : '') + (j.message || '') });
      };
    }
  }

  return {
    SyncLogModal,
    open() { const m = new SyncLogModal(); m.open(); return m; },
    _internals: { lineText, countsText, backlogText, when },
  };
};

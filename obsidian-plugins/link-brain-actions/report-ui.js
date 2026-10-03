// report-ui.js — 第 6 批：目录页标题下「N 篇 · 更新 …」那行点开的「本周同步情况」窗口。
// main.js 只接两行：reportUI() 按需 require 本文件；openWeekReport() { return this.reportUI().open(); }
// 数据：python -m link_brain report week [--days 7] → {ok, message, days, rows:[{date, weekday, new, note:{done,missing},
//   agent:{done,missing}, attachments:{expected,downloaded,missing,convertible,converted,unconverted}, vision_missing, summary_missing,
//   incomplete:[{id,title,note,missing:[…]}], nightly:{source, finished, text, problems:[…], open_problems}}], total:{…}, deferred, nightly_source}
// 那天夜跑的一句话（nightly.text）由 Python 拼好；这里只拼计数。本模块不起进程：一律经 plugin.runPy（CONVENTIONS §1.4），失败如实提示。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Modal, Notice } = obsidian;
  const say = (msg, ms = 8000) => { try { new Notice(msg, ms); } catch {} };
  const n = v => Number(v) || 0;

  // 一天（或总计）的计数 → 几小段话；没有新收的那天只说「没有新收藏」
  function facts(r) {
    const out = [];
    if (!n(r.new)) return out;
    const noteMiss = n(r.note?.missing), agentMiss = n(r.agent?.missing);
    out.push(noteMiss || agentMiss
      ? `正文 ${n(r.note?.done)}/${n(r.new)} · 机读版 ${n(r.agent?.done)}/${n(r.new)}`
      : '正文、机读版都生成了');
    const a = r.attachments || {};
    if (n(a.expected)) {
      let s = `附件下好 ${n(a.downloaded)}/${n(a.expected)}`;
      if (n(a.missing)) s += `，还缺 ${n(a.missing)} 个`;
      if (n(a.convertible)) s += n(a.unconverted) ? ` · 转文字 ${n(a.converted)}/${n(a.convertible)}` : ' · 都转成文字了';
      out.push(s);
    }
    const v = n(r.vision_missing), m = n(r.summary_missing);
    out.push(v || m ? [v && `识图还差 ${v} 篇`, m && `概要还差 ${m} 篇`].filter(Boolean).join(' · ') : '识图、概要都齐了');
    return out;
  }
  const shortDate = d => String(d || '').slice(5).replace('-', '/');

  async function openNote(note) {
    if (!note) throw new Error('这一篇还没生成正文');
    await plugin.app.workspace.openLinkText(plugin.lbPath(note), '', false);
  }

  class WeekReportModal extends Modal {
    constructor(days = 7) { super(plugin.app); this.days = days; }
    onOpen() {
      this.modalEl?.addClass?.('lb-report-modal');
      const c = this.contentEl;
      c.empty();
      c.createEl('h2', { text: '本周同步情况' });
      this.body = c.createDiv({ cls: 'lb-report-body' });
      return this.load();
    }
    onClose() { this.contentEl.empty(); }
    async load() {
      const body = this.body;
      body.empty();
      body.createEl('p', { cls: 'lb-report-status', text: '正在读取…' });
      let r;
      try { r = await plugin.runPy(['-m', 'link_brain', 'report', 'week', '--days', String(this.days)], { label: '读取同步情况', fallback: '读不到同步情况', timeoutMs: 120000 }); }
      catch (e) { body.empty(); body.createEl('p', { cls: 'lb-report-status mod-warning', text: '读不到同步情况：' + e.message }); return; }
      const j = r.json;
      body.empty();
      if (!j || j.ok === false || !Array.isArray(j.rows)) {
        body.createEl('p', { cls: 'lb-report-status mod-warning', text: '读不到同步情况：' + ((j && (j.message || j.error)) || '后台没返回数据') });
        return;
      }
      this.render(j);
    }
    render(j) {
      const body = this.body;
      const rows = j.rows;
      if (!rows.some(x => n(x.new))) {
        body.createEl('p', { cls: 'lb-report-status lb-report-empty', text: `最近 ${n(j.days) || 7} 天没有新收藏` });
      }
      for (const x of rows) this.day(body, x);
      const t = j.total || {};
      const foot = body.createDiv({ cls: 'lb-report-total' });
      foot.createDiv({ cls: 'lb-report-total-line', text: [`合计新收 ${n(t.new)} 篇`, ...facts(t)].join(' · ') });
      if (n(j.deferred) > 0) foot.createDiv({ cls: 'lb-report-deferred', text: `还剩 ${n(j.deferred)} 篇收藏逐晚处理` });
      if (j.nightly_source === 'problems') foot.createDiv({ cls: 'lb-report-note', text: '这台电脑没有夜跑日志：夜跑走没走完看不出来，只列当天登记的问题。' });
      if (j.time_field_note) foot.createDiv({ cls: 'lb-report-note', text: '「新收」' + j.time_field_note + '。' });
    }
    day(body, x) {
      const box = body.createDiv({ cls: 'lb-report-day' + (n(x.new) ? '' : ' is-empty') });
      const head = box.createDiv({ cls: 'lb-report-dayhead' });
      head.createSpan({ cls: 'lb-report-date', text: `${shortDate(x.date)} ${x.weekday || ''}`.trim() });
      head.createSpan({ cls: 'lb-report-new', text: n(x.new) ? `新收 ${n(x.new)} 篇` : '没有新收藏' });
      const f = facts(x);
      if (f.length) box.createDiv({ cls: 'lb-report-facts', text: f.join(' · ') });
      const nt = x.nightly || {};
      if (nt.text) {
        const line = box.createDiv({ cls: 'lb-report-nightly' + (nt.finished === false || n(nt.open_problems) ? ' is-warn' : '') });
        line.createSpan({ text: nt.text });
        if (Array.isArray(nt.problems) && nt.problems.length) {
          const b = line.createEl('button', { cls: 'lb-report-problems', text: '看问题' });
          b.onclick = async () => {
            try { await plugin.openProblems(); this.close(); }
            catch (e) { say('打不开问题列表：' + e.message); }
          };
        }
      }
      const todo = Array.isArray(x.incomplete) ? x.incomplete : [];
      if (todo.length) {
        const list = box.createDiv({ cls: 'lb-report-todo' });
        list.createDiv({ cls: 'lb-report-todo-head', text: `还没完成的 ${todo.length} 篇` });
        for (const it of todo) {
          const row = list.createDiv({ cls: 'lb-report-item' });
          const title = row.createEl(it.note ? 'a' : 'span', { cls: 'lb-report-title', text: it.title || it.id || '' });
          row.createSpan({ cls: 'lb-report-missing', text: '差：' + (it.missing || []).join('、') });
          if (it.note) {
            title.href = '#';
            title.onclick = async e => {
              e?.preventDefault?.();
              try { await openNote(it.note); this.close(); }
              catch (err) { say('打不开这一篇：' + err.message); }
            };
          }
        }
      }
    }
  }

  return {
    WeekReportModal,
    open(days) { const m = new WeekReportModal(days); m.open(); return m; },
    _internals: { facts },
  };
};

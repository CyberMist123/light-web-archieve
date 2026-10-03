// schedule-ui.js — 10-03 她定：定时同步更灵活（一次性某月某日某时 / 每周几可多选 + 时刻 / 每天一天几次 / 每 1–6 小时后台同步）。
// 设置页「同步与内容」的「定时…」弹窗和「开始」页 ④ 用的是这同一个组件：render(el, {onSaved}) → {refresh(), destroy()}。
// 规则形状（Python sync_schedule.normalize_rules 校验，这里只做格式上的初筛，不拼任何命令）：
//   {kind:'daily', times:['04:00','16:00']} · {kind:'weekly', days:['Monday'], times:['08:00']}
//   {kind:'once', at:'2026-10-03 17:00'} · {kind:'hourly', hours:4, from:'00:00'}
// 读：plugin.getSyncSchedule()（cur.rules / cur.summary 由 Python 给；老版本只有 freq/time/day 也认）。
// 写：plugin.setSyncRules(rules)；关闭：plugin.setSyncSchedule('off')。本模块不起进程，结果如实显示。
'use strict';

const DAYS = [['Monday', '一'], ['Tuesday', '二'], ['Wednesday', '三'], ['Thursday', '四'], ['Friday', '五'], ['Saturday', '六'], ['Sunday', '日']];
const KINDS = [['daily', '每天'], ['weekly', '每周几'], ['once', '一次'], ['hourly', '每几小时']];
const HOURLY_WARN = '每几小时同步会频繁用小红书号，太密容易触发验证 / 风控；建议 4 小时以上，或只在白天用。';
const TIME_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

const pad = n => String(n).padStart(2, '0');
function parseTimes(text) {
  const parts = String(text || '').split(/[\s,，、;；]+/).map(s => s.trim()).filter(Boolean);
  if (!parts.length) return null;
  const out = [];
  for (const p of parts) {
    const m = p.match(TIME_RE);
    if (!m) return null;
    const v = pad(Number(m[1])) + ':' + m[2];
    if (!out.includes(v)) out.push(v);
  }
  return out.sort();
}
// 读到的状态 → 编辑行（Python 给了 rules 就用；老格式只有 freq/time/day 也能还原；什么都没有 = 每天 04:00 一行）
function rowsFromState(cur) {
  cur = cur || {};
  if (Array.isArray(cur.rules) && cur.rules.length) return cur.rules.map(r => ({ ...r, times: r.times ? [...r.times] : undefined, days: r.days ? [...r.days] : undefined }));
  if (cur.freq === 'daily' && cur.time) return [{ kind: 'daily', times: [cur.time] }];
  if (cur.freq === 'weekly' && cur.time) return [{ kind: 'weekly', days: String(cur.day || 'Monday').split(',').map(s => s.trim()).filter(Boolean), times: [cur.time] }];
  return [{ kind: 'daily', times: ['04:00'] }];
}
// 编辑行 → 规则；格式不对返回 {error}
function rulesFromRows(rows) {
  const rules = [];
  for (const r of rows || []) {
    if (r.kind === 'daily' || r.kind === 'weekly') {
      const times = Array.isArray(r.times) ? parseTimes(r.times.join(',')) : parseTimes(r.timesText);
      if (!times) return { error: '时间格式不对：24 小时制，如 04:00 / 22:30，几个时刻用逗号隔开' };
      if (r.kind === 'weekly') {
        const days = DAYS.map(d => d[0]).filter(d => (r.days || []).includes(d));
        if (!days.length) return { error: '每周要至少选一天' };
        rules.push({ kind: 'weekly', days, times });
      } else rules.push({ kind: 'daily', times });
    } else if (r.kind === 'once') {
      const m = String(r.at || '').trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})/);
      if (!m) return { error: '一次性的要填日期和时间，如 2026-10-03 17:00' };
      rules.push({ kind: 'once', at: `${m[1]}-${pad(m[2])}-${pad(m[3])} ${pad(m[4])}:${m[5]}` });
    } else if (r.kind === 'hourly') {
      const h = Number(r.hours);
      if (!(h >= 1 && h <= 6 && Number.isInteger(h))) return { error: '每几小时只能是 1–6' };
      rules.push({ kind: 'hourly', hours: h, from: r.from || '00:00' });
    }
  }
  if (!rules.length) return { error: '至少要有一条定时（不想定时就点「关闭定时」）' };
  return { rules };
}
function statusLine(cur) {
  cur = cur || {};
  if (cur.error) return '当前：读不到计划任务（' + cur.error + '）';
  if (cur.freq === 'none') return cur.installable ? '当前：还没开启定时同步（保存 = 注册计划任务，关着 Obsidian 也按时同步）' : '当前：没有计划任务';
  if (cur.enabled === false) return '当前：已关闭' + (cur.summary && cur.summary !== '已关闭' ? '（保存就重新打开）' : '');
  if (cur.summary) return '当前：' + cur.summary + (Array.isArray(cur.others) && cur.others.length && cur.rules && cur.rules.length ? '　·　另有：' + cur.others.join('、') + '（不改动）' : '');
  return null;
}

module.exports = function scheduleUI(obsidian, plugin) {
  const Notice = obsidian.Notice;
  const say = (m, ms = 8000) => { try { new Notice(m, ms); } catch {} };

  function render(el, { onSaved = null } = {}) {
    const box = el.createDiv({ cls: 'lb-sched' });
    const status = box.createDiv({ cls: 'setting-item-description lb-sched-status', text: '读取当前定时…' });
    const list = box.createDiv({ cls: 'lb-sched-rows' });
    const add = box.createEl('button', { cls: 'lb-sched-add', text: '+ 加一条' });
    const warn = box.createDiv({ cls: 'setting-item-description lb-sched-warn', text: HOURLY_WARN });
    const actions = box.createDiv({ cls: 'lb-sched-actions' });
    const save = actions.createEl('button', { cls: 'mod-cta lb-sched-save', text: '保存定时' });
    const off = actions.createEl('button', { cls: 'lb-sched-off', text: '关闭定时' });
    const msg = box.createDiv({ cls: 'setting-item-description lb-sched-msg' });
    let rows = [], cur = null, alive = true;

    function paint() {
      list.empty();
      rows.forEach((r, i) => {
        const row = list.createDiv({ cls: 'lb-sched-row', attr: { 'data-kind': r.kind } });
        const kind = row.createEl('select', { cls: 'dropdown lb-sched-kind' });
        for (const [k, label] of KINDS) kind.createEl('option', { text: label, attr: { value: k } });
        kind.value = r.kind;
        kind.onchange = () => {
          const k = kind.value;
          rows[i] = k === 'weekly' ? { kind: k, days: ['Monday'], times: ['08:00'] } : k === 'once' ? { kind: k, at: '' }
            : k === 'hourly' ? { kind: k, hours: 4, from: '00:00' } : { kind: 'daily', times: ['04:00'] };
          paint();
        };
        if (r.kind === 'weekly') {
          const days = row.createDiv({ cls: 'lb-sched-days' });
          for (const [d, label] of DAYS) {
            const on = (r.days || []).includes(d);
            const b = days.createEl('button', { cls: 'lb-sched-day' + (on ? ' is-on' : ''), text: label, attr: { 'data-day': d, 'aria-pressed': String(on) } });
            b.onclick = () => { const set = new Set(r.days || []); set.has(d) ? set.delete(d) : set.add(d); r.days = DAYS.map(x => x[0]).filter(x => set.has(x)); paint(); };
          }
        }
        if (r.kind === 'daily' || r.kind === 'weekly') {
          const t = row.createEl('input', { cls: 'lb-sched-times', type: 'text' });
          t.placeholder = '04:00, 16:00';
          t.value = r.timesText != null ? r.timesText : (r.times || []).join(', ');
          t.oninput = () => { r.timesText = t.value; delete r.times; };
          row.createSpan({ cls: 'lb-sched-hint', text: r.kind === 'daily' ? '一天几次就写几个时刻' : '时刻' });
        } else if (r.kind === 'once') {
          const t = row.createEl('input', { cls: 'lb-sched-at', type: 'datetime-local' });
          t.value = String(r.at || '').replace(' ', 'T');
          t.oninput = t.onchange = () => { r.at = t.value; };
        } else if (r.kind === 'hourly') {
          row.createSpan({ cls: 'lb-sched-hint', text: '每' });
          const h = row.createEl('select', { cls: 'dropdown lb-sched-hours' });
          for (let n = 1; n <= 6; n++) h.createEl('option', { text: String(n), attr: { value: String(n) } });
          h.value = String(r.hours || 4);
          h.onchange = () => { r.hours = Number(h.value); };
          row.createSpan({ cls: 'lb-sched-hint', text: '小时在后台同步一次' });
        }
        const del = row.createEl('button', { cls: 'lb-sched-del', text: '×' });
        del.setAttribute('aria-label', '删掉这一条');
        del.onclick = () => { rows.splice(i, 1); paint(); };
      });
      warn.hidden = !rows.some(r => r.kind === 'hourly');
    }
    add.onclick = () => { rows.push({ kind: 'daily', times: ['04:00'] }); paint(); };

    async function refresh() {
      try { cur = await plugin.getSyncSchedule(); }
      catch (e) { cur = { error: e.message || String(e) }; }
      if (!alive) return cur;
      status.setText(statusLine(cur) || (plugin.scheduleStatusText ? plugin.scheduleStatusText(cur) : ''));
      rows = rowsFromState(cur);
      paint();
      return cur;
    }
    save.onclick = async () => {
      const r = rulesFromRows(rows);
      if (r.error) { msg.setText(r.error); say(r.error); return; }
      save.disabled = true; off.disabled = true; msg.setText('正在保存…');
      try {
        const res = await plugin.setSyncRules(r.rules);
        if (res && res.ok) { msg.setText(res.detail || '已保存'); say(res.detail || '已保存定时同步'); await refresh(); onSaved && onSaved(res); }
        else { const why = (res && (res.error || res.detail || res.message)) || '可能需要管理员权限'; msg.setText('没保存上：' + why); say('没保存上：' + why, 10000); }
      } catch (e) { msg.setText('没保存上：' + (e.message || e)); say('没保存上：' + (e.message || e), 10000); }
      finally { save.disabled = false; off.disabled = false; }
    };
    off.onclick = async () => {
      save.disabled = true; off.disabled = true; msg.setText('正在关闭…');
      try {
        const res = await plugin.setSyncSchedule('off');
        if (res && res.ok) { msg.setText('已关闭定时同步（触发器都留着，保存就恢复）'); await refresh(); onSaved && onSaved(res); }
        else { const why = (res && (res.error || res.detail || res.message)) || '没关上'; msg.setText('没关上：' + why); }
      } catch (e) { msg.setText('没关上：' + (e.message || e)); }
      finally { save.disabled = false; off.disabled = false; }
    };
    paint();
    const ready = refresh();
    return { el: box, ready, refresh, destroy() { alive = false; }, get rows() { return rows; } };
  }

  return { render, _internals: { rowsFromState, rulesFromRows, parseTimes, statusLine, HOURLY_WARN } };
};

// schedule-ui.js — 10-03 她定：定时同步更灵活（一次性某月某日某时 / 每周几可多选 + 时刻 / 每天一天几次 / 每 1–6 小时后台同步）。
// 唯一的「自动同步时间」编辑器：设置页「收藏与同步」、首次设置「同步」一步都由 settings-v6.js 的 syncTimeEditor 包这一个组件；
// 首页齿轮 / 同步记录「改定时」/ 账号弹窗「定时…」都走 plugin.openSyncTime() 跳到设置页里的它（1026 起不再有单独的定时弹窗）。
// 1027（设置页六组）：改了自动保存——没有「保存定时」「关闭定时」两个按钮了。打字停 1.2 秒或离开那一格就存（合并着存，不每个字注册一次计划任务）；
//   格式不对只在下面说一句、不存（留作草稿，下次打开接着改）；开 / 关是设置页「同步」那一个开关（setEnabled）。
//   只在她动了编辑器之后才写——画出来、读到推荐值都不写；「同步」关着时改时间只记着，打开「同步」才按它注册。
// render(el, {onSaved, onState, delay}) → {ready, refresh(), isDirty(), saveNow(), setEnabled(on), enabled(), destroy()}。
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
  if (!rules.length) return { error: '至少要有一条时间（不想自动同步就关掉上面的「同步」）' };
  return { rules };
}
function statusLine(cur) {
  cur = cur || {};
  if (cur.error) return '当前：暂时读不到现在的定时（改一下时间就按下面的设置重写一遍）';   // 1010：原始报错不直接露，折在「详情」里
  if (cur.freq === 'none') return cur.installable ? '当前：还没开（打开「同步」就按下面的时间注册计划任务，关着 Obsidian 也照常同步）' : '当前：没有计划任务';
  if (cur.enabled === false) return '当前：已关闭';
  if (cur.summary) return '当前：' + cur.summary + (Array.isArray(cur.others) && cur.others.length && cur.rules && cur.rules.length ? '　·　另有：' + cur.others.join('、') + '（不改动）' : '');
  return null;
}
// 开着没有：没有计划任务 / 关掉了 = 没开；读不到 = 不知道（null）
function enabledOf(cur) {
  if (!cur || cur.error) return null;
  return !(cur.freq === 'none' || cur.enabled === false);
}

module.exports = function scheduleUI(obsidian, plugin) {
  const Notice = obsidian.Notice;
  const say = (message, ms = 8000) => plugin.notify ? plugin.notify(message, { ms }) : new Notice(message, ms);

  function render(el, { onSaved = null, onState = null, delay = 1200 } = {}) {
    const box = el.createDiv({ cls: 'lb-sched' });
    const status = box.createDiv({ cls: 'setting-item-description lb-sched-status', text: '读取当前定时…' });
    const list = box.createDiv({ cls: 'lb-sched-rows' });
    const add = box.createEl('button', { cls: 'lb-sched-add', text: '+ 加一条' });
    const warn = box.createDiv({ cls: 'setting-item-description lb-sched-warn', text: HOURLY_WARN });
    const msg = box.createDiv({ cls: 'setting-item-description lb-sched-msg', attr: { role: 'status' } });
    let rows = [], cur = null, alive = true, timer = null, saving = null, again = false, edits = 0, savedEdits = 0;

    // 她动了一下：过一会儿自动存（离开那一格 / 换了选项立刻存）
    const touched = (now = false) => {
      edits++;
      box.classList.add('is-dirty');
      clearTimeout(timer); timer = null;
      if (now) saveNow(); else timer = setTimeout(() => { timer = null; saveNow(); }, delay);
    };
    function paint() {
      list.empty();
      rows.forEach((r, i) => {
        const row = list.createDiv({ cls: 'lb-sched-row', attr: { 'data-kind': r.kind } });
        const kind = row.createEl('select', { cls: 'dropdown lb-sched-kind', attr: { 'aria-label': '多久同步一次' } });
        for (const [k, label] of KINDS) kind.createEl('option', { text: label, attr: { value: k } });
        kind.value = r.kind;
        kind.onchange = () => {
          const k = kind.value;
          rows[i] = k === 'weekly' ? { kind: k, days: ['Monday'], times: ['08:00'] } : k === 'once' ? { kind: k, at: '' }
            : k === 'hourly' ? { kind: k, hours: 4, from: '00:00' } : { kind: 'daily', times: ['04:00'] };
          paint(); touched();
        };
        if (r.kind === 'weekly') {
          const days = row.createDiv({ cls: 'lb-sched-days' });
          for (const [d, label] of DAYS) {
            const on = (r.days || []).includes(d);
            const b = days.createEl('button', { cls: 'lb-sched-day' + (on ? ' is-on' : ''), text: label, attr: { 'data-day': d, 'aria-pressed': String(on) } });
            b.onclick = () => { const set = new Set(r.days || []); set.has(d) ? set.delete(d) : set.add(d); r.days = DAYS.map(x => x[0]).filter(x => set.has(x)); paint(); touched(); };
          }
        }
        if (r.kind === 'daily' || r.kind === 'weekly') {
          const t = row.createEl('input', { cls: 'lb-sched-times', type: 'text', attr: { 'aria-label': '同步时刻（24 小时制，几个用逗号隔开）' } });
          t.placeholder = '04:00, 16:00';
          t.value = r.timesText != null ? r.timesText : (r.times || []).join(', ');
          t.oninput = () => { r.timesText = t.value; delete r.times; touched(); };
          t.onchange = () => { if (timer) touched(true); };
          row.createSpan({ cls: 'lb-sched-hint', text: r.kind === 'daily' ? '一天几次就写几个时刻' : '时刻' });
        } else if (r.kind === 'once') {
          const t = row.createEl('input', { cls: 'lb-sched-at', type: 'datetime-local', attr: { 'aria-label': '哪天几点同步一次' } });
          t.value = String(r.at || '').replace(' ', 'T');
          t.oninput = () => { r.at = t.value; touched(); };
          t.onchange = () => { r.at = t.value; touched(true); };
        } else if (r.kind === 'hourly') {
          row.createSpan({ cls: 'lb-sched-hint', text: '每' });
          const h = row.createEl('select', { cls: 'dropdown lb-sched-hours', attr: { 'aria-label': '每几小时' } });
          for (let n = 1; n <= 6; n++) h.createEl('option', { text: String(n), attr: { value: String(n) } });
          h.value = String(r.hours || 4);
          h.onchange = () => { r.hours = Number(h.value); touched(); };
          row.createSpan({ cls: 'lb-sched-hint', text: '小时在后台同步一次' });
        }
        const del = row.createEl('button', { cls: 'lb-sched-del', text: '×' });
        del.setAttribute('aria-label', '删掉这一条');
        del.onclick = () => { rows.splice(i, 1); paint(); touched(); };
      });
      warn.hidden = !rows.some(r => r.kind === 'hourly');
    }
    add.onclick = () => { rows.push({ kind: 'daily', times: ['04:00'] }); paint(); touched(); };

    function paintStatus() {
      status.setText(statusLine(cur) || (plugin.scheduleStatusText ? plugin.scheduleStatusText(cur) : ''));
      if (cur && cur.error) { const det = status.createEl('details', { cls: 'lb-fail-detail' }); det.createEl('summary', { text: '详情' }); det.createEl('pre', { text: String(cur.error).slice(0, 2000) }); }
      try { onState && onState(enabledOf(cur), cur); } catch (e) { console.error('[lb] 同步开关没对上', e); }
    }
    async function refresh(preserveDraft = false) {
      add.disabled = true;
      list.classList.add('is-loading');
      try { cur = await plugin.getSyncSchedule(); }
      catch (e) { cur = { error: e.message || String(e) }; }
      if (!alive) return cur;
      // 上次没存成（格式不对 / 写失败）的草稿：接着显示，并标出来（不冒充已生效）
      const draft = preserveDraft && plugin.scheduleDraft;
      rows = draft ? plugin.scheduleDraft : rowsFromState(cur);
      paintStatus();
      paint();
      if (draft) { const r = rulesFromRows(rows); msg.setText('上次改的还没保存' + (r.error ? '：' + r.error : '')); box.classList.add('is-dirty'); }
      add.disabled = false;
      list.classList.remove('is-loading');
      return cur;
    }
    const savedRules = () => { const r = rulesFromRows(rowsFromState(cur)); return r.error ? null : JSON.stringify(r.rules); };
    function isDirty() {
      if (timer || saving) return true;
      if (!cur || cur.error) return false;
      const r = rulesFromRows(rows);
      if (r.error) return true;
      return enabledOf(cur) === true && JSON.stringify(r.rules) !== savedRules();
    }
    // 存一次（多次改动合并；正在存时又改了 → 存完再存一次）。「同步」关着时只记着，不注册计划任务（打开「同步」才按这几条注册）
    async function saveNow({ force = false } = {}) {
      clearTimeout(timer); timer = null;
      if (saving) { again = true; return saving; }
      const r = rulesFromRows(rows);
      if (r.error) { msg.setText('没保存：' + r.error); plugin.scheduleDraft = rows; return { ok: false, error: r.error }; }
      if (!force && enabledOf(cur) !== true) { msg.setText('「同步」关着：打开就按这个时间同步'); box.classList.remove('is-dirty'); plugin.scheduleDraft = rows; return { ok: true, skipped: true }; }
      if (!force && JSON.stringify(r.rules) === savedRules()) { box.classList.remove('is-dirty'); plugin.scheduleDraft = null; return { ok: true, unchanged: true }; }
      const at = edits;
      msg.setText('正在保存…');
      saving = (async () => {
        try {
          const res = await plugin.setSyncRules(r.rules);
          if (res && res.ok) {
            plugin.scheduleDraft = null; savedEdits = at;
            try { cur = await plugin.getSyncSchedule(); } catch { cur = { ...(cur || {}), freq: 'custom', enabled: true, rules: r.rules }; }
            if (alive) { paintStatus(); msg.setText(res.detail || '已保存'); if (edits === at) box.classList.remove('is-dirty'); }
            onSaved && onSaved(res);
            return res;
          }
          const why = (res && (res.error || res.detail || res.message)) || '可能需要管理员权限';
          msg.setText('没保存上：' + why); say('同步时间没保存上：' + why, 10000); plugin.scheduleDraft = rows;
          return { ok: false, error: why };
        } catch (e) { const why = e.message || String(e); msg.setText('没保存上：' + why); say('同步时间没保存上：' + why, 10000); plugin.scheduleDraft = rows; return { ok: false, error: why }; }
      })();
      try { return await saving; }
      finally { saving = null; if (again) { again = false; if (edits !== savedEdits) saveNow(); } }
    }
    // 设置页「同步」开关：开 = 按编辑器里这几条注册 / 恢复计划任务；关 = 关掉（触发器留着，再开就恢复）
    async function setEnabled(on) {
      if (on) return saveNow({ force: true });
      clearTimeout(timer); timer = null;
      msg.setText('正在关…');
      try {
        const res = await plugin.setSyncSchedule('off');
        if (res && res.ok) {
          plugin.scheduleDraft = null;
          try { cur = await plugin.getSyncSchedule(); } catch { cur = null; }
          if (!cur || enabledOf(cur) !== false) cur = { ...(cur || {}), enabled: false, summary: '已关闭' };
          if (alive) { paintStatus(); msg.setText('已关闭自动同步（再打开就按这个时间）'); }
          return res;
        }
        const why = (res && (res.error || res.detail || res.message)) || '没关上';
        msg.setText('没关上：' + why); return { ok: false, error: why };
      } catch (e) { msg.setText('没关上：' + (e.message || e)); return { ok: false, error: e.message || String(e) }; }
    }
    paint();
    const ready = refresh(true);
    // 关设置页时还有没存的：立刻存（格式不对的留作草稿，下次打开接着改、标着没保存）
    return { el: box, ready, refresh, isDirty, saveNow, setEnabled, enabled: () => enabledOf(cur),
      destroy() { if (timer) saveNow(); alive = false; }, get rows() { return rows; } };
  }

  return { render, _internals: { rowsFromState, rulesFromRows, parseTimes, statusLine, enabledOf, HOURLY_WARN } };
};

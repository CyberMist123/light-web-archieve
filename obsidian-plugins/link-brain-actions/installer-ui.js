// installer-ui.js — 1103 作者：新电脑第一次装，像个安装器。一个窗口：上面趁着装先选好（收藏放哪 · 认不认图片里的字 · 登录），
//   下面一条总进度条（百分比 + 正在做什么）。以前是启动弹一条通知、进度画在设置页里，新用户点进设置页满屏「没找到后端程序」。
// 两段：① 后端（homeUI.installBackend → backend-install.ensureBackend：uv → Python → 环境 → link-brain[ocr,bilibili,docs] → 自检）
//       ② 组件（`setup install --component reader / ocr`：读取组件、OCR 模型 + 认一张测试图；缺 VC++ 运行库后端自己补）。
// OCR / B 站 / 附件的依赖默认都装（作者：几百 MB，省用户成本；不开的功能只是不显示）。
// 关掉窗口照样在后台装（底部状态栏有进度，设置页顶部有「打开安装窗口」）；装完接着走首次自动同步（onboarding-ui.startup）。
// 本模块不起进程：后端那段经 homeUI，组件那段经 plugin.spawnPy（CONVENTIONS §6.1）。
'use strict';

// 每一步占总进度条多少（下依赖那一步最长：几百 MB）
const WEIGHTS = [['uv', 4], ['python', 10], ['venv', 2], ['install', 52], ['check', 3], ['reader', 14], ['ocr', 15]];
const STEP_TEXT = { uv: '准备安装工具', python: '下载 Python', venv: '建后端环境', install: '下载并安装依赖', check: '自检',
  reader: '下载读取组件', ocr: '下载认字模型并试认一张图' };
// 没有真进度（done/total）的步骤：按时间慢慢往前挪，最多挪到这一步的 90%，别让进度条看着像卡死（秒）
const CREEP_S = { uv: 15, python: 40, venv: 10, install: 180, check: 20, reader: 40, ocr: 60 };
const COMPONENTS = ['reader', 'ocr'];

const num = v => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));
function stepFraction(st, now = Date.now()) {
  if (!st) return 0;
  if (st.state === 'ok' || st.state === 'skipped') return 1;
  const d = num(st.done), t = num(st.total);
  if (d != null && t) return Math.max(0, Math.min(0.99, d / t));
  if (st.state === 'running' && st.startedAt) return 0.9 * (1 - Math.exp(-Math.max(0, now - st.startedAt) / 1000 / (CREEP_S[st.stage] || 30)));
  return st.frac || 0;
}
// 总进度（0–100）。只进不退由调用方记 best
function overallPct(steps, now = Date.now()) {
  let sum = 0, all = 0;
  for (const [k, w] of WEIGHTS) { all += w; sum += w * stepFraction(steps[k], now); }
  return Math.max(0, Math.min(100, Math.floor(sum / all * 100)));
}
// 进度条下面那一行：正在跑的那一步说了什么（没说就用这一步的名字）
function currentText(steps) {
  for (const [k] of WEIGHTS) {
    const st = steps[k];
    if (st && st.state === 'running') return st.text ? `${STEP_TEXT[k]}：${st.text}` : STEP_TEXT[k] + '…';
  }
  return '';
}
// 出错时给人看的一句话（原始报错折进「详情」）
function friendlyError(step, res) {
  const code = String((res && res.code) || ''), raw = String((res && res.message) || '');
  const what = STEP_TEXT[step] || '安装';
  let text;
  if (code === 'TRANSIENT.NETWORK' || code === 'TRANSIENT.HTTP_5XX' || code === 'TRANSIENT.DISCONNECTED') text = `${what}时网络断了或太慢。已经下好的会留着，点「重试」接着下。`;
  else if (code === 'PERMANENT.DISK_FULL') text = '磁盘空间不够：C 盘清出 1 GB 左右再点「重试」。';
  else if (code === 'PERMANENT.CHECKSUM_MISMATCH') text = `${what}时下载的文件没通过校验（可能下坏了），已经删掉。点「重试」重新下。`;
  else if (code === 'SKIPPED.NOT_CONFIGURED' && raw) text = raw;
  else text = `${what}没成功。点「重试」再试一次；还不行就点「复制详情」发给作者。`;
  return { text, detail: raw, code };
}
// `setup install` 的一行 → 这一步的状态补丁（不是进度 / 结果行返回 null）
function componentEvent(line) {
  let ev; try { ev = JSON.parse(line); } catch { return null; }
  if (!ev || typeof ev !== 'object') return null;
  if (ev.type === 'progress') return { state: 'running', done: num(ev.done), total: num(ev.total), text: ev.text || ev.phase || '' };
  if (ev.type === 'result') return { state: ev.ok ? 'ok' : 'failed', result: ev, text: ev.ok ? (ev.message || '好了') : '' };
  return null;
}

module.exports = function installerUI(obsidian, plugin) {
  const { Modal, Setting } = obsidian;
  const S = () => plugin.installerState || (plugin.installerState = { state: 'idle', steps: {}, error: null, warnings: [], best: 0, startedAt: 0, goWaiters: [], modal: null });
  const listeners = new Set();
  const changed = () => { for (const f of listeners) { try { f(); } catch (e) { console.error('[lb] 安装窗口没重画上', e); } } };
  const setStep = (k, patch) => {
    const st = S(), cur = st.steps[k] || { stage: k, state: 'pending' };
    const next = { ...cur, ...patch, stage: k };
    if (next.state === 'running' && !cur.startedAt) next.startedAt = Date.now();
    st.steps[k] = next;
    changed();
  };
  const pct = () => { const st = S(); st.best = Math.max(st.best, overallPct(st.steps)); return st.state === 'done' ? 100 : st.best; };
  const running = () => S().state === 'running';

  // 用户在窗口里点了「开始同步」或者关了窗口 → 首次自动同步可以开始了
  function releaseGo() { const st = S(); const ws = st.goWaiters.splice(0); for (const w of ws) w(); }
  function waitGo() { const st = S(); if (!st.modal) return Promise.resolve(); return new Promise(r => st.goWaiters.push(r)); }

  async function installComponent(id) {
    setStep(id, { state: 'running', text: '' });
    const r = await plugin.spawnPy(['-m', 'link_brain', 'setup', 'install', '--component', id], {
      exclusive: true, label: '安装 ' + STEP_TEXT[id], timeoutMs: 30 * 60000,
      onLine: line => {
        const p = componentEvent(line);
        if (!p) return;
        setStep(id, p);
        if (p.state === 'running') { plugin.runningProgress = STEP_TEXT[id] + (p.text ? '：' + p.text : ''); plugin.taskChanged?.(); }
      },
    });
    const cur = S().steps[id] || {};
    if (cur.state === 'ok') return { ok: true };
    const res = cur.result || (r.json && r.json.type === 'result' ? r.json : null)
      || { ok: false, code: r.busy ? 'TRANSIENT.BUSY' : r.timedOut ? 'TRANSIENT.TIMEOUT' : 'TRANSIENT.STEP_CRASHED', message: r.busy ? plugin.busyText() : String(r.err || '').trim().split('\n').slice(-3).join('\n') };
    setStep(id, { state: 'failed', result: res });
    return res;
  }

  // 整个安装：后端 → 组件。返回 {ok}（后端没装上 = false；组件没装好只记 warnings，不算失败：同步照样能跑）
  async function run() {
    const st = S();
    if (st.state === 'running') return st.promise;
    st.state = 'running'; st.error = null; st.warnings = []; st.startedAt = Date.now();
    for (const k of Object.keys(st.steps)) if (st.steps[k].state !== 'ok' && st.steps[k].state !== 'skipped') delete st.steps[k];
    changed();
    st.promise = (async () => {
      const home = plugin.homeUI();
      if (plugin.currentBackend().mode === 'missing') {
        const res = await home.installBackend({ quiet: true, onProgress: ev => setStep(ev.stage, { state: ev.state, done: ev.done, total: ev.total, text: ev.text }) });
        if (!res || !res.ok) {
          const failed = Object.keys(st.steps).find(k => st.steps[k].state === 'failed') || 'install';
          st.error = friendlyError(failed, res || { code: 'TRANSIENT.BUSY', message: plugin.busyText ? plugin.busyText() : '' });
          st.state = 'failed'; changed();
          return { ok: false, error: st.error };
        }
      } else for (const [k] of WEIGHTS.slice(0, 5)) setStep(k, { state: 'skipped' });
      for (const id of COMPONENTS) {
        const r = await installComponent(id);
        if (!r.ok) st.warnings.push({ id, ...friendlyError(id, r) });
      }
      st.state = 'done'; changed();
      plugin.notify(st.warnings.length ? 'Link Brain 装好了（有一项没装好，见安装窗口）' : 'Link Brain 装好了', { kind: st.warnings.length ? 'warn' : 'ok', ms: 6000 });
      return { ok: true, warnings: st.warnings };
    })();
    return st.promise;
  }

  // —— 窗口 ——
  class InstallerModal extends Modal {
    constructor(app) { super(app); this.unsub = null; this.timer = null; }
    onOpen() {
      const st = S();
      st.modal = this;
      this.modalEl.addClass?.('lb-installer-modal');
      this.titleEl?.setText?.('安装 Link Brain');
      const c = this.contentEl;
      c.empty?.();
      c.addClass?.('lb-installer');
      // 上：趁着装先选好
      const pick = c.createDiv({ cls: 'lb-installer-pick' });
      pick.createEl('p', { cls: 'lb-installer-lead', text: '正在自动安装，大约几分钟。趁这会儿先选好下面几样（都能以后在设置里改）：' });
      try { plugin.onboardingUI().renderFolder(pick); } catch (e) { console.error('[lb] 收藏位置那一行没画上', e); }
      const ocr = new Setting(pick).setName('认图片里的字').setDesc('截图、表格里的字也能搜到；在本机认，免费。关掉也照样装好，只是不用、不显示。');
      ocr.addToggle(t => t.setValue(ocrOn()).onChange(async v => {
        try { await setOcr(v); } catch (e) { plugin.notify('没保存上：' + (e && e.message || e), { kind: 'error' }); }
      }));
      new Setting(pick).setName('接 AI（问收藏、自动写概要）').setDesc('要自己的 API key，不接也能用。装完在设置里填。');
      this.login = new Setting(pick).setName('登录小红书').setDesc('');
      this.login.addButton(b => { this.loginBtn = b; b.setButtonText('扫码登录').onClick(() => this.doLogin()); });
      // 下：总进度
      const foot = c.createDiv({ cls: 'lb-installer-foot' });
      this.pctEl = foot.createDiv({ cls: 'lb-installer-pct' });
      const bar = foot.createDiv({ cls: 'lb-bar lb-installer-bar' });
      this.fillEl = bar.createDiv({ cls: 'lb-bar-fill' });
      this.nowEl = foot.createDiv({ cls: 'lb-installer-now setting-item-description' });
      this.msgEl = foot.createDiv({ cls: 'lb-installer-msg' });
      this.actsEl = foot.createDiv({ cls: 'lb-installer-actions' });
      // 没有真进度的步骤按时间往前挪：装的时候每秒重画一次
      const tick = () => { this.timer = null; this.paint(); if (running()) this.timer = setTimeout(tick, 1000); };
      const paint = () => { if (this.timer == null) tick(); else this.paint(); };
      listeners.add(paint);
      this.unsub = () => listeners.delete(paint);
      tick();
    }
    paint() {
      const st = S();
      const p = pct();
      this.pctEl.setText(st.state === 'done' ? '装好了' : st.state === 'failed' ? '没装完' : `${p}%`);
      this.fillEl.style.width = p + '%';
      this.nowEl.setText(st.state === 'running' ? (currentText(st.steps) || '准备中…') : '');
      this.msgEl.empty?.();
      this.actsEl.empty?.();
      if (st.state === 'failed' && st.error) {
        this.msgEl.createDiv({ cls: 'lb-installer-err', text: st.error.text });
        this.button(this.actsEl, '重试', () => run(), true);
        if (st.error.detail) this.button(this.actsEl, '复制详情', () => plugin.copyText?.(`[${st.error.code}] ${st.error.detail}`));
      }
      if (st.state === 'done') {
        for (const w of st.warnings) this.msgEl.createDiv({ cls: 'lb-installer-warn', text: (w.id === 'ocr' ? '认图片里的字没装好，不影响同步：' : '') + w.text });
        if (st.warnings.length) this.button(this.actsEl, '重试没装好的', () => run());
        this.button(this.actsEl, '开始同步', () => { this.close(); }, true);
      }
      if (st.state === 'running') this.button(this.actsEl, '放到后台装', () => this.close());
      // 登录：读取组件装好、而且没在装别的才能扫（扫码会占「正在跑」的位，装 OCR 时扫会把它停掉）
      const readerOk = (st.steps.reader || {}).state === 'ok';
      const can = readerOk && !running() && !plugin.running;
      this.loginBtn?.setDisabled?.(!can);
      if (!this.loginState) this.login.setDesc(can ? '用手机小红书 App 扫一下；不扫也能装完，之后在设置里扫。' : '装好读取组件就能扫（装完会亮）。');
    }
    button(parent, text, fn, cta = false) {
      const b = parent.createEl('button', { cls: cta ? 'mod-cta' : '', text });
      b.onclick = fn;
      return b;
    }
    async doLogin() {
      this.loginBtn?.setDisabled?.(true);
      this.loginState = 'running'; this.login.setDesc('已经打开扫码窗口，用手机扫一下…');
      try {
        const r = await plugin.loginAccount(false);
        this.loginState = 'done';
        this.login.setDesc(r && r.ok !== false ? '✓ 已登录' : (r && r.message) || '没登录上，可以再点一次');
      } catch (e) { this.loginState = null; this.login.setDesc('没登录上：' + (e && e.message || e)); }
      this.paint();
    }
    onClose() {
      if (this.unsub) this.unsub();
      clearTimeout(this.timer); this.timer = null;
      const st = S();
      if (st.modal === this) st.modal = null;
      releaseGo();
    }
  }

  const ocrOn = () => { const o = plugin.settings && plugin.settings.ocr; return !(o && o.mode === 'off'); };
  async function setOcr(v) {
    const s = plugin.settings;
    if (!s.ocr || typeof s.ocr !== 'object') s.ocr = {};
    s.ocr.mode = v ? (s.ocr.mode && s.ocr.mode !== 'off' ? s.ocr.mode : 'local') : 'off';
    if (!s.setup || typeof s.setup !== 'object') s.setup = {};
    const cur = Array.isArray(s.setup.selected) ? s.setup.selected : ['core', 'reader', 'ocr'];
    s.setup.selected = v ? [...new Set([...cur, 'ocr'])] : cur.filter(x => x !== 'ocr' && x !== 'ai_vision');
    await plugin.saveSettings();
  }

  function open() {
    const st = S();
    if (st.modal) return st.modal;
    const m = new InstallerModal(plugin.app);
    m.open();
    return m;
  }
  // 启动时（新电脑没后端）：开窗口 + 开始装；装完、而且用户点了「开始同步」或关了窗口，才返回（之后接首次自动同步）
  async function openAndRun() {
    open();
    const res = await run();
    if (res && res.ok) await waitGo();
    return res;
  }

  return { open, run, openAndRun, state: S, pct, running,
    _internals: { overallPct, stepFraction, currentText, friendlyError, componentEvent, WEIGHTS } };
};
module.exports._internals = { overallPct, stepFraction, currentText, friendlyError, componentEvent, WEIGHTS, STEP_TEXT };

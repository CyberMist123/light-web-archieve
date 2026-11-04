// 1104（虚拟机实测）：首次启用时后端还在装，小红书账号卡查不了、停在「正在安装后端程序」——后端装好后它一直不变。
// 断言：后端缺失时那一次查不成 → 挂到懒人安装的重画上；后端能用了的那次重画 → 自动重查一次（浅查），画成真实状态；只重查一次。
// 不起真进程：child_process 是一碰就炸的桩，状态查询用替身。
'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const { makeDom } = require('./_fakedom.cjs');

const dom = makeDom();
const El = dom.document.createElement('div').constructor;
El.prototype.removeClass = function (...c) { this.classList.remove(...c); };
El.prototype.toggleClass = function (c, on) { this.classList.toggle(c, on); };
El.prototype.hide = function () { this.hidden = true; };
El.prototype.show = function () { this.hidden = false; };
class FakeSetting {
  constructor(container) {
    this.settingEl = container.createDiv({ cls: 'setting-item' });
    const info = this.settingEl.createDiv({ cls: 'setting-item-info' });
    this.nameEl = info.createDiv({ cls: 'setting-item-name' });
    this.descEl = info.createDiv({ cls: 'setting-item-description' });
    this.controlEl = this.settingEl.createDiv({ cls: 'setting-item-control' });
  }
  setClass(c) { this.settingEl.classList.add(c); return this; }
  addButton(cb) { const el = this.controlEl.createEl('button'); const b = { buttonEl: el, setButtonText(t) { el.setText(t); return b; }, setDisabled(v) { el.disabled = !!v; return b; }, onClick(f) { el.onclick = f; return b; } }; cb(b); return this; }
  addExtraButton(cb) { const el = this.controlEl.createEl('span'); const b = { extraSettingsEl: el, setIcon() { return b; }, setTooltip() { return b; }, onClick(f) { el.onclick = f; return b; } }; cb(b); return this; }
}
const OBS = { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Setting: FakeSetting, Notice: class {}, Menu: class {} };
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, setInterval, clearInterval, document: dom.document, URL, console, Buffer,
  require: n => n === 'obsidian' ? OBS : n === 'child_process' ? { spawn() { throw new Error('测试里不许 spawn 真进程'); } } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
const Plugin = context.module.exports;
const flush = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise(r => setTimeout(r, 0)); };

(async () => {
  const p = new Plugin();
  p.settings = {};
  p.taskListeners = new Set();   // 和 onload 一样是 Set（1104 虚拟机：卡片拿它当数组 push，整块渲染失败）
  let backend = 'missing';
  p.currentBackend = () => ({ mode: backend });
  const painters = new Set();
  p.homeUI = () => ({ onRepaint: fn => { painters.add(fn); return () => painters.delete(fn); } });
  p.stateRegistry = async () => ({});
  p.accountCacheStale = async () => true;
  p.xhsSyncing = () => false;
  const asked = [];
  p.accountStatus = async ({ deep }) => {
    asked.push(deep);
    if (backend === 'missing') throw new Error('正在安装后端程序，装好就能用');
    return { state: 'not_logged_in', code: '', message: '未登录', next_step: '点「登录」扫码' };
  };
  const host = dom.document.createElement('div');
  dom.document.body.appendChild(host);
  p.renderAccounts(host, { inCard: true });
  await flush();
  const text = () => host.textContent;
  assert.match(text(), /正在安装后端程序/);
  assert.equal(painters.size, 1, '查不了 → 挂到懒人安装的重画上');
  // 还在装：重画也不重查
  for (const f of [...painters]) f();
  await flush();
  assert.equal(asked.length, 1);
  // 后端装好了：下一次重画自动重查（浅查），画成真实状态，然后撤掉
  backend = 'managed';
  for (const f of [...painters]) f();
  await flush();
  assert.deepEqual(asked, [false, false], '重查一次，浅查');
  assert.match(text(), /点「登录」扫码/);
  assert.doesNotMatch(text(), /正在安装后端程序/);
  assert.equal(painters.size, 0, '只重查一次');
  assert.doesNotMatch(text(), /暂时读不到/, '卡片整块没渲染失败');
  assert.equal(p.taskListeners.size, 1, '跟着同步换状态的监听挂上了');
  // 同步开始：已登录的号 → 「同步中」
  p.accountStatus = async () => ({ state: 'ready', message: '已登录', account: '合成号' });
  await p.renderAccounts(host, { inCard: true }) && null;
  await flush();
  p.xhsSyncing = () => true;
  for (const f of [...p.taskListeners]) f();
  await flush();
  assert.match(text(), /同步中/);
  console.log('PASS account card 1104: stuck on 「正在安装后端程序」 rechecks once (shallow) when the backend becomes available');
})().catch(e => { console.error(e); process.exitCode = 1; });

// 1104 作者：小红书 / B 站账号的状态字只有三种——同步中 / 已登录 / 未登录；原因放说明行
{
  const assert3 = require('node:assert/strict');
  const ctx = { module: { exports: {} }, process, setTimeout, clearTimeout, console, URL, Buffer,
    require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Notice: class {}, Menu: class {} } : n === 'child_process' ? {} : require(n) };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), ctx);
  const tri = ctx.module.exports.accountTriState;
  const L = (r, o) => tri(r, o).label;
  assert3.equal(L({ state: 'ready' }), '已登录');
  assert3.equal(L({ state: 'syncing' }), '同步中');
  assert3.equal(L({ state: 'not_logged_in', code: 'NOT_LOGGED_IN' }), '未登录');
  assert3.equal(L({ state: 'expired' }), '未登录');
  assert3.equal(L({ state: 'error', code: 'NOT_LOGGED_IN' }), '未登录', '掉登录');
  assert3.equal(L({ state: 'error', action: 'login' }), '未登录', '登录没完成');
  assert3.equal(L({ state: 'captcha', code: 'CAPTCHA_REQUIRED', action: 'verify' }), '已登录', '要验证：号是登着的，原因进说明行');
  assert3.equal(L({ state: 'idle' }), '已登录', '读取服务没在跑：后端对从没登录过的电脑已经答了未登录，这里是登过的号');
  assert3.equal(L({ state: 'disconnected', code: 'DISCONNECTED' }), '已登录');
  assert3.equal(L({ state: 'unknown' }), '已登录');
  assert3.equal(L({ state: 'error' }), '未登录', '插件这头没问成、之前也没确认过');
  assert3.equal(L({ state: 'error' }, { knownIn: true }), '已登录', '之前确认过登着');
  assert3.equal(L({ state: 'checking' }, { prev: '已登录' }), '已登录', '检查中不另起一个状态字');
  assert3.equal(L({ state: 'checking' }), '');
  for (const s of ['ready', 'syncing', 'not_logged_in', 'expired', 'captcha', 'idle', 'disconnected', 'unknown', 'error', 'unconfigured'])
    assert3.ok(['已登录', '同步中', '未登录'].includes(L({ state: s })), s);
  console.log('PASS account states 1104: only 同步中 / 已登录 / 未登录 (reasons go to the hint line)');
}

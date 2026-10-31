// 1031 设置页① B 站卡（settings-v6.js biliCard）：登录两行状态、同步选项存 settings.bilibili（存失败拨回）、
//   「预估」跑 dry-run 显示条数 / 总时长 / 估计体积 / 估计耗时、「立即同步」走互斥任务（状态栏 + 能停止）后显示上次摘要。
// 不起真进程（CONVENTIONS §7.5）：runPy / run / spawnPy 都是替身，按命令回合成 JSON。
'use strict';
const assert = require('assert/strict');
const path = require('path');
const { makeDom } = require('./_fakedom.cjs');

const dom = makeDom();
const doc = dom.document;
const El = doc.createElement('div').constructor;
El.prototype.removeClass = function (...c) { this.classList.remove(...c); };
El.prototype.toggleClass = function (c, on) { this.classList.toggle(c, on); };

class Setting {
  constructor(container) {
    this.settingEl = container.createDiv({ cls: 'setting-item' });
    const info = this.settingEl.createDiv({ cls: 'setting-item-info' });
    this.nameEl = info.createDiv({ cls: 'setting-item-name' });
    this.descEl = info.createDiv({ cls: 'setting-item-description' });
    this.controlEl = this.settingEl.createDiv({ cls: 'setting-item-control' });
  }
  setName(n) { this.nameEl.setText(n); return this; }
  setDesc(d) { this.descEl.setText(d); return this; }
  addToggle(cb) {
    const el = this.controlEl.createEl('div', { cls: 'checkbox-container' });
    let change = null;
    const t = { toggleEl: el, getValue: () => !!el.checked, setValue(v) { const was = !!el.checked; el.checked = !!v; if (change && was !== !!v) change(!!v); return t; },
      setDisabled() { return t; }, onChange(f) { change = f; el.onchange = () => f(el.checked); return t; } };
    cb(t); return this;
  }
  addDropdown(cb) {
    const el = this.controlEl.createEl('select');
    const d = { selectEl: el, options: [], addOption(v, l) { d.options.push([v, l]); return d; }, setValue(v) { el.value = v; return d; },
      onChange(f) { el.onchange = () => f(el.value); return d; } };
    cb(d); return this;
  }
}

const flush = () => new Promise(r => setTimeout(r, 0));
const settle = async (n = 10) => { for (let i = 0; i < n; i++) await flush(); };

const STATUS = { ok: true, state: 'logged_in', mid_masked: '12***34', vip: true, message: '已登录',
  tv: { state: 'logged_out', detail: '电视端没登录' } };
const DRY = { ok: true, message: '预演：会下载 515 条', counts: { multi_p: 73, long: 11 },
  estimate: { count: 515, total_duration_s: 515 * 600, size_bytes: { low: 50 * 2 ** 30, high: 90 * 2 ** 30 }, eta_s: { low: 3600 * 20, high: 3600 * 50 },
    basis: { size: '已入库 487 条 1080p 的实测', speed: '单连接 130–430 KB/s（10-29 实测）× 2 路' }, workers: 2, estimated: true } };
const LAST0 = { ok: true, exists: true, state: 'interrupted', code: 'INTERRUPTED', downloaded: 340, failed: 9, multi_p: 73,
  details: { long: 11, invalid: 66 }, pending_note: 'Web/Bilibili/B站待选清单.md',
  message: '上次同步停在第 349/849 条：进程被结束了（关机 / 注销 / 点了「停止」/ Obsidian 关掉），没来得及收尾。已经下好的都在，再点「立即同步」只补没下的（停下时正在下的那条会重下）' };
const LAST1 = { ok: true, exists: true, state: 'done', downloaded: 515, failed: 0, multi_p: 73, details: { long: 11, invalid: 66 },
  pending_note: 'Web/Bilibili/B站待选清单.md', message: '同步完：新下 515 条、已在库 487 条、失败 0 条；多 P 的 73 条只记了链接' };

function makePlugin() {
  const p = { settings: {}, calls: [], runs: [], notices: [], saves: 0, saveFails: 0, running: null, runningProgress: '', listeners: new Set() };
  p.lbPath = x => x;
  p.app = { vault: { adapter: { read: async () => JSON.stringify({ state: 'running', started_at: new Date().toISOString(), progress: { done: 3, total: 515 } }) },
    getAbstractFileByPath: f => (f === LAST0.pending_note ? { path: f } : null) },
    workspace: { getLeaf: () => ({ openFile: f => { p.opened = f.path; } }) } };
  p.settingsPages = () => ({ LINKS: {} });
  p.saveSettings = async () => { if (p.saveFails > 0) { p.saveFails--; throw new Error('磁盘满了（合成）'); } p.saves++; };
  p.notify = (m, o = {}) => p.notices.push({ m, ...o });
  p.busyButton = (btn, t) => { const was = btn.textContent; btn.textContent = t; btn.disabled = true; return () => { btn.textContent = was; btn.disabled = false; }; };
  p.busyText = () => `正在${p.running}，完成后再点，或在底部状态栏停止`;
  p.onTask = cb => { p.listeners.add(cb); return () => p.listeners.delete(cb); };
  p.taskChanged = () => { for (const cb of p.listeners) cb(); };
  p.last = LAST0;
  p.runPy = async args => {
    p.calls.push(args.slice(2).join(' '));
    const sub = args.slice(2, 4).join(' ');
    if (sub === 'bilibili status') return { code: 0, json: STATUS };
    if (sub === 'bilibili last') return { code: 0, json: p.last };
    return { code: 0, json: { ok: true, message: 'ok' } };
  };
  p.run = async (args, label, slow, opts) => {
    p.runs.push({ args, label, quiet: opts && opts.quiet });
    p.running = label; p.taskChanged();
    await new Promise(r => setTimeout(r, 5));
    p.running = null; p.taskChanged();
    if (args.includes('--dry-run')) return { code: 0, json: DRY };
    p.last = LAST1;
    return { code: 0, json: { ...LAST1, ok: true, counts: { multi_p: 73 }, pending_note: LAST1.pending_note } };
  };
  return p;
}

(async () => {
  const plugin = makePlugin();
  const V = require(path.resolve('obsidian-plugins/link-brain-actions/settings-v6.js'))({ Setting }, plugin);
  const B = V.bili;

  // —— 纯逻辑：参数、状态句、预估句、摘要句 ——
  assert.deepEqual(B.BILI_DEFAULTS, { quality: 'max', maxDuration: 3600, danmaku: true, workers: 8, skipFolders: [] }, '默认最高画质、存弹幕、8 路、收藏夹全开（1031 她）');
  assert.deepEqual(B.biliSyncArgs(B.BILI_DEFAULTS), ['-m', 'link_brain', 'bilibili', 'sync', '--json', '--quality', 'max', '--max-duration', '3600', '--workers', '8']);
  assert.deepEqual(B.BILI_WORKERS.map(([v]) => v), ['1', '2', '3', '4', '5', '6', '7', '8'], '同时下几路 1–8');
  const a2 = B.biliSyncArgs({ quality: '720', maxDuration: 0, danmaku: false, workers: 19, tv: false, skipFolders: ['12', 'toview', '12', ''] }, { dryRun: true });
  assert.deepEqual(a2.slice(5), ['--quality', '720', '--max-duration', '0', '--workers', '8', '--no-danmaku', '--skip-folder', '12', '--skip-folder', 'toview', '--dry-run'], '不限 = 0；路数夹到 1–8；关掉的收藏夹去重后逐个 --skip-folder；无水印默认（不再有 --no-tv）');
  assert.equal(B.biliSyncArgs({ quality: 'bogus' })[6], 'max');
  assert.deepEqual(B.biliLoginLines(STATUS), ['网页登录：已登录（12***34） · 大会员', '电视端：没登录（可选；不扫也能下，走网页片源，可能带水印）']);
  assert.match(B.biliLoginLines({ state: 'logged_out', tv: { state: 'expired' } }).join('\n'), /没登录（读收藏夹要登录）[\s\S]*登录已失效/);
  assert.equal(B.estimateText(DRY.estimate), '要下 515 条 · 总时长 85 小时 50 分 · 约 50.0 GB–90.0 GB · 约 20 小时–50 小时');
  assert.equal(B.estimateText({ count: 0 }), '没有要下的：收藏里的视频都已经在库里了');
  const lt = B.lastText(LAST0);
  assert.match(lt.main, /停在第 349\/849 条.*关机/);
  assert.equal(lt.sub, '新下 340 条 · 失败 9 条 · 多 P 待选 73 条（另有 超时长 11、已失效 66 条只记在明细里，不用管）', '超时长 / 失效不算待处理');
  assert.equal(B.lastText(null).main, '还没同步过 B 站收藏');

  // —— 画卡：登录状态、选项、上次摘要 ——
  const tab = { stops: [], help() {} };
  const card = doc.createElement('div');
  doc.body.appendChild(card);
  B.biliCard(card, tab); B.biliSync(card, tab);   // 1031：登录在①、同步在②，这里画在一起测
  await settle();
  const text = () => card.textContent;
  // 1031 她「和小红书对齐、给一个（扫码）就行」：一行「昵称 / 号 · ✓ 已登录（大会员）」+ ⋯；电视端没登只给一句，不另放按钮
  assert.ok(card.querySelector('.lb-acct-row .lb-acct-who') && card.querySelector('.lb-bili-more'), '和小红书同一套账号行 + ⋯');
  assert.match(card.querySelector('.lb-acct-row').textContent, /12\*\*\*34 · ✓ 已登录（大会员）/);
  assert.match(text(), /重新扫码登录」扫一次能拿无水印片源/);
  assert.equal(card.querySelectorAll('.lb-acct-row button').filter(b => !b.hidden).length, 0, '网页端登着：没有大按钮');
  assert.match(text(), /上次：上次同步停在第 349\/849 条/, '被打断的那次：停在第几条、为什么');
  const btn = t => card.querySelectorAll('button').find(b => b.textContent === t);
  assert.equal(tab.stops.length, 1, '任务监听在设置页关掉时注销');
  btn('打开 B站待选清单').onclick();
  assert.equal(plugin.opened, LAST0.pending_note);

  // —— 选项改了就存；存失败拨回 ——
  const rowOf = n => card.querySelectorAll('.setting-item').find(r => r.querySelector('.setting-item-name').textContent === n);
  const sel = rowOf('画质').querySelector('select');
  assert.equal(sel.value, 'max');
  sel.value = '1080'; await sel.onchange(); await settle();
  assert.equal(plugin.settings.bilibili.quality, '1080');
  plugin.saveFails = 1;
  const dsel = rowOf('超过多长先不下').querySelector('select');
  dsel.value = '0'; await dsel.onchange(); await settle();
  assert.equal(plugin.settings.bilibili.maxDuration, 3600, '没存上：值退回');
  assert.equal(dsel.value, '3600', '下拉拨回');
  assert.match(plugin.notices.at(-1).m, /没保存上/);
  const tgl = rowOf('保存弹幕').querySelector('.checkbox-container');
  assert.equal(tgl.checked, true);
  tgl.checked = false; await tgl.onchange(); await settle();
  assert.equal(plugin.settings.bilibili.danmaku, false);

  // —— 预估 ——
  await btn('预估').onclick(); await settle();
  const est = plugin.runs.at(-1);
  assert.equal(est.label, '预估 B 站收藏');
  assert.ok(est.args.includes('--dry-run') && est.args.includes('--no-danmaku') && est.args[est.args.indexOf('--quality') + 1] === '1080');
  assert.match(card.querySelector('.lb-bili-estimate').textContent, /要下 515 条 · 总时长 85 小时 50 分 · 约 50\.0 GB–90\.0 GB/);
  assert.match(card.querySelector('.lb-bili-estimate').textContent, /都是估计：体积按已入库 487 条 1080p 的实测/);

  // —— 立即同步：互斥任务（状态栏那条叫「下载 B 站收藏」，不带「同步」二字），跑完提示 + 刷新上次摘要 ——
  await btn('立即同步').onclick(); await settle(20);
  const run = plugin.runs.at(-1);
  assert.equal(run.label, '下载 B 站收藏') ; assert.ok(!/同步/.test(run.label) && run.quiet && !run.args.includes('--dry-run'));
  const fin = plugin.notices.at(-1);
  assert.match(fin.m, /新下 515 条/); assert.equal(fin.kind, 'ok'); assert.equal(fin.actions[0].label, '打开待选清单');
  assert.match(text(), /上次：同步完：新下 515 条/);
  assert.ok(btn('停止').hidden, '跑完「停止」收起');

  // —— 正在跑别的：不起第二个 ——
  plugin.running = '同步收藏';
  const before = plugin.runs.length;
  await btn('立即同步').onclick();
  assert.equal(plugin.runs.length, before); assert.match(plugin.notices.at(-1).m, /正在同步收藏/);
  plugin.running = null;
  console.log('PASS settings ① B 站卡（1031）：默认最高画质 / 存弹幕；参数、状态句、预估句、摘要句；选项改了就存、存失败拨回；预估、立即同步走互斥任务并刷新上次摘要；超时长 / 失效不算待处理');
})().catch(e => { console.error(e); process.exit(1); });

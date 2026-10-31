// 1031 作者「所有的对话框都测试一下不同屏幕」：插件设置窗（六组 + ② 收藏与同步的小红书 / B 站切换、B 站登录卡、「挑选要同步的…」弹窗）、
// 插件弹窗（导入网址 / 改标题 / 每行几列 / 确认框 / 补齐附件 / 管理分类 / 未归类建议 / 按标签连播 / 问题 / 设口令 / 同步记录）、
// 目录页自己的小窗（存成选集 .lbc-dialog、自制菜单 .lbc-menu、导入时间菜单、编排条）在不同宽度下量：
//   ① 弹窗整个在视口里（超高的在里面滚，不跑出屏幕）；② 弹窗 / 内容区没有横向滚动；③ 没有元素伸出弹窗（或它所在的裁剪框）左右边；
//   ④ 按钮 / 标签没被省略号或 flex 挤截断；⑤ 弹窗左右内边距大致相等、窄屏（390）也 ≥ 12px。
// 宽度：窗口 390 / 700 / 900 / 1200 / 1600；设置窗按内容区宽 420 / 600 / 800 / 1000（照 l4_settings_ui）。亮色为主，暗色抽查。
// runPy 是替身（不起真进程，CONVENTIONS §7.5）；截图进 LWA_QA_DIR（dialogs-*.png）。LWA_DIALOG_REPORT=1 只打印问题不判红（排查用）。
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const shell = require('../_obsidian_shell.cjs');

const ROOT = 'obsidian-plugins/link-brain-actions';
const MODS = ['main', 'home-ui', 'remote-ui', 'schedule-ui', 'onboarding-ui', 'index-ui', 'skills-ui', 'usage-ui', 'settings-pages', 'settings-v6', 'provider-icons', 'lb-theme',
  'library-ui', 'problems-ui', 'report-ui', 'player-ui'];
const sources = Object.fromEntries(MODS.map(n => [n + '.js', fs.readFileSync(path.join(shell.ROOT, ROOT, n + '.js'), 'utf8')]));
const REPORT = !!process.env.LWA_DIALOG_REPORT;
const WIDTHS = [390, 700, 900, 1200, 1600];
const SETTING_WIDTHS = [420, 600, 800, 1000];

// ── 页面里：量一个框（弹窗 / 设置内容区）。返回问题清单（字符串） ──
function probe([rootSel, o]) {
  const root = typeof rootSel === 'string' ? document.querySelector(rootSel) : rootSel;
  if (!root) return ['没找到 ' + rootSel];
  const out = [], vw = innerWidth, vh = innerHeight;
  const R = e => e.getBoundingClientRect();
  const name = e => (e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : ''));
  const txt = e => (e.textContent || e.value || e.placeholder || '').trim().replace(/\s+/g, ' ').slice(0, 18);
  const shown = e => { if (!e.getClientRects().length) return false; const cs = getComputedStyle(e); return cs.visibility !== 'hidden' && cs.display !== 'contents'; };
  const rr = R(root), rcs = getComputedStyle(root);
  if (o.fit) {
    if (rr.left < -0.5 || rr.right > vw + 0.5) out.push(`弹窗横向出了视口 ${Math.round(rr.left)}..${Math.round(rr.right)} / ${vw}`);
    if (rr.top < -0.5 || rr.bottom > vh + 0.5) out.push(`弹窗竖向出了视口 ${Math.round(rr.top)}..${Math.round(rr.bottom)} / ${vh}`);
  }
  for (const s of [root, ...root.querySelectorAll(o.scrollers || '.modal-content')]) {
    if (s && shown(s) && s.scrollWidth > s.clientWidth + 1) out.push(`横向滚动 ${name(s)} ${s.scrollWidth}>${s.clientWidth}`);
  }
  const L = rr.left + parseFloat(rcs.borderLeftWidth) + (o.inner ? parseFloat(rcs.paddingLeft) : 0);
  const Rt = rr.right - parseFloat(rcs.borderRightWidth) - (o.inner ? parseFloat(rcs.paddingRight) : 0);
  const skip = o.skip ? [...root.querySelectorAll(o.skip)] : [];
  const okEllipsis = o.okEllipsis ? [...root.querySelectorAll(o.okEllipsis)] : [];
  for (const e of root.querySelectorAll('*')) {
    if (!shown(e) || skip.some(s => s.contains(e))) continue;
    const b = R(e); if (b.width < 1 || b.height < 1) continue;
    const cs = getComputedStyle(e);
    if (cs.position === 'fixed') continue;
    // 最近一个会裁剪的祖先（在 root 里面）：伸出去的部分被它裁掉 → 以它为界
    let clip = null;
    for (let a = e.parentElement; a && a !== root; a = a.parentElement) { if (getComputedStyle(a).overflowX !== 'visible') { clip = a; break; } }
    const cb = clip ? R(clip) : { left: L, right: Rt };
    const over = Math.max(b.right - cb.right, cb.left - b.left);
    if (over > 1) out.push(`出界 ${name(e)} ${over > 0 ? '+' + Math.round(over) : ''}「${txt(e)}」${clip ? ' 在 ' + name(clip) + ' 里' : ''}`);
    // 短标签（≤ 8 个字、没有子元素）被挤成好几行：「B 站」竖着排、按钮字折行
    const t = (e.textContent || '').trim();
    if (!e.children.length && t && t.length <= 8) {
      const rg = document.createRange(); rg.selectNodeContents(e);
      const tops = new Set([...rg.getClientRects()].filter(r => r.width > 0).map(r => Math.round(r.top / 4)));
      if (tops.size > 1) out.push(`短标签折成 ${tops.size} 行 ${name(e)}「${t}」`);
    }
    if (/^(INPUT|TEXTAREA|SELECT|svg|path|IMG|CANVAS|VIDEO)$/i.test(e.tagName) || cs.display === 'inline') continue;
    if (e.scrollWidth > e.clientWidth + 1 && !okEllipsis.some(s => s === e)) {
      const scrolls = /auto|scroll/.test(cs.overflowX);
      if (scrolls) out.push(`内部横向滚动 ${name(e)} ${e.scrollWidth}>${e.clientWidth}「${txt(e)}」`);
      else if (cs.textOverflow === 'ellipsis' || cs.overflowX !== 'visible' || /flex|grid/.test(cs.display) || e.tagName === 'BUTTON') out.push(`截断 / 挤出 ${name(e)} ${e.scrollWidth}>${e.clientWidth}「${txt(e)}」`);
    }
  }
  if (o.pad) {
    const inner = typeof o.pad === 'string' ? root.querySelector(o.pad) : null;
    let pl, pr;
    if (inner) { const ib = R(inner); pl = ib.left - rr.left; pr = rr.right - ib.right; }
    else { pl = parseFloat(rcs.paddingLeft); pr = parseFloat(rcs.paddingRight); }
    if (Math.abs(pl - pr) > (o.padTol || 6)) out.push(`左右内边距不等 ${Math.round(pl)} / ${Math.round(pr)}`);
    if (Math.min(pl, pr) < (o.padMin || 12) - 0.5) out.push(`内边距太小 ${Math.round(pl)} / ${Math.round(pr)}`);
  }
  return [...new Set(out)];
}

// ── 页面里：装插件（main.js 等源码 + require 替身 + runPy 替身），照 tests/ui/l4_settings_ui.cjs ──
function installPlugin([sources, spec]) {
  const modules = {};
  const require = name => {
    if (name === 'obsidian') return window.obsidian;
    if (name === 'path') return { join: (...p) => p.join('/'), basename: v => v.split('/').at(-1), parse: v => ({ name: v.split('/').at(-1).replace(/\.[^.]+$/, '') }) };
    if (name === 'os') return { homedir: () => '/synthetic-home', tmpdir: () => '/tmp' };
    if (name === 'fs') return { existsSync: () => false, statSync() { throw new Error('ENOENT'); } };
    if (name === 'fs/promises') return { readdir: async () => [], stat: async () => ({ size: 0, mtimeMs: 0 }) };
    if (name === 'child_process') return { spawn() { throw new Error('No real process allowed'); } };
    if (name === 'electron') return { webUtils: {}, shell: { openExternal() {}, openPath() {} } };
    const file = name.split('/').at(-1);
    if (!sources[file]) throw Object.assign(new Error('no module ' + name), { code: 'MODULE_NOT_FOUND' });
    if (!modules[file]) {
      const module = { exports: {} }; modules[file] = module;
      new Function('require', 'module', 'process', sources[file] + (file === 'main.js'
        ? '\nmodule.exports.Tab=LinkBrainSettingTab;module.exports.merge=mergeSettings;module.exports.ImportModal=ImportModal;module.exports.CatalogTitleModal=CatalogTitleModal;module.exports.ColumnsModal=ColumnsModal;module.exports.ConfirmModal=ConfirmModal;' : ''))(require, module, { env: {}, platform: 'win32' });
    }
    return modules[file].exports;
  };
  const TP = window.obsidian.ToggleComponent.prototype;
  TP.setValue = function (v) { const changed = this._get() !== !!v; this._set(v); if (changed && this._change) this._change(!!v); return this; };
  const LONG = '一个特别特别长的收藏夹名字用来试窄屏会不会把开关挤出去';
  const dates = Array.from({ length: 30 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - 29 + i); return d.toISOString().slice(0, 10); });
  const f = o => ({ calls: 1, failed: 0, items: 0, in: 0, out: 0, sec: 0, cost: 0, free: 0, unpriced: 0, ...o });
  const reply = args => {
    const sub = args.slice(2).join(' ');
    if (sub.startsWith('setup plan')) return { ok: true, components: [{ id: 'core', name: '归档·同步·浏览·关键词搜索', required: true, status: 'ready', depends: [] }], presets: { light: ['core'] } };
    if (sub.startsWith('setup estimate')) return { ok: true, items: [] };
    if (sub.startsWith('comments --fill-status')) return { ok: true, pending: 190, missing: 5800, stuck: 0, running: true };
    if (sub.startsWith('connect status')) return { ok: true, clients: {}, json: '{}', apps: [{ id: 'claude-code', name: 'Claude Code', installed: true, oneclick: true, version: '2.1.302', connected: true },
      { id: 'codex', name: 'Codex', installed: true, oneclick: true, version: '0.146.0', connected: false }], not_installed: ['Pi'] };
    if (sub.startsWith('remote status')) return { ok: true, state: 'running', message: '运行中（127.0.0.1:18071）', auth: { passphrase_set: true, passphrase_copyable: true, clients: [{ id: 'c1', name: 'claude.ai', connected_at: '2026-10-09T21:30:00' }], personal: [] }, recent: [] };
    if (sub.startsWith('sync-schedule')) return { task: 'LinkBrainNightly', freq: 'daily', time: '04:00', enabled: true, summary: '每天 04:00', rules: [{ kind: 'daily', times: ['04:00'] }] };
    if (sub.startsWith('usage --table')) return { ok: true, ai_table: { cli: [] } };
    if (sub.startsWith('usage')) {
      const win = { total: f({ calls: 558, cost: 2.85 }), providers: { aliyun: f({ calls: 472, cost: 1.42 }) }, models: {}, features: { vision: f({ calls: 412, cost: 0.86 }) }, unpriced_models: [] };
      return { ok: true, links: {}, keys: {}, budget: { daily_yuan: 3, spent_today: 0.83, day: dates[29], over: false },
        summary: { as_of: dates[29], features: { vision: '识图' }, windows: { today: win, '7d': win, '30d': win }, series: { dates, providers: { aliyun: dates.map(() => 0.1) }, models: {}, features: {} }, recent: [], recent_limit: 200, month: {} },
        features: [{ id: 'vision', name: '识图', on: true, state: 'ok', chain: [{ label: 'Gemini', provider: 'google' }] }] };
    }
    if (sub.startsWith('bilibili status')) return { ok: true, state: 'logged_in', mid_masked: '12***34', vip: true, tv: { state: 'logged_out' }, message: '已登录' };
    if (sub.startsWith('bilibili last')) return { ok: true, exists: true, message: '上次同步完：新下 12 条，失败 1 条（2026-10-31 18:20）', downloaded: 12, failed: 1, multi_p: 2, details: { long: 3, invalid: 1 }, pending_note: 'B站待选清单.md' };
    if (sub.startsWith('bilibili pick')) return { ok: true, empty: false, message: '收藏夹 4 个',
      folders: [{ id: 'toview', title: '稍后再看', media_count: 4, private: true, kind: 'toview', scanned: true }, { id: '11', title: '音乐', media_count: 30, kind: 'folder', scanned: true },
        { id: '12', title: LONG, media_count: 1234, private: true, kind: 'folder', scanned: false }, { id: '13', title: 'Lecture_Notes_Machine_Learning_Advanced_2026', media_count: 2, kind: 'folder', scanned: true }],
      long: { total: 3, chosen: 1, max_duration: 3600, items: [
        { bvid: 'BV1a', title: '【4K 纪录片】一个非常非常长的标题，看看窄屏下会不会把勾选框挤歪或者伸出弹窗右边', duration: 7200, duration_text: '2:00:00', upper: 'UP 主名字也很长很长很长', folders: ['音乐', LONG], folder_ids: ['11', '12'], chosen: false },
        { bvid: 'BV1b', title: 'Lecture_01_Introduction_to_Something_Really_Long_Without_Spaces_At_All', duration: 5000, duration_text: '1:23:20', upper: 'UP', folders: ['稍后再看'], folder_ids: ['toview'], chosen: true },
        { bvid: 'BV1c', title: '短名', duration: 39000, duration_text: '10:50:00', upper: 'UP', folders: ['音乐'], folder_ids: ['11'], chosen: false }] } };
    if (sub.startsWith('problems list')) return { ok: true, summary: {}, problems: [
      { key: 'k1', ts: new Date().toISOString(), step: 'fetch', category: 'fetch', group: 'gave_up', title: '一篇标题特别长特别长特别长特别长特别长的收藏帖子看看会不会出界', label: '评论没拿全', hover: '读取服务返回空页：可能是网络慢或者被限频，过一会儿再试', code: 'FETCH.EMPTY', item_id: 'xhs-1', repairable: true, dismissable: true, count: 3 },
      { key: 'k2', ts: new Date().toISOString(), step: 'login', category: 'account', group: 'needs_you', title: '小红书登录', label: '要你扫码', hover: '登录过期了', code: 'NEEDS_HUMAN.NOT_LOGGED_IN', action: 'login',
        items: [{ item_id: 'xhs-2', title: 'Lecture_Notes_Machine_Learning_Advanced_2026_Without_Spaces' }, { item_id: 'xhs-3', title: '第二篇' }] },
      { key: 'k3', ts: new Date().toISOString(), step: 'ai.vision', category: 'api', group: 'auto', title: '识图', label: '限频，等会儿自动重试', code: 'AUTO.RATE_LIMIT', repairable: true, repair_note: '试过换 key：两把 key 都在限频；明早 04:00 自动再试', repair_state: 'failed' }] };
    if (sub.startsWith('synclog list')) return { ok: true, backlog: { favorites_total: 6400, archived: 5800, deferred: 600, days_left: 4 }, runs: [
      { run_id: 'r1', trigger: 'nightly', started_at: new Date().toISOString(), finished_at: new Date().toISOString(), new: 3, counts: { note: { ok: 3, failed: 1 }, attachment: { ok: 2, failed: 0 } },
        items: [{ kind: 'note', id: 'x1', title: '一篇标题特别长特别长特别长特别长特别长的收藏帖子看看会不会出界', note: 'a.md', ok: false, reason: '读取服务返回空页：可能是网络慢或者被限频' }, { kind: 'attachment', id: 'x2', title: 'Lecture_Notes_Machine_Learning_Advanced_2026_Without_Spaces.pdf', ok: true }],
        errors: [{ step: 'fetch', reason: '一篇正文没拿到', code: 'FETCH.EMPTY' }] },
      { run_id: 'r2', trigger: 'manual', started_at: new Date(Date.now() - 864e5).toISOString(), finished_at: new Date(Date.now() - 864e5).toISOString(), new: 0, counts: {}, items: [], errors: [] }] };
    if (sub.startsWith('index suggest')) return { ok: true, message: '找到 2 条建议', suggestions: [
      { id: 's1', action: 'new', name: '空气炸锅', path: '做饭/厨具/小家电', tags: ['空气炸锅', '烤箱', '懒人菜'], examples: ['一篇很长很长的帖子标题', '另一篇也很长很长的帖子标题'], gain: 12, why: '这些帖子都在讲空气炸锅' },
      { id: 's2', action: 'add_tags', path: '穿搭', tags: ['Lecture_Notes_Machine_Learning_Advanced_2026'], examples: [], gain: 3 }] };
    if (sub.startsWith('playlist --tags')) return { ok: true, tags: [{ tag: '做饭', count: 30, playable: 28 }, { tag: '一个特别长特别长特别长特别长的标签名字看看会怎样', count: 12, playable: 2 }, { tag: 'Lecture_Notes_Machine_Learning_Advanced_2026', count: 3, playable: 3 }] };
    return { ok: true };
  };
  const Plugin = require('main.js');
  const files = { '_archive/catalog-data.json': '{"items":[]}', '_archive/problems-summary.json': JSON.stringify({ needs_human: 0, auto: 1, gave_up: 0, sync: { state: 'ready', last_success: new Date().toISOString() } }) };
  const app = { workspace: { trigger() {}, on() { return {}; }, offref() {}, getActiveFile: () => null, getLeaf: () => ({ openFile: async () => {} }) },
    vault: { adapter: { getBasePath: () => '/synthetic-vault', exists: async p => p in files, read: async p => { if (!(p in files)) throw new Error('ENOENT'); return files[p]; }, list: async () => ({ folders: [], files: [] }) },
      getAllLoadedFiles: () => [], getMarkdownFiles: () => [], getAbstractFileByPath: () => null },
    metadataCache: { getFileCache: () => ({}) } };
  const plugin = new Plugin(app, { id: 'link-brain-actions', dir: '' });
  plugin.settings = Plugin.merge({ setup: { selected: ['core'], aiSynced: true }, voice: { capsLock: false }, asrAI: { mode: 'off' }, onboarding: { guideDone: true } });
  plugin.settings.remote = { enabled: !!spec.remoteOn, domain: spec.remoteOn ? 'https://lwa.example.com' : '', port: 18071, folders: ['@xhs'] };
  plugin.lbPath = x => x; plugin.manifest = { id: 'link-brain-actions', dir: '' };
  plugin.loadData = async () => JSON.parse(JSON.stringify(plugin.settings));
  plugin.saveSettings = async () => {};
  plugin.renderSetupHints = () => {};
  plugin.capsWriterDir = () => null;
  plugin.renderAccounts = (c, opts) => { const s = new window.obsidian.Setting(c).setName(opts && opts.inCard ? 'momo · ✓ 已登录' : '小红书 · momo · ✓ 已登录'); s.settingEl.classList.add('lb-acct-row'); s.addButton(b => b.setButtonText('换个账号')); };
  plugin.runPy = async args => ({ code: 0, json: reply(args) });
  plugin.indexUI = require('index-ui.js')(window.obsidian, plugin); plugin.indexUI.attach?.();
  const sb = document.querySelector('.status-bar') || document.body.appendChild(document.createElement('div'));
  plugin.taskStatusEl = sb.createDiv({ cls: 'status-bar-item' });
  plugin.onboardingUI = () => require('onboarding-ui.js')(window.obsidian, plugin);
  plugin.usageUI = () => require('usage-ui.js')(window.obsidian, plugin);
  plugin.remoteUI = require('remote-ui.js')(window.obsidian, plugin);
  plugin.playerUI = require('player-ui.js')(window.obsidian, plugin);
  plugin.homeUI().runAll = async () => ({ ok: true });
  window.L = { plugin, Plugin, require };
}

// 外壳（冻结）的手写子集缺几条量尺寸要用的 Obsidian 规则，这里照 1.14.5 app.css 补上（只补和宽度有关的）：
//   假 setIcon 画的 <svg> 没宽高会按 300×150 撑开（.svg-icon 用 --icon-size）；设置行名字单行省略号、行首元素 16px 右边距；开关 40×22；
//   按钮不折行；设置内容区最宽 700px 居中（--setting-group-max-width，所以设置窗再宽，两张并排卡也只有 ~220px）。
// 真 app.css 可用 LWA_OBSIDIAN_APP_CSS 垫进来（tests/tools/obsidian_css.py 抽，绝不进仓），外壳会放在最前面。
const OBS_CSS = 'body{--icon-size:18px;}.svg-icon{width:var(--icon-size);height:var(--icon-size);}'
  + '.setting-item-info{min-width:0;}.setting-item-name{text-overflow:ellipsis;overflow:hidden;}.setting-item>*:first-child{margin-inline-end:var(--size-4-4);}.setting-item>*:last-child{margin-inline-end:0;}'
  + '.checkbox-container{display:inline-block;flex-shrink:0;width:40px;height:22px;border-radius:11px;background:var(--background-modifier-border);}.checkbox-container.is-enabled{background:var(--interactive-accent);}'
  + 'button{white-space:nowrap;}.modal.mod-settings .vertical-tab-content{padding-inline:max(var(--size-4-8), calc((100% - 700px) / 2));}';
const extraCss = page => page.addStyleTag({ content: OBS_CSS });   // 设了 LWA_OBSIDIAN_APP_CSS 时外壳自己把真 app.css 垫在最前面
const shot = (page, name) => page.screenshot({ path: path.join(shell.QA_DIR, name + '.png') });

async function settingsPage(browser, contentWidth, theme = 'light') {
  const page = await browser.newPage({ viewport: { width: contentWidth + 200 + 64 + 120, height: 1000 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await shell.settings(page, { theme, contentWidth });
  await extraCss(page);
  await page.evaluate(installPlugin, [sources, {}]);
  await page.evaluate(() => { const tab = new window.L.Plugin.Tab(window.L.plugin.app, window.L.plugin); tab.containerEl = document.querySelector('.vertical-tab-content'); window.L.plugin.settingTab = tab; tab.display(); });
  await page.waitForFunction(() => document.querySelector('.lb-group[data-section="g-sync"]') && /已登录/.test(document.querySelector('[data-section="bili-login"]')?.textContent || ''));
  await page.waitForTimeout(250);
  return { page, errors };
}
async function modalPage(browser, width, theme = 'light') {
  const page = await browser.newPage({ viewport: { width, height: 860 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await shell.setup(page, { host: 'page-reading', theme });
  await extraCss(page);
  await page.evaluate(installPlugin, [sources, {}]);
  return { page, errors };
}
// 弹窗：怎么开 + 量哪个框
const MODALS = [
  ['import', '导入网址', () => new (window.L.require('main.js').ImportModal)(window.L.plugin).open()],
  ['title', '改标题', () => new (window.L.require('main.js').CatalogTitleModal)(window.L.plugin).open()],
  ['columns', '每行几列', () => new (window.L.require('main.js').ColumnsModal)(window.L.plugin).open()],
  ['confirm', '确认框', () => new (window.L.require('main.js').ConfirmModal)(window.L.plugin.app, { title: '退出 B 站登录？', body: '只删这台电脑上存的登录态（网页端和电视端），已下载的视频不动。', ok: '退出', danger: true }, () => {}).open()],
  ['attach', '补齐附件', () => window.L.plugin.openAttachments([{ id: 'x1', title: '一篇标题特别长特别长特别长特别长特别长的收藏帖子看看会不会出界', url: 'https://example.com/a',
    attachment_files: [{ name: 'Lecture_Notes_Machine_Learning_Advanced_2026_Without_Spaces.pdf', doc_id: 'd1' }], attachment_reason: '附件要登录网页版才能下' }], null)],
  ['cats', '管理分类', () => window.L.plugin.openCategories([{ name: '做饭', keywords: ['菜谱', '空气炸锅', '烘焙'] }, { name: '穿搭灵感', keywords: [] }], '做饭', null)],
  ['suggest', '未归类建议', () => window.L.plugin.indexUI.openIndexSuggestions()],
  ['tagpick', '按标签连播', () => window.L.plugin.playerUI.openTagPicker({})],
  ['problems', '问题', () => window.L.plugin.openProblems()],
  ['synclog', '同步记录', () => window.L.plugin.reportUI().open()],
  ['bilipick', 'B 站挑选', () => window.L.plugin.settingsV6().bili.biliPicker({})],
  ['passphrase', '设口令（TextModal）', async () => {
    const box = document.body.createDiv({ cls: 'lb-offscreen' }); box.style.cssText = 'position:absolute;left:-9999px;width:800px';
    window.L.plugin.settings.remote.enabled = true;
    window.L.plugin.remoteUI.renderConnect(box, () => {}, null, { part: 'web' });
    for (let i = 0; i < 40 && ![...box.querySelectorAll('button')].some(b => /自己改一个|自己设一个/.test(b.textContent)); i++) await new Promise(r => setTimeout(r, 25));
    [...box.querySelectorAll('button')].find(b => /自己改一个|自己设一个/.test(b.textContent)).click();
  }],
];

module.exports = { probe, installPlugin, settingsPage, modalPage, MODALS, sources };
if (require.main === module) (async () => {
  shell.requirePlaywright();
  fs.mkdirSync(shell.QA_DIR, { recursive: true });
  const browser = await shell.launch();
  const problems = [], shots = [], checked = [];
  const note = (tag, list) => { checked.push(tag); for (const p of list) problems.push(`${tag}：${p}`); };
  try {
    // ① 设置窗：整页（六组），② 切到 B 站；B 站登录卡；挑选弹窗（从设置页按钮开）
    for (const theme of ['light', 'dark']) for (const cw of theme === 'light' ? SETTING_WIDTHS : [420]) {
      const { page, errors } = await settingsPage(browser, cw, theme);
      const opt = { scrollers: '.lb-tab-pane', okEllipsis: '.lb-anchors', skip: '.lb-anchors' };
      note(`设置窗 ${theme} ${cw} 整页`, await page.evaluate(probe, ['.vertical-tab-content', { ...opt, inner: true }]));
      note(`设置窗 ${theme} ${cw} 锚点条`, await page.evaluate(probe, ['.lb-anchors', {}]).then(l => l.filter(x => !/内部横向滚动|横向滚动 nav/.test(x))));
      await page.evaluate(() => document.querySelector('.lb-plat-tab[data-platform="bilibili"]').click());
      await page.waitForFunction(() => /上次/.test(document.querySelector('[data-section="bili-last"]')?.textContent || ''));
      note(`设置窗 ${theme} ${cw} ②B 站`, await page.evaluate(probe, ['[data-section="g-sync"]', {}]));
      note(`设置窗 ${theme} ${cw} B 站登录卡`, await page.evaluate(probe, ['[data-section="account-bili"]', { inner: true }]));
      await page.evaluate(() => { const g = document.querySelector('[data-section="g-sync"]'); g.scrollIntoView(); });
      await page.waitForTimeout(80);
      shots.push(path.join(shell.QA_DIR, `dialogs-settings-sync-bili-${theme}-${cw}.png`)); await shot(page, `dialogs-settings-sync-bili-${theme}-${cw}`);
      await page.evaluate(() => document.querySelector('[data-section="account-bili"]').scrollIntoView());
      await page.waitForTimeout(60);
      await shot(page, `dialogs-settings-account-${theme}-${cw}`);
      assert.deepEqual(errors, [], `设置窗 ${cw}：页面报错`);
      await page.close();
    }
    // ② 插件弹窗 + 挑选弹窗：窗口宽 390–1600
    for (const theme of ['light', 'dark']) for (const w of theme === 'light' ? WIDTHS : [390, 1200]) {
      const { page, errors } = await modalPage(browser, w, theme);
      for (const [id, label, open] of MODALS) {
        await page.evaluate(() => document.querySelectorAll('.modal-container').forEach(e => e.remove()));
        await page.evaluate(open);
        await page.waitForSelector('.modal-container .modal');
        await page.waitForTimeout(id === 'problems' || id === 'synclog' || id === 'suggest' || id === 'tagpick' || id === 'bilipick' ? 200 : 60);
        const list = await page.evaluate(probe, ['.modal-container .modal', { fit: true, pad: true, padMin: w <= 400 ? 12 : 16, skip: '.modal-close-button', okEllipsis: '.lb-problem-item-title' }]);
        note(`${label} ${theme} ${w}`, list);
        if (w === 390 || w === 1200 || list.length) await shot(page, `dialogs-modal-${id}-${theme}-${w}`);
      }
      assert.deepEqual(errors, [], `弹窗 ${w}：页面报错`);
      await page.close();
    }
    // ③ 目录页：存成选集小窗（.lbc-dialog）、自制菜单（.lbc-menu：插件没给 showMenu 时）、导入时间菜单、编排条
    const data = shell.makeCatalogData({ n: 30 });
    data.items[0].title = '一篇标题特别长特别长特别长特别长特别长特别长特别长特别长的收藏帖子看看会不会出界';
    for (const theme of ['light', 'dark']) for (const w of theme === 'light' ? WIDTHS : [390, 1200]) {
      const page = await browser.newPage({ viewport: { width: w, height: 860 } });
      const S = await shell.page(page, { host: 'page-reading', kind: 'catalog', theme, data, plugin: { settings: { hiddenCats: [] } }, pluginInit: p => { delete p.showMenu; } });
      await extraCss(page);
      await S.settle(60);
      // 存成选集：卡片右键 →「给 AI（存成选集）」
      await page.click('.lbc-card', { button: 'right' }); await S.settle();
      const hasMenu = await page.evaluate(() => !!document.querySelector('.lbc-menu'));
      if (hasMenu) {
        note(`目录页 卡片右键菜单 ${theme} ${w}`, await page.evaluate(probe, ['.lbc-menu', { fit: true }]));
        if (w === 390) await shot(page, `dialogs-catalog-ctxmenu-${theme}-${w}`);
        await page.evaluate(() => [...document.querySelectorAll('.lbc-menu .lbc-menu-item')].find(b => /存成选集/.test(b.textContent))?.click()); await S.settle();
      }
      if (await page.evaluate(() => !!document.querySelector('.lbc-dialog'))) {
        note(`目录页 存成选集 ${theme} ${w}`, await page.evaluate(probe, ['.lbc-dialog', { fit: true, pad: true }]));
        if (w === 390 || w === 1200) await shot(page, `dialogs-catalog-dialog-${theme}-${w}`);
        await page.evaluate(() => document.querySelectorAll('.lbc-dialog-back').forEach(e => e.remove()));
      } else problems.push(`目录页 ${w}：存成选集小窗没打开`);
      // 管理菜单（自制）
      if (await page.isVisible('.lbc-manage')) {
        await page.click('.lbc-manage'); await S.settle();
        note(`目录页 管理菜单 ${theme} ${w}`, await page.evaluate(probe, ['.lbc-menu', { fit: true }]));
        if (w === 390) await shot(page, `dialogs-catalog-manage-${theme}-${w}`);
        await page.keyboard.press('Escape'); await S.settle();
      }
      // 导入时间菜单
      if (await page.isVisible('.lbc-time')) {
        await page.click('.lbc-time'); await S.settle();
        note(`目录页 时间菜单 ${theme} ${w}`, await page.evaluate(probe, ['.lbc-time-menu', { fit: true }]));
        if (w === 390) await shot(page, `dialogs-catalog-time-${theme}-${w}`);
        await page.keyboard.press('Escape'); await S.settle();
      }
      // 编排条
      if (await page.isVisible('.lbc-arrange')) {
        await page.click('.lbc-arrange'); await S.settle(80);
        note(`目录页 编排条 ${theme} ${w}`, await page.evaluate(probe, ['.lbc-arrange-tray', {}]));
        if (w === 390 || w === 900) await shot(page, `dialogs-catalog-arrange-${theme}-${w}`);
      }
      const errs = await S.pageErrors();
      assert.deepEqual(errs, [], `目录页 ${w}：页面报错`);
      await page.close();
    }
  } finally { await browser.close(); }
  if (REPORT) { console.log('检查过：\n  ' + checked.join('\n  ') + '\n问题（' + problems.length + '）：\n  ' + problems.join('\n  ')); return; }
  assert.deepEqual(problems, [], '弹窗尺寸问题：\n' + problems.join('\n'));
  console.log(`PASS dialogs_sizes_ui 1031：${checked.length} 个「弹窗 × 宽度」都在视口里、没有横向滚动 / 出界 / 截断、左右内边距相等。截图：${shell.QA_DIR}`);
})().catch(e => { console.error(e); process.exit(1); });

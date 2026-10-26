'use strict';
// 1027 设置页六组（design-1027/prototype.html「设置」第三版）在真 Chromium + Obsidian 外壳（settings-modal）里，亮 / 暗 / 第三方主题：
//   ① 左边锚点 + 一页六组：账号登录 · 收藏与同步 · 目录与批注 · 高级功能 · CLI 与外接 MCP · 修复；组底「＋ 更多」默认收着
//   ② ④ 一项一行带线条图标；AI 控制台一行（今天 · 本月 · 每天最多花），点开左右两栏：左折线固定 190px 高、不撑出去，右三种看法 + 小表
//   ③ key 用不了：一句 + 去充值 + 换 key（落到「更多 → 接口与密钥」唯一那个粘 key 的框，焦点进去）
//   ④ ⑤ 电脑端 / 网页端两张卡并排；接入 Codex 一个开关；网页端的开关在卡片标题上
//   ⑤ 窄（设置内容区 420px）：锚点变横排、两栏变一栏、页面不横向滚动
//   ⑥ 没有术语、最多一个主按钮、不框套框、行不自带底色；读不到的块：一句人话 + 重试，原始报错折在「详情」
//   ⑦ 库里还没收藏：首次设置（欢迎 → 自定义四步 → 完成变六组页）
// runPy 是替身（不起真进程）；截图落盘留档（LWA_QA_DIR）。
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const shell = require('../_obsidian_shell.cjs');
const root = 'obsidian-plugins/link-brain-actions';
const sources = Object.fromEntries(['main', 'home-ui', 'remote-ui', 'schedule-ui', 'onboarding-ui', 'index-ui', 'skills-ui', 'usage-ui', 'settings-pages', 'settings-v6', 'provider-icons', 'lb-theme'].map(name =>
  [name + '.js', fs.readFileSync(path.join(root, name + '.js'), 'utf8')]));
// 新手主界面（「更多」收着时）上不该看到的词（她 1010 点名的术语；要留的旁边有人话解释）
const JARGON = ['OAuth', 'Bearer', 'Authorization', 'launchd', 'systemd', '标准输入', '标准输出', '扩检索词', '归档摘要模型', '认领', '令牌', '没画上', '读不到状态：', '读不到功能清单：'];

async function open(browser, theme, { failRemote = false, guide = false, width = 800, remoteOn = false } = {}) {
  const page = await browser.newPage({ viewport: { width: width + 500, height: 1400 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  page.on('console', m => { if (m.type() === 'error') console.log('[console]', m.text()); });
  await shell.settings(page, { theme, contentWidth: width });
  if (process.env.LWA_OBSIDIAN_CSS && fs.existsSync(process.env.LWA_OBSIDIAN_CSS)) await page.addStyleTag({ path: process.env.LWA_OBSIDIAN_CSS });
  await page.evaluate(([sources, failRemote, guide, remoteOn]) => {
    const modules = {};
    const require = name => {
      if (name === 'obsidian') return window.obsidian;
      if (name === 'path') return { join: (...parts) => parts.join('/'), basename: value => value.split('/').at(-1) };
      if (name === 'os') return { homedir: () => '/synthetic-home' };
      if (name === 'fs') return { existsSync: () => false };
      if (name === 'child_process') return { spawn() { throw new Error('No real process allowed'); } };
      if (name === 'electron') throw Object.assign(new Error('no electron'), { code: 'MODULE_NOT_FOUND' });
      const file = name.split('/').at(-1);
      if (!modules[file]) {
        const module = { exports: {} }; modules[file] = module;
        new Function('require', 'module', 'process', sources[file] + (file === 'main.js'
          ? '\nmodule.exports.Tab=LinkBrainSettingTab;module.exports.merge=mergeSettings;' : ''))(require, module, { env: {}, platform: 'win32' });
      }
      return modules[file].exports;
    };
    // 外壳的开关照 Obsidian 1.14.4：setValue 值变了会再触发 onChange（app.js 里 ToggleComponent.setValue 调 changeCallback）
    const TP = window.obsidian.ToggleComponent.prototype;
    TP.setValue = function (v) { const changed = this._get() !== !!v; this._set(v); if (changed && this._change) this._change(!!v); return this; };
    const PLAN = { ok: true, components: [
      { id: 'core', name: '归档·同步·浏览·关键词搜索', required: true, status: 'ready', disk_mb: 120, ram_mb: 300, depends: [] },
      { id: 'reader', name: '读取组件', required: true, status: 'ready', disk_mb: 80, ram_mb: 400, depends: ['core'] },
      { id: 'dataview', name: 'Dataview', required: true, status: 'ready', depends: [] },
      { id: 'ocr', name: '本地 OCR', status: 'ready', disk_mb: 60, ram_mb: 200, depends: ['core'] },
      { id: 'asr', name: '本地语音识别', status: 'missing', disk_mb: 900, ram_mb: 600, depends: ['core'] },
      { id: 'capslock', name: 'CapsLock 语音输入', status: 'missing', disk_mb: 5, ram_mb: 30, depends: ['asr'] },
      { id: 'ai_text', name: 'AI 问答 · 概要 · 打标', needs_key: true, status: 'needs_key', depends: ['core'] },
      { id: 'ai_vision', name: '识图', needs_key: true, status: 'needs_key', depends: ['ocr'] },
      { id: 'remote', name: '远程阅读', later: true, depends: ['core'] }], presets: { light: ['core', 'reader', 'dataview', 'ocr'] } };
    const dates = Array.from({ length: 30 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - 29 + i); return d.toISOString().slice(0, 10); });
    const reply = args => {
      const sub = args.slice(2).join(' ');
      if (sub.startsWith('setup plan')) return PLAN;
      if (sub.startsWith('setup estimate')) return { ok: true, items: [] };
      if (sub.startsWith('comments --fill-status')) return { ok: true, pending: 190, missing: 5800, stuck: 0, running: true };
      if (sub.startsWith('connect status')) return { ok: true, clients: {}, json: '{}',
        apps: [{ id: 'claude-code', name: 'Claude Code', installed: true, oneclick: true, version: '2.1.302', connected: true },
          { id: 'codex', name: 'Codex', installed: true, oneclick: true, version: '0.146.0', connected: false },
          { id: 'opencode', name: 'OpenCode', installed: true, oneclick: false, version: '1.19.3', connected: false }], not_installed: ['Pi', 'Grok Build'] };
      if (sub.startsWith('connect add') || sub.startsWith('connect remove')) return { ok: true, changed: true, message: '已接到 Codex' };
      if (sub.startsWith('remote status')) { if (failRemote) throw new Error('ConnectError: 远程访问服务的状态命令崩了（合成）'); return { ok: true, state: 'running', message: '运行中（127.0.0.1:18071）', auth: { passphrase_set: true, passphrase_copyable: true, clients: [{ id: 'c1', name: 'claude.ai', connected_at: '2026-10-09T21:30:00' }], personal: [] }, recent: [] }; }
      if (sub.startsWith('sync-schedule')) return { task: 'LinkBrainNightly', freq: 'daily', time: '04:00', enabled: true, summary: '每天 04:00', rules: [{ kind: 'daily', times: ['04:00'] }] };
      if (sub.startsWith('selftest')) return { ok: true, detail: '合成测试正常' };
      if (sub.startsWith('usage --table')) return { ok: true, ai_table: { cli: [{ id: 'codex', name: 'Codex', preset: 'codex' }, { id: 'claude', name: 'Claude Code', preset: 'claude' }] } };
      if (sub.startsWith('usage')) {
        const f = o => ({ calls: 1, failed: 0, items: 0, in: 0, out: 0, sec: 0, cost: 0, free: 0, unpriced: 0, ...o });
        const win = { total: f({ calls: 558, cost: 2.85, free: 40, unpriced: 5 }),
          providers: { aliyun: f({ calls: 472, cost: 1.42 }), deepseek: f({ calls: 46, cost: 1.05 }), google: f({ calls: 40, free: 40 }) },
          models: { 'aliyun|qwen3.8-flash': f({ provider: 'aliyun', model: 'qwen3.8-flash', calls: 412, cost: 0.86 }), 'google|gemini-3.5-flash': f({ provider: 'google', model: 'gemini-3.5-flash', calls: 40, free: 40 }),
            'google|gemini-embedding-2': f({ provider: 'google', model: 'gemini-embedding-2', calls: 5, unpriced: 5 }) },
          features: { vision: f({ calls: 412, cost: 0.86 }), summary: f({ calls: 40, cost: 0.36 }), ask: f({ calls: 23, cost: 1.02 }) }, unpriced_models: [{ provider: 'google', model: 'gemini-embedding-2', calls: 5 }] };
        const wave = k => dates.map((_, i) => (i % 5 === 3 ? null : Math.round((0.05 + 0.3 * Math.abs(Math.sin(i / k))) * 100) / 100));
        return { ok: true, links: { aliyun: { name: '通义千问', console: 'https://bailian.console.aliyun.com/cn-beijing/', recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge' } },
          keys: { aliyun: { code: 'NEEDS_HUMAN.AUTH_FAILED', caps: ['visionAI', 'summaryAI'] } },
          budget: { daily_yuan: 3, spent_today: 0.83, day: '2026-10-27', over: false },
          summary: { as_of: '2026-10-03', features: { vision: '识图', summary: '概要', ask: '问收藏' }, windows: { today: win, '7d': win, '30d': win },
            series: { dates, providers: { aliyun: wave(3), deepseek: wave(5) }, models: { 'aliyun|qwen3.8-flash': wave(3) }, features: { vision: wave(3), summary: wave(4), ask: wave(6) } },
            recent: [{ ts: new Date().toISOString(), f: 'vision', p: 'aliyun', m: 'qwen3.8-flash', in: 2100, out: 150, ok: true, item: 'xhs-synthetic-1', cost: 0.0021, status: 'paid' }], recent_limit: 200,
            month: { deepseek: f({ calls: 46, cost: 1.05 }), aliyun: f({ calls: 512, cost: 1.80 }) } },
          features: [{ id: 'vision', name: '识图', on: true, state: 'ok', chain: [{ label: 'Gemini', provider: 'google' }, { label: '通义千问', provider: 'aliyun' }] }] };
      }
      return { ok: true };
    };
    const Plugin = require('main.js');
    window.l4skills = ['recipe'];
    const files = { '_skills/recipe/SKILL.md': '---\nname: recipe\ndescription: 菜谱\n---\n正文',
      '_archive/problems-summary.json': JSON.stringify({ needs_human: 0, auto: 1, gave_up: 0, sync: { state: 'ready', last_success: new Date().toISOString(), new: 40, deferred: 600 } }) };
    if (!guide) files['_archive/catalog-data.json'] = '{"items":[]}';
    const app = { workspace: { trigger() {}, on() { return {}; }, offref() {}, getActiveFile: () => null },
      vault: { adapter: { getBasePath: () => '/synthetic-vault', exists: async f => f in files || (f === '_skills' && window.l4skills.length > 0), read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; },
        list: async dir => ({ folders: window.l4skills.map(id => dir + '/' + id), files: [] }) }, getAllLoadedFiles: () => [] },
      metadataCache: { getFileCache: () => ({}) } };
    const plugin = new Plugin(app, { id: 'link-brain-actions', dir: '' });
    const BL = 'https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions', G = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions';
    plugin.settings = Plugin.merge({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'sample-text' },
      summaryAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', fallback: { endpoint: BL, model: 'qwen3.7-flash' } },
      visionAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', refine: { endpoint: BL, model: 'qwen3.8-max' } },
      setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text', 'ai_vision'], aiSynced: true }, voice: { capsLock: false }, asrAI: { mode: 'off' } });
    plugin.settings.remote = { enabled: remoteOn, domain: remoteOn ? 'https://lwa.example.com' : '', port: 18071, folders: ['@xhs', 'D:/笔记/读书'] };
    if (!guide) plugin.settings.onboarding = { guideDone: true };
    plugin.lbPath = x => x; plugin.manifest = { id: 'link-brain-actions', dir: '' };
    plugin.loadData = async () => JSON.parse(JSON.stringify(plugin.settings));
    window.saveFails = 0;
    plugin.saveSettings = async () => { if (window.saveFails > 0) { window.saveFails--; throw new Error('磁盘满了（合成）'); } };
    plugin.renderSetupHints = () => {};
    plugin.capsWriterDir = () => null;
    plugin.setCapsVoice = async () => true;
    plugin.renderAccounts = (c, opts) => { const s = new window.obsidian.Setting(c).setName(opts && opts.inCard ? 'momo · ✓ 已登录' : '小红书 · momo · ✓ 已登录'); s.settingEl.classList.add('lb-acct-row'); s.addButton(b => b.setButtonText('换个账号')); };
    plugin.runPy = async args => ({ code: 0, json: reply(args) });
    plugin.indexUI = require('index-ui.js')(window.obsidian, plugin); plugin.indexUI.attach();
    plugin.taskStatusEl = document.querySelector('.status-bar').createDiv({ cls: 'status-bar-item l4-task' });
    plugin.onboardingUI = () => require('onboarding-ui.js')(window.obsidian, plugin);
    plugin.usageUI = () => require('usage-ui.js')(window.obsidian, plugin);
    plugin.openProblems = () => { window.l4problems = (window.l4problems || 0) + 1; };
    plugin.remoteUI = require('remote-ui.js')(window.obsidian, plugin);
    const tab = new Plugin.Tab(app, plugin);
    tab.containerEl = document.querySelector('.vertical-tab-content');
    plugin.settingTab = tab;
    window.l4 = { plugin, tab, Plugin };
    window.l4runs = 0;
    plugin.homeUI().runAll = async () => { window.l4runs++; return { ok: true }; };
    tab.display();
  }, [sources, failRemote, guide, remoteOn]);
  return { page, errors };
}

const shot = (page, name) => page.screenshot({ path: path.join(shell.QA_DIR, name), fullPage: true });
const nestedBoxes = page => page.evaluate(() => {
  const pane = document.querySelector('.lb-tab-pane');
  const boxed = e => { const cs = getComputedStyle(e); return ['Top', 'Bottom', 'Left', 'Right'].every(s => cs['border' + s + 'Style'] === 'solid' && parseFloat(cs['border' + s + 'Width']) > 0)
    && parseFloat(cs.borderTopLeftRadius) >= 6 && !e.closest('.checkbox-container, .dropdown, button, input, textarea, .lb-usage-grid, .lb-guide-dot, .lb-seg') && e.getBoundingClientRect().height > 40; };
  const boxes = [...pane.querySelectorAll('div, details, section')].filter(boxed);
  return boxes.filter(b => boxes.some(o => o !== b && o.contains(b))).map(e => e.className);
});
const visibleText = page => page.evaluate(() => {
  const textOf = node => { if (node.nodeType === 3) return node.textContent; if (node.nodeType !== 1) return ''; if (node.tagName === 'DETAILS' && !node.open) return node.querySelector('summary')?.textContent || '';
    if (node.hidden || getComputedStyle(node).display === 'none') return ''; return [...node.childNodes].map(textOf).join(' '); };
  return textOf(document.querySelector('.lb-tab-pane'));
});

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const summary = {};
  try {
    for (const theme of ['light', 'dark', 'orange']) {
      const { page, errors } = await open(browser, theme);
      await page.waitForFunction(() => /¥0\.83/.test(document.querySelector('.lb-console')?.textContent || '') && document.querySelectorAll('.lb-app').length >= 3);
      await page.waitForTimeout(300);
      assert.equal(await page.locator('.lb-tabs').count(), 0, '没有页签');
      const groups = await page.evaluate(() => [...document.querySelectorAll('.lb-group')].map(g => g.getAttribute('data-section') + ':' + g.querySelector('h2').textContent));
      assert.deepEqual(groups, ['g-account:账号登录', 'g-sync:收藏与同步', 'g-catalog:目录与批注', 'g-advanced:高级功能', 'g-connect:CLI 与外接 MCP', 'g-repair:修复']);
      // 左边锚点：和内容并排、跟着滚（sticky）
      const geo = await page.evaluate(() => { const n = document.querySelector('.lb-anchors').getBoundingClientRect(), m = document.querySelector('.lb-v7-main').getBoundingClientRect();
        return { navRight: n.right, mainLeft: m.left, pos: getComputedStyle(document.querySelector('.lb-anchors')).position }; });
      assert.ok(geo.navRight <= geo.mainLeft && geo.pos === 'sticky', theme + '：锚点在左边、sticky ' + JSON.stringify(geo));
      const text = await visibleText(page);
      assert.deepEqual(JARGON.filter(w => text.includes(w)), [], theme + '：明面上没有术语');
      assert.ok(await page.locator('.lb-tab-pane button.mod-cta:visible').count() <= 1, '最多一个主按钮');
      assert.deepEqual(await nestedBoxes(page), [], theme + '：不框套框');
      const rowBoxes = await page.evaluate(() => [...document.querySelectorAll('.lb-v7 .setting-item')].filter(r => { const cs = getComputedStyle(r);
        return cs.backgroundColor !== 'rgba(0, 0, 0, 0)' || cs.borderLeftStyle === 'solid'; }).map(r => r.querySelector('.setting-item-name')?.textContent));
      assert.deepEqual(rowBoxes, [], theme + '：行不再自带底色 / 边框');
      // ④ 图标：六个、可见、和名字同一行
      const icons = await page.evaluate(() => [...document.querySelectorAll('[data-section="g-advanced"] .lb-feat .lb-feat-icon svg')].map(s => { const r = s.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height); }));
      assert.deepEqual(icons, Array(6).fill('18x18'), theme + '：六个线条图标 ' + icons);
      // 账号卡、电脑端 / 网页端两张卡并排
      const twin = await page.evaluate(() => [...document.querySelectorAll('.lb-twin')].map(t => { const [a, b] = t.querySelectorAll('.lb-twin-card'); const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); return Math.abs(ra.top - rb.top) < 2 && ra.right <= rb.left; }));
      assert.deepEqual(twin, [true, true], theme + '：两张卡并排');
      // key 用不了：一句 + 去充值 + 换 key → 「更多 → 接口与密钥」那一个粘 key 的框
      assert.match(await page.locator('.lb-key-trouble .lb-fix-line').first().textContent(), /通义千问 key 用不了（识图、概要）.*去充值 ↗.*换 key/);
      await page.locator('.lb-key-trouble button', { hasText: '换 key' }).click(); await page.waitForTimeout(500);
      assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('[data-section="ai-key-paste"] input')), true, theme + '：换 key → 焦点进粘 key 的框');
      // AI 控制台：点开左右两栏；折线固定 190px，不撑出去
      await page.locator('.lb-console-toggle').click(); await page.waitForTimeout(200);
      const chart = await page.evaluate(() => { const c = document.querySelector('.lb-chart').getBoundingClientRect(), s = document.querySelector('.lb-chart svg').getBoundingClientRect(),
        l = document.querySelector('.lb-console-left').getBoundingClientRect(), r = document.querySelector('.lb-console-right').getBoundingClientRect();
        return { h: Math.round(c.height), svgInside: s.bottom <= c.bottom + 0.5 && s.right <= c.right + 0.5 && s.left >= c.left - 0.5, twoCols: l.right <= r.left && Math.abs(l.top - r.top) < 4, lines: document.querySelectorAll('.lb-chart [data-key]').length,
        tableInside: document.querySelector('.lb-console-right table').getBoundingClientRect().right <= r.right + 0.5 }; });
      assert.deepEqual(chart, { h: 190, svgInside: true, twoCols: true, lines: 2, tableInside: true }, theme + '：' + JSON.stringify(chart));
      await page.locator('.lb-usage-dim', { hasText: '模型' }).click(); await page.waitForTimeout(100);
      const modelRows = await page.evaluate(() => [...document.querySelectorAll('.lb-console-right .lb-usage-grid tr')].map(tr => [...tr.children].map(td => td.textContent)));
      assert.ok(modelRows.some(r => r[0] === 'gemini-3.5-flash · Gemini' && r[1] === '免费 / 未计费'), theme + '：免费 key 写免费 / 未计费');
      assert.ok(modelRows.some(r => r[0] === 'gemini-embedding-2 · Gemini' && r[1] === '未计价'));
      assert.deepEqual(modelRows.slice(-2).map(r => r[0]), ['免费 / 未计费', '未计价']);
      await page.locator('.lb-console').screenshot({ path: path.join(shell.QA_DIR, `S1027-console-${theme}.png`) });
      // 每天最多花：改了立刻存
      await page.locator('input.lb-spend-input').fill('5'); await page.locator('input.lb-spend-input').dispatchEvent('change'); await page.waitForTimeout(100);
      assert.equal(await page.evaluate(() => window.l4.plugin.settings.budget.dailyYuan), 5);
      // 接入 Codex：开关 → connect add codex → 「已接入」
      await page.evaluate(() => document.querySelector('.lb-app[data-app="codex"] .checkbox-container').click()); await page.waitForTimeout(200);
      assert.equal(await page.evaluate(() => document.querySelector('.lb-app[data-app="codex"] .setting-item-description').textContent), '已接入');
      assert.equal(await page.locator('[data-section="remote"] .lb-twin-head .checkbox-container').count(), 1, '网页端的开关在卡片标题上');
      summary[theme] = { groups, chart };
      await page.evaluate(() => { document.querySelector('.vertical-tab-content').scrollTop = 0; });
      await shot(page, `S1027-settings-${theme}.png`);
      assert.deepEqual(errors, []);
      await page.close();
    }
    // 窄：设置内容区 420px——锚点横排吸顶、两栏变一栏、没有横向滚动
    {
      const { page, errors } = await open(browser, 'light', { width: 420 });
      await page.waitForFunction(() => document.querySelectorAll('.lb-app').length >= 3);
      await page.locator('.lb-console-toggle').click(); await page.waitForTimeout(200);
      const n = await page.evaluate(() => { const nav = document.querySelector('.lb-anchors'), sc = document.querySelector('.vertical-tab-content');
        const l = document.querySelector('.lb-console-left').getBoundingClientRect(), r = document.querySelector('.lb-console-right').getBoundingClientRect();
        const [a, b] = document.querySelectorAll('.lb-twin')[0].querySelectorAll('.lb-twin-card');
        return { dir: getComputedStyle(nav).flexDirection, stacked: r.top >= l.bottom - 1, cardsStacked: b.getBoundingClientRect().top >= a.getBoundingClientRect().bottom - 1,
          overflow: sc.scrollWidth - sc.clientWidth, chartH: Math.round(document.querySelector('.lb-chart').getBoundingClientRect().height) }; });
      assert.deepEqual(n, { dir: 'row', stacked: true, cardsStacked: true, overflow: 0, chartH: 190 }, '窄窗：' + JSON.stringify(n));
      await shot(page, 'S1027-settings-narrow.png');
      assert.deepEqual(errors, []);
      await page.close();
    }
    // 网页端开着：网址 / 连接地址 / 口令 / 两家几步；读不到的块一句人话 + 重试
    {
      const { page, errors } = await open(browser, 'light', { remoteOn: true });
      await page.waitForFunction(() => /● 开着/.test(document.querySelector('[data-section="remote"]')?.textContent || ''));
      for (const n of ['你的网址', '连接地址', '口令']) assert.ok(await page.locator('[data-section="remote"] .setting-item-name', { hasText: n }).count(), '网页端：' + n);
      assert.ok(!/OAuth/.test(await page.evaluate(() => document.querySelector('[data-section="remote"]').innerText)), '界面上没有 OAuth');
      await page.locator('[data-section="remote"]').screenshot({ path: path.join(shell.QA_DIR, 'S1027-web-card.png') });
      assert.deepEqual(errors, []);
      await page.close();
      const f = await open(browser, 'light', { remoteOn: true, failRemote: true });
      await f.page.waitForFunction(() => document.querySelector('[data-section="remote"] .lb-fail'));
      const fb = await f.page.evaluate(() => { const x = document.querySelector('[data-section="remote"] .lb-fail'); const d = x.querySelector('details'); return { line: x.querySelector('.lb-fail-line').textContent, open: d.open, raw: d.textContent }; });
      assert.match(fb.line, /这一块暂时读不到，点重试/);
      assert.equal(fb.open, false, '原始报错默认折着');
      assert.match(fb.raw, /详情.*状态命令崩了/);
      assert.deepEqual(f.errors, []);
      await f.page.close();
    }
    // 库里还没收藏：首次设置（欢迎页 → 自定义四步 → 完成变六组页）
    {
      const { page, errors } = await open(browser, 'light', { guide: true });
      await page.waitForFunction(() => document.querySelector('.lb-guide .lb-big'));
      assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('.lb-big-name')].map(e => e.textContent)), ['推荐设置，一键开始', '自定义']);
      await page.locator('button.lb-big', { hasText: '自定义' }).click(); await page.waitForTimeout(150);
      const seen = [];
      for (let k = 1; k <= 4; k++) {
        await page.waitForTimeout(250);
        seen.push(await page.evaluate(() => document.querySelector('.lb-guide .lb-card-title').textContent));
        await shot(page, `S1027-guide-${k}-light.png`);
        if (k < 4) { await page.locator('.lb-guide-nav button', { hasText: '下一步' }).click(); await page.waitForTimeout(200); }
      }
      assert.deepEqual(seen, ['登录小红书', '同步', '识别与问答', '接入其他 AI（MCP）']);
      await page.locator('.lb-guide-nav button', { hasText: '完成' }).click();
      await page.waitForFunction(() => document.querySelector('.lb-group[data-section="g-account"]'));
      assert.equal(await page.evaluate(() => window.l4.plugin.settings.onboarding.guideDone), true);
      assert.equal(await page.evaluate(() => window.l4runs), 1, '完成后开始一口气跑');
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  fs.mkdirSync(shell.QA_DIR, { recursive: true });
  fs.writeFileSync(path.join(shell.QA_DIR, 'S1027-settings-rows.json'), JSON.stringify(summary, null, 2));
  console.log('PASS 1027 settings six groups (real Chromium, light / dark / third-party): anchors left + sticky, six groups, six stroke icons, twin cards side by side, key trouble → 换 key focuses the one paste box, AI console two columns with chart fixed at 190px inside its column (free / unpriced rows), budget saves, Codex one-switch, web toggle on card head; narrow 420px → horizontal anchors, one column, no horizontal scroll; web card fields + unreadable block retry; first-run 4 steps → six groups; no jargon / box-in-box. Screenshots: ' + shell.QA_DIR);
})().catch(error => { console.error(error); process.exitCode = 1; });

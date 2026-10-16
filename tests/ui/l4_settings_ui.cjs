'use strict';
// 1016 设置页重做（她：懒得动、不想看的不放；要确认的、要知道的才放；不套框）：四个页签 概览 / 同步 / AI / 更多 + 第一次的四步指引。
// 下面头注释是 1015 版的；检查项已按 1016 改（见文件后半）。
// 1015 设置页（她：照 claudian 插件改版）在真 Chromium + Obsidian 外壳（settings-modal）里，亮 / 暗 / 第三方主题：
//   ① 顶部下划线页签：通用 / 模型与提供商 / 技能；一次只画一栏；每栏最多一个主按钮（mod-cta）
//   ② 通用：每组一张圆角卡片（标题加粗 + 分隔线）—— 状态（账号 · 收藏同步 · 评论补齐 · 问题 · 这台电脑 +「一键装好 / 跑完」）· 收藏 ·
//      定时同步（自动同步编辑器 · 每次同步最多收几篇 · 每天最多新收几篇 · 每篇评论抓几楼 · 补评论节奏）· 目录与批注（目录分类默认收起）·
//      附件手动下载 · 连接其他 AI（「还没有网址？」紧挨着网址；访问令牌只在最下面「高级」折叠里；界面上没有 OAuth）· 开发者
//   ③ 模型与提供商：子页签 AI 功能（价钱、子选项只在父开关打开后出现）· 问收藏模型（勾选列表，勾选框在左）· 识图 · 认字 · 语音 · 提示词
//   ④ 技能：说明行 + 刷新 / ＋ · 读收藏库 _skills 的列表 · 空状态一句 · 隐藏列表输入框
//   ⑦ 开关改了立刻存，存失败拨回原值并提示（外壳的开关照 1.14.4：setValue 会再触发 onChange——验拨回不来回弹）
//   ⑧ 读不到的块不露原始报错：「这一块暂时读不到，点重试」+ 折起来的「详情」
// runPy 是替身（不起真进程）；截图落盘留档（LWA_QA_DIR）。
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const shell = require('../_obsidian_shell.cjs');
const root = 'obsidian-plugins/link-brain-actions';
const sources = Object.fromEntries(['main', 'home-ui', 'remote-ui', 'schedule-ui', 'onboarding-ui', 'index-ui', 'skills-ui', 'usage-ui', 'settings-pages'].map(name =>
  [name + '.js', fs.readFileSync(path.join(root, name + '.js'), 'utf8')]));
const TABS = ['概览', '同步', 'AI', '更多'];
// 新手主界面（不算「连接其他 AI」里的高级折叠）上不该看到的词（她 1010 点名的术语；要留的旁边有人话解释）
const JARGON = ['OAuth', 'Bearer', 'Authorization', 'launchd', 'systemd', '标准输入', '标准输出', '扩检索词', '归档摘要模型', '认领', '令牌', '没画上', '读不到状态：', '读不到功能清单：'];

async function open(browser, theme, { failRemote = false, guide = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1300, height: 1400 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await shell.settings(page, { theme, contentWidth: 800 });
  await page.evaluate(([sources, failRemote, guide]) => {
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
      { id: 'reader', name: '读取组件（读小红书收藏 / 评论 / 附件）', required: true, status: 'ready', disk_mb: 80, ram_mb: 400, depends: ['core'] },
      { id: 'dataview', name: 'Dataview（目录页显示用，Obsidian 插件）', required: true, status: 'ready', depends: [] },
      { id: 'ocr', name: '本地 OCR（图片里的字）', status: 'ready', disk_mb: 60, ram_mb: 200, depends: ['core'] },
      { id: 'asr', name: '本地语音识别（CapsWriter，视频转写 / 语音提问）', status: 'missing', disk_mb: 900, ram_mb: 600, depends: ['core'] },
      { id: 'capslock', name: 'CapsLock 语音输入', status: 'missing', disk_mb: 5, ram_mb: 30, depends: ['asr'] },
      { id: 'ai_text', name: 'AI 问答 · 概要 · 打标（要 API key）', needs_key: true, status: 'needs_key', depends: ['core'] },
      { id: 'ai_vision', name: '识图（要 API key）', needs_key: true, status: 'needs_key', depends: ['ocr'] },
      { id: 'remote', name: '远程阅读（MCP，高级，要自备域名）', later: true, depends: ['core'] }], presets: { light: ['core', 'reader', 'dataview', 'ocr'] } };
    const EST = { ok: true, items: [
      { id: 'summary', name: '概要 + 打标', provider: 'DeepSeek', model: 'deepseek-flash', api_model: 'deepseek-v4-flash', yuan: 0.8, per: '100 篇', endpoint: 'https://api.deepseek.com/chat/completions', key_url: 'https://platform.deepseek.com/api_keys' },
      { id: 'vision', name: '识图', provider: '通义千问', model: 'qwen3.8-flash', yuan: null, per: '100 篇', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', key_url: 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key' },
      { id: 'video', name: '视频转写', provider: 'OpenAI', model: 'gpt-4o-mini-transcribe', yuan: 12, per: '100 篇' },
      { id: 'ask', name: '问答（每问一次）', provider: 'DeepSeek', model: 'deepseek-flash', yuan: 0.004, per: '次', endpoint: 'https://api.deepseek.com/chat/completions', key_url: 'https://platform.deepseek.com/api_keys' }],
      prices: { as_of: '2026-10-03' } };
    const reply = args => {
      const sub = args.slice(2).join(' ');
      if (sub.startsWith('setup plan')) return PLAN;
      if (sub.startsWith('setup estimate')) return EST;
      if (sub.startsWith('comments --fill-status')) return { ok: true, pending: 190, missing: 5800, stuck: 0, running: true };
      if (sub.startsWith('connect status')) return { ok: true, clients: { 'claude-code': { installed: true, connected: false, command: 'claude mcp add lwa -s user -- python -m link_brain mcp' }, 'claude-desktop': { installed: false, connected: false } }, json: '{}' };
      if (sub.startsWith('remote status')) { if (failRemote) throw new Error('ConnectError: 远程访问服务的状态命令崩了（合成）'); return { ok: true, state: 'running', message: '运行中（127.0.0.1:18071）', auth: { passphrase_set: true, passphrase_copyable: true, clients: [{ id: 'c1', name: 'claude.ai', connected_at: '2026-10-09T21:30:00' }], personal: [] }, recent: [] }; }
      if (sub.startsWith('sync-schedule')) return { task: 'LinkBrainNightly', freq: 'daily', time: '04:00', enabled: true, summary: '每天 04:00', rules: [{ kind: 'daily', times: ['04:00'] }] };
      if (sub.startsWith('selftest')) return { ok: true, detail: '合成测试正常' };
      // 1016 用量与余额（合成数）
      if (sub.startsWith('usage')) {
        const f = o => ({ calls: 1, failed: 0, items: 0, in: 0, out: 0, sec: 0, cost: 0, unpriced: 0, ...o });
        const links = { deepseek: { name: 'DeepSeek', console: 'https://platform.deepseek.com/', recharge: 'https://platform.deepseek.com/top_up', usage: 'https://platform.deepseek.com/usage' },
          aliyun: { name: '通义千问', console: 'https://bailian.console.aliyun.com/cn-beijing/', recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge', usage: 'https://bailian.console.aliyun.com/cn-beijing/costing-balance/usage-statistics' } };
        const features = { vision: f({ calls: 412, failed: 3, items: 38, in: 865000, out: 61000, cost: 0.86 }), refine: f({ calls: 6, items: 4, in: 18000, out: 9000, cost: 0.54 }),
          summary: f({ calls: 40, items: 40, in: 98000, out: 21000, cost: 0.36 }), ask: f({ calls: 23, in: 412000, out: 31000, cost: 1.02 }), expand: f({ calls: 23, in: 9800, out: 2100, cost: 0.03 }),
          embed: f({ calls: 31, in: 52000, cost: 0.0065 }), rerank: f({ calls: 23, in: 61000, cost: 0.0305 }) };
        const total = f({ calls: 558, failed: 3, in: 1515800, out: 124100, cost: 2.85 });
        const out = { ok: true, links, keys: { aliyun: { code: 'NEEDS_HUMAN.AUTH_FAILED', caps: ['visionAI', 'summaryAI'] } },
          summary: { as_of: '2026-10-03', features: { vision: '识图', refine: '精细识图', summary: '概要', ask: '问收藏', expand: '扩词', embed: '向量（embedding）', asr: '语音转写', rerank: '精排（rerank）', other: '索引 / wiki 整理' },
            windows: { today: { total, features, providers: {} }, '7d': { total, features, providers: {} }, '30d': { total, features, providers: {} } },
            month: { deepseek: f({ calls: 46, cost: 1.05 }), aliyun: f({ calls: 512, cost: 1.80 }) } } };
        if (sub.includes('--balance')) out.balances = { deepseek: { ok: true, available: true, balances: [{ currency: 'CNY', total: '105.38', granted: '4.40', topped_up: '100.97' }] },
          aliyun: { ok: false, unsupported: true, message: '百炼没有用 API key 能查的余额接口：点「充值」在阿里云费用中心看' } };
        return out;
      }
      return { ok: true };
    };
    const Plugin = require('main.js');
    // 1015 技能页：收藏库 _skills 里两个合成技能
    window.l4skills = ['recipe', 'travel'];
    const files = { '_skills/recipe/SKILL.md': '---\nname: recipe\ndescription: 菜谱：列菜名、主料、难度；展开给用量和步骤\n---\n正文',
      '_skills/travel/SKILL.md': '---\nname: travel\ndescription: >\n  旅游攻略：路线、时段、预算、坑\n---\n',
      '_archive/comments-fill-status.json': JSON.stringify({ state: 'running', message: '正在补评论 · 已补齐 7/197 篇 · 还缺 5800 条回复', updated_at: new Date().toISOString() }),
      '_archive/problems-summary.json': JSON.stringify({ needs_human: 0, auto: 1, gave_up: 0, sync: { state: 'ready', last_success: new Date().toISOString(), new: 40, deferred: 600 } }) };
    if (!guide) files['_archive/catalog-data.json'] = '{"items":[]}';   // 库里有收藏：不出四步指引
    const app = { workspace: { trigger() {}, getActiveFile: () => null },
      vault: { adapter: { getBasePath: () => '/synthetic-vault', exists: async f => f in files || (f === '_skills' && window.l4skills.length > 0), read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; },
        list: async dir => ({ folders: window.l4skills.map(id => dir + '/' + id), files: [] }) }, getAllLoadedFiles: () => [] },
      metadataCache: { getFileCache: () => ({}) } };
    const plugin = new Plugin(app, { id: 'link-brain-actions', dir: '' });
    const BL = 'https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions', G = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions';
    plugin.settings = Plugin.merge({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'sample-text' },
      summaryAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', fallback: { endpoint: BL, model: 'qwen3.7-flash' } },
      visionAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', refine: { endpoint: BL, model: 'qwen3.8-max' } },
      embedAI: { mode: 'http', endpoint: BL.replace('/chat/completions', '/embeddings'), model: 'qwen3.7-text-embedding-flash' },
      setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text'], aiSynced: true }, connect: { clients: ['claude-code', 'claude-ai', 'chatgpt'] },
      voice: { capsLock: false }, asrAI: { mode: 'off' } });
    plugin.settings.remote = { enabled: true, domain: '', port: 18071, folders: ['@xhs', 'D:/笔记/读书'] };
    plugin.lbPath = x => x; plugin.manifest = { id: 'link-brain-actions', dir: '' };
    plugin.loadData = async () => JSON.parse(JSON.stringify(plugin.settings));
    window.saveFails = 0;
    plugin.saveSettings = async () => { if (window.saveFails > 0) { window.saveFails--; throw new Error('磁盘满了（合成）'); } };
    plugin.renderSetupHints = () => {};
    plugin.capsWriterDir = () => null;
    plugin.setCapsVoice = async () => true;
    plugin.renderAccounts = c => { const s = new window.obsidian.Setting(c).setName('小红书 · momo · ✓ 已登录'); s.settingEl.classList.add('lb-acct-row'); };
    plugin.runPy = async args => ({ code: 0, json: reply(args) });
    plugin.indexUI = require('index-ui.js')(window.obsidian, plugin); plugin.indexUI.attach();   // 10-10 索引树：设置里「目录分类」那一节的按钮调它挂的方法
    plugin.taskStatusEl = document.querySelector('.status-bar').createDiv({ cls: 'status-bar-item l4-task' });
    plugin.onboardingUI = () => require('onboarding-ui.js')(window.obsidian, plugin);
    plugin.usageUI = () => require('usage-ui.js')(window.obsidian, plugin);
    plugin.openProblems = () => { window.l4problems = (window.l4problems || 0) + 1; };
    plugin.remoteUI = require('remote-ui.js')(window.obsidian, plugin);
    const tab = new Plugin.Tab(app, plugin);
    tab.containerEl = document.querySelector('.vertical-tab-content');
    plugin.settingTab = tab;
    window.l4 = { plugin, tab, Plugin };
    tab.display();
  }, [sources, failRemote, guide]);
  return { page, errors };
}

// 当前那一栏的读数（收起的折叠里的行不算「看得见」）
const readPane = page => page.evaluate(JARGON => {
  const pane = document.querySelector('.lb-tab-pane');
  const vis = el => { for (let n = el; n && n !== pane; n = n.parentElement) { if (n.tagName === 'DETAILS' && !n.open && !n.querySelector('summary').contains(el)) return false; if (n.hidden) return false; } return true; };
  const rows = [...pane.querySelectorAll('.setting-item')].filter(vis).map(r => (r.querySelector('.setting-item-name')?.textContent || '').replace(/\?$/, '').trim());
  const textOf = node => { if (node.nodeType === 3) return node.textContent; if (node.nodeType !== 1) return ''; if (node.classList.contains('lb-connect-adv')) return '';
    if (node.tagName === 'DETAILS' && !node.open) return node.querySelector('summary')?.textContent || ''; return [...node.childNodes].map(textOf).join(' '); };
  const text = textOf(pane);
  // 框套框：设置区里四边都有实线边框、又有圆角的大块（输入框 / 按钮 / 开关 / 下拉 / 表格不算）
  const boxes = [...pane.querySelectorAll('div, details, section')].filter(e => { const cs = getComputedStyle(e);
    return ['Top', 'Bottom', 'Left', 'Right'].every(s => cs['border' + s + 'Style'] === 'solid' && parseFloat(cs['border' + s + 'Width']) > 0) && parseFloat(cs.borderTopLeftRadius) >= 6
      && !e.closest('.checkbox-container, .dropdown, button, input, textarea, .lb-usage-grid, .lb-guide-dot') && e.getBoundingClientRect().height > 40; }).map(e => e.className);
  return { tab: pane.getAttribute('data-tab'), rows, cta: pane.querySelectorAll('button.mod-cta').length, ctaText: [...pane.querySelectorAll('button.mod-cta')].map(b => b.textContent),
    jargon: JARGON.filter(w => text.includes(w)), text, boxes,
    tabs: [...document.querySelectorAll('.lb-tabs .lb-tab')].map(b => b.textContent), active: [...document.querySelectorAll('.lb-tabs .lb-tab.is-active')].map(b => b.textContent) };
}, JARGON);
const clickTab = async (page, label) => { await page.locator('.lb-tabs .lb-tab', { hasText: label }).first().click(); await page.waitForTimeout(200); };
const shot = (page, name) => page.screenshot({ path: path.join(shell.QA_DIR, name), fullPage: true });

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const summary = {};
  try {
    for (const theme of ['light', 'dark', 'orange']) {
      const { page, errors } = await open(browser, theme);
      // ① 概览：账号 · 收藏 · 全部记录；没有需要留意的事就不出那一块
      await page.waitForFunction(() => document.querySelector('.lb-tab-pane[data-tab="overview"]') && [...document.querySelectorAll('.setting-item-name')].some(e => e.textContent === '全部记录'));
      let p = await readPane(page);
      assert.deepEqual(p.tabs, TABS); assert.deepEqual(p.active, ['概览']);
      assert.ok(!(await page.locator('.lb-subtabs').count()), '没有子页签');
      assert.ok(!(await page.locator('.lb-guide').count()), '库里有收藏：不出指引');
      for (const n of ['小红书 · momo · ✓ 已登录', '收藏同步', '全部记录']) assert.ok(p.rows.includes(n), `${theme} 概览缺「${n}」：${p.rows}`);
      assert.ok(p.rows.length <= 4, `${theme} 概览别塞太多：${p.rows}`);
      assert.equal(p.cta, 0, '概览没有主按钮');
      assert.deepEqual(p.boxes, [], theme + '：概览不套框');
      assert.deepEqual(p.jargon, [], theme + '：概览没有术语');
      summary[theme] = { 概览: p.rows };
      await shot(page, `S1016-settings-overview-${theme}.png`);
      // ② 同步：三项 + 折叠
      await clickTab(page, '同步');
      await page.waitForFunction(() => document.querySelector('.lb-sched-row') && !document.querySelector('.lb-sched-rows.is-loading'));
      p = await readPane(page);
      assert.equal(p.tab, 'sync');
      assert.deepEqual(p.rows, ['自动同步', '存视频', '每篇评论抓几楼'], theme + '：同步页明面上三项');
      assert.match(p.text, /更多同步选项/);
      assert.deepEqual(p.boxes, [], theme + '：同步不套框');
      summary[theme]['同步'] = p.rows;
      await shot(page, `S1016-settings-sync-${theme}.png`);
      await page.locator('[data-section="sync-more"] > summary').click(); await page.waitForTimeout(150);
      p = await readPane(page);
      for (const n of ['收藏放在哪', '存图片', '登录后马上同步', '每次同步最多收几篇', '每天最多新收几篇', '补评论节奏']) assert.ok(p.rows.includes(n), `${theme} 同步折叠缺「${n}」`);
      // ③ AI：每家一行写它管哪些功能；花了多少；详细设置在折叠里
      await clickTab(page, 'AI');
      await page.waitForFunction(() => document.querySelectorAll('.lb-provider-row').length >= 3 && /105\.38/.test(document.querySelector('.lb-usage-provider[data-provider="deepseek"]')?.textContent || ''));
      assert.equal(await page.evaluate(() => document.querySelector('[data-section="ai-usage"]').open), false, '花费明细默认收起');
      p = await readPane(page);
      assert.equal(p.tab, 'ai');
      const prov = await page.evaluate(() => [...document.querySelectorAll('.lb-provider-row')].map(r => [r.querySelector('.setting-item-name').textContent,
        r.querySelector('.setting-item-description').textContent, [...r.querySelectorAll('button')].map(b => b.textContent).join('/')]));
      assert.deepEqual(prov.map(x => x[0]), ['Gemini（几把 key 轮流用）', 'DeepSeek', '阿里云百炼']);
      assert.equal(prov[0][1], '概要 · 识图'); assert.equal(prov[1][1], '问收藏'); assert.equal(prov[2][1], '语义搜索　备用：概要 · 精细识图');
      assert.equal(prov[0][2], '控制台/拿 key'); assert.equal(prov[1][2], '控制台/充值/拿 key');
      assert.match(p.text, /详细设置/);
      assert.equal(await page.evaluate(() => document.querySelector('[data-section="ai-more"]').open), false, '详细设置默认收起');
      assert.ok(p.cta <= 1);
      assert.deepEqual(p.jargon, [], theme + '：AI 页明面上没有术语');
      summary[theme].AI = p.rows;
      await shot(page, `S1016-settings-ai-${theme}.png`);
      // ④ 更多
      await clickTab(page, '更多');
      await page.waitForFunction(() => /● 开着/.test(document.querySelector('.lb-remote-svc')?.textContent || ''));
      p = await readPane(page);
      for (const n of ['批注署名', '留言对象']) assert.ok(p.rows.includes(n), `${theme} 更多明面上缺「${n}」`);
      assert.ok(!p.rows.includes('远程访问'), '接其他 AI 默认收着');
      assert.deepEqual(p.boxes, [], theme + '：更多不套框');
      await shot(page, `S1016-settings-more-${theme}.png`);
      await page.locator('[data-section="connect"] > summary').click(); await page.waitForTimeout(150);
      p = await readPane(page);
      for (const n of ['Claude Code', '远程访问', '批注署名', '留言对象']) assert.ok(p.rows.includes(n), `${theme} 更多缺「${n}」：${p.rows}`);
      assert.match(p.text, /技能/); assert.match(p.text, /高级/);
      assert.ok(!/OAuth/.test(p.text), '界面上没有 OAuth');
      summary[theme]['更多'] = p.rows;
      await shot(page, `S1016-settings-more-open-${theme}.png`);
      assert.deepEqual(errors, []);
      await page.close();
    }
    // ⑤ 库里还没收藏：四步指引
    {
      const { page, errors } = await open(browser, 'light', { guide: true });
      await page.waitForFunction(() => document.querySelector('.lb-guide'));
      const g = () => page.evaluate(() => ({ title: document.querySelector('.lb-guide-title').textContent,
        steps: [...document.querySelectorAll('.lb-guide-step')].map(s => s.className.replace('lb-guide-step', '').trim() + ':' + s.textContent) }));
      let st = await g();
      assert.equal(st.title, '收藏放在哪个文件夹？');
      assert.deepEqual(st.steps, ['is-on:1放在哪', ':2登录小红书', ':3AI 帮忙', ':4开始同步']);
      await shot(page, 'S1016-settings-guide-1-light.png');
      await page.locator('.lb-guide-nav button', { hasText: '下一步' }).click(); await page.waitForTimeout(150);
      await page.locator('.lb-guide-nav button', { hasText: '下一步' }).click(); await page.waitForTimeout(150);
      st = await g();
      assert.equal(st.title, '要不要 AI 帮你整理？');
      assert.deepEqual(st.steps, ['is-done:✓放在哪', 'is-done:✓登录小红书', 'is-on:3AI 帮忙', ':4开始同步']);
      const choices = await page.evaluate(() => [...document.querySelectorAll('.lb-guide-choice .setting-item-name')].map(e => e.textContent));
      assert.deepEqual(choices, ['用免费的 Gemini', '用付费的（DeepSeek / 阿里云）', '先不用'], '一次最多三个选项');
      await shot(page, 'S1016-settings-guide-3-light.png');
      await page.locator('.lb-guide-nav button', { hasText: '跳过指引' }).click(); await page.waitForTimeout(200);
      assert.equal(await page.evaluate(() => window.l4.plugin.settings.onboarding.guideDone), true, '跳过 = 走完，不再出');
      assert.deepEqual(errors, []);
      await page.close();
    }
    // 读不到的块：一句人话 + 重试，原始报错折在「详情」里
    {
      const { page, errors } = await open(browser, 'light', { failRemote: true });
      await clickTab(page, '更多');
      await page.waitForFunction(() => document.querySelector('.lb-remote-svc .lb-fail'));
      const fb = await page.evaluate(() => { const f = document.querySelector('.lb-remote-svc .lb-fail'); const d = f.querySelector('details'); return { line: f.querySelector('.lb-fail-line').textContent, open: d.open, raw: d.textContent }; });
      assert.match(fb.line, /这一块暂时读不到，点重试/);
      assert.equal(fb.open, false, '原始报错默认折着');
      assert.match(fb.raw, /详情.*状态命令崩了/);
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  fs.mkdirSync(shell.QA_DIR, { recursive: true });
  fs.writeFileSync(path.join(shell.QA_DIR, 'S1016-settings-rows.json'), JSON.stringify(summary, null, 2));
  console.log('PASS 1016 settings (real Chromium, light / dark / third-party): tabs 概览 · 同步 · AI · 更多; overview = account + collection + records; sync = 3 rows + fold; AI = one row per provider with its features + usage + folded details; no nested boxes; no jargon; first-run 4-step guide; unreadable block -> retry + folded details. Screenshots: ' + shell.QA_DIR);
})().catch(error => { console.error(error); process.exitCode = 1; });

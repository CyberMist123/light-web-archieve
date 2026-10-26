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
const sources = Object.fromEntries(['main', 'home-ui', 'remote-ui', 'schedule-ui', 'onboarding-ui', 'index-ui', 'skills-ui', 'usage-ui', 'settings-pages', 'settings-v6', 'provider-icons'].map(name =>
  [name + '.js', fs.readFileSync(path.join(root, name + '.js'), 'utf8')]));
const TABS = ['概览', '同步', 'AI', '接其他 AI', '更多'];   // 1018：接其他 AI 升成独立页签
// 新手主界面（不算「连接其他 AI」里的高级折叠）上不该看到的词（她 1010 点名的术语；要留的旁边有人话解释）
const JARGON = ['OAuth', 'Bearer', 'Authorization', 'launchd', 'systemd', '标准输入', '标准输出', '扩检索词', '归档摘要模型', '认领', '令牌', '没画上', '读不到状态：', '读不到功能清单：'];

async function open(browser, theme, { failRemote = false, guide = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1300, height: 1400 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  page.on('console', m => { if (m.type() === 'error') console.log('[console]', m.text()); });
  await shell.settings(page, { theme, contentWidth: 800 });
  // 可选：加载本机 Obsidian 自带的 app.css（从安装包里取出来的那份，不进仓库），看真主题样式下有没有框套框
  if (process.env.LWA_OBSIDIAN_CSS && fs.existsSync(process.env.LWA_OBSIDIAN_CSS)) await page.addStyleTag({ path: process.env.LWA_OBSIDIAN_CSS });
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
      if (sub.startsWith('connect status')) return { ok: true, clients: { 'claude-code': { installed: true, connected: false, command: 'claude mcp add lwa -s user -- python -m link_brain mcp' }, 'claude-desktop': { installed: false, connected: false } }, json: '{}',
        apps: [{ id: 'claude-code', name: 'Claude Code', installed: true, oneclick: true, version: '2.1.302', connected: true },
          { id: 'codex', name: 'Codex', installed: true, oneclick: true, version: '0.146.0', connected: false },
          { id: 'opencode', name: 'OpenCode', installed: true, oneclick: false, version: '1.19.3', connected: false }], not_installed: ['Pi', 'Grok Build', 'DeepSeek Harness'] };
      if (sub.startsWith('connect add') || sub.startsWith('connect remove')) return { ok: true, changed: true, message: '已接到 Codex' };
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
            windows: Object.fromEntries(['today', '7d', '30d'].map(w => [w, { total: { ...total, free: 40 }, features,
              providers: { aliyun: f({ calls: 472, in: 1000000, out: 70000, cost: 1.42 }), deepseek: f({ calls: 46, in: 420000, out: 33000, cost: 1.05 }), google: f({ calls: 40, free: 40 }) },
              models: { 'aliyun|qwen3.8-flash': f({ provider: 'aliyun', model: 'qwen3.8-flash', calls: 412, cost: 0.86 }), 'google|gemini-3.5-flash': f({ provider: 'google', model: 'gemini-3.5-flash', calls: 40, free: 40 }),
                'google|gemini-embedding-2': f({ provider: 'google', model: 'gemini-embedding-2', calls: 5, unpriced: 5 }) },
              unpriced_models: [{ provider: 'google', model: 'gemini-embedding-2', calls: 5 }] }])),
            recent: [{ ts: new Date().toISOString(), f: 'vision', p: 'aliyun', m: 'qwen3.8-flash', in: 2100, out: 150, ok: true, item: 'xhs-synthetic-1', cost: 0.0021, status: 'paid' }], recent_limit: 200,
            month: { deepseek: f({ calls: 46, cost: 1.05 }), aliyun: f({ calls: 512, cost: 1.80 }) } } };
        // 1018 AI 页重排：每个功能用谁（主用 → 备用）+ 每天上限
        const G = (label, extra = {}) => ({ label, provider: 'google', model: 'gemini-3.5-flash', free: true, price: '免费', key: '3 把轮流用', ...extra });
        const Q = (model, price) => ({ label: '通义千问 ' + model, provider: 'aliyun', model, free: false, price, key: '密钥文件 keys.csv 里的「apiKey」' });
        const D = price => ({ label: 'DeepSeek deepseek-v4-flash', provider: 'deepseek', model: 'deepseek-v4-flash', free: false, price, key: '密钥文件 keys.csv 里的「ds」' });
        out.budget = { daily_yuan: 3, spent_today: 0.83, day: '2026-10-18', over: false };
        out.features = [
          { id: 'ask', name: '问收藏', cap: 'textAI', on: true, chain: [D('约 ¥0.02/次')], state: 'ok', state_text: '正常', choices: ['DeepSeek', 'Codex', 'Sonnet'], active: 'DeepSeek' },
          { id: 'summary', name: '概要 · 打标签', cap: 'summaryAI', on: true, chain: [G('Google gemini-3.5-flash'), Q('qwen3.7-flash', '约 ¥0.16/百篇'), D('约 ¥1.63/百篇')], state: 'ok', state_text: '正常' },
          { id: 'vision', name: '识图', cap: 'visionAI', on: true, chain: [G('Google gemini-3.5-flash'), Q('qwen3.8-flash', '约 ¥0.20/百张'), Q('qwen3.8-max', '约 ¥2.91/百张')],
            state: 'backup', state_text: '主用的暂时不行，通义千问 qwen3.8-flash 顶着' },
          { id: 'refine', name: '精细识图', cap: 'visionAI.refine', on: true, chain: [G('Gemini 免费（3 把 key）'), Q('qwen3.8-max', '约 ¥6.07/百张')], state: 'ok', state_text: '正常' },
          { id: 'embed', name: '语义搜索', cap: 'embedAI', on: true, chain: [Q('qwen3.7-text-embedding-flash', '约 ¥0.02/百次')], state: 'ok', state_text: '正常' }];
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
    if (!guide) plugin.settings.onboarding = { guideDone: true };
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
    window.l4runs = 0;
    plugin.homeUI().runAll = async () => { window.l4runs++; return { ok: true }; };   // 首次设置「完成」后一口气跑：替身
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

// 1018 v6：边框套边框（卡片里再有一圈实线边框的大块）不许有；卡片本身是她批的样子
const nestedBoxes = page => page.evaluate(() => {
  const pane = document.querySelector('.lb-tab-pane');
  const boxed = e => { const cs = getComputedStyle(e); return ['Top', 'Bottom', 'Left', 'Right'].every(s => cs['border' + s + 'Style'] === 'solid' && parseFloat(cs['border' + s + 'Width']) > 0)
    && parseFloat(cs.borderTopLeftRadius) >= 6 && !e.closest('.checkbox-container, .dropdown, button, input, textarea, .lb-usage-grid, .lb-guide-dot, .lb-pv') && e.getBoundingClientRect().height > 40; };
  const boxes = [...pane.querySelectorAll('div, details, section')].filter(boxed);
  return boxes.filter(b => boxes.some(o => o !== b && o.contains(b))).map(e => e.className);
});
const cards = page => page.evaluate(() => [...document.querySelectorAll('.lb-v6 > .lb-card')].map(c => c.getAttribute('data-section') + ':' + c.querySelector('.lb-card-title').textContent));
const rowsIn = (page, sel) => page.evaluate(sel => [...document.querySelectorAll(sel + ' .setting-item')].map(r => (r.querySelector('.setting-item-name')?.textContent || '').replace(/\?$/, '').trim()), sel);

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const summary = {};
  try {
    for (const theme of ['light', 'dark', 'orange']) {
      const { page, errors } = await open(browser, theme);
      // ① 一页五张卡；状态卡读回用量后：灯黄（百炼 key 用不了）+ 一句 + 去充值 / 换一个 key
      await page.waitForFunction(() => /今天 ¥0\.83/.test(document.querySelector('[data-section="s-status"]')?.textContent || '') && document.querySelectorAll('.lb-app').length >= 3);
      await page.waitForTimeout(300);
      assert.equal(await page.locator('.lb-tabs').count(), 0, '没有页签');
      // 1026（录屏场景 08）：按要做的事排六组
      assert.deepEqual(await cards(page), ['s-status:状态', 's-xhs:收藏与同步', 's-content:内容、目录及管理', 's-ai:识别与问答', 's-cost:模型与费用', 's-mcp:外部 AI 接入', 's-more:高级 / 修复']);
      const status = await rowsIn(page, '[data-section="s-status"]');
      assert.deepEqual(status, ['小红书 · momo · ✓ 已登录', '收藏同步', 'API 费用', '识别', '读取']);
      assert.ok(await page.locator('[data-section="s-status"] .lb-lamp.is-warn').count(), theme + '：key 用不了 → 黄灯');
      const fix = await page.evaluate(() => document.querySelector('.lb-fix-line')?.textContent || '');
      assert.match(fix, /通义千问 key 用不了.*去充值 ↗.*换一个 key/);
      assert.match(await page.evaluate(() => document.querySelector('[data-section="s-status"]').textContent), /已接入 Claude Code/);
      const ai = await rowsIn(page, '[data-section="s-ai"]');
      assert.deepEqual(ai, ['识图', '语音', '按意思搜', '概要', 'AI 识图', '问收藏用的模型'], theme + ' 识别与问答：' + ai);
      const chips = await page.evaluate(() => [...document.querySelectorAll('[data-section="s-ai"] .lb-pv')].map(x => x.getAttribute('data-provider') || x.textContent));
      assert.deepEqual(chips, ['google', 'deepseek', 'aliyun', '＋ 添加 key']);
      const apps = await page.evaluate(() => [...document.querySelectorAll('.lb-app')].map(r => r.getAttribute('data-app') + ':' + r.querySelector('.setting-item-description').textContent));
      assert.deepEqual(apps, ['claude-code:已接入', 'codex:自动检测', 'opencode:自动检测 · 复制设置，粘进它的 MCP 设置', 'other:Cursor 等支持 MCP 的软件：复制设置，粘进它的 MCP 设置']);
      assert.equal(await page.locator('.lb-app[data-app="codex"] .lb-app-icon svg').count(), 1, 'Codex 用 Claudian 的图标');
      assert.equal(await page.evaluate(() => document.querySelector('.lb-app[data-app="codex"] .lb-app-ver').textContent), 'v0.146.0');
      const text = await page.evaluate(() => document.querySelector('.lb-tab-pane').innerText);
      assert.deepEqual(JARGON.filter(w => text.includes(w)), [], theme + '：明面上没有术语');
      assert.ok(await page.locator('.lb-tab-pane button.mod-cta').count() <= 1, '最多一个主按钮');
      assert.deepEqual(await nestedBoxes(page), [], theme + '：卡片里不再套框');
      // 1018 晚她：照 Claudian——卡片透明底 + 一圈细边，卡里的行不再各自带底色 / 边框
      const rowBoxes = await page.evaluate(() => [...document.querySelectorAll('.lb-v6 .lb-card .setting-item')].filter(r => { const cs = getComputedStyle(r);
        return cs.backgroundColor !== 'rgba(0, 0, 0, 0)' || parseFloat(cs.borderTopLeftRadius) > 0 || cs.borderLeftStyle === 'solid'; }).map(r => r.querySelector('.setting-item-name')?.textContent));
      assert.deepEqual(rowBoxes, [], theme + '：行不再自带底色 / 圆角 / 边框');
      summary[theme] = { cards: await cards(page), 状态: status, 识别与问答: ai, 接入: apps };
      await shot(page, `S1018v6-settings-${theme}.png`);
      for (const sec of ['s-xhs', 's-content', 's-ai', 's-cost', 's-mcp', 's-more']) await page.locator(`.lb-card[data-section="${sec}"]`).screenshot({ path: path.join(shell.QA_DIR, `S1018v6-card-${sec}-${theme}.png`) });
      // ② 接入 Codex：开关 → connect add codex → 「已接入」
      await page.evaluate(() => document.querySelector('.lb-app[data-app="codex"] .checkbox-container').click()); await page.waitForTimeout(200);   // 外壳的开关没有尺寸：走 DOM 点
      assert.equal(await page.evaluate(() => document.querySelector('.lb-app[data-app="codex"] .setting-item-description').textContent), '已接入');
      // 1026（录屏 23:23 / 23:34）：点状态行的字（不只是小箭头）→ 滚到能改的那一格、焦点落进去、闪一下
      const inView = sel => page.evaluate(sel => { const el = document.querySelector(sel), box = document.querySelector('.vertical-tab-content');
        const r = el.getBoundingClientRect(), b = box.getBoundingClientRect(); return r.top >= b.top - 1 && r.bottom <= b.bottom + 1; }, sel);
      await page.evaluate(() => { document.querySelector('.vertical-tab-content').scrollTop = 0; });
      await page.locator('[data-section="s-status"] .setting-item[data-jump="ai-spend"] .setting-item-name').click(); await page.waitForTimeout(900);
      assert.ok(await inView('[data-section="ai-spend"] input.lb-spend-input'), theme + '：点「API 费用」→ 每天上限那一格在视野里');
      assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('[data-section="ai-spend"] input.lb-spend-input')), true, theme + '：焦点落进每天上限');
      assert.ok(await page.locator('[data-section="ai-spend"].lb-flash').count(), theme + '：落地那一块闪一下');
      await page.evaluate(() => { document.querySelector('.vertical-tab-content').scrollTop = 0; });
      await page.locator('[data-section="s-status"] .lb-sync-row button', { hasText: '改时间' }).click(); await page.waitForTimeout(900);
      assert.ok(await inView('[data-section="sync-time"] .lb-sched-times'), theme + '：「改时间」→ 自动同步时间那一格在视野里（不是卡片顶）');
      await page.evaluate(() => { document.querySelector('.vertical-tab-content').scrollTop = 0; });
      await page.locator('[data-section="s-status"] .setting-item[data-jump="mcp-apps"] .setting-item-name').click(); await page.waitForTimeout(900);
      assert.ok(await inView('[data-section="mcp-apps"] .lb-app'), theme + '：点「读取」→ 接入电脑端那几行');
      // 花了多少：三种看法切换（人民币；免费的不算进 ¥；未计价的点名）
      await page.locator('.lb-usage-dim', { hasText: '按 API 或模型' }).click(); await page.waitForTimeout(100);
      const modelRows = await page.evaluate(() => [...document.querySelectorAll('.lb-usage-grid[data-dim="models"] tr')].map(tr => [...tr.children].map(td => td.textContent)));
      assert.ok(modelRows.some(r => r[0] === 'gemini-3.5-flash · Gemini' && r.at(-1) === '免费 / 未计费'), theme + '：免费 key 写免费 / 未计费：' + JSON.stringify(modelRows));
      assert.ok(modelRows.some(r => r[0] === 'gemini-embedding-2 · Gemini' && r.at(-1) === '未计价'));
      assert.match(await page.evaluate(() => document.querySelector('.lb-usage-gaps').textContent), /未计价.*gemini-embedding-2/);
      await page.locator('.lb-usage-dim', { hasText: '按服务商' }).click(); await page.waitForTimeout(100);
      await page.locator('.lb-card[data-section="s-cost"]').screenshot({ path: path.join(shell.QA_DIR, `S1026-cost-providers-${theme}.png`) });
      await page.locator('.lb-usage-dim', { hasText: '按功能' }).click(); await page.waitForTimeout(100);
      // ③ 每天上限（只在「模型与费用」一处）：改了立刻存
      await page.locator('[data-section="ai-spend"] input.lb-spend-input').fill('5'); await page.locator('[data-section="ai-spend"] input.lb-spend-input').dispatchEvent('change'); await page.waitForTimeout(100);
      assert.equal(await page.evaluate(() => window.l4.plugin.settings.budget.dailyYuan), 5);
      // ④a 网页端怎么接：点开是步骤 + 一键复制
      await page.locator('details[data-section="web-howto"] > summary .lb-rf-name').click(); await page.waitForTimeout(150);
      await page.locator('.lb-card[data-section="s-mcp"]').screenshot({ path: path.join(shell.QA_DIR, `S1018v6-web-howto-${theme}.png`) });
      // ④ 网页端那一行点开：远程访问那几格
      await page.locator('details[data-section="remote"] > summary').click();
      await page.waitForFunction(() => /● 开着/.test(document.querySelector('.lb-remote-svc')?.textContent || ''));
      assert.ok(!/OAuth/.test(await page.evaluate(() => document.querySelector('details[data-section="remote"]').innerText)), '界面上没有 OAuth');
      // ⑤ 模型与费用 → 每个功能用谁：每一项（主用 → 备用）平铺，点开识图有接口 / 模型
      await page.waitForFunction(() => document.querySelectorAll('[data-section="s-cost"] .lb-route').length >= 8);
      await page.locator('.lb-route[data-feature="vision"] > summary').click(); await page.waitForTimeout(200);
      const visionRows = await rowsIn(page, '.lb-route[data-feature="vision"]');
      for (const n of ['接口地址', '模型名']) assert.ok(visionRows.includes(n), `${theme} 识图展开缺「${n}」：${visionRows}`);
      await shot(page, `S1018v6-settings-open-${theme}.png`);
      assert.deepEqual(errors, []);
      await page.close();
    }
    // ⑥ 库里还没收藏：首次设置（欢迎页 → 自定义四步 → 完成变状态页）
    {
      const { page, errors } = await open(browser, 'light', { guide: true });
      await page.waitForFunction(() => document.querySelector('.lb-guide .lb-big'));
      assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('.lb-big-name')].map(e => e.textContent)), ['推荐设置，一键开始', '自定义']);
      await shot(page, 'S1018v6-guide-0-light.png');
      await page.locator('button.lb-big', { hasText: '自定义' }).click(); await page.waitForTimeout(150);
      const g = () => page.evaluate(() => ({ title: document.querySelector('.lb-guide .lb-card-title').textContent,
        steps: [...document.querySelectorAll('.lb-guide-step')].map(s => s.className.replace('lb-guide-step', '').trim() + ':' + s.textContent) }));
      const seen = [];
      for (let k = 1; k <= 4; k++) {
        await page.waitForTimeout(250);
        const st = await g(); seen.push(st.title);
        if (k === 3) assert.deepEqual(st.steps, ['is-done:登录小红书✓', 'is-done:同步✓', 'is-on:识别与问答3', ':接入其他 AI4']);
        await shot(page, `S1018v6-guide-${k}-light.png`);
        if (k < 4) { await page.locator('.lb-guide-nav button', { hasText: '下一步' }).click(); await page.waitForTimeout(200); }
      }
      assert.deepEqual(seen, ['登录小红书', '同步', '识别与问答', '接入其他 AI（MCP）']);
      await page.locator('.lb-guide-nav button', { hasText: '完成' }).click();
      await page.waitForFunction(() => document.querySelector('.lb-card[data-section="s-status"]'));
      assert.equal(await page.evaluate(() => window.l4.plugin.settings.onboarding.guideDone), true);
      assert.equal(await page.evaluate(() => window.l4runs), 1, '完成后开始一口气跑');
      assert.deepEqual(errors, []);
      await page.close();
    }
    // 读不到的块：一句人话 + 重试，原始报错折在「详情」里
    {
      const { page, errors } = await open(browser, 'light', { failRemote: true });
      await page.locator('details[data-section="remote"] > summary').click();
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
  fs.writeFileSync(path.join(shell.QA_DIR, 'S1018v6-settings-rows.json'), JSON.stringify(summary, null, 2));
  console.log('PASS 1018 settings v6 (real Chromium, light / dark / third-party; 1026 regrouped into six task groups, status rows land on the editable control, cost views by provider / model / feature): one page of cards; status card lamp + key trouble line; recognition rows; installed AI apps + one-click Codex; budget saves; web row folds out remote access; per-feature models under 更多; no box-in-box; no jargon; first-run welcome + 4 steps -> status page; unreadable block -> retry + folded details. Screenshots: ' + shell.QA_DIR);
})().catch(error => { console.error(error); process.exitCode = 1; });

'use strict';
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
const sources = Object.fromEntries(['main', 'home-ui', 'remote-ui', 'schedule-ui', 'onboarding-ui', 'index-ui', 'skills-ui', 'usage-ui'].map(name =>
  [name + '.js', fs.readFileSync(path.join(root, name + '.js'), 'utf8')]));
const TABS = ['通用', '模型与提供商', '技能'];
// 新手主界面（不算「连接其他 AI」里的高级折叠）上不该看到的词（她 1010 点名的术语；要留的旁边有人话解释）
const JARGON = ['OAuth', 'Bearer', 'Authorization', 'launchd', 'systemd', '标准输入', '标准输出', '扩检索词', '归档摘要模型', '认领', '令牌', '没画上', '读不到状态：', '读不到功能清单：'];

async function open(browser, theme, { failRemote = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1300, height: 1400 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await shell.settings(page, { theme, contentWidth: 800 });
  await page.evaluate(([sources, failRemote]) => {
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
    const app = { workspace: { trigger() {}, getActiveFile: () => null },
      vault: { adapter: { getBasePath: () => '/synthetic-vault', exists: async f => f in files || (f === '_skills' && window.l4skills.length > 0), read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; },
        list: async dir => ({ folders: window.l4skills.map(id => dir + '/' + id), files: [] }) }, getAllLoadedFiles: () => [] },
      metadataCache: { getFileCache: () => ({}) } };
    const plugin = new Plugin(app, { id: 'link-brain-actions', dir: '' });
    plugin.settings = Plugin.merge({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'sample-text' },
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
    plugin.remoteUI = require('remote-ui.js')(window.obsidian, plugin);
    const tab = new Plugin.Tab(app, plugin);
    tab.containerEl = document.querySelector('.vertical-tab-content');
    plugin.settingTab = tab;
    window.l4 = { plugin, tab, Plugin };
    tab.display();
  }, [sources, failRemote]);
  return { page, errors };
}

// 当前那一栏的读数
const readPane = page => page.evaluate(JARGON => {
  const pane = document.querySelector('.lb-tab-pane');
  const vis = el => { for (let n = el; n && n !== pane; n = n.parentElement) { if (n.tagName === 'DETAILS' && !n.open && el !== n.querySelector('summary') && !n.querySelector('summary').contains(el)) return false; if (n.hidden) return false; } return true; };
  const rows = [...pane.querySelectorAll('.setting-item')].filter(vis).map(r => (r.querySelector('.setting-item-name')?.textContent || '').replace(/\?$/, '').trim());
  // 「连接其他 AI」最下面的「高级」折叠（访问令牌就在那里）整块不算新手主界面
  const textOf = node => { if (node.nodeType === 3) return node.textContent; if (node.nodeType !== 1) return ''; if (node.classList.contains('lb-connect-adv')) return '';
    if (node.tagName === 'DETAILS' && !node.open) return node.querySelector('summary')?.textContent || ''; return [...node.childNodes].map(textOf).join(' '); };
  const text = textOf(pane);
  return { tab: pane.getAttribute('data-tab'), rows, cta: pane.querySelectorAll('button.mod-cta').length, ctaText: [...pane.querySelectorAll('button.mod-cta')].map(b => b.textContent),
    jargon: JARGON.filter(w => text.includes(w)), text,
    tabs: [...document.querySelectorAll('.lb-tabs .lb-tab')].map(b => b.textContent), active: [...document.querySelectorAll('.lb-tabs .lb-tab.is-active')].map(b => b.textContent) };
}, JARGON);
const clickTab = async (page, label) => { await page.locator('.lb-tabs .lb-tab', { hasText: label }).first().click(); await page.waitForTimeout(150); };

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const summary = {};
  const tap = (page, sel) => page.evaluate(s => document.querySelector(s).click(), sel);   // 外壳 CSS 子集里开关 0×0：直接在元素上点
  const clickSub = async (page, label) => { await page.locator('.lb-subtabs .lb-subtab', { hasText: label }).first().click(); await page.waitForTimeout(150); };
  // 卡片样子（她 1015：照 claudian）：圆角、有边框、标题加粗 + 下面一条分隔线
  const cardLook = page => page.evaluate(() => [...document.querySelectorAll('.lb-tab-pane .lb-card')].map(c => {
    const cs = getComputedStyle(c), head = c.querySelector('.lb-card-head'), title = c.querySelector('.lb-card-title');
    return { title: title.textContent, radius: parseFloat(cs.borderTopLeftRadius), border: cs.borderTopStyle, weight: Number(getComputedStyle(title).fontWeight),
      sep: getComputedStyle(head).borderBottomStyle, overflow: c.scrollWidth - c.clientWidth };
  }));
  try {
    for (const theme of ['light', 'dark', 'orange']) {
      const { page, errors } = await open(browser, theme);
      // ① 三个页签，默认通用
      await page.waitForFunction(() => document.querySelector('.lb-run-go') && /已补齐 7\/197/.test(document.querySelector('.lb-fill-row')?.textContent || '')
        && document.querySelector('.lb-sched-row') && !document.querySelector('.lb-sched-rows.is-loading') && /● 开着/.test(document.querySelector('.lb-remote-svc')?.textContent || ''));
      let p = await readPane(page);
      assert.deepEqual(p.tabs, TABS); assert.deepEqual(p.active, ['通用']);
      assert.equal(p.tab, 'general');
      // 下划线页签：选中那个有下划线
      const tabLine = await page.evaluate(() => { const a = document.querySelector('.lb-tabs .lb-tab.is-active'), o = document.querySelector('.lb-tabs .lb-tab:not(.is-active)');
        return { active: getComputedStyle(a).borderBottomStyle + ' ' + parseFloat(getComputedStyle(a).borderBottomWidth), other: getComputedStyle(o).borderBottomColor, activeColor: getComputedStyle(a).borderBottomColor }; });
      assert.equal(tabLine.active, 'solid 2'); assert.notEqual(tabLine.activeColor, tabLine.other, theme + '：选中的页签下划线有颜色');
      // ② 通用：每组一张卡片
      const looks = await cardLook(page);
      assert.deepEqual(looks.map(l => l.title), ['状态', '收藏', '定时同步', '目录与批注', '附件手动下载', '连接其他 AI', '开发者']);
      for (const l of looks) {
        assert.ok(l.radius >= 8 && l.border === 'solid' && l.weight >= 600 && l.sep === 'solid', theme + '：卡片样子 ' + JSON.stringify(l));
        assert.ok(l.overflow <= 1, theme + '：卡片里不出横向滚动 ' + JSON.stringify(l));
      }
      for (const n of ['小红书 · momo · ✓ 已登录', '收藏同步', '评论补齐', '问题', '这台电脑', '收藏放在哪', '自动同步', '每次同步最多收几篇', '每天最多新收几篇',
        '下载图片', '下载视频', '每篇评论抓几楼', '补评论节奏', '登录后自动同步', '批注署名', '留言对象', '下载文件夹', '后端命令', '检查这台电脑'])
        assert.ok(p.rows.includes(n), `${theme} 通用缺「${n}」：${p.rows}`);
      assert.deepEqual(p.ctaText, ['一键装好 / 跑完'], theme + '：通用唯一的主按钮（「保存定时」在这里是次要的）');
      const schedRows = await page.evaluate(() => [...document.querySelectorAll('.lb-card[data-section="schedule"] .setting-item-name')].map(e => e.textContent.replace(/\?$/, '')));
      assert.deepEqual(schedRows, ['自动同步', '每次同步最多收几篇', '每天最多新收几篇', '每篇评论抓几楼', '补评论节奏'], '同步篇数、补评论都在「定时同步」卡片');
      assert.ok(!p.rows.some(r => /评论 · (自动|手动)拉取/.test(r)), '「自动拉取」「手动拉取」合成了一项');
      assert.match(p.text, /打开那篇，在右上角 ⋮ 菜单里点「抓全部评论」/, '手动的差别一行小字');
      assert.equal(await page.evaluate(() => document.querySelector('.lb-cats-fold').open), false, '目录分类默认收起');
      // 10-10 索引树：目录分类 = 编辑索引 / AI 起草 / 未归类建议 / 重新整理目录（次要链接，放得下）+ 索引文件路径；文本框退场
      await page.evaluate(() => { const d = document.querySelector('.lb-cats-fold'); d.open = true; window.l4seen = []; const rp = l4.plugin.runPy;
        l4.plugin.runPy = async (a, o) => { window.l4seen.push(a.slice(2).join(' ')); return rp(a, o); }; window.l4rp = rp; });
      await page.locator('.lb-cats-actions button', { hasText: 'AI 起草' }).click();
      await page.waitForFunction(() => window.l4seen.includes('index draft') && !document.querySelector('.lb-cats-actions button.is-busy'));
      const cats = await page.evaluate(() => {
        const det = document.querySelector('.lb-cats-fold'), card = det.closest('.lb-card').getBoundingClientRect();
        const row = det.querySelector('.lb-cats-actions'), btns = [...row.querySelectorAll('button')];
        const out = { names: btns.map(b => b.textContent), cta: btns.filter(b => b.classList.contains('mod-cta')).length, textarea: !!det.querySelector('textarea'),
          inside: btns.every(b => { const r = b.getBoundingClientRect(); return r.width > 0 && r.left >= card.left - 1 && r.right <= card.right + 1; }),
          overflow: row.scrollWidth - row.clientWidth, placeholder: det.querySelector('input')?.getAttribute('placeholder'), seen: window.l4seen.slice() };
        l4.plugin.runPy = window.l4rp; det.open = false;
        return out;
      });
      assert.deepEqual(cats.names, ['打开 索引.md', 'AI 起草', '未归类建议', '重新整理目录'], theme + '：目录分类那一行的链接');
      assert.equal(cats.cta, 0, '目录分类里没有主按钮'); assert.equal(cats.textarea, false, '「名称: 关键词」文本框退场');
      assert.ok(cats.inside && cats.overflow <= 1, theme + '：目录分类的链接放得下（不出横向滚动）' + JSON.stringify(cats));
      assert.equal(cats.placeholder, '索引.md'); assert.deepEqual(cats.seen, ['index draft'], '点「AI 起草」跑的是 index draft');
      // 连接其他 AI（通用里的一张卡片）
      for (const n of ['Claude Code', '远程访问', '你的网址', '连接地址', '口令', '小红书收藏库', '再开放一个文件夹']) assert.ok(p.rows.includes(n), `${theme} 连接缺「${n}」：${p.rows}`);
      const near = await page.evaluate(() => { const d = document.querySelector('.lb-remote-domain'); const n = d.nextElementSibling; return { next: n && n.tagName + '.' + n.className, open: n && n.open }; });
      assert.equal(near.next, 'DETAILS.lb-remote-nodomain', '「还没有网址？」紧挨着网址那一格');
      assert.equal(near.open, true, '没填网址：两条路默认展开');
      assert.match(p.text, /Cloudflare/); assert.match(p.text, /Tailscale/);
      assert.ok(!/OAuth/.test(p.text), '界面上没有 OAuth');
      assert.equal(await page.evaluate(() => document.querySelector('.lb-connect-adv').open), false, '高级折叠默认收起');
      const addr = await page.evaluate(() => { const r = [...document.querySelectorAll('.setting-item')].find(x => x.querySelector('.setting-item-name')?.textContent === '连接地址'); return { disabled: r.querySelector('button').disabled, desc: r.querySelector('.setting-item-description').textContent }; });
      assert.ok(addr.disabled && /先填上面的网址/.test(addr.desc), '复制按钮不能点时旁边一句为什么');
      assert.deepEqual(p.jargon, [], theme + '：通用没有术语 / 原始报错');
      summary[theme] = { 通用: p.rows };
      await page.evaluate(() => { document.querySelector('.vertical-tab-content').scrollTop = 0; });
      await page.screenshot({ path: path.join(shell.QA_DIR, `S1015-settings-general-${theme}.png`), fullPage: true });
      await page.locator('.lb-connect-adv > summary').click(); await page.waitForTimeout(200);
      const advRows = await page.evaluate(() => [...document.querySelectorAll('.lb-connect-adv .setting-item-name')].map(e => e.textContent.replace(/\?$/, '')));
      for (const n of ['远程访问的运行情况', '端口', '访问令牌（给不支持口令的软件）', '全部断开']) assert.ok(advRows.includes(n), '高级折叠缺「' + n + '」' + advRows);
      assert.ok(await page.locator('.lb-connect-adv button', { hasText: '测一下本机的连接程序（MCP）' }).count(), '测本机连接程序在这里');

      // ③ 模型与提供商：子页签
      await clickTab(page, '模型与提供商');
      await page.waitForFunction(() => document.querySelectorAll('.lb-feat').length >= 4 && document.querySelector('.lb-key-row'));
      p = await readPane(page);
      assert.equal(p.tab, 'providers');
      assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('.lb-subtabs .lb-subtab')].map(b => b.textContent)), ['AI 功能', '问收藏模型', '识图 · 认字 · 语音', '提示词', '用量与余额']);
      assert.match(p.text, /要不要 AI：不填也能用；填了多出 问收藏、自动概要、识图。/);
      const prices = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('.lb-feat')].map(r => [r.getAttribute('data-id'), r.querySelector('.lb-price')?.textContent || ''])));
      assert.equal(prices.ocr, '免费（本机跑）'); assert.equal(prices.asr, '免费（本机跑）');
      assert.equal(prices.ai_text, '概要和打标签 约 ¥0.80 / 100 篇 · 问收藏 约 ¥0.004 / 次');
      assert.equal(prices.ai_vision, '按用量', '估不出价的写「按用量」');
      assert.ok(!('capslock' in prices), '子选项（CapsLock 说话）只在「视频说话转文字」打开后出现');
      for (const n of ['接口地址', '密钥（API Key）', '模型名']) assert.ok(p.rows.includes(n), `${theme} AI 缺「${n}」`);
      assert.ok(p.rows.some(r => /^DeepSeek（概要和打标签、问收藏）$/.test(r)), '去哪弄密钥：按服务商合一行 ' + p.rows);
      assert.equal(p.cta, 0, theme + '：AI 功能没有主按钮（测试是次要的）');
      assert.deepEqual(p.jargon, []);
      await tap(page, '.lb-feat[data-id="asr"] .checkbox-container'); await page.waitForTimeout(150);
      assert.ok(await page.locator('.lb-feat[data-id="capslock"]').count(), '父开关打开后，子选项出现');
      summary[theme]['AI 功能'] = (await readPane(page)).rows;
      await page.screenshot({ path: path.join(shell.QA_DIR, `S1015-settings-providers-${theme}.png`), fullPage: true });
      // 开关存失败：拨回原值 + 提示一句；外壳开关照 1.14.4 会因 setValue 再触发 onChange——不能来回弹
      await page.evaluate(() => { window.saveFails = 1; });
      await tap(page, '.lb-feat[data-id="capslock"] .checkbox-container'); await page.waitForTimeout(200);
      const rev = await page.evaluate(() => ({ on: document.querySelector('.lb-feat[data-id="capslock"] .checkbox-container').classList.contains('is-enabled'),
        sel: window.l4.plugin.settings.setup.selected.includes('capslock'), notices: [...document.querySelectorAll('.notice')].map(n => n.textContent) }));
      assert.equal(rev.on, false, '存失败：开关拨回关'); assert.equal(rev.sel, false, '设置也还原了');
      assert.ok(rev.notices.some(t => t.includes('没保存上，开关已拨回原来的位置')), rev.notices.join(' | '));
      // 问收藏模型：勾选列表（勾选框在行的最左边）
      await clickSub(page, '问收藏模型');
      p = await readPane(page);
      const models = await page.evaluate(() => [...document.querySelectorAll('.lb-model-row')].map(r => { const cb = r.querySelector('.lb-model-check'), nm = r.querySelector('.setting-item-name');
        return { name: nm.textContent, checked: cb.checked, left: cb.getBoundingClientRect().right <= nm.getBoundingClientRect().left + 1 }; }));
      assert.deepEqual(models.map(m => m.name), ['文本 AI', 'Codex', 'Sonnet']);
      assert.ok(models.every(m => m.checked && m.left), theme + '：勾选框在左边、默认勾着 ' + JSON.stringify(models));
      for (const n of ['输入框里的提示字', '提问时先想几个同义词一起搜', '问收藏 / 概要改用本机命令行', '回答最长多少（max_tokens）', '最多参考几篇（topK）']) assert.ok(p.rows.includes(n), `${theme} 问收藏模型缺「${n}」`);
      assert.ok(p.cta <= 1);
      await page.screenshot({ path: path.join(shell.QA_DIR, `S1015-settings-models-${theme}.png`), fullPage: true });
      await clickSub(page, '识图 · 认字 · 语音');
      p = await readPane(page);
      for (const n of ['写概要用的模型', '认视频画面里的字', '认字精度']) assert.ok(p.rows.includes(n), `${theme} 识图 · 认字 · 语音缺「${n}」：${p.rows}`);
      summary[theme]['识图 · 认字 · 语音'] = p.rows;
      await clickSub(page, '提示词');
      p = await readPane(page);
      assert.deepEqual(p.rows, ['写概要的提示词', '问收藏的提示词']);
      // 1016 用量与余额：每家一行（余额 / 本月 / 密钥状态 + 三个跳转），各功能明细表不横向溢出
      await clickSub(page, '用量与余额');
      await page.waitForFunction(() => /105\.38/.test(document.querySelector('.lb-usage-provider[data-provider="deepseek"]')?.textContent || ''));
      const u = await page.evaluate(() => ({ btns: [...document.querySelectorAll('.lb-usage-provider[data-provider="deepseek"] button')].map(b => b.textContent),
        rows: document.querySelectorAll('.lb-usage-grid tr').length, cta: document.querySelectorAll('.lb-tab-pane .mod-cta').length,
        warn: document.querySelector('.lb-usage-provider[data-provider="aliyun"] .lb-usage-key')?.textContent || '',
        overflow: (t => t.scrollWidth - t.clientWidth)(document.querySelector('.lb-usage-table')) }));
      assert.deepEqual(u.btns, ['控制台', '充值', '看用量']);
      assert.equal(u.rows, 9, '表头 + 7 个功能 + 合计');
      assert.ok(u.warn.includes('密钥被拒'), u.warn);
      assert.ok(u.cta <= 1 && u.overflow <= 1, JSON.stringify(u));
      await page.screenshot({ path: path.join(shell.QA_DIR, `S1016-settings-usage-${theme}.png`), fullPage: true });

      // ④ 技能：说明行 + 刷新 / ＋ · 列表 · 隐藏列表输入框
      await clickTab(page, '技能');
      await page.waitForFunction(() => document.querySelectorAll('.lb-skill-row').length === 2);
      p = await readPane(page);
      assert.equal(p.tab, 'skills');
      const sk = await page.evaluate(() => ({ lead: [...document.querySelectorAll('.lb-skill-lead .extra-setting-button')].map(b => b.getAttribute('aria-label')),
        rows: [...document.querySelectorAll('.lb-skill-row')].map(r => r.querySelector('.setting-item-name').textContent + '｜' + r.querySelector('.setting-item-description').textContent),
        hiddenInput: !!document.querySelector('.lb-skill-hidden-input') }));
      assert.deepEqual(sk.lead, ['刷新', '从本地文件夹导入（只拷文字文件，不执行）']);
      assert.deepEqual(sk.rows, ['recipe｜菜谱：列菜名、主料、难度；展开给用量和步骤', 'travel｜旅游攻略：路线、时段、预算、坑']);
      assert.ok(sk.hiddenInput, '隐藏列表输入框');
      assert.equal(p.cta, 0);
      await page.screenshot({ path: path.join(shell.QA_DIR, `S1015-settings-skills-${theme}.png`), fullPage: true });
      // 空状态
      await page.evaluate(() => { window.l4skills.length = 0; document.querySelector('.lb-skill-lead .extra-setting-button').click(); });
      await page.waitForFunction(() => document.querySelector('.lb-skill-empty'));
      assert.match(await page.locator('.lb-skill-empty').textContent(), /还没有技能。点右上角 ＋ 从本地文件夹导入/);
      if (theme === 'light') await page.screenshot({ path: path.join(shell.QA_DIR, `S1015-settings-skills-empty-${theme}.png`), fullPage: true });
      assert.deepEqual(errors, []);
      await page.close();
    }
    // ⑧ 读不到的块：一句人话 + 重试，原始报错折在「详情」里
    {
      const { page, errors } = await open(browser, 'light', { failRemote: true });
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
  fs.writeFileSync(path.join(shell.QA_DIR, 'S1015-settings-rows.json'), JSON.stringify(summary, null, 2));
  console.log('PASS 1015 settings (claudian layout, real Chromium, light / dark / third-party): underline tabs 通用 · 模型与提供商 · 技能, rounded bordered cards with bold title + separator, ≤1 primary per tab, sync count + comment pace in 定时同步, provider sub-tabs with model checklist (box on the left), skills list + refresh / ＋ + empty state + hidden input, no jargon / raw errors on newbie pages, failed save reverts the toggle, unreadable block → retry + folded details. Screenshots: ' + shell.QA_DIR);
})().catch(error => { console.error(error); process.exitCode = 1; });

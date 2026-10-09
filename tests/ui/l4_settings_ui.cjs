'use strict';
// 1009 设置页（一页：状态 · 功能 · 连接 AI · 高级）在真 Chromium + Obsidian 外壳里：功能开关、AI 原地填、一键装好 / 跑完、
// 连接 AI 五个客户端、高级折叠；亮 / 暗 / 第三方主题各截一张（qa/）。runPy 是替身（不起真进程）。
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
process.env.LWA_QA_DIR = path.resolve('qa');
const shell = require('../_obsidian_shell.cjs');
const root = 'obsidian-plugins/link-brain-actions';
const sources = Object.fromEntries(['main', 'home-ui', 'remote-ui', 'schedule-ui', 'onboarding-ui'].map(name =>
  [name + '.js', fs.readFileSync(path.join(root, name + '.js'), 'utf8')]));

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  try {
    for (const theme of ['light', 'dark', 'orange']) {
      const page = await browser.newPage({ viewport: { width: 1300, height: 1400 } });
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      await shell.settings(page, { theme, contentWidth: 800 });
      await page.evaluate(sources => {
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
        const reply = args => {
          const sub = args.slice(2).join(' ');
          if (sub.startsWith('setup plan')) return PLAN;
          if (sub.startsWith('setup estimate')) return { ok: true, items: [{ id: 'summary', name: '概要 + 打标', provider: 'DeepSeek', model: 'deepseek-v4-flash', yuan: 0.8, endpoint: 'https://api.deepseek.com/chat/completions' }], prices: { as_of: '2026-10-03' } };
          if (sub.startsWith('comments --fill-status')) return { ok: true, pending: 190, missing: 5800, stuck: 0, running: true };
          if (sub.startsWith('connect status')) return { ok: true, clients: { 'claude-code': { installed: true, connected: false, command: 'claude mcp add lwa -s user -- python -m link_brain mcp' }, 'claude-desktop': { installed: false, connected: false } }, json: '{}' };
          if (sub.startsWith('remote status')) return { ok: true, state: 'running', message: '运行中（127.0.0.1:18071）', auth: { passphrase_set: true, passphrase_copyable: true, clients: [{ id: 'c1', name: 'claude.ai', connected_at: '2026-10-09T21:30:00' }] }, recent: [] };
          if (sub.startsWith('selftest')) return { ok: true, detail: '合成测试正常' };
          return { ok: true };
        };
        const Plugin = require('main.js');
        const files = { '_archive/comments-fill-status.json': JSON.stringify({ state: 'running', message: '正在补评论 · 已补齐 7/197 篇 · 还缺 5800 条回复', updated_at: new Date().toISOString() }),
          '_archive/problems-summary.json': JSON.stringify({ needs_human: 0, auto: 1, gave_up: 0, sync: { state: 'ready', last_success: new Date().toISOString(), new: 40, deferred: 600 } }) };
        const app = { workspace: { trigger() {}, getActiveFile: () => null },
          vault: { adapter: { getBasePath: () => '/synthetic-vault', exists: async f => f in files, read: async f => { if (!(f in files)) throw new Error('ENOENT'); return files[f]; } }, getAllLoadedFiles: () => [] },
          metadataCache: { getFileCache: () => ({}) } };
        const plugin = new Plugin(app, { id: 'link-brain-actions', dir: '' });
        plugin.settings = Plugin.merge({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'sample-text' },
          setup: { selected: ['core', 'reader', 'dataview', 'ocr', 'ai_text'], aiSynced: true }, connect: { clients: ['claude-code', 'claude-ai', 'chatgpt'] } });
        plugin.settings.remote = { enabled: true, domain: 'https://lwa.example.com', port: 18071, folders: ['@xhs', 'D:/笔记/读书'] };
        plugin.lbPath = x => x; plugin.manifest = { id: 'link-brain-actions', dir: '' };
        plugin.loadData = async () => JSON.parse(JSON.stringify(plugin.settings));
        plugin.saveSettings = async () => {};
        plugin.renderSetupHints = () => {};
        plugin.capsWriterDir = () => null;
        plugin.renderAccounts = c => { const s = new window.obsidian.Setting(c).setName('小红书 · momo · ✓ 已登录'); s.settingEl.classList.add('lb-acct-row'); };
        plugin.runPy = async args => ({ code: 0, json: reply(args) });
        plugin.taskStatusEl = document.querySelector('.status-bar').createDiv({ cls: 'status-bar-item l4-task' });
        plugin.onboardingUI = () => require('onboarding-ui.js')(window.obsidian, plugin);
        plugin.remoteUI = require('remote-ui.js')(window.obsidian, plugin);
        const tab = new Plugin.Tab(app, plugin);
        tab.containerEl = document.querySelector('.vertical-tab-content');
        window.l4 = { plugin, tab, Plugin };
        tab.display();
      }, sources);
      await page.waitForFunction(() => document.querySelectorAll('.lb-feat').length >= 8 && document.querySelector('.lb-connect-chip'));
      await page.waitForFunction(() => /已补齐 7\/197/.test(document.querySelector('.lb-fill-row')?.textContent || ''));
      // 功能：AI 问答打开了 → 原地出接口那几格；点「测试文本 AI」结果就地显示
      await page.getByRole('button', { name: '测试文本 AI', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('.lb-test-result')?.textContent.includes('正常'));
      const geometry = await page.evaluate(() => {
        const input = document.querySelector('.lb-feat-cap input');
        return { input: input.getBoundingClientRect().width, run: !!document.querySelector('.lb-run-go'), chips: document.querySelectorAll('.lb-connect-chip').length,
          sections: [...document.querySelectorAll('[data-section]')].map(s => s.getAttribute('data-section')), advOpen: document.querySelector('.lb-adv').open };
      });
      assert.ok(geometry.input >= 150, JSON.stringify(geometry));
      assert.deepEqual(geometry.sections, ['status', 'features', 'connect', 'advanced']);
      assert.equal(geometry.run, true); assert.equal(geometry.chips, 5); assert.equal(geometry.advOpen, false);
      await page.screenshot({ path: path.join(shell.QA_DIR, `S1009-settings-${theme}.png`), fullPage: true });
      // 高级：一个折叠，点开才画
      await page.locator('.lb-adv > summary').click();
      await page.waitForFunction(() => document.querySelector('.lb-adv-body') && /每天最多新抓/.test(document.querySelector('.lb-adv-body').textContent));
      await page.screenshot({ path: path.join(shell.QA_DIR, `S1009-settings-adv-${theme}.png`), fullPage: true });
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  console.log('PASS 1009 settings real Chromium: one page 状态 · 功能 · 连接 AI · 高级, AI inline + live test result, run-all button, 5 connect chips, advanced folds; light/dark/third-party screenshots');
})().catch(error => { console.error(error); process.exitCode = 1; });

'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
process.env.LWA_QA_DIR = path.resolve('qa');
const shell = require('../_obsidian_shell.cjs');
const root = 'obsidian-plugins/link-brain-actions';
const sources = Object.fromEntries(['main', 'setup-ui', 'schedule-ui', 'onboarding-ui'].map(name =>
  [name + '.js', fs.readFileSync(path.join(root, name + '.js'), 'utf8')]));

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  try {
    for (const theme of ['light', 'dark', 'orange']) {
      const page = await browser.newPage({ viewport: { width: 1300, height: 1000 } });
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
          const file = name.split('/').at(-1);
          if (!modules[file]) {
            const module = { exports: {} }; modules[file] = module;
            new Function('require', 'module', 'process', sources[file] + (file === 'main.js'
              ? '\nmodule.exports.Tab=LinkBrainSettingTab;module.exports.merge=mergeSettings;' : ''))(require, module, { env: {}, platform: 'win32' });
          }
          return modules[file].exports;
        };
        const Plugin = require('main.js');
        const app = { workspace: { trigger() {}, getActiveFile: () => null },
          vault: { adapter: { getBasePath: () => '/synthetic-vault' } }, metadataCache: { getFileCache: () => ({}) } };
        const plugin = new Plugin(app, { id: 'link-brain-actions', dir: '' });
        plugin.settings = Plugin.merge({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'sample-text' },
          setup: { step: 5, selected: ['ai_text'], aiSynced: true } });
        plugin.settingsView = { tab: 'ai' };
        plugin.saveSettings = async () => {};
        plugin.renderSetupHints = () => {};
        plugin.capsWriterDir = () => null;
        plugin.runPy = async () => ({ json: { ok: true, detail: '合成测试正常' } });
        plugin.taskStatusEl = document.querySelector('.status-bar').createDiv({ cls: 'status-bar-item l4-task' });
        plugin.setupUI = () => require('setup-ui.js')(window.obsidian, plugin);
        plugin.onboardingUI = () => require('onboarding-ui.js')(window.obsidian, plugin);
        const tab = new Plugin.Tab(app, plugin);
        tab.containerEl = document.querySelector('.vertical-tab-content');
        window.l4 = { plugin, tab, Plugin };
        tab.display();
      }, sources);
      await page.getByRole('button', { name: '测试文本 AI', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('.lb-test-result')?.textContent.includes('正常'));
      assert.equal(await page.locator('.lb-model-now').count(), 1);
      await page.screenshot({ path: path.join(shell.QA_DIR, `L4-ai-${theme}.png`), fullPage: true });
      await page.evaluate(() => {
        const { tab, plugin } = window.l4;
        tab.containerEl.empty();
        const body = tab.containerEl.createDiv({ cls: 'lb-step-body' });
        tab.sectionTextAI(body, { heading: false });
        plugin.running = '同步收藏'; plugin.runningProgress = '2/5 篇'; plugin.taskChanged();
      });
      const geometry = await page.evaluate(() => {
        const body = document.querySelector('.lb-step-body');
        const input = body.querySelector('input');
        return { body: body.clientWidth, input: input.getBoundingClientRect().width };
      });
      assert.ok(geometry.input >= 300, JSON.stringify(geometry));
      assert.match(await page.locator('.l4-task').textContent(), /同步收藏.*2\/5/);
      await page.screenshot({ path: path.join(shell.QA_DIR, `L4-step5-${theme}.png`), fullPage: true });
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  console.log('PASS L4 settings real Chromium: live AI test result, model summary, step input width, task bar; light/dark/third-party screenshots');
})().catch(error => { console.error(error); process.exitCode = 1; });

'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const { makeDom, makeWorkspace } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');
const dom = makeDom(), notices = [];
const context = { module: { exports: {} }, URL, process, console, setTimeout, clearTimeout,
  setInterval, clearInterval, document: dom.document,
  require: name => name === 'obsidian' ? makeObsidian(dom.document, { notices }) : name === 'child_process'
    ? { spawn() { throw new Error('No real processes in L4 tests'); } } : require(name) };
vm.runInNewContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8'), context);
const Plugin = context.module.exports;
for (const [kind, value, expected] of JSON.parse(fs.readFileSync('tests/fixtures/endpoint_cases.json'))) {
  assert.equal(Plugin.normalizeEndpoint(kind, value), expected);
}
for (const item of JSON.parse(fs.readFileSync('tests/fixtures/with_model_cases.json'))) {
  const settings = { textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions',
    model: 'sample-text', keyFile: 'synthetic-secrets.json', keyField: 'ds' },
    models: [{ name: 'selected', ...item.entry }], activeModel: 'selected' };
  const before = JSON.stringify(settings), chosen = Plugin.effectiveTextAI(settings);
  assert.equal(Plugin.endpointHost(chosen.textAI.endpoint), item.host, item.name);
  assert.equal(chosen.textAI.model, item.model);
  assert.equal(!!chosen.textAI.keyFile, item.keyFile);
  assert.equal(!!chosen.modelFallback, !!item.fallback);
  assert.equal(JSON.stringify(settings), before);
}
const plugin = new Plugin({ workspace: makeWorkspace() }, {});
plugin.taskStatusEl = dom.document.createElement('div');
plugin.running = '同步收藏'; plugin.runningProgress = '2/5 篇';
let called = 0; const off = plugin.onTask(() => called++);
plugin.taskChanged(); assert.equal(plugin.taskStatusEl.hidden, false);
assert.match(plugin.taskStatusEl.textContent, /2\/5/);
plugin.running = null; plugin.externalSync = { state: 'running', updated_at: new Date().toISOString(), done: 3, total: 7 };
plugin.runningProgress = ''; plugin.taskChanged(); assert.match(plugin.taskStatusEl.textContent, /夜跑同步.*3\/7/);
plugin.externalSync.updated_at = '2000-01-01'; plugin.taskChanged(); assert.equal(plugin.taskStatusEl.hidden, true);
off(); plugin.taskChanged(); assert.equal(called, 3);
assert.equal(plugin.commandTable().length, 5);
assert.match(Plugin.resultMessage('同步', { code: 3 }).message, /只做了一部分/);
assert.equal(Plugin.resultMessage('同步', { code: 0, json: { message: '已保存' } }).message, '已保存');
console.log('PASS L4 shared model/endpoint contracts; state bar, subscription cleanup, commands and human messages');

// settings-pages.js（1027 以后只剩服务商那几块积木）+ 首次设置什么时候出（settings-v6.js needsGuide）的纯逻辑。
// 1027 删掉的：1016 四页签（概览 / 同步 / 更多 / 四步指引 / 「需要你留意」attentionText）——六组设置页里各有唯一的一处。
'use strict';
const assert = require('assert/strict');
const path = require('path');

class Setting { constructor() {} }
const OBS = { Setting };
const plugin = { settings: {}, app: { vault: { adapter: { exists: async () => true } } }, lbPath: p => p };
plugin.settingsPages = () => P;
const P = require(path.resolve('obsidian-plugins/link-brain-actions/settings-pages.js'))(OBS, plugin);
const V = require(path.resolve('obsidian-plugins/link-brain-actions/settings-v6.js'))(OBS, plugin);

(async () => {
  // —— 1023（ARCH-AUDIT 第 2 批）：哪家管哪些功能由后端 ai_routes 给（每一格带 provider），JS 不再自己按接口地址猜 ——
  assert.equal(P.providerOf, undefined, 'providerOf 删了：读后端给的 provider');
  for (const gone of ['renderOverview', 'renderSync', 'renderConnect', 'renderMore', 'renderGuide', 'needsGuide', 'attentionText', 'renderAI']) assert.equal(P[gone], undefined, gone + ' 删了（死代码）');
  assert.ok(/^https:\/\//.test(P.LINKS.deepseek.recharge) && /^https:\/\//.test(P.LINKS.google.key), '拿 key / 充值兜底网址');
  // —— 「主用 → 备用」一句：在干活的那一格标出来，没开如实说 ——
  const data = { features: [
    { id: 'vision', name: '识图', on: true, state: 'backup', state_text: '主用的暂时不行，通义千问 qwen3.8-flash 顶着', chain: [{ label: 'Gemini' }, { label: '通义千问 qwen3.8-flash', model: 'qwen3.8-flash' }] },
    { id: 'ask', name: '问收藏', on: false, state: 'off', chain: [{ label: 'DeepSeek' }] },
    { id: 'embed', name: '按意思搜', on: true, state: 'ok', chain: [] }] };
  assert.equal(P.routeText(data, 'vision'), 'Gemini → 【通义千问 qwen3.8-flash】 · 主用的暂时不行，通义千问 qwen3.8-flash 顶着');
  assert.equal(P.routeText(data, 'ask'), '（关着）DeepSeek');
  assert.equal(P.routeText(data, 'embed'), '还没配');
  assert.equal(P.routeText(data, 'nope'), '');

  // —— 首次设置：库里没收藏才自动出；走完（guideDone）不再出；「重新走一遍」（force）一定出 ——
  plugin.settings = { onboarding: { done: true } };
  plugin.app.vault.adapter.exists = async () => false;
  assert.equal(await V.needsGuide(), true, '新库：启动时自动跑过轻量版（done）也照样出');
  plugin.app.vault.adapter.exists = async () => true;
  assert.equal(await V.needsGuide(), false, '已经有收藏：不出');
  plugin.settings = { onboarding: { guideDone: true } };
  plugin.app.vault.adapter.exists = async () => false;
  assert.equal(await V.needsGuide(), false, '走完了：不再出');
  plugin.settings = { onboarding: { guideDone: true, force: true } };
  assert.equal(await V.needsGuide(), true, '重走一遍');
  // —— key 出问题的那一句：点名哪家、影响哪项；接口地址认哪家和后端 pricing.provider_of 同一规则 ——
  const kt = V.keyTrouble({ keys: { aliyun: { code: 'NEEDS_HUMAN.AUTH_FAILED', caps: ['visionAI.refine', 'summaryAI'] }, deepseek: { code: 'NEEDS_HUMAN.QUOTA_EXCEEDED', caps: [] } } });
  assert.deepEqual(kt.map(k => k.text), ['通义千问 key 用不了（精细识图、概要）', 'DeepSeek 额度用完或余额不足']);
  // 哪几格在用这家：只认后端 keys detect 给的 slots（前端不按接口地址猜，test_guards「供应商猜测」守着）；只换撞上问题的那几项
  assert.equal(V.providerOf, undefined);
  plugin.settings = { textAI: { endpoint: 'x' }, summaryAI: { mode: 'inherit', fallback: { endpoint: 'y' } }, visionAI: { refine: { endpoint: 'z' } } };
  const got = V.slotsFor(['textAI', 'summaryAI.fallback', 'visionAI.refine'], ['summaryAI']);
  assert.deepEqual(got.map(x => x.endpoint), ['x', 'y'], '概要跟随问答撞上了：问答那一格 + 概要的备用；识图那格不动');
  assert.deepEqual(V.slotsFor(['visionAI.refine'], []).map(x => x.endpoint), ['z'], '没说哪几项：这家的全换');
  console.log('ok test_settings_pages_1016 (1027: settings-pages keeps LINKS / routeText / keyring; dead pages gone; needsGuide; keyTrouble; slotsFor from backend)');
})().catch(e => { console.error(e); process.exit(1); });

// 1016 设置页四个页签（settings-pages.js）的纯逻辑：AI 页按「哪家管哪些功能」排、「需要你留意」的措辞、四步指引什么时候出。
'use strict';
const assert = require('assert/strict');
const path = require('path');

class Setting { constructor() {} }
const OBS = { Setting };
const plugin = { settings: {}, app: { vault: { adapter: { exists: async () => true } } }, lbPath: p => p };
const P = require(path.resolve('obsidian-plugins/link-brain-actions/settings-pages.js'))(OBS, plugin);

(async () => {
  // —— AI 页：她 1016 的配置（问收藏 DeepSeek；概要 / 识图 Gemini 轮 key，备用百炼；向量百炼）——
  const BL = 'https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions';
  const G = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions';
  const hers = {
    textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-v4-flash' },
    summaryAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', fallback: { endpoint: BL, model: 'qwen3.7-flash' } },
    visionAI: { mode: 'http', endpoint: G, model: 'gemini-3.5-flash', keyPool: 'gemini', refine: { endpoint: BL, model: 'qwen3.8-max' } },
    embedAI: { mode: 'http', endpoint: BL.replace('/chat/completions', '/embeddings'), model: 'qwen3.7-text-embedding-flash' },
    asrAI: { mode: 'capswriter' },
    models: [{ name: 'Codex', mode: 'cli' }],
  };
  const rows = P.providerRows(hers);
  assert.deepEqual(rows.map(r => r.id), ['google', 'deepseek', 'aliyun'], 'Gemini 在前（主力），本机的不出现');
  const g = rows.find(r => r.id === 'google'), a = rows.find(r => r.id === 'aliyun'), d = rows.find(r => r.id === 'deepseek');
  assert.deepEqual(g.main, ['概要', '识图']); assert.equal(g.pool, 'gemini', '几把 key 轮流用');
  assert.deepEqual(d.main, ['问收藏']);
  assert.deepEqual(a.main, ['语义搜索']); assert.deepEqual(a.backup, ['概要', '精细识图'], '备用另列');
  // 概要继承问收藏（默认）：算在问收藏那一家
  const inh = P.providerRows({ textAI: { mode: 'http', endpoint: 'https://api.deepseek.com/chat/completions' }, summaryAI: { mode: 'inherit' } });
  assert.deepEqual(inh.map(r => [r.id, r.main]), [['deepseek', ['问收藏', '概要']]]);
  // 全关 / 全命令行：没有 API 行
  assert.deepEqual(P.providerRows({ textAI: { mode: 'cli' }, summaryAI: { mode: 'off' }, visionAI: { mode: 'off' } }), []);
  assert.equal(P.providerOf('', 'qwen3.7-flash'), 'aliyun');

  // —— 需要你留意：不吓人、不 bossy；说发生了什么、有没有影响 ——
  const t = P.attentionText({ code: 'NEEDS_HUMAN.AUTH_FAILED', step: 'ai.vision',
    reason: '识图接口（通义千问 qwen3.8-flash，密钥文件 千问.csv）；接口拒绝了 key（HTTP 403）' });
  assert.equal(t.title, '阿里云百炼的 key 用不了');
  assert.match(t.desc, /可能欠费、过期或没开通服务；影响识图/);
  assert.equal(t.provider, 'aliyun');
  for (const w of ['异常', '风控', '要你处理', '必须']) assert.ok(!(t.title + t.desc).includes(w), '措辞里不该有「' + w + '」');
  // 1018：原因里「已换用 通义千问 …」是顶上的备用，坏的是前面那家（Gemini）——别冤枉百炼
  const gm = P.attentionText({ code: 'NEEDS_HUMAN.AUTH_FAILED', step: 'ai.vision',
    reason: '识图接口（Google gemini-3.5-flash，没有 key）；gemini 的 key 今天都用不了了；已换用 通义千问 qwen3.8-max（补上 7 次）；原因：…' });
  assert.equal(gm.title, 'Gemini的 key 用不了');
  assert.equal(gm.provider, 'google');
  assert.match(gm.desc, /识图没停：已自动改用 通义千问 qwen3\.8-max 顶上/);
  const r = P.attentionText({ code: 'PERMANENT.NOTE_RESTRICTED', item_id: 'xhs-1', title: '一篇笔记' });
  assert.match(r.title, /要在网页上验证一下才能看/); assert.equal(r.restricted, 'xhs-1');

  // —— 四步指引：库里没收藏才自动出；走完（guideDone）不再出；「重走一遍」（force）一定出 ——
  plugin.settings = { onboarding: { done: true } };
  plugin.app.vault.adapter.exists = async () => false;
  assert.equal(await P.needsGuide(), true, '新库：启动时自动跑过轻量版（done）也照样出指引');
  plugin.app.vault.adapter.exists = async () => true;
  assert.equal(await P.needsGuide(), false, '已经有收藏：不出');
  plugin.settings = { onboarding: { guideDone: true } };
  plugin.app.vault.adapter.exists = async () => false;
  assert.equal(await P.needsGuide(), false, '走完了：不再出');
  plugin.settings = { onboarding: { guideDone: true, force: true } };
  assert.equal(await P.needsGuide(), true, '重走一遍');
  console.log('ok test_settings_pages_1016');
})().catch(e => { console.error(e); process.exit(1); });

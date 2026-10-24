// 1016 设置页四个页签（settings-pages.js）的纯逻辑：AI 页按「哪家管哪些功能」排、「需要你留意」的措辞、四步指引什么时候出。
'use strict';
const assert = require('assert/strict');
const path = require('path');

class Setting { constructor() {} }
const OBS = { Setting };
const plugin = { settings: {}, app: { vault: { adapter: { exists: async () => true } } }, lbPath: p => p };
const P = require(path.resolve('obsidian-plugins/link-brain-actions/settings-pages.js'))(OBS, plugin);

(async () => {
  // —— 1023（ARCH-AUDIT 第 2 批）：哪家管哪些功能由后端 ai_routes 给（每一格带 provider），JS 不再自己按接口地址猜 ——
  assert.equal(P.providerOf, undefined, 'providerOf 删了：读后端给的 provider');
  assert.equal(P.providerRows, undefined);

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

const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const notices = [];
const confirms = [];
// node 测试不许起真进程（CONVENTIONS §7.5）：child_process 换成一碰就炸的桩，所有调用都必须被 spawnPy 的替身接住
const noSpawn = {spawn(){ throw new Error('测试里不许 spawn 真进程'); }};
const context = {module:{exports:{}}, process, setTimeout, clearTimeout,
  window: {confirm: msg => { confirms.push(msg); return false; }},
  require:n => n === 'obsidian' ? {Plugin:class{}, PluginSettingTab:class{}, Modal:class{open(){}}, Notice:class{constructor(m){notices.push(m);}}}
    : n === 'child_process' ? noSpawn : require(n)};
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js','utf8'), context);
const ok = out => ({code:0, json:(()=>{try{return JSON.parse(out);}catch{return null;}})(), out, err:'', all:out, timedOut:false});
(async () => {
  const p = new context.module.exports();
  p.app = {vault:{adapter:{getBasePath:()=> 'D:/host-vault', read:async()=>JSON.stringify(p._sync)}, configDir:'.obsidian-test'}};
  p.lbPath = x => x;
  p.settings = {loginNoticeSeen: true};
  let calls = [];

  // 环境检查：一次 doctor --only local，并发刷新合并成一次
  p.spawnPy = async args => { calls.push(args); return ok(JSON.stringify({checks:[]})); };
  await Promise.all([p.checkRuntime(), p.checkRuntime()]);
  assert.equal(calls.length, 1, 'duplicate refresh shares one check');
  assert.ok(calls[0].includes('--only') && calls[0].includes('local'));
  assert.ok(calls[0].at(-1).endsWith('.obsidian-test'));

  // 登录：一个号，不再区分 favorites / attachments；--force 透传
  calls = [];
  p.spawnPy = async args => { calls.push(args); return ok('{"state":"ready","message":"已登录：alice"}'); };
  assert.equal((await p.loginAccount()).state, 'ready');
  assert.equal(JSON.stringify(calls[0]), JSON.stringify(['-m','link_brain','login','--json']));
  await p.loginAccount(true);
  assert.ok(calls[1].includes('--force'));
  assert.equal(p.running, null);

  // 扫码进行中：状态查询不再起 Python（不去碰浏览器），登录互斥（问一句要不要停；不停就报「还在跑」）
  p.running = '账号登录';
  assert.equal((await p.accountStatus()).state, 'busy');
  await assert.rejects(p.loginAccount(), /还在跑/);
  assert.equal(confirms.length, 1, '换号前先问一句');
  p.running = null;

  // Python 不在：给出安装指引，而不是一串堆栈
  p.spawnPy = async () => ({code:-1, json:null, out:'', err:'spawn python ENOENT', all:'', timedOut:false});
  await assert.rejects(p.checkRuntime(), /README/);
  await assert.rejects(p.loginAccount(), /Python/);
  assert.equal(p.running, null);

  // 状态检查超过 3 分钟：报错并给出下一步，不无限转圈
  let seenTimeout = 0;
  p.spawnPy = async (args, opts) => { seenTimeout = opts?.timeoutMs; return {code:-2, json:null, out:'', err:'', all:'', timedOut:true}; };
  await assert.rejects(p.accountStatus(), /超过 3 分钟/);
  assert.equal(seenTimeout, 180000);

  // 退出码非 0 且没有 JSON：抛 stderr 尾三行（不再把空串当成功）
  p.spawnPy = async () => ({code:1, json:null, out:'', err:'a\nb\nc\nd 最后一句原因', all:'', timedOut:false});
  await assert.rejects(p.accountStatus(), e => e.message === 'b\nc\nd 最后一句原因');

  // 目录页「!」：按失败原因直达修复
  const routes = [];
  p.loginAccount = async () => { routes.push('login'); return {state:'ready', message:'已登录：alice'}; };
  p.openVerify = async () => { routes.push('verify'); return {}; };
  p.openAccountStatus = () => routes.push('panel');
  p.syncNow = () => routes.push('sync');
  p._sync = {state:'blocked', account:'xhs', code:'NOT_LOGGED_IN'}; await p.fixFromCatalog();
  p._sync = {state:'blocked', account:'xhs', code:'CAPTCHA_REQUIRED'}; await p.fixFromCatalog();
  p._sync = {state:'blocked', account:null, code:'DISCONNECTED'}; await p.fixFromCatalog();
  assert.equal(JSON.stringify(routes), JSON.stringify(['login', 'sync', 'verify', 'panel']), '登录成功直接开始同步');
  console.log('PASS account UI: single env check, one-account login/force, busy guard asks first, python missing, 3-min timeout, stderr tail, catalog ! routes to login/verify/panel');
})().catch(e => {console.error(e);process.exitCode=1;});

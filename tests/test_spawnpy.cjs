// 第 0 批：插件唯一 Python 入口 spawnPy / runPy、唯一杀树 killTree（CONVENTIONS §1、§6），以及迁到 runPy 的各调用点。
// 全部用假 child_process：不起真 Python、不起 PowerShell。
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict'), { EventEmitter } = require('events');

const spawned = [];
let script = () => ({ code: 0 });   // 每次 spawn 怎么表现：{stdout, stderr, code, error, hang}
function fakeSpawn(exe, args, opts) {
  const c = new EventEmitter();
  c.pid = 1000 + spawned.length;
  c.stdout = new EventEmitter(); c.stderr = new EventEmitter();
  c.stdout.setEncoding = () => {};
  c.stdin = new EventEmitter(); c.stdin.write = s => { c.input = (c.input || '') + s; }; c.stdin.end = () => {};
  c.kill = () => { c.killed = true; setTimeout(() => c.emit('close', null), 0); };
  spawned.push({ exe, args, opts, child: c });
  const plan = script(exe, args, c);
  setTimeout(() => {
    if (plan.error) { c.emit('error', new Error(plan.error)); return; }
    if (plan.stdout) c.stdout.emit('data', Buffer.from(plan.stdout));
    if (plan.stderr) c.stderr.emit('data', Buffer.from(plan.stderr));
    if (!plan.hang) c.emit('close', plan.code ?? 0);
  }, 0);
  return c;
}
const notices = [];
const context = { module: { exports: {} }, process, setTimeout, clearTimeout, Buffer,
  window: { confirm: () => true },
  require: n => n === 'obsidian' ? { Plugin: class {}, PluginSettingTab: class {}, Modal: class {}, Notice: class { constructor(m) { notices.push(m); } } }
    : n === 'child_process' ? { spawn: fakeSpawn } : require(n) };
vm.createContext(context);
vm.runInContext(fs.readFileSync('obsidian-plugins/link-brain-actions/main.js', 'utf8') + ';module.exports.selectKillPids=selectKillPids;', context);
const Plugin = context.module.exports;

(async () => {
  const p = new Plugin(); p.repoRoot = 'D:/repo';
  p.app = { vault: { adapter: { exists: async () => false, read: async () => '', write: async () => {} } }, workspace: { trigger() {} } };
  p.lbPath = x => x;

  // spawnPy：统一 cwd / env / windowsHide；最后一行 JSON；stdout 里的人话不影响解析
  script = () => ({ stdout: '进度一行\n{"ok":true,"n":3}\n', stderr: 'warn\n', code: 0 });
  let r = await p.spawnPy(['-m', 'link_brain', 'x']);
  assert.equal(spawned[0].exe, 'python');
  assert.equal(spawned[0].opts.cwd, 'D:/repo'); assert.equal(spawned[0].opts.windowsHide, true);
  assert.equal(spawned[0].opts.env.PYTHONIOENCODING, 'utf-8');
  assert.deepEqual({ ...r.json }, { ok: true, n: 3 }); assert.equal(r.code, 0); assert.equal(r.err, 'warn\n');
  assert.ok(r.all.includes('进度一行') && r.all.includes('warn'));

  // runPy：退出码≠0 且没 JSON → 抛 stderr 尾三行
  script = () => ({ stdout: '', stderr: 'l1\nl2\nl3\nl4\n', code: 1 });
  await assert.rejects(p.runPy(['x']), e => e.message === 'l2\nl3\nl4' && e.result.code === 1);
  // 退出码≠0 但有 JSON → 不抛，交给调用方判
  script = () => ({ stdout: '{"ok":false,"results":[]}', code: 1 });
  r = await p.runPy(['x']); assert.equal(r.code, 1); assert.equal(r.json.ok, false);
  // 空 stdout、退出码 0 → json=null（不再把空串当 {}）
  script = () => ({ stdout: '', code: 0 });
  r = await p.runPy(['x']); assert.equal(r.json, null);
  // okCodes
  script = () => ({ stdout: 'plain', stderr: '转换失败', code: 2 });
  r = await p.runPy(['x'], { okCodes: [0, 2] }); assert.equal(r.code, 2);
  // 起不来
  script = () => ({ error: 'spawn python ENOENT' });
  await assert.rejects(p.runPy(['x']), /找不到 Python/);

  // 超时 → killTree(child.pid)，code=-2、timedOut，runPy 抛 timeoutMessage
  const killed = [];
  p.killTree = async pid => { killed.push(pid); const s = spawned.find(x => x.child.pid === pid); s.child.emit('close', 1); return [pid]; };
  script = () => ({ hang: true });
  const before = spawned.length;
  await assert.rejects(p.runPy(['slow'], { timeoutMs: 20, timeoutMessage: '太慢了' }), e => e.message === '太慢了' && e.timedOut);
  assert.deepEqual(killed, [spawned[before].child.pid]);
  delete p.killTree;

  // exclusive：占 this.running，互斥；结束后释放
  script = () => ({ stdout: '{"ok":true}', code: 0, hang: true });
  const first = p.spawnPy(['long'], { exclusive: true, label: '同步收藏' });
  assert.equal(p.running, '同步收藏'); assert.ok(p.runningChild);
  const second = await p.spawnPy(['other'], { exclusive: true, label: '别的' });
  assert.equal(second.busy, true);
  p.runningChild.emit('close', 0); await first;
  assert.equal(p.running, null); assert.equal(p.runningChild, null);

  // run()：界面壳仍返回 {code, out, stdout} 并写日志
  const logs = []; p.log = async t => logs.push(t);
  script = () => ({ stdout: '{"items":[]}\n', stderr: '完成了\n', code: 0 });
  r = await p.run(['-m', 'link_brain', 'catalog'], '重建目录');
  assert.equal(r.code, 0); assert.equal(r.stdout, '{"items":[]}\n'); assert.ok(r.out.includes('完成了'));
  assert.ok(logs[0].startsWith('[重建目录] exit=0'));

  // killTree：PowerShell 枚举 → 同一套选择规则 → Stop-Process 只点名要杀的（读取服务和它的浏览器不在里面）
  const ps = [];
  p.psRun = async s => {
    ps.push(s);
    if (s.startsWith('Get-CimInstance')) return JSON.stringify([
      { pid: 10, ppid: 1, name: 'python.exe', created: 10 }, { pid: 11, ppid: 10, name: 'claude.exe', created: 11 },
      { pid: 20, ppid: 10, name: 'link-brain-reader.exe', created: 20 }, { pid: 21, ppid: 20, name: 'chrome.exe', created: 21 },
      { pid: 22, ppid: 21, name: 'msedge.exe', created: 22 }]);
    return '';
  };
  const realPlatform = process.platform;
  Object.defineProperty(process, 'platform', { value: 'win32' });
  try {
    const out = await p.killTree(10);
    assert.deepEqual([...out], [11, 10]);
    assert.equal(ps[1], 'Stop-Process -Id 11,10 -Force -ErrorAction SilentlyContinue');
    assert.ok(!ps[1].includes('20') && !ps[1].includes('21'));
    // 根就是读取服务：什么都不杀
    ps.length = 0; assert.deepEqual([...await p.killTree(20)], []); assert.equal(ps.length, 1);
    // 枚举失败：只结束根本身
    p.psRun = async s => { ps.push(s); return s.startsWith('Get-CimInstance') ? 'not json' : ''; };
    ps.length = 0;
    const origKill = process.kill; const direct = []; process.kill = pid => direct.push(pid);
    try { assert.deepEqual([...await p.killTree(10)], [10]); } finally { process.kill = origKill; }
    assert.equal(ps[1], 'Stop-Process -Id 10 -Force -ErrorAction SilentlyContinue'); assert.deepEqual(direct, [10]);
  } finally { Object.defineProperty(process, 'platform', { value: realPlatform }); }

  // ── 迁到 runPy 的调用点 ──
  const answer = (stdout, code = 0, stderr = '') => { script = () => ({ stdout, stderr, code }); };
  // 同步计划：读不到 → 抛（以前悄悄当成 {}，页面显示「每天 04:00」）
  answer('', 1, 'schtasks 拒绝访问');
  await assert.rejects(p.getSyncSchedule(), /拒绝访问/);
  answer('{"task":"XhsFavSync","freq":"daily","time":"04:00"}');
  assert.equal((await p.getSyncSchedule()).freq, 'daily');
  answer('{"ok":false,"error":"未知周期"}', 1);
  assert.equal((await p.setSyncSchedule('x')).ok, false);
  answer('', 0);
  assert.equal((await p.setSyncSchedule('daily', '04:00')).ok, false);
  // 删除：空输出不再当成功
  answer('', 0);
  await assert.rejects(p.deleteItems(['a']), /没返回可解析结果/);
  answer('', 1, 'Traceback...\nPermissionError: 文件被占用');
  await assert.rejects(p.deleteItems(['a']), /文件被占用/);
  answer('{"deleted":1,"results":[{"item_id":"a","status":"deleted"},{"item_id":"b","status":"missing","error":"不在库里"}]}', 1);
  assert.equal((await p.deleteItems(['a', 'b'])).deleted, 1, '部分失败：逐条结果照样交给页面');
  // 清洗链接
  answer('', 1, 'httpx 连接失败');
  await assert.rejects(p.expandAndCleanLinks('x'), /连接失败/);
  // 星标
  answer('', 1, '对象不存在');
  await assert.rejects(p.starNote('a', true), /收藏失败：对象不存在/);
  answer('{"status":"ok","starred":true}');
  assert.equal((await p.starNote('a', true)).starred, true);
  // 挂附件：退出码 2 仍是「已保存 + 警告」
  answer('已复制', 2, '正文转换失败');
  assert.equal((await p.attachFile('a', 'C:/f.pdf')).warning, '正文转换失败');
  answer('', 1, '文件不存在');
  await assert.rejects(p.attachFile('a', 'C:/f.pdf'), /文件不存在/);
  // 回收站
  answer('', 1, '索引库坏了');
  await assert.rejects(p.trashAction('restore', ['a']), /索引库坏了/);
  answer('{"results":[{"item_id":"a","status":"failed","error":"目录被占用"}]}', 1);
  await assert.rejects(p.trashAction('restore', ['a']), /目录被占用/);
  // 导出
  answer('', 1, '磁盘满了');
  await assert.rejects(p.exportArchiveBundle(['a']), /磁盘满了/);
  console.log('PASS spawnPy/runPy/killTree: one entry, last-line JSON, stderr tail, okCodes, timeout→killTree, exclusive, run() shell, reader-safe kill selection, migrated call sites');
})().catch(e => { console.error(e); process.exitCode = 1; });

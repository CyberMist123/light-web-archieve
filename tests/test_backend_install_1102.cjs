// 1102 托管模式：backend-install.js（机器上没有 Python 也能装好后端）。
//   - uvAsset：按 platform / arch 选资产，表里的 sha256 / 版本是常量；
//   - download：写 .part → sha256 对上才改名；校验不过删干净；有残片带 Range 续传；404 / 5xx / 连不上 各归各的码；跟着 302 走；onProgress 有 done / total；
//   - ensureBackend：五步进度事件（uv → python → venv → install → check）、每一步失败返回 {ok:false, code, message} 不抛、
//     发布包没发（BACKEND_RELEASE 哈希为空）如实说；装好写 config.json 的 backend_dir；已装好只自检；
//   - upgrade：装到 py-<版本>/，自检过了才切 backend_dir、上一版留一份、再早的删；rollbackBackend 切回去；
//   - extractUv：Windows 走 PowerShell Expand-Archive（失败退 tar）；其它平台 tar --strip-components=1（Linux 上真解一个假包）。
// 不真下载（本地 http 假服务器）；子进程一律注入 runImpl 记账 + 造文件，不起真 uv / Python（CONVENTIONS §7.5）。
'use strict';
const fs = require('fs'), os = require('os'), path = require('path'), http = require('http'), crypto = require('crypto'), assert = require('assert/strict');
const { spawnSync } = require('child_process');

const B = require(path.resolve('obsidian-plugins/link-brain-actions/backend-install.js'));
const sha = buf => crypto.createHash('sha256').update(buf).digest('hex');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-bi-'));
const P = process.platform;

// —— 本地假服务器：/files/<name> 支持 Range；/redirect → 302；/boom → 500；/nope → 404 ——
const files = {};
const hits = [];
const server = http.createServer((req, res) => {
  hits.push({ url: req.url, range: req.headers.range || null });
  if (req.url === '/redirect') { res.writeHead(302, { Location: '/files/lock' }); return res.end(); }
  if (req.url === '/boom') { res.writeHead(500); return res.end('x'); }
  const m = /^\/files\/(.+)$/.exec(req.url);
  const body = m && files[m[1]];
  if (!body) { res.writeHead(404); return res.end('no'); }
  const r = /^bytes=(\d+)-$/.exec(req.headers.range || '');
  if (r) {
    const from = Number(r[1]);
    if (from >= body.length) { res.writeHead(416); return res.end(); }
    res.writeHead(206, { 'Content-Length': body.length - from, 'Content-Range': `bytes ${from}-${body.length - 1}/${body.length}` });
    return res.end(body.subarray(from));
  }
  res.writeHead(200, { 'Content-Length': body.length });
  res.end(body);
});
const listen = () => new Promise(r => server.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${server.address().port}`)));

(async () => {
  const base = await listen();
  files.lock = Buffer.from('jieba==0.42.1 --hash=sha256:' + '0'.repeat(64) + '\n');
  files['link_brain-0.2.0-py3-none-any.whl'] = crypto.randomBytes(3 * 1024 * 1024 + 123);   // 3 MB：进度事件能看到 done / total
  files.uv = Buffer.from('fake uv archive');

  // —— 1. 资产表 ——
  assert.equal(B.uvAsset('win32', 'x64').name, 'uv-x86_64-pc-windows-msvc.zip');
  assert.equal(B.uvAsset('win32', 'arm64').name, 'uv-aarch64-pc-windows-msvc.zip');
  assert.equal(B.uvAsset('darwin', 'arm64').name, 'uv-aarch64-apple-darwin.tar.gz');
  assert.equal(B.uvAsset('linux', 'x64').name, 'uv-x86_64-unknown-linux-gnu.tar.gz');
  assert.equal(B.uvAsset('freebsd', 'x64'), null);
  for (const a of Object.values(B.UV_RELEASE.assets)) assert.match(a.sha256, /^[0-9a-f]{64}$/, '每个资产都有 sha256');
  assert.ok(B.uvAsset('win32', 'x64').url.startsWith('https://github.com/astral-sh/uv/releases/download/' + B.UV_RELEASE.version + '/'));
  assert.equal(typeof B.BACKEND_RELEASE.wheelUrl, 'string');
  assert.ok(B.BACKEND_RELEASE.wheelUrl.includes(`/releases/download/v${B.BACKEND_RELEASE.version}/link_brain-${B.BACKEND_RELEASE.version}-py3-none-any.whl`) && /requirements\.lock$/.test(B.BACKEND_RELEASE.lockUrl), '按 v<版本> 的命名约定');

  // —— 2. download ——
  const dl = path.join(tmp, 'dl');
  // 2a 正常：.part → 改名；进度 done / total 递增到底
  const events = [];
  let r = await B.download(base + '/files/link_brain-0.2.0-py3-none-any.whl', path.join(dl, 'w.whl'), { sha256: sha(files['link_brain-0.2.0-py3-none-any.whl']), onProgress: e => events.push(e) });
  assert.equal(r.ok, true);
  assert.ok(fs.existsSync(path.join(dl, 'w.whl')) && !fs.existsSync(path.join(dl, 'w.whl.part')), '改名了、.part 没了');
  assert.ok(events.length >= 1 && events.at(-1).done === files['link_brain-0.2.0-py3-none-any.whl'].length && events.at(-1).total === files['link_brain-0.2.0-py3-none-any.whl'].length, '最后一条进度 done=total');
  assert.match(events.at(-1).text, /MB/);
  assert.equal(sha(fs.readFileSync(path.join(dl, 'w.whl'))), sha(files['link_brain-0.2.0-py3-none-any.whl']));
  // 2b 校验不过：.part 和 dest 都删掉，不留半截
  r = await B.download(base + '/files/link_brain-0.2.0-py3-none-any.whl', path.join(dl, 'bad.whl'), { sha256: '0'.repeat(64) });
  assert.equal(r.ok, false); assert.equal(r.code, 'PERMANENT.CHECKSUM_MISMATCH'); assert.match(r.message, /校验和不对.*没有安装/);
  assert.ok(!fs.existsSync(path.join(dl, 'bad.whl')) && !fs.existsSync(path.join(dl, 'bad.whl.part')));
  // 2c 续传：留一截 .part → 带 Range 接着下，内容完整
  fs.writeFileSync(path.join(dl, 'r.whl.part'), files['link_brain-0.2.0-py3-none-any.whl'].subarray(0, 1000));
  hits.length = 0;
  r = await B.download(base + '/files/link_brain-0.2.0-py3-none-any.whl', path.join(dl, 'r.whl'), { sha256: sha(files['link_brain-0.2.0-py3-none-any.whl']) });
  assert.equal(r.ok, true);
  assert.deepEqual(hits.map(h => h.range), ['bytes=1000-'], '带 Range 续传');
  assert.equal(sha(fs.readFileSync(path.join(dl, 'r.whl'))), sha(files['link_brain-0.2.0-py3-none-any.whl']), '拼起来和原文件一样');
  // 2d 残片已经是整个文件（416）：直接校验通过
  fs.writeFileSync(path.join(dl, 'full.whl.part'), files['link_brain-0.2.0-py3-none-any.whl']);
  r = await B.download(base + '/files/link_brain-0.2.0-py3-none-any.whl', path.join(dl, 'full.whl'), { sha256: sha(files['link_brain-0.2.0-py3-none-any.whl']) });
  assert.equal(r.ok, true); assert.ok(fs.existsSync(path.join(dl, 'full.whl')));
  // 2e 404 / 500 / 连不上 / 跟 302
  r = await B.download(base + '/nope', path.join(dl, 'n'), {}); assert.equal(r.code, 'PERMANENT.BAD_PACKAGE'); assert.match(r.message, /发布包不存在.*404/);
  r = await B.download(base + '/boom', path.join(dl, 'b'), {}); assert.equal(r.code, 'TRANSIENT.HTTP_5XX');
  r = await B.download('http://127.0.0.1:1/x', path.join(dl, 'c'), { label: '下载 uv' }); assert.equal(r.code, 'TRANSIENT.NETWORK'); assert.match(r.message, /下载 uv没连上/);
  r = await B.download(base + '/redirect', path.join(dl, 'lock'), { sha256: sha(files.lock) }); assert.equal(r.ok, true, '跟着 302 走');
  for (const x of [r]) assert.ok(!('stack' in x), '返回值不是异常');

  // —— 3. ensureBackend：假 uv（runImpl 记账 + 造文件）——
  const home = path.join(tmp, 'home');
  const release = { version: '0.2.0', wheelUrl: base + '/files/link_brain-0.2.0-py3-none-any.whl', wheelSha256: sha(files['link_brain-0.2.0-py3-none-any.whl']), lockUrl: base + '/files/lock', lockSha256: sha(files.lock) };
  const uvRelease = { version: '0.13.6', asset: { name: 'uv-fake.tar.gz', sha256: sha(files.uv), url: base + '/files/uv' } };
  const calls = [];
  let failAt = null;   // 'python' | 'venv' | 'pip' | 'check'：让某一步失败
  const touch = (f, body = '') => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, body); };
  const runImpl = async (exe, args, opts = {}) => {
    calls.push([path.basename(exe), ...args]);
    const name = path.basename(exe);
    if (name === 'tar' || name === 'powershell.exe') {   // 解到哪就在哪造一个 uv（-C <bin> / -DestinationPath '<bin>'）
      const bin = name === 'tar' ? args[args.indexOf('-C') + 1] : /-DestinationPath '(.*?)' -Force/.exec(args.at(-1))[1].replace(/''/g, "'");
      touch(path.join(bin, P === 'win32' ? 'uv.exe' : 'uv'), '#!/bin/sh\n'); return { code: 0, out: '', err: '' };
    }
    if (/^uv(\.exe)?$/.test(name)) {
      assert.equal(opts.env.UV_PYTHON_INSTALL_DIR, path.join(opts.env.LINK_BRAIN_HOME, 'python'), 'uv 的 Python 收进 ~/.link-brain/python');
      assert.equal(opts.env.UV_PYTHON_INSTALL_BIN, '0');
      if (args[0] === '--version') return { code: 0, out: 'uv 0.13.6\n', err: '' };
      if (args[0] === 'python') { opts.onLine?.('Installed Python 3.12.x'); return failAt === 'python' ? { code: 1, out: '', err: 'error: Failed to download https://github.com/...: connect timed out\n' } : { code: 0, out: '', err: '' }; }
      if (args[0] === 'venv') { if (failAt === 'venv') return { code: 2, out: '', err: 'error: No interpreter found\n' }; touch(B.venvPython(args[1], P)); return { code: 0, out: '', err: '' }; }
      if (args[0] === 'pip') {
        assert.equal(args[1], 'install'); assert.equal(args[2], '--python'); assert.ok(args.includes('--require-hashes'), '必带 --require-hashes');
        const lock = args[args.indexOf('-r') + 1], wheelReq = args[args.lastIndexOf('-r') + 1];
        assert.ok(fs.readFileSync(lock, 'utf8').includes('--hash=sha256:'), 'lock 真下到了本地');
        assert.match(fs.readFileSync(wheelReq, 'utf8'), /^link-brain\[ocr,bilibili,docs\] @ file:\/\/.*\.whl --hash=sha256:[0-9a-f]{64}\n$/, 'wheel 也带哈希（1103：OCR / B 站 / 附件默认一起装）');
        if (failAt === 'pip') return { code: 1, out: '', err: 'error: No solution found when resolving dependencies\n' };
        const dir = path.dirname(path.dirname(args[3]));
        touch(B.venvBackend(dir, P), '#!/bin/sh\n');
        return { code: 0, out: '', err: '' };
      }
    }
    if (/^link-brain(\.exe)?$/.test(name)) return failAt === 'check' ? { code: -1, out: '', err: 'spawn ENOENT' } : { code: 0, out: 'link-brain 0.2.0\n', err: '' };
    if (/^python/.test(name)) return failAt === 'check' ? { code: 1, out: '', err: 'ModuleNotFoundError: link_brain' } : { code: 0, out: 'usage', err: '' };
    throw new Error('意外的子进程 ' + exe + ' ' + args.join(' '));
  };
  const opts = { env: { ...process.env, LINK_BRAIN_HOME: home }, home, release, uvRelease, runImpl, platform: P };
  const located = [];
  const plugin = { locateCollection: async () => located.push(1) };

  // 3a 发布包没发：如实说，不装、不下载
  hits.length = 0;
  let out = await B.ensureBackend(plugin, { ...opts, release: { ...release, wheelSha256: '', lockSha256: '' } });
  assert.equal(out.ok, false); assert.equal(out.code, 'SKIPPED.NOT_CONFIGURED'); assert.match(out.message, /还没发布/);
  assert.equal(hits.length, 0, '没发布就不下载'); assert.equal(calls.length, 0);

  // 3b 全流程：五步、顺序、config.json
  const prog = [];
  out = await B.ensureBackend(plugin, { ...opts, onProgress: e => prog.push(e) });
  assert.equal(out.ok, true, JSON.stringify(out));
  assert.equal(out.code, ''); assert.match(out.message, /后端装好了：link-brain 0\.2\.0/);
  assert.equal(out.dir, path.join(home, 'py'));
  assert.equal(out.exe, B.venvBackend(path.join(home, 'py'), P)); assert.equal(out.python, B.venvPython(path.join(home, 'py'), P));
  const order = [...new Set(prog.map(e => e.stage))];
  assert.deepEqual(order, ['uv', 'python', 'venv', 'install', 'check'], '五步按顺序');
  for (const e of prog) { assert.ok(e.stage && e.label && 'done' in e && 'total' in e && 'text' in e, '事件形状 {stage, label, done, total, text}'); }
  const last = st => prog.filter(e => e.stage === st).at(-1);
  for (const st of order) assert.equal(last(st).state, 'ok', st + ' 最后一条是 ok');
  assert.ok(prog.some(e => e.stage === 'install' && e.total === files['link_brain-0.2.0-py3-none-any.whl'].length), '下载 wheel 的进度带 total');
  assert.ok(prog.some(e => e.stage === 'python' && /^Python \S+ 装好了$/.test(e.text)), 'uv 的输出逐行成为进度文字（1103：认得的行换成人话）');
  assert.ok(fs.existsSync(B.uvExe(home, P)), 'uv 解到 ~/.link-brain/bin');
  assert.ok(!fs.existsSync(path.join(home, 'downloads', 'uv-fake.tar.gz')), 'uv 压缩包用完删掉');
  assert.deepEqual(B.readConfig(home), { backend_dir: path.join(home, 'py') }, 'config.json 记下后端目录');
  assert.equal(located.length, 1, '装好后让插件重找后端');
  const seq = calls.map(c => c.slice(0, 2).join(' '));
  assert.deepEqual(seq.filter(s => /^uv(\.exe)? /.test(s) && !/--version/.test(s)), ['uv python', 'uv venv', 'uv pip'].map(s => (P === 'win32' ? 'uv.exe ' : 'uv ') + s.split(' ')[1]), 'uv 的三步：python install → venv → pip install');
  assert.ok(calls.some(c => c[0] === 'tar' && c.includes('--strip-components=1')) || P === 'win32', 'tar.gz 剥一层目录');
  assert.deepEqual(calls.find(c => c[1] === 'python'), [P === 'win32' ? 'uv.exe' : 'uv', 'python', 'install', '3.12']);
  assert.deepEqual(calls.find(c => c[1] === 'venv').slice(0, 5), [P === 'win32' ? 'uv.exe' : 'uv', 'venv', path.join(home, 'py'), '--python', '3.12']);

  // 3c 已装好、不是升级：只自检，前四步 skipped
  calls.length = 0; prog.length = 0;
  out = await B.ensureBackend(plugin, { ...opts, onProgress: e => prog.push(e) });
  assert.equal(out.ok, true); assert.match(out.message, /已经装好/);
  assert.deepEqual([...new Set(prog.filter(e => e.state === 'skipped').map(e => e.stage))], ['uv', 'python', 'venv', 'install']);
  assert.deepEqual(calls.map(c => c.slice(0, 2).join(' ')), ['version', 'setup'].map(a => (P === 'win32' ? 'link-brain.exe ' : 'link-brain ') + a), '只跑了自检（版本 + 核心检查）');
  // 1104（审查 11）：自检 = version + 不联网的核心检查；版本 JSON 只取版本号；核心检查不过 → 如实说「核心功能跑不起来」
  assert.equal(B.versionText('{"ok": true, "version": "0.2.2", "python": "3.12"}\n'), '0.2.2');
  assert.equal(B.versionText('link-brain 0.2.0\n'), 'link-brain 0.2.0');
  {
    const ck = await B.selfCheck(path.join(home, 'py'), { platform: P, runImpl: async (exe, args) => (args[0] === 'version'
      ? { code: 0, out: '{"ok": true, "version": "0.2.2"}\n', err: '' }
      : { code: 1, out: '{"ok": false, "message": "core 缺依赖：jieba"}\n', err: '' }) });
    assert.equal(ck.ok, false); assert.equal(ck.code, 'PERMANENT.BAD_PACKAGE'); assert.match(ck.message, /核心功能跑不起来：core 缺依赖：jieba/);
    const ok2 = await B.selfCheck(path.join(home, 'py'), { platform: P, runImpl: async (exe, args) => ({ code: 0, out: args[0] === 'version' ? '{"ok": true, "version": "0.2.2"}\n' : '{"ok": true}\n', err: '' }) });
    assert.equal(ok2.version, '0.2.2');
  }
  // 1104（审查 4）：装后端的跨进程锁——别的活进程拿着 → 忙；持有者死了 / 太久 → 当过期重拿；放锁只放自己的
  {
    const lh = path.join(tmp, 'lockhome');
    const a = B.takeInstallLock(lh, { pid: 111, alive: () => true });
    assert.equal(a.ok, true);
    const b = B.takeInstallLock(lh, { pid: 222, alive: () => true });
    assert.equal(b.ok, false); assert.equal(b.holder.pid, 111);
    const c = B.takeInstallLock(lh, { pid: 222, alive: pid => pid !== 111 });
    assert.equal(c.ok, true, '持有者进程没了 = 过期');
    a.release();
    assert.ok(fs.existsSync(path.join(lh, 'locks', 'backend-install.lock')), '别人的锁不放');
    c.release();
    assert.ok(!fs.existsSync(path.join(lh, 'locks', 'backend-install.lock')));
    const d = B.takeInstallLock(lh, { pid: 333, now: 0, alive: () => true }); d && null;
    const e = B.takeInstallLock(lh, { pid: 444, now: 4 * 3600000, alive: () => true });
    assert.equal(e.ok, true, '超过 3 小时 = 过期'); e.release();
    // 另一个窗口正在装 → ensureBackend 不动手、说清楚
    const busyHome = path.join(tmp, 'busyhome');
    fs.mkdirSync(path.join(busyHome, 'locks'), { recursive: true });
    fs.writeFileSync(path.join(busyHome, 'locks', 'backend-install.lock'), JSON.stringify({ pid: process.ppid, started: Date.now() }));
    calls.length = 0;
    const busy = await B.ensureBackend(plugin, { ...opts, home: busyHome, env: { ...process.env, LINK_BRAIN_HOME: busyHome } });
    assert.equal(busy.ok, false); assert.equal(busy.code, 'TRANSIENT.BUSY'); assert.match(busy.message, /另一个 Obsidian 窗口正在装后端/);
    assert.equal(calls.length, 0, '别的窗口在装就不下载、不起进程');
  }
  // 1104（审查 3）：超时整棵结束（Windows 用 taskkill /T），再收尾
  {
    const seen = [];
    B.killTree({ pid: 42, kill: s => seen.push('kill ' + s) }, { platform: 'win32', spawnSyncImpl: (exe, args) => seen.push([exe, ...args].join(' ')) });
    assert.deepEqual(seen, ['taskkill /PID 42 /T /F', 'kill SIGKILL']);
    const r = await B.run(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { timeoutMs: 300 });
    assert.equal(r.code, -2); assert.match(r.err, /已停止/);
  }

  // 3d 每一步失败：不抛、码对、那一步 failed
  const fresh = async (at, home2) => {
    failAt = at; calls.length = 0; const pr = [];
    const o = { ...opts, home: home2, env: { ...process.env, LINK_BRAIN_HOME: home2 }, onProgress: e => pr.push(e) };
    const res = await B.ensureBackend(plugin, o);
    failAt = null;
    return { res, pr };
  };
  let f = await fresh('python', path.join(tmp, 'h-python'));
  assert.equal(f.res.ok, false, JSON.stringify(f.res)); assert.equal(f.res.code, 'TRANSIENT.NETWORK', JSON.stringify(f.res)); assert.match(f.res.message, /装 Python 3\.12 没成功/);
  assert.equal(f.pr.filter(e => e.stage === 'python').at(-1).state, 'failed');
  assert.ok(!f.pr.some(e => e.stage === 'venv'), '后面的步不跑');
  f = await fresh('venv', path.join(tmp, 'h-venv')); assert.equal(f.res.code, 'PERMANENT.BAD_PACKAGE'); assert.match(f.res.message, /建后端环境没成功：error: No interpreter found/);
  f = await fresh('pip', path.join(tmp, 'h-pip')); assert.equal(f.res.code, 'PERMANENT.BAD_PACKAGE'); assert.match(f.res.message, /安装 link-brain 没成功/);
  assert.equal(B.readConfig(path.join(tmp, 'h-pip')).backend_dir, undefined, '没装成不写 backend_dir');
  f = await fresh('check', path.join(tmp, 'h-check')); assert.equal(f.res.code, 'PERMANENT.BAD_PACKAGE'); assert.match(f.res.message, /装好了但跑不起来/);
  // 下载 wheel 校验不过
  f = await (async () => { calls.length = 0; const h = path.join(tmp, 'h-sha'); return { res: await B.ensureBackend(plugin, { ...opts, home: h, env: { ...process.env, LINK_BRAIN_HOME: h }, release: { ...release, wheelSha256: 'f'.repeat(64) } }) }; })();
  assert.equal(f.res.code, 'PERMANENT.CHECKSUM_MISMATCH'); assert.match(f.res.message, /下载 link-brain：校验和不对/);
  assert.ok(!calls.some(c => c[1] === 'pip'), '校验不过就不装');

  // —— 4. upgrade → py-0.2.0、切 backend_dir、上一版留着；再升级删再早的；rollback 切回 ——
  calls.length = 0;
  const first = path.join(home, 'py');
  out = await B.ensureBackend(plugin, { ...opts, upgrade: true, release: { ...release, version: '0.3.0' } });
  assert.equal(out.ok, true, JSON.stringify(out)); assert.match(out.message, /后端已更新到 link-brain 0\.3\.0/);
  const v3 = path.join(home, 'py-0.3.0');
  assert.equal(out.dir, v3);
  assert.deepEqual(B.readConfig(home), { backend_dir: v3, backend_prev_dir: first });
  assert.ok(fs.existsSync(B.venvBackend(first, P)), '上一版目录留着');
  assert.equal(B.managedDir(home), v3);
  // 自检不过的升级：不切
  failAt = 'check';
  out = await B.ensureBackend(plugin, { ...opts, upgrade: true, release: { ...release, version: '0.4.0' } });
  failAt = null;
  assert.equal(out.ok, false); assert.deepEqual(B.readConfig(home), { backend_dir: v3, backend_prev_dir: first }, '自检没过不切 backend_dir');
  // 再升一版：再早的 py/ 删掉，上一版 = py-0.3.0
  out = await B.ensureBackend(plugin, { ...opts, upgrade: true, release: { ...release, version: '0.5.0' } });
  const v5 = path.join(home, 'py-0.5.0');
  assert.equal(out.ok, true); assert.deepEqual(B.readConfig(home), { backend_dir: v5, backend_prev_dir: v3 });
  assert.ok(!fs.existsSync(first), '只留一份上一版，再早的删了');
  assert.ok(fs.existsSync(B.venvBackend(v3, P)));
  // rollback
  located.length = 0;
  out = await B.rollbackBackend(plugin, { ...opts });
  assert.equal(out.ok, true); assert.match(out.message, /已退回上一版后端/);
  assert.deepEqual(B.readConfig(home), { backend_dir: v3, backend_prev_dir: v5 }); assert.equal(located.length, 1);
  assert.ok(fs.existsSync(B.venvBackend(v5, P)), '退回不删任何目录');
  const info = B.managedInfo({ env: opts.env, platform: P, home });
  assert.equal(info.dir, v3); assert.equal(info.installed, true); assert.equal(info.prev, v5); assert.equal(info.python, B.venvPython(v3, P));
  // 没有上一版 → SKIPPED；上一版目录没了 → 如实说
  out = await B.rollbackBackend(plugin, { ...opts, home: path.join(tmp, 'h-venv') });
  assert.equal(out.code, 'SKIPPED.NOT_CONFIGURED'); assert.match(out.message, /没有上一版/);
  fs.rmSync(v5, { recursive: true, force: true });
  out = await B.rollbackBackend(plugin, { ...opts });
  assert.equal(out.ok, false); assert.match(out.message, /上一版目录里没有后端程序了/);

  // —— 5. 解压：Windows 的 PowerShell 命令怎么拼、失败退 tar；其它平台 tar 剥一层（Linux 上真解一个假包）——
  {
    const cmds = [];
    const winRun = async (exe, args) => { cmds.push([exe, ...args]); if (exe === 'powershell.exe') return { code: 1, out: '', err: 'Expand-Archive : boom' }; touch(path.join(tmp, 'winhome', 'bin', 'uv.exe')); return { code: 0, out: '', err: '' }; };
    const ex = await B.extractUv(path.join(tmp, "d'l", 'uv-x86_64-pc-windows-msvc.zip'), path.join(tmp, 'winhome', 'bin'), { platform: 'win32', runImpl: winRun });
    assert.equal(ex.ok, true);
    assert.equal(cmds[0][0], 'powershell.exe');
    assert.ok(cmds[0].includes('-NoProfile') && cmds[0].includes('-NonInteractive'));
    assert.match(cmds[0].at(-1), /^Expand-Archive -LiteralPath '.*d''l.*\.zip' -DestinationPath '.*bin' -Force$/, '单引号转义、-Force 覆盖');
    assert.deepEqual(cmds[1].slice(0, 2), ['tar', '-xf'], 'PowerShell 不行退 tar（Windows 10+ 自带）');
    const ex2 = await B.extractUv(path.join(tmp, 'x.zip'), path.join(tmp, 'winhome2', 'bin'), { platform: 'win32', runImpl: async () => ({ code: 1, out: '', err: 'nope' }) });
    assert.equal(ex2.ok, false); assert.equal(ex2.code, 'PERMANENT.BAD_PACKAGE'); assert.match(ex2.message, /解压 uv 没成功：nope/);
    if (P !== 'win32' && spawnSync('tar', ['--version']).status === 0) {
      const src = path.join(tmp, 'pack', 'uv-x86_64-unknown-linux-gnu'); fs.mkdirSync(src, { recursive: true });
      fs.writeFileSync(path.join(src, 'uv'), '#!/bin/sh\necho uv 0.13.6\n'); fs.writeFileSync(path.join(src, 'uvx'), '');
      const tgz = path.join(tmp, 'pack', 'uv.tar.gz');
      assert.equal(spawnSync('tar', ['-czf', tgz, '-C', path.join(tmp, 'pack'), 'uv-x86_64-unknown-linux-gnu']).status, 0);
      const h3 = path.join(tmp, 'realhome');
      const ex3 = await B.extractUv(tgz, path.join(h3, 'bin'), { platform: P });
      assert.equal(ex3.ok, true, JSON.stringify(ex3));
      assert.equal(ex3.path, path.join(h3, 'bin', 'uv'));
      assert.ok(fs.statSync(ex3.path).mode & 0o100, '可执行');
      assert.equal(fs.readFileSync(ex3.path, 'utf8').trim().split('\n').pop(), 'echo uv 0.13.6');
    }
  }

  // —— 6. 目录规则和 Python deps.managed_dir 一致：backend_dir 相对路径按 ~/.link-brain；坏 config 退默认 ——
  {
    const h = path.join(tmp, 'h-cfg'); fs.mkdirSync(h, { recursive: true });
    fs.writeFileSync(path.join(h, 'config.json'), JSON.stringify({ backend_dir: 'py-9' }));
    assert.equal(B.managedDir(h), path.join(h, 'py-9'));
    fs.writeFileSync(path.join(h, 'config.json'), '{坏');
    assert.equal(B.managedDir(h), path.join(h, 'py'));
    assert.deepEqual(B.readConfig(h), {});
    assert.throws(() => B.writeConfig(h, { a: 1 }), /config.json 读不懂，没改它/, '读不懂的不覆盖');
    assert.equal(B.homeDir({ env: { LINK_BRAIN_HOME: '/x/y' } }), '/x/y');
    assert.equal(B.homeDir({ env: {}, home: '/home/u' }), path.join('/home/u', '.link-brain'));
    assert.equal(B.venvPython('/h/py', 'win32'), path.join('/h/py', 'Scripts', 'python.exe'));
    assert.equal(B.venvBackend('/h/py', 'linux'), path.join('/h/py', 'bin', 'link-brain'));
  }

  server.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log('PASS backend-install (1102): uv asset table, download (.part / sha256 / resume / 404 / 5xx / redirect / cleanup), ensureBackend 5 stages + per-stage failure codes, upgrade keeps one previous + rollback, extract (PowerShell → tar / tar --strip-components)');
})().catch(e => { console.error(e); server.close(); process.exit(1); });

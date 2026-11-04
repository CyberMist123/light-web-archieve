// backend-install.js — 1102 托管模式（RELEASE-BAR P8「装一个插件就行」）：机器上没有 Python 也能自己装好后端。
//   目录（docs/SETUP-CONTRACT.md「托管模式」）：~/.link-brain/bin/uv(.exe) · ~/.link-brain/python/（uv 管的 CPython）·
//   ~/.link-brain/py/（uv 建的 venv，装 link-brain；升级装到 py-<版本>/，config.json 的 backend_dir 指过去，上一版留一份）。
//   步骤 ensureBackend：① 下载 uv 的 Release 包（按平台选资产，写 .part、算 sha256、对上才改名、解压）② uv python install 3.12
//   ③ uv venv ④ uv pip install --require-hashes -r requirements.lock + wheel（都来自 LWA 自己的 Release，sha256 写成常量）⑤ 自检。
//   这时机器上还没有 Python，所以全部纯 JS（Node https / crypto），解压用 PowerShell Expand-Archive（Windows）/ tar（其它）。
//   每一步 onProgress({stage, label, done, total, text, state})；失败返回 CONVENTIONS §1 形状 {ok:false, code, message}，不抛。
//   rollbackBackend：config.json 的 backend_dir 切回上一版（backend_prev_dir）。
// main.js 只接几行：backendInstall() 按需 require；pickBackend / whichCommand 把托管目录当固定候选；设置页「更新后端 / 退回上一版后端」调这里。
// 不许在这里起 Python：唯一起的子进程是 uv（和解压用的 PowerShell / tar）。
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const http = require('http');
const https = require('https');
const { spawn } = require('child_process');

// —— uv 的发布件（2026-11-02 到 https://github.com/astral-sh/uv/releases 核实：当前稳定版 0.13.6，sha256 取自每个资产旁边的 .sha256 文件）——
const UV_RELEASE = {
  version: '0.13.6',
  base: 'https://github.com/astral-sh/uv/releases/download/0.13.6/',
  assets: {
    'win32-x64': { name: 'uv-x86_64-pc-windows-msvc.zip', sha256: 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f' },
    'win32-arm64': { name: 'uv-aarch64-pc-windows-msvc.zip', sha256: 'c2426c0c8e28b53d8c440e47a18d96ad4db51e159866c0e81435b196d7f0081c' },
    'darwin-arm64': { name: 'uv-aarch64-apple-darwin.tar.gz', sha256: '60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472' },
    'darwin-x64': { name: 'uv-x86_64-apple-darwin.tar.gz', sha256: '63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02' },
    'linux-x64': { name: 'uv-x86_64-unknown-linux-gnu.tar.gz', sha256: 'f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645' },
    'linux-arm64': { name: 'uv-aarch64-unknown-linux-gnu.tar.gz', sha256: '229e194255c7958d86d56e8790d969a6f74736592133f0dfd0076f754c642c1d' },
  },
};
const PYTHON_VERSION = '3.12';
// —— LWA 自己的后端发布件（发布工作流由另一个会话在做，按 reader-v0.2.0 的约定：标签 v<版本>，资产 = wheel + 带哈希的 requirements.lock + SHA256SUMS）。
//    TODO：Release v0.2.0 发出来后回填 wheelSha256 / lockSha256（SHA256SUMS 里的值）。两个哈希为空时 ensureBackend 如实说「后端发布包还没发布」，不装。
const BACKEND_RELEASE = {
  version: '0.2.2',
  wheelUrl: 'https://github.com/CyberMist123/light-web-archieve/releases/download/v0.2.2/link_brain-0.2.2-py3-none-any.whl',
  wheelSha256: 'a1538aa31eec52ee03161ca3b64217177691be88bfb36a284979f89ce08ce8f1',   // Release v0.2.2 的 SHA256SUMS（1103：本机下载核对过；lock 带 ocr/bilibili/docs）
  lockUrl: 'https://github.com/CyberMist123/light-web-archieve/releases/download/v0.2.2/requirements.lock',
  lockSha256: 'fcc55028caabd2c77e1990370c8d03144625fb20630a91b3f533803cb0f83605',
};
// 1103 作者：OCR / B 站 / 附件转文字默认一起装（Release 的 lock 带这三个 extra，见 python-release.yml），用户不开的功能只是不显示
const BACKEND_EXTRAS = ['ocr', 'bilibili', 'docs'];
const STAGES = [['uv', '准备安装工具 uv'], ['python', '准备 Python ' + PYTHON_VERSION], ['venv', '建后端环境'], ['install', '安装 link-brain'], ['check', '自检']];
const STAGE_LABEL = Object.fromEntries(STAGES);
const BACKEND_DIR_KEY = 'backend_dir', PREV_DIR_KEY = 'backend_prev_dir';
const MANAGED_DIRNAME = 'py';
const REQUEST_IDLE_MS = 60000;
const MAX_REDIRECTS = 5;

const fail = (code, message, extra = null) => ({ ok: false, code, message, ...(extra || {}) });
const isWin = platform => platform === 'win32';
const sha256File = file => new Promise((resolve, reject) => {
  const h = crypto.createHash('sha256');
  fs.createReadStream(file).on('data', d => h.update(d)).on('error', reject).on('end', () => resolve(h.digest('hex')));
});

// 目录：LINK_BRAIN_HOME 或 ~/.link-brain（和 Python storage.link_brain_home、main.js writeUserConfig 同一规则）
function homeDir({ env = process.env, home = os.homedir() } = {}) { return env.LINK_BRAIN_HOME || path.join(home, '.link-brain'); }
function uvExe(home, platform = process.platform) { return path.join(home, 'bin', isWin(platform) ? 'uv.exe' : 'uv'); }
function venvPython(dir, platform = process.platform) { return isWin(platform) ? path.join(dir, 'Scripts', 'python.exe') : path.join(dir, 'bin', 'python'); }
function venvBackend(dir, platform = process.platform) { return isWin(platform) ? path.join(dir, 'Scripts', 'link-brain.exe') : path.join(dir, 'bin', 'link-brain'); }
function uvAsset(platform = process.platform, arch = process.arch) {
  const key = `${platform}-${arch}`;
  const a = UV_RELEASE.assets[key];
  return a ? { ...a, key, url: UV_RELEASE.base + a.name } : null;
}
// ~/.link-brain/config.json：读不懂 = 空（和 Python storage.user_config 一样 fail-open）；写 = 合并、先写临时文件再换名
function readConfig(home) {
  try { const raw = JSON.parse(fs.readFileSync(path.join(home, 'config.json'), 'utf8').replace(/^﻿/, '')); return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}; }
  catch { return {}; }
}
function writeConfig(home, patch) {
  const file = path.join(home, 'config.json');
  let cur = {};
  try { cur = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/, '')); }
  catch (e) { if (e.code !== 'ENOENT') throw new Error('config.json 读不懂，没改它：' + e.message); }
  if (!cur || typeof cur !== 'object' || Array.isArray(cur)) throw new Error('config.json 不是一个对象，没改它');
  fs.mkdirSync(home, { recursive: true });
  const tmp = file + '.tmp-' + process.pid;
  fs.writeFileSync(tmp, JSON.stringify({ ...cur, ...patch }, null, 2), 'utf8');
  fs.renameSync(tmp, file);
  return file;
}
// 当前托管目录：config.json 的 backend_dir（相对的按 ~/.link-brain 解析）→ 默认 ~/.link-brain/py（Python deps.managed_dir 同一规则）
function managedDir(home) {
  const v = readConfig(home)[BACKEND_DIR_KEY];
  if (typeof v === 'string' && v.trim()) { const p = v.trim(); return path.isAbsolute(p) ? p : path.join(home, p); }
  return path.join(home, MANAGED_DIRNAME);
}

// —— 下载：写 <dest>.part（有残片就带 Range 续传）、算 sha256、对上才改名成 dest。sha256 不对 → 删 .part 和 dest。
//    返回 {ok, path} 或 {ok:false, code, message}。request 可注入（单测用本地 http 假服务器，不真下载）。
function download(url, dest, { sha256 = '', onProgress = null, request = null, label = '' } = {}) {
  const part = dest + '.part';
  const doRequest = (u, headers) => new Promise((resolve, reject) => {
    const mod = request ? { request } : (String(u).startsWith('http:') ? http : https);
    const req = mod.request(u, { method: 'GET', headers: { 'User-Agent': 'link-brain-plugin', ...headers } }, res => resolve(res));
    req.on('error', reject);
    req.setTimeout?.(REQUEST_IDLE_MS, () => req.destroy(Object.assign(new Error('连接超过 60 秒没有数据'), { code: 'ETIMEDOUT' })));
    req.end();
  });
  return (async () => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    let have = 0;
    try { have = fs.statSync(part).size; } catch { have = 0; }
    let res = null, u = url;
    try {
      for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
        res = await doRequest(u, have > 0 ? { Range: `bytes=${have}-` } : {});
        if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
          res.resume();
          u = new URL(res.headers.location, u).toString();
          if (hop === MAX_REDIRECTS) return fail('TRANSIENT.NETWORK', `${label || '下载'}：跳转太多次（${url}）`);
          continue;
        }
        break;
      }
    } catch (e) { return fail('TRANSIENT.NETWORK', `${label || '下载'}没连上：${e.message}`); }
    if (res.statusCode === 416 && have > 0) { res.resume(); }   // 残片已经是整个文件：直接校验
    else if (res.statusCode === 206 && have > 0) { /* 续传：接着写 */ }
    else if (res.statusCode === 200) { have = 0; }               // 服务器不认 Range：从头来
    else if (res.statusCode >= 500) { res.resume(); return fail('TRANSIENT.HTTP_5XX', `${label || '下载'}：服务器出错（HTTP ${res.statusCode}）`); }
    else if (res.statusCode !== 206) { res.resume(); return fail('PERMANENT.BAD_PACKAGE', `${label || '下载'}：发布包不存在（HTTP ${res.statusCode}）：${url}`); }
    if (res.statusCode !== 416) {
      const len = Number(res.headers['content-length']);
      const total = Number.isFinite(len) && len > 0 ? have + len : null;
      let done = have;
      const emit = () => onProgress && onProgress({ done, total, text: total ? `${(done / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} MB` : `${(done / 1048576).toFixed(1)} MB` });
      try {
        await new Promise((resolve, reject) => {
          const out = fs.createWriteStream(part, { flags: have > 0 ? 'a' : 'w' });
          let last = 0;
          res.on('data', d => { done += d.length; const now = Date.now(); if (now - last > 200) { last = now; emit(); } });
          res.on('error', reject); out.on('error', reject);
          res.on('aborted', () => reject(Object.assign(new Error('连接中断'), { code: 'ECONNRESET' })));
          out.on('finish', resolve);
          res.pipe(out);
        });
        emit();
      } catch (e) {
        if (e.code === 'ENOSPC') return fail('PERMANENT.DISK_FULL', `${label || '下载'}：磁盘空间不够`);
        return fail('TRANSIENT.NETWORK', `${label || '下载'}中断（已下 ${(done / 1048576).toFixed(1)} MB，下次接着下）：${e.message}`);
      }
    }
    if (sha256) {
      const got = await sha256File(part);
      if (got.toLowerCase() !== String(sha256).toLowerCase()) {
        try { fs.unlinkSync(part); } catch {}
        try { fs.unlinkSync(dest); } catch {}
        return fail('PERMANENT.CHECKSUM_MISMATCH', `${label || '下载'}：校验和不对（期望 ${String(sha256).slice(0, 12)}…，实际 ${got.slice(0, 12)}…），已删掉，没有安装`);
      }
    }
    try { fs.renameSync(part, dest); } catch (e) { return fail('PERMANENT.DISK_FULL', `${label || '下载'}：写不进 ${dest}：${e.message}`); }
    return { ok: true, path: dest };
  })();
}

// —— 子进程（只给 uv / PowerShell / tar 用；不许起 Python）——
function run(exe, args, { env = process.env, cwd = undefined, onLine = null, timeoutMs = 0 } = {}) {
  return new Promise(resolve => {
    let out = '', err = '', buf = '', timer = null, child;
    try { child = spawn(exe, args, { env, cwd, windowsHide: true }); }
    catch (e) { return resolve({ code: -1, out: '', err: e.message }); }
    const line = s => { buf += s; let i; while ((i = buf.indexOf('\n')) >= 0) { const l = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (l && onLine) { try { onLine(l); } catch {} } } };
    child.stdout?.on('data', d => { const s = d.toString(); out += s; line(s); });
    child.stderr?.on('data', d => { const s = d.toString(); err += s; line(s); });
    const finish = (code, e) => { clearTimeout(timer); if (buf.trim() && onLine) { try { onLine(buf.trim()); } catch {} } buf = ''; resolve({ code, out, err: e ? (err + e) : err }); };
    let timedOut = false;
    child.on('error', e => finish(-1, e.message));
    child.on('close', code => finish(timedOut ? -2 : code == null ? -1 : code, timedOut ? `超过 ${Math.round(timeoutMs / 60000)} 分钟没有结果，已停止` : undefined));
    // 1104（审查 3）：超时整棵结束（uv 会起下载 / 编译子进程，只杀直接进程会留下后代攥着管道），等它真退了才报「已停止」；
    // 5 秒还没退也照样收尾，免得这里一直挂着
    if (timeoutMs > 0) timer = setTimeout(() => {
      timedOut = true;
      killTree(child);
      setTimeout(() => finish(-2, `超过 ${Math.round(timeoutMs / 60000)} 分钟没有结果，已停止`), 5000);
    }, timeoutMs);
  });
}
function killTree(child, { platform = process.platform, spawnSyncImpl = require('child_process').spawnSync } = {}) {
  if (isWin(platform) && child && child.pid) {
    try { spawnSyncImpl('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, timeout: 15000 }); } catch {}
  }
  try { child.kill('SIGKILL'); } catch {}
}

// —— 1104（审查 4）：装后端跨进程一把锁（两个 Obsidian 窗口 / 两个库共用 ~/.link-brain/py）——
// 锁文件 ~/.link-brain/locks/backend-install.lock：{pid, started}。持有者进程没了、或超过 3 小时，算过期，删了重拿。
const INSTALL_LOCK_STALE_MS = 3 * 3600000;
function pidAlive(pid) { try { process.kill(pid, 0); return true; } catch (e) { return !!(e && e.code === 'EPERM'); } }
function takeInstallLock(home, { now = Date.now(), alive = pidAlive, pid = process.pid } = {}) {
  const file = path.join(home, 'locks', 'backend-install.lock');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  for (let i = 0; i < 2; i++) {
    try {
      const fd = fs.openSync(file, 'wx');
      fs.writeSync(fd, JSON.stringify({ pid, started: now, owner: '装后端' }));
      fs.closeSync(fd);
      return { ok: true, release: () => { try { const cur = JSON.parse(fs.readFileSync(file, 'utf8')); if (cur.pid === pid) fs.unlinkSync(file); } catch {} } };
    } catch (e) {
      if (!e || e.code !== 'EEXIST') return { ok: true, release: () => {} };   // 锁文件建不了（只读盘等）：不因为锁挡住安装
      let cur = null;
      try { cur = JSON.parse(fs.readFileSync(file, 'utf8')); } catch {}
      const stale = !cur || !Number.isFinite(cur.pid) || !alive(cur.pid) || now - (Number(cur.started) || 0) > INSTALL_LOCK_STALE_MS;
      if (!stale) return { ok: false, holder: cur };
      try { fs.unlinkSync(file); } catch {}
    }
  }
  return { ok: false, holder: null };
}
const lastLine = r => String(r.err || r.out || '').trim().split('\n').filter(Boolean).pop() || `退出码 ${r.code}`;
// uv 的环境：Python 和缓存都收进 ~/.link-brain，不往 ~/.local/bin 放 python 启动器、不写 Windows 注册表、只用自己管的 Python
function uvEnv(home, base = process.env) {
  return { ...base, UV_PYTHON_INSTALL_DIR: path.join(home, 'python'), UV_CACHE_DIR: path.join(home, 'uv-cache'),
    UV_PYTHON_INSTALL_BIN: '0', UV_PYTHON_INSTALL_REGISTRY: '0', UV_PYTHON_PREFERENCE: 'only-managed', UV_NO_MODIFY_PATH: '1' };
}

// —— 解压 uv 的发布包到 ~/.link-brain/bin/：zip（Windows）用 PowerShell Expand-Archive，tar.gz 用 tar（包里有一层目录，剥掉）——
async function extractUv(archive, binDir, { platform = process.platform, runImpl = run } = {}) {
  fs.mkdirSync(binDir, { recursive: true });
  let r;
  if (archive.endsWith('.zip')) {
    if (isWin(platform)) {
      const ps = (s) => "'" + String(s).replace(/'/g, "''") + "'";
      r = await runImpl('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command',
        `Expand-Archive -LiteralPath ${ps(archive)} -DestinationPath ${ps(binDir)} -Force`], { timeoutMs: 5 * 60000 });
      if (r.code !== 0) r = await runImpl('tar', ['-xf', archive, '-C', binDir], { timeoutMs: 5 * 60000 });   // Windows 10+ 自带 bsdtar，也认 zip
    } else r = await runImpl('tar', ['-xf', archive, '-C', binDir], { timeoutMs: 5 * 60000 });
  } else {
    r = await runImpl('tar', ['-xzf', archive, '-C', binDir, '--strip-components=1'], { timeoutMs: 5 * 60000 });
  }
  if (r.code !== 0) return fail('PERMANENT.BAD_PACKAGE', '解压 uv 没成功：' + lastLine(r));
  const exe = uvExe(path.dirname(binDir), platform);
  if (!fs.existsSync(exe)) return fail('PERMANENT.BAD_PACKAGE', `解压后没有 ${path.basename(exe)}（包的内容和预期不一样）`);
  if (!isWin(platform)) { try { fs.chmodSync(exe, 0o755); } catch {} }
  return { ok: true, path: exe };
}

// —— 自检：link-brain version（另一个会话在加这个子命令）；没有就退回 python -m link_brain --help 也算过 ——
async function selfCheck(dir, { platform = process.platform, runImpl = run, env = process.env } = {}) {
  const exe = venvBackend(dir, platform), py = venvPython(dir, platform);
  const r = await runImpl(exe, ['version'], { env, timeoutMs: 120000 });
  if (r.code !== 0) {
    const r2 = await runImpl(py, ['-m', 'link_brain', '--help'], { env, timeoutMs: 120000 });
    if (r2.code !== 0) return fail('PERMANENT.BAD_PACKAGE', '装好了但跑不起来：' + lastLine(r.code === -1 ? r2 : r), { exe, python: py });
  }
  // 1104（审查 11）：version 特意不加载依赖，过了不等于后端能用——再做一次不联网、不加载认字模型的核心检查
  //（`setup check --components core`：核心依赖都 import 得到）；版本只显示版本号，不把整行 JSON 摆给人看
  const version = versionText(r.code === 0 ? r.out : '');
  const k = await runImpl(exe, ['setup', 'check', '--components', 'core'], { env, timeoutMs: 180000 });
  if (k.code !== 0) {
    let why = '';
    try { const j = JSON.parse(String(k.out || '').trim().split('\n').pop()); why = (j && (j.message || (j.results && j.results[0] && (j.results[0].detail || j.results[0].fix_hint)))) || ''; } catch {}
    return fail('PERMANENT.BAD_PACKAGE', '装好了，但核心功能跑不起来：' + (why || lastLine(k)), { exe, python: py });
  }
  return { ok: true, exe, python: py, version };
}
function versionText(out) {
  const last = String(out || '').trim().split('\n').pop() || '';
  try { const j = JSON.parse(last); if (j && j.version) return String(j.version); } catch {}
  return last.slice(0, 40);
}

// —— 1103：uv pip install 的输出 → 一句人话（uv 不给机读进度、也不报总字节数，所以只翻译它说了什么，不编百分比；
//   界面上这一步画不定进度条）。下好了几个大文件计个数，让人知道在动。认不出的行返回 null（不改进度文字）。
function uvInstallMeter() {
  let pkgs = 0, big = 0, got = 0;
  return line => {
    const l = String(line || '').trim();
    let m, text = null;
    if ((m = /^Resolved (\d+) packages?/i.exec(l))) { pkgs = Number(m[1]); text = `要装 ${pkgs} 个依赖包，开始下载…`; }
    else if ((m = /^Downloading (\S+) \(([^)]+)\)/i.exec(l))) { big++; text = `正在下载 ${m[1]}（${m[2].replace(/MiB/i, ' MB').replace(/KiB/i, ' KB').replace(/GiB/i, ' GB')}）`; }
    else if ((m = /^Downloaded (\S+)/i.exec(l))) { got++; text = `下载好了 ${m[1]}（大文件 ${got}/${big}）`; }
    else if (/^Prepared \d+ packages?/i.test(l)) text = '下载完了，正在安装…';
    else if ((m = /^\+ (\S+?)==/.exec(l))) text = `已装 ${m[1]}`;
    else if (/^Installed \d+ packages?/i.test(l)) text = '依赖都装好了';
    else return null;
    return { done: null, total: null, text };
  };
}

// uv python install 的一行 → 给人看的一句（认不出的原样截短）
function pythonLineText(line) {
  const l = String(line || '').trim();
  let m;
  if ((m = /^Downloading cpython-(\d+\.\d+\.\d+)\S*.*?\(([\d.]+)\s*MiB\)/i.exec(l))) return `正在下载 Python ${m[1]}（${m[2]} MB）`;
  if ((m = /^Installed Python (\S+)/i.exec(l))) return `Python ${m[1]} 装好了`;
  return l.slice(0, 160);
}

// —— 主流程 ——
// ensureBackend(plugin, {onProgress, upgrade}) → {ok, code, message, dir, python, exe, stages}
//   upgrade=false：托管目录里已经有能跑的后端就只自检；没有就装到 ~/.link-brain/py。
//   upgrade=true：装到 ~/.link-brain/py-<BACKEND_RELEASE.version>/，自检过了才把 config.json 的 backend_dir 指过去；上一版留一份（再早的删）。
async function ensureBackend(plugin, { onProgress = null, upgrade = false, env = process.env, platform = process.platform, arch = process.arch,
  home = homeDir({ env }), request = null, runImpl = run, release = BACKEND_RELEASE, uvRelease = null, pythonVersion = PYTHON_VERSION } = {}) {
  const stages = {};
  const progress = (stage, patch) => {
    const cur = stages[stage] || { stage, label: STAGE_LABEL[stage] || stage, done: null, total: null, text: '', state: 'running' };
    stages[stage] = { ...cur, ...patch };
    if (onProgress) { try { onProgress({ ...stages[stage] }); } catch (e) { console.error('[lb] 进度没画上', e); } }
  };
  const bad = (stage, r) => { progress(stage, { state: 'failed', text: r.message }); return { ...r, stages }; };
  let lock = null;
  try {
    const uvEnvironment = uvEnv(home, env);
    const asset = uvRelease ? uvRelease.asset : uvAsset(platform, arch);
    const uv = uvExe(home, platform);
    const curDir = managedDir(home);
    const targetDir = upgrade ? path.join(home, `${MANAGED_DIRNAME}-${release.version}`) : curDir;
    const haveBackend = fs.existsSync(venvBackend(curDir, platform));

    // 已经装好、不是升级：只自检
    if (!upgrade && haveBackend) {
      for (const [st] of STAGES.slice(0, 4)) progress(st, { state: 'skipped', text: '已经有了' });
      progress('check', { text: '正在自检…' });
      const c = await selfCheck(curDir, { platform, runImpl, env: uvEnvironment });
      if (!c.ok) return bad('check', c);
      progress('check', { state: 'ok', text: c.version || '能跑' });
      return { ok: true, code: '', message: '后端已经装好' + (c.version ? `（${c.version}）` : ''), dir: curDir, python: c.python, exe: c.exe, stages };
    }
    if (!release.wheelSha256 || !release.lockSha256) {
      progress('install', { state: 'failed', text: '后端发布包还没发布' });
      return { ...fail('SKIPPED.NOT_CONFIGURED', `后端发布包（v${release.version}）还没发布：等作者发出 Release 后更新插件再点一次`), stages };
    }
    lock = takeInstallLock(home);
    if (!lock.ok) {
      progress('uv', { state: 'failed', text: '另一个窗口正在装' });
      return { ...fail('TRANSIENT.BUSY', '另一个 Obsidian 窗口正在装后端（共用同一份），等它装完这里会自己认到；过几分钟再点一次也行'), stages };
    }

    // ① uv
    progress('uv', { text: '检查…' });
    let haveUv = fs.existsSync(uv) && (await runImpl(uv, ['--version'], { env: uvEnvironment, timeoutMs: 60000 })).code === 0;
    if (!haveUv) {
      if (!asset) return bad('uv', fail('PERMANENT.BAD_PACKAGE', `这台电脑（${platform} ${arch}）没有对应的 uv 发布包；请到设置里手填「后端命令」`));
      const archive = path.join(home, 'downloads', asset.name);
      let got = fs.existsSync(archive) && (await sha256File(archive)) === asset.sha256 ? { ok: true, path: archive } : null;
      if (!got) {
        progress('uv', { text: '下载 uv ' + (uvRelease ? uvRelease.version : UV_RELEASE.version) });
        got = await download(asset.url, archive, { sha256: asset.sha256, request, label: '下载 uv', onProgress: p => progress('uv', p) });
        if (!got.ok) return bad('uv', got);
      }
      progress('uv', { done: null, total: null, text: '解压…' });
      const ex = await extractUv(archive, path.join(home, 'bin'), { platform, runImpl });
      if (!ex.ok) return bad('uv', ex);
      const v = await runImpl(uv, ['--version'], { env: uvEnvironment, timeoutMs: 60000 });
      if (v.code !== 0) return bad('uv', fail('PERMANENT.BAD_PACKAGE', 'uv 解压出来了但跑不起来：' + lastLine(v)));
      try { fs.unlinkSync(archive); } catch {}
    }
    progress('uv', { state: 'ok', text: '就绪' });

    // ② Python
    progress('python', { text: `uv python install ${pythonVersion}（第一次要下载约 30 MB）` });
    const py = await runImpl(uv, ['python', 'install', pythonVersion], { env: uvEnvironment, timeoutMs: 20 * 60000, onLine: l => progress('python', { text: pythonLineText(l) }) });
    if (py.code !== 0) return bad('python', fail(/download|fetch|connect|timed out|dns/i.test(py.err + py.out) ? 'TRANSIENT.NETWORK' : 'PERMANENT.BAD_PACKAGE', `装 Python ${pythonVersion} 没成功：` + lastLine(py)));
    progress('python', { state: 'ok', text: `Python ${pythonVersion} 就绪` });

    // ③ venv
    progress('venv', { text: `uv venv ${targetDir}` });
    const vv = await runImpl(uv, ['venv', targetDir, '--python', pythonVersion, '--seed', '--quiet'], { env: uvEnvironment, timeoutMs: 5 * 60000 });
    if (vv.code !== 0) return bad('venv', fail('PERMANENT.BAD_PACKAGE', '建后端环境没成功：' + lastLine(vv)));
    const pyExe = venvPython(targetDir, platform);
    progress('venv', { state: 'ok', text: pyExe });

    // ④ wheel + lock → uv pip install --require-hashes
    const dl = path.join(home, 'downloads');
    const lockFile = path.join(dl, `requirements-${release.version}.lock`), wheelFile = path.join(dl, path.basename(new URL(release.wheelUrl).pathname));
    progress('install', { text: '下载依赖清单…' });
    const lk = await download(release.lockUrl, lockFile, { sha256: release.lockSha256, request, label: '下载依赖清单' });
    if (!lk.ok) return bad('install', lk);
    progress('install', { text: '下载 link-brain…' });
    const wh = await download(release.wheelUrl, wheelFile, { sha256: release.wheelSha256, request, label: '下载 link-brain', onProgress: p => progress('install', { ...p, text: 'link-brain ' + p.text }) });
    if (!wh.ok) return bad('install', wh);
    // wheel 也走 --require-hashes：写一行带 --hash 的直连需求（本地文件 URL）
    const wheelReq = path.join(dl, `link-brain-${release.version}.txt`);
    fs.writeFileSync(wheelReq, `link-brain[${BACKEND_EXTRAS.join(',')}] @ ${fileUrl(wheelFile)} --hash=sha256:${release.wheelSha256}\n`, 'utf8');
    const meter = uvInstallMeter();
    progress('install', { done: null, total: null, text: '准备安装依赖（认字、B 站下载等，约几百 MB）…' });
    const inst = await runImpl(uv, ['pip', 'install', '--python', pyExe, '--require-hashes', '-r', lockFile, '-r', wheelReq],
      { env: uvEnvironment, timeoutMs: 30 * 60000, onLine: l => { const p = meter(l); if (p) progress('install', p); } });
    if (inst.code !== 0) {
      const text = inst.err + inst.out;
      const code = /Failed building wheel|No matching distribution|requires a different Python|No solution found|hash/i.test(text) ? 'PERMANENT.BAD_PACKAGE'
        : /ConnectionError|ReadTimeout|ProxyError|Failed to fetch|error sending request|timed out/i.test(text) ? 'TRANSIENT.NETWORK' : 'TRANSIENT.NETWORK';
      return bad('install', fail(code, '安装 link-brain 没成功：' + lastLine(inst)));
    }
    progress('install', { state: 'ok', text: `link-brain ${release.version}` });

    // ⑤ 自检；升级时过了才切 backend_dir
    progress('check', { text: '正在自检…' });
    const c = await selfCheck(targetDir, { platform, runImpl, env: uvEnvironment });
    if (!c.ok) return bad('check', c);
    progress('check', { state: 'ok', text: c.version || '能跑' });
    if (upgrade || path.resolve(targetDir) !== path.resolve(curDir)) {
      const cfg = readConfig(home);
      const prev = typeof cfg[PREV_DIR_KEY] === 'string' ? cfg[PREV_DIR_KEY] : '';
      // 上一版留一份：再早的那份删掉（只删 ~/.link-brain 下 py* 开头的目录，别的路径不碰）
      if (prev && path.resolve(prev) !== path.resolve(curDir) && path.resolve(prev) !== path.resolve(targetDir) && insideManaged(home, prev)) {
        try { fs.rmSync(prev, { recursive: true, force: true }); } catch (e) { console.error('[lb] 旧后端目录没删掉', e); }
      }
      writeConfig(home, { [BACKEND_DIR_KEY]: targetDir, [PREV_DIR_KEY]: haveBackend ? curDir : (prev || '') });
    } else if (!readConfig(home)[BACKEND_DIR_KEY]) writeConfig(home, { [BACKEND_DIR_KEY]: targetDir });
    if (plugin && typeof plugin.locateCollection === 'function') { try { await plugin.locateCollection(); } catch (e) { console.error('[lb] 后端位置没刷新', e); } }
    return { ok: true, code: '', message: (upgrade ? '后端已更新到 ' : '后端装好了：') + `link-brain ${release.version}` + (c.version ? `（${c.version}）` : ''), dir: targetDir, python: c.python, exe: c.exe, stages };
  } catch (e) {
    return { ...fail(e && e.code === 'ENOSPC' ? 'PERMANENT.DISK_FULL' : 'PERMANENT.BAD_PACKAGE', '安装后端时出错：' + (e && e.message || e)), stages };
  } finally {
    if (lock && lock.release) lock.release();
  }
}
function fileUrl(p) { let s = path.resolve(p).replace(/\\/g, '/'); if (!s.startsWith('/')) s = '/' + s; return 'file://' + encodeURI(s); }
function insideManaged(home, dir) { const rel = path.relative(home, dir); return !!rel && !rel.startsWith('..') && !path.isAbsolute(rel) && /^py(-|$)/.test(rel.split(/[\\/]/)[0]); }

// 退回上一版：backend_dir ↔ backend_prev_dir 对调（上一版目录得还在、里面有后端）。不删任何目录。
async function rollbackBackend(plugin, { env = process.env, platform = process.platform, home = homeDir({ env }), runImpl = run } = {}) {
  const cfg = readConfig(home);
  const cur = managedDir(home), prev = typeof cfg[PREV_DIR_KEY] === 'string' ? cfg[PREV_DIR_KEY].trim() : '';
  if (!prev) return fail('SKIPPED.NOT_CONFIGURED', '没有上一版后端可退（还没更新过）');
  const prevDir = path.isAbsolute(prev) ? prev : path.join(home, prev);
  if (!fs.existsSync(venvBackend(prevDir, platform))) return fail('PERMANENT.BAD_PACKAGE', `上一版目录里没有后端程序了（${prevDir}）`);
  const c = await selfCheck(prevDir, { platform, runImpl, env: uvEnv(home, env) });
  if (!c.ok) return { ...c, message: '上一版跑不起来，没有切换：' + c.message };
  try { writeConfig(home, { [BACKEND_DIR_KEY]: prevDir, [PREV_DIR_KEY]: cur }); }
  catch (e) { return fail('PERMANENT.BAD_PACKAGE', '没写上 config.json：' + e.message); }
  if (plugin && typeof plugin.locateCollection === 'function') { try { await plugin.locateCollection(); } catch (e) { console.error('[lb] 后端位置没刷新', e); } }
  return { ok: true, code: '', message: '已退回上一版后端' + (c.version ? `（${c.version}）` : '') + '：' + prevDir, dir: prevDir, python: c.python, exe: c.exe };
}

// 设置页只读显示用：当前托管目录、python、link-brain、有没有上一版
function managedInfo({ env = process.env, platform = process.platform, home = homeDir({ env }) } = {}) {
  const dir = managedDir(home), cfg = readConfig(home);
  return { home, dir, python: venvPython(dir, platform), exe: venvBackend(dir, platform), uv: uvExe(home, platform),
    installed: fs.existsSync(venvBackend(dir, platform)), prev: typeof cfg[PREV_DIR_KEY] === 'string' && cfg[PREV_DIR_KEY] ? cfg[PREV_DIR_KEY] : '' };
}

module.exports = { takeInstallLock, killTree, versionText, ensureBackend, rollbackBackend, managedInfo, download, extractUv, selfCheck, run, uvAsset, uvEnv, homeDir, managedDir, uvExe, venvPython, venvBackend,
  readConfig, writeConfig, fileUrl, uvInstallMeter, pythonLineText, UV_RELEASE, BACKEND_RELEASE, BACKEND_EXTRAS, PYTHON_VERSION, STAGES };

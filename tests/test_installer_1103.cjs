// 1103 安装窗口（installer-ui.js）+ uv 安装进度（backend-install.js uvInstallMeter）：
//   总进度只进不退、按步骤权重算；没真进度的步骤按时间挪但不到头；出错一句人话 + 重试；后端 → 读取组件 → OCR 依次装；
//   OCR 没装好不算失败（同步照样跑），后端没装上算失败；用户点「开始同步」或关窗口后 openAndRun 才返回；
//   装后端期间「没找到后端程序」改说「正在安装」。
'use strict';
const assert = require('assert');
const path = require('path');
const { makeDom } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');

const DIR = path.join(__dirname, '..', 'obsidian-plugins', 'link-brain-actions');
const installerUI = require(path.join(DIR, 'installer-ui.js'));
const BI = require(path.join(DIR, 'backend-install.js'));
const { overallPct, stepFraction, currentText, friendlyError, componentEvent } = installerUI._internals;

(async () => {
  // ── 纯函数 ──
  assert.equal(overallPct({}), 0);
  const allOk = Object.fromEntries(installerUI._internals.WEIGHTS.map(([k]) => [k, { state: 'ok' }]));
  assert.equal(overallPct(allOk), 100);
  // 下依赖那一步跑到一半（千分制 500/1000）：前面几步都好了
  const half = { uv: { state: 'ok' }, python: { state: 'ok' }, venv: { state: 'ok' }, install: { state: 'running', done: 500, total: 1000 } };
  assert.equal(overallPct(half), 42, '4+10+2+26 = 42');
  // 没真进度：按时间挪，10 分钟后也不到这一步的头
  const t0 = 1_000_000;
  assert.ok(stepFraction({ stage: 'python', state: 'running', startedAt: t0 }, t0 + 600000) < 0.9);
  assert.ok(stepFraction({ stage: 'python', state: 'running', startedAt: t0 }, t0 + 20000) > 0.2);
  assert.equal(currentText({ uv: { state: 'ok' }, python: { state: 'running', text: '正在下载 Python 3.12.16（20.1 MB）' } }), '下载 Python：正在下载 Python 3.12.16（20.1 MB）');
  assert.equal(currentText({ install: { state: 'running' } }), '下载并安装依赖…');
  assert.match(friendlyError('install', { code: 'TRANSIENT.NETWORK', message: 'x' }).text, /网络.*重试/);
  assert.match(friendlyError('install', { code: 'PERMANENT.DISK_FULL', message: 'x' }).text, /磁盘空间不够/);
  assert.match(friendlyError('ocr', { code: 'PERMANENT.BAD_PACKAGE', message: 'DLL load failed' }).text, /没成功.*重试/, '原始报错不直接给人看');
  assert.equal(friendlyError('ocr', { code: 'PERMANENT.BAD_PACKAGE', message: 'DLL load failed' }).detail, 'DLL load failed', '原始报错留在详情里');
  assert.deepEqual(componentEvent('{"type":"progress","component":"ocr","phase":"下载模型","done":5,"total":10,"text":"a 1 MB"}'), { state: 'running', done: 5, total: 10, text: 'a 1 MB' });
  assert.equal(componentEvent('{"type":"result","ok":false,"code":"X","message":"m"}').state, 'failed');
  assert.equal(componentEvent('不是 JSON'), null);

  // ── uv pip install 的输出 → 进度（只进不退、千分制）──
  const meter = BI.uvInstallMeter();
  const seq = ['Resolved 59 packages in 1.2s', 'Downloading onnxruntime (12.0MiB)', 'Downloading opencv-python-headless (36.0MiB)',
    ' Downloaded onnxruntime', 'Downloading numpy (12.0MiB)', ' Downloaded opencv-python-headless', ' Downloaded numpy',
    'Prepared 59 packages in 30.1s', ' + numpy==2.3.1', 'Installed 59 packages in 3.0s'];
  const got = seq.map(l => meter(l));
  assert.equal(meter('warning: something'), null, '认不出的行不动进度');
  const dones = got.map(p => p.done);
  for (let i = 1; i < dones.length; i++) assert.ok(dones[i] >= dones[i - 1], '只进不退：' + dones.join(','));
  assert.equal(got[3].text, '下载好了 onnxruntime');
  assert.equal(got[1].text, '正在下载 onnxruntime（12.0 MB）');
  assert.ok(got[3].done > 50 && got[3].done < 850, '下完一个大文件在 5%–85% 之间');
  assert.equal(got[got.length - 1].done, 1000);
  assert.equal(got[0].total, BI.METER_TOTAL);
  assert.deepEqual(BI.BACKEND_EXTRAS, ['ocr', 'bilibili', 'docs']);

  // ── 窗口 + 流程（假 DOM / 假 obsidian；后端、spawnPy 都是假的）──
  const dom = makeDom();
  const notices = [];
  const obs = makeObsidian(dom.document, { notices });
  const calls = [];
  let finishBackend;
  const plugin = {
    app: {}, settings: { ocr: { mode: 'local' } }, running: null, runningProgress: '', homeState: null,
    saved: 0, saveSettings: async () => { plugin.saved++; },
    notify: (m, o) => { notices.push({ m, o }); },
    taskChanged: () => {}, busyText: () => '正在忙',
    copyText: t => { calls.push(['copy', t]); },
    backendMode: 'missing',
    currentBackend: () => ({ mode: plugin.backendMode }),
    onboardingUI: () => ({ renderFolder: c => c.createDiv({ cls: 'fake-folder-row', text: '收藏放在哪' }) }),
    homeUI: () => ({
      installBackend: ({ onProgress }) => new Promise(resolve => {
        plugin.homeState = { backendRun: { state: 'running' } };
        onProgress({ stage: 'uv', state: 'ok' });
        onProgress({ stage: 'python', state: 'running', text: '正在下载 Python 3.12.16（20.1 MB）' });
        finishBackend = res => { plugin.homeState.backendRun.state = 'done'; if (res.ok) plugin.backendMode = 'managed'; resolve(res); };
      }),
    }),
    spawnPy: async (args, { onLine }) => {
      const comp = args[args.indexOf('--component') + 1];
      calls.push(['install', comp]);
      onLine(JSON.stringify({ type: 'progress', component: comp, phase: '下载', done: 1, total: 2, text: comp + ' 一半' }));
      const ok = comp !== 'ocr';
      const res = { type: 'result', ok, code: ok ? '' : 'PERMANENT.BAD_PACKAGE', message: ok ? comp + ' 好了' : 'rapidocr 导入失败：DLL load failed' };
      onLine(JSON.stringify(res));
      return { code: ok ? 0 : 1, json: res };
    },
    loginAccount: async () => { calls.push(['login']); return { ok: true }; },
  };
  const ui = installerUI(obs, plugin);
  const body = dom.document.body;
  const q = s => body.querySelector(s);
  const btns = () => Array.from(body.querySelectorAll('.lb-installer-actions button')).map(b => b.textContent);

  let returned = false;
  const p = ui.openAndRun().then(r => { returned = true; return r; });
  await new Promise(r => setTimeout(r, 0));
  assert.ok(q('.modal.lb-installer-modal'), '开了安装窗口');
  assert.equal(q('.modal-title').textContent, '安装 Link Brain');
  assert.ok(q('.fake-folder-row'), '上面有「收藏放在哪」');
  assert.ok(ui.running());
  assert.match(q('.lb-installer-now').textContent, /^下载 Python：正在下载 Python 3\.12\.16/);
  assert.ok(/^\d+%$/.test(q('.lb-installer-pct').textContent));
  assert.deepEqual(btns(), ['放到后台装']);
  const loginBtn = Array.from(body.querySelectorAll('.lb-installer-pick button')).find(b => b.textContent === '扫码登录');
  assert.ok(loginBtn.disabled, '读取组件没装好不能扫码');

  // OCR 开关：关掉 → ocr.mode=off、selected 去掉 ocr；照样装
  const toggle = body.querySelector('.lb-installer-pick .checkbox-container');
  toggle.click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(plugin.settings.ocr.mode, 'off');
  assert.deepEqual(plugin.settings.setup.selected, ['core', 'reader']);
  toggle.click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(plugin.settings.ocr.mode, 'local');

  finishBackend({ ok: true, message: '后端装好了' });
  for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(calls.filter(c => c[0] === 'install').map(c => c[1]), ['reader', 'ocr'], '后端好了依次装读取组件、OCR');
  assert.equal(ui.state().state, 'done', 'OCR 没装好不算失败');
  assert.equal(q('.lb-installer-pct').textContent, '装好了');
  assert.match(q('.lb-installer-warn').textContent, /^认图片里的字没装好，不影响同步：/);
  assert.ok(!/DLL/.test(q('.lb-installer-warn').textContent), '原始报错不直接给人看');
  assert.deepEqual(btns(), ['重试没装好的', '开始同步']);
  assert.equal(ui.pct(), 100);
  const loginBtn2 = Array.from(body.querySelectorAll('.lb-installer-pick button')).find(b => b.textContent === '扫码登录');
  assert.ok(!loginBtn2.disabled, '装完能扫码');
  assert.equal(returned, false, '窗口还开着、没点「开始同步」：先不往下跑首次同步');
  Array.from(body.querySelectorAll('.lb-installer-actions button')).find(b => b.textContent === '开始同步').click();
  const res = await p;
  assert.equal(res.ok, true);
  assert.ok(!q('.modal.lb-installer-modal'), '点了就关窗');

  // ── 后端没装上：失败 + 一句人话 + 重试；不装组件 ──
  const plugin2 = { ...plugin, installerState: null, backendMode: 'missing', homeState: null };
  calls.length = 0;
  plugin2.currentBackend = () => ({ mode: 'missing' });
  plugin2.homeUI = () => ({ installBackend: async ({ onProgress }) => {
    onProgress({ stage: 'uv', state: 'ok' }); onProgress({ stage: 'python', state: 'failed', text: 'x' });
    return { ok: false, code: 'TRANSIENT.NETWORK', message: '装 Python 3.12 没成功：error sending request' };
  } });
  const ui2 = installerUI(obs, plugin2);
  const r2 = await ui2.openAndRun();
  assert.equal(r2.ok, false);
  assert.deepEqual(calls, [], '后端没装上不装组件');
  assert.match(q('.lb-installer-err').textContent, /^下载 Python时网络断了或太慢/);
  assert.deepEqual(btns(), ['重试', '复制详情']);
  Array.from(body.querySelectorAll('.lb-installer-actions button')).find(b => b.textContent === '复制详情').click();
  assert.deepEqual(calls[0], ['copy', '[TRANSIENT.NETWORK] 装 Python 3.12 没成功：error sending request']);
  body.querySelector('.modal-close-button').click();

  // ── 装后端期间各处的「没找到后端程序」改说「正在安装」（main.src.js backendMissingText）──
  const src = require('fs').readFileSync(path.join(DIR, 'main.src.js'), 'utf8');
  assert.match(src, /backendMissingText\(\) \{ return this\.backendInstalling\(\) \? BACKEND_INSTALLING_TEXT/);
  assert.ok(!/new Error\(backendMissingText\(/.test(src), 'pyChild / runPy 抛错都走 this.backendMissingText()');

  console.log('PASS installer 1103: one window (pick on top, one overall bar below), weighted monotonic %, uv output → progress, backend → reader → ocr, OCR failure = warning not failure, friendly errors + retry + copy detail, waits for 开始同步, installing text replaces 没找到后端程序');
})().catch(e => { console.error(e); process.exit(1); });

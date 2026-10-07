#!/usr/bin/env node
// node 测试一条命令跑完（CONVENTIONS §7.1）：`npm test` = 本文件。
//   - 跑 tests/test_*.cjs（node 单测，无浏览器），每个一个子进程，汇总 PASS / FAIL / SKIP；
//   - 页面测试（playwright）在同一次汇总里：装了 playwright 才跑，没装标 SKIP，不算失败；
//     读真 vault 数据的页面测试在 vault/_archive/catalog-data.json 不存在时（比如 worktree 里）也标 SKIP。
//   - 子进程退出码 77 = 用例自己声明跳过（stdout 最后一行写原因）。
// 任何一个 FAIL → 退出码 1。
//   node tests/run-node.cjs          全部（node 单测 + 页面测试）
//   node tests/run-node.cjs --ui     只跑页面测试（npm run test:ui）
//   node tests/run-node.cjs --unit   只跑 node 单测
//   node tests/run-node.cjs <名字…>  只跑名字里含这些片段的文件
// 批次 D 地基：页面测试 = 老的 UI_FILES 列表 + 自动发现 tests/ui/*.cjs（各线新的页面测试一律放 tests/ui/，不再改这个列表）。
// 没装 playwright 时页面测试全是 SKIP，汇总最后一行写明「UI 层没跑」——验收文件里必须照抄，不许当通过。
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const TESTS = __dirname;
const UI_FILES = ['catalog_ui_smoke.cjs', 'evidence_ui.cjs', 'media_controls_ui.cjs', 'ui_pages_qa.cjs'];
const UI_DIR = path.join(TESTS, 'ui');
const uiDiscovered = () => (fs.existsSync(UI_DIR) ? fs.readdirSync(UI_DIR).filter(f => f.endsWith('.cjs') && !f.startsWith('_')).sort().map(f => 'ui/' + f) : []);
const SKIP_CODE = 77;
const TIMEOUT_MS = 180000;

const argv = process.argv.slice(2);
const onlyUi = argv.includes('--ui');
const onlyUnit = argv.includes('--unit');
const filters = argv.filter(a => !a.startsWith('--'));

function hasPlaywright() {
  try { require.resolve('playwright', { paths: [ROOT, ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)] }); return true; }
  catch { return false; }
}

const unit = fs.readdirSync(TESTS).filter(f => /^test_.*\.cjs$/.test(f)).sort();
let plan = [];
if (!onlyUi) plan.push(...unit.map(f => ({ file: f, kind: 'node' })));
if (!onlyUnit) plan.push(...[...UI_FILES.filter(f => fs.existsSync(path.join(TESTS, f))), ...uiDiscovered()].map(f => ({ file: f, kind: 'ui' })));
if (filters.length) plan = plan.filter(t => filters.some(x => t.file.includes(x)));

const pw = hasPlaywright();
const results = [];
for (const t of plan) {
  const full = path.join(TESTS, t.file);
  if (t.kind === 'ui') {
    if (!pw) { results.push({ ...t, status: 'SKIP', noPw: true, note: '没装 playwright：UI 层没跑（npm i -D playwright 后再跑 npm run test:ui）' }); continue; }
    const src = fs.readFileSync(full, 'utf8');
    if (src.includes("vault/_archive/catalog-data.json") && !fs.existsSync(path.join(ROOT, 'vault', '_archive', 'catalog-data.json'))) {
      results.push({ ...t, status: 'SKIP', note: '要读 vault/_archive/catalog-data.json，这里没有 vault' }); continue;
    }
  }
  const started = Date.now();
  const r = spawnSync(process.execPath, [full], { cwd: ROOT, encoding: 'utf8', timeout: TIMEOUT_MS, env: { ...process.env } });
  const ms = Date.now() - started;
  const out = (r.stdout || '').trim(), err = (r.stderr || '').trim();
  let status = r.status === 0 ? 'PASS' : r.status === SKIP_CODE ? 'SKIP' : 'FAIL';
  if (r.error) status = 'FAIL';
  const note = status === 'FAIL'
    ? (r.error ? `${r.error.code || r.error.message}` : `exit=${r.status}`) + '\n' + (err || out).split('\n').slice(-12).join('\n')
    : (out.split('\n').filter(Boolean).pop() || '');
  results.push({ ...t, status, note, ms });
}

const pad = (s, n) => (s + ' '.repeat(n)).slice(0, n);
for (const r of results) {
  console.log(`${pad(r.status, 4)}  ${pad(r.file, 32)} ${r.ms != null ? pad(r.ms + 'ms', 8) : pad('', 8)} ${r.status === 'FAIL' ? '' : r.note}`);
  if (r.status === 'FAIL') console.log(r.note.split('\n').map(l => '      ' + l).join('\n'));
}
const count = s => results.filter(r => r.status === s).length;
console.log(`\n${count('PASS')} passed, ${count('FAIL')} failed, ${count('SKIP')} skipped (${results.length} files)`);
const uiPlanned = results.filter(r => r.kind === 'ui');
if (uiPlanned.length && uiPlanned.every(r => r.noPw)) console.log('UI 层没跑：没装 playwright（页面测试全部 SKIP，不算通过）');
else if (uiPlanned.length) console.log(`UI 层：${uiPlanned.filter(r => r.status === 'PASS').length} 过 / ${uiPlanned.filter(r => r.status === 'FAIL').length} 挂 / ${uiPlanned.filter(r => r.status === 'SKIP').length} 跳过`);
process.exit(count('FAIL') ? 1 : 0);

// 资产 JS 语法门：assets/*.js 是嵌进目录 MD 的 dataviewjs 片段（async 上下文），
// 一个语法错误会让整个目录页打不开（0924 真发生过：孤儿 catch）。
// 这里只做最轻的检查：包成 async 函数后 node --check。
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const assetsDir = path.join(__dirname, '..', 'link_brain', 'assets');
const files = fs.readdirSync(assetsDir).filter(f => f.endsWith('.js'));
if (!files.length) { console.error('FAIL: no js assets found'); process.exit(1); }

let failed = 0;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-syntax-'));
for (const name of files) {
  const src = fs.readFileSync(path.join(assetsDir, name), 'utf8');
  const wrapped = path.join(tmp, name);
  fs.writeFileSync(wrapped, 'async function __check(app, dv, input) {\n' + src + '\n}');
  const res = spawnSync(process.execPath, ['--check', wrapped], { encoding: 'utf8' });
  if (res.status !== 0) {
    failed++;
    console.error(`FAIL: ${name}\n${(res.stderr || '').trim()}`);
  }
}
fs.rmSync(tmp, { recursive: true, force: true });
if (failed) process.exit(1);
console.log(`PASS: ${files.length} asset scripts parse (${files.join(', ')})`);

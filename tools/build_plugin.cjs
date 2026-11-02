#!/usr/bin/env node
// 1102：插件 main.js 是构建产物（别手改）。源 = obsidian-plugins/link-brain-actions/main.src.js + 打包进来的模块。
//   node tools/build_plugin.cjs          构建，写 main.js
//   node tools/build_plugin.cjs --check  只检查 main.js 是不是最新的（CI 用；不是就失败，提示先跑 npm run build）
// 为什么要打包：手机上的 Obsidian 只加载插件目录里的 main.js（不能按路径 require 同目录的其他文件，也没有 Node 模块）。
// 手机上要用的只有 page-host.js（```lb-page 块的执行器），所以用 esbuild 把它（连同它 require 的东西）打成一个 IIFE，
// 全局名 LBPageHost，放在 main.src.js 前面；main.src.js 原样跟在后面（顶层名字不变，桌面端其余几个文件照旧在运行时按路径加载）。
// page-host.js 仍是源文件，留在插件目录里（单测直接 require 它）。
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DIR = path.join(ROOT, 'obsidian-plugins', 'link-brain-actions');
const SRC = path.join(DIR, 'main.src.js');
const OUT = path.join(DIR, 'main.js');
const BUNDLED = [{ file: 'page-host.js', globalName: 'LBPageHost' }];
// 原样当字符串打进去的文本（BRAT 只下载 main.js / manifest.json / styles.css，手机上要用的样式也得在 main.js 里）
const TEXTS = [{ file: 'note.css', globalName: 'LBNoteCss' }];

function build() {
  const esbuild = require('esbuild');
  const parts = ['// 构建产物，别手改：源在 main.src.js（+ 下面打包进来的 ' + [...BUNDLED, ...TEXTS].map(b => b.file).join('、') + '），改完跑 npm run build（tools/build_plugin.cjs）。'];
  for (const b of BUNDLED) {
    const r = esbuild.buildSync({
      entryPoints: [path.join(DIR, b.file)], bundle: true, write: false, format: 'iife', globalName: b.globalName,
      platform: 'neutral', target: 'es2020', charset: 'utf8', legalComments: 'none', logLevel: 'silent',
    });
    // esbuild 把源文件的 'use strict' 提到文件最前面——那样会让后面整个 main.src.js 也变成严格模式（行为可能变）。挪进 IIFE 里，只管打包的这一段
    let text = r.outputFiles[0].text.trimEnd();
    const strict = /^"use strict";\n/.test(text);
    if (strict) text = text.replace(/^"use strict";\n/, '').replace(`var ${b.globalName} = (() => {`, `var ${b.globalName} = (() => {\n  "use strict";`);
    parts.push(`// ── ${b.file}（esbuild 打包，全局名 ${b.globalName}）──`, text);
  }
  for (const t of TEXTS) parts.push(`// ── ${t.file}（原样字符串，全局名 ${t.globalName}）──`, `var ${t.globalName} = ${JSON.stringify(fs.readFileSync(path.join(DIR, t.file), 'utf8').replace(/\r\n/g, '\n'))};`);
  parts.push('// ── main.src.js ──', fs.readFileSync(SRC, 'utf8').replace(/\r\n/g, '\n').trimEnd(), '');
  return parts.join('\n');
}

if (require.main === module) {
  const want = build();
  if (process.argv.includes('--check')) {
    const have = fs.existsSync(OUT) ? fs.readFileSync(OUT, 'utf8').replace(/\r\n/g, '\n') : '';
    if (have !== want) { console.error('obsidian-plugins/link-brain-actions/main.js 不是最新的构建产物：先跑 npm run build 再提交'); process.exit(1); }
    console.log('main.js 是最新的构建产物');
  } else {
    fs.writeFileSync(OUT, want, 'utf8');
    console.log('已构建 ' + path.relative(ROOT, OUT));
  }
}
module.exports = { build, OUT, SRC };

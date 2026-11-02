#!/usr/bin/env node
// 1102：插件 main.js 是构建产物（别手改）。源 = obsidian-plugins/link-brain-actions/main.src.js + 它 require 的同目录文件。
//   node tools/build_plugin.cjs          构建，写 main.js
//   node tools/build_plugin.cjs --check  只检查 main.js 是不是最新的（CI 用；不是就失败，提示先跑 npm run build）
// 为什么整个打包：BRAT 只下载 main.js / manifest.json / styles.css，手机上的 Obsidian 也只加载 main.js。
// 所以 main.src.js 和它 require('./xxx.js') 的所有界面模块、page-host.js、note.css（text loader，变成字符串）都由 esbuild 打成一个 CJS 文件。
// esbuild 把每个打进来的模块包成「第一次 require 才执行」的函数，main.src.js 只在用到时调用，手机加载时不碰任何 Node 模块。
// obsidian、electron 和 Node 内置模块一律 external（运行时由 Obsidian / Electron 提供）。
'use strict';
const fs = require('fs');
const path = require('path');
const { builtinModules } = require('module');

const ROOT = path.resolve(__dirname, '..');
const DIR = path.join(ROOT, 'obsidian-plugins', 'link-brain-actions');
const SRC = path.join(DIR, 'main.src.js');
const OUT = path.join(DIR, 'main.js');
const EXTERNAL = ['obsidian', 'electron', '@electron/remote', ...builtinModules, ...builtinModules.map(m => 'node:' + m)];
const BANNER = '// 构建产物，别手改：源在 main.src.js 和它 require 的同目录文件（page-host.js、各 *-ui.js、note.css 等），改完跑 npm run build（tools/build_plugin.cjs）。';

function build() {
  const esbuild = require('esbuild');
  const r = esbuild.buildSync({
    entryPoints: [SRC], bundle: true, write: false, format: 'cjs', platform: 'node', target: 'es2020',
    external: EXTERNAL, loader: { '.css': 'text' }, charset: 'utf8', legalComments: 'none', logLevel: 'silent',
    banner: { js: BANNER }, absWorkingDir: ROOT,
  });
  return r.outputFiles[0].text.replace(/\r\n/g, '\n');
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

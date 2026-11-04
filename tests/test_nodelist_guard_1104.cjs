// 1104 作者（问收藏页「我保存的」来源点不出来）：querySelectorAll 在真浏览器里给的是 NodeList，没有 filter / map / find…；
// 测试用的假 DOM 给的是数组，所以单测一直过、真页面里一点就抛错。守卫：页面脚本和插件源码里不许直接在 querySelectorAll(...)
// 后面接数组方法（先 [...x] 或 Array.from(x)）。只扫源码，不扫测试。
'use strict';
const fs = require('fs'), path = require('path'), assert = require('assert/strict');
const ROOT = path.join(__dirname, '..');
const dirs = ['link_brain/assets', 'obsidian-plugins/link-brain-actions'];
const BAD = /querySelectorAll\([^()]*\)\s*\.\s*(filter|map|find|findIndex|some|every|reduce|includes|indexOf|slice|at)\s*\(/;
const hits = [];
for (const d of dirs) {
  for (const f of fs.readdirSync(path.join(ROOT, d))) {
    if (!f.endsWith('.js') || f === 'main.js') continue;   // main.js 是构建产物（源码已经扫了）
    fs.readFileSync(path.join(ROOT, d, f), 'utf8').split('\n').forEach((line, i) => {
      if (BAD.test(line)) hits.push(`${d}/${f}:${i + 1}: ${line.trim().slice(0, 120)}`);
    });
  }
}
assert.deepEqual(hits, [], 'querySelectorAll 后面直接接数组方法（真浏览器里 NodeList 没有这些方法）：\n' + hits.join('\n'));
console.log('PASS nodelist guard 1104: no array methods called directly on querySelectorAll() in page scripts / plugin sources');

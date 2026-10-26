// 1026 录屏 00:26：命令面板里日常入口好找，维护命令统一「维护：」开头（照样能调用）。
// 静态读插件源码里的 addCommand / commandTable 条目，不起 Obsidian。
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const DIR = path.join(__dirname, '..', 'obsidian-plugins', 'link-brain-actions');
const src = fs.readdirSync(DIR).filter(f => f.endsWith('.js')).map(f => fs.readFileSync(path.join(DIR, f), 'utf8')).join('\n');
const names = {};
for (const m of src.matchAll(/id:\s*['"]([\w-]+)['"],\s*name:\s*['"]([^'"]+)['"]/g)) names[m[1]] = m[2];

const DAILY = { 'open-catalog': '打开收藏目录', 'open-ask': '问收藏', 'search-collections': '搜索收藏',
  'sync-favorites': '立即同步收藏', 'import-links': '导入网址（可批量）', 'open-sync-log': '打开同步记录' };
for (const [id, name] of Object.entries(DAILY)) assert.strictEqual(names[id], name, `日常命令 ${id}`);

const MAINT = ['rebuild-catalog', 'fetch-attachments', 'ingest-inbox', 'ingest-clipboard', 'refine-images',
  'open-problems', 'index-draft', 'index-suggest'];
for (const id of MAINT) assert.ok((names[id] || '').startsWith('维护：'), `维护命令 ${id} 要「维护：」开头，现在是 ${names[id]}`);
for (const id of Object.keys(DAILY)) assert.ok(!names[id].startsWith('维护：'), `日常命令 ${id} 不该进维护`);
console.log('PASS commands_1026', Object.keys(names).length, '条命令');

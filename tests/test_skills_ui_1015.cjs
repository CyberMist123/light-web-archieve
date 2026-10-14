// 1015 设置页「技能」的纯函数（skills-ui.js）：SKILL.md frontmatter 解析、导入计划（只收文字文件、大小上限、嵌套只认最外层、一次多个技能）。
// 页面上的行为（列表 / 空状态 / 刷新 / ＋导入 / 隐藏列表）在 test_settings_layout.cjs 第 14 段。
'use strict';
const assert = require('assert/strict');
const { parseSkillMd, planImport, skillId } = require('../obsidian-plugins/link-brain-actions/skills-ui.js');

// frontmatter：单行 / 引号 / 折行（>）/ 保留换行（|）；BOM、CRLF 都认
let r = parseSkillMd('﻿---\r\nname: "recipe"\r\ndescription: 菜谱：列菜名\r\nlicense: MIT\r\n---\r\n正文');
assert.deepEqual([r.ok, r.name, r.description, r.body], [true, 'recipe', '菜谱：列菜名', '正文']);
r = parseSkillMd('---\nname: travel\ndescription: >\n  路线、时段\n  预算\nlwa:\n  renderer: board\n---\n');
assert.equal(r.description, '路线、时段 预算');
r = parseSkillMd("---\nname: 'x'\ndescription: |\n  a\n  b\n---\n");
assert.equal(r.description, 'a\nb');
assert.equal(parseSkillMd('没有 frontmatter').ok, false);
assert.match(parseSkillMd('---\ndescription: d\n---\n').error, /没有 name/);

// 名字 → 文件夹名
assert.equal(skillId('Trip Planner'), 'trip-planner');
assert.equal(skillId('  菜谱 / 做菜  '), '菜谱-做菜');
assert.equal(skillId('../../etc'), 'etc', '不许跳出 _skills');

// 导入计划
const f = (rel, size = 10) => ({ rel, size });
const text = { 'pack/a/SKILL.md': '---\nname: A\n---\n', 'pack/b/SKILL.md': '---\nname: b\n---\n', 'pack/a/inner/SKILL.md': '---\nname: inner\n---\n' };
const files = [f('pack/a/SKILL.md'), f('pack/a/inner/SKILL.md'), f('pack/a/notes.txt'), f('pack/a/big.md', 300 * 1024), f('pack/a/tool.exe'),
  f('pack/a/.git/config'), f('pack/b/SKILL.md'), f('pack/b/data.json'), f('pack/readme.md')];
const plan = planImport(files, x => text[x.rel] || '');
assert.deepEqual(plan.skills.map(s => s.id), ['a', 'b'], '一个文件夹里多个技能各算一个；技能里再套的 SKILL.md 不另算');
const a = plan.skills[0];
assert.deepEqual(a.files.map(x => x.rel).sort(), ['SKILL.md', 'inner/SKILL.md', 'notes.txt']);
assert.deepEqual(a.skipped.map(x => [x.rel, x.why]).sort(), [['.git/config', '隐藏文件'], ['big.md', '太大'], ['tool.exe', '不是文字文件']]);
assert.ok(a.files.every(x => x.from && x.from.rel), '拷的时候拿得到原文件对象');
assert.deepEqual(plan.skills[1].files.map(x => x.rel).sort(), ['SKILL.md', 'data.json']);
assert.match(planImport([f('x/readme.md')], () => '').errors[0], /没有 SKILL\.md/);
// 直接选中技能文件夹本身（SKILL.md 在最上层）
assert.deepEqual(planImport([f('SKILL.md'), f('ref.md')], () => '---\nname: solo\n---\n').skills.map(s => [s.id, s.files.length]), [['solo', 2]]);
// SKILL.md 坏了：报一句，不导入
assert.match(planImport([f('z/SKILL.md')], () => 'bad').errors[0], /^z：/);

console.log('PASS skills-ui (1015): SKILL.md frontmatter (plain / quoted / folded / literal / BOM / CRLF), folder ids stay inside _skills, import plan copies text files only (size cap, hidden files skipped), nested SKILL.md not split, multi-skill folders');

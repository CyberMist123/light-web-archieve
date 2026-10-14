// skills-ui.js — 1015 设置页「技能」页签（她：照 claudian 插件的技能页：说明行 + 刷新 / ＋，空状态一句，隐藏列表输入框）。
// 技能放在收藏库的 _skills/<id>/SKILL.md（Anthropic Agent Skills 规范：frontmatter name / description + 正文），问收藏按 description 选用。
// ＋ = 从本地文件夹导入：只拷文字文件（.md / .txt / .json / .yaml…），脚本、程序、图片一律不拷，也绝不执行（AGENTS.md 第 7 条：外来内容只当数据）。
// 隐藏列表存 settings.skills.hidden（id 数组），问收藏不自动选用这些；文件不删。
// render(container, tab) → stop()。纯函数 parseSkillMd / planImport / skillId 挂在导出上给 node 单测。
'use strict';

const SKILLS_DIR = '_skills';
const TEXT_EXT = new Set(['md', 'markdown', 'txt', 'json', 'yaml', 'yml', 'csv', 'tsv', 'toml', 'xml']);
const MAX_FILE = 256 * 1024;        // 单个文件最大 256 KB
const MAX_TOTAL = 2 * 1024 * 1024;  // 一个技能最多 2 MB
const MAX_FILES = 200;

// SKILL.md 的 frontmatter：只认 name / description（单行、引号、> | 折行都行）；别的键原样留在文件里，这里不管
function parseSkillMd(text) {
  const src = String(text || '').replace(/^﻿/, '');
  const m = src.match(/^---\r?\n([\s\S]*?)\r?\n---\s*(?:\r?\n|$)/);
  if (!m) return { ok: false, error: '开头没有 --- 包起来的 name / description' };
  const lines = m[1].split(/\r?\n/), out = {};
  for (let i = 0; i < lines.length; i++) {
    const kv = lines[i].match(/^(name|description)\s*:\s*(.*)$/);
    if (!kv) continue;
    let v = kv[2].trim();
    if (/^[>|][+-]?$/.test(v)) {   // 块标量：收后面缩进的行
      const parts = [];
      while (i + 1 < lines.length && (/^\s+\S/.test(lines[i + 1]) || lines[i + 1].trim() === '')) parts.push(lines[++i].trim());
      v = parts.filter(Boolean).join(v[0] === '|' ? '\n' : ' ');
    } else if (/^(['"]).*\1$/.test(v)) v = v.slice(1, -1);
    out[kv[1]] = v;
  }
  if (!out.name) return { ok: false, error: 'frontmatter 里没有 name' };
  return { ok: true, name: out.name, description: out.description || '', body: src.slice(m[0].length) };
}

// 名字 → 文件夹名：小写、只留字母数字汉字和 -，别的换成 -
function skillId(name) {
  return String(name || '').trim().toLowerCase().replace(/[^\p{L}\p{N}-]+/gu, '-').replace(/^-+|-+$/g, '').slice(0, 64);
}
const extOf = p => { const m = String(p).match(/\.([^./\\]+)$/); return m ? m[1].toLowerCase() : ''; };

// 选中的文件夹里的文件（[{rel:'top/sub/SKILL.md', size, text?}]）→ 要导入的技能：
// 每个含 SKILL.md 的目录算一个技能；只收它底下的文字文件（大小有上限），别的列进 skipped。
// 返回 {skills:[{id, name, description, dir, files:[{rel, from}], skipped:[{rel, why}]}], errors:[…]}
function planImport(files, readText) {
  const list = (files || []).map(f => ({ orig: f, size: f.size, rel:String(f.rel || '').replace(/\\/g, '/').replace(/^\/+/, '') }));
  const roots = list.filter(f => /(^|\/)SKILL\.md$/i.test(f.rel)).map(f => f.rel.replace(/(^|\/)SKILL\.md$/i, ''));
  // 嵌套的只认最外层（技能里再带的 SKILL.md 当普通文件）
  const tops = roots.filter(r => !roots.some(o => o !== r && (o === '' || r.startsWith(o + '/')))).sort();
  const skills = [], errors = [];
  if (!tops.length) return { skills, errors: ['这个文件夹里没有 SKILL.md：技能是一个文件夹，里面要有 SKILL.md'] };
  for (const dir of tops) {
    const prefix = dir ? dir + '/' : '';
    const mine = list.filter(f => f.rel.startsWith(prefix));
    const head = mine.find(f => f.rel.slice(prefix.length).toLowerCase() === 'skill.md');
    const parsed = parseSkillMd(readText(head.orig));
    if (!parsed.ok) { errors.push(`${dir || '所选文件夹'}：${parsed.error}`); continue; }
    const id = skillId(parsed.name) || skillId(dir.split('/').pop());
    if (!id) { errors.push(`${dir || '所选文件夹'}：名字用不了`); continue; }
    const keep = [], skipped = [];
    let total = 0;
    for (const f of mine) {
      const rel = f.rel.slice(prefix.length);
      if (rel.split('/').some(seg => seg.startsWith('.') || seg === '..')) { skipped.push({ rel, why: '隐藏文件' }); continue; }
      if (!TEXT_EXT.has(extOf(rel))) { skipped.push({ rel, why: '不是文字文件' }); continue; }
      if ((f.size || 0) > MAX_FILE) { skipped.push({ rel, why: '太大' }); continue; }
      if (total + (f.size || 0) > MAX_TOTAL || keep.length >= MAX_FILES) { skipped.push({ rel, why: '超过总量上限' }); continue; }
      total += f.size || 0;
      keep.push({ rel: rel.toLowerCase() === 'skill.md' ? 'SKILL.md' : rel, from: f.orig });
    }
    skills.push({ id, name: parsed.name, description: parsed.description, dir, files: keep, skipped });
  }
  return { skills, errors };
}

function factory(obsidian, plugin) {
  const { Setting } = obsidian;
  const adapter = () => plugin.app.vault.adapter;
  const root = () => plugin.lbPath(SKILLS_DIR);
  const hidden = () => { const s = plugin.settings; s.skills ||= { hidden: [] }; if (!Array.isArray(s.skills.hidden)) s.skills.hidden = []; return s.skills.hidden; };

  // 读 _skills：每个子文件夹一个技能；SKILL.md 坏了也列出来（标「读不懂」），别悄悄没了
  async function list() {
    const a = adapter();
    if (!(await a.exists(root()))) return [];
    const { folders = [] } = await a.list(root());
    const out = [];
    for (const folder of folders.slice().sort()) {
      const dir = String(folder).split('/').pop();
      const file = `${folder}/SKILL.md`;
      let info;
      try { info = parseSkillMd(await a.read(file)); } catch { info = { ok: false, error: '没有 SKILL.md' }; }
      out.push({ id: dir, file, ok: info.ok, name: info.ok ? info.name : dir, description: info.ok ? info.description : info.error });
    }
    return out;
  }

  // 选文件夹：<input type=file webkitdirectory>（Obsidian 桌面版 = Chromium），拿到的是文件内容，不碰别的路径
  function pickFolder() {
    return new Promise(resolve => {
      const input = document.createElement('input');
      input.type = 'file'; input.setAttribute('webkitdirectory', ''); input.multiple = true;
      input.onchange = () => resolve([...(input.files || [])]);
      input.click();
    });
  }

  async function importFiles(fileObjs) {
    const texts = new Map();
    const files = fileObjs.map(f => ({ rel: f.webkitRelativePath || f.name, size: f.size, raw: f }));
    // SKILL.md 要先读出来才知道名字
    for (const f of files) if (/(^|\/)SKILL\.md$/i.test(f.rel.replace(/\\/g, '/'))) texts.set(f, await f.raw.text());
    const plan = planImport(files, f => texts.get(f) || '');
    if (!plan.skills.length) { plugin.notify(plan.errors[0] || '没导入：没找到技能', { kind: 'error' }); return 0; }
    const a = adapter();
    let done = 0;
    for (const sk of plan.skills) {
      const dest = `${root()}/${sk.id}`;
      if (await a.exists(dest)) {
        const ok = await plugin.confirm?.({ title: `已经有「${sk.id}」这个技能了`, body: '换成新导入的这份？原来那份会被覆盖。', ok: '覆盖' });
        if (!ok) continue;
      }
      for (const f of sk.files) {
        const target = `${dest}/${f.rel}`;
        const parent = target.split('/').slice(0, -1).join('/');
        if (!(await a.exists(parent))) await a.mkdir(parent);
        await a.write(target, texts.get(f.from) ?? await f.from.raw.text());
      }
      done++;
      const skip = sk.skipped.length ? `；${sk.skipped.length} 个不是文字文件或太大，没拷` : '';
      plugin.notify(`已导入技能「${sk.name}」（${sk.files.length} 个文件${skip}）`);
    }
    for (const e of plan.errors) plugin.notify('有一个没导入：' + e, { kind: 'warn' });
    return done;
  }

  function render(container, tab) {
    let alive = true;
    const listBox = container.createDiv({ cls: 'lb-skill-list' });
    const paint = async () => {
      listBox.empty();
      const wait = listBox.createEl('p', { cls: 'setting-item-description lb-loading', text: '读技能列表' });
      let items;
      try { items = await list(); }
      catch (e) { if (!alive) return; wait.remove(); plugin.failBox?.(listBox, '技能列表', e, paint); return; }
      if (!alive) return;
      wait.remove();
      if (!items.length) {
        listBox.createDiv({ cls: 'lb-skill-empty', text: `还没有技能。点右上角 ＋ 从本地文件夹导入（文件夹里要有 SKILL.md），或把技能文件夹放进收藏库的 ${SKILLS_DIR} 里再点刷新。` });
        return;
      }
      const off = new Set(hidden());
      for (const sk of items) {
        const row = new Setting(listBox).setName(sk.name).setDesc(sk.description || '');
        row.settingEl.addClass('lb-skill-row');
        row.settingEl.setAttribute?.('data-skill', sk.id);
        if (!sk.ok) row.settingEl.addClass('is-broken');
        if (off.has(sk.id)) { row.settingEl.addClass('is-hidden-skill'); row.nameEl.createSpan({ cls: 'lb-skill-tag', text: '已隐藏' }); }
        row.addExtraButton(b => b.setIcon('file-text').setTooltip('打开 SKILL.md').onClick(() => plugin.app.workspace.openLinkText?.(sk.file, '', true)));
      }
    };
    container.paint = paint;
    paint();
    return () => { alive = false; };
  }

  // 技能卡片标题行右边的两个小图标：刷新 / ＋导入
  function headerButtons(row, repaint) {
    row.addExtraButton(b => b.setIcon('refresh-cw').setTooltip('刷新').onClick(() => repaint()));
    row.addExtraButton(b => b.setIcon('plus').setTooltip('从本地文件夹导入（只拷文字文件，不执行）').onClick(async () => {
      try { const files = await pickFolder(); if (files.length && await importFiles(files)) repaint(); }
      catch (e) { plugin.notify('没导入成：' + ((e && e.message) || e), { kind: 'error' }); }
    }));
  }

  return { list, render, headerButtons, importFiles, hidden };
}

module.exports = factory;
Object.assign(module.exports, { parseSkillMd, planImport, skillId, SKILLS_DIR, TEXT_EXT });

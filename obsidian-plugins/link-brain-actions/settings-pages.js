// settings-pages.js — 1016 设置页重做（她：用户懒得动、不想看的别放设置；要确认的、要知道的才放，小白看得懂，一次别让人选太多）。
// 四个页签：概览 · 同步 · AI · 更多。每页小标题 + 平铺的行，不套框；细项一律收进「更多」或页底的折叠里。
// 第一次用（库里还没有收藏、也没走完指引）概览页换成四步指引：放在哪 → 登录小红书 → AI 帮忙 → 开始同步。
// 这里只排版和接线：每一行的读写、保存失败拨回等仍用设置页（tab）上原有的方法。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Setting } = obsidian;

  const openUrl = url => {
    if (!/^https:\/\//.test(url || '')) return;
    try { require('electron').shell.openExternal(url); return; } catch {}
    try { window.open(url); } catch (e) { console.error('[lb] 网页没打开', e); }
  };

  // —— 小积木 ——
  function heading(parent, text, section) {
    const h = parent.createDiv({ cls: 'lb-sec-h', text });
    if (section) h.setAttribute('data-section', section);
    return h;
  }
  // 页底折叠：默认收着，标题一句话说里面是什么
  function fold(parent, title, section) {
    const d = parent.createEl('details', { cls: 'lb-fold' });
    if (section) d.setAttribute('data-section', section);
    d.createEl('summary', { text: title });
    return d.createDiv({ cls: 'lb-fold-body' });
  }
  function safe(tab, c, what, fn) { return tab.safe ? tab.safe(c, what, fn) : fn(); }

  // —— 提供商：从接口地址认是哪家（和 Python usage.provider_of 同一套）——
  const PROVIDER_NAME = { google: 'Gemini', aliyun: '阿里云百炼', deepseek: 'DeepSeek', openai: 'OpenAI' };
  const LINKS = {
    google: { key: 'https://aistudio.google.com/apikey', console: 'https://aistudio.google.com/', usage: 'https://aistudio.google.com/usage' },
    aliyun: { key: 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key', console: 'https://bailian.console.aliyun.com/cn-beijing/',
      recharge: 'https://usercenter2.aliyun.com/finance/fund-management/recharge' },
    deepseek: { key: 'https://platform.deepseek.com/api_keys', console: 'https://platform.deepseek.com/', recharge: 'https://platform.deepseek.com/top_up' },
    openai: { key: 'https://platform.openai.com/api-keys' },
  };
  function providerOf(endpoint, model) {
    const e = String(endpoint || '').toLowerCase(), m = String(model || '').toLowerCase();
    if (e.includes('deepseek') || (!e && m.startsWith('deepseek'))) return 'deepseek';
    if (e.includes('aliyuncs') || e.includes('dashscope') || (!e && m.startsWith('qwen'))) return 'aliyun';
    if (e.includes('openai.com')) return 'openai';
    if (e.includes('googleapis')) return 'google';
    if (!e) return '';
    return e.split('://').pop().split('/')[0];
  }
  // 每个功能现在用谁：[{id, label, cap, fallback?}]，按功能列；off / cli 的不算 API
  function featureUses(s) {
    const out = [];
    const add = (label, cfg, extra = {}) => {
      if (!cfg || cfg.mode === 'off' || cfg.mode === 'cli' || cfg.mode === 'capswriter') return;
      const id = providerOf(cfg.endpoint, cfg.model);
      if (id) out.push({ id, label, pool: cfg.keyPool || '', ...extra });
    };
    const text = s.textAI || {};
    add('问收藏', text);
    const sum = s.summaryAI || {};
    if (sum.mode === 'inherit' || !sum.mode) add('概要', { ...text, model: sum.model || text.model }); else add('概要', sum);
    if (sum.fallback) add('概要', sum.fallback, { backup: true });
    const vis = s.visionAI || {};
    add('识图', vis);
    if (vis.refine) add('精细识图', vis.refine, { backup: true });
    const emb = s.embedAI || (vis.mode === 'http' && !vis.keyPool ? { ...vis, endpoint: String(vis.endpoint || '').replace(/\/chat\/completions$/, '/embeddings') } : null);
    add('语义搜索', emb);
    if ((s.asrAI || {}).mode === 'http') add('视频转文字', s.asrAI);
    return out;
  }
  function providerRows(s) {
    const by = new Map();
    for (const u of featureUses(s)) {
      const row = by.get(u.id) || { id: u.id, main: [], backup: [], pool: '' };
      (u.backup ? row.backup : row.main).push(u.label);
      if (u.pool) row.pool = u.pool;
      by.set(u.id, row);
    }
    const order = ['google', 'deepseek', 'aliyun', 'openai'];
    return [...by.values()].sort((a, b) => ((order.indexOf(a.id) + 1) || 99) - ((order.indexOf(b.id) + 1) || 99))
      .map(r => ({ ...r, main: [...new Set(r.main)], backup: [...new Set(r.backup.filter(x => !r.main.includes(x)))] }));
  }

  // —— 「需要你留意」：只列真要人动手的；措辞说发生了什么、有没有影响、点哪里（她：别吓人、别 bossy）——
  const ACCOUNT_STEPS = new Set(['login', 'sync.favorites']);
  function attentionText(p) {
    const code = String(p.code || ''), sub = code.split('.').pop(), step = String(p.step || '');
    if (step.startsWith('ai.') || ['AUTH_FAILED', 'QUOTA_EXCEEDED'].includes(sub)) {
      const reason = String(p.reason || '');
      const m = reason.match(/^([^（(；;]+?)（([^，,）)]+)/);
      const who = (reason.includes('通义') || reason.includes('千问') || reason.includes('百炼')) ? '阿里云百炼'
        : reason.includes('DeepSeek') ? 'DeepSeek' : reason.includes('Gemini') || reason.includes('Google') ? 'Gemini' : (m ? m[2] : 'AI');
      const what = step === 'ai.vision' ? '识图' : step === 'ai.summary' ? '概要' : step === 'ai.embed' ? '语义搜索' : '';
      return { title: `${who}的 key 用不了`, desc: `可能欠费、过期或没开通服务${what ? `；影响${what}` : ''}。配了备用的会自动改用备用。`,
        provider: who === '阿里云百炼' ? 'aliyun' : who === 'DeepSeek' ? 'deepseek' : who === 'Gemini' ? 'google' : '' };
    }
    if (sub === 'NOTE_RESTRICTED') return { title: `有一篇要在网页上验证一下才能看`, desc: p.title ? `《${String(p.title).slice(0, 24)}》` : '', restricted: p.item_id };
    return { title: p.label || '有一件事没做成', desc: String(p.hover || p.reason || '').slice(0, 80) };
  }

  async function paintAttention(box, tab) {
    box.empty();
    let list = [];
    try {
      const cached = plugin.problemsCache && Date.now() - plugin.problemsCache.at < 60000 ? plugin.problemsCache : null;
      let problems = cached ? cached.problems : null;
      if (!problems) {
        const r = await plugin.runPy(['-m', 'link_brain', 'problems', 'list'], { label: '读取需要留意的事', fallback: '读不到', timeoutMs: 60000, quiet: true });
        problems = (r && r.json && Array.isArray(r.json.problems)) ? r.json.problems : [];
        plugin.problemsCache = { problems, summary: r?.json?.summary || null, at: Date.now() };
      }
      list = problems.filter(p => p.group === 'needs_you' && !p.hidden && !p.resolved_at && !ACCOUNT_STEPS.has(String(p.step || '')));
    } catch (e) { console.error('[lb] 需要留意的事没读到', e); return; }
    if (!list.length) return;   // 没事就整块不出现
    heading(box, '需要你留意', 'attention');
    const seen = new Set();
    for (const p of list.slice(0, 5)) {
      const t = attentionText(p);
      if (seen.has(t.title)) continue;
      seen.add(t.title);
      const row = new Setting(box).setName(t.title).setDesc(t.desc || '');
      row.settingEl.addClass('lb-attn-row');
      const links = LINKS[t.provider] || null;
      if (links?.console) tab.link(row, '去控制台看看', () => openUrl(links.console), '在浏览器打开它的控制台');
      if (t.provider) tab.link(row, '换一把 key', () => tab.showTab('ai'), '到 AI 页改 key');
      if (t.restricted && plugin.openNoteVerify) tab.link(row, '打开验证', () => plugin.openNoteVerify(t.restricted), '打开这篇，过一下验证');
    }
    if (list.length > 5) tab.link(new Setting(box).setName(`还有 ${list.length - 5} 件`), '查看', () => plugin.openProblems(), '打开完整记录');
  }

  // ———————————————————— 概览 ————————————————————
  function renderOverview(c, tab) {
    const att = c.createDiv({ cls: 'lb-attn' });
    paintAttention(att, tab).catch(console.error);
    heading(c, '小红书账号', 'status');
    safe(tab, c, '小红书账号', () => plugin.renderAccounts(c));
    heading(c, '收藏', 'collect-status');
    safe(tab, c, '收藏同步', () => tab.stops.push(plugin.renderSyncRow(c, { compact: true, onSchedule: () => tab.showTab('sync') })));
    const more = new Setting(c).setName('全部记录').setDesc('每次同步做了什么、哪里没做成、系统已经怎么处理的。');
    tab.link(more, '打开', () => plugin.openProblems(), '打开同步与问题记录');
  }

  // ———————————————————— 同步：三项，其余收进折叠 ————————————————————
  function renderSync(c, tab) {
    const s = plugin.settings, so = s.sync;
    heading(c, '什么时候同步', 'schedule');
    const row = new Setting(c).setName('自动同步').setDesc('电脑开着就会按时同步，Obsidian 不用开。');
    row.settingEl.addClass('lb-sched-row');
    safe(tab, c, '自动同步', () => { const ed = plugin.scheduleUI().render(c.createDiv({ cls: 'lb-sched-host' }), { primary: false }); tab.stops.push(() => ed.destroy()); });
    heading(c, '存什么', 'collect');
    tab.toggleRow(c, '存视频', '关掉只存封面和地址，省硬盘。', () => so.downloadVideo, v => { so.downloadVideo = v; });
    tab.fieldCommentFloors(c);
    const more = fold(c, '更多同步选项：放在哪、每次多少篇、补评论节奏', 'sync-more');
    tab.fieldCollectionFolder(more);
    tab.toggleRow(more, '存图片', '关掉只存文字和图片地址。', () => so.downloadImages, v => { so.downloadImages = v; });
    tab.toggleRow(more, '登录后马上同步', '第一次扫码登录成功后就开始。', () => so.autoAfterLogin, v => { so.autoAfterLogin = v; });
    tab.fieldPerRunLimit(more);
    tab.fieldDailyLimit(more);
    tab.fieldFillPace(more);
  }

  // ———————————————————— AI：API / 命令行，每家一行写它管哪些功能 ————————————————————
  function renderAI(c, tab) {
    const s = plugin.settings;
    heading(c, 'API', 'ai-api');
    const rows = providerRows(s);
    if (!rows.length) new Setting(c).setName('还没接 AI').setDesc('不接也能存、能按关键词搜。想要概要、识图、按意思找，在下面「详细设置」里填一家的 key。');
    for (const r of rows) {
      const name = PROVIDER_NAME[r.id] || r.id;
      const row = new Setting(c).setName(name + (r.pool ? '（几把 key 轮流用）' : ''));
      row.settingEl.addClass('lb-provider-row'); row.settingEl.setAttribute('data-provider', r.id);
      const parts = [];
      if (r.main.length) parts.push(r.main.join(' · '));
      if (r.backup.length) parts.push('备用：' + r.backup.join(' · '));
      row.setDesc(parts.join('　'));
      const l = LINKS[r.id] || {};
      if (l.console) tab.link(row, '控制台', () => openUrl(l.console), `在浏览器打开 ${name} 的控制台`);
      if (l.recharge) tab.link(row, '充值', () => openUrl(l.recharge), `在浏览器打开 ${name} 的充值页`);
      if (l.key) tab.link(row, '拿 key', () => openUrl(l.key), `在浏览器打开 ${name} 拿 key 的页面`);
    }
    const cli = (s.models || []).filter(m => m.mode === 'cli');
    if (cli.length) {
      heading(c, '命令行', 'ai-cli');
      for (const m of cli) {
        const active = s.activeModel === m.name;
        const row = new Setting(c).setName(m.name || '命令行').setDesc((active ? '问收藏正在用 · ' : '问收藏可选 · ') + '用本机已登录的账号，不要 key，每问约 20 秒');
        if (!active) tab.link(row, '设为问收藏', async () => { s.activeModel = m.name; await tab.save(); plugin.app.workspace.trigger?.('link-brain:models-changed'); tab.redraw(); }, '问收藏改用它');
      }
    }
    // 花费明细（各家余额、本月、各功能表）收起来：要看再点开，平时不占地方
    const usage = fold(c, '花了多少：各家余额、这个月花费、各功能明细', 'ai-usage');
    safe(tab, usage, '用量', () => tab.renderUsage(usage.createDiv({ cls: 'lb-usage-host' })));
    const more = fold(c, '详细设置：接口地址、key、模型名、认字、语音、提示词', 'ai-more');
    safe(tab, more, 'AI 功能', () => tab.renderAIFeatures(more));
    safe(tab, more, '问收藏模型', () => tab.renderChatModels(more));
    safe(tab, more, '识图 · 认字 · 语音', () => tab.renderMediaAI(more));
    safe(tab, more, '提示词', () => tab.renderPrompts(more));
  }

  // ———————————————————— 更多：接其他 AI · 目录与批注 · 技能 · 附件 · 高级 ————————————————————
  function renderMore(c, tab) {
    const s = plugin.settings;
    // 接其他 AI 内容多（一键接上、远程访问、教程、开放哪些文件夹），收成一行，用到再点开
    const conn = fold(c, '接其他 AI：让 Claude、ChatGPT 读你的收藏', 'connect');
    safe(tab, conn, '连接其他 AI', () => tab.stops.push(plugin.remoteUI?.renderConnect(conn, () => tab.display(), tab)));
    heading(c, '目录与批注', 'catalog');
    new Setting(c).setName('批注署名').setDesc('你写的批注署这个名字；空着不署名。')
      .addText(t => t.setPlaceholder('我').setValue(s.nickname || '').onChange(async v => { s.nickname = v.trim(); await tab.save(); }));
    new Setting(c).setName('留言对象').setDesc('以「@名字」开头的批注标成留言给它；空着不启用。')
      .addText(t => t.setPlaceholder('不启用').setValue(s.annotateMention || '').onChange(async v => { s.annotateMention = v.trim(); await tab.save(); }));
    tab.fieldCategories(c);
    const skills = fold(c, '技能：问收藏时按问题选用的写法（菜谱、攻略…）', 'skills');
    safe(tab, skills, '技能', () => tab.renderSkillsTab(skills));
    const att = fold(c, '附件：手动下载、还没下到的', 'attach');
    tab.fieldDownloadFolder(att);
    tab.numberField(att, '等下载最多几分钟', '手动下载附件时，在下载文件夹里等文件出现多久。',
      { get: () => s.downloads.waitMinutes, set: v => s.downloads.waitMinutes = v, def: 5, unit: '分钟' });
    tab.link(new Setting(att).setName('还没下到的附件'), '查看', async () => {
      try {
        const data = plugin.catalogCache?.data || JSON.parse(await plugin.app.vault.adapter.read(plugin.lbPath('_archive/catalog-data.json')));
        plugin.openAttachments(data.items.filter(it => it.attachment === '待补'));
      } catch (e) { plugin.notify('这一块暂时读不到：' + e.message, { kind: 'error' }); }
    }, '列出还没下到附件的笔记');
    const adv = fold(c, '高级：一键装好、后端程序、检查这台电脑、重走第一次的指引', 'developer');
    const home = plugin.homeUI ? plugin.homeUI() : null;
    if (home) safe(tab, adv, '一键装好', () => tab.stops.push(home.renderRun(adv, tab)));
    safe(tab, adv, '高级', () => tab.renderDeveloperCard(adv));
    tab.link(new Setting(adv).setName('第一次的指引'), '重走一遍', () => { s.onboarding = { ...(s.onboarding || {}), force: true, step: 0 }; tab.save().then(() => tab.showTab('overview')); }, '在概览页重新走四步指引');
  }

  // ———————————————————— 第一次：四步指引（照 MAA 的设置指引：右边步骤线，左边一次一件事）————————————————————
  const STEPS = [['folder', '放在哪'], ['login', '登录小红书'], ['ai', 'AI 帮忙'], ['start', '开始同步']];
  // 指引自己记走没走完（guideDone）：onboarding.done 是启动时「按轻量版自动跑一次」记的，和指引无关
  async function needsGuide() {
    const ob = plugin.settings.onboarding || {};
    if (ob.force) return true;
    if (ob.guideDone) return false;
    try { return !(await plugin.app.vault.adapter.exists(plugin.lbPath('_archive/catalog-data.json'))); } catch { return false; }
  }

  function renderGuide(c, tab) {
    const s = plugin.settings;
    s.onboarding = s.onboarding || {};
    let step = Math.min(Math.max(+s.onboarding.step || 0, 0), STEPS.length - 1);
    const wrap = c.createDiv({ cls: 'lb-guide' });
    const left = wrap.createDiv({ cls: 'lb-guide-main' });
    const right = wrap.createDiv({ cls: 'lb-guide-steps' });
    const finish = async () => { s.onboarding = { ...s.onboarding, guideDone: true, force: false, step: 0 }; await tab.save(); tab.showTab('overview'); };
    const go = async n => { step = n; s.onboarding.step = n; await tab.save(); paint(); };
    const paint = () => {
      right.empty();
      STEPS.forEach(([, label], i) => {
        if (i) right.createDiv({ cls: 'lb-guide-line' + (i <= step ? ' is-done' : '') });
        const st = right.createDiv({ cls: 'lb-guide-step' + (i < step ? ' is-done' : i === step ? ' is-on' : '') });
        st.createSpan({ cls: 'lb-guide-dot', text: i < step ? '✓' : String(i + 1) });
        st.createSpan({ text: label });
      });
      left.empty();
      const [id] = STEPS[step];
      const title = t => left.createDiv({ cls: 'lb-guide-title', text: t });
      const hint = t => left.createEl('p', { cls: 'lb-guide-hint', text: t });
      if (id === 'folder') {
        title('收藏放在哪个文件夹？');
        hint('一般不用改，直接下一步。');
        tab.fieldCollectionFolder(left);
      } else if (id === 'login') {
        title('登录你收藏用的小红书号');
        hint('用手机扫码。登录状态只存在这台电脑上。');
        safe(tab, left, '小红书账号', () => plugin.renderAccounts(left));
      } else if (id === 'ai') {
        title('要不要 AI 帮你整理？');
        hint('不用也能存、能按关键词搜。用的话会帮你写概要、认图里的字、按意思找收藏。');
        const pick = (label, desc, fn) => { const r = new Setting(left).setName(label).setDesc(desc); r.settingEl.addClass('lb-guide-choice'); r.addButton(b => b.setButtonText('选这个').onClick(fn)); return r; };
        pick('用免费的 Gemini', '要一把 Google 的 key，每天额度够日常用。', () => { openUrl(LINKS.google.key); tab.showTab('ai'); });
        pick('用付费的（DeepSeek / 阿里云）', '按用量付费，日常每月大约几块钱。', () => tab.showTab('ai'));
        pick('先不用', '以后在「AI」页随时打开。', () => go(step + 1));
      } else {
        title('开始同步');
        hint('第一次会把以前的收藏分几天慢慢补完，像人一样读，不伤号。之后每天自动同步。');
        const home = plugin.homeUI ? plugin.homeUI() : null;   // 先把这台电脑缺的装好（读取组件、认字模型…），装好了这一块只剩一句「都装好了」
        if (home) safe(tab, left, '一键装好', () => tab.stops.push(home.renderRun(left, tab)));
        new Setting(left).setName('现在开始').addButton(b => b.setCta().setButtonText('开始同步').onClick(async () => { plugin.syncNow?.(); await finish(); }));
      }
      const nav = left.createDiv({ cls: 'lb-guide-nav' });
      const prev = nav.createEl('button', { text: '上一步' }); prev.disabled = step === 0; prev.onclick = () => go(step - 1);
      const skip = nav.createEl('button', { cls: 'lb-link', text: '跳过指引' }); skip.onclick = finish;
      if (step < STEPS.length - 1) { const next = nav.createEl('button', { cls: 'mod-cta', text: '下一步' }); next.onclick = () => go(step + 1); }
    };
    paint();
  }

  return { renderOverview, renderSync, renderAI, renderMore, renderGuide, needsGuide, providerRows, featureUses, attentionText, providerOf };
};

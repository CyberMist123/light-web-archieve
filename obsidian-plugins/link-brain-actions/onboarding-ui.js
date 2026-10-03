// onboarding-ui.js — 第 5 批 B2（RELEASE-BAR P8）：首次打开的引导 + 启动时的「缺什么」提示。
// main.js 只接几行：onboardingUI() 按需 require 本文件；openOnboarding() / startupChecks() / renderSetupHints(c) 转到这里。
// 引导四步：① 收藏存放位置 ② 读取组件 ③ 扫码登录 ④ 可选填 AI key。每步都能跳过，状态如实（CONVENTIONS §1）：
// 做成了说做了什么，没做成说原因，跳过就写「已跳过」，没做就空着。关掉窗口 = 引导结束（命令面板「打开首次引导」可再来）。
// 什么时候自己弹：这个库第一次启用本插件、后端程序找得到、收藏库里还没有 _archive（还没准备好）、没走过引导。作者本机（已有收藏库）不弹。
// 本模块不起进程：一律经 plugin.runPy（CONVENTIONS §1.4）。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Modal, Notice, Setting } = obsidian;
  const BACKEND_INSTALL = 'uv tool install link-brain';

  const copy = (text) => plugin.copyText(text);

  // 收藏存放位置：本库里的相对文件夹。拒绝绝对路径、盘符、..（收藏库要在 Obsidian 能看到的地方）。返回 {ok, folder|error}
  function normalizeFolder(text) {
    const raw = String(text || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    if (!raw) return { ok: true, folder: '' };
    if (/^[a-zA-Z]:/.test(raw) || raw.includes(':')) return { ok: false, error: '只填本库里的文件夹名（如「收藏」），不填盘符或完整路径' };
    const parts = raw.split('/').map(s => s.trim());
    if (parts.some(s => !s || s === '.' || s === '..' || s.startsWith('.'))) return { ok: false, error: '文件夹名不能是空的，也不能以「.」开头或用「..」' };
    return { ok: true, folder: parts.join('/') };
  }

  // 要不要自己弹引导：走过了 / 后端没找到 / 收藏库已有 _archive（作者本机、老用户）→ 不弹
  async function needsOnboarding() {
    if (plugin.settings?.onboarding?.done) return false;
    if (plugin.currentBackend().mode === 'missing') return false;
    try { if (await plugin.app.vault.adapter.exists(plugin.lbPath('_archive'))) return false; } catch { return false; }
    return true;
  }

  function aiConfigured(s) {
    const t = (s && s.textAI) || {};
    if (t.mode === 'cli') return !!t.command;
    if (t.mode === 'http') return !!(t.endpoint && (t.apiKey || t.keyFile));
    return false;
  }

  class OnboardingModal extends Modal {
    constructor() { super(plugin.app); this.result = {}; }

    // 一步 = 标题 + 说明 + 内容区 + 状态行；setState(kind, text)：done / skipped / failed / ''（没做）
    step(c, title, desc) {
      const box = c.createDiv({ cls: 'lb-onb-step' });
      box.createEl('h3', { text: title });
      if (desc) box.createEl('p', { cls: 'setting-item-description', text: desc });
      const body = box.createDiv({ cls: 'lb-onb-body' });
      const state = box.createDiv({ cls: 'lb-onb-state' });
      const setState = (kind, text = '') => {
        state.className = 'lb-onb-state' + (kind ? ' is-' + kind : '');
        state.setText(kind === 'done' ? '✓ ' + text : kind === 'skipped' ? '已跳过' + (text ? '：' + text : '') : kind === 'failed' ? '没做成：' + text : text);
      };
      return { box, body, setState };
    }

    onOpen() {
      const c = this.contentEl; c.empty();
      this.modalEl?.addClass?.('lb-onboarding');
      c.createEl('h2', { text: '开始使用 Link Brain' });
      c.createEl('p', { cls: 'setting-item-description', text: '四步，每步都能跳过。之后想再来：命令面板「打开首次引导」。' });
      this.drawFolder(c);
      this.drawReader(c);
      this.drawLogin(c);
      this.drawAI(c);
      new Setting(c).addButton(b => b.setButtonText('完成').setCta().onClick(() => this.close()));
    }

    // ① 收藏存放位置
    drawFolder(c) {
      const st = this.step(c, '① 收藏存放位置', '默认就放在这个库里。想放进单独的文件夹就填文件夹名（在本库里，没有会自动建）。程序装在哪和收藏放在哪互不相关。');
      let value = plugin.settings.collectionFolder || '';
      const base = plugin.app.vault.adapter.getBasePath();
      const preview = st.body.createEl('p', { cls: 'setting-item-description' });
      const paint = () => { const n = normalizeFolder(value); preview.setText(n.ok ? '收藏会放在：' + (n.folder ? base.replace(/[\\/]+$/, '') + '/' + n.folder : base) : n.error); };
      new Setting(st.body).setName('文件夹').setDesc('留空 = 库根目录')
        .addText(t => t.setPlaceholder('留空，或如：收藏').setValue(value).onChange(v => { value = v; paint(); }))
        .addButton(b => b.setButtonText('保存').setCta().onClick(async () => {
          b.setDisabled(true);
          try { st.setState('done', await this.saveFolder(value)); this.result.folder = 'done'; }
          catch (e) { st.setState('failed', e.message); this.result.folder = 'failed'; }
          finally { b.setDisabled(false); }
        }))
        .addButton(b => b.setButtonText('跳过').onClick(() => { st.setState('skipped', '收藏放在库根目录'); this.result.folder = 'skipped'; }));
      paint();
      if (plugin.settings.collectionFolder) st.setState('done', '之前选过：' + plugin.vaultDir);
    }

    async saveFolder(value) {
      const n = normalizeFolder(value);
      if (!n.ok) throw new Error(n.error);
      const a = plugin.app.vault.adapter;
      if (n.folder && !(await a.exists(n.folder))) await a.mkdir(n.folder);
      plugin.settings.collectionFolder = n.folder;
      await plugin.saveSettings();
      await plugin.locateCollection();
      let extra = '';
      // 命令行 / 外接 MCP / 计划任务不经插件起：后端命令模式下顺手写进 ~/.link-brain/config.json 的 vault（仓库模式不碰）
      if (plugin.currentBackend().mode === 'command') {
        try { plugin.writeUserConfig({ vault: plugin.vaultDir }); extra = '（命令行也用这个位置）'; }
        catch (e) { extra = '（插件里已生效；命令行用的 ~/.link-brain/config.json 没写上：' + e.message + '）'; }
      }
      return '收藏放在 ' + plugin.vaultDir + extra;
    }

    // ② 读取组件：reader status → 已就位 / 下载 / 发布地址还没配（测试版：手动放置）
    drawReader(c) {
      const st = this.step(c, '② 读取组件', '读收藏、评论、附件都要它（一个小程序，带自己的浏览器）。');
      const draw = async () => {
        st.body.empty(); st.setState('', '检查中…');
        let r;
        try { r = (await plugin.runPy(['-m', 'link_brain', 'reader', 'status'], { label: '检查读取组件', fallback: '读不到读取组件状态', timeoutMs: 60000 })).json; }
        catch (e) { st.setState('failed', e.message); this.result.reader = 'failed'; return; }
        if (!r) { st.setState('failed', '后台没返回读取组件状态'); this.result.reader = 'failed'; return; }
        if (r.reader) { st.setState('done', '已就位：' + r.reader); this.result.reader = 'done'; return; }
        st.setState('', '还没装');
        const row = new Setting(st.body).setName('下载读取组件');
        if (r.release_configured === true) {
          row.setDesc('从发布页下载并校验后装进 ' + (r.bin_dir || '~/.link-brain/bin'));
          row.addButton(b => b.setButtonText('下载读取组件').setCta().onClick(async () => {
            b.setDisabled(true); st.setState('', '正在下载…（几十 MB，几分钟）');
            try {
              const { json } = await plugin.runPy(['-m', 'link_brain', 'reader', 'install'], { label: '下载读取组件', fallback: '下载失败', timeoutMs: 15 * 60000, okCodes: [0, 1] });
              if (json && json.ok) { st.setState('done', json.message || '读取组件已装好'); this.result.reader = 'done'; this.refreshAccounts?.(); }
              else { st.setState('failed', (json && json.message) || '后台没返回结果'); this.result.reader = 'failed'; }
            } catch (e) { st.setState('failed', e.message); this.result.reader = 'failed'; }
            finally { b.setDisabled(false); }
          }));
        } else {
          // 发布地址常量还空着（测试版）：不编地址，给手动放置说明
          row.setDesc('测试版还没有发布下载地址。手动放置：把编译好的 link-brain-reader（Windows 上是 link-brain-reader.exe）和 relatedfile 放进 '
            + (r.bin_dir || '~/.link-brain/bin') + '，再点「重新检查」。编译方法见仓库 reader/README.md。');
          row.addButton(b => { b.setButtonText('发布地址还没配置（测试版）').setDisabled(true); });
        }
        new Setting(st.body)
          .addButton(b => b.setButtonText('重新检查').onClick(draw))
          .addButton(b => b.setButtonText('跳过').onClick(() => { st.setState('skipped', '以后在这里或命令面板再装'); this.result.reader = 'skipped'; }));
      };
      this.drawReaderNow = draw;
      draw();
    }

    // ③ 扫码登录：直接用设置页的账号卡片（同一个扫码流程）
    drawLogin(c) {
      const st = this.step(c, '③ 扫码登录', '用手机小红书 App 扫一次码。一个号覆盖收藏、评论、附件；登录过期才需要再扫。');
      try { this.refreshAccounts = plugin.renderAccounts(st.body); }
      catch (e) { st.setState('failed', e.message); }
      new Setting(st.body).addButton(b => b.setButtonText('跳过').onClick(() => { st.setState('skipped', '以后在设置页「账号」里扫码'); this.result.login = 'skipped'; }));
    }

    // ④ 可选：AI key（跳到设置页 AI 那块）
    drawAI(c) {
      const st = this.step(c, '④ AI（可选）', '问收藏要一个文本 AI：填接口地址 + Key，或用本机已登录的命令行。不填也能归档、浏览、搜索。');
      if (aiConfigured(plugin.settings)) st.setState('done', '已配置文本 AI');
      new Setting(st.body)
        .addButton(b => b.setButtonText('去填 AI 设置').onClick(() => { this.result.ai = 'opened'; this.close(); plugin.openSettingsTab(); }))
        .addButton(b => b.setButtonText('跳过').onClick(() => { st.setState('skipped'); this.result.ai = 'skipped'; }));
    }

    onClose() {
      this.contentEl.empty();
      plugin.settings.onboarding = { done: true, at: new Date().toISOString(), steps: { ...this.result } };
      Promise.resolve(plugin.saveSettings()).catch(e => console.error('[lb] 引导状态没存上', e));
    }
  }

  // 带一个按钮的提示（Obsidian Notice 支持 DocumentFragment；没 document 的环境退回纯文字）
  function noticeWithButton(text, label, onClick, timeout = 0) {
    if (typeof document === 'undefined' || !document.createDocumentFragment) return new Notice(text, timeout || 15000);
    const frag = document.createDocumentFragment();
    const p = document.createElement('div'); p.textContent = text; frag.appendChild(p);
    const b = document.createElement('button'); b.textContent = label; b.style.marginTop = '6px';
    b.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
    frag.appendChild(b);
    return new Notice(frag, timeout);
  }

  // 一块醒目的提示：文字 + 按钮（设置页顶部、目录页顶部共用）
  function hintBox(container, text, buttons, cls = '') {
    const box = container.createDiv({ cls: 'lb-setup-hint ' + cls });
    box.createEl('p', { text });
    const row = box.createDiv({ cls: 'lb-setup-hint-actions' });
    for (const [label, fn] of buttons) { const b = row.createEl('button', { text: label }); b.onclick = fn; }
    return box;
  }

  function dataviewButtons(state) {
    return [[state === 'nojs' ? '打开 Dataview 设置' : '打开第三方插件', () => plugin.openPluginSettings(state === 'nojs' ? 'dataview' : 'community-plugins')]];
  }

  return {
    OnboardingModal,
    open() { const m = new OnboardingModal(); m.open(); return m; },
    needsOnboarding,
    // 启动时（窗口开好后）：Dataview 缺了 / 后端程序找不到 → 提示一次（带按钮）；还没准备好的新库 → 弹引导
    async startup() {
      const dv = plugin.dataviewState();
      if (dv && dv !== 'ok') noticeWithButton(plugin.dataviewHint(dv), dataviewButtons(dv)[0][0], dataviewButtons(dv)[0][1], 20000);
      const b = plugin.currentBackend();
      if (b.mode === 'missing') { noticeWithButton(plugin.backendMissingText(), '复制安装命令', () => copy(BACKEND_INSTALL), 30000); return 'backend-missing'; }
      if (await needsOnboarding()) { this.open(); return 'onboarding'; }
      return 'ready';
    },
    // 设置页最上面：缺后端 / 缺 Dataview / 旧图片导航插件还开着 → 各一块提示（都正常就什么也不加）
    renderSetupHints(c) {
      const shown = [];
      const b = plugin.currentBackend();
      if (b.mode === 'missing') { hintBox(c, plugin.backendMissingText(), [['复制安装命令', () => copy(BACKEND_INSTALL)]], 'is-backend'); shown.push('backend'); }
      const dv = plugin.dataviewState();
      if (dv && dv !== 'ok') { hintBox(c, plugin.dataviewHint(dv), dataviewButtons(dv), 'is-dataview'); shown.push('dataview'); }
      if (plugin.mediaNav?.skipped) {
        hintBox(c, '图片导航已经并进本插件。旧插件「Link Brain Native Media Nav」还开着，现在由它负责；在「第三方插件」里停用它并重启 Obsidian，就由本插件接管（两个同时开会重复）。',
          [['打开第三方插件', () => plugin.openPluginSettings('community-plugins')]], 'is-medianav');
        shown.push('medianav');
      }
      return shown;
    },
    // 目录页 / 问收藏页（lb-page）打开时：Dataview 不可用就在页面顶部放一条提示（页面本身靠它渲染，缺了只剩代码块）
    dataviewBanner(view) {
      const host = view && (view.contentEl || view.containerEl?.querySelector?.('.view-content'));
      if (!host) return null;
      host.querySelector?.('.lb-dataview-hint')?.remove();
      const dv = plugin.dataviewState();
      if (!dv || dv === 'ok') return null;
      const box = hintBox(host, plugin.dataviewHint(dv), dataviewButtons(dv), 'lb-dataview-hint');
      if (host.firstChild && host.firstChild !== box && host.insertBefore) host.insertBefore(box, host.firstChild);
      return box;
    },
    _internals: { normalizeFolder, aiConfigured, noticeWithButton },
  };
};

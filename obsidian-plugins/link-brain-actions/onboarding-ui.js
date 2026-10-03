// onboarding-ui.js — 第 5 批 B2（RELEASE-BAR P8）：首次打开的引导 + 启动时的「缺什么」提示。
// main.js 只接几行：onboardingUI() 按需 require 本文件；openOnboarding() / startupChecks() / renderSetupHints(c) 转到这里。
// 第 7 批：首次引导不再是弹窗——直接打开设置页「开始」分页（setup-ui.js：选功能 / 检查安装 / 扫码 / 同步 / AI）。
// 原第 ① 步「收藏存放位置」搬成一行设置 renderFolder（「开始」第 ① 步和「高级」分页共用）；读取组件归第 ② 步 setup install。
// 什么时候自己打开：这个库第一次启用本插件、后端程序找得到、收藏库里还没有 _archive（还没准备好）、没走过引导。作者本机（已有收藏库）不开。
// 本模块不起进程：一律经 plugin.runPy（CONVENTIONS §1.4）。
'use strict';
module.exports = function (obsidian, plugin) {
  const { Notice, Setting } = obsidian;
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

  // 收藏存放位置：本库里的文件夹。改了存插件设置；后端命令模式下顺手写 ~/.link-brain/config.json 的 vault（仓库模式不碰）。
  async function saveFolder(value) {
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

  // 第 7 批：原首次引导第 ① 步，搬成一行设置（「开始」第 ① 步和「高级」分页共用）：文件夹 + 保存 + 一行如实状态
  function renderFolder(container) {
    let value = plugin.settings.collectionFolder || '';
    const base = String(plugin.app.vault.adapter.getBasePath() || '');
    const row = new Setting(container).setName('收藏存放位置')
      .setDesc('默认就放在这个库里；想放进单独的文件夹就填文件夹名（在本库里，没有会自动建）。已有的收藏不会自动搬。');
    row.settingEl.addClass('lb-folder-row');
    const state = row.descEl.createDiv({ cls: 'lb-onb-state' });
    const setState = (kind, text) => { state.className = 'lb-onb-state' + (kind ? ' is-' + kind : ''); state.setText(text); };
    const preview = () => { const n = normalizeFolder(value); n.ok ? setState('', '收藏会放在：' + (n.folder ? base.replace(/[\\/]+$/, '') + '/' + n.folder : base)) : setState('failed', n.error); };
    row.addText(t => t.setPlaceholder('留空 = 库根目录，或如：收藏').setValue(value).onChange(v => { value = v; preview(); }))
      .addButton(b => b.setButtonText('保存').onClick(async () => {
        b.setDisabled(true);
        try { setState('done', '✓ ' + await saveFolder(value)); }
        catch (e) { setState('failed', '没做成：' + e.message); }
        finally { b.setDisabled(false); }
      }));
    setState('', '当前：' + (plugin.vaultDir || base || '本库根目录'));
    return row;
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
    // 首次引导 = 设置页「开始」分页
    open() { return plugin.openSetupPage('start'); },
    needsOnboarding,
    renderFolder,
    saveFolder,
    aiConfigured,
    // 启动时（窗口开好后）：Dataview 缺了 / 后端程序找不到 → 提示一次（带按钮）；还没准备好的新库 → 打开「开始」页（只自动开这一次）
    async startup() {
      const dv = plugin.dataviewState();
      if (dv && dv !== 'ok') noticeWithButton(plugin.dataviewHint(dv), dataviewButtons(dv)[0][0], dataviewButtons(dv)[0][1], 20000);
      const b = plugin.currentBackend();
      if (b.mode === 'missing') { noticeWithButton(plugin.backendMissingText(), '复制安装命令', () => copy(BACKEND_INSTALL), 30000); return 'backend-missing'; }
      if (await needsOnboarding()) {
        plugin.settings.onboarding = { done: true, at: new Date().toISOString(), via: 'setup-page' };
        Promise.resolve(plugin.saveSettings()).catch(e => console.error('[lb] 引导状态没存上', e));
        this.open();
        return 'onboarding';
      }
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

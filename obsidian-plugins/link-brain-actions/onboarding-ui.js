// onboarding-ui.js — 第 5 批 B2（RELEASE-BAR P8）：首次打开的引导 + 启动时的「缺什么」提示。
// main.js 只接几行：onboardingUI() 按需 require 本文件；openOnboarding() / startupChecks() / renderSetupHints(c) 转到这里。
// 1009 作者：首次不弹分步向导了——零配置，装上就按轻量版自动跑一次（home-ui.js firstRun）；设置页顶部就是功能开关。
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

  // 要不要自己弹引导：走过了 / 收藏库已有 _archive（作者本机、老用户）→ 不弹。
  // 1102：后端没找到**也算要引导**（以前返回 false，首次引导整个被跳过）——startup 会先自己把后端装好（backend-install.js）再走首次自动跑。
  async function needsOnboarding() {
    if (plugin.settings?.onboarding?.done) return false;
    try { if (await plugin.app.vault.adapter.exists(plugin.lbPath('_archive'))) return false; } catch { return false; }
    return true;
  }
  // 1102：没有后端 → 调插件自己的安装（进度画在设置页顶部「懒人安装」那一块）。返回 ensureBackend 的结果（{ok, code, message}，不抛）
  async function installBackend({ quiet = false } = {}) {
    try { return await plugin.homeUI().installBackend({ quiet }); }
    catch (e) { return { ok: false, code: 'PERMANENT.BAD_PACKAGE', message: '安装后端时出错：' + (e && e.message || e) }; }
  }

  function aiConfigured(s) {
    const t = (s && s.textAI) || {};
    if (t.mode === 'cli') return !!(t.command || t.preset);
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
    if (['command', 'managed'].includes(plugin.currentBackend().mode)) {
      try { plugin.writeUserConfig({ vault: plugin.vaultDir }); extra = '（命令行也用这个位置）'; }
      catch (e) { extra = '（插件里已生效；命令行用的 ~/.link-brain/config.json 没写上：' + e.message + '）'; }
    }
    return '收藏放在 ' + plugin.vaultDir + extra;
  }

  // 第 7 批：原首次引导第 ① 步，搬成一行设置。1010：设置页里只在「收藏与同步」这一处（main.js fieldCollectionFolder 调它，
  // 不再有第二份兜底的同名行）。文件夹 + 保存 + 一行如实状态。
  function renderFolder(container, tab = null) {
    let value = plugin.settings.collectionFolder || '';
    const base = String(plugin.app.vault.adapter.getBasePath() || '');
    const row = new Setting(container).setName('收藏放在哪')
      .setDesc('默认就在这个库里；填文件夹名就放进那个文件夹（没有会自动建）。');
    row.settingEl.addClass('lb-folder-row');
    if (tab && typeof tab.help === 'function') tab.help(row, '只能填这个库里的文件夹名，不填盘符或完整路径。');
    const state = row.descEl.createDiv({ cls: 'lb-onb-state' });
    const setState = (kind, text) => { state.className = 'lb-onb-state' + (kind ? ' is-' + kind : ''); state.setText(text); };
    const preview = () => { const n = normalizeFolder(value); n.ok ? setState('', '收藏会放在：' + (n.folder ? base.replace(/[\\/]+$/, '') + '/' + n.folder : base)) : setState('failed', n.error); };
    let input = null;
    row.addText(t => { input = t; t.setPlaceholder('留空 = 库根目录，或如：收藏').setValue(value).onChange(v => { value = v; preview(); }); })
      .addButton(b => b.setButtonText('保存').onClick(async () => {
        b.setDisabled(true);
        try { setState('done', '✓ ' + await saveFolder(value) + '（已经存下的收藏不会跟着搬）'); }
        catch (e) { setState('failed', '没做成：' + e.message); }
        finally { b.setDisabled(false); }
      }));
    setState('', '当前：' + (plugin.vaultDir || base || '本库根目录'));
    // 1103：页上两处（懒人安装卡片上方 + 收藏与同步）——另一处存了新位置，这里跟着变（正在这一格里打字时不动它）
    const ws = plugin.app.workspace;
    if (input && ws && typeof ws.on === 'function') {
      const ref = ws.on('link-brain:settings', () => {
        const saved = plugin.settings.collectionFolder || '';
        const el = input.inputEl;
        if (saved === value || (el && el.ownerDocument && el.ownerDocument.activeElement === el)) return;
        value = saved; input.setValue(saved);
        setState('', '当前：' + (plugin.vaultDir || base || '本库根目录'));
      });
      if (tab && tab.stops) tab.stops.push(() => { try { ws.offref(ref); } catch {} });
    }
    return row;
  }

  // 带一个按钮的提示（Obsidian Notice 支持 DocumentFragment；没 document 的环境退回纯文字）
  function noticeWithButton(text, label, onClick, timeout = 0) {
    return plugin.notify(text, { ms: timeout, actions: [{ label, run: onClick }] });
  }

  // 一块醒目的提示：文字 + 按钮（设置页顶部、目录页顶部共用）
  function hintBox(container, text, buttons, cls = '') {
    const box = container.createDiv({ cls: 'lb-setup-hint ' + cls });
    box.createEl('p', { text });
    const row = box.createDiv({ cls: 'lb-setup-hint-actions' });
    for (const [label, fn] of buttons) { const b = row.createEl('button', { text: label }); b.onclick = fn; }
    return box;
  }

  return {
    // 首次引导 = 设置页「开始」分页
    open() { return plugin.openSetupPage('features'); },
    needsOnboarding,
    installBackend,
    renderFolder,
    saveFolder,
    aiConfigured,
    // 启动时（窗口开好后）：后端程序找不到 → 自动装、装不上提示一次（带按钮）；还没准备好的新库 → 打开「开始」页（只自动开这一次）。
    // 1102：不再查 Dataview（页面由插件自己画）
    async startup() {
      const b = plugin.currentBackend();
      // 1104 作者：首轮全自动时自动打开的设置页直接是「懒人安装」卡片，不先出「开始使用 LWA」引导（新库里引导会盖住安装进度）。
      // 引导记成走过；想走还能在「06 修复 → 重新走一遍首次设置」进
      const skipGuide = () => { plugin.settings.onboarding = { ...(plugin.settings.onboarding || {}), guideDone: true }; };
      if (b.mode === 'missing') {
        skipGuide();
        Promise.resolve(plugin.saveSettings()).catch(e => console.error('[lb] 引导状态没存上', e));
        // 1102：不再只弹「复制安装命令」——新电脑（可能连 Python 都没有）由插件自己装后端；装好接着走首次自动跑，没装上才提示并停下
        // 1103 作者：全自动——直接打开设置页的「懒人安装」卡片（上面边装边选，下面是进度），通知只是个入口
        try { plugin.openSetupPage?.(); } catch (e) { console.error('[lb] 设置页没打开', e); }
        plugin.notify('Link Brain 正在自动安装（后端、认字、读取组件，几百 MB）：进度在设置页「懒人安装」，上面的选项随时能改。', { ms: 12000,
          actions: [{ label: '看进度', run: () => plugin.openSetupPage?.() }] });
        const got = await installBackend({ quiet: true });
        if (!got || !got.ok || plugin.currentBackend().mode === 'missing') {
          noticeWithButton(plugin.backendMissingText() + (got && got.message ? '（自动安装没做成：' + got.message + '）' : ''), '复制安装命令', () => copy(BACKEND_INSTALL), 30000);
          return 'backend-missing';
        }
      }
      if (await needsOnboarding()) {
        // 1009 作者：零配置——装上就按轻量版自动跑（装好缺的 → 同步 → OCR → 目录 → 索引），不弹分步向导
        // 1103 作者（虚拟机）：「走完首次设置教程，后来又被带回第 2 步『同步』」——根因在这里：以前整个换掉 onboarding，
        // 装后端那几分钟里用户在设置页走完的教程（guideDone）被冲掉；目录页还没生成时 needsGuide() 又判「要教程」，
        // 带着「同步时间」落点打开设置页就停在第 2 步。现在只并进这几个键，走完的记号留着
        skipGuide();
        plugin.settings.onboarding = { ...plugin.settings.onboarding, done: true, at: new Date().toISOString(), via: 'first-run' };
        Promise.resolve(plugin.saveSettings()).catch(e => console.error('[lb] 引导状态没存上', e));
        try { await plugin.homeUI().firstRun(); } catch (e) { console.error('[lb] 首次自动跑没起来', e); this.open(); }
        return 'onboarding';
      }
      try { await plugin.homeUI().firstRun(); } catch (e) { console.error('[lb] 首次标记没记上', e); }
      return 'ready';
    },
    // 设置页最上面：缺后端 / 旧图片导航插件还开着 → 各一块提示（都正常就什么也不加）
    renderSetupHints(c) {
      const shown = [];
      const b = plugin.currentBackend();
      // 1103：正在装后端时不另挂提示（进度就在下面「懒人安装」卡片里）；没在装才说缺后端。后端一装好这块自己消失（挂在 home 的重画上）
      if (b.mode === 'missing' && !plugin.backendInstalling?.()) {
        const box = hintBox(c, plugin.backendMissingText(), [['一键装好', () => installBackend()], ['复制安装命令', () => copy(BACKEND_INSTALL)]], 'is-backend');
        shown.push('backend');
        const h = plugin.homeUI?.();
        if (h && typeof h.onRepaint === 'function') {
          const off = h.onRepaint(() => { if (plugin.backendInstalling?.() || plugin.currentBackend().mode !== 'missing') { box.remove?.(); off(); } });
        }
      }
      if (plugin.mediaNav?.skipped) {
        hintBox(c, '图片导航已经并进本插件。旧插件「Link Brain Native Media Nav」还开着，现在由它负责；在「第三方插件」里停用它并重启 Obsidian，就由本插件接管（两个同时开会重复）。',
          [['打开第三方插件', () => plugin.openPluginSettings('community-plugins')]], 'is-medianav');
        shown.push('medianav');
      }
      return shown;
    },
    _internals: { normalizeFolder, aiConfigured, noticeWithButton },
  };
};

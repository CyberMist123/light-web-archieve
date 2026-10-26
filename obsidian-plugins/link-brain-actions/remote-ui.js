// 连接其他 AI（1009 她：连几个 MCP 要看好几个地方 → 一个模块；1010 她：设置页分栏，这是「连接其他 AI」一整栏）。
// main.js 只有几处接入：
//   onload：this.remoteUI = require(<插件目录>/remote-ui.js)(obsidian, this); await this.remoteUI.attach();
//   saveSettings：保存前 await this.remoteUI.beforeSave()（remote 段以磁盘为准，见下）
//   设置页「连接其他 AI」：this.plugin.remoteUI?.renderConnect(c, redraw, tab)——远程访问的东西全在这一栏（1010 她：别拆两处）
// 1027 设置页六组：⑤「CLI 与外接 MCP」里两张卡——电脑端（settings-v6.js 按 connect status 认出的应用，一个开关接上）· 网页端（这里的 part:'web'）：
//   远程访问开没开、你的网址（紧挨着「还没有网址？」两条路）、连接地址、口令、ChatGPT / claude.ai 几步做法（只有 WEB_STEPS 这一份）、已经连上的；
//   不支持口令的软件到⑤「更多」里生成访问令牌（renderAdvanced）。旧的「勾选软件」小片和 settings.connect.clients 删了。
// 对新手只讲「口令」；访问令牌只在「高级」折叠里给不支持口令的软件用；「OAuth」这个词不在界面上出现。
// 开放哪些文件夹（权限）只在这里一处：小红书收藏库开关 + 已开放的列表 +「从库内选…」「选本机文件夹…」两个入口并排（手输路径留作兜底）。
// 服务本体是独立后台进程（python -m link_brain remote serve，Windows 上由计划任务 LwaMcp 常驻），关掉 Obsidian 照常可连。
// 口令 / 令牌不经过 data.json：口令走 stdin 交给 Python（哈希 + DPAPI 副本存 ~/.link-brain/remote），令牌只在生成时显示一次。
//
// 10-09 根因修复：remote 段的唯一来源是磁盘上的 data.json（任何一次保存前 beforeSave 先从磁盘重读；这一页改 remote 走 saveRemote）。
// CONVENTIONS §1：每个操作如实提示结果（成功说做了什么，失败带原因）；状态只显示后端给的。
'use strict';

// 必须和 link_brain/remote/config.py 的 DEFAULTS 一致（tests/test_remote_cli.py 核对），改一处改两处。
const REMOTE_DEFAULTS = {"enabled": false, "domain": "", "port": 18071, "folders": ["@xhs"]};
const XHS = '@xhs';
const XHS_LABEL = '小红书收藏库';
const DOMAIN_RE = /^https:\/\/([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const DOCS_URL = 'https://github.com/CyberMist123/light-web-archieve/blob/main/docs/remote-access.md';
// 「连接其他 AI」的软件（id → 名字 / 本机还是网页）
const CLIENTS = [['claude-code', 'Claude Code', 'local'], ['claude-desktop', 'Claude Desktop', 'local'], ['claude-ai', 'claude.ai', 'web'],
  ['chatgpt', 'ChatGPT', 'web'], ['other', '其他 AI 软件', 'other']];
const WEB_STEPS = {
  'claude-ai': ['claude.ai（网页 / 手机 App）：设置 → Connectors → Add custom connector，名字填 LWA，URL 粘「连接地址」，点 Add。',
    '点 Connect，会打开这台电脑上的授权页：粘贴口令 →「允许连接」，自动跳回就连上了。',
    '聊天里在工具菜单打开 LWA，说「在我的收藏里搜……」试一句。'],
  chatgpt: ['ChatGPT：设置 → Apps & Connectors → Advanced settings，打开 Developer mode。',
    '回到 Apps & Connectors → Create：名字 LWA，MCP Server URL（服务器地址那一格）粘「连接地址」；Authentication 选会弹授权页的那一项（不是 No authentication），勾「我信任这个应用」，Create。',
    '弹出授权页：粘贴口令 →「允许连接」。新对话里在 + → 更多 选上 LWA 再提问。'],
};

// 「复制接入说明」：连接地址 + 两家几步（和上面 WEB_STEPS 同一份；口令本身不进剪贴板）
function webGuideText(url) {
  const list = a => a.map((x, k) => `${k + 1}. ${x}`).join('\n');
  return ['LWA 收藏库（MCP，只读：能搜、能读、能看图，不能改也不能删）',
    '连接地址：' + (url || '还没填网址——先在 LWA 设置「CLI 与外接 MCP → 网页端」里填'),
    '', ...CLIENTS.filter(c => c[2] === 'web').flatMap(([id, name]) => [name + '：', list(WEB_STEPS[id]), '']),
    '用的时候说「在我的收藏里搜……」。'].join('\n');
}

function normalizeRemote(raw) {
  const out = JSON.parse(JSON.stringify(REMOTE_DEFAULTS));
  if (!raw || typeof raw !== 'object') return out;
  out.enabled = raw.enabled === true;
  if (typeof raw.domain === 'string') out.domain = raw.domain;
  const port = parseInt(raw.port, 10);
  if (port >= 1024 && port <= 65535) out.port = port;
  if (Array.isArray(raw.folders)) out.folders = [...new Set(raw.folders.filter(f => typeof f === 'string' && f.trim()).map(f => f.trim()))];
  return out;
}

// 'https://A.example.com/' → 'https://a.example.com'；空 → ''；不合格 → null
function cleanDomain(text) {
  const t = String(text || '').trim().replace(/\/+$/, '').toLowerCase();
  if (!t) return '';
  return DOMAIN_RE.test(t) ? t : null;
}

// 库外绝对路径（C:\… / C:/… / \\server\share / POSIX /…）——和 policy.is_external 同一判据
function isExternal(f) { return /^[A-Za-z]:[\\/]/.test(f) || f.startsWith('\\\\') || (process.platform !== 'win32' && f.startsWith('/')); }

function fmtTime(ts) { return ts ? String(ts).replace('T', ' ').slice(5, 16) : ''; }

const ACCESS_TOOL = { search: '搜索', read: '读', image: '看原图', files: '浏览文件夹', topics: '星标主题', selections: '暗号',
  recent: '最近收藏', history: '搜索历史', ask: '问收藏', read_asset: '看原图', list: '列目录', mcp: '连接', http: '请求',
  'oauth.register': '注册客户端', 'oauth.approve': '授权', 'oauth.token': '换令牌' };
const ACCESS_CODE = { BAD_TOKEN: '令牌无效或已撤销', BAD_PASSPHRASE: '口令不对', LOCKED: '口令错太多次，暂时锁定',
  BAD_HOST: '地址没登记', BAD_ORIGIN: '来自别的网页', RATE_LIMITED: '太频繁', NOT_SHARED: '不在开放的文件夹里',
  FORBIDDEN: '禁止读取', INVALID_PATH: '路径不合法', NOT_FOUND: '没有这个文件', NOT_TEXT: '不是文本文件', BAD_PKCE: 'PKCE 校验没过' };

function accessLine(r) {
  const what = ACCESS_TOOL[r.tool] || r.tool || '';
  const res = r.status === 'ok' ? '成功' : (r.status === 'denied' ? '拒绝' : '出错') + (r.code ? '（' + (ACCESS_CODE[r.code] || r.code) + '）' : '');
  return [fmtTime(r.ts), r.client || '未授权', what, r.path || '', res].filter(Boolean).join(' · ');
}

// 库内文件夹（Obsidian 的路径，相对库根）→ 远程配置里的路径（相对收藏库根）；不在收藏库里 → null
function vaultRelative(folderPath, lbRoot) {
  const p = String(folderPath || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const root = String(lbRoot || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  if (!p) return null;
  if (!root) return p;
  if (p === root) return null;
  return p.startsWith(root + '/') ? p.slice(root.length + 1) : null;
}

module.exports = function remoteUI(obsidian, plugin) {
  const { Setting, Notice, Modal, FuzzySuggestModal, TFolder } = obsidian;
  const run = (args, opts = {}) => plugin.runPy(['-m', 'link_brain', 'remote', ...args], { label: '远程 MCP', fallback: '远程 MCP 命令没有结果', ...opts });
  // 服务读的就是本插件此刻写的那份 data.json（库被联接点挂进别的库时，插件目录不一定在归档 vault 里）
  const settingsArgs = () => {
    try { return ['--settings', require('path').join(plugin.app.vault.adapter.getBasePath(), plugin.manifest.dir, 'data.json')]; }
    catch { return []; }
  };
  const s = () => plugin.settings.remote;
  let fresh = false;   // 这一刻内存里的 remote 段刚从磁盘读过并改好，下一次保存照它写

  async function syncFromDisk() {
    let raw = null;
    try { raw = await plugin.loadData(); } catch { raw = null; }
    plugin.settings.remote = normalizeRemote(raw && raw.remote);
    return plugin.settings.remote;
  }
  // 改 remote 段的唯一入口：读磁盘最新 → 改 → 写
  async function saveRemote(mutate) {
    const r = await syncFromDisk();
    mutate(r);
    fresh = true;
    try { await plugin.saveSettings(); } finally { fresh = false; }
    return r;
  }
  const copy = async (text, what) => { await navigator.clipboard.writeText(text); new Notice('已复制' + what); };

  // 一次 CLI 调用的统一提示：ok → 成功句；否则「没…：原因」
  async function act(args, failPrefix, opts = {}) {
    try {
      const { json } = await run(args, opts);
      if (json && json.ok) return json;
      new Notice(failPrefix + '：' + ((json && json.message) || '没有原因'), 10000);
      return json || { ok: false };
    } catch (e) { new Notice(failPrefix + '：' + e.message, 10000); return { ok: false, message: e.message }; }
  }
  async function connectCmd(args, failPrefix) {
    try {
      const { json } = await plugin.runPy(['-m', 'link_brain', 'connect', ...args], { label: '连接 AI', fallback: '连接命令没有结果', timeoutMs: 120000, okCodes: [0, 1] });
      if (json && !json.ok && failPrefix) new Notice(failPrefix + '：' + (json.message || '没有原因'), 10000);
      return json || { ok: false, message: '没有结果' };
    } catch (e) { if (failPrefix) new Notice(failPrefix + '：' + e.message, 10000); return { ok: false, message: e.message }; }
  }

  class TextModal extends Modal {
    constructor(title, build) { super(plugin.app); this.title = title; this.build = build; }
    onOpen() { this.contentEl.empty(); this.contentEl.createEl('h3', { text: this.title }); this.build(this.contentEl, this); }
    onClose() { this.contentEl.empty(); }
  }

  function passphraseModal(done) {
    new TextModal('设一个口令', (el, modal) => {
      el.createEl('p', { cls: 'setting-item-description', text: '网页版 AI 第一次连接时，授权页会让你输这个口令。至少 8 个字。' });
      el.createEl('p', { cls: 'setting-item-description', text: '口令只加密存在这台电脑上，不进插件设置。改口令不影响已经连上的；想让某个重新授权，在「已经连上的网页版」里断开它。' });
      const a = el.createEl('input', { type: 'password', attr: { placeholder: '新口令', autocomplete: 'new-password' } });
      const b = el.createEl('input', { type: 'password', attr: { placeholder: '再输一次', autocomplete: 'new-password' } });
      for (const i of [a, b]) { i.style.width = '100%'; i.style.marginBottom = '8px'; }
      const msg = el.createEl('p', { cls: 'setting-item-description' });
      new Setting(el).addButton(btn => btn.setButtonText('保存口令').setCta().onClick(async () => {
        if (a.value.length < 8) { msg.setText('至少 8 个字符'); return; }
        if (a.value !== b.value) { msg.setText('两次输的不一样'); return; }
        btn.setDisabled(true);
        const r = await act(['passphrase'], '口令没保存上', { input: JSON.stringify({ passphrase: a.value }) });
        a.value = ''; b.value = '';
        if (r.ok) { new Notice(r.message || '口令已保存'); modal.close(); done && done(); } else { msg.setText(r.message || '没保存上'); btn.setDisabled(false); }
      }));
    }).open();
  }

  async function confirmModal(title, text, okText, onOk) {
    if (await plugin.confirm({ title, body: text, ok: okText, danger: true })) await onOk();
  }

  // 「选本机文件夹」：Electron 的对话框（新版 Obsidian 多半拿不到）→ Python 弹系统对话框（`pick-folder`，tkinter 置顶 / PowerShell 兜底）
  async function pickFolder() {
    try {
      const electron = require('electron');
      const remote = electron.remote || (() => { try { return require('@electron/remote'); } catch { return null; } })();
      if (remote && remote.dialog) {
        const r = await remote.dialog.showOpenDialog({ properties: ['openDirectory'] });
        return r && !r.canceled && r.filePaths && r.filePaths[0] ? r.filePaths[0] : null;
      }
    } catch (e) { if (e && e.code !== 'MODULE_NOT_FOUND') console.warn('[lb] Electron 文件夹对话框不可用', e); }
    try {
      const { json } = await plugin.runPy(['-m', 'link_brain', 'pick-folder', '--title', '选一个要开放给 AI 的文件夹'],
        { label: '选文件夹', fallback: '选文件夹的对话框没弹出来', timeoutMs: 15 * 60000, okCodes: [0, 1] });
      if (json && json.ok) return json.canceled ? '' : (json.path || '');
      new Notice((json && json.message) || '选文件夹的对话框没弹出来：请直接粘贴路径', 10000);
    } catch (e) { new Notice('选文件夹的对话框没弹出来：' + e.message + '。请直接粘贴路径', 10000); }
    return null;
  }

  // 「从库内选…」：Obsidian 自己的模糊搜索弹窗（FuzzySuggestModal），列收藏库里的所有文件夹
  function pickVaultFolder() {
    return new Promise(resolve => {
      const all = (plugin.app.vault.getAllLoadedFiles ? plugin.app.vault.getAllLoadedFiles() : [])
        .filter(f => (TFolder ? f instanceof TFolder : Array.isArray(f.children)) && f.path && !f.path.split('/').some(seg => seg.startsWith('.')));
      const items = all.map(f => ({ path: f.path, rel: vaultRelative(f.path, plugin.lbRoot || '') })).filter(x => x.rel && x.rel !== '_archive' && !x.rel.startsWith('_archive/'));
      if (!FuzzySuggestModal) { resolve(null); return; }
      let chosen = null;
      class FolderModal extends FuzzySuggestModal {
        getItems() { return items; }
        getItemText(item) { return item.rel; }
        onChooseItem(item) { chosen = item.rel; }
        onClose() { setTimeout(() => resolve(chosen), 0); }
      }
      const m = new FolderModal(plugin.app);
      try { m.setPlaceholder('搜库里的文件夹（回车开放给 AI）'); } catch {}
      m.open();
    });
  }

  // 已开放的文件夹：加一个（库内相对路径 / 库外绝对路径），先问后端能不能开放
  async function addFolder(raw, after) {
    const p = String(raw || '').trim().replace(/[\\/]+$/, '');
    if (!p) return false;
    if (isExternal(p)) { const chk = await act(['folders', '--check', p], '不能开放'); if (!chk.ok) return false; }
    else if (/^[A-Za-z]:/.test(p) || p.startsWith('..')) { new Notice('库内文件夹用「从库内选…」，库外的要完整路径（比如 D:\\笔记）', 8000); return false; }
    await saveRemote(x => { if (!x.folders.includes(p)) x.folders.push(p); });
    new Notice('已开放「' + p + '」' + (s().enabled ? '，几秒内生效' : '')); after && after();
    return true;
  }

  function showToken(token) {
    new TextModal('新的访问令牌', (el, modal) => {
      el.createEl('p', { text: '只显示这一次，关掉就看不到了：现在复制，填进那个软件的「访问令牌」一格（有的软件叫 Authorization 请求头：Bearer <令牌>）。' });
      const code = el.createEl('code', { text: token }); code.style.cssText = 'display:block;word-break:break-all;user-select:all;padding:8px;';
      new Setting(el).addButton(b => b.setButtonText('复制').setCta().onClick(() => copy(token, '访问令牌')))
        .addButton(b => b.setButtonText('关闭').onClick(() => modal.close()));
    }).open();
  }
  function showManual(command) {
    new TextModal('这台电脑要手动启动远程访问', (el, modal) => {
      el.createEl('p', { text: '这台电脑不是 Windows，没法自动在后台常驻。开关已经打开；请在终端里运行下面这条命令（想开机自动运行，把它加进系统的开机启动项）：' });
      const code = el.createEl('code', { text: command }); code.style.cssText = 'display:block;word-break:break-all;user-select:all;padding:8px;';
      new Setting(el).addButton(b => b.setButtonText('复制').setCta().onClick(() => copy(command, '命令')))
        .addButton(b => b.setButtonText('关闭').onClick(() => modal.close()));
    }).open();
  }

  // 远程服务开 / 关（网页客户端那一步里用；先存开关再调 enable，注册失败开关退回去）
  function xhsToggle(row, tab = null) {
    if (tab && typeof tab.help === 'function') tab.help(row, '.obsidian、隐藏文件夹、插件设置、密钥、数据库和日志永远不开放，开了也读不到。');
    row.settingEl?.addClass?.('lb-xhs-open');
    row.addToggle(t => {
      let reverting = false;
      t.setValue((s().folders || []).includes(XHS)).onChange(async v => {
        if (reverting) return;
        try { await saveRemote(x => { x.folders = v ? [...new Set([...x.folders, XHS])] : x.folders.filter(f => f !== XHS); }); }
        catch (e) { reverting = true; try { t.setValue(!v); } catch {} finally { reverting = false; } new Notice('没保存上，开关已拨回原来的位置：' + e.message, 8000); return; }
        new Notice((v ? '已开放' : '已不再开放') + '小红书收藏库' + (s().enabled ? '，几秒内生效' : ''));
      });
    });
    return row;
  }

  async function setEnabled(v) {
    await saveRemote(x => { x.enabled = v; });
    if (v) {
      const res = await act(['enable', ...settingsArgs()], '没启用上');
      if (res.ok) { new Notice(res.message || '已启用'); return true; }
      if (res.code === 'SKIPPED.NOT_CONFIGURED' && res.command) { showManual(res.command); return true; }
      await saveRemote(x => { x.enabled = false; });
      return false;
    }
    const res = await act(['disable'], '没停干净');
    if (res.ok) new Notice(res.message || '已停用');
    return true;
  }

  // 设置页⑤「更多」（1027；原「连接其他 AI」最下面的「高级」）：运行情况 · 端口 · 访问令牌（给不支持口令的软件）·
  // 全部断开 · 后台服务 · 访问记录 · 测一下本机的连接程序。对新手只讲「口令」——令牌只在这里出现（10-10 她定）。
  function renderAdvancedInto(container, tab = null) {
    if (!plugin.settings.remote) plugin.settings.remote = normalizeRemote(null);
    const box = container.createDiv({ cls: 'lb-remote-adv' });
    const help = (row, text) => (tab && typeof tab.help === 'function' ? tab.help(row, text) : null);
    const redraw = async () => { await syncFromDisk(); box.empty(); draw(); };
    const draw = () => {
      const r = s();
      const st = new Setting(box).setName('远程访问的运行情况').setDesc('读取中…');
      st.addExtraButton(b => b.setIcon('refresh-cw').setTooltip('刷新').onClick(() => redraw()));
      const portRow = new Setting(box).setName('端口').setDesc('这台电脑上远程访问服务用的端口（1024–65535）。');
      help(portRow, '你的隧道（Cloudflare / Tailscale）那头要指到同一个端口。');
      portRow.addText(t => {
        t.setValue(String(r.port));
        t.inputEl.addEventListener('change', async () => {
          const p = parseInt(t.inputEl.value, 10);
          if (!(p >= 1024 && p <= 65535)) { new Notice('端口要在 1024–65535 之间', 8000); t.setValue(String(r.port)); return; }
          if (p === r.port) return;
          await saveRemote(x => { x.port = p; });
          if (s().enabled) { const res = await act(['restart'], '端口已保存，但服务没重启上'); if (res.ok) new Notice('端口已改成 ' + p + '，服务已重启（隧道那头也要跟着改）'); }
          else new Notice('端口已保存');
          redraw();
        });
      });
      const tokSet = new Setting(box).setName('访问令牌（给不支持口令的软件）').setDesc('有的软件不会弹授权页、只能填一串令牌：在这里生成一个给它。');
      help(tokSet, '放进那个软件的「访问令牌」一格（有的软件叫 Authorization 请求头：Bearer <令牌>）。');
      let label = '';
      tokSet.addText(t => t.setPlaceholder('备注（可选）').onChange(v => label = v));
      tokSet.addButton(b => b.setButtonText('生成（只显示一次）').onClick(async () => {
        b.setDisabled(true);
        const res = await act(['token', 'new', '--label', label || '访问令牌'], '没生成出来');
        b.setDisabled(false);
        if (res.ok && res.token) showToken(res.token);
        redraw();
      }));
      const tokBox = box.createDiv();
      const revoke = new Setting(box).setName('全部断开').setDesc('所有连上的软件和访问令牌都会立刻失效；口令不变。');
      revoke.addButton(b => b.setButtonText('全部断开（都要重新授权）').setWarning().onClick(() => confirmModal('全部断开？',
        'claude.ai / ChatGPT 等所有连上的软件、所有访问令牌马上失效，要重新授权才能再连。口令不变。', '全部断开', async () => {
          const res = await act(['revoke-all'], '没断开');
          if (res.ok) new Notice(res.message || '已全部断开');
          redraw();
        })));
      const taskLine = box.createEl('p', { cls: 'setting-item-description' });
      box.createDiv({ cls: 'setting-item-name', text: '访问记录' }).style.marginTop = '12px';
      const recent = box.createDiv({ cls: 'setting-item-description lb-remote-recent' });
      recent.setText('读取中…');
      if (tab && typeof tab.addTestButton === 'function') tab.addTestButton(box, '测一下本机的连接程序（MCP）', ['-m', 'link_brain', 'selftest', 'mcp']);
      (async () => {
        let j = null;
        try { ({ json: j } = await run(['status', ...settingsArgs()], { timeoutMs: 30000, fallback: '读不到状态' })); }
        catch (e) { st.setDesc(''); if (typeof plugin.failBox === 'function') plugin.failBox(st.descEl, '', e, () => redraw()); recent.setText(''); return; }
        if (!j) { st.setDesc(''); if (typeof plugin.failBox === 'function') plugin.failBox(st.descEl, '', new Error('后台没有返回'), () => redraw()); recent.setText(''); return; }
        st.setDesc((j.state === 'running' ? '● 开着：' : j.state === 'error' ? '✗ 出了问题：' : '○ 没开：') + (j.message || j.state));
        const t = j.task || {};
        taskLine.setText('后台服务：计划任务 ' + (t.name || 'LwaMcp') + (t.registered ? '（' + (t.state || '已注册') + (t.last_run ? '，上次启动 ' + fmtTime(t.last_run) : '') + '）' : t.supported === false ? '（不是 Windows：要手动启动）' : '（还没注册）')
          + ' · 设置文件 ' + (j.settings_path || ''));
        for (const p of (j.auth || {}).personal || []) new Setting(tokBox).setName('　' + (p.label || '访问令牌'))
          .setDesc('生成于 ' + fmtTime(p.created) + (p.last_used ? ' · 最近用过 ' + fmtTime(p.last_used) : ' · 还没用过'))
          .addButton(b => b.setButtonText('作废').onClick(async () => {
            const res = await act(['token', 'revoke', p.id], '没作废');
            if (res.ok) new Notice('已作废「' + (p.label || '访问令牌') + '」');
            redraw();
          }));
        recent.empty();
        const rows = j.recent || [];
        if (!rows.length) recent.setText('还没有访问记录。');
        for (const row of rows.slice(0, 20)) recent.createDiv({ text: accessLine(row) });
      })();
    };
    syncFromDisk().then(draw, draw);
  }

  return {
    REMOTE_DEFAULTS, normalizeRemote, cleanDomain, accessLine, isExternal, vaultRelative, CLIENTS, WEB_STEPS, webGuideText, pickFolder, addFolder, setEnabled,

    // onload：data.json 里的 remote 段挂到 settings 上（mergeSettings 只认 DEFAULT_SETTINGS 的键，不挂会在下次保存时丢）
    async attach() { await syncFromDisk(); },

    // 插件任何一次保存前调：remote 段以磁盘为准（除非这一页刚经 saveRemote 改过）
    async beforeSave() { if (!fresh) await syncFromDisk(); },

    // —— 设置页⑤「CLI 与外接 MCP → 让其他 AI 读收藏」（1027 六组）——
    // part：'web' = 「网页端」那张卡（远程访问开关 · 你的网址 · 连接地址 · 口令 · ChatGPT / claude.ai 几步 · 已经连上的）；
    //       'folders' = 开放给 AI 的文件夹（skipXhs：小红书收藏库那一个开关设置页自己常露，这里只画其他的 + 再开放一个）。
    // toggleHost（'web'）：远程访问的开关画在卡片标题右边（她：开关在卡片上），状态一句在卡片里；关着时下面只有一句怎么用。
    // 1027：旧的 'all' 整栏（勾选软件的小片 + 本机 Claude Code / Desktop 一键接上）删了——本机的在「电脑端」那张卡（connect status 认出的应用）。
    renderConnect(container, redrawAll, tab = null, { part = 'web', toggleHost = null, skipXhs = false } = {}) {
      if (!plugin.settings.remote) plugin.settings.remote = normalizeRemote(null);
      const box = container.createDiv({ cls: 'lb-connect' });
      const main = box.createDiv({ cls: 'lb-connect-main' });
      const typed = {};   // 重画时保住正在打的字（你的网址 / 粘贴路径）：存好了才清掉
      const focusOf = el => { try { const ae = el.ownerDocument && el.ownerDocument.activeElement; const key = ae && el.contains && el.contains(ae) && ae.getAttribute && ae.getAttribute('data-lb-key'); return key ? { key, a: ae.selectionStart, b: ae.selectionEnd } : null; } catch { return null; } };
      const refocus = (el, keep) => { if (!keep) return; try { const t = el.querySelector && el.querySelector('[data-lb-key="' + keep.key + '"]'); if (!t) return; t.focus(); if (keep.a != null && t.setSelectionRange) t.setSelectionRange(keep.a, keep.b); } catch {} };
      let alive = true;
      const redraw = async () => { if (!alive) return; await syncFromDisk(); if (!alive) return; const keep = focusOf(main); main.empty(); draw(); refocus(main, keep); };
      let status = null;   // 后端回来的：remote status
      const help = (row, text) => (tab && typeof tab.help === 'function' ? tab.help(row, text) : null);
      const linkBtn = (row, text, onClick, title = '') => row.addButton(b => { b.setButtonText(text).onClick(onClick); b.buttonEl?.addClass?.('lb-link'); if (title) b.buttonEl?.setAttribute?.('aria-label', title); });
      const fail = (where, what, err, retry) => (typeof plugin.failBox === 'function' ? plugin.failBox(where, what, err, retry)
        : where.createEl('p', { cls: 'lb-setup-error', text: (what ? what + '：' : '') + '这一块暂时读不到，点重试' }));
      const statusText = () => !status ? '读取中…' : status.unreadable ? '' : status.state === 'running' ? '● 开着：' + (status.message || '在运行')
        : status.state === 'error' ? '✗ 出了问题：' + (status.message || '') : '○ 没开';

      // 远程访问开关：存失败 / 起不来 → 提示一句，重画时开关按磁盘上的真实状态回到原位
      const onToggle = async (t, v, say) => {
        t.setDisabled?.(true); say(v ? '正在打开（注册后台服务，十几秒）…' : '正在关…');
        try { await setEnabled(v); } catch (e) { new Notice('没保存上，开关已拨回原来的位置：' + e.message, 8000); }
        await loadStatus(); redraw();
      };
      let headToggle = null, quiet = false;
      if (toggleHost && part === 'web') {
        const holder = toggleHost.createDiv({ cls: 'lb-card-toggle' });
        new Setting(holder).addToggle(t => { headToggle = t; t.setValue(!!s().enabled).onChange(v => { if (!quiet) onToggle(t, v, x => { if (main.lbState) main.lbState.setText(x); }); }); });
        holder.querySelector?.('.checkbox-container')?.setAttribute?.('aria-label', '远程访问（网页端）');
      }

      const draw = () => {
        const box = main;
        const r = s();
        const url = r.domain ? r.domain + '/mcp' : '';
        if (part === 'folders') { drawFolders(box, r); return; }
        // 网页端：远程访问 · 你的网址（+ 还没有网址？）· 测一下 · 连接地址 · 口令 · 几步做法 · 已经连上的
        const web = box.createDiv({ cls: 'lb-connect-web' });
        if (headToggle) {
          // 开关按磁盘上的真实状态摆（开没开上、存没存上都以 data.json 为准）；拨的时候不再触发一次
          try { headToggle.setDisabled?.(false); if (headToggle.getValue && headToggle.getValue() !== !!r.enabled) { quiet = true; headToggle.setValue(!!r.enabled); } } catch {} finally { quiet = false; }
          const st = web.createDiv({ cls: 'setting-item-description lb-remote-state lb-remote-svc', text: statusText() });
          main.lbState = st;
          if (status && status.unreadable) fail(st, '', new Error(status.error || ''), async () => { status = null; redraw(); await loadStatus(); redraw(); });
          if (status && status.state === 'error') st.addClass?.('mod-warning');
          if (!r.enabled) { web.createDiv({ cls: 'setting-item-description', text: '打开右上角的开关，再填你的网址和口令；ChatGPT、claude.ai 网页版和手机 App 就能读收藏（只读）。' }); return; }
        } else {
          const svc = new Setting(web).setName('远程访问').setDesc(statusText());
          svc.settingEl.addClass('lb-remote-svc');
          help(svc, '网页版 AI 在外网，要经过你自己的网址，连到这台电脑上的一个小服务；关着 Obsidian 也照常能连。');
          if (status && status.unreadable) fail(svc.descEl, '', new Error(status.error || ''), async () => { status = null; redraw(); await loadStatus(); redraw(); });
          svc.addToggle(t => t.setValue(r.enabled).onChange(v => onToggle(t, v, x => svc.setDesc(x))));
          if (status && status.state === 'error') svc.descEl.addClass?.('mod-warning');
        }
        const dom = new Setting(web).setName('你的网址').setDesc(r.domain ? '' : '填 https:// 开头的网址（只到域名，不带路径）。')
          .addText(t => {
            t.setPlaceholder('https://lwa.example.com').setValue(typed.domain != null ? typed.domain : (r.domain || ''));
            t.inputEl.style.width = '16em';
            if (t.inputEl.setAttribute) t.inputEl.setAttribute('data-lb-key', 'domain');
            t.inputEl.addEventListener('input', () => { typed.domain = t.inputEl.value; });
            t.inputEl.addEventListener('change', async () => {
              const v = cleanDomain(t.inputEl.value);
              if (v === null) { new Notice('网址格式不对：只填 https://主机名，不带端口和路径', 8000); return; }
              try { await saveRemote(x => { x.domain = v; }); }
              catch (e) { new Notice('没保存上，网址没改：' + e.message, 8000); delete typed.domain; t.setValue(r.domain || ''); return; }
              delete typed.domain;
              new Notice(v ? '网址已保存' + (r.enabled ? '，几秒内生效' : '') : '已清空网址：只有这台电脑自己能连'); redraw();
            });
          });
        dom.settingEl.addClass('lb-remote-domain');
        help(dom, '网页版 AI 通过这个网址连回这台电脑；它要指到这台电脑上的远程访问服务（端口在「更多」里）。');
        if (r.domain) {
          linkBtn(dom, '测一下外面能不能连上', async () => {
            dom.setDesc('正在从外面绕一圈：网址 → 你的隧道 → 这台电脑…');
            let j = null;
            try { ({ json: j } = await run(['probe', ...settingsArgs()], { timeoutMs: 30000, fallback: '测不了' })); } catch (e) { j = { ok: false, message: e.message }; }
            dom.setDesc((j && j.ok ? '✓ ' : '✗ ') + ((j && j.message) || '没有结果'));
          }, '从外网访问一次你的网址，看能不能连到这台电脑（只读，不改设置）');
        }
        // 「还没有网址？」——紧挨着网址那一格，没填网址时默认展开；两条路
        const nd = web.createEl('details', { cls: 'lb-remote-nodomain' });
        nd.open = !r.domain;
        nd.createEl('summary', { text: '还没有网址？' });
        const ndb = nd.createDiv({ cls: 'setting-item-description' });
        ndb.createEl('p', { text: '① 已经有自己的域名：用 Cloudflare 免费建一条「隧道」（把外网的网址接到这台电脑上的一根管子），子域名指到 http://127.0.0.1:' + r.port + '，再把 https://子域名 填在上面。' });
        ndb.createEl('p', { text: '② 没有域名：装 Tailscale，打开它的 Funnel，会给你一个固定的网址 https://<电脑名>.<你的名字>.ts.net，填在上面。' });
        ndb.createEl('p', { text: '不推荐临时网址（trycloudflare 那种）：每次重启都会换，已经连上的都要重连。' });
        const doc = new Setting(ndb).setName('图文教程').setDesc('两条路一步一步怎么做，还有常见报错。');
        linkBtn(doc, '打开教程', async () => {
          const p = plugin.repoRoot ? require('path').join(plugin.repoRoot, 'docs', 'remote-access.md') : null;
          let err = 'no repo';
          try { err = p ? await require('electron').shell.openPath(p) : 'no repo'; } catch (e) { err = e.message; }
          if (err) window.open(DOCS_URL);
        }, '打开本机的说明文档（打不开就去 GitHub 上看）');
        const addr = new Setting(web).setName('连接地址').setDesc(url || '先填上面的网址，这里才有地址可复制。');
        addr.settingEl.addClass('lb-remote-addr');
        addr.addButton(b => b.setButtonText('复制').setDisabled(!url).onClick(() => copy(url, '连接地址')));
        const auth = (status && status.auth) || {};
        const pass = new Setting(web).setName('口令').setDesc(!status || status.unreadable ? '读取中…' : auth.passphrase_set
          ? (auth.passphrase_copyable ? '网页版第一次连接时，授权页会让你输它。' : '这个口令是旧版设的、取不回来：点「换一个新口令」重设一次，以后就能复制。')
          : '还没设：点「随机生成一个」最省事（生成就复制好了）。');
        help(pass, '口令只加密存在这台电脑上；只在网页版第一次授权时用。');
        pass.addButton(b => b.setButtonText('复制口令').setDisabled(!(auth.passphrase_set && auth.passphrase_copyable)).onClick(async () => {
          const j = await act(['passphrase', '--reveal'], '没取回口令');
          if (j.ok && j.passphrase) await copy(j.passphrase, '口令');
        }));
        pass.addButton(b => b.setButtonText(auth.passphrase_set ? '换一个新口令（旧的作废）' : '随机生成一个').onClick(async () => {
          const go = async () => { const j = await act(['passphrase', '--generate'], '没生成出来'); if (j.ok && j.passphrase) { await copy(j.passphrase, '新口令（已保存）'); await loadStatus(); redraw(); } };
          if (auth.passphrase_set) await confirmModal('换一个随机口令？', '旧口令马上作废（已经连上的不受影响）。新口令会自动复制到剪贴板。', '生成并复制', go);
          else await go();
        }));
        pass.addButton(b => b.setButtonText(auth.passphrase_set ? '自己改一个' : '自己设一个').onClick(() => passphraseModal(async () => { await loadStatus(); redraw(); })));
        // 几步做法：只有这一份（照 docs/remote-access.md 第 3 步）；也能一键复制（口令本身不进剪贴板）
        const how = web.createEl('details', { cls: 'lb-connect-howto setting-item-description', attr: { 'data-section': 'web-howto' } });
        const hs = how.createEl('summary');
        hs.createSpan({ text: 'ChatGPT、claude.ai 怎么连' });
        const cp = hs.createEl('button', { cls: 'lb-link', text: '复制接入说明' });
        cp.setAttribute('aria-label', '复制连接地址和接入步骤（不含口令）');
        cp.onclick = ev => { ev?.preventDefault?.(); ev?.stopPropagation?.(); copy(webGuideText(url), '接入说明'); };
        for (const [id, name] of CLIENTS.filter(c => c[2] === 'web')) {
          const one = how.createDiv({ attr: { 'data-client': id } });
          one.createEl('div', { cls: 'setting-item-name', text: name + ' 怎么连' });
          const ol = one.createEl('ol'); for (const l of WEB_STEPS[id]) ol.createEl('li', { text: l });
        }
        const clients = auth.clients || [];
        if (clients.length) {
          web.createDiv({ cls: 'setting-item-name lb-remote-sub', text: '已经连上的网页版' });
          for (const c of clients) new Setting(web).setName('　' + c.name)
            .setDesc('连上于 ' + fmtTime(c.connected_at) + (c.last_used ? ' · 最近用过 ' + fmtTime(c.last_used) : ''))
            .addButton(b => b.setButtonText('断开').onClick(() => confirmModal('断开「' + c.name + '」？', '它马上就连不上了，要重新授权才能再连。', '断开', async () => {
              const res = await act(['client', 'revoke', c.id], '没断开');
              if (res.ok) new Notice('已断开「' + c.name + '」');
              await loadStatus(); redraw();
            })));
        }
        for (const w of (status && status.warnings) || []) web.createDiv({ cls: 'setting-item-description lb-remote-warn', text: '⚠ ' + w });
      };

      // 权限：开放哪些文件夹（对所有连上的 AI 都一样）
      const drawFolders = (box, r) => {
        if (!skipXhs) {
          box.createEl('p', { cls: 'setting-item-description', text: '连上的 AI 能搜、能读这些文件夹里的笔记（含子文件夹）；改完几秒内生效。' });
          xhsToggle(new Setting(box).setName(XHS_LABEL).setDesc('可见笔记，加上每篇的机读版、附件全文、批注（推荐开）。'), tab);
        }
        for (const f of r.folders.filter(f => f !== XHS)) {
          const row = new Setting(box).setName(f).setDesc(isExternal(f) ? '这个库外面的文件夹（AI 看到的是 @ext/<文件夹名>/…）' : '这个库里的文件夹');
          row.settingEl.addClass('lb-connect-folder');
          row.addExtraButton(b => b.setIcon('trash').setTooltip('不再开放').onClick(async () => {
            await saveRemote(x => { x.folders = x.folders.filter(y => y !== f); });
            new Notice('已不再开放「' + f + '」'); redraw();
          }));
        }
        const pick = new Setting(box).setName('再开放一个文件夹').setDesc('库里的点「从库内选…」；库外的点「选本机文件夹…」。');
        help(pick, '对话框弹不出来时，把文件夹路径粘到右边的框里点「添加」。');
        pick.settingEl.addClass('lb-connect-pick');
        let manual = null;
        pick.addButton(b => b.setButtonText('从库内选…').onClick(async () => { const rel = await pickVaultFolder(); if (rel) await addFolder(rel, redraw); }));
        pick.addButton(b => b.setButtonText('选本机文件夹…').onClick(async () => {
          b.setDisabled(true);
          try { const p = await pickFolder(); if (p) await addFolder(p, redraw); else if (p === null && manual) manual.inputEl.focus(); }
          finally { b.setDisabled(false); }
        }));
        pick.addText(t => {
          manual = t; t.setPlaceholder('或粘贴路径：D:\\笔记\\读书'); if (typed.manual) t.setValue(typed.manual); t.inputEl.style.width = '13em';
          if (t.inputEl.setAttribute) t.inputEl.setAttribute('data-lb-key', 'manual');
          if (t.inputEl.addEventListener) t.inputEl.addEventListener('input', () => { typed.manual = t.inputEl.value; });
        });
        pick.addButton(b => b.setButtonText('添加').onClick(() => addFolder(manual && manual.inputEl.value, () => { delete typed.manual; redraw(); })));
      };

      const loadStatus = async () => {
        try { const { json } = await run(['status', ...settingsArgs()], { timeoutMs: 30000, fallback: '读不到状态' }); status = json || { unreadable: true, error: '后台没有返回' }; }
        catch (e) { status = { unreadable: true, error: e.message }; }
      };
      // 卡片版（toggleHost）关着时不去读远程状态（打开开关那一下才读）：设置页打开少起一个后台
      syncFromDisk().then(() => { if (!alive) return; draw(); if (part === 'folders' || (headToggle && !s().enabled)) return;
        loadStatus().then(() => redraw()); }, () => draw());
      return () => { alive = false; };
    },

    // 小红书收藏库那一个开关（设置页⑤常露「开放收藏库」也用它）：开 / 关只改 remote.folders 里的 @xhs，存失败拨回
    xhsToggle(row, tab = null) { return xhsToggle(row, tab); },

    // —— 「连接其他 AI」最下面的「高级」：端口 · 访问令牌 · 撤销全部 · 访问记录（也单独导出给单测）——
    renderAdvanced(container, tab = null) { renderAdvancedInto(container, tab); },
  };
};

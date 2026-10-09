// 连接 AI（1009 她：连几个 MCP 要看好几个地方 → 一个模块）——设置页「连接 AI」这一节的全部界面 + 「高级 → 远程服务」。
// main.js 只有几处接入：
//   onload：this.remoteUI = require(<插件目录>/remote-ui.js)(obsidian, this); await this.remoteUI.attach();
//   saveSettings：保存前 await this.remoteUI.beforeSave()（remote 段以磁盘为准，见下）
//   设置页：this.plugin.remoteUI?.renderConnect(c, redraw)；高级里 this.plugin.remoteUI?.renderAdvanced(c, redraw)
// 选要连的客户端（Claude Code / Claude Desktop / claude.ai / ChatGPT / 其他 MCP 客户端，可多选，存 settings.connect.clients），每个一步：
//   · 本机的（Claude Code / Claude Desktop）：一键写配置（`connect add`，写前备份、写完报结果、可「撤销」= `connect remove`）；
//   · 网页的（claude.ai / ChatGPT）：一屏给全——远程服务开没开、域名、连接地址（复制）、口令（复制 / 随机生成）、几步做法；
//   · 其他：本机 JSON 片段（复制）+ 远程地址；不支持 OAuth 的到「高级 → 远程服务」生成访问令牌。
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
const XHS_LABEL = '小红书收藏库（可见笔记 + 每篇的机读版、附件全文、批注）';
const DOMAIN_RE = /^https:\/\/([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const DOCS_URL = 'https://github.com/CyberMist123/light-web-archieve/blob/main/docs/remote-access.md';
// 「连接 AI」的客户端（id → 名字 / 本机还是网页）
const CLIENTS = [['claude-code', 'Claude Code', 'local'], ['claude-desktop', 'Claude Desktop', 'local'], ['claude-ai', 'claude.ai', 'web'],
  ['chatgpt', 'ChatGPT', 'web'], ['other', '其他 MCP 客户端', 'other']];
const WEB_STEPS = {
  'claude-ai': ['claude.ai（网页 / 手机 App）：设置 → Connectors → Add custom connector，名字填 LWA，URL 粘「连接地址」，点 Add。',
    '点 Connect，会打开本机服务的授权页：粘贴口令 →「允许连接」，自动跳回就连上了。',
    '聊天里在工具菜单打开 LWA，说「在我的收藏里搜……」试一句。'],
  chatgpt: ['ChatGPT：设置 → Apps & Connectors → Advanced settings 打开 Developer mode。',
    '回到 Apps & Connectors → Create：名字 LWA，MCP Server URL 粘「连接地址」，Authentication 选 OAuth，勾「我信任这个应用」，Create。',
    '弹出授权页：粘贴口令 →「允许连接」。新对话里在 + → 更多 选上 LWA 再提问。'],
};

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

// 「连接 AI」勾了哪些客户端：存过就用存的；没存过 = 远程服务开着就先勾网页那两个，否则都不勾
function chosenClients(settings) {
  const saved = settings && settings.connect && Array.isArray(settings.connect.clients) ? settings.connect.clients : null;
  if (saved) return saved.filter(id => CLIENTS.some(c => c[0] === id));
  return settings && settings.remote && settings.remote.enabled ? ['claude-ai', 'chatgpt'] : [];
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
    new TextModal('设置远程 MCP 口令', (el, modal) => {
      el.createEl('p', { cls: 'setting-item-description', text: 'claude.ai / ChatGPT 第一次连接时会打开一个授权页，要输这个口令。至少 8 个字符。'
        + '验证只用哈希；另存一份用 Windows 账户加密的副本（~/.link-brain/remote，不进插件设置、不进仓库），供「复制口令」用。'
        + '改口令不影响已经连上的客户端；要让某个客户端重新授权，在「已连接」里吊销它。' });
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
      el.createEl('p', { text: '只显示这一次，关掉就看不到了。请现在复制，放进客户端的请求头：Authorization: Bearer <令牌>。' });
      const code = el.createEl('code', { text: token }); code.style.cssText = 'display:block;word-break:break-all;user-select:all;padding:8px;';
      new Setting(el).addButton(b => b.setButtonText('复制').setCta().onClick(() => copy(token, '访问令牌')))
        .addButton(b => b.setButtonText('关闭').onClick(() => modal.close()));
    }).open();
  }
  function showManual(command) {
    new TextModal('这台电脑要手动启动', (el, modal) => {
      el.createEl('p', { text: '不是 Windows，没法自动注册后台服务。开关已打开；请在终端运行下面这条命令（可以交给 launchd / systemd 开机自启）：' });
      const code = el.createEl('code', { text: command }); code.style.cssText = 'display:block;word-break:break-all;user-select:all;padding:8px;';
      new Setting(el).addButton(b => b.setButtonText('复制').setCta().onClick(() => copy(command, '命令')))
        .addButton(b => b.setButtonText('关闭').onClick(() => modal.close()));
    }).open();
  }

  // 远程服务开 / 关（网页客户端那一步里用；先存开关再调 enable，注册失败开关退回去）
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

  return {
    REMOTE_DEFAULTS, normalizeRemote, cleanDomain, accessLine, isExternal, chosenClients, vaultRelative, CLIENTS, pickFolder, addFolder,

    // onload：data.json 里的 remote 段挂到 settings 上（mergeSettings 只认 DEFAULT_SETTINGS 的键，不挂会在下次保存时丢）
    async attach() { await syncFromDisk(); },

    // 插件任何一次保存前调：remote 段以磁盘为准（除非这一页刚经 saveRemote 改过）
    async beforeSave() { if (!fresh) await syncFromDisk(); },

    // —— 设置页「连接 AI」——
    renderConnect(container, redrawAll) {
      if (!plugin.settings.remote) plugin.settings.remote = normalizeRemote(null);
      const box = container.createDiv({ cls: 'lb-connect' });
      let alive = true;
      const redraw = async () => { if (!alive) return; await syncFromDisk(); box.empty(); draw(); };
      let status = null, local = null;   // 后端回来的：remote status / connect status

      const draw = () => {
        const r = s();
        const url = r.domain ? r.domain + '/mcp' : '';
        box.createEl('h3', { text: '连接 AI' });
        box.createEl('p', { cls: 'setting-item-description', text: '让别的 AI 读你的收藏：搜索、阅读、看图、星标主题、问收藏（会花模型钱）。勾上要连的，每个只要一步；不能改动或删除收藏本身。' });
        const chips = box.createDiv({ cls: 'lb-connect-chips' });
        const picked = new Set(chosenClients(plugin.settings));
        for (const [id, name] of CLIENTS) {
          const lab = chips.createEl('label', { cls: 'lb-connect-chip' + (picked.has(id) ? ' is-on' : ''), attr: { 'data-client': id } });
          const cb = lab.createEl('input', { type: 'checkbox' }); cb.type = 'checkbox'; cb.checked = picked.has(id);
          lab.createSpan({ text: name });
          cb.onchange = async () => {
            const next = new Set(chosenClients(plugin.settings));
            if (cb.checked) next.add(id); else next.delete(id);
            plugin.settings.connect = { ...(plugin.settings.connect || {}), clients: CLIENTS.map(c => c[0]).filter(x => next.has(x)) };
            await plugin.saveSettings(); redraw();
          };
        }
        if (!picked.size) box.createEl('p', { cls: 'setting-item-description', text: '上面勾一个，这里就出它的那一步。' });

        // 本机的：一键写配置 / 撤销
        for (const [id, name] of CLIENTS.filter(c => c[2] === 'local' && picked.has(c[0]))) {
          const row = new Setting(box).setName(name);
          row.settingEl.addClass('lb-connect-client'); row.settingEl.setAttribute?.('data-client', id);
          const st = local && local.clients ? local.clients[id] : null;
          const note = row.descEl.createDiv({ cls: 'lb-connect-note' });
          const set = text => note.setText(text);
          if (!local) set('读取中…');
          else if (st && st.connected) set('✓ 已接上（工具名以 lwa 开头）' + (id === 'claude-desktop' ? '。改了要完全退出 Claude Desktop 再打开' : '。重开 Claude Code 生效'));
          else if (st && !st.installed) set(id === 'claude-code' ? '没找到 claude 命令：装好 Claude Code 再点；或复制命令到终端运行' : '没找到 Claude Desktop：装好并打开过一次再点');
          else set(id === 'claude-code' ? '点一下就写进 Claude Code 的用户级配置（写前备份，可撤销）' : '点一下就写进 Claude Desktop 的配置（写前备份，可撤销）');
          if (st && st.connected) row.addButton(b => b.setButtonText('撤销').onClick(async () => {
            b.setDisabled(true);
            const res = await connectCmd(['remove', id], '没撤掉');
            if (res.ok) new Notice(res.message || '已撤掉');
            await loadLocal(); redraw();
          }));
          else row.addButton(b => b.setButtonText('一键接上').setCta().setDisabled(!!local && !!st && !st.installed && id === 'claude-desktop').onClick(async () => {
            b.setDisabled(true); set('正在写配置…');
            const res = await connectCmd(['add', id], '');
            if (res.ok) {
              plugin.notify(res.message || '已接上', { kind: 'ok', actions: res.changed ? [{ label: '撤销', run: async () => {
                const undo = await connectCmd(['remove', id], '没撤掉'); if (undo.ok) new Notice(undo.message || '已撤掉'); await loadLocal(); redraw();
              } }] : null });
            } else if (res.command) {
              set((res.message || '没接上') + '：');
              row.descEl.createEl('code', { cls: 'lb-connect-cmd', text: res.command });
            } else new Notice('没接上：' + (res.message || '没有原因'), 10000);
            await loadLocal(); if (res.ok || !res.command) redraw(); else b.setDisabled(false);
          }));
          if (id === 'claude-code' && st && st.command && !st.connected) row.addExtraButton(b => b.setIcon('copy').setTooltip('复制命令（自己到终端运行）').onClick(() => copy(st.command, ' Claude Code 命令')));
        }

        // 网页的：远程服务 + 域名 + 连接地址 + 口令 + 几步
        const webPicked = CLIENTS.filter(c => c[2] === 'web' && picked.has(c[0]));
        if (webPicked.length || picked.has('other')) {
          const web = box.createDiv({ cls: 'lb-connect-web' });
          const svc = new Setting(web).setName('远程服务').setDesc(status ? ((status.state === 'running' ? '● ' : status.state === 'error' ? '✗ 出错：' : '○ ') + (status.message || status.state)) : '读取中…');
          svc.addToggle(t => t.setValue(r.enabled).onChange(async v => { t.setDisabled(true); svc.setDesc(v ? '正在注册并启动后台服务（十几秒）…' : '正在停止…'); await setEnabled(v); await loadStatus(); redraw(); }));
          if (status && status.state === 'error') svc.descEl.addClass?.('mod-warning');
          const dom = new Setting(web).setName('域名').setDesc(r.domain ? '' : '填 https://主机名（不带路径）。还没有？看「高级 → 远程服务」里的教程（Cloudflare 命名隧道 / Tailscale Funnel）。')
            .addText(t => {
              t.setPlaceholder('https://lwa.example.com').setValue(r.domain || '');
              t.inputEl.style.width = '16em';
              t.inputEl.addEventListener('change', async () => {
                const v = cleanDomain(t.inputEl.value);
                if (v === null) { new Notice('域名格式不对：只填 https://主机名，不带端口和路径', 8000); return; }
                await saveRemote(x => { x.domain = v; });
                new Notice(v ? '域名已保存' + (r.enabled ? '，几秒内生效' : '') : '已清空域名：只有本机能连'); redraw();
              });
            });
          dom.settingEl.addClass('lb-remote-domain');
          if (r.domain) dom.addButton(b => b.setButtonText('测试公网').onClick(async () => {
            b.setDisabled(true); dom.setDesc('正在从外面绕一圈：域名 → 隧道 → 本机服务…');
            let j = null;
            try { ({ json: j } = await run(['probe', ...settingsArgs()], { timeoutMs: 30000, fallback: '测不了' })); } catch (e) { j = { ok: false, message: e.message }; }
            dom.setDesc((j && j.ok ? '✓ ' : '✗ ') + ((j && j.message) || '没有结果')); b.setDisabled(false);
          }));
          new Setting(web).setName('连接地址').setDesc(url || '先填上面的域名。')
            .addButton(b => b.setButtonText('复制').setCta().setDisabled(!url).onClick(() => copy(url, '连接地址')));
          const auth = (status && status.auth) || {};
          const pass = new Setting(web).setName('口令').setDesc(!status ? '读取中…' : auth.passphrase_set
            ? (auth.passphrase_copyable ? '授权页要输它：点「复制口令」。' : '这个口令是旧版设的、取不回来：点「随机生成」重设一次，以后就能复制。')
            : '还没设：点「随机生成」最省事（生成即复制）。');
          pass.addButton(b => b.setButtonText('复制口令').setDisabled(!(auth.passphrase_set && auth.passphrase_copyable)).onClick(async () => {
            const j = await act(['passphrase', '--reveal'], '没取回口令');
            if (j.ok && j.passphrase) await copy(j.passphrase, '口令');
          }));
          pass.addButton(b => b.setButtonText('随机生成').onClick(async () => {
            const go = async () => { const j = await act(['passphrase', '--generate'], '没生成出来'); if (j.ok && j.passphrase) { await copy(j.passphrase, '新口令（已保存）'); await loadStatus(); redraw(); } };
            if (auth.passphrase_set) await confirmModal('换一个随机口令？', '旧口令立即作废（已连上的客户端不受影响）。新口令会自动复制到剪贴板。', '生成并复制', go);
            else await go();
          }));
          pass.addButton(b => b.setButtonText(auth.passphrase_set ? '修改口令' : '设置口令').onClick(() => passphraseModal(async () => { await loadStatus(); redraw(); })));
          for (const [id, name] of webPicked) {
            const how = web.createDiv({ cls: 'lb-connect-howto setting-item-description', attr: { 'data-client': id } });
            how.createEl('div', { cls: 'setting-item-name', text: name + ' 怎么连' });
            const ol = how.createEl('ol'); for (const l of WEB_STEPS[id]) ol.createEl('li', { text: l });
          }
          if (picked.has('other')) {
            const other = new Setting(web).setName('其他 MCP 客户端').setDesc('本机的（Cursor、Codex 等）：复制 JSON 粘进它的 MCP 配置；远程的：用上面的连接地址，支持 OAuth 就走口令，不支持的到「高级 → 远程服务」生成访问令牌。');
            other.addButton(b => b.setButtonText('复制 JSON').setDisabled(!local || !local.json).onClick(() => copy(local.json, ' JSON 配置')));
          }
          const clients = auth.clients || [];
          if (clients.length) {
            web.createDiv({ cls: 'setting-item-name lb-remote-sub', text: '已连接的网页客户端' });
            for (const c of clients) new Setting(web).setName('　' + c.name)
              .setDesc('连上于 ' + fmtTime(c.connected_at) + (c.last_used ? ' · 最近使用 ' + fmtTime(c.last_used) : ''))
              .addButton(b => b.setButtonText('吊销').onClick(() => confirmModal('吊销「' + c.name + '」？', '它的访问立即失效，要重新授权才能再连。', '吊销', async () => {
                const res = await act(['client', 'revoke', c.id], '没吊销成功');
                if (res.ok) new Notice('已吊销「' + c.name + '」');
                await loadStatus(); redraw();
              })));
          }
          for (const w of (status && status.warnings) || []) web.createDiv({ cls: 'setting-item-description lb-remote-warn', text: '⚠ ' + w });
        }

        // 权限：开放哪些文件夹（对所有连上的 AI 都一样）
        box.createEl('h4', { text: '开放给 AI 的文件夹' });
        box.createEl('p', { cls: 'setting-item-description', text: '开放了的，连上的 AI 能搜索、阅读里面的文本文件（.md / .txt，含子文件夹）。.obsidian、隐藏文件夹、插件设置、密钥、数据库和日志永远不开放。改完几秒内生效。' });
        const have = new Set(r.folders);
        new Setting(box).setName(XHS_LABEL).setDesc('收藏库本体（推荐开）')
          .addToggle(t => t.setValue(have.has(XHS)).onChange(async v => {
            await saveRemote(x => { x.folders = v ? [...new Set([...x.folders, XHS])] : x.folders.filter(f => f !== XHS); });
            new Notice((v ? '已开放' : '已不再开放') + '小红书收藏库' + (s().enabled ? '，几秒内生效' : ''));
          }));
        for (const f of r.folders.filter(f => f !== XHS)) {
          const row = new Setting(box).setName(f).setDesc(isExternal(f) ? '库外文件夹（AI 看到的是 @ext/<文件夹名>/…）' : '库里的文件夹');
          row.settingEl.addClass('lb-connect-folder');
          row.addExtraButton(b => b.setIcon('trash').setTooltip('不再开放').onClick(async () => {
            await saveRemote(x => { x.folders = x.folders.filter(y => y !== f); });
            new Notice('已不再开放「' + f + '」'); redraw();
          }));
        }
        const pick = new Setting(box).setName('再开放一个文件夹').setDesc('库里的从「从库内选…」搜；库外的点「选本机文件夹…」弹系统对话框。对话框弹不出来就把路径粘到框里点「添加」。');
        pick.settingEl.addClass('lb-connect-pick');
        let manual = null;
        pick.addButton(b => b.setButtonText('从库内选…').onClick(async () => { const rel = await pickVaultFolder(); if (rel) await addFolder(rel, redraw); }));
        pick.addButton(b => b.setButtonText('选本机文件夹…').onClick(async () => {
          b.setDisabled(true);
          try { const p = await pickFolder(); if (p) await addFolder(p, redraw); else if (p === null && manual) manual.inputEl.focus(); }
          finally { b.setDisabled(false); }
        }));
        pick.addText(t => { manual = t; t.setPlaceholder('或粘贴路径：D:\\笔记\\读书'); t.inputEl.style.width = '13em'; });
        pick.addButton(b => b.setButtonText('添加').onClick(() => addFolder(manual && manual.inputEl.value, redraw)));
      };

      const loadStatus = async () => {
        try { const { json } = await run(['status', ...settingsArgs()], { timeoutMs: 30000, fallback: '读不到状态' }); status = json || { state: 'error', message: '读不到状态' }; }
        catch (e) { status = { state: 'error', message: '读不到状态：' + e.message }; }
      };
      const loadLocal = async () => {
        try { const { json } = await plugin.runPy(['-m', 'link_brain', 'connect', 'status'], { label: '连接 AI', timeoutMs: 60000 }); local = json || { clients: {} }; }
        catch (e) { local = { clients: {}, error: e.message }; }
      };
      syncFromDisk().then(() => { if (!alive) return; draw(); Promise.all([loadStatus(), loadLocal()]).then(() => redraw()); }, () => draw());
      return () => { alive = false; };
    },

    // —— 高级 → 远程服务：端口 · 访问令牌 · 最近访问 · 撤销全部 · 还没有域名？——
    renderAdvanced(container) {
      if (!plugin.settings.remote) plugin.settings.remote = normalizeRemote(null);
      const box = container.createDiv({ cls: 'lb-remote-adv' });
      const redraw = async () => { await syncFromDisk(); box.empty(); draw(); };
      const draw = () => {
        const r = s();
        const st = new Setting(box).setName('远程服务状态').setDesc('读取中…');
        st.addExtraButton(b => b.setIcon('refresh-cw').setTooltip('刷新').onClick(() => redraw()));
        new Setting(box).setName('端口').setDesc('本机监听端口（1024–65535）。改了会自动重启服务；隧道那头也要跟着改。')
          .addText(t => {
            t.setValue(String(r.port));
            t.inputEl.addEventListener('change', async () => {
              const p = parseInt(t.inputEl.value, 10);
              if (!(p >= 1024 && p <= 65535)) { new Notice('端口要在 1024–65535 之间', 8000); t.setValue(String(r.port)); return; }
              if (p === r.port) return;
              await saveRemote(x => { x.port = p; });
              if (s().enabled) { const res = await act(['restart'], '端口已保存，但服务没重启上'); if (res.ok) new Notice('端口已改成 ' + p + '，服务已重启'); }
              else new Notice('端口已保存');
              redraw();
            });
          });
        const tokSet = new Setting(box).setName('给其他客户端的访问令牌')
          .setDesc('不支持 OAuth 的客户端用：请求头带 Authorization: Bearer <令牌>。令牌只在生成时显示一次。');
        let label = '';
        tokSet.addText(t => t.setPlaceholder('备注（可选）').onChange(v => label = v));
        tokSet.addButton(b => b.setButtonText('生成').onClick(async () => {
          b.setDisabled(true);
          const res = await act(['token', 'new', '--label', label || '访问令牌'], '没生成出来');
          b.setDisabled(false);
          if (res.ok && res.token) showToken(res.token);
          redraw();
        }));
        const tokBox = box.createDiv();
        new Setting(box).setName('撤销全部访问').setDesc('所有已连接的客户端和访问令牌立即失效，都要重新授权。口令不变。')
          .addButton(b => b.setButtonText('撤销全部').setWarning().onClick(() => confirmModal('撤销全部访问？',
            '撤销后，claude.ai / ChatGPT 等所有已连接的客户端、所有访问令牌立即失效，要重新授权才能再连。口令不变。', '撤销全部', async () => {
              const res = await act(['revoke-all'], '没撤销成功');
              if (res.ok) new Notice(res.message || '已撤销全部访问');
              redraw();
            })));
        const taskLine = box.createEl('p', { cls: 'setting-item-description' });
        box.createDiv({ cls: 'setting-item-name', text: '最近访问' }).style.marginTop = '12px';
        const recent = box.createDiv({ cls: 'setting-item-description lb-remote-recent' });
        recent.setText('读取中…');
        const nd = box.createEl('details', { cls: 'lb-remote-nodomain' });
        nd.createEl('summary', { text: '还没有域名？' });
        const ndb = nd.createDiv({ cls: 'setting-item-description' });
        ndb.createEl('p', { text: '最省事：已有一个托管在 Cloudflare 的域名 → 建一条命名隧道（cloudflared），把子域名指到 http://127.0.0.1:' + r.port + '，再把 https://子域名 填到「连接 AI」里。'
          + '没有域名：Tailscale Funnel 能给你一个固定的 https://<机器名>.<tailnet>.ts.net。不推荐 trycloudflare 临时地址：每次重启都换网址，已连的客户端全要重连。' });
        new Setting(ndb).setName('图文教程').setDesc('docs/remote-access.md：命名隧道 + 已有域名 / Tailscale Funnel / 常见报错。')
          .addButton(b => b.setButtonText('打开本机文档').onClick(async () => {
            const p = plugin.repoRoot ? require('path').join(plugin.repoRoot, 'docs', 'remote-access.md') : null;
            const err = p ? await require('electron').shell.openPath(p) : 'no repo';
            if (err) window.open(DOCS_URL);
          }))
          .addButton(b => b.setButtonText('在 GitHub 看').onClick(() => window.open(DOCS_URL)));
        (async () => {
          let j = null;
          try { ({ json: j } = await run(['status', ...settingsArgs()], { timeoutMs: 30000, fallback: '读不到状态' })); }
          catch (e) { st.setDesc('读不到状态：' + e.message); recent.setText(''); return; }
          if (!j) { st.setDesc('读不到状态'); recent.setText(''); return; }
          st.setDesc((j.state === 'running' ? '● ' : j.state === 'error' ? '✗ 出错：' : '○ ') + (j.message || j.state));
          const t = j.task || {};
          taskLine.setText('后台服务：计划任务 ' + (t.name || 'LwaMcp') + (t.registered ? '（' + (t.state || '已注册') + (t.last_run ? '，上次启动 ' + fmtTime(t.last_run) : '') + '）' : t.supported === false ? '（非 Windows：手动启动）' : '（没注册）')
            + ' · 设置文件 ' + (j.settings_path || ''));
          for (const p of (j.auth || {}).personal || []) new Setting(tokBox).setName('　' + (p.label || '访问令牌'))
            .setDesc('生成于 ' + fmtTime(p.created) + (p.last_used ? ' · 最近使用 ' + fmtTime(p.last_used) : ' · 还没用过'))
            .addButton(b => b.setButtonText('撤销').onClick(async () => {
              const res = await act(['token', 'revoke', p.id], '没撤销成功');
              if (res.ok) new Notice('已撤销「' + (p.label || '访问令牌') + '」');
              redraw();
            }));
          recent.empty();
          const rows = j.recent || [];
          if (!rows.length) recent.setText('还没有访问记录。');
          for (const row of rows.slice(0, 20)) recent.createDiv({ text: accessLine(row) });
        })();
      };
      syncFromDisk().then(draw, draw);
    },
  };
};

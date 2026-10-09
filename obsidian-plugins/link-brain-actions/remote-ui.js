// 远程 MCP（LWA MCP over HTTP）——设置页这一节的全部界面（第 6 批；10-09 重排成分组折叠）。main.js 只有三处接入：
//   onload：this.remoteUI = require(<插件目录>/remote-ui.js)(obsidian, this); await this.remoteUI.attach();
//   saveSettings：保存前 await this.remoteUI.beforeSave()（remote 段以磁盘为准，见下）
//   设置页「远程」分页末尾：this.plugin.remoteUI?.render(c, () => this.display());
// 服务本体是独立后台进程（python -m link_brain remote serve，Windows 上由计划任务 LwaMcp 常驻），
// 不挂在 Obsidian 下：关掉 Obsidian 照常可连。这里只做：改 data.json 的 remote 段 + 经 runPy 调 `remote <子命令>`。
// 口令 / 令牌不经过 data.json：口令走 stdin 交给 Python（哈希 + DPAPI 副本存 ~/.link-brain/remote），令牌只在生成时显示一次。
//
// 10-09 根因修复：remote 段的唯一来源是磁盘上的 data.json。以前插件把 remote 段攥在内存里，别的设置一保存就把
// 内存里的旧值（比如空域名）整份写回去，盖掉了在别处（命令行 / 另一个窗口）改好的域名。现在：
//   · 任何一次保存前（beforeSave）先从磁盘重读 remote 段，内存里的只当缓存；
//   · 这一页自己改 remote 时走 saveRemote(改法)：先读磁盘最新值、只改这一处、再写回。
// CONVENTIONS §1：每个操作如实提示结果（成功说做了什么，失败带原因）；状态只显示后端给的。
'use strict';

// 必须和 link_brain/remote/config.py 的 DEFAULTS 一致（tests/test_remote_cli.py 核对），改一处改两处。
const REMOTE_DEFAULTS = {"enabled": false, "domain": "", "port": 18071, "folders": ["@xhs"]};
const XHS = '@xhs';
const XHS_LABEL = '小红书收藏库（可见笔记 + 每篇的机读版、附件全文、批注）';
const DOMAIN_RE = /^https:\/\/([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const DOCS_URL = 'https://github.com/CyberMist123/light-web-archieve/blob/main/docs/remote-access.md';

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

module.exports = function remoteUI(obsidian, plugin) {
  const { Setting, Notice, Modal } = obsidian;
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

  class TextModal extends Modal {
    constructor(title, build) { super(plugin.app); this.title = title; this.build = build; }
    onOpen() { this.contentEl.empty(); this.contentEl.createEl('h3', { text: this.title }); this.build(this.contentEl, this); }
    onClose() { this.contentEl.empty(); }
  }

  function passphraseModal(done) {
    new TextModal('设置远程 MCP 口令', (el, modal) => {
      el.createEl('p', { cls: 'setting-item-description', text: 'claude.ai / ChatGPT 第一次连接时会打开一个授权页，要输这个口令。至少 8 个字符。'
        + '验证只用哈希；另存一份用 Windows 账户加密的副本（~/.link-brain/remote，不进插件设置、不进仓库），供「复制口令」用。'
        + '改口令不影响已经连上的客户端；要让某个客户端重新授权，在「状态」里吊销它。' });
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

  // 选一个本机文件夹：Electron 对话框 → 退回 PowerShell 的 FolderBrowserDialog → 都不行返回 null（让她手填）
  async function pickFolder() {
    try {
      const electron = require('electron');
      const remote = electron.remote || (() => { try { return require('@electron/remote'); } catch { return null; } })();
      if (remote && remote.dialog) {
        const r = await remote.dialog.showOpenDialog({ properties: ['openDirectory'] });
        return r && !r.canceled && r.filePaths && r.filePaths[0] ? r.filePaths[0] : null;
      }
    } catch (e) { console.warn('[lb] Electron 文件夹对话框不可用', e); }
    if (process.platform !== 'win32') return null;
    const script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;Add-Type -AssemblyName System.Windows.Forms;"
      + "$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description='选一个要开放给远程 MCP 的文件夹';"
      + "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){$d.SelectedPath}";
    return await new Promise(resolve => {
      const child = require('child_process').spawn('powershell.exe', ['-NoProfile', '-STA', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], { windowsHide: true });
      let out = ''; child.stdout.on('data', d => out += d.toString('utf8'));
      child.on('error', () => resolve(null));
      child.on('close', () => resolve(out.trim() || null));
    });
  }

  return {
    REMOTE_DEFAULTS, normalizeRemote, cleanDomain, accessLine, isExternal,

    // onload：data.json 里的 remote 段挂到 settings 上（mergeSettings 只认 DEFAULT_SETTINGS 的键，不挂会在下次保存时丢）
    async attach() { await syncFromDisk(); },

    // 插件任何一次保存前调：remote 段以磁盘为准（除非这一页刚经 saveRemote 改过）
    async beforeSave() { if (!fresh) await syncFromDisk(); },

    render(container, redrawAll) {
      if (!plugin.settings.remote) plugin.settings.remote = normalizeRemote(null);
      const box = container.createDiv({ cls: 'lb-remote' });
      const openState = { status: true, connect: true };   // 重画时保持各组的折叠状态
      const redraw = async () => { await syncFromDisk(); box.empty(); draw(); };
      const group = (key, title, defaultOpen = false) => {
        const d = box.createEl('details', { cls: 'lb-remote-group' });
        d.open = key in openState ? openState[key] : defaultOpen;
        d.addEventListener('toggle', () => { openState[key] = d.open; });
        d.createEl('summary', { text: title });
        return d.createDiv({ cls: 'lb-remote-body' });
      };

      const draw = () => {
        const r = s();
        const url = r.domain ? r.domain + '/mcp' : '';
        box.createEl('h4', { text: '远程 MCP（claude.ai / ChatGPT 连你的收藏库）' });
        box.createEl('p', { cls: 'setting-item-description', text: '让 claude.ai、ChatGPT 或任何能连远程 MCP 的 AI 搜索和阅读你的收藏、写星标主题和暗号、调用「问收藏」（会花模型钱）。'
          + '共 9 个工具，不能改动或删除收藏本身。服务在本机后台运行、只监听 127.0.0.1:' + r.port + '，关掉 Obsidian 也照常可连；公网要靠你自己的域名 + 隧道接进来。' });

        // ===== 状态 =====
        const g1 = group('status', '状态', true);
        const st = new Setting(g1).setName('服务').setDesc('读取中…');
        st.addExtraButton(b => b.setIcon('refresh-cw').setTooltip('刷新').onClick(() => redraw()));
        new Setting(g1).setName('启用').setDesc('开启 = 注册并启动后台服务（Windows 计划任务 LwaMcp：登录时启动，意外退出 5 分钟内自动拉起）；关闭 = 停止并删除它。')
          .addToggle(t => t.setValue(r.enabled).onChange(async v => {
            t.setDisabled(true);
            st.setDesc(v ? '正在注册并启动后台服务（十几秒）…' : '正在停止…');
            await saveRemote(x => { x.enabled = v; });
            if (v) {
              const res = await act(['enable', ...settingsArgs()], '没启用上');
              if (res.ok) new Notice(res.message || '已启用');
              else if (res.code === 'SKIPPED.NOT_CONFIGURED' && res.command) showManual(res.command);   // 非 Windows：开关留着，手动起
              else await saveRemote(x => { x.enabled = false; });                                       // 没注册上：开关退回去，原因已提示
            } else {
              const res = await act(['disable'], '没停干净');
              if (res.ok) new Notice(res.message || '已停用');
            }
            redraw();
          }));
        const pub = new Setting(g1).setName('公网').setDesc(r.domain ? '没测过。点「测试公网」从外面绕一圈：域名 → 隧道 → 本机服务。' : '没填域名：现在只有本机能连。到「连接」里填域名。');
        pub.addButton(b => b.setButtonText('测试公网').setDisabled(!r.domain).onClick(async () => {
          b.setDisabled(true); pub.setDesc('正在请求 ' + r.domain + '/.well-known/oauth-authorization-server …');
          let j = null;
          try { ({ json: j } = await run(['probe', ...settingsArgs()], { timeoutMs: 30000, fallback: '测不了' })); } catch (e) { j = { ok: false, message: e.message }; }
          pub.setDesc((j && j.ok ? '✓ ' : '✗ ') + ((j && j.message) || '没有结果'));
          pub.descEl.toggleClass('mod-warning', !(j && j.ok));
          b.setDisabled(false);
        }));
        const warnBox = g1.createDiv({ cls: 'setting-item-description lb-remote-warn' });
        g1.createDiv({ cls: 'setting-item-name', text: '已连接的客户端' }).style.marginTop = '10px';
        const clientBox = g1.createDiv();
        clientBox.createEl('p', { cls: 'setting-item-description', text: '读取中…' });
        new Setting(g1).setName('撤销全部访问').setDesc('所有已连接的客户端和访问令牌立即失效，都要重新授权。口令不变。')
          .addButton(b => b.setButtonText('撤销全部').setWarning().onClick(() => confirmModal('撤销全部访问？',
            '撤销后，claude.ai / ChatGPT 等所有已连接的客户端、所有访问令牌立即失效，要重新授权才能再连。口令不变。', '撤销全部', async () => {
              const res = await act(['revoke-all'], '没撤销成功');
              if (res.ok) new Notice(res.message || '已撤销全部访问');
              redraw();
            })));

        // ===== 连接 =====
        const g2 = group('connect', '连接（域名 · 连接地址 · 各客户端怎么连）', true);
        const dom = new Setting(g2).setName('域名').setDesc('只填 https://主机名（不带路径），比如 https://lwa.example.com。用你的隧道 / 反代把它接到 127.0.0.1:' + r.port + '。留空 = 只有本机能连。')
          .addText(t => {
            t.setPlaceholder('https://lwa.example.com').setValue(r.domain || '');
            t.inputEl.style.width = '18em';
            t.inputEl.addEventListener('change', async () => {
              const v = cleanDomain(t.inputEl.value);
              if (v === null) { new Notice('域名格式不对：只填 https://主机名，不带端口和路径', 8000); return; }
              await saveRemote(x => { x.domain = v; });
              new Notice(v ? '域名已保存' + (r.enabled ? '，几秒内生效' : '') : '已清空域名：只有本机能连'); redraw();
            });
          });
        dom.settingEl.addClass('lb-remote-domain');
        new Setting(g2).setName('连接地址（填进 claude.ai / ChatGPT）').setDesc(url || '先填上面的域名。')
          .addButton(b => b.setButtonText('复制').setCta().setDisabled(!url).onClick(() => copy(url, '连接地址')));
        if (url) g2.createEl('code', { cls: 'lb-remote-url', text: url });

        const how = g2.createDiv({ cls: 'lb-remote-howto setting-item-description' });
        const block = (title, lines) => { how.createEl('div', { cls: 'setting-item-name', text: title }); const ol = how.createEl('ol'); lines.forEach(l => ol.createEl('li', { text: l })); };
        block('claude.ai（网页 / 手机 App）', ['设置 → Connectors（连接器）→ Add custom connector。',
          '名字随便填（比如 LWA），URL 粘上面复制的连接地址，其他留空，点 Add。',
          '点 Connect：会打开本机服务的授权页，列出将授予的权限。',
          '在授权页的口令框粘贴口令（到下面「口令」点「复制口令」），点「允许连接」，自动跳回 claude.ai 就连上了。',
          '聊天里在工具菜单打开 LWA，说「在我的收藏里搜……」试一句。']);
        block('ChatGPT（网页）', ['设置 → Apps & Connectors → Advanced settings 打开 Developer mode。',
          '回到 Apps & Connectors → Create，名字填 LWA，MCP Server URL 粘连接地址，Authentication 选 OAuth，勾上「我信任这个应用」，Create。',
          '弹出授权页：粘贴口令 →「允许连接」。',
          '新对话里在 + → 更多 里选上 LWA 再提问。']);
        block('本机 Claude Code / Claude 桌面（不用域名、不要口令）', ['走本机 stdio，不经网络：复制下面的命令到终端运行（Claude Code），或把 JSON 粘进 Claude 桌面的 claude_desktop_config.json。',
          '重启客户端，工具名以 lwa 开头。']);
        let argv = null;
        try { argv = plugin.mcpArgv(); } catch { argv = null; }
        if (argv) {
          const quote = p => /\s/.test(p) ? JSON.stringify(p) : p;
          const cc = 'claude mcp add --scope user lwa -- ' + argv.map(quote).join(' ');
          const json = JSON.stringify({ mcpServers: { lwa: { command: argv[0], args: argv.slice(1) } } }, null, 2);
          new Setting(g2).setName('Claude Code 命令').setDesc(cc).addButton(b => b.setButtonText('复制').onClick(() => copy(cc, ' Claude Code 命令')));
          new Setting(g2).setName('Claude 桌面 / 其他客户端（JSON）').setDesc('粘进它们的 MCP 配置。').addButton(b => b.setButtonText('复制').onClick(() => copy(json, ' JSON 配置')));
        }
        g2.createEl('p', { cls: 'setting-item-description', text: '不支持 OAuth 的客户端：到「高级」生成访问令牌，请求头带 Authorization: Bearer <令牌>。' });

        const nd = g2.createEl('details', { cls: 'lb-remote-nodomain' });
        nd.createEl('summary', { text: '还没有域名？' });
        const ndb = nd.createDiv({ cls: 'setting-item-description' });
        ndb.createEl('p', { text: '最省事：已有一个托管在 Cloudflare 的域名 → 建一条命名隧道（cloudflared），把子域名指到 http://127.0.0.1:' + r.port + '，再把 https://子域名 填到上面。'
          + '没有域名：Tailscale Funnel 能给你一个固定的 https://<机器名>.<tailnet>.ts.net。不推荐 trycloudflare 临时地址：每次重启都换网址，已连的客户端全要重连，且不保证可用。' });
        new Setting(ndb).setName('图文教程（懒人版）').setDesc('docs/remote-access.md：命名隧道 + 已有域名 / Tailscale Funnel / 常见报错。')
          .addButton(b => b.setButtonText('打开本机文档').onClick(async () => {
            const p = plugin.repoRoot ? require('path').join(plugin.repoRoot, 'docs', 'remote-access.md') : null;
            const err = p ? await require('electron').shell.openPath(p) : 'no repo';
            if (err) window.open(DOCS_URL);
          }))
          .addButton(b => b.setButtonText('在 GitHub 看').onClick(() => window.open(DOCS_URL)));

        // ===== 权限（开放的文件夹）=====
        const g3 = group('perm', '权限（开放哪些文件夹）');
        g3.createEl('p', { cls: 'setting-item-description', text: '勾选即开放：拿到授权的客户端能搜索、阅读里面的文本文件（.md / .txt，含子文件夹）。'
          + '.obsidian、隐藏文件夹、插件设置、密钥文件、数据库和日志永远不开放；链接 / 联接点不跟随。改完几秒内生效。' });
        const listBox = g3.createDiv({ cls: 'lb-remote-folders' });
        listBox.createEl('p', { cls: 'setting-item-description', text: '读取文件夹…' });
        const addRow = new Setting(g3).setName('添加本机文件夹').setDesc('库外的任意文件夹（不能是整个盘 / 整个用户目录 / 包含库的上级）。');
        let addInput = null;
        addRow.addText(t => { addInput = t; t.setPlaceholder('D:\\笔记\\读书'); t.inputEl.style.width = '14em'; });
        const addPath = async raw => {
          const p = String(raw || '').trim().replace(/[\\/]+$/, '');
          if (!p) return;
          if (!isExternal(p)) { new Notice('要填完整的本机路径（比如 D:\\笔记）；库内文件夹直接在上面勾选', 8000); return; }
          const chk = await act(['folders', '--check', p], '不能开放');
          if (!chk.ok) return;
          await saveRemote(x => { if (!x.folders.includes(p)) x.folders.push(p); });
          new Notice('已开放「' + p + '」' + (s().enabled ? '，几秒内生效' : '')); redraw();
        };
        addRow.addButton(b => b.setButtonText('选择…').onClick(async () => {
          const p = await pickFolder();
          if (p) await addPath(p); else if (addInput) { addInput.inputEl.focus(); new Notice('没选到：可以直接在框里粘贴路径再点「添加」'); }
        }));
        addRow.addButton(b => b.setButtonText('添加').onClick(() => addPath(addInput && addInput.getValue())));

        // ===== 口令 =====
        const g4 = group('pass', '口令（授权页要输的）');
        const pass = new Setting(g4).setName('口令').setDesc('claude.ai / ChatGPT 连接时授权页要输这个口令。读取中…');
        let copyBtn = null, setBtn = null, passSet = false;
        pass.addButton(b => { copyBtn = b; b.setButtonText('复制口令').setDisabled(true).onClick(async () => {
          const j = await act(['passphrase', '--reveal'], '没取回口令');
          if (j.ok && j.passphrase) await copy(j.passphrase, '口令');
        }); });
        pass.addButton(b => b.setButtonText('随机生成').onClick(async () => {
          const go = async () => {
            const j = await act(['passphrase', '--generate'], '没生成出来');
            if (j.ok && j.passphrase) { await copy(j.passphrase, '新口令（已保存）'); redraw(); }
          };
          if (passSet) {
            await confirmModal('换一个随机口令？', '旧口令立即作废（已连上的客户端不受影响）。新口令会自动复制到剪贴板。', '生成并复制', go);
          } else await go();
        }));
        pass.addButton(b => { setBtn = b; b.setButtonText('设置口令').onClick(() => passphraseModal(redraw)); });

        // ===== 高级 =====
        const g5 = group('adv', '高级（端口 · 访问令牌 · 访问记录）');
        new Setting(g5).setName('端口').setDesc('本机监听端口（1024–65535）。改了会自动重启服务；隧道那头也要跟着改。')
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
        const tokSet = new Setting(g5).setName('给其他客户端的访问令牌')
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
        const tokBox = g5.createDiv();
        const taskLine = g5.createEl('p', { cls: 'setting-item-description' });
        g5.createDiv({ cls: 'setting-item-name', text: '最近访问' }).style.marginTop = '12px';
        const recent = g5.createDiv({ cls: 'setting-item-description' });
        recent.style.cssText = 'line-height:1.7;max-height:14em;overflow:auto;';
        recent.setText('读取中…');

        // 文件夹勾选列表：库内一二级 + 已配置的库外路径
        const loadFolders = async () => {
          let j = null;
          try { ({ json: j } = await run(['folders', ...settingsArgs()], { timeoutMs: 30000, fallback: '读不到文件夹列表' })); }
          catch (e) { listBox.empty(); listBox.createEl('p', { cls: 'setting-item-description mod-warning', text: '读不到文件夹列表：' + e.message }); return; }
          listBox.empty();
          const have = new Set(s().folders);
          const toggleRow = (value, name, desc) => new Setting(listBox).setName(name).setDesc(desc || '')
            .addToggle(t => t.setValue(have.has(value)).onChange(async v => {
              await saveRemote(x => { x.folders = v ? [...new Set([...x.folders, value])] : x.folders.filter(f => f !== value); });
              new Notice((v ? '已开放「' : '已不再开放「') + (value === XHS ? '小红书收藏库' : value) + '」' + (s().enabled ? '，几秒内生效' : ''));
            }));
          toggleRow(XHS, XHS_LABEL, '收藏库本体（推荐开）');
          const vaultDirs = (j && j.folders) || [];
          const known = new Set(vaultDirs);
          // 已勾但不在一二级里的库内深层文件夹，也列出来能取消
          for (const f of s().folders) if (f !== XHS && !isExternal(f) && !known.has(f)) vaultDirs.push(f);
          vaultDirs.sort();
          if (vaultDirs.length) listBox.createDiv({ cls: 'setting-item-name lb-remote-sub', text: '库内文件夹' });
          for (const f of vaultDirs) { const row = toggleRow(f, f, ''); if (f.includes('/')) row.settingEl.addClass('lb-remote-depth2'); }
          const ext = (j && j.externals) || [];
          if (ext.length) listBox.createDiv({ cls: 'setting-item-name lb-remote-sub', text: '本机其他文件夹' });
          for (const e of ext) {
            new Setting(listBox).setName(e.path).setDesc(e.ok ? '已开放（客户端看到的是 @ext/<文件夹名>/…）' : '⚠ 没生效：' + e.message)
              .addExtraButton(b => b.setIcon('trash').setTooltip('不再开放').onClick(async () => {
                await saveRemote(x => { x.folders = x.folders.filter(f => f !== e.path); });
                new Notice('已不再开放「' + e.path + '」'); redraw();
              }));
          }
        };

        // 状态一次读回（含计划任务、健康检查、口令、客户端、令牌、最近访问）
        const loadStatus = async () => {
          let j = null;
          try { ({ json: j } = await run(['status', ...settingsArgs()], { timeoutMs: 30000, fallback: '读不到状态' })); }
          catch (e) { st.setDesc('读不到状态：' + e.message); recent.setText(''); clientBox.empty(); return; }
          if (!j) { st.setDesc('读不到状态'); recent.setText(''); clientBox.empty(); return; }
          st.setDesc((j.state === 'running' ? '● ' : j.state === 'error' ? '✗ 出错：' : '○ ') + (j.message || j.state));
          if (j.state === 'error') st.descEl.addClass('mod-warning');
          for (const w of j.warnings || []) warnBox.createDiv({ text: '⚠ ' + w });
          const t = j.task || {};
          taskLine.setText('后台服务：计划任务 ' + (t.name || 'LwaMcp') + (t.registered ? '（' + (t.state || '已注册') + (t.last_run ? '，上次启动 ' + fmtTime(t.last_run) : '') + '）' : t.supported === false ? '（非 Windows：手动启动）' : '（没注册）')
            + ' · 设置文件 ' + (j.settings_path || ''));
          const auth = j.auth || {};
          pass.setDesc('claude.ai / ChatGPT 连接时授权页要输这个口令。' + (auth.passphrase_set
            ? '已设（' + fmtTime(auth.passphrase_set_at) + '）。' + (auth.passphrase_copyable ? '' : '这个口令是旧版设的、取不回来：点「随机生成」或「修改口令」重设一次，以后就能复制。')
            : '还没设：点「随机生成」最省事（生成即复制）。'));
          passSet = !!auth.passphrase_set;
          if (copyBtn) copyBtn.setDisabled(!(auth.passphrase_set && auth.passphrase_copyable));
          if (setBtn) setBtn.setButtonText(auth.passphrase_set ? '修改口令' : '设置口令');
          clientBox.empty();
          const clients = auth.clients || [];
          if (!clients.length) clientBox.createEl('p', { cls: 'setting-item-description', text: '还没有客户端连上。' });
          for (const c of clients) new Setting(clientBox).setName('　' + c.name)
            .setDesc('连上于 ' + fmtTime(c.connected_at) + (c.last_used ? ' · 最近使用 ' + fmtTime(c.last_used) : ''))
            .addButton(b => b.setButtonText('吊销').onClick(() => confirmModal('吊销「' + c.name + '」？', '它的访问立即失效，要重新授权才能再连。', '吊销', async () => {
              const res = await act(['client', 'revoke', c.id], '没吊销成功');
              if (res.ok) new Notice('已吊销「' + c.name + '」');
              redraw();
            })));
          for (const p of auth.personal || []) new Setting(tokBox).setName('　' + (p.label || '访问令牌'))
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
        };
        loadStatus();
        loadFolders();
      };

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
      // 打开这一页时先从磁盘读一次（别信内存里的旧值），再画
      syncFromDisk().then(draw, draw);
    },
  };
};

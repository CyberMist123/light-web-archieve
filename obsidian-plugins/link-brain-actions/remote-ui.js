// 远程阅读（MCP，高级）——设置页这一节的全部界面（第 6 批）。main.js 只有两行接入：
//   onload：this.remoteUI = require(<插件目录>/remote-ui.js)(obsidian, this); await this.remoteUI.attach();
//   设置页「更多」（原「高级设置」）末尾：this.plugin.remoteUI?.render(a, () => this.display());
// 服务本体是独立后台进程（python -m link_brain remote serve，Windows 上由计划任务 LinkBrainRemote 常驻），
// 不挂在 Obsidian 下：关掉 Obsidian 照常可读。这里只做：改 data.json 的 remote 段 + 经 runPy 调 `remote <子命令>`。
// 口令 / 令牌不经过 data.json：口令走 stdin 交给 Python，令牌只在生成时显示一次。
// CONVENTIONS §1：每个操作如实提示结果（成功说做了什么，失败带原因）；状态只显示后端给的。
'use strict';

// 必须和 link_brain/remote/config.py 的 DEFAULTS 一致（tests/test_remote_cli.py 核对），改一处改两处。
const REMOTE_DEFAULTS = {"enabled": false, "domain": "", "port": 18071, "folders": ["@xhs"]};
const XHS = '@xhs';
const XHS_LABEL = '小红书收藏库（可见笔记 + 每篇的机读版、附件全文、批注）';
const DOMAIN_RE = /^https:\/\/([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;

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

function fmtTime(ts) { return ts ? String(ts).replace('T', ' ').slice(5, 16) : ''; }

const ACCESS_TOOL = { search: '搜索', read: '读', read_asset: '看原图', list: '列目录', mcp: '连接', http: '请求',
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
  const run = (args, opts = {}) => plugin.runPy(['-m', 'link_brain', 'remote', ...args], { label: '远程阅读', fallback: '远程阅读命令没有结果', ...opts });
  // 服务读的就是本插件此刻写的那份 data.json（库被联接点挂进别的库时，插件目录不一定在归档 vault 里）
  const settingsArgs = () => {
    try { return ['--settings', require('path').join(plugin.app.vault.adapter.getBasePath(), plugin.manifest.dir, 'data.json')]; }
    catch { return []; }
  };
  const s = () => plugin.settings.remote;
  const save = () => plugin.saveSettings();

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
    new TextModal('设置远程阅读口令', (el, modal) => {
      el.createEl('p', { cls: 'setting-item-description', text: 'GPT 网页版这类客户端第一次连接时，会打开一个授权页，要输这个口令。至少 8 个字符。'
        + '口令只以哈希存在本机（~/.link-brain/remote），不进插件设置文件。改口令不影响已经连上的客户端；要让它们重新授权，点「撤销全部访问」。' });
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

  function confirmModal(title, text, okText, onOk) {
    new TextModal(title, (el, modal) => {
      el.createEl('p', { text });
      new Setting(el)
        .addButton(b => b.setButtonText('取消').onClick(() => modal.close()))
        .addButton(b => b.setButtonText(okText).setWarning().onClick(async () => { modal.close(); await onOk(); }));
    }).open();
  }

  function addFolderModal(redraw) {
    new TextModal('开放一个文件夹', async (el, modal) => {
      el.createEl('p', { cls: 'setting-item-description', text: '从这个库里现有的文件夹里选。只开放里面的文本文件（.md / .txt）；.obsidian、插件设置、密钥文件、数据库和日志永远不开放。' });
      const wait = el.createEl('p', { cls: 'setting-item-description', text: '读取文件夹…' });
      let list = [];
      try { const { json } = await run(['folders'], { fallback: '读不到文件夹列表' }); list = (json && json.folders) || []; wait.remove(); }
      catch (e) { wait.setText('读不到文件夹列表：' + e.message); return; }
      const have = new Set(s().folders);
      const options = (have.has(XHS) ? [] : [[XHS, XHS_LABEL]]).concat(list.filter(f => !have.has(f)).map(f => [f, f]));
      if (!options.length) { el.createEl('p', { text: '没有可以再加的文件夹了。' }); return; }
      let pick = options[0][0];
      new Setting(el).setName('文件夹').addDropdown(d => { options.forEach(([v, l]) => d.addOption(v, l)); d.setValue(pick).onChange(v => pick = v); });
      el.createEl('p', { cls: 'mod-warning', text: '拿到授权的客户端都能读这个文件夹（包括里面的子文件夹）。' });
      new Setting(el)
        .addButton(b => b.setButtonText('取消').onClick(() => modal.close()))
        .addButton(b => b.setButtonText('开放').setWarning().onClick(async () => {
          s().folders = [...s().folders, pick]; await save(); modal.close();
          new Notice('已开放「' + (pick === XHS ? '小红书收藏库' : pick) + '」' + (s().enabled ? '，几秒内生效' : ''));
          redraw();
        }));
    }).open();
  }

  return {
    REMOTE_DEFAULTS, normalizeRemote, cleanDomain, accessLine,

    // onload：data.json 里的 remote 段挂到 settings 上（mergeSettings 只认 DEFAULT_SETTINGS 的键，不挂会在下次保存时丢）
    async attach() {
      let raw = null;
      try { raw = await plugin.loadData(); } catch { raw = null; }
      plugin.settings.remote = normalizeRemote(raw && raw.remote);
    },

    render(container, redrawAll) {
      if (!plugin.settings.remote) plugin.settings.remote = normalizeRemote(null);
      const box = container.createDiv({ cls: 'lb-remote' });
      const redraw = () => { box.empty(); draw(); };
      const draw = () => {
        const r = s();
        box.createEl('h4', { text: '远程阅读（MCP）' });
        box.createEl('p', { cls: 'setting-item-description', text: '让 GPT 网页版，或任何能连远程 MCP 的 AI，只读地搜索和阅读你的收藏（包括机读版和附件全文）。'
          + '服务在本机后台运行、只监听 127.0.0.1，关掉 Obsidian 也照常可读。需要你自备域名，用自己的隧道或反向代理把它接到 127.0.0.1:' + r.port + '；插件不管隧道。' });

        // —— 状态 ——
        const st = new Setting(box).setName('状态').setDesc('读取中…');
        st.addExtraButton(b => b.setIcon('refresh-cw').setTooltip('刷新').onClick(() => redraw()));
        const detail = box.createDiv({ cls: 'setting-item-description' });
        detail.style.cssText = 'margin:-6px 0 10px;line-height:1.7;';

        // —— 开关 ——
        new Setting(box).setName('启用').setDesc('开启 = 注册并启动一个后台服务（Windows 计划任务 LinkBrainRemote：登录时启动，意外退出 5 分钟内自动拉起）；关闭 = 停止并删除它。')
          .addToggle(t => t.setValue(r.enabled).onChange(async v => {
            t.setDisabled(true);
            r.enabled = v; await save();
            if (v) {
              const res = await act(['enable', ...settingsArgs()], '没启用上');
              if (res.ok) new Notice(res.message || '已启用');
              else if (res.code === 'SKIPPED.NOT_CONFIGURED' && res.command) showManual(res.command);   // 非 Windows：开关留着，手动起
              else { r.enabled = false; await save(); }                                                  // 没注册上：开关退回去，原因已提示
            } else {
              const res = await act(['disable'], '没停干净');
              if (res.ok) new Notice(res.message || '已停用');
            }
            redraw();
          }));

        // —— 域名 / 端口 ——
        const dom = new Setting(box).setName('域名').setDesc('只填 https://主机名（不带路径），比如 https://read.example.com。把这个域名经你的隧道或反代接到 127.0.0.1:' + r.port + '。留空 = 只有本机能连。')
          .addText(t => {
            t.setPlaceholder('https://read.example.com').setValue(r.domain || '');
            t.inputEl.addEventListener('change', async () => {
              const v = cleanDomain(t.inputEl.value);
              if (v === null) { new Notice('域名格式不对：只填 https://主机名，不带端口和路径', 8000); return; }
              r.domain = v; await save(); new Notice(v ? '域名已保存' + (r.enabled ? '，几秒内生效' : '') : '已清空域名：只有本机能连'); redraw();
            });
          });
        dom.settingEl.addClass('lb-remote-domain');
        new Setting(box).setName('端口').setDesc('本机监听端口（1024–65535）。改了会自动重启服务。')
          .addText(t => {
            t.setValue(String(r.port));
            t.inputEl.addEventListener('change', async () => {
              const p = parseInt(t.inputEl.value, 10);
              if (!(p >= 1024 && p <= 65535)) { new Notice('端口要在 1024–65535 之间', 8000); t.setValue(String(r.port)); return; }
              if (p === r.port) return;
              r.port = p; await save();
              if (r.enabled) { const res = await act(['restart'], '端口已保存，但服务没重启上'); if (res.ok) new Notice('端口已改成 ' + p + '，服务已重启'); }
              else new Notice('端口已保存');
              redraw();
            });
          });

        // —— 口令 ——
        let passBtn = null;
        const pass = new Setting(box).setName('口令').setDesc('GPT 网页版等走 OAuth 的客户端连接时，授权页要输这个口令。')
          .addButton(b => { passBtn = b; b.setButtonText('设置口令').onClick(() => passphraseModal(redraw)); });

        // —— 文件夹 ——
        box.createEl('div', { cls: 'setting-item-name', text: '开放的文件夹' }).style.marginTop = '12px';
        box.createEl('p', { cls: 'setting-item-description', text: '拿到授权的客户端只能读这里列的内容。.obsidian、插件设置、密钥文件、数据库和日志永远不开放。' });
        if (!r.folders.length) box.createEl('p', { cls: 'setting-item-description', text: '现在一个都没开放：客户端连上也什么都读不到。' });
        r.folders.forEach((f, i) => new Setting(box).setName(f === XHS ? XHS_LABEL : f)
          .addExtraButton(b => b.setIcon('trash').setTooltip('不再开放').onClick(async () => {
            r.folders.splice(i, 1); await save(); new Notice('已不再开放「' + (f === XHS ? '小红书收藏库' : f) + '」'); redraw();
          })));
        new Setting(box).addButton(b => b.setButtonText('添加文件夹').onClick(() => addFolderModal(redraw)));

        // —— 连接地址 ——
        const url = r.domain ? r.domain + '/mcp' : '';
        new Setting(box).setName('连接地址').setDesc(url || '先填域名。本机测试可以用 http://127.0.0.1:' + r.port + '/mcp')
          .addButton(b => b.setButtonText('复制').setDisabled(!url).onClick(async () => { await navigator.clipboard.writeText(url); new Notice('已复制连接地址'); }));

        // —— 访问令牌 ——
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
        const clientBox = box.createDiv();

        new Setting(box).setName('撤销全部访问').setDesc('所有已连接的客户端和访问令牌立即失效，需要重新授权。口令不变。')
          .addButton(b => b.setButtonText('撤销全部').setWarning().onClick(() => confirmModal('撤销全部访问？',
            '撤销后，GPT 网页版等所有已连接的客户端、所有访问令牌立即失效，要重新授权才能再读。口令不变。', '撤销全部', async () => {
              const res = await act(['revoke-all'], '没撤销成功');
              if (res.ok) new Notice(res.message || '已撤销全部访问');
              redraw();
            })));

        box.createEl('div', { cls: 'setting-item-name', text: '最近访问' }).style.marginTop = '12px';
        const recent = box.createDiv({ cls: 'setting-item-description' });
        recent.style.cssText = 'line-height:1.7;max-height:14em;overflow:auto;';
        recent.setText('读取中…');

        // 状态一次读回（含计划任务、健康检查、令牌列表、最近访问）。「更多」折叠着时不读，展开那一下再读（不拖慢设置页）。
        const loadStatus = async () => {
          let j = null;
          try { ({ json: j } = await run(['status', ...settingsArgs()], { timeoutMs: 30000, fallback: '读不到状态' })); }
          catch (e) { st.setDesc('读不到状态：' + e.message); recent.setText(''); return; }
          if (!j) { st.setDesc('读不到状态'); recent.setText(''); return; }
          const label = { running: '运行中', stopped: '已停', error: '出错' }[j.state] || j.state;
          st.setDesc(j.state === 'running' ? j.message : (j.state === 'error' ? '出错：' + j.message : j.message || label));
          if (j.state === 'error') st.descEl.addClass('mod-warning');
          for (const w of j.warnings || []) detail.createDiv({ text: '⚠ ' + w });
          const auth = j.auth || {};
          pass.setDesc('GPT 网页版等走 OAuth 的客户端连接时，授权页要输这个口令。' + (auth.passphrase_set ? '已设（' + fmtTime(auth.passphrase_set_at) + '）。' : '还没设。'));
          if (passBtn) passBtn.setButtonText(auth.passphrase_set ? '修改口令' : '设置口令');
          for (const p of auth.personal || []) new Setting(tokBox).setName('　' + (p.label || '访问令牌'))
            .setDesc('生成于 ' + fmtTime(p.created) + (p.last_used ? ' · 最近使用 ' + fmtTime(p.last_used) : ' · 还没用过'))
            .addButton(b => b.setButtonText('撤销').onClick(async () => {
              const res = await act(['token', 'revoke', p.id], '没撤销成功');
              if (res.ok) new Notice('已撤销「' + (p.label || '访问令牌') + '」');
              redraw();
            }));
          if ((auth.clients || []).length) {
            clientBox.createEl('p', { cls: 'setting-item-description', text: '已授权的客户端：' + auth.clients.map(c => c.name + (c.last_used ? '（最近 ' + fmtTime(c.last_used) + '）' : '')).join('、') });
          }
          recent.empty();
          const rows = j.recent || [];
          if (!rows.length) recent.setText('还没有访问记录。');
          for (const row of rows.slice(0, 20)) recent.createDiv({ text: accessLine(row) });
        };
        const det = typeof container.closest === 'function' ? container.closest('details') : null;
        if (det && !det.open) {
          const once = () => { if (det.open) { det.removeEventListener('toggle', once); loadStatus(); } };
          det.addEventListener('toggle', once);
        } else loadStatus();
      };

      function showToken(token) {
        new TextModal('新的访问令牌', (el, modal) => {
          el.createEl('p', { text: '只显示这一次，关掉就看不到了。请现在复制，放进客户端的请求头：Authorization: Bearer <令牌>。' });
          const code = el.createEl('code', { text: token }); code.style.cssText = 'display:block;word-break:break-all;user-select:all;padding:8px;';
          new Setting(el).addButton(b => b.setButtonText('复制').setCta().onClick(async () => { await navigator.clipboard.writeText(token); new Notice('已复制访问令牌'); }))
            .addButton(b => b.setButtonText('关闭').onClick(() => modal.close()));
        }).open();
      }
      function showManual(command) {
        new TextModal('这台电脑要手动启动', (el, modal) => {
          el.createEl('p', { text: '不是 Windows，没法自动注册后台服务。开关已打开；请在终端运行下面这条命令（可以交给 launchd / systemd 开机自启）：' });
          const code = el.createEl('code', { text: command }); code.style.cssText = 'display:block;word-break:break-all;user-select:all;padding:8px;';
          new Setting(el).addButton(b => b.setButtonText('复制').setCta().onClick(async () => { await navigator.clipboard.writeText(command); new Notice('已复制命令'); }))
            .addButton(b => b.setButtonText('关闭').onClick(() => modal.close()));
        }).open();
      }
      draw();
    },
  };
};

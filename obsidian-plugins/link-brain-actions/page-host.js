// page-host.js — 1102：LWA 页面（目录 / 星标 / 问收藏 / Wiki / 回收站 / B 站挑选 / 每篇笔记的批注块）由插件自己执行，不再要 Dataview。
//
// md 里是一小段 ```lb-page 代码块（link_brain/catalog.py `_page_bootstrap()` 生成），块里写脚本名，可再带几行参数：
//
//     ```lb-page
//     catalog-page.js
//     ```
//     ```lb-page
//     annotate-view.js
//     itemId: "xhs-…"
//     notePath: "_archive/xiaohongshu/…/notes.json"
//     ```
//
// 这里做的事和 link_brain/assets/page-bootstrap.js（旧的 dataviewjs 引导）完全一样：找仓根 → 读（或复用已编译的）_archive/<脚本>
// → 给一个和 Dataview 一样的 `dv`（container / component / current() / page() / el() / paragraph() / __lbCodeVer）和 `app` → 跑脚本。
// 页面代码（lb-page-lib.js 和各 view）只用这几样，不用 Dataview 的查询 API，所以一行都不用改。
// 「找仓根 + 读 + 编译 + 按版本缓存」那段（lb-page-core）唯一源在 page-bootstrap.js，下面是逐字副本：
// python tools/sync_tokens.py 拷，tests/test_page_host.cjs 锁住两边一致。
//
// 和 Dataview 一样的重跑：库里任何一篇 .md 变了（2.5 秒防抖），可见的块清空容器再跑一遍（页面靠 lb-page-lib 的 reuseDom 原样挂回旧 DOM，不闪）；
// component.render() = 立刻重跑（lb-page-lib 的 deferIfHidden 用它）。块被 Obsidian 摘掉 / 插件卸载时 component 卸载，页面自己的 onUnload 收尾。
// 插件没启用（手机上，或用户关了它）时 Obsidian 把这块当普通代码显示一行脚本名，不报错。
'use strict';

// lb-page-core:begin
// 找仓根（从本页往上第一个带 _archive 的目录）→ 读（或复用已编译的）_archive/<script> → 编译成 AsyncFunction(dv, app, ...names)。
// 返回 {root, file, ver, run, error}：run 为 null 时 error 是没读到 / 没编译成的原因。同一文件同一版本（mtime:size）同一组参数名只编译一次。
async function lbLoadPage(app, folder, script, names) {
  let root = folder || "";
  while (root && !app.vault.getAbstractFileByPath(root + "/_archive")) root = root.includes("/") ? root.slice(0, root.lastIndexOf("/")) : "";
  const file = (root ? root + "/" : "") + "_archive/" + script;
  const stat = app.vault.getAbstractFileByPath(file)?.stat;
  const ver = stat && stat.mtime ? stat.mtime + ":" + stat.size : "";
  const params = ["dv", "app"].concat(names || []);
  const key = file + "|" + params.join(",");
  const cache = (globalThis.__lbPageCode = globalThis.__lbPageCode || {});
  if (ver && cache[key] && cache[key].ver === ver) return { root, file, ver, run: cache[key].fn, error: null };
  try {
    const code = await app.vault.adapter.read(file);
    // 脚本里有顶层 await / return，必须用 AsyncFunction 构造
    const fn = new (Object.getPrototypeOf(async function () {}).constructor)(...params, code);
    if (ver) cache[key] = { ver, fn };
    return { root, file, ver, run: fn, error: null };
  } catch (e) { return { root, file, ver, run: null, error: e }; }
}
// lb-page-core:end

const LANG = 'lb-page';
const RERUN_MS = 2500;   // 和 Dataview 默认的刷新间隔一样
const SCRIPT_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*\.js$/;   // 只认 _archive 下的一个文件名：不许带路径、不许 ..
const KEY_RE = /^([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*(.*)$/;
const RESERVED = new Set(['dv', 'app', 'script', 'arguments', 'eval']);

// 块内容 → {script, params, error}。第一行不带冒号的是脚本名（也可写 `script: x.js`）；其余 `名字: 值` 是参数，值按 JSON 解析，解析不了当字符串。
// 以 Path 结尾的参数是仓根相对路径，运行时补上仓根前缀（批注块的 notePath；和旧引导里的 lbPath 一样）。
function parseBlock(source) {
  const out = { script: '', params: {}, error: '' };
  for (const raw of String(source == null ? '' : source).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith('//')) continue;
    const m = KEY_RE.exec(line);
    if (!m) { if (!out.script) { out.script = line; continue; } out.error = '看不懂这一行：' + line; break; }
    let value = m[2].trim();
    try { value = JSON.parse(value); } catch { /* 不是 JSON：当字符串 */ }
    if (m[1] === 'script') { out.script = String(value); continue; }
    if (RESERVED.has(m[1])) { out.error = '参数名不能用 ' + m[1]; break; }
    out.params[m[1]] = value;
  }
  if (!out.error && !out.script) out.error = '没写要跑哪个页面脚本';
  else if (!out.error && !SCRIPT_RE.test(out.script)) out.error = '页面脚本名不对：' + out.script;
  return out;
}

function folderOf(p) { const s = String(p || ''); return s.includes('/') ? s.slice(0, s.lastIndexOf('/')) : ''; }

module.exports = function pageHost(obsidian, plugin) {
  const app = plugin.app;
  const live = new Set();   // 正在显示的块（插件卸载时逐个卸掉）
  let attached = false;

  // 页面出错时的提示框：只占这一块，不往外抛（Obsidian 渲染这一段的其余内容照常）
  function failBox(el, text) {
    try {
      const doc = el.ownerDocument || document;
      const box = doc.createElement('div');
      box.className = 'lb-page-fail';
      box.textContent = text;
      el.appendChild(box);
      return box;
    } catch { return null; }
  }

  // 和 Dataview 的 dv 一样大小的那几样（页面只用这些）
  function makeDv(el, child, sourcePath) {
    const folder = folderOf(sourcePath);
    const name = String(sourcePath || '').split('/').pop() || '';
    const dv = {
      container: el,
      component: child,
      current: () => ({ file: { path: sourcePath || '', folder, name } }),
      page(p) {
        try { const fm = app.metadataCache?.getCache?.(p)?.frontmatter; return fm ? Object.assign({}, fm, { file: { path: p } }) : null; } catch { return null; }
      },
      // 字符串按 Markdown 渲染（和 Dataview 一样；只给兜底提示用，页面正文走插件的 renderMarkdownScoped）
      el(tag, text, attrs) {
        const doc = el.ownerDocument || document;
        const node = doc.createElement(tag || 'div');
        if (attrs && attrs.cls) node.className = [].concat(attrs.cls).join(' ');
        const md = typeof plugin.neutralizeMarkdown === 'function' ? plugin.neutralizeMarkdown(String(text == null ? '' : text)) : String(text == null ? '' : text);
        const MR = obsidian && obsidian.MarkdownRenderer;
        try {
          if (MR && typeof MR.render === 'function') MR.render(app, md, node, sourcePath || '', child);
          else if (MR && typeof MR.renderMarkdown === 'function') MR.renderMarkdown(md, node, sourcePath || '', child);
          else node.textContent = md;
        } catch { node.textContent = md; }
        el.appendChild(node);
        return node;
      },
      paragraph(text, attrs) { return dv.el('p', text, attrs); },
      header(level, text, attrs) { return dv.el('h' + (Number(level) || 1), text, attrs); },
      span(text, attrs) { return dv.el('span', text, attrs); },
    };
    return dv;
  }

  function clear(el) { if (typeof el.empty === 'function') el.empty(); else el.innerHTML = ''; }

  // 跑一次：读脚本 → 跑；读不到 / 跑出错都只在这一块里说一句（entry.lastError 记下原因，测试 / 诊断读它）
  // env：额外传给脚本的名字（只给测试外壳注入假时钟等，块里写的参数都是 JSON）
  async function runOnce(entry, block, el, child, sourcePath, env) {
    entry.lastError = null;
    const names = Object.keys(block.params);
    const envNames = Object.keys(env || {}).filter(k => !RESERVED.has(k) && !(k in block.params));
    const page = await lbLoadPage(app, folderOf(sourcePath), block.script, names.concat(envNames));
    if (!page.run) {
      const why = page.error && (page.error.message || String(page.error)) || '没找到';
      entry.lastError = page.error || new Error(why);
      failBox(el, '页面脚本没读到（' + why + '）：点右上「…」→ 刷新目录');
      return false;
    }
    const prefix = p => (page.root ? page.root + '/' + p : p);
    const values = names.map(k => (/Path$/.test(k) && typeof block.params[k] === 'string' ? prefix(block.params[k]) : block.params[k]))
      .concat(envNames.map(k => env[k]));
    const dv = makeDv(el, child, sourcePath);
    dv.__lbCodeVer = page.ver;
    try {
      await page.run(dv, app, ...values);
      return true;
    } catch (e) {
      entry.lastError = e;
      console.error('[lb] 页面 ' + block.script + ' 出错', e);
      failBox(el, '页面出错了（' + (e && e.message || e) + '）：点右上「…」→ 刷新目录 后再打开；还不行到设置页「修复」里复制报错');
      return false;
    }
  }

  // 返回这一块的 entry {child, el, script, sourcePath, rerun, lastError}（块写错 / 没有 MarkdownRenderChild 时 null）
  async function processBlock(source, el, ctx, opts = {}) {
    const block = parseBlock(source);
    const sourcePath = (ctx && ctx.sourcePath) || '';
    if (block.error) { failBox(el, 'LWA 页面块写错了：' + block.error); return null; }
    const Child = obsidian && obsidian.MarkdownRenderChild;
    const child = Child ? new Child(el) : null;
    if (!child) { failBox(el, '这个 Obsidian 版本没有 MarkdownRenderChild，页面显示不了'); return null; }
    let alive = true, running = null, again = false, timer = null;
    const entry = { child, el, script: block.script, sourcePath, lastError: null };
    // 重跑：和 Dataview 一样先清空容器再跑；跑着的时候又要重跑 → 跑完再来一次（不叠两份）
    const rerun = async () => {
      if (!alive) return;
      if (running) { again = true; return running; }
      running = (async () => {
        do { again = false; clear(el); await runOnce(entry, block, el, child, sourcePath, opts.env); } while (again && alive);
      })().finally(() => { running = null; });
      return running;
    };
    entry.rerun = rerun;
    child.render = rerun;
    child.register(() => { alive = false; if (timer) clearTimeout(timer); timer = null; live.delete(entry); });
    // 库里的 .md 变了（同步写笔记、批注落盘、目录重建）→ 2.5 秒后重跑看得见的这一块（Dataview 也是这样）
    const schedule = file => {
      if (!alive || !file || !/\.md$/i.test(String(file.path || ''))) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => { timer = null; if (alive && el.isConnected) rerun().catch(e => console.error('[lb] 页面重跑失败', e)); }, RERUN_MS);
    };
    if (app.vault && typeof app.vault.on === 'function') for (const ev of ['modify', 'create', 'delete', 'rename']) child.registerEvent(app.vault.on(ev, schedule));
    if (app.workspace && typeof app.workspace.on === 'function') child.registerEvent(app.workspace.on('link-brain:refresh-pages', () => { if (alive && el.isConnected) rerun().catch(() => {}); }));
    if (ctx && typeof ctx.addChild === 'function') ctx.addChild(child); else if (typeof child.load === 'function') child.load();
    live.add(entry);
    try { await rerun(); } catch (e) { entry.lastError = e; console.error('[lb] 页面没画上', e); failBox(el, '页面没画上：' + (e && e.message || e)); }
    return entry;
  }

  return {
    LANG,
    live,
    process: processBlock,
    attach() {
      if (attached || typeof plugin.registerMarkdownCodeBlockProcessor !== 'function') return false;
      plugin.registerMarkdownCodeBlockProcessor(LANG, (source, el, ctx) => processBlock(source, el, ctx).catch(e => { console.error('[lb] lb-page 块出错', e); failBox(el, '页面没画上：' + (e && e.message || e)); }));
      attached = true;
      return true;
    },
    // 插件卸载：已画出来的块逐个卸掉（页面的 onUnload 摘 host、停监听 / 定时器）
    detach() {
      for (const entry of [...live]) { try { entry.child.unload(); } catch {} }
      live.clear();
    },
    // 别处（重建目录之后、设置里换了东西）要页面立刻重跑：和 Dataview 的 refresh-views 一样
    refreshAll() { for (const entry of [...live]) { try { if (entry.el.isConnected) entry.rerun(); } catch {} } },
  };
};
module.exports.parseBlock = parseBlock;
module.exports.lbLoadPage = lbLoadPage;
module.exports.LANG = LANG;
module.exports.RERUN_MS = RERUN_MS;

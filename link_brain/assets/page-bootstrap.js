// 页面脚本在 _archive/__LB_SCRIPT__（catalog.py 生成，别手改）；这里只负责载入。
// 1017：以前 210KB 的页面脚本直接烤在 md 里，每次打开 Obsidian 都要把它当 Markdown 解析两遍（阅读视图 + 藏着的编辑视图，编辑视图还逐行着色），
// Dataview 再 direct eval 两遍。现在只读一次文件、按 mtime:size 认版本，编译好的函数挂在 globalThis 上，同一版本只编译一次。
// 1102：这一段只在「旧库 / 设置 pageBlock=dataviewjs」时还写进 md（默认是 lb-page 代码块，由插件 page-host.js 执行，不要 Dataview）。
// 下面 lb-page-core 两个标记之间是**唯一源**：插件 page-host.js 里同名一段是逐字副本（python tools/sync_tokens.py 拷，tests/test_page_host.cjs 锁）。
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
const lbPage = await lbLoadPage(app, dv.current()?.file?.folder || "", "__LB_SCRIPT__");
if (lbPage.error) dv.paragraph("页面脚本没读到（" + (lbPage.error?.message || lbPage.error) + "）：在电脑上点右上「…」→ 刷新目录");
// 1020：脚本版本交给页面——页面复用旧 DOM（切走再回来 / 暂存整页）前先比它，代码换了就重建（以前部署后要重启 Obsidian 才是新版）
if (lbPage.run) { try { dv.__lbCodeVer = lbPage.ver; } catch {} await lbPage.run(dv, app); }

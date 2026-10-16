// 页面脚本在 _archive/__LB_SCRIPT__（catalog.py 生成，别手改）；这里只负责载入。
// 1017：以前 210KB 的页面脚本直接烤在 md 里，每次打开 Obsidian 都要把它当 Markdown 解析两遍（阅读视图 + 藏着的编辑视图，编辑视图还逐行着色），
// Dataview 再 direct eval 两遍。现在只读一次文件、按 mtime:size 认版本，编译好的函数挂在 globalThis 上，同一版本只编译一次。
let lbRoot = dv.current()?.file?.folder || "";
while (lbRoot && !app.vault.getAbstractFileByPath(lbRoot + "/_archive")) lbRoot = lbRoot.includes("/") ? lbRoot.slice(0, lbRoot.lastIndexOf("/")) : "";
const lbScript = (lbRoot ? lbRoot + "/" : "") + "_archive/__LB_SCRIPT__";
const lbStat = app.vault.getAbstractFileByPath(lbScript)?.stat;
const lbVer = lbStat && lbStat.mtime ? lbStat.mtime + ":" + lbStat.size : "";
const lbCodeCache = (globalThis.__lbPageCode = globalThis.__lbPageCode || {});
let lbRun = lbVer && lbCodeCache[lbScript]?.ver === lbVer ? lbCodeCache[lbScript].fn : null;
try {
  if (!lbRun) {
    const code = await app.vault.adapter.read(lbScript);
    // 脚本里有顶层 await / return，必须用 AsyncFunction 构造
    lbRun = new (Object.getPrototypeOf(async function () {}).constructor)("dv", code);
    if (lbVer) lbCodeCache[lbScript] = { ver: lbVer, fn: lbRun };
  }
} catch (e) { lbRun = null; dv.paragraph("页面脚本没读到（" + (e?.message || e) + "）：在电脑上点右上「…」→ 刷新目录"); }
if (lbRun) await lbRun(dv);

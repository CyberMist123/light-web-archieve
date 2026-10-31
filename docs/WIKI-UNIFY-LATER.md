# 个人 Wiki：先在 Wiki 里这样做、以后再统一的前端（10-29）

> 作者（10-29）：「你标一些哪些前端会变，这以后统一。」
> 设计稿（design-1028-wiki，不进仓）里有几处会牵动别的页面。现在的做法：**Wiki 页先沿用现在共用的样子**，别的页面一处不动；统一时照下表一批改。

## 1. 页头三页切换（浏览收藏 / 问收藏 / Wiki）

设计稿：胶囊改成宋体 16 的下划线标签（当前 = 600 + 2.5px 墨线），和篇数行同压一条墨线；手机上篇数行在上、切换在下。以后可能再换成液态玻璃（只用在这一处，见设计稿 design.md §13）。
**现在**：Wiki 页用现有的 `.lb-page-nav` 胶囊，只多一颗「Wiki」。

统一时会变的地方：

| 页面 | 代码 | 现在的样子 |
|---|---|---|
| 共用样式 | `link_brain/assets/lb-page-lib.js` `LB_SHARED_CSS` 里的 `.lb-page-nav` 三条 | 浅灰底胶囊组，当前项白底 |
| 问收藏 | `link_brain/assets/chat-view.js` 建 `pageNav` 那段（「浏览收藏 / 问收藏」两颗）+ 窄屏规则 `.lbchat-head .lb-page-nav` | 标题下面左对齐；篇数行单独居中一行 |
| 回收站 | `link_brain/assets/trash-view.js` 的 `nav`（`.lbt-wrap .lb-page-nav`） | 同上 |
| 目录页（浏览收藏） | `link_brain/assets/catalog-view.js` 没有这组切换，用的是积木 `ask` 里的「问收藏 →」胶囊（`.lbc-askbtn`） | 统一时要决定：目录页也上三页切换，还是保留「问收藏 →」再加一颗「Wiki →」 |
| Wiki | `link_brain/assets/wiki-view.js`（新） | 现在：现有胶囊；统一时一起换 |

## 2. 收藏引用的长相

设计稿：Wiki 正文里的收藏引用 = 点线下划线 + 斜体编号圈（本页出现顺序），和「问收藏来源角标一套」。
**现在**：只在 Wiki 里这样做。问收藏的引用仍是 `chat-view.js` 的 `.lbchat-cite`（上标小胶囊数字）。统一时两边用同一个编号圈组件。

## 3. 正文里随手写的数字也斜（`LB Digits Inline`）

设计稿：另起一个只含 0–9、`size-adjust:114%` 的字体，放在宋体 / 黑体字栈最前，正文、标题、目录里的数字全斜。
**现在**：只挂在 Wiki 页的根元素上（`.lbw` 作用域）。共用的 `lb-page-lib.js` `brandFontCss()` 里已有 `LB Digits`（数字和数字旁的符号），没动。统一时决定要不要把 Inline 版挪进共用字体、让问收藏 / 目录页正文里的数字也斜。

## 4. 不再用 `title` / `aria-label` 做悬浮说明

设计稿：Wiki 全页没有 `title=` 和 `aria-label=`（Obsidian 会画成浮框，作者不要），图标钮靠隐藏文字给读屏，说明写在工具行行尾。
**现在**：只 Wiki 这样。问收藏 / 目录页里还有不少（例：`chat-view.js` 历史钮的 `aria-label` / `title`），统一时一起清。

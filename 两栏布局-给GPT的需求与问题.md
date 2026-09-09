# 两栏「左图右文」布局 —— 需求 + 现存问题（给 GPT）

分支：`gpt/highlight-sticky-layout-20260905`（HEAD 已到 `a4a7ddd`）
仓库：`D:\LIGHT WEB ARCHIEVE`，Obsidian vault 在 `vault\`，CSS 片段 `vault\.obsidian\snippets\link-brain.css`（源在 `link_brain\assets\link-brain.css`，`render` 会同步）。

---

## 一、我要的最终效果（需求，按重要度）

**R1. 默认两栏「左图右文」**：图片列在**左**、正文/标签/评论在**右**。这是我辛苦调好、想保留的核心版式。

**R2. 阅读视图和编辑/实时预览视图都要两栏**。现在只有阅读视图（Reading View）写了两栏，实时预览（Live Preview / 编辑模式）是单栏。我经常在编辑模式看/改，希望编辑模式也是左右两栏。

**R3. 只有「手机大小」才收成上下单栏**：正常桌面宽度一律两栏；窄到手机宽度（例如 pane 内宽 < 600px）才允许塌成上下单栏。不要在普通桌面宽度就塌单栏。

**R4. 图片尺寸 / 比例绝对不许变**。我已经把图片大小、两栏比例调到满意了，这次只解决「分不分栏」，不要动任何图片尺寸、`max-height`、列宽比例等。

**R5.（附带，已做一半）多图能用 ←/→ 翻页**。已经有一个 Obsidian 插件 `link-brain-native-media-nav`（`obsidian-plugins\` + 已装进 vault），改成驱动两栏里左边的 `.lb-carousel` 滑动条，翻图不影响正文。只要两栏能正常出来，这个就能配合工作。

---

## 二、现在的两个 Bug

**B1（最关键）阅读视图下不是左右两栏，而是上下堆叠。**
即：图片在上、正文在下，一整列铺满宽度——不是我要的左图右文。

**B2 编辑 / 实时预览视图下完全没有两栏（永远单栏）。**
GPT 这版 CSS 只给阅读视图（`.markdown-preview-view.xhs-note`）写了两栏 grid，没给编辑视图（`.markdown-source-view` / CodeMirror）写任何两栏规则。

---

## 三、技术背景 / 根因线索（给 GPT 定位用）

### 渲染出的 HTML 结构（`render.py` `_render_note` 尾部）
一篇笔记的正文层是**一个大 div 包住全部**：
```html
<div class="lb-note">
  <section class="lb-media"><div class="lb-carousel">
    <figure class="lb-slide"><img …><figcaption class="lb-counter">1 / 26</figcaption></figure>
    … 每张图一个 figure.lb-slide …
  </div></section>
  <div class="lb-author-row">…作者…</div>
  …正文（真 Markdown，不再包 div，为了能直接 ==划重点==）…
  <div class="lb-comments">…评论…</div>
</div>
```
正文用真 Markdown（不是 HTML），这是为了在 Live Preview 里能直接划重点、点正文不掉进源码块。

### GPT 这版 CSS 的两栏机制（阅读视图）
用的是 **grid-on-sizer + 直接子选择器 + 容器查询**：
```css
.markdown-preview-view.xhs-note,
.markdown-source-view.xhs-note { container-type: inline-size; container-name: link-brain-note; }

.markdown-preview-view.xhs-note .markdown-preview-sizer { max-width: min(100%,1380px)!important; } /* 覆盖可读行长 */

.markdown-preview-view.xhs-note .markdown-preview-sizer { display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); }
.markdown-preview-view.xhs-note .markdown-preview-sizer > *        { grid-column: 2; }   /* 默认右列 */
.markdown-preview-view.xhs-note .markdown-preview-sizer > .lb-note { grid-column: 1; grid-row: span 500; position: sticky; top:16px; } /* 图片列左、且吸顶 */
.markdown-preview-view.xhs-note .markdown-preview-sizer > .lb-author-row { grid-column: 2; position: sticky; top:16px; } /* 作者行也吸顶 */

@container link-brain-note (max-width: 600px) { … display:block … }  /* 窄到手机才塌单栏 */
```

### 关键矛盾（很可能就是 B1 的根因）
- CSS 用的是 `.markdown-preview-sizer > .lb-note`、`.markdown-preview-sizer > .lb-author-row` 这种**直接子选择器**，并期望 `.lb-media`/`.lb-author-row`/正文/评论是 sizer 下的**平级兄弟**（注释里写着「两栏不能再依赖一个包住正文的 HTML div，而是直接把 markdown-preview-sizer 当 grid」）。
- 但 `render.py` 实际输出是**全部包在一个 `<div class="lb-note">` 里**（见上），并**不是**平级兄弟。而且 Obsidian 阅读视图通常会给每个顶层块再套一层 `div.el-*` 包裹，`.markdown-preview-sizer > .lb-note` 这种直接子选择器**大概率匹配不到** → grid 分不了栏 → 全挤进一列 → 上下堆叠。
- 对照：**`main` 的老版能出左右两栏**，它用的是 **float**（`render.py` 注释仍写「左图右文改由 CSS 让 `.lb-media` 浮到左边实现」）。也就是说 GPT 这版把 float 改成了 grid-on-sizer，但 `render.py` 的结构没同步改成 grid 需要的平级兄弟，于是回归。

### B2（编辑模式）的背景
Live Preview 是 CodeMirror，正文是真 Markdown。要在编辑模式做两栏，得在 `.markdown-source-view.xhs-note .cm-sizer` / `.cm-content` 上做，且不能破坏光标/选区/划重点。

---

## 四、给 GPT 的建议方向（供参考，不强制）

1. **先开 devtools 看真实 DOM**：Obsidian 里 `Ctrl+Shift+I`，检查阅读视图下 `.markdown-preview-sizer` 的直接子到底是什么（是不是 `div.el-*` 包了一层，导致 `> .lb-note` 匹配不到）。这一步能直接证实 B1 根因。

2. **两个候选修法**：
   - **(推荐) 回到 float 两栏**：这是 `main` 上**已在真机验证能出左右两栏**的方案——对 `.lb-note` 内部：`.lb-media` 浮左（固定或按比例宽度）、正文自然环绕。好处：① 不依赖 Obsidian 的块包裹结构；② **float 的 HTML 块在 Live Preview（CodeMirror）里正文也能自然环绕**，所以**阅读+编辑两个视图都能两栏**，正好满足 R2；③ 改动集中在 `.lb-note` 内部，不动图片尺寸（满足 R4）。
   - **或修 grid 方案**：把 `render.py` 改成真正输出平级兄弟（不包在一个 `.lb-note` 里，或用 Obsidian 支持的结构），并把 `>` 直接子选择器改成后代选择器；同时给 `.markdown-source-view` 也写一套。这条更折腾、且编辑模式的 grid 容易和 CodeMirror 打架。

3. **阈值**：单栏收拢门槛已从 795px 降到 **600px**（`@container link-brain-note (max-width: 600px)`，两处）。若嫌 600px 时两栏太挤可再商量，但需求是「桌面默认两栏」。

4. **红线（R4）**：不要改任何图片尺寸相关的值——`.lb-slide img` 的 `max-height`、`.lb-media`/列宽比例、`grid-template-columns` 的比例等，保持现状。只解决分栏结构。

5. **历史坑**：`main` 的 `STATE.md`「本轮明确回滚」里记过——「作者头 sticky」「图片/正文强制固定的实验布局」在真机体验变差被撤过。GPT 这版又带了 `.lb-note` 和 `.lb-author-row` 的 `position: sticky`。如果滚动时觉得别扭，可考虑去掉 sticky。

---

## 五、验收（我会在 Obsidian 真机看）
- 正常桌面宽度：阅读视图 **和** 编辑/实时预览视图**都**是左图右文两栏。
- 窗口拖到手机宽（<600px）才塌成上下单栏。
- 图片大小、两栏比例和现在（我调好的）一模一样，没变。
- 多图能点图后用 ←/→ 翻左列的图。

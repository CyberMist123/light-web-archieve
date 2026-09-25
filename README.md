# light-web-archieve

把小红书链接归档成**不可变的原始快照** + **一篇给人看的 Obsidian 笔记**。

## 第一次使用（Windows 桌面）

准备 **Python 3.11+、Git、Obsidian**。安装 Python 时勾选添加到 PATH。

在 PowerShell 中执行：

```powershell
git clone https://github.com/CyberMist123/light-web-archieve.git
cd light-web-archieve
python -m pip install -e .
python -m link_brain catalog
New-Item -ItemType Directory -Force vault/.obsidian/plugins
Copy-Item -Recurse -Force obsidian-plugins/link-brain-actions vault/.obsidian/plugins/
Copy-Item -Recurse -Force obsidian-plugins/link-brain-native-media-nav vault/.obsidian/plugins/
```

1. 在 Obsidian 中「打开文件夹作为仓库」，选择刚 clone 的 **`vault` 文件夹**。
2. 设置 → 社区插件，启用 **Link Brain Actions** 和 **Link Brain Native Media Nav**。
3. 安装并启用 **Dataview**，在它的设置中打开 **Enable JavaScript Queries**。
4. 按 [`reader/README.md`](reader/README.md) 编译读取组件（放进 `%USERPROFILE%\.link-brain\bin\`）。打开 **Link Brain Actions 设置**，顶部是 **小红书账号** 卡片，点 **扫码登录**：浏览器弹出二维码，用手机小红书「扫一扫」并确认，卡片自动变成「已登录」。**一个号覆盖读取、评论、私密收藏、附件下载**，登录自动保存，失效时才需要重新扫码。
5. 打开「小红书收藏目录」，点击 **＋**，粘贴从小红书 App 复制的完整分享链接。导入完成后点击卡片，即可看到第一篇归档；Markdown 位于 `vault/Web/Xiaohongshu/`。

首次下载组件/浏览器需要联网，可能较慢。Python 安装后若 Obsidian 仍找不到它，请重启 Obsidian。
可在终端做同样的检查和登录：

```powershell
link-brain doctor
link-brain login
link-brain ingest "粘贴完整分享链接"
link-brain catalog
```

若终端找不到 `link-brain`，把命令前缀换成 `python -m link_brain`。安装采用 editable 模式，保留 clone 的文件夹；插件默认使用该目录中的 `vault`。本轮未验证 macOS / Linux 首次使用。

**普通链接归档需要读取账号登录。** 不要把 HTTP 200 或游客可见的附件名称当成完整内容已经可读。
收藏同步、自动附件下载和 AI 都是可选项；不配置仍可读取链接、保存原文/原图、检索本地归档。
AI/OCR 未配置时，不会阻塞原文归档。手机扫码及必要的官方验证由本人完成。

### 出问题时

账号卡片和目录页都会直接告诉你原因和下一步，按钮就是解决办法：

| 看到 | 原因 | 点什么 |
|---|---|---|
| **登录失效** / 目录页 **! 需要登录** | 会话过期 | **扫码登录**（目录页点「!」直接出码） |
| **需要验证** / **! 需要验证** | 小红书弹了安全验证（拼图滑块） | **打开验证**：在弹出的窗口里手动拖动滑块后关掉窗口；或过几小时再试。程序不会自动重试，也不会替你过验证 |
| **刚刚同步过** | 为防风控，收藏每 10 分钟最多读一次 | 稍后再点 **立即同步** |
| **服务未运行** | 读取组件没起来 | **重试**（会自动拉起）；日志在 `%USERPROFILE%\.link-brain\reader.log` |
| **未安装** | 没找到 `link-brain-reader` | 见「读取组件」 |

扫码时只轮询服务的内存状态，不会刷新浏览器，二维码不会被冲掉；扫码进行中其它操作会立即提示「正在等待扫码」，不会排队卡住。
`link-brain login --status --json` / `login --verify` 是界面用的同一套接口。

### Optional features / 可选能力

- **收藏同步 / 附件下载**：与读取同一个号、同一个登录，不用再单独登录。收藏同步要登录**收藏所在的那个号**。不要在其他电脑浏览器同时登录这个号（同一个号两个网页会话会互相顶掉；手机 App 不受影响）。
- **AI**：在设置页配置自己的接口并点击测试。状态「已配置」不代表已完成真实调用验证。

English quick start: install Python 3.11+, Git and Obsidian, run the commands above, open `vault` in Obsidian, enable both bundled plugins and Dataview JavaScript queries, then open **Link Brain Actions** settings and click **扫码登录** on the Xiaohongshu account card. One account covers reading, comments, private favorites and attachment downloads; the session is saved and only needs a new scan when it expires. Paste a full share link through the catalog's **＋** button. AI is optional.

详细能力与验证边界见 [首次使用能力审计](docs/CAPABILITIES.md)。以下为高级配置和已有功能参考。

## 读取组件（link-brain-reader）

所有需要登录的操作都经由一个本地服务 `link-brain-reader`（默认 `127.0.0.1:18061`）。它基于 [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 扩展：

- 独占一个持久浏览器目录，登录态住在里面（不导出 cookie）；评论、私密收藏、附件都在同一进程里**串行**执行，同一个号不会出现第二个网页会话去顶号。
- 关闭浏览器前把站点下发的会话 cookie 落盘——这是旧版「扫码成功、下次又是未登录」的原因。
- `GET /api/v1/login/session`：扫码进度（纯内存，不开浏览器）；`GET /api/v1/favorites`：收藏列表（10 分钟限频）；`POST /api/v1/attachments/download`：点附件页「下载」；`POST /api/v1/verify/window`：打开有界面的窗口供人工完成安全验证。
- 识别到安全验证（拼图滑块）立即返回 `CAPTCHA_REQUIRED` 停车，不重试、不尝试自动通过。

**获取**：以补丁形式放在本仓库 [`reader/`](reader/README.md)：按那里的步骤检出原项目指定版本、打补丁、编译，把 `link-brain-reader.exe` 放进 `%USERPROFILE%\.link-brain\bin\`（或用 `LINK_BRAIN_XHS_EXE` 指定路径）；插件和命令行在需要时会自动在后台启动它。全部改动清单也在那里。官方原版 xiaohongshu-mcp 没有上述收藏 / 附件 / 登录会话接口，只能用于普通链接读取。

浏览器目录默认 `%USERPROFILE%\.link-brain\xhs-profile`（`XHS_PROFILE_DIR` 可覆盖）。换号：先结束 `link-brain-reader` 进程，把该目录改名备份（删掉 cookie 文件没用，登录态在目录里），再点「扫码登录」用新号扫。

### 本机依赖与环境变量（开源移植看这里）

以下供已有组件的高级用户覆盖。普通用户按顶部 Quick Start 操作即可；AI/OCR 的历史本机路径仍保留兼容，但不作为首次归档前提。

| 环境变量 | 覆盖什么 | 不设时的默认 |
|---|---|---|
| `LINK_BRAIN_VAULT` | vault 根目录 | 仓库下 `vault/` |
| `LINK_BRAIN_MEDIA_PY` | 便宜的文本/识图脚本 `media.py`（`llm.py` / `vision.py`） | 作者本机路径 |
| `DASHSCOPE_API_KEY` | media.py 用的千问 key | media.py 读仓库外 CSV |
| `LINK_BRAIN_XHS_EXE` / `LINK_BRAIN_XHS_ENDPOINT` | 读取组件程序 / 服务地址 | `.link-brain\bin\link-brain-reader.exe` / `http://127.0.0.1:18061/mcp` |
| `XHS_PROFILE_DIR` | 读取组件的浏览器目录（登录态所在） | `.link-brain\xhs-profile` |
| `LINK_BRAIN_HOME` | 登录入口的配置、下载程序、日志目录 | 当前用户 `.link-brain` |

私密收藏与附件字节都走读取组件的同一个登录；没登录也不影响已归档内容的目录、检索、问答。

### AI 接口（问答 / 摘要 / 识图 / TTS）

配置在 Obsidian 插件 **Link Brain Actions 的设置页**，只落 `vault/.obsidian/plugins/link-brain-actions/data.json`
（`vault/` 已 gitignore，**key 绝不进仓、绝不打印**）。两种通路：

- **本机 media.py（默认）**：复用作者本机已配置的便宜通路，无需在插件里填 key。
- **自定义 HTTP**：没有 media.py 的用户填自己的 OpenAI 兼容 endpoint/model/key 即可（文本走 `/chat/completions`、TTS 走 `/audio/speech`）。

摘要提示词接 `llm.py` 抽取流程、识图通路接 `vision.py`、`/问AI` 走 `python -m link_brain ask`
（读整个本地 `catalog-data.json` 重新检索，只把挑出的少量片段送模型，token 控制全在这一步）。
每条接口在设置页都有「测试」按钮，发一次最小真实调用验证是否接通。

## 仓库是公开的

`vault/`、`.env`、`*.local.*` 全在 `.gitignore`。**任何 cookie / token / key / 抓下来的样本数据都不许进版本控制。**
commit 前跑一次 `git status` 核对。

## 文档

- `docs/TASKBOOK.md` — 唯一执行文档（做什么、验收标准、5 条样本）
- `docs/FORMAT.md` — 数据格式唯一真相
- `docs/POC-xiaohongshu.md` — 小红书 MCP 能拿到什么、拿不到什么
- `docs/STATE.md` — 当前进度、已回滚实验、下一步
- `docs/BENCH.md` — 小模型跑分（成功率 / token / 成本，Owner 填人工判定列）
- `docs/tag-vocab.yaml` — 标签归一词表

## 测试

```bash
python -m pytest -q
```

## 许可

[MIT](LICENSE) © CyberMist

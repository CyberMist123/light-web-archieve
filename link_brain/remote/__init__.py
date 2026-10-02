"""远程阅读（MCP，高级）：本机一个只读的 MCP HTTP 小服务，用户自备域名经自己的隧道 / 反代接到它，
GPT 网页版或任何能连远程 MCP 的客户端就能**阅读和搜索**收藏（含机读版 agent.md、附件全文）。

它是**独立后台服务**，不挂在 Obsidian 下：读的是本机文件，关了 Obsidian 照常可读。
Windows 上「启用」= 注册计划任务 `LinkBrainRemote`（登录时启动、每 5 分钟看一眼没在跑就拉起），
「停用」= 停掉并删除任务。macOS / Linux 手动起：`python -m link_brain remote serve`。

模块图：
- `config`  ：唯一配置源 = 插件 data.json 的 `remote` 段（开关 / 域名 / 端口 / 文件夹）；按 mtime 热重载。
- `policy`  ：路径白名单。规范化 → 规则核对 → 文件系统核对（lstat 非链接 + realpath 逐字相等），三道都过才读。
- `store`   ：口令（scrypt）与令牌（只存 sha256）——`~/.link-brain/remote/auth.json`，不进 data.json、不进仓库。
- `tools`   ：三个只读工具 search / read / list（search 复用 retrieval 的词法 + 语义）。
- `server`  ：ASGI 应用（Host 校验、OAuth 动态注册 + PKCE + 口令批准页、Bearer、每令牌限速、访问日志）+ uvicorn。
- `task`    ：Windows 计划任务的注册 / 移除 / 启停（PowerShell ScheduledTasks）。
- `cli`     ：`python -m link_brain remote <子命令>`，设置页经 runPy 调它。

本机状态目录 `$LINK_BRAIN_HOME/remote`（默认 `~/.link-brain/remote`）：
auth.json（口令哈希 / 令牌哈希）· status.json（服务自报的运行状态）· access.log（每次访问一行，不记内容）· server.log。
"""

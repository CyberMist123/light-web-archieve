# link-brain-reader（读取组件）

Link Brain 所有需要小红书登录的操作（读笔记与评论、私密收藏、附件下载、扫码登录）都经由这个本地服务。
它是 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 的修改版，以补丁形式放在这里：

- 基线：xiaohongshu-mcp 提交 `c2fc4dde2c45f26f6f9de288b7423a2bdfa7af1c`
- 补丁：[`link-brain-reader.patch`](link-brain-reader.patch)

原项目以 Apache License 2.0 发布，版权归原作者所有；本补丁同样以 Apache License 2.0 提供。下面列出所有改动。

## 编译（Windows / macOS / Linux，需要 Go 1.24+ 与 Git）

```bash
git clone https://github.com/xpzouying/xiaohongshu-mcp.git
cd xiaohongshu-mcp
git checkout c2fc4dde2c45f26f6f9de288b7423a2bdfa7af1c
git apply /path/to/light-web-archieve/reader/link-brain-reader.patch
go build -o link-brain-reader.exe .
```

把 `link-brain-reader.exe` 放进 `%USERPROFILE%\.link-brain\bin\`（或用环境变量 `LINK_BRAIN_XHS_EXE` 指定路径）。
之后插件和命令行在需要时会自动在后台启动它（默认端口 18061），不用手动运行。首次启动会下载它自带的浏览器。

## 改了什么

**一个号、一个会话**
- 使用持久浏览器目录（`XHS_PROFILE_DIR`，默认 `~/.link-brain/xhs-profile`）保存登录，不导出 cookie；
  所有打开浏览器的操作在进程内串行，同一个号不会出现第二个网页会话互相顶掉。
- 关闭浏览器前把站点下发的会话 cookie 补上有效期落盘——否则每次调用后登录即丢失。
- 登录落在 xiaohongshu.com 还是 rednote.com 因账号而异：登录成功时逐个复核，记在 profile 的 `site-host` 里，之后读取统一用它（`XHS_HOST` 可强制指定）。

**登录**
- `POST /api/v1/login/window`：打开小红书官方登录页（有界面），用户在官方页面扫码，成功后窗口自动关闭。
- `GET /api/v1/login/session`：登录进度（纯内存，不开浏览器，可随意轮询；旧的 `/login/status` 每次都会导航，会冲掉正在扫的二维码）。
- `POST /api/v1/login/logout`：清除本地 profile 里的登录。
- 全新 profile 的首页不会自动弹登录框：出码时自动点侧栏「登录」；游客态以 `loggedIn:false / guest:true` 持续 12 秒为准。
- 取二维码限时 45 秒，任何失败（含异常）都关闭浏览器、释放 profile 锁——修复前一次失败会让整个服务永久卡住。

**读取**
- `GET /api/v1/favorites`：当前账号的收藏列表（10 分钟限频）；收藏页签点击失败时换干净标签页重试，懒加载以「12 秒无新增」判定到底。
- `POST /api/v1/attachments/download`：在有界面的浏览器里点笔记附件页的「下载」（无界面时该下载请求会挂住）。
- 评论保留 `pictures`（评论图片）与 `audioInfo`（语音评论：音频地址、时长、站点自带转写 `asrText`、标签）。
- 读首屏评论前等待其加载（最多 10 秒）。

**防风控与不卡住**
- 识别「安全验证」拼图浮层即返回 `CAPTCHA_REQUIRED` 并停止，不重试、不尝试自动通过；`POST /api/v1/verify/window` 打开有界面的窗口供人手动完成。
- 扫码或验证进行中，其它会开浏览器的接口立即返回 409，不排队干等。

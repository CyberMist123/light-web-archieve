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
go vet ./...                          # 补丁自带全部源码（含 linkbrain_api.go、page_ready.go、third_party/headless_browser），干净基线上应无报错
go build -o link-brain-reader.exe .
go build -o relatedfile.exe ./cmd/relatedfile   # 附件探测用的游客浏览器小工具（Python 端会调用）
```

补丁不含本机调试用的私有小工具（`cmd/momologin`、`cmd/sessioncheck`、各种 `*probe`、`commentkeys`、`verifywin`、旧的 `attachdl`/`favdump`）；它们不影响编译。

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
- 抓全部评论只给 8 分钟：到点停下，把已经加载出来的评论交回，而不是整页超时、一条都拿不回来。

**安全**
- 默认只监听 `127.0.0.1:18061`（原版 `:18060` 对局域网开放）——这个服务握着小红书登录。
- 拒绝一切带 `Origin` 头的请求（即浏览器网页发起的），并去掉原版的 `Access-Control-Allow-Origin: *`：否则任何网页都能在后台读收藏、帮你退出登录。本机 Python / CLI 不带 Origin，不受影响。

**性能**
- 详情页等待关键容器出现，不再等整页 DOM 静止（取自原项目后续提交 ae5d1a2 的 `page_ready.go`）。

**防风控与不卡住**
- 统一风控检查：所有会开页的路径（收藏、入库主路 `get_feed_detail`、附件下载、登录号补看、登录检查）在导航后和关键步骤前都查一次。
  被跳到 `/website-login/*`（error、captcha 等）→ `ACCOUNT_RISK`；出现「安全验证」拼图浮层 → `CAPTCHA_REQUIRED`；
  需要登录的操作发现是游客 → `NOT_LOGGED_IN`。命中即停止本次操作、不重试、不尝试自动通过。MCP 报错文本里带方括号码（如 `[ACCOUNT_RISK]`）。
- 验证浮层按结构认，不扫整页文字：可见的验证组件（class/id/iframe 带 captcha），或固定定位浮层里一句短的「安全验证」加操作提示；
  笔记标题、正文、评论、收藏卡片里的字一律不算（收藏了一篇叫「手机号安全验证怎么办」的笔记不会把号判成撞了验证码）。
- 长循环里也查：抓全部评论每 3 轮、每次点「展开回复」前查一次，命中就整篇按风控失败（不拿半截数据当成功）；
  抽取前无论评论加载结果如何再查一次。滚收藏每 4 轮查一次；附件页每次（重）点「下载」前查一次。
- 一篇详情（导航 + 评论 + 抽取）总时限 = 锁看门狗上限 − 3 分钟（默认 12 分钟），评论预算给抽取留 150 秒，慢夜里不会读到一半被看门狗结束。
- 风控熔断：命中上面任一码就写 `<XHS_PROFILE_DIR>/risk-hold.json`（`{"code","since","detail"}`，重启服务后仍生效）。
  熔断期间一切会开浏览器的请求都被拒绝：REST 回 `423 {"code":"RISK_HOLD","hold":{…}}`，MCP 工具回 `isError` 且文本含 `[RISK_HOLD]`。
  只有三种方式解除：登录窗口（或远程扫码）成功、`POST /api/v1/verify/window` 人工验证完成、`POST /api/v1/risk/clear`。
  验证窗口按关窗前最后一次读到的页面判断：仍有风控就保持熔断；掉登录 / 安全跳转类熔断还要求看到已登录。
  取二维码时发现「已是登录态」只解除 `NOT_LOGGED_IN`。
  登录窗口、验证窗口、扫码、`/login/session`、`/login/logout`、`/risk/clear` 不受熔断拦截。
- 两道闸：请求进来时查一次；拿到浏览器锁之后、启动浏览器之前再查一次——排在锁后面等的请求，
  若前一个请求刚撞了风控，也回 `423 RISK_HOLD` / `[RISK_HOLD]`，不开浏览器。
- 读收藏一次请求最多试 2 次，只在「收藏页签没点中」这种纯前端问题时重试；重试前先查风控、再像人一样歇 20–40 秒。
- `GET /api/v1/login/session` 多报两项：`risk_hold`（熔断对象或 null）和 `lock`（浏览器锁被谁占、从几点起、占了几秒，或 null）。它仍然不拿锁、不开浏览器，服务卡住时也能秒回。
- 关浏览器有上限：落盘会话 cookie ≤10 秒、关闭 ≤20 秒，超时就杀掉整棵浏览器进程树并强制释放锁（以前会无限等 Chromium 退出，锁永远不放）。
- 锁看门狗：浏览器锁被占超过 `XHS_LOCK_MAX_S`（默认 900 秒）就记日志、杀掉浏览器并以退出码 75 结束进程，交给调用方重新拉起。
- 登录窗口 / 验证窗口拿浏览器锁最多等 60 秒，拿不到或窗口里出错都会收尾为失败，状态不会永远停在「等待扫码」；5 分钟扫码时限从拿到锁之后才开始算（`/login/session` 的 `expires_at` 同步改成真实截止时间，调用方应按它等）。验证窗口最长 12 分钟。

**测试**
- `go test ./...`：不开浏览器（启动被桩替换）。
- `go test -tags localbrowser -run LocalBrowser . ./xiaohongshu`：用内置浏览器（无界面、临时 profile、挂死代理只通本机）打开本机假站点，
  验证风控探针和真实入口（读收藏、登录检查、MCP 读详情）的接线。不访问小红书。
- 扫码或验证进行中，`/api/v1/*` 下其它会开浏览器的接口立即返回 409，不排队干等（`/mcp` 的工具调用不在此列，会排在浏览器锁后面）。

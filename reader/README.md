# link-brain-reader（读取组件）

Link Brain 所有需要小红书登录的操作（读笔记与评论、私密收藏、附件下载、扫码登录）都经由这个本地服务。
它是 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 的修改版，以补丁形式放在这里：

- 基线：xiaohongshu-mcp 提交 `c2fc4dde2c45f26f6f9de288b7423a2bdfa7af1c`
- 补丁：[`link-brain-reader.patch`](link-brain-reader.patch)

原项目以 Apache License 2.0 发布，版权归原作者所有；本补丁同样以 Apache License 2.0 提供。下面列出所有改动。

## 预编译件（推荐）

不想装 Go 的，直接用 GitHub Releases 里的 `reader-v*`（Windows x64）。插件首次引导点「安装读取组件」会自动下载并校验；也可以命令行 `python -m link_brain reader install`（不带参数 = 用程序内置的地址和 sha256）。下面的编译步骤只在你要改补丁时需要。

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
- 关闭浏览器前仅为非空的 `web_session` 会话 Cookie 补 30 天有效期；安全令牌不延期，已有持久 Cookie 不续期。站点域名按 DNS 边界匹配。
- 登录完成后在本次实际域名复核同一账号，确认后记入 profile 的 `site-host`；不再循环探测另一个域名的旧会话。`XHS_HOST` 可显式指定，但必须与确认的登录域名一致。

**登录**
- `POST /api/v1/login/window`：打开小红书官方登录页（有界面），用户在官方页面扫码，成功后窗口自动关闭。
- `GET /api/v1/login/session`：登录进度（纯内存，不开浏览器，可随意轮询；旧的 `/login/status` 每次都会导航，会冲掉正在扫的二维码）。
- `POST /api/v1/login/logout`：清除本地 profile 里的登录。
- 全新 profile 的首页不会自动弹登录框：出码时自动点侧栏「登录」；游客态以 `loggedIn:false / guest:true` 持续 12 秒为准。
- 取二维码限时 45 秒，任何失败（含异常）都关闭浏览器、释放 profile 锁——修复前一次失败会让整个服务永久卡住。

**读取**
- `GET /api/v1/favorites[?expect=N]`：当前账号的收藏列表（10 分钟限频）。判底看页面状态里的「还有更多」（`hasMore=false` 才算读全）；页面不给 `hasMore`、条数又明显低于调用方给的基准 `N` 时换滚法再试（四级），滚动间隔带抖动；一次请求最多滚到底 1 次，滚动预算 420 秒、请求上限 10 分钟。响应如实带 `partial` / `stop_reason` / `has_more` / `scroll`，读不全不当全量交出去。
  - 前兆即停（「点不动」「卡住」多半是收藏接口开始拒绝，不再加码）：收藏页签第 1 轮拟人点击没生效 → 查一次风控、落证据、在原页面歇 20–40 秒；点第 2 次之前先只读看一眼——第 1 次点击已经迟到生效就不再点，收藏接口已经回了拒绝也不再点；否则再拟人点 1 次（不用 DOM 合成点击、不换新页、不再做第二次登录检查），还不生效就回 `503 FAV_TAB_STUCK`（「页签点不动，疑似小红书在限流，今晚先不读收藏」，不写熔断）；条数停住而页面说还有更多时最多换第 1 级滚法（往回滚一截），还不动就停（`stop_reason=stalled`，partial），不上真实滚轮，卡住期间每轮都查风控。
  - 增量读（1011）：`POST /api/v1/favorites`，body `{"expect": N, "known_ids": [...], "stop_after_known": K}`——从最新往下滚，列表里连着出现 K 篇（夹在 5–200）调用方已知的笔记就停，`stop_reason=known_streak`、`partial=false`、`incremental=true`；不给 `known_ids` 等于全量。`GET` 一字不变（老调用方照旧）；坏 body 回 400、不吃限频。
  - 读收藏时监听收藏接口回包（只读浏览器内存）：接口回了拒绝（HTTP ≥400 或 `success=false`）就立即停（`stop_reason=api_refused`，partial）；页面上的「还没有收藏」若是被拒后的占位，不当成空收藏交出去。
  - 滚动途中页面里出现看不见的验证组件（见下「防风控」）：立即停，已读到的按 partial 交回（`stop_reason=hidden_widget`），不写熔断；还没开始滚就碰上，回 `503 HIDDEN_WIDGET`（「页面里有验证组件但没显示滑块，这次先停，下次照常读」）。
- 评论逐楼展开：前 `limit` 楼（默认 10）每楼的回复连点「展开」到底；预算在各楼之间轮转分配（每档 30 条），点之前把按钮滚进视口、点不动退回 DOM click 并退避重试，疑似限频就歇一段；整个请求预算默认 540 秒（参数 `comment_budget_s` / `comment_config.budget_s`，每楼回复上限 `max_replies_per_floor`，0 = 全部）。响应 `comment_load` 如实带 `floors_loaded`、`floors_expanded`、每楼缺多少（`replies_partial`）、判停原因和用时。
  楼中楼单独限速（1015：10-12 起的「熔断」全是展开楼中楼 `comment/sub/page` 被回 300013「访问频繁」）：只展开前 10 楼的回复（其余楼进 `replies_partial`，`reason=expand_cap`，不算 partial；续读 `expand_floors` 不受限），每次点「展开回复」前歇 4–9 秒（偶尔再多 5–10 秒）。
  - 状态里 `subCommentHasMore` 会陈旧地停在 true：楼里没有「展开」按钮且已加载 ≥ 楼上显示数，就算展开到底（计入 `floors_expanded`）；缺口为 0 的楼不进 `replies_partial`。
  - 续读 `expand_floors`（MCP 参数，或 REST `comment_config.expand_floors` / 顶层 `expand_floors`；一级评论 `comment_id` 列表）：只展开这些楼的回复（自动展开，不受 `limit` 限制），其它楼不点也不列；一级评论滚到这些楼都出来（或到底 / 预算尽）。`partial`、`replies_partial`、`replies_missing`、`floors_expanded` 只按这些楼算；页面上没找到的 id 列在 `comment_load.floors_not_found`（滚到底仍没有不算 partial）。不传 = 原行为。
  - 断点续展 `expand_resume`（1017，配合 `expand_floors`；每项 `comment_id:cursor:have`）：网页版每次打开，楼中楼都只带第 1 条，从头点要把存过的再点一遍，一小时额度永远够不着几百条以后的回复。带了它，点这楼之前先把页面状态里这楼的 `subCommentCursor` 改成 `cursor`（已存的最后一条回复 id；站点「展开回复」就拿它请求 `comment/sub/page`），点一下就接着往后拉；读数按 `have` 补偿，缺口照算，`comment_load.resumed` = 续上的楼数。游标写不进去就从头展开。展开过的楼 `hasMore` 认站点写的 `hasMore`（首屏的 `subCommentHasMore` 会陈旧地停在 true）。
  - 一级评论续翻 `floors_resume`（1017，`cursor:have`）：首屏评论落地后把页面的 `comments.cursor` 改成已存的最后一楼，往下滚就从那之后接着拉（热门帖 8 分钟只滚得到 ~500 楼，不续永远到不了底）；楼数读数按 `have` 补偿，`comment_load.floors_resumed_from` = 从第几楼接着翻。
  - 楼中楼每小时额度（1017）：默认 30 次（`XHS_SUB_PER_HOUR`）；`<XHS_PROFILE_DIR>/sub-per-hour.json` 写 `{"per_hour": N}` 可临时调高（最多 120），撞到任何熔断（限频 / 验证 / 账号异常）服务自己删掉这个文件、退回默认。
- `POST /api/v1/attachments/download`：在有界面的浏览器里点笔记附件页的「下载」（无界面时该下载请求会挂住）。
- 网页版限制的笔记（1011：收藏里有、浏览器里打开要「验证一下」，详情页上没有这篇）：先照旧过风控检查和错误容器；都不是、
  页面状态里又没有这篇时——页面上有登录框 → `NOT_LOGGED_IN`（写熔断）；落在登录类页面 → 不判（原样报错）；其余 → `NOTE_RESTRICTED`：
  只是这一篇、**不写熔断**，落一份证据（`trigger=note_restricted`）。关键容器没出现时再等 6 秒，判定后就停，不在空页面上滚评论。
  REST 回 `422 {"code":"NOTE_RESTRICTED"}`（详情、附件下载——附件在笔记页那一步就停，不再去附件页），MCP 报错文本带 `[NOTE_RESTRICTED]`。
- `POST /api/v1/notes/search-token` `{note_id, keyword}`：用标题搜一次，按笔记 id 从搜索结果里认出这篇，回 `{found, xsec_token, count}`
  （拿新口令再开一次用）。搜索页导航后、读完都查风控（MCP `search_feeds` 也一并补上）。节奏（每篇每天一次、开页间隔、账号锁）由调用方管。
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
- 验证浮层按结构认，不扫整页文字：验证组件（class/id/iframe 带 captcha），或固定定位浮层里一句短的「安全验证」加操作提示；
  笔记标题、正文、评论、收藏卡片里的字一律不算（收藏了一篇叫「手机号安全验证怎么办」的笔记不会把号判成撞了验证码）。
  「看得见」要真看得见：与视口有交集，祖先链没有 `display:none` / `visibility:hidden` / 透明、没被 `clip` / `clip-path` 裁没，
  可见部分中心点 `elementFromPoint` 命中它自己或子孙（没被盖住）；占满视口的大容器（`html` / `body` / `#app` 一类）里得有验证内容
  （iframe / canvas / img 或「验证 / 拖动 / 滑块」字样，且总字数少）才算。看到后隔 1.5 秒再读一次仍在，才按 `CAPTCHA_REQUIRED` 停车写熔断。
- 看不见的验证组件（DOM 里有验证组件但没画出来：在屏幕外、祖先透明、被盖住、被裁、`display:none` 但里面有验证内容；
  或者出现了一下 1.5 秒内又没了）→ `HIDDEN_WIDGET`：停下本次操作、落证据，**不写熔断**；REST 回 `503`，MCP 报错文本带 `[HIDDEN_WIDGET]`。
  空的、藏起来的占位容器不算。验证窗口里只认看得见的验证。
- 长循环里也查：抓全部评论每 3 轮、每次点「展开回复」前查一次，命中就整篇按风控失败（不拿半截数据当成功）；
  抽取前无论评论加载结果如何再查一次。滚收藏每 4 轮查一次（列表卡住时每轮查）；附件页每次（重）点「下载」前查一次。
  这些检查一律用一份新的 5 秒时限读页面，不受调用方早已用完的时限影响；读不到页面按「看不出风险」处理，但记日志、记进下一份证据。
- 出事证据：撞风控、看不见的验证组件、收藏页签第 1 轮没点中、收藏列表卡住、收藏接口回拒绝这几个时刻，把程序看见的页面落到
  `~/.link-brain/risk-evidence/<YYYYMMDD-HHMMSS>/`（`LINK_BRAIN_EVIDENCE_DIR` 或 `$LINK_BRAIN_HOME/risk-evidence` 可改）：
  `shot.png`（视口截图，不改视口、不发请求）、`hit.html`（开头一行 CSP，打开也不去拉小红书的资源；连同命中元素 outerHTML 共 ≤2KB）、
  `meta.json`（地址、子页签、程序要去的子页签、命中原因与复读结论、命中元素位置与祖先链样式、中心点是不是它自己、
  「收藏」页签中心被谁挡住、收藏接口的 HTTP 状态和 code/msg、最近一次读页失败）。
  只读页面、只存本机，保留 14 天自动删（落证据、启动、`/login/session` 被轮询时最多每小时清一次；目录里有别的文件就不删）；
  截图里有私密收藏，不要导出。
- 一篇详情（导航 + 评论 + 抽取）总时限 = 锁看门狗上限 − 3 分钟（默认 12 分钟），评论预算给抽取留 150 秒，慢夜里不会读到一半被看门狗结束。
- 限频冷却（1015）：被跳到 `/website-login/error?error_code=300013`（「访问频繁，请稍后再试」）判 `XHS_RATE_LIMITED`，不当 `ACCOUNT_RISK`。照样写 `risk-hold.json`，但带 `until`（冷却到几点）和 `strikes`（24 小时内第几次）：第 1/2/3 次分别冷却 2/4/6 小时，冷却期内拦请求（423，`details` 写明「不用处理」）；到点后放行请求当自探（`/login/session` 的 `risk_hold.probing=true`），第一个成功（2xx / MCP 非错误）的请求自动解除；自探又被限频进下一档；第 4 次升级成 `ACCOUNT_RISK` 要人处理。限频计数在 `rate-limit-strikes.json`，人工解除（扫码 / 验证窗口 / `risk/clear`）时清零。新撞上时回 `429 XHS_RATE_LIMITED`。
- 风控熔断：命中 `ACCOUNT_RISK` / `CAPTCHA_REQUIRED` / `NOT_LOGGED_IN` 就写 `<XHS_PROFILE_DIR>/risk-hold.json`（`{"code","since","detail"}`，经页面探针撞上的另带出事页面 `url`、子页签 `tab`、程序要去的子页签 `want_tab`、证据目录 `evidence`；重启服务后仍生效）。
  熔断期间一切会开浏览器的请求都被拒绝：REST 回 `423 {"code":"RISK_HOLD","hold":{…}}`，MCP 工具回 `isError` 且文本含 `[RISK_HOLD]`。
  HTTP 里的熔断对象不带 `url`（含本号主页和 `xsec_token`，只留给验证窗口用）；`423` 里也不带证据目录，只有 `/login/session` 带。
  只有这几种方式解除：登录窗口（或远程扫码）扫码成功、`POST /api/v1/verify/window` 人工验证完成、`POST /api/v1/risk/clear`，以及（1011，只限验证码类）`POST /api/v1/risk/probe` 冷却后自查干净（见下）。
  验证窗口不再「关窗即解除」：没有熔断时不开窗（回 `result:"no_hold"`）；有熔断就打开出事的那一页（去掉 `tab` 参数，不让页面自己去读收藏），出事时在收藏页签、或正要去收藏页签的，页面顶部提示「请点一下『收藏』页签看看有没有滑块」（窗口不替你点；出事页面不是主页时从首页经侧栏「我」进主页）。
  解除都要求关窗前页面干净且看到已登录；验证码 / 安全跳转类另要求窗口里**出现过**验证（她真拖过了）；从头到尾没出现过就保持熔断，`/login/session` 给 `verify_result:"no_captcha_seen"`，由人确认没事后 `POST /api/v1/risk/clear`。连续两次读不到窗口才算关窗；有提示时每秒看一眼。
  取二维码时、或登录窗口一打开就发现「已是登录态」（没扫码），只解除 `NOT_LOGGED_IN`。
  笔记验证窗口（1011）：`POST /api/v1/verify/window` 带 `{note_id, xsec_token}` 且**没有熔断**时，开有界面的浏览器到这一篇（响应 `mode:"note"`），
  她过完验证、看到笔记就关窗；关窗前页面上还要验证 / 被跳到安全页 → 按风控写熔断（`still_risk`），有登录框 → `NOT_LOGGED_IN`，
  窗口里看到过这篇正常渲染 → `note_ok`，否则 `note_not_seen`；`/login/session` 多给 `verify_note`（`note_id` / `ok` / 当时地址里的口令）。
  有熔断时一律先走熔断验证（`mode:"hold"`）。
- 冷却后自查（1011）：`POST /api/v1/risk/probe`（body 可带 `{"cooldown_s": 2700}`）——第四条、单独的解除路，`risk/clear` 语义不变：
  只认 `CAPTCHA_REQUIRED`（掉登录 / 安全跳转回 `result:"not_captcha"`，什么都不做）；熔断写下后不满冷却（调用方给的数，服务端下限 30 分钟）回 `cooling` + `retry_after_s`、不开页；
  同一次熔断两次自查至少隔 20 小时（开页前把 `auto_probe_at` 落进 `risk-hold.json`，重启也算数），再来回 `already_probed`；
  自查 = 用号开一页本号主页（出事页面就是本号主页时去掉 `tab` 直开，否则从侧栏「我」进），不点页签、不滚动、不读收藏，过统一风控检查（看不见的验证组件也当「还在」）+ 读登录态；
  干净且已登录才解除（日志写「冷却后自查无验证，自动恢复」），还有验证 `still_risk` / 是游客 `not_logged_in` / 读不到 `not_read` 一律保持；浏览器被别的操作占着回 `window_failed`、不算查过。
  熔断中放行；扫码 / 验证窗口开着照旧 409。结论进 `/login/session` 的 `auto_probe`。
  登录窗口、验证窗口、扫码、`/login/session`、`/login/logout`、`/risk/clear` 不受熔断拦截。
- 两道闸：请求进来时查一次；拿到浏览器锁之后、启动浏览器之前再查一次——排在锁后面等的请求，
  若前一个请求刚撞了风控，也回 `423 RISK_HOLD` / `[RISK_HOLD]`，不开浏览器。
- 读收藏一次请求只进 1 次收藏页签，不换新页重试（见上面「前兆即停」）。
- `GET /api/v1/login/session` 多报几项：`risk_hold`（熔断对象或 null：`code` / `since` / `detail` / `tab` / `want_tab` / `incident_page` / `evidence`）、`lock`（浏览器锁被谁占、从几点起、占了几秒，或 null），以及最近一次验证窗口的结论 `verify_result`（`cleared` / `no_captcha_seen` / `still_risk` / `not_read` / `not_logged_in` / `no_hold` / `window_failed`）、`verify_finished_at`、`verify_hold_since`（那次针对的熔断的 `since`）。它仍然不拿锁、不开浏览器，服务卡住时也能秒回。
- 关浏览器有上限：落盘会话 cookie ≤10 秒、关闭 ≤20 秒，超时就杀掉整棵浏览器进程树并强制释放锁（以前会无限等 Chromium 退出，锁永远不放）。
- 锁看门狗：浏览器锁被占超过 `XHS_LOCK_MAX_S`（默认 900 秒）就记日志、杀掉浏览器并以退出码 75 结束进程，交给调用方重新拉起。
- 登录窗口 / 验证窗口拿浏览器锁最多等 60 秒，拿不到或窗口里出错都会收尾为失败，状态不会永远停在「等待扫码」；5 分钟扫码时限从拿到锁之后才开始算（`/login/session` 的 `expires_at` 同步改成真实截止时间，调用方应按它等）。验证窗口最长 12 分钟。

**测试**
- `go test ./...`：不开浏览器（启动被桩替换）。
- `go test -tags localbrowser -run LocalBrowser . ./xiaohongshu`：用内置浏览器（无界面、临时 profile、挂死代理只通本机）打开本机假站点，
  验证风控探针（看得见 / 看不见的验证组件、出现又消失）和真实入口（读收藏、登录检查、MCP 读详情、验证窗口）的接线，以及出事证据落盘、
  页签点不动 / 列表卡住 / 收藏接口被拒即停、动作时限过期后风控检查照样读得到页面。不访问小红书。
- 扫码或验证进行中，`/api/v1/*` 下其它会开浏览器的接口立即返回 409，不排队干等（`/mcp` 的工具调用不在此列，会排在浏览器锁后面）。


## 登录维护与换号（2026-10-28）

登录窗口和远程二维码共用账号身份复核。验证码尚在时不报告成功；账号风险/验证熔断期间不新开扫码，登录成功只解除未登录熔断。选择“切换账号”会先主动退出认证 Cookie，再由用户扫码；设备标识与 Profile 保留。普通状态检查不会自动转入扫码，定时检查使用 `scripts/xhs-login-check.ps1` 的浅查模式。

旧版本错误延期的安全 Cookie 可使用 `clean_legacy_session_cookies.py --profile <目录>` 离线预览；确认后加 `--apply`。需要 Reader 和关联浏览器完全关闭，工具先完整备份，只清理三种已知安全 Cookie 中具有旧 30 天特征的持久项，保留认证凭证、设备数据和备份；重复执行会跳过。日期特征不能绝对证明 Cookie 来源，先看预览，不自动清理。

当前补丁已经包含 reader-15 至 reader-20 演进的最终实现以及登录修复；已撤销的探针和自动重试不会重新引入。补丁在干净上游上应用后通过 `go test ./...`、`go vet ./...` 和编译。登录相关真实 Chromium 离线验收可用：

```powershell
go test -tags localbrowser ./browser ./xiaohongshu -run 'TestLocalBrowserCookiePersistence|TestLocalBrowserLoginPolicy' -count=1
```

# 远程 MCP：让 claude.ai / ChatGPT 从外面连上你的收藏库

> 懒人版。示例里的 `lwa.example.com`、`example.com` 都是占位，换成你自己的。

远程 MCP 服务跑在你自己的电脑上，**只监听 `127.0.0.1:18071`**（端口可在设置里改），外网直接访问不到。
claude.ai / ChatGPT 在云端，要连它，需要一个 **https 公网地址** 把请求转进本机——这就是「域名 + 隧道」。

```
claude.ai / ChatGPT ──https──> lwa.example.com ──隧道──> 你电脑上的 127.0.0.1:18071
```

整件事只有三步：**① 搞一个 https 地址 → ② 填进 Obsidian 设置 → ③ 在 claude.ai / ChatGPT 里添加连接器并输口令。**

---

## 方案 A（推荐）：已有域名 + Cloudflare 命名隧道

前提：你有一个域名，并且它的 DNS 托管在 Cloudflare（免费套餐就够）。

1. **装 cloudflared**（Windows）：`winget install --id Cloudflare.cloudflared`
2. **登录**：`cloudflared tunnel login`（浏览器里选你的域名，授权一次）
3. **建隧道**：`cloudflared tunnel create lwa`（记下输出的隧道 ID）
4. **把子域名指向隧道**：`cloudflared tunnel route dns lwa lwa.example.com`
5. **写配置** `%USERPROFILE%\.cloudflared\config.yml`：

   ```yaml
   tunnel: lwa
   credentials-file: C:\Users\<你>\.cloudflared\<隧道ID>.json
   ingress:
     - hostname: lwa.example.com
       service: http://127.0.0.1:18071
     - service: http_status:404
   ```

   已经有一条隧道在跑别的服务？不用新建，在它的 `ingress` 里**加一行** `hostname: lwa.example.com → http://127.0.0.1:18071`（放在最后那条 `http_status:404` 之前），再执行第 4 步把子域名指过去。
6. **常驻**：`cloudflared service install`（开机自动跑），或先 `cloudflared tunnel run lwa` 手动试。
7. 回到 Obsidian → Link Brain 设置 → **远程 MCP → 连接 → 域名** 填 `https://lwa.example.com`，然后在「状态」点 **测试公网**，看到「公网通了」就好。

> 用的是 Cloudflare 网页面板（Zero Trust → Networks → Tunnels）也一样：Public Hostname 填 `lwa.example.com`，Service 填 `HTTP` + `127.0.0.1:18071`。

**别开 Cloudflare Access（登录墙）** 挡在这个子域名前面：claude.ai / ChatGPT 的服务器过不了它的登录页。这个服务自己有 OAuth + 口令把关。

## 方案 B：没有域名 —— Tailscale Funnel

1. 装 Tailscale 并登录；在管理后台给这台机器开 **HTTPS** 和 **Funnel**。
2. 运行：`tailscale funnel --bg 18071`
3. 它会给你一个固定地址 `https://<机器名>.<你的 tailnet>.ts.net`，填进 Obsidian 的「域名」，点「测试公网」。

地址固定、免费、不用买域名；缺点是域名长、Funnel 的带宽有限（看收藏完全够用）。

## 为什么不推荐 trycloudflare 临时地址

`cloudflared tunnel --url http://127.0.0.1:18071` 能一条命令得到 `https://xxx.trycloudflare.com`，看着最省事，但：

- **每次重启都换网址**：设置里的域名要跟着改，claude.ai / ChatGPT 里已加的连接器全部失效、要删了重加、重新授权。
- Cloudflare 明说它是**测试用、不保证可用**，随时可能限流或断。
- 网址是随机的，你没法知道它什么时候变了——远程连接会无声地断掉。

只想临时试一下能不能连通，可以用；长期用请选 A 或 B。

---

## 连上之后

- **连接地址** = `https://你的域名/mcp`（设置页「连接」里有复制按钮）。
- **claude.ai**：设置 → Connectors → Add custom connector → 粘连接地址 → Connect → 授权页里粘贴口令 →「允许连接」。
- **ChatGPT**：设置 → Apps & Connectors → 开 Developer mode → Create → 粘连接地址、认证选 OAuth → 授权页里粘贴口令。
- **口令**：设置页「口令」点「随机生成」（自动复制）；以后要再用点「复制口令」。口令用 Windows 账户加密存在本机，不进插件设置、不进仓库。
- **本机的 Claude Code / Claude 桌面**不需要这些：设置页「连接」里复制 stdio 命令即可，不走网络、不要口令。

## 常见报错（「测试公网」给的提示）

| 提示 | 多半是 |
|---|---|
| 公网不通（ConnectError / 解析失败） | 域名没指到隧道，或 cloudflared / tailscale 没在跑 |
| 530 | Cloudflare 找不到隧道：cloudflared 没在跑或隧道被删了 |
| 502 | 隧道通了，但本机服务没在跑，或隧道指的端口和设置里的不一致 |
| 503 | 服务在，但设置里「启用」关着 |
| 403 | 设置里的域名和实际访问的域名不一致（服务只认登记过的域名） |
| 能连上但 issuer 不对 | 隧道指到了别的服务 |

## 安全边界（不用记，知道有就行）

- 服务只认设置里登记的域名和本机；不发 CORS；授权必须 PKCE；口令错 5 次锁 15 分钟。
- 客户端只能读到你在「权限」里勾选的文件夹；`.obsidian`、隐藏文件夹、插件设置、密钥文件、数据库、日志永远读不到；不跟随链接 / 联接点。
- 每次访问记一行日志（时间、谁、哪个工具、路径、结果），不记查询内容；设置页「高级 → 最近访问」能看。
- 任何时候可以在「状态」里单独吊销某个客户端，或「撤销全部访问」。

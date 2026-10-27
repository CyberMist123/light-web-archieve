# 登录态修复验收（2026-10-27）

本分支配套独立 Reader 修复：仅持久化 web_session、按真实登录域名及账号身份复核、风险期间拒绝新登录、移除出码前清凭证和双域重试。Cookie 策略位于 Reader 的 browser/cookie_policy.go；现有 reader/link-brain-reader.patch 尚未导回这些变更，不可仅应用旧补丁构建本次修复。

Python 登录超时不再自动重启重试；缺账号 ID 不保存身份；风险期间不执行换号。scripts/xhs-login-check.ps1 为浅查且静默的定时检查入口。reader/clean_legacy_session_cookies.py 为默认只预览的离线维护工具，执行前备份，只匹配已知安全 Cookie 的旧 30 天特征。

针对性测试：58 passed。SQLite 迁移测试使用合成数据库，检查备份保留、认证/设备 Cookie 保留、限定删除及一次性执行。Reader 默认 Go 全套和 go vet 通过，真实 Chromium 仅访问本机假站点，通过 Cookie 重启和登录状态用例。

发布标准 P9/P12：本次代码尚未部署，真实账号登录保持、切换账号和 Obsidian 入口未验收；不能宣布真实登录已恢复。账号风险仍需用户处理，不自动清熔断。全库 Python 回归：2532 passed、2 skipped（544.86 秒）；随后补充的两个账号用例与相关测试共 58 passed。

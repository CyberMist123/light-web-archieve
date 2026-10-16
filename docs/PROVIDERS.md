# 模型提供商：控制台 / 用量 / 余额 / 充值（2026-10-16 核对）

设置页「模型与提供商 → 用量与余额」和问题面板「key 失效 / 欠费」那条的跳转按钮，网址都从 `link_brain/pricing.json` 的 `providers` 读（改网址只改那里）。
控制台页面都要在浏览器里登录；没登录时会先跳登录页，这不算网址错。

## 网址表

| 提供商 | 用途 | 网址 | 怎么核对的（2026-10-16） |
|---|---|---|---|
| DeepSeek | 控制台首页 | https://platform.deepseek.com/ | 浏览器打开，未登录跳 `/sign_in` |
| DeepSeek | 用量 | https://platform.deepseek.com/usage | 站点前端路由表 `USAGE="/usage"`（打包脚本里读到） |
| DeepSeek | API key | https://platform.deepseek.com/api_keys | 同上 `API_KEYS="/api_keys"` |
| DeepSeek | 账单 / 明细 | https://platform.deepseek.com/transactions | 同上 `TRANSACTIONS="/transactions"` |
| DeepSeek | 充值 | https://platform.deepseek.com/top_up | 同上 `TOP_UP="/top_up"` |
| DeepSeek | 余额接口 | `GET https://api.deepseek.com/user/balance` | 不带 key → 401；带本机 key 实测 200 |
| 通义千问（百炼） | 控制台首页 | https://bailian.console.aliyun.com/cn-beijing/ | 浏览器打开 200（页内登录） |
| 通义千问（百炼） | API key | https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key | 旧链接 `?tab=model#/api-key` 打开后自动跳到这里 |
| 通义千问（百炼） | 模型用量 | https://bailian.console.aliyun.com/cn-beijing/costing-balance/usage-statistics | 侧栏「费用用量 → 模型用量」点进去的地址 |
| 通义千问（百炼） | 费用概览 | https://bailian.console.aliyun.com/cn-beijing/costing-balance/overview | 浏览器打开，侧栏有 免费额度 / 模型限额 / 模型用量 / 费用概览 / 预算管理 |
| 阿里云 | 充值 | https://usercenter2.aliyun.com/finance/fund-management/recharge | curl 200 → 登录页；百炼控制台脚本里引用的就是这个地址 |
| 阿里云 | 费用中心首页（余额） | https://usercenter2.aliyun.com/home | curl 200 → 登录页 |

## 余额能不能查

- **DeepSeek**：能。`GET /user/balance`，`Authorization: Bearer <key>`，回 `{is_available, balance_infos: [{currency, total_balance, granted_balance, topped_up_balance}]}`（金额是字符串）。
  用问收藏 / 概要里配的 DeepSeek key（`usage._deepseek_key`），10-16 实测能查到。
- **通义千问（百炼）**：拿 DashScope API key（`sk-…`）**查不了**。唯一的接口是阿里云 BSS OpenAPI `QueryAccountBalance`，要 AccessKey ID / Secret——按约定不收 AK/SK，界面只给「充值」「看用量」跳转。

## 记账与金额

- 每次调模型接口记一行到 `vault/_archive/usage/YYYY-MM.jsonl`（`link_brain/usage.py`，CONVENTIONS §4 规则 9）。
- 金额按 `pricing.json` 现价在汇总时折算；DeepSeek 按调用时刻分高峰 / 空闲价（法定节假日不认，按高峰算）。价格表里没有的模型金额显示「—」，不编。
- 10-16 补进价格表（百炼 model-pricing 页，华北 2）：`qwen3.7-text-embedding-flash` 0.125 元 / 百万 token、`text-embedding-v4` 0.5、`qwen3-rerank` 0.5（都只收输入）。
- 语音转写（OpenAI 兼容接口）按音频秒数记；`whisper-1` 官方已不列价，金额「—」。本机 CapsWriter / 本机命令行模型不花钱。

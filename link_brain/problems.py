"""唯一问题记录（CONVENTIONS §2 / §3）：`vault/_archive/problems.jsonl` + 故障码分类 + 显示登记表。

一行一条，append-only：
    {"ts", "key", "step", "item_id", "title", "code", "reason", "action", "next_at", "count", "resolved_at", "notified"}
- key = `step|item_id|细分码`（item_id 为空 = 步骤级问题），`load()` 按 key 折叠：最新一行为准、count 累加；
  「已解决」= 再追加一行同 key 带 resolved_at；之后同 key 再出现就是新的一轮（count 从头算）。
- 超过 500 行时在锁里压实为最近 500 个 key（每个 key 一行折叠后的结果：count / days / notified 都保留）。

故障码 = `类.细分`，四类：TRANSIENT（自动退避重试）· PERMANENT（记原因、不再重试、不推送）·
NEEDS_HUMAN（只报一次）· SKIPPED（未配置 / 已关闭 / 预算到了：进记录、不算失败、角标不计数）。
现有的裸码（ReaderError.code、sync-status.json.code，如 `NOT_LOGGED_IN`）格式不变，由 `classify` 推出类。

推送只有一个出口：`report()` 内部判定——
- NEEDS_HUMAN：同一步骤 + 同一细分码还有没解决、已推过的，就不再推（同一把 key 失效 50 篇只推一次）；
- TRANSIENT：同 key 在连续 3 个日历日都出现 → 追加一条同 step + item_id 的 NEEDS_HUMAN.STUCK（卡片上看得到是哪篇），
  推送同样按「同一步骤」去重（50 篇一起卡住只推一次）；那一篇 / 那一步 resolve 时 STUCK 一起标已解决。
- 账号类码（掉登录 / 验证 / 风控 / 熔断 / 登错号 / 没装组件）不管哪一步撞见，report_blocked 都记在 step=login。
推送走 alert._alert（模块私有，仓内只有这里调；tests/test_problems_alert_exit.py 扫源码守住）。

第 4 批：17 处报警已全部迁到这里；每次写成功后同锁刷新 `_archive/problems-summary.json`（页面顶部入口读它）。

10-04 当场自愈：每个非风控码的修复动作在 `repair.py`（`repair.plan(row)`）；夜跑收尾的自愈轮和面板「现在修」都走它。
修复过程写成同 key 的「注记行」（`annotate`，`note: true`）：不加次数、不算出现日，只带 repair_state / repair_note。
"""

from __future__ import annotations

import itertools
import json
import os
import platform
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import domain, storage
from .errtext import errtext

FILE_NAME = "problems.jsonl"
SUMMARY_NAME = "problems-summary.json"
MAX_KEYS = 500
# 压实留余量：超过 MAX_KEYS + COMPACT_SLACK 行才压回 MAX_KEYS（压完正好 MAX_KEYS 行时，不至于每登记一次就整份重写）
COMPACT_SLACK = 100
LOCK_WAIT_S = 5
PENDING_DIR = "problems.pending"
REASON_MAX = 320  # 1008：AI 接口归并那一条要写清 哪个 key / 原因 / 处理 / 影响几篇 / 花费，放宽
TITLE_MAX = 120
STUCK_DAYS = 3
# key 失效 / 欠费：产品规则是「连续几晚没修好」才推——至少在这么多个日历日出现过才推（列表里一直看得到）
DELAYED_PUSH = {"AUTH_FAILED", "QUOTA_EXCEEDED"}
DELAYED_PUSH_DAYS = 2
DAYS_KEPT = 7  # 每个 key 记住最近几个出现过的日历日（压实后也不丢）

CLASSES = ("TRANSIENT", "PERMANENT", "NEEDS_HUMAN", "SKIPPED")
ACTIONS = ("gave_up", "retry_later", "retrying", "needs_human", "skipped")
DEFAULT_ACTION = {"TRANSIENT": "retry_later", "PERMANENT": "gave_up", "NEEDS_HUMAN": "needs_human",
                  "SKIPPED": "skipped"}
STEPS = ("sync.favorites", "ingest", "attachments.download", "attachments.convert", "attachments.recheck",
         "enrich.summary", "vision.layer1", "vision.refine", "videos.transcribe", "embed", "ask", "login", "config", "remote",
         # 1008：AI 接口故障归并到能力级（ai_health.py），一个原因一条
         "ai.summary", "ai.vision", "ai.refine", "ai.embed", "ai.ask",
         # 批次 D · F1-d：笔记页被手改坏了（restore --scan 只读检查）
         "render.check",
         # 1009：评论补齐（设置楼数内的楼中楼连着几次补不上）
         "comments.fill",
         # 1011：这篇在小红书网页版要验证才能看（只是这一篇，不是号出事；link_brain/restricted.py）
         "note.restricted",
         # 1024：本机 MCP 服务（mcp_server）里工具 / 协议层漏出来的异常
         "mcp")
STEP_PREFIXES = ("nightly.", "cli.")  # cli.<子命令>：命令行兜底登记的未知崩溃（cli.main）
# 推送标题 / 问题列表里给人看的步骤名（夜跑步骤 nightly.<名> 显示「夜跑：<名>」）
# 注记行（annotate）能改的字段：自愈动作的状态（running / failed / waiting）、一句「试过什么、为什么没好、下一步」、
# 什么时候修的、预计几分钟
NOTE_FIELDS = ("repair_state", "repair_note", "repair_at", "repair_eta_min",
               # 1008（B1 A2）：验证窗口关窗后的结论（读取服务 /login/session 的 verify_result）与时刻，面板据此给「没看到验证，恢复」
               "verify_result", "verify_at")
# 1008（B2）隐藏：她手动、可恢复、照样导出（不违反 1004「实际报错照实显示、不藏」——藏的是她看过、决定不管的那条）。
# 只有没解决的 PERMANENT（已放弃）能隐藏；NEEDS_HUMAN（要她处理）和 TRANSIENT（正在自动处理）一律不能。
# 口径：一直隐藏到这个 key 被解决为止；同一 key 没解决又报一次 = 还是那件事，照样藏着（hidden_repeats 记又出现几次）；
# 解决后又坏了才重新出现。写法：追加 {"ts","key","dismiss":true,"by":"owner"}；恢复追加 {"ts","key","dismiss":false}。
DISMISSABLE_CLASSES = ("PERMANENT",)
# 1008：撞验证 / 风控跳页是「一次一件事」——上一次推过、面板还没刷掉，隔了这么久又撞一次，也当场再推一次
# （同一次出事在一个进程里会经两条路各登记一回，间隔是秒级，靠这个窗口去重）。熔断中（RISK_HOLD）不算新出事。
INCIDENT_CODES = ("CAPTCHA_REQUIRED", "ACCOUNT_RISK")
INCIDENT_REPUSH_MIN = 15
STEP_LABELS = {
    "sync.favorites": "收藏同步", "ingest": "导入", "attachments.download": "下附件", "attachments.convert": "附件转文字",
    "attachments.recheck": "附件补查", "enrich.summary": "概要 / 识图补处理", "vision.layer1": "识图",
    "vision.refine": "精细识图", "videos.transcribe": "视频转写", "embed": "语义索引", "ask": "问收藏",
    "login": "小红书账号", "config": "设置", "remote": "远程阅读",
    "ai.summary": "AI 概要 / 打标接口", "ai.vision": "识图接口", "ai.refine": "精细识图接口", "ai.embed": "向量索引接口",
    "ai.ask": "问答接口", "render.check": "笔记页检查", "comments.fill": "评论补齐",
    "note.restricted": "网页版要验证", "mcp": "MCP 工具",
}

# 现有裸码 → 类（§2.2：复用现有码、不改拼写）
BARE_CLASS = {
    "NOT_LOGGED_IN": "NEEDS_HUMAN", "CAPTCHA_REQUIRED": "NEEDS_HUMAN", "ACCOUNT_RISK": "NEEDS_HUMAN",
    "RISK_HOLD": "NEEDS_HUMAN", "NOT_INSTALLED": "NEEDS_HUMAN", "WRONG_ACCOUNT": "NEEDS_HUMAN",
    # 10-03 夜跑实证：读取服务有时只滚到第一页（50 条）就当「全量加载完成」，下一次多半又正常——
    # 这是临时故障，不是要人处理的事：只记、下次同步自动再读，连着 3 天都这样才升级推一次
    "FAVORITES_SUSPICIOUS": "TRANSIENT",
    "RATE_LIMITED": "TRANSIENT", "DISCONNECTED": "TRANSIENT", "TIMEOUT": "TRANSIENT", "BUSY": "TRANSIENT",
    "INTERRUPTED": "TRANSIENT", "TOO_MANY_FAILURES": "TRANSIENT", "ACCOUNT_BUSY": "TRANSIENT",
    "ACCOUNT_BLOCKED": "NEEDS_HUMAN",  # 「号出事了」但读取服务没给具体风险码（MCP 报错文本像掉登录 / 验证）
    "FAVORITES_FAILED": "TRANSIENT",  # 读取服务读收藏失败（如机器卡导致登录检查超时，HTTP 500）——不是风控
    # 1008（读取组件 d7）：页面里有验证组件但没显示滑块 / 收藏页签点不动——只停这一次读收藏、不写熔断、下次照常读
    "HIDDEN_WIDGET": "TRANSIENT", "FAV_TAB_STUCK": "TRANSIENT",
    # 1015：小红书回 300013「访问频繁」= 限频冷却（读取组件到点自探、成功自动清），不是要人处理的风控
    "XHS_RATE_LIMITED": "TRANSIENT",
}

# 账号类（撞见就整批停车、要人处理）：这些码不管在哪一步撞见，一律登记在 step=login、item_id=None，
# 同一件事只有一把 key（同步、附件、导入撞见的是同一个号）。
ACCOUNT_CODES = ("NOT_LOGGED_IN", "CAPTCHA_REQUIRED", "ACCOUNT_RISK", "RISK_HOLD", "NOT_INSTALLED",
                 "WRONG_ACCOUNT", "ACCOUNT_BLOCKED")

# 显示登记表（§3.1）：code（或 `类.*` 兜底）→ 显示位置 / 标签 / 悬停 / 分组。Python 是唯一文案源，
# 每个码「用户看到什么 → 根因 → 修法 / 自愈动作 → 回归用例」记在 docs/ERRORS.md；新增码要同步登记到那里
# （CONVENTIONS §2），自愈动作登记到 repair.py 的 plan()。
# 以后写进 catalog-data.json 的 "state_registry" 给页面读；JS 不许自己写状态文案。
# where：top+card（顶部计数 + 卡片角标）· card · list（只在问题列表）· none（列表灰色「未开启」组）
# group：needs_you（等你处理）· auto（正在自动处理）· gave_up（已放弃）· off（未开启）
STATE_REGISTRY: dict[str, dict[str, str]] = {
    # —— 要人处理 ——
    "NEEDS_HUMAN.NOT_LOGGED_IN": dict(where="top+card", label="需要登录", hover="小红书账号掉登录了：点目录页顶部的问题入口扫码登录", group="needs_you"),
    "NEEDS_HUMAN.CAPTCHA_REQUIRED": dict(where="top+card", label="需要验证", hover="小红书弹了验证（不是掉登录）：点「打开验证」，窗口打开后点一下「收藏」页签（上次是读收藏时被拦的）；出现滑块就拖完再关窗，没出现就直接关窗", group="needs_you"),
    # 1011：没人看着时撞的验证码先不叫她（night_captcha）：冷却后自查一次，干净就自动恢复；连着两晚没好才升级成上面那条
    "TRANSIENT.NIGHT_CAPTCHA": dict(where="list", label="夜里弹了验证（不是掉登录）", hover="{reason}", group="auto"),
    "NEEDS_HUMAN.ACCOUNT_RISK": dict(where="top+card", label="账号风控", hover="小红书把读取号跳到了登录/安全页：同步已全部暂停，点目录页顶部的问题入口处理", group="needs_you"),
    "NEEDS_HUMAN.RISK_HOLD": dict(where="top+card", label="风控暂停中", hover="风控暂停中：所有用号的同步都停了，点目录页顶部的问题入口处理，处理完自动恢复", group="needs_you"),
    "NEEDS_HUMAN.NOT_INSTALLED": dict(where="top+card", label="未安装读取组件", hover="按 README「读取组件」安装后刷新", group="needs_you"),
    # 1024 返修：缺第三方包（deps.MissingDependency）。不是账号的事，不进 ACCOUNT_CODES，留在撞见的那一步
    "NEEDS_HUMAN.MISSING_DEPENDENCY": dict(where="top+card", label="缺 Python 依赖", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.WRONG_ACCOUNT": dict(where="top+card", label="登错号", hover="登录的不是收藏所在的号：换号重新扫码", group="needs_you"),
    "TRANSIENT.FAVORITES_SUSPICIOUS": dict(where="list", label="收藏只读到一截", hover="{reason}", group="auto"),
    # 1008：原因由 ai_health 写全（哪个接口 / 哪把 key / 为什么 / 怎么办 / 影响几篇 / 补齐花费），hover 直接显示它
    "NEEDS_HUMAN.AUTH_FAILED": dict(where="top+card", label="AI key 失效", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.QUOTA_EXCEEDED": dict(where="top+card", label="AI 余额不足", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.BACKUP_DISK_MISSING": dict(where="top+card", label="备份盘没挂", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.STUCK": dict(where="top+card", label="连续几天没修好", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.PORT_IN_USE": dict(where="top+card", label="远程阅读端口被占用", hover="{reason}", group="needs_you"),
    "NEEDS_HUMAN.ACCOUNT_BLOCKED": dict(where="top+card", label="账号要处理", hover="读取账号可能掉登录或要安全验证：点目录页顶部的问题入口检查账号", group="needs_you"),
    "NEEDS_HUMAN.SYNC_STUCK": dict(where="top+card", label="同步卡住了", hover="有一次收藏同步占着号好几个小时没有进展：{reason}", group="needs_you"),
    # —— 自动重试 ——
    "TRANSIENT.HTTP_5XX": dict(where="list", label="接口暂时出错", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.HTTP_429": dict(where="list", label="接口限流", hover="{reason}（{next_at} 再试）", group="auto"),
    # 1018 每天花费上限：今天花到了，后台补跑先只用免费的（明天 0 点恢复）；不打扰
    "TRANSIENT.BUDGET": dict(where="none", label="今天到花费上限了", hover="{reason}（北京时间明天 0 点恢复）", group="auto"),
    "TRANSIENT.NETWORK": dict(where="list", label="网络不通", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.SERVICE_BUSY": dict(where="list", label="服务正忙", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.STEP_TIMEOUT": dict(where="list", label="步骤超时", hover="{reason}", group="auto"),
    "TRANSIENT.RATE_LIMITED": dict(where="list", label="刚刚同步过", hover="收藏每 10 分钟最多读一次，稍后自动再试", group="auto"),
    "TRANSIENT.XHS_RATE_LIMITED": dict(where="list", label="小红书限频冷却中", hover="{reason}", group="auto"),
    "TRANSIENT.DISCONNECTED": dict(where="list", label="读取服务没在运行", hover="{reason}（下次自动拉起）", group="auto"),
    "TRANSIENT.TIMEOUT": dict(where="list", label="读取服务响应超时", hover="{reason}（稍后自动再试）", group="auto"),
    "TRANSIENT.BUSY": dict(where="list", label="读取服务正忙", hover="正在抓别的笔记，做完自然恢复", group="auto"),
    "TRANSIENT.INTERRUPTED": dict(where="list", label="被打断", hover="中途被打断，已抓的都在：{reason}", group="auto"),
    "TRANSIENT.TOO_MANY_FAILURES": dict(where="list", label="连续失败已暂停", hover="{reason}", group="auto"),
    "TRANSIENT.ACCOUNT_BUSY": dict(where="list", label="号正被占用", hover="另一个任务在用号，这一步今晚没做，下次再试", group="auto"),
    "TRANSIENT.FAVORITES_FAILED": dict(where="list", label="读收藏没成功", hover="{reason}（不是风控，稍后自动再试）", group="auto"),
    "TRANSIENT.SYNC_FAILED": dict(where="list", label="同步没做完", hover="{reason}", group="auto"),
    "TRANSIENT.DOWNLOAD_FAILED": dict(where="card", label="附件没下好", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.PROBE_FAILED": dict(where="list", label="附件没查清", hover="{reason}（{next_at} 再查）", group="auto"),
    "TRANSIENT.WEB_PROBE_BLOCKED": dict(where="list", label="网页那侧被拦", hover="{reason}（附件信息夜里再补查）", group="auto"),
    "TRANSIENT.RETRY_EXHAUSTED": dict(where="card", label="连着几次没补成", hover="{reason}（{next_at} 再试）", group="auto"),
    "TRANSIENT.STEP_CRASHED": dict(where="list", label="步骤中途出错退出", hover="{reason}", group="auto"),
    "TRANSIENT.SECRET_TIMEOUT": dict(where="list", label="取 AI key 超时", hover="从密码库取 key 没成：{reason}", group="auto"),
    # 1008（读取组件 d7）：读收藏「只停这一次、不熔断」的两种——只停收藏，当晚其它步骤照跑，下次照常读
    "TRANSIENT.HIDDEN_WIDGET": dict(where="list", label="收藏这次先停了", hover="{reason}", group="auto"),
    "TRANSIENT.FAV_TAB_STUCK": dict(where="list", label="收藏页签点不动", hover="{reason}", group="auto"),
    "TRANSIENT.*": dict(where="list", label="稍后自动重试", hover="{reason}（{next_at} 再试）", group="auto"),
    # —— 已放弃（记原因，不再自动重试）——
    "PERMANENT.PDF_ENCRYPTED": dict(where="card", label="全文没转出来", hover="PDF 有打开密码，字节已保存", group="gave_up"),
    "PERMANENT.PDF_DAMAGED": dict(where="card", label="全文没转出来", hover="PDF 文件损坏，字节已保存", group="gave_up"),
    "PERMANENT.DOC_UNSUPPORTED": dict(where="card", label="全文没转出来", hover="这种文档格式还转不了，原件已保存", group="gave_up"),
    "PERMANENT.NO_AUDIO": dict(where="list", label="视频没有音轨", hover="没有可转写的声音，画面上也没认出字幕", group="gave_up"),
    "PERMANENT.NOTE_DAMAGED": dict(where="list", label="笔记页被改坏", hover="{reason}；一天没动会自动按存档恢复（改坏的那版存了快照，可撤销）", group="gave_up"),
    "PERMANENT.NO_SPEECH": dict(where="list", label="视频里没人说话", hover="只有背景音乐或环境声，画面上也没认出字幕", group="gave_up"),
    # 1008：补查判定「原帖打不开」只上卡片、不进问题列表（她：没人声的不是问题）；分不清删了还是仅作者可见，别直说「已删除」
    "PERMANENT.NOTE_GONE": dict(where="card", label="原帖打不开", hover="原帖打不开（可能已删或仅作者可见），本地存档还在", group="gave_up"),
    "PERMANENT.MODEL_OUTPUT_INVALID": dict(where="card", label="AI 结果不可用", hover="{reason}", group="gave_up"),
    # 1015：识图接口内容审核拦下（去掉 OCR 文字重试过仍不收）——不是设置问题，OCR 文字照常可用
    "PERMANENT.CONTENT_FILTERED": dict(where="card", label="识图被接口审核拦下", hover="{reason}；本地 OCR 文字照常可搜", group="gave_up"),
    "PERMANENT.REMOTE_TASK_FAILED": dict(where="list", label="远程阅读的计划任务没弄好", hover="{reason}", group="gave_up"),
    # 第 5 批 `reader install`（用户点的操作，只出现在命令结果里，不登记问题记录）
    "PERMANENT.CHECKSUM_MISMATCH": dict(where="list", label="下载的组件校验不过", hover="{reason}", group="gave_up"),
    "PERMANENT.BAD_PACKAGE": dict(where="list", label="组件包不对", hover="{reason}", group="gave_up"),
    # 第 7 批 `setup install`（同上，只出现在命令结果里）：装之前核磁盘空间 / 下载解压中途磁盘满
    "PERMANENT.DISK_FULL": dict(where="list", label="磁盘空间不够", hover="{reason}", group="gave_up"),
    "PERMANENT.CONVERSION_FAILED": dict(where="card", label="全文没转出来", hover="{reason}（原件已保存）", group="gave_up"),
    "PERMANENT.STEP_ARGS": dict(where="list", label="程序和夜跑脚本版本对不上", hover="夜跑脚本给的命令参数程序不认：{reason}（更新程序或脚本后自动恢复）", group="gave_up"),
    # 1009：设置楼数内的楼中楼连着几次续读都没多拿到（原因照实写）；笔记页自己那一行也照实标
    "PERMANENT.COMMENTS_INCOMPLETE": dict(where="list", label="评论没补全", hover="{reason}", group="gave_up"),
    # 1011：只是这一篇（网页版要验证才给看）——不推送、一篇一条；卡片角标 + 问题面板 / 笔记页给「打开验证」（开验证窗口到这一篇）
    "PERMANENT.NOTE_RESTRICTED": dict(where="card", label="网页版要验证", hover="{reason}", group="gave_up"),
    "PERMANENT.*": dict(where="card", label="已放弃", hover="{reason}", group="gave_up"),
    # —— 未开启（不算失败）——
    "SKIPPED.NOT_CONFIGURED": dict(where="none", label="未配置", hover="{reason}", group="off"),
    "SKIPPED.DISABLED": dict(where="none", label="已关闭", hover="{reason}", group="off"),
    "SKIPPED.BUDGET": dict(where="none", label="今天的额度到了", hover="{reason}（明天接着来）", group="off"),
    "SKIPPED.FALLBACK": dict(where="none", label="已退回普通方式", hover="{reason}", group="off"),
    "SKIPPED.LEGACY_CONFIG": dict(where="none", label="旧设置已自动换算", hover="{reason}", group="off"),
    "SKIPPED.SKILL": dict(where="none", label="技能文件读不了，已跳过", hover="{reason}（问答退回通用写法）", group="off"),
    # 1018 设置页「添加 key」：粘的不像 key / 是 Anthropic 那种不通用的——只在小窗里说一句，不进面板
    "SKIPPED.BAD_INPUT": dict(where="none", label="粘的不像一把 key", hover="{reason}", group="off"),
    "SKIPPED.UNSUPPORTED": dict(where="none", label="这家的 key 用不了", hover="{reason}", group="off"),
    "SKIPPED.*": dict(where="none", label="未开启", hover="{reason}", group="off"),
}

# §2.3 首批新增码 + 现有裸码：登记表里精确登记的码必须出自这里或代码里的 problems.report( 字面码
# （tests/test_problems_registry.py 双向核对）。第 4 批接上调用点时这些码会出现在代码里。
PLANNED_CODES = (
    "TRANSIENT.HTTP_5XX", "TRANSIENT.HTTP_429", "TRANSIENT.NETWORK", "TRANSIENT.SERVICE_BUSY",
    "TRANSIENT.STEP_TIMEOUT",
    "PERMANENT.PDF_ENCRYPTED", "PERMANENT.PDF_DAMAGED", "PERMANENT.DOC_UNSUPPORTED", "PERMANENT.NO_AUDIO",
    "PERMANENT.NO_SPEECH", "PERMANENT.NOTE_GONE", "PERMANENT.MODEL_OUTPUT_INVALID",
    "PERMANENT.CONTENT_FILTERED",
    "NEEDS_HUMAN.AUTH_FAILED", "NEEDS_HUMAN.QUOTA_EXCEEDED", "NEEDS_HUMAN.BACKUP_DISK_MISSING",
    "NEEDS_HUMAN.STUCK",
    "SKIPPED.NOT_CONFIGURED", "SKIPPED.DISABLED", "SKIPPED.BUDGET", "SKIPPED.FALLBACK",
)
# 仓外夜跑脚本（`python -m link_brain problems report --step nightly.<名> --code …`）会报的码：
# 仓里没有字面调用点，登记表双向核对时按「有人产生」算。
EXTERNAL_CODES = (
    "TRANSIENT.STEP_TIMEOUT", "TRANSIENT.STEP_CRASHED", "TRANSIENT.SECRET_TIMEOUT", "TRANSIENT.INTERRUPTED",
    "TRANSIENT.ACCOUNT_BUSY", "PERMANENT.STEP_ARGS", "NEEDS_HUMAN.SYNC_STUCK",
)

GROUP_OF_CLASS = {"NEEDS_HUMAN": "needs_you", "TRANSIENT": "auto", "PERMANENT": "gave_up", "SKIPPED": "off"}

# 1017（她）：面板按「是什么事」分类，不再按「系统放没放弃」分组——原因清楚的毛病挂在「已放弃」里看着闹心。
# group（等你处理 / 自动处理 / 已放弃 / 未开启）照旧留在行上，只管按钮和计数；面板分区看 category。
CATEGORIES = (("account", "登录验证"), ("api", "AI 接口"), ("fetch", "拉取没拿全"), ("other", "其他"), ("off", "未开启"))
# 1017：网页版要验证是「这一篇」的事，不是号的事——归拉取，登录验证区只留号本身
_ACCOUNT_SUBS = {*ACCOUNT_CODES, "NIGHT_CAPTCHA", "XHS_RATE_LIMITED", "SYNC_STUCK"}
_API_SUBS = {"AUTH_FAILED", "QUOTA_EXCEEDED", "HTTP_429", "HTTP_5XX", "NETWORK", "SECRET_TIMEOUT",
             "MODEL_OUTPUT_INVALID", "CONTENT_FILTERED"}
_API_STEPS = {"enrich.summary", "vision.layer1", "vision.refine", "embed", "ask"}
_FETCH_STEPS = {"sync.favorites", "ingest", "attachments.download", "attachments.recheck", "comments.fill"}


def category(row: dict[str, Any]) -> str:
    """account（登录验证：号、要她点一下验证的那篇）· api（AI 接口：key / 余额 / 限流 / 模型输出）·
    fetch（拉取没拿全：收藏、正文、评论、附件）· other · off（未开启）。"""
    step = str(row.get("step") or "")
    try:
        cls, sub = normalize(row.get("code") or "").split(".", 1)
    except BadCode:
        cls, sub = "", ""
    if cls == "SKIPPED":
        return "off"
    if step == "login" or sub in _ACCOUNT_SUBS:
        return "account"
    if sub == "STEP_CRASHED":
        return "other"  # 代码自己崩了（mcp / 问答 / 命令兜底），哪一步崩的都不是 AI 接口或拉取的问题
    if step.startswith("ai.") or sub in _API_SUBS or step in _API_STEPS:
        return "api"
    if step in _FETCH_STEPS or step == "note.restricted" or sub in ("NOTE_GONE", "NOTE_RESTRICTED"):
        return "fetch"
    return "other"
SUMMARY_KEY = {"NEEDS_HUMAN": "needs_human", "TRANSIENT": "auto", "PERMANENT": "gave_up", "SKIPPED": "skipped"}


class BadCode(ValueError):
    pass


# --------------------------------------------------------------------------
# 码
# --------------------------------------------------------------------------

_SUB_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def normalize(code: str) -> str:
    """`NOT_LOGGED_IN` → `NEEDS_HUMAN.NOT_LOGGED_IN`；已带类的原样返回。格式不对 → BadCode。

    裸码不在 BARE_CLASS 里：`HTTP_429` / `HTTP_5xx` 按 §4.6 翻；其余未知裸码归 TRANSIENT
    （自动重试，连续 3 天还在就升级 STUCK 报给人——不会悄悄藏起来）。"""
    code = str(code or "").strip()
    if "." in code:
        cls, sub = code.split(".", 1)
        if cls not in CLASSES or not _SUB_RE.match(sub):
            raise BadCode(f"故障码格式不对：{code!r}（要 TRANSIENT|PERMANENT|NEEDS_HUMAN|SKIPPED.<大写下划线>）")
        return code
    if not _SUB_RE.match(code):
        raise BadCode(f"故障码格式不对：{code!r}")
    if code in BARE_CLASS:
        return f"{BARE_CLASS[code]}.{code}"
    m = re.match(r"^HTTP_(\d{3})$", code)
    if m:
        status = int(m.group(1))
        if status == 429:
            return "TRANSIENT.HTTP_429"
        if status in (401, 403):
            return "NEEDS_HUMAN.AUTH_FAILED"
        if status == 402:
            return "NEEDS_HUMAN.QUOTA_EXCEEDED"
        if status >= 500:
            return "TRANSIENT.HTTP_5XX"
        return "PERMANENT.MODEL_OUTPUT_INVALID"
    return f"TRANSIENT.{code}"


def classify(code: str) -> str:
    """'TRANSIENT' | 'PERMANENT' | 'NEEDS_HUMAN' | 'SKIPPED'。"""
    return normalize(code).split(".", 1)[0]


def subcode(code: str) -> str:
    return normalize(code).split(".", 1)[1]


def lookup(code: str) -> dict[str, str]:
    """登记表里的显示行：先精确，再 `类.*` 兜底。"""
    full = normalize(code)
    entry = STATE_REGISTRY.get(full) or STATE_REGISTRY[full.split(".", 1)[0] + ".*"]
    return {"code": full, **entry}


def registry_for_js() -> dict[str, dict[str, str]]:
    """给页面用的那份（catalog-data.json 的 state_registry）。"""
    return {k: dict(v) for k, v in STATE_REGISTRY.items()}


def step_label(step: str | None) -> str:
    step = str(step or "")
    if step.startswith("nightly."):
        return f"夜跑：{step[len('nightly.'):]}"
    if step.startswith("cli."):
        return f"命令：{step[len('cli.'):]}"
    return STEP_LABELS.get(step, step)


def when_text(ts: str | None) -> str:
    """ISO 时间 → 页面上的短写「10-03 04:00」；读不出来原样返回。"""
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(str(ts)).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(ts)


def fill_hover(template: str, reason: str | None = None, next_at: str | None = None) -> str:
    """把登记表 hover 里的 {reason} {next_at} 填好（页面直接显示，JS 不拼文案）。没有 next_at 时说「稍后」。"""
    text = str(template or "")
    if "{next_at}" in text:
        when = when_text(next_at)
        text = text.replace("{next_at}", when) if when else text.replace("{next_at} ", "稍后").replace("{next_at}", "稍后")
    text = text.replace("{reason}", str(reason or "").strip() or "没有更多说明")
    return text


def describe(code: str, reason: str | None = None, next_at: str | None = None) -> dict[str, str]:
    """{code, label, hover, group, where}：label / hover 只从登记表来，hover 已填好。码坏了给兜底，不抛。"""
    try:
        entry = lookup(code)
    except (BadCode, KeyError):
        entry = {"code": str(code or ""), **STATE_REGISTRY["TRANSIENT.*"]}
    return {"code": entry["code"], "label": entry["label"], "hover": fill_hover(entry["hover"], reason, next_at),
            "group": entry["group"], "where": entry["where"]}


# --------------------------------------------------------------------------
# 文件
# --------------------------------------------------------------------------


def path() -> Path:
    return storage.archive_root() / FILE_NAME


def _now() -> datetime:
    return datetime.now().astimezone()


def _day(ts: str | None) -> str | None:
    try:
        return datetime.fromisoformat(str(ts)).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return None


def make_key(step: str, item_id: str | None, code: str) -> str:
    return f"{step}|{item_id or ''}|{subcode(code)}"


def pending_dir() -> Path:
    """等不到 problems 锁时的旁路：每次一个小文件（原子写，名字不撞），拿到锁的人并回 problems.jsonl。"""
    return storage.archive_root() / PENDING_DIR


def _pending_files() -> list[Path]:
    try:
        return sorted(pending_dir().glob("*.jsonl"))
    except OSError:
        return []


def _read_file(p: Path, strict: bool) -> list[dict[str, Any]]:
    """读一份记录的行。没有文件 = 空；半行 / 坏行（含截在汉字中间）跳过，不让一行坏掉整份；
    打不开（被占）strict 时抛，否则当空。"""
    try:
        rows, _bad = storage.read_jsonl(p)
    except OSError:
        if strict:
            raise
        return []
    return [r for r in rows if r.get("key")]


def _row_time(row: dict[str, Any]) -> float | None:
    times = [t.timestamp() for t in (_parse_ts(row.get("ts")), _parse_ts(row.get("resolved_at"))) if t]
    return max(times) if times else None


_eid_seq = itertools.count()


def _stamped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每行一个事件 id：写入时刻（纳秒）-pid-线程-序号。旁路并回按它去重、同一秒内按它排先后（Codex 1025）。
    进 _append 的都是新事件，一律给新 id（从别的行复制出来的也不沿用）。"""
    base = f"{time.time_ns()}-{os.getpid()}-{threading.get_ident()}"
    return [{**r, "eid": f"{base}-{next(_eid_seq)}"} for r in rows]


def _eid_ns(row: dict[str, Any]) -> int:
    try:
        return int(str(row.get("eid") or "").split("-", 1)[0])
    except ValueError:
        return 0  # 1025 之前的行没有事件 id：同一秒内排在有 id 的前面


def _ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """旁路里的行并回来时按时间插回去（稳定排序；没时间的行跟着前一行），折叠顺序才对。
    时间只到秒：同一秒内按事件 id 里的写入时刻排，不然旧报错会排到同一秒的解决行后面、把问题重新打开。"""
    keyed, last = [], float("-inf")
    for i, r in enumerate(rows):
        t = _row_time(r)
        last = last if t is None else t
        keyed.append((last, _eid_ns(r), i, r))
    return [r for *_, r in sorted(keyed, key=lambda x: x[:3])]


def _new_rows(known: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """extra 里 known 和自己前面都没出现过的行（按事件 id）：旁路并回后删不掉，下次别再并一遍、算两次。"""
    seen = {r["eid"] for r in known if r.get("eid")}
    out = []
    for r in extra:
        if r.get("eid"):
            if r["eid"] in seen:
                continue
            seen.add(r["eid"])
        out.append(r)
    return out


def _read_rows(*, strict: bool = False) -> list[dict[str, Any]]:
    """problems.jsonl + 还没并回的旁路行。strict=True 时读不出来就抛（report 据此不推送），否则读不出来当空。"""
    extra: list[dict[str, Any]] = []
    for f in _pending_files():  # 先读旁路再读主文件：中间正好被并回，最多重一遍（按事件 id 去掉），不会漏
        extra += _read_file(f, strict)
    rows = _read_file(path(), strict)
    extra = _new_rows(rows, extra)
    return _ordered(rows + extra) if extra else rows


def _fold(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 key 折叠：最新一行为准；count 累加（解决之后从头算）；days 记最近出现的日历日；notified 本轮推过没有。"""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["key"]
        prev = out.get(key)
        if "dismiss" in row:
            # 隐藏 / 恢复行：不加次数、不算出现日；那条已解决 / 不存在就丢掉（隐藏只对「这一轮」有效）
            if prev is not None and not prev.get("resolved_at"):
                if row.get("dismiss"):
                    out[key] = {**prev, "dismissed_at": prev.get("dismissed_at") or row.get("ts"),
                                "hidden_repeats": int(prev.get("hidden_repeats") or 0)}
                else:
                    out[key] = {k: v for k, v in prev.items() if k not in ("dismissed_at", "hidden_repeats")}
            continue
        if row.get("note"):
            # 注记行（自愈过程）：只并进修复字段，不加次数、不算出现日；那条已解决 / 不存在就丢掉
            if prev is not None and not prev.get("resolved_at"):
                out[key] = {**prev, **{k: row[k] for k in NOTE_FIELDS if k in row}}
            continue
        if row.get("resolved_at"):
            if prev is not None:
                out[key] = {**prev, "resolved_at": row["resolved_at"], "notified": False}
            else:
                out[key] = {**row, "count": 0, "days": [], "notified": False}
            continue
        fresh = prev is None or bool(prev.get("resolved_at"))
        base_count = 0 if fresh else int(prev.get("count") or 0)
        days = [] if fresh else list(prev.get("days") or [])
        for d in (row.get("days") or [_day(row.get("ts"))]):
            if d and d not in days:
                days.append(d)
        days = sorted(days)[-DAYS_KEPT:]
        notified = bool(row.get("notified")) or (not fresh and bool(prev.get("notified")))
        # 新出现一次 = 上一轮的修复注记作废（压实行自己带着的除外）
        carried = {k: row[k] for k in NOTE_FIELDS if k in row}
        out[key] = {**{k: v for k, v in row.items() if k not in NOTE_FIELDS}, **carried,
                    "count": base_count + int(row.get("count") or 1), "days": days,
                    "notified": notified, "resolved_at": None}
        if not fresh and prev.get("dismissed_at"):
            # 隐藏要从上一轮显式带过来（注记字段在复发时会被扔掉，隐藏不能跟着丢）：同一件事又报一次，照样藏着
            out[key]["dismissed_at"] = prev["dismissed_at"]
            out[key]["hidden_repeats"] = int(prev.get("hidden_repeats") or 0) + 1
        elif fresh and not row.get("dismissed_at"):
            out[key].pop("dismissed_at", None)
            out[key].pop("hidden_repeats", None)
    return out


def is_hidden(row: dict[str, Any]) -> bool:
    """这条是她手动隐藏、还没解决的（隐藏的不进顶部计数，列表里放在「已隐藏」区）。"""
    return bool(row.get("dismissed_at")) and not row.get("resolved_at")


# 1011（她：自愈的就不要显示报错）：评论续读放弃了、但设置楼数内的楼中楼只缺这么几条——不影响阅读，
# 不进问题列表和顶部计数，只留在「复制报错」里（状态写「轻微」）。缺几条优先读行上的 missing，老行从原因里认。
MINOR_CODES = {"PERMANENT.COMMENTS_INCOMPLETE": 2}
_MISSING_RE = re.compile(r"楼中楼还缺\s*(\d+)\s*条")


def missing_count(row: dict[str, Any]) -> int | None:
    """这条评论没补全还缺几条回复；认不出来 = None（不当轻微）。"""
    v = row.get("missing")
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    m = _MISSING_RE.search(str(row.get("reason") or ""))
    return int(m.group(1)) if m else None


# 1017（她：限频冷却已经自动处理了还挂着，荒谬；只有掉登录才需要显示）：自己会好、不用人管的号状态不进面板和计数，
# 只在「复制报错」里。号真出事（掉登录 / 验证 / 风控 / 第 4 次限频升级）是别的码，照列。
QUIET_CODES = ("TRANSIENT.XHS_RATE_LIMITED",)


def is_minor(row: dict[str, Any]) -> bool:
    """没解决、但轻微到不该打扰她的（见 MINOR_CODES / QUIET_CODES）：问题列表 / 计数 / 「全部修一遍」都不算，诊断导出照留。"""
    if row.get("resolved_at"):
        return False
    if str(row.get("code") or "") in QUIET_CODES:
        return True
    if row.get("step") == "sync.favorites" and row.get("code") == "TRANSIENT.INTERRUPTED":
        return True  # 1019 她：关 Obsidian 打断一次同步，下次自己接着来，不占面板
    limit = MINOR_CODES.get(str(row.get("code") or ""))
    if limit is None:
        return False
    n = missing_count(row)
    return n is not None and 0 < n <= limit


def _dump(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _append_text(p: Path, blob: str) -> None:
    """追加；文件不以换行结尾（上次写到半截）先补一个，免得新行粘在半行后面一起坏掉。"""
    with p.open("a+b") as fh:
        if fh.seek(0, os.SEEK_END) > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                blob = "\n" + blob
        fh.write(blob.encode("utf-8"))


def _write_pending(blob: str) -> None:
    d = pending_dir()
    d.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_text(d / f"{time.time_ns()}-{os.getpid()}-{threading.get_ident()}.jsonl", blob)


def _merge_pending_locked() -> int:
    """（已拿 problems 锁）把旁路行按时间并回 problems.jsonl，删掉旁路文件。返回并回几行。"""
    files = _pending_files()
    if not files:
        return 0
    extra: list[dict[str, Any]] = []
    done: list[Path] = []
    for f in files:
        if not f.exists():
            continue
        try:
            extra += _read_file(f, True)
        except OSError as exc:
            print(f"[problems] 旁路记录这次没并回（{errtext(exc)}），下次再并：{f.name}", file=sys.stderr)
            continue
        done.append(f)
    main = _read_file(path(), True)
    extra = _new_rows(main, extra)
    if extra:
        storage.atomic_write_text(path(), _dump(_ordered(main + extra)))
    for f in done:
        try:
            f.unlink()
        except OSError as exc:
            print(f"[problems] 旁路文件删不掉（{errtext(exc)}）：{f.name}", file=sys.stderr)
    return len(extra)


def _append(rows) -> None:
    """追加行（每行 ≤ 4 KB），超过 MAX_KEYS + COMPACT_SLACK 行就压回 MAX_KEYS。

    rows 是行列表，或 build(folded, readable) -> 行列表：后者在锁里读、判断、追加（report 用：两个进程不会同时判「没推过」）。
    锁等不到就写旁路文件（problems.pending/），拿到锁的人并回——不在锁外碰 problems.jsonl，免得被别人的压实冲掉。"""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    got = False
    try:
        with storage.file_lock("problems", wait_s=LOCK_WAIT_S):
            got = True
            try:
                _merge_pending_locked()
            except Exception as exc:  # noqa: BLE001 - 主文件一时打不开：旁路留着下次并，这一行照样要记
                print(f"[problems] 旁路记录这次没并回（{errtext(exc)}），下次再并", file=sys.stderr)
            if callable(rows):
                rows = rows(*_read_folded())
            blob = _dump(_stamped(rows))
            try:
                _append_text(p, blob)
            except OSError as exc:
                # 主文件这会儿写不了（杀毒 / 同步盘占着）：退到旁路，拿到锁的人并回，绝不丢这一行
                print(f"[problems] 主文件写不上（{errtext(exc)}），先记进旁路", file=sys.stderr)
                _write_pending(blob)
            else:
                try:
                    _compact_locked(MAX_KEYS + COMPACT_SLACK)
                except Exception as exc:  # noqa: BLE001 - 行已追加，压实下次再做
                    print(f"[problems] 这次没压实（{errtext(exc)}）", file=sys.stderr)
            _write_summary_locked()
    except storage.LockBusy:
        if got:
            raise
        if callable(rows):
            rows = rows(*_read_folded())  # 锁外读：只用来判推送，最坏多推一次
        _write_pending(_dump(_stamped(rows)))
        _write_summary_locked()  # 原子写：和锁里那份抢也只是谁新谁留


def _read_folded() -> tuple[dict[str, dict[str, Any]], bool]:
    """(折叠结果, 读没读出来)。读不出来 = ({}, False)：调用方据此不推送。"""
    try:
        return _fold(_read_rows(strict=True)), True
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 问题记录读不出来（{errtext(exc)}），这次不推送", file=sys.stderr)
        return {}, False


def _compact_locked(threshold: int | None = None) -> bool:
    if _pending_files():
        # 还有旁路没删掉（被占 / 刚有人写进来）：压实会丢掉各行的事件 id，之后再并回就分不出哪些并过了。等删掉再压
        return False
    # 只读主文件：检查完旁路到读之间别的进程可能刚写进旁路，那几行留给下次并回（带事件 id 去重），
    # 不能这次折进主文件、旁路又留着——那样会重复累加（1025 Codex 复查：3 次报错算成 4）。
    rows = _read_file(path(), False)
    if len(rows) <= (MAX_KEYS if threshold is None else threshold):
        return False
    folded = _fold(rows)
    keep = sorted(folded.values(), key=lambda r: str(r.get("ts") or ""))[-MAX_KEYS:]
    storage.atomic_write_text(path(), _dump(keep))
    return True


def compact() -> bool:
    """压实为最近 MAX_KEYS 个 key（每个 key 一行折叠结果）。在 problems 锁里做（先并回旁路）。"""
    with storage.file_lock("problems", wait_s=30):
        _merge_pending_locked()
        done = _compact_locked()
        _write_summary_locked()
        return done


def last_risk() -> dict[str, Any] | None:
    """最近一次撞验证 / 风控跳页（不管解没解决）：{at, code, text, open}。设置页「立即同步」旁如实写
    「上次 HH:MM 在读收藏时判到验证」（她 1008：不拦、不冷却，只照实说）。读不动 = None。"""
    try:
        rows = [r for r in _read_rows() if r.get("step") == "login" and not r.get("note") and "dismiss" not in r
                and not r.get("resolved_at") and str(r.get("key", "")).rsplit("|", 1)[-1] in (*INCIDENT_CODES, "NIGHT_CAPTCHA")]
        if not rows:
            return None
        r = max(rows, key=lambda x: str(x.get("ts") or ""))
        row = _fold(_read_rows()).get(r["key"]) or {}
        return {"at": r.get("ts"), "code": r.get("code"), "text": str(r.get("reason") or "")[:160],
                "open": not row.get("resolved_at")}
    except Exception:  # noqa: BLE001
        return None


def summary_path() -> Path:
    return storage.archive_root() / SUMMARY_NAME


def page_summary() -> dict[str, Any]:
    """`problems-summary.json` 的内容：{updated_at, needs_human, auto, gave_up, skipped, last_runs, sync}。
    sync 段 = 修正后的同步状态（进程已死的 running 已改成 INTERRUPTED），见 sync_state.page_state。"""
    out: dict[str, Any] = {"updated_at": _now().isoformat(timespec="seconds"), **summary(), "last_risk": last_risk()}
    try:
        from . import sync_state
        out["sync"] = sync_state.page_state()
    except Exception as exc:  # noqa: BLE001 - 同步段读不动不影响计数
        print(f"[problems] 同步状态读不出来（{errtext(exc)}）", file=sys.stderr)
        out["sync"] = None
    return out


def _write_summary_locked() -> bool:
    """写 problems-summary.json（调用方已拿 problems 锁或锁忙时兜底）。fail-open：失败只打 stderr。"""
    try:
        storage.write_json(summary_path(), page_summary())
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] problems-summary.json 没写上（{errtext(exc)}）", file=sys.stderr)
        return False


def write_summary(wait_s: float = 5) -> bool:
    """在 problems 锁里刷新 problems-summary.json（sync_state 每次写 sync-status 后调）。永不抛异常。"""
    try:
        with storage.file_lock("problems", wait_s=wait_s):
            return _write_summary_locked()
    except storage.LockBusy:
        return _write_summary_locked()
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] problems-summary.json 没写上（{errtext(exc)}）", file=sys.stderr)
        return False


# --------------------------------------------------------------------------
# 推送（唯一出口）
# --------------------------------------------------------------------------


def _push(row: dict[str, Any]) -> None:
    """报给人。alert 永不抛异常；这里再兜一层，推送失败绝不影响记录。"""
    try:
        from . import alert as alert_mod

        entry = lookup(row["code"])
        step = str(row.get("step") or "")
        where = row.get("title") or row.get("item_id") or step_label(step)
        title = f"{entry['label']}：{where}"
        if str(row.get("code") or "").endswith(".CAPTCHA_REQUIRED"):
            title = "小红书弹了验证（不是掉登录）"  # 1011 她：一眼分清是验证还是掉登录
        # 正文 = 登记表那句「该做什么」（已填好）+ 原因详情（不重复时）
        reason = str(row.get("reason") or "")
        body = fill_hover(entry["hover"], reason, row.get("next_at"))
        if reason and reason not in body:
            body = reason if reason.startswith(body) else f"{body}\n详情：{reason}"
        alert_mod._alert("problem", title, body, code=row["code"], step=step, item_id=row.get("item_id"))
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 推送失败（{errtext(exc)}）", file=sys.stderr)


def _consecutive_days(days: list[str], n: int, today: date) -> bool:
    want = {(today - timedelta(days=i)).isoformat() for i in range(n)}
    return want.issubset(set(days))


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------


def report(step: str, code: str, reason: str, *, item_id: str | None = None, title: str | None = None,
           action: str | None = None, next_at: str | None = None, evidence_id: str | None = None,
           missing: int | None = None, _now_fn=None) -> dict[str, Any]:
    """登记一条问题，返回写进文件的那一行。推送判定在这里（见模块说明）。

    码格式不对抛 BadCode（调用方写错码是 bug，要在测试里炸出来）；写盘失败不抛，返回的行带 written=False。"""
    full = normalize(code)
    cls = full.split(".", 1)[0]
    if action is not None and action not in ACTIONS:
        raise ValueError(f"action 只能是 {ACTIONS}：{action!r}")
    now = (_now_fn or _now)()
    key = make_key(step, item_id, full)
    row: dict[str, Any] = {
        "ts": now.isoformat(timespec="seconds"), "key": key, "step": step, "item_id": item_id or None,
        "title": (title or "")[:TITLE_MAX] or None, "code": full, "reason": str(reason or "")[:REASON_MAX],
        "action": action or DEFAULT_ACTION[cls], "next_at": next_at, "count": 1, "resolved_at": None,
    }
    if missing is not None:
        row["missing"] = int(missing)  # 1011：评论还缺几条回复（is_minor 判「轻微」用）
    if evidence_id:
        # 出事证据目录的名字（~/.link-brain/risk-evidence/<名字>），不是路径：本机绝对路径不进问题记录（面板「查看截图」自己拼）
        row["evidence_id"] = str(evidence_id)[:40]
    sub = full.split(".", 1)[1]
    today = now.date().isoformat()
    decided: dict[str, Any] = {}

    def build(folded: dict[str, dict[str, Any]], readable: bool) -> list[dict[str, Any]]:
        """读和判断在 problems 锁里（_append 调）；记录读不出来就不推送（行照写，notified=False，下次再判）。"""
        # 同一步骤 + 同一细分码、还没解决的各篇合起来，出现过哪几个日历日（一件事 = 一个原因，不按篇算）
        days = sorted({*_open_days(folded, step, sub), today})
        push = readable and cls == "NEEDS_HUMAN" and not _already_pushed(folded, step, full)
        if (readable and not push and cls == "NEEDS_HUMAN" and sub in INCIDENT_CODES
                and not _already_pushed(folded, step, full, within=now - timedelta(minutes=INCIDENT_REPUSH_MIN))):
            push = True  # 1008（她：撞验证「当时就通知」）：上一次推过之后又撞了一次新的，照样当场推
        if push and sub == "RISK_HOLD" and _hold_cause_open([r for r in folded.values() if r.get("notified")]):
            push = False  # 1019 她：掉登录 / 验证那条已经推过，「熔断中」是同一件事，不再推第二条
        if push and sub in DELAYED_PUSH and len(days) < DELAYED_PUSH_DAYS:
            push = False  # key 失效 / 欠费：产品规则「连续几晚没修好」才推；先进列表（橙色计数照样有）
        row.pop("notified", None)
        if push:
            row["notified"] = True
        out_rows = [row]
        stuck = None
        if cls == "TRANSIENT" and _consecutive_days(days, STUCK_DAYS, now.date()):
            # 升级按「步骤」记一条（item_id=None）：50 篇附件同一个原因卡 3 天 = 一件事，顶部橙色只 +1
            stuck_key = make_key(step, None, "NEEDS_HUMAN.STUCK")
            stuck_prev = folded.get(stuck_key)
            if not (stuck_prev and not stuck_prev.get("resolved_at")):
                stuck_push = readable and not _already_pushed(folded, step, "NEEDS_HUMAN.STUCK")
                stuck = {**row, "key": stuck_key, "item_id": None, "title": None, "code": "NEEDS_HUMAN.STUCK",
                         "action": "needs_human",
                         "reason": f"连续 {STUCK_DAYS} 天自动重试都没成功（{sub}）：{row['reason']}"[:REASON_MAX],
                         "next_at": None, "notified": stuck_push}
                out_rows.append(stuck)
        decided.update(push=push, stuck=stuck)
        return out_rows

    try:
        _append(build)
        row["written"] = True
    except OSError as exc:
        print(f"[problems] 问题记录写不进去（{errtext(exc)}）", file=sys.stderr)
        row["written"] = False
    if not decided:
        build(*_read_folded())  # 写盘前就失败了：照样判一次推送（要人处理的事不能因为磁盘丢）
    push, stuck = decided["push"], decided["stuck"]
    if push:
        _push(row)
    if stuck and stuck.get("notified"):
        _push(stuck)
    return row


def _open_days(folded: dict[str, dict[str, Any]], step: str, sub: str) -> set[str]:
    """step 下细分码为 sub、还没解决的各条，出现过的日历日的并集。"""
    out: set[str] = set()
    for r in folded.values():
        if r.get("step") == step and not r.get("resolved_at") and str(r.get("key", "")).rsplit("|", 1)[-1] == sub:
            out.update(d for d in (r.get("days") or []) if d)
    return out


def _already_pushed(folded: dict[str, dict[str, Any]], step: str, full_code: str,
                    within: datetime | None = None) -> bool:
    """同一步骤 + 同一细分码还有没解决、推过的记录 → 这件事已经告诉过人了（各篇共用一次推送：
    key 失效时 50 篇概要都会撞 AUTH_FAILED，只推一次）。"""
    sub = full_code.split(".", 1)[1]
    for r in folded.values():
        if (r.get("step") == step and not r.get("resolved_at") and r.get("notified")
                and str(r.get("key", "")).rsplit("|", 1)[-1] == sub):
            if within is None:
                return True
            ts = _parse_ts(r.get("ts"))
            if ts is None or ts >= within:
                return True
    return False


def _parse_ts(ts) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts)).astimezone()
    except (TypeError, ValueError):
        return None


def report_blocked(step: str, code: str | None, reason: str, *, service: bool = False,
                   item_id: str | None = None, title: str | None = None) -> dict[str, Any] | None:
    """读取服务 / 账号撞墙（xhs.NeedsHumanError 那一类）登记成一条问题，永不抛异常。

    - 账号类（掉登录 / 验证码 / 风控 / 熔断 / 登错号 / 没装组件；没带码的「号出事了」记 ACCOUNT_BLOCKED）
      → step=login、item_id=None：不管同步、附件还是导入撞见，都是同一件事、同一把 key，只推一次。
    - 服务类（读取服务没起来 / 超时 / 忙 / 读收藏 500）→ 留在本步骤，TRANSIENT：下次自动再试，
      连续 3 天还这样才升级 STUCK 推一次。
    - RATE_LIMITED（刚同步过）不是问题，不登记。"""
    raw = str(code or "").strip()
    if raw == "RATE_LIMITED":
        return None
    try:
        if not raw:
            raw = "DISCONNECTED" if service else "ACCOUNT_BLOCKED"
        full = normalize(raw)
        sub = full.split(".", 1)[1]
        if sub == "XHS_RATE_LIMITED":
            # 1015：限频冷却是号的事、不是某一步的事：不管哪一步撞见都记在 login 一把 key 上（TRANSIENT，不推）
            # 1017：调用方的原因常套着「读取账号需要处理：请…重新扫码」（掉登录的话术），对限频是错的——原因只用限频那句
            try:
                from . import accounts
                reason = accounts.rate_limit_text(accounts._hold_file())
            except Exception:  # noqa: BLE001
                reason = "小红书说访问太频繁（限频，不是封号），已自动冷却，到点自己再试，不用处理"
            return report("login", full, reason, title=title)
        if sub in ACCOUNT_CODES and full.startswith("NEEDS_HUMAN."):
            # 1011：没人看着（夜跑 / 后台补评论）时撞的验证码先不叫她：登记 TRANSIENT.NIGHT_CAPTCHA，冷却后自查（night_captcha）
            from . import night_captcha
            if night_captcha.defer(sub):
                return night_captcha.report_deferred(reason)
            # 1008：出事那一刻的证据目录名（读取组件写在本机熔断文件里）——面板「查看截图」用；路径本身不进记录
            eid = None
            try:
                from . import accounts
                eid = accounts.evidence_id(accounts._hold_file()) or None
            except Exception:  # noqa: BLE001
                eid = None
            return report("login", full, reason, title=title, evidence_id=eid)
        return report(step, full, reason, item_id=item_id, title=title)
    except Exception as exc:  # noqa: BLE001 - 登记失败不能把归档带走
        print(f"[problems] 登记失败（{errtext(exc)}）", file=sys.stderr)
        return None


def is_open_step(step: str) -> bool:
    """这一步还有没有没解决的问题（任何码、任何篇）。"""
    try:
        return any(r.get("step") == step and not r.get("resolved_at") for r in _fold(_read_rows()).values())
    except Exception:  # noqa: BLE001
        return False


def is_open(step: str, item_id: str | None, code: str) -> bool:
    """这个 step + item_id + 码现在有没有一条还没解决的记录（只记一次的说明类用它去重）。读不动就当没有。"""
    try:
        row = _fold(_read_rows()).get(make_key(step, item_id, normalize(code)))
    except Exception:  # noqa: BLE001
        return False
    return bool(row) and not row.get("resolved_at")


def annotate(row: dict[str, Any], **fields: Any) -> bool:
    """给一条还没解决的问题追加一行注记（自愈过程：正在修 / 试过什么没好 / 要等到几点）。
    不加次数、不算出现日、不推送。只认 NOTE_FIELDS。永不抛异常，返回写没写进去。"""
    try:
        note = {"ts": _now().isoformat(timespec="seconds"), "key": row["key"], "step": row.get("step"),
                "item_id": row.get("item_id") or None, "code": row.get("code"), "note": True,
                **{k: v for k, v in fields.items() if k in NOTE_FIELDS}}
        if isinstance(note.get("repair_note"), str):
            note["repair_note"] = note["repair_note"][:REASON_MAX]
        _append([note])
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 修复注记没写上（{errtext(exc)}）", file=sys.stderr)
        return False


def resolve(step: str, item_id: str | None = None, code: str | None = None, *, _now_fn=None) -> int:
    """把 step（+ item_id；None = 步骤级那几条）下未解决的问题标成已解决。code 给了就只解决那一个码。
    返回解决了几条。永不抛异常（解决失败最多是列表里多挂一条）。"""
    try:
        folded = _fold(_read_rows())
        want_sub = subcode(code) if code else None
        targets = [r for r in folded.values()
                   if r.get("step") == step and (r.get("item_id") or None) == (item_id or None)
                   and not r.get("resolved_at")
                   and (want_sub is None or str(r.get("key", "")).rsplit("|", 1)[-1] == want_sub)]
        # 步骤级的 STUCK（item_id=None）跟着「这一步还有没有没好的临时故障」走：
        # 各篇都好了才解决它；还有篇在卡，就算步骤级 resolve 也留着（不然第二天又升级、又推一次）
        stuck_key = make_key(step, None, "NEEDS_HUMAN.STUCK")
        stuck = folded.get(stuck_key)
        if stuck is not None and not stuck.get("resolved_at"):
            done = {r["key"] for r in targets}
            still = any(r.get("step") == step and not r.get("resolved_at") and r["key"] not in done
                        and str(r.get("code", "")).startswith("TRANSIENT.") for r in folded.values())
            if still:
                targets = [r for r in targets if r["key"] != stuck_key]
            elif stuck_key not in done:
                targets.append(stuck)
        if not targets:
            return 0
        now = (_now_fn or _now)().isoformat(timespec="seconds")
        _append([{"ts": now, "key": r["key"], "step": step, "item_id": item_id or None, "code": r["code"],
                  "resolved_at": now, "count": 0} for r in targets])
        return len(targets)
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 标记已解决失败（{errtext(exc)}）", file=sys.stderr)
        return 0


def reconcile_account(session: dict[str, Any] | None = None) -> int:
    """1017（她：账号是否正常只看一个状态）：号的事只认读取服务的 /login/session（不拉起服务、不开页、不拿锁）。
    已登录、没熔断（限频冷却到点算没熔断）、没在扫码 / 验证 → 走 sync_state.account_ok()：login 下掉登录 / 验证 /
    风控 / 限频 / 夜里验证那几条一并已解决，同步状态里的账号「!」也撤。查不清（服务没起、超时）一律不动（fail-open）。
    返回解决了几条。永不抛异常。"""
    try:
        from . import accounts, sync_state
        if session is None:
            session = accounts.api("GET", "/api/v1/login/session", timeout=3)
        if not isinstance(session, dict):
            return 0
        if session.get("verifying") or session.get("state") == "waiting" or accounts.hold_from_session(session):
            return 0
        open_login = [r for r in _fold(_read_rows()).values() if r.get("step") == "login" and not r.get("resolved_at")]
        before = len(open_login)
        if not before:
            return 0
        if session.get("logged_in") is False:
            return 0
        if session.get("logged_in") is None and not _used_fine_since(max(str(r.get("ts") or "") for r in open_login)):
            # 读取服务重启后还没查过登录（logged_in 不知道）：看用号日志——这之后号用成功过、最近一次也没被拦，就算好着
            return 0
        sync_state.account_ok()
        after = sum(1 for r in _fold(_read_rows()).values() if r.get("step") == "login" and not r.get("resolved_at"))
        return before - after
    except Exception as exc:  # noqa: BLE001 - 对不上就照旧显示，不挡面板
        print(f"[problems] 账号状态没对上（{errtext(exc)}）", file=sys.stderr)
        return 0


def _used_fine_since(ts: str) -> bool:
    """1017：用号行为日志里，ts 之后有成功的用号，且最近一次用号不是被拦（风控 / 限频 / 验证 / 掉登录）。"""
    try:
        from . import actionlog
        since = datetime.fromisoformat(ts)
        rows = [r for r in actionlog.read(since=since) if actionlog._ts(r) and actionlog._ts(r) > since]
    except Exception:  # noqa: BLE001
        return False
    if not rows:
        return False
    rows.sort(key=lambda r: actionlog._ts(r))
    return any(r.get("ok") for r in rows) and not actionlog.is_risk(rows[-1])


# 1015：同一次熔断只显示一条——起因（验证 / 安全跳转 / 掉登录 / 限频）那条还开着时，之后各步撞见「熔断中」登记的
# RISK_HOLD 是同一件事（她截图里两条一起挂着），面板和计数都只留起因那条。
HOLD_CAUSE_CODES = ("CAPTCHA_REQUIRED", "ACCOUNT_RISK", "NOT_LOGGED_IN", "ACCOUNT_BLOCKED", "XHS_RATE_LIMITED", "NIGHT_CAPTCHA")


def _hold_cause_open(rows: list[dict[str, Any]]) -> bool:
    """起因（验证 / 安全跳转 / 掉登录 / 限频）那条还开着、没隐藏。"""
    return any(not r.get("resolved_at") and not is_hidden(r) and r.get("step") in ("login", "comments.fill")
               and str(r.get("code") or "").rsplit(".", 1)[-1] in HOLD_CAUSE_CODES for r in rows)


def _same_hold_dupes(rows: list[dict[str, Any]]) -> set[str]:
    """没解决、没隐藏的行里，被起因那条代表了的 RISK_HOLD 行的 key。"""
    def sub(r):
        return str(r.get("code") or "").rsplit(".", 1)[-1]
    live = [r for r in rows if not r.get("resolved_at") and not is_hidden(r)]
    if not _hold_cause_open(live):
        return set()
    return {str(r.get("key")) for r in live if sub(r) == "RISK_HOLD"}


def load(limit: int = MAX_KEYS, *, include_resolved: bool = False, include_minor: bool = True) -> list[dict[str, Any]]:
    """折叠后的问题：未解决在前（要你处理 → 自动处理 → 已放弃 → 未开启），同组新的在前。

    1011：include_minor=False（面板 `problems list` 用）把轻微的（is_minor）也拿掉——已解决和轻微的只在诊断导出里。"""
    folded = list(_fold(_read_rows()).values())
    if not include_resolved:
        folded = [r for r in folded if not r.get("resolved_at")]
    dupes = _same_hold_dupes(folded)
    if dupes:
        folded = [r for r in folded if str(r.get("key")) not in dupes]
    if not include_minor:
        folded = [r for r in folded if not is_minor(r)]
    order = {"needs_you": 0, "auto": 1, "gave_up": 2, "off": 3}

    def sort_key(r):
        try:
            group = GROUP_OF_CLASS[classify(r.get("code", ""))]
        except BadCode:
            group = "auto"
        return (1 if r.get("resolved_at") else 0, order[group], _neg_ts(r.get("ts")))

    folded.sort(key=sort_key)
    titles = _catalog_titles({str(r["item_id"]) for r in folded[:limit] if r.get("item_id") and not r.get("title")})
    out = []
    for r in folded[:limit]:
        if not r.get("title") and titles.get(str(r.get("item_id") or "")):
            r = {**r, "title": titles[str(r["item_id"])]}
        try:
            entry = lookup(r["code"])
        except (BadCode, KeyError):
            entry = {"label": r.get("code", ""), "hover": "{reason}", "where": "list", "group": "auto"}
        out.append({**r, "label": entry["label"], "group": entry["group"], "where": entry["where"],
                    "hover": fill_hover(entry["hover"], r.get("reason"), r.get("next_at")),
                    "step_label": step_label(r.get("step")),
                    # 1008：她手动隐藏的（面板放进默认收起的「已隐藏」区，可恢复）
                    "hidden": is_hidden(r), "hidden_repeats": int(r.get("hidden_repeats") or 0),
                    "dismissable": _dismissable(r), "minor": is_minor(r), "category": category(r)})
        if not r.get("resolved_at"):
            try:  # 面板要的「现在修」/ 状态一句话（repair.describe）；算不出来不影响列表
                from . import repair
                out[-1].update(repair.describe(r))
            except Exception as exc:  # noqa: BLE001
                print(f"[problems] 修复说明算不出来（{errtext(exc)}）", file=sys.stderr)
    return out


def _catalog_titles(ids: set[str]) -> dict[str, str]:
    """1017：登记时没带标题的那几篇（面板上标题位只剩「网页版要验证 网页版要验证」）——从目录数据补上。读不到就不补。"""
    if not ids:
        return {}
    try:
        data = json.loads((storage.archive_root() / "catalog-data.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for it in (data.get("items") or []) if isinstance(data, dict) else []:
        iid = isinstance(it, dict) and (it.get("id") or it.get("item_id"))
        if iid in ids and it.get("title"):
            out[iid] = str(it["title"])[:TITLE_MAX]
    return out


# 1017（她：评论没补全多条合并一条就行）：同一种「一篇一条」的毛病，面板里 ≥2 篇就并成一条「N 篇…」，展开是每一篇
# （各自的查看 / 打开验证）；某一篇修好（resolve）就从这条里撤掉，全撤完整条消失。诊断导出照旧一篇一行。
FOLD_CODES = {
    "PERMANENT.COMMENTS_INCOMPLETE": ("篇评论没补全", "楼中楼还没读全，后台在接着读；读全的那篇会自己从这里消失"),
    "PERMANENT.NOTE_RESTRICTED": ("篇网页版打不开", "隔天重开还是打不开（号是好的，只是这几篇）：点那篇的「打开验证」，"
                                                "在弹出的窗口里过一下验证、看到笔记后关窗；过了会自动补抓"),
}
FOLD_PREFIX = "fold|"


def fold_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """面板用：FOLD_CODES 里同一个码、没解决没隐藏的 ≥2 篇并成一行（key = fold|<码>），位置放在其中最新那篇处。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("code") in FOLD_CODES and not r.get("resolved_at") and not r.get("hidden") and r.get("item_id"):
            groups.setdefault(r["code"], []).append(r)
    out, done = [], set()
    for r in rows:
        code = r.get("code")
        members = groups.get(code) or []
        if len(members) < 2 or r not in members:
            out.append(r)
            continue
        if code in done:
            continue
        done.add(code)
        tail, hover = FOLD_CODES[code]
        out.append({**members[0], "key": FOLD_PREFIX + code, "item_id": None, "title": f"{len(members)} {tail}",
                    "hover": hover, "reason": hover, "count": len(members), "folded": True,
                    "ts": max(str(m.get("ts") or "") for m in members),
                    "dismissable": all(m.get("dismissable") for m in members), "repairable": False,
                    "status_text": "", "repair_note": None, "repair_state": None, "evidence_id": None,
                    "items": [{"key": m["key"], "item_id": m["item_id"], "title": m.get("title") or m["item_id"],
                               "reason": m.get("reason") or ""} for m in members]})
    return out


def _neg_ts(ts) -> float:
    try:
        return -datetime.fromisoformat(str(ts)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def summary() -> dict[str, Any]:
    """{needs_human, auto, gave_up, skipped, hidden, minor, last_runs: {step: {ts, ok}}}——顶部入口的计数。
    1011：轻微的（is_minor）不计数、另给 minor，只为诊断导出。

    1008：她隐藏的不计数（另给 hidden）；last_runs 按步骤取最近一次登记 / 解决的时刻，ok = 这一步现在没有还开着的问题
    （以前取原始最后一行：注记行、某一篇的老失败都会顶上来，补查正常跑完不写行就一直停在「有问题」）。
    附件补查另以 _archive/attachments-recheck-status.json（每次运行都写，跳过也写）为准，比问题记录新就用它。"""
    rows = _read_rows()
    folded = _fold(rows)
    counts = {"needs_human": 0, "auto": 0, "gave_up": 0, "skipped": 0, "hidden": 0, "minor": 0}
    open_steps: set[str] = set()
    dupes = _same_hold_dupes(list(folded.values()))
    folded_seen: dict[str, int] = {}
    for r in folded.values():
        if r.get("resolved_at") or str(r.get("key")) in dupes:
            continue
        if is_minor(r):
            counts["minor"] += 1  # 1011：轻微的不进任何计数，也不让那一步算「有问题」
            continue
        if is_hidden(r):
            counts["hidden"] += 1
            continue
        if r.get("step"):
            open_steps.add(r["step"])
        if r.get("code") in FOLD_CODES and r.get("item_id"):
            folded_seen.setdefault(r["code"], 0)
            folded_seen[r["code"]] += 1
            if folded_seen[r["code"]] > 1:
                continue  # 1017：面板里并成一条，计数也只算一条
        try:
            counts[SUMMARY_KEY[classify(r.get("code", ""))]] += 1
        except BadCode:
            counts["auto"] += 1
    last: dict[str, dict[str, Any]] = {}
    for r in rows:
        step = r.get("step")
        if not step or r.get("note") or "dismiss" in r:
            continue  # 注记 / 隐藏行不是一次运行
        if step not in last or str(r.get("ts") or "") >= str(last[step]["ts"] or ""):
            last[step] = {"ts": r.get("ts"), "ok": step not in open_steps}
    for step, info in last.items():
        info["ok"] = step not in open_steps
    run = _recheck_run()
    if run and (not last.get("attachments.recheck") or _neg_ts(run["ts"]) <= _neg_ts(last["attachments.recheck"]["ts"])):
        last["attachments.recheck"] = run
    return {**counts, "last_runs": last}


def _recheck_run() -> dict[str, Any] | None:
    """附件补查最近一次运行（attachments.recheck_status 写的状态文件）→ {ts, ok, skipped?, note}。读不到 = None。"""
    try:
        st = storage.read_json(storage.archive_root() / "attachments-recheck-status.json")
    except (OSError, ValueError):
        return None
    if not isinstance(st, dict) or not st.get("at"):
        return None
    out = {"ts": st.get("at"), "ok": not st.get("stopped_reason") or st.get("stopped_reason") in ("done", "limit", "out_of_time")}
    if st.get("skipped"):
        out["skipped"] = st.get("skipped")
    if st.get("text"):
        out["note"] = str(st.get("text"))[:200]
    return out


MIGRATIONS_NAME = "problem-migrations.json"


def migrate_orphan_refine() -> int:
    """一次性迁移（1008，B2-7）：卡片上有「AI 结果不可用」标（vision.json 里有 refine failed 的图）、问题记录里却没有
    没解决的条目——当时问题面板还没接上这类报错。补登记一次，好让她在面板里看得到、能隐藏。
    ts 用 vision.json 里那张图的 refine.at（不是「现在」）；PERMANENT 不推送。做过一次就记在 problem-migrations.json，
    之后零开销。不放在 catalog build 里（Obsidian「刷新目录」也会 build，刷新不该有写问题记录的副作用）。永不抛异常。"""
    try:
        mark = storage.archive_root() / MIGRATIONS_NAME
        try:
            done = storage.read_json(mark)
        except (OSError, ValueError):
            done = {}
        if not isinstance(done, dict):
            done = {}
        if done.get("orphan_refine_1008"):
            return 0
        folded = _fold(_read_rows())
        rows = []
        for vpath in sorted(storage.archive_root().glob("*/*/derived/vision.json")):
            try:
                doc = storage.read_json(vpath)
            except (OSError, ValueError):
                continue
            failed = [im for im in doc.get("images", []) if (im.get("refine") or {}).get("status") == "failed"]
            if not failed:
                continue
            obj = vpath.parents[1]
            if obj.parent.name not in domain.PREFIX:   # _archive 下不是来源目录的杂目录，不算
                continue
            try:
                item_id = storage.read_json(obj / "meta.json").get("item_id") or domain.item_id(obj.parent.name, obj.name)
            except (OSError, ValueError):
                item_id = domain.item_id(obj.parent.name, obj.name)
            code = "PERMANENT.MODEL_OUTPUT_INVALID"
            prev = folded.get(make_key("vision.refine", item_id, code))
            if prev and not prev.get("resolved_at"):
                continue
            last = max(failed, key=lambda im: str((im.get("refine") or {}).get("at") or ""))
            ref = last.get("refine") or {}
            ts = str(ref.get("at") or "") or _now().isoformat(timespec="seconds")
            reason = (f"{str(last.get('asset') or '').split('/')[-1]}：{ref.get('error') or '精细识别结果不合格'}"
                      "（补登记：卡片上一直有这个标，当时问题面板还没接上）")
            rows.append({"ts": ts, "key": make_key("vision.refine", item_id, code), "step": "vision.refine",
                         "item_id": item_id, "title": None, "code": code, "reason": reason[:REASON_MAX],
                         "action": "gave_up", "next_at": None, "count": 1, "resolved_at": None})
        if rows:
            _append(rows)
        storage.write_json(mark, {**done, "orphan_refine_1008": _now().isoformat(timespec="seconds")})
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 一次性补登记没做成（{errtext(exc)}）", file=sys.stderr)
        return 0


# --------------------------------------------------------------------------
# 隐藏 / 恢复（1008，B2）
# --------------------------------------------------------------------------


def _dismissable(r: dict[str, Any]) -> bool:
    try:
        return (not r.get("resolved_at") and classify(r.get("code") or "") in DISMISSABLE_CLASSES)
    except BadCode:
        return False


def _refuse_reason(r: dict[str, Any]) -> str:
    try:
        cls = classify(r.get("code") or "")
    except BadCode:
        cls = ""
    if cls == "NEEDS_HUMAN":
        return "这条要你处理（账号 / key / 备份盘这类），不能隐藏"
    if cls == "TRANSIENT":
        return "这条正在自动处理，修好会自己消失，不能隐藏"
    return "这条不是「已放弃」的问题，不能隐藏"


def dismiss(key: str | None = None, group: str | None = None, *, category_name: str | None = None,
            _now_fn=None) -> dict[str, Any]:
    """隐藏一条（key）、整组已放弃（group="gave_up"）或面板一个分区里能隐藏的（category_name，1017）。只接受没解决的 PERMANENT。
    返回 {ok, code, message, dismissed:[key]}（CONVENTIONS §1 的形状）。"""
    try:
        folded = _fold(_read_rows())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": "READ_FAILED", "message": f"问题记录读不出来：{exc}", "dismissed": []}
    if category_name:
        if category_name not in dict(CATEGORIES):
            return {"ok": False, "code": "BAD_GROUP", "message": "没有这个分区", "dismissed": []}
        targets = [r for r in folded.values() if _dismissable(r) and not is_hidden(r) and not is_minor(r)
                   and category(r) == category_name]
    elif group:
        if group != "gave_up":
            return {"ok": False, "code": "BAD_GROUP", "message": "只能整组隐藏「已放弃」", "dismissed": []}
        targets = [r for r in folded.values() if _dismissable(r) and not is_hidden(r) and not is_minor(r)]
    elif str(key or "").startswith(FOLD_PREFIX):
        # 1017：并起来的那条 = 隐藏它下面每一篇
        code = str(key)[len(FOLD_PREFIX):]
        targets = [r for r in folded.values() if r.get("code") == code and r.get("item_id") and _dismissable(r)
                   and not is_hidden(r) and not is_minor(r)]
    else:
        r = folded.get(str(key or ""))
        if r is None or r.get("resolved_at"):
            return {"ok": False, "code": "NOT_FOUND", "message": "这条已经好了或不存在", "dismissed": []}
        if not _dismissable(r):
            return {"ok": False, "code": "NOT_DISMISSABLE", "message": _refuse_reason(r), "dismissed": []}
        if is_hidden(r):
            return {"ok": True, "code": "", "message": "这条已经隐藏了", "dismissed": []}
        targets = [r]
    if not targets:
        return {"ok": True, "code": "", "message": "没有要隐藏的", "dismissed": []}
    now = (_now_fn or _now)().isoformat(timespec="seconds")
    try:
        _append([{"ts": now, "key": r["key"], "step": r.get("step"), "item_id": r.get("item_id") or None,
                  "code": r.get("code"), "dismiss": True, "by": "owner"} for r in targets])
    except OSError as exc:
        return {"ok": False, "code": "WRITE_FAILED", "message": f"问题记录写不进去：{exc}", "dismissed": []}
    n = len(targets)
    return {"ok": True, "code": "", "dismissed": [r["key"] for r in targets],
            "message": f"已隐藏 {n} 条，可在列表最下面「已隐藏」里恢复；同样的原因再出现不会再打扰你"}


def undismiss(key: str, *, _now_fn=None) -> dict[str, Any]:
    """恢复显示一条隐藏的。返回 {ok, code, message, restored:[key]}。"""
    try:
        r = _fold(_read_rows()).get(str(key or ""))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": "READ_FAILED", "message": f"问题记录读不出来：{exc}", "restored": []}
    if r is None or r.get("resolved_at"):
        return {"ok": False, "code": "NOT_FOUND", "message": "这条已经好了或不存在", "restored": []}
    if not is_hidden(r):
        return {"ok": True, "code": "", "message": "这条本来就显示着", "restored": []}
    now = (_now_fn or _now)().isoformat(timespec="seconds")
    try:
        _append([{"ts": now, "key": r["key"], "step": r.get("step"), "item_id": r.get("item_id") or None,
                  "code": r.get("code"), "dismiss": False, "by": "owner"}])
    except OSError as exc:
        return {"ok": False, "code": "WRITE_FAILED", "message": f"问题记录写不进去：{exc}", "restored": []}
    return {"ok": True, "code": "", "message": "已恢复显示", "restored": [r["key"]]}


def dismissed_pairs() -> set[tuple[str, str]]:
    """{(item_id, 细分码)}：她隐藏了、还没解决的按篇问题（目录卡片角标据此不出标）。读不动就当没有。"""
    try:
        folded = _fold(_read_rows())
    except Exception:  # noqa: BLE001
        return set()
    return {(str(r.get("item_id")), str(r.get("key", "")).rsplit("|", 1)[-1])
            for r in folded.values() if is_hidden(r) and r.get("item_id")}


def resolve_item(item_id: str, *, _now_fn=None) -> int:
    """她删掉一篇笔记：这篇名下所有没解决的问题标成已解决（真正的「删除」只发生在这里）。永不抛异常。"""
    try:
        folded = _fold(_read_rows())
        targets = [r for r in folded.values() if (r.get("item_id") or None) == item_id and not r.get("resolved_at")]
        if not targets:
            return 0
        now = (_now_fn or _now)().isoformat(timespec="seconds")
        _append([{"ts": now, "key": r["key"], "step": r.get("step"), "item_id": item_id, "code": r["code"],
                  "resolved_at": now, "count": 0, "why": "note_removed"} for r in targets])
        return len(targets)
    except Exception as exc:  # noqa: BLE001
        print(f"[problems] 删笔记时撤问题没成（{errtext(exc)}）", file=sys.stderr)
        return 0


# --------------------------------------------------------------------------
# 「复制报错」（§3.5）
# --------------------------------------------------------------------------

_SECRET_RE = re.compile(
    r'(?i)("?(?:api[_-]?key|apikey|token|cookie|authorization|x-api-key|secret|password)"?\s*[:=]\s*)'
    r'("[^"]*"|\'[^\']*\'|[^\s,;&}]+)')
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_XSEC_RE = re.compile(r"(?i)(xsec_token=)[^&\s\"'<>]+")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
# 1008：出事证据目录（截图里有私密收藏）的路径不进「复制报错」：整段换成占位
_EVIDENCE_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>]*?risk-evidence[^\s\"'<>]*|[~/][^\s\"'<>]*?risk-evidence[^\s\"'<>]*")


def redact(text: str, *, vault: Path | None = None, home: Path | None = None) -> str:
    """去掉 apiKey/token/cookie/Authorization/Bearer 后面的值、xsec_token 参数值；vault 绝对路径换 <vault>、家目录换 ~。"""
    text = str(text or "")
    text = _BEARER_RE.sub(r"\1 <redacted>", text)
    text = _SECRET_RE.sub(lambda m: m.group(1) + ('"<redacted>"' if m.group(2).startswith('"') else "<redacted>"), text)
    text = _XSEC_RE.sub(r"\1<redacted>", text)
    text = _SK_RE.sub("sk-<redacted>", text)
    text = _EVIDENCE_RE.sub("<本机证据目录>", text)
    vault = Path(vault) if vault else storage.vault_root()
    home = Path(home) if home else Path.home()
    for raw, token in ((str(vault), "<vault>"), (str(home), "~")):
        if not raw or len(raw) < 3:
            continue
        variants = {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\"), raw.replace("/", "\\")}
        for v in sorted(variants, key=len, reverse=True):
            text = re.sub(re.escape(v), lambda _m, t=token: t, text, flags=re.IGNORECASE)
    return text


def _plugin_version() -> str:
    try:
        manifest = storage.repo_root() / "obsidian-plugins" / "link-brain-actions" / "manifest.json"
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "?")
    except (OSError, ValueError):
        return "?"


def export_redacted(limit: int = 50, *, plugin_version: str | None = None) -> str:
    """「复制报错」的内容：插件版本 · Python 版本 · 各 step 上次运行结果 · 最近 50 条问题，全部脱敏。
    保留 item_id 和标题（用户自己的数据）。"""
    from . import __version__

    s = summary()
    lines = [
        "# Link Brain 诊断信息（已脱敏）",
        f"- 插件版本：{plugin_version or _plugin_version()} · link_brain {__version__}",
        f"- Python：{platform.python_version()} · {platform.system()} {platform.release()}",
        f"- 问题计数：要你处理 {s['needs_human']} · 自动处理中 {s['auto']} · 已放弃 {s['gave_up']} · 未开启 {s['skipped']}"
        f" · 已隐藏 {s.get('hidden', 0)} · 轻微（不进列表）{s.get('minor', 0)}",
        "",
        "## 各步骤上次记录",
    ]
    for step, info in sorted(s["last_runs"].items()):
        lines.append(f"- {step}：{info.get('ts') or '?'} · {'已恢复' if info.get('ok') else '有问题'}")
    if not s["last_runs"]:
        lines.append("- （没有记录）")
    lines += ["", f"## 最近 {limit} 条问题"]
    rows = load(MAX_KEYS, include_resolved=True)
    rows.sort(key=lambda r: _neg_ts(r.get("ts")))
    for r in rows[:limit]:
        state = ("已解决" if r.get("resolved_at") else "轻微（不进列表）" if r.get("minor")
                 else "已隐藏" if r.get("hidden") else r.get("action") or "")
        lines.append(" · ".join(str(x) for x in (r.get("ts"), r.get("step"), r.get("item_id") or "-",
                                                 r.get("title") or "", r.get("code"), state,
                                                 f"×{r.get('count')}", r.get("reason") or "") if x != ""))
    if not rows:
        lines.append("- （没有问题记录）")
    return redact("\n".join(lines))


# --------------------------------------------------------------------------
# CLI：python -m link_brain problems list|report|resolve|export|summary
# --------------------------------------------------------------------------


def add_parser(sub) -> None:
    p = sub.add_parser("problems", help="问题记录：list 列出 / report 登记一条（夜跑脚本用）/ export 复制报错（脱敏）")
    psub = p.add_subparsers(dest="problems_cmd", metavar="<list|report|resolve|export|summary|repair|dismiss|undismiss>")
    pl = psub.add_parser("list", help="列出问题（折叠后，未解决在前），输出 JSON")
    pl.add_argument("--all", action="store_true", help="连已解决的、轻微的（楼中楼只缺 ≤2 条）也列")
    pl.add_argument("--limit", type=int, default=MAX_KEYS)
    pr = psub.add_parser("report", help="登记一条问题（夜跑脚本登记步骤超时用），输出 JSON")
    pr.add_argument("--step", required=True)
    pr.add_argument("--code", required=True, help="类.细分，如 TRANSIENT.STEP_TIMEOUT")
    pr.add_argument("--reason", default="")
    pr.add_argument("--item-id", dest="item_id")
    pr.add_argument("--title")
    pr.add_argument("--action", choices=ACTIONS)
    pr.add_argument("--next-at", dest="next_at")
    pv = psub.add_parser("resolve", help="把一步（+ 一篇 / 一个码）的问题标成已解决（夜跑每步成功后调），输出 JSON")
    pv.add_argument("--step", required=True)
    pv.add_argument("--item-id", dest="item_id")
    pv.add_argument("--code", help="只解决这个码（类.细分 或 现有裸码）")
    pe = psub.add_parser("export", help="复制报错：脱敏后的诊断信息，输出 JSON {text}")
    pe.add_argument("--limit", type=int, default=50)
    pe.add_argument("--plugin-version", dest="plugin_version")
    pd = psub.add_parser("dismiss", help="隐藏已放弃的问题（她手动、可恢复、照样导出），输出 JSON")
    pd_one = pd.add_mutually_exclusive_group(required=True)
    pd_one.add_argument("--key", help="只隐藏这一条")
    pd_one.add_argument("--group", choices=("gave_up",), help="整组隐藏「已放弃」")
    pd_one.add_argument("--category", choices=tuple(c for c, _ in CATEGORIES), help="隐藏面板这个分区里能隐藏的（1017）")
    pu = psub.add_parser("undismiss", help="恢复显示一条隐藏的问题，输出 JSON")
    pu.add_argument("--key", required=True)
    psub.add_parser("summary", help="核一次同步进程还在不在（被打断就如实改成 INTERRUPTED）、刷新 problems-summary.json，输出它")
    pf = psub.add_parser("repair", help="当场自愈：对还没解决的非风控问题跑对应的修复动作（风控 / 登录类绝不碰），输出 JSON")
    pf.add_argument("--key", help="只修这一条（面板「现在修」）")
    pf.add_argument("--since", help="只修这个时刻之后登记的（夜跑收尾的自愈轮）")
    pf.add_argument("--auto", action="store_true", help="夜跑自愈轮：只跑能自动跑的动作（不重读收藏列表、PERMANENT 不重试）")
    pf.add_argument("--no-account", dest="no_account", action="store_true", help="号要人处理时：碰号的修复动作一律不跑")
    pf.add_argument("--budget-seconds", dest="budget_seconds", type=float, default=None,
                    help="这一轮最多跑几秒（默认：单条 20 分钟 / 全部 15 分钟 / 夜跑自愈轮 30 分钟，且不过 06:50）")


def _valid_step(step: str) -> bool:
    # 夜跑步骤名：nightly.<小写字母 / 数字 / 连字符 / 下划线>，如 nightly.sync-favorites、nightly.catalog-final
    return step in STEPS or any(step.startswith(p) and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", step[len(p):])
                                for p in STEP_PREFIXES)


def run(args) -> int:
    from .read import dump_json

    cmd = getattr(args, "problems_cmd", None)
    if cmd == "repair":
        from . import repair
        result = repair.run(key=args.key, since=args.since, auto=args.auto, allow_account=not args.no_account,
                            budget_seconds=args.budget_seconds)
        dump_json(result)
        # 修不好的已经逐条写回问题记录（试过什么、为什么没好、下一步）：不算「这一步出错」，免得夜跑再多登记一条
        return 0 if result.get("ran", True) else 1
    if cmd == "list":
        from . import ai_health, usage
        reconcile_account()  # 1017：账号那几行先和读取服务的实时状态对齐（号好着就撤掉旧的掉登录 / 限频）
        try:
            from . import restricted as _restricted
            _restricted.quiet_unconfirmed()  # 1017：只撞见过一天的「网页版要验证」收掉，等隔天再开一次
        except Exception as exc:  # noqa: BLE001
            print(f"[problems] 疑似要验证的没收成：{errtext(exc)}", file=sys.stderr)
        ai_health.migrate_legacy_rows()  # 1008：老记录里按篇登的 key 失效 / 欠费收成每个接口一条（幂等，没有就 0 开销）
        migrate_orphan_refine()  # 1008：卡片上有标、面板里没有的精细识图失败补登记一次（做过就不再做）
        try:
            from . import restricted
            restricted.reclassify_fill_failures()  # 1016：续读报 [NOTE_RESTRICTED] 却记成 COMMENTS_INCOMPLETE 的改记（幂等、零开页）
        except Exception as exc:  # noqa: BLE001 - 迁移失败不挡面板
            print(f"[problems] 网页版要验证改记没做成：{errtext(exc)}", file=sys.stderr)
        dump_json({"ok": True, "code": "", "message": "", "summary": summary(),
                   "problems": usage.decorate_problem_rows(
                       (lambda rows: rows if args.all else fold_rows(rows))(
                           load(args.limit, include_resolved=args.all, include_minor=args.all)))})
        return 0
    if cmd == "report":
        if not _valid_step(args.step):
            print(f"step 不在词表里：{args.step}（见 CONVENTIONS §2 step 词表，夜跑用 nightly.<名>）", file=sys.stderr)
            return 1
        try:
            row = report(args.step, args.code, args.reason, item_id=args.item_id, title=args.title,
                         action=args.action, next_at=args.next_at)
        except (BadCode, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        ok = bool(row.get("written"))
        dump_json({"ok": ok, "code": "", "message": "已登记" if ok else "问题记录没写进去", "row": row})
        if not ok:
            print("问题记录没写进去（磁盘或权限）", file=sys.stderr)
        return 0 if ok else 1
    if cmd == "export":
        dump_json({"ok": True, "code": "", "message": "已生成诊断信息",
                   "text": export_redacted(args.limit, plugin_version=args.plugin_version)})
        return 0
    if cmd == "resolve":
        if not _valid_step(args.step):
            print(f"step 不在词表里：{args.step}（见 CONVENTIONS §2 step 词表，夜跑用 nightly.<名>）", file=sys.stderr)
            dump_json({"ok": False, "code": "", "message": "step 不在词表里", "resolved": 0})
            return 1
        if args.code:
            try:
                normalize(args.code)
            except BadCode as exc:
                print(str(exc), file=sys.stderr)
                dump_json({"ok": False, "code": "", "message": str(exc), "resolved": 0})
                return 1
        n = resolve(args.step, args.item_id, args.code)
        dump_json({"ok": True, "code": "", "message": f"已解决 {n} 条" if n else "没有要解决的", "resolved": n})
        return 0
    if cmd == "dismiss":
        result = dismiss(key=args.key, group=args.group, category_name=getattr(args, "category", None))
        dump_json(result)
        if result.get("dismissed"):
            write_summary()
        return 0 if result["ok"] else 1
    if cmd == "undismiss":
        result = undismiss(args.key)
        dump_json(result)
        return 0 if result["ok"] else 1
    if cmd == "summary":
        from . import sync_state
        sync_state.current()  # 进程已死的 running → 落盘成 INTERRUPTED（并登记一条），顺带刷新 summary
        reconcile_account()   # 1017：顶部计数也只认号的实时状态
        try:
            from . import restricted as _restricted
            _restricted.quiet_unconfirmed()
        except Exception:  # noqa: BLE001
            pass
        write_summary()
        try:
            data = storage.read_json(summary_path())
        except (OSError, ValueError):
            data = page_summary()
        dump_json({"ok": True, "code": "", "message": "", **data})
        return 0
    print("用法：python -m link_brain problems list|report|resolve|export|summary|repair|dismiss|undismiss", file=sys.stderr)
    return 1

# 验收：第二波 PR① 规则收口 domain.py（1025）

入口：无新入口。唯一用户可见的变化在目录页「来源 ▾」下拉：原来「聊天分享」一组并进「fable」。

## 步骤 / 预期 / 实测

| 步骤 | 预期 | 实测 |
|---|---|---|
| `pytest tests/test_domain.py` | 全绿；`test_tg_share_counts_as_fable` 在修前（provenance 旧规则）是红的 | 修前红（返回「聊天分享」）→ 修后绿 |
| `pytest tests/test_provenance_1020.py` | 两处断言按新口径改后全绿 | 绿 |
| 守卫 `tests/test_guards.py` | 「item_id 前缀」基线只剩 accounts（xhs-profile 目录名）/ adapters（xhs-guest- 临时目录）/ restore（cssclass xhs-note）各 1，都不是 item_id | 如预期 |
| 全量 pytest（TZ=Australia/Sydney）+ node 与 main 对比 | 无新增失败 | 见 PR 描述 |
| 本地 catalog build（真库） | 「来源 ▾」没有「聊天分享」，原来那几篇出现在 fable 组；items 多一个 `via` 键 | **待她：一步**（部署后在 Obsidian 目录页点「来源 ▾」看一眼） |

## 待她：一步
部署后打开目录页「来源 ▾」：原来「聊天分享」那组的帖应在「fable」里；如果之前存过「聊天分享」筛选，会落回「我的收藏」，属预期。

# 验收：第二波 PR⑤a ingest 走暂存 + 单篇锁提交 + 收编孤儿版本（1025）

入口：插件「导入网址」、TG、收藏同步、评论续读都经 `ingest_url`；返回的键不变（多一个可选的 `adopted`）。无新故障码、无界面变化。

## 步骤 / 预期 / 实测

| 步骤 | 预期 | 实测 |
|---|---|---|
| `pytest tests/test_ingest_commit.py` | 8 条全绿；`crash_mid_download` / `orphan_version_is_adopted_not_refetched` / `deleted_during_fetch` / `concurrent_ingest_single_version` 在修前（PR④ 头 2334cff）红 | 修前 4 红 → 修后绿 |
| ingest / 续读 / 删除 / 暂存相关旧测试 | 全绿（返回 dict 的键不变） | 绿 |
| 守卫 | 「在库 / 墓碑判断」ingest 0 处，基线改小 | 如预期 |
| 全量 pytest + node 与 main 对比 | 无新增失败 | 见 PR 描述 |
| 真入口：插件「导入网址」导一篇新的、一篇已在库的 | 新的出 v0001 且 raw/ 下没有 `.staging-` 残留；已在库的秒回「已在库」 | **待她：碰号，等她定时间 / 号**（设计 §7 第 7 条） |

## 不在本 PR 里
通用九步、`sources` 接口、续读 / 抓取细节搬进小红书包（⑤b，等 PR③）。

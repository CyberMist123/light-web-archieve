# 验收：第二波 PR⑤a ingest 走暂存 + 单篇锁提交 + 收编孤儿版本（1025）

入口：插件「导入网址」、TG、收藏同步、评论续读都经 `ingest_url`；返回的键不变（多一个可选的 `adopted`）。无新故障码、无界面变化。

## 步骤 / 预期 / 实测

| 步骤 | 预期 | 实测 |
|---|---|---|
| `pytest tests/test_ingest_commit.py` | 10 条全绿；`crash_mid_download` / `orphan_version_is_adopted_not_refetched` / `deleted_during_fetch` / `concurrent_ingest_single_version` 在修前（PR④ 头 2334cff）红 | 修前 4 红 → 修后绿 |
| ingest / 续读 / 删除 / 暂存相关旧测试 | 全绿（返回 dict 的键不变） | 绿 |
| 守卫 | 「在库 / 墓碑判断」ingest 0 处，基线改小 | 如预期 |
| 全量 pytest + node 与 main 对比 | 无新增失败 | 见 PR 描述 |
| 真入口：插件「导入网址」导一篇新的、一篇已在库的 | 新的出 v0001 且 raw/ 下没有 `.staging-` 残留；已在库的秒回「已在库」 | **待她：碰号，等她定时间 / 号**（设计 §7 第 7 条） |

## 复审（一轮，1025）
修了再合 → 已修：续读 / 手动抓评论时这篇被删了，不再往下读状态、重渲染已进回收站的帖；收编时 meta 指着半截版本就把 current_version / versions 改回完整的那个，一个完整版本都没有就不收编（按新帖抓）；只是索引丢了（meta 在）按已在库返回，不重排识图 / 不覆盖项目，只有从没写成 meta 的孤儿版本按新帖；提交时撞上「别人刚存好 / 内容没变」也照记这次来源的关联、索引跟上。补测试：提交那一刻内容没变不发布、meta 指半截版本的收编。

## 不在本 PR 里
通用九步、`sources` 接口、续读 / 抓取细节搬进小红书包（⑤b，等 PR③）。

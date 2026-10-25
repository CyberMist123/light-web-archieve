# 验收：第二波 PR⓪ 守卫合一（1025）

入口：无用户可见入口。这个 PR 只动测试和文档，不改任何后端行为、不改页面，不需要部署，不需要在 Obsidian 里点。

## 步骤 / 预期 / 实测

| 步骤 | 预期 | 实测 |
|---|---|---|
| `python -m pytest -q tests/test_guards.py` | 全绿：17 条规则各一条 + 自测 | 绿（见 PR 的 CI） |
| 新基线和旧守卫逐条对账 | 命中集合一致 | 手拼异常文字 46 个文件、119 处，与 `test_errtext.BASELINE` 逐文件相等；唯一来源 11 条的 known 白名单 ↔ 基线文件集合一致（计数是新加的粒度） |
| 「手写原子写」改扫全部 `link_brain/**/*.py` | 原来只查 4 个文件，现在把全部现存写法进基线 | 新进基线 2 处：`crawl.py`、`remote/secret_box.py`（各 1 处 `os.replace(tmp`），以后动到这两个文件时收进 `storage.*` |
| 「本机私有路径」改扫全部 py + js | 基线为空 | 空 |
| 全量 `python -m pytest -q`（TZ=Australia/Sydney）与 main 对比 | 无新增失败 | 见 PR 描述 |
| `node tests/run-node.cjs --unit` | 与 main 相同 | 见 PR 描述 |
| 故意在 `catalog.py` 加一行 `type(e).__name__` 再跑 | 「手拼异常文字」红，报 `catalog.py: (4, 3)` | 本地验过，红 → 还原后绿 |

## 待她：一步
无。合并后不用部署、不用重建目录。

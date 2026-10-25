# 验收：最后两处手写原子写迁 storage + 守卫收紧（1025）

入口：无用户可见入口。`crawl-status.json`（`watch` 终端读的那份进度）和设置页「复制口令」的对外行为不变；不需要部署，不需要在 Obsidian 里点。

## 步骤 / 预期 / 实测

| 步骤 | 预期 | 实测 |
|---|---|---|
| 先写 `tests/test_atomic_write_leftovers.py`，改代码前跑 | 「storage.atomic_write_text 抛 OSError」两条红（现在不走 storage，写失败该存活 / 该删旧副本的都没做到），其余绿 | 红：`test_write_status_survives_atomic_write_failure`（文件里多出了 c，没走 storage）、`test_secret_box_save_failure_deletes_old_copy`（save 返回 True，旧副本还在）；输出贴进 PR 正文 |
| 改 `crawl.write_status` / `secret_box.save` 后再跑同一文件 | 4 条全绿 | 绿（4 passed） |
| `python -m pytest -q tests/test_atomic_write_leftovers.py tests/test_guards.py tests/test_remote_cli.py tests/test_remote_1009.py` | 全绿 | 57 passed |
| `python tests/test_guards.py` | 和基线一致 | 和基线一致 |
| `python tests/test_guards.py --write` 后 `git diff tests/guards-baseline.json` | 只许「手写原子写」变 `{}`，其余规则一个字不动；不许出现新文件 | 恰好一处：`手写原子写: {crawl.py:1, remote/secret_box.py:1}` → `{}`；「变多」分支没触发（没加 `--allow-grow`） |
| `git grep -n -E "with_suffix\(.\.tmp.\)\|os\.replace\(tmp" -- link_brain` | 只剩 `storage.py` 自己 | 只剩 `link_brain/storage.py:346`（storage 原子写实现本身） |
| 全量 `python -m pytest -q` 与基线对比 | 无新增红 | 见 PR 描述 |
| `node tests/run-node.cjs --unit` | 与基线相同（82 过 0 败） | 见 PR 描述 |

## 改了什么

- `link_brain/crawl.py`：`write_status` 里 `tmp = p.with_suffix(".tmp")` / `tmp.write_text(...)` / `os.replace(tmp, p)` 三行 → `storage.atomic_write_text(p, json.dumps(...))` 一行；外层 `except OSError: pass` 保留；import 行 `from . import actionlog` → `from . import actionlog, storage`。
- `link_brain/remote/secret_box.py`：`save` 里同样三行 → `storage.atomic_write_text(p, blob)` 一行；外层 `except OSError`（删旧副本、返回 False）保留；新增 `from .. import storage`；`import os` 因 `os.replace` 是它唯一用处一并移除。
- `tests/test_guards.py`：「手写原子写」正则 `os\.replace\(tmp|mkstemp\(|\.tmp'\)` → `os\.replace\(tmp|mkstemp\(|\.tmp["']\)|with_suffix\(["']\.tmp["']\)|NamedTemporaryFile\(`；自测区加 `test_scanner_catches_hand_rolled_atomic_writes`（假仓三种写法各计一次、整行注释不计、storage.py 在 allowed 不计）。
- `tests/guards-baseline.json`：「手写原子写」→ `{}`（`--write` 重写，diff 仅此一处）。
- `tests/test_atomic_write_leftovers.py` 新建（4 条用例，见上表）。

## 待她：一步

无。合并后不用部署、不用重建目录。

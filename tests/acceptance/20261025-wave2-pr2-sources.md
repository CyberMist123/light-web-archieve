# 第二波 PR②：来源接口与异常基类

日期：2026-10-25。基于已合入 PR① 的 main 开工；交付前 PR④ #16 合入，已重放到更新后的 main，仅 STATE 顶部记录发生冲突并保留双方内容。分支 `feat/sources-contract`，草稿 PR 待复审，未部署。

## 范围

- 新建 `link_brain.sources` 的五类异常、数据形状、Protocol 和按模块路径延迟加载的注册表；接口包只 import 标准库。
- 小红书来源薄接现有 parse / fetch / normalize / fingerprint；媒体计划与原下载函数并存。网页附件探测 / 登录号补看仍在 ingest。
- adapter 的五类旧异常名直接指向新类；catch / ingest 只增加 sources import 并替换 except 类名，处理逻辑不变。
- 不搬文件，不改 normalize / download_media / 重试函数本体，不新增 SHA 匹配，不改其他异常组、旧测试或守卫基线。PR⑥ 等 PR⑤ 合并及细则补齐。

## 步骤、预期与实测

1. 在新增接口包但尚未改异常别名与 except 时运行 `python -m pytest -q tests/test_sources_contract.py::test_shared_code_catches_source_errors`。替身令小红书 fetch 抛 `sources.ServiceDown`，预期旧 catch 漏接并返回 error；实际输出：

   ```text
   >       assert result["status"] == "blocked"
   E       AssertionError: assert 'error' == 'blocked'
   E         - blocked
   E         + error
   FAILED tests/test_sources_contract.py::test_shared_code_catches_source_errors
   ```

2. 接通异常别名与 except 后运行 `python -m pytest -q tests/test_sources_contract.py tests/test_guards.py`。预期停车入口返回 blocked 且按服务问题登记；实测 58 项通过，其中来源契约 32 项、守卫 26 项，基线未修改。
3. 来源契约逐项核对：注册来源全部 Protocol 成员、domain.PREFIX 对齐、未知来源报错；脱敏 fixture 的 parse → normalize → fingerprint 与旧函数相等（含 web_probe 上下文）；fetch 参数转发；五类异常同对象且双向 isinstance；中文粘连 / 短链 / 分享口令 / 重复链接 / 非来源 host 的提取与 catch 相等。实测通过。
4. 用同一份脱敏 fixture 生成图片 / 视频笔记，加合成的父评论和楼中楼图片 / 语音，遍历下载图片和视频的四种开关组合；monkeypatch 原下载函数记录实际调用。预期计划的 role / index / comment_id / url 集合，以及 url / stem / kind 顺序与原下载路径一致，每条带原 DOWNLOAD_HEADERS；实测八种组合通过。
5. main 和本分支在独立工作树各跑 `python -m pytest -q`（附 JUnit 输出用于失败集合对照）。实测 PR① 合入后的 main：2057 passed、2 skipped；本分支：2089 passed、2 skipped；两边退出码均为 0，失败集合均为空，无新增失败。PR④ 合入后的重放没有改本 PR 的业务代码；随后补跑 `tests/test_sources_contract.py tests/test_raw_staging.py tests/test_guards.py tests/test_catch.py`，83 passed，退出码 0。全量结果对应重放前的树；重放后未重复全量，Linux 全量对比由 Fable 复审侧执行。
6. `node tests/run-node.cjs --unit`：82 passed, 0 failed, 0 skipped (82 files)。UI 层没跑；本 PR 无页面变动。
7. 隐私闸与 `git diff --check`：通过（提交后、推送前执行隐私闸）。

## 兼容性与发布口径

异常旧名保持同一个类对象；类的 `__name__` 随基类迁移变化。旧 catch / ingest 仍直接调用原函数，小红书包的 ingest / index 引用在函数内延迟加载，避免初始化成环；这些临时转接按计划留给 PR⑤。

本轮只验证离线接口与现有归档入口的异常路径，无新增用户状态，无用户可见行为设计变更，RELEASE-BAR 各项评级不变。不联网碰小红书、不调用读取服务、不写真库；未做线上抓取或 Obsidian 界面验收。

待她：无（本 PR 的离线结构改动不需要新增真号 / 页面操作；合并由作者在 Fable 复审后决定）。

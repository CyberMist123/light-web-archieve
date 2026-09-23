# BENCH — 检索与模型验证

## 2026-09-24 Lot B：hybrid（BM25 × embedding RRF）

基线（改动前）与改动后双跑，18 题金标 + 8 题 paraphrase 集（`"set":"paraphrase"`，换说法探针，不冒充金标）。embedding：`qwen3.7-text-embedding-flash`（本机 key 的 MaaS 网关没有 text-embedding-v4，403 Unpurchased；公网 DashScope 该账号欠费），dimensions=1024，全库 236 篇切 3917 chunk / 3912 唯一 hash。

| 指标 | 词法-only | hybrid |
|---|---|---|
| 金标 18 题 recall@8 | 18/18（基线同） | 18/18（不退化 ✓） |
| paraphrase 8 题 recall@8 | 6/8（75%） | 7/8（87.5%） |
| 单题检索耗时 | 13–33 ms | 1.7–2.7 s（查询向量 HTTP 一次；LRU 缓存后重复问题回到本地扫描） |

hybrid 补上的是「AI睡觉时离线整理记忆的那套方案」；两路都漏的是「让AI自己醒过来而不是被轮询唤起的思路」（AttentionField，正文偏实现细节）。fail-open 实测：无 db / 无 key / numpy 缺 / HTTP 超时全部退纯词法（tests/test_semantic.py 钉住）。证据：`vault/_archive/qa-20260924/retrieval-{baseline,lotb-lexical,lotb-hybrid}.json`。复跑：

```powershell
python -m link_brain embed          # 增量；--all 全部重算
python tests/bench_retrieval.py --out vault/_archive/qa-20260924/retrieval-lotb-hybrid.json
```

嵌入全库一次约 15 分钟（392 个批次，中途超时可直接重跑续传）；查询侧每个新问题一次 embeddings 调用，费用可忽略。

## 2026-09-18 收藏问答与检索

18题位于 `tests/fixtures/retrieval_bench.json`，题目和目标来自真实收藏，尚非 Owner 标注集。会话与存档历史为空，因此这是暂定工程评测，已向 Owner 征集常用原句。一次修正了“记忆做梦”目标ID的抄写错误，改前/改后一起重算；原始 top8 未改。不能用这18题推断任意问题准确率。

| 指标 | 改前 | 改后 |
|---|---|---|
| recall@8，18题各1目标 | 17/18（94.44%） | 18/18（100%） |
| 真实回答成功 | 千问403，0/3 | DS Flash，3/3 |
| 冷启动首字 | 无成功基线 | 2.882秒 |
| 热启动首字 | 无成功基线 | 1.015 / 0.930秒 |
| 总耗时（冷/热/热） | 无成功基线 | 3.930 / 1.947 / 1.855秒 |
| 流块数 | 无成功基线 | 201 / 173 / 177 |

改前的3.292/1.851/2.190秒是失败返回时间，不是首字/回答耗时。没有把它们拿来计算提速比例；总耗时减半尚无法验收，冷首字≤2秒仍未达到。三题依次是蒜香鱼片、空气炸锅杏鲍菇、麻酱虾滑宽粉。鱼片视频转写是背景歌，缺完整菜谱，模型明确说明缺材料，没有把歌声当步骤。

真实配置：Owner 指定 `deepseek-v4-flash`，模型ID放在 `assets/llm-config.yaml` 的 `answer_model`；endpoint 与 keyFile/keyField 只在已忽略的插件 data.json。凭据每次从仓外CSV读取，不复制密钥。默认千问通路依旧使用 `model` 字段。system 指令独立；默认max_tokens=1200；进程内HTTP流式调用，不再起 media.py 子进程。

缓存随catalog文件mtime失效；stdio worker空闲600秒退出，请求150秒超时，异常退出拒绝当前请求并重启，下一次可重试。不新建HTTP服务。没有发现现成可直接用的本地embedding服务，未增加依赖。

证据均在 gitignored 的 `vault/_archive/qa-20260918/`：`retrieval-before.json`、`retrieval-after.json`、`stream-after.json`、`fable-query.json`。公开仓不保存回答原文、签名URL或凭据。复跑检索：

```powershell
python tests/bench_retrieval.py --out vault/_archive/qa-20260918/retrieval-after.json
python tests/bench_worker.py --out vault/_archive/qa-20260918/stream-after.json
```

后一个命令会调用真实模型并产生用量。浏览器测试中的回答为演示数据，仅证明流式交互，不计入模型性能；原生Obsidian三问截图尚未完成。

---

**JSON 一次成功率：5 / 5 = 100%**（qwen3.7-flash，2026-09-04 首轮 5 条样本）
**单条平均估算成本：$0.000125**（阈值 < $0.001，够用）

跑法：

```bash
python -m link_brain render --all --extract     # 缺 extracted.json 才调模型
python -m link_brain render --all --re-extract  # 强制全部重跑（会花钱）
```

模型 / 价格改 `link_brain/assets/llm-config.yaml`，改完把这张表重跑一遍。

## 口径

- token 数是**估算**：调用走 `media.py text`，它不回传 usage，所以按字符估
  （CJK 约 1.5 字/token，其余 4 字符/token，见 `llm.estimate_tokens`）。
  真实账单以阿里云控制台为准，这里只用来横向比较和挡"输入没裁剪"这类错误。
- 价格快照 2026-09-04：`$0.028 / 1M input`、`$0.110 / 1M output`（Qwen 3.7 Flash ≤32K）。
- 输入只有：标题 + 作者 + 正文 + 图片 OCR + 评论（带编号）。
  **`mcp_raw.json` 不进输入**——单条输入超过 ~6k token 基本就是这里漏了。

## 首轮：5 条样本

| # | note_id 后 8 位 | 输入 tokens(估) | 输出 tokens(估) | 估算成本 | JSON 一次成功? | tags 数 | 有价值/广告评论数 | 漏正文? | 误删细节? | 广告当信息? |
|---|---|---|---|---|---|---|---|---|---|---|
| A · P 模式 | `1502522c` | 3358 | 596 | $0.000160 | 是 | 6 | 3/8 |  |  |  |
| B · 无线水吧台（视频） | `1700a211` | 848 | 480 | $0.000077 | 是 | 5 | 4/9 |  |  |  |
| C · 家克 | `2602082f` | 1411 | 448 | $0.000089 | 是 | 6 | 4/12 |  |  |  |
| D · Ombre 二改 | `08031731` | 3979 | 593 | $0.000177 | 是 | 6 | 5/3 |  |  |  |
| E · GPTPro | `080119fe` | 2195 | 548 | $0.000122 | 是 | 6 | 5/0 |  |  |  |

最后三列留给 Owner 人工判定（看 `vault/Web/Xiaohongshu/*.md` 和
`vault/_archive/xiaohongshu/<id>/derived/agent.md`）。

## 已经验到的

- **D 条的关键验收过了**：原帖没有裸 URL，只在文字里提到仓库名，小模型在
  `links_worth_opening` 里点出了 `Yinglianchun/Ombre-Brain`（和原版 `P0luz/Ombre-Brain`、
  `paw-memory`、`Rikkahub`），落进 agent.md 的「外链」小节，标成"原帖没给链接"。
- B 条（视频型）输入最短——正文只有一串 hashtag，没有 OCR 可用，概要基本靠标题 + 评论。
  这条的概要质量最值得 Owner 重点看。
- 广告/噪音判定偏激进（C 条 19 条评论标了 12 条噪音）。当前只影响 agent.md 的标注，
  不删任何内容、不影响人看的那篇；Owner 觉得判太狠就在这张表记一笔，下轮收紧 prompt。

## 待办

- Owner 把样本补到 20 条后重跑，把「漏正文 / 误删细节 / 广告当信息」三列填上。
- 若一次成功率跌破 90% 或平均成本超 $0.001，再考虑 issue #41 第 16 节的
  DeepSeek V4 Flash 做 A/B（换 `llm-config.yaml` 的 model + pricing 即可）。

# BENCH — 小模型派生跑分（Lot 4）

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

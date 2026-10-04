"""召回耗时基准（合成库，R1 收尾的「性能前后对比」）：只测检索，不调任何模型、不碰收藏库、不联网。

    python tests/tools/recall_bench.py [--n 350 1000] [--repeat 5] [--out <结果.json>]

造 N 篇合成笔记（字段长度照真库量级：正文几百字、OCR / 评论上千字、少数篇带几千字附件），语义层和扩词换成确定的桩
（语义 = 按词重叠打分取前 80 篇，扩词 = 固定 4 个词），然后对一组问题各跑 ask.recall：
- cold = 换一份新 items 后第一问（含字段规范化、BM25 统计的建缓存）；
- warm = 同一份 items 再问（问收藏连着问时的常态），取中位数 / p95。
另测目录关键词筛选 retrieval.keyword_hits（目录页同规则的 Python 版；没有这个函数的旧版本跳过）。

只用 ask.recall / retrieval 这几个各版本都有的入口，所以拿旧版本的代码树也能跑（cd 到那棵树里执行同一个文件即可），
前后对比用同一份随机种子。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

WORDS = ("记忆 回避 吵架 依恋 面点 包子 饺子 悉尼 墨尔本 咖啡 早餐 减脂 火锅 苍蝇馆子 做梦 睡眠 知识图谱 向量 检索 权重 衰减 "
         "提示词 模型 开源 项目 部署 插件 笔记 收纳 穿搭 通勤 旅行 东京 大阪 超市 零食 游戏 剧本 盗墓 同人 保险 留学 看病 "
         "调料 步骤 配方 烤箱 面粉 发酵 情绪 陪伴 伴侣 主动 被动 指令 依赖 新颖 奖励 评论 回复 楼主 链接 地址 教程 合集").split()
FILLER = "今天 然后 我们 觉得 真的 可以 因为 所以 还是 就是 一下 这个 那个 已经 没有 自己 时候 大家 一起 其实".split()
QUESTIONS = ["ai 吵架 回避", "面点", "悉尼好吃的", "AI 记忆层有哪些项目推荐", "怎么让AI不忘事", "知识图谱",
             "减脂早餐", "盗墓笔记相关", "权重衰减和加固", "东京便利店零食"]


def _text(rng, n):
    out = []
    for _ in range(n):
        out.append(rng.choice(WORDS) if rng.random() < .3 else rng.choice(FILLER))
    return "".join(out)


def make_items(n, seed=7):
    rng = random.Random(seed)
    items = []
    for k in range(n):
        title = ("AI " if rng.random() < .5 else "") + _text(rng, 4)
        fields = {"body": _text(rng, rng.randint(40, 200)), "ocr": _text(rng, rng.randint(0, 600)),
                  "comments": _text(rng, rng.randint(0, 400)), "transcript": _text(rng, rng.randint(0, 200)) if k % 5 == 0 else "",
                  "attachments": _text(rng, rng.randint(1000, 3000)) if k % 10 == 0 else "", "notes": ""}
        items.append({"id": f"syn-{k:05d}", "title": title, "tags": [rng.choice(WORDS) for _ in range(3)],
                      "cats": [rng.choice(WORDS)], "summary": _text(rng, 30), "note": f"Web/Xiaohongshu/syn-{k:05d}.md",
                      "url": "", "author": f"作者{k % 37}", "starred": k % 23 == 0, "ts": f"2026-09-{k % 28 + 1:02d}",
                      "search_fields": fields})
    return items


def install_stubs(items_ref):
    """语义层 / 扩词换成确定的桩：不调接口，耗时只算检索本身。"""
    from link_brain import ask, retrieval

    def fake_sem(question, depth=80):
        words = set(ask.query_terms(question))
        scored = []
        for it in items_ref[0]:
            text = it["title"] + " ".join(it["tags"]) + it["search_fields"]["body"][:200]
            s = sum(w in text for w in words)
            if s:
                scored.append((s, it["id"]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return {i: {"score": 1 - r / 200, "chunks": [{"field": "body", "text": "", "score": 1 - r / 200}]}
                for r, (_, i) in enumerate(scored[:depth])} or None

    retrieval.semantic_hits = lambda q: fake_sem(q, 40)
    if hasattr(retrieval, "semantic_deep"):
        retrieval.semantic_deep = lambda q: fake_sem(q, 80)
    ask.llm_expansions = lambda q, **k: {"terms": ["记忆", "依恋", "发酵", "通勤"], "status": "cached"}


def bench(n, repeat):
    from link_brain import ask, retrieval
    items_ref = [make_items(n)]
    install_stubs(items_ref)
    cold, warm, kw = [], [], []
    for q in QUESTIONS:
        items_ref[0] = make_items(n)  # 新的一份 items：缓存全部重建（换库 / 重启后第一问）
        start = time.perf_counter()
        ask.recall(q, items_ref[0], {}, [])
        cold.append(time.perf_counter() - start)
        for _ in range(repeat):
            start = time.perf_counter()
            ask.recall(q, items_ref[0], {}, [])
            warm.append(time.perf_counter() - start)
        if hasattr(retrieval, "keyword_hits"):
            for _ in range(repeat):
                start = time.perf_counter()
                retrieval.keyword_hits(q, items_ref[0])
                kw.append(time.perf_counter() - start)

    def stat(xs):
        if not xs:
            return None
        xs = sorted(xs)
        return {"p50_ms": round(statistics.median(xs) * 1000, 1), "p95_ms": round(xs[max(0, int(len(xs) * .95) - 1)] * 1000, 1)}
    return {"n": n, "cold": stat(cold), "warm": stat(warm), "keyword": stat(kw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, nargs="+", default=[350, 1000])
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    rows = [bench(n, args.repeat) for n in args.n]
    print(json.dumps(rows, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

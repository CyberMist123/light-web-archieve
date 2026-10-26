"""Source-specific comment wording and link handling; no rendering dependency."""
from __future__ import annotations

import re
from typing import Any

_URL_TAIL = ".,;:!?\'\"*_~"


def comment_gap_text(comment: dict[str, Any], missing: int, gap_reasons: dict[str, str] | None,
              floor_limit: int | None = None, scoped: bool = False) -> str:
    """这楼还有几条回复没拿到、为什么（1008 Owner：缺口如实标，不写假的「展开 N 条回复」）。
    批次 D · N8：楼层上限外没展开的（原因不知道 / not_expanded）说人话：「另有 N 条回复没存（只存了前 10 楼的回复）」。"""
    from . import adapter as xhs
    reason = (gap_reasons or {}).get(str(comment.get("comment_id") or ""))
    if reason is None or (reason == "not_expanded" and not scoped):
        floors = (("全部楼层" if floor_limit >= 2000 else f"前 {floor_limit} 楼")
                  if isinstance(floor_limit, int) and floor_limit > 0 else "前几楼")
        return f"另有 {missing} 条回复没存（只存了{floors}的回复）"
    # 1009：设置楼数之内的缺口后台会自动补齐；读多少次都一样的（原站多显示 / 楼已删）照实说，不说「接着读」
    if reason == "count_mismatch":
        return f"原站多显示 {missing} 条回复（删了或被折叠，看不到）"
    if reason == "gone":
        return f"还有 {missing} 条回复没拿到（这楼在原帖里已经找不到了，存下的是当时那几条）"
    if reason in ("old_reader", "not_expanded"):  # 只有 scoped（设置楼数之内）才会走到这里
        from .comment_fill import reason_text
        return f"还有 {missing} 条回复没拿到（{reason_text(reason)}，后台在补）"
    why = xhs.REPLY_GAP_CN.get(reason, "没读全")
    tail = "，后台在补" if reason in xhs.RESUMABLE_GAPS else ""
    return f"还有 {missing} 条回复没拿到（{why}{tail}）"


def comment_status_text(capture: dict[str, Any] | None, comments: list[dict[str, Any]],
                        view: dict[str, Any] | None = None) -> str:
    """评论区顶上的一行状态：读到几楼、展开几楼、还缺几条——只在没读全时出现。

    1009：有 view（comment_fill.view_for_render）就按设置楼数现算——设置楼数之内没缺口就不出这一行；
    有缺口写「后台在补」，连着几次补不上写「已记进问题面板」，不再写「下次同步接着读」「不再读」。"""
    if view is not None:
        full = view.get("full")
        if isinstance(full, dict) and full.get("text"):
            # 1026：她手动抓过全部评论：照实写抓到哪了（已抓楼数 / 翻没翻到最后一页 / 还缺什么、为什么 / 上次没成的原因）
            return "全部评论 · " + str(full["text"])
        missing = int(view.get("missing") or 0)
        if missing <= 0:
            return ""
        from .comment_fill import floors_label
        attempts = int(view.get("attempts") or 0)
        why = view.get("why") or "没读全"
        if view.get("stuck"):
            tail = f"，试了 {attempts} 次没补上，已记进问题面板" if attempts else "，已记进问题面板"
        else:
            tail = "，后台在补" + (f"（已续读 {attempts} 次）" if attempts else "")
        text = f"评论读到 {len(comments)} 楼，{floors_label(int(view.get('floors') or 10))}的楼中楼还缺 {missing} 条（{why}{tail}）"
        return text
    cl = (capture or {}).get("comment_load") or {}
    missing = int(cl.get("replies_missing") or 0)
    if missing <= 0:
        if cl:
            return ""
        # 老读取组件没有 comment_load：按楼算楼中楼还缺几条（不编原因）
        lack = 0
        for c in comments or []:
            try:
                lack += max(0, int(c.get("sub_comment_count") or 0) - len(c.get("sub_comments") or []))
            except (TypeError, ValueError):
                continue
        if lack <= 0:
            return ""
        return f"楼中楼还缺 {lack} 条（只存了前几楼的回复）"
    from . import adapter as xhs
    bits = [f"评论读到 {cl.get('floors_loaded') or len(comments)} 楼"]
    if cl.get("floor_limit"):
        bits.append(f"前 {cl['floor_limit']} 楼展开回复")
    gaps = cl.get("gaps") or []
    main = max(gaps, key=lambda g: int(g.get("missing") or 0)).get("reason") if gaps else cl.get("stop_reason")
    why = xhs.REPLY_GAP_CN.get(str(main or ""), "没读全")
    attempts = int(cl.get("fill_attempts") or 0)
    if any(g.get("reason") in xhs.RESUMABLE_GAPS for g in gaps) and attempts < 3:
        tail = "，下次同步接着读" + (f"（已续读 {attempts} 次）" if attempts else "")
    elif attempts >= 3:
        tail = f"，已续读 {attempts} 次，剩下的太长不再读"
    else:
        tail = ""
    bits.append(f"楼中楼还缺 {missing} 条（{why}{tail}）")
    return "，".join(bits)


def is_link_only(note_text: str | None) -> bool:
    """附言是不是「只有一条分享链接、没别的话」——是的话就不该在留言层留一条噪音 cmt1。

    去掉所有 URL 后，只剩空白 / 标点 / 小红书那句「先复制这段文字…」类模板 = 视为纯链接。
    """
    if not note_text:
        return True
    from .adapter import URL_RE

    residual = URL_RE.sub("", note_text)
    residual = re.sub(r"(先复制这段文字|再进【?小红书】?查看完整笔记|打开【?小红书】?浏览笔记|这段文字复制好)", "", residual)
    residual = re.sub(r"[\s，。、；：！？…·\-—|｜/\\【】\[\]（）()<>「」]+", "", residual)
    return not residual


def suggested_link_url(raw: Any) -> str:
    """小模型给的链接 → 干净的 URL：从 http(s) 开头截到第一个空白 / 全角括号 / 中文字符 / 中文标点为止
    （和 adapter.URL_RE 同一把尺子），再去掉句末的半角标点。不是 http(s) 开头就返回空串。"""
    from .adapter import URL_RE

    m = URL_RE.match(str(raw or "").strip())
    return m.group(0).rstrip(_URL_TAIL) if m else ""


def source_open_url(note: dict[str, Any], meta: dict[str, Any]) -> str | None:
    """给人点的原文链接。

    光有 `canonical_url`（`/explore/<id>`）现在**会 404**——小红书要求带 `xsec_token`
    （2026-09-05 Owner 实机报的）。所以显示用的链接把抓取时那个 token 带上；
    `canonical_url` 仍然只当去重键用（硬约束 7），不动它。
    """
    canonical = meta.get("canonical_url") or note.get("canonical_url")
    if not canonical:
        return None
    token = note.get("xsec_token")
    if not token:
        # 老对象的 source.json 可能没存 token，从当初那条 input_url 里捞
        raw_input = meta.get("input_url") or ""
        match = re.search(r"[?&]xsec_token=([^&\s]+)", raw_input)
        token = match.group(1) if match else None
    if not token:
        return canonical
    return f"{canonical}?xsec_token={token}&xsec_source=pc_feed"

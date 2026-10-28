"""1028 审查第一批（同步 / 登录状态 / 补评论）的回归测试。每一项对应 REVIEW-1028 的一条：

- A7 夜跑让路只看 nightly.STEPS 里 Step.account（不碰号的步骤不让）。
"""
from __future__ import annotations

from link_brain import nightly
from link_brain.sources.xiaohongshu import comment_fill as cf


RUNNING = [{"state": "Running", "next": ""}]


def test_nightly_yield_follows_step_account_flag():
    """nightly.STEPS 每一步：碰号的让路、不碰号的不让；名单里没有的照旧让（宁可多等）。"""
    for step in nightly.STEPS:
        why = cf.nightly_busy(rows=RUNNING, step=step.name)
        if step.account:
            assert why, f"{step.name} 碰号，补评论该让路"
        else:
            assert why == "", f"{step.name} 不碰号，补评论不该让路"
    # 以前的名单漏掉的两步（1028 审查 A7）：游客段附件补查 150 分钟、索引补课 30 分钟，都不碰号
    assert cf.nightly_busy(rows=RUNNING, step="attachments --recheck --guest-only") == ""
    assert cf.nightly_busy(rows=RUNNING, step="index catch-up") == ""
    assert cf.step_touches_account("attachments --recheck --guest-only") is False
    assert cf.step_touches_account("sync-favorites") is True
    # 认不出的步骤（含快照同步这种临时 Step）照旧让路
    assert cf.step_touches_account("") is None and cf.step_touches_account("没有这一步") is None
    assert cf.nightly_busy(rows=RUNNING, step="sync-favorites --from-snapshot") != ""
    assert cf.nightly_busy(rows=RUNNING, step="") != ""

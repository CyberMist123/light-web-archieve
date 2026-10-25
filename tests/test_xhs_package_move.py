"""第二波 PR③：小红书 9 个文件搬进 link_brain/sources/xiaohongshu/，旧路径留 sys.modules 别名。"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from link_brain import storage

ROOT = Path(__file__).resolve().parents[1]
MOVED = {
    "link_brain.accounts": "link_brain.sources.xiaohongshu.accounts",
    "link_brain.favorites": "link_brain.sources.xiaohongshu.favorites",
    "link_brain.fav_counts": "link_brain.sources.xiaohongshu.fav_counts",
    "link_brain.comment_fill": "link_brain.sources.xiaohongshu.comment_fill",
    "link_brain.restricted": "link_brain.sources.xiaohongshu.restricted",
    "link_brain.albums": "link_brain.sources.xiaohongshu.albums",
    "link_brain.night_captcha": "link_brain.sources.xiaohongshu.night_captcha",
    "link_brain.reader_install": "link_brain.sources.xiaohongshu.reader_install",
    "link_brain.adapters.xiaohongshu": "link_brain.sources.xiaohongshu.adapter",
}


@pytest.mark.parametrize("old,new", list(MOVED.items()))
def test_old_paths_are_aliases(old, new, monkeypatch):
    """旧路径和新路径是同一个模块对象：测试 monkeypatch 旧路径，真代码（新路径）看得到（import * 会悄悄假绿）。"""
    o, n = importlib.import_module(old), importlib.import_module(new)
    assert o is n
    pkg, _, attr = old.rpartition(".")
    assert getattr(importlib.import_module(pkg), attr) is n
    monkeypatch.setattr(f"{old}.__pr3_probe__", 1, raising=False)
    assert getattr(n, "__pr3_probe__") == 1


def test_old_path_files_are_only_forwarders():
    for old, new in MOVED.items():
        text = (ROOT / (old.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        assert "sys.modules[__name__] = _real" in text and new.rsplit(".", 1)[1] in text
        assert len([ln for ln in text.splitlines() if ln.strip() and not ln.startswith(("#", '"""'))]) < 12


def test_comment_fill_worker_cwd_is_repo_root(monkeypatch):
    """后台补评论 worker 用 `-m link_brain` 起：cwd 必须是仓库根（没装成包的机器上靠 cwd 找到 link_brain）。
    搬家后若还按 comment_fill 的 __file__ 推，cwd 会落到 link_brain/sources。"""
    from link_brain import comment_fill, deps, procs
    seen = {}
    monkeypatch.setattr(comment_fill, "read_status", lambda: {})
    monkeypatch.setattr(deps, "python_exe", lambda: "python")
    monkeypatch.setattr(procs, "spawn_detached", lambda argv, cwd, env, log_path: seen.update(cwd=cwd) or 4242)
    out = comment_fill.spawn_worker()
    assert out["started"] is True
    assert Path(seen["cwd"]).resolve() == ROOT == storage.repo_root()
    assert (Path(seen["cwd"]) / "link_brain" / "__main__.py").is_file()


def test_account_guard_checks_program_root(monkeypatch, tmp_path):
    """碰号闸认的「这份代码在哪」= 仓库根，不是 link_brain/sources/xiaohongshu 的上一层。"""
    import json
    from link_brain import accounts
    monkeypatch.setattr(accounts, "home", lambda: tmp_path)
    (tmp_path / accounts.GUARD_FILE).write_text(json.dumps({"allowed_roots": [str(ROOT / "link_brain" / "sources")]}), "utf-8")
    with pytest.raises(accounts.ReaderError):
        accounts._account_guard()

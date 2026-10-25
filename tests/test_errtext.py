import collections
import pathlib
import re

from link_brain.errtext import errtext

# 1024：守卫放宽到所有拿类名拼文字的写法（`type(…).__name__`、`….__class__.__name__`），不只认一种 f-string。
# 真不是拼错误文字的（比如报「参数类型不对」）行尾写 `# errtext-ok`。
PAT = re.compile(r"type\(.*?\)\.__name__|\.__class__\.__name__")
ROOT = pathlib.Path(__file__).resolve().parents[1] / "link_brain"

# 基线白名单（1024 盘点，共 122 处）：只许减不许增。改到哪个文件顺手换成 errtext，再把这里的数改小 / 删掉。
BASELINE = {
    "accounts.py": 1,
    "adapters/xiaohongshu.py": 1,
    "ai_health.py": 3,
    "alert.py": 1,
    "answer_check.py": 9,
    "ask.py": 4,
    "asr.py": 2,
    "attachments.py": 3,
    "catalog.py": 3,
    "catch.py": 3,
    "comment_fill.py": 5,
    "docconv.py": 3,
    "enrich.py": 1,
    "export_bundle.py": 1,
    "favorites.py": 3,
    "indextree.py": 4,
    "ingest.py": 4,
    "mcp_tools.py": 2,
    "nightly.py": 11,
    "note.py": 2,
    "pdftext.py": 1,
    "pickfolder.py": 1,
    "procs.py": 2,
    "providers.py": 2,
    "reader_install.py": 2,
    "recall_core.py": 1,
    "recall_table.py": 1,
    "remote/cli.py": 1,
    "remote/config.py": 1,
    "remote/server.py": 1,
    "remove.py": 2,
    "render.py": 2,
    "rerank.py": 1,
    "restore.py": 1,
    "screentext.py": 1,
    "semantic.py": 1,
    "setup/common.py": 2,
    "setup/components.py": 2,
    "setup/fetch.py": 4,
    "setup/pipeline.py": 1,
    "synclog.py": 10,
    "topics.py": 1,
    "usage.py": 2,
    "videos.py": 3,
    "vision.py": 3,
    "visual.py": 4,
}


def _counts(root: pathlib.Path = ROOT) -> dict[str, int]:
    out: collections.Counter = collections.Counter()
    for p in root.rglob("*.py"):
        if p.name == "errtext.py":
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "errtext-ok" not in line:
                out[p.relative_to(root).as_posix()] += len(PAT.findall(line))
    return {k: v for k, v in out.items() if v}


def test_errtext_unwraps_groups():
    g = ExceptionGroup("outer", [KeyError("noteCard"), ExceptionGroup("in", [TimeoutError("slow")])])
    s = errtext(g)
    assert "TaskGroup" not in s and "outer" not in s
    assert "KeyError: 'noteCard'" in s and "TimeoutError: slow" in s
    assert errtext(ValueError("x")) == "ValueError: x"


def test_no_new_handwritten_exception_text():
    grown = {f: (n, BASELINE.get(f, 0)) for f, n in _counts().items() if n > BASELINE.get(f, 0)}
    assert not grown, f"异常转文字请用 link_brain.errtext.errtext（文件: (现在, 基线)）：{grown}"


def test_guard_catches_every_spelling(tmp_path):
    (tmp_path / "a.py").write_text(
        'x = f"{type(exc).__name__}: {exc}"\n'
        'y = "出错：" + type(e).__name__\n'
        'z = f"（{type(err).__name__}）{err}"\n'
        'w = exc.__class__.__name__\n'
        'ok = type(v).__name__  # errtext-ok\n', encoding="utf-8")
    assert _counts(tmp_path) == {"a.py": 4}


def test_baseline_only_shrinks():
    """基线里的数比现状多 = 已经改掉了，顺手把基线改小（不然以后又能悄悄加回来）。"""
    now = _counts()
    stale = {f: (now.get(f, 0), n) for f, n in BASELINE.items() if now.get(f, 0) < n}
    assert not stale, f"这些文件已经少了，把 BASELINE 改小（文件: (现在, 基线)）：{stale}"

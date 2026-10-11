import pathlib
import re

from link_brain.errtext import errtext

PAT = re.compile(r'f"\{type\(exc\)\.__name__\}: \{exc\}"')


def test_errtext_unwraps_groups():
    g = ExceptionGroup("outer", [KeyError("noteCard"), ExceptionGroup("in", [TimeoutError("slow")])])
    s = errtext(g)
    assert "TaskGroup" not in s and "outer" not in s
    assert "KeyError: 'noteCard'" in s and "TimeoutError: slow" in s
    assert errtext(ValueError("x")) == "ValueError: x"


def test_no_handwritten_exception_text():
    root = pathlib.Path(__file__).resolve().parents[1] / "link_brain"
    bad = [str(p) for p in root.rglob("*.py") if p.name != "errtext.py" and any(PAT.search(l) and "errtext-ok" not in l for l in p.read_text(encoding="utf-8").splitlines())]
    assert not bad, f"异常转文字请用 link_brain.errtext.errtext：{bad}"

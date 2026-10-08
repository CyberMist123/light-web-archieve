"""笔记页夹具（tests/fixtures/note-page/*.html）必须就是当前 render 的输出：改了渲染就跑 python tests/tools/note_fixture.py 重写。"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("note_fixture", ROOT / "tests" / "tools" / "note_fixture.py")
note_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(note_fixture)


def test_note_fixture_golden():
    for case in note_fixture.CASES:
        want = (note_fixture.OUT / f"{case}.html").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert note_fixture.build(case) == want, f"{case}.html 过期了：python tests/tools/note_fixture.py"

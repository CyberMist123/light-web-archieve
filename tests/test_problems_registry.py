"""登记制（CONVENTIONS §3.1）：代码里 `problems.report(` 的字面码 ↔ problems.STATE_REGISTRY 双向对齐。

- 正向：仓里任何 `problems.report(step, "<码>", …)` / `report(…, "<码>", …)` 的字面码，必须在登记表里**精确**登记
  （`类.*` 兜底只管显示，不算登记）——新故障码不登记，这条就不过。
- 反向：登记表里每个精确码，要么代码里有人报它，要么列在 problems.PLANNED_CODES（§2.3 首批，第 4 批接调用点）
  或是现有裸码（problems.BARE_CLASS）——没人会产生的码不许挂在表里。
- 一致性：每行的类和分组 / 显示位置对得上（NEEDS_HUMAN 一律 top+card；SKIPPED 一律 none）。
"""

from __future__ import annotations

import re
from pathlib import Path

from link_brain import problems

ROOT = Path(__file__).resolve().parents[1] / "link_brain"
# problems.report("step", "CODE"…) / report(step, 'CODE'…)：取第二个位置参数里的字面码
REPORT_CALL = re.compile(r"""\breport\(\s*[^,()]+,\s*(['"])([A-Z_]+(?:\.[A-Z0-9_]+)?)\1""")
CLI_CALL = re.compile(r"""problems\s+report\b[^\n]*?--code\s+([A-Z_]+\.[A-Z0-9_]+)""")
WHERE = {"top+card", "card", "list", "none"}
GROUPS = {"needs_you", "auto", "gave_up", "off"}


def literal_codes() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for f in ROOT.rglob("*.py"):
        text = f.read_text("utf-8", errors="replace")
        for m in REPORT_CALL.finditer(text):
            found.setdefault(problems.normalize(m.group(2)), []).append(f.name)
    for f in list(ROOT.rglob("*.js")) + list((ROOT.parent / "obsidian-plugins").rglob("*.js")) + list((ROOT.parent / "scripts").rglob("*")):
        if f.is_file():
            for m in CLI_CALL.finditer(f.read_text("utf-8", errors="replace")):
                found.setdefault(problems.normalize(m.group(1)), []).append(f.name)
    return found


def exact_entries() -> set[str]:
    return {k for k in problems.STATE_REGISTRY if not k.endswith(".*")}


def test_every_reported_literal_code_is_registered():
    missing = {code: where for code, where in literal_codes().items() if code not in exact_entries()}
    assert missing == {}, f"这些码在代码里报了，但没在 problems.STATE_REGISTRY 精确登记：{missing}"


def test_every_registered_code_is_produced_or_planned():
    produced = set(literal_codes())
    bare = {problems.normalize(c) for c in problems.BARE_CLASS}
    orphans = exact_entries() - produced - set(problems.PLANNED_CODES) - bare
    assert orphans == set(), f"登记表里有没人会产生的码：{sorted(orphans)}"


def test_planned_and_bare_codes_are_all_registered():
    for code in problems.PLANNED_CODES:
        assert code in exact_entries(), code
    for bare in problems.BARE_CLASS:
        assert problems.normalize(bare) in exact_entries(), bare


def test_registry_rows_are_consistent_with_their_class():
    for key, row in problems.STATE_REGISTRY.items():
        cls = key.split(".", 1)[0]
        assert cls in problems.CLASSES, key
        assert set(row) == {"where", "label", "hover", "group"}, key
        assert row["where"] in WHERE and row["group"] in GROUPS, key
        assert row["group"] == problems.GROUP_OF_CLASS[cls], key
        assert row["label"] and row["hover"], key
        if cls == "NEEDS_HUMAN":
            assert row["where"] == "top+card", key
        if cls == "SKIPPED":
            assert row["where"] == "none", key
        if not key.endswith(".*"):
            assert problems.normalize(key) == key, key
    for cls in problems.CLASSES:
        if cls != "NEEDS_HUMAN":
            assert f"{cls}.*" in problems.STATE_REGISTRY, f"{cls} 缺兜底行"


def test_the_scanner_actually_sees_report_calls(tmp_path, monkeypatch):
    """扫描器自己别是摆设：造一个带 report 调用的模块，未登记的码要被抓出来。"""
    pkg = tmp_path / "link_brain"
    pkg.mkdir()
    (pkg / "x.py").write_text('problems.report("embed", "PERMANENT.BRAND_NEW", "r")\n'
                              "report('ask', 'SKIPPED.FALLBACK', '退回')\n", "utf-8")
    monkeypatch.setattr(__import__(__name__), "ROOT", pkg)
    codes = literal_codes()
    assert set(codes) == {"PERMANENT.BRAND_NEW", "SKIPPED.FALLBACK"}
    assert "PERMANENT.BRAND_NEW" not in exact_entries()


def test_registry_is_json_ready_for_pages():
    import json
    data = problems.registry_for_js()
    assert json.loads(json.dumps(data, ensure_ascii=False)) == data

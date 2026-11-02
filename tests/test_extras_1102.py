"""1102 依赖拆分：extras.py 解析包元数据 / 后备表、按 Python 版本算环境标记、展开自引用的 full / dev；
缺功能包时 setup check / doctor / B 站 / PDF·Word 的提示都是「要用 X，先装 `uv pip install link-brain[xxx]`」。"""
from __future__ import annotations

import sys
from importlib import metadata

import pytest

from link_brain import doctor, docconv, extras
from link_brain.setup import components


META = [
    'mcp<2,>=1.27', 'httpx>=0.27', 'jieba>=0.42.1',
    'rapidocr>=3.10; extra == "ocr"',
    'onnxruntime>=1.17; python_version < "3.13" and extra == "ocr"',
    'onnxruntime>=1.20; python_version == "3.13" and extra == "ocr"',
    'onnxruntime>=1.24.1; extra == "ocr" and python_version >= "3.14"',   # extra 写在前面也认
    'yt-dlp>=2025.1; extra == "bilibili"',
    'pypdfium2>=4.30; extra == "docs"', 'python-docx>=1.1; extra == "docs"',
    'link-brain[bilibili,docs,ocr]; extra == "full"',
    'link-brain[full]; extra == "dev"', 'pytest>=8.0; extra == "dev"',
]


@pytest.fixture
def fake_meta(monkeypatch):
    monkeypatch.setattr(metadata, "requires", lambda dist: list(META) if dist == extras.DIST else None)


def test_requirements_by_extra_and_python_version(fake_meta):
    assert extras.raw_requirements()[1] == "metadata"
    assert extras.requirements("") == ["mcp<2,>=1.27", "httpx>=0.27", "jieba>=0.42.1"]
    assert extras.requirements("ocr", version=(3, 11)) == ["rapidocr>=3.10", "onnxruntime>=1.17"]
    assert extras.requirements("ocr", version=(3, 12)) == ["rapidocr>=3.10", "onnxruntime>=1.17"]
    assert extras.requirements("ocr", version=(3, 13)) == ["rapidocr>=3.10", "onnxruntime>=1.20"]
    assert extras.requirements("ocr", version=(3, 14)) == ["rapidocr>=3.10", "onnxruntime>=1.24.1"]
    assert extras.requirements("ocr", version=(3, 15)) == ["rapidocr>=3.10", "onnxruntime>=1.24.1"]
    # full / dev 是自引用，展开成真包；dev 还多 pytest
    assert extras.requirements("full", version=(3, 13)) == ["yt-dlp>=2025.1", "pypdfium2>=4.30", "python-docx>=1.1",
                                                           "rapidocr>=3.10", "onnxruntime>=1.20"]
    assert extras.requirements("dev", version=(3, 13))[-1] == "pytest>=8.0"
    assert extras.dist_names("", "ocr", version=(3, 13)) == ["mcp", "httpx", "jieba", "rapidocr", "onnxruntime"]
    assert extras.spec_map("ocr")["onnxruntime"] == extras.requirements("ocr")[-1]


def test_fallback_when_not_installed(monkeypatch):
    def boom(dist):
        raise metadata.PackageNotFoundError(dist)
    monkeypatch.setattr(metadata, "requires", boom)
    table, source = extras.raw_requirements()
    assert source == "fallback" and table[""] == list(extras.FALLBACK[""])
    assert "yt-dlp>=2025.1" in extras.requirements("bilibili")


def test_marker_evaluation_is_narrow_and_fail_open():
    assert extras.marker_applies('python_version < "3.13"', (3, 12)) and not extras.marker_applies('python_version < "3.13"', (3, 13))
    assert extras.marker_applies('python_version >= "3.14"', (3, 14)) and not extras.marker_applies('python_version != "3.13"', (3, 13))
    assert extras.marker_applies('sys_platform == "win32"', (3, 13)), "看不懂的标记当成立（宁可多装，不漏装）"
    assert extras.marker_applies("", (3, 13))


def test_import_names_and_hint_text():
    assert extras.import_name("python-docx") == "docx" and extras.import_name("yt-dlp") == "yt_dlp"
    assert extras.import_name("PyYAML") == "yaml" and extras.import_name("Pillow") == "PIL"
    assert extras.import_name("onnxruntime") == "onnxruntime"
    assert extras.install_hint("bilibili") == "uv pip install link-brain[bilibili]"
    assert extras.install_hint() == "uv pip install link-brain"
    assert extras.missing_text("bilibili") == "要用 B 站下载，先装 `uv pip install link-brain[bilibili]`"
    assert extras.missing_text("ocr") == "要用本地 OCR，先装 `uv pip install link-brain[ocr]`"
    assert extras.missing_text("docs", "PDF 附件转文字") == "要用 PDF 附件转文字，先装 `uv pip install link-brain[docs]`"
    # 不和本包任何模块扯上关系（doctor 缺依赖时也要能 import；也别把它卷进 import 环）
    src = open(extras.__file__, encoding="utf-8").read()
    assert "from . import" not in src and "from link_brain" not in src and "import link_brain" not in src


# ------------------------------------------------------------------ setup check 的口径：core 不再被功能包拖住

def _no(monkeypatch, *modules):
    real = components._has
    monkeypatch.setattr(components, "_has", lambda m: False if m in modules else real(m))


def test_core_ready_without_optional_extras(monkeypatch):
    """装了核心、没装 B 站 / PDF·Word / OCR：core 是 ready（以前 CORE_REQS 把 pypdfium2 / docx / mcp 混进来）。"""
    _no(monkeypatch, "yt_dlp", "pypdfium2", "docx", "rapidocr", "onnxruntime")
    out = components.check(["core", "ocr"])
    by = {r["item_id"]: r for r in out["results"]}
    assert by["core"]["status"] == "ready", by["core"]
    assert by["ocr"]["status"] == "missing" and by["ocr"]["fix"] == "auto"
    assert "uv pip install link-brain[ocr]" in by["ocr"]["fix_hint"]


def test_core_partial_lists_missing_core_dep(monkeypatch):
    _no(monkeypatch, "jieba", "qrcode")
    row = components.check(["core"])["results"][0]
    assert row["status"] == "partial" and "jieba" in row["detail"] and "qrcode" in row["detail"]
    # 补装用的说明就是 pyproject 那一条
    assert components.CORE_SPECS["jieba"] == "jieba>=0.42.1"


def test_core_install_specs_follow_pyproject(monkeypatch):
    _no(monkeypatch, "qrcode")
    seen = {}
    monkeypatch.setattr(components, "_pip_install", lambda component, specs, emit: seen.update(specs=specs))
    out = components._install_core(None)
    assert seen["specs"] == ["qrcode>=7.0"] and out["changed"] is True


# ------------------------------------------------------------------ doctor：核心缺了判红，功能包没装单列

def test_doctor_separates_core_missing_from_optional_extras(monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    info = doctor.python_checks()
    by = {d["name"]: d for d in info["deps"]}
    assert by["yt-dlp"]["ok"] is False and by["yt-dlp"]["extra"] == "bilibili" and by["httpx"]["extra"] == ""
    assert "yt-dlp" not in info["missing"] and "bilibili" in info["missing_extras"] and "docs" in info["missing_extras"]
    row = doctor._python_row(doctor._plain_row, info)
    if not info["missing"] and not info.get("scheduled_error"):
        assert row["state"] == "ready", "功能包没装不把 Python 那一行判红"
    assert "bilibili（B 站下载，缺 yt-dlp）" in row["message"] and "uv pip install link-brain[bilibili]" in row["next_step"]


def test_doctor_core_missing_hint_is_the_package_itself(monkeypatch):
    monkeypatch.setitem(sys.modules, "jieba", None)
    info = doctor.python_checks()
    row = doctor._python_row(doctor._plain_row, info)
    assert row["state"] == "error" and "缺 jieba" in row["message"] and "uv pip install link-brain" in row["next_step"]


# ------------------------------------------------------------------ PDF / Word：缺 docs 功能包在撞见那一步说一句

def test_docconv_missing_docs_extra_says_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    monkeypatch.setitem(sys.modules, "docx", None)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = docconv.pdf_to_markdown(pdf)
    assert out["status"] == "failed" and out["code"] == "NEEDS_HUMAN.MISSING_DEPENDENCY"
    assert out["error"] == "要用 PDF 附件转文字，先装 `uv pip install link-brain[docs]`"
    doc = tmp_path / "b.docx"
    doc.write_bytes(b"PK fake")
    out = docconv.docx_to_markdown(doc)
    assert out["code"] == "NEEDS_HUMAN.MISSING_DEPENDENCY" and out["error"] == "要用 Word 附件转文字，先装 `uv pip install link-brain[docs]`"

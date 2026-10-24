"""唯一数据来源守卫（ARCH-AUDIT 第 0 批）。

每条规则 = 一类数据的定义 / 读法只许出现在 allowed 里。known 是排查时（1023）就已存在的重复，
按 ARCH-AUDIT 的批次逐个迁走；迁走一处就从 known 删一处（不删也会红，防止白名单烂掉）。
新代码在别处再写一份 → 红。扫的是源码文本，整行注释（# / //）不算。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY_GLOBS = ("link_brain/**/*.py", "link_brain/assets/*.yaml")
JS_GLOBS = ("link_brain/assets/*.js", "obsidian-plugins/**/*.js")

# name: (globs, 正则, allowed, known, 迁移批次)
RULES = {
    "价格表": (
        PY_GLOBS,
        r"^\s*PRICES\s*=|[\"']pricing\.json[\"']|^pricing:",
        {"link_brain/setup/estimate.py"},
        {"link_brain/visual.py", "link_brain/keyprobe.py", "link_brain/assets/llm-config.yaml"},
        2,
    ),
    "收藏判断": (
        PY_GLOBS,
        r"ingest_kind[\"']?\)?\s*==?\s*[\"']favorite|\.get\([\"']favorited_by[\"']\)",
        {"link_brain/provenance.py", "link_brain/favorites.py"},
        {"link_brain/catalog.py", "link_brain/fav_counts.py", "link_brain/synclog.py"},
        3,
    ),
    "账号字段": (
        PY_GLOBS,
        r"config\(\)\.get\([\"'](sync_account|nickname|user_id)[\"']",
        {"link_brain/accounts.py"},
        {"link_brain/favorites.py"},
        3,
    ),
    "Gemini 密钥来源": (
        PY_GLOBS,
        r"LWA_GEMINI_KEYS|gemini_keys_(file|cmd)",
        {"link_brain/providers.py", "link_brain/storage.py"},
        {"link_brain/nightly.py", "link_brain/vision.py", "link_brain/ai_config.py"},
        2,
    ),
    "写死的模型名": (
        PY_GLOBS,
        r"[\"'](qwen[0-9][\w.-]*|qwen3-[\w.-]+|gemini-[0-9][\w.-]*|deepseek-[\w.-]+|gpt-4o[\w.-]*"
        r"|text-embedding-[\w.-]+|whisper-1)[\"']",
        {"link_brain/ai_config.py"},
        {"link_brain/asr.py", "link_brain/keyprobe.py", "link_brain/rerank.py", "link_brain/semantic.py",
         "link_brain/setup/capswriter.py", "link_brain/vision.py", "link_brain/visual.py"},
        2,
    ),
    "页面标题兜底 Collections": (
        JS_GLOBS,
        r"[\"']Collections[\"']",
        {"link_brain/assets/lb-page-lib.js"},
        {"link_brain/assets/catalog-view.js", "link_brain/assets/chat-view.js",
         "obsidian-plugins/link-brain-actions/main.js"},
        4,
    ),
    "问题分组表抄本": (
        JS_GLOBS,
        r"GROUP_OF_CLASS\s*=",
        set(),
        {"obsidian-plugins/link-brain-actions/problems-ui.js"},
        4,
    ),
    "供应商猜测": (
        JS_GLOBS,
        r"function providerOf|providerOf\s*=",
        set(),
        {"obsidian-plugins/link-brain-actions/settings-pages.js"},
        2,
    ),
    "前端预算默认值": (
        JS_GLOBS,
        r"(dailyYuan|daily_yuan)[^\n]*\?\?\s*3\b",
        set(),
        {"obsidian-plugins/link-brain-actions/settings-pages.js",
         "obsidian-plugins/link-brain-actions/settings-v6.js"},
        2,
    ),
    "默认回答提示词": (
        JS_GLOBS,
        r"DEFAULT_ANSWER_PROMPT\s*=",
        set(),
        {"obsidian-plugins/link-brain-actions/main.js"},
        4,
    ),
    "CLI 命令抄本": (
        JS_GLOBS,
        r"claude -p --model",
        set(),
        {"obsidian-plugins/link-brain-actions/main.js"},
        2,
    ),
}


def _code_lines(path: Path):
    for line in path.read_text("utf-8", errors="replace").splitlines():
        s = line.lstrip()
        if s.startswith("#") or s.startswith("//"):
            continue
        yield line


def _hits(globs, pattern) -> set[str]:
    rx = re.compile(pattern)
    found = set()
    for g in globs:
        for p in ROOT.glob(g):
            if "node_modules" in p.parts:
                continue
            if any(rx.search(line) for line in _code_lines(p)):
                found.add(p.relative_to(ROOT).as_posix())
    return found


@pytest.mark.parametrize("name", list(RULES))
def test_single_source(name):
    globs, pattern, allowed, known, batch = RULES[name]
    found = _hits(globs, pattern)
    new = found - allowed - known
    assert not new, (f"「{name}」出现新的重复定义：{sorted(new)}。只许在 {sorted(allowed) or '（后端统一来源）'}；"
                     f"见 docs/ARCH-AUDIT.md 第 {batch} 批")
    gone = known - found
    assert not gone, f"「{name}」这些已经迁走了，从 known 白名单删掉：{sorted(gone)}"

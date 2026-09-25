"""OCR 文本整理（2026-09-26）。

vision.json 里的 OCR 原文保持不动（含「(OCR 行数 N，均信心 X)」统计行，排查识别错误时用）。
给人看、给检索用的版本在这里整理：
- clean_ocr：去掉统计行和「没认出文字」占位，保留按行格式（检索与原文定位按行找）。
- reflow_ocr：显示用，一行不以句末标点结尾、下一行也不是列表项，就接回一句。
"""
from __future__ import annotations

import re

_STAT_LINE = re.compile(r"^\(OCR 行数 \d+，均信心 [\d.]+\)$")
_EMPTY_MARK = "[OCR 没认出文字]"
_SENTENCE_END = tuple("。！？!?；;：:…」』）)】\"'")
_LIST_START = re.compile(r"^(\d+[.、)）]|[-•·●○■□▪◆◇*]|[（(]?[一二三四五六七八九十]+[、.）)])")


def clean_ocr(text: str | None) -> str:
    lines = [line for line in (text or "").splitlines()
             if line.strip() and not _STAT_LINE.match(line.strip()) and line.strip() != _EMPTY_MARK]
    return "\n".join(lines)


def reflow_ocr(text: str | None) -> str:
    """只接「被图片宽度折断」的行，别把标题、列表、短句堆成一坨（Owner 0926）。

    判据：上一行接近这张图里最长的行（≥ 80%，说明是写满才折的）、不以句末标点结尾、
    不是列表项，且本行也不是列表项。标题/列表/短句都短，达不到长度门槛，保持原样换行。
    """
    lines = [line.strip() for line in clean_ocr(text).splitlines()]
    if not lines:
        return ""
    width = max(len(line) for line in lines)
    threshold = max(8, int(width * 0.8))
    out: list[str] = []
    wrapped = False  # 上一行是否是「写满折断」的续行候选
    for line in lines:
        if out and wrapped and not _LIST_START.match(line):
            prev = out[-1]
            ascii_join = prev[-1:].isascii() and prev[-1:].isalnum() and line[:1].isascii() and line[:1].isalnum()
            out[-1] = prev + (" " if ascii_join else "") + line
        else:
            out.append(line)
        wrapped = len(line) >= threshold and not line.endswith(_SENTENCE_END) and not _LIST_START.match(line)
    return "\n".join(out)

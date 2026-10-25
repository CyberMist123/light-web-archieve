"""ocrtext 的补充用例（现有 test_ocrtext.py 已盖统计行 / 占位行 / 基本接行 / 英文加空格）。

只断言 link_brain/ocrtext.py 里能直接读出的行为：clean_ocr 按行过滤、reflow_ocr 的
「上一行写满折断才接、句末标点 / 列表项都停」判据。
"""

from link_brain.ocrtext import clean_ocr, reflow_ocr


def test_clean_none_empty_and_blank_lines():
    assert clean_ocr(None) == ""
    assert clean_ocr("") == ""
    assert clean_ocr(" \n　\n\t\n") == ""                      # 全空白（含全角空格）= 空
    assert clean_ocr("第一行\n   \n第二行") == "第一行\n第二行"   # 夹在中间的空白行去掉


def test_clean_keeps_mixed_cjk_ascii_lines():
    text = "Caffeine 95mg\n拿铁 12 元\n(OCR 行数 2，均信心 0.98)"
    assert clean_ocr(text) == "Caffeine 95mg\n拿铁 12 元"


def test_reflow_none_and_all_filtered():
    assert reflow_ocr(None) == ""
    assert reflow_ocr("[OCR 没认出文字]\n(OCR 行数 0，均信心 0.00)") == ""


def test_reflow_stops_at_sentence_end():
    # 第一行以句末标点结尾 = 不是折断，第二行不接
    text = "第一行写得很长很长很长很长很长很长。\n第二行短句"
    assert reflow_ocr(text) == "第一行写得很长很长很长很长很长很长。\n第二行短句"


def test_reflow_never_joins_list_items():
    # 列表项自己再长也不是折断的续行候选；列表项也不接到上一行后面
    text = "1. 这一条列表项写得很长很长很长很长很长\n· 要点"
    assert reflow_ocr(text).splitlines() == ["1. 这一条列表项写得很长很长很长很长很长", "· 要点"]


def test_reflow_joins_cjk_directly_and_after_cjk_no_space():
    # 两行都写满、都无句末标点：中文相接不加空格（前一行以汉字结尾、本行以字母开头也不加）
    text = "本行写满折断的第一段内容结尾是英文版\nR2D2 是第二段继续写满折断的内容"
    out = reflow_ocr(text)
    assert "\n" not in out and "版R2D2" in out

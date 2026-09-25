from link_brain.ocrtext import clean_ocr, reflow_ocr

SAMPLE = """标题：怎么做
这是一段很长很长的正文被图片的宽度折断
了，需要接回来才能读顺。
1. 列表项
2. 第二项
短句
hello
world
(OCR 行数 9，均信心 0.93)"""


def test_clean_drops_stats_and_empty_marker_but_keeps_lines():
    assert "均信心" not in clean_ocr(SAMPLE)
    assert clean_ocr(SAMPLE).count("\n") == 7  # 按行保留，供检索与原文定位
    assert clean_ocr("[OCR 没认出文字]\n(OCR 行数 0，均信心 0.00)") == ""


def test_reflow_joins_only_wrapped_lines():
    assert reflow_ocr(SAMPLE).splitlines() == [
        "标题：怎么做",
        "这是一段很长很长的正文被图片的宽度折断了，需要接回来才能读顺。",
        "1. 列表项",
        "2. 第二项",
        "短句",
        "hello",
        "world",
    ]


def test_reflow_keeps_space_between_wrapped_english_words():
    text = "This is a long English sentence that wraps\nat the edge of the picture."
    assert reflow_ocr(text) == "This is a long English sentence that wraps at the edge of the picture."

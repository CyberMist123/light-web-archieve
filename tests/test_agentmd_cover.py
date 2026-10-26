"""r5 补测：机读版拼装的纯函数层（norm/cut/junk_line/句子截断/水印/OCR 行/存疑原因），全离线。"""
from __future__ import annotations

from link_brain import agentmd as a


def test_norm_and_cut():
    assert a.norm(" 你好，世界！Hello, world? ") == "你好世界Helloworld"
    assert a.norm(None) == "" and a.norm(123) == "123"
    assert a.cut("短", 10) == "短"
    assert a.cut("abcdefghij", 10) == "abcdefghij"  # 恰好等长不动
    assert a.cut("abcdefghijk", 10) == "abcdefghij…"
    assert a.cut("尾随空白   ", 5) == "尾随空白…"  # 截完先 rstrip 再补尾


def test_junk_line_rules():
    assert a.junk_line("买") is True                 # 单字装饰
    assert a.junk_line("ab") is True                 # ≤2 个有效字符且非两字词
    assert a.junk_line("关注") is False              # 两个汉字的词保留
    assert a.junk_line("今天教你做红烧肉") is False
    assert a.junk_line("11001010 0101") is True      # 二进制装饰（去空白后 ≥8 位 01 串）
    assert a.junk_line("123") is True                # 纯数字短行
    assert a.junk_line("1100013100131") is True      # 二进制认错几位的（01 占 3/4 以上）
    assert a.junk_line("2026年10月26日") is False    # 带汉字的正常内容
    assert a.junk_line("   ") is True and a.junk_line("") is True


def test_image_no_and_asset_name():
    assert a.image_no("assets/image-012.jpg") == 12
    assert a.image_no("image-3.webp") == 3
    assert a.image_no("no-match.jpg") is None and a.image_no("") is None and a.image_no(None) is None
    assert a.asset_name("x/y/z.jpg") == "z.jpg"
    assert a.asset_name("z.jpg") == "z.jpg"
    assert a.asset_name(None) == "" and a.asset_name("") == ""


def test_cut_sentences_keeps_whole_sentences():
    assert a.cut_sentences("短", 10) == "短"
    assert a.cut_sentences("第一句。第二句。第三句超长" * 3, 10) == "第一句。第二句。…（略）"
    # 第一句就超限：整句保留，后面截掉并照样加尾注
    assert a.cut_sentences("这一句本身就超过十个字了哦。后面还有。", 10) == "这一句本身就超过十个字了哦。…（略）"


def test_watermarks_need_three_images_and_majority():
    two = [["小红书"], ["小红书"]]
    assert a.watermarks(two) == []  # 不到 3 张不判
    three = [["小红书", "每日分享"], ["小红书"], ["小红书", "这一行超过十二个字所以不参与统计哦"]]
    assert a.watermarks(three) == ["小红书"]  # 3/3 出现、≤12 字、按首次出现顺序
    assert a.watermarks([["甲"], ["乙"], ["丙"]]) == []  # 各出现一次，不到半数


def test_covered_by_exact_or_partial_ratio():
    assert a._covered("", "pool") is True                     # 空片算已覆盖
    assert a._covered("ab", "xxabyy") is True                 # 短片：原样包含才算
    assert a._covered("ab", "xyz") is False                   # 短片不做模糊
    assert a._covered("红烧肉做法", "今天分享红烧肉做法大全") is True   # ≥4 字走 partial_ratio
    assert a._covered("完全不同的内容", "今天分享红烧肉做法大全") is False


def test_ocr_lines_dedup_junk_and_paragraph_gap():
    img = {"lines": [
        {"text": "第一行文字", "box": [0, 0, 200, 20], "score": 0.9},
        {"text": "第一行文字", "box": [0, 30, 200, 50], "score": 0.9},  # norm 重复 → 只留一次
        {"text": "买", "box": [0, 55, 200, 75], "score": 0.9},         # 乱码单字 → 丢
        {"text": "第二行文字", "box": [0, 110, 200, 130], "score": 0.9},  # 竖向空隙 > 1.2×行高中位 → 段落空行
    ]}
    assert a.ocr_lines(img) == ["第一行文字", "", "第二行文字"]
    # 行没有 box：退回 image["ocr"] 文本；没有 ocr 字段就是没行
    assert a.ocr_lines({"lines": [{"text": "没有盒子"}]}) == []
    assert a.ocr_lines({}) == []


def test_ocr_garble_ratio_and_gates():
    assert a.ocr_garble({}) == (0.0, 0)                      # 没有逐行信心的旧结果
    assert a.ocr_garble({"lines": [{"text": "某行"}]}) == (0.0, 0)   # 缺 score 也算旧结果
    ratio, chars = a.ocr_garble({"lines": [
        {"text": "确定认准的一行字", "score": 0.99},
        {"text": "没认准的另一行字", "score": 0.3},   # < 0.65 → 没认准
    ]})
    assert ratio == 0.5 and chars == 16
    # junk 行认得很有把握就不算（机读版里本来就不出现）
    assert a.ocr_garble({"lines": [{"text": "1100013100131", "score": 0.99},
                                   {"text": "认得很准的一行字", "score": 0.99}]}) == (0.0, 8)


def test_doubt_reasons_priority_and_shaky():
    assert a.doubt_reasons({"status": "failed"}) == ["识别失败"]
    assert a.doubt_reasons({"status": "ok", "visual": {"kind": "title"}}) == []  # 标题图不判
    garbled = {"status": "ok", "visual": {"status": "ok", "kind": "image", "text": ""},
               "lines": [{"text": "没认准的字" * 8, "score": 0.3}]}  # 40 个有效字全没认准
    assert a.doubt_reasons(garbled) == ["OCR 大半没认准"]
    handwrite = {"status": "ok", "visual": {"status": "ok", "kind": "image", "text": "图上是手写的字",
                                            "shaky": "有点糊"},
                 "refine": {"status": "failed"},
                 "lines": [{"text": "手写字行" * 8, "score": 0.3}]}  # ≥30 字门槛过了，手写放宽到 0.3
    assert a.doubt_reasons(handwrite) == ["疑似手写", "精细识别没过", "有点糊"]
    assert a.shaky({"status": "ok", "visual": {"kind": "image", "shaky": "有点糊"}}) == "有点糊"
    assert a.shaky({"status": "ok", "visual": {"kind": "image", "text": ""}}) == ""

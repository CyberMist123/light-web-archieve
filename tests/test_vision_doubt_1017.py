"""1017 作者裁决：识图结果不可靠（手写字、乱码、精细识别阶梯全部不合格退回第一层）不是故障、不进问题面板，
改在 vision.json 记存疑、机读版 agent.md 里那张图写一句「识图存疑…以原图为准」。合成数据、假 provider，不联网。"""
from __future__ import annotations

from link_brain import agentmd, cli, problems, render as render_mod, repair, storage, vision, visual

REFINE = "PERMANENT.MODEL_OUTPUT_INVALID"
BAD = {"status": "failed", "error": "出现复读", "code": REFINE, "text": "复读复读"}


def _line(text, score):
    return {"text": text, "box": [0, 0, 10, 10], "score": score}


def _img(lines, visual_text="要点", kind="text", **extra):
    image = {"asset": "raw/v0001/assets/image-003.webp", "status": "ok", "lines": lines,
             "visual": {"kind": kind, "status": "ok", "text": visual_text, "v": visual.VISUAL_VERSION}}
    image.update(extra)
    return image


GOOD = [_line("这是一段认得很清楚的说明文字第一行", 0.98), _line("第二行也认得很清楚没有问题的", 0.97)]
GARBLED = [_line("九国内长染为部内大水", 0.55), _line("海水Ⅱ颗味三一不馆上", 0.52), _line("经一后回条平餐济上鸡内", 0.6),
           _line("清楚的一行字", 0.95)]


# ---------------------------------------------------------------- 判据（纯函数，阈值可测）


def test_clean_image_has_no_doubt():
    assert agentmd.doubt_reasons(_img(GOOD)) == []


def test_ocr_mostly_low_confidence_is_doubt():
    ratio, chars = agentmd.ocr_garble(_img(GARBLED))
    assert chars >= agentmd.DOUBT_MIN_CHARS and ratio >= agentmd.DOUBT_RATIO
    assert agentmd.doubt_reasons(_img(GARBLED)) == ["OCR 大半没认准"]


def test_ocr_ratio_threshold_is_half():
    # 低信心字正好一半 → 存疑；不到一半 → 不标
    half = [_line("一二三四五六七八九十一二三四五", 0.5), _line("甲乙丙丁戊己庚辛壬癸子丑寅卯辰", 0.9)]
    assert agentmd.ocr_garble(_img(half))[0] == 0.5 and agentmd.doubt_reasons(_img(half))
    less = half + [_line("子丑寅卯", 0.9)]
    assert agentmd.ocr_garble(_img(less))[0] < 0.5 and agentmd.doubt_reasons(_img(less)) == []


def test_handwriting_lowers_threshold_and_says_so():
    lines = [_line("一二三四五六七八九十", 0.5), _line("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉", 0.9)]  # 低信心 1/3
    assert agentmd.doubt_reasons(_img(lines)) == []
    assert agentmd.doubt_reasons(_img(lines, visual_text="一页手写笔记，字迹潦草")) == ["疑似手写"]


def test_confident_decorations_do_not_count():
    """二进制装饰串、表盘数字这类 junk_line 认得很有把握的不算「没认准」（机读版里本来就不出现）。"""
    lines = [_line("000110010101101100", 1.0), _line("0100001100001", 0.99), _line("55", 1.0), _line("那你自己靠什么生活呢", 1.0)]
    assert agentmd.doubt_reasons(_img(lines, kind="picture")) == []


def test_too_few_chars_not_judged():
    assert agentmd.doubt_reasons(_img([_line("给你们表演一个吃柠檬", 1.0), _line("51004g2114", 0.59)])) == [],         "一句配文 + 一行糊字（共 20 字 < DOUBT_MIN_CHARS）不标"


def test_unreadable_marks_and_refine_failed():
    marks = "[看不清] 一行 [看不清] 两行 [无法辨认]"
    assert agentmd.doubt_reasons(_img(GOOD, visual_text=marks)) == ["多处看不清"]
    sparse = marks + "很长的一段认得清楚的文字" * 30   # 零星几处、长截图：文字里本来带着标记，不另标
    assert agentmd.doubt_reasons(_img(GOOD, visual_text=sparse)) == []
    failed = _img(GOOD, refine={"status": "failed", "fallback": "layer1", "error": "出现复读"})
    assert agentmd.doubt_reasons(failed) == ["精细识别没过"]
    both = _img(GARBLED, refine={"status": "failed", "fallback": "layer1"})
    assert agentmd.shaky(both) == "OCR 大半没认准，精细识别没过"


def test_refined_ok_and_title_are_trusted():
    assert agentmd.doubt_reasons(_img(GARBLED, refined={"status": "ok", "kind": "text", "text": "强模型认好的字"})) == []
    title = _img(GARBLED, kind="title")
    assert agentmd.doubt_reasons(title) == []


# ---------------------------------------------------------------- vision.json：精细识别放弃 → 记存疑、不登记问题


def _vision_setup(tmp_path, monkeypatch, entry):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    monkeypatch.setattr(render_mod, "render_object", lambda *a, **k: None)
    monkeypatch.setattr(vision, "REFINE_GAP_SECONDS", (0, 0))
    monkeypatch.setattr(vision, "strong_config", lambda: None)
    monkeypatch.setattr(visual, "vision_config", lambda: None)
    vision.mark_refine(entry, "第一层出现复读")
    vpath = storage.derived_dir("xiaohongshu", "abc") / "vision.json"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json(vpath, {"schema_version": 1, "version": 1, "images": [entry]})
    return vpath


def test_ladder_gave_up_marks_doubt_not_problem(tmp_path, monkeypatch):
    vpath = _vision_setup(tmp_path, monkeypatch, _img(GOOD))
    monkeypatch.setattr(visual, "refine", lambda *a, **k: dict(BAD))
    monkeypatch.setattr(vision, "refine_tiles", lambda *a, **k: None)
    tally = vision.refine_object("xiaohongshu", "abc", {"model": "m", "endpoint": "e"})
    img = storage.read_json(vpath)["images"][0]
    assert tally["failed"] == 1 and img["refine"]["status"] == "failed" and img["refine"]["fallback"] == "layer1"
    assert img["doubt"] is True and img["doubt_reason"] == "精细识别没过"
    assert [r for r in problems.load(100, include_resolved=True) if r["step"] == "vision.refine"] == []


def test_request_refused_three_times_marks_doubt_not_problem(tmp_path, monkeypatch):
    vpath = _vision_setup(tmp_path, monkeypatch, _img(GOOD))
    monkeypatch.setattr(visual, "refine", lambda *a, **k: {"status": "failed", "code": REFINE, "http_status": 400,
                                                           "error": "接口不接受这次请求（HTTP 400）"})
    for _ in range(vision.REFINE_TRIES):
        vision.refine_object("xiaohongshu", "abc", {"model": "m"})
    img = storage.read_json(vpath)["images"][0]
    assert img["refine"]["status"] == "failed" and img["refine"]["fallback"] == "layer1" and img["doubt"] is True
    assert problems.load(100, include_resolved=True) == []


def test_api_failure_still_not_counted_and_not_doubt(tmp_path, monkeypatch):
    """接口那一侧（限流 / 断网 / key）照旧：不计次数、留 pending，不标存疑（交给 ai_health，见 run_refine）。"""
    vpath = _vision_setup(tmp_path, monkeypatch, _img(GOOD))
    monkeypatch.setattr(visual, "refine", lambda *a, **k: {"status": "failed", "code": "TRANSIENT.HTTP_429",
                                                           "api_error": True, "error": "限流"})
    tally = vision.refine_object("xiaohongshu", "abc", {"model": "m"})
    img = storage.read_json(vpath)["images"][0]
    assert tally["api_errors"] == 1 and img["refine"]["status"] == "pending" and "doubt" not in img


def test_stamp_doubt_adds_and_removes_fields():
    e = vision.stamp_doubt(_img(GARBLED))
    assert e["doubt"] is True and e["doubt_reason"] == "OCR 大半没认准"
    e["lines"] = GOOD
    vision.stamp_doubt(e)
    assert "doubt" not in e and "doubt_reason" not in e


# ---------------------------------------------------------------- 机读版：一图一句、不占字数限额


def _render(images):
    return render_mod.render_agent_md(source={"note": {"title": "合成标题"}}, vision={"images": images},
                                      meta={"item_id": "xhs-t", "source_id": "t", "current_version": 1}, extracted={})


def test_agent_md_one_line_per_doubtful_image(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    ok = {**_img(GOOD, kind="picture", visual_text="一张说明图"), "asset": "raw/v0001/assets/image-001.webp"}
    bad = _img(GARBLED, kind="picture", visual_text="一页手写笔记", refine={"status": "failed", "fallback": "layer1"})
    text = _render([ok, bad])
    assert text.count("识图存疑") == 1
    assert ("识图存疑（疑似手写，精细识别没过），文字仅供参考，以原图为准。"
            "原图：_archive/xiaohongshu/t/raw/v0001/assets/image-003.webp") in text
    section = text.split("### 第3张", 1)[1]
    assert section.index("图上文字") < section.index("识图存疑")


def test_doubt_line_does_not_eat_image_budget():
    lines = [_line("清" * 50, 0.4)]
    images = [_img(lines, kind="picture", visual_text="", refine={"status": "failed"}) for _ in range(3)]
    for i, im in enumerate(images):
        im["asset"] = f"raw/v0001/assets/image-00{i + 1}.webp"
    origin = lambda a: "_archive/x/" + "很长的路径" * 20 + a  # noqa: E731
    out = agentmd.image_section(images, origin, total=170)
    assert "（略，超出图片字数上限）" not in "\n".join(out), "三张各约 55 字 < 170：存疑那句不算进限额"
    assert sum("识图存疑" in r for r in out) == 3


# ---------------------------------------------------------------- 旧行：读取 / 运行时自动收成已解决


def test_old_rows_resolved_on_panel_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    a = problems.report("vision.refine", REFINE, "image-006.webp：出现复读；…已退回第一层识图结果", item_id="xhs-a")
    b = problems.report("vision.refine", REFINE, "image-002.webp：出现复读", item_id="xhs-b")
    problems.dismiss(key=b["key"])  # 她隐藏过的那几条一样收掉
    problems.report("ai.refine", "TRANSIENT.HTTP_429", "限流")  # 接口那一侧的照旧
    problems.report("vision.refine", "PERMANENT.CONTENT_FILTERED", "审核拦下", item_id="xhs-c")  # 别的码不碰
    assert cli.main(["problems", "list"]) == 0
    capsys.readouterr()
    left = {r["key"] for r in problems.load(100)}
    assert left == {problems.make_key("ai.refine", None, "TRANSIENT.HTTP_429"),
                    problems.make_key("vision.refine", "xhs-c", "PERMANENT.CONTENT_FILTERED")}
    done = {r["key"]: r for r in problems.load(100, include_resolved=True)}
    assert done[a["key"]]["resolved_at"] and done[b["key"]]["resolved_at"]
    assert vision.retire_refine_problems() == 0, "幂等"


def test_repair_plan_says_not_a_fault():
    row = {"key": "vision.refine|xhs-a|MODEL_OUTPUT_INVALID", "step": "vision.refine", "item_id": "xhs-a",
           "code": REFINE, "reason": "r", "ts": "2026-10-08T04:38:23+11:00"}
    p = repair.plan(row)
    assert p["kind"] == "manual" and not p["auto"] and "不是故障" in p["next"]
    step_row = {**row, "item_id": None, "code": "TRANSIENT.SERVICE_BUSY"}
    assert repair.plan(step_row)["action"] == "refine_run"

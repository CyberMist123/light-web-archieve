"""1015：识图 HTTP 400 三篇的根因——百炼内容审核（data_inspection_failed）拦的是附带的 OCR 文字，图本身能过。
请求体（webp data URL、1080x1440、几百 KB）和同篇成功的图一样，不是格式 / 尺寸 / 编码问题。"""
import json

import httpx

from link_brain import problems, providers, visual

FILTER_TEXT = json.dumps({"error": {"code": "data_inspection_failed", "type": "data_inspection_failed",
                                    "message": "Input text data may contain inappropriate content."}})
FILTER_IMAGE = json.dumps({"error": {"code": "data_inspection_failed", "type": "data_inspection_failed",
                                     "message": "Input data may contain inappropriate content."}})
CFG = {"endpoint": "https://example.invalid/compatible-mode/v1/chat/completions", "model": "qwen3.8-flash",
       "apiKey": "test"}
LINES = [{"text": "敏感的一行 OCR 字", "score": 0.9}]


def test_http_code_maps_inspection_failure_to_content_filtered():
    assert providers.http_code(400, FILTER_TEXT) == "PERMANENT.CONTENT_FILTERED"
    got = providers.http_failure(400, FILTER_TEXT)
    assert got["code"] == "PERMANENT.CONTENT_FILTERED" and got["api_error"] is False
    assert got["filtered_input"] == "text"
    assert "检查模型名" not in got["error"] and "审核" in got["error"]
    assert providers.http_failure(400, FILTER_IMAGE)["filtered_input"] == "unknown"
    # 普通 400 照旧
    assert providers.http_code(400, '{"error":{"code":"invalid_parameter"}}') == "PERMANENT.MODEL_OUTPUT_INVALID"


def _img(tmp_path):
    p = tmp_path / "image-002.webp"
    p.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 fake")
    return p


def test_layer1_retries_without_ocr_when_text_is_filtered(monkeypatch, tmp_path):
    prompts = []

    def post(url, **kw):
        body = json.loads(kw["content"])
        prompt = body["messages"][0]["content"][1]["text"]
        prompts.append(prompt)
        assert body["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/webp;base64,")
        if "敏感的一行" in prompt:
            return httpx.Response(400, text=FILTER_TEXT, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "类型：图片\n一张书桌照片"},
                                                      "finish_reason": "stop"}], "usage": {}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    got = visual.understand(_img(tmp_path), LINES, CFG)
    assert got["status"] == "ok" and got["kind"] == "picture"
    assert len(prompts) == 2 and visual.NO_OCR_NOTE in prompts[1] and "敏感的一行" not in prompts[1]


def test_layer1_image_itself_filtered_gives_up_with_clear_code(monkeypatch, tmp_path):
    calls = []

    def post(url, **kw):
        calls.append(1)
        return httpx.Response(400, text=FILTER_IMAGE, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    got = visual.understand(_img(tmp_path), LINES, CFG)
    assert got["status"] == "failed" and got["code"] == "PERMANENT.CONTENT_FILTERED"
    assert len(calls) == 1  # 拦的不是文字：不白烧第二次


def test_refine_also_retries_without_ocr(monkeypatch, tmp_path):
    def post(url, **kw):
        prompt = json.loads(kw["content"])["messages"][0]["content"][1]["text"]
        if "敏感的一行" in prompt:
            return httpx.Response(400, text=FILTER_TEXT, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "一段转录文字"}, "finish_reason": "stop"}],
                                         "usage": {}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    got = visual.refine(_img(tmp_path), LINES, "text", CFG)
    assert got["status"] == "ok"

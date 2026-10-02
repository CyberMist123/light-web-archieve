"""第 1B 批干净环境验收：新建 venv 只 `pip install -e .` 之后，用合成样例跑一遍随包自带的能力。

    python -m venv <venv> && <venv>\\Scripts\\pip install -e <仓库>
    <venv>\\Scripts\\python tests\\tools\\clean_venv_1b.py

不需要任何 LINK_BRAIN_* 环境变量、仓库外脚本或 key（本脚本只在自己进程里把 vault / home 指到临时目录，免得写进仓库）。
不联网：识图 / 概要用本进程起的假 OpenAI 兼容服务端，语音用假 CapsWriter websocket 服务端；小红书抓取换成合成笔记。
每步打印一行 `PASS|FAIL 名称：说明`，最后一行是 JSON 汇总；有 FAIL 退出 1。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="lwa-1b-clean-"))
for key in [k for k in os.environ if k.startswith("LINK_BRAIN_") or k.startswith("DASHSCOPE_")]:
    del os.environ[key]
os.environ["LINK_BRAIN_VAULT"] = str(TMP / "vault")
os.environ["LINK_BRAIN_HOME"] = str(TMP / "home")
os.environ["LINK_BRAIN_RENDER_INPROC"] = "1"
# 本机保险丝（和 tests/conftest.py 同一套）：绝不拉起、连接本机的小红书读取服务 / relatedfile
os.environ["LINK_BRAIN_XHS_EXE"] = str(TMP / "no-such-reader.exe")
os.environ["LINK_BRAIN_RELATEDFILE_EXE"] = str(TMP / "no-such-relatedfile.exe")
os.environ["XHS_PROFILE_DIR"] = str(TMP / "xhs-profile")
os.environ["LWA_OPEN_GAP"] = "0,0"
os.environ["LWA_FETCH_REST"] = "0,0"

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}：{detail}", file=sys.stderr)


GOOD_SUMMARY = {"summary": "番茄炒蛋家常做法", "key_points": ["先炒蛋后炒番茄"], "tags": ["菜谱", "家常菜"],
                "links_worth_opening": [], "valuable_comments": [], "ads_or_noise": []}


class FakeOpenAI(BaseHTTPRequestHandler):
    """/chat/completions：stream=true 回 SSE（概要），否则回整包（识图）。"""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeOpenAI.seen.append({"path": self.path, "model": body.get("model"), "auth": self.headers.get("Authorization")})
        if body.get("stream"):
            text = json.dumps(GOOD_SUMMARY, ensure_ascii=False)
            events = [{"choices": [{"delta": {"content": text}}]},
                      {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 300, "completion_tokens": 60}}]
            payload = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events) + "data: [DONE]\n\n"
            self._send(200, payload.encode("utf-8"), "text/event-stream")
        else:
            doc = {"choices": [{"message": {"content": "类型：截图文字\nOCR TEST"}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
            self._send(200, json.dumps(doc).encode(), "application/json")

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


FakeOpenAI.seen = []


def write_settings(raw: dict) -> None:
    from link_brain import ai_config
    path = ai_config.data_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    import _samples
    from link_brain import ask, docconv, problems, voice
    work = TMP / "samples"
    work.mkdir(parents=True)

    # ---- 附件转换 ----
    r = docconv.to_markdown(_samples.text_pdf(work / "带文字层.pdf", [["Hello archive, this PDF has a real text layer."] * 6]))
    check("带文字层的 PDF", r["status"] == "ok" and r["method"] == "text_layer" and "real text layer" in r["markdown"],
          f"{r['status']} / {r['method']} / {r['note']}")
    r = docconv.to_markdown(_samples.image_pdf(work / "扫描件.pdf", ["SCANNED PAGE ONE", "SCANNED PAGE TWO"]))
    check("扫描版 PDF（本地 OCR）", r["status"] == "ok" and r["method"] == "ocr" and "SCANNED" in (r["markdown"] or "").upper(),
          f"{r['status']} / {r['method']} / {r['note']}")
    locked = work / "加密.pdf"
    locked.write_bytes(_samples.encrypted_pdf_bytes())
    r = docconv.to_markdown(locked)
    check("加密 PDF", r["status"] == "failed" and r["code"] == "PERMANENT.PDF_ENCRYPTED", f"{r['code']} / {r['error']}")
    r = docconv.to_markdown(_samples.docx(work / "表格.docx"))
    check("docx（含表格）", r["status"] == "ok" and "| 番茄 | 两个 |" in (r["markdown"] or ""), f"{r['status']} / {r['method']}")

    # ---- 语音：假 CapsWriter 服务端；关掉后 = skipped ----
    from _samples import FakeCapsWriter, free_port
    srv = FakeCapsWriter()
    write_settings({"asrAI": {"mode": "capswriter", "port": srv.port}})
    r = voice.transcribe(voice.SAMPLE)
    srv.close()
    check("短音频（假 CapsWriter）", r["status"] == "ok" and r["text"] == "第1段", f"{r['status']} / {r.get('engine')} / {r.get('text')}")
    write_settings({"asrAI": {"mode": "capswriter", "port": free_port()}})
    r = voice.transcribe(voice.SAMPLE)
    check("CapsWriter 没开 = 跳过", r["status"] == "skipped" and r["code"] == "SKIPPED.NOT_CONFIGURED", r.get("error") or "")

    # ---- 零 key：归档完整，概要 skipped，问题记录有一条 ----
    from link_brain import cli, enrich, index as index_mod, llm, storage
    from link_brain.adapters import xiaohongshu as xhs
    write_settings({})
    payload = json.loads((ROOT / "tests" / "fixtures" / "mcp_raw_sanitized.json").read_text(encoding="utf-8"))
    note_id = "0000000000000000deadbeef"
    xhs.parse_input = lambda text, client=None: {"note_id": note_id, "xsec_token": "FAKE",
                                                 "canonical_url": xhs.CANONICAL_FMT.format(note_id=note_id),
                                                 "input_url": text, "input_kind": "url"}
    xhs.fetch_detail = lambda *a, **k: payload
    xhs.fetch_related_file = lambda *a, **k: {"ok": False, "related_file": None, "url": "", "error": "验收不联网"}
    from link_brain import accounts

    def no_reader(*a, **k):
        raise accounts.httpx.ConnectError("验收不连读取服务")  # 和 tests/conftest.py 一样：当它没在跑
    accounts.httpx.request = no_reader
    from link_brain import attachments as attachments_mod
    attachments_mod._probe_logged_in = lambda *a, **k: {"ok": False, "error": "验收不碰号"}
    code = cli.main(["ingest", "https://example.invalid/share"])
    conn = index_mod.connect()
    row = conn.execute("SELECT item_id, source, source_id FROM objects").fetchone()
    conn.close()
    archived = row is not None and (storage.object_dir(row["source"], row["source_id"]) / "meta.json").is_file()
    check("零 key 归档", archived and code in (0, 2), f"ingest 退出码 {code}（2 = 合成笔记里的图片地址下不到，不联网）")
    code = cli.main(["enrich", "--item", row["item_id"]])
    doc = llm.load_extracted(row["source"], row["source_id"]) or {}
    rows = [p for p in problems.load() if p["step"] == "enrich.summary"]
    check("零 key 概要 = SKIPPED", code == 0 and doc.get("status") == "skipped" and rows and rows[0]["code"] == "SKIPPED.NOT_CONFIGURED",
          f"enrich 退出码 {code}；extracted={doc.get('status')}；问题记录={[p['code'] for p in rows]}")

    # ---- 打标概要 + 识图：假 OpenAI 兼容服务端 ----
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    write_settings({"textAI": {"mode": "http", "endpoint": endpoint, "model": "fake-text", "apiKey": "TEST-KEY"},
                    "visionAI": {"mode": "http", "endpoint": endpoint, "model": "fake-vl", "apiKey": "TEST-KEY"}})
    needs = enrich.needs(row["source"], row["source_id"])
    code = cli.main(["enrich", "--item", row["item_id"]])
    doc = llm.load_extracted(row["source"], row["source_id"]) or {}
    data = doc.get("data") or {}
    check("打标概要（假 HTTP 服务端）", "summary" in needs and code == 0 and doc.get("status") == "ok" and "菜谱" in data.get("tags", []),
          f"配上后 needs={needs}；enrich 退出码 {code}；model={doc.get('model')}；tags={data.get('tags')}；usage={doc.get('usage', {}).get('note')}")
    rows = [p for p in problems.load() if p["step"] == "enrich.summary"]
    check("概要成功后问题记录清掉", rows == [], f"剩 {len(rows)} 条")
    t = ask.selftest("summary")
    check("测试按钮：归档摘要", t["ok"] is True, t["detail"])
    t = ask.selftest("vision")
    check("测试按钮：识图", t["ok"] is True and "截图文字" in t["detail"], t["detail"])
    server.shutdown()
    check("请求带了设置里的 key 和模型", any(s["auth"] == "Bearer TEST-KEY" and s["model"] == "fake-text" for s in FakeOpenAI.seen),
          f"{len(FakeOpenAI.seen)} 次请求")

    bad = [r for r in RESULTS if not r["ok"]]
    print(json.dumps({"ok": not bad, "passed": len(RESULTS) - len(bad), "failed": len(bad), "python": sys.executable},
                     ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

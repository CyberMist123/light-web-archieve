"""第 7 批「开始」页向导后端：setup plan / check / install / estimate / backfill。

不联网：CapsWriter 发布包用本地假包（127.0.0.1 上的小 HTTP 服务，支持 Range），服务端拉起 / 自检换成假的；
本机进程 / 端口 / 常见安装位置的探测全换掉，测试结果不受开发机上装没装 CapsWriter 影响。
"""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import random
import threading
import zipfile
from pathlib import Path

import pytest

from link_brain import cli
from link_brain.setup import backfill, capswriter, common, components, estimate, fetch, sysinfo


# --------------------------------------------------------------------------
# 夹具：隔离本机探测 + 本地发布服务
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_local_probe(monkeypatch, tmp_path):
    monkeypatch.delenv("CAPSWRITER_DIR", raising=False)
    monkeypatch.setattr(capswriter, "_running_servers", lambda: [])
    monkeypatch.setattr(capswriter, "_guesses", lambda: [])
    monkeypatch.setattr(sysinfo, "processes_named", lambda name: [])
    monkeypatch.setattr(sysinfo, "port_open", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(capswriter, "windows", lambda: True)
    monkeypatch.setattr(fetch, "REPORT_EVERY", 1)  # 小包也能看到进度事件


def _vault() -> Path:
    return Path(os.environ["LINK_BRAIN_VAULT"])


def _home() -> Path:
    return Path(os.environ["LINK_BRAIN_HOME"])


def _plugin_data(data: dict | None = None) -> Path:
    p = _vault() / ".obsidian" / "plugins" / "link-brain-actions" / "data.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if data is not None:
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}
    log: list[tuple[str, str]] = []

    def do_GET(self):  # noqa: N802
        body = self.files.get(self.path)
        rng = self.headers.get("Range")
        self.log.append((self.path, rng or ""))
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            if start >= len(body):
                self.send_response(416)
                self.end_headers()
                return
            chunk = body[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        else:
            chunk = body
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def log_message(self, *a):  # 安静
        pass


@pytest.fixture
def release_server():
    _RangeHandler.files = {}
    _RangeHandler.log = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class _GbkInfo(zipfile.ZipInfo):
    def _encodeFilenameFlags(self):  # noqa: N802 - 覆盖 zipfile 内部方法
        return self.filename.encode("gbk"), self.flag_bits & ~0x800


def _zip(entries: dict[str, bytes], *, gbk_names: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            if gbk_names:  # 像 Windows 资源管理器 / 7-Zip 打的包：文件名是 GBK 字节、不打 UTF-8 标记
                info = _GbkInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)
            else:
                zf.writestr(name, data)
    return buf.getvalue()


CONFIG_SERVER = """class ServerConfig:
    addr = '0.0.0.0'
    port = '6123'

    # 语音模型选择
    model_type = 'qwen_asr'
"""


@pytest.fixture
def fake_release(monkeypatch, release_server):
    srv, base = release_server
    pkg = _zip({"CapsWriter-Offline/start_server.exe": b"MZ-server", "CapsWriter-Offline/start_client.exe": b"MZ-client",
                "CapsWriter-Offline/config_server.py": CONFIG_SERVER.encode("utf-8"),
                "CapsWriter-Offline/models/Qwen3-ASR/模型下载链接.txt": b"see release"}, gbk_names=True)
    rnd = random.Random(7)
    model = _zip({"qwen3_asr_encoder_frontend.onnx": rnd.randbytes(3000), "qwen3_asr_encoder_backend.onnx": rnd.randbytes(5000),
                  "qwen3_asr_llm.gguf": rnd.randbytes(20000)})
    _RangeHandler.files = {"/pkg.zip": pkg, "/model.zip": model}
    monkeypatch.setattr(capswriter, "PACKAGE", {**capswriter.PACKAGE, "url": base + "/pkg.zip", "name": "pkg.zip",
                                                "size": len(pkg), "sha256": hashlib.sha256(pkg).hexdigest(),
                                                "unpacked": 10_000})
    monkeypatch.setattr(capswriter, "MODELS", {"qwen3-asr-q4": {**capswriter.MODELS["qwen3-asr-q4"],
                                                                "url": base + "/model.zip", "name": "model.zip",
                                                                "size": len(model),
                                                                "sha256": hashlib.sha256(model).hexdigest(),
                                                                "unpacked": 30_000}})
    calls = {"start": [], "verify": []}

    def fake_start(folder, *, ours):
        calls["start"].append((str(folder), ours))
        return "假启动"

    def fake_verify(host, port, emit):
        calls["verify"].append((host, port))
        # 服务端「起来了」：之后的端口探测按通算（install 装完会再 check 一遍）
        monkeypatch.setattr(sysinfo, "port_open", lambda h, p, timeout=1.0: (h, p) == (host, port))
        common.progress(emit, "asr", "验证", None, None, "假自检")
        return {"status": "ok", "text": "你好", "code": "", "error": None}

    monkeypatch.setattr(capswriter, "_start_server", fake_start)
    monkeypatch.setattr(capswriter, "_verify", fake_verify)
    return {"pkg": pkg, "model": model, "calls": calls, "server": srv}


def _run_cli(capsys, *argv) -> tuple[int, list[dict]]:
    code = cli.main(["setup", *argv])
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    return code, lines


# --------------------------------------------------------------------------
# plan / check
# --------------------------------------------------------------------------

def test_plan_shape(capsys):
    code, lines = _run_cli(capsys, "plan")
    assert code == 0 and len(lines) == 1
    plan = lines[0]
    assert plan["ok"] is True and plan["code"] == ""
    ids = [c["id"] for c in plan["components"]]
    assert ids == components.IDS
    assert set(ids) >= {"core", "ocr", "asr", "capslock", "ai_text", "ai_vision", "reader", "dataview", "remote"}
    for c in plan["components"]:
        for key in ("id", "name", "desc", "required", "default", "needs_key", "local", "disk_mb", "ram_mb", "installed",
                    "status", "detail", "depends", "settings_tab", "basis", "check_only", "later"):
            assert key in c, (c["id"], key)
        assert c["status"] in ("ready", "missing", "partial", "unknown", "needs_key")
        for key in ("disk_mb", "ram_mb"):
            assert isinstance(c[key], int) and c[key] >= 0, (c["id"], key, c[key])
        assert c["basis"]
        assert all(d in ids for d in c["depends"])
    by = {c["id"]: c for c in plan["components"]}
    assert by["dataview"]["check_only"] is True and by["remote"]["later"] is True
    assert by["ai_text"]["needs_key"] and by["ai_text"]["disk_mb"] == 0 and by["ai_text"]["ram_mb"] == 0
    # 没装 CapsWriter：磁盘按官方包 + 模型解压大小
    asr = by["asr"]
    assert asr["status"] == "missing" and asr["installed"] is False
    want = (capswriter.PACKAGE["unpacked"] + capswriter.MODELS[capswriter.DEFAULT_MODEL]["unpacked"]) / (1 << 20)
    assert abs(asr["disk_mb"] - want) <= 1
    assert plan["presets"]["light"] == ["core", "reader", "dataview", "ocr"]
    assert plan["presets"]["full"] == ids
    assert all(i in ids for p in plan["presets"].values() for i in p)
    assert plan["totals_basis"].startswith("磁盘 / 内存是估计值")
    rel = plan["capswriter_release"]
    assert rel["license"] == "MIT" and rel["package"]["sha256"] and rel["package"]["url"].startswith("https://github.com/")


def test_check_shape_and_unknown_component(capsys):
    code, lines = _run_cli(capsys, "check")
    out = lines[-1]
    assert code == 0 and out["ok"] is True
    assert [r["item_id"] for r in out["results"]] == components.IDS
    for r in out["results"]:
        assert set(r) >= {"item_id", "status", "code", "error", "detail", "fix", "fix_hint"}
        assert r["status"] in ("ready", "missing", "partial", "failed", "needs_key")
        assert r["fix"] in ("", "auto", "manual")
    by = {r["item_id"]: r for r in out["results"]}
    assert by["asr"]["status"] == "missing" and by["asr"]["fix"] == "auto"
    assert by["ai_text"]["status"] == "needs_key" and by["ai_text"]["fix"] == "manual"
    assert out["all_ready"] is False  # 被 asr 等拖住，不是被 ai_text
    code, lines = _run_cli(capsys, "check", "--components", "ocr,bogus")
    out = lines[-1]
    assert code == 1 and out["ok"] is False
    assert [r["item_id"] for r in out["results"]] == ["ocr", "bogus"]
    assert out["results"][1]["status"] == "failed"


def test_needs_key_items_do_not_block_all_ready(monkeypatch):
    real = components.evaluate

    def fake(ids=None):
        out = real(ids)
        for cid, e in out.items():
            if cid not in ("ai_text", "ai_vision"):
                e["row"] = {**e["row"], "status": "ready"}
        return out
    monkeypatch.setattr(components, "evaluate", fake)
    out = components.check()
    by = {r["item_id"]: r["status"] for r in out["results"]}
    assert by["ai_text"] == by["ai_vision"] == "needs_key"
    assert out["ok"] is True and out["all_ready"] is True and out["message"] == "全部就绪"


def test_check_is_read_only(tmp_path):
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    components.check()
    components.plan()
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after


# --------------------------------------------------------------------------
# install asr：一键安装 / 进度 / 中断 / 续传 / 已装不覆盖
# --------------------------------------------------------------------------

def test_install_asr_fresh_progress_and_result(capsys, fake_release):
    _plugin_data({"asrAI": {"mode": "off"}, "other": 1})
    code, lines = _run_cli(capsys, "install", "--component", "asr")
    assert code == 0, lines[-1]
    *events, result = lines
    assert all(e["type"] == "progress" and e["component"] == "asr" for e in events)
    phases = [e["phase"] for e in events]
    for ph in ("下载", "校验", "下载模型", "解压", "验证"):
        assert ph in phases, ph
    assert phases.index("下载") < phases.index("下载模型") < phases.index("解压") < phases.index("验证")
    dl = [e for e in events if e["phase"] == "下载"]
    assert dl[-1]["done"] == dl[-1]["total"] == len(fake_release["pkg"])
    assert result["type"] == "result" and result["ok"] is True and result["status"] == "ready"
    assert result["check"]["status"] == "ready"
    target = _home() / "capswriter"
    assert (target / "start_server.exe").read_bytes() == b"MZ-server"
    assert (target / "models/Qwen3-ASR/Qwen3-ASR-1.7B/qwen3_asr_llm.gguf").stat().st_size == 20000
    assert (target / "models/Qwen3-ASR/模型下载链接.txt").is_file()  # GBK 文件名还原了
    cfg = (target / "config_server.py").read_text(encoding="utf-8")
    assert "addr = '127.0.0.1'" in cfg and "model_type = 'qwen_asr'" in cfg
    marker = json.loads((target / capswriter.MARKER).read_text(encoding="utf-8"))
    assert marker["package_sha256"] == hashlib.sha256(fake_release["pkg"]).hexdigest()
    assert not list(_home().glob("capswriter.staging-*"))
    assert not (_home() / "downloads" / "pkg.zip").exists()  # 装好删下载包
    data = json.loads(_plugin_data().read_text(encoding="utf-8"))
    assert data["asrAI"] == {"mode": "capswriter", "host": "127.0.0.1", "port": "6123"}
    assert data["voice"]["capsWriterDir"] == str(target) and data["other"] == 1
    assert result["settings_patch"]["asrAI"]["port"] == "6123"
    assert fake_release["calls"]["start"] == [(str(target), True)]
    assert fake_release["calls"]["verify"] == [("127.0.0.1", 6123)]


def test_install_asr_interrupted_then_reinstall_clean(monkeypatch, fake_release):
    real_unzip = fetch.unzip

    def boom(pkg, target, **kw):
        if Path(pkg).name == "model.zip":
            (Path(target) / "half.bin").parent.mkdir(parents=True, exist_ok=True)
            (Path(target) / "half.bin").write_bytes(b"x")
            raise KeyboardInterrupt
        return real_unzip(pkg, target, **kw)

    monkeypatch.setattr(fetch, "unzip", boom)
    with pytest.raises(KeyboardInterrupt):
        capswriter.install(None)
    assert not (_home() / "capswriter").exists()
    assert not list(_home().glob("capswriter.staging-*"))
    assert (_home() / "downloads" / "model.zip").is_file()  # 校验过的下载包留着
    monkeypatch.setattr(fetch, "unzip", real_unzip)
    before = len(_RangeHandler.log)
    out = capswriter.install(None)
    assert out["ok"] is True and out["changed"] is True
    assert len(_RangeHandler.log) == before  # 没有重下
    assert not (_home() / "capswriter" / "models/Qwen3-ASR/Qwen3-ASR-1.7B/half.bin").exists()


def test_install_asr_cli_interrupt_reports_result(capsys, monkeypatch, fake_release):
    def interrupted(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(capswriter, "_fresh_install", interrupted)
    code, lines = _run_cli(capsys, "install", "--component", "asr")
    assert code == 1
    assert lines[-1]["type"] == "result" and lines[-1]["code"] == "TRANSIENT.INTERRUPTED"


def test_download_resumes_from_part(fake_release):
    model = fake_release["model"]
    dest = _home() / "downloads" / "model.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    (dest.parent / "model.zip.part").write_bytes(model[:1000])
    info = capswriter.MODELS["qwen3-asr-q4"]
    got = fetch.fetch_verified(info["url"], dest, sha256=info["sha256"], size=info["size"])
    assert got["verified"] and dest.read_bytes() == model
    assert ("/model.zip", "bytes=1000-") in _RangeHandler.log


def test_checksum_mismatch_cleans_up(monkeypatch, fake_release):
    monkeypatch.setattr(capswriter, "PACKAGE", {**capswriter.PACKAGE, "sha256": "0" * 64})
    out = capswriter.install(None)
    assert out["ok"] is False and out["code"] == "PERMANENT.CHECKSUM_MISMATCH"
    assert not (_home() / "capswriter").exists()
    assert not list((_home() / "downloads").glob("pkg.zip*"))
    assert fake_release["calls"]["start"] == []


def test_disk_full_refuses_before_download(monkeypatch, fake_release):
    import shutil as _sh
    monkeypatch.setattr(_sh, "disk_usage", lambda p: _sh._ntuple_diskusage(10, 10, 5))
    out = capswriter.install(None)
    assert out["ok"] is False and out["code"] == "PERMANENT.DISK_FULL"
    assert _RangeHandler.log == []


def _foreign_install(tmp_path) -> Path:
    d = tmp_path / "her-capswriter"
    (d / "models/Qwen3-ASR/Qwen3-ASR-1.7B").mkdir(parents=True)
    for n in ("qwen3_asr_encoder_frontend.onnx", "qwen3_asr_encoder_backend.onnx", "qwen3_asr_llm.gguf"):
        (d / "models/Qwen3-ASR/Qwen3-ASR-1.7B" / n).write_bytes(b"m")
    (d / "start_server.exe").write_bytes(b"hers")
    (d / "start_client.exe").write_bytes(b"hers")
    (d / "config_server.py").write_text(CONFIG_SERVER.replace("6123", "6016"), encoding="utf-8")
    return d


def _snapshot(folder: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in folder.rglob("*")}


def test_existing_running_capswriter_is_ready_untouched(monkeypatch, tmp_path, fake_release):
    d = _foreign_install(tmp_path)
    data = _plugin_data({"voice": {"capsWriterDir": str(d)}, "asrAI": {"mode": "capswriter"}})
    before, settings_before = _snapshot(d), data.read_bytes()
    monkeypatch.setattr(sysinfo, "port_open", lambda host, port, timeout=1.0: port == 6016)
    row = capswriter.check()
    assert row["status"] == "ready"
    out = components.install("asr", None)
    assert out["ok"] is True and out["status"] == "ready" and out["changed"] is False
    assert "settings_patch" not in out
    assert _RangeHandler.log == [] and fake_release["calls"]["start"] == []
    assert _snapshot(d) == before and data.read_bytes() == settings_before
    assert not (_home() / "capswriter").exists()
    # capslock 同理：客户端在就 ready，不改设置
    assert components.install("capslock", None)["ok"] is True
    assert data.read_bytes() == settings_before


def test_existing_stopped_capswriter_only_started(monkeypatch, tmp_path, fake_release):
    d = _foreign_install(tmp_path)
    monkeypatch.setenv("CAPSWRITER_DIR", str(d))
    before = _snapshot(d)
    row = capswriter.check()
    assert row["status"] == "partial" and row["fix"] == "auto"
    out = capswriter.install(None)
    assert out["ok"] is True and out["changed"] is False
    assert fake_release["calls"]["start"] == [(str(d), False)]
    assert fake_release["calls"]["verify"] == [("127.0.0.1", 6016)]
    assert _RangeHandler.log == [] and _snapshot(d) == before


def test_existing_capswriter_missing_model_not_touched(monkeypatch, tmp_path, fake_release):
    d = _foreign_install(tmp_path)
    (d / "models/Qwen3-ASR/Qwen3-ASR-1.7B/qwen3_asr_llm.gguf").unlink()
    monkeypatch.setenv("CAPSWRITER_DIR", str(d))
    row = capswriter.check()
    assert row["status"] == "partial" and row["fix"] == "manual"
    out = components.install("asr", None)
    assert out["ok"] is False and out.get("manual") is True
    assert _RangeHandler.log == [] and fake_release["calls"]["start"] == []


def test_unzip_rejects_zip_slip(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(_zip({"../evil.txt": b"x"}))
    with pytest.raises(common.SetupError) as e:
        fetch.unzip(bad, tmp_path / "out")
    assert e.value.code == "PERMANENT.BAD_PACKAGE"
    assert not (tmp_path / "evil.txt").exists()


# --------------------------------------------------------------------------
# install：其它组件
# --------------------------------------------------------------------------

def test_install_manual_only_component_exit_5(capsys):
    code, lines = _run_cli(capsys, "install", "--component", "dataview")
    assert code == 5
    assert lines[-1]["ok"] is False and lines[-1]["manual"] is True and lines[-1]["check"]["fix"] == "manual"


def test_install_unknown_component(capsys):
    code, lines = _run_cli(capsys, "install", "--component", "nope")
    assert code == 1 and lines[-1]["ok"] is False


def test_install_core_when_present(capsys):
    code, lines = _run_cli(capsys, "install", "--component", "core")
    assert code == 0 and lines[-1]["ok"] is True and lines[-1]["changed"] is False


def test_ocr_models_download_and_settings(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    models = []
    for part in ("det", "rec"):
        f = src / f"PP-OCRv6_{part}_medium.onnx"
        f.write_bytes(part.encode() * 1000)
        models.append({"part": part, "url": f.as_uri(), "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                       "name": f.name})
    monkeypatch.setattr(components, "ocr_release_models", lambda tier="medium": models)
    monkeypatch.setattr(components, "_ocr_selftest", lambda tier, model_dir: None)
    empty_dir = tmp_path / "pkg-models"
    empty_dir.mkdir()
    monkeypatch.setattr(components, "_ocr_model_files",
                        lambda tier, model_dir: ((Path(model_dir) if model_dir else empty_dir),
                                                 [(Path(model_dir) if model_dir else empty_dir) / f"PP-OCRv6_{p}_{tier}.onnx"
                                                  for p in ("det", "rec")]))
    data = _plugin_data({"ocr": {"mode": "local", "modelTier": "medium", "modelDir": ""}})
    assert components.check(["ocr"])["results"][0]["status"] == "partial"
    events = []
    out = components.install("ocr", events.append)
    assert out["ok"] is True, out
    target = _home() / "models" / "rapidocr"
    assert (target / "PP-OCRv6_det_medium.onnx").is_file() and (target / "PP-OCRv6_rec_medium.onnx").is_file()
    assert json.loads(data.read_text(encoding="utf-8"))["ocr"]["modelDir"] == str(target)
    assert out["settings_patch"] == {"ocr": {"modelDir": str(target)}}
    assert {"下载模型", "校验", "验证"} <= {e["phase"] for e in events}


def test_ocr_existing_model_dir_left_alone(monkeypatch, tmp_path):
    d = tmp_path / "her-ocr"
    d.mkdir()
    for part in ("det", "rec"):
        (d / f"PP-OCRv6_{part}_medium.onnx").write_bytes(b"x")
    data = _plugin_data({"ocr": {"mode": "local", "modelTier": "medium", "modelDir": str(d)}})
    before = data.read_bytes()
    monkeypatch.setattr(components, "ocr_release_models", lambda tier="medium": pytest.fail("不该下载"))
    monkeypatch.setattr(components, "_ocr_selftest", lambda tier, model_dir: None)
    assert components.check(["ocr"])["results"][0]["status"] == "ready"
    out = components.install("ocr", None)
    assert out["ok"] is True and "settings_patch" not in out and data.read_bytes() == before


# --------------------------------------------------------------------------
# estimate
# --------------------------------------------------------------------------

def _note(root: Path, nid: str, *, body: str, video_sec: int = 0, vision_tokens=(), summary=(1000, 400),
          favorite: bool = True) -> None:
    d = root / "_archive" / "xiaohongshu" / nid
    (d / "raw" / "v0001").mkdir(parents=True)
    (d / "derived").mkdir()
    (d / "meta.json").write_text(json.dumps({"favorited_by": ["me"] if favorite else [],
                                             "ingest_kind": "favorite" if favorite else "shared"}), encoding="utf-8")
    note = {"title": "标题", "body": body}
    if video_sec:
        note["video"] = {"duration_sec": str(video_sec)}
    (d / "raw" / "v0001" / "source.json").write_text(json.dumps({"note": note, "comments": [{"text": "评论"}]},
                                                                ensure_ascii=False), encoding="utf-8")
    if summary:
        (d / "derived" / "extracted.json").write_text(json.dumps({"status": "ok", "usage": {
            "input_tokens_est": summary[0], "output_tokens_est": summary[1]}}), encoding="utf-8")
    images = [{"asset": f"i{i}", "visual": {"tokens": list(t)} if t else {"kind": "title"}}
              for i, t in enumerate(vision_tokens)]
    (d / "derived" / "vision.json").write_text(json.dumps({"images": images}), encoding="utf-8")


def _flat_pricing():
    """把价格换成好算的整数，测算法本身。"""
    p = _home() / "pricing.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"models": {
        "deepseek-flash": {"input": 1.0, "output": 2.0},
        "qwen3.8-flash": {"input": 10.0, "output": 100.0},
        "gpt-4o-mini-transcribe": {"price": 0.5, "currency": "USD"},
    }, "usd_cny": {"rate": 7.0}}), encoding="utf-8")


def test_estimate_from_library(capsys):
    _flat_pricing()
    v = _vault()
    _note(v, "a", body="字" * 100, video_sec=120, vision_tokens=[(1000, 100), (3000, 300), None])
    _note(v, "b", body="字" * 300, video_sec=0, vision_tokens=[], summary=(3000, 600))
    code, lines = _run_cli(capsys, "estimate", "--posts", "100")
    out = lines[-1]
    assert code == 0 and out["ok"] is True and out["posts"] == 100
    b = out["basis"]
    assert b["from_library"] is True and b["sample"] == 2
    assert b["avg_chars"] == 202  # (2+100 + 2+300) / 2
    assert b["avg_video_min"] == 1.0  # 2 分钟 / 2 篇
    assert b["avg_images"] == 1.5 and b["vision_calls"] == 1.0
    assert b["vision_tokens_in"] == 2000 and b["vision_tokens_out"] == 200
    assert b["summary_tokens_in"] == 2000 and b["summary_tokens_out"] == 500
    items = {i["id"]: i for i in out["items"]}
    assert set(items) == {"summary", "vision", "video", "ask"}
    for i in out["items"]:
        assert set(i) >= {"id", "name", "provider", "model", "yuan", "per", "how"}
    # 概要：100 篇 ×（2000×1 + 500×2）/ 1e6 = 0.3 元
    assert items["summary"]["model"] == "deepseek-flash" and items["summary"]["yuan"] == 0.3
    # 识图：100 篇 × 1 次 ×（2000×10 + 200×100）/ 1e6 = 4.0 元
    assert items["vision"]["yuan"] == 4.0
    # 视频：100 篇 × 1 分钟 × 0.5 美元 × 7 = 350 元
    assert items["video"]["yuan"] == 350.0
    assert items["ask"]["per"] == "次" and items["ask"]["yuan"] > 0
    assert out["prices"]["as_of"] and out["prices"]["sources"]
    assert out["local_free"] == ["ocr", "asr"]


def test_estimate_uses_configured_model():
    _flat_pricing()
    _plugin_data({"summaryAI": {"mode": "http", "model": "qwen3.7-flash", "endpoint": "https://x.invalid/v1",
                                "apiKey": "k"}})
    out = estimate.estimate(100)
    s = next(i for i in out["items"] if i["id"] == "summary")
    assert s["model"] == "qwen3.7-flash" and s["configured"] is True
    assert any(a["model"] == "deepseek-flash" for a in s["alternatives"])


def test_estimate_empty_library_uses_typical():
    out = estimate.estimate(100)
    assert out["basis"]["from_library"] is False and out["basis"]["sample"] == 0
    assert all(i["yuan"] is None or i["yuan"] >= 0 for i in out["items"])
    assert next(i for i in out["items"] if i["id"] == "summary")["yuan"] > 0


def test_pricing_table_sane():
    data = json.loads(estimate.PRICING_PATH.read_text(encoding="utf-8"))
    assert data["as_of"] and data["usd_cny"]["rate"] and data["usd_cny"]["source"].startswith("https://")
    for key, m in data["models"].items():
        assert m["source"] in data["sources"], key
        assert m["checked"] and m["currency"] in ("CNY", "USD") and m["unit"]
        if m["unit"] == "per_million_tokens":
            assert isinstance(m["input"], (int, float)) and isinstance(m["output"], (int, float)), key
        else:
            assert m["price"] is None or isinstance(m["price"], (int, float)), key
    for item, model in data["recommended"].items():
        assert model in data["models"], (item, model)


# --------------------------------------------------------------------------
# backfill
# --------------------------------------------------------------------------

def test_backfill_from_status_and_library(capsys, tmp_path):
    v = _vault()
    for i in range(3):
        _note(v, f"f{i}", body="x")
    _note(v, "s", body="x", favorite=False)
    (tmp_path / "sync-status.json").write_text(json.dumps({"state": "finished", "favorites": 50,
                                                           "last_favorites": 1159}), encoding="utf-8")
    _plugin_data({"sync": {"dailyNewLimit": 50}})
    code, lines = _run_cli(capsys, "backfill")
    out = lines[-1]
    assert code == 0 and out["ok"] is True
    assert out["favorites_total"] == 1159 and out["archived"] == 3 and out["archived_all"] == 4
    assert out["deferred"] == 1156 and out["deferred_from"] == "total_minus_archived"
    assert out["daily_limit"] == 50 and out["days_left"] == 24
    assert out["as_of"]


def test_backfill_prefers_last_sync_deferred_and_unlimited(tmp_path):
    (tmp_path / "sync-status.json").write_text(json.dumps({"state": "finished", "favorites": 100, "deferred": 7}),
                                              encoding="utf-8")
    _plugin_data({"sync": {"dailyNewLimit": 0}})
    out = backfill.backfill()
    assert out["deferred"] == 7 and out["deferred_from"] == "last_sync" and out["days_left"] == 1


def test_backfill_no_data():
    out = backfill.backfill()
    assert out["favorites_total"] is None and out["deferred"] is None and out["days_left"] is None
    assert out["archived"] == 0

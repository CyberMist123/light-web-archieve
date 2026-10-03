"""CapsWriter-Offline（本地语音识别）检测 + 一键安装。

检测（只读）：设置里的「CapsWriter 目录」→ 环境变量 CAPSWRITER_DIR → 本程序装的 `~/.link-brain/capswriter` →
正在运行的 start_server.exe 所在目录 → 几个常见解压位置（和插件 main.js capsWriterDir() 同一份，不猜私人盘位）。
**已经装了的（不管谁装的）绝不重装、不覆盖、不改它的文件和设置**：服务端在跑 = 直接 ready；没在跑就只拉起来自检。

安装（没装时）：官方 GitHub Release 的发布包 + 一个模型包 → `~/.link-brain/downloads/`（可续传）→ sha256 校验 →
解到临时目录 `~/.link-brain/capswriter.staging-<pid>` → 改两处服务端配置（只听本机 127.0.0.1、选模型）→
写安装记录 → 整个目录一次改名成 `~/.link-brain/capswriter`（改名前任何一步断掉，正式目录都不会出现半截）→
写插件设置（asrAI 地址端口、CapsWriter 目录）→ 拉起服务端（经 cmd start 中转，不是任何 Python 的子进程）→
用随包 3 秒样例真识别一次。

发布信息（2026-10-03 读 GitHub Releases API 元数据核对，未下载大包；sha256 是 GitHub 给每个发布文件算的 digest）：
- 仓库 https://github.com/HaujetZhao/CapsWriter-Offline ，许可 MIT（仓库 LICENSE，Copyright (c) 2026 Haujet Zhao）
- 程序：tag v2.6「大量细节改进」（2026-05-30 发布，包 2026-09-14 更新）CapsWriter-Offline-20260914.zip，
  含客户端 + 服务端，Windows 10 64 位及以上
- 模型：tag models。默认 Qwen3-ASR-1.7B-q4_k（上游服务端默认引擎 qwen_asr；发布说明：独显用 q5_k、集显试 q4_k、
  性能太差用 SenseVoice-Small）；另备 SenseVoice-Small（小、快、准确度低一档）。标点 / 时间戳对齐模型不装
  （上游加载失败会静默退回无标点 / 无精确时间戳，qwen_asr 自己出标点）。
包内结构用 HTTP Range 只读了 zip 尾部的目录（几百 KB）核对：程序包顶层是 `CapsWriter-Offline/`；
Qwen3-ASR 模型包三个文件直接在根上，要放进 `models/Qwen3-ASR/Qwen3-ASR-1.7B/`；SenseVoice 包顶层 `Sensevoice-Small-ONNX/`，
放进 `models/SenseVoice-Small/`。程序包里的中文文件名是 GBK（fetch.member_name 还原）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import fetch, sysinfo
from .common import Emit, SetupError, apply_settings_patch, mb, progress

COMPONENT = "asr"
CHECKED = "2026-10-03"
REPO = "https://github.com/HaujetZhao/CapsWriter-Offline"
LICENSE = "MIT"
SOURCE = ("GitHub Releases API：https://api.github.com/repos/HaujetZhao/CapsWriter-Offline/releases/tags/v2.6 "
          "与 /releases/tags/models（assets 的 size / digest），2026-10-03 核对")

PACKAGE: dict[str, Any] = {
    "version": "v2.6",
    "name": "CapsWriter-Offline-20260914.zip",
    "url": "https://github.com/HaujetZhao/CapsWriter-Offline/releases/download/v2.6/CapsWriter-Offline-20260914.zip",
    "size": 110555597,
    "sha256": "40a46100e2b221ed487d85aa923a38f8f722090bf1fa86975b701baceafbb6f4",
    "unpacked": 313474195,
    "strip": "CapsWriter-Offline/",
}

MODELS: dict[str, dict[str, Any]] = {
    "qwen3-asr-q4": {
        "label": "Qwen3-ASR-1.7B（q4_k）",
        "name": "Qwen3-ASR-1.7B-q4_k.zip",
        "url": "https://github.com/HaujetZhao/CapsWriter-Offline/releases/download/models/Qwen3-ASR-1.7B-q4_k.zip",
        "size": 1410584449,
        "sha256": "9b3d2a66a4a26a0404c32085ec838b7c482495a7827919a5aa674de617c2757b",
        "unpacked": 1468051775,
        "model_type": "qwen_asr",
        "target": "models/Qwen3-ASR/Qwen3-ASR-1.7B",
        "strip": "",
    },
    "sensevoice": {
        "label": "SenseVoice-Small",
        "name": "Sensevoice-Small-ONNX.zip",
        "url": "https://github.com/HaujetZhao/CapsWriter-Offline/releases/download/models/Sensevoice-Small-ONNX.zip",
        "size": 433798984,
        "sha256": "3948b5761f12db1c01d7a7e596294b43b0316aa5c7a8df77981e78573997dcbb",
        "unpacked": 473542751,
        "model_type": "sensevoice",
        "target": "models/SenseVoice-Small",
        "strip": "",
    },
}
DEFAULT_MODEL = "qwen3-asr-q4"

# 上游 config_server.py ModelPaths：每种引擎要的文件（相对安装目录）。检测「模型齐不齐」用。
REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "qwen_asr": ("models/Qwen3-ASR/Qwen3-ASR-1.7B/qwen3_asr_encoder_frontend.onnx",
                 "models/Qwen3-ASR/Qwen3-ASR-1.7B/qwen3_asr_encoder_backend.onnx",
                 "models/Qwen3-ASR/Qwen3-ASR-1.7B/qwen3_asr_llm.gguf"),
    "sensevoice": ("models/SenseVoice-Small/Sensevoice-Small-ONNX/SenseVoice-Encoder.fp16.onnx",
                   "models/SenseVoice-Small/Sensevoice-Small-ONNX/SenseVoice-CTC.fp16.onnx",
                   "models/SenseVoice-Small/Sensevoice-Small-ONNX/tokenizer.bpe.model"),
    "fun_asr_nano": ("models/Fun-ASR-Nano/Fun-ASR-Nano-GGUF/Fun-ASR-Nano-Encoder-Adaptor.fp16.onnx",
                     "models/Fun-ASR-Nano/Fun-ASR-Nano-GGUF/Fun-ASR-Nano-CTC.fp16.onnx",
                     "models/Fun-ASR-Nano/Fun-ASR-Nano-GGUF/Fun-ASR-Nano-Decoder.q5_k.gguf",
                     "models/Fun-ASR-Nano/Fun-ASR-Nano-GGUF/tokens.txt"),
    "paraformer": ("models/Paraformer/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx/model.onnx",
                   "models/Paraformer/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx/tokens.txt"),
}

MARKER = ".link-brain-install.json"
SERVER_EXE = "start_server.exe"
CLIENT_EXE = "start_client.exe"
START_WAIT_S = 240       # 服务端加载 1.4 GB 模型（CPU）要一阵：最多等这么久端口打开
VERIFY_TIMEOUT_S = 180   # 样例识别一次的上限
DISK_MARGIN = 300 << 20  # 装完还要留的余量


# --------------------------------------------------------------------------
# 检测（只读）
# --------------------------------------------------------------------------

def windows() -> bool:
    """一键安装 / 拉起只做 Windows（发布包只有 Windows 版）。单独成函数好让测试换掉。"""
    return os.name == "nt"


def install_dir() -> Path:
    from .. import storage
    return storage.link_brain_home() / "capswriter"


def _settings() -> dict[str, Any]:
    try:
        from .. import ai_config
        return ai_config.load()
    except Exception:  # noqa: BLE001 - 读不到设置就当默认
        return {}


def _guesses() -> list[Path]:
    """和插件 main.js capsWriterDir() 同一份常见位置（不猜任何人的私人盘位）。"""
    home = Path.home()
    out = []
    if os.environ.get("LOCALAPPDATA"):
        out.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "CapsWriter-Offline")
    out += [home / "CapsWriter-Offline", home / "Desktop" / "CapsWriter-Offline", home / "Downloads" / "CapsWriter-Offline",
            home / "Documents" / "CapsWriter-Offline"]
    if windows():
        out += [Path("C:/CapsWriter-Offline"), Path("C:/Program Files/CapsWriter-Offline"), Path("D:/CapsWriter-Offline")]
    return out


def looks_installed(folder: Path) -> bool:
    return any((folder / n).is_file() for n in (SERVER_EXE, CLIENT_EXE, "start_server.py", "start_client.py"))


def model_type_of(folder: Path) -> str | None:
    try:
        text = (folder / "config_server.py").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^\s*model_type\s*=\s*['\"]([\w-]+)['\"]", text, re.M)
    return m.group(1) if m else None


def missing_model_files(folder: Path, model_type: str | None) -> list[str] | None:
    """None = 不认识这种引擎（不判）；[] = 齐了。"""
    need = REQUIRED_FILES.get(model_type or "")
    if need is None:
        return None
    return [rel for rel in need if not (folder / rel).is_file()]


def _running_servers() -> list[dict[str, Any]]:
    return sysinfo.processes_named(SERVER_EXE) if windows() else []


def detect() -> dict[str, Any]:
    """找本机的 CapsWriter（只读）。返回 {dir, source, ours, host, port, server_running, processes, model_type,
    model_ok, missing_files, client_exe}。"""
    from .. import providers
    settings = _settings()
    asr_cfg = settings.get("asrAI") or {}
    voice = settings.get("voice") or {}
    host = str(asr_cfg.get("host") or "127.0.0.1")
    procs = _running_servers()
    candidates: list[tuple[str, Path]] = []
    if str(voice.get("capsWriterDir") or "").strip():
        candidates.append(("设置里的 CapsWriter 目录", Path(str(voice["capsWriterDir"]).strip())))
    if os.environ.get("CAPSWRITER_DIR"):
        candidates.append(("环境变量 CAPSWRITER_DIR", Path(os.environ["CAPSWRITER_DIR"])))
    candidates.append(("本程序装的", install_dir()))
    for p in procs:
        if p.get("exe"):
            candidates.append(("正在运行的服务端", Path(p["exe"]).parent))
    candidates += [("常见位置", g) for g in _guesses()]
    found_src, found = None, None
    for src, folder in candidates:
        if looks_installed(folder):
            found_src, found = src, folder
            break
    port_setting = str(asr_cfg.get("port") or "").strip()
    try:
        port = int(port_setting) if port_setting else providers.capswriter_port({"capsWriterDir": str(found or "")})
    except ValueError:
        port = providers.CAPSWRITER_DEFAULT_PORT
    running = sysinfo.port_open(host, port)
    out: dict[str, Any] = {"dir": str(found) if found else None, "source": found_src, "host": host, "port": port,
                           "server_running": running, "processes": procs,
                           "ours": bool(found and (found / MARKER).is_file()
                                        and os.path.normcase(str(found)) == os.path.normcase(str(install_dir()))),
                           "model_type": None, "model_ok": None, "missing_files": None, "client_exe": None}
    if found:
        mt = model_type_of(found)
        missing = missing_model_files(found, mt)
        out.update(model_type=mt, missing_files=missing, model_ok=None if missing is None else not missing)
        client = found / CLIENT_EXE
        out["client_exe"] = str(client) if client.is_file() else None
    return out


def check(det: dict[str, Any] | None = None) -> dict[str, Any]:
    """setup check 的一行（只读）。"""
    det = det or detect()
    configured = bool(PACKAGE.get("url") and PACKAGE.get("sha256") and MODELS.get(DEFAULT_MODEL, {}).get("url"))
    where = f"{det['host']}:{det['port']}"
    if det["server_running"]:
        detail = f"服务端在 {where} 运行" + (f"（{det['source']}：{det['dir']}）" if det["dir"] else "")
        return _row("ready", detail)
    if det["dir"]:
        if det["model_ok"] is False:
            miss = "、".join(Path(m).name for m in det["missing_files"][:3])
            if det["ours"]:
                return _row("partial", f"本程序装的 CapsWriter 缺模型文件（{miss}）", fix="auto",
                            hint="点「安装」会重新下载补齐")
            return _row("partial", f"已装的 CapsWriter（{det['dir']}）缺 {det['model_type']} 模型文件：{miss}",
                        fix="manual", hint="按 CapsWriter 自己的说明把模型解压到它的 models 目录（这里不替你改已装的 CapsWriter）")
        return _row("partial", f"已装（{det['source']}：{det['dir']}），服务端现在没开（{where} 连不上）", fix="auto",
                    hint="点「安装」只会把服务端拉起来并自检，不改任何文件")
    if not windows():
        return _row("missing", "没找到 CapsWriter-Offline；一键安装目前只支持 Windows", fix="manual",
                    hint=f"按 {REPO} 的说明手动安装，然后在设置里填它的目录")
    if not configured:
        return _row("missing", "没找到 CapsWriter-Offline，发布地址没配置", fix="manual",
                    hint=f"到 {REPO}/releases 手动下载")
    model = MODELS[DEFAULT_MODEL]
    return _row("missing", f"没装：一键安装会下载约 {mb(PACKAGE['size'] + model['size'])} MB"
                           f"（程序 {PACKAGE['version']} + 模型 {model['label']}），装好占约 "
                           f"{mb(PACKAGE['unpacked'] + model['unpacked'])} MB", fix="auto",
                hint="点「安装」")


def _row(status: str, detail: str, *, fix: str = "", hint: str = "", code: str = "", error: str = "") -> dict[str, Any]:
    return {"item_id": COMPONENT, "status": status, "code": code, "error": error, "detail": detail,
            "fix": fix, "fix_hint": hint}


# --------------------------------------------------------------------------
# 拉起服务端 + 自检
# --------------------------------------------------------------------------

def _start_server(folder: Path, *, ours: bool) -> str:
    """拉起服务端。别人装的：和插件同一规则——有计划任务「CapsWriter Server」就运行它，否则直接启动 exe。
    本程序装的：直接启动。都经 cmd start 中转（procs.spawn_detached），服务端不是任何 Python 的子孙。"""
    exe = folder / SERVER_EXE
    if not windows() or not exe.is_file():
        raise SetupError("SKIPPED.NOT_CONFIGURED", f"没有 {SERVER_EXE}（一键启动目前只支持 Windows）：{folder}")
    import subprocess
    if not ours:
        try:
            r = subprocess.run(["schtasks", "/Run", "/TN", "CapsWriter Server"], capture_output=True, timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                return "计划任务 CapsWriter Server"
        except (OSError, subprocess.SubprocessError):
            pass
    from .. import procs, storage
    log = storage.link_brain_home() / "logs" / "capswriter-server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    procs.spawn_detached([str(exe)], cwd=str(folder), log_path=str(log))
    return str(exe)


def _verify(host: str, port: int, emit: Emit | None) -> dict[str, Any]:
    """等端口打开（服务端在加载模型），再用随包样例真识别一次。返回 R（asr.transcribe 的形状）。"""
    from .. import asr, voice
    started = time.monotonic()
    last_note = 0.0
    while not sysinfo.port_open(host, port):
        waited = time.monotonic() - started
        if waited > START_WAIT_S:
            return {"status": "failed", "code": "TRANSIENT.STEP_TIMEOUT", "text": None,
                    "error": f"服务端 {START_WAIT_S} 秒内没开好端口 {host}:{port}（看 ~/.link-brain/logs/capswriter-server.log）"}
        if waited - last_note >= 5:
            last_note = waited
            progress(emit, COMPONENT, "验证", int(waited), START_WAIT_S, f"等服务端加载模型（{int(waited)} 秒）")
        time.sleep(1.0)
    progress(emit, COMPONENT, "验证", None, None, "服务端已开，识别一段 3 秒样例")
    cfg = {"mode": "capswriter", "host": host, "port": port, "timeoutSec": VERIFY_TIMEOUT_S, "segmentSec": 50,
           "context": "", "language": "auto"}
    return asr.transcribe(voice.SAMPLE, cfg)


def _start_and_verify(folder: Path, det: dict[str, Any], emit: Emit | None, *, ours: bool) -> tuple[str, dict]:
    how = _start_server(folder, ours=ours)
    progress(emit, COMPONENT, "验证", None, None, f"已拉起服务端（{how}）")
    return how, _verify(det["host"], det["port"], emit)


# --------------------------------------------------------------------------
# 安装
# --------------------------------------------------------------------------

def _cleanup_staging() -> None:
    home = install_dir().parent
    if not home.is_dir():
        return
    for p in home.glob("capswriter.staging-*"):
        shutil.rmtree(p, ignore_errors=True)


def _patch_server_config(folder: Path, model_type: str) -> None:
    """只改本程序刚解出来的那份 config_server.py：监听只限本机（上游默认 0.0.0.0 会对局域网开放）、选模型。"""
    cfg = folder / "config_server.py"
    text = cfg.read_text(encoding="utf-8")
    new = re.sub(r"^(\s*addr\s*=\s*)['\"][^'\"]*['\"]", r"\g<1>'127.0.0.1'", text, count=1, flags=re.M)
    new = re.sub(r"^(\s*model_type\s*=\s*)['\"][^'\"]*['\"]", rf"\g<1>'{model_type}'", new, count=1, flags=re.M)
    if f"'{model_type}'" not in new:
        raise SetupError("PERMANENT.BAD_PACKAGE", "发布包里的 config_server.py 找不到 model_type，没法选模型")
    cfg.write_text(new, encoding="utf-8")


def _need_bytes(model: dict[str, Any], downloads: Path) -> int:
    def left(name: str, size: int) -> int:
        for p in (downloads / name, downloads / (name + ".part")):
            if p.exists():
                return max(0, size - p.stat().st_size) if p.suffix == ".part" else 0
        return size
    return (left(PACKAGE["name"], PACKAGE["size"]) + left(model["name"], model["size"])
            + PACKAGE["unpacked"] + model["unpacked"] + DISK_MARGIN)


def _fresh_install(model_key: str, emit: Emit | None) -> dict[str, Any]:
    from .. import storage
    model = MODELS[model_key]
    home = storage.link_brain_home()
    downloads = home / "downloads"
    final = install_dir()
    _cleanup_staging()
    home.mkdir(parents=True, exist_ok=True)
    need = _need_bytes(model, downloads)
    free = shutil.disk_usage(home).free
    if free < need:
        raise SetupError("PERMANENT.DISK_FULL",
                         f"{home} 所在的盘只剩 {mb(free)} MB，装 CapsWriter 还要约 {mb(need)} MB（含下载包和余量）")

    def dl(phase: str, label: str):
        return lambda done, total: progress(emit, COMPONENT, phase, done, total, f"{label} {mb(done)}/{mb(total) if total else '?'} MB")

    def vf(label: str):
        return lambda done, total: progress(emit, COMPONENT, "校验", done, total, f"核对 {label} 的 sha256")

    pkg = fetch.fetch_verified(PACKAGE["url"], downloads / PACKAGE["name"], sha256=PACKAGE["sha256"],
                               size=PACKAGE["size"], on_download=dl("下载", "程序包"), on_verify=vf("程序包"))
    mdl = fetch.fetch_verified(model["url"], downloads / model["name"], sha256=model["sha256"], size=model["size"],
                               on_download=dl("下载模型", model["label"]), on_verify=vf(model["label"]))
    staging = home / f"capswriter.staging-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        progress(emit, COMPONENT, "解压", 0, PACKAGE["unpacked"], "解压程序包")
        fetch.unzip(pkg["path"], staging, strip=PACKAGE["strip"],
                    on_progress=lambda d, t: progress(emit, COMPONENT, "解压", d, t, "解压程序包"))
        if not looks_installed(staging) or not (staging / "config_server.py").is_file():
            raise SetupError("PERMANENT.BAD_PACKAGE", f"程序包里没有 {SERVER_EXE} / config_server.py，不像 CapsWriter-Offline")
        target = staging.joinpath(*model["target"].split("/"))
        progress(emit, COMPONENT, "解压", 0, model["unpacked"], f"解压模型 {model['label']}")
        fetch.unzip(mdl["path"], target, strip=model["strip"],
                    on_progress=lambda d, t: progress(emit, COMPONENT, "解压", d, t, f"解压模型 {model['label']}"))
        missing = missing_model_files(staging, model["model_type"])
        if missing:
            raise SetupError("PERMANENT.BAD_PACKAGE", f"模型包解出来缺文件：{', '.join(missing)}")
        _patch_server_config(staging, model["model_type"])
        (staging / MARKER).write_text(json.dumps({
            "installed_by": "link-brain setup", "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "version": PACKAGE["version"], "package": PACKAGE["name"], "package_sha256": pkg["sha256"],
            "model": model_key, "model_package": model["name"], "model_sha256": mdl["sha256"],
            "source": SOURCE, "license": LICENSE}, ensure_ascii=False, indent=2), encoding="utf-8")
        if final.exists():
            shutil.rmtree(final)  # 只会是本程序自己装坏的那份（调用方已确认 ours）
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    for p in (pkg["path"], mdl["path"]):  # 装好了：下载包删掉，省 1.5 GB
        try:
            p.unlink()
        except OSError:
            pass
    return {"dir": str(final), "package_sha256": pkg["sha256"], "model_sha256": mdl["sha256"]}


def install(emit: Emit | None = None, *, model_key: str = DEFAULT_MODEL) -> dict[str, Any]:
    """setup install --component asr。返回 §1 形状 + status ready|failed + settings_patch + check。"""
    if model_key not in MODELS:
        return _result(False, "SKIPPED.NOT_CONFIGURED", f"不认识的模型：{model_key}（可选 {', '.join(MODELS)}）")
    det = detect()
    if det["server_running"]:
        return _result(True, "", f"CapsWriter 已在运行（{det['host']}:{det['port']}），没动它", det=det, changed=False)
    if det["dir"] and not (det["ours"] and det["model_ok"] is False):
        folder = Path(det["dir"])
        if det["model_ok"] is False:
            return _result(False, "SKIPPED.NOT_CONFIGURED",
                           f"已装的 CapsWriter（{folder}）缺模型文件，没替你改：按它的说明补模型", det=det, changed=False,
                           manual=True)
        try:
            how, r = _start_and_verify(folder, det, emit, ours=det["ours"])
        except SetupError as exc:
            return _result(False, exc.code, exc.message, det=det, changed=False)
        return _verified_result(r, det, f"已装（{det['source']}），拉起服务端（{how}）", changed=False)
    if not windows():
        return _result(False, "SKIPPED.NOT_CONFIGURED", f"一键安装目前只支持 Windows：按 {REPO} 的说明手动装",
                       det=det, changed=False, manual=True)
    if not (PACKAGE.get("url") and PACKAGE.get("sha256")):
        return _result(False, "SKIPPED.NOT_CONFIGURED", f"CapsWriter 发布地址没配置：到 {REPO}/releases 手动下载",
                       det=det, changed=False, manual=True)
    from .. import storage
    try:
        with storage.file_lock("setup-capswriter", wait_s=0, owner="安装 CapsWriter"):
            info = _fresh_install(model_key, emit)
            port = _fresh_port(Path(info["dir"]))
            patch = {"asrAI": {"mode": "capswriter", "host": "127.0.0.1", "port": str(port)},
                     "voice": {"capsWriterDir": info["dir"]}}
            written = apply_settings_patch(patch)
            det = detect()
            det["host"], det["port"] = "127.0.0.1", port
            how, r = _start_and_verify(Path(info["dir"]), det, emit, ours=True)
    except storage.LockBusy:
        return _result(False, "TRANSIENT.SERVICE_BUSY", "另一个 CapsWriter 安装正在进行，等它装完", det=det, changed=False)
    except SetupError as exc:
        return _result(False, exc.code, exc.message, det=det, changed=False)
    out = _verified_result(r, det, f"装好了：{info['dir']}，拉起服务端（{how}）", changed=True)
    out["settings_patch"] = patch
    out["settings_written"] = written
    out["installed"] = {"dir": info["dir"], "version": PACKAGE["version"], "model": MODELS[model_key]["label"],
                        "package_sha256": info["package_sha256"], "model_sha256": info["model_sha256"]}
    return out


def _fresh_port(folder: Path) -> int:
    from .. import providers
    return providers.capswriter_port({"capsWriterDir": str(folder)})


def _verified_result(r: dict[str, Any], det: dict[str, Any], what: str, *, changed: bool) -> dict[str, Any]:
    if r.get("status") == "ok":
        heard = (r.get("text") or "").strip()
        return _result(True, "", f"{what}；样例识别通过" + (f"：「{heard[:30]}」" if heard else "（样例没识别出字，但服务端正常回包）"),
                       det=det, changed=changed)
    return _result(False, r.get("code") or "TRANSIENT.NETWORK", f"{what}；但自检没过：{r.get('error') or r.get('status')}",
                   det=det, changed=changed)


def _result(ok: bool, code: str, message: str, *, det: dict[str, Any] | None = None, changed: bool = False,
            manual: bool = False) -> dict[str, Any]:
    out = {"ok": ok, "code": code, "message": message, "component": COMPONENT,
           "status": "ready" if ok else "failed", "changed": changed, "manual": manual}
    if det is not None:
        out["capswriter"] = {k: det.get(k) for k in ("dir", "source", "ours", "host", "port", "model_type", "model_ok")}
    return out


def release_info() -> dict[str, Any]:
    return {"repo": REPO, "license": LICENSE, "checked": CHECKED, "source": SOURCE,
            "package": {k: PACKAGE[k] for k in ("version", "name", "url", "size", "sha256", "unpacked")},
            "models": {k: {x: v[x] for x in ("label", "name", "url", "size", "sha256", "unpacked", "model_type")}
                       for k, v in MODELS.items()},
            "default_model": DEFAULT_MODEL}


if __name__ == "__main__":  # pragma: no cover
    json.dump(detect(), sys.stdout, ensure_ascii=False, indent=2, default=str)

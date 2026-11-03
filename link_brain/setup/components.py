"""「开始」页的功能清单：每项的磁盘 / 内存占用（带依据）、检查、安装。

磁盘：装了的现量（目录 / Python 包按文件逐个 stat，跟着目录联接走）；没装的按官方发布包 / 模型文件大小。
内存：本机进程实测（CapsWriter 服务端 / 客户端在跑就现量它们的峰值工作集）；量不到的用下面 RAM_MEASURED
里 2026-10-03 在开发机上实测的典型值（量法写在每条旁边），没法量的写明是估计。
"""
from __future__ import annotations
from ..errtext import errtext

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .. import extras
from . import capswriter, fetch, sysinfo
from .common import Emit, SetupError, apply_settings_patch, mb, progress

# 2026-10-03 开发机（Windows 10，Python 3.14，rapidocr 3.9.2，onnxruntime CPU）实测，单位 MB：
RAM_MEASURED = {
    # 一个 Python 进程 import 归档 / 目录 / 检索 / 问答 / 同步 / MCP 模块并初始化 jieba 词典后的 RSS
    "core": 151,
    # 临时进程里真加载 PP-OCRv6 + 认一张 1080×1440 的图：识别时峰值工作集（认完常驻 medium 278 / small 175）
    "ocr_medium": 672, "ocr_small": 397,
    # CapsWriter 客户端（start_client.exe）峰值工作集
    "capswriter_client": 143,
    # CapsWriter 服务端（3 个 start_server.exe 进程）峰值工作集之和，模型是 Qwen3-ASR-1.7B（模型目录 2009 MB）
    "capswriter_server": 2187, "capswriter_server_model_mb": 2009,
    # 读取服务 link-brain-reader 空闲时（读收藏时另开浏览器，没实测：开发中不许启动读取服务）
    "reader_idle": 20,
}
READER_BROWSER_EST = 300  # 估计：读收藏时开的无界面浏览器（Chromium 单标签页常见 250–400 MB），没实测
READER_EXE_MB = 27        # 发布包 reader-v0.2.0 解出来的实量：link-brain-reader.exe 16.0 MB + relatedfile.exe 10.7 MB
READER_QUARANTINE_HINT = "；可能被杀毒软件隔离，去 Windows 安全中心恢复并加入排除"

# pyproject 的依赖（发行名 → import 名 / 依赖说明），1102 起从包元数据推（link_brain/extras.py，唯一来源）：
# core = pyproject 的 dependencies；ocr = extra `ocr`（B 站 / PDF·Word 的 extra 没有对应的功能项，缺了在用到那一步提示）。
CORE_REQS = extras.import_map("")
CORE_SPECS = extras.spec_map("")
OCR_REQS = extras.import_map("ocr")
OCR_SPECS = extras.spec_map("ocr")

COMPONENTS: list[dict[str, Any]] = [
    {"id": "core", "name": "归档·同步·浏览·关键词搜索", "desc": "把收藏存成 Obsidian 笔记、目录页、关键词搜索；不要任何 key。",
     "required": True, "default": True, "needs_key": False, "local": True, "depends": [], "settings_tab": "sync"},
    {"id": "reader", "name": "读取组件（读小红书收藏 / 评论 / 附件）", "desc": "本机的读取服务，用你扫码登录的号读收藏。",
     "required": True, "default": True, "needs_key": False, "local": True, "depends": ["core"], "settings_tab": "sync"},
    {"id": "ocr", "name": "本地 OCR（图片里的字）", "desc": "RapidOCR + PP-OCRv6，在本机认图里的字，免费、不出电脑。",
     "required": False, "default": True, "needs_key": False, "local": True, "depends": ["core"], "settings_tab": "ai"},
    {"id": "asr", "name": "本地语音识别（CapsWriter，视频转写 / 语音提问）",
     "desc": "CapsWriter-Offline 本机识别服务（MIT），视频转文字、问 AI 用语音提问；免费、离线。",
     "required": False, "default": True, "needs_key": False, "local": True, "depends": ["core"], "settings_tab": "ai"},
    {"id": "capslock", "name": "CapsLock 语音输入", "desc": "CapsWriter 客户端：任何程序里按住 CapsLock 说话，松开出字。",
     "required": False, "default": True, "needs_key": False, "local": True, "depends": ["asr"], "settings_tab": "ai"},
    {"id": "ai_text", "name": "AI 问答 · 概要 · 打标（要 API key）", "desc": "问收藏、每篇概要和标签；要自备文本模型的 key。",
     "required": False, "default": False, "needs_key": True, "local": False, "depends": ["core"], "settings_tab": "ai"},
    {"id": "ai_vision", "name": "识图（要 API key）", "desc": "表格、流程图、截图按图转写纠错；要自备识图模型的 key。",
     "required": False, "default": False, "needs_key": True, "local": False, "depends": ["ocr"], "settings_tab": "ai"},
    {"id": "remote", "name": "远程阅读（MCP，高级，要自备域名）", "desc": "让手机 / 网页端的 AI 读你的收藏；要自己的域名和隧道。",
     "required": False, "default": False, "needs_key": False, "local": True, "later": True, "depends": ["core"],
     "settings_tab": "remote"},
]
IDS = [c["id"] for c in COMPONENTS]
# 1102：不再需要的功能 id（老设置的 setup.selected 里可能还有）：check / install 当它不存在，不报「不认识」
# dataview：页面改成 ```lb-page 块、由 LWA 插件自己显示（page-host.js），不再要 Dataview
RETIRED = {"dataview": "不再需要 Dataview：目录页等由 LWA 插件自己显示"}
PRESETS = {
    "light": ["core", "reader", "ocr"],
    "recommended": ["core", "reader", "ocr", "asr", "capslock", "ai_text"],
    "full": list(IDS),
}
TOTALS_BASIS = ("磁盘 / 内存是估计值：装了的按本机实际占用量（目录和 Python 包逐个文件算，CapsWriter 服务端在跑就量它的峰值内存）；"
                "没装的磁盘按官方发布包 / 模型解压后的大小，内存按 2026-10-03 在一台 Windows 开发机上加载后实测的典型值；"
                "要 key 的两项在云端跑，本机不占。内存不会全部同时占满：OCR 只在处理图片时加载，用完随进程退出。")


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _package_dir() -> Path:
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# 每项：占用 + 检查
# --------------------------------------------------------------------------

def _core() -> dict[str, Any]:
    missing = [d for d, m in CORE_REQS.items() if not _has(m)]
    deps, _ = sysinfo.dist_bytes(list(CORE_REQS), exclude=set(OCR_REQS))
    own = sysinfo.dir_bytes(_package_dir())
    py_ok = sys.version_info >= (3, 11)
    disk = {"disk_mb": mb(own + deps), "ram_mb": RAM_MEASURED["core"],
            "basis": f"磁盘：本机 link_brain 程序 {mb(own)} MB + 依赖包（含传递依赖，不含 OCR 两个包）{mb(deps)} MB，按已装文件实量；"
                     f"内存：一个后端 Python 进程载入模块和分词词典后实测约 {RAM_MEASURED['core']} MB"}
    if not py_ok:
        row = _row("core", "failed", f"Python 版本 {sys.version.split()[0]} 太旧，要 3.11 以上", fix="manual",
                   hint="到 Link Brain 设置页顶部点「一键装好」重装后端（自带 Python 3.12，不用另装）")
    elif missing:
        row = _row("core", "partial", f"缺 Python 依赖：{', '.join(missing)}", fix="auto", hint="点「安装」用 pip 补装")
    else:
        row = _row("core", "ready", "后端程序和依赖都在")
    return {**disk, "installed": py_ok and not missing, "row": row}


def _ocr_model_files(tier: str, model_dir: str) -> tuple[Path, list[Path]]:
    if model_dir:
        root = Path(model_dir)
    else:
        spec = importlib.util.find_spec("rapidocr")
        root = Path(spec.origin).parent / "models" if spec and spec.origin else Path()
    files = [root / f"PP-OCRv6_det_{tier}.onnx", root / f"PP-OCRv6_rec_{tier}.onnx"]
    return root, files


def _ocr_settings() -> tuple[str, str, str]:
    """(档位, 模型目录, 模式)。"""
    try:
        from .. import ai_config
        cfg = ai_config.load().get("ocr") or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    tier = str(cfg.get("modelTier") or "medium").strip().lower()
    if tier not in ("tiny", "small", "medium"):
        tier = "medium"
    return tier, str(cfg.get("modelDir") or "").strip(), str(cfg.get("mode") or "local")


def ocr_release_models(tier: str = "medium") -> list[dict[str, Any]]:
    """rapidocr 自带的模型清单（default_models.yaml，onnxruntime 段）里 PP-OCRv6 该档 det / rec 的官方地址和 sha256。"""
    import yaml
    spec = importlib.util.find_spec("rapidocr")
    if not spec or not spec.origin:
        return []
    try:
        data = yaml.safe_load((Path(spec.origin).parent / "default_models.yaml").read_text(encoding="utf-8"))
        v6 = data["onnxruntime"]["PP-OCRv6"]
        out = []
        for part in ("det", "rec"):
            info = v6[part][f"multi_PP-OCRv6_{part}_{tier}"]
            out.append({"part": part, "url": info["model_dir"], "sha256": str(info.get("SHA256") or "").lower(),
                        "name": f"PP-OCRv6_{part}_{tier}.onnx"})
        return out
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        return []


OCR_MEDIUM_BYTES = 62119454 + 76629984  # PP-OCRv6 medium det + rec（开发机上 rapidocr 3.9.2 官方下载的两个 onnx 实量）


def _ocr() -> dict[str, Any]:
    tier, model_dir, _mode = _ocr_settings()
    pkgs_ok = all(_has(m) for m in OCR_REQS.values())
    pkg_bytes, _ = sysinfo.dist_bytes(list(OCR_REQS), transitive=False)
    root, files = _ocr_model_files(tier, model_dir)
    models_ok = tier == "small" and not model_dir or all(f.is_file() for f in files)
    model_bytes = sum(f.stat().st_size for f in files if f.is_file()) if (model_dir or tier != "small") else 0
    if not model_bytes and tier == "medium":
        model_bytes = OCR_MEDIUM_BYTES
    ram = RAM_MEASURED["ocr_medium"] if tier == "medium" else RAM_MEASURED["ocr_small"]
    basis = (f"磁盘：rapidocr + onnxruntime 两个包 {mb(pkg_bytes)} MB（已装的实量）+ PP-OCRv6 {tier} 档模型 {mb(model_bytes)} MB"
             f"{'（实量）' if models_ok and model_bytes else '（按官方模型文件大小）'}；"
             f"内存：临时进程里加载 {tier} 档认一张 1080×1440 图的峰值实测约 {ram} MB，只在处理图片时占用")
    if not pkgs_ok:
        row = _row("ocr", "missing", "没装 rapidocr / onnxruntime", fix="auto",
                   hint=f"点「安装」用 pip 补装，或自己装：{extras.install_hint('ocr')}")
    # 1103：check 只答「装没装」——设置里关着（mode == "off"）不算没装好，开没开由界面按设置自己判断
    elif sys.platform == "win32" and not _vc_runtime_ok():
        row = _row("ocr", "partial", "这台电脑缺 VC++ 运行库（msvcp140.dll），OCR 加载不了", fix="auto",
                   hint="点「安装」自动补装（约 2 MB）")
    elif not models_ok:
        where = f"设置里的模型目录 {model_dir}" if model_dir else "rapidocr 的模型目录"
        row = _row("ocr", "partial", f"PP-OCRv6 {tier} 档模型还没下（{where}）；第一次用时会自动下载",
                   fix="auto", hint="点「安装」现在就下（约 139 MB，带官方 sha256 校验）")
    else:
        row = _row("ocr", "ready", f"本地 OCR 可用（PP-OCRv6 {tier}{'，模型目录 ' + model_dir if model_dir else ''}）")
    return {"disk_mb": mb(pkg_bytes + model_bytes), "ram_mb": ram, "basis": basis,
            "installed": pkgs_ok and models_ok, "row": row}


def _asr_sizes(det: dict[str, Any]) -> tuple[int, int, str]:
    servers = [p for p in det.get("processes") or [] if p.get("peak_ws")]
    model = capswriter.MODELS[capswriter.DEFAULT_MODEL]
    if det.get("dir"):
        disk = sysinfo.dir_bytes(det["dir"])
        disk_note = f"已装目录 {det['dir']} 实量（含模型；目录联接跟进）"
    else:
        disk = capswriter.PACKAGE["unpacked"] + model["unpacked"]
        disk_note = (f"官方 {capswriter.PACKAGE['version']} 程序包解压后 {mb(capswriter.PACKAGE['unpacked'])} MB + "
                     f"{model['label']} 模型解压后 {mb(model['unpacked'])} MB（另需临时下载 "
                     f"{mb(capswriter.PACKAGE['size'] + model['size'])} MB，装完删掉）")
    if servers:
        ram = sum(p["peak_ws"] for p in servers)
        ram_note = f"正在运行的 {len(servers)} 个服务端进程峰值工作集之和实量"
    else:
        overhead = RAM_MEASURED["capswriter_server"] - RAM_MEASURED["capswriter_server_model_mb"]
        ram = (model["unpacked"] >> 20) + overhead
        ram_note = (f"按模型大小 {mb(model['unpacked'])} MB + 运行开销约 {overhead} MB 估（开销取自开发机上 "
                    f"Qwen3-ASR-1.7B 服务端实测 {RAM_MEASURED['capswriter_server']} MB 减模型 "
                    f"{RAM_MEASURED['capswriter_server_model_mb']} MB）")
        return disk, ram << 20, f"磁盘：{disk_note}；内存：{ram_note}，服务端常驻"
    return disk, ram, f"磁盘：{disk_note}；内存：{ram_note}，服务端常驻"


def _asr(det: dict[str, Any]) -> dict[str, Any]:
    disk, ram, basis = _asr_sizes(det)
    row = capswriter.check(det)
    return {"disk_mb": mb(disk), "ram_mb": mb(ram), "basis": basis, "installed": bool(det.get("dir")), "row": row}


def _capslock(det: dict[str, Any]) -> dict[str, Any]:
    clients = [p for p in sysinfo.processes_named(capswriter.CLIENT_EXE) if p.get("peak_ws")] if os.name == "nt" else []
    if clients:
        ram, ram_note = mb(sum(p["peak_ws"] for p in clients)), "正在运行的客户端峰值工作集实量"
    else:
        ram, ram_note = RAM_MEASURED["capswriter_client"], f"开发机上客户端峰值工作集实测约 {RAM_MEASURED['capswriter_client']} MB"
    basis = f"磁盘：客户端在 CapsWriter 同一个包里，不另占；内存：{ram_note}，开着 CapsLock 语音时常驻"
    if det.get("client_exe"):
        # 1103：check 只答「装没装」——设置里 CapsLock 语音关着不算没装好
        detail = "客户端在" + ("（正在运行）" if clients else "（插件开着 CapsLock 语音时自动拉起）")
        row = _row("capslock", "ready", detail)
    elif det.get("dir"):
        row = _row("capslock", "missing", f"CapsWriter 目录里没有 {capswriter.CLIENT_EXE}：{det['dir']}", fix="manual",
                   hint="用 CapsWriter 的完整包（含客户端）")
    else:
        row = _row("capslock", "missing", "要先装本地语音识别（CapsWriter），客户端在同一个包里", fix="auto",
                   hint="点「安装」会连同语音识别一起装")
    return {"disk_mb": 0, "ram_mb": ram, "basis": basis, "installed": bool(det.get("client_exe")), "row": row}


def _reader() -> dict[str, Any]:
    from .. import reader_install
    st = reader_install.status()
    files = [p for p in (st.get("reader"), st.get("relatedfile")) if p]
    size = sum(Path(p).stat().st_size for p in files if Path(p).is_file())
    disk = mb(size) if size else READER_EXE_MB
    basis = (f"磁盘：{'已装的读取组件实量' if size else '发布包里 link-brain-reader + relatedfile 的实量'}；"
             f"内存：读取服务空闲约 {RAM_MEASURED['reader_idle']} MB（实量），读收藏时另开无界面浏览器，按约 "
             f"{READER_BROWSER_EST} MB 估（没实测）")
    if st.get("reader"):
        row = _row("reader", "ready", f"读取组件在：{st['reader']}")
    elif st.get("release_configured"):
        row = _row("reader", "missing", "还没装读取组件", fix="auto", hint="点「安装」下载并校验")
    else:
        row = _row("reader", "missing", "还没装读取组件；发布地址还没配置（测试版）", fix="manual",
                   hint=f"把 link-brain-reader.exe（和 relatedfile.exe）放进 {st.get('bin_dir')}")
    return {"disk_mb": disk, "ram_mb": RAM_MEASURED["reader_idle"] + READER_BROWSER_EST, "basis": basis,
            "installed": bool(st.get("reader")), "row": row}


def _ai(item: str) -> dict[str, Any]:
    from .. import ai_config, providers
    cap = "textAI" if item == "ai_text" else "visionAI"
    try:
        settings = ai_config.load()
        cfg = providers.resolve(cap, ai_config.with_model(settings) if cap == "textAI" else settings)
    except Exception:  # noqa: BLE001
        cfg = None
    label = "文本 AI" if cap == "textAI" else "识图"
    if cfg:
        row = _row(item, "ready", f"{label}已配置（{cfg.get('model') or cfg.get('mode')}；没调用验证，⑤ 里「试问一句」验）")
    elif providers.gate(cap, settings)['gated']:
        row = _row(item, 'not_selected', f'已填好，但「开始」页没勾「{label}」，现在不会跑')
    else:
        # 要 key 的项不算「没装好」：前端放在 ⑤ 填 key，② 一键检查不被它拖住（status 单列 needs_key）
        row = _row(item, "needs_key", f"{label}没配 key（不填也能用归档、浏览、关键词搜索、本地 OCR、本地语音）", fix="manual",
                   hint="在第 ⑤ 步填接口和 key")
    return {"disk_mb": 0, "ram_mb": 0, "basis": "在云端跑，本机不占磁盘和内存（只有请求时的网络流量）",
            "installed": bool(cfg), "row": row}


def _remote() -> dict[str, Any]:
    try:
        from ..remote import config as rconfig
        cfg, _errors = rconfig.load()
    except Exception:  # noqa: BLE001
        cfg = {}
    ready = bool(cfg.get("enabled")) and bool(cfg.get("domain"))
    row = (_row("remote", "ready", f"远程阅读已开（{cfg.get('domain')}）") if ready else
           _row("remote", "missing", "远程阅读没开（高级，要自备域名和隧道）", fix="manual", hint="到「远程阅读」分页按说明开"))
    return {"disk_mb": 0, "ram_mb": RAM_MEASURED["core"],
            "basis": f"磁盘：随后端程序一起，不另占；内存：开着时多一个后端进程，按后端实测约 {RAM_MEASURED['core']} MB 计",
            "installed": ready, "row": row}


def _row(item: str, status: str, detail: str, *, fix: str = "", hint: str = "", code: str = "",
         error: str = "") -> dict[str, Any]:
    if status in ("ready",):
        fix, hint = "", ""
    return {"item_id": item, "status": status, "code": code, "error": error, "detail": detail, "fix": fix,
            "fix_hint": hint}


def evaluate(ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """{id: {disk_mb, ram_mb, basis, installed, row}}，只读。CapsWriter 只探一次。"""
    ids = ids or IDS
    det = capswriter.detect() if {"asr", "capslock"} & set(ids) else {}
    out = {}
    for cid in ids:
        try:
            if cid == "core":
                out[cid] = _core()
            elif cid == "ocr":
                out[cid] = _ocr()
            elif cid == "asr":
                out[cid] = _asr(det)
            elif cid == "capslock":
                out[cid] = _capslock(det)
            elif cid == "reader":
                out[cid] = _reader()
            elif cid in ("ai_text", "ai_vision"):
                out[cid] = _ai(cid)
            elif cid == "remote":
                out[cid] = _remote()
        except Exception as exc:  # noqa: BLE001 - 一项检查出错不挡其余（CONVENTIONS §1.3）
            out[cid] = {"disk_mb": None, "ram_mb": None, "basis": "检查出错，量不到", "installed": False,
                        "row": _row(cid, "failed", "检查出错", code="TRANSIENT.STEP_CRASHED",
                                    error=errtext(exc), fix="manual", hint="把这句错误发给开发者")}
    return out


def plan() -> dict[str, Any]:
    ev = evaluate()
    comps = []
    for c in COMPONENTS:
        e = ev[c["id"]]
        row = e["row"]
        comps.append({**c, "check_only": bool(c.get("check_only")), "later": bool(c.get("later")),
                      "disk_mb": e["disk_mb"], "ram_mb": e["ram_mb"], "basis": e["basis"],
                      "installed": e["installed"], "status": "unknown" if row["status"] == "failed" else row["status"],
                      "detail": row["detail"]})
    return {"ok": True, "code": "", "message": f"{len(comps)} 项功能", "components": comps, "presets": PRESETS,
            "totals_basis": TOTALS_BASIS, "capswriter_release": capswriter.release_info()}


def check(ids: list[str] | None = None) -> dict[str, Any]:
    retired = [i for i in ids or [] if i in RETIRED]
    if ids:
        ids = [i for i in ids if i not in RETIRED]
    bad = [i for i in ids or [] if i not in IDS]
    ev = evaluate([i for i in (ids if ids or retired else IDS) if i in IDS])   # 只问了退役项 = 什么也不查
    results = [ev[i]["row"] for i in ev]
    results += [_row(i, "failed", "不认识这一项", code="SKIPPED.NOT_CONFIGURED", error=f"可选：{', '.join(IDS)}")
                for i in bad]
    failed = [r for r in results if r["status"] == "failed"]
    # all_ready：要 key 的项（needs_key，留到 ⑤）不拖住整体
    ready = all(r["status"] in ("ready", "needs_key") for r in results)
    if bad:
        message = f"不认识：{'、'.join(bad)}（可选 {', '.join(IDS)}）"
    else:
        message = "全部就绪" if ready else ("、".join(r["item_id"] for r in results
                                                 if r["status"] not in ("ready", "needs_key")) + " 还没好")
    return {"ok": not failed, "code": failed[0]["code"] if failed else "", "message": message, "all_ready": ready,
            "results": results}


# --------------------------------------------------------------------------
# 安装
# --------------------------------------------------------------------------

# 1102 托管模式：插件「一键装好」把 uv 放在 ~/.link-brain/bin/，后端环境是 uv 建的 venv（没有 pip）——补装依赖用它。
MANAGED_UV_HINT = "后端环境里没有 pip，也没找到 ~/.link-brain/bin 下的 uv：到 Link Brain 设置页顶部点「一键装好」装后端（会一起装上 uv），或在终端里 pip install 这几个包"
# pip / uv 输出里认失败原因（CONVENTIONS §2：装不上的包 = PERMANENT，网络 = TRANSIENT）
_BAD_PACKAGE_MARKS = ("Failed building wheel", "No matching distribution", "requires a different Python",
                      "No solution found", "has no wheels with a matching")
_NETWORK_MARKS = ("ConnectionError", "ReadTimeout", "ProxyError", "ConnectTimeout", "NewConnectionError",
                  "Failed to fetch", "error sending request", "Temporary failure in name resolution")


def managed_uv() -> Path | None:
    """`~/.link-brain/bin/uv(.exe)`（插件 backend-install.js 下载的那一个）；没有 = None。"""
    from .. import storage
    exe = storage.link_brain_home() / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")
    return exe if exe.is_file() else None


def classify_install_failure(lines: list[str], code: int | None = None) -> tuple[str, str]:
    """pip / uv 输出的尾巴 → (故障码, 给人看的一句)。包不对 / Python 版本不符 → PERMANENT.BAD_PACKAGE；连不上 → TRANSIENT.NETWORK；
    认不出的按网络（以前就是这样：装依赖失败最常见的原因是网，重试还有机会）。"""
    text = "\n".join(lines)
    last = next((ln for ln in reversed(lines) if ln.strip()), "") or f"退出码 {code}"
    if any(m in text for m in _BAD_PACKAGE_MARKS):
        return "PERMANENT.BAD_PACKAGE", "依赖装不上（这个包在这台电脑 / 这个 Python 版本上没有能装的版本）：" + last
    if any(m in text for m in _NETWORK_MARKS):
        return "TRANSIENT.NETWORK", "下载依赖时网络不通：" + last
    return "TRANSIENT.NETWORK", "pip 安装没成功：" + last


def _pip_install(component: str, specs: list[str], emit: Emit | None) -> None:
    """往当前 Python 补装依赖：有 ~/.link-brain/bin/uv 用 `uv pip install --python <当前解释器>`（uv 建的环境没有 pip）；
    没有 uv 但有 pip 用 pip；两个都没有如实说 uv 从哪来（设置页「一键装好」）。失败按输出分类（classify_install_failure）。"""
    if not specs:
        return
    uv = managed_uv()
    if uv is not None:
        cmd = [str(uv), "pip", "install", "--python", sys.executable, *specs]
        shown = "uv pip install " + " ".join(specs)
    elif _has("pip"):
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *specs]
        shown = "pip install " + " ".join(specs)
    else:
        raise SetupError("SKIPPED.NOT_CONFIGURED", MANAGED_UV_HINT)
    progress(emit, component, "安装", 0, len(specs), shown)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=flags)
    tail: list[str] = []
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if line:
                tail = (tail + [line])[-5:]
                progress(emit, component, "安装", None, None, line[:200])
        code = proc.wait(timeout=1800)
    except BaseException:
        from .. import procs
        procs.kill_tree(proc.pid)
        raise
    if code != 0:
        raise SetupError(*classify_install_failure(tail, code))


def _install_core(emit: Emit | None) -> dict[str, Any]:
    missing = [CORE_SPECS[d] for d, m in CORE_REQS.items() if not _has(m)]
    _pip_install("core", missing, emit)
    importlib.invalidate_caches()
    return {"message": f"补装了 {len(missing)} 个依赖" if missing else "依赖都在，没装东西", "changed": bool(missing)}


def _install_ocr(emit: Emit | None) -> dict[str, Any]:
    from .. import storage
    changed = False
    missing = [OCR_SPECS[d] for d, m in OCR_REQS.items() if not _has(m)]
    if missing:
        _pip_install("ocr", missing, emit)
        importlib.invalidate_caches()
        changed = True
    tier, model_dir, _mode = _ocr_settings()
    patch: dict[str, Any] = {}
    root, files = _ocr_model_files(tier, model_dir)
    need_models = not (tier == "small" and not model_dir) and not all(f.is_file() for f in files)
    if need_models:
        models = ocr_release_models(tier)
        if len(models) != 2:
            raise SetupError("SKIPPED.NOT_CONFIGURED", f"rapidocr 的模型清单里找不到 PP-OCRv6 {tier} 档地址：在设置里改用 small 档或手动下模型")
        target = Path(model_dir) if model_dir else storage.link_brain_home() / "models" / "rapidocr"
        with storage.file_lock("setup-ocr", wait_s=0, owner="下载 OCR 模型"):
            for m in models:
                dest = target / m["name"]
                fetch.fetch_verified(
                    m["url"], dest, sha256=m["sha256"] or None, size=None,
                    on_download=lambda d, t, n=m["name"]: progress(emit, "ocr", "下载模型", d, t, f"{n} {mb(d)} MB"),
                    on_verify=lambda d, t, n=m["name"]: progress(emit, "ocr", "校验", d, t, f"核对 {n} 的 sha256"))
        if not model_dir:
            patch = {"ocr": {"modelDir": str(target)}}
            model_dir = str(target)
        changed = True
    if _ensure_vc_runtime(emit):
        changed = True
    progress(emit, "ocr", "验证", None, None, "加载 OCR 模型认一张测试图")
    _ocr_selftest(tier, model_dir)
    msg = (f"本地 OCR 可用（PP-OCRv6 {tier}）" + ("，模型已下好" if need_models else ""))
    return {"message": msg, "changed": changed, "settings_patch": patch}


VC_RUNTIME_SPEC = "msvc-runtime>=14.40"


def _vc_runtime_ok() -> bool:
    """msvcp140.dll 加载得上（System32 里有，或 link_brain 启动时已把 sys.prefix 加进 DLL 搜索路径）。"""
    import ctypes
    try:
        ctypes.WinDLL("msvcp140.dll")
        return True
    except OSError:
        return False


def _ensure_vc_runtime(emit: Emit | None) -> bool:
    """1103 干净 Win11 实测：没装 VC++ 运行库时 pyclipper（rapidocr 依赖）导入报 DLL load failed。
    缺就装 PyPI 的 msvc-runtime（微软可再分发 DLL，约 2 MB，落在 sys.prefix），再把 sys.prefix 加进 DLL 搜索路径。
    不用系统级 vc_redist.exe：要管理员权限、要弹 UAC。返回这次装了没有。"""
    if sys.platform != "win32" or _vc_runtime_ok():
        return False
    progress(emit, "ocr", "补运行库", None, None, "这台电脑没有 VC++ 运行库，补装 msvc-runtime（约 2 MB）")
    _pip_install("ocr", [VC_RUNTIME_SPEC], emit)
    if os.path.isfile(os.path.join(sys.prefix, "msvcp140.dll")):
        import link_brain
        if link_brain._VC_RUNTIME_DIR is None:
            link_brain._VC_RUNTIME_DIR = link_brain._add_vc_runtime_dir()
    if not _vc_runtime_ok():
        raise SetupError("PERMANENT.BAD_PACKAGE", "装了 VC++ 运行库还是加载不上：到微软官网装「Visual C++ 可再发行程序包（x64）」后再点一次")
    return True


def _ocr_selftest(tier: str, model_dir: str) -> None:
    import tempfile
    from PIL import Image, ImageDraw
    try:
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import ModelType, OCRVersion
    except ImportError as exc:
        raise SetupError("SKIPPED.NOT_CONFIGURED", f"rapidocr 导入失败：{exc}") from exc
    params = {"Global.log_level": "warning", "Det.ocr_version": OCRVersion.PPOCRV6, "Rec.ocr_version": OCRVersion.PPOCRV6,
              "Det.model_type": ModelType(tier), "Rec.model_type": ModelType(tier)}
    if model_dir:
        params.update({"Det.model_path": str(Path(model_dir) / f"PP-OCRv6_det_{tier}.onnx"),
                       "Rec.model_path": str(Path(model_dir) / f"PP-OCRv6_rec_{tier}.onnx")})
    with tempfile.TemporaryDirectory(prefix="lb-ocr-") as tmp:
        img = Image.new("RGB", (640, 160), "white")
        ImageDraw.Draw(img).text((20, 60), "OCR self test 12345", fill="black")
        path = Path(tmp) / "t.png"
        img.save(path)
        try:
            got = RapidOCR(params=params)(str(path))
        except Exception as exc:  # noqa: BLE001
            raise SetupError("PERMANENT.BAD_PACKAGE", f"OCR 模型加载 / 识别失败：{errtext(exc)}") from exc
    if not any("12345" in str(t) or "test" in str(t).lower() for t in (got.txts or ())):
        raise SetupError("PERMANENT.MODEL_OUTPUT_INVALID", f"OCR 能跑但测试图没认对：{list(got.txts or ())[:3]}")


def _install_reader(emit: Emit | None) -> dict[str, Any]:
    from .. import reader_install
    st = reader_install.status()
    if st.get("reader"):
        return {"message": "读取组件已在，没动它", "changed": False}
    if not st.get("release_configured"):
        raise SetupError("SKIPPED.NOT_CONFIGURED",
                         f"读取组件的发布地址还没配置（测试版）：把 link-brain-reader.exe 放进 {st.get('bin_dir')}")
    progress(emit, "reader", "下载", None, None, "下载读取组件")
    # 1102：reader_install 走 setup.fetch（.part 续传、分块进度事件、sha256 过了才改名、GitHub 地址先试配置的镜像）
    out = reader_install.install(emit=emit)
    if not out.get("ok"):
        raise SetupError(out.get("code") or "TRANSIENT.NETWORK", out.get("message") or "读取组件没装上")
    return {"message": out.get("message") or "读取组件已装好", "changed": True}


def install(component: str, emit: Emit | None = None, *, asr_model: str = capswriter.DEFAULT_MODEL) -> dict[str, Any]:
    """装一项，装完再 check 一遍写进结果。返回 {type:result, ok, code, message, component, status, check, ...}。"""
    if component in RETIRED:
        return _final(component, True, "", RETIRED[component])
    if component not in IDS:
        return _final(component, False, "SKIPPED.NOT_CONFIGURED", f"不认识的功能：{component}（可选 {', '.join(IDS)}）")
    extra: dict[str, Any] = {}
    try:
        if component in ("asr", "capslock"):
            out = capswriter.install(emit, model_key=asr_model)
            out.pop("status", None)
            extra = {k: v for k, v in out.items() if k not in ("ok", "code", "message", "component")}
            if component == "capslock" and out["ok"] and "settings_patch" in out:
                out["settings_patch"].setdefault("voice", {})["capsLock"] = True
                apply_settings_patch({"voice": {"capsLock": True}})
            ok, code, message = out["ok"], out["code"], out["message"]
            if component == "capslock" and ok:
                message += "；CapsLock 语音由插件在开着时拉起客户端"
        elif component in ("ai_text", "ai_vision", "remote"):
            row = evaluate([component])[component]["row"]
            if row["status"] == "ready":
                ok, code, message = True, "", row["detail"]
            else:
                ok, code, message = False, "SKIPPED.NOT_CONFIGURED", f"{row['detail']}：{row['fix_hint']}"
                extra["manual"] = True
        else:
            fn = {"core": _install_core, "ocr": _install_ocr, "reader": _install_reader}[component]
            got = fn(emit)
            ok, code, message = True, "", got["message"]
            extra["changed"] = got.get("changed", False)
            if got.get("settings_patch"):
                extra["settings_patch"] = got["settings_patch"]
                extra["settings_written"] = apply_settings_patch(got["settings_patch"])
    except SetupError as exc:
        ok, code, message = False, exc.code, exc.message
        extra.setdefault("manual", exc.code == "SKIPPED.NOT_CONFIGURED")
    except Exception as exc:  # noqa: BLE001
        ok, code, message = False, "TRANSIENT.STEP_CRASHED", f"安装出错：{errtext(exc)}"
    return _final(component, ok, code, message, **extra)


def _final(component: str, ok: bool, code: str, message: str, **extra: Any) -> dict[str, Any]:
    after = check([component]) if component in IDS else {"results": []}
    row = (after.get("results") or [None])[0]
    if ok and row and row["status"] != "ready":
        ok, code = False, code or "TRANSIENT.STEP_CRASHED"
        message = f"{message}；但装完再检查还不是就绪：{row['detail']}"
        if component == "reader":
            # 1102：读取组件「刚装好又不见了」在 Windows 上多半是杀毒软件把 exe 隔离了（Go 编译的服务常被误报）
            message += READER_QUARANTINE_HINT
    return {"type": "result", "ok": ok, "code": code, "message": message, "component": component,
            "status": "ready" if ok else "failed", "check": row, **extra}

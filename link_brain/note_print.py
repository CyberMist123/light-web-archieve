"""单篇导出（批次 D · F3）：渲染版 PDF（方案 C）/ 网页版 / 压缩包。

PDF：用和笔记页同一套 render 片段 + link-brain.css + lb-print.css 拼一份打印 HTML，
交给系统自带的 Edge / Chrome 无头打印（独立 user-data-dir，只引用 file://，不碰小红书）；
找不到浏览器就降级成网页版（ok:true, fallback:'html'），提示 Ctrl+P 另存。
不改 render_agent_md / render_content_block，打印版自己拼。
"""

from __future__ import annotations
from .errtext import errtext

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import attachments as attachments_mod
from . import comments as comments_mod
from . import note as note_mod
from . import procs, storage
from . import render as render_mod

ASSETS = Path(__file__).resolve().parent / "assets"
PRINT_TIMEOUT_S = 90
ENV_BROWSER = "LINK_BRAIN_PDF_BROWSER"


class ExportError(Exception):
    def __init__(self, message: str, exit_code: int = 1, code: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code


def _stage(name: str) -> None:
    print(f"[export] {name}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# 读对象
# --------------------------------------------------------------------------

def load_object(target: str) -> dict[str, Any]:
    obj = None
    try:
        obj = note_mod.resolve(target)
    except Exception:  # noqa: BLE001 - index 打不开就退回扫 meta
        obj = None
    if obj is None:
        from . import restore as restore_mod
        meta = restore_mod._meta_scan().get(target)
        obj = restore_mod._obj_from_meta(meta) if meta else None
    if obj is None:
        raise ExportError(f"找不到这条收藏：{target}", 2)
    od = storage.object_dir(obj["source"], obj["source_id"])
    meta = storage.read_json(od / "meta.json")
    raw = storage.raw_dir(obj["source"], obj["source_id"], meta["current_version"])
    source_doc = storage.read_json(raw / "source.json")
    manifest = storage.read_json(raw / "manifest.json")
    note = source_doc.setdefault("note", {})
    tp = storage.derived_dir(obj["source"], obj["source_id"]) / "transcript.json"
    tdoc = storage.read_json(tp) if tp.exists() else {}
    note["transcript"] = tdoc.get("text", "") if isinstance(tdoc, dict) else ""
    note["screen_text"] = ((tdoc.get("screen") or {}).get("text", "")) if isinstance(tdoc, dict) else ""
    try:
        note["attachments"] = attachments_mod.declared_attachments(od, source_doc)
    except Exception:  # noqa: BLE001
        pass
    vis_text = ""
    if meta.get("visible_note"):
        vp = storage.vault_root() / meta["visible_note"]
        if vp.is_file():
            vis_text = vp.read_text(encoding="utf-8")
    try:
        notes = note_mod.load_notes(obj["source"], obj["source_id"])
    except note_mod.NotesCorrupt:
        notes = {}
    return {"obj": obj, "dir": od, "meta": meta, "raw": raw, "source": source_doc, "manifest": manifest,
            "note": note, "visible_text": vis_text, "notes": notes,
            "object_rel": f"_archive/{obj['source']}/{obj['source_id']}",
            "title": meta.get("title") or note.get("title") or obj.get("title") or "未命名"}


def _esc(v: Any) -> str:
    return render_mod._safe(v)


def _mmss(sec: Any) -> str:
    try:
        s = int(round(float(sec)))
    except (TypeError, ValueError):
        return ""
    return f"{s // 60}:{s % 60:02d}"


# --------------------------------------------------------------------------
# 打印 HTML
# --------------------------------------------------------------------------

_VIDEO_RE = re.compile(r'<video\b[^>]*>.*?</video>', re.S)
_POSTER_RE = re.compile(r'\bposter="([^"]*)"')


def _postprocess(fragment: str, duration: str) -> str:
    fragment = fragment.replace(' loading="lazy"', "")
    fragment = re.sub(r"<details(?![^>]*\bopen\b)", "<details open", fragment)
    fragment = re.sub(r"<audio\b[^>]*>.*?</audio>", "", fragment, flags=re.S)
    fragment = re.sub(r"<audio\b[^>]*/?>", "", fragment)
    fragment = re.sub(r"<script\b.*?</script>", "", fragment, flags=re.S | re.I)

    cap = "▶ 视频" + (f" · {duration}" if duration else "") + " · 原视频在压缩包里"

    def inner(video_tag: str) -> str:
        pm = _POSTER_RE.search(video_tag)
        return (f'<img src="{pm.group(1)}" alt="视频封面">' if pm and pm.group(1)
                else '<div class="lb-print-video-box">▶</div>')

    # 轮播里的 <figure class="lb-slide"><video …></video></figure>：整个换成封面 + 时长说明
    fragment = re.sub(r'<figure class="lb-slide">\s*(<video\b[^>]*>.*?</video>)\s*</figure>',
                      lambda m: f'<figure class="lb-slide lb-print-video">{inner(m.group(1))}<figcaption>{cap}</figcaption></figure>',
                      fragment, flags=re.S)
    # 其它地方的 <video>（评论里之类）
    fragment = _VIDEO_RE.sub(lambda m: f'<span class="lb-print-video">{inner(m.group(0))}</span>', fragment)
    return fragment


def _annots_html(notes: dict[str, Any]) -> str:
    items = sorted(note_mod.live_annotations(notes), key=lambda a: str(a.get("ts") or ""))
    if not items:
        return ""
    rows = []
    for a in items:
        who = a.get("author") or a.get("by") or ""
        ts = str(a.get("ts") or "")[:16].replace("T", " ")
        meta = " · ".join(x for x in (str(who), ts) if x)
        rows.append(f'<div class="lb-print-annot"><span class="lb-print-annot-meta">{_esc(meta)}</span>{_esc(a.get("text") or "")}</div>')
    return '<div class="lb-print-annots"><h4>批注</h4>' + "".join(rows) + "</div>"


def _left_comments_html(text: str) -> str:
    block, _ = render_mod.split_layers(text)
    if not block:
        return ""
    got = comments_mod.parse_block(block)
    if not got:
        return ""
    rows = "".join(f'<p><span class="lb-print-annot-meta">{_esc(c.date)} {_esc(comments_mod.display_name(c.actor))}</span>{_esc(c.text)}</p>' for c in got)
    return f'<section class="lb-print-extra"><h4>留言</h4>{rows}</section>'


def print_html(target: str, font: str | None = None, *, data: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    d = data or load_object(target)
    note, manifest, rel = d["note"], d["manifest"], d["object_rel"]
    media, has_media = render_mod._media_html(note, manifest, rel)
    video = next((m for m in manifest.get("media", []) if m.get("role") == "video"), None)
    duration = _mmss((note.get("video") or {}).get("duration_sec"))
    side = _postprocess(media, duration) + _annots_html(d["notes"])
    title = f'<h2 class="lb-note-title">{_esc(d["title"])}</h2>'
    body = render_mod._body_html(note.get("body") or "")
    if note.get("transcript"):
        body += '<details class="lb-transcript"><summary>视频文字稿</summary>' + render_mod._body_html(note["transcript"]) + "</details>"
    if note.get("screen_text"):
        body += '<details class="lb-transcript"><summary>视频画面文字</summary>' + render_mod._body_html(note["screen_text"]) + "</details>"
    main = f'{render_mod._author_html(note)}<div class="lb-scroll">{title}{body}</div>'
    detail = render_mod._comments_html(note, d["source"].get("comments") or [], manifest, rel, d["source"].get("capture"))
    # 她划的重点：贴回「右栏 + 评论」（与 render 相同的「首个出现」规则）
    _layer = render_mod.existing_content_layer(d["visible_text"])
    marks = render_mod.collect_highlights(_layer)
    joined = (render_mod.reapply_highlights(main + "\x00SPLIT\x00" + detail, marks, render_mod.collect_highlight_colors(_layer))
              if marks else main + "\x00SPLIT\x00" + detail)
    main, _, detail = joined.partition("\x00SPLIT\x00")
    main, detail = _postprocess(main, duration), _postprocess(detail, duration)
    cls = "lb-note" if has_media and media else "lb-note lb-no-media"
    note_html = (f'<div class="{cls}"><div class="lb-side">{side}</div><div class="lb-main">{main}</div></div>'
                 if has_media and media else f'<div class="{cls}"><div class="lb-main">{main}</div></div>')
    extra = _left_comments_html(d["visible_text"])
    atts = [render_mod.attachment_label(a) if hasattr(render_mod, "attachment_label") else str(a.get("name") or "")
            for a in note.get("attachments") or []]
    if atts:
        extra += '<section class="lb-print-extra"><h4>附件</h4>' + "".join(f"<p>{_esc(a)}</p>" for a in atts) + "</section>"
    url = d["meta"].get("canonical_url") or ""
    head = (f'<header class="lb-print-head"><span>原文 <a href="{_esc(url)}">{_esc(url)}</a></span>'
            f'<span>导出于 {datetime.now():%Y-%m-%d}</span></header>')
    css = (ASSETS / "link-brain.css").read_text(encoding="utf-8") + "\n" + (ASSETS / "lb-print.css").read_text(encoding="utf-8")
    font_css = ""
    if font:
        safe_font = re.sub(r"[<>{};\\]", "", str(font))[:200].strip()
        if safe_font:
            font_css = f":root{{--lb-font:{safe_font}}}"
    base = storage.visible_dir().as_uri() + "/"
    doc = ("<!doctype html><html><head><meta charset=\"utf-8\">"
           f"<title>{_esc(d['title'])}</title><base href=\"{base}\">"
           f"<style>{css}\n{font_css}</style></head>"
           '<body><div class="markdown-preview-view markdown-rendered xhs-note lb-print">'
           f"{head}{note_html}{detail}{extra}</div></body></html>")
    images = doc.count("<img ")
    return doc, {"title": d["title"], "images": images, "has_video": bool(video)}


# --------------------------------------------------------------------------
# 浏览器
# --------------------------------------------------------------------------

def find_browser() -> str | None:
    env = os.environ.get(ENV_BROWSER)
    if env:
        return env if Path(env).is_file() else None
    cands: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg
            for exe in ("msedge.exe", "chrome.exe"):
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                            cands.append(Path(winreg.QueryValue(k, None)))
                    except OSError:
                        pass
        except ImportError:
            pass
        for envname in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
            root = os.environ.get(envname)
            if root:
                cands += [Path(root) / "Microsoft/Edge/Application/msedge.exe", Path(root) / "Google/Chrome/Application/chrome.exe"]
    elif sys.platform == "darwin":
        for app, exe in (("Microsoft Edge", "Microsoft Edge"), ("Google Chrome", "Google Chrome"), ("Chromium", "Chromium")):
            cands.append(Path(f"/Applications/{app}.app/Contents/MacOS/{exe}"))
    else:
        for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
            w = shutil.which(name)
            if w:
                cands.append(Path(w))
    for c in cands:
        if c and c.is_file():
            return str(c)
    return None


def _engine(path: str) -> str:
    n = Path(path).name.lower()
    return "msedge" if "edge" in n else "chrome" if "chrom" in n else ""


def _pdf_ok(path: Path) -> int:
    """合格返回页数，否则 0。"""
    try:
        if not path.is_file() or path.stat().st_size <= 1024:
            return 0
        with path.open("rb") as fh:
            if fh.read(4) != b"%PDF":
                return 0
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(path))
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return 0


def print_pdf(browser: str, html_path: Path, out_pdf: Path, timeout: float = PRINT_TIMEOUT_S) -> bool:
    profile = html_path.parent / "profile"
    # 1025：Chrome 153 的无头模式带 --user-data-dir 打印会一直挂到超时（干净 Linux 上复现：不带 user-data-dir 1 秒出 PDF，
    # 带就挂；加 --incognito 就好）。独立 profile 目录仍要（不碰她真浏览器的资料），只是这一次不落盘
    args = [browser, "--headless=new", "--incognito", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-background-networking", "--disable-component-update", "--disable-sync",
            f"--user-data-dir={profile}", "--no-pdf-header-footer", "--print-to-pdf-no-header",
            "--virtual-time-budget=15000", f"--print-to-pdf={out_pdf}", html_path.as_uri()]
    kw: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    import time
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(args, **kw)
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        procs.kill_tree(proc.pid)   # 只杀自己起的这棵树，不按映像名
        try:
            proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        return False
    # Windows 上 msedge.exe 启动器常常先退出、真正的无头进程（同一个独立 profile）随后才写完 PDF：
    # 等文件出现且能打开（或到总时限），不按退出码判断
    while time.monotonic() < deadline:
        if _pdf_ok(out_pdf):
            return True
        time.sleep(0.2)
    return False


# --------------------------------------------------------------------------
# 落盘
# --------------------------------------------------------------------------

def export_dir() -> Path:
    folder = storage.vault_root() / "收藏导出"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def safe_name(value: Any, n: int = 60) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")[:n].strip(" .") or "未命名"


def unique(folder: Path, stem: str, ext: str) -> Path:
    p = folder / f"{stem}{ext}"
    n = 2
    while p.exists():
        p = folder / f"{stem}（{n}）{ext}"
        n += 1
    return p


def _place(src: Path, dest: Path) -> None:
    """临时目录可能在别的盘：先拷到同目录 .part 再 os.replace。"""
    part = dest.with_name(dest.name + ".part")
    try:
        shutil.copyfile(src, part)
        os.replace(part, dest)
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(storage.vault_root())).replace("\\", "/")
    except ValueError:
        return str(p)


def render_pdf_file(target: str, font: str | None = None, *, data: dict[str, Any] | None = None,
                    tmp_root: Path | None = None) -> tuple[Path | None, str, dict[str, Any], str]:
    """→ (临时 pdf 路径 | None, 打印 HTML, info, engine)。找不到浏览器 pdf=None、engine=''。临时目录由调用方删。"""
    _stage("排版")
    doc, info = print_html(target, font, data=data)
    browser = find_browser()
    if not browser or tmp_root is None:
        return None, doc, info, ""
    html_path = tmp_root / "note.html"
    html_path.write_text(doc, encoding="utf-8")
    out = tmp_root / "out.pdf"
    _stage("打印 PDF")
    done = print_pdf(browser, html_path, out)
    info["pages"] = _pdf_ok(out) if done else 0
    info["timed_out"] = not done
    return (out if info["pages"] else None), doc, info, _engine(browser)


def export_pdf(target: str, font: str | None = None, *, html_only: bool = False) -> dict[str, Any]:
    d = load_object(target)
    folder = export_dir()
    stem = f"{safe_name(d['title'])}_{datetime.now():%Y%m%d}"
    tmp = Path(tempfile.mkdtemp(prefix="lb-print-"))
    try:
        if html_only:
            _stage("排版")
            doc, info = print_html(target, font, data=d)
            pdf, engine = None, ""
            info["pages"] = 0
        else:
            pdf, doc, info, engine = render_pdf_file(target, font, data=d, tmp_root=tmp)
        base = {"item_id": d["obj"]["item_id"], "engine": engine, "results": []}
        if pdf is not None:
            dest = unique(folder, stem, ".pdf")
            _place(pdf, dest)
            return {"ok": True, "code": "", "message": f"已导出 PDF（{info['pages']} 页）", "path": str(dest),
                    "rel": _rel(dest), "pages": info["pages"], "fallback": "", **base}
        dest = unique(folder, stem, ".html")
        storage.atomic_write_text(dest, doc)
        if html_only:
            return {"ok": True, "code": "", "message": "已导出网页版", "path": str(dest), "rel": _rel(dest),
                    "pages": 0, "fallback": "", **base}
        if engine:   # 有浏览器但打印失败 / 超时：网页版照样留着，当场告知（不写进问题记录）
            return {"ok": False, "code": "TRANSIENT.STEP_TIMEOUT", "path": str(dest), "rel": _rel(dest), "pages": 0,
                    "message": "打印 PDF 没成功" + ("（超时）" if info.get("timed_out") else "") + "：已生成网页版，打开后按 Ctrl+P 另存为 PDF",
                    "fallback": "html", **base}
        return {"ok": True, "code": "", "path": str(dest), "rel": _rel(dest), "pages": 0, "fallback": "html",
                "message": "没找到 Edge / Chrome：已生成网页版，打开后按 Ctrl+P 另存为 PDF", **base}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def add_parser(sub) -> None:
    p = sub.add_parser("export-note", help="导出一篇：--pdf 渲染版 PDF（找不到浏览器给网页版）/ --html 网页版 / --zip 全部本地资料")
    p.add_argument("target", help="item_id 或裸 source_id")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pdf", action="store_true")
    g.add_argument("--zip", action="store_true")
    g.add_argument("--html", action="store_true")
    p.add_argument("--no-video", action="store_true", help="压缩包不放视频")
    p.add_argument("--no-pdf", action="store_true", help="压缩包不放 PDF")
    p.add_argument("--font", help="打印用的字体（插件传 --font-text）")
    p.add_argument("--stdin", action="store_true", help='从 stdin 读 {"font": "…"}')
    p.add_argument("--json", action="store_true")


def run(args) -> int:
    from .read import dump_json
    font = args.font
    if args.stdin:
        try:
            req = json.loads(sys.stdin.read() or "{}")
            font = font or (req.get("font") if isinstance(req, dict) else None)
        except (OSError, ValueError):
            pass
    try:
        if args.zip:
            from . import export_bundle
            out = export_bundle.export_note_zip(args.target, include_video=not args.no_video, include_pdf=not args.no_pdf)
        else:
            out = export_pdf(args.target, font, html_only=args.html)
        code = 0 if out.get("ok") else 1
    except ExportError as exc:
        out, code = {"ok": False, "code": exc.code, "message": str(exc), "results": []}, 1
    except Exception as exc:  # noqa: BLE001 - 她点的操作：当场告知原因
        out, code = {"ok": False, "code": "", "message": errtext(exc), "results": []}, 1
    print(out.get("message") or "", file=sys.stderr)
    dump_json(out)
    return code

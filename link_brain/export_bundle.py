"""Portable Markdown and optional original images, without modifying archived notes."""
import json
import re
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from urllib.parse import quote
from . import storage
from .mdsafe import neutralize  # 1001 C-2：导出包里的回答/机读版解压后常被拖回 vault


def export_bundle(ids, include_images=True, answer="", question="选中收藏", asked_at=None):
    vault = storage.vault_root()
    data = json.loads((vault / "_archive/catalog-data.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in data["items"]}
    selected = [by_id[key] for key in dict.fromkeys(ids) if key in by_id]
    if not selected and not answer:
        raise ValueError("没有找到选中的收藏，请刷新目录")
    folder = vault / "收藏导出"
    folder.mkdir(exist_ok=True)
    def safe(value):
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")[:90] or "未命名"
    stamp = datetime.fromisoformat(asked_at.replace("Z", "+00:00")).astimezone() if asked_at and asked_at != "unknown" else datetime.now()
    time_label = "提问时间未记录" if asked_at == "unknown" else stamp.strftime("%Y%m%d-%H%M%S")
    stem = f"{safe(question)}_{len(selected)}篇_{time_label}"
    destination = folder / (stem + ".zip")
    repeat = 2
    while destination.exists():
        destination = folder / f"{stem}（{repeat}）.zip"
        repeat += 1
    missing, index, count = [], ["# 收藏资料", "", "解压后可将 Markdown 与 images 文件夹一起交给支持图片的 AI 工具。", ""], 0
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        if answer:
            archive.writestr("回答与摘录.md", neutralize(answer))
        names = set()
        for n, item in enumerate(selected, 1):
            channel = {"xiaohongshu": "小红书"}.get(item.get("source"), item.get("source") or "小红书")
            base = safe(item["title"]) + "_" + safe(item.get("author") or "未知作者") + "_" + safe(channel)
            name = base + ".md"
            if name in names:
                name = base + f"_{n}.md"
            names.add(name)
            index.append(f"- [{item['title']}]({quote(name)})")
            body = (vault / item["agent_md"]).read_text(encoding="utf-8")
            body += f"\n\n## 来源\n\n{item.get('url', '')}\n\n本地原文：{vault / item['note']}\n"
            if include_images:
                obj = (vault / item["agent_md"]).parent.parent
                meta = json.loads((obj / "meta.json").read_text(encoding="utf-8"))
                raw = obj / "raw" / f"v{meta['current_version']:04d}"
                manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
                body += "\n## 原图\n"
                for media in manifest.get("media", []):
                    if media.get("role") not in {"note_image", "video_cover", "comment_image"}:
                        continue
                    file = media.get("file")
                    source = obj / file if file and file.startswith("raw/") else raw / (file or "")
                    if not file or not source.is_file():
                        missing.append(f"{item['title']}：{file or '图片未下载'}")
                        continue
                    count += 1
                    target = f"images/{n:02d}-{count:04d}{source.suffix}"
                    archive.write(source, target)
                    body += f"\n![原图]({target})\n"
            archive.writestr(name, neutralize(body))
        if missing:
            index.extend(["", "## 未能打包的图片", *[f"- {x}" for x in missing]])
        archive.writestr("索引.md", "\n".join(index))
    if answer:
        from . import answer_cache  # Lot D：回填答案索引的 export_path；失败不挡导出
        answer_cache.attach_export(question, asked_at, destination)
    return {"path": str(destination), "notes": len(selected), "images": count, "missing": missing}


def run(args):
    import sys
    request = json.load(sys.stdin)
    result = export_bundle(request.get("ids", []), request.get("images", True), request.get("answer", ""), request.get("question", "选中收藏"), request.get("asked_at"))
    print(json.dumps(result, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------
# 批次 D · F3-c：单篇压缩包（这一篇的全部本地资料）
# --------------------------------------------------------------------------

def _safe_name(value, n=90):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")[:n].strip(" .") or "未命名"


def _object_media(obj, meta, roles):
    """按 manifest 顺序给出 (role, 源文件路径|None, 条目)。file 以 raw/ 开头按对象目录，否则按 raw/vNNNN。"""
    raw = obj / "raw" / f"v{int(meta['current_version']):04d}"
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    for media in manifest.get("media", []):
        role = media.get("role")
        if role not in roles:
            continue
        file = media.get("file")
        src = (obj / file if file.startswith("raw/") else raw / file) if file else None
        yield role, (src if src is not None and src.is_file() else None), media


def _fmt_size(size):
    return f"{size / 1024 / 1024:.0f} MB" if size >= 1024 * 1024 else f"{max(1, size // 1024)} KB"


def export_note_zip(item_id, *, include_video=True, include_pdf=True):
    import os
    import shutil
    import sys
    import tempfile
    from zipfile import ZIP_STORED
    from . import comments as comments_mod
    from . import note as note_mod
    from . import note_print
    from . import render as render_mod

    d = note_print.load_object(item_id)
    obj, meta, note = d["dir"], d["meta"], d["note"]
    title = d["title"]
    author = (note.get("author") or {}).get("nickname") or "未知作者"
    folder = storage.vault_root() / "收藏导出"
    folder.mkdir(exist_ok=True)
    stem = f"{_safe_name(title, 60)}_{_safe_name(author, 30)}_{datetime.now():%Y%m%d-%H%M%S}"
    destination = folder / (stem + ".zip")
    repeat = 2
    while destination.exists():
        destination = folder / f"{stem}（{repeat}）.zip"
        repeat += 1
    top = _safe_name(title, 60)
    part = destination.with_name(destination.name + ".part")
    counts = {"images": 0, "comment_images": 0, "comment_audio": 0, "video": 0, "attachments": 0}
    missing, have = [], []
    tmp = Path(tempfile.mkdtemp(prefix="lb-zip-"))
    try:
        with ZipFile(part, "w", ZIP_DEFLATED) as zf:
            n_img = 0
            per_comment = {}
            roles = {"note_image", "video_cover", "comment_image", "comment_audio", "video"}
            for role, src, entry in _object_media(obj, meta, roles):
                if role in ("note_image", "video_cover"):
                    if src is None:
                        missing.append(f"图片：{entry.get('file') or '未下载'}")
                        continue
                    n_img += 1
                    zf.write(src, f"{top}/images/{n_img:02d}{src.suffix}")
                    counts["images"] += 1
                elif role in ("comment_image", "comment_audio"):
                    kind = "图" if role == "comment_image" else "语音"
                    if src is None:
                        missing.append(f"评论{kind}：{entry.get('file') or '未下载'}")
                        continue
                    floor = re.sub(r"[^0-9A-Za-z_-]", "", str(entry.get("floor") or entry.get("comment_id") or "x"))[:24] or "x"
                    per_comment[floor] = per_comment.get(floor, 0) + 1
                    zf.write(src, f"{top}/comments/c{floor}-{per_comment[floor]}{src.suffix}")
                    counts["comment_images" if role == "comment_image" else "comment_audio"] += 1
                elif role == "video" and include_video:
                    if src is None or entry.get("download_status") != "ok":
                        missing.append("视频：没下载")
                        continue
                    print(f"[export] 打包视频（{_fmt_size(src.stat().st_size)}）", file=sys.stderr, flush=True)
                    zf.write(src, f"{top}/video/video{src.suffix or '.mp4'}", compress_type=ZIP_STORED)
                    counts["video"] += 1
            # 附件：原件 + 转出的全文
            att_dir = obj / "attachments"
            if att_dir.is_dir():
                for f in sorted(att_dir.iterdir()):
                    if f.is_file() and not f.name.endswith((".json", ".part")):
                        zf.write(f, f"{top}/attachments/{f.name}")
                        counts["attachments"] += 1
            dmd = obj / "derived" / "attachments"
            if dmd.is_dir():
                for f in sorted(dmd.glob("*.md")):
                    zf.writestr(f"{top}/attachments/{f.name}", neutralize(f.read_text(encoding="utf-8")))
            for a in note.get("attachments") or []:
                if a.get("status") != "downloaded":
                    missing.append(f"附件：{a.get('name') or a.get('hint') or a.get('doc_id') or '未下载'}")
            # 正文与识图（不放 raw JSON：里面有 xsec_token，压缩包常被转发）
            agent = obj / "derived" / "agent.md"
            if agent.is_file():
                body = agent.read_text(encoding="utf-8") + f"\n\n## 来源\n\n{meta.get('canonical_url') or ''}\n"
                zf.writestr(f"{top}/正文与识图.md", neutralize(body))
            # 批注
            lives = sorted(note_mod.live_annotations(d["notes"]), key=lambda a: str(a.get("ts") or ""))
            if lives or d["notes"].get("starred"):
                lines = [f"# 批注 · {title}", ""]
                if d["notes"].get("starred"):
                    lines += [f"★ 已加星（{d['notes'].get('starred_at') or ''}）", ""]
                for a in lives:
                    bits = [str(a.get("ts") or "")[:16].replace("T", " "), str(a.get("author") or a.get("by") or ""),
                            str(a.get("text") or "")]
                    lines.append("- " + " · ".join(x for x in bits if x))
                zf.writestr(f"{top}/批注.md", neutralize("\n".join(lines) + "\n"))
            # 留言
            block, _ = render_mod.split_layers(d["visible_text"])
            got = comments_mod.parse_block(block) if block else []
            if got:
                lines = [f"# 留言 · {title}", ""] + [f"- {c.date} {comments_mod.display_name(c.actor)}：{c.text}" for c in got]
                zf.writestr(f"{top}/留言.md", neutralize("\n".join(lines) + "\n"))
            # 渲染版 PDF：有浏览器才有，没有就在索引里写一句，不算失败
            pdf_note = ""
            if include_pdf:
                try:
                    pdf = note_print.render_pdf_file(item_id, data=d, tmp_root=tmp)[0]
                except Exception as exc:  # noqa: BLE001
                    pdf, pdf_note = None, f"笔记页.pdf 没生成（{type(exc).__name__}）"
                if pdf is not None:
                    zf.write(pdf, f"{top}/笔记页.pdf")
                    have.append("笔记页.pdf（渲染版）")
                elif not pdf_note:
                    pdf_note = "笔记页.pdf 没生成：这台电脑没找到 Edge / Chrome（或打印失败）"
            else:
                pdf_note = "这次没放笔记页.pdf"
            idx = [f"# {title}", "", f"- 作者：{author}", f"- 原文：{meta.get('canonical_url') or ''}",
                   f"- 导出时间：{datetime.now():%Y-%m-%d %H:%M}", "", "## 包里有什么", "",
                   f"- 原图 {counts['images']} 张（images/）",
                   f"- 评论图 {counts['comment_images']} 张、评论语音 {counts['comment_audio']} 条（comments/）",
                   f"- 视频 {counts['video']} 个（video/）", f"- 附件 {counts['attachments']} 个（attachments/）",
                   "- 正文与识图.md", *(f"- {x}" for x in have)]
            if pdf_note:
                idx += ["", pdf_note]
            if missing:
                idx += ["", "## 缺什么", "", *[f"- {x}" for x in missing]]
            zf.writestr(f"{top}/索引.md", "\n".join(idx) + "\n")
        os.replace(part, destination)
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    size = destination.stat().st_size
    bits = [f"{counts['images']} 张原图"]
    if counts["video"]:
        bits.append(f"{counts['video']} 个视频")
    if counts["attachments"]:
        bits.append(f"{counts['attachments']} 个附件")
    rel = str(destination.relative_to(storage.vault_root())).replace("\\", "/")
    return {"ok": True, "code": "", "message": f"已打包：{'、'.join(bits)}（{_fmt_size(size)}）", "path": str(destination),
            "rel": rel, "counts": counts, "missing": missing, "bytes": size, "results": []}

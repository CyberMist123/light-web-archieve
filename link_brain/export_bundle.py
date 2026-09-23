"""Portable Markdown and optional original images, without modifying archived notes."""
import json
import re
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from urllib.parse import quote
from . import storage


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
            archive.writestr("回答与摘录.md", answer)
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
            archive.writestr(name, body)
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

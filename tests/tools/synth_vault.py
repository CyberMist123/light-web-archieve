"""造一个合成数据的测试库（真实入口验收用，CONVENTIONS §7.3 / AGENTS.local.md「会改数据的验收不在真库上做」）。

    python tests/tools/synth_vault.py [--n 350] [--out <worktree>/vault] [--dataview-from <别的库>/.obsidian/plugins/dataview]
                                      [--videos 3] [--video-tag 健身] [--cover-size 1080x1440] [--cover-kb 600] [--seed 7]

做的事：
- 走真的 `ingest.ingest_url` + `render` + `catalog.build`，只把联网的几处换成本地桩：
  解析链接、拉笔记详情（照 tests/fixtures/mcp_raw_sanitized.json 的形状造 N 篇）、下载图片（Pillow 现画）、下载视频（拷仓内
  tests/fixtures/tiny-1s.mp4）；OCR 桩成一句固定文字。全程不碰网络、不起小红书组件、不读真库数据。
- 批次 D 地基一次加齐的样本（各线的页面 / 笔记 / 恢复 / 连播用例都在合成库上走真实入口）：
  · 图片多尺寸：3:4（600×800）、9:16（1080×1920）、4:3（1200×900）、长截图（1080×3000），按序号轮换；
    --cover-size WxH 把每篇第一张图（封面）定成这个尺寸，--cover-kb N 让封面变成带噪点的 webp、约 N KB（测大封面缩略图）。
  · 评论：每 5 篇有 1 篇 15 楼带楼中楼，回复数比实际存下的多，带 capture.comment_load（floor_limit=10、带原因的缺口）和带宽高的评论图；
    每 7 篇有 1 篇评论为空但 engagement.comment_count=120；其余照样例 1 楼。
  · 视频：--videos N 篇视频笔记（默认 3），话题带 --video-tag（默认「健身」），manifest 的 video 条目指向拷进去的 tiny-1s.mp4，
    source.note.video.duration_sec=1。
  · 高亮和批注：每 6 篇有 1 篇正文带 <mark> 高亮（render.set_highlight 真改），notes.json 有两条批注 + 一条删除墓碑（deleted）。
  · 一篇照她那次改坏的笔记：内容层清空，外面多一行 ==🟡==（给笔记页的「改坏提示」和恢复用）。
  · 1000 篇规模：--n 1000（几分钟）。
- 星标一部分（notes.json），写 .obsidian：启用 Dataview（刷新 2.5 秒，和作者本机一致）、link-brain-actions（插件从本 worktree 的
  obsidian-plugins/ 拷），CSS 片段。**不再拷贝、启用旧插件 link-brain-native-media-nav**（它开着时并入版 media-nav 会让路，
  合成库里就一直跑旧代码）。Dataview 本身不在仓里：用 --dataview-from 指一份已装好的（只读拷贝）。
- 插件会把 vault 的上一层当程序目录，所以这个库跑的就是本 worktree 的代码。
- 造完在 <out>/../.lbhome-synth/synth-summary.json 记下各类样本是哪几篇（item_id），各线用例按它挑。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mcp_raw_sanitized.json"
TINY_VIDEO = ROOT / "tests" / "fixtures" / "tiny-1s.mp4"

TOPICS = [
    ("悉尼", ["悉尼周末去哪", "悉尼咖啡地图", "悉尼海边徒步", "悉尼租房避坑", "悉尼超市折扣日"]),
    ("做饭", ["电饭煲鸡肉饭", "快手鸡胸肉", "十分钟早餐", "空气炸锅薯条", "一人食番茄汤"]),
    ("AI", ["AI 记忆层开源方案", "让 AI 做梦的实验", "本地大模型部署", "提示词写法合集", "AI 伴侣聊天记录"]),
    ("学习", ["法学复习三步法", "英文论文速读", "番茄钟用法", "错题本模板", "考试周作息"]),
    ("穿搭", ["秋天叠穿", "通勤包推荐", "小个子显高", "白衬衫五种穿法", "运动鞋清洁"]),
    ("家居", ["出租屋改造", "收纳神器", "绿植养护", "灯光氛围", "小厨房布置"]),
    ("旅行", ["墨尔本三日", "新西兰自驾", "东京便利店", "曼谷夜市", "首尔咖啡店"]),
]
PALETTE = ["#e8b4a0", "#a0c4e8", "#b8e0a0", "#e0d0a0", "#c8a0e0", "#a0e0d8", "#e0a0b8", "#d0d0d0"]
# 图片尺寸轮换：3:4 / 9:16 / 4:3 / 长截图
SIZES = [(600, 800), (1080, 1920), (1200, 900), (1080, 3000)]
COMMENT_IMAGE = (480, 360)
HIGHLIGHT_PHRASE = "第一段正文"


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("msyh.ttc", size)
    except Exception:  # noqa: BLE001 - 没有雅黑就用默认字体（只影响封面上的字）
        return ImageFont.load_default()


def _image(text: str, seed: int, size: tuple[int, int], *, fmt: str = "PNG", target_kb: int = 0) -> bytes:
    """现画一张图：纯色底 + 一块白条写字；target_kb>0 时叠噪点存 webp，质量往下调到约 target_kb。"""
    from PIL import Image, ImageDraw

    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", (w, h), rnd.choice(PALETTE))
    draw = ImageDraw.Draw(img)
    fs = max(18, min(w, h) // 14)
    font = _font(fs)
    draw.rectangle([30, h - 4 * fs, w - 30, h - fs], fill="#ffffff")
    draw.text((50, h - 3.6 * fs), text[:12], fill="#333333", font=font)
    draw.text((50, h - 2.3 * fs), f"#{seed:03d} {w}×{h}", fill="#666666", font=font)
    buf = io.BytesIO()
    if target_kb > 0:
        noise = Image.frombytes("RGB", (w, h), rnd.randbytes(w * h * 3))
        img = Image.blend(img, noise, 0.35)
        best = None
        for q in (95, 90, 80, 70, 60, 50, 40, 30, 20, 10):
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=q)
            best = buf.getvalue()
            if len(best) <= target_kb * 1024 * 1.1:
                break
        return best
    img.save(buf, fmt)
    return buf.getvalue()


def _note_id(i: int) -> str:
    return f"{i:024x}"  # 24 位十六进制，形状同真 id，内容是序号


def _plan(n: int, videos: int) -> list[dict]:
    plan = []
    video_at = set(range(4, 4 + 9 * videos, 9)) if videos else set()   # 视频笔记分散开：第 4、13、22… 篇
    for i in range(n):
        cat, titles = TOPICS[i % len(TOPICS)]
        title = f"{titles[(i // len(TOPICS)) % len(titles)]} {i:03d}"
        plan.append({
            "i": i, "id": _note_id(i), "cat": cat, "title": title,
            "video": i in video_at,
            "comments": "gaps" if i % 5 == 1 else "empty120" if i % 7 == 3 else "one",
            "highlight": i % 6 == 2,
        })
    return plan


def _comment_raw(note_id: str, floor: int, *, subs_declared: int, subs_kept: int, pictures: int) -> dict:
    cid = f"c{note_id[-6:]}{floor:03d}"
    pics = [{"urlDefault": f"https://example.invalid/{note_id}/c{floor}-{k}", "width": COMMENT_IMAGE[0], "height": COMMENT_IMAGE[1]}
            for k in range(1, pictures + 1)]
    return {
        "id": cid, "noteId": note_id, "content": f"第 {floor} 楼的评论：说说我的经验。", "likeCount": str(floor * 3),
        "createTime": 1780000100000 + floor * 60000, "ipLocation": "示例", "liked": False,
        "userInfo": {"userId": f"u{floor:04d}", "nickname": f"评论者{floor:02d}", "image": ""},
        "subCommentCount": str(subs_declared), "showTags": [], "pictures": pics,
        "subComments": [{"id": f"{cid}r{k}", "noteId": note_id, "content": f"回复 {k}", "likeCount": "0", "createTime": 1780000200000 + k,
                         "ipLocation": "示例", "liked": False, "userInfo": {"userId": f"r{k:04d}", "nickname": f"回复者{k}", "image": ""},
                         "showTags": []} for k in range(1, subs_kept + 1)],
    }


def build(n: int, out: Path, dataview_from: Path | None, *, videos: int = 3, video_tag: str = "健身",
          cover_size: tuple[int, int] | None = None, cover_kb: int = 0, seed: int = 7) -> dict:
    out = out.resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} 已存在且非空：先删掉再造（防止盖掉别的东西）")
    out.mkdir(parents=True, exist_ok=True)
    home = out.parent / ".lbhome-synth"
    os.environ["LINK_BRAIN_VAULT"] = str(out)
    os.environ["LINK_BRAIN_HOME"] = str(home)
    os.environ["LINK_BRAIN_RENDER_INPROC"] = "1"
    os.environ["LINK_BRAIN_XHS_EXE"] = str(home / "no-such-reader.exe")
    os.environ.pop("LINK_BRAIN_ALERT_CMD", None)
    os.environ.pop("LINK_BRAIN_XHS_ENDPOINT", None)
    os.environ["XHS_PROFILE_DIR"] = str(home / "xhs-profile")
    os.environ["LWA_OPEN_GAP"] = "0,0"
    os.environ["LWA_FETCH_REST"] = "0,0"
    sys.path.insert(0, str(ROOT))

    import httpx

    def refuse(*a, **k):
        raise RuntimeError("synth_vault 不联网")

    httpx.Client.send = refuse  # 兜底：任何真 HTTP 都炸
    from link_brain import accounts, catalog, ingest, render, storage, videos as videos_mod, vision
    from link_brain.adapters import xiaohongshu as xhs

    def reader_not_running(*a, **k):  # 同 conftest：读取服务「没装、没在跑」
        raise httpx.ConnectError("合成库没有读取服务")

    accounts.httpx.request = reader_not_running

    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan = _plan(n, videos)
    by_id = {p["id"]: p for p in plan}

    def size_of(p: dict, k: int) -> tuple[int, int]:
        if p["video"]:
            return (1080, 1920)   # 竖版视频封面
        if k == 0 and cover_size:
            return cover_size
        return SIZES[(p["i"] + k) % len(SIZES)]

    def parse_input(text, client=None):
        nid = text.rsplit("/", 1)[-1]
        return {"note_id": nid, "xsec_token": "SYNTH", "canonical_url": xhs.CANONICAL_FMT.format(note_id=nid),
                "input_url": text, "input_kind": "url"}

    def fetch_detail(note_id, *a, **k):
        p = by_id[note_id]
        i, cat, title = p["i"], p["cat"], p["title"]
        raw = json.loads(json.dumps(base))
        note = raw["data"]["note"]
        raw["feed_id"] = note["noteId"] = note_id
        note["title"] = title
        body = [f"这是合成样例第 {i} 篇，主题「{cat}」。", f"{title}：{HIGHLIGHT_PHRASE}，讲讲具体怎么做。"]
        body += [f"第 {k} 段：一些细节和注意事项，方便测试长笔记滚动。" for k in range(2, 2 + (i % 6))]
        tags = f"#{cat}[话题]#" + (f" #{video_tag}[话题]#" if p["video"] else "")
        note["desc"] = "\n".join(body) + "\n" + tags
        note["time"] = 1780000000000 + i * 3_600_000
        note["user"]["nickname"] = f"作者{i % 17:02d}"
        note["interactInfo"]["likedCount"] = str((i * 37) % 20000)
        count = 1 if p["video"] else 1 + i % 3
        note["imageList"] = [{"width": size_of(p, k)[0], "height": size_of(p, k)[1], "urlDefault": f"https://example.invalid/{note_id}/{k}"}
                             for k in range(count)]
        if p["video"]:
            note["type"] = "video"
            note["video"] = {"capa": {"duration": 1},
                             "media": {"stream": {"h264": [{"masterUrl": f"https://example.invalid/{note_id}/video.mp4", "codec": "h264", "width": 64, "height": 64}]}}}
        comments = raw["data"]["comments"]
        if p["comments"] == "gaps":
            floors = [_comment_raw(note_id, f, subs_declared=(8 if f in (2, 5) else 2 if f % 3 == 0 else 0),
                                   subs_kept=(3 if f == 2 else 1 if f == 5 else 2 if f % 3 == 0 else 0), pictures=(1 if f in (1, 4) else 0))
                      for f in range(1, 16)]
            comments.update(list=floors, hasMore=True, cursor=floors[-1]["id"])
            note["interactInfo"]["commentCount"] = "40"
            raw["data"]["comment_load"] = {
                "floor_limit": 10, "floors_loaded": 15, "floors_expanded": 10, "comments_has_more": True, "stop_reason": "cap",
                "partial": True, "seconds": 42,
                "replies_partial": [
                    {"floor": 2, "comment_id": floors[1]["id"], "shown": 8, "loaded": 3, "missing": 5, "reason": "cap"},
                    {"floor": 5, "comment_id": floors[4]["id"], "shown": 8, "loaded": 1, "missing": 7, "reason": "count_mismatch"},
                ],
            }
        elif p["comments"] == "empty120":
            comments.update(list=[], hasMore=True, cursor="")
            note["interactInfo"]["commentCount"] = "120"
        return raw

    def download_image(url, dest_dir, stem, *, client):
        nid, k = url.rsplit("/", 2)[-2:]
        p = by_id[nid]
        if k.startswith("c"):   # 评论图：c<楼>-<第几张>
            floor, j = (int(x) for x in k[1:].split("-"))
            size, payload, ext, mime = COMMENT_IMAGE, _image(f"评论图 {floor}-{j}", p["i"] * 100 + floor * 10 + j, COMMENT_IMAGE), "png", "image/png"
        else:
            k = int(k)
            size = size_of(p, k)
            label = p["title"] if k == 0 else f"{p['cat']} 图{k + 1}"
            if k == 0 and cover_kb:
                payload, ext, mime = _image(label, p["i"] * 10 + seed, size, target_kb=cover_kb), "webp", "image/webp"
            else:
                payload, ext, mime = _image(label, p["i"] * 10 + k, size), "png", "image/png"
        path = Path(dest_dir) / f"{stem}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {"file": path.name, "requested_url": url, "mime": mime, "width": size[0], "height": size[1],
                "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "download_status": "ok", "error": None}

    def download_video(video, raw, prefix, client=None):
        assets = Path(raw) / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TINY_VIDEO, assets / "video.mp4")
        size = (assets / "video.mp4").stat().st_size
        return {"role": "video", "index": 1, "file": prefix + "/assets/video.mp4", "original_url": video.get("video_url"),
                "mime": "video/mp4", "bytes": size, "width": 64, "height": 64, "download_status": "ok", "error": None}

    class _NoNetClient:   # 下载全换成桩了：别每篇新建真 httpx.Client（每次加载系统证书约 0.7 秒，1000 篇就是十几分钟）
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def close(self): pass
        def get(self, *a, **k): raise RuntimeError("synth_vault 不联网")
        stream = get

    class _HttpxShim:
        Client = _NoNetClient
        def __getattr__(self, name): return getattr(httpx, name)

    xhs.parse_input = parse_input
    xhs.fetch_detail = fetch_detail
    ingest.httpx = _HttpxShim()
    ingest.download_image = download_image
    videos_mod.download = download_video
    xhs.fetch_related_file = lambda note_id, xsec_token, **kw: {
        "ok": True, "related_file": None, "url": xhs.CANONICAL_FMT.format(note_id=note_id), "error": None}
    vision.run_ocr = lambda path, *a, **k: {"status": "ok", "ocr": "合成图片文字", "error": None}

    for p in plan:
        ingest.ingest_url(f"https://example.invalid/{p['id']}", origin="synth")
        render.render_item(xhs.SOURCE, p["id"])
        if p["i"] % 50 == 0:
            print(f"  {p['i']}/{n}", file=sys.stderr)

    summary = {"n": n, "videos": [], "video_tag": video_tag, "comment_gaps": [], "comments_empty_120": [], "highlighted": [],
               "annotated": [], "starred": [], "broken": None, "cover_size": list(cover_size) if cover_size else None, "cover_kb": cover_kb}
    objects = out / "_archive" / "xiaohongshu"
    for p in plan:
        item_id = f"xhs-{p['id']}"
        obj = objects / p["id"]
        notes = {"starred": int(p["id"], 16) % 9 == 0, "annotations": []}
        if p["video"]:
            summary["videos"].append(item_id)
        if p["comments"] == "gaps":
            summary["comment_gaps"].append(item_id)
        elif p["comments"] == "empty120":
            summary["comments_empty_120"].append(item_id)
        if p["highlight"]:
            _, changed = render.set_highlight(item_id, HIGHLIGHT_PHRASE)
            if changed:
                summary["highlighted"].append(item_id)
            notes["annotations"] = [
                {"id": f"a{p['i']}-1", "ts": "2026-10-01T09:00:00+10:00", "text": "合成批注：这条留着", "author": ""},
                {"id": f"a{p['i']}-2", "ts": "2026-10-02T09:00:00+10:00", "text": "@Fable 合成留言", "to_fable": True, "author": ""},
            ]
            notes["deleted"] = [f"a{p['i']}-0"]   # 删除墓碑：之前删掉的那条
            summary["annotated"].append(item_id)
        if notes["starred"]:
            summary["starred"].append(item_id)
        if notes["starred"] or notes["annotations"]:
            storage.write_json(obj / "notes.json", notes)

    # 一篇照她那次改坏的：内容层清空，外面多一行 ==🟡==（挑一篇普通图文笔记）
    victim = next((p for p in plan if not p["video"] and p["comments"] == "one" and not p["highlight"] and p["i"] > 0), None)
    if victim:
        meta = storage.read_json(objects / victim["id"] / "meta.json")
        visible = out / meta["visible_note"]
        text = visible.read_text(encoding="utf-8")
        start, end = text.find(render.CONTENT_START), text.find(render.CONTENT_END)
        if start != -1 and end != -1:
            broken = text[:start] + render.CONTENT_START + "\n" + render.CONTENT_END + "\n==🟡==" + text[end + len(render.CONTENT_END):]
            visible.write_text(broken, encoding="utf-8")
            summary["broken"] = f"xhs-{victim['id']}"
    catalog.build()

    ob = out / ".obsidian"
    plugins = ob / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "obsidian-plugins" / "link-brain-actions", plugins / "link-brain-actions", dirs_exist_ok=True)
    enabled = ["link-brain-actions"]
    if dataview_from and (dataview_from / "main.js").exists():
        dv = plugins / "dataview"
        dv.mkdir(exist_ok=True)
        for f in ("main.js", "manifest.json", "styles.css"):
            if (dataview_from / f).exists():
                shutil.copy2(dataview_from / f, dv / f)
        (dv / "data.json").write_text(json.dumps({"refreshEnabled": True, "refreshInterval": 2500, "enableDataviewJs": True,
                                                  "enableInlineDataviewJs": False}, indent=1), encoding="utf-8")
        enabled.insert(0, "dataview")
    (ob / "community-plugins.json").write_text(json.dumps(enabled, indent=1), encoding="utf-8")
    (ob / "app.json").write_text(json.dumps({"defaultViewMode": "preview", "livePreview": True}, indent=1), encoding="utf-8")
    (ob / "snippets").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "link_brain" / "assets" / "link-brain.css", ob / "snippets" / "link-brain.css")
    (ob / "appearance.json").write_text(json.dumps({"enabledCssSnippets": ["link-brain"]}), encoding="utf-8")
    home.mkdir(parents=True, exist_ok=True)
    (home / "synth-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"合成库：{out}（{n} 篇；视频 {len(summary['videos'])}、评论缺口 {len(summary['comment_gaps'])}、评论空但 120 条 "
          f"{len(summary['comments_empty_120'])}、高亮 {len(summary['highlighted'])}、改坏 {summary['broken'] or '无'}）；样本清单：{home / 'synth-summary.json'}")
    return summary


def _size(text: str) -> tuple[int, int]:
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=350)
    ap.add_argument("--out", type=Path, default=ROOT / "vault")
    ap.add_argument("--dataview-from", type=Path, default=None)
    ap.add_argument("--videos", type=int, default=3, help="视频笔记篇数（拷 tests/fixtures/tiny-1s.mp4）")
    ap.add_argument("--video-tag", default="健身", help="视频笔记都带的话题（连播按它挑）")
    ap.add_argument("--cover-size", type=_size, default=None, help="封面尺寸 WxH（每篇第一张图）")
    ap.add_argument("--cover-kb", type=int, default=0, help="封面做成带噪点的 webp，约多少 KB（0 = 普通 PNG）")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    build(a.n, a.out, a.dataview_from, videos=a.videos, video_tag=a.video_tag, cover_size=a.cover_size, cover_kb=a.cover_kb, seed=a.seed)


if __name__ == "__main__":
    main()

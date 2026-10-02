"""造一个合成数据的测试库（真实入口验收用，CONVENTIONS §7.3 / AGENTS.local.md「会改数据的验收不在真库上做」）。

    python tests/tools/synth_vault.py [--n 350] [--out <worktree>/vault] [--dataview-from <别的库>/.obsidian/plugins/dataview]

做的事：
- 走真的 `ingest.ingest_url` + `render` + `catalog.build`，只把联网的三处换成本地桩：
  解析链接、拉笔记详情（照 tests/fixtures/mcp_raw_sanitized.json 的形状造 N 篇）、下载图片（Pillow 现画一张彩色封面）；
  OCR 桩成一句固定文字。全程不碰网络、不起小红书组件、不读真库数据。
- 星标一部分（notes.json），写 .obsidian：启用 Dataview（刷新 2.5 秒，和作者本机一致）、link-brain-actions、
  link-brain-native-media-nav（插件从本 worktree 的 obsidian-plugins/ 拷），CSS 片段。
  Dataview 本身不在仓里：用 --dataview-from 指一份已装好的（只读拷贝）。
- 插件会把 vault 的上一层当程序目录，所以这个库跑的就是本 worktree 的代码。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mcp_raw_sanitized.json"

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


def _png(text: str, seed: int) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    rnd = random.Random(seed)
    w, h = 600, rnd.choice([600, 750, 800])
    img = Image.new("RGB", (w, h), rnd.choice(PALETTE))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("msyh.ttc", 44)
    except Exception:  # noqa: BLE001 - 没有雅黑就用默认字体（只影响封面上的字）
        font = ImageFont.load_default()
    draw.rectangle([30, h - 170, w - 30, h - 40], fill="#ffffffcc")
    draw.text((50, h - 150), text[:12], fill="#333333", font=font)
    draw.text((50, h - 95), f"#{seed:03d}", fill="#666666", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _note_id(i: int) -> str:
    return f"{i:024x}"  # 24 位十六进制，形状同真 id，内容是序号


def build(n: int, out: Path, dataview_from: Path | None) -> None:
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
    from link_brain import accounts, catalog, ingest, render, storage, vision

    def reader_not_running(*a, **k):  # 同 conftest：读取服务「没装、没在跑」
        raise httpx.ConnectError("合成库没有读取服务")

    accounts.httpx.request = reader_not_running
    from link_brain.adapters import xiaohongshu as xhs

    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan = []
    for i in range(n):
        cat, titles = TOPICS[i % len(TOPICS)]
        title = f"{titles[(i // len(TOPICS)) % len(titles)]} {i:03d}"
        plan.append((i, cat, title))
    by_id = {_note_id(i): (i, cat, title) for i, cat, title in plan}

    def parse_input(text, client=None):
        nid = text.rsplit("/", 1)[-1]
        return {"note_id": nid, "xsec_token": "SYNTH", "canonical_url": xhs.CANONICAL_FMT.format(note_id=nid),
                "input_url": text, "input_kind": "url"}

    def fetch_detail(note_id, *a, **k):
        parsed = {"note_id": note_id}
        i, cat, title = by_id[note_id]
        raw = json.loads(json.dumps(base))
        note = raw["data"]["note"]
        raw["feed_id"] = note["noteId"] = parsed["note_id"]
        note["title"] = title
        body = [f"这是合成样例第 {i} 篇，主题「{cat}」。", f"{title}：第一段正文，讲讲具体怎么做。"]
        body += [f"第 {k} 段：一些细节和注意事项，方便测试长笔记滚动。" for k in range(2, 2 + (i % 6))]
        note["desc"] = "\n".join(body) + f"\n#{cat}[话题]#"
        note["time"] = 1780000000000 + i * 3_600_000
        note["user"]["nickname"] = f"作者{i % 17:02d}"
        note["interactInfo"]["likedCount"] = str((i * 37) % 20000)
        note["imageList"] = [{"width": 600, "height": 800, "urlDefault": f"https://example.invalid/{parsed['note_id']}/{k}"}
                             for k in range(1 + i % 3)]
        return raw

    def download_image(url, dest_dir, stem, *, client):
        nid, k = url.rsplit("/", 2)[-2:]
        i, cat, title = by_id[nid]
        payload = _png(title if k == "0" else f"{cat} 图{int(k) + 1}", i * 10 + int(k))
        path = Path(dest_dir) / f"{stem}.png"
        path.write_bytes(payload)
        import hashlib
        return {"file": path.name, "requested_url": url, "mime": "image/png", "width": 600, "height": 800,
                "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "download_status": "ok", "error": None}

    xhs.parse_input = parse_input
    xhs.fetch_detail = fetch_detail
    ingest.download_image = download_image
    xhs.fetch_related_file = lambda note_id, xsec_token, **kw: {
        "ok": True, "related_file": None, "url": xhs.CANONICAL_FMT.format(note_id=note_id), "error": None}
    vision.run_ocr = lambda path, *a, **k: {"status": "ok", "ocr": "合成图片文字", "error": None}

    for i, cat, title in plan:
        ingest.ingest_url(f"https://example.invalid/{_note_id(i)}", origin="synth")
        render.render_item(xhs.SOURCE, _note_id(i))
        if i % 50 == 0:
            print(f"  {i}/{n}", file=sys.stderr)
    # 星标约 1/9
    for obj in sorted((out / "_archive" / "xiaohongshu").iterdir()):
        if int(obj.name, 16) % 9 == 0:
            storage.write_json(obj / "notes.json", {"starred": True, "annotations": []})
    catalog.build()

    ob = out / ".obsidian"
    plugins = ob / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    for name in ("link-brain-actions", "link-brain-native-media-nav"):
        shutil.copytree(ROOT / "obsidian-plugins" / name, plugins / name, dirs_exist_ok=True)
    enabled = ["link-brain-actions", "link-brain-native-media-nav"]
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
    print(f"合成库：{out}（{n} 篇）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=350)
    ap.add_argument("--out", type=Path, default=ROOT / "vault")
    ap.add_argument("--dataview-from", type=Path, default=None)
    a = ap.parse_args()
    build(a.n, a.out, a.dataview_from)


if __name__ == "__main__":
    main()

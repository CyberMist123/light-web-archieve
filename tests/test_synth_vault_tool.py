"""批次 D 地基：tests/tools/synth_vault.py 造得出各线要的样本（子进程跑，临时目录，不联网、不碰真库）。"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_synth_vault_builds_batch_d_samples(tmp_path):
    out = tmp_path / "vault"
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "tools" / "synth_vault.py"), "--n", "14", "--videos", "1", "--video-tag", "健身",
                        "--cover-size", "600x800", "--cover-kb", "60", "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8", timeout=600, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-2000:]
    summary = json.loads((tmp_path / ".lbhome-synth" / "synth-summary.json").read_text(encoding="utf-8"))
    objects = out / "_archive" / "xiaohongshu"

    # 视频：拷进去的就是仓内 tiny-1s.mp4，manifest 有 video 条目，话题带 --video-tag
    vid = summary["videos"][0][4:]
    manifest = json.loads((objects / vid / "raw" / "v0001" / "manifest.json").read_text(encoding="utf-8"))
    video = next(m for m in manifest["media"] if m["role"] == "video")
    assert video["download_status"] == "ok"
    assert (objects / vid / video["file"]).read_bytes() == (ROOT / "tests" / "fixtures" / "tiny-1s.mp4").read_bytes()
    source = json.loads((objects / vid / "raw" / "v0001" / "source.json").read_text(encoding="utf-8"))
    assert source["note"]["kind"] == "video" and source["note"]["video"]["duration_sec"] == 1 and "健身" in source["note"]["hashtags"]

    # 评论缺口：15 楼、comment_load 带原因的缺口；评论空但 comment_count=120
    gap = json.loads((objects / summary["comment_gaps"][0][4:] / "raw" / "v0001" / "source.json").read_text(encoding="utf-8"))
    cl = gap["capture"]["comment_load"]
    assert len(gap["comments"]) == 15 and cl["floor_limit"] == 10 and {g["reason"] for g in cl["gaps"]} == {"cap", "count_mismatch"}
    assert any(c["images"] and c["images"][0]["width"] for c in gap["comments"]), "评论图带宽高"
    empty = json.loads((objects / summary["comments_empty_120"][0][4:] / "raw" / "v0001" / "source.json").read_text(encoding="utf-8"))
    assert empty["comments"] == [] and empty["note"]["engagement"]["comment_count"] == 120

    # 高亮 + 批注（含墓碑）
    hid = summary["highlighted"][0][4:]
    meta = json.loads((objects / hid / "meta.json").read_text(encoding="utf-8"))
    assert "<mark>" in (out / meta["visible_note"]).read_text(encoding="utf-8")
    notes = json.loads((objects / hid / "notes.json").read_text(encoding="utf-8"))
    assert len(notes["annotations"]) == 2 and notes["deleted"]

    # 改坏的那篇：内容层清空、外面多一行 ==🟡==
    bid = summary["broken"][4:]
    text = (out / json.loads((objects / bid / "meta.json").read_text(encoding="utf-8"))["visible_note"]).read_text(encoding="utf-8")
    assert "<!-- link-brain:content:start -->\n<!-- link-brain:content:end -->\n==🟡==" in text

    # 封面：--cover-size / --cover-kb → 带噪点的 webp；目录数据有封面宽高
    data = json.loads((out / "_archive" / "catalog-data.json").read_text(encoding="utf-8"))
    assert len(data["items"]) == 14
    covers = [it for it in data["items"] if it.get("cover", "").endswith(".webp") and "image-001" in it["cover"]]
    assert covers and (covers[0]["cover_w"], covers[0]["cover_h"]) == (600, 800)

    # 不再拷贝、启用旧图片导航插件
    assert json.loads((out / ".obsidian" / "community-plugins.json").read_text(encoding="utf-8")) == ["link-brain-actions"]
    assert not (out / ".obsidian" / "plugins" / "link-brain-native-media-nav").exists()
    for f in ("note-actions.js", "note-tools.js", "image-actions.js", "player-ui.js", "index-ui.js"):
        assert (out / ".obsidian" / "plugins" / "link-brain-actions" / f).exists()

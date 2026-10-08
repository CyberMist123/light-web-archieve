"""批次 D · L3：笔记页测试夹具——调真的 render.render_content_block，把几种笔记的「内容层」写到 tests/fixtures/note-page/*.html，
给 playwright 外壳（tests/ui/note_page_ui.cjs）用：页面测试用的就是生产渲染的输出，不是手写的 DOM。
图片的 src 是生产的相对路径（../../_archive/…），外壳里按 width / height 换成同尺寸的现画图。全是合成数据。

用法：python tests/tools/note_fixture.py          # 重写夹具
      pytest tests/test_note_fixture_golden.py      # 每次重新生成并和仓库里的比对
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from link_brain import render  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "note-page"
OBJ = "_archive/xiaohongshu/synth0001"
BODY = "\n\n".join(f"第 {i} 段合成正文：讲做饭的步骤、火候和调味，用来把右栏撑高。" for i in range(1, 9))


def _comments(n: int = 24) -> list[dict]:
    return [{"comment_id": f"c{i}", "author": {"nickname": f"读者{i}"}, "text": f"第 {i} 楼合成评论，说说自己的做法。",
             "like_count": i, "sub_comment_count": 0, "sub_comments": []} for i in range(1, n + 1)]


def _images(sizes: list[tuple[int, int]]) -> list[dict]:
    return [{"role": "note_image", "file": f"raw/v0001/assets/image-{i:03d}.webp", "download_status": "ok", "width": w, "height": h}
            for i, (w, h) in enumerate(sizes, 1)]


CASES = {
    "image-3x4": {"kind": "image", "media": _images([(600, 800)] * 3)},
    "image-9x16": {"kind": "image", "media": _images([(1080, 1920)] * 2)},
    "image-4x3": {"kind": "image", "media": _images([(1200, 900)] * 3)},
    "image-mixed": {"kind": "image", "media": _images([(600, 800), (1200, 900), (1080, 1920)])},
    "video-9x16": {"kind": "video", "media": [
        {"role": "video", "file": "raw/v0001/assets/video.mp4", "download_status": "ok", "width": 1080, "height": 1920},
        {"role": "video_cover", "file": "raw/v0001/assets/cover.webp", "download_status": "ok", "width": 1080, "height": 1920},
    ]},
}


def build(case: str) -> str:
    spec = CASES[case]
    source = {
        "note": {"title": f"合成笔记 {case}", "kind": spec["kind"], "body": BODY, "hashtags": ["做饭", "家常菜"], "links": [],
                 "author": {"nickname": "合成作者"}, "published_at": "2026-09-04T12:00:00+10:00",
                 "engagement": {"liked": 12, "collected": 3, "comment_count": 24}},
        "comments": _comments(),
    }
    meta = {"item_id": "xhs-synth0001", "source": "xiaohongshu", "source_id": "synth0001",
            "canonical_url": "https://example.invalid/explore/synth0001"}
    return render.render_content_block(source=source, manifest={"media": spec["media"]}, meta=meta, object_rel=OBJ) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        (OUT / f"{case}.html").write_text(build(case), encoding="utf-8", newline="\n")
    print(f"写了 {len(CASES)} 份夹具 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""note_print 的补充用例：只测纯函数 _esc / _mmss / _postprocess / _annots_html / _left_comments_html。

find_browser / print_pdf / print_html / load_object 要找浏览器、读真对象目录，不在本文件盖
（print_html 会读 assets 里的真 CSS，export 走临时目录和进程，归别的测试）。
"""

from __future__ import annotations

from link_brain import note_print as npx
from link_brain import render as render_mod


def test_esc_is_html_escape():
    assert npx._esc('<a href="x">她</a>') == "&lt;a href=&quot;x&quot;&gt;她&lt;/a&gt;"
    assert npx._esc(None) == "" and npx._esc(123) == "123"
    assert npx._esc("它's") == "它&#x27;s"          # quote=True 连单引号也转


def test_mmss_rounds_and_fails_open():
    assert npx._mmss(65) == "1:05" and npx._mmss(599) == "9:59"
    assert npx._mmss(600) == "10:00" and npx._mmss(0) == "0:00"
    assert npx._mmss(59.6) == "1:00"                # 四舍五入到秒
    assert npx._mmss("12.4") == "0:12"              # 数字字符串也认
    assert npx._mmss(None) == "" and npx._mmss("abc") == ""


def test_postprocess_strips_and_opens_details():
    frag = ('<img src="a.jpg" loading="lazy"><details><summary>s</summary>x</details>'
            '<details open><summary>y</summary></details>'
            '<audio controls src="x.mp3"></audio><audio src="y.mp3"/>'
            '<script>a<b</script><SCRIPT>bad</SCRIPT>')
    out = npx._postprocess(frag, "")
    assert ' loading="lazy"' not in out and '<img src="a.jpg">' in out
    assert out.count("<details open") == 2           # 没 open 的补上，已有的不动
    assert "audio" not in out and "<script" not in out.lower() and "bad" not in out


def test_postprocess_slide_video_uses_poster_and_duration():
    frag = '<figure class="lb-slide"><video src="v.mp4" poster="p.jpg"></video></figure>'
    out = npx._postprocess(frag, "12:34")
    assert out == ('<figure class="lb-slide lb-print-video"><img src="p.jpg" alt="视频封面">'
                   '<figcaption>▶ 视频 · 12:34 · 原视频在压缩包里</figcaption></figure>')


def test_postprocess_video_without_poster_or_duration():
    frag = '<figure class="lb-slide"> <video src="v.mp4"></video> </figure>前文 <video poster="q.jpg">x</video> 后文'
    out = npx._postprocess(frag, "")
    assert ('<figure class="lb-slide lb-print-video"><div class="lb-print-video-box">▶</div>'
            '<figcaption>▶ 视频 · 原视频在压缩包里</figcaption></figure>') in out   # 没时长不加点
    assert '<span class="lb-print-video"><img src="q.jpg" alt="视频封面"></span>' in out  # 轮播外的视频成 span
    assert "<video" not in out and "前文" in out and "后文" in out                   # 视频一个不剩，正文不动


def test_annots_html_filters_tombstones_and_sorts():
    notes = {"annotations": [
        {"id": "a2", "ts": "2026-10-26T09:05:30+11:00", "text": "第二条"},
        {"id": "a1", "author": "她", "ts": "2026-10-25T08:00:00+11:00", "text": "第一条 <b>重点</b>"},
        {"id": "a3", "ts": "2026-10-26T10:00:00+11:00", "text": "   "},   # 空白文本不算
        "不是字典",                                                        # 非字典条目跳过
        {"id": "a4", "by": "机器人", "text": "没有时间戳"},
    ], "deleted": ["a2"]}
    out = npx._annots_html(notes)
    assert out.startswith('<div class="lb-print-annots"><h4>批注</h4>')
    row_no_ts = '<div class="lb-print-annot"><span class="lb-print-annot-meta">机器人</span>没有时间戳</div>'
    row_a1 = ('<div class="lb-print-annot"><span class="lb-print-annot-meta">她 · 2026-10-25 08:00</span>'
              '第一条 &lt;b&gt;重点&lt;/b&gt;</div>')
    assert row_no_ts in out and row_a1 in out
    assert out.index(row_no_ts) < out.index(row_a1)                  # 没时间戳的排最前（空串最小）
    assert "第二条" not in out and out.count('<div class="lb-print-annot">') == 2   # 墓碑里的不出现
    assert npx._annots_html({}) == "" and npx._annots_html({"annotations": []}) == ""


def test_left_comments_html_parses_managed_block():
    s, e = render_mod.COMMENTS_START, render_mod.COMMENTS_END
    text = (f"{s}\n> 「20260101 人」这条她写的\n"
            '<!-- link-brain:id=c1 actor=fable target=none status=ok -->\n'
            f"> 「20260102 人」另一条 1 < 2\n{e}")
    out = npx._left_comments_html(text)
    assert out == ('<section class="lb-print-extra"><h4>留言</h4>'
                   '<p><span class="lb-print-annot-meta">20260101 Fable</span>这条她写的</p>'
                   '<p><span class="lb-print-annot-meta">20260102 人</span>另一条 1 &lt; 2</p></section>')
    assert npx._left_comments_html("没有受管块的正文") == ""        # 找不到块 → 空
    assert npx._left_comments_html(f"{s}\n不是留言行\n{e}") == ""  # 块里没有留言行 → 空

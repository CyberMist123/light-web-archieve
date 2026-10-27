"""把样式模版做成单文件：docs/style-guide.src.html → docs/style-guide.html。

源文件里两处占位换成真内容：
  /*@TOKENS@*/  ← link_brain/assets/lb-tokens.css 原文（唯一源，不手抄）
  /*@FONTS@*/   ← 随包的 Cinzel / Cormorant woff2，base64 内嵌成 @font-face（"LB Cinzel" / "LB Cormorant"）
生成的文件不依赖任何相对路径：在 Claude 的文件预览、浏览器、发给别人都照样显示。
用法：python tools/build_style_guide.py    （改了 src 或样式集之后跑一次；--check 只查生成物是不是最新）
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "style-guide.src.html"
OUT = ROOT / "docs" / "style-guide.html"
TOKENS = ROOT / "link_brain" / "assets" / "lb-tokens.css"
FONTS = [("LB Cinzel", "Cinzel-latin-variable.woff2", "400 900", "normal", ""),
         ("LB Cormorant", "CormorantGaramond-Italic-latin-variable.woff2", "300 700", "italic", ""),
         # 和 lb-page-lib.js brandFontCss 的「LB Digits」同一个：只管数字，名字里的字母不斜
         ("LB Digits", "CormorantGaramond-Italic-latin-variable.woff2", "300 700", "italic", "U+0030-0039,U+0025,U+002B-002F,U+003A,U+00A5,U+FFE5")]


def build() -> str:
    src = SRC.read_text(encoding="utf-8")
    faces = []
    for family, name, weight, style, rng in FONTS:
        data = base64.b64encode((ROOT / "link_brain" / "assets" / "fonts" / name).read_bytes()).decode("ascii")
        faces.append(f'@font-face{{font-family:"{family}";src:url(data:font/woff2;base64,{data}) format("woff2");'
                     f"font-weight:{weight};font-style:{style};font-display:block;" + (f"unicode-range:{rng};" if rng else "") + "}")
    for mark in ("/*@FONTS@*/", "/*@TOKENS@*/"):
        if src.count(mark) != 1:
            raise SystemExit(f"{SRC.name} 里 {mark} 应该正好一处")
    out = src.replace("/*@FONTS@*/", "\n".join(faces)).replace("/*@TOKENS@*/", TOKENS.read_text(encoding="utf-8"))
    return out.replace("这是源文件：改这里，再跑", "这是生成的文件（别手改）：改 docs/style-guide.src.html，再跑", 1)


def main(argv: list[str]) -> int:
    html = build()
    if "--check" in argv:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == html
        print("最新" if ok else "过期了：跑 python tools/build_style_guide.py")
        return 0 if ok else 1
    OUT.write_text(html, encoding="utf-8")
    print(f"写好了：{OUT.relative_to(ROOT)}（{len(html.encode('utf-8')) // 1024} KB）")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main(sys.argv[1:]))

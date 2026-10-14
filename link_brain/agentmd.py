"""机读版 agent.md 的精简规则（2026-10-08 批次 B）。

`render.render_agent_md` 只管按节拼；这里放各节的清洗 / 去重 / 限额，全是纯函数，不读盘：
- 图片：原图目录只写一次；OCR 去二进制串 / 乱码行 / 每张图都有的水印；识图描述去掉和 OCR 重复的句子，
  和前面某张图差不多的写「同图N」，每图限字。图号（图3 = image-003）照旧，问答证据身份读 vision.json 不读这里。
- 评论：去水话、按「作者回复 / 值得看 / 带图片文字」优先精选、限条数和字数；楼号 c3 / c3.1 用原编号，略去的楼不让号。
- 视频：转写合并口吃重复、长稿分段；画面文字去乱码、和转写交叉去重、限字。
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

from .ocrtext import clean_ocr

# ---------------------------------------------------------------- 通用

_PUNCT = re.compile(r"[\s，。！？、,.!?；;：:“”\"'‘’（）()「」『』【】\[\]《》<>…·—\-~～*#/|]+")
_EFFECTIVE = re.compile(r"[0-9A-Za-z一-鿿぀-ヿ가-힯]")
_CJK = re.compile(r"[一-鿿぀-ヿ가-힯]")
_WORDY = re.compile(r"[A-Za-z一-鿿぀-ヿ가-힯]")


def norm(text: Any) -> str:
    """去空白和标点，比较用。"""
    return _PUNCT.sub("", str(text or ""))


def cut(text: str, limit: int, tail: str = "…") -> str:
    return text if len(text) <= limit else text[: max(0, limit)].rstrip() + tail


def junk_line(line: str) -> bool:
    """OCR 乱码 / 装饰行：二进制串、≤2 个有效字符（两个汉字的词保留）、只有数字和符号的短行。"""
    s = (line or "").strip()
    effective = _EFFECTIVE.findall(s)
    if len(effective) <= 2 and len(_CJK.findall(s)) < 2:
        return True
    if len(re.sub(r"\s", "", s)) >= 8 and re.fullmatch(r"[01\s]+", s):
        return True
    if not _WORDY.search(s):
        digits = re.sub(r"\D", "", s)
        if len(effective) <= 6:
            return True
        if len(digits) >= 8 and digits.count("0") + digits.count("1") >= 0.75 * len(digits):
            return True   # OCR 把二进制装饰认错几位（1100013100131）
    return False


def _covered(piece: str, pool: str, threshold: int = 90) -> bool:
    """piece（已归一化）是否已在 pool 里出现过：短的只认原样包含，≥4 字按 partial_ratio。"""
    from rapidfuzz import fuzz
    if not piece:
        return True
    if piece in pool:
        return True
    return len(piece) >= 4 and bool(pool) and fuzz.partial_ratio(piece, pool) >= threshold


# ---------------------------------------------------------------- 图片

_TRANSCRIBE_HEAD = re.compile(r"[^。\n]*文字(?:转录|内容|如下)[^。\n]*?[:：]")
_TEXT_WORDS = ("文字", "字幕", "写着", "配文", "标题", "文案", "署名", "水印", "栏目")
_QUOTE = re.compile(r"[“\"「『]([^”\"」』]{1,80})[”\"」』]")
DESC_LIMIT = 400        # 识图描述安全上限：按句子边界截，不截半句（10-15 前是 60 字硬截，把「挎…」截在半句）
IMAGE_LIMIT = 600       # 每图 OCR 文字上限：按整行截
STRUCTURED_LIMIT = 800
COMMENT_IMAGE_LIMIT = 300


def image_no(asset: str) -> int | None:
    m = re.search(r"image-(\d+)", asset or "")
    return int(m.group(1)) if m else None


def asset_name(asset: str) -> str:
    return str(asset or "").rsplit("/", 1)[-1]


def ocr_lines(image: dict[str, Any]) -> list[str]:
    """一张图的 OCR 行：去统计行、乱码行，同图内重复行只留一次。段落间隔（按行框的竖向空隙判断）用空串表示。"""
    boxed = [x for x in image.get("lines") or [] if isinstance(x, dict) and str(x.get("text") or "").strip()]
    if boxed and all(isinstance(x.get("box"), (list, tuple)) and len(x["box"]) == 4 for x in boxed):
        rows = [(str(x["text"]).strip(), x["box"]) for x in boxed]
    else:
        rows = [(line.strip(), None) for line in clean_ocr(image.get("ocr")).splitlines()]
    heights = sorted(b[3] - b[1] for _, b in rows if b) or [0]
    gap_need = 1.2 * heights[len(heights) // 2]
    out: list[str] = []
    seen: set[str] = set()
    prev_bottom = None
    for s, box in rows:
        if not s or junk_line(s):
            continue
        key = norm(s)
        if not key or key in seen:
            continue
        seen.add(key)
        if box and prev_bottom is not None and out and box[1] - prev_bottom > gap_need > 0:
            out.append("")
        out.append(s)
        if box:
            prev_bottom = box[3]
    return out


def cut_sentences(text: str, limit: int) -> str:
    """按句子边界截到 limit 字以内，不截半句；第一句就超长时整句保留。截了末尾加「…（略）」。"""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    parts = [x for x in re.split(r"(?<=[。！？!?；;])", text) if x]
    out = ""
    for part in parts:
        if out and len(out) + len(part) > limit:
            return out.rstrip() + "…（略）"
        out += part
    return out


def watermarks(per_image: list[list[str]]) -> list[str]:
    """≥3 张图时，在 ≥50% 的图里都出现的短行（≤12 字）= 水印 / 栏目名。按首次出现的顺序返回原样文字。"""
    if len(per_image) < 3:
        return []
    count: dict[str, int] = {}
    first: dict[str, str] = {}
    for lines in per_image:
        for line in lines:
            if line:
                first.setdefault(norm(line), line)
        for key in {norm(x) for x in lines if x and len(x) <= 12 and norm(x)}:
            count[key] = count.get(key, 0) + 1
    need = max(2, math.ceil(len(per_image) * 0.5))
    return [line for key, line in first.items() if count.get(key, 0) >= need]


def clean_description(text: str, ocr_norm: str) -> str:
    """识图描述去掉和 OCR 重复的部分：「图内文字转录如下：…」整段、和 OCR 几乎一样的句子、只是在复述图上文字的句子。"""
    from rapidfuzz import fuzz
    text = str(text or "")
    if ocr_norm:
        m = _TRANSCRIBE_HEAD.search(text)
        if m:
            text = text[: m.start()]
    kept = []
    for raw in re.split(r"(?<=[。；;])|\n", text):   # 不按！？切：引号里常有，切开就配不上引号
        sent = raw.strip()
        n = norm(sent)
        if not n:
            continue
        if ocr_norm:
            if len(n) >= 4 and fuzz.partial_ratio(n, ocr_norm) >= 90:
                continue
            quotes = [norm(q) for q in _QUOTE.findall(sent) if norm(q)]
            if quotes and any(w in sent for w in _TEXT_WORDS) and all(set(q) <= set(ocr_norm) for q in quotes):
                continue
        kept.append(sent)
    return "".join(kept)


def _structured_label(image: dict[str, Any]) -> tuple[str, list[str]] | None:
    """精细识别 / 按图校对的文字、表格、流程图：返回（标签, 行）；普通图片返回 None。"""
    refined = image.get("refined") or {}
    if refined.get("status") == "ok":
        label = {"table": "表格·精细识别", "diagram": "流程图·精细识别", "text": "文字·精细识别"}.get(refined.get("kind"), "精细识别")
        return label, str(refined.get("text") or "").splitlines()
    visual = image.get("visual") or {}
    if visual.get("status") == "ok" and visual.get("v") and visual.get("kind") in ("table", "diagram", "text"):
        label = {"table": "表格", "diagram": "流程图要点", "text": "文字（按图校对）"}[visual["kind"]]
        if (image.get("refine") or {}).get("status") == "pending":
            label += "，待精细识别"
        rows = str(visual.get("text") or "").splitlines()
        if visual["kind"] == "text":   # 按图校对的文字也去掉 UI 控件之类的乱码行（表格 / 流程图的行不动，分隔行要留）
            rows = [r for r in rows if not junk_line(re.sub(r"^\s*[-*]\s+", "", r))]
        return label, rows
    return None


def shaky(image: dict[str, Any]) -> str:
    """识图结果没把握的原因；有把握返回空串。"""
    if image.get("status") != "ok":
        return "识别失败"
    visual = image.get("visual") or {}
    if visual.get("shaky"):
        return str(visual["shaky"])
    if visual and visual.get("status") not in (None, "", "ok", "skipped"):
        return "识图没成功"
    return ""


def _safe(value: Any) -> str:
    import html
    return html.escape("" if value is None else str(value), quote=True)


def _diagram_raw(image: dict[str, Any], indent: str) -> list[str]:
    """R2 10-04：二层 Mermaid 会丢非结构文字，图下折叠附一层 OCR 原文（每行缩进、不留空行，别跳出列表项）。"""
    raw = [str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in image.get("lines") or []] \
        or str(image.get("ocr") or "").splitlines()
    raw = [row for row in (r.strip() for r in raw) if row]
    if not raw:
        return []
    out = [f"{indent}  <details><summary>一层 OCR 原文（识别结果，未经精细识别）</summary>",
           f"{indent}  <pre>" + _safe(raw[0])] + [f"{indent}  {_safe(row)}" for row in raw[1:]]
    out[-1] += "</pre>"
    out.append(f"{indent}  </details>")
    return out


def image_entries(images: list[dict[str, Any]], origin: Callable[[str], str]) -> tuple[list[str], list[dict[str, Any]]]:
    """正文图片 → (水印行, 每张图一条 {no, lines, cap, fixed})。lines 已按每图上限截好；fixed=True 的（精细识别）不再压缩。"""
    plain = [ocr_lines(im) for im in images]
    marks = watermarks([lines for im, lines in zip(images, plain) if im.get("status") == "ok"])
    mark_keys = {norm(x) for x in marks}
    entries: list[dict[str, Any]] = []
    descs: list[tuple[int | str, str]] = []
    for image, lines in zip(images, plain):
        asset = str(image.get("asset") or "")
        no = image_no(asset)
        head = f"### 第{no}张（图{no} · {asset_name(asset)}）" if no is not None else f"### {asset_name(asset)}"
        why = shaky(image)
        tail = [f"识别没把握（{why}），原图：{origin(asset)}"] if why else []
        if image.get("status") != "ok":
            entries.append({"head": head, "lines": [head, "", f"（识别失败：{image.get('error')}）"] + tail, "fixed": True})
            continue
        structured = _structured_label(image)
        if structured:
            label, rows = structured
            fixed = (image.get("refined") or {}).get("status") == "ok"
            body = [row.rstrip() for row in rows]
            while body and not body[-1]:
                body.pop()
            if not fixed:
                body = _cap_rows(body, STRUCTURED_LIMIT)
            out = [head, "", f"{label}：", ""] + [_no_heading(r) for r in body]
            if fixed and (image.get("refined") or {}).get("kind") == "diagram":
                out += [""] + [r[2:] for r in _diagram_raw(image, "")]
            entries.append({"head": head, "lines": out + ([""] + tail if tail else []), "fixed": fixed})
            continue
        text_lines = [x for x in lines if not x or norm(x) not in mark_keys]
        while text_lines and not text_lines[0]:
            text_lines.pop(0)
        text_lines = [x for i, x in enumerate(text_lines) if x or (i + 1 < len(text_lines) and text_lines[i - 1])]
        visual = image.get("visual") or {}
        desc = ""
        if visual.get("status") == "ok":
            desc = clean_description(visual.get("text") or "", norm(clean_ocr(image.get("ocr"))))
        entries.append({"head": head, "ocr": text_lines, "desc": desc, "tail": tail,
                        "kind": visual.get("kind"), "no": no if no is not None else asset_name(asset)})
    # 和前面某张图描述差不多（≥80%）的写「同图N」
    from rapidfuzz import fuzz
    for entry in entries:
        if not entry.get("desc"):
            continue
        n = norm(entry["desc"])
        same = next((no for no, prev in descs if fuzz.ratio(n, prev) >= 80), None)
        if same is not None:
            entry["same"] = same
        else:
            descs.append((entry["no"], n))
    return marks, entries


def _cap_rows(rows: list[str], limit: int) -> list[str]:
    """按整行截到 limit 字以内（表格截行仍是合法表格），截了末尾加一行「…（略）」。"""
    out, used = [], 0
    for row in rows:
        if used + len(row.strip()) > limit and out:
            out.append(f"{row[: len(row) - len(row.lstrip())]}…（略）")
            return out
        out.append(row)
        used += len(row.strip())
    return out


def _no_heading(row: str) -> str:
    """图上文字顶格的「# 标题」会变成机读版里的真小标题、打乱分节（read 按 ## 取节），转义成字面井号。"""
    stripped = row.lstrip()
    return row[: len(row) - len(stripped)] + "\\" + stripped if stripped.startswith("#") else row


def render_entry(entry: dict[str, Any]) -> list[str]:
    """一张普通图片：小标题「第N张」，下面先「描述」（不硬截，按句子边界设安全上限），再「图上文字」（保留原换行和段落）。"""
    if "lines" in entry:
        return entry["lines"]
    label = {"table": "表格", "title": "标题图"}.get(entry.get("kind"), "描述")
    out = [entry["head"], ""]
    if entry.get("same") is not None:
        out += [f"{label}：同第{entry['same']}张", ""]
    elif entry.get("desc"):
        out += [f"{label}：" + cut_sentences(entry["desc"], DESC_LIMIT), ""]
    if entry["ocr"]:
        out += ["图上文字：", ""] + [_no_heading(r) for r in _cap_rows(entry["ocr"], IMAGE_LIMIT)] + [""]
    if len(out) == 2:
        out += ["（没认出文字）", ""]
    if entry["tail"]:
        out += entry["tail"] + [""]
    return out[:-1] if out[-1] == "" else out


def image_section(images: list[dict[str, Any]], origin: Callable[[str], str], total: int = 3000) -> list[str]:
    """「图片 OCR」节的正文行（不含节标题）。超过 total 字后，后面的普通图片只留小标题和一行「略」。"""
    if not images:
        return []
    marks, entries = image_entries(images, origin)
    folder = origin(str(images[0].get("asset") or "")).rsplit("/", 1)[0] + "/"
    out = [f"原图在 `{folder}`（image-NNN.webp 按图号；评论图 comment-<评论id>-N.webp），需要看原图用 read_asset。"]
    if marks:
        out.append("每张图都带：" + "、".join(marks))
    used = 0
    for entry in entries:
        rows = render_entry(entry)
        size = sum(len(r.strip()) for r in rows[1:])
        if used + size > total and "lines" not in entry:
            rows = [entry["head"], "", "（略，超出图片字数上限）"] + ([""] + entry["tail"] if entry["tail"] else [])
            size = sum(len(r) for r in rows[1:])
        out += [""] + rows
        used += size
    return out


def comment_image_text(image: dict[str, Any]) -> str:
    """评论图片只留有文字的：按图校对 / 精细识别的文字，或去掉乱码后的 OCR；表情包、（无文字）、识图描述都不要。"""
    structured = _structured_label(image)
    if structured:
        rows = [re.sub(r"^\s*[-*]\s+", "", r).replace("**", "").strip() for r in structured[1]]
        text = " / ".join(r for r in rows if r and not r.startswith("```") and not r.startswith("|-") and not junk_line(r))
    else:
        text = " / ".join(x for x in ocr_lines(image) if x)
    return cut(text, COMMENT_IMAGE_LIMIT, "…（略）") if len(norm(text)) >= 4 else ""


# ---------------------------------------------------------------- 评论

_EMOJI = re.compile(r"\[[^\[\]\s]{1,10}\]")
_MENTION = re.compile(r"@\S+")
_CHATTER_WORDS = ("哈哈", "笑死", "绝了", "救命", "好好笑", "太好笑", "好可爱", "可爱", "同问", "码住", "马住", "蹲", "收藏了", "我也是")
_FILLER = set("哈呵嘿嘻hHaA啊呀哇哦噢嗯唔呜哭笑草好的了么吗呢吧嘛啦耶草")


def chatter(text: Any) -> bool:
    """没信息的水话：表情码 / @ 去掉后 ≤10 字，且去掉「哈哈 / 笑死」这类词和语气字后剩不到 3 个字。"""
    core = norm(_MENTION.sub("", _EMOJI.sub("", str(text or ""))))
    if len(core) > 10:
        return False
    rest = core
    for word in _CHATTER_WORDS:
        rest = rest.replace(word, "")
    rest = "".join(c for c in rest if c not in _FILLER)
    return len(rest) <= 2


def select_comments(labeled: list[tuple[str, dict[str, Any]]], *, author_id: str, valuable: set[str],
                    noise: set[str], with_text: set[str], max_count: int = 30, max_chars: int = 3000
                    ) -> tuple[set[str], dict[str, int]]:
    """挑要写进机读版的楼号。优先：作者自己 / 作者回复过的楼 / 值得看 / 带图片文字；水话和小模型标的广告噪音不要（优先的除外）。
    返回（选中的楼号, {"chatter": n, "over": n}）。楼号是原编号，略去的不让号。"""
    replied = {label.split(".")[0] for label, c in labeled
               if author_id and str((c.get("author") or {}).get("user_id") or "") == author_id}

    def size(label: str, c: dict[str, Any]) -> int:
        return len(str(c.get("text") or "")) + 10

    first, rest, dropped = [], [], 0
    for label, c in labeled:
        own = bool(author_id) and str((c.get("author") or {}).get("user_id") or "") == author_id
        empty = chatter(c.get("text"))
        # 作者回复过的楼：楼主那句留；作者自己的回复不是水话才算优先
        priority = (label in valuable or label in with_text or (own and not empty)
                    or ("." not in label and label in replied and not (own and empty)))
        if priority:
            first.append((label, c))
        elif label in noise or empty:
            dropped += 1
        else:
            rest.append((label, c))
    chosen: set[str] = set()
    used = 0
    for i, (label, c) in enumerate(first + rest):
        if len(chosen) >= max_count:
            break
        # 字数上限只拦普通楼；优先的楼（值得看 / 作者 / 带图片文字）照留，只占额度
        if i >= len(first) and used + size(label, c) > max_chars:
            continue
        chosen.add(label)
        used += size(label, c)
    # 选中了楼中楼、没选中它那一楼的：楼主那句不是水话就带上，给上下文
    by_label = dict(labeled)
    for label in list(chosen):
        top = label.split(".")[0]
        if top != label and top not in chosen and top not in noise and not chatter(by_label[top].get("text")):
            chosen.add(top)
    over = len(labeled) - dropped - len(chosen)
    return chosen, {"chatter": dropped, "over": max(0, over)}


# ---------------------------------------------------------------- 视频

_STUTTER = re.compile(r"\b((?:[A-Za-z']+\s+){0,3}[A-Za-z']+)(?:[\s,]+\1\b)+", re.I)
TRANSCRIPT_PARAGRAPH = 3000
PARAGRAPH = 400
SCREEN_LIMIT = 1500


def merge_stutter(text: str) -> str:
    """转写里连着重复的词 / 短语只留一次：we we → we，it's also it's also → it's also。"""
    return _STUTTER.sub(r"\1", text or "")


def paragraphs(text: str, limit: int = PARAGRAPH) -> str:
    """按句切成 ≤ limit 字的段落，段间空行。"""
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?；])|(?<=[.;])\s+|\n", text or "") if s and s.strip()]
    paras: list[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + len(s) > limit:
            paras.append(cur)
            cur = ""
        joint = " " if cur and cur[-1:].isascii() and s[:1].isascii() else ""
        cur = cur + joint + s if cur else s
    if cur:
        paras.append(cur)
    return "\n\n".join(paras)


def screen_units(text: str, seen: str, *, legacy: bool) -> list[str]:
    """视频画面文字 → 要写的行：去乱码、和已留下的行比（ratio ≥ 85 算重复）、和正文 / 转写比（partial_ratio ≥ 90 算重复）。
    legacy=True：旧版抽取把一帧里的各行用空格拼成了一行，这里按空格拆回小块再比，留下的块按帧拼回一行。"""
    from rapidfuzz import fuzz, process
    pool = norm(seen)
    kept: list[str] = []
    out: list[str] = []
    for line in (text or "").splitlines():
        pieces = line.split() if legacy else [line]
        fresh = []
        for piece in pieces:
            piece = piece.strip()
            n = norm(piece)
            if not n or junk_line(piece) or _covered(n, pool):
                continue
            if n in kept or (kept and process.extractOne(n, kept, scorer=fuzz.ratio, score_cutoff=85)):
                continue
            kept.append(n)
            fresh.append(piece)
        if fresh:
            out.append(" ".join(fresh))
    return out


def cap_units(units: list[str], limit: int = SCREEN_LIMIT) -> list[str]:
    """超过 limit 字：留最长的若干段（按原顺序输出），末尾写「已截断，共 N 段」。"""
    if sum(len(u) for u in units) <= limit:
        return units
    order = sorted(range(len(units)), key=lambda i: -len(units[i]))
    keep, used = set(), 0
    for i in order:
        if used + len(units[i]) <= limit:
            keep.add(i)
            used += len(units[i])
    return [units[i] for i in sorted(keep)] + [f"（已截断，共 {len(units)} 段）"]

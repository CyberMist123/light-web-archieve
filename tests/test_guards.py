"""仓库守卫：所有「扫源码找不该有的写法」的规则都在这一个文件里，基线只有一份 `tests/guards-baseline.json`。

1025 第二波 PR⓪，把原来散在五处的守卫合成一处（路线评审：「守卫在膨胀，合成一个文件 + 一份基线」）：
- `test_single_source.py` 的 12 条唯一数据来源规则（ARCH-AUDIT 第 0 批，allowed / known 白名单）
- `test_errtext.py` 的手拼异常文字基线（每文件计数，只许减）
- `test_problems_alert_exit.py` 的报警出口扫描（CONVENTIONS §2.6）
- `test_file_lock.py` 的手写原子写扫描（CONVENTIONS §6.5）
- `test_hardening_1001.py` 的本机私有路径扫描（AGENTS.md 第 5 条）

一条规则 = 一个正则 + 扫哪些文件 + 允许出现的文件（allowed，不计数）。其余文件里每一处命中都计数，
和基线比：
- 基线里没有的文件出现命中 → 红（新写了一份重复 / 新绕过了约定）
- 某文件命中数比基线多 → 红
- 某文件命中数比基线少 → 也红，提示把基线改小（不然以后能悄悄加回来）
改到哪个文件顺手迁掉几处，然后 `python tests/test_guards.py --write` 重写基线（默认只接受变少；真要把新命中写进基线加 `--allow-grow`，diff 会出现在 PR 里，审的人看得见）；
`python tests/test_guards.py` 不带参数只打印现状和基线的差。

整行注释（# / //）不扫（旧的异常文字扫描连注释一起扫，这次有意改成不扫：注释拼不出用户看得到的文字；「本机私有路径」例外，注释里也不许有）；
真不是违规的那一行，行里任何位置带规则的 ok 标记（如 `# errtext-ok`）就不计。
以后新守卫（第二波的 import 契约、环数等）也加在这里：能写成「正则 + allowed」的加进 RULES，不能的写成本文件里的一个测试。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = Path(__file__).resolve().parent / "guards-baseline.json"

PY_GLOBS = ("link_brain/**/*.py", "link_brain/assets/*.yaml")
PY_ONLY = ("link_brain/**/*.py",)
JS_GLOBS = ("link_brain/assets/*.js", "obsidian-plugins/**/*.js")


@dataclass(frozen=True)
class Rule:
    pattern: str
    globs: tuple[str, ...]
    allowed: frozenset[str] = frozenset()
    doc: str = ""
    ok_marker: str = ""          # 行尾带这个标记的行不计
    skip_comments: bool = True   # 整行注释不扫
    flags: int = 0               # 正则开关（如 re.I）
    _rx: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_rx", re.compile(self.pattern, self.flags))


def _rule(pattern, globs, allowed=(), doc="", **kw) -> Rule:
    return Rule(pattern, tuple(globs), frozenset(allowed), doc, **kw)


RULES: dict[str, Rule] = {
    # ---- 唯一数据来源（原 test_single_source.py；批次见 docs/ARCH-AUDIT.md §10）----
    "价格表": _rule(
        r"^\s*PRICES\s*=|[\"']pricing\.json[\"']|^pricing:",
        PY_GLOBS, {"link_brain/pricing.py"}, "ARCH-AUDIT 第 2 批"),
    "价格读法": _rule(
        r"estimate\.(_price|load_pricing|token_cost|audio_cost)\(|refineKeysEnv[\"']?\)",
        PY_GLOBS, {"link_brain/providers.py"}, "ARCH-AUDIT 第 2 批"),
    "收藏判断": _rule(
        r"ingest_kind[\"']?\)?\s*==?\s*[\"']favorite|\.get\([\"']favorited_by[\"']\)",
        # domain 是规则本体；favorites.tag_account 写 favorited_by（SYNC 归属）；synclog 问的是「哪趟同步带进来的」，读 ingest_kind 是对的
        PY_GLOBS, {"link_brain/domain.py", "link_brain/sources/xiaohongshu/favorites.py", "link_brain/synclog.py"}, "ARCH-AUDIT 第 3 批 / 第二波 PR①"),
    # ---- 第二波 PR① 新加（设计稿 §5.4）----
    "item_id 前缀": _rule(
        r"[\"']xhs-|f[\"']xhs-\{|removeprefix\([\"']xhs-",
        PY_GLOBS, {"link_brain/domain.py"},
        "身份规则只在 domain.py（item_id / parse_item_id / short_id）。基线里剩的是目录名 / cssclass，不是 item_id"),
    "在库 / 墓碑判断": _rule(
        r"FROM tombstones",
        PY_GLOBS, {"link_brain/index.py", "link_brain/remove.py", "link_brain/storage.py"},
        "在库 / 已删判断走 domain.lookup(storage.probe_object(...))，第二波 PR④⑤ 清空"),
    "账号字段": _rule(
        r"config\(\)\.get\([\"'](sync_account|nickname|user_id)[\"']",
        PY_GLOBS, {"link_brain/sources/xiaohongshu/accounts.py"}, "ARCH-AUDIT 第 3 批"),
    "Gemini 密钥来源": _rule(
        r"LWA_GEMINI_KEYS|gemini_keys_(file|cmd)",
        PY_GLOBS, {"link_brain/providers.py", "link_brain/storage.py"}, "ARCH-AUDIT 第 2 批"),
    "写死的模型名": _rule(
        r"[\"'](qwen[0-9][\w.-]*|qwen3-[\w.-]+|gemini-[0-9][\w.-]*|deepseek-[\w.-]+|gpt-4o[\w.-]*"
        r"|text-embedding-[\w.-]+|whisper-1)[\"']",
        PY_GLOBS, {"link_brain/ai_config.py"}, "ARCH-AUDIT 第 2 批"),
    "页面标题兜底 Collections": _rule(
        r"[\"']Collections[\"']",
        JS_GLOBS, {"link_brain/assets/lb-page-lib.js"}, "ARCH-AUDIT 第 4 批"),
    "问题分组表抄本": _rule(
        r"GROUP_OF_CLASS\s*=", JS_GLOBS, (), "ARCH-AUDIT 第 4 批"),
    "供应商猜测": _rule(
        r"function providerOf|providerOf\s*=", JS_GLOBS, (), "ARCH-AUDIT 第 2 批"),
    "前端预算默认值": _rule(
        r"(dailyYuan|daily_yuan)[^\n]*\?\?\s*3\b", JS_GLOBS, (), "ARCH-AUDIT 第 2 批"),
    "默认回答提示词": _rule(
        r"DEFAULT_ANSWER_PROMPT\s*=", JS_GLOBS, (), "ARCH-AUDIT 第 4 批"),
    "CLI 命令抄本": _rule(
        r"claude -p --model", JS_GLOBS, (), "ARCH-AUDIT 第 2 批"),
    # ---- 异常转文字只走 errtext（原 test_errtext.py）----
    "手拼异常文字": _rule(
        r"type\(.*?\)\.__name__|\.__class__\.__name__",
        PY_ONLY, {"link_brain/errtext.py"},
        "异常转文字请用 link_brain.errtext.errtext（CONVENTIONS §2）", ok_marker="errtext-ok"),
    # ---- 推送只有一个出口（原 test_problems_alert_exit.py）----
    "绕过 problems 直接报警": _rule(
        r"\balert_mod\b|\balert\._alert\s*\(|\balert\.alert\s*\(|from\s+\.+\s*alert\s+import|"
        r"from\s+\.+\s+import\s+[^\n]*\balert\b|import\s+link_brain\.alert|from\s+link_brain\s+import\s+[^\n]*\balert\b"
        r"|from\s+link_brain\.alert\s+import",
        PY_ONLY, {"link_brain/alert.py", "link_brain/problems.py"}, "CONVENTIONS §2.6：报警只经 problems.report"),
    # ---- 原子写收口 storage（原 test_file_lock.test_no_hand_rolled_atomic_writes_left，扫全部而不只四个文件）----
    "手写原子写": _rule(
        r"os\.replace\(tmp|mkstemp\(|\.tmp[\"']\)|with_suffix\([\"']\.tmp[\"']\)|NamedTemporaryFile\(",
        PY_ONLY, {"link_brain/storage.py"}, "CONVENTIONS §6.5：写 .tmp 再 os.replace 用 storage.*"),
    # ---- 公开仓不带本机路径（原 test_hardening_1001.test_no_private_default_paths_in_public_modules，扫全部）----
    "本机私有路径": _rule(
        r"[A-Za-z]:[\\/]Users[\\/](?!<|%|\{)[^\\/\s]+[\\/]",
        PY_GLOBS + JS_GLOBS, (), "AGENTS.md 第 5 条：不进本机用户路径", skip_comments=False, flags=re.I),
}


def _files(globs, root: Path):
    seen = set()
    for g in globs:
        for p in sorted(root.glob(g)):
            if "node_modules" in p.parts or not p.is_file() or p in seen:
                continue
            seen.add(p)
            yield p


def scan(rule: Rule, root: Path = ROOT) -> dict[str, int]:
    """allowed 之外的文件 → 命中数（只含 >0 的）。"""
    out: dict[str, int] = {}
    for p in _files(rule.globs, root):
        rel = p.relative_to(root).as_posix()
        if rel in rule.allowed:
            continue
        n = 0
        for line in p.read_text("utf-8", errors="replace").splitlines():
            s = line.lstrip()
            if rule.skip_comments and (s.startswith("#") or s.startswith("//")):
                continue
            if rule.ok_marker and rule.ok_marker in line:
                continue
            n += len(rule._rx.findall(line))
        if n:
            out[rel] = n
    return out


def current() -> dict[str, dict[str, int]]:
    return {name: scan(rule) for name, rule in RULES.items()}


def load_baseline(path: Path = BASELINE_FILE) -> dict[str, dict[str, int]]:
    data = json.loads(path.read_text("utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def write_baseline(path: Path = BASELINE_FILE, allow_grow: bool = False) -> list[str]:
    """重写基线。默认只接受变少；变多的规则原样留在基线里并返回提示（要接受加 allow_grow）。"""
    now = current()
    old = load_baseline(path) if path.exists() else {}
    refused = []
    if not allow_grow:
        for name, files in now.items():
            base = old.get(name, {})
            grown = [m for m in diff(name, files, base) if "基线之外" in m or "变多" in m]
            if grown and name in old:
                refused += grown
                now[name] = base
    data = {"_": "tests/test_guards.py 的基线：规则 → 文件 → 命中数。只许减；改动用 python tests/test_guards.py --write 重写。"}
    data.update(now)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")
    return refused


def diff(name: str, now: dict[str, int], base: dict[str, int]) -> list[str]:
    rule = RULES[name]
    msgs = []
    new = sorted(set(now) - set(base))
    if new:
        where = f"只许在 {sorted(rule.allowed)}" if rule.allowed else "后端统一来源之外不该再有"
        msgs.append(f"「{name}」出现在基线之外的文件：{ {f: now[f] for f in new} }。{where}；{rule.doc}")
    grown = {f: (now[f], base[f]) for f in now if f in base and now[f] > base[f]}
    if grown:
        msgs.append(f"「{name}」命中数变多（文件: (现在, 基线)）：{grown}。{rule.doc}")
    less = {f: (now.get(f, 0), base[f]) for f in base if now.get(f, 0) < base[f]}
    if less:
        msgs.append(f"「{name}」这些文件已经少了，把基线改小（python tests/test_guards.py --write）：{less}")
    return msgs


# ------------------------------------------------------------------------------------------------
# 守卫本身
# ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(RULES))
def test_guard(name):
    base = load_baseline()
    assert name in base, f"基线里没有「{name}」这条规则：python tests/test_guards.py --write"
    msgs = diff(name, scan(RULES[name]), base[name])
    assert not msgs, "\n".join(msgs)


def test_baseline_has_no_stale_rules():
    stale = set(load_baseline()) - set(RULES)
    assert not stale, f"基线里这些规则已经不存在了，从 guards-baseline.json 删掉：{sorted(stale)}"


def test_allowed_files_exist():
    missing = {name: sorted(f for f in rule.allowed if not (ROOT / f).is_file()) for name, rule in RULES.items()}
    missing = {k: v for k, v in missing.items() if v}
    assert not missing, f"allowed 里写了不存在的文件（拼错了或已搬走）：{missing}"


# ------------------------------------------------------------------------------------------------
# 扫描器自测：每种写法都抓得到、注释和 ok 标记放过
# ------------------------------------------------------------------------------------------------


def _fake_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_scanner_counts_every_errtext_spelling(tmp_path):
    root = _fake_repo(tmp_path, {"link_brain/a.py": (
        'x = f"{type(exc).__name__}: {exc}"\n'
        'y = "出错：" + type(e).__name__\n'
        'z = f"（{type(err).__name__}）{err}"\n'
        'w = exc.__class__.__name__\n'
        'ok = type(v).__name__  # errtext-ok\n'
        '# type(c).__name__ 在注释里\n'),
        "link_brain/errtext.py": "s = type(exc).__name__\n"})
    assert scan(RULES["手拼异常文字"], root) == {"link_brain/a.py": 4}


def test_scanner_catches_direct_alert_calls_and_spares_problems(tmp_path):
    root = _fake_repo(tmp_path, {
        "link_brain/x.py": "from . import alert as alert_mod\nalert_mod._alert('a')\nfrom link_brain.alert import _alert\n",
        "link_brain/problems.py": "from . import alert as alert_mod\nalert_mod._alert('a')\n",
        "link_brain/alert.py": "def _alert(m): pass\n"})
    assert scan(RULES["绕过 problems 直接报警"], root) == {"link_brain/x.py": 4}


def test_scanner_catches_hand_rolled_atomic_writes(tmp_path):
    """「手写原子写」要认得 with_suffix(\".tmp\") / NamedTemporaryFile / os.replace(tmp，三种写法各计一次；
    注释不算；storage.py 本身在 allowed 里不算。"""
    code = ('import tempfile, os\n'
            'def w(p, d):\n'
            '    tmp = p.with_suffix(".tmp")\n'
            '    f = tempfile.NamedTemporaryFile(dir=d)\n'
            '    os.replace(tmp, p)\n'
            '# os.replace(tmp, p)\n')
    root = _fake_repo(tmp_path, {
        "link_brain/x.py": code,
        "link_brain/storage.py": code})
    assert scan(RULES["手写原子写"], root) == {"link_brain/x.py": 3}


def test_scanner_catches_single_source_copies_in_js_and_skips_comments(tmp_path):
    root = _fake_repo(tmp_path, {
        "link_brain/assets/lb-page-lib.js": "const t = 'Collections';\n",
        "link_brain/assets/catalog-view.js": "// 'Collections' 注释不算\nconst a = 'Collections'; const b = \"Collections\";\n",
        "obsidian-plugins/p/main.js": "x('Collections')\n"})
    assert scan(RULES["页面标题兜底 Collections"], root) == {
        "link_brain/assets/catalog-view.js": 2, "obsidian-plugins/p/main.js": 1}


def test_scanner_catches_private_paths_even_in_comments(tmp_path):
    root = _fake_repo(tmp_path, {
        "link_brain/a.py": "# 默认 C:\\Users\\someone\\x\np = 'C:/Users/<you>/ok'\nq = 'c:/users/lower/case/'\n",
        "link_brain/assets/b.js": "const d = 'C:/Users/%USERNAME%/fine';\n"})
    assert scan(RULES["本机私有路径"], root) == {"link_brain/a.py": 2}


def test_diff_reports_new_grown_and_shrunk():
    msgs = diff("手拼异常文字", {"a.py": 2, "b.py": 3, "new.py": 1}, {"a.py": 1, "b.py": 4, "gone.py": 1})
    assert len(msgs) == 3
    assert "new.py" in msgs[0] and "'a.py': (2, 1)" in msgs[1] and "gone.py" in msgs[2] and "b.py" in msgs[2]


def test_write_baseline_refuses_growth_by_default(tmp_path, monkeypatch):
    base = tmp_path / "b.json"
    base.write_text(json.dumps({"手拼异常文字": {"link_brain/a.py": 1}}), "utf-8")
    monkeypatch.setattr(sys.modules[__name__], "current", lambda: {"手拼异常文字": {"link_brain/a.py": 2}})
    refused = write_baseline(base)
    assert refused and load_baseline(base)["手拼异常文字"] == {"link_brain/a.py": 1}
    assert write_baseline(base, allow_grow=True) == [] and load_baseline(base)["手拼异常文字"] == {"link_brain/a.py": 2}


# ---- import 契约（第二波 PR③，设计稿 §5）：.importlinter 是基线，tests/tools/import_scan.py 是扫描 ----
sys.path.insert(0, str(ROOT / "tests" / "tools"))
import import_scan  # noqa: E402

# 最大环的模块数（PR③ 搬家后 78）。只许减：拆掉一截就把数字改小。
MAX_CYCLE = 78


@pytest.fixture(scope="module")
def import_graph():
    return import_scan.edges()


@pytest.mark.parametrize("key", list(import_scan.contracts()))
def test_import_contract(key, import_graph):
    c = import_scan.contracts()[key]
    now = import_scan.violations(c, import_graph)
    new = sorted(now - c["ignore"])
    gone = sorted(c["ignore"] - now)
    assert not new, f"「{c['name']}」新增违规（改走 link_brain.sources 接口，或确有理由再写进 .importlinter 的 ignore_imports）：\n" + \
        "\n".join(f"    {a} -> {b}" for a, b in new)
    assert not gone, f"「{c['name']}」这些已经迁走了，把 .importlinter 里对应的 ignore_imports 行删掉：\n" + \
        "\n".join(f"    {a} -> {b}" for a, b in gone)


def test_import_cycle_size(import_graph):
    n = import_scan.largest_cycle(import_graph)
    assert n <= MAX_CYCLE, f"最大 import 环从 {MAX_CYCLE} 个模块涨到 {n}：新加的 import 把更多模块卷进环里了"
    assert n == MAX_CYCLE, f"最大 import 环缩到 {n} 个模块了，把 tests/test_guards.py 的 MAX_CYCLE 改成 {n}"


def test_import_scan_contract_semantics():
    g = {("link_brain.domain", "link_brain.storage"),
         ("link_brain.sources", "link_brain.sources.xiaohongshu"),
         ("link_brain.sources.xiaohongshu.accounts", "link_brain.sources.xiaohongshu.adapter"),
         ("link_brain.ingest", "link_brain.sources.xiaohongshu.adapter")}
    pure = {"source": ["link_brain.domain"], "forbidden": ["link_brain"]}
    iface = {"source": ["link_brain.sources"], "forbidden": ["link_brain.sources.xiaohongshu"]}
    shared = {"source": ["link_brain.ingest"], "forbidden": ["link_brain.sources.xiaohongshu"]}
    assert import_scan.violations(pure, g) == {("link_brain.domain", "link_brain.storage")}
    assert import_scan.violations(iface, g) == {("link_brain.sources", "link_brain.sources.xiaohongshu")}
    assert import_scan.violations(shared, g) == {("link_brain.ingest", "link_brain.sources.xiaohongshu.adapter")}
    assert import_scan.largest_cycle({("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")}) == 3


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        refused = write_baseline(allow_grow="--allow-grow" in sys.argv[1:])
        print(f"已重写 {BASELINE_FILE.relative_to(ROOT)}")
        if refused:
            print("这些变多的没写进去（确认是有意的再加 --allow-grow）：\n" + "\n".join(refused))
            sys.exit(1)
    else:
        base = load_baseline() if BASELINE_FILE.exists() else {}
        out = [m for name, now in current().items() for m in diff(name, now, base.get(name, {}))]
        print("\n".join(out) if out else "和基线一致")
        sys.exit(1 if out else 0)

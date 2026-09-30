"""推送前隐私闸（.githooks/pre-push 调用；fail-closed：扫不了就不许推）。

只查这次要推、远端还没有的提交，查三样：
1. 作者/提交者邮箱必须是 GitHub noreply（个人邮箱一旦进公开历史就只能重写历史才能删）。
2. 新增文件的类型：课表、录音、视频、cookie、密钥库、数据库这类私人文件一律不许进仓。
3. 新增行和提交说明：通用密钥特征 + 本机私有特征清单。

私有特征清单放 `.githooks/private-patterns.local.txt`（`*.local.*` 已被 ignore，不进仓库）：
一行一个字面串，不分大小写，# 开头是注释——主号 id 前缀、私人域名、个人邮箱之类。
写进公开脚本等于自己把它们公开了，所以只能放本机。清单不存在时拒推；
确实要在没有清单的机器上推，设 LWA_GATE_NO_PRIVATE=1。

命中只打印提交、文件、规则名，不打印命中的值。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_LIST = ROOT / ".githooks" / "private-patterns.local.txt"

NOREPLY = re.compile(r"(@users\.noreply\.github\.com|^noreply@github\.com)$", re.I)
BLOCKED_FILES = re.compile(
    r"(\.(ics|kdbx|pem|p12|pfx|key|m4a|mp3|wav|flac|mp4|mov|db|sqlite)$"
    r"|(^|/)cookies[^/]*\.json$|(^|/)\.env$)",
    re.I,
)
SECRETS = {
    "openai-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "bark key": re.compile(r"api\.day\.app/[A-Za-z0-9]{10,}"),
    "telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}"),
    "xhs session cookie": re.compile(r"web_session[\"'=:\s]+[0-9a-f]{20,}", re.I),
    "xhs share token": re.compile(r"xsec_token=AB[A-Za-z0-9%+/=_-]{20,}"),
    "xhs share short link": re.compile(r"xhslink\.cn/o/(?!FakeLink)[A-Za-z0-9]{9,}"),
}


def git(*args):
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def load_private():
    if not PRIVATE_LIST.exists():
        if os.environ.get("LWA_GATE_NO_PRIVATE") == "1":
            return []
        raise RuntimeError(f"missing {PRIVATE_LIST.relative_to(ROOT)} (set LWA_GATE_NO_PRIVATE=1 to push without it)")
    lines = PRIVATE_LIST.read_text(encoding="utf-8").splitlines()
    return [x.strip().lower() for x in lines if x.strip() and not x.strip().startswith("#")]


def scan_text(text, private):
    """返回命中的规则名（不带值）。"""
    hits = [name for name, rx in SECRETS.items() if rx.search(text)]
    low = text.lower()
    hits += [f"private pattern #{i + 1}" for i, pat in enumerate(private) if pat in low]
    return hits


def scan_commit(sha, private):
    problems = []
    who = git("show", "-s", "--format=%ae%n%ce", sha).split()
    for email in who:
        if not NOREPLY.search(email):
            problems.append("author/committer email is not a GitHub noreply address")
            break
    message = git("show", "-s", "--format=%B", sha)
    problems += [f"commit message: {h}" for h in scan_text(message, private)]
    diff = git("diff-tree", "-p", "--root", "-r", "-U0", "--no-color", "--no-ext-diff", sha)
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].rstrip()  # 带空格的文件名 git 会在末尾补一个 tab
            path = None if name == "/dev/null" else name.removeprefix("b/")
            if path and BLOCKED_FILES.search(path):
                problems.append(f"{path}: private file type")
        elif line.startswith("+") and path:
            problems += [f"{path}: {h}" for h in scan_text(line[1:], private)]
    return sorted(set(problems))


def main(argv):
    remote = "origin"
    if len(argv) >= 2 and argv[0] == "--remote":
        remote, argv = argv[1], argv[2:]
    tips = [a for a in argv if re.fullmatch(r"[0-9a-f]{40}", a)]
    if not tips:
        return 0
    try:
        private = load_private()
        exclude = [f"--remotes={remote}"] if git("for-each-ref", f"refs/remotes/{remote}").strip() else []
        commits = git("rev-list", *tips, "--not", *exclude).split() if exclude else git("rev-list", *tips).split()
        blocked = {}
        for sha in commits:
            found = scan_commit(sha, private)
            if found:
                blocked[sha] = found
    except Exception as exc:  # noqa: BLE001 - fail-closed：闸自己出错也不许推
        print(f"privacy gate could not run: {exc}", file=sys.stderr)
        return 2
    print(f"privacy gate: scanned {len(commits)} commit(s) not yet on {remote}")
    for sha, found in blocked.items():
        for item in found:
            print(f"  BLOCK {sha[:8]} {item}", file=sys.stderr)
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

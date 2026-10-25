"""推送前隐私闸（.githooks/pre-push 调用；fail-closed：扫不了就不许推）。

只查这次要推、远端还没有的提交，查三样：
1. 作者/提交者邮箱必须是 GitHub noreply（或 Claude Code 的 noreply@anthropic.com；个人邮箱一旦进公开历史就只能重写历史才能删）。
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

# noreply@anthropic.com：Claude Code 云端会话固定的提交身份（不是个人邮箱），1023 作者同意放行
NOREPLY = re.compile(r"(@users\.noreply\.github\.com|^noreply@github\.com|^noreply@anthropic\.com)$", re.I)
BLOCKED_FILES = re.compile(
    r"(\.(ics|kdbx|pem|p12|pfx|key|m4a|mp3|wav|flac|mp4|mov|db|sqlite)$"
    r"|(^|/)cookies[^/]*\.json$|(^|/)\.env$)",
    re.I,
)
# 白名单：公开仓里有意放的小样本（合成、不含任何私人内容），路径精确匹配。新增要在提交说明里写清来源。
ALLOWED_FILES = {
    "tests/fixtures/tiny-1s.mp4",  # 1 秒合成测试视频（纯色 + 静音，ffmpeg 生成），播放器 / 媒体工具的 UI 用例用
}
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


# 测试里故意埋的假密钥（验证「密钥永远读不到 / 不外泄」用）：值本身写明是占位的才放过，真样子的照拦。
PLACEHOLDER = re.compile(r"never-leak|fake|dummy|example|placeholder|not-a-real", re.I)


def scan_text(text, private):
    """返回命中的规则名（不带值）。"""
    hits = [name for name, rx in SECRETS.items()
            if any(not PLACEHOLDER.search(m.group(0)) for m in rx.finditer(text))]
    low = text.lower()
    hits += [f"private pattern #{i + 1}" for i, pat in enumerate(private) if pat in low]
    return hits


def blocked_path(path):
    return bool(BLOCKED_FILES.search(path)) and path not in ALLOWED_FILES


def added_paths(sha):
    """这个提交新增 / 改名 / 复制 / 修改进来的文件路径。

    1008：文件类型不能从 -p 补丁里的「+++ b/<路径>」认——二进制文件（mp4、db、kdbx…）的补丁只有一行
    「Binary files … differ」，没有 +++ 行，旧写法整个漏检。改从 --name-status 拿路径（-z：带空格 / 中文的名字原样）。"""
    out = git("diff-tree", "--root", "-r", "-z", "--no-renames", "--name-status", "--diff-filter=ACMRT", sha)
    parts = [x for x in out.split("\0") if x != ""]
    if parts and re.fullmatch(r"[0-9a-f]{40}", parts[0]):
        parts = parts[1:]  # 单个提交时开头是提交号
    return [parts[i + 1] for i in range(0, len(parts) - 1, 2)]


def scan_commit(sha, private, check_email=True):
    problems = []
    # 邮箱规则防的是作者个人邮箱进公开历史。只有 CI 入口（--base … --skip-email）才关得掉：pre-push 钩子不传这个开关，
    # 环境变量也不认（1025 Codex 审：原来的 LWA_GATE_SKIP_EMAIL 在本机 shell 里设上同样生效，等于给闸留了个口子）
    if check_email:
        who = git("show", "-s", "--format=%ae%n%ce", sha).split()
        if any(not NOREPLY.search(email) for email in who):
            problems.append("author/committer email is not a GitHub noreply address")
    message = git("show", "-s", "--format=%B", sha)
    problems += [f"commit message: {h}" for h in scan_text(message, private)]
    problems += [f"{path}: private file type" for path in added_paths(sha) if blocked_path(path)]
    diff = git("diff-tree", "-p", "--root", "-r", "-U0", "--no-color", "--no-ext-diff", sha)
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].rstrip()  # 带空格的文件名 git 会在末尾补一个 tab
            path = None if name == "/dev/null" else name.removeprefix("b/")
        elif line.startswith("+") and path:
            problems += [f"{path}: {h}" for h in scan_text(line[1:], private)]
    return sorted(set(problems))


def main(argv):
    remote = "origin"
    base = None  # CI：--base <sha> 只扫 base 之后的提交（PR 的头分支本身就在远端上，按「远端没有的」会扫出 0 个）
    if len(argv) >= 2 and argv[0] == "--remote":
        remote, argv = argv[1], argv[2:]
    if len(argv) >= 2 and argv[0] == "--base":
        base, argv = argv[1], argv[2:]
    skip_email = False  # 只在带 --base 的 CI 入口上认（别人的 PR 不按作者邮箱拦）；本机 hook 走不到这里
    if base and argv and argv[0] == "--skip-email":
        skip_email, argv = True, argv[1:]
    tips = [a for a in argv if re.fullmatch(r"[0-9a-f]{40}", a)]
    if not tips:
        return 0
    try:
        private = load_private()
        if base:
            commits = git("rev-list", *tips, f"^{base}").split()
        else:
            exclude = [f"--remotes={remote}"] if git("for-each-ref", f"refs/remotes/{remote}").strip() else []
            commits = git("rev-list", *tips, "--not", *exclude).split() if exclude else git("rev-list", *tips).split()
        blocked = {}
        for sha in commits:
            found = scan_commit(sha, private, check_email=not skip_email)
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

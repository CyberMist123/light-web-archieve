"""可选依赖与解释器（P0 1024，BUGS-1024 根因）。

1. `require(name, purpose)`：导入第三方包；缺了抛 `MissingDependency`（码 `NEEDS_HUMAN.MISSING_DEPENDENCY`，一句人话；
   不用 NOT_INSTALLED——那是「未安装读取组件」，账号类，撞见会整批停车），
   不再是裸 ModuleNotFoundError，也不许调用方悄悄退化——切词缺 jieba 时问答 / 搜索一律明确报错。
2. `python_exe()`：本程序该用哪个 Python。唯一配置 = 插件 data.json 的 `pythonPath`（插件「Python 路径」设置，
   插件起进程 / MCP 命令读同一个键，见 main.js `pickPython`）；没配按下面顺序找（1102 托管模式，docs/SETUP-CONTRACT.md「托管模式」）：
   ① 托管环境 `$LINK_BRAIN_HOME/py/`（插件「一键装好」用 uv 建的 venv；`config.json` 的 `backend_dir` 指到别处就用那个）；
   ② 程序目录下的 `.venv`——只在「源码仓库」里猜（程序目录下有 `link_brain/` 包和 `pyproject.toml`）；wheel 装进 site-packages 时
     `_repo_root()` 是 site-packages，那里的 `.venv` 不是我们的，不猜；
   ③ 当前解释器。
   配的是相对路径按程序目录解析（不按当前目录）；配了但找不到这个文件 → `PythonNotFound`，注册如实失败，不把坏路径写进计划任务。
   计划任务 / 后台常驻注册时写它的绝对路径，不再沿用「注册那一刻碰巧是谁」。插件 main.js `pickBackend` / `pickPython` 同一套顺序。
本模块顶部只导标准库：doctor 在缺依赖时也要能跑。
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

CODE = "NEEDS_HUMAN.MISSING_DEPENDENCY"
PYTHON_KEY = "pythonPath"
MANAGED_DIRNAME = "py"          # ~/.link-brain/py/：托管的 venv（升级装到 py-<版本>/，config.json 的 backend_dir 指过去）
BACKEND_DIR_KEY = "backend_dir"


class PythonNotFound(OSError):
    """设置里的「Python 路径」指的文件不存在（填错 / .venv 删了重建到别处）。str(exc) 是给人看的那句。"""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"设置里的 Python 路径找不到：{path}（设置 → 开发者 → Python 路径改对，或清空改用程序目录的 .venv）")


class MissingDependency(RuntimeError):
    """缺第三方包。code 是 §2 故障码；message 是给人看的那句（str(exc) 带上码，经 errtext 也看得到）。"""

    def __init__(self, name: str, purpose: str = ""):
        self.name = name
        self.purpose = purpose
        self.code = CODE
        self.message = f"缺依赖 {name}{('（' + purpose + '）') if purpose else ''}：请用项目 .venv 启动，或 pip install {name}"
        super().__init__(f"{CODE}：{self.message}")


def require(name: str, purpose: str = "") -> Any:
    """导入 `name` 并返回模块；没装（或装坏到导不进来）→ MissingDependency。"""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise MissingDependency(name, purpose) from exc


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def configured_python(vault: str | Path | None = None) -> str:
    """插件 data.json 的 pythonPath（去引号去空白）；读不到 / 没配 = ''。"""
    try:
        if vault is not None:
            from .ai_config import PLUGIN_ID
            path = Path(vault) / ".obsidian" / "plugins" / PLUGIN_ID / "data.json"
        else:
            from .ai_config import data_json_path
            path = data_json_path()
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = raw.get(PYTHON_KEY) if isinstance(raw, dict) else None
    return str(value or "").strip().strip('"').strip()


def _venv_exe(root: Path) -> Path:
    return root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def venv_python(root: Path | None = None) -> Path:
    root = root or _repo_root()
    return _venv_exe(root / ".venv")


def is_source_checkout(root: Path | None = None) -> bool:
    """程序目录是不是源码仓库（有 link_brain/ 包和 pyproject.toml）。wheel 装的 site-packages 不是，不许猜那里的 .venv。"""
    root = root or _repo_root()
    return (root / "link_brain" / "__init__.py").is_file() and (root / "pyproject.toml").is_file()


def _home() -> Path:
    return Path(os.environ.get("LINK_BRAIN_HOME") or str(Path.home() / ".link-brain"))


def managed_dir() -> Path:
    """托管环境目录：`~/.link-brain/config.json` 的 `backend_dir`（升级后指到 py-<版本>/）→ 默认 `~/.link-brain/py`。
    只读标准库 json（本模块不许导 storage：doctor 缺依赖时也要能跑）。"""
    home = _home()
    try:
        raw = json.loads((home / "config.json").read_text("utf-8-sig"))
        configured = raw.get(BACKEND_DIR_KEY) if isinstance(raw, dict) else None
    except (OSError, ValueError):
        configured = None
    if isinstance(configured, str) and configured.strip():
        p = Path(os.path.expandvars(configured.strip())).expanduser()
        return p if p.is_absolute() else home / p
    return home / MANAGED_DIRNAME


def managed_python() -> Path:
    """托管环境里的 python（Windows `py/Scripts/python.exe`，其他 `py/bin/python`）；存在与否由调用方判。"""
    return _venv_exe(managed_dir())


def python_exe(*, windowless: bool = False, vault: str | Path | None = None) -> str:
    """绝对路径。windowless=True（计划任务 / 后台常驻）：同目录有 pythonw.exe 就用它（不弹黑窗）。
    配了「Python 路径」但找不到 → PythonNotFound（OSError 的子类）。
    没配：托管环境 → 源码仓库的 .venv → 当前解释器（见模块说明）。"""
    own = configured_python(vault)
    if own:
        if Path(own).is_absolute():
            exe = Path(own)
        elif "/" in own or "\\" in own:
            exe = _repo_root() / own  # 相对路径按程序目录（输入框占位就是 .venv\Scripts\python.exe），不按当前目录
        else:
            exe = Path(shutil.which(own) or own)
        if not exe.is_file():
            raise PythonNotFound(str(exe))
    else:
        managed = managed_python()
        venv = venv_python()
        if managed.is_file():
            exe = managed
        elif is_source_checkout() and venv.is_file():
            exe = venv
        else:
            exe = Path(sys.executable)
    exe = exe.absolute()
    if windowless:
        cand = exe.with_name("pythonw.exe")
        if cand.is_file():
            return str(cand)
    return str(exe)

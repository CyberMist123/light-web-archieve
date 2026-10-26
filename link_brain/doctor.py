"""Read-only capability checks, shared by CLI and Obsidian.

P0 1024：模块顶部只导标准库和不带第三方依赖的本包模块（accounts 要 httpx，用到才导）——缺依赖时 doctor 自己得能跑，
并如实列出当前解释器和缺了什么。
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
from pathlib import Path

from . import ai_config, deps, storage

# 关键依赖（pyproject 的 dependencies）：(pip 名, 模块名, 用途, 当场导入?)。
# 轻的真导一次（装坏了也看得出）；重的（OCR 模型 / numpy）只看装没装，不为体检加载几秒。
KEY_DEPS = (
    ('jieba', 'jieba', '问答 / 搜索切词', True),
    ('pypinyin', 'pypinyin', '拼音搜索、目录', True),
    ('httpx', 'httpx', '调 AI 接口、读取组件', True),
    ('pyyaml', 'yaml', '笔记元数据', True),
    ('pillow', 'PIL', '图片', True),
    ('rapidocr', 'rapidocr', '本地认字', False),
    ('onnxruntime', 'onnxruntime', '本地认字', False),
    ('numpy', 'numpy', '语义检索', False),
    ('mcp', 'mcp', '接其他 AI', False),
    ('pypdfium2', 'pypdfium2', 'PDF 附件', False),
    ('python-docx', 'docx', 'Word 附件', False),
)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return default


# 插件目录里必须有的文件（main.js 按需 require 其余几个；第 5 批 B2 加了首次引导和并进来的图片导航；第 7 批加「开始」页向导，1009 换成设置页顶部 home-ui；10-03 加定时组件）
PLUGIN_FILES = ('main.js', 'manifest.json', 'library-ui.js', 'remote-ui.js', 'problems-ui.js', 'report-ui.js', 'usage-ui.js', 'onboarding-ui.js', 'media-nav.js',
                'home-ui.js', 'schedule-ui.js',  # 1009：设置页顶部（功能开关 + 一键装好 / 跑完）；10-03：灵活定时组件
                'note-actions.js', 'note-tools.js', 'image-actions.js', 'player-ui.js',  # 批次 D：onload 的四个挂载点
                'index-ui.js',  # 10-10 索引树（保存 索引.md 重算 / 起草 / 未归类建议 / wiki）
                'skills-ui.js',  # 1015 设置页「技能」页签（列 _skills、导入只拷文字文件）
                'settings-pages.js', 'settings-v6.js', 'provider-icons.js',
                'lb-theme.js')  # 1027 样式集（Aa 样式换算，和页面 LB.applyTheme 同一段）；1016 设置页排版；1018 v6 一页五张卡 + 首次设置；图标取自 Claudian（MIT）


def _importable(module: str, load: bool) -> bool:
    if load:
        try:
            deps.require(module)
            return True
        except deps.MissingDependency:
            return False
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def python_checks() -> dict:
    """当前解释器 + 关键依赖能不能导入；scheduled = 计划任务注册时会写的解释器（deps.python_exe）。"""
    rows = [dict(name=name, module=module, purpose=purpose, ok=_importable(module, load))
            for name, module, purpose, load in KEY_DEPS]
    scheduled_error = ''
    try:
        scheduled = deps.python_exe()
    except OSError as exc:  # PythonNotFound：设置里的 Python 路径找不到，照实说
        scheduled, scheduled_error = '', str(exc)
    return {'executable': sys.executable, 'version': platform.python_version(), 'scheduled': scheduled,
            'scheduled_error': scheduled_error, 'deps': rows, 'missing': [r['name'] for r in rows if not r['ok']]}


def _python_row(row, info: dict) -> dict:
    missing = info['missing']
    message = f"{info['executable']}（Python {info['version']}）" + (f"；缺 {'、'.join(missing)}" if missing else '；依赖齐')
    step = (f"请用项目 .venv 启动（设置 → 开发者 → Python 路径），或 pip install {' '.join(missing)}" if missing else '')
    detail = f"计划任务会用：{info['scheduled']}" if info.get('scheduled') else (info.get('scheduled_error') or '')
    bad = bool(missing or info.get('scheduled_error'))
    if info.get('scheduled_error') and not step:
        step = '设置 → 开发者 → Python 路径改对，或清空改用程序目录的 .venv'
    return row('python', 'Python 与依赖', 'error' if bad else 'ready', message, step, detail)


def _plain_row(key: str, label: str, state: str, message: str, next_step: str = '', detail: str = '',
               optional=False, action: str = '', account: str = '') -> dict:
    """accounts.row 的同形兜底：accounts 导不进来（缺 httpx）时用。"""
    return dict(id=key, label=label, state=state, message=message, next_step=next_step, detail=detail,
                optional=optional, action=action, account=account)


def dataview_ready(obs: Path) -> bool:
    """Dataview 装了、启用了、开了 JS 查询（目录 / 问答 / 回收站页都靠它渲染）。"""
    enabled = read_json(obs / 'community-plugins.json', [])
    dv = read_json(obs / 'plugins' / 'dataview' / 'data.json', {})
    return 'dataview' in enabled and dv.get('enableDataviewJs') is True


def diagnose(*, obsidian_dir: str | None = None, only=None) -> dict:
    try:
        from . import accounts
        row = accounts.row
    except ImportError:
        accounts, row = None, _plain_row
    info = python_checks()
    rows = [_python_row(row, info)]
    vault = storage.vault_root()
    parent = vault
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    ready = sys.version_info >= (3, 11) and os.access(parent, os.W_OK)
    rows.append(row('archive', '基础归档', 'ready' if ready else 'error',
                             '可用（本地存储）' if ready else '环境不可用',
                             '' if ready else '安装 Python 3.11+，并选择可写的归档文件夹。'))
    obs = Path(obsidian_dir) if obsidian_dir else vault / '.obsidian'
    enabled = read_json(obs / 'community-plugins.json', [])
    plugins = obs / 'plugins'
    installed = all((plugins / 'link-brain-actions' / name).is_file()
                    for name in PLUGIN_FILES)
    plugin_ready = installed and 'link-brain-actions' in enabled
    rows.append(row('obsidian', 'Obsidian 插件', 'ready' if plugin_ready else 'missing',
                             '已安装并启用' if plugin_ready else ('尚未启用' if installed else '未安装'),
                             '' if plugin_ready else '按 README 复制插件，然后在 Obsidian 社区插件中启用。', optional=True))
    dv_ready = dataview_ready(obs)
    rows.append(row('dataview', 'Dataview', 'ready' if dv_ready else 'missing',
                             '已启用 JS 查询' if dv_ready else '未检测到 / 未开启 JS',
                             '' if dv_ready else '安装并启用 Dataview，打开 Enable JavaScript Queries（目录页靠它显示，首版必装）。'))
    # 1025 第二波 PR④：RAW 目录健康——老代码崩在下载中留下的半截 vNNNN（没 manifest.json，不算版本、不动）、
    # 过期暂存目录（下次同一篇入库时自动清）。只报数，不改文件。
    try:
        health = storage.raw_health() if vault.exists() and (not only or only == 'local') else {}
    except OSError:
        health = {}
    half, stale = health.get('objects_with_incomplete_versions', 0), health.get('stale_staging_dirs', 0)
    rows.append(row('raw', 'RAW 版本', 'ready' if not (half or stale) else 'notice',
                             '版本目录完整' if not (half or stale) else
                             f'{half} 篇有写一半的旧版本目录，{stale} 个过期暂存目录',
                             '' if not (half or stale) else '不影响使用：半截目录不算版本，重新抓一次那篇就有完整版本；过期暂存目录在下次给同一篇写版本时自动清。',
                             optional=True))
    if (not only or only in ('xhs', 'favorites', 'attachments')) and accounts is not None:
        rows.append(accounts.xhs_status(deep=only is not None))
    try:
        from . import providers
        configured = providers.resolve('textAI', ai_config.with_model(ai_config.load())) is not None
    except (ImportError, OSError, ValueError, UnicodeError):
        configured = False
    rows.append(row('ai', 'AI', 'configured' if configured else 'unconfigured',
                             '已配置（未调用验证）' if configured else '可选，未配置',
                             '在下方 AI 设置中配置并点击「测试」。', optional=True))
    if only:
        rows = [r for r in rows if r['id'] == only or (r['id'] == 'xhs' and only in ('favorites', 'attachments')) or (only == 'local' and r['id'] in ('python', 'archive', 'obsidian', 'dataview', 'raw', 'ai'))]
    return {'core_ready': ready, 'xhs_ready': any(r['id'] == 'xhs' and r['state'] == 'ready' for r in rows),
            'vault': str(vault), 'python': info, 'checks': rows}


def run(args) -> int:
    result = diagnose(obsidian_dir=args.obsidian_dir, only=getattr(args, 'only', None))
    if args.json:
        try:
            from .read import dump_json
        except ImportError:   # read 连带要 yaml：缺依赖时照 dump_json 的写法直写 UTF-8 字节
            def dump_json(payload):
                line = json.dumps(payload, ensure_ascii=False) + '\n'
                if hasattr(sys.stdout, 'buffer'):
                    sys.stdout.flush()
                    sys.stdout.buffer.write(line.encode('utf-8'))
                    sys.stdout.buffer.flush()
                else:
                    sys.stdout.write(line)
        dump_json(result)
    else:
        marks = {'ready': '✅', 'configured': '○', 'unconfigured': '○', 'unknown': '⚠', 'missing': '⚠', 'notice': '⚠'}
        lines = []
        for r in result['checks']:
            lines.append(f"{r['label']} {marks.get(r['state'], '❌')} {r['message']}")
            if r['next_step']:
                lines.append('  下一步：' + r['next_step'])
        text = '\n'.join(lines) + '\n'
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout.buffer.write(text.encode('utf-8'))
        else:
            print(text, end='')
    return 0 if result['core_ready'] else 1

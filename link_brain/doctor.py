"""Read-only capability checks, shared by CLI and Obsidian."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import accounts, ai_config, storage


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return default


def diagnose(*, obsidian_dir: str | None = None, only=None) -> dict:
    rows = []
    vault = storage.vault_root()
    parent = vault
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    ready = sys.version_info >= (3, 11) and os.access(parent, os.W_OK)
    rows.append(accounts.row('archive', '基础归档', 'ready' if ready else 'error',
                             '可用（本地存储）' if ready else '环境不可用',
                             '' if ready else '安装 Python 3.11+，并选择可写的归档文件夹。'))
    obs = Path(obsidian_dir) if obsidian_dir else vault / '.obsidian'
    enabled = read_json(obs / 'community-plugins.json', [])
    plugins = obs / 'plugins'
    installed = all((plugins / 'link-brain-actions' / name).is_file()
                    for name in ('main.js', 'manifest.json', 'library-ui.js'))
    plugin_ready = installed and 'link-brain-actions' in enabled
    rows.append(accounts.row('obsidian', 'Obsidian 插件', 'ready' if plugin_ready else 'missing',
                             '已安装并启用' if plugin_ready else ('尚未启用' if installed else '未安装'),
                             '' if plugin_ready else '按 README 复制插件，然后在 Obsidian 社区插件中启用。', optional=True))
    dv = read_json(plugins / 'dataview' / 'data.json', {})
    dv_ready = 'dataview' in enabled and dv.get('enableDataviewJs') is True
    rows.append(accounts.row('dataview', 'Dataview', 'ready' if dv_ready else 'missing',
                             '已启用 JS 查询' if dv_ready else '未检测到 / 未开启 JS',
                             '' if dv_ready else '安装并启用 Dataview，打开 Enable JavaScript Queries。', optional=True))
    if not only or only in ('xhs', 'favorites', 'attachments'):
        rows.append(accounts.xhs_status(deep=only is not None))
    ai = ai_config.load().get('textAI') or {}
    from .text_stream import default_http_config
    try:
        configured = (bool(ai.get('endpoint')) if ai.get('mode') == 'http'
                      else bool(default_http_config(ai).get('apiKey')))
    except (OSError, ValueError, UnicodeError):
        configured = False
    rows.append(accounts.row('ai', 'AI', 'configured' if configured else 'unconfigured',
                             '已配置（未调用验证）' if configured else '可选，未配置',
                             '在下方 AI 设置中配置并点击「测试」。', optional=True))
    if only:
        rows = [r for r in rows if r['id'] == only or (r['id'] == 'xhs' and only in ('favorites', 'attachments')) or (only == 'local' and r['id'] in ('archive', 'obsidian', 'dataview', 'ai'))]
    return {'core_ready': ready, 'xhs_ready': any(r['id'] == 'xhs' and r['state'] == 'ready' for r in rows),
            'vault': str(vault), 'checks': rows}


def run(args) -> int:
    from .read import dump_json
    result = diagnose(obsidian_dir=args.obsidian_dir, only=getattr(args, 'only', None))
    if args.json:
        dump_json(result)
    else:
        marks = {'ready': '✅', 'configured': '○', 'unconfigured': '○', 'unknown': '⚠', 'missing': '⚠'}
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

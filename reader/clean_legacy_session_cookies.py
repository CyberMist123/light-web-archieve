"""Offline, opt-in repair of the old 30-day security-cookie persistence policy.

Default is metadata-only preview. Never opens a browser or reads cookie values.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

SECURITY_COOKIES = {'websectiga', 'sec_poison_id', 'acw_tc'}
MARKER = 'legacy-session-cookie-cleanup.json'
THIRTY_DAYS_US = 30 * 86400 * 1_000_000


def site_domain(domain):
    d = domain.lower().removeprefix('.')
    return any(d == root or d.endswith('.' + root) for root in ('xiaohongshu.com', 'rednote.com'))


def candidate(row):
    # last_update_utc and expires_utc use Chromium microseconds. The old CDP
    # write set expiry to now + 30 days. Natural/session cookies stay untouched.
    _, domain, name, _, expires, updated, persistent = row
    return (site_domain(domain) and name in SECURITY_COOKIES and persistent == 1
            and updated > 0 and abs(expires - updated - THIRTY_DAYS_US) <= 120 * 1_000_000)


def require_closed(profile):
    if os.name != 'nt':
        raise RuntimeError('此维护工具目前只支持 Windows；不会自动停止进程')
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'chrome|chromium|reader|xiaohongshu' } | Select-Object Name,CommandLine | ConvertTo-Json -Compress"
    raw = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], text=True, encoding='utf-8')
    processes = json.loads(raw) if raw.strip() else []
    if isinstance(processes, dict):
        processes = [processes]
    target = str(profile.resolve()).lower().replace('/', '\\')
    for proc in processes:
        name = (proc.get('Name') or '').lower()
        cmd = (proc.get('CommandLine') or '').lower().replace('/', '\\')
        if 'reader' in name or 'xiaohongshu' in name or target in cmd or not cmd:
            raise RuntimeError('Reader 或关联浏览器仍在运行/无法确认已关闭；未清理')


def clean(profile, *, apply=False, closed=require_closed):
    profile = Path(profile).resolve(strict=True)
    marker = profile / MARKER
    if marker.exists():
        return {'state': 'already_done', 'deleted': 0}
    closed(profile)
    databases = list(profile.glob('*/Network/Cookies'))
    if not databases:
        raise RuntimeError('未找到 Chromium Cookies 数据库')
    selected = []
    for db in databases:
        with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
            rows = conn.execute('SELECT rowid,host_key,name,path,expires_utc,last_update_utc,is_persistent FROM cookies').fetchall()
        selected.extend((db, row) for row in rows if candidate(row))
    preview = [{'database': str(db.relative_to(profile)), 'domain': row[1], 'name': row[2], 'path': row[3]} for db, row in selected]
    result = {'state': 'preview', 'count': len(selected), 'cookies': preview}
    if not apply:
        return result
    closed(profile)
    backup = profile.with_name(profile.name + '.before-cookie-cleanup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copytree(profile, backup)
    closed(profile)
    deleted = 0
    for db in databases:
        with sqlite3.connect(db) as conn:
            for selected_db, row in selected:
                if selected_db == db:
                    deleted += conn.execute('DELETE FROM cookies WHERE rowid=? AND host_key=? AND name=? AND path=? AND expires_utc=? AND last_update_utc=? AND is_persistent=?', row).rowcount
    result.update(state='cleaned', deleted=deleted, backup=str(backup))
    marker.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='备份后执行一次清理；不传则只预览')
    args = parser.parse_args()
    try:
        print(json.dumps(clean(args.profile, apply=args.apply), ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'清理未完成：{exc}\n')

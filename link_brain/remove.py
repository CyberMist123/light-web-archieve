"""回收站：恢复归档和批注；彻底删除仍保留同步屏蔽记录。"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import index as index_mod, storage
from .read import EXIT_ERROR, EXIT_OK, dump_json


def _trash_path(relative: str) -> Path:
    root = (storage.vault_root() / '_trash').resolve()
    target = (storage.vault_root() / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError('回收站路径越界')
    return target


def delete_item(conn, item_id: str) -> dict[str, Any]:
    row = index_mod.get_object(conn, item_id)
    if row is None:
        return {'item_id': item_id, 'status': 'missing'}
    from .render import sanitize_title
    vault = storage.vault_root()
    obj = storage.object_dir(row['source'], row['source_id'])
    meta = storage.read_json(obj / 'meta.json') if (obj / 'meta.json').exists() else {}
    visible = meta.get('visible_note') or row['visible_note']
    relative = f"_trash/{row['source']}/{row['source_id']}"
    trash = _trash_path(relative)
    trash.mkdir(parents=True, exist_ok=True)
    snapshot = {table: [dict(r) for r in conn.execute(
        f'SELECT * FROM {table} WHERE item_id = ?', (item_id,))]
        for table in ('objects', 'sources', 'relations')}
    snapshot['objects'][0]['visible_note'] = visible
    files = []
    candidates = [vault / visible] if visible else []
    # 1001（审计 render-8）：她改过名 / 挪过位置的、以前同步冒出来的重复份，按 frontmatter 的 item_id 一起收进回收站
    from .render import find_visible_by_item_id
    seen = {p.resolve() for p in candidates}
    for extra in find_visible_by_item_id(item_id):
        if extra.resolve() not in seen:
            seen.add(extra.resolve())
            candidates.append(extra)
    # 旧版 ⭐ 会把可见笔记复制到 vault 根；副本机制已删，这里仍要清扫历史遗留副本
    star = vault / f"{sanitize_title(meta.get('title') or row['title'] or '未命名收藏')}.md"
    if star.exists():
        text = star.read_text(encoding='utf-8')
        if item_id in text or row['source_id'] in text:
            candidates.append(star)
    for n, file in enumerate(candidates):
        if file.exists():
            saved = f'notes/{n}-{file.name}'
            (trash / 'notes').mkdir(exist_ok=True)
            files.append({'original': file.relative_to(vault).as_posix(), 'saved': saved})
    cover = ''
    data = vault / '_archive/catalog-data.json'
    if data.exists():
        entry = next((x for x in storage.read_json(data).get('items', []) if x['id'] == item_id), {})
        cover = entry.get('cover') or ''
    original_prefix = obj.relative_to(vault).as_posix()
    if cover.startswith(original_prefix + '/'):
        cover = relative + '/object/' + cover[len(original_prefix) + 1:]
    storage.write_json(trash / 'restore.json', {'tables': snapshot, 'files': files})
    for file in files:
        shutil.move(str(vault / file['original']), str(trash / file['saved']))
    if obj.exists():
        shutil.move(str(obj), str(trash / 'object'))
    conn.execute('INSERT OR REPLACE INTO tombstones VALUES (?,?,?,?,?,?,?,?)', (
        row['source'], row['source_id'], item_id, row['title'], row['canonical_url'],
        cover, datetime.now(timezone.utc).isoformat(), relative))
    conn.execute('DELETE FROM objects WHERE item_id = ?', (item_id,))
    conn.commit()
    return {'item_id': item_id, 'status': 'deleted', 'note': visible}


def restore_item(conn, item_id: str) -> dict:
    row = conn.execute('SELECT * FROM tombstones WHERE item_id = ?', (item_id,)).fetchone()
    if not row:
        return {'item_id': item_id, 'status': 'missing'}
    trash = _trash_path(row['trash_dir'])
    if not (trash / 'restore.json').exists():
        return {'item_id': item_id, 'status': 'purged', 'error': '文件已彻底删除，无法恢复'}
    snapshot = storage.read_json(trash / 'restore.json')
    vault = storage.vault_root()
    obj = storage.object_dir(row['source'], row['source_id'])
    targets = [vault / f['original'] for f in snapshot['files']]
    if obj.exists() or any(p.exists() for p in targets):
        raise FileExistsError('原位置已有文件，未覆盖；请先处理重名文件')
    if (trash / 'object').exists():
        obj.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash / 'object'), str(obj))
    for file, target in zip(snapshot['files'], targets):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash / file['saved']), str(target))
    for table in ('objects', 'sources', 'relations'):
        for record in snapshot['tables'][table]:
            record = {k: v for k, v in record.items() if k != 'id'}
            conn.execute(f"INSERT INTO {table} ({','.join(record)}) VALUES ({','.join('?' for _ in record)})", tuple(record.values()))
    conn.execute('DELETE FROM tombstones WHERE item_id = ?', (item_id,))
    conn.commit()
    shutil.rmtree(trash)
    return {'item_id': item_id, 'status': 'restored', 'visible_note': snapshot['tables']['objects'][0]['visible_note']}


def purge_item(conn, item_id: str) -> dict:
    row = conn.execute('SELECT * FROM tombstones WHERE item_id = ?', (item_id,)).fetchone()
    if not row:
        return {'item_id': item_id, 'status': 'missing'}
    trash = _trash_path(row['trash_dir'])
    if trash.exists():
        shutil.rmtree(trash)
    return {'item_id': item_id, 'status': 'purged'}


def publish_trash(vault=None):
    vault = vault or storage.vault_root()
    conn = index_mod.connect(vault / '_archive/index.db')
    try:
        items = [dict(r) for r in conn.execute('SELECT * FROM tombstones ORDER BY deleted_at DESC')]
    finally:
        conn.close()
    for item in items:
        item['restorable'] = (vault / item['trash_dir'] / 'restore.json').exists()
        item['has_files'] = (vault / item['trash_dir']).exists()
    storage.write_json(vault / '_archive/trash-data.json', {'items': items})
    script = (Path(__file__).parent / 'assets/trash-view.js').read_text(encoding='utf-8')
    # 第 3 批：页头带 lb-page: trash，她改了名也按标记找回那一份重写（不再按固定名另冒一份「回收站.md」）
    from .catalog import library_pages
    page = library_pages(vault)['trash']
    storage.atomic_write_text(vault / page, '---\nlb-page: trash\n---\n\n# 回收站\n\n删除的收藏不会再次同步。请在「设置 → 文件与链接 → 排除的文件」加入 `_trash`。\n\n```dataviewjs\n' + script + '\n```\n')


def _one(action, conn, item_id: str) -> dict[str, Any]:
    """CONVENTIONS §1.3：逐条单独 try，一条抛错不吞掉其余结果；失败那条带一句能给用户看的原因。"""
    try:
        return action(conn, item_id)
    except Exception as exc:  # noqa: BLE001 - 逐条兜底，原因交给页面
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        reason = (str(exc) or type(exc).__name__)[:200]
        if isinstance(exc, PermissionError):
            reason = '文件被占用或没有权限：' + reason
        # 用户自己点的操作：原因当场给她看，不进问题记录，故障码留空
        return {'item_id': item_id, 'status': 'failed', 'code': '', 'error': reason}


def _summary(outcome: dict, verb: str, ok_status: str) -> dict:
    results = outcome['results']
    done = sum(r['status'] == ok_status for r in results)
    bad = [r for r in results if r['status'] != ok_status]
    outcome['ok'] = not bad
    outcome['code'] = '' if not bad else (bad[0].get('code') or '')
    if not bad:
        outcome['message'] = f'已{verb} {done} 篇'
    else:
        why = bad[0].get('error') or ('不在库里' if bad[0]['status'] == 'missing' else bad[0]['status'])
        outcome['message'] = (f'已{verb} {done} 篇；' if done else '') + f'{len(bad)} 篇没{verb}掉：{why}'
    for r in bad:
        if r['status'] == 'missing':
            r.setdefault('error', '库里没有这一篇（可能已经删过）')
    return outcome


def delete_items(item_ids: list[str]) -> dict[str, Any]:
    conn = index_mod.connect()
    try:
        results = [_one(delete_item, conn, i) for i in item_ids]
    finally:
        conn.close()
    return _summary({'deleted': sum(r['status'] == 'deleted' for r in results), 'results': results}, '删', 'deleted')


def run(args) -> int:
    outcome = {'results': []}
    try:
        if args.command == 'delete':
            outcome = delete_items(args.item_ids)
        else:
            conn = index_mod.connect()
            try:
                ids = args.item_ids
                if args.action == 'empty':
                    ids = [r['item_id'] for r in conn.execute('SELECT item_id FROM tombstones')]
                action = restore_item if args.action == 'restore' else purge_item
                ok_status = 'restored' if args.action == 'restore' else 'purged'
                outcome = _summary({'results': [_one(action, conn, i) for i in ids]},
                                   '恢复' if args.action == 'restore' else '彻底删除', ok_status)
            finally:
                conn.close()
    finally:
        # 前面几条可能已经进了回收站：不管后面怎样都重建目录，页面才和磁盘一致
        try:
            from . import catalog
            catalog.build()
        except Exception as exc:  # noqa: BLE001
            outcome['catalog_error'] = (str(exc) or type(exc).__name__)[:200]
            print('目录没重建上：' + outcome['catalog_error'], file=sys.stderr)
    dump_json(outcome)
    return EXIT_OK if outcome.get('ok') else EXIT_ERROR

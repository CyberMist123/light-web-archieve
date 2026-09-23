"""回收站：恢复归档和批注；彻底删除仍保留同步屏蔽记录。"""
from __future__ import annotations

import shutil
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
    (vault / '回收站.md').write_text('# 回收站\n\n删除的收藏不会再次同步。请在「设置 → 文件与链接 → 排除的文件」加入 `_trash`。\n\n```dataviewjs\n' + script + '\n```\n', encoding='utf-8')


def delete_items(item_ids: list[str]) -> dict[str, Any]:
    conn = index_mod.connect()
    try:
        results = [delete_item(conn, i) for i in item_ids]
    finally:
        conn.close()
    return {'deleted': sum(r['status'] == 'deleted' for r in results), 'results': results}


def run(args) -> int:
    if args.command == 'delete':
        outcome = delete_items(args.item_ids)
    else:
        conn = index_mod.connect()
        try:
            ids = args.item_ids
            if args.action == 'empty':
                ids = [r['item_id'] for r in conn.execute('SELECT item_id FROM tombstones')]
            action = restore_item if args.action == 'restore' else purge_item
            outcome = {'results': [action(conn, i) for i in ids]}
        finally:
            conn.close()
    from . import catalog
    catalog.build()
    dump_json(outcome)
    return EXIT_ERROR if any(r['status'] == 'missing' or r.get('error') for r in outcome['results']) else EXIT_OK

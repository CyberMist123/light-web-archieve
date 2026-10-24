"""回收站：恢复归档和批注；彻底删除仍保留同步屏蔽记录。"""
from __future__ import annotations

import json
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
    """删一篇进回收站。顺序（1024 p0-tomb）：
    ① 写 restore.json（续删时沿用上次那份，不重算——已挪走的文件不在原处了，重算会把它们从恢复清单里丢掉）
    ② 写屏蔽 state=pending（先 tombstones.jsonl 再 index.db）——从这一刻起同步不会再把它拉回来
    ③ 挪文件（已挪过的跳过）
    ④ 删 objects 行 + 屏蔽标 done 一起提交，再往 jsonl 追加一行 done
    半路崩了：屏蔽一直在（pending）；再删一次 / 恢复 / 下次跑 trash 命令时从断点接着做完（finish_pending）。
    """
    row = index_mod.get_object(conn, item_id)
    if row is None:
        tomb = conn.execute("SELECT * FROM tombstones WHERE item_id = ? AND state = 'pending'", (item_id,)).fetchone()
        if tomb is not None:
            # objects 行已经删掉（④ 提交过，或 index.db 重建过）：文件要是还在原处就收进回收站，再标完成
            return _finish_without_row(conn, dict(tomb))
        return {'item_id': item_id, 'status': 'missing'}
    from .render import sanitize_title
    vault = storage.vault_root()
    obj = storage.object_dir(row['source'], row['source_id'])
    relative = f"_trash/{row['source']}/{row['source_id']}"
    trash = _trash_path(relative)
    trash.mkdir(parents=True, exist_ok=True)
    pending = conn.execute("SELECT * FROM tombstones WHERE item_id = ? AND state = 'pending'", (item_id,)).fetchone()
    if pending is not None and (trash / 'restore.json').exists():
        saved_restore = storage.read_json(trash / 'restore.json')
        files, visible = saved_restore['files'], saved_restore['tables']['objects'][0]['visible_note']
        cover = pending['cover'] or ''
    else:
        meta = storage.read_json(obj / 'meta.json') if (obj / 'meta.json').exists() else {}
        visible = meta.get('visible_note') or row['visible_note']
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
    record = {'source': row['source'], 'source_id': row['source_id'], 'item_id': item_id, 'title': row['title'],
              'url': row['canonical_url'], 'cover': cover, 'trash_dir': relative,
              'deleted_at': pending['deleted_at'] if pending is not None else datetime.now(timezone.utc).isoformat()}
    if pending is None:
        index_mod.write_tombstone(conn, {**record, 'state': 'pending'})
    _move_into_trash(vault, obj, trash, files)
    conn.execute('DELETE FROM objects WHERE item_id = ?', (item_id,))
    conn.execute("UPDATE tombstones SET state = 'done' WHERE item_id = ?", (item_id,))
    conn.commit()
    out = {'item_id': item_id, 'status': 'deleted', 'note': visible}
    try:
        index_mod.write_tombstone(conn, {**record, 'state': 'done'})
    except OSError as exc:
        # ④ 已提交：文件在回收站、objects 行已删，这篇确实删了；jsonl 最后一行还是 pending，下次 connect 对齐后续删补上 done
        from .errtext import errtext
        out['warning'] = f'收尾没记完（{errtext(exc)}），下次自动补'
        print(f'[remove] {item_id} {out["warning"]}', file=sys.stderr)
    # 1008（L6·B2）：删掉这篇 = 它名下没解决的问题一并标已解决（问题面板唯一的「真删除」）；永不抛异常
    from . import problems
    problems.resolve_item(item_id)
    return out


def _move_into_trash(vault: Path, obj: Path, trash: Path, files: list[dict]) -> None:
    """③：已经挪过的跳过（续删时用）。"""
    for file in files:
        src, dst = vault / file['original'], trash / file['saved']
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
    if obj.exists() and not (trash / 'object').exists():
        shutil.move(str(obj), str(trash / 'object'))


def _finish_without_row(conn, tomb: dict) -> dict[str, Any]:
    """pending 屏蔽、objects 行已经没了：按 restore.json 把还留在原处的文件收进回收站，再标完成。"""
    vault = storage.vault_root()
    trash = _trash_path(tomb['trash_dir'])
    saved = storage.read_json(trash / 'restore.json') if (trash / 'restore.json').exists() else {'files': []}
    _move_into_trash(vault, storage.object_dir(tomb['source'], tomb['source_id']), trash, saved['files'])
    index_mod.write_tombstone(conn, {**tomb, 'state': 'done'})
    from . import problems
    problems.resolve_item(tomb['item_id'])
    return {'item_id': tomb['item_id'], 'status': 'deleted', 'note': None}


def finish_pending(conn, skip=()) -> list[dict]:
    """把上次半路崩掉的删除接着做完（幂等）；一条出错不影响别的，原因放进结果里。skip = 这次刚处理过的。"""
    ids = [r['item_id'] for r in conn.execute("SELECT item_id FROM tombstones WHERE state = 'pending'")
           if r['item_id'] not in skip]
    return [_one(delete_item, conn, i) for i in ids]


def restore_item(conn, item_id: str) -> dict:
    row = conn.execute('SELECT * FROM tombstones WHERE item_id = ?', (item_id,)).fetchone()
    if not row:
        return {'item_id': item_id, 'status': 'missing'}
    if row['state'] == 'pending':
        delete_item(conn, item_id)  # 删到一半崩了：先把删除做完，文件全在回收站里再整份挪回去
        row = conn.execute('SELECT * FROM tombstones WHERE item_id = ?', (item_id,)).fetchone()
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
            if table == 'relations':
                # 1024 之前的快照里可能带着重复行：走同一个去重插入，恢复回来不再变回多行
                index_mod.add_relation(conn, **record, commit=False)
                continue
            conn.execute(f"INSERT INTO {table} ({','.join(record)}) VALUES ({','.join('?' for _ in record)})", tuple(record.values()))
    # 解除屏蔽：jsonl 先记。崩在提交前 = 文件已回原处、索引没写上，跑一次 reindex 就补回来，不会被屏蔽卡住
    index_mod.clear_tombstone(conn, row, 'restore', commit=False)
    conn.commit()
    shutil.rmtree(trash)
    return {'item_id': item_id, 'status': 'restored', 'visible_note': snapshot['tables']['objects'][0]['visible_note']}


def purge_item(conn, item_id: str) -> dict:
    row = conn.execute('SELECT * FROM tombstones WHERE item_id = ?', (item_id,)).fetchone()
    if not row:
        return {'item_id': item_id, 'status': 'missing'}
    if row['state'] == 'pending':
        # 删到一半（对象目录还在 _archive）：先把删除做完再删回收站，不然对象留在原处，下次续删又冒回回收站（复审 tomb#2）。
        # 还是挪不动就抛，如实报「没删掉」
        delete_item(conn, item_id)
        row = conn.execute('SELECT * FROM tombstones WHERE item_id = ?', (item_id,)).fetchone()
    trash = _trash_path(row['trash_dir'])
    if trash.exists():
        shutil.rmtree(trash)
    return {'item_id': item_id, 'status': 'purged'}


def forget_item(conn, item_id: str) -> dict:
    """1023：已彻底删除的记录「重新导入」前先去掉屏蔽记录；文件还在的（能恢复的）不走这里，要用恢复。"""
    row = conn.execute('SELECT * FROM tombstones WHERE item_id = ?', (item_id,)).fetchone()
    if not row:
        return {'item_id': item_id, 'status': 'missing'}
    if _trash_path(row['trash_dir']).exists():
        return {'item_id': item_id, 'status': 'failed', 'code': '', 'error': '文件还在回收站里，请用「恢复」'}
    index_mod.clear_tombstone(conn, row, 'forget')  # 1024：解除屏蔽也记进 tombstones.jsonl，重建 index.db 不会又屏蔽回去
    # tombstones 表的列叫 url（以前读 canonical_url，真库上每次都抛 IndexError，重新导入一直失败）
    return {'item_id': item_id, 'status': 'forgotten', 'url': row['url']}


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
    from .catalog import _write_if_changed  # 1023：内容没变不写，不让 Dataview 重画
    _write_if_changed(vault / '_archive/trash-data.json', json.dumps({'items': items}, ensure_ascii=False, indent=2) + '\n')
    script = (Path(__file__).parent / 'assets/trash-view.js').read_text(encoding='utf-8')
    # 第 3 批：页头带 lb-page: trash，她改了名也按标记找回那一份重写（不再按固定名另冒一份「回收站.md」）
    # 批次 D · C16：和目录页同一套前导（lb-page-lib 内联在前面：host、样式挂 head、提示 / 确认 / busy、手机只读）；
    # 标题和说明挪进页面脚本里画（cssclasses 让外框隐形规则只作用在这一页）
    from .catalog import _PAGE_LIB, library_pages
    page = library_pages(vault)['trash']
    _write_if_changed(vault / page, '---\nlb-page: trash\ncssclasses: [lb-trashpage]\n---\n\n```dataviewjs\n' + _PAGE_LIB + '\n' + script + '\n```\n')


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
        leftover = finish_pending(conn, skip=item_ids)
    finally:
        conn.close()
    outcome = _summary({'deleted': sum(r['status'] == 'deleted' for r in results), 'results': results}, '删', 'deleted')
    return _report_unfinished(outcome, leftover)


def _report_unfinished(outcome: dict, leftover: list[dict]) -> dict:
    """以前半路崩掉的删除这次顺带做完；还没做完的照实说（它们一直被屏蔽着，不会被同步拉回来）。
    顺带做完的放进 finished：目录快速更新要连它们一起摘（Codex 1025）。"""
    finished = [r for r in leftover if r['status'] == 'deleted']
    if finished:
        outcome['finished'] = finished
    bad = [r for r in leftover if r['status'] != 'deleted']
    if bad:
        outcome['unfinished'] = bad
        outcome['message'] = outcome.get('message', '') + f'；另有 {len(bad)} 篇上次没删完，还在屏蔽中：{bad[0].get("error") or bad[0]["status"]}'
        print('上次没删完：' + outcome['message'], file=sys.stderr)
    return outcome


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
                action, ok_status, verb = {
                    'restore': (restore_item, 'restored', '恢复'),
                    'forget': (forget_item, 'forgotten', '解除屏蔽'),
                }.get(args.action, (purge_item, 'purged', '彻底删除'))
                outcome = _summary({'results': [_one(action, conn, i) for i in ids]}, verb, ok_status)
                _report_unfinished(outcome, finish_pending(conn, skip=ids))
            finally:
                conn.close()
    finally:
        # 前面几条可能已经进了回收站：不管后面怎样都重建目录，页面才和磁盘一致
        try:
            from . import catalog
            done = [r.get('item_id') for r in (outcome.get('results') or []) + (outcome.get('finished') or [])
                    if r.get('status') == 'deleted']
            if args.command == 'delete' and outcome.get('ok') and catalog.drop_items(done):
                publish_trash()  # 1019：删除只摘目录数据里这几篇 + 刷回收站，不整份重建（快十几秒）
            else:
                catalog.build()
        except Exception as exc:  # noqa: BLE001
            outcome['catalog_error'] = (str(exc) or type(exc).__name__)[:200]
            print('目录没重建上：' + outcome['catalog_error'], file=sys.stderr)
    dump_json(outcome)
    return EXIT_OK if outcome.get('ok') else EXIT_ERROR

"""1023：回收站「记录」里重新导入——forget 只解除已彻底删除记录的屏蔽，文件还在的不动。"""
from types import SimpleNamespace

from link_brain import remove


class _Conn:
    def __init__(self, row):
        self.row, self.deleted, self.committed = row, False, False

    def execute(self, sql, params=()):
        if sql.startswith('DELETE'):
            self.deleted = True
        return SimpleNamespace(fetchone=lambda: self.row)

    def commit(self):
        self.committed = True


def test_forget_purged_record(tmp_path, monkeypatch):
    # 1024：用真 index.db——以前的假行用了 canonical_url，可 tombstones 表的列叫 url，真库上 forget 每次都抛错
    from link_brain import index as index_mod, storage
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    conn = index_mod.connect()
    index_mod.write_tombstone(conn, {'source': 'x', 'source_id': '1', 'item_id': 'x-1', 'url': 'https://example.com/a',
                                     'deleted_at': '2026-10-01', 'trash_dir': '_trash/x/1'})
    r = remove.forget_item(conn, 'x-1')
    assert r == {'item_id': 'x-1', 'status': 'forgotten', 'url': 'https://example.com/a'}
    assert conn.execute('SELECT COUNT(*) FROM tombstones').fetchone()[0] == 0
    conn.close()


def test_forget_refuses_when_files_still_there(tmp_path, monkeypatch):
    (tmp_path / 'still').mkdir()
    monkeypatch.setattr(remove, '_trash_path', lambda rel: tmp_path / 'still')
    conn = _Conn({'trash_dir': '_trash/x/1', 'canonical_url': 'u'})
    r = remove.forget_item(conn, 'x-1')
    assert r['status'] == 'failed' and '恢复' in r['error'] and not conn.deleted


def test_forget_missing():
    assert remove.forget_item(_Conn(None), 'x-1')['status'] == 'missing'

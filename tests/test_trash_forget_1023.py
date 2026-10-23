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
    monkeypatch.setattr(remove, '_trash_path', lambda rel: tmp_path / 'gone')
    conn = _Conn({'trash_dir': '_trash/x/1', 'canonical_url': 'https://example.com/a'})
    r = remove.forget_item(conn, 'x-1')
    assert r == {'item_id': 'x-1', 'status': 'forgotten', 'url': 'https://example.com/a'}
    assert conn.deleted and conn.committed


def test_forget_refuses_when_files_still_there(tmp_path, monkeypatch):
    (tmp_path / 'still').mkdir()
    monkeypatch.setattr(remove, '_trash_path', lambda rel: tmp_path / 'still')
    conn = _Conn({'trash_dir': '_trash/x/1', 'canonical_url': 'u'})
    r = remove.forget_item(conn, 'x-1')
    assert r['status'] == 'failed' and '恢复' in r['error'] and not conn.deleted


def test_forget_missing():
    assert remove.forget_item(_Conn(None), 'x-1')['status'] == 'missing'

"""Shared attachment queues skip sources without attachment support."""
import sys
import types

from link_brain import attachments, sources, storage


def test_queue_skips_source_without_attachments(tmp_path, monkeypatch):
    fake = types.ModuleType("fake_attachment_source")
    fake.name, fake.capabilities = "fakesite", frozenset()
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setitem(sources._REGISTRY, fake.name, fake.__name__)
    monkeypatch.setenv(storage.ENV_VAULT, str(tmp_path))
    obj = storage.object_dir(fake.name, "item42")
    storage.write_json(obj / "meta.json", {"source": fake.name, "source_id": "item42",
                                         "item_id": "fake-item42", "current_version": 1})

    def no_open(*args, **kwargs):
        raise AssertionError("source without attachments opened a page")

    fake.attachment_backend = no_open
    assert attachments.recheck_queues() == {"guest": [], "tail": [], "gone": 0, "unprobed": 0}
    assert attachments.reconcile() == {"cleared": 0, "declared": 0, "gone": 0}
    assert attachments.download_for_object(fake.name, "item42") == {"item_id": "fake-item42", "results": []}
    assert attachments.grab_after_ingest(fake.name, "item42") == ""

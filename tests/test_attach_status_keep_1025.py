"""1025：重抓不把已下载的附件状态降回 metadata_only（其余情况照抓到的走）。"""
from link_brain.ingest import merge_meta


def test_refetch_keeps_downloaded_attachments():
    old = {"attachments_status": "downloaded", "title": "t"}
    fetched = {"attachments_status": "metadata_only", "title": "t"}
    assert merge_meta(old, fetched)["attachments_status"] == "downloaded"


def test_refetch_other_attachment_changes_follow_fetch():
    assert merge_meta({"attachments_status": "downloaded"}, {"attachments_status": "none"})["attachments_status"] == "none"
    assert merge_meta({"attachments_status": "metadata_only"}, {"attachments_status": "downloaded"})["attachments_status"] == "downloaded"
    assert merge_meta(None, {"attachments_status": "metadata_only"})["attachments_status"] == "metadata_only"

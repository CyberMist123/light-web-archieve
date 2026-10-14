"""1015 她 C11：全库评论多少被判成水话（机读版略去）、有没有误伤——只读统计 + 一行话 + 可能误伤的例子。"""

import json

from link_brain import agentmd, cli, storage


def _post(vault, sid, comments):
    d = vault / "_archive" / "xiaohongshu" / sid
    (d / "raw" / "v0001").mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"current_version": 1}), encoding="utf-8")
    (d / "raw" / "v0001" / "source.json").write_text(json.dumps({"comments": comments}, ensure_ascii=False), encoding="utf-8")


def test_chatter_report_counts_and_suspects(tmp_path, monkeypatch, capsys):
    v = tmp_path / "vault"
    monkeypatch.setenv(storage.ENV_VAULT, str(v))
    _post(v, "a1", [{"text": "哈哈哈哈", "sub_comments": [{"text": "同求"}, {"text": "这个锅在哪里买的？链接发一下"}]},
                    {"text": "有吗？"}, {"text": "40"}])
    _post(v, "a2", [])
    r = agentmd.chatter_report(v)
    assert r["total"] == 5 and r["posts"] == 1
    assert r["chatter"] == 4                          # 哈哈哈哈 / 同求 / 有吗？/ 40
    assert r["suspect"] == 2 and {x["text"] for x in r["samples"]} == {"有吗？", "40"}
    assert "判成水话略去 4 条" in r["message"]
    assert json.loads((v / "_archive" / "chatter-report.json").read_text(encoding="utf-8"))["chatter"] == 4
    code = cli.main(["chatter-report", "--json"])
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and j["total"] == 5

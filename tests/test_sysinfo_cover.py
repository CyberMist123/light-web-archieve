"""setup/sysinfo 的补充用例（现有测试没有专门碰它）。

按任务说明：`processes_named` / `_win_proc_info` 不测（真进程查询）；目录联接去重那条
在 Windows 上要开发者模式才能建 symlink，也跳过。端口测试只连 127.0.0.1 自己。
"""

from __future__ import annotations

import socket

from link_brain.setup import sysinfo


def test_dir_bytes_sums_files_and_respects_limit(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 30)
    assert sysinfo.dir_bytes(tmp_path) == 130
    assert sysinfo.dir_bytes(tmp_path, limit_files=1) in (100, 30)   # 数够 1 个文件就返回
    assert sysinfo.dir_bytes(tmp_path / "sub") == 30


def test_dir_bytes_empty_and_missing_dir(tmp_path):
    assert sysinfo.dir_bytes(tmp_path / "空目录") == 0
    assert sysinfo.dir_bytes(tmp_path / "根本没有这个目录") == 0      # scandir 的 OSError 吞掉 = 0


def test_norm_normalizes_separators_and_case():
    assert sysinfo._norm("My_Package.Name") == "my-package-name"
    assert sysinfo._norm("PIL") == "pil"
    assert sysinfo._norm("-_-") == "-"
    assert sysinfo._norm("") == ""


def test_requirement_names_real_package_and_unknown():
    got = sysinfo.requirement_names("httpx")             # httpx 是测试依赖，必装
    assert {"certifi", "httpcore"} <= set(got)
    assert all(";" not in n and "extra" not in n for n in got)   # extra-only 依赖被跳过，名字是裸的
    assert sysinfo.requirement_names("no-such-package-xyz") == []


def test_dist_bytes_known_and_missing():
    total, missing = sysinfo.dist_bytes(["httpx"], transitive=False)
    assert total > 0 and missing == []
    total2, missing2 = sysinfo.dist_bytes(["no-such-package-xyz"])
    assert missing2 == ["no-such-package-xyz"]
    total3, _ = sysinfo.dist_bytes(["httpx"], exclude={"httpx"}, transitive=False)
    assert total3 == 0


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_port_open_false_on_unlistened_port():
    port = _free_port()                                   # 刚关掉的端口 = 确定没人监听
    assert sysinfo.port_open("127.0.0.1", port, timeout=0.3) is False
    assert sysinfo.port_open("127.0.0.1", "不是数字") is False   # int() 抛 ValueError → False


def test_port_open_true_on_own_listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert sysinfo.port_open("127.0.0.1", port, timeout=0.5) is True
    finally:
        s.close()

"""r5 补测：读取组件下载安装（file:// 离线包走全程，不出网、不起进程；home / 组件目录全在 tmp_path）。"""
from __future__ import annotations

import zipfile

from link_brain.sources.xiaohongshu import reader_install as ri


def _env(tmp_path, monkeypatch):
    home = tmp_path / "lbhome"
    home.mkdir()
    monkeypatch.setenv("LINK_BRAIN_HOME", str(home))
    monkeypatch.setenv("LINK_BRAIN_XHS_TOOL_DIR", str(tmp_path / "no-tools"))  # 别看作者本机的 ~/.xiaohongshu-mcp


def _pkg(tmp_path, files: dict[str, bytes]) -> tuple[str, str]:
    """打一个 zip 离线包，返回 (file:// 地址, sha256)。"""
    pkg = tmp_path / "reader-pkg.zip"
    with zipfile.ZipFile(pkg, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return pkg.as_uri(), ri.sha256_of(pkg)


def test_install_zip_flattens_known_and_extra_files(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, sha = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE", "sub/relatedfile.exe": b"REL", "README.txt": b"doc"})
    out = ri.install(url=url, sha256=sha)
    assert out["ok"] is True and out["code"] == ""
    assert out["message"] == "读取组件已装好（3 个文件）"
    bin_dir = tmp_path / "lbhome" / "bin"
    assert sorted(p.name for p in bin_dir.iterdir()) == ["README.txt", "link-brain-reader.exe", "relatedfile.exe"]
    assert sorted(out["installed"]) == sorted(str(bin_dir / n) for n in ("README.txt", "link-brain-reader.exe", "relatedfile.exe"))
    assert out["sha256"] == sha and out["bin_dir"] == str(bin_dir)
    assert list((tmp_path / "lbhome" / "downloads").iterdir()) == []  # 装完删掉下载的包
    assert not [d for d in (tmp_path / "lbhome").iterdir() if d.name.startswith("reader-")]  # 临时解压目录清掉


def test_install_single_exe_not_zip(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    exe = tmp_path / "link-brain-reader"
    exe.write_bytes(b"#!/bin/sh\n")
    out = ri.install(url=exe.as_uri(), sha256=ri.sha256_of(exe))
    assert out["ok"] is True
    assert out["installed"] == [str(tmp_path / "lbhome" / "bin" / "link-brain-reader")]
    assert (tmp_path / "lbhome" / "bin" / "link-brain-reader").read_bytes() == b"#!/bin/sh\n"


def test_checksum_mismatch_deletes_download(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, _ = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE"})
    out = ri.install(url=url, sha256="0" * 64)
    assert out["ok"] is False and out["code"] == "PERMANENT.CHECKSUM_MISMATCH"
    assert "已删掉下载的文件" in out["message"]
    assert list((tmp_path / "lbhome" / "downloads").iterdir()) == []  # 坏包不留
    assert not (tmp_path / "lbhome" / "bin").exists()  # 没建 bin，没装任何东西


def test_missing_url_or_sha_never_pairs_with_builtin(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    out = ri.install(url="", sha256="a" * 64)
    assert out["code"] == "SKIPPED.NOT_CONFIGURED" and "还没有读取组件的发布地址" in out["message"]
    # 只给一半：另一半不拿内置的凑，也不动手下载
    exe = tmp_path / "link-brain-reader"
    exe.write_bytes(b"x")
    out2 = ri.install(url=exe.as_uri(), sha256=None)
    assert out2["code"] == "SKIPPED.NOT_CONFIGURED" and "sha256" in out2["message"]
    assert list((tmp_path / "lbhome").iterdir()) == []  # 连 downloads 都没碰


def test_unsafe_zip_members_rejected(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    for bad in ("../evil.txt", "/abs/evil.txt", "C:/evil.exe"):
        url, sha = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE", bad: b"x"})
        out = ri.install(url=url, sha256=sha)
        assert out["code"] == "PERMANENT.BAD_PACKAGE" and "不安全的路径" in out["message"], bad
        assert not (tmp_path / "lbhome" / "bin" / "link-brain-reader.exe").exists()


def test_zip_without_known_component_rejected(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, sha = _pkg(tmp_path, {"README.txt": b"only docs"})
    out = ri.install(url=url, sha256=sha)
    assert out["code"] == "PERMANENT.BAD_PACKAGE" and "包里没有读取组件" in out["message"]


def test_busy_file_reports_service_busy(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, sha = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE"})
    real_replace = ri.os.replace

    def busy(src, dst, *a, **kw):
        if str(dst).endswith("link-brain-reader.exe"):
            raise PermissionError("file in use")
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(ri.os, "replace", busy)
    out = ri.install(url=url, sha256=sha)
    assert out["code"] == "TRANSIENT.SERVICE_BUSY" and "先在设置里停掉读取服务" in out["message"]


def test_status_before_and_after_install(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    monkeypatch.delenv("LINK_BRAIN_XHS_EXE", raising=False)
    s0 = ri.status()
    assert s0["ok"] is True and s0["reader"] is None and s0["relatedfile"] is None
    assert "还没装读取组件" in s0["message"]
    assert s0["release_configured"] == (bool(ri.RELEASE_URL.strip()) and len(ri.RELEASE_SHA256.strip()) == 64)
    url, sha = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE"})
    assert ri.install(url=url, sha256=sha)["ok"] is True
    s1 = ri.status()
    assert s1["reader"] == str(tmp_path / "lbhome" / "bin" / "link-brain-reader.exe")
    assert "读取组件已就位" in s1["message"]
    assert s1["relatedfile"] is None  # 这个包没带 relatedfile

"""r5 补测：读取组件下载安装（file:// 离线包走全程，不出网、不起进程；home / 组件目录全在 tmp_path）。"""
from __future__ import annotations

import zipfile

import pytest

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


# ---------------------------------------------------------------- 1102：走 setup.fetch（续传 / 进度 / 校验后改名）+ 可覆盖的发布对 + 镜像


def test_install_emits_download_verify_unzip_progress(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, sha = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE" * 1000})
    events = []
    out = ri.install(url=url, sha256=sha, emit=events.append)
    assert out["ok"] is True
    phases = [e["phase"] for e in events if e.get("component") == "reader"]
    assert phases[0] == "下载" and "校验" in phases and "解压" in phases
    dl = [e for e in events if e.get("phase") == "下载"]
    assert dl[-1]["done"] == dl[-1]["total"] and dl[-1]["total"] > 0   # 分块报进度，最后一条是满的


def test_install_resumes_from_part_and_renames_only_after_checksum(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, sha = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE" * 5000})
    whole = (tmp_path / "reader-pkg.zip").read_bytes()
    downloads = tmp_path / "lbhome" / "downloads"
    downloads.mkdir(parents=True)
    (downloads / "reader-pkg.zip.part").write_bytes(whole[:3000])   # 上回下到一半被打断
    copied = []
    from link_brain.setup import fetch
    real = fetch._download_one

    def spy(url_, dest, **kw):
        part = fetch.Path(str(dest) + ".part")
        copied.append(part.stat().st_size if part.exists() else 0)
        return real(url_, dest, **kw)
    monkeypatch.setattr(fetch, "_download_one", spy)
    out = ri.install(url=url, sha256=sha)
    assert out["ok"] is True and copied == [3000], "从 .part 已有的 3000 字节接着下"
    assert not list(downloads.iterdir())   # 校验过、装好、删掉


def test_checksum_mismatch_leaves_no_part_and_no_bin(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, _ = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE"})
    out = ri.install(url=url, sha256="f" * 64)
    assert out["code"] == "PERMANENT.CHECKSUM_MISMATCH" and "再点一次安装会重新下载" in out["message"]
    assert not list((tmp_path / "lbhome" / "downloads").glob("*")) and not (tmp_path / "lbhome" / "bin").exists()


def test_release_pair_override_env_then_config_then_builtin(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    for k in (ri.ENV_URL, ri.ENV_SHA256):
        monkeypatch.delenv(k, raising=False)
    assert ri.release_pair() == (ri.RELEASE_URL, ri.RELEASE_SHA256)
    # config.json 一对
    (tmp_path / "lbhome" / "config.json").write_text(
        '{"reader_release_url": "file:///tmp/x.zip", "reader_release_sha256": "%s"}' % ("b" * 64), "utf-8")
    assert ri.release_pair() == ("file:///tmp/x.zip", "b" * 64)
    # 环境变量压过 config
    monkeypatch.setenv(ri.ENV_URL, "file:///tmp/env.zip")
    monkeypatch.setenv(ri.ENV_SHA256, "C" * 64)
    assert ri.release_pair() == ("file:///tmp/env.zip", "c" * 64)
    # 只给一半：这一层不算，看下一层（不拿内置的凑）
    monkeypatch.delenv(ri.ENV_SHA256)
    assert ri.release_pair() == ("file:///tmp/x.zip", "b" * 64)
    (tmp_path / "lbhome" / "config.json").write_text('{"reader_release_url": "file:///tmp/half.zip"}', "utf-8")
    assert ri.release_pair() == (ri.RELEASE_URL, ri.RELEASE_SHA256)


def test_install_without_args_uses_overridden_pair(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    url, sha = _pkg(tmp_path, {"link-brain-reader.exe": b"EXE"})
    monkeypatch.setenv(ri.ENV_URL, url)
    monkeypatch.setenv(ri.ENV_SHA256, sha)
    assert ri.status()["release_configured"] is True
    out = ri.install()
    assert out["ok"] is True and out["sha256"] == sha
    monkeypatch.setenv(ri.ENV_SHA256, "")
    monkeypatch.setattr(ri, "RELEASE_URL", "")
    monkeypatch.setattr(ri, "RELEASE_SHA256", "")
    assert ri.status()["release_configured"] is False


def test_fetch_candidates_try_mirrors_for_github_release_only(monkeypatch, tmp_path):
    from link_brain.setup import fetch
    _env(tmp_path, monkeypatch)
    gh = "https://github.com/o/r/releases/download/reader-v0.2.0/pkg.zip"
    monkeypatch.delenv(fetch.ENV_MIRRORS, raising=False)
    assert fetch.candidates(gh) == [gh]   # 默认没有镜像
    monkeypatch.setenv(fetch.ENV_MIRRORS, "https://mirror-a.example/, ,https://mirror-b.example")
    assert fetch.candidates(gh) == ["https://mirror-a.example/" + gh, "https://mirror-b.example/" + gh, gh]
    assert fetch.candidates("https://example.com/x.zip") == ["https://example.com/x.zip"]   # 非 GitHub 地址不套镜像
    assert fetch.candidates("file:///tmp/x.zip") == ["file:///tmp/x.zip"]
    monkeypatch.delenv(fetch.ENV_MIRRORS)
    (tmp_path / "lbhome" / "config.json").write_text('{"download_mirrors": ["https://cfg.example"]}', "utf-8")
    assert fetch.mirror_prefixes() == ["https://cfg.example"]


def test_fetch_download_falls_back_to_next_candidate_only_on_network_error(monkeypatch, tmp_path):
    from link_brain.setup import fetch
    _env(tmp_path, monkeypatch)
    monkeypatch.setenv(fetch.ENV_MIRRORS, "https://m1.example,https://m2.example")
    gh = "https://github.com/o/r/releases/download/reader-v0.2.0/pkg.zip"
    tried = []

    def fake(url, dest, **kw):
        tried.append(url)
        if url.startswith("https://m1"):
            raise fetch.SetupError("TRANSIENT.NETWORK", "下载失败：HTTP 502")
        if url.startswith("https://m2"):
            raise fetch.SetupError("TRANSIENT.NETWORK", "下载中断：timeout")
        return dest.with_name(dest.name + ".part")
    monkeypatch.setattr(fetch, "_download_one", fake)
    assert fetch.download(gh, tmp_path / "pkg.zip").name == "pkg.zip.part"
    assert [u.split("/")[2] for u in tried] == ["m1.example", "m2.example", "github.com"]

    tried.clear()

    def full(url, dest, **kw):
        tried.append(url)
        raise fetch.SetupError("PERMANENT.DISK_FULL", "磁盘满了")
    monkeypatch.setattr(fetch, "_download_one", full)
    with pytest.raises(fetch.SetupError) as ei:
        fetch.download(gh, tmp_path / "pkg.zip")
    assert ei.value.code == "PERMANENT.DISK_FULL" and len(tried) == 1, "不是网络问题不换镜像"

    tried.clear()

    def all_down(url, dest, **kw):
        tried.append(url)
        raise fetch.SetupError("TRANSIENT.NETWORK", f"下载失败：{url.split('/')[2]}")
    monkeypatch.setattr(fetch, "_download_one", all_down)
    with pytest.raises(fetch.SetupError) as ei:
        fetch.download(gh, tmp_path / "pkg.zip")
    assert ei.value.code == "TRANSIENT.NETWORK" and "之前试过的镜像也没成" in ei.value.message and len(tried) == 3


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

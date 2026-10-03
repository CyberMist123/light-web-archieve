"""远程阅读看图：read_asset（单张原图 → ImageContent）+ read 的图片清单 / include_images。

GPT 实测：只回文本时「看得到图片路径 ≠ 看得到图片」，OCR 有小错。补法：OCR / 识图文字用来找，命中后原图用来判。
覆盖：对象图片能读（SDK 客户端解析出图片块）、非对象目录 / 非图片扩展 / 越界 / 大小写 / 链接 / 硬链接 / 假图一律拒、
用户开放文件夹里的图默认不开、超大图被等比缩、include_images 数量上限、read 带 images 清单（agent.md / 批注 / 可见笔记）、
每令牌限速计数。合成库（conftest 已把 vault 指到 tmp），不联网。
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from link_brain import storage
from link_brain.remote import server as rserver
from link_brain.remote import tools as rtools
from link_brain.remote.policy import Denied, Policy

from test_remote_mcp import AGENT, NOTE, NOTES, OTHER, make_vault, mcp_post, remote  # noqa: F401  (remote 是 fixture)
import remote_probe  # noqa: E402  (test_remote_mcp 已把 tests/tools 放进 sys.path)

OBJ = "_archive/xiaohongshu/abc12345"
ASSETS = OBJ + "/raw/v0001/assets"
IMG1 = ASSETS + "/image-001.webp"
IMG2 = ASSETS + "/image-002.png"
BIG = ASSETS + "/image-003.webp"
COMMENTS = [f"{ASSETS}/comment-c{i:02d}-001.jpg" for i in range(1, 10)]


def _img(path: Path, size, fmt, mode="RGB", color=(200, 80, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color if mode == "RGB" else color + (128,)).save(path, fmt)


def make_images(vault: Path) -> None:
    make_vault(vault)
    obj = vault / OBJ
    storage.write_json(obj / "meta.json", {"item_id": "xhs-abc12345", "current_version": 1})
    _img(vault / IMG1, (64, 48), "WEBP")
    _img(vault / IMG2, (40, 30), "PNG", mode="RGBA")
    _img(vault / BIG, (3000, 1000), "WEBP")
    for c in COMMENTS:
        _img(vault / c, (20, 20), "JPEG")
    media = [{"role": "note_image", "index": 1, "file": IMG1.removeprefix(OBJ + "/"), "width": 64, "height": 48},
             {"role": "note_image", "index": 2, "file": IMG2.removeprefix(OBJ + "/"), "width": 40, "height": 30},
             {"role": "note_image", "index": 3, "file": BIG.removeprefix(OBJ + "/"), "width": 3000, "height": 1000},
             {"role": "note_image", "index": 4, "file": "raw/v0001/assets/image-004.webp", "width": 9, "height": 9}]  # 没下到
    media += [{"role": "comment_image", "index": 1, "file": c.removeprefix(OBJ + "/"), "width": 20, "height": 20}
              for c in COMMENTS]
    storage.write_json(obj / "raw/v0001/manifest.json", {"media": media})
    # 不该被读到的：非图片、对象里 assets 以外的图、可见笔记目录里的图、内部 / 隐藏目录的图、假图
    (obj / "raw/v0001/assets/readme.txt").write_text("not image", encoding="utf-8")
    _img(obj / "derived/preview.png", (8, 8), "PNG")
    _img(vault / "Web/Xiaohongshu/pic.png", (8, 8), "PNG")
    _img(vault / "其他资料/图.png", (8, 8), "PNG")
    _img(vault / "_trash/x.png", (8, 8), "PNG")
    _img(vault / ".obsidian/x.png", (8, 8), "PNG")
    (vault / ASSETS / "fake.webp").write_bytes(b"this is not an image at all")


@pytest.fixture
def vault():
    v = Path(os.environ["LINK_BRAIN_VAULT"])
    make_images(v)
    return v


def call(r, token, name, args):
    """→ (isError, 文本块 JSON, 图片块列表)。"""
    resp = mcp_post(r, token, "tools/call", {"name": name, "arguments": args})
    assert resp.status_code == 200, resp.text
    res = resp.json()["result"]
    texts = [c for c in res["content"] if c["type"] == "text"]
    images = [c for c in res["content"] if c["type"] == "image"]
    return res.get("isError", False), json.loads(texts[0]["text"]), images


def _decode(block) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(block["data"])))


# ------------------------------------------------------------------ read_asset

def test_read_asset_returns_image_content_via_sdk(remote):
    make_images(remote.vault)
    t = remote.app.store.new_personal("x")["token"]

    async def go():
        async with remote_probe.token_session(remote.base, t) as s:
            res = await s.call_tool("read_asset", {"path": IMG1})
            assert not res.isError
            kinds = [c.type for c in res.content]
            assert kinds == ["text", "image"]
            info = json.loads(res.content[0].text)
            assert (info["path"], info["width"], info["height"], info["mime"], info["resized"]) == (IMG1, 64, 48, "image/webp", False)
            assert info["bytes"] == (remote.vault / IMG1).stat().st_size
            img = res.content[1]
            assert img.mimeType == "image/webp"
            assert base64.b64decode(img.data) == (remote.vault / IMG1).read_bytes()     # 小图原样给
    remote.run(go())
    log = (remote.state / "access.log").read_text("utf-8")
    assert '"tool": "read_asset"' in log and IMG1 in log


def test_read_asset_png_and_big_image_resized(remote):
    make_images(remote.vault)
    t = remote.app.store.new_personal("x")["token"]
    err, info, imgs = call(remote, t, "read_asset", {"path": IMG2})
    assert not err and imgs[0]["mimeType"] == "image/png" and _decode(imgs[0]).size == (40, 30)
    err, info, imgs = call(remote, t, "read_asset", {"path": BIG})
    assert not err and info["resized"] is True and (info["width"], info["height"]) == (3000, 1000)
    assert (info["sent_width"], info["sent_height"]) == (2048, 683) and info["sent_mime"] == "image/jpeg"
    assert len(imgs) == 1 and imgs[0]["mimeType"] == "image/jpeg"
    assert _decode(imgs[0]).size == (2048, 683)


def test_byte_limit_triggers_resize(vault, monkeypatch):
    noisy = vault / ASSETS / "noisy.png"
    Image.frombytes("RGB", (300, 300), os.urandom(300 * 300 * 3)).save(noisy, "PNG")
    pol = Policy.build(vault, ["@xhs"])
    monkeypatch.setattr(rtools, "IMAGE_MAX_BYTES", 120 * 1024)
    assert noisy.stat().st_size > 120 * 1024
    data, mime, info = rtools.load_image(pol, ASSETS + "/noisy.png")
    assert mime == "image/jpeg" and info["resized"] and len(data) <= 120 * 1024
    assert (info["sent_width"], info["sent_height"]) == (300, 300)     # 长边没超，只转码压字节


BAD_ASSETS = [
    (OBJ + "/raw/v0001/source.json", "NOT_IMAGE"),
    (OBJ + "/raw/v0001/assets/readme.txt", "NOT_IMAGE"),
    (AGENT, "NOT_IMAGE"),
    (OBJ + "/derived/preview.png", "FORBIDDEN"),                         # 对象里但不在 raw/vNNNN/assets
    ("Web/Xiaohongshu/pic.png", "NOT_SHARED"),                            # 可见笔记目录里的图不开
    ("其他资料/图.png", "NOT_SHARED"),
    ("_trash/x.png", "FORBIDDEN"),
    (".obsidian/x.png", "FORBIDDEN"),
    ("_archive/x.png", "FORBIDDEN"),
    (ASSETS + "/../assets/image-001.webp", "INVALID_PATH"),
    (ASSETS + "/./image-001.webp", "INVALID_PATH"),
    ("../" + IMG1, "INVALID_PATH"),
    ("/" + IMG1, "INVALID_PATH"),
    ("C:/" + IMG1, "INVALID_PATH"),
    (IMG1.replace("/", "\\"), "INVALID_PATH"),
    (IMG1 + ".", "INVALID_PATH"),
    (IMG1 + "::$DATA", "INVALID_PATH"),
    (ASSETS + "//image-001.webp", "INVALID_PATH"),
    (ASSETS + "/image-001.WEBP", "NOT_IMAGE"),                            # 扩展名大小写变体
    (ASSETS + "/fake.webp", "NOT_IMAGE"),                                 # 扩展名对、内容不是图
    (ASSETS + "/image-004.webp", "NOT_FOUND"),
    ("", "INVALID_PATH"),
]


def test_read_asset_denials(remote):
    make_images(remote.vault)
    t = remote.app.store.new_personal("x")["token"]
    for bad, code in BAD_ASSETS:
        err, data, imgs = call(remote, t, "read_asset", {"path": bad})
        assert err and data["error"] == code and not imgs, (bad, data)
    # 大小写变体：Windows 上真路径对不上 → FORBIDDEN；区分大小写的盘上就是没有
    err, data, _ = call(remote, t, "read_asset", {"path": IMG1.replace("abc12345", "ABC12345")})
    assert err and data["error"] in {"FORBIDDEN", "NOT_FOUND"}
    # read 不读图片
    err, data, imgs = call(remote, t, "read", {"path": IMG1})
    assert err and not imgs
    # 用户开放的文件夹：文本能读，图片默认照样不开
    remote.set_folders(["@xhs", "其他资料"])
    err, data, _ = call(remote, t, "read_asset", {"path": "其他资料/图.png"})
    assert err and data["error"] == "NOT_SHARED"
    # 收藏库没开放：对象图片也读不到
    remote.set_folders(["其他资料"])
    err, data, _ = call(remote, t, "read_asset", {"path": IMG1})
    assert err and data["error"] == "FORBIDDEN"
    log = (remote.state / "access.log").read_text("utf-8")
    assert '"tool": "read_asset"' in log and '"status": "denied"' in log


@pytest.mark.skipif(sys.platform != "win32", reason="联接点是 Windows 的")
def test_read_asset_junction_and_hardlink_denied(remote, tmp_path):
    import _winapi
    make_images(remote.vault)
    outside = tmp_path / "outside"
    _img(outside / "secret.png", (8, 8), "PNG")
    _winapi.CreateJunction(str(outside), str(remote.vault / OBJ / "raw" / "v0002"))
    linked = remote.vault / ASSETS / "hard.webp"
    os.link(remote.vault / IMG1, linked)
    t = remote.app.store.new_personal("x")["token"]
    err, data, _ = call(remote, t, "read_asset", {"path": OBJ + "/raw/v0002/secret.png"})
    assert err and data["error"] == "FORBIDDEN"
    (outside / "assets").mkdir()
    _img(outside / "assets" / "secret.png", (8, 8), "PNG")
    err, data, _ = call(remote, t, "read_asset", {"path": OBJ + "/raw/v0002/assets/secret.png"})
    assert err and data["error"] == "FORBIDDEN", data                    # 父目录是联接点：真路径对不上
    err, data, _ = call(remote, t, "read_asset", {"path": ASSETS + "/hard.webp"})
    assert err and data["error"] == "FORBIDDEN"


# ------------------------------------------------------------------ read 的图片清单 / include_images

def test_read_lists_images_for_object_texts(remote):
    make_images(remote.vault)
    t = remote.app.store.new_personal("x")["token"]
    err, page, imgs = call(remote, t, "read", {"path": AGENT, "max_chars": 100})
    assert not err and not imgs
    paths = [i["path"] for i in page["images"]]
    assert paths == [IMG1, IMG2, BIG] + COMMENTS                          # 没下到的 image-004 不列
    assert [i["n"] for i in page["images"]] == list(range(1, 13))
    assert page["images"][0] == {"n": 1, "path": IMG1, "width": 64, "height": 48, "role": "正文图"}
    assert page["images"][3]["role"] == "评论图"
    for p in paths:                                                       # 清单里的都能 read_asset
        assert remote.app.policy().allowed_asset(p)
    for path in (NOTES, NOTE):                                            # 批注、可见笔记同样带清单
        err, page, _ = call(remote, t, "read", {"path": path})
        assert not err and [i["path"] for i in page["images"]] == paths, path
    remote.set_folders(["@xhs", "其他资料"])
    err, page, _ = call(remote, t, "read", {"path": OTHER})
    assert not err and "images" not in page                               # 不是收藏对象里的文本


def test_read_include_images_default_and_cap(remote):
    make_images(remote.vault)
    t = remote.app.store.new_personal("x")["token"]
    err, page, imgs = call(remote, t, "read", {"path": AGENT, "include_images": True, "max_chars": 10})
    assert not err and len(imgs) == 4 and len(page["attached_images"]) == 4
    assert [a["n"] for a in page["attached_images"]] == [1, 2, 3, 4]
    assert page["attached_images"][2]["resized"] is True and _decode(imgs[2]).size == (2048, 683)
    assert "_images" not in page
    err, page, imgs = call(remote, t, "read", {"path": AGENT, "include_images": True, "max_images": 99})
    assert not err and len(imgs) == 8                                      # 上限 8
    err, page, imgs = call(remote, t, "read", {"path": AGENT, "include_images": True, "max_images": 2})
    assert not err and len(imgs) == 2
    err, page, imgs = call(remote, t, "read", {"path": AGENT, "include_images": "yes"})
    assert not err and not imgs and "attached_images" not in page        # 只认 true


def test_include_images_total_budget(vault, monkeypatch):
    pol = Policy.build(vault, ["@xhs"])
    one = (vault / IMG1).stat().st_size
    monkeypatch.setattr(rtools, "INCLUDE_TOTAL_BYTES", one + 10)
    out = rtools.read(pol, {"path": AGENT, "include_images": True, "max_images": 3})
    assert len(out["_images"]) == 1 and [s["error"] for s in out["skipped_images"]] == ["BUDGET", "BUDGET"]


def test_image_list_falls_back_to_vision_json(vault):
    obj = vault / OBJ
    (obj / "raw/v0001/manifest.json").unlink()
    storage.write_json(obj / "derived/vision.json", {"images": [
        {"asset": IMG1.removeprefix(OBJ + "/")}, {"asset": "raw/v0001/assets/../../meta.json"}, {"asset": "derived/preview.png"}]})
    pol = Policy.build(vault, ["@xhs"])
    assert rtools.image_list(pol, AGENT) == [{"n": 1, "path": IMG1, "width": None, "height": None}]
    assert rtools.image_list(Policy.build(vault, ["其他资料"]), AGENT) is None


# ------------------------------------------------------------------ 限速

def test_read_asset_counts_toward_rate_limit(remote):
    make_images(remote.vault)
    remote.app.rate = rserver.Window(2, 60)
    t = remote.app.store.new_personal("a")["token"]
    assert not call(remote, t, "read_asset", {"path": IMG1})[0]
    assert not call(remote, t, "read_asset", {"path": IMG2})[0]
    r = mcp_post(remote, t, "tools/call", {"name": "read_asset", "arguments": {"path": IMG1}})
    assert r.status_code == 429


def test_include_images_each_extra_image_counts(remote):
    make_images(remote.vault)
    remote.app.rate = rserver.Window(3, 60)
    t = remote.app.store.new_personal("a")["token"]
    # 这次请求占 1，附图第 2、3 张各占 1，第 4 张超了不附
    err, page, imgs = call(remote, t, "read", {"path": AGENT, "include_images": True, "max_images": 4})
    assert not err and len(imgs) == 3 and len(page["attached_images"]) == 3
    assert page["skipped_images"] == [{"n": 4, "path": COMMENTS[0], "error": "RATE_LIMITED"}]
    assert mcp_post(remote, t).status_code == 429


def test_policy_asset_rule_is_separate_from_text_rule(vault):
    pol = Policy.build(vault, ["@xhs", "其他资料"])
    assert pol.allowed_asset(IMG1) and not pol.allowed_file(IMG1)
    assert pol.allowed_file(AGENT) and not pol.allowed_asset(AGENT)
    assert not pol.allowed_asset("其他资料/图.png")
    with pytest.raises(Denied):
        pol.resolve_asset(OBJ + "/raw/v1/assets/image-001.webp")          # 版本目录必须 vNNNN

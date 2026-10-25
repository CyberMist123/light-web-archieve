"""1024 第一波合并收尾：render_item 默认不识图，要识图的调用方显式传 vision=True。

夜跑补识图（enrich._child）和主动保存（catch._ensure_rendered）原来靠默认值 True 识图；
默认改成 False 后它们必须显式传，否则夜跑会悄悄不识图。
"""
import argparse
import inspect

from link_brain import catch, cli, enrich, render


def _spy(monkeypatch):
    calls = []

    def fake_render_item(source_key, source_id, **kw):
        calls.append(kw)
        return {}

    monkeypatch.setattr(render, "render_item", fake_render_item)
    return calls


def test_render_item_defaults_to_no_vision():
    assert inspect.signature(render.render_item).parameters["vision"].default is False


def test_enrich_child_asks_for_vision(monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(enrich, "_child", enrich._child)  # 不替换，只确认走真函数
    try:
        enrich._child("xiaohongshu", "abc", False)
    except Exception:  # noqa: BLE001 - 后续步骤在隔离 vault 里找不到对象无所谓，只看 render 调用
        pass
    assert calls and calls[0].get("vision") is True


def test_catch_ensure_rendered_asks_for_vision(monkeypatch):
    calls = _spy(monkeypatch)
    catch._ensure_rendered("xiaohongshu", "abc", force=True, extract=False)
    assert calls and calls[0].get("vision") is True


def test_cli_render_vision_flag():
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:
        src = inspect.getsource(cli)
        assert '"--vision"' in src and '"--no-vision"' in src
        return
    args = parser.parse_args(["render", "x", "--vision"])
    assert args.vision is True
    args = parser.parse_args(["render", "x", "--no-vision"])
    assert getattr(args, "vision", False) is False

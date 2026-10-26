"""setup/common 的补充用例（test_setup.py 只经 install 间接碰到 progress / SetupError；
apply_settings_patch、_deep_merge、mb、stdout_emit 没有直接测试）。

全部不出网、不起进程：apply_settings_patch 用 LINK_BRAIN_HOME / LINK_BRAIN_VAULT 指到 tmp_path；
写失败分支 monkeypatch 掉 storage.write_json（common 里是函数内 import，patch 模块属性即生效）。
"""

from __future__ import annotations

import json
import sys

from link_brain import storage
from link_brain.setup import common


def _pin_home(monkeypatch, tmp_path):
    monkeypatch.setenv("LINK_BRAIN_HOME", str(tmp_path))
    monkeypatch.setenv("LINK_BRAIN_VAULT", str(tmp_path))


def test_mb_rounds_and_passes_none():
    assert common.mb(None) is None
    assert common.mb(0) == 0 and common.mb(1 << 20) == 1
    assert common.mb(1.6 * (1 << 20)) == 2
    assert common.mb(2.5 * (1 << 20)) == 2          # round 的银行家舍入：2.5 → 2


def test_progress_event_shape_and_none_emit_is_noop():
    events = []
    common.progress(None, "asr", "安装")            # emit=None 完全静默
    assert events == []
    common.progress(events.append, "asr", "验证", 2.9, "5", "文本")
    assert events == [{"type": "progress", "component": "asr", "phase": "验证",
                       "done": 2, "total": 5, "text": "文本"}]   # 数字都 int() 收敛
    common.progress(events.append, "x", "y")
    assert events[-1]["done"] is None and events[-1]["total"] is None and events[-1]["text"] == ""


def test_stdout_emit_json_line_and_text_fallback(capsys, monkeypatch):
    common.stdout_emit({"type": "progress", "text": "中文✓"})   # 一行一个 JSON，非 ASCII 不转义
    assert json.loads(capsys.readouterr().out.strip()) == {"type": "progress", "text": "中文✓"}

    class _NoBuffer:                                 # stdout 没有 .buffer（纯文本流）→ 走 write+flush 回退
        def write(self, s):
            captured.append(s)
            return len(s)
        def flush(self):
            pass
    captured = []
    monkeypatch.setattr(sys, "stdout", _NoBuffer())
    common.stdout_emit({"a": 1})
    assert json.loads("".join(captured)) == {"a": 1}


def test_setuperror_carries_code_and_message():
    e = common.SetupError("NEEDS_HUMAN.AUTH_FAILED", "key 不对")
    assert e.code == "NEEDS_HUMAN.AUTH_FAILED" and e.message == "key 不对"
    assert str(e) == "key 不对"
    assert isinstance(e, Exception)


def test_deep_merge_nested_and_no_mutation():
    base = {"a": {"b": 1, "c": {"d": 2}}, "keep": [1]}
    over = {"a": {"b": 9, "c": {"e": 3}}, "new": "x"}
    merged = common._deep_merge(base, over)
    assert merged == {"a": {"b": 9, "c": {"d": 2, "e": 3}}, "keep": [1], "new": "x"}
    assert base == {"a": {"b": 1, "c": {"d": 2}}, "keep": [1]}   # 深拷贝，入参不动
    assert common._deep_merge({}, {"x": {"y": 1}}) == {"x": {"y": 1}}
    assert common._deep_merge({"x": {"y": 1}}, {}) == {"x": {"y": 1}}


def test_apply_settings_patch_empty_and_missing_plugin_dir(monkeypatch, tmp_path):
    _pin_home(monkeypatch, tmp_path)
    out = common.apply_settings_patch({})
    assert out["written"] is False and "没有要改" in out["reason"]          # 空 patch 不动文件
    out2 = common.apply_settings_patch({"a": 1})
    assert out2["written"] is False and "插件目录不在" in out2["reason"]     # 没装插件只带补丁
    assert not (tmp_path / ".obsidian").exists()                          # 也不顺手建目录


def test_apply_settings_patch_write_merge_and_failures(monkeypatch, tmp_path):
    _pin_home(monkeypatch, tmp_path)
    path = storage.vault_root() / ".obsidian" / "plugins" / "link-brain-actions" / "data.json"
    path.parent.mkdir(parents=True)

    fresh = common.apply_settings_patch({"asrAI": {"port": "6123"}})        # 没有旧文件 → 写 patch 本身
    assert fresh["written"] is True and json.loads(path.read_text(encoding="utf-8")) == {"asrAI": {"port": "6123"}}

    path.write_text(json.dumps({"asrAI": {"port": "1", "other": True}, "top": 5}), encoding="utf-8")
    merged = common.apply_settings_patch({"asrAI": {"port": "6123"}})       # 合并：只改给出的键
    assert merged["written"] is True
    assert json.loads(path.read_text(encoding="utf-8")) == {"asrAI": {"port": "6123", "other": True}, "top": 5}

    path.write_text("{oops", encoding="utf-8")
    bad = common.apply_settings_patch({"a": 1})
    assert bad["written"] is False and "读不了" in bad["reason"] and "JSONDecodeError" in bad["reason"]

    path.write_text("[1, 2]", encoding="utf-8")
    notobj = common.apply_settings_patch({"a": 1})
    assert notobj["written"] is False and "不是对象" in notobj["reason"]

    path.write_text("{}", encoding="utf-8")

    def boom(_path, _data):
        raise OSError(13, "拒绝访问")
    monkeypatch.setattr(storage, "write_json", boom)                        # 函数内 import → patch 模块属性生效
    denied = common.apply_settings_patch({"a": 1})
    assert denied["written"] is False and "写不进去" in denied["reason"] and "PermissionError" in denied["reason"]

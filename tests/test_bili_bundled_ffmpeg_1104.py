"""1104：B 站功能包随带 ffmpeg（imageio-ffmpeg），PATH 上没有也能合并 / 校验。全部离线。"""
from __future__ import annotations

def test_bili_uses_bundled_ffmpeg_when_path_has_none(tmp_path, monkeypatch):
    """1104 作者：虚拟机上懒人安装完 B 站一条都下不了（没装 ffmpeg）。bilibili 功能包随带 imageio-ffmpeg：PATH 上没有就用它，
    合并（--ffmpeg-location）和校验（没有 ffprobe 时读 ffmpeg -i 的文件头）都走它。"""
    import subprocess
    import sys
    import types
    from link_brain.sources.bilibili import ytdlp
    exe = tmp_path / "ffmpeg-bundled.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", types.SimpleNamespace(get_ffmpeg_exe=lambda: str(exe)))
    assert ytdlp.ffmpeg_exe() == str(exe) and ytdlp.ffmpeg_ok() and "ffmpeg" not in ytdlp.missing_tools()
    argv = ytdlp.build_argv("https://www.bilibili.com/video/BV1xx411c7mD", tmp_path, cookies=None)
    assert argv[argv.index("--ffmpeg-location") + 1] == str(exe)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 2048)
    head = ("Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'v.mp4':\n  Duration: 00:02:53.12, start: 0.000000, bitrate: 1445 kb/s\n"
            "  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 1300 kb/s, 30 fps\n"
            "  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s\n"
            "At least one output file must be specified\n")
    seen = []
    monkeypatch.setattr(ytdlp.subprocess, "run", lambda argv, **k: seen.append(argv) or subprocess.CompletedProcess(argv, 1, "", head))
    out = ytdlp.probe_video(video)
    assert seen[0][0] == str(exe) and "-i" in seen[0]
    assert out == {"ok": True, "duration_sec": 173.12, "width": 1920, "height": 1080, "vcodec": "h264", "acodec": "aac",
                   "has_audio": True, "error": None}
    # 认不出的文件：说清楚，不当成功
    monkeypatch.setattr(ytdlp.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "v.mp4: Invalid data found"))
    bad = ytdlp.probe_video(video)
    assert bad["ok"] is False and "认不出" in bad["error"]
    # 两样都没有：缺 ffmpeg
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)
    assert ytdlp.ffmpeg_exe() is None and "ffmpeg" in ytdlp.missing_tools()

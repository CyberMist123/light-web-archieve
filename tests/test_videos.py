from link_brain.adapters.xiaohongshu import _video
from link_brain import videos, render
import httpx


def test_ef_stream_and_codec_preference():
    streams={'EF4':[{'masterUrl':'https://x/unknown','backupUrls':['https://x/backup'],'videoCodec':'EF4'}], 'odd':[{'masterUrl':'https://x/av1','codec':'av1'},{'masterUrl':'https://x/h264','codec':'h264'}]}
    note={'video':{'media':{'stream':streams}}}
    assert _video(note)['video_url']=='https://x/h264'
    del streams['odd']
    assert _video(note)['backup_urls']==['https://x/backup']


def test_video_backup_download(tmp_path):
    def handler(req):
        return httpx.Response(403) if req.url.path=='/bad' else httpx.Response(200,content=b'\x00\x00\x00\x20ftyp'+b'0'*50)
    client=httpx.Client(transport=httpx.MockTransport(handler))
    result=videos.download({'video_url':'https://x/bad','backup_urls':['https://x/good']},tmp_path,'raw/v0002',client)
    assert result['download_status']=='ok'
    assert result['file']=='raw/v0002/assets/video.mp4'
    assert (tmp_path/'assets/video.mp4').stat().st_size==58


def test_local_video_is_first_slide():
    html, media=render._media_html({'kind':'video'}, {'media':[{'role':'video','file':'raw/v0002/assets/video.mp4','download_status':'ok'},{'role':'video_cover','file':'raw/v0001/assets/cover.webp','download_status':'ok'}]},'_archive/xiaohongshu/test')
    assert media and html.index('<video')<html.index('<img')
    assert 'controls preload="metadata"' in html
    assert '../../_archive/xiaohongshu/test/raw/v0002/assets/video.mp4' in html
    assert '未下载' not in html

"""下载视频、为旧 RAW 新建版本；转写作为独立命令，不阻塞导入。"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import httpx
from . import storage, index, render
from .adapters import xiaohongshu as xhs
from .read import dump_json


def download(video, raw, prefix, client=None):
    entry = {'role': 'video', 'index': 1, 'file': None, 'original_url': video.get('video_url'),
             'mime': 'video/mp4', 'bytes': None, 'width': video.get('width'), 'height': video.get('height'),
             'download_status': 'failed', 'error': '没有可用视频地址'}
    urls = list(dict.fromkeys([video.get('video_url'), *(video.get('backup_urls') or [])]))
    assets = raw / 'assets'; assets.mkdir(parents=True, exist_ok=True)
    target = assets / 'video.mp4'
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=90)
    try:
        for url in filter(None, urls):
            try:
                with client.stream('GET', url, follow_redirects=True, timeout=90) as response:
                    response.raise_for_status()
                    with target.open('wb') as out:
                        for chunk in response.iter_bytes():
                            out.write(chunk)
                if target.stat().st_size < 32 or b'ftyp' not in target.open('rb').read(32):
                    raise ValueError('响应不是 MP4')
                entry.update(file=prefix+'/assets/video.mp4', bytes=target.stat().st_size,
                             download_status='ok', error=None)
                break
            except (httpx.HTTPError, OSError, ValueError) as exc:
                target.unlink(missing_ok=True)
                entry['error'] = f'视频下载失败：{type(exc).__name__}'
    finally:
        if own: client.close()
    return entry


def backfill(row):
    obj = storage.object_dir(row['source'], row['source_id'])
    meta = storage.read_json(obj/'meta.json')
    old = storage.raw_dir(row['source'], row['source_id'], meta['current_version'])
    source = storage.read_json(old/'source.json')
    manifest = storage.read_json(old/'manifest.json')
    existing = next((m for m in manifest['media'] if m['role']=='video' and m.get('file') and (obj/m['file']).exists()), None)
    if existing:
        return {'item_id': row['item_id'], 'status':'hit', 'bytes':existing['bytes']}
    raw = storage.read_json(old/'mcp_raw.json')
    note = (raw.get('data') or {}).get('note') or {}
    video = xhs._video(note) or source['note'].get('video') or {}
    if not video.get('video_url'):
        return {'item_id':row['item_id'], 'status':'missing_url', 'bytes':0}
    version = max(storage.existing_versions(row['source'],row['source_id']))+1
    dest = storage.raw_dir(row['source'],row['source_id'],version)
    dest.mkdir(parents=True)
    prefix = f'raw/v{version:04d}'
    # 旧资产继续指向原版本；新版本只新增视频，旧 RAW 字节不动。
    entry = download(video, dest, prefix)
    source['note']['video'] = {**video,'downloaded':entry['download_status']=='ok'}
    manifest['media'] = [m for m in manifest['media'] if m['role']!='video'] + [entry]
    manifest['version'] = version
    storage.write_json(dest/'source.json',source)
    storage.write_json(dest/'manifest.json',manifest)
    shutil.copyfile(old/'mcp_raw.json',dest/'mcp_raw.json')
    meta['current_version'] = version
    storage.write_json(obj/'meta.json',meta)
    conn=index.connect()
    try:
        index.upsert_object(conn,meta,source)
        # source_sha256 是旧 schema 的必填列；本轮不生成或匹配 SHA。
        index.add_source_version(conn,item_id=row['item_id'],version=version,raw_dir=dest,
            captured_at=source['capture']['captured_at'],adapter=source['capture']['adapter'],
            input_url=source['capture'].get('input_url'),input_kind=source['capture'].get('input_kind'),source_sha256='')
    finally: conn.close()
    render.render_object(row['source'],row['source_id'])
    return {'item_id':row['item_id'],'status':entry['download_status'],'bytes':entry['bytes'] or 0,'error':entry['error']}


def screen_text_enabled():
    """设置「识图接口 → 视频画面文字」；关了就只做语音转写。"""
    from . import ai_config
    return (ai_config.load().get('visionAI') or {}).get('videoScreenText', True) is not False


# 1001 审计 A-6 / xc-5：转写失败要留下原因；「没人声 / 没音轨」是结论不是失败；
# 同一原因连续失败 GIVE_UP_AFTER 次就退避 BACKOFF_DAYS 天，退避中不重试、不算失败（这步不再天天 exit=2）。
DONE_STATUSES = ('ok', 'no_speech', 'no_audio')
QUIET_STATUSES = ('ok', 'hit', 'no_speech', 'no_audio', 'backoff')
GIVE_UP_AFTER = 3
BACKOFF_DAYS = 7
_NO_AUDIO = ('does not contain any stream', 'matches no streams', 'Output file is empty')


def _last_line(text, limit=300):
    lines = [x.strip() for x in str(text or '').splitlines() if x.strip()]
    line = lines[-1] if lines else ''
    return re.sub(r'\s*（可加 --via .*$', '', line)[:limit]  # media.py 的换引擎提示不算原因


def _now():
    return datetime.now().astimezone()


def _failed(prev, reason, now):
    """同一原因连着失败就累计；够次数写 retry_after。"""
    same = prev.get('status') == 'failed' and prev.get('error') == reason
    count = int(prev.get('fail_count') or 1) + 1 if same else 1
    doc = {'status': 'failed', 'text': '', 'engine': 'media.py audio / CMX', 'error': reason,
           'fail_count': count, 'last_tried': now.isoformat(timespec='seconds')}
    if count >= GIVE_UP_AFTER:
        doc['retry_after'] = (now + timedelta(days=BACKOFF_DAYS)).isoformat(timespec='seconds')
    return doc


def _backing_off(prev, now):
    try:
        return prev.get('status') == 'failed' and bool(prev.get('retry_after')) \
            and datetime.fromisoformat(prev['retry_after']) > now
    except (TypeError, ValueError):
        return False


def _speech(audio, prev, now):
    """跑 media.py audio（CMX 本机 ASR），返回要写进 transcript.json 的结论（不含 screen）。"""
    from .vision import MEDIA_PY
    proc = subprocess.run(['python', MEDIA_PY, 'audio', str(audio)], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=900)
    lines = (proc.stdout or '').strip().splitlines()
    text = '\n'.join(lines[:-1] if lines and lines[-1].startswith('(引擎 ') else lines).strip()
    if proc.returncode == 0 and text:
        return {'status': 'ok', 'text': text, 'engine': 'media.py audio / CMX', 'error': None}
    if re.search(r'\bno_speech\b', proc.stdout or '') or proc.returncode == 0:
        # 纯音乐 / 没人声：CMX 回 no_speech（media.py 退出码 1）或空文本——这是结论，画面文字照抽
        return {'status': 'no_speech', 'text': '', 'engine': 'media.py audio / CMX', 'error': None,
                'last_tried': now.isoformat(timespec='seconds')}
    reason = _last_line(proc.stdout) or _last_line(proc.stderr) or f'media.py audio 退出码 {proc.returncode}'
    return _failed(prev, reason, now)


def transcribe(row):
    obj=storage.object_dir(row['source'],row['source_id'])
    output=obj/'derived/transcript.json'
    meta=storage.read_json(obj/'meta.json')
    manifest=storage.read_json(storage.raw_dir(row['source'],row['source_id'],meta['current_version'])/'manifest.json')
    entry=next((m for m in manifest['media'] if m['role']=='video' and m.get('file')),None)
    prev=storage.read_json(output) if output.exists() else {}
    if prev.get('status') in DONE_STATUSES:
        # 0926：语音转写过的视频补「画面文字」（烧录字幕 / 文字卡），不重转语音
        done=prev
        if entry and 'screen' not in done and screen_text_enabled():
            from .screentext import extract
            done['screen']=extract(obj/entry['file'])
            storage.write_json(output,done)
            render.render_object(row['source'],row['source_id'])
            return {'item_id':row['item_id'],'status':'ok','screen_chars':len(done['screen'].get('text',''))}
        return {'item_id':row['item_id'],'status':'hit'}
    if not entry:return {'item_id':row['item_id'],'status':'no_video'}
    now=_now()
    if _backing_off(prev, now):
        return {'item_id':row['item_id'],'status':'backoff','error':prev.get('error'),'retry_after':prev['retry_after']}
    audio=obj/'derived/transcript-audio.wav';audio.parent.mkdir(exist_ok=True)
    try:
        try:
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(obj/entry['file']),'-vn','-ac','1','-ar','16000',str(audio)],check=True,capture_output=True,timeout=180)
        except subprocess.CalledProcessError as exc:
            err=(exc.stderr or b'').decode('utf-8','replace') if isinstance(exc.stderr,bytes) else str(exc.stderr or '')
            if any(x in err for x in _NO_AUDIO):
                result={'status':'no_audio','text':'','error':None,'last_tried':now.isoformat(timespec='seconds')}
            else:
                result=_failed(prev,'抽音轨失败：'+(_last_line(err) or f'ffmpeg 退出码 {exc.returncode}'),now)
        else:
            result=_speech(audio,prev,now)
    except subprocess.TimeoutExpired as exc:
        result=_failed(prev,f'超时（{int(exc.timeout or 0)} 秒）：{Path(str(exc.cmd[0] if exc.cmd else "")).name}',now)
    except (subprocess.SubprocessError,OSError) as exc:
        result=_failed(prev,f'{type(exc).__name__}: {exc}'[:300],now)
    finally:audio.unlink(missing_ok=True)
    if screen_text_enabled():
        from .screentext import extract
        old_screen=prev.get('screen') or {}
        # 画面文字与语音并存：背景乐转写成歌词时以它为准；重试转写时上次抽好的画面文字直接沿用
        result['screen']=old_screen if old_screen.get('status')=='ok' else extract(obj/entry['file'])
    storage.write_json(output,result)
    render.render_object(row['source'],row['source_id'])
    out={'item_id':row['item_id'],'status':result['status'],'chars':len(result['text'])}
    if result.get('error'):out['error']=result['error']
    if result.get('retry_after'):out['retry_after']=result['retry_after']
    return out


def run(args):
    conn=index.connect()
    rows=conn.execute("SELECT * FROM objects WHERE kind='video'").fetchall();conn.close()
    if args.target:rows=[r for r in rows if r['item_id']==args.target]
    results=[]
    for row in rows:
        result=transcribe(row) if args.transcribe else backfill(row)
        results.append(result)
        why=f" {result['error']}" if result.get('error') else ''
        print(row['item_id']+' '+result['status']+why,file=__import__('sys').stderr,flush=True)
    from .catalog import build
    build()
    dump_json({'results':results,'bytes':sum(r.get('bytes',0) for r in results)})
    return 0 if all(r['status'] in QUIET_STATUSES for r in results) else 2

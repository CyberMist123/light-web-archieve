"""下载视频、为旧 RAW 新建版本；转写作为独立命令，不阻塞导入。"""
from __future__ import annotations
import os
import shutil
import subprocess
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


def transcribe(row):
    from .vision import MEDIA_PY
    obj=storage.object_dir(row['source'],row['source_id'])
    output=obj/'derived/transcript.json'
    meta=storage.read_json(obj/'meta.json')
    manifest=storage.read_json(storage.raw_dir(row['source'],row['source_id'],meta['current_version'])/'manifest.json')
    entry=next((m for m in manifest['media'] if m['role']=='video' and m.get('file')),None)
    if output.exists() and storage.read_json(output).get('status')=='ok':
        # 0926：语音转写过的视频补「画面文字」（烧录字幕 / 文字卡），不重转语音
        done=storage.read_json(output)
        if entry and 'screen' not in done:
            from .screentext import extract
            done['screen']=extract(obj/entry['file'])
            storage.write_json(output,done)
            render.render_object(row['source'],row['source_id'])
            return {'item_id':row['item_id'],'status':'ok','screen_chars':len(done['screen'].get('text',''))}
        return {'item_id':row['item_id'],'status':'hit'}
    if not entry:return {'item_id':row['item_id'],'status':'no_video'}
    audio=obj/'derived/transcript-audio.wav';audio.parent.mkdir(exist_ok=True)
    try:
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(obj/entry['file']),'-vn','-ac','1','-ar','16000',str(audio)],check=True,capture_output=True,timeout=180)
        proc=subprocess.run(['python',MEDIA_PY,'audio',str(audio)],capture_output=True,text=True,encoding='utf-8',timeout=900)
        lines=proc.stdout.strip().splitlines()
        text='\n'.join(lines[:-1] if lines and lines[-1].startswith('(引擎 ') else lines).strip()
        result={'status':'ok' if proc.returncode==0 and text else 'failed','text':text if proc.returncode==0 else '',
                'engine':'media.py audio / CMX','error':None if proc.returncode==0 else '本机转写失败'}
    except (subprocess.SubprocessError,OSError) as exc:
        result={'status':'failed','text':'','error':type(exc).__name__}
    finally:audio.unlink(missing_ok=True)
    from .screentext import extract
    result['screen']=extract(obj/entry['file'])  # 画面文字与语音并存：背景乐转写成歌词时以它为准
    storage.write_json(output,result)
    render.render_object(row['source'],row['source_id'])
    return {'item_id':row['item_id'],'status':result['status'],'chars':len(result['text'])}


def run(args):
    conn=index.connect()
    rows=conn.execute("SELECT * FROM objects WHERE kind='video'").fetchall();conn.close()
    if args.target:rows=[r for r in rows if r['item_id']==args.target]
    results=[]
    for row in rows:
        result=transcribe(row) if args.transcribe else backfill(row)
        results.append(result)
        print(row['item_id']+' '+result['status'],file=__import__('sys').stderr,flush=True)
    from .catalog import build
    build()
    dump_json({'results':results,'bytes':sum(r.get('bytes',0) for r in results)})
    return 0 if all(r['status'] in ('ok','hit') for r in results) else 2

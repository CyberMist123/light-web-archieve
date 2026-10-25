"""下载视频、为旧 RAW 新建版本；转写作为独立命令，不阻塞导入。"""
from __future__ import annotations
import os
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
    """给旧 RAW 补视频。整段在这篇的单篇锁里（1025 第二波 PR④）：读 meta → 下载 → 发布 → 改 meta 之间别的入口
    （删除、续读）进不来，删除也就不会在下载中途把对象目录挪走再被这里建回来。拿不到锁 = 别人正写这篇，这次跳过如实报。"""
    try:
        with storage.file_lock(storage.obj_lock_name(row['item_id']), wait_s=30, owner='videos backfill'):
            return _backfill(row)
    except storage.LockBusy:
        return {'item_id': row['item_id'], 'status': 'busy', 'bytes': 0, 'error': '这篇正被别的任务写入，下次再补'}


def _backfill(row):
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
    # 1025 第二波 PR④：下载写进暂存目录，manifest 写好再一次改名成 vNNNN——下载中崩了磁盘上不留半截版本。
    # 旧资产继续指向原版本；新版本只新增视频，旧 RAW 字节不动。
    with storage.stage_version(row['source'], row['source_id']) as stg:
        entry = download(video, stg.path, 'raw/' + stg.path.name)
        source['note']['video'] = {**video,'downloaded':entry['download_status']=='ok'}
        shutil.copyfile(old/'mcp_raw.json',stg.path/'mcp_raw.json')

        def finalize(v):
            if entry.get('file'):
                entry['file'] = f'raw/{storage.version_name(v)}/assets/video.mp4'
            manifest['media'] = [m for m in manifest['media'] if m['role']!='video'] + [entry]
            manifest['version'] = v
            storage.write_json(stg.path/'source.json',source)
            return manifest
        version = stg.publish(finalize)
    dest = storage.raw_dir(row['source'],row['source_id'],version)
    # 1024：只改版本这两个键，单篇锁里重读再写（下载期间别的入口写进 meta 的键不被旧副本盖掉）
    meta = storage.update_json(obj/'meta.json', lambda m: m.update(current_version=version,
        versions=storage.existing_versions(row['source'],row['source_id'])), lock_name=storage.obj_lock_name(row['item_id']))
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
# skipped = 语音识别没开 / 没配（CONVENTIONS §4.4）：不算失败，不计次数；开了以后下次自然补上
QUIET_STATUSES = ('ok', 'hit', 'no_speech', 'no_audio', 'backoff', 'skipped')
GIVE_UP_AFTER = 3
BACKOFF_DAYS = 7
_NO_AUDIO = ('does not contain any stream', 'matches no streams', 'Output file is empty')


def _last_line(text, limit=300):
    lines = [x.strip() for x in str(text or '').splitlines() if x.strip()]
    line = lines[-1] if lines else ''
    return line[:limit]


def _now():
    return datetime.now().astimezone()


def _failed(prev, reason, now, code='TRANSIENT.SERVICE_BUSY', engine=''):
    """同一原因连着失败就累计；够次数写 retry_after。"""
    same = prev.get('status') == 'failed' and prev.get('error') == reason
    count = int(prev.get('fail_count') or 1) + 1 if same else 1
    doc = {'status': 'failed', 'text': '', 'engine': engine, 'error': reason, 'code': code,
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


def _speech(audio, prev, now, cfg):
    """语音识别执行器（asr.transcribe，设置里的「语音识别」），返回要写进 transcript.json 的结论（不含 screen）。"""
    from . import asr
    got = asr.transcribe(audio, cfg)
    engine = got.get('engine') or cfg.get('mode') or ''
    if got.get('status') == 'ok' and (got.get('text') or '').strip():
        return {'status': 'ok', 'text': got['text'].strip(), 'engine': engine, 'error': None}
    if got.get('status') == 'ok':
        # 纯音乐 / 没人声：识别出空文本——这是结论，画面文字照抽
        return {'status': 'no_speech', 'text': '', 'engine': engine, 'error': None,
                'last_tried': now.isoformat(timespec='seconds')}
    if got.get('status') == 'skipped':
        return {'status': 'skipped', 'text': '', 'engine': engine, 'code': got.get('code'), 'error': got.get('error'),
                'last_tried': now.isoformat(timespec='seconds')}
    return _failed(prev, got.get('error') or '语音识别失败', now, got.get('code') or 'TRANSIENT.SERVICE_BUSY', engine)


def _has_screen_text(result):
    screen = result.get('screen') or {}
    return screen.get('status') == 'ok' and bool((screen.get('text') or '').strip())


def _wants_screen(result):
    """画面文字：设置开着就抽；关着时，没人声 / 没音轨的视频也抽（否则这条视频一个字都没有）。本地 OCR，不花钱。"""
    return screen_text_enabled() or result.get('status') in ('no_speech', 'no_audio')


def _report(row, result):
    """转写结论进问题记录：失败 / 没音轨 / 没人声按码登记，没开记一条步骤级 SKIPPED，转出来了就清掉这篇的记录。"""
    from . import problems
    item_id, title = row['item_id'], (row['title'] if 'title' in row.keys() else None)
    status = result.get('status')
    try:  # 10-03 同步记录：转写这次的结果（没人声 / 没音轨也算处理完了）；没开的不记
        from . import synclog
        if status in ('ok', 'no_speech', 'no_audio'):
            synclog.note('video', item_id, True, title=title)
        elif status == 'failed':
            synclog.note('video', item_id, False, title=title, reason=result.get('error') or '语音识别失败',
                         code=result.get('code') or '')
    except Exception as exc:  # noqa: BLE001
        print(f'[synclog] {type(exc).__name__}: {exc}', file=__import__('sys').stderr)
    if status == 'ok':
        problems.resolve('videos.transcribe', item_id)
        problems.resolve('videos.transcribe', None, 'SKIPPED.NOT_CONFIGURED')
    elif status == 'skipped':
        problems.report('videos.transcribe', result.get('code') or 'SKIPPED.NOT_CONFIGURED',
                        result.get('error') or '语音识别没开', action='skipped')
    elif status in ('no_speech', 'no_audio') and _has_screen_text(result):
        # 1004：没人声但画面字幕读出来了 = 这条视频有文字可用，不算问题（她：有字幕还报错让人困扰）
        problems.resolve('videos.transcribe', item_id)
    elif status == 'no_speech':
        problems.report('videos.transcribe', 'PERMANENT.NO_SPEECH', '视频里没听出人声，画面上也没认出字幕',
                        item_id=item_id, title=title)
    elif status == 'no_audio':
        problems.report('videos.transcribe', 'PERMANENT.NO_AUDIO', '视频没有音轨，画面上也没认出字幕',
                        item_id=item_id, title=title)
    elif status == 'failed':
        problems.report('videos.transcribe', result.get('code') or 'TRANSIENT.SERVICE_BUSY',
                        result.get('error') or '语音识别失败', item_id=item_id, title=title,
                        next_at=result.get('retry_after'))


_ASR_START = {'tried': False, 'ok': False, 'note': ''}  # 一次运行只试着拉起一次转写服务


def _asr_ready(cfg):
    """转写服务能不能用；capswriter 没开就当场试着拉起一次（10-04 当场自愈），一次运行只拉一次。"""
    from . import asr
    if asr.available(cfg):
        return True
    if cfg.get('mode') != 'capswriter':
        return False
    if not _ASR_START['tried']:
        _ASR_START['tried'] = True
        ok, note = asr.ensure_running(cfg)
        _ASR_START.update(ok=ok, note=note)
        print(f"[videos] 转写服务没开，当场拉起：{note or ('好了' if ok else '没成')}", file=__import__('sys').stderr)
    return _ASR_START['ok'] and asr.available(cfg)


def transcribe(row, *, rescreen=False):
    obj=storage.object_dir(row['source'],row['source_id'])
    output=obj/'derived/transcript.json'
    meta=storage.read_json(obj/'meta.json')
    manifest=storage.read_json(storage.raw_dir(row['source'],row['source_id'],meta['current_version'])/'manifest.json')
    entry=next((m for m in manifest['media'] if m['role']=='video' and m.get('file')),None)
    prev=storage.read_json(output) if output.exists() else {}
    if rescreen and prev.get('status') in ('no_speech','no_audio') and (prev.get('screen') or {}).get('status')!='ok':
        prev.pop('screen',None)  # 当场自愈（问题列表「现在修」）：没人声 / 没音轨、上次也没读出字幕的，重读一次画面字幕
    if prev.get('status') in DONE_STATUSES:
        # 0926：语音转写过的视频补「画面文字」（烧录字幕 / 文字卡），不重转语音
        done=prev
        if entry and 'screen' not in done and _wants_screen(done):
            from .screentext import extract
            done['screen']=extract(obj/entry['file'])
            storage.write_json(output,done)
            if done.get('status')!='ok':_report(row,done)
            render.render_object(row['source'],row['source_id'])
            return {'item_id':row['item_id'],'status':'ok','screen_chars':len(done['screen'].get('text',''))}
        return {'item_id':row['item_id'],'status':'hit'}
    if not entry:return {'item_id':row['item_id'],'status':'no_video'}
    now=_now()
    if _backing_off(prev, now):
        return {'item_id':row['item_id'],'status':'backoff','error':prev.get('error'),'retry_after':prev['retry_after']}
    from . import asr, providers
    cfg=providers.resolve('asrAI')
    if cfg is None or not _asr_ready(cfg):
        # 语音识别没开 / 没配：先不抽音轨（别白跑 ffmpeg），不写 transcript.json（开了以后自然补上）
        got=asr.not_running(cfg) if cfg else providers.skipped_for('asrAI')
        why=got['error']+(f"（当场拉起：{_ASR_START['note']}）" if cfg and _ASR_START['note'] else '')
        result={'status':'skipped','code':got['code'],'error':why}
        _report(row,result)
        return {'item_id':row['item_id'],'status':'skipped','error':got['error']}
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
            result=_speech(audio,prev,now,cfg)
    except subprocess.TimeoutExpired as exc:
        result=_failed(prev,f'超时（{int(exc.timeout or 0)} 秒）：{Path(str(exc.cmd[0] if exc.cmd else "")).name}',now,
                       'TRANSIENT.STEP_TIMEOUT')
    except (subprocess.SubprocessError,OSError) as exc:
        result=_failed(prev,f'{type(exc).__name__}: {exc}'[:300],now)
    finally:audio.unlink(missing_ok=True)
    if _wants_screen(result):
        from .screentext import extract
        old_screen=prev.get('screen') or {}
        # 画面文字与语音并存：背景乐转写成歌词时以它为准；重试转写时上次抽好的画面文字直接沿用
        result['screen']=old_screen if old_screen.get('status')=='ok' else extract(obj/entry['file'])
    _report(row,result)
    if result['status']=='skipped':
        # 识别服务半路没了（探测时还在）：不写 transcript.json，下次再来
        return {'item_id':row['item_id'],'status':'skipped','error':result.get('error')}
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
        result=transcribe(row,rescreen=getattr(args,'rescreen',False)) if args.transcribe else backfill(row)
        results.append(result)
        why=f" {result['error']}" if result.get('error') else ''
        print(row['item_id']+' '+result['status']+why,file=__import__('sys').stderr,flush=True)
    from .catalog import build
    build()
    dump_json({'results':results,'bytes':sum(r.get('bytes',0) for r in results)})
    return 0 if all(r['status'] in QUIET_STATUSES for r in results) else 2

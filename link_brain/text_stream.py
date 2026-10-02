"""收藏问答的流式文本调用；凭据只读内存，不记录请求或鉴权。"""
import csv
import io
import json
import os
from pathlib import Path
import httpx
from . import llm

_CLIENT = httpx.Client(timeout=httpx.Timeout(120, connect=15))


def default_http_config(cfg):
    key = os.environ.get('DASHSCOPE_API_KEY', '').strip()
    base = os.environ.get('DASHSCOPE_OPENAI_BASE', '').strip()
    paths = sorted(Path(os.environ.get('LINK_BRAIN_MODELS_DIR', r'D:\AI\models')).glob('千问*apiKey*.csv'))
    if not key and paths:
        raw = paths[0].read_bytes()
        text = raw.decode('utf-8-sig') if raw.startswith(b'\xef\xbb\xbf') else raw.decode('gbk')
        data = {r[0].strip(): r[1].strip() for r in csv.reader(io.StringIO(text)) if len(r)>=2}
        key = data.get('apiKey','');base = base or data.get('openAiCompatible','')
    return {**cfg, 'apiKey':key, 'endpoint':(base or 'https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')+'/chat/completions',
            'model':cfg.get('model') or llm.load_config()['model']}


# 1001（审计 C-1）：命令行模型吃的是陌生人写的收藏原文和评论，本机 claude / codex 的全局设置又是全权限
# （bypassPermissions / danger-full-access）。这里强制收权，data.json 里存着的旧命令也一并兜住。
CLAUDE_DENIED_TOOLS = ('Bash', 'PowerShell', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'WebFetch', 'WebSearch')
_UNSAFE_FLAGS = ('--dangerously-skip-permissions', '--dangerously-bypass-approvals-and-sandbox', '--full-auto', '--yolo')


def _prog(token: str) -> str:
    name = token.strip('"\'').replace('\\', '/').rsplit('/', 1)[-1].lower()
    for ext in ('.exe', '.cmd', '.bat', '.ps1'):
        if name.endswith(ext):
            return name[:-len(ext)]
    return name


def _set_flag(cmd, names, value, insert_at):
    """把 names 里任一写法的参数值改成 value（`--x v` 或 `--x=v`）；没有就在 insert_at 插进去。"""
    for i, tok in enumerate(cmd):
        bare = tok.strip('"\'')
        for name in names:
            if bare == name:
                if i + 1 < len(cmd):
                    cmd[i + 1] = value
                else:
                    cmd.append(value)
                return cmd
            if bare.startswith(name + '='):
                cmd[i] = f'{name}={value}'
                return cmd
    cmd[insert_at:insert_at] = [names[0], value]
    return cmd


def harden_command(cmd):
    """claude：--permission-mode default + 禁用会动本机的工具 + 不加载任何 MCP；codex：-s read-only。已有同类参数不重复加。"""
    cmd = [t for t in cmd if t.strip('"\'') not in _UNSAFE_FLAGS]
    if not cmd:
        return cmd
    prog = _prog(cmd[0])
    if prog == 'claude':
        cmd = _set_flag(cmd, ('--permission-mode',), 'default', len(cmd))
        for i, tok in enumerate(cmd):
            bare = tok.strip('"\'')
            if bare in ('--disallowedTools', '--disallowed-tools') and i + 1 < len(cmd):
                have = {t for t in cmd[i + 1].strip('"\'').replace(',', ' ').split() if t}
                missing = [t for t in CLAUDE_DENIED_TOOLS if t not in have]
                if missing:
                    cmd[i + 1] = ','.join([*sorted(have), *missing])
                break
        else:
            cmd += ['--disallowedTools', ','.join(CLAUDE_DENIED_TOOLS)]
        if not any(t.strip('"\'') == '--strict-mcp-config' for t in cmd):
            cmd.append('--strict-mcp-config')
    elif prog == 'codex':
        at = next((i + 1 for i, t in enumerate(cmd) if t.strip('"\'') == 'exec'), 1)
        cmd = _set_flag(cmd, ('-s', '--sandbox'), 'read-only', at)
    return cmd


CLI_TIMEOUT_DEFAULT = 180  # 秒；cfg['timeoutSec'] 覆盖（CONVENTIONS §6.6）


def cli_call(instruction, text, cfg, on_delta=None):
    """本机命令行模型（0926）：如 `codex exec -` / `claude -p`，用它们自己的登录，不需要 API key。
    提示词走 stdin，stdout 边读边吐。"""
    import subprocess
    cmd = cfg.get('command') or []
    if isinstance(cmd, str):
        import shlex
        cmd = shlex.split(cmd, posix=False)
    if not cmd:
        return {'status': 'failed', 'error': '命令行模型没有填命令'}
    cmd = harden_command(list(cmd))
    import tempfile
    # 空目录里跑：别让 codex/claude 去翻仓库文件；stderr 进临时文件——它进度日志很多，管道读不及会把进程堵死
    err_file = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace')
    try:
        proc = subprocess.Popen(cmd, cwd=tempfile.gettempdir(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err_file,
                                text=True, encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as exc:
        err_file.close()
        return {'status': 'failed', 'error': f'找不到命令 {cmd[0]}：{exc.strerror or exc}'}
    # CONVENTIONS §6.6：超时 = cfg.timeoutSec（默认 180 秒）；到点整棵杀（procs.kill_tree，不碰读取服务），
    # 读 stdout 的循环随管道关闭结束。看门狗是个定时器线程：主线程照常边读边吐。
    import threading
    from . import procs
    try:
        limit = float(cfg.get('timeoutSec') or CLI_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        limit = float(CLI_TIMEOUT_DEFAULT)
    timed_out = threading.Event()

    def _expire():
        if proc.poll() is None:
            timed_out.set()
            procs.kill_tree(proc.pid)
            try:
                proc.kill()
            except OSError:
                pass

    watchdog = threading.Timer(limit, _expire)
    watchdog.daemon = True
    watchdog.start()
    chunks = []
    try:
        try:
            proc.stdin.write(instruction + '\n\n' + text)
            proc.stdin.close()
        except OSError:
            pass  # 进程已经退出 / 被看门狗杀了：下面按退出码和输出判
        for line in proc.stdout:
            chunks.append(line)
            if on_delta:
                on_delta(line)
        code = proc.wait()
    finally:
        watchdog.cancel()
    err_file.seek(0)
    err = err_file.read()
    err_file.close()
    out = ''.join(chunks).strip()
    if timed_out.is_set():
        return {'status': 'failed', 'code': 'TRANSIENT.STEP_TIMEOUT',
                'error': f'{cmd[0]} 超过 {limit:.0f} 秒没有答完，已停止'}
    if code != 0 or not out:
        tail = (err or out).strip().splitlines()[-1:] or ['无输出']
        return {'status': 'failed', 'error': f'{cmd[0]} 失败：{tail[0][:200]}'}
    return {'status': 'ok', 'text': out, 'usage': None, 'truncated': False}


def call(instruction, text, cfg, on_delta=None):
    if cfg.get('mode') == 'cli':
        return cli_call(instruction, text, cfg, on_delta)
    if cfg.get('mode') != 'http' or not cfg.get('endpoint'):
        cfg=default_http_config(cfg)
    return http_call(instruction,text,cfg,on_delta)


def http_call(instruction,text,cfg,on_delta=None):
    cfg = dict(cfg)
    # 1001（审计 C-3）：条目自己填的 apiKey 优先；仓外密钥文件只在没填 key 时兜底
    if cfg.get('keyFile') and not str(cfg.get('apiKey') or '').strip():
        try:
            raw = Path(cfg['keyFile']).read_bytes()
            text_csv = raw.decode('utf-8-sig') if raw.startswith(b'\xef\xbb\xbf') else raw.decode('gbk')
            data = {r[0].strip():r[1].strip() for r in csv.reader(io.StringIO(text_csv)) if len(r)>=2}
            cfg['apiKey'] = data.get(cfg.get('keyField') or 'apiKey', '')
        except (OSError, UnicodeError):
            return {'status':'failed','error':'无法读取已配置的仓外密钥文件'}
    headers={'Content-Type':'application/json'}
    if cfg.get('apiKey'):headers['Authorization']='Bearer '+cfg['apiKey'].strip()
    body={'model':cfg.get('model') or llm.load_config().get('answer_model') or llm.load_config()['model'],
          'messages':[{'role':'system','content':instruction},{'role':'user','content':text}],
          'max_tokens':int(cfg.get('maxTokens') or 1200),'stream':True,'temperature':.3}
    if body['model'].startswith('deepseek'):
        body['thinking']={'type':'enabled' if cfg.get('thinking') else 'disabled'}
        if cfg.get('thinking'):body['reasoning_effort']='low'
    if cfg.get('responseFormat'):
        body['response_format']=cfg['responseFormat']
    chunks=[];usage=None;finish_reason=None
    try:
        with _CLIENT.stream('POST',cfg['endpoint'],headers=headers,json=body) as response:
            if response.status_code>=400:
                return {'status':'failed','error':f'模型接口 HTTP {response.status_code}；请检查模型权限或配置'}
            for line in response.iter_lines():
                if not line.startswith('data:'):continue
                data=line[5:].strip()
                if data=='[DONE]':break
                event=json.loads(data)
                if event.get('error'):return {'status':'failed','error':'模型流返回错误，回答未完成'}
                usage=event.get('usage') or usage
                choice=(event.get('choices') or [{}])[0]
                finish_reason=choice.get('finish_reason') or finish_reason
                delta=(choice.get('delta') or {}).get('content') or ''
                if delta:
                    chunks.append(delta)
                    if on_delta:on_delta(delta)
        return {'status':'ok','text':''.join(chunks),'usage':usage,'truncated':finish_reason=='length'}
    except (httpx.HTTPError,ValueError) as exc:
        return {'status':'failed','error':'模型连接失败：'+type(exc).__name__}

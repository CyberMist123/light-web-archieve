"""文本模型调用（问答、主题扩词、归档摘要都走这里）；凭据只读内存，不记录请求或鉴权。

CONVENTIONS §4：`call(instruction, text, cfg, on_delta)` 返回统一形状 R
`{status: ok|failed|skipped, text, code, error, usage, truncated, api_error}`；HTTP 状态翻成故障码。
没配接口 = skipped（SKIPPED.NOT_CONFIGURED），不算失败。模型名、接口地址只认设置，不再从 llm-config.yaml 回落。
"""
import json
import threading
from contextvars import ContextVar

import httpx

from . import providers

_CLIENT = httpx.Client(timeout=httpx.Timeout(120, connect=15))

# 第 3 批「停止」：调用方（serve.py 的问答 worker）把一个 threading.Event 放进这里；用户点停止 = set()。
# cli_call 到点整棵杀命令行模型（procs.kill_tree，不碰读取服务）；http_call 关掉流。返回 status=cancelled。
CANCEL: ContextVar = ContextVar('lb_text_cancel', default=None)


def cancelled_result(text=None):
    return providers.result('cancelled', text or None, error='已停止')


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


def _watch_cli(proc, limit, cancel, finished, timed_out, stopped):
    """命令行模型的看门狗：到 limit 秒（timed_out）或用户点停止（stopped）就整棵杀，不碰读取服务。"""
    import time
    from . import procs
    deadline = time.monotonic() + limit
    while not finished.wait(0.2):
        hit = timed_out if time.monotonic() >= deadline else stopped if cancel is not None and cancel.is_set() else None
        if hit is None:
            continue
        if proc.poll() is None:
            hit.set()
            procs.kill_tree(proc.pid)
            try:
                proc.kill()
            except OSError:
                pass
        return


def cli_call(instruction, text, cfg, on_delta=None):
    """本机命令行模型（0926）：如 `codex exec -` / `claude -p`，用它们自己的登录，不需要 API key。
    提示词走 stdin，stdout 边读边吐。"""
    import subprocess
    cmd = cfg.get('command') or []
    if isinstance(cmd, str):
        import shlex
        cmd = shlex.split(cmd, posix=False)
    if not cmd:
        return providers.skipped('textAI', '命令行模型没有填命令')
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
        return providers.skipped('textAI', f'找不到命令 {cmd[0]}：{exc.strerror or exc}')
    # CONVENTIONS §6.6：超时 = cfg.timeoutSec（默认 180 秒）；到点或用户点停止 → 整棵杀（procs.kill_tree，不碰读取服务），
    # 读 stdout 的循环随管道关闭结束。看门狗是个线程：主线程照常边读边吐。
    try:
        limit = float(cfg.get('timeoutSec') or CLI_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        limit = float(CLI_TIMEOUT_DEFAULT)
    timed_out = threading.Event()
    stopped = threading.Event()
    finished = threading.Event()
    watchdog = threading.Thread(target=_watch_cli, args=(proc, limit, CANCEL.get(), finished, timed_out, stopped),
                                daemon=True)
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
        finished.set()
    err_file.seek(0)
    err = err_file.read()
    err_file.close()
    out = ''.join(chunks).strip()
    if stopped.is_set():
        return cancelled_result(out)
    if timed_out.is_set():
        return providers.result('failed', code='TRANSIENT.STEP_TIMEOUT',
                                error=f'{cmd[0]} 超过 {limit:.0f} 秒没有答完，已停止', api_error=True)
    if code != 0 or not out:
        tail = (err or out).strip().splitlines()[-1:] or ['无输出']
        return providers.result('failed', code='TRANSIENT.SERVICE_BUSY', error=f'{cmd[0]} 失败：{tail[0][:200]}',
                                api_error=True)
    return providers.result('ok', out)


def call(instruction, text, cfg, on_delta=None, *, cap='textAI'):
    """按 cfg.mode 分流：cli → 本机命令行；http → OpenAI 兼容流式接口；off / 没配好 → skipped。"""
    cfg = dict(cfg or {})
    resolved, why = providers.finalize(cap, cfg)
    if resolved is None:
        return providers.skipped(cap, why or '文本 AI 没配置', disabled=cfg.get('mode') == 'off')
    cancel = CANCEL.get()
    if cancel is not None and cancel.is_set():
        return cancelled_result()
    if resolved.get('mode') == 'cli':
        return cli_call(instruction, text, resolved, on_delta)
    return http_call(instruction, text, resolved, on_delta)


def http_call(instruction, text, cfg, on_delta=None):
    cfg = dict(cfg)
    if not cfg.get('endpoint'):
        return providers.skipped('textAI', '文本 AI 没填接口地址')
    if not str(cfg.get('model') or '').strip():
        return providers.skipped('textAI', '文本 AI 没填模型名')
    if 'apiKey' not in cfg or cfg.get('keyFile'):
        key, err = providers.resolve_key(cfg)
        if err and not key:
            return providers.result('failed', code='NEEDS_HUMAN.AUTH_FAILED', error=err, api_error=True)
        cfg['apiKey'] = key
    elif cfg.get('keyError') and not cfg.get('apiKey'):
        return providers.result('failed', code='NEEDS_HUMAN.AUTH_FAILED', error=cfg['keyError'], api_error=True)
    headers = {'Content-Type': 'application/json'}
    if cfg.get('apiKey'):
        headers['Authorization'] = 'Bearer ' + str(cfg['apiKey']).strip()
    body = {'model': cfg['model'],
            'messages': [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': text}],
            'max_tokens': int(cfg.get('maxTokens') or 1200), 'stream': True, 'temperature': .3}
    if body['model'].startswith('deepseek'):
        body['thinking'] = {'type': 'enabled' if cfg.get('thinking') else 'disabled'}
        if cfg.get('thinking'):
            body['reasoning_effort'] = 'low'
    if cfg.get('responseFormat'):
        body['response_format'] = cfg['responseFormat']
    try:
        limit = float(cfg.get('timeoutSec') or 120)
    except (TypeError, ValueError):
        limit = 120.0
    chunks = []
    usage = None
    finish_reason = None
    cancel = CANCEL.get()
    finished = threading.Event()
    try:
        with _CLIENT.stream('POST', cfg['endpoint'], headers=headers, json=body,
                            timeout=httpx.Timeout(limit, connect=15)) as response:
            if cancel is not None:
                # 用户点停止：从旁边把流关掉，下面的 iter_lines 立刻抛出 / 结束
                def _watch():
                    while not finished.wait(0.2):
                        if cancel.is_set():
                            try:
                                response.close()
                            except Exception:  # noqa: BLE001
                                pass
                            return
                threading.Thread(target=_watch, daemon=True).start()
            if response.status_code >= 400:
                try:
                    detail = response.read().decode('utf-8', 'replace')[:2000]
                except httpx.HTTPError:
                    detail = ''
                return providers.http_failure(response.status_code, detail)
            for line in response.iter_lines():
                if cancel is not None and cancel.is_set():
                    break
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                event = json.loads(data)
                if event.get('error'):
                    err = event['error']
                    detail = json.dumps(err, ensure_ascii=False) if not isinstance(err, str) else err
                    code = providers.http_code(int((err or {}).get('code') or 500) if isinstance(err, dict)
                                               and str((err or {}).get('code') or '').isdigit() else 500, detail)
                    return providers.result('failed', ''.join(chunks) or None, code=code,
                                            error='模型流返回错误，回答未完成', api_error=True)
                usage = event.get('usage') or usage
                choice = (event.get('choices') or [{}])[0]
                finish_reason = choice.get('finish_reason') or finish_reason
                delta = (choice.get('delta') or {}).get('content') or ''
                if delta:
                    chunks.append(delta)
                    if on_delta:
                        on_delta(delta)
        if cancel is not None and cancel.is_set():
            return cancelled_result(''.join(chunks))
        return providers.result('ok', ''.join(chunks), usage=usage, truncated=finish_reason == 'length',
                                model=cfg['model'])
    except (httpx.HTTPError, httpx.StreamError, RuntimeError, OSError) as exc:
        if cancel is not None and cancel.is_set():
            return cancelled_result(''.join(chunks))
        if isinstance(exc, httpx.HTTPError):
            return providers.network_failure(exc)
        raise
    except ValueError:
        return providers.result('failed', code='TRANSIENT.HTTP_5XX', error='模型流的数据坏了，回答未完成',
                                api_error=True)
    finally:
        finished.set()

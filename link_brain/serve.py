"""单进程 JSON-lines 问答 worker；stdout 只发协议，空闲十分钟退出。

协议（一行一个 JSON）：
  入 {"id", "question", "history", "model"}                     → 出 start · phase* · delta* · result
  入 {"id", "type": "cancel"}（第 3 批「停止」，CONVENTIONS §6.7） → 正在答的那条：杀掉它起的 claude/codex（不碰读取服务）、
     关掉 HTTP 流，回 result status=cancelled（带已生成的半截）；还在排队的那条：轮到时直接回 cancelled。
"""
import json
import queue
import sys
import threading
from . import ask, text_stream


def _warm():
    """进程一起来就载好向量矩阵、打通 embedding 连接，第一问不再付冷启动。失败无所谓。"""
    try:
        from . import semantic
        semantic._load_matrix(semantic.load_config()['model'])
        semantic.query_vector('收藏')
    except Exception:  # noqa: BLE001 - 预热失败不影响问答
        pass


def run(args):
    incoming = queue.Queue()
    lock = threading.Lock()
    state = {'id': None, 'cancel': None}
    cancelled = set()

    def read():
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                msg = None
            if isinstance(msg, dict) and msg.get('type') == 'cancel':
                with lock:
                    if msg.get('id') is not None and msg.get('id') == state['id']:
                        state['cancel'].set()
                    else:
                        cancelled.add(msg.get('id'))
                continue
            incoming.put(line)
        incoming.put(None)
    threading.Thread(target=read, daemon=True).start()
    threading.Thread(target=_warm, daemon=True).start()

    def emit(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)
    while True:
        try:
            line = incoming.get(timeout=600)
        except queue.Empty:
            return 0
        if line is None:
            return 0
        request = {}
        try:
            request = json.loads(line)
            request_id = request['id']
            with lock:
                if request_id in cancelled:
                    cancelled.discard(request_id)
                    emit({'id': request_id, 'type': 'result', 'result': {'status': 'cancelled', 'markdown': ''}})
                    continue
                ev = threading.Event()
                state.update(id=request_id, cancel=ev)
            token = text_stream.CANCEL.set(ev)
            try:
                emit({'id': request_id, 'type': 'start'})
                result = ask.answer(request['question'], request.get('history'), request.get('include'),
                                    model=request.get('model') or '',
                                    on_delta=lambda text: emit({'id': request_id, 'type': 'delta', 'text': text}),
                                    on_phase=lambda text: emit({'id': request_id, 'type': 'phase', 'text': text}))
            finally:
                text_stream.CANCEL.reset(token)
                with lock:
                    state.update(id=None, cancel=None)
            emit({'id': request_id, 'type': 'result', 'result': result})
        except Exception as exc:
            emit({'id': request.get('id'), 'type': 'result', 'result': {'status': 'error', 'markdown': '问答失败：' + type(exc).__name__}})

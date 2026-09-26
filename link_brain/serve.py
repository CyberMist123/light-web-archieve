"""单进程 JSON-lines 问答 worker；stdout 只发协议，空闲十分钟退出。"""
import json
import queue
import sys
import threading
from . import ask


def _warm():
    """进程一起来就载好向量矩阵、打通 embedding 连接，第一问不再付冷启动。失败无所谓。"""
    try:
        from . import semantic
        semantic._load_matrix(semantic.load_config()['model'])
        semantic.query_vector('收藏')
    except Exception:  # noqa: BLE001 - 预热失败不影响问答
        pass


def run(args):
    incoming=queue.Queue()
    def read():
        for line in sys.stdin:incoming.put(line)
        incoming.put(None)
    threading.Thread(target=read,daemon=True).start()
    threading.Thread(target=_warm,daemon=True).start()
    def emit(value):
        print(json.dumps(value,ensure_ascii=False),flush=True)
    while True:
        try:line=incoming.get(timeout=600)
        except queue.Empty:return 0
        if line is None:return 0
        request={}
        try:
            request=json.loads(line)
            request_id=request['id']
            emit({'id':request_id,'type':'start'})
            result=ask.answer(request['question'],request.get('history'),request.get('include'),
                on_delta=lambda text:emit({'id':request_id,'type':'delta','text':text}))
            emit({'id':request_id,'type':'result','result':result})
        except Exception as exc:
            emit({'id':request.get('id'),'type':'result','result':{'status':'error','markdown':'问答失败：'+type(exc).__name__}})

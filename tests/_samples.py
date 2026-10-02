"""合成样例（测试和干净 venv 验收共用）：不依赖 pymupdf，也不碰任何真实笔记。

- text_pdf：手写的最小 PDF，Helvetica 文字层（只能写 ASCII）；
- image_pdf：Pillow 把带字的图存成 PDF（没有文字层 = 扫描件）；
- blank_pdf：pypdfium2 新建的空白页；
- encrypted_pdf_bytes：tests/fixtures/encrypted.pdf（AES-256，有打开密码，内容只有一句 secret tutorial）；
- docx：python-docx 现做一份带标题、列表、表格、超链接文字的 Word；
- FakeCapsWriter：本进程里的假 CapsWriter-Offline 服务端（照它 core/protocol.py 的消息格式），测试里绝不连真的。
"""

from __future__ import annotations

import base64
import json
import socket
import threading
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def text_pdf(path: Path, pages: list[list[str]]) -> Path:
    """每页若干行 ASCII 文字的真文字层 PDF。"""
    objs: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, lines in enumerate(pages):
        content_id = 4 + 2 * i
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode())
        ops = ["BT", "/F1 14 Tf", "16 TL", "72 720 Td"]
        for line in lines:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops += [f"({safe}) Tj", "T*"]
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path = Path(path)
    path.write_bytes(bytes(out))
    return path


def image_pdf(path: Path, page_texts: list[str]) -> Path:
    """扫描件：每页一张画了字的图，没有文字层。"""
    from PIL import Image, ImageDraw, ImageFont
    images = []
    for text in page_texts:
        img = Image.new("RGB", (1240, 900), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=72)
        except TypeError:
            font = ImageFont.load_default()
        draw.text((80, 200), text, fill="black", font=font)
        images.append(img)
    path = Path(path)
    images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=150)
    return path


def blank_pdf(path: Path, pages: int = 2) -> Path:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(612, 792)
    doc.save(str(path))
    doc.close()
    return Path(path)


def encrypted_pdf_bytes() -> bytes:
    return (FIXTURES / "encrypted.pdf").read_bytes()


def docx(path: Path) -> Path:
    from docx import Document
    doc = Document()
    doc.add_heading("合成说明书", level=1)
    doc.add_paragraph("这是一份测试用的 Word 文档。")
    doc.add_paragraph("第一条要点", style="List Bullet")
    doc.add_paragraph("第二条要点", style="List Number")
    table = doc.add_table(rows=3, cols=2)
    for r, row in enumerate([("材料", "用量"), ("番茄", "两个"), ("鸡蛋", "三个")]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    doc.save(str(path))
    return Path(path)


RATE = 16000


class FakeCapsWriter:
    """收到一段（is_final）就回一条 RecognitionMessage：text = 「第N段」；reply=False 时一声不吭（测超时）。"""

    def __init__(self, *, reply=True):
        from websockets.sync.server import serve
        self.received: list[dict] = []
        self.reply = reply
        self.subprotocols: list = []
        self.server = serve(self._handler, "127.0.0.1", 0, subprotocols=["binary"], max_size=None)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _handler(self, ws):
        self.subprotocols.append(ws.subprotocol)
        for raw in ws:
            msg = json.loads(raw)
            self.received.append(msg)
            if msg["is_final"] and self.reply:
                seconds = len(base64.b64decode(msg["data"])) / 4 / RATE
                ws.send(json.dumps({"task_id": msg["task_id"], "is_final": True, "duration": seconds,
                                    "time_start": msg["time_start"], "time_submit": 0, "time_complete": 0,
                                    "text": f"第{len(self.received)}段", "text_accu": "", "tokens": [], "timestamps": []},
                                   ensure_ascii=False))

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=5)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

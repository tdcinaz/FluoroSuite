"""Serve the rendered 8-bit live preview to other machines as MJPEG over HTTP.

The capture page pushes each already-windowed 8-bit grayscale frame to a
``PreviewStreamServer``. A background thread JPEG-encodes the newest frame and
fans it out to any browser on the LAN via ``multipart/x-mixed-replace``, so no
client software beyond a web browser is required.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage


def local_ip() -> str:
    """Best-effort LAN address of this machine for display in the preview URL."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _encode_jpeg(frame: np.ndarray, quality: int) -> bytes | None:
    frame = np.ascontiguousarray(frame)
    height, width = frame.shape
    image = QImage(frame.data, width, height, width, QImage.Format.Format_Grayscale8)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "JPEG", quality):
        return None
    return bytes(buffer.data())


class PreviewBroadcaster:
    """Encodes the newest rendered frame to JPEG and shares it with MJPEG clients."""

    def __init__(self, quality: int = 80) -> None:
        self._quality = int(quality)
        self._raw_cond = threading.Condition()
        self._raw: np.ndarray | None = None
        self._raw_seq = 0
        self._clients = 0
        self._jpeg_cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._jpeg_seq = 0
        self._stopped = False
        self._thread = threading.Thread(target=self._encode_loop, name="preview-encoder", daemon=True)
        self._thread.start()

    def submit(self, frame: np.ndarray) -> None:
        """Publish a rendered 8-bit frame; skipped entirely when nobody is watching."""
        with self._raw_cond:
            if self._clients <= 0 or self._stopped:
                return
            self._raw = frame
            self._raw_seq += 1
            self._raw_cond.notify()

    def client_connected(self) -> None:
        with self._raw_cond:
            self._clients += 1

    def client_disconnected(self) -> None:
        with self._raw_cond:
            self._clients = max(0, self._clients - 1)

    def client_count(self) -> int:
        with self._raw_cond:
            return self._clients

    def wait_for_frame(self, last_seq: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        with self._jpeg_cond:
            if self._jpeg_seq == last_seq and not self._stopped:
                self._jpeg_cond.wait(timeout)
            return self._jpeg_seq, self._jpeg

    def stop(self) -> None:
        self._stopped = True
        with self._raw_cond:
            self._raw_cond.notify_all()
        with self._jpeg_cond:
            self._jpeg_cond.notify_all()

    def _encode_loop(self) -> None:
        last = 0
        while not self._stopped:
            with self._raw_cond:
                while self._raw_seq == last and not self._stopped:
                    self._raw_cond.wait()
                if self._stopped:
                    return
                frame = self._raw
                last = self._raw_seq
            if frame is None:
                continue
            jpeg = _encode_jpeg(frame, self._quality)
            if jpeg is None:
                continue
            with self._jpeg_cond:
                self._jpeg = jpeg
                self._jpeg_seq += 1
                self._jpeg_cond.notify_all()


_INDEX_PAGE = b"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FluoroSuite live preview</title>
<style>
  body { margin: 0; background: #0b0f17; color: #94a3b8;
         font-family: system-ui, sans-serif; text-align: center; }
  h1 { font-size: 1rem; font-weight: 600; padding: 12px; margin: 0; }
  img { max-width: 100vw; max-height: calc(100vh - 48px); image-rendering: pixelated; }
</style>
</head>
<body>
<h1>FluoroSuite live preview &mdash; research use only, not for diagnosis</h1>
<img src="/stream.mjpg" alt="Live preview">
</body>
</html>
"""


class _PreviewRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _broadcaster(self) -> PreviewBroadcaster:
        return self.server.broadcaster  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_index()
        elif path == "/stream.mjpg":
            self._serve_stream()
        else:
            self.send_error(404)

    def _serve_index(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_INDEX_PAGE)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(_INDEX_PAGE)

    def _serve_stream(self) -> None:
        broadcaster = self._broadcaster
        broadcaster.client_connected()
        try:
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            last = 0
            while True:
                seq, jpeg = broadcaster.wait_for_frame(last)
                if jpeg is None or seq == last:
                    continue
                last = seq
                header = (
                    b"--FRAME\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                )
                self.wfile.write(header)
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            broadcaster.client_disconnected()

    def log_message(self, *args: object) -> None:  # silence per-request logging
        pass


class PreviewStreamServer:
    """Threaded MJPEG server that broadcasts the rendered live preview over HTTP."""

    def __init__(self, host: str, port: int, quality: int = 80) -> None:
        self.host = host
        self.port = port
        self.broadcaster = PreviewBroadcaster(quality)
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        server = ThreadingHTTPServer((self.host, self.port), _PreviewRequestHandler)
        server.daemon_threads = True
        server.broadcaster = self.broadcaster  # type: ignore[attr-defined]
        self._server = server
        threading.Thread(target=server.serve_forever, name="preview-http", daemon=True).start()

    def submit(self, frame: np.ndarray) -> None:
        self.broadcaster.submit(frame)

    def client_count(self) -> int:
        return self.broadcaster.client_count()

    def url(self) -> str:
        return f"http://{local_ip()}:{self.port}/"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self.broadcaster.stop()

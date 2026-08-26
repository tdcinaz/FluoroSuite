"""Reconstruct GigE Vision (GVSP) frames from the forwarded raw stream.

Ported and streamlined from the legacy Fluoro live-view daemon. The Windows relay
sends length-prefixed link-layer packets over TCP; frames are reassembled by GVSP
block id and published as the newest 1024x1024 16-bit frame.
"""

from __future__ import annotations

import socket
import threading
import time

import numpy as np

from ..config import (
    COLUMNS,
    EXPOSURE_BRIGHT_LEVEL,
    EXPOSURE_FRACTION,
    GVCP_CONTROL_PORT,
    MAX_STREAM_PACKET,
    PIXEL_BYTES,
    ROWS,
)


def is_exposure(frame_bytes: bytes) -> bool:
    image = np.frombuffer(frame_bytes, dtype="<u2").reshape((ROWS, COLUMNS))
    return bool(np.mean(image[::8, ::8] >= EXPOSURE_BRIGHT_LEVEL) >= EXPOSURE_FRACTION)


class LatestFrame:
    """Single-slot holder that always keeps the newest reconstructed frame."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._pixels: bytes | None = None
        self._seq = 0

    def set(self, pixels: bytes) -> None:
        with self._cond:
            self._pixels = pixels
            self._seq += 1
            self._cond.notify_all()

    def snapshot(self) -> tuple[int, bytes | None]:
        with self._cond:
            return self._seq, self._pixels


class PreviewStore:
    """Thread-safe live ingest metrics used by the capture page."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.received = 0
        self.dropped = 0
        self.fps = 0.0
        self.state = "waiting"
        self.exposure = False
        self.error: str | None = None
        self.suggested: tuple[int, int] | None = None

    def note_received(self) -> None:
        with self._lock:
            self.received += 1

    def note_dropped(self) -> None:
        with self._lock:
            self.dropped += 1

    def set_error(self, error: object) -> None:
        with self._lock:
            self.error = str(error)

    def update_metrics(self, fps: float, state: str, exposure: bool, suggested: tuple[int, int] | None) -> None:
        with self._lock:
            self.fps = round(fps, 1)
            self.state = state
            self.exposure = exposure
            if suggested is not None:
                self.suggested = suggested
            self.error = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "received": self.received,
                "dropped": self.dropped,
                "fps": self.fps,
                "state": self.state,
                "exposure": self.exposure,
                "error": self.error,
                "suggested": self.suggested,
            }


class _FrameProcessor:
    """Joins reassembled payloads off the socket thread, records, and publishes."""

    def __init__(self, latest: LatestFrame, store: PreviewStore, recorder, max_pending: int = 8) -> None:
        import queue

        self.latest = latest
        self.store = store
        self.recorder = recorder
        self.queue: "queue.Queue[dict | None]" = queue.Queue(maxsize=max_pending)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, payloads: dict) -> None:
        if self.queue.full():
            self.store.note_dropped()
        else:
            self.queue.put_nowait(payloads)

    def stop(self) -> None:
        self.queue.put(None)

    def _run(self) -> None:
        while True:
            payloads = self.queue.get()
            if payloads is None:
                return
            pixels = b"".join(payloads[key] for key in sorted(payloads))
            if len(pixels) != PIXEL_BYTES:
                self.store.note_dropped()
                continue
            if self.recorder is not None:
                self.recorder.capture(pixels)
            self.latest.set(pixels)
            self.store.note_received()


class _StreamAssembler:
    """Reassemble GVSP frames from a continuous stream of link-layer packets."""

    def __init__(self, processor: _FrameProcessor) -> None:
        self.processor = processor
        self.current_block: int | None = None
        self.payloads: dict[int, bytes] = {}

    def _finalize(self) -> None:
        if not self.payloads:
            return
        self.processor.submit(self.payloads)
        self.payloads = {}

    def feed(self, packet: bytes) -> None:
        if len(packet) < 50 or packet[12:14] != b"\x08\x00" or packet[23] != 17:
            return
        ip_header_length = (packet[14] & 15) * 4
        udp_offset = 14 + ip_header_length
        gvsp_offset = udp_offset + 8
        if gvsp_offset + 8 > len(packet):
            return
        if int.from_bytes(packet[udp_offset : udp_offset + 2], "big") == GVCP_CONTROL_PORT:
            return
        block = int.from_bytes(packet[gvsp_offset + 2 : gvsp_offset + 4], "big")
        packet_format = packet[gvsp_offset + 4] & 15
        if self.current_block is None:
            self.current_block = block
        if block != self.current_block:
            self._finalize()
            self.current_block = block
        if packet_format == 3:
            packet_id = int.from_bytes(packet[gvsp_offset + 5 : gvsp_offset + 8], "big")
            self.payloads[packet_id] = packet[gvsp_offset + 8 :]
        elif packet_format == 2:
            self._finalize()
            self.current_block = None


class StreamReceiver:
    """Listens for the forwarded raw GVSP stream and publishes reconstructed frames."""

    def __init__(self, latest: LatestFrame, store: PreviewStore, recorder, host: str, port: int) -> None:
        self.latest = latest
        self.store = store
        self.recorder = recorder
        self.host = host
        self.port = port
        self._server: socket.socket | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._serve, name="gvsp-stream-receiver", daemon=True).start()
        threading.Thread(target=self._metrics_loop, name="capture-metrics", daemon=True).start()

    def stop(self) -> None:
        self._stopped.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass

    def _serve(self) -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(4)
        except OSError as error:
            self.store.set_error(f"Cannot bind {self.host}:{self.port} ({error})")
            return
        self._server = server
        while not self._stopped.is_set():
            try:
                connection, _address = server.accept()
            except OSError:
                return
            threading.Thread(
                target=self._handle_connection, args=(connection,), daemon=True
            ).start()

    def _handle_connection(self, connection: socket.socket) -> None:
        processor = _FrameProcessor(self.latest, self.store, self.recorder)
        assembler = _StreamAssembler(processor)
        try:
            with connection:
                connection.settimeout(30)
                reader = connection.makefile("rb", buffering=1024 * 1024)
                while not self._stopped.is_set():
                    length_prefix = reader.read(2)
                    if len(length_prefix) < 2:
                        break
                    length = (length_prefix[0] << 8) | length_prefix[1]
                    if length == 0 or length > MAX_STREAM_PACKET:
                        raise ValueError(f"invalid stream packet length {length}")
                    packet = reader.read(length)
                    if len(packet) < length:
                        break
                    assembler.feed(packet)
        except (OSError, ValueError) as error:
            self.store.set_error(error)
        finally:
            processor.stop()

    def _metrics_loop(self, interval: float = 0.5) -> None:
        prev_received = 0
        prev_seq = 0
        prev_time = time.monotonic()
        last_new = time.monotonic()
        while not self._stopped.is_set():
            time.sleep(interval)
            now = time.monotonic()
            snapshot = self.store.snapshot()
            received = int(snapshot["received"])
            delta = now - prev_time
            fps = (received - prev_received) / delta if delta > 0 else 0.0
            prev_received = received
            prev_time = now

            seq, pixels = self.latest.snapshot()
            suggested = None
            exposure = bool(snapshot["exposure"])
            if seq != prev_seq and pixels is not None:
                prev_seq = seq
                last_new = now
                image = np.frombuffer(pixels, dtype="<u2").reshape((ROWS, COLUMNS))
                sample = image[::8, ::8]
                low, high = np.percentile(sample, (1.0, 99.5))
                low = int(low)
                high = int(max(high, low + 1))
                suggested = ((low + high) // 2, high - low)
                exposure = bool(np.mean(sample >= EXPOSURE_BRIGHT_LEVEL) >= EXPOSURE_FRACTION)
            live = (now - last_new) < 1.5
            self.store.update_metrics(fps, "live" if live else "waiting", exposure, suggested)

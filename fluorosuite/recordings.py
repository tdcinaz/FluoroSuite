"""Reading recorded raw fluoroscopy runs (.raw pixel data + .json sidecar).

The on-disk format matches the legacy Fluoro recorder: each run is a flat file of
concatenated 1024x1024 little-endian 16-bit frames with a JSON metadata sidecar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import COLUMNS, PIXEL_BYTES, ROWS


@dataclass(frozen=True, slots=True)
class RecordingInfo:
    path: Path
    frames: int
    started: float | None
    ended: float | None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def duration(self) -> float | None:
        if self.started is None or self.ended is None:
            return None
        return max(0.0, self.ended - self.started)

    @property
    def fps(self) -> float:
        duration = self.duration
        if duration and self.frames:
            return max(1.0, self.frames / duration)
        return 15.0

    def label(self) -> str:
        duration = self.duration
        suffix = f", {duration:.1f}s" if duration else ""
        return f"{self.name}  ({self.frames} f{suffix})"


def list_recordings(directory: Path) -> list[RecordingInfo]:
    if not directory.exists():
        return []
    items: list[RecordingInfo] = []
    for raw in directory.glob("*.raw"):
        try:
            size = raw.stat().st_size
        except OSError:
            continue
        meta = {}
        sidecar = raw.with_suffix(".json")
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text())
            except (OSError, json.JSONDecodeError):
                meta = {}
        items.append(
            RecordingInfo(
                path=raw,
                frames=size // PIXEL_BYTES,
                started=meta.get("started"),
                ended=meta.get("ended"),
            )
        )
    items.sort(key=lambda item: item.started or 0, reverse=True)
    return items


class RecordingReader:
    """Random-access reader for a single recorded run."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.frame_count = self.path.stat().st_size // PIXEL_BYTES

    def read_frame(self, index: int) -> np.ndarray | None:
        if index < 0 or index >= self.frame_count:
            return None
        with open(self.path, "rb") as handle:
            handle.seek(index * PIXEL_BYTES)
            data = handle.read(PIXEL_BYTES)
        if len(data) != PIXEL_BYTES:
            return None
        return np.frombuffer(data, dtype="<u2").reshape((ROWS, COLUMNS))

    def read_all(self) -> np.ndarray:
        """Return every frame as a (frames, rows, columns) uint16 array."""
        with open(self.path, "rb") as handle:
            data = handle.read(self.frame_count * PIXEL_BYTES)
        return np.frombuffer(data, dtype="<u2").reshape((self.frame_count, ROWS, COLUMNS))

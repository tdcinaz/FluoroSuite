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
from .pipeline.models import Circle, TimingAlignmentResult


def _read_sidecar(path: Path) -> dict:
    sidecar = Path(path).with_suffix(".json")
    try:
        metadata = json.loads(sidecar.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _write_analysis_value(path: Path, key: str, value: dict) -> None:
    sidecar = Path(path).with_suffix(".json")
    metadata = _read_sidecar(path)
    analysis = metadata.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
        metadata["analysis"] = analysis
    analysis[key] = value
    temporary = sidecar.with_name(sidecar.name + ".tmp")
    temporary.write_text(json.dumps(metadata, indent=2))
    temporary.replace(sidecar)


def _read_analysis_value(path: Path, key: str) -> object:
    analysis = _read_sidecar(path).get("analysis")
    return analysis.get(key) if isinstance(analysis, dict) else None


def load_saved_roi(path: Path) -> Circle | None:
    value = _read_analysis_value(path, "roi")
    if not isinstance(value, dict):
        return None
    try:
        return Circle(
            center_x=int(value["center_x"]),
            center_y=int(value["center_y"]),
            radius=max(1, int(value["radius"])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_roi(path: Path, roi: Circle) -> None:
    _write_analysis_value(
        path,
        "roi",
        {"center_x": roi.center_x, "center_y": roi.center_y, "radius": roi.radius},
    )


def load_saved_timing_alignment(path: Path) -> TimingAlignmentResult | None:
    value = _read_analysis_value(path, "timing_alignment")
    if not isinstance(value, dict):
        return None
    try:
        return TimingAlignmentResult(
            injection_frame=max(0, int(value["injection_frame"])),
            start_frame=max(0, int(value["start_frame"])),
            fps=max(1.0, float(value["fps"])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_timing_alignment(path: Path, result: TimingAlignmentResult) -> None:
    _write_analysis_value(
        path,
        "timing_alignment",
        {
            "injection_frame": result.injection_frame,
            "start_frame": result.start_frame,
            "fps": result.fps,
        },
    )


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
        meta = _read_sidecar(raw)
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

    def iter_frames(self):
        """Yield frames one at a time without loading the recording into memory."""
        with open(self.path, "rb") as handle:
            for _ in range(self.frame_count):
                data = handle.read(PIXEL_BYTES)
                if len(data) != PIXEL_BYTES:
                    return
                yield np.frombuffer(data, dtype="<u2").reshape((ROWS, COLUMNS))

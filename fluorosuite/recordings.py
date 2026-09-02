"""Reading recorded raw fluoroscopy runs (.raw pixel data + .json sidecar).

The on-disk format matches the legacy Fluoro recorder: each run is a flat file of
concatenated 1024x1024 little-endian 16-bit frames with a JSON metadata sidecar.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

import numpy as np

from .config import COLUMNS, PIXEL_BYTES, ROWS
from .pipeline.models import (
    Circle,
    InletROIResult,
    Rectangle,
    ROIParameters,
    ROIResidenceResult,
    TimingAlignmentResult,
)
from .pipeline.stages import analyze_roi_means

_ANALYSIS_CSV_FIELDS = ("time_s", "roi_mean", "inlet_roi_mean")


def _read_sidecar(path: Path) -> dict:
    sidecar = Path(path).with_suffix(".json")
    try:
        metadata = json.loads(sidecar.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _write_sidecar(path: Path, metadata: dict) -> None:
    sidecar = Path(path).with_suffix(".json")
    temporary = sidecar.with_name(sidecar.name + ".tmp")
    temporary.write_text(json.dumps(metadata, indent=2))
    temporary.replace(sidecar)


def _write_analysis_value(path: Path, key: str, value: object) -> None:
    metadata = _read_sidecar(path)
    analysis = metadata.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
        metadata["analysis"] = analysis
    analysis[key] = value
    _write_sidecar(path, metadata)


def _read_analysis_value(path: Path, key: str) -> object:
    analysis = _read_sidecar(path).get("analysis")
    return analysis.get(key) if isinstance(analysis, dict) else None


def _metadata_fps(metadata: dict) -> float | None:
    try:
        fps = float(metadata["fps"])
    except (KeyError, TypeError, ValueError):
        return None
    return fps if isfinite(fps) and fps > 0 else None


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


def load_saved_inlet_roi(path: Path) -> Rectangle | None:
    value = _read_analysis_value(path, "inlet_roi")
    if not isinstance(value, dict):
        return None
    try:
        return Rectangle(
            center_x=int(value["center_x"]),
            center_y=int(value["center_y"]),
            width=max(1, int(value["width"])),
            height=max(1, int(value["height"])),
            rotation=max(-180, min(180, int(value["rotation"]))),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_inlet_roi(path: Path, roi: Rectangle) -> None:
    _write_analysis_value(
        path,
        "inlet_roi",
        {
            "center_x": roi.center_x,
            "center_y": roi.center_y,
            "width": roi.width,
            "height": roi.height,
            "rotation": roi.rotation,
        },
    )


def load_saved_rotation(path: Path) -> int:
    try:
        rotation = int(_read_analysis_value(path, "rotation"))
    except (TypeError, ValueError):
        return 0
    return max(-180, min(180, rotation))


def save_rotation(path: Path, rotation: int) -> None:
    _write_analysis_value(path, "rotation", max(-180, min(180, int(rotation))))


def load_saved_timing_alignment(path: Path) -> TimingAlignmentResult | None:
    metadata = _read_sidecar(path)
    analysis = metadata.get("analysis")
    value = analysis.get("timing_alignment") if isinstance(analysis, dict) else None
    if not isinstance(value, dict):
        return None
    try:
        return TimingAlignmentResult(
            injection_frame=max(0, int(value["injection_frame"])),
            start_frame=max(0, int(value["start_frame"])),
            fps=max(1.0, _metadata_fps(metadata) or float(value["fps"])),
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


def analysis_data_path(path: Path) -> Path:
    path = Path(path)
    data_file = _read_sidecar(path).get("data_file")
    if isinstance(data_file, str) and data_file and Path(data_file).name == data_file:
        return path.parent / data_file
    return path.with_suffix(".csv")


def load_saved_analysis_result(
    path: Path,
    parameters: ROIParameters,
) -> ROIResidenceResult | None:
    try:
        with analysis_data_path(path).open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return None
        time = np.asarray([float(row["time_s"]) for row in rows], dtype=np.float32)
        roi_mean = np.asarray([float(row["roi_mean"]) for row in rows], dtype=np.float32)
        if time.size > 1:
            intervals = np.diff(time.astype(np.float64))
            if not np.all(np.isfinite(intervals)) or np.any(intervals <= 0):
                raise ValueError("analysis time values must be finite and increasing")
            fps = 1.0 / float(np.median(intervals))
        else:
            timing = load_saved_timing_alignment(path)
            fps = timing.fps if timing is not None else 15.0
        return analyze_roi_means(roi_mean, parameters, fps, time=time)
    except (OSError, csv.Error, KeyError, TypeError, ValueError):
        return None


def load_saved_inlet_analysis_result(path: Path) -> InletROIResult | None:
    try:
        with analysis_data_path(path).open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or not all(row.get("inlet_roi_mean") for row in rows):
            return None
        time = np.asarray([float(row["time_s"]) for row in rows], dtype=np.float32)
        roi_mean = np.asarray([float(row["inlet_roi_mean"]) for row in rows], dtype=np.float32)
        return InletROIResult(time=time, roi_mean=roi_mean)
    except (OSError, csv.Error, KeyError, TypeError, ValueError):
        return None


def save_analysis_results(
    path: Path,
    result: ROIResidenceResult | None,
    inlet_result: InletROIResult | None,
) -> None:
    if result is None and inlet_result is None:
        raise ValueError("at least one analysis result is required")
    for item in (result, inlet_result):
        if item is not None and item.time.size != item.roi_mean.size:
            raise ValueError("analysis time and ROI mean arrays must have equal lengths")
    if result is not None and inlet_result is not None and not np.array_equal(result.time, inlet_result.time):
        raise ValueError("aneurysm and inlet analysis times must match")

    time = result.time if result is not None else inlet_result.time
    assert time is not None

    path = Path(path)
    data_path = path.with_suffix(".csv")
    temporary = data_path.with_name(data_path.name + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(_ANALYSIS_CSV_FIELDS)
        for index, time_value in enumerate(time):
            roi_mean = float(result.roi_mean[index]) if result is not None else ""
            inlet_roi_mean = float(inlet_result.roi_mean[index]) if inlet_result is not None else ""
            writer.writerow((float(time_value), roi_mean, inlet_roi_mean))
    temporary.replace(data_path)

    metadata = _read_sidecar(path)
    metadata["data_file"] = data_path.name
    _write_sidecar(path, metadata)


def save_analysis_result(path: Path, result: ROIResidenceResult) -> None:
    inlet_result = load_saved_inlet_analysis_result(path)
    if inlet_result is not None and not np.array_equal(result.time, inlet_result.time):
        inlet_result = None
    save_analysis_results(path, result, inlet_result)


@dataclass(frozen=True, slots=True)
class RecordingInfo:
    path: Path
    frames: int
    started: float | None
    ended: float | None
    frame_rate: float | None = None

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
        if self.frame_rate is not None and isfinite(self.frame_rate) and self.frame_rate > 0:
            return max(1.0, self.frame_rate)
        duration = self.duration
        if duration and self.frames > 1:
            return max(1.0, (self.frames - 1) / duration)
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
                frame_rate=_metadata_fps(meta),
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

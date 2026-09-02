"""Export corrected fluoroscopy recordings as shareable video files."""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPainterPath

from .config import COLUMNS, DARK_FIELD_FILE, EXPORT_DIR, LIVE_DIR, ROWS
from .recordings import (
    RecordingInfo,
    analysis_data_path,
    list_recordings,
    load_saved_rotation,
    load_saved_timing_alignment,
)
from .visualization import DarkFieldCorrection, Visualization, render_gray, to_qimage

WINDOW_WIDTH = 1700
WINDOW_LEVEL = 800
_RECORDING_STEM = re.compile(r"^.+_([^_]+)_(?:pre|post)_\d+$")


def _trial_designator(path: Path) -> str:
    match = _RECORDING_STEM.fullmatch(Path(path).stem)
    if match is None:
        raise ValueError(f"Cannot determine trial designator from {Path(path).name}")
    return match.group(1)


def export_aligned_analysis_csv(paths: list[Path], output_path: Path) -> None:
    """Export enabled analyses on one timeline beginning five seconds before injection."""
    if not paths:
        raise ValueError("at least one recording is required")

    series: list[tuple[str, list[dict[str, str]]]] = []
    frame_rate: float | None = None
    for path in paths:
        path = Path(path)
        timing = load_saved_timing_alignment(path)
        if timing is None or timing.injection_frame <= 0:
            raise ValueError(f"{path.name} has no detected injection timing")
        if frame_rate is None:
            frame_rate = timing.fps
        elif not np.isclose(timing.fps, frame_rate):
            raise ValueError("enabled recordings do not share the same frame rate")

        designator = _trial_designator(path)
        if any(existing == designator for existing, _rows in series):
            raise ValueError(f"duplicate trial designator: {designator}")
        with analysis_data_path(path).open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or not all(row.get("roi_mean") and row.get("inlet_mean") for row in rows):
            raise ValueError(f"{path.name} has incomplete saved ROI analysis data")
        start_frame = timing.injection_frame - round(5.0 * timing.fps)
        if start_frame < 0:
            raise ValueError(f"{path.name} has less than five seconds before injection")
        series.append((designator, rows[start_frame:]))

    assert frame_rate is not None
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    headers = ["time_s"]
    for designator, _rows in series:
        headers.extend((f"{designator}_roi_mean", f"{designator}_inlet_mean"))
    row_count = max(len(rows) for _designator, rows in series)
    with temporary.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for index in range(row_count):
            output_row: list[object] = [index / frame_rate]
            for _designator, rows in series:
                if index < len(rows):
                    output_row.extend((rows[index]["roi_mean"], rows[index]["inlet_mean"]))
                else:
                    output_row.extend(("", ""))
            writer.writerow(output_row)
    temporary.replace(output_path)


def _playback_bounds(recording: RecordingInfo) -> tuple[int, int]:
    """Return the saved trimmed playback interval, or the complete recording."""
    timing = load_saved_timing_alignment(recording.path)
    return timing.playback_bounds(recording.frames) if timing is not None else (0, recording.frames)


def render_fluoroscopy_view(frame: np.ndarray, lut: np.ndarray, rotation: int) -> np.ndarray:
    """Render a grayscale frame as it appears in the circular fluoroscopy viewport."""
    source = to_qimage(frame, lut)
    height, width = frame.shape
    rendered = QImage(width, height, QImage.Format.Format_Grayscale8)
    rendered.fill(0)

    painter = QPainter(rendered)
    viewport = QRectF(0, 0, width, height)
    clip = QPainterPath()
    clip.addEllipse(viewport)
    painter.setClipPath(clip)
    painter.translate(viewport.center())
    painter.rotate(rotation)
    painter.translate(-viewport.center())
    painter.drawImage(viewport, source)
    painter.end()

    bits = rendered.bits()
    pixels = np.frombuffer(
        bits,
        dtype=np.uint8,
        count=height * rendered.bytesPerLine(),
    ).reshape(height, rendered.bytesPerLine())
    return pixels[:, :width].copy()


def export_recording(
    recording: RecordingInfo,
    output_path: Path,
    correction: DarkFieldCorrection,
    *,
    window_width: int = WINDOW_WIDTH,
    window_level: int = WINDOW_LEVEL,
    ffmpeg: str = "ffmpeg",
    raw: bool = False,
) -> None:
    """Write one trimmed, corrected recording as compressed MP4 or raw 8-bit AVI."""
    executable = shutil.which(ffmpeg)
    if executable is None:
        raise RuntimeError(f"FFmpeg executable not found: {ffmpeg}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lut = Visualization(level=window_level, width=window_width).build_lut()
    rotation = load_saved_rotation(recording.path)
    start, end = _playback_bounds(recording)
    frames = np.memmap(
        recording.path,
        dtype="<u2",
        mode="r",
        shape=(recording.frames, ROWS, COLUMNS),
    )
    encoder_options = (
        ["-c:v", "rawvideo", "-pix_fmt", "gray"]
        if raw
        else [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-vf",
            "format=yuvj420p",
            "-pix_fmt",
            "yuvj420p",
            "-color_range",
            "pc",
            "-colorspace",
            "bt709",
            "-color_trc",
            "iec61966-2-1",
            "-color_primaries",
            "bt709",
        ]
    )
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "gray",
        "-video_size",
        f"{COLUMNS}x{ROWS}",
        "-framerate",
        f"{recording.fps:.6f}",
        "-i",
        "pipe:0",
        "-an",
        *encoder_options,
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for frame in frames[start:end]:
            corrected = correction.apply(frame)
            rendered = render_fluoroscopy_view(corrected, lut, rotation)
            process.stdin.write(rendered.tobytes())
        process.stdin.close()
        stderr = process.stderr.read().decode(errors="replace") if process.stderr is not None else ""
        if process.wait() != 0:
            raise RuntimeError(f"FFmpeg failed while exporting {recording.name}: {stderr.strip()}")
    except BaseException:
        process.kill()
        process.wait()
        output_path.unlink(missing_ok=True)
        raise
    finally:
        del frames


def export_live_trials(
    source_dir: Path,
    output_dir: Path,
    correction: DarkFieldCorrection,
    *,
    overwrite: bool = False,
    window_width: int = WINDOW_WIDTH,
    window_level: int = WINDOW_LEVEL,
    ffmpeg: str = "ffmpeg",
    workers: int | None = None,
    raw: bool = False,
) -> list[Path]:
    """Export every ``TF_`` recording in ``source_dir`` concurrently."""
    exported: list[Path] = []
    trials = [recording for recording in list_recordings(source_dir) if recording.path.stem.startswith("TF_")]
    if not trials:
        raise RuntimeError(f"No TF_ recordings found in {source_dir}")

    pending: list[tuple[RecordingInfo, Path]] = []
    for index, recording in enumerate(trials, start=1):
        suffix = ".avi" if raw else ".mp4"
        output_path = output_dir / f"{recording.path.stem}{suffix}"
        if output_path.exists() and not overwrite:
            print(f"[{index}/{len(trials)}] Skipping {output_path.name}; it already exists")
            continue
        start, end = _playback_bounds(recording)
        print(f"[{index}/{len(trials)}] Exporting {recording.name} ({end - start} frames)")
        pending.append((recording, output_path))

    if not pending:
        return exported
    worker_count = min(workers if workers is not None else min(4, os.cpu_count() or 1), len(pending))
    if worker_count < 1:
        raise ValueError("workers must be at least 1")
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                export_recording,
                recording,
                output_path,
                correction,
                window_width=window_width,
                window_level=window_level,
                ffmpeg=ffmpeg,
                raw=raw,
            )
            for recording, output_path in pending
        ]
        for future, (_recording, output_path) in zip(futures, pending, strict=True):
            future.result()
            exported.append(output_path)
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Export corrected TF fluoroscopy trials as video files")
    parser.add_argument("--source-dir", type=Path, default=LIVE_DIR, help="Directory containing recorded .raw files")
    parser.add_argument("--output-dir", type=Path, default=EXPORT_DIR, help="Destination directory for video files")
    parser.add_argument("--dark-field", type=Path, default=DARK_FIELD_FILE, help="Dark-field calibration .npz file")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing video files")
    parser.add_argument("--raw", action="store_true", help="Export uncompressed 8-bit grayscale AVI instead of MP4")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable to run")
    parser.add_argument("--workers", type=int, help="Number of recordings to export concurrently (default: up to 4)")
    arguments = parser.parse_args()

    correction = DarkFieldCorrection.load(arguments.dark_field)
    if correction is None:
        parser.error(f"Could not load dark-field calibration from {arguments.dark_field}")

    exported = export_live_trials(
        arguments.source_dir,
        arguments.output_dir,
        correction,
        overwrite=arguments.overwrite,
        ffmpeg=arguments.ffmpeg,
        workers=arguments.workers,
        raw=arguments.raw,
    )
    print(f"Exported {len(exported)} video(s) to {arguments.output_dir}")


if __name__ == "__main__":
    main()
"""Export corrected fluoroscopy recordings as shareable MP4 files."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPainterPath

from .config import COLUMNS, DARK_FIELD_FILE, EXPORT_DIR, LIVE_DIR, ROWS
from .recordings import RecordingInfo, list_recordings, load_saved_rotation, load_saved_timing_alignment
from .visualization import DarkFieldCorrection, Visualization, render_gray, to_qimage

WINDOW_WIDTH = 1700
WINDOW_LEVEL = 800


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
) -> None:
    """Write one trimmed, corrected recording as an H.264 MP4 at its captured frame rate."""
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
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
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
) -> list[Path]:
    """Export every ``TF_`` recording in ``source_dir`` and return outputs written."""
    exported: list[Path] = []
    trials = [recording for recording in list_recordings(source_dir) if recording.path.stem.startswith("TF_")]
    if not trials:
        raise RuntimeError(f"No TF_ recordings found in {source_dir}")

    for index, recording in enumerate(trials, start=1):
        output_path = output_dir / f"{recording.path.stem}.mp4"
        if output_path.exists() and not overwrite:
            print(f"[{index}/{len(trials)}] Skipping {output_path.name}; it already exists")
            continue
        start, end = _playback_bounds(recording)
        print(f"[{index}/{len(trials)}] Exporting {recording.name} ({end - start} frames)")
        export_recording(
            recording,
            output_path,
            correction,
            window_width=window_width,
            window_level=window_level,
            ffmpeg=ffmpeg,
        )
        exported.append(output_path)
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Export corrected TF fluoroscopy trials as H.264 MP4 files")
    parser.add_argument("--source-dir", type=Path, default=LIVE_DIR, help="Directory containing recorded .raw files")
    parser.add_argument("--output-dir", type=Path, default=EXPORT_DIR, help="Destination directory for MP4 files")
    parser.add_argument("--dark-field", type=Path, default=DARK_FIELD_FILE, help="Dark-field calibration .npz file")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing MP4 files")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable to run")
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
    )
    print(f"Exported {len(exported)} video(s) to {arguments.output_dir}")


if __name__ == "__main__":
    main()
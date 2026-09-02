"""Export corrected fluoroscopy recordings as shareable video files."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
import os
import platform
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

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
COMPARISON_TILE_SIZE = 320
MAX_HARDWARE_BITRATE = 1_000_000_000
_RECORDING_STEM = re.compile(r"^.+_([^_]+)_(?:pre|post)_\d+$")
_COMPARISON_TRIAL = re.compile(r"^(?P<variant>\d[A-Z])T(?P<trial>[123])$")
_COMPARISON_GROUPS = (
    ("TF_comparison_0C_3P_6P.mp4", ("0C", "3P", "6P")),
    ("TF_comparison_0C_2H_5H.mp4", ("0C", "2H", "5H")),
    ("TF_comparison_0C_1Y_4T.mp4", ("0C", "1Y", "4T")),
)


@dataclass(frozen=True)
class VideoEncoder:
    name: str
    codec: str
    hardware: bool
    frame_filter: str
    pixel_format: str | None
    input_options: tuple[str, ...] = ()
    codec_options: tuple[str, ...] = ()


_SOFTWARE_ENCODER = VideoEncoder(
    name="software",
    codec="libx264",
    hardware=False,
    frame_filter="format=yuvj420p",
    pixel_format="yuvj420p",
    codec_options=("-preset", "medium", "-crf", "18"),
)
_HARDWARE_ENCODERS = {
    "videotoolbox": VideoEncoder(
        "videotoolbox",
        "h264_videotoolbox",
        True,
        "format=yuv420p",
        "yuv420p",
    ),
    "nvenc": VideoEncoder(
        "nvenc",
        "h264_nvenc",
        True,
        "format=nv12",
        "nv12",
        codec_options=("-preset", "p5", "-tune", "hq", "-rc", "vbr"),
    ),
    "qsv": VideoEncoder(
        "qsv",
        "h264_qsv",
        True,
        "format=nv12",
        "nv12",
        codec_options=("-preset", "medium"),
    ),
    "amf": VideoEncoder(
        "amf",
        "h264_amf",
        True,
        "format=nv12",
        "nv12",
        codec_options=("-quality", "quality", "-rc", "vbr_peak"),
    ),
    "mediafoundation": VideoEncoder(
        "mediafoundation",
        "h264_mf",
        True,
        "format=nv12",
        "nv12",
        codec_options=("-hw_encoding", "1"),
    ),
    "vaapi": VideoEncoder(
        "vaapi",
        "h264_vaapi",
        True,
        "format=nv12,hwupload",
        None,
        codec_options=("-rc_mode", "VBR"),
    ),
    "v4l2m2m": VideoEncoder(
        "v4l2m2m",
        "h264_v4l2m2m",
        True,
        "format=yuv420p",
        "yuv420p",
    ),
}
ENCODER_CHOICES = ("auto", "software", *_HARDWARE_ENCODERS)


def _encoder_order() -> tuple[str, ...]:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        return ("videotoolbox",)
    if system == "Windows":
        if machine in {"arm64", "aarch64"}:
            return ("mediafoundation", "nvenc", "qsv", "amf")
        return ("nvenc", "qsv", "amf", "mediafoundation")
    if system == "Linux":
        if machine in {"arm64", "aarch64", "armv7l"}:
            return ("v4l2m2m", "nvenc", "vaapi", "qsv")
        return ("nvenc", "qsv", "vaapi", "v4l2m2m")
    return ()


def _configured_encoder(name: str) -> VideoEncoder:
    encoder = _HARDWARE_ENCODERS[name]
    if name != "vaapi":
        return encoder
    device = os.environ.get("FLUOROSUITE_VAAPI_DEVICE")
    if device is None:
        render_devices = sorted(Path("/dev/dri").glob("renderD*"))
        device = str(render_devices[0]) if render_devices else "/dev/dri/renderD128"
    return replace(encoder, input_options=("-vaapi_device", device))


def _hardware_bitrate(width: int, height: int, fps: float) -> int:
    reference_pixels_per_second = 1024 * 1024 * 30
    scaled = round(100_000_000 * width * height * fps / reference_pixels_per_second)
    return min(MAX_HARDWARE_BITRATE, max(20_000_000, scaled))


def _video_encoder_options(
    encoder: VideoEncoder,
    width: int,
    height: int,
    fps: float,
) -> list[str]:
    options = ["-c:v", encoder.codec, *encoder.codec_options]
    if encoder.hardware:
        bitrate = _hardware_bitrate(width, height, fps)
        options.extend(
            (
                "-b:v",
                str(bitrate),
                "-maxrate",
                str(round(bitrate * 1.2)),
                "-bufsize",
                str(bitrate * 2),
            )
        )
    if encoder.pixel_format is not None:
        options.extend(("-pix_fmt", encoder.pixel_format))
    options.extend(
        (
            "-color_range",
            "pc",
            "-colorspace",
            "bt709",
            "-color_trc",
            "iec61966-2-1",
            "-color_primaries",
            "bt709",
        )
    )
    return options


def _ffmpeg_encoder_names(executable: str) -> set[str]:
    result = subprocess.run(
        [executable, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {
        parts[1]
        for line in result.stdout.splitlines()
        if len(parts := line.split()) >= 2 and len(parts[0]) == 6 and parts[0].startswith("V")
    }


def _probe_video_encoder(executable: str, encoder: VideoEncoder) -> bool:
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        *encoder.input_options,
        "-f",
        "lavfi",
        "-i",
        f"color=black:s={COLUMNS}x{ROWS}:r=30",
        "-frames:v",
        "2",
        "-an",
        "-vf",
        encoder.frame_filter,
        *_video_encoder_options(encoder, COLUMNS, ROWS, 30.0),
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode == 0


def select_video_encoder(executable: str, requested: str = "auto") -> VideoEncoder:
    """Select a usable native H.264 encoder, falling back to libx264 in auto mode."""
    if requested == "software":
        return _SOFTWARE_ENCODER
    if requested not in ENCODER_CHOICES:
        raise ValueError(f"Unknown video encoder: {requested}")

    available = _ffmpeg_encoder_names(executable)
    candidates = _encoder_order() if requested == "auto" else (requested,)
    for name in candidates:
        encoder = _configured_encoder(name)
        if encoder.codec in available and _probe_video_encoder(executable, encoder):
            return encoder

    if requested != "auto":
        raise RuntimeError(f"Requested FFmpeg encoder is unavailable: {requested}")
    return _SOFTWARE_ENCODER


def _trial_designator(path: Path) -> str:
    match = _RECORDING_STEM.fullmatch(Path(path).stem)
    if match is None:
        raise ValueError(f"Cannot determine trial designator from {Path(path).name}")
    return match.group(1)


def _ordered_comparison_videos(paths: list[Path]) -> list[tuple[str, Path]]:
    columns: dict[str, dict[int, tuple[str, Path]]] = {}
    for path in paths:
        designator = _trial_designator(path)
        match = _COMPARISON_TRIAL.fullmatch(designator)
        if match is None:
            raise ValueError(f"Invalid comparison trial designator: {designator}")
        variant = match.group("variant")
        trial = int(match.group("trial"))
        trials = columns.setdefault(variant, {})
        if trial in trials:
            raise ValueError(f"Duplicate comparison trial: {designator}")
        trials[trial] = (designator, Path(path))

    for variant, trials in columns.items():
        if set(trials) != {1, 2, 3}:
            raise ValueError(f"Comparison column {variant} must contain trials T1, T2, and T3")

    return [
        columns[variant][trial]
        for variant in sorted(columns, key=lambda item: int(item[0]))
        for trial in (1, 2, 3)
    ]


def _write_comparison_labels(
    videos: list[tuple[str, Path]],
    output_path: Path,
    tile_size: int,
) -> None:
    application = QGuiApplication.instance()
    if application is None:
        application = QGuiApplication([])
    column_count = len(videos) // 3
    labels = QImage(column_count * tile_size, 3 * tile_size, QImage.Format.Format_ARGB32)
    labels.fill(Qt.GlobalColor.transparent)
    painter = QPainter(labels)
    font = QFont()
    font.setPixelSize(max(18, tile_size // 13))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255))
    metrics = painter.fontMetrics()
    for index, (designator, _path) in enumerate(videos):
        column, row = divmod(index, 3)
        label_width = metrics.horizontalAdvance(designator) + 20
        label_height = metrics.height() + 10
        label_rect = QRectF(
            column * tile_size + 10,
            row * tile_size + 10,
            label_width,
            label_height,
        )
        painter.fillRect(label_rect, QColor(0, 0, 0, 170))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, designator)
    painter.end()
    if not labels.save(str(output_path)):
        raise RuntimeError(f"Could not create comparison labels at {output_path}")


def export_comparison_video(
    video_paths: list[Path],
    output_path: Path,
    *,
    overwrite: bool = False,
    ffmpeg: str = "ffmpeg",
    tile_size: int = COMPARISON_TILE_SIZE,
    encoder: str | VideoEncoder = "software",
) -> Path:
    """Tile trial MP4s by device variant and overlay each trial designator."""
    videos = _ordered_comparison_videos(video_paths)
    if not videos:
        raise ValueError("at least one comparison video is required")
    if tile_size < 1:
        raise ValueError("tile_size must be at least 1")
    missing = [path.name for _designator, path in videos if not path.is_file()]
    if missing:
        raise RuntimeError(f"Comparison inputs do not exist: {', '.join(missing)}")

    executable = shutil.which(ffmpeg)
    if executable is None:
        raise RuntimeError(f"FFmpeg executable not found: {ffmpeg}")
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        print(f"Skipping {output_path.name}; it already exists")
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected_encoder = (
        encoder if isinstance(encoder, VideoEncoder) else select_video_encoder(executable, encoder)
    )
    column_count = len(videos) // 3
    output_width = column_count * tile_size
    output_height = 3 * tile_size
    if selected_encoder.name == "videotoolbox" and output_width > 4096:
        selected_encoder = _SOFTWARE_ENCODER

    with tempfile.TemporaryDirectory() as temporary_directory:
        labels_path = Path(temporary_directory) / "comparison-labels.png"
        _write_comparison_labels(videos, labels_path, tile_size)
        inputs = [argument for _designator, path in videos for argument in ("-i", str(path))]
        scaled = [
            f"[{index}:v]scale={tile_size}:{tile_size}:flags=lanczos,setsar=1[tile{index}]"
            for index in range(len(videos))
        ]
        layout = "|".join(
            f"{column * tile_size}_{row * tile_size}"
            for column in range(column_count)
            for row in range(3)
        )
        tiles = "".join(f"[tile{index}]" for index in range(len(videos)))
        filter_graph = ";".join(
            [
                *scaled,
                f"{tiles}xstack=inputs={len(videos)}:layout={layout}:shortest=1[grid]",
                (
                    f"[grid][{len(videos)}:v]overlay=0:0:shortest=1,"
                    f"{selected_encoder.frame_filter}[out]"
                ),
            ]
        )
        command = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *selected_encoder.input_options,
            *inputs,
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(labels_path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[out]",
            "-an",
            *_video_encoder_options(selected_encoder, output_width, output_height, 30.0),
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            output_path.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg failed while exporting comparison video: {result.stderr.strip()}")
    return output_path


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
    encoder: str | VideoEncoder = "software",
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
    selected_encoder = None
    if not raw:
        selected_encoder = (
            encoder if isinstance(encoder, VideoEncoder) else select_video_encoder(executable, encoder)
        )
    input_options = selected_encoder.input_options if selected_encoder is not None else ()
    encoder_options = ["-c:v", "rawvideo", "-pix_fmt", "gray"] if raw else [
        "-vf",
        selected_encoder.frame_filter,
        *_video_encoder_options(selected_encoder, COLUMNS, ROWS, recording.fps),
    ]
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *input_options,
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
    encoder: str | VideoEncoder = "software",
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
                encoder=encoder,
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
    parser.add_argument(
        "--comparison-tile-size",
        type=int,
        default=COMPARISON_TILE_SIZE,
        help=f"Square tile resolution in comparison videos (default: {COMPARISON_TILE_SIZE})",
    )
    parser.add_argument(
        "--encoder",
        choices=ENCODER_CHOICES,
        default="auto",
        help="H.264 encoder backend (default: auto-detect GPU acceleration)",
    )
    parser.add_argument("--workers", type=int, help="Number of recordings to export concurrently (default: up to 4)")
    arguments = parser.parse_args()

    correction = DarkFieldCorrection.load(arguments.dark_field)
    if correction is None:
        parser.error(f"Could not load dark-field calibration from {arguments.dark_field}")

    executable = shutil.which(arguments.ffmpeg)
    if executable is None:
        parser.error(f"FFmpeg executable not found: {arguments.ffmpeg}")
    try:
        selected_encoder = _SOFTWARE_ENCODER if arguments.raw else select_video_encoder(
            executable,
            arguments.encoder,
        )
    except RuntimeError as error:
        parser.error(str(error))
    print(f"Video encoder: {'rawvideo' if arguments.raw else selected_encoder.codec}")

    exported = export_live_trials(
        arguments.source_dir,
        arguments.output_dir,
        correction,
        overwrite=arguments.overwrite,
        ffmpeg=arguments.ffmpeg,
        workers=arguments.workers,
        raw=arguments.raw,
        encoder=selected_encoder,
    )
    print(f"Exported {len(exported)} video(s) to {arguments.output_dir}")
    if not arguments.raw:
        comparison_inputs = [
            arguments.output_dir / f"{recording.path.stem}.mp4"
            for recording in list_recordings(arguments.source_dir)
            if recording.path.stem.startswith("TF_")
        ]
        comparison_path = export_comparison_video(
            comparison_inputs,
            arguments.output_dir / "TF_comparison.mp4",
            overwrite=arguments.overwrite,
            ffmpeg=arguments.ffmpeg,
            tile_size=arguments.comparison_tile_size,
            encoder=selected_encoder,
        )
        print(f"Comparison video: {comparison_path}")
        for filename, variants in _COMPARISON_GROUPS:
            group_inputs = [
                path
                for path in comparison_inputs
                if _trial_designator(path)[:2] in variants
            ]
            comparison_path = export_comparison_video(
                group_inputs,
                arguments.output_dir / filename,
                overwrite=arguments.overwrite,
                ffmpeg=arguments.ffmpeg,
                tile_size=arguments.comparison_tile_size,
                encoder=selected_encoder,
            )
            print(f"Comparison video: {comparison_path}")


if __name__ == "__main__":
    main()
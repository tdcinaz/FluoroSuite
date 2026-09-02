from __future__ import annotations

import csv
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from fluorosuite.export import (
    VideoEncoder,
    _ordered_comparison_videos,
    _playback_bounds,
    export_aligned_analysis_csv,
    export_comparison_video,
    export_live_trials,
    export_recording,
    render_fluoroscopy_view,
    select_video_encoder,
)
from fluorosuite.recordings import RecordingInfo
from fluorosuite.visualization import Visualization


class ExportRenderingTests(unittest.TestCase):
    def test_auto_encoder_uses_platform_hardware_after_successful_probe(self) -> None:
        with (
            patch("fluorosuite.export.platform.system", return_value="Darwin"),
            patch("fluorosuite.export.platform.machine", return_value="arm64"),
            patch(
                "fluorosuite.export._ffmpeg_encoder_names",
                return_value={"libx264", "h264_videotoolbox"},
            ),
            patch("fluorosuite.export._probe_video_encoder", return_value=True) as probe,
        ):
            encoder = select_video_encoder("/usr/bin/ffmpeg")

        self.assertEqual(encoder.codec, "h264_videotoolbox")
        probe.assert_called_once_with("/usr/bin/ffmpeg", encoder)

    def test_auto_encoder_falls_back_when_hardware_probe_fails(self) -> None:
        with (
            patch("fluorosuite.export.platform.system", return_value="Linux"),
            patch("fluorosuite.export.platform.machine", return_value="x86_64"),
            patch(
                "fluorosuite.export._ffmpeg_encoder_names",
                return_value={"libx264", "h264_nvenc"},
            ),
            patch("fluorosuite.export._probe_video_encoder", return_value=False),
        ):
            encoder = select_video_encoder("/usr/bin/ffmpeg")

        self.assertEqual(encoder.codec, "libx264")

    def test_orders_comparison_videos_by_variant_then_trial(self) -> None:
        paths = [
            Path("TF_3PT3_post_0.mp4"),
            Path("TF_0CT2_pre_0.mp4"),
            Path("TF_3PT1_post_0.mp4"),
            Path("TF_0CT1_pre_0.mp4"),
            Path("TF_3PT2_post_0.mp4"),
            Path("TF_0CT3_pre_0.mp4"),
        ]

        ordered = _ordered_comparison_videos(paths)

        self.assertEqual(
            [designator for designator, _path in ordered],
            ["0CT1", "0CT2", "0CT3", "3PT1", "3PT2", "3PT3"],
        )

    def test_export_comparison_video_builds_three_row_grid(self) -> None:
        names = [
            "TF_1YT3_post_0.mp4",
            "TF_0CT1_pre_0.mp4",
            "TF_1YT1_post_0.mp4",
            "TF_0CT3_pre_0.mp4",
            "TF_1YT2_post_0.mp4",
            "TF_0CT2_pre_0.mp4",
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            paths = [directory / name for name in names]
            for path in paths:
                path.touch()
            output_path = directory / "TF_comparison.mp4"
            result = MagicMock(returncode=0, stderr="")
            with (
                patch("fluorosuite.export.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch("fluorosuite.export._write_comparison_labels") as write_labels,
                patch("fluorosuite.export.subprocess.run", return_value=result) as run,
            ):
                exported = export_comparison_video(paths, output_path, tile_size=100)

        self.assertEqual(exported, output_path)
        ordered = write_labels.call_args.args[0]
        self.assertEqual(
            [designator for designator, _path in ordered],
            ["0CT1", "0CT2", "0CT3", "1YT1", "1YT2", "1YT3"],
        )
        command = run.call_args.args[0]
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("xstack=inputs=6:layout=0_0|0_100|0_200|100_0|100_100|100_200", filter_graph)
        self.assertIn("[grid][6:v]overlay=0:0:shortest=1", filter_graph)

    def test_exports_aligned_analysis_with_shared_time_and_trial_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            paths = [directory / "TF_1YT2_post_0.raw", directory / "TF_2HT1_post_0.raw"]
            values = [
                [(str(10 + index), str(20 + index)) for index in range(12)],
                [(str(30 + index), str(40 + index)) for index in range(12)],
            ]
            for path, injection_frame, recording_values in zip(paths, (10, 11), values, strict=True):
                path.with_suffix(".json").write_text(
                    json.dumps(
                        {
                            "analysis": {
                                "timing_alignment": {
                                    "injection_frame": injection_frame,
                                    "start_frame": injection_frame - 10,
                                    "fps": 2.0,
                                }
                            }
                        }
                    )
                )
                with path.with_suffix(".csv").open("w", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(("time_s", "roi_mean", "inlet_mean"))
                    for index, (roi_mean, inlet_mean) in enumerate(recording_values):
                        writer.writerow((index / 2.0, roi_mean, inlet_mean))

            output_path = directory / "aligned.csv"
            export_aligned_analysis_csv(paths, output_path)

            with output_path.open(newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(
                rows[0],
                [
                    "time_s",
                    "1YT2_roi_mean",
                    "1YT2_inlet_mean",
                    "2HT1_roi_mean",
                    "2HT1_inlet_mean",
                ],
            )
            self.assertEqual(rows[1], ["0.0", "10", "20", "31", "41"])
            self.assertEqual(rows[11], ["5.0", "20", "30", "41", "51"])
            self.assertEqual(rows[12], ["5.5", "21", "31", "", ""])

    def test_rejects_incomplete_inlet_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "TF_1YT2_post_0.raw"
            path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "analysis": {
                            "timing_alignment": {
                                "injection_frame": 10,
                                "start_frame": 0,
                                "fps": 2.0,
                            }
                        }
                    }
                )
            )
            path.with_suffix(".csv").write_text(
                "time_s,roi_mean,inlet_mean\n0.0,10.0,\n"
            )

            with self.assertRaisesRegex(ValueError, "incomplete saved ROI analysis data"):
                export_aligned_analysis_csv([path], Path(temporary_directory) / "aligned.csv")

    def test_render_fluoroscopy_view_clips_frame_to_circular_viewport(self) -> None:
        frame = np.full((5, 5), 16383, dtype=np.uint16)
        lut = Visualization().build_lut()

        rendered = render_fluoroscopy_view(frame, lut, rotation=0)

        self.assertEqual(rendered.dtype, np.uint8)
        self.assertEqual(rendered[0, 0], 0)
        self.assertEqual(rendered[0, 4], 0)
        self.assertEqual(rendered[4, 0], 0)
        self.assertEqual(rendered[4, 4], 0)
        self.assertEqual(rendered[2, 2], 255)

    def test_render_fluoroscopy_view_rotates_image_content(self) -> None:
        frame = np.zeros((9, 9), dtype=np.uint16)
        frame[4, 6] = 16383
        lut = Visualization().build_lut()

        rendered = render_fluoroscopy_view(frame, lut, rotation=180)

        self.assertEqual(rendered[4, 2], 255)
        self.assertEqual(rendered[4, 6], 0)

    def test_playback_bounds_uses_saved_timing_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "trial.raw"
            path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "analysis": {
                            "timing_alignment": {
                                "injection_frame": 50,
                                "start_frame": 0,
                                "fps": 10.0,
                            }
                        }
                    }
                )
            )
            recording = RecordingInfo(path=path, frames=300, started=None, ended=None)

            self.assertEqual(_playback_bounds(recording), (40, 201))

    def test_export_recording_uses_h264_by_default(self) -> None:
        recording = RecordingInfo(Path("trial.raw"), 1, None, None)
        frame = np.zeros((2, 2), dtype=np.uint16)
        rendered = np.array([[0, 255], [64, 128]], dtype=np.uint8)
        correction = MagicMock()
        correction.apply.return_value = frame
        process = MagicMock()
        process.stderr.read.return_value = b""
        process.wait.return_value = 0

        with (
            patch("fluorosuite.export.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("fluorosuite.export.np.memmap", return_value=np.array([frame])),
            patch("fluorosuite.export.load_saved_rotation", return_value=0),
            patch("fluorosuite.export._playback_bounds", return_value=(0, 1)),
            patch("fluorosuite.export.render_fluoroscopy_view", return_value=rendered),
            patch("fluorosuite.export.subprocess.Popen", return_value=process) as popen,
        ):
            export_recording(recording, Path("trial.mp4"), correction)

        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "yuvj420p")
        self.assertIn("-crf", command)
        process.stdin.write.assert_called_once_with(rendered.tobytes())

    def test_export_recording_uses_high_bitrate_hardware_encoder(self) -> None:
        recording = RecordingInfo(Path("trial.raw"), 1, None, None, frame_rate=30.0)
        frame = np.zeros((2, 2), dtype=np.uint16)
        correction = MagicMock()
        correction.apply.return_value = frame
        process = MagicMock()
        process.stderr.read.return_value = b""
        process.wait.return_value = 0
        encoder = VideoEncoder(
            "videotoolbox",
            "h264_videotoolbox",
            True,
            "format=yuv420p",
            "yuv420p",
        )

        with (
            patch("fluorosuite.export.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("fluorosuite.export.np.memmap", return_value=np.array([frame])),
            patch("fluorosuite.export.load_saved_rotation", return_value=0),
            patch("fluorosuite.export._playback_bounds", return_value=(0, 1)),
            patch("fluorosuite.export.render_fluoroscopy_view", return_value=np.zeros((2, 2), dtype=np.uint8)),
            patch("fluorosuite.export.subprocess.Popen", return_value=process) as popen,
        ):
            export_recording(recording, Path("trial.mp4"), correction, encoder=encoder)

        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-c:v") + 1], "h264_videotoolbox")
        self.assertGreaterEqual(int(command[command.index("-b:v") + 1]), 100_000_000)
        self.assertNotIn("-crf", command)

    def test_export_recording_raw_uses_uncompressed_8_bit_grayscale(self) -> None:
        recording = RecordingInfo(Path("trial.raw"), 1, None, None)
        frame = np.zeros((2, 2), dtype=np.uint16)
        correction = MagicMock()
        correction.apply.return_value = frame
        process = MagicMock()
        process.stderr.read.return_value = b""
        process.wait.return_value = 0

        with (
            patch("fluorosuite.export.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("fluorosuite.export.np.memmap", return_value=np.array([frame])),
            patch("fluorosuite.export.load_saved_rotation", return_value=0),
            patch("fluorosuite.export._playback_bounds", return_value=(0, 1)),
            patch("fluorosuite.export.render_fluoroscopy_view", return_value=np.zeros((2, 2), dtype=np.uint8)),
            patch("fluorosuite.export.subprocess.Popen", return_value=process) as popen,
        ):
            export_recording(recording, Path("trial.avi"), correction, raw=True)

        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-c:v") + 1], "rawvideo")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "gray")
        self.assertNotIn("libx264", command)
        self.assertNotIn("-crf", command)

    def test_export_live_trials_exports_recordings_concurrently(self) -> None:
        recordings = [
            RecordingInfo(Path(f"TF_trial-{index}.raw"), 10, None, None)
            for index in range(2)
        ]
        started = threading.Barrier(2)
        completed: list[Path] = []

        def export_stub(recording, output_path, correction, **kwargs) -> None:  # noqa: ANN001, ARG001
            started.wait(timeout=1)
            completed.append(output_path)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with (
                patch("fluorosuite.export.list_recordings", return_value=recordings),
                patch("fluorosuite.export.export_recording", side_effect=export_stub),
            ):
                exported = export_live_trials(
                    Path("unused"),
                    output_dir,
                    correction=None,  # type: ignore[arg-type]
                    workers=2,
                )

        expected = [output_dir / "TF_trial-0.mp4", output_dir / "TF_trial-1.mp4"]
        self.assertEqual(exported, expected)
        self.assertCountEqual(completed, expected)

    def test_export_live_trials_raw_uses_avi_suffix(self) -> None:
        recording = RecordingInfo(Path("TF_trial.raw"), 10, None, None)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with (
                patch("fluorosuite.export.list_recordings", return_value=[recording]),
                patch("fluorosuite.export.export_recording") as export_mock,
            ):
                exported = export_live_trials(
                    Path("unused"),
                    output_dir,
                    correction=None,  # type: ignore[arg-type]
                    raw=True,
                )

        expected = output_dir / "TF_trial.avi"
        self.assertEqual(exported, [expected])
        self.assertEqual(export_mock.call_args.args[1], expected)
        self.assertTrue(export_mock.call_args.kwargs["raw"])


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from fluorosuite.export import _playback_bounds, export_live_trials, render_fluoroscopy_view
from fluorosuite.recordings import RecordingInfo
from fluorosuite.visualization import Visualization


class ExportRenderingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
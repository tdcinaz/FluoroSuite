from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fluorosuite.pipeline import Circle, RectangleROI, TimingAlignmentResult
from fluorosuite.recordings import (
    load_saved_rectangular_roi,
    load_saved_roi,
    save_rectangular_roi,
    load_saved_timing_alignment,
    save_roi,
    save_timing_alignment,
)


class RecordingAnalysisMetadataTests(unittest.TestCase):
    def test_saves_analysis_data_without_replacing_recording_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            sidecar = raw_path.with_suffix(".json")
            sidecar.write_text(json.dumps({"frames": 120, "started": 10.0}))

            save_roi(raw_path, Circle(100, 200, 30))
            save_timing_alignment(raw_path, TimingAlignmentResult(90, 40, 10.0))

            metadata = json.loads(sidecar.read_text())
            self.assertEqual(metadata["frames"], 120)
            self.assertEqual(load_saved_roi(raw_path), Circle(100, 200, 30))
            self.assertEqual(
                load_saved_timing_alignment(raw_path),
                TimingAlignmentResult(90, 40, 10.0),
            )

    def test_saving_roi_overwrites_previous_position_and_radius(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"

            save_roi(raw_path, Circle(10, 20, 30))
            save_roi(raw_path, Circle(40, 50, 60))

            self.assertEqual(load_saved_roi(raw_path), Circle(40, 50, 60))

    def test_saves_and_loads_rectangular_roi_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            rectangle = RectangleROI(100, 200, width=120, height=40, angle=27.5)

            save_rectangular_roi(raw_path, rectangle)

            self.assertEqual(load_saved_rectangular_roi(raw_path), rectangle)

    def test_loads_rectangular_roi_without_legacy_angle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            raw_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "analysis": {
                            "rectangular_roi": {
                                "center_x": 100,
                                "center_y": 200,
                                "width": 120,
                                "height": 40,
                            }
                        }
                    }
                )
            )

            self.assertEqual(
                load_saved_rectangular_roi(raw_path),
                RectangleROI(100, 200, width=120, height=40),
            )


if __name__ == "__main__":
    unittest.main()
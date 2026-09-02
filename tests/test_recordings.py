from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from fluorosuite.pipeline import (
    Circle,
    InletROIResult,
    Rectangle,
    ROIParameters,
    ROIResidenceResult,
    TimingAlignmentResult,
    analyze_roi_means,
)
from fluorosuite.recordings import (
    RecordingInfo,
    load_saved_analysis_result,
    load_saved_inlet_analysis_result,
    load_saved_inlet_roi,
    load_saved_roi,
    load_saved_rotation,
    load_saved_timing_alignment,
    save_analysis_result,
    save_analysis_results,
    save_inlet_roi,
    save_roi,
    save_rotation,
    save_timing_alignment,
)


class RecordingInfoTests(unittest.TestCase):
    def test_fps_uses_inter_frame_interval_count(self) -> None:
        info = RecordingInfo(Path("recording.raw"), frames=301, started=10.0, ended=20.0)

        self.assertEqual(info.fps, 30.0)

    def test_declared_frame_rate_overrides_wall_clock_estimate(self) -> None:
        info = RecordingInfo(
            Path("recording.raw"),
            frames=301,
            started=10.0,
            ended=19.9,
            frame_rate=30.0,
        )

        self.assertEqual(info.fps, 30.0)


class RecordingAnalysisMetadataTests(unittest.TestCase):
    def test_round_trips_analysis_csv_and_records_data_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            sidecar = raw_path.with_suffix(".json")
            sidecar.write_text(json.dumps({"frames": 3, "started": 10.0}))
            result = ROIResidenceResult(
                time=np.array([0.0, 0.1, 0.2], dtype=np.float32),
                roi_mean=np.array([100.0, 90.0, 95.0], dtype=np.float32),
                contrast=np.array([0.0, 10.0, 5.0], dtype=np.float32),
                baseline=100.0,
                baseline_start_time=0.0,
                peak_contrast=10.0,
                time_to_peak=0.1,
                onset_time=0.1,
                clearance_time=0.2,
                residence_time=0.1,
            )

            save_analysis_result(raw_path, result)

            metadata = json.loads(sidecar.read_text())
            self.assertEqual(metadata["frames"], 3)
            self.assertEqual(metadata["data_file"], "recording.csv")
            self.assertTrue(raw_path.with_suffix(".csv").exists())
            with raw_path.with_suffix(".csv").open(newline="") as handle:
                self.assertEqual(
                    csv.reader(handle).__next__(),
                    ["time_s", "roi_mean", "inlet_roi_mean"],
                )

            parameters = ROIParameters(baseline_frames=2, clearance_fraction=0.5)
            loaded = load_saved_analysis_result(raw_path, parameters)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            expected = analyze_roi_means(result.roi_mean, parameters, fps=10.0, time=result.time)
            np.testing.assert_array_equal(loaded.time, result.time)
            np.testing.assert_array_equal(loaded.roi_mean, result.roi_mean)
            np.testing.assert_array_equal(loaded.contrast, expected.contrast)
            self.assertEqual(loaded.baseline, expected.baseline)
            self.assertEqual(loaded.residence_time, expected.residence_time)

            replacement = replace(
                result,
                time=result.time[:1],
                roi_mean=result.roi_mean[:1],
                contrast=result.contrast[:1],
                baseline=50.0,
            )
            save_analysis_result(raw_path, replacement)
            loaded = load_saved_analysis_result(raw_path, parameters)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.time.size, 1)
            self.assertEqual(loaded.baseline, float(replacement.roi_mean[0]))
            self.assertNotEqual(loaded.baseline, replacement.baseline)

    def test_round_trips_inlet_means_with_aneurysm_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            time = np.array([0.0, 0.1, 0.2], dtype=np.float32)
            result = analyze_roi_means(
                np.array([100.0, 90.0, 95.0], dtype=np.float32),
                ROIParameters(),
                fps=10.0,
                time=time,
            )
            inlet_result = InletROIResult(
                time=time,
                roi_mean=np.array([200.0, 180.0, 190.0], dtype=np.float32),
            )

            save_analysis_results(raw_path, result, inlet_result)

            loaded = load_saved_inlet_analysis_result(raw_path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            np.testing.assert_array_equal(loaded.time, inlet_result.time)
            np.testing.assert_array_equal(loaded.roi_mean, inlet_result.roi_mean)

    def test_round_trips_inlet_only_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            inlet_result = InletROIResult(
                time=np.array([0.0, 0.1], dtype=np.float32),
                roi_mean=np.array([200.0, 180.0], dtype=np.float32),
            )

            save_analysis_results(raw_path, None, inlet_result)

            self.assertIsNone(load_saved_analysis_result(raw_path, ROIParameters()))
            loaded = load_saved_inlet_analysis_result(raw_path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            np.testing.assert_array_equal(loaded.roi_mean, inlet_result.roi_mean)
            with raw_path.with_suffix(".csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["roi_mean"] for row in rows], ["", ""])

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

    def test_timing_alignment_uses_declared_recording_frame_rate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            raw_path.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "fps": 30.0,
                        "analysis": {
                            "timing_alignment": {
                                "injection_frame": 90,
                                "start_frame": 40,
                                "fps": 30.034,
                            }
                        },
                    }
                )
            )

            self.assertEqual(
                load_saved_timing_alignment(raw_path),
                TimingAlignmentResult(90, 40, 30.0),
            )

    def test_saving_roi_overwrites_previous_position_and_radius(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"

            save_roi(raw_path, Circle(10, 20, 30))
            save_roi(raw_path, Circle(40, 50, 60))

            self.assertEqual(load_saved_roi(raw_path), Circle(40, 50, 60))

    def test_inlet_roi_round_trips_position_dimensions_and_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            sidecar = raw_path.with_suffix(".json")
            sidecar.write_text(json.dumps({"frames": 120, "started": 10.0}))
            inlet_roi = Rectangle(300, 400, 40, 120, 86)

            save_inlet_roi(raw_path, inlet_roi)

            metadata = json.loads(sidecar.read_text())
            self.assertEqual(metadata["frames"], 120)
            self.assertEqual(
                metadata["analysis"]["inlet_roi"],
                {
                    "center_x": 300,
                    "center_y": 400,
                    "width": 40,
                    "height": 120,
                    "rotation": 86,
                },
            )
            self.assertEqual(load_saved_inlet_roi(raw_path), inlet_roi)

    def test_rotation_round_trips_and_preserves_recording_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            raw_path = Path(temporary_directory) / "recording.raw"
            sidecar = raw_path.with_suffix(".json")
            sidecar.write_text(json.dumps({"frames": 120, "started": 10.0}))

            self.assertEqual(load_saved_rotation(raw_path), 0)
            save_rotation(raw_path, 45)
            save_rotation(raw_path, -30)

            metadata = json.loads(sidecar.read_text())
            self.assertEqual(metadata["frames"], 120)
            self.assertEqual(metadata["analysis"]["rotation"], -30)
            self.assertEqual(load_saved_rotation(raw_path), -30)


if __name__ == "__main__":
    unittest.main()
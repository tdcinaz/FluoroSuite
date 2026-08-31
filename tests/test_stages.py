from __future__ import annotations

import unittest

import numpy as np

from fluorosuite.pipeline.models import ROIParameters
from fluorosuite.pipeline.stages import _analyze_roi_means, detect_injection_timing


class ROIResidenceTests(unittest.TestCase):
    def test_places_baseline_after_startup_ramp_stabilizes(self) -> None:
        ramp = np.linspace(100.0, 120.0, 90, dtype=np.float32)
        plateau = np.full(120, 120.0, dtype=np.float32)
        contrast = np.linspace(120.0, 80.0, 90, dtype=np.float32)
        roi_mean = np.concatenate((ramp, plateau, contrast))

        result = _analyze_roi_means(roi_mean, ROIParameters(baseline_frames=8), fps=30.0)

        self.assertGreaterEqual(result.baseline_start_time, 3.0)
        self.assertLess(result.baseline_start_time, 7.0)
        self.assertAlmostEqual(result.baseline, 120.0, places=3)


class TimingAlignmentTests(unittest.TestCase):
    def test_leaves_flat_recording_untrimmed(self) -> None:
        frames = (np.full((8, 8), 1000, dtype=np.uint16) for _ in range(100))

        result = detect_injection_timing(frames, fps=10.0)

        self.assertEqual(result.injection_frame, 0)
        self.assertEqual(result.start_frame, 0)

    def test_aligns_detected_intensity_drop_to_five_seconds(self) -> None:
        fps = 10.0
        values = np.concatenate((np.full(83, 1000.0), np.linspace(980.0, 700.0, 12), np.full(120, 700.0)))
        frames = (np.full((8, 8), value, dtype=np.float32) for value in values)

        result = detect_injection_timing(frames, fps)

        self.assertGreaterEqual(result.injection_frame, 83)
        self.assertLessEqual(result.injection_frame, 94)
        self.assertAlmostEqual((result.injection_frame - result.start_frame) / fps, 5.0)


if __name__ == "__main__":
    unittest.main()
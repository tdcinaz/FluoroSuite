from __future__ import annotations

import unittest

import numpy as np

from fluorosuite.pipeline.models import Circle, ROIParameters, Rectangle, TimingAlignmentResult
from fluorosuite.pipeline.stages import analyze_roi_means, analyze_rois_stream, detect_injection_timing


class RectangleROITests(unittest.TestCase):
    def test_unrotates_vertical_display_roi_for_raw_frame_mask(self) -> None:
        rectangle = Rectangle(center_x=100, center_y=100, width=40, height=120, rotation=90)

        mask = rectangle.mask((201, 201))

        self.assertEqual(np.count_nonzero(mask), 40 * 120)
        self.assertTrue(mask[100, 159])
        self.assertTrue(mask[120, 100])
        self.assertFalse(mask[121, 100])
        self.assertFalse(mask[100, 160])

    def test_samples_aneurysm_and_inlet_means_in_one_frame_pass(self) -> None:
        frames = np.zeros((3, 201, 201), dtype=np.float32)
        circle = Circle(center_x=25, center_y=25, radius=5)
        inlet_roi = Rectangle(center_x=100, center_y=100, width=40, height=120, rotation=90)
        circle_mask = circle.mask((201, 201))
        inlet_mask = inlet_roi.mask((201, 201))
        frames[:, circle_mask] = np.array([100.0, 90.0, 80.0])[:, None]
        frames[:, inlet_mask] = np.array([200.0, 180.0, 160.0])[:, None]

        result, inlet_result = analyze_rois_stream(
            iter(frames),
            circle,
            inlet_roi,
            ROIParameters(),
            fps=10.0,
        )

        self.assertIsNotNone(result)
        self.assertIsNotNone(inlet_result)
        assert result is not None and inlet_result is not None
        np.testing.assert_array_equal(result.roi_mean, [100.0, 90.0, 80.0])
        np.testing.assert_array_equal(inlet_result.roi_mean, [200.0, 180.0, 160.0])


class ROIResidenceTests(unittest.TestCase):
    def test_returns_raw_contrast_without_smoothing(self) -> None:
        roi_mean = np.array([100.0, 100.0, 90.0, 100.0, 80.0], dtype=np.float32)

        result = analyze_roi_means(roi_mean, ROIParameters(baseline_frames=2), fps=30.0)

        np.testing.assert_array_equal(result.contrast, result.baseline - roi_mean)

    def test_places_baseline_after_startup_ramp_stabilizes(self) -> None:
        ramp = np.linspace(100.0, 120.0, 90, dtype=np.float32)
        plateau = np.full(120, 120.0, dtype=np.float32)
        contrast = np.linspace(120.0, 80.0, 90, dtype=np.float32)
        roi_mean = np.concatenate((ramp, plateau, contrast))

        result = analyze_roi_means(roi_mean, ROIParameters(baseline_frames=8), fps=30.0)

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


class PlaybackBoundsTests(unittest.TestCase):
    def test_trim_bounds_include_one_second_before_and_fifteen_after_injection(self) -> None:
        timing = TimingAlignmentResult(injection_frame=100, start_frame=50, fps=10.0)

        self.assertEqual(timing.playback_bounds(400), (90, 251))

    def test_trim_bounds_leave_recording_untrimmed_without_detected_injection(self) -> None:
        timing = TimingAlignmentResult(injection_frame=0, start_frame=0, fps=10.0)

        self.assertEqual(timing.playback_bounds(400), (0, 400))


if __name__ == "__main__":
    unittest.main()
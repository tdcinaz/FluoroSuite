from __future__ import annotations

import unittest

import numpy as np

from fluorosuite.pipeline.models import ROIParameters
from fluorosuite.pipeline.stages import _analyze_roi_means


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


if __name__ == "__main__":
    unittest.main()
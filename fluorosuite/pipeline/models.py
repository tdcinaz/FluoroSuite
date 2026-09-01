"""Immutable pipeline data models."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Circle:
    center_x: int
    center_y: int
    radius: int

    def mask(self, shape: tuple[int, int]) -> np.ndarray:
        """Return a boolean circular mask for a frame of the given (rows, cols)."""
        rows, cols = shape
        yy, xx = np.ogrid[:rows, :cols]
        distance_sq = (xx - self.center_x) ** 2 + (yy - self.center_y) ** 2
        return distance_sq <= self.radius**2


@dataclass(frozen=True, slots=True)
class ROIParameters:
    roi_radius: int = 70
    baseline_frames: int = 8
    clearance_fraction: float = 0.10


@dataclass(frozen=True, slots=True)
class StageInstance:
    key: str
    enabled: bool = True
    roi: Circle | None = None
    parameters: ROIParameters = ROIParameters()


@dataclass(frozen=True, slots=True)
class ROIResidenceResult:
    time: np.ndarray
    roi_mean: np.ndarray
    contrast: np.ndarray
    baseline: float
    baseline_start_time: float
    peak_contrast: float
    time_to_peak: float
    onset_time: float
    clearance_time: float
    residence_time: float


@dataclass(frozen=True, slots=True)
class TimingAlignmentResult:
    injection_frame: int
    start_frame: int
    fps: float

    def playback_bounds(self, frame_count: int) -> tuple[int, int]:
        """Return the injection-centered playback interval as [start, end)."""
        frame_count = max(0, int(frame_count))
        if self.injection_frame <= 0:
            return 0, frame_count
        lead_frames = round(self.fps)
        follow_frames = round(15.0 * self.fps)
        start = max(0, self.injection_frame - lead_frames)
        end = min(frame_count, self.injection_frame + follow_frames + 1)
        return start, max(start, end)

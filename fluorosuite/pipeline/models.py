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
class Rectangle:
    center_x: int
    center_y: int
    width: int
    height: int
    rotation: int = 0

    def mask(self, shape: tuple[int, int]) -> np.ndarray:
        """Return the raw-frame mask for a rectangle placed on the rotated view."""
        rows, cols = shape
        yy, xx = np.ogrid[:rows, :cols]
        radians = np.deg2rad(self.rotation)
        cosine = np.cos(radians)
        sine = np.sin(radians)
        delta_x = xx - self.center_x
        delta_y = yy - self.center_y
        display_x = cosine * delta_x - sine * delta_y
        display_y = sine * delta_x + cosine * delta_y
        return (
            (display_x >= -self.width / 2)
            & (display_x < self.width / 2)
            & (display_y >= -self.height / 2)
            & (display_y < self.height / 2)
        )

    def corners(self) -> tuple[tuple[float, float], ...]:
        """Return raw-frame corners for this display-oriented rectangle."""
        radians = np.deg2rad(self.rotation)
        cosine = np.cos(radians)
        sine = np.sin(radians)
        return tuple(
            (
                self.center_x + cosine * display_x + sine * display_y,
                self.center_y - sine * display_x + cosine * display_y,
            )
            for display_x, display_y in (
                (-self.width / 2, -self.height / 2),
                (self.width / 2, -self.height / 2),
                (self.width / 2, self.height / 2),
                (-self.width / 2, self.height / 2),
            )
        )


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
class InletROIResult:
    time: np.ndarray
    roi_mean: np.ndarray


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

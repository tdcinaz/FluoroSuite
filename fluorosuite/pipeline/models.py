"""Immutable pipeline data models."""

from __future__ import annotations

from dataclasses import dataclass
import math

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
class RectangleROI:
    center_x: int
    center_y: int
    width: int = 120
    height: int = 40
    angle: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", max(1, int(self.width)))
        object.__setattr__(self, "height", max(1, int(self.height)))

    @classmethod
    def from_center_corner(cls, center_x: int, center_y: int, corner_x: int, corner_y: int) -> "RectangleROI":
        return cls(
            center_x=int(center_x),
            center_y=int(center_y),
            width=max(1, abs(int(corner_x) - int(center_x)) * 2),
            height=max(1, abs(int(corner_y) - int(center_y)) * 2),
        )

    def mask(self, shape: tuple[int, int]) -> np.ndarray:
        """Return a boolean rectangular mask for a frame of the given (rows, cols)."""
        rows, cols = shape
        yy, xx = np.ogrid[:rows, :cols]
        radians = math.radians(self.angle)
        cosine, sine = math.cos(radians), math.sin(radians)
        delta_x = xx - self.center_x
        delta_y = yy - self.center_y
        local_x = cosine * delta_x + sine * delta_y
        local_y = -sine * delta_x + cosine * delta_y
        return (
            (local_x >= -(self.width // 2))
            & (local_x < self.width - self.width // 2)
            & (local_y >= -(self.height // 2))
            & (local_y < self.height - self.height // 2)
        )


@dataclass(frozen=True, slots=True)
class ROIParameters:
    roi_radius: int = 70
    baseline_frames: int = 8
    clearance_fraction: float = 0.10
    smoothing_window: int = 5


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

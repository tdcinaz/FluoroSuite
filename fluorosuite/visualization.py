"""Window/level visualization for 16-bit fluoroscopy frames.

The rendering model matches the legacy Fluoro viewers: a lookup table maps each
14-bit pixel to an 8-bit grayscale value using window level/width, brightness,
contrast, and optional grayscale inversion.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from PySide6.QtGui import QImage

from .config import COLUMNS, LUT_SIZE, MAX_VALUE, ROWS


@dataclass(frozen=True, slots=True)
class Visualization:
    level: int = MAX_VALUE // 2
    width: int = MAX_VALUE
    brightness: int = 0
    contrast: float = 1.0
    invert: bool = False
    dark_field: bool = True

    @classmethod
    def default(cls) -> "Visualization":
        return cls()

    def with_window(self, level: int, width: int) -> "Visualization":
        return replace(self, level=int(level), width=max(1, int(width)))

    def build_lut(self) -> np.ndarray:
        """Return a uint8 lookup table indexed by 14-bit pixel value."""
        width = max(1, self.width)
        low = self.level - width / 2.0
        scale = 255.0 / width
        pixels = np.arange(LUT_SIZE, dtype=np.float32)
        values = (pixels - low) * scale
        np.clip(values, 0.0, 255.0, out=values)
        values = (values - 128.0) * self.contrast + 128.0 + self.brightness
        np.clip(values, 0.0, 255.0, out=values)
        lut = values.astype(np.uint8)
        if self.invert:
            lut = 255 - lut
        return lut


def auto_window(frame: np.ndarray, low_pct: float = 1.0, high_pct: float = 99.5) -> tuple[int, int]:
    """Return a (level, width) window from robust intensity percentiles."""
    sample = frame[::8, ::8]
    low, high = np.percentile(sample, (low_pct, high_pct))
    low = int(low)
    high = int(max(high, low + 1))
    return (low + high) // 2, high - low


def render_gray(frame: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Apply a lookup table to a 16-bit frame, returning a contiguous uint8 image."""
    return np.ascontiguousarray(lut[frame & MAX_VALUE])


def to_qimage(frame: np.ndarray, lut: np.ndarray) -> QImage:
    gray = render_gray(frame, lut)
    height, width = gray.shape
    image = QImage(gray.data, width, height, width, QImage.Format.Format_Grayscale8)
    return image.copy()


class DarkFieldCorrection:
    """Applies a measured per-pixel dark-offset correction to raw frames."""

    def __init__(self, path) -> None:
        with np.load(path, allow_pickle=False) as calibration:
            if "dark" not in calibration or "reference" not in calibration:
                raise ValueError("dark-field calibration must contain dark and reference arrays")
            self.dark = np.asarray(calibration["dark"], dtype=np.float32)
            self.reference = float(np.asarray(calibration["reference"]).item())
        if self.dark.shape != (ROWS, COLUMNS):
            raise ValueError(f"dark-field calibration has unexpected dimensions {self.dark.shape}")
        if not np.isfinite(self.reference) or not np.all(np.isfinite(self.dark)):
            raise ValueError("dark-field calibration contains non-finite values")

    def apply(self, frame: np.ndarray) -> np.ndarray:
        corrected = np.clip(frame.astype(np.float32) - self.dark + self.reference, 0, MAX_VALUE)
        return np.rint(corrected).astype(np.uint16)

    @classmethod
    def load(cls, path) -> "DarkFieldCorrection | None":
        try:
            return cls(path)
        except (OSError, ValueError):
            return None

"""Pipeline stage registry and the aneurysm ROI residence analysis.

Iodinated contrast attenuates X-rays, so it appears dark in fluoroscopy. The
residence signal is therefore measured as ``baseline - current`` mean brightness
inside the manually placed ROI circle.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable

import numpy as np

from .models import Circle, ROIParameters, ROIResidenceResult


@dataclass(frozen=True, slots=True)
class StageDefinition:
    key: str
    display_name: str
    description: str


STAGE_REGISTRY: dict[str, StageDefinition] = {
    "roi_analysis": StageDefinition(
        key="roi_analysis",
        display_name="Aneurysm ROI analysis",
        description="Place a circular ROI on the aneurysm and measure contrast residence over time.",
    ),
}


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or values.size < window:
        return values
    kernel = np.ones(window, dtype=np.float32) / float(window)
    return np.convolve(values, kernel, mode="same")


def analyze_roi_residence(
    frames: np.ndarray,
    circle: Circle,
    parameters: ROIParameters,
    fps: float,
) -> ROIResidenceResult:
    """Measure contrast residence inside ``circle`` across a stack of raw frames.

    ``frames`` is a (count, rows, cols) uint16 array.
    """
    count = int(frames.shape[0])
    mask = circle.mask((int(frames.shape[1]), int(frames.shape[2])))
    pixel_count = max(1, int(np.count_nonzero(mask)))

    roi_mean = np.empty(count, dtype=np.float32)
    for index in range(count):
        roi_mean[index] = float(frames[index][mask].sum()) / pixel_count

    return _analyze_roi_means(roi_mean, parameters, fps)


def analyze_roi_residence_stream(
    frames: Iterable[np.ndarray],
    circle: Circle,
    parameters: ROIParameters,
    fps: float,
    total_frames: int = 0,
    progress: Callable[[float], None] | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> ROIResidenceResult:
    """Measure ROI residence from frames yielded without retaining the stack."""
    mask: np.ndarray | None = None
    pixel_count = 0
    roi_means: list[float] = []
    next_update = 0.01
    for frame in frames:
        if should_continue is not None and not should_continue():
            break
        if mask is None:
            mask = circle.mask((int(frame.shape[0]), int(frame.shape[1])))
            pixel_count = max(1, int(np.count_nonzero(mask)))
        roi_means.append(float(frame[mask].sum()) / pixel_count)
        if progress is not None and total_frames > 0:
            fraction = len(roi_means) / total_frames
            if fraction >= next_update or fraction >= 1.0:
                progress(min(1.0, fraction))
                next_update += 0.01
    return _analyze_roi_means(np.asarray(roi_means, dtype=np.float32), parameters, fps)


def _analyze_roi_means(
    roi_mean: np.ndarray,
    parameters: ROIParameters,
    fps: float,
) -> ROIResidenceResult:
    count = int(roi_mean.size)

    fps = max(1.0, float(fps))
    time = np.arange(count, dtype=np.float32) / fps

    baseline_frames = max(1, min(parameters.baseline_frames, count))
    baseline = float(np.mean(roi_mean[:baseline_frames]))

    contrast = baseline - roi_mean
    contrast = _smooth(contrast, parameters.smoothing_window)

    peak_index = int(np.argmax(contrast)) if count else 0
    peak_contrast = float(contrast[peak_index]) if count else 0.0
    time_to_peak = float(time[peak_index]) if count else 0.0

    threshold = parameters.clearance_fraction * peak_contrast
    above = contrast >= threshold if peak_contrast > 0 else np.zeros(count, dtype=bool)
    if np.any(above):
        indices = np.flatnonzero(above)
        onset_time = float(time[indices[0]])
        clearance_time = float(time[indices[-1]])
    else:
        onset_time = 0.0
        clearance_time = 0.0
    residence_time = max(0.0, clearance_time - onset_time)

    return ROIResidenceResult(
        time=time,
        roi_mean=roi_mean,
        contrast=contrast,
        baseline=baseline,
        peak_contrast=peak_contrast,
        time_to_peak=time_to_peak,
        onset_time=onset_time,
        clearance_time=clearance_time,
        residence_time=residence_time,
    )

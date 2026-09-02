"""Pipeline stage registry and ROI analysis implementations.

Iodinated contrast attenuates X-rays, so it appears dark in fluoroscopy. The
residence signal is therefore measured as ``baseline - current`` mean brightness
inside the manually placed ROI circle.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable

import numpy as np

from .models import Circle, InletROIResult, Rectangle, ROIParameters, ROIResidenceResult, TimingAlignmentResult


@dataclass(frozen=True, slots=True)
class StageDefinition:
    key: str
    display_name: str
    description: str


STAGE_REGISTRY: dict[str, StageDefinition] = {
    "timing_alignment": StageDefinition(
        key="timing_alignment",
        display_name="Injection timing alignment",
        description="Detect contrast injection and align it to 5 seconds without modifying the recording.",
    ),
    "roi_analysis": StageDefinition(
        key="roi_analysis",
        display_name="Aneurysm ROI analysis",
        description="Place a circular ROI on the aneurysm and measure contrast residence over time.",
    ),
    "inlet_roi_analysis": StageDefinition(
        key="inlet_roi_analysis",
        display_name="Inlet ROI analysis",
        description="Place a fixed 40 x 120 px ROI on the vertically oriented inlet vessel.",
    ),
}


def detect_injection_timing(
    frames: Iterable[np.ndarray],
    fps: float,
    should_continue: Callable[[], bool] | None = None,
) -> TimingAlignmentResult:
    """Detect contrast arrival from raw whole-frame intensity and compute a virtual trim."""
    fps = max(1.0, float(fps))
    frame_means: list[float] = []
    for frame in frames:
        if should_continue is not None and not should_continue():
            break
        frame_means.append(float(np.mean(frame[::8, ::8], dtype=np.float64)))

    values = np.asarray(frame_means, dtype=np.float64)
    if values.size < 2:
        return TimingAlignmentResult(0, 0, fps)

    window = max(1, round(fps))
    if values.size < 2 * window + 1:
        return TimingAlignmentResult(0, 0, fps)
    moving_average = np.convolve(values, np.ones(window, dtype=np.float64) / window, mode="valid")
    sustained_change = moving_average[window:] - moving_average[:-window]
    search_start = min(sustained_change.size, round(2.0 * fps))
    search_stop = min(sustained_change.size, round(20.0 * fps))
    search_values = sustained_change[search_start:search_stop]
    if search_values.size == 0:
        search_values = sustained_change
        search_start = 0

    center = float(np.median(search_values))
    noise = float(np.median(np.abs(search_values - center))) * 1.4826
    strongest_index = int(np.argmin(search_values))
    strongest_drop = max(0.0, center - float(search_values[strongest_index]))
    if strongest_drop <= 6.0 * noise or strongest_drop <= np.finfo(np.float64).eps:
        injection_frame = 0
    else:
        injection_frame = search_start + strongest_index + window

    aligned_lead_frames = round(5.0 * fps)
    start_frame = max(0, injection_frame - aligned_lead_frames)
    return TimingAlignmentResult(injection_frame, start_frame, fps)


def _stable_baseline_start(
    roi_mean: np.ndarray,
    baseline_frames: int,
    fps: float,
) -> int:
    count = int(roi_mean.size)
    if count <= baseline_frames:
        return 0

    stability_frames = min(count, max(baseline_frames, round(2.0 * fps)))
    search_frames = min(count, max(stability_frames, round(10.0 * fps)))
    search_values = roi_mean[:search_frames].astype(np.float64, copy=False)
    differences = np.diff(search_values)
    if differences.size:
        difference_median = float(np.median(differences))
        noise = float(np.median(np.abs(differences - difference_median))) * 1.4826 / np.sqrt(2.0)
    else:
        noise = 0.0

    block_count = min(4, stability_frames)
    block_frames = max(1, stability_frames // block_count)
    tolerance = max(0.25, min(1.0, 4.0 * noise / np.sqrt(block_frames)))
    best_start = 0
    best_range = float("inf")
    final_start = search_frames - stability_frames
    for start in range(final_start + 1):
        window = search_values[start : start + stability_frames]
        block_means = np.asarray([float(np.mean(block)) for block in np.array_split(window, block_count)])
        block_range = float(np.ptp(block_means))
        if block_range < best_range:
            best_start = start
            best_range = block_range
        if block_range <= tolerance:
            best_start = start
            break

    return min(count - baseline_frames, best_start + stability_frames - baseline_frames)


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

    return analyze_roi_means(roi_mean, parameters, fps)


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
    result, _inlet_result = analyze_rois_stream(
        frames,
        circle,
        None,
        parameters,
        fps,
        total_frames,
        progress,
        should_continue,
    )
    if result is None:  # pragma: no cover - circle is always provided
        return analyze_roi_means(np.empty(0, dtype=np.float32), parameters, fps)
    return result


def analyze_rois_stream(
    frames: Iterable[np.ndarray],
    circle: Circle | None,
    inlet_roi: Rectangle | None,
    parameters: ROIParameters,
    fps: float,
    total_frames: int = 0,
    progress: Callable[[float], None] | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> tuple[ROIResidenceResult | None, InletROIResult | None]:
    """Measure enabled aneurysm and inlet ROIs in one pass over raw frames."""
    roi_mask: np.ndarray | None = None
    inlet_mask: np.ndarray | None = None
    roi_pixel_count = 0
    inlet_pixel_count = 0
    roi_means: list[float] = []
    inlet_means: list[float] = []
    next_update = 0.01
    for frame in frames:
        if should_continue is not None and not should_continue():
            break
        shape = (int(frame.shape[0]), int(frame.shape[1]))
        if circle is not None:
            if roi_mask is None:
                roi_mask = circle.mask(shape)
                roi_pixel_count = max(1, int(np.count_nonzero(roi_mask)))
            roi_means.append(float(frame[roi_mask].sum()) / roi_pixel_count)
        if inlet_roi is not None:
            if inlet_mask is None:
                inlet_mask = inlet_roi.mask(shape)
                inlet_pixel_count = max(1, int(np.count_nonzero(inlet_mask)))
            inlet_means.append(float(frame[inlet_mask].sum()) / inlet_pixel_count)
        if progress is not None and total_frames > 0:
            processed_frames = len(roi_means) if circle is not None else len(inlet_means)
            fraction = processed_frames / total_frames
            if fraction >= next_update or fraction >= 1.0:
                progress(min(1.0, fraction))
                next_update += 0.01
    roi_values = np.asarray(roi_means, dtype=np.float32)
    inlet_values = np.asarray(inlet_means, dtype=np.float32)
    roi_result = analyze_roi_means(roi_values, parameters, fps) if circle is not None else None
    inlet_result = None
    if inlet_roi is not None:
        time = np.arange(inlet_values.size, dtype=np.float32) / max(1.0, float(fps))
        inlet_result = InletROIResult(time=time, roi_mean=inlet_values)
    return roi_result, inlet_result


def analyze_roi_means(
    roi_mean: np.ndarray,
    parameters: ROIParameters,
    fps: float,
    *,
    time: np.ndarray | None = None,
) -> ROIResidenceResult:
    """Calculate contrast and summary metrics from per-frame ROI means."""
    count = int(roi_mean.size)

    fps = max(1.0, float(fps))
    if time is None:
        time = np.arange(count, dtype=np.float32) / fps
    else:
        time = np.asarray(time, dtype=np.float32)
        if time.size != count:
            raise ValueError("time and ROI mean arrays must have equal lengths")

    baseline_frames = max(1, min(parameters.baseline_frames, count))
    baseline_start = _stable_baseline_start(roi_mean, baseline_frames, fps)
    baseline = float(np.mean(roi_mean[baseline_start : baseline_start + baseline_frames]))

    contrast = baseline - roi_mean

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
        baseline_start_time=float(time[baseline_start]) if count else 0.0,
        peak_contrast=peak_contrast,
        time_to_peak=time_to_peak,
        onset_time=onset_time,
        clearance_time=clearance_time,
        residence_time=residence_time,
    )

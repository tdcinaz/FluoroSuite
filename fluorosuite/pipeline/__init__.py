"""Frontend-neutral pipeline contracts for the fluoroscopy suite."""

from .models import (
    Circle,
    InletROIResult,
    Rectangle,
    ROIParameters,
    ROIResidenceResult,
    StageInstance,
    TimingAlignmentResult,
)
from .stages import (
    STAGE_REGISTRY,
    StageDefinition,
    analyze_roi_means,
    analyze_roi_residence,
    analyze_roi_residence_stream,
    analyze_rois_stream,
    detect_injection_timing,
)

__all__ = [
    "Circle",
    "InletROIResult",
    "Rectangle",
    "ROIParameters",
    "ROIResidenceResult",
    "StageInstance",
    "TimingAlignmentResult",
    "STAGE_REGISTRY",
    "StageDefinition",
    "analyze_roi_means",
    "analyze_roi_residence",
    "analyze_roi_residence_stream",
    "analyze_rois_stream",
    "detect_injection_timing",
]

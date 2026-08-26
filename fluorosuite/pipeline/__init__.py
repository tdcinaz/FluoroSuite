"""Frontend-neutral pipeline contracts for the fluoroscopy suite.

The design mirrors the legacy Contrast pipeline package but is streamlined to a
single pipeline. For now the only registered stage places and analyzes an
aneurysm ROI circle, but the registry keeps the app open to further stages.
"""

from .models import Circle, ROIParameters, ROIResidenceResult, StageInstance
from .stages import STAGE_REGISTRY, StageDefinition, analyze_roi_residence

__all__ = [
    "Circle",
    "ROIParameters",
    "ROIResidenceResult",
    "StageInstance",
    "STAGE_REGISTRY",
    "StageDefinition",
    "analyze_roi_residence",
]

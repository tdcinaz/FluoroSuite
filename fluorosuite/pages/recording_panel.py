"""A self-contained recorded-video panel: selection, display, and ROI placement.

Playback is driven externally so multiple panels can share one transport.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..pipeline import Circle
from ..recordings import RecordingInfo, RecordingReader, list_recordings
from ..visualization import DarkFieldCorrection, Visualization
from ..widgets import FrameView
from ..widgets.recording_selector import RecordingSelector


class RecordingPanel(QWidget):
    """One recorded run with its own selector and ROI overlay, driven externally."""

    roiPlaced = Signal(object)  # emits a Circle
    recordingOpened = Signal(object)  # emits a RecordingInfo
    recordingCleared = Signal()

    def __init__(
        self,
        live_dir: Path,
        correction: DarkFieldCorrection | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._live_dir = live_dir
        self._correction = correction
        self._visualization = Visualization.default()
        self._reader: RecordingReader | None = None
        self._info: RecordingInfo | None = None
        self._current_frame: np.ndarray | None = None
        self._roi: Circle | None = None

        self.frame_view = FrameView("Select a recording")
        self.recording_selector = RecordingSelector()
        self.frame_view.set_overlay_widget(self.recording_selector)

        self.recording_selector.currentIndexChanged.connect(self._open_selected)
        self.recording_selector.popupAboutToShow.connect(self.refresh_recordings)
        self.frame_view.roiPlaced.connect(self._on_roi_placed)

        self._build_layout()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.frame_view, 1)

    # -- public API -----------------------------------------------------------
    @property
    def info(self) -> RecordingInfo | None:
        return self._info

    @property
    def current_frame(self) -> np.ndarray | None:
        return self._current_frame

    @property
    def roi(self) -> Circle | None:
        return self._roi

    @property
    def frame_count(self) -> int:
        return self._reader.frame_count if self._reader is not None else 0

    def has_recording(self) -> bool:
        return self._reader is not None

    def set_roi_color(self, color: str) -> None:
        self.frame_view.set_roi_color(color)

    def set_roi_editable(self, editable: bool) -> None:
        self.frame_view.set_roi_editable(editable)

    def set_roi_radius(self, radius: int) -> None:
        self.frame_view.set_roi_radius(radius)
        if self._roi is not None:
            self._roi = Circle(self._roi.center_x, self._roi.center_y, radius)

    def clear_roi(self) -> None:
        self._roi = None
        self.frame_view.set_roi(None)

    def set_visualization(self, visualization: Visualization) -> None:
        self._visualization = visualization
        self.frame_view.set_visualization(visualization)
        self._render_current()

    def set_correction(self, correction: DarkFieldCorrection | None) -> None:
        self._correction = correction
        self._render_current()

    def frames_array(self) -> np.ndarray | None:
        if self._reader is None:
            return None
        frames = self._reader.read_all()
        if self._visualization.dark_field and self._correction is not None:
            return np.stack([self._correction.apply(frame) for frame in frames])
        return frames

    def show_frame(self, index: int) -> None:
        """Display the given frame, clamped to this recording's final frame."""
        if self._reader is None:
            return
        index = max(0, min(index, self._reader.frame_count - 1))
        frame = self._reader.read_frame(index)
        if frame is None:
            return
        self._current_frame = frame
        self._render_current()

    # -- selection ------------------------------------------------------------
    def refresh_recordings(self) -> None:
        selected = self.recording_selector.currentData()
        previous_path = self._info.path if self._info is not None else None
        recordings = list_recordings(self._live_dir)
        self.recording_selector.blockSignals(True)
        self.recording_selector.clear()
        for info in recordings:
            self.recording_selector.addItem(info.name, info)
        self.frame_view.update_overlay_geometry()
        if not recordings:
            self.recording_selector.blockSignals(False)
            self._reader = None
            self._info = None
            self._current_frame = None
            self.frame_view.set_frame(None)
            self.recordingCleared.emit()
            return
        index = 0
        if selected is not None:
            for candidate in range(self.recording_selector.count()):
                if self.recording_selector.itemData(candidate).path == selected.path:
                    index = candidate
                    break
        self.recording_selector.setCurrentIndex(index)
        self.recording_selector.blockSignals(False)
        info = self.recording_selector.currentData()
        if info is not None and (self._reader is None or info.path != previous_path):
            self._open_selected()

    def _open_selected(self) -> None:
        info = self.recording_selector.currentData()
        if info is None:
            return
        self._info = info
        self._reader = RecordingReader(info.path)
        self.show_frame(0)
        self.recordingOpened.emit(info)

    # -- rendering ------------------------------------------------------------
    def _render_current(self) -> None:
        if self._current_frame is None:
            return
        frame = self._current_frame
        if self._visualization.dark_field and self._correction is not None:
            frame = self._correction.apply(frame)
        self.frame_view.set_frame(frame)

    def _on_roi_placed(self, roi: Circle) -> None:
        self._roi = roi
        self.roiPlaced.emit(roi)

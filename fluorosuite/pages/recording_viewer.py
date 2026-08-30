"""Shared recording selection and playback behavior for playback/analysis pages."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from ..recordings import RecordingInfo, RecordingReader, list_recordings
from ..visualization import DarkFieldCorrection, Visualization
from ..widgets import FrameView, PlaybackBar, VisualizationPanel
from ..widgets.recording_selector import RecordingSelector


class RecordingViewer(QWidget):
    """Base widget that loads a recorded run and drives frame-by-frame playback."""

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

        self.frame_view = FrameView("Select a recording")
        self.recording_selector = RecordingSelector()
        self.frame_view.set_overlay_widget(self.recording_selector)
        self.playback_bar = PlaybackBar()
        self.visualization_panel = VisualizationPanel()
        self.visualization_panel.set_dark_field_available(correction is not None)

        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance)

        self.recording_selector.currentIndexChanged.connect(self._open_selected)
        self.recording_selector.popupAboutToShow.connect(self.refresh_recordings)
        self.playback_bar.playToggled.connect(self._on_play_toggled)
        self.playback_bar.indexChanged.connect(self._on_scrub)
        self.playback_bar.speed.currentIndexChanged.connect(self._update_timer_interval)
        self.visualization_panel.changed.connect(self._on_visualization_changed)

    def refresh_recordings(self) -> None:
        selected = self.recording_selector.currentData()
        recordings = list_recordings(self._live_dir)
        self.recording_selector.blockSignals(True)
        self.recording_selector.clear()
        for info in recordings:
            self.recording_selector.addItem(info.name, info)
        self.recording_selector.blockSignals(False)
        self.frame_view.update_overlay_geometry()
        if not recordings:
            self._reader = None
            self._info = None
            self.frame_view.set_frame(None)
            self.playback_bar.set_frame_count(0)
            self._on_recording_cleared()
            return
        index = 0
        if selected is not None:
            for candidate in range(self.recording_selector.count()):
                if self.recording_selector.itemData(candidate).path == selected.path:
                    index = candidate
                    break
        self.recording_selector.setCurrentIndex(index)
        self._open_selected()

    def _open_selected(self) -> None:
        info = self.recording_selector.currentData()
        if info is None:
            return
        self._pause()
        self._info = info
        self._reader = RecordingReader(info.path)
        self.playback_bar.set_frame_count(self._reader.frame_count)
        self._load_frame(0)
        self._on_recording_opened(info)

    # -- playback -------------------------------------------------------------
    def _load_frame(self, index: int) -> None:
        if self._reader is None:
            return
        frame = self._reader.read_frame(index)
        if frame is None:
            return
        self._current_frame = frame
        self.playback_bar.set_index(index)
        self._render_current()
        self._on_frame_shown(index, frame)

    def _render_current(self) -> None:
        if self._current_frame is None:
            return
        frame = self._current_frame
        if self._visualization.dark_field and self._correction is not None:
            frame = self._correction.apply(frame)
        self.frame_view.set_frame(frame)

    def set_correction(self, correction: DarkFieldCorrection | None) -> None:
        self._correction = correction
        self.visualization_panel.set_dark_field_available(correction is not None)
        self._render_current()

    def _on_play_toggled(self, playing: bool) -> None:
        if playing:
            self._update_timer_interval()
            self._play_timer.start()
        else:
            self._play_timer.stop()

    def _pause(self) -> None:
        self._play_timer.stop()
        self.playback_bar.set_playing(False)

    def _advance(self) -> None:
        if self._reader is None:
            return
        index = self.playback_bar.index()
        if index >= self._reader.frame_count - 1:
            if self.playback_bar.is_looping():
                self._load_frame(0)
            else:
                self._pause()
            return
        self._load_frame(index + 1)

    def _update_timer_interval(self) -> None:
        fps = self._info.fps if self._info else 15.0
        interval = 1000.0 / max(1.0, fps * self.playback_bar.speed_factor())
        self._play_timer.setInterval(int(interval))

    def _on_scrub(self, index: int) -> None:
        self._pause()
        self._load_frame(index)

    def _on_visualization_changed(self, visualization: Visualization) -> None:
        self._visualization = visualization
        self.frame_view.set_visualization(visualization)
        self._render_current()

    def frames_array(self) -> np.ndarray | None:
        if self._reader is None:
            return None
        frames = self._reader.read_all()
        if self._visualization.dark_field and self._correction is not None:
            return np.stack([self._correction.apply(frame) for frame in frames])
        return frames

    # -- hooks for subclasses -------------------------------------------------
    def _on_recording_opened(self, info: RecordingInfo) -> None:  # noqa: ARG002
        pass

    def _on_recording_cleared(self) -> None:
        pass

    def _on_frame_shown(self, index: int, frame: np.ndarray) -> None:  # noqa: ARG002
        pass

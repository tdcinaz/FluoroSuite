"""Playback page: review recorded runs with window/level and transport controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ..recordings import RecordingInfo
from ..visualization import DarkFieldCorrection
from ..widgets import ScrollableColumn
from .recording_viewer import RecordingViewer


class PlaybackPage(RecordingViewer):
    def __init__(
        self,
        live_dir: Path,
        correction: DarkFieldCorrection | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(live_dir, correction, parent)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(12)
        center.addWidget(self.frame_view, 1)
        center.addWidget(self.playback_bar)

        side = QVBoxLayout()
        side.setContentsMargins(16, 16, 16, 16)
        side.addWidget(self.visualization_panel)
        side.addStretch(1)
        side_card = QFrame()
        side_card.setObjectName("card")
        side_card.setLayout(side)
        side_column = ScrollableColumn(side_card)
        side_column.setFixedWidth(300)

        body = QHBoxLayout(self)
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(16)
        body.addLayout(center, 1)
        body.addWidget(side_column)

    def _on_recording_cleared(self) -> None:
        self.frame_view._placeholder = "No recordings found"
        self.frame_view.update()

    def _on_recording_opened(self, info: RecordingInfo) -> None:
        # Reasonable initial window from the first frame.
        if self._current_frame is not None:
            from ..visualization import auto_window

            level, width = auto_window(self._current_frame)
            self.visualization_panel.apply_window(level, width)

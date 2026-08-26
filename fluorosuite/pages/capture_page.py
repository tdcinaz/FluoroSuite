"""Live capture page: shows the reconstructed camera stream and records exposures."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..capture import LatestFrame, PreviewStore, Recorder
from ..config import COLUMNS, ROWS
from ..visualization import DarkFieldCorrection, Visualization
from ..widgets import FrameView, VisualizationPanel


class CapturePage(QWidget):
    def __init__(
        self,
        latest: LatestFrame,
        store: PreviewStore,
        recorder: Recorder,
        correction: DarkFieldCorrection | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._latest = latest
        self._store = store
        self._recorder = recorder
        self._correction = correction
        self._visualization = Visualization.default()
        self._last_seq = -1

        self.frame_view = FrameView("Waiting for camera stream")
        self.visualization_panel = VisualizationPanel()
        self.visualization_panel.set_dark_field_available(correction is not None)
        self.visualization_panel.changed.connect(self._on_visualization_changed)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(16)
        side.addWidget(self._wrap_card(self.visualization_panel))
        side.addWidget(self._build_recording_card())
        side.addStretch(1)
        side_widget = QWidget()
        side_widget.setFixedWidth(300)
        side_widget.setLayout(side)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        body.addWidget(self.frame_view, 1)
        body.addWidget(side_widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_status_bar())
        layout.addLayout(body, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._refresh)

    # -- construction ---------------------------------------------------------
    def _wrap_card(self, inner: QWidget) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.addWidget(inner)
        return card

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("card")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(24)

        self.state_label = QLabel("Connecting")
        self.state_label.setObjectName("statusValue")
        self.ingest_label = QLabel("Ingest: 0.0 fps")
        self.frames_label = QLabel("Frames: 0")
        self.dropped_label = QLabel("Dropped: 0")
        self.rec_badge = QLabel("")
        self.rec_badge.setObjectName("recBadge")
        for label in (self.ingest_label, self.frames_label, self.dropped_label):
            label.setObjectName("subtleLabel")

        layout.addWidget(QLabel("Live camera"))
        layout.addWidget(self.state_label)
        layout.addStretch(1)
        layout.addWidget(self.ingest_label)
        layout.addWidget(self.frames_label)
        layout.addWidget(self.dropped_label)
        layout.addWidget(self.rec_badge)
        return bar

    def _build_recording_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Recording")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.prefix_edit = QLineEdit("BDL")
        self.trial_edit = QLineEdit("A0")
        self.phase_toggle = QCheckBox("Post (unchecked: pre)")

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        prefix_label = QLabel("Prefix")
        prefix_label.setObjectName("subtleLabel")
        trial_label = QLabel("Trial")
        trial_label.setObjectName("subtleLabel")
        grid.addWidget(prefix_label, 0, 0)
        grid.addWidget(self.prefix_edit, 0, 1)
        grid.addWidget(trial_label, 1, 0)
        grid.addWidget(self.trial_edit, 1, 1)
        layout.addLayout(grid)
        layout.addWidget(self.phase_toggle)

        self.name_preview = QLabel()
        self.name_preview.setObjectName("statusValue")
        layout.addWidget(self.name_preview)

        self.record_button = QPushButton("Enable auto-recording")
        self.record_button.setObjectName("recordButton")
        self.record_button.setCheckable(True)
        layout.addWidget(self.record_button)

        note = QLabel("Research live preview. Not for diagnostic use.")
        note.setObjectName("subtleLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.prefix_edit.editingFinished.connect(self._update_naming)
        self.trial_edit.editingFinished.connect(self._update_naming)
        self.phase_toggle.toggled.connect(self._update_naming)
        self.record_button.toggled.connect(self._toggle_recording)
        self._update_naming()
        return card

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # -- handlers -------------------------------------------------------------
    def _on_visualization_changed(self, visualization: Visualization) -> None:
        self._visualization = visualization
        self.frame_view.set_visualization(visualization)
        self._last_seq = -1  # force re-render with the new dark-field choice

    def _update_naming(self) -> None:
        try:
            state = self._recorder.update_naming(
                self.prefix_edit.text().strip(),
                self.trial_edit.text().strip(),
                "post" if self.phase_toggle.isChecked() else "pre",
            )
        except ValueError:
            self.name_preview.setText("Invalid name")
            return
        self.name_preview.setText(str(state["preview"]))

    def _toggle_recording(self, enabled: bool) -> None:
        state = self._recorder.set_enabled(enabled)
        self.record_button.setText("Disable auto-recording" if enabled else "Enable auto-recording")
        self.name_preview.setText(str(state["preview"]))

    def _refresh(self) -> None:
        status = self._store.snapshot()
        self._update_badges(status)

        seq, pixels = self._latest.snapshot()
        if pixels is not None and seq != self._last_seq:
            self._last_seq = seq
            frame = np.frombuffer(pixels, dtype="<u2").reshape((ROWS, COLUMNS))
            if self._visualization.dark_field and self._correction is not None:
                frame = self._correction.apply(frame)
            self.frame_view.set_frame(frame)
        self.visualization_panel.set_suggested_window(status["suggested"])

    def _update_badges(self, status: dict) -> None:
        error = status["error"]
        if error:
            self.state_label.setText("Stream error")
        elif status["state"] == "live":
            self.state_label.setText("Exposure" if status["exposure"] else "Live")
        else:
            self.state_label.setText("Waiting for stream")
        self.ingest_label.setText(f"Ingest: {status['fps']:.1f} fps")
        self.frames_label.setText(f"Frames: {status['received']}")
        self.dropped_label.setText(f"Dropped: {status['dropped']}")

        rec_state = self._recorder.state()
        if rec_state["recording"]:
            self.rec_badge.setText(f"\u25cf REC {rec_state['seconds']:.0f}s / {rec_state['frames']}f")
        elif rec_state["auto_recording"]:
            self.rec_badge.setText("\u25cf AUTO REC")
        else:
            self.rec_badge.setText("")

"""Live capture page: shows the reconstructed camera stream and records exposures."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..capture import LatestFrame, PreviewStore, Recorder, is_exposure
from ..config import COLUMNS, DARK_FIELD_FILE, ROWS
from ..visualization import DarkFieldCorrection, Visualization
from ..widgets import FrameView, VisualizationPanel

CALIBRATION_FRAMES = 64


class CapturePage(QWidget):
    calibrated = Signal(object)  # emits a DarkFieldCorrection

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
        side.addWidget(self._build_calibration_card())
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

        self._calibrating = False
        self._calibration_frames: list[np.ndarray] = []
        self._calibration_last_seq = -1
        self._calibration_timer = QTimer(self)
        self._calibration_timer.setInterval(20)
        self._calibration_timer.timeout.connect(self._collect_calibration_frame)

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

    def _build_calibration_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Dark-field calibration")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Turn the X-ray source OFF, then capture dark frames to measure each "
            "pixel's offset."
        )
        hint.setObjectName("subtleLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.calibrate_button = QPushButton("Calibrate dark-field")
        self.calibrate_button.clicked.connect(self._start_calibration)
        layout.addWidget(self.calibrate_button)

        state = "Calibrated." if self._correction is not None else "Not calibrated."
        self.calibration_status = QLabel(state)
        self.calibration_status.setObjectName("subtleLabel")
        self.calibration_status.setWordWrap(True)
        layout.addWidget(self.calibration_status)
        return card

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

    # -- dark-field calibration ----------------------------------------------
    def _start_calibration(self) -> None:
        if self._calibrating:
            return
        status = self._store.snapshot()
        if status["state"] != "live" or status["error"]:
            QMessageBox.warning(
                self,
                "Dark-field calibration",
                "No live stream. Wait for the camera before calibrating.",
            )
            return
        if status["exposure"]:
            QMessageBox.warning(
                self,
                "Dark-field calibration",
                "Turn the X-ray source OFF. Dark-field must be captured with no exposure.",
            )
            return
        self._calibrating = True
        self._calibration_frames = []
        self._calibration_last_seq = -1
        self.calibrate_button.setEnabled(False)
        self.calibration_status.setText(f"Capturing dark frames\u2026 0/{CALIBRATION_FRAMES}")
        self._calibration_timer.start()

    def _collect_calibration_frame(self) -> None:
        if not self._calibrating:
            return
        seq, pixels = self._latest.snapshot()
        if pixels is None or seq == self._calibration_last_seq:
            return
        self._calibration_last_seq = seq
        if is_exposure(pixels):
            self._abort_calibration("Exposure detected. Keep the X-ray source OFF and retry.")
            return
        frame = np.frombuffer(pixels, dtype="<u2").reshape((ROWS, COLUMNS))
        self._calibration_frames.append(frame.astype(np.float32))
        captured = len(self._calibration_frames)
        self.calibration_status.setText(f"Capturing dark frames\u2026 {captured}/{CALIBRATION_FRAMES}")
        if captured >= CALIBRATION_FRAMES:
            self._finish_calibration()

    def _finish_calibration(self) -> None:
        self._calibration_timer.stop()
        stack = np.stack(self._calibration_frames)
        try:
            correction = DarkFieldCorrection.calibrate(stack, DARK_FIELD_FILE)
        except (OSError, ValueError) as error:
            self._abort_calibration(f"Calibration failed: {error}")
            return
        self._calibrating = False
        self._calibration_frames = []
        self._correction = correction
        self.visualization_panel.set_dark_field_available(True)
        self.calibrate_button.setEnabled(True)
        self.calibration_status.setText(f"Calibrated from {CALIBRATION_FRAMES} dark frames.")
        self._last_seq = -1
        self.calibrated.emit(correction)

    def _abort_calibration(self, message: str) -> None:
        self._calibration_timer.stop()
        self._calibrating = False
        self._calibration_frames = []
        self.calibrate_button.setEnabled(True)
        self.calibration_status.setText(message)

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

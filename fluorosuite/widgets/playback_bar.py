"""Transport controls for playback and analysis pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


class PlaybackBar(QWidget):
    playToggled = Signal(bool)
    indexChanged = Signal(int)  # emitted for user-driven scrub/step

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame_count = 0
        self._playing = False

        self.play_button = QPushButton()
        self.play_button.setObjectName("playbackPlayButton")
        self.play_button.setText("▶")
        self.play_button.setToolTip("Play/Pause")
        self.step_back = QPushButton()
        self.step_back.setObjectName("playbackSeekButton")
        self.step_back.setText("◀◀◀")
        self.step_back.setToolTip("Previous frame")
        self.step_forward = QPushButton()
        self.step_forward.setObjectName("playbackSeekButton")
        self.step_forward.setText("▶▶▶")
        self.step_forward.setToolTip("Next frame")

        self.scrub = QSlider(Qt.Orientation.Horizontal)
        self.scrub.setRange(0, 0)
        self.scrub.setMinimumWidth(180)

        self.position_label = QLabel("0 / 0")
        self.position_label.setObjectName("subtleLabel")

        self.speed = QComboBox()
        for text, value in (("0.25x", 0.25), ("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x", 4.0)):
            self.speed.addItem(text, value)
        self.speed.setCurrentIndex(2)

        self.loop_button = QPushButton()
        self.loop_button.setObjectName("playbackLoopButton")
        self.loop_button.setText("↻")
        self.loop_button.setToolTip("Loop playback")
        self.loop_button.setCheckable(True)
        self.loop_button.setFixedWidth(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.step_back)
        layout.addWidget(self.play_button)
        layout.addWidget(self.step_forward)
        layout.addWidget(self.scrub, 1)
        layout.addWidget(self.position_label)
        layout.addWidget(QLabel("Speed"))
        layout.addWidget(self.speed)
        layout.addWidget(self.loop_button)

        self.play_button.clicked.connect(self._toggle)
        self.step_back.clicked.connect(lambda: self._step(-1))
        self.step_forward.clicked.connect(lambda: self._step(1))
        self.scrub.valueChanged.connect(self._on_scrub)

    def set_frame_count(self, count: int) -> None:
        self._frame_count = count
        self.scrub.blockSignals(True)
        self.scrub.setRange(0, max(0, count - 1))
        self.scrub.setValue(0)
        self.scrub.blockSignals(False)
        self._update_position(0)

    def set_index(self, index: int) -> None:
        self.scrub.blockSignals(True)
        self.scrub.setValue(index)
        self.scrub.blockSignals(False)
        self._update_position(index)

    def index(self) -> int:
        return self.scrub.value()

    def speed_factor(self) -> float:
        return float(self.speed.currentData())

    def is_looping(self) -> bool:
        return self.loop_button.isChecked()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.play_button.setProperty("playing", playing)
        self.play_button.setText("||" if playing else "▶")
        self.play_button.style().unpolish(self.play_button)
        self.play_button.style().polish(self.play_button)
        self.play_button.update()

    def _toggle(self) -> None:
        self._playing = not self._playing
        self.set_playing(self._playing)
        self.playToggled.emit(self._playing)

    def _step(self, delta: int) -> None:
        if self._frame_count == 0:
            return
        target = max(0, min(self._frame_count - 1, self.scrub.value() + delta))
        self.set_index(target)
        self.indexChanged.emit(target)

    def _on_scrub(self, value: int) -> None:
        self._update_position(value)
        self.indexChanged.emit(value)

    def _update_position(self, index: int) -> None:
        total = self._frame_count
        self.position_label.setText(f"{index + 1 if total else 0} / {total}")

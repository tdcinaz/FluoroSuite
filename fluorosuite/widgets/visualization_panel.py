"""Window/level control panel that emits Visualization updates."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config import MAX_VALUE
from ..visualization import Visualization


class VisualizationPanel(QWidget):
    changed = Signal(object)  # emits a Visualization
    trimPlaybackChanged = Signal(bool)
    rotationChanged = Signal(int)
    secondaryRotationChanged = Signal(int)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        show_rotation: bool = False,
        show_secondary_rotation: bool = False,
    ) -> None:
        super().__init__(parent)
        self._suggested: tuple[int, int] | None = None
        self._dark_field_available = False

        title = QLabel("Visualization")
        title.setObjectName("sectionTitle")

        self.level = self._slider(0, MAX_VALUE, MAX_VALUE // 2)
        self.width = self._slider(1, MAX_VALUE, MAX_VALUE)
        self.brightness = self._slider(-128, 128, 0)
        self.contrast = self._slider(20, 400, 100)
        self.rotation = self._slider(-180, 180, 0)
        self.secondary_rotation = self._slider(-180, 180, 0)
        self.level_value = QLabel(str(MAX_VALUE // 2))
        self.width_value = QLabel(str(MAX_VALUE))
        self.brightness_value = QLabel("0")
        self.contrast_value = QLabel("1.00")
        self.rotation_value = QLabel("0°")
        self.secondary_rotation_value = QLabel("0°")
        for label in (
            self.level_value,
            self.width_value,
            self.brightness_value,
            self.contrast_value,
            self.rotation_value,
            self.secondary_rotation_value,
        ):
            label.setObjectName("statusValue")
            label.setAlignment(Qt.AlignmentFlag.AlignRight)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self._add_row(grid, 0, "Window level", self.level, self.level_value)
        self._add_row(grid, 2, "Window width", self.width, self.width_value)
        self._add_row(grid, 4, "Brightness", self.brightness, self.brightness_value)
        self._add_row(grid, 6, "Contrast", self.contrast, self.contrast_value)
        self.rotation_label: QLabel | None = None
        self.secondary_rotation_label: QLabel | None = None
        if show_rotation:
            self.rotation_label = self._add_row(
                grid, 8, "Rotation", self.rotation, self.rotation_value
            )
        if show_secondary_rotation:
            self.secondary_rotation_label = self._add_row(
                grid,
                10,
                "Rotation B",
                self.secondary_rotation,
                self.secondary_rotation_value,
            )
            self.set_comparison_rotation_visible(False)

        self.invert = QCheckBox("Invert grayscale")
        self.dark_field = QCheckBox("Dark-field correction")
        self.trim_playback = QCheckBox("Trim playback")
        self.dark_field.setChecked(True)
        self.dark_field.setEnabled(False)

        buttons = QHBoxLayout()
        self.auto_button = QPushButton("Auto window")
        self.reset_button = QPushButton("Reset")
        buttons.addWidget(self.auto_button)
        buttons.addWidget(self.reset_button)

        options = QVBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(10)
        options.addWidget(self.invert)
        options.addWidget(self.dark_field)
        options.addWidget(self.trim_playback)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addLayout(grid)
        layout.addLayout(options)
        layout.addLayout(buttons)

        for slider in (self.level, self.width, self.brightness, self.contrast):
            slider.valueChanged.connect(self._emit)
        self.rotation.valueChanged.connect(self._on_rotation_changed)
        self.secondary_rotation.valueChanged.connect(self._on_secondary_rotation_changed)
        self.invert.toggled.connect(self._emit)
        self.dark_field.toggled.connect(self._emit)
        self.trim_playback.toggled.connect(self.trimPlaybackChanged)
        self.auto_button.clicked.connect(self._apply_auto)
        self.reset_button.clicked.connect(self._reset)

    def _slider(self, minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        return slider

    def _add_row(
        self,
        grid: QGridLayout,
        row: int,
        name: str,
        slider: QSlider,
        value: QLabel,
    ) -> QLabel:
        label = QLabel(name)
        label.setObjectName("subtleLabel")
        grid.addWidget(label, row, 0)
        grid.addWidget(value, row, 1)
        grid.addWidget(slider, row + 1, 0, 1, 2)
        return label

    def visualization(self) -> Visualization:
        return Visualization(
            level=self.level.value(),
            width=self.width.value(),
            brightness=self.brightness.value(),
            contrast=self.contrast.value() / 100.0,
            rotation=self.rotation.value(),
            invert=self.invert.isChecked(),
            dark_field=self.dark_field.isChecked() and self._dark_field_available,
        )

    def set_dark_field_available(self, available: bool) -> None:
        self._dark_field_available = available
        self.dark_field.setEnabled(available)
        if not available:
            self.dark_field.setChecked(False)

    def set_suggested_window(self, suggested: tuple[int, int] | None) -> None:
        self._suggested = suggested

    def apply_window(self, level: int, width: int) -> None:
        for slider, value in ((self.level, level), (self.width, width)):
            slider.blockSignals(True)
            slider.setValue(int(value))
            slider.blockSignals(False)
        self._emit()

    def set_rotation(self, rotation: int) -> None:
        self.rotation.blockSignals(True)
        self.rotation.setValue(int(rotation))
        self.rotation.blockSignals(False)
        self.rotation_value.setText(f"{self.rotation.value()}°")

    def set_secondary_rotation(self, rotation: int) -> None:
        self.secondary_rotation.blockSignals(True)
        self.secondary_rotation.setValue(int(rotation))
        self.secondary_rotation.blockSignals(False)
        self.secondary_rotation_value.setText(f"{self.secondary_rotation.value()}°")

    def set_comparison_rotation_visible(self, visible: bool) -> None:
        if self.rotation_label is not None:
            self.rotation_label.setText("Rotation A" if visible else "Rotation")
        if self.secondary_rotation_label is None:
            return
        for widget in (
            self.secondary_rotation_label,
            self.secondary_rotation_value,
            self.secondary_rotation,
        ):
            widget.setVisible(visible)

    def _apply_auto(self) -> None:
        if self._suggested is not None:
            self.apply_window(*self._suggested)

    def _reset(self) -> None:
        previous_rotation = self.rotation.value()
        previous_secondary_rotation = self.secondary_rotation.value()
        defaults = (
            (self.level, MAX_VALUE // 2),
            (self.width, MAX_VALUE),
            (self.brightness, 0),
            (self.contrast, 100),
            (self.rotation, 0),
            (self.secondary_rotation, 0),
        )
        for slider, value in defaults:
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self.invert.blockSignals(True)
        self.invert.setChecked(False)
        self.invert.blockSignals(False)
        self._emit()
        if previous_rotation != self.rotation.value():
            self.rotationChanged.emit(self.rotation.value())
        if previous_secondary_rotation != self.secondary_rotation.value():
            self.secondaryRotationChanged.emit(self.secondary_rotation.value())

    def _on_rotation_changed(self, rotation: int) -> None:
        self._emit()
        self.rotationChanged.emit(rotation)

    def _on_secondary_rotation_changed(self, rotation: int) -> None:
        self.secondary_rotation_value.setText(f"{rotation}°")
        self.secondaryRotationChanged.emit(rotation)

    def _emit(self) -> None:
        self.level_value.setText(str(self.level.value()))
        self.width_value.setText(str(self.width.value()))
        self.brightness_value.setText(str(self.brightness.value()))
        self.contrast_value.setText(f"{self.contrast.value() / 100.0:.2f}")
        self.rotation_value.setText(f"{self.rotation.value()}°")
        self.secondary_rotation_value.setText(f"{self.secondary_rotation.value()}°")
        self.changed.emit(self.visualization())

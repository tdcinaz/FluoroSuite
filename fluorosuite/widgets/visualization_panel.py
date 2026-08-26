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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suggested: tuple[int, int] | None = None
        self._dark_field_available = False

        title = QLabel("Visualization")
        title.setObjectName("sectionTitle")

        self.level = self._slider(0, MAX_VALUE, MAX_VALUE // 2)
        self.width = self._slider(1, MAX_VALUE, MAX_VALUE)
        self.brightness = self._slider(-128, 128, 0)
        self.contrast = self._slider(20, 400, 100)
        self.level_value = QLabel(str(MAX_VALUE // 2))
        self.width_value = QLabel(str(MAX_VALUE))
        self.brightness_value = QLabel("0")
        self.contrast_value = QLabel("1.00")
        for label in (self.level_value, self.width_value, self.brightness_value, self.contrast_value):
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

        self.invert = QCheckBox("Invert grayscale")
        self.dark_field = QCheckBox("Dark-field correction")
        self.dark_field.setChecked(True)
        self.dark_field.setEnabled(False)

        buttons = QHBoxLayout()
        self.auto_button = QPushButton("Auto window")
        self.reset_button = QPushButton("Reset")
        buttons.addWidget(self.auto_button)
        buttons.addWidget(self.reset_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addLayout(grid)
        layout.addWidget(self.invert)
        layout.addWidget(self.dark_field)
        layout.addLayout(buttons)

        for slider in (self.level, self.width, self.brightness, self.contrast):
            slider.valueChanged.connect(self._emit)
        self.invert.toggled.connect(self._emit)
        self.dark_field.toggled.connect(self._emit)
        self.auto_button.clicked.connect(self._apply_auto)
        self.reset_button.clicked.connect(self._reset)

    def _slider(self, minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        return slider

    def _add_row(self, grid: QGridLayout, row: int, name: str, slider: QSlider, value: QLabel) -> None:
        label = QLabel(name)
        label.setObjectName("subtleLabel")
        grid.addWidget(label, row, 0)
        grid.addWidget(value, row, 1)
        grid.addWidget(slider, row + 1, 0, 1, 2)

    def visualization(self) -> Visualization:
        return Visualization(
            level=self.level.value(),
            width=self.width.value(),
            brightness=self.brightness.value(),
            contrast=self.contrast.value() / 100.0,
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

    def _apply_auto(self) -> None:
        if self._suggested is not None:
            self.apply_window(*self._suggested)

    def _reset(self) -> None:
        defaults = ((self.level, MAX_VALUE // 2), (self.width, MAX_VALUE), (self.brightness, 0), (self.contrast, 100))
        for slider, value in defaults:
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self.invert.blockSignals(True)
        self.invert.setChecked(False)
        self.invert.blockSignals(False)
        self._emit()

    def _emit(self) -> None:
        self.level_value.setText(str(self.level.value()))
        self.width_value.setText(str(self.width.value()))
        self.brightness_value.setText(str(self.brightness.value()))
        self.contrast_value.setText(f"{self.contrast.value() / 100.0:.2f}")
        self.changed.emit(self.visualization())

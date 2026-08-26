"""Small metric card used to summarize analysis results."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class MetricCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self._title = QLabel(title)
        self._title.setObjectName("metricTitle")
        self._value = QLabel("--")
        self._value.setObjectName("metricValue")
        self._detail = QLabel("")
        self._detail.setObjectName("metricDetail")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._detail)

    def set_value(self, value: str, detail: str = "") -> None:
        self._value.setText(value)
        self._detail.setText(detail)

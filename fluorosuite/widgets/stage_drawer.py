"""Collapsible pipeline stage card, adapted from the legacy Contrast StageDrawer."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFrame,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class StageDrawer(QFrame):
    enabledChanged = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stageDrawer")

        self.enable_button = QToolButton()
        self.enable_button.setObjectName("stageEnableButton")
        self.enable_button.setCheckable(True)
        self.enable_button.setFixedSize(32, 32)
        self.enable_button.setToolTip("Enable stage")

        self.stage_label = QLabel(title)
        self.stage_label.setObjectName("stageLabel")
        self.stage_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.expand_button = QToolButton()
        self.expand_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.expand_button.setArrowType(Qt.ArrowType.RightArrow)
        self.expand_button.setCheckable(True)
        self.expand_button.setFixedSize(32, 32)
        self.expand_button.setToolTip("Show stage options")

        self.header = QWidget()
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.installEventFilter(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(self.enable_button)
        header_layout.addWidget(self.stage_label, 1)
        header_layout.addWidget(self.expand_button)

        self.content = QWidget()
        self.content.setVisible(False)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setVisible(False)
        self.status_label.setWordWrap(True)
        self.status_label.setContentsMargins(8, 0, 8, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(self.header)
        layout.addWidget(self.status_label)
        layout.addWidget(self.content)

        self._set_enabled_icon(False)
        self.enable_button.toggled.connect(self._set_enabled_icon)
        self.enable_button.toggled.connect(self.enabledChanged.emit)
        self.expand_button.toggled.connect(self._set_expanded)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.header
            and event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if not self._is_control_at(event.position().toPoint()):
                self.expand_button.toggle()
                return True
        return super().eventFilter(watched, event)

    def _is_control_at(self, point) -> bool:
        widget = self.header.childAt(point)
        while widget is not None:
            if widget in (self.enable_button, self.expand_button):
                return True
            widget = widget.parentWidget()
        return False

    def is_enabled(self) -> bool:
        return self.enable_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.expand_button.setChecked(expanded)

    def set_status(self, message: str | None, is_error: bool = False) -> None:
        if not message:
            self.status_label.clear()
            self.status_label.setVisible(False)
            return
        color = "#fca5a5" if is_error else "#9fb0c6"
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setVisible(True)

    def _set_expanded(self, expanded: bool) -> None:
        self.expand_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)

    def _set_enabled_icon(self, enabled: bool) -> None:
        color = QColor("#14b8a6" if enabled else "#64748b")
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(5, 5, 22, 22))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.drawEllipse(QRectF(9, 9, 14, 14))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setPen(QPen(color, 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(16, 4, 16, 14)
        painter.end()
        self.enable_button.setIcon(QIcon(pixmap))
        self.enable_button.setToolTip("Disable stage" if enabled else "Enable stage")

"""Displays a 16-bit fluoroscopy frame with window/level and optional ROI editing."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..pipeline.models import Circle
from ..theme import ROI_COLOR
from ..visualization import Visualization, to_qimage


class FrameView(QWidget):
    """Aspect-correct display for raw frames, with click-to-place ROI support."""

    roiPlaced = Signal(object)  # emits a Circle

    def __init__(self, placeholder: str = "No frame", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame: np.ndarray | None = None
        self._visualization = Visualization.default()
        self._lut = self._visualization.build_lut()
        self._qimage = None
        self._display_rect = QRect()
        self._placeholder = placeholder

        self.roi_editable = False
        self.roi_radius = 70
        self._roi: Circle | None = None
        self._roi_color = QColor(ROI_COLOR)
        self._roi_processing = False
        self._roi_progress = 0.0

        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #000000; border: 1px solid #253044; border-radius: 8px;")

    def set_roi_color(self, color: str) -> None:
        self._roi_color = QColor(color)
        self.update()

    # -- data -----------------------------------------------------------------
    def set_frame(self, frame: np.ndarray | None) -> None:
        self._frame = frame
        self._rebuild_image()
        self.update()

    def set_visualization(self, visualization: Visualization) -> None:
        self._visualization = visualization
        self._lut = visualization.build_lut()
        self._rebuild_image()
        self.update()

    def _rebuild_image(self) -> None:
        self._qimage = None if self._frame is None else to_qimage(self._frame, self._lut)

    # -- roi ------------------------------------------------------------------
    def set_roi(self, roi: Circle | None) -> None:
        self._roi = roi
        if roi is not None:
            self.roi_radius = roi.radius
        self.update()

    def set_roi_processing(self, processing: bool, progress: float = 0.0) -> None:
        self._roi_processing = processing
        self._roi_progress = min(1.0, max(0.0, float(progress))) if processing else 0.0
        self.update()

    def roi(self) -> Circle | None:
        return self._roi

    def set_roi_radius(self, radius: int) -> None:
        self.roi_radius = max(1, int(radius))
        if self._roi is not None:
            self._roi = Circle(self._roi.center_x, self._roi.center_y, self.roi_radius)
            self.roiPlaced.emit(self._roi)
        self.update()

    def set_roi_editable(self, editable: bool) -> None:
        self.roi_editable = editable
        self.setCursor(Qt.CursorShape.CrossCursor if editable else Qt.CursorShape.ArrowCursor)

    # -- painting -------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

        if self._qimage is None:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            self._display_rect = QRect()
            return

        self._display_rect = self._fit_rect(self._qimage.width(), self._qimage.height())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self._display_rect, self._qimage)

        if self._roi is not None and self._frame is not None:
            center = self._frame_to_display(QPoint(self._roi.center_x, self._roi.center_y))
            scale = self._display_rect.width() / max(1, self._frame.shape[1])
            radius = max(1, round(self._roi.radius * scale))
            roi_color = QColor("#facc15") if self._roi_processing else self._roi_color
            painter.setPen(QPen(roi_color, 2))
            if self._roi_processing:
                painter.setBrush(QColor(roi_color.red(), roi_color.green(), roi_color.blue(), 55))
                bounds = QRect(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPie(bounds, 90 * 16, -round(self._roi_progress * 360 * 16))
                painter.setPen(QPen(roi_color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                painter.setBrush(QColor(roi_color.red(), roi_color.green(), roi_color.blue(), 40))
            painter.drawEllipse(center, radius, radius)
            painter.setPen(QColor("#f8fafc"))
            painter.drawText(center + QPoint(radius + 4, -radius), "ROI")

    def _fit_rect(self, image_width: int, image_height: int) -> QRect:
        available = self.rect()
        if image_width <= 0 or image_height <= 0:
            return QRect()
        scale = min(available.width() / image_width, available.height() / image_height)
        width = max(1, round(image_width * scale))
        height = max(1, round(image_height * scale))
        x = available.left() + (available.width() - width) // 2
        y = available.top() + (available.height() - height) // 2
        return QRect(x, y, width, height)

    # -- coordinate mapping ---------------------------------------------------
    def _display_to_frame(self, point: QPoint) -> QPoint | None:
        if self._frame is None or self._display_rect.isEmpty() or not self._display_rect.contains(point):
            return None
        rows, cols = self._frame.shape
        x_fraction = (point.x() - self._display_rect.left()) / max(1, self._display_rect.width())
        y_fraction = (point.y() - self._display_rect.top()) / max(1, self._display_rect.height())
        x = round(min(1.0, max(0.0, x_fraction)) * (cols - 1))
        y = round(min(1.0, max(0.0, y_fraction)) * (rows - 1))
        return QPoint(x, y)

    def _frame_to_display(self, point: QPoint) -> QPoint:
        rows, cols = self._frame.shape
        x_scale = self._display_rect.width() / max(1, cols)
        y_scale = self._display_rect.height() / max(1, rows)
        return QPoint(
            round(self._display_rect.left() + point.x() * x_scale),
            round(self._display_rect.top() + point.y() * y_scale),
        )

    # -- interaction ----------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.roi_editable or event.button() != Qt.MouseButton.LeftButton:
            return
        frame_point = self._display_to_frame(event.position().toPoint())
        if frame_point is None:
            return
        self._roi = Circle(frame_point.x(), frame_point.y(), self.roi_radius)
        self.roiPlaced.emit(self._roi)
        self.update()

"""Displays a 16-bit fluoroscopy frame with window/level and optional ROI editing."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QResizeEvent,
    QShowEvent,
    QTransform,
)
from PySide6.QtWidgets import QComboBox, QSizePolicy, QWidget

from ..pipeline.models import Circle, Rectangle
from ..theme import INLET_ROI_COLOR, ROI_COLOR
from ..visualization import Visualization, to_qimage


class FrameView(QWidget):
    """Aspect-correct display for raw frames, with click-to-place ROI support."""

    roiPlaced = Signal(object)  # emits a Circle
    inletRoiPlaced = Signal(object)  # emits a Rectangle

    def __init__(
        self,
        placeholder: str = "No frame",
        parent: QWidget | None = None,
        *,
        circular_mask: bool = False,
    ) -> None:
        super().__init__(parent)
        self._frame: np.ndarray | None = None
        self._circular_mask = circular_mask
        self._visualization = Visualization.default()
        self._lut = self._visualization.build_lut()
        self._qimage = None
        self._display_rect = QRect()
        self._placeholder = placeholder
        self._overlay_widget: QWidget | None = None

        self.roi_editable = False
        self.inlet_roi_editable = False
        self.roi_radius = 70
        self._roi: Circle | None = None
        self._inlet_roi: Rectangle | None = None
        self._roi_color = QColor(ROI_COLOR)
        self._roi_processing = False
        self._roi_progress = 0.0

        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #000000; border: 1px solid #253044; border-radius: 8px;")

    def set_overlay_widget(self, widget: QWidget) -> None:
        self._overlay_widget = widget
        widget.setParent(self)
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self.update_overlay_geometry)
        widget.show()
        self.update_overlay_geometry()

    def update_overlay_geometry(self) -> None:
        if self._overlay_widget is None:
            return
        margin = 12
        available_width = max(0, self.width() - margin * 2)
        preferred_width = self._overlay_widget.sizeHint().width()
        width = min(420, available_width, preferred_width)
        self._overlay_widget.setGeometry(margin, margin, width, self._overlay_widget.sizeHint().height())
        self._overlay_widget.raise_()

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

    def set_inlet_roi(self, roi: Rectangle | None) -> None:
        self._inlet_roi = roi
        self.update()

    def inlet_roi(self) -> Rectangle | None:
        return self._inlet_roi

    def set_roi_radius(self, radius: int) -> None:
        self.roi_radius = max(1, int(radius))
        if self._roi is not None:
            self._roi = Circle(self._roi.center_x, self._roi.center_y, self.roi_radius)
            self.roiPlaced.emit(self._roi)
        self.update()

    def set_roi_editable(self, editable: bool) -> None:
        self.roi_editable = editable
        self._update_roi_cursor()

    def set_inlet_roi_editable(self, editable: bool) -> None:
        self.inlet_roi_editable = editable
        self._update_roi_cursor()

    def _update_roi_cursor(self) -> None:
        editable = self.roi_editable or self.inlet_roi_editable
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
        painter.save()
        if self._circular_mask:
            mask_path = QPainterPath()
            mask_path.addEllipse(QRectF(self._display_rect))
            painter.setClipPath(mask_path)
        center = QRectF(self._display_rect).center()
        painter.translate(center)
        painter.rotate(self._visualization.rotation)
        painter.translate(-center)
        painter.drawImage(self._display_rect, self._qimage)
        painter.restore()

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

        if self._inlet_roi is not None and self._frame is not None:
            polygon = QPolygonF(
                [
                    QPointF(self._frame_to_display(QPoint(round(x), round(y))))
                    for x, y in self._inlet_roi.corners()
                ]
            )
            inlet_color = QColor(INLET_ROI_COLOR)
            painter.setPen(QPen(inlet_color, 2))
            painter.setBrush(QColor(inlet_color.red(), inlet_color.green(), inlet_color.blue(), 40))
            painter.drawPolygon(polygon)
            bounds = polygon.boundingRect()
            painter.setPen(QColor("#f8fafc"))
            painter.drawText(bounds.topRight() + QPointF(4, 12), "Inlet")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.update_overlay_geometry()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.update_overlay_geometry()

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
        display_point = self._rotation_transform().inverted()[0].map(QPointF(point))
        rows, cols = self._frame.shape
        x_fraction = (display_point.x() - self._display_rect.left()) / max(1, self._display_rect.width())
        y_fraction = (display_point.y() - self._display_rect.top()) / max(1, self._display_rect.height())
        x = round(min(1.0, max(0.0, x_fraction)) * (cols - 1))
        y = round(min(1.0, max(0.0, y_fraction)) * (rows - 1))
        return QPoint(x, y)

    def _frame_to_display(self, point: QPoint) -> QPoint:
        rows, cols = self._frame.shape
        x_scale = self._display_rect.width() / max(1, cols)
        y_scale = self._display_rect.height() / max(1, rows)
        display_point = QPointF(
            round(self._display_rect.left() + point.x() * x_scale),
            round(self._display_rect.top() + point.y() * y_scale),
        )
        return self._rotation_transform().map(display_point).toPoint()

    def _rotation_transform(self) -> QTransform:
        center = QRectF(self._display_rect).center()
        transform = QTransform()
        transform.translate(center.x(), center.y())
        transform.rotate(self._visualization.rotation)
        transform.translate(-center.x(), -center.y())
        return transform

    # -- interaction ----------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        placing_aneurysm = self.roi_editable and event.button() == Qt.MouseButton.LeftButton
        placing_inlet = self.inlet_roi_editable and event.button() == Qt.MouseButton.RightButton
        if not placing_aneurysm and not placing_inlet:
            return
        frame_point = self._display_to_frame(event.position().toPoint())
        if frame_point is None:
            return
        if placing_aneurysm:
            self._roi = Circle(frame_point.x(), frame_point.y(), self.roi_radius)
            self.roiPlaced.emit(self._roi)
        else:
            self._inlet_roi = Rectangle(
                frame_point.x(),
                frame_point.y(),
                width=40,
                height=120,
                rotation=self._visualization.rotation,
            )
            self.inletRoiPlaced.emit(self._inlet_roi)
        self.update()

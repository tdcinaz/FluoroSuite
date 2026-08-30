"""Video filename selector that can refresh its contents before opening."""

from PySide6.QtCore import QPoint, QSize, Signal
from PySide6.QtWidgets import QComboBox, QWidget


class RecordingSelector(QComboBox):
    """A combo box that announces when its popup is about to open."""

    popupAboutToShow = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("recordingOverlay")
        self.setPlaceholderText("Select video file")

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        text = self.currentText() or self.placeholderText()
        return QSize(self.fontMetrics().horizontalAdvance(text) + 22, hint.height())

    def showPopup(self) -> None:
        self.popupAboutToShow.emit()
        widest_text = max(
            (self.fontMetrics().horizontalAdvance(self.itemText(index)) for index in range(self.count())),
            default=0,
        )
        popup_width = max(self.width(), widest_text + 64)
        self.view().setMinimumWidth(popup_width - 2)
        super().showPopup()
        popup = self.view().window()
        popup.resize(popup_width, popup.height())
        popup.move(self.mapToGlobal(QPoint(0, 0)).x(), popup.y())
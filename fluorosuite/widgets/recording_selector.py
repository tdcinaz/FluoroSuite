"""Recording selector that can refresh its contents before opening."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox


class RecordingSelector(QComboBox):
    """A combo box that announces when its popup is about to open."""

    popupAboutToShow = Signal()

    def showPopup(self) -> None:
        self.popupAboutToShow.emit()
        super().showPopup()
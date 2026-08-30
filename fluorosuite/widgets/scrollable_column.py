"""Responsive vertical scrolling for narrow control columns."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLayout, QScrollArea, QSizePolicy, QWidget


class ScrollableColumn(QScrollArea):
    """Let a control column fill available height and scroll when necessary."""

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        content_layout = content.layout()
        if content_layout is not None:
            content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setWidget(content)

        if content.minimumWidth() > 0:
            self.setMinimumWidth(content.minimumWidth())
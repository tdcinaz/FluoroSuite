from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fluorosuite.visualization import Visualization
from fluorosuite.widgets.frame_view import FrameView


class FrameViewInletROITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_right_click_places_fixed_inlet_roi_at_current_rotation(self) -> None:
        view = FrameView()
        view.resize(400, 400)
        view.set_frame(np.zeros((1024, 1024), dtype=np.uint16))
        view.set_visualization(Visualization.default().with_rotation(86))
        view.set_inlet_roi_editable(True)
        view.show()
        self.app.processEvents()

        QTest.mouseClick(view, Qt.MouseButton.RightButton, pos=view.rect().center())

        roi = view.inlet_roi()
        self.assertIsNotNone(roi)
        assert roi is not None
        self.assertLessEqual(abs(roi.center_x - 512), 3)
        self.assertLessEqual(abs(roi.center_y - 512), 3)
        self.assertEqual((roi.width, roi.height), (40, 120))
        self.assertEqual(roi.rotation, 86)
        view.close()


if __name__ == "__main__":
    unittest.main()
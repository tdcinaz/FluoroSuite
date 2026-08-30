"""Shared dark theme, adapted from the legacy Contrast analyzer design."""

from __future__ import annotations

# Panel accent colors for ROI overlays and plot traces.
ROI_COLOR = "#38bdf8"
ACCENT = "#14b8a6"
# Trace/ROI colors for the two comparison videos.
TRACE_A = "#38bdf8"
TRACE_B = "#f5a25d"

STYLESHEET = """
QMainWindow, QWidget { background: #0b1018; color: #e5edf6; font-size: 13px; }
QToolTip { background: #111827; color: #e5edf6; border: 1px solid #334155; }

QTabWidget::pane { border: 1px solid #253044; border-radius: 8px; top: -1px; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background: #111827; color: #9fb0c6; border: 1px solid #253044;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
    padding: 9px 26px; margin-right: 4px; font-weight: 700; font-size: 14px;
}
QTabBar::tab:selected { background: #0f172a; color: #f8fafc; border-bottom-color: #0f172a; }
QTabBar::tab:hover:!selected { background: #182233; color: #e5edf6; }

QPushButton { background: #1c2637; border: 1px solid #334155; border-radius: 7px; color: #e5edf6; padding: 7px 12px; }
QPushButton:hover { background: #263449; border-color: #5eead4; }
QPushButton:disabled { color: #64748b; background: #111827; }
QPushButton#primaryButton { background: #0f766e; border-color: #14b8a6; font-weight: 700; }
QPushButton#primaryButton:hover { background: #0d9488; }
QPushButton#primaryButton[analysisRunning="true"] { background: #a16207; border-color: #facc15; color: #fef9c3; }
QPushButton#primaryButton[analysisRunning="true"]:hover { background: #ca8a04; }
QPushButton#recordButton:checked { background: #7f1d1d; border-color: #f87171; color: #fee2e2; font-weight: 700; }
QPushButton#modeButton { background: #111827; border: 1px solid #334155; color: #9fb0c6; padding: 6px 16px; font-weight: 700; }
QPushButton#modeButton:checked { background: #134e4a; border-color: #14b8a6; color: #f0fdfa; }
QPushButton#playbackPlayButton, QPushButton#playbackSeekButton, QPushButton#playbackLoopButton { min-width: 38px; min-height: 30px; padding: 3px 8px; font-weight: 800; }
QPushButton#playbackPlayButton { background: #134e4a; border-color: #14b8a6; color: #f8fafc; font-size: 16px; }
QPushButton#playbackPlayButton:hover { background: #0f766e; border-color: #5eead4; }
QPushButton#playbackPlayButton[playing="true"] { background: #a16207; border-color: #facc15; color: #f8fafc; }
QPushButton#playbackPlayButton[playing="true"]:hover { background: #ca8a04; border-color: #fde047; }
QPushButton#playbackSeekButton { background: #1c2637; border-color: #475569; color: #f8fafc; font-size: 11px; }
QPushButton#playbackSeekButton:hover { background: #263449; border-color: #cbd5e1; }
QPushButton#playbackLoopButton { background: #1c2637; border-color: #475569; color: #f8fafc; font-size: 20px; }
QPushButton#playbackLoopButton:hover { background: #263449; border-color: #cbd5e1; }
QPushButton#playbackLoopButton:checked { background: #134e4a; border-color: #14b8a6; }

QToolButton { background: #1c2637; border: 1px solid #334155; border-radius: 6px; padding: 4px; }
QToolButton:hover { background: #263449; }

QLabel#panelTitle { font-size: 16px; font-weight: 700; color: #f8fafc; }
QLabel#sectionTitle { color: #8fb3a6; font-size: 12px; font-weight: 700; letter-spacing: 1px; }
QLabel#subtleLabel { color: #9fb0c6; }
QLabel#statusValue { color: #67e8f9; }
QLabel#recBadge { color: #f87171; font-weight: 700; }

QGroupBox { background: #111827; border: 1px solid #253044; border-radius: 8px; margin-top: 12px; padding: 12px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #f8fafc; }

QSlider::groove:horizontal { height: 6px; background: #273449; border-radius: 3px; }
QSlider::handle:horizontal { background: #67e8f9; width: 16px; margin: -5px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: #a5f3fc; }

QSpinBox, QDoubleSpinBox, QComboBox { background: #111827; border: 1px solid #334155; border-radius: 6px; padding: 5px; color: #e5edf6; }
QComboBox::drop-down { border: none; }
QLineEdit { background: #111827; border: 1px solid #5b718c; border-radius: 5px; padding: 5px 7px; color: #f8fafc; }
QLineEdit:focus { border-color: #5eead4; }
QCheckBox { color: #cdd8d2; }

QSplitter::handle:horizontal { background: transparent; border: none; }
QSplitter::handle:vertical { background: transparent; border: none; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 0 0 0 6px; }
QScrollBar::handle:vertical { background: #475569; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #64748b; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QFrame#card { background: #111827; border: 1px solid #253044; border-radius: 8px; }
QFrame#stageDrawer { background: #0f172a; border: 1px solid #273449; border-radius: 8px; }
QFrame#drawer { background: #0f172a; border: 1px solid #253044; border-radius: 8px; }
QFrame#metricCard { background: #0f172a; border: 1px solid #273449; border-radius: 8px; }
QLabel#metricTitle { color: #9fb0c6; font-size: 12px; }
QLabel#metricValue { color: #f8fafc; font-size: 22px; font-weight: 800; }
QLabel#metricDetail { color: #94a3b8; font-size: 12px; }

QToolButton#stageEnableButton { border: 1px solid transparent; border-radius: 6px; }
QToolButton#stageEnableButton:hover { background: #1c2637; border-color: #334155; }
QToolButton#stageEnableButton:checked { background: #134e4a; border-color: #14b8a6; }
QLabel#stageLabel { color: #f8fafc; font-weight: 700; }

QStatusBar { background: #0b1018; color: #9fb0c6; }
"""

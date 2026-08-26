"""Analysis page: place an aneurysm ROI circle and measure contrast residence."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..pipeline import STAGE_REGISTRY, Circle, ROIParameters, analyze_roi_residence
from ..recordings import RecordingInfo
from ..theme import ROI_COLOR
from ..visualization import DarkFieldCorrection, auto_window
from ..widgets import MetricCard, StageDrawer
from .recording_viewer import RecordingViewer


class AnalysisPage(RecordingViewer):
    def __init__(
        self,
        live_dir: Path,
        correction: DarkFieldCorrection | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(live_dir, correction, parent)
        self._roi: Circle | None = None

        pipeline_drawer = self._build_pipeline_drawer()
        center = self._build_center()
        analysis_panel = self._build_analysis_panel()

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(center)
        right_splitter.addWidget(analysis_panel)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(pipeline_drawer)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([340, 1100])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(main_splitter)

        self.frame_view.roiPlaced.connect(self._on_roi_placed)

    # -- construction ---------------------------------------------------------
    def _build_pipeline_drawer(self) -> QFrame:
        drawer = QFrame()
        drawer.setObjectName("drawer")
        drawer.setMinimumWidth(300)
        layout = QVBoxLayout(drawer)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        title = QLabel("Pipeline")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        definition = STAGE_REGISTRY["roi_analysis"]
        self.stage = StageDrawer(definition.display_name)
        self.stage.enabledChanged.connect(self._on_stage_enabled)
        self._build_stage_controls(self.stage, definition.description)
        layout.addWidget(self.stage)

        layout.addWidget(self.visualization_panel)
        layout.addStretch(1)
        return drawer

    def _build_stage_controls(self, stage: StageDrawer, description: str) -> None:
        hint = QLabel(description + "\n\nEnable the stage, then click the aneurysm to place the ROI.")
        hint.setObjectName("subtleLabel")
        hint.setWordWrap(True)
        stage.content_layout.addWidget(hint)

        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(5, 400)
        self.radius_spin.setValue(70)
        self.baseline_spin = QSpinBox()
        self.baseline_spin.setRange(1, 200)
        self.baseline_spin.setValue(8)
        self.clearance_spin = QDoubleSpinBox()
        self.clearance_spin.setRange(0.01, 0.90)
        self.clearance_spin.setSingleStep(0.05)
        self.clearance_spin.setValue(0.10)
        self.smoothing_spin = QSpinBox()
        self.smoothing_spin.setRange(1, 31)
        self.smoothing_spin.setValue(5)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self._add_param(grid, 0, "ROI radius (px)", self.radius_spin)
        self._add_param(grid, 1, "Baseline frames", self.baseline_spin)
        self._add_param(grid, 2, "Clearance fraction", self.clearance_spin)
        self._add_param(grid, 3, "Smoothing window", self.smoothing_spin)
        stage.content_layout.addLayout(grid)

        self.radius_spin.valueChanged.connect(self._on_radius_changed)
        for widget in (self.baseline_spin, self.clearance_spin, self.smoothing_spin):
            widget.valueChanged.connect(self._run_analysis)

        stage.set_expanded(True)

    def _add_param(self, grid: QGridLayout, row: int, name: str, widget: QWidget) -> None:
        label = QLabel(name)
        label.setObjectName("subtleLabel")
        grid.addWidget(label, row, 0)
        grid.addWidget(widget, row, 1)

    def _build_center(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(self._build_selector_row())
        layout.addWidget(self.frame_view, 1)
        layout.addWidget(self.playback_bar)
        return center

    def _build_analysis_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Contrast residence")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.run_button = QPushButton("Run analysis")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._run_analysis)
        header.addWidget(self.run_button)
        layout.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.peak_card = MetricCard("Peak contrast")
        self.time_to_peak_card = MetricCard("Time to peak")
        self.residence_card = MetricCard("Residence time")
        self.baseline_card = MetricCard("Baseline ROI")
        for card in (self.peak_card, self.time_to_peak_card, self.residence_card, self.baseline_card):
            cards.addWidget(card)
        layout.addLayout(cards)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setBackground("#0b1018")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "Contrast (baseline - ROI)")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self._curve = self.plot.plot(pen=pg.mkPen(ROI_COLOR, width=2.5))
        layout.addWidget(self.plot, 1)
        return panel

    # -- parameters -----------------------------------------------------------
    def _parameters(self) -> ROIParameters:
        return ROIParameters(
            roi_radius=self.radius_spin.value(),
            baseline_frames=self.baseline_spin.value(),
            clearance_fraction=self.clearance_spin.value(),
            smoothing_window=self.smoothing_spin.value(),
        )

    # -- handlers -------------------------------------------------------------
    def _on_stage_enabled(self, enabled: bool) -> None:
        self.frame_view.set_roi_editable(enabled)
        if enabled:
            self.stage.set_status("Click the aneurysm on the image to place the ROI.")
        else:
            self.stage.set_status(None)

    def _on_radius_changed(self, radius: int) -> None:
        self.frame_view.set_roi_radius(radius)
        if self._roi is not None:
            self._roi = Circle(self._roi.center_x, self._roi.center_y, radius)
            self._run_analysis()

    def _on_roi_placed(self, roi: Circle) -> None:
        self._roi = roi
        self.stage.set_status(f"ROI at ({roi.center_x}, {roi.center_y}), r={roi.radius} px.")
        self._run_analysis()

    def _on_recording_opened(self, info: RecordingInfo) -> None:
        if self._current_frame is not None:
            level, width = auto_window(self._current_frame)
            self.visualization_panel.apply_window(level, width)
        self._roi = None
        self.frame_view.set_roi(None)
        self._clear_results()

    def _on_recording_cleared(self) -> None:
        self.frame_view._placeholder = "No recordings found"
        self.frame_view.update()

    def _run_analysis(self) -> None:
        if self._roi is None or not self.stage.is_enabled():
            return
        frames = self.frames_array()
        if frames is None or frames.shape[0] == 0:
            return
        fps = self._info.fps if self._info else 15.0
        result = analyze_roi_residence(frames, self._roi, self._parameters(), fps)

        self._curve.setData(result.time, result.contrast)
        self.peak_card.set_value(f"{result.peak_contrast:.1f}", "raw units")
        self.time_to_peak_card.set_value(f"{result.time_to_peak:.2f} s")
        self.residence_card.set_value(
            f"{result.residence_time:.2f} s",
            f"onset {result.onset_time:.2f}s \u2192 clear {result.clearance_time:.2f}s",
        )
        self.baseline_card.set_value(f"{result.baseline:.0f}", "raw units")

    def _clear_results(self) -> None:
        self._curve.setData([], [])
        for card in (self.peak_card, self.time_to_peak_card, self.residence_card, self.baseline_card):
            card.set_value("--")

"""Analysis page: place an aneurysm ROI circle and measure contrast residence.

Supports a single recording or a two-video side-by-side comparison.
"""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
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

from ..pipeline import (
    STAGE_REGISTRY,
    Circle,
    ROIParameters,
    ROIResidenceResult,
    analyze_roi_residence,
)
from ..theme import TRACE_A, TRACE_B
from ..visualization import DarkFieldCorrection, Visualization, auto_window
from ..widgets import MetricCard, PlaybackBar, StageDrawer, VisualizationPanel
from .recording_panel import RecordingPanel


class AnalysisPage(QWidget):
    def __init__(
        self,
        live_dir: Path,
        correction: DarkFieldCorrection | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._compare = False

        self.panel_a = RecordingPanel(live_dir, correction, "Video A")
        self.panel_a.set_roi_color(TRACE_A)
        self.panel_b = RecordingPanel(live_dir, correction, "Video B")
        self.panel_b.set_roi_color(TRACE_B)

        self.playback_bar = PlaybackBar()
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance)

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

        for panel in (self.panel_a, self.panel_b):
            panel.roiPlaced.connect(self._on_roi_placed)
            panel.recordingCleared.connect(lambda p=panel: self._on_panel_cleared(p))
        self.panel_a.recordingOpened.connect(self._on_panel_a_opened)
        self.panel_b.recordingOpened.connect(self._on_panel_b_opened)

        self.playback_bar.playToggled.connect(self._on_play_toggled)
        self.playback_bar.indexChanged.connect(self._on_scrub)
        self.playback_bar.speed.currentIndexChanged.connect(self._update_timer_interval)

        self._apply_mode()

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

        layout.addLayout(self._build_mode_toggle())

        definition = STAGE_REGISTRY["roi_analysis"]
        self.stage = StageDrawer(definition.display_name)
        self.stage.enabledChanged.connect(self._on_stage_enabled)
        self._build_stage_controls(self.stage, definition.description)
        layout.addWidget(self.stage)

        self.visualization_panel = VisualizationPanel()
        self.visualization_panel.set_dark_field_available(self.panel_a._correction is not None)
        self.visualization_panel.changed.connect(self._on_visualization_changed)
        layout.addWidget(self.visualization_panel)
        layout.addStretch(1)
        return drawer

    def _build_mode_toggle(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        label = QLabel("View")
        label.setObjectName("sectionTitle")
        row.addWidget(label)
        row.addSpacing(10)

        self.single_button = QPushButton("Single")
        self.compare_button = QPushButton("Compare")
        self._mode_group = QButtonGroup(self)
        for button in (self.single_button, self.compare_button):
            button.setObjectName("modeButton")
            button.setCheckable(True)
            self._mode_group.addButton(button)
            row.addWidget(button)
        self.single_button.setChecked(True)
        self.single_button.clicked.connect(lambda: self._set_compare(False))
        self.compare_button.clicked.connect(lambda: self._set_compare(True))
        row.addStretch(1)
        return row

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
        self.video_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.video_splitter.addWidget(self.panel_a)
        self.video_splitter.addWidget(self.panel_b)
        self.video_splitter.setStretchFactor(0, 1)
        self.video_splitter.setStretchFactor(1, 1)

        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.video_splitter, 1)
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
        self._legend = self.plot.addLegend(offset=(-10, 10))
        self._curve_a = self.plot.plot(pen=pg.mkPen(TRACE_A, width=2.5), name="Video A")
        self._curve_b = self.plot.plot(pen=pg.mkPen(TRACE_B, width=2.5), name="Video B")
        layout.addWidget(self.plot, 1)
        return panel

    # -- mode -----------------------------------------------------------------
    def _set_compare(self, compare: bool) -> None:
        if compare == self._compare:
            return
        self._compare = compare
        self._apply_mode()
        self._sync_playback()
        self._run_analysis()

    def _apply_mode(self) -> None:
        self.panel_b.setVisible(self._compare)
        self._curve_b.setVisible(self._compare)
        self._legend.setVisible(self._compare)
        self.single_button.setChecked(not self._compare)
        self.compare_button.setChecked(self._compare)
        if not self._compare:
            self._curve_b.setData([], [])

    # -- shared playback ------------------------------------------------------
    def _playback_panels(self) -> tuple[RecordingPanel, ...]:
        panels = (self.panel_a, self.panel_b) if self._compare else (self.panel_a,)
        return tuple(panel for panel in panels if panel.has_recording())

    def _timeline_count(self) -> int:
        return max((panel.frame_count for panel in self._playback_panels()), default=0)

    def _sync_playback(self, reset: bool = False) -> None:
        count = self._timeline_count()
        self.playback_bar.set_frame_count(count)
        index = 0 if reset else min(self.playback_bar.index(), max(0, count - 1))
        self._drive_index(index)

    def _drive_index(self, index: int) -> None:
        self.playback_bar.set_index(index)
        for panel in self._playback_panels():
            panel.show_frame(index)

    def _on_play_toggled(self, playing: bool) -> None:
        if playing:
            self._update_timer_interval()
            self._play_timer.start()
        else:
            self._play_timer.stop()

    def _pause(self) -> None:
        self._play_timer.stop()
        self.playback_bar.set_playing(False)

    def _advance(self) -> None:
        count = self._timeline_count()
        if count == 0:
            return
        index = self.playback_bar.index()
        if index >= count - 1:
            if self.playback_bar.is_looping():
                self._drive_index(0)
            else:
                self._pause()
            return
        self._drive_index(index + 1)

    def _update_timer_interval(self) -> None:
        count = self._timeline_count()
        fps = 15.0
        for panel in self._playback_panels():
            if panel.frame_count == count and panel.info is not None:
                fps = panel.info.fps
                break
        interval = 1000.0 / max(1.0, fps * self.playback_bar.speed_factor())
        self._play_timer.setInterval(int(interval))

    def _on_scrub(self, index: int) -> None:
        self._pause()
        self._drive_index(index)

    # -- parameters -----------------------------------------------------------
    def _parameters(self) -> ROIParameters:
        return ROIParameters(
            roi_radius=self.radius_spin.value(),
            baseline_frames=self.baseline_spin.value(),
            clearance_fraction=self.clearance_spin.value(),
            smoothing_window=self.smoothing_spin.value(),
        )

    # -- public ---------------------------------------------------------------
    def refresh_recordings(self) -> None:
        self._pause()
        self.panel_a.refresh_recordings()
        self.panel_b.refresh_recordings()
        self._sync_playback(reset=True)
        self._run_analysis()

    # -- handlers -------------------------------------------------------------
    def _on_stage_enabled(self, enabled: bool) -> None:
        for panel in (self.panel_a, self.panel_b):
            panel.set_roi_editable(enabled)
        if enabled:
            self.stage.set_status("Click the aneurysm on each image to place the ROI.")
        else:
            self.stage.set_status(None)

    def _on_radius_changed(self, radius: int) -> None:
        for panel in (self.panel_a, self.panel_b):
            panel.set_roi_radius(radius)
        self._run_analysis()

    def _on_roi_placed(self, roi: Circle) -> None:  # noqa: ARG002
        self._run_analysis()

    def _on_visualization_changed(self, visualization: Visualization) -> None:
        for panel in (self.panel_a, self.panel_b):
            panel.set_visualization(visualization)

    def _on_panel_a_opened(self, info: object) -> None:  # noqa: ARG002
        self._pause()
        frame = self.panel_a.current_frame
        if frame is not None:
            level, width = auto_window(frame)
            self.visualization_panel.apply_window(level, width)
        self._sync_playback(reset=True)
        self._run_analysis()

    def _on_panel_b_opened(self, info: object) -> None:  # noqa: ARG002
        self._pause()
        self._sync_playback(reset=True)
        self._run_analysis()

    def _on_panel_cleared(self, panel: RecordingPanel) -> None:
        panel.frame_view._placeholder = "No recordings found"
        panel.frame_view.update()
        self._sync_playback(reset=True)
        self._clear_results()

    def _analyze_panel(self, panel: RecordingPanel) -> ROIResidenceResult | None:
        if panel.roi is None or not panel.has_recording():
            return None
        frames = panel.frames_array()
        if frames is None or frames.shape[0] == 0:
            return None
        fps = panel.info.fps if panel.info else 15.0
        return analyze_roi_residence(frames, panel.roi, self._parameters(), fps)

    def _run_analysis(self) -> None:
        if not self.stage.is_enabled():
            return
        result_a = self._analyze_panel(self.panel_a)
        result_b = self._analyze_panel(self.panel_b) if self._compare else None

        if result_a is not None:
            self._curve_a.setData(result_a.time, result_a.contrast)
        else:
            self._curve_a.setData([], [])
        if result_b is not None:
            self._curve_b.setData(result_b.time, result_b.contrast)
        elif self._compare:
            self._curve_b.setData([], [])

        self._update_cards(result_a, result_b)

    def _update_cards(
        self,
        a: ROIResidenceResult | None,
        b: ROIResidenceResult | None,
    ) -> None:
        if a is None:
            self._clear_results()
            return

        def detail(value: str) -> str:
            if not self._compare:
                return "raw units"
            return f"B {value}" if b is not None else "B --"

        self.peak_card.set_value(f"{a.peak_contrast:.1f}", detail(f"{b.peak_contrast:.1f}" if b else ""))
        self.time_to_peak_card.set_value(
            f"{a.time_to_peak:.2f} s",
            (f"B {b.time_to_peak:.2f} s" if b else "B --") if self._compare else "",
        )
        residence_detail = (
            (f"B {b.residence_time:.2f} s" if b else "B --")
            if self._compare
            else f"onset {a.onset_time:.2f}s \u2192 clear {a.clearance_time:.2f}s"
        )
        self.residence_card.set_value(f"{a.residence_time:.2f} s", residence_detail)
        self.baseline_card.set_value(f"{a.baseline:.0f}", detail(f"{b.baseline:.0f}" if b else ""))

    def _clear_results(self) -> None:
        self._curve_a.setData([], [])
        self._curve_b.setData([], [])
        for card in (self.peak_card, self.time_to_peak_card, self.residence_card, self.baseline_card):
            card.set_value("--")

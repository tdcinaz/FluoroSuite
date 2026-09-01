"""Analysis page: place an aneurysm ROI circle and measure contrast residence.

Supports a single recording or a two-video side-by-side comparison.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, QTimer
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
    TimingAlignmentResult,
    analyze_roi_residence_stream,
    detect_injection_timing,
)
from ..theme import TRACE_A, TRACE_B
from ..recordings import (
    RecordingInfo,
    RecordingReader,
    load_saved_analysis_result,
    load_saved_timing_alignment,
    save_analysis_result,
    save_timing_alignment,
)
from ..visualization import DarkFieldCorrection, Visualization, auto_window
from ..widgets import MetricCard, PlaybackBar, ScrollableColumn, StageDrawer, VisualizationPanel
from .recording_panel import RecordingPanel


class _AnalysisSignals(QObject):
    finished = Signal(int, int, object)
    failed = Signal(int, int, object)
    progress = Signal(int, int, float)


class _AnalysisTask(QRunnable):
    def __init__(
        self,
        generation: int,
        panel_index: int,
        panel: RecordingPanel,
        parameters: ROIParameters,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.panel_index = panel_index
        self.inputs = self._snapshot_panel(panel)
        self.parameters = parameters
        self.signals = _AnalysisSignals()
        self.cancelled = False

    def run(self) -> None:
        if self.cancelled:
            self.signals.finished.emit(self.generation, self.panel_index, None)
            return
        try:
            result = self._analyze_panel(
                self.inputs,
                self.parameters,
                lambda value: self.signals.progress.emit(self.generation, self.panel_index, value),
                lambda: not self.cancelled,
            )
        except Exception as error:  # pragma: no cover - defensive worker boundary
            self.signals.failed.emit(self.generation, self.panel_index, error)
            return
        self.signals.finished.emit(self.generation, self.panel_index, result)

    @staticmethod
    def _snapshot_panel(
        panel: RecordingPanel,
    ) -> tuple[RecordingReader, Circle, RecordingInfo | None, Visualization, DarkFieldCorrection | None] | None:
        if panel.roi is None or panel._reader is None:
            return None
        return panel._reader, panel.roi, panel.info, panel._visualization, panel._correction

    @staticmethod
    def _analyze_panel(
        inputs: tuple[RecordingReader, Circle, RecordingInfo | None, Visualization, DarkFieldCorrection | None] | None,
        parameters: ROIParameters,
        progress: Callable[[float], None],
        should_continue: Callable[[], bool],
    ) -> ROIResidenceResult | None:
        if inputs is None:
            return None
        reader, roi, info, visualization, correction = inputs
        fps = info.fps if info else 15.0
        frames = reader.iter_frames()
        if visualization.dark_field and correction is not None:
            frames = (correction.apply(frame) for frame in frames)
        result = analyze_roi_residence_stream(
            frames,
            roi,
            parameters,
            fps,
            reader.frame_count,
            progress,
            should_continue,
        )
        if result.time.size == 0:
            return None
        return result


class _TimingSignals(QObject):
    finished = Signal(int, int, object)
    failed = Signal(int, int, object)


class _TimingTask(QRunnable):
    def __init__(self, generation: int, panel_index: int, panel: RecordingPanel) -> None:
        super().__init__()
        self.generation = generation
        self.panel_index = panel_index
        self.reader = panel._reader
        self.fps = panel.info.fps if panel.info is not None else 15.0
        self.signals = _TimingSignals()
        self.cancelled = False

    def run(self) -> None:
        if self.cancelled or self.reader is None:
            self.signals.finished.emit(self.generation, self.panel_index, None)
            return
        try:
            result = detect_injection_timing(
                self.reader.iter_frames(),
                self.fps,
                lambda: not self.cancelled,
            )
        except Exception as error:  # pragma: no cover - defensive worker boundary
            self.signals.failed.emit(self.generation, self.panel_index, error)
            return
        self.signals.finished.emit(
            self.generation,
            self.panel_index,
            result if not self.cancelled else None,
        )


class AnalysisPage(QWidget):
    def __init__(
        self,
        live_dir: Path,
        correction: DarkFieldCorrection | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._compare = False
        self._analysis_generations = [0, 0]
        self._analysis_tasks: set[_AnalysisTask] = set()
        self._published_results: dict[int, ROIResidenceResult | None] = {}
        self._timing_generations = [0, 0]
        self._timing_tasks: set[_TimingTask] = set()
        self._timing_results: dict[int, TimingAlignmentResult] = {}
        self._analysis_pool = QThreadPool(self)
        self._analysis_pool.setMaxThreadCount(4)

        self.panel_a = RecordingPanel(live_dir, correction)
        self.panel_a.set_roi_color(TRACE_A)
        self.panel_b = RecordingPanel(live_dir, correction)
        self.panel_b.set_roi_color(TRACE_B)

        self.playback_bar = PlaybackBar()
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance)

        pipeline_drawer = ScrollableColumn(self._build_pipeline_drawer())
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

        for panel_index, panel in enumerate((self.panel_a, self.panel_b)):
            panel.roiPlaced.connect(
                lambda roi, index=panel_index: self._on_roi_placed(index, roi)
            )
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

        timing_definition = STAGE_REGISTRY["timing_alignment"]
        self.timing_stage = StageDrawer(timing_definition.display_name)
        self.timing_stage.enabledChanged.connect(self._on_timing_stage_enabled)
        timing_hint = QLabel(timing_definition.description)
        timing_hint.setObjectName("subtleLabel")
        timing_hint.setWordWrap(True)
        self.timing_stage.content_layout.addWidget(timing_hint)
        self.timing_stage.set_expanded(True)
        layout.addWidget(self.timing_stage)

        definition = STAGE_REGISTRY["roi_analysis"]
        self.stage = StageDrawer(definition.display_name)
        self.stage.enabledChanged.connect(self._on_stage_enabled)
        self._build_stage_controls(self.stage, definition.description)
        layout.addWidget(self.stage)

        self.visualization_panel = VisualizationPanel(
            show_rotation=True,
            show_secondary_rotation=True,
        )
        self.visualization_panel.set_dark_field_available(self.panel_a._correction is not None)
        self.visualization_panel.changed.connect(self._on_visualization_changed)
        self.visualization_panel.trimPlaybackChanged.connect(self._on_trim_playback_changed)
        self.visualization_panel.rotationChanged.connect(self._on_rotation_changed)
        self.visualization_panel.secondaryRotationChanged.connect(
            self._on_secondary_rotation_changed
        )
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

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self._add_param(grid, 0, "ROI radius (px)", self.radius_spin)
        self._add_param(grid, 1, "Baseline window (frames)", self.baseline_spin)
        self._add_param(grid, 2, "Clearance fraction", self.clearance_spin)
        stage.content_layout.addLayout(grid)

        self.radius_spin.valueChanged.connect(self._on_radius_changed)
        for widget in (self.baseline_spin, self.clearance_spin):
            widget.valueChanged.connect(lambda _value: self._run_analysis())

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
        self.run_button.setProperty("analysisRunning", False)
        self.run_button.clicked.connect(lambda _checked=False: self._run_analysis())
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
        self._curve_a = self.plot.plot(pen=pg.mkPen(TRACE_A, width=2.5), name="A")
        self._curve_b = self.plot.plot(pen=pg.mkPen(TRACE_B, width=2.5), name="B")
        layout.addWidget(self.plot, 1)
        return panel

    # -- mode -----------------------------------------------------------------
    def _set_compare(self, compare: bool) -> None:
        if compare == self._compare:
            return
        self._compare = compare
        self._apply_mode()
        self._sync_playback()
        self._publish_available_results()
        if compare:
            self._run_timing_alignment((1,))
        if (
            compare
            and 1 not in self._published_results
            and not any(task.panel_index == 1 and not task.cancelled for task in self._analysis_tasks)
        ):
            self._run_analysis((1,))

    def _apply_mode(self) -> None:
        self.panel_b.setVisible(self._compare)
        self.visualization_panel.set_secondary_rotation(self.panel_b.rotation)
        self.visualization_panel.set_comparison_rotation_visible(self._compare)
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
        counts = (
            end - start
            for panel_index, panel in enumerate((self.panel_a, self.panel_b))
            if panel in self._playback_panels()
            for start, end in (self._playback_bounds(panel_index, panel),)
        )
        return max(counts, default=0)

    def _playback_bounds(self, panel_index: int, panel: RecordingPanel) -> tuple[int, int]:
        if not self.visualization_panel.trim_playback.isChecked():
            return self._alignment_start(panel_index), panel.frame_count
        result = self._timing_results.get(panel_index)
        if result is None:
            return self._alignment_start(panel_index), panel.frame_count
        return result.playback_bounds(panel.frame_count)

    def _sync_playback(self, reset: bool = False) -> None:
        count = self._timeline_count()
        self.playback_bar.set_frame_count(count)
        index = 0 if reset else min(self.playback_bar.index(), max(0, count - 1))
        self._drive_index(index)

    def _drive_index(self, index: int) -> None:
        self.playback_bar.set_index(index)
        for panel_index, panel in enumerate((self.panel_a, self.panel_b)):
            if panel in self._playback_panels():
                start, _end = self._playback_bounds(panel_index, panel)
                panel.show_frame(index + start)

    def _alignment_start(self, panel_index: int) -> int:
        if not self.timing_stage.is_enabled():
            return 0
        result = self._timing_results.get(panel_index)
        return result.start_frame if result is not None else 0

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
        )

    # -- public ---------------------------------------------------------------
    def refresh_recordings(self) -> None:
        self._pause()
        self.panel_a.refresh_recordings()
        self.panel_b.refresh_recordings()
        self._sync_playback(reset=True)

    # -- handlers -------------------------------------------------------------
    def _on_stage_enabled(self, enabled: bool) -> None:
        for task in self._analysis_tasks:
            task.cancelled = True
        self._analysis_generations[0] += 1
        self._analysis_generations[1] += 1
        if not enabled:
            self._set_analysis_running(False)
        for panel in (self.panel_a, self.panel_b):
            panel.set_roi_editable(enabled)
        if enabled:
            self.stage.set_status("Click the aneurysm on each image to place the ROI.")
        else:
            self.stage.set_status(None)

    def _on_timing_stage_enabled(self, enabled: bool) -> None:
        self._pause()
        if enabled:
            self._run_timing_alignment()
        else:
            self.timing_stage.set_status(None)
            self._sync_playback(reset=True)
            self._publish_available_results()

    def _on_radius_changed(self, radius: int) -> None:
        for panel in (self.panel_a, self.panel_b):
            panel.set_roi_radius(radius)
        self._run_analysis()

    def _on_roi_placed(self, panel_index: int, roi: Circle) -> None:  # noqa: ARG002
        self._run_analysis((panel_index,))

    def _on_visualization_changed(self, visualization: Visualization) -> None:
        for panel in (self.panel_a, self.panel_b):
            panel.set_visualization(visualization.with_rotation(panel.rotation))

    def _on_trim_playback_changed(self, enabled: bool) -> None:  # noqa: ARG002
        self._pause()
        self._sync_playback(reset=True)

    def _on_rotation_changed(self, rotation: int) -> None:
        if self.panel_a.has_recording():
            self.panel_a.set_rotation(rotation, save=True)

    def _on_secondary_rotation_changed(self, rotation: int) -> None:
        if self._compare and self.panel_b.has_recording():
            self.panel_b.set_rotation(rotation, save=True)

    def set_correction(self, correction: DarkFieldCorrection | None) -> None:
        for panel in (self.panel_a, self.panel_b):
            panel.set_correction(correction)
        self.visualization_panel.set_dark_field_available(correction is not None)

    def _on_panel_a_opened(self, info: RecordingInfo) -> None:
        self._pause()
        self.visualization_panel.set_rotation(self.panel_a.rotation)
        self._published_results.pop(0, None)
        self._invalidate_timing(0)
        self._restore_timing(0, info)
        if self.panel_a.roi is not None:
            self.stage.enable_button.setChecked(True)
        self._legend.getLabel(self._curve_a).setText(info.name)
        frame = self.panel_a.current_frame
        if frame is not None:
            level, width = auto_window(frame)
            self.visualization_panel.apply_window(level, width)
        self._sync_playback(reset=True)
        self._run_timing_alignment((0,))
        self._load_or_run_analysis(0)

    def _on_panel_b_opened(self, info: RecordingInfo) -> None:
        self._pause()
        self.visualization_panel.set_secondary_rotation(self.panel_b.rotation)
        self._published_results.pop(1, None)
        self._invalidate_timing(1)
        self._restore_timing(1, info)
        if self.panel_b.roi is not None:
            self.stage.enable_button.setChecked(True)
        self._legend.getLabel(self._curve_b).setText(info.name)
        self._sync_playback(reset=True)
        self._run_timing_alignment((1,))
        self._load_or_run_analysis(1)

    def _on_panel_cleared(self, panel: RecordingPanel) -> None:
        panel_index = 0 if panel is self.panel_a else 1
        self._analysis_generations[panel_index] += 1
        for task in self._analysis_tasks:
            if task.panel_index == panel_index:
                task.cancelled = True
        self._published_results.pop(panel_index, None)
        self._invalidate_timing(panel_index)
        panel.frame_view._placeholder = "No recordings found"
        panel.frame_view.update()
        self._sync_playback(reset=True)
        self._clear_results()

    def _invalidate_timing(self, panel_index: int) -> None:
        self._timing_generations[panel_index] += 1
        self._timing_results.pop(panel_index, None)
        for task in self._timing_tasks:
            if task.panel_index == panel_index:
                task.cancelled = True

    def _restore_timing(self, panel_index: int, info: RecordingInfo) -> None:
        result = load_saved_timing_alignment(info.path)
        if result is not None:
            self._timing_results[panel_index] = result
            self.timing_stage.enable_button.setChecked(True)

    def _run_timing_alignment(self, panel_indices: tuple[int, ...] | None = None) -> None:
        if not self.timing_stage.is_enabled():
            return
        panels = (self.panel_a, self.panel_b)
        active_indices = (0, 1) if self._compare else (0,)
        indices = active_indices if panel_indices is None else panel_indices
        pending_indices = tuple(
            index
            for index in indices
            if panels[index].has_recording()
            and index not in self._timing_results
            and not any(
                task.panel_index == index and not task.cancelled for task in self._timing_tasks
            )
        )
        if not pending_indices:
            self._publish_available_results()
            return
        self.timing_stage.set_status("Detecting contrast injection...")
        self._publish_available_results()
        for panel_index in pending_indices:
            task = _TimingTask(self._timing_generations[panel_index], panel_index, panels[panel_index])
            task.signals.finished.connect(self._on_timing_completed)
            task.signals.failed.connect(self._timing_failed)
            self._timing_tasks.add(task)
            self._analysis_pool.start(task)

    def _on_timing_completed(
        self,
        generation: int,
        panel_index: int,
        result: TimingAlignmentResult | None,
    ) -> None:
        task = next(
            (
                candidate
                for candidate in self._timing_tasks
                if candidate.generation == generation and candidate.panel_index == panel_index
            ),
            None,
        )
        if task is not None:
            self._timing_tasks.remove(task)
        if generation != self._timing_generations[panel_index] or result is None:
            return
        self._timing_results[panel_index] = result
        panel = (self.panel_a, self.panel_b)[panel_index]
        if panel.info is not None:
            save_timing_alignment(panel.info.path, result)
        if self.timing_stage.is_enabled() and not any(
            not candidate.cancelled for candidate in self._timing_tasks
        ):
            active_count = 2 if self._compare else 1
            active_results = (self._timing_results.get(index) for index in range(active_count))
            if any(item is not None and item.injection_frame == 0 for item in active_results):
                self.timing_stage.set_status("No injection detected; recording left untrimmed.")
            else:
                self.timing_stage.set_status("Injection timing aligned to 5.00 s.")
        self._sync_playback(reset=True)
        self._publish_available_results()

    def _timing_failed(self, generation: int, panel_index: int, error: object) -> None:
        task = next(
            (
                candidate
                for candidate in self._timing_tasks
                if candidate.generation == generation and candidate.panel_index == panel_index
            ),
            None,
        )
        if task is not None:
            self._timing_tasks.remove(task)
        if generation == self._timing_generations[panel_index]:
            self.timing_stage.set_status(f"Timing alignment failed: {error}", is_error=True)

    def _load_or_run_analysis(self, panel_index: int) -> None:
        panel = (self.panel_a, self.panel_b)[panel_index]
        result = (
            load_saved_analysis_result(panel.info.path, self._parameters())
            if panel.info is not None
            else None
        )
        if result is None:
            self._run_analysis((panel_index,))
            return

        self._analysis_generations[panel_index] += 1
        for task in self._analysis_tasks:
            if task.panel_index == panel_index:
                task.cancelled = True
        self._published_results[panel_index] = result
        panel.frame_view.set_roi_processing(False)
        self._set_analysis_running(any(not task.cancelled for task in self._analysis_tasks))
        self._publish_available_results()

    def _run_analysis(self, panel_indices: tuple[int, ...] | None = None) -> None:
        if not self.stage.is_enabled():
            return
        all_panels = (self.panel_a, self.panel_b)
        active_indices = (0, 1) if self._compare else (0,)
        available_indices = tuple(index for index in active_indices if all_panels[index].has_recording())
        if not available_indices:
            self._set_analysis_running(False)
            self._clear_results()
            return
        indices = available_indices if panel_indices is None else panel_indices
        indexed_panels = tuple((index, all_panels[index]) for index in indices if index in available_indices)
        if not indexed_panels:
            return
        self._set_analysis_running(True)
        parameters = self._parameters()
        for panel_index, panel in indexed_panels:
            self._analysis_generations[panel_index] += 1
            generation = self._analysis_generations[panel_index]
            for previous in self._analysis_tasks:
                if previous.panel_index == panel_index:
                    previous.cancelled = True
            if panel.roi is not None:
                panel.frame_view.set_roi_processing(True)
            task = _AnalysisTask(generation, panel_index, panel, parameters)
            task.signals.finished.connect(self._on_analysis_completed)
            task.signals.progress.connect(self._on_analysis_progress)
            task.signals.failed.connect(self._analysis_failed)
            self._analysis_tasks.add(task)
            self._analysis_pool.start(task)

    def _on_analysis_completed(
        self,
        generation: int,
        panel_index: int,
        result: ROIResidenceResult | None,
    ) -> None:
        task = next(
            (
                candidate
                for candidate in self._analysis_tasks
                if candidate.generation == generation and candidate.panel_index == panel_index
            ),
            None,
        )
        if task is not None:
            self._analysis_tasks.remove(task)
        if generation != self._analysis_generations[panel_index]:
            return
        self._published_results[panel_index] = result
        panel = (self.panel_a, self.panel_b)[panel_index]
        if result is not None and panel.info is not None:
            save_analysis_result(panel.info.path, result)
        panel.frame_view.set_roi_processing(False)
        self._set_analysis_running(any(not candidate.cancelled for candidate in self._analysis_tasks))
        self._publish_available_results()

    def _publish_available_results(self) -> None:
        def ready_result(panel_index: int) -> ROIResidenceResult | None:
            if self.timing_stage.is_enabled() and panel_index not in self._timing_results:
                return None
            return self._published_results.get(panel_index)

        self._apply_analysis_results(
            ready_result(0),
            ready_result(1),
        )

    def _apply_analysis_results(
        self,
        result_a: ROIResidenceResult | None,
        result_b: ROIResidenceResult | None,
    ) -> None:
        if result_a is not None:
            self._set_aligned_curve(self._curve_a, 0, result_a)
        else:
            self._curve_a.setData([], [])
        if result_b is not None:
            self._set_aligned_curve(self._curve_b, 1, result_b)
        elif self._compare:
            self._curve_b.setData([], [])

        self._update_cards(result_a, result_b)

    def _set_aligned_curve(self, curve: object, panel_index: int, result: ROIResidenceResult) -> None:
        start_frame = self._alignment_start(panel_index)
        time = result.time[start_frame:]
        if time.size:
            time = time - time[0]
        curve.setData(time, result.contrast[start_frame:])

    def _analysis_failed(self, generation: int, panel_index: int, error: object) -> None:
        task = next(
            (
                candidate
                for candidate in self._analysis_tasks
                if candidate.generation == generation and candidate.panel_index == panel_index
            ),
            None,
        )
        if task is not None:
            self._analysis_tasks.remove(task)
        if generation == self._analysis_generations[panel_index]:
            (self.panel_a, self.panel_b)[panel_index].frame_view.set_roi_processing(False)
            self._set_analysis_running(any(not candidate.cancelled for candidate in self._analysis_tasks))
            self.stage.set_status(f"Analysis failed: {error}")

    def _on_analysis_progress(self, generation: int, panel_index: int, progress: float) -> None:
        if generation != self._analysis_generations[panel_index]:
            return
        (self.panel_a, self.panel_b)[panel_index].frame_view.set_roi_processing(True, progress)

    def _set_analysis_running(self, running: bool) -> None:
        self.run_button.setProperty("analysisRunning", running)
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)
        self.run_button.update()

    def _update_cards(
        self,
        a: ROIResidenceResult | None,
        b: ROIResidenceResult | None,
    ) -> None:
        if a is None:
            if b is None:
                self._clear_results()
                return
            self.peak_card.set_value("--", f"B {b.peak_contrast:.1f}")
            self.time_to_peak_card.set_value("--", f"B {b.time_to_peak:.2f} s")
            self.residence_card.set_value("--", f"B {b.residence_time:.2f} s")
            self.baseline_card.set_value("--", f"B {b.baseline:.0f} from {b.baseline_start_time:.2f} s")
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
        baseline_detail = (
            f"B {b.baseline:.0f} from {b.baseline_start_time:.2f} s"
            if self._compare and b is not None
            else "B --"
            if self._compare
            else f"from {a.baseline_start_time:.2f} s"
        )
        self.baseline_card.set_value(f"{a.baseline:.0f}", baseline_detail)

    def _clear_results(self) -> None:
        self._curve_a.setData([], [])
        self._curve_b.setData([], [])
        for card in (self.peak_card, self.time_to_peak_card, self.residence_card, self.baseline_card):
            card.set_value("--")

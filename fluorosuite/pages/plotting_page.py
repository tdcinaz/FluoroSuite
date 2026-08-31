"""Batch plotting page for timing-aligned ROI analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..pipeline import ROIParameters, ROIResidenceResult, analyze_roi_residence_stream
from ..recordings import (
    RecordingInfo,
    RecordingReader,
    list_recordings,
    load_saved_roi,
    load_saved_timing_alignment,
)

_TRACE_COLORS = (
    "#38bdf8",
    "#f5a25d",
    "#2dd4bf",
    "#f472b6",
    "#a3e635",
    "#facc15",
    "#c084fc",
    "#fb7185",
    "#60a5fa",
    "#34d399",
)


@dataclass(slots=True)
class _RecordingRow:
    info: RecordingInfo
    checkbox: QCheckBox
    status: QLabel


class _PlotAnalysisSignals(QObject):
    finished = Signal(object, object, object)
    failed = Signal(object, object, object)
    progress = Signal(object, object, float)


class _PlotAnalysisTask(QRunnable):
    def __init__(
        self,
        path: Path,
        cache_key: tuple[object, ...],
        parameters: ROIParameters,
    ) -> None:
        super().__init__()
        self.path = path
        self.cache_key = cache_key
        self.parameters = parameters
        self.signals = _PlotAnalysisSignals()

    def run(self) -> None:
        try:
            roi = load_saved_roi(self.path)
            timing = load_saved_timing_alignment(self.path)
            if roi is None or timing is None:
                raise ValueError("ROI or timing metadata changed while analysis was running")
            reader = RecordingReader(self.path)
            result = analyze_roi_residence_stream(
                reader.iter_frames(),
                roi,
                self.parameters,
                timing.fps,
                reader.frame_count,
                lambda value: self.signals.progress.emit(self.path, self.cache_key, value),
            )
            if result.time.size == 0:
                raise ValueError("recording contains no readable frames")
        except Exception as error:  # pragma: no cover - defensive worker boundary
            self.signals.failed.emit(self.path, self.cache_key, error)
            return
        self.signals.finished.emit(self.path, self.cache_key, result)


class PlottingPage(QWidget):
    """Plot cached ROI analysis for any number of recordings in one folder."""

    def __init__(self, live_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._directory = Path(live_dir)
        self._parameters = ROIParameters()
        self._rows: dict[Path, _RecordingRow] = {}
        self._curves: dict[Path, pg.PlotDataItem] = {}
        self._cache: dict[tuple[object, ...], ROIResidenceResult] = {}
        self._tasks: dict[Path, _PlotAnalysisTask] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_recording_panel())
        splitter.addWidget(self._build_plot_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 1100])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(splitter)
        self.refresh_recordings()

    def _build_recording_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(460)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Recordings")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_edit = QLineEdit(str(self._directory))
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setToolTip("Folder containing raw recordings and JSON sidecars")
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        self.count_label = QLabel()
        self.count_label.setObjectName("subtleLabel")
        layout.addWidget(self.count_label)

        self.recording_list = QWidget()
        self.recording_layout = QVBoxLayout(self.recording_list)
        self.recording_layout.setContentsMargins(0, 0, 0, 0)
        self.recording_layout.setSpacing(8)
        self.recording_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.recording_list)
        layout.addWidget(scroll, 1)

        self.status_label = QLabel("Select recordings to add them to the plot.")
        self.status_label.setObjectName("subtleLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return panel

    def _build_plot_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Timing-aligned ROI contrast")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setBackground("#0b1018")
        self.plot.setLabel("bottom", "Time from aligned start", units="s")
        self.plot.setLabel("left", "Contrast (baseline - ROI)")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.addLegend(offset=(-10, 10))
        layout.addWidget(self.plot, 1)
        return panel

    def _browse_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select recordings folder", str(self._directory))
        if not selected:
            return
        self._directory = Path(selected)
        self.folder_edit.setText(selected)
        self.refresh_recordings()

    def refresh_recordings(self) -> None:
        visible_paths = {path for path, row in self._rows.items() if row.checkbox.isChecked()}
        for curve in self._curves.values():
            self.plot.removeItem(curve)
        self._curves.clear()
        self._rows.clear()
        while self.recording_layout.count() > 1:
            item = self.recording_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        recordings = list_recordings(self._directory)
        self.count_label.setText(f"{len(recordings)} recordings")
        for info in recordings:
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)
            checkbox = QCheckBox(info.label())
            status = QLabel("Hidden")
            status.setObjectName("subtleLabel")
            row_layout.addWidget(checkbox)
            row_layout.addWidget(status)
            self.recording_layout.insertWidget(self.recording_layout.count() - 1, row_widget)
            row = _RecordingRow(info, checkbox, status)
            self._rows[info.path] = row
            checkbox.toggled.connect(
                lambda visible, path=info.path: self._set_recording_visible(path, visible)
            )
            if info.path in visible_paths:
                checkbox.setChecked(True)

        if recordings:
            self.status_label.setText("Select recordings to add them to the plot.")
        else:
            self.status_label.setText("No .raw recordings were found in this folder.")

    def _set_recording_visible(self, path: Path, visible: bool) -> None:
        row = self._rows.get(path)
        if row is None:
            return
        curve = self._curves.get(path)
        if not visible:
            if curve is not None:
                curve.setVisible(False)
            row.status.setText("Ready" if self._cached_result(path) is not None else "Hidden")
            return

        missing = self._metadata_error(path)
        if missing is not None:
            row.status.setObjectName("errorLabel")
            row.status.setText(missing)
            row.checkbox.blockSignals(True)
            row.checkbox.setChecked(False)
            row.checkbox.blockSignals(False)
            self.status_label.setObjectName("errorLabel")
            self.status_label.setText(f"{row.info.name}: {missing}")
            self._refresh_style(row.status)
            self._refresh_style(self.status_label)
            return

        self._set_normal_status(row.status, "Ready")
        self._set_normal_status(self.status_label, f"Showing {row.info.name}")
        cached = self._cached_result(path)
        if cached is not None:
            self._show_result(path, cached)
            return
        if path in self._tasks:
            row.status.setText("Computing...")
            return

        cache_key = self._cache_key(path)
        task = _PlotAnalysisTask(path, cache_key, self._parameters)
        task.signals.progress.connect(self._analysis_progress)
        task.signals.finished.connect(self._analysis_finished)
        task.signals.failed.connect(self._analysis_failed)
        self._tasks[path] = task
        row.status.setText("Computing... 0%")
        self._pool.start(task)

    def _metadata_error(self, path: Path) -> str | None:
        if load_saved_roi(path) is None:
            return "Missing or invalid saved ROI"
        timing = load_saved_timing_alignment(path)
        if timing is None:
            return "Missing or invalid timing alignment"
        try:
            frame_count = RecordingReader(path).frame_count
        except OSError:
            return "Recording cannot be read"
        if timing.start_frame >= frame_count:
            return "Timing start frame is outside the recording"
        return None

    def _cache_key(self, path: Path) -> tuple[object, ...]:
        sidecar = path.with_suffix(".json")
        raw_stat = path.stat()
        sidecar_stat = sidecar.stat()
        return (
            path.resolve(),
            raw_stat.st_size,
            raw_stat.st_mtime_ns,
            sidecar_stat.st_size,
            sidecar_stat.st_mtime_ns,
            self._parameters,
        )

    def _cached_result(self, path: Path) -> ROIResidenceResult | None:
        try:
            return self._cache.get(self._cache_key(path))
        except OSError:
            return None

    def _analysis_progress(self, path: Path, cache_key: tuple[object, ...], progress: float) -> None:
        task = self._tasks.get(path)
        row = self._rows.get(path)
        if task is not None and task.cache_key == cache_key and row is not None:
            row.status.setText(f"Computing... {progress:.0%}")

    def _analysis_finished(
        self,
        path: Path,
        cache_key: tuple[object, ...],
        result: ROIResidenceResult,
    ) -> None:
        task = self._tasks.get(path)
        if task is None or task.cache_key != cache_key:
            return
        self._tasks.pop(path, None)
        self._cache[cache_key] = result
        row = self._rows.get(path)
        if row is None:
            return
        self._set_normal_status(row.status, "Ready")
        if row.checkbox.isChecked():
            self._show_result(path, result)

    def _analysis_failed(self, path: Path, cache_key: tuple[object, ...], error: object) -> None:
        task = self._tasks.get(path)
        if task is None or task.cache_key != cache_key:
            return
        self._tasks.pop(path, None)
        row = self._rows.get(path)
        if row is None:
            return
        row.checkbox.blockSignals(True)
        row.checkbox.setChecked(False)
        row.checkbox.blockSignals(False)
        row.status.setObjectName("errorLabel")
        row.status.setText(f"Analysis failed: {error}")
        self.status_label.setObjectName("errorLabel")
        self.status_label.setText(f"{row.info.name}: analysis failed: {error}")
        self._refresh_style(row.status)
        self._refresh_style(self.status_label)

    def _show_result(self, path: Path, result: ROIResidenceResult) -> None:
        timing = load_saved_timing_alignment(path)
        row = self._rows.get(path)
        if timing is None or row is None:
            return
        time = result.time[timing.start_frame :]
        if time.size:
            time = time - time[0]
        contrast = result.contrast[timing.start_frame :]
        curve = self._curves.get(path)
        if curve is None:
            index = list(self._rows).index(path)
            pen = pg.mkPen(_TRACE_COLORS[index % len(_TRACE_COLORS)], width=2)
            curve = self.plot.plot(time, contrast, pen=pen, name=path.stem)
            self._curves[path] = curve
        else:
            curve.setData(time, contrast)
            curve.setVisible(True)

    def _set_normal_status(self, label: QLabel, text: str) -> None:
        label.setObjectName("subtleLabel")
        label.setText(text)
        self._refresh_style(label)

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
"""FluoroSuite application: unified capture, playback, and analysis window."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from .capture import LatestFrame, PreviewStore, Recorder, StreamReceiver
from .config import DARK_FIELD_FILE, LIVE_DIR, STREAM_HOST, STREAM_PORT
from .pages import AnalysisPage, CapturePage, PlaybackPage, PlottingPage
from .theme import STYLESHEET
from .visualization import DarkFieldCorrection


class MainWindow(QMainWindow):
    def __init__(self, stream_host: str, stream_port: int) -> None:
        super().__init__()
        self.setWindowTitle("FluoroSuite")
        self.resize(1500, 940)

        LIVE_DIR.mkdir(parents=True, exist_ok=True)
        self._correction = DarkFieldCorrection.load(DARK_FIELD_FILE)

        self._latest = LatestFrame()
        self._store = PreviewStore()
        self._recorder = Recorder(LIVE_DIR)
        self._receiver = StreamReceiver(self._latest, self._store, self._recorder, stream_host, stream_port)
        self._receiver.start()

        self.capture_page = CapturePage(self._latest, self._store, self._recorder, self._correction)
        self.playback_page = PlaybackPage(LIVE_DIR, self._correction)
        self.analysis_page = AnalysisPage(LIVE_DIR, self._correction)
        self.plotting_page = PlottingPage(LIVE_DIR)
        self.capture_page.calibrated.connect(self._on_calibrated)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.capture_page, "Capture")
        self.tabs.addTab(self.playback_page, "Playback")
        self.tabs.addTab(self.analysis_page, "Analysis")
        self.tabs.addTab(self.plotting_page, "Plotting")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        self.statusBar().showMessage(f"Listening for camera stream on {stream_host}:{stream_port}")
        self.capture_page.start()

    def _on_calibrated(self, correction: DarkFieldCorrection) -> None:
        self._correction = correction
        self.playback_page.set_correction(correction)
        self.analysis_page.set_correction(correction)

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.capture_page:
            self.capture_page.start()
        else:
            self.capture_page.stop()
        if widget is self.playback_page:
            self.playback_page.refresh_recordings()
        elif widget is self.analysis_page:
            self.analysis_page.refresh_recordings()
        elif widget is self.plotting_page:
            self.plotting_page.refresh_recordings()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._recorder.set_enabled(False)
        self.capture_page.shutdown()
        self._receiver.stop()
        super().closeEvent(event)


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified fluoroscopy suite")
    parser.add_argument("--stream-host", default=STREAM_HOST, help="Bind address for the raw GVSP stream")
    parser.add_argument("--stream-port", type=int, default=STREAM_PORT, help="Bind port for the raw GVSP stream")
    arguments = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(arguments.stream_host, arguments.stream_port)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

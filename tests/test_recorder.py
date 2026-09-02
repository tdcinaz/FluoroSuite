from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from fluorosuite.capture.recorder import Recorder
from fluorosuite.config import COLUMNS, PIXEL_BYTES, ROWS
from fluorosuite.recordings import list_recordings


def frame_with_exposure_fraction(fraction: float) -> bytes:
    frame = np.zeros((ROWS, COLUMNS), dtype="<u2")
    sample = frame[::8, ::8]
    sample.flat[: round(fraction * sample.size)] = 2048
    return frame.tobytes()


class RecorderTests(unittest.TestCase):
    def test_metadata_spans_first_to_last_written_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            recorder = Recorder(directory)
            recorder.set_enabled(True)
            frame_times = [100.0 + index / 30.0 for index in range(17)]

            with patch("fluorosuite.capture.recorder.time.time", side_effect=frame_times):
                for _ in range(16):
                    recorder.capture(frame_with_exposure_fraction(0.32))
                recorder.capture(frame_with_exposure_fraction(0.0))

            raw_path = next(directory.glob("*.raw"))
            metadata = json.loads(raw_path.with_suffix(".json").read_text())
            self.assertEqual(metadata["started"], frame_times[0])
            self.assertEqual(metadata["ended"], frame_times[15])
            self.assertEqual(metadata["ended_at"], "1970-01-01T00:01:40.500000+00:00")
            self.assertEqual(metadata["fps"], 30.0)
            self.assertAlmostEqual(list_recordings(directory)[0].fps, 30.0)

    def test_discards_opening_and_closing_diaphragm_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            recorder = Recorder(directory)
            recorder.set_enabled(True)

            for fraction in (0.05, 0.10, 0.15, 0.20, 0.25, 0.28, 0.30):
                recorder.capture(frame_with_exposure_fraction(fraction))
            for _ in range(16):
                recorder.capture(frame_with_exposure_fraction(0.32))
            recorder.capture(frame_with_exposure_fraction(0.10))
            recorder.capture(frame_with_exposure_fraction(0.0))

            raw_path = next(directory.glob("*.raw"))
            metadata = json.loads(raw_path.with_suffix(".json").read_text())
            self.assertEqual(raw_path.stat().st_size, 16 * PIXEL_BYTES)
            self.assertEqual(metadata["frames"], 16)
            self.assertEqual(metadata["data_file"], raw_path.with_suffix(".csv").name)


if __name__ == "__main__":
    unittest.main()
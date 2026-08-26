"""Per-exposure recorder writing raw runs plus JSON metadata sidecars.

Ported from the legacy Fluoro recorder. While auto-recording is enabled, each
fluoroscopy exposure is written to its own .raw run; recording stops automatically
when the exposure ends.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import COLUMNS, PIXEL_BYTES, ROWS
from .receiver import is_exposure

_FILENAME_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


class Recorder:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.lock = threading.Lock()
        self.file = None
        self.meta_path: Path | None = None
        self.path: Path | None = None
        self.frames = 0
        self.started: float | None = None
        self.enabled = False
        self.naming = {"prefix": "BDL", "trial": "A0", "phase": "pre"}

    @staticmethod
    def _validate_component(value: object, label: str) -> str:
        if not isinstance(value, str) or not _FILENAME_COMPONENT.fullmatch(value):
            raise ValueError(f"{label} must contain only letters, numbers, dots, or hyphens")
        return value

    def _next_paths_locked(self) -> tuple[Path, Path]:
        stem = "{prefix}_{trial}_{phase}_".format(**self.naming)
        index = 0
        while True:
            raw_path = self.directory / (stem + str(index) + ".raw")
            meta_path = self.directory / (stem + str(index) + ".json")
            if not raw_path.exists() and not meta_path.exists():
                return raw_path, meta_path
            index += 1

    def update_naming(self, prefix: str, trial: str, phase: str) -> dict:
        with self.lock:
            prefix = self._validate_component(prefix, "prefix")
            trial = self._validate_component(trial, "trial")
            if phase not in ("pre", "post"):
                raise ValueError("phase must be pre or post")
            self.naming = {"prefix": prefix, "trial": trial, "phase": phase}
            return self._state_locked()

    def set_enabled(self, enabled: bool) -> dict:
        with self.lock:
            self.enabled = enabled
            if not enabled:
                self._stop_locked()
            return self._state_locked()

    def capture(self, pixels: bytes) -> None:
        with self.lock:
            if not self.enabled:
                return
        exposure = is_exposure(pixels)
        with self.lock:
            if not self.enabled:
                return
            if not exposure:
                self._stop_locked()
                return
            if self.file is None:
                self._start_locked()
            self.file.write(pixels)
            self.frames += 1

    def _start_locked(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path, self.meta_path = self._next_paths_locked()
        self.file = open(self.path, "wb", buffering=1024 * 1024)
        self.frames = 0
        self.started = time.time()
        self._write_meta_locked(None)

    def _stop_locked(self) -> None:
        if self.file is None:
            return
        self.file.flush()
        self.file.close()
        self.file = None
        self._write_meta_locked(time.time())

    def _write_meta_locked(self, ended: float | None) -> None:
        assert self.path is not None and self.meta_path is not None
        meta = {
            "file": self.path.name,
            "rows": ROWS,
            "columns": COLUMNS,
            "dtype": "<u2",
            "bits": 14,
            "frame_bytes": PIXEL_BYTES,
            "frames": self.frames,
            "started": self.started,
            "started_at": datetime.fromtimestamp(self.started, timezone.utc).isoformat() if self.started else None,
            "ended": ended,
        }
        temporary = self.meta_path.with_name(self.meta_path.name + ".tmp")
        temporary.write_text(json.dumps(meta, indent=2))
        temporary.replace(self.meta_path)

    def _state_locked(self) -> dict:
        active = self.file is not None
        return {
            "recording": active,
            "auto_recording": self.enabled,
            "frames": self.frames,
            "seconds": round(time.time() - self.started, 1) if active and self.started else 0.0,
            "preview": (self.path if active else self._next_paths_locked()[0]).name,
        }

    def state(self) -> dict:
        with self.lock:
            return self._state_locked()

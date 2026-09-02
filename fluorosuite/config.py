"""Shared constants for the fluoroscopy suite.

Frame geometry and network endpoints mirror the legacy Fluoro capture daemon so
recordings and the GigE Vision stream remain compatible.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPTURES_DIR = ROOT / "captures"
LIVE_DIR = CAPTURES_DIR / "live"
EXPORT_DIR = CAPTURES_DIR / "exports"
CALIBRATION_DIR = CAPTURES_DIR / "calibration"
DARK_FIELD_FILE = CALIBRATION_DIR / "dark-field.npz"
SETTINGS_FILE = CAPTURES_DIR / ".cache.json"

# Frame geometry of the reconstructed GVSP frame.
ROWS = 1024
COLUMNS = 1024
PIXEL_BYTES = ROWS * COLUMNS * 2
BITS = 14
MAX_VALUE = (1 << BITS) - 1  # 16383
LUT_SIZE = MAX_VALUE + 1
CAPTURE_FPS = 30.0

# Network endpoints (see legacy Fluoro network_setup.txt). The raw GVSP stream is
# the active path; the push receiver is retained for compatibility.
STREAM_HOST = "10.200.0.1"
STREAM_PORT = 5802
PUSH_PORT = 5801

# Live 8-bit preview served to other machines on the LAN as MJPEG over HTTP.
PREVIEW_STREAM_HOST = "0.0.0.0"
PREVIEW_STREAM_PORT = 8089
PREVIEW_JPEG_QUALITY = 80

MAX_STREAM_PACKET = 65535
MAX_FRAME_SIZE = 4 * 1024 * 1024
GVCP_CONTROL_PORT = 3956  # never parse the control channel as GVSP stream data

# Exposure detection for auto-recording.
EXPOSURE_BRIGHT_LEVEL = 1024
EXPOSURE_FRACTION = 0.01

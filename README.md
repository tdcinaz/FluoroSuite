# FluoroSuite

A unified desktop application for benchtop aneurysm fluoroscopy work. It combines
the live GigE Vision camera capture, recorded-run playback, and contrast residence
analysis into a single PySide6 interface with three tabs:

- **Capture** — receives the forwarded raw GVSP stream, reconstructs 1024×1024
  16-bit frames, applies window/level for viewing, and records each exposure to a
  `.raw` run with a JSON sidecar.
- **Playback** — reviews recorded runs with a scrub/transport bar and window/level.
- **Analysis** — measures aneurysm contrast residence from a circular ROI and
  inlet brightness from a fixed rectangular ROI.

The capture engine and on-disk recording format are compatible with the legacy
Fluoro daemon, so existing recordings in `captures/live/` open directly. Disable
the standalone Fluoro live-capture daemon before running this suite, since both
bind the same GVSP stream endpoint.

## Run

```bash
uv sync
uv run fluorosuite
```

By default the app binds the raw GVSP stream on `10.200.0.1:5802` (the WireGuard
endpoint on the workstation, matching the network topology). Override with:

```bash
uv run fluorosuite --stream-host 0.0.0.0 --stream-port 5802
```

## Video export

Exported MP4 files use the first usable native H.264 encoder detected for the
host: VideoToolbox on macOS, NVENC/QSV/AMF/Media Foundation on Windows, or
NVENC/QSV/VAAPI/V4L2 M2M on Linux. Each candidate performs a short hardware
encode probe before it is selected; `libx264` is used when no GPU backend works.
Hardware bitrates scale with frame size and rate from 100 Mbps at 1024×1024 and
30 fps to preserve the quality of the existing CRF 18 exports.

```bash
uv run fluorosuite-export --overwrite
uv run fluorosuite-export --encoder software
uv run fluorosuite-export --encoder videotoolbox
```

Use `--encoder` with `auto`, `software`, `videotoolbox`, `nvenc`, `qsv`, `amf`,
`mediafoundation`, `vaapi`, or `v4l2m2m`. On Linux, set
`FLUOROSUITE_VAAPI_DEVICE` when the desired render node is not the first
`/dev/dri/renderD*` device.

## Recording format

Each run is a flat file of concatenated 1024×1024 little-endian 16-bit (14-bit
significant) frames, with a JSON sidecar describing geometry, frame count, and
timing. The sidecar's `data_file` field names the corresponding CSV containing
`time_s`, `roi_mean`, and `inlet_mean`; contrast and summary metrics are
calculated when the data is loaded. Recordings are written to `captures/live/`.

## Contrast residence

Iodinated contrast attenuates X-rays and appears dark, so the residence signal is
measured inside the ROI as `baseline − current` mean brightness. The analysis
reports baseline level, peak contrast, time to peak, and residence time.

## Architecture

- `fluorosuite/capture/` — GVSP stream reassembly (`receiver.py`) and per-exposure
  recording (`recorder.py`).
- `fluorosuite/pipeline/` — frontend-neutral pipeline contracts and ROI analysis
  stages.
- `fluorosuite/widgets/` — reusable frame view, visualization panel, transport
  bar, and collapsible stage drawer.
- `fluorosuite/pages/` — the capture, playback, and analysis pages.
- `fluorosuite/app.py` — the tabbed main window and entry point.

Not for diagnostic use.

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

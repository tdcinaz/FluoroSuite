---
description: "UI/UX design standards for FluoroSuite's PySide6 interface — cohesive theming, flexible layout, responsiveness, and a high-quality medical-research look. Applied when editing pages, widgets, or the theme."
applyTo: "fluorosuite/pages/**,fluorosuite/widgets/**,fluorosuite/theme.py"
---
# FluoroSuite UI Design Standards

FluoroSuite must read as **high-quality medical research software**: calm, precise, and trustworthy. Favor clarity and restraint over decoration. Every screen should look deliberate, aligned, and consistent with the rest of the app.

## Cohesive & consistent
- Drive all styling from the shared dark theme in [fluorosuite/theme.py](fluorosuite/theme.py). Do **not** hardcode colors, borders, or fonts in widget code — add or reuse a rule in the global `STYLESHEET` and select it via `setObjectName(...)`.
- Reuse existing object-name styles instead of inventing near-duplicates: `card`, `metricCard`, `drawer`, `stageDrawer` (containers); `primaryButton`, `modeButton`, `recordButton` (buttons); `panelTitle`, `sectionTitle`, `subtleLabel`, `metricTitle`, `metricValue`, `metricDetail`, `statusValue` (text). If a new pattern is truly needed, add one named style and reuse it everywhere.
- Keep the palette disciplined: teal accent (`ACCENT #14b8a6`) for primary/active affordances, cyan (`#67e8f9`) for live values and slider handles, `ROI_COLOR`/`TRACE_A`/`TRACE_B` for overlays and plot traces. Reserve red (`#7f1d1d` / `#f87171`) exclusively for recording and destructive/error states.
- Group related controls in `card`/`GroupBox` containers with titles. Establish a clear visual hierarchy: `panelTitle` → `sectionTitle` → body. Maintain consistent spacing — 12–16px between sections, 6–8px within a control cluster.
- Align labels, inputs, and buttons to a shared grid. Prefer `QGridLayout`/`QFormLayout` for parameter panels so columns line up across cards.

## Flexible layout
- Compose with layouts, stretch factors, and size policies — never with absolute positioning. Use `addStretch()` and layout stretch weights so content reflows as the window resizes (default window is 1500×940 but must degrade gracefully when smaller).
- The image/plot viewport is the priority region: give it `addWidget(view, 1)` (or an expanding size policy) so it grows while side panels stay a sensible fixed or bounded width.
- Prefer bounded side panels (`setMaximumWidth`/`setFixedWidth` only for genuinely fixed rails like the ~300px side card) over hardcoding pixel sizes on content that should flex. Avoid `setFixedSize` on anything the user might resize.
- Use `QSplitter` for side-by-side comparison and any region where the user benefits from reclaiming space; give panes sensible initial stretch and non-zero minimums so nothing collapses to zero.
- Set `setContentsMargins` and `setSpacing` explicitly and consistently (outer margins ~16px, inner card padding ~12px) rather than relying on platform defaults.

## Responsive feel
- Never block the Qt main thread. Keep frame reconstruction, file I/O, and analysis off the GUI thread (worker threads / the existing receiver + recorder pattern) and marshal results back via signals.
- Drive live UI updates with `QTimer` at a steady cadence; coalesce high-frequency stream updates so paints stay smooth and the UI never stutters.
- Every user action gives immediate feedback: button `:hover`/`:checked` states, status-bar messages, and clear enabled/disabled states. Disable controls that aren't valid in the current state instead of letting them fail.
- Provide honest empty, loading, and error states (e.g. no recordings, no stream yet) rather than blank panels. Use `QMessageBox` only for genuine decisions/errors, not routine feedback.
- Keep interactions snappy: debounce expensive recomputation triggered by sliders/spinboxes so dragging feels live without recomputing on every tick.

## Medical-research polish
- Numbers are the product: right-align measured values, show consistent units and precision, and use the `metricValue`/`metricDetail` styles so readings are legible at a glance.
- Keep labels precise and clinical; avoid emoji and playful copy. Iconography (`QToolButton`) should be simple and monochrome to match the theme.
- Ensure sufficient contrast for readability on the dark background; verify text remains legible and interactive states are clearly distinguishable.
- Validate visual changes with the capture script (`uv run python captures/capture_screens.py`) and review the rendered PNGs before considering a UI change done.

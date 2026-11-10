# LumaCut Studio (native) – Gap analysis vs. LightBurn and xTool Creative Space

Date: 2026-10-25 · Scope: `software/lumacut-studio-native` (PySide6) plus the Pi 400 rules in
`pi400/marlin/transport.py` · Machine: diode laser, SKR Mini MZ (Marlin 2.1, `M3 I` inline
power, S0–255), 360 × 340 mm, camera + Z probe on the head.

## 1. What LumaCut Studio actually has (code audit)

| Area | Present in code |
|---|---|
| Canvas (`lumacut_canvas`) | Tools V/R/E/L/T/P (select, rect, ellipse, line, text, polygon, freehand path), move/scale/rotate, groups, copy/paste/duplicate, undo/redo, grid + 1 mm snap, rulers, `.lumacut.json` save/open, SVG/PNG export |
| Layers | One layer = one setting: power 1–100 %, speed 1–6000 mm/min, passes 1–30, visible/locked; bottom layer runs first. (In-flight, uncommitted work by the Canvas/Materials side adds `z_step` per pass.) |
| G-code (`gcode.py`) | Pi-safe Marlin output: one `M3 I`, G0 without S, every G1 with F and S, `M5 I`/`M400`, no G28; bounds check. **No ordering, no overscan, no raster, no estimate.** |
| Import | None in native (only own JSON). Legacy web studio has SVG/raster import. |
| Raster / images | None in native (legacy web studio: threshold/grayscale/Floyd). |
| Zoom/pan | Wheel zoom ×1.15, Ctrl+= / Ctrl+- / Ctrl+0, 0.4–60 px/mm, middle-mouse and Space+drag pan. Anchor relied on `AnchorUnderMouse` (QCursor), no pinch, no fit-to-selection. |
| Machine panel | Connect, status, jog, home, probe (G30), park, upload, start (with confirmation), autorun, abort, E-stop (M112 channel, Pause key). |
| Scan/probe (`scanprobe`) | Tile scan + stitching, object detection, probe plans, height maps, focus compensation of G-code (`apply_focus_compensation`), overlays/ROI hooks into the canvas. |
| Materials | Placeholder `QComboBox` "Material" in main window, no library module. |
| Positioning | Pi does homing, focus and park. No framing, no origin options (absolute work area only), no time estimate. |
| Job queue / autosave | Single uploaded file; no queue, no autosave/recovery. |

## 2. Reference features (sources)

- LightBurn Cut Planner / Optimization Settings – inner shapes first, reduce travel, best start
  point, direction, order by layer: <https://docs.lightburnsoftware.com/OptimizationSettings.html>,
  <https://github.com/LightBurnSoftware/Documentation/blob/master/CutPlanner.md>
- LightBurn Scanning Offset Adjustment (bidirectional raster, ≥5 % overscan for GCode devices):
  <https://docs.lightburnsoftware.com/latest/Guides/ScanningOffsetAdjustment/>
- LightBurn Image Mode (threshold, ordered, Atkinson, dither, Stucki, Jarvis, newsprint,
  halftone, sketch, grayscale, 3D slice): <https://docs.lightburnsoftware.com/2.1/Reference/CutSettingsEditor/ImageMode/>
- LightBurn 3D Sliced image (Galvo only; darker pixels get more passes):
  <https://docs.lightburnsoftware.com/latest/Guides/3DSlicedImage/>
- LightBurn Line mode: Z offset, Z step per pass:
  <https://docs.lightburnsoftware.com/latest/Reference/CutSettingsEditor/LineMode/>
- LightBurn Laser window – Frame (bounding box), rubber-band frame, frame continuously, laser-on
  framing: <https://docs.lightburnsoftware.com/2.2/Reference/LaserWindow/>
- LightBurn Preview – cut/rapid distance, estimated time: <https://docs.lightburnsoftware.com/2.1/Reference/Preview/>
- LightBurn Material Library – presets by material + thickness, *Assign* vs *Link* to layer:
  <https://docs.lightburnsoftware.com/2.1/Reference/MaterialLibrary/>
- LightBurn hotkeys (Ctrl+=/-, Ctrl+0 zoom to page, Ctrl+Shift+A frame selection, Alt+P preview,
  Alt+Shift+R rubber band): <https://docs.lightburnsoftware.com/Hotkeys>
- xTool Material Test Array (columns = power, rows = speed; vector and bitmap):
  <https://support.xtool.com/article/872>, <https://support.xtool.com/article/1864>
- xTool 3D engraving from grayscale depth maps: <https://www.xtool.com/blogs/xtool-academy/3d-laser-engraving>
- xTool framing, bitmap modes (Grayscale, Jarvis, Bayer, Floyd, Stucki, Atkinson, Sierra), lines
  per cm: <https://support.xtool.com/article/507>
- XCS import formats (JPG/PNG/BMP/SVG/DXF/WEBP), arrays: <https://support.xtool.com/article/1303>
- XCS shortcuts (Ctrl+wheel/Ctrl± zoom, wheel scroll, Shift+wheel horizontal, Space pan, Ctrl+0
  fit, boolean ops, node edit): <https://support.xtool.com/article/132>
- XCS zoom bar (fit width/height/screen, hand tool): <https://support.xtool.com/article/3447>

## 3. Prioritized gap table

Diode fit: how much the feature matters on a ~5–20 W diode with Marlin. Effort: S < 1 day,
M 1–3 days, L > 3 days. Status after this pass in **bold**.

| # | Feature | LightBurn / xTool | LumaCut before | LumaCut now | Diode fit | Effort | Owner |
|---|---|---|---|---|---|---|---|
| 1 | Cut order: inside-first, reduce travel, best start | LB yes (default) / XCS yes | none | **done** (`lumacut_job.planner`, used by "Design senden") | very high (parts drop before holes otherwise) | S | Review (new module) |
| 2 | Job time + distance estimate | LB Preview / XCS yes | none | **done** (`lumacut_job.estimate`, accel + junction model, Alt+P; per layer since round 4) | high | S | Review |
| 3 | Framing (box + rubber band, laser off) | LB / XCS yes | none | **done** (toolbar "Rahmen", Ctrl+Shift+F / Alt+Shift+F) | very high (no red-dot pointer; camera only) | S | Review → Machine for a dedicated frame API |
| 4 | Material test grid (power × speed) | LB / XCS yes | none | **done** (`lumacut_job.material_test`, one undo step) | very high (every new material) | S | Review; Materials to consume results |
| 5 | Raster engraving (image object, dithers, line interval, bidirectional, overscan, scan offset) | LB / XCS yes | none | **done** (engine `lumacut_job.raster` + image object on the canvas with settings dialog; images are engraved before vectors in the same job) | very high | M (canvas object + UI) | Canvas (image item) + Review (engine) |
| 6 | 3D / depth: sliced passes from height map, Z step per slice | LB 3D slice Galvo-only; XCS 3D | none | **done** for image objects (mode "3D" in the image dialog → `sliced_depth_gcode`, ≤3 mm total drop); combined with focus compensation it is refused safely (Z words) | medium-high (relief in wood/slate) | M for UI | Canvas/Materials + Review |
| 7 | Zoom: anchor at event position, pinch, fit selection, trackpad | LB / XCS yes | wheel only, QCursor anchor | **done** (`canvas_view` + Ctrl+Shift+A) | high (daily use) | S | Canvas (minimal edit) |
| 8 | Material library: presets by material + thickness, assign/link to layers, combo box wired | LB yes / XCS yes (xTool materials) | placeholder combo | **done** (Materials agent: `lumacut_materials`, material section in the layers panel) | very high | M | **Materials agent** |
| 9 | Import SVG/DXF/PNG/JPG/PDF | LB / XCS yes | none in native | **done** for SVG/DXF/PNG/JPG/BMP (`lumacut_import`, Datei › Importieren Ctrl+I, drag-and-drop, mm conversion, one undo step, clamped to the 360×340 mm work area); **PDF done** (vector paths via `pypdf`, page picker, round 4); **image trace done** (bitmap → vectors, Alt+T, round 5) | very high | M | Canvas |
| 10 | Workflow wizard scan → detect → probe → focus → job → park, focus compensation applied on send | n/a (LB has camera overlay; XCS auto-focus + camera) | pieces exist separately; compensation not hooked into "Design senden" | **done** (`lumacut_workflow`: panel "Ablauf" Home → Scan → Markieren → Probe → Fokus → Rahmen → Auftrag → Parken; status per step, skip, precondition checks; uses the existing panel actions, focus compensation via `prepare_job_gcode`) | very high (USP) | M | Scan Probe + Machine; Review can wire the send path |
| 11 | Fill / hatch for vectors (Fill mode, line interval, cross-hatch) | LB / XCS yes | none | **done** (Canvas: per-layer fill/cross-hatch, 1ddc258) | high | M | Canvas |
| 12 | Kerf offset, tabs/bridges, lead-in/out | LB yes / XCS partial | none | **done** (`lumacut_job.cutpath`, per-layer fields, dialog „Schnittoptionen…“ Alt+K; leads checked for collisions since round 4) | medium (diodes have small kerf; tabs useful) | M | Review (planner) |
| 13 | Boolean ops, node editing, offset, arrays | LB / XCS yes | polygon only | **done** (Canvas: arrays/align 7174f7d, booleans/weld/offset/text-to-path 8993552, node editing 8090f1b) | medium | L | Canvas |
| 14 | Preview of G-code path (travel lines, order animation) | LB / XCS yes | none | **done** (Canvas: path preview overlay with travel, order and time, d2f79dd) | medium | M | Canvas overlay + Review |
| 15 | Air assist M8/M9 per layer | LB yes | none (Pi allows M7/M8/M9) | **not feasible on this machine** – see §8 | medium (if relay installed) | S | Materials/layer field + gcode |
| 16 | Origin options (current position / user origin), job placement on camera | LB yes / XCS yes | absolute only | **done** (Machine: absolute / current position / user origin, `op=place`, fd7601c + ed96c63); job placement on camera open | medium | M | Machine |
| 17 | Job queue, autosave / crash recovery | LB autosave yes | none | **autosave/recovery done** (`lumacut_session`, every 60 s, crash recovery on start); **job history done** (`lumacut_job.history`, Ctrl+H: last 20 sent jobs, resend/save); **multi-job queue done** (Machine: Pi queue e7166c3, queue list in the machine panel 4418a54) | medium | S–M | Canvas (autosave), Machine (queue) |
| 18 | Raster throughput to SKR (Pi-side streaming / line compression) | n/a | risk noted in plan | **done** (Machine/Pi: job streaming to the SKR, 22ece4f) | high for photos | L | Pi / Machine |

## 4. Focus areas

**Zoom.** LightBurn zooms with the wheel at the pointer, Ctrl+=/- and Ctrl+0 (page), and
Ctrl+Shift+A (frame selection). XCS uses Ctrl+wheel for zoom and plain wheel to scroll, plus
fit-width/height/screen. LumaCut now has explicit anchoring at the event position (wheel and
pinch), pixel-delta trackpads, clamped 0.4–60 px/mm, fit-to-selection (Ctrl+Shift+A, falls back
to all objects, then the work area). Kept the LightBurn convention (plain wheel = zoom). Done
since (Canvas, §13): zoom % menu with presets and a „100 %“ button next to „Einpassen“ (9658b85),
Shift+wheel / sideways wheel pans horizontally (88ea265).

**Material automation.** Test grid done; every cell is a real layer, so a grid that worked can be
copied straight into a preset. Needed from the Materials agent: library with material +
thickness → power/speed/passes/z_step/interval/air; "assign" (copy) vs "link" (layer follows
preset); wiring the main-window Material combo; a "save cell as preset" action on test layers.

**3D/depth.** `sliced_depth_gcode` is the diode-friendly equivalent of LightBurn's Galvo-only 3D
slice: N constant-power slices, dark = more slices, optional Z step after each slice (relative
`G91 / G0 Z- / G90`, total ≤ 3 mm, restored at the end; the Pi still enforces its Z floor).
Grayscale power modulation exists as a separate mode. Missing: canvas image object, preview of
the depth map, cross-direction slices (Y raster) to reduce ridging.

**Scan/probe integration.** The scan package already provides height maps and
`apply_focus_compensation`. The job path ("Design senden") does not apply it yet, and the frame
is not drawn over the camera image. Recommendation: one `JobPipeline` hook (optimize → focus
compensate if a valid map exists → estimate → upload), owned jointly by Scan Probe + Review.

**Overall workflow.** Target: Scan → detect material/outline → probe grid → focus → frame →
job → park. Pieces exist in three panels; there is no guided sequence and no "ready" checklist.
This is the biggest UX differentiator over LightBurn/XCS and should be the next milestone.

## 5. Top 10 priorities

1. Material library + layer assign/link (Materials) – the combo box is still empty.
2. Raster image object on the canvas using `lumacut_job.raster` (Canvas + Review).
3. SVG/DXF/PNG import (Canvas).
4. Guided workflow scan → probe → focus → frame → job → park (Scan Probe + Machine).
5. Focus compensation in the send path (Scan Probe hook into `_send_canvas_job`).
6. Dedicated frame API on the machine panel/Pi (so framing does not replace the uploaded job).
7. Vector fill/hatch mode per layer (Canvas).
8. Path preview overlay with order + travel (Canvas overlay + planner data).
9. Tabs/kerf/lead-in in the planner (Review).
10. Autosave/recovery and air-assist M8/M9 per layer.

## 6. Implemented in this pass

- `src/lumacut_job/planner.py` – inside-first (containment), nearest-neighbour travel reduction,
  best start vertex, open-path reversal; per layer, layer order unchanged. Used by "Design senden".
- `src/lumacut_job/estimate.py` – trapezoid/junction-deviation time estimate (150 mm/s,
  500 mm/s², Z 9 mm/s), box/hull framing G-code with laser off (`S0`, no `M3 I`).
- `src/lumacut_job/material_test.py` – power × speed grid, fill or outline, labels.
- `src/lumacut_job/raster.py` – raster modes, bidirectional, overscan, scan offset, sliced depth.
- `src/lumacut_job/qt_tools.py` – "Auftrag" toolbar: Zeit schätzen (Alt+P), Rahmen
  (Ctrl+Shift+F), Gummiband-Rahmen (Alt+Shift+F), Materialtest… dialog.
- Minimal edits: `canvas_view.py` (anchored zoom, pinch, `fit_rect`), `editor.py` (one action +
  `fit_selection`), `main.py` (import, install call, optimized send + estimate message).
- All generated G-code is checked in tests against the Pi's own `MarlinLaserGuard`.

## 7. Decisions needed

- Framing currently uploads `lumacut-frame.gcode` and starts it, which replaces the uploaded job;
  user must press "Design senden" again. Prefer a Pi/Machine frame endpoint?
- Laser-on (low power) framing for better visibility on a diode: allowed or not?
- Z step per pass/slice: keep in the G-code (relative G91) or let the Pi apply focus drops?
- Y axis direction on the real machine not verified against canvas Y-down (affects raster order
  and framing corners only cosmetically, not safety).
- Long-term: Pi generating motion (raster streaming) vs. Studio-side G-code.

## 8. Status update 2026-10-26 (review round 2)

Done and pushed to `main` (all G-code still checked against `MarlinLaserGuard`):

- **Import** (#9): `src/lumacut_import/` – SVG (paths, basic shapes, transforms, viewBox → mm),
  DXF (via `ezdxf`, incl. blocks/INSERT, `$INSUNITS`), raster PNG/JPG/BMP as
  image objects (DPI → mm). Menu *Datei › Importieren…* (Ctrl+I), drag-and-drop onto the canvas,
  one undo step, result scaled/moved into the 360×340 mm work area. New dependencies in
  `requirements.txt` (`svgelements`, `ezdxf`; raster via Qt `QImage` + `numpy`); `build-windows.bat` updated.
- **Image objects** (#5/#6): settings dialog *Bildeinstellungen* (Ctrl+Shift+I: mode, line interval,
  max/min power, speed, passes, bidirectional, negative); engraved before the vector layers in one program.
- **Guided workflow** (#10): `src/lumacut_workflow/` – Qt-free step engine (`steps.py`) plus panel
  *Ablauf* (`qt.py`). Every step shows Erledigt/Bereit/Gesperrt/Übersprungen/Läuft, a reason when
  blocked (not connected, not homed, E-stop latched, machine busy, no marked areas, no design, …),
  and can be skipped except Home and Auftrag. Frame/job count as done only on a real
  running → complete transition; editing the design reopens frame and job.
- **Autosave / crash recovery** (#17): `src/lumacut_session/` – atomic save every 60 s to
  AppData/autosave while the project has unsaved changes; per-session `QLockFile`, so a second
  running Studio is never offered as "crashed". On start, a backup of a crashed session is offered
  ("Projekt wiederherstellen?"); the restored project is marked unsaved. Backups are deleted on
  save, on undo back to the saved state and on normal exit.
- **Materials** (#8) was completed by the Materials agent (`lumacut_materials`).
  Follow-up (2026-10-26): link vs assign with automatic re-plan on thickness/depth change (same
  undo step, generic `register_layer_attr_hook`), main-window Material combo wired, "save test
  cell as preset" (#4 → #8), per-material kerf/tab-width defaults written into the #12 layer fields
  (spacing/lead-in only when already enabled), relief plan → image `depth3d` settings (#6).
  See `software/lumacut-studio-native/docs/MATERIALS.md`.
- **Dedicated frame op** (Top-10 #6) was completed by the Machine side (`op=frame`).

**Air assist (#15) – not feasible as specified.** The Pi guard does allow M7/M8/M9, but on this
machine those codes are already wired to other outputs: **M7 = lights, M8 = exhaust (Absaugung),
M9 = both off**. Emitting M8/M9 per layer would toggle the exhaust mid-job (M9 would even switch
off the extraction during cutting). Air assist needs its own output (e.g. a free SKR fan/heater
pin with a dedicated M-code such as `M106 P<n>`) plus a matching guard rule on the Pi before a
layer field makes sense.

Still open at the time: path preview overlay (#14), kerf/tabs/lead-in (#12), vector fill/hatch
(#11), PDF import, job queue, raster streaming (#18) – all done since, see §9–§11 and §13. Error diffusion on very large images is slow
(pure-Python inner loop).


## 9. Status update 2026-10-26 (review round 3)

Ownership this round: touch, vector fill/hatch (#11) and the path-preview overlay incl. its data
(#14) belong to the **Canvas agent**; the review side did planner/job-side items only.

Done and pushed to `main` (G-code checked against `MarlinLaserGuard` in tests):

- **Kerf / tabs / lead-in/out** (#12): per-layer fields on `Layer` and `JobLayer`
  (`kerf_mm`, `tab_count`, `tab_width_mm`, `tab_spacing_mm`, `lead_in_mm`, `lead_in_arc`,
  `lead_out_mm`; defaults in `lumacut_canvas.model.CUT_LAYER_DEFAULTS`, written to the file only
  when set, so older files and readers are unaffected). Applied in `optimize_layers`: kerf before
  ordering (shapely, side by nesting parity), tabs and leads after ordering. Each output polyline
  is tagged in `JobLayer.poly_kinds` (`cut`/`lead_in`/`lead_out`/`tab`). Dialog „Schnittoptionen…“
  (Alt+K). New dependency `shapely>=2.0` (requirements + `build-windows.bat`).
- **Job history + G-Code speichern** (part of #17): last 20 sent jobs (any sender) with resend
  (upload only, start stays manual) and save-as-file; „G-Code speichern…“ (Alt+G) for offline use.
- **Shortcut overview**: Hilfe › Tastenkürzel (F1), collected live from all window actions.

Still open (at the time; unit toggle, #13, #16, #17, #18 and PDF import done since, see §10–§13): unit toggle mm/inch (touches canvas widgets → Canvas), PDF import (no small,
permissively licensed vector-PDF reader; PyMuPDF is AGPL), multi-job queue on the Pi (Machine),
boolean/node/offset/array tools (#13, Canvas), origin options (#16, Machine), raster streaming
(#18, Pi), lead collision check against neighbouring parts, Windows hardware test of the new
cut options.

## 10. Status update 2026-10-26 (review round 4)

Done (review side, pushed to `main`, G-code checked against `MarlinLaserGuard` where relevant):

- **PDF import** (#9): `lumacut_import.pdf` reads vector paths from PDF pages with `pypdf`
  (BSD, pure Python; PyMuPDF rejected for its AGPL licence). Own small content-stream
  interpreter: `m l c v y h re`, `cm`, `q/Q`, page `/Rotate` and `/UserUnit`, form XObjects; fill and
  stroke paths become polygons/polylines in mm (pt × 25.4/72) and go through the same placement as
  SVG/DXF (one undo step, clamped to the work area). Multi-page PDFs ask for the page. Strokes that
  writers store as thin filled rings (Qt, Word) are reduced to one contour ("doppelte Strichkante").
  Not imported: text (unless converted to outlines), embedded images, clipping, dash patterns,
  encrypted files. New dependency `pypdf>=4.0`.
- **Lead collision check** (rest of #12): with lead-in/out active, `optimize_layers` builds a
  shapely STRtree of all post-kerf contours of all layers. A lead that crosses its own contour or
  any other part is first retried at other start points (long edge midpoints, then evenly spaced
  points), reversed, then shortened; only then dropped. `PlanReport` counts moved/dropped leads; the
  note („Anfahrt bei N Kontur(en) weggelassen … – Ebene X“) is shown after Senden, in the estimate
  and when saving G-code (main window and workflow panel).
- **Estimate per layer** (#2): `JobEstimate.layers` from the planner's `; LAYER` / `; IMAGE`
  comments; the estimate dialog lists time per layer when there are two or more.
- **„Nur Auswahl“** (LightBurn "Cut selected graphics"): checkable toolbar action; Senden,
  Schätzung, Rahmen and G-Code speichern then use only the selected objects (layer settings kept);
  nothing selected → clear error, no job.
- **Windows build**: `build_exe.py` holds the PyInstaller options for `build-windows.bat` *and* CI
  (all own packages, ezdxf, svgelements, pypdf, shapely, `materials.json`) and fails if the material
  data is missing from the bundle. Before, `--collect-data` silently skipped our own packages
  (not on `sys.path` at build time), so the shipped exe had no material library. The CI build step
  now runs `python build_exe.py`; a test keeps `OWN_PACKAGES` in sync with `src/`.

Caveats: the path preview overlay (Canvas) and the scan/probe panel still show the whole design,
not the selection (path preview fixed since: follows „Nur Auswahl“, 6bd4b8c, §13; scan/probe panel
still whole design – Scan Probe); the thin-ring merge is a heuristic (≤0.5 mm ring width) and can merge a real
very thin outline frame.

Done meanwhile by the Machine agent: origin options (#16; absolute / current position / user
origin, `op=place`, fd7601c + ed96c63).

Still open: ~~unit toggle mm/inch~~ (done, a73bfe7), ~~boolean/node/offset/array (#13)~~ (done, §11) – Canvas; multi-job queue on the
Pi (#17) – Machine; raster streaming (#18) – Pi; Windows hardware test of
cut options, PDF import and the rebuilt exe – needs a Windows machine with the laser.

## 11. Status update 2026-10-26 (review round 5)

Verified on `main` (commits exist, features and tests present):

- **#11 Fill / hatch** – Canvas, 1ddc258 (per-layer fill and cross-hatch).
- **#13 Boolean / offset / arrays / node editing** – Canvas: 7174f7d (align, distribute, grid and
  circular arrays), 8993552 (booleans, weld, offset, text to paths), df63635 (font, size, bold,
  italic). Node editing was still in progress when this round started and landed during it
  (8090f1b, tool „Knoten“, key N), so #13 is now done.
- **#14 Path preview** – Canvas, d2f79dd (laser path, order, time overlay); touch polish ff638ef.
- **#16 Origin options** – Machine, fd7601c + ed96c63 (absolute / current position / user origin,
  placement check on the Pi).
- **#17 Multi-job queue** – Machine, e7166c3 (Pi queue: run, skip, remove) + 4418a54 (queue list in
  the machine panel). Autosave and job history were already done.
- **#18 Raster throughput** – Pi/Machine, 22ece4f (job streaming to the SKR).

Done in this round (review side, `lumacut_import` / `lumacut_job` only, no new dependencies):

- **Image trace** (LightBurn „Trace Image“, part of #9): *Datei › Bild nachzeichnen…* (Alt+T) turns
  the selected image into polygon outlines. `lumacut_import.trace` (Qt-free): threshold (default
  from the image settings), invert, Gaussian smoothing, simplify tolerance (mm) and min area
  (despeckle). Contours come from OpenCV on a 2×-upscaled mask and are grown by ¼ px, so outlines
  sit exactly on pixel edges and 1-px lines survive; holes become `rings` (even-odd), several parts
  are grouped, image rotation is respected. Dialog with live preview (debounced, downscaled);
  one undo step incl. optional deletion of the image. Noisy images (too many contour points) are
  refused quickly with a hint instead of hanging. G-code of traced parts passes `MarlinLaserGuard`.
- **Serial numbers** (batch case of LightBurn „Variable Text“): „Seriennummern…“ (Alt+N, toolbar
  „Auftrag“) replaces the selected text with a grouped grid of copies; template placeholders
  `{n}`, `{n:3}` (zero-padded), `{date}`, `{{ }}`; start, step, count (≤ 500), columns, gaps; height,
  font, rotation, layer and stretch kept, width follows the text; one undo step; grids that do not
  fit the work area are refused without changes.

Tests: `tests/test_trace.py` (12), `tests/test_serial_numbers.py` (7).

Still open:

- ~~Unit toggle mm/inch – Canvas.~~ Done (a73bfe7, §13).
- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Variable text evaluated at send time with an auto-incrementing counter (CSV/merge, counter
  persisted per job) – the batch grid covers the common case; decide if the job-time variant is
  wanted.
- Min/max power with speed-dependent corner power (LightBurn) – needs a planner change and checking
  what the SKR's Marlin build supports (`LASER_POWER_TRAP` / inline power); not started.
- Trace: no centre-line trace and no curve fitting (outlines are polygons); photos need a manual
  threshold.
- Windows hardware test of cut options, PDF import, image trace and the rebuilt exe – needs a
  Windows machine with the laser.

## 12. Status update 2026-10-26 (review round 6)

Done in this round (review side, `lumacut_import` only, no new dependencies):

- **Image trace hang fixed** (`lumacut_import.trace`): the slow cases were GEOS' hole handling and
  topology-preserving simplify, which grow roughly quadratically with the number of holes in one
  part. Parts with more than 64 holes now take a ring-by-ring path: shell and holes are grown /
  shrunk separately, touching holes are merged via an STRtree, properly contained holes are
  inserted directly (only the rest go through one difference), and each ring is simplified on its
  own with an STRtree conflict check (conflicting rings fall back to the raw outline). Parts with
  ≤ 64 holes keep the old code path, so the output of all existing cases is unchanged. A
  1000×1000 dot grid with ~15 000 holes now takes ~0.9 s instead of ~15 s, and the 2000×2000
  smooth-noise benchmark dropped from ~11.5 s worst case to ~2.8 s.
- **Time budget**: cheap pre-pass (part count) before any shapely work, image size cap
  (`MAX_PIXELS`, 40 MP) and a deadline (`time_limit_s`, 60 s default) that stops with a clear
  message instead of hanging. The live preview runs on ≤ 420 px with a 2 s limit, so the dialog
  cannot freeze; the final trace shows a wait cursor.
- **Auto threshold** (Otsu): `TraceSettings.auto_threshold` (default off, so behaviour is unchanged)
  picks the threshold after smoothing; the dialog has an „Auto“ checkbox next to „Schwellwert“
  that disables the spin box and shows the detected value in the preview text.
- Centre-line trace was **not** started: it needs skeletonisation plus graph-to-polyline conversion,
  which is not a small change.

Tests: `tests/test_trace.py` now has 18 (6 new: many-holes speed and exactness, smooth noise
finishes or is refused within the time limit, time limit and size cap, preview responsiveness on a
9 MP noisy image, Otsu engine, dialog „Auto“ checkbox).

Still open:

- ~~Unit toggle mm/inch – Canvas.~~ Done (a73bfe7, §13).
- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Variable text evaluated at send time with an auto-incrementing counter (CSV/merge, counter
  persisted per job) – the batch grid covers the common case; decide if the job-time variant is
  wanted.
- Min/max power with speed-dependent corner power (LightBurn) – firmware checked in round 7 (§14):
  needs a user decision (`LASER_POWER_TRAP` in the SKR build).
- Trace: ~~no centre-line trace~~ (done, §14) and no curve fitting (outlines are polygons). Masks with more than
  400 000 raw edge points (very detailed or noisy images) are still refused with a hint; raising
  that limit is possible now but costs memory and time.
- Windows hardware test of cut options, PDF import, image trace and the rebuilt exe – needs a
  Windows machine with the laser.

## 13. Status update 2026-10-26 (Canvas)

Done and pushed to `main` (Canvas agent; full Studio suite green offscreen before each push):

- **Coordinate helpers** (c75182b): all screen ↔ user ↔ machine conversions go through
  `lumacut_canvas/workarea.py` (`screen_to_machine`, `machine_to_screen`, `machine_rect_to_screen`,
  `screen_to_user`, `axis_tooltips`, …). `ORIGIN_TOP_RIGHT` exists only there.
- **Origin top right** (3b79ab6, `docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md` §2.3):
  `ORIGIN_TOP_RIGHT = True`, machine = (390 − x, 30 + y); file marker `coords` =
  `screen-tl/machine-tr-v2`, unknown conventions are refused. Pushed together with Scan Probe's
  part (f00485e, 3c3a801, d8b4528). Raster export: image column 0 (left edge on screen) lands at
  the large machine X, checked by `test_origin_top_right.py::test_raster_column_0_lands_at_large_machine_x`.
- **Units mm/inch** (a73bfe7): action bar toggle „mm/Zoll“ (Ctrl+Shift+U), saved in QSettings.
  Storage, G-code and raster stay in mm; rulers, property bar, cursor readout and all
  `LengthSpin` fields convert for display only and accept `25,4 mm`, `1 in`, `1″`. Layer and
  material dialogs stay in mm (process values).
- **Zoom** (9658b85): „100 %“ (Ctrl+1, physical size) next to „Einpassen“; the zoom % label is a
  menu with 25/50/100/200/400/800 %.
- **Pan** (88ea265): Shift+wheel and sideways wheel/trackpad scroll horizontally.
- **Path preview = job** (6bd4b8c): with „Nur Auswahl“ the preview computes only the selection
  (readout „Nur Auswahl · …“), rebuilds on selection change; nothing selected shows the job's
  message instead of a path.
- **Kamera-Scan** in the main view calls `ScanPanel.camera_scan()` (switches to the Pi camera when
  connected), falling back to `start_scan()` on older panels.

Still open / for others:

- Scan/probe panel areas still use the whole design, not „Nur Auswahl“ – Scan Probe.
- Old toolbar start in `main.py` should also go to `one_click.start` (§1.1 answer 1) – owner of
  that block (Machine).
- Physical check on the machine after homing (X+10 moves left, Y+10 towards the door, test rectangle
  position) – user at the machine.

## 14. Status update 2026-10-26 (review round 7)

Done in this round (review side, `lumacut_import` only, no new dependencies):

- **Centre-line trace** (`lumacut_import/centerline.py`, `TraceSettings.mode = "centerline"`):
  for sketches, handwriting and technical drawings every stroke becomes one open line instead of
  two outlines, so the laser burns it once. Pipeline: same threshold / smoothing / Otsu as the
  outline trace → specks below „Mindestfläche“ dropped → thinning (Zhang-Suen through 256-entry
  lookup tables on one `filter2D` neighbour code, then a checkerboard pass that deletes the
  remaining staircase pixels with a simple-point test, so the skeleton is one pixel wide and keeps
  the topology) → skeleton graph (junction pixels merged into clusters, chains between clusters /
  end points, pure loops closed) → spurs shorter than ~1.5× the local half stroke width pruned →
  chains joined where only two branches meet and, at crossings / T-junctions, the pairs that
  continue within ~32° of straight (a „+“ stays two lines) → free ends extended along their
  direction to the stroke tip (thinning eats about half a stroke width) → Douglas-Peucker with
  „Toleranz“ (at least ½ pixel against the pixel staircase).
- Result: `TraceResult.lines`; `traced_shapes` creates open `path` objects (closed loops repeat
  their first point, so a fill layer does not fill them), several are grouped as before. The
  default mode stays „Kontur“, so all existing results are unchanged.
- Dialog „Bild nachzeichnen“: new „Modus“ selector (Kontur / Mittellinie) with tooltip; preview
  draws the lines, the info text counts „Linie(n)“, and for filled areas in centre-line mode it
  hints that the mode is meant for strokes.
- Runtime: thinning works on the foreground's bounding box and checks the trace deadline every
  iteration; large filled areas stop with „Mittellinie dauert zu lange – … für Flächen „Kontur“
  verwenden“ instead of hanging. 1500×1500 px with 150 random strokes ≈ 2–3 s.

Corner power (open item, checked, **not** implemented – user decision needed): the SKR Marlin
build (`firmware/marlin/build.py`) enables `LASER_FEATURE` with `CUTTER_POWER_UNIT PWM255`, the
gateway uses `M3 I` (inline continuous). `LASER_POWER_TRAP` (Marlin scales inline power with the
real speed during acceleration / deceleration, the clean equivalent of LightBurn's min power) is
**not** enabled. Marlin's `M4` dynamic mode scales with the commanded feed rate `F`, not with the
real speed at corners, so it does not help. A G-code-side emulation (splitting segments near
corners into short pieces with ramped `S`) would multiply the line count over serial (`BUFSIZE 8`)
and can starve the planner, which causes stops and more burn – not done. Options: (1) enable
`LASER_POWER_TRAP` in the firmware build, re-flash, then the Studio gets a per-layer „Min. Leistung“
field mapped to it; (2) leave as is.

Tests: new `tests/test_trace_centerline.py` (12): mode normalisation, one-pixel skeleton with the
same topology, thick stroke → one straight centre line, crossing stays two lines, Y/T junction keeps
all branches with ends at the stroke tips, ring → closed line on the circle, despeckle and
tolerance, raw pixel graph, canvas `path` objects + G-code through the Pi guard, speed / blob time
limit, dialog mode switch + trace into the document, filled-area hint. Existing `test_trace.py`
unchanged and green.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see above).
- Trace: curve fitting (Bézier output) for outlines and centre lines; centre lines of very thick
  strokes have small kinks at junctions.
- Variable text evaluated at send time with an auto-incrementing counter – decide if wanted.
- Windows hardware test of cut options, PDF import, image trace (incl. centre line) and the rebuilt
  exe – needs a Windows machine with the laser.

## 15. Status update 2026-10-26 (review round 8)

Done in this round (review side, `lumacut_import` only, no new dependencies – numpy / shapely):

- **Trace curve fitting „Glätten“** (`lumacut_import/curvefit.py`, `TraceSettings.smooth_curves`,
  default on like potrace / LightBurn): traced outlines (outer rings and holes) and centre lines are
  fitted with cubic Béziers instead of only simplifying the pixel staircase. Pipeline per ring /
  line: pixel-edge staircase → unit-edge midpoints → corner detection (turn angle over ±4 px of arc
  length > 70°, non-maximum suppression; the corner is then placed on the intersection of straight
  line fits of both sides) → per piece between corners: resample at 0.5 px, Gaussian pre-smoothing
  (σ 1.5 px, ends pinned), Schneider least-squares Bézier fit with Newton re-parametrisation and
  splitting at the worst point, tolerance max(0.3 px, „Toleranz“) → flattened to a fine polyline
  (chord deviation ≤ 0.02 mm, clamped to 0.05–0.25 px). Closed rings without corners are fitted as
  one loop with a shared tangent, tiny rings (< 12 px perimeter) stay as they are, and a result that
  would make the polygon invalid falls back to the old simplification.
- The document model has no general Bézier type (only per-segment Catmull-Rom `curves` for node
  editing), so the curves are stored as the fine polyline – G-code, preview, export and the Pi
  guard are unchanged. Measured on filled circles r 8–150 px: max radial deviation ≈ 0.68 px →
  0.26–0.45 px, RMS ≈ 0.34 → 0.13–0.15 px; curvature spikes of the staircase are gone. Axis-aligned
  squares keep exactly their 4 corners; rotated squares keep 4 sharp corners and straight edges
  (Hausdorff to the true square below the plain trace).
- **Centre lines:** chains are trimmed by 1.2× the local half stroke width at junctions (the
  skeleton bends there), straight-through junctions are dropped from the pin list, sharp ones stay
  pinned, then each chain is fitted like above; branch ends are snapped onto the fitted through-line
  and refitted. Thick T-junctions now have a perfectly straight bar and the stem ends on it (before:
  kink of ~1 px), crossings stay within 1 px of the true strokes, thick rings are round.
- Dialog „Bild nachzeichnen“: new checkbox „Glätten (Kurven anpassen, Ecken bleiben scharf)“ with
  tooltip, live preview, remembered via `TraceSettings`. „Toleranz“ now controls the fit (and the
  Douglas-Peucker simplification when „Glätten“ is off); the point count is set by the fine
  flattening.
- Runtime: ≈ 45 µs per raw contour point (corner suppression uses bisect, no quadratic loop).
  Above 150 000 raw contour points (noise, photos) smoothing is skipped and the preview says
  „Glätten übersprungen – Bild sehr detailreich (nur vereinfacht)“, so the existing time limits hold
  (2000×2000 noise unchanged, 1500×1500 line art with 150 strokes ≈ 4 s incl. smoothing).

Tests: new `tests/test_trace_smooth.py` (19): default / normalisation, circles r 8/25/60 rounder
than the plain trace with bounded flattening chord, axis square exact corners, rotated squares
(17°/30°/45°) sharp corners and straight edges, holes smoothed and polygon valid, tiny dots and
curve-fit helpers, tolerance vs. flattening, centre-line ring / thick T-junction / crossing strokes,
speed (line art, logo-sized image), skip note on very detailed images, G-code through the Pi guard,
dialog checkbox. Existing trace tests that check the pixel-exact raw trace or the Douglas-Peucker
point reduction now set `smooth_curves=False` explicitly (`RAW`, despeckle / tolerance tests).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter – decide if wanted.
- Trace: true Bézier objects in the document (editable curve handles) would need a model change
  (Canvas); oblique thick crossings still split into two nearby junctions with a short bridge line.
- Windows hardware test of cut options, PDF import, image trace (incl. centre line and „Glätten“)
  and the rebuilt exe – needs a Windows machine with the laser.

## 16. Status update 2026-11-01 (review round 9)

Done in this round (review side, `lumacut_job` only, no new runtime dependencies – Android already
had both features, commits 5329cbd / 6516dec):

- **QR code generator** (`lumacut_job/qr.py`, pure Python, ISO/IEC 18004): byte mode (UTF-8),
  versions 1–40 chosen automatically, error correction L/M/Q/H, Reed–Solomon over GF(256), block
  interleaving, format and version information, all 8 masks with the standard penalty rules
  (N1–N4, ported 1:1 from Nayuki's reference so the chosen mask is identical). Verified offline
  against Nayuki qrcodegen and the `qrcode` package (identical matrices on 149 random texts × all
  EC levels, incl. v40), and every result decoded with zxing-cpp. `segno` is *not* a byte-exact
  reference (it adds a 0x00 byte before the padding – still valid, but a different matrix).
- Output: dark modules merged row-wise and unioned (shapely) into `polygon` objects with holes as
  rings, one group per code; filled by the layer's hatch / cross-hatch like any other object (the
  even-odd fill keeps holes open). Quiet zone 0–10 modules (default 4) is reserved around the code;
  „Invertiert“ engraves the light modules *and* the quiet zone (materials that turn light, e.g.
  anodised aluminium / slate). Size 5–340 mm; error below 0.2 mm module size or if the code incl.
  quiet zone does not fit the work area; hint below 0.8 mm module size.
- Dialog „QR-Code einfügen“ (Auftrag menu / Design menu, **Alt+Q**): content, Fehlerkorrektur,
  Größe, Ruhezone, Invertiert, info line (version, modules, module size, warnings). The code goes
  onto the **active layer** if that layer fills; if it does not fill, the dialog pre-checks
  „Neue Ebene „QR-Code“ mit Füllung (Schraffur 0,1 mm)“ – otherwise only outlines would be lasered
  and the code would be unreadable. Inserted centred on the work area, selected, one undo step
  (incl. the new layer), locked layer → message.
- **Arc / curved text** (`lumacut_job/arctext.py` + `arctext_qt.py`, „Bogentext…“, **Alt+B**): text
  along a circle as vector outlines (one grouped `polygon` per glyph, holes as rings). „Oben/außen“
  runs clockwise with the letters outside, „Unten/innen“ runs counter-clockwise with the letters
  inside, both reading left to right. Settings: font (system font combo), bold/italic, cap height,
  radius, angle (0° = 12 o'clock, clockwise), reference point Mitte/Anfang/Ende, letter spacing.
  Kerning is kept (advances from the font metrics of the whole string). Errors: text longer than
  the circumference, letters higher than the radius (inside), result larger than the work area.
  If exactly one text object is selected it pre-fills text / font / height / radius and can
  replace it in place (same layer and groups, one undo step).

Tests: `tests/test_qr_code.py` (21) – matrices identical to Nayuki reference, ISO byte capacities,
format info for all EC levels × masks, chosen mask = minimal penalty, version info (v7), quiet zone /
invert runs, polygon area = dark modules (no overlaps), errors, decoding with OpenCV (already a
dependency) of the rendered vector shapes, of the inverted code and of the 0.1 mm hatch lines,
dialog, window action (Alt+Q, Design + Auftrag menu), active layer / new fill layer, one undo step,
G-code through the Pi guard. `tests/test_arc_text.py` (14) – angles / anchors / orientation for top
and bottom, alignment, spacing, errors, grouping / centring / clamping, font glyph metrics,
dialog, window action (Alt+B), replace selected text, undo, G-code through the Pi guard.

Pre-existing failures on clean `origin/main` (Pi side changed, Studio tests not updated – Machine /
Scan Probe): `test_machine_probe_reach.py` (collection error, `PROBE_HEAD_MAX` removed from
`pi400/marlin/transport.py` in 9ae8577), `test_probe_reach.py::test_reach_constants_match_pi_source`
(same) and `test_origin_end_to_end.py::test_default_anchor_at_switch_corner`
(`placement.check_extent` now expects a park-corner tuple instead of a float).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter – decide if wanted.
- Trace: true Bézier objects in the document (editable curve handles) would need a model change
  (Canvas); oblique thick crossings still split into two nearby junctions with a short bridge line.
- QR / arc text are static vector objects (not re-editable parameters after insertion; re-create
  via the dialog). Other 2D codes (DataMatrix, barcodes) not covered.
- The three pre-existing test failures above (Machine / Scan Probe).
- Windows hardware test of cut options, PDF import, image trace (incl. centre line and „Glätten“),
  QR code readability on real material and the rebuilt exe – needs a Windows machine with the laser.

## 17. Status update 2026-11-02 (review round 10)

Done in this round (`lumacut_job` only, no new runtime dependencies):

- **1D barcode generator** (`lumacut_job/barcode.py`, pure Python): **Code 128** (printable ASCII
  32–126; code sets B/C chosen by a shortest-path search – digit runs go to C
  where that saves symbols, ties stay in the current set; checksum mod 103, stop with termination
  bar), **EAN-13**, **EAN-8** and **UPC-A** (L/G/R patterns, parity from the first digit, guard
  bars). The check digit is appended if missing or validated if given (wrong digit → German error
  naming the correct one). Verified offline against python-barcode 0.16.1: identical module
  strings for all EAN/UPC cases and for Code 128 wherever python-barcode picks the optimal set
  sequence (it is not optimal for e.g. „X12345“ / „ab1234cd“ – ours is equal or shorter), all
  decoded with zxing-cpp.
- Output: every bar (adjacent dark modules merged) is one filled rectangle `polygon`, all bars and
  text glyphs in one group; filled by the layer's hatch like the QR code. Quiet zone per standard
  (Code 128 10 modules, EAN-13 11/7, EAN-8 7/7, UPC-A 9/9), optional human-readable text below as
  vector outlines (EAN/UPC: digits in the standard slots, guard bars extended; Code 128: centred,
  shrunk if wider than the code), optional bar width reduction for the laser spot. Module width
  0.1–5 mm (error below 0.1 mm, hint below 0.15 mm), height 2–300 mm; error if the code incl.
  quiet zone and text does not fit 360 × 340 mm.
- Dialog „Barcode einfügen“ (Auftrag menu + Design menu, **Alt+C**): type, content (example
  replaced when switching to a type it does not fit), module width, height, quiet zone, text +
  size + font, bar correction, info line (modules, symbols / check digit, size, warnings). Same
  layer logic as the QR code: active layer if it fills, otherwise pre-checked new layer „Barcode“
  with 0.1 mm hatch; centred, selected, one undo step, locked layer → message.
- Pre-existing failures fixed (stale Studio tests only, Pi unchanged): `test_machine_probe_reach.py`
  and `test_probe_reach.py` now take the probe head maximum as `TRAVEL_XY_MM − 10` (Pi 9ae8577),
  `test_origin_end_to_end.py` uses the real `PARK_CORNER_MM` for `check_extent` (refusal at origin
  (30, 30), acceptance right of the park corner).

Tests: `tests/test_barcode.py` (31) – module strings identical to python-barcode references,
Code 128 table / checksum (Wikipedia example), set switching (8 cases) and optimality against a
brute force, EAN/UPC check digits and errors, EAN structure, bar geometry (widths, positions,
quiet zone, no overlaps, bar correction), EAN text slots and guards, limits / errors / normalisation,
read-back of the rendered vector bars scanline by scanline (6 codes), decoding with zxing-cpp of
the rendered shapes incl. text (5) and of the 0.1 mm hatch lines (skipped without zxing-cpp, now
in `requirements-dev.txt`), dialog, window action (Alt+C, no clash, Design + Auftrag menu), active
layer / new fill layer, one undo step, wrong check digit / locked layer messages, G-code through
the Pi guard. Full suite: 1052 passed, 2 skipped (before: 1012 passed, 2 failed, 1 collection
error).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter – decide if wanted.
- Trace: true Bézier objects in the document (editable curve handles) would need a model change
  (Canvas); oblique thick crossings still split into two nearby junctions with a short bridge line.
- QR / barcode / arc text are static vector objects (not re-editable parameters after insertion;
  re-create via the dialog). **DataMatrix** and other 2D codes (PDF417, Aztec) still not covered;
  barcode has no „Invertiert“ mode yet (QR has one); GS1-128 (FNC1) / Code 128 set A
  (control characters) not supported.
- **Park corner in Studio** (decision needed): since Pi 9ae8577 the Pi refuses powered moves inside
  the park corner (X0–78 / Y0–35 for head v6), but the Studio canvas still assumes the 30 mm
  L-shaped safe zone and does not know the corner – a motif in the canvas top-right corner (e.g.
  at the default user origin (30, 30)) is accepted by Studio and refused by the Pi at send time.
  Studio should read the park corner from the Pi and show / check it (Canvas / Machine).
- Studio `PROBE_HEAD_MAX` (380, 360) follows the *default* travel 390 × 370; the Pi now derives it
  from the configured travel (`/api/settings`, measured 370 × 360 on the owner's machine), so the
  Studio reach preview can be too optimistic there (Machine / Scan Probe).
- Windows hardware test of cut options, PDF import, image trace (incl. centre line and „Glätten“),
  QR code and barcode readability on real material and the rebuilt exe – needs a Windows machine
  with the laser.

## 18. Status update 2026-11-02 (review round 11)

Done in this round (Studio only, Pi unchanged, no new runtime dependencies):

- **Park corner preflight** (`lumacut_job/park_corner.py`): Studio now mirrors the Pi's check
  from 9ae8577. `powered_bounds` reproduces `pi400/marlin/placement.scan` (beam off on G0/M5,
  S word on G1–G3, arcs, G91), `anchor_point`/`placement_offset` reproduce `make_placement`, and
  the corner comes from the Pi status (`park_corner_mm`, `cutting_bounds`) with
  `PARK_CORNER_MM = (78, 35)` as fallback. Every `MachinePanel.send_gcode` (design send, Ablauf,
  relief, history re-send) is wrapped: a job whose absolute powered box reaches into the corner is
  **not sent**; a send with autorun at a user origin is **not started** when the placed box would
  hit the corner; a plain send whose later start at the chosen origin would be refused gets a
  warning. The one-click „Start“ flow (`scanprobe/job_flow_qt.py`) refuses before anything moves,
  and the time estimate (Alt+P) mentions the problem. Messages are German and name the required
  shift („Motiv um mindestens … mm nach links (X+) oder … mm nach unten (Y+) verschieben“).
  `history_qt.attach_history` now passes `send_gcode` keyword arguments through (it dropped
  `autorun`). The canvas does not draw the corner yet (Canvas agent) – only a 48 × 5 mm strip at
  the top right of the visible work area is affected.
- **Data Matrix ECC 200** (`lumacut_job/datamatrix.py`, pure Python): all 24 square sizes
  10 × 10 … 144 × 144 (data regions, 1–10 interleaved Reed-Solomon blocks over GF(256)/0x12D,
  generator roots α¹…αⁿ), ASCII encodation with digit-pair compaction, Upper Shift for 128–255
  (ISO 8859-1), ECI 26 + UTF-8 for other Unicode, 253-state pad randomisation, ISO 16022 Annex F
  placement incl. the four corner cases and the fixed lower-right pattern. Automatic size or a
  chosen minimum size. Output exactly like the QR code: merged filled polygons (holes as rings) in
  one group, quiet zone (default 2 modules), „Invertiert“, active fill layer or new layer
  „Data Matrix“ with 0.1 mm hatch, centred, one undo step. Dialog „Data Matrix…“ in the Design
  and Auftrag menus, shortcut **Alt+X** (no clash, no menu mnemonic).
- **Barcode „Invertiert“**: engraves quiet zone, spaces and a border of max(1 mm, 5 modules) above
  and below as polygons with the bars and human-readable digits as holes; quiet zone forced on;
  the bar correction widens the bars (narrows the lasered spaces) in this mode.

Tests:

- `tests/test_park_corner.py` (22): the mirror is checked against the Pi source.
  - `powered_bounds` vs. Pi `scan` (7 G-code cases), `anchor_point` vs. Pi, and the visible
    anchor inverting `wire_anchor`.
  - Random absolute and placed jobs agree with Pi `check_extent`/`translate`.
  - German message at the default user origin (30, 30), unknown origin / cutting bounds, and
    status parsing.
  - Panel hook: refusal, corner taken from the Pi, offline pass, placed origin / autorun / start.
  - History + autorun pass-through; a refused send is not recorded.
  - Main window send and estimate; one-click Start refusal.
- `tests/test_datamatrix.py` (93 + 1 skipped without pylibdmtx):
  - The ISO 16022 example „123456“ gives codewords 142 164 186 114 25 5 88 102.
  - Encodation unit tests (digit pairs, Upper Shift, ECI) and pad randomisation.
  - Reed-Solomon syndromes are zero for every block of every size.
  - Size choice and limits; finder, timing and region-separator patterns for all 24 sizes.
  - zxing-cpp decodes every size, Unicode/ECI text, the rendered vector shapes, the inverted
    shapes and the 0.1 mm hatch lines.
  - Module matrices are bit-identical to the zxing-cpp writer for ASCII-optimal texts up to
    144 × 144, with 6 and 10 interleaved blocks.
  - Geometry (area, bounds, no overlaps, group), errors, dialog, window action / menus /
    shortcut, one undo step, new fill layer, and G-code through the Pi guard.
- `tests/test_barcode.py` (+8):
  - Inverted geometry: background minus bars, margin, forced quiet zone, widened bars.
  - Digits cut out as holes.
  - zxing-cpp decodes inverted Code 128 / EAN-13 / EAN-8 from the light marking and from the
    0.1 mm hatch.
  - Dialog checkbox, and the window insert with one undo step and the Pi guard.

Full suite: 1175 passed, 3 skipped (pylibdmtx and the existing optional skips; before: 1052 passed, 2 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter – decide if wanted.
- Trace: true Bézier objects in the document (editable curve handles) would need a model change
  (Canvas); oblique thick crossings still split into two nearby junctions with a short bridge line.
- QR / barcode / Data Matrix / arc text are static vector objects (not re-editable after
  insertion; re-create via the dialog). Data Matrix: no rectangular sizes and no C40/Text/
  Base 256 encodation (ASCII only – digits are compact, long lowercase text needs larger
  symbols); PDF417 and Aztec not covered; GS1-128 / GS1 DataMatrix (FNC1) and Code 128 set A
  (control characters) not supported.
- Park corner on the canvas: Studio now checks and refuses, but the canvas does not draw the
  corner as a no-go zone yet and still shows the old 30 mm L-shaped safe-zone assumption
  (Canvas). Moving the user origin / anchor automatically out of the corner is not offered.
- Studio `PROBE_HEAD_MAX` (380, 360) follows the *default* travel 390 × 370; the Pi derives it
  from the configured travel (`/api/settings`, measured 370 × 360 on the owner's machine), so the
  Studio reach preview can be too optimistic there (Machine / Scan Probe).
- Windows hardware test of cut options, PDF import, image trace (incl. centre line and „Glätten“),
  QR code, barcode (incl. inverted) and Data Matrix readability on real material, the park-corner
  refusal against the real Pi, and the rebuilt exe – needs a Windows machine with the laser.

## 19. Status update 2026-11-02 (review round 12)

Done this round (Review; nothing from Canvas, Machine / Scan Probe or Materials touched):

- **Re-editable generated objects** (LightBurn / XCS: double-click a QR code or barcode to change
  its text). QR code, barcode, Data Matrix and arc text now store their generator parameters on
  every part (`Shape.generator`: kind, version, spec without position, original box). The model
  key is optional, so older Studio versions still open the files (they drop the key).
  - Double-click a part with the select tool, or „Code bearbeiten…“ (**Alt+E**, Design and
    Auftrag menus, no clash, no menu mnemonic) on the selection, opens the generator's own dialog
    pre-filled, titled „… bearbeiten“, OK button „Übernehmen“, no new-fill-layer option.
  - The new symbol replaces the old one in one undo step („QR-Code bearbeiten“ etc.) with the same
    centre, rotation, layer, enclosing groups and group id, and is selected afterwards.
  - A resize since insertion is carried over: QR / Data Matrix size × √(sx·sy); barcode module
    width × sx, bar and digit height × sy; arc text radius, height and spacing × k.
  - The group is found as the innermost group (`groups[-1]`), so it survives copy/paste, arrays
    and grouping with other objects. After ungrouping or a path operation the parts are plain
    polygons again. Mixed or individually rotated parts give a German message instead of an edit.
    A locked layer is refused.
  - Arc text replacing a grouped text now keeps its own group innermost (before, the arc group
    was put outside the replaced text's groups).

Tests:

- `tests/test_generated_edit.py` (15):
  - Meta shared on all parts, JSON / file round trip, unknown kind and newer version refused,
    unknown keys ignored.
  - Scale factors per kind; unit frame (centre, size, scale) after move + rotate + resize.
  - `find_unit` on plain / missing shapes, mixed or individually rotated parts, and after ungroup.
  - Window: edit a rotated QR code (one undo step, same group / centre / rotation / layer,
    zxing-cpp decodes the new text, G-code through the Pi guard, undo restores).
  - A resized Data Matrix pre-fills the scaled size and decodes after the edit.
  - Code 128 → EAN-13 edit decodes; arc text edit (bottom); copy/paste edits only the copy.
  - Outer group kept; kind change refused; messages for an empty or double selection, a locked
    layer, and too long text.
  - All four dialogs in edit mode reproduce the stored spec.
  - The double-click hook edits a code, and plain objects fall through.
  - Action / shortcut / menus.

Full suite: 1190 passed, 3 skipped (before: 1175 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter – decide if wanted.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- Data Matrix: no rectangular sizes, no C40 / Text / Base 256 encodation. PDF417 and Aztec are not
  covered. GS1-128 / GS1 DataMatrix (FNC1) and Code 128 set A are not supported.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Windows hardware tests (cut options, PDF import, trace, QR / barcode / Data Matrix readability
  incl. edited codes, park-corner refusal, rebuilt exe).

## 20. Status update 2026-11-02 (review round 13)

Done this round (Review; nothing from Canvas, Machine / Scan Probe or Materials touched):

- **GS1 element strings** (new `lumacut_job/gs1.py`, shared by GS1-128 and GS1 DataMatrix; LightBurn
  and XCS both offer GS1 codes for product / batch labels). Input is the printed form
  „(01)09501101530003(17)261231(10)AB-12“: AIs of 2–4 digits (fixed AI length for known prefixes),
  predefined fixed-length fields (01, 11–17, 20, 31xx … per GS1 table) must have exactly that length
  and digits only, mod-10 check digits are verified for (00), (01), (02), (410)–(417) with the
  correct digit in the German message, GS1 character set 82, variable fields ≤ 90 characters.
  FNC1 is inserted first and after every variable-length field except the last.
- **Barcode dialog** (Alt+C):
  - **Code 128 set A** – the encoder now uses a shortest-path choice over sets A / B / C, so ASCII
    control characters are encodable (printable text gives the same codewords as before). New
    checkbox „Steuerzeichen als \t \r \n \g \xHH eingeben (Code 128)“ (opt-in, stored in the spec,
    so existing texts with a backslash are unchanged): \t Tab, \n LF, \r CR, \e ESC, \g GS, \0 NUL,
    \xHH, \\ – for scanners that should send Tab / Enter. Human-readable line leaves control
    characters out.
  - **GS1-128** as new symbology: Start C/B + FNC1, FNC1 separators, max. 48 data characters,
    human-readable text with AIs in parentheses, quiet zone 10 modules.
- **Data Matrix dialog** (Alt+X):
  - **Encodation modes**: shortest mix of ASCII, C40, Text, X12 and Base 256 by a dynamic program
    over the input (ASCII wins ties, C40/Text/X12 in whole triples, Unlatch dropped when the data ends
    exactly at the symbol capacity, Base 256 with 255-state randomisation and 1/2-byte length).
    Typical gains: upper- or lower-case text one to two sizes smaller (e.g. 104 capitals: 40×40 →
    36×36). EDIFACT is not used (rarely shorter for engraving texts).
  - Non-ASCII text (incl. umlauts) is now UTF-8 behind ECI 26: zxing-based phone scanners showed
    short ISO 8859-1 umlaut texts as Shift JIS („ﾄﾖ“) – found while fuzzing.
  - **Rectangular sizes** 8×18, 8×32, 12×26, 12×36, 16×36, 16×48 (multi-region placement, own
    finder / separator pattern); combo „Automatisch quadratisch“, „Automatisch rechteckig“ or a
    minimum size (next larger one of the same shape; too long for 16×48 → hint to use a square size).
    „Breite“ is the width; the height follows from the module size; info line shows the height.
  - **GS1 DataMatrix**: checkbox „GS1-Daten“, FNC1 first (codeword 232), separators inside C40 / Text
    via Shift 2, decoded by zxing-cpp with symbology identifier ]d2.
  - Both options are part of the generator metadata, so „Code bearbeiten…“ (Alt+E) reopens rectangular,
    GS1 and Code 128 control-character codes with their settings.

Tests:

- `tests/test_gs1.py` (17): check digits, parse / HRI / whitespace, FNC1 sequence, 14 German error
  messages.
- `tests/test_barcode.py` (+9): escapes and their errors, set-A codewords, unchanged set B for printable
  text, GS1-128 codewords / limits / spec normalisation; zxing-cpp decodes control characters (]C0, raw
  text) and GS1-128 (]C1, HRI) from the rendered vector shapes; dialog checkbox and GS1 validation.
- `tests/test_datamatrix.py` (+29): ISO „AIM“ C40 / Text codewords, X12, Base 256 randomisation and
  2-byte length, smaller symbols than pure ASCII (zxing-decoded), 9 mixed-mode texts decoded as square and
  rectangle, all 6 rectangular sizes (structure, Reed-Solomon syndromes, zxing at capacity), symbol keys
  and auto rectangle, dropped trailing Unlatch (16×48 only fits because of it, decodes), GS1 DataMatrix
  (]d2, incl. FNC1 inside a C40 run), rectangular spec size / shapes / centring / describe, dialog,
  window insert with G-code through the Pi guard and edit round trip of a rectangular GS1 code.
- A random fuzz of 2 400 texts (all modes, square and rectangular) decoded with zxing-cpp without a
  mismatch (not part of the suite).

Full suite: 1245 passed, 3 skipped (before: 1190 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter – decide if wanted.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: PDF417 and Aztec are not covered; Data Matrix EDIFACT mode and DMRE sizes
  (ISO 21471) not supported; no GS1 Digital Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Windows hardware tests (cut options, PDF import, trace, QR / barcode / Data Matrix readability
  incl. edited, rectangular and GS1 codes with a real scanner, park-corner refusal, rebuilt exe).

## 21. Status update 2026-11-02 (review round 14)

Done this round (Review; nothing from Canvas, Machine / Scan Probe or Materials touched – the two
new layer fields go through the existing cut-option plumbing in `model.py` / `export.py`):

- Audit of the candidates: perforation / dot mode and overcut did not exist; Variable Text exists
  only as the batch „Seriennummern…“ (no CSV merge, no evaluation at send time); PDF417 is still
  missing. Perforation and overcut are standard LightBurn Cut Settings options (XCS has no
  equivalent) and matter for every diode cut, so they were picked over another symbology.
- **Overcut** (`Layer.overcut_mm`, 0–10 mm, `lumacut_job.cutpath.overcut_path`): closed contours
  are cut past their start point along the contour, so start and end overlap and no thread is left
  standing (diode cuts in plywood / card often hang on exactly that spot). At most one perimeter.
  With tabs the overcut stops 0.5 mm before the first tab (never cuts through a bridge); a
  lead-out starts at the end of the overcut on the waste side (contour rotated to that point).
  Open paths are unchanged.
- **Perforation mode** (`Layer.perf_cut_mm` / `perf_skip_mm`, 0–50 mm, `cutpath.perforate`):
  every line of the layer – closed contours, tab pieces, overcut and open paths – is cut
  `perf_cut_mm`, then skipped `perf_skip_mm` with the laser off (G0), pattern starting at each
  path start, rests under 0.01 mm dropped. Lead-in / lead-out and hatch fills stay continuous;
  the lead-in still joins the first piece without G0. Pieces after a gap have the new kind `perf`
  in `JobLayer.poly_kinds`. Short cuts (0.1–0.3 mm) give a dotted line – the practical substitute
  for LightBurn's *Dot Mode*, which would need laser-on dwells that the inline `M3 I` mode on the
  SKR does not fire.
- **Dialog „Schnittoptionen“** (Alt+K): new rows „Überschnitt“ („aus“ at 0), „Perforation
  Schnitt“ („aus“ at 0) and „Perforation Lücke“ (enabled only when perforation is on), German
  tooltips, „Zurücksetzen“ covers them; status summary e.g. „Überschnitt 0.8 mm, Perforation
  2.5/1.5 mm“. The fields are only written to the file when set, so older files and files without
  the options are byte-identical; values are clamped on load. Estimate, frame, path preview
  (parses the planner G-code) and „G-Code speichern“ follow automatically.

Tests:

- `tests/test_overcut_perforation.py` (16): perforation pattern on lines and around corners
  (vertices kept), off / short / tiny rest, dot line; overcut path, rotated start, closed-only
  overcut, overcut stops before the first tab (no bridge cut), overcut + lead-out on the waste side
  and joined; perforation kinds incl. open paths and continuous lead-in, perforated tab pieces and
  overcut; active flags; planner G-code through the Pi guard (cut length × 3/5, no S on G0),
  overcut adds exactly its length without extra G0, dot mode identical in every pass; layer
  round trip / defaults not written / clamping; dialog values, enable state, reset and summary.

Full suite: 1261 passed, 3 skipped (before: 1245 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter and CSV merge
  (LightBurn „Variable Text“ / „Merge CSV“) – decide if wanted; today only the batch
  „Seriennummern…“ exists.
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: PDF417 and Aztec are not covered; Data Matrix EDIFACT mode and DMRE sizes
  (ISO 21471) not supported; no GS1 Digital Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Windows hardware tests (cut options incl. overcut and perforation on card / plywood, PDF import,
  trace, QR / barcode / Data Matrix readability incl. edited, rectangular and GS1 codes with a real
  scanner, park-corner refusal, rebuilt exe).

## 22. Status update 2026-11-02 (review round 15)

Done this round (Review; nothing from Machine / Scan Probe or Materials touched; from the Canvas
area only the fill-box enable state and two tooltips in `layers_panel.py` – the new combo entry
comes from `hatch.FILL_MODES` automatically):

- Fresh audit against LightBurn / XCS (verified in code): image dithering modes, material test
  grid, start-from / job origin (absolute, current position, user origin with anchor), „nur
  Auswahl“ and cut options are present. Not present and not listed so far: **offset fill**
  (LightBurn *Offset Fill*), rotary and print-and-cut. Rotary needs extra hardware and
  print-and-cut needs camera registration (Machine / Scan Probe), so offset fill was picked: pure
  planner work, useful on every diode engraving of text, logos and round shapes, no user decision.
- **Offset-Füllung** (`fill_mode = "offset"`, `hatch.offset_fill_rings`): the even-odd area of a
  closed object (holes stay free) is offset inwards with Shapely – first ring half a line interval
  inside the edge (same convention as the hatch rows), then one interval deeper per ring until
  the area vanishes; holes get their own rings growing outwards, rounded concave corners with
  ≤ 0.02 mm chord error, rings simplified at 0.005 mm. Order: outside in; within one depth the
  nearest ring first, each started at the vertex nearest to the previous start (short travels).
  Parts narrower than one interval get no ring (the outline covers them when „Kontur mitlasern“
  is on); more than 5000 rings are refused like the 20 000-line hatch limit.
- **G-code**: rings go into `JobLayer.fills` as closed segment chains
  (`hatch.rings_to_segments`); `layers_to_gcode` now omits the `G0` when a fill segment starts
  exactly where the previous one ended, so each ring is one `G0` plus continuous `G1 … S`. Hatch
  and crosshatch output is byte-identical (their segments never chain). Passes, depth hook, fill
  only / with outline, planner, estimate, path preview, canvas fill preview and SVG/PNG export
  work unchanged; the Pi guard accepts the output.
- **Ebenen-Panel**: new entry „Offset-Füllung“ in „Füllmodus“; „Winkel“ and „Bidirektional“ are
  disabled for it (`hatch.LINE_FILL_MODES`), tooltips mention the offset contours. Saved as
  `fill_mode: "offset"` (older builds load such a layer as „Keine“).

Tests:

- `tests/test_offset_fill.py` (17): mode / label; square rings at 0.5, 1.5 … mm with exact
  perimeters and total length = area / interval; rings inside and at constant distance; holes free
  with their own ring; circle radii; two islands depth by depth with nearest start; thin parts,
  degenerate input, limits; closed segment chains, angle / bidirectional ignored; rect / ellipse /
  text fill inside the glyphs; G-code one `G0` per ring with layer power / speed and estimated
  cut length; passes with outline; crosshatch G-code still `G0`/`G1` per line; planner + Pi
  guard; reversed block breaks only between rings; file round trip; panel enable state, undo,
  summary; canvas preview.

Full suite: 1278 passed, 3 skipped (before: 1261 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter and CSV merge
  (LightBurn „Variable Text“ / „Merge CSV“) – decide if wanted; today only the batch
  „Seriennummern…“ exists.
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Offset fill: no LightBurn „fill groups together“ option (each object is filled on its own) and no
  inside-out order switch.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: PDF417 and Aztec are not covered; Data Matrix EDIFACT mode and DMRE sizes
  (ISO 21471) not supported; no GS1 Digital Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (offset fill on wood / card, cut options incl. overcut and perforation,
  PDF import, trace, QR / barcode / Data Matrix readability incl. edited, rectangular and GS1 codes
  with a real scanner, park-corner refusal, rebuilt exe).

## 23. Status update 2026-11-02 (review round 16)

Done this round (Review; nothing from Machine / Scan Probe or Materials touched; from the Canvas
area only two new rows in the fill box of `layers_panel.py`, and `export.py` / `fill_preview.py`
now take the fill blocks from one shared function):

- Fresh audit against LightBurn / XCS (verified in code): offset fill, dithering, material test,
  start-from / job origin, cut options, codes and arc text are present. Open fill gaps were
  LightBurn's per-layer fill grouping (*Fill shapes individually / Fill groups together / Fill all
  shapes at once*) – every object was filled on its own, so a circle drawn inside a rectangle was
  engraved twice instead of becoming a hole, overlapping objects burnt the overlap twice, and a
  row of separate objects was hatched object by object – and the offset fill order (rings only
  outside in, and with several islands the head bounced between them at every depth). No user
  decision needed, pure planner work, so both were picked.
- **Füllen** (`Layer.fill_grouping`, `hatch.FILL_GROUPINGS`): *Jedes Objekt einzeln* (default,
  output byte-identical to before), *Gruppen zusammen* (all fillable objects of the same top-level
  group form one area, ungrouped objects stay single) and *Alle Objekte zusammen* (the whole layer
  is one area). Applies to hatch, crosshatch and offset fill. Objects filled together follow the
  even-odd rule like LightBurn: nested objects become holes, overlaps stay free.
  `export.layer_fill_blocks(doc, layer)` returns `(shape ids, segments)` per block and feeds
  `job_layers`, the canvas fill preview and the SVG / PNG export (fill-only outlines are skipped
  for every object of a non-empty block); `shape_fill_segments` stays as the single-object helper.
- **Offset fill order**: islands of one fill area (e.g. the letters of a text) are now filled one
  after another, nearest island first, instead of depth by depth across all islands (far fewer
  long travels). New layer option *Von innen nach außen* (`Layer.offset_inside_out`) reverses the
  ring order per island (edge last). Offset blocks are marked `JobLayer.fill_fixed_order`, so
  `order_fill_blocks` never runs them backwards (before, a block could be reversed when its
  innermost ring was nearer to the head, silently turning the order inside out); hatch blocks
  still reverse to the nearer end.
- **Ebenen-Panel**: combo „Füllen“ (enabled when the layer fills) and check box „Von innen nach
  außen“ (enabled only for offset fill), one undo step each; the layer summary shows „alle
  zusammen“ / „Gruppen zusammen“. Saved as `fill_grouping` / `offset_inside_out` only when not
  default (older builds ignore them and fill individually / outside in).

Tests:

- `tests/test_fill_grouping.py` (14): groupings and labels; layer defaults, normalization and file
  round trip; individual = one block per object; together = frame with hole and overlap free (exact
  hatch length, nothing inside the hole); groups = per top-level group, nested sub-groups,
  ungrouped objects single; offset fill together follows the hole; open shapes / no fill; inside
  out ring order per island and in `fill_segments`, hatch unaffected; offset blocks never reversed
  in the G-code, hatch blocks still reversible; default output unchanged; G-code, planner, estimate
  and Pi guard for hatch / crosshatch / offset together; panel combo and check box enable state,
  undo and summary; canvas preview length; PNG export with hole and overlap free.
- `tests/test_offset_fill.py`: the islands test now expects island-by-island order.

Full suite: 1292 passed, 3 skipped (before: 1278 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter and CSV merge
  (LightBurn „Variable Text“ / „Merge CSV“) – decide if wanted; today only the batch
  „Seriennummern…“ exists.
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: no overscan; no per-object fill order optimisation across blocks (blocks run in object
  order, hatch blocks only flip to the nearer end); fill grouping does not cross layers.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: PDF417 and Aztec are not covered; Data Matrix EDIFACT mode and DMRE sizes
  (ISO 21471) not supported; no GS1 Digital Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (fill grouping and inside-out offset fill on wood / card, offset fill,
  cut options incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix
  readability incl. edited, rectangular and GS1 codes with a real scanner, park-corner refusal,
  rebuilt exe).

## 24. Status update 2026-11-02 (review round 17)

Done this round (Review; nothing from Machine / Scan Probe or Materials touched; from the Canvas
area only one new row „Überlauf“ in the fill box of `layers_panel.py`):

- Gap picked from §23 „Still open“: fill had no overscan and fill blocks always ran in object
  order. Both are pure G-code / planner work without a user decision.
- **Fill overscan** (`Layer.fill_overscan_mm`, 0–20 mm, `hatch.OVERSCAN_RANGE`, default 0 = output
  byte-identical to before): like LightBurn's *Overscanning*, every hatch / crosshatch line is
  extended at both ends with the laser off – `G0` to the extended start, `G1 … S0` run-in,
  `G1 … S<p>` the line, `G1 … S0` run-out – so the head is at speed when the beam switches on and
  line ends do not burn darker. `gcode.overscan_segment` shortens the extension at the edge of the
  cutting area, so the job never fails the bounds check or the Pi guard. Offset fill ignores it
  (rings run without stops; `JobLayer.fill_overscan_mm` is 0 there). Since the extension is real
  G-code, the time estimate and the path preview show it as travel and the park-corner check sees
  only the powered part.
- **Fill block order**: with the planner option „Leerfahrten reduzieren“ (`reduce_travel`, on by
  default) the fill blocks of a layer (per object, group or layer – §23) are now ordered nearest
  neighbour first (`planner.order_fill_blocks_nearest`) instead of in object order; hatch blocks may
  still run backwards, offset blocks (`fill_fixed_order`) are moved but never reversed. Contours of
  the layer start where the fill ends. Plain „G-Code exportieren“ without the planner is unchanged.
- **Fix**: `optimized_document_gcode` dropped a fill-only layer (outline off) when the document also
  had an image layer – the layer had no polylines and was not counted as vector work.
- **Ebenen-Panel**: spin box „Überlauf“ (special value „Aus“) after „Winkel“, enabled only for hatch
  / crosshatch, one undo step per edit; the layer summary shows „Überlauf X mm“. Saved as
  `fill_overscan_mm` only when not 0 (older builds ignore it).

Tests:

- `tests/test_fill_overscan.py` (14): defaults, normalization and file round trip; job layer gets
  the overscan only for line fills; default output unchanged and offset fill ignores it; overscan
  geometry for hatch 0° / 30° and crosshatch 45° (G0 → G1 S0 → G1 S → G1 S0, exact distance,
  collinear); Pi guard, estimate, powered bounds and longer job time; clamping at the work-area
  edge; path preview travel length; panel enable state, undo / redo and summary; nearest-neighbour
  block order cuts travel, `reduce_travel=False` keeps object order; offset blocks reordered but not
  reversed; contours start at the fill end; fill-only layer kept next to an image.

Full suite: 1306 passed, 3 skipped (before: 1292 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter and CSV merge
  (LightBurn „Variable Text“ / „Merge CSV“) – decide if wanted; today only the batch
  „Seriennummern…“ exists.
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; block order is greedy nearest neighbour (no 2-opt);
  overscan is clamped to the cutting area, not to the real machine travel.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: PDF417 and Aztec are not covered; Data Matrix EDIFACT mode and DMRE sizes
  (ISO 21471) not supported; no GS1 Digital Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (fill overscan – line ends even at 2–5 mm on wood / card – and
  nearest-neighbour block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix readability incl.
  edited, rectangular and GS1 codes with a real scanner, park-corner refusal, rebuilt exe).

## 25. Status update 2026-11-03 (review round 18)

Done this round (Review; nothing from Canvas, Machine / Scan Probe or Materials touched – only the
design-menu action list in `main_view.py` gained one entry):

- Gap picked from §24 „Still open“: 2D codes – Aztec was not covered (LightBurn and xTool Creative
  Space both offer it). No user decision needed and it fits the existing QR / Data Matrix framework;
  compact Aztec needs no quiet zone, which suits small laser-marked parts.
- **Aztec generator** (`lumacut_job/aztec.py`, no extra library), ISO/IEC 24778:
  - all 33 sizes – compact 15 × 15 … 27 × 27 (1–4 layers) and full-range 31 × 31 … 151 × 151
    (4–32 layers, reference grid); „Automatisch“ or a minimum size;
  - error correction 10–90 % (default 23 % + 3 words as recommended by ISO), Reed-Solomon over
    GF(64 / 256 / 1024 / 4096), mode message over GF(16), bit stuffing, bull's eye with
    orientation marks, layout identical to the zxing reference;
  - high-level encodation as a dynamic program over Upper / Lower / Mixed / Punct / Digit with
    latches, P/S and U/S shifts, the Punct pairs (CR LF, „. “, „, “, „: “) and Binary Shift runs
    (short and long form) – shortest bit stream, so texts fit into smaller symbols;
  - non-ASCII text as UTF-8 with ECI 26; option GS1 (FNC1 as FLG(0), same element-string check as
    GS1-128 / GS1 DataMatrix).
- **Studio**: „Aztec-Code…“ (*Alt+Z*, menu „Auftrag“ and design menu), dialog „Aztec-Code einfügen“
  with live info / warnings (size too small, work area, next larger size chosen), edge length
  without quiet zone, quiet zone (default 1 module), invert, new fill layer „Aztec“ (hatch 0.1 mm)
  when the active layer has no fill; one undo step. Aztec objects are re-editable like the other
  generated objects (`generated.py` kind „aztec“, dialog „Aztec-Code bearbeiten“, size follows a
  later scaling, saved in the file).

Tests:

- `tests/test_aztec.py` (81): mode codes, latches, shifts, Punct pairs, binary short / long form,
  ECI 26 prefix and GS1 FNC1; bit stuffing; RS syndromes zero in GF(16 … 4096); format table, bull's
  eye, orientation marks and reference grid; capacity (3832 digits in 151 × 151) and errors; every
  size filled to capacity decodes with zxing-cpp; module matrices identical to the zxing-cpp writer
  for unambiguous texts; mixed / Unicode / binary / random texts decode; GS1 decodes as `]z1`;
  12 flipped data modules are corrected; vector shapes (area, no overlap, quiet zone, inverted,
  hatch fill) decode; dialog warnings; window action, shortcut without clash, menus, insertion at
  the centre, undo, G-code with Pi guard, new fill layer; re-edit after scaling and file round
  trip.

Full suite: 1387 passed, 3 skipped (before: 1306 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter and CSV merge
  (LightBurn „Variable Text“ / „Merge CSV“) – decide if wanted; today only the batch
  „Seriennummern…“ exists.
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; block order is greedy nearest neighbour (no 2-opt);
  overscan is clamped to the cutting area, not to the real machine travel.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: PDF417 not covered; Aztec has no rune symbols and no structured append; Data Matrix
  EDIFACT mode and DMRE sizes (ISO 21471) not supported; no GS1 Digital Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (fill overscan – line ends even at 2–5 mm on wood / card – and
  nearest-neighbour block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec readability
  incl. edited, rectangular, compact 15 × 15 and GS1 codes with a real scanner, park-corner
  refusal, rebuilt exe).

## 26. Status update 2026-11-03 (review round 19)

Done this round (Review; nothing from Canvas, Machine / Scan Probe or Materials touched – only the
design-menu action list in `main_view.py` gained one entry):

- Gap picked from §25 „Still open“: 2D codes – PDF417 was not covered (LightBurn and xTool Creative
  Space both offer it). No user decision needed and it fits the existing QR / Data Matrix / Aztec
  framework; the wide, flat stacked code suits strips, edges and labels (IDs, shipping, boarding
  passes).
- **PDF417 generator** (`lumacut_job/pdf417.py`, no extra library), ISO/IEC 15438:
  - 1–30 columns („Automatisch“ picks a width / height ratio near 3 : 1) and 3–90 rows, up to 928
    codewords (2692 digits); start / stop patterns, left and right row indicators, the three
    codeword clusters (tables identical to the zxing reference);
  - Reed-Solomon over GF(929), error correction level 0–8, default „Automatisch“ per the ISO
    recommendation (level 2 … 5 by data length, lowered to at least 2 when the symbol would be too
    large);
  - high-level encodation: text compaction as a shortest path over Alpha / Lower / Mixed / Punct
    with latches and the PS / AS shifts, numeric compaction (base 900) for digit runs ≥ 13, byte
    compaction (901 / 924) and the 913 byte shift for single bytes inside text;
  - non-ASCII text as UTF-8 with ECI 26; option compact PDF417 (no right row indicator, one-module
    stop);
  - row height in modules (default 3 = ISO minimum), quiet zone (default 2 modules), invert.
- **Studio**: „PDF417-Code…“ (*Alt+F*, menu „Auftrag“ and design menu), dialog „PDF417-Code
  einfügen“ with live info / warnings (modules too narrow / under 0.4 mm, row height under 3,
  error correction under the ISO recommendation, quiet zone under 2, too many rows, work area),
  width without quiet zone, new fill layer „PDF417“ (hatch 0.1 mm) when the active layer has no
  fill; one undo step. PDF417 objects are re-editable like the other generated objects
  (`generated.py` kind „pdf417“, dialog „PDF417-Code bearbeiten“; width follows a later X scaling,
  row height the Y / X ratio; saved in the file).

Tests:

- `tests/test_pdf417.py` (60): codeword tables (cluster rule, start / stop), text submodes with
  latches and shifts, numeric (ISO example) and byte compaction (901 / 924, 913 shift), segmenting
  and ECI 26; RS roots for all levels and the ISO Annex example; ISO level recommendation; row
  layout, length descriptor, pads and row indicators, compact layout; columns / rows / auto ratio,
  maximum capacity and errors; zxing-cpp decodes fixed, Unicode, binary and 60 random texts, every
  level, 1–30 columns normal and compact, the largest symbol and a damaged symbol; vector shapes
  (area, no overlap, quiet zone, inverted, hatch fill) decode; dialog warnings; window action,
  shortcut without clash, menus, insertion at the centre, undo, G-code with Pi guard, new fill
  layer; re-edit after non-uniform scaling and document file round trip.

Full suite: 1447 passed, 3 skipped (before: 1387 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter and CSV merge
  (LightBurn „Variable Text“ / „Merge CSV“) – decide if wanted; today only the batch
  „Seriennummern…“ exists.
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; block order is greedy nearest neighbour (no 2-opt);
  overscan is clamped to the cutting area, not to the real machine travel.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode and DMRE
  sizes (ISO 21471) not supported; PDF417 has no Macro PDF417 (structured append) and no
  MicroPDF417; no GS1 Digital Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (fill overscan – line ends even at 2–5 mm on wood / card – and
  nearest-neighbour block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417 readability
  incl. edited, rectangular, compact 15 × 15, GS1 and (compact) PDF417 codes with a real scanner, park-corner
  refusal, rebuilt exe).

## 27. Status update 2026-11-03 (review round 20)

Done this round (Review; nothing from Canvas, Machine / Scan Probe or Materials touched – the G-code
writer is unchanged):

- Gaps picked from §26 „Still open“: the fill block order was greedy nearest neighbour only, and
  Data Matrix had no DMRE sizes. Neither needs a user decision.
- **Fill block order: 2-opt / Or-opt** (`lumacut_job/planner.py`, `improve_fill_block_order`), run by
  the planner („Leerfahrten reduzieren“) after the nearest-neighbour order of commit 0cd8cbe:
  - moves: 2-opt segment reversal and Or-opt moves of 1–3 consecutive blocks (optionally reversed,
    or to the front), tried only towards the 8 nearest blocks; first improvement, repeated until no
    move helps;
  - entry direction: the cost uses the same rule as `gcode.order_fill_blocks` (a block is entered
    at its nearer end, reversed only for hatch / scanline blocks), and the result is emitted in
    that orientation – the first pass lasers exactly the planned tour, later passes keep the
    writer's own re-orientation;
  - constraints kept: per layer, blocks stay whole (no segment is moved between blocks), offset
    rings (`fill_fixed_order`) are never reversed; never longer than the greedy order;
  - bounded and deterministic: a fixed work budget (1 000 000 block steps, no wall clock), over
    2000 blocks the greedy order is kept; ≈ 0.2–0.6 s for 300–1500 blocks. Random layouts: about
    20 % less travel at 100 blocks, 9 % at 300, under 1 % at 1000 (greedy is already good there).
  - Not covered: a free start corner inside a block (only reversal), overscan length in the cost.
- **Data Matrix DMRE** (`lumacut_job/datamatrix.py`, ISO/IEC 21471): the 18 rectangular sizes 8 × 48
  … 8 × 144, 12 × 64, 12 × 88, 16 × 64, 20 × 36 … 20 × 64, 22 × 48, 24 × 48, 24 × 64, 26 × 40 …
  26 × 64 (one Reed-Solomon block each; row wrap in the placement for the 26-row sizes as in
  zxing-cpp). New choice „Automatisch rechteckig inkl. DMRE“ (smallest rectangle by data, then area);
  „Automatisch rechteckig“ stays ISO/IEC 16022 only. A fixed DMRE size that is too small grows to the
  next DMRE size of the same height first. Dialog lists the sizes as „… Module DMRE“ and hints to
  test the own scanner; re-edit and file round trip unchanged.

Tests:

- `tests/test_fill_block_order_opt.py` (12): travel never above greedy and clearly below it on
  random hatch / offset blocks, a textbook case where greedy leaves a block behind, blocks whole and
  offset blocks never reversed, the G-code writer keeps the planned order, determinism, trivial
  inputs, budget 0 / small budget and the block limit, runtime at 1500 blocks, sent G-code (hatch and
  offset, 2 passes) with less travel, same cut length and Pi guard, `optimize_layers` with and
  without „Leerfahrten reduzieren“.
- `tests/test_datamatrix.py` (+27): DMRE table geometry, zxing-cpp decodes every DMRE size
  (structure and RS), auto DMRE vs. auto rectangular and explicit sizes, vector shapes (incl. Unicode,
  hatch fill) decode, GS1 in DMRE (`]d8`), dialog entries / info, window insert, G-code with
  Pi guard, re-edit and file round trip.

Full suite: 1486 passed, 3 skipped (before: 1447 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- Variable text evaluated at send time with an auto-incrementing counter and CSV merge
  (LightBurn „Variable Text“ / „Merge CSV“) – decide if wanted; today only the batch
  „Seriennummern…“ exists.
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; block entry is only „start or end“ (no free start
  corner inside a block); overscan is clamped to the cutting area, not to the real machine travel.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417; no GS1 Digital
  Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417 readability
  incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes with a real scanner,
  park-corner refusal, rebuilt exe).

## 28. Status update 2026-11-03 (review round 21)

Done this round (Review/Job layer; Canvas, Machine / Scan Probe and Materials untouched apart from
one entry in the design-menu list in `lumacut_canvas/main_view.py`):

- Gap picked from §27 „Still open“: **variable text** evaluated at send time (LightBurn „Variable
  Text“ / „Merge CSV“). Fits the existing model without a format change: the template stays in
  `Shape.text`, the settings live in `Shape.generator` (`kind: "vartext"`), so file save / load
  round-trips the template and the stored counter.
- `lumacut_job/vartext.py` (pure Python):
  - placeholders `{n}`, `{n:3}`, `{date}` / `{date:FMT}`, `{time}` / `{time:FMT}` (whitelisted
    strftime codes `%d %m %Y %y %H %M %S %j %V %%`), `{row}`, CSV columns `{Name}` (case-insensitive
    fallback), `{csv:Name}`, `{csv:2}`, literal `{{` `}}`; unknown column, missing file or a row past
    the end raise a German `VarTextError` (a `ValueError`) – a job is never sent with literal
    placeholders;
  - CSV: delimiter sniffed from the header line (`;` `,` Tab `|`), UTF-8 (BOM) then Windows-1252,
    empty lines skipped, cached by mtime / size, 20 MB / 200 000 rows limit;
  - `evaluate_document`: job document with evaluated copies (original untouched, layers shared),
    only visible layers, copies of one series in reading order get consecutive values / rows
    (`per_copy`), the width follows the text with the left-mid anchor fixed in the rotated frame,
    blank results are left out; `advanced_spec` for the next job.
- `lumacut_job/qt_tools.py`: `job_document()` / `job_gcode()` evaluate, so send, „Senden &
  Starten“, one-click / scan job, G-code save, frame, estimate and the canvas path preview all use
  the evaluated text; the planner note shows „Variabler Text: Nr. 007 … Nr. 009“.
- Advancing (`lumacut_job/vartext_qt.py`, `VarTextTracker`, outermost wrapper of
  `MachinePanel.send_gcode` after history and park check): a built job carries
  `; VARIABLE TEXT <token>`; only an upload of exactly that job that the panel reports as done
  (`command_finished(label, True)` and `_uploaded == name`) advances counter / CSV row – one undo
  step, document marked modified. Refused (park corner), not dispatched, failed upload, failed start,
  history re-send and plain G-code files never advance.
- Dialog „Variabler Text…“ (*Alt+V*, menu „Auftrag“ and design menu): on/off, template with
  help, counter (start, step, digits, next value, „Auf Start“, copies consecutive), CSV merge (file,
  remove, next row, advance per send, table preview with click-to-select row), live preview of the
  next job incl. errors. Applies to the selected texts plus the rest of their series; one undo step;
  locked layers refused. Double click still edits the template text; `generated.find_unit`
  ignores variable text.
- „Seriennummern…“ integration: new option „Beim Senden weiterzählen (variabler Text)“ – the copies
  keep the template and become one series (first job start … start + (count − 1) × step, then
  continuing); a literal batch made from a variable text drops the vartext marker.

Tests:

- `tests/test_variable_text.py` (27): tokens, date / time formats, errors, CSV delimiters,
  quoting, BOM / cp1252, cache, spec meta (future version, clamping), advance rules, job document
  (texts, widths, rotated anchor, reading order, CSV rows, blank copies, hidden layer, separate
  series, per-copy off), file round trip, G-code equal to the literal text with Pi guard, marker,
  tracker (failed / refused / not dispatched / failed start / other labels / history re-send /
  undo / no signal), apply + undo + locked layer, dialog with CSV table, window action / shortcut /
  menus / `job_gcode` / advance / save dict / switch off, send refused with an error, serial
  variable mode (window and dialog).

Full suite: 1513 passed, 3 skipped (before: 1486 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; block entry is only „start or end“ (no free start
  corner inside a block); overscan is clamped to the cutting area, not to the real machine travel.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: no per-object counter shown on the canvas (the template is drawn, the values
  are in the dialog / path preview); „Text in Pfade“ converts the template literally; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417; no GS1 Digital
  Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417 readability
  incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes with a real scanner,
  park-corner refusal, variable text / CSV merge over several sends, rebuilt exe).

## 29. Status update 2026-11-03 (review round 22)

Done this round (Review/Job layer; Canvas, Machine / Scan Probe and Materials untouched apart from
one new `JobLayer` field in `lumacut_canvas/export.py` and the line shift in
`lumacut_canvas/gcode.py`):

- Gap picked: **scanning offset adjustment** (LightBurn „Scanning Offset Adjustment“, xTool
  bidirectional calibration). At high bidirectional speeds a diode laser fires late in the
  direction of travel, so forward and return lines are offset and vertical edges look ragged.
  `RasterSettings.scan_offset_mm` existed in the image engine but nothing set it, and hatch fills had
  no compensation at all. Picked over the remaining §28 fill items (cross-layer grouping, free start
  corner, travel-clamped overscan) because it is a core calibration for fast diode engraving.
- `lumacut_job/scan_offset.py` (pure Python):
  - `ScanOffsetTable`: speed (mm/min) → offset (mm), up to 32 entries, 1–6000 mm/min, −2…2 mm,
    no duplicate speeds; linear interpolation, nearest entry outside the table (no extrapolation);
    JSON round trip (version 1); German summary for the planner note.
  - Process-wide active table (`active_table` / `set_active_table`, default off).
  - Calibration pattern `ScanTestSpec` / `test_pattern_layers` / `test_pattern_gcode`: one row of
    hatch patches per speed, one column per trial offset (each patch carries its own fixed offset,
    `fill_fixed_order`), text labels; validated against the work area; G-code header comment
    lists the column offsets.
- Model: every scan line moves by **half** the offset against its own direction of travel, so the
  engraving stays centred on the contour and the rule is direction-independent (unidirectional
  hatch is shifted too, consistent with images). The shift is shortened at the cutting-area edge;
  overscan is added after the shift. Contours and offset fill (rings) are not shifted.
- `lumacut_canvas/gcode.py`: `scan_offset_segment` and `JobLayer.fill_scan_offset_mm` (applied to
  hatch / crosshatch lines before overscan). `lumacut_job/images.py`: `image_job(…, scan_offsets)`
  sets `RasterSettings.scan_offset_mm` from the image speed and shifts the origin by −offset/2
  (clamped to edge room).
- `lumacut_job/planner.py`: `optimized_document_gcode` applies the active table by default (send,
  save, estimate, path preview, workflow and scan job pick it up without call-site changes);
  `PlanReport.scan_offset` is appended to the planner note. With the table off the G-code is
  byte-for-byte unchanged.
- UI (`lumacut_job/scan_offset_qt.py`, `qt_tools.py`): toolbar / menu „Auftrag“ action
  „Scan-Versatz…“ – on/off, editable table (comma decimals accepted), live check „Prüfen bei …
  mm/min“, validation disables OK; stored in QSettings `job/scan_offset` (machine setting, not in
  the document). „Testmuster…“ dialog: speeds, offset range / step, power, line interval, patch
  size, position, labels; „Senden (ohne Start)“ uploads `scan-versatz-test.gcode` without starting,
  „Speichern…“ writes a file.

Tests:

- `tests/test_scan_offset.py` (33): table normalisation / errors / interpolation / JSON, default
  off, segment shift and edge clamp, bidirectional hatch shift, overscan after shift, planner with
  active table (offset fill and contours unchanged, off = identical G-code, report note), images
  (half shift per direction, edge clamp), test pattern layers / G-code with Pi guard, spec errors,
  settings round trip, dialog editing and check label, test dialog callbacks, window action /
  menu / job note / save / send without start.

Full suite: 1546 passed, 3 skipped (before: 1513 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; block entry is only „start or end“ (no free start
  corner inside a block); overscan is clamped to the cutting area, not to the real machine travel.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the canvas fill preview
  (`fill_preview`) shows unshifted lines (the path preview shows the shift); the test pattern is
  not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: no per-object counter shown on the canvas (the template is drawn, the values
  are in the dialog / path preview); „Text in Pfade“ converts the template literally; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417; no GS1 Digital
  Link / GS1 QR code.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (scan offset test pattern and compensated bidirectional hatch / image at
  3000–6000 mm/min, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417 readability
  incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes with a real scanner,
  park-corner refusal, variable text / CSV merge over several sends, rebuilt exe).

## 30. Status update 2026-11-03 (review round 23)

Done this round (Review/Job layer; Canvas, Machine / Scan Probe and Materials untouched):

- Gap picked from §29 „Still open“: **GS1 QR code and GS1 Digital Link** (LightBurn and xTool
  Creative Space offer QR codes; GS1 Digital Link QR codes are the format retail moves to with
  „Sunrise 2027“, so product makers who mark packaging or wooden / metal products need them).
  Picked over the remaining fill / scan-offset items because it is self-contained in the Job
  layer, needs no user decision and closes a 2D-code gap next to the existing GS1-128 / GS1
  DataMatrix; Data Matrix EDIFACT and MicroPDF417 are rarely needed for laser marking.
- `lumacut_job/gs1_link.py` (pure Python, GS1 Digital Link URI Syntax 1.x):
  - `build(element_string, domain)`: exactly one primary key (GTIN 01, ITIP 8006, GMN 8013,
    CPID 8010, GLN 414 / 415 / 417, SSCC 00, GDTI 253, GCN 255, GINC 401, GSIN 402, GRAI 8003,
    GIAI 8004, GSRN 8017 / 8018) in the path, its key qualifiers in the prescribed order (GTIN:
    22, 10, 21 or 235), all other AIs as query parameters in input order; values percent-encoded
    except RFC 3986 unreserved characters; values checked with `gs1.parse` (fixed lengths, digits,
    check digits, character set 82).
  - `normalize_domain`: default `https://id.gs1.org`, scheme added, host lower-cased, optional
    path prefix, no query / fragment; German errors.
  - `parse(uri)`: any domain with a path prefix, finds the primary key, checks qualifier order,
    rejects keys in the query, keeps non-AI parameters (`linkType`) separately, ignores the
    fragment; `resolve(text, domain)` accepts an element string (built) or a complete URI (encoded
    verbatim after validation); `describe` for the dialog.
- `lumacut_job/qr.py`:
  - mixed segments (numeric / alphanumeric / byte) with a shortest-bit dynamic programme per
    version class (`segments`, `segment_bits`, `encode_items`), version chosen from the exact
    bit length;
  - **GS1 QR code** (`encode_gs1`): mode indicator „FNC1 in first position“ (0101), FNC1
    separators as „%“ in alphanumeric segments (literal „%“ doubled) or GS (0x1D) in byte
    segments; scanners report `]Q3` and the GS1 element string;
  - **Digital Link** (`encode_link`): the URI with mixed segments (the GTIN digits go numeric);
  - `QrSpec.mode` („text“ / „gs1“ / „link“) and `QrSpec.domain` appended to the dataclass
    (positional callers unchanged), `QrSpec.content()` / `encode()`, `content_info` for the
    dialog. Plain text mode is byte-for-byte unchanged (still one byte segment, the existing
    reference matrices still match).
- Generated objects: mode and domain are part of the generator spec, so files, autosave and
  „Code bearbeiten“ (*Alt+E* / double click) keep the kind; older files without the fields open
  as plain text QR codes.
- Dialog „QR-Code einfügen“: new row „Art“ (Text / Adresse, GS1 QR-Code (Elementstring), GS1
  Digital Link (Web-Adresse)), „Domain“ (only for Digital Link), „Beispiel“ button, a line with
  the encoded data / the resulting address, placeholder and tooltip per kind; invalid GS1 data or
  domain disables „Einfügen“ with the German message. Status line „GS1 QR-Code eingefügt …“ /
  „GS1-Digital-Link-QR-Code eingefügt …“.

Tests:

- `tests/test_gs1_qr.py` (25): Digital Link build (qualifier order, query attributes,
  percent-encoding, SSCC / GLN keys), domain variants and errors, build errors (no / two primary
  keys, duplicate AI, 21 + 235, check digit, no brackets), parse round trip with prefix /
  `linkType` / fragment and parse errors, resolve; segment choice (byte + numeric, alphanumeric,
  FNC1 as „%“ / GS, literal „%%“); GS1 QR data streams and Digital Link URIs read back with an
  independent matrix reader in the test (unmasking, de-interleaving, Reed-Solomon check, segment
  parser) for all EC levels, versions ≥ 10 and all masks; compactness vs. byte mode; capacity
  and input errors; text mode unchanged; spec normalisation and positional arguments; zxing-cpp
  decode (`]Q3` with GS1 text, `]Q1` URIs – skipped without zxing-cpp, pass with it); generator
  meta round trip incl. old meta; dialog kinds / domain / example / errors / edit mode; window
  insert of both kinds, G-code with Pi guard, edit keeps kind and domain.

Full suite: 1571 passed, 3 skipped (before: 1546 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; block entry is only „start or end“ (no free start
  corner inside a block); overscan is clamped to the cutting area, not to the real machine travel.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the canvas fill preview
  (`fill_preview`) shows unshifted lines (the path preview shows the shift); the test pattern is
  not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: no per-object counter shown on the canvas (the template is drawn, the values
  are in the dialog / path preview); „Text in Pfade“ converts the template literally; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes still use one byte segment (mixed segments only for the GS1 kinds); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (GS1 QR / Digital Link codes with a GS1 scanner and a phone camera,
  scan offset test pattern and compensated bidirectional hatch / image at
  3000–6000 mm/min, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417 readability
  incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes with a real scanner,
  park-corner refusal, variable text / CSV merge over several sends, rebuilt exe).

## 31. Status update 2026-11-03 (review round 24)

Done this round (Review/Job layer + fill G-code; Canvas widgets, Machine / Scan Probe and Materials
untouched):

- Gap picked from §30 „Still open“: **free start corner inside fill blocks** (LightBurn and xTool
  Creative Space start a hatched shape at whichever corner is nearest; LumaCut could only enter a
  block at its first or last segment, so with an even / odd row count the head often crossed the
  whole block before the next one).
- `lumacut_canvas/hatch.py`:
  - `fill_block_rows`: splits a hatch block into rows (consecutive collinear segments in the same
    direction – holes split a row into several segments, crosshatch blocks give the rows of both
    angles);
  - four variants `FORWARD`, `REVERSED` (the old „reverse“), `ROWS_REVERSED` (rows from the other
    side, each row keeps its direction) and `ROWS_FLIPPED` (rows in order, every row reversed);
    bidirectional blocks keep their back-and-forth, unidirectional blocks keep one scan direction
    (both corner variants are pure transformations of the existing rows);
  - `fill_block_entries` / `fill_block_variant` / `nearest_fill_entry`: corner entries only for
    blocks with at least two rows; on a tie the earlier variant wins, so the old start / end
    choice is kept wherever it was already optimal.
- `lumacut_canvas/gcode.py`: `order_fill_blocks(..., corners=False)` uses the same entry rule;
  `layers_to_gcode` enables corners per layer via the new `JobLayer.fill_free_corner`
  (`lumacut_canvas/export.py`: set for hatch / crosshatch, never for offset fill – ring order
  stays fixed). Overscan and scan offset are applied per segment after the variant is chosen, so
  they follow the new direction automatically.
- `lumacut_job/planner.py`: nearest-neighbour order and the 2-opt / Or-opt pass work on up to four
  entries per block (`_block_neighbours` generalised, entry rule identical to the writer), so pass
  1 lasers exactly the planned order; same budget, deterministic, 1500 blocks well under the time
  limit.
- Overscan clamp to the real machine travel: **not implemented**. Studio has no travel setting;
  the travel (390 × 370 mm) only exists as Machine-owned constants (`machine/client.py`,
  `scanprobe/reach.py`) and in the Pi config (`travels`). The high side of the cutting area
  (X30…390 / Y30…370) already equals the travel, so the only gain would be overscan into the
  30 mm safe-zone bands (X < 30 / Y < 30, homing zone incl. the park corner). That breaks the
  invariant „all coordinates inside the cutting area“ and needs a **user decision** whether
  laser-off overscan may enter the safe zone.

Tests:

- `tests/test_fill_block_corners.py` (28): row detection with holes and crosshatch; variants ×
  bidirectional / unidirectional keep the scan rule and give the right entries / exits; entries
  per block kind (single row, offset); nearest entry and tie rule; textbook row of blocks with an
  odd row count (< 0.8 of the old travel, corner variants used), 6 × 6 tile grid (< 0.75), random
  layouts (never worse); writer order equals plan with corners; fixed order ignores corners;
  determinism and runtime (1500 blocks); `fill_free_corner` only for hatch / crosshatch; sent
  G-code passes the Pi guard, travel < 0.85 of the old order, pass-1 burns equal the plan;
  overscan and scan offset follow the chosen direction; offset fill and single-block output
  byte-for-byte unchanged.

Full suite: 1599 passed, 3 skipped (before: 1571 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see above); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the canvas fill preview
  (`fill_preview`) shows unshifted lines (the path preview shows the shift); the test pattern is
  not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: no per-object counter shown on the canvas (the template is drawn, the values
  are in the dialog / path preview); „Text in Pfade“ converts the template literally; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes still use one byte segment (mixed segments only for the GS1 kinds); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (GS1 QR / Digital Link codes with a GS1 scanner and a phone camera,
  scan offset test pattern and compensated bidirectional hatch / image at
  3000–6000 mm/min, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options
  incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417 readability
  incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes with a real scanner,
  park-corner refusal, variable text / CSV merge over several sends, rebuilt exe).

## 32. Status update 2026-11-03 (review round 25)

Done this round (Review/Job layer, shared G-code helper and a minimal hook in the canvas fill
preview; Machine / Scan Probe and Materials untouched):

- Gap 1 from §31 „Still open“: **canvas fill preview shows the scan offset** (before, the path
  preview and the G-code shifted every hatch line by half the offset, the fill preview on the
  canvas did not – preview ≠ output).
  - `lumacut_canvas/gcode.py`: the fill loop of `layers_to_gcode` is now `_fill_moves` (block
    order incl. free start corner, scan offset, overscan); the writer and the new
    `fill_burn_segments(layers)` share it. `fill_burn_segments` replays the writer's head
    position over all layers, passes and contours and returns the burned fill lines of pass 1 per
    layer. G-code output is byte-for-byte unchanged (checked against the previous commit with and
    without a table, all fill kinds).
  - `lumacut_job/scan_offset.py`: `preview_fill_lines(doc)` – `None` when the table is off or no
    hatch / crosshatch layer has a non-zero offset at its speed (offset fill and fixed-order
    layers are never shifted); otherwise it plans the job exactly like sending
    (`optimize_layers` + `apply_to_layers`) and maps the burned lines back to canvas mm.
    Single-entry cache keyed by the job layers and the table, so edits that do not change the
    job (colour, names, selection) reuse the plan.
  - `lumacut_canvas/fill_preview.py`: `rebuild()` asks the helper (lazy import, as in the path
    preview) and draws the shifted lines; on error or without a table the old geometry is used.
    New flag `scan_offset_applied`. `lumacut_job/qt_tools.py`: loading / changing the table
    refreshes the fill preview as well as the path preview.
  - Cost: with an active table each fill-preview rebuild runs the planner (≈ 0.4 s for 100,
    ≈ 1.2–1.6 s for 1500 hatched objects on the dev box, GUI thread after the 120 ms debounce);
    unchanged job → cached (≈ 0.05 s). Without a table nothing changes.
- Gap 2 from §31: **plain-text QR codes use optimal mixed segments** (numeric / alphanumeric /
  byte, the same DP as the GS1 kinds, `qr.mixed_bits` / `text_segments` / `encode_text`).
  - Compatibility rule: mixed segments are only used when they give a **smaller version** than
    one byte segment; otherwise the matrix stays bit-identical to before (reference matrices and
    e.g. lower-case https URLs unchanged). Non-ASCII text always stays one UTF-8 byte segment
    (no ECI; scanners guess the charset per segment).
  - Examples: „HTTPS://LUMACUT.EXAMPLE/P/4711“ M 3 → 2, 35 digits M 3 → 2, URL with a long
    serial M 4 → 3, Wi-Fi string Q 4 → 3, 1000 digits L 22 → 13; capacity now 7089 digits /
    4296 alphanumerics at L 40.
  - Output change for old files: none on opening (documents store the module polygons). Only
    „Code bearbeiten“ re-encodes; a re-edited plain-text code whose content profits from mixed
    segments then gets a smaller version (other module pattern, same content). The dialog shows
    the segments („Segmente: Byte 16, numerisch 14, …“).

Tests:

- `tests/test_fill_preview_scan_offset.py` (17): `None` cases (table off, zero offset, offset
  fill, no fill); bidirectional lines shift ±offset/2 against travel, unidirectional all the same
  way; preview = pass-1 burns of the planned G-code for bidirectional, unidirectional,
  crosshatch, angled, overscan, 3 passes + outline, grouping „together“ and several layers /
  speeds (offset-fill layer unshifted); clamp at the cutting-area edge; cache reuse and
  invalidation; `fill_burn_segments` = writer; canvas widget draws shifted lines, flag, hidden
  layer, fallback on planner error; window: changing the table schedules the fill preview.
- `tests/test_qr_text_segments.py` (34): version reductions, unchanged matrices without gain,
  non-ASCII stays byte, capacity, `min_version` / mask honoured, DP never worse than one mode
  (random), decoding with OpenCV and zxing (also hatch-filled), dialog info, rebuild of an old
  byte code unchanged.

Full suite: 1650 passed, 3 skipped (before: 1599 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the fill preview shows
  pass 1 only and runs the planner on the GUI thread (≈ 1 s per job change at ~1500 hatched
  objects – a background thread would be the next step if that hurts); the test pattern is not
  yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: no per-object counter shown on the canvas (the template is drawn, the values
  are in the dialog / path preview); „Text in Pfade“ converts the template literally; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (GS1 QR / Digital Link codes with a GS1 scanner and a phone camera,
  plain-text QR codes with mixed segments, scan offset test pattern and compensated bidirectional
  hatch / image at 3000–6000 mm/min incl. the shifted fill preview, fill overscan – line ends even
  at 2–5 mm on wood / card – and 2-opt block order, fill grouping and inside-out offset fill,
  offset fill, cut options incl. overcut and perforation, PDF import, trace, QR / barcode / Data
  Matrix / Aztec / PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and
  (compact) PDF417 codes with a real scanner, park-corner refusal, variable text / CSV merge over
  several sends, rebuilt exe).

## 33. Status update 2026-11-04 (review round 26)

Done this round (Review/Job layer, the fill-preview module and the canvas overlay hook; no
change to the canvas widget, Machine / Scan Probe and Materials untouched):

- Gap from §32 „Still open“ (scan offset): **the fill preview plans the scan offset in a
  background thread** (before: ≈ 1–1.6 s frozen GUI per job change at ~1500 hatched objects).
  - `lumacut_job/planner.py`: optional `should_stop` callable for `optimize_layers`,
    `order_polylines`, `order_fill_blocks_nearest` and `improve_fill_block_order`; a true result
    raises `PlanCancelled`. Without it the output is unchanged (G-code byte-for-byte).
  - `lumacut_job/scan_offset.py`: `preview_fill_request(doc)` builds the job layers on the GUI
    thread and returns `None` (no shift), the cached lines, or a `FillPreviewJob` whose `run()`
    holds no Qt objects and can run in a worker thread; the cache is guarded by a lock.
    `preview_fill_lines` is now request + synchronous run (same result).
  - `lumacut_canvas/fill_preview.py`: `rebuild()` first draws the plain geometry, then starts a
    daemon worker (starting it after drawing avoids GIL contention: GUI part 0.52 s → 0.13 s at
    1500 objects); a 25 ms timer on the GUI thread collects the result and draws the shifted
    lines. A new edit (debounce) cancels the running plan and bumps a generation counter, so a
    stale plan is never drawn; worker errors keep the plain geometry. `busy()`, `wait()`,
    `background_runs`, `scan_offset_pending`; `BACKGROUND = False` keeps the old synchronous
    path. Preview = output stays guaranteed (same planner call as sending).
- Gap from §32 (variable text): **the canvas shows the next value of every variable text**
  (LightBurn draws the evaluated text; LumaCut drew only the template).
  - `lumacut_job/vartext.py`: `preview_values(doc, now)` → `{shape_id: PreviewValue(text,
    error)}` with exactly the job evaluation (series, reading order, copies in a row, CSV row,
    hidden layers skipped); an error only marks its own series. `evaluate_document` shares the
    series code (`_series_members`, `_series_texts`), output unchanged. `uses_clock(template)`.
  - `lumacut_job/vartext_preview.py`: overlay on `editor.add_overlay` (z 60, never in export /
    G-code): a small label under each object („→ Nr. 042“, green; „⚠ …“ red for errors; above
    the object at the bottom edge; height 1.6–5 mm with the zoom), debounced on document /
    selection changes, refreshed every 30 s while a template uses date / time. Source is the
    Studio's job source, so „Nur Auswahl“ shows the values the selected objects really get.
  - `lumacut_job/qt_tools.py`, `vartext_qt.py`: checkbox „Nächste Werte auf der Arbeitsfläche
    anzeigen“ in the dialog, persisted (`vartext/show_values`).

Tests:

- `tests/test_fill_preview_background.py` (12): `should_stop` unchanged / raises / stops mid-plan
  in all ordering functions; request kinds and copies, run in a worker thread = synchronous
  lines and G-code; widget: plain lines drawn at once, shifted lines from a non-GUI thread equal
  `preview_fill_lines`, cached rebuild without a new run, poll timer in the event loop, edit
  while planning cancels, stale result never drawn, worker errors, synchronous mode, 1500-object
  rebuild returns before the planner finishes. `tests/test_fill_preview_scan_offset.py` waits for
  the worker.
- `tests/test_vartext_canvas_values.py` (11): values = job document texts, date / CSV row /
  per-series errors / hidden layer, `evaluate_document` unchanged, label text (truncation,
  newlines, empty, error), label position / height / colour / painting, label above at the
  bottom edge, debounce and enable / disable, clock timer only with date / time, settings
  roundtrip, window: copies in a series, „Nur Auswahl“, toggle; dialog checkbox.

Full suite: 1673 passed, 3 skipped (before: 1650 passed, 3 skipped).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the fill preview shows
  pass 1 only (shifted lines appear ≈ 1.5 s after a change at ~1500 hatched objects, the canvas
  stays usable meanwhile); the test pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (GS1 QR / Digital Link codes with a GS1 scanner and a phone camera,
  plain-text QR codes with mixed segments, scan offset test pattern and compensated bidirectional
  hatch / image at 3000–6000 mm/min incl. the shifted fill preview and its background planning
  on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and 2-opt block
  order, fill grouping and inside-out offset fill, offset fill, cut options incl. overcut and
  perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417 readability incl.
  edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes with a real scanner,
  park-corner refusal, variable text / CSV merge over several sends incl. the canvas value
  labels, rebuilt exe).

## 34. Status update 2026-11-04 (review round 27)

Done this round (Job raster engine, image model / job builder and the image settings dialog; no
change to the canvas widget, Machine / Scan Probe and Materials untouched):

- Gap picked outside the §33 list: **image engraving modes**. The §2 references list LightBurn's
  Jarvis, Stucki, Newsprint, Halftone (cells per inch + angle), Sketch and *Dot Width
  Correction*, xTool offers Jarvis / Stucki / Sierra; LumaCut had only threshold, Floyd, Atkinson,
  Bayer, grayscale and 3D depth, no dot width correction and no preview of the dithered result –
  photo engraving is the main image use on a diode laser, so this was the most valuable untracked
  gap.
  - `lumacut_job/raster.py`: new modes `jarvis`, `stucki`, `sierra` (textbook kernels /48, /42,
    /32, row-vectorised diffusion – 1 MP in ≈ 0.3 s; Floyd / Atkinson keep the old loop and stay
    bit-identical), `halftone` (rotated AM screen, `halftone_cpi` 5–150 cells per inch,
    `halftone_angle` −90…90°, round dots grown from the cell centre, cell area = exact mean tone)
    and `newsprint` (45° clustered-dot 12 × 12 threshold tile, 72 levels). `dot_mask()` is the
    shared on/off decision; `halftone_cell_px()`. **Dot width correction** (`dot_width_mm`,
    0 … line interval): every burning run is shortened by half the value at each end that borders
    an unburned pixel (minimum 0.1 px so single dots survive), applied before reversing / scan
    offset, works for every mode incl. grayscale and 3D depth.
  - `lumacut_canvas/model.py`: `IMAGE_MODES` extended, `ImageSettings.halftone_cpi`,
    `halftone_angle`, `dot_width_mm` with clamping. `lumacut_job/images.py`: passes the fields;
    with `IMAGE_FLIP_X` the halftone angle is mirrored with the image, so the dots on the
    workpiece keep the chosen angle.
  - `lumacut_import/image_preview.py` (Qt-free) + `lumacut_import/qt.py`: the image settings
    dialog shows a **live preview** of the engraved result (one preview pixel = one laser dot at
    the line interval, big images as a centre crop ≤ 360 000 dots, debounced 150 ms, share of
    burned dots), fields for cells / angle / dot width, a cell-size hint („Zelle 0.85 mm = 8.5
    Punkte“, warning below 3 dots). Preview uses the same `power_map` as the job.

Tests:

- `tests/test_image_modes.py` (69): modes listed in engine / model / dialog, Pi-safe on/off
  G-code for every new mode, tone kept (mean burned share ≈ grey level), white / black, row
  diffusion = pixel loop, kernel weights, old modes unchanged, halftone round clusters per cell,
  cell size / angle change the pattern, exact 45° newsprint tile (72 levels, each once per cell),
  validation, speed, dot width (0 = unchanged, both run ends, tiny dots and grayscale edges,
  reversed lines and scan offset, shorter burned length in G-code, 3D depth), settings roundtrip
  and clamping, image objects send Pi-safe, angle mirrored with `IMAGE_FLIP_X`, old documents
  give byte-identical G-code, preview = engine, preview grayscale / depth / crop, dialog fields,
  debounced preview, `edit_image_settings` passes the image.

Full suite: 1742 passed, 3 skipped (before: 1673 passed, 3 skipped).

Output change for old files: none – G-code is byte-for-byte unchanged (default dot width 0, old
modes untouched); saved image settings gain `halftone_cpi`, `halftone_angle`, `dot_width_mm`.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: no *Sketch* mode (edge-enhanced engraving), no scan angle / angle increment per pass,
  no per-image brightness / contrast / gamma / sharpen adjustments in the dialog, the preview
  ignores rotation and the material's real dot size; mode presets are not linked to the material
  library (Materials).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the fill preview shows
  pass 1 only (shifted lines appear ≈ 1.5 s after a change at ~1500 hatched objects, the canvas
  stays usable meanwhile); the test pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (Jarvis / Stucki / Sierra / halftone / newsprint photos and dot width
  correction on wood / card at 3000–6000 mm/min incl. the dialog preview, GS1 QR / Digital Link
  codes with a GS1 scanner and a phone camera, plain-text QR codes with mixed segments, scan
  offset test pattern and compensated bidirectional hatch / image incl. the shifted fill preview
  and its background planning on the Windows app, fill overscan – line ends even at 2–5 mm on
  wood / card – and 2-opt block order, fill grouping and inside-out offset fill, offset fill, cut
  options incl. overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 35. Status update 2026-11-04 (review round 28)

Done this round (Job raster engine, image model / job builder, image preview and the image settings
dialog; no change to the canvas widget, Machine / Scan Probe and Materials untouched):

- Gap picked from the §34 list: **per-image adjustments and the Sketch mode**. LightBurn's *Adjust
  Image* (brightness, contrast, gamma, enhance / sharpen) and xTool's image adjustments are the
  usual first step for photo engraving – without them every photo had to be edited in an external
  program before import. The *Sketch* mode was the last LightBurn image mode from §2 missing.
  - `lumacut_job/raster.py`: `RasterSettings.brightness` (−100…100 %, added), `contrast`
    (−100…100, slope 10^(c/100) around mid grey), `gamma` (0.2…5, `v ** (1/γ)`, > 1 lightens mid
    tones, black and white stay), `sharpen` (unsharp mask 0…500 %) with `sharpen_radius`
    (Gaussian σ 0.5…10 dots), validation. `adjust_gray()` (order: sharpen, brightness, contrast,
    gamma) runs inside `power_map()` before every mode, `adjusted_height()` in
    `sliced_depth_gcode()` for 3D depth – so all modes incl. grayscale and 3D use it. New mode
    `sketch`: Sobel gradient of the lightly smoothed darkness (a hard step = full edge, flat areas –
    light or dark – = nothing), dithered with Jarvis; works with negative, dot width correction
    and the adjustments (contrast / sharpen strengthen the lines). Separable `gaussian_blur()`
    (numpy, edge pixels repeated; 1 MP sharpen + sketch ≈ 0.3 s). `power_map(..., inside=mask)`:
    pixels outside the real image never burn from adjustments or sketch edges; `margin=` lets a
    crop carry filter context (`filter_margin()`).
  - `lumacut_canvas/model.py`: `IMAGE_MODES` + `sketch`, `ImageSettings.brightness`, `contrast`,
    `gamma`, `sharpen`, `sharpen_radius` with clamping. `lumacut_job/images.py`: passes the
    fields; `render_inside()` renders the rotated image's footprint so a darkened or sketched
    rotated image does not burn the corners of its bounding box (mirrored with `IMAGE_FLIP_X`).
  - `lumacut_import/image_preview.py`: the live preview uses the same `power_map` /
    `adjusted_height`; a cropped preview of a big image takes the filter margin along, so sharpen
    and sketch at the crop edge give exactly the job's pixels.
  - `lumacut_import/qt.py`: group **Bildanpassung** in the image settings dialog (Helligkeit,
    Kontrast, Gamma, Schärfen, Schärferadius – only active with sharpen > 0 – and *Zurücksetzen*),
    debounced preview on every change, mode „Skizze (Kanten, Zeichenstil)“ with a hint.
  - Invert was already available as *Negativ* and is not duplicated.

Tests:

- `tests/test_image_adjustments.py` (47): defaults are a bit-identical no-op (mask ignored),
  brightness shift / clip and less burn when brighter, contrast slope and order, gamma keeps
  black / white and bends mid tones, Gaussian blur (flat areas, kernel), unsharp mask overshoot
  and radius, exact order of operations, validation, Pi-safe adjusted G-code, inside mask keeps
  box corners unburned, negative, 3D height map uses the adjustments; sketch listed everywhere,
  edges only (flat black / white free), disc outline in both polarities, shorter than dithering,
  with contrast / sharpen / dot width, filter margin = whole-image result; settings roundtrip and
  clamping, job settings carry the fields, adjusted image objects (Jarvis / sketch / grayscale /
  3D) send Pi-safe, old (rotated) documents give byte-identical G-code in five modes,
  `render_inside()` for rotated images, darkened rotated image never burns the corners; preview
  = engine with adjustments (Jarvis / sketch / grayscale), 3D preview, cropped preview with filter
  margin, unchanged preview without adjustments; dialog fields roundtrip / reset / radius
  enabling, old settings unchanged by the dialog, sketch hint and preview, debounced preview on
  adjustment changes, `edit_image_settings` stores the adjustments with undo.

Full suite: 1789 passed, 3 skipped (before: 1742 passed, 3 skipped).

Output change for old files: none – G-code is byte-for-byte unchanged (all adjustments default to
„unchanged“ and are skipped entirely; the inside mask is only used with adjustments or sketch);
saved image settings gain `brightness`, `contrast`, `gamma`, `sharpen`, `sharpen_radius`.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: no scan angle / angle increment per pass (Marlin raster runs along X only), no
  histogram / auto-levels button, the preview ignores rotation and the material's real dot size;
  mode and adjustment presets are not linked to the material library (Materials).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the fill preview shows
  pass 1 only (shifted lines appear ≈ 1.5 s after a change at ~1500 hatched objects, the canvas
  stays usable meanwhile); the test pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 36. Status update 2026-11-04 (review round 29)

Done this round (Job raster engine helpers, image preview and the image settings dialog; no change
to the job builder output, the canvas widget, Machine / Scan Probe and Materials untouched):

- Gaps picked from the §35 list: **histogram / auto-levels** and **a preview that honours the
  object's rotation**. A histogram is the usual way to judge a photo before engraving (LightBurn
  shows the effect of *Adjust Image* only on the image, xTool has an automatic image adjustment);
  without it the brightness / contrast fields had to be found by trial. The old preview drew the
  unrotated source image with nearest-neighbour sampling, so a rotated photo looked different
  from what the laser burns.
  - `lumacut_job/raster.py`: `gray_histogram(gray, inside=None)` (256 counts, float input
    rounded, optional mask), `levels_points(hist, clip)` (darkest / lightest grey after ignoring
    `AUTO_LEVELS_CLIP` = 0.5 % of the pixels at each end) and `auto_levels(hist, clip)`: the
    linear stretch `(v − lo) / (hi − lo)` expressed with the existing adjustments – contrast
    `100·log10(1/(hi − lo))`, brightness `100·(0.5 − (lo + hi)/2)` – rounded to whole percent and
    clamped (a range under 10 % of the grey scale gets contrast 100, centred; flat images give
    0 / 0). No new settings field, so the job needs nothing new.
  - `lumacut_import/image_preview.py`: `preview_pixels()` (preview of an array already in the
    line interval, with the job's inside mask, crop + filter margin as before);
    `render_for_preview(shape, settings)` renders the image object exactly like
    `images.render_gray()` / `render_inside()` (rotation, smooth scaling) with the dialog's not
    yet applied settings; `preview_shape()` computes it mirrored like the job at origin top right
    (`IMAGE_FLIP_X`: error diffusion direction and negated halftone angle) and mirrors it back for
    display – preview pixels = the job's `power_map` pixels incl. rotated box corners staying
    white. `histograms()` (source and adjusted histogram of the whole image in the line interval,
    big images sampled coarser with the sharpen radius scaled, share of pure black / white after
    adjustment, tonal range) and `auto_levels_for()` (levels of the sharpened image – sharpen runs
    before the stretch; existing brightness / contrast are replaced, gamma and sharpen stay).
    `preview_array()` (image data only) is unchanged.
  - `lumacut_import/qt.py`: `HistogramWidget` under the preview (light = image, dark = adjusted,
    square-root scale, red edge marks when > 1 % is clipped to pure black / white) with a text
    line (pure black / white share, tonal range); button **Auto-Tonwert** next to *Zurücksetzen*
    (disabled without image data). The dialog takes `shape=`; `edit_image_settings()` passes the
    object, the preview then renders it like the job (cached per line interval / negative, so
    power / mode / adjustment changes don't re-render) and says „gedreht um N°“.

Tests:

- `tests/test_image_levels.py` (40): histogram counts / mask / float rounding, level points
  ignore outliers, auto-levels stretch maps the range to ≈ black / white and the middle to mid
  grey, exact formula, dark / light images shift brightness in opposite directions, flat / full /
  very narrow ranges and validation; preview histograms before / after adjustment, sampled big
  images, `auto_levels_for` replaces existing brightness / contrast and sees sharpen; shape
  preview = job `power_map` in five modes (Floyd, Jarvis, halftone, threshold, sketch) × rotated /
  unrotated × with / without adjustments, grayscale values identical to the job, rotated box
  corners white (plain, darkened, negative), rotated preview has the bounding-box size, dialog
  settings used instead of the stored ones, crop of big rotated images, 3D depth preview, old
  documents give byte-identical G-code; dialog histogram and idempotent Auto-Tonwert (gamma kept,
  preview and histogram follow), no auto-levels without image data, dialog with shape = job
  preview with render cache, `edit_image_settings` passes the shape and stores auto levels with
  undo.

Full suite: 1829 passed, 3 skipped (before: 1789 passed, 3 skipped).

Output change for old files: none – G-code is byte-for-byte unchanged (the job builder was not
touched; Auto-Tonwert only fills the existing brightness / contrast fields); saved files unchanged.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: no scan angle / angle increment per pass (Marlin raster runs along X only); the preview
  shows one pixel per dot and does not model the material's real dot size / beam spread (needs
  the material library – Materials); no manual levels (black / white point sliders) – auto-levels
  uses brightness / contrast; the histogram is of the unrotated source image; mode and
  adjustment presets are not linked to the material library (Materials).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the fill preview shows
  pass 1 only (shifted lines appear ≈ 1.5 s after a change at ~1500 hatched objects, the canvas
  stays usable meanwhile); the test pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (auto-levelled photos and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 37. Status update 2026-11-04 (review round 30)

Done this round (Job raster engine, image settings model field, image preview and the image
settings dialog; canvas widget, Machine / Scan Probe and Materials untouched):

- Gaps picked from the §36 list: **manual levels (black / white point)** and **the histogram of a
  rotated image**. The kerf / tabs / lead-in, vector fill / hatch, path preview and touch gaps
  from the priority list are all done (§3 #11, #12, #14; touch polish ff638ef, §11), so the next open item of the
  image chain was taken. A black / white point is the usual first correction for a photo
  (image editors' *Levels*; xTool and LightBurn users do it before import) – with brightness /
  contrast alone the dark end and the light end cannot be set independently.
  - `lumacut_job/raster.py`: `RasterSettings.black_point` / `white_point` (0..255, black <
    white, validated; `levels_set()`, counted by `adjusted()`); `adjust_gray()` applies
    `(v − black) / (white − black)`, clipped, after the unsharp mask and before brightness /
    contrast / gamma. 0 / 255 = unchanged (bit-identical). All modes incl. Sketch and 3D depth
    get it through `power_map` / `adjusted_height`; rotated box corners stay unburnt (inside
    mask as before).
  - `lumacut_canvas/model.py`: `ImageSettings.black_point` / `white_point` (defaults 0 / 255;
    `normalized()` clamps the black point to 0..254 and keeps the white point above it); older
    files without the keys load as 0 / 255. `lumacut_job/images.py` and the preview pass them on.
  - `lumacut_import/image_preview.py`: `Histograms.points` (set black / white point);
    `histograms_rendered(gray, inside, settings)` – histogram of the image rendered like the job
    (rotation, smoothing), only pixels inside the rotated image, big images sampled with a
    stride (sharpen radius scaled). `auto_levels_for()` keeps the black / white point (Auto-Tonwert
    stretches what is left after them).
  - `lumacut_import/qt.py`: spin boxes **Schwarzpunkt** / **Weißpunkt** at the top of
    *Bildanpassung* (they push each other instead of crossing; live preview; *Zurücksetzen*
    resets them too); the histogram draws blue markers at the points and the text line names
    them; for a rotated object the histogram uses the dialog's job render (same cache as the
    preview, no extra render).

Tests:

- `tests/test_image_black_white_point.py` (29): linear mapping and clipping, defaults
  bit-identical / not `adjusted()`, white point lightens / black point darkens, order (after
  sharpen, before brightness / contrast / gamma), validation (4 cases), `ImageSettings`
  clamping / round trip / old dicts, Auto-Tonwert on top of levels; job G-code changes with
  levels while an old document without the keys gives identical G-code; shape preview = job
  `power_map` with levels in four modes × rotated / unrotated, grayscale values identical to
  the job, rotated box corners stay white even with an extreme black point, 3D depth preview
  follows the black point; histogram points and clipped shares, rotated histogram counts only
  the inside pixels, sampled big rendered images; dialog spin boxes / histogram text / markers
  paint / mutual push / reset, darker preview with a black point, rotated dialog histogram
  from the shared render (one render), `edit_image_settings` stores the points with undo.

Full suite: 1858 passed, 3 skipped (before: 1829 passed, 3 skipped).

Output change for old files: none – documents without `black_point` / `white_point` load as
0 / 255 and give byte-identical G-code; saved files gain the two keys in the image settings.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: no scan angle / angle increment per pass (Marlin raster runs along X only); the preview
  shows one pixel per dot and does not model the material's real dot size / beam spread (needs
  the material library – Materials); no curves (only black / white point, brightness, contrast,
  gamma); Auto-Tonwert sets brightness / contrast, not the black / white point; mode and
  adjustment presets are not linked to the material library (Materials).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); speeds only in mm/min (no mm/s view); the fill preview shows
  pass 1 only (shifted lines appear ≈ 1.5 s after a change at ~1500 hatched objects, the canvas
  stays usable meanwhile); the test pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Park corner on the canvas: the corner is not drawn as a no-go zone yet (Canvas).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (photos with black / white point, auto-levelled photos and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 38. Status update 2026-11-04 (review round 31)

Done this round (unit helpers / speed widgets, image preview and image settings dialog, job
park-corner overlay; canvas editing, Machine / Scan Probe and Materials untouched):

- Gaps picked from the §37 list: **speeds only in mm/min (no mm/s view)**, **Auto-Tonwert sets
  brightness / contrast, not the black / white point** and **park corner not drawn on the
  canvas**.
- **Speed display unit mm/min or mm/s** (LightBurn shows mm/s by default; diode users switch
  between both all the time):
  - `lumacut_canvas/units.py`: `MM_PER_MIN` / `MM_PER_S`, `speed_to_display` /
    `speed_from_display` (rounded to 0.001 mm/min), `format_speed` (trailing zeros dropped) and
    `parse_speed` (comma or point, an explicitly typed unit wins, e.g. „3000 mm/min“ in mm/s
    mode).
  - `lumacut_canvas/unit_ui.py`: `DisplaySpeedUnits` (one app-wide unit, stored in the app
    settings as `canvas/speed_unit`, change signal), `SpeedSpin` (value always mm/min, text in
    the display unit, validate / fixup) and `SpeedUnitCombo`.
  - Used in the layer list and layer speed field (`layers_panel.py`), the image settings dialog
    (`lumacut_import/qt.py`), the material test dialog (`lumacut_job/qt_tools.py`) and the scan
    offset table (`lumacut_job/scan_offset_qt.py`); all follow a change at once. Documents,
    material presets, scan offset settings and G-code stay mm/min – identical G-code in both
    views.
- **Auto-Tonwert sets the black / white point** (`lumacut_import/image_preview.py`
  `auto_levels_for()`, dialog in `lumacut_import/qt.py`): the black / white point are set to the
  tonal range of the (sharpened) image without 0.5 % outliers at each end, brightness / contrast
  go to 0, gamma and sharpen stay. The stretch is now exactly linear from black to white (the old
  brightness / contrast approximation clipped slightly); a second click changes nothing, a flat
  image gives 0 / 255.
- **Park corner on the canvas** (`lumacut_job/park_zone.py`, installed by `JobTools`): the part
  of the Pi's park corner inside the visible work area (head v6: machine X0–78 / Y0–35 → a
  48 × 5 mm strip at the top right) is drawn as a red hatched, dashed-outline background overlay
  „Park-Ecke“ (under the objects, not clickable, not exported). It follows `park_corner_mm` from
  `/api/status` (mirror `PARK_CORNER_MM` without a Pi) and is hidden while the panel's origin is
  „Aktuelle Position“ / „Benutzer-Ursprung“ (the Pi moves the motif then; the send-time check
  still covers it). Only public APIs are used (`editor.add_overlay`, panel `status_changed`,
  `job_origin()`, `origin_combo`); redraw only when corner or visibility change.
- Test fix: `test_touch.py::test_long_press_opens_menu_without_click_or_move` failed once in a
  full run under load (the 550 ms long-press timer fired late); it now polls up to 3 s for the
  menu instead of a fixed wait.

Tests:

- `tests/test_speed_units.py` (14): conversion / rounding / formatting, parsing with comma and
  explicit units, the shared unit (toggle, signal, stored in the app settings), `SpeedSpin`
  value stays mm/min, `SpeedUnitCombo` follows / sets the shared unit, layer panel list and field
  in mm/s, layer material summary, image / material test dialogs return mm/min, scan offset test
  dialog in mm/s gives identical G-code.
- `tests/test_image_auto_points.py` (9): Auto-Tonwert points from the outlier-trimmed range,
  exact stretch, idempotent, flat image, sharpened source, dialog and `edit_image_settings`
  store the points with undo; `tests/test_image_levels.py` adjusted to the new behaviour.
- `tests/test_park_zone.py` (15): zone rectangle for the default corner, corners inside the safe
  zone are invisible (5 cases), clamping, 45° hatch inside the zone, object overlap, a motif in
  the drawn zone is exactly what `park_corner.check_job` refuses, rendering only inside the zone,
  sync with the Pi corner / origin and redraw only on a change, real `JobTools` + `MachinePanel`
  install the overlay.

Full suite: 1899 passed, 3 skipped (before: 1858 passed, 3 skipped).

Output change for old files: none – speeds are stored and sent in mm/min as before; Auto-Tonwert
only changes what the button sets (existing documents keep their saved settings); the park zone
is display only.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: no scan angle / angle increment per pass (Marlin raster runs along X only); the preview
  shows one pixel per dot and does not model the material's real dot size / beam spread (needs
  the material library – Materials); no curves (only black / white point, brightness, contrast,
  gamma); mode and adjustment presets are not linked to the material library (Materials).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the zone is not shown for a job placed at „Aktuelle Position“ / „Benutzer-Ursprung“
  (would need the placed extent drawn relative to the head / user origin); moving an object into
  the zone gives no live warning (the send / start check refuses it).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (speeds typed in mm/s on the layer panel and dialogs against the sent
  G-code, the park-corner zone against a real refusal, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 39. Status update 2026-11-04 (review round 32)

Done this round (image adjustment, image settings dialog, job park-corner overlay; canvas editing,
Machine / Scan Probe and Materials untouched):

- Gaps picked from the §38 list: **no image curves**, **no live warning when an object is moved
  into the park corner** and **park zone not shown for „Aktuelle Position“ / „Benutzer-Ursprung“**.
- **Tone curve (Gradationskurve)** for images (LightBurn / Photoshop „Curves“):
  - Engine (`lumacut_job/raster.py`): `RasterSettings.curve` (2–16 points (in, out), 0–255,
    strictly rising inputs, validated); applied in `adjust_gray` after black / white point and
    before brightness / contrast / gamma. Monotone cubic Hermite through all points
    (Fritsch–Butland slopes with Fritsch–Carlson limiting: no overshoot, rising points give a
    rising curve), flat beyond the end points, evaluated via a cached 4096-entry LUT
    (`curve_lut`, `apply_curve`). An empty curve is bit-identical to before.
  - Model (`lumacut_canvas/model.py`): `ImageSettings.curve`, `normalize_curve` (round / clamp,
    sort, duplicate inputs → last wins, max. 16 points, identity → empty); `to_dict` only writes
    `curve` when it is not linear. Job (`lumacut_job/images.py`) and dialog preview
    (`lumacut_import/image_preview.py`) pass it through; `curve_input_histogram` gives the
    histogram after the black / white point (what the curve sees); Auto-Tonwert ignores and keeps
    the curve.
  - Widget (`lumacut_import/curve_widget.py` `CurveWidget`): square plot with the input histogram
    as background, grid, diagonal; click adds a point, drag moves it (kept between its
    neighbours), right / double click or Delete / Backspace removes it (end points snap back to
    their corner; the key wins against application shortcuts), 16-point limit. Presets
    `CURVE_PRESETS` (linear, S-curve, strong S-curve, less contrast, lighten / darken midtones,
    lift shadows for dark wood, darken highlights for light areas), „Benutzerdefiniert“ when
    edited.
  - Dialog (`lumacut_import/qt.py` `ImageSettingsDialog`): row „Kurve“ (preset combo + widget)
    after the white point; live preview / histogram follow, the histogram line names the curve,
    *Zurücksetzen* makes it linear, `settings()` returns it (undoable via `edit_image_settings`).
- **Live park-corner warning** (`lumacut_job/park_zone.py` `ParkZoneSync`, hooked into
  `JobTools`): after every `documentChanged` / `selectionChanged` (drag, nudge, paste, layer
  visibility, „Nur Auswahl“ toggled) the design box of what would be sent (visible layers, only
  the selection with „Nur Auswahl“) is checked with the Pi's rule (`design_hits_zone`: the whole
  placed box reaching into the corner is refused – even if no single object lies in it). The zone
  is drawn stronger with „N Objekte darin!“ / „Motiv-Umriss reicht hinein!“, and the status bar
  gets one message per change (incl. „Park-Ecke wieder frei.“); redraws only on a change.
- **Park zone for placed jobs**: with „Aktuelle Position“ / „Benutzer-Ursprung“ the zone is the
  machine corner shifted back by the Pi's `placement_offset` for the current design box, anchor
  (visible corner, older-Pi l/r swap undone) and head position / stored user origin
  (`placed_zone_rect`), clipped to the work area and labelled „Park-Ecke (am Ursprung …)“; hidden
  while that point is unknown. Follows panel status, origin and anchor combos.
- Test fix: the curve widget keyboard test failed in a full run (an application Delete shortcut
  of a leftover window ate the key); the widget now accepts the shortcut override and the test
  sends the events directly.

Tests:

- `tests/test_image_curve.py` (34): LUT through the points / monotone / flat ends / no overshoot,
  validation, empty curve bit-identical, order in the adjustment chain, `normalize_curve` cases,
  `to_dict` / `from_dict` incl. old documents without `curve`, job and dialog preview use the
  curve, Auto-Tonwert keeps it, curve input histogram, widget mouse add / drag / remove, keyboard,
  point limit, presets and „Benutzerdefiniert“, dialog row / reset / histogram label,
  `edit_image_settings` with undo.
- `tests/test_park_zone_live.py` (15): machine design box, the box rule incl. two objects whose
  common box reaches the corner and the unknown-target case, agreement with
  `park_corner.check_job` (absolute and placed with anchors bl / center / tr over a grid of
  positions), placed zone hidden without head position, live warning on move in / move within /
  move out (one message each, „wieder frei“), hidden layers and „Nur Auswahl“, rotated object
  boxes, real `CanvasEditor` + `JobTools` + `MachinePanel` status-bar message.

Full suite: 1948 passed, 3 skipped (before: 1899 passed, 3 skipped).

Output change for old files: none – documents without `curve` engrave bit-identically and are saved
without it; the park-zone changes are display / warning only (the send-time check is unchanged).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: no scan angle / angle increment per pass (Marlin raster runs along X only); the preview
  shows one pixel per dot and does not model the material's real dot size / beam spread (needs
  the material library – Materials); mode and adjustment presets (incl. the curve presets) are
  not linked to the material library (Materials); no per-channel / colour curves (images are
  grey only).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes (slightly stricter than the powered G-code extent
  at send, e.g. text with small glyphs or images with white margins); with „Aktuelle Position“
  the zone follows the head only as often as the Pi status updates; overscan / lead-ins are not
  part of the live box (the send check still covers them).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); plain-text QR
  codes with non-ASCII characters stay one byte segment (no ECI / Kanji mode); no Micro QR.
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (speeds typed in mm/s on the layer panel and dialogs against the sent
  G-code, the park-corner zone against a real refusal incl. the live warning and the placed zone at
  „Aktuelle Position“ / „Benutzer-Ursprung“, photos with tone curves (S-curve, shadows lifted)
  against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 40. Status update 2026-11-05 (review round 33)

Done this round (2D codes, live park-corner box; canvas editing, Machine / Scan Probe and
Materials untouched):

- Gaps picked from the §39 list: **plain-text QR codes with non-ASCII characters stay one byte
  segment (no ECI / Kanji mode)** and **overscan / lead-ins are not part of the live park-corner
  box**.
- **QR ECI 26 (UTF-8) and Kanji mode** (`lumacut_job/qr.py`, ISO/IEC 18004 §7.4.2 / §7.4.6):
  - `QrSpec.eci` (new codes from the dialog: on; missing in old documents → off): text with
    non-ASCII characters gets an ECI header (mode `0111`, designator 26 = UTF-8) before the
    segments, so scanners decode umlauts / symbols as UTF-8 instead of guessing (ISO 8859-1 or
    Shift JIS). The mixed-segment optimiser (numeric / alphanumeric / byte) still runs behind
    the header.
  - Kanji mode (`1000`, 13 bits per character from Shift JIS, count bits 8 / 10 / 12) joins the
    mixed-segment optimiser for Japanese text (kana / CJK ideographs present, every non-ASCII
    character Shift-JIS encodable, no `\` / `~`): e.g. 52 kanji at level M need version 5
    instead of 9. Non-Japanese text never uses Kanji mode (symbols like ° or × would be misread).
  - `text_charset` / `content_info`: „Zeichensatz UTF-8 (ECI 26)“, „Kanji-Modus (Shift JIS)“
    or, for old codes, „UTF-8 ohne Zeichensatz-Kennung (älterer Code) … „UTF-8 kennzeichnen“
    einschalten“; the segment summary names Kanji segments.
  - Dialog (`qr_qt.py`): checkbox „UTF-8 kennzeichnen (ECI) – Umlaute / Sonderzeichen sicher
    lesbar“ (text mode only, on for new codes, saved in the code meta, undoable via the generated
    object edit).
- **Live park-corner box with cut options** (`lumacut_job/park_zone.py`):
  - `cut_margin_mm(layer, table)`: upper bound for how far the powered path leaves the object
    boxes – 2 × |kerf| (mitred corners), lead-in / lead-out length (√2 × for quarter-circle leads),
    half the scan offset at the layer speed for hatch / cross-hatch; `margin_box` = object boxes
    grown by it.
  - `ParkZoneSync.job_box`: the object boxes stay the base; only if the bound can change the
    verdict (boxes clear, grown boxes in the corner) the job is planned exactly like at send
    (`planned_powered_box`: `job_layers` → `optimize_layers` → scan offset →
    `layers_to_gcode` → `park_corner.powered_bounds`; „Nur Auswahl“ plans the selection
    document; images keep their object box). Cached on the job layers like the fill preview, so
    status ticks and unrelated edits do not plan again; far from the corner nothing is planned; a
    planning error falls back to the object boxes (the send check decides).
  - Warning „Achtung: An-/Abfahrt, Kerf- oder Scan-Versatz (Schnitt-Optionen der Ebene) des
    Motivs … reicht in die Park-Ecke …“ and label „Anfahrt / Versatz reicht hinein!“; the
    objects whose grown box reaches the zone are listed. Works for placed jobs („Aktuelle
    Position“ / „Benutzer-Ursprung“) as well – the placed zone uses the same box.
  - Correction of §39: fill overscan runs with the laser off (`G1 … S0`) and is not part of the
    Pi's powered extent; it never caused a refusal and is (correctly) not counted live either.

Tests:

- `tests/test_qr_eci_kanji.py` (76): charset choice table, ISO Kanji examples (点 → 0xD9F,
  茗 → 0x1AAA), ECI header bits, bit-exact matrices against segno (embedded references for
  „Grüße“ / „東京タワー“ plus single-segment texts at L / M / Q / H), old codes bit-identical
  without ECI, ASCII ignores ECI, mixed byte / numeric with umlauts, Kanji smaller than byte,
  random Japanese segmentation bound, capacity limits (ä × 1470 / 1477 at 40-L, 東 × 1817 / 1818),
  zxing-cpp decode with the `]Q2\000026` ECI designator (vs. `]Q1` for old codes), Kanji decode,
  hatch-filled ECI code decode, spec default / meta round trip, content info lines, dialog
  checkbox, rebuild of an old umlaut code unchanged.
- `tests/test_park_zone_cut_options.py` (28): margin bound per option (overscan, tabs, overcut,
  perforation = 0), scan offset only for line fills, the bound contains the planned extent
  (rects, rotated rects, ellipses, holes), planned box = powered bounds of the sent G-code incl.
  scan offset and overscan, plan cache, sweeps along the corner with lead-in, arc lead-in /
  lead-out and kerf where the live verdict equals `check_job` on the planned G-code (incl. the
  positions only the lead reaches in), warning text and „wieder frei“, no planning far away / for
  layers without cut options / on status ticks, overscan never refused, scan offset sweep,
  „Nur Auswahl“, placed jobs (anchors bl / center) over a grid of head positions, planning error
  fallback.

Full suite: 2052 passed, 3 skipped (before: 1948 passed, 3 skipped).

Output change for old files: none – QR codes without `eci` in their meta rebuild bit-identically
(the dialog only switches ECI on for new codes or when the box is ticked); the park-zone change is
display / warning only (the send-time check is unchanged).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: no scan angle / angle increment per pass (Marlin raster runs along X only); the preview
  shows one pixel per dot and does not model the material's real dot size / beam spread (needs
  the material library – Materials); mode and adjustment presets (incl. the curve presets) are
  not linked to the material library (Materials); no per-channel / colour curves (images are
  grey only).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  no Micro QR.
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (QR codes with umlauts (ECI 26) and Japanese Kanji text with phone
  scanners (iOS / Android camera apps) and a handheld scanner, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 41. Status update 2026-11-05 (review round 34)

Done this round (image scan angle; canvas editing, Machine / Scan Probe and Materials
untouched):

- Gap picked from the §40 list: **Image: no scan angle / angle increment per pass (Marlin raster
  runs along X only)** (LightBurn *Scan Angle* / *Angle Increment*).
- **Model** (`lumacut_canvas/model.py`): `ImageSettings.scan_angle` and `angle_increment`
  (degrees, −90…90, counter-clockwise on the canvas; 0 = rows along X, 90 = along Y); saved only
  when ≠ 0, so old files stay byte-identical.
- **Engine** (`lumacut_job/raster.py`): `ScanFrame` (row origin + row / column axes in machine
  mm), `wrap_angle`, `scanlines_frame` – the same run building, dot width correction,
  bidirectional order, overscan and scan offset as `scanlines`, but every row is written as
  oblique `G1 X… Y… S…` along the frame (vector-style moves, the Pi guard already accepts them);
  burning runs are clipped to the row's chord through the (rotated) image so anti-aliased edge
  pixels never burn outside the object. `sliced_depth_gcode` takes an optional frame / chords
  (3D depth at an angle, odd slices bottom-up as before).
- **Job** (`lumacut_job/images.py`): `ScanGeometry` / `scan_geometry` render the image (incl. the
  object's own rotation) in a grid rotated by the scan angle at the line interval
  (`render_gray_frame`, `render_inside_frame`); `angled_settings` clamps overscan and scan offset
  to the work area along the row (shortest room from the image corners) and turns the halftone
  angle by the scan angle so the screen stays at the set angle on the workpiece. With an angle
  increment pass k uses `wrap(scan_angle + k × increment)`; each distinct angle is rasterised
  once and every pass gets `; PASS k OF n` / `; SCAN ANGLE a` comments. All angles 0 → the
  untouched old path.
- **Preview** (`lumacut_import/image_preview.py`): the dialog preview computes pass 1 in the
  rotated grid like the job and rotates it back to the canvas orientation (`rotate_pixels`, no
  smoothing); the burnt share refers to the image, not the larger rotated grid.
- **Dialog** (`lumacut_import/qt.py`): „Scan-Winkel“ and „Winkel-Schritt je Durchgang“ (only
  enabled with more than one pass), preview label „Scan-Winkel …°“, render cache keyed by the
  angle; stored with undo via the existing image-settings command.

Tests:

- `tests/test_image_scan_angle.py` (26): settings defaults / normalising / round trip / old files,
  `wrap_angle` and per-pass angles, run clipping and frame maths, **old output byte-identical** for
  Floyd, halftone, rotated grayscale with scan offset and 2 passes, 3D depth and rotated sketch
  near the work-area edge (SHA-256 of round-33 output), burns inside the dark half and along the
  scan direction for 30° / −45° / 60° / 90° on plain and rotated objects (coverage = area / line
  interval within 8 %), 90° = vertical rows, bidirectional vs. unidirectional, overscan along the
  row, overscan / scan offset clamped at the work-area edge (all moves inside the machine limits),
  scan offset shifts every row by half the offset against its travel direction, 0° / 90° / 0°
  passes with the angle increment (identical bodies for equal angles, one pass → unchanged),
  3D depth at 45°, halftone angle compensation, preview orientation and burn share, dialog round
  trip / enabling / label, edit with undo and save / load, full document G-code through the Pi
  guard and the time estimate.

Full suite: 2078 passed, 3 skipped (before: 2052 passed, 3 skipped).

Output change for old files: none – documents without `scan_angle` / `angle_increment` take the
unchanged X raster path (verified byte-identical against round 33 for several modes, rotation,
scan offset, passes and edge clamping).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); oblique rows are short `G1` segments without
  acceleration-aware speed (the time estimate counts them like vector moves); the park-corner
  live box keeps using the object box (the powered extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  no Micro QR.
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (QR codes with umlauts (ECI 26) and Japanese Kanji text with phone
  scanners (iOS / Android camera apps) and a handheld scanner, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 42. Status update 2026-11-05 (review round 35)

Done this round (material test with a parameter per axis / interval test; canvas editing,
Machine / Scan Probe and Materials untouched):

- Gap picked from a sanity sweep, not on the §41 list: **Material test only varies power × speed**.
  LightBurn's *Material Test* lets every axis pick its parameter (power, speed, interval, passes …)
  and LightBurn ships a separate *Interval Test*; on a diode the line interval and the number of
  passes are the settings that are calibrated most after power / speed (engrave darkness and cut
  depth), and LumaCut had no way to test them in one grid. Chosen over the §41 candidates (pass
  previews with an angle increment, oblique-row time estimate, in/min, Micro QR) because it is an
  everyday calibration workflow; the oblique-row estimate turned out to be covered already – the
  estimator plans every `G1` segment with acceleration and junction deviation, so collinear
  oblique row segments keep their speed.
- **Engine** (`lumacut_job/material_test.py`): `MaterialTestSpec.column_param` / `row_param`
  (`TEST_PARAMS` = power, speed, interval, passes; default power × speed), `interval_max`,
  `passes_max`; `param_values`, `cell_settings` (off-axis parameters take their fixed value:
  `power_min`, `speed_min`, `line_interval_mm`, `passes`), `label_texts`, `label_width`.
  Validation: different parameters per axis, interval test only for engrave cells, interval
  0.05–2 mm, passes 1–30. Each cell stays one layer named `Test P<power>% F<mm/min>` so the
  material library (`lumacut_materials.testgrid`) still recognises it; passes are on the layer,
  the tested interval is recorded in the layer's `line_interval_mm` (fill stays off, the cell is a
  serpentine at the cell's interval). Labels: power %, speed mm/s, interval mm, passes „3x“;
  wide row labels widen the label column (included in the work-area check).
- **Dialog** (`lumacut_job/qt_tools.py`): „Spalten-Parameter“ / „Zeilen-Parameter“, „Linienabstand
  bis“ and „Durchgänge bis“; range fields („… von“ / „… bis“) only for parameters on an axis, the
  others are one fixed field; the same parameter twice or an interval test with „Kontur“ disables
  OK with a hint; the mode follows the given spec (outline spec → „Kontur“).

Tests:

- `tests/test_material_test_params.py` (31): defaults = classic grid, values for every parameter
  (integer passes), fixed off-axis values, validation, interval × power / passes × speed /
  swapped axes grids (layer values, hatch rows per interval), layer order and names recognised by
  the material library incl. a preset with the layer's passes, labels and the wider label
  column (no overlap, work-area check), **old output byte-identical** (SHA-256 of round-34 output
  for the default engrave grid and a 3 × 4 outline grid with 2 passes; label boxes of the classic
  grid unchanged), all axis combinations through the Pi guard (plain and optimised send) and the
  estimate, burnt length scales with passes / interval, save / load, dialog round trip /
  enabling / checks, insert as one undo step.

Full suite: 2109 passed, 3 skipped (before: 2078 passed, 3 skipped).

Output change for old files: none – documents are not affected at all; a material test grid
with the default axes is byte-identical to round 34 (verified for several sizes, outline / engrave,
passes and labels).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: no focus / Z-offset axis (LightBurn *Focus Test*; LumaCut has no per-layer Z
  offset, only `z_step`) and no image (raster) test cells; the material library's
  „Preset aus Testzelle“ takes the line interval from its own planning, not from the cell layer's
  tested `line_interval_mm` (Materials, `testgrid.py`); several cells of an interval test share
  the same layer name (power / speed are equal) – the canvas labels tell them apart.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed –
  checked this round), but with one XY acceleration, so Marlin's per-axis limits on diagonal
  moves are not modelled (to be compared on the SKR); the park-corner
  live box keeps using the object box (the powered extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  no Micro QR.
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, QR codes with umlauts (ECI 26) and Japanese Kanji text with phone
  scanners (iOS / Android camera apps) and a handheld scanner, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / barcode / Data Matrix / Aztec / PDF417
  readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417 codes
  with a real scanner, park-corner refusal, variable text / CSV merge over several sends incl.
  the canvas value labels, rebuilt exe).

## 43. Status update 2026-11-05 (review round 36)

Done this round (Micro QR M1–M4 as vector engraving objects; canvas editing, Machine /
Scan Probe and Materials untouched beyond the shared QR dialog / generated-object wiring):

- Gap picked from the §42 list: **QR: no Micro QR**. LightBurn and xTool Creative Space both
  offer Micro QR for part marking in tight spaces; LumaCut only had the full QR symbol
  (version 1–40). Chosen over the other §42 2D-code leftovers (Aztec runes / structured append,
  Data Matrix EDIFACT, Macro / Micro PDF417, GS1 Digital Link compression) because Micro QR
  reuses the existing QR dialog and Reed–Solomon helpers and closes the most visible 2D-code
  gap for diode part marking.
- **Engine** (`lumacut_job/micro_qr.py`): pure-Python ISO/IEC 18004 Micro QR encoder – versions
  M1–M4 (11×11 … 17×17), EC D (M1 detection-only) / L / M / Q (Q only M4), modes numeric /
  alphanumeric / byte (UTF-8); no ECI, no Kanji, no FNC1 / structured append. Single finder,
  timing on row/col 0, format info, four Micro masks (ISO masks 1/4/6/7) with maximise score;
  terminator 3/5/7/9 bits; M1/M3 final 4-bit data codeword. Quiet zone default **2** modules;
  size = edge without quiet zone; invert; work-area clamp and `HARD_MIN_MODULE_MM` /
  `MIN_MODULE_MM` like full QR. `QrSpec.mode == "micro"` routes through `qr.qr_shapes` →
  `micro_qr_shapes`; fill layer name „Micro-QR“. Matrices validated against segno 1.6.6
  reference encodings (M1–M3 numeric / alphanumeric / byte samples).
- **Dialog** (`lumacut_job/qr_qt.py`): Art „Micro QR (klein, M1–M4)“ in the existing QR dialog
  (tooltip: Bauteilkennzeichnung / wenig Platz); EC combo switches to D/L/M/Q; quiet default 2
  when switching into Micro; status line shows Version M1–M4; ECI hidden; insert + „Code
  bearbeiten…“ round-trip via generator metadata (`mode: "micro"`); one undo step; locked fill
  layer behaviour unchanged. Full-QR Art paths and defaults unchanged.

Tests:

- `tests/test_micro_qr.py` (21): segno reference matrices M1–M3, version / capacity / mode
  choice, forced mask, quiet zone / invert runs, shapes bbox / area / clamp, `QrSpec`
  normalisation and generator metadata round-trip (old full-QR meta without `mode` still loads
  as text), content info / describe, dialog Micro round-trip under offscreen Qt, insert with
  „Micro-QR“ fill layer as one undo step through the Pi guard and the time estimate, **old
  full-QR output byte-identical** (Nayuki reference modules unchanged; SHA-256 of optimised
  G-code for a fixed „LumaCut“ M hatch job).

Full suite: 2135 passed, 3 skipped (before: 2109 passed, 3 skipped).

Output change for old files: none – documents without Micro QR stay byte-identical; the default
full-QR encode path is unchanged (verified against Nayuki references and a fixed G-code digest).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: no focus / Z-offset axis (LightBurn *Focus Test*; LumaCut has no per-layer Z
  offset, only `z_step`) and no image (raster) test cells; the material library's
  „Preset aus Testzelle“ takes the line interval from its own planning, not from the cell layer's
  tested `line_interval_mm` (Materials, `testgrid.py`); several cells of an interval test share
  the same layer name (power / speed are equal) – the canvas labels tell them apart.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression) and no short-name aliases (`/gtin/`); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, QR codes with umlauts (ECI 26) and Japanese Kanji text with phone
  scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on small parts
  with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera, plain-text QR codes with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 44. Status update 2026-11-05 (review round 37)

Done this round (GS1 Digital Link short-name path aliases; canvas editing, Machine /
Scan Probe and Materials untouched beyond the shared QR / GS1 dialog wiring):

- Gap picked from the §43 list: **GS1 Digital Link: no short-name aliases (`/gtin/`)**. GS1
  Digital Link URI Syntax 1.1 defined convenience alphas (`gtin`, `sscc`, `gln`, `lot`, `ser`,
  `exp`, …) that older scanners and docs still use; Syntax 1.3.0 removed them, but LumaCut only
  accepted numeric AIs. Chosen over DL binary compression (larger, deferred) and the other §43
  2D-code leftovers (Aztec runes / structured append, Data Matrix EDIFACT, Macro / Micro PDF417)
  because aliases reuse the existing `gs1_link` parse/build path and close the most visible
  Digital Link interop gap.
- **Engine** (`lumacut_job/gs1_link.py`): `SHORT_NAMES` / `AI_SHORT_NAMES` map (primary keys,
  key qualifiers, query attrs `exp` / `expdt` from DL 1.1). `parse` always accepts numeric AIs
  **or** aliases (case-insensitive) in path and query; non-AI query keys such as `linkType` stay
  in `Link.extra`. `build(..., short_names=False)` (default) stays numeric so existing G-code
  digests remain byte-identical; `short_names=True` emits `/gtin/…/lot/…?exp=…`. `resolve` and
  helpers `resolve_key` / `short_name` wire the option through. Round-trip alias → elements →
  numeric (and vice versa) is stable; percent-encoding and path prefixes unchanged.
- **Dialog** (`lumacut_job/qr_qt.py` / `QrSpec.short_names`): checkbox „Kurzname (/gtin/, /lot/, …)
  statt numerischer AI“ (default off, visible only in Digital Link mode). Pasted alias URIs are
  always accepted; the checkbox only controls emit when building from an element string. Old
  documents without `short_names` load as False.

Tests:

- `tests/test_gs1_qr.py`: new `test_short_name_aliases_build_parse_and_round_trip` (GTIN+lot+exp,
  SSCC, GLN/glnx, mixed query attrs + extras, case folding, percent-encoding, invalid alias,
  `exp` rejected in path, resolve verbatim / flag, `QrSpec` / `encode_link`); dialog test extended
  for checkbox visibility, default off, emit toggle, pasted alias URI, edit round-trip. Existing
  numeric URI expectations unchanged.

Full suite: 2136 passed, 3 skipped (before: 2135 passed, 3 skipped).

Output change for old files: none – numeric Digital Link URIs (default) stay byte-identical;
`QrSpec.short_names` defaults to False and is ignored outside link mode; old generator meta
without the field still loads.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: no focus / Z-offset axis (LightBurn *Focus Test*; LumaCut has no per-layer Z
  offset, only `z_step`) and no image (raster) test cells; the material library's
  „Preset aus Testzelle“ takes the line interval from its own planning, not from the cell layer's
  tested `line_interval_mm` (Materials, `testgrid.py`); several cells of an interval test share
  the same layer name (power / speed are equal) – the canvas labels tell them apart.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, QR codes with umlauts (ECI 26) and Japanese Kanji text with phone
  scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on small parts
  with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 45. Status update 2026-11-05 (review round 38)

Done this round (material test image cells; canvas editing, Machine / Scan Probe and the
Materials package untouched – the material library's test-cell parsing is only read):

- Closed since §44 by the Materials agent: **„Preset aus Testzelle“ takes the tested line
  interval** – commit 83b2294 (`lumacut_materials/testgrid.py`, `tested_axes`) uses the cell
  layer's `line_interval_mm` when the interval was a grid axis (clamped to the Pi range, not
  for cutting) and always the cell's passes; verified against the current tree.
- Gap picked from the §44 list: **material test without image (raster) test cells**. LightBurn's
  Interval Test offers „Dithered Image“ cells, and photo engraving is where diode users need a
  test most (dither / greyscale response differs strongly from a solid fill). Chosen over the
  scan-angle preview of later passes (cosmetic), the in/min speed unit (touches Materials'
  `presets.py`), the variable-text keyboard prompt (send-path / Machine wiring) and the 2D-code
  leftovers (Data Matrix EDIFACT, Macro / Micro PDF417, Aztec runes – niche).
- **Engine** (`lumacut_job/material_test.py`): `MaterialTestSpec.image_mode` (default `""` =
  vector cells, unchanged) and `image_min_power`. With an image mode every cell becomes an image
  object (`Shape.kind == "image"`) at the cell box holding a white → black grey ramp
  (`ramp_png`, 256 × 16 px 8-bit grey PNG written with `zlib`, Qt-free, deterministic) whose
  `ImageSettings` carry the cell's power (at black), speed, line interval and passes plus the
  common min power (at white). All image modes except Sketch (`TEST_IMAGE_MODES`; a ramp has no
  edges). All axis parameters work, including the interval test (the tested interval also
  stays on the cell layer). Validation: image mode known, line interval > 0, min power ≤ the
  smallest power. Cell layers keep the `Test P…% F…` names and values, so the material
  library still recognises the cells and their axes. The existing image path
  (`images.document_image_jobs`, planner „images before vectors“) engraves the cells top-left
  first and the labels afterwards; nothing in the planner or raster engine changed.
- **Dialog** (`lumacut_job/qt_tools.py`): „Art“ gets a third entry „Bild (Graustufen-Verlauf)“
  with „Bildmodus“ (same labels as the image dialog, Floyd-Steinberg preselected) and
  „Min.-Leistung (Weiß)“, shown only for image cells; the line interval stays editable; min
  power above the smallest power disables OK with a hint; the interval test is allowed with
  image cells. Fill / outline produce `image_mode = ""` as before.

Tests:

- New `tests/test_material_test_image.py` (20 tests): ramp PNG decodes white → black and is
  deterministic; default spec has vector cells; image cells carry power / speed / passes /
  interval / min power and sit at the vector cell positions; interval × passes axes in the
  image settings and recognised by `testgrid.tested_axes`; validation (sketch / unknown mode,
  interval 0, min power); Pi-guard-safe G-code for Floyd / greyscale / threshold / halftone /
  Jarvis with cells before the labels and the top-left cell first; greyscale ramp rises to the
  cell power; power / speed change the G-code; the round-34 vector grid SHA unchanged; save /
  load gives identical G-code; dialog visibility, round trip and min-power check; one undo step.

Full suite: 2156 passed, 3 skipped (before: 2136 passed, 3 skipped).

Output change for old files: none – `image_mode` defaults to `""`, vector grids (fill /
outline, all axis parameters) are byte-identical (round-34 SHA test); the spec is not stored in
documents (the grid is plain layers / shapes), so old documents load unchanged.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: no focus / Z-offset axis (LightBurn *Focus Test*; LumaCut has no per-layer Z
  offset, only `z_step`); several cells of an interval test share the same layer name (power /
  speed are equal) – the canvas labels tell them apart. Image cells: the G-code follows each
  cell's image settings, so editing a cell *layer's* power / speed in the layer panel does not
  change an image cell (the image settings dialog does); the ramp is the only test image (no
  user photo / step wedge), and the image modes' extra parameters (threshold, halftone cells /
  angle, 3D levels, adjustments) take their defaults.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, image test cells (Floyd / Jarvis / greyscale / halftone ramps × power ×
  speed and × line interval) on wood / card against real photo engravings with the chosen
  setting, QR codes with umlauts (ECI 26) and Japanese Kanji text with phone
  scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on small parts
  with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 46. Status update 2026-11-05 (review round 39)

Done this round (material test focus / Z-offset axis; Canvas / Machine / Scan Probe and the
Materials package untouched beyond the minimal Layer / JobLayer / gcode / image-job hooks for
`z_offset`):

- Closed since §45 by others: none in the studio-native Review scope (main advanced with Web /
  Pi / Panel merges only).
- Gap picked from the §45 „Still open“ list: **material test without a focus / Z-offset axis**
  (LightBurn *Focus Test*). LumaCut already had per-pass `z_step`, but no per-layer relative
  focus offset, so a Focus Test grid could not be expressed. Chosen over the variable-text
  keyboard / serial placeholder (send-path / Machine wiring), MicroPDF417 (niche 2D leftover)
  and image-cell step wedge / user photo (nice-to-have on top of the round-38 ramp cells).
- **Foundation** (`lumacut_canvas/model.py`, `export.py`, `gcode.py`, `lumacut_job/images.py`):
  `Layer.z_offset` (float mm, default 0, clamped to `Z_OFFSET_RANGE` = ±`MAX_FOCUS_DROP_MM`)
  is a relative focus offset applied once at the start of that layer and restored after it
  finishes (after any `z_step` restore). Sign convention matches `z_step`: negative lowers the
  head toward the material. Persisted only when non-zero (old documents stay byte-identical);
  mapped to `JobLayer.z_offset_mm`. `layers_to_gcode` emits `G91` / `G0 Z{offset:.3f} F600` /
  `G90` before the layer's passes and the inverse after; absolute Z words never appear.
  Combined peak drop (`max(0, -z_offset) + z_step*(passes-1)`) is refused above
  `MAX_FOCUS_DROP_MM`. Image jobs of a layer with a non-zero offset get the same relative wrap
  so a focus axis also moves image cells. `z_offset = 0` keeps G-code byte-identical.
- **Engine** (`lumacut_job/material_test.py`): `TEST_PARAMS` gains `"focus"` (label
  „Fokus-Versatz“) with `focus_min` / `focus_max` (default −1…+1 mm). `param_values` /
  `cell_settings` / labels / validate cover focus (range inside `Z_OFFSET_RANGE`, min≠max on
  an axis; allowed with fill, outline and image). `build_material_test` sets `layer.z_offset`
  from the cell when focus is on an axis; off-axis focus stays 0. Layer names stay
  `Test P…% F…` for the material library; focus appears only in the label texts (signed mm).
- **Dialog** (`lumacut_job/qt_tools.py`): focus in the column / row combos; „Fokus von/bis“
  shown only when focus is on an axis; tooltip (relative to current focus, negative = closer,
  needs motorized Z); equal from/to disables OK with a German hint.

Tests:

- New `tests/test_layer_z_offset.py` (9 tests): range, roundtrip + clamp, omit-when-zero
  `to_dict`, JobLayer mapping, relative Z at layer start/end, zero unchanged, positive offset,
  combined with `z_step` restores step then offset, peak-drop / range refusal, Pi-guard.
- Extended `tests/test_material_test_params.py` (+6 focus cases, validation updates): focus ×
  power and focus × speed grids; signed labels; Pi-safe G-code; default power×speed SHA
  unchanged; image cells with focus axis; dialog option, visibility, round trip.

Full suite: 2169 collected (before §45: 2156 passed, 3 skipped; +9 `test_layer_z_offset` and
+6 focus cases in `test_material_test_params`). Focus / z_offset / material-test / gcode /
focus-export related suites green. Pre-existing failures unrelated to this round:
`tests/test_polygon.py` (3× `pytest.approx` on nested tuples – Canvas) and one
`tests/test_trace.py` case (Canvas); some Qt SIGABRT-on-teardown runs in image / barcode
files under this environment (tests themselves pass when the process survives).

Output change for old files: none – `z_offset` defaults to 0.0 and is omitted from
`Layer.to_dict` when zero; default power×speed material-test grids are byte-identical
(round-34 SHA test); old documents without the field load as 0.0.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does); the ramp is the only test image (no user photo / step
  wedge), and the image modes' extra parameters (threshold, halftone cells / angle, 3D levels,
  adjustments) take their defaults.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps × power ×
  speed and × line interval) on wood / card against real photo engravings with the chosen
  setting, QR codes with umlauts (ECI 26) and Japanese Kanji text with phone
  scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on small parts
  with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 47. Status update 2026-11-05 (review round 40)

Done this round (material test image-cell step wedge / user photo; Canvas / Machine /
Scan Probe / Materials untouched):

- Closed since §46 by others: Scan Probe Fokuskorrektur docs on main (`9d198c2`); no
  further studio-native Review gaps closed outside this round.
- Gap picked from the §46 „Still open“ list: **material test image cells – only a grey
  ramp** (no step wedge / user photo). LightBurn Interval Test style extras on top of
  the round-38 ramp cells. Chosen over MicroPDF417 (niche), unique layer names when
  interval is on an axis (risk to `TEST_CELL_RE` / material library), and image-mode
  extras (threshold / halftone angle / 3D levels / adjustments – deferred).
- **Engine** (`lumacut_job/material_test.py`): `image_source` on `MaterialTestSpec`
  (`ramp` | `wedge` | `photo`, default `ramp`) plus optional `image_png` (embedded
  8-bit grey PNG for photo). `ramp_png()` unchanged (default grids / SHA stay
  byte-identical). New `wedge_png()` builds a 16-band horizontal step wedge
  (white→black); `cell_image_png()` / `image_cell` / `build_material_test` share one
  PNG across the grid. Photo without bytes or non-PNG fails validate with a clear
  German error („Eigenes Bild fehlt…“ / „muss ein PNG sein“).
- **Dialog** (`lumacut_job/qt_tools.py`): when Art is Bild, „Bildquelle“ combo
  (Verlauf / Stufenkeil / Eigenes Bild…) and a file picker that converts PNG/JPG/BMP
  to 8-bit grey (long side capped at 512). Missing photo disables OK with a German
  hint; German tooltips; fill / outline still produce `image_mode = ""` with
  `image_source = "ramp"` and no `image_png`.

Tests:

- Extended `tests/test_material_test_image.py`: wedge band count / monotonic equal
  bands; shared wedge / photo PNG across cells; ramp source byte-identical to
  legacy; photo / unknown-source validation; Pi-safe photo grid; dialog visibility
  and round-trip of `image_source` (ramp / wedge / photo). Existing ramp SHA and
  vector-grid SHA tests unchanged.

Full suite touch: material-test image + params green (66 passed in this round's
focused run). Pre-existing failures unrelated to this round: `tests/test_polygon.py`
(Canvas) and occasional `tests/test_trace.py` / Qt SIGABRT-on-teardown flakes.

Output change for old files: none – `image_source` defaults to `"ramp"` and
`image_png` to `None`; default ramp image cells stay byte-identical; vector grids
keep the round-34 SHA.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does); the image modes' extra parameters (threshold, halftone
  cells / angle, 3D levels, adjustments) take their defaults.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval) on wood / card against real photo
  engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 48. Status update 2026-11-09 (review round 41)

Done this round (material test image-cell mode parameters; Canvas / Machine / Scan Probe /
Materials untouched):

- Closed since §47 by others: none in studio-native – main only got hardware / „Stand“
  notes, Pi (`job_optimizer.py`, `scan_offset.py`, material calibration), firmware and
  Android commits since `716b0c5`.
- Gap picked from the §47 „Still open“ list: **material test image cells – the image
  modes' extra parameters take their defaults** (threshold, halftone cells / angle, 3D
  levels, adjustments). LightBurn's Interval Test engraves each cell with the layer's full
  image settings; LumaCut's image cells only used power / speed / interval / passes / min
  power. Chosen over MicroPDF417 / Macro PDF417 (niche), unique layer names on an interval
  axis (risk to `TEST_CELL_RE` / material library – Materials) and the Canvas / Machine /
  Scan Probe items (owned by other agents).
- **Engine** (`lumacut_job/material_test.py`): `image_options` on `MaterialTestSpec`
  (dict, default `None`) with `IMAGE_OPTION_KEYS` = `threshold`, `halftone_cpi`,
  `halftone_angle`, `depth_levels`, `z_step_mm`, `brightness`, `contrast`, `gamma`,
  `negative`. `image_overrides()` passes only the keys that apply to the chosen mode
  (`IMAGE_MODE_OPTIONS`: threshold → threshold, halftone → cells / angle, depth3d →
  levels / Z step; `IMAGE_ADJUST_OPTIONS` for every mode) into each cell's
  `ImageSettings`, so a foreign key (e.g. threshold on a Floyd grid) never reaches the
  stored settings. Validate rejects unknown keys, out-of-range values and a 3D focus drop
  `z_step × (levels − 1)` above `raster.MAX_DEPTH_DROP_MM` (3 mm) with German errors
  („Unbekannte Bildoption…“, „Schwellwert außerhalb 0..255“, „Fokus-Absenkung … > 3 mm“).
- **Dialog** (`lumacut_job/qt_tools.py`): when Art is Bild, the rows follow the Bildmodus –
  „Schwellwert“ (Schwellwert), „Halbton-Zellen“ + „Rasterwinkel“ (Halbton), „3D-Stufen“ +
  „Z-Schritt je Stufe“ (3D-Tiefe) – plus „Helligkeit“, „Kontrast“, „Gamma“ and „Negativ
  (Helles lasern)“ for every mode; German tooltips; start values from the spec or the
  `ImageSettings` defaults. `spec()` emits only values that differ from the defaults
  (`None` when untouched, so the dialog's spec equals the round-40 one); fill / outline
  never carry options. A too deep 3D drop disables OK with a German hint.

Tests:

- New `tests/test_material_test_image_options.py` (24 tests): option tables match
  `ImageSettings` fields; `None` / `{}` / default-valued options give byte-identical image
  G-code for floyd / grayscale / threshold / halftone / depth3d; threshold changes the lit
  length on the ramp; halftone cells / angle and depth3d levels / Z step reach every cell
  and stay Pi-safe; adjustments apply to all modes; foreign-mode keys and vector grids are
  ignored; range / unknown-key / 3D-drop validation; save / load round-trip; dialog row
  visibility per mode, changed-values-only round-trip, reopen with options, OK blocked on
  a > 3 mm drop. Existing ramp / wedge / photo, vector-grid SHA and round-34 SHA tests
  unchanged.

Full suite touch: material-test image + options + params + grid focused runs green (107
passed). The single-process full run SIGABRTs early on this box, so the suite was run file
by file: 1842 passed, 4 failed – `tests/test_polygon.py` (3, Canvas) and `tests/test_trace.py`
(1) – and eight files abort with a Qt / native SIGABRT before finishing
(`test_barcode`, `test_image_adjustments`, `test_image_black_white_point`,
`test_image_levels`, `test_image_modes`, `test_image_scan_angle`, `test_import`,
`test_qr_text_segments`). All of these fail / abort identically on main (`716b0c5`
studio code) – pre-existing, unrelated to this round. Running the material-test files
together in one process also aborts on main (`test_material_test.py::test_insert_is_one_undo_step`
after the image-dialog tests); each file passes alone.

Output change for old files: none – `image_options` defaults to `None`; image cells without
options keep exactly the round-40 settings and G-code; vector grids keep the round-34 SHA.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover threshold, halftone cells /
  angle, 3D levels / Z step and brightness / contrast / gamma / negative; sharpen, black /
  white point, tone curve, dot width correction, scan angle and bidirectional / overscan still
  take their defaults, and one option set applies to the whole grid (no option on an axis,
  e.g. a threshold or halftone-angle sweep).
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative) on wood / card against real photo
  engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 49. Status update 2026-11-09 (review round 42)

Done this round (material test image cells – remaining image settings; Canvas / Machine /
Scan Probe / Materials untouched):

- Closed since §48 by others: none – main had no new commits since `73b1269`.
- Gap picked from the §48 „Still open“ list: **material test image cells – sharpen, black /
  white point, tone curve, dot width correction, scan angle and bidirectional / overscan
  still take their defaults**. With round 41 a grid could already test threshold / halftone /
  3D / adjustments, but a photo that is engraved with an S-curve, levels, a 45° scan angle or
  unidirectional rows could not be reproduced in the test cells. Chosen before an image
  option on an axis (bigger change to the axis / label / layer-name model, kept for later).
- **Engine** (`lumacut_job/material_test.py`): `IMAGE_EXTRA_OPTIONS` = `sharpen`,
  `sharpen_radius`, `black_point`, `white_point`, `curve`, `dot_width_mm`, `scan_angle`,
  `angle_increment`, `bidirectional`, `overscan_mm` join `IMAGE_OPTION_KEYS` and apply to
  every image mode (like the adjustments). `image_overrides()` types them (bool / int /
  float, the curve through `normalize_curve`, so a list from JSON or a straight line gives
  the stored tuple / `()`); new `min_interval()` = smallest cell line interval (interval axis
  included). Validate adds the ranges of `ImageSettings.normalized()`, black point < white
  point, the curve (2..16 points, 0..255, rising inputs) and dot width ≤ smallest line
  interval with German errors („Schwarzpunkt muss kleiner als der Weißpunkt sein“,
  „Punktbreitenkorrektur 0.3 mm > kleinster Linienabstand 0.25 mm“, „Kurve: …“).
- **Dialog** (`lumacut_job/qt_tools.py`): under the Modus-Parameter a checkbox „Weitere
  Bildoptionen (Schärfen, Tonwerte, Kurve, Scan)“ (only for Art Bild) shows „Schärfen“,
  „Schärferadius“ (enabled when sharpening), „Schwarzpunkt“, „Weißpunkt“, „Kurve“ (the
  curve presets of the image settings; a custom curve from the spec appears as
  „Benutzerdefiniert“), „Punktbreitenkorrektur“, „Scan-Winkel“, „Winkel-Schritt je
  Durchgang“, „Overscan“ and „Bidirektional (hin und zurück lasern)“, with German tooltips.
  Off = hidden and not applied (the dialog stays as short as in round 41); it starts on when
  the spec carries one of these options. `spec()` emits only changed values (`None` when
  untouched). Black ≥ white point or a dot width above the smallest line interval disables
  OK with a German hint.

Tests:

- New `tests/test_material_test_image_extra_options.py` (37 tests): extra keys are
  `ImageSettings` fields with ranges; default-valued extras give byte-identical G-code for
  floyd / grayscale / threshold / halftone / depth3d; each option reaches every cell and
  changes the (Pi-safe) G-code; extras apply to greyscale / halftone / 3D; 90° scan angle
  gives rows along Y; unidirectional rows all run one way; no overscan shortens the program;
  curve normalisation; range / levels / curve / dot-width validation incl. the interval axis;
  save / load round-trip; dialog checkbox visibility, sharpen-radius enabling,
  changed-values-only round-trip, reopen with a custom curve, OK blocked on bad levels /
  dot width. Round-41 `test_material_test_image_options.py` unchanged and green.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2245 passed, 3 skipped**, 0 failed (11 min). (The
Python 3.11 venv in the main checkout still SIGABRTs in `test_barcode.py`, as noted in §48 –
an environment issue, not a code one.)

Output change for old files: none – `image_options` defaults to `None`, and the dialog only
emits extra options when „Weitere Bildoptionen“ is on and a value was changed.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options now cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan), but one option set applies to the whole grid (no image option on
  an axis, e.g. a threshold, halftone-angle or scan-angle sweep).
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan) on wood / card against real photo
  engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 50. Status update 2026-11-09 (review round 43)

Done this round (material test image cells – image option on an axis; Canvas / Machine /
Scan Probe / Materials untouched):

- Closed since §49 by others: none – main had no new code commits since `d655659` (only the
  user's hardware notes).
- Gap picked from the §49 „Still open“ list: **material test image cells – one image option
  set applies to the whole grid**. A LightBurn-style Interval Test that sweeps the threshold,
  the halftone screen or the scan angle across the cells needed one grid per value. Now an
  image option can go on a column or row axis instead.
- **Engine** (`lumacut_job/material_test.py`): `IMAGE_AXIS_PARAMS` = `threshold`,
  `halftone_cpi`, `halftone_angle`, `brightness`, `contrast`, `gamma`, `sharpen`,
  `scan_angle` (numeric options only) join the axis parameters (`AXIS_PARAMS` =
  `TEST_PARAMS` + image axes, `AXIS_PARAM_LABELS` with the German option labels; `TEST_PARAMS`
  itself unchanged). New spec field `image_axis_ranges` = {option: (from, to)}, missing =
  `IMAGE_AXIS_DEFAULT_RANGES` (e.g. threshold 64..192, gamma 0.6..1.8, scan angle 0..90°);
  threshold values are integers, gamma has two decimals. `cell_settings()` carries the swept
  value; `image_cell()` puts it on top of the grid-wide `image_overrides()` (the axis wins, the
  other options stay). Column / row labels show the value (brightness / contrast signed), and
  `cell_layer_name()` appends it with its unit (`Test P20% F600 Schwellwert 128`,
  `… Helligkeit +20% Scan-Winkel 90°`), so the cells are distinguishable in the layer panel;
  two image axes (e.g. threshold × gamma) work. Validation with German errors: an image axis
  needs image cells („Gamma als Achse nur mit Bild-Testzellen“), mode-specific axes need their
  mode („Schwellwert-Achse nur im Bildmodus Schwellwert“, halftone cells / angle →
  Halbton; derived from `IMAGE_MODE_OPTIONS`), from / to within the `ImageSettings.normalized()`
  range („Scan-Winkel außerhalb -90..90“), from ≠ to and no duplicate cells after rounding
  („… von und bis müssen verschieden sein“), unknown keys / non-numbers in
  `image_axis_ranges`. The image raster path is unchanged, so the cells stay Pi-safe G-code.
- **Dialog** (`lumacut_job/qt_tools.py`): the Spalten- / Zeilen-Parameter combos list the
  image options as „Schwellwert (Bild)“, „Rasterwinkel (Bild)“, … – enabled only with Art Bild
  and a matching Bildmodus (threshold only in Schwellwert, halftone only in Halbton). An image
  axis shows „<Option> von“ / „<Option> bis“ spins under its Spalten / Zeilen row with the
  option's range, decimals and unit (° / % / /Zoll); the range is remembered per option when
  the axis is switched. The grid-wide widget of the swept option is hidden and not emitted in
  `image_options`. Image axis without Art Bild, a mode mismatch or equal / colliding from–to
  values disable OK with a German hint. `spec()` emits `image_axis_ranges` only for image
  axes (`None` otherwise); a reopened spec restores the axes and ranges.

Tests:

- New `tests/test_material_test_image_axis.py` (38 tests): axis keys are numeric
  `ImageSettings` options with ranges and valid defaults; each of the eight options swept on a
  column reaches the cells with the expected values and changes the (Pi-safe) G-code; integer
  threshold steps; default range; the axis overrides the grid-wide value while other options
  stay; two image axes; layer names / labels with the swept value (unique per cell); mixed
  power × threshold names; validation (no image cells, mode mismatch, ranges, from = to,
  rounding collisions, unknown key, non-numbers); unused ranges change nothing; grids without
  an image axis keep the classic names; save / load round-trip (settings, names, G-code);
  dialog: image axes disabled without Art Bild / wrong mode, spins with range / decimals /
  unit, hidden grid-wide widget, spec / validate / cell values, remembered range, OK blocked
  with hints, reopen round-trip, untouched dialog gives `image_axis_ranges = None`.
  Round-40–42 material-test tests unchanged and green.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2283 passed, 3 skipped**, 0 failed (11 min). (The
Python 3.11 venv in the main checkout still SIGABRTs in `test_barcode.py`, as noted in §48 –
an environment issue, not a code one.)

Output change for old files: none – `image_axis_ranges` defaults to `None`, the axis defaults
stay power × speed, and layer names only change when an image option is on an axis. Checked
against `d655659`: G-code and layer names of default, outline, floyd, threshold × interval /
passes, halftone wedge × focus and greyscale-with-options grids are byte-identical.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle can also be swept on an axis. Not on an axis:
  3D levels / Z step, black / white point, dot width, overscan, angle increment, the tone
  curve and the booleans (negative, bidirectional); one shared test image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder; undoing the advance step rewinds the counter.
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed incl. the labels and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels, rebuilt exe).

## 51. Status update 2026-11-09 (review round 44)

Done this round (variable text – undo never rewinds the counter; Canvas / Machine / Scan Probe /
Materials untouched):

- Closed since §50 by others: none – main had no new commits since `17ced16`.
- Gap picked from the §50 „Still open“ list: **variable text – undoing the advance step rewinds
  the counter**. Rounds 40–43 were all material-test image cells, so this round takes a
  user-visible gap outside that area. It was also the riskiest open item: after a send the
  advance was the newest undo step, so the first Ctrl+Z after a job (meant for the last edit)
  silently set the serial number / CSV row back and the next job lasered the *same* number
  again; undoing any edit made before the send restored a stored shape copy with the old
  counter too. LightBurn's Variable Text never brings a lasered serial number back with undo
  (only an explicit change in the settings resets it). Chosen before the keyboard / serial
  input placeholder (a new prompt-at-send flow touching the send path that the Machine agent
  owns) and before fill grouping across layers (planner order change, needs hardware checks).
- **Advance is no undo step** (`lumacut_job/vartext_qt.py`): `advance()` replaces the series'
  shapes in place (`put_shapes`, same ids and z order) instead of pushing a macro, and calls
  `QUndoStack.resetClean()`, so the project is still marked as changed (title „•“, the close
  prompt asks to save the new values). Ctrl+Z after a send now undoes the user's last real edit.
- **Ledger** (`VarTextLedger`, one per editor via `ledger_of()`, created by the tracker): the
  values a sent job advanced to are kept per (series, epoch) and re-applied after every undo
  index change (undo, redo, new step) to every variable text of that series and epoch – no
  undo step, so an older stored copy (moved / edited / deleted-and-restored text, a pasted copy
  of an old state) can no longer bring the old counter or CSV row back. Nothing is recorded with
  an empty history (no stored copy exists), and the ledger is cleared with the history (new /
  opened project).
- **Epoch** (`lumacut_job/vartext.py`): new `VarTextSpec.epoch`; `apply_vartext()` (OK in
  „Variabler Text…“) sets a fresh one, so a deliberate dialog change („Auf Start“, another next
  value / row) wins over the advanced values, and undoing that change gives the advanced values
  back. `spec_dict()` leaves an empty epoch out, so `make_meta()` / saved projects and the
  `; VARIABLE TEXT <token>` job marker of specs without an epoch stay byte-identical.
- UI text: the status message reads „Variabler Text weitergeschaltet: … (kein
  Rückgängig-Schritt – zurücksetzen in „Variabler Text…“)“; the „Nächster Wert“ tooltip says
  that Strg+Z does not count back.

Tests:

- New `tests/test_vartext_undo_ledger.py` (14 tests): epoch default / omitted from old metas /
  kept by `advanced_spec`; job-marker token unchanged for specs without an epoch; advance is no
  undo step but marks the stack unclean; undo / redo of a move or of text edits across several
  jobs keeps the counter (next job lasers 3, 4 – no duplicate); CSV row kept; a deleted-and-
  restored copy and a pasted old copy get the advanced value; other series and plain texts
  untouched; dialog reset wins, undoing it restores the advanced value, and the values of both
  epochs survive further undo / redo; every apply gets a new epoch; ledger empty without history
  and cleared with it; texts from a newer version skipped; main window: send, status message,
  „•“ title, Ctrl+Z undoes the dialog step and redo comes back with the advanced value.
- `tests/test_variable_text.py`: the tracker test asserted the old behaviour („undo rewinds the
  counter“); it now checks that the advance leaves no undo step and the counter stays.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2297 passed, 3 skipped**, 0 failed (11 min; 2283 + 14 new).

Output change for old files: none – G-code and the job marker of an old variable-text project,
its saved generator dicts and the advanced metas are byte-identical to `17ced16` (checked with a
three-text, two-series document incl. `{date}`, padding and `per_copy` off). Only behaviour
changes: Ctrl+Z after a send no longer rewinds the counter / CSV row, and specs applied in the
dialog from now on carry an `epoch` key in the project file.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle can also be swept on an axis. Not on an axis:
  3D levels / Z step, black / white point, dot width, overscan, angle increment, the tone
  curve and the booleans (negative, bidirectional); one shared test image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog preview shows pass 1 only (with an angle
  increment the later passes are not previewed); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed incl. the labels and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 52. Status update 2026-11-09 (review round 45)

Done this round (image scan angle – preview of every pass; Canvas / Machine / Scan Probe /
Materials untouched):

- Closed since §51 by others: none – main had no new commits since `88825be`.
- Gap picked from the §51 „Still open“ list (Image): **scan angle – the dialog preview shows
  pass 1 only**. With a „Winkel-Schritt je Durchgang“ (e.g. 90° cross raster, or 30° steps
  against wood grain) the user could not see what passes 2… engrave before sending: the
  dither / halftone pattern of an oblique pass differs from pass 1, and the label only said
  „(Vorschau: 1. Durchgang)“. LightBurn's preview shows all passes of a cross-hatched image;
  xTool Creative Space has no angle increment at all. Chosen before the keyboard / serial
  variable-text placeholder (prompt-at-send flow in the send path – Machine) and fill
  grouping across layers (planner order change, needs hardware checks); purely
  preview-side, so the G-code is unchanged.
- **Engine** (`lumacut_import/image_preview.py`): new `pass_angle(settings, pass_index)`
  (clamped to the passes); `render_for_preview()` and `preview_shape()` take a
  `pass_index` (default 0 = the old preview, byte-identical) and render / rotate back the
  raster of that pass's scan angle exactly like the job. `preview_shape_passes()` overlays
  the passes via `overlay_previews()` – rotated rasters of different size are centred on the
  largest, per dot the darkest value wins (lasered if any pass lasers it), the burn share is
  the mean of the passes; `distinct_pass_indices()` renders every angle once (0° / 90° / 0°
  → two renders).
- **Dialog** („Bildeinstellungen“, `lumacut_import/qt.py`): under the preview a new
  „Vorschau zeigt“ choice (`image_preview_pass`) lists „1. Durchgang (30°)“, „2. Durchgang
  (75°)“, … and „Alle N Durchgänge übereinander“; it is shown only for an image object with
  more than one pass and a non-zero angle increment, keeps the chosen pass while angles change
  (falls back to pass 1 when that pass disappears), and is preview-only (not saved in the
  settings). The label names the shown pass and its angle. The render cache now holds one
  entry per scan angle (cleared on a new line interval / negative), so switching passes or
  changing power / mode does not re-render; the histogram stays on pass 1. Changing the
  angle increment now refreshes the choice and the preview (it was not connected before).

Tests:

- New `tests/test_image_scan_angle_pass_preview.py` (9 tests): pass angles incl. clamping and
  distinct passes; `pass_index` 0 equals the old preview / render; pass 2 of a 0° + 90°
  increment equals a plain 90° preview and keeps the canvas orientation; overlay (darkest dot,
  centring, burn share mean, copy for one pass, error for none); all-passes overlay covers each
  pass and renders a cross raster's repeated angle once; dialog choice labels, relabelling on a
  new increment, fallback with fewer passes, hidden for one pass / no increment; dialog shows
  the chosen pass and the overlay with one render per angle, power changes reuse the cache,
  a new line interval re-renders; the choice schedules a preview; the dialog without an image
  object keeps the old hint.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2306 passed, 3 skipped**, 0 failed (14 min; 2297 + 9 new).

Output change for old files: none – the preview is dialog-only; G-code, project files and
`ImageSettings` are unchanged.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle can also be swept on an axis. Not on an axis:
  3D levels / Z step, black / white point, dot width, overscan, angle increment, the tone
  curve and the booleans (negative, bidirectional); one shared test image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass or all passes overlaid
  (darkest dot per position – the extra burn of greyscale dots hit by several passes is
  not added up); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine.
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed incl. the labels and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ preview) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 53. Status update 2026-11-09 (review round 46)

Done this round (material test image cells – black / white point, dot width and overscan on
an axis; Canvas / Machine / Scan Probe / Materials untouched):

- Closed since §52 by others: none – main only got the user's hardware commit `e35e4da`
  („Gestell v1“) since `b86863b`.
- Gap picked from the §52 „Still open“ list (Material test): **black / white point, dot width
  and overscan cannot be swept on an axis**. These are the image settings a user calibrates
  per material: the black point (where shadows burn to full power), the white point (where
  light tones stay unburnt), the dot width correction (beam width against the line interval)
  and the overscan (clean line ends at speed). So far each value needed its own grid (or a
  manual series of image objects); LightBurn's Interval Test sweeps only power / speed /
  interval, xTool Creative Space's material test only power / speed. Chosen before the
  all-passes burn sum (preview-only refinement of round 45), the per-axis acceleration
  model (needs SKR measurements to compare), node edits on code parts (Canvas owns the
  path editing) and the keyboard / serial variable-text placeholder (send path – Machine):
  it directly saves test material and time and reuses the round-43 axis machinery.
- **Engine** (`lumacut_job/material_test.py`): `IMAGE_AXIS_PARAMS` += `black_point`,
  `white_point`, `dot_width_mm`, `overscan_mm` (every image mode). Default ranges black point
  0..64, white point 192..255 (integer grey values), dot width 0..0.1 mm (three decimals),
  overscan 0..5 mm; units in layer names `mm` (`Test P20% F600 Punktbreitenkorrektur 0.05mm`,
  `… Overscan 2mm`, `… Schwarzpunkt 32`). Coupled options are now checked **per cell**
  (`MaterialTestSpec.image_cell_problem()`): the swept black point against the grid-wide or
  the swept white point („Schwarzpunkt 100 muss kleiner als der Weißpunkt 80 sein (in jeder
  Testzelle)“), the swept dot width against that cell's line interval (also with the interval
  on the other axis: „Punktbreitenkorrektur 0.2 mm > Linienabstand 0.1 mm der Testzelle“).
  The grid-wide black / white and dot-width checks are skipped for a swept option (the axis
  value wins, as for the round-43 axes), so they stay unchanged without such an axis.
- **Dialog** (`lumacut_job/qt_tools.py`): the four options appear in the Spalten- /
  Zeilen-Parameter combos as „Schwarzpunkt (Bild)“, „Weißpunkt (Bild)“,
  „Punktbreitenkorrektur (Bild)“, „Overscan (Bild)“ (any Bildmodus); von / bis spins with
  step 16 (grey values, no decimals), 0.01 mm (three decimals) and 0.5 mm; the hidden
  grid-wide widget of a swept option is not emitted. The per-cell check disables OK with the
  engine's German message; the old „Schwarzpunkt muss kleiner …“ / dot-width hints are not
  raised by the hidden widget of a swept option.

Tests:

- New `tests/test_material_test_levels_axis.py` (17 tests): new axes offered with default
  ranges (integer grey values, dot-width decimals); each of the four options swept on a
  column reaches the cells and changes the (Pi-safe) G-code; layer names with the value and
  unit; black axis vs. grid-wide white point, black × white axes per cell, swept white point
  ignores a conflicting grid-wide value; dot width vs. each cell's interval (also with an
  interval axis); overscan range; grid-wide checks unchanged without an axis; save / load
  round-trip (settings, names, G-code); dialog spins / hidden widgets / spec, OK blocked and
  released for black > white and dot width > interval, reopened overscan spec. The round-43
  tests that loop over every image axis now also cover the four new axes (defaults within the option ranges,
  disabled without Art Bild).

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2323 passed, 3 skipped**, 0 failed (11 min; 2306 + 17 new). A first run had one
failure in `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
(`wait_until` for „ok start“ timed out under load; untouched Machine code) – the file passes alone
(3 ×) and the complete rerun was green.

Output change for old files: none – the axis defaults stay power × speed and only grids with
one of the new axes get different names / G-code. Checked against `e35e4da`: G-code and layer
names of the default, outline, Floyd, grayscale with grid-wide black / white point, dot
width and overscan, threshold × interval and gamma × speed grids are byte-identical.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan can be swept on an axis. Not on an axis: 3D levels / Z step, angle
  increment, the tone curve and the booleans (negative, bidirectional); one shared test
  image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass or all passes overlaid
  (darkest dot per position – the extra burn of greyscale dots hit by several passes is
  not added up); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ preview) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 54. Status update 2026-11-09 (review round 47)

Done this round (image scan angle – burn sum of all passes in the preview; Canvas / Machine /
Scan Probe / Materials untouched):

- Closed since §53 by others: none – main had no new commits since `1d8bf0c`.
- Gap picked from the §53 „Still open“ list (Image / scan angle): **the all-passes preview
  shows the darkest dot per position – the extra burn of dots hit by several passes is not
  added up**. With an angle increment (cross raster 0° / 90°, 30° / 45° steps against the
  wood grain) the dots where the passes cross get the power of every pass; in greyscale a
  50 % dot burnt twice ends up as dark as one full-power dot. The round-45 overlay showed
  such a raster like a single pass, so the user could not see the over-burnt crossings /
  the darker tone before sending. LightBurn's preview of a multi-pass image shades by the
  number of passes; xTool Creative Space has no angle increment. Chosen before the variable
  text value drawn in the object itself (canvas rendering – Canvas), the boolean / angle
  increment material-test axes (less calibration value than the image preview the user
  sees for every multi-pass engraving) and the per-axis acceleration model (needs SKR
  measurements); purely preview-side, so the G-code is unchanged.
- **Engine** (`lumacut_import/image_preview.py`): new `sum_previews(previews, counts)` –
  per dot the darkness (`255 - value`) of every pass is added and divided by the number of
  passes (black = every pass at full power, one of N passes at full power = 1/N grey);
  rotated rasters of different size are centred like `overlay_previews()`; `counts` weighs
  an angle that repeats (0° / 90° / 0° → `[2, 1]`), so each angle is still rendered once.
  `Preview` gets an optional `multi_share` (share of the lasered dots hit by more than one
  pass; `None` for single passes and the overlay), `burn_share` is the pass-weighted mean.
  `preview_shape_passes(…, burn_sum=True)` returns the sum; the default (`False`) keeps the
  round-45 darkest-dot overlay byte-identical.
- **Dialog** („Bildeinstellungen“, `lumacut_import/qt.py`): „Vorschau zeigt“ gets a last
  entry „Alle N Durchgänge aufaddiert (Brennsumme)“ (`ALL_PASSES_SUM`, preview-only like the
  other entries, shown under the same rule – image object, more than one pass, angle
  increment); it reuses the per-angle render cache. The label says „Brennsumme aller N
  Durchgänge – Schwarz = alle mit voller Leistung; X % der gelaserten Punkte mehrfach
  gelasert“; the tooltip explains the three views.

Tests:

- New `tests/test_image_burn_sum_preview.py` (6 tests): sum arithmetic (full / half power,
  one of two passes = half grey, rounding, weighted burn share, multi share); repeated-angle
  counts, centring of different sizes, single preview, invalid counts; threshold cross raster
  (never darker than the overlay, lasered exactly where it lasers, crossings black / single
  hits half grey, overlay unchanged without `multi_share`); a 0° / 90° / 0° greyscale image
  renders each angle once and counts 0° twice; a mid-grey greyscale image sums to the
  mean darkness; dialog entry label / position, the shown sum equals the engine, label with
  the multi share, render cache reused (also when switching to the overlay), choice kept on
  a new increment, preview-only, hidden for one pass.
- `tests/test_image_scan_angle_pass_preview.py`: the choice list now ends with the new entry
  (labels and the count after reducing the passes updated).

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2329 passed, 3 skipped**, 0 failed (11 min; 2323 + 6 new), first run green.

Output change for old files: none – the burn sum is a dialog-only preview; G-code, project
files and `ImageSettings` are unchanged. Checked against `1d8bf0c`: single-pass previews of
every pass, the darkest-dot overlay (pixels and burn share) and the G-code of floyd /
greyscale / threshold / halftone images with and without angle increment are byte-identical.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan can be swept on an axis. Not on an axis: 3D levels / Z step, angle
  increment, the tone curve and the booleans (negative, bidirectional); one shared test
  image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 55. Status update 2026-11-09 (review round 48)

Done this round (material test image cells – angle increment and the on / off options
negative / bidirectional on an axis; Canvas / Machine / Scan Probe / Materials untouched):

- Closed since §54 by others: none – main had no new commits since `799891a`.
- Gap picked from the §54 „Still open“ list (Material test): **angle increment and the
  booleans (negative, bidirectional) cannot be swept on an axis**. For a diode laser these
  are everyday questions per material: does bidirectional engraving stay sharp at this
  speed or does it need the slower unidirectional mode (line offset / „ghosting“ at
  3000–6000 mm/min), does an inverted image (slate, anodised aluminium, dark wood) look
  better, and which cross-raster angle increment evens out the wood grain with 2–3 passes.
  So far each answer needed a second grid. LightBurn's Interval Test sweeps power / speed /
  interval only, xTool Creative Space's material test power / speed only. Chosen before
  the node edits on code parts (path editing – Canvas), the keyboard / serial
  variable-text placeholder (send path – Machine), in/min speeds (unit UI shared with
  Materials' presets) and the per-axis acceleration model (needs SKR measurements): it
  completes the image-option axes with the round-43 machinery, no user decision needed.
- **Engine** (`lumacut_job/material_test.py`): `IMAGE_AXIS_PARAMS` += `angle_increment`
  (default 0..90°, unit `°`, layer names `Test P20% F600 Winkel-Schritt 45°`); new
  `IMAGE_BOOL_AXIS_PARAMS = ("negative", "bidirectional")` (`IMAGE_ALL_AXIS_PARAMS` = both
  lists, part of `AXIS_PARAMS`): an on / off axis has exactly two columns / rows, first aus
  then an, no range (`image_axis_ranges` still only accepts numeric options); labels
  „aus“ / „an“, layer names `… Bidirektional aus`, `… Negativ an`. The swept value
  overrides the grid-wide option as before. Validation: „Negativ-Achse braucht genau 2
  Spalten (aus / an)“; an angle-increment axis needs more than one pass in some cell
  (fixed passes or the passes axis, `MaterialTestSpec.max_passes()`): „Winkel-Schritt-Achse
  braucht mehr als einen Durchgang (dreht erst den 2. und jeden weiteren Durchgang)“.
- **Dialog** (`lumacut_job/qt_tools.py`): „Winkel-Schritt (Bild)“, „Negativ (Bild)“ and
  „Bidirektional (Bild)“ in the Spalten- / Zeilen-Parameter combos (any Bildmodus, image
  cells only). The angle increment gets von / bis spins (15° step); an on / off axis sets
  its Spalten / Zeilen count to 2 and locks it (re-enabled when another parameter is
  chosen), shows no von / bis spins, and hides / does not emit the grid-wide checkbox. OK is
  disabled with „Winkel-Schritt-Achse braucht mehr als einen Durchgang („Durchgänge“ ≥ 2).“
  until Durchgänge (or Durchgänge bis on a passes axis) is ≥ 2; the passes spins now
  refresh the check.

Tests:

- New `tests/test_material_test_toggle_axis.py` (21 tests): new axes offered (default
  range, aus / an values, combined axis list); each on / off option on a column reaches the
  cells and changes the (Pi-safe) G-code; the axis overrides the grid-wide value and keeps
  the others; negative × bidirectional 2 × 2 grid (cells, unique layer names, „aus“ / „an“
  labels); angle increment 0 / 45 / 90° with 2 passes (pass angles, layer name, G-code),
  with a scan angle and a passes axis; validation (2 columns / rows, image cells only,
  passes ≥ 2 also via the passes axis, range, from = to, no range for an on / off option);
  classic names without the new axes; save / load round-trip; dialog: offered only for
  image cells with „(Bild)“, on / off axis locks the count at 2 and hides the grid-wide
  checkbox (also on both axes, unlocked again for power), angle-increment spins and the
  passes hint, reopened spec equals the dialog spec.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2350 passed, 3 skipped**, 0 failed (11 min; 2329 + 21 new), first run green.

Output change for old files: none – the axis defaults stay power × speed and only grids with
one of the new axes get different names / G-code. Checked against `799891a`: G-code and
layer names of the default, outline, Floyd, greyscale with grid-wide negative /
unidirectional / 90° angle increment over 2 passes, threshold × interval and gamma ×
3 passes with scan angle 45° / increment 30° grids are byte-identical.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan, since round 48 the angle increment and – as aus / an axes over
  exactly two columns / rows – negative and bidirectional can be swept on an axis. Not on
  an axis: 3D levels / Z step and the tone curve; one shared test image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`, `… Bidirektional aus`,
  `… Winkel-Schritt 45°`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  but with one XY acceleration, so Marlin's per-axis limits on diagonal moves are not modelled
  (to be compared on the SKR); the park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, bidirectional
  aus / an × speed at 3000–6000 mm/min (line offset), negative aus / an on slate / anodised
  aluminium and angle increment 0..90° × 2–3 passes, incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 56. Status update 2026-11-10 (review round 49)

Done this round (job time estimate – plans with the Pi's motion calibration and Marlin's
per-axis feed limits; Canvas / Machine / Scan Probe / Materials untouched apart from a
one-method hook in the path preview):

- Closed since §55 by others: none – main had no new commits since `6d41569`.
- Gap picked: the time estimate (#2, LightBurn Preview „Total estimated time“, xTool's job
  time) always planned with the firmware defaults 500 mm/s² / 150 mm/s, while the Pi sends
  its motion calibration (`config.motion`, `M201` / `M203` / `M204`, e.g. 2100 mm/s² /
  200 mm/s on the SKR, capped on the Atomstack board) at every connection and jobs run with
  it. So every estimate – path preview, „Zeit schätzen“, the one-click start prompt, the
  send message and the job history – was too long on a calibrated machine (a 6000 mm/min
  hatch job: 279 s estimated, 232 s with the calibration, −17 %), and the open §54 item
  „one XY acceleration, Marlin's per-axis limits on diagonal moves not modelled“ stayed open.
  LightBurn and xTool estimate with the device's configured acceleration. Chosen over the
  remaining small material-test increments (tone curve / 3D-level axes) and the 2D-code
  extras (MicroPDF417, Macro PDF417, structured append): it improves a number the user
  sees for every job and needs no user decision; the SKR comparison stays a hardware test.
- **Model** (new `lumacut_job/motion.py`): `MotionProfile(accel, speed, z_speed, source)`;
  `motion_from_status(raw)` reads `config.motion` / `config.z_speed_mm_s` from
  `/api/status` (ranges as `op=motion_limits`: 100..20000 mm/s², 10..500 mm/s; null,
  incomplete or out-of-range motion = firmware values „Pi ohne Kalibrierung (Firmware)“;
  Z capped at the firmware's 9 mm/s; no `config` = keep what is known). `active_motion()` /
  `set_active_motion()` with change listeners; `load_saved` / `save` keep the last seen
  calibration (QSettings `estimate/motion_*`, only non-default values are restored).
- **Estimate** (`lumacut_job/estimate.py`): `estimate_gcode` takes its limits from the
  active profile (explicit `accel` / `max_xy` / `max_z` or `motion=` still win);
  `JobEstimate.motion` + `motion_note()` („Bewegung: Pi-Kalibrierung 2100 mm/s², 200 mm/s“).
  The feed limit is per axis like `M203 X Y`: a move's path speed is capped at
  `speed / max(|ux|, |uy|)`, so a 45° image row or diagonal cut at F12000 runs 200 mm/s
  instead of being cut to 150 (≤ 212 mm/s). With the firmware defaults the old numbers stay:
  axis-aligned moves and default rapids (F9000) are unchanged.
- **App** (`qt_tools.install_motion_sync`): `MotionSync` follows the Machine panel's
  `status_changed`; the first status of a session and any change set the profile and store
  it (also the reset to firmware values, so a stale calibration never comes back); offline
  the Windows app starts with the last seen one („Pi-Kalibrierung (zuletzt gesehen)“). A
  change re-estimates the open path preview without regenerating its G-code
  (`PathPreview.refresh_estimate`); the preview readout's tooltip and the „Zeit schätzen“
  status message name the limits used. Tests write to a temporary ini
  (`LUMACUT_MOTION_SETTINGS`, conftest) and reset the profile around every test.

Tests:

- New `tests/test_estimate_motion.py` (20 tests): firmware defaults and note; active profile
  drives acceleration / speed (exact trapezoid times); explicit arguments win; per-axis feed
  limit at 45° / 30° and unchanged axis-aligned / default rapid times; Z speed; status
  parsing (calibrated, null, Atomstack-capped, Z cap / slow Z, 7 invalid forms → firmware,
  no `config` keeps the limits, via `MachineStatus.from_json`); listeners only on a real
  change; sync stores once per change, reduced answers keep the limits, restart uses the
  stored calibration, reset to firmware clears it; garbage in the store; the env ini; main
  window: a status re-estimates the preview (same G-code, shorter time, tooltip) and
  „Zeit schätzen“ names the Pi calibration.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2370 passed, 3 skipped**, 0 failed (13 min; 2350 + 20 new), first run green.

Output change for old files: none – G-code is not touched. Estimates with the firmware
defaults are identical to `6d41569` (checked on a hatch + cut job at 3000 and 6000 mm/min:
440.25 s / 279.13 s both before and after); only diagonal moves whose F exceeds the axis
limit and – once a Pi was seen – the calibrated limits change the times.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan, since round 48 the angle increment and – as aus / an axes over
  exactly two columns / rows – negative and bidirectional can be swept on an axis. Not on
  an axis: 3D levels / Z step and the tone curve; one shared test image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`, `… Bidirektional aus`,
  `… Winkel-Schritt 45°`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  with the Pi's motion calibration and per-axis feed limits since round 49 (§56); the
  park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Time estimate (§56): Cartesian model – a CoreXY frame (Gestell v1) limits the motor axes
  (A = X+Y, B = X−Y), so diagonals would have to be planned per motor once that frame runs;
  Grbl's own planner on the Atomstack board (dynamic laser mode) is planned like Marlin; one
  stored calibration per Windows user (switching between two Pis shows the other's values
  until the first status arrives); jobs still do not include homing / probing / parking.
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  keyboard / serial-port input placeholder. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests (material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, bidirectional
  aus / an × speed at 3000–6000 mm/min (line offset), negative aus / an on slate / anodised
  aluminium and angle increment 0..90° × 2–3 passes, incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, the time estimate with
  the SKR calibration (2100 mm/s², 200 mm/s) against the real run time of hatch / image /
  cut jobs incl. 45° image rows and the stored value offline after a restart, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 57. Status update 2026-11-10 (review round 50)

Done this round (variable text – keyboard input placeholder typed in at send; Canvas /
Machine / Scan Probe / Materials untouched – their send paths call `JobTools.job_gcode()`
unchanged):

- Closed since §56 by others: none – main had no new commits since `5092cd6`.
- Gap picked: variable text (§56 „no keyboard / serial-port input placeholder“). EzCad's
  *Keyboard* text and the „type a name before each part“ workflow LightBurn users build
  with CSV files: a name tag, a gift engraving or a batch label that changes per part had
  to be edited on the canvas (template lost) or put into a one-row CSV file. Now a
  template like `Für {input:Name}` asks for the value at every send. Chosen over the time
  estimate with homing / probing / parking (those run on the Pi and are timed by the
  Machine / Scan Probe job flow – no reliable model without their data), the in/min speed
  unit (little value for a metric user base) and the remaining material-test / 2D-code
  increments: it is user-visible on every personalised job, self-contained in
  `lumacut_job` and needs no user decision.
- **Model** (`lumacut_job/vartext.py`): placeholders `{input:Label}` and `{eingabe:Label}`
  (case-insensitive, optional default `{input:Label=Vorgabe}`; label 1–40 characters, an
  empty label is an error like the other placeholders). `InputField(label, default)`,
  `input_fields(template)`, `uses_input`, `document_inputs(doc)` (visible variable texts
  in reading order, each label once – all copies and series with the same label share one
  value). `evaluate` / `preview_values` / `evaluate_document` take `inputs=`; without it
  the session store (`input_values` / `set_input_values` / `clear_input_values`, keys
  case-folded, not saved in the project or settings) is used, then the default, then the
  stand-in `‹Label›`. Typed values are one line (line breaks / tabs → blanks, control
  characters removed, at most 200 characters). `{input:…}` is never taken as a CSV column
  (`{csv:input}` still reads a column called „input“).
- **App** (`JobTools.job_gcode(ask_inputs=True)`, `vartext_qt.VarTextInputDialog`): send,
  „Senden & Starten“ / one-click job (workflow and Scan Probe flow) and „G-Code speichern“
  open „Eingaben für den Auftrag“ (one line per label, pre-filled with the value typed last
  in the session, else the default; hint for empty fields – a text that becomes blank is
  left out as before). Cancel = nothing is sent / saved („Eingabe für den variablen Text
  abgebrochen“). „Zeit schätzen“, the estimate, frame, path preview, park-zone check and
  the canvas value labels never ask: they use the last typed value (or default /
  `‹Label›`); a new value rebuilds the canvas labels and re-schedules the path preview.
  „Nur Auswahl“ asks only for the labels in the selection. The counter / CSV advance after
  a successful upload is unchanged (the job marker includes the typed text). Dialog help
  and README list the new placeholder. Tests reset the session store (conftest).

Tests:

- New `tests/test_vartext_input.py` (17 tests): fields, defaults, aliases, case, escaped
  braces and the CSV distinction; 4 invalid forms; evaluation with explicit inputs, store,
  default and stand-in; one-line clean-up and length; document fields in reading order /
  hidden layer / literal text; shared value across series and copies, refit width, blank
  copy left out, template unchanged; combined with counter, CSV (column named „Input“) and
  date; old templates unchanged; the dialog (pre-fill, placeholder, empty hint, max
  length); main window: send asks once and lasers the value (Pi guard), labels / job
  document / estimate / frame reuse it without asking, one-click start asks again; cancel
  blocks send, start and save and the estimate shows `‹Name›` without asking; save asks,
  templates without input never ask; „Nur Auswahl“; preview labels follow a new value.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2387 passed, 3 skipped**, 0 failed (12.5 min; 2370 + 17 new), first run green.

Output change for old files: none – templates without `{input:…}` evaluate exactly as
before and no question appears; G-code of documents without variable text is untouched.
Only a template that already contained `{input:…}` / `{eingabe:…}` (until now a lookup of a
CSV column literally called „input:…“, i.e. an error in practice) now asks for a value.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan, since round 48 the angle increment and – as aus / an axes over
  exactly two columns / rows – negative and bidirectional can be swept on an axis. Not on
  an axis: 3D levels / Z step and the tone curve; one shared test image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`, `… Bidirektional aus`,
  `… Winkel-Schritt 45°`) are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  with the Pi's motion calibration and per-axis feed limits since round 49 (§56); the
  park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Time estimate (§56): Cartesian model – a CoreXY frame (Gestell v1) limits the motor axes
  (A = X+Y, B = X−Y), so diagonals would have to be planned per motor once that frame runs;
  Grbl's own planner on the Atomstack board (dynamic laser mode) is planned like Marlin; one
  stored calibration per Windows user (switching between two Pis shows the other's values
  until the first status arrives); jobs still do not include homing / probing / parking.
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  serial-port / barcode-scanner input placeholder (a USB scanner typing into the
  „Eingaben“ dialog works like a keyboard). Keyboard input (§57) is one value per label and
  send – copies cannot get different typed values in one job (use a CSV file), and typed
  values are kept for the session only. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests („Eingaben für den Auftrag“ at send / one-click start with a name
  tag – umlauts, long names, a USB barcode scanner typing into the dialog –, material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, bidirectional
  aus / an × speed at 3000–6000 mm/min (line offset), negative aus / an on slate / anodised
  aluminium and angle increment 0..90° × 2–3 passes, incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, the time estimate with
  the SKR calibration (2100 mm/s², 200 mm/s) against the real run time of hatch / image /
  cut jobs incl. 45° image rows and the stored value offline after a restart, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 58. Status update 2026-11-10 (review round 51)

Done this round (material test – tone curve and 3D levels / Z step as test axes; Canvas /
Machine / Scan Probe / Materials untouched – only `lumacut_job` and the shared curve
preset table):

- Closed since §57 by others: none – main had no new commits since `261ea93`.
- Gap picked: material test (§57 „Not on an axis: 3D levels / Z step and the tone
  curve“). For photo engraving on a diode laser the tone curve is the setting that decides
  whether dark wood grain drowns the shadows or light card stays blank; until now each
  curve needed its own grid (one curve grid-wide), so comparing „Linear / S-Kurve /
  Schatten aufhellen“ on the same board meant three jobs with drifting focus / material.
  LightBurn's Interval Test applies the layer's image settings, but users compare
  adjustments side by side – now one grid does it, crossed with power, speed or any other
  axis. The 3D-depth sweep (levels × Z step) closes the rest of the same item for relief
  tests. Chosen over variable text with distinct typed values per copy (rare – a CSV file
  covers it), Data Matrix EDIFACT (no practical gain for laser marking, ASCII / C40 / Base
  256 cover every payload) and the in/min speed unit (metric user base): it is
  self-contained in `lumacut_job`, extends the axis framework of rounds 43–48 and needs no
  user decision.
- **Model** (`lumacut_job/material_test.py`): new *choice* axis kind
  `IMAGE_CHOICE_AXIS_PARAMS = ("curve",)` (part of `IMAGE_ALL_AXIS_PARAMS` / `AXIS_PARAMS`).
  `MaterialTestSpec.image_axis_curves` = curves in column / row order (`((in, out), …)`,
  `()` = linear, lists accepted); `None` = the first n presets (`CURVE_AXIS_PRESETS`, the
  order of the image dialog's presets). Validation: 2.. columns / rows, at most 8 without a
  list, exactly one curve per column / row with a list, every curve valid (2–16 points,
  rising inputs), no duplicate curve. The cell's curve replaces the grid-wide `curve`
  option; the other image options stay. Labels and layer names carry the curve's short
  name (`CURVE_SHORT_LABELS`: Linear, S, S+, Flach, Mitte+, Mitte-, Tiefen+, Lichter-;
  curves that are no preset „Eigene 1“, „Eigene 2“ … in axis order) –
  `Test P50% F1200 Kurve S`; wide row labels widen the label column as before.
  `depth_levels` (4..16 by default, integer) and `z_step_mm` (0..0.2 mm) are numeric image
  axes for the image mode 3D-Tiefe (other modes: „3D-Stufen-Achse nur im Bildmodus
  3D-Tiefe“); the focus drop z_step × (levels − 1) ≤ 3 mm is checked per cell (axis value
  against the grid-wide or the other axis's value) instead of grid-wide.
  The preset table moved from `lumacut_import/curve_widget.py` to `lumacut_job/raster.py`
  (`CURVE_PRESETS`, free of Qt; `curve_widget` re-exports it – same object, the image
  settings dialog is unchanged).
- **App** (`MaterialTestDialog`): „Kurve (Bild)“, „3D-Stufen (Bild)“, „Z-Schritt (Bild)“ in
  the column / row parameter (enabled only with Art „Bild“, the depth axes only in
  3D-Tiefe). With the curve on an axis a „Kurven (Spalten / Zeilen)“ list appears: every
  preset checkable (first n checked when the axis is chosen, n = the current count, at most
  8), drag to reorder; the column / row count follows the checked curves and is locked,
  fewer than 2 blocks OK („Kurven-Achse: mindestens 2 Kurven anhaken“); the grid-wide
  „Kurve“ box under „Weitere Bildoptionen“ is hidden. A reopened spec lists its curves
  first in their order (custom ones as „Benutzerdefiniert N“), so the dialog returns the
  same spec. Depth axes: from / to spins (levels step 2, Z step 0.05 mm), hint and OK lock
  for a cell whose focus drop exceeds 3 mm. README: new bullet „Bildoptionen als Achse“.

Tests:

- New `tests/test_material_test_curve_axis.py` (27 tests): axes offered and the preset table
  shared with the image dialog; default curve axis (first presets, labels, layer names);
  the curve reaches the G-code (Linear cell = untouched image powers, S-curve cell differs,
  Pi guard); axis curve overrides the grid-wide curve and keeps gamma; custom curves on
  the rows („Eigene 1 / 2“, labels, widened label column); curve × power; 3D levels × Z
  step (settings, names, labels, G-code); per-cell focus-drop check for both depth axes;
  11 invalid forms; grids without the new axes unchanged (an `image_axis_curves` list
  without a curve axis is ignored, grid-wide drop check as before); save / load round trip;
  dialog: axes offered per mode, curve list sets / locks the count and emits the checked
  curves in order, minimum-2 hint, back to power, reorder, reopen with a custom curve
  (`spec() == spec`), depth-axis ranges and the drop hint.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2414 passed, 3 skipped**, 0 failed (11.7 min; 2387 + 27 new), first run green.

Output change for old files: none – grids without a curve / depth axis keep their layer
names, cells and G-code byte-identical (`image_axis_curves` defaults to `None` and is only
read with a curve axis); saved projects store the cells' image settings, not the spec, so
they load and engrave as before. The image settings dialog shows the same presets (the
table only moved).

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan, since round 48 the angle increment and – as aus / an axes over
  exactly two columns / rows – negative and bidirectional can be swept on an axis, since
  round 51 (§58) also 3D levels / Z step and the tone curve (presets or curves of a
  reopened spec – a new custom curve cannot be drawn in the test dialog). One shared test
  image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`, `… Bidirektional aus`,
  `… Winkel-Schritt 45°`, since round 51 `… Kurve S`, `… 3D-Stufen 8`, `… Z-Schritt 0.1mm`)
  are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  with the Pi's motion calibration and per-axis feed limits since round 49 (§56); the
  park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Time estimate (§56): Cartesian model – a CoreXY frame (Gestell v1) limits the motor axes
  (A = X+Y, B = X−Y), so diagonals would have to be planned per motor once that frame runs;
  Grbl's own planner on the Atomstack board (dynamic laser mode) is planned like Marlin; one
  stored calibration per Windows user (switching between two Pis shows the other's values
  until the first status arrives); jobs still do not include homing / probing / parking.
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  serial-port / barcode-scanner input placeholder (a USB scanner typing into the
  „Eingaben“ dialog works like a keyboard). Keyboard input (§57) is one value per label and
  send – copies cannot get different typed values in one job (use a CSV file), and typed
  values are kept for the session only. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests („Eingaben für den Auftrag“ at send / one-click start with a name
  tag – umlauts, long names, a USB barcode scanner typing into the dialog –, material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, bidirectional
  aus / an × speed at 3000–6000 mm/min (line offset), negative aus / an on slate / anodised
  aluminium and angle increment 0..90° × 2–3 passes, tone-curve axis (Linear / S / Tiefen+ /
  Lichter- × power on a user photo, wood / card) and 3D levels 4..16 × Z step 0..0.2 mm
  (relief depth with motorized Z), incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, the time estimate with
  the SKR calibration (2100 mm/s², 200 mm/s) against the real run time of hatch / image /
  cut jobs incl. 45° image rows and the stored value offline after a restart, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 59. Status update 2026-11-10 (review round 52)

Done this round (time estimate – approach from the park corner and parking after the job;
Canvas / Machine / Scan Probe / Materials untouched apart from a one-line tooltip text in
the path preview):

- Closed since §58 by others: none – main had no new commits since `9c06f9b`.
- Gap picked: the time estimate (#2; §56/§58 „jobs still do not include homing / probing /
  parking“). The Pi runs every Studio job from the park corner X0/Y0 and parks after it
  (`_execute_job` → `park_safezone`: Z up to the travel height, `G0 X0 Y0 F9000`, down to the
  park height 1 mm; at the start `_unpark_before_locked` lifts from 1 to 20 mm before the
  first X/Y move). The estimate counted the first positioning move as 0 mm and stopped at
  the last G-code line, so every job looked 5–10 s shorter than it runs (a 20 × 15 cm outline
  + circle at 3000 mm/min: 19.1 s shown, 27.0 s with approach / parking, +41 %; on long jobs a
  few %). LightBurn's preview time includes the travel back to the finish position and xTool
  counts the head's return. Chosen over drawing a custom tone curve in the material-test
  dialog (a reopened spec covers it) and distinct typed values per copy (a CSV file covers
  it): it corrects a number shown for every job, is self-contained in `lumacut_job` and needs
  no user decision. Homing and probing stay out: homing runs only on an unreferenced Pi, and
  the probe grid is planned on the Pi from its probe offset / tapped points (Scan Probe).
- **Model** (`lumacut_job/estimate.py`): `ParkRoutine(park_z, travel_z, feed, z_accel)` with
  mirrors of the Pi defaults (`PARK_Z_MM` 1 mm = `transport.PARK_Z_MM` / `config.park_z_mm`,
  `TRAVEL_Z_MM` 20 mm = `config.z_clearance_mm`, `PARK_FEED` F9000 as in `park_safezone`,
  `Z_ACCEL` 100 mm/s² = firmware `DEFAULT_MAX_ACCELERATION` Z). `estimate_gcode(…, park=True)`
  (default; `False` / `None` = the G-code lines only, a `ParkRoutine` for other heights):
  *approach* = lift park → travel height (skipped when the first move carries Z) + the first
  move from X0/Y0 at its own F (G0 without F = F9000) with the per-axis limit; *return* =
  lift back to the travel height when the job ended lower (relative Z from the travel height,
  absolute Z as machine Z), rapid to X0/Y0, down to the park height. Every part is planned
  rest to rest (the Pi waits with `M400`), with the active motion profile (§56: calibrated
  acceleration, Z speed). `JobEstimate` gains `approach_time_s` / `approach_length_mm`,
  `park_time_s` / `park_length_mm`, `park_included`, `program_time_s` (G-code lines, what
  `layers` adds up – unchanged), `routine_time_s`; `total_time_s` = program + routine.
  `summary()` appends „· Anfahrt/Parken 8 s“; `scope_note()` = „mit Anfahrt aus der Park-Ecke
  und Parken, ohne Referenzfahrt/Abtasten“ (without park „ohne Referenzfahrt/Fokus/Parken“).
  Cut / travel lengths and times stay the G-code's: the travel length does not grow.
- **App**: every caller uses the default, so the path preview time, „Zeit schätzen“, the
  one-click start prompt, the send message and the job history all include the routine;
  „Zeit schätzen“ names the scope instead of the fixed „(ohne Referenzfahrt/Fokus/Parken)“,
  and the path preview tooltip reads it from the estimate (`path_preview.py`, one line).
  README: „Schätzung“ bullet and the path-preview note.

Tests:

- New `tests/test_estimate_park.py` (13 tests): mirrors checked against `pi400` (park / travel
  height, park feed, firmware Z acceleration, park after every job); exact approach / return
  times (19 mm Z at 9 mm/s / 100 mm/s², 150 mm at 150 mm/s / 500 mm/s²); G-code part
  unchanged and `park=False` = old total; summary / scope note; layers stay the G-code time;
  45° approach / return; first move with its own F or Z; lift back after relative / absolute Z
  and none above the travel height; calibrated acceleration and Z speed; custom routine
  (park at travel height, higher travel height, `None`); no XY move → no routine; canvas job;
  history summary; main window: preview estimate, tooltip and „Zeit schätzen“ message.
- Adjusted: `test_job_estimate.py` (total = program + routine, `park=False` = cut + travel)
  and `test_job_selection_estimate.py` (layers add up `program_time_s`).

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2427 passed, 3 skipped**, 0 failed (14.1 min; 2414 + 13 new), first run green.

Output change for old files: none in G-code – only the estimate grows by the approach /
parking (≈ 3.5–4.5 s each way for a job in the middle of the bed with the firmware limits,
≈ 7–9 s per job); per-layer times, cut / travel lengths and the path preview's lengths are
identical to `9c06f9b`; `estimate_gcode(g, park=False)` returns the old numbers.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan, since round 48 the angle increment and – as aus / an axes over
  exactly two columns / rows – negative and bidirectional can be swept on an axis, since
  round 51 (§58) also 3D levels / Z step and the tone curve (presets or curves of a
  reopened spec – a new custom curve cannot be drawn in the test dialog). One shared test
  image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`, `… Bidirektional aus`,
  `… Winkel-Schritt 45°`, since round 51 `… Kurve S`, `… 3D-Stufen 8`, `… Z-Schritt 0.1mm`)
  are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  with the Pi's motion calibration and per-axis feed limits since round 49 (§56); the
  park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Time estimate (§56, §59): Cartesian model – a CoreXY frame (Gestell v1) limits the motor axes
  (A = X+Y, B = X−Y), so diagonals would have to be planned per motor once that frame runs;
  Grbl's own planner on the Atomstack board (dynamic laser mode) is planned like Marlin; one
  stored calibration per Windows user (switching between two Pis shows the other's values
  until the first status arrives). Since round 52 every estimate includes the approach from
  the park corner and the parking after the job, with the Pi's default heights (park 1 mm,
  travel 20 mm) – a changed `z_clearance_mm` / `park_z_mm` or thick material (travel height
  = material + 20 mm) is not read from the status yet, the approach is planned from X0/Y0
  even when the head was jogged away, and a job placed at „Aktuelle Position“ /
  „Benutzer-Ursprung“ is planned unshifted. Not included: homing (only when the Pi is not
  referenced – after connecting, a reset or an emergency stop) and the probing of the
  automatic run (the Pi plans the probe grid, `heightmap.plan_probe` – Scan Probe),
  `M400` / `M114` / `M119` round trips and the start / done melody.
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  serial-port / barcode-scanner input placeholder (a USB scanner typing into the
  „Eingaben“ dialog works like a keyboard). Keyboard input (§57) is one value per label and
  send – copies cannot get different typed values in one job (use a CSV file), and typed
  values are kept for the session only. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests („Eingaben für den Auftrag“ at send / one-click start with a name
  tag – umlauts, long names, a USB barcode scanner typing into the dialog –, material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, bidirectional
  aus / an × speed at 3000–6000 mm/min (line offset), negative aus / an on slate / anodised
  aluminium and angle increment 0..90° × 2–3 passes, tone-curve axis (Linear / S / Tiefen+ /
  Lichter- × power on a user photo, wood / card) and 3D levels 4..16 × Z step 0..0.2 mm
  (relief depth with motorized Z), incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, the time estimate with
  the SKR calibration (2100 mm/s², 200 mm/s) against the real run time of hatch / image /
  cut jobs incl. 45° image rows and – since round 52 – a stopwatch from „Start“ to the head
  lowered in the park corner (approach + parking, small and far jobs, plain start and
  one-click start without homing) and the stored value offline after a restart, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).


## 60. Status update 2026-11-10 (review round 53)

Done this round (time estimate – the Pi's travel / park height, the head position and the
origin placement; Canvas / Machine / Scan Probe / Materials untouched):

- Closed since §59 by others: none – main had no new commits since `5a91e4b`.
- Gap picked: the §59 follow-ups of the time estimate (#2). Round 52 planned the approach /
  parking with the Pi *defaults* (park 1 mm, travel 20 mm) from X0/Y0 with the job unshifted.
  The Pi plans with `machine.travel_z` = max(`z_clearance_mm`, material + 20 mm) – 6 mm
  plywood makes every lift 25 mm instead of 19 mm –, parks above a probed surface
  (`park_safezone`: max(Z, travel height, probe minimum)), starts a job from wherever the
  head is (it lifts only when the head sits low in the park corner, `_unpark_before_locked`)
  and moves a job placed at „Aktuelle Position“ / „Benutzer-Ursprung“ by the anchor offset
  (`make_placement`). LightBurn plans its preview from the job's start position / origin,
  xTool from the head. Chosen over drawing a custom tone curve in the material-test dialog
  (a reopened spec still covers it): it closes the last listed inaccuracy of a number shown
  for every job, is self-contained in `lumacut_job` and needs no user decision.
- **What the Pi reports** (checked in `pi400`, nothing invented): `/api/status` has
  `travel_z_mm` (= `machine.travel_z`, material included, ≤ Z 80), `config.park_z_mm`
  (0..20, 0 = park at travel height), `config.z_clearance_mm` (0.5..50, used when an older
  answer lacks `travel_z_mm`), `probe_minimum_z` (surface + probe clearance, null before
  probing), `position` (head X/Y/Z) and `origin.user`. Not reported: the Z acceleration and
  the park feed F9000 – they stay mirrors; the material thickness itself is not needed
  (`travel_z_mm` already contains it).
- **Model** (new `lumacut_job/park_routine.py`; `estimate.py` re-exports the constants):
  `ParkRoutine` gains `min_park_lift_z` (probe minimum) and `source`; new `JobStart(head,
  origin, anchor, target)` with `offset(gcode)` = the Pi's placement (`park_corner.
  powered_bounds` + `placement_offset`, like the park-corner check) and `parked_low()`.
  `estimate_gcode(…, start=None)` (default `active_start()`, heights `active_park()`):
  approach from the head X/Y to the shifted first move, the park-height lift only when the
  head is parked low (offline: as before); the return lifts to max(end Z, travel height,
  probe minimum) and lowers from *that* height to the park height (round 52 lowered only
  travel → park even when the job ended higher – one test value adjusted). The G-code part
  (cut / travel lengths and times, layers, bounds) stays translation invariant.
  `JobEstimate` gains `routine`, `placement_offset`, `placement_origin`, `start_xy` and
  `routine_note()` („Fahrhöhe 26 mm, Parkhöhe 1 mm (Pi) · am Ursprung „Benutzer-Ursprung“
  versetzt um X+50.0 / Y+50.0 mm“); `scope_note()` says „Anfahrt von der Kopfposition“ when
  the head is not in the park corner.
- **Status / storage**: `routine_from_status` / `start_from_status` read the fields above
  (garbage → defaults, a reduced answer keeps what is known); `ParkSync` follows the Machine
  panel's `status_changed` and the origin / anchor combos, stores travel / park height in the
  same QSettings as the motion calibration (round 49; the probe minimum belongs to one
  surface and is not stored) and keeps the start while a job or frame runs; disconnected =
  park corner, absolute. `install_park_sync` re-estimates the open path preview on a change
  (no G-code regeneration); „Zeit schätzen“ appends the routine note. README: „Schätzung“
  bullet and the known-limits note.

Tests:

- New `tests/test_estimate_park_status.py` (12 tests): the reported fields and formulas
  checked against `pi400` (`travel_z_mm`, `probe_minimum_z`, material + `TRAVEL_GAP_MM`,
  ranges, `park_safezone` max rule, parked-low lift); status parsing incl. older / reduced /
  invalid answers; 26 mm travel height (both lifts 25 mm, active routine and note); probe
  minimum (park move from Z30); head jogged away (no lift, approach 50 mm, low head lifts at
  the end); parked head = old default, head at X0/Y0 but up = no lift; user origin (offset,
  approach / park lengths, G-code part and bounds unchanged, centre anchor, unknown target /
  no laser moves unshifted); „Aktuelle Position“ (approach 0); `start_from_status` from
  `MachineStatus` and raw dicts; listeners and storage; `ParkSync` (status, origin combo,
  running job keeps the start, disconnect, offline reload); main window (status with
  `travel_z_mm` 40 re-estimates the preview without new G-code, „Zeit schätzen“ text,
  stored value).
- Adjusted: `test_estimate_park.py` (a job ending at Z30 lowers 29 mm, not 19 mm);
  `conftest.py` resets the active heights / start around every test.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2439 passed, 3 skipped**, 0 failed (13.8 min; 2427 + 12 new), first run green.

Output change for old files: none in G-code. Offline (no Pi seen) estimates are identical to
`5a91e4b` except a job ending above the travel height (lowering from its real height). With a
Pi: a 10 × 8 cm square at X100..200 / Y60..140 (3000 mm/min) – absolute 14.1 s (6.6 s
approach / parking); with 6 mm material (travel 26 mm) 15.4 s; placed at a user origin
(300, 250) 17.8 s (offset X+200 / Y+190); head jogged to the motif's start 10.8 s.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets only in the test
  dialog, a custom curve only via a reopened spec –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan, since round 48 the angle increment and – as aus / an axes over
  exactly two columns / rows – negative and bidirectional can be swept on an axis, since
  round 51 (§58) also 3D levels / Z step and the tone curve (presets or curves of a
  reopened spec – a new custom curve cannot be drawn in the test dialog). One shared test
  image per grid.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`, `… Bidirektional aus`,
  `… Winkel-Schritt 45°`, since round 51 `… Kurve S`, `… 3D-Stufen 8`, `… Z-Schritt 0.1mm`)
  are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  with the Pi's motion calibration and per-axis feed limits since round 49 (§56); the
  park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Time estimate (§56, §59, §60): Cartesian model – a CoreXY frame (Gestell v1) limits the motor axes
  (A = X+Y, B = X−Y), so diagonals would have to be planned per motor once that frame runs;
  Grbl's own planner on the Atomstack board (dynamic laser mode) is planned like Marlin; one
  stored calibration / park and travel height per Windows user (switching between two Pis
  shows the other's values until the first status arrives). Since round 53 the approach /
  parking uses the Pi's reported travel height (`travel_z_mm`, clearance or material + 20 mm),
  park height and probe minimum, starts at the reported head position and follows the
  placement at „Aktuelle Position“ / „Benutzer-Ursprung“. Still mirrored, not reported: the
  Z acceleration (firmware `M201 Z` 100 mm/s²) and the park feed F9000; a plain „Senden und
  starten“ (`start=True`, runs absolute) is estimated at the panel's origin like the later
  „Start“; the Pi's job optimizer (`job_optimize`, automatic run only) may reorder the job
  from the head position – not modelled. Not included: homing (only when the Pi is not
  referenced – after connecting, a reset or an emergency stop) and the probing of the
  automatic run (the Pi plans the probe grid, `heightmap.plan_probe` – Scan Probe),
  `M400` / `M114` / `M119` round trips and the start / done melody.
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  serial-port / barcode-scanner input placeholder (a USB scanner typing into the
  „Eingaben“ dialog works like a keyboard). Keyboard input (§57) is one value per label and
  send – copies cannot get different typed values in one job (use a CSV file), and typed
  values are kept for the session only. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests („Eingaben für den Auftrag“ at send / one-click start with a name
  tag – umlauts, long names, a USB barcode scanner typing into the dialog –, material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, bidirectional
  aus / an × speed at 3000–6000 mm/min (line offset), negative aus / an on slate / anodised
  aluminium and angle increment 0..90° × 2–3 passes, tone-curve axis (Linear / S / Tiefen+ /
  Lichter- × power on a user photo, wood / card) and 3D levels 4..16 × Z step 0..0.2 mm
  (relief depth with motorized Z), incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, the time estimate with
  the SKR calibration (2100 mm/s², 200 mm/s) against the real run time of hatch / image /
  cut jobs incl. 45° image rows and – since round 52 – a stopwatch from „Start“ to the head
  lowered in the park corner (approach + parking, small and far jobs, plain start and
  one-click start without homing; since round 53 with 6–20 mm material, a changed park
  height, the head jogged away and a job at „Benutzer-Ursprung“ / „Aktuelle Position“) and the stored value offline after a restart, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

## 61. Status update 2026-11-10 (review round 54)

Done this round (material test – drawing own tone curves; Canvas / Machine / Scan Probe /
Materials untouched):

- Closed since §60 by others: none – main had no new commits since `14b099c`.
- Gap picked: the open material-test item „a new custom curve cannot be drawn in the test
  dialog“ (§58 / §60). Since round 51 the tone curve can be swept on an axis, but only the
  eight presets (and curves of a reopened spec) were offered – the curve a user actually
  drew for a photo in the image settings could not be tested against the presets.
  LightBurn's Material Test uses the full image settings incl. the drawn curve, xTool CS
  tests the image as adjusted. For a diode laser user engraving photos on wood / card the
  tone curve is the main lever against burnt shadows, so testing *their* curve is worth more
  than the remaining candidates: MicroPDF417 / Macro PDF417 / Data Matrix EDIFACT (rarely
  needed on laser parts), node edits on a re-edited code part (Canvas-adjacent), plain
  „Senden und starten“ estimate (a seconds-level difference only when the panel origin is
  not absolute) and oblique trace crossings (cosmetic). Self-contained in `lumacut_job`, no
  hardware fact or user decision needed (no Pi / firmware change – the curve is applied in
  the Studio raster, `raster.adjust_gray`, before G-code).
- **Editor** (new `lumacut_job/material_test_curve_qt.py`): `CurveDrawDialog` reuses the image
  dialog's `CurveWidget` (drag points, tap = new point, double / right click = delete; touch
  arrives as mouse) with a „Vorlage“ combo (the presets plus the curves of the document's
  images; editing switches it to „Benutzerdefiniert“) over the histogram of the grid's
  shared test image (`grid_image_histogram`: ramp, step wedge or photo, stretched by the
  dialog's black / white point like the image dialog's curve input).
  `document_image_curves(doc, selection)` lists the non-linear curves of the document's
  images once each, selected images first, labelled „Bild N“ in document order.
- **Dialog** (`MaterialTestDialog(…, image_curves=…)`, `JobTools.material_test` passes the
  document's curves): under the curve list „Kurve zeichnen…“ (from the chosen curve; the
  result is checked, an equal listed curve is checked instead of a copy), „Bearbeiten…“ /
  double click (an own curve changes in place keeping its label and position, a preset or
  image curve stays and the result is added as „Benutzerdefiniert N“; an edit that equals
  another entry merges into it), „Entfernen“ (own curves only). Image curves appear
  unchecked as „Bild N“ in the list and in the grid-wide „Kurve“ combo of „Weitere
  Bildoptionen“, which also gets „Kurve zeichnen…“ („Benutzerdefiniert“, „… 2“). More than
  12 checked curves block OK with „höchstens 12 Kurven“ (before, the count spin silently
  clamped). The engine (`MaterialTestSpec.image_axis_curves`, labels „Eigene N“, G-code) is
  unchanged – it already accepted any valid curve list since round 51. README: material
  test bullet.

Tests:

- New `tests/test_material_test_draw_curve.py` (14 tests): draw dialog (templates incl.
  image curves, preset deduplication, histogram, edit → „Benutzerdefiniert“, linear);
  histogram of ramp / wedge photo / black-white point, missing photo; document curves
  (selected first, once, linear and non-image shapes skipped); untouched dialog = same spec
  as before and buttons follow the axis; a drawn axis curve is checked, raises the count,
  validates, labels „Eigene 1“, reaches every cell and changes the G-code (Pi guard);
  cancel / drawing an existing preset (no copy); edit in place after a reorder, edit of a
  preset adds an own curve; edit merging into an existing curve, remove (presets protected,
  count back); > 12 curves block OK; image curves in the list / combo / as templates;
  reopened spec with own + image curve unchanged; grid-wide drawn curve (combo labels, cells,
  G-code, preset re-chosen, hidden when the curve is on an axis); the real editor dialog is
  built; main window passes the selected image's curve first and the inserted grid uses it.

Full suite: `QT_QPA_PLATFORM=offscreen pytest` in one process with the Python 3.13 venv
(`/workspace/lcvenv`, PySide6 6.12): **2453 passed, 3 skipped**, 0 failed (21.8 min under load; 2439 + 14 new), first run green.

Output change for old files: none – G-code, projects and an untouched material-test dialog
give the same spec / grid as `14b099c`; a document with curved images only adds unchecked
„Bild N“ entries to the dialog's lists.

Still open:

- Job placement on the camera image (rest of #16) – Machine / Scan Probe.
- Print-and-cut (registration marks via the camera) – Machine / Scan Probe, not started.
- Rotary (cylinder engraving) – needs a rotary attachment and firmware axis mapping; user decision
  whether LumaCut hardware gets one.
- Min/max corner power – user decision on `LASER_POWER_TRAP` (see §14).
- LightBurn *Dot Mode* with a real dwell per dot – only via perforation with short cuts (needs a
  laser-on dwell on the SKR / Pi guard; not planned).
- Material test: several cells of an interval test share the same layer name (power / speed are
  equal) – the canvas labels tell them apart. Image cells: the G-code follows each cell's image
  settings, so editing a cell *layer's* power / speed in the layer panel does not change an image
  cell (the image settings dialog does). Image-cell options cover every image setting
  (mode parameters, adjustments, sharpen, levels, tone curve – presets, drawn curves and
  the curves of the document's images –, dot width, scan angle / increment,
  bidirectional, overscan); since round 43 threshold, halftone cells / angle, brightness,
  contrast, gamma, sharpen and scan angle, since round 46 also black / white point, dot
  width and overscan, since round 48 the angle increment and – as aus / an axes over
  exactly two columns / rows – negative and bidirectional can be swept on an axis, since
  round 51 (§58) also 3D levels / Z step and the tone curve, since round 54 (§61) with
  curves drawn in the test dialog and the curves of the document's images. One shared test
  image per grid (not an image of the document – the photo is loaded from a file); a curve
  taken from a document image is labelled „Eigene N“ on the canvas / in the layer name, its
  „Bild N“ name is a dialog label only.
- Material library (Materials): `lumacut_materials.testgrid.TEST_CELL_RE` is anchored
  (`…F<speed>$`), so cell layers of a grid with an image-option axis (`Test P50% F1200
  Gamma 1.2`, `… Schwarzpunkt 32`, `… Punktbreitenkorrektur 0.05mm`, `… Bidirektional aus`,
  `… Winkel-Schritt 45°`, since round 51 `… Kurve S`, `… 3D-Stufen 8`, `… Z-Schritt 0.1mm`)
  are not offered by „Preset aus Testzelle“; relaxing it to accept a trailing
  ` <Option> <Wert>` suffix (and keeping the swept image value in the preset notes) is up to
  the Materials agent. Grids without an image axis keep the classic names.
- Image: the preview shows one pixel per dot and does not model the material's real dot size /
  beam spread (needs the material library – Materials); mode and adjustment presets (incl. the
  curve presets) are not linked to the material library (Materials); no per-channel / colour
  curves (images are grey only). Scan angle: the dialog previews each pass, all passes overlaid
  (darkest dot per position) or, since round 47, their burn sum (power per dot added up and
  divided by the passes – a linear model: real wood / card darkens non-linearly with the
  absorbed energy, which needs the material library – Materials); the time estimate plans oblique rows like X
  rows (acceleration and junction deviation per `G1`, collinear row segments keep their speed),
  with the Pi's motion calibration and per-axis feed limits since round 49 (§56); the
  park-corner live box keeps using the object box (the powered
  extent of an angled image never leaves it).
- Time estimate (§56, §59, §60): Cartesian model – a CoreXY frame (Gestell v1) limits the motor axes
  (A = X+Y, B = X−Y), so diagonals would have to be planned per motor once that frame runs;
  Grbl's own planner on the Atomstack board (dynamic laser mode) is planned like Marlin; one
  stored calibration / park and travel height per Windows user (switching between two Pis
  shows the other's values until the first status arrives). Since round 53 the approach /
  parking uses the Pi's reported travel height (`travel_z_mm`, clearance or material + 20 mm),
  park height and probe minimum, starts at the reported head position and follows the
  placement at „Aktuelle Position“ / „Benutzer-Ursprung“. Still mirrored, not reported: the
  Z acceleration (firmware `M201 Z` 100 mm/s²) and the park feed F9000; a plain „Senden und
  starten“ (`start=True`, runs absolute) is estimated at the panel's origin like the later
  „Start“; the Pi's job optimizer (`job_optimize`, automatic run only) may reorder the job
  from the head position – not modelled. Not included: homing (only when the Pi is not
  referenced – after connecting, a reset or an emergency stop) and the probing of the
  automatic run (the Pi plans the probe grid, `heightmap.plan_probe` – Scan Probe),
  `M400` / `M114` / `M119` round trips and the start / done melody.
- Speed unit: material preset labels in the material library (Materials, `presets.py`) and
  error messages still print mm/min; in/min is not offered for speeds.
- Park corner: the live check uses object boxes as the base (slightly stricter than the powered
  G-code extent at send, e.g. text with small glyphs or images with white margins; image scan
  offset is not added); with „Aktuelle Position“ the zone follows the head only as often as the
  Pi status updates; near the corner a large hatched job is planned synchronously on a change
  (≈ 1 s at ~1500 hatched objects, cached afterwards).
- Fill: fill grouping does not cross layers; overscan is clamped to the cutting area, not to the
  real machine travel (user decision, see §31); the free start corner is not yet checked on the
  Windows app with real hardware.
- Scan offset: one table for the machine (no per-layer / per-material override, no link to the
  material library – Materials); the fill preview shows pass 1 only (shifted lines appear
  ≈ 1.5 s after a change at ~1500 hatched objects, the canvas stays usable meanwhile); the test
  pattern is not yet automatically evaluated via the camera.
- Trace: true Bézier objects in the document (Canvas); oblique thick crossings still split into two
  nearby junctions.
- Variable text: „Text in Pfade“ converts the template literally (Canvas, `pathops_ui.py`); the
  canvas label is a hint under the object, the object itself still shows the template; no
  serial-port / barcode-scanner input placeholder (a USB scanner typing into the
  „Eingaben“ dialog works like a keyboard). Keyboard input (§57) is one value per label and
  send – copies cannot get different typed values in one job (use a CSV file), and typed
  values are kept for the session only. The advanced counter / CSV row lives in memory
  outside the undo history only until the history is cleared (new / opened project) – after
  a reopen the saved project values apply, so an advanced but unsaved project still loses
  its values when closed without saving (the close prompt asks, as before).
- Generated objects:
  - No canvas context-menu entry for „Code bearbeiten“ (Canvas).
  - Node edits on a code part are discarded when it is re-edited.
  - A font not installed on the machine falls back in the dialog.
- 2D codes: Aztec has no rune symbols and no structured append; Data Matrix EDIFACT mode not
  supported; PDF417 has no Macro PDF417 (structured append) and no MicroPDF417. GS1 Digital
  Link: no compressed form (DL compression); QR: no ECI for
  other character sets than UTF-8 (not needed – UTF-8 covers everything), no structured append;
  Micro QR has no Kanji mode (UTF-8 byte mode covers Japanese text at a higher bit cost).
- Studio `PROBE_HEAD_MAX` vs. configured travel (Machine / Scan Probe).
- Flaky timing test `test_machine_reliability.py::EmergencyStopClientTests::test_retries_stop_at_the_deadline`
  failed once in a full run under load (passes alone) – Machine. Same for
  `test_machine_origin.py::OriginPanelTests::test_user_origin_from_head_and_placed_start_and_frame`
  (round 46: „ok start“ wait timed out once under load, green alone and in the rerun).
- Windows hardware tests („Eingaben für den Auftrag“ at send / one-click start with a name
  tag – umlauts, long names, a USB barcode scanner typing into the dialog –, material test grids interval × power and passes × speed on wood /
  card incl. the labels, focus × power / focus × speed grids (relative Z) on wood / card with
  motorized Z, image test cells (Floyd / Jarvis / greyscale / halftone ramps, step wedges and
  user photos × power × speed and × line interval, incl. non-default threshold / halftone
  cells and angle / 3D levels with Z step / brightness / contrast / gamma / negative, and with
  the „Weitere Bildoptionen“ sharpen / black-white point / S-curve / dot width / scan angle
  45° / unidirectional / reduced overscan, and image-option axes – threshold sweep
  64..192, halftone angle 0..45° and cells 20..60 /Zoll, gamma 0.6..1.8 × contrast,
  brightness × power and scan angle 0..90° × speed, black point 0..64 × white point,
  dot width 0..0.1 mm × power and overscan 0..5 mm × speed – line ends –, bidirectional
  aus / an × speed at 3000–6000 mm/min (line offset), negative aus / an on slate / anodised
  aluminium and angle increment 0..90° × 2–3 passes, tone-curve axis (Linear / S / Tiefen+ /
  Lichter- × power on a user photo, wood / card; since round 54 a drawn curve and the curve
  of a photo in the document against the presets, the editor by touch on the Windows tablet) and 3D levels 4..16 × Z step 0..0.2 mm
  (relief depth with motorized Z), incl. the labels
  and layer names) on
  wood / card against real photo engravings with the chosen setting, QR codes with umlauts (ECI 26) and Japanese Kanji text
  with phone scanners (iOS / Android camera apps) and a handheld scanner, Micro QR M1–M4 on
  small parts with phone / handheld scanners, the live park-corner warning with
  lead-ins / kerf against a real refusal, speeds typed in mm/s on the layer panel and dialogs
  against the sent G-code, the park-corner zone against a real refusal incl. the live warning and
  the placed zone at „Aktuelle Position“ / „Benutzer-Ursprung“, the time estimate with
  the SKR calibration (2100 mm/s², 200 mm/s) against the real run time of hatch / image /
  cut jobs incl. 45° image rows and – since round 52 – a stopwatch from „Start“ to the head
  lowered in the park corner (approach + parking, small and far jobs, plain start and
  one-click start without homing; since round 53 with 6–20 mm material, a changed park
  height, the head jogged away and a job at „Benutzer-Ursprung“ / „Aktuelle Position“) and the stored value offline after a restart, photos at scan angles 30° / 45° /
  90° and with a 90° angle increment (cross raster, against the „Alle Durchgänge
  übereinander“ and the „aufaddiert (Brennsumme)“ preview, incl. greyscale photos with 2–3
  passes at 0° / 45° / 90°) on wood against the X-only raster (line
  quality of oblique `G1` rows at 3000–6000 mm/min on the SKR), photos with tone curves (S-curve,
  shadows lifted) against the real engraving, auto-levelled photos with the new black /
  white point, photos with black / white point and the rotated dialog preview against the real
  engraving, photos with brightness / contrast / gamma / sharpen and Sketch engravings
  on wood / card incl. the dialog preview, Jarvis / Stucki / Sierra / halftone / newsprint photos
  and dot width correction at 3000–6000 mm/min, GS1 QR / Digital Link codes with a GS1 scanner
  and a phone camera (incl. short-name aliases `/gtin/`, `/lot/`, `?exp=`), plain-text QR codes
  with mixed segments, scan offset test pattern and
  compensated bidirectional hatch / image incl. the shifted fill preview and its background
  planning on the Windows app, fill overscan – line ends even at 2–5 mm on wood / card – and
  2-opt block order, fill grouping and inside-out offset fill, offset fill, cut options incl.
  overcut and perforation, PDF import, trace, QR / Micro QR / barcode / Data Matrix / Aztec /
  PDF417 readability incl. edited, rectangular, DMRE, compact 15 × 15, GS1 and (compact) PDF417
  codes with a real scanner, park-corner refusal, variable text / CSV merge over several sends
  incl. the canvas value labels and Ctrl+Z / Strg+Y between sends (no repeated serial number), rebuilt exe).

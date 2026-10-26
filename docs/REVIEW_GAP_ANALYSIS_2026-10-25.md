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
- Min/max power with speed-dependent corner power (LightBurn) – needs a planner change and checking
  what the SKR's Marlin build supports (`LASER_POWER_TRAP` / inline power); not started.
- Trace: no centre-line trace and no curve fitting (outlines are polygons). Masks with more than
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

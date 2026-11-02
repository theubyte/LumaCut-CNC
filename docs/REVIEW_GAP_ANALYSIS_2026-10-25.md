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

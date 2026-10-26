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
| 2 | Job time + distance estimate | LB Preview / XCS yes | none | **done** (`lumacut_job.estimate`, accel + junction model, Alt+P) | high | S | Review |
| 3 | Framing (box + rubber band, laser off) | LB / XCS yes | none | **done** (toolbar "Rahmen", Ctrl+Shift+F / Alt+Shift+F) | very high (no red-dot pointer; camera only) | S | Review → Machine for a dedicated frame API |
| 4 | Material test grid (power × speed) | LB / XCS yes | none | **done** (`lumacut_job.material_test`, one undo step) | very high (every new material) | S | Review; Materials to consume results |
| 5 | Raster engraving (image object, dithers, line interval, bidirectional, overscan, scan offset) | LB / XCS yes | none | **done** (engine `lumacut_job.raster` + image object on the canvas with settings dialog; images are engraved before vectors in the same job) | very high | M (canvas object + UI) | Canvas (image item) + Review (engine) |
| 6 | 3D / depth: sliced passes from height map, Z step per slice | LB 3D slice Galvo-only; XCS 3D | none | **done** for image objects (mode "3D" in the image dialog → `sliced_depth_gcode`, ≤3 mm total drop); combined with focus compensation it is refused safely (Z words) | medium-high (relief in wood/slate) | M for UI | Canvas/Materials + Review |
| 7 | Zoom: anchor at event position, pinch, fit selection, trackpad | LB / XCS yes | wheel only, QCursor anchor | **done** (`canvas_view` + Ctrl+Shift+A) | high (daily use) | S | Canvas (minimal edit) |
| 8 | Material library: presets by material + thickness, assign/link to layers, combo box wired | LB yes / XCS yes (xTool materials) | placeholder combo | **done** (Materials agent: `lumacut_materials`, material section in the layers panel) | very high | M | **Materials agent** |
| 9 | Import SVG/DXF/PNG/JPG/PDF | LB / XCS yes | none in native | **done** for SVG/DXF/PNG/JPG/BMP (`lumacut_import`, Datei › Importieren Ctrl+I, drag-and-drop, mm conversion, one undo step, clamped to the 360×340 mm work area); PDF open | very high | M | Canvas |
| 10 | Workflow wizard scan → detect → probe → focus → job → park, focus compensation applied on send | n/a (LB has camera overlay; XCS auto-focus + camera) | pieces exist separately; compensation not hooked into "Design senden" | **done** (`lumacut_workflow`: panel "Ablauf" Home → Scan → Markieren → Probe → Fokus → Rahmen → Auftrag → Parken; status per step, skip, precondition checks; uses the existing panel actions, focus compensation via `prepare_job_gcode`) | very high (USP) | M | Scan Probe + Machine; Review can wire the send path |
| 11 | Fill / hatch for vectors (Fill mode, line interval, cross-hatch) | LB / XCS yes | none | open (hatch helper exists in material_test) | high | M | Canvas |
| 12 | Kerf offset, tabs/bridges, lead-in/out | LB yes / XCS partial | none | open | medium (diodes have small kerf; tabs useful) | M | Review (planner) |
| 13 | Boolean ops, node editing, offset, arrays | LB / XCS yes | polygon only | open | medium | L | Canvas |
| 14 | Preview of G-code path (travel lines, order animation) | LB / XCS yes | none | open (estimate only) – not done in this pass | medium | M | Canvas overlay + Review |
| 15 | Air assist M8/M9 per layer | LB yes | none (Pi allows M7/M8/M9) | **not feasible on this machine** – see §8 | medium (if relay installed) | S | Materials/layer field + gcode |
| 16 | Origin options (current position / user origin), job placement on camera | LB yes / XCS yes | absolute only | open | medium | M | Machine |
| 17 | Job queue, autosave / crash recovery | LB autosave yes | none | **autosave/recovery done** (`lumacut_session`, every 60 s, crash recovery on start); queue open | medium | S–M | Canvas (autosave), Machine (queue) |
| 18 | Raster throughput to SKR (Pi-side streaming / line compression) | n/a | risk noted in plan | open | high for photos | L | Pi / Machine |

## 4. Focus areas

**Zoom.** LightBurn zooms with the wheel at the pointer, Ctrl+=/- and Ctrl+0 (page), and
Ctrl+Shift+A (frame selection). XCS uses Ctrl+wheel for zoom and plain wheel to scroll, plus
fit-width/height/screen. LumaCut now has explicit anchoring at the event position (wheel and
pinch), pixel-delta trackpads, clamped 0.4–60 px/mm, fit-to-selection (Ctrl+Shift+A, falls back
to all objects, then the work area). Kept the LightBurn convention (plain wheel = zoom). Still
open: zoom % field / fit-width buttons, Shift+wheel horizontal pan.

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
- **Dedicated frame op** (Top-10 #6) was completed by the Machine side (`op=frame`).

**Air assist (#15) – not feasible as specified.** The Pi guard does allow M7/M8/M9, but on this
machine those codes are already wired to other outputs: **M7 = lights, M8 = exhaust (Absaugung),
M9 = both off**. Emitting M8/M9 per layer would toggle the exhaust mid-job (M9 would even switch
off the extraction during cutting). Air assist needs its own output (e.g. a free SKR fan/heater
pin with a dedicated M-code such as `M106 P<n>`) plus a matching guard rule on the Pi before a
layer field makes sense.

Still open: path preview overlay (#14), kerf/tabs/lead-in (#12), vector fill/hatch (#11), PDF
import, job queue, raster streaming (#18). Error diffusion on very large images is slow
(pure-Python inner loop).


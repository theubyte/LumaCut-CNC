# LumaCut Studio (Preview 0.1)

Independent software track alongside LightBurn; existing controller firmware remains untouched.

## Start
Open `index.html` in a current Chromium-based browser (Edge/Chrome) on Windows. No build tooling needed.

## Implemented
- Dark responsive operator UI sized for the LumaCut machine
- Import local SVG paths, circles, ellipses, lines, polygons, rects
- Geometric preview, size and position control (390 × 370 mm preview with 30 mm reserved top zone)
- 2D vector sampling, cut path estimate, power/feed/pass parameters
- Download draft GRBL-style G-code for offline review
- Offline-only operation: no network connection and no machine commands

## Limitations (important)
Not production ready. The prototype does NOT stream jobs, home the machine, probe material, control Z, raster engrave, handle DXF/DWG, compute kerf or perform collision/interlock checks. A file exported here must not be run on a real machine without a tested postprocessor and safety review. SVG transforms and nested transformed groups are intentionally rejected; fonts and embedded bitmaps are unsupported. The preview uses top-left positive-Y-down coordinates, which may NOT match the controller machine/work coordinate convention. G-code export is *not* a substitute for a tested machine job pipeline.

## Target architecture
- UI: Tauri 2 + TypeScript/SVG canvas
- Core: Rust document parser + geometry engine + job planner, deterministic unit tests
- Machine adapter: separate Raspberry Pi 400 service talking via USB serial to SKR grblHAL, explicit protocol state machine, one serial owner
- Machine capability handshake, controller-state polling rate limits, configurable calibration/profile
- Planned closed-loop job stages: validate -> XY home -> safe Z -> probe bed/reference -> probe workpiece -> compute surface/focus -> dry run -> explicitly armed laser job -> park
- Hardware independent safety interlock and emergency stop required; motion/laser commands never sent by browser preview
- Import pipeline SVG/DXF, optional DWG via supported converter, raster PNG/JPEG with image engraving planner
- Multi-pass cutting with measured material thickness and validated step-down/focus strategy
- Project autosave, undo/redo, layers/colors, nested shape operations, process profiles, camera overlay

## Development priorities
1. Verified SKR/Pi protocol contract, units and axis mapping; sample logs and fixtures.
2. Tested geometry parser and deterministic G-code/postprocessor based on actual machine coordinates.
3. Safe job state machine, endstops and interlock handling, serialized connection ownership.
4. Material probe / Z reference calibration / focus and pass planning.
5. Native Windows application packaging and feature-complete editing.

All work resides under `software/lumacut-studio/` to avoid modifying LightBurn-related firmware.

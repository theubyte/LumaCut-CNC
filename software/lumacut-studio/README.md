# LumaCut Studio v0.2 (early preview)

This is an early feature preview, NOT a validated laser job sender. Build via GitHub Actions workflow `lumacut-studio-windows.yml`; a green workflow must be confirmed before claiming a working Windows installer.

## New editor features
- Draw rectangle, ellipse, line, freehand and text objects on the 390 x 370 preview bed
- Create and rename multiple process layers; assign cut/engrave designation and per-layer power, feed and passes
- Import JPG, PNG, WebP images for placement preview (raster engraving toolpaths NOT implemented)
- Save and load LumaCut JSON design projects
- Locally editable material library, with profile values applied to selected layer
- Optional camera live view, plus uncalibrated rectangular still capture

## Unimplemented / hardware-dependent
- Camera-to-bed homography and pixel-to-millimetre registration
- Controller-driven fiducial marker engraving and automatic optical calibration
- Moving-camera mosaics and area-dependent scanning
- Bitmap dithering/raster G-code, reliable layer-scheduled job planning
- DXF/DWG support, robust transforms, full editing operations, tested machine streaming
- Safe Z probing, homing, interlocks and hardware state-machine integration
- In-app signed autoupdate

**Do not run generated G-code on the machine.** The earlier draft vector export does not include newer editor layers and raster artwork, and uses non-validated coordinates. It is retained only for offline prototype experimentation. Do not assume vector or raster import equals machine-ready output.

---

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

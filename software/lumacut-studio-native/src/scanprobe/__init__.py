"""LumaCut Studio – Kachel-Scan, Objekterkennung und Multi-Bereich-Probing.

Der Kern ist bewusst Qt-frei (nur numpy + OpenCV), damit er auf Windows in
Studio, auf dem Pi 400 und in Tests identisch läuft. Die Qt-Anbindung liegt in
``scanprobe.qt_bridge`` und wird nur importiert, wenn PySide6 vorhanden ist.

Ablauf (siehe docs/LUMACUT_STUDIO_PLAN_2026-10-25.md):
1. Kachel-Scan bei fester Höhe  -> ``TileScanner`` / ``stitch_mosaic``
2. Objekte erkennen             -> ``detect_objects``
3. Auto-Probe nur dieser Bereiche -> ``plan_probe_job`` / ``ProbeRunner``
4. Eigenes Höhenmesh je Bereich -> ``HeightMap`` / ``HeightMapSet``
5. Adaptive Fokuskorrektur      -> ``apply_focus_compensation``
"""
from .geometry import (
    MachineLimits, Rect, Polygon, DEFAULT_LIMITS, PROBE_OFFSET_MM,
)
from .control import RunControl, Progress, Cancelled
from .interfaces import MachineInterface, CameraInterface, ProbeInterface
from .calibration import CameraCalibration
from .tile_scan import TilePlan, Tile, CapturedTile, plan_tiles, TileScanner
from .stitch import Mosaic, stitch_mosaic
from .detection import DetectedObject, detect_objects
from .probe_plan import (
    ProbeSettings, ProbeArea, ProbePoint, ProbeJob, plan_probe_job,
    areas_from_objects, areas_from_design_bounds,
)
from .heightmap import HeightMap, HeightMapSet
from .probing import ProbeRunner, ProbeResult
from .compensation import FocusSettings, CompensationReport, apply_focus_compensation
from .heatmap import render_heatmap
from .workflow import ScanProbeWorkflow, WorkflowResult

__all__ = [name for name in dir() if not name.startswith("_")]
__version__ = "0.1.0"

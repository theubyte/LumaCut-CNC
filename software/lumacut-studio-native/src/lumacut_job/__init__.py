"""Job planning on top of the canvas export (Qt-free except :mod:`qt_tools`).

- :mod:`planner`    cut order: inner shapes first, reduced travel, best start point
- :mod:`estimate`   job time estimate from G-code, bounding box / rubber-band framing
- :mod:`material_test`  power x speed test grid as canvas layers
- :mod:`raster`     grayscale raster and sliced depth (2.5D) engraving planner

All coordinates are *machine* mm (safezone offset already applied by
``lumacut_canvas.export.job_layers``). Nothing here talks to the machine.
"""

from .estimate import JobEstimate, estimate_gcode, format_duration, frame_gcode, job_bounds
from .planner import optimize_layers, optimized_document_gcode

__all__ = [
    "JobEstimate", "estimate_gcode", "format_duration", "frame_gcode", "job_bounds",
    "optimize_layers", "optimized_document_gcode",
]

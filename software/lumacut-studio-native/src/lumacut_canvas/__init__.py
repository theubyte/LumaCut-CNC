"""LumaCut-Canvas: Vektor-Editor für die 360 × 340 mm Arbeitsfläche.

Öffentliche, Qt-freie Schnittstelle (für Job-, Scan- und Maschinenmodule):

- :class:`Document`, :class:`Layer`, :class:`Shape`, :class:`Geometry`
- :func:`save_document`, :func:`load_document`
- :func:`to_machine` / :func:`from_machine` (einzige Stelle mit Safezone-Versatz)

Die Qt-Oberfläche liegt in :mod:`lumacut_canvas.editor` (``CanvasEditor``) und
:mod:`lumacut_canvas.layers_panel` (``LayersPanel``).
"""

from .document_io import FILE_SUFFIX, load_document, save_document
from .model import Document, Geometry, Layer, Shape
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, from_machine, to_machine

__all__ = [
    "Document", "Geometry", "Layer", "Shape", "Rect",
    "save_document", "load_document", "FILE_SUFFIX",
    "to_machine", "from_machine", "WORK_WIDTH_MM", "WORK_HEIGHT_MM",
]

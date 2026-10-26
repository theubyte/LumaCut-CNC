"""LumaCut-Canvas: Vektor-Editor für die 360 × 340 mm Arbeitsfläche.

Öffentliche, Qt-freie Schnittstelle (für Job-, Scan- und Maschinenmodule):

- :class:`Document`, :class:`Layer`, :class:`Shape`, :class:`Geometry`
- :func:`save_document`, :func:`load_document`
- :func:`to_machine` / :func:`from_machine` (einzige Stelle mit Safezone-Versatz
  und Spiegelung: Nullpunkt oben rechts, siehe :mod:`lumacut_canvas.workarea`)
- :func:`screen_to_user` / :func:`user_to_screen` (Anzeige-mm für Lineale, Felder)

Die Qt-Oberfläche liegt in :mod:`lumacut_canvas.editor` (``CanvasEditor``) und
:mod:`lumacut_canvas.layers_panel` (``LayersPanel``).
"""

from .document_io import FILE_SUFFIX, load_document, save_document
from .model import Document, Geometry, Layer, Shape
from .workarea import (ORIGIN_TOP_RIGHT, WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, from_machine,
                       screen_to_user, to_machine, user_to_screen)

__all__ = [
    "Document", "Geometry", "Layer", "Shape", "Rect",
    "save_document", "load_document", "FILE_SUFFIX",
    "to_machine", "from_machine", "WORK_WIDTH_MM", "WORK_HEIGHT_MM",
    "screen_to_user", "user_to_screen", "ORIGIN_TOP_RIGHT",
]
